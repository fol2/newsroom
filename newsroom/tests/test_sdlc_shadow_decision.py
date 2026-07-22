from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

import scripts.sdlc.shadow_decision as decision_module
from scripts.sdlc.emit_evidence import sha256_identity
from scripts.sdlc.shadow_decision import (
    POLICY_VERSION,
    SCHEMA_VERSION,
    ShadowDecisionError,
    build_shadow_decision,
    reconcile_shadow_decision,
    validate_shadow_decision,
)


REPOSITORY_ID = 1153895518
HEAD_REPOSITORY_ID = 999
BASE_SHA = "1" * 40
BASE_TREE = "2" * 40
HEAD_SHA = "3" * 40
HEAD_TREE = "4" * 40
EVENT_SHA = "5" * 40
WORKFLOW_SHA = "6" * 40


@dataclass(frozen=True)
class _Event:
    repository: str = "fol2/newsroom"
    repository_id: int = REPOSITORY_ID
    head_repository: str = "contributor/newsroom"
    head_repository_id: int = HEAD_REPOSITORY_ID
    event_name: str = "pull_request"
    event_sha: str = EVENT_SHA
    base_sha: str = BASE_SHA
    base_tree_sha: str = BASE_TREE
    evaluated_sha: str = HEAD_SHA
    evaluated_tree_sha: str = HEAD_TREE
    ref: str = "refs/pull/10/merge"

    def as_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": "newsroom.sdlc.workflow-event.v1",
            "event_identity": "",
            "repository": self.repository,
            "repository_id": self.repository_id,
            "head_repository": self.head_repository,
            "head_repository_id": self.head_repository_id,
            "event_name": self.event_name,
            "event_sha": self.event_sha,
            "base_sha": self.base_sha,
            "base_tree_sha": self.base_tree_sha,
            "evaluated_sha": self.evaluated_sha,
            "evaluated_tree_sha": self.evaluated_tree_sha,
            "ref": self.ref,
        }
        value["event_identity"] = sha256_identity(
            {key: item for key, item in value.items() if key != "event_identity"}
        )
        return value


@dataclass(frozen=True)
class _RouteDecision:
    route_digest: str


@dataclass(frozen=True)
class _GateDecision:
    gate_id: str
    phase: str
    result: str = "PASS"
    execution_ms: int = 1000


@dataclass(frozen=True)
class _Receipt:
    route: _RouteDecision
    gate_decisions: tuple[_GateDecision, ...]
    repository: str = "fol2/newsroom"
    repository_id: int = REPOSITORY_ID
    head_repository: str = "contributor/newsroom"
    head_repository_id: int = HEAD_REPOSITORY_ID
    event_name: str = "pull_request"
    event_sha: str = EVENT_SHA
    evaluated_sha: str = HEAD_SHA
    evaluated_tree_sha: str = HEAD_TREE
    ref: str = "refs/pull/10/merge"
    workflow_ref: str = (
        "fol2/newsroom/.github/workflows/evidence.yml@refs/pull/10/merge"
    )
    workflow_sha: str = WORKFLOW_SHA


@dataclass(frozen=True)
class _Replay:
    run_id: int = 123
    run_attempt: int = 2
    repository_id: int = REPOSITORY_ID
    head_repository_id: int = HEAD_REPOSITORY_ID
    head_sha: str = HEAD_SHA


@dataclass(frozen=True)
class _Telemetry:
    job_conclusion: str = "success"
    queue_ms: int = 1000
    bootstrap_ms: int = 4000
    finalize_ms: int = 1000


@dataclass(frozen=True)
class _Lane:
    lane_id: str
    lane_identity: str
    replay: _Replay
    receipt: _Receipt
    telemetry: _Telemetry


def _route(
    *,
    risk_tier: str = "R1_LOCAL_CODE",
    service_required: bool = False,
    owner_required: bool = False,
) -> dict[str, object]:
    manifest = {
        "core_tests": ["newsroom/tests"],
        "service_tests": ["service.py"] if service_required else [],
        "sentinels": ["sentinel"],
    }
    return {
        "schema_version": "newsroom.sdlc.route.v1",
        "contract_version": "sdlc-v2.2",
        "base_sha": BASE_SHA,
        "head_sha": HEAD_SHA,
        "base_tree_sha": BASE_TREE,
        "head_tree_sha": HEAD_TREE,
        "risk_tier": risk_tier,
        "reasons": [f"path:example:{risk_tier}"],
        "core_required": True,
        "service_required": service_required,
        "clustering_required": False,
        "owner_authority_required": owner_required,
        "core_tests": manifest["core_tests"],
        "service_tests": manifest["service_tests"],
        "sentinels": manifest["sentinels"],
        "selected_test_manifest_digest": sha256_identity(manifest),
    }


