from __future__ import annotations

import sqlite3
from dataclasses import replace

from newsroom.authority._capability import _AuthorizedCommandGrant
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.persistence import (
    AuthorityPersistenceError,
    ExpectedVersionConflict,
)
from newsroom.authority.types import EventId, TrustScope, UtcTimestamp
from newsroom.relations.editorial_models import (
    EDITORIAL_PREDICATE_REGISTRY_V1,
    EditorialRelationAssertion,
    ExtractionRelationEvidence,
    EditorialRelationDecision,
    EditorialRelationDecisionRequest,
    EditorialRelationProposalRequest,
    evidence_canonical_value,
    endpoint_canonical_value,
)
from newsroom.relations.editorial_policy import (
    EDITORIAL_RELATION_DECISION_COMMAND,
    EDITORIAL_RELATION_PROPOSAL_COMMAND,
)
from newsroom.relations.editorial_types import (
    EditorialRelationAssertionLifecycle,
    EditorialRelationCurrentState,
    EditorialRelationDecisionAction,
    EditorialRelationDecisionConflict,
    EditorialRelationIdentifierReuse,
    EditorialRelationProjectionAction,
    EditorialRelationStaleDecision,
    EditorialRelationStateError,
)

from ._editorial_relation_store_common import (
    deterministic_editorial_projection_event_id,
)


_STATE_BY_ACTION = {
    EditorialRelationDecisionAction.ACCEPT: EditorialRelationCurrentState.ADMITTED,
    EditorialRelationDecisionAction.REJECT: EditorialRelationCurrentState.REJECTED,
    EditorialRelationDecisionAction.HOLD: EditorialRelationCurrentState.HELD,
    EditorialRelationDecisionAction.UNRESOLVED: EditorialRelationCurrentState.UNRESOLVED,
    EditorialRelationDecisionAction.INVALIDATE: EditorialRelationCurrentState.INVALIDATED,
    EditorialRelationDecisionAction.REVOKE: EditorialRelationCurrentState.REVOKED,
    EditorialRelationDecisionAction.SUPERSEDE: EditorialRelationCurrentState.SUPERSEDED,
}

_LIFECYCLE_BY_ACTION = {
    EditorialRelationDecisionAction.INVALIDATE: EditorialRelationAssertionLifecycle.INVALIDATED,
    EditorialRelationDecisionAction.REVOKE: EditorialRelationAssertionLifecycle.REVOKED,
    EditorialRelationDecisionAction.SUPERSEDE: EditorialRelationAssertionLifecycle.SUPERSEDED,
}


