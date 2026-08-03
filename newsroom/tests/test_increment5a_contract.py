from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment5 import (
    CONTRACT_PATH,
    INCREMENT_5A_CONTRACT,
    INCREMENT_5A_CONTRACT_DIGEST,
    ComponentDisposition,
    ContractEffect,
    ContractStatus,
    Increment5ContractError,
    RetrievalComponentKind,
    RetrievalMode,
    RetrievalProfileKind,
    load_increment5a_contract,
)


def _record() -> dict[str, object]:
    value = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _resign(record: dict[str, object]) -> bytes:
    payload = record["payload"]
    assert isinstance(payload, dict)
    components = payload["components"]
    assert isinstance(components, list)
    record["component_digests"] = {
        str(component["kind"]): digest_bytes(canonical_json_bytes(component))
        for component in components
        if isinstance(component, dict)
    }
    record["payload_digest"] = digest_bytes(canonical_json_bytes(payload))
    return canonical_json_bytes(record)


def _write(tmp_path: Path, record: dict[str, object], name: str = "contract.json") -> Path:
    path = tmp_path / name
    path.write_bytes(_resign(record))
    return path


def _component(record: dict[str, object], kind: str) -> dict[str, object]:
    payload = record["payload"]
    assert isinstance(payload, dict)
    components = payload["components"]
    assert isinstance(components, list)
    return next(
        component
        for component in components
        if isinstance(component, dict) and component.get("kind") == kind
    )


def test_accepted_on_merge_contract_is_narrow_and_non_production() -> None:
    contract = INCREMENT_5A_CONTRACT

    assert contract.status is ContractStatus.OWNER_ACCEPTED_ON_MERGE
    assert (
        contract.effect
        is ContractEffect.IMPLEMENTATION_AND_NON_PRODUCTION_QUALIFICATION
    )
    assert contract.owner == "fol2"
    assert contract.issue_number == 250
    assert contract.pr_number == 255
    assert contract.effective_when == "PRESENT_ON_MAIN_AFTER_REVIEWED_PR_255"
    assert contract.production_activation_authorized is False
    assert contract.approved_profiles == (
        RetrievalProfileKind.FIXTURE_REPLAY,
        RetrievalProfileKind.PRODUCTION_SHAPED_QUALIFICATION,
    )
    assert contract.required_modes == tuple(RetrievalMode)
    assert contract.contract_digest == (
        "sha256:c7dabaf97301f851c67a2d831f6ac87b34b38c78626ea7edf8f5725ff97f1c58"
    )
    assert INCREMENT_5A_CONTRACT_DIGEST == contract.contract_digest


def test_component_inventory_is_exact_and_vector_model_boundary_is_truthful() -> None:
    components = INCREMENT_5A_CONTRACT.component_by_kind

    assert tuple(components) == tuple(RetrievalComponentKind)
    assert (
        components[RetrievalComponentKind.EMBEDDING].disposition
        is ComponentDisposition.DISABLED_IN_INCREMENT_5_V1
    )
    assert dict(components[RetrievalComponentKind.EMBEDDING].configuration) == {
        "artifact_download_at_request_time": False,
        "credential_reference": "NONE",
        "destination": "NONE",
        "execution_mode": "DISABLED",
        "max_external_calls_per_request": 0,
        "max_gross_cost_microunits_per_request": 0,
        "model_id": "NONE",
        "model_revision": "NONE",
        "protected_content_authorized": False,
        "provider": "NONE",
        "provider_version": "NONE",
        "remote_code_allowed": False,
        "selection": "NONE",
    }
    vector = components[RetrievalComponentKind.VECTOR_INDEX]
    assert vector.disposition is ComponentDisposition.QUALIFICATION_ONLY
    assert vector.configuration["input_vector_source"] == (
        "DETERMINISTIC_FIXED_POINT_FIXTURE"
    )
    assert vector.configuration["dimensions"] == 1024
    assert vector.configuration["embedding_execution_allowed"] is False
    assert vector.configuration["production_activation_allowed"] is False

    assert all(
        component.disposition is ComponentDisposition.BOUND_FOR_IMPLEMENTATION
        for kind, component in components.items()
        if kind
        not in {
            RetrievalComponentKind.EMBEDDING,
            RetrievalComponentKind.VECTOR_INDEX,
        }
    )


def test_hybrid_contract_keeps_ranking_advisory_and_hydration_authoritative() -> None:
    components = INCREMENT_5A_CONTRACT.component_by_kind
    fusion = components[RetrievalComponentKind.FUSION].configuration
    hydration = components[RetrievalComponentKind.HYDRATION].configuration
    degraded = components[RetrievalComponentKind.DEGRADED_POLICY].configuration
    authority = INCREMENT_5A_CONTRACT.payload["authority_boundaries"]

    assert fusion["algorithm"] == "RECIPROCAL_RANK_FUSION"
    assert fusion["reciprocal_rank_k"] == 60
    assert fusion["score_representation"] == "REDUCED_RATIONAL"
    assert fusion["fusion_is_authority"] is False
    assert fusion["raw_score_comparability_assumed"] is False
    assert hydration["authority"] == "sqlite-ledger-and-governed-objects"
    assert hydration["projection_text_factual_use_allowed"] is False
    assert hydration["rights_recheck_at_read"] is True
    assert degraded["graph_free_fallback"] is False
    assert degraded["silent_mode_fallback"] is False
    assert degraded["no_match_requires_complete_retrieval"] is True
    assert authority == {
        "candidate_collision_system": "sqlite-authoritative-exact-collision",
        "hydration_system": "sqlite-ledger-and-governed-objects",
        "model_is_authority": False,
        "path_is_authority": False,
        "projection_role": "rebuildable-generation-scoped-context",
        "rank_is_authority": False,
        "similarity_is_authority": False,
    }


