from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import Event, Thread
from typing import Any

import pytest

from newsroom.authority import AuthorityPersistenceError
from newsroom.projection import (
    ProjectionFamilyRegistrationRequest,
    ProjectionGenerationCreateRequest,
    ProjectionGenerationId,
    ProjectionGenerationPromotionRequest,
    ProjectionGenerationState,
)
from newsroom.projection.neo4j import (
    Neo4jStructuralRead,
    StructuralActiveReadRequest,
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


def _generation(system: Any, generation_id: ProjectionGenerationId):
    return next(
        item
        for item in system.projections.generations(FAMILY_ID, proof=proof())
        if item.generation_id == generation_id
    )


def _register(system: Any) -> None:
    system.projections.register_family(
        ProjectionFamilyRegistrationRequest(
            FAMILY_ID,
            "b3-active-serving-adversarial-family",
        ),
        proof=proof(),
    )


def _create(system: Any, *, suffix: str):
    return system.projections.create_generation(
        ProjectionGenerationCreateRequest(
            ProjectionGenerationId.new(),
            FAMILY_ID,
            "B3_ACTIVE_SERVING_ADVERSARIAL",
            f"b3-active-serving-adversarial-{suffix}",
        ),
        proof=proof(),
    )


def _rebuild(system: Any, generation: Any, *, key: str):
    current = _generation(system, generation.generation_id)
    through = system.events.after(0, limit=1000, proof=proof())[-1].ledger_seq
    return system.structural.rebuild(
        StructuralRebuildRequest(
            generation_id=current.generation_id,
            expected_authority_version=current.authority_aggregate_version,
            through_ledger_seq=through,
            reason_code="B3_ACTIVE_SERVING_ADVERSARIAL_REBUILD",
            idempotency_key=key,
        ),
        proof=proof(),
    )


def _validate(system: Any, generation_id: ProjectionGenerationId, checkpoint: int, *, key: str):
    current = _generation(system, generation_id)
    return system.structural.validate_generation(
        StructuralGenerationValidationRequest(
            generation_id=generation_id,
            expected_authority_version=current.authority_aggregate_version,
            checkpoint_ledger_seq=checkpoint,
            reason_code="B3_ACTIVE_SERVING_ADVERSARIAL_VALIDATE",
            idempotency_key=key,
        ),
        proof=proof(),
    )


def _promote(
    system: Any,
    generation_id: ProjectionGenerationId,
    validation: Any,
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
            reason_code="B3_ACTIVE_SERVING_ADVERSARIAL_PROMOTE",
            idempotency_key=key,
            prior_generation_id=prior_generation_id,
            expected_prior_authority_version=(
                None if prior is None else prior.authority_aggregate_version
            ),
        ),
        proof=proof(),
    )


def _canonical_ids(
    adapter: MemoryNeo4jAdapter,
    generation_id: ProjectionGenerationId,
) -> tuple[str, ...]:
    batches = [
        batch
        for (stored_generation, _), batch in sorted(adapter.deliveries.items())
        if stored_generation == str(generation_id)
    ]
    assert batches
    return tuple(
        sorted(
            {
                node.canonical_id
                for batch in batches
                for node in batch.nodes
            }
        )
    )


def _active_request(canonical_ids: tuple[str, ...]) -> StructuralActiveReadRequest:
    return StructuralActiveReadRequest(
        family_id=FAMILY_ID,
        canonical_ids=canonical_ids,
        query_valid_time=FIXED_NOW,
        limit=100,
    )


class _BlockingReadAdapter(MemoryNeo4jAdapter):
    def __post_init__(self) -> None:
        super().__post_init__()
        self.block_reads = False
        self.read_entered = Event()
        self.release_read = Event()

    def read(
        self,
        *,
        generation_id: str,
        canonical_ids: tuple[str, ...],
        maximum_ledger_seq: int,
        limit: int,
    ) -> Neo4jStructuralRead:
        if self.block_reads:
            self.read_entered.set()
            if not self.release_read.wait(timeout=5):
                raise AssertionError("blocked active read was not released")
        return super().read(
            generation_id=generation_id,
            canonical_ids=canonical_ids,
            maximum_ledger_seq=maximum_ledger_seq,
            limit=limit,
        )


