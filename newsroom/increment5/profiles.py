"""Safe profile manifests for Increment 5 fixture and system qualification.

The public profile API is compiled once from the exact checked repository
contract.  Runtime calls do not resolve a mutable loader or accept a contract
object, so a same-process caller cannot substitute unreviewed contract,
component, or schema identities while continuing to use these gates.

This is a deterministic source boundary, not a capability system: repository
review and merge decide which source revision is accepted, while this module
only validates manifests against the reviewed bytes in that revision.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable

from jsonschema import Draft202012Validator

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)

from .contract_types import Increment5ContractError, RetrievalProfileKind
from .decision import load_repository_contract as _load_repository_contract_once


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


def _compile_profile_api() -> tuple[
    Callable[..., dict[str, Any]],
    Callable[..., dict[str, Any]],
    Callable[[Mapping[str, Any]], ValidatedProfileManifest],
]:
    """Compile the reviewed contract and schemas into a closed validation kernel."""

    # Capture every authority-relevant dependency before exposing the public API.
    # Public calls below use only these closure values, never mutable module names.
    canonicalize = canonical_json_bytes
    calculate_digest = digest_bytes
    validate_digest_text = validate_sha256_digest
    loads_json = json.loads
    schema_validator_type = Draft202012Validator
    profile_type = RetrievalProfileKind
    error_type = Increment5ProfileError
    result_type = ValidatedProfileManifest
    mapping_type = Mapping
    mapping_proxy_type = MappingProxyType

    try:
        contract = _load_repository_contract_once()
    except Increment5ContractError as exc:
        raise error_type(str(exc)) from exc

    expected_schema_digests = dict(_PROFILE_SCHEMA_DIGESTS)
    if dict(contract.profile_schema_digests) != expected_schema_digests:
        raise error_type(
            "repository contract profile schema identities differ from reviewed v1"
        )

    contract_digest = contract.contract_digest
    contract_version = contract.contract_version
    approved_profiles = frozenset(contract.approved_profiles)
    component_digests = mapping_proxy_type(dict(contract.component_digests))
    payload_budgets = contract.payload["budgets"]
    if not isinstance(payload_budgets, mapping_type):
        raise error_type("accepted contract budgets are malformed")
    budgets = mapping_proxy_type(dict(payload_budgets))
    safe_runtime_effects = mapping_proxy_type(dict(_SAFE_RUNTIME_EFFECTS))

    def compile_schema(
        path: Path,
        expected_digest: str,
    ) -> Draft202012Validator:
        try:
            raw = path.read_bytes()
            value = loads_json(raw.decode("utf-8", errors="strict"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise error_type("cannot read profile schema") from exc
        try:
            if raw != canonicalize(value):
                raise error_type("profile schema is not canonical JSON")
            if calculate_digest(raw) != expected_digest:
                raise error_type("profile schema digest differs from v1")
        except CanonicalizationError as exc:
            raise error_type("profile schema is outside canonical JSON") from exc
        if not isinstance(value, mapping_type):
            raise error_type("profile schema must be an object")

        bound = deepcopy(dict(value))
        try:
            properties = bound["properties"]
            components = properties["components"]["properties"]
            if not isinstance(properties, dict) or not isinstance(components, dict):
                raise TypeError
            properties["contract_digest"] = {"const": contract_digest}
            for kind, identity_digest in component_digests.items():
                if kind not in components:
                    raise KeyError(kind)
                components[kind] = {"const": identity_digest}
        except (KeyError, TypeError) as exc:
            raise error_type(
                "profile schema cannot bind reviewed contract identities"
            ) from exc

        schema_validator_type.check_schema(bound)
        return schema_validator_type(bound)

    validators = mapping_proxy_type(
        {
            profile_type.FIXTURE_REPLAY: (
                compile_schema(
                    FIXTURE_REPLAY_PROFILE_SCHEMA_PATH,
                    FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST,
                ),
                FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST,
            ),
            profile_type.PRODUCTION_SHAPED_QUALIFICATION: (
                compile_schema(
                    QUALIFICATION_PROFILE_SCHEMA_PATH,
                    QUALIFICATION_PROFILE_SCHEMA_DIGEST,
                ),
                QUALIFICATION_PROFILE_SCHEMA_DIGEST,
            ),
        }
    )

    def require_profile(profile: RetrievalProfileKind) -> None:
        if not isinstance(profile, profile_type):
            raise error_type("retrieval profile must be typed")
        if profile not in approved_profiles:
            raise error_type(f"{profile.value} is not admitted by Increment 5A")

    def checked_digest(value: object, field: str) -> str:
        try:
            return validate_digest_text(value, field=field)  # type: ignore[arg-type]
        except (CanonicalizationError, ValueError, TypeError) as exc:
            raise error_type(f"{field} must be a canonical digest") from exc

    def freeze(value: Any) -> Any:
        if isinstance(value, mapping_type):
            return mapping_proxy_type({name: freeze(item) for name, item in value.items()})
        if isinstance(value, list):
            return tuple(freeze(item) for item in value)
        return value

    def base_manifest(profile: RetrievalProfileKind) -> dict[str, Any]:
        require_profile(profile)
        return {
            "profile_kind": profile.value,
            "contract_digest": contract_digest,
            "contract_version": contract_version,
            "components": dict(component_digests),
            "budgets": dict(budgets),
            "runtime_effects": dict(safe_runtime_effects),
            "vector_source": "DETERMINISTIC_FIXED_POINT_FIXTURE",
            "production_activation_authorized": False,
        }

    def validate_snapshot(
        snapshot: Mapping[str, Any],
        *,
        profile: RetrievalProfileKind,
    ) -> str:
        require_profile(profile)
        validator, profile_schema_digest = validators[profile]
        errors = sorted(
            validator.iter_errors(snapshot),
            key=lambda error: tuple(str(item) for item in error.absolute_path),
        )
        if errors:
            first = errors[0]
            location = ".".join(str(item) for item in first.absolute_path) or "$"
            raise error_type(
                f"profile schema validation failed at {location}: {first.message}"
            )

        if snapshot["contract_digest"] != contract_digest:
            raise error_type("profile contract digest differs")
        if snapshot["contract_version"] != contract_version:
            raise error_type("profile contract version differs")
        if dict(snapshot["components"]) != dict(component_digests):
            raise error_type("profile component identities differ")
        if dict(snapshot["budgets"]) != dict(budgets):
            raise error_type("profile budgets differ")
        if dict(snapshot["runtime_effects"]) != dict(safe_runtime_effects):
            raise error_type("profile attempts a prohibited runtime effect")
        if snapshot["production_activation_authorized"] is not False:
            raise error_type("Increment 5 profiles cannot activate production")
        return profile_schema_digest

    def build_fixture_replay_manifest(
        *,
        fixture_id: str,
        fixture_manifest_digest: str,
    ) -> dict[str, Any]:
        manifest = base_manifest(profile_type.FIXTURE_REPLAY)
        manifest.update(
            {
                "schema_version": "newsroom.increment5.fixture-replay-profile.v1",
                "fixture": {
                    "fixture_id": fixture_id,
                    "fixture_manifest_digest": checked_digest(
                        fixture_manifest_digest,
                        "fixture_manifest_digest",
                    ),
                    "production_substitution_allowed": False,
                },
                "qualification_eligible": False,
            }
        )
        validate_snapshot(manifest, profile=profile_type.FIXTURE_REPLAY)
        return manifest

    def build_qualification_manifest(
        *,
        dataset_id: str,
        dataset_manifest_digest: str,
    ) -> dict[str, Any]:
        manifest = base_manifest(profile_type.PRODUCTION_SHAPED_QUALIFICATION)
        manifest.update(
            {
                "schema_version": (
                    "newsroom.increment5.production-shaped-qualification-profile.v1"
                ),
                "dataset": {
                    "dataset_id": dataset_id,
                    "dataset_manifest_digest": checked_digest(
                        dataset_manifest_digest,
                        "dataset_manifest_digest",
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
        validate_snapshot(
            manifest,
            profile=profile_type.PRODUCTION_SHAPED_QUALIFICATION,
        )
        return manifest

    def validate_profile_manifest(
        manifest: Mapping[str, Any],
    ) -> ValidatedProfileManifest:
        if not isinstance(manifest, mapping_type):
            raise error_type("profile manifest must be an object")
        try:
            snapshot = loads_json(canonicalize(manifest).decode("utf-8"))
        except (CanonicalizationError, UnicodeError, json.JSONDecodeError) as exc:
            raise error_type("profile manifest is outside canonical JSON") from exc
        if not isinstance(snapshot, dict):
            raise error_type("profile manifest must be an object")
        try:
            profile = profile_type(snapshot.get("profile_kind"))
        except (TypeError, ValueError) as exc:
            raise error_type("profile kind is unsupported") from exc

        profile_schema_digest = validate_snapshot(snapshot, profile=profile)
        return result_type(
            profile_kind=profile,
            profile_schema_digest=profile_schema_digest,
            contract_digest=contract_digest,
            qualification_eligible=bool(snapshot["qualification_eligible"]),
            production_activation_authorized=False,
            manifest=freeze(snapshot),
        )

    return (
        build_fixture_replay_manifest,
        build_qualification_manifest,
        validate_profile_manifest,
    )


(
    build_fixture_replay_manifest,
    build_qualification_manifest,
    validate_profile_manifest,
) = _compile_profile_api()

# The loader and compiler are intentionally absent from the runtime module
# namespace.  The public functions retain only the reviewed immutable values and
# precompiled validators in their closures.
del _compile_profile_api
del _load_repository_contract_once
