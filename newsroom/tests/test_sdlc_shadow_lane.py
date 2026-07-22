from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.sdlc.shadow_lane as lane_module
from scripts.sdlc.emit_evidence import sha256_identity
from scripts.sdlc.shadow_lane import (
    POLICY_VERSION,
    SCHEMA_VERSION,
    ShadowLaneError,
    ShadowLaneRecord,
    validate_shadow_lane_record,
    verify_shadow_lane,
)
from scripts.sdlc.transport_replay import TransportReplay, TransportReplayError
from scripts.sdlc.workflow_event import JobTelemetry, WorkflowEvidenceError


RUN_ID = 123
RUN_ATTEMPT = 2
REPOSITORY_ID = 1153895518
HEAD_REPOSITORY_ID = 999
HEAD_SHA = "a" * 40
ARTIFACT_ID = 456
ARTIFACT_NAME = f"newsroom-sdlc-{RUN_ID}-{RUN_ATTEMPT}-core-{HEAD_SHA}"
ARTIFACT_DIGEST = "sha256:" + "1" * 64


@dataclass(frozen=True)
class _Metadata:
    run_id: int = RUN_ID
    artifact_id: int = ARTIFACT_ID
    name: str = ARTIFACT_NAME
    size_bytes: int = 4096
    digest: str = ARTIFACT_DIGEST


@dataclass(frozen=True)
class _Route:
    contract_version: str = "sdlc-v2.2"
    risk_classifier_version: str = "sdlc-risk-v1"
    risk_tier: str = "R1_LOCAL_CODE"
    service_required: bool = False
    owner_authority_required: bool = False


@dataclass(frozen=True)
class _GateDecision:
    gate_id: str


@dataclass(frozen=True)
class _Receipt:
    metadata: _Metadata
    route: _Route = _Route()
    run_attempt: int = RUN_ATTEMPT
    repository_id: int = REPOSITORY_ID
    head_repository_id: int = HEAD_REPOSITORY_ID
    evaluated_sha: str = HEAD_SHA
    producer_job_id: str = "core"
    event_name: str = "pull_request"
    gate_decisions: tuple[_GateDecision, ...] = (
        _GateDecision("source-integrity"),
        _GateDecision("core-deterministic"),
    )
    receipt_identity: str = "sha256:" + "2" * 64

    def as_dict(self) -> dict[str, object]:
        return {"receipt_identity": self.receipt_identity}


def _replay(*, artifact_name: str = ARTIFACT_NAME) -> TransportReplay:
    values: dict[str, object] = {
        "schema_version": "newsroom.sdlc.transport-replay.v1",
        "transport_identity": "sha256:" + "3" * 64,
        "run_id": RUN_ID,
        "run_attempt": RUN_ATTEMPT,
        "repository_id": REPOSITORY_ID,
        "head_repository_id": HEAD_REPOSITORY_ID,
        "head_sha": HEAD_SHA,
        "artifact_id": ARTIFACT_ID,
        "artifact_name": artifact_name,
        "artifact_size_bytes": 4096,
        "artifact_digest": ARTIFACT_DIGEST,
        "run_digest": "sha256:" + "4" * 64,
        "jobs_digest": "sha256:" + "5" * 64,
        "metadata_digest": "sha256:" + "6" * 64,
    }
    values["replay_identity"] = sha256_identity(values)
    return TransportReplay(
        transport_identity=str(values["transport_identity"]),
        run_id=RUN_ID,
        run_attempt=RUN_ATTEMPT,
        repository_id=REPOSITORY_ID,
        head_repository_id=HEAD_REPOSITORY_ID,
        head_sha=HEAD_SHA,
        artifact_id=ARTIFACT_ID,
        artifact_name=artifact_name,
        artifact_size_bytes=4096,
        artifact_digest=ARTIFACT_DIGEST,
        run_digest=str(values["run_digest"]),
        jobs_digest=str(values["jobs_digest"]),
        metadata_digest=str(values["metadata_digest"]),
        replay_identity=str(values["replay_identity"]),
    )


def _telemetry(*, job_name: str = "core") -> JobTelemetry:
    return JobTelemetry(
        run_id=RUN_ID,
        run_attempt=RUN_ATTEMPT,
        job_id=789,
        job_name=job_name,
        job_conclusion="success",
        ready_after_jobs=(),
        queue_ms=1000,
        bootstrap_ms=4000,
        finalize_ms=1000,
        workflow_created_at="2026-07-22T12:00:00.000Z",
        ready_at="2026-07-22T12:00:00.000Z",
        job_started_at="2026-07-22T12:00:01.000Z",
        bootstrap_completed_at="2026-07-22T12:00:05.000Z",
        finalization_started_at="2026-07-22T12:00:40.000Z",
        finalization_completed_at="2026-07-22T12:00:41.000Z",
        job_completed_at="2026-07-22T12:00:42.000Z",
    )


