from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import BinaryIO, Mapping, Sequence
import zipfile

from .artifact_envelope import (
    ArtifactEnvelope,
    ArtifactProvenanceError,
    GithubRunContext,
    _artifact_root,
    _load_json_artifact,
    _read_artifact_file,
    _safe_machine_file,
    _unique_object,
    _validate_context,
    _validate_json_depth,
    context_from_environment,
    validate_envelope,
)
from .contracts import ContractError, SdlcContract, load_contract
from .emit_evidence import (
    EvidenceError,
    _validate_gate_run,
    _validate_junit,
    _validate_route,
    canonical_json_bytes,
    sha256_identity,
    validate_evidence_record,
)


SCHEMA_VERSION = "newsroom.sdlc.artifact-receipt.v1"
_MAX_METADATA_BYTES = 1024 * 1024
_MAX_ARTIFACT_ARCHIVE_BYTES = 512 * 1024 * 1024
_MAX_FILES = 64
_MAX_ARCHIVE_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
_ALLOWED_ZIP_COMPRESSION = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
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
_RISK_TIERS = frozenset(
    {
        "R0_DOCUMENTATION",
        "R1_LOCAL_CODE",
        "R2_STATEFUL_CONTRACT",
        "R3_EXTERNAL_SERVICE_SECURITY",
        "R4_RELEASE_OPERATIONAL",
    }
)
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_SAFE_ID = re.compile(r"[A-Za-z0-9_.-]{1,128}")
_SAFE_REASON_SUFFIX = re.compile(r"[A-Za-z0-9_=.*-]{1,256}")
_API_PREFIX = "https://api.github.com/repos/fol2/newsroom/actions/artifacts/"
_ALLOWED_EVENTS = frozenset({"pull_request", "merge_group", "workflow_dispatch", "push"})
_METADATA_KEYS = frozenset(
    {
        "artifact_id",
        "name",
        "size_bytes",
        "digest",
        "created_at",
        "updated_at",
        "expires_at",
        "run_id",
        "repository_id",
        "head_repository_id",
        "head_sha",
    }
)
_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "receipt_identity",
        "metadata",
        "envelope_identity",
        "repository",
        "repository_id",
        "head_repository",
        "head_repository_id",
        "producer_job_id",
        "consumer_job_id",
        "run_attempt",
        "workflow_ref",
        "workflow_sha",
        "event_name",
        "event_sha",
        "evaluated_sha",
        "evaluated_tree_sha",
        "ref",
        "producer_runner_environment",
        "consumer_runner_environment",
        "route",
        "entries",
        "raw_reports",
        "gate_decisions",
    }
)
_ROUTE_DECISION_KEYS = frozenset(
    {
        "route_digest",
        "base_sha",
        "base_tree_sha",
        "contract_version",
        "risk_classifier_version",
        "risk_tier",
        "risk_reasons",
        "core_required",
        "service_required",
        "clustering_required",
        "owner_authority_required",
        "selected_test_manifest_digest",
    }
)
_GATE_DECISION_KEYS = frozenset(
    {
        "gate_id",
        "phase",
        "command_spec_digest",
        "evidence_identity",
        "result",
        "result_reason",
        "queue_ms",
        "bootstrap_ms",
        "execution_ms",
        "finalize_ms",
        "test_count",
        "failure_count",
        "error_count",
        "skip_count",
        "required_skip_count",
        "first_failure_fingerprint",
    }
)


class ArtifactReceiptError(ValueError):
    """Raised when a downloaded artifact cannot satisfy final-decision provenance."""


@dataclass(frozen=True)
class ArtifactMetadata:
    artifact_id: int
    name: str
    size_bytes: int
    digest: str
    created_at: str
    updated_at: str
    expires_at: str
    run_id: int
    repository_id: int
    head_repository_id: int
    head_sha: str

    def as_dict(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "name": self.name,
            "size_bytes": self.size_bytes,
            "digest": self.digest,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "run_id": self.run_id,
            "repository_id": self.repository_id,
            "head_repository_id": self.head_repository_id,
            "head_sha": self.head_sha,
        }


@dataclass(frozen=True)
class RawReport:
    summary_path: str
    path: str
    size_bytes: int
    digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "summary_path": self.summary_path,
            "path": self.path,
            "size_bytes": self.size_bytes,
            "digest": self.digest,
        }


@dataclass(frozen=True)
class RouteDecision:
    route_digest: str
    base_sha: str
    base_tree_sha: str
    contract_version: str
    risk_classifier_version: str
    risk_tier: str
    risk_reasons: tuple[str, ...]
    core_required: bool
    service_required: bool
    clustering_required: bool
    owner_authority_required: bool
    selected_test_manifest_digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "route_digest": self.route_digest,
            "base_sha": self.base_sha,
            "base_tree_sha": self.base_tree_sha,
            "contract_version": self.contract_version,
            "risk_classifier_version": self.risk_classifier_version,
            "risk_tier": self.risk_tier,
            "risk_reasons": list(self.risk_reasons),
            "core_required": self.core_required,
            "service_required": self.service_required,
            "clustering_required": self.clustering_required,
            "owner_authority_required": self.owner_authority_required,
            "selected_test_manifest_digest": self.selected_test_manifest_digest,
        }


@dataclass(frozen=True)
class GateDecision:
    gate_id: str
    phase: str
    command_spec_digest: str
    evidence_identity: str
    result: str
    result_reason: str
    queue_ms: int
    bootstrap_ms: int
    execution_ms: int
    finalize_ms: int
    test_count: int
    failure_count: int
    error_count: int
    skip_count: int
    required_skip_count: int
    first_failure_fingerprint: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "gate_id": self.gate_id,
            "phase": self.phase,
            "command_spec_digest": self.command_spec_digest,
            "evidence_identity": self.evidence_identity,
            "result": self.result,
            "result_reason": self.result_reason,
            "queue_ms": self.queue_ms,
            "bootstrap_ms": self.bootstrap_ms,
            "execution_ms": self.execution_ms,
            "finalize_ms": self.finalize_ms,
            "test_count": self.test_count,
            "failure_count": self.failure_count,
            "error_count": self.error_count,
            "skip_count": self.skip_count,
            "required_skip_count": self.required_skip_count,
            "first_failure_fingerprint": self.first_failure_fingerprint,
        }


@dataclass(frozen=True)
class _ArchiveEntry:
    path: str
    size_bytes: int
    digest: str


