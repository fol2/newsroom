from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import stat

import pytest

import scripts.sdlc.shadow_decision as decision_module
from scripts.sdlc.artifact_envelope import GithubRunContext
from scripts.sdlc.contracts import load_contract
from scripts.sdlc.emit_evidence import sha256_identity
from scripts.sdlc.shadow_decision import (
    ShadowDecisionError,
    aggregate_shadow_decision,
    failure_shadow_decision,
    main as decision_main,
    validate_shadow_decision,
)
from scripts.sdlc.shadow_lane import ShadowLaneError
from scripts.sdlc.workflow_event import WorkflowEvent


REPOSITORY_ID = 1153895518
RUN_ID = 123
RUN_ATTEMPT = 2
HEAD_SHA = "c" * 40
HEAD_TREE = "d" * 40
BASE_SHA = "e" * 40
BASE_TREE = "f" * 40


def _contract():
    return load_contract(Path(__file__).resolve().parents[2])


def _context(*, job_id: str = "decision") -> GithubRunContext:
    return GithubRunContext(
        repository="fol2/newsroom",
        repository_id=REPOSITORY_ID,
        head_repository="fol2/newsroom",
        head_repository_id=REPOSITORY_ID,
        run_id=RUN_ID,
        run_attempt=RUN_ATTEMPT,
        job_id=job_id,
        workflow_ref="fol2/newsroom/.github/workflows/evidence.yml@refs/pull/10/merge",
        workflow_sha="a" * 40,
        event_name="pull_request",
        event_sha="b" * 40,
        evaluated_sha=HEAD_SHA,
        evaluated_tree_sha=HEAD_TREE,
        ref="refs/pull/10/merge",
        runner_environment="github-hosted",
    )


def _event(**changes: object) -> WorkflowEvent:
    values: dict[str, object] = {
        "repository": "fol2/newsroom",
        "repository_id": REPOSITORY_ID,
        "head_repository": "fol2/newsroom",
        "head_repository_id": REPOSITORY_ID,
        "event_name": "pull_request",
        "event_sha": "b" * 40,
        "base_sha": BASE_SHA,
        "base_tree_sha": BASE_TREE,
        "evaluated_sha": HEAD_SHA,
        "evaluated_tree_sha": HEAD_TREE,
        "ref": "refs/pull/10/merge",
    }
    values.update(changes)
    return WorkflowEvent(**values)  # type: ignore[arg-type]


@dataclass(frozen=True)
class _Route:
    risk_tier: str
    service_required: bool
    owner_authority_required: bool
    base_sha: str = BASE_SHA
    base_tree_sha: str = BASE_TREE

    def as_dict(self) -> dict[str, object]:
        return {
            "risk_tier": self.risk_tier,
            "service_required": self.service_required,
            "owner_authority_required": self.owner_authority_required,
            "base_sha": self.base_sha,
            "base_tree_sha": self.base_tree_sha,
        }


@dataclass(frozen=True)
class _Metadata:
    run_id: int
    artifact_id: int


@dataclass(frozen=True)
class _Gate:
    gate_id: str
    phase: str
    result: str = "PASS"
    result_reason: str = ""
    execution_ms: int = 500
    test_count: int = 1
    failure_count: int = 0
    error_count: int = 0
    skip_count: int = 0
    required_skip_count: int = 0
    first_failure_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if not self.result_reason:
            object.__setattr__(
                self,
                "result_reason",
                f"{self.result}:{self.gate_id}:{self.phase}",
            )


@dataclass(frozen=True)
class _Receipt:
    route: _Route
    producer_job_id: str
    metadata: _Metadata
    gate_decisions: tuple[_Gate, ...]
    repository: str = "fol2/newsroom"
    repository_id: int = REPOSITORY_ID
    head_repository: str = "fol2/newsroom"
    head_repository_id: int = REPOSITORY_ID
    run_attempt: int = RUN_ATTEMPT
    consumer_job_id: str = "decision"
    workflow_ref: str = "fol2/newsroom/.github/workflows/evidence.yml@refs/pull/10/merge"
    workflow_sha: str = "a" * 40
    event_name: str = "pull_request"
    event_sha: str = "b" * 40
    evaluated_sha: str = HEAD_SHA
    evaluated_tree_sha: str = HEAD_TREE
    ref: str = "refs/pull/10/merge"
    receipt_identity: str = "sha256:" + "7" * 64


@dataclass(frozen=True)
class _Replay:
    run_id: int
    run_attempt: int
    repository_id: int
    head_repository_id: int
    head_sha: str
    replay_identity: str


@dataclass(frozen=True)
class _Telemetry:
    job_id: int
    job_name: str
    job_conclusion: str = "success"
    queue_ms: int = 100
    bootstrap_ms: int = 200
    finalize_ms: int = 300


