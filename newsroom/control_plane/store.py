"""Unpublished Surface Payload store and append-only control ledger."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.control_plane.surface import UnpublishedSurfacePayload
from newsroom.control_plane.veto import VetoError, assert_private_store, refuse_public_effect

SCHEMA_VERSION = "newsroom.control-plane.unpublished.v5"
LEDGER_GENESIS = "sha256:" + ("0" * 64)
GRAPHITI_MAX_FAILURES = 3

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


def _now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def connect(path: str) -> sqlite3.Connection:
    assert_private_store(path)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(_PAYLOAD_SQL)
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
        "SELECT 1 FROM ledger WHERE kind='GRAPHITI_SPEND_RESERVE' LIMIT 1"
    ).fetchone()
    return row is not None


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
    eligible_ids: tuple[str, ...],
    observed_at: tuple[str, ...] = (),
    retry_count: int | None = None,
    dead_letter_count: int | None = None,
) -> dict[str, object]:
    eligible = len(eligible_ids)
    ingested_ids: set[str] = set()
    watermark_at: str | None = None
    if eligible_ids:
        placeholders = ",".join("?" * len(eligible_ids))
        rows = connection.execute(
            f"""
            SELECT ingest_id, at FROM unpublished_graphiti_ingest
            WHERE outcome IN ('COMPLETE','PARTIAL') AND ingest_id IN ({placeholders})
            """,
            eligible_ids,
        ).fetchall()
        ingested_ids = {row[0] for row in rows}
        times = [row[1] for row in rows if row[1]]
        watermark_at = max(times) if times else None
    payloads = connection.execute(
        "SELECT COUNT(*) FROM unpublished_surface_payloads"
    ).fetchone()[0]
    metered = 0
    for (blob,) in connection.execute(
        "SELECT receipt_json FROM unpublished_graphiti_receipts"
    ):
        try:
            payload = json.loads(blob)
        except json.JSONDecodeError:
            continue
        cost = payload.get("cost_microunits")
        if isinstance(cost, int) and cost > 0:
            metered += cost
    pending = [
        observed_at[index]
        for index, ingest_id in enumerate(eligible_ids)
        if ingest_id not in ingested_ids and index < len(observed_at)
    ]
    lag_seconds = 0
    if pending:
        try:
            oldest = min(pending)
            then = datetime.fromisoformat(oldest.replace("Z", "+00:00"))
            if then.tzinfo is None:
                then = then.replace(tzinfo=UTC)
            lag_seconds = max(int((datetime.now(tz=UTC) - then).total_seconds()), 0)
        except ValueError:
            lag_seconds = 0
    if retry_count is None:
        retry_row = connection.execute(
            "SELECT COALESCE(SUM(retry_count), 0) FROM unpublished_graphiti_failures"
        ).fetchone()
        retry_count = int(retry_row[0]) if retry_row else 0
    if dead_letter_count is None:
        dead_row = connection.execute(
            "SELECT COUNT(*) FROM unpublished_graphiti_failures WHERE dead_lettered=1"
        ).fetchone()
        dead_letter_count = int(dead_row[0]) if dead_row else 0
    return {
        "eligible_source_revisions": eligible,
        "successfully_ingested_revisions": len(ingested_ids),
        "unresolved_gap": eligible - len(ingested_ids),
        "ingest_watermark_at": watermark_at,
        "lag_seconds": lag_seconds,
        "retry_count": retry_count,
        "dead_letter_count": dead_letter_count,
        "admission_backlog": len(ingested_ids),
        "reserved_spend": spend_reserved(connection),
        "actual_metered_spend_microunits": metered,
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
