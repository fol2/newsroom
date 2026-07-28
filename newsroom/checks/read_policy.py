from __future__ import annotations

from dataclasses import dataclass

from newsroom.authority.canonical import digest_canonical
from newsroom.authority.types import require_scope, require_token

from .types import CheckContractError


@dataclass(frozen=True, slots=True)
class DiscoveryCheckReadPolicy:
    policy_id: str
    purpose: str
    metadata_required_scope: str
    sensitive_required_scope: str
    allowed_principal_ids: frozenset[str]
    max_results: int = 1000

    def __post_init__(self) -> None:
        require_token(self.policy_id, field="check_read_policy_id")
        require_token(self.purpose, field="check_read_purpose")
        require_scope(
            self.metadata_required_scope,
            field="check_metadata_read_scope",
        )
        require_scope(
            self.sensitive_required_scope,
            field="check_sensitive_read_scope",
        )
        if self.metadata_required_scope == self.sensitive_required_scope:
            raise CheckContractError(
                "Check metadata and sensitive reads require distinct scopes"
            )
        if (
            not isinstance(self.allowed_principal_ids, frozenset)
            or not self.allowed_principal_ids
        ):
            raise CheckContractError(
                "Check read principals must be a non-empty frozenset"
            )
        for principal_id in self.allowed_principal_ids:
            require_token(principal_id, field="check_reader_principal")
        if (
            isinstance(self.max_results, bool)
            or not isinstance(self.max_results, int)
            or self.max_results <= 0
            or self.max_results > 10_000
        ):
            raise CheckContractError(
                "Check read maximum must be between 1 and 10000"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "purpose": self.purpose,
            "metadata_required_scope": self.metadata_required_scope,
            "sensitive_required_scope": self.sensitive_required_scope,
            "allowed_principal_ids": sorted(self.allowed_principal_ids),
            "max_results": self.max_results,
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())

    def require_principal(self, principal_id: str) -> None:
        if principal_id not in self.allowed_principal_ids:
            raise PermissionError(
                "Check reader principal is outside the read policy"
            )

    def require_limit(self, limit: int) -> None:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit <= 0
            or limit > self.max_results
        ):
            raise PermissionError("Check read limit exceeds the read policy")


__all__ = ["DiscoveryCheckReadPolicy"]