@dataclass(frozen=True)
class _Lane:
    lane_id: str
    receipt: _Receipt
    replay: _Replay
    telemetry: _Telemetry
    lane_identity: str
    run_event: str = "pull_request"
    run_created_at: str = "2026-07-22T12:00:00.000Z"

    def as_dict(self) -> dict[str, object]:
        return {"lane_identity": self.lane_identity, "lane_id": self.lane_id}


def _route(risk: str = "R1_LOCAL_CODE") -> _Route:
    contract = _contract()
    return _Route(
        risk_tier=risk,
        service_required=contract.service_required(risk),
        owner_authority_required=contract.owner_authority_required(risk),
    )


def _gate(
    gate_id: str,
    phase: str,
    *,
    result: str = "PASS",
    execution_ms: int = 500,
    required_skip: bool = False,
) -> _Gate:
    if required_skip:
        return _Gate(
            gate_id,
            phase,
            result="FAIL",
            result_reason=f"FAIL:{gate_id}:junit",
            execution_ms=execution_ms,
            skip_count=1,
            required_skip_count=1,
            first_failure_fingerprint="sha256:" + "9" * 64,
        )
    return _Gate(gate_id, phase, result=result, execution_ms=execution_ms)


def _lane(
    lane_id: str,
    route: _Route,
    *,
    gates: tuple[_Gate, ...] | None = None,
    conclusion: str = "success",
    finalize_ms: int = 300,
    artifact_id: int | None = None,
) -> _Lane:
    selected_gates = gates or (
        (
            _gate("source-integrity", "source"),
            _gate("core-deterministic", "tests"),
        )
        if lane_id == "core"
        else (_gate("service-neo4j", "tests"),)
    )
    number = artifact_id if artifact_id is not None else (100 if lane_id == "core" else 101)
    return _Lane(
        lane_id=lane_id,
        receipt=_Receipt(
            route=route,
            producer_job_id=lane_id,
            metadata=_Metadata(RUN_ID, number),
            gate_decisions=selected_gates,
            receipt_identity="sha256:" + ("7" if lane_id == "core" else "8") * 64,
        ),
        replay=_Replay(
            RUN_ID,
            RUN_ATTEMPT,
            REPOSITORY_ID,
            REPOSITORY_ID,
            HEAD_SHA,
            "sha256:" + ("4" if lane_id == "core" else "5") * 64,
        ),
        telemetry=_Telemetry(
            job_id=200 if lane_id == "core" else 201,
            job_name=lane_id,
            job_conclusion=conclusion,
            finalize_ms=finalize_ms,
        ),
        lane_identity="sha256:" + ("1" if lane_id == "core" else "2") * 64,
    )


def _patch_lane_validator(monkeypatch: pytest.MonkeyPatch, *lanes: _Lane) -> None:
    registry = {(lane.lane_id, lane.lane_identity): lane for lane in lanes}

    def validate(value, *, contract=None):
        identity = value.get("lane_identity") if isinstance(value, dict) else None
        try:
            lane_id = value.get("lane_id") if isinstance(value, dict) else None
            return registry[(lane_id, identity)]
        except KeyError as exc:
            raise ShadowLaneError("lane_identity") from exc

    monkeypatch.setattr(decision_module, "validate_shadow_lane_record", validate)


def test_core_only_pass_is_exact_and_replayable(monkeypatch: pytest.MonkeyPatch) -> None:
    route = _route()
    core = _lane("core", route)
    _patch_lane_validator(monkeypatch, core)

    decision = aggregate_shadow_decision(
        context=_context(),
        event=_event(),
        core=core,  # type: ignore[arg-type]
        service=None,
        contract=_contract(),
    )

    assert decision.result == "PASS"
    assert decision.result_reason == "PASS:decision"
    assert decision.first_failure is None
    assert decision.totals.test_count == 2
    assert decision.totals.execution_max_ms == 1000
    assert validate_shadow_decision(decision.as_dict(), contract=_contract()) == decision


def test_service_is_required_exactly_when_route_requires_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = _route("R3_EXTERNAL_SERVICE_SECURITY")
    core = _lane("core", route)
    service = _lane("service", route)
    _patch_lane_validator(monkeypatch, core, service)

    with pytest.raises(ShadowDecisionError, match="service_lane_missing"):
        aggregate_shadow_decision(
            context=_context(),
            event=_event(),
            core=core,  # type: ignore[arg-type]
            service=None,
            contract=_contract(),
        )

    decision = aggregate_shadow_decision(
        context=_context(),
        event=_event(),
        core=core,  # type: ignore[arg-type]
        service=service,  # type: ignore[arg-type]
        contract=_contract(),
    )
    assert decision.result == "PASS"
    assert [lane.lane_id for lane in decision.lanes] == ["core", "service"]

    local_route = _route()
    local_core = _lane("core", local_route)
    local_service = _lane("service", local_route)
    _patch_lane_validator(monkeypatch, local_core, local_service)
    with pytest.raises(ShadowDecisionError, match="service_lane_unexpected"):
        aggregate_shadow_decision(
            context=_context(),
            event=_event(),
            core=local_core,  # type: ignore[arg-type]
            service=local_service,  # type: ignore[arg-type]
            contract=_contract(),
        )


