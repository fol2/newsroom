from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3

import pytest

from newsroom.authority import (
    AggregateId,
    AuthorityPersistenceError,
    InlinePayload,
    SemanticCommand,
)
from newsroom.projection import (
    CompleteProjectionProfile,
    INTEGRATED_FIXTURE_V2_PROJECTION,
    INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID,
    ProjectionDeliveryOutcome,
    ProjectionDeliveryRequest,
    ProjectionFamilyRegistrationRequest,
    ProjectionGenerationPromotionRequest,
    ProjectionGenerationState,
    ProjectionGenerationValidationRequest,
    ProjectionStateError,
)
from newsroom.projection.models import ProjectionContractError
from newsroom.projection.neo4j import (
    CompleteGenerationQualificationRequest,
    CompleteGenerationValidationRequest,
    CompleteRebuildRequest,
    Neo4jIdentityConflict,
)

from .complete_projection_2b_helpers import (
    MemoryCompleteNeo4jAdapter,
    open_complete_test_system,
    proof,
    register_complete_generation,
    seed_complete_fixture_authority,
)


def _latest(database: Path) -> int:
    with sqlite3.connect(database) as conn:
        return int(
            conn.execute(
                "SELECT COALESCE(MAX(ledger_seq),0) FROM ledger_events "
                "WHERE security_scope != 'authority.projection'"
            ).fetchone()[0]
        )


def _setup(tmp_path: Path, *, adapter: MemoryCompleteNeo4jAdapter | None = None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    tmp_path.chmod(0o700)
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    seed_complete_fixture_authority(database, object_root=object_root)
    selected = adapter or MemoryCompleteNeo4jAdapter()
    system = open_complete_test_system(
        database,
        object_root=object_root,
        adapter=selected,
    )
    generation = register_complete_generation(system)
    return database, object_root, selected, system, generation


def _rebuild(system, generation, database: Path, *, key: str = "complete-rebuild"):
    return system.complete.rebuild(
        CompleteRebuildRequest(
            generation_id=generation.generation_id,
            expected_authority_version=generation.authority_aggregate_version,
            through_ledger_seq=_latest(database),
            reason_code="INCREMENT_2B_COMPLETE_REBUILD",
            idempotency_key=key,
        ),
        proof=proof(),
    )


def _current(system, generation_id):
    return next(
        item
        for item in system.projections.generations(
            INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID,
            proof=proof(),
        )
        if item.generation_id == generation_id
    )


def _tamper_immutable_row(
    database: Path,
    *,
    trigger_name: str,
    statement: str,
) -> None:
    with sqlite3.connect(database) as conn:
        trigger_sql = str(
            conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",
                (trigger_name,),
            ).fetchone()[0]
        )
        conn.execute(f"DROP TRIGGER {trigger_name}")
        conn.execute(statement)
        conn.execute(trigger_sql)


def _source_command(*, key: str) -> SemanticCommand:
    return SemanticCommand(
        command_type="source.item.write",
        aggregate_id=AggregateId.new(),
        expected_aggregate_version=0,
        payload=InlinePayload(
            {"headline": "Concurrent Increment 2B authority", "count": 1}
        ),
        idempotency_key=key,
    )


def test_complete_facade_exposes_only_complete_derivative_operations() -> None:
    from newsroom.authority._complete_projection_system import CompleteNeo4jProjector

    public = {
        name
        for name in dir(CompleteNeo4jProjector)
        if not name.startswith("_")
    }
    assert public == {
        "deliver",
        "qualify_generation",
        "rebuild",
        "validate_generation",
    }


