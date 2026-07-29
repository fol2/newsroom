from __future__ import annotations

import sqlite3
from typing import Any

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.persistence import AuthorityPersistenceError
from newsroom.authority.types import EventId, UtcTimestamp
from newsroom.extraction.decoding import (
    extraction_attempt_from_value,
    extraction_output_from_value,
    extraction_run_from_value,
    extractor_contract_from_value,
    proposal_set_from_value,
)
from newsroom.extraction.policy import (
    EXTRACTION_ATTEMPT_RECORD_COMMAND,
    EXTRACTION_OUTPUT_RETAIN_COMMAND,
    EXTRACTION_PROPOSAL_SET_RETAIN_COMMAND,
    EXTRACTION_RUN_REGISTER_COMMAND,
    EXTRACTOR_CONTRACT_REGISTER_COMMAND,
)
from newsroom.extraction.records import (
    ExtractionAttempt,
    ExtractionOutput,
    ExtractionReplayBundle,
    ExtractionRun,
    ExtractorContract,
    ProposalSet,
)
from newsroom.extraction.types import (
    ExtractionAttemptId,
    ExtractionOutputId,
    ExtractionRunId,
    ExtractorContractId,
    ProposalSetId,
)


class _ExtractionStoreReadMixin:
    def _contract_from_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        replayed: bool,
    ) -> ExtractorContract:
        canonical = bytes(row["canonical_bytes"])
        value = self._decode_json(canonical, identity="extractor contract")
        event = self._validate_record_envelope(
            conn,
            row,
            command_type=EXTRACTOR_CONTRACT_REGISTER_COMMAND,
            aggregate_id=str(row["contract_id"]),
            canonical_bytes=canonical,
            canonical_digest=str(row["canonical_digest"]),
        )
        request = extractor_contract_from_value(
            value, idempotency_key=str(event["idempotency_key"])
        )
        bounds = request.resource_bounds
        normalized = {
            "contract_id": str(request.contract_id),
            "contract_family": request.contract_family,
            "version_number": request.version_number,
            "previous_contract_id": None
            if request.previous_contract_id is None
            else str(request.previous_contract_id),
            "producer_kind": request.producer_kind.value,
            "execution_profile": request.execution_profile.value,
            "max_input_bytes": bounds.max_input_bytes,
            "max_output_bytes": bounds.max_output_bytes,
            "max_proposals": bounds.max_proposals,
            "max_attempts": bounds.max_attempts,
            "max_duration_ms": bounds.max_duration_ms,
            "max_input_tokens": bounds.max_input_tokens,
            "max_output_tokens": bounds.max_output_tokens,
            "max_cost_microunits": bounds.max_cost_microunits,
            "runtime_authority": request.runtime_authority,
            "registered_at": request.registered_at.to_text(),
            "semantic_digest": request.semantic_digest,
        }
        if any(row[key] != value for key, value in normalized.items()):
            raise AuthorityPersistenceError(
                "extractor contract normalized columns differ from canonical bytes"
            )
        blobs = {
            "framework_bytes": request.framework.canonical_value(),
            "model_placeholder_bytes": request.model_placeholder.canonical_value(),
            "prompt_contract_bytes": request.prompt_contract.canonical_value(),
            "output_schema_contract_bytes": request.output_schema_contract.canonical_value(),
            "code_contract_bytes": request.code_contract.canonical_value(),
            "normalization_contract_bytes": request.normalization_contract.canonical_value(),
            "extraction_policy_bytes": request.extraction_policy.canonical_value(),
            "resource_bounds_bytes": bounds.canonical_value(),
        }
        for column, expected in blobs.items():
            if bytes(row[column]) != canonical_json_bytes(expected):
                raise AuthorityPersistenceError(
                    f"extractor contract {column} differs from canonical bytes"
                )
        return ExtractorContract(
            request=request,
            event_id=EventId.parse(str(row["authority_event_id"])),
            aggregate_version=int(row["authority_aggregate_version"]),
            recorded_at=UtcTimestamp.parse(str(row["recorded_at"])),
            canonical_digest=str(row["canonical_digest"]),
            replayed=replayed,
        )

    def _run_from_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        replayed: bool,
    ) -> ExtractionRun:
        canonical = bytes(row["canonical_bytes"])
        value = self._decode_json(canonical, identity="extraction run")
        event = self._validate_record_envelope(
            conn,
            row,
            command_type=EXTRACTION_RUN_REGISTER_COMMAND,
            aggregate_id=str(row["run_id"]),
            canonical_bytes=canonical,
            canonical_digest=str(row["canonical_digest"]),
        )
        request = extraction_run_from_value(
            value, idempotency_key=str(event["idempotency_key"])
        )
        normalized = {
            "run_id": str(request.run_id),
            "contract_id": str(request.contract_id),
            "contract_digest": request.contract_digest,
            "definition_id": str(request.definition_id),
            "definition_version_id": str(request.definition_version_id),
            "item_id": str(request.item_id),
            "revision_id": str(request.revision_id),
            "representation_id": str(request.representation_id),
            "rights_decision_id": request.rights_decision_id,
            "rights_policy_version": request.rights_policy_version,
            "allowed_use": request.allowed_use,
            "source_retention_scope": request.retention_scope,
            "input_manifest_digest": request.input_manifest_digest,
            "producer_id": request.producer_id,
            "producer_version": request.producer_version,
            "requested_at": request.requested_at.to_text(),
            "semantic_digest": request.semantic_digest,
        }
        if any(row[key] != expected for key, expected in normalized.items()):
            raise AuthorityPersistenceError(
                "extraction run normalized columns differ from canonical bytes"
            )
        if bytes(row["input_manifest_bytes"]) != canonical_json_bytes(
            request.input_manifest_value()
        ):
            raise AuthorityPersistenceError(
                "extraction run input manifest differs from canonical bytes"
            )
        passages = conn.execute(
            "SELECT * FROM extraction_passages WHERE run_id=? ORDER BY ordinal",
            (str(request.run_id),),
        ).fetchall()
        if len(passages) != len(request.passages):
            raise AuthorityPersistenceError(
                "extraction passage count differs from run manifest"
            )
        for stored, expected in zip(passages, request.passages, strict=True):
            expected_bytes = canonical_json_bytes(expected.canonical_value())
            if (
                str(stored["passage_id"]) != expected.passage_id
                or int(stored["ordinal"]) != expected.ordinal
                or str(stored["source_field"]) != expected.source_field
                or int(stored["start_offset"]) != expected.start_offset
                or int(stored["end_offset"]) != expected.end_offset
                or str(stored["text_digest"]) != expected.text_digest
                or str(stored["language"]) != expected.language
                or stored["object_admission_id"]
                != (
                    None
                    if expected.object_admission_id is None
                    else str(expected.object_admission_id)
                )
                or stored["hydration_digest"] != expected.hydration_digest
                or bytes(stored["canonical_bytes"]) != expected_bytes
                or str(stored["canonical_digest"]) != digest_bytes(expected_bytes)
            ):
                raise AuthorityPersistenceError(
                    "extraction passage differs from run manifest"
                )
        return ExtractionRun(
            request=request,
            event_id=EventId.parse(str(row["authority_event_id"])),
            aggregate_version=int(row["authority_aggregate_version"]),
            recorded_at=UtcTimestamp.parse(str(row["recorded_at"])),
            canonical_digest=str(row["canonical_digest"]),
            replayed=replayed,
        )

    def _attempt_from_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        replayed: bool,
    ) -> ExtractionAttempt:
        canonical = bytes(row["canonical_bytes"])
        value = self._decode_json(canonical, identity="extraction attempt")
        event = self._validate_record_envelope(
            conn,
            row,
            command_type=EXTRACTION_ATTEMPT_RECORD_COMMAND,
            aggregate_id=str(row["attempt_id"]),
            canonical_bytes=canonical,
            canonical_digest=str(row["canonical_digest"]),
        )
        request = extraction_attempt_from_value(
            value, idempotency_key=str(event["idempotency_key"])
        )
        normalized: dict[str, Any] = {
            "attempt_id": str(request.attempt_id),
            "run_id": str(request.run_id),
            "attempt_number": request.attempt_number,
            "previous_attempt_id": None
            if request.previous_attempt_id is None
            else str(request.previous_attempt_id),
            "outcome": request.outcome.value,
            "producer_execution_id": request.producer_execution_id,
            "started_at": request.started_at.to_text(),
            "ended_at": request.ended_at.to_text(),
            "input_bytes": request.input_bytes,
            "output_bytes": request.output_bytes,
            "input_tokens": request.input_tokens,
            "output_tokens": request.output_tokens,
            "cost_microunits": request.cost_microunits,
            "error_code": request.error_code,
            "error_summary": request.error_summary,
            "semantic_digest": request.semantic_digest,
        }
        if any(row[key] != expected for key, expected in normalized.items()):
            raise AuthorityPersistenceError(
                "extraction attempt normalized columns differ from canonical bytes"
            )
        return ExtractionAttempt(
            request=request,
            event_id=EventId.parse(str(row["authority_event_id"])),
            aggregate_version=int(row["authority_aggregate_version"]),
            recorded_at=UtcTimestamp.parse(str(row["recorded_at"])),
            canonical_digest=str(row["canonical_digest"]),
            replayed=replayed,
        )

    def _output_from_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        replayed: bool,
    ) -> ExtractionOutput:
        canonical = bytes(row["canonical_bytes"])
        value = self._decode_json(canonical, identity="extraction output")
        event = self._validate_record_envelope(
            conn,
            row,
            command_type=EXTRACTION_OUTPUT_RETAIN_COMMAND,
            aggregate_id=str(row["output_id"]),
            canonical_bytes=canonical,
            canonical_digest=str(row["canonical_digest"]),
        )
        request = extraction_output_from_value(
            value, idempotency_key=str(event["idempotency_key"])
        )
        normalized = {
            "output_id": str(request.output_id),
            "run_id": str(request.run_id),
            "attempt_id": str(request.attempt_id),
            "output_kind": request.output_kind.value,
            "output_schema_digest": request.output_schema_digest,
            "object_admission_id": None
            if request.object_admission_id is None
            else str(request.object_admission_id),
            "hydration_digest": request.hydration_digest,
            "output_digest": request.output_digest,
            "valid": int(request.valid),
            "retained_at": request.retained_at.to_text(),
        }
        if any(row[key] != expected for key, expected in normalized.items()):
            raise AuthorityPersistenceError(
                "extraction output normalized columns differ from canonical bytes"
            )
        expected_output = request.output_bytes
        stored_output = row["structured_output_bytes"]
        if (stored_output is None) != (expected_output is None) or (
            stored_output is not None and bytes(stored_output) != expected_output
        ):
            raise AuthorityPersistenceError(
                "retained structured output differs from canonical bytes"
            )
        if bytes(row["validation_errors_bytes"]) != canonical_json_bytes(
            list(request.validation_errors)
        ):
            raise AuthorityPersistenceError(
                "output validation errors differ from canonical bytes"
            )
        return ExtractionOutput(
            request=request,
            event_id=EventId.parse(str(row["authority_event_id"])),
            aggregate_version=int(row["authority_aggregate_version"]),
            recorded_at=UtcTimestamp.parse(str(row["recorded_at"])),
            canonical_digest=str(row["canonical_digest"]),
            replayed=replayed,
        )

    def _proposal_set_from_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        replayed: bool,
    ) -> ProposalSet:
        canonical = bytes(row["canonical_bytes"])
        value = self._decode_json(canonical, identity="extraction proposal set")
        event = self._validate_record_envelope(
            conn,
            row,
            command_type=EXTRACTION_PROPOSAL_SET_RETAIN_COMMAND,
            aggregate_id=str(row["proposal_set_id"]),
            canonical_bytes=canonical,
            canonical_digest=str(row["canonical_digest"]),
        )
        request = proposal_set_from_value(
            value, idempotency_key=str(event["idempotency_key"])
        )
        normalized = {
            "proposal_set_id": str(request.proposal_set_id),
            "run_id": str(request.run_id),
            "attempt_id": str(request.attempt_id),
            "output_id": str(request.output_id),
            "completeness": request.completeness.value,
            "proposal_count": len(request.proposals),
            "semantic_digest": request.semantic_digest,
            "retained_at": request.retained_at.to_text(),
        }
        if any(row[key] != expected for key, expected in normalized.items()):
            raise AuthorityPersistenceError(
                "proposal set normalized columns differ from canonical bytes"
            )
        stored = conn.execute(
            "SELECT * FROM extraction_proposals WHERE proposal_set_id=? "
            "ORDER BY proposal_id",
            (str(request.proposal_set_id),),
        ).fetchall()
        if len(stored) != len(request.proposals):
            raise AuthorityPersistenceError(
                "proposal row count differs from retained proposal set"
            )
        for proposal_row, expected in zip(stored, request.proposals, strict=True):
            expected_bytes = canonical_json_bytes(expected.canonical_value())
            subject_bytes = canonical_json_bytes(expected.subject.canonical_value())
            object_bytes = (
                None
                if expected.object is None
                else canonical_json_bytes(expected.object.canonical_value())
            )
            if (
                str(proposal_row["proposal_id"]) != str(expected.proposal_id)
                or str(proposal_row["run_id"]) != str(request.run_id)
                or str(proposal_row["attempt_id"]) != str(request.attempt_id)
                or str(proposal_row["output_id"]) != str(request.output_id)
                or str(proposal_row["producer_local_id"])
                != expected.producer_local_id
                or str(proposal_row["proposal_kind"])
                != expected.proposal_kind.value
                or str(proposal_row["subject_kind"]) != expected.subject.kind.value
                or bytes(proposal_row["subject_bytes"]) != subject_bytes
                or proposal_row["object_kind"]
                != (None if expected.object is None else expected.object.kind.value)
                or (proposal_row["object_bytes"] is None) != (object_bytes is None)
                or (
                    object_bytes is not None
                    and bytes(proposal_row["object_bytes"]) != object_bytes
                )
                or proposal_row["predicate_hint"] != expected.predicate_hint
                or bytes(proposal_row["passage_ids_bytes"])
                != canonical_json_bytes(list(expected.passage_ids))
                or int(proposal_row["confidence_basis_points"])
                != expected.confidence_basis_points
                or str(proposal_row["uncertainty"]) != expected.uncertainty.value
                or bytes(proposal_row["uncertainty_reasons_bytes"])
                != canonical_json_bytes(list(expected.uncertainty_reasons))
                or bytes(proposal_row["attributes_bytes"])
                != canonical_json_bytes(expected.attributes)
                or bytes(proposal_row["canonical_bytes"]) != expected_bytes
                or str(proposal_row["canonical_digest"]) != expected.digest
            ):
                raise AuthorityPersistenceError(
                    "proposal row differs from retained proposal-set bytes"
                )
            passage_rows = tuple(
                str(item["passage_id"])
                for item in conn.execute(
                    "SELECT passage_id FROM extraction_proposal_passages "
                    "WHERE proposal_id=? ORDER BY passage_id",
                    (str(expected.proposal_id),),
                ).fetchall()
            )
            if passage_rows != expected.passage_ids:
                raise AuthorityPersistenceError(
                    "proposal passage links differ from canonical proposal"
                )
        return ProposalSet(
            request=request,
            event_id=EventId.parse(str(row["authority_event_id"])),
            aggregate_version=int(row["authority_aggregate_version"]),
            recorded_at=UtcTimestamp.parse(str(row["recorded_at"])),
            canonical_digest=str(row["canonical_digest"]),
            replayed=replayed,
        )

    def _record_for_event(
        self,
        conn: sqlite3.Connection,
        *,
        table: str,
        event_id: str,
        loader: Any,
        identity: str,
        replayed: bool,
    ) -> Any:
        row = conn.execute(
            f"SELECT * FROM {table} WHERE authority_event_id=?", (event_id,)
        ).fetchone()
        if row is None:
            raise AuthorityPersistenceError(f"committed {identity} row is missing")
        return loader(conn, row, replayed=replayed)

    def _contract_for_event(self, conn: sqlite3.Connection, event_id: str, *, replayed: bool) -> ExtractorContract:
        return self._record_for_event(
            conn,
            table="extractor_contracts",
            event_id=event_id,
            loader=self._contract_from_row,
            identity="extractor contract",
            replayed=replayed,
        )

    def _run_for_event(self, conn: sqlite3.Connection, event_id: str, *, replayed: bool) -> ExtractionRun:
        return self._record_for_event(
            conn,
            table="extraction_runs",
            event_id=event_id,
            loader=self._run_from_row,
            identity="extraction run",
            replayed=replayed,
        )

    def _attempt_for_event(self, conn: sqlite3.Connection, event_id: str, *, replayed: bool) -> ExtractionAttempt:
        return self._record_for_event(
            conn,
            table="extraction_attempts",
            event_id=event_id,
            loader=self._attempt_from_row,
            identity="extraction attempt",
            replayed=replayed,
        )

    def _output_for_event(self, conn: sqlite3.Connection, event_id: str, *, replayed: bool) -> ExtractionOutput:
        return self._record_for_event(
            conn,
            table="extraction_outputs",
            event_id=event_id,
            loader=self._output_from_row,
            identity="extraction output",
            replayed=replayed,
        )

    def _proposal_set_for_event(self, conn: sqlite3.Connection, event_id: str, *, replayed: bool) -> ProposalSet:
        return self._record_for_event(
            conn,
            table="extraction_proposal_sets",
            event_id=event_id,
            loader=self._proposal_set_from_row,
            identity="proposal set",
            replayed=replayed,
        )

    def extractor_contract(self, contract_id: ExtractorContractId) -> ExtractorContract | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM extractor_contracts WHERE contract_id=?",
                (str(contract_id),),
            ).fetchone()
            return None if row is None else self._contract_from_row(self._connection, row, replayed=False)

    def current_extractor_contract(self, contract_family: str) -> ExtractorContract | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT c.* FROM extractor_contract_heads h "
                "JOIN extractor_contracts c ON c.contract_id=h.current_contract_id "
                "WHERE h.contract_family=?",
                (contract_family,),
            ).fetchone()
            return None if row is None else self._contract_from_row(self._connection, row, replayed=False)

    def extraction_run(self, run_id: ExtractionRunId) -> ExtractionRun | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM extraction_runs WHERE run_id=?", (str(run_id),)
            ).fetchone()
            return None if row is None else self._run_from_row(self._connection, row, replayed=False)

    def extraction_attempt(self, attempt_id: ExtractionAttemptId) -> ExtractionAttempt | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM extraction_attempts WHERE attempt_id=?",
                (str(attempt_id),),
            ).fetchone()
            return None if row is None else self._attempt_from_row(self._connection, row, replayed=False)

    def extraction_attempts(self, run_id: ExtractionRunId, *, limit: int) -> tuple[ExtractionAttempt, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM extraction_attempts WHERE run_id=? "
                "ORDER BY attempt_number LIMIT ?",
                (str(run_id), limit),
            ).fetchall()
            return tuple(self._attempt_from_row(self._connection, row, replayed=False) for row in rows)

    def extraction_output(self, output_id: ExtractionOutputId) -> ExtractionOutput | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM extraction_outputs WHERE output_id=?",
                (str(output_id),),
            ).fetchone()
            return None if row is None else self._output_from_row(self._connection, row, replayed=False)

    def proposal_set(self, proposal_set_id: ProposalSetId) -> ProposalSet | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM extraction_proposal_sets WHERE proposal_set_id=?",
                (str(proposal_set_id),),
            ).fetchone()
            return None if row is None else self._proposal_set_from_row(self._connection, row, replayed=False)

    def replay_bundle(self, run_id: ExtractionRunId) -> ExtractionReplayBundle:
        with self._lock:
            conn = self._connection
            self._require_current_run_rights(conn, run_id=str(run_id))
            run_row = self._run_row(conn, str(run_id))
            run = self._run_from_row(conn, run_row, replayed=True)
            head = conn.execute(
                "SELECT current_attempt_id FROM extraction_attempt_heads WHERE run_id=?",
                (str(run_id),),
            ).fetchone()
            if head is None:
                raise LookupError("extraction run has no retained attempt")
            attempt_row = self._attempt_row(conn, str(head["current_attempt_id"]))
            attempt = self._attempt_from_row(conn, attempt_row, replayed=True)
            output_row = conn.execute(
                "SELECT * FROM extraction_outputs WHERE attempt_id=?",
                (str(attempt.request.attempt_id),),
            ).fetchone()
            if output_row is None:
                raise LookupError("current extraction attempt has no retained output")
            output = self._output_from_row(conn, output_row, replayed=True)
            set_row = conn.execute(
                "SELECT * FROM extraction_proposal_sets WHERE output_id=?",
                (str(output.request.output_id),),
            ).fetchone()
            proposal_set = (
                None
                if set_row is None
                else self._proposal_set_from_row(conn, set_row, replayed=True)
            )
            return ExtractionReplayBundle(
                run=run,
                attempt=attempt,
                output=output,
                proposal_set=proposal_set,
            )


__all__ = ["_ExtractionStoreReadMixin"]
