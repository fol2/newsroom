from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

import pytest

from newsroom.authority import (
    AuthenticationProof,
    StaticAuthenticator,
    StaticAuthorizer,
    StaticPrincipal,
)
from newsroom.authority.development_candidate_system import (
    open_complete_fixture_candidate_authority_system,
)
from newsroom.authority.persistence import AuthorityPersistenceError
from newsroom.increment2 import (
    INTEGRATED_FIXTURE_V2_DEVELOPMENT_CANDIDATE,
    Increment2CompleteProofController,
    Increment2PreparedAuthority,
    Increment2ProofEnvironment,
    Increment2ProofKeys,
    Increment2ProofStateError,
)
from newsroom.integrated import CandidateAdmissionOutcome, IntegratedTriageProposalId
from newsroom.projection import (
    CompleteProjectionProfile,
    INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID,
    ProjectionGenerationPromotionRequest,
    ProjectionGenerationState,
)
from newsroom.projection.neo4j import (
    CompleteDeliveryRequest,
    CompleteGenerationQualificationRequest,
    CompleteGenerationValidationRequest,
    CompleteRebuildRequest,
    Neo4jIdentityConflict,
    Neo4jProjectorConfig,
)
from newsroom.projection.neo4j._complete_adapter import (
    _open_complete_neo4j_adapter,
)
from newsroom.relations import (
    INTEGRATED_FIXTURE_V2,
    INTEGRATED_FIXTURE_V2_BINDING_ID,
    RelationCurrentState,
    RelationDecisionAction,
    RelationPredicate,
    RelationProducer,
    RelationProducerKind,
    RelationProposalId,
)
from newsroom.retrieval import (
    INTEGRATED_FIXTURE_V2_RETRIEVAL,
    RetrievalContextV2Id,
    RetrievalOutcome,
    RetrievalRequestId,
    RetrievalStateError,
)

from .authority_a2b_helpers import _policy_registries
from .authority_event_helpers import payload_schemas
from .complete_projection_2b_helpers import (
    COMPLETE_NOW,
    complete_contract_registry,
    proof,
    register_complete_generation,
)
from .increment_2d_helpers import (
    _current_generation,
    _latest_complete_source_ledger_seq,
    _rebuild_generation,
    block_active_candidate_generation,
    candidate_request,
    fixture_passage_admission_id,
    object_limits,
    open_candidate_complete_system,
    open_candidate_object_system,
    open_candidate_relation_system,
    retained_relation_identities,
    retrieval_request,
    scopes,
)
from .projection_b1_helpers import source_command_registry
from .relation_2a_helpers import decision_request
from .test_complete_projection_2b_neo4j_service import (
    _cleanup_generation,
    _names,
    _projector_scalar,
    _projector_write,
    _setup,
)


_REQUIRED_FLAG = "NEWSROOM_NEO4J_INCREMENT_2D_SERVICE_REQUIRED"


def _service_config() -> Neo4jProjectorConfig:
    if os.environ.get(_REQUIRED_FLAG) != "1":
        pytest.skip("complete Increment 2D actual Neo4j service is required")
    return Neo4jProjectorConfig.from_environment()


def _open_candidate(database: Path, object_root: Path):
    rights, hydration, admissions = _policy_registries()
    return open_complete_fixture_candidate_authority_system(
        path=database,
        object_root=object_root,
        object_limits=object_limits(),
        registry=source_command_registry(),
        payload_schemas=payload_schemas(),
        contracts=complete_contract_registry(),
        admission_registry=admissions,
        rights_policies=rights,
        hydration_policies=hydration,
        authenticator=StaticAuthenticator(
            credentials={"token-1": StaticPrincipal("principal.alpha")},
            authority_domain="newsroom.authority",
        ),
        authorizer=StaticAuthorizer(
            policy_version="increment-2d-actual-service-authz-v1",
            grants_by_principal={"principal.alpha": scopes()},
        ),
        neo4j_config=_service_config(),
        clock=lambda: COMPLETE_NOW,
    )


