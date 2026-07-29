from __future__ import annotations

from pathlib import Path

import pytest

from newsroom.authority import TrustScope, UtcTimestamp
from newsroom.projection import (
    DISCOVERY_LINEAGE_FAMILY_ID,
    ProjectionNodeType,
    ProjectionRelationType,
    ProjectionFamilyRegistrationRequest,
    ProjectionGenerationCreateRequest,
    ProjectionGenerationId,
    ProjectionGenerationPromotionRequest,
    ProjectionGenerationState,
    ProjectionStateError,
)
from newsroom.projection.neo4j import (
    DiscoveryLineageProjectionFacade,
    DiscoveryLineageReadError,
    DiscoveryLineageReadRequest,
    DiscoveryLineageSubject,
    Neo4jIdentityConflict,
    Neo4jProjectorConfig,
    StructuralGenerationValidationRequest,
    StructuralRebuildRequest,
)
from newsroom.projection.neo4j._adapter import _open_neo4j_adapter

from .check_3c_authority_helpers import OCCURRENCE_ID
from .check_3c_helpers import (
    ATTEMPT_ID,
    DEFINITION_ID,
    ITEM_ID,
    OUTCOME_ID,
    REPRESENTATION_ID,
    REQUEST_ID,
    REVISION_ID,
    TRANSITION_ID,
    VERSION_ID,
)
from .discovery_3d_helpers import GATE_ID, LEAD_ID, SIGNAL_ID
from .discovery_projection_3e_helpers import (
    open_lineage_projection_service_system,
    proof,
)
from .test_discovery_projection_3e_authority import seed_complete_lineage



def _subjects() -> tuple[DiscoveryLineageSubject, ...]:
    return tuple(
        DiscoveryLineageSubject(identifier)
        for identifier in (
            DEFINITION_ID,
            VERSION_ID,
            ITEM_ID,
            REVISION_ID,
            REPRESENTATION_ID,
            OCCURRENCE_ID,
            REQUEST_ID,
            ATTEMPT_ID,
            OUTCOME_ID,
            TRANSITION_ID,
            SIGNAL_ID,
            GATE_ID,
            LEAD_ID,
        )
    )


def _read_request() -> DiscoveryLineageReadRequest:
    return DiscoveryLineageReadRequest(
        subjects=_subjects(),
        query_valid_time=UtcTimestamp.now(),
        limit=250,
    )


def _assert_complete_lineage(response) -> None:
    non_event_nodes = tuple(
        node
        for node in response.nodes
        if node.node_type is not ProjectionNodeType.LEDGER_EVENT
    )
    lineage_relations = tuple(
        relation
        for relation in response.relations
        if relation.relation_type
        is not ProjectionRelationType.PROJECTED_FROM_EVENT
    )
    assert len(non_event_nodes) == 13
    assert len(lineage_relations) == 16
    assert {node.node_type for node in non_event_nodes} == {
        subject.node_type for subject in _subjects()
    }
    assert all(node.identity_source == "GOVERNED_ID" for node in non_event_nodes)
    assert all(node.first_ledger_seq > 0 for node in response.nodes)
    assert all(
        node.first_source_event_digest.startswith("sha256:")
        and len(node.first_source_event_digest) == 71
        for node in response.nodes
    )
    known = {node.canonical_id for node in response.nodes}
    assert all(
        relation.source_canonical_id in known
        and relation.target_canonical_id in known
        and relation.trust_scope in {TrustScope.ADMITTED, TrustScope.OBSERVED}
        and relation.ledger_seq > 0
        and relation.source_event_digest.startswith("sha256:")
        and relation.payload_digest.startswith("sha256:")
        for relation in response.relations
    )
    assert response.metadata.open_gap_count == 0
    assert response.metadata.dead_letter_count == 0


def _register_and_create(system, *, suffix: str):
    system.projections.register_family(
        ProjectionFamilyRegistrationRequest(
            DISCOVERY_LINEAGE_FAMILY_ID,
            "3e-service-family-register",
        ),
        proof=proof(),
    )
    return system.projections.create_generation(
        ProjectionGenerationCreateRequest(
            ProjectionGenerationId.new(),
            DISCOVERY_LINEAGE_FAMILY_ID,
            "INCREMENT_3E_ACTUAL_SERVICE",
            f"3e-service-generation-{suffix}",
        ),
        proof=proof(),
    )


