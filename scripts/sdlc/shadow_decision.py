from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Mapping, Sequence

from .artifact_envelope import (
    ArtifactProvenanceError,
    GithubRunContext,
    _context_from_mapping,
    _safe_machine_file,
    _unique_object,
    _validate_context,
    _validate_json_depth,
)
from .contracts import ContractError, SdlcContract, load_contract
from .emit_evidence import EvidenceError, canonical_json_bytes, sha256_identity
from .shadow_lane import (
    ShadowLaneError,
    ShadowLaneRecord,
    validate_shadow_lane_record,
)
from .workflow_event import (
    WorkflowEvent,
    WorkflowEvidenceError,
    validate_workflow_event,
)


SCHEMA_VERSION = "newsroom.sdlc.shadow-decision.v1"
POLICY_VERSION = "sdlc-shadow-decision-v1"
TOTALS_SCHEMA_VERSION = "newsroom.sdlc.shadow-totals.v1"
FAILURE_SCHEMA_VERSION = "newsroom.sdlc.shadow-failure.v1"
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_SAFE_ID = re.compile(r"[A-Za-z0-9_.-]{1,128}")
_ALLOWED_RESULTS = frozenset(
    {
        "PASS",
        "FAIL",
        "BUDGET_EXCEEDED",
        "CLASSIFIER_ERROR",
        "ENVIRONMENT_ERROR",
        "EVIDENCE_MISMATCH",
        "UNAUTHORISED_EFFECT",
    }
)
_RESULT_PRECEDENCE = {
    "PASS": 0,
    "FAIL": 1,
    "BUDGET_EXCEEDED": 2,
    "CLASSIFIER_ERROR": 3,
    "ENVIRONMENT_ERROR": 4,
    "EVIDENCE_MISMATCH": 5,
    "UNAUTHORISED_EFFECT": 6,
}
_DECISION_KEYS = frozenset(
    {
        "schema_version",
        "policy_version",
        "decision_identity",
        "result",
        "result_reason",
        "context",
        "event",
        "lanes",
        "totals",
        "first_failure",
    }
)
_TOTAL_KEYS = frozenset(
    {
        "schema_version",
        "queue_max_ms",
        "bootstrap_max_ms",
        "execution_max_ms",
        "finalize_max_ms",
        "test_count",
        "failure_count",
        "error_count",
        "skip_count",
        "required_skip_count",
    }
)
_FAILURE_KEYS = frozenset(
    {
        "schema_version",
        "lane_id",
        "gate_id",
        "phase",
        "result",
        "result_reason",
        "first_failure_fingerprint",
    }
)


class ShadowDecisionError(ValueError):
    """Raised when exact shadow evidence cannot yield a trustworthy decision."""


@dataclass(frozen=True)
class DecisionTotals:
    queue_max_ms: int
    bootstrap_max_ms: int
    execution_max_ms: int
    finalize_max_ms: int
    test_count: int
    failure_count: int
    error_count: int
    skip_count: int
    required_skip_count: int

    def __post_init__(self) -> None:
        for name, value in self.as_dict().items():
            if name == "schema_version":
                continue
            _nonnegative(value, name)
        if self.required_skip_count > self.skip_count:
            raise ShadowDecisionError("totals_required_skip")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": TOTALS_SCHEMA_VERSION,
            "queue_max_ms": self.queue_max_ms,
            "bootstrap_max_ms": self.bootstrap_max_ms,
            "execution_max_ms": self.execution_max_ms,
            "finalize_max_ms": self.finalize_max_ms,
            "test_count": self.test_count,
            "failure_count": self.failure_count,
            "error_count": self.error_count,
            "skip_count": self.skip_count,
            "required_skip_count": self.required_skip_count,
        }


