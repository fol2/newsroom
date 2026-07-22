from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, Sequence

from .contracts import SdlcContract
from .emit_evidence import (
    EvidenceError,
    _validate_route,
    sha256_identity,
)
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
_LANE_EXECUTION_LIMIT_MS = 55_000
_FINALIZATION_LIMIT_MS = 5_000
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_SAFE_ID = re.compile(r"[A-Za-z0-9_.-]{1,128}")
_RESULT_PRIORITY = {
    "PASS": 0,
    "FAIL": 1,
    "BUDGET_EXCEEDED": 2,
    "ENVIRONMENT_ERROR": 3,
    "CLASSIFIER_ERROR": 4,
    "EVIDENCE_MISMATCH": 5,
    "UNAUTHORISED_EFFECT": 6,
}
_RECORD_KEYS = frozenset(
    {
        "schema_version",
        "policy_version",
        "decision_identity",
        "event_identity",
        "route_digest",
        "repository",
        "repository_id",
        "head_repository",
        "head_repository_id",
        "event_name",
        "event_sha",
        "base_sha",
        "base_tree_sha",
        "head_sha",
        "head_tree_sha",
        "ref",
        "risk_tier",
        "risk_reasons",
        "service_required",
        "owner_authority_required",
        "run_id",
        "run_attempt",
        "workflow_ref",
        "workflow_sha",
        "core_lane_identity",
        "service_lane_identity",
        "core_metrics",
        "service_metrics",
        "findings",
        "result",
        "result_reason",
    }
)
_METRIC_KEYS = frozenset(
    {
        "job_conclusion",
        "queue_ms",
        "bootstrap_ms",
        "execution_ms",
        "finalize_ms",
        "gate_results",
    }
)


class ShadowDecisionError(ValueError):
    """Raised when an aggregate shadow decision cannot be validated."""


@dataclass(frozen=True)
class LaneMetrics:
    job_conclusion: str
    queue_ms: int
    bootstrap_ms: int
    execution_ms: int
    finalize_ms: int
    gate_results: tuple[tuple[str, str, str], ...]

    def __post_init__(self) -> None:
        _identifier(self.job_conclusion, "job_conclusion")
        for value, code in (
            (self.queue_ms, "queue_ms"),
            (self.bootstrap_ms, "bootstrap_ms"),
            (self.execution_ms, "execution_ms"),
            (self.finalize_ms, "finalize_ms"),
        ):
            _nonnegative(value, code)
        if self.gate_results != tuple(sorted(self.gate_results)) or not self.gate_results:
            raise ShadowDecisionError("gate_results")
        if len(set((gate, phase) for gate, phase, _ in self.gate_results)) != len(
            self.gate_results
        ):
            raise ShadowDecisionError("gate_results")
        for gate, phase, result in self.gate_results:
            _identifier(gate, "gate_id")
            _identifier(phase, "gate_phase")
            if result not in _RESULT_PRIORITY:
                raise ShadowDecisionError("gate_result")

    def as_dict(self) -> dict[str, object]:
        return {
            "job_conclusion": self.job_conclusion,
            "queue_ms": self.queue_ms,
            "bootstrap_ms": self.bootstrap_ms,
            "execution_ms": self.execution_ms,
            "finalize_ms": self.finalize_ms,
            "gate_results": [
                {"gate_id": gate, "phase": phase, "result": result}
                for gate, phase, result in self.gate_results
            ],
        }


