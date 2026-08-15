"""Canonical Increment 9R shadow plan and owner-decision gate.

Loading this module performs no network request, credential lookup, deployment,
provider/model execution or shadow run.  The retained v1 document is a draft
owner-decision packet: it deliberately fails the approval gate until every
listed live-runtime decision is bound and explicitly approved by the owner.
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
EXPECTED_SHADOW_PLAN_DIGEST = (
    "sha256:a881b3c0da08dfa8d817f54377827879f13365d94e001c867c53bca68b32dbd8"
)

EXPECTED_BASE = {
    "commit": "834250f8b0e7b5ce34e0cb54236d463429bd766e",
    "tree": "06b99d383f514db2fda95afe83f99c0e5b489ef5",
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
        selection=raw["selection"],
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
    if plan.issue_number != 488 or plan.parent_issue_number != 149:
        raise Increment9PlanError("issue identity differs")
    if dict(plan.planning_base) != EXPECTED_BASE:
        raise Increment9PlanError("accepted planning base differs")
    validate_sha256_digest(plan.plan_digest, field="plan_digest")

    decision_ids = tuple(item.decision_id for item in plan.owner_decisions)
    if decision_ids != EXPECTED_OWNER_DECISION_IDS:
        raise Increment9PlanError("owner decision inventory differs")
    if any(
        item.status != "OWNER_DECISION_REQUIRED"
        or item.selection is not None
        or item.evidence_refs
        for item in plan.owner_decisions
    ):
        raise Increment9PlanError("unapproved owner decision was invented")

    approval = plan.approval
    if approval.get("status") != "OWNER_DECISION_REQUIRED":
        raise Increment9PlanError("draft approval status differs")
    if tuple(approval.get("required_owner_decision_ids", ())) != decision_ids:
        raise Increment9PlanError("approval decision inventory differs")
    for field in (
        "approved_by",
        "approved_at",
        "approval_record",
        "approved_plan_digest",
    ):
        if approval.get(field) is not None:
            raise Increment9PlanError(f"{field} must remain unbound before owner approval")
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
            raise Increment9PlanError(f"{field} must remain false")

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
        for dependency in allocation.dependencies:
            if dependency not in wave_by_issue:
                raise Increment9PlanError("dependency is outside Increment 9")
            if wave_by_issue[dependency] > wave_by_issue[allocation.issue_number]:
                raise Increment9PlanError("dependency wave precedes its dependency")
    ownership = [path for item in plan.allocations for path in item.file_ownership]
    if len(ownership) != len(set(ownership)):
        raise Increment9PlanError("file ownership overlaps")

    non_effect = plan.non_effect_authority
    if non_effect.get("public_effect_authorised") is not False:
        raise Increment9PlanError("public effect must remain unauthorised")
    if non_effect.get("production_authority_mutation_authorised") is not False:
        raise Increment9PlanError("production mutation must remain unauthorised")
    zero_tolerance = plan.frozen_rules.get("zero_tolerance_counts")
    if not isinstance(zero_tolerance, Mapping) or any(
        value != 0 for value in zero_tolerance.values()
    ):
        raise Increment9PlanError("zero-tolerance thresholds differ")
    if plan.outcome_vocabulary != EXPECTED_OUTCOMES:
        raise Increment9PlanError("outcome vocabulary differs")
    if plan.increment10_eligibility.get("automatic_transition_allowed") is not False:
        raise Increment9PlanError("Increment 10 must not start automatically")
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
            programme_issue_number=_integer(payload["programme_issue_number"], "programme_issue_number"),
            planning_base=_frozen_mapping(payload["planning_base"], "planning_base"),
            approval=_frozen_mapping(payload["approval"], "approval"),
            repository_baseline=_frozen_mapping(payload["repository_baseline"], "repository_baseline"),
            owner_decisions=tuple(_owner_decision(item, i) for i, item in enumerate(raw_decisions)),
            frozen_rules=_frozen_mapping(payload["frozen_rules"], "frozen_rules"),
            non_effect_authority=_frozen_mapping(payload["non_effect_authority"], "non_effect_authority"),
            stop_and_recovery=_frozen_mapping(payload["stop_and_recovery"], "stop_and_recovery"),
            allocations=tuple(_allocation(item, i) for i, item in enumerate(raw_allocations)),
            waves=tuple(waves),
            gate_requirements=_frozen_mapping(payload["gate_requirements"], "gate_requirements"),
            outcome_vocabulary=_strings(payload["outcome_vocabulary"], "outcome_vocabulary"),
            increment10_eligibility=_frozen_mapping(payload["increment10_eligibility"], "increment10_eligibility"),
            plan_digest=plan_digest,
        )
    except (KeyError, TypeError, ValueError, CanonicalizationError) as exc:
        if isinstance(exc, Increment9PlanError):
            raise
        raise Increment9PlanError("shadow plan payload is malformed") from exc
    _validate_plan(plan)
    return plan


def require_owner_approved_plan(plan: Increment9ShadowPlan) -> None:
    """Fail closed until an explicitly approved successor plan is reviewed."""

    if not isinstance(plan, Increment9ShadowPlan):
        raise Increment9PlanError("shadow plan identity differs")
    if not plan.owner_approved:
        unresolved = ",".join(plan.unresolved_owner_decision_ids)
        raise OwnerApprovalRequired(f"owner approval required: {unresolved}")


INCREMENT_9_SHADOW_PLAN = load_increment9_shadow_plan(SHADOW_PLAN_PATH)
INCREMENT_9_SHADOW_PLAN_DIGEST = INCREMENT_9_SHADOW_PLAN.plan_digest
