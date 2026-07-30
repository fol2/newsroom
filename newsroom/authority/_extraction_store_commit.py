from __future__ import annotations

import sqlite3

from newsroom.authority._capability import _AuthorizedCommandGrant
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes, digest_canonical
from newsroom.authority.persistence import AuthorityPersistenceError
from newsroom.authority.types import UtcTimestamp
from newsroom.extraction.models import (
    ExtractionRunRequest,
    ExtractionRunVersion,
    ExtractorContract,
    ExtractorContractRequest,
    ProducedExtraction,
    ProposalDraft,
)
from newsroom.extraction.output_schema import validate_fixture_production
from newsroom.extraction.policy import (
    EXTRACTION_RUN_EXECUTE_COMMAND,
    EXTRACTOR_CONTRACT_REGISTER_COMMAND,
)
from newsroom.extraction.types import (
    ExtractionFailureCode,
    ExtractionOutputId,
    ProposalEnvelopeId,
    ProposalSetId,
)


class _ExtractionCommitMixin:
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
            now = self._clock()
            grant.authentication.require_current(now)
            if grant.replay_of_command_id is not None:
                committed = self._commit_grant_in_transaction(
                    conn, grant, recorded_at=now.to_text()
                )
                return self._contract_for_event(
                    conn, committed.event_id, replayed=True
                )
            self._ensure_identifier_absent(
                conn,
                table="extractor_contracts",
                column="contract_id",
                identifier=str(request.contract_id),
                identity="extractor contract identity",
            )
            self._ensure_semantic_absent(
                conn,
                table="extractor_contracts",
                column="semantic_digest",
                digest=request.semantic_digest,
                identity="extractor contract semantics",
            )
            recorded_at = now.to_text()
            committed = self._commit_grant_in_transaction(
                conn, grant, recorded_at=recorded_at
            )
            if committed.replayed:
                return self._contract_for_event(
                    conn, committed.event_id, replayed=True
                )
            components = {
                "framework": request.framework,
                "model": request.model,
                "prompt": request.prompt,
                "output_schema": request.output_schema,
                "code": request.code,
                "normalisation": request.normalisation,
                "policy": request.policy,
            }
            values: list[object] = [str(request.contract_id)]
            for component in components.values():
                values.extend(
                    (
                        component.component_id,
                        component.component_version,
                        component.contract_digest,
                    )
                )
            values.extend(
                (
                    request.execution_profile.value,
                    request.producer_kind,
                    request.semantic_digest,
                    committed.event_id,
                    committed.aggregate_version,
                    request.canonical_bytes,
                    request.digest,
                    recorded_at,
                )
            )
            conn.execute(
                "INSERT INTO extractor_contracts("
                "contract_id,framework_id,framework_version,framework_digest,"
                "model_id,model_version,model_digest,"
                "prompt_id,prompt_version,prompt_digest,"
                "output_schema_id,output_schema_version,output_schema_digest,"
                "code_id,code_version,code_digest,"
                "normalisation_id,normalisation_version,normalisation_digest,"
                "policy_id,policy_version,policy_digest,"
                "execution_profile,producer_kind,semantic_digest,"
                "authority_event_id,authority_aggregate_version,"
                "canonical_bytes,canonical_digest,recorded_at) "
                "VALUES(" + ",".join("?" for _ in values) + ")",
                tuple(values),
            )
            return self._contract_for_event(
                conn, committed.event_id, replayed=False
            )

    @staticmethod
    def _validate_produced_evidence(
        request: ExtractionRunRequest,
        production: ProducedExtraction,
    ) -> None:
        for proposal in production.proposals:
            for evidence in proposal.evidence:
                passage = request.input_binding.passage(evidence.passage_id)
                text = passage.require_text().encode("utf-8")
                if evidence.end_byte > len(text):
                    raise AuthorityPersistenceError(
                        "proposal evidence exceeds its governed passage"
                    )
                if (
                    digest_bytes(text[evidence.start_byte : evidence.end_byte])
                    != evidence.evidence_text_digest
                ):
                    raise AuthorityPersistenceError(
                        "proposal evidence digest differs from governed bytes"
                    )

    @staticmethod
    def _proposal_record_values(
        *,
        proposal_id: ProposalEnvelopeId,
        proposal_set_id: ProposalSetId,
        output_id: ExtractionOutputId,
        request: ExtractionRunRequest,
        draft: ProposalDraft,
        producer_contract_digest: str,
    ) -> tuple[dict[str, object], bytes, str]:
        value = {
            "proposal_id": str(proposal_id),
            "proposal_set_id": str(proposal_set_id),
            "output_id": str(output_id),
            "run_id": str(request.run_id),
            "run_version_id": str(request.run_version_id),
            "draft": draft.canonical_value(),
            "producer_contract_digest": producer_contract_digest,
        }
        data = canonical_json_bytes(value)
        return value, data, digest_bytes(data)

    def commit_extraction_run(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        request: ExtractionRunRequest,
        production: ProducedExtraction | None,
        started_at: UtcTimestamp | None,
        ended_at: UtcTimestamp | None,
    ) -> ExtractionRunVersion:
        if not isinstance(request, ExtractionRunRequest):
            raise TypeError("extraction run commit requires a typed request")
        self._require_extraction_grant(
            grant,
            command_type=EXTRACTION_RUN_EXECUTE_COMMAND,
            aggregate_id=str(request.run_version_id),
            canonical_bytes=request.canonical_bytes,
        )
        replay = grant.replay_of_command_id is not None
        if replay:
            if production is not None or started_at is not None or ended_at is not None:
                raise AuthorityPersistenceError(
                    "exact extraction replay must not rerun the producer"
                )
        else:
            if (
                not isinstance(production, ProducedExtraction)
                or not isinstance(started_at, UtcTimestamp)
                or not isinstance(ended_at, UtcTimestamp)
            ):
                raise TypeError("new extraction execution requires typed producer output")
            if ended_at.value < started_at.value:
                raise AuthorityPersistenceError(
                    "extraction producer ended before it started"
                )
            production.usage.require_within(
                request.budget,
                allow_elapsed_timeout=(
                    production.failure_code
                    is ExtractionFailureCode.EXECUTION_TIMEOUT
                ),
            )
            if production.usage.input_bytes != request.input_binding.input_bytes:
                raise AuthorityPersistenceError(
                    "producer input usage differs from exact passage bytes"
                )
            self._validate_produced_evidence(request, production)

        with self._lock, self._transaction() as conn:
            now = self._clock()
            grant.authentication.require_current(now)
            self._require_current_input(
                conn,
                request=request,
                now=now,
                principal_id=grant.authentication.principal_id,
                require_text=not replay,
            )
            contract_row = self._contract_row(conn, str(request.contract_id))
            if str(contract_row["producer_kind"]) != "DETERMINISTIC_FIXTURE":
                raise AuthorityPersistenceError(
                    "unapproved extractor producer entered the authority store"
                )
            if not replay:
                assert production is not None
                retained_contract = self._contract_from_row(
                    conn, contract_row, replayed=False
                )
                validate_fixture_production(
                    contract=retained_contract.request,
                    request=request,
                    production=production,
                )
            if replay:
                committed = self._commit_grant_in_transaction(
                    conn, grant, recorded_at=now.to_text()
                )
                result = self._run_version_for_event(
                    conn, committed.event_id, replayed=True
                )
                # A retained replay cannot silently bind different current input
                # metadata even though its semantic command digest already matches.
                if result.request.input_binding.digest != request.input_binding.digest:
                    raise AuthorityPersistenceError(
                        "replayed extraction input binding differs"
                    )
                return result

            assert production is not None
            assert started_at is not None
            assert ended_at is not None
            if now.value < ended_at.value:
                raise AuthorityPersistenceError(
                    "extraction retention cannot precede producer completion"
                )
            self._ensure_identifier_absent(
                conn,
                table="extraction_run_versions",
                column="run_version_id",
                identifier=str(request.run_version_id),
                identity="extraction run version identity",
            )
            if request.version_number == 1:
                self._ensure_identifier_absent(
                    conn,
                    table="extraction_runs",
                    column="run_id",
                    identifier=str(request.run_id),
                    identity="extraction run identity",
                )
                self._ensure_semantic_absent(
                    conn,
                    table="extraction_runs",
                    column="stable_semantic_digest",
                    digest=request.stable_run_semantic_digest,
                    identity="extraction run semantics",
                )
            else:
                run = self._run_row(conn, str(request.run_id))
                if (
                    str(run["contract_id"]) != str(request.contract_id)
                    or str(run["input_binding_digest"])
                    != request.input_binding.digest
                    or str(run["budget_digest"]) != request.budget.digest
                    or str(run["stable_semantic_digest"])
                    != request.stable_run_semantic_digest
                ):
                    raise AuthorityPersistenceError(
                        "later extraction version changes stable run semantics"
                    )
            self._validate_run_chain(conn, request)
            recorded_at = now.to_text()
            committed = self._commit_grant_in_transaction(
                conn, grant, recorded_at=recorded_at
            )
            if committed.replayed:
                return self._run_version_for_event(
                    conn, committed.event_id, replayed=True
                )

            if request.version_number == 1:
                stable_value = self._stable_run_value(request)
                stable_bytes = canonical_json_bytes(stable_value)
                conn.execute(
                    "INSERT INTO extraction_runs("
                    "run_id,contract_id,definition_id,definition_version_id,"
                    "item_id,revision_id,representation_id,input_binding_digest,"
                    "budget_bytes,budget_digest,stable_semantic_digest,"
                    "created_by_event_id,canonical_bytes,canonical_digest,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        str(request.run_id),
                        str(request.contract_id),
                        str(request.input_binding.definition_id),
                        str(request.input_binding.definition_version_id),
                        str(request.input_binding.item_id),
                        str(request.input_binding.revision_id),
                        str(request.input_binding.representation_id),
                        request.input_binding.digest,
                        canonical_json_bytes(request.budget.canonical_value()),
                        request.budget.digest,
                        request.stable_run_semantic_digest,
                        committed.event_id,
                        stable_bytes,
                        digest_bytes(stable_bytes),
                        recorded_at,
                    ),
                )
                for passage in request.input_binding.passages:
                    passage_bytes = canonical_json_bytes(passage.canonical_value())
                    conn.execute(
                        "INSERT INTO extraction_run_passages("
                        "run_id,passage_id,admission_id,access_decision_id,"
                        "hydration_policy_contract_digest,principal_id,"
                        "authority_domain,purpose,object_class,allowed_use,"
                        "security_scope,retention_scope,byte_offset,byte_length,"
                        "blob_digest,text_digest,language,canonical_bytes,"
                        "canonical_digest) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            str(request.run_id),
                            str(passage.passage_id),
                            str(passage.admission_id),
                            str(passage.access_decision_id),
                            passage.hydration_policy_contract_digest,
                            passage.principal_id,
                            passage.authority_domain,
                            passage.purpose,
                            passage.object_class,
                            passage.allowed_use,
                            passage.security_scope,
                            passage.retention_scope,
                            passage.byte_offset,
                            passage.byte_length,
                            passage.blob_digest,
                            passage.text_digest,
                            passage.language,
                            passage_bytes,
                            digest_bytes(passage_bytes),
                        ),
                    )

            version_value = self._run_version_value(
                request=request,
                contract_digest=str(contract_row["canonical_digest"]),
                outcome=production.outcome.value,
                failure_code=production.failure_code.value,
                started_at=started_at.to_text(),
                ended_at=ended_at.to_text(),
                usage_value=production.usage.canonical_value(),
            )
            version_bytes = canonical_json_bytes(version_value)
            usage = production.usage
            conn.execute(
                "INSERT INTO extraction_run_versions("
                "run_version_id,run_id,version_number,previous_run_version_id,"
                "contract_canonical_digest,outcome,failure_code,started_at,ended_at,"
                "elapsed_ms,input_bytes,output_bytes,proposal_count,"
                "evidence_range_count,request_tokens,response_tokens,cost_microunits,"
                "authority_event_id,authority_aggregate_version,request_bytes,"
                "request_digest,canonical_bytes,canonical_digest,recorded_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(request.run_version_id),
                    str(request.run_id),
                    request.version_number,
                    (
                        None
                        if request.expected_previous_version_id is None
                        else str(request.expected_previous_version_id)
                    ),
                    str(contract_row["canonical_digest"]),
                    production.outcome.value,
                    production.failure_code.value,
                    started_at.to_text(),
                    ended_at.to_text(),
                    usage.elapsed_ms,
                    usage.input_bytes,
                    usage.output_bytes,
                    usage.proposal_count,
                    usage.evidence_range_count,
                    usage.request_tokens,
                    usage.response_tokens,
                    usage.cost_microunits,
                    committed.event_id,
                    committed.aggregate_version,
                    request.canonical_bytes,
                    request.digest,
                    version_bytes,
                    digest_bytes(version_bytes),
                    recorded_at,
                ),
            )

            raw_output = production.raw_output_bytes
            if raw_output is not None:
                output_id = ExtractionOutputId.new()
                assert production.validation is not None
                conn.execute(
                    "INSERT INTO extraction_outputs("
                    "output_id,run_id,run_version_id,validation_state,"
                    "schema_contract_digest,byte_length,canonical_bytes,"
                    "canonical_digest,retained_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        str(output_id),
                        str(request.run_id),
                        str(request.run_version_id),
                        production.validation.value,
                        str(contract_row["output_schema_digest"]),
                        len(raw_output),
                        raw_output,
                        digest_bytes(raw_output),
                        recorded_at,
                    ),
                )
                if production.proposals:
                    proposal_set_id = ProposalSetId.new()
                    identities = [
                        (ProposalEnvelopeId.new(), draft)
                        for draft in production.proposals
                    ]
                    records = [
                        self._proposal_record_values(
                            proposal_id=proposal_id,
                            proposal_set_id=proposal_set_id,
                            output_id=output_id,
                            request=request,
                            draft=draft,
                            producer_contract_digest=str(
                                contract_row["canonical_digest"]
                            ),
                        )
                        for proposal_id, draft in identities
                    ]
                    set_value = {
                        "proposal_set_id": str(proposal_set_id),
                        "output_id": str(output_id),
                        "run_id": str(request.run_id),
                        "run_version_id": str(request.run_version_id),
                        "producer_contract_digest": str(
                            contract_row["canonical_digest"]
                        ),
                        "proposal_digests": [record[2] for record in records],
                    }
                    set_bytes = canonical_json_bytes(set_value)
                    conn.execute(
                        "INSERT INTO extraction_proposal_sets("
                        "proposal_set_id,output_id,run_id,run_version_id,"
                        "proposal_count,producer_contract_digest,canonical_bytes,"
                        "canonical_digest,retained_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            str(proposal_set_id),
                            str(output_id),
                            str(request.run_id),
                            str(request.run_version_id),
                            len(records),
                            str(contract_row["canonical_digest"]),
                            set_bytes,
                            digest_bytes(set_bytes),
                            recorded_at,
                        ),
                    )
                    for (proposal_id, draft), (_, proposal_bytes, proposal_digest) in zip(
                        identities, records, strict=True
                    ):
                        conn.execute(
                            "INSERT INTO extraction_proposals("
                            "proposal_id,proposal_set_id,output_id,run_id,"
                            "run_version_id,local_id,proposal_kind,"
                            "subject_placeholder,object_placeholder,predicate_hint,"
                            "confidence_basis_points,uncertainty_codes_bytes,"
                            "rationale_codes_bytes,producer_contract_digest,"
                            "semantic_digest,canonical_bytes,canonical_digest,"
                            "retained_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                str(proposal_id),
                                str(proposal_set_id),
                                str(output_id),
                                str(request.run_id),
                                str(request.run_version_id),
                                draft.local_id,
                                draft.kind.value,
                                draft.subject_placeholder,
                                draft.object_placeholder,
                                (
                                    None
                                    if draft.predicate_hint is None
                                    else draft.predicate_hint.value
                                ),
                                draft.confidence_basis_points,
                                canonical_json_bytes(list(draft.uncertainty_codes)),
                                canonical_json_bytes(list(draft.rationale_codes)),
                                str(contract_row["canonical_digest"]),
                                draft.digest,
                                proposal_bytes,
                                proposal_digest,
                                recorded_at,
                            ),
                        )
                        for ordinal, evidence in enumerate(draft.evidence, start=1):
                            evidence_value = {
                                "proposal_id": str(proposal_id),
                                "evidence_ordinal": ordinal,
                                "run_id": str(request.run_id),
                                **evidence.canonical_value(),
                            }
                            evidence_bytes = canonical_json_bytes(evidence_value)
                            conn.execute(
                                "INSERT INTO extraction_proposal_evidence("
                                "proposal_id,evidence_ordinal,run_id,passage_id,"
                                "start_byte,end_byte,evidence_text_digest,"
                                "canonical_bytes,canonical_digest) "
                                "VALUES(?,?,?,?,?,?,?,?,?)",
                                (
                                    str(proposal_id),
                                    ordinal,
                                    str(request.run_id),
                                    str(evidence.passage_id),
                                    evidence.start_byte,
                                    evidence.end_byte,
                                    evidence.evidence_text_digest,
                                    evidence_bytes,
                                    digest_bytes(evidence_bytes),
                                ),
                            )

            return self._run_version_for_event(
                conn, committed.event_id, replayed=False
            )


__all__ = ["_ExtractionCommitMixin"]
