from __future__ import annotations

import sqlite3

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.persistence import AuthorityPersistenceError, AuthoritySchemaError
from newsroom.entities.types import (
    CanonicalEntityId,
    EntityMentionId,
    EntityResolutionProposalId,
)


class _EntityIntegrityMixin:
    def _validate_schema_and_integrity(self) -> None:
        super()._validate_schema_and_integrity()
        self._validate_entity_integrity(self._connection)

    def _validate_entity_integrity(self, conn: sqlite3.Connection) -> None:
        try:
            for row in conn.execute(
                "SELECT * FROM entity_mentions ORDER BY mention_id"
            ).fetchall():
                self._mention_from_row(conn, row, replayed=False)
            for row in conn.execute(
                "SELECT * FROM entity_resolution_proposal_versions "
                "ORDER BY resolution_proposal_id,version_number"
            ).fetchall():
                self._proposal_version_from_row(conn, row, replayed=False)
            for row in conn.execute(
                "SELECT * FROM entity_resolution_decisions "
                "ORDER BY resolution_proposal_id,decision_version"
            ).fetchall():
                self._decision_from_row(conn, row, replayed=False)
            for row in conn.execute(
                "SELECT * FROM canonical_entities ORDER BY entity_id"
            ).fetchall():
                self._entity_from_row(conn, row)
            for row in conn.execute(
                "SELECT * FROM canonical_entity_versions "
                "ORDER BY entity_id,version_number"
            ).fetchall():
                self._entity_version_from_row(conn, row)
            for row in conn.execute(
                "SELECT * FROM entity_aliases ORDER BY alias_id"
            ).fetchall():
                self._alias_from_row(conn, row)
            self._validate_entity_heads(conn)
            self._validate_entity_resolution_rows(conn)
            self._validate_entity_projection_rows(conn)
            self._validate_entity_event_coverage(conn)
        except AuthoritySchemaError:
            raise
        except Exception as exc:
            raise AuthoritySchemaError("entity authority integrity validation failed") from exc

    @staticmethod
    def _validate_entity_heads(conn: sqlite3.Connection) -> None:
        bad = conn.execute(
            "SELECT h.resolution_proposal_id FROM entity_resolution_proposal_heads h "
            "LEFT JOIN entity_resolution_proposal_versions v "
            "ON v.resolution_proposal_id=h.resolution_proposal_id "
            "AND v.proposal_version_id=h.current_proposal_version_id "
            "AND v.version_number=h.current_version_number "
            "WHERE v.proposal_version_id IS NULL LIMIT 1"
        ).fetchone()
        if bad is not None:
            raise AuthoritySchemaError("resolution proposal head is inconsistent")
        bad = conn.execute(
            "SELECT h.resolution_proposal_id FROM entity_resolution_decision_heads h "
            "LEFT JOIN entity_resolution_decisions d "
            "ON d.resolution_proposal_id=h.resolution_proposal_id "
            "AND d.decision_id=h.current_decision_id "
            "AND d.decision_version=h.current_decision_version "
            "WHERE d.decision_id IS NULL OR h.current_state!=CASE d.action "
            "WHEN 'ACCEPT' THEN 'ACCEPTED' WHEN 'REJECT' THEN 'REJECTED' "
            "WHEN 'HOLD' THEN 'HELD' ELSE 'UNRESOLVED' END "
            "OR h.terminal!=(d.action IN('ACCEPT','REJECT')) LIMIT 1"
        ).fetchone()
        if bad is not None:
            raise AuthoritySchemaError("resolution decision head is inconsistent")
        bad = conn.execute(
            "SELECT h.entity_id FROM canonical_entity_heads h "
            "LEFT JOIN canonical_entity_versions v "
            "ON v.entity_id=h.entity_id "
            "AND v.entity_version_id=h.current_entity_version_id "
            "AND v.version_number=h.current_version_number "
            "WHERE v.entity_version_id IS NULL OR v.lifecycle!=h.lifecycle LIMIT 1"
        ).fetchone()
        if bad is not None:
            raise AuthoritySchemaError("canonical entity head is inconsistent")

    @staticmethod
    def _validate_entity_resolution_rows(conn: sqlite3.Connection) -> None:
        for row in conn.execute(
            "SELECT * FROM entity_mention_resolutions ORDER BY mention_id,decision_id"
        ).fetchall():
            value = {
                "mention_id": str(row["mention_id"]),
                "decision_id": str(row["decision_id"]),
                "resolution_proposal_id": str(row["resolution_proposal_id"]),
                "entity_id": str(row["entity_id"]),
                "entity_version_id": str(row["entity_version_id"]),
                "alias_id": str(row["alias_id"]),
                "admitted_at": str(row["admitted_at"]),
            }
            data = canonical_json_bytes(value)
            if data != bytes(row["canonical_bytes"]) or digest_bytes(data) != str(
                row["canonical_digest"]
            ):
                raise AuthoritySchemaError(
                    "entity mention resolution canonical bytes differ"
                )
        duplicate = conn.execute(
            "SELECT mention_id,COUNT(*) FROM entity_mention_resolutions "
            "GROUP BY mention_id HAVING COUNT(*)>1 LIMIT 1"
        ).fetchone()
        if duplicate is not None:
            raise AuthoritySchemaError(
                "one mention cannot have multiple admitted resolutions before lineage reversal"
            )

    @staticmethod
    def _validate_entity_projection_rows(conn: sqlite3.Connection) -> None:
        stale = conn.execute(
            "SELECT p.entity_id FROM entity_preferred_identities p "
            "JOIN canonical_entity_heads h ON h.entity_id=p.entity_id "
            "WHERE p.current_entity_version_id!=h.current_entity_version_id "
            "OR p.lifecycle!=h.lifecycle "
            "OR p.projected_through_ledger_seq>(SELECT COALESCE(MAX(ledger_seq),0) FROM ledger_events) "
            "LIMIT 1"
        ).fetchone()
        if stale is not None:
            raise AuthoritySchemaError("preferred entity projection is inconsistent")
        for row in conn.execute(
            "SELECT * FROM entity_projection_events ORDER BY source_ledger_seq,projection_event_id"
        ).fetchall():
            value = {
                "projection_event_id": str(row["projection_event_id"]),
                "source_event_id": str(row["source_event_id"]),
                "source_ledger_seq": int(row["source_ledger_seq"]),
                "action": str(row["action"]),
                "entity_id": str(row["entity_id"]),
                "entity_version_id": str(row["entity_version_id"]),
                "preferred_entity_id": (
                    None
                    if row["preferred_entity_id"] is None
                    else str(row["preferred_entity_id"])
                ),
                "lifecycle": str(row["lifecycle"]),
            }
            data = canonical_json_bytes(value)
            if data != bytes(row["canonical_bytes"]) or digest_bytes(data) != str(
                row["canonical_digest"]
            ):
                raise AuthoritySchemaError("entity projection event canonical bytes differ")
            event = conn.execute(
                "SELECT ledger_seq FROM ledger_events WHERE event_id=?",
                (str(row["source_event_id"]),),
            ).fetchone()
            if event is None or int(event["ledger_seq"]) != int(row["source_ledger_seq"]):
                raise AuthoritySchemaError("entity projection event source differs")

    @staticmethod
    def _validate_entity_event_coverage(conn: sqlite3.Connection) -> None:
        checks = (
            ("entity.mention.admitted", "entity_mentions"),
            ("entity.resolution.proposed", "entity_resolution_proposal_versions"),
            ("entity.resolution.decided", "entity_resolution_decisions"),
        )
        for event_type, table in checks:
            missing = conn.execute(
                f"SELECT e.event_id FROM ledger_events e LEFT JOIN {table} r "
                "ON r.authority_event_id=e.event_id "
                "WHERE e.event_type=? AND r.authority_event_id IS NULL LIMIT 1",
                (event_type,),
            ).fetchone()
            if missing is not None:
                raise AuthoritySchemaError(
                    f"{event_type} event lacks its typed entity record"
                )
            duplicate = conn.execute(
                f"SELECT authority_event_id,COUNT(*) FROM {table} "
                "GROUP BY authority_event_id HAVING COUNT(*)!=1 LIMIT 1"
            ).fetchone()
            if duplicate is not None:
                raise AuthoritySchemaError(
                    f"{event_type} event maps to multiple typed entity records"
                )


__all__ = ["_EntityIntegrityMixin"]