@dataclass(frozen=True)
class ArtifactReceipt:
    metadata: ArtifactMetadata
    envelope_identity: str
    repository: str
    repository_id: int
    head_repository: str
    head_repository_id: int
    producer_job_id: str
    consumer_job_id: str
    run_attempt: int
    workflow_ref: str
    workflow_sha: str
    event_name: str
    event_sha: str
    evaluated_sha: str
    evaluated_tree_sha: str
    ref: str
    producer_runner_environment: str
    consumer_runner_environment: str
    route: RouteDecision
    entry_digests: tuple[tuple[str, str, str], ...]
    raw_reports: tuple[RawReport, ...]
    gate_decisions: tuple[GateDecision, ...]
    receipt_identity: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "receipt_identity": self.receipt_identity,
            "metadata": self.metadata.as_dict(),
            "envelope_identity": self.envelope_identity,
            "repository": self.repository,
            "repository_id": self.repository_id,
            "head_repository": self.head_repository,
            "head_repository_id": self.head_repository_id,
            "producer_job_id": self.producer_job_id,
            "consumer_job_id": self.consumer_job_id,
            "run_attempt": self.run_attempt,
            "workflow_ref": self.workflow_ref,
            "workflow_sha": self.workflow_sha,
            "event_name": self.event_name,
            "event_sha": self.event_sha,
            "evaluated_sha": self.evaluated_sha,
            "evaluated_tree_sha": self.evaluated_tree_sha,
            "ref": self.ref,
            "producer_runner_environment": self.producer_runner_environment,
            "consumer_runner_environment": self.consumer_runner_environment,
            "route": self.route.as_dict(),
            "entries": [
                {"role": role, "path": path, "digest": digest}
                for role, path, digest in self.entry_digests
            ],
            "raw_reports": [report.as_dict() for report in self.raw_reports],
            "gate_decisions": [
                decision.as_dict() for decision in self.gate_decisions
            ],
        }


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ArtifactReceiptError(code)
    return value


def _text(value: object, code: str, *, maximum: int = 2048) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ArtifactReceiptError(code)
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ArtifactReceiptError(code)
    return value


def _identifier(value: object, code: str) -> str:
    text = _text(value, code, maximum=128)
    if _SAFE_ID.fullmatch(text) is None:
        raise ArtifactReceiptError(code)
    return text


