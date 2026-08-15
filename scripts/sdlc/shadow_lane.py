from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .artifact_envelope import GithubRunContext
from .artifact_receipt import (
    ArtifactReceipt,
    ArtifactReceiptError,
    validate_receipt,
    verify_artifact,
)
from .contracts import SdlcContract, load_contract
from .emit_evidence import sha256_identity
from .transport_replay import (
    TransportReplay,
    TransportReplayError,
    load_verified_transport,
    validate_transport_replay,
)
from .workflow_event import (
    JobTelemetry,
    WorkflowEvidenceError,
    measure_job_telemetry,
    validate_job_telemetry,
)
from .workflow_event import (
    _timestamp as _workflow_timestamp,
)

SCHEMA_VERSION = "newsroom.sdlc.shadow-lane.v1"
POLICY_VERSION = "sdlc-shadow-lane-v1"
CONTRACT_VERSION = "sdlc-v2.6"
CLASSIFIER_VERSION = "sdlc-risk-v1"
_SERVICE_RISKS = frozenset({"R3_EXTERNAL_SERVICE_SECURITY", "R4_RELEASE_OPERATIONAL"})
_OWNER_RISKS = frozenset({"R4_RELEASE_OPERATIONAL"})
_SAFE_ID = re.compile(r"[A-Za-z0-9_.-]{1,128}")
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[^\x00-\x1f\x7f]{1,48}Z")
_SUCCESSFUL_STEP_CONCLUSIONS = frozenset({"success", "skipped", "neutral"})
_CORE_SHARD_NAMES = tuple(f"core-shard-{index}" for index in range(18))
_RECORD_KEYS = frozenset(
    {
        "schema_version",
        "policy_version",
        "lane_identity",
        "lane_id",
        "run_event",
        "run_created_at",
        "replay",
        "receipt",
        "telemetry",
    }
)


class ShadowLaneError(ValueError):
    """Raised when a transported lane cannot satisfy exact shadow evidence."""


@dataclass(frozen=True)
class LanePolicy:
    lane_id: str
    producer_job_id: str
    consumer_job_id: str
    gate_keys: frozenset[tuple[str, str]]
    bootstrap_end_step: str
    finalization_step: str
    ready_after_jobs: tuple[str, ...] = ()


_POLICIES = {
    "core": LanePolicy(
        lane_id="core",
        producer_job_id="core",
        consumer_job_id="decision",
        gate_keys=frozenset(
            {("source-integrity", "source"), ("core-deterministic", "tests")}
        ),
        bootstrap_end_step="Sync locked environment",
        finalization_step="Finalize evidence",
        ready_after_jobs=("core_shard", "route", "source"),
    ),
    "service": LanePolicy(
        lane_id="service",
        producer_job_id="service",
        consumer_job_id="decision",
        gate_keys=frozenset({("service-neo4j", "tests")}),
        bootstrap_end_step="Wait for authenticated Neo4j",
        finalization_step="Finalize evidence",
        ready_after_jobs=("route",),
    ),
}


@dataclass(frozen=True)
class ShadowLaneRecord:
    lane_id: str
    run_event: str
    run_created_at: str
    replay: TransportReplay
    receipt: ArtifactReceipt
    telemetry: JobTelemetry
    lane_identity: str

    def __post_init__(self) -> None:
        policy = _policy(self.lane_id)
        _event_name(self.run_event)
        _timestamp(self.run_created_at)
        try:
            replay = validate_transport_replay(self.replay.as_dict())
            receipt = validate_receipt(self.receipt.as_dict())
            telemetry = validate_job_telemetry(self.telemetry.as_dict())
        except (
            TransportReplayError,
            ArtifactReceiptError,
            WorkflowEvidenceError,
        ) as exc:
            raise ShadowLaneError("nested_evidence") from exc
        if (
            replay != self.replay
            or receipt != self.receipt
            or telemetry != self.telemetry
        ):
            raise ShadowLaneError("nested_evidence")
        _cross_check(
            policy=policy,
            run_event=self.run_event,
            run_created_at=self.run_created_at,
            replay=replay,
            receipt=receipt,
            telemetry=telemetry,
        )
        _sha(self.lane_identity, "lane_identity")
        if self.lane_identity != sha256_identity(_identity_inputs(self)):
            raise ShadowLaneError("lane_identity")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "policy_version": POLICY_VERSION,
            "lane_identity": self.lane_identity,
            "lane_id": self.lane_id,
            "run_event": self.run_event,
            "run_created_at": self.run_created_at,
            "replay": self.replay.as_dict(),
            "receipt": self.receipt.as_dict(),
            "telemetry": self.telemetry.as_dict(),
        }


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ShadowLaneError(code)
    return value


