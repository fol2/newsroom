from __future__ import annotations

from pathlib import Path

import pytest

from newsroom.projection import (
    ProjectionDeliveryOutcome,
    ProjectionDeliveryRequest,
    ProjectionGapId,
    ProjectionGapResolutionRequest,
    ProjectionGenerationId,
    ProjectionGenerationPromotionRequest,
    ProjectionGenerationState,
    ProjectionGenerationTransitionRequest,
    ProjectionGenerationValidationRequest,
)

from .extraction_4a_helpers import extraction_proof
from .increment4e_helpers import (
    INCREMENT4_PROJECTION_SCOPES,
    admitted_increment4_fixture,
    open_increment4_neo4j_system,
)
from .projection_b2_helpers import MemoryNeo4jAdapter
from .test_increment4e_neo4j_controller import GENERATION_1, _request


MISSING_GENERATION = ProjectionGenerationId.parse(
    "00000000-0000-4000-8000-000000005098"
)
GAP_ID = ProjectionGapId.parse(
    "00000000-0000-4000-8000-000000005099"
)


def _mutation_operations(system, generation_id, built):
    version = built.generation.authority_aggregate_version
    return (
        (
            "transition",
            lambda: system.projections.transition_generation(
                ProjectionGenerationTransitionRequest(
                    generation_id=generation_id,
                    expected_authority_version=version,
                    target_state=ProjectionGenerationState.FAILED,
                    reason_code="DENIED_TRANSITION",
                    idempotency_key=f"denied-transition-{generation_id}",
                ),
                proof=extraction_proof(),
            ),
        ),
        (
            "delivery",
            lambda: system.projections.record_delivery(
                ProjectionDeliveryRequest(
                    generation_id=generation_id,
                    expected_authority_version=version,
                    ledger_seq=1,
                    outcome=ProjectionDeliveryOutcome.IGNORED_OPTIONAL,
                    idempotency_key=f"denied-delivery-{generation_id}",
                ),
                proof=extraction_proof(),
            ),
        ),
        (
            "gap",
            lambda: system.projections.resolve_gap(
                ProjectionGapResolutionRequest(
                    generation_id=generation_id,
                    expected_authority_version=version,
                    gap_id=GAP_ID,
                    reason_code="DENIED_GAP",
                    idempotency_key=f"denied-gap-{generation_id}",
                ),
                proof=extraction_proof(),
            ),
        ),
        (
            "promotion",
            lambda: system.projections.promote_generation(
                ProjectionGenerationPromotionRequest(
                    generation_id=generation_id,
                    expected_authority_version=version,
                    checkpoint_ledger_seq=built.checkpoint_ledger_seq,
                    validation_digest=built.validation.validation_digest,
                    reason_code="DENIED_PROMOTION",
                    idempotency_key=f"denied-promotion-{generation_id}",
                ),
                proof=extraction_proof(),
            ),
        ),
        (
            "validation",
            lambda: system.projections.validate_generation(
                ProjectionGenerationValidationRequest(
                    generation_id=generation_id,
                    expected_authority_version=version,
                    checkpoint_ledger_seq=built.checkpoint_ledger_seq,
                    service_compatibility_digest=(
                        built.validation.service_compatibility_digest
                    ),
                    projection_state_digest=(
                        built.validation.projection_state_digest
                    ),
                    reason_code="DENIED_VALIDATION",
                    idempotency_key=f"denied-validation-{generation_id}",
                ),
                proof=extraction_proof(),
            ),
        ),
    )


def test_generic_mutation_authorization_precedes_generation_lookup(
    tmp_path: Path,
) -> None:
    state, snapshot = admitted_increment4_fixture(tmp_path)
    with open_increment4_neo4j_system(
        state,
        MemoryNeo4jAdapter(),
    ) as system:
        built = system.increment4.build_and_promote(
            _request(
                GENERATION_1,
                snapshot,
                key="increment4-mutation-oracle-base-v1",
            ),
            proof=extraction_proof(),
        )

    restricted_scopes = INCREMENT4_PROJECTION_SCOPES - {
        "authority.projection.manage",
        "authority.projection.write",
    }
    adapter = MemoryNeo4jAdapter()
    with open_increment4_neo4j_system(
        state,
        adapter,
        scopes=restricted_scopes,
    ) as system:
        messages: dict[str, list[str]] = {}
        for generation_id in (GENERATION_1, MISSING_GENERATION):
            for operation_name, operation in _mutation_operations(
                system,
                generation_id,
                built,
            ):
                with pytest.raises(PermissionError) as error:
                    operation()
                messages.setdefault(operation_name, []).append(str(error.value))

    assert all(len(values) == 2 for values in messages.values())
    assert all(values[0] == values[1] for values in messages.values())
    assert adapter.apply_count == 0
    assert adapter.cleanup_count == 0
    assert adapter.reconcile_count == 0
