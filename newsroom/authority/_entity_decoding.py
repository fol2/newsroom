from __future__ import annotations

from typing import Any, Callable

from newsroom.authority.persistence import AuthorityPersistenceError
from newsroom.entities.models import (
    EntityMentionAdmissionRequest,
    EntityResolutionDecisionRequest,
    EntityResolutionProposalRequest,
)
from newsroom.entities.types import (
    CanonicalEntityId,
    CanonicalEntityVersionId,
    EntityAliasId,
    EntityAliasKind,
    EntityKind,
    EntityMentionId,
    EntityResolutionDecisionAction,
    EntityResolutionDecisionId,
    EntityResolutionProposalId,
    EntityResolutionProposalKind,
    EntityResolutionProposalVersionId,
    EntityScript,
)
from newsroom.extraction.types import ProposalEnvelopeId


def _object(value: object, *, identity: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise AuthorityPersistenceError(f"{identity} must be a canonical object")
    return value


def _id(value: object, parser: Callable[[str], Any], *, field: str) -> Any:
    if not isinstance(value, str):
        raise AuthorityPersistenceError(f"{field} must be text")
    try:
        return parser(value)
    except (TypeError, ValueError) as exc:
        raise AuthorityPersistenceError(f"{field} is invalid") from exc


def _optional_id(value: object, parser: Callable[[str], Any], *, field: str) -> Any:
    return None if value is None else _id(value, parser, field=field)


def _enum(value: object, enum_type: type, *, field: str) -> Any:
    if not isinstance(value, str):
        raise AuthorityPersistenceError(f"{field} must be text")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise AuthorityPersistenceError(f"{field} is invalid") from exc


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise AuthorityPersistenceError(f"{field} must be text")
    return value


def _integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AuthorityPersistenceError(f"{field} must be an integer")
    return value


def _optional_integer(value: object, *, field: str) -> int | None:
    return None if value is None else _integer(value, field=field)


def _strings(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise AuthorityPersistenceError(f"{field} must be a text array")
    return tuple(value)


def _require_keys(value: dict[str, Any], keys: frozenset[str], *, identity: str) -> None:
    if frozenset(value) != keys:
        raise AuthorityPersistenceError(f"{identity} fields differ from the contract")


def decode_entity_mention_request(
    value: object, *, idempotency_key: str
) -> EntityMentionAdmissionRequest:
    item = _object(value, identity="entity mention request")
    keys = frozenset(
        {
            "mention_id",
            "source_proposal_id",
            "expected_source_proposal_digest",
            "entity_kind",
            "language",
            "script",
            "normalized_text",
            "normalization_contract_digest",
        }
    )
    _require_keys(item, keys, identity="entity mention request")
    request = EntityMentionAdmissionRequest(
        mention_id=_id(item["mention_id"], EntityMentionId.parse, field="mention_id"),
        source_proposal_id=_id(
            item["source_proposal_id"], ProposalEnvelopeId.parse, field="source_proposal_id"
        ),
        expected_source_proposal_digest=_text(
            item["expected_source_proposal_digest"],
            field="expected_source_proposal_digest",
        ),
        entity_kind=_enum(item["entity_kind"], EntityKind, field="entity_kind"),
        language=_text(item["language"], field="language"),
        script=_enum(item["script"], EntityScript, field="script"),
        normalized_text=_text(item["normalized_text"], field="normalized_text"),
        normalization_contract_digest=_text(
            item["normalization_contract_digest"],
            field="normalization_contract_digest",
        ),
        idempotency_key=idempotency_key,
    )
    if request.canonical_value() != item:
        raise AuthorityPersistenceError("entity mention request is not canonical")
    return request


def decode_entity_proposal_request(
    value: object, *, idempotency_key: str
) -> EntityResolutionProposalRequest:
    item = _object(value, identity="entity resolution proposal request")
    keys = frozenset(
        {
            "proposal_id",
            "proposal_version_id",
            "version_number",
            "expected_previous_version_id",
            "source_proposal_id",
            "expected_source_proposal_digest",
            "kind",
            "subject_mention_id",
            "object_mention_id",
            "candidate_entity_id",
            "candidate_entity_version_id",
            "confidence_basis_points",
            "uncertainty_codes",
            "basis_codes",
        }
    )
    _require_keys(item, keys, identity="entity resolution proposal request")
    request = EntityResolutionProposalRequest(
        proposal_id=_id(
            item["proposal_id"], EntityResolutionProposalId.parse, field="proposal_id"
        ),
        proposal_version_id=_id(
            item["proposal_version_id"],
            EntityResolutionProposalVersionId.parse,
            field="proposal_version_id",
        ),
        version_number=_integer(item["version_number"], field="version_number"),
        expected_previous_version_id=_optional_id(
            item["expected_previous_version_id"],
            EntityResolutionProposalVersionId.parse,
            field="expected_previous_version_id",
        ),
        source_proposal_id=_id(
            item["source_proposal_id"], ProposalEnvelopeId.parse, field="source_proposal_id"
        ),
        expected_source_proposal_digest=_text(
            item["expected_source_proposal_digest"],
            field="expected_source_proposal_digest",
        ),
        kind=_enum(item["kind"], EntityResolutionProposalKind, field="kind"),
        subject_mention_id=_id(
            item["subject_mention_id"], EntityMentionId.parse, field="subject_mention_id"
        ),
        object_mention_id=_optional_id(
            item["object_mention_id"], EntityMentionId.parse, field="object_mention_id"
        ),
        candidate_entity_id=_optional_id(
            item["candidate_entity_id"], CanonicalEntityId.parse, field="candidate_entity_id"
        ),
        candidate_entity_version_id=_optional_id(
            item["candidate_entity_version_id"],
            CanonicalEntityVersionId.parse,
            field="candidate_entity_version_id",
        ),
        confidence_basis_points=_optional_integer(
            item["confidence_basis_points"], field="confidence_basis_points"
        ),
        uncertainty_codes=_strings(item["uncertainty_codes"], field="uncertainty_codes"),
        basis_codes=_strings(item["basis_codes"], field="basis_codes"),
        idempotency_key=idempotency_key,
    )
    if request.canonical_value() != item:
        raise AuthorityPersistenceError("entity resolution proposal request is not canonical")
    return request


def decode_entity_decision_request(
    value: object, *, idempotency_key: str
) -> EntityResolutionDecisionRequest:
    item = _object(value, identity="entity resolution decision request")
    keys = frozenset(
        {
            "proposal_id",
            "expected_proposal_version_id",
            "expected_proposal_digest",
            "action",
            "expected_decision_version",
            "expected_previous_decision_id",
            "accepted_entity_id",
            "accepted_entity_version_id",
            "alias_id",
            "alias_kind",
            "reason_code",
            "decision_policy_version",
        }
    )
    _require_keys(item, keys, identity="entity resolution decision request")
    request = EntityResolutionDecisionRequest(
        proposal_id=_id(
            item["proposal_id"], EntityResolutionProposalId.parse, field="proposal_id"
        ),
        expected_proposal_version_id=_id(
            item["expected_proposal_version_id"],
            EntityResolutionProposalVersionId.parse,
            field="expected_proposal_version_id",
        ),
        expected_proposal_digest=_text(
            item["expected_proposal_digest"], field="expected_proposal_digest"
        ),
        action=_enum(
            item["action"], EntityResolutionDecisionAction, field="action"
        ),
        expected_decision_version=_integer(
            item["expected_decision_version"], field="expected_decision_version"
        ),
        expected_previous_decision_id=_optional_id(
            item["expected_previous_decision_id"],
            EntityResolutionDecisionId.parse,
            field="expected_previous_decision_id",
        ),
        accepted_entity_id=_optional_id(
            item["accepted_entity_id"], CanonicalEntityId.parse, field="accepted_entity_id"
        ),
        accepted_entity_version_id=_optional_id(
            item["accepted_entity_version_id"],
            CanonicalEntityVersionId.parse,
            field="accepted_entity_version_id",
        ),
        alias_id=_optional_id(item["alias_id"], EntityAliasId.parse, field="alias_id"),
        alias_kind=(
            None
            if item["alias_kind"] is None
            else _enum(item["alias_kind"], EntityAliasKind, field="alias_kind")
        ),
        reason_code=_text(item["reason_code"], field="reason_code"),
        decision_policy_version=_text(
            item["decision_policy_version"], field="decision_policy_version"
        ),
        idempotency_key=idempotency_key,
    )
    if request.canonical_value() != item:
        raise AuthorityPersistenceError("entity resolution decision request is not canonical")
    return request


__all__ = [
    "decode_entity_decision_request",
    "decode_entity_mention_request",
    "decode_entity_proposal_request",
]
