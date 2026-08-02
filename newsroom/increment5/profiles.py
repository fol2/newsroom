"""Safe profile manifests for Increment 5 fixture and system qualification.

Profile validation proves conformance to the checked contract.  It does not activate a
runtime lane, authenticate a GitHub event, or mint any capability.
"""

from __future__ import annotations

from collections.abc import Mapping
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

from .contracts import (
    Increment5AContract,
    Increment5ContractError,
    RetrievalProfileKind,
)


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
    *,
    contract: Increment5AContract,
    profile: RetrievalProfileKind,
) -> dict[str, Any]:
    contract.require_profile(profile)
    payload_budgets = contract.payload["budgets"]
    if not isinstance(payload_budgets, Mapping):
        raise Increment5ProfileError("accepted contract budgets are malformed")
    return {
        "profile_kind": profile.value,
        "contract_digest": contract.contract_digest,
        "contract_version": contract.contract_version,
        "components": dict(contract.component_digests),
        "budgets": dict(payload_budgets),
        "runtime_effects": dict(_SAFE_RUNTIME_EFFECTS),
        "vector_source": "DETERMINISTIC_FIXED_POINT_FIXTURE",
        "production_activation_authorized": False,
    }


def build_fixture_replay_manifest(
    *,
    contract: Increment5AContract,
    fixture_id: str,
    fixture_manifest_digest: str,
) -> dict[str, Any]:
    manifest = _base_manifest(
        contract=contract,
        profile=RetrievalProfileKind.FIXTURE_REPLAY,
    )
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
    return manifest


def build_qualification_manifest(
    *,
    contract: Increment5AContract,
    dataset_id: str,
    dataset_manifest_digest: str,
) -> dict[str, Any]:
    manifest = _base_manifest(
        contract=contract,
        profile=RetrievalProfileKind.PRODUCTION_SHAPED_QUALIFICATION,
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
    return manifest


def validate_profile_manifest(
    manifest: Mapping[str, Any],
    *,
    contract: Increment5AContract,
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
    try:
        contract.require_profile(profile)
    except Increment5ContractError as exc:
        raise Increment5ProfileError(str(exc)) from exc

    schema_path, expected_schema_digest = _schema_for(profile)
    schema = _load_schema(schema_path, expected_schema_digest)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(snapshot),
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

    return ValidatedProfileManifest(
        profile_kind=profile,
        contract_digest=contract.contract_digest,
        qualification_eligible=bool(manifest["qualification_eligible"]),
        production_activation_authorized=False,
        manifest=_freeze(snapshot),
    )
