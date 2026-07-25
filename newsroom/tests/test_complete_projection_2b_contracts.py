from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from newsroom.projection import (
    CompleteProjectionContract,
    CompleteProjectionContractRegistry,
    CompleteProjectionProfile,
    FullTextIndexContract,
    INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID,
    INTEGRATED_FIXTURE_V2_PROJECTION,
    ProjectionContractError,
    VectorIndexContract,
    with_integrated_fixture_v2_complete_projection,
)
from newsroom.tests.projection_b1_helpers import projection_contracts


_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE = _ROOT / "fixtures/integrated_fixture_v2_projection.json"
_SCHEMA = _ROOT / "fixtures/integrated_fixture_v2_projection.schema.json"


def test_fixture_projection_is_checked_bilingual_and_complete() -> None:
    fixture = INTEGRATED_FIXTURE_V2_PROJECTION

    assert fixture.schema_version == "integrated_fixture_v2_projection_v1"
    assert fixture.dimensions == 16
    assert fixture.component_scale == 1_000_000
    assert len(fixture.documents) == 7
    assert {item.language for item in fixture.documents} == {"en-GB", "zh-HK"}
    assert fixture.expected_tombstoned_passage_ids == (
        "ifv2-tombstoned-negative",
    )
    assert fixture.complete_contract.required_derivatives == (
        "ADMITTED_RELATION",
        "FULL_TEXT",
        "STRUCTURAL",
        "VECTOR",
    )
    assert fixture.fulltext_contract.provider == "fulltext-2.0"
    assert fixture.vector_contract.provider == "vector-2026.06"


def test_projection_fixture_json_satisfies_committed_schema() -> None:
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    value = json.loads(_FIXTURE.read_text(encoding="utf-8"))

    errors = tuple(Draft202012Validator(schema).iter_errors(value))
    assert errors == ()


def test_fulltext_normalization_is_nfkc_casefolded_and_whitespace_stable() -> None:
    contract = INTEGRATED_FIXTURE_V2_PROJECTION.fulltext_contract

    assert contract.normalize("  ＳYNTHETIC\n Portal  ") == "synthetic portal"
    assert contract.normalize("合成網上平台　截止日期") == "合成網上平台 截止日期"


def test_fulltext_contract_rejects_eventual_consistency() -> None:
    contract = INTEGRATED_FIXTURE_V2_PROJECTION.fulltext_contract

    with pytest.raises(ProjectionContractError, match="synchronous"):
        replace(contract, eventually_consistent=True)


def test_vector_contract_is_fixed_finite_and_fixture_only() -> None:
    contract = INTEGRATED_FIXTURE_V2_PROJECTION.vector_contract
    document = INTEGRATED_FIXTURE_V2_PROJECTION.document_by_id["ifv2-new-en"]

    vector = contract.vector_from_components(document.components)
    assert len(vector) == 16
    assert any(value != 0 for value in vector)
    contract.require_profile(CompleteProjectionProfile.FIXTURE_QUALIFICATION)

    with pytest.raises(ProjectionContractError, match="outside qualification"):
        contract.require_profile(CompleteProjectionProfile.PRODUCTION)
    with pytest.raises(ProjectionContractError, match="outside qualification"):
        contract.require_profile(CompleteProjectionProfile.EVALUATION)


def test_vector_contract_rejects_wrong_dimension_zero_and_out_of_range() -> None:
    contract = INTEGRATED_FIXTURE_V2_PROJECTION.vector_contract

    with pytest.raises(ProjectionContractError, match="wrong dimension"):
        contract.vector_from_components((1,) * 15)
    with pytest.raises(ProjectionContractError, match="cannot be all zero"):
        contract.vector_from_components((0,) * 16)
    with pytest.raises(ProjectionContractError, match="fixed-point range"):
        contract.vector_from_components((contract.component_scale + 1,) + (0,) * 15)
    with pytest.raises(ProjectionContractError, match="fixed-point integers"):
        contract.vector_from_components((True,) + (0,) * 15)


def test_complete_contract_rejects_partial_derivative_set() -> None:
    contract = INTEGRATED_FIXTURE_V2_PROJECTION.complete_contract

    with pytest.raises(ProjectionContractError, match="exact four"):
        replace(contract, required_derivatives=("STRUCTURAL", "FULL_TEXT"))


def test_complete_registry_resolves_exact_contract_chain() -> None:
    fixture = INTEGRATED_FIXTURE_V2_PROJECTION
    registry = fixture.contracts

    assert registry.fulltext(fixture.fulltext_contract.contract_digest) is fixture.fulltext_contract
    assert registry.vector(fixture.vector_contract.contract_digest) is fixture.vector_contract
    assert registry.fixture_manifest(fixture.manifest_digest).manifest_digest == fixture.manifest_digest
    assert registry.complete(fixture.complete_contract.contract_digest) is fixture.complete_contract

    with pytest.raises(ProjectionContractError, match="unknown full-text"):
        registry.fulltext("sha256:" + "0" * 64)


def test_complete_registry_rejects_unknown_contract_reference() -> None:
    fixture = INTEGRATED_FIXTURE_V2_PROJECTION
    invalid = replace(
        fixture.complete_contract,
        fulltext_contract_digest="sha256:" + "0" * 64,
    )

    with pytest.raises(ProjectionContractError, match="unknown full-text"):
        CompleteProjectionContractRegistry(
            fulltext_contracts=(fixture.fulltext_contract,),
            vector_contracts=(fixture.vector_contract,),
            fixture_manifests=(fixture.fixture_manifest_contract,),
            complete_contracts=(invalid,),
        )


def test_complete_family_extends_structural_registry_without_mutating_base() -> None:
    base = projection_contracts()
    complete = with_integrated_fixture_v2_complete_projection(base)

    assert INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID not in {
        item.family_id for item in base.families.definitions()
    }
    family = complete.family(INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID)
    structural = base.family("graph.structural")
    assert family.ontology_contract_digest == structural.ontology_contract_digest
    assert family.mapping_contract_digest == structural.mapping_contract_digest
    assert family.complete_projection_contract_digest == (
        INTEGRATED_FIXTURE_V2_PROJECTION.complete_contract.contract_digest
    )
    assert complete.complete_projections is not None


def test_complete_family_extension_is_idempotent() -> None:
    once = with_integrated_fixture_v2_complete_projection(projection_contracts())
    twice = with_integrated_fixture_v2_complete_projection(once)

    assert twice.family(INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID).digest == (
        once.family(INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID).digest
    )
    assert twice.complete_projections is not None
    assert len(twice.complete_projections.complete_contracts()) == 1


def test_complete_contract_types_remain_immutable() -> None:
    for value in (
        INTEGRATED_FIXTURE_V2_PROJECTION.fulltext_contract,
        INTEGRATED_FIXTURE_V2_PROJECTION.vector_contract,
        INTEGRATED_FIXTURE_V2_PROJECTION.complete_contract,
        INTEGRATED_FIXTURE_V2_PROJECTION.fixture_manifest_contract,
    ):
        with pytest.raises((AttributeError, TypeError)):
            value.contract_id = "changed"  # type: ignore[attr-defined]
