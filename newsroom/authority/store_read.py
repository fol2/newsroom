from __future__ import annotations

from .models import AuditRecord, LedgerEvent
from .store_base import _EXPECTED_TABLES
from .types import TrustScope


class AuthorityStoreReadMixin:
    def get_current_version(self, aggregate_type: str, aggregate_id: str) -> int | None:
        row = self._conn.execute(
            "SELECT current_version FROM authority_aggregates "
            "WHERE aggregate_type = ? AND aggregate_id = ?",
            (aggregate_type, aggregate_id),
        ).fetchone()
        return None if row is None else int(row[0])

    def read_events(
        self, *, after_ledger_seq: int = 0, limit: int = 100
    ) -> tuple[LedgerEvent, ...]:
        if after_ledger_seq < 0 or limit <= 0 or limit > 10_000:
            raise ValueError("invalid event read bounds")
        rows = self._conn.execute(
            "SELECT * FROM ledger_events WHERE ledger_seq > ? "
            "ORDER BY ledger_seq ASC LIMIT ?",
            (after_ledger_seq, limit),
        ).fetchall()
        return tuple(self._row_to_event(row) for row in rows)

    @staticmethod
    def _row_to_event(row: object) -> LedgerEvent:
        return LedgerEvent(
            ledger_seq=int(row["ledger_seq"]),
            event_id=str(row["event_id"]),
            event_type=str(row["event_type"]),
            event_schema_version=int(row["event_schema_version"]),
            aggregate_type=str(row["aggregate_type"]),
            aggregate_id=str(row["aggregate_id"]),
            aggregate_version=int(row["aggregate_version"]),
            recorded_at=str(row["recorded_at"]),
            command_id=str(row["command_id"]),
            principal_id=str(row["principal_id"]),
            authentication_context_id=str(row["authentication_context_id"]),
            authorization_decision_id=str(row["authorization_decision_id"]),
            correlation_id=(
                None if row["correlation_id"] is None else str(row["correlation_id"])
            ),
            causation_id=(
                None if row["causation_id"] is None else str(row["causation_id"])
            ),
            producer_version=str(row["producer_version"]),
            payload_digest=str(row["payload_digest"]),
            payload_object_ref=(
                None
                if row["payload_object_ref"] is None
                else str(row["payload_object_ref"])
            ),
            security_scope=str(row["security_scope"]),
            retention_scope=str(row["retention_scope"]),
            trust_scope=TrustScope(str(row["trust_scope"])),
        )

    def read_audit_for_command(self, command_id: str) -> AuditRecord | None:
        row = self._conn.execute(
            "SELECT * FROM authority_audit_events WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        if row is None:
            return None
        return AuditRecord(
            audit_id=str(row["audit_id"]),
            command_id=str(row["command_id"]),
            event_type=str(row["event_type"]),
            principal_id=str(row["principal_id"]),
            authentication_context_id=str(row["authentication_context_id"]),
            authorization_decision_id=str(row["authorization_decision_id"]),
            authorization_policy_version=str(row["authorization_policy_version"]),
            effective_scope_digest=str(row["effective_scope_digest"]),
            semantic_request_digest=str(row["semantic_request_digest"]),
            detail_digest=str(row["detail_digest"]),
            recorded_at=str(row["recorded_at"]),
        )

    def table_count(self, table: str) -> int:
        if table not in _EXPECTED_TABLES:
            raise ValueError("unknown authority table")
        return int(self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
