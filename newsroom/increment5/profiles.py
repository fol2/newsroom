from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)

from .contracts import (
    ComponentDisposition,
    Increment5ADecisionPacket,
    Increment5ContractError,
    Increment5ProfileError,
    RetrievalComponentKind,
    RetrievalMode,
    RetrievalProfileKind,
    RuntimeAuthority,
)


PRODUCTION_PROFILE_SCHEMA_ID = "urn:newsroom:increment5:production-profile:v1"
FIXTURE_REPLAY_PROFILE_SCHEMA_ID = (
    "urn:newsroom:increment5:fixture-replay-profile:v1"
)
PRODUCTION_PROFILE_SCHEMA_VERSION = "increment5-production-profile-v1"
FIXTURE_REPLAY_PROFILE_SCHEMA_VERSION = "increment5-fixture-replay-profile-v1"

_PROFILE_DATA_ROOT = Path(__file__).resolve().parent / "data"
PRODUCTION_PROFILE_SCHEMA_PATH = (
    _PROFILE_DATA_ROOT / "increment5_production_profile_v1.schema.json"
)
FIXTURE_REPLAY_PROFILE_SCHEMA_PATH = (
    _PROFILE_DATA_ROOT / "increment5_fixture_replay_profile_v1.schema.json"
)


_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
_COMPONENT_KEYS = tuple(item.value for item in RetrievalComponentKind)
_REQUIRED_MODES = tuple(item.value for item in RetrievalMode)


def _component_reference_schema(
    *,
    implementation_kinds: tuple[str, ...],
    approval_statuses: tuple[str, ...],
) -> dict[str, object]:
    return {
        "type": "object",
        "required": [
            "contract_id",
            "contract_version",
            "implementation_version",
            "configuration_digest",
            "identity_digest",
            "implementation_kind",
            "approval_status",
        ],
        "additionalProperties": False,
        "properties": {
            "contract_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "contract_version": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
            },
            "implementation_version": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
            },
            "configuration_digest": {
                "type": "string",
                "pattern": _SHA256_PATTERN,
            },
            "identity_digest": {
                "type": "string",
                "pattern": _SHA256_PATTERN,
            },
            "implementation_kind": {"enum": list(implementation_kinds)},
            "approval_status": {"enum": list(approval_statuses)},
        },
    }


def _components_schema(reference: dict[str, object]) -> dict[str, object]:
    return {
        "type": "object",
        "required": list(_COMPONENT_KEYS),
        "additionalProperties": False,
        "properties": {key: reference for key in _COMPONENT_KEYS},
    }


_COMMON_REQUIRED = [
    "schema_version",
    "profile",
    "decision_payload_digest",
    "contract_bundle_digest",
    "runtime_authority",
    "qualification_eligible",
    "required_modes",
    "graph_free_fallback",
    "silent_mode_fallback",
    "components",
    "budgets",
    "rights",
]


_COMMON_PROPERTIES: dict[str, object] = {
    "decision_payload_digest": {"type": "string", "pattern": _SHA256_PATTERN},
    "contract_bundle_digest": {"type": "string", "pattern": _SHA256_PATTERN},
    "required_modes": {"const": list(_REQUIRED_MODES)},
    "graph_free_fallback": {"const": False},
    "silent_mode_fallback": {"const": False},
    "budgets": {
        "type": "object",
        "required": [
            "timeout_ms",
            "branch_result_limit",
            "retained_candidate_limit",
            "response_byte_limit",
            "max_external_calls_per_request",
            "max_gross_cost_microunits_per_request",
        ],
        "additionalProperties": False,
        "properties": {
            "timeout_ms": {"type": "integer", "minimum": 1, "maximum": 5000},
            "branch_result_limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 8,
            },
            "retained_candidate_limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 12,
            },
            "response_byte_limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 262144,
            },
            "max_external_calls_per_request": {
                "type": "integer",
                "minimum": 0,
                "maximum": 8,
            },
            "max_gross_cost_microunits_per_request": {
                "type": "integer",
                "minimum": 0,
            },
        },
    },
    "rights": {
        "type": "object",
        "required": [
            "protected_content_allowed",
            "rights_rechecked_at_hydration",
            "purge_required",
            "rebuild_must_not_resurrect",
        ],
        "additionalProperties": False,
        "properties": {
            "protected_content_allowed": {"type": "boolean"},
            "rights_rechecked_at_hydration": {"const": True},
            "purge_required": {"const": True},
            "rebuild_must_not_resurrect": {"const": True},
        },
    },
}


