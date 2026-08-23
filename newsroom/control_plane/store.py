"""Unpublished Surface Payload store and append-only control ledger."""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
)
from newsroom.control_plane.surface import UnpublishedSurfacePayload
from newsroom.control_plane.corpus import EligibleCorpusRevision
from newsroom.control_plane.sqlite_profile import apply_control_plane_sqlite_profile
from newsroom.control_plane.veto import (
    VetoError,
    assert_private_store,
    refuse_public_effect,
)
from newsroom.effective_revision import EffectiveRevisionIdentity
from newsroom.graphiti_adapter.embedding_meter import is_exact_provider_reported_usage

SCHEMA_VERSION = "newsroom.control-plane.unpublished.v11"
EFFECTIVE_REVISION_LANDED = "EFFECTIVE_REVISION_LANDED"
LEDGER_GENESIS = "sha256:" + ("0" * 64)
GRAPHITI_MAX_FAILURES = 3
_SQLITE_BIND_BATCH_SIZE = 500
_NO_EMBEDDING_USAGE_KEYS = frozenset(
    {
        "requests",
        "request_count",
        "embedding_tokens",
        "cost_usd_microunits",
        "usage_basis",
    }
)


def is_exact_no_embedding_call(
    embedding_usage: Mapping[str, object] | None,
) -> bool:
    """Return whether provider telemetry is the complete canonical no-call shape."""

    if embedding_usage is None or set(embedding_usage) != _NO_EMBEDDING_USAGE_KEYS:
        return False
    zero_fields = (
        embedding_usage["request_count"],
        embedding_usage["embedding_tokens"],
        embedding_usage["cost_usd_microunits"],
    )
    return (
        embedding_usage["usage_basis"] == "NO_EMBEDDING_CALL"
        and embedding_usage["requests"] == []
        and all(type(value) is int and value == 0 for value in zero_fields)
    )


def _bind_batches(values: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    return tuple(
        values[offset : offset + _SQLITE_BIND_BATCH_SIZE]
        for offset in range(0, len(values), _SQLITE_BIND_BATCH_SIZE)
    )


_PAYLOAD_SQL = """
CREATE TABLE IF NOT EXISTS unpublished_surface_payloads(
    payload_id TEXT PRIMARY KEY,
    payload_kind TEXT NOT NULL CHECK(payload_kind='unpublished_surface_payload'),
    publication_bundle INTEGER NOT NULL DEFAULT 0 CHECK(publication_bundle=0),
    auto_publish INTEGER NOT NULL DEFAULT 0 CHECK(auto_publish=0),
    language TEXT NOT NULL CHECK(language='ZH_HANT_HK'),
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    evidence_package_digest TEXT NOT NULL,
    story_candidate_id TEXT NOT NULL UNIQUE,
    event_hypothesis_id TEXT NOT NULL,
    source_lineage TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status='UNPUBLISHED'),
    writer_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger(
    seq INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    prev_digest TEXT NOT NULL,
    digest TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS unpublished_graphiti_attempts(
    story_candidate_id TEXT PRIMARY KEY,
    outcome TEXT NOT NULL,
    proposal_count INTEGER NOT NULL,
    failure_code TEXT NOT NULL,
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS unpublished_graphiti_ingest(
    ingest_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    item_key TEXT NOT NULL,
    outcome TEXT NOT NULL,
    proposal_count INTEGER NOT NULL,
    entity_count INTEGER NOT NULL,
    relation_count INTEGER NOT NULL,
    failure_code TEXT NOT NULL,
    temporal_basis TEXT NOT NULL,
    reference_time TEXT NOT NULL,
    generation_id TEXT NOT NULL,
    receipt_digest TEXT NOT NULL,
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS unpublished_graphiti_receipts(
    ingest_id TEXT PRIMARY KEY,
    receipt_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS unpublished_graphiti_attempt_receipts(
    ingest_id TEXT NOT NULL,
    attempt_number INTEGER NOT NULL,
    outcome TEXT NOT NULL,
    receipt_digest TEXT NOT NULL,
    receipt_json TEXT NOT NULL,
    at TEXT NOT NULL,
    PRIMARY KEY(ingest_id, attempt_number)
);
CREATE TABLE IF NOT EXISTS unpublished_graphiti_authority_records(
    record_id TEXT PRIMARY KEY,
    record_type TEXT NOT NULL,
    record_digest TEXT NOT NULL,
    record_json TEXT NOT NULL,
    retained_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS unpublished_graphiti_coverage(
    seq INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    coverage_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS unpublished_graphiti_failures(
    ingest_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    item_key TEXT NOT NULL,
    retry_count INTEGER NOT NULL,
    last_outcome TEXT NOT NULL,
    last_failure_code TEXT NOT NULL,
    dead_lettered INTEGER NOT NULL DEFAULT 0 CHECK(dead_lettered IN (0,1)),
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS unpublished_graphiti_spend(
    spend_id TEXT PRIMARY KEY,
    ingest_id TEXT NOT NULL,
    attempt_number INTEGER NOT NULL,
    proving_run_id TEXT NOT NULL,
    generation_id TEXT,
    reserved_gbp_microunits INTEGER NOT NULL,
    actual_usd_microunits INTEGER,
    actual_gbp_microunits INTEGER,
    usage_basis TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('RESERVED','RECONCILED','UNRECONCILED')),
    provider_usage_json TEXT,
    dispatch_owner TEXT,
    dispatch_lease_expires_at TEXT,
    at TEXT NOT NULL,
    UNIQUE(ingest_id, attempt_number)
);
"""


@dataclass(frozen=True, slots=True)
class UnpublishedDraft:
    """Legacy sidecar row. Not a Destination Surface Payload."""

    draft_id: str
    source_id: str
    proving_run_id: str
    observation_digest: str
    item_key: str
    headline: str
    body: str
    canonical_url: str
    observed_at: str
    minted_at: str
    status: str


class GraphitiSpendCeilingExceeded(RuntimeError):
    """A new Graphiti reservation would exceed the fixed OD-011 ceiling."""


class EffectiveRevisionLandedError(RuntimeError):
    """A landed record cannot be emitted for this effective revision."""


def _now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


_LANDED_TABLE = "unpublished_effective_revision_landed"
_LANDED_V10_TABLE = "unpublished_effective_revision_landed_v10"
_LANDED_V11_DDL = f"""
CREATE TABLE {_LANDED_TABLE}(
    source_id TEXT NOT NULL,
    item_key TEXT NOT NULL,
    revision_digest TEXT NOT NULL,
    published_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    first_observed_at TEXT NOT NULL,
    ingest_ids_json TEXT NOT NULL DEFAULT '[]',
    legacy_v10 INTEGER NOT NULL DEFAULT 0,
    payload_digest TEXT NOT NULL,
    ledger_digest TEXT NOT NULL,
    at TEXT NOT NULL,
    PRIMARY KEY(source_id, item_key, revision_digest, published_at, updated_at)
) WITHOUT ROWID
"""


def _sqlite_table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _landed_columns(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[1]) for row in connection.execute(f"PRAGMA table_info({_LANDED_TABLE})")
    }


