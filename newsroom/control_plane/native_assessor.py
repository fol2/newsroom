"""Autonomous, fail-closed assessment of independently acquired evidence."""

from __future__ import annotations

import json
import sqlite3
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Callable

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
)
from newsroom.control_plane.evidence import (
    ClaimAuthorityClass,
    EVID_012_POLICY_VERSION,
    EVIDENCE_GATE_POLICY_VERSION,
    EvidencePackage,
    GOVERNED_CLAIM_POLICY_VERSION,
    GovernedClaimStatus,
    ORIGINALITY_POLICY_VERSION,
    Evid012QualificationTest,
    evidence_package_value,
)
from newsroom.increment10.editorial import SourceCurrentness
from newsroom.increment10.evidence import (
    EvidencePackageError,
    _base_package,
    _package_from_value,
)

from .model_usage import (
    InvocationAllocation,
    InvocationEfficiencyPolicy,
    ModelUsageIntegrityError,
    ModelUsageService,
    UsageStatus,
    WorkEnvelope,
    WorkloadClass,
    _allocation_from_record,
    _envelope_from_record,
    _policy_for_allocation,
    _require_reported_telemetry,
    _terminal_from_record,
)

from .native_evidence import (
    AcquiredEvidence,
    AcquiredSourceAssessment,
    IndependentEvidenceAssessment,
    NativeEvidenceError,
    NativeEvidenceHold,
    rights_eligibility_digest,
    NativeEvidenceSource,
    SourceAuthorityAssessment,
)
from .writer import (
    CONT_DISABLED_CAPABILITIES,
    CONT_PRIMARY_COMMAND_FLAGS,
    CONT_PRIMARY_MODEL,
    CONT_PRIMARY_PROVIDER,
    CONT_PRIMARY_REASONING,
    WriterDispatchError,
    _run_grok_json,
    cont_writer_implementation_identity,
    read_grok_command_semantic_version,
)
from .cycle import _complete_writer_usage

VERSION = "newsroom.native-evidence-assessor.v1"
ROUTE = "NATIVE_EVIDENCE_ASSESSOR"
CONTEXT_IDENTITY = "native-evidence-exact-acquisition-v1"
CONFIG_IDENTITY = "native-evidence-assessor-grok-hermetic-command-v1"
CONTEXT_MANIFEST_SCHEMA_VERSION = (
    "newsroom.native-evidence-assessor.context-manifest.v1"
)
SYSTEM = (
    "You are a one-turn evidence extraction transform. Use only the supplied "
    "candidate and exact source bytes. Return JSON matching the schema. Never "
    "claim facts, translations or authority absent from an exact source excerpt."
)
_STRING = {"type": "string"}
_STRINGS = {"type": "array", "items": _STRING}
_PAIRS = {
    "type": "array",
    "items": {
        "type": "array", "items": _STRING, "minItems": 2, "maxItems": 2,
    },
}
_CLAIM_FIELDS = {
    "claim_id": _STRING, "claim": _STRING, "passage_index": {"type": "integer"},
    "supporting_excerpt": _STRING, "source_ids": _STRINGS,
    "source_record_ids": _STRINGS, "source_authority_decision_ids": _STRINGS,
    "rights_decision_ids": _STRINGS,
    "dependency_evidence_ids": _STRINGS, "evidential_origin_ids": _STRINGS,
    "authority_class": {"enum": ["RESPONSIBLE_PRIMARY", "INDEPENDENT_RELIABLE"]},
    "authority_scope": _STRING,
    "status": {"enum": [item.value for item in GovernedClaimStatus]},
    "attribution": _STRING, "rendered_assertion_zh_hant_hk": _STRING,
    "claim_role": {"enum": ["HEADLINE", "SUBSTANTIVE", "CONTEXT"]},
    "semantic_relation_evidence_id": _STRING,
    "localised_factual_expressions": _PAIRS,
    "named_entity_evidence": {
        "type": "array", "items": {
            "type": "array", "items": _STRING, "minItems": 3, "maxItems": 3,
        },
    },
    "named_entities": _STRINGS, "rendered_named_entities": _STRINGS,
    "quotations": _STRINGS, "certainty": {"const": "CONFIRMED"},
    "originality_basis": {"const": "FACTUAL_REWRITE_REQUIRED"},
    "originality_policy_version": {"const": ORIGINALITY_POLICY_VERSION},
    "admitted_use": {"const": "PUBLICATION_EVIDENCE"},
    "policy_version": {"const": GOVERNED_CLAIM_POLICY_VERSION},
}
_PACKAGE_FIELDS = {
    "candidate_id": _STRING, "hypothesis_id": _STRING, "signal_ids": _STRINGS,
    "lead_ids": _STRINGS, "source_ids": _STRINGS, "observation_digests": _STRINGS,
    "passages": _STRINGS, "substantive_new_information": _STRINGS,
    "governed_claims": {"type": "array", "items": {
        "type": "object", "properties": _CLAIM_FIELDS,
        "required": list(_CLAIM_FIELDS), "additionalProperties": False,
    }},
    "qualification_evidence": {"type": "array", "items": {
        "type": "object", "properties": {
            "test": {"enum": [item.value for item in Evid012QualificationTest]},
            "governed_claim_id": _STRING,
            "qualification_record_id": _STRING, "test_evidence": _PAIRS,
            "policy_version": {"const": EVID_012_POLICY_VERSION},
        },
        "required": [
            "test", "governed_claim_id", "qualification_record_id",
            "test_evidence", "policy_version",
        ],
        "additionalProperties": False,
    }},
    "selection_rationale": _STRING, "geography": _STRINGS, "categories": _STRINGS,
    "evidence_gate_results": _PAIRS,
    "evidence_gate_evidence": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "gate": {"enum": [
                "CLAIM_TRACEABILITY", "EVIDENCE_SUFFICIENCY", "SOURCE_AUTHORITY",
            ]},
            "result": {"const": "PASS"},
            "governed_claim_ids": _STRINGS,
            "policy_version": {"const": EVIDENCE_GATE_POLICY_VERSION},
        },
        "required": ["gate", "result", "governed_claim_ids", "policy_version"],
        "additionalProperties": False,
    }},
    "freshness_result": _STRING, "integrity_result": _STRING,
    "explicit_exclusions": _STRINGS,
    "resolved_evidence_records": _PAIRS,
}
def _record_schema(kind: str, fields: dict[str, object]) -> dict[str, object]:
    properties = {
        "record_id": _STRING, "record_type": {"const": kind},
        "governed_claim_id": _STRING, **fields,
    }
    return {
        "type": "object", "properties": properties,
        "required": list(properties), "additionalProperties": False,
    }


