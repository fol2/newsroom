"""Safe profile-manifest builders for Increment 5.

The public package exposes builders and reviewed schema paths, not an
in-process qualification certificate. Python code running in the same process
can mutate functions, globals, closures, and return objects; it is therefore not
an admissible security principal for qualification authority.

At import, this module reconstructs the exact reviewed-binding schemas from the
contract-owned structural schemas and exact repository contract. Builders use a
private deterministic checker as a convenience. Qualification evidence must
validate canonical manifest bytes in a fresh exact-head process through
``scripts/sdlc/increment5_profile_validator.py``; that process emits a
non-authoritative validation receipt only.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import json
from pathlib import Path
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

# Structural schemas are part of the contract identity. They intentionally use
# digest-shaped fields so the contract can identify their bytes without a
# self-referential digest cycle.
FIXTURE_REPLAY_PROFILE_STRUCTURAL_SCHEMA_PATH = (
    _DATA_DIR / "increment5_fixture_replay_profile_structural_v1.schema.json"
)
QUALIFICATION_PROFILE_STRUCTURAL_SCHEMA_PATH = (
    _DATA_DIR / "increment5_qualification_profile_structural_v1.schema.json"
)
FIXTURE_REPLAY_PROFILE_STRUCTURAL_SCHEMA_DIGEST = (
    "sha256:7c2e50d952109d834d944c120b8f9a5adcc59c6f39106430fa8728c5ad25c9a0"
)
QUALIFICATION_PROFILE_STRUCTURAL_SCHEMA_DIGEST = (
    "sha256:9a79627dbc6814ac132caecde5c6253d20bd10778eeac8f008612eaafd6ae786"
)

# Public schemas are self-contained reviewed bindings. Each is derived from
# its exact structural schema and fixes the reviewed contract plus every
# component identity with JSON-Schema ``const`` values.
FIXTURE_REPLAY_PROFILE_SCHEMA_PATH = (
    _DATA_DIR / "increment5_fixture_replay_profile_v1.schema.json"
)
QUALIFICATION_PROFILE_SCHEMA_PATH = (
    _DATA_DIR / "increment5_qualification_profile_v1.schema.json"
)
FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST = (
    "sha256:56de5d698405617731d5e4d6ba403472116f931983f50b2c804377aa1def8bda"
)
QUALIFICATION_PROFILE_SCHEMA_DIGEST = (
    "sha256:81fa28a7e3a66ffe80b7cbef89276769f9c18022a9727650688ad7e8837db75d"
)

_PROFILE_STRUCTURAL_SCHEMA_DIGESTS = {
    RetrievalProfileKind.FIXTURE_REPLAY.value: (
        FIXTURE_REPLAY_PROFILE_STRUCTURAL_SCHEMA_DIGEST
    ),
    RetrievalProfileKind.PRODUCTION_SHAPED_QUALIFICATION.value: (
        QUALIFICATION_PROFILE_STRUCTURAL_SCHEMA_DIGEST
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


def _compile_profile_api() -> tuple[
    Callable[..., dict[str, Any]],
    Callable[..., dict[str, Any]],
    Callable[[Mapping[str, Any]], None],
]:
    """Compile reviewed bytes into builders plus a private deterministic check."""

    clone = deepcopy
    canonicalize = canonical_json_bytes
    calculate_digest = digest_bytes
    validate_digest_text = validate_sha256_digest
    loads_json = json.loads
    schema_validator_type = Draft202012Validator
    canonicalization_error_type = CanonicalizationError
    json_decode_error_type = json.JSONDecodeError
    profile_type = RetrievalProfileKind
    error_type = Increment5ProfileError
    mapping_type = Mapping
    dict_type = dict
    str_type = str

    try:
        contract = _load_repository_contract_once()
    except Increment5ContractError as exc:
        raise error_type(str(exc)) from exc

    expected_structural_schema_digests = dict(_PROFILE_STRUCTURAL_SCHEMA_DIGESTS)
    if dict(contract.profile_schema_digests) != expected_structural_schema_digests:
        raise error_type(
            "repository contract structural profile identities differ from reviewed v1"
        )

    contract_digest = contract.contract_digest
    contract_version = contract.contract_version
    approved_profiles = frozenset(contract.approved_profiles)

    component_document = dict(contract.component_digests)
    payload_budgets = contract.payload["budgets"]
    if not isinstance(payload_budgets, mapping_type):
        raise error_type("accepted contract budgets are malformed")
    budget_document = dict(payload_budgets)
    safe_runtime_effects_document = dict(_SAFE_RUNTIME_EFFECTS)
    try:
        component_bytes = canonicalize(component_document)
        budget_bytes = canonicalize(budget_document)
        safe_runtime_effects_bytes = canonicalize(safe_runtime_effects_document)
    except canonicalization_error_type as exc:
        raise error_type(
            "accepted profile semantics are outside canonical JSON"
        ) from exc

    common_root_keys = frozenset(
        {
            "schema_version",
            "profile_kind",
            "contract_digest",
            "contract_version",
            "components",
            "budgets",
            "runtime_effects",
            "vector_source",
            "qualification_eligible",
            "production_activation_authorized",
        }
    )
    fixture_root_keys = common_root_keys | frozenset({"fixture"})
    qualification_root_keys = common_root_keys | frozenset(
        {
            "dataset",
            "actual_neo4j_required",
            "signed_dataset_manifest_required",
            "embedding_quality_qualified",
            "expected_outcome_scope",
        }
    )
    fixture_keys = frozenset(
        {
            "fixture_id",
            "fixture_manifest_digest",
            "production_substitution_allowed",
        }
    )
    dataset_keys = frozenset(
        {
            "dataset_id",
            "dataset_manifest_digest",
            "rights_cleared",
            "repository_safe",
            "contains_protected_content",
        }
    )
    identifier_first_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    identifier_remaining_chars = identifier_first_chars + "0123456789_.:-"

    def load_canonical_schema(
        path: Path,
        expected_digest: str,
    ) -> tuple[dict[str, Any], bytes]:
        try:
            raw = path.read_bytes()
            value = loads_json(raw.decode("utf-8", errors="strict"))
        except (OSError, UnicodeError, json_decode_error_type) as exc:
            raise error_type("cannot read profile schema") from exc
        try:
            if raw != canonicalize(value):
                raise error_type("profile schema is not canonical JSON")
            if calculate_digest(raw) != expected_digest:
                raise error_type("profile schema digest differs from reviewed v1")
        except canonicalization_error_type as exc:
            raise error_type("profile schema is outside canonical JSON") from exc
        if not isinstance(value, dict_type):
            raise error_type("profile schema must be an object")
        return value, raw

    def compile_schema(
        *,
        binding_path: Path,
        binding_digest: str,
        binding_id: str,
        structural_path: Path,
        structural_digest: str,
    ) -> bytes:
        binding, binding_raw = load_canonical_schema(binding_path, binding_digest)
        structural, _ = load_canonical_schema(structural_path, structural_digest)

        expected_binding = clone(structural)
        try:
            expected_binding["$id"] = binding_id
            expected_binding["title"] = (
                f"{structural['title']} — reviewed identity binding"
            )
            properties = expected_binding["properties"]
            properties["contract_digest"] = {"const": contract_digest}
            component_properties = properties["components"]["properties"]
            if set(component_properties) != set(component_document):
                raise error_type("structural profile component inventory differs")
            for kind, identity_digest in component_document.items():
                component_properties[kind] = {"const": identity_digest}
        except (KeyError, TypeError) as exc:
            raise error_type("structural profile schema shape differs") from exc

        if binding != expected_binding:
            raise error_type(
                "public profile schema is not the reviewed structural binding"
            )

        schema_validator_type.check_schema(binding)
        return binding_raw

    fixture_schema_bytes = compile_schema(
        binding_path=FIXTURE_REPLAY_PROFILE_SCHEMA_PATH,
        binding_digest=FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST,
        binding_id=(
            "urn:newsroom:increment5:fixture-replay-profile:reviewed-binding:v1"
        ),
        structural_path=FIXTURE_REPLAY_PROFILE_STRUCTURAL_SCHEMA_PATH,
        structural_digest=FIXTURE_REPLAY_PROFILE_STRUCTURAL_SCHEMA_DIGEST,
    )
    qualification_schema_bytes = compile_schema(
        binding_path=QUALIFICATION_PROFILE_SCHEMA_PATH,
        binding_digest=QUALIFICATION_PROFILE_SCHEMA_DIGEST,
        binding_id=(
            "urn:newsroom:increment5:production-shaped-qualification-profile:"
            "reviewed-binding:v1"
        ),
        structural_path=QUALIFICATION_PROFILE_STRUCTURAL_SCHEMA_PATH,
        structural_digest=QUALIFICATION_PROFILE_STRUCTURAL_SCHEMA_DIGEST,
    )

    def require_profile(profile: RetrievalProfileKind) -> None:
        if not isinstance(profile, profile_type):
            raise error_type("retrieval profile must be typed")
        if profile not in approved_profiles:
            raise error_type(f"{profile.value} is not admitted by Increment 5A")

    def schema_bytes_for(profile: RetrievalProfileKind) -> bytes:
        require_profile(profile)
        if profile is profile_type.FIXTURE_REPLAY:
            return fixture_schema_bytes
        if profile is profile_type.PRODUCTION_SHAPED_QUALIFICATION:
            return qualification_schema_bytes
        raise error_type("retrieval profile is unsupported")

    def expected_eligibility(profile: RetrievalProfileKind) -> bool:
        require_profile(profile)
        if profile is profile_type.FIXTURE_REPLAY:
            return False
        if profile is profile_type.PRODUCTION_SHAPED_QUALIFICATION:
            return True
        raise error_type("retrieval profile is unsupported")

    def checked_digest(value: object, field: str) -> str:
        try:
            return validate_digest_text(value, field=field)  # type: ignore[arg-type]
        except (canonicalization_error_type, ValueError, TypeError) as exc:
            raise error_type(f"{field} must be a canonical digest") from exc

    def require_identifier(value: object, field: str) -> str:
        if not isinstance(value, str_type):
            raise error_type(f"{field} must be canonical text")
        if not 1 <= len(value) <= 128:
            raise error_type(f"{field} must contain 1 to 128 characters")
        if value[0] not in identifier_first_chars:
            raise error_type(f"{field} must begin with an ASCII letter")
        if any(
            character not in identifier_remaining_chars
            for character in value[1:]
        ):
            raise error_type(f"{field} contains an unsupported character")
        return value

    def require_exact_keys(
        value: object,
        expected: frozenset[str],
        field: str,
    ) -> dict[str, Any]:
        if not isinstance(value, dict_type):
            raise error_type(f"{field} must be an object")
        if frozenset(value) != expected:
            raise error_type(f"{field} fields differ from the reviewed profile")
        return value

    def require_exact_canonical_object(
        value: object,
        expected_bytes: bytes,
        field: str,
    ) -> None:
        if not isinstance(value, dict_type):
            raise error_type(f"{field} must be an object")
        try:
            actual_bytes = canonicalize(value)
        except canonicalization_error_type as exc:
            raise error_type(f"{field} is outside canonical JSON") from exc
        if actual_bytes != expected_bytes:
            raise error_type(f"{field} differs from the reviewed profile")

    def check_semantic_envelope(
        snapshot: dict[str, Any],
        *,
        profile: RetrievalProfileKind,
    ) -> None:
        """Check reviewed semantics; the result itself grants no authority."""

        require_profile(profile)
        eligibility = expected_eligibility(profile)
        if profile is profile_type.FIXTURE_REPLAY:
            root_keys = fixture_root_keys
            schema_version = "newsroom.increment5.fixture-replay-profile.v1"
        elif profile is profile_type.PRODUCTION_SHAPED_QUALIFICATION:
            root_keys = qualification_root_keys
            schema_version = (
                "newsroom.increment5.production-shaped-qualification-profile.v1"
            )
        else:
            raise error_type("retrieval profile is unsupported")

        require_exact_keys(snapshot, root_keys, "profile")
        if snapshot.get("schema_version") != schema_version:
            raise error_type("profile schema version differs")
        if snapshot.get("profile_kind") != profile.value:
            raise error_type("profile kind differs from the selected profile")
        if snapshot.get("contract_digest") != contract_digest:
            raise error_type("profile contract digest differs")
        if snapshot.get("contract_version") != contract_version:
            raise error_type("profile contract version differs")
        require_exact_canonical_object(
            snapshot.get("components"),
            component_bytes,
            "profile component identities",
        )
        require_exact_canonical_object(
            snapshot.get("budgets"),
            budget_bytes,
            "profile budgets",
        )
        require_exact_canonical_object(
            snapshot.get("runtime_effects"),
            safe_runtime_effects_bytes,
            "profile runtime effects",
        )
        if snapshot.get("vector_source") != "DETERMINISTIC_FIXED_POINT_FIXTURE":
            raise error_type("profile vector source differs")
        if snapshot.get("qualification_eligible") is not eligibility:
            raise error_type("profile qualification eligibility differs")
        if snapshot.get("production_activation_authorized") is not False:
            raise error_type("Increment 5 profiles cannot activate production")

        if profile is profile_type.FIXTURE_REPLAY:
            fixture = require_exact_keys(
                snapshot.get("fixture"),
                fixture_keys,
                "fixture",
            )
            require_identifier(fixture.get("fixture_id"), "fixture_id")
            checked_digest(
                fixture.get("fixture_manifest_digest"),
                "fixture_manifest_digest",
            )
            if fixture.get("production_substitution_allowed") is not False:
                raise error_type(
                    "fixture replay cannot substitute for production qualification"
                )
            return

        dataset = require_exact_keys(
            snapshot.get("dataset"),
            dataset_keys,
            "dataset",
        )
        require_identifier(dataset.get("dataset_id"), "dataset_id")
        checked_digest(
            dataset.get("dataset_manifest_digest"),
            "dataset_manifest_digest",
        )
        if dataset.get("rights_cleared") is not True:
            raise error_type("qualification dataset must be rights cleared")
        if dataset.get("repository_safe") is not True:
            raise error_type("qualification dataset must be repository safe")
        if dataset.get("contains_protected_content") is not False:
            raise error_type("qualification dataset cannot contain protected content")
        if snapshot.get("actual_neo4j_required") is not True:
            raise error_type("qualification requires an actual Neo4j service")
        if snapshot.get("signed_dataset_manifest_required") is not True:
            raise error_type("qualification requires a signed dataset manifest")
        if snapshot.get("embedding_quality_qualified") is not False:
            raise error_type(
                "fixed-point fixture vectors cannot qualify embedding quality"
            )
        if snapshot.get("expected_outcome_scope") != (
            "RETRIEVER_INDEX_HYDRATION_AND_DEGRADATION_ONLY"
        ):
            raise error_type("qualification outcome scope differs")

    def fresh_object(raw: bytes, field: str) -> dict[str, Any]:
        try:
            value = loads_json(raw.decode("utf-8", errors="strict"))
        except (UnicodeError, json_decode_error_type) as exc:
            raise error_type(f"{field} cannot be reconstructed") from exc
        if not isinstance(value, dict_type):
            raise error_type(f"{field} must be an object")
        return value

    def check_snapshot(
        snapshot: Mapping[str, Any],
        *,
        profile: RetrievalProfileKind,
    ) -> None:
        require_profile(profile)
        schema_document = fresh_object(
            schema_bytes_for(profile),
            "profile schema",
        )
        validator = schema_validator_type(schema_document)
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
        if not isinstance(snapshot, dict_type):
            raise error_type("profile manifest must be an object")
        check_semantic_envelope(snapshot, profile=profile)

    def base_manifest(profile: RetrievalProfileKind) -> dict[str, Any]:
        require_profile(profile)
        return {
            "profile_kind": profile.value,
            "contract_digest": contract_digest,
            "contract_version": contract_version,
            "components": fresh_object(component_bytes, "components"),
            "budgets": fresh_object(budget_bytes, "budgets"),
            "runtime_effects": fresh_object(
                safe_runtime_effects_bytes,
                "runtime effects",
            ),
            "vector_source": "DETERMINISTIC_FIXED_POINT_FIXTURE",
            "production_activation_authorized": False,
        }

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
        check_snapshot(manifest, profile=profile_type.FIXTURE_REPLAY)
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
        check_snapshot(
            manifest,
            profile=profile_type.PRODUCTION_SHAPED_QUALIFICATION,
        )
        return manifest

    def check_profile_manifest(manifest: Mapping[str, Any]) -> None:
        """Private convenience check; success is not an authority certificate."""

        if not isinstance(manifest, mapping_type):
            raise error_type("profile manifest must be an object")
        try:
            snapshot = loads_json(canonicalize(manifest).decode("utf-8"))
        except (
            canonicalization_error_type,
            UnicodeError,
            json_decode_error_type,
        ) as exc:
            raise error_type("profile manifest is outside canonical JSON") from exc
        if not isinstance(snapshot, dict_type):
            raise error_type("profile manifest must be an object")
        try:
            profile = profile_type(snapshot.get("profile_kind"))
        except (TypeError, ValueError) as exc:
            raise error_type("profile kind is unsupported") from exc
        check_snapshot(snapshot, profile=profile)
        return None

    return (
        build_fixture_replay_manifest,
        build_qualification_manifest,
        check_profile_manifest,
    )


(
    build_fixture_replay_manifest,
    build_qualification_manifest,
    _check_profile_manifest,
) = _compile_profile_api()

# The compiler and repository loader are absent after import. The remaining
# private check is used by the fresh-process validator and grants no authority.
del _compile_profile_api
del _load_repository_contract_once
