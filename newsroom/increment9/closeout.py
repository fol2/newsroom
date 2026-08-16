"""Closed-world Increment 9G receipt and subject validators.

The closeout preserves the blocked runtime result.  It can establish completion
of the evidence process, but it cannot turn missing active coverage into
operational, canary, Increment 10 or production eligibility.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Mapping

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.increment9.decision import BlockedShadowDecision, ShadowDisposition
from newsroom.increment9.plan import INCREMENT_9_SHADOW_PLAN_DIGEST

DEPLOYMENT_RECEIPT_SCHEMA = "newsroom.increment9.closeout-deployment-receipt.v1"
RUN_INVENTORY_SCHEMA = "newsroom.increment9.closeout-run-inventory.v1"
REVIEW_REPORT_SCHEMA = "newsroom.increment9.closeout-review-metric-report.v1"
CLOSEOUT_SCHEMA = "newsroom.increment9.final-closeout.v1"
MAX_SUBJECT_BYTES = 8_388_608
EXPECTED_ISSUES = (*range(488, 498), 500, 521)
EXPECTED_DEPLOYMENT_RUN = 31_923_002_243
EXPECTED_DEPLOYMENT_HEAD = "390237b9183f5ee77da363669de3ddef964d0c32"
EXPECTED_TOPOLOGY = {
    "core_shards": 18,
    "persistent_workers_per_shard": 2,
    "required_error_count": 0,
    "required_failure_count": 0,
    "required_skip_count": 0,
    "shard_hard_seconds": 330,
    "shard_warning_seconds": 300,
    "testcase_hard_seconds": 90,
    "testcase_warning_seconds": 75,
}
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_UTC = re.compile(
    r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{6}Z\Z"
)


class Increment9CloseoutError(ValueError):
    """A retained subject or final closeout binding differs."""


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for name, item in pairs:
        if type(name) is not str or name in value:
            raise Increment9CloseoutError("closeout JSON names differ")
        value[name] = item
    return value


def exact_json(raw: bytes, *, maximum: int = MAX_SUBJECT_BYTES) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > maximum:
        raise Increment9CloseoutError("closeout subject is absent or unbounded")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
        canonical = canonical_json_bytes(value)
    except Increment9CloseoutError:
        raise
    except (
        UnicodeError,
        json.JSONDecodeError,
        CanonicalizationError,
        RecursionError,
    ) as exc:
        raise Increment9CloseoutError("closeout subject is not canonical JSON") from exc
    if canonical != raw or type(value) is not dict:
        raise Increment9CloseoutError("closeout subject bytes differ")
    return value


def _digest(value: object, field: str) -> str:
    if type(value) is not str:
        raise Increment9CloseoutError(f"{field} digest differs")
    try:
        return validate_sha256_digest(value, field=field)
    except (CanonicalizationError, TypeError, ValueError) as exc:
        raise Increment9CloseoutError(f"{field} digest differs") from exc


def _sha(value: object, field: str) -> str:
    if type(value) is not str or not _HEX40.fullmatch(value):
        raise Increment9CloseoutError(f"{field} SHA differs")
    return value


def _timestamp(value: object, field: str) -> str:
    if type(value) is not str or not _UTC.fullmatch(value):
        raise Increment9CloseoutError(f"{field} timestamp differs")
    return value


def _component(value: Mapping[str, object]) -> dict[str, object]:
    raw = canonical_json_bytes(dict(value))
    return {"canonical_digest": digest_bytes(raw), "file_sha256": digest_bytes(raw)}


def validate_sdlc_decision(
    value: Mapping[str, object], *, head: str, tree: str
) -> str:
    if value.get("schema_version") != "newsroom.sdlc.shadow-decision.v1" or value.get("result") != "PASS":
        raise Increment9CloseoutError("SDLC decision is not PASS")
    context = value.get("context")
    totals = value.get("totals")
    lanes = value.get("lanes")
    if not isinstance(context, Mapping) or not isinstance(totals, Mapping) or not isinstance(lanes, list):
        raise Increment9CloseoutError("SDLC decision structure differs")
    if (
        context.get("evaluated_sha") != head
        or context.get("evaluated_tree_sha") != tree
        or context.get("event_name") != "workflow_dispatch"
        or context.get("ref") != "refs/heads/main"
    ):
        raise Increment9CloseoutError("SDLC decision is not exact main")
    if (
        totals.get("failure_count") != 0
        or totals.get("error_count") != 0
        or totals.get("required_skip_count") != 0
        or not isinstance(totals.get("test_count"), int)
        or totals["test_count"] < 4_024
    ):
        raise Increment9CloseoutError("SDLC totals differ")
    if {item.get("lane_id") for item in lanes if isinstance(item, Mapping)} != {"core", "service"}:
        raise Increment9CloseoutError("exact-main actual-service lane is absent")
    return _digest(value.get("decision_identity"), "SDLC decision identity")


def build_deployment_receipt(
    *, readiness: Mapping[str, object], restart: Mapping[str, object]
) -> dict[str, object]:
    if (
        readiness.get("server_name") != "Neo4j Kernel"
        or readiness.get("server_version") != "5.26.2"
        or readiness.get("edition") != "community"
        or readiness.get("database") != "increment9"
        or readiness.get("namespace") != "increment9_shadow"
        or readiness.get("remaining_probe_indexes") != 0
        or readiness.get("remaining_probe_nodes") != 0
        or readiness.get("secret_value_count") != 0
        or restart.get("server_version") != "5.26.2"
        or restart.get("restart_count") != 1
        or restart.get("remaining_probe_indexes") != 0
        or restart.get("remaining_probe_nodes") != 0
        or restart.get("secret_value_count") != 0
    ):
        raise Increment9CloseoutError("deployment readiness subject differs")
    readiness_digest = _digest(readiness.get("evidence_digest"), "readiness evidence")
    restart_digest = _digest(restart.get("evidence_digest"), "restart evidence")
    body = {
        "actual_service_ready": True,
        "deployment_head": EXPECTED_DEPLOYMENT_HEAD,
        "deployment_run_id": EXPECTED_DEPLOYMENT_RUN,
        "issue_number": 490,
        "production_nonmutation": True,
        "readiness_evidence_digest": readiness_digest,
        "readiness_file_digest": digest_bytes(canonical_json_bytes(dict(readiness))),
        "restart_evidence_digest": restart_digest,
        "restart_file_digest": digest_bytes(canonical_json_bytes(dict(restart))),
        "schema_version": DEPLOYMENT_RECEIPT_SCHEMA,
        "secret_value_count": 0,
        "teardown_residual_count": 0,
    }
    return {**body, "receipt_digest": digest_bytes(canonical_json_bytes(body))}


def build_run_inventory(
    *, campaign: Mapping[str, object], fault: Mapping[str, object]
) -> dict[str, object]:
    launch = campaign.get("launch_receipt")
    campaign_outcome = campaign.get("outcome")
    fault_outcome = fault.get("outcome")
    phases = fault.get("phase_inventory")
    if not all(isinstance(item, Mapping) for item in (launch, campaign_outcome, fault_outcome)) or not isinstance(phases, list):
        raise Increment9CloseoutError("runtime inventory structure differs")
    if (
        launch.get("disposition") != "BLOCKED_BEFORE_FIRST_IO"
        or campaign_outcome.get("outcome") != "BLOCKED"
        or campaign_outcome.get("run_attempt_inventory") != []
        or fault_outcome.get("campaign_outcome") != "BLOCKED"
        or fault_outcome.get("executed_phase_count") != 0
        or fault_outcome.get("not_run_phase_count") != 26
        or len(phases) != 26
    ):
        raise Increment9CloseoutError("runtime stop inventory differs")
    body = {
        "attempts": [],
        "campaign_bundle_digest": _digest(campaign.get("bundle_digest"), "campaign bundle"),
        "campaign_outcome": "BLOCKED",
        "checkpoints": [],
        "complete_denominators": True,
        "decision_bearing_case_count": 0,
        "fault_bundle_digest": _digest(fault.get("bundle_digest"), "fault bundle"),
        "fault_executed_count": 0,
        "fault_not_run_count": 26,
        "gross_gbp_minor_units": 0,
        "inventory_reconciled": True,
        "original_stop_retained": True,
        "runs": [],
        "schema_version": RUN_INVENTORY_SCHEMA,
        "source_http_attempts": 0,
    }
    return {**body, "inventory_digest": digest_bytes(canonical_json_bytes(body))}


def build_review_report(decision: BlockedShadowDecision) -> dict[str, object]:
    if decision.disposition is not ShadowDisposition.BLOCKED_ACTIVE_COVERAGE:
        raise Increment9CloseoutError("review disposition differs")
    body = {
        "ablation_count": len(decision.ablations),
        "all_values_not_evaluated": True,
        "cost_and_capacity": dict(decision.cost_and_capacity),
        "decision_digest": decision.canonical_digest,
        "disposition": decision.disposition.value,
        "metric_count": len(decision.metrics),
        "production_equivalence_claim_permitted": False,
        "reviewer_count": len(decision.reviewers),
        "reviewer_invocation_count": sum(item.invocation_count for item in decision.reviewers),
        "schema_version": REVIEW_REPORT_SCHEMA,
        "slice_count": len(decision.slices),
        "zero_tolerance_count": len(decision.zero_tolerance),
        "zero_tolerance_pass_claimed": False,
    }
    return {**body, "report_digest": digest_bytes(canonical_json_bytes(body))}


@dataclass(frozen=True, slots=True)
class CloseoutInputs:
    exact_main_sha: str
    exact_main_tree: str
    closed_at: str
    issue_evidence_digest: str
    sdlc_decision_identity: str
    plan_file_digest: str
    deployment_receipt_digest: str
    run_inventory_digest: str
    review_report_digest: str
    shadow_decision_digest: str
    topology: Mapping[str, object]
    production_nonmutation: bool
    public_effect_count: int
    residual_blockers: tuple[str, ...]


def build_closeout_receipt(inputs: CloseoutInputs) -> dict[str, object]:
    _sha(inputs.exact_main_sha, "closeout main")
    _sha(inputs.exact_main_tree, "closeout tree")
    _timestamp(inputs.closed_at, "closeout time")
    for field in (
        "issue_evidence_digest",
        "sdlc_decision_identity",
        "plan_file_digest",
        "deployment_receipt_digest",
        "run_inventory_digest",
        "review_report_digest",
        "shadow_decision_digest",
    ):
        _digest(getattr(inputs, field), field)
    if dict(inputs.topology) != EXPECTED_TOPOLOGY:
        raise Increment9CloseoutError("accepted topology differs")
    if (
        inputs.production_nonmutation is not True
        or inputs.public_effect_count != 0
        or not inputs.residual_blockers
        or inputs.residual_blockers != tuple(sorted(set(inputs.residual_blockers)))
    ):
        raise Increment9CloseoutError("blocked closeout boundary differs")
    body = {
        "closed_at": inputs.closed_at,
        "completion_status": "INCREMENT9_EVIDENCE_PROCESS_CLOSED",
        "deployment_receipt_digest": inputs.deployment_receipt_digest,
        "downstream": {
            "increment10_eligible": False,
            "reason": "BLOCKED_ACTIVE_COVERAGE",
            "separate_increment10_plan_authorised": False,
        },
        "exact_main_sha": inputs.exact_main_sha,
        "exact_main_tree": inputs.exact_main_tree,
        "issue_evidence_digest": inputs.issue_evidence_digest,
        "non_effects": {
            "canary": False,
            "evidence_intake": False,
            "production_activation": False,
            "production_mutation": False,
            "publication": False,
            "public_effect_count": inputs.public_effect_count,
        },
        "owner_plan_digest": INCREMENT_9_SHADOW_PLAN_DIGEST,
        "plan_file_digest": inputs.plan_file_digest,
        "production_nonmutation": inputs.production_nonmutation,
        "residual_blockers": list(inputs.residual_blockers),
        "review_report_digest": inputs.review_report_digest,
        "run_inventory_digest": inputs.run_inventory_digest,
        "schema_version": CLOSEOUT_SCHEMA,
        "sdlc_decision_identity": inputs.sdlc_decision_identity,
        "shadow_decision_digest": inputs.shadow_decision_digest,
        "shadow_disposition": "BLOCKED_ACTIVE_COVERAGE",
        "signed_subjects_required": True,
        "topology": dict(inputs.topology),
    }
    return {**body, "closeout_digest": digest_bytes(canonical_json_bytes(body))}


def verify_closeout_receipt(raw: bytes) -> dict[str, object]:
    value = exact_json(raw)
    if value.get("schema_version") != CLOSEOUT_SCHEMA:
        raise Increment9CloseoutError("closeout schema differs")
    body = dict(value)
    claimed = _digest(body.pop("closeout_digest", None), "closeout digest")
    if digest_bytes(canonical_json_bytes(body)) != claimed:
        raise Increment9CloseoutError("closeout digest differs")
    if (
        value.get("shadow_disposition") != "BLOCKED_ACTIVE_COVERAGE"
        or value.get("production_nonmutation") is not True
        or value.get("signed_subjects_required") is not True
        or value.get("downstream")
        != {
            "increment10_eligible": False,
            "reason": "BLOCKED_ACTIVE_COVERAGE",
            "separate_increment10_plan_authorised": False,
        }
    ):
        raise Increment9CloseoutError("closeout outcome differs")
    return value
