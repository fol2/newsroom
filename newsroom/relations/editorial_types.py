from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from newsroom.authority.canonical import digest_canonical, validate_sha256_digest
from newsroom.authority.types import UUIDv4Id, require_scope, require_token


class EditorialRelationAuthorityError(RuntimeError):
    """Base error for governed editorial-relation authority."""


class EditorialRelationContractError(ValueError):
    """A typed editorial-relation value or contract is malformed."""


class EditorialRelationStateError(EditorialRelationAuthorityError):
    """Current retained authority cannot support the requested transition."""


class EditorialRelationIdentifierReuse(EditorialRelationStateError):
    """A retained identity is being reused for different immutable semantics."""


class EditorialRelationSemanticCollision(EditorialRelationStateError):
    """Equivalent semantics already exist under another stable identity."""


class EditorialRelationDecisionConflict(EditorialRelationStateError):
    """Concurrent or materially incompatible relation authority conflicts."""


class EditorialRelationStaleDecision(EditorialRelationStateError):
    """A decision is not pinned to the exact current proposal/assertion head."""


class EditorialRelationRightsDenied(PermissionError, EditorialRelationAuthorityError):
    """Current source, object, entity or retention rights block relation use."""


class EditorialRelationProposalId(UUIDv4Id):
    pass


class EditorialRelationProposalVersionId(UUIDv4Id):
    pass


class EditorialRelationDecisionId(UUIDv4Id):
    pass


class EditorialRelationAssertionId(UUIDv4Id):
    pass


class EditorialRelationSupersessionId(UUIDv4Id):
    pass


class EditorialPredicateCode(StrEnum):
    SAME_EVENT_AS = "SAME_EVENT_AS"
    DEVELOPMENT_OF = "DEVELOPMENT_OF"
    SAME_PROCESS_AS = "SAME_PROCESS_AS"
    CORRECTS = "CORRECTS"
    SUPERSEDES = "SUPERSEDES"
    SUPPORTS = "SUPPORTS"
    DISPUTES = "DISPUTES"
    CONTRADICTS = "CONTRADICTS"
    ABOUT_EVENT = "ABOUT_EVENT"


class EditorialRelationEndpointKind(StrEnum):
    CANONICAL_ENTITY_VERSION = "CANONICAL_ENTITY_VERSION"
    SOURCE_REVISION = "SOURCE_REVISION"
    EVENT_HYPOTHESIS_VERSION = "EVENT_HYPOTHESIS_VERSION"
    STORY_CANDIDATE_VERSION = "STORY_CANDIDATE_VERSION"
    RELATION_ASSERTION = "RELATION_ASSERTION"


class EditorialPredicateDirectionality(StrEnum):
    DIRECTED = "DIRECTED"
    SYMMETRIC = "SYMMETRIC"


class EditorialPredicateTemporalSemantics(StrEnum):
    VALID_INTERVAL_REQUIRED = "VALID_INTERVAL_REQUIRED"
    VALID_INTERVAL_OPTIONAL = "VALID_INTERVAL_OPTIONAL"
    TIMELESS = "TIMELESS"


class EditorialRelationEvidenceKind(StrEnum):
    EXTRACTION_PROPOSAL = "EXTRACTION_PROPOSAL"
    WORKFLOW_EVENT = "WORKFLOW_EVENT"


class EditorialRelationProducerKind(StrEnum):
    DETERMINISTIC_FIXTURE = "DETERMINISTIC_FIXTURE"
    EXTRACTION_RUN = "EXTRACTION_RUN"
    AUTHORISED_OPERATOR = "AUTHORISED_OPERATOR"
    GOVERNED_WORKFLOW = "GOVERNED_WORKFLOW"


