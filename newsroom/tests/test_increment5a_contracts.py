from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment5 import (
    ComponentDisposition,
    DecisionPacketStatus,
    EmbeddingContractIdentity,
    FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST,
    FIXTURE_REPLAY_PROFILE_SCHEMA_PATH,
    INCREMENT_5A_DECISION_PACKET,
    Increment5ContractError,
    Increment5ProfileError,
    PRODUCTION_PROFILE_SCHEMA_DIGEST,
    PRODUCTION_PROFILE_SCHEMA_PATH,
    PROPOSAL_PRODUCTION_PROFILE_SCHEMA_DIGEST,
    PROPOSAL_PRODUCTION_PROFILE_SCHEMA_PATH,
    QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_DIGEST,
    QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_PATH,
    RetrievalComponentKind,
    RetrievalProfileKind,
    RuntimeAuthority,
    VectorIndexContractIdentity,
    build_fixture_replay_manifest,
    load_increment5a_decision_packet,
    validate_profile_manifest,
    PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST,
)
from newsroom.increment5.decision import DECISION_PACKET_PATH


def _decision_record() -> dict[str, object]:
    return json.loads(DECISION_PACKET_PATH.read_text(encoding="utf-8"))


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


def _write_record(tmp_path: Path, record: dict[str, object]) -> Path:
    path = tmp_path / "decision.json"
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


def test_pending_packet_is_exact_zero_spend_and_fixture_only() -> None:
    packet = INCREMENT_5A_DECISION_PACKET

    assert packet.status is DecisionPacketStatus.PENDING_OWNER_REVIEW
    assert packet.runtime_authority is RuntimeAuthority.CONTRACT_AND_FIXTURE_REPLAY_ONLY
    assert packet.approved_profiles == (RetrievalProfileKind.FIXTURE_REPLAY,)
    assert packet.blocked_profiles == (RetrievalProfileKind.PRODUCTION,)
    assert not packet.production_authorized
    assert packet.budgets.max_external_calls_per_request == 0
    assert packet.budgets.max_gross_cost_microunits_per_request == 0
    assert packet.payload_digest == (
        "sha256:4cc1de54a8d831358bbbe9b65c724d442401e84e3e72918df45807e140bdea56"
    )
    assert packet.record_digest == (
        "sha256:77fe5544b33a85519b8c1fba57f41fe1a68aa411eb63c64be5429dbbd28ea913"
    )
    assert packet.bundle.contract_digest == (
        "sha256:c0976abd6c2d450f242351f2cd94b2589cac5e6a03f1a2f98bfe1acbcbc4ea8c"
    )
    assert packet.bundle.production_profile_schema_digest == (
        PROPOSAL_PRODUCTION_PROFILE_SCHEMA_DIGEST
    )
    assert packet.bundle.fixture_replay_profile_schema_digest == (
        PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST
    )


def test_schema_artifacts_are_canonical_digest_bound_and_unambiguous() -> None:
    for path, expected_digest in (
        (
            PROPOSAL_PRODUCTION_PROFILE_SCHEMA_PATH,
            PROPOSAL_PRODUCTION_PROFILE_SCHEMA_DIGEST,
        ),
        (
            QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_PATH,
            QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_DIGEST,
        ),
        (FIXTURE_REPLAY_PROFILE_SCHEMA_PATH, FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST),
    ):
        data = path.read_bytes()
        value = json.loads(data.decode("utf-8"))
        assert data == canonical_json_bytes(value)
        assert digest_bytes(data) == expected_digest

    assert PRODUCTION_PROFILE_SCHEMA_PATH == (
        QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_PATH
    )
    assert PRODUCTION_PROFILE_SCHEMA_DIGEST == (
        QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_DIGEST
    )
    assert PRODUCTION_PROFILE_SCHEMA_PATH != (
        PROPOSAL_PRODUCTION_PROFILE_SCHEMA_PATH
    )
    assert PRODUCTION_PROFILE_SCHEMA_DIGEST != (
        PROPOSAL_PRODUCTION_PROFILE_SCHEMA_DIGEST
    )


