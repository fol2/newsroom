from __future__ import annotations

from pathlib import Path

import pytest

from newsroom.authority import AuthorizationDenied
from newsroom.projection import (
    ProjectionFamilyRegistrationRequest,
    ProjectionGenerationCreateRequest,
    ProjectionGenerationId,
    ProjectionGenerationPromotionRequest,
    ProjectionGenerationState,
    ProjectionStateError,
)
from newsroom.projection.neo4j import (
    Neo4jIdentityConflict,
    StructuralActiveReadRequest,
    StructuralDeliveryRequest,
    StructuralGenerationValidationRequest,
    StructuralRebuildRequest,
)

from .authority_helpers import FIXED_NOW
from .projection_b1_helpers import FAMILY_ID
from .projection_b2_helpers import (
    MemoryNeo4jAdapter,
    open_b2_system,
    proof,
    source_command,
)


def _generation(system, generation_id):
    return next(
        item
        for item in system.projections.generations(FAMILY_ID, proof=proof())
        if item.generation_id == generation_id
    )


def _register(system) -> None:
    system.projections.register_family(
        ProjectionFamilyRegistrationRequest(
            FAMILY_ID,
            "b3-active-serving-family",
        ),
        proof=proof(),
    )


def _create(system, *, suffix: str):
    return system.projections.create_generation(
        ProjectionGenerationCreateRequest(
            ProjectionGenerationId.new(),
            FAMILY_ID,
            "B3_ACTIVE_SERVING",
            f"b3-active-serving-generation-{suffix}",
        ),
        proof=proof(),
    )


def _rebuild(system, generation, *, key: str):
    current = _generation(system, generation.generation_id)
    through = system.events.after(0, limit=1000, proof=proof())[-1].ledger_seq
    return system.structural.rebuild(
        StructuralRebuildRequest(
            generation_id=current.generation_id,
            expected_authority_version=current.authority_aggregate_version,
            through_ledger_seq=through,
            reason_code="B3_ACTIVE_SERVING_REBUILD",
            idempotency_key=key,
        ),
        proof=proof(),
    )


def _validate(system, generation_id, checkpoint: int, *, key: str):
    current = _generation(system, generation_id)
    return system.structural.validate_generation(
        StructuralGenerationValidationRequest(
            generation_id=generation_id,
            expected_authority_version=current.authority_aggregate_version,
            checkpoint_ledger_seq=checkpoint,
            reason_code="B3_ACTIVE_SERVING_VALIDATE",
            idempotency_key=key,
        ),
        proof=proof(),
    )


def _promote(system, generation_id, validation, *, key: str):
    current = _generation(system, generation_id)
    return system.projections.promote_generation(
        ProjectionGenerationPromotionRequest(
            generation_id=generation_id,
            expected_authority_version=current.authority_aggregate_version,
            checkpoint_ledger_seq=validation.checkpoint_ledger_seq,
            validation_digest=validation.validation_digest,
            reason_code="B3_ACTIVE_SERVING_PROMOTE",
            idempotency_key=key,
        ),
        proof=proof(),
    )


def _canonical_ids(adapter: MemoryNeo4jAdapter, generation_id) -> tuple[str, ...]:
    batches = [
        batch
        for (stored_generation, _), batch in sorted(adapter.deliveries.items())
        if stored_generation == str(generation_id)
    ]
    assert batches
    return tuple(sorted({node.canonical_id for batch in batches for node in batch.nodes}))


def _active_request(canonical_ids: tuple[str, ...]) -> StructuralActiveReadRequest:
    return StructuralActiveReadRequest(
        family_id=FAMILY_ID,
        canonical_ids=canonical_ids,
        query_valid_time=FIXED_NOW,
        limit=100,
    )


def test_active_read_fails_closed_until_authority_promotion(tmp_path: Path) -> None:
    adapter = MemoryNeo4jAdapter()
    system = open_b2_system(tmp_path / "authority.sqlite3", adapter)
    try:
        _register(system)
        system.commands.execute(
            source_command(key="b3-active-serving-source"),
            proof=proof(),
        )
        generation = _create(system, suffix="first")
        rebuilt = _rebuild(
            system,
            generation,
            key="b3-active-serving-rebuild-first",
        )
        canonical_ids = _canonical_ids(adapter, generation.generation_id)

        with pytest.raises(
            ProjectionStateError,
            match="no authority-selected active generation",
        ):
            system.structural.read_active(
                _active_request(canonical_ids),
                proof=proof(),
            )

        validation = _validate(
            system,
            generation.generation_id,
            rebuilt.checkpoint_ledger_seq,
            key="b3-active-serving-validate-first",
        )
        promoted = _promote(
            system,
            generation.generation_id,
            validation,
            key="b3-active-serving-promote-first",
        )
        assert promoted.generation.state is ProjectionGenerationState.ACTIVE

        response = system.structural.read_active(
            _active_request(canonical_ids),
            proof=proof(),
        )
        assert response.metadata.generation_id == generation.generation_id
        assert response.metadata.generation_state is ProjectionGenerationState.ACTIVE
        assert response.nodes
        assert response.relations
    finally:
        system.close()