def _keys(prefix: str) -> Increment2ProofKeys:
    return Increment2ProofKeys(
        request_id=RetrievalRequestId.new(),
        context_id=RetrievalContextV2Id.new(),
        proposal_id=IntegratedTriageProposalId.new(),
        retrieval_idempotency_key=f"{prefix}-retrieval-{uuid4().hex}",
        candidate_idempotency_key=f"{prefix}-candidate-{uuid4().hex}",
    )




def _retain_unadmitted_same_event_proposal(database: Path) -> RelationProposalId:
    proposal_id = RelationProposalId.new()
    request = replace(
        INTEGRATED_FIXTURE_V2.relation.request(
            proposal_id=proposal_id,
            fixture_binding_id=INTEGRATED_FIXTURE_V2_BINDING_ID,
            idempotency_key=f"increment-2d-actual-same-event-{uuid4().hex}",
        ),
        predicate=RelationPredicate.SAME_EVENT_AS,
        producer=RelationProducer(
            RelationProducerKind.AUTHORISED_OPERATOR,
            "increment-2d-fixture-reviewer",
            "increment-2d-fixture-reviewer-v1",
            "increment-2d-same-event-distractor-v1",
        ),
        statement=(
            "This synthetic SAME_EVENT_AS proposal is retained only as an "
            "unadmitted Increment 2D distractor."
        ),
    )
    system = open_candidate_relation_system(database)
    try:
        retained = system.relations.propose(request, proof=proof())
        assert retained.proposal_id == proposal_id
        assert retained.predicate is RelationPredicate.SAME_EVENT_AS
    finally:
        system.close()
    return proposal_id

def _candidate_counts(database: Path) -> tuple[int, int, int]:
    with sqlite3.connect(database) as conn:
        return tuple(
            int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "development_candidates_v2",
                "development_candidate_versions_v2",
                "development_candidate_admission_decisions_v2",
            )
        )


def _authenticated_current(complete_system, generation_id, authentication):
    return next(
        item
        for item in complete_system.projections.generations(
            INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID,
            proof=authentication,
        )
        if item.generation_id == generation_id
    )


def _activate_initial(
    complete_system,
    generation,
    database: Path,
    *,
    authentication: AuthenticationProof,
) -> Increment2PreparedAuthority:
    if not isinstance(authentication, AuthenticationProof):
        raise TypeError("complete proof preparation authentication must be typed")
    rebuilt = complete_system.complete.rebuild(
        CompleteRebuildRequest(
            generation_id=generation.generation_id,
            expected_authority_version=generation.authority_aggregate_version,
            through_ledger_seq=_latest_complete_source_ledger_seq(database),
            reason_code="INCREMENT_2D_COMPLETE_PROOF_REBUILD",
            idempotency_key=f"increment-2d-service-rebuild-{uuid4().hex}",
        ),
        proof=authentication,
    )
    current = _authenticated_current(
        complete_system,
        generation.generation_id,
        authentication,
    )
    validation = complete_system.complete.validate_generation(
        CompleteGenerationValidationRequest(
            generation_id=generation.generation_id,
            expected_authority_version=current.authority_aggregate_version,
            checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
            reason_code="INCREMENT_2D_COMPLETE_PROOF_VALIDATE",
            idempotency_key=f"increment-2d-service-validate-{uuid4().hex}",
        ),
        proof=authentication,
    )
    complete_system.complete.qualify_generation(
        CompleteGenerationQualificationRequest(
            generation_id=generation.generation_id,
            checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
            profile=CompleteProjectionProfile.FIXTURE_QUALIFICATION,
        ),
        proof=authentication,
    )
    current = _authenticated_current(
        complete_system,
        generation.generation_id,
        authentication,
    )
    promoted = complete_system.projections.promote_generation(
        ProjectionGenerationPromotionRequest(
            generation_id=generation.generation_id,
            expected_authority_version=current.authority_aggregate_version,
            checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
            validation_digest=validation.validation_digest,
            reason_code="INCREMENT_2D_COMPLETE_PROOF_PROMOTE",
            idempotency_key=f"increment-2d-service-promote-{uuid4().hex}",
        ),
        proof=authentication,
    )
    assert promoted.generation.state is ProjectionGenerationState.ACTIVE
    return Increment2PreparedAuthority(
        fixture_id=INTEGRATED_FIXTURE_V2_RETRIEVAL.fixture_id,
        generation_id=generation.generation_id,
        checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
        relation_key=INTEGRATED_FIXTURE_V2_DEVELOPMENT_CANDIDATE.relation_key,
    )