def test_active_read_and_promotion_are_serialized_on_one_process_lock(
    tmp_path: Path,
) -> None:
    adapter = _BlockingReadAdapter()
    system = open_b2_system(tmp_path / "authority.sqlite3", adapter)
    try:
        _register(system)
        system.commands.execute(
            source_command(key="b3-active-race-source"),
            proof=proof(),
        )
        first = _create(system, suffix="first")
        first_rebuild = _rebuild(
            system,
            first,
            key="b3-active-race-first-rebuild",
        )
        first_validation = _validate(
            system,
            first.generation_id,
            first_rebuild.checkpoint_ledger_seq,
            key="b3-active-race-first-validate",
        )
        _promote(
            system,
            first.generation_id,
            first_validation,
            key="b3-active-race-first-promote",
        )

        second = _create(system, suffix="second")
        second_rebuild = _rebuild(
            system,
            second,
            key="b3-active-race-second-rebuild",
        )
        second_validation = _validate(
            system,
            second.generation_id,
            second_rebuild.checkpoint_ledger_seq,
            key="b3-active-race-second-validate",
        )
        request = _active_request(_canonical_ids(adapter, first.generation_id))

        read_results: list[Any] = []
        promotion_results: list[Any] = []
        errors: list[BaseException] = []
        promotion_started = Event()
        promotion_finished = Event()

        def perform_read() -> None:
            try:
                read_results.append(
                    system.structural.read_active(request, proof=proof())
                )
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        def perform_promotion() -> None:
            promotion_started.set()
            try:
                promotion_results.append(
                    _promote(
                        system,
                        second.generation_id,
                        second_validation,
                        key="b3-active-race-second-promote",
                        prior_generation_id=first.generation_id,
                    )
                )
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)
            finally:
                promotion_finished.set()

        adapter.block_reads = True
        read_thread = Thread(target=perform_read)
        promotion_thread = Thread(target=perform_promotion)
        read_thread.start()
        assert adapter.read_entered.wait(timeout=5)
        promotion_thread.start()
        assert promotion_started.wait(timeout=5)
        assert not promotion_finished.wait(timeout=0.2)

        adapter.release_read.set()
        read_thread.join(timeout=5)
        promotion_thread.join(timeout=5)
        assert not read_thread.is_alive()
        assert not promotion_thread.is_alive()
        assert not errors
        assert read_results[0].metadata.generation_id == first.generation_id
        assert promotion_results[0].generation.generation_id == second.generation_id
        assert promotion_results[0].generation.state is ProjectionGenerationState.ACTIVE

        adapter.block_reads = False
        current = system.structural.read_active(request, proof=proof())
        assert current.metadata.generation_id == second.generation_id
    finally:
        system.close()


def test_active_read_fails_closed_if_authority_is_corrupted_to_two_active_generations(
    tmp_path: Path,
) -> None:
    authority_path = tmp_path / "authority.sqlite3"
    adapter = MemoryNeo4jAdapter()
    system = open_b2_system(authority_path, adapter)
    try:
        _register(system)
        system.commands.execute(
            source_command(key="b3-active-duplicate-source"),
            proof=proof(),
        )
        active = _create(system, suffix="active")
        rebuilt = _rebuild(
            system,
            active,
            key="b3-active-duplicate-rebuild",
        )
        validation = _validate(
            system,
            active.generation_id,
            rebuilt.checkpoint_ledger_seq,
            key="b3-active-duplicate-validate",
        )
        _promote(
            system,
            active.generation_id,
            validation,
            key="b3-active-duplicate-promote",
        )
        other = _create(system, suffix="corrupted-second-active")
        canonical_ids = _canonical_ids(adapter, active.generation_id)

        with sqlite3.connect(authority_path) as connection:
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute(
                "DROP INDEX idx_projection_one_active_generation"
            )
            connection.execute(
                "UPDATE projection_generations "
                "SET state='ACTIVE', "
                "lifecycle_version=lifecycle_version+1, "
                "authority_aggregate_version=authority_aggregate_version+1 "
                "WHERE generation_id=?",
                (str(other.generation_id),),
            )

        with pytest.raises(
            AuthorityPersistenceError,
            match="multiple active generations",
        ):
            system.structural.read_active(
                _active_request(canonical_ids),
                proof=proof(),
            )
    finally:
        system.close()