def test_route_event_context_and_identity_conflicts_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = _route("R3_EXTERNAL_SERVICE_SECURITY")
    core = _lane("core", route)
    service = _lane("service", replace(route, base_sha="0" * 40))
    _patch_lane_validator(monkeypatch, core, service)
    with pytest.raises(ShadowDecisionError, match="lane_context|route_mismatch"):
        aggregate_shadow_decision(
            context=_context(),
            event=_event(),
            core=core,  # type: ignore[arg-type]
            service=service,  # type: ignore[arg-type]
            contract=_contract(),
        )

    _patch_lane_validator(monkeypatch, core)
    with pytest.raises(ShadowDecisionError, match="event_context"):
        aggregate_shadow_decision(
            context=_context(),
            event=_event(evaluated_sha="0" * 40),
            core=core,  # type: ignore[arg-type]
            service=None,
            contract=_contract(),
        )

    duplicate_service = replace(
        _lane("service", route),
        lane_identity=core.lane_identity,
        replay=replace(_lane("service", route).replay, replay_identity=core.replay.replay_identity),
        receipt=replace(_lane("service", route).receipt, receipt_identity=core.receipt.receipt_identity),
        telemetry=replace(_lane("service", route).telemetry, job_id=core.telemetry.job_id),
    )
    _patch_lane_validator(monkeypatch, core, duplicate_service)
    with pytest.raises(ShadowDecisionError, match="lane_identity_duplicate"):
        aggregate_shadow_decision(
            context=_context(),
            event=_event(),
            core=core,  # type: ignore[arg-type]
            service=duplicate_service,  # type: ignore[arg-type]
            contract=_contract(),
        )


def test_gate_failure_required_skip_and_budget_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = _route()
    required_skip = _lane(
        "core",
        route,
        gates=(
            _gate("source-integrity", "source"),
            _gate("core-deterministic", "tests", required_skip=True),
        ),
    )
    _patch_lane_validator(monkeypatch, required_skip)
    failed = aggregate_shadow_decision(
        context=_context(),
        event=_event(),
        core=required_skip,  # type: ignore[arg-type]
        service=None,
        contract=_contract(),
    )
    assert failed.result == "FAIL"
    assert failed.first_failure is not None
    assert failed.first_failure.first_failure_fingerprint is not None
    assert failed.totals.required_skip_count == 1

    over_budget = _lane(
        "core",
        route,
        gates=(
            _gate("source-integrity", "source", result="FAIL"),
            _gate("core-deterministic", "tests", execution_ms=56_000),
        ),
    )
    _patch_lane_validator(monkeypatch, over_budget)
    budget = aggregate_shadow_decision(
        context=_context(),
        event=_event(),
        core=over_budget,  # type: ignore[arg-type]
        service=None,
        contract=_contract(),
    )
    assert budget.result == "BUDGET_EXCEEDED"
    assert budget.first_failure is not None
    assert budget.first_failure.phase == "execution"


def test_environment_finalize_and_owner_authority_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = _route()
    environment = _lane("core", route, conclusion="failure", finalize_ms=6000)
    _patch_lane_validator(monkeypatch, environment)
    decision = aggregate_shadow_decision(
        context=_context(),
        event=_event(),
        core=environment,  # type: ignore[arg-type]
        service=None,
        contract=_contract(),
    )
    assert decision.result == "ENVIRONMENT_ERROR"

    release = _route("R4_RELEASE_OPERATIONAL")
    core = _lane("core", release)
    service = _lane("service", release)
    _patch_lane_validator(monkeypatch, core, service)
    owner = aggregate_shadow_decision(
        context=_context(),
        event=_event(),
        core=core,  # type: ignore[arg-type]
        service=service,  # type: ignore[arg-type]
        contract=_contract(),
    )
    assert owner.result == "UNAUTHORISED_EFFECT"
    assert owner.first_failure is not None
    assert owner.first_failure.gate_id == "owner-authority"


