from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from newsroom.authority.auth import AuthenticationProof
from newsroom.authority.types import UtcTimestamp, require_token
from newsroom.projection.health import (
    DiscoveryHealthAssessment,
    HealthPolicy,
)
from newsroom.sources.types import SourceDefinitionId


@dataclass(frozen=True, slots=True)
class DiscoverySourceHealthReadRequest:
    definition_id: SourceDefinitionId
    policy: HealthPolicy
    assessed_at: UtcTimestamp

    def __post_init__(self) -> None:
        if not isinstance(self.definition_id, SourceDefinitionId):
            raise TypeError(
                "source health read requires a typed Source Definition ID"
            )
        if not isinstance(self.policy, HealthPolicy):
            raise TypeError("source health read requires a typed health policy")
        if not isinstance(self.assessed_at, UtcTimestamp):
            raise TypeError("source health read requires a typed assessment time")


@dataclass(frozen=True, slots=True)
class DiscoveryCoverageHealthReadRequest:
    obligation_id: str
    policy: HealthPolicy
    assessed_at: UtcTimestamp

    def __post_init__(self) -> None:
        require_token(self.obligation_id, field="coverage_obligation_id")
        if not isinstance(self.policy, HealthPolicy):
            raise TypeError("coverage health read requires a typed health policy")
        if not isinstance(self.assessed_at, UtcTimestamp):
            raise TypeError("coverage health read requires a typed assessment time")


class DiscoveryHealthAuthorityFacade:
    """Authenticated, fixed-contract source and coverage health inspection."""

    __slots__ = ("__source", "__coverage", "__eligibility")

    def __init__(
        self,
        *,
        source: Callable[
            [DiscoverySourceHealthReadRequest, AuthenticationProof],
            tuple[DiscoveryHealthAssessment, ...],
        ],
        coverage: Callable[
            [DiscoveryCoverageHealthReadRequest, AuthenticationProof],
            DiscoveryHealthAssessment,
        ],
        eligibility: Callable[[tuple[object, ...], AuthenticationProof], None],
    ) -> None:
        self.__source = source
        self.__coverage = coverage
        self.__eligibility = eligibility

    def source(
        self,
        request: DiscoverySourceHealthReadRequest,
        *,
        proof: AuthenticationProof,
    ) -> tuple[DiscoveryHealthAssessment, ...]:
        if not isinstance(request, DiscoverySourceHealthReadRequest):
            raise TypeError("source health read requires a typed request")
        return self.__source(request, proof)

    def coverage(
        self,
        request: DiscoveryCoverageHealthReadRequest,
        *,
        proof: AuthenticationProof,
    ) -> DiscoveryHealthAssessment:
        if not isinstance(request, DiscoveryCoverageHealthReadRequest):
            raise TypeError("coverage health read requires a typed request")
        return self.__coverage(request, proof)

    def require_lineage_eligible(
        self,
        identifiers: tuple[object, ...],
        *,
        proof: AuthenticationProof,
    ) -> None:
        if (
            not isinstance(identifiers, tuple)
            or not identifiers
            or len(identifiers) > 64
        ):
            raise TypeError(
                "lineage eligibility requires bounded governed identities"
            )
        self.__eligibility(identifiers, proof)


__all__ = [
    "DiscoveryCoverageHealthReadRequest",
    "DiscoveryHealthAuthorityFacade",
    "DiscoverySourceHealthReadRequest",
]
