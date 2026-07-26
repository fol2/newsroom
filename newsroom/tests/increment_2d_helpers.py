from __future__ import annotations

from pathlib import Path
from typing import Callable

from newsroom.authority import (
    AggregateId,
    InlinePayload,
    ObjectAdmissionId,
    SemanticCommand,
    StaticAuthenticator,
    StaticAuthorizer,
    StaticPrincipal,
)
from newsroom.authority._complete_projection_system import (
    _open_complete_with_adapter,
)
from newsroom.authority._development_candidate_system import (
    _open_complete_fixture_candidate_with_adapter,
)
from newsroom.increment2 import DevelopmentCandidateAdmissionRequest
from newsroom.increment2.policy import (
    merge_development_candidate_authority_registries,
)
from newsroom.integrated import IntegratedTriageProposalId
from newsroom.projection import (
    CompleteProjectionProfile,
    INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID,
    ProjectionFamilyKind,
    ProjectionGenerationId,
    ProjectionGenerationPromotionRequest,
    ProjectionReadPolicy,
)
from newsroom.projection.neo4j import (
    CompleteDeliveryRequest,
    CompleteGenerationQualificationRequest,
    CompleteGenerationValidationRequest,
    CompleteRebuildRequest,
)
from newsroom.projection.policy import merge_projection_authority_registries
from newsroom.relations import (
    RelationAdmissionDecisionId,
    RelationProposalId,
)
from newsroom.relations.policy import merge_relation_authority_registries
from newsroom.retrieval import (
    FindRelatedEventCandidatesRequest,
    INTEGRATED_FIXTURE_V2_RETRIEVAL,
    RetrievalContextV2Id,
    RetrievalRequestId,
)

from .authority_a2b_helpers import _policy_registries, open_object_system
from .authority_event_helpers import payload_schemas
from .complete_projection_2b_helpers import (
    COMPLETE_NOW,
    MemoryCompleteNeo4jAdapter,
    complete_contract_registry,
    complete_scopes,
    proof,
    register_complete_generation,
)
from .projection_b1_helpers import event_read_policy, source_command_registry
from .relation_2a_helpers import (
    authenticator as relation_authenticator,
    authorizer as relation_authorizer,
    event_read_policy as relation_event_read_policy,
    relation_read_policy,
)
from newsroom.authority._relation_system import (
    open_governed_relation_authority_system,
)
from newsroom.authority.object_policy import merge_authority_registries
from .retrieval_2c_helpers import (
    MemoryHybridRetrievalAdapter,
    object_limits,
    seed_active_retrieval_authority,
)


def _current_generation(system, generation_id: ProjectionGenerationId):
    return next(
        item
        for item in system.projections.generations(
            INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID,
            proof=proof(),
        )
        if item.generation_id == generation_id
    )


def _latest_complete_source_ledger_seq(database: Path) -> int:
    import sqlite3

    with sqlite3.connect(database) as conn:
        return int(
            conn.execute(
                "SELECT COALESCE(MAX(ledger_seq),0) FROM ledger_events "
                "WHERE security_scope NOT IN "
                "('authority.projection','authority.candidate')"
            ).fetchone()[0]
        )


def _rebuild_generation(system, generation, database: Path, *, key: str):
    return system.complete.rebuild(
        CompleteRebuildRequest(
            generation_id=generation.generation_id,
            expected_authority_version=(
                generation.authority_aggregate_version
            ),
            through_ledger_seq=_latest_complete_source_ledger_seq(database),
            reason_code="INCREMENT_2D_COMPLETE_REBUILD",
            idempotency_key=key,
        ),
        proof=proof(),
    )


def scopes() -> frozenset[str]:
    return frozenset(
        {
            *complete_scopes(),
            "authority.retrieval.read",
            "authority.candidate.admit",
            "authority.candidate.read",
        }
    )


def candidate_registries():
    object_commands, object_schemas = merge_authority_registries(
        command_registry=source_command_registry(),
        payload_schemas=payload_schemas(),
    )
    relation_commands, relation_schemas = merge_relation_authority_registries(
        command_registry=object_commands,
        payload_schemas=object_schemas,
    )
    projection_commands, projection_schemas = (
        merge_projection_authority_registries(
            command_registry=relation_commands,
            payload_schemas=relation_schemas,
        )
    )
    return merge_development_candidate_authority_registries(
        command_registry=projection_commands,
        payload_schemas=projection_schemas,
    )


def candidate_complete_registries():
    """Add Candidate commands before the complete opener adds its layers."""

    return merge_development_candidate_authority_registries(
        command_registry=source_command_registry(),
        payload_schemas=payload_schemas(),
    )


