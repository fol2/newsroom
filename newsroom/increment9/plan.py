"""Canonical Increment 9R shadow plan and owner-decision gate.

Loading this module performs no network request, credential lookup, deployment,
provider/model execution or shadow run.  The retained v1 document is the
owner-approved plan.  Its conditional autonomy envelope authorises later work
only after the exact implementation and evidence prerequisites recorded in the
plan have passed; loading or merging these bytes creates no live effect.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)

SHADOW_PLAN_PATH = Path(__file__).with_name("shadow_plan_v1.json")
AGENT_PROFILES_PATH = Path(__file__).with_name("agent_profiles_v1.json")
EXPECTED_SHADOW_PLAN_DIGEST = (
    "sha256:4163ad944597dd69f433a89c2af892904258a5cd56c38afe4b295c0a82f182bd"
)
EXPECTED_AGENT_PROFILES_DIGEST = (
    "sha256:c6835632cb9088167ff049325277802d1b6347bc9df44b1e5b41d1d029c56944"
)

EXPECTED_BASE = {
    "commit": "3d4ace16a75e92b9f80c526f18aa811be6c2b053",
    "tree": "4dd2b50aafd074314fbbefe3519f0707b9c5507f",
    "schema_version": 32,
    "schema_fingerprint": (
        "sha256:3439b82ec6d212116e54765d50cace4d7f147b6ecc3e6ff84146b523c6fd5676"
    ),
    "migration_history_digest": (
        "sha256:5a48fd76cd11f266e19a4b48174d0c009f320a8d00d3eeb281a558fc2d561910"
    ),
    "increment8_exact_main_run": 31871581163,
    "increment8_operational_admission": "FIXTURE_OPERATIONAL_ADMITTED",
    "increment9_disposition": "ELIGIBLE_FOR_SEPARATE_PLAN",
    "capacity_issue": 500,
    "capacity_pull_request": 501,
    "capacity_exact_main_run": 31900458431,
    "deterministic_core_shards": 18,
}

EXPECTED_OWNER_DECISION_IDS = tuple(f"OD-{number:03d}" for number in range(1, 15))
EXPECTED_ISSUES = tuple(range(488, 499))
EXPECTED_WAVES = (
    (488,),
    (489, 491, 494, 496),
    (490, 492),
    (493,),
    (495,),
    (497,),
    (498,),
)
EXPECTED_OUTCOMES = (
    "FAILED",
    "INCONCLUSIVE",
    "CONTINUE_SHADOW",
    "COMPARATOR_ONLY",
    "BLOCKED_ACTIVE_COVERAGE",
    "SCOPED_OPERATIONAL_ELIGIBILITY",
)
EXPECTED_ALLOCATION_DEPENDENCIES = {
    488: (),
    489: (488,),
    490: (489,),
    491: (488,),
    492: (488, 489, 490, 491),
    493: (488, 489, 490, 491, 492),
    494: (488,),
    495: (490, 491, 492, 493, 494),
    496: (488,),
    497: (493, 495, 496),
    498: tuple(range(488, 498)),
}
EXPECTED_ZERO_TOLERANCE_FIELDS = {
    "authority_cross_contamination",
    "credential_exposure",
    "prohibited_egress",
    "production_authority_mutation",
    "public_effect",
    "rights_breach",
    "uncontained_ambiguous_effect",
}


class Increment9PlanError(ValueError):
    """The supplied document is not the reviewed Increment 9R plan."""


class OwnerApprovalRequired(Increment9PlanError):
    """The immutable plan still contains unresolved owner decisions."""


@dataclass(frozen=True, slots=True)
class OwnerDecision:
    decision_id: str
    title: str
    status: str
    required_bindings: tuple[str, ...]
    selection: object | None
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ChildAllocation:
    issue_number: int
    atom: str
    dependencies: tuple[int, ...]
    work_kind: str
    file_ownership: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Increment9ShadowPlan:
    schema_version: str
    plan_id: str
    plan_version: str
    issue_number: int
    parent_issue_number: int
    programme_issue_number: int
    planning_base: Mapping[str, object]
    approval: Mapping[str, object]
    repository_baseline: Mapping[str, object]
    owner_decisions: tuple[OwnerDecision, ...]
    frozen_rules: Mapping[str, object]
    non_effect_authority: Mapping[str, object]
    stop_and_recovery: Mapping[str, object]
    allocations: tuple[ChildAllocation, ...]
    waves: tuple[tuple[int, ...], ...]
    gate_requirements: Mapping[str, object]
    outcome_vocabulary: tuple[str, ...]
    increment10_eligibility: Mapping[str, object]
    plan_digest: str

    @property
    def unresolved_owner_decision_ids(self) -> tuple[str, ...]:
        return tuple(
            item.decision_id
            for item in self.owner_decisions
            if item.status != "APPROVED"
        )

    @property
    def owner_approved(self) -> bool:
        return not self.unresolved_owner_decision_ids and (
            self.approval.get("status") == "OWNER_APPROVED"
        )


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise Increment9PlanError(f"duplicate object name: {name}")
        result[name] = value
    return result


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Increment9PlanError(f"{field} must be an object")
    return value


def _exact_keys(value: Mapping[str, object], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise Increment9PlanError(f"{field} fields differ")


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Increment9PlanError(f"{field} must be an integer")
    return value


def _strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise Increment9PlanError(f"{field} must contain non-empty strings")
    return tuple(value)


def _integers(value: object, field: str) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise Increment9PlanError(f"{field} must be an array")
    return tuple(_integer(item, field) for item in value)


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({name: _freeze(item) for name, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _frozen_mapping(value: object, field: str) -> Mapping[str, object]:
    frozen = _freeze(_mapping(value, field))
    assert isinstance(frozen, Mapping)
    return frozen


def _owner_decision(value: object, index: int) -> OwnerDecision:
    field = f"owner_decisions[{index}]"
    raw = _mapping(value, field)
    _exact_keys(
        raw,
        {
            "decision_id",
            "title",
            "status",
            "required_bindings",
            "selection",
            "evidence_refs",
        },
        field,
    )
    decision_id = str(raw["decision_id"])
    if re.fullmatch(r"OD-[0-9]{3}", decision_id) is None:
        raise Increment9PlanError(f"{field}.decision_id differs")
    return OwnerDecision(
        decision_id=decision_id,
        title=str(raw["title"]),
        status=str(raw["status"]),
        required_bindings=_strings(raw["required_bindings"], f"{field}.required_bindings"),
        selection=_freeze(raw["selection"]),
        evidence_refs=_strings(raw["evidence_refs"], f"{field}.evidence_refs"),
    )


def _allocation(value: object, index: int) -> ChildAllocation:
    field = f"execution_graph.allocations[{index}]"
    raw = _mapping(value, field)
    _exact_keys(
        raw,
        {"issue_number", "atom", "dependencies", "work_kind", "file_ownership"},
        field,
    )
    return ChildAllocation(
        issue_number=_integer(raw["issue_number"], f"{field}.issue_number"),
        atom=str(raw["atom"]),
        dependencies=_integers(raw["dependencies"], f"{field}.dependencies"),
        work_kind=str(raw["work_kind"]),
        file_ownership=_strings(raw["file_ownership"], f"{field}.file_ownership"),
    )


def _validate_component_blobs(repository_baseline: Mapping[str, object]) -> None:
    components = repository_baseline.get("component_blobs")
    if not isinstance(components, tuple) or not components:
        raise Increment9PlanError("repository component inventory is empty")
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for index, value in enumerate(components):
        if not isinstance(value, Mapping):
            raise Increment9PlanError(f"component_blobs[{index}] must be an object")
        if set(value) != {"component_id", "path", "git_blob", "role"}:
            raise Increment9PlanError(f"component_blobs[{index}] fields differ")
        component_id = value["component_id"]
        path = value["path"]
        blob = value["git_blob"]
        if not all(isinstance(item, str) and item for item in (component_id, path, blob)):
            raise Increment9PlanError(f"component_blobs[{index}] text differs")
        if re.fullmatch(r"[0-9a-f]{40}", blob) is None:
            raise Increment9PlanError(f"component_blobs[{index}].git_blob differs")
        if component_id in seen_ids or path in seen_paths:
            raise Increment9PlanError("repository component inventory overlaps")
        seen_ids.add(component_id)
        seen_paths.add(path)


def _validate_plan(plan: Increment9ShadowPlan) -> None:
    if plan.schema_version != "newsroom.increment9.shadow-plan.v1":
        raise Increment9PlanError("shadow plan schema differs")
    if plan.plan_id != "increment9-production-equivalent-shadow-plan-v1":
        raise Increment9PlanError("shadow plan identity differs")
    if plan.plan_version != "increment9-shadow-plan-v1-owner-approved":
        raise Increment9PlanError("shadow plan version differs")
    if plan.issue_number != 488 or plan.parent_issue_number != 149:
        raise Increment9PlanError("issue identity differs")
    if plan.programme_issue_number != 141:
        raise Increment9PlanError("programme issue identity differs")
    if dict(plan.planning_base) != EXPECTED_BASE:
        raise Increment9PlanError("accepted planning base differs")
    validate_sha256_digest(plan.plan_digest, field="plan_digest")

    decision_ids = tuple(item.decision_id for item in plan.owner_decisions)
    if decision_ids != EXPECTED_OWNER_DECISION_IDS:
        raise Increment9PlanError("owner decision inventory differs")
    for item in plan.owner_decisions:
        if item.status != "APPROVED":
            raise Increment9PlanError("owner decision is not approved")
        if not isinstance(item.selection, Mapping):
            raise Increment9PlanError("owner decision selection must be an object")
        if set(item.selection) != set(item.required_bindings):
            raise Increment9PlanError("owner decision bindings differ")
        if not item.evidence_refs or len(item.evidence_refs) != len(
            set(item.evidence_refs)
        ):
            raise Increment9PlanError("owner decision evidence differs")

    approval = plan.approval
    _exact_keys(
        approval,
        {
            "status",
            "approved_by",
            "approved_at",
            "approval_record",
            "approved_plan_digest",
            "required_owner_decision_ids",
            "contract_implementation_authorised",
            "live_shadow_authorised",
            "comparator_fault_execution_authorised",
            "evidence_intake_authorised",
            "publication_authorised",
            "canary_authorised",
            "production_activation_authorised",
            "authority_grant_mode",
            "planning_merge_creates_live_effect",
            "conditional_authority",
        },
        "approval",
    )
    if approval.get("status") != "OWNER_APPROVED":
        raise Increment9PlanError("owner approval status differs")
    if tuple(approval.get("required_owner_decision_ids", ())) != decision_ids:
        raise Increment9PlanError("approval decision inventory differs")
    if approval.get("approved_by") != "github:fol2":
        raise Increment9PlanError("owner identity differs")
    if approval.get("approved_at") != "2026-08-15T22:51:14Z":
        raise Increment9PlanError("owner approval time differs")
    if approval.get("approval_record") != (
        "https://github.com/fol2/newsroom/issues/503#issuecomment-5304608768"
    ):
        raise Increment9PlanError("owner approval record differs")
    validate_sha256_digest(
        approval.get("approved_plan_digest"), field="approved_plan_digest"
    )
    for field in (
        "contract_implementation_authorised",
        "live_shadow_authorised",
        "comparator_fault_execution_authorised",
        "evidence_intake_authorised",
        "publication_authorised",
        "canary_authorised",
        "production_activation_authorised",
    ):
        if approval.get(field) is not False:
            raise Increment9PlanError(f"{field} must remain false before later gate")
    if approval.get("authority_grant_mode") != (
        "CONDITIONAL_AUTONOMOUS_ACTIVATION_AFTER_EXACT_GATES"
    ):
        raise Increment9PlanError("authority grant mode differs")
    if approval.get("planning_merge_creates_live_effect") is not False:
        raise Increment9PlanError("planning merge must not create a live effect")
    conditional = approval.get("conditional_authority")
    if not isinstance(conditional, Mapping) or set(conditional) != {
        "authorised_phases",
        "effective_when",
        "further_human_approval_required",
    }:
        raise Increment9PlanError("conditional authority differs")
    if conditional.get("further_human_approval_required") is not False:
        raise Increment9PlanError("conditional authority must be autonomous")
    if tuple(conditional.get("authorised_phases", ())) != (
        "CONTRACT_IMPLEMENTATION",
        "ISOLATED_LIVE_SHADOW",
        "COMPARATOR_AND_FAULT_CAMPAIGN",
        "EVIDENCE_INTAKE",
        "SEALED_AI_REVIEW",
        "INCREMENT10_CANARY",
        "PRODUCTION_ACTIVATION",
        "AUTONOMOUS_PUBLICATION",
    ):
        raise Increment9PlanError("conditional phase inventory differs")
    if not isinstance(conditional.get("effective_when"), tuple) or not conditional.get(
        "effective_when"
    ):
        raise Increment9PlanError("conditional prerequisites differ")

    if tuple(item.issue_number for item in plan.allocations) != EXPECTED_ISSUES:
        raise Increment9PlanError("child issue inventory differs")
    if plan.waves != EXPECTED_WAVES:
        raise Increment9PlanError("dependency waves differ")
    wave_by_issue = {
        issue: wave_number
        for wave_number, issues in enumerate(plan.waves)
        for issue in issues
    }
    for allocation in plan.allocations:
        if allocation.dependencies != EXPECTED_ALLOCATION_DEPENDENCIES[
            allocation.issue_number
        ]:
            raise Increment9PlanError("allocation dependencies differ")
        if not allocation.atom or not allocation.work_kind:
            raise Increment9PlanError("allocation identity differs")
        if any(
            path.startswith("/")
            or "\\" in path
            or "/../" in f"/{path}/"
            or path in {".", ".."}
            for path in allocation.file_ownership
        ):
            raise Increment9PlanError("file ownership path differs")
        for dependency in allocation.dependencies:
            if dependency not in wave_by_issue:
                raise Increment9PlanError("dependency is outside Increment 9")
            if wave_by_issue[dependency] > wave_by_issue[allocation.issue_number]:
                raise Increment9PlanError("dependency wave precedes its dependency")
    ownership = [path for item in plan.allocations for path in item.file_ownership]
    if len(ownership) != len(set(ownership)):
        raise Increment9PlanError("file ownership overlaps")

    non_effect = plan.non_effect_authority
    _exact_keys(
        non_effect,
        {
            "allowed_now",
            "prohibited_until_exact_later_gate",
            "public_effect_authorised",
            "production_authority_mutation_authorised",
            "production_writer_routes_required_absent",
            "proof_rule",
        },
        "non_effect_authority",
    )
    if non_effect.get("public_effect_authorised") is not False:
        raise Increment9PlanError("public effect must remain unauthorised")
    if non_effect.get("production_authority_mutation_authorised") is not False:
        raise Increment9PlanError("production mutation must remain unauthorised")
    zero_tolerance = plan.frozen_rules.get("zero_tolerance_counts")
    if (
        not isinstance(zero_tolerance, Mapping)
        or set(zero_tolerance) != EXPECTED_ZERO_TOLERANCE_FIELDS
        or any(value != 0 for value in zero_tolerance.values())
    ):
        raise Increment9PlanError("zero-tolerance thresholds differ")
    _exact_keys(
        plan.frozen_rules,
        {
            "prospective_only",
            "complete_denominators_required",
            "hindsight_selection_allowed",
            "post_result_threshold_change_allowed",
            "post_result_case_substitution_allowed",
            "material_change_closes_epoch",
            "failed_partial_blocked_and_early_stopped_results_retained",
            "unchanged_failed_run_retry_allowed",
            "missing_evidence_interpretation",
            "zero_tolerance_counts",
            "effective_manifest_change_starts_new_cohort",
            "closeout_applies_to_final_manifest_only",
        },
        "frozen_rules",
    )
    if any(
        plan.frozen_rules.get(field) is not expected
        for field, expected in {
            "prospective_only": True,
            "complete_denominators_required": True,
            "hindsight_selection_allowed": False,
            "post_result_threshold_change_allowed": False,
            "post_result_case_substitution_allowed": False,
            "material_change_closes_epoch": False,
            "failed_partial_blocked_and_early_stopped_results_retained": True,
            "unchanged_failed_run_retry_allowed": False,
            "effective_manifest_change_starts_new_cohort": True,
            "closeout_applies_to_final_manifest_only": True,
        }.items()
    ):
        raise Increment9PlanError("prospective evidence rules differ")
    if (
        plan.frozen_rules.get("missing_evidence_interpretation")
        != "INCONCLUSIVE_OR_BLOCKED_NEVER_PASS"
    ):
        raise Increment9PlanError("missing evidence rule differs")

    _exact_keys(
        plan.stop_and_recovery,
        {
            "stop_precedence",
            "owner_decision_id",
            "mandatory_behaviour",
            "later_phase_after_early_stop_allowed",
        },
        "stop_and_recovery",
    )
    if plan.stop_and_recovery.get("owner_decision_id") != "OD-014":
        raise Increment9PlanError("stop owner decision differs")
    if plan.stop_and_recovery.get("later_phase_after_early_stop_allowed") is not True:
        raise Increment9PlanError("autonomous recovery evidence must remain allowed")

    _exact_keys(
        plan.gate_requirements,
        {
            "PLANNING",
            "CONTRACT",
            "ISOLATION_READINESS",
            "RUNTIME",
            "SEALED_REVIEW",
            "EXACT_MAIN_SIGNED_CLOSEOUT",
        },
        "gate_requirements",
    )
    if any(
        not isinstance(requirements, tuple) or not requirements
        for requirements in plan.gate_requirements.values()
    ):
        raise Increment9PlanError("gate requirements differ")
    if plan.outcome_vocabulary != EXPECTED_OUTCOMES:
        raise Increment9PlanError("outcome vocabulary differs")
    _exact_keys(
        plan.increment10_eligibility,
        {"automatic_transition_allowed", "required"},
        "increment10_eligibility",
    )
    if plan.increment10_eligibility.get("automatic_transition_allowed") is not True:
        raise Increment9PlanError("Increment 10 autonomous transition differs")
    required_increment10 = plan.increment10_eligibility.get("required")
    if not isinstance(required_increment10, tuple) or not required_increment10:
        raise Increment9PlanError("Increment 10 requirements differ")
    _exact_keys(
        plan.repository_baseline,
        {
            "authority",
            "derivative_systems",
            "python_requirement",
            "neo4j_driver",
            "qualified_fixture_neo4j_image",
            "graphiti_real_runtime_enabled",
            "current_operational_profile",
            "current_evaluation_plan",
            "component_blobs",
        },
        "repository_baseline",
    )
    if plan.repository_baseline.get("authority") != "SQLITE_AND_GOVERNED_OBJECTS":
        raise Increment9PlanError("repository authority differs")
    if plan.repository_baseline.get("graphiti_real_runtime_enabled") is not False:
        raise Increment9PlanError("real Graphiti must remain disabled")
    _validate_component_blobs(plan.repository_baseline)


def load_increment9_shadow_plan(path: Path) -> Increment9ShadowPlan:
    """Load the exact canonical draft plan without crossing a runtime boundary."""

    if not isinstance(path, Path):
        raise Increment9PlanError("shadow plan path must be a pathlib.Path")
    try:
        raw = path.read_bytes()
        document = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_object_without_duplicates,
        )
        canonical = canonical_json_bytes(document)
    except Increment9PlanError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, CanonicalizationError) as exc:
        raise Increment9PlanError("cannot read canonical Increment 9R plan") from exc
    if raw != canonical:
        raise Increment9PlanError("shadow plan must use exact canonical JSON")
    plan_digest = digest_bytes(raw)
    if plan_digest != EXPECTED_SHADOW_PLAN_DIGEST:
        raise Increment9PlanError("shadow plan bytes differ from reviewed v1")

    try:
        top = _mapping(document, "shadow plan")
        _exact_keys(top, {"schema_version", "payload"}, "shadow plan")
        payload = _mapping(top["payload"], "payload")
        _exact_keys(
            payload,
            {
                "plan_id",
                "plan_version",
                "issue_number",
                "parent_issue_number",
                "programme_issue_number",
                "prepared_date",
                "planning_base",
                "approval",
                "repository_baseline",
                "owner_decisions",
                "frozen_rules",
                "non_effect_authority",
                "stop_and_recovery",
                "execution_graph",
                "gate_requirements",
                "outcome_vocabulary",
                "increment10_eligibility",
            },
            "payload",
        )
        planning_base = _mapping(payload["planning_base"], "planning_base")
        _exact_keys(planning_base, set(EXPECTED_BASE), "planning_base")
        if payload["prepared_date"] != "2026-08-15":
            raise Increment9PlanError("prepared date differs")
        raw_decisions = payload["owner_decisions"]
        graph = _mapping(payload["execution_graph"], "execution_graph")
        _exact_keys(
            graph,
            {
                "allocations",
                "waves",
                "single_writer_per_branch",
                "next_wave_requires_dependencies_merged_to_main",
            },
            "execution_graph",
        )
        if graph["single_writer_per_branch"] is not True:
            raise Increment9PlanError("single-writer rule differs")
        if graph["next_wave_requires_dependencies_merged_to_main"] is not True:
            raise Increment9PlanError("dependency merge rule differs")
        raw_allocations = graph["allocations"]
        raw_waves = graph["waves"]
        if not all(isinstance(item, list) for item in (raw_decisions, raw_allocations, raw_waves)):
            raise Increment9PlanError("decision, allocation and wave inventories must be arrays")
        waves: list[tuple[int, ...]] = []
        for index, value in enumerate(raw_waves):
            wave = _mapping(value, f"execution_graph.waves[{index}]")
            _exact_keys(wave, {"wave", "issues"}, f"execution_graph.waves[{index}]")
            if _integer(wave["wave"], f"execution_graph.waves[{index}].wave") != index:
                raise Increment9PlanError("wave numbering differs")
            waves.append(_integers(wave["issues"], f"execution_graph.waves[{index}].issues"))
        plan = Increment9ShadowPlan(
            schema_version=str(top["schema_version"]),
            plan_id=str(payload["plan_id"]),
            plan_version=str(payload["plan_version"]),
            issue_number=_integer(payload["issue_number"], "issue_number"),
            parent_issue_number=_integer(payload["parent_issue_number"], "parent_issue_number"),
            programme_issue_number=_integer(
                payload["programme_issue_number"], "programme_issue_number"
            ),
            planning_base=_frozen_mapping(payload["planning_base"], "planning_base"),
            approval=_frozen_mapping(payload["approval"], "approval"),
            repository_baseline=_frozen_mapping(
                payload["repository_baseline"], "repository_baseline"
            ),
            owner_decisions=tuple(_owner_decision(item, i) for i, item in enumerate(raw_decisions)),
            frozen_rules=_frozen_mapping(payload["frozen_rules"], "frozen_rules"),
            non_effect_authority=_frozen_mapping(
                payload["non_effect_authority"], "non_effect_authority"
            ),
            stop_and_recovery=_frozen_mapping(payload["stop_and_recovery"], "stop_and_recovery"),
            allocations=tuple(_allocation(item, i) for i, item in enumerate(raw_allocations)),
            waves=tuple(waves),
            gate_requirements=_frozen_mapping(payload["gate_requirements"], "gate_requirements"),
            outcome_vocabulary=_strings(payload["outcome_vocabulary"], "outcome_vocabulary"),
            increment10_eligibility=_frozen_mapping(
                payload["increment10_eligibility"], "increment10_eligibility"
            ),
            plan_digest=plan_digest,
        )
    except (KeyError, TypeError, ValueError, CanonicalizationError) as exc:
        if isinstance(exc, Increment9PlanError):
            raise
        raise Increment9PlanError("shadow plan payload is malformed") from exc
    _validate_plan(plan)
    return plan


def require_owner_approved_plan(plan: Increment9ShadowPlan) -> None:
    """Fail closed unless the exact retained plan has explicit owner approval."""

    if not isinstance(plan, Increment9ShadowPlan):
        raise Increment9PlanError("shadow plan identity differs")
    if not plan.owner_approved:
        unresolved = ",".join(plan.unresolved_owner_decision_ids)
        raise OwnerApprovalRequired(f"owner approval required: {unresolved}")


def load_increment9_agent_profiles(path: Path) -> Mapping[str, object]:
    """Load and validate the exact provider-neutral agent profile document."""

    if not isinstance(path, Path):
        raise Increment9PlanError("agent profile path must be a pathlib.Path")
    try:
        raw = path.read_bytes()
        document = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_object_without_duplicates,
        )
        canonical = canonical_json_bytes(document)
    except Increment9PlanError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, CanonicalizationError) as exc:
        raise Increment9PlanError("cannot read canonical Increment 9 profiles") from exc
    if raw != canonical:
        raise Increment9PlanError("agent profiles must use exact canonical JSON")
    if digest_bytes(raw) != EXPECTED_AGENT_PROFILES_DIGEST:
        raise Increment9PlanError("agent profile bytes differ from reviewed v1")

    top = _mapping(document, "agent profiles")
    _exact_keys(top, {"schema_version", "payload"}, "agent profiles")
    if top["schema_version"] != "newsroom.increment9.agent-profiles.v1":
        raise Increment9PlanError("agent profile schema differs")
    payload = _mapping(top["payload"], "agent profile payload")
    _exact_keys(
        payload,
        {
            "profile_version",
            "owner",
            "transport_contract",
            "profiles",
            "result_schema",
        },
        "agent profile payload",
    )
    if payload["profile_version"] != "increment9-agent-profiles-v1":
        raise Increment9PlanError("agent profile version differs")
    if payload["owner"] != "newsroom":
        raise Increment9PlanError("agent profile owner differs")
    transport = _mapping(payload["transport_contract"], "transport contract")
    _exact_keys(
        transport,
        {
            "input",
            "output",
            "stdout_policy",
            "stderr_policy",
            "invalid_result",
            "silent_repair_allowed",
        },
        "transport contract",
    )
    if transport != {
        "input": "newsroom.increment9.hermes-input.v1",
        "output": "newsroom.increment9.hermes-result.v1",
        "stdout_policy": "ONE_SCHEMA_VALID_JSON_RESULT_ONLY",
        "stderr_policy": "EVENT_STREAM_REDACTED_TO_AUTONOMOUS_CONTROL_LEDGER",
        "invalid_result": "NOT_EVALUATED",
        "silent_repair_allowed": False,
    }:
        raise Increment9PlanError("transport contract differs")
    profiles = payload["profiles"]
    if not isinstance(profiles, list) or len(profiles) != 3:
        raise Increment9PlanError("agent profile inventory differs")
    profile_ids: list[str] = []
    for index, value in enumerate(profiles):
        profile = _mapping(value, f"profiles[{index}]")
        _exact_keys(
            profile,
            {
                "profile_id",
                "role",
                "provider",
                "model_selector",
                "memory_namespace",
                "prompt",
                "prompt_digest",
            },
            f"profiles[{index}]",
        )
        prompt = profile["prompt"]
        if not isinstance(prompt, str) or not prompt:
            raise Increment9PlanError("agent profile prompt differs")
        if digest_bytes(prompt.encode()) != profile["prompt_digest"]:
            raise Increment9PlanError("agent profile prompt digest differs")
        profile_ids.append(str(profile["profile_id"]))
    if tuple(profile_ids) != (
        "increment9-sut-v1",
        "increment9-primary-reviewer-v1",
        "increment9-adjudicator-v1",
    ):
        raise Increment9PlanError("agent profile identity differs")
    result_schema = _mapping(payload["result_schema"], "result schema")
    _exact_keys(
        result_schema,
        {"required", "statuses", "verdicts", "additional_properties"},
        "result schema",
    )
    if result_schema.get("additional_properties") is not False:
        raise Increment9PlanError("result schema must reject additional properties")
    if _strings(result_schema.get("statuses"), "result schema statuses") != (
        "SUCCESS",
        "NOT_EVALUATED",
        "FAILED",
    ):
        raise Increment9PlanError("result status vocabulary differs")
    if _strings(result_schema.get("verdicts"), "result schema verdicts") != (
        "APPROVE",
        "BLOCK",
        "INSUFFICIENT_EVIDENCE",
        "NOT_APPLICABLE",
    ):
        raise Increment9PlanError("result verdict vocabulary differs")
    return _frozen_mapping(document, "agent profiles")


INCREMENT_9_SHADOW_PLAN = load_increment9_shadow_plan(SHADOW_PLAN_PATH)
INCREMENT_9_SHADOW_PLAN_DIGEST = INCREMENT_9_SHADOW_PLAN.plan_digest
INCREMENT_9_AGENT_PROFILES = load_increment9_agent_profiles(AGENT_PROFILES_PATH)
INCREMENT_9_AGENT_PROFILES_DIGEST = EXPECTED_AGENT_PROFILES_DIGEST
