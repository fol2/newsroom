"""Deterministic fixture reconciliation, backup, restore, purge and fault evidence."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, ClassVar, Self

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
    validate_sha256_digest,
)
from newsroom.authority.increment8_recovery_migrations import _helpers
from newsroom.increment8.operations import DueWork, Urgency, WorkState
from newsroom.increment8.readiness import INCREMENT_8_READINESS


class RecoveryError(ValueError):
    """Recovery evidence violates the frozen Operational Profile."""


class RecoveryStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class FaultScenario(StrEnum):
    STORE_FAILURE = "STORE_FAILURE"
    ORPHANED_OWNERSHIP = "ORPHANED_OWNERSHIP"
    MISSING_OUTCOME = "MISSING_OUTCOME"
    AMBIGUOUS_EFFECT = "AMBIGUOUS_EFFECT"
    DUPLICATE_DELIVERY = "DUPLICATE_DELIVERY"
    STALE_WORK = "STALE_WORK"
    PENDING_HANDOFF = "PENDING_HANDOFF"
    PROJECTION_MISMATCH = "PROJECTION_MISMATCH"


_FINDINGS = tuple(scenario.value for scenario in FaultScenario if scenario is not FaultScenario.STORE_FAILURE)
_EXPECTED_FAULT_OUTCOME = {
    FaultScenario.STORE_FAILURE: "FAIL_CLOSED",
    FaultScenario.ORPHANED_OWNERSHIP: "LEASE_ORPHANED",
    FaultScenario.MISSING_OUTCOME: "RETAIN_PENDING",
    FaultScenario.AMBIGUOUS_EFFECT: "BLOCK_AND_RECONCILE",
    FaultScenario.DUPLICATE_DELIVERY: "DEDUPLICATE",
    FaultScenario.STALE_WORK: "REVALIDATE",
    FaultScenario.PENDING_HANDOFF: "RETAIN_PENDING",
    FaultScenario.PROJECTION_MISMATCH: "BLOCK_PROJECTION",
}


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise RecoveryError(f"{field} must be an integer >= {minimum}")
    return value


def _token(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or len(value.encode()) > 256:
        raise RecoveryError(f"{field} must be bounded text")
    allowed = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-/")
    if any(character not in allowed for character in value):
        raise RecoveryError(f"{field} contains unsupported characters")
    return value


def _digest(value: object, field: str) -> str:
    try:
        return validate_sha256_digest(value, field=field)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise RecoveryError(f"{field} must be a canonical digest") from exc


def _time(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise RecoveryError(f"{field} must be canonical UTC text")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise RecoveryError(f"{field} must be canonical UTC text") from exc
    if parsed.utcoffset() != timedelta(0):
        raise RecoveryError(f"{field} must be UTC")
    return value


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")


def _record(schema: str, id_field: str, prefix: str, payload: Mapping[str, object]) -> tuple[str, bytes, str]:
    identity = digest_canonical({"schema_version": schema, "payload": payload})
    identifier = f"{prefix}:{identity.removeprefix('sha256:')}"
    raw = canonical_json_bytes({"schema_version": schema, id_field: identifier, "payload": dict(payload)})
    return identifier, raw, digest_bytes(raw)


def _decode(raw: bytes, schema: str, id_field: str, prefix: str) -> tuple[str, Mapping[str, Any]]:
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RecoveryError("record bytes are not canonical JSON") from exc
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise RecoveryError("record bytes are not canonical JSON")
    payload = value.get("payload")
    if set(value) != {"schema_version", id_field, "payload"} or value["schema_version"] != schema or not isinstance(payload, dict):
        raise RecoveryError("record envelope differs")
    identifier, expected, _ = _record(schema, id_field, prefix, payload)
    if value[id_field] != identifier or expected != raw:
        raise RecoveryError("record identity differs")
    return identifier, MappingProxyType(payload)


@dataclass(frozen=True, slots=True)
class _Record:
    identifier: str
    canonical_bytes: bytes
    digest: str
    payload: Mapping[str, object]
    SCHEMA: ClassVar[str]
    ID_FIELD: ClassVar[str]
    PREFIX: ClassVar[str]

    @classmethod
    def build(cls, payload: Mapping[str, object]) -> Self:
        identifier, raw, record_digest = _record(cls.SCHEMA, cls.ID_FIELD, cls.PREFIX, payload)
        return cls(identifier, raw, record_digest, MappingProxyType(dict(payload)))

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        identifier, payload = _decode(raw, cls.SCHEMA, cls.ID_FIELD, cls.PREFIX)
        return cls(identifier, raw, digest_bytes(raw), payload)


@dataclass(frozen=True, slots=True)
class ReconciliationRun(_Record):
    SCHEMA = "newsroom.increment8.reconciliation-run.v1"
    ID_FIELD = "reconciliation_id"
    PREFIX = "reconciliation"

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        identifier, payload = _decode(raw, cls.SCHEMA, cls.ID_FIELD, cls.PREFIX)
        base_fields = {
            "profile_digest", "authority_version_digest", "finding_counts",
            "replay_item_count", "maximum_replay_items", "started_at", "completed_at",
            "status", "automatic_operation_blocked", "model_decision_used",
        }
        restore_fields = {"restore_id", "restore_digest", "restored_state_digest"}
        if frozenset(payload) not in {
            frozenset(base_fields),
            frozenset(base_fields | restore_fields),
        }:
            raise RecoveryError("reconciliation Run payload differs")
        finding_counts = payload["finding_counts"]
        if not isinstance(finding_counts, dict) or tuple(sorted(finding_counts)) != tuple(sorted(_FINDINGS)):
            raise RecoveryError("reconciliation Finding inventory differs")
        findings = {
            name: _integer(finding_counts[name], name) for name in sorted(_FINDINGS)
        }
        replay = _integer(payload["replay_item_count"], "replay_item_count")
        maximum = int(INCREMENT_8_READINESS.operational_profile["recovery"]["maximum_replay_items"])  # type: ignore[index]
        start = _time(payload["started_at"], "started_at")
        complete = _time(payload["completed_at"], "completed_at")
        passed = not any(findings.values())
        if (
            payload["profile_digest"] != _digest(payload["profile_digest"], "profile_digest")
            or payload["authority_version_digest"]
            != _digest(payload["authority_version_digest"], "authority_version_digest")
            or payload["maximum_replay_items"] != maximum
            or replay > maximum
            or _dt(complete) < _dt(start)
            or payload["status"]
            != (RecoveryStatus.PASS.value if passed else RecoveryStatus.FAIL.value)
            or payload["automatic_operation_blocked"] is not (not passed)
            or payload["model_decision_used"] is not False
        ):
            raise RecoveryError("reconciliation Run semantics differ")
        if restore_fields <= set(payload):
            _token(payload["restore_id"], "restore_id")
            _digest(payload["restore_digest"], "restore_digest")
            _digest(payload["restored_state_digest"], "restored_state_digest")
        rebuilt = cls.build(dict(payload))
        if rebuilt.identifier != identifier or rebuilt.canonical_bytes != raw:
            raise RecoveryError("reconciliation Run identity differs")
        return cls(identifier, raw, digest_bytes(raw), payload)


@dataclass(frozen=True, slots=True)
class BackupManifest(_Record):
    SCHEMA = "newsroom.increment8.backup-manifest.v1"
    ID_FIELD = "backup_id"
    PREFIX = "backup"


@dataclass(frozen=True, slots=True)
class RestoreRun(_Record):
    SCHEMA = "newsroom.increment8.restore-run.v1"
    ID_FIELD = "restore_id"
    PREFIX = "restore"


@dataclass(frozen=True, slots=True)
class PurgeReceipt(_Record):
    SCHEMA = "newsroom.increment8.purge-receipt.v1"
    ID_FIELD = "purge_id"
    PREFIX = "purge"


@dataclass(frozen=True, slots=True)
class FaultInjectionRun(_Record):
    SCHEMA = "newsroom.increment8.fault-injection-run.v1"
    ID_FIELD = "fault_run_id"
    PREFIX = "fault-run"

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        identifier, payload = _decode(raw, cls.SCHEMA, cls.ID_FIELD, cls.PREFIX)
        required = {
            "profile_digest", "scenario", "expected_outcome", "observed_outcome",
            "completed_at", "status", "live_effect_authorised",
        }
        if set(payload) != required:
            raise RecoveryError("fault Injection Run payload differs")
        try:
            scenario = FaultScenario(payload["scenario"])
        except (TypeError, ValueError) as exc:
            raise RecoveryError("fault scenario differs") from exc
        expected = _EXPECTED_FAULT_OUTCOME[scenario]
        observed = _token(payload["observed_outcome"], "observed_outcome")
        status = RecoveryStatus.PASS.value if observed == expected else RecoveryStatus.FAIL.value
        if (
            payload["profile_digest"] != _digest(payload["profile_digest"], "profile_digest")
            or payload["expected_outcome"] != expected
            or payload["completed_at"] != _time(payload["completed_at"], "completed_at")
            or payload["status"] != status
            or payload["live_effect_authorised"] is not False
        ):
            raise RecoveryError("fault Injection Run semantics differ")
        rebuilt = cls.build(dict(payload))
        if rebuilt.identifier != identifier or rebuilt.canonical_bytes != raw:
            raise RecoveryError("fault Injection Run identity differs")
        return cls(identifier, raw, digest_bytes(raw), payload)


@dataclass(frozen=True, slots=True)
class ReplayReceipt(_Record):
    SCHEMA = "newsroom.increment8.replay-receipt.v1"
    ID_FIELD = "replay_id"
    PREFIX = "replay"


def build_reconciliation_run(
    *,
    profile_digest: str,
    authority_version_digest: str,
    finding_counts: Mapping[str, int],
    replay_item_count: int,
    started_at: str,
    completed_at: str,
) -> ReconciliationRun:
    if tuple(sorted(finding_counts)) != tuple(sorted(_FINDINGS)):
        raise RecoveryError("reconciliation Finding inventory differs")
    findings = {name: _integer(finding_counts[name], name) for name in sorted(_FINDINGS)}
    replay = _integer(replay_item_count, "replay_item_count")
    maximum = int(INCREMENT_8_READINESS.operational_profile["recovery"]["maximum_replay_items"])  # type: ignore[index]
    start = _time(started_at, "started_at")
    complete = _time(completed_at, "completed_at")
    if _dt(complete) < _dt(start) or replay > maximum:
        raise RecoveryError("reconciliation exceeds time or replay bounds")
    passed = not any(findings.values())
    return ReconciliationRun.build(
        {
            "profile_digest": _digest(profile_digest, "profile_digest"),
            "authority_version_digest": _digest(authority_version_digest, "authority_version_digest"),
            "finding_counts": findings,
            "replay_item_count": replay,
            "maximum_replay_items": maximum,
            "started_at": start,
            "completed_at": complete,
            "status": RecoveryStatus.PASS.value if passed else RecoveryStatus.FAIL.value,
            "automatic_operation_blocked": not passed,
            "model_decision_used": False,
        }
    )


def build_restore_reconciliation_run(
    *,
    restore: RestoreRun,
    profile_digest: str,
    authority_version_digest: str,
    finding_counts: Mapping[str, int],
    replay_item_count: int,
    started_at: str,
    completed_at: str,
) -> ReconciliationRun:
    if not isinstance(restore, RestoreRun):
        raise RecoveryError("restore reconciliation requires an exact Restore Run")
    rebuilt_restore = RestoreRun.from_canonical_bytes(restore.canonical_bytes)
    if rebuilt_restore != restore:
        raise RecoveryError("restore reconciliation requires an exact Restore Run")
    if _dt(_time(started_at, "started_at")) < _dt(
        str(restore.payload["completed_at"])
    ):
        raise RecoveryError("restore reconciliation starts before Restore Run completion")
    base = build_reconciliation_run(
        profile_digest=profile_digest,
        authority_version_digest=authority_version_digest,
        finding_counts=finding_counts,
        replay_item_count=replay_item_count,
        started_at=started_at,
        completed_at=completed_at,
    )
    return ReconciliationRun.build(
        {
            **base.payload,
            "restore_id": restore.identifier,
            "restore_digest": restore.digest,
            "restored_state_digest": restore.payload["restored_logical_digest"],
        }
    )


def create_checked_backup(
    connection: sqlite3.Connection,
    destination: Path,
    *,
    profile_digest: str,
    authority_version_digest: str,
    audit_state_digest: str,
    created_at: str,
    retain_until: str,
) -> BackupManifest:
    if not isinstance(connection, sqlite3.Connection) or connection.in_transaction or not isinstance(destination, Path) or not destination.is_absolute():
        raise RecoveryError("backup requires idle connection and absolute destination")
    if destination.exists():
        raise RecoveryError("backup destination already exists")
    created = _time(created_at, "created_at")
    retained = _time(retain_until, "retain_until")
    minimum_retention = int(INCREMENT_8_READINESS.operational_profile["recovery"]["backup_retention_days"])  # type: ignore[index]
    if _dt(retained) < _dt(created) + timedelta(days=minimum_retention):
        raise RecoveryError("backup retention is below the frozen Profile")
    if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
        raise RecoveryError("source integrity check failed")
    logical = _helpers._logical_database_digest(connection)
    created_destination = False
    target: sqlite3.Connection | None = None
    try:
        destination.open("xb").close()
        created_destination = True
        target = sqlite3.connect(destination, isolation_level=None)
        connection.backup(target)
        if target.execute("PRAGMA integrity_check").fetchone() != ("ok",) or _helpers._logical_database_digest(target) != logical:
            raise RecoveryError("backup integrity differs")
        target.close()
        target = None
        file_digest = _helpers._file_digest(destination)
        return BackupManifest.build(
            {
                "profile_digest": _digest(profile_digest, "profile_digest"),
                "authority_version_digest": _digest(authority_version_digest, "authority_version_digest"),
                "audit_state_digest": _digest(audit_state_digest, "audit_state_digest"),
                "authority_logical_digest": logical,
                "backup_file_digest": file_digest,
                "created_at": created,
                "retain_until": retained,
                "rpo_seconds": int(INCREMENT_8_READINESS.operational_profile["recovery"]["backup_rpo_seconds"]),  # type: ignore[index]
                "included_state": ["AUDIT", "AUTHORITY", "BASELINE", "DEDUPE", "PENDING_WORK"],
                "integrity_status": RecoveryStatus.PASS.value,
                "live_effect_authorised": False,
            }
        )
    except Exception:
        if target is not None:
            target.close()
        if created_destination:
            destination.unlink(missing_ok=True)
        raise


def restore_checked_backup(
    manifest: BackupManifest,
    source: Path,
    destination: Path,
    *,
    completed_at: str,
) -> RestoreRun:
    if not isinstance(manifest, BackupManifest) or BackupManifest.from_canonical_bytes(manifest.canonical_bytes) != manifest:
        raise RecoveryError("backup Manifest is forged")
    if not all(isinstance(path, Path) and path.is_absolute() for path in (source, destination)) or not source.is_file() or destination.exists():
        raise RecoveryError("restore path boundary differs")
    if not destination.parent.is_dir():
        raise RecoveryError("restore destination parent is absent")
    completed = _time(completed_at, "completed_at")
    if _helpers._file_digest(source) != manifest.payload["backup_file_digest"]:
        raise RecoveryError("backup file digest differs")
    incoming = sqlite3.connect(f"file:{source}?mode=ro", uri=True, isolation_level=None)
    target: sqlite3.Connection | None = None
    created_destination = False
    try:
        if incoming.execute("PRAGMA integrity_check").fetchone() != ("ok",) or _helpers._logical_database_digest(incoming) != manifest.payload["authority_logical_digest"]:
            raise RecoveryError("backup logical state differs")
        destination.open("xb").close()
        created_destination = True
        target = sqlite3.connect(destination, isolation_level=None)
        incoming.backup(target)
        restored = _helpers._logical_database_digest(target)
        if target.execute("PRAGMA integrity_check").fetchone() != ("ok",) or restored != manifest.payload["authority_logical_digest"]:
            raise RecoveryError("restored authority differs")
    except Exception:
        if target is not None:
            target.close()
            target = None
        if created_destination:
            destination.unlink(missing_ok=True)
        raise
    finally:
        incoming.close()
        if target is not None:
            target.close()
    return RestoreRun.build(
        {
            "backup_id": manifest.identifier,
            "backup_manifest_digest": manifest.digest,
            "restored_logical_digest": str(manifest.payload["authority_logical_digest"]),
            "completed_at": completed,
            "status": "RECONCILIATION_REQUIRED",
            "automatic_operation_resumed": False,
            "baselines_reconciled": False,
            "leases_reconciled": False,
            "queues_reconciled": False,
            "handoffs_reconciled": False,
            "coverage_reconciled": False,
        }
    )


def build_replay_receipt(
    *,
    input_digest: str,
    later_output_digest: str,
    version_digests: Sequence[str],
    replay_item_count: int,
    completed_at: str,
) -> ReplayReceipt:
    source = _digest(input_digest, "input_digest")
    output = _digest(later_output_digest, "later_output_digest")
    versions = tuple(_digest(value, "version_digests") for value in version_digests)
    if not versions or versions != tuple(sorted(set(versions))) or source == output:
        raise RecoveryError("replay must bind exact versions and a later output")
    count = _integer(replay_item_count, "replay_item_count", minimum=1)
    maximum = int(INCREMENT_8_READINESS.operational_profile["recovery"]["maximum_replay_items"])  # type: ignore[index]
    if count > maximum:
        raise RecoveryError("replay exceeds the frozen bound")
    return ReplayReceipt.build(
        {
            "input_digest": source,
            "later_output_digest": output,
            "version_digests": list(versions),
            "replay_item_count": count,
            "completed_at": _time(completed_at, "completed_at"),
            "history_rewritten": False,
            "model_decision_used": False,
        }
    )


def build_purge_receipt(
    *,
    scope_digest: str,
    before_digest: str,
    after_digest: str,
    authorised_by_digest: str,
    reason_class: str,
    purged_at: str,
) -> PurgeReceipt:
    before = _digest(before_digest, "before_digest")
    after = _digest(after_digest, "after_digest")
    if before == after:
        raise RecoveryError("purge must change retained scope state")
    return PurgeReceipt.build(
        {
            "scope_digest": _digest(scope_digest, "scope_digest"),
            "before_digest": before,
            "after_digest": after,
            "authorised_by_digest": _digest(authorised_by_digest, "authorised_by_digest"),
            "reason_class": _token(reason_class, "reason_class"),
            "purged_at": _time(purged_at, "purged_at"),
            "rebuild_required": True,
            "automatic_operation_resumed": False,
        }
    )


def build_fault_injection_run(
    *,
    profile_digest: str,
    scenario: FaultScenario,
    observed_outcome: str,
    completed_at: str,
) -> FaultInjectionRun:
    if not isinstance(scenario, FaultScenario):
        raise RecoveryError("fault scenario must be typed")
    observed = _token(observed_outcome, "observed_outcome")
    expected = _EXPECTED_FAULT_OUTCOME[scenario]
    passed = observed == expected
    return FaultInjectionRun.build(
        {
            "profile_digest": _digest(profile_digest, "profile_digest"),
            "scenario": scenario.value,
            "expected_outcome": expected,
            "observed_outcome": observed,
            "completed_at": _time(completed_at, "completed_at"),
            "status": RecoveryStatus.PASS.value if passed else RecoveryStatus.FAIL.value,
            "live_effect_authorised": False,
        }
    )


def bounded_catch_up(work: Sequence[DueWork]) -> tuple[DueWork, ...]:
    if any(not isinstance(item, DueWork) for item in work):
        raise RecoveryError("catch-up requires typed due work")
    try:
        reconstructed = tuple(_reconstruct_due_work(item.canonical_bytes) for item in work)
    except (TypeError, ValueError) as exc:
        raise RecoveryError("catch-up DueWork is forged") from exc
    if any(rebuilt != supplied for rebuilt, supplied in zip(reconstructed, work, strict=True)):
        raise RecoveryError("catch-up DueWork is forged")
    maximum = int(INCREMENT_8_READINESS.operational_profile["schedule"]["maximum_catch_up_items"])  # type: ignore[index]
    urgency = {Urgency.URGENT.value: 0, Urgency.TIME_SENSITIVE.value: 1, Urgency.PLANNED.value: 2, Urgency.ROUTINE.value: 3}
    try:
        ordered = sorted(reconstructed, key=lambda item: (urgency[str(item.payload["urgency"])], _dt(str(item.payload["deadline_at"])), item.work_id))
    except (KeyError, TypeError, ValueError) as exc:
        raise RecoveryError("catch-up DueWork semantics differ") from exc
    return tuple(ordered[:maximum])


def _reconstruct_due_work(raw: bytes) -> DueWork:
    work = DueWork.from_canonical_bytes(raw)
    payload = work.payload
    required = {
        "work_id", "state_version", "profile_record_id", "profile_digest",
        "logical_due_key", "scope_kind", "urgency", "state", "attempt_count",
        "due_at", "deadline_at", "previous_digest", "authority_version_digest",
        "editorial_rejection", "model_scheduling_used",
    }
    if set(payload) != required:
        raise RecoveryError("catch-up DueWork payload differs")
    version = _integer(payload["state_version"], "state_version", minimum=1)
    attempts = _integer(payload["attempt_count"], "attempt_count")
    profile_digest = _digest(payload["profile_digest"], "profile_digest")
    profile_record_id = _token(payload["profile_record_id"], "profile_record_id")
    key = _token(payload["logical_due_key"], "logical_due_key")
    kind = _token(payload["scope_kind"], "scope_kind")
    try:
        urgency = Urgency(payload["urgency"])
        state = WorkState(payload["state"])
    except (TypeError, ValueError) as exc:
        raise RecoveryError("catch-up DueWork state or urgency differs") from exc
    due = _time(payload["due_at"], "due_at")
    deadline = _time(payload["deadline_at"], "deadline_at")
    expected_work_id = "work:" + digest_canonical(
        {"profile_digest": profile_digest, "logical_due_key": key}
    ).removeprefix("sha256:")
    previous = payload["previous_digest"]
    if (
        payload["work_id"] != expected_work_id
        or len(profile_record_id) != len("profile:") + 64
        or not profile_record_id.startswith("profile:")
        or any(character not in "0123456789abcdef" for character in profile_record_id.removeprefix("profile:"))
        or kind not in INCREMENT_8_READINESS.operational_profile["scope_kinds"]
        or payload["urgency"] != urgency.value
        or payload["state"] != state.value
        or _dt(deadline) < _dt(due)
        or attempts >= version
        or payload["authority_version_digest"]
        != _digest(payload["authority_version_digest"], "authority_version_digest")
        or payload["editorial_rejection"] is not False
        or payload["model_scheduling_used"] is not False
    ):
        raise RecoveryError("catch-up DueWork semantics differ")
    if version == 1:
        if state is not WorkState.QUEUED or attempts != 0 or previous is not None:
            raise RecoveryError("catch-up initial DueWork semantics differ")
    elif previous != _digest(previous, "previous_digest"):
        raise RecoveryError("catch-up DueWork predecessor differs")
    lineage_is_reachable = (
        (state is WorkState.QUEUED and version == 1 and attempts == 0)
        or (state is WorkState.LEASED and attempts >= 1 and version == 2 * attempts)
        or (
            state in {WorkState.RETRY_PENDING, WorkState.COMPLETED}
            and attempts >= 1
            and version == 2 * attempts + 1
        )
        or (state is WorkState.EXPLICITLY_CLOSED and version == 2 * attempts + 2)
        or (
            state is WorkState.QUARANTINED
            and (
                (attempts == 0 and version == 2)
                or (attempts >= 1 and version in {2 * attempts + 1, 2 * attempts + 2})
            )
        )
    )
    if not lineage_is_reachable:
        raise RecoveryError("catch-up DueWork attempt lineage differs")
    if state not in {WorkState.QUEUED, WorkState.RETRY_PENDING}:
        raise RecoveryError("catch-up DueWork is not operationally due")
    return work


class RecoveryAuthority:
    """Append-only schema-v32 fixture recovery authority."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        if (
            not isinstance(connection, sqlite3.Connection)
            or connection.in_transaction
            or connection.execute("PRAGMA user_version").fetchone()[0] < 32
            or connection.execute("PRAGMA foreign_keys").fetchone() != (1,)
        ):
            raise RecoveryError("recovery authority requires idle foreign-key-enabled schema v32 connection")
        self._connection = connection

    def _insert(self, sql: str, values: tuple[object, ...]) -> None:
        if (
            self._connection.in_transaction
            or self._connection.execute("PRAGMA foreign_keys").fetchone() != (1,)
        ):
            raise RecoveryError("recovery write requires idle foreign-key-enabled connection")
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._connection.execute(sql, values)
            self._connection.execute("COMMIT")
        except Exception:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise

    def append_reconciliation(self, run: ReconciliationRun) -> None:
        if not isinstance(run, ReconciliationRun) or ReconciliationRun.from_canonical_bytes(run.canonical_bytes) != run:
            raise RecoveryError("Reconciliation Run is forged")
        self._insert("INSERT INTO reconciliation_runs VALUES(?,?,?,?,?,?,?,?)", (run.identifier, run.canonical_bytes, run.digest, run.payload["profile_digest"], run.payload["started_at"], run.payload["completed_at"], run.payload["status"], int(bool(run.payload["automatic_operation_blocked"]))))

    def append_backup(self, manifest: BackupManifest) -> None:
        if not isinstance(manifest, BackupManifest) or BackupManifest.from_canonical_bytes(manifest.canonical_bytes) != manifest:
            raise RecoveryError("Backup Manifest is forged")
        self._insert("INSERT INTO backup_manifests VALUES(?,?,?,?,?,?,?,?)", (manifest.identifier, manifest.canonical_bytes, manifest.digest, manifest.payload["authority_logical_digest"], manifest.payload["backup_file_digest"], manifest.payload["created_at"], manifest.payload["retain_until"], manifest.payload["integrity_status"]))

    def append_restore(self, run: RestoreRun) -> None:
        if not isinstance(run, RestoreRun) or RestoreRun.from_canonical_bytes(run.canonical_bytes) != run:
            raise RecoveryError("Restore Run is forged")
        self._insert("INSERT INTO restore_runs VALUES(?,?,?,?,?,?,?,?)", (run.identifier, run.canonical_bytes, run.digest, run.payload["backup_id"], run.payload["restored_logical_digest"], run.payload["completed_at"], run.payload["status"], 0))

    def append_purge(self, receipt: PurgeReceipt) -> None:
        if not isinstance(receipt, PurgeReceipt) or PurgeReceipt.from_canonical_bytes(receipt.canonical_bytes) != receipt:
            raise RecoveryError("Purge Receipt is forged")
        self._insert("INSERT INTO purge_receipts VALUES(?,?,?,?,?,?,?,?,?)", (receipt.identifier, receipt.canonical_bytes, receipt.digest, receipt.payload["scope_digest"], receipt.payload["before_digest"], receipt.payload["after_digest"], receipt.payload["authorised_by_digest"], receipt.payload["purged_at"], 1))

    def append_fault(self, run: FaultInjectionRun) -> None:
        if not isinstance(run, FaultInjectionRun) or FaultInjectionRun.from_canonical_bytes(run.canonical_bytes) != run:
            raise RecoveryError("Fault Injection Run is forged")
        self._insert("INSERT INTO fault_injection_runs VALUES(?,?,?,?,?,?,?,?)", (run.identifier, run.canonical_bytes, run.digest, run.payload["profile_digest"], run.payload["scenario"], run.payload["completed_at"], run.payload["status"], 0))


__all__ = [
    "BackupManifest", "FaultInjectionRun", "FaultScenario", "PurgeReceipt", "ReconciliationRun",
    "RecoveryAuthority", "RecoveryError", "RecoveryStatus", "ReplayReceipt", "RestoreRun",
    "bounded_catch_up", "build_fault_injection_run", "build_purge_receipt", "build_reconciliation_run",
    "build_replay_receipt", "build_restore_reconciliation_run", "create_checked_backup",
    "restore_checked_backup",
]
