from __future__ import annotations

from pathlib import Path

import pytest

from newsroom.authority import AuthorizationDenied, digest_canonical
from newsroom.projection import (
    ProjectionFamilyRegistrationRequest,
    ProjectionGenerationCreateRequest,
    ProjectionGenerationId,
    ProjectionGenerationValidationRequest,
    ProjectionStateError,
)
from newsroom.projection.neo4j import (
    Neo4jIdentityConflict,
    StructuralGenerationValidationRequest,
    StructuralRebuildRequest,
)
from newsroom.projection.neo4j._state import (
    _actual_projection_state_digest,
    _delivery_properties,
    _expected_projection_state_digest,
    _node_properties,
    _relation_identity_properties,
    _relation_properties,
)

from .projection_b1_helpers import FAMILY_ID
from .projection_b2_helpers import (
    MemoryNeo4jAdapter,
    open_b2_system,
    proof,
    source_command,
    structural_batch,
)


def _registered_generation(system):
    system.projections.register_family(
        ProjectionFamilyRegistrationRequest(
            FAMILY_ID,
            "b3-reconciliation-family",
        ),
        proof=proof(),
    )
    return system.projections.create_generation(
        ProjectionGenerationCreateRequest(
            ProjectionGenerationId.new(),
            FAMILY_ID,
            "B3_RECONCILIATION",
            "b3-reconciliation-generation",
        ),
        proof=proof(),
    )


def _rebuild_source(system, generation):
    system.commands.execute(
        source_command(key="b3-reconciliation-source"),
        proof=proof(),
    )
    current = next(
        item
        for item in system.projections.generations(FAMILY_ID, proof=proof())
        if item.generation_id == generation.generation_id
    )
    through = system.events.after(0, limit=1000, proof=proof())[-1].ledger_seq
    rebuilt = system.structural.rebuild(
        StructuralRebuildRequest(
            generation_id=current.generation_id,
            expected_authority_version=current.authority_aggregate_version,
            through_ledger_seq=through,
            reason_code="B3_RECONCILIATION_REBUILD",
            idempotency_key="b3-reconciliation-rebuild",
        ),
        proof=proof(),
    )
    current = next(
        item
        for item in system.projections.generations(FAMILY_ID, proof=proof())
        if item.generation_id == generation.generation_id
    )
    return current, rebuilt


def test_neo4j_composition_rejects_unreconciled_validation_bypass(
    tmp_path: Path,
) -> None:
    adapter = MemoryNeo4jAdapter()
    system = open_b2_system(tmp_path / "authority.sqlite3", adapter)
    try:
        generation = _registered_generation(system)
        current, rebuilt = _rebuild_source(system, generation)
        before = system.events.after(0, limit=1000, proof=proof())

        with pytest.raises(ProjectionStateError, match="structural reconciliation"):
            system.projections.validate_generation(
                ProjectionGenerationValidationRequest(
                    generation_id=current.generation_id,
                    expected_authority_version=current.authority_aggregate_version,
                    checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
                    service_compatibility_digest=digest_canonical(
                        {"caller": "service"}
                    ),
                    projection_state_digest=digest_canonical(
                        {"caller": "graph"}
                    ),
                    reason_code="CALLER_DIGEST_FORBIDDEN",
                    idempotency_key="caller-digest-forbidden",
                ),
                proof=proof(),
            )

        assert system.events.after(0, limit=1000, proof=proof()) == before
    finally:
        system.close()