def _ensure_landed_schema(connection: sqlite3.Connection) -> None:
    has_landed = _sqlite_table_exists(connection, _LANDED_TABLE)
    has_v10 = _sqlite_table_exists(connection, _LANDED_V10_TABLE)
    columns = _landed_columns(connection) if has_landed else set()
    needs_rebuild = has_landed and (
        "published_at" not in columns or "ingest_ids_json" not in columns
    )
    if has_landed and not needs_rebuild and "legacy_v10" not in columns:
        connection.execute(
            f"ALTER TABLE {_LANDED_TABLE} "
            "ADD COLUMN legacy_v10 INTEGER NOT NULL DEFAULT 0"
        )
    if has_landed and not needs_rebuild and not has_v10:
        return
    own_txn = not connection.in_transaction
    if own_txn:
        connection.execute("BEGIN IMMEDIATE")
    try:
        if needs_rebuild:
            connection.execute(
                f"ALTER TABLE {_LANDED_TABLE} RENAME TO {_LANDED_V10_TABLE}"
            )
            has_v10 = True
            connection.execute(_LANDED_V11_DDL)
        elif not _sqlite_table_exists(connection, _LANDED_TABLE):
            connection.execute(_LANDED_V11_DDL)
        if has_v10 and _sqlite_table_exists(connection, _LANDED_V10_TABLE):
            connection.execute(
                f"""
                INSERT OR IGNORE INTO {_LANDED_TABLE}(
                    source_id, item_key, revision_digest, published_at, updated_at,
                    first_observed_at, ingest_ids_json, legacy_v10, payload_digest,
                    ledger_digest, at
                )
                SELECT source_id, item_key, revision_digest, '', '',
                       first_observed_at, '[]', 1, payload_digest, ledger_digest, at
                FROM {_LANDED_V10_TABLE}
                """
            )
            v10_count = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {_LANDED_V10_TABLE}"
                ).fetchone()[0]
            )
            v11_count = int(
                connection.execute(f"SELECT COUNT(*) FROM {_LANDED_TABLE}").fetchone()[
                    0
                ]
            )
            if v11_count < v10_count:
                raise EffectiveRevisionLandedError(
                    "landed v10 rows were not recovered into the active schema"
                )
            connection.execute(f"DROP TABLE {_LANDED_V10_TABLE}")
        if own_txn:
            connection.commit()
    except Exception:
        if own_txn and connection.in_transaction:
            connection.rollback()
        raise


