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
    EvidencePackage,
    GOVERNED_CLAIM_POLICY_VERSION,
    GovernedClaimStatus,
    NAMED_ENTITY_POLICY_VERSION,
    ORIGINALITY_POLICY_VERSION,
    Evid012QualificationTest,
    bounded_named_entities,
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
    _assessment_id,
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
from .store import append_ledger

VERSION = "newsroom.native-evidence-assessor.v4"
ROUTE = "NATIVE_EVIDENCE_ASSESSOR"
CONTEXT_IDENTITY = "native-evidence-exact-acquisition-v1"
CONFIG_IDENTITY = "native-evidence-assessor-grok-hermetic-command-v1"
CONTEXT_MANIFEST_SCHEMA_VERSION = (
    "newsroom.native-evidence-assessor.context-manifest.v1"
)
SYSTEM = (
    "You are a one-turn evidence extraction transform. Use only the supplied "
    "candidate and exact source bytes. Return JSON matching the schema. Translate "
    "or localise only facts present in an exact source excerpt; never add facts or "
    "authority absent from that evidence. Preserve every named entity used in the "
    "claim with exact source-excerpt evidence and its source spelling unchanged in the "
    "rendered claim; do not annotate or translate named entities. Localised factual "
    "expressions are limited to equivalent source/rendered pairs present in both "
    "texts: D Month [YYYY] [at HH:MM] dates and equivalent Chinese dates; numeric "
    "or one-to-ten word durations in hours/minutes and equivalent Chinese durations "
    "with at least 60 minutes where used as qualification evidence; "
    "or counts of schools, hospitals, clinics, buses or roads in those number forms. "
    "Return no qualification_evidence when no supported qualification test applies; "
    "never invent an AFFIRMED qualification merely to populate that array."
)
_STRING = {"type": "string"}
_STRINGS = {"type": "array", "items": _STRING}
_PAIRS = {
    "type": "array",
    "items": {
        "type": "array", "items": _STRING, "minItems": 2, "maxItems": 2,
    },
}
_SEMANTIC_RELATION_FIELDS = {
    "source_modality": _STRING,
    "rendered_modality": _STRING,
    "source_polarity": _STRING,
    "rendered_polarity": _STRING,
    "relation": _STRING,
}


def _qualification_schema(
    test: Evid012QualificationTest, fields: dict[str, object]
) -> dict[str, object]:
    evidence = {
        "type": "object",
        "properties": fields,
        "required": list(fields),
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "test": {"const": test.value},
            "governed_claim_id": _STRING,
            "test_evidence": evidence,
            "policy_version": {"const": EVID_012_POLICY_VERSION},
        },
        "required": [
            "test", "governed_claim_id", "test_evidence", "policy_version",
        ],
        "additionalProperties": False,
    }


