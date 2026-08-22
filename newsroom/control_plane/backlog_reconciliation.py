"""No-loss remap of poll-amplified identities onto effective revisions.

Independent of the live identity resolver: a bug there cannot approve this
migration. Repair means remap; append-only evidence is never deleted.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from newsroom.authority.canonical import digest_canonical
from newsroom.control_plane.items import parse_observation
from newsroom.control_plane.paths import (
    CANONICAL_PROVING_STORE,
    CANONICAL_UNPUBLISHED_STORE,
)
from newsroom.control_plane.store import append_ledger, connect as connect_unpublished
from newsroom.control_plane.veto import assert_private_store


# Must match newsroom.control_plane.cycle._RAW_HTTP_RETENTION.
RAW_HTTP_RETENTION = timedelta(days=7)
RECONCILIATION_KIND = "EFFECTIVE_REVISION_BACKLOG_RECONCILED"
SOURCE_SUPPLIED_VERSION_MARKER = "SOURCE_SUPPLIED_VERSION_MARKER"
FIRST_SEEN_WITHOUT_RETAINED_OBSERVATION = "FIRST_SEEN_WITHOUT_RETAINED_OBSERVATION"
RETENTION_WINDOW_BOUNDED_INACCURACY = "RETENTION_WINDOW_BOUNDED_INACCURACY"
GRAPH_EFFECT_MULTIPLE_TERMINAL = "GRAPH_EFFECT_MULTIPLE_TERMINAL"


class BacklogReconciliationError(RuntimeError):
    """A fail-closed reconciliation gate refused to mutate."""


class CanonicalStoreGuardError(BacklogReconciliationError):
    """Writable access to a canonical Control Plane store was refused."""


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

    def as_dict(self) -> dict[str, object]:
        return {
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


def _readonly_connect(path: str) -> sqlite3.Connection:
    resolved = _resolved(path)
    if not resolved.is_file():
        raise BacklogReconciliationError(f"store does not exist: {path}")
    connection = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


def _writable_connect(path: str, *, allow_canonical_mutation: bool) -> sqlite3.Connection:
    refuse_canonical_write(path, allow_canonical_mutation=allow_canonical_mutation)
    assert_private_store(path)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _ids(connection: sqlite3.Connection, sql: str) -> frozenset[str]:
    return frozenset(str(row[0]) for row in connection.execute(sql))


def _census_proving(connection: sqlite3.Connection) -> dict[str, frozenset[str]]:
    census: dict[str, frozenset[str]] = {}
    if _table_exists(connection, "proving_observations"):
        census["proving_observations"] = _ids(
            connection,
            """
            SELECT run_id || '|' || source_id || '|' || fetched_at || '|' || body_digest
            FROM proving_observations
            """,
        )
    else:
        census["proving_observations"] = frozenset()
    if _table_exists(connection, "proving_runs"):
        census["proving_runs"] = _ids(connection, "SELECT run_id FROM proving_runs")
    if _table_exists(connection, "proving_gates"):
        census["proving_gates"] = _ids(
            connection, "SELECT run_id || '|' || gate_id FROM proving_gates"
        )
    if _table_exists(connection, "proving_rights_packets"):
        census["proving_rights_packets"] = _ids(
            connection,
            "SELECT run_id || '|' || gate_id FROM proving_rights_packets",
        )
    return census


def _census_unpublished(connection: sqlite3.Connection) -> dict[str, frozenset[str]]:
    census: dict[str, frozenset[str]] = {}
    queries = (
        ("ledger", "SELECT digest FROM ledger"),
        (
            "unpublished_graphiti_attempt_receipts",
            "SELECT ingest_id || ':' || attempt_number "
            "FROM unpublished_graphiti_attempt_receipts",
        ),
        ("unpublished_graphiti_ingest", "SELECT ingest_id FROM unpublished_graphiti_ingest"),
        (
            "unpublished_graphiti_receipts",
            "SELECT ingest_id FROM unpublished_graphiti_receipts",
        ),
        (
            "unpublished_graphiti_authority_records",
            "SELECT record_id FROM unpublished_graphiti_authority_records",
        ),
        ("unpublished_graphiti_spend", "SELECT spend_id FROM unpublished_graphiti_spend"),
        (
            "unpublished_graphiti_failures",
            "SELECT ingest_id FROM unpublished_graphiti_failures",
        ),
        (
            "unpublished_surface_payloads",
            "SELECT payload_id FROM unpublished_surface_payloads",
        ),
        (
            "unpublished_effective_revision_landed",
            "SELECT source_id || '|' || item_key || '|' || revision_digest "
            "FROM unpublished_effective_revision_landed",
        ),
    )
    for name, sql in queries:
        census[name] = _ids(connection, sql) if _table_exists(connection, name) else frozenset()
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
) -> tuple[tuple[str, str, str, bytes], ...]:
    if not _table_exists(connection, "proving_observations"):
        return ()
    rows = connection.execute(
        """
        SELECT source_id, fetched_at, url, body
        FROM proving_observations
        WHERE status_code=200 AND body IS NOT NULL AND error IS NULL
        ORDER BY fetched_at ASC, source_id, url
        """
    ).fetchall()
    return tuple(
        (str(source_id), str(fetched_at), str(url), bytes(body))
        for source_id, fetched_at, url, body in rows
        if body
    )


@dataclass(frozen=True, slots=True)
class _Plan:
    expected_keys: tuple[_Triple, ...]
    earliest: dict[_Triple, str]
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


def _amplification(old_n: int, new_n: int) -> str:
    if new_n <= 0:
        return "n/a" if old_n == 0 else "unbounded"
    return f"{old_n / new_n:.2f}x"


def _build_plan(
    proving: sqlite3.Connection,
    unpublished: sqlite3.Connection | None,
    *,
    evaluated_at: datetime,
) -> _Plan:
    earliest: dict[_Triple, str] = {}
    old_keys: set[tuple[str, ...]] = set()
    version_markers: dict[_Triple, set[tuple[str | None, str | None]]] = {}
    poll_mappings: list[dict[str, str]] = []
    old_by_source: dict[str, set[tuple[str, ...]]] = {}
    new_by_source: dict[str, set[_Triple]] = {}

    for source_id, fetched_at, url, body in _usable_observation_rows(proving):
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
            new_by_source.setdefault(source_id, set()).add(triple)

    expected_keys = tuple(
        sorted(earliest, key=lambda item: (item.source_id, item.item_key, item.revision_digest))
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
    if _table_exists(proving, "proving_runs"):
        older_runs = proving.execute(
            "SELECT 1 FROM proving_runs WHERE started_at<? LIMIT 1",
            (cutoff,),
        ).fetchone() is not None

    first_seen: dict[_Triple, str] = {}
    if _table_exists(proving, "proving_revision_first_seen"):
        for source_id, item_key, revision_digest, first_seen_at in proving.execute(
            """
            SELECT source_id, item_key, revision_digest, first_seen_at
            FROM proving_revision_first_seen
            """
        ):
            first_seen[
                _Triple(str(source_id), str(item_key), str(revision_digest))
            ] = str(first_seen_at)

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
        window_bound = older_runs and new_at >= cutoff
        if window_bound:
            bounded.append(
                {
                    "rule": RETENTION_WINDOW_BOUNDED_INACCURACY,
                    "source_id": triple.source_id,
                    "item_key": triple.item_key,
                    "revision_digest": triple.revision_digest,
                    "earliest_retained_at": new_at,
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
        if recorded == new_at:
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

    expected_n = len(expected_keys)
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
                "amplification_after": "1.00x" if new_n else _amplification(old_n, new_n),
            }
        )

    mapping_digest = digest_canonical(
        {
            "effective_revisions": [
                {**triple.as_dict(), "first_observed_at": earliest[triple]}
                for triple in expected_keys
            ],
            "amplified_poll_mappings": poll_mappings,
            "orphan_first_seen": [
                {**triple.as_dict(), "first_seen_at": first_seen[triple]}
                for triple in orphan_keys
            ],
        }
    )
    collisions = _graph_effect_collisions(unpublished, earliest) if unpublished else ()
    return _Plan(
        expected_keys=expected_keys,
        earliest=earliest,
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
    )


def _graph_effect_collisions(
    unpublished: sqlite3.Connection, earliest: dict[_Triple, str]
) -> tuple[dict[str, object], ...]:
    if not _table_exists(unpublished, "unpublished_graphiti_ingest"):
        return ()
    ingest_by_item: dict[tuple[str, str], list[str]] = {}
    for ingest_id, source_id, item_key, outcome in unpublished.execute(
        """
        SELECT ingest_id, source_id, item_key, outcome
        FROM unpublished_graphiti_ingest
        """
    ):
        if str(outcome) not in {"COMPLETE", "PARTIAL"}:
            continue
        ingest_by_item.setdefault((str(source_id), str(item_key)), []).append(
            str(ingest_id)
        )
    digest_by_item: dict[tuple[str, str], set[str]] = {}
    for triple in earliest:
        digest_by_item.setdefault((triple.source_id, triple.item_key), set()).add(
            triple.revision_digest
        )
    collisions: list[dict[str, object]] = []
    for (source_id, item_key), ingest_ids in sorted(ingest_by_item.items()):
        if len(ingest_ids) < 2:
            continue
        digests = digest_by_item.get((source_id, item_key), set())
        if len(digests) > 1:
            continue
        collisions.append(
            {
                "kind": GRAPH_EFFECT_MULTIPLE_TERMINAL,
                "source_id": source_id,
                "item_key": item_key,
                "revision_digest": next(iter(digests)) if digests else None,
                "ingest_ids": sorted(ingest_ids),
                "merged": False,
            }
        )
    return tuple(collisions)


def _assert_g1(plan: _Plan) -> None:
    expected = set(plan.expected_keys)
    if plan.new_effective_revision_count != len(expected):
        raise BacklogReconciliationError(
            "G1: new effective-revision count differs from the independent dedupe"
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
    before = dry_run_receipt.get("before_denominator", dry_run_receipt.get("old_identity_count"))
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


def _backup_store(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
    dest_conn = sqlite3.connect(destination)
    try:
        source_conn.backup(dest_conn)
        dest_conn.commit()
    finally:
        dest_conn.close()
        source_conn.close()


def _restore_store(backup: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(destination) + suffix)
        if sidecar.exists():
            sidecar.unlink()
    source_conn = sqlite3.connect(f"file:{backup.resolve()}?mode=ro", uri=True)
    dest_conn = sqlite3.connect(destination)
    try:
        source_conn.backup(dest_conn)
        dest_conn.commit()
    finally:
        dest_conn.close()
        source_conn.close()


def _row_changes(connection: sqlite3.Connection) -> int:
    return int(connection.execute("SELECT changes()").fetchone()[0])


def _ensure_first_seen_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS proving_revision_first_seen(
            source_id TEXT NOT NULL,
            item_key TEXT NOT NULL,
            revision_digest TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            PRIMARY KEY(source_id, item_key, revision_digest)
        ) WITHOUT ROWID
        """
    )