class EditorialRelationDecisionAction(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    HOLD = "HOLD"
    UNRESOLVED = "UNRESOLVED"
    INVALIDATE = "INVALIDATE"
    REVOKE = "REVOKE"
    SUPERSEDE = "SUPERSEDE"

    @property
    def is_admission(self) -> bool:
        return self in {
            EditorialRelationDecisionAction.ACCEPT,
            EditorialRelationDecisionAction.REJECT,
            EditorialRelationDecisionAction.HOLD,
            EditorialRelationDecisionAction.UNRESOLVED,
        }

    @property
    def is_lifecycle(self) -> bool:
        return not self.is_admission

    @property
    def terminal_for_proposal(self) -> bool:
        return self in {
            EditorialRelationDecisionAction.ACCEPT,
            EditorialRelationDecisionAction.REJECT,
        }


class EditorialRelationCurrentState(StrEnum):
    PROPOSED = "PROPOSED"
    HELD = "HELD"
    UNRESOLVED = "UNRESOLVED"
    REJECTED = "REJECTED"
    ADMITTED = "ADMITTED"
    INVALIDATED = "INVALIDATED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class EditorialRelationAssertionLifecycle(StrEnum):
    ACTIVE = "ACTIVE"
    INVALIDATED = "INVALIDATED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class EditorialRelationProjectionAction(StrEnum):
    UPSERT = "UPSERT"
    REMOVE = "REMOVE"


def bounded_text(
    value: str,
    *,
    field: str,
    maximum_bytes: int = 4096,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise EditorialRelationContractError(f"{field} must be canonical text")
    if not allow_empty and not value:
        raise EditorialRelationContractError(f"{field} cannot be empty")
    if len(value.encode("utf-8")) > maximum_bytes:
        raise EditorialRelationContractError(f"{field} exceeds its byte bound")
    return value


def bounded_token(value: str, *, field: str) -> str:
    try:
        return require_token(value, field=field)
    except ValueError as exc:
        raise EditorialRelationContractError(str(exc)) from exc


def bounded_scope(value: str, *, field: str) -> str:
    try:
        return require_scope(value, field=field)
    except ValueError as exc:
        raise EditorialRelationContractError(str(exc)) from exc


def bounded_int(
    value: int,
    *,
    field: str,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EditorialRelationContractError(f"{field} must be an integer")
    if value < minimum or value > maximum:
        raise EditorialRelationContractError(
            f"{field} must be between {minimum} and {maximum}"
        )
    return value


def canonical_digest(value: str, *, field: str) -> str:
    try:
        return validate_sha256_digest(value, field=field)
    except ValueError as exc:
        raise EditorialRelationContractError(str(exc)) from exc


def sorted_text_tuple(
    values: tuple[str, ...],
    *,
    field: str,
    allow_empty: bool = False,
    maximum_items: int = 64,
    maximum_item_bytes: int = 256,
) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise EditorialRelationContractError(f"{field} must be an immutable tuple")
    if not allow_empty and not values:
        raise EditorialRelationContractError(f"{field} cannot be empty")
    if len(values) > maximum_items:
        raise EditorialRelationContractError(f"{field} exceeds its item bound")
    normalized = tuple(
        bounded_text(item, field=field, maximum_bytes=maximum_item_bytes)
        for item in values
    )
    if normalized != tuple(sorted(set(normalized))):
        raise EditorialRelationContractError(f"{field} must be sorted and unique")
    return normalized


def sorted_id_tuple(
    values: tuple[UUIDv4Id, ...],
    expected_type: type[UUIDv4Id],
    *,
    field: str,
    allow_empty: bool = False,
    maximum_items: int = 128,
) -> tuple[UUIDv4Id, ...]:
    if not isinstance(values, tuple):
        raise EditorialRelationContractError(f"{field} must be an immutable tuple")
    if not allow_empty and not values:
        raise EditorialRelationContractError(f"{field} cannot be empty")
    if len(values) > maximum_items:
        raise EditorialRelationContractError(f"{field} exceeds its item bound")
    if any(not isinstance(item, expected_type) for item in values):
        raise EditorialRelationContractError(f"{field} contains an untyped identity")
    texts = tuple(str(item) for item in values)
    if texts != tuple(sorted(set(texts))):
        raise EditorialRelationContractError(f"{field} must be sorted and unique")
    return values


def canonical_registry_digest(value: object) -> str:
    return digest_canonical(value)


__all__ = [
    "EditorialPredicateCode",
    "EditorialPredicateDirectionality",
    "EditorialPredicateTemporalSemantics",
    "EditorialRelationAssertionId",
    "EditorialRelationAssertionLifecycle",
    "EditorialRelationAuthorityError",
    "EditorialRelationContractError",
    "EditorialRelationCurrentState",
    "EditorialRelationDecisionAction",
    "EditorialRelationDecisionConflict",
    "EditorialRelationDecisionId",
    "EditorialRelationEndpointKind",
    "EditorialRelationEvidenceKind",
    "EditorialRelationIdentifierReuse",
    "EditorialRelationProducerKind",
    "EditorialRelationProjectionAction",
    "EditorialRelationProposalId",
    "EditorialRelationProposalVersionId",
    "EditorialRelationRightsDenied",
    "EditorialRelationSemanticCollision",
    "EditorialRelationStaleDecision",
    "EditorialRelationStateError",
    "EditorialRelationSupersessionId",
    "bounded_int",
    "bounded_scope",
    "bounded_text",
    "bounded_token",
    "canonical_digest",
    "canonical_registry_digest",
    "sorted_id_tuple",
    "sorted_text_tuple",
]