def ensure_reconciliation_schema(
    connection: sqlite3.Connection, *, schema: str = "main"
) -> None:
    prefix = "" if schema == "main" else f"{schema}."
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}unpublished_effective_revision_remap(
            mapping_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            item_key TEXT NOT NULL,
            revision_digest TEXT NOT NULL,
            published_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '',
            old_observed_fallback_at TEXT,
            new_first_observed_at TEXT NOT NULL,
            kind TEXT NOT NULL,
            retention_window_bounded_inaccuracy INTEGER NOT NULL DEFAULT 0
                CHECK(retention_window_bounded_inaccuracy IN (0,1)),
            old_ingest_id TEXT,
            new_ingest_id TEXT,
            at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}unpublished_backlog_reconciliation_receipts(
            receipt_digest TEXT PRIMARY KEY,
            at TEXT NOT NULL,
            mode TEXT NOT NULL,
            receipt_json TEXT NOT NULL
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}unpublished_reconciliation_commands(
            idempotency_key TEXT PRIMARY KEY,
            caller_principal TEXT NOT NULL,
            command_type TEXT NOT NULL,
            expected_mapping_digest TEXT NOT NULL,
            receipt_json TEXT NOT NULL,
            at TEXT NOT NULL
        )
        """
    )
    pragma = (
        "table_info(unpublished_effective_revision_remap)"
        if schema == "main"
        else f"{schema}.table_info(unpublished_effective_revision_remap)"
    )
    info = list(connection.execute(f"PRAGMA {pragma}"))
    if not info:
        return
    columns = {str(row[1]) for row in info}
    for name, declaration in (
        ("new_ingest_id", "TEXT"),
        ("published_at", "TEXT NOT NULL DEFAULT ''"),
        ("updated_at", "TEXT NOT NULL DEFAULT ''"),
    ):
        if name not in columns:
            connection.execute(
                f"ALTER TABLE {prefix}unpublished_effective_revision_remap "
                f"ADD COLUMN {name} {declaration}"
            )


def connect(path: str) -> sqlite3.Connection:
    assert_private_store(path)
    connection = sqlite3.connect(path)
    apply_control_plane_sqlite_profile(connection)
    connection.executescript(_PAYLOAD_SQL)
    _ensure_landed_schema(connection)
    ensure_reconciliation_schema(connection)
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(unpublished_graphiti_spend)")
    }
    if "proving_run_id" not in columns:
        connection.execute(
            "ALTER TABLE unpublished_graphiti_spend "
            "ADD COLUMN proving_run_id TEXT NOT NULL DEFAULT 'LEGACY_UNKNOWN'"
        )
    if "generation_id" not in columns:
        connection.execute(
            "ALTER TABLE unpublished_graphiti_spend ADD COLUMN generation_id TEXT"
        )
    for column, declaration in (
        ("dispatch_owner", "TEXT"),
        ("dispatch_lease_expires_at", "TEXT"),
    ):
        if column not in columns:
            connection.execute(
                f"ALTER TABLE unpublished_graphiti_spend ADD COLUMN {column} {declaration}"
            )
    return connection


def _head_digest(connection: sqlite3.Connection) -> str:
    row = connection.execute(
        "SELECT digest FROM ledger ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else LEDGER_GENESIS


def append_ledger(
    connection: sqlite3.Connection, kind: str, payload: dict[str, object]
) -> str:
    refuse_public_effect(kind)
    payload_digest = digest_bytes(canonical_json_bytes(payload))
    prev = _head_digest(connection)
    at = _now()
    digest = digest_bytes(
        canonical_json_bytes(
            {"at": at, "kind": kind, "payload_digest": payload_digest, "prev": prev}
        )
    )
    connection.execute(
        "INSERT INTO ledger(at, kind, payload_digest, prev_digest, digest) VALUES(?,?,?,?,?)",
        (at, kind, payload_digest, prev, digest),
    )
    return digest


def effective_revision_landed_payload(
    identity: EffectiveRevisionIdentity,
    *,
    published_at: str = "",
    updated_at: str = "",
    ingest_ids: tuple[str, ...] = (),
    first_observed_at: str | None = None,
) -> dict[str, object]:
    return {
        "source_id": identity.source_id,
        "item_key": identity.item_key,
        "revision_digest": identity.revision_digest,
        "published_at": published_at,
        "updated_at": updated_at,
        "first_observed_at": first_observed_at or identity.first_observed_at,
        "ingest_ids": list(ingest_ids),
    }


def has_effective_revision_landed(
    connection: sqlite3.Connection,
    identity: EffectiveRevisionIdentity,
    *,
    published_at: str = "",
    updated_at: str = "",
) -> bool:
    row = connection.execute(
        """
        SELECT 1 FROM unpublished_effective_revision_landed
        WHERE source_id=? AND item_key=? AND revision_digest=?
          AND published_at=? AND updated_at=?
        """,
        (
            identity.source_id,
            identity.item_key,
            identity.revision_digest,
            published_at,
            updated_at,
        ),
    ).fetchone()
    return row is not None


def emit_effective_revision_landed(
    connection: sqlite3.Connection,
    identity: EffectiveRevisionIdentity,
    *,
    published_at: str | None = None,
    updated_at: str | None = None,
    ingest_ids: tuple[str, ...] = (),
    landed_at: str | None = None,
) -> bool:
    """Append one identity-keyed landed record, or no-op if it already exists."""

    marker_published = published_at or ""
    marker_updated = updated_at or ""
    first_observed_at = landed_at or identity.first_observed_at
    if not identity.source_id or not identity.item_key or not identity.revision_digest:
        raise EffectiveRevisionLandedError(
            "effective-revision landed identity is incomplete"
        )
    if not first_observed_at:
        raise EffectiveRevisionLandedError(
            "effective-revision landed record requires first_observed_at"
        )
    if has_effective_revision_landed(
        connection,
        identity,
        published_at=marker_published,
        updated_at=marker_updated,
    ):
        return False
    payload = effective_revision_landed_payload(
        identity,
        published_at=marker_published,
        updated_at=marker_updated,
        ingest_ids=ingest_ids,
        first_observed_at=first_observed_at,
    )
    payload_digest = digest_canonical(payload)
    ledger_digest = append_ledger(connection, EFFECTIVE_REVISION_LANDED, payload)
    try:
        connection.execute(
            """
            INSERT INTO unpublished_effective_revision_landed(
                source_id, item_key, revision_digest, published_at, updated_at,
                first_observed_at, ingest_ids_json, payload_digest, ledger_digest, at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                identity.source_id,
                identity.item_key,
                identity.revision_digest,
                marker_published,
                marker_updated,
                first_observed_at,
                json.dumps(list(ingest_ids), ensure_ascii=False),
                payload_digest,
                ledger_digest,
                _now(),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise EffectiveRevisionLandedError(
            "effective-revision landed identity collided during emission"
        ) from exc
    return True


def list_landed_revisions(
    connection: sqlite3.Connection,
) -> tuple[EligibleCorpusRevision, ...]:
    from newsroom.control_plane.corpus import synthetic_coverage_revision

    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='unpublished_effective_revision_landed'"
    ).fetchone():
        return ()
    columns = _landed_columns(connection)
    if "published_at" not in columns:
        rows = connection.execute(
            """
            SELECT source_id, item_key, revision_digest, first_observed_at
            FROM unpublished_effective_revision_landed
            """
        ).fetchall()
        return tuple(
            synthetic_coverage_revision(
                source_id=str(source_id),
                item_key=str(item_key),
                revision_digest=str(revision_digest),
                first_observed_at=str(first_observed_at),
            )
            for source_id, item_key, revision_digest, first_observed_at in rows
        )
    corrected_first_seen: dict[tuple[str, str, str], str] = {}
    if _sqlite_table_exists(connection, "unpublished_effective_revision_remap"):
        for source_id, item_key, revision_digest, corrected_at in connection.execute(
            """
            SELECT source_id, item_key, revision_digest, new_first_observed_at
            FROM unpublished_effective_revision_remap
            WHERE kind='FIRST_SEEN_CORRECTION'
            ORDER BY at, mapping_id
            """
        ):
            corrected_first_seen[
                (str(source_id), str(item_key), str(revision_digest))
            ] = str(corrected_at)
    rows = list(
        connection.execute(
            """
        SELECT source_id, item_key, revision_digest, published_at, updated_at,
               first_observed_at, ingest_ids_json, legacy_v10
        FROM unpublished_effective_revision_landed
        """
        )
    )
    marker_landings = {
        (str(row[0]), str(row[1]), str(row[2]), str(row[5]))
        for row in rows
        if not bool(row[7]) and (str(row[3] or "") or str(row[4] or ""))
    }
    revisions: list[EligibleCorpusRevision] = []
    for row in rows:
        landing = (str(row[0]), str(row[1]), str(row[2]), str(row[5]))
        if bool(row[7]) and landing in marker_landings:
            continue
        ingest_ids = tuple(json.loads(str(row[6] or "[]")))
        published = str(row[3] or "") or None
        updated = str(row[4] or "") or None
        first_observed_at = str(row[5])
        if published is None and updated is None:
            first_observed_at = corrected_first_seen.get(
                (str(row[0]), str(row[1]), str(row[2])), first_observed_at
            )
        revisions.append(
            synthetic_coverage_revision(
                source_id=str(row[0]),
                item_key=str(row[1]),
                revision_digest=str(row[2]),
                first_observed_at=first_observed_at,
                published_at=published,
                updated_at=updated,
                ingest_ids=ingest_ids,
            )
        )
    return tuple(revisions)