@dataclass(frozen=True)
class FailureSummary:
    lane_id: str
    gate_id: str
    phase: str
    result: str
    result_reason: str
    first_failure_fingerprint: str | None

    def __post_init__(self) -> None:
        _identifier(self.lane_id, "failure_lane")
        _identifier(self.gate_id, "failure_gate")
        _identifier(self.phase, "failure_phase")
        if _result(self.result, "failure_result") == "PASS":
            raise ShadowDecisionError("failure_result")
        reason = _text(self.result_reason, "failure_reason", maximum=512)
        if not reason.startswith(self.result + ":"):
            raise ShadowDecisionError("failure_reason")
        if self.first_failure_fingerprint is not None:
            _sha(self.first_failure_fingerprint, "failure_fingerprint")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": FAILURE_SCHEMA_VERSION,
            "lane_id": self.lane_id,
            "gate_id": self.gate_id,
            "phase": self.phase,
            "result": self.result,
            "result_reason": self.result_reason,
            "first_failure_fingerprint": self.first_failure_fingerprint,
        }


@dataclass(frozen=True)
class ShadowDecision:
    result: str
    result_reason: str
    context: GithubRunContext
    event: WorkflowEvent | None
    lanes: tuple[ShadowLaneRecord, ...]
    totals: DecisionTotals
    first_failure: FailureSummary | None
    decision_identity: str

    def __post_init__(self) -> None:
        _result(self.result, "result")
        reason = _text(self.result_reason, "result_reason", maximum=512)
        if not reason.startswith(self.result + ":"):
            raise ShadowDecisionError("result_reason")
        try:
            _validate_context(self.context)
        except ArtifactProvenanceError as exc:
            raise ShadowDecisionError("context") from exc
        if self.context.job_id != "decision":
            raise ShadowDecisionError("decision_job")
        if not isinstance(self.totals, DecisionTotals):
            raise ShadowDecisionError("totals")
        if self.event is not None and not isinstance(self.event, WorkflowEvent):
            raise ShadowDecisionError("event")
        if not isinstance(self.lanes, tuple) or len(self.lanes) > 2:
            raise ShadowDecisionError("lanes")
        try:
            lane_ids = tuple(lane.lane_id for lane in self.lanes)
        except AttributeError as exc:
            raise ShadowDecisionError("lanes") from exc
        if tuple(sorted(lane_ids)) != lane_ids or len(set(lane_ids)) != len(lane_ids):
            raise ShadowDecisionError("lanes")
        if self.first_failure is not None and not isinstance(
            self.first_failure, FailureSummary
        ):
            raise ShadowDecisionError("first_failure")
        if self.lanes:
            if self.event is None or "core" not in set(lane_ids):
                raise ShadowDecisionError("lane_event")
            if (self.result == "PASS") is not (self.first_failure is None):
                raise ShadowDecisionError("first_failure")
            if self.first_failure is not None:
                if self.first_failure.result != self.result:
                    raise ShadowDecisionError("first_failure")
                expected_reason = (
                    f"{self.result}:decision:{self.first_failure.lane_id}:"
                    f"{self.first_failure.gate_id}:{self.first_failure.phase}"
                )
                if self.result_reason != expected_reason:
                    raise ShadowDecisionError("first_failure")
        elif (
            self.event is not None
            or self.result == "PASS"
            or self.first_failure is None
            or self.first_failure.lane_id != "decision"
            or self.first_failure.result != self.result
            or self.first_failure.result_reason != self.result_reason
        ):
            raise ShadowDecisionError("failure_record")
        identity = _sha(self.decision_identity, "decision_identity")
        if identity != sha256_identity(_identity_inputs(self)):
            raise ShadowDecisionError("decision_identity")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "policy_version": POLICY_VERSION,
            "decision_identity": self.decision_identity,
            "result": self.result,
            "result_reason": self.result_reason,
            "context": self.context.as_dict(),
            "event": None if self.event is None else self.event.as_dict(),
            "lanes": [lane.as_dict() for lane in self.lanes],
            "totals": self.totals.as_dict(),
            "first_failure": (
                None if self.first_failure is None else self.first_failure.as_dict()
            ),
        }


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ShadowDecisionError(code)
    return value