PRODUCTION_PROFILE_SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": PRODUCTION_PROFILE_SCHEMA_ID,
    "type": "object",
    "required": _COMMON_REQUIRED,
    "additionalProperties": False,
    "properties": {
        **_COMMON_PROPERTIES,
        "schema_version": {"const": PRODUCTION_PROFILE_SCHEMA_VERSION},
        "profile": {"const": RetrievalProfileKind.PRODUCTION.value},
        "runtime_authority": {
            "const": RuntimeAuthority.PRODUCTION_QUALIFICATION.value
        },
        "qualification_eligible": {"const": True},
        "components": _components_schema(
            _component_reference_schema(
                implementation_kinds=("REAL_REPOSITORY_NATIVE",),
                approval_statuses=("APPROVED",),
            )
        ),
    },
}


FIXTURE_REPLAY_PROFILE_SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": FIXTURE_REPLAY_PROFILE_SCHEMA_ID,
    "type": "object",
    "required": _COMMON_REQUIRED + ["fixture"],
    "additionalProperties": False,
    "properties": {
        **_COMMON_PROPERTIES,
        "schema_version": {"const": FIXTURE_REPLAY_PROFILE_SCHEMA_VERSION},
        "profile": {"const": RetrievalProfileKind.FIXTURE_REPLAY.value},
        "runtime_authority": {
            "const": RuntimeAuthority.CONTRACT_AND_FIXTURE_REPLAY_ONLY.value
        },
        "qualification_eligible": {"const": False},
        "components": _components_schema(
            _component_reference_schema(
                implementation_kinds=(
                    "REPOSITORY_FIXTURE",
                    "REPOSITORY_REPLAY",
                ),
                approval_statuses=("NON_QUALIFYING",),
            )
        ),
        "fixture": {
            "type": "object",
            "required": [
                "fixture_id",
                "fixture_manifest_digest",
                "protected_content_present",
                "production_substitution_allowed",
            ],
            "additionalProperties": False,
            "properties": {
                "fixture_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 256,
                },
                "fixture_manifest_digest": {
                    "type": "string",
                    "pattern": _SHA256_PATTERN,
                },
                "protected_content_present": {"const": False},
                "production_substitution_allowed": {"const": False},
            },
        },
    },
}


Draft202012Validator.check_schema(PRODUCTION_PROFILE_SCHEMA)
Draft202012Validator.check_schema(FIXTURE_REPLAY_PROFILE_SCHEMA)
_PRODUCTION_VALIDATOR = Draft202012Validator(PRODUCTION_PROFILE_SCHEMA)
_FIXTURE_REPLAY_VALIDATOR = Draft202012Validator(
    FIXTURE_REPLAY_PROFILE_SCHEMA
)

PRODUCTION_PROFILE_SCHEMA_DIGEST = digest_bytes(
    canonical_json_bytes(PRODUCTION_PROFILE_SCHEMA)
)
FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST = digest_bytes(
    canonical_json_bytes(FIXTURE_REPLAY_PROFILE_SCHEMA)
)