def list_remapped_ingest_effects(
    connection: sqlite3.Connection,
) -> tuple[tuple[str, str, str, str, str, str, str], ...]:
    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='unpublished_effective_revision_remap'"
    ).fetchone():
        return ()
    columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(unpublished_effective_revision_remap)"
        )
    }
    has_markers = "published_at" in columns and "updated_at" in columns
    if "new_ingest_id" not in columns:
        return ()
    select_sql = (
        """
        SELECT source_id, item_key, revision_digest, published_at, updated_at,
               old_ingest_id, new_ingest_id
        FROM unpublished_effective_revision_remap
        WHERE old_ingest_id IS NOT NULL AND old_ingest_id != ''
          AND new_ingest_id IS NOT NULL AND new_ingest_id != ''
        """
        if has_markers
        else """
        SELECT source_id, item_key, revision_digest, '', '', old_ingest_id, ''
        FROM unpublished_effective_revision_remap
        WHERE 0
        """
    )
    return tuple(
        (
            str(source_id),
            str(item_key),
            str(revision_digest),
            str(published_at or ""),
            str(updated_at or ""),
            str(old_ingest_id),
            str(new_ingest_id),
        )
        for source_id, item_key, revision_digest, published_at, updated_at, old_ingest_id, new_ingest_id in connection.execute(
            select_sql
        )
    )


def spend_reserved(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        """
        SELECT 1 FROM unpublished_graphiti_spend
        WHERE status IN ('RESERVED','UNRECONCILED') LIMIT 1
        """
    ).fetchone()
    return row is not None


def reserve_graphiti_spend(
    connection: sqlite3.Connection,
    *,
    spend_id: str,
    ingest_id: str,
    attempt_number: int,
    proving_run_id: str,
    generation_id: str,
    reserved_gbp_microunits: int,
    ceiling_gbp_microunits: int,
) -> bool:
    existing = connection.execute(
        "SELECT 1 FROM unpublished_graphiti_spend WHERE spend_id=?", (spend_id,)
    ).fetchone()
    if existing is not None:
        return False
    row = connection.execute(
        """
        SELECT COALESCE(SUM(
            CASE WHEN status='RECONCILED'
                 THEN COALESCE(actual_gbp_microunits, 0)
                 ELSE reserved_gbp_microunits END
        ), 0)
        FROM unpublished_graphiti_spend
        """
    ).fetchone()
    committed = int(row[0]) if row else 0
    if committed + reserved_gbp_microunits > ceiling_gbp_microunits:
        raise GraphitiSpendCeilingExceeded(
            "OD-011 Graphiti embedding cash ceiling would be exceeded"
        )
    connection.execute(
        """
        INSERT INTO unpublished_graphiti_spend(
            spend_id, ingest_id, attempt_number, reserved_gbp_microunits,
            proving_run_id, generation_id,
            actual_usd_microunits, actual_gbp_microunits, usage_basis,
            status, provider_usage_json, at
        ) VALUES(?,?,?,?,?,?,NULL,NULL,'PENDING_PROVIDER_REPORT','RESERVED',NULL,?)
        """,
        (
            spend_id,
            ingest_id,
            attempt_number,
            reserved_gbp_microunits,
            proving_run_id,
            generation_id,
            _now(),
        ),
    )
    return True