_ASSESSMENT_RECORD = {"oneOf": [
    _record_schema("SEMANTIC_RELATION_EVIDENCE", {
        "source_modality": _STRING, "rendered_modality": _STRING,
        "source_polarity": _STRING, "rendered_polarity": _STRING,
        "relation": _STRING, "claim_digest": _STRING,
        "rendered_assertion_digest": _STRING,
    }),
    _record_schema("QUALIFICATION_EVIDENCE", {
        "test": _STRING,
        "test_evidence": _PAIRS, "policy_version": _STRING,
        "evidence_span_digest": _STRING, "source_record_ids": _STRINGS,
    }),
    _record_schema("NAMED_ENTITY_EVIDENCE", {
        "text": _STRING, "rendered_text": _STRING, "entity_type": _STRING,
        "canonical_entity_id": _STRING, "rendered_span_digest": _STRING,
        "policy_version": _STRING, "evidence_span_digest": _STRING,
        "source_record_ids": _STRINGS,
    }),
]}
SCHEMA = {
    "type": "object",
    "required": ["package", "assessment_records"],
    "additionalProperties": False,
    "properties": {
        "package": {
            "type": "object", "properties": _PACKAGE_FIELDS,
            "required": list(_PACKAGE_FIELDS), "additionalProperties": False,
        },
        "assessment_records": {"type": "array", "items": _ASSESSMENT_RECORD},
    },
}
SCHEMA_DIGEST = digest_bytes(canonical_json_bytes(SCHEMA))
INTEGRITY = (
    "ACCESS_COMPLETE",
    "ENCODING_VALID",
    "EXTRACTION_COMPLETE",
    "NOT_PAYWALL_FRAGMENT",
    "NOT_TRUNCATED",
    "VERSION_UNAMBIGUOUS",
)


@dataclass(frozen=True, slots=True)
class NativeAssessmentExecution:
    text: str
    usage: dict[str, object]


@dataclass(frozen=True, slots=True)
class RetainedAssessorContractFailure:
    envelope_id: str
    invocation_id: str
    allocation_digest: str
    terminal_digest: str
    context_manifest_digest: str