def open_candidate_complete_system(
    database: Path,
    *,
    object_root: Path,
    adapter: object,
    clock: Callable = lambda: COMPLETE_NOW,
):
    commands, schemas = candidate_complete_registries()
    return _open_complete_with_adapter(
        path=database,
        object_root=object_root,
        object_limits=object_limits(),
        registry=commands,
        payload_schemas=schemas,
        contracts=complete_contract_registry(),
        authenticator=StaticAuthenticator(
            credentials={"token-1": StaticPrincipal("principal.alpha")},
            authority_domain="newsroom.authority",
        ),
        authorizer=StaticAuthorizer(
            policy_version="increment-2d-complete-authz-v1",
            grants_by_principal={"principal.alpha": scopes()},
        ),
        event_read_policy=event_read_policy(),
        projection_read_policy=ProjectionReadPolicy(
            policy_id="increment-2d-complete-reader-v1",
            purpose="complete.projection.authority",
            required_scope="authority.projection.read",
            allowed_principal_ids=frozenset({"principal.alpha"}),
            allowed_family_ids=frozenset(
                {INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID, "graph.structural"}
            ),
            allowed_family_kinds=frozenset({ProjectionFamilyKind.GRAPH}),
            max_results=2_000,
        ),
        adapter=adapter,
        clock=clock,
    )


def open_candidate_relation_system(database: Path):
    commands, schemas = candidate_registries()
    return open_governed_relation_authority_system(
        path=database,
        registry=commands,
        payload_schemas=schemas,
        authenticator=relation_authenticator(),
        authorizer=relation_authorizer(),
        event_read_policy=relation_event_read_policy(),
        relation_read_policy=relation_read_policy(),
        clock=lambda: COMPLETE_NOW,
    )


def open_candidate_object_system(database: Path, *, object_root: Path):
    commands, schemas = candidate_registries()
    return open_object_system(
        database,
        object_root=object_root,
        scopes=scopes(),
        command_registry=commands,
        payload_schema_registry=schemas,
        clock=lambda: COMPLETE_NOW,
    )


def retained_relation_identities(
    database: Path,
) -> tuple[RelationProposalId, RelationAdmissionDecisionId]:
    import sqlite3

    with sqlite3.connect(database) as conn:
        row = conn.execute(
            "SELECT proposal_id,decision_id FROM relation_decision_heads "
            "WHERE current_state='ADMITTED'"
        ).fetchone()
    if row is None:
        raise AssertionError("fixture relation is not admitted")
    return (
        RelationProposalId.parse(str(row[0])),
        RelationAdmissionDecisionId.parse(str(row[1])),
    )


def fixture_passage_admission_id(
    database: Path,
    *,
    passage_id: str,
) -> ObjectAdmissionId:
    import sqlite3

    with sqlite3.connect(database) as conn:
        row = conn.execute(
            "SELECT admission_id FROM integrated_fixture_v2_passage_objects "
            "WHERE passage_id=?",
            (passage_id,),
        ).fetchone()
    if row is None:
        raise AssertionError(f"fixture passage {passage_id!r} is not bound")
    return ObjectAdmissionId.parse(str(row[0]))


def replace_active_retrieval_generation(
    database: Path,
    *,
    object_root: Path,
    suffix: str,
) -> ProjectionGenerationId:
    """Rebuild and atomically promote one replacement fixture generation.

    The helper uses only the governed complete-projection facade.  The current
    ACTIVE generation is named explicitly as the prior generation so the
    replacement transition cannot silently create two ACTIVE generations.
    """

    system = open_candidate_complete_system(
        database,
        object_root=object_root,
        adapter=MemoryCompleteNeo4jAdapter(),
    )
    try:
        active = system.projections.status(
            INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID,
            proof=proof(),
        )
        prior = _current_generation(system, active.generation_id)
        replacement = register_complete_generation(
            system,
            suffix=suffix,
            register_family=False,
        )
        rebuilt = _rebuild_generation(
            system,
            replacement,
            database,
            key=f"increment-2d-{suffix}-rebuild",
        )
        current = _current_generation(system, replacement.generation_id)
        validation = system.complete.validate_generation(
            CompleteGenerationValidationRequest(
                generation_id=replacement.generation_id,
                expected_authority_version=current.authority_aggregate_version,
                checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
                reason_code="INCREMENT_2D_REPLACEMENT_VALIDATE",
                idempotency_key=f"increment-2d-{suffix}-validate",
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
                expected_authority_version=(
                    validating.authority_aggregate_version
                ),
                checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
                validation_digest=validation.validation_digest,
                reason_code="INCREMENT_2D_REPLACEMENT_PROMOTE",
                idempotency_key=f"increment-2d-{suffix}-promote",
                prior_generation_id=prior.generation_id,
                expected_prior_authority_version=(
                    prior.authority_aggregate_version
                ),
            ),
            proof=proof(),
        )
        return promoted.generation.generation_id
    finally:
        system.close()