def next_graphiti_attempt_number(connection: sqlite3.Connection, ingest_id: str) -> int:
    row = connection.execute(
        """
        SELECT s.attempt_number, s.status,
               EXISTS(
                   SELECT 1 FROM unpublished_graphiti_attempt_receipts r
                   WHERE r.ingest_id=s.ingest_id
                     AND r.attempt_number=s.attempt_number
               ) AS has_receipt
        FROM unpublished_graphiti_spend s
        WHERE s.ingest_id=?
        ORDER BY s.attempt_number DESC
        LIMIT 1
        """,
        (ingest_id,),
    ).fetchone()
    if row is None:
        return 1
    attempt_number = int(row[0])
    if str(row[1]) == "RESERVED" and not bool(row[2]):
        # A process may have ended after the provider/Neo4j effect but before
        # its SQLite receipt. Re-enter that durable attempt identity first so
        # COMPLETE can be recovered or PENDING can be classified and charged.
        return attempt_number
    return attempt_number + 1


def claim_graphiti_attempt(
    connection: sqlite3.Connection,
    *,
    spend_id: str,
    generation_id: str,
    owner_id: str,
    claimed_at: str,
    lease_expires_at: str,
) -> bool:
    """Atomically claim one attempt across its whole Graphiti generation."""

    row = connection.execute(
        """
        UPDATE unpublished_graphiti_spend
        SET dispatch_owner=?, dispatch_lease_expires_at=?
        WHERE spend_id=? AND generation_id=? AND status='RESERVED'
          AND (
              dispatch_owner IS NULL
              OR dispatch_lease_expires_at IS NULL
              OR dispatch_lease_expires_at <= ?
          )
          AND NOT EXISTS (
              SELECT 1
              FROM unpublished_graphiti_spend AS active
              WHERE active.spend_id <> unpublished_graphiti_spend.spend_id
                AND (
                    active.generation_id = ?
                    OR active.generation_id IS NULL
                )
                AND active.dispatch_owner IS NOT NULL
                AND active.dispatch_lease_expires_at > ?
          )
        RETURNING spend_id
        """,
        (
            owner_id,
            lease_expires_at,
            spend_id,
            generation_id,
            claimed_at,
            generation_id,
            claimed_at,
        ),
    ).fetchone()
    return row is not None


def release_graphiti_attempt_claim(
    connection: sqlite3.Connection,
    *,
    spend_id: str,
    owner_id: str,
) -> bool:
    """Release only the caller's lease without changing unresolved spend."""

    row = connection.execute(
        """
        UPDATE unpublished_graphiti_spend
        SET dispatch_owner=NULL, dispatch_lease_expires_at=NULL, at=?
        WHERE spend_id=? AND status='RESERVED' AND dispatch_owner=?
        RETURNING spend_id
        """,
        (_now(), spend_id, owner_id),
    ).fetchone()
    return row is not None


def reconcile_graphiti_spend(
    connection: sqlite3.Connection,
    *,
    spend_id: str,
    embedding_usage: dict[str, object] | None,
) -> dict[str, object]:
    usage = embedding_usage or {}
    usage_basis = str(usage.get("usage_basis") or "UNREPORTED")
    raw_cost = usage.get("cost_usd_microunits")
    no_call = is_exact_no_embedding_call(embedding_usage)
    reported = is_exact_provider_reported_usage(embedding_usage)
    # Conservative versioned parity conversion until a separately accepted FX
    # table supersedes this policy: USD 1.00 reserves/debits GBP 1.00.
    fx_policy = "USD_GBP_CONSERVATIVE_PARITY_V1"
    actual_usd = 0 if no_call else (int(raw_cost) if reported else None)
    actual_gbp = actual_usd
    status = "RECONCILED" if reported or no_call else "UNRECONCILED"
    connection.execute(
        """
        UPDATE unpublished_graphiti_spend
        SET actual_usd_microunits=?, actual_gbp_microunits=?, usage_basis=?,
            status=?, provider_usage_json=?, dispatch_owner=NULL,
            dispatch_lease_expires_at=NULL, at=?
        WHERE spend_id=?
        """,
        (
            actual_usd,
            actual_gbp,
            usage_basis,
            status,
            json.dumps(usage, ensure_ascii=False, sort_keys=True),
            _now(),
            spend_id,
        ),
    )
    return {
        "spend_id": spend_id,
        "usage_basis": usage_basis,
        "status": status,
        "actual_usd_microunits": actual_usd,
        "actual_gbp_microunits": actual_gbp,
        "fx_policy": fx_policy,
        "unused_reservation_released": reported or no_call,
    }


def retain_graphiti_authority_records(
    connection: sqlite3.Connection,
    records: tuple[dict[str, object], ...],
) -> None:
    """Retain authority records and reject an identifier reused for new semantics."""

    for record in records:
        record_id = str(record.get("record_id") or "")
        record_type = str(record.get("record_type") or "")
        if not record_id or not record_type:
            raise ValueError("Graphiti authority record identity and type are required")
        record_json = canonical_json_bytes(record).decode("utf-8")
        record_digest = digest_bytes(record_json.encode("utf-8"))
        retained = connection.execute(
            "SELECT record_digest FROM unpublished_graphiti_authority_records "
            "WHERE record_id=?",
            (record_id,),
        ).fetchone()
        if retained is not None and str(retained[0]) != record_digest:
            raise ValueError("Graphiti authority record identity was reused")
        connection.execute(
            """
            INSERT OR IGNORE INTO unpublished_graphiti_authority_records(
                record_id, record_type, record_digest, record_json, retained_at
            ) VALUES(?,?,?,?,?)
            """,
            (record_id, record_type, record_digest, record_json, _now()),
        )


