from __future__ import annotations

from typing import Callable

from . import profiles as _profiles_module


_original_bind_repository_authority_once = (
    _profiles_module._bind_repository_authority_once
)
_profiles_module._bind_repository_authority_once = lambda **_kwargs: None
try:
    from . import _approval_v1 as _core
finally:
    _profiles_module._bind_repository_authority_once = (
        _original_bind_repository_authority_once
    )

for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)

from .admission_anchors import (
    ADMISSION_SOURCE_BUNDLE_IDENTITY,
    ADMISSION_SOURCE_MANIFEST_DIGEST,
    APPROVAL_RECORD_DIGEST,
    MAIN_QUALIFICATION_RECORD_DIGEST,
)
from .github_attempts import (
    build_repository_main_qualification_authenticator,
)


def expected_increment5a_owner_approval_body(
    proposal: Increment5ADecisionPacket = INCREMENT_5A_DECISION_PACKET,
) -> str:
    if not isinstance(proposal, Increment5ADecisionPacket):
        raise Increment5ContractError(
            "approval statement requires a typed proposal"
        )
    return (
        "I approve Increment 5A proposal payload "
        f"`{proposal.payload_digest}`, proposal record "
        f"`{proposal.record_digest}`, proposal contract bundle "
        f"`{proposal.bundle.contract_digest}`, effective "
        "production-qualification schema "
        f"`{_qualification_schema_digest()}`, approval-attestation schema "
        f"`{APPROVAL_ATTESTATION_SCHEMA_DIGEST}`, fixture-replay schema "
        f"`{proposal.bundle.fixture_replay_profile_schema_digest}`, "
        "admission-source manifest "
        f"`{ADMISSION_SOURCE_MANIFEST_DIGEST}`, and admission-source bundle "
        f"`{ADMISSION_SOURCE_BUNDLE_IDENTITY}` as the exact "
        "production-equivalent qualification contract for issues #251–#254. "
        "This approval authorizes production-equivalent qualification only; "
        "it authorizes no downstream implementation, shadow, canary, "
        "production activation, publication, public effect, live-source "
        "execution, external embedding API call, provider spending, or "
        "protected-content vector."
    )


# All core builders and parsers resolve this global at call time.  Binding the
# reviewed source identities into the exact GitHub owner statement makes the
# mutable data anchor externally authenticated without changing the immutable
# approval/parser/gate source during later materialisation.
_core.expected_increment5a_owner_approval_body = (
    expected_increment5a_owner_approval_body
)

_LOAD_REPOSITORY_APPROVAL = _core._repository_loader_factory(
    path=APPROVAL_RECORD_PATH,
    expected_digest=APPROVAL_RECORD_DIGEST,
)
_AUTHENTICATE_REPOSITORY_MAIN_QUALIFICATION = (
    build_repository_main_qualification_authenticator(
        approval_loader=_LOAD_REPOSITORY_APPROVAL,
    )
)
_LOAD_MAIN_QUALIFICATION = _core._main_qualification_loader_factory(
    path=MAIN_QUALIFICATION_RECORD_PATH,
    expected_digest=MAIN_QUALIFICATION_RECORD_DIGEST,
    approval_record_digest=APPROVAL_RECORD_DIGEST,
    authenticator=_AUTHENTICATE_REPOSITORY_MAIN_QUALIFICATION,
)
_EFFECTIVE_CONTRACT_DIGEST_FOR = _core._effective_contract_digest_factory(
    proposal=INCREMENT_5A_DECISION_PACKET,
    qualification_schema_digest=_qualification_schema_digest(),
    approval_effect=APPROVAL_EFFECT,
)

Increment5ADecisionAuthority = _core._decision_authority_class_factory(
    proposal=INCREMENT_5A_DECISION_PACKET,
    load_approval=_LOAD_REPOSITORY_APPROVAL,
    load_main_qualification=_LOAD_MAIN_QUALIFICATION,
    effective_contract_digest_for=_EFFECTIVE_CONTRACT_DIGEST_FOR,
)
INCREMENT_5A_DECISION_AUTHORITY = Increment5ADecisionAuthority()

_original_bind_repository_authority_once(
    authority=INCREMENT_5A_DECISION_AUTHORITY,
    load_approval=_LOAD_REPOSITORY_APPROVAL,
    effective_contract_digest_for=_EFFECTIVE_CONTRACT_DIGEST_FOR,
)


def repository_approval_record(
    _load: Callable[
        [], Increment5AApprovalAttestation | None
    ] = _LOAD_REPOSITORY_APPROVAL,
) -> Increment5AApprovalAttestation | None:
    """Return only the digest-anchored repository owner record."""

    return _load()


def require_repository_approval_record(
    _load: Callable[
        [], Increment5AApprovalAttestation | None
    ] = _LOAD_REPOSITORY_APPROVAL,
) -> Increment5AApprovalAttestation:
    approval = _load()
    if approval is None:
        raise Increment5ProfileError(
            "PRODUCTION is not authorized without the admitted repository "
            "owner approval record"
        )
    return approval


def repository_main_qualification_record(
    _load: Callable[
        [], Increment5AMainQualificationRecord | None
    ] = _LOAD_MAIN_QUALIFICATION,
) -> Increment5AMainQualificationRecord | None:
    """Return only the authenticated post-merge exact-main admission."""

    return _load()


def require_repository_main_qualification_record(
    _load: Callable[
        [], Increment5AMainQualificationRecord | None
    ] = _LOAD_MAIN_QUALIFICATION,
) -> Increment5AMainQualificationRecord:
    qualification = _load()
    if qualification is None:
        raise Increment5ProfileError(
            "Increment 5 implementation remains blocked until the admitted "
            "post-merge exact-main qualification record exists"
        )
    return qualification


def decision_authority() -> Increment5ADecisionAuthority:
    """Return the repository-backed status facade."""

    return INCREMENT_5A_DECISION_AUTHORITY


del _name
