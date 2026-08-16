"""Immutable owner-approved Increment 10 local-fixture plan.

Loading this document validates reviewed bytes and returns immutable data.  It
does not grant runtime authority or perform any network, intake or publication
operation.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from newsroom.authority.canonical import CanonicalizationError, canonical_json_bytes, digest_bytes

PLAN_PATH = Path(__file__).with_name("plan_v1.json")
EXPECTED_PLAN_DIGEST = "sha256:1f5088e1397bb394e60f3ed883517cec803442572cccba3892c9f8f6ab8abc89"
EXPECTED_OWNER_DECISIONS_DIGEST = "sha256:0bd3dd2eda6bb90dede62e6c76ce52ab2ec8f1caaf3f395b676fcc7b74ac0e60"
EXPECTED_SECTION_DIGESTS = {
    "approval": "sha256:534eb84f92ed4b47b1ab3c5af5215c8964205d33055ca5d6b91a7881e0fb7b17",
    "execution_graph": "sha256:d35a652ea940d7aad97575bb4e2c856e708aab70c6b147f2f150135560a9873f",
    "gate_requirements": "sha256:55719f90ff3d31716612c5d5589cd4ddf6d67d3efcbf97834735731c57a589f1",
    "increment11_eligibility": "sha256:9c174aded4fdb7b4e8180b601fef8d8ff37304572133e4c87840d57bd7a58518",
    "non_effects": "sha256:84aaf4c24737b56784f317bf073e947e0dfe582e80955f3ba8e94f2148401663",
    "owner_decisions": EXPECTED_OWNER_DECISIONS_DIGEST,
    "planning_base": "sha256:6927a72bee648a5e689f6fd0f22db5faad805f0acf94061995807fdb4355c164",
}
EXPECTED_DECISION_IDS = tuple(f"I10-OD-{number:03d}" for number in range(1, 13))
EXPECTED_ISSUES = tuple(range(528, 537))


class Increment10PlanError(ValueError):
    """The retained Increment 10 plan is absent, changed or unsafe."""


@dataclass(frozen=True, slots=True)
class Increment10Plan:
    schema_version: str
    plan_id: str
    plan_version: str
    issue_number: int
    parent_issue_number: int
    programme_issue_number: int
    planning_base: Mapping[str, object]
    approval: Mapping[str, object]
    owner_decisions: tuple[Mapping[str, object], ...]
    execution_graph: Mapping[str, object]
    gate_requirements: Mapping[str, object]
    non_effects: Mapping[str, object]
    increment11_eligibility: Mapping[str, object]
    plan_digest: str

    @property
    def permits_runtime(self) -> bool:
        return False

    @property
    def permits_contract_implementation(self) -> bool:
        """The plan bytes alone do not prove signed exact-main closeout."""
        return False


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if type(key) is not str or key in result:
            raise Increment10PlanError("plan JSON names are invalid or duplicated")
        result[key] = value
    return result


def _object(value: object, field: str) -> dict[str, object]:
    if type(value) is not dict:
        raise Increment10PlanError(f"{field} must be an object")
    return value


def _freeze(value: object) -> object:
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


def _mapping(value: object, field: str) -> Mapping[str, object]:
    frozen = _freeze(_object(value, field))
    assert isinstance(frozen, Mapping)
    return frozen


def _validate(plan: Increment10Plan) -> None:
    if plan.schema_version != "newsroom.increment10.plan.v1":
        raise Increment10PlanError("plan schema differs")
    if plan.plan_id != "increment10-local-fixture-evidence-intake-canary-plan-v1":
        raise Increment10PlanError("plan identity differs")
    if plan.plan_version != "increment10-plan-v1-owner-approved":
        raise Increment10PlanError("plan version differs")
    if (plan.issue_number, plan.parent_issue_number, plan.programme_issue_number) != (527, 150, 141):
        raise Increment10PlanError("issue identity differs")
    if plan.planning_base != {
        "closed_issue_subject_sha256": "0c7d508f466623b3d7bffd37daa4c9c47e7b0027fd148049fbf9feb314542c75",
        "commit": "f9f483fbe47a2f1f751a44ea12b5f220c6dbfd17",
        "exact_main_run": 31939104268,
        "operational_admission": "FIXTURE_OPERATIONAL_ADMITTED",
        "requalification_digest": "sha256:0b7bf344c60e7d73490a571f6638ab46acc9194f1eabee68c1158e26da7b5747",
        "schema_version": 32,
        "tree": "33d8ae0b15d31cef3f9b7b6432fd7a348da82ec5",
    }:
        raise Increment10PlanError("planning base differs")
    if plan.approval != {
        "approval_record": "https://github.com/fol2/newsroom/issues/527#issuecomment-5306787711",
        "approved_at": "2026-08-16T09:39:01Z",
        "approved_by": "github:fol2",
        "approved_owner_decisions_digest": EXPECTED_OWNER_DECISIONS_DIGEST,
        "canary_execution_authorised": False,
        "external_effect_authorised": False,
        "implementation_authorised_after_dependencies": True,
        "planning_merge_creates_runtime": False,
        "status": "OWNER_APPROVED",
    }:
        raise Increment10PlanError("owner approval differs")
    if tuple(item["decision_id"] for item in plan.owner_decisions) != EXPECTED_DECISION_IDS:
        raise Increment10PlanError("owner decision inventory differs")
    if any(item["status"] != "APPROVED" or not item["required_bindings"] or not item["evidence_refs"] for item in plan.owner_decisions):
        raise Increment10PlanError("owner decision binding differs")
    graph = plan.execution_graph
    allocations = graph.get("allocations")
    if not isinstance(allocations, tuple) or tuple(item["issue_number"] for item in allocations) != EXPECTED_ISSUES:
        raise Increment10PlanError("allocation inventory differs")
    owned = [path for item in allocations for path in item["file_ownership"]]
    if len(owned) != len(set(owned)):
        raise Increment10PlanError("file ownership overlaps")
    completed: set[int] = {526, 527}
    for wave in graph["waves"]:
        for issue in wave:
            allocation = next(item for item in allocations if item["issue_number"] == issue)
            if not set(allocation["dependencies"]).issubset(completed):
                raise Increment10PlanError("execution dependency order differs")
        completed.update(wave)
    if any(value is not False for value in plan.non_effects.values()):
        raise Increment10PlanError("plan creates a prohibited effect")
    budgets = plan.owner_decisions[5]["selection"]["budgets"]
    for field in ("external_requests_max", "provider_requests_max", "model_input_tokens_max", "model_output_tokens_max", "embedding_units_max", "reviewer_minutes_max", "gross_gbp_minor_units_max"):
        if budgets[field] != 0:
            raise Increment10PlanError("closed-world budget differs")
    if plan.increment11_eligibility["automatic"] is not False:
        raise Increment10PlanError("Increment 11 eligibility differs")


def load_plan(path: Path = PLAN_PATH) -> Increment10Plan:
    if not isinstance(path, Path):
        raise Increment10PlanError("plan path must be pathlib.Path")
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_pairs)
    except Increment10PlanError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise Increment10PlanError("cannot read plan") from exc
    try:
        canonical = canonical_json_bytes(value)
    except (CanonicalizationError, RecursionError) as exc:
        raise Increment10PlanError("plan is outside the canonical domain") from exc
    if type(value) is not dict or canonical != raw:
        raise Increment10PlanError("plan is not exact canonical JSON")
    if digest_bytes(raw) != EXPECTED_PLAN_DIGEST:
        raise Increment10PlanError("plan bytes differ")
    try:
        if set(value) != {"schema_version", "payload"}:
            raise Increment10PlanError("plan fields differ")
        payload = _object(value["payload"], "payload")
        expected_fields = {"plan_id", "plan_version", "issue_number", "parent_issue_number", "programme_issue_number", "planning_base", "approval", "owner_decisions", "execution_graph", "gate_requirements", "non_effects", "increment11_eligibility"}
        if set(payload) != expected_fields:
            raise Increment10PlanError("plan payload fields differ")
        for field, expected in EXPECTED_SECTION_DIGESTS.items():
            if digest_bytes(canonical_json_bytes(payload[field])) != expected:
                raise Increment10PlanError(f"{field} reviewed bytes differ")
        decisions = payload["owner_decisions"]
        if type(decisions) is not list:
            raise Increment10PlanError("owner decisions must be a list")
        plan = Increment10Plan(
            schema_version=str(value["schema_version"]), plan_id=str(payload["plan_id"]), plan_version=str(payload["plan_version"]),
            issue_number=int(payload["issue_number"]), parent_issue_number=int(payload["parent_issue_number"]), programme_issue_number=int(payload["programme_issue_number"]),
            planning_base=_mapping(payload["planning_base"], "planning base"), approval=_mapping(payload["approval"], "approval"),
            owner_decisions=tuple(_mapping(item, "owner decision") for item in decisions), execution_graph=_mapping(payload["execution_graph"], "execution graph"),
            gate_requirements=_mapping(payload["gate_requirements"], "gate requirements"), non_effects=_mapping(payload["non_effects"], "non-effects"),
            increment11_eligibility=_mapping(payload["increment11_eligibility"], "Increment 11 eligibility"), plan_digest=digest_bytes(raw),
        )
        _validate(plan)
        return plan
    except Increment10PlanError:
        raise
    except (TypeError, ValueError, KeyError, StopIteration, RecursionError) as exc:
        raise Increment10PlanError("plan payload is malformed") from exc


INCREMENT_10_PLAN = load_plan()
INCREMENT_10_PLAN_DIGEST = INCREMENT_10_PLAN.plan_digest
