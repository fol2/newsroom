"""Unpublished Surface Payload store and append-only control ledger."""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.control_plane.surface import UnpublishedSurfacePayload
from newsroom.control_plane.corpus import EligibleCorpusRevision
from newsroom.control_plane.veto import VetoError, assert_private_store, refuse_public_effect
from newsroom.graphiti_adapter.embedding_meter import is_exact_provider_reported_usage

SCHEMA_VERSION = "newsroom.control-plane.unpublished.v9"
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


def _now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def connect(path: str) -> sqlite3.Connection:
    assert_private_store(path)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(_PAYLOAD_SQL)
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
    row = connection.execute("SELECT digest FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
    return row[0] if row else LEDGER_GENESIS


def append_ledger(connection: sqlite3.Connection, kind: str, payload: dict[str, object]) -> str:
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


def next_graphiti_attempt_number(
    connection: sqlite3.Connection, ingest_id: str
) -> int:
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


def has_graphiti_ingest(connection: sqlite3.Connection, ingest_id: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM unpublished_graphiti_ingest WHERE ingest_id=?",
        (ingest_id,),
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
    row = connection.execute(
        """
        SELECT retry_count, dead_lettered
        FROM unpublished_graphiti_failures
        WHERE ingest_id=?
        """,
        (ingest_id,),
    ).fetchone()
    if row is None:
        return 0, False
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


def graphiti_coverage(
    connection: sqlite3.Connection,
    *,
    revisions: tuple[EligibleCorpusRevision, ...],
    retry_count: int | None = None,
    dead_letter_count: int | None = None,
) -> dict[str, object]:
    eligible_ids = tuple(
        ingest_id for revision in revisions for ingest_id in revision.ingest_ids
    )
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
        if all(ingest_id in ingested_ids for ingest_id in revision.ingest_ids)
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
    if retry_count is None:
        retry_count = sum(row[1] for row in failure_rows)
    failed_ids = {row[0] for row in failure_rows}
    dead_ids = {row[0] for row in failure_rows if row[2] == 1}
    calculated_dead_revisions = sum(
        any(ingest_id in dead_ids for ingest_id in revision.ingest_ids)
        for revision in unresolved
    )
    if dead_letter_count is None:
        dead_letter_count = calculated_dead_revisions
    held_or_failed = sum(
        any(ingest_id in failed_ids for ingest_id in revision.ingest_ids)
        for revision in unresolved
    )
    p95_lag = (
        sorted(lags)[max(math.ceil(len(lags) * 0.95) - 1, 0)] if lags else 0
    )
    oldest_gap = unresolved[0] if unresolved else None
    return {
        "eligible_source_revisions": len(revisions),
        "eligible_ingest_chunks": len(eligible_ids),
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
        "dead_letter_chunks": len(dead_ids),
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


def list_payloads(path: str, *, limit: int = 100) -> tuple[UnpublishedSurfacePayload, ...]:
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