def test_exact_self_hosted_embedding_proposal_is_local_and_still_disabled() -> None:
    record = _decision_record()
    embedding = _component(record, "EMBEDDING")
    configuration = embedding["configuration"]
    assert isinstance(configuration, dict)

    assert embedding["disposition"] == "DISABLED_PENDING_OWNER_DECISION"
    assert configuration == {
        "artifact_preload_required": True,
        "credential_reference": "NONE",
        "dense_only": True,
        "destination": "LOCAL_PROCESS_ONLY",
        "device_policy": "QUALIFICATION_PROFILE_EXACT",
        "dimensions": 1024,
        "execution_mode": "DISABLED_PENDING_OWNER_DECISION",
        "inference_precision": "FLOAT32",
        "max_external_calls_per_request": 0,
        "max_gross_cost_microunits_per_request": 0,
        "maximum_input_tokens": 8192,
        "model_artifact_source": "HUGGING_FACE_MODEL_REPOSITORY",
        "model_download_at_request_time": False,
        "model_id": "BAAI/bge-m3",
        "model_license": "MIT",
        "model_revision": "5617a9f61b028005a4858fdac845db406aefb181",
        "normalize_embeddings": True,
        "output_data_type": "FLOAT32",
        "pooling": "CLS",
        "protected_content_authorized": False,
        "provider": "sentence-transformers",
        "provider_kind": "SELF_HOSTED_LOCAL_MODEL",
        "provider_version": "5.6.0",
        "provider_wheel_sha256": (
            "d2075b5e687a1611005e20ab04a6846994d51adfcf39610aed066af3c0c0b81f"
        ),
        "remote_code_allowed": False,
    }

    payload = record["payload"]
    assert isinstance(payload, dict)
    rights = payload["rights_matrix"]
    assert isinstance(rights, list)
    rights_by_class = {
        row["data_class"]: row for row in rights if isinstance(row, dict)
    }
    assert (
        rights_by_class["RIGHTS_RESTRICTED_SOURCE_TEXT"]["vector_index"]
        == "PROHIBITED_IN_INCREMENT_5_V1"
    )
    assert rights_by_class["PERSONAL_DATA"]["vector_index"] == "PROHIBITED"
    assert (
        rights_by_class["REPOSITORY_FIXTURE_TEXT"]["production_qualification"]
        == "PROHIBITED"
    )


def test_component_inventory_is_typed_and_production_vector_lane_is_disabled() -> None:
    components = INCREMENT_5A_DECISION_PACKET.bundle.component_by_kind

    assert tuple(components) == tuple(RetrievalComponentKind)
    assert isinstance(
        components[RetrievalComponentKind.EMBEDDING],
        EmbeddingContractIdentity,
    )
    assert isinstance(
        components[RetrievalComponentKind.VECTOR_INDEX],
        VectorIndexContractIdentity,
    )
    assert (
        components[RetrievalComponentKind.EMBEDDING].disposition
        is ComponentDisposition.DISABLED_PENDING_OWNER_DECISION
    )
    assert (
        components[RetrievalComponentKind.VECTOR_INDEX].disposition
        is ComponentDisposition.BLOCKED_BY_DISABLED_DEPENDENCY
    )
    assert (
        components[RetrievalComponentKind.EMBEDDING].implementation_version
        == "sentence-transformers-5.6.0-bge-m3-dense-v1"
    )
    assert (
        components[RetrievalComponentKind.EMBEDDING].configuration_digest
        == "sha256:07f61889905f8278aca1e8ab9ad9a3b299b9441787d3c0fd7c647e286533ffbb"
    )
    assert all(
        component.compatibility_rule == "EXACT_DIGEST_ONLY"
        for component in components.values()
    )


def test_fixture_replay_manifest_validates_but_can_never_qualify() -> None:
    manifest = build_fixture_replay_manifest(
        packet=INCREMENT_5A_DECISION_PACKET,
        fixture_id="integrated-fixture-v2",
        fixture_manifest_digest=(
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        ),
    )

    validated = validate_profile_manifest(
        manifest,
        packet=INCREMENT_5A_DECISION_PACKET,
    )

    assert validated.profile is RetrievalProfileKind.FIXTURE_REPLAY
    assert validated.qualification_eligible is False
    assert manifest["fixture"]["production_substitution_allowed"] is False
    assert manifest["rights"]["protected_content_allowed"] is False
    assert manifest["budgets"]["max_external_calls_per_request"] == 0


def test_production_profile_is_mechanically_blocked_before_owner_decision() -> None:
    with pytest.raises(Increment5ProfileError, match="PRODUCTION is not authorized"):
        INCREMENT_5A_DECISION_PACKET.require_profile(
            RetrievalProfileKind.PRODUCTION
        )


def test_noncanonical_and_duplicate_json_are_rejected(tmp_path: Path) -> None:
    record = _decision_record()
    pretty = json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8")
    pretty_path = tmp_path / "pretty.json"
    pretty_path.write_bytes(pretty)
    with pytest.raises(Increment5ContractError, match="exact canonical JSON"):
        load_increment5a_decision_packet(pretty_path)

    raw = DECISION_PACKET_PATH.read_text(encoding="utf-8")
    duplicated = raw.replace(
        '"schema_version":"increment5a-decision-packet-v1"',
        '"schema_version":"increment5a-decision-packet-v1",'
        '"schema_version":"increment5a-decision-packet-v1"',
        1,
    )
    duplicate_path = tmp_path / "duplicate.json"
    duplicate_path.write_text(duplicated, encoding="utf-8")
    with pytest.raises(Increment5ContractError, match="duplicate object name"):
        load_increment5a_decision_packet(duplicate_path)


