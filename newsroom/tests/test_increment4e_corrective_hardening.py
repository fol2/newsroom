from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3

import pytest

import newsroom.authority._increment4_neo4j_boundary as increment4_boundary_module
from newsroom.authority import digest_canonical
from newsroom.entities.types import EntityKind
from newsroom.projection import (
    ProjectionDeliveryOutcome,
    ProjectionDeliveryRequest,
    ProjectionFamilyRegistrationRequest,
    ProjectionGapId,
    ProjectionGapResolutionRequest,
    ProjectionGenerationCreateRequest,
    ProjectionGenerationPromotionRequest,
    ProjectionGenerationState,
    ProjectionGenerationTransitionRequest,
    ProjectionGenerationValidationRequest,
    ProjectionStateError,
)
from newsroom.projection.neo4j import Neo4jWriteError

from .extraction_4a_helpers import extraction_proof
from .increment4e_helpers import (
    admitted_increment4_fixture,
    open_increment4_neo4j_system,
)
from .projection_b2_helpers import MemoryNeo4jAdapter
from .test_increment4e_neo4j_controller import GENERATION_1, GENERATION_2, _request


_FAMILY_ID = "graph.increment4.admitted"


def _fabricated_snapshot(snapshot, kind: str):
    if kind == "entity-version":
        state = snapshot.entities[0]
        fabricated_kind = next(
            item for item in EntityKind if item is not state.version.entity_kind
        )
        fabricated_state = replace(
            state,
            version=replace(state.version, entity_kind=fabricated_kind),
        )
        return replace(
            snapshot,
            entities=(fabricated_state, *snapshot.entities[1:]),
        )
    if kind == "alias":
        state = snapshot.entities[0]
        alias = state.aliases[0]
        fabricated_alias = replace(
            alias,
            uncertainty_codes=tuple(
                sorted(set((*alias.uncertainty_codes, "FABRICATED_ALIAS")))
            ),
        )
        fabricated_state = replace(
            state,
            aliases=(fabricated_alias, *state.aliases[1:]),
        )
        return replace(
            snapshot,
            entities=(fabricated_state, *snapshot.entities[1:]),
        )
    if kind == "assertion":
        relation = snapshot.relations[0]
        assertion = relation.current.assertion
        fabricated_assertion = replace(
            assertion,
            statement=assertion.statement + " fabricated",
            canonical_digest=digest_canonical(
                {
                    "fabricated_assertion": str(assertion.assertion_id),
                }
            ),
        )
        fabricated_relation = replace(
            relation,
            current=replace(relation.current, assertion=fabricated_assertion),
            projection_event=replace(
                relation.projection_event,
                assertion=fabricated_assertion,
            ),
        )
        return replace(snapshot, relations=(fabricated_relation,))
    raise AssertionError(kind)


@pytest.mark.parametrize("fabricated_kind", ("entity-version", "alias", "assertion"))
def test_increment4_rejects_fabricated_semantics_before_any_graph_or_generation_effect(
    tmp_path: Path,
    fabricated_kind: str,
) -> None:
    state, snapshot = admitted_increment4_fixture(tmp_path)
    adapter = MemoryNeo4jAdapter()
    fabricated = _fabricated_snapshot(snapshot, fabricated_kind)

    with open_increment4_neo4j_system(state, adapter) as system:
        with pytest.raises(
            ProjectionStateError,
            match="differs from exact retained admitted authority",
        ):
            system.increment4.build_and_promote(
                _request(
                    GENERATION_1,
                    fabricated,
                    key=f"increment4-fabricated-{fabricated_kind}-v1",
                ),
                proof=extraction_proof(),
            )

    assert adapter.apply_count == 0
    assert adapter.cleanup_count == 0
    with sqlite3.connect(state.entity.extraction.database) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM projection_generations"
        ).fetchone()[0] == 0


def test_increment4_mapper_receives_fresh_authority_owned_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, snapshot = admitted_increment4_fixture(tmp_path)
    adapter = MemoryNeo4jAdapter()
    captured = []
    build = increment4_boundary_module.build_increment4_admitted_batches

    def capture(authoritative_snapshot, **kwargs):
        captured.append(authoritative_snapshot)
        return build(authoritative_snapshot, **kwargs)

    monkeypatch.setattr(
        increment4_boundary_module,
        "build_increment4_admitted_batches",
        capture,
    )
    with open_increment4_neo4j_system(state, adapter) as system:
        system.increment4.build_and_promote(
            _request(GENERATION_1, snapshot, key="increment4-authority-owned-v1"),
            proof=extraction_proof(),
        )

    assert captured == [snapshot]
    assert captured[0] is not snapshot