def test_strict_record_rejects_tampering(monkeypatch: pytest.MonkeyPatch) -> None:
    route = _route()
    core = _lane("core", route)
    _patch_lane_validator(monkeypatch, core)
    decision = aggregate_shadow_decision(
        context=_context(), event=_event(), core=core, service=None, contract=_contract()  # type: ignore[arg-type]
    )

    for field, value, reason in (
        ("decision_identity", "sha256:" + "0" * 64, "decision_identity"),
        ("result", "FAIL", "result_reason|decision_result"),
    ):
        changed = decision.as_dict()
        changed[field] = value
        with pytest.raises(ShadowDecisionError, match=reason):
            validate_shadow_decision(changed, contract=_contract())

    changed = decision.as_dict()
    changed["totals"]["test_count"] = 999  # type: ignore[index]
    changed["decision_identity"] = sha256_identity(
        {key: item for key, item in changed.items() if key != "decision_identity"}
    )
    with pytest.raises(ShadowDecisionError, match="totals"):
        validate_shadow_decision(changed, contract=_contract())


def test_typed_failure_record_is_content_addressed() -> None:
    decision = failure_shadow_decision(context=_context(), code="missing-core")
    assert decision.result == "EVIDENCE_MISMATCH"
    assert decision.event is None
    assert decision.lanes == ()
    assert decision.first_failure is not None
    assert validate_shadow_decision(decision.as_dict(), contract=_contract()) == decision

    with pytest.raises(ShadowDecisionError, match="decision_job"):
        failure_shadow_decision(context=_context(job_id="core"), code="bad")


def test_cli_always_emits_typed_failure_for_invalid_lane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context = tmp_path / "context.json"
    event = tmp_path / "event.json"
    core = tmp_path / "core.json"
    context.write_text(json.dumps(_context().as_dict()), encoding="utf-8")
    event.write_text(json.dumps(_event().as_dict()), encoding="utf-8")
    core.write_text(json.dumps({"lane_identity": "sha256:" + "0" * 64}), encoding="utf-8")

    def reject(*_args, **_kwargs):
        raise ShadowLaneError("lane_identity")

    monkeypatch.setattr(decision_module, "validate_shadow_lane_record", reject)
    output = tmp_path / "decision.json"
    monkeypatch.setattr(decision_module, "load_contract", lambda _root: _contract())
    assert decision_main(
        (
            "--repo-root",
            str(tmp_path),
            "--context",
            str(context),
            "--event",
            str(event),
            "--core",
            str(core),
            "--output",
            "decision.json",
        )
    ) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["result"] == "EVIDENCE_MISMATCH"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert capsys.readouterr().out

    original = output.read_bytes()
    assert decision_main(
        (
            "--repo-root",
            str(tmp_path),
            "--context",
            str(context),
            "--event",
            str(event),
            "--core",
            str(core),
            "--output",
            "decision.json",
        )
    ) == 2
    assert output.read_bytes() == original



def test_service_lanes_must_share_workflow_creation_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = _route("R3_EXTERNAL_SERVICE_SECURITY")
    core = _lane("core", route)
    service = replace(
        _lane("service", route),
        run_created_at="2026-07-22T12:00:01.000Z",
    )
    _patch_lane_validator(monkeypatch, core, service)

    with pytest.raises(ShadowDecisionError, match="run_created_at_mismatch"):
        aggregate_shadow_decision(
            context=_context(),
            event=_event(),
            core=core,  # type: ignore[arg-type]
            service=service,  # type: ignore[arg-type]
            contract=_contract(),
        )


def test_direct_record_construction_rechecks_shape_and_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = _route()
    core = _lane("core", route)
    _patch_lane_validator(monkeypatch, core)
    decision = aggregate_shadow_decision(
        context=_context(),
        event=_event(),
        core=core,  # type: ignore[arg-type]
        service=None,
        contract=_contract(),
    )

    with pytest.raises(ShadowDecisionError, match="decision_identity"):
        replace(decision, decision_identity="sha256:" + "0" * 64)
    with pytest.raises(ShadowDecisionError, match="failure_record"):
        replace(decision, event=None, lanes=())
    with pytest.raises(ShadowDecisionError, match="lanes"):
        replace(decision, lanes=(object(),))  # type: ignore[arg-type]


def test_cli_contract_failure_after_context_is_typed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = tmp_path / "context.json"
    context.write_text(json.dumps(_context().as_dict()), encoding="utf-8")

    def reject_contract(_root):
        raise decision_module.ContractError("contract")

    monkeypatch.setattr(decision_module, "load_contract", reject_contract)
    output = tmp_path / "decision.json"
    assert decision_main(
        (
            "--repo-root",
            str(tmp_path),
            "--context",
            str(context),
            "--event",
            "missing-event.json",
            "--core",
            "missing-core.json",
            "--output",
            "decision.json",
        )
    ) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["result"] == "EVIDENCE_MISMATCH"
    assert payload["result_reason"] == "EVIDENCE_MISMATCH:decision:invalid-input"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
