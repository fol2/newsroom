from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from jsonschema import Draft202012Validator

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes, validate_sha256_digest

from . import _profiles_proposal_v1 as _proposal
from .contracts import (
    Increment5ADecisionPacket,
    Increment5ContractError,
    Increment5ProfileError,
    RetrievalComponentKind,
    RetrievalMode,
    RetrievalProfileKind,
    RuntimeAuthority,
)


# v1 remains immutable proposal evidence only; the public production surface is v2.
PROPOSAL_PRODUCTION_PROFILE_SCHEMA = _proposal.PRODUCTION_PROFILE_SCHEMA
PROPOSAL_PRODUCTION_PROFILE_SCHEMA_DIGEST = _proposal.PRODUCTION_PROFILE_SCHEMA_DIGEST
PROPOSAL_PRODUCTION_PROFILE_SCHEMA_ID = _proposal.PRODUCTION_PROFILE_SCHEMA_ID
PROPOSAL_PRODUCTION_PROFILE_SCHEMA_PATH = _proposal.PRODUCTION_PROFILE_SCHEMA_PATH
PROPOSAL_PRODUCTION_PROFILE_SCHEMA_VERSION = _proposal.PRODUCTION_PROFILE_SCHEMA_VERSION

FIXTURE_REPLAY_PROFILE_SCHEMA = _proposal.FIXTURE_REPLAY_PROFILE_SCHEMA
FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST = _proposal.FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST
FIXTURE_REPLAY_PROFILE_SCHEMA_ID = _proposal.FIXTURE_REPLAY_PROFILE_SCHEMA_ID
FIXTURE_REPLAY_PROFILE_SCHEMA_PATH = _proposal.FIXTURE_REPLAY_PROFILE_SCHEMA_PATH
FIXTURE_REPLAY_PROFILE_SCHEMA_VERSION = _proposal.FIXTURE_REPLAY_PROFILE_SCHEMA_VERSION

QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_ID = "urn:newsroom:increment5:production-qualification-profile:v2"
QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_VERSION = "increment5-production-qualification-profile-v2"
QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_PATH = (
    Path(__file__).resolve().parent / "data" / "increment5_production_qualification_profile_v2.schema.json"
)
_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
_REQUIRED_MODES = tuple(item.value for item in RetrievalMode)

RepositoryApprovalBinding = tuple[
    object,
    Callable[[], object | None],
    Callable[[object | None], str],
]


def _repository_authority_binding_factory() -> tuple[
    Callable[..., None],
    Callable[[], RepositoryApprovalBinding],
]:
    binding: RepositoryApprovalBinding | None = None

    def bind_once(
        *,
        authority: object,
        load_approval: Callable[[], object | None],
        effective_contract_digest_for: Callable[[object | None], str],
    ) -> None:
        nonlocal binding
        candidate = (
            authority,
            load_approval,
            effective_contract_digest_for,
        )
        if binding is None:
            binding = candidate
            return
        if (
            binding[0] is not authority
            or binding[1] is not load_approval
            or binding[2] is not effective_contract_digest_for
        ):
            raise Increment5ContractError(
                "repository approval authority is already bound"
            )

    def get_binding() -> RepositoryApprovalBinding:
        if binding is None:
            raise Increment5ProfileError(
                "repository approval authority is not initialized"
            )
        return binding

    return bind_once, get_binding


(
    _bind_repository_authority_once,
    _get_repository_authority_binding,
) = _repository_authority_binding_factory()


def _proposal_packet() -> Increment5ADecisionPacket:
    # decision.py imports this schema module, so load the packet only after both
    # modules have completed initialization.
    from .decision import INCREMENT_5A_DECISION_PACKET

    return INCREMENT_5A_DECISION_PACKET


def _qualification_component_reference_schema() -> dict[str, object]:
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
            "contract_version": {"type": "string", "minLength": 1, "maxLength": 128},
            "implementation_version": {"type": "string", "minLength": 1, "maxLength": 128},
            "configuration_digest": {"type": "string", "pattern": _SHA256_PATTERN},
            "identity_digest": {"type": "string", "pattern": _SHA256_PATTERN},
            "implementation_kind": {"const": "REAL_REPOSITORY_NATIVE"},
            "approval_status": {"const": "APPROVED_BY_ATTESTATION"},
        },
    }