def _positive(value: object, code: str, *, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ArtifactReceiptError(code)
    if maximum is not None and value > maximum:
        raise ArtifactReceiptError(code)
    return value


def _nonnegative(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ArtifactReceiptError(code)
    if value > 9_223_372_036_854_775_807:
        raise ArtifactReceiptError(code)
    return value


def _boolean(value: object, code: str) -> bool:
    if not isinstance(value, bool):
        raise ArtifactReceiptError(code)
    return value


def _sha(value: object, code: str) -> str:
    text = _text(value, code, maximum=71)
    if _SHA256.fullmatch(text) is None:
        raise ArtifactReceiptError(code)
    return text


def _git_sha(value: object, code: str) -> str:
    text = _text(value, code, maximum=40)
    if _GIT_SHA.fullmatch(text) is None:
        raise ArtifactReceiptError(code)
    return text


def _timestamp(value: object, code: str) -> tuple[str, datetime]:
    text = _text(value, code, maximum=64)
    if not text.endswith("Z"):
        raise ArtifactReceiptError(code)
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise ArtifactReceiptError(code) from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ArtifactReceiptError(code)
    return text, parsed


def _relative_path(value: object, code: str) -> str:
    text = _text(value, code, maximum=1024)
    candidate = Path(text)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or ".." in candidate.parts
        or "\\" in text
        or candidate.as_posix() != text
        or text == "envelope.json"
    ):
        raise ArtifactReceiptError(code)
    return text


def load_metadata(path: str | Path) -> Mapping[str, object]:
    payload = _safe_machine_file(path, maximum=_MAX_METADATA_BYTES, code="metadata_file")
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ArtifactReceiptError("metadata_json") from exc
    _validate_json_depth(value)
    return _mapping(value, "metadata_json")


def validate_metadata(
    value: object,
    *,
    envelope: ArtifactEnvelope,
    decision_context: GithubRunContext,
    now: datetime | None = None,
) -> ArtifactMetadata:
    try:
        producer_context = _validate_context(envelope.context)
        consumer_context = _validate_context(decision_context)
    except ArtifactProvenanceError as exc:
        raise ArtifactReceiptError("artifact_context") from exc
    metadata = _mapping(value, "metadata")
    artifact_id = _positive(metadata.get("id"), "artifact_id")
    name = _text(metadata.get("name"), "artifact_name", maximum=255)
    if name != envelope.artifact_name:
        raise ArtifactReceiptError("artifact_name")
    size = _positive(
        metadata.get("size_in_bytes"),
        "artifact_size",
        maximum=_MAX_ARTIFACT_ARCHIVE_BYTES,
    )
    if metadata.get("expired") is not False:
        raise ArtifactReceiptError("artifact_expired")
    digest = _sha(metadata.get("digest"), "artifact_digest")
    expected_url = f"{_API_PREFIX}{artifact_id}"
    if metadata.get("url") != expected_url:
        raise ArtifactReceiptError("artifact_url")
    if metadata.get("archive_download_url") != expected_url + "/zip":
        raise ArtifactReceiptError("artifact_download_url")
    created_text, created = _timestamp(metadata.get("created_at"), "artifact_created_at")
    updated_text, updated = _timestamp(metadata.get("updated_at"), "artifact_updated_at")
    expires_text, expires = _timestamp(metadata.get("expires_at"), "artifact_expires_at")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() != timezone.utc.utcoffset(current):
        raise ArtifactReceiptError("verification_time")
    if not created <= updated <= current < expires:
        raise ArtifactReceiptError("artifact_time")

    workflow_run = _mapping(metadata.get("workflow_run"), "artifact_workflow_run")
    run_id = _positive(workflow_run.get("id"), "artifact_run_id")
    repository_id = _positive(
        workflow_run.get("repository_id"), "artifact_repository_id"
    )
    head_repository_id = _positive(
        workflow_run.get("head_repository_id"), "artifact_head_repository_id"
    )
    head_sha = _git_sha(workflow_run.get("head_sha"), "artifact_head_sha")
    if (
        run_id != consumer_context.run_id
        or run_id != producer_context.run_id
        or repository_id != consumer_context.repository_id
        or repository_id != producer_context.repository_id
        or head_repository_id != consumer_context.head_repository_id
        or head_repository_id != producer_context.head_repository_id
        or head_sha != consumer_context.evaluated_sha
        or head_sha != producer_context.evaluated_sha
    ):
        raise ArtifactReceiptError("artifact_workflow_identity")
    return ArtifactMetadata(
        artifact_id=artifact_id,
        name=name,
        size_bytes=size,
        digest=digest,
        created_at=created_text,
        updated_at=updated_text,
        expires_at=expires_text,
        run_id=run_id,
        repository_id=repository_id,
        head_repository_id=head_repository_id,
        head_sha=head_sha,
    )


def _same_run_context(
    producer: GithubRunContext,
    consumer: GithubRunContext,
    expected_job_id: str,
) -> tuple[GithubRunContext, GithubRunContext]:
    try:
        normalized_producer = _validate_context(producer)
        normalized_consumer = _validate_context(consumer)
    except ArtifactProvenanceError as exc:
        raise ArtifactReceiptError("producer_context") from exc
    expected_job = _identifier(expected_job_id, "producer_job")
    if (
        normalized_producer.job_id != expected_job
        or normalized_producer.job_id == normalized_consumer.job_id
    ):
        raise ArtifactReceiptError("producer_job")
    producer_value = normalized_producer.as_dict()
    consumer_value = normalized_consumer.as_dict()
    for field in ("job_id", "runner_environment"):
        producer_value.pop(field)
        consumer_value.pop(field)
    if producer_value != consumer_value:
        raise ArtifactReceiptError("producer_context")
    return normalized_producer, normalized_consumer


def _read_envelope(root: Path) -> ArtifactEnvelope:
    payload, normalized = _read_artifact_file(root, "envelope.json")
    if normalized != "envelope.json":
        raise ArtifactReceiptError("envelope_path")
    try:
        return validate_envelope(_load_json_artifact(payload))
    except ArtifactProvenanceError as exc:
        raise ArtifactReceiptError("envelope_invalid") from exc


def _secure_file(root: Path, relative: str) -> tuple[bytes, str]:
    try:
        return _read_artifact_file(root, relative)
    except ArtifactProvenanceError as exc:
        raise ArtifactReceiptError("artifact_file") from exc


def _validate_command_run(value: object) -> dict[str, object]:
    command_run = dict(_mapping(value, "command_run"))
    if set(command_run) != {
        "schema_version",
        "command_spec_digest",
        "gate_run",
    } or command_run.get("schema_version") != "newsroom.sdlc.command-run.v1":
        raise ArtifactReceiptError("command_run_shape")
    command_run["command_spec_digest"] = _sha(
        command_run.get("command_spec_digest"), "command_spec_digest"
    )
    gate_value = _mapping(command_run.get("gate_run"), "gate_run")
    gate_id = _identifier(gate_value.get("gate_id"), "gate_id")
    try:
        command_run["gate_run"] = _validate_gate_run(gate_id, gate_value)
    except EvidenceError as exc:
        raise ArtifactReceiptError("command_run_invalid") from exc
    return command_run


def _gate_inputs_digest(
    *,
    route: Mapping[str, object],
    command_run: Mapping[str, object],
) -> str:
    gate_run = _mapping(command_run["gate_run"], "gate_run")
    return sha256_identity(
        {
            "command_spec_digest": command_run["command_spec_digest"],
            "gate_id": gate_run["gate_id"],
            "head_tree_sha": route["head_tree_sha"],
            "phase": gate_run["phase"],
            "route_digest": sha256_identity(route),
            "selected_test_manifest_digest": route["selected_test_manifest_digest"],
        }
    )


def _junit_signature(summary: Mapping[str, object]) -> tuple[object, ...]:
    return (
        summary["test_count"],
        summary["failure_count"],
        summary["error_count"],
        summary["skip_count"],
        summary["required_skip_count"],
        summary["first_failure_fingerprint"],
    )


def _evidence_signature(record: Mapping[str, object]) -> tuple[object, ...]:
    return (
        record["test_count"],
        record["failure_count"],
        record["error_count"],
        record["skip_count"],
        record["required_skip_count"],
        record["first_failure_fingerprint"],
    )


def _expected_selected_tests(gate_id: str, route: Mapping[str, object]) -> list[str]:
    if gate_id == "service-neo4j":
        return list(route["service_tests"])
    if gate_id in {"core-deterministic", "merge-exact"}:
        return list(route["core_tests"])
    return []


def _gate_path(gate_id: str, phase: str, filename: str) -> str:
    return f"gates/{gate_id}/{phase}/{filename}"


def _gate_key_from_path(path: str, filename: str) -> tuple[str, str]:
    parts = Path(path).parts
    if (
        len(parts) != 4
        or parts[0] != "gates"
        or parts[3] != filename
    ):
        raise ArtifactReceiptError("gate_artifact_path")
    return (
        _identifier(parts[1], "gate_artifact_path"),
        _identifier(parts[2], "gate_artifact_path"),
    )


def _report_prefix(gate_id: str, phase: str) -> str:
    return f"gates/{gate_id}/{phase}/reports/"


def _reconcile_evidence_route(
    *,
    contract: SdlcContract,
    route: Mapping[str, object],
    evidence: Mapping[str, object],
) -> None:
    gate_id = str(evidence["gate_id"])
    accepted_gate_ids = {
        str(gate["id"]) for gate in contract.data["gate"].values()
    }
    if gate_id not in accepted_gate_ids:
        raise ArtifactReceiptError("gate_not_accepted")
    expected = {
        "gate_contract_version": contract.contract_version,
        "risk_classifier_version": contract.classifier_version,
        "base_sha": route["base_sha"],
        "head_sha": route["head_sha"],
        "base_tree_sha": route["base_tree_sha"],
        "tree_sha": route["head_tree_sha"],
        "risk_tier": route["risk_tier"],
        "risk_reasons": route["reasons"],
        "selected_test_manifest_digest": route["selected_test_manifest_digest"],
        "selected_tests": _expected_selected_tests(gate_id, route),
        "sentinel_tests": route["sentinels"],
    }
    if any(evidence[field] != value for field, value in expected.items()):
        raise ArtifactReceiptError("evidence_route")


def _verify_archive_payload(
    *,
    path: str,
    payload: bytes,
    archive_entries: Mapping[str, _ArchiveEntry],
) -> None:
    archived = archive_entries.get(path)
    if (
        archived is None
        or archived.size_bytes != len(payload)
        or archived.digest != "sha256:" + hashlib.sha256(payload).hexdigest()
    ):
        raise ArtifactReceiptError("archive_extraction")


def _reconcile_artifacts(
    *,
    contract: SdlcContract,
    root: Path,
    envelope: ArtifactEnvelope,
    archive_entries: Mapping[str, _ArchiveEntry],
) -> tuple[
    tuple[tuple[str, str, str], ...],
    tuple[RawReport, ...],
    RouteDecision,
    tuple[GateDecision, ...],
    set[str],
]:
    allowed_paths = {"envelope.json"}
    entry_digests: list[tuple[str, str, str]] = []
    route: dict[str, object] | None = None
    command_runs: dict[tuple[str, str], dict[str, object]] = {}
    junit_summaries: dict[tuple[str, str], tuple[str, dict[str, object]]] = {}
    evidences: dict[tuple[str, str], dict[str, object]] = {}

    pending_evidences: list[tuple[str, dict[str, object]]] = []
    raw_reports: list[RawReport] = []
    gate_decisions: list[GateDecision] = []
    accepted_gate_ids = {
        str(gate["id"]) for gate in contract.data["gate"].values()
    }
    for entry in envelope.entries:
        payload, normalized = _secure_file(root, entry.path)
        if normalized != entry.path or len(payload) != entry.size_bytes:
            raise ArtifactReceiptError("entry_size")
        _verify_archive_payload(
            path=entry.path,
            payload=payload,
            archive_entries=archive_entries,
        )
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        if digest != entry.digest:
            raise ArtifactReceiptError("entry_digest")
        allowed_paths.add(entry.path)
        entry_digests.append((entry.role, entry.path, digest))
        value = _load_json_artifact(payload)
        try:
            if entry.role == "route":
                if entry.path != "route.json" or route is not None:
                    raise ArtifactReceiptError("route_count")
                route = _validate_route(contract, value)
            elif entry.role == "command_run":
                command = _validate_command_run(value)
                gate_run = _mapping(command["gate_run"], "gate_run")
                key = (str(gate_run["gate_id"]), str(gate_run["phase"]))
                if key[0] not in accepted_gate_ids:
                    raise ArtifactReceiptError("gate_not_accepted")
                if entry.path != _gate_path(*key, "command-run.json") or key in command_runs:
                    raise ArtifactReceiptError("command_artifact_path")
                command_runs[key] = command
            elif entry.role == "junit_summary":
                summary = _validate_junit(value)
                if summary is None:
                    raise ArtifactReceiptError("junit_invalid")
                key = _gate_key_from_path(entry.path, "junit-summary.json")
                if key in junit_summaries:
                    raise ArtifactReceiptError("junit_pairing")
                junit_summaries[key] = (entry.path, summary)
            elif entry.role == "gate_evidence":
                pending_evidences.append((entry.path, validate_evidence_record(value)))
            else:
                raise ArtifactReceiptError("entry_role")
        except EvidenceError as exc:
            raise ArtifactReceiptError("entry_invalid") from exc

    if route is None:
        raise ArtifactReceiptError("route_count")
    if (
        route["head_sha"] != envelope.context.evaluated_sha
        or route["head_tree_sha"] != envelope.context.evaluated_tree_sha
    ):
        raise ArtifactReceiptError("route_identity")
    if not command_runs or not pending_evidences:
        raise ArtifactReceiptError("gate_pairing")

    unmatched_commands = dict(command_runs)
    for evidence_path, evidence in pending_evidences:
        gate_id = str(evidence["gate_id"])
        same_gate = [
            (key, command)
            for key, command in unmatched_commands.items()
            if key[0] == gate_id
        ]
        candidates = [
            (key, command)
            for key, command in same_gate
            if evidence["gate_inputs_digest"]
            == _gate_inputs_digest(route=route, command_run=command)
        ]
        if not candidates and same_gate:
            raise ArtifactReceiptError("gate_inputs_digest")
        if len(candidates) != 1:
            raise ArtifactReceiptError("gate_pairing")
        key, command_run = candidates[0]
        if evidence_path != _gate_path(*key, "gate-evidence.json") or key in evidences:
            raise ArtifactReceiptError("evidence_artifact_path")
        del unmatched_commands[key]
        evidences[key] = evidence
        gate_run = _mapping(command_run["gate_run"], "gate_run")
        _reconcile_evidence_route(contract=contract, route=route, evidence=evidence)
        if evidence["execution_ms"] != gate_run["execution_ms"]:
            raise ArtifactReceiptError("evidence_execution")

        junit_item = junit_summaries.pop(key, None)
        if evidence["test_count"]:
            if junit_item is None:
                raise ArtifactReceiptError("junit_pairing")
            summary_path, summary = junit_item
            if _junit_signature(summary) != _evidence_signature(evidence):
                raise ArtifactReceiptError("junit_pairing")
            expected_result = (
                "FAIL"
                if gate_run["result"] == "PASS" and summary["outcome"] == "FAIL"
                else gate_run["result"]
            )
            expected_reason = (
                f"FAIL:{gate_id}:junit"
                if expected_result == "FAIL"
                and gate_run["result"] == "PASS"
                and summary["outcome"] == "FAIL"
                else gate_run["result_reason"]
            )
            if (
                evidence["result"] != expected_result
                or evidence["result_reason"] != expected_reason
            ):
                raise ArtifactReceiptError("evidence_result")
            prefix = _report_prefix(*key)
            for report in summary["reports"]:
                report_mapping = _mapping(report, "junit_report")
                path = _relative_path(report_mapping.get("path"), "junit_report_path")
                if not path.startswith(prefix) or path in allowed_paths:
                    raise ArtifactReceiptError("raw_report_path")
                payload, normalized = _secure_file(root, path)
                _verify_archive_payload(
                    path=path,
                    payload=payload,
                    archive_entries=archive_entries,
                )
                digest = "sha256:" + hashlib.sha256(payload).hexdigest()
                if normalized != path or digest != report_mapping.get("digest"):
                    raise ArtifactReceiptError("raw_report_digest")
                allowed_paths.add(path)
                raw_reports.append(
                    RawReport(
                        summary_path=summary_path,
                        path=path,
                        size_bytes=len(payload),
                        digest=digest,
                    )
                )
        else:
            if junit_item is not None:
                raise ArtifactReceiptError("junit_unexpected")
            if any(
                evidence[field]
                for field in ("failure_count", "error_count", "skip_count")
            ):
                raise ArtifactReceiptError("zero_test_counts")
            if (
                evidence["result"] != gate_run["result"]
                or evidence["result_reason"] != gate_run["result_reason"]
            ):
                raise ArtifactReceiptError("evidence_result")

        gate_decisions.append(
            GateDecision(
                gate_id=key[0],
                phase=key[1],
                command_spec_digest=str(command_run["command_spec_digest"]),
                evidence_identity=str(evidence["evidence_identity"]),
                result=str(evidence["result"]),
                result_reason=str(evidence["result_reason"]),
                queue_ms=int(evidence["queue_ms"]),
                bootstrap_ms=int(evidence["bootstrap_ms"]),
                execution_ms=int(evidence["execution_ms"]),
                finalize_ms=int(evidence["finalize_ms"]),
                test_count=int(evidence["test_count"]),
                failure_count=int(evidence["failure_count"]),
                error_count=int(evidence["error_count"]),
                skip_count=int(evidence["skip_count"]),
                required_skip_count=int(evidence["required_skip_count"]),
                first_failure_fingerprint=(
                    str(evidence["first_failure_fingerprint"])
                    if evidence["first_failure_fingerprint"] is not None
                    else None
                ),
            )
        )

    if unmatched_commands or junit_summaries or set(evidences) != set(command_runs):
        raise ArtifactReceiptError("gate_pairing")
    route_decision = RouteDecision(
        route_digest=sha256_identity(route),
        base_sha=str(route["base_sha"]),
        base_tree_sha=str(route["base_tree_sha"]),
        contract_version=str(route["contract_version"]),
        risk_classifier_version=contract.classifier_version,
        risk_tier=str(route["risk_tier"]),
        risk_reasons=tuple(str(reason) for reason in route["reasons"]),
        core_required=bool(route["core_required"]),
        service_required=bool(route["service_required"]),
        clustering_required=bool(route["clustering_required"]),
        owner_authority_required=bool(route["owner_authority_required"]),
        selected_test_manifest_digest=str(route["selected_test_manifest_digest"]),
    )
    return (
        tuple(sorted(entry_digests)),
        tuple(sorted(raw_reports, key=lambda item: (item.summary_path, item.path))),
        route_decision,
        tuple(sorted(gate_decisions, key=lambda item: (item.gate_id, item.phase))),
        allowed_paths,
    )


def _inventory(root: Path) -> set[str]:
    files: set[str] = set()
    visited = 0
    for path in root.rglob("*"):
        visited += 1
        if visited > _MAX_FILES * 2:
            raise ArtifactReceiptError("artifact_file_count")
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ArtifactReceiptError("artifact_symlink")
        if path.is_dir():
            continue
        try:
            metadata = os.lstat(path)
        except OSError as exc:
            raise ArtifactReceiptError("artifact_inventory") from exc
        if not stat.S_ISREG(metadata.st_mode):
            raise ArtifactReceiptError("artifact_non_regular")
        files.add(relative)
        if len(files) > _MAX_FILES:
            raise ArtifactReceiptError("artifact_file_count")
    return files


def _archive_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ArtifactReceiptError("archive_path")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ArtifactReceiptError("archive_symlink")
    return path


def _zip_member_path(value: str) -> str:
    candidate = Path(value)
    if (
        not value
        or len(value) > 1024
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or not candidate.parts
        or value in {".", ".."}
        or candidate.is_absolute()
        or ".." in candidate.parts
        or "\\" in value
        or candidate.as_posix() != value.rstrip("/")
        or value == "envelope.json/"
    ):
        raise ArtifactReceiptError("archive_member")
    return value.rstrip("/")


def _hash_stream(stream: BinaryIO, *, maximum: int, code: str) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    while payload := stream.read(1024 * 1024):
        total += len(payload)
        if total > maximum:
            raise ArtifactReceiptError(code)
        digest.update(payload)
    return total, "sha256:" + digest.hexdigest()


def _verify_archive(
    archive_path: str | Path,
    *,
    metadata: ArtifactMetadata,
    extracted_root: Path,
) -> tuple[_ArchiveEntry, ...]:
    path = _archive_path(archive_path)
    try:
        initial = os.lstat(path)
    except OSError as exc:
        raise ArtifactReceiptError("archive_file") from exc
    if (
        not stat.S_ISREG(initial.st_mode)
        or initial.st_size != metadata.size_bytes
        or initial.st_size > _MAX_ARTIFACT_ARCHIVE_BYTES
    ):
        raise ArtifactReceiptError("archive_size")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ArtifactReceiptError("archive_file") from exc
    entries: list[_ArchiveEntry] = []
    try:
        current = os.fstat(descriptor)
        if (
            not stat.S_ISREG(current.st_mode)
            or current.st_size != metadata.size_bytes
            or current.st_size > _MAX_ARTIFACT_ARCHIVE_BYTES
        ):
            raise ArtifactReceiptError("archive_size")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            size, digest = _hash_stream(
                stream,
                maximum=_MAX_ARTIFACT_ARCHIVE_BYTES,
                code="archive_size",
            )
            if size != metadata.size_bytes:
                raise ArtifactReceiptError("archive_size")
            if digest != metadata.digest:
                raise ArtifactReceiptError("archive_digest")
            stream.seek(0)
            try:
                archive = zipfile.ZipFile(stream)
            except (OSError, zipfile.BadZipFile) as exc:
                raise ArtifactReceiptError("archive_zip") from exc
            with archive:
                seen: set[str] = set()
                total_uncompressed = 0
                for info in archive.infolist():
                    normalized = _zip_member_path(info.filename)
                    if normalized in seen:
                        raise ArtifactReceiptError("archive_member_duplicate")
                    seen.add(normalized)
                    if len(seen) > _MAX_FILES * 2:
                        raise ArtifactReceiptError("archive_file_count")
                    mode = info.external_attr >> 16
                    if info.is_dir():
                        continue
                    if (
                        info.flag_bits & 0x1
                        or info.compress_type not in _ALLOWED_ZIP_COMPRESSION
                        or (mode and not stat.S_ISREG(mode))
                        or not 0 < info.file_size <= 32 * 1024 * 1024
                    ):
                        raise ArtifactReceiptError("archive_member")
                    total_uncompressed += info.file_size
                    if total_uncompressed > _MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                        raise ArtifactReceiptError("archive_uncompressed_size")
                    try:
                        with archive.open(info, "r") as member:
                            member_size, member_digest = _hash_stream(
                                member,
                                maximum=32 * 1024 * 1024,
                                code="archive_member_size",
                            )
                    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                        raise ArtifactReceiptError("archive_member") from exc
                    if member_size != info.file_size:
                        raise ArtifactReceiptError("archive_member_size")
                    entries.append(
                        _ArchiveEntry(normalized, member_size, member_digest)
                    )
    finally:
        os.close(descriptor)

    archive_entries = tuple(sorted(entries, key=lambda item: item.path))
    if len({item.path for item in archive_entries}) != len(archive_entries):
        raise ArtifactReceiptError("archive_member_duplicate")
    extracted_files = _inventory(extracted_root)
    if {item.path for item in archive_entries} != extracted_files:
        raise ArtifactReceiptError("archive_inventory")
    for entry in archive_entries:
        payload, normalized = _secure_file(extracted_root, entry.path)
        if (
            normalized != entry.path
            or len(payload) != entry.size_bytes
            or "sha256:" + hashlib.sha256(payload).hexdigest() != entry.digest
        ):
            raise ArtifactReceiptError("archive_extraction")
    return archive_entries


def verify_artifact(
    *,
    repo_root: str | Path,
    artifact_root: str | Path,
    archive_path: str | Path,
    metadata_value: object,
    decision_context: GithubRunContext,
    expected_job_id: str,
    contract: SdlcContract | None = None,
    now: datetime | None = None,
) -> ArtifactReceipt:
    repository_root = Path(repo_root).resolve()
    accepted = contract or load_contract(repository_root)
    if accepted.repo_root != repository_root:
        raise ArtifactReceiptError("contract_root")
    try:
        normalized_decision = _validate_context(decision_context)
        root = _artifact_root(repository_root, artifact_root)
        envelope = _read_envelope(root)
    except ArtifactProvenanceError as exc:
        raise ArtifactReceiptError("artifact_context") from exc
    normalized_producer, normalized_decision = _same_run_context(
        envelope.context, normalized_decision, expected_job_id
    )
    metadata = validate_metadata(
        metadata_value,
        envelope=envelope,
        decision_context=normalized_decision,
        now=now,
    )
    archive_entries = {
        entry.path: entry
        for entry in _verify_archive(
            archive_path,
            metadata=metadata,
            extracted_root=root,
        )
    }
    envelope_payload, envelope_path = _secure_file(root, "envelope.json")
    if envelope_path != "envelope.json":
        raise ArtifactReceiptError("envelope_path")
    _verify_archive_payload(
        path="envelope.json",
        payload=envelope_payload,
        archive_entries=archive_entries,
    )
    try:
        final_envelope = validate_envelope(_load_json_artifact(envelope_payload))
    except ArtifactProvenanceError as exc:
        raise ArtifactReceiptError("envelope_invalid") from exc
    if final_envelope != envelope:
        raise ArtifactReceiptError("envelope_changed")
    entries, raw_reports, route_decision, gate_decisions, allowed = _reconcile_artifacts(
        contract=accepted,
        root=root,
        envelope=final_envelope,
        archive_entries=archive_entries,
    )
    if _inventory(root) != allowed:
        raise ArtifactReceiptError("artifact_extra_files")
    identity_inputs = {
        "schema_version": SCHEMA_VERSION,
        "metadata": metadata.as_dict(),
        "envelope_identity": envelope.envelope_identity,
        "repository": normalized_producer.repository,
        "repository_id": normalized_producer.repository_id,
        "head_repository": normalized_producer.head_repository,
        "head_repository_id": normalized_producer.head_repository_id,
        "producer_job_id": normalized_producer.job_id,
        "consumer_job_id": normalized_decision.job_id,
        "run_attempt": normalized_producer.run_attempt,
        "workflow_ref": normalized_producer.workflow_ref,
        "workflow_sha": normalized_producer.workflow_sha,
        "event_name": normalized_producer.event_name,
        "event_sha": normalized_producer.event_sha,
        "evaluated_sha": normalized_producer.evaluated_sha,
        "evaluated_tree_sha": normalized_producer.evaluated_tree_sha,
        "ref": normalized_producer.ref,
        "producer_runner_environment": normalized_producer.runner_environment,
        "consumer_runner_environment": normalized_decision.runner_environment,
        "route": route_decision.as_dict(),
        "entries": [
            {"role": role, "path": path, "digest": digest}
            for role, path, digest in entries
        ],
        "raw_reports": [report.as_dict() for report in raw_reports],
        "gate_decisions": [decision.as_dict() for decision in gate_decisions],
    }
    receipt_identity = sha256_identity(identity_inputs)
    return ArtifactReceipt(
        metadata=metadata,
        envelope_identity=envelope.envelope_identity,
        repository=normalized_producer.repository,
        repository_id=normalized_producer.repository_id,
        head_repository=normalized_producer.head_repository,
        head_repository_id=normalized_producer.head_repository_id,
        producer_job_id=normalized_producer.job_id,
        consumer_job_id=normalized_decision.job_id,
        run_attempt=normalized_producer.run_attempt,
        workflow_ref=normalized_producer.workflow_ref,
        workflow_sha=normalized_producer.workflow_sha,
        event_name=normalized_producer.event_name,
        event_sha=normalized_producer.event_sha,
        evaluated_sha=normalized_producer.evaluated_sha,
        evaluated_tree_sha=normalized_producer.evaluated_tree_sha,
        ref=normalized_producer.ref,
        producer_runner_environment=normalized_producer.runner_environment,
        consumer_runner_environment=normalized_decision.runner_environment,
        route=route_decision,
        entry_digests=entries,
        raw_reports=raw_reports,
        gate_decisions=gate_decisions,
        receipt_identity=receipt_identity,
    )


def _normalized_metadata(value: object) -> ArtifactMetadata:
    metadata_value = _mapping(value, "receipt_metadata")
    if frozenset(metadata_value) != _METADATA_KEYS:
        raise ArtifactReceiptError("receipt_metadata")
    created_text, created = _timestamp(metadata_value.get("created_at"), "created_at")
    updated_text, updated = _timestamp(metadata_value.get("updated_at"), "updated_at")
    expires_text, expires = _timestamp(metadata_value.get("expires_at"), "expires_at")
    if not created <= updated < expires:
        raise ArtifactReceiptError("receipt_metadata_time")
    return ArtifactMetadata(
        artifact_id=_positive(metadata_value.get("artifact_id"), "artifact_id"),
        name=_text(metadata_value.get("name"), "artifact_name", maximum=255),
        size_bytes=_positive(
            metadata_value.get("size_bytes"),
            "artifact_size",
            maximum=_MAX_ARTIFACT_ARCHIVE_BYTES,
        ),
        digest=_sha(metadata_value.get("digest"), "artifact_digest"),
        created_at=created_text,
        updated_at=updated_text,
        expires_at=expires_text,
        run_id=_positive(metadata_value.get("run_id"), "run_id"),
        repository_id=_positive(metadata_value.get("repository_id"), "repository_id"),
        head_repository_id=_positive(
            metadata_value.get("head_repository_id"), "head_repository_id"
        ),
        head_sha=_git_sha(metadata_value.get("head_sha"), "head_sha"),
    )


def _validate_decision_reason(
    *,
    result: str,
    gate_id: str,
    phase: str,
    reason: str,
    has_test_failure: bool,
) -> None:
    base = f"{result}:{gate_id}:{phase}"
    if result in {"PASS", "BUDGET_EXCEEDED"}:
        if reason != base:
            raise ArtifactReceiptError("decision_result_reason")
        return
    if result == "FAIL":
        if reason == f"FAIL:{gate_id}:junit":
            if not has_test_failure:
                raise ArtifactReceiptError("decision_result_reason")
            return
        prefix = base + ":exit="
        if not reason.startswith(prefix):
            raise ArtifactReceiptError("decision_result_reason")
        raw_code = reason[len(prefix) :]
        try:
            exit_code = int(raw_code)
        except ValueError as exc:
            raise ArtifactReceiptError("decision_result_reason") from exc
        if str(exit_code) != raw_code or exit_code == 0:
            raise ArtifactReceiptError("decision_result_reason")
        return
    if reason == base:
        return
    prefix = base + ":"
    if not reason.startswith(prefix) or _SAFE_REASON_SUFFIX.fullmatch(
        reason[len(prefix) :]
    ) is None:
        raise ArtifactReceiptError("decision_result_reason")


def validate_receipt(
    value: object,
    *,
    contract: SdlcContract | None = None,
) -> ArtifactReceipt:
    mapping = _mapping(value, "receipt")
    if frozenset(mapping) != _RECEIPT_KEYS:
        raise ArtifactReceiptError("receipt_shape")
    if mapping.get("schema_version") != SCHEMA_VERSION:
        raise ArtifactReceiptError("receipt_schema")
    metadata = _normalized_metadata(mapping.get("metadata"))
    repository = _text(mapping.get("repository"), "repository", maximum=255)
    if repository != "fol2/newsroom":
        raise ArtifactReceiptError("repository")
    repository_id = _positive(mapping.get("repository_id"), "repository_id")
    head_repository = _text(
        mapping.get("head_repository"), "head_repository", maximum=255
    )
    head_repository_id = _positive(
        mapping.get("head_repository_id"), "head_repository_id"
    )
    producer_job = _identifier(mapping.get("producer_job_id"), "producer_job_id")
    consumer_job = _identifier(mapping.get("consumer_job_id"), "consumer_job_id")
    if producer_job == consumer_job:
        raise ArtifactReceiptError("receipt_jobs")
    run_attempt = _positive(mapping.get("run_attempt"), "run_attempt")
    workflow_ref = _text(mapping.get("workflow_ref"), "workflow_ref")
    if not workflow_ref.startswith(f"{repository}/.github/workflows/"):
        raise ArtifactReceiptError("workflow_ref")
    workflow_sha = _git_sha(mapping.get("workflow_sha"), "workflow_sha")
    event_name = _text(mapping.get("event_name"), "event_name", maximum=64)
    if event_name not in _ALLOWED_EVENTS:
        raise ArtifactReceiptError("event_name")
    event_sha = _git_sha(mapping.get("event_sha"), "event_sha")
    evaluated_sha = _git_sha(mapping.get("evaluated_sha"), "evaluated_sha")
    evaluated_tree_sha = _git_sha(
        mapping.get("evaluated_tree_sha"), "evaluated_tree_sha"
    )
    ref = _text(mapping.get("ref"), "ref")
    producer_runner_environment = _text(
        mapping.get("producer_runner_environment"),
        "producer_runner_environment",
        maximum=64,
    )
    consumer_runner_environment = _text(
        mapping.get("consumer_runner_environment"),
        "consumer_runner_environment",
        maximum=64,
    )
    if (
        producer_runner_environment not in {"github-hosted", "self-hosted"}
        or consumer_runner_environment not in {"github-hosted", "self-hosted"}
    ):
        raise ArtifactReceiptError("runner_environment")
    envelope_identity = _sha(mapping.get("envelope_identity"), "envelope_identity")
    if (
        metadata.repository_id != repository_id
        or metadata.head_repository_id != head_repository_id
        or metadata.head_sha != evaluated_sha
        or metadata.name
        != f"newsroom-sdlc-{metadata.run_id}-{run_attempt}-{producer_job}-{evaluated_sha}"
    ):
        raise ArtifactReceiptError("receipt_metadata_identity")

    route_value = _mapping(mapping.get("route"), "receipt_route")
    if frozenset(route_value) != _ROUTE_DECISION_KEYS:
        raise ArtifactReceiptError("receipt_route")
    risk_reasons_value = route_value.get("risk_reasons")
    if (
        not isinstance(risk_reasons_value, list)
        or not risk_reasons_value
        or len(risk_reasons_value) > 4096
    ):
        raise ArtifactReceiptError("route_risk_reasons")
    risk_reasons = tuple(
        _text(reason, "route_risk_reason", maximum=512)
        for reason in risk_reasons_value
    )
    if len(set(risk_reasons)) != len(risk_reasons) or list(risk_reasons) != sorted(
        risk_reasons
    ):
        raise ArtifactReceiptError("route_risk_reasons")
    risk_tier = _identifier(route_value.get("risk_tier"), "route_risk_tier")
    if risk_tier not in _RISK_TIERS:
        raise ArtifactReceiptError("route_risk_tier")
    route_decision = RouteDecision(
        route_digest=_sha(route_value.get("route_digest"), "route_digest"),
        base_sha=_git_sha(route_value.get("base_sha"), "route_base_sha"),
        base_tree_sha=_git_sha(
            route_value.get("base_tree_sha"), "route_base_tree_sha"
        ),
        contract_version=_text(
            route_value.get("contract_version"), "route_contract_version", maximum=128
        ),
        risk_classifier_version=_text(
            route_value.get("risk_classifier_version"),
            "route_classifier_version",
            maximum=128,
        ),
        risk_tier=risk_tier,
        risk_reasons=risk_reasons,
        core_required=_boolean(route_value.get("core_required"), "route_core_required"),
        service_required=_boolean(
            route_value.get("service_required"), "route_service_required"
        ),
        clustering_required=_boolean(
            route_value.get("clustering_required"), "route_clustering_required"
        ),
        owner_authority_required=_boolean(
            route_value.get("owner_authority_required"), "route_owner_required"
        ),
        selected_test_manifest_digest=_sha(
            route_value.get("selected_test_manifest_digest"),
            "route_selected_manifest",
        ),
    )
    if not route_decision.core_required:
        raise ArtifactReceiptError("route_core_required")
    if contract is not None:
        if (
            route_decision.contract_version != contract.contract_version
            or route_decision.risk_classifier_version != contract.classifier_version
            or route_decision.risk_tier not in contract.risk_rank
            or route_decision.service_required
            is not contract.service_required(route_decision.risk_tier)
            or route_decision.owner_authority_required
            is not contract.owner_authority_required(route_decision.risk_tier)
        ):
            raise ArtifactReceiptError("route_contract")

    raw_entries = mapping.get("entries")
    if not isinstance(raw_entries, list) or not 0 < len(raw_entries) <= _MAX_FILES:
        raise ArtifactReceiptError("receipt_entries")
    entries: list[tuple[str, str, str]] = []
    command_keys: set[tuple[str, str]] = set()
    evidence_keys: set[tuple[str, str]] = set()
    junit_keys: set[tuple[str, str]] = set()
    route_count = 0
    for item_value in raw_entries:
        item = _mapping(item_value, "receipt_entry")
        if set(item) != {"role", "path", "digest"}:
            raise ArtifactReceiptError("receipt_entry")
        role = _identifier(item.get("role"), "entry_role")
        path = _relative_path(item.get("path"), "entry_path")
        digest = _sha(item.get("digest"), "entry_digest")
        if role == "route":
            if path != "route.json":
                raise ArtifactReceiptError("receipt_entries")
            route_count += 1
        elif role == "command_run":
            command_keys.add(_gate_key_from_path(path, "command-run.json"))
        elif role == "gate_evidence":
            evidence_keys.add(_gate_key_from_path(path, "gate-evidence.json"))
        elif role == "junit_summary":
            junit_keys.add(_gate_key_from_path(path, "junit-summary.json"))
        else:
            raise ArtifactReceiptError("receipt_entries")
        entries.append((role, path, digest))
    if (
        entries != sorted(entries)
        or len({path for _, path, _ in entries}) != len(entries)
        or route_count != 1
        or not command_keys
        or command_keys != evidence_keys
        or not junit_keys.issubset(command_keys)
    ):
        raise ArtifactReceiptError("receipt_entries")

    raw_values = mapping.get("raw_reports")
    if not isinstance(raw_values, list) or len(raw_values) > _MAX_FILES:
        raise ArtifactReceiptError("receipt_reports")
    reports: list[RawReport] = []
    for item_value in raw_values:
        item = _mapping(item_value, "receipt_report")
        if set(item) != {"summary_path", "path", "size_bytes", "digest"}:
            raise ArtifactReceiptError("receipt_report")
        summary_path = _relative_path(item.get("summary_path"), "summary_path")
        key = _gate_key_from_path(summary_path, "junit-summary.json")
        report_path = _relative_path(item.get("path"), "report_path")
        if key not in junit_keys or not report_path.startswith(_report_prefix(*key)):
            raise ArtifactReceiptError("receipt_reports")
        reports.append(
            RawReport(
                summary_path=summary_path,
                path=report_path,
                size_bytes=_positive(
                    item.get("size_bytes"),
                    "report_size",
                    maximum=_MAX_ARTIFACT_ARCHIVE_BYTES,
                ),
                digest=_sha(item.get("digest"), "report_digest"),
            )
        )
    ordered_reports = sorted(reports, key=lambda item: (item.summary_path, item.path))
    report_keys = {
        _gate_key_from_path(item.summary_path, "junit-summary.json")
        for item in reports
    }
    if (
        reports != ordered_reports
        or len({item.path for item in reports}) != len(reports)
        or report_keys != junit_keys
    ):
        raise ArtifactReceiptError("receipt_reports")
    entry_paths = {path for _, path, _ in entries}
    if any(report.path in entry_paths for report in reports):
        raise ArtifactReceiptError("receipt_reports")

    raw_decisions = mapping.get("gate_decisions")
    if (
        not isinstance(raw_decisions, list)
        or not 0 < len(raw_decisions) <= _MAX_FILES
    ):
        raise ArtifactReceiptError("receipt_decisions")
    decisions: list[GateDecision] = []
    decision_keys: set[tuple[str, str]] = set()
    for item_value in raw_decisions:
        item = _mapping(item_value, "receipt_decision")
        if frozenset(item) != _GATE_DECISION_KEYS:
            raise ArtifactReceiptError("receipt_decision")
        gate_id = _identifier(item.get("gate_id"), "decision_gate_id")
        phase = _identifier(item.get("phase"), "decision_phase")
        key = (gate_id, phase)
        if key in decision_keys:
            raise ArtifactReceiptError("receipt_decisions")
        result = _identifier(item.get("result"), "decision_result")
        if result not in _ALLOWED_RESULTS:
            raise ArtifactReceiptError("decision_result")
        result_reason = _text(
            item.get("result_reason"), "decision_result_reason", maximum=512
        )
        test_count = _nonnegative(item.get("test_count"), "decision_test_count")
        failure_count = _nonnegative(
            item.get("failure_count"), "decision_failure_count"
        )
        error_count = _nonnegative(item.get("error_count"), "decision_error_count")
        skip_count = _nonnegative(item.get("skip_count"), "decision_skip_count")
        required_skip_count = _nonnegative(
            item.get("required_skip_count"), "decision_required_skip_count"
        )
        if (
            required_skip_count > skip_count
            or failure_count + error_count + skip_count > test_count
        ):
            raise ArtifactReceiptError("decision_counts")
        raw_fingerprint = item.get("first_failure_fingerprint")
        fingerprint = (
            None
            if raw_fingerprint is None
            else _sha(raw_fingerprint, "decision_failure_fingerprint")
        )
        has_test_failure = bool(failure_count or error_count or required_skip_count)
        if has_test_failure != (fingerprint is not None):
            raise ArtifactReceiptError("decision_failure_fingerprint")
        if result == "PASS" and has_test_failure:
            raise ArtifactReceiptError("decision_pass")
        if contract is not None and gate_id not in {
            str(gate["id"]) for gate in contract.data["gate"].values()
        }:
            raise ArtifactReceiptError("decision_gate_contract")
        _validate_decision_reason(
            result=result,
            gate_id=gate_id,
            phase=phase,
            reason=result_reason,
            has_test_failure=has_test_failure,
        )
        decisions.append(
            GateDecision(
                gate_id=gate_id,
                phase=phase,
                command_spec_digest=_sha(
                    item.get("command_spec_digest"), "decision_command_spec_digest"
                ),
                evidence_identity=_sha(
                    item.get("evidence_identity"), "decision_evidence_identity"
                ),
                result=result,
                result_reason=result_reason,
                queue_ms=_nonnegative(item.get("queue_ms"), "decision_queue_ms"),
                bootstrap_ms=_nonnegative(
                    item.get("bootstrap_ms"), "decision_bootstrap_ms"
                ),
                execution_ms=_nonnegative(
                    item.get("execution_ms"), "decision_execution_ms"
                ),
                finalize_ms=_nonnegative(
                    item.get("finalize_ms"), "decision_finalize_ms"
                ),
                test_count=test_count,
                failure_count=failure_count,
                error_count=error_count,
                skip_count=skip_count,
                required_skip_count=required_skip_count,
                first_failure_fingerprint=fingerprint,
            )
        )
        decision_keys.add(key)
    ordered_decisions = sorted(decisions, key=lambda item: (item.gate_id, item.phase))
    if (
        decisions != ordered_decisions
        or decision_keys != command_keys
        or {
            (decision.gate_id, decision.phase)
            for decision in decisions
            if decision.test_count > 0
        }
        != junit_keys
    ):
        raise ArtifactReceiptError("receipt_decisions")

    normalized = {
        "schema_version": SCHEMA_VERSION,
        "metadata": metadata.as_dict(),
        "envelope_identity": envelope_identity,
        "repository": repository,
        "repository_id": repository_id,
        "head_repository": head_repository,
        "head_repository_id": head_repository_id,
        "producer_job_id": producer_job,
        "consumer_job_id": consumer_job,
        "run_attempt": run_attempt,
        "workflow_ref": workflow_ref,
        "workflow_sha": workflow_sha,
        "event_name": event_name,
        "event_sha": event_sha,
        "evaluated_sha": evaluated_sha,
        "evaluated_tree_sha": evaluated_tree_sha,
        "ref": ref,
        "producer_runner_environment": producer_runner_environment,
        "consumer_runner_environment": consumer_runner_environment,
        "route": route_decision.as_dict(),
        "entries": [
            {"role": role, "path": path, "digest": digest}
            for role, path, digest in entries
        ],
        "raw_reports": [report.as_dict() for report in reports],
        "gate_decisions": [decision.as_dict() for decision in decisions],
    }
    receipt_identity = _sha(mapping.get("receipt_identity"), "receipt_identity")
    if receipt_identity != sha256_identity(normalized):
        raise ArtifactReceiptError("receipt_identity")
    return ArtifactReceipt(
        metadata=metadata,
        envelope_identity=envelope_identity,
        repository=repository,
        repository_id=repository_id,
        head_repository=head_repository,
        head_repository_id=head_repository_id,
        producer_job_id=producer_job,
        consumer_job_id=consumer_job,
        run_attempt=run_attempt,
        workflow_ref=workflow_ref,
        workflow_sha=workflow_sha,
        event_name=event_name,
        event_sha=event_sha,
        evaluated_sha=evaluated_sha,
        evaluated_tree_sha=evaluated_tree_sha,
        ref=ref,
        producer_runner_environment=producer_runner_environment,
        consumer_runner_environment=consumer_runner_environment,
        route=route_decision,
        entry_digests=tuple(entries),
        raw_reports=tuple(reports),
        gate_decisions=tuple(decisions),
        receipt_identity=receipt_identity,
    )


def _safe_output(root: Path, relative: str | Path) -> Path:
    candidate = Path(relative)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or ".." in candidate.parts
        or "\\" in str(relative)
        or candidate.suffix != ".json"
    ):
        raise ArtifactReceiptError("output_path")
    current = root
    for part in candidate.parts[:-1]:
        current /= part
        if current.is_symlink():
            raise ArtifactReceiptError("output_parent")
    resolved_parent = current.resolve()
    if not resolved_parent.is_relative_to(root) or not resolved_parent.is_dir():
        raise ArtifactReceiptError("output_parent")
    path = current / candidate.name
    if path.exists() or path.is_symlink():
        raise ArtifactReceiptError("output_exists")
    return path