def _require_schema_artifact(
    *,
    path: Path,
    expected: Mapping[str, Any],
    expected_digest: str,
) -> None:
    try:
        data = path.read_bytes()
        value = json.loads(data.decode("utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Increment5ContractError(
            f"cannot load retrieval profile schema artifact: {path.name}"
        ) from exc
    if not isinstance(value, dict):
        raise Increment5ContractError(
            f"retrieval profile schema artifact is not an object: {path.name}"
        )
    if data != canonical_json_bytes(value):
        raise Increment5ContractError(
            f"retrieval profile schema artifact is not canonical: {path.name}"
        )
    if value != dict(expected) or digest_bytes(data) != expected_digest:
        raise Increment5ContractError(
            f"retrieval profile schema artifact differs from code: {path.name}"
        )


_require_schema_artifact(
    path=PRODUCTION_PROFILE_SCHEMA_PATH,
    expected=PRODUCTION_PROFILE_SCHEMA,
    expected_digest=PRODUCTION_PROFILE_SCHEMA_DIGEST,
)
_require_schema_artifact(
    path=FIXTURE_REPLAY_PROFILE_SCHEMA_PATH,
    expected=FIXTURE_REPLAY_PROFILE_SCHEMA,
    expected_digest=FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST,
)


@dataclass(frozen=True, slots=True)
class ValidatedRetrievalProfile:
    profile: RetrievalProfileKind
    decision_payload_digest: str
    contract_bundle_digest: str
    manifest_digest: str
    qualification_eligible: bool

    def __post_init__(self) -> None:
        if not isinstance(self.profile, RetrievalProfileKind):
            raise Increment5ContractError("validated profile kind must be typed")
        for field_name in (
            "decision_payload_digest",
            "contract_bundle_digest",
            "manifest_digest",
        ):
            try:
                validate_sha256_digest(getattr(self, field_name), field=field_name)
            except ValueError as exc:
                raise Increment5ContractError(
                    f"{field_name} is not a canonical digest"
                ) from exc
        if not isinstance(self.qualification_eligible, bool):
            raise Increment5ContractError(
                "qualification eligibility must be boolean"
            )
        if (
            self.profile is RetrievalProfileKind.FIXTURE_REPLAY
            and self.qualification_eligible
        ):
            raise Increment5ContractError(
                "fixture replay can never become qualification evidence"
            )


def _schema_errors(
    validator: Draft202012Validator,
    document: Mapping[str, Any],
) -> tuple[str, ...]:
    errors = sorted(
        validator.iter_errors(document),
        key=lambda item: [str(component) for component in item.absolute_path],
    )
    return tuple(
        (
            "/".join(str(component) for component in error.absolute_path)
            or "<root>"
        )
        + ": "
        + error.message
        for error in errors
    )


def _require_component_references(
    *,
    document: Mapping[str, Any],
    packet: Increment5ADecisionPacket,
) -> None:
    components = document.get("components")
    if not isinstance(components, Mapping):
        raise Increment5ProfileError("profile component references are absent")
    for kind, identity in packet.bundle.component_by_kind.items():
        reference = components.get(kind.value)
        if not isinstance(reference, Mapping):
            raise Increment5ProfileError(
                f"profile does not bind {kind.value}"
            )
        expected = {
            "contract_id": identity.contract_id,
            "contract_version": identity.contract_version,
            "implementation_version": identity.implementation_version,
            "configuration_digest": identity.configuration_digest,
            "identity_digest": identity.identity_digest,
        }
        actual = {key: reference.get(key) for key in expected}
        if actual != expected:
            raise Increment5ProfileError(
                f"profile component {kind.value} differs from the exact decision"
            )


def _require_budget_binding(
    *,
    document: Mapping[str, Any],
    packet: Increment5ADecisionPacket,
) -> None:
    budgets = document.get("budgets")
    if not isinstance(budgets, Mapping):
        raise Increment5ProfileError("profile budgets are absent")
    selected = packet.budgets.canonical_value()
    actual = {key: budgets.get(key) for key in selected}
    if actual != selected:
        raise Increment5ProfileError(
            "profile budgets differ from the exact decision packet"
        )


def validate_profile_manifest(
    document: Mapping[str, Any],
    *,
    packet: Increment5ADecisionPacket,
) -> ValidatedRetrievalProfile:
    if not isinstance(document, Mapping):
        raise Increment5ProfileError("retrieval profile manifest must be an object")
    raw_profile = document.get("profile")
    if not isinstance(raw_profile, str):
        raise Increment5ProfileError("retrieval profile kind is unknown")
    try:
        profile = RetrievalProfileKind(raw_profile)
    except ValueError as exc:
        raise Increment5ProfileError("retrieval profile kind is unknown") from exc

    validator = (
        _PRODUCTION_VALIDATOR
        if profile is RetrievalProfileKind.PRODUCTION
        else _FIXTURE_REPLAY_VALIDATOR
    )
    errors = _schema_errors(validator, document)
    if errors:
        raise Increment5ProfileError(
            "retrieval profile schema validation failed: " + errors[0]
        )

    if document["decision_payload_digest"] != packet.payload_digest:
        raise Increment5ProfileError(
            "profile decision digest differs from the exact packet"
        )
    if document["contract_bundle_digest"] != packet.bundle.contract_digest:
        raise Increment5ProfileError(
            "profile contract bundle digest differs from the exact packet"
        )
    _require_component_references(document=document, packet=packet)
    _require_budget_binding(document=document, packet=packet)
    packet.require_profile(profile)

    rights = document["rights"]
    if not rights["rights_rechecked_at_hydration"]:
        raise Increment5ProfileError(
            "profile cannot bypass rights recheck during hydration"
        )
    if not rights["purge_required"] or not rights["rebuild_must_not_resurrect"]:
        raise Increment5ProfileError(
            "profile cannot weaken purge or non-resurrection"
        )

    if profile is RetrievalProfileKind.PRODUCTION:
        for kind, identity in packet.bundle.component_by_kind.items():
            if identity.disposition is not ComponentDisposition.BOUND_CONTRACT:
                raise Increment5ProfileError(
                    f"production component {kind.value} is not fully bound"
                )
        if packet.unresolved_decisions:
            raise Increment5ProfileError(
                "production profile cannot validate with unresolved decisions"
            )
    else:
        budgets = document["budgets"]
        if (
            budgets["max_external_calls_per_request"] != 0
            or budgets["max_gross_cost_microunits_per_request"] != 0
            or document["rights"]["protected_content_allowed"]
        ):
            raise Increment5ProfileError(
                "fixture replay must remain local, zero-spend and unprotected"
            )

    return ValidatedRetrievalProfile(
        profile=profile,
        decision_payload_digest=packet.payload_digest,
        contract_bundle_digest=packet.bundle.contract_digest,
        manifest_digest=digest_bytes(canonical_json_bytes(document)),
        qualification_eligible=bool(document["qualification_eligible"]),
    )


def build_fixture_replay_manifest(
    *,
    packet: Increment5ADecisionPacket,
    fixture_id: str,
    fixture_manifest_digest: str,
) -> dict[str, object]:
    packet.require_profile(RetrievalProfileKind.FIXTURE_REPLAY)
    if (
        not isinstance(fixture_id, str)
        or not fixture_id
        or fixture_id != fixture_id.strip()
        or len(fixture_id.encode("utf-8")) > 256
    ):
        raise Increment5ProfileError(
            "fixture identity must be bounded canonical text"
        )
    try:
        validate_sha256_digest(
            fixture_manifest_digest,
            field="fixture_manifest_digest",
        )
    except ValueError as exc:
        raise Increment5ProfileError(
            "fixture manifest digest is invalid"
        ) from exc

    components: dict[str, object] = {}
    for kind, identity in packet.bundle.component_by_kind.items():
        implementation_kind = (
            "REPOSITORY_FIXTURE"
            if kind
            in {
                RetrievalComponentKind.EMBEDDING,
                RetrievalComponentKind.VECTOR_INDEX,
            }
            else "REPOSITORY_REPLAY"
        )
        components[kind.value] = {
            "contract_id": identity.contract_id,
            "contract_version": identity.contract_version,
            "implementation_version": identity.implementation_version,
            "configuration_digest": identity.configuration_digest,
            "identity_digest": identity.identity_digest,
            "implementation_kind": implementation_kind,
            "approval_status": "NON_QUALIFYING",
        }

    return {
        "schema_version": FIXTURE_REPLAY_PROFILE_SCHEMA_VERSION,
        "profile": RetrievalProfileKind.FIXTURE_REPLAY.value,
        "decision_payload_digest": packet.payload_digest,
        "contract_bundle_digest": packet.bundle.contract_digest,
        "runtime_authority": (
            RuntimeAuthority.CONTRACT_AND_FIXTURE_REPLAY_ONLY.value
        ),
        "qualification_eligible": False,
        "required_modes": list(_REQUIRED_MODES),
        "graph_free_fallback": False,
        "silent_mode_fallback": False,
        "components": components,
        "budgets": packet.budgets.canonical_value(),
        "rights": {
            "protected_content_allowed": False,
            "rights_rechecked_at_hydration": True,
            "purge_required": True,
            "rebuild_must_not_resurrect": True,
        },
        "fixture": {
            "fixture_id": fixture_id,
            "fixture_manifest_digest": fixture_manifest_digest,
            "protected_content_present": False,
            "production_substitution_allowed": False,
        },
    }