def _admit_actual_candidate(
    database: Path,
    object_root: Path,
    *,
    prefix: str,
):
    system = _open_candidate(database, object_root)
    try:
        retrieval = system.retrieval.find_related_event_candidates(
            retrieval_request(key=f"{prefix}-context-{uuid4().hex}"),
            proof=AuthenticationProof(method="STATIC_TOKEN", credential="token-1"),
        )
        assert retrieval.outcome is RetrievalOutcome.COMPLETE
        assert retrieval.context is not None
        context = retrieval.context
        request = candidate_request(
            context,
            key=f"{prefix}-candidate-{uuid4().hex}",
        )
        admitted = system.candidates.admit(
            request,
            proof=AuthenticationProof(method="STATIC_TOKEN", credential="token-1"),
        )
        return context, request, admitted
    finally:
        system.close()


def _replace_active_actual_generation(
    database: Path,
    object_root: Path,
    *,
    suffix: str,
):
    system = open_candidate_complete_system(
        database,
        object_root=object_root,
        adapter=_open_complete_neo4j_adapter(_service_config()),
    )
    try:
        active = system.projections.status(
            INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID,
            proof=proof(),
        )
        prior = _current_generation(system, active.generation_id)
        replacement = register_complete_generation(
            system,
            suffix=f"{suffix}-{uuid4().hex}",
            register_family=False,
        )
        rebuilt = _rebuild_generation(
            system,
            replacement,
            database,
            key=f"{suffix}-rebuild-{uuid4().hex}",
        )
        current = _current_generation(system, replacement.generation_id)
        validation = system.complete.validate_generation(
            CompleteGenerationValidationRequest(
                generation_id=replacement.generation_id,
                expected_authority_version=current.authority_aggregate_version,
                checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
                reason_code="INCREMENT_2D_ACTUAL_REPLACEMENT_VALIDATE",
                idempotency_key=f"{suffix}-validate-{uuid4().hex}",
            ),
            proof=proof(),
        )
        system.complete.qualify_generation(
            CompleteGenerationQualificationRequest(
                generation_id=replacement.generation_id,
                checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
                profile=CompleteProjectionProfile.FIXTURE_QUALIFICATION,
            ),
            proof=proof(),
        )
        validating = _current_generation(system, replacement.generation_id)
        prior = _current_generation(system, prior.generation_id)
        promoted = system.projections.promote_generation(
            ProjectionGenerationPromotionRequest(
                generation_id=replacement.generation_id,
                expected_authority_version=validating.authority_aggregate_version,
                checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
                validation_digest=validation.validation_digest,
                reason_code="INCREMENT_2D_ACTUAL_REPLACEMENT_PROMOTE",
                idempotency_key=f"{suffix}-promote-{uuid4().hex}",
                prior_generation_id=prior.generation_id,
                expected_prior_authority_version=prior.authority_aggregate_version,
            ),
            proof=proof(),
        )
        assert promoted.generation.state is ProjectionGenerationState.ACTIVE
        return replacement.generation_id
    finally:
        system.close()