def test_increment4_failed_replacement_keeps_prior_active_and_serving(
    tmp_path: Path,
) -> None:
    state, snapshot = admitted_increment4_fixture(tmp_path)
    adapter = MemoryNeo4jAdapter()

    with open_increment4_neo4j_system(state, adapter) as system:
        first = system.increment4.build_and_promote(
            _request(GENERATION_1, snapshot, key="increment4-stable-prior-v1"),
            proof=extraction_proof(),
        )
        prior_batches = {
            key: value
            for key, value in adapter.deliveries.items()
            if key[0] == str(GENERATION_1)
        }
        adapter.fail_writes = True
        with pytest.raises(Neo4jWriteError):
            system.increment4.build_and_promote(
                _request(
                    GENERATION_2,
                    snapshot,
                    key="increment4-failed-replacement-v1",
                ),
                proof=extraction_proof(),
            )
        first_status = system.increment4.generation_status(
            GENERATION_1, proof=extraction_proof()
        )
        second_status = system.increment4.generation_status(
            GENERATION_2, proof=extraction_proof()
        )

    assert first.generation.state is ProjectionGenerationState.ACTIVE
    assert first_status.generation.state is ProjectionGenerationState.ACTIVE
    assert second_status.generation.state is ProjectionGenerationState.BUILDING
    assert {
        key: value
        for key, value in adapter.deliveries.items()
        if key[0] == str(GENERATION_1)
    } == prior_batches


class _FailRetiredCleanupOnceAdapter(MemoryNeo4jAdapter):
    def __post_init__(self) -> None:
        super().__post_init__()
        self.fail_cleanup_generation: str | None = None
        self.failed_cleanup = False

    def cleanup_generation(self, generation_id: str) -> int:
        if (
            generation_id == self.fail_cleanup_generation
            and not self.failed_cleanup
        ):
            self.cleanup_count += 1
            self.failed_cleanup = True
            raise Neo4jWriteError("fixed retired-generation cleanup failure")
        return super().cleanup_generation(generation_id)


def test_increment4_active_retry_completes_failed_retired_predecessor_purge(
    tmp_path: Path,
) -> None:
    state, snapshot = admitted_increment4_fixture(tmp_path)
    adapter = _FailRetiredCleanupOnceAdapter()
    replacement_request = _request(
        GENERATION_2,
        snapshot,
        key="increment4-retry-retired-cleanup-v1",
    )

    with open_increment4_neo4j_system(state, adapter) as system:
        first = system.increment4.build_and_promote(
            _request(
                GENERATION_1,
                snapshot,
                key="increment4-retry-retired-cleanup-prior-v1",
            ),
            proof=extraction_proof(),
        )
        adapter.fail_cleanup_generation = str(GENERATION_1)
        with pytest.raises(
            Neo4jWriteError,
            match="retired-generation cleanup failure",
        ):
            system.increment4.build_and_promote(
                replacement_request,
                proof=extraction_proof(),
            )
        first_status = system.increment4.generation_status(
            GENERATION_1, proof=extraction_proof()
        )
        second_status = system.increment4.generation_status(
            GENERATION_2, proof=extraction_proof()
        )
        assert first_status.generation.state is ProjectionGenerationState.RETIRED
        assert second_status.generation.state is ProjectionGenerationState.ACTIVE
        assert any(key[0] == str(GENERATION_1) for key in adapter.deliveries)
        serving_before_retry = {
            key: value
            for key, value in adapter.deliveries.items()
            if key[0] == str(GENERATION_2)
        }
        apply_before_retry = adapter.apply_count
        reconcile_before_retry = adapter.reconcile_count

        replay = system.increment4.build_and_promote(
            replacement_request,
            proof=extraction_proof(),
        )

    assert replay.generation.state is ProjectionGenerationState.ACTIVE
    assert replay.prior_generation is not None
    assert replay.prior_generation.generation_id == GENERATION_1
    assert replay.deleted_target_graph_record_count == 0
    assert replay.purged_retired_graph_record_count == first.projected_batch_count
    assert adapter.apply_count == apply_before_retry
    assert adapter.reconcile_count == reconcile_before_retry + 1
    assert not any(key[0] == str(GENERATION_1) for key in adapter.deliveries)
    assert {
        key: value
        for key, value in adapter.deliveries.items()
        if key[0] == str(GENERATION_2)
    } == serving_before_retry


