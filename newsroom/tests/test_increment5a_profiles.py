from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import inspect
import json
from types import MappingProxyType
from typing import Callable

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
import newsroom.increment5 as increment5
from newsroom.increment5 import (
    FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST,
    FIXTURE_REPLAY_PROFILE_SCHEMA_PATH,
    FIXTURE_REPLAY_PROFILE_STRUCTURAL_SCHEMA_DIGEST,
    FIXTURE_REPLAY_PROFILE_STRUCTURAL_SCHEMA_PATH,
    INCREMENT_5A_CONTRACT,
    QUALIFICATION_PROFILE_SCHEMA_DIGEST,
    QUALIFICATION_PROFILE_SCHEMA_PATH,
    QUALIFICATION_PROFILE_STRUCTURAL_SCHEMA_DIGEST,
    QUALIFICATION_PROFILE_STRUCTURAL_SCHEMA_PATH,
    Increment5ProfileError,
    RetrievalProfileKind,
    build_fixture_replay_manifest,
    build_qualification_manifest,
)
from newsroom.increment5 import profiles
import newsroom.increment5.decision as decision


_DIGEST_A = "sha256:" + "a" * 64
_DIGEST_B = "sha256:" + "b" * 64


def _schema(path: object) -> dict[str, object]:
    raw = path.read_bytes()  # type: ignore[union-attr]
    value = json.loads(raw.decode("utf-8"))
    assert isinstance(value, dict)
    return value