def _text(value: object, code: str, *, maximum: int = 2048) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ShadowLaneError(code)
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ShadowLaneError(code)
    return value


def _identifier(value: object, code: str) -> str:
    text = _text(value, code, maximum=128)
    if _SAFE_ID.fullmatch(text) is None:
        raise ShadowLaneError(code)
    return text


def _sha(value: object, code: str) -> str:
    text = _text(value, code, maximum=71)
    if _SHA256.fullmatch(text) is None:
        raise ShadowLaneError(code)
    return text


def _timestamp(value: object) -> str:
    text = _text(value, "run_created_at", maximum=64)
    if _TIMESTAMP.fullmatch(text) is None:
        raise ShadowLaneError("run_created_at")
    try:
        datetime.fromisoformat(text)
    except ValueError as exc:
        raise ShadowLaneError("run_created_at") from exc
    return text


def _event_name(value: object) -> str:
    text = _identifier(value, "run_event")
    if text not in {"pull_request", "merge_group", "push", "workflow_dispatch"}:
        raise ShadowLaneError("run_event")
    return text


def _policy(lane_id: object) -> LanePolicy:
    value = _identifier(lane_id, "lane_id")
    try:
        return _POLICIES[value]
    except KeyError as exc:
        raise ShadowLaneError("lane_id") from exc


def _identity_values(
    *,
    lane_id: str,
    run_event: str,
    run_created_at: str,
    replay: TransportReplay,
    receipt: ArtifactReceipt,
    telemetry: JobTelemetry,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "lane_id": lane_id,
        "run_event": run_event,
        "run_created_at": run_created_at,
        "replay_identity": replay.replay_identity,
        "receipt_identity": receipt.receipt_identity,
        "telemetry_identity": telemetry.as_dict()["telemetry_identity"],
    }


def _identity_inputs(record: ShadowLaneRecord) -> dict[str, object]:
    return _identity_values(
        lane_id=record.lane_id,
        run_event=record.run_event,
        run_created_at=record.run_created_at,
        replay=record.replay,
        receipt=record.receipt,
        telemetry=record.telemetry,
    )


def _cross_check(
    *,
    policy: LanePolicy,
    run_event: str,
    run_created_at: str,
    replay: TransportReplay,
    receipt: ArtifactReceipt,
    telemetry: JobTelemetry,
) -> None:
    metadata = receipt.metadata
    if (
        replay.run_id != metadata.run_id
        or replay.run_attempt != receipt.run_attempt
        or replay.repository_id != receipt.repository_id
        or replay.head_repository_id != receipt.head_repository_id
        or replay.head_sha != receipt.evaluated_sha
        or replay.artifact_id != metadata.artifact_id
        or replay.artifact_name != metadata.name
        or replay.artifact_size_bytes != metadata.size_bytes
        or replay.artifact_digest != metadata.digest
    ):
        raise ShadowLaneError("replay_receipt_identity")
    if (
        telemetry.run_id != replay.run_id
        or telemetry.run_attempt != replay.run_attempt
        or telemetry.job_name != policy.producer_job_id
        or telemetry.ready_after_jobs != policy.ready_after_jobs
        or receipt.producer_job_id != policy.producer_job_id
        or receipt.consumer_job_id != policy.consumer_job_id
    ):
        raise ShadowLaneError("producer_identity")
    if telemetry.workflow_created_at != run_created_at:
        raise ShadowLaneError("workflow_created_at")
    if receipt.event_name != run_event:
        raise ShadowLaneError("run_event")
    route = receipt.route
    if (
        route.contract_version != CONTRACT_VERSION
        or route.risk_classifier_version != CLASSIFIER_VERSION
        or route.service_required is not (route.risk_tier in _SERVICE_RISKS)
        or route.owner_authority_required is not (route.risk_tier in _OWNER_RISKS)
    ):
        raise ShadowLaneError("route_contract")
    if policy.lane_id == "service" and not route.service_required:
        raise ShadowLaneError("lane_route")
    gate_keys = frozenset(
        (decision.gate_id, decision.phase) for decision in receipt.gate_decisions
    )
    if gate_keys != policy.gate_keys:
        raise ShadowLaneError("lane_gates")