def _identity(
    lane_id: str,
    replay: TransportReplay,
    receipt: _Receipt,
    telemetry: JobTelemetry,
) -> str:
    return sha256_identity(
        {
            "schema_version": SCHEMA_VERSION,
            "policy_version": POLICY_VERSION,
            "lane_id": lane_id,
            "run_event": "pull_request",
            "run_created_at": "2026-07-22T12:00:00.000Z",
            "replay_identity": replay.replay_identity,
            "receipt_identity": receipt.receipt_identity,
            "telemetry_identity": telemetry.as_dict()["telemetry_identity"],
        }
    )


def _patch_receipt_validator(
    monkeypatch: pytest.MonkeyPatch,
    receipt: _Receipt,
) -> None:
    monkeypatch.setattr(
        lane_module,
        "validate_receipt",
        lambda value, contract=None: receipt,
    )


def _record(
    monkeypatch: pytest.MonkeyPatch,
    *,
    lane_id: str = "core",
    receipt: _Receipt | None = None,
    telemetry: JobTelemetry | None = None,
) -> ShadowLaneRecord:
    selected_receipt = receipt or _Receipt(_Metadata())
    _patch_receipt_validator(monkeypatch, selected_receipt)
    replay = _replay(artifact_name=selected_receipt.metadata.name)
    selected_telemetry = telemetry or _telemetry(job_name=lane_id)
    return ShadowLaneRecord(
        lane_id=lane_id,
        run_event="pull_request",
        run_created_at="2026-07-22T12:00:00.000Z",
        replay=replay,
        receipt=selected_receipt,  # type: ignore[arg-type]
        telemetry=selected_telemetry,
        lane_identity=_identity(
            lane_id,
            replay,
            selected_receipt,
            selected_telemetry,
        ),
    )


def test_verify_shadow_lane_composes_replay_telemetry_and_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replay = _replay()
    receipt = _Receipt(_Metadata())
    telemetry = _telemetry()
    transport = SimpleNamespace(
        replay=replay,
        run={"event": "pull_request", "created_at": telemetry.workflow_created_at},
        jobs={"jobs": []},
        metadata={"id": ARTIFACT_ID},
        artifact_root=tmp_path / "artifact",
        archive_path=tmp_path / "artifact.zip",
    )
    calls: dict[str, object] = {}
    monkeypatch.setattr(lane_module, "load_verified_transport", lambda _root: transport)

    def measure(jobs, **kwargs):
        calls["measure"] = (jobs, kwargs)
        return telemetry

    def verify(**kwargs):
        calls["verify"] = kwargs
        return receipt

    monkeypatch.setattr(lane_module, "measure_job_telemetry", measure)
    monkeypatch.setattr(lane_module, "verify_artifact", verify)
    _patch_receipt_validator(monkeypatch, receipt)
    contract = SimpleNamespace(repo_root=tmp_path)
    decision_context = SimpleNamespace(job_id="decision")

    record = verify_shadow_lane(
        repo_root=tmp_path,
        bundle_root=tmp_path / "bundle",
        lane_id="core",
        decision_context=decision_context,  # type: ignore[arg-type]
        contract=contract,  # type: ignore[arg-type]
        now=datetime(2026, 7, 22, 12, 1, tzinfo=timezone.utc),
    )

    assert record.lane_id == "core"
    assert record.replay == replay
    assert record.receipt == receipt
    assert record.telemetry == telemetry
    assert calls["measure"][1]["job_name"] == "core"  # type: ignore[index]
    assert calls["measure"][1]["bootstrap_end_step"] == "Sync locked environment"  # type: ignore[index]
    assert calls["verify"]["expected_job_id"] == "core"  # type: ignore[index]
    assert validate_shadow_lane_record(record.as_dict(), contract=contract) == record


def test_service_lane_uses_exact_service_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _Receipt(
        _Metadata(name=ARTIFACT_NAME.replace("-core-", "-service-")),
        route=_Route(
            risk_tier="R3_EXTERNAL_SERVICE_SECURITY",
            service_required=True,
        ),
        producer_job_id="service",
        gate_decisions=(_GateDecision("service-neo4j"),),
    )
    replay = _replay(artifact_name=receipt.metadata.name)
    telemetry = _telemetry(job_name="service")
    transport = SimpleNamespace(
        replay=replay,
        run={"event": "pull_request", "created_at": telemetry.workflow_created_at},
        jobs={},
        metadata={},
        artifact_root=tmp_path / "artifact",
        archive_path=tmp_path / "artifact.zip",
    )
    calls: dict[str, object] = {}
    monkeypatch.setattr(lane_module, "load_verified_transport", lambda _root: transport)
    monkeypatch.setattr(
        lane_module,
        "measure_job_telemetry",
        lambda jobs, **kwargs: calls.setdefault("measure", kwargs) and telemetry,
    )
    monkeypatch.setattr(
        lane_module,
        "verify_artifact",
        lambda **kwargs: calls.setdefault("verify", kwargs) and receipt,
    )
    _patch_receipt_validator(monkeypatch, receipt)

    record = verify_shadow_lane(
        repo_root=tmp_path,
        bundle_root=tmp_path / "bundle",
        lane_id="service",
        decision_context=SimpleNamespace(job_id="decision"),  # type: ignore[arg-type]
        contract=SimpleNamespace(repo_root=tmp_path),  # type: ignore[arg-type]
    )

    assert record.lane_id == "service"
    assert calls["measure"]["job_name"] == "service"  # type: ignore[index]
    assert calls["measure"]["bootstrap_end_step"] == "Wait for authenticated Neo4j"  # type: ignore[index]
    assert calls["verify"]["expected_job_id"] == "service"  # type: ignore[index]