def _lane(
    lane_id: str,
    route: dict[str, object],
    *,
    run_id: int = 123,
    workflow_sha: str = WORKFLOW_SHA,
    conclusion: str = "success",
    finalize_ms: int = 1000,
    gate_result: str = "PASS",
    execution_ms: int = 1000,
) -> _Lane:
    if lane_id == "core":
        gates = (
            _GateDecision("source-integrity", "source", execution_ms=execution_ms),
            _GateDecision(
                "core-deterministic",
                "tests",
                result=gate_result,
                execution_ms=execution_ms,
            ),
        )
    else:
        gates = (
            _GateDecision(
                "service-neo4j",
                "tests",
                result=gate_result,
                execution_ms=execution_ms,
            ),
        )
    receipt = _Receipt(
        route=_RouteDecision(sha256_identity(route)),
        gate_decisions=gates,
        workflow_sha=workflow_sha,
    )
    return _Lane(
        lane_id=lane_id,
        lane_identity="sha256:" + ("a" if lane_id == "core" else "b") * 64,
        replay=_Replay(run_id=run_id),
        receipt=receipt,
        telemetry=_Telemetry(
            job_conclusion=conclusion,
            finalize_ms=finalize_ms,
        ),
    )


def _patch_validators(
    monkeypatch: pytest.MonkeyPatch,
    *,
    event: _Event,
    route: dict[str, object],
    core: _Lane | None,
    service: _Lane | None,
) -> None:
    monkeypatch.setattr(decision_module, "validate_workflow_event", lambda value: event)
    monkeypatch.setattr(decision_module, "_validate_route", lambda contract, value: route)

    def lane_validator(value, contract=None):
        if value is core:
            return core
        if value is service:
            return service
        raise AssertionError("unexpected lane input")

    monkeypatch.setattr(decision_module, "validate_shadow_lane_record", lane_validator)


def _build(
    monkeypatch: pytest.MonkeyPatch,
    *,
    event: _Event | None = None,
    route: dict[str, object] | None = None,
    core: _Lane | None = None,
    service: _Lane | None = None,
):
    selected_event = event or _Event()
    selected_route = route or _route()
    selected_core = core if core is not None else _lane("core", selected_route)
    _patch_validators(
        monkeypatch,
        event=selected_event,
        route=selected_route,
        core=selected_core,
        service=service,
    )
    return build_shadow_decision(
        contract=SimpleNamespace(),  # type: ignore[arg-type]
        workflow_event=selected_event,
        route=selected_route,
        core_lane=selected_core,
        service_lane=service,
    )


def test_r1_core_only_decision_passes_and_replays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = _route()
    core = _lane("core", route)
    decision = _build(monkeypatch, route=route, core=core)

    assert decision.result == "PASS"
    assert decision.result_reason == "PASS:shadow-decision"
    assert decision.service_required is False
    assert decision.service_lane_identity is None
    assert decision.core_metrics is not None
    assert decision.core_metrics.execution_ms == 2000
    assert validate_shadow_decision(decision.as_dict()) == decision
    assert (
        reconcile_shadow_decision(
            decision.as_dict(),
            contract=SimpleNamespace(),  # type: ignore[arg-type]
            workflow_event=_Event(),
            route=route,
            core_lane=core,
            service_lane=None,
        )
        == decision
    )


def test_r3_requires_exact_service_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    route = _route(
        risk_tier="R3_EXTERNAL_SERVICE_SECURITY",
        service_required=True,
    )
    core = _lane("core", route)
    service = _lane("service", route)
    decision = _build(
        monkeypatch,
        route=route,
        core=core,
        service=service,
    )

    assert decision.result == "PASS"
    assert decision.service_lane_identity == service.lane_identity
    assert decision.service_metrics is not None


@pytest.mark.parametrize(
    ("route", "core", "service", "finding"),
    [
        (_route(), None, None, "EVIDENCE_MISMATCH:core_missing"),
        (
            _route(
                risk_tier="R3_EXTERNAL_SERVICE_SECURITY",
                service_required=True,
            ),
            "core",
            None,
            "EVIDENCE_MISMATCH:service_missing",
        ),
        (
            _route(),
            "core",
            "service",
            "EVIDENCE_MISMATCH:service_unexpected",
        ),
    ],
)
def test_missing_or_unexpected_lanes_report_typed_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    route: dict[str, object],
    core: str | None,
    service: str | None,
    finding: str,
) -> None:
    selected_core = _lane("core", route) if core else None
    selected_service = _lane("service", route) if service else None
    _patch_validators(
        monkeypatch,
        event=_Event(),
        route=route,
        core=selected_core,
        service=selected_service,
    )
    decision = build_shadow_decision(
        contract=SimpleNamespace(),  # type: ignore[arg-type]
        workflow_event=_Event(),
        route=route,
        core_lane=selected_core,
        service_lane=selected_service,
    )

    assert decision.result == "EVIDENCE_MISMATCH"
    assert finding in decision.findings