def insert_graphiti_attempt_receipt(
    connection: sqlite3.Connection,
    *,
    ingest_id: str,
    attempt_number: int,
    outcome: str,
    receipt: dict[str, object],
) -> str:
    value = dict(receipt)
    supplied_digest = value.pop("receipt_digest", None)
    receipt_digest = digest_bytes(canonical_json_bytes(value))
    if supplied_digest not in (None, "", receipt_digest):
        raise ValueError("Graphiti final receipt digest differs from retained receipt")
    value["receipt_digest"] = receipt_digest
    connection.execute(
        """
        INSERT INTO unpublished_graphiti_attempt_receipts(
            ingest_id, attempt_number, outcome, receipt_digest, receipt_json, at
        ) VALUES(?,?,?,?,?,?)
        """,
        (
            ingest_id,
            attempt_number,
            outcome,
            receipt_digest,
            json.dumps(value, ensure_ascii=False, sort_keys=True),
            _now(),
        ),
    )
    return receipt_digest


def _remapped_ingest_aliases(
    connection: sqlite3.Connection, new_ingest_id: str
) -> tuple[str, ...]:
    if not _sqlite_table_exists(connection, "unpublished_effective_revision_remap"):
        return ()
    columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(unpublished_effective_revision_remap)"
        )
    }
    if "new_ingest_id" not in columns:
        return ()
    return tuple(
        str(row[0])
        for row in connection.execute(
            "SELECT old_ingest_id FROM unpublished_effective_revision_remap "
            "WHERE new_ingest_id=? AND old_ingest_id IS NOT NULL "
            "AND old_ingest_id != ''",
            (new_ingest_id,),
        )
    )


def has_graphiti_ingest(connection: sqlite3.Connection, ingest_id: str) -> bool:
    ingest_ids = (ingest_id, *_remapped_ingest_aliases(connection, ingest_id))
    placeholders = ",".join("?" * len(ingest_ids))
    row = connection.execute(
        f"SELECT 1 FROM unpublished_graphiti_ingest "
        f"WHERE ingest_id IN ({placeholders}) LIMIT 1",
        ingest_ids,
    ).fetchone()
    return row is not None


