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
from typing import Mapping, Sequence

from .artifact_envelope import (
    ArtifactEnvelope,
    ArtifactProvenanceError,
    GithubRunContext,
    _artifact_root,
    _load_json_artifact,
    _read_artifact_file,
    _safe_machine_file,
    _unique_object,
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
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_API_PREFIX = "https://api.github.com/repos/fol2/newsroom/actions/artifacts/"


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
class ArtifactReceipt:
    metadata: ArtifactMetadata
    envelope_identity: str
    producer_job_id: str
    consumer_job_id: str
    run_attempt: int
    workflow_ref: str
    workflow_sha: str
    event_name: str
    event_sha: str
    evaluated_sha: str
    evaluated_tree_sha: str
    entry_digests: tuple[tuple[str, str, str], ...]
    raw_reports: tuple[RawReport, ...]
    receipt_identity: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "receipt_identity": self.receipt_identity,
            "metadata": self.metadata.as_dict(),
            "envelope_identity": self.envelope_identity,
            "producer_job_id": self.producer_job_id,
            "consumer_job_id": self.consumer_job_id,
            "run_attempt": self.run_attempt,
            "workflow_ref": self.workflow_ref,
            "workflow_sha": self.workflow_sha,
            "event_name": self.event_name,
            "event_sha": self.event_sha,
            "evaluated_sha": self.evaluated_sha,
            "evaluated_tree_sha": self.evaluated_tree_sha,
            "entries": [
                {"role": role, "path": path, "digest": digest}
                for role, path, digest in self.entry_digests
            ],
            "raw_reports": [report.as_dict() for report in self.raw_reports],
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


def _positive(value: object, code: str, *, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ArtifactReceiptError(code)
    if maximum is not None and value > maximum:
        raise ArtifactReceiptError(code)
    return value


def _sha(value: object, code: str) -> str:
    text = _text(value, code, maximum=71)
    if _SHA256.fullmatch(text) is None:
        raise ArtifactReceiptError(code)
    return text


def _git_sha(value: object, code: str) -> str:
    text = _text(value, code, maximum=40)
    if re.fullmatch(r"[0-9a-f]{40}", text) is None:
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
    if not created <= updated < expires or current >= expires:
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
        run_id != decision_context.run_id
        or run_id != envelope.context.run_id
        or repository_id != decision_context.repository_id
        or repository_id != envelope.context.repository_id
        or head_repository_id != decision_context.head_repository_id
        or head_repository_id != envelope.context.head_repository_id
        or head_sha != decision_context.evaluated_sha
        or head_sha != envelope.context.evaluated_sha
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
) -> None:
    if producer.job_id != expected_job_id or producer.job_id == consumer.job_id:
        raise ArtifactReceiptError("producer_job")
    producer_value = producer.as_dict()
    consumer_value = consumer.as_dict()
    producer_value.pop("job_id")
    consumer_value.pop("job_id")
    if producer_value != consumer_value:
        raise ArtifactReceiptError("producer_context")


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
    gate_id = _text(gate_value.get("gate_id"), "gate_id", maximum=128)
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


def _reconcile_artifacts(
    *,
    contract: SdlcContract,
    root: Path,
    envelope: ArtifactEnvelope,
) -> tuple[tuple[tuple[str, str, str], ...], tuple[RawReport, ...], set[str]]:
    allowed_paths = {"envelope.json"}
    entry_digests: list[tuple[str, str, str]] = []
    routes: list[tuple[str, dict[str, object]]] = []
    command_runs: list[tuple[str, dict[str, object]]] = []
    junit_summaries: list[tuple[str, dict[str, object]]] = []
    evidences: list[tuple[str, dict[str, object]]] = []

    for entry in envelope.entries:
        payload, normalized = _secure_file(root, entry.path)
        if normalized != entry.path or len(payload) != entry.size_bytes:
            raise ArtifactReceiptError("entry_size")
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        if digest != entry.digest:
            raise ArtifactReceiptError("entry_digest")
        allowed_paths.add(entry.path)
        entry_digests.append((entry.role, entry.path, digest))
        value = _load_json_artifact(payload)
        try:
            if entry.role == "route":
                routes.append((entry.path, _validate_route(contract, value)))
            elif entry.role == "command_run":
                command_runs.append((entry.path, _validate_command_run(value)))
            elif entry.role == "junit_summary":
                summary = _validate_junit(value)
                if summary is None:
                    raise ArtifactReceiptError("junit_invalid")
                junit_summaries.append((entry.path, summary))
            elif entry.role == "gate_evidence":
                evidences.append((entry.path, validate_evidence_record(value)))
            else:
                raise ArtifactReceiptError("entry_role")
        except EvidenceError as exc:
            raise ArtifactReceiptError("entry_invalid") from exc

    if len(routes) != 1:
        raise ArtifactReceiptError("route_count")
    route = routes[0][1]
    if (
        route["head_sha"] != envelope.context.evaluated_sha
        or route["head_tree_sha"] != envelope.context.evaluated_tree_sha
    ):
        raise ArtifactReceiptError("route_identity")

    command_by_gate: dict[str, dict[str, object]] = {}
    for _, command_run in command_runs:
        gate_run = _mapping(command_run["gate_run"], "gate_run")
        gate_id = str(gate_run["gate_id"])
        if gate_id in command_by_gate:
            raise ArtifactReceiptError("command_gate_duplicate")
        command_by_gate[gate_id] = command_run

    evidence_by_gate: dict[str, dict[str, object]] = {}
    for _, evidence in evidences:
        gate_id = str(evidence["gate_id"])
        if gate_id in evidence_by_gate:
            raise ArtifactReceiptError("evidence_gate_duplicate")
        evidence_by_gate[gate_id] = evidence
    if set(command_by_gate) != set(evidence_by_gate):
        raise ArtifactReceiptError("gate_pairing")

    unmatched_junit = dict(junit_summaries)
    raw_reports: list[RawReport] = []
    for gate_id, evidence in evidence_by_gate.items():
        command_run = command_by_gate[gate_id]
        gate_run = _mapping(command_run["gate_run"], "gate_run")
        if evidence["gate_inputs_digest"] != _gate_inputs_digest(
            route=route,
            command_run=command_run,
        ):
            raise ArtifactReceiptError("gate_inputs_digest")
        if evidence["head_sha"] != route["head_sha"] or evidence["tree_sha"] != route[
            "head_tree_sha"
        ]:
            raise ArtifactReceiptError("evidence_identity")

        candidates = [
            (path, summary)
            for path, summary in unmatched_junit.items()
            if _junit_signature(summary) == _evidence_signature(evidence)
        ]
        if evidence["test_count"]:
            if len(candidates) != 1:
                raise ArtifactReceiptError("junit_pairing")
            summary_path, summary = candidates[0]
            del unmatched_junit[summary_path]
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
            if evidence["result"] != expected_result or evidence[
                "result_reason"
            ] != expected_reason:
                raise ArtifactReceiptError("evidence_result")
            for report in summary["reports"]:
                report_mapping = _mapping(report, "junit_report")
                path = _text(report_mapping.get("path"), "junit_report_path", maximum=1024)
                if path in allowed_paths:
                    raise ArtifactReceiptError("raw_report_path")
                payload, normalized = _secure_file(root, path)
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
            if candidates:
                raise ArtifactReceiptError("junit_unexpected")
            if any(evidence[field] for field in ("failure_count", "error_count", "skip_count")):
                raise ArtifactReceiptError("zero_test_counts")
            if evidence["result"] != gate_run["result"] or evidence[
                "result_reason"
            ] != gate_run["result_reason"]:
                raise ArtifactReceiptError("evidence_result")

    if unmatched_junit:
        raise ArtifactReceiptError("junit_unpaired")
    return (
        tuple(sorted(entry_digests)),
        tuple(sorted(raw_reports, key=lambda item: (item.summary_path, item.path))),
        allowed_paths,
    )


def _inventory(root: Path) -> set[str]:
    files: set[str] = set()
    for path in root.rglob("*"):
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


def verify_artifact(
    *,
    repo_root: str | Path,
    artifact_root: str | Path,
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
        root = _artifact_root(repository_root, artifact_root)
        envelope = _read_envelope(root)
    except ArtifactProvenanceError as exc:
        raise ArtifactReceiptError("artifact_root") from exc
    _same_run_context(envelope.context, decision_context, expected_job_id)
    metadata = validate_metadata(
        metadata_value,
        envelope=envelope,
        decision_context=decision_context,
        now=now,
    )
    entries, raw_reports, allowed = _reconcile_artifacts(
        contract=accepted,
        root=root,
        envelope=envelope,
    )
    if _inventory(root) != allowed:
        raise ArtifactReceiptError("artifact_extra_files")
    identity_inputs = {
        "schema_version": SCHEMA_VERSION,
        "metadata": metadata.as_dict(),
        "envelope_identity": envelope.envelope_identity,
        "producer_job_id": envelope.context.job_id,
        "consumer_job_id": decision_context.job_id,
        "run_attempt": envelope.context.run_attempt,
        "workflow_ref": envelope.context.workflow_ref,
        "workflow_sha": envelope.context.workflow_sha,
        "event_name": envelope.context.event_name,
        "event_sha": envelope.context.event_sha,
        "evaluated_sha": envelope.context.evaluated_sha,
        "evaluated_tree_sha": envelope.context.evaluated_tree_sha,
        "entries": [
            {"role": role, "path": path, "digest": digest}
            for role, path, digest in entries
        ],
        "raw_reports": [report.as_dict() for report in raw_reports],
    }
    receipt_identity = sha256_identity(identity_inputs)
    return ArtifactReceipt(
        metadata=metadata,
        envelope_identity=envelope.envelope_identity,
        producer_job_id=envelope.context.job_id,
        consumer_job_id=decision_context.job_id,
        run_attempt=envelope.context.run_attempt,
        workflow_ref=envelope.context.workflow_ref,
        workflow_sha=envelope.context.workflow_sha,
        event_name=envelope.context.event_name,
        event_sha=envelope.context.event_sha,
        evaluated_sha=envelope.context.evaluated_sha,
        evaluated_tree_sha=envelope.context.evaluated_tree_sha,
        entry_digests=entries,
        raw_reports=raw_reports,
        receipt_identity=receipt_identity,
    )


def validate_receipt(value: object) -> ArtifactReceipt:
    mapping = _mapping(value, "receipt")
    if mapping.get("schema_version") != SCHEMA_VERSION:
        raise ArtifactReceiptError("receipt_schema")
    receipt_identity = _sha(mapping.get("receipt_identity"), "receipt_identity")
    metadata_value = _mapping(mapping.get("metadata"), "receipt_metadata")
    metadata = ArtifactMetadata(
        artifact_id=_positive(metadata_value.get("artifact_id"), "artifact_id"),
        name=_text(metadata_value.get("name"), "artifact_name", maximum=255),
        size_bytes=_positive(
            metadata_value.get("size_bytes"),
            "artifact_size",
            maximum=_MAX_ARTIFACT_ARCHIVE_BYTES,
        ),
        digest=_sha(metadata_value.get("digest"), "artifact_digest"),
        created_at=_timestamp(metadata_value.get("created_at"), "created_at")[0],
        updated_at=_timestamp(metadata_value.get("updated_at"), "updated_at")[0],
        expires_at=_timestamp(metadata_value.get("expires_at"), "expires_at")[0],
        run_id=_positive(metadata_value.get("run_id"), "run_id"),
        repository_id=_positive(metadata_value.get("repository_id"), "repository_id"),
        head_repository_id=_positive(
            metadata_value.get("head_repository_id"), "head_repository_id"
        ),
        head_sha=_git_sha(metadata_value.get("head_sha"), "head_sha"),
    )
    raw_entries = mapping.get("entries")
    if not isinstance(raw_entries, list) or len(raw_entries) > _MAX_FILES:
        raise ArtifactReceiptError("receipt_entries")
    entries: list[tuple[str, str, str]] = []
    for item_value in raw_entries:
        item = _mapping(item_value, "receipt_entry")
        if set(item) != {"role", "path", "digest"}:
            raise ArtifactReceiptError("receipt_entry")
        entries.append(
            (
                _text(item.get("role"), "entry_role", maximum=64),
                _text(item.get("path"), "entry_path", maximum=1024),
                _sha(item.get("digest"), "entry_digest"),
            )
        )
    if entries != sorted(entries) or len({path for _, path, _ in entries}) != len(entries):
        raise ArtifactReceiptError("receipt_entries")
    raw_values = mapping.get("raw_reports")
    if not isinstance(raw_values, list) or len(raw_values) > _MAX_FILES:
        raise ArtifactReceiptError("receipt_reports")
    reports: list[RawReport] = []
    for item_value in raw_values:
        item = _mapping(item_value, "receipt_report")
        if set(item) != {"summary_path", "path", "size_bytes", "digest"}:
            raise ArtifactReceiptError("receipt_report")
        reports.append(
            RawReport(
                summary_path=_text(
                    item.get("summary_path"), "summary_path", maximum=1024
                ),
                path=_text(item.get("path"), "report_path", maximum=1024),
                size_bytes=_positive(
                    item.get("size_bytes"),
                    "report_size",
                    maximum=_MAX_ARTIFACT_ARCHIVE_BYTES,
                ),
                digest=_sha(item.get("digest"), "report_digest"),
            )
        )
    ordered_reports = sorted(reports, key=lambda item: (item.summary_path, item.path))
    if reports != ordered_reports or len({item.path for item in reports}) != len(reports):
        raise ArtifactReceiptError("receipt_reports")
    identity_inputs = {
        key: mapping[key]
        for key in (
            "schema_version",
            "metadata",
            "envelope_identity",
            "producer_job_id",
            "consumer_job_id",
            "run_attempt",
            "workflow_ref",
            "workflow_sha",
            "event_name",
            "event_sha",
            "evaluated_sha",
            "evaluated_tree_sha",
            "entries",
            "raw_reports",
        )
        if key in mapping
    }
    if set(mapping) != set(identity_inputs) | {"receipt_identity"}:
        raise ArtifactReceiptError("receipt_shape")
    if receipt_identity != sha256_identity(identity_inputs):
        raise ArtifactReceiptError("receipt_identity")
    return ArtifactReceipt(
        metadata=metadata,
        envelope_identity=_sha(mapping.get("envelope_identity"), "envelope_identity"),
        producer_job_id=_text(
            mapping.get("producer_job_id"), "producer_job_id", maximum=128
        ),
        consumer_job_id=_text(
            mapping.get("consumer_job_id"), "consumer_job_id", maximum=128
        ),
        run_attempt=_positive(mapping.get("run_attempt"), "run_attempt"),
        workflow_ref=_text(mapping.get("workflow_ref"), "workflow_ref"),
        workflow_sha=_git_sha(mapping.get("workflow_sha"), "workflow_sha"),
        event_name=_text(mapping.get("event_name"), "event_name", maximum=64),
        event_sha=_git_sha(mapping.get("event_sha"), "event_sha"),
        evaluated_sha=_git_sha(mapping.get("evaluated_sha"), "evaluated_sha"),
        evaluated_tree_sha=_git_sha(
            mapping.get("evaluated_tree_sha"), "evaluated_tree_sha"
        ),
        entry_digests=tuple(entries),
        raw_reports=tuple(reports),
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
