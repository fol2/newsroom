from __future__ import annotations

import sqlite3

from newsroom.authority._capability import _AuthorizedCommandGrant
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.persistence import AuthorityPersistenceError
from newsroom.extraction.models import (
    ExtractionAttemptRequest,
    ExtractionOutputRequest,
    ExtractionRunRequest,
    ExtractorContractRequest,
    ProposalSetRequest,
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
    ExtractionRun,
    ExtractorContract,
    ProposalSet,
)
from newsroom.extraction.types import (
    ExtractionAttemptOutcome,
    ExtractionExecutionProfile,
    ExtractionRightsBlocked,
    ExtractionSemanticCollision,
    ExtractionStateError,
    ExtractionVersionConflict,
)


class _ExtractionStoreCommitMixin:
    def commit_extractor_contract(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        request: ExtractorContractRequest,
    ) -> ExtractorContract:
        if not isinstance(request, ExtractorContractRequest):
            raise TypeError("extractor contract commit requires a typed request")
        self._require_extraction_grant(
            grant,
            command_type=EXTRACTOR_CONTRACT_REGISTER_COMMAND,
            aggregate_id=str(request.contract_id),
            canonical_bytes=request.canonical_bytes,
        )
        with self._lock, self._transaction() as conn:
            if grant.replay_of_command_id is not None:
                committed = self._commit_grant_in_transaction(
                    conn, grant, recorded_at=self._clock().to_text()
                )
                return self._contract_for_event(
                    conn, committed.event_id, replayed=True
                )
            self._extraction_identifier_absent(
                conn,
                table="extractor_contracts",
                column="contract_id",
                identifier=str(request.contract_id),
                identity="extractor contract identity",
            )
            self._extraction_semantic_absent(
                conn,
                table="extractor_contracts",
                predicate="contract_family=? AND semantic_digest=?",
                parameters=(request.contract_family, request.semantic_digest),
                identity="extractor contract semantics",
            )
            head = conn.execute(
                "SELECT * FROM extractor_contract_heads WHERE contract_family=?",
                (request.contract_family,),
            ).fetchone()
            if head is None:
                if request.version_number != 1 or request.previous_contract_id is not None:
                    raise ExtractionVersionConflict(
                        "initial extractor contract must be version one"
                    )
            elif (
                request.version_number != int(head["current_version_number"]) + 1
                or request.previous_contract_id is None
                or str(request.previous_contract_id)
                != str(head["current_contract_id"])
            ):
                raise ExtractionVersionConflict(
                    "extractor contract does not extend the exact current head"
                )
            recorded_at = self._clock().to_text()
            committed = self._commit_grant_in_transaction(
                conn, grant, recorded_at=recorded_at
            )
            if committed.replayed:
                return self._contract_for_event(
                    conn, committed.event_id, replayed=True
                )
            bounds = request.resource_bounds
            conn.execute(
                "INSERT INTO extractor_contracts("
                "contract_id,contract_family,version_number,previous_contract_id,"
                "framework_bytes,model_placeholder_bytes,prompt_contract_bytes,"
                "output_schema_contract_bytes,code_contract_bytes,"
                "normalization_contract_bytes,extraction_policy_bytes,"
                "producer_kind,execution_profile,resource_bounds_bytes,"
                "max_input_bytes,max_output_bytes,max_proposals,max_attempts,"
                "max_duration_ms,max_input_tokens,max_output_tokens,"
                "max_cost_microunits,runtime_authority,registered_at,"
                "semantic_digest,authority_event_id,authority_aggregate_version,"
                "canonical_bytes,canonical_digest,recorded_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(request.contract_id),
                    request.contract_family,
                    request.version_number,
                    None
                    if request.previous_contract_id is None
                    else str(request.previous_contract_id),
                    canonical_json_bytes(request.framework.canonical_value()),
                    canonical_json_bytes(request.model_placeholder.canonical_value()),
                    canonical_json_bytes(request.prompt_contract.canonical_value()),
                    canonical_json_bytes(
                        request.output_schema_contract.canonical_value()
                    ),
                    canonical_json_bytes(request.code_contract.canonical_value()),
                    canonical_json_bytes(
                        request.normalization_contract.canonical_value()
                    ),
                    canonical_json_bytes(request.extraction_policy.canonical_value()),
                    request.producer_kind.value,
                    request.execution_profile.value,
                    canonical_json_bytes(bounds.canonical_value()),
                    bounds.max_input_bytes,
                    bounds.max_output_bytes,
                    bounds.max_proposals,
                    bounds.max_attempts,
                    bounds.max_duration_ms,
                    bounds.max_input_tokens,
                    bounds.max_output_tokens,
                    bounds.max_cost_microunits,
                    request.runtime_authority,
                    request.registered_at.to_text(),
                    request.semantic_digest,
                    committed.event_id,
                    committed.aggregate_version,
                    request.canonical_bytes,
                    request.digest,
                    recorded_at,
                ),
            )
            return self._contract_for_event(
                conn, committed.event_id, replayed=False
            )

    def _validate_run_lineage(
        self,
        conn: sqlite3.Connection,
        request: ExtractionRunRequest,
    ) -> sqlite3.Row:
        contract = self._require_current_contract(
            conn, contract_id=str(request.contract_id)
        )
        if str(contract["canonical_digest"]) != request.contract_digest:
            raise ExtractionStateError(
                "extraction run contract digest differs from registered authority"
            )
        if len(canonical_json_bytes(request.input_manifest_value())) > int(
            contract["max_input_bytes"]
        ):
            raise ExtractionStateError(
                "extraction input manifest exceeds contract byte bound"
            )
        lineage = conn.execute(
            "SELECT v.*,h.current_version_id,i.definition_version_id AS item_version,"
            "r.item_id AS revision_item,r.definition_version_id AS revision_version,"
            "p.revision_id AS representation_revision,"
            "p.definition_version_id AS representation_version,"
            "p.produced_at AS representation_produced_at "
            "FROM source_definition_versions v "
            "JOIN source_definition_version_heads h "
            "ON h.definition_id=v.definition_id "
            "JOIN source_items i ON i.item_id=? "
            "JOIN source_revisions r ON r.revision_id=? "
            "JOIN discovery_representations p ON p.representation_id=? "
            "WHERE v.version_id=? AND v.definition_id=?",
            (
                str(request.item_id),
                str(request.revision_id),
                str(request.representation_id),
                str(request.definition_version_id),
                str(request.definition_id),
            ),
        ).fetchone()
        if lineage is None:
            raise ExtractionStateError("extraction source lineage is not retained")
        if (
            str(lineage["current_version_id"])
            != str(request.definition_version_id)
            or str(lineage["definition_id"]) != str(request.definition_id)
            or str(lineage["item_version"])
            != str(request.definition_version_id)
            or str(lineage["revision_item"]) != str(request.item_id)
            or str(lineage["revision_version"])
            != str(request.definition_version_id)
            or str(lineage["representation_revision"])
            != str(request.revision_id)
            or str(lineage["representation_version"])
            != str(request.definition_version_id)
            or str(lineage["rights_decision_id"])
            != request.rights_decision_id
            or str(lineage["rights_policy_version"])
            != request.rights_policy_version
            or str(lineage["allowed_use"]) != request.allowed_use
            or str(lineage["source_retention_scope"])
            != request.retention_scope
            or str(lineage["lifecycle_stage"]) in {"RETIRED", "REJECTED"}
        ):
            raise ExtractionRightsBlocked(
                "extraction run is not bound to exact current source rights"
            )
        if request.requested_at.to_text() < str(
            lineage["representation_produced_at"]
        ):
            raise ExtractionStateError(
                "extraction run cannot precede its retained representation"
            )
        profile = ExtractionExecutionProfile(str(contract["execution_profile"]))
        if profile is ExtractionExecutionProfile.FIXTURE and not str(
            lineage["locator"]
        ).startswith("fixture://"):
            raise ExtractionStateError(
                "deterministic fake extraction is restricted to fixture locators"
            )
        for passage in request.passages:
            self._require_active_object_admission(
                conn,
                None
                if passage.object_admission_id is None
                else str(passage.object_admission_id),
            )
        return contract

    def commit_extraction_run(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        request: ExtractionRunRequest,
    ) -> ExtractionRun:
        if not isinstance(request, ExtractionRunRequest):
            raise TypeError("extraction run commit requires a typed request")
        self._require_extraction_grant(
            grant,
            command_type=EXTRACTION_RUN_REGISTER_COMMAND,
            aggregate_id=str(request.run_id),
            canonical_bytes=request.canonical_bytes,
        )
        with self._lock, self._transaction() as conn:
            if grant.replay_of_command_id is not None:
                committed = self._commit_grant_in_transaction(
                    conn, grant, recorded_at=self._clock().to_text()
                )
                return self._run_for_event(conn, committed.event_id, replayed=True)
            self._validate_run_lineage(conn, request)
            self._extraction_identifier_absent(
                conn,
                table="extraction_runs",
                column="run_id",
                identifier=str(request.run_id),
                identity="extraction run identity",
            )
            self._extraction_semantic_absent(
                conn,
                table="extraction_runs",
                predicate="semantic_digest=?",
                parameters=(request.semantic_digest,),
                identity="extraction run semantics",
            )
            recorded_at = self._clock().to_text()
            committed = self._commit_grant_in_transaction(
                conn, grant, recorded_at=recorded_at
            )
            if committed.replayed:
                return self._run_for_event(conn, committed.event_id, replayed=True)
            conn.execute(
                "INSERT INTO extraction_runs("
                "run_id,contract_id,contract_digest,definition_id,"
                "definition_version_id,item_id,revision_id,representation_id,"
                "rights_decision_id,rights_policy_version,allowed_use,"
                "source_retention_scope,input_manifest_bytes,input_manifest_digest,"
                "producer_id,producer_version,requested_at,semantic_digest,"
                "authority_event_id,authority_aggregate_version,canonical_bytes,"
                "canonical_digest,recorded_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(request.run_id),
                    str(request.contract_id),
                    request.contract_digest,
                    str(request.definition_id),
                    str(request.definition_version_id),
                    str(request.item_id),
                    str(request.revision_id),
                    str(request.representation_id),
                    request.rights_decision_id,
                    request.rights_policy_version,
                    request.allowed_use,
                    request.retention_scope,
                    canonical_json_bytes(request.input_manifest_value()),
                    request.input_manifest_digest,
                    request.producer_id,
                    request.producer_version,
                    request.requested_at.to_text(),
                    request.semantic_digest,
                    committed.event_id,
                    committed.aggregate_version,
                    request.canonical_bytes,
                    request.digest,
                    recorded_at,
                ),
            )
            for passage in request.passages:
                passage_bytes = canonical_json_bytes(passage.canonical_value())
                conn.execute(
                    "INSERT INTO extraction_passages("
                    "run_id,passage_id,ordinal,source_field,start_offset,end_offset,"
                    "text_digest,language,object_admission_id,hydration_digest,"
                    "canonical_bytes,canonical_digest) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        str(request.run_id),
                        passage.passage_id,
                        passage.ordinal,
                        passage.source_field,
                        passage.start_offset,
                        passage.end_offset,
                        passage.text_digest,
                        passage.language,
                        None
                        if passage.object_admission_id is None
                        else str(passage.object_admission_id),
                        passage.hydration_digest,
                        passage_bytes,
                        digest_bytes(passage_bytes),
                    ),
                )
            return self._run_for_event(conn, committed.event_id, replayed=False)

    def commit_extraction_attempt(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        request: ExtractionAttemptRequest,
    ) -> ExtractionAttempt:
        if not isinstance(request, ExtractionAttemptRequest):
            raise TypeError("extraction attempt commit requires a typed request")
        self._require_extraction_grant(
            grant,
            command_type=EXTRACTION_ATTEMPT_RECORD_COMMAND,
            aggregate_id=str(request.attempt_id),
            canonical_bytes=request.canonical_bytes,
        )
        with self._lock, self._transaction() as conn:
            if grant.replay_of_command_id is not None:
                committed = self._commit_grant_in_transaction(
                    conn, grant, recorded_at=self._clock().to_text()
                )
                return self._attempt_for_event(
                    conn, committed.event_id, replayed=True
                )
            run = self._require_current_run_rights(
                conn, run_id=str(request.run_id)
            )
            contract = self._contract_row(conn, str(run["contract_id"]))
            duration_ms = int(
                (request.ended_at.value - request.started_at.value).total_seconds()
                * 1000
            )
            if duration_ms > int(contract["max_duration_ms"]):
                raise ExtractionStateError(
                    "extraction attempt exceeds contract duration bound"
                )
            if request.outcome in {
                ExtractionAttemptOutcome.RETRYABLE_FAILURE,
                ExtractionAttemptOutcome.BLOCKING_FAILURE,
            } and request.output_bytes != 0:
                raise ExtractionStateError(
                    "failed extraction attempt cannot claim unretained output bytes"
                )
            self._extraction_identifier_absent(
                conn,
                table="extraction_attempts",
                column="attempt_id",
                identifier=str(request.attempt_id),
                identity="extraction attempt identity",
            )
            self._extraction_semantic_absent(
                conn,
                table="extraction_attempts",
                predicate="run_id=? AND semantic_digest=?",
                parameters=(str(request.run_id), request.semantic_digest),
                identity="extraction attempt semantics",
            )
            head = conn.execute(
                "SELECT * FROM extraction_attempt_heads WHERE run_id=?",
                (str(request.run_id),),
            ).fetchone()
            if head is None:
                if request.attempt_number != 1 or request.previous_attempt_id is not None:
                    raise ExtractionVersionConflict(
                        "initial extraction attempt must be attempt one"
                    )
            elif (
                str(head["current_outcome"])
                != ExtractionAttemptOutcome.RETRYABLE_FAILURE.value
                or request.attempt_number
                != int(head["current_attempt_number"]) + 1
                or request.previous_attempt_id is None
                or str(request.previous_attempt_id)
                != str(head["current_attempt_id"])
            ):
                raise ExtractionVersionConflict(
                    "extraction retry does not extend an exact retryable head"
                )
            recorded_at = self._clock().to_text()
            committed = self._commit_grant_in_transaction(
                conn, grant, recorded_at=recorded_at
            )
            if committed.replayed:
                return self._attempt_for_event(
                    conn, committed.event_id, replayed=True
                )
            conn.execute(
                "INSERT INTO extraction_attempts("
                "attempt_id,run_id,attempt_number,previous_attempt_id,outcome,"
                "producer_execution_id,started_at,ended_at,input_bytes,output_bytes,"
                "input_tokens,output_tokens,cost_microunits,error_code,error_summary,"
                "semantic_digest,authority_event_id,authority_aggregate_version,"
                "canonical_bytes,canonical_digest,recorded_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(request.attempt_id),
                    str(request.run_id),
                    request.attempt_number,
                    None
                    if request.previous_attempt_id is None
                    else str(request.previous_attempt_id),
                    request.outcome.value,
                    request.producer_execution_id,
                    request.started_at.to_text(),
                    request.ended_at.to_text(),
                    request.input_bytes,
                    request.output_bytes,
                    request.input_tokens,
                    request.output_tokens,
                    request.cost_microunits,
                    request.error_code,
                    request.error_summary,
                    request.semantic_digest,
                    committed.event_id,
                    committed.aggregate_version,
                    request.canonical_bytes,
                    request.digest,
                    recorded_at,
                ),
            )
            return self._attempt_for_event(
                conn, committed.event_id, replayed=False
            )

    def commit_extraction_output(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        request: ExtractionOutputRequest,
    ) -> ExtractionOutput:
        if not isinstance(request, ExtractionOutputRequest):
            raise TypeError("extraction output commit requires a typed request")
        self._require_extraction_grant(
            grant,
            command_type=EXTRACTION_OUTPUT_RETAIN_COMMAND,
            aggregate_id=str(request.output_id),
            canonical_bytes=request.canonical_bytes,
        )
        with self._lock, self._transaction() as conn:
            if grant.replay_of_command_id is not None:
                committed = self._commit_grant_in_transaction(
                    conn, grant, recorded_at=self._clock().to_text()
                )
                return self._output_for_event(
                    conn, committed.event_id, replayed=True
                )
            run = self._require_current_run_rights(
                conn, run_id=str(request.run_id)
            )
            attempt = self._attempt_row(conn, str(request.attempt_id))
            if str(attempt["run_id"]) != str(request.run_id):
                raise ExtractionStateError(
                    "extraction output attempt differs from run"
                )
            contract = self._contract_row(conn, str(run["contract_id"]))
            expected_schema_digest = digest_bytes(
                bytes(contract["output_schema_contract_bytes"])
            )
            if request.output_schema_digest != expected_schema_digest:
                raise ExtractionStateError(
                    "extraction output schema differs from exact contract"
                )
            self._require_active_object_admission(
                conn,
                None
                if request.object_admission_id is None
                else str(request.object_admission_id),
            )
            self._extraction_identifier_absent(
                conn,
                table="extraction_outputs",
                column="output_id",
                identifier=str(request.output_id),
                identity="extraction output identity",
            )
            if conn.execute(
                "SELECT 1 FROM extraction_outputs WHERE attempt_id=?",
                (str(request.attempt_id),),
            ).fetchone() is not None:
                raise ExtractionSemanticCollision(
                    "extraction attempt already has retained output"
                )
            recorded_at = self._clock().to_text()
            committed = self._commit_grant_in_transaction(
                conn, grant, recorded_at=recorded_at
            )
            if committed.replayed:
                return self._output_for_event(
                    conn, committed.event_id, replayed=True
                )
            conn.execute(
                "INSERT INTO extraction_outputs("
                "output_id,run_id,attempt_id,output_kind,output_schema_digest,"
                "structured_output_bytes,object_admission_id,hydration_digest,"
                "output_digest,valid,validation_errors_bytes,retained_at,"
                "authority_event_id,authority_aggregate_version,canonical_bytes,"
                "canonical_digest,recorded_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(request.output_id),
                    str(request.run_id),
                    str(request.attempt_id),
                    request.output_kind.value,
                    request.output_schema_digest,
                    request.output_bytes,
                    None
                    if request.object_admission_id is None
                    else str(request.object_admission_id),
                    request.hydration_digest,
                    request.output_digest,
                    int(request.valid),
                    canonical_json_bytes(list(request.validation_errors)),
                    request.retained_at.to_text(),
                    committed.event_id,
                    committed.aggregate_version,
                    request.canonical_bytes,
                    request.digest,
                    recorded_at,
                ),
            )
            return self._output_for_event(
                conn, committed.event_id, replayed=False
            )

    def commit_proposal_set(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        request: ProposalSetRequest,
    ) -> ProposalSet:
        if not isinstance(request, ProposalSetRequest):
            raise TypeError("proposal set commit requires a typed request")
        self._require_extraction_grant(
            grant,
            command_type=EXTRACTION_PROPOSAL_SET_RETAIN_COMMAND,
            aggregate_id=str(request.proposal_set_id),
            canonical_bytes=request.canonical_bytes,
        )
        with self._lock, self._transaction() as conn:
            if grant.replay_of_command_id is not None:
                committed = self._commit_grant_in_transaction(
                    conn, grant, recorded_at=self._clock().to_text()
                )
                return self._proposal_set_for_event(
                    conn, committed.event_id, replayed=True
                )
            run = self._require_current_run_rights(
                conn, run_id=str(request.run_id)
            )
            attempt = self._attempt_row(conn, str(request.attempt_id))
            output = self._output_row(conn, str(request.output_id))
            if (
                str(attempt["run_id"]) != str(request.run_id)
                or str(output["run_id"]) != str(request.run_id)
                or str(output["attempt_id"]) != str(request.attempt_id)
                or int(output["valid"]) != 1
            ):
                raise ExtractionStateError(
                    "proposal set lineage requires one valid retained output"
                )
            contract = self._contract_row(conn, str(run["contract_id"]))
            if len(request.proposals) > int(contract["max_proposals"]):
                raise ExtractionStateError(
                    "proposal set exceeds extractor contract bound"
                )
            permitted_passages = {
                str(row["passage_id"])
                for row in conn.execute(
                    "SELECT passage_id FROM extraction_passages WHERE run_id=?",
                    (str(request.run_id),),
                ).fetchall()
            }
            for proposal in request.proposals:
                if not set(proposal.passage_ids) <= permitted_passages:
                    raise ExtractionStateError(
                        "proposal cites a passage outside exact run input"
                    )
                self._extraction_identifier_absent(
                    conn,
                    table="extraction_proposals",
                    column="proposal_id",
                    identifier=str(proposal.proposal_id),
                    identity="proposal identity",
                )
                if conn.execute(
                    "SELECT 1 FROM extraction_proposals WHERE canonical_digest=?",
                    (proposal.digest,),
                ).fetchone() is not None:
                    raise ExtractionSemanticCollision(
                        "proposal semantics already exist under another identity"
                    )
            self._extraction_identifier_absent(
                conn,
                table="extraction_proposal_sets",
                column="proposal_set_id",
                identifier=str(request.proposal_set_id),
                identity="proposal set identity",
            )
            self._extraction_semantic_absent(
                conn,
                table="extraction_proposal_sets",
                predicate="semantic_digest=?",
                parameters=(request.semantic_digest,),
                identity="proposal set semantics",
            )
            recorded_at = self._clock().to_text()
            committed = self._commit_grant_in_transaction(
                conn, grant, recorded_at=recorded_at
            )
            if committed.replayed:
                return self._proposal_set_for_event(
                    conn, committed.event_id, replayed=True
                )
            conn.execute(
                "INSERT INTO extraction_proposal_sets("
                "proposal_set_id,run_id,attempt_id,output_id,completeness,"
                "proposal_count,semantic_digest,retained_at,authority_event_id,"
                "authority_aggregate_version,canonical_bytes,canonical_digest,"
                "recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(request.proposal_set_id),
                    str(request.run_id),
                    str(request.attempt_id),
                    str(request.output_id),
                    request.completeness.value,
                    len(request.proposals),
                    request.semantic_digest,
                    request.retained_at.to_text(),
                    committed.event_id,
                    committed.aggregate_version,
                    request.canonical_bytes,
                    request.digest,
                    recorded_at,
                ),
            )
            for proposal in request.proposals:
                proposal_bytes = canonical_json_bytes(proposal.canonical_value())
                conn.execute(
                    "INSERT INTO extraction_proposals("
                    "proposal_id,proposal_set_id,run_id,attempt_id,output_id,"
                    "producer_local_id,proposal_kind,subject_kind,subject_bytes,"
                    "object_kind,object_bytes,predicate_hint,passage_ids_bytes,"
                    "confidence_basis_points,uncertainty,"
                    "uncertainty_reasons_bytes,attributes_bytes,canonical_bytes,"
                    "canonical_digest) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        str(proposal.proposal_id),
                        str(request.proposal_set_id),
                        str(request.run_id),
                        str(request.attempt_id),
                        str(request.output_id),
                        proposal.producer_local_id,
                        proposal.proposal_kind.value,
                        proposal.subject.kind.value,
                        canonical_json_bytes(proposal.subject.canonical_value()),
                        None
                        if proposal.object is None
                        else proposal.object.kind.value,
                        None
                        if proposal.object is None
                        else canonical_json_bytes(
                            proposal.object.canonical_value()
                        ),
                        proposal.predicate_hint,
                        canonical_json_bytes(list(proposal.passage_ids)),
                        proposal.confidence_basis_points,
                        proposal.uncertainty.value,
                        canonical_json_bytes(
                            list(proposal.uncertainty_reasons)
                        ),
                        canonical_json_bytes(proposal.attributes),
                        proposal_bytes,
                        proposal.digest,
                    ),
                )
                for passage_id in proposal.passage_ids:
                    conn.execute(
                        "INSERT INTO extraction_proposal_passages("
                        "proposal_id,run_id,passage_id) VALUES(?,?,?)",
                        (
                            str(proposal.proposal_id),
                            str(request.run_id),
                            passage_id,
                        ),
                    )
            return self._proposal_set_for_event(
                conn, committed.event_id, replayed=False
            )


__all__ = ["_ExtractionStoreCommitMixin"]
