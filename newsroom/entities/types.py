from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable
import unicodedata

from newsroom.authority.canonical import digest_canonical, validate_sha256_digest
from newsroom.authority.types import UUIDv4Id, require_scope, require_token




ENTITY_NORMALISATION_CONTRACT = {
    "contract": "entity-text-normalisation-v1",
    "unicode_form": "NFC",
    "whitespace": "unicode-split-single-space",
    "case": "unicode-casefold",
    "translation": False,
    "transliteration": False,
    "fuzzy_matching": False,
}
ENTITY_NORMALISATION_CONTRACT_DIGEST = digest_canonical(
    ENTITY_NORMALISATION_CONTRACT
)


def normalize_entity_text(value: str) -> str:
    """Return bounded deterministic text without inferring entity identity."""

    bounded_text(value, field="entity_text", maximum_bytes=4096)
    normalized = unicodedata.normalize("NFC", value)
    normalized = " ".join(normalized.split()).casefold()
    if not normalized:
        raise EntityContractError("normalized entity text cannot be empty")
    if len(normalized.encode("utf-8")) > 4096:
        raise EntityContractError("normalized entity text exceeds its byte bound")
    return normalized


def require_normalized_entity_text(value: str, *, field: str) -> str:
    bounded_text(value, field=field, maximum_bytes=4096)
    normalized = normalize_entity_text(value)
    if value != normalized:
        raise EntityContractError(
            f"{field} must equal deterministic entity normalisation"
        )
    return value


def classify_entity_script(value: str) -> EntityScript:
    bounded_text(value, field="entity_script_text", maximum_bytes=4096)
    has_latin = False
    has_han = False
    has_other_letter = False
    for character in unicodedata.normalize("NFC", value):
        if not character.isalpha():
            continue
        name = unicodedata.name(character, "")
        if "LATIN" in name:
            has_latin = True
        elif "CJK UNIFIED IDEOGRAPH" in name or "CJK COMPATIBILITY IDEOGRAPH" in name:
            has_han = True
        else:
            has_other_letter = True
    populated = sum((has_latin, has_han, has_other_letter))
    if populated > 1:
        return EntityScript.MIXED
    if has_latin:
        return EntityScript.LATIN
    if has_han:
        return EntityScript.TRADITIONAL_HAN
    return EntityScript.UNKNOWN


class EntityAuthorityError(RuntimeError):
    """Base error for governed entity-resolution authority."""


class EntityContractError(ValueError):
    """A typed entity-resolution contract or retained value is malformed."""


class EntityStateError(EntityAuthorityError):
    """Current retained authority cannot support the requested transition."""


class EntityIdentifierReuse(EntityStateError):
    """An immutable entity identity is being reused for different semantics."""


class EntitySemanticCollision(EntityStateError):
    """Equivalent semantics already exist under a different stable identity."""


class EntityDecisionConflict(EntityStateError):
    """Concurrent or materially incompatible resolution authority conflicts."""


class EntityStaleDecision(EntityStateError):
    """A decision is not pinned to the exact current proposal/entity head."""


class EntityRightsDenied(PermissionError, EntityAuthorityError):
    """Current source, passage, or governed-object rights block entity use."""


class EntityMentionId(UUIDv4Id):
    pass


class CanonicalEntityId(UUIDv4Id):
    pass


class CanonicalEntityVersionId(UUIDv4Id):
    pass


class EntityAliasId(UUIDv4Id):
    pass


class EntityResolutionProposalId(UUIDv4Id):
    pass


class EntityResolutionProposalVersionId(UUIDv4Id):
    pass


class EntityResolutionDecisionId(UUIDv4Id):
    pass


class EntityResolutionDependencyId(UUIDv4Id):
    pass


class EntityMergeDecisionId(UUIDv4Id):
    pass


class EntitySplitDecisionId(UUIDv4Id):
    pass


class EntityReversalDecisionId(UUIDv4Id):
    pass


class EntityKind(StrEnum):
    PERSON = "PERSON"
    ORGANISATION = "ORGANISATION"
    GOVERNMENT_BODY = "GOVERNMENT_BODY"
    LOCATION = "LOCATION"
    FACILITY = "FACILITY"
    PRODUCT = "PRODUCT"
    WORK = "WORK"
    EVENT = "EVENT"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class EntityScript(StrEnum):
    LATIN = "LATIN"
    TRADITIONAL_HAN = "TRADITIONAL_HAN"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


class EntityAliasKind(StrEnum):
    PRIMARY_NAME = "PRIMARY_NAME"
    ALIAS = "ALIAS"
    LEGAL_NAME = "LEGAL_NAME"
    ABBREVIATION = "ABBREVIATION"
    TRANSLATION = "TRANSLATION"
    TRANSLITERATION = "TRANSLITERATION"


class EntityResolutionProposalKind(StrEnum):
    MENTION_TO_NEW_ENTITY = "MENTION_TO_NEW_ENTITY"
    MENTION_TO_ENTITY = "MENTION_TO_ENTITY"
    MENTION_EQUIVALENCE = "MENTION_EQUIVALENCE"
    ALIAS_TO_ENTITY = "ALIAS_TO_ENTITY"


