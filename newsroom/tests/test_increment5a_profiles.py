from __future__ import annotations

from copy import deepcopy
import json

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment5 import (
    FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST,
    FIXTURE_REPLAY_PROFILE_SCHEMA_PATH,
    INCREMENT_5A_CONTRACT,
    QUALIFICATION_PROFILE_SCHEMA_DIGEST,
    QUALIFICATION_PROFILE_SCHEMA_PATH,
    Increment5ProfileError,
    RetrievalProfileKind,
    build_fixture_replay_manifest,
    build_qualification_manifest,
    validate_profile_manifest,
)


_DIGEST_A = "sha256:" + "a" * 64
_DIGEST_B = "sha256:" + "b" * 64


def test_profile_schemas_are_canonical_and_digest_bound() -> None:
    for path, expected in (
        (
            FIXTURE_REPLAY_PROFILE_SCHEMA_PATH,
            FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST,
        ),
        (
            QUALIFICATION_PROFILE_SCHEMA_PATH,
            QUALIFICATION_PROFILE_SCHEMA_DIGEST,
        ),
    ):
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
        assert raw == canonical_json_bytes(value)
        assert digest_bytes(raw) == expected


def test_fixture_replay_profile_is_hermetic_and_never_qualification_evidence() -> None:
    manifest = build_fixture_replay_manifest(
        contract=INCREMENT_5A_CONTRACT,
        fixture_id="integrated-fixture-v3",
        fixture_manifest_digest=_DIGEST_A,
    )
    validated = validate_profile_manifest(
        manifest,
        contract=INCREMENT_5A_CONTRACT,
    )

    assert validated.profile_kind is RetrievalProfileKind.FIXTURE_REPLAY
    assert validated.qualification_eligible is False
    assert validated.production_activation_authorized is False
    assert manifest["runtime_effects"] == {
        "external_calls": 0,
        "live_sources": False,
        "model_load": False,
        "protected_content": False,
        "provider_credentials": False,
        "provider_spend_microunits": 0,
        "public_effect": False,
        "write_authority": False,
    }
    assert manifest["fixture"]["production_substitution_allowed"] is False


def test_production_shaped_qualification_is_actual_service_but_not_production() -> None:
    manifest = build_qualification_manifest(
        contract=INCREMENT_5A_CONTRACT,
        dataset_id="increment5-rights-cleared-v1",
        dataset_manifest_digest=_DIGEST_B,
    )
    validated = validate_profile_manifest(
        manifest,
        contract=INCREMENT_5A_CONTRACT,
    )

    assert (
        validated.profile_kind
        is RetrievalProfileKind.PRODUCTION_SHAPED_QUALIFICATION
    )
    assert validated.qualification_eligible is True
    assert validated.production_activation_authorized is False
    assert manifest["actual_neo4j_required"] is True
    assert manifest["signed_dataset_manifest_required"] is True
    assert manifest["embedding_quality_qualified"] is False
    assert manifest["vector_source"] == "DETERMINISTIC_FIXED_POINT_FIXTURE"
    assert manifest["expected_outcome_scope"] == (
        "RETRIEVER_INDEX_HYDRATION_AND_DEGRADATION_ONLY"
    )


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("runtime_effects", "external_calls"), 1),
        (("runtime_effects", "model_load"), True),
        (("runtime_effects", "protected_content"), True),
        (("runtime_effects", "public_effect"), True),
        (("runtime_effects", "write_authority"), True),
        (("production_activation_authorized",), True),
    ),
)
def test_profile_cannot_gain_runtime_effect(
    path: tuple[str, ...],
    value: object,
) -> None:
    manifest = build_qualification_manifest(
        contract=INCREMENT_5A_CONTRACT,
        dataset_id="increment5-rights-cleared-v1",
        dataset_manifest_digest=_DIGEST_A,
    )
    target: dict[str, object] = manifest
    for name in path[:-1]:
        nested = target[name]
        assert isinstance(nested, dict)
        target = nested
    target[path[-1]] = value

    with pytest.raises(Increment5ProfileError, match="schema validation failed"):
        validate_profile_manifest(manifest, contract=INCREMENT_5A_CONTRACT)


def test_profile_contract_and_component_identity_must_match() -> None:
    manifest = build_fixture_replay_manifest(
        contract=INCREMENT_5A_CONTRACT,
        fixture_id="integrated-fixture-v3",
        fixture_manifest_digest=_DIGEST_A,
    )

    tampered = deepcopy(manifest)
    tampered["contract_digest"] = _DIGEST_B
    with pytest.raises(Increment5ProfileError, match="contract digest differs"):
        validate_profile_manifest(tampered, contract=INCREMENT_5A_CONTRACT)

    tampered = deepcopy(manifest)
    tampered["components"]["EMBEDDING"] = _DIGEST_B
    with pytest.raises(Increment5ProfileError, match="component identities differ"):
        validate_profile_manifest(tampered, contract=INCREMENT_5A_CONTRACT)


def test_unknown_or_extra_profile_fields_fail_closed() -> None:
    manifest = build_fixture_replay_manifest(
        contract=INCREMENT_5A_CONTRACT,
        fixture_id="integrated-fixture-v3",
        fixture_manifest_digest=_DIGEST_A,
    )
    manifest["implicit_authority"] = True
    with pytest.raises(Increment5ProfileError, match="schema validation failed"):
        validate_profile_manifest(manifest, contract=INCREMENT_5A_CONTRACT)

    manifest = build_fixture_replay_manifest(
        contract=INCREMENT_5A_CONTRACT,
        fixture_id="integrated-fixture-v3",
        fixture_manifest_digest=_DIGEST_A,
    )
    manifest["profile_kind"] = "PRODUCTION_ACTIVE"
    with pytest.raises(Increment5ProfileError, match="profile kind is unsupported"):
        validate_profile_manifest(manifest, contract=INCREMENT_5A_CONTRACT)