class NativeAssessmentUsage:
    """Persist exact native-assessor intent, dispatch and terminal usage."""

    def __init__(
        self,
        service: ModelUsageService,
        policy: InvocationEfficiencyPolicy,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    ) -> None:
        if (
            type(service) is not ModelUsageService
            or type(policy) is not InvocationEfficiencyPolicy
            or policy.workload_class is not WorkloadClass.NATIVE_EVIDENCE_ASSESSOR
            or (policy.provider, policy.route, policy.model, policy.reasoning)
            != (
                CONT_PRIMARY_PROVIDER,
                ROUTE,
                CONT_PRIMARY_MODEL,
                CONT_PRIMARY_REASONING,
            )
            or policy.prompt_contract_version != VERSION
            or policy.output_schema_digest != SCHEMA_DIGEST
            or policy.command_flags != CONT_PRIMARY_COMMAND_FLAGS
            or policy.context_manifest_schema_version
            != CONTEXT_MANIFEST_SCHEMA_VERSION
            or policy.disabled_capabilities != CONT_DISABLED_CAPABILITIES
            or CONTEXT_IDENTITY not in policy.allowed_context_identities
            or CONFIG_IDENTITY not in policy.allowed_config_identities
            or not policy.qualified
        ):
            raise NativeEvidenceError("qualified native assessment usage is required")
        self._service = service
        self._policy = policy
        self._clock = clock
        service.register_policy(policy)

    def begin(self, candidate, base, prompt: str) -> InvocationAllocation:
        now = self._clock().astimezone(UTC)
        prompt_bytes = prompt.encode()
        package_bytes = canonical_json_bytes(evidence_package_value(base))
        command_version = read_grok_command_semantic_version()
        implementation_revision, implementation_clean = (
            cont_writer_implementation_identity()
        )
        policy = self._policy
        if (
            command_version != policy.command_semantic_version
            or implementation_revision != policy.implementation_revision
            or implementation_clean is not True
        ):
            raise NativeEvidenceError("native assessment runner identity differs")
        manifest = {
            "schema_version": CONTEXT_MANIFEST_SCHEMA_VERSION,
            "provider": policy.provider,
            "route": policy.route,
            "model": policy.model,
            "reasoning": policy.reasoning,
            "command_semantic_version": command_version,
            "command_flags": list(CONT_PRIMARY_COMMAND_FLAGS),
            "disabled_capabilities": list(CONT_DISABLED_CAPABILITIES),
            "implementation_revision": implementation_revision,
            "implementation_worktree_clean": True,
            "prompt_contract_version": VERSION,
            "prompt_bytes": len(prompt_bytes),
            "prompt_digest": digest_bytes(prompt_bytes),
            "schema_digest": SCHEMA_DIGEST,
            "output_schema_digest": SCHEMA_DIGEST,
            "system_digest": digest_bytes(SYSTEM.encode()),
            "evidence_package_digest": base.digest,
            "evidence_package_bytes": len(package_bytes),
            "context_identity": CONTEXT_IDENTITY,
            "config_identity": CONFIG_IDENTITY,
            "one_turn": True,
            "exact_input": True,
            "skills_enabled": False,
            "tools_enabled": False,
            "mcp_enabled": False,
            "prior_message_count": 0,
            "skill_count": 0,
            "tool_count": 0,
            "mcp_server_count": 0,
            "mcp_tool_count": 0,
        }
        manifest["request_digest"] = digest_canonical(
            {
                key: manifest[key]
                for key in (
                    "provider",
                    "route",
                    "model",
                    "reasoning",
                    "command_semantic_version",
                    "command_flags",
                    "implementation_revision",
                    "system_digest",
                    "prompt_digest",
                    "output_schema_digest",
                )
            }
        )
        manifest["context_manifest_digest"] = digest_canonical(manifest)
        cycle_id = digest_bytes(
            canonical_json_bytes([candidate.version_id, base.digest])
        )
        envelope = WorkEnvelope.create(
            cycle_id=cycle_id,
            workload_class=WorkloadClass.NATIVE_EVIDENCE_ASSESSOR,
            admitted_at=now,
            admission_decision_id=None,
            candidate_id=candidate.candidate_id,
            hypothesis_digest=candidate.governing_manifest.canonical_digest,
            evidence_package_digest=base.digest,
            ingest_id=None,
            graphiti_attempt_id=None,
        )
        self._service.open_envelope(envelope)
        self._service.retain_context_manifest(manifest)
        allocation = InvocationAllocation.create(
            envelope_id=envelope.envelope_id,
            cycle_id=cycle_id,
            leaf_ordinal=1,
            workload_class=WorkloadClass.NATIVE_EVIDENCE_ASSESSOR,
            invocation_policy_digest=policy.canonical_digest,
            provider=policy.provider,
            route=policy.route,
            model=policy.model,
            reasoning=policy.reasoning,
            prompt_contract_version=VERSION,
            prompt_bytes=len(prompt_bytes),
            prompt_digest=digest_bytes(prompt_bytes),
            request_digest=str(manifest["request_digest"]),
            output_schema_digest=SCHEMA_DIGEST,
            max_output_tokens=policy.max_output_tokens,
            context_manifest_digest=str(manifest["context_manifest_digest"]),
            context_identity=CONTEXT_IDENTITY,
            config_identity=CONFIG_IDENTITY,
            one_turn=True,
            exact_input=True,
            skills_enabled=False,
            tools_enabled=False,
            mcp_enabled=False,
            prior_message_count=0,
            allocated_at=now,
            recovery_deadline_at=now + timedelta(minutes=5),
            parent_invocation_id=None,
        )
        self._service.allocate(allocation, owner_emergency_stop=False)
        return allocation

    def mark_dispatch(self, allocation: InvocationAllocation) -> datetime:
        dispatched_at = self._clock().astimezone(UTC)
        self._service.observe_transport(
            invocation_id=allocation.invocation_id,
            observed_at=dispatched_at,
            state="DISPATCH_STARTED",
            evidence_digest=allocation.request_digest,
        )
        return dispatched_at

    def complete(
        self,
        allocation: InvocationAllocation,
        *,
        outcome: str,
        execution: NativeAssessmentExecution | None,
        provider_dispatched: bool,
        dispatch_at: datetime | None = None,
        failure_class: str | None = None,
    ) -> None:
        now = self._clock().astimezone(UTC)
        _complete_writer_usage(
            self._service,
            allocation,
            outcome=outcome,
            failure_class=failure_class,
            usage=None if execution is None else execution.usage,
            dispatch_at=dispatch_at if provider_dispatched else None,
            completed_at=now,
            provider_dispatched=provider_dispatched,
            policy=self._policy,
        )

    def retained_output_contract_failure(
        self, candidate: object
    ) -> RetainedAssessorContractFailure | None:
        """Prove one settled, candidate-bound assessor contract failure."""

        candidate_id = getattr(candidate, "candidate_id", None)
        version_id = getattr(candidate, "version_id", None)
        manifest = getattr(candidate, "governing_manifest", None)
        hypothesis_digest = getattr(manifest, "canonical_digest", None)
        if not all(type(value) is str and value for value in (
            candidate_id, version_id, hypothesis_digest,
        )):
            return None
        connection = sqlite3.connect(f"file:{self._service.path}?mode=ro", uri=True)
        try:
            rows = connection.execute(
                "SELECT envelope_id,cycle_id,workload_class,admitted_at,"
                "canonical_digest,record_json FROM model_work_envelopes "
                "WHERE workload_class=?",
                (WorkloadClass.NATIVE_EVIDENCE_ASSESSOR.value,),
            ).fetchall()
            matches: list[RetainedAssessorContractFailure] = []
            for row in rows:
                try:
                    envelope_record = json.loads(row[5])
                    envelope = _envelope_from_record(envelope_record)
                except (TypeError, ValueError, ModelUsageIntegrityError):
                    return None
                if tuple(row[:5]) != (
                    envelope.envelope_id,
                    envelope.cycle_id,
                    envelope.workload_class.value,
                    envelope_record["admitted_at"],
                    envelope.canonical_digest,
                ) or envelope.as_record() != envelope_record:
                    return None
                if (
                    envelope.candidate_id != candidate_id
                    or envelope.hypothesis_digest != hypothesis_digest
                ):
                    continue
                if envelope.evidence_package_digest is None or envelope.cycle_id != digest_bytes(
                    canonical_json_bytes([version_id, envelope.evidence_package_digest])
                ):
                    continue
                allocation_rows = connection.execute(
                    "SELECT invocation_id,envelope_id,cycle_id,leaf_ordinal,"
                    "workload_class,policy_digest,provider,route,model,request_digest,"
                    "parent_invocation_id,allocated_at,canonical_digest,record_json "
                    "FROM model_invocation_allocations WHERE envelope_id=?",
                    (envelope.envelope_id,),
                ).fetchall()
                if len(allocation_rows) != 1:
                    return None
                allocation_row = allocation_rows[0]
                try:
                    allocation_record = json.loads(allocation_row[13])
                    allocation = _allocation_from_record(allocation_record)
                except (TypeError, ValueError, ModelUsageIntegrityError):
                    return None
                if tuple(allocation_row[:13]) != (
                    allocation.invocation_id,
                    allocation.envelope_id,
                    allocation.cycle_id,
                    allocation.leaf_ordinal,
                    allocation.workload_class.value,
                    allocation.invocation_policy_digest,
                    allocation.provider,
                    allocation.route,
                    allocation.model,
                    allocation.request_digest,
                    allocation.parent_invocation_id,
                    allocation_record["allocated_at"],
                    allocation.canonical_digest,
                ) or allocation.as_record() != allocation_record or (
                    allocation.envelope_id != envelope.envelope_id
                    or allocation.cycle_id != envelope.cycle_id
                    or allocation.leaf_ordinal != 1
                    or allocation.workload_class
                    is not WorkloadClass.NATIVE_EVIDENCE_ASSESSOR
                ):
                    return None
                context_row = connection.execute(
                    "SELECT context_manifest_digest,provider,route,"
                    "evidence_package_digest,record_json "
                    "FROM model_invocation_context_manifests "
                    "WHERE context_manifest_digest=?",
                    (allocation.context_manifest_digest,),
                ).fetchone()
                terminal_row = connection.execute(
                    "SELECT terminal_digest,invocation_id,usage_status,outcome,"
                    "failure_class,completed_at,record_json "
                    "FROM model_invocation_terminals WHERE invocation_id=?",
                    (allocation.invocation_id,),
                ).fetchone()
                transport_rows = connection.execute(
                    "SELECT observation_digest,invocation_id,observed_at,state,"
                    "evidence_digest,record_json FROM model_transport_observations "
                    "WHERE invocation_id=? ORDER BY observed_at,observation_digest",
                    (allocation.invocation_id,),
                ).fetchall()
                if context_row is None or terminal_row is None:
                    return None
                try:
                    policy = _policy_for_allocation(connection, allocation)
                    policy_record_row = connection.execute(
                        "SELECT record_json FROM model_invocation_policies "
                        "WHERE canonical_digest=?",
                        (allocation.invocation_policy_digest,),
                    ).fetchone()
                    if policy_record_row is None:
                        return None
                    policy_record = json.loads(policy_record_row[0])
                    policy._validate()
                    context = json.loads(context_row[4])
                    terminal_record = json.loads(terminal_row[6])
                    terminal = _terminal_from_record(terminal_record)
                    transport_values = tuple(
                        json.loads(item[5]) for item in transport_rows
                    )
                except (TypeError, ValueError, ModelUsageIntegrityError):
                    return None
                if type(policy_record) is not dict:
                    return None
                unsigned_policy = dict(policy_record)
                retained_policy_digest = unsigned_policy.pop(
                    "canonical_digest", None
                )
                if (
                    policy_record != policy.as_record()
                    or retained_policy_digest != policy.canonical_digest
                    or digest_canonical(unsigned_policy) != policy.canonical_digest
                ):
                    return None
                try:
                    terminal_policy_breach = self._service._validate_terminal(
                        terminal,
                        allocation.workload_class,
                        policy,
                        requested_max_output_tokens=allocation.max_output_tokens,
                    )
                except ModelUsageIntegrityError:
                    return None
                unsigned_context = dict(context)
                retained_context_digest = unsigned_context.pop(
                    "context_manifest_digest", None
                )
                if (
                    policy.canonical_digest
                    != allocation.invocation_policy_digest
                    or policy.workload_class
                    is not WorkloadClass.NATIVE_EVIDENCE_ASSESSOR
                    or not policy.qualified
                    or (
                        allocation.provider,
                        allocation.route,
                        allocation.model,
                        allocation.reasoning,
                        allocation.prompt_contract_version,
                        allocation.output_schema_digest,
                    )
                    != (
                        policy.provider,
                        policy.route,
                        policy.model,
                        policy.reasoning,
                        policy.prompt_contract_version,
                        policy.output_schema_digest,
                    )
                    or (
                        allocation.one_turn,
                        allocation.exact_input,
                        allocation.skills_enabled,
                        allocation.tools_enabled,
                        allocation.mcp_enabled,
                        allocation.prior_message_count,
                        allocation.context_identity,
                        allocation.config_identity,
                    )
                    != (
                        policy.one_turn,
                        policy.exact_input,
                        policy.skills_enabled,
                        policy.tools_enabled,
                        policy.mcp_enabled,
                        policy.prior_message_count,
                        CONTEXT_IDENTITY,
                        CONFIG_IDENTITY,
                    )
                    or allocation.context_identity
                    not in policy.allowed_context_identities
                    or allocation.config_identity
                    not in policy.allowed_config_identities
                    or tuple(context_row[:4]) != (
                        retained_context_digest,
                        context.get("provider"),
                        context.get("route"),
                        context.get("evidence_package_digest"),
                    )
                    or retained_context_digest != allocation.context_manifest_digest
                    or digest_canonical(unsigned_context) != retained_context_digest
                    or context.get("evidence_package_digest")
                    != envelope.evidence_package_digest
                    or context.get("request_digest") != allocation.request_digest
                    or context.get("prompt_digest") != allocation.prompt_digest
                    or context.get("provider") != allocation.provider
                    or context.get("route") != allocation.route
                    or context.get("model") != allocation.model
                    or context.get("reasoning") != allocation.reasoning
                    or context.get("implementation_revision")
                    != policy.implementation_revision
                    or context.get("implementation_worktree_clean") is not True
                    or context.get("command_semantic_version")
                    != policy.command_semantic_version
                    or context.get("command_flags") != list(policy.command_flags)
                    or context.get("disabled_capabilities")
                    != list(policy.disabled_capabilities)
                    or context.get("prompt_contract_version")
                    != policy.prompt_contract_version
                    or context.get("context_identity")
                    != allocation.context_identity
                    or context.get("config_identity")
                    != allocation.config_identity
                    or context.get("one_turn") != allocation.one_turn
                    or context.get("exact_input") != allocation.exact_input
                    or context.get("skills_enabled") != allocation.skills_enabled
                    or context.get("tools_enabled") != allocation.tools_enabled
                    or context.get("mcp_enabled") != allocation.mcp_enabled
                    or context.get("prior_message_count")
                    != allocation.prior_message_count
                    or context.get("output_schema_digest") != SCHEMA_DIGEST
                    or context.get("schema_digest") != policy.output_schema_digest
                    or tuple(terminal_row[:6]) != (
                        terminal.terminal_digest,
                        terminal.invocation_id,
                        terminal.usage_status.value,
                        terminal.outcome,
                        terminal.failure_class,
                        terminal_record["completed_at"],
                    )
                    or terminal.as_record() != terminal_record
                    or terminal.invocation_id != allocation.invocation_id
                    or terminal.usage_status is not UsageStatus.REPORTED
                    or terminal.outcome != "ASSESSOR_VALIDATION_FAILED"
                    or terminal.failure_class != "ASSESSMENT_VALIDATION_FAILED"
                    or terminal.dispatch_at is None
                    or terminal.pre_dispatch_zero_proved
                    or terminal.policy_breach is not None
                    or terminal_policy_breach is not None
                    or len(transport_rows) != 1
                    or tuple(transport_rows[0][:5]) != (
                        transport_values[0].get("observation_digest"),
                        allocation.invocation_id,
                        transport_values[0].get("observed_at"),
                        "DISPATCH_STARTED",
                        allocation.request_digest,
                    )
                    or transport_values[0].get("invocation_id")
                    != allocation.invocation_id
                    or transport_values[0].get("state") != "DISPATCH_STARTED"
                    or transport_values[0].get("evidence_digest")
                    != allocation.request_digest
                    or transport_values[0].get("observed_at")
                    != terminal_record.get("dispatch_at")
                    or digest_canonical(
                        {
                            key: value
                            for key, value in transport_values[0].items()
                            if key != "observation_digest"
                        }
                    )
                    != transport_values[0].get("observation_digest")
                    or connection.execute(
                        "SELECT 1 FROM model_usage_reconciliations "
                        "WHERE invocation_id=? AND "
                        "json_extract(record_json,'$.policy_breach') IS NOT NULL",
                        (allocation.invocation_id,),
                    ).fetchone()
                    is not None
                ):
                    return None
                try:
                    _require_reported_telemetry(connection, terminal)
                except ModelUsageIntegrityError:
                    return None
                matches.append(RetainedAssessorContractFailure(
                    envelope.envelope_id,
                    allocation.invocation_id,
                    allocation.canonical_digest,
                    terminal.terminal_digest,
                    allocation.context_manifest_digest,
                ))
            return matches[0] if len(matches) == 1 else None
        finally:
            connection.close()