def test_actual_service_complete_increment_2_proof_admits_replays_and_restarts(
    tmp_path: Path,
) -> None:
    (
        database,
        object_root,
        _seeded,
        _proposal,
        _decision,
        complete_system,
        generation,
    ) = _setup(tmp_path)
    complete_system.close()
    distractor_id = _retain_unadmitted_same_event_proposal(database)
    complete_system = open_candidate_complete_system(
        database,
        object_root=object_root,
        adapter=_open_complete_neo4j_adapter(_service_config()),
    )
    prepared: dict[str, Increment2PreparedAuthority] = {}

    def prepare(
        authentication: AuthenticationProof,
        _keys: Increment2ProofKeys,
    ) -> Increment2PreparedAuthority:
        if not isinstance(authentication, AuthenticationProof):
            raise TypeError("actual proof preparation authentication must be typed")
        current = prepared.get("authority")
        if current is not None:
            return current
        current = _activate_initial(
            complete_system,
            generation,
            database,
            authentication=authentication,
        )
        complete_system.close()
        prepared["authority"] = current
        return current

    controller = Increment2CompleteProofController(
        Increment2ProofEnvironment(
            prepare=prepare,
            open_candidate_authority=lambda: _open_candidate(
                database,
                object_root,
            ),
        )
    )
    keys = _keys("increment-2d-actual")

    try:
        result = controller.run(
            proof=AuthenticationProof(
                method="STATIC_TOKEN",
                credential="token-1",
            ),
            keys=keys,
        )
        assert result.candidate.outcome is CandidateAdmissionOutcome.ADMITTED
        assert result.retrieval_replay_confirmed is True
        assert result.candidate_replay_confirmed is True
        assert result.restart_confirmed is True
        assert _candidate_counts(database) == (1, 1, 1)

        replay = controller.run(
            proof=AuthenticationProof(
                method="STATIC_TOKEN",
                credential="token-1",
            ),
            keys=keys,
        )
        assert replay.context.context_digest == result.context.context_digest
        assert replay.candidate == result.candidate
        assert _candidate_counts(database) == (1, 1, 1)
        with sqlite3.connect(database) as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM relation_proposals "
                "WHERE proposal_id=? AND predicate='SAME_EVENT_AS'",
                (str(distractor_id),),
            ).fetchone()[0] == 1
            assert conn.execute(
                "SELECT COUNT(*) FROM relation_assertions WHERE proposal_id=?",
                (str(distractor_id),),
            ).fetchone()[0] == 0
        assert _projector_scalar(
            "MATCH ()-[relation:SAME_EVENT_AS "
            "{generation_id:$generation_id}]->() RETURN count(relation)",
            generation_id=str(generation.generation_id),
        ) == 0
    finally:
        if "authority" not in prepared:
            complete_system.close()
        _cleanup_generation(generation.generation_id)


def test_actual_service_replacement_generation_deduplicates_candidate_authority(
    tmp_path: Path,
) -> None:
    database, object_root, _seeded, _proposal, _decision, system, generation = _setup(
        tmp_path
    )
    replacement_id = None
    try:
        _activate_initial(
            system, generation, database, authentication=proof()
        )
    finally:
        system.close()
    try:
        _context, _request, admitted = _admit_actual_candidate(
            database,
            object_root,
            prefix="increment-2d-actual-replacement-initial",
        )
        replacement_id = _replace_active_actual_generation(
            database,
            object_root,
            suffix="increment-2d-actual-replacement",
        )
        recovered_context, _recovered_request, recovered = _admit_actual_candidate(
            database,
            object_root,
            prefix="increment-2d-actual-replacement-recovered",
        )
        assert recovered_context.projection.identity.generation_id == replacement_id
        assert recovered.outcome is CandidateAdmissionOutcome.DEDUPLICATED
        assert recovered.candidate_id == admitted.candidate_id
        assert recovered.candidate_version_id == admitted.candidate_version_id
        assert recovered.decision_id != admitted.decision_id
        assert _candidate_counts(database) == (1, 1, 2)
        reopened = _open_candidate(database, object_root)
        try:
            assert reopened.candidates.decision(
                admitted.decision_id,
                proof=AuthenticationProof(
                    method="STATIC_TOKEN",
                    credential="token-1",
                ),
            ) == admitted
        finally:
            reopened.close()
    finally:
        _cleanup_generation(generation.generation_id)
        if replacement_id is not None:
            _cleanup_generation(replacement_id)


