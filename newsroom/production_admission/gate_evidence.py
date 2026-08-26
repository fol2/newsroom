"""Typed, reproducible evidence facts for every production readiness gate."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes

from ._shared import (
    FreezeIdentity,
    ProductionAdmissionError,
    _boolean,
    _canonical_document,
    _digest,
    _git_sha,
    _nonnegative_integer,
    _optional_digest,
    _positive_integer,
    _token,
)
from .identities import (
    BoundArtifact,
    BoundArtifactRole,
    EvaluatedIdentity,
    IdentityClass,
    ProductionGateId,
    ProductionIdentitySet,
    _publication_spec_digests,
)


def _gate_fact_mapping(value: object, required: set[str]) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != required:
        raise ProductionAdmissionError("gate evidence fact inventory differs")
    return dict(value)


def _identity(
    identity_set: ProductionIdentitySet, identity_class: IdentityClass
) -> EvaluatedIdentity:
    matches = tuple(
        item
        for item in identity_set.identities
        if item.identity_class is identity_class
    )
    if len(matches) != 1:
        raise ProductionAdmissionError(f"identity {identity_class.value} is not exact")
    return matches[0]


def _artifact(
    bound_artifacts: Sequence[BoundArtifact], role: BoundArtifactRole
) -> BoundArtifact:
    matches = tuple(item for item in bound_artifacts if item.role is role)
    if len(matches) != 1:
        raise ProductionAdmissionError(f"bound artifact {role.value} is not exact")
    return matches[0]


def _identity_gate_facts(
    *,
    value: object,
    required: set[str],
    identity_set: ProductionIdentitySet,
    identity_class: IdentityClass,
) -> tuple[dict[str, object], set[str]]:
    facts = _gate_fact_mapping(
        value,
        required | {"identity_digest", "evaluation_evidence_digest"},
    )
    facts["identity_digest"] = _digest(facts["identity_digest"], "identity_digest")
    facts["evaluation_evidence_digest"] = _digest(
        facts["evaluation_evidence_digest"], "evaluation_evidence_digest"
    )
    identity = _identity(identity_set, identity_class)
    blockers: set[str] = set()
    if facts["identity_digest"] != identity.identity_digest:
        blockers.add(f"IDENTITY_DIGEST_DRIFT:{identity_class.value}")
    if facts["evaluation_evidence_digest"] != identity.evaluation_evidence_digest:
        blockers.add(f"IDENTITY_EVALUATION_EVIDENCE_DRIFT:{identity_class.value}")
    return facts, blockers


def _normalise_gate_facts(
    *,
    gate_id: ProductionGateId,
    value: object,
    identity_set: ProductionIdentitySet,
    bound_artifacts: Sequence[BoundArtifact],
    accepted_publication_spec_digests: Mapping[str, str],
) -> tuple[Mapping[str, object], tuple[str, ...]]:
    blockers: set[str] = set()

    if gate_id is ProductionGateId.RELATIONAL_SCHEMA_CURRENT:
        facts, blockers = _identity_gate_facts(
            value=value,
            required={
                "relational_schema_version",
                "migration_history_digest",
                "schema_fingerprint",
            },
            identity_set=identity_set,
            identity_class=IdentityClass.RELATIONAL_SCHEMA,
        )
        facts["relational_schema_version"] = _positive_integer(
            facts["relational_schema_version"], "relational_schema_version"
        )
        facts["migration_history_digest"] = _digest(
            facts["migration_history_digest"], "migration_history_digest"
        )
        facts["schema_fingerprint"] = _digest(
            facts["schema_fingerprint"], "schema_fingerprint"
        )
        if (
            facts["relational_schema_version"] != identity_set.relational_schema_version
            or facts["migration_history_digest"]
            != identity_set.migration_history_digest
            or facts["schema_fingerprint"] != identity_set.schema_fingerprint
        ):
            blockers.add("RELATIONAL_SCHEMA_IDENTITY_DRIFT")
    elif gate_id is ProductionGateId.OPERATIONAL_PROFILE_CURRENT:
        facts, blockers = _identity_gate_facts(
            value=value,
            required={"profile_scope", "profile_current"},
            identity_set=identity_set,
            identity_class=IdentityClass.OPERATIONAL_PROFILE,
        )
        facts["profile_scope"] = _token(facts["profile_scope"], "profile_scope")
        facts["profile_current"] = _boolean(facts["profile_current"], "profile_current")
        if facts["profile_scope"] != "production" or not facts["profile_current"]:
            blockers.add("OPERATIONAL_PROFILE_NOT_CURRENT")
    elif gate_id is ProductionGateId.GRAPHRAG_DEPLOYMENT_CURRENT:
        facts, blockers = _identity_gate_facts(
            value=value,
            required={
                "deployment_bytes_digest",
                "projection_generation_digest",
                "contiguous_projection_watermark",
                "admitted_only",
            },
            identity_set=identity_set,
            identity_class=IdentityClass.GRAPHRAG_DEPLOYMENT,
        )
        facts["deployment_bytes_digest"] = _digest(
            facts["deployment_bytes_digest"], "deployment_bytes_digest"
        )
        facts["projection_generation_digest"] = _digest(
            facts["projection_generation_digest"], "projection_generation_digest"
        )
        facts["contiguous_projection_watermark"] = _positive_integer(
            facts["contiguous_projection_watermark"],
            "contiguous_projection_watermark",
        )
        facts["admitted_only"] = _boolean(facts["admitted_only"], "admitted_only")
        if (
            facts["deployment_bytes_digest"] != identity_set.deployment_bytes_digest
            or facts["projection_generation_digest"]
            != identity_set.projection_generation_digest
            or facts["contiguous_projection_watermark"]
            != identity_set.contiguous_projection_watermark
            or not facts["admitted_only"]
        ):
            blockers.add("GRAPHRAG_DEPLOYMENT_NOT_CURRENT")
    elif gate_id is ProductionGateId.RETRIEVAL_CONTRACT_CURRENT:
        facts, blockers = _identity_gate_facts(
            value=value,
            required={"contract_current", "admitted_only"},
            identity_set=identity_set,
            identity_class=IdentityClass.RETRIEVAL_CONTRACT,
        )
        facts["contract_current"] = _boolean(
            facts["contract_current"], "contract_current"
        )
        facts["admitted_only"] = _boolean(facts["admitted_only"], "admitted_only")
        if not facts["contract_current"] or not facts["admitted_only"]:
            blockers.add("RETRIEVAL_CONTRACT_NOT_CURRENT")
    elif gate_id is ProductionGateId.LIVE_EVIDENCE_INTAKE_CURRENT:
        facts, blockers = _identity_gate_facts(
            value=value,
            required={"canary_closeout_digest", "canary_outcome", "run_window_closed"},
            identity_set=identity_set,
            identity_class=IdentityClass.LIVE_EVIDENCE_INTAKE,
        )
        facts["canary_closeout_digest"] = _digest(
            facts["canary_closeout_digest"], "canary_closeout_digest"
        )
        facts["canary_outcome"] = _token(facts["canary_outcome"], "canary_outcome")
        facts["run_window_closed"] = _boolean(
            facts["run_window_closed"], "run_window_closed"
        )
        canary = _artifact(
            bound_artifacts,
            BoundArtifactRole.LIVE_EVIDENCE_INTAKE_CANARY_CLOSEOUT,
        )
        if (
            facts["canary_closeout_digest"] != canary.artifact_digest
            or facts["canary_outcome"] != "ELIGIBLE_FOR_ACTIVATION_PLANNING"
            or not facts["run_window_closed"]
        ):
            blockers.add("LIVE_EVIDENCE_INTAKE_CANARY_NOT_QUALIFYING")
    elif gate_id is ProductionGateId.PUBLICATION_ADAPTERS_CURRENT:
        facts, blockers = _identity_gate_facts(
            value=value,
            required={"adapter_inventory_digest", "adapter_count", "adapters_current"},
            identity_set=identity_set,
            identity_class=IdentityClass.PUBLICATION_ADAPTERS,
        )
        facts["adapter_inventory_digest"] = _digest(
            facts["adapter_inventory_digest"], "adapter_inventory_digest"
        )
        facts["adapter_count"] = _positive_integer(
            facts["adapter_count"], "adapter_count"
        )
        facts["adapters_current"] = _boolean(
            facts["adapters_current"], "adapters_current"
        )
        if not facts["adapters_current"]:
            blockers.add("PUBLICATION_ADAPTERS_NOT_CURRENT")
    elif gate_id is ProductionGateId.HANDOFF_NON_EFFECT_IDENTITIES_CURRENT:
        facts, blockers = _identity_gate_facts(
            value=value,
            required={
                "handoff_max_attempts",
                "publication_effects",
                "public_dispatch_effects",
                "production_mutations",
            },
            identity_set=identity_set,
            identity_class=IdentityClass.HANDOFF_NON_EFFECT,
        )
        facts["handoff_max_attempts"] = _positive_integer(
            facts["handoff_max_attempts"], "handoff_max_attempts"
        )
        for name in (
            "publication_effects",
            "public_dispatch_effects",
            "production_mutations",
        ):
            facts[name] = _nonnegative_integer(facts[name], name)
        if facts["handoff_max_attempts"] != identity_set.handoff_max_attempts:
            blockers.add("HANDOFF_IDENTITY_DRIFT")
        if (
            any(facts[name] != 0 for name in facts if name.endswith("effects"))
            or facts["production_mutations"] != 0
        ):
            blockers.add("HANDOFF_NON_EFFECT_IDENTITY_DRIFT")
    elif gate_id is ProductionGateId.EFFECTIVE_REVISION_COVERAGE_CURRENT:
        facts = _gate_fact_mapping(
            value,
            {
                "coverage_policy",
                "eligible_revisions",
                "terminal_revisions",
                "terminal_coverage_ppm",
                "required_terminal_coverage_ppm",
                "hidden_gap_count",
                "threshold_authority_digest",
                "contiguous_projection_watermark",
            },
        )
        facts["coverage_policy"] = _token(facts["coverage_policy"], "coverage_policy")
        eligible_revisions = _positive_integer(
            facts["eligible_revisions"], "eligible_revisions"
        )
        terminal_revisions = _nonnegative_integer(
            facts["terminal_revisions"], "terminal_revisions"
        )
        terminal_coverage_ppm = _nonnegative_integer(
            facts["terminal_coverage_ppm"], "terminal_coverage_ppm"
        )
        hidden_gap_count = _nonnegative_integer(
            facts["hidden_gap_count"], "hidden_gap_count"
        )
        required_terminal_coverage_ppm = _positive_integer(
            facts["required_terminal_coverage_ppm"],
            "required_terminal_coverage_ppm",
        )
        facts.update(
            {
                "eligible_revisions": eligible_revisions,
                "terminal_revisions": terminal_revisions,
                "terminal_coverage_ppm": terminal_coverage_ppm,
                "hidden_gap_count": hidden_gap_count,
                "required_terminal_coverage_ppm": required_terminal_coverage_ppm,
            }
        )
        facts["threshold_authority_digest"] = _optional_digest(
            facts["threshold_authority_digest"], "threshold_authority_digest"
        )
        facts["contiguous_projection_watermark"] = _positive_integer(
            facts["contiguous_projection_watermark"],
            "contiguous_projection_watermark",
        )
        expected_ppm = terminal_revisions * 1_000_000 // eligible_revisions
        if (
            terminal_revisions > eligible_revisions
            or terminal_coverage_ppm != expected_ppm
            or terminal_coverage_ppm < required_terminal_coverage_ppm
            or hidden_gap_count != 0
        ):
            blockers.add("TERMINAL_EFFECTIVE_REVISION_COVERAGE_INCOMPLETE")
        if facts["contiguous_projection_watermark"] != (
            identity_set.contiguous_projection_watermark
        ):
            blockers.add("PROJECTION_WATERMARK_DRIFT")
        if facts["coverage_policy"] == "FULL_TERMINAL":
            if (
                required_terminal_coverage_ppm != 1_000_000
                or facts["threshold_authority_digest"] is not None
            ):
                blockers.add("COVERAGE_POLICY_INVALID")
        elif facts["coverage_policy"] == "OWNER_APPROVED_THRESHOLD":
            if facts["threshold_authority_digest"] is None:
                blockers.add("MISSING_COVERAGE_THRESHOLD_AUTHORITY")
        else:
            blockers.add("COVERAGE_POLICY_INVALID")
    elif gate_id is ProductionGateId.SPEND_ACCOUNTING_RECONCILED:
        facts = _gate_fact_mapping(
            value,
            {
                "attempt_count",
                "reconciled_attempt_count",
                "unreconciled_attempt_count",
                "usage_uncertainty_count",
                "reserved_gbp_microunits",
                "actual_gbp_microunits",
            },
        )
        accounting = {name: _nonnegative_integer(facts[name], name) for name in facts}
        facts.update(accounting)
        if (
            accounting["reconciled_attempt_count"]
            + accounting["unreconciled_attempt_count"]
            != accounting["attempt_count"]
            or accounting["unreconciled_attempt_count"] != 0
            or accounting["usage_uncertainty_count"] != 0
            or accounting["reserved_gbp_microunits"] != 0
        ):
            blockers.add("SPEND_OR_USAGE_UNRECONCILED")
    elif gate_id is ProductionGateId.RIGHTS_TERMS_CREDENTIALS_EGRESS_CURRENT:
        facts = _gate_fact_mapping(
            value,
            {
                "rights_identity_digest",
                "provider_terms_identity_digest",
                "credential_identity_digest",
                "egress_identity_digest",
                "rights_current",
                "provider_terms_current",
                "credentials_current",
                "egress_current",
            },
        )
        for name in tuple(facts):
            if name.endswith("_digest"):
                facts[name] = _digest(facts[name], name)
            else:
                facts[name] = _boolean(facts[name], name)
        if not all(facts[name] for name in facts if name.endswith("_current")):
            blockers.add("RIGHTS_TERMS_CREDENTIALS_OR_EGRESS_NOT_CURRENT")
    elif gate_id is ProductionGateId.HERMES_RUNTIME_CONTROLS_CURRENT:
        facts = _gate_fact_mapping(
            value,
            {
                "control_plane",
                "single_instance_count",
                "veto_ready",
                "kill_switch_ready",
                "signed_human_stop_digest",
                "human_stop_state",
                "legacy_stack_running",
            },
        )
        facts["control_plane"] = _token(facts["control_plane"], "control_plane")
        facts["single_instance_count"] = _nonnegative_integer(
            facts["single_instance_count"], "single_instance_count"
        )
        facts["veto_ready"] = _boolean(facts["veto_ready"], "veto_ready")
        facts["kill_switch_ready"] = _boolean(
            facts["kill_switch_ready"], "kill_switch_ready"
        )
        facts["signed_human_stop_digest"] = _digest(
            facts["signed_human_stop_digest"], "signed_human_stop_digest"
        )
        facts["human_stop_state"] = _token(
            facts["human_stop_state"], "human_stop_state"
        )
        facts["legacy_stack_running"] = _boolean(
            facts["legacy_stack_running"], "legacy_stack_running"
        )
        if (
            facts["control_plane"] != "HERMES"
            or facts["single_instance_count"] != 1
            or not facts["veto_ready"]
            or not facts["kill_switch_ready"]
            or facts["human_stop_state"] != "CLEAR_SIGNED"
            or facts["legacy_stack_running"]
        ):
            blockers.add("HERMES_RUNTIME_CONTROLS_NOT_CURRENT")
    elif gate_id is ProductionGateId.STORAGE_BACKUP_RESTORE_ROLLBACK_CURRENT:
        facts = _gate_fact_mapping(
            value,
            {
                "protected_storage",
                "store_identity_digest",
                "backup_digest",
                "restore_digest",
                "rollback_digest",
                "ambiguous_effect_count",
                "unreconciled_ambiguous_effect_count",
            },
        )
        facts["protected_storage"] = _boolean(
            facts["protected_storage"], "protected_storage"
        )
        for name in (
            "store_identity_digest",
            "backup_digest",
            "restore_digest",
            "rollback_digest",
        ):
            facts[name] = _digest(facts[name], name)
        for name in ("ambiguous_effect_count", "unreconciled_ambiguous_effect_count"):
            facts[name] = _nonnegative_integer(facts[name], name)
        backup = _artifact(bound_artifacts, BoundArtifactRole.BACKUP)
        restore = _artifact(bound_artifacts, BoundArtifactRole.RESTORE)
        rollback = _artifact(bound_artifacts, BoundArtifactRole.ROLLBACK)
        if (
            not facts["protected_storage"]
            or facts["store_identity_digest"] != backup.store_identity_digest
            or facts["backup_digest"] != backup.artifact_digest
            or facts["restore_digest"] != restore.artifact_digest
            or facts["rollback_digest"] != rollback.artifact_digest
            or facts["unreconciled_ambiguous_effect_count"] != 0
        ):
            blockers.add("STORAGE_RECOVERY_OR_RECONCILIATION_NOT_CURRENT")
    elif gate_id is ProductionGateId.PUBLICATION_LIFECYCLE_SPECIFICATIONS_ACCEPTED:
        facts = _gate_fact_mapping(value, {"accepted_spec_digests", "draft_count"})
        facts["accepted_spec_digests"] = dict(
            _publication_spec_digests(facts["accepted_spec_digests"])
        )
        facts["draft_count"] = _nonnegative_integer(facts["draft_count"], "draft_count")
        if (
            facts["accepted_spec_digests"] != dict(accepted_publication_spec_digests)
            or facts["draft_count"] != 0
        ):
            blockers.add("PUBLICATION_SPECIFICATIONS_NOT_ACCEPTED")
    elif gate_id is ProductionGateId.CANARY_ROLLBACK_RESTORE_IDENTITY_BOUND:
        facts = _gate_fact_mapping(
            value,
            {"canary_digest", "restore_digest", "rollback_digest", "same_identity"},
        )
        for name in ("canary_digest", "restore_digest", "rollback_digest"):
            facts[name] = _digest(facts[name], name)
        facts["same_identity"] = _boolean(facts["same_identity"], "same_identity")
        canary = _artifact(
            bound_artifacts,
            BoundArtifactRole.LIVE_EVIDENCE_INTAKE_CANARY_CLOSEOUT,
        )
        restore = _artifact(bound_artifacts, BoundArtifactRole.RESTORE)
        rollback = _artifact(bound_artifacts, BoundArtifactRole.ROLLBACK)
        if (
            facts["canary_digest"] != canary.artifact_digest
            or facts["restore_digest"] != restore.artifact_digest
            or facts["rollback_digest"] != rollback.artifact_digest
            or not facts["same_identity"]
        ):
            blockers.add("CANARY_ROLLBACK_RESTORE_EVIDENCE_DRIFT")
    elif gate_id is ProductionGateId.SDLC_CORE_SERVICE_CURRENT:
        facts = _gate_fact_mapping(
            value,
            {
                "risk_tier",
                "core_status",
                "service_status",
                "owner_authority_required",
                "origin_main_present",
                "source_main_sha",
                "source_main_tree",
                "merged_main_ci_digest",
                "merged_main_ci_status",
            },
        )
        for name in (
            "risk_tier",
            "core_status",
            "service_status",
            "merged_main_ci_status",
        ):
            facts[name] = _token(facts[name], name)
        facts["owner_authority_required"] = _boolean(
            facts["owner_authority_required"], "owner_authority_required"
        )
        facts["origin_main_present"] = _boolean(
            facts["origin_main_present"], "origin_main_present"
        )
        facts["source_main_sha"] = _git_sha(facts["source_main_sha"], "source_main_sha")
        facts["source_main_tree"] = _git_sha(
            facts["source_main_tree"], "source_main_tree"
        )
        facts["merged_main_ci_digest"] = _digest(
            facts["merged_main_ci_digest"], "merged_main_ci_digest"
        )
        if (
            facts["risk_tier"] != "R4_RELEASE_OPERATIONAL"
            or facts["core_status"] != "PASS"
            or facts["service_status"] != "PASS"
            or not facts["owner_authority_required"]
            or not facts["origin_main_present"]
            or facts["source_main_sha"] != identity_set.freeze.exact_main_sha
            or facts["source_main_tree"] != identity_set.freeze.exact_main_tree
            or facts["merged_main_ci_status"] != "PASS"
        ):
            blockers.add("SDLC_CORE_SERVICE_OR_SOURCE_AUTHORITY_NOT_CURRENT")
    elif gate_id is ProductionGateId.READINESS_INSPECTION_NON_EFFECT:
        facts = _gate_fact_mapping(
            value,
            {"provider_calls", "publication_effects", "production_mutations"},
        )
        for name in facts:
            facts[name] = _nonnegative_integer(facts[name], name)
        if any(facts.values()):
            blockers.add("READINESS_INSPECTION_CREATED_EFFECT")
    else:  # pragma: no cover - the enum inventory is exhaustive
        raise ProductionAdmissionError("production gate evidence differs")

    return MappingProxyType(facts), tuple(sorted(blockers))


@dataclass(frozen=True, slots=True)
class ProductionGateEvidence:
    gate_id: ProductionGateId
    freeze: FreezeIdentity
    operational_manifest_digest: str
    identity_set_digest: str
    facts: Mapping[str, object]
    blockers: tuple[str, ...]
    canonical_bytes: bytes
    digest: str

    @classmethod
    def build(
        cls,
        *,
        gate_id: ProductionGateId,
        identity_set: ProductionIdentitySet,
        bound_artifacts: Sequence[BoundArtifact],
        accepted_publication_spec_digests: Mapping[str, str],
        facts: Mapping[str, object],
    ) -> ProductionGateEvidence:
        if not isinstance(gate_id, ProductionGateId):
            raise ProductionAdmissionError("production gate evidence differs")
        normalised, blockers = _normalise_gate_facts(
            gate_id=gate_id,
            value=facts,
            identity_set=identity_set,
            bound_artifacts=bound_artifacts,
            accepted_publication_spec_digests=accepted_publication_spec_digests,
        )
        value = {
            "schema_version": "newsroom.production-gate-evidence.v1",
            "gate_id": gate_id.value,
            **identity_set.freeze.canonical_value(),
            "operational_manifest_digest": identity_set.operational_manifest_digest,
            "identity_set_digest": identity_set.digest,
            "facts": dict(normalised),
        }
        raw = canonical_json_bytes(value)
        return cls(
            gate_id,
            identity_set.freeze,
            identity_set.operational_manifest_digest,
            identity_set.digest,
            normalised,
            blockers,
            raw,
            digest_bytes(raw),
        )

    @classmethod
    def from_canonical_bytes(
        cls,
        raw: bytes,
        *,
        identity_set: ProductionIdentitySet,
        bound_artifacts: Sequence[BoundArtifact],
        accepted_publication_spec_digests: Mapping[str, str],
    ) -> ProductionGateEvidence:
        value = _canonical_document(raw)
        required = {
            "schema_version",
            "gate_id",
            "exact_main_sha",
            "exact_main_tree",
            "operational_manifest_digest",
            "identity_set_digest",
            "facts",
        }
        if (
            set(value) != required
            or value["schema_version"] != "newsroom.production-gate-evidence.v1"
            or not isinstance(value["gate_id"], str)
            or not isinstance(value["facts"], dict)
        ):
            raise ProductionAdmissionError("production gate evidence fields differ")
        try:
            gate_id = ProductionGateId(value["gate_id"])
        except ValueError as exc:
            raise ProductionAdmissionError("production gate evidence differs") from exc
        rebuilt = cls.build(
            gate_id=gate_id,
            identity_set=identity_set,
            bound_artifacts=bound_artifacts,
            accepted_publication_spec_digests=accepted_publication_spec_digests,
            facts=value["facts"],
        )
        if (
            value["exact_main_sha"] != identity_set.freeze.exact_main_sha
            or value["exact_main_tree"] != identity_set.freeze.exact_main_tree
            or value["operational_manifest_digest"]
            != identity_set.operational_manifest_digest
            or value["identity_set_digest"] != identity_set.digest
            or rebuilt.canonical_bytes != raw
        ):
            raise ProductionAdmissionError("production gate evidence binding differs")
        return rebuilt

    def canonical_value(self) -> Mapping[str, object]:
        return _canonical_document(self.canonical_bytes)