class EntityResolutionDecisionAction(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    HOLD = "HOLD"
    UNRESOLVED = "UNRESOLVED"

    @property
    def terminal(self) -> bool:
        return self in {
            EntityResolutionDecisionAction.ACCEPT,
            EntityResolutionDecisionAction.REJECT,
        }


class EntityResolutionState(StrEnum):
    PROPOSED = "PROPOSED"
    HELD = "HELD"
    UNRESOLVED = "UNRESOLVED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    REVERSED = "REVERSED"


class CanonicalEntityLifecycle(StrEnum):
    ACTIVE = "ACTIVE"
    MERGED = "MERGED"
    SPLIT = "SPLIT"
    REVERSED = "REVERSED"
    RETIRED = "RETIRED"


class EntityLineageDecisionKind(StrEnum):
    MERGE = "MERGE"
    SPLIT = "SPLIT"
    REVERSAL = "REVERSAL"


class EntityCreationDecisionKind(StrEnum):
    RESOLUTION = "RESOLUTION"
    MERGE = "MERGE"
    SPLIT = "SPLIT"


class EntityReversalTargetKind(StrEnum):
    MERGE = "MERGE"
    SPLIT = "SPLIT"


class EntityProjectionAction(StrEnum):
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
        raise EntityContractError(f"{field} must be canonical text")
    if not allow_empty and not value:
        raise EntityContractError(f"{field} cannot be empty")
    if len(value.encode("utf-8")) > maximum_bytes:
        raise EntityContractError(f"{field} exceeds its byte bound")
    return value


def bounded_token(value: str, *, field: str) -> str:
    try:
        return require_token(value, field=field)
    except ValueError as exc:
        raise EntityContractError(str(exc)) from exc


def bounded_scope(value: str, *, field: str) -> str:
    try:
        return require_scope(value, field=field)
    except ValueError as exc:
        raise EntityContractError(str(exc)) from exc


def canonical_digest(value: str, *, field: str) -> str:
    try:
        normalized = validate_sha256_digest(value, field=field)
    except ValueError as exc:
        raise EntityContractError(str(exc)) from exc
    if normalized != value:
        raise EntityContractError(f"{field} must use canonical lowercase text")
    return value


def bounded_int(
    value: int,
    *,
    field: str,
    minimum: int = 0,
    maximum: int,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > maximum
    ):
        raise EntityContractError(
            f"{field} must be an integer between {minimum} and {maximum}"
        )
    return value


def sorted_text_tuple(
    values: Iterable[str],
    *,
    field: str,
    allow_empty: bool = True,
    maximum_items: int = 32,
    maximum_item_bytes: int = 256,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise EntityContractError(f"{field} must be an iterable of text")
    items = tuple(
        sorted(
            {
                bounded_text(
                    item,
                    field=field,
                    maximum_bytes=maximum_item_bytes,
                )
                for item in values
            }
        )
    )
    if not allow_empty and not items:
        raise EntityContractError(f"{field} cannot be empty")
    if len(items) > maximum_items:
        raise EntityContractError(f"{field} exceeds its item bound")
    return items


@dataclass(frozen=True, slots=True)
class EntityReadPolicy:
    policy_id: str
    purpose: str
    proposal_required_scope: str
    admitted_required_scope: str
    projection_required_scope: str
    allowed_principal_ids: frozenset[str]
    max_results: int = 1000

    def __post_init__(self) -> None:
        bounded_token(self.policy_id, field="entity_read_policy_id")
        bounded_token(self.purpose, field="entity_read_purpose")
        scopes = (
            bounded_scope(
                self.proposal_required_scope,
                field="entity_proposal_read_scope",
            ),
            bounded_scope(
                self.admitted_required_scope,
                field="entity_admitted_read_scope",
            ),
            bounded_scope(
                self.projection_required_scope,
                field="entity_projection_read_scope",
            ),
        )
        if len(set(scopes)) != len(scopes):
            raise EntityContractError(
                "entity proposal, admitted, and projection reads need distinct scopes"
            )
        if (
            not isinstance(self.allowed_principal_ids, frozenset)
            or not self.allowed_principal_ids
        ):
            raise EntityContractError(
                "entity read principals must be a non-empty frozenset"
            )
        for principal_id in self.allowed_principal_ids:
            bounded_token(principal_id, field="entity_reader_principal")
        bounded_int(
            self.max_results,
            field="entity_read_maximum",
            minimum=1,
            maximum=10_000,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "purpose": self.purpose,
            "proposal_required_scope": self.proposal_required_scope,
            "admitted_required_scope": self.admitted_required_scope,
            "projection_required_scope": self.projection_required_scope,
            "allowed_principal_ids": sorted(self.allowed_principal_ids),
            "max_results": self.max_results,
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())

    def require_principal(self, principal_id: str) -> None:
        if principal_id not in self.allowed_principal_ids:
            raise PermissionError(
                "entity reader principal is outside the read policy"
            )

    def require_limit(self, limit: int) -> None:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit <= 0
            or limit > self.max_results
        ):
            raise PermissionError("entity read limit exceeds the read policy")