class AutonomousNativeEvidenceAssessor:
    """Dispatch one fixed-schema transform, then prove its output locally."""

    def __init__(
        self,
        dispatch: Callable[[str], NativeAssessmentExecution] | None = None,
        *,
        usage: NativeAssessmentUsage | None = None,
        dispatch_fence: Callable[[], AbstractContextManager] | None = None,
    ) -> None:
        default_dispatch = dispatch is None
        dispatch = dispatch or _dispatch_grok
        if not callable(dispatch):
            raise NativeEvidenceError("native assessment transport is required")
        self._dispatch = dispatch
        if default_dispatch and usage is None:
            raise NativeEvidenceError("native assessment usage authority is required")
        if usage is not None and dispatch_fence is None:
            raise NativeEvidenceError("native assessment dispatch fence is required")
        if dispatch_fence is not None and not callable(dispatch_fence):
            raise NativeEvidenceError("native assessment dispatch fence differs")
        self._usage = usage
        self._dispatch_fence = dispatch_fence or nullcontext

    def __call__(self, candidate, base, sources, acquired):
        for source, result in zip(sources, acquired, strict=True):
            if (
                result.currentness_basis
                != "AUTHORITATIVE_CURRENT_CONTENT_ENDPOINT"
                or not result.text_only
                or result.rights_eligibility_digest
                != rights_eligibility_digest(
                    source.rights, body_digest=result.body_digest,
                    transport_digest=result.transport_evidence_digest,
                    exclusion_signals=result.exclusion_signals, text_only=result.text_only,
                )
                or not result.licence_attribution
                or result.exclusion_signals
                or source.rights.decision != "PERMITTED"
                or source.rights.permitted_use != "PUBLICATION_EVIDENCE"
            ):
                raise NativeEvidenceHold(
                    "SOURCE_POLICY_FACTS_HOLD", source.unit.source_id
                )
        prompt = canonical_json_bytes(
            {
                "contract": VERSION,
                "candidate_version": json.loads(candidate.canonical_bytes),
                "base_package": evidence_package_value(base),
                "sources": [
                    {
                        "source_id": source.unit.source_id,
                        "source_definition_version_digest": (
                            source.source_version.canonical_digest
                        ),
                        "rights_receipt_id": source.rights.record_id,
                        "dependency_receipt_id": source.dependency.record_id,
                        "acquisition_receipt_id": result.receipt_digest,
                        "publication_time": result.publication_time,
                        "source_updated_time": result.source_updated_time,
                        "retrieval_time": result.retrieval_time,
                        "body": result.body.decode("utf-8"),
                    }
                    for source, result in zip(sources, acquired, strict=True)
                ],
                "output_schema_digest": SCHEMA_DIGEST,
            }
        ).decode()
        request = prompt
        allocation = (
            None if self._usage is None else self._usage.begin(candidate, base, request)
        )
        execution = None
        dispatch_at = None
        try:
            with self._dispatch_fence():
                if allocation is not None:
                    dispatch_at = self._usage.mark_dispatch(allocation)
                execution = self._dispatch(request)
            result = self._validated_execution(
                execution, candidate, base, sources, acquired
            )
        except WriterDispatchError as exc:
            if allocation is not None:
                self._usage.complete(
                    allocation, outcome="ASSESSOR_PROVIDER_FAILED",
                    execution=None,
                    provider_dispatched=dispatch_at is not None,
                    dispatch_at=dispatch_at,
                    failure_class=exc.failure_class,
                )
            raise
        except EvidencePackageError as exc:
            if allocation is None or execution is None:
                raise
            self._usage.complete(
                allocation,
                outcome="ASSESSOR_VALIDATION_FAILED",
                execution=execution,
                provider_dispatched=dispatch_at is not None,
                dispatch_at=dispatch_at,
                failure_class="ASSESSMENT_VALIDATION_FAILED",
            )
            if self._usage.retained_output_contract_failure(candidate) is None:
                raise
            raise NativeEvidenceHold(
                "ASSESSOR_OUTPUT_CONTRACT_HOLD",
                (
                    sources[0].unit.source_id
                    if sources
                    else str(getattr(candidate, "candidate_id", "unknown-candidate"))
                ),
            ) from exc
        except BaseException:
            if allocation is not None:
                self._usage.complete(
                    allocation,
                    outcome=(
                        "ASSESSOR_PROVIDER_FAILED"
                        if execution is None
                        else "ASSESSOR_VALIDATION_FAILED"
                    ),
                    execution=execution,
                    provider_dispatched=dispatch_at is not None,
                    dispatch_at=dispatch_at,
                    failure_class=(
                        "UNKNOWN_PROVIDER_FAILURE"
                        if execution is None
                        else "ASSESSMENT_VALIDATION_FAILED"
                    ),
                )
            raise
        if allocation is not None:
            self._usage.complete(
                allocation, outcome="ASSESSOR_ACCEPTED", execution=execution,
                provider_dispatched=True, dispatch_at=dispatch_at,
            )
        return result

    @staticmethod
    def _validated_execution(execution, candidate, base, sources, acquired):
        if type(execution) is not NativeAssessmentExecution:
            raise NativeEvidenceHold("ASSESSOR_TRANSPORT_HOLD", sources[0].unit.source_id)
        value = _document(execution.text)
        package = _package_from_value(value.get("package"))
        if _base_package(package) != base:
            raise NativeEvidenceHold("ASSESSOR_BASE_BINDING_HOLD", sources[0].unit.source_id)
        source_ids = {source.unit.source_id for source in sources}
        receipt_by_source = {
            source.unit.source_id: result.receipt_digest
            for source, result in zip(sources, acquired, strict=True)
        }
        for claim in package.governed_claims:
            if (
                claim.passage_index >= len(acquired)
                or claim.supporting_excerpt
                not in acquired[claim.passage_index].body.decode("utf-8")
                or set(claim.source_ids) - source_ids
                or set(claim.source_record_ids)
                != {receipt_by_source[item] for item in claim.source_ids}
            ):
                raise NativeEvidenceHold(
                    "ASSESSOR_CLAIM_BINDING_HOLD", sources[0].unit.source_id
                )
        source_by_id = {source.unit.source_id: source for source in sources}
        authority = []
        governed_claims = []
        for claim in package.governed_claims:
            selected = tuple(source_by_id[item] for item in claim.source_ids)
            source_roles = tuple(
                tuple(
                    assignment
                    for assignment in source.source_version.request.roles
                    if assignment.role.value
                    in {"ORIGINATING_AUTHORITY", "RESPONSIBLE_OPERATOR"}
                )
                for source in selected
            )
            if any(len(roles) != 1 for roles in source_roles):
                raise NativeEvidenceHold(
                    "SOURCE_AUTHORITY_HOLD", claim.source_ids[0]
                )
            roles = tuple(items[0] for items in source_roles)
            scope = "; ".join(sorted({item.purpose for item in roles}))
            decisions = tuple(
                SourceAuthorityAssessment.create(
                    source_id=source.unit.source_id,
                    governed_claim_id=claim.claim_id,
                    decision="ADMITTED",
                    authority_class="RESPONSIBLE_PRIMARY",
                    authority_scope=role.purpose,
                    evidence_digest=digest_bytes(
                        canonical_json_bytes(
                            {
                                "claim_digest": digest_bytes(claim.claim.encode()),
                                "source_definition_version_digest": (
                                    source.source_version.canonical_digest
                                ),
                                "role_assignments": [
                                    item.canonical_value()
                                    for item in source.source_version.request.roles
                                ],
                            }
                        )
                    ),
                )
                for source, role in zip(selected, roles, strict=True)
            )
            authority.extend(decisions)
            governed_claims.append(
                replace(
                    claim,
                    source_record_ids=tuple(
                        receipt_by_source[item] for item in claim.source_ids
                    ),
                    source_authority_decision_ids=tuple(
                        item.record_id for item in decisions
                    ),
                    rights_decision_ids=tuple(
                        source_by_id[item].rights.record_id
                        for item in claim.source_ids
                    ),
                    dependency_evidence_ids=tuple(
                        source_by_id[item].dependency.record_id
                        for item in claim.source_ids
                    ),
                    evidential_origin_ids=tuple(
                        source_by_id[item].dependency.evidential_origin_id
                        for item in claim.source_ids
                    ),
                    authority_class=ClaimAuthorityClass.RESPONSIBLE_PRIMARY,
                    authority_scope=scope,
                )
            )
        assessments = tuple(
            AcquiredSourceAssessment(
                source.unit.source_id,
                SourceCurrentness(
                    source.unit.source_id,
                    source.unit.authority.definition_id,
                    source.source_version.canonical_digest,
                    "CURRENT_VERSION",
                    result.publication_time,
                    result.retrieval_time,
                    None,
                    result.source_updated_time,
                    result.transport_evidence_digest,
                    result.transport_evidence_digest,
                    "PASS",
                    "CURRENT_CONTENT_API_VERSION_CONFIRMED",
                ),
                tuple((name, "PASS") for name in INTEGRITY),
            )
            for source, result in zip(sources, acquired, strict=True)
        )
        claims_by_id = {claim.claim_id: claim for claim in governed_claims}
        assessment_records = []
        for record in _objects(value.get("assessment_records")):
            if record.get("record_type") in {
                "SOURCE_RECORD",
                "SOURCE_AUTHORITY_DECISION",
                "RIGHTS_DECISION",
                "DEPENDENCY_EVIDENCE",
            }:
                raise NativeEvidenceHold(
                    "ASSESSOR_AUTHORITY_RECORD_HOLD", sources[0].unit.source_id
                )
            if "source_record_ids" in record:
                claim = claims_by_id.get(record.get("governed_claim_id"))
                if claim is None:
                    raise NativeEvidenceHold(
                        "ASSESSOR_CLAIM_BINDING_HOLD", sources[0].unit.source_id
                    )
                record = {
                    **record,
                    "source_record_ids": list(claim.source_record_ids),
                }
            assessment_records.append(record)
        return IndependentEvidenceAssessment(
            assessments,
            tuple(authority),
            package.substantive_new_information,
            tuple(governed_claims),
            package.qualification_evidence,
            tuple(assessment_records),
            package.selection_rationale,
            package.geography,
            package.categories,
            package.explicit_exclusions,
        )



def _document(text: str) -> dict[str, object]:
    def unique(pairs):
        value = dict(pairs)
        if len(value) != len(pairs):
            raise NativeEvidenceError("native assessment output has duplicate fields")
        return value

    try:
        value = json.loads(text, object_pairs_hook=unique)
    except (TypeError, json.JSONDecodeError) as exc:
        raise NativeEvidenceError("native assessment output is malformed") from exc
    if type(value) is not dict:
        raise NativeEvidenceError("native assessment output is malformed")
    if set(value) != set(SCHEMA["required"]):
        raise NativeEvidenceError("native assessment output fields differ")
    return value


def _objects(value: object) -> tuple[dict[str, object], ...]:
    if type(value) is not list or any(type(item) is not dict for item in value):
        raise NativeEvidenceError("native assessment records differ")
    return tuple(value)


def _dispatch_grok(prompt: str) -> NativeAssessmentExecution:
    execution = _run_grok_json(
        prompt,
        schema=SCHEMA,
        system_instruction=SYSTEM,
        temporary_prefix="newsroom-grok-evidence-assessor-",
    )
    return NativeAssessmentExecution(execution.text, execution.usage)