def validate_shadow_lane_record(
    value: object,
    *,
    contract: SdlcContract | None = None,
) -> ShadowLaneRecord:
    item = _mapping(value, "shadow_lane")
    if frozenset(item) != _RECORD_KEYS:
        raise ShadowLaneError("shadow_lane_shape")
    if (
        item.get("schema_version") != SCHEMA_VERSION
        or item.get("policy_version") != POLICY_VERSION
    ):
        raise ShadowLaneError("shadow_lane_schema")
    try:
        replay = validate_transport_replay(item.get("replay"))
        receipt = validate_receipt(item.get("receipt"), contract=contract)
        telemetry = validate_job_telemetry(item.get("telemetry"))
    except (TransportReplayError, ArtifactReceiptError, WorkflowEvidenceError) as exc:
        raise ShadowLaneError("nested_evidence") from exc
    return ShadowLaneRecord(
        lane_id=_identifier(item.get("lane_id"), "lane_id"),
        run_event=_event_name(item.get("run_event")),
        run_created_at=_timestamp(item.get("run_created_at")),
        replay=replay,
        receipt=receipt,
        telemetry=telemetry,
        lane_identity=_sha(item.get("lane_identity"), "lane_identity"),
    )


def _telemetry_jobs(
    value: object, *, policy: LanePolicy, run_id: int, run_attempt: int
) -> object:
    if policy.lane_id != "core":
        return value
    jobs = value.get("jobs") if isinstance(value, dict) else None
    if not isinstance(jobs, list):
        raise WorkflowEvidenceError("jobs_shape")
    matrix = [
        job
        for job in jobs
        if isinstance(job, dict)
        and isinstance(job.get("name"), str)
        and str(job["name"]).startswith("core-shard-")
    ]
    expected = set(_CORE_SHARD_NAMES)
    if (
        len(matrix) != len(_CORE_SHARD_NAMES)
        or {job["name"] for job in matrix} != expected
        or any(job.get("name") == "core_shard" for job in jobs if isinstance(job, dict))
        or any(
            (job.get("run_id"), job.get("run_attempt"), job.get("status"))
            != (run_id, run_attempt, "completed")
            for job in matrix
        )
    ):
        raise WorkflowEvidenceError("ready_after_job")
    matrix_conclusions = tuple(job.get("conclusion") for job in matrix)
    if any(
        type(conclusion) is not str or conclusion not in {"success", "failure"}
        for conclusion in matrix_conclusions
    ):
        raise WorkflowEvidenceError("ready_after_job")
    completed_at = max(
        (
            _workflow_timestamp(job.get("completed_at"), "ready_after_job_completed_at")
            for job in matrix
        ),
        key=lambda item: item[1],
    )[0]
    dependency = {
        "name": "core_shard",
        "run_id": run_id,
        "run_attempt": run_attempt,
        "status": "completed",
        "conclusion": ("failure" if "failure" in matrix_conclusions else "success"),
        "completed_at": completed_at,
    }
    return {**value, "jobs": [*jobs, dependency]}


def _verify_core_dependency_results(
    jobs_value: object, *, policy: LanePolicy, receipt: ArtifactReceipt
) -> None:
    if policy.lane_id != "core":
        return
    payload = _mapping(jobs_value, "jobs_mapping")
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        raise ShadowLaneError("producer_result")

    def unique(name: str) -> Mapping[str, object]:
        matches = [
            item for item in jobs if isinstance(item, dict) and item.get("name") == name
        ]
        if len(matches) != 1:
            raise ShadowLaneError("producer_result")
        return matches[0]

    decisions = {
        (item.gate_id, item.phase): item.result for item in receipt.gate_decisions
    }
    try:
        source_result = decisions[("source-integrity", "source")]
        core_result = decisions[("core-deterministic", "tests")]
    except KeyError as exc:
        raise ShadowLaneError("producer_result") from exc
    source_conclusion = unique("source").get("conclusion")
    matrix_conclusion = unique("core_shard").get("conclusion")
    if (
        type(source_conclusion) is not str
        or source_conclusion not in {"success", "failure"}
        or type(matrix_conclusion) is not str
        or matrix_conclusion not in {"success", "failure"}
        or (source_conclusion == "success") is not (source_result == "PASS")
        or (matrix_conclusion == "failure" and core_result == "PASS")
    ):
        raise ShadowLaneError("producer_result")


