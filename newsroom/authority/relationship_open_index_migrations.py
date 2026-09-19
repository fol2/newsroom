"""Append-only v40 relationship-event coverage index."""

from __future__ import annotations

from dataclasses import dataclass

from .canonical import digest_canonical

RELATIONSHIP_OPEN_INDEX_SCHEMA_VERSION = 40
RELATIONSHIP_OPEN_INDEX_PREDECESSOR_SCHEMA_VERSION = 39
RELATIONSHIP_OPEN_INDEX_MIGRATION_NAME = "relationship_open_index_v40"


@dataclass(frozen=True, slots=True)
class RelationshipOpenIndexMigrationRecord:
    version: int
    name: str
    checksum: str


RELATIONSHIP_OPEN_INDEX_MIGRATION_STATEMENTS: tuple[str, ...] = (
    "CREATE INDEX idx_ledger_events_relationship_event_type "
    "ON ledger_events(event_id) "
    "WHERE event_type='event_hypothesis_relationship_decision_retained'",
)

RELATIONSHIP_OPEN_INDEX_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": RELATIONSHIP_OPEN_INDEX_SCHEMA_VERSION,
        "name": RELATIONSHIP_OPEN_INDEX_MIGRATION_NAME,
        "statements": list(RELATIONSHIP_OPEN_INDEX_MIGRATION_STATEMENTS),
    }
)
RELATIONSHIP_OPEN_INDEX_MIGRATION = (
    RelationshipOpenIndexMigrationRecord(
        RELATIONSHIP_OPEN_INDEX_SCHEMA_VERSION,
        RELATIONSHIP_OPEN_INDEX_MIGRATION_NAME,
        RELATIONSHIP_OPEN_INDEX_MIGRATION_CHECKSUM,
    )
)


__all__ = [
    name
    for name in globals()
    if name.startswith(("RELATIONSHIP_OPEN_INDEX_", "RelationshipOpenIndex"))
]
