from __future__ import annotations

from dataclasses import replace

import pytest

from newsroom.projection import CompleteProjectionProfile, INTEGRATED_FIXTURE_V2_PROJECTION
from newsroom.projection.models import ProjectionContractError
from newsroom.projection.neo4j import (
    CompleteDerivativeType,
    CompleteProjectionBatch,
    CompleteProjectionRemoval,
    Neo4jIdentityConflict,
    complete_generation_names,
    expected_complete_projection_state,
)

from .complete_projection_2b_helpers import (
    COMPLETE_GENERATION_ID,
    admitted_relation,
    complete_batch,
    complete_document,
    complete_identity,
    event_id,
)


def test_generation_names_are_deterministic_isolated_and_fixed_relation_type() -> None:
    identity = complete_identity()
    fixture = INTEGRATED_FIXTURE_V2_PROJECTION

    names = complete_generation_names(
        identity,
        fixture.fulltext_contract,
        fixture.vector_contract,
    )

    suffix = f"g{COMPLETE_GENERATION_ID.value.hex}"
    assert names.generation_suffix == suffix
    assert names.document_label.endswith(suffix)
    assert names.fulltext_index_name.endswith(suffix)
    assert names.vector_index_name.endswith(suffix)
    assert names.admitted_relation_type == "DEVELOPMENT_OF"
    assert names.fulltext_index_name != names.vector_index_name


def test_complete_document_exposes_finite_vector_and_stable_digest() -> None:
    document = complete_document()

    assert len(document.vector) == 16
    assert document.document_digest == complete_document().document_digest
    assert all(-1.0 <= component <= 1.0 for component in document.vector)


def test_complete_document_rejects_wrong_dimension_and_boolean_component() -> None:
    document = complete_document()

    with pytest.raises(ProjectionContractError, match="wrong dimension"):
        replace(document, vector_components=document.vector_components[:-1])
    with pytest.raises(ProjectionContractError, match="fixed-point integers"):
        replace(
            document,
            vector_components=(True,) + document.vector_components[1:],
        )


def test_complete_batch_requires_sorted_unique_items_and_exact_source_sequence() -> None:
    document = complete_document()

    with pytest.raises(ProjectionContractError, match="sorted and unique"):
        complete_batch(documents=(document, document))
    with pytest.raises(ProjectionContractError, match="source sequence"):
        complete_batch(documents=(replace(document, source_ledger_seq=2),))


def test_expected_state_applies_document_and_relation_then_removals() -> None:
    identity = complete_identity()
    document = complete_document(identity=identity, ledger_seq=1)
    relation = admitted_relation(identity=identity, ledger_seq=2)
    removal = CompleteProjectionRemoval(
        identity=identity,
        derivative_type=CompleteDerivativeType.FULL_TEXT,
        stable_key=document.passage_id,
        source_event_id=event_id(3),
        source_ledger_seq=3,
        reason_code="OBJECT_REVOKED",
        object_admission_ids=(document.admission_id,),
    )
    batches = (
        complete_batch(identity=identity, ledger_seq=1, documents=(document,)),
        complete_batch(identity=identity, ledger_seq=2, relations=(relation,)),
        complete_batch(identity=identity, ledger_seq=3, removals=(removal,)),
    )
    fixture = INTEGRATED_FIXTURE_V2_PROJECTION

    state = expected_complete_projection_state(
        identity,
        3,
        batches,
        fulltext=fixture.fulltext_contract,
        vector=fixture.vector_contract,
        profile=CompleteProjectionProfile.FIXTURE_QUALIFICATION,
    )

    assert state.documents == ()
    assert state.relations == (relation,)
    assert tuple(item.ledger_seq for item in state.deliveries) == (1, 2, 3)
    assert state.fulltext_index_provider == "fulltext-2.0"
    assert state.vector_index_provider == "vector-2026.06"


def test_expected_state_requires_strict_order_exact_checkpoint_and_identity() -> None:
    identity = complete_identity()
    document = complete_document(identity=identity, ledger_seq=1)
    first = complete_batch(identity=identity, ledger_seq=1, documents=(document,))
    fixture = INTEGRATED_FIXTURE_V2_PROJECTION

    with pytest.raises(Neo4jIdentityConflict, match="exact checkpoint"):
        expected_complete_projection_state(
            identity,
            2,
            (first,),
            fulltext=fixture.fulltext_contract,
            vector=fixture.vector_contract,
            profile=CompleteProjectionProfile.FIXTURE_QUALIFICATION,
        )
    with pytest.raises(Neo4jIdentityConflict, match="strictly ordered"):
        expected_complete_projection_state(
            identity,
            1,
            (first, first),
            fulltext=fixture.fulltext_contract,
            vector=fixture.vector_contract,
            profile=CompleteProjectionProfile.FIXTURE_QUALIFICATION,
        )
    other = complete_identity(
        type(COMPLETE_GENERATION_ID).parse(
            "44444444-4444-4444-8444-444444444444"
        )
    )
    with pytest.raises(Neo4jIdentityConflict, match="another generation"):
        expected_complete_projection_state(
            other,
            1,
            (first,),
            fulltext=fixture.fulltext_contract,
            vector=fixture.vector_contract,
            profile=CompleteProjectionProfile.FIXTURE_QUALIFICATION,
        )


def test_expected_state_rejects_non_qualification_vector_profile() -> None:
    identity = complete_identity()
    fixture = INTEGRATED_FIXTURE_V2_PROJECTION

    with pytest.raises(ProjectionContractError, match="outside qualification"):
        expected_complete_projection_state(
            identity,
            0,
            (),
            fulltext=fixture.fulltext_contract,
            vector=fixture.vector_contract,
            profile=CompleteProjectionProfile.PRODUCTION,
        )