def test_promotion_reconciles_current_graph_and_exact_replay(
    tmp_path: Path,
) -> None:
    adapter = MemoryNeo4jAdapter()
    system = open_b2_system(tmp_path / "authority.sqlite3", adapter)
    try:
        _register(system)
        system.commands.execute(
            source_command(key="b3-promotion-reconcile-source"),
            proof=proof(),
        )
        generation = _create(system, suffix="promotion-reconcile")
        rebuilt = _rebuild(
            system,
            generation,
            key="b3-promotion-reconcile-rebuild",
        )
        validation = _validate(
            system,
            generation.generation_id,
            rebuilt.checkpoint_ledger_seq,
            key="b3-promotion-reconcile-validate",
        )
        validating = _generation(system, generation.generation_id)
        request = ProjectionGenerationPromotionRequest(
            generation_id=generation.generation_id,
            expected_authority_version=(
                validating.authority_aggregate_version
            ),
            checkpoint_ledger_seq=validation.checkpoint_ledger_seq,
            validation_digest=validation.validation_digest,
            reason_code="B3_PROMOTION_RECONCILE",
            idempotency_key="b3-promotion-reconcile-promote",
        )

        adapter.reconciliation_mismatch = True
        with pytest.raises(Neo4jIdentityConflict, match="differs"):
            system.projections.promote_generation(request, proof=proof())
        assert (
            _generation(system, generation.generation_id).state
            is ProjectionGenerationState.VALIDATING
        )

        adapter.reconciliation_mismatch = False
        promoted = system.projections.promote_generation(
            request,
            proof=proof(),
        )
        assert promoted.generation.state is ProjectionGenerationState.ACTIVE
        retained_events = system.events.after(0, limit=1000, proof=proof())

        adapter.reconciliation_mismatch = True
        with pytest.raises(Neo4jIdentityConflict, match="differs"):
            system.projections.promote_generation(request, proof=proof())
        assert system.events.after(
            0,
            limit=1000,
            proof=proof(),
        ) == retained_events
        assert (
            _generation(system, generation.generation_id).state
            is ProjectionGenerationState.ACTIVE
        )
    finally:
        system.close()