_qualification_common_properties = deepcopy(_proposal._COMMON_PROPERTIES)
_qualification_budgets = deepcopy(_qualification_common_properties["budgets"])
assert isinstance(_qualification_budgets, dict)
_budget_properties = _qualification_budgets["properties"]
assert isinstance(_budget_properties, dict)
_budget_properties["max_external_calls_per_request"] = {"const": 0}
_budget_properties["max_gross_cost_microunits_per_request"] = {"const": 0}
_qualification_common_properties["budgets"] = _qualification_budgets
_qualification_rights = deepcopy(_qualification_common_properties["rights"])
assert isinstance(_qualification_rights, dict)
_rights_properties = _qualification_rights["properties"]
assert isinstance(_rights_properties, dict)
_rights_properties["protected_content_allowed"] = {"const": False}
_qualification_common_properties["rights"] = _qualification_rights

QUALIFICATION_PRODUCTION_PROFILE_SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_ID,
    "type": "object",
    "required": [
        *_proposal._COMMON_REQUIRED,
        "proposal_record_digest",
        "approval_attestation_digest",
        "effective_contract_digest",
    ],
    "additionalProperties": False,
    "properties": {
        **_qualification_common_properties,
        "schema_version": {"const": QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_VERSION},
        "profile": {"const": RetrievalProfileKind.PRODUCTION.value},
        "runtime_authority": {"const": RuntimeAuthority.PRODUCTION_QUALIFICATION.value},
        "qualification_eligible": {"const": True},
        "proposal_record_digest": {"type": "string", "pattern": _SHA256_PATTERN},
        "approval_attestation_digest": {"type": "string", "pattern": _SHA256_PATTERN},
        "effective_contract_digest": {"type": "string", "pattern": _SHA256_PATTERN},
        "components": {
            "type": "object",
            "required": [item.value for item in RetrievalComponentKind],
            "additionalProperties": False,
            "properties": {
                item.value: _qualification_component_reference_schema()
                for item in RetrievalComponentKind
            },
        },
    },
}
Draft202012Validator.check_schema(QUALIFICATION_PRODUCTION_PROFILE_SCHEMA)
_QUALIFICATION_PRODUCTION_VALIDATOR = Draft202012Validator(QUALIFICATION_PRODUCTION_PROFILE_SCHEMA)
QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_DIGEST = digest_bytes(
    canonical_json_bytes(QUALIFICATION_PRODUCTION_PROFILE_SCHEMA)
)