def _text(value: object, code: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ShadowDecisionError(code)
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ShadowDecisionError(code)
    return value


def _identifier(value: object, code: str) -> str:
    text = _text(value, code, maximum=128)
    if _SAFE_ID.fullmatch(text) is None:
        raise ShadowDecisionError(code)
    return text


def _sha(value: object, code: str) -> str:
    text = _text(value, code, maximum=71)
    if _SHA256.fullmatch(text) is None:
        raise ShadowDecisionError(code)
    return text


def _nonnegative(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ShadowDecisionError(code)
    return value


def _result(value: object, code: str) -> str:
    result = _identifier(value, code)
    if result not in _ALLOWED_RESULTS:
        raise ShadowDecisionError(code)
    return result


def _contract_limits(contract: SdlcContract) -> tuple[int, int]:
    global_value = _mapping(contract.data.get("global"), "contract_global")
    lane = global_value.get("lane_execution_timeout_seconds")
    finalize = global_value.get("finalization_timeout_seconds")
    if (
        isinstance(lane, bool)
        or not isinstance(lane, int)
        or lane <= 0
        or isinstance(finalize, bool)
        or not isinstance(finalize, int)
        or finalize <= 0
    ):
        raise ShadowDecisionError("contract_budget")
    return lane * 1000, finalize * 1000


def _context_matches_event(context: GithubRunContext, event: WorkflowEvent) -> None:
    if (
        event.repository != context.repository
        or event.repository_id != context.repository_id
        or event.head_repository != context.head_repository
        or event.head_repository_id != context.head_repository_id
        or event.event_name != context.event_name
        or event.event_sha != context.event_sha
        or event.evaluated_sha != context.evaluated_sha
        or event.evaluated_tree_sha != context.evaluated_tree_sha
        or event.ref != context.ref
    ):
        raise ShadowDecisionError("event_context")


def _lane_matches_context(
    lane: ShadowLaneRecord,
    *,
    context: GithubRunContext,
    event: WorkflowEvent,
) -> None:
    receipt = lane.receipt
    replay = lane.replay
    if (
        receipt.repository != context.repository
        or receipt.repository_id != context.repository_id
        or receipt.head_repository != context.head_repository
        or receipt.head_repository_id != context.head_repository_id
        or receipt.metadata.run_id != context.run_id
        or receipt.run_attempt != context.run_attempt
        or receipt.consumer_job_id != context.job_id
        or receipt.workflow_ref != context.workflow_ref
        or receipt.workflow_sha != context.workflow_sha
        or receipt.event_name != context.event_name
        or receipt.event_sha != context.event_sha
        or receipt.evaluated_sha != context.evaluated_sha
        or receipt.evaluated_tree_sha != context.evaluated_tree_sha
        or receipt.ref != context.ref
        or receipt.route.base_sha != event.base_sha
        or receipt.route.base_tree_sha != event.base_tree_sha
        or replay.run_id != context.run_id
        or replay.run_attempt != context.run_attempt
        or replay.repository_id != context.repository_id
        or replay.head_repository_id != context.head_repository_id
        or replay.head_sha != context.evaluated_sha
        or lane.run_event != context.event_name
    ):
        raise ShadowDecisionError("lane_context")


def _normalize_lanes(
    *,
    context: GithubRunContext,
    event: WorkflowEvent,
    core: ShadowLaneRecord,
    service: ShadowLaneRecord | None,
    contract: SdlcContract,
) -> tuple[ShadowLaneRecord, ...]:
    try:
        normalized_core = validate_shadow_lane_record(core.as_dict(), contract=contract)
    except ShadowLaneError as exc:
        raise ShadowDecisionError("core_lane") from exc
    if normalized_core.lane_id != "core":
        raise ShadowDecisionError("core_lane")
    _lane_matches_context(normalized_core, context=context, event=event)
    route = normalized_core.receipt.route
    if route.service_required != (service is not None):
        raise ShadowDecisionError(
            "service_lane_missing" if route.service_required else "service_lane_unexpected"
        )
    lanes = [normalized_core]
    if service is not None:
        try:
            normalized_service = validate_shadow_lane_record(
                service.as_dict(), contract=contract
            )
        except ShadowLaneError as exc:
            raise ShadowDecisionError("service_lane") from exc
        if normalized_service.lane_id != "service":
            raise ShadowDecisionError("service_lane")
        _lane_matches_context(normalized_service, context=context, event=event)
        if normalized_service.receipt.route.as_dict() != route.as_dict():
            raise ShadowDecisionError("route_mismatch")
        if normalized_service.run_created_at != normalized_core.run_created_at:
            raise ShadowDecisionError("run_created_at_mismatch")
        lanes.append(normalized_service)
    ordered = tuple(sorted(lanes, key=lambda item: item.lane_id))
    if len({lane.lane_identity for lane in ordered}) != len(ordered):
        raise ShadowDecisionError("lane_identity_duplicate")
    if len({lane.replay.replay_identity for lane in ordered}) != len(ordered):
        raise ShadowDecisionError("replay_identity_duplicate")
    if len({lane.receipt.receipt_identity for lane in ordered}) != len(ordered):
        raise ShadowDecisionError("receipt_identity_duplicate")
    if len({lane.receipt.metadata.artifact_id for lane in ordered}) != len(ordered):
        raise ShadowDecisionError("artifact_id_duplicate")
    if len({lane.telemetry.job_id for lane in ordered}) != len(ordered):
        raise ShadowDecisionError("telemetry_job_duplicate")
    return ordered


def _totals(lanes: tuple[ShadowLaneRecord, ...]) -> DecisionTotals:
    decisions = [decision for lane in lanes for decision in lane.receipt.gate_decisions]
    return DecisionTotals(
        queue_max_ms=max((lane.telemetry.queue_ms for lane in lanes), default=0),
        bootstrap_max_ms=max(
            (lane.telemetry.bootstrap_ms for lane in lanes), default=0
        ),
        execution_max_ms=max(
            (
                sum(item.execution_ms for item in lane.receipt.gate_decisions)
                for lane in lanes
            ),
            default=0,
        ),
        finalize_max_ms=max(
            (lane.telemetry.finalize_ms for lane in lanes), default=0
        ),
        test_count=sum(item.test_count for item in decisions),
        failure_count=sum(item.failure_count for item in decisions),
        error_count=sum(item.error_count for item in decisions),
        skip_count=sum(item.skip_count for item in decisions),
        required_skip_count=sum(item.required_skip_count for item in decisions),
    )


def _failure(
    lane_id: str,
    gate_id: str,
    phase: str,
    result: str,
    reason: str,
    fingerprint: str | None = None,
) -> FailureSummary:
    return FailureSummary(lane_id, gate_id, phase, result, reason, fingerprint)


def _gate_failure(lane: ShadowLaneRecord) -> FailureSummary | None:
    failed = [item for item in lane.receipt.gate_decisions if item.result != "PASS"]
    if not failed:
        return None
    selected = sorted(
        failed,
        key=lambda item: (
            -_RESULT_PRECEDENCE[item.result],
            item.gate_id,
            item.phase,
            item.result_reason,
        ),
    )[0]
    return _failure(
        lane.lane_id,
        selected.gate_id,
        selected.phase,
        selected.result,
        selected.result_reason,
        selected.first_failure_fingerprint,
    )


def _derive_result(
    lanes: tuple[ShadowLaneRecord, ...], *, contract: SdlcContract
) -> tuple[str, str, FailureSummary | None]:
    lane_budget_ms, finalize_budget_ms = _contract_limits(contract)
    failures = [failure for lane in lanes if (failure := _gate_failure(lane))]
    for lane in lanes:
        if lane.telemetry.job_conclusion != "success":
            failures.append(
                _failure(
                    lane.lane_id,
                    "job-conclusion",
                    "complete",
                    "ENVIRONMENT_ERROR",
                    f"ENVIRONMENT_ERROR:{lane.lane_id}:job-conclusion",
                )
            )
        execution = sum(item.execution_ms for item in lane.receipt.gate_decisions)
        if execution > lane_budget_ms:
            failures.append(
                _failure(
                    lane.lane_id,
                    "lane-budget",
                    "execution",
                    "BUDGET_EXCEEDED",
                    f"BUDGET_EXCEEDED:{lane.lane_id}:execution",
                )
            )
        if lane.telemetry.finalize_ms > finalize_budget_ms:
            failures.append(
                _failure(
                    lane.lane_id,
                    "lane-budget",
                    "finalize",
                    "BUDGET_EXCEEDED",
                    f"BUDGET_EXCEEDED:{lane.lane_id}:finalize",
                )
            )
    if lanes[0].receipt.route.owner_authority_required:
        failures.append(
            _failure(
                "decision",
                "owner-authority",
                "policy",
                "UNAUTHORISED_EFFECT",
                "UNAUTHORISED_EFFECT:decision:owner-authority-required",
            )
        )
    if not failures:
        return "PASS", "PASS:decision", None
    selected = sorted(
        failures,
        key=lambda item: (
            -_RESULT_PRECEDENCE[item.result],
            item.lane_id,
            item.gate_id,
            item.phase,
            item.result_reason,
        ),
    )[0]
    return (
        selected.result,
        f"{selected.result}:decision:{selected.lane_id}:{selected.gate_id}:{selected.phase}",
        selected,
    )


def _identity_inputs(decision: ShadowDecision) -> dict[str, object]:
    value = decision.as_dict()
    value.pop("decision_identity")
    return value


def _build(
    *,
    result: str,
    reason: str,
    context: GithubRunContext,
    event: WorkflowEvent | None,
    lanes: tuple[ShadowLaneRecord, ...],
    totals: DecisionTotals,
    first_failure: FailureSummary | None,
) -> ShadowDecision:
    identity_inputs = {
        "schema_version": SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "result": result,
        "result_reason": reason,
        "context": context.as_dict(),
        "event": None if event is None else event.as_dict(),
        "lanes": [lane.as_dict() for lane in lanes],
        "totals": totals.as_dict(),
        "first_failure": (
            None if first_failure is None else first_failure.as_dict()
        ),
    }
    return ShadowDecision(
        result,
        reason,
        context,
        event,
        lanes,
        totals,
        first_failure,
        sha256_identity(identity_inputs),
    )


def aggregate_shadow_decision(
    *,
    context: GithubRunContext,
    event: WorkflowEvent,
    core: ShadowLaneRecord,
    service: ShadowLaneRecord | None,
    contract: SdlcContract,
) -> ShadowDecision:
    try:
        normalized_context = _validate_context(context)
        normalized_event = validate_workflow_event(event.as_dict())
    except (ArtifactProvenanceError, WorkflowEvidenceError) as exc:
        raise ShadowDecisionError("context_or_event") from exc
    if normalized_context.job_id != "decision":
        raise ShadowDecisionError("decision_job")
    _context_matches_event(normalized_context, normalized_event)
    lanes = _normalize_lanes(
        context=normalized_context,
        event=normalized_event,
        core=core,
        service=service,
        contract=contract,
    )
    result, reason, first = _derive_result(lanes, contract=contract)
    decision = _build(
        result=result,
        reason=reason,
        context=normalized_context,
        event=normalized_event,
        lanes=lanes,
        totals=_totals(lanes),
        first_failure=first,
    )
    return validate_shadow_decision(decision.as_dict(), contract=contract)


def failure_shadow_decision(
    *, context: GithubRunContext, code: str, result: str = "EVIDENCE_MISMATCH"
) -> ShadowDecision:
    try:
        normalized_context = _validate_context(context)
    except ArtifactProvenanceError as exc:
        raise ShadowDecisionError("context") from exc
    if normalized_context.job_id != "decision":
        raise ShadowDecisionError("decision_job")
    selected = _result(result, "failure_result")
    if selected == "PASS":
        raise ShadowDecisionError("failure_result")
    suffix = _identifier(code, "failure_code")
    reason = f"{selected}:decision:{suffix}"
    first = _failure(
        "decision", "decision-input", "validation", selected, reason
    )
    return _build(
        result=selected,
        reason=reason,
        context=normalized_context,
        event=None,
        lanes=(),
        totals=_totals(()),
        first_failure=first,
    )


def _parse_failure(value: object) -> FailureSummary:
    item = _mapping(value, "first_failure")
    if frozenset(item) != _FAILURE_KEYS or item.get("schema_version") != FAILURE_SCHEMA_VERSION:
        raise ShadowDecisionError("failure_shape")
    fingerprint = item.get("first_failure_fingerprint")
    return FailureSummary(
        lane_id=_identifier(item.get("lane_id"), "failure_lane"),
        gate_id=_identifier(item.get("gate_id"), "failure_gate"),
        phase=_identifier(item.get("phase"), "failure_phase"),
        result=_result(item.get("result"), "failure_result"),
        result_reason=_text(item.get("result_reason"), "failure_reason", maximum=512),
        first_failure_fingerprint=(
            None if fingerprint is None else _sha(fingerprint, "failure_fingerprint")
        ),
    )


def _parse_totals(value: object) -> DecisionTotals:
    item = _mapping(value, "totals")
    if frozenset(item) != _TOTAL_KEYS or item.get("schema_version") != TOTALS_SCHEMA_VERSION:
        raise ShadowDecisionError("totals_shape")
    return DecisionTotals(
        *(
            _nonnegative(item.get(name), name)
            for name in (
                "queue_max_ms",
                "bootstrap_max_ms",
                "execution_max_ms",
                "finalize_max_ms",
                "test_count",
                "failure_count",
                "error_count",
                "skip_count",
                "required_skip_count",
            )
        )
    )


def validate_shadow_decision(
    value: object, *, contract: SdlcContract
) -> ShadowDecision:
    item = _mapping(value, "decision")
    if frozenset(item) != _DECISION_KEYS:
        raise ShadowDecisionError("decision_shape")
    if (
        item.get("schema_version") != SCHEMA_VERSION
        or item.get("policy_version") != POLICY_VERSION
    ):
        raise ShadowDecisionError("decision_schema")
    try:
        context = _context_from_mapping(item.get("context"))
    except ArtifactProvenanceError as exc:
        raise ShadowDecisionError("context") from exc
    if context.job_id != "decision":
        raise ShadowDecisionError("decision_job")
    result = _result(item.get("result"), "result")
    reason = _text(item.get("result_reason"), "result_reason", maximum=512)
    if not reason.startswith(result + ":"):
        raise ShadowDecisionError("result_reason")
    event_value = item.get("event")
    event = None
    if event_value is not None:
        try:
            event = validate_workflow_event(event_value)
        except WorkflowEvidenceError as exc:
            raise ShadowDecisionError("event") from exc
        _context_matches_event(context, event)
    raw_lanes = item.get("lanes")
    if not isinstance(raw_lanes, list) or len(raw_lanes) > 2:
        raise ShadowDecisionError("lanes")
    try:
        lanes = tuple(
            validate_shadow_lane_record(value, contract=contract)
            for value in raw_lanes
        )
    except ShadowLaneError as exc:
        raise ShadowDecisionError("lanes") from exc
    if tuple(sorted(lanes, key=lambda lane: lane.lane_id)) != lanes:
        raise ShadowDecisionError("lanes")
    totals = _parse_totals(item.get("totals"))
    if totals != _totals(lanes):
        raise ShadowDecisionError("totals")
    raw_failure = item.get("first_failure")
    first = None if raw_failure is None else _parse_failure(raw_failure)
    if lanes:
        if event is None or {lane.lane_id for lane in lanes} not in (
            {"core"},
            {"core", "service"},
        ):
            raise ShadowDecisionError("lane_event")
        normalized = _normalize_lanes(
            context=context,
            event=event,
            core=next(lane for lane in lanes if lane.lane_id == "core"),
            service=next(
                (lane for lane in lanes if lane.lane_id == "service"), None
            ),
            contract=contract,
        )
        if normalized != lanes:
            raise ShadowDecisionError("lanes")
        expected = _derive_result(lanes, contract=contract)
        if (result, reason, first) != expected:
            raise ShadowDecisionError("decision_result")
    else:
        if (
            event is not None
            or result == "PASS"
            or first is None
            or first.result != result
            or first.result_reason != reason
            or first.lane_id != "decision"
        ):
            raise ShadowDecisionError("failure_record")
    decision = ShadowDecision(
        result=result,
        result_reason=reason,
        context=context,
        event=event,
        lanes=lanes,
        totals=totals,
        first_failure=first,
        decision_identity=_sha(item.get("decision_identity"), "decision_identity"),
    )
    if decision.decision_identity != sha256_identity(_identity_inputs(decision)):
        raise ShadowDecisionError("decision_identity")
    return decision


def _load_json(root: Path, value: str | Path) -> object:
    candidate = Path(value)
    path = candidate if candidate.is_absolute() else root / candidate
    payload = _safe_machine_file(path, maximum=32 * 1024 * 1024, code="input_file")
    try:
        parsed = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
        _validate_json_depth(parsed)
    except (UnicodeError, json.JSONDecodeError, ArtifactProvenanceError) as exc:
        raise ShadowDecisionError("input_json") from exc
    return parsed


def _safe_output(root: Path, relative: str | Path) -> Path:
    candidate = Path(relative)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or ".." in candidate.parts
        or "\\" in str(relative)
        or candidate.suffix != ".json"
    ):
        raise ShadowDecisionError("output_path")
    current = root
    for part in candidate.parts[:-1]:
        current /= part
        if current.is_symlink():
            raise ShadowDecisionError("output_parent")
    parent = current.resolve()
    if not parent.is_relative_to(root) or not parent.is_dir():
        raise ShadowDecisionError("output_parent")
    path = current / candidate.name
    if path.exists() or path.is_symlink():
        raise ShadowDecisionError("output_exists")
    return path


def _publish(path: Path, payload: bytes) -> None:
    descriptor = -1
    temporary: Path | None = None
    linked = False
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary = Path(name)
        try:
            os.fchmod(descriptor, 0o600)
            stream = os.fdopen(descriptor, "wb", closefd=True)
            descriptor = -1
        except OSError as exc:
            raise ShadowDecisionError("output_open") from exc
        with stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
            linked = True
            directory = os.open(
                path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            )
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except FileExistsError as exc:
            raise ShadowDecisionError("output_exists") from exc
        except OSError as exc:
            if linked:
                path.unlink(missing_ok=True)
            raise ShadowDecisionError("output_publish") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate exact Newsroom shadow lane evidence"
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--context", required=True)
    parser.add_argument("--event", required=True)
    parser.add_argument("--core", required=True)
    parser.add_argument("--service")
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)
    root = Path(arguments.repo_root).resolve()
    try:
        try:
            context = _context_from_mapping(_load_json(root, arguments.context))
        except (ArtifactProvenanceError, ShadowDecisionError) as exc:
            print("EVIDENCE_MISMATCH:shadow-decision:context", file=sys.stderr)
            return 2
        try:
            contract = load_contract(root)
            event = validate_workflow_event(_load_json(root, arguments.event))
            core = validate_shadow_lane_record(
                _load_json(root, arguments.core), contract=contract
            )
            service = (
                None
                if arguments.service is None
                else validate_shadow_lane_record(
                    _load_json(root, arguments.service), contract=contract
                )
            )
            decision = aggregate_shadow_decision(
                context=context,
                event=event,
                core=core,
                service=service,
                contract=contract,
            )
        except (
            ShadowDecisionError,
            ShadowLaneError,
            WorkflowEvidenceError,
            ArtifactProvenanceError,
            ContractError,
            EvidenceError,
            OSError,
            UnicodeError,
            json.JSONDecodeError,
        ) as exc:
            code = (
                str(exc)
                if isinstance(exc, ShadowDecisionError)
                and str(exc)
                and _SAFE_ID.fullmatch(str(exc))
                else "invalid-input"
            )
            decision = failure_shadow_decision(context=context, code=code)
        rendered = canonical_json_bytes(decision.as_dict()) + b"\n"
        _publish(_safe_output(root, arguments.output), rendered)
        sys.stdout.write(rendered.decode("utf-8"))
        return 0
    except (
        ShadowDecisionError,
        ArtifactProvenanceError,
        ContractError,
        EvidenceError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
    ) as exc:
        code = str(exc) if isinstance(exc, ShadowDecisionError) and str(exc) else type(exc).__name__
        print(f"EVIDENCE_MISMATCH:shadow-decision:{code}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