def test_actual_service_relation_revocation_changes_later_context_without_rewrite(
    tmp_path: Path,
) -> None:
    database, object_root, _seeded, _proposal, _decision, system, generation = _setup(
        tmp_path
    )
    replacement_id = None
    try:
        _activate_initial(
            system, generation, database, authentication=proof()
        )
    finally:
        system.close()
    try:
        _context, original_request, admitted = _admit_actual_candidate(
            database,
            object_root,
            prefix="increment-2d-actual-relation-initial",
        )
        proposal_id, admission_decision_id = retained_relation_identities(database)
        relation_system = open_candidate_relation_system(database)
        try:
            proposal = relation_system.relations.proposal(proposal_id, proof=proof())
            revoked = relation_system.relations.decide(
                decision_request(
                    proposal,
                    action=RelationDecisionAction.REVOKE,
                    expected_version=1,
                    previous_decision_id=admission_decision_id,
                    key=f"increment-2d-actual-relation-revoke-{uuid4().hex}",
                ),
                proof=proof(),
            )
            assert revoked.current_state is RelationCurrentState.REVOKED
        finally:
            relation_system.close()

        stale = _open_candidate(database, object_root)
        try:
            assert stale.candidates.decision(
                admitted.decision_id,
                proof=AuthenticationProof(method="STATIC_TOKEN", credential="token-1"),
            ) == admitted
            with pytest.raises(RetrievalStateError):
                stale.candidates.admit(
                    original_request,
                    proof=AuthenticationProof(
                        method="STATIC_TOKEN",
                        credential="token-1",
                    ),
                )
        finally:
            stale.close()

        replacement_id = _replace_active_actual_generation(
            database,
            object_root,
            suffix="increment-2d-actual-after-relation-revocation",
        )
        current = _open_candidate(database, object_root)
        try:
            later = current.retrieval.find_related_event_candidates(
                retrieval_request(
                    key=f"increment-2d-actual-revoked-later-{uuid4().hex}"
                ),
                proof=AuthenticationProof(method="STATIC_TOKEN", credential="token-1"),
            )
            assert later.outcome is RetrievalOutcome.INCOMPLETE
            assert later.context is None
            assert current.candidates.decision(
                admitted.decision_id,
                proof=AuthenticationProof(method="STATIC_TOKEN", credential="token-1"),
            ) == admitted
            assert _candidate_counts(database) == (1, 1, 1)
        finally:
            current.close()
    finally:
        _cleanup_generation(generation.generation_id)
        if replacement_id is not None:
            _cleanup_generation(replacement_id)