def test_unknown_payload_and_component_configuration_fields_fail_closed(
    tmp_path: Path,
) -> None:
    record = _decision_record()
    payload = record["payload"]
    assert isinstance(payload, dict)
    payload["implicit_runtime_authority"] = True
    with pytest.raises(Increment5ContractError, match="payload keys differ"):
        load_increment5a_decision_packet(_write_record(tmp_path, record))

    record = _decision_record()
    embedding = _component(record, "EMBEDDING")
    configuration = embedding["configuration"]
    assert isinstance(configuration, dict)
    configuration["allow_unreviewed_fallback"] = True
    with pytest.raises(
        Increment5ContractError,
        match="repository-bound pending proposal",
    ):
        load_increment5a_decision_packet(_write_record(tmp_path, record))


def test_boolean_integer_confusion_cannot_bypass_exact_contract(
    tmp_path: Path,
) -> None:
    record = _decision_record()
    payload = record["payload"]
    assert isinstance(payload, dict)
    budgets = payload["budgets"]
    assert isinstance(budgets, dict)
    budgets["max_external_calls_per_request"] = False
    with pytest.raises(Increment5ContractError):
        load_increment5a_decision_packet(_write_record(tmp_path, record))

    record = _decision_record()
    embedding = _component(record, "EMBEDDING")
    configuration = embedding["configuration"]
    assert isinstance(configuration, dict)
    configuration["dimensions"] = False
    with pytest.raises(
        Increment5ContractError,
        match="repository-bound pending proposal",
    ):
        load_increment5a_decision_packet(_write_record(tmp_path, record))


def test_recomputed_digests_do_not_authorize_real_embedding_or_vectors(
    tmp_path: Path,
) -> None:
    record = _decision_record()
    embedding = _component(record, "EMBEDDING")
    embedding["disposition"] = "BOUND_CONTRACT"
    configuration = embedding["configuration"]
    assert isinstance(configuration, dict)
    configuration.update(
        {
            "provider_kind": "EXTERNAL_API",
            "provider": "unapproved-provider",
            "model_id": "unapproved-model",
            "destination": "https://example.invalid",
            "execution_mode": "ENABLED",
            "dimensions": 1536,
            "output_data_type": "FLOAT32",
            "max_external_calls_per_request": 1,
            "max_gross_cost_microunits_per_request": 1000,
            "protected_content_authorized": True,
            "credential_reference": "secret/unapproved",
        }
    )
    with pytest.raises(
        Increment5ContractError,
        match="repository-bound pending proposal",
    ):
        load_increment5a_decision_packet(_write_record(tmp_path, record))

    record = _decision_record()
    vector = _component(record, "VECTOR_INDEX")
    vector["disposition"] = "BOUND_CONTRACT"
    configuration = vector["configuration"]
    assert isinstance(configuration, dict)
    configuration["dimensions"] = 1536
    configuration["index_creation_allowed"] = True
    with pytest.raises(
        Increment5ContractError,
        match="repository-bound pending proposal",
    ):
        load_increment5a_decision_packet(_write_record(tmp_path, record))


def test_graph_free_and_silent_fallback_cannot_be_introduced(tmp_path: Path) -> None:
    record = _decision_record()
    degraded = _component(record, "DEGRADED_POLICY")
    configuration = degraded["configuration"]
    assert isinstance(configuration, dict)
    configuration["graph_free_fallback"] = True
    with pytest.raises(
        Increment5ContractError,
        match="repository-bound pending proposal",
    ):
        load_increment5a_decision_packet(_write_record(tmp_path, record))

    record = _decision_record()
    degraded = _component(record, "DEGRADED_POLICY")
    configuration = degraded["configuration"]
    assert isinstance(configuration, dict)
    configuration["silent_mode_fallback"] = True
    with pytest.raises(
        Increment5ContractError,
        match="repository-bound pending proposal",
    ):
        load_increment5a_decision_packet(_write_record(tmp_path, record))


def test_fixture_profile_tampering_is_rejected() -> None:
    manifest = build_fixture_replay_manifest(
        packet=INCREMENT_5A_DECISION_PACKET,
        fixture_id="integrated-fixture-v2",
        fixture_manifest_digest=(
            "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        ),
    )

    tampered = deepcopy(manifest)
    tampered["qualification_eligible"] = True
    with pytest.raises(Increment5ProfileError, match="schema validation failed"):
        validate_profile_manifest(
            tampered,
            packet=INCREMENT_5A_DECISION_PACKET,
        )

    tampered = deepcopy(manifest)
    tampered["rights"]["protected_content_allowed"] = True
    with pytest.raises(
        Increment5ProfileError,
        match="schema validation failed",
    ):
        validate_profile_manifest(
            tampered,
            packet=INCREMENT_5A_DECISION_PACKET,
        )

    tampered = deepcopy(manifest)
    tampered["components"].pop("GRAPH_QUERY")
    with pytest.raises(Increment5ProfileError, match="schema validation failed"):
        validate_profile_manifest(
            tampered,
            packet=INCREMENT_5A_DECISION_PACKET,
        )