def _publish(path: Path, payload: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    linked = False
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
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
            raise ArtifactReceiptError("output_exists") from exc
        except OSError as exc:
            if linked:
                try:
                    path.unlink()
                except OSError:
                    pass
            raise ArtifactReceiptError("output_publish") from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify exact Newsroom artifact receipt")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--expected-job", required=True)
    parser.add_argument("--output")
    arguments = parser.parse_args(argv)
    root = Path(arguments.repo_root).resolve()
    try:
        context = context_from_environment(root)
        receipt = verify_artifact(
            repo_root=root,
            artifact_root=arguments.artifact_root,
            archive_path=arguments.archive,
            metadata_value=load_metadata(arguments.metadata),
            decision_context=context,
            expected_job_id=arguments.expected_job,
        )
        rendered = canonical_json_bytes(receipt.as_dict()) + b"\n"
        if arguments.output:
            _publish(_safe_output(root, arguments.output), rendered)
        else:
            sys.stdout.write(rendered.decode("utf-8"))
    except (
        ArtifactReceiptError,
        ArtifactProvenanceError,
        ContractError,
        EvidenceError,
        OSError,
        UnicodeError,
    ) as exc:
        reason = (
            str(exc)
            if isinstance(exc, ArtifactReceiptError) and str(exc)
            else type(exc).__name__
        )
        print(f"EVIDENCE_MISMATCH:artifact-receipt:{reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