def test_actual_service_governed_deletion_purges_derivative_and_never_requalifies(
    tmp_path: Path,
) -> None:
    database, object_root, _seeded, _proposal, _decision, system, generation = _setup(
        tmp_path
    )
    replacement_id = None
    try:
        _activate_initial(
            system, generation, database, authentication=proof()
        )
    finally:
        system.close()
    try:
        _context, original_request, admitted = _admit_actual_candidate(
            database,
            object_root,
            prefix="increment-2d-actual-tombstone-initial",
        )
        passage = INTEGRATED_FIXTURE_V2.passage_by_id["ifv2-prior-en"]
        admission_id = fixture_passage_admission_id(
            database,
            passage_id=passage.passage_id,
        )
        object_system = open_candidate_object_system(
            database,
            object_root=object_root,
        )
        try:
            object_system.objects.revoke(
                admission_id,
                reason_code="INCREMENT_2D_ACTUAL_PRIOR_PASSAGE_REVOKED",
                idempotency_key=f"increment-2d-actual-passage-revoke-{uuid4().hex}",
                proof=proof(),
            )
            deletion = object_system.objects.request_deletion(
                passage.blob_digest,
                reason_code="INCREMENT_2D_ACTUAL_PRIOR_PASSAGE_DELETE",
                idempotency_key=f"increment-2d-actual-passage-delete-{uuid4().hex}",
                proof=proof(),
            )
            object_system.objects.tombstone(
                deletion.deletion_id,
                reason_code="INCREMENT_2D_ACTUAL_PRIOR_PASSAGE_TOMBSTONE",
                idempotency_key=f"increment-2d-actual-passage-tombstone-{uuid4().hex}",
                proof=proof(),
            )
        finally:
            object_system.close()

        stale = _open_candidate(database, object_root)
        try:
            assert stale.candidates.decision(
                admitted.decision_id,
                proof=AuthenticationProof(method="STATIC_TOKEN", credential="token-1"),
            ) == admitted
            with pytest.raises((RetrievalStateError, AuthorityPersistenceError)):
                stale.candidates.admit(
                    original_request,
                    proof=AuthenticationProof(method="STATIC_TOKEN", credential="token-1"),
                )
        finally:
            stale.close()

        complete = open_candidate_complete_system(
            database,
            object_root=object_root,
            adapter=_open_complete_neo4j_adapter(_service_config()),
        )
        try:
            start = complete.projections.status(
                INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID,
                proof=proof(),
            ).contiguous_ledger_seq
            target = _latest_complete_source_ledger_seq(database)
            for ledger_seq in range(start + 1, target + 1):
                active = _current_generation(complete, generation.generation_id)
                complete.complete.deliver(
                    CompleteDeliveryRequest(
                        generation_id=generation.generation_id,
                        expected_authority_version=(
                            active.authority_aggregate_version
                        ),
                        ledger_seq=ledger_seq,
                        idempotency_key=(
                            f"increment-2d-actual-tombstone-deliver-{ledger_seq}"
                        ),
                    ),
                    proof=proof(),
                )
            assert _projector_scalar(
                "MATCH (document {generation_id:$generation_id, "
                "passage_id:$passage_id}) RETURN count(document)",
                generation_id=str(generation.generation_id),
                passage_id=passage.passage_id,
            ) == 0

            replacement = register_complete_generation(
                complete,
                suffix=f"increment-2d-actual-tombstone-{uuid4().hex}",
                register_family=False,
            )
            replacement_id = replacement.generation_id
            rebuilt = _rebuild_generation(
                complete,
                replacement,
                database,
                key=f"increment-2d-actual-tombstone-rebuild-{uuid4().hex}",
            )
            assert _projector_scalar(
                "MATCH (document {generation_id:$generation_id, "
                "passage_id:$passage_id}) RETURN count(document)",
                generation_id=str(replacement.generation_id),
                passage_id=passage.passage_id,
            ) == 0
            current = _current_generation(complete, replacement.generation_id)
            with pytest.raises(Neo4jIdentityConflict):
                complete.complete.validate_generation(
                    CompleteGenerationValidationRequest(
                        generation_id=replacement.generation_id,
                        expected_authority_version=current.authority_aggregate_version,
                        checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
                        reason_code="INCREMENT_2D_ACTUAL_TOMBSTONE_VALIDATE",
                        idempotency_key=(
                            f"increment-2d-actual-tombstone-validate-{uuid4().hex}"
                        ),
                    ),
                    proof=proof(),
                )
        finally:
            complete.close()
        assert _candidate_counts(database) == (1, 1, 1)
    finally:
        _cleanup_generation(generation.generation_id)
        if replacement_id is not None:
            _cleanup_generation(replacement_id)


@pytest.mark.parametrize("surface", ("fulltext", "relation", "vector"))
def test_actual_service_complete_proof_fails_closed_when_required_surface_is_lost(
    tmp_path: Path,
    surface: str,
) -> None:
    database, object_root, _seeded, _proposal, _decision, system, generation = _setup(
        tmp_path
    )
    try:
        prepared = _activate_initial(
            system, generation, database, authentication=proof()
        )
    finally:
        system.close()
    try:
        names = _names(generation.generation_id)
        if surface == "fulltext":
            _projector_write(f"DROP INDEX `{names.fulltext_index_name}`")
            expected = "NEO4J_RETRIEVAL_UNAVAILABLE"
        elif surface == "vector":
            _projector_write(f"DROP INDEX `{names.vector_index_name}`")
            expected = "NEO4J_RETRIEVAL_UNAVAILABLE"
        else:
            _projector_write(
                "MATCH ()-[relation:DEVELOPMENT_OF "
                "{generation_id:$generation_id}]->() DELETE relation",
                generation_id=str(generation.generation_id),
            )
            expected = "RETRIEVAL_CONTRACT_MISMATCH"

        controller = Increment2CompleteProofController(
            Increment2ProofEnvironment(
                prepare=lambda _proof, _keys: prepared,
                open_candidate_authority=lambda: _open_candidate(
                    database, object_root
                ),
            )
        )
        with pytest.raises(Increment2ProofStateError, match=expected):
            controller.run(
                proof=AuthenticationProof(
                    method="STATIC_TOKEN", credential="token-1"
                ),
                keys=_keys(f"increment-2d-actual-lost-{surface}"),
            )
        assert _candidate_counts(database) == (0, 0, 0)
    finally:
        _cleanup_generation(generation.generation_id)


