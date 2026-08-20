"""Unpublished Surface Payload store and append-only control ledger."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.control_plane.surface import UnpublishedSurfacePayload
from newsroom.control_plane.veto import VetoError, assert_private_store, refuse_public_effect

SCHEMA_VERSION = "newsroom.control-plane.unpublished.v2"
LEDGER_GENESIS = "sha256:" + ("0" * 64)

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


def has_graphiti_attempt(connection: sqlite3.Connection, candidate_id: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM unpublished_graphiti_attempts WHERE story_candidate_id=?",
        (candidate_id,),
    ).fetchone()
    return row is not None


def insert_graphiti_attempt(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
    outcome: str,
    proposal_count: int,
    failure_code: str,
) -> bool:
    if has_graphiti_attempt(connection, candidate_id):
        return False
    connection.execute(
        """
        INSERT INTO unpublished_graphiti_attempts(
            story_candidate_id, outcome, proposal_count, failure_code, at
        ) VALUES(?,?,?,?,?)
        """,
        (candidate_id, outcome, proposal_count, failure_code, _now()),
    )
    return True


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