def test_structural_validation_reconciles_before_authority_commit(
    tmp_path: Path,
) -> None:
    adapter = MemoryNeo4jAdapter(reconciliation_mismatch=True)
    system = open_b2_system(tmp_path / "authority.sqlite3", adapter)
    try:
        generation = _registered_generation(system)
        current, rebuilt = _rebuild_source(system, generation)
        request = StructuralGenerationValidationRequest(
            generation_id=current.generation_id,
            expected_authority_version=current.authority_aggregate_version,
            checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
            reason_code="B3_RECONCILE",
            idempotency_key="b3-reconcile-validation",
        )
        before = system.events.after(0, limit=1000, proof=proof())

        with pytest.raises(Neo4jIdentityConflict, match="differs"):
            system.structural.validate_generation(request, proof=proof())
        assert system.events.after(0, limit=1000, proof=proof()) == before

        adapter.reconciliation_mismatch = False
        validation = system.structural.validate_generation(request, proof=proof())
        expected = _expected_projection_state_digest(
            str(generation.generation_id),
            tuple(
                batch
                for (stored_generation, _), batch in sorted(
                    adapter.deliveries.items()
                )
                if stored_generation == str(generation.generation_id)
            ),
        )
        assert validation.projection_state_digest == expected
        assert system.structural.validate_generation(
            request, proof=proof()
        ) == validation

        adapter.reconciliation_mismatch = True
        with pytest.raises(Neo4jIdentityConflict, match="differs"):
            system.structural.validate_generation(request, proof=proof())
    finally:
        system.close()


def test_actual_state_digest_requires_fixed_inventory_and_relationships() -> None:
    batch = structural_batch()
    expected = _expected_projection_state_digest(
        str(batch.generation_id),
        (batch,),
    )
    node_by_id = {item.canonical_id: item for item in batch.nodes}
    node_records = [
        (("NewsroomProjectionNode",), _node_properties(batch, item))
        for item in batch.nodes
    ]
    node_records.append(
        (("NewsroomProjectionDelivery",), _delivery_properties(batch))
    )
    for relation in batch.relations:
        node_records.append(
            (
                ("NewsroomProjectionRelationIdentity",),
                _relation_identity_properties(batch, relation),
            )
        )
    relationship_records = [
        (
            ("NewsroomProjectionNode",),
            _node_properties(batch, node_by_id[relation.source_canonical_id]),
            relation.relation_type.value,
            _relation_properties(batch, relation),
            ("NewsroomProjectionNode",),
            _node_properties(batch, node_by_id[relation.target_canonical_id]),
        )
        for relation in batch.relations
    ]

    assert _actual_projection_state_digest(
        str(batch.generation_id),
        node_records=node_records,
        relationship_records=relationship_records,
    ) == expected

    extra_label = list(node_records)
    labels, properties = extra_label[0]
    extra_label[0] = ((*labels, "AttackerLabel"), properties)
    with pytest.raises(Neo4jIdentityConflict, match="fixed labels"):
        _actual_projection_state_digest(
            str(batch.generation_id),
            node_records=extra_label,
            relationship_records=relationship_records,
        )

    wrong_endpoint = list(relationship_records)
    value = list(wrong_endpoint[0])
    target = dict(value[5])
    target["canonical_id"] = value[1]["canonical_id"]
    value[5] = target
    wrong_endpoint[0] = tuple(value)  # type: ignore[assignment]
    with pytest.raises(Neo4jIdentityConflict, match="endpoints"):
        _actual_projection_state_digest(
            str(batch.generation_id),
            node_records=node_records,
            relationship_records=wrong_endpoint,
        )


def test_structural_validation_requires_manage_scope_before_graph_read(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    writer_adapter = MemoryNeo4jAdapter()
    writer = open_b2_system(database, writer_adapter)
    try:
        generation = _registered_generation(writer)
        current, rebuilt = _rebuild_source(writer, generation)
        request = StructuralGenerationValidationRequest(
            generation_id=current.generation_id,
            expected_authority_version=current.authority_aggregate_version,
            checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
            reason_code="B3_RECONCILE_SCOPE",
            idempotency_key="b3-reconcile-scope",
        )
    finally:
        writer.close()

    reader_adapter = MemoryNeo4jAdapter()
    reader = open_b2_system(
        database,
        reader_adapter,
        scopes=frozenset(
            {
                "authority.fixture.events.read",
                "authority.projection.read",
            }
        ),
    )
    try:
        before = reader.events.after(0, limit=1000, proof=proof())
        with pytest.raises(AuthorizationDenied):
            reader.structural.validate_generation(request, proof=proof())
        assert reader_adapter.reconcile_count == 0
        assert reader.events.after(0, limit=1000, proof=proof()) == before
    finally:
        reader.close()
