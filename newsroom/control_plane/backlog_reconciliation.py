"""No-loss remap of poll-amplified identities onto effective revisions.

Independent of the live identity resolver: a bug there cannot approve this
migration. Repair means remap; append-only evidence is never deleted.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from newsroom.authority.auth import AuthenticationProof
from newsroom.authority.canonical import digest_canonical
from newsroom.authority.types import UtcTimestamp
from newsroom.control_plane.command_auth import (
    COMMAND_SERVICE_PRINCIPAL,
    HERMES_COMMAND_PRINCIPAL,
    RECONCILE_COMMAND_TYPE,
)
from newsroom.control_plane.corpus import effective_pull_ingest_ids
from newsroom.control_plane.items import parse_observation
from newsroom.control_plane.paths import (
    CANONICAL_PROVING_STORE,
    CANONICAL_UNPUBLISHED_STORE,
)
from newsroom.control_plane.proving_revision_schema import (
    ensure_proving_revision_schema,
)
from newsroom.control_plane.sqlite_profile import (
    BUSY_TIMEOUT_MS,
    apply_control_plane_sqlite_profile,
)
from newsroom.control_plane.store import (
    _ensure_landed_schema,
    append_ledger,
    ensure_reconciliation_schema,
)

# Must match newsroom.control_plane.cycle._RAW_HTTP_RETENTION.
RAW_HTTP_RETENTION = timedelta(days=7)
RECONCILIATION_KIND = "EFFECTIVE_REVISION_BACKLOG_RECONCILED"
SOURCE_SUPPLIED_VERSION_MARKER = "SOURCE_SUPPLIED_VERSION_MARKER"
FIRST_SEEN_WITHOUT_RETAINED_OBSERVATION = "FIRST_SEEN_WITHOUT_RETAINED_OBSERVATION"
RETENTION_WINDOW_BOUNDED_INACCURACY = "RETENTION_WINDOW_BOUNDED_INACCURACY"
GRAPH_EFFECT_AMBIGUOUS_COVERAGE = "GRAPH_EFFECT_AMBIGUOUS_COVERAGE"
RETAINED_LINEAGE_REMAP = "RETAINED_LINEAGE_REMAP"
ALLOWED_CALLER_PRINCIPALS = frozenset({HERMES_COMMAND_PRINCIPAL})
ALLOWED_COMMAND_TYPES = frozenset({RECONCILE_COMMAND_TYPE})
BACKUP_DIR_MODE = 0o700
BACKUP_FILE_MODE = 0o600
COORDINATOR_NAME = "dual_store_mutation.json"
PROVING_ATTACH_SCHEMA = "proving"
LIVE_TRANSACTION_TIMEOUT_SECONDS = BUSY_TIMEOUT_MS / 1_000


class BacklogReconciliationError(RuntimeError):
    """A fail-closed reconciliation gate refused to mutate."""


class CanonicalStoreGuardError(BacklogReconciliationError):
    """Writable access to a canonical Control Plane store was refused."""


class ReconciliationCommandError(BacklogReconciliationError):
    """Live mutation refused the caller principal, command, or version fence."""


@dataclass(frozen=True, slots=True)
class _ReconciliationCommand:
    caller_principal: str
    writer_principal: str
    command_type: str
    idempotency_key: str
    expected_mapping_digest: str

    def as_dict(self) -> dict[str, str]:
        return {
            "caller_principal": self.caller_principal,
            "writer_principal": self.writer_principal,
            "command_type": self.command_type,
            "idempotency_key": self.idempotency_key,
            "expected_mapping_digest": self.expected_mapping_digest,
        }


@dataclass(frozen=True, slots=True)
class _Triple:
    source_id: str
    item_key: str
    revision_digest: str

    def as_dict(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "item_key": self.item_key,
            "revision_digest": self.revision_digest,
        }


@dataclass(frozen=True, slots=True)
class BacklogReconciliationReceipt:
    mode: Literal["dry-run", "live"]
    old_identity_count: int
    new_effective_revision_count: int
    mapping_digest: str
    unresolved_collisions: tuple[dict[str, object], ...]
    no_loss_proof: dict[str, object]
    first_seen_corrections: tuple[dict[str, object], ...]
    remapped_count: int
    per_source: tuple[dict[str, object], ...]
    attributed_source_version_rules: tuple[dict[str, object], ...]
    retention_window_bounded_inaccuracies: tuple[dict[str, object], ...]
    mutated: bool
    gates: dict[str, str]
    command: dict[str, str] | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "mode": self.mode,
            "old_identity_count": self.old_identity_count,
            "new_effective_revision_count": self.new_effective_revision_count,
            "before_denominator": self.old_identity_count,
            "after_denominator": self.new_effective_revision_count,
            "mapping_digest": self.mapping_digest,
            "unresolved_collisions": list(self.unresolved_collisions),
            "no_loss_proof": self.no_loss_proof,
            "first_seen_corrections": list(self.first_seen_corrections),
            "remapped_count": self.remapped_count,
            "per_source": list(self.per_source),
            "attributed_source_version_rules": list(
                self.attributed_source_version_rules
            ),
            "retention_window_bounded_inaccuracies": list(
                self.retention_window_bounded_inaccuracies
            ),
            "mutated": self.mutated,
            "gates": dict(self.gates),
        }
        if self.command is not None:
            payload["command"] = dict(self.command)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> BacklogReconciliationReceipt:
        command = payload.get("command")
        return cls(
            mode="live" if payload.get("mode") == "live" else "dry-run",
            old_identity_count=int(payload["old_identity_count"]),
            new_effective_revision_count=int(payload["new_effective_revision_count"]),
            mapping_digest=str(payload["mapping_digest"]),
            unresolved_collisions=tuple(payload.get("unresolved_collisions") or ()),
            no_loss_proof=dict(payload.get("no_loss_proof") or {}),
            first_seen_corrections=tuple(payload.get("first_seen_corrections") or ()),
            remapped_count=int(payload.get("remapped_count") or 0),
            per_source=tuple(payload.get("per_source") or ()),
            attributed_source_version_rules=tuple(
                payload.get("attributed_source_version_rules") or ()
            ),
            retention_window_bounded_inaccuracies=tuple(
                payload.get("retention_window_bounded_inaccuracies") or ()
            ),
            mutated=bool(payload.get("mutated")),
            gates=dict(payload.get("gates") or {}),
            command=dict(command) if isinstance(command, Mapping) else None,
        )


def _now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    return _as_utc(value).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_utc(text: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_utc(parsed)


def parse_evaluated_at(text: str) -> datetime:
    parsed = _parse_utc(text)
    if parsed is None:
        raise BacklogReconciliationError(f"invalid evaluated-at timestamp: {text}")
    return parsed


def _independent_revision_digest(
    *, headline: str, body: str, canonical_url: str
) -> str:
    """Hash retained item expression without the live identity module."""

    return digest_canonical(
        {"headline": headline, "body": body, "canonical_url": canonical_url}
    )


def _resolved(path: str) -> Path:
    return Path(path).expanduser().resolve()


def canonical_store_paths() -> tuple[Path, Path]:
    return (
        CANONICAL_PROVING_STORE.expanduser().resolve(),
        CANONICAL_UNPUBLISHED_STORE.expanduser().resolve(),
    )


def is_canonical_store(path: str) -> bool:
    resolved = _resolved(path)
    proving, unpublished = canonical_store_paths()
    return resolved in {proving, unpublished}


def refuse_canonical_write(path: str, *, allow_canonical_mutation: bool) -> None:
    if allow_canonical_mutation:
        return
    if is_canonical_store(path):
        raise CanonicalStoreGuardError(
            f"refusing writable open of canonical store {path}; "
            "copy the store into the worktree, or pass --mutate-canonical "
            "only after the live daemon is stopped"
        )


class _ScratchReadOnlyConnection(sqlite3.Connection):
    """Read a copied WAL snapshot without touching source sidecars."""

    scratch: tempfile.TemporaryDirectory[str] | None = None

    def close(self) -> None:
        super().close()
        if self.scratch is not None:
            self.scratch.cleanup()
            self.scratch = None


def _readonly_connect(path: str) -> sqlite3.Connection:
    resolved = _resolved(path)
    if not resolved.is_file():
        raise BacklogReconciliationError(f"store does not exist: {path}")
    # SQLite mutates SHM even in mode=ro. Read a complete WAL snapshot from a
    # scratch copy; WAL-free stores can be opened immutable in place.
    wal_exists, shm_exists = (
        Path(str(resolved) + suffix).exists() for suffix in ("-wal", "-shm")
    )
    if wal_exists != shm_exists:
        raise BacklogReconciliationError(
            f"store has an incomplete WAL sidecar pair: {path}"
        )
    if wal_exists:
        source_paths = tuple(
            Path(str(resolved) + suffix) for suffix in ("", "-wal", "-shm")
        )
        before = tuple(
            (
                item.stat().st_dev,
                item.stat().st_ino,
                item.stat().st_size,
                item.stat().st_mtime_ns,
            )
            for item in source_paths
        )
        scratch = tempfile.TemporaryDirectory(prefix="newsroom-readonly-")
        copied = Path(scratch.name) / resolved.name
        try:
            shutil.copy2(resolved, copied)
            shutil.copy2(Path(str(resolved) + "-wal"), Path(str(copied) + "-wal"))
            after = tuple(
                (
                    item.stat().st_dev,
                    item.stat().st_ino,
                    item.stat().st_size,
                    item.stat().st_mtime_ns,
                )
                for item in source_paths
            )
            if after != before:
                raise BacklogReconciliationError(
                    f"store changed while taking a read-only snapshot: {path}"
                )
            connection = sqlite3.connect(
                f"{copied.as_uri()}?mode=ro",
                uri=True,
                factory=_ScratchReadOnlyConnection,
            )
            connection.scratch = scratch
        except Exception:
            scratch.cleanup()
            raise
    else:
        connection = sqlite3.connect(
            f"{resolved.as_uri()}?mode=ro&immutable=1", uri=True
        )
    try:
        apply_control_plane_sqlite_profile(connection, query_only=True, wal=False)
    except Exception:
        connection.close()
        raise
    return connection


def _schema_table(name: str, *, schema: str) -> str:
    return name if schema == "main" else f"{schema}.{name}"


def _table_exists(
    connection: sqlite3.Connection, name: str, *, schema: str = "main"
) -> bool:
    catalog = "sqlite_master" if schema == "main" else f"{schema}.sqlite_master"
    row = connection.execute(
        f"SELECT 1 FROM {catalog} WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _ids(connection: sqlite3.Connection, sql: str) -> frozenset[str]:
    return frozenset(str(row[0]) for row in connection.execute(sql))


def _table_columns(
    connection: sqlite3.Connection, name: str, *, schema: str = "main"
) -> frozenset[str]:
    pragma = (
        f"table_info({name})" if schema == "main" else f"{schema}.table_info({name})"
    )
    return frozenset(str(row[1]) for row in connection.execute(f"PRAGMA {pragma}"))


def _census_proving(
    connection: sqlite3.Connection, *, schema: str = "main"
) -> dict[str, frozenset[str]]:
    census: dict[str, frozenset[str]] = {}
    observations = _schema_table("proving_observations", schema=schema)
    runs = _schema_table("proving_runs", schema=schema)
    gates = _schema_table("proving_gates", schema=schema)
    packets = _schema_table("proving_rights_packets", schema=schema)
    pulls = _schema_table("proving_effective_pull_first_seen", schema=schema)
    if _table_exists(connection, "proving_observations", schema=schema):
        census["proving_observations"] = _ids(
            connection,
            f"""
            SELECT run_id || '|' || source_id || '|' || fetched_at || '|' || body_digest
            FROM {observations}
            """,
        )
    else:
        census["proving_observations"] = frozenset()
    if _table_exists(connection, "proving_runs", schema=schema):
        census["proving_runs"] = _ids(connection, f"SELECT run_id FROM {runs}")
    if _table_exists(connection, "proving_gates", schema=schema):
        census["proving_gates"] = _ids(
            connection, f"SELECT run_id || '|' || gate_id FROM {gates}"
        )
    if _table_exists(connection, "proving_rights_packets", schema=schema):
        census["proving_rights_packets"] = _ids(
            connection,
            f"SELECT run_id || '|' || gate_id FROM {packets}",
        )
    if _table_exists(connection, "proving_effective_pull_first_seen", schema=schema):
        census["proving_effective_pull_first_seen"] = _ids(
            connection,
            "SELECT source_id || '|' || item_key || '|' || revision_digest || '|' "
            "|| published_at || '|' || updated_at "
            f"FROM {pulls}",
        )
    return census


def _census_unpublished(
    connection: sqlite3.Connection, *, schema: str = "main"
) -> dict[str, frozenset[str]]:
    census: dict[str, frozenset[str]] = {}
    landed_columns = _table_columns(
        connection, "unpublished_effective_revision_landed", schema=schema
    )
    landed_key = "source_id || '|' || item_key || '|' || revision_digest"
    if {"published_at", "updated_at"}.issubset(landed_columns):
        landed_key += (
            " || CASE WHEN published_at='' AND updated_at='' THEN '' "
            "ELSE '|' || published_at || '|' || updated_at END"
        )
    queries = (
        ("ledger", f"SELECT digest FROM {_schema_table('ledger', schema=schema)}"),
        (
            "unpublished_graphiti_attempt_receipts",
            "SELECT ingest_id || ':' || attempt_number "
            f"FROM {_schema_table('unpublished_graphiti_attempt_receipts', schema=schema)}",
        ),
        (
            "unpublished_graphiti_ingest",
            "SELECT ingest_id FROM "
            f"{_schema_table('unpublished_graphiti_ingest', schema=schema)}",
        ),
        (
            "unpublished_graphiti_receipts",
            "SELECT ingest_id FROM "
            f"{_schema_table('unpublished_graphiti_receipts', schema=schema)}",
        ),
        (
            "unpublished_graphiti_authority_records",
            "SELECT record_id FROM "
            f"{_schema_table('unpublished_graphiti_authority_records', schema=schema)}",
        ),
        (
            "unpublished_graphiti_spend",
            "SELECT spend_id FROM "
            f"{_schema_table('unpublished_graphiti_spend', schema=schema)}",
        ),
        (
            "unpublished_graphiti_failures",
            "SELECT ingest_id FROM "
            f"{_schema_table('unpublished_graphiti_failures', schema=schema)}",
        ),
        (
            "unpublished_surface_payloads",
            "SELECT payload_id FROM "
            f"{_schema_table('unpublished_surface_payloads', schema=schema)}",
        ),
        (
            "unpublished_effective_revision_landed",
            f"SELECT {landed_key} "
            f"FROM {_schema_table('unpublished_effective_revision_landed', schema=schema)}",
        ),
    )
    for name, sql in queries:
        census[name] = (
            _ids(connection, sql)
            if _table_exists(connection, name, schema=schema)
            else frozenset()
        )
    return census


def _census_missing(
    before: dict[str, frozenset[str]], after: dict[str, frozenset[str]]
) -> dict[str, list[str]]:
    missing: dict[str, list[str]] = {}
    for name, ids in before.items():
        lost = sorted(ids - after.get(name, frozenset()))
        if lost:
            missing[name] = lost
    return missing


def _flatten_census(census: dict[str, frozenset[str]]) -> int:
    return sum(len(ids) for ids in census.values())


def _usable_observation_rows(
    connection: sqlite3.Connection,
    *,
    schema: str = "main",
) -> tuple[tuple[str, str, str, bytes], ...]:
    if not _table_exists(connection, "proving_observations", schema=schema):
        return ()
    observations = _schema_table("proving_observations", schema=schema)
    rows = connection.execute(
        f"""
        SELECT source_id, fetched_at, url, body
        FROM {observations}
        WHERE status_code=200 AND body IS NOT NULL AND error IS NULL
        ORDER BY fetched_at ASC, source_id, url
        """
    ).fetchall()
    from newsroom.increment9.proving import assess_content

    return tuple(
        (str(source_id), str(fetched_at), str(url), bytes(body))
        for source_id, fetched_at, url, body in rows
        if body and assess_content(str(url), bytes(body)).usable
    )


@dataclass(frozen=True, slots=True)
class _Plan:
    expected_keys: tuple[_Triple, ...]
    earliest: dict[_Triple, str]
    pull_earliest: dict[tuple[_Triple, str, str], str]
    old_identity_count: int
    new_effective_revision_count: int
    mapping_digest: str
    poll_mappings: tuple[dict[str, str], ...]
    first_seen_corrections: tuple[dict[str, object], ...]
    missing_first_seen: tuple[tuple[_Triple, str], ...]
    per_source: tuple[dict[str, object], ...]
    attributed_source_version_rules: tuple[dict[str, object], ...]
    retention_window_bounded_inaccuracies: tuple[dict[str, object], ...]
    unresolved_collisions: tuple[dict[str, object], ...]
    orphan_first_seen: tuple[_Triple, ...]
    digest_mismatches: tuple[_Triple, ...]
    retained_effect_maps: tuple[dict[str, object], ...]


def _amplification(old_n: int, new_n: int) -> str:
    if new_n <= 0:
        return "n/a" if old_n == 0 else "unbounded"
    return f"{old_n / new_n:.2f}x"


def _build_plan(
    proving: sqlite3.Connection,
    unpublished: sqlite3.Connection | None,
    *,
    evaluated_at: datetime,
    proving_schema: str = "main",
    unpublished_schema: str = "main",
) -> _Plan:
    earliest: dict[_Triple, str] = {}
    old_keys: set[tuple[str, ...]] = set()
    version_markers: dict[_Triple, set[tuple[str | None, str | None]]] = {}
    poll_mappings: list[dict[str, str]] = []
    old_by_source: dict[str, set[tuple[str, ...]]] = {}
    new_by_source: dict[str, set[tuple[_Triple, str, str]]] = {}
    pulls: set[tuple[_Triple, str, str]] = set()
    pull_earliest: dict[tuple[_Triple, str, str], str] = {}
    pull_ingest_ids: dict[tuple[_Triple, str, str], tuple[str, ...]] = {}

    for source_id, fetched_at, url, body in _usable_observation_rows(
        proving, schema=proving_schema
    ):
        for item in parse_observation(source_id=source_id, url=url, body=body):
            digest = _independent_revision_digest(
                headline=item.headline,
                body=item.retained_corpus_body,
                canonical_url=item.canonical_url,
            )
            triple = _Triple(source_id, item.item_key, digest)
            previous = earliest.get(triple)
            if previous is None or fetched_at < previous:
                earliest[triple] = fetched_at
            version_markers.setdefault(triple, set()).add(
                (item.published_at, item.updated_at)
            )
            undated = item.published_at is None and item.updated_at is None
            if undated:
                old_key: tuple[str, ...] = (
                    source_id,
                    item.item_key,
                    digest,
                    fetched_at,
                )
                poll_mappings.append(
                    {
                        "source_id": source_id,
                        "item_key": item.item_key,
                        "revision_digest": digest,
                        "poll_observed_at": fetched_at,
                        "new_first_observed_at": "",
                    }
                )
            else:
                old_key = (
                    source_id,
                    item.item_key,
                    digest,
                    item.published_at or "",
                    item.updated_at or "",
                )
            old_keys.add(old_key)
            old_by_source.setdefault(source_id, set()).add(old_key)
            pull = (triple, item.published_at or "", item.updated_at or "")
            pulls.add(pull)
            if pull not in pull_ingest_ids:
                pull_ingest_ids[pull] = effective_pull_ingest_ids(
                    source_id=source_id,
                    item_key=item.item_key,
                    headline=item.headline,
                    body=item.retained_corpus_body,
                    canonical_url=item.canonical_url,
                    published_at=item.published_at,
                    updated_at=item.updated_at,
                )
            pull_first = pull_earliest.get(pull)
            if pull_first is None or fetched_at < pull_first:
                pull_earliest[pull] = fetched_at
            new_by_source.setdefault(source_id, set()).add(pull)

    expected_keys = tuple(
        sorted(
            earliest,
            key=lambda item: (item.source_id, item.item_key, item.revision_digest),
        )
    )
    for mapping in poll_mappings:
        triple = _Triple(
            mapping["source_id"], mapping["item_key"], mapping["revision_digest"]
        )
        mapping["new_first_observed_at"] = earliest[triple]
    poll_mappings.sort(
        key=lambda item: (
            item["source_id"],
            item["item_key"],
            item["revision_digest"],
            item["poll_observed_at"],
        )
    )

    cutoff = _utc_text(_as_utc(evaluated_at) - RAW_HTTP_RETENTION)
    older_runs = False
    if _table_exists(proving, "proving_runs", schema=proving_schema):
        proving_runs = _schema_table("proving_runs", schema=proving_schema)
        older_runs = (
            proving.execute(
                f"SELECT 1 FROM {proving_runs} WHERE started_at<? LIMIT 1",
                (cutoff,),
            ).fetchone()
            is not None
        )

    first_seen: dict[_Triple, str] = {}
    if _table_exists(proving, "proving_revision_first_seen", schema=proving_schema):
        first_seen_table = _schema_table(
            "proving_revision_first_seen", schema=proving_schema
        )
        for source_id, item_key, revision_digest, first_seen_at in proving.execute(
            f"""
            SELECT source_id, item_key, revision_digest, first_seen_at
            FROM {first_seen_table}
            """
        ):
            first_seen[_Triple(str(source_id), str(item_key), str(revision_digest))] = (
                str(first_seen_at)
            )

    retained_earliest = dict(earliest)
    # Retention can reveal an earlier observation, but it can never move a
    # durable first-seen instant later.
    for triple, recorded_at in first_seen.items():
        if triple in earliest and recorded_at < earliest[triple]:
            earliest[triple] = recorded_at
    for mapping in poll_mappings:
        triple = _Triple(
            mapping["source_id"], mapping["item_key"], mapping["revision_digest"]
        )
        mapping["new_first_observed_at"] = earliest[triple]

    pull_first_seen: dict[tuple[_Triple, str, str], str] = {}
    if _table_exists(
        proving, "proving_effective_pull_first_seen", schema=proving_schema
    ):
        pull_table = _schema_table(
            "proving_effective_pull_first_seen", schema=proving_schema
        )
        rows = proving.execute(
            f"""SELECT source_id, item_key, revision_digest, published_at,
                       updated_at, first_seen_at
                FROM {pull_table}"""
        )
        for source_id, item_key, revision_digest, published, updated, seen in rows:
            pull_first_seen[
                (
                    _Triple(str(source_id), str(item_key), str(revision_digest)),
                    str(published or ""),
                    str(updated or ""),
                )
            ] = str(seen)
    for pull in pulls:
        retained_at = pull_earliest[pull]
        durable_at = pull_first_seen.get(pull)
        if durable_at is None and len(version_markers[pull[0]]) == 1:
            durable_at = first_seen.get(pull[0])
        if durable_at is not None and durable_at < retained_at:
            pull_earliest[pull] = durable_at

    attributed: list[dict[str, object]] = []
    for triple, markers in sorted(
        version_markers.items(),
        key=lambda item: (item[0].source_id, item[0].item_key, item[0].revision_digest),
    ):
        if len(markers) <= 1:
            continue
        attributed.append(
            {
                "rule": SOURCE_SUPPLIED_VERSION_MARKER,
                "source_id": triple.source_id,
                "item_key": triple.item_key,
                "revision_digest": triple.revision_digest,
                "marker_count": len(markers),
                "markers": [
                    {"published_at": published, "updated_at": updated}
                    for published, updated in sorted(
                        markers, key=lambda item: (item[0] or "", item[1] or "")
                    )
                ],
            }
        )

    orphan_keys = tuple(
        sorted(
            (key for key in first_seen if key not in earliest),
            key=lambda item: (item.source_id, item.item_key, item.revision_digest),
        )
    )
    expected_items = {(item.source_id, item.item_key) for item in expected_keys}
    digest_mismatches: list[_Triple] = []
    kept_orphans: list[_Triple] = []
    for triple in orphan_keys:
        if (triple.source_id, triple.item_key) in expected_items:
            digest_mismatches.append(triple)
            continue
        kept_orphans.append(triple)
        attributed.append(
            {
                "rule": FIRST_SEEN_WITHOUT_RETAINED_OBSERVATION,
                "source_id": triple.source_id,
                "item_key": triple.item_key,
                "revision_digest": triple.revision_digest,
                "first_seen_at": first_seen[triple],
            }
        )
    orphan_keys = tuple(kept_orphans)

    corrections: list[dict[str, object]] = []
    bounded: list[dict[str, object]] = []
    missing: list[tuple[_Triple, str]] = []
    for triple in expected_keys:
        new_at = earliest[triple]
        window_bound = older_runs and retained_earliest[triple] >= cutoff
        if window_bound:
            bounded.append(
                {
                    "rule": RETENTION_WINDOW_BOUNDED_INACCURACY,
                    "source_id": triple.source_id,
                    "item_key": triple.item_key,
                    "revision_digest": triple.revision_digest,
                    "earliest_retained_at": retained_earliest[triple],
                    "retention_cutoff": cutoff,
                    "not_true_first_landing": True,
                }
            )
        recorded = first_seen.get(triple)
        if recorded is None:
            missing.append((triple, new_at))
            corrections.append(
                {
                    "source_id": triple.source_id,
                    "item_key": triple.item_key,
                    "revision_digest": triple.revision_digest,
                    "old_first_seen_at": None,
                    "new_first_seen_at": new_at,
                    "identity_remap": {
                        "old": None,
                        "new": {**triple.as_dict(), "first_observed_at": new_at},
                    },
                    "retention_window_bounded_inaccuracy": window_bound,
                }
            )
            continue
        if recorded <= new_at:
            continue
        corrections.append(
            {
                "source_id": triple.source_id,
                "item_key": triple.item_key,
                "revision_digest": triple.revision_digest,
                "old_first_seen_at": recorded,
                "new_first_seen_at": new_at,
                "identity_remap": {
                    "old": {**triple.as_dict(), "first_observed_at": recorded},
                    "new": {**triple.as_dict(), "first_observed_at": new_at},
                },
                "retention_window_bounded_inaccuracy": window_bound,
            }
        )

    correction_inputs = {
        (
            str(item["source_id"]),
            str(item["item_key"]),
            str(item["revision_digest"]),
            str(item["old_first_seen_at"] or ""),
            str(item["new_first_seen_at"]),
        ): {
            key: item[key]
            for key in (
                "source_id",
                "item_key",
                "revision_digest",
                "old_first_seen_at",
                "new_first_seen_at",
                "retention_window_bounded_inaccuracy",
            )
        }
        for item in corrections
    }
    if unpublished is not None and _table_exists(
        unpublished, "unpublished_effective_revision_remap", schema=unpublished_schema
    ):
        table = _schema_table(
            "unpublished_effective_revision_remap", schema=unpublished_schema
        )
        for row in unpublished.execute(
            f"""
            SELECT source_id, item_key, revision_digest,
                   old_observed_fallback_at, new_first_observed_at,
                   retention_window_bounded_inaccuracy
            FROM {table}
            WHERE kind='FIRST_SEEN_CORRECTION'
            """
        ):
            source_id, item_key, revision_digest = map(str, row[:3])
            old_at = None if row[3] is None else str(row[3])
            new_at = str(row[4])
            correction_inputs[
                (source_id, item_key, revision_digest, old_at or "", new_at)
            ] = {
                "source_id": source_id,
                "item_key": item_key,
                "revision_digest": revision_digest,
                "old_first_seen_at": old_at,
                "new_first_seen_at": new_at,
                "retention_window_bounded_inaccuracy": bool(row[5]),
            }

    expected_n = len(pulls)
    per_source = []
    for source_id in sorted({*old_by_source, *new_by_source}):
        old_n = len(old_by_source.get(source_id, set()))
        new_n = len(new_by_source.get(source_id, set()))
        per_source.append(
            {
                "source_id": source_id,
                "old_identities": old_n,
                "stable_revisions": new_n,
                "amplification_before": _amplification(old_n, new_n),
                "amplification_after": "1.00x"
                if new_n
                else _amplification(old_n, new_n),
            }
        )

    retained_effect_maps, collisions = (
        _resolve_retained_lineage(
            unpublished,
            pulls,
            pull_earliest,
            pull_ingest_ids,
            schema=unpublished_schema,
        )
        if unpublished
        else ((), ())
    )
    mapping_digest = digest_canonical(
        {
            "effective_revisions": [
                {**triple.as_dict(), "first_observed_at": earliest[triple]}
                for triple in expected_keys
            ],
            "effective_pulls": [
                {
                    **triple.as_dict(),
                    "published_at": published,
                    "updated_at": updated,
                    "first_observed_at": pull_earliest[(triple, published, updated)],
                }
                for triple, published, updated in sorted(
                    pulls,
                    key=lambda item: (
                        item[0].source_id,
                        item[0].item_key,
                        item[0].revision_digest,
                        item[1],
                        item[2],
                    ),
                )
            ],
            "amplified_poll_mappings": poll_mappings,
            "first_seen_corrections": [
                correction_inputs[key] for key in sorted(correction_inputs)
            ],
            "orphan_first_seen": [
                {**triple.as_dict(), "first_seen_at": first_seen[triple]}
                for triple in orphan_keys
            ],
            "retained_effect_maps": list(retained_effect_maps),
            "unresolved_collisions": list(collisions),
        }
    )
    return _Plan(
        expected_keys=expected_keys,
        earliest=earliest,
        pull_earliest=pull_earliest,
        old_identity_count=len(old_keys),
        new_effective_revision_count=expected_n,
        mapping_digest=mapping_digest,
        poll_mappings=tuple(poll_mappings),
        first_seen_corrections=tuple(corrections),
        missing_first_seen=tuple(missing),
        per_source=tuple(per_source),
        attributed_source_version_rules=tuple(attributed),
        retention_window_bounded_inaccuracies=tuple(bounded),
        unresolved_collisions=collisions,
        orphan_first_seen=orphan_keys,
        digest_mismatches=tuple(digest_mismatches),
        retained_effect_maps=retained_effect_maps,
    )


def _retained_lineage_by_item(
    unpublished: sqlite3.Connection,
    *,
    schema: str = "main",
) -> dict[tuple[str, str], dict[str, tuple[str, str, str, int | None] | None]]:
    by_item: dict[
        tuple[str, str], dict[str, tuple[str, str, str, int | None] | None]
    ] = {}
    for table_name in (
        "unpublished_graphiti_ingest",
        "unpublished_graphiti_failures",
    ):
        if not _table_exists(unpublished, table_name, schema=schema):
            continue
        table = _schema_table(table_name, schema=schema)
        for ingest_id, source_id, item_key in unpublished.execute(
            f"SELECT ingest_id, source_id, item_key FROM {table}"
        ):
            by_item.setdefault((str(source_id), str(item_key)), {})[str(ingest_id)] = (
                None
            )
    authority_revisions: dict[str, tuple[str, str, str, str, str]] = {}
    if _table_exists(
        unpublished, "unpublished_graphiti_authority_records", schema=schema
    ):
        table = _schema_table("unpublished_graphiti_authority_records", schema=schema)
        for record_id, record_json in unpublished.execute(
            f"SELECT record_id, record_json FROM {table} "
            "WHERE record_type='SOURCE_REVISION'"
        ):
            try:
                record = json.loads(str(record_json))
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(record, dict):
                continue
            authority_revisions[str(record_id)] = (
                str(record.get("source_id") or ""),
                str(record.get("item_key") or ""),
                str(record.get("revision_digest") or ""),
                str(record.get("published_at") or ""),
                str(record.get("updated_at") or ""),
            )
    for table_name in (
        "unpublished_graphiti_attempt_receipts",
        "unpublished_graphiti_receipts",
    ):
        if not _table_exists(unpublished, table_name, schema=schema):
            continue
        table = _schema_table(table_name, schema=schema)
        for ingest_id, receipt_json in unpublished.execute(
            f"SELECT ingest_id, receipt_json FROM {table}"
        ):
            try:
                receipt = json.loads(str(receipt_json))
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(receipt, dict):
                continue
            revision = authority_revisions.get(str(receipt.get("revision_id") or ""))
            if revision is not None:
                source_id, item_key, revision_digest, published_at, updated_at = (
                    revision
                )
            else:
                source_id = receipt.get("source_id")
                item_key = receipt.get("item_key")
                revision_digest = str(receipt.get("revision_digest") or "")
                published_at = str(receipt.get("published_at") or "")
                updated_at = str(receipt.get("updated_at") or "")
            if not isinstance(source_id, str) or not isinstance(item_key, str):
                continue
            raw_ordinal = receipt.get("chunk_ordinal")
            chunk_ordinal = (
                raw_ordinal if type(raw_ordinal) is int and raw_ordinal > 0 else None
            )
            by_item.setdefault((source_id, item_key), {})[str(ingest_id)] = (
                revision_digest,
                published_at,
                updated_at,
                chunk_ordinal,
            )
    return by_item


def _landed_ingest_ids(
    unpublished: sqlite3.Connection, *, schema: str = "main"
) -> dict[tuple[str, str, str, str, str], tuple[str, ...]]:
    if not _table_exists(
        unpublished, "unpublished_effective_revision_landed", schema=schema
    ):
        return {}
    columns = _table_columns(
        unpublished, "unpublished_effective_revision_landed", schema=schema
    )
    if not {"published_at", "updated_at", "ingest_ids_json"}.issubset(columns):
        return {}
    table = _schema_table("unpublished_effective_revision_landed", schema=schema)
    result: dict[tuple[str, str, str, str, str], tuple[str, ...]] = {}
    for source_id, item_key, digest, published, updated, raw_ids in unpublished.execute(
        f"SELECT source_id, item_key, revision_digest, published_at, updated_at, "
        f"ingest_ids_json FROM {table}"
    ):
        try:
            parsed = json.loads(str(raw_ids))
        except (json.JSONDecodeError, TypeError):
            continue
        if (
            not isinstance(parsed, list)
            or not parsed
            or not all(isinstance(item, str) for item in parsed)
        ):
            continue
        result[
            (str(source_id), str(item_key), str(digest), str(published), str(updated))
        ] = tuple(parsed)
    return result


def _pulls_by_item(
    pulls: set[tuple[_Triple, str, str]],
) -> dict[tuple[str, str], list[tuple[_Triple, str, str]]]:
    by_item: dict[tuple[str, str], list[tuple[_Triple, str, str]]] = {}
    for pull in pulls:
        triple, _published, _updated = pull
        by_item.setdefault((triple.source_id, triple.item_key), []).append(pull)
    return by_item


def _resolve_retained_lineage(
    unpublished: sqlite3.Connection,
    pulls: set[tuple[_Triple, str, str]],
    pull_earliest: dict[tuple[_Triple, str, str], str],
    pull_ingest_ids: dict[tuple[_Triple, str, str], tuple[str, ...]],
    *,
    schema: str = "main",
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    lineage_by_item = _retained_lineage_by_item(unpublished, schema=schema)
    landed_ids = _landed_ingest_ids(unpublished, schema=schema)
    pulls_by_item = _pulls_by_item(pulls)
    mapped: list[dict[str, object]] = []
    collisions: list[dict[str, object]] = []
    for (source_id, item_key), lineage in sorted(lineage_by_item.items()):
        unresolved: list[str] = []
        for ingest_id, markers in sorted(lineage.items()):
            candidates = pulls_by_item.get((source_id, item_key), [])
            if markers is not None:
                revision_digest, published_at, updated_at, chunk_ordinal = markers
                candidates = [
                    pull
                    for pull in candidates
                    if (
                        not revision_digest
                        or pull[0].revision_digest == revision_digest
                    )
                    and pull[1:] == (published_at, updated_at)
                ]
            if len(candidates) != 1:
                unresolved.append(ingest_id)
                continue
            triple, published, updated = candidates[0]
            new_ids = landed_ids.get(
                (
                    triple.source_id,
                    triple.item_key,
                    triple.revision_digest,
                    published,
                    updated,
                ),
                pull_ingest_ids[candidates[0]],
            )
            if markers is None:
                chunk_ordinal = None
            new_ingest_id = (
                new_ids[chunk_ordinal - 1]
                if chunk_ordinal is not None and chunk_ordinal <= len(new_ids)
                else new_ids[0]
                if len(new_ids) == 1
                else None
            )
            mapped.append(
                {
                    "source_id": triple.source_id,
                    "item_key": triple.item_key,
                    "revision_digest": triple.revision_digest,
                    "published_at": published,
                    "updated_at": updated,
                    "old_ingest_id": ingest_id,
                    "new_ingest_id": new_ingest_id,
                    "new_first_observed_at": pull_earliest[candidates[0]],
                }
            )
            if new_ingest_id is None:
                unresolved.append(ingest_id)
        if unresolved:
            collisions.append(
                {
                    "kind": GRAPH_EFFECT_AMBIGUOUS_COVERAGE,
                    "source_id": source_id,
                    "item_key": item_key,
                    "ingest_ids": unresolved,
                    "merged": False,
                }
            )
    mapped.sort(
        key=lambda item: (
            item["source_id"],
            item["item_key"],
            item["revision_digest"],
            item["published_at"],
            item["updated_at"],
            item["old_ingest_id"],
        )
    )
    return tuple(mapped), tuple(collisions)


def _assert_g1(plan: _Plan) -> None:
    expected = set(plan.expected_keys)
    if plan.new_effective_revision_count < len(expected):
        raise BacklogReconciliationError(
            "G1: new effective-revision count is below the independent content dedupe"
        )
    if plan.digest_mismatches:
        sample = plan.digest_mismatches[0]
        raise BacklogReconciliationError(
            "G1: unattributed first-seen digest differs from retained evidence "
            f"for {sample.source_id}:{sample.item_key}"
        )
    attributed_orphans = {
        _Triple(
            str(rule["source_id"]), str(rule["item_key"]), str(rule["revision_digest"])
        )
        for rule in plan.attributed_source_version_rules
        if rule.get("rule") == FIRST_SEEN_WITHOUT_RETAINED_OBSERVATION
    }
    unattributed_orphans = [
        triple for triple in plan.orphan_first_seen if triple not in attributed_orphans
    ]
    if unattributed_orphans:
        raise BacklogReconciliationError(
            "G1: unattributed first-seen rows are not in retained evidence"
        )
    for row in plan.per_source:
        new_n = int(row["stable_revisions"])
        if new_n and row["amplification_after"] != "1.00x":
            raise BacklogReconciliationError(
                f"G1: source {row['source_id']} still amplified after remap "
                f"({row['amplification_after']})"
            )
        old_n = int(row["old_identities"])
        if new_n and old_n < new_n:
            raise BacklogReconciliationError(
                f"G1: source {row['source_id']} lost identities under remap"
            )


def _assert_g2(plan: _Plan, dry_run_receipt: Mapping[str, object]) -> None:
    before = dry_run_receipt.get(
        "before_denominator", dry_run_receipt.get("old_identity_count")
    )
    after = dry_run_receipt.get(
        "after_denominator", dry_run_receipt.get("new_effective_revision_count")
    )
    digest = dry_run_receipt.get("mapping_digest")
    if before != plan.old_identity_count or after != plan.new_effective_revision_count:
        raise BacklogReconciliationError(
            "G2: live denominator differs from the dry-run receipt"
        )
    if digest != plan.mapping_digest:
        raise BacklogReconciliationError(
            "G2: live mapping digest differs from the dry-run receipt"
        )


def _assert_g5(plan: _Plan) -> None:
    for collision in plan.unresolved_collisions:
        if collision.get("merged") is True:
            raise BacklogReconciliationError(
                "G5: unresolved collision was silently merged"
            )
        if not collision.get("kind") or not collision.get("ingest_ids"):
            raise BacklogReconciliationError(
                "G5: collision is missing an explicit listing"
            )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _integrity_ok(connection: sqlite3.Connection) -> bool:
    row = connection.execute("PRAGMA integrity_check").fetchone()
    return row is not None and str(row[0]) == "ok"


def _backup_store(source: Path, destination: Path) -> dict[str, str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(destination.parent, BACKUP_DIR_MODE)
    source_conn = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
    apply_control_plane_sqlite_profile(source_conn, query_only=True, wal=False)
    dest_conn = sqlite3.connect(destination)
    apply_control_plane_sqlite_profile(dest_conn, wal=False)
    try:
        if not _integrity_ok(source_conn):
            raise BacklogReconciliationError(f"source integrity check failed: {source}")
        source_conn.backup(dest_conn)
        dest_conn.commit()
        if not _integrity_ok(dest_conn):
            raise BacklogReconciliationError(
                f"backup integrity check failed: {destination}"
            )
    finally:
        dest_conn.close()
        source_conn.close()
    os.chmod(destination, BACKUP_FILE_MODE)
    digest = _file_sha256(destination)
    sidecar = Path(str(destination) + ".sha256")
    sidecar.write_text(digest + "\n", encoding="utf-8")
    os.chmod(sidecar, BACKUP_FILE_MODE)
    return {"path": str(destination), "digest": digest, "integrity": "ok"}


def _ensure_first_seen_schema(
    connection: sqlite3.Connection, *, schema: str = "main"
) -> None:
    ensure_proving_revision_schema(connection, schema=schema)


def _apply_proving(
    connection: sqlite3.Connection, plan: _Plan, *, schema: str = "main"
) -> int:
    _ensure_first_seen_schema(connection, schema=schema)
    table = _schema_table("proving_revision_first_seen", schema=schema)
    before = connection.total_changes
    for correction in plan.first_seen_corrections:
        triple = (
            str(correction["source_id"]),
            str(correction["item_key"]),
            str(correction["revision_digest"]),
        )
        new_at = str(correction["new_first_seen_at"])
        if correction["old_first_seen_at"] is None:
            connection.execute(
                f"""
                INSERT OR IGNORE INTO {table}(
                    source_id, item_key, revision_digest, first_seen_at
                ) VALUES(?,?,?,?)
                """,
                (*triple, new_at),
            )
        else:
            connection.execute(
                f"""
                UPDATE {table}
                SET first_seen_at=?
                WHERE source_id=? AND item_key=? AND revision_digest=?
                  AND first_seen_at=?
                """,
                (new_at, *triple, str(correction["old_first_seen_at"])),
            )
    pull_table = _schema_table("proving_effective_pull_first_seen", schema=schema)
    for (triple, published_at, updated_at), first_seen_at in plan.pull_earliest.items():
        connection.execute(
            f"""
            INSERT OR IGNORE INTO {pull_table}(
                source_id, item_key, revision_digest, published_at, updated_at,
                first_seen_at
            ) VALUES(?,?,?,?,?,?)
            """,
            (
                triple.source_id,
                triple.item_key,
                triple.revision_digest,
                published_at,
                updated_at,
                first_seen_at,
            ),
        )
    return connection.total_changes - before


def _apply_remap_rows(
    connection: sqlite3.Connection, plan: _Plan, *, schema: str = "main"
) -> int:
    ensure_reconciliation_schema(connection, schema=schema)
    table = _schema_table("unpublished_effective_revision_remap", schema=schema)
    at = _now()
    rows: list[tuple[object, ...]] = []
    for mapping in plan.poll_mappings:
        payload = {"kind": "AMPLIFIED_POLL_REMAP", **mapping}
        rows.append(
            (
                digest_canonical(payload),
                mapping["source_id"],
                mapping["item_key"],
                mapping["revision_digest"],
                "",
                "",
                mapping["poll_observed_at"],
                mapping["new_first_observed_at"],
                "AMPLIFIED_POLL_REMAP",
                0,
                None,
                None,
                at,
            )
        )
    for correction in plan.first_seen_corrections:
        window = 1 if correction.get("retention_window_bounded_inaccuracy") else 0
        payload = {
            "kind": "FIRST_SEEN_CORRECTION",
            "source_id": correction["source_id"],
            "item_key": correction["item_key"],
            "revision_digest": correction["revision_digest"],
            "old_first_seen_at": correction["old_first_seen_at"],
            "new_first_seen_at": correction["new_first_seen_at"],
        }
        rows.append(
            (
                digest_canonical(payload),
                correction["source_id"],
                correction["item_key"],
                correction["revision_digest"],
                "",
                "",
                correction["old_first_seen_at"],
                correction["new_first_seen_at"],
                "FIRST_SEEN_CORRECTION",
                window,
                None,
                None,
                at,
            )
        )
    for mapping in plan.retained_effect_maps:
        payload = {"kind": RETAINED_LINEAGE_REMAP, **mapping}
        rows.append(
            (
                digest_canonical(payload),
                mapping["source_id"],
                mapping["item_key"],
                mapping["revision_digest"],
                mapping.get("published_at") or "",
                mapping.get("updated_at") or "",
                None,
                mapping["new_first_observed_at"],
                RETAINED_LINEAGE_REMAP,
                0,
                mapping["old_ingest_id"],
                mapping.get("new_ingest_id"),
                at,
            )
        )
    before = connection.total_changes
    connection.executemany(
        f"""
        INSERT OR IGNORE INTO {table}(
            mapping_id, source_id, item_key, revision_digest,
            published_at, updated_at,
            old_observed_fallback_at, new_first_observed_at, kind,
            retention_window_bounded_inaccuracy, old_ingest_id, new_ingest_id, at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    return connection.total_changes - before


def _retain_receipt(
    connection: sqlite3.Connection, receipt: Mapping[str, object]
) -> None:
    ensure_reconciliation_schema(connection)
    at = _now()
    connection.execute(
        """
        INSERT OR IGNORE INTO unpublished_backlog_reconciliation_receipts(
            receipt_digest, at, mode, receipt_json
        ) VALUES(?,?,?,?)
        """,
        (
            digest_canonical(dict(receipt)),
            at,
            "live",
            json.dumps(dict(receipt), ensure_ascii=False, sort_keys=True),
        ),
    )
    append_ledger(connection, RECONCILIATION_KIND, dict(receipt))


def _record_command(
    connection: sqlite3.Connection,
    command: _ReconciliationCommand,
    receipt: BacklogReconciliationReceipt,
) -> None:
    ensure_reconciliation_schema(connection)
    connection.execute(
        """
        INSERT OR REPLACE INTO unpublished_reconciliation_commands(
            idempotency_key, caller_principal, writer_principal,
            command_type, expected_mapping_digest, receipt_json, at
        ) VALUES(?,?,?,?,?,?,?)
        """,
        (
            command.idempotency_key,
            command.caller_principal,
            command.writer_principal,
            command.command_type,
            command.expected_mapping_digest,
            json.dumps(receipt.as_dict(), ensure_ascii=False, sort_keys=True),
            _now(),
        ),
    )


def _write_receipt(path: Path | None, receipt: BacklogReconciliationReceipt) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(receipt.as_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _empty_unpublished_census() -> dict[str, frozenset[str]]:
    return {
        "ledger": frozenset(),
        "unpublished_graphiti_attempt_receipts": frozenset(),
        "unpublished_graphiti_ingest": frozenset(),
        "unpublished_graphiti_receipts": frozenset(),
        "unpublished_graphiti_authority_records": frozenset(),
        "unpublished_graphiti_spend": frozenset(),
        "unpublished_graphiti_failures": frozenset(),
        "unpublished_surface_payloads": frozenset(),
        "unpublished_effective_revision_landed": frozenset(),
    }


def _no_loss_proof(
    *,
    proving_before: dict[str, frozenset[str]],
    unpublished_before: dict[str, frozenset[str]],
    proving_after: dict[str, frozenset[str]] | None = None,
    unpublished_after: dict[str, frozenset[str]] | None = None,
) -> dict[str, object]:
    proving_missing = (
        {} if proving_after is None else _census_missing(proving_before, proving_after)
    )
    unpublished_missing = (
        {}
        if unpublished_after is None
        else _census_missing(unpublished_before, unpublished_after)
    )
    return {
        "proving_record_count": _flatten_census(proving_before),
        "unpublished_record_count": _flatten_census(unpublished_before),
        "proving_missing": proving_missing,
        "unpublished_missing": unpublished_missing,
        "lost": bool(proving_missing or unpublished_missing),
    }


def _receipt_from_plan(
    plan: _Plan,
    *,
    mode: Literal["dry-run", "live"],
    mutated: bool,
    remapped_count: int,
    no_loss_proof: dict[str, object],
    gates: dict[str, str],
    command: dict[str, str] | None = None,
) -> BacklogReconciliationReceipt:
    return BacklogReconciliationReceipt(
        mode=mode,
        old_identity_count=plan.old_identity_count,
        new_effective_revision_count=plan.new_effective_revision_count,
        mapping_digest=plan.mapping_digest,
        unresolved_collisions=plan.unresolved_collisions,
        no_loss_proof=no_loss_proof,
        first_seen_corrections=plan.first_seen_corrections,
        remapped_count=remapped_count,
        per_source=plan.per_source,
        attributed_source_version_rules=plan.attributed_source_version_rules,
        retention_window_bounded_inaccuracies=plan.retention_window_bounded_inaccuracies,
        mutated=mutated,
        gates=gates,
        command=command,
    )


def _assert_command(
    command: _ReconciliationCommand | None,
    plan: _Plan,
    dry_run_receipt: Mapping[str, object],
) -> _ReconciliationCommand:
    if command is None:
        raise ReconciliationCommandError("live mutation requires a service command")
    _assert_command_authority(command)
    if not command.idempotency_key.strip():
        raise ReconciliationCommandError("idempotency key is required")
    if command.expected_mapping_digest != plan.mapping_digest:
        raise ReconciliationCommandError(
            "expected mapping digest does not match the live plan"
        )
    if dry_run_receipt.get("mapping_digest") != command.expected_mapping_digest:
        raise ReconciliationCommandError(
            "expected mapping digest does not match the dry-run receipt"
        )
    return command


def _assert_command_authority(command: _ReconciliationCommand) -> None:
    if command.caller_principal not in ALLOWED_CALLER_PRINCIPALS:
        raise ReconciliationCommandError(
            f"caller principal is not allow-listed: {command.caller_principal}"
        )
    if command.writer_principal != COMMAND_SERVICE_PRINCIPAL:
        raise ReconciliationCommandError(
            f"writer principal is not the command service: {command.writer_principal}"
        )
    if command.command_type not in ALLOWED_COMMAND_TYPES:
        raise ReconciliationCommandError(
            f"command type is not allow-listed: {command.command_type}"
        )


def _load_completed_command(
    unpublished_store: str, command: _ReconciliationCommand
) -> BacklogReconciliationReceipt | None:
    if not Path(unpublished_store).is_file():
        return None
    connection = _readonly_connect(unpublished_store)
    try:
        if not _table_exists(connection, "unpublished_reconciliation_commands"):
            return None
        row = connection.execute(
            """
            SELECT expected_mapping_digest, receipt_json
            FROM unpublished_reconciliation_commands
            WHERE idempotency_key=?
            """,
            (command.idempotency_key,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return None
    if str(row[0]) != command.expected_mapping_digest:
        raise ReconciliationCommandError(
            "idempotency key reused with a different mapping digest"
        )
    payload = json.loads(str(row[1]))
    if not isinstance(payload, dict):
        raise BacklogReconciliationError("stored command receipt is not an object")
    return BacklogReconciliationReceipt.from_dict(payload)


def _write_coordinator(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, BACKUP_DIR_MODE)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            os.fchmod(handle.fileno(), BACKUP_FILE_MODE)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _store_identity(path: Path) -> dict[str, object]:
    resolved = path.expanduser().resolve()
    stat = resolved.stat()
    return {
        "path": str(resolved),
        "device": stat.st_dev,
        "inode": stat.st_ino,
    }


def _assert_coordinator_binding(
    coordinator: Mapping[str, object],
    proving_path: Path,
    unpublished_path: Path,
    proving_backup: Path,
    unpublished_backup: Path,
) -> None:
    expected = {
        "proving_store": _store_identity(proving_path),
        "unpublished_store": _store_identity(unpublished_path),
        "proving_backup": str(proving_backup.resolve()),
        "unpublished_backup": str(unpublished_backup.resolve()),
    }
    for key, value in expected.items():
        if coordinator.get(key) != value:
            raise BacklogReconciliationError(
                f"G3: coordinator is not bound to this store pair ({key})"
            )
    for key, path in (
        ("proving_backup_digest", proving_backup),
        ("unpublished_backup_digest", unpublished_backup),
    ):
        if not path.is_file() or coordinator.get(key) != _file_sha256(path):
            raise BacklogReconciliationError(
                f"G3: coordinator backup binding differs ({key})"
            )


def _read_coordinator(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _set_journal_mode(path: Path, mode: str) -> None:
    connection = sqlite3.connect(str(path))
    try:
        apply_control_plane_sqlite_profile(connection, wal=False)
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute(f"PRAGMA journal_mode={mode}")
        connection.commit()
    finally:
        connection.close()


def _restore_wal_profiles(*paths: Path) -> None:
    failure: Exception | None = None
    for path in paths:
        try:
            _set_journal_mode(path, "WAL")
        except Exception as exc:  # attempt every store before surfacing failure
            failure = failure or exc
    if failure is not None:
        raise failure


def _restore_incomplete_dual_store(
    proving_path: Path,
    unpublished_path: Path,
    backup_dir: Path,
) -> bool:
    coordinator = _read_coordinator(backup_dir / COORDINATOR_NAME)
    if coordinator is None or coordinator.get("status") in {"ABORTED", "COMPLETE"}:
        return False
    proving_backup = backup_dir / "proving_store.sqlite3"
    unpublished_backup = backup_dir / "unpublished_store.sqlite3"
    _assert_coordinator_binding(
        coordinator,
        proving_path,
        unpublished_path,
        proving_backup,
        unpublished_backup,
    )
    if coordinator.get("status") == "COMMITTED":
        _restore_wal_profiles(proving_path, unpublished_path)
        _write_coordinator(
            backup_dir / COORDINATOR_NAME,
            {**coordinator, "status": "COMPLETE"},
        )
        return False
    # One attached SQLite transaction is crash-atomic. STARTED means the
    # transaction did not commit; restoring an older backup here could delete
    # append-only evidence committed by another connection.
    for path in (proving_path, unpublished_path):
        connection = sqlite3.connect(path)
        try:
            if not _integrity_ok(connection):
                raise BacklogReconciliationError(
                    f"G3: incomplete transaction left an invalid store: {path}"
                )
        finally:
            connection.close()
    _restore_wal_profiles(proving_path, unpublished_path)
    _write_coordinator(
        backup_dir / COORDINATOR_NAME,
        {**coordinator, "status": "ABORTED"},
    )
    return False


def _plan_reconciliation(
    proving_store: str,
    unpublished_store: str,
    *,
    evaluated_at: datetime,
) -> tuple[_Plan, dict[str, frozenset[str]], dict[str, frozenset[str]]]:
    unpublished_path = Path(unpublished_store)
    proving = _readonly_connect(proving_store)
    unpublished: sqlite3.Connection | None = None
    try:
        if unpublished_path.is_file():
            unpublished = _readonly_connect(unpublished_store)
        plan = _build_plan(proving, unpublished, evaluated_at=evaluated_at)
        proving_before = _census_proving(proving)
        unpublished_before = (
            _census_unpublished(unpublished)
            if unpublished is not None
            else _empty_unpublished_census()
        )
        _assert_g1(plan)
        _assert_g5(plan)
    finally:
        proving.close()
        if unpublished is not None:
            unpublished.close()
    return plan, proving_before, unpublished_before


def reconcile_effective_revision_backlog(
    *,
    proving_store: str,
    unpublished_store: str,
    mode: Literal["dry-run"] = "dry-run",
    receipt_path: Path | None = None,
    evaluated_at: datetime | None = None,
) -> BacklogReconciliationReceipt:
    """Build the exact read-only reconciliation plan and receipt."""

    if mode != "dry-run":
        raise BacklogReconciliationError(
            "live mutation must enter through ControlPlaneCommandService"
        )
    evaluated = _as_utc(evaluated_at or datetime.now(tz=UTC))
    plan, proving_before, unpublished_before = _plan_reconciliation(
        proving_store, unpublished_store, evaluated_at=evaluated
    )
    receipt = _receipt_from_plan(
        plan,
        mode="dry-run",
        mutated=False,
        remapped_count=0,
        no_loss_proof=_no_loss_proof(
            proving_before=proving_before,
            unpublished_before=unpublished_before,
        ),
        gates={
            "G1": "pass",
            "G2": "pending-live",
            "G3": "census-recorded",
            "G4": "pending-rerun",
            "G5": "pass",
        },
    )
    _write_receipt(receipt_path, receipt)
    return receipt


class _ControlPlaneCommandService:
    """Sole direct writer for Control Plane canonical mutation."""

    principal = COMMAND_SERVICE_PRINCIPAL

    def __init__(
        self,
        *,
        authenticator: object,
        clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
    ) -> None:
        if authenticator is None:
            raise ValueError("command service requires an authenticator")
        self._authenticator = authenticator
        self._clock = clock

    def reconcile_effective_revision_backlog(
        self,
        *,
        proving_store: str,
        unpublished_store: str,
        dry_run_receipt: Mapping[str, object],
        receipt_path: Path | None = None,
        backup_dir: Path | None = None,
        allow_canonical_mutation: bool = False,
        evaluated_at: datetime | None = None,
        idempotency_key: str,
        expected_mapping_digest: str,
        proof: AuthenticationProof,
        mode: Literal["live"] = "live",
    ) -> BacklogReconciliationReceipt:
        if mode != "live":
            raise ValueError("command-service mutation is live-only")
        now = self._clock()
        authentication = self._authenticator.authenticate(proof, now=now)
        authentication.require_current(now)
        command = _ReconciliationCommand(
            caller_principal=authentication.principal_id,
            writer_principal=COMMAND_SERVICE_PRINCIPAL,
            command_type=RECONCILE_COMMAND_TYPE,
            idempotency_key=idempotency_key,
            expected_mapping_digest=expected_mapping_digest,
        )
        refuse_canonical_write(
            proving_store, allow_canonical_mutation=allow_canonical_mutation
        )
        refuse_canonical_write(
            unpublished_store, allow_canonical_mutation=allow_canonical_mutation
        )
        if backup_dir is None:
            raise BacklogReconciliationError(
                "G3: live migration requires a backup directory"
            )
        _assert_command_authority(command)
        proving_path = Path(proving_store)
        unpublished_path = Path(unpublished_store)
        backup_root = Path(backup_dir)

        # Recovery is itself a mutation, so it stays behind authentication.
        _restore_incomplete_dual_store(
            proving_path, unpublished_path, backup_root
        )
        evaluated = _as_utc(evaluated_at or datetime.now(tz=UTC))
        plan, _proving_before, _unpublished_before = _plan_reconciliation(
            proving_store, unpublished_store, evaluated_at=evaluated
        )
        _assert_g2(plan, dry_run_receipt)
        _assert_command(command, plan, dry_run_receipt)
        completed = _load_completed_command(unpublished_store, command)
        if completed is not None:
            _write_receipt(receipt_path, completed)
            return completed

        proving_backup = backup_root / "proving_store.sqlite3"
        unpublished_backup = backup_root / "unpublished_store.sqlite3"
        proving_backup_result = _backup_store(proving_path, proving_backup)
        unpublished_backup_result = _backup_store(
            unpublished_path, unpublished_backup
        )
        coordinator: dict[str, object] = {
            "mapping_digest": plan.mapping_digest,
            "idempotency_key": command.idempotency_key,
            "proving_store": _store_identity(proving_path),
            "unpublished_store": _store_identity(unpublished_path),
            "proving_backup": str(proving_backup.resolve()),
            "unpublished_backup": str(unpublished_backup.resolve()),
            "proving_backup_digest": proving_backup_result["digest"],
            "unpublished_backup_digest": unpublished_backup_result["digest"],
        }
        coordinator_path = backup_root / COORDINATOR_NAME
        _write_coordinator(
            coordinator_path, {**coordinator, "status": "STARTED"}
        )

        def apply_mutations() -> tuple[int, BacklogReconciliationReceipt]:
            conn: sqlite3.Connection | None = sqlite3.connect(str(unpublished_path))
            try:
                apply_control_plane_sqlite_profile(conn, wal=False)
                conn.execute("ATTACH DATABASE ? AS proving", (str(proving_path),))
                apply_control_plane_sqlite_profile(
                    conn, wal=False, schema=PROVING_ATTACH_SCHEMA
                )

                def versions() -> tuple[int, int]:
                    return (
                        int(conn.execute("PRAGMA main.data_version").fetchone()[0]),
                        int(conn.execute("PRAGMA proving.data_version").fetchone()[0]),
                    )

                before_plan_versions = versions()
                live_plan = _build_plan(
                    conn,
                    conn,
                    evaluated_at=evaluated,
                    proving_schema=PROVING_ATTACH_SCHEMA,
                )
                if versions() != before_plan_versions:
                    raise BacklogReconciliationError(
                        "G2: stores changed while planning"
                    )
                _assert_g1(live_plan)
                _assert_g2(live_plan, dry_run_receipt)
                _assert_g5(live_plan)
                _assert_command(command, live_plan, dry_run_receipt)
                proving_before = _census_proving(
                    conn, schema=PROVING_ATTACH_SCHEMA
                )
                unpublished_before = _census_unpublished(conn)
                conn.execute("BEGIN IMMEDIATE")
                if versions() != before_plan_versions:
                    raise BacklogReconciliationError(
                        "G2: stores changed before mutation"
                    )
                deadline = time.monotonic() + LIVE_TRANSACTION_TIMEOUT_SECONDS
                conn.set_progress_handler(lambda: time.monotonic() >= deadline, 1_000)
                _ensure_landed_schema(conn)
                remapped = _apply_proving(
                    conn, live_plan, schema=PROVING_ATTACH_SCHEMA
                )
                remapped += _apply_remap_rows(conn, live_plan)
                no_loss = _no_loss_proof(
                    proving_before=proving_before,
                    unpublished_before=unpublished_before,
                    proving_after=_census_proving(
                        conn, schema=PROVING_ATTACH_SCHEMA
                    ),
                    unpublished_after=_census_unpublished(conn),
                )
                if no_loss["lost"]:
                    raise BacklogReconciliationError(
                        "G3: append-only census lost records"
                    )
                rerun_changes = _apply_proving(
                    conn, live_plan, schema=PROVING_ATTACH_SCHEMA
                ) + _apply_remap_rows(conn, live_plan)
                if rerun_changes:
                    raise BacklogReconciliationError(
                        "G4: rerun produced further remapping"
                    )
                receipt = _receipt_from_plan(
                    live_plan,
                    mode="live",
                    mutated=True,
                    remapped_count=remapped,
                    no_loss_proof=no_loss,
                    gates={key: "pass" for key in ("G1", "G2", "G3", "G4", "G5")},
                    command=command.as_dict(),
                )
                _retain_receipt(conn, receipt.as_dict())
                _record_command(conn, command, receipt)
                conn.commit()
                return remapped, receipt
            except Exception as exc:
                if conn is not None and conn.in_transaction:
                    conn.rollback()
                if conn is not None:
                    conn.close()
                    conn = None
                if isinstance(exc, sqlite3.OperationalError) and "interrupted" in str(
                    exc
                ):
                    raise BacklogReconciliationError(
                        "live reconciliation exceeded the five-second transaction limit"
                    ) from exc
                raise
            finally:
                if conn is not None:
                    conn.set_progress_handler(None, 0)
                    conn.close()

        try:
            _set_journal_mode(proving_path, "DELETE")
            _set_journal_mode(unpublished_path, "DELETE")
            remapped, receipt = apply_mutations()
        except Exception:
            _restore_wal_profiles(proving_path, unpublished_path)
            _write_coordinator(
                coordinator_path, {**coordinator, "status": "ABORTED"}
            )
            raise
        coordinator["remapped_count"] = remapped
        _write_coordinator(
            coordinator_path, {**coordinator, "status": "COMMITTED"}
        )
        _restore_wal_profiles(proving_path, unpublished_path)
        _write_coordinator(
            coordinator_path, {**coordinator, "status": "COMPLETE"}
        )
        _write_receipt(receipt_path, receipt)
        return receipt