@dataclass(frozen=True)
class ShadowDecision:
    event_identity: str
    route_digest: str
    repository: str
    repository_id: int
    head_repository: str
    head_repository_id: int
    event_name: str
    event_sha: str
    base_sha: str
    base_tree_sha: str
    head_sha: str
    head_tree_sha: str
    ref: str
    risk_tier: str
    risk_reasons: tuple[str, ...]
    service_required: bool
    owner_authority_required: bool
    run_id: int | None
    run_attempt: int | None
    workflow_ref: str | None
    workflow_sha: str | None
    core_lane_identity: str | None
    service_lane_identity: str | None
    core_metrics: LaneMetrics | None
    service_metrics: LaneMetrics | None
    findings: tuple[str, ...]
    result: str
    result_reason: str
    decision_identity: str

    def __post_init__(self) -> None:
        _validate_decision_fields(self)
        if self.decision_identity != sha256_identity(_identity_inputs(self)):
            raise ShadowDecisionError("decision_identity")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "policy_version": POLICY_VERSION,
            "decision_identity": self.decision_identity,
            "event_identity": self.event_identity,
            "route_digest": self.route_digest,
            "repository": self.repository,
            "repository_id": self.repository_id,
            "head_repository": self.head_repository,
            "head_repository_id": self.head_repository_id,
            "event_name": self.event_name,
            "event_sha": self.event_sha,
            "base_sha": self.base_sha,
            "base_tree_sha": self.base_tree_sha,
            "head_sha": self.head_sha,
            "head_tree_sha": self.head_tree_sha,
            "ref": self.ref,
            "risk_tier": self.risk_tier,
            "risk_reasons": list(self.risk_reasons),
            "service_required": self.service_required,
            "owner_authority_required": self.owner_authority_required,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "workflow_ref": self.workflow_ref,
            "workflow_sha": self.workflow_sha,
            "core_lane_identity": self.core_lane_identity,
            "service_lane_identity": self.service_lane_identity,
            "core_metrics": (
                self.core_metrics.as_dict() if self.core_metrics is not None else None
            ),
            "service_metrics": (
                self.service_metrics.as_dict()
                if self.service_metrics is not None
                else None
            ),
            "findings": list(self.findings),
            "result": self.result,
            "result_reason": self.result_reason,
        }


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ShadowDecisionError(code)
    return value


def _text(value: object, code: str, *, maximum: int = 2048) -> str:
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