def insert_graphiti_ingest(
    connection: sqlite3.Connection,
    *,
    ingest_id: str,
    source_id: str,
    item_key: str,
    outcome: str,
    proposal_count: int,
    entity_count: int,
    relation_count: int,
    failure_code: str,
    temporal_basis: str,
    reference_time: str,
    generation_id: str,
    receipt_digest: str,
    receipt: dict[str, object] | None = None,
) -> bool:
    if has_graphiti_ingest(connection, ingest_id):
        return False
    connection.execute(
        """
        INSERT INTO unpublished_graphiti_ingest(
            ingest_id, source_id, item_key, outcome, proposal_count, entity_count,
            relation_count, failure_code, temporal_basis, reference_time,
            generation_id, receipt_digest, at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            ingest_id,
            source_id,
            item_key,
            outcome,
            proposal_count,
            entity_count,
            relation_count,
            failure_code,
            temporal_basis,
            reference_time,
            generation_id,
            receipt_digest,
            _now(),
        ),
    )
    if receipt is not None:
        connection.execute(
            "INSERT INTO unpublished_graphiti_receipts(ingest_id, receipt_json) VALUES(?,?)",
            (ingest_id, json.dumps(receipt, ensure_ascii=False, sort_keys=True)),
        )
    return True


def graphiti_failure_state(
    connection: sqlite3.Connection, ingest_id: str
) -> tuple[int, bool]:
    ingest_ids = (ingest_id, *_remapped_ingest_aliases(connection, ingest_id))
    placeholders = ",".join("?" * len(ingest_ids))
    row = connection.execute(
        f"""
        SELECT COALESCE(MAX(retry_count), 0), COALESCE(MAX(dead_lettered), 0)
        FROM unpublished_graphiti_failures
        WHERE ingest_id IN ({placeholders})
        """,
        ingest_ids,
    ).fetchone()
    return int(row[0]), bool(row[1])


def record_graphiti_failure(
    connection: sqlite3.Connection,
    *,
    ingest_id: str,
    source_id: str,
    item_key: str,
    outcome: str,
    failure_code: str,
) -> int:
    previous, _dead = graphiti_failure_state(connection, ingest_id)
    retry_count = previous + 1
    dead = 1 if retry_count >= GRAPHITI_MAX_FAILURES else 0
    connection.execute(
        """
        INSERT INTO unpublished_graphiti_failures(
            ingest_id, source_id, item_key, retry_count, last_outcome,
            last_failure_code, dead_lettered, at
        ) VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(ingest_id) DO UPDATE SET
            retry_count=excluded.retry_count,
            last_outcome=excluded.last_outcome,
            last_failure_code=excluded.last_failure_code,
            dead_lettered=excluded.dead_lettered,
            at=excluded.at
        """,
        (
            ingest_id,
            source_id,
            item_key,
            retry_count,
            outcome,
            failure_code,
            dead,
            _now(),
        ),
    )
    return retry_count


def clear_graphiti_failure(connection: sqlite3.Connection, ingest_id: str) -> None:
    connection.execute(
        "DELETE FROM unpublished_graphiti_failures WHERE ingest_id=?",
        (ingest_id,),
    )


class CoverageGrainError(ValueError):
    """Coverage telemetry grains are negative or contradictory."""


def _non_negative_count(value: int, *, field: str) -> int:
    if type(value) is not int or value < 0:
        raise CoverageGrainError(f"{field} must be a non-negative integer")
    return value


def _coverage_query_ids(
    connection: sqlite3.Connection,
    revisions: tuple[EligibleCorpusRevision, ...],
) -> tuple[str, ...]:
    ids = {ingest_id for revision in revisions for ingest_id in revision.ingest_ids}
    wanted = set(ids)
    for (
        _source_id,
        _item_key,
        _revision_digest,
        _published_at,
        _updated_at,
        old_ingest_id,
        new_ingest_id,
    ) in list_remapped_ingest_effects(connection):
        if new_ingest_id in wanted:
            ids.add(old_ingest_id)
    return tuple(sorted(ids))


def _revision_is_ingested(
    revision: EligibleCorpusRevision,
    ingested_ids: set[str],
    remapped_ids: dict[str, tuple[str, ...]],
) -> bool:
    return bool(revision.ingest_ids) and all(
        ingest_id in ingested_ids
        or any(alias in ingested_ids for alias in remapped_ids.get(ingest_id, ()))
        for ingest_id in revision.ingest_ids
    )


def graphiti_coverage(
    connection: sqlite3.Connection,
    *,
    revisions: tuple[EligibleCorpusRevision, ...],
    retry_count: int | None = None,
    dead_letter_count: int | None = None,
    poll_observation_count: int | None = None,
    feed_snapshot_item_count: int | None = None,
) -> dict[str, object]:
    remapped_ids: dict[str, list[str]] = {}
    for (
        _source_id,
        _item_key,
        _revision_digest,
        _published_at,
        _updated_at,
        old_ingest_id,
        new_ingest_id,
    ) in list_remapped_ingest_effects(connection):
        remapped_ids.setdefault(new_ingest_id, []).append(old_ingest_id)
    remapped_tuples = {key: tuple(values) for key, values in remapped_ids.items()}
    eligible_ids = _coverage_query_ids(connection, revisions)
    ingested_ids: set[str] = set()
    proposal_counts: dict[str, int] = {}
    if eligible_ids:
        rows: list[tuple[object, ...]] = []
        for batch in _bind_batches(eligible_ids):
            placeholders = ",".join("?" * len(batch))
            rows.extend(
                connection.execute(
                    f"""
                    SELECT ingest_id, proposal_count FROM unpublished_graphiti_ingest
                    WHERE outcome IN ('COMPLETE','PARTIAL')
                      AND ingest_id IN ({placeholders})
                    """,
                    batch,
                ).fetchall()
            )
        ingested_ids = {row[0] for row in rows}
        proposal_counts = {str(row[0]): int(row[1]) for row in rows}
    successful = tuple(
        revision
        for revision in revisions
        if _revision_is_ingested(revision, ingested_ids, remapped_tuples)
    )
    successful_ids = {item.revision_id for item in successful}
    unresolved = tuple(
        item for item in revisions if item.revision_id not in successful_ids
    )
    contiguous = None
    for revision in revisions:
        if revision.revision_id not in successful_ids:
            break
        contiguous = revision
    payloads = connection.execute(
        "SELECT COUNT(*) FROM unpublished_surface_payloads"
    ).fetchone()[0]
    spend = connection.execute(
        """
        SELECT
          COALESCE(SUM(CASE WHEN status='RECONCILED' THEN actual_gbp_microunits ELSE 0 END),0),
          COALESCE(SUM(
            CASE WHEN status IN ('RESERVED','UNRECONCILED')
                 THEN reserved_gbp_microunits ELSE 0 END
          ),0),
          SUM(CASE WHEN status='UNRECONCILED' THEN 1 ELSE 0 END)
        FROM unpublished_graphiti_spend
        """
    ).fetchone()
    lags: list[int] = []
    for revision in unresolved:
        try:
            then = datetime.fromisoformat(revision.observed_at.replace("Z", "+00:00"))
            if then.tzinfo is None:
                then = then.replace(tzinfo=UTC)
            lags.append(max(int((datetime.now(tz=UTC) - then).total_seconds()), 0))
        except ValueError:
            continue
    failure_rows: list[tuple[str, int, int]] = []
    if eligible_ids:
        for batch in _bind_batches(eligible_ids):
            placeholders = ",".join("?" * len(batch))
            failure_rows.extend(
                (str(row[0]), int(row[1]), int(row[2]))
                for row in connection.execute(
                    f"""
                    SELECT ingest_id, retry_count, dead_lettered
                    FROM unpublished_graphiti_failures
                    WHERE ingest_id IN ({placeholders})
                    """,
                    batch,
                )
            )
    failed_ids = {row[0] for row in failure_rows}
    dead_ids = {row[0] for row in failure_rows if row[2] == 1}

    current_ingest_ids = tuple(
        ingest_id for revision in revisions for ingest_id in revision.ingest_ids
    )
    failure_states = {
        ingest_id: graphiti_failure_state(connection, ingest_id)
        for ingest_id in current_ingest_ids
    }
    if retry_count is None:
        retry_count = sum(state[0] for state in failure_states.values())

    def effect_ids(revision: EligibleCorpusRevision) -> set[str]:
        return {
            item
            for ingest_id in revision.ingest_ids
            for item in (ingest_id, *remapped_tuples.get(ingest_id, ()))
        }

    calculated_dead_revisions = sum(
        bool(effect_ids(revision) & dead_ids) for revision in unresolved
    )
    if dead_letter_count is None:
        dead_letter_count = calculated_dead_revisions
    held_or_failed = sum(
        bool(effect_ids(revision) & failed_ids) for revision in unresolved
    )
    p95_lag = sorted(lags)[max(math.ceil(len(lags) * 0.95) - 1, 0)] if lags else 0
    oldest_gap = unresolved[0] if unresolved else None
    effective_pull_count = len(revisions)
    coverage: dict[str, object] = {
        "effective_pull_count": effective_pull_count,
        "eligible_source_revisions": effective_pull_count,
        "eligible_ingest_chunks": sum(
            len(revision.ingest_ids) for revision in revisions
        ),
        "successfully_ingested_revisions": len(successful),
        "held_or_failed_revisions": held_or_failed,
        "unresolved_gap": len(unresolved),
        "contiguous_input_watermark": (
            None if contiguous is None else contiguous.revision_id
        ),
        "ingest_watermark_at": None if contiguous is None else contiguous.observed_at,
        "oldest_unresolved_gap": (
            None
            if oldest_gap is None
            else {
                "revision_id": oldest_gap.revision_id,
                "source_id": oldest_gap.source_id,
                "item_key": oldest_gap.item_key,
                "observed_at": oldest_gap.observed_at,
            }
        ),
        "latest_source_time_covered": (
            max(item.source_time for item in successful) if successful else None
        ),
        "oldest_ingest_lag_seconds": max(lags) if lags else 0,
        "p95_ingest_lag_seconds": p95_lag,
        "lag_seconds": max(lags) if lags else 0,
        "retry_count": retry_count,
        "retry_attempt_count": retry_count,
        "dead_letter_count": dead_letter_count,
        "dead_letter_revisions": dead_letter_count,
        "dead_letter_chunks": sum(state[1] for state in failure_states.values()),
        "admission_backlog": sum(proposal_counts.values()),
        "governed_projection_watermark": None,
        "reserved_spend": spend_reserved(connection),
        "outstanding_reserved_spend_gbp_microunits": int(spend[1]) if spend else 0,
        "actual_metered_spend_microunits": int(spend[0]) if spend else 0,
        "actual_metered_spend_gbp_microunits": int(spend[0]) if spend else 0,
        "unreconciled_embedding_attempts": int(spend[2]) if spend and spend[2] else 0,
        "unpublished_payload_count": payloads,
        "payload_count_is_not_coverage": True,
    }
    if poll_observation_count is not None:
        poll_count = _non_negative_count(
            poll_observation_count, field="poll_observation_count"
        )
        coverage["poll_observation_count"] = poll_count
    if feed_snapshot_item_count is not None:
        coverage["feed_snapshot_item_count"] = _non_negative_count(
            feed_snapshot_item_count, field="feed_snapshot_item_count"
        )
    return coverage


def record_graphiti_coverage(
    connection: sqlite3.Connection, coverage: dict[str, object]
) -> None:
    connection.execute(
        "INSERT INTO unpublished_graphiti_coverage(at, coverage_json) VALUES(?,?)",
        (_now(), json.dumps(coverage, ensure_ascii=False, sort_keys=True)),
    )


def has_candidate(connection: sqlite3.Connection, candidate_id: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM unpublished_surface_payloads WHERE story_candidate_id=?",
        (candidate_id,),
    ).fetchone()
    return row is not None


def insert_payload(
    connection: sqlite3.Connection, payload: UnpublishedSurfacePayload
) -> bool:
    if has_candidate(connection, payload.story_candidate_id):
        return False
    connection.execute(
        """
        INSERT INTO unpublished_surface_payloads(
            payload_id, payload_kind, publication_bundle, auto_publish, language,
            title, body, evidence_package_digest, story_candidate_id,
            event_hypothesis_id, source_lineage, generated_at, status, writer_id
        ) VALUES(?,?,0,0,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            payload.story_candidate_id,
            payload.payload_kind,
            payload.language,
            payload.title,
            payload.body,
            payload.evidence_package_digest,
            payload.story_candidate_id,
            payload.event_hypothesis_id,
            json.dumps(list(payload.source_lineage), ensure_ascii=False),
            payload.generated_at,
            payload.status,
            payload.writer_id,
        ),
    )
    return True


