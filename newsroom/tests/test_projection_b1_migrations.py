from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from newsroom.authority import (
    AggregateId,
    AuthoritySchemaError,
    InlinePayload,
    SemanticCommand,
)
from newsroom.projection import (
    ProjectionDeliveryOutcome,
    ProjectionDeliveryRequest,
    ProjectionFamilyRegistrationRequest,
    ProjectionGenerationCreateRequest,
    ProjectionGenerationId,
)

from .projection_b1_helpers import FAMILY_ID, open_projection_system, proof


def _seed(path: Path):
    system = open_projection_system(path)
    family = system.projections.register_family(
        ProjectionFamilyRegistrationRequest(FAMILY_ID, "family-register"),
        proof=proof(),
    )
    generation = system.projections.create_generation(
        ProjectionGenerationCreateRequest(
            ProjectionGenerationId.new(),
            FAMILY_ID,
            "INITIAL_BUILD",
            "generation-create",
        ),
        proof=proof(),
    )
    system.close()
    return family, generation


def test_projection_migration_history_contracts_and_schema_are_exact(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    _seed(database)
    conn = sqlite3.connect(database)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
        history = conn.execute(
            "SELECT version,name FROM authority_migrations ORDER BY version"
        ).fetchall()
        assert history == [
            (1, "authority_event_foundation_v1"),
            (2, "governed_object_authority_v2"),
            (3, "projection_authority_v3"),
            (4, "projection_generation_promotion_v4"),
        ]
        assert conn.execute(
            "SELECT COUNT(*) FROM projection_ontology_contracts"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM projection_mapping_contracts"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM projection_family_definitions"
        ).fetchone()[0] == 1
        graphiti = conn.execute(
            "SELECT mode,endpoint_reference,secret_reference "
            "FROM projection_graphiti_workspace_contracts"
        ).fetchone()
        assert graphiti == (
            "PROPOSAL_ONLY",
            "config://graphiti/proposal-endpoint",
            "secret://graphiti/proposal-token",
        )
    finally:
        conn.close()


def test_projection_contracts_and_versions_are_immutable(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    _, generation = _seed(database)
    conn = sqlite3.connect(database)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="immutable projection ontology"):
            conn.execute(
                "UPDATE projection_ontology_contracts "
                "SET implementation_version='tampered'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable projection checkpoint"):
            conn.execute(
                "UPDATE projection_checkpoint_versions SET contiguous_ledger_seq=99"
            )
        with pytest.raises(sqlite3.IntegrityError, match="retained"):
            conn.execute(
                "DELETE FROM projection_generations WHERE generation_id=?",
                (str(generation.generation_id),),
            )
    finally:
        conn.close()


def test_reopen_rejects_projection_head_tampering(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    _, generation = _seed(database)
    conn = sqlite3.connect(database)
    try:
        # This update meets the narrow SQL transition trigger but does not have
        # a corresponding authority aggregate version/event. Startup integrity
        # must therefore reject the database rather than trusting the mutable
        # head row.
        conn.execute(
            "UPDATE projection_generations "
            "SET authority_aggregate_version=authority_aggregate_version+1 "
            "WHERE generation_id=?",
            (str(generation.generation_id),),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(Exception, match="authority head is inconsistent"):
        open_projection_system(database)


def test_second_writer_is_rejected_and_first_writer_survives(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    first = open_projection_system(database)
    try:
        with pytest.raises(Exception, match="another authority writer"):
            open_projection_system(database)
        family = first.projections.register_family(
            ProjectionFamilyRegistrationRequest(FAMILY_ID, "family-register"),
            proof=proof(),
        )
        assert family.family_id == FAMILY_ID
    finally:
        first.close()



def _seed_delivery(path: Path):
    system = open_projection_system(path)
    _, generation = _seed_existing_system(system)
    system.commands.execute(
        SemanticCommand(
            command_type="source.item.write",
            aggregate_id=AggregateId.new(),
            expected_aggregate_version=0,
            payload=InlinePayload({"headline": "Integrity", "count": 1}),
            idempotency_key="integrity-source",
        ),
        proof=proof(),
    )
    source = [
        event
        for event in system.events.after(0, limit=100, proof=proof())
        if event.event_type == "source.item.versioned"
    ][0]
    delivery = system.projections.record_delivery(
        ProjectionDeliveryRequest(
            generation.generation_id,
            generation.authority_aggregate_version,
            source.ledger_seq,
            ProjectionDeliveryOutcome.APPLIED,
            "integrity-delivery",
        ),
        proof=proof(),
    )
    system.close()
    return generation, delivery


def _seed_existing_system(system):
    family = system.projections.register_family(
        ProjectionFamilyRegistrationRequest(FAMILY_ID, "family-register"),
        proof=proof(),
    )
    generation = system.projections.create_generation(
        ProjectionGenerationCreateRequest(
            ProjectionGenerationId.new(),
            FAMILY_ID,
            "INITIAL_BUILD",
            "generation-create",
        ),
        proof=proof(),
    )
    return family, generation


def _temporarily_disable_trigger(
    conn: sqlite3.Connection, trigger_name: str
) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",
        (trigger_name,),
    ).fetchone()
    assert row is not None and row[0]
    sql = str(row[0])
    conn.execute(f'DROP TRIGGER "{trigger_name}"')
    return sql


def test_reopen_rejects_generation_head_that_differs_from_exact_version(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    _, generation = _seed(database)
    conn = sqlite3.connect(database)
    try:
        trigger = _temporarily_disable_trigger(
            conn, "projection_generation_update_guard"
        )
        conn.execute(
            "UPDATE projection_generations SET state='ACTIVE' "
            "WHERE generation_id=?",
            (str(generation.generation_id),),
        )
        conn.execute(trigger)
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(Exception, match="exact lifecycle version"):
        open_projection_system(database)


def test_reopen_rejects_delivery_head_and_source_provenance_tampering(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    generation, _delivery = _seed_delivery(database)
    conn = sqlite3.connect(database)
    try:
        state_trigger = _temporarily_disable_trigger(
            conn, "projection_delivery_state_update_guard"
        )
        attempt_trigger = _temporarily_disable_trigger(
            conn, "immutable_projection_delivery_attempt_update"
        )
        conn.execute(
            "UPDATE projection_delivery_states SET finalized=0 "
            "WHERE generation_id=?",
            (str(generation.generation_id),),
        )
        conn.execute(
            "UPDATE projection_delivery_attempts "
            "SET source_event_digest=? WHERE generation_id=?",
            ("sha256:" + "0" * 64, str(generation.generation_id)),
        )
        conn.execute(state_trigger)
        conn.execute(attempt_trigger)
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(Exception, match="source provenance|finalized state"):
        open_projection_system(database)