def _source_watermark(system) -> int:
    events = system.events.after(0, limit=1_000, proof=proof())
    source = tuple(
        event
        for event in events
        if not event.event_type.startswith("projection.")
    )
    assert source
    return source[-1].ledger_seq


def _generation(system, generation_id: ProjectionGenerationId):
    return next(
        item
        for item in system.projections.generations(
            DISCOVERY_LINEAGE_FAMILY_ID,
            proof=proof(),
        )
        if item.generation_id == generation_id
    )


def _rebuild_request(system, generation, *, key: str) -> StructuralRebuildRequest:
    current = _generation(system, generation.generation_id)
    return StructuralRebuildRequest(
        generation_id=generation.generation_id,
        expected_authority_version=current.authority_aggregate_version,
        through_ledger_seq=_source_watermark(system),
        reason_code="INCREMENT_3E_ACTUAL_SERVICE_REBUILD",
        idempotency_key=key,
    )


def _validate(system, generation_id: ProjectionGenerationId, checkpoint: int, *, key: str):
    current = _generation(system, generation_id)
    return system.structural.validate_generation(
        StructuralGenerationValidationRequest(
            generation_id=generation_id,
            expected_authority_version=current.authority_aggregate_version,
            checkpoint_ledger_seq=checkpoint,
            reason_code="INCREMENT_3E_ACTUAL_SERVICE_RECONCILE",
            idempotency_key=key,
        ),
        proof=proof(),
    )


def _promote(
    system,
    generation_id: ProjectionGenerationId,
    validation,
    *,
    key: str,
    prior_generation_id: ProjectionGenerationId | None = None,
):
    current = _generation(system, generation_id)
    prior = (
        None
        if prior_generation_id is None
        else _generation(system, prior_generation_id)
    )
    return system.projections.promote_generation(
        ProjectionGenerationPromotionRequest(
            generation_id=generation_id,
            expected_authority_version=current.authority_aggregate_version,
            checkpoint_ledger_seq=validation.checkpoint_ledger_seq,
            validation_digest=validation.validation_digest,
            reason_code="INCREMENT_3E_ACTUAL_SERVICE_PROMOTE",
            idempotency_key=key,
            prior_generation_id=prior_generation_id,
            expected_prior_authority_version=(
                None if prior is None else prior.authority_aggregate_version
            ),
        ),
        proof=proof(),
    )


def _cleanup(config: Neo4jProjectorConfig, *generation_ids: ProjectionGenerationId) -> None:
    adapter = _open_neo4j_adapter(config)
    try:
        adapter.verify_compatibility()
        for generation_id in generation_ids:
            adapter.cleanup_generation(str(generation_id))
    finally:
        adapter.close()