def rebuild_replacement_generation(
    database: Path,
    *,
    object_root: Path,
    suffix: str,
) -> tuple[MemoryCompleteNeo4jAdapter, ProjectionGenerationId, int]:
    """Rebuild a replacement without qualifying or promoting it.

    Destructive lifecycle proof uses the returned batches to demonstrate that
    revoked or tombstoned content is removed. Qualification remains fail-closed
    because the original complete fixture contract is intentionally no longer
    satisfiable.
    """

    adapter = MemoryCompleteNeo4jAdapter()
    system = open_candidate_complete_system(
        database,
        object_root=object_root,
        adapter=adapter,
    )
    try:
        replacement = register_complete_generation(
            system,
            suffix=suffix,
            register_family=False,
        )
        rebuilt = _rebuild_generation(
            system,
            replacement,
            database,
            key=f"increment-2d-{suffix}-rebuild",
        )
        return (
            adapter,
            replacement.generation_id,
            rebuilt.checkpoint_ledger_seq,
        )
    finally:
        system.close()


def block_active_candidate_generation(
    database: Path,
    *,
    object_root: Path,
    dead_letter: bool,
) -> None:
    """Create a required gap or dead letter with the full Candidate registry."""

    system = open_candidate_complete_system(
        database,
        object_root=object_root,
        adapter=MemoryCompleteNeo4jAdapter(fail_writes=True),
    )
    try:
        status = system.projections.status(
            INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID,
            proof=proof(),
        )
        system.commands.execute(
            SemanticCommand(
                command_type="source.item.write",
                aggregate_id=AggregateId.new(),
                expected_aggregate_version=0,
                payload=InlinePayload(
                    {
                        "headline": "Increment 2D blocked source",
                        "count": 1,
                    }
                ),
                idempotency_key=(
                    "increment-2d-dead-letter-source"
                    if dead_letter
                    else "increment-2d-gap-source"
                ),
            ),
            proof=proof(),
        )
        target = system.events.after(0, limit=1_000, proof=proof())[-1]
        attempts = 3 if dead_letter else 1
        for attempt in range(1, attempts + 1):
            generation = _current_generation(system, status.generation_id)
            system.complete.deliver(
                CompleteDeliveryRequest(
                    generation_id=generation.generation_id,
                    expected_authority_version=(
                        generation.authority_aggregate_version
                    ),
                    ledger_seq=target.ledger_seq,
                    idempotency_key=(
                        f"increment-2d-blocked-delivery-{dead_letter}-{attempt}"
                    ),
                ),
                proof=proof(),
            )
    finally:
        system.close()


def open_candidate_test_system(
    database: Path,
    *,
    object_root: Path,
    adapter: object,
    granted_scopes: frozenset[str] | None = None,
    clock: Callable = lambda: COMPLETE_NOW,
):
    rights, hydration, admissions = _policy_registries()
    selected = scopes() if granted_scopes is None else granted_scopes
    return _open_complete_fixture_candidate_with_adapter(
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
            policy_version="increment-2d-candidate-authz-v1",
            grants_by_principal={"principal.alpha": selected},
        ),
        adapter=adapter,
        clock=clock,
    )


def retrieval_request(*, key: str) -> FindRelatedEventCandidatesRequest:
    fixture = INTEGRATED_FIXTURE_V2_RETRIEVAL
    return FindRelatedEventCandidatesRequest(
        request_id=RetrievalRequestId.new(),
        context_id=RetrievalContextV2Id.new(),
        fixture_id=fixture.fixture_id,
        query_revision_id=fixture.query_revision_id,
        query_hypothesis_version_id=fixture.query_hypothesis_version_id,
        query_valid_time=fixture.query_valid_time,
        idempotency_key=key,
    )


def candidate_request(context, *, key: str) -> DevelopmentCandidateAdmissionRequest:
    return DevelopmentCandidateAdmissionRequest(
        proposal_id=IntegratedTriageProposalId.new(),
        retrieval_context_id=context.context_id,
        expected_context_digest=context.context_digest,
        idempotency_key=key,
    )


__all__ = [
    "MemoryHybridRetrievalAdapter",
    "block_active_candidate_generation",
    "candidate_request",
    "candidate_complete_registries",
    "candidate_registries",
    "fixture_passage_admission_id",
    "open_candidate_complete_system",
    "open_candidate_object_system",
    "open_candidate_relation_system",
    "open_candidate_test_system",
    "proof",
    "rebuild_replacement_generation",
    "replace_active_retrieval_generation",
    "retained_relation_identities",
    "retrieval_request",
    "scopes",
    "seed_active_retrieval_authority",
]