class _EditorialRelationCommitMixin:
    def commit_editorial_relation_proposal(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        request: EditorialRelationProposalRequest,
    ):
        if not isinstance(request, EditorialRelationProposalRequest):
            raise TypeError("relation proposal commit requires a typed request")
        self._require_editorial_relation_grant(
            grant,
            command_type=EDITORIAL_RELATION_PROPOSAL_COMMAND,
            aggregate_id=str(request.proposal_version_id),
            canonical_bytes=request.canonical_bytes,
        )
        with self._lock, self._transaction() as conn:
            now = self._clock()
            grant.authentication.require_current(now)
            recorded_at = now.to_text()
            # Reconcile idempotency inside the serialized transaction. Two callers
            # can both be authorized before either commits; the second must become
            # exact replay rather than a stale-head failure.
            try:
                committed = self._commit_grant_in_transaction(
                    conn, grant, recorded_at=recorded_at
                )
            except ExpectedVersionConflict as exc:
                if conn.execute(
                    "SELECT 1 FROM editorial_relation_proposal_versions "
                    "WHERE proposal_version_id=?",
                    (str(request.proposal_version_id),),
                ).fetchone() is not None:
                    raise EditorialRelationIdentifierReuse(
                        "editorial relation proposal version identity is already retained"
                    ) from exc
                raise
            if committed.replayed:
                row = self._editorial_row_for_event(
                    conn,
                    table="editorial_relation_proposal_versions",
                    event_id=committed.event_id,
                    identity="editorial relation proposal version",
                )
                result = self._editorial_proposal_version_from_row(
                    conn, row, replayed=True
                )
                self._validate_editorial_evidence_current(conn, result.evidence)
                return result

            self._require_editorial_endpoint_current(conn, request.subject)
            self._require_editorial_endpoint_current(conn, request.object)
            self._validate_editorial_evidence_current(conn, request.evidence)
            source_ids = frozenset(
                str(item.source_proposal_id)
                for item in request.evidence
                if isinstance(item, ExtractionRelationEvidence)
            )
            self._editorial_dependencies_from_ids(
                conn,
                request.resolution_dependency_ids,
                require_accepted=False,
                source_proposal_ids=source_ids,
            )

            head = self._editorial_proposal_head_row(conn, request.proposal_id)
            if request.version_number == 1:
                if head is not None:
                    raise EditorialRelationStaleDecision(
                        "initial relation proposal already has a head"
                    )
                self._editorial_ensure_identifier_absent(
                    conn,
                    table="editorial_relation_proposals",
                    column="proposal_id",
                    identifier=str(request.proposal_id),
                    identity="editorial relation proposal identity",
                )
                self._editorial_ensure_semantic_absent(
                    conn,
                    table="editorial_relation_proposals",
                    column="stable_semantic_digest",
                    digest=request.stable_semantic_digest,
                    identity="editorial relation proposal semantics",
                )
            else:
                if (
                    head is None
                    or int(head["current_version_number"])
                    != request.version_number - 1
                    or str(head["current_proposal_version_id"])
                    != str(request.expected_previous_version_id)
                ):
                    raise EditorialRelationStaleDecision(
                        "relation proposal does not extend the current head"
                    )
                if self._editorial_decision_head_row(conn, request.proposal_id) is not None:
                    raise EditorialRelationStateError(
                        "decided relation proposal cannot receive a new version"
                    )
                base = conn.execute(
                    "SELECT stable_semantic_digest FROM editorial_relation_proposals "
                    "WHERE proposal_id=?",
                    (str(request.proposal_id),),
                ).fetchone()
                if (
                    base is None
                    or str(base["stable_semantic_digest"])
                    != request.stable_semantic_digest
                ):
                    raise EditorialRelationSemanticCollision(
                        "relation proposal version changes stable semantics"
                    )
            self._editorial_ensure_identifier_absent(
                conn,
                table="editorial_relation_proposal_versions",
                column="proposal_version_id",
                identifier=str(request.proposal_version_id),
                identity="editorial relation proposal version identity",
            )

            subject_digest = self._retain_editorial_endpoint(conn, request.subject)
            object_digest = self._retain_editorial_endpoint(conn, request.object)

            if request.version_number == 1:
                contract = EDITORIAL_PREDICATE_REGISTRY_V1.contract(
                    request.predicate
                )
                base_value = {
                    "proposal_id": str(request.proposal_id),
                    "registry_version": EDITORIAL_PREDICATE_REGISTRY_V1.registry_version,
                    "predicate_registry_digest": request.predicate_registry_digest,
                    "predicate": request.predicate.value,
                    "predicate_contract_version": contract.contract_version,
                    "predicate_contract_digest": request.predicate_contract_digest,
                    "subject": endpoint_canonical_value(request.subject),
                    "object": endpoint_canonical_value(request.object),
                    "producer": request.producer.canonical_value(),
                    "semantic_slot_digest": request.semantic_slot_digest,
                    "stable_semantic_digest": request.stable_semantic_digest,
                }
                base_bytes = canonical_json_bytes(base_value)
                conn.execute(
                    "INSERT INTO editorial_relation_proposals("
                    "proposal_id,registry_version,predicate_registry_digest,predicate,"
                    "predicate_contract_version,predicate_contract_digest,"
                    "subject_endpoint_digest,object_endpoint_digest,producer_kind,"
                    "producer_id,producer_version,producer_contract_digest,"
                    "semantic_slot_digest,stable_semantic_digest,created_by_event_id,"
                    "canonical_bytes,canonical_digest,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        str(request.proposal_id),
                        EDITORIAL_PREDICATE_REGISTRY_V1.registry_version,
                        request.predicate_registry_digest,
                        request.predicate.value,
                        contract.contract_version,
                        request.predicate_contract_digest,
                        subject_digest,
                        object_digest,
                        request.producer.kind.value,
                        request.producer.producer_id,
                        request.producer.producer_version,
                        request.producer.contract_digest,
                        request.semantic_slot_digest,
                        request.stable_semantic_digest,
                        committed.event_id,
                        base_bytes,
                        digest_bytes(base_bytes),
                        recorded_at,
                    ),
                )

            conn.execute(
                "INSERT INTO editorial_relation_proposal_versions("
                "proposal_version_id,proposal_id,version_number,"
                "previous_proposal_version_id,valid_from,valid_until,observed_at,"
                "statement,confidence_basis_points,uncertainty_codes_bytes,"
                "basis_codes_bytes,request_bytes,request_digest,canonical_bytes,"
                "canonical_digest,authority_event_id,authority_ledger_seq,"
                "authority_aggregate_version,recorded_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(request.proposal_version_id),
                    str(request.proposal_id),
                    request.version_number,
                    (
                        None
                        if request.expected_previous_version_id is None
                        else str(request.expected_previous_version_id)
                    ),
                    (
                        None
                        if request.temporal_scope.valid_from is None
                        else request.temporal_scope.valid_from.to_text()
                    ),
                    (
                        None
                        if request.temporal_scope.valid_until is None
                        else request.temporal_scope.valid_until.to_text()
                    ),
                    request.temporal_scope.observed_at.to_text(),
                    request.statement,
                    request.confidence_basis_points,
                    canonical_json_bytes(list(request.uncertainty_codes)),
                    canonical_json_bytes(list(request.basis_codes)),
                    request.canonical_bytes,
                    request.canonical_digest,
                    request.canonical_bytes,
                    request.canonical_digest,
                    committed.event_id,
                    committed.ledger_seq,
                    committed.aggregate_version,
                    recorded_at,
                ),
            )
            for ordinal, evidence in enumerate(request.evidence):
                data = evidence.canonical_bytes
                conn.execute(
                    "INSERT INTO editorial_relation_evidence_items("
                    "proposal_version_id,evidence_ordinal,evidence_kind,"
                    "canonical_bytes,canonical_digest) VALUES(?,?,?,?,?)",
                    (
                        str(request.proposal_version_id),
                        ordinal,
                        evidence.kind.value,
                        data,
                        digest_bytes(data),
                    ),
                )
                if evidence.kind.value == "EXTRACTION_PROPOSAL":
                    conn.execute(
                        "INSERT INTO editorial_relation_extraction_evidence("
                        "proposal_version_id,evidence_ordinal,source_proposal_id,"
                        "source_evidence_ordinal,source_proposal_digest,run_id,"
                        "run_version_id,output_id,passage_id,start_byte,end_byte,"
                        "evidence_text_digest) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            str(request.proposal_version_id),
                            ordinal,
                            str(evidence.source_proposal_id),
                            evidence.source_evidence_ordinal + 1,
                            evidence.source_proposal_digest,
                            str(evidence.run_id),
                            str(evidence.run_version_id),
                            str(evidence.output_id),
                            str(evidence.passage_id),
                            evidence.start_byte,
                            evidence.end_byte,
                            evidence.evidence_text_digest,
                        ),
                    )
                else:
                    conn.execute(
                        "INSERT INTO editorial_relation_workflow_evidence("
                        "proposal_version_id,evidence_ordinal,authority_event_id,"
                        "aggregate_type,aggregate_id,aggregate_version,event_digest) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (
                            str(request.proposal_version_id),
                            ordinal,
                            str(evidence.authority_event_id),
                            evidence.aggregate_type,
                            evidence.aggregate_id,
                            evidence.aggregate_version,
                            evidence.event_digest,
                        ),
                    )
            for ordinal, dependency_id in enumerate(
                request.resolution_dependency_ids
            ):
                conn.execute(
                    "INSERT INTO editorial_relation_resolution_dependencies("
                    "proposal_version_id,dependency_ordinal,dependency_id) "
                    "VALUES(?,?,?)",
                    (str(request.proposal_version_id), ordinal, str(dependency_id)),
                )
            if request.version_number == 1:
                conn.execute(
                    "INSERT INTO editorial_relation_proposal_heads("
                    "proposal_id,current_version_number,current_proposal_version_id,"
                    "updated_at) VALUES(?,?,?,?)",
                    (
                        str(request.proposal_id),
                        request.version_number,
                        str(request.proposal_version_id),
                        recorded_at,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE editorial_relation_proposal_heads SET "
                    "current_version_number=?,current_proposal_version_id=?,updated_at=? "
                    "WHERE proposal_id=?",
                    (
                        request.version_number,
                        str(request.proposal_version_id),
                        recorded_at,
                        str(request.proposal_id),
                    ),
                )
            row = self._editorial_row_for_event(
                conn,
                table="editorial_relation_proposal_versions",
                event_id=committed.event_id,
                identity="editorial relation proposal version",
            )
            return self._editorial_proposal_version_from_row(
                conn, row, replayed=False
            )

    def _editorial_assertion_value(
        self,
        *,
        assertion: EditorialRelationAssertion,
    ) -> dict[str, object]:
        return {
            "assertion_id": str(assertion.assertion_id),
            "proposal_id": str(assertion.proposal_id),
            "proposal_version_id": str(assertion.proposal_version_id),
            "predicate_registry_digest": assertion.predicate_registry_digest,
            "predicate_contract_digest": assertion.predicate_contract_digest,
            "predicate": assertion.predicate.value,
            "subject": endpoint_canonical_value(assertion.subject),
            "object": endpoint_canonical_value(assertion.object),
            "temporal_scope": assertion.temporal_scope.canonical_value(),
            "evidence": [evidence_canonical_value(item) for item in assertion.evidence],
            "resolution_dependency_ids": [
                str(item) for item in assertion.resolution_dependency_ids
            ],
            "producer": assertion.producer.canonical_value(),
            "statement": assertion.statement,
            "uncertainty_codes": list(assertion.uncertainty_codes),
            "trust_scope": assertion.trust_scope.value,
            "admission_decision_id": str(assertion.admission_decision_id),
            "admitted_at": assertion.admitted_at.to_text(),
        }

    def _insert_editorial_projection_event(
        self,
        conn: sqlite3.Connection,
        *,
        decision: EditorialRelationDecision,
        assertion: EditorialRelationAssertion | None,
        assertion_id,
        action: EditorialRelationProjectionAction,
        lifecycle: EditorialRelationAssertionLifecycle,
    ) -> None:
        event_id = deterministic_editorial_projection_event_id(
            source_event_id=decision.authority_event_id,
            assertion_id=assertion_id,
        )
        value = {
            "projection_event_id": str(event_id),
            "source_event_id": str(decision.authority_event_id),
            "source_ledger_seq": decision.authority_ledger_seq,
            "action": action.value,
            "assertion_id": str(assertion_id),
            "assertion_digest": (
                None if assertion is None else assertion.canonical_digest
            ),
            "lifecycle": lifecycle.value,
            "recorded_at": decision.recorded_at.to_text(),
        }
        data = canonical_json_bytes(value)
        conn.execute(
            "INSERT INTO editorial_relation_projection_events("
            "projection_event_id,source_event_id,source_ledger_seq,action,"
            "assertion_id,lifecycle,canonical_bytes,canonical_digest,recorded_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (
                str(event_id),
                str(decision.authority_event_id),
                decision.authority_ledger_seq,
                action.value,
                str(assertion_id),
                lifecycle.value,
                data,
                digest_bytes(data),
                decision.recorded_at.to_text(),
            ),
        )

    def commit_editorial_relation_decision(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        request: EditorialRelationDecisionRequest,
    ) -> EditorialRelationDecision:
        if not isinstance(request, EditorialRelationDecisionRequest):
            raise TypeError("relation decision commit requires a typed request")
        self._require_editorial_relation_grant(
            grant,
            command_type=EDITORIAL_RELATION_DECISION_COMMAND,
            aggregate_id=str(request.decision_id),
            canonical_bytes=request.canonical_bytes,
        )
        with self._lock, self._transaction() as conn:
            now = self._clock()
            grant.authentication.require_current(now)
            recorded_at = now.to_text()
            # Recheck idempotency under the sole-writer lock so an identical
            # concurrent decision returns the retained decision rather than stale.
            try:
                committed = self._commit_grant_in_transaction(
                    conn, grant, recorded_at=recorded_at
                )
            except ExpectedVersionConflict as exc:
                if conn.execute(
                    "SELECT 1 FROM editorial_relation_decisions WHERE decision_id=?",
                    (str(request.decision_id),),
                ).fetchone() is not None:
                    raise EditorialRelationIdentifierReuse(
                        "editorial relation decision identity is already retained"
                    ) from exc
                raise
            if committed.replayed:
                row = self._editorial_row_for_event(
                    conn,
                    table="editorial_relation_decisions",
                    event_id=committed.event_id,
                    identity="editorial relation decision",
                )
                return self._editorial_decision_from_row(conn, row, replayed=True)

            proposal_version = self._require_editorial_proposal_version_current(
                conn,
                request.proposal_version_id,
                require_dependencies_accepted=(
                    request.action is EditorialRelationDecisionAction.ACCEPT
                ),
            )
            if (
                proposal_version.proposal_id != request.proposal_id
                or proposal_version.canonical_digest
                != request.expected_proposal_version_digest
            ):
                raise EditorialRelationStaleDecision(
                    "relation decision does not name the exact current proposal"
                )
            head = self._editorial_decision_head_row(conn, request.proposal_id)
            if request.expected_previous_decision_version == 0:
                if head is not None or request.expected_previous_decision_id is not None:
                    raise EditorialRelationStaleDecision(
                        "first relation decision already has a head"
                    )
            else:
                if (
                    head is None
                    or int(head["current_decision_version"])
                    != request.expected_previous_decision_version
                    or str(head["current_decision_id"])
                    != str(request.expected_previous_decision_id)
                ):
                    raise EditorialRelationStaleDecision(
                        "relation decision does not extend the current head"
                    )

            current_state = (
                EditorialRelationCurrentState.PROPOSED
                if head is None
                else EditorialRelationCurrentState(str(head["current_state"]))
            )
            if request.action.is_admission:
                if current_state in {
                    EditorialRelationCurrentState.REJECTED,
                    EditorialRelationCurrentState.ADMITTED,
                    EditorialRelationCurrentState.INVALIDATED,
                    EditorialRelationCurrentState.REVOKED,
                    EditorialRelationCurrentState.SUPERSEDED,
                }:
                    raise EditorialRelationDecisionConflict(
                        "terminal relation proposal cannot receive another admission decision"
                    )
            else:
                if current_state is not EditorialRelationCurrentState.ADMITTED:
                    raise EditorialRelationDecisionConflict(
                        "relation lifecycle decision requires an admitted assertion"
                    )
                assert request.target_assertion_id is not None
                target = self._require_editorial_assertion_current(
                    conn, request.target_assertion_id
                )
                if (
                    target.proposal_id != request.proposal_id
                    or target.proposal_version_id != request.proposal_version_id
                ):
                    raise EditorialRelationDecisionConflict(
                        "relation lifecycle decision targets another proposal"
                    )
                if request.action is EditorialRelationDecisionAction.SUPERSEDE:
                    assert request.successor_assertion_id is not None
                    self._require_editorial_assertion_current(
                        conn, request.successor_assertion_id
                    )

            self._editorial_ensure_identifier_absent(
                conn,
                table="editorial_relation_decisions",
                column="decision_id",
                identifier=str(request.decision_id),
                identity="editorial relation decision identity",
            )
            if request.action is EditorialRelationDecisionAction.ACCEPT:
                assert request.assertion_id is not None
                self._editorial_ensure_identifier_absent(
                    conn,
                    table="editorial_relation_assertions",
                    column="assertion_id",
                    identifier=str(request.assertion_id),
                    identity="editorial relation assertion identity",
                )

            decision_version = request.expected_previous_decision_version + 1
            conn.execute(
                "INSERT INTO editorial_relation_decisions("
                "decision_id,proposal_id,proposal_version_id,proposal_version_digest,"
                "decision_version,previous_decision_id,action,assertion_id,"
                "target_assertion_id,successor_assertion_id,supersession_id,"
                "reason_code,decision_policy_version,authority_event_id,"
                "authority_ledger_seq,authority_aggregate_version,canonical_bytes,"
                "canonical_digest,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(request.decision_id),
                    str(request.proposal_id),
                    str(request.proposal_version_id),
                    request.expected_proposal_version_digest,
                    decision_version,
                    (
                        None
                        if request.expected_previous_decision_id is None
                        else str(request.expected_previous_decision_id)
                    ),
                    request.action.value,
                    None if request.assertion_id is None else str(request.assertion_id),
                    (
                        None
                        if request.target_assertion_id is None
                        else str(request.target_assertion_id)
                    ),
                    (
                        None
                        if request.successor_assertion_id is None
                        else str(request.successor_assertion_id)
                    ),
                    (
                        None
                        if request.supersession_id is None
                        else str(request.supersession_id)
                    ),
                    request.reason_code,
                    request.decision_policy_version,
                    committed.event_id,
                    committed.ledger_seq,
                    committed.aggregate_version,
                    request.canonical_bytes,
                    request.canonical_digest,
                    recorded_at,
                ),
            )
            decision = EditorialRelationDecision(
                decision_id=request.decision_id,
                action=request.action,
                proposal_id=request.proposal_id,
                proposal_version_id=request.proposal_version_id,
                proposal_version_digest=request.expected_proposal_version_digest,
                decision_version=decision_version,
                previous_decision_id=request.expected_previous_decision_id,
                assertion_id=request.assertion_id,
                target_assertion_id=request.target_assertion_id,
                successor_assertion_id=request.successor_assertion_id,
                supersession_id=request.supersession_id,
                reason_code=request.reason_code,
                decision_policy_version=request.decision_policy_version,
                authority_event_id=EventId.parse(committed.event_id),
                authority_ledger_seq=committed.ledger_seq,
                canonical_digest=request.canonical_digest,
                recorded_at=UtcTimestamp.parse(recorded_at),
                replayed=False,
            )

            assertion = None
            if request.action is EditorialRelationDecisionAction.ACCEPT:
                assert request.assertion_id is not None
                proposal_row = self._editorial_required_row(
                    conn,
                    table="editorial_relation_proposals",
                    column="proposal_id",
                    identifier=str(request.proposal_id),
                    identity="editorial relation proposal",
                )
                proposal = self._editorial_proposal_from_row(conn, proposal_row)
                assertion = EditorialRelationAssertion(
                    assertion_id=request.assertion_id,
                    proposal_id=request.proposal_id,
                    proposal_version_id=request.proposal_version_id,
                    predicate_registry_digest=proposal.predicate_registry_digest,
                    predicate_contract_digest=proposal.predicate_contract_digest,
                    predicate=proposal.predicate,
                    subject=proposal.subject,
                    object=proposal.object,
                    temporal_scope=proposal_version.temporal_scope,
                    evidence=proposal_version.evidence,
                    resolution_dependency_ids=(
                        proposal_version.resolution_dependency_ids
                    ),
                    producer=proposal.producer,
                    statement=proposal_version.statement,
                    uncertainty_codes=proposal_version.uncertainty_codes,
                    trust_scope=TrustScope.ADMITTED,
                    admission_decision_id=request.decision_id,
                    admitted_at=UtcTimestamp.parse(recorded_at),
                    canonical_digest="",
                )
                assertion_data = canonical_json_bytes(
                    self._editorial_assertion_value(assertion=assertion)
                )
                assertion = replace(
                    assertion, canonical_digest=digest_bytes(assertion_data)
                )
                if conn.execute(
                    "SELECT 1 FROM editorial_relation_assertions WHERE relation_key=?",
                    (assertion.relation_key,),
                ).fetchone() is not None:
                    raise EditorialRelationSemanticCollision(
                        "equivalent admitted relation already exists"
                    )
                proposal_base = self._editorial_required_row(
                    conn,
                    table="editorial_relation_proposals",
                    column="proposal_id",
                    identifier=str(request.proposal_id),
                    identity="editorial relation proposal",
                )
                contract = EDITORIAL_PREDICATE_REGISTRY_V1.contract(
                    proposal.predicate
                )
                conn.execute(
                    "INSERT INTO editorial_relation_assertions("
                    "assertion_id,proposal_id,proposal_version_id,admission_decision_id,"
                    "registry_version,predicate_registry_digest,predicate,"
                    "predicate_contract_version,predicate_contract_digest,"
                    "subject_endpoint_digest,object_endpoint_digest,valid_from,"
                    "valid_until,observed_at,producer_kind,producer_id,producer_version,"
                    "producer_contract_digest,statement,uncertainty_codes_bytes,"
                    "relation_key,trust_scope,proposal_version_digest,canonical_bytes,"
                    "canonical_digest,admitted_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        str(assertion.assertion_id),
                        str(assertion.proposal_id),
                        str(assertion.proposal_version_id),
                        str(request.decision_id),
                        EDITORIAL_PREDICATE_REGISTRY_V1.registry_version,
                        assertion.predicate_registry_digest,
                        assertion.predicate.value,
                        contract.contract_version,
                        assertion.predicate_contract_digest,
                        str(proposal_base["subject_endpoint_digest"]),
                        str(proposal_base["object_endpoint_digest"]),
                        (
                            None
                            if assertion.temporal_scope.valid_from is None
                            else assertion.temporal_scope.valid_from.to_text()
                        ),
                        (
                            None
                            if assertion.temporal_scope.valid_until is None
                            else assertion.temporal_scope.valid_until.to_text()
                        ),
                        assertion.temporal_scope.observed_at.to_text(),
                        assertion.producer.kind.value,
                        assertion.producer.producer_id,
                        assertion.producer.producer_version,
                        assertion.producer.contract_digest,
                        assertion.statement,
                        canonical_json_bytes(list(assertion.uncertainty_codes)),
                        assertion.relation_key,
                        assertion.trust_scope.value,
                        proposal_version.canonical_digest,
                        assertion_data,
                        assertion.canonical_digest,
                        recorded_at,
                    ),
                )
                conn.execute(
                    "INSERT INTO editorial_relation_assertion_heads("
                    "assertion_id,lifecycle,current_decision_id,"
                    "current_decision_version,updated_at) VALUES(?,?,?,?,?)",
                    (
                        str(assertion.assertion_id),
                        EditorialRelationAssertionLifecycle.ACTIVE.value,
                        str(request.decision_id),
                        decision_version,
                        recorded_at,
                    ),
                )

            state = _STATE_BY_ACTION[request.action]
            if head is None:
                conn.execute(
                    "INSERT INTO editorial_relation_decision_heads("
                    "proposal_id,current_decision_version,current_decision_id,"
                    "current_state,updated_at) VALUES(?,?,?,?,?)",
                    (
                        str(request.proposal_id),
                        decision_version,
                        str(request.decision_id),
                        state.value,
                        recorded_at,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE editorial_relation_decision_heads SET "
                    "current_decision_version=?,current_decision_id=?,"
                    "current_state=?,updated_at=? WHERE proposal_id=?",
                    (
                        decision_version,
                        str(request.decision_id),
                        state.value,
                        recorded_at,
                        str(request.proposal_id),
                    ),
                )

            if request.action is EditorialRelationDecisionAction.ACCEPT:
                assert assertion is not None
                self._insert_editorial_projection_event(
                    conn,
                    decision=decision,
                    assertion=assertion,
                    assertion_id=assertion.assertion_id,
                    action=EditorialRelationProjectionAction.UPSERT,
                    lifecycle=EditorialRelationAssertionLifecycle.ACTIVE,
                )
            elif request.action.is_lifecycle:
                assert request.target_assertion_id is not None
                lifecycle = _LIFECYCLE_BY_ACTION[request.action]
                conn.execute(
                    "UPDATE editorial_relation_assertion_heads SET "
                    "lifecycle=?,current_decision_id=?,current_decision_version=?,"
                    "updated_at=? WHERE assertion_id=?",
                    (
                        lifecycle.value,
                        str(request.decision_id),
                        decision_version,
                        recorded_at,
                        str(request.target_assertion_id),
                    ),
                )
                if request.action is EditorialRelationDecisionAction.SUPERSEDE:
                    assert request.supersession_id is not None
                    assert request.successor_assertion_id is not None
                    value = {
                        "supersession_id": str(request.supersession_id),
                        "decision_id": str(request.decision_id),
                        "predecessor_assertion_id": str(request.target_assertion_id),
                        "successor_assertion_id": str(request.successor_assertion_id),
                        "recorded_at": recorded_at,
                    }
                    data = canonical_json_bytes(value)
                    conn.execute(
                        "INSERT INTO editorial_relation_supersessions("
                        "supersession_id,decision_id,predecessor_assertion_id,"
                        "successor_assertion_id,canonical_bytes,canonical_digest,"
                        "recorded_at) VALUES(?,?,?,?,?,?,?)",
                        (
                            str(request.supersession_id),
                            str(request.decision_id),
                            str(request.target_assertion_id),
                            str(request.successor_assertion_id),
                            data,
                            digest_bytes(data),
                            recorded_at,
                        ),
                    )
                self._insert_editorial_projection_event(
                    conn,
                    decision=decision,
                    assertion=None,
                    assertion_id=request.target_assertion_id,
                    action=EditorialRelationProjectionAction.REMOVE,
                    lifecycle=lifecycle,
                )

            row = self._editorial_row_for_event(
                conn,
                table="editorial_relation_decisions",
                event_id=committed.event_id,
                identity="editorial relation decision",
            )
            return self._editorial_decision_from_row(conn, row, replayed=False)


# Imported late to avoid a cycle in the class body.
from newsroom.relations.editorial_types import EditorialRelationSemanticCollision


__all__ = ["_EditorialRelationCommitMixin"]