def run_actual_service_projects_complete_lineage_and_recovers_graph_loss(
    tmp_path: Path,
    config: Neo4jProjectorConfig,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seed_complete_lineage(database)
    generation_id: ProjectionGenerationId | None = None
    replacement_generation_id: ProjectionGenerationId | None = None
    rebuild_request: StructuralRebuildRequest | None = None

    system = open_lineage_projection_service_system(database, config)
    try:
        generation = _register_and_create(system, suffix="complete")
        generation_id = generation.generation_id
        rebuild_request = _rebuild_request(
            system,
            generation,
            key="3e-service-complete-rebuild",
        )
        rebuilt = system.structural.rebuild(rebuild_request, proof=proof())
        validation = _validate(
            system,
            generation_id,
            rebuilt.checkpoint_ledger_seq,
            key="3e-service-complete-validate",
        )
        promoted = _promote(
            system,
            generation_id,
            validation,
            key="3e-service-complete-promote",
        )
        assert promoted.generation.state is ProjectionGenerationState.ACTIVE

        facade = DiscoveryLineageProjectionFacade.from_system(system)
        initial = facade.read(_read_request(), proof=proof())
        assert {node.node_type for node in initial.nodes} >= {
            subject.node_type for subject in _subjects()
        }
        assert initial.relations
        _assert_complete_lineage(initial)
        before_replay = system.events.after(0, limit=1_000, proof=proof())

        # A promoted generation is immutable projection history. Exact rebuild
        # replay is allowed only while the target remains BUILDING; graph loss
        # after activation must be repaired through a replacement generation.
        with pytest.raises(
            ProjectionStateError,
            match="only a building generation can be destructively rebuilt",
        ):
            system.structural.rebuild(rebuild_request, proof=proof())
        assert system.events.after(0, limit=1_000, proof=proof()) == before_replay
        assert facade.read(_read_request(), proof=proof()) == initial
    finally:
        system.close()

    assert generation_id is not None
    assert rebuild_request is not None
    try:
        _cleanup(config, generation_id)
        restarted = open_lineage_projection_service_system(database, config)
        try:
            facade = DiscoveryLineageProjectionFacade.from_system(restarted)
            with pytest.raises(Neo4jIdentityConflict, match="differs"):
                facade.read(_read_request(), proof=proof())

            replacement = _register_and_create(
                restarted,
                suffix="graph-loss-replacement",
            )
            replacement_generation_id = replacement.generation_id
            replacement_rebuild = restarted.structural.rebuild(
                _rebuild_request(
                    restarted,
                    replacement,
                    key="3e-service-graph-loss-replacement-rebuild",
                ),
                proof=proof(),
            )
            replacement_validation = _validate(
                restarted,
                replacement.generation_id,
                replacement_rebuild.checkpoint_ledger_seq,
                key="3e-service-graph-loss-replacement-validate",
            )
            promotion = _promote(
                restarted,
                replacement.generation_id,
                replacement_validation,
                key="3e-service-graph-loss-replacement-promote",
                prior_generation_id=generation_id,
            )
            assert promotion.generation.state is ProjectionGenerationState.ACTIVE
            assert promotion.prior_generation is not None
            assert (
                promotion.prior_generation.state
                is ProjectionGenerationState.RETIRED
            )
            restored = facade.read(_read_request(), proof=proof())
            assert restored.metadata.generation_id == replacement.generation_id
            assert restored.nodes
            assert restored.relations
            _assert_complete_lineage(restored)
        finally:
            restarted.close()
    finally:
        cleanup_ids = tuple(
            item
            for item in (generation_id, replacement_generation_id)
            if item is not None
        )
        _cleanup(config, *cleanup_ids)


def run_actual_service_replacement_generation_becomes_only_active_lineage(
    tmp_path: Path,
    config: Neo4jProjectorConfig,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seed_complete_lineage(database)
    generations: list[ProjectionGenerationId] = []
    system = open_lineage_projection_service_system(database, config)
    try:
        first = _register_and_create(system, suffix="first")
        generations.append(first.generation_id)
        first_rebuild = system.structural.rebuild(
            _rebuild_request(system, first, key="3e-service-first-rebuild"),
            proof=proof(),
        )
        first_validation = _validate(
            system,
            first.generation_id,
            first_rebuild.checkpoint_ledger_seq,
            key="3e-service-first-validate",
        )
        _promote(
            system,
            first.generation_id,
            first_validation,
            key="3e-service-first-promote",
        )

        replacement = system.projections.create_generation(
            ProjectionGenerationCreateRequest(
                ProjectionGenerationId.new(),
                DISCOVERY_LINEAGE_FAMILY_ID,
                "INCREMENT_3E_ACTUAL_SERVICE_REPLACEMENT",
                "3e-service-generation-replacement",
            ),
            proof=proof(),
        )
        generations.append(replacement.generation_id)
        replacement_rebuild = system.structural.rebuild(
            _rebuild_request(
                system,
                replacement,
                key="3e-service-replacement-rebuild",
            ),
            proof=proof(),
        )
        replacement_validation = _validate(
            system,
            replacement.generation_id,
            replacement_rebuild.checkpoint_ledger_seq,
            key="3e-service-replacement-validate",
        )
        promotion = _promote(
            system,
            replacement.generation_id,
            replacement_validation,
            key="3e-service-replacement-promote",
            prior_generation_id=first.generation_id,
        )
        assert promotion.generation.state is ProjectionGenerationState.ACTIVE
        assert promotion.prior_generation is not None
        assert promotion.prior_generation.state is ProjectionGenerationState.RETIRED

        response = DiscoveryLineageProjectionFacade.from_system(system).read(
            _read_request(),
            proof=proof(),
        )
        assert response.metadata.generation_id == replacement.generation_id
        _assert_complete_lineage(response)
    finally:
        system.close()
        if generations:
            _cleanup(config, *generations)
