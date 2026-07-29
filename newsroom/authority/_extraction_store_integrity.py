from __future__ import annotations

import sqlite3

from newsroom.authority.canonical import digest_bytes
from newsroom.authority.persistence import (
    AuthorityPersistenceError,
    AuthoritySchemaError,
)
from newsroom.extraction.decoding import (
    extraction_attempt_from_value,
    extraction_output_from_value,
    extraction_run_from_value,
    extractor_contract_from_value,
    proposal_set_from_value,
)
from newsroom.extraction.types import (
    ExtractionAttemptOutcome,
    ExtractionExecutionProfile,
    RUNTIME_AUTHORITY_DISABLED,
)

_EXTRACTION_TABLES = frozenset(
    {
        "extractor_contracts",
        "extractor_contract_heads",
        "extraction_runs",
        "extraction_passages",
        "extraction_attempts",
        "extraction_attempt_heads",
        "extraction_outputs",
        "extraction_proposal_sets",
        "extraction_proposals",
        "extraction_proposal_passages",
    }
)


class _ExtractionIntegrityMixin:
    """Re-derive every Increment 4A record and cross-record authority invariant."""

    def _validate_schema_and_integrity(self) -> None:
        super()._validate_schema_and_integrity()
        conn = self._connection
        missing = _EXTRACTION_TABLES - self._table_names()
        if missing:
            raise AuthoritySchemaError(
                f"extraction authority schema tables are missing: {sorted(missing)!r}"
            )
        if conn.execute(
            "SELECT 1 FROM extractor_contracts WHERE runtime_authority!=? LIMIT 1",
            (RUNTIME_AUTHORITY_DISABLED,),
        ).fetchone() is not None:
            raise AuthoritySchemaError(
                "extraction authority contains an executable runtime contract"
            )
        self._validate_extraction_records(conn)
        self._validate_contract_heads(conn)
        self._validate_run_lineage_history(conn)
        self._validate_attempt_chains(conn)
        self._validate_output_and_proposal_lineage(conn)
        self._validate_extraction_event_coverage(conn)

    def _validate_extraction_records(self, conn: sqlite3.Connection) -> None:
        for row in conn.execute(
            "SELECT * FROM extractor_contracts ORDER BY contract_family,version_number"
        ).fetchall():
            self._contract_from_row(conn, row, replayed=False)
        for row in conn.execute(
            "SELECT * FROM extraction_runs ORDER BY recorded_at,run_id"
        ).fetchall():
            self._run_from_row(conn, row, replayed=False)
        for row in conn.execute(
            "SELECT * FROM extraction_attempts ORDER BY run_id,attempt_number"
        ).fetchall():
            self._attempt_from_row(conn, row, replayed=False)
        for row in conn.execute(
            "SELECT * FROM extraction_outputs ORDER BY recorded_at,output_id"
        ).fetchall():
            self._output_from_row(conn, row, replayed=False)
        for row in conn.execute(
            "SELECT * FROM extraction_proposal_sets "
            "ORDER BY recorded_at,proposal_set_id"
        ).fetchall():
            self._proposal_set_from_row(conn, row, replayed=False)

    @staticmethod
    def _contract_was_current_at_event(
        conn: sqlite3.Connection,
        *,
        contract_id: str,
        record_event_id: str,
    ) -> bool:
        row = conn.execute(
            "SELECT c.contract_family,c.version_number,ce.ledger_seq AS contract_seq,"
            "re.ledger_seq AS record_seq "
            "FROM extractor_contracts c "
            "JOIN ledger_events ce ON ce.event_id=c.authority_event_id "
            "JOIN ledger_events re ON re.event_id=? "
            "WHERE c.contract_id=?",
            (record_event_id, contract_id),
        ).fetchone()
        if row is None or int(row["contract_seq"]) > int(row["record_seq"]):
            return False
        successor = conn.execute(
            "SELECT MIN(e.ledger_seq) AS next_seq "
            "FROM extractor_contracts c "
            "JOIN ledger_events e ON e.event_id=c.authority_event_id "
            "WHERE c.contract_family=? AND c.version_number>?",
            (str(row["contract_family"]), int(row["version_number"])),
        ).fetchone()
        next_seq = None if successor is None else successor["next_seq"]
        return next_seq is None or int(row["record_seq"]) < int(next_seq)

    @staticmethod
    def _validate_contract_heads(conn: sqlite3.Connection) -> None:
        missing = conn.execute(
            "SELECT c.contract_family FROM extractor_contracts c "
            "LEFT JOIN extractor_contract_heads h "
            "ON h.contract_family=c.contract_family "
            "WHERE h.contract_family IS NULL LIMIT 1"
        ).fetchone()
        if missing is not None:
            raise AuthoritySchemaError(
                "extractor contract family lacks a retained current head"
            )
        for head in conn.execute(
            "SELECT * FROM extractor_contract_heads"
        ).fetchall():
            rows = conn.execute(
                "SELECT contract_id,version_number,previous_contract_id,recorded_at "
                "FROM extractor_contracts WHERE contract_family=? "
                "ORDER BY version_number",
                (str(head["contract_family"]),),
            ).fetchall()
            if not rows:
                raise AuthoritySchemaError(
                    "extractor contract head has no immutable contract versions"
                )
            previous: str | None = None
            for ordinal, row in enumerate(rows, start=1):
                actual_previous = (
                    None
                    if row["previous_contract_id"] is None
                    else str(row["previous_contract_id"])
                )
                if int(row["version_number"]) != ordinal or actual_previous != previous:
                    raise AuthoritySchemaError(
                        "extractor contract version chain is not contiguous"
                    )
                previous = str(row["contract_id"])
            final = rows[-1]
            if (
                int(head["current_version_number"]) != len(rows)
                or str(head["current_contract_id"]) != str(final["contract_id"])
                or str(head["updated_at"]) != str(final["recorded_at"])
            ):
                raise AuthoritySchemaError(
                    "extractor contract head differs from immutable chain"
                )

    def _validate_run_lineage_history(self, conn: sqlite3.Connection) -> None:
        for row in conn.execute("SELECT * FROM extraction_runs").fetchall():
            request = extraction_run_from_value(
                self._decode_json(
                    bytes(row["canonical_bytes"]), identity="extraction run"
                ),
                idempotency_key=str(
                    self._record_context(
                        conn, event_id=str(row["authority_event_id"])
                    )["idempotency_key"]
                ),
            )
            if not self._source_version_was_current_at_event(
                conn,
                definition_id=str(request.definition_id),
                version_id=str(request.definition_version_id),
                record_event_id=str(row["authority_event_id"]),
            ):
                raise AuthorityPersistenceError(
                    "Extraction Run source version was not current when recorded"
                )
            if not self._contract_was_current_at_event(
                conn,
                contract_id=str(request.contract_id),
                record_event_id=str(row["authority_event_id"]),
            ):
                raise AuthorityPersistenceError(
                    "Extraction Run contract was not current when recorded"
                )
            lineage = conn.execute(
                "SELECT v.definition_id,v.rights_decision_id,"
                "v.rights_policy_version,v.allowed_use,v.source_retention_scope,"
                "v.lifecycle_stage,v.locator,"
                "i.definition_id AS item_definition,"
                "i.definition_version_id AS item_version,"
                "r.item_id AS revision_item,"
                "r.definition_id AS revision_definition,"
                "r.definition_version_id AS revision_version,"
                "p.revision_id AS representation_revision,"
                "p.definition_id AS representation_definition,"
                "p.definition_version_id AS representation_version,"
                "p.produced_at AS representation_produced_at,"
                "c.canonical_digest AS retained_contract_digest,"
                "c.execution_profile,c.max_input_bytes "
                "FROM source_definition_versions v "
                "JOIN source_items i ON i.item_id=? "
                "JOIN source_revisions r ON r.revision_id=? "
                "JOIN discovery_representations p ON p.representation_id=? "
                "JOIN extractor_contracts c ON c.contract_id=? "
                "WHERE v.version_id=?",
                (
                    str(request.item_id),
                    str(request.revision_id),
                    str(request.representation_id),
                    str(request.contract_id),
                    str(request.definition_version_id),
                ),
            ).fetchone()
            if lineage is None:
                raise AuthorityPersistenceError(
                    "Extraction Run exact input lineage is missing"
                )
            expected = (
                str(lineage["definition_id"]) == str(request.definition_id)
                and str(lineage["item_definition"]) == str(request.definition_id)
                and str(lineage["item_version"])
                == str(request.definition_version_id)
                and str(lineage["revision_item"]) == str(request.item_id)
                and str(lineage["revision_definition"])
                == str(request.definition_id)
                and str(lineage["revision_version"])
                == str(request.definition_version_id)
                and str(lineage["representation_revision"])
                == str(request.revision_id)
                and str(lineage["representation_definition"])
                == str(request.definition_id)
                and str(lineage["representation_version"])
                == str(request.definition_version_id)
                and str(lineage["rights_decision_id"])
                == request.rights_decision_id
                and str(lineage["rights_policy_version"])
                == request.rights_policy_version
                and str(lineage["allowed_use"]) == request.allowed_use
                and str(lineage["source_retention_scope"])
                == request.retention_scope
                and str(lineage["lifecycle_stage"]) not in {"RETIRED", "REJECTED"}
                and str(lineage["retained_contract_digest"])
                == request.contract_digest
                and request.requested_at.to_text()
                >= str(lineage["representation_produced_at"])
                and len(bytes(row["input_manifest_bytes"]))
                <= int(lineage["max_input_bytes"])
            )
            if not expected:
                raise AuthorityPersistenceError(
                    "Extraction Run retained lineage or rights are inconsistent"
                )
            if (
                str(lineage["execution_profile"])
                == ExtractionExecutionProfile.FIXTURE.value
                and not str(lineage["locator"]).startswith("fixture://")
            ):
                raise AuthorityPersistenceError(
                    "fixture Extraction Run is bound to a non-fixture locator"
                )

    def _validate_attempt_chains(self, conn: sqlite3.Connection) -> None:
        run_ids = {
            str(row["run_id"])
            for row in conn.execute(
                "SELECT DISTINCT run_id FROM extraction_attempts"
            ).fetchall()
        }
        head_ids = {
            str(row["run_id"])
            for row in conn.execute(
                "SELECT run_id FROM extraction_attempt_heads"
            ).fetchall()
        }
        if run_ids != head_ids:
            raise AuthoritySchemaError(
                "extraction attempt heads differ from runs with attempts"
            )
        for run_id in sorted(run_ids):
            rows = conn.execute(
                "SELECT a.*,ae.ledger_seq AS attempt_seq,"
                "r.requested_at,re.ledger_seq AS run_seq,"
                "c.max_attempts,c.max_input_bytes,c.max_output_bytes,"
                "c.max_input_tokens,c.max_output_tokens,c.max_cost_microunits,"
                "c.max_duration_ms "
                "FROM extraction_attempts a "
                "JOIN extraction_runs r ON r.run_id=a.run_id "
                "JOIN extractor_contracts c ON c.contract_id=r.contract_id "
                "JOIN ledger_events ae ON ae.event_id=a.authority_event_id "
                "JOIN ledger_events re ON re.event_id=r.authority_event_id "
                "WHERE a.run_id=? ORDER BY a.attempt_number",
                (run_id,),
            ).fetchall()
            previous_id: str | None = None
            previous_outcome: str | None = None
            previous_end: str | None = None
            for ordinal, row in enumerate(rows, start=1):
                actual_previous = (
                    None
                    if row["previous_attempt_id"] is None
                    else str(row["previous_attempt_id"])
                )
                duration_ms = int(
                    (
                        extraction_attempt_from_value(
                            self._decode_json(
                                bytes(row["canonical_bytes"]),
                                identity="extraction attempt",
                            ),
                            idempotency_key=str(
                                self._record_context(
                                    conn,
                                    event_id=str(row["authority_event_id"]),
                                )["idempotency_key"]
                            ),
                        ).ended_at.value
                        - extraction_attempt_from_value(
                            self._decode_json(
                                bytes(row["canonical_bytes"]),
                                identity="extraction attempt",
                            ),
                            idempotency_key=str(
                                self._record_context(
                                    conn,
                                    event_id=str(row["authority_event_id"]),
                                )["idempotency_key"]
                            ),
                        ).started_at.value
                    ).total_seconds()
                    * 1000
                )
                if (
                    int(row["attempt_number"]) != ordinal
                    or actual_previous != previous_id
                    or (ordinal > 1 and previous_outcome != ExtractionAttemptOutcome.RETRYABLE_FAILURE.value)
                    or str(row["started_at"]) < str(row["requested_at"])
                    or (previous_end is not None and str(row["started_at"]) < previous_end)
                    or int(row["attempt_seq"]) <= int(row["run_seq"])
                    or ordinal > int(row["max_attempts"])
                    or int(row["input_bytes"]) > int(row["max_input_bytes"])
                    or int(row["output_bytes"]) > int(row["max_output_bytes"])
                    or int(row["input_tokens"]) > int(row["max_input_tokens"])
                    or int(row["output_tokens"]) > int(row["max_output_tokens"])
                    or int(row["cost_microunits"])
                    > int(row["max_cost_microunits"])
                    or duration_ms > int(row["max_duration_ms"])
                ):
                    raise AuthorityPersistenceError(
                        "extraction attempt chain, chronology or resource bounds are inconsistent"
                    )
                previous_id = str(row["attempt_id"])
                previous_outcome = str(row["outcome"])
                previous_end = str(row["ended_at"])
            head = conn.execute(
                "SELECT * FROM extraction_attempt_heads WHERE run_id=?",
                (run_id,),
            ).fetchone()
            assert head is not None
            final = rows[-1]
            if (
                int(head["current_attempt_number"])
                != int(final["attempt_number"])
                or str(head["current_attempt_id"])
                != str(final["attempt_id"])
                or str(head["current_outcome"]) != str(final["outcome"])
                or str(head["updated_at"]) != str(final["recorded_at"])
            ):
                raise AuthoritySchemaError(
                    "extraction attempt head differs from immutable attempt chain"
                )

    def _validate_output_and_proposal_lineage(
        self, conn: sqlite3.Connection
    ) -> None:
        for row in conn.execute("SELECT * FROM extraction_outputs").fetchall():
            request = extraction_output_from_value(
                self._decode_json(
                    bytes(row["canonical_bytes"]), identity="extraction output"
                ),
                idempotency_key=str(
                    self._record_context(
                        conn, event_id=str(row["authority_event_id"])
                    )["idempotency_key"]
                ),
            )
            lineage = conn.execute(
                "SELECT a.outcome,a.output_bytes,a.ended_at,"
                "ae.ledger_seq AS attempt_seq,oe.ledger_seq AS output_seq,"
                "c.output_schema_contract_bytes,c.max_output_bytes "
                "FROM extraction_attempts a "
                "JOIN extraction_runs r ON r.run_id=a.run_id "
                "JOIN extractor_contracts c ON c.contract_id=r.contract_id "
                "JOIN ledger_events ae ON ae.event_id=a.authority_event_id "
                "JOIN ledger_events oe ON oe.event_id=? "
                "WHERE a.attempt_id=? AND a.run_id=?",
                (
                    str(row["authority_event_id"]),
                    str(request.attempt_id),
                    str(request.run_id),
                ),
            ).fetchone()
            if lineage is None:
                raise AuthorityPersistenceError(
                    "extraction output lacks exact attempt lineage"
                )
            outcome = str(lineage["outcome"])
            compatible = (
                request.valid
                and outcome
                in {
                    ExtractionAttemptOutcome.SUCCESS.value,
                    ExtractionAttemptOutcome.PARTIAL.value,
                }
            ) or (
                not request.valid
                and outcome == ExtractionAttemptOutcome.INVALID_OUTPUT.value
            )
            retained_size = (
                int(lineage["output_bytes"])
                if request.output_bytes is None
                else len(request.output_bytes)
            )
            if (
                not compatible
                or retained_size != int(lineage["output_bytes"])
                or retained_size > int(lineage["max_output_bytes"])
                or request.output_schema_digest
                != digest_bytes(bytes(lineage["output_schema_contract_bytes"]))
                or request.retained_at.to_text() < str(lineage["ended_at"])
                or int(lineage["output_seq"]) <= int(lineage["attempt_seq"])
            ):
                raise AuthorityPersistenceError(
                    "extraction output chronology, outcome or schema lineage is inconsistent"
                )

        for row in conn.execute(
            "SELECT * FROM extraction_proposal_sets"
        ).fetchall():
            request = proposal_set_from_value(
                self._decode_json(
                    bytes(row["canonical_bytes"]),
                    identity="extraction proposal set",
                ),
                idempotency_key=str(
                    self._record_context(
                        conn, event_id=str(row["authority_event_id"])
                    )["idempotency_key"]
                ),
            )
            lineage = conn.execute(
                "SELECT a.outcome,o.valid,o.retained_at,"
                "oe.ledger_seq AS output_seq,pe.ledger_seq AS proposal_seq,"
                "c.max_proposals "
                "FROM extraction_attempts a "
                "JOIN extraction_outputs o "
                "ON o.attempt_id=a.attempt_id AND o.run_id=a.run_id "
                "JOIN extraction_runs r ON r.run_id=a.run_id "
                "JOIN extractor_contracts c ON c.contract_id=r.contract_id "
                "JOIN ledger_events oe ON oe.event_id=o.authority_event_id "
                "JOIN ledger_events pe ON pe.event_id=? "
                "WHERE a.attempt_id=? AND a.run_id=? AND o.output_id=?",
                (
                    str(row["authority_event_id"]),
                    str(request.attempt_id),
                    str(request.run_id),
                    str(request.output_id),
                ),
            ).fetchone()
            expected_completeness = (
                "COMPLETE"
                if lineage is not None
                and str(lineage["outcome"])
                == ExtractionAttemptOutcome.SUCCESS.value
                else "PARTIAL"
            )
            if (
                lineage is None
                or int(lineage["valid"]) != 1
                or str(lineage["outcome"])
                not in {
                    ExtractionAttemptOutcome.SUCCESS.value,
                    ExtractionAttemptOutcome.PARTIAL.value,
                }
                or request.completeness.value != expected_completeness
                or len(request.proposals) > int(lineage["max_proposals"])
                or request.retained_at.to_text() < str(lineage["retained_at"])
                or int(lineage["proposal_seq"]) <= int(lineage["output_seq"])
            ):
                raise AuthorityPersistenceError(
                    "proposal set does not follow an earlier valid retained output"
                )
            for proposal in request.proposals:
                linked = tuple(
                    str(item["passage_id"])
                    for item in conn.execute(
                        "SELECT passage_id FROM extraction_proposal_passages "
                        "WHERE proposal_id=? ORDER BY passage_id",
                        (str(proposal.proposal_id),),
                    ).fetchall()
                )
                if linked != proposal.passage_ids:
                    raise AuthorityPersistenceError(
                        "proposal passage join rows differ from canonical proposal"
                    )

    @staticmethod
    def _validate_extraction_event_coverage(conn: sqlite3.Connection) -> None:
        specs = (
            ("extraction.contract.registered", "extractor_contracts"),
            ("extraction.run.registered", "extraction_runs"),
            ("extraction.attempt.recorded", "extraction_attempts"),
            ("extraction.output.retained", "extraction_outputs"),
            ("extraction.proposal_set.retained", "extraction_proposal_sets"),
        )
        for event_type, table in specs:
            missing = conn.execute(
                f"SELECT e.event_id FROM ledger_events e LEFT JOIN {table} r "
                "ON r.authority_event_id=e.event_id WHERE e.event_type=? "
                "AND r.authority_event_id IS NULL LIMIT 1",
                (event_type,),
            ).fetchone()
            if missing is not None:
                raise AuthoritySchemaError(
                    f"{event_type} has no exact extraction authority record"
                )


__all__ = ["_ExtractionIntegrityMixin"]