def test_active_generation_revalidates_after_incremental_delivery_and_restart(
    tmp_path: Path,
) -> None:
    authority_path = tmp_path / "authority.sqlite3"
    adapter = MemoryNeo4jAdapter()
    system = open_b2_system(authority_path, adapter)
    try:
        _register(system)
        system.commands.execute(
            source_command(key="b3-active-revalidation-initial-source"),
            proof=proof(),
        )
        generation = _create(system, suffix="active-revalidation")
        rebuilt = _rebuild(
            system,
            generation,
            key="b3-active-revalidation-rebuild",
        )
        initial_validation = _validate(
            system,
            generation.generation_id,
            rebuilt.checkpoint_ledger_seq,
            key="b3-active-revalidation-initial-validate",
        )
        validating = _generation(system, generation.generation_id)
        promotion_request = ProjectionGenerationPromotionRequest(
            generation_id=generation.generation_id,
            expected_authority_version=(
                validating.authority_aggregate_version
            ),
            checkpoint_ledger_seq=initial_validation.checkpoint_ledger_seq,
            validation_digest=initial_validation.validation_digest,
            reason_code="B3_ACTIVE_REVALIDATION_PROMOTE",
            idempotency_key="b3-active-revalidation-promote",
        )
        promotion = system.projections.promote_generation(
            promotion_request,
            proof=proof(),
        )
        assert promotion.generation.state is ProjectionGenerationState.ACTIVE

        command = system.commands.execute(
            source_command(key="b3-active-revalidation-incremental-source"),
            proof=proof(),
        )
        source = next(
            event
            for event in system.events.after(0, limit=1000, proof=proof())
            if event.command_id == str(command.command_id)
        )
        current = _generation(system, generation.generation_id)
        system.structural.deliver(
            StructuralDeliveryRequest(
                generation_id=generation.generation_id,
                expected_authority_version=(
                    current.authority_aggregate_version
                ),
                ledger_seq=source.ledger_seq,
                idempotency_key="b3-active-revalidation-delivery",
            ),
            proof=proof(),
        )
        status = system.projections.status(FAMILY_ID, proof=proof())
        assert status.generation_state is ProjectionGenerationState.ACTIVE
        assert status.contiguous_ledger_seq > (
            initial_validation.checkpoint_ledger_seq
        )
        assert system.projections.validation(
            generation.generation_id,
            proof=proof(),
        ) == initial_validation

        with pytest.raises(
            ProjectionStateError,
            match="current authority checkpoint",
        ):
            system.projections.promote_generation(
                promotion_request,
                proof=proof(),
            )

        refreshed = _validate(
            system,
            generation.generation_id,
            status.contiguous_ledger_seq,
            key="b3-active-revalidation-refresh",
        )
        refreshed_generation = _generation(
            system,
            generation.generation_id,
        )
        assert refreshed.validation_version == (
            initial_validation.validation_version + 1
        )
        assert refreshed_generation.state is ProjectionGenerationState.ACTIVE
        assert refreshed_generation.validated_through_ledger_seq == (
            status.contiguous_ledger_seq
        )
        assert system.projections.validation(
            generation.generation_id,
            proof=proof(),
        ) == refreshed

        before_replay = system.events.after(0, limit=1000, proof=proof())
        replay = system.projections.promote_generation(
            promotion_request,
            proof=proof(),
        )
        assert replay == promotion
        assert system.events.after(
            0,
            limit=1000,
            proof=proof(),
        ) == before_replay
        canonical_ids = _canonical_ids(adapter, generation.generation_id)
        response = system.structural.read_active(
            _active_request(canonical_ids),
            proof=proof(),
        )
        assert response.metadata.generation_id == generation.generation_id
        assert response.metadata.contiguous_ledger_seq == (
            status.contiguous_ledger_seq
        )
    finally:
        system.close()

    restarted = open_b2_system(authority_path, adapter)
    try:
        assert _generation(
            restarted,
            generation.generation_id,
        ).state is ProjectionGenerationState.ACTIVE
        assert restarted.projections.validation(
            generation.generation_id,
            proof=proof(),
        ) == refreshed
        assert restarted.projections.promotions(
            FAMILY_ID,
            proof=proof(),
        ) == (promotion,)
    finally:
        restarted.close()


def test_newer_building_generation_cannot_replace_active_serving_target(
    tmp_path: Path,
) -> None:
    adapter = MemoryNeo4jAdapter()
    system = open_b2_system(tmp_path / "authority.sqlite3", adapter)
    try:
        _register(system)
        system.commands.execute(
            source_command(key="b3-active-serving-stable-source"),
            proof=proof(),
        )
        active = _create(system, suffix="active")
        rebuilt = _rebuild(
            system,
            active,
            key="b3-active-serving-rebuild-active",
        )
        validation = _validate(
            system,
            active.generation_id,
            rebuilt.checkpoint_ledger_seq,
            key="b3-active-serving-validate-active",
        )
        _promote(
            system,
            active.generation_id,
            validation,
            key="b3-active-serving-promote-active",
        )
        canonical_ids = _canonical_ids(adapter, active.generation_id)

        newer = _create(system, suffix="newer-building")
        assert _generation(system, newer.generation_id).state is ProjectionGenerationState.BUILDING

        response = system.structural.read_active(
            _active_request(canonical_ids),
            proof=proof(),
        )
        assert response.metadata.generation_id == active.generation_id
        assert response.metadata.generation_state is ProjectionGenerationState.ACTIVE
        assert response.nodes
        assert response.relations
    finally:
        system.close()



def test_active_read_authorizes_before_resolving_serving_state(
    tmp_path: Path,
) -> None:
    adapter = MemoryNeo4jAdapter()
    system = open_b2_system(
        tmp_path / "authority.sqlite3",
        adapter,
        scopes=frozenset({"authority.projection.manage"}),
    )
    try:
        _register(system)
        with pytest.raises(AuthorizationDenied):
            system.structural.read_active(
                _active_request(("npid:v1:source-item:unavailable",)),
                proof=proof(),
            )
    finally:
        system.close()

def test_active_read_request_is_bounded_and_typed() -> None:
    with pytest.raises(Exception):
        StructuralActiveReadRequest(
            family_id=FAMILY_ID,
            canonical_ids=(),
            query_valid_time=FIXED_NOW,
        )
    with pytest.raises(Exception):
        StructuralActiveReadRequest(
            family_id=FAMILY_ID,
            canonical_ids=("npid:v1:source-item:duplicate",) * 2,
            query_valid_time=FIXED_NOW,
        )