def list_payloads(
    path: str, *, limit: int = 100
) -> tuple[UnpublishedSurfacePayload, ...]:
    connection = connect(path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT payload_kind, publication_bundle, auto_publish, language, title, body,
                   evidence_package_digest, story_candidate_id, event_hypothesis_id,
                   source_lineage, generated_at, status, writer_id
            FROM unpublished_surface_payloads
            ORDER BY generated_at DESC, story_candidate_id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        connection.close()
    payloads: list[UnpublishedSurfacePayload] = []
    for row in rows:
        payloads.append(
            UnpublishedSurfacePayload(
                payload_kind=row["payload_kind"],
                publication_bundle=bool(row["publication_bundle"]),
                auto_publish=bool(row["auto_publish"]),
                language=row["language"],
                title=row["title"],
                body=row["body"],
                evidence_package_digest=row["evidence_package_digest"],
                story_candidate_id=row["story_candidate_id"],
                event_hypothesis_id=row["event_hypothesis_id"],
                source_lineage=tuple(json.loads(row["source_lineage"])),
                generated_at=row["generated_at"],
                status=row["status"],
                writer_id=row["writer_id"],
            )
        )
    return tuple(payloads)


def list_drafts(path: str, *, limit: int = 100) -> tuple[UnpublishedDraft, ...]:
    """Legacy sidecar reader. Destination UI must use list_payloads."""
    connection = connect(path)
    connection.row_factory = sqlite3.Row
    try:
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "unpublished_drafts" not in names:
            return ()
        rows = connection.execute(
            """
            SELECT draft_id, source_id, proving_run_id, observation_digest, item_key,
                   headline, body, canonical_url, observed_at, minted_at, status
            FROM unpublished_drafts
            ORDER BY minted_at DESC, draft_id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        connection.close()
    return tuple(UnpublishedDraft(**dict(row)) for row in rows)


def mark_public_dispatch(connection: sqlite3.Connection, draft_id: str) -> None:
    raise VetoError("public effect refused: PUBLIC_DISPATCH")