def test_zero_effect_budgets_and_change_control_are_exact() -> None:
    assert INCREMENT_5A_CONTRACT.payload["budgets"] == {
        "branch_result_limit": 8,
        "max_external_calls_per_request": 0,
        "max_gross_cost_microunits_per_request": 0,
        "response_byte_limit": 262_144,
        "retained_candidate_limit": 12,
        "timeout_ms": 5_000,
    }
    assert INCREMENT_5A_CONTRACT.payload["change_control"] == {
        "approval_authority": "REVIEWED_MERGE_TO_MAIN",
        "digests_are_content_identity_not_authorization": True,
        "material_change_requires_new_contract_version": True,
        "post_merge_materialisation_required": False,
        "runtime_github_api_required": False,
        "runtime_source_closure_attestation_required": False,
    }
    assert "PRODUCTION_ACTIVATION" in INCREMENT_5A_CONTRACT.payload["non_effects"]
    assert "PROVIDER_SPENDING" in INCREMENT_5A_CONTRACT.payload["non_effects"]


def test_contract_file_is_canonical_and_duplicate_names_fail_closed(
    tmp_path: Path,
) -> None:
    raw = CONTRACT_PATH.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    assert raw == canonical_json_bytes(value)

    pretty = tmp_path / "pretty.json"
    pretty.write_text(json.dumps(value, indent=2), encoding="utf-8")
    with pytest.raises(Increment5ContractError, match="exact canonical JSON"):
        load_increment5a_contract(pretty)

    duplicated = raw.decode("utf-8").replace(
        '"schema_version":"newsroom.increment5a.retrieval-contract.v1"',
        '"schema_version":"newsroom.increment5a.retrieval-contract.v1",'
        '"schema_version":"newsroom.increment5a.retrieval-contract.v1"',
        1,
    )
    duplicate_path = tmp_path / "duplicate.json"
    duplicate_path.write_text(duplicated, encoding="utf-8")
    with pytest.raises(Increment5ContractError, match="duplicate object name"):
        load_increment5a_contract(duplicate_path)


def test_recomputed_record_digests_cannot_enable_production_or_embedding(
    tmp_path: Path,
) -> None:
    record = _record()
    payload = record["payload"]
    assert isinstance(payload, dict)
    payload["production_activation_authorized"] = True
    with pytest.raises(Increment5ContractError, match="cannot activate production"):
        load_increment5a_contract(_write(tmp_path, record, "production.json"))

    record = _record()
    embedding = _component(record, "EMBEDDING")
    embedding["disposition"] = "BOUND_FOR_IMPLEMENTATION"
    configuration = embedding["configuration"]
    assert isinstance(configuration, dict)
    configuration.update(
        {
            "selection": "UNREVIEWED_MODEL",
            "execution_mode": "ENABLED",
            "provider": "unreviewed-provider",
            "model_id": "unreviewed-model",
            "destination": "EXTERNAL_API",
            "max_external_calls_per_request": 1,
            "max_gross_cost_microunits_per_request": 1,
            "protected_content_authorized": True,
        }
    )
    with pytest.raises(Increment5ContractError, match="component digest identities"):
        load_increment5a_contract(_write(tmp_path, record, "embedding.json"))


def test_recomputed_record_digests_cannot_enable_generated_queries_or_silent_fallback(
    tmp_path: Path,
) -> None:
    record = _record()
    graph = _component(record, "GRAPH_QUERY")
    configuration = graph["configuration"]
    assert isinstance(configuration, dict)
    configuration["generated_cypher_allowed"] = True
    with pytest.raises(Increment5ContractError, match="component digest identities"):
        load_increment5a_contract(_write(tmp_path, record, "graph.json"))

    record = _record()
    degraded = _component(record, "DEGRADED_POLICY")
    configuration = degraded["configuration"]
    assert isinstance(configuration, dict)
    configuration["silent_mode_fallback"] = True
    with pytest.raises(Increment5ContractError, match="component digest identities"):
        load_increment5a_contract(_write(tmp_path, record, "fallback.json"))


def test_thresholds_are_frozen_and_calibration_cannot_qualify() -> None:
    plan = INCREMENT_5A_CONTRACT.payload["evaluation_plan"]
    assert plan["thresholds_frozen_before_qualification"] is True
    assert plan["calibration_and_qualification_disjoint"] is True
    assert plan["embedding_quality_qualification_blocked"] is True
    assert plan["thresholds"] == {
        "aggregate_mrr_at_12_min_ppm": 750_000,
        "aggregate_recall_at_12_min_ppm": 900_000,
        "exact_identifier_precision_at_1_ppm": 1_000_000,
        "false_no_match_count": 0,
        "p95_latency_ms_max": 5_000,
        "provenance_completeness_ppm": 1_000_000,
        "required_slice_recall_at_12_min_ppm": 800_000,
        "rights_purge_residual_count": 0,
        "scope_escape_count": 0,
        "trust_label_completeness_ppm": 1_000_000,
        "write_attempt_success_count": 0,
    }


def test_contract_value_objects_are_immutable() -> None:
    with pytest.raises(TypeError):
        INCREMENT_5A_CONTRACT.payload["owner"] = "other"  # type: ignore[index]
    with pytest.raises(TypeError):
        INCREMENT_5A_CONTRACT.component_digests["EMBEDDING"] = "sha256:00"  # type: ignore[index]