def test_structural_only_family_cannot_be_registered_by_complete_authority(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    adapter = MemoryCompleteNeo4jAdapter()
    system = open_complete_test_system(
        database,
        object_root=object_root,
        adapter=adapter,
    )
    try:
        with pytest.raises(ProjectionStateError, match="structural-only"):
            system.projections.register_family(
                ProjectionFamilyRegistrationRequest(
                    "graph.structural",
                    "complete-reject-structural-family",
                ),
                proof=proof(),
            )
    finally:
        system.close()


def test_complete_rebuild_validate_qualify_and_promote_is_sqlite_authoritative(
    tmp_path: Path,
) -> None:
    database, _objects, adapter, system, generation = _setup(tmp_path)
    try:
        rebuilt = _rebuild(system, generation, database)
        assert rebuilt.checkpoint_ledger_seq == rebuilt.through_ledger_seq
        assert rebuilt.recorded_delivery_count == rebuilt.through_ledger_seq
        assert rebuilt.blocked_delivery_count == 0
        assert adapter.bootstrap_index_count == 1

        current = _current(system, generation.generation_id)
        validation = system.complete.validate_generation(
            CompleteGenerationValidationRequest(
                generation_id=generation.generation_id,
                expected_authority_version=current.authority_aggregate_version,
                checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
                reason_code="INCREMENT_2B_COMPLETE_VALIDATE",
                idempotency_key="complete-validate",
            ),
            proof=proof(),
        )
        qualification = system.complete.qualify_generation(
            CompleteGenerationQualificationRequest(
                generation_id=generation.generation_id,
                checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
                profile=CompleteProjectionProfile.FIXTURE_QUALIFICATION,
            ),
            proof=proof(),
        )
        assert qualification.projection_state_digest == (
            validation.projection_state_digest
        )
        assert len(qualification.fulltext_hits) == 4
        assert len(qualification.vector_hits) == 3

        validating = _current(system, generation.generation_id)
        promoted = system.projections.promote_generation(
            ProjectionGenerationPromotionRequest(
                generation_id=generation.generation_id,
                expected_authority_version=(
                    validating.authority_aggregate_version
                ),
                checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
                validation_digest=validation.validation_digest,
                reason_code="INCREMENT_2B_COMPLETE_PROMOTE",
                idempotency_key="complete-promote",
            ),
            proof=proof(),
        )
        assert promoted.generation.generation_id == generation.generation_id
        assert _current(system, generation.generation_id).state is (
            ProjectionGenerationState.ACTIVE
        )
    finally:
        system.close()
    assert adapter.closed is True


def test_generic_delivery_and_validation_are_rejected_for_complete_generation(
    tmp_path: Path,
) -> None:
    database, _objects, _adapter, system, generation = _setup(tmp_path)
    try:
        with pytest.raises(ProjectionStateError, match="typed complete projector"):
            system.projections.record_delivery(
                ProjectionDeliveryRequest(
                    generation_id=generation.generation_id,
                    expected_authority_version=(
                        generation.authority_aggregate_version
                    ),
                    ledger_seq=1,
                    outcome=ProjectionDeliveryOutcome.APPLIED,
                    idempotency_key="generic-delivery-rejected",
                ),
                proof=proof(),
            )
        with pytest.raises(ProjectionStateError, match="complete reconciliation"):
            system.projections.validate_generation(
                ProjectionGenerationValidationRequest(
                    generation_id=generation.generation_id,
                    expected_authority_version=(
                        generation.authority_aggregate_version
                    ),
                    checkpoint_ledger_seq=0,
                    service_compatibility_digest="sha256:" + "1" * 64,
                    projection_state_digest="sha256:" + "2" * 64,
                    reason_code="GENERIC_VALIDATE_REJECTED",
                    idempotency_key="generic-validation-rejected",
                ),
                proof=proof(),
            )
    finally:
        system.close()


def test_rebuild_requires_exact_current_sqlite_watermark_before_cleanup(
    tmp_path: Path,
) -> None:
    database, _objects, adapter, system, generation = _setup(tmp_path)
    try:
        latest = _latest(database)
        with pytest.raises(ProjectionStateError, match="exact current authority watermark"):
            system.complete.rebuild(
                CompleteRebuildRequest(
                    generation_id=generation.generation_id,
                    expected_authority_version=(
                        generation.authority_aggregate_version
                    ),
                    through_ledger_seq=latest - 1,
                    reason_code="STALE_COMPLETE_REBUILD",
                    idempotency_key="stale-complete-rebuild",
                ),
                proof=proof(),
            )
        assert adapter.cleanup_count == 0
        assert adapter.deliveries == {}
    finally:
        system.close()


def test_validation_transaction_rejects_source_advance_during_reconciliation(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    seed_complete_fixture_authority(
        database,
        object_root=object_root,
    )
    adapter = MemoryCompleteNeo4jAdapter()
    system = open_complete_test_system(
        database,
        object_root=object_root,
        adapter=adapter,
    )
    generation = register_complete_generation(system)
    try:
        rebuilt = _rebuild(system, generation, database)
        current = _current(system, generation.generation_id)
        original = adapter.reconcile_complete_generation
        advanced = False

        def reconcile_and_advance(**kwargs):
            nonlocal advanced
            digest = original(**kwargs)
            if not advanced:
                advanced = True
                system.commands.execute(
                    _source_command(
                        key="validation-concurrent-source-advance"
                    ),
                    proof=proof(),
                )
            return digest

        adapter.reconcile_complete_generation = reconcile_and_advance
        with pytest.raises(
            ProjectionStateError,
            match="source watermark changed before authority commit",
        ):
            system.complete.validate_generation(
                CompleteGenerationValidationRequest(
                    generation_id=generation.generation_id,
                    expected_authority_version=(
                        current.authority_aggregate_version
                    ),
                    checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
                    reason_code="CONCURRENT_SOURCE_VALIDATE",
                    idempotency_key="concurrent-source-validate",
                ),
                proof=proof(),
            )
        assert _current(system, generation.generation_id).state is (
            ProjectionGenerationState.BUILDING
        )
    finally:
        system.close()


def test_promotion_transaction_rejects_source_advance_during_reconciliation(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    seed_complete_fixture_authority(
        database,
        object_root=object_root,
    )
    adapter = MemoryCompleteNeo4jAdapter()
    system = open_complete_test_system(
        database,
        object_root=object_root,
        adapter=adapter,
    )
    generation = register_complete_generation(system)
    try:
        rebuilt = _rebuild(system, generation, database)
        building = _current(system, generation.generation_id)
        validation = system.complete.validate_generation(
            CompleteGenerationValidationRequest(
                generation_id=generation.generation_id,
                expected_authority_version=(
                    building.authority_aggregate_version
                ),
                checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
                reason_code="INCREMENT_2B_COMPLETE_VALIDATE",
                idempotency_key="complete-validate-before-race",
            ),
            proof=proof(),
        )
        validating = _current(system, generation.generation_id)
        original = adapter.reconcile_complete_generation
        advanced = False

        def reconcile_and_advance(**kwargs):
            nonlocal advanced
            digest = original(**kwargs)
            if not advanced:
                advanced = True
                system.commands.execute(
                    _source_command(
                        key="promotion-concurrent-source-advance"
                    ),
                    proof=proof(),
                )
            return digest

        adapter.reconcile_complete_generation = reconcile_and_advance
        with pytest.raises(
            ProjectionStateError,
            match="source watermark changed before authority commit",
        ):
            system.projections.promote_generation(
                ProjectionGenerationPromotionRequest(
                    generation_id=generation.generation_id,
                    expected_authority_version=(
                        validating.authority_aggregate_version
                    ),
                    checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
                    validation_digest=validation.validation_digest,
                    reason_code="CONCURRENT_SOURCE_PROMOTE",
                    idempotency_key="concurrent-source-promote",
                ),
                proof=proof(),
            )
        assert _current(system, generation.generation_id).state is (
            ProjectionGenerationState.VALIDATING
        )
    finally:
        system.close()


def test_qualification_rejects_source_advance_during_query_evidence(
    tmp_path: Path,
) -> None:
    database, _object_root, adapter, system, generation = _setup(tmp_path)
    try:
        rebuilt = _rebuild(system, generation, database)
        building = _current(system, generation.generation_id)
        system.complete.validate_generation(
            CompleteGenerationValidationRequest(
                generation_id=generation.generation_id,
                expected_authority_version=(
                    building.authority_aggregate_version
                ),
                checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
                reason_code="INCREMENT_2B_COMPLETE_VALIDATE",
                idempotency_key="complete-validate-before-qualification-race",
            ),
            proof=proof(),
        )
        original = adapter.qualify_complete_generation
        advanced = False

        def qualify_and_advance(**kwargs):
            nonlocal advanced
            qualification = original(**kwargs)
            if not advanced:
                advanced = True
                system.commands.execute(
                    _source_command(
                        key="qualification-concurrent-source-advance"
                    ),
                    proof=proof(),
                )
            return qualification

        adapter.qualify_complete_generation = qualify_and_advance
        with pytest.raises(
            ProjectionStateError,
            match="exact current source watermark",
        ):
            system.complete.qualify_generation(
                CompleteGenerationQualificationRequest(
                    generation_id=generation.generation_id,
                    checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
                    profile=CompleteProjectionProfile.FIXTURE_QUALIFICATION,
                ),
                proof=proof(),
            )
    finally:
        system.close()


def test_store_open_rejects_complete_generation_binding_column_tamper(
    tmp_path: Path,
) -> None:
    database, object_root, _adapter, system, _generation = _setup(tmp_path)
    system.close()
    _tamper_immutable_row(
        database,
        trigger_name="immutable_projection_generation_complete_update",
        statement=(
            "UPDATE projection_generation_complete_bindings "
            "SET canonical_digest='sha256:" + "0" * 64 + "'"
        ),
    )

    with pytest.raises(
        AuthorityPersistenceError,
        match="complete projection generation binding",
    ):
        open_complete_test_system(
            database,
            object_root=object_root,
            adapter=MemoryCompleteNeo4jAdapter(),
        )


def test_store_open_rejects_complete_validation_binding_column_tamper(
    tmp_path: Path,
) -> None:
    database, object_root, _adapter, system, generation = _setup(tmp_path)
    rebuilt = _rebuild(system, generation, database)
    current = _current(system, generation.generation_id)
    system.complete.validate_generation(
        CompleteGenerationValidationRequest(
            generation_id=generation.generation_id,
            expected_authority_version=current.authority_aggregate_version,
            checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
            reason_code="INCREMENT_2B_COMPLETE_VALIDATE",
            idempotency_key="complete-validation-before-binding-tamper",
        ),
        proof=proof(),
    )
    system.close()
    _tamper_immutable_row(
        database,
        trigger_name="immutable_projection_complete_validation_update",
        statement=(
            "UPDATE projection_generation_complete_validations "
            "SET canonical_digest='sha256:" + "0" * 64 + "'"
        ),
    )

    with pytest.raises(
        AuthorityPersistenceError,
        match="complete projection validation binding",
    ):
        open_complete_test_system(
            database,
            object_root=object_root,
            adapter=MemoryCompleteNeo4jAdapter(),
        )


def test_exact_rebuild_replay_restores_derivatives_without_new_authority(
    tmp_path: Path,
) -> None:
    database, _objects, adapter, system, generation = _setup(tmp_path)
    try:
        request = CompleteRebuildRequest(
            generation_id=generation.generation_id,
            expected_authority_version=generation.authority_aggregate_version,
            through_ledger_seq=_latest(database),
            reason_code="INCREMENT_2B_REPLAY_REBUILD",
            idempotency_key="complete-rebuild-replay",
        )
        first = system.complete.rebuild(request, proof=proof())
        before = system.events.after(0, limit=1000, proof=proof())
        adapter.cleanup_complete_generation(
            first.identity,
            fulltext=INTEGRATED_FIXTURE_V2_PROJECTION.fulltext_contract,
            vector=INTEGRATED_FIXTURE_V2_PROJECTION.vector_contract,
        )
        assert adapter.deliveries == {}

        replay = system.complete.rebuild(request, proof=proof())

        assert replay.authority_command_replayed is True
        assert replay.rebuild_authority_event_id == (
            first.rebuild_authority_event_id
        )
        assert replay.recorded_delivery_count == 0
        assert replay.reapplied_delivery_count == first.through_ledger_seq
        assert system.events.after(0, limit=1000, proof=proof()) == before
        assert len(adapter.deliveries) == first.through_ledger_seq
    finally:
        system.close()


def test_boundary_rejects_incomplete_normalized_query_evidence(
    tmp_path: Path,
) -> None:
    database, _objects, adapter, system, generation = _setup(tmp_path)
    try:
        rebuilt = _rebuild(system, generation, database)
        current = _current(system, generation.generation_id)
        original = adapter.qualify_complete_generation

        def omit_normalized_evidence(**kwargs):
            qualification = original(**kwargs)
            return replace(
                qualification,
                fulltext_hits=tuple(
                    hit
                    for hit in qualification.fulltext_hits
                    if not hit.query_id.endswith(".normalized")
                ),
            )

        adapter.qualify_complete_generation = omit_normalized_evidence
        with pytest.raises(
            Neo4jIdentityConflict,
            match="full-text query evidence is incomplete",
        ):
            system.complete.validate_generation(
                CompleteGenerationValidationRequest(
                    generation_id=generation.generation_id,
                    expected_authority_version=(
                        current.authority_aggregate_version
                    ),
                    checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
                    reason_code="INCOMPLETE_NORMALIZED_QUERY_EVIDENCE",
                    idempotency_key="incomplete-normalized-query-evidence",
                ),
                proof=proof(),
            )
    finally:
        system.close()


def test_reconciliation_or_qualification_mismatch_blocks_validation(
    tmp_path: Path,
) -> None:
    for mode in ("reconcile", "qualify"):
        root = tmp_path / mode
        adapter = MemoryCompleteNeo4jAdapter(
            reconciliation_mismatch=(mode == "reconcile"),
            qualification_mismatch=(mode == "qualify"),
        )
        database, _objects, _adapter, system, generation = _setup(
            root,
            adapter=adapter,
        )
        try:
            rebuilt = _rebuild(
                system,
                generation,
                database,
                key=f"{mode}-rebuild",
            )
            current = _current(system, generation.generation_id)
            with pytest.raises(Neo4jIdentityConflict):
                system.complete.validate_generation(
                    CompleteGenerationValidationRequest(
                        generation_id=generation.generation_id,
                        expected_authority_version=(
                            current.authority_aggregate_version
                        ),
                        checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
                        reason_code="MISMATCH_VALIDATE",
                        idempotency_key=f"{mode}-validate",
                    ),
                    proof=proof(),
                )
            assert _current(system, generation.generation_id).state is (
                ProjectionGenerationState.BUILDING
            )
        finally:
            system.close()


def test_fixture_only_profile_is_rejected_for_production_qualification(
    tmp_path: Path,
) -> None:
    database, _objects, _adapter, system, generation = _setup(tmp_path)
    try:
        rebuilt = _rebuild(system, generation, database)
        current = _current(system, generation.generation_id)
        system.complete.validate_generation(
            CompleteGenerationValidationRequest(
                generation_id=generation.generation_id,
                expected_authority_version=current.authority_aggregate_version,
                checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
                reason_code="QUALIFICATION_VALIDATE",
                idempotency_key="qualification-validate",
            ),
            proof=proof(),
        )
        with pytest.raises(ProjectionContractError, match="outside qualification"):
            system.complete.qualify_generation(
                CompleteGenerationQualificationRequest(
                    generation_id=generation.generation_id,
                    checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
                    profile=CompleteProjectionProfile.PRODUCTION,
                ),
                proof=proof(),
            )
    finally:
        system.close()