@pytest.mark.parametrize(
    ("receipt", "telemetry", "reason"),
    [
        (
            _Receipt(_Metadata(artifact_id=999)),
            _telemetry(),
            "replay_receipt_identity",
        ),
        (
            _Receipt(_Metadata()),
            _telemetry(job_name="other"),
            "producer_identity",
        ),
        (
            _Receipt(_Metadata(), event_name="push"),
            _telemetry(),
            "run_event",
        ),
    ],
)
def test_cross_record_identity_mismatch_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    receipt: _Receipt,
    telemetry: JobTelemetry,
    reason: str,
) -> None:
    _patch_receipt_validator(monkeypatch, receipt)
    replay = _replay(artifact_name=receipt.metadata.name)
    with pytest.raises(ShadowLaneError, match=reason):
        ShadowLaneRecord(
            lane_id="core",
            run_event="pull_request",
            run_created_at="2026-07-22T12:00:00.000Z",
            replay=replay,
            receipt=receipt,  # type: ignore[arg-type]
            telemetry=telemetry,
            lane_identity="sha256:" + "0" * 64,
        )



def test_route_and_lane_gate_semantics_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_route = _Receipt(
        _Metadata(),
        route=_Route(
            risk_tier="R1_LOCAL_CODE",
            service_required=True,
        ),
    )
    _patch_receipt_validator(monkeypatch, invalid_route)
    replay = _replay()
    with pytest.raises(ShadowLaneError, match="route_contract"):
        ShadowLaneRecord(
            lane_id="core",
            run_event="pull_request",
            run_created_at="2026-07-22T12:00:00.000Z",
            replay=replay,
            receipt=invalid_route,  # type: ignore[arg-type]
            telemetry=_telemetry(),
            lane_identity="sha256:" + "0" * 64,
        )

    invalid_gates = _Receipt(
        _Metadata(),
        gate_decisions=(_GateDecision("core-deterministic"),),
    )
    _patch_receipt_validator(monkeypatch, invalid_gates)
    with pytest.raises(ShadowLaneError, match="lane_gates"):
        ShadowLaneRecord(
            lane_id="core",
            run_event="pull_request",
            run_created_at="2026-07-22T12:00:00.000Z",
            replay=replay,
            receipt=invalid_gates,  # type: ignore[arg-type]
            telemetry=_telemetry(),
            lane_identity="sha256:" + "0" * 64,
        )


def test_record_rejects_shape_policy_and_identity_tampering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record(monkeypatch).as_dict()

    changed = dict(record)
    changed["unknown"] = True
    with pytest.raises(ShadowLaneError, match="shadow_lane_shape"):
        validate_shadow_lane_record(changed)

    changed = dict(record)
    changed["policy_version"] = "other"
    with pytest.raises(ShadowLaneError, match="shadow_lane_schema"):
        validate_shadow_lane_record(changed)

    changed = dict(record)
    changed["lane_identity"] = "sha256:" + "0" * 64
    with pytest.raises(ShadowLaneError, match="lane_identity"):
        validate_shadow_lane_record(changed)


def test_dependency_failures_use_stable_lane_categories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = SimpleNamespace(repo_root=tmp_path)
    context = SimpleNamespace(job_id="decision")
    monkeypatch.setattr(
        lane_module,
        "load_verified_transport",
        lambda _root: (_ for _ in ()).throw(TransportReplayError("bad")),
    )
    with pytest.raises(ShadowLaneError, match="transport_replay"):
        verify_shadow_lane(
            repo_root=tmp_path,
            bundle_root=tmp_path / "bundle",
            lane_id="core",
            decision_context=context,  # type: ignore[arg-type]
            contract=contract,  # type: ignore[arg-type]
        )

    replay = _replay()
    transport = SimpleNamespace(
        replay=replay,
        run={"event": "pull_request", "created_at": "2026-07-22T12:00:00.000Z"},
        jobs={},
        metadata={},
        artifact_root=tmp_path / "artifact",
        archive_path=tmp_path / "artifact.zip",
    )
    monkeypatch.setattr(lane_module, "load_verified_transport", lambda _root: transport)
    monkeypatch.setattr(
        lane_module,
        "measure_job_telemetry",
        lambda *args, **kwargs: (_ for _ in ()).throw(WorkflowEvidenceError("bad")),
    )
    with pytest.raises(ShadowLaneError, match="job_telemetry"):
        verify_shadow_lane(
            repo_root=tmp_path,
            bundle_root=tmp_path / "bundle",
            lane_id="core",
            decision_context=context,  # type: ignore[arg-type]
            contract=contract,  # type: ignore[arg-type]
        )
