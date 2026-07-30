from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.persistence import (
    AuthorityPersistenceError,
    AuthoritySchemaError,
)
from newsroom.authority.types import EventId, UtcTimestamp
from newsroom.entities.models import EntityPreferredIdentity, EntityProjectionEvent
from newsroom.entities.types import (
    CanonicalEntityId,
    CanonicalEntityLifecycle,
    CanonicalEntityVersionId,
    EntityLineageDecisionKind,
    EntityProjectionAction,
)


@dataclass(frozen=True, slots=True)
class _ExpectedPreferredProjection:
    value: EntityPreferredIdentity
    updated_at: UtcTimestamp


class _EntityProjectionMixin:
    @staticmethod
    def _projection_event_from_row(
        conn: sqlite3.Connection, row: sqlite3.Row
    ) -> EntityProjectionEvent:
        source = conn.execute(
            "SELECT ledger_seq FROM ledger_events WHERE event_id=?",
            (str(row["source_event_id"]),),
        ).fetchone()
        if source is None or int(source["ledger_seq"]) != int(
            row["source_ledger_seq"]
        ):
            raise AuthorityPersistenceError(
                "entity projection event source differs from ledger authority"
            )
        result = EntityProjectionEvent(
            projection_event_id=EventId.parse(str(row["projection_event_id"])),
            source_event_id=EventId.parse(str(row["source_event_id"])),
            source_ledger_seq=int(row["source_ledger_seq"]),
            action=EntityProjectionAction(str(row["action"])),
            entity_id=CanonicalEntityId.parse(str(row["entity_id"])),
            entity_version_id=CanonicalEntityVersionId.parse(
                str(row["entity_version_id"])
            ),
            preferred_entity_id=(
                None
                if row["preferred_entity_id"] is None
                else CanonicalEntityId.parse(str(row["preferred_entity_id"]))
            ),
            lifecycle=CanonicalEntityLifecycle(str(row["lifecycle"])),
            recorded_at=UtcTimestamp.parse(str(row["recorded_at"])),
        )
        data = canonical_json_bytes(result.canonical_value())
        if data != bytes(row["canonical_bytes"]) or digest_bytes(data) != str(
            row["canonical_digest"]
        ):
            raise AuthorityPersistenceError(
                "entity projection event canonical bytes differ"
            )
        return result

    def projection_events_after(
        self, *, after_ledger_seq: int, limit: int
    ) -> tuple[EntityProjectionEvent, ...]:
        if (
            isinstance(after_ledger_seq, bool)
            or not isinstance(after_ledger_seq, int)
            or after_ledger_seq < 0
        ):
            raise ValueError("entity projection event cutoff must be non-negative")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit <= 0
            or limit > 10_000
        ):
            raise ValueError("entity projection event limit is invalid")
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM entity_projection_events "
                "WHERE source_ledger_seq>? "
                "ORDER BY source_ledger_seq,projection_event_id LIMIT ?",
                (after_ledger_seq, limit),
            ).fetchall()
            events: list[EntityProjectionEvent] = []
            for row in rows:
                event = self._projection_event_from_row(self._connection, row)
                self._require_entity_current(self._connection, event.entity_id)
                events.append(event)
            return tuple(events)

    @staticmethod
    def _expected_preferred_projection(
        conn: sqlite3.Connection,
    ) -> tuple[_ExpectedPreferredProjection, ...]:
        rows = conn.execute(
            "SELECT h.entity_id,h.current_entity_version_id,h.lifecycle,"
            "v.lineage_decision_kind,v.lineage_decision_id,"
            "p.entity_version_id AS projected_entity_version_id,"
            "p.preferred_entity_id,p.lifecycle AS projected_lifecycle,"
            "p.source_ledger_seq,p.recorded_at "
            "FROM canonical_entity_heads h "
            "JOIN canonical_entity_versions v "
            "ON v.entity_id=h.entity_id "
            "AND v.entity_version_id=h.current_entity_version_id "
            "JOIN entity_projection_events p ON p.entity_id=h.entity_id "
            "AND p.source_ledger_seq=("
            "SELECT MAX(p2.source_ledger_seq) FROM entity_projection_events p2 "
            "WHERE p2.entity_id=h.entity_id"
            ") ORDER BY h.entity_id"
        ).fetchall()
        head_count = int(
            conn.execute("SELECT COUNT(*) FROM canonical_entity_heads").fetchone()[0]
        )
        if len(rows) != head_count:
            raise AuthoritySchemaError(
                "canonical entity head lacks a latest projection event"
            )
        expected: list[_ExpectedPreferredProjection] = []
        for row in rows:
            if (
                str(row["projected_entity_version_id"])
                != str(row["current_entity_version_id"])
                or str(row["projected_lifecycle"]) != str(row["lifecycle"])
                or row["preferred_entity_id"] is None
            ):
                raise AuthoritySchemaError(
                    "latest entity projection event differs from current authority"
                )
            expected.append(
                _ExpectedPreferredProjection(
                    EntityPreferredIdentity(
                        entity_id=CanonicalEntityId.parse(str(row["entity_id"])),
                        current_entity_version_id=CanonicalEntityVersionId.parse(
                            str(row["current_entity_version_id"])
                        ),
                        preferred_entity_id=CanonicalEntityId.parse(
                            str(row["preferred_entity_id"])
                        ),
                        lifecycle=CanonicalEntityLifecycle(str(row["lifecycle"])),
                        decided_by_kind=(
                            None
                            if row["lineage_decision_kind"] is None
                            else EntityLineageDecisionKind(
                                str(row["lineage_decision_kind"])
                            )
                        ),
                        decided_by_id=(
                            None
                            if row["lineage_decision_id"] is None
                            else str(row["lineage_decision_id"])
                        ),
                        projected_through_ledger_seq=int(row["source_ledger_seq"]),
                    ),
                    UtcTimestamp.parse(str(row["recorded_at"])),
                )
            )
        return tuple(expected)

    @staticmethod
    def _preferred_row_matches(
        row: sqlite3.Row, expected: _ExpectedPreferredProjection
    ) -> bool:
        value = expected.value
        return (
            str(row["entity_id"]) == str(value.entity_id)
            and str(row["current_entity_version_id"])
            == str(value.current_entity_version_id)
            and str(row["preferred_entity_id"]) == str(value.preferred_entity_id)
            and str(row["lifecycle"]) == value.lifecycle.value
            and (
                None
                if row["decided_by_kind"] is None
                else str(row["decided_by_kind"])
            )
            == (
                None
                if value.decided_by_kind is None
                else value.decided_by_kind.value
            )
            and (
                None if row["decided_by_id"] is None else str(row["decided_by_id"])
            )
            == value.decided_by_id
            and int(row["projected_through_ledger_seq"])
            == value.projected_through_ledger_seq
            and str(row["updated_at"]) == expected.updated_at.to_text()
        )

    def rebuild_preferred_projection(self) -> tuple[EntityPreferredIdentity, ...]:
        """Recreate only missing preferred rows from immutable authority history.

        Existing divergent projection rows are never overwritten.  Every current
        entity is rights-revalidated before the first insert so prohibited source
        material cannot be resurrected by a projection rebuild.
        """

        if not self._allow_projection_rebuild:
            raise PermissionError(
                "preferred entity projection rebuild is not enabled"
            )
        with self._lock, self._transaction() as conn:
            expected = self._expected_preferred_projection(conn)
            for item in expected:
                self._require_entity_current(conn, item.value.entity_id)

            existing_rows = {
                str(row["entity_id"]): row
                for row in conn.execute(
                    "SELECT * FROM entity_preferred_identities ORDER BY entity_id"
                ).fetchall()
            }
            expected_ids = {str(item.value.entity_id) for item in expected}
            if set(existing_rows) - expected_ids:
                raise AuthoritySchemaError(
                    "preferred entity projection contains unknown identities"
                )
            for item in expected:
                entity_id = str(item.value.entity_id)
                existing = existing_rows.get(entity_id)
                if existing is not None:
                    if not self._preferred_row_matches(existing, item):
                        raise AuthoritySchemaError(
                            "existing preferred entity projection differs from rebuild"
                        )
                    continue
                value = item.value
                conn.execute(
                    "INSERT INTO entity_preferred_identities("
                    "entity_id,current_entity_version_id,preferred_entity_id,"
                    "lifecycle,decided_by_kind,decided_by_id,"
                    "projected_through_ledger_seq,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (
                        entity_id,
                        str(value.current_entity_version_id),
                        str(value.preferred_entity_id),
                        value.lifecycle.value,
                        (
                            None
                            if value.decided_by_kind is None
                            else value.decided_by_kind.value
                        ),
                        value.decided_by_id,
                        value.projected_through_ledger_seq,
                        item.updated_at.to_text(),
                    ),
                )
            return tuple(item.value for item in expected)


__all__ = ["_EntityProjectionMixin"]