def _ensure_remap_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS unpublished_effective_revision_remap(
            mapping_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            item_key TEXT NOT NULL,
            revision_digest TEXT NOT NULL,
            old_observed_fallback_at TEXT,
            new_first_observed_at TEXT NOT NULL,
            kind TEXT NOT NULL,
            retention_window_bounded_inaccuracy INTEGER NOT NULL DEFAULT 0
                CHECK(retention_window_bounded_inaccuracy IN (0,1)),
            old_ingest_id TEXT,
            at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS unpublished_backlog_reconciliation_receipts(
            receipt_digest TEXT PRIMARY KEY,
            at TEXT NOT NULL,
            mode TEXT NOT NULL,
            receipt_json TEXT NOT NULL
        )
        """
    )


def _apply_proving(connection: sqlite3.Connection, plan: _Plan) -> int:
    _ensure_first_seen_schema(connection)
    changed = 0
    for correction in plan.first_seen_corrections:
        triple = (
            str(correction["source_id"]),
            str(correction["item_key"]),
            str(correction["revision_digest"]),
        )
        new_at = str(correction["new_first_seen_at"])
        if correction["old_first_seen_at"] is None:
            connection.execute(
                """
                INSERT OR IGNORE INTO proving_revision_first_seen(
                    source_id, item_key, revision_digest, first_seen_at
                ) VALUES(?,?,?,?)
                """,
                (*triple, new_at),
            )
        else:
            connection.execute(
                """
                UPDATE proving_revision_first_seen
                SET first_seen_at=?
                WHERE source_id=? AND item_key=? AND revision_digest=?
                  AND first_seen_at=?
                """,
                (new_at, *triple, str(correction["old_first_seen_at"])),
            )
        changed += _row_changes(connection)
    return changed


def _apply_remap_rows(connection: sqlite3.Connection, plan: _Plan) -> int:
    _ensure_remap_schema(connection)
    at = _now()
    changed = 0
    for mapping in plan.poll_mappings:
        payload = {"kind": "AMPLIFIED_POLL_REMAP", **mapping}
        connection.execute(
            """
            INSERT OR IGNORE INTO unpublished_effective_revision_remap(
                mapping_id, source_id, item_key, revision_digest,
                old_observed_fallback_at, new_first_observed_at, kind,
                retention_window_bounded_inaccuracy, old_ingest_id, at
            ) VALUES(?,?,?,?,?,?,?,?,NULL,?)
            """,
            (
                digest_canonical(payload),
                mapping["source_id"],
                mapping["item_key"],
                mapping["revision_digest"],
                mapping["poll_observed_at"],
                mapping["new_first_observed_at"],
                "AMPLIFIED_POLL_REMAP",
                0,
                at,
            ),
        )
        changed += _row_changes(connection)
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
        connection.execute(
            """
            INSERT OR IGNORE INTO unpublished_effective_revision_remap(
                mapping_id, source_id, item_key, revision_digest,
                old_observed_fallback_at, new_first_observed_at, kind,
                retention_window_bounded_inaccuracy, old_ingest_id, at
            ) VALUES(?,?,?,?,?,?,?,?,NULL,?)
            """,
            (
                digest_canonical(payload),
                correction["source_id"],
                correction["item_key"],
                correction["revision_digest"],
                correction["old_first_seen_at"],
                correction["new_first_seen_at"],
                "FIRST_SEEN_CORRECTION",
                window,
                at,
            ),
        )
        changed += _row_changes(connection)
    return changed


def _retain_receipt(
    connection: sqlite3.Connection, receipt: Mapping[str, object]
) -> None:
    _ensure_remap_schema(connection)
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


def _write_receipt(path: Path | None, receipt: BacklogReconciliationReceipt) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(receipt.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_receipt(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise BacklogReconciliationError("dry-run receipt is not an object")
    return payload


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
        {}
        if proving_after is None
        else _census_missing(proving_before, proving_after)
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
    )


def reconcile_effective_revision_backlog(
    *,
    proving_store: str,
    unpublished_store: str,
    mode: Literal["dry-run", "live"],
    dry_run_receipt: Mapping[str, object] | None = None,
    receipt_path: Path | None = None,
    backup_dir: Path | None = None,
    allow_canonical_mutation: bool = False,
    evaluated_at: datetime | None = None,
) -> BacklogReconciliationReceipt:
    """Remap amplified backlog identities. Dry-run mutates nothing."""

    if mode not in {"dry-run", "live"}:
        raise BacklogReconciliationError(f"unknown mode {mode}")
    evaluated = _as_utc(evaluated_at or datetime.now(tz=UTC))
    unpublished_path = Path(unpublished_store)
    proving = _readonly_connect(proving_store)
    unpublished: sqlite3.Connection | None = None
    try:
        if unpublished_path.is_file():
            unpublished = _readonly_connect(unpublished_store)
        plan = _build_plan(proving, unpublished, evaluated_at=evaluated)
        proving_before = _census_proving(proving)
        unpublished_before = (
            _census_unpublished(unpublished)
            if unpublished is not None
            else _empty_unpublished_census()
        )
        _assert_g1(plan)
        _assert_g5(plan)
        if mode == "live":
            if dry_run_receipt is None:
                raise BacklogReconciliationError(
                    "G2: live migration requires the dry-run receipt"
                )
            _assert_g2(plan, dry_run_receipt)
    finally:
        proving.close()
        if unpublished is not None:
            unpublished.close()

    if mode == "dry-run":
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

    refuse_canonical_write(proving_store, allow_canonical_mutation=allow_canonical_mutation)
    refuse_canonical_write(
        unpublished_store, allow_canonical_mutation=allow_canonical_mutation
    )
    if backup_dir is None:
        raise BacklogReconciliationError("G3: live migration requires a backup directory")
    backup_root = Path(backup_dir)
    proving_backup = backup_root / "proving_store.sqlite3"
    unpublished_backup = backup_root / "unpublished_store.sqlite3"
    _backup_store(Path(proving_store), proving_backup)
    if unpublished_path.is_file():
        _backup_store(unpublished_path, unpublished_backup)

    proving_write = _writable_connect(
        proving_store, allow_canonical_mutation=allow_canonical_mutation
    )
    unpublished_write: sqlite3.Connection | None = None
    try:
        unpublished_write = connect_unpublished(unpublished_store)
        proving_write.execute("BEGIN IMMEDIATE")
        unpublished_write.execute("BEGIN IMMEDIATE")
        remapped = _apply_proving(proving_write, plan)
        remapped += _apply_remap_rows(unpublished_write, plan)
        proving_after = _census_proving(proving_write)
        unpublished_after = _census_unpublished(unpublished_write)
        no_loss = _no_loss_proof(
            proving_before=proving_before,
            unpublished_before=unpublished_before,
            proving_after=proving_after,
            unpublished_after=unpublished_after,
        )
        if no_loss["lost"]:
            raise BacklogReconciliationError("G3: append-only census lost records")
        receipt = _receipt_from_plan(
            plan,
            mode="live",
            mutated=True,
            remapped_count=remapped,
            no_loss_proof=no_loss,
            gates={
                "G1": "pass",
                "G2": "pass",
                "G3": "pass",
                "G4": "pending-rerun",
                "G5": "pass",
            },
        )
        _retain_receipt(unpublished_write, receipt.as_dict())
        proving_write.commit()
        unpublished_write.commit()
    except Exception:
        if proving_write.in_transaction:
            proving_write.rollback()
        if unpublished_write is not None and unpublished_write.in_transaction:
            unpublished_write.rollback()
        _restore_store(proving_backup, Path(proving_store))
        if unpublished_backup.exists():
            _restore_store(unpublished_backup, unpublished_path)
        raise
    finally:
        proving_write.close()
        if unpublished_write is not None:
            unpublished_write.close()
    _write_receipt(receipt_path, receipt)
    return receipt
