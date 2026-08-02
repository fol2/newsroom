"""Safe profile manifests for Increment 5 fixture and system qualification.

Profile construction and validation bind only to the exact checked repository
contract. They do not activate a runtime lane, authenticate a GitHub event, or
mint any capability.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

from jsonschema import Draft202012Validator

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)

from .contract_types import (
    Increment5AContract,
    Increment5ContractError,
    RetrievalProfileKind,
)
from .decision import load_repository_contract


class Increment5ProfileError(ValueError):
    """A profile manifest is malformed or incompatible with Increment 5A."""


_DATA_DIR = Path(__file__).resolve().parent / "data"
FIXTURE_REPLAY_PROFILE_SCHEMA_PATH = (
    _DATA_DIR / "increment5_fixture_replay_profile_v1.schema.json"
)
QUALIFICATION_PROFILE_SCHEMA_PATH = (
    _DATA_DIR / "increment5_qualification_profile_v1.schema.json"
)
FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST = (
    "sha256:7c2e50d952109d834d944c120b8f9a5adcc59c6f39106430fa8728c5ad25c9a0"
)
QUALIFICATION_PROFILE_SCHEMA_DIGEST = (
    "sha256:9a79627dbc6814ac132caecde5c6253d20bd10778eeac8f008612eaafd6ae786"
)
_PROFILE_SCHEMA_DIGESTS = {
    RetrievalProfileKind.FIXTURE_REPLAY.value: FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST,
    RetrievalProfileKind.PRODUCTION_SHAPED_QUALIFICATION.value: (
        QUALIFICATION_PROFILE_SCHEMA_DIGEST
    ),
}
_SAFE_RUNTIME_EFFECTS = {
    "external_calls": 0,
    "live_sources": False,
    "model_load": False,
    "protected_content": False,
    "provider_credentials": False,
    "provider_spend_microunits": 0,
    "public_effect": False,
    "write_authority": False,
}


@dataclass(frozen=True, slots=True)
class ValidatedProfileManifest:
    profile_kind: RetrievalProfileKind
    profile_schema_digest: str
    contract_digest: str
    qualification_eligible: bool
    production_activation_authorized: bool
    manifest: Mapping[str, Any]


def _schema_for(profile: RetrievalProfileKind) -> tuple[Path, str]:
    if profile is RetrievalProfileKind.FIXTURE_REPLAY:
        return (
            FIXTURE_REPLAY_PROFILE_SCHEMA_PATH,
            FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST,
        )
    return QUALIFICATION_PROFILE_SCHEMA_PATH, QUALIFICATION_PROFILE_SCHEMA_DIGEST


def _repository_contract(profile: RetrievalProfileKind) -> Increment5AContract:
    """Resolve the only contract that a profile may attest to."""

    try:
        contract = load_repository_contract()
        contract.require_profile(profile)
    except Increment5ContractError as exc:
        raise Increment5ProfileError(str(exc)) from exc
    if dict(contract.profile_schema_digests) != _PROFILE_SCHEMA_DIGESTS:
        raise Increment5ProfileError(
            "repository contract profile schema identities differ from reviewed v1"
        )
    return contract


def _load_schema(path: Path, expected_digest: str) -> Mapping[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Increment5ProfileError("cannot read profile schema") from exc
    try:
        if raw != canonical_json_bytes(value):
            raise Increment5ProfileError("profile schema is not canonical JSON")
        if digest_bytes(raw) != expected_digest:
            raise Increment5ProfileError("profile schema digest differs from v1")
    except CanonicalizationError as exc:
        raise Increment5ProfileError("profile schema is outside canonical JSON") from exc
    if not isinstance(value, Mapping):
        raise Increment5ProfileError("profile schema must be an object")
    Draft202012Validator.check_schema(value)
    return value


def _bind_reviewed_identity(
    schema: Mapping[str, Any],
    contract: Increment5AContract,
) -> Mapping[str, Any]:
    """Bind the structural schema to exact reviewed contract identities.

    The checked schema files remain content-addressed structural artefacts. The
    validation gate overlays exact constants from the checked repository contract,
    avoiding a circular schema-digest/contract-digest dependency while rejecting
    every unreviewed contract or component identity.
    """

    bound = deepcopy(dict(schema))
    try:
        properties = bound["properties"]
        components = properties["components"]["properties"]
        if not isinstance(properties, dict) or not isinstance(components, dict):
            raise TypeError
        properties["contract_digest"] = {"const": contract.contract_digest}
        for kind, identity_digest in contract.component_digests.items():
            if kind not in components:
                raise KeyError(kind)
            components[kind] = {"const": identity_digest}
    except (KeyError, TypeError) as exc:
        raise Increment5ProfileError(
            "profile schema cannot bind reviewed contract identities"
        ) from exc
    Draft202012Validator.check_schema(bound)
    return bound


def _validate_digest(value: object, field: str) -> str:
    try:
        return validate_sha256_digest(value, field=field)  # type: ignore[arg-type]
    except (CanonicalizationError, ValueError, TypeError) as exc:
        raise Increment5ProfileError(f"{field} must be a canonical digest") from exc


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({name: _freeze(item) for name, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _base_manifest(
    profile: RetrievalProfileKind,
) -> tuple[Increment5AContract, dict[str, Any]]:
    contract = _repository_contract(profile)
    payload_budgets = contract.payload["budgets"]
    if not isinstance(payload_budgets, Mapping):
        raise Increment5ProfileError("accepted contract budgets are malformed")
    return contract, {
        "profile_kind": profile.value,
        "contract_digest": contract.contract_digest,
        "contract_version": contract.contract_version,
        "components": dict(contract.component_digests),
        "budgets": dict(payload_budgets),
        "runtime_effects": dict(_SAFE_RUNTIME_EFFECTS),
        "vector_source": "DETERMINISTIC_FIXED_POINT_FIXTURE",
        "production_activation_authorized": False,
    }


def _validate_snapshot(
    snapshot: Mapping[str, Any],
    *,
    profile: RetrievalProfileKind,
    contract: Increment5AContract,
) -> str:
    schema_path, expected_schema_digest = _schema_for(profile)
    structural_schema = _load_schema(schema_path, expected_schema_digest)
    bound_schema = _bind_reviewed_identity(structural_schema, contract)
    errors = sorted(
        Draft202012Validator(bound_schema).iter_errors(snapshot),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(item) for item in first.absolute_path) or "$"
        raise Increment5ProfileError(
            f"profile schema validation failed at {location}: {first.message}"
        )

    if snapshot["contract_digest"] != contract.contract_digest:
        raise Increment5ProfileError("profile contract digest differs")
    if snapshot["contract_version"] != contract.contract_version:
        raise Increment5ProfileError("profile contract version differs")
    if dict(snapshot["components"]) != dict(contract.component_digests):
        raise Increment5ProfileError("profile component identities differ")
    if dict(snapshot["budgets"]) != dict(contract.payload["budgets"]):
        raise Increment5ProfileError("profile budgets differ")
    if dict(snapshot["runtime_effects"]) != _SAFE_RUNTIME_EFFECTS:
        raise Increment5ProfileError("profile attempts a prohibited runtime effect")
    if snapshot["production_activation_authorized"] is not False:
        raise Increment5ProfileError("Increment 5 profiles cannot activate production")
    return expected_schema_digest


def build_fixture_replay_manifest(
    *,
    fixture_id: str,
    fixture_manifest_digest: str,
) -> dict[str, Any]:
    contract, manifest = _base_manifest(RetrievalProfileKind.FIXTURE_REPLAY)
    manifest.update(
        {
            "schema_version": "newsroom.increment5.fixture-replay-profile.v1",
            "fixture": {
                "fixture_id": fixture_id,
                "fixture_manifest_digest": _validate_digest(
                    fixture_manifest_digest, "fixture_manifest_digest"
                ),
                "production_substitution_allowed": False,
            },
            "qualification_eligible": False,
        }
    )
    _validate_snapshot(
        manifest,
        profile=RetrievalProfileKind.FIXTURE_REPLAY,
        contract=contract,
    )
    return manifest


def build_qualification_manifest(
    *,
    dataset_id: str,
    dataset_manifest_digest: str,
) -> dict[str, Any]:
    contract, manifest = _base_manifest(
        RetrievalProfileKind.PRODUCTION_SHAPED_QUALIFICATION
    )
    manifest.update(
        {
            "schema_version": (
                "newsroom.increment5.production-shaped-qualification-profile.v1"
            ),
            "dataset": {
                "dataset_id": dataset_id,
                "dataset_manifest_digest": _validate_digest(
                    dataset_manifest_digest, "dataset_manifest_digest"
                ),
                "rights_cleared": True,
                "repository_safe": True,
                "contains_protected_content": False,
            },
            "actual_neo4j_required": True,
            "signed_dataset_manifest_required": True,
            "qualification_eligible": True,
            "embedding_quality_qualified": False,
            "expected_outcome_scope": (
                "RETRIEVER_INDEX_HYDRATION_AND_DEGRADATION_ONLY"
            ),
        }
    )
    _validate_snapshot(
        manifest,
        profile=RetrievalProfileKind.PRODUCTION_SHAPED_QUALIFICATION,
        contract=contract,
    )
    return manifest


def validate_profile_manifest(
    manifest: Mapping[str, Any],
) -> ValidatedProfileManifest:
    if not isinstance(manifest, Mapping):
        raise Increment5ProfileError("profile manifest must be an object")
    try:
        snapshot = json.loads(canonical_json_bytes(manifest).decode("utf-8"))
    except (CanonicalizationError, UnicodeError, json.JSONDecodeError) as exc:
        raise Increment5ProfileError("profile manifest is outside canonical JSON") from exc
    if not isinstance(snapshot, dict):
        raise Increment5ProfileError("profile manifest must be an object")
    try:
        profile = RetrievalProfileKind(snapshot.get("profile_kind"))
    except (TypeError, ValueError) as exc:
        raise Increment5ProfileError("profile kind is unsupported") from exc

    contract = _repository_contract(profile)
    profile_schema_digest = _validate_snapshot(
        snapshot,
        profile=profile,
        contract=contract,
    )
    return ValidatedProfileManifest(
        profile_kind=profile,
        profile_schema_digest=profile_schema_digest,
        contract_digest=contract.contract_digest,
        qualification_eligible=bool(snapshot["qualification_eligible"]),
        production_activation_authorized=False,
        manifest=_freeze(snapshot),
    )