def _require_qualification_schema_artifact() -> None:
    try:
        data = QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_PATH.read_bytes()
        value = json.loads(data.decode("utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Increment5ContractError("cannot load production-qualification profile schema artifact") from exc
    if not isinstance(value, dict):
        raise Increment5ContractError("production-qualification schema artifact must be an object")
    if (
        data != canonical_json_bytes(value)
        or value != QUALIFICATION_PRODUCTION_PROFILE_SCHEMA
        or digest_bytes(data) != QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_DIGEST
    ):
        raise Increment5ContractError("production-qualification schema artifact differs from code")


_require_qualification_schema_artifact()


@dataclass(frozen=True, slots=True)
class ValidatedRetrievalProfile:
    profile: RetrievalProfileKind
    decision_payload_digest: str
    contract_bundle_digest: str
    manifest_digest: str
    qualification_eligible: bool
    proposal_record_digest: str | None = None
    approval_attestation_digest: str | None = None
    effective_contract_digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.profile, RetrievalProfileKind):
            raise Increment5ContractError("validated profile kind must be typed")
        for field_name in ("decision_payload_digest", "contract_bundle_digest", "manifest_digest"):
            try:
                validate_sha256_digest(getattr(self, field_name), field=field_name)
            except ValueError as exc:
                raise Increment5ContractError(f"{field_name} is not a canonical digest") from exc
        optional = ("proposal_record_digest", "approval_attestation_digest", "effective_contract_digest")
        for field_name in optional:
            value = getattr(self, field_name)
            if value is not None:
                try:
                    validate_sha256_digest(value, field=field_name)
                except ValueError as exc:
                    raise Increment5ContractError(f"{field_name} is not a canonical digest") from exc
        if not isinstance(self.qualification_eligible, bool):
            raise Increment5ContractError("qualification eligibility must be boolean")
        if self.profile is RetrievalProfileKind.FIXTURE_REPLAY:
            if self.qualification_eligible or any(getattr(self, name) is not None for name in optional):
                raise Increment5ContractError("fixture replay cannot carry production authority")
        elif not self.qualification_eligible or any(getattr(self, name) is None for name in optional):
            raise Increment5ContractError("production qualification requires complete approval identity")


def _schema_errors(
    validator: Draft202012Validator,
    document: Mapping[str, Any],
) -> tuple[str, ...]:
    errors = sorted(
        validator.iter_errors(document),
        key=lambda item: [str(component) for component in item.absolute_path],
    )
    return tuple(
        ("/".join(str(component) for component in error.absolute_path) or "<root>")
        + ": "
        + error.message
        for error in errors
    )


def _proposal_for_fixture(packet: object) -> Increment5ADecisionPacket:
    from .approval import INCREMENT_5A_DECISION_AUTHORITY

    proposal = _proposal_packet()
    if packet is proposal or packet is INCREMENT_5A_DECISION_AUTHORITY:
        return proposal
    raise Increment5ProfileError("retrieval profile validation requires canonical 5A authority")


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
            raise Increment5ProfileError(f"profile does not bind {kind.value}")
        expected = {
            "contract_id": identity.contract_id,
            "contract_version": identity.contract_version,
            "implementation_version": identity.implementation_version,
            "configuration_digest": identity.configuration_digest,
            "identity_digest": identity.identity_digest,
        }
        if {key: reference.get(key) for key in expected} != expected:
            raise Increment5ProfileError(f"profile component {kind.value} differs from proposal")


def _require_budget_binding(
    *,
    document: Mapping[str, Any],
    packet: Increment5ADecisionPacket,
) -> None:
    budgets = document.get("budgets")
    if not isinstance(budgets, Mapping):
        raise Increment5ProfileError("profile budgets are absent")
    selected = packet.budgets.canonical_value()
    if {key: budgets.get(key) for key in selected} != selected:
        raise Increment5ProfileError("profile budgets differ from the exact proposal")


def _validate_profile_manifest_impl(
    document: Mapping[str, Any],
    *,
    packet: object,
    _repository_binding: RepositoryApprovalBinding,
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

    if profile is RetrievalProfileKind.FIXTURE_REPLAY:
        proposal = _proposal_for_fixture(packet)
        validated = _proposal.validate_profile_manifest(document, packet=proposal)
        return ValidatedRetrievalProfile(
            profile=validated.profile,
            decision_payload_digest=validated.decision_payload_digest,
            contract_bundle_digest=validated.contract_bundle_digest,
            manifest_digest=validated.manifest_digest,
            qualification_eligible=False,
        )

    (
        authority,
        load_approval,
        effective_contract_digest_for,
    ) = _repository_binding
    if packet is not authority:
        raise Increment5ProfileError(
            "PRODUCTION requires canonical repository authority"
        )
    proposal = _proposal_packet()
    approval = load_approval()
    if approval is None:
        raise Increment5ProfileError(
            "PRODUCTION is not authorized without the admitted repository "
            "owner approval record"
        )
    effective_contract_digest = effective_contract_digest_for(approval)
    errors = _schema_errors(_QUALIFICATION_PRODUCTION_VALIDATOR, document)
    if errors:
        raise Increment5ProfileError("retrieval profile schema validation failed: " + errors[0])
    if document["decision_payload_digest"] != proposal.payload_digest:
        raise Increment5ProfileError("profile proposal payload digest differs")
    if document["proposal_record_digest"] != proposal.record_digest:
        raise Increment5ProfileError("profile proposal record digest differs")
    if document["contract_bundle_digest"] != proposal.bundle.contract_digest:
        raise Increment5ProfileError("profile proposal contract bundle differs")
    if document["approval_attestation_digest"] != approval.attestation_digest:
        raise Increment5ProfileError("profile approval record digest differs")
    if document["effective_contract_digest"] != effective_contract_digest:
        raise Increment5ProfileError("profile effective contract digest differs")
    _require_component_references(document=document, packet=proposal)
    _require_budget_binding(document=document, packet=proposal)
    for kind in RetrievalComponentKind:
        expected = proposal.bundle.component_by_kind[kind].identity_digest
        if approval.component_digest_by_kind.get(kind) != expected:
            raise Increment5ProfileError("production component approval is incomplete")
    rights = document["rights"]
    if rights["protected_content_allowed"] is not False:
        raise Increment5ProfileError("Increment 5 v1 prohibits protected-content processing")
    if not rights["rights_rechecked_at_hydration"] or not rights["purge_required"] or not rights["rebuild_must_not_resurrect"]:
        raise Increment5ProfileError("profile cannot weaken rights, purge or non-resurrection")
    return ValidatedRetrievalProfile(
        profile=RetrievalProfileKind.PRODUCTION,
        decision_payload_digest=proposal.payload_digest,
        proposal_record_digest=proposal.record_digest,
        contract_bundle_digest=proposal.bundle.contract_digest,
        approval_attestation_digest=approval.attestation_digest,
        effective_contract_digest=effective_contract_digest,
        manifest_digest=digest_bytes(canonical_json_bytes(document)),
        qualification_eligible=True,
    )


def build_fixture_replay_manifest(
    *,
    packet: object,
    fixture_id: str,
    fixture_manifest_digest: str,
) -> dict[str, object]:
    return _proposal.build_fixture_replay_manifest(
        packet=_proposal_for_fixture(packet),
        fixture_id=fixture_id,
        fixture_manifest_digest=fixture_manifest_digest,
    )


def _build_production_qualification_manifest_impl(
    *,
    _repository_binding: RepositoryApprovalBinding,
) -> dict[str, object]:
    (
        _authority,
        load_approval,
        effective_contract_digest_for,
    ) = _repository_binding
    proposal = _proposal_packet()
    approval = load_approval()
    if approval is None:
        raise Increment5ProfileError(
            "PRODUCTION is not authorized without the admitted repository "
            "owner approval record"
        )
    effective_contract_digest = effective_contract_digest_for(approval)
    components: dict[str, object] = {}
    for kind, identity in proposal.bundle.component_by_kind.items():
        if approval.component_digest_by_kind.get(kind) != identity.identity_digest:
            raise Increment5ProfileError(f"production component {kind.value} is not approved")
        components[kind.value] = {
            "contract_id": identity.contract_id,
            "contract_version": identity.contract_version,
            "implementation_version": identity.implementation_version,
            "configuration_digest": identity.configuration_digest,
            "identity_digest": identity.identity_digest,
            "implementation_kind": "REAL_REPOSITORY_NATIVE",
            "approval_status": "APPROVED_BY_ATTESTATION",
        }
    return {
        "schema_version": QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_VERSION,
        "profile": RetrievalProfileKind.PRODUCTION.value,
        "decision_payload_digest": proposal.payload_digest,
        "proposal_record_digest": proposal.record_digest,
        "contract_bundle_digest": proposal.bundle.contract_digest,
        "approval_attestation_digest": approval.attestation_digest,
        "effective_contract_digest": effective_contract_digest,
        "runtime_authority": RuntimeAuthority.PRODUCTION_QUALIFICATION.value,
        "qualification_eligible": True,
        "required_modes": list(_REQUIRED_MODES),
        "graph_free_fallback": False,
        "silent_mode_fallback": False,
        "components": components,
        "budgets": proposal.budgets.canonical_value(),
        "rights": {
            "protected_content_allowed": False,
            "rights_rechecked_at_hydration": True,
            "purge_required": True,
            "rebuild_must_not_resurrect": True,
        },
    }


def _public_profile_gate_factory(
    *,
    validate_impl: Callable[..., ValidatedRetrievalProfile],
    build_impl: Callable[..., dict[str, object]],
    get_binding: Callable[[], RepositoryApprovalBinding],
) -> tuple[Callable[..., ValidatedRetrievalProfile], Callable[[], dict[str, object]]]:
    def validate_profile_manifest(
        document: Mapping[str, Any],
        *,
        packet: object,
    ) -> ValidatedRetrievalProfile:
        return validate_impl(
            document,
            packet=packet,
            _repository_binding=get_binding(),
        )

    def build_production_qualification_manifest() -> dict[str, object]:
        return build_impl(_repository_binding=get_binding())

    return validate_profile_manifest, build_production_qualification_manifest


(
    validate_profile_manifest,
    build_production_qualification_manifest,
) = _public_profile_gate_factory(
    validate_impl=_validate_profile_manifest_impl,
    build_impl=_build_production_qualification_manifest_impl,
    get_binding=_get_repository_authority_binding,
)

del _validate_profile_manifest_impl
del _build_production_qualification_manifest_impl
del _public_profile_gate_factory
del _get_repository_authority_binding