def _normalise_stale_completed_jobs(
    value: object,
    *,
    job_names: frozenset[str],
) -> object:
    jobs = value.get("jobs") if isinstance(value, dict) else None
    if not isinstance(jobs, list):
        return value
    normalised: list[object] = []
    for raw_job in jobs:
        if not isinstance(raw_job, dict) or raw_job.get("name") not in job_names:
            normalised.append(raw_job)
            continue
        if not {"status", "conclusion", "completed_at"}.issubset(raw_job) or (
            raw_job.get("status"),
            raw_job.get("conclusion"),
            raw_job.get("completed_at"),
        ) != ("in_progress", None, None):
            normalised.append(raw_job)
            continue
        steps = raw_job.get("steps")
        if not isinstance(steps, list) or not steps:
            raise WorkflowEvidenceError("stale_job_steps")
        completed_steps: list[tuple[str, datetime]] = []
        seen_names: set[str] = set()
        complete_job_count = 0
        complete_job_completed: datetime | None = None
        for raw_step in steps:
            if not isinstance(raw_step, dict):
                raise WorkflowEvidenceError("stale_job_step")
            name = _text(raw_step.get("name"), "stale_job_step_name", maximum=256)
            if name in seen_names:
                raise WorkflowEvidenceError("stale_job_step_duplicate")
            seen_names.add(name)
            if raw_step.get("status") != "completed":
                raise WorkflowEvidenceError("stale_job_step_incomplete")
            conclusion = raw_step.get("conclusion")
            if conclusion not in _SUCCESSFUL_STEP_CONCLUSIONS:
                raise WorkflowEvidenceError("stale_job_step_conclusion")
            completed_steps.append(
                _workflow_timestamp(
                    raw_step.get("completed_at"),
                    "stale_job_step_completed_at",
                )
            )
            if name == "Complete job":
                complete_job_count += 1
                if conclusion != "success":
                    raise WorkflowEvidenceError("stale_job_complete_conclusion")
                complete_job_completed = completed_steps[-1][1]
        if complete_job_count != 1:
            raise WorkflowEvidenceError("stale_job_complete_step")
        latest_step = max(completed_steps, key=lambda item: item[1])
        if (
            not isinstance(steps[-1], dict)
            or steps[-1].get("name") != "Complete job"
            or complete_job_completed != latest_step[1]
        ):
            raise WorkflowEvidenceError("stale_job_complete_order")
        normalised.append(
            {
                **raw_job,
                "status": "completed",
                "conclusion": "success",
                "completed_at": latest_step[0],
            }
        )
    return {**value, "jobs": normalised}


def verify_shadow_lane(
    *,
    repo_root: str | Path,
    bundle_root: str | Path,
    lane_id: str,
    decision_context: GithubRunContext,
    contract: SdlcContract | None = None,
    now: datetime | None = None,
) -> ShadowLaneRecord:
    root = Path(repo_root).resolve()
    accepted = contract or load_contract(root)
    if accepted.repo_root != root:
        raise ShadowLaneError("contract_root")
    policy = _policy(lane_id)
    try:
        transport = load_verified_transport(bundle_root)
    except TransportReplayError as exc:
        raise ShadowLaneError("transport_replay") from exc
    run = transport.run
    run_event = _event_name(run.get("event"))
    run_created_at = _timestamp(run.get("created_at"))
    try:
        normalised_jobs = _normalise_stale_completed_jobs(
            transport.jobs,
            job_names=frozenset(
                {
                    policy.producer_job_id,
                    *policy.ready_after_jobs,
                    *_CORE_SHARD_NAMES,
                }
            ),
        )
        jobs = _telemetry_jobs(
            normalised_jobs,
            policy=policy,
            run_id=transport.replay.run_id,
            run_attempt=transport.replay.run_attempt,
        )
        telemetry = measure_job_telemetry(
            jobs,
            run_id=transport.replay.run_id,
            run_attempt=transport.replay.run_attempt,
            job_name=policy.producer_job_id,
            workflow_created_at=run_created_at,
            ready_after_job_names=policy.ready_after_jobs,
            bootstrap_end_step=policy.bootstrap_end_step,
            finalization_step=policy.finalization_step,
        )
    except WorkflowEvidenceError as exc:
        raise ShadowLaneError("job_telemetry") from exc
    try:
        receipt = verify_artifact(
            repo_root=root,
            artifact_root=transport.artifact_root,
            archive_path=transport.archive_path,
            metadata_value=transport.metadata,
            decision_context=decision_context,
            expected_job_id=policy.producer_job_id,
            contract=accepted,
            now=now,
        )
    except ArtifactReceiptError as exc:
        raise ShadowLaneError("artifact_receipt") from exc
    _verify_core_dependency_results(jobs, policy=policy, receipt=receipt)
    lane_identity = sha256_identity(
        _identity_values(
            lane_id=policy.lane_id,
            run_event=run_event,
            run_created_at=run_created_at,
            replay=transport.replay,
            receipt=receipt,
            telemetry=telemetry,
        )
    )
    record = ShadowLaneRecord(
        lane_id=policy.lane_id,
        run_event=run_event,
        run_created_at=run_created_at,
        replay=transport.replay,
        receipt=receipt,
        telemetry=telemetry,
        lane_identity=lane_identity,
    )
    return validate_shadow_lane_record(record.as_dict(), contract=accepted)