def test_event_route_and_cross_lane_identity_mismatches_are_retained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = _route(
        risk_tier="R3_EXTERNAL_SERVICE_SECURITY",
        service_required=True,
    )
    route["base_sha"] = "7" * 40
    core = _lane("core", route)
    service = _lane("service", route, run_id=999, workflow_sha="8" * 40)
    decision = _build(
        monkeypatch,
        route=route,
        core=core,
        service=service,
    )

    assert decision.result == "EVIDENCE_MISMATCH"
    assert "EVIDENCE_MISMATCH:route_base_sha" in decision.findings
    assert "EVIDENCE_MISMATCH:service_run_id" in decision.findings
    assert "EVIDENCE_MISMATCH:service_workflow_sha" in decision.findings


@pytest.mark.parametrize(
    ("core_kwargs", "expected_result", "expected_finding"),
    [
        (
            {"gate_result": "FAIL"},
            "FAIL",
            "FAIL:core_core-deterministic_tests",
        ),
        (
            {"execution_ms": 30_000},
            "BUDGET_EXCEEDED",
            "BUDGET_EXCEEDED:core_execution",
        ),
        (
            {"finalize_ms": 5_001},
            "BUDGET_EXCEEDED",
            "BUDGET_EXCEEDED:core_finalize",
        ),
        (
            {"conclusion": "cancelled"},
            "ENVIRONMENT_ERROR",
            "ENVIRONMENT_ERROR:core_job_cancelled",
        ),
    ],
)
def test_gate_job_and_budget_results_are_deterministic(
    monkeypatch: pytest.MonkeyPatch,
    core_kwargs: dict[str, object],
    expected_result: str,
    expected_finding: str,
) -> None:
    route = _route()
    core = _lane("core", route, **core_kwargs)
    decision = _build(monkeypatch, route=route, core=core)

    assert decision.result == expected_result
    assert expected_finding in decision.findings
    assert decision.result_reason.startswith(expected_result + ":")


def test_owner_required_route_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    route = _route(
        risk_tier="R4_RELEASE_OPERATIONAL",
        service_required=True,
        owner_required=True,
    )
    core = _lane("core", route)
    service = _lane("service", route)
    decision = _build(
        monkeypatch,
        route=route,
        core=core,
        service=service,
    )

    assert decision.result == "UNAUTHORISED_EFFECT"
    assert decision.result_reason == "UNAUTHORISED_EFFECT:owner_authority_required"


def test_validator_rejects_shape_identity_result_and_pass_tampering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decision = _build(monkeypatch).as_dict()

    changed = deepcopy(decision)
    changed["unknown"] = True
    with pytest.raises(ShadowDecisionError, match="shadow_decision_shape"):
        validate_shadow_decision(changed)

    changed = deepcopy(decision)
    changed["decision_identity"] = "sha256:" + "0" * 64
    with pytest.raises(ShadowDecisionError, match="decision_identity"):
        validate_shadow_decision(changed)

    changed = deepcopy(decision)
    changed["result"] = "FAIL"
    changed["result_reason"] = "FAIL:fake"
    changed["decision_identity"] = _decision_identity(changed)
    with pytest.raises(ShadowDecisionError, match="decision_result"):
        validate_shadow_decision(changed)

    changed = deepcopy(decision)
    changed["core_metrics"] = None
    changed["run_id"] = None
    changed["run_attempt"] = None
    changed["workflow_ref"] = None
    changed["workflow_sha"] = None
    changed["core_lane_identity"] = None
    changed["decision_identity"] = _decision_identity(changed)
    with pytest.raises(ShadowDecisionError, match="pass_invariant"):
        validate_shadow_decision(changed)


def test_reconciliation_rejects_different_input_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = _route()
    core = _lane("core", route)
    decision = _build(monkeypatch, route=route, core=core).as_dict()
    changed_route = dict(route)
    changed_route["reasons"] = ["different"]
    monkeypatch.setattr(
        decision_module,
        "_validate_route",
        lambda contract, value: changed_route,
    )

    with pytest.raises(ShadowDecisionError, match="decision_reconciliation"):
        reconcile_shadow_decision(
            decision,
            contract=SimpleNamespace(),  # type: ignore[arg-type]
            workflow_event=_Event(),
            route=changed_route,
            core_lane=core,
            service_lane=None,
        )


def _decision_identity(value: dict[str, object]) -> str:
    return sha256_identity(
        {key: item for key, item in value.items() if key != "decision_identity"}
    )
