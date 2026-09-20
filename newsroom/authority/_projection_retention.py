"""Reconstruct dispensable retired no-op detail from retained authority."""
from __future__ import annotations

import sqlite3
import json

from .canonical import canonical_json_bytes, digest_bytes
from .persistence import AuthorityPersistenceError


RETIRED_IGNORED_STATE_ROWS = (
    "SELECT s.*,g.family_id,g.state AS generation_state,e.event_type,"
    "e.aggregate_type,e.aggregate_id,e.payload_digest AS event_payload_digest,"
    "e.payload_schema_version,p.mode,p.schema_version,p.payload_bytes,p.payload_digest "
    "FROM projection_delivery_states s "
    "JOIN projection_generations g ON g.generation_id=s.generation_id "
    "LEFT JOIN ledger_events e ON e.event_id=s.last_authority_event_id "
    "AND g.state='RETIRED' AND s.current_outcome='IGNORED_OPTIONAL' AND s.attempt_count=1 "
    "LEFT JOIN authority_payloads p ON p.payload_id=e.payload_id "
)


def retired_ignored_attempt(conn: sqlite3.Connection, event_id: str) -> dict | None:
    cursor = conn.execute(
        "SELECT e.event_type,e.aggregate_type,e.aggregate_id,"
        "e.payload_digest AS event_payload_digest,e.payload_schema_version,"
        "p.mode,p.schema_version,p.payload_bytes,p.payload_digest "
        "FROM ledger_events e LEFT JOIN authority_payloads p ON p.payload_id=e.payload_id "
        "WHERE e.event_id=?", (event_id,),
    )
    raw = cursor.fetchone()
    if raw is None:
        return None
    authority = dict(zip((column[0] for column in cursor.description), raw, strict=True))
    try:
        value = json.loads(authority["payload_bytes"])
        if type(value) is not dict or type(value.get("ledger_seq")) is not int:
            raise ValueError("delivery payload differs")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise AuthorityPersistenceError("retired ignored delivery authority differs") from exc
    # Start from the event primary key, then the state composite primary key.
    # A lookup by last_authority_event_id alone would scan all delivery states.
    cursor = conn.execute(
        "SELECT s.*,g.family_id,g.state AS generation_state "
        "FROM projection_delivery_states s "
        "JOIN projection_generations g ON g.generation_id=s.generation_id "
        "WHERE s.generation_id=? AND s.ledger_seq=? AND s.last_authority_event_id=?",
        (authority["aggregate_id"], value["ledger_seq"], event_id),
    )
    raw = cursor.fetchone()
    if raw is None:
        return None
    row = dict(zip((column[0] for column in cursor.description), raw, strict=True))
    row.update(authority)
    return retired_ignored_attempt_from_state(row)


def retired_ignored_attempt_from_state(row) -> dict | None:
    if (row["generation_state"] != "RETIRED" or row["current_outcome"] != "IGNORED_OPTIONAL"
            or row["attempt_count"] != 1 or row["required"] != 0
            or row["finalized"] != 1 or row["last_error_code"] is not None):
        return None
    expected = canonical_json_bytes({
        "generation_id": row["generation_id"], "ledger_seq": row["ledger_seq"],
        "outcome": "IGNORED_OPTIONAL", "error_code": None,
    })
    if (row["event_type"] != "projection.delivery.recorded"
            or row["aggregate_type"] != "projection_generation"
            or row["aggregate_id"] != row["generation_id"]
            or row["mode"] != "INLINE"
            or row["schema_version"] != "projection_delivery_record_v1"
            or row["payload_schema_version"] != row["schema_version"]
            or row["payload_bytes"] != expected
            or row["payload_digest"] != digest_bytes(expected)
            or row["event_payload_digest"] != row["payload_digest"]):
        raise AuthorityPersistenceError("retired ignored delivery authority differs")
    return {
        **{key: row[key] for key in (
            "generation_id", "family_id", "ledger_seq", "source_event_id",
            "source_event_digest", "source_event_type", "required",
        )},
        "outcome": "IGNORED_OPTIONAL", "attempt_number": 1, "error_code": None,
        "authority_event_id": row["last_authority_event_id"], "recorded_at": row["updated_at"],
    }