def test_increment4_family_rejects_every_generic_projection_mutation(
    tmp_path: Path,
) -> None:
    state, snapshot = admitted_increment4_fixture(tmp_path)
    adapter = MemoryNeo4jAdapter()

    with open_increment4_neo4j_system(state, adapter) as system:
        built = system.increment4.build_and_promote(
            _request(GENERATION_1, snapshot, key="increment4-generic-guard-v1"),
            proof=extraction_proof(),
        )
        version = built.generation.authority_aggregate_version
        digest = digest_canonical({"generic": "increment4-guard"})
        operations = (
            lambda: system.projections.register_family(
                ProjectionFamilyRegistrationRequest(
                    family_id=_FAMILY_ID,
                    idempotency_key="generic-register-increment4-v1",
                ),
                proof=extraction_proof(),
            ),
            lambda: system.projections.create_generation(
                ProjectionGenerationCreateRequest(
                    generation_id=GENERATION_2,
                    family_id=_FAMILY_ID,
                    reason_code="GENERIC_CREATE_BLOCKED",
                    idempotency_key="generic-create-increment4-v1",
                ),
                proof=extraction_proof(),
            ),
            lambda: system.projections.transition_generation(
                ProjectionGenerationTransitionRequest(
                    generation_id=GENERATION_1,
                    expected_authority_version=version,
                    target_state=ProjectionGenerationState.FAILED,
                    reason_code="GENERIC_TRANSITION_BLOCKED",
                    idempotency_key="generic-transition-increment4-v1",
                ),
                proof=extraction_proof(),
            ),
            lambda: system.projections.validate_generation(
                ProjectionGenerationValidationRequest(
                    generation_id=GENERATION_1,
                    expected_authority_version=version,
                    checkpoint_ledger_seq=built.checkpoint_ledger_seq,
                    service_compatibility_digest=digest,
                    projection_state_digest=digest,
                    reason_code="GENERIC_VALIDATE_BLOCKED",
                    idempotency_key="generic-validate-increment4-v1",
                ),
                proof=extraction_proof(),
            ),
            lambda: system.projections.promote_generation(
                ProjectionGenerationPromotionRequest(
                    generation_id=GENERATION_1,
                    expected_authority_version=version,
                    checkpoint_ledger_seq=built.checkpoint_ledger_seq,
                    validation_digest=built.validation.validation_digest,
                    reason_code="GENERIC_PROMOTE_BLOCKED",
                    idempotency_key="generic-promote-increment4-v1",
                ),
                proof=extraction_proof(),
            ),
            lambda: system.projections.record_delivery(
                ProjectionDeliveryRequest(
                    generation_id=GENERATION_1,
                    expected_authority_version=version,
                    ledger_seq=1,
                    outcome=ProjectionDeliveryOutcome.IGNORED_OPTIONAL,
                    idempotency_key="generic-delivery-increment4-v1",
                ),
                proof=extraction_proof(),
            ),
            lambda: system.projections.resolve_gap(
                ProjectionGapResolutionRequest(
                    generation_id=GENERATION_1,
                    expected_authority_version=version,
                    gap_id=ProjectionGapId.parse(
                        "00000000-0000-4000-8000-000000004999"
                    ),
                    reason_code="GENERIC_GAP_BLOCKED",
                    idempotency_key="generic-gap-increment4-v1",
                ),
                proof=extraction_proof(),
            ),
        )
        before_apply = adapter.apply_count
        before_cleanup = adapter.cleanup_count
        for operation in operations:
            with pytest.raises(
                ProjectionStateError,
                match="requires its bounded controller",
            ):
                operation()
        after = system.increment4.generation_status(
            GENERATION_1, proof=extraction_proof()
        )

    assert after.generation == built.generation
    assert adapter.apply_count == before_apply
    assert adapter.cleanup_count == before_cleanup