def test_actual_service_required_gap_blocks_complete_candidate_proof(
    tmp_path: Path,
) -> None:
    database, object_root, _seeded, _proposal, _decision, system, generation = _setup(
        tmp_path
    )
    try:
        _activate_initial(
            system, generation, database, authentication=proof()
        )
    finally:
        system.close()
    try:
        _context, original_request, admitted = _admit_actual_candidate(
            database,
            object_root,
            prefix="increment-2d-actual-gap-initial",
        )
        block_active_candidate_generation(
            database,
            object_root=object_root,
            dead_letter=False,
        )
        blocked = _open_candidate(database, object_root)
        try:
            with pytest.raises(RetrievalStateError, match="required gap"):
                blocked.candidates.admit(
                    original_request,
                    proof=AuthenticationProof(method="STATIC_TOKEN", credential="token-1"),
                )
            retrieval = blocked.retrieval.find_related_event_candidates(
                retrieval_request(key=f"increment-2d-actual-gap-{uuid4().hex}"),
                proof=AuthenticationProof(method="STATIC_TOKEN", credential="token-1"),
            )
            assert retrieval.outcome is RetrievalOutcome.INCOMPLETE
            assert retrieval.context is None
            assert retrieval.failure is not None
            assert retrieval.failure.reason_code == "RETRIEVAL_GAP_BLOCKED"
            assert blocked.candidates.decision(
                admitted.decision_id,
                proof=AuthenticationProof(method="STATIC_TOKEN", credential="token-1"),
            ) == admitted
        finally:
            blocked.close()
    finally:
        _cleanup_generation(generation.generation_id)


def test_actual_service_dead_letter_blocks_complete_candidate_proof(
    tmp_path: Path,
) -> None:
    database, object_root, _seeded, _proposal, _decision, system, generation = _setup(
        tmp_path
    )
    try:
        _activate_initial(
            system, generation, database, authentication=proof()
        )
    finally:
        system.close()
    try:
        _context, original_request, admitted = _admit_actual_candidate(
            database,
            object_root,
            prefix="increment-2d-actual-dead-letter-initial",
        )
        block_active_candidate_generation(
            database,
            object_root=object_root,
            dead_letter=True,
        )
        blocked = _open_candidate(database, object_root)
        try:
            with pytest.raises(RetrievalStateError, match="dead letter"):
                blocked.candidates.admit(
                    original_request,
                    proof=AuthenticationProof(method="STATIC_TOKEN", credential="token-1"),
                )
            retrieval = blocked.retrieval.find_related_event_candidates(
                retrieval_request(
                    key=f"increment-2d-actual-dead-letter-{uuid4().hex}"
                ),
                proof=AuthenticationProof(method="STATIC_TOKEN", credential="token-1"),
            )
            assert retrieval.outcome is RetrievalOutcome.INCOMPLETE
            assert retrieval.context is None
            assert retrieval.failure is not None
            assert retrieval.failure.reason_code == "RETRIEVAL_DEAD_LETTER_BLOCKED"
            assert blocked.candidates.decision(
                admitted.decision_id,
                proof=AuthenticationProof(method="STATIC_TOKEN", credential="token-1"),
            ) == admitted
        finally:
            blocked.close()
    finally:
        _cleanup_generation(generation.generation_id)
