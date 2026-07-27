from __future__ import annotations

import sqlite3

from newsroom.authority._check_store_support import _CHECK_RECORD_SPECS
from newsroom.authority.persistence import AuthorityPersistenceError
from newsroom.sources import SourceDefinitionId, SourceDefinitionVersionId


_TABLE_BY_COMMAND = {
    "check.request.register": "check_requests",
    "check.attempt.start": "check_attempts",
    "check.outcome.record": "check_outcomes",
    "check.baseline.decide": "baseline_decisions",
    "source.observable_transition.record": "observable_transitions",
    "operational.finding.open": "operational_findings",
    "operational.finding.occurrence.record": (
        "operational_finding_occurrences"
    ),
}


class _CheckIntegrityMixin:
    def _validate_schema_and_integrity(self) -> None:
        super()._validate_schema_and_integrity()
        conn = self._connection
        self._validate_check_records(conn)
        self._validate_attempt_chains(conn)
        self._validate_baseline_heads(conn)
        self._validate_occurrence_links(conn)
        self._validate_check_event_coverage(conn)

    def _validate_check_records(self, conn: sqlite3.Connection) -> None:
        for row in conn.execute("SELECT * FROM check_requests").fetchall():
            record = self._check_request_from_row(conn, row, replayed=False)
            request = record.request
            version = self._version_row(conn, request.definition_version_id)
            if (
                str(version["definition_id"]) != str(request.definition_id)
                or str(version["rights_decision_id"])
                != request.rights_decision_id
                or str(version["rights_policy_version"])
                != request.rights_policy_version
                or str(version["baseline_policy_id"])
                != request.baseline_policy.policy_id
                or str(version["baseline_policy_version"])
                != request.baseline_policy.policy_version
                or str(version["revision_policy_id"])
                != request.revision_policy.policy_id
                or str(version["revision_policy_version"])
                != request.revision_policy.policy_version
            ):
                raise AuthorityPersistenceError(
                    "Check Request source contract is inconsistent"
                )
            coverage = conn.execute(
                "SELECT 1 FROM source_version_coverage_mappings "
                "WHERE version_id=? AND obligation_id=? "
                "AND responsibility=? AND contribution=?",
                (
                    str(request.definition_version_id),
                    request.coverage.obligation_id,
                    request.coverage.responsibility.value,
                    request.coverage.contribution.value,
                ),
            ).fetchone()
            if coverage is None:
                raise AuthorityPersistenceError(
                    "Check Request coverage contract is inconsistent"
                )

        for row in conn.execute("SELECT * FROM check_attempts").fetchall():
            record = self._check_attempt_from_row(conn, row, replayed=False)
            parent = self._check_request_row(
                conn, str(record.request.request_id)
            )
            if (
                str(parent["adapter_request_digest"])
                != record.request.adapter_request_digest
            ):
                raise AuthorityPersistenceError(
                    "Check Attempt adapter contract is inconsistent"
                )

        for row in conn.execute("SELECT * FROM check_outcomes").fetchall():
            record = self._check_outcome_from_row(conn, row, replayed=False)
            request = record.request
            attempt = self._check_attempt_row(conn, str(request.attempt_id))
            parent = self._check_request_row(conn, str(request.request_id))
            if (
                str(attempt["request_id"]) != str(request.request_id)
                or str(parent["definition_id"]) != str(request.definition_id)
                or str(parent["definition_version_id"])
                != str(request.definition_version_id)
                or request.completed_at.to_text() < str(attempt["started_at"])
            ):
                raise AuthorityPersistenceError(
                    "Check Outcome lineage or chronology is inconsistent"
                )

        for row in conn.execute("SELECT * FROM baseline_decisions").fetchall():
            record = self._baseline_decision_from_row(
                conn, row, replayed=False
            )
            request = record.request
            version = self._version_row(conn, request.definition_version_id)
            parent = self._check_request_row(
                conn, str(request.check_request_id)
            )
            outcome = self._check_outcome_row(
                conn, str(request.check_outcome_id)
            )
            if (
                str(version["definition_id"]) != str(request.definition_id)
                or str(version["observation_model"])
                != request.observation_model.value
                or str(version["baseline_policy_id"])
                != request.baseline_policy.policy_id
                or str(version["baseline_policy_version"])
                != request.baseline_policy.policy_version
                or str(parent["definition_id"]) != str(request.definition_id)
                or str(parent["definition_version_id"])
                != str(request.definition_version_id)
                or str(outcome["request_id"])
                != str(request.check_request_id)
            ):
                raise AuthorityPersistenceError(
                    "Baseline Decision source lineage is inconsistent"
                )

        for row in conn.execute(
            "SELECT * FROM observable_transitions"
        ).fetchall():
            record = self._observable_transition_from_row(
                conn, row, replayed=False
            )
            request = record.request
            version = self._version_row(conn, request.definition_version_id)
            outcome = self._check_outcome_row(
                conn, str(request.check_outcome_id)
            )
            item = self._item_row(conn, str(request.item_id))
            parent = self._check_request_row(conn, str(outcome["request_id"]))
            if (
                str(version["definition_id"]) != str(request.definition_id)
                or str(version["observation_model"])
                != request.observation_model.value
                or str(outcome["definition_id"])
                != str(request.definition_id)
                or str(outcome["definition_version_id"])
                != str(request.definition_version_id)
                or str(item["definition_id"]) != str(request.definition_id)
                or str(parent["transition_policy_id"])
                != request.transition_policy.policy_id
                or str(parent["transition_policy_version"])
                != request.transition_policy.policy_version
            ):
                raise AuthorityPersistenceError(
                    "Observable Transition source lineage is inconsistent"
                )

        for row in conn.execute("SELECT * FROM operational_findings").fetchall():
            record = self._operational_finding_from_row(
                conn, row, replayed=False
            )
            self._validate_finding_lineage(conn, record.request)

        for row in conn.execute(
            "SELECT * FROM operational_finding_occurrences"
        ).fetchall():
            record = self._finding_occurrence_from_row(
                conn, row, replayed=False
            )
            self._operational_finding_row(
                conn, str(record.request.finding_id)
            )
            self._validate_finding_lineage(conn, record.request)

    def _validate_finding_lineage(self, conn, request) -> None:
        request_id = getattr(request, "opened_by_request_id", None)
        attempt_id = getattr(request, "opened_by_attempt_id", None)
        outcome_id = getattr(request, "opened_by_outcome_id", None)
        if not hasattr(request, "opened_by_request_id"):
            request_id = request.request_id
            attempt_id = request.attempt_id
            outcome_id = request.outcome_id
        parent_request = None
        if request_id is not None:
            parent_request = self._check_request_row(conn, str(request_id))
        if attempt_id is not None:
            attempt = self._check_attempt_row(conn, str(attempt_id))
            if (
                parent_request is not None
                and str(attempt["request_id"]) != str(request_id)
            ):
                raise AuthorityPersistenceError(
                    "Operational Finding Attempt lineage is inconsistent"
                )
            if parent_request is None:
                parent_request = self._check_request_row(
                    conn, str(attempt["request_id"])
                )
        if outcome_id is not None:
            outcome = self._check_outcome_row(conn, str(outcome_id))
            if request_id is not None and str(outcome["request_id"]) != str(
                request_id
            ):
                raise AuthorityPersistenceError(
                    "Operational Finding Outcome lineage is inconsistent"
                )
            if attempt_id is not None and str(outcome["attempt_id"]) != str(
                attempt_id
            ):
                raise AuthorityPersistenceError(
                    "Operational Finding Outcome/Attempt lineage is inconsistent"
                )

    @staticmethod
    def _validate_attempt_chains(conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            "SELECT request_id,attempt_id,attempt_number,prior_attempt_id "
            "FROM check_attempts ORDER BY request_id,attempt_number"
        ).fetchall()
        prior_by_request: dict[str, tuple[int, str]] = {}
        for row in rows:
            request_id = str(row["request_id"])
            attempt_id = str(row["attempt_id"])
            number = int(row["attempt_number"])
            previous = prior_by_request.get(request_id)
            expected_number = 1 if previous is None else previous[0] + 1
            expected_id = None if previous is None else previous[1]
            actual_id = (
                None
                if row["prior_attempt_id"] is None
                else str(row["prior_attempt_id"])
            )
            if number != expected_number or actual_id != expected_id:
                raise AuthorityPersistenceError(
                    "Check Attempt chain is not contiguous"
                )
            prior_by_request[request_id] = (number, attempt_id)

    @staticmethod
    def _validate_baseline_heads(conn: sqlite3.Connection) -> None:
        definitions = conn.execute(
            "SELECT DISTINCT definition_id FROM baseline_decisions"
        ).fetchall()
        for definition in definitions:
            definition_id = str(definition["definition_id"])
            rows = conn.execute(
                "SELECT d.decision_id,d.kind,d.previous_decision_id,e.ledger_seq "
                "FROM baseline_decisions d "
                "JOIN ledger_events e ON e.event_id=d.authority_event_id "
                "WHERE d.definition_id=? ORDER BY e.ledger_seq",
                (definition_id,),
            ).fetchall()
            prior = None
            for index, row in enumerate(rows):
                actual = (
                    None
                    if row["previous_decision_id"] is None
                    else str(row["previous_decision_id"])
                )
                if index == 0:
                    if str(row["kind"]) != "ESTABLISH" or actual is not None:
                        raise AuthorityPersistenceError(
                            "baseline lineage does not begin with establishment"
                        )
                elif actual != prior or str(row["kind"]) == "ESTABLISH":
                    raise AuthorityPersistenceError(
                        "baseline lineage does not extend exact predecessor"
                    )
                prior = str(row["decision_id"])
            head = conn.execute(
                "SELECT current_decision_id FROM baseline_decision_heads "
                "WHERE definition_id=?",
                (definition_id,),
            ).fetchone()
            if head is None or str(head["current_decision_id"]) != prior:
                raise AuthorityPersistenceError(
                    "baseline head differs from retained decision history"
                )
        orphan = conn.execute(
            "SELECT 1 FROM baseline_decision_heads h "
            "LEFT JOIN baseline_decisions d "
            "ON d.decision_id=h.current_decision_id "
            "WHERE d.decision_id IS NULL LIMIT 1"
        ).fetchone()
        if orphan is not None:
            raise AuthorityPersistenceError("baseline head is orphaned")

    @staticmethod
    def _validate_occurrence_links(conn: sqlite3.Connection) -> None:
        missing = conn.execute(
            "SELECT o.occurrence_id FROM discovery_occurrences o "
            "JOIN check_outcomes c ON c.outcome_id=o.check_outcome_id "
            "LEFT JOIN discovery_occurrence_check_links l "
            "ON l.occurrence_id=o.occurrence_id "
            "WHERE l.occurrence_id IS NULL LIMIT 1"
        ).fetchone()
        if missing is not None:
            raise AuthorityPersistenceError(
                "post-v11 discovery occurrence lacks exact Check link"
            )
        mismatch = conn.execute(
            "SELECT 1 FROM discovery_occurrence_check_links l "
            "JOIN discovery_occurrences o ON o.occurrence_id=l.occurrence_id "
            "WHERE o.check_outcome_id!=l.check_outcome_id LIMIT 1"
        ).fetchone()
        if mismatch is not None:
            raise AuthorityPersistenceError(
                "discovery occurrence Check link is inconsistent"
            )

    @staticmethod
    def _validate_check_event_coverage(conn: sqlite3.Connection) -> None:
        for command_type, (_, event_type, _) in _CHECK_RECORD_SPECS.items():
            table = _TABLE_BY_COMMAND[command_type]
            events = {
                str(row[0])
                for row in conn.execute(
                    "SELECT event_id FROM ledger_events WHERE event_type=?",
                    (event_type,),
                ).fetchall()
            }
            rows = {
                str(row[0])
                for row in conn.execute(
                    f"SELECT authority_event_id FROM {table}"
                ).fetchall()
            }
            if events != rows:
                raise AuthorityPersistenceError(
                    f"{command_type} ledger coverage differs from typed records"
                )


__all__ = ["_CheckIntegrityMixin"]
