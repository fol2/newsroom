"""Caller and rights identities bound to every Increment 5B request."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from newsroom.authority.types import UUIDv4Id

from ._retrieval_validation import (
    Increment5RetrievalContractError,
    bounded_text,
    require_bool,
    require_digest,
    require_mapping,
    sorted_unique_text,
)


class BranchRequestId(UUIDv4Id):
    """Opaque request identity with no authority or ordering effect."""


class RetrievalDataClass(StrEnum):
    REPOSITORY_FIXTURE_TEXT = "REPOSITORY_FIXTURE_TEXT"
    GOVERNED_SYNTHETIC_QUALIFICATION_TEXT = "GOVERNED_SYNTHETIC_QUALIFICATION_TEXT"
    PUBLIC_GOVERNED_SOURCE_TEXT = "PUBLIC_GOVERNED_SOURCE_TEXT"
    RIGHTS_RESTRICTED_SOURCE_TEXT = "RIGHTS_RESTRICTED_SOURCE_TEXT"
    PERSONAL_DATA = "PERSONAL_DATA"
    SECRETS_AND_CREDENTIALS = "SECRETS_AND_CREDENTIALS"
    TOMBSTONED_OR_REVOKED = "TOMBSTONED_OR_REVOKED"


@dataclass(frozen=True, slots=True)
class RetrievalCaller:
    principal_id: str
    authority_domain: str
    effective_scopes: tuple[str, ...]

    def __post_init__(self) -> None:
        bounded_text(self.principal_id, field="retrieval principal", maximum_bytes=128)
        bounded_text(self.authority_domain, field="authority domain", maximum_bytes=128)
        sorted_unique_text(
            self.effective_scopes,
            field="effective scopes",
            maximum_items=32,
            maximum_item_bytes=256,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "principal_id": self.principal_id,
            "authority_domain": self.authority_domain,
            "effective_scopes": list(self.effective_scopes),
        }

    @classmethod
    def from_value(cls, value: object) -> "RetrievalCaller":
        item = require_mapping(value, field="retrieval caller")
        return cls(
            principal_id=str(item["principal_id"]),
            authority_domain=str(item["authority_domain"]),
            effective_scopes=tuple(str(scope) for scope in item["effective_scopes"]),
        )


@dataclass(frozen=True, slots=True)
class RetrievalRightsContext:
    data_class: RetrievalDataClass
    allowed: bool
    rights_policy_version: str
    rights_decision_digest: str
    permitted_uses: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.data_class, RetrievalDataClass):
            raise Increment5RetrievalContractError("retrieval data class must be typed")
        require_bool(self.allowed, field="retrieval rights allowed")
        bounded_text(self.rights_policy_version, field="rights policy", maximum_bytes=128)
        require_digest(self.rights_decision_digest, field="rights decision digest")
        sorted_unique_text(
            self.permitted_uses,
            field="permitted uses",
            allow_empty=not self.allowed,
            maximum_items=16,
            maximum_item_bytes=128,
        )
        if not self.allowed and self.permitted_uses:
            raise Increment5RetrievalContractError(
                "denied retrieval rights cannot retain permitted uses"
            )
        if self.allowed and self.data_class in {
            RetrievalDataClass.SECRETS_AND_CREDENTIALS,
            RetrievalDataClass.TOMBSTONED_OR_REVOKED,
        }:
            raise Increment5RetrievalContractError(
                "prohibited retrieval data class cannot be marked allowed"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "data_class": self.data_class.value,
            "allowed": self.allowed,
            "rights_policy_version": self.rights_policy_version,
            "rights_decision_digest": self.rights_decision_digest,
            "permitted_uses": list(self.permitted_uses),
        }

    @classmethod
    def from_value(cls, value: object) -> "RetrievalRightsContext":
        item = require_mapping(value, field="retrieval rights context")
        return cls(
            data_class=RetrievalDataClass(item["data_class"]),
            allowed=item["allowed"],
            rights_policy_version=str(item["rights_policy_version"]),
            rights_decision_digest=str(item["rights_decision_digest"]),
            permitted_uses=tuple(str(use) for use in item["permitted_uses"]),
        )


__all__ = [
    "BranchRequestId",
    "RetrievalCaller",
    "RetrievalDataClass",
    "RetrievalRightsContext",
]