def test_profile_schemas_are_canonical_and_digest_bound() -> None:
    for path, expected in (
        (
            FIXTURE_REPLAY_PROFILE_STRUCTURAL_SCHEMA_PATH,
            FIXTURE_REPLAY_PROFILE_STRUCTURAL_SCHEMA_DIGEST,
        ),
        (
            QUALIFICATION_PROFILE_STRUCTURAL_SCHEMA_PATH,
            QUALIFICATION_PROFILE_STRUCTURAL_SCHEMA_DIGEST,
        ),
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

    assert dict(INCREMENT_5A_CONTRACT.profile_schema_digests) == {
        RetrievalProfileKind.FIXTURE_REPLAY.value: (
            FIXTURE_REPLAY_PROFILE_STRUCTURAL_SCHEMA_DIGEST
        ),
        RetrievalProfileKind.PRODUCTION_SHAPED_QUALIFICATION.value: (
            QUALIFICATION_PROFILE_STRUCTURAL_SCHEMA_DIGEST
        ),
    }
    assert FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST not in (
        INCREMENT_5A_CONTRACT.profile_schema_digests.values()
    )
    assert QUALIFICATION_PROFILE_SCHEMA_DIGEST not in (
        INCREMENT_5A_CONTRACT.profile_schema_digests.values()
    )


@pytest.mark.parametrize(
    (
        "binding_path",
        "binding_id",
        "structural_path",
        "structural_digest",
    ),
    (
        (
            FIXTURE_REPLAY_PROFILE_SCHEMA_PATH,
            "urn:newsroom:increment5:fixture-replay-profile:reviewed-binding:v1",
            FIXTURE_REPLAY_PROFILE_STRUCTURAL_SCHEMA_PATH,
            FIXTURE_REPLAY_PROFILE_STRUCTURAL_SCHEMA_DIGEST,
        ),
        (
            QUALIFICATION_PROFILE_SCHEMA_PATH,
            (
                "urn:newsroom:increment5:production-shaped-qualification-profile:"
                "reviewed-binding:v1"
            ),
            QUALIFICATION_PROFILE_STRUCTURAL_SCHEMA_PATH,
            QUALIFICATION_PROFILE_STRUCTURAL_SCHEMA_DIGEST,
        ),
    ),
)
def test_reviewed_binding_schema_is_exact_non_circular_derivation(
    binding_path: object,
    binding_id: str,
    structural_path: object,
    structural_digest: str,
) -> None:
    binding = _schema(binding_path)
    structural = _schema(structural_path)
    assert digest_bytes(canonical_json_bytes(structural)) == structural_digest

    expected = deepcopy(structural)
    expected["$id"] = binding_id
    expected["title"] = f"{structural['title']} — reviewed identity binding"
    properties = expected["properties"]
    assert isinstance(properties, dict)
    properties["contract_digest"] = {
        "const": INCREMENT_5A_CONTRACT.contract_digest
    }
    components = properties["components"]
    assert isinstance(components, dict)
    component_properties = components["properties"]
    assert isinstance(component_properties, dict)
    component_properties.update(
        {
            kind: {"const": identity}
            for kind, identity in INCREMENT_5A_CONTRACT.component_digests.items()
        }
    )

    assert binding == expected


@pytest.mark.parametrize(
    ("builder", "binding_path"),
    (
        (
            lambda: build_fixture_replay_manifest(
                fixture_id="integrated-fixture-v3",
                fixture_manifest_digest=_DIGEST_A,
            ),
            FIXTURE_REPLAY_PROFILE_SCHEMA_PATH,
        ),
        (
            lambda: build_qualification_manifest(
                dataset_id="increment5-rights-cleared-v1",
                dataset_manifest_digest=_DIGEST_A,
            ),
            QUALIFICATION_PROFILE_SCHEMA_PATH,
        ),
    ),
)
def test_exported_schemas_reject_unreviewed_identities_without_python_overlay(
    builder: Callable[[], dict[str, object]],
    binding_path: object,
) -> None:
    validator = Draft202012Validator(_schema(binding_path))
    manifest = builder()
    validator.validate(manifest)

    tampered = deepcopy(manifest)
    tampered["contract_digest"] = _DIGEST_B
    with pytest.raises(ValidationError):
        validator.validate(tampered)

    tampered = deepcopy(manifest)
    components = tampered["components"]
    assert isinstance(components, dict)
    components["EMBEDDING"] = _DIGEST_B
    with pytest.raises(ValidationError):
        validator.validate(tampered)


def test_public_profile_api_exposes_no_in_process_authority_certificate() -> None:
    assert not hasattr(increment5, "ValidatedProfileManifest")
    assert not hasattr(increment5, "validate_profile_manifest")
    assert "ValidatedProfileManifest" not in increment5.__all__
    assert "validate_profile_manifest" not in increment5.__all__

    assert "_check_profile_manifest" in profiles.__dict__
    assert inspect.signature(profiles._check_profile_manifest).return_annotation in {
        None,
        "None",
    }


def test_profile_builders_have_no_caller_supplied_contract_authority() -> None:
    for function in (
        build_fixture_replay_manifest,
        build_qualification_manifest,
    ):
        assert "contract" not in inspect.signature(function).parameters

    unreviewed = replace(INCREMENT_5A_CONTRACT, contract_digest=_DIGEST_B)
    with pytest.raises(TypeError, match="unexpected keyword argument 'contract'"):
        build_fixture_replay_manifest(  # type: ignore[call-arg]
            contract=unreviewed,
            fixture_id="integrated-fixture-v3",
            fixture_manifest_digest=_DIGEST_A,
        )


def test_profile_kernel_captures_exact_repository_contract_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_components = dict(INCREMENT_5A_CONTRACT.component_digests)
    fake_components["EMBEDDING"] = _DIGEST_B
    unreviewed = replace(
        INCREMENT_5A_CONTRACT,
        contract_digest=_DIGEST_B,
        component_digests=MappingProxyType(fake_components),
    )

    assert "load_repository_contract" not in profiles.__dict__
    assert "_load_repository_contract_once" not in profiles.__dict__

    # Replacing either the source module or adding the old public seam after
    # import cannot alter the already compiled builder functions.
    monkeypatch.setattr(decision, "load_repository_contract", lambda: unreviewed)
    monkeypatch.setattr(
        profiles,
        "load_repository_contract",
        lambda: unreviewed,
        raising=False,
    )

    manifest = build_fixture_replay_manifest(
        fixture_id="integrated-fixture-v3",
        fixture_manifest_digest=_DIGEST_A,
    )
    assert profiles._check_profile_manifest(manifest) is None

    assert manifest["contract_digest"] == INCREMENT_5A_CONTRACT.contract_digest
    assert manifest["components"] == dict(INCREMENT_5A_CONTRACT.component_digests)


def test_fixture_replay_profile_is_hermetic_and_never_qualification_evidence() -> None:
    manifest = build_fixture_replay_manifest(
        fixture_id="integrated-fixture-v3",
        fixture_manifest_digest=_DIGEST_A,
    )

    assert profiles._check_profile_manifest(manifest) is None
    assert manifest["profile_kind"] == RetrievalProfileKind.FIXTURE_REPLAY.value
    assert manifest["qualification_eligible"] is False
    assert manifest["production_activation_authorized"] is False
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
    fixture = manifest["fixture"]
    assert isinstance(fixture, dict)
    assert fixture["production_substitution_allowed"] is False


def test_production_shaped_qualification_is_actual_service_but_not_production() -> None:
    manifest = build_qualification_manifest(
        dataset_id="increment5-rights-cleared-v1",
        dataset_manifest_digest=_DIGEST_B,
    )

    assert profiles._check_profile_manifest(manifest) is None
    assert manifest["profile_kind"] == (
        RetrievalProfileKind.PRODUCTION_SHAPED_QUALIFICATION.value
    )
    assert manifest["qualification_eligible"] is True
    assert manifest["production_activation_authorized"] is False
    assert manifest["actual_neo4j_required"] is True
    assert manifest["signed_dataset_manifest_required"] is True
    assert manifest["embedding_quality_qualified"] is False
    assert manifest["vector_source"] == "DETERMINISTIC_FIXED_POINT_FIXTURE"
    assert manifest["expected_outcome_scope"] == (
        "RETRIEVER_INDEX_FUSION_DEDUPLICATION_HYDRATION_DEGRADATION_AND_RECOVERY_ONLY"
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
def test_private_profile_check_rejects_runtime_effect(
    path: tuple[str, ...],
    value: object,
) -> None:
    manifest = build_qualification_manifest(
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
        profiles._check_profile_manifest(manifest)


def test_profile_contract_and_component_identity_are_exact_schema_constants() -> None:
    manifest = build_fixture_replay_manifest(
        fixture_id="integrated-fixture-v3",
        fixture_manifest_digest=_DIGEST_A,
    )

    tampered = deepcopy(manifest)
    tampered["contract_digest"] = _DIGEST_B
    with pytest.raises(Increment5ProfileError, match="schema validation failed"):
        profiles._check_profile_manifest(tampered)

    tampered = deepcopy(manifest)
    components = tampered["components"]
    assert isinstance(components, dict)
    components["EMBEDDING"] = _DIGEST_B
    with pytest.raises(Increment5ProfileError, match="schema validation failed"):
        profiles._check_profile_manifest(tampered)


def test_unknown_or_extra_profile_fields_fail_closed() -> None:
    manifest = build_fixture_replay_manifest(
        fixture_id="integrated-fixture-v3",
        fixture_manifest_digest=_DIGEST_A,
    )
    manifest["implicit_authority"] = True
    with pytest.raises(Increment5ProfileError, match="schema validation failed"):
        profiles._check_profile_manifest(manifest)

    manifest = build_fixture_replay_manifest(
        fixture_id="integrated-fixture-v3",
        fixture_manifest_digest=_DIGEST_A,
    )
    manifest["profile_kind"] = "PRODUCTION_ACTIVE"
    with pytest.raises(Increment5ProfileError, match="profile kind is unsupported"):
        profiles._check_profile_manifest(manifest)

def test_qualification_scope_is_complete_and_cannot_shrink() -> None:
    expected = "RETRIEVER_INDEX_FUSION_DEDUPLICATION_HYDRATION_DEGRADATION_AND_RECOVERY_ONLY"
    structural = _schema(QUALIFICATION_PROFILE_STRUCTURAL_SCHEMA_PATH)
    public = _schema(QUALIFICATION_PROFILE_SCHEMA_PATH)
    assert structural["properties"]["expected_outcome_scope"] == {"const": expected}
    assert public["properties"]["expected_outcome_scope"] == {"const": expected}

    manifest = build_qualification_manifest(
        dataset_id="increment5-rights-cleared-v1",
        dataset_manifest_digest=_DIGEST_A,
    )
    assert manifest["expected_outcome_scope"] == expected
    assert all(
        surface in expected
        for surface in (
            "FUSION",
            "DEDUPLICATION",
            "HYDRATION",
            "DEGRADATION",
            "RECOVERY",
        )
    )

    narrowed = deepcopy(manifest)
    narrowed["expected_outcome_scope"] = "RETRIEVER_INDEX_HYDRATION_AND_DEGRADATION_ONLY"
    with pytest.raises(Increment5ProfileError, match="schema validation failed"):
        profiles._check_profile_manifest(narrowed)