def _positive(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ShadowDecisionError(code)
    return value


def _nonnegative(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ShadowDecisionError(code)
    if value > 9_223_372_036_854_775_807:
        raise ShadowDecisionError(code)
    return value


def _boolean(value: object, code: str) -> bool:
    if not isinstance(value, bool):
        raise ShadowDecisionError(code)
    return value


def _sha(value: object, code: str) -> str:
    text = _text(value, code, maximum=71)
    if _SHA256.fullmatch(text) is None:
        raise ShadowDecisionError(code)
    return text


def _git_sha(value: object, code: str) -> str:
    text = _text(value, code, maximum=40)
    if _GIT_SHA.fullmatch(text) is None:
        raise ShadowDecisionError(code)
    return text


def _optional_text(value: object, code: str, *, maximum: int) -> str | None:
    return None if value is None else _text(value, code, maximum=maximum)


def _optional_positive(value: object, code: str) -> int | None:
    return None if value is None else _positive(value, code)


def _optional_sha(value: object, code: str) -> str | None:
    return None if value is None else _sha(value, code)


def _string_tuple(
    value: object,
    code: str,
    *,
    maximum_items: int,
    maximum_length: int,
) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > maximum_items:
        raise ShadowDecisionError(code)
    result = tuple(_text(item, code, maximum=maximum_length) for item in value)
    if result != tuple(sorted(result)) or len(set(result)) != len(result):
        raise ShadowDecisionError(code)
    return result


def _lane_metrics(lane: ShadowLaneRecord) -> LaneMetrics:
    gate_results = tuple(
        sorted(
            (
                decision.gate_id,
                decision.phase,
                decision.result,
            )
            for decision in lane.receipt.gate_decisions
        )
    )
    execution_ms = sum(decision.execution_ms for decision in lane.receipt.gate_decisions)
    return LaneMetrics(
        job_conclusion=lane.telemetry.job_conclusion,
        queue_ms=lane.telemetry.queue_ms,
        bootstrap_ms=lane.telemetry.bootstrap_ms,
        execution_ms=execution_ms,
        finalize_ms=lane.telemetry.finalize_ms,
        gate_results=gate_results,
    )


def _metrics_from_mapping(value: object, code: str) -> LaneMetrics | None:
    if value is None:
        return None
    item = _mapping(value, code)
    if frozenset(item) != _METRIC_KEYS:
        raise ShadowDecisionError(code)
    raw_results = item.get("gate_results")
    if not isinstance(raw_results, list) or len(raw_results) > 32:
        raise ShadowDecisionError("gate_results")
    results: list[tuple[str, str, str]] = []
    for raw in raw_results:
        result = _mapping(raw, "gate_result")
        if set(result) != {"gate_id", "phase", "result"}:
            raise ShadowDecisionError("gate_result")
        results.append(
            (
                _identifier(result.get("gate_id"), "gate_id"),
                _identifier(result.get("phase"), "gate_phase"),
                _identifier(result.get("result"), "gate_result"),
            )
        )
    return LaneMetrics(
        job_conclusion=_identifier(item.get("job_conclusion"), "job_conclusion"),
        queue_ms=_nonnegative(item.get("queue_ms"), "queue_ms"),
        bootstrap_ms=_nonnegative(item.get("bootstrap_ms"), "bootstrap_ms"),
        execution_ms=_nonnegative(item.get("execution_ms"), "execution_ms"),
        finalize_ms=_nonnegative(item.get("finalize_ms"), "finalize_ms"),
        gate_results=tuple(results),
    )


def _route_mismatches(event: WorkflowEvent, route: Mapping[str, object]) -> set[str]:
    mismatches: set[str] = set()
    expected = {
        "base_sha": event.base_sha,
        "base_tree_sha": event.base_tree_sha,
        "head_sha": event.evaluated_sha,
        "head_tree_sha": event.evaluated_tree_sha,
    }
    for field, value in expected.items():
        if route[field] != value:
            mismatches.add(f"route_{field}")
    return mismatches


def _lane_mismatches(
    *,
    event: WorkflowEvent,
    route: Mapping[str, object],
    lane: ShadowLaneRecord,
    expected_lane: str,
) -> set[str]:
    mismatches: set[str] = set()
    receipt = lane.receipt
    if lane.lane_id != expected_lane:
        mismatches.add(f"{expected_lane}_lane_id")
    expected = {
        "repository": event.repository,
        "repository_id": event.repository_id,
        "head_repository": event.head_repository,
        "head_repository_id": event.head_repository_id,
        "event_name": event.event_name,
        "event_sha": event.event_sha,
        "evaluated_sha": event.evaluated_sha,
        "evaluated_tree_sha": event.evaluated_tree_sha,
        "ref": event.ref,
    }
    for field, value in expected.items():
        if getattr(receipt, field) != value:
            mismatches.add(f"{expected_lane}_{field}")
    if receipt.route.route_digest != sha256_identity(route):
        mismatches.add(f"{expected_lane}_route_digest")
    return mismatches


def _cross_lane_mismatches(
    core: ShadowLaneRecord,
    service: ShadowLaneRecord,
) -> set[str]:
    mismatches: set[str] = set()
    core_receipt = core.receipt
    service_receipt = service.receipt
    expected = {
        "run_id": core.replay.run_id,
        "run_attempt": core.replay.run_attempt,
        "repository_id": core.replay.repository_id,
        "head_repository_id": core.replay.head_repository_id,
        "head_sha": core.replay.head_sha,
        "workflow_ref": core_receipt.workflow_ref,
        "workflow_sha": core_receipt.workflow_sha,
        "run_created_at": core.run_created_at,
        "route_digest": core_receipt.route.route_digest,
    }
    actual = {
        "run_id": service.replay.run_id,
        "run_attempt": service.replay.run_attempt,
        "repository_id": service.replay.repository_id,
        "head_repository_id": service.replay.head_repository_id,
        "head_sha": service.replay.head_sha,
        "workflow_ref": service_receipt.workflow_ref,
        "workflow_sha": service_receipt.workflow_sha,
        "run_created_at": service.run_created_at,
        "route_digest": service_receipt.route.route_digest,
    }
    for field, value in expected.items():
        if actual[field] != value:
            mismatches.add(f"service_{field}")
    return mismatches


def _lane_findings(lane_name: str, metrics: LaneMetrics) -> set[str]:
    findings: set[str] = set()
    if metrics.job_conclusion != "success":
        findings.add(f"ENVIRONMENT_ERROR:{lane_name}_job_{metrics.job_conclusion}")
    if metrics.execution_ms > _LANE_EXECUTION_LIMIT_MS:
        findings.add(f"BUDGET_EXCEEDED:{lane_name}_execution")
    if metrics.finalize_ms > _FINALIZATION_LIMIT_MS:
        findings.add(f"BUDGET_EXCEEDED:{lane_name}_finalize")
    for gate, phase, result in metrics.gate_results:
        if result != "PASS":
            findings.add(f"{result}:{lane_name}_{gate}_{phase}")
    return findings


def _decision_result(findings: Sequence[str]) -> tuple[str, str]:
    if not findings:
        return "PASS", "PASS:shadow-decision"
    parsed: list[tuple[int, str, str]] = []
    for finding in findings:
        result, separator, code = finding.partition(":")
        if not separator or result not in _RESULT_PRIORITY or not code:
            raise ShadowDecisionError("finding")
        parsed.append((_RESULT_PRIORITY[result], result, code))
    _, result, code = max(parsed, key=lambda item: (item[0], item[2]))
    return result, f"{result}:{code}"


def _identity_inputs(decision: ShadowDecision) -> dict[str, object]:
    value = decision.as_dict()
    value.pop("decision_identity")
    return value


def _validate_decision_fields(decision: ShadowDecision) -> None:
    _sha(decision.event_identity, "event_identity")
    _sha(decision.route_digest, "route_digest")
    if decision.repository != "fol2/newsroom":
        raise ShadowDecisionError("repository")
    _positive(decision.repository_id, "repository_id")
    _text(decision.head_repository, "head_repository", maximum=255)
    _positive(decision.head_repository_id, "head_repository_id")
    _identifier(decision.event_name, "event_name")
    for value, code in (
        (decision.event_sha, "event_sha"),
        (decision.base_sha, "base_sha"),
        (decision.base_tree_sha, "base_tree_sha"),
        (decision.head_sha, "head_sha"),
        (decision.head_tree_sha, "head_tree_sha"),
    ):
        _git_sha(value, code)
    _text(decision.ref, "ref", maximum=2048)
    _identifier(decision.risk_tier, "risk_tier")
    if decision.risk_reasons != tuple(sorted(decision.risk_reasons)) or not decision.risk_reasons:
        raise ShadowDecisionError("risk_reasons")
    for reason in decision.risk_reasons:
        _text(reason, "risk_reason", maximum=512)
    _boolean(decision.service_required, "service_required")
    _boolean(decision.owner_authority_required, "owner_authority_required")
    optional_run_values = (
        decision.run_id,
        decision.run_attempt,
        decision.workflow_ref,
        decision.workflow_sha,
        decision.core_lane_identity,
        decision.core_metrics,
    )
    if any(value is None for value in optional_run_values) and any(
        value is not None for value in optional_run_values
    ):
        raise ShadowDecisionError("core_identity")
    if decision.run_id is not None:
        _positive(decision.run_id, "run_id")
        _positive(decision.run_attempt, "run_attempt")
        _text(decision.workflow_ref, "workflow_ref", maximum=2048)
        _git_sha(decision.workflow_sha, "workflow_sha")
        _sha(decision.core_lane_identity, "core_lane_identity")
    if (decision.service_lane_identity is None) != (decision.service_metrics is None):
        raise ShadowDecisionError("service_identity")
    if decision.service_lane_identity is not None:
        _sha(decision.service_lane_identity, "service_lane_identity")
    if decision.findings != tuple(sorted(decision.findings)) or len(set(decision.findings)) != len(
        decision.findings
    ):
        raise ShadowDecisionError("findings")
    expected_result, expected_reason = _decision_result(decision.findings)
    if decision.result != expected_result or decision.result_reason != expected_reason:
        raise ShadowDecisionError("decision_result")
    if decision.result not in _RESULT_PRIORITY:
        raise ShadowDecisionError("decision_result")
    if decision.result == "PASS" and (
        decision.core_metrics is None
        or decision.service_required != (decision.service_metrics is not None)
        or decision.owner_authority_required
    ):
        raise ShadowDecisionError("pass_invariant")
    _sha(decision.decision_identity, "decision_identity")


def validate_shadow_decision(value: object) -> ShadowDecision:
    item = _mapping(value, "shadow_decision")
    if frozenset(item) != _RECORD_KEYS:
        raise ShadowDecisionError("shadow_decision_shape")
    if (
        item.get("schema_version") != SCHEMA_VERSION
        or item.get("policy_version") != POLICY_VERSION
    ):
        raise ShadowDecisionError("shadow_decision_schema")
    findings = _string_tuple(
        item.get("findings"),
        "findings",
        maximum_items=128,
        maximum_length=256,
    )
    return ShadowDecision(
        event_identity=_sha(item.get("event_identity"), "event_identity"),
        route_digest=_sha(item.get("route_digest"), "route_digest"),
        repository=_text(item.get("repository"), "repository", maximum=255),
        repository_id=_positive(item.get("repository_id"), "repository_id"),
        head_repository=_text(
            item.get("head_repository"), "head_repository", maximum=255
        ),
        head_repository_id=_positive(
            item.get("head_repository_id"), "head_repository_id"
        ),
        event_name=_identifier(item.get("event_name"), "event_name"),
        event_sha=_git_sha(item.get("event_sha"), "event_sha"),
        base_sha=_git_sha(item.get("base_sha"), "base_sha"),
        base_tree_sha=_git_sha(item.get("base_tree_sha"), "base_tree_sha"),
        head_sha=_git_sha(item.get("head_sha"), "head_sha"),
        head_tree_sha=_git_sha(item.get("head_tree_sha"), "head_tree_sha"),
        ref=_text(item.get("ref"), "ref", maximum=2048),
        risk_tier=_identifier(item.get("risk_tier"), "risk_tier"),
        risk_reasons=_string_tuple(
            item.get("risk_reasons"),
            "risk_reasons",
            maximum_items=4096,
            maximum_length=512,
        ),
        service_required=_boolean(
            item.get("service_required"), "service_required"
        ),
        owner_authority_required=_boolean(
            item.get("owner_authority_required"), "owner_authority_required"
        ),
        run_id=_optional_positive(item.get("run_id"), "run_id"),
        run_attempt=_optional_positive(item.get("run_attempt"), "run_attempt"),
        workflow_ref=_optional_text(
            item.get("workflow_ref"), "workflow_ref", maximum=2048
        ),
        workflow_sha=(
            None
            if item.get("workflow_sha") is None
            else _git_sha(item.get("workflow_sha"), "workflow_sha")
        ),
        core_lane_identity=_optional_sha(
            item.get("core_lane_identity"), "core_lane_identity"
        ),
        service_lane_identity=_optional_sha(
            item.get("service_lane_identity"), "service_lane_identity"
        ),
        core_metrics=_metrics_from_mapping(item.get("core_metrics"), "core_metrics"),
        service_metrics=_metrics_from_mapping(
            item.get("service_metrics"), "service_metrics"
        ),
        findings=findings,
        result=_identifier(item.get("result"), "result"),
        result_reason=_text(item.get("result_reason"), "result_reason", maximum=512),
        decision_identity=_sha(
            item.get("decision_identity"), "decision_identity"
        ),
    )


def build_shadow_decision(
    *,
    contract: SdlcContract,
    workflow_event: object,
    route: object,
    core_lane: object | None,
    service_lane: object | None,
) -> ShadowDecision:
    try:
        event = validate_workflow_event(workflow_event)
        normalized_route = _validate_route(contract, route)
        core = (
            None
            if core_lane is None
            else validate_shadow_lane_record(core_lane, contract=contract)
        )
        service = (
            None
            if service_lane is None
            else validate_shadow_lane_record(service_lane, contract=contract)
        )
    except (WorkflowEvidenceError, EvidenceError, ShadowLaneError) as exc:
        raise ShadowDecisionError("input_evidence") from exc

    findings: set[str] = {
        f"EVIDENCE_MISMATCH:{code}"
        for code in _route_mismatches(event, normalized_route)
    }
    service_required = bool(normalized_route["service_required"])
    owner_required = bool(normalized_route["owner_authority_required"])
    core_metrics: LaneMetrics | None = None
    service_metrics: LaneMetrics | None = None

    if core is None:
        findings.add("EVIDENCE_MISMATCH:core_missing")
    else:
        findings.update(
            f"EVIDENCE_MISMATCH:{code}"
            for code in _lane_mismatches(
                event=event,
                route=normalized_route,
                lane=core,
                expected_lane="core",
            )
        )
        core_metrics = _lane_metrics(core)
        findings.update(_lane_findings("core", core_metrics))

    if service_required:
        if service is None:
            findings.add("EVIDENCE_MISMATCH:service_missing")
    elif service is not None:
        findings.add("EVIDENCE_MISMATCH:service_unexpected")

    if service is not None:
        findings.update(
            f"EVIDENCE_MISMATCH:{code}"
            for code in _lane_mismatches(
                event=event,
                route=normalized_route,
                lane=service,
                expected_lane="service",
            )
        )
        if core is not None:
            findings.update(
                f"EVIDENCE_MISMATCH:{code}"
                for code in _cross_lane_mismatches(core, service)
            )
        service_metrics = _lane_metrics(service)
        findings.update(_lane_findings("service", service_metrics))

    if owner_required:
        findings.add("UNAUTHORISED_EFFECT:owner_authority_required")

    ordered_findings = tuple(sorted(findings))
    result, reason = _decision_result(ordered_findings)
    route_digest = sha256_identity(normalized_route)
    event_identity = str(event.as_dict()["event_identity"])
    run_id = core.replay.run_id if core is not None else None
    run_attempt = core.replay.run_attempt if core is not None else None
    workflow_ref = core.receipt.workflow_ref if core is not None else None
    workflow_sha = core.receipt.workflow_sha if core is not None else None
    core_identity = core.lane_identity if core is not None else None
    service_identity = service.lane_identity if service is not None else None

    values = {
        "schema_version": SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "event_identity": event_identity,
        "route_digest": route_digest,
        "repository": event.repository,
        "repository_id": event.repository_id,
        "head_repository": event.head_repository,
        "head_repository_id": event.head_repository_id,
        "event_name": event.event_name,
        "event_sha": event.event_sha,
        "base_sha": event.base_sha,
        "base_tree_sha": event.base_tree_sha,
        "head_sha": event.evaluated_sha,
        "head_tree_sha": event.evaluated_tree_sha,
        "ref": event.ref,
        "risk_tier": normalized_route["risk_tier"],
        "risk_reasons": list(normalized_route["reasons"]),
        "service_required": service_required,
        "owner_authority_required": owner_required,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "workflow_ref": workflow_ref,
        "workflow_sha": workflow_sha,
        "core_lane_identity": core_identity,
        "service_lane_identity": service_identity,
        "core_metrics": core_metrics.as_dict() if core_metrics is not None else None,
        "service_metrics": (
            service_metrics.as_dict() if service_metrics is not None else None
        ),
        "findings": list(ordered_findings),
        "result": result,
        "result_reason": reason,
    }
    decision = ShadowDecision(
        event_identity=event_identity,
        route_digest=route_digest,
        repository=event.repository,
        repository_id=event.repository_id,
        head_repository=event.head_repository,
        head_repository_id=event.head_repository_id,
        event_name=event.event_name,
        event_sha=event.event_sha,
        base_sha=event.base_sha,
        base_tree_sha=event.base_tree_sha,
        head_sha=event.evaluated_sha,
        head_tree_sha=event.evaluated_tree_sha,
        ref=event.ref,
        risk_tier=str(normalized_route["risk_tier"]),
        risk_reasons=tuple(str(reason_item) for reason_item in normalized_route["reasons"]),
        service_required=service_required,
        owner_authority_required=owner_required,
        run_id=run_id,
        run_attempt=run_attempt,
        workflow_ref=workflow_ref,
        workflow_sha=workflow_sha,
        core_lane_identity=core_identity,
        service_lane_identity=service_identity,
        core_metrics=core_metrics,
        service_metrics=service_metrics,
        findings=ordered_findings,
        result=result,
        result_reason=reason,
        decision_identity=sha256_identity(values),
    )
    return validate_shadow_decision(decision.as_dict())


def reconcile_shadow_decision(
    value: object,
    *,
    contract: SdlcContract,
    workflow_event: object,
    route: object,
    core_lane: object | None,
    service_lane: object | None,
) -> ShadowDecision:
    actual = validate_shadow_decision(value)
    expected = build_shadow_decision(
        contract=contract,
        workflow_event=workflow_event,
        route=route,
        core_lane=core_lane,
        service_lane=service_lane,
    )
    if actual != expected:
        raise ShadowDecisionError("decision_reconciliation")
    return actual