_AFFIRMED = {"const": "AFFIRMED"}
_MATERIAL_SPAN = _STRING
_QUALIFICATION_SCHEMAS = (
    _qualification_schema(Evid012QualificationTest.LAW_RIGHT_STATUS_POLICY, {
        "change_kind": {"enum": [
            "LAW", "RIGHT", "STATUS", "OFFICIAL_DEADLINE", "PUBLIC_POLICY",
        ]},
        "event_polarity": _AFFIRMED,
        "change_relation": {"const": "NEW_OR_CHANGED_STATE"},
        "material_relation_span": _MATERIAL_SPAN,
        "new_state": _STRING,
    }),
    _qualification_schema(Evid012QualificationTest.SAFETY_OR_PUBLIC_HEALTH, {
        "effect_class": {"enum": [
            "INJURY_RISK", "PUBLIC_HEALTH_WARNING", "EVACUATION",
            "MATERIAL_EXPOSURE",
        ]},
        "event_polarity": _AFFIRMED,
        "effect_relation": {"const": "MATERIAL_EFFECT"},
        "material_relation_span": _MATERIAL_SPAN,
        "affected_group": _STRING,
    }),
    _qualification_schema(Evid012QualificationTest.ESSENTIAL_SERVICE_DISRUPTION, {
        "service_kind": {"enum": [
            "TRANSPORT", "UTILITY", "SCHOOL", "WORKPLACE", "LOCALITY",
        ]},
        "event_polarity": _AFFIRMED,
        "duration_relation": {"const": "DISRUPTION_DURATION"},
        "duration_minutes": _STRING,
        "affected_group": _STRING,
    }),
    _qualification_schema(Evid012QualificationTest.HOUSEHOLD_PRACTICAL_EFFECT, {
        "domain": {"enum": [
            "MONEY", "WORK", "HOUSING", "EDUCATION", "HEALTHCARE",
            "UK_HONG_KONG_TRAVEL",
        ]},
        "event_polarity": _AFFIRMED,
        "effect_relation": {"const": "MATERIAL_PRACTICAL_EFFECT"},
        "material_relation_span": _MATERIAL_SPAN,
        "practical_effect": _STRING,
    }),
    _qualification_schema(Evid012QualificationTest.OFFICIAL_ACTION_OR_DEADLINE, {
        "action_class": {"enum": [
            "INSTRUCTION", "PROCESS", "OFFICIAL_DEADLINE",
        ]},
        "event_polarity": _AFFIRMED,
        "action_relation": {"const": "NEW_OR_CHANGED_OFFICIAL_ACTION"},
        "material_relation_span": _MATERIAL_SPAN,
        "reader_action": _STRING,
    }),
    _qualification_schema(Evid012QualificationTest.EXCEPTIONAL_PUBLIC_IMPORTANCE, {
        "importance_class": {"enum": [
            "HONG_KONG_WIDE", "INTERNATIONAL_EMERGENCY", "CONSTITUTIONAL_CHANGE",
        ]},
        "event_polarity": _AFFIRMED,
        "importance_relation": {"const": "CURRENT_EXCEPTIONAL_IMPORTANCE"},
        "material_relation_span": _MATERIAL_SPAN,
        "affected_group": _STRING,
    }),
)
_CLAIM_FIELDS = {
    "claim_id": _STRING, "claim": _STRING, "passage_index": {"type": "integer"},
    "supporting_excerpt": _STRING, "source_ids": _STRINGS,
    "status": {"enum": [item.value for item in GovernedClaimStatus]},
    "rendered_assertion_zh_hant_hk": _STRING,
    "claim_role": {"enum": ["HEADLINE", "SUBSTANTIVE", "CONTEXT"]},
    "semantic_relation": {
        "type": "object",
        "properties": _SEMANTIC_RELATION_FIELDS,
        "required": list(_SEMANTIC_RELATION_FIELDS),
        "additionalProperties": False,
    },
    "localised_factual_expressions": _PAIRS,
    "quotations": _STRINGS, "certainty": {"const": "CONFIRMED"},
    "originality_basis": {"const": "FACTUAL_REWRITE_REQUIRED"},
    "originality_policy_version": {"const": ORIGINALITY_POLICY_VERSION},
    "admitted_use": {"const": "PUBLICATION_EVIDENCE"},
    "policy_version": {"const": GOVERNED_CLAIM_POLICY_VERSION},
}
_PACKAGE_FIELDS = {
    "substantive_new_information": _STRINGS,
    "governed_claims": {"type": "array", "items": {
        "type": "object", "properties": _CLAIM_FIELDS,
        "required": list(_CLAIM_FIELDS), "additionalProperties": False,
    }},
    "qualification_evidence": {"type": "array", "items": {
        "oneOf": list(_QUALIFICATION_SCHEMAS),
    }},
    "selection_rationale": _STRING, "geography": _STRINGS, "categories": _STRINGS,
    "explicit_exclusions": _STRINGS,
}
SCHEMA = {
    "type": "object",
    "required": ["package"],
    "additionalProperties": False,
    "properties": {
        "package": {
            "type": "object", "properties": _PACKAGE_FIELDS,
            "required": list(_PACKAGE_FIELDS), "additionalProperties": False,
        },
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
_ASSESSMENT_RESULT_KIND = "NATIVE_ASSESSMENT_RESULT"
_ASSESSMENT_RESULT_SCHEMA_VERSION = "newsroom.native-assessment-result.v1"
_MAX_RETAINED_RESULT_BYTES = 256 * 1024


def _semantic_record_id(claim_id: str, claim: str, rendered: str) -> str:
    return _assessment_id("SEMANTIC_RELATION", claim_id, claim, rendered)


def _qualification_record_id(
    claim_id: str, test: str, test_evidence: object
) -> str:
    return _assessment_id(
        "QUALIFICATION", claim_id, test, digest_canonical(test_evidence)
    )


def _named_entity_record_id(
    claim_id: str, text: str, entity_type: str, rendered: str
) -> str:
    return _assessment_id("NAMED_ENTITY", claim_id, text, entity_type, rendered)


def _contract_hold_reason(error: EvidencePackageError) -> str:
    current: BaseException | None = error
    while current is not None:
        message = str(current)
        if "named entit" in message:
            return "ASSESSOR_NAMED_ENTITY_CONTRACT_HOLD"
        if "localised factual expression" in message:
            return "ASSESSOR_LOCALISATION_CONTRACT_HOLD"
        if "qualification" in message:
            return "ASSESSOR_QUALIFICATION_CONTRACT_HOLD"
        current = current.__cause__
    return "ASSESSOR_OUTPUT_CONTRACT_HOLD"


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
        connection = service._connection()
        try:
            if connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ledger'"
            ).fetchone() is None:
                raise NativeEvidenceError(
                    "native assessment diagnostic ledger is required"
                )
        finally:
            connection.close()
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

    def retain_result(
        self,
        allocation: InvocationAllocation,
        execution: NativeAssessmentExecution,
        *,
        dispatch_at: datetime,
    ) -> bool:
        """Retain bounded diagnostic output without admitting its contents."""

        if (
            type(allocation) is not InvocationAllocation
            or type(execution) is not NativeAssessmentExecution
            or type(execution.text) is not str
            or type(execution.usage) is not dict
        ):
            raise NativeEvidenceError("native assessment result binding differs")
        raw = execution.text.encode("utf-8")
        result_digest = digest_bytes(raw)
        connection = self._service._connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            allocation_row = connection.execute(
                "SELECT invocation_id,envelope_id,cycle_id,leaf_ordinal,"
                "workload_class,policy_digest,provider,route,model,request_digest,"
                "parent_invocation_id,allocated_at,canonical_digest,record_json "
                "FROM model_invocation_allocations "
                "WHERE invocation_id=?",
                (allocation.invocation_id,),
            ).fetchone()
            policy = _policy_for_allocation(connection, allocation)
            dispatch_rows = connection.execute(
                "SELECT observed_at,evidence_digest,record_json "
                "FROM model_transport_observations "
                "WHERE invocation_id=? AND state='DISPATCH_STARTED'",
                (allocation.invocation_id,),
            ).fetchall()
            if allocation_row is None or len(dispatch_rows) != 1:
                raise NativeEvidenceError("native assessment result lacks dispatch authority")
            allocation_record = json.loads(allocation_row[13])
            retained_allocation = _allocation_from_record(allocation_record)
            dispatch_record = json.loads(dispatch_rows[0][2])
            if (
                retained_allocation != allocation
                or tuple(allocation_row[:13]) != (
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
                )
                or retained_allocation.invocation_policy_digest
                != self._policy.canonical_digest
                or policy.as_record() != self._policy.as_record()
                or dispatch_record.get("invocation_id") != allocation.invocation_id
                or dispatch_record.get("state") != "DISPATCH_STARTED"
                or dispatch_record.get("evidence_digest") != allocation.request_digest
                or digest_canonical({
                    key: value for key, value in dispatch_record.items()
                    if key != "observation_digest"
                }) != dispatch_record.get("observation_digest")
                or tuple(dispatch_rows[0][:2]) != (
                    dispatch_record.get("observed_at"), allocation.request_digest,
                )
                or datetime.fromisoformat(str(dispatch_record.get("observed_at")))
                != dispatch_at
            ):
                raise NativeEvidenceError("native assessment result authority differs")
            retained = len(raw) <= _MAX_RETAINED_RESULT_BYTES
            observed_at = self._clock().astimezone(UTC)
            if observed_at < dispatch_at:
                raise NativeEvidenceError(
                    "native assessment result precedes dispatch"
                )
            record = {
                "schema_version": _ASSESSMENT_RESULT_SCHEMA_VERSION,
                "invocation_id": allocation.invocation_id,
                "allocation_digest": allocation.canonical_digest,
                "invocation_policy_digest": allocation.invocation_policy_digest,
                "request_digest": allocation.request_digest,
                "observed_at": observed_at.isoformat(timespec="microseconds"),
                "dispatch_at": dispatch_record["observed_at"],
                "result_digest": result_digest,
                "result_bytes": len(raw),
                "result_text": execution.text if retained else None,
                "retention_outcome": "RETAINED" if retained else "OVERSIZED",
            }
            rows = connection.execute(
                "SELECT payload_digest,payload_json FROM ledger WHERE kind=? "
                "AND json_extract(payload_json,'$.invocation_id')=?",
                (_ASSESSMENT_RESULT_KIND, allocation.invocation_id),
            ).fetchall()
            if rows:
                if len(rows) != 1:
                    raise NativeEvidenceError(
                        "conflicting native assessment result replay"
                    )
                retained_record = json.loads(rows[0][1])
                comparable = dict(retained_record)
                comparable.pop("observed_at", None)
                expected = dict(record)
                expected.pop("observed_at")
                if (
                    digest_bytes(rows[0][1].encode()) != rows[0][0]
                    or comparable != expected
                    or datetime.fromisoformat(retained_record["observed_at"])
                    < dispatch_at
                ):
                    raise NativeEvidenceError(
                        "conflicting native assessment result replay"
                    )
            if not rows:
                append_ledger(connection, _ASSESSMENT_RESULT_KIND, record)
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        return retained

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
                    or context.get("output_schema_digest")
                    != allocation.output_schema_digest
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
                if allocation is not None and not self._usage.retain_result(
                    allocation, execution, dispatch_at=dispatch_at
                ):
                    raise EvidencePackageError(
                        "native assessment output exceeds retained result limit"
                    )
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
                _contract_hold_reason(exc),
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
        source_ids = {source.unit.source_id for source in sources}
        receipt_by_source = {
            source.unit.source_id: result.receipt_digest
            for source, result in zip(sources, acquired, strict=True)
        }
        acquired_by_source = {
            source.unit.source_id: result
            for source, result in zip(sources, acquired, strict=True)
        }
        source_by_id = {source.unit.source_id: source for source in sources}
        raw_package = value.get("package")
        if type(raw_package) is not dict or set(raw_package) != set(_PACKAGE_FIELDS):
            raise EvidencePackageError("assessment package fields differ")
        authority: list[SourceAuthorityAssessment] = []
        governed_claims: list[dict[str, object]] = []
        semantic_by_claim: dict[str, dict[str, object]] = {}
        raw_claims = raw_package.get("governed_claims")
        if type(raw_claims) is not list:
            raise EvidencePackageError("assessment claims differ")
        for raw_claim in raw_claims:
            if type(raw_claim) is not dict or set(raw_claim) != set(_CLAIM_FIELDS):
                raise EvidencePackageError("assessment claim fields differ")
            claim_source_ids = raw_claim.get("source_ids")
            if (
                type(claim_source_ids) is not list
                or not claim_source_ids
                or any(
                    type(item) is not str or item not in source_ids
                    for item in claim_source_ids
                )
            ):
                raise NativeEvidenceHold(
                    "ASSESSOR_CLAIM_BINDING_HOLD", sources[0].unit.source_id
                )
            selected = tuple(source_by_id[item] for item in claim_source_ids)
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
                    "SOURCE_AUTHORITY_HOLD", claim_source_ids[0]
                )
            roles = tuple(items[0] for items in source_roles)
            scope = "; ".join(sorted({item.purpose for item in roles}))
            claim_id = raw_claim.get("claim_id")
            claim_text = raw_claim.get("claim")
            rendered = raw_claim.get("rendered_assertion_zh_hant_hk")
            if not all(type(item) is str for item in (claim_id, claim_text, rendered)):
                raise EvidencePackageError("assessment claim identity differs")
            raw_semantic = raw_claim.get("semantic_relation")
            if (
                type(raw_semantic) is not dict
                or set(raw_semantic) != set(_SEMANTIC_RELATION_FIELDS)
                or any(type(item) is not str for item in raw_semantic.values())
            ):
                raise EvidencePackageError("assessment semantic relation differs")
            semantic_by_claim[claim_id] = raw_semantic
            decisions = tuple(
                SourceAuthorityAssessment.create(
                    source_id=source.unit.source_id,
                    governed_claim_id=claim_id,
                    decision="ADMITTED",
                    authority_class="RESPONSIBLE_PRIMARY",
                    authority_scope=role.purpose,
                    evidence_digest=digest_bytes(
                        canonical_json_bytes(
                            {
                                "claim_digest": digest_bytes(claim_text.encode()),
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
            supporting_excerpt = raw_claim.get("supporting_excerpt")
            if type(supporting_excerpt) is not str:
                raise EvidencePackageError("assessment supporting excerpt differs")
            named_entities = tuple(sorted(bounded_named_entities(claim_text)))
            if not set(named_entities) <= bounded_named_entities(supporting_excerpt):
                raise EvidencePackageError(
                    "assessment named entities differ from source evidence"
                )
            if bounded_named_entities(rendered) != set(named_entities):
                raise EvidencePackageError(
                    "assessment rendered named entities differ"
                )
            governed_claims.append({
                **{
                    key: item
                    for key, item in raw_claim.items()
                    if key != "semantic_relation"
                },
                "source_record_ids": [
                    receipt_by_source[item] for item in claim_source_ids
                ],
                "source_authority_decision_ids": [
                    item.record_id for item in decisions
                ],
                "rights_decision_ids": [
                    source_by_id[item].rights.record_id for item in claim_source_ids
                ],
                "dependency_evidence_ids": [
                    source_by_id[item].dependency.record_id
                    for item in claim_source_ids
                ],
                "evidential_origin_ids": [
                    source_by_id[item].dependency.evidential_origin_id
                    for item in claim_source_ids
                ],
                "authority_class": ClaimAuthorityClass.RESPONSIBLE_PRIMARY.value,
                "authority_scope": scope,
                "attribution": "; ".join(
                    sorted(
                        {acquired_by_source[item].publisher for item in claim_source_ids}
                    )
                ),
                "semantic_relation_evidence_id": _semantic_record_id(
                    claim_id, claim_text, rendered
                ),
                "named_entity_evidence": [
                    [
                        text,
                        entity_type,
                        _named_entity_record_id(claim_id, text, entity_type, text),
                    ]
                    for text, entity_type in named_entities
                ],
                "named_entities": [item[0] for item in named_entities],
                "rendered_named_entities": [
                    item[0] for item in named_entities
                ],
            })
        raw_qualifications = raw_package.get("qualification_evidence")
        if type(raw_qualifications) is not list:
            raise EvidencePackageError("assessment qualifications differ")
        qualifications = []
        for item in raw_qualifications:
            if type(item) is not dict or set(item) != {
                "test", "governed_claim_id", "test_evidence", "policy_version"
            }:
                raise EvidencePackageError("assessment qualification fields differ")
            test_evidence = item.get("test_evidence")
            if type(test_evidence) is not dict:
                raise EvidencePackageError("assessment qualification evidence differs")
            evidence_pairs = [[key, value] for key, value in test_evidence.items()]
            qualifications.append({
                **item,
                "qualification_record_id": _qualification_record_id(
                    item.get("governed_claim_id"),
                    item.get("test"),
                    evidence_pairs,
                ),
                "test_evidence": evidence_pairs,
            })
        package_value = evidence_package_value(base)
        package_value.update(raw_package)
        package_value["governed_claims"] = governed_claims
        package_value["qualification_evidence"] = qualifications
        package = _package_from_value(package_value)
        if _base_package(package) != base:
            raise NativeEvidenceHold("ASSESSOR_BASE_BINDING_HOLD", sources[0].unit.source_id)
        for claim in package.governed_claims:
            if (
                claim.passage_index >= len(acquired)
                or claim.supporting_excerpt
                not in acquired[claim.passage_index].body.decode("utf-8")
            ):
                raise NativeEvidenceHold(
                    "ASSESSOR_CLAIM_BINDING_HOLD", sources[0].unit.source_id
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
        claims_by_id = {claim.claim_id: claim for claim in package.governed_claims}
        if any(
            item.governed_claim_id not in claims_by_id
            for item in package.qualification_evidence
        ):
            raise EvidencePackageError("assessment qualification claim differs")
        assessment_records = [
            {
                "record_id": claim.semantic_relation_evidence_id,
                "record_type": "SEMANTIC_RELATION_EVIDENCE",
                "governed_claim_id": claim.claim_id,
                **semantic_by_claim[claim.claim_id],
                "claim_digest": digest_bytes(claim.claim.encode()),
                "rendered_assertion_digest": digest_bytes(
                    claim.rendered_assertion_zh_hant_hk.encode()
                ),
            }
            for claim in package.governed_claims
        ]
        assessment_records.extend(
            {
                "record_id": item.qualification_record_id,
                "record_type": "QUALIFICATION_EVIDENCE",
                "governed_claim_id": item.governed_claim_id,
                "test": item.test.value,
                "test_evidence": [list(value) for value in item.test_evidence],
                "policy_version": item.policy_version,
                "evidence_span_digest": digest_bytes(
                    claims_by_id[item.governed_claim_id].supporting_excerpt.encode()
                ),
                "source_record_ids": list(
                    claims_by_id[item.governed_claim_id].source_record_ids
                ),
            }
            for item in package.qualification_evidence
        )
        assessment_records.extend(
            {
                "record_id": record_id,
                "record_type": "NAMED_ENTITY_EVIDENCE",
                "governed_claim_id": claim.claim_id,
                "text": text,
                "rendered_text": claim.rendered_named_entities[index],
                "entity_type": entity_type,
                "canonical_entity_id": digest_bytes(f"{entity_type}:{text}".encode()),
                "rendered_span_digest": digest_bytes(
                    claim.rendered_named_entities[index].encode()
                ),
                "policy_version": NAMED_ENTITY_POLICY_VERSION,
                "evidence_span_digest": digest_bytes(text.encode()),
                "source_record_ids": list(claim.source_record_ids),
            }
            for claim in package.governed_claims
            for index, (text, entity_type, record_id) in enumerate(
                claim.named_entity_evidence
            )
        )
        return IndependentEvidenceAssessment(
            assessments,
            tuple(authority),
            package.substantive_new_information,
            package.governed_claims,
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
            raise EvidencePackageError(
                "native assessment output has duplicate fields"
            )
        return value

    try:
        value = json.loads(text, object_pairs_hook=unique)
    except (TypeError, json.JSONDecodeError) as exc:
        raise EvidencePackageError(
            "native assessment output is malformed"
        ) from exc
    if type(value) is not dict:
        raise EvidencePackageError("native assessment output is malformed")
    if set(value) != set(SCHEMA["required"]):
        raise EvidencePackageError("native assessment output fields differ")
    return value


def _dispatch_grok(prompt: str) -> NativeAssessmentExecution:
    execution = _run_grok_json(
        prompt,
        schema=SCHEMA,
        system_instruction=SYSTEM,
        temporary_prefix="newsroom-grok-evidence-assessor-",
    )
    return NativeAssessmentExecution(execution.text, execution.usage)
