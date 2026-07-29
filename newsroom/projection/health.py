from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

from newsroom.authority.types import UtcTimestamp, require_token
from newsroom.sources.types import (
    CheckOutcomeId,
    CoverageContribution,
    CoverageResponsibility,
    PortfolioFunction,
    SourceDefinitionId,
    SourceDefinitionVersionId,
)

from .models import ProjectionGenerationId, ProjectionGenerationState

if TYPE_CHECKING:
    from newsroom.checks.types import CheckOutcomeKind, QuarantineDisposition


class DiscoveryHealthContractError(ValueError):
    """Raised when health evidence or a deterministic assessment is malformed."""


class DiscoveryHealthDimension(StrEnum):
    SOURCE_ACCESS = "SOURCE_ACCESS"
    SOURCE_CONTRACT = "SOURCE_CONTRACT"
    PARSER = "PARSER"
    CHECK_EXECUTION = "CHECK_EXECUTION"
    OBSERVATION_FRESHNESS = "OBSERVATION_FRESHNESS"
    SEMANTIC_LINEAGE = "SEMANTIC_LINEAGE"
    PROJECTION = "PROJECTION"
    COVERAGE_AVAILABILITY = "COVERAGE_AVAILABILITY"


class DiscoveryHealthState(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    QUARANTINED = "QUARANTINED"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class HealthPolicy:
    policy_id: str
    policy_version: str
    freshness_window_seconds: int

    def __post_init__(self) -> None:
        require_token(self.policy_id, field="health_policy_id")
        require_token(self.policy_version, field="health_policy_version")
        if (
            isinstance(self.freshness_window_seconds, bool)
            or not isinstance(self.freshness_window_seconds, int)
            or self.freshness_window_seconds <= 0
        ):
            raise DiscoveryHealthContractError(
                "health freshness window must be a positive integer"
            )


@dataclass(frozen=True, slots=True)
class HealthEvidenceReference:
    evidence_type: str
    identifier: str
    observed_at: UtcTimestamp
    digest: str | None = None

    def __post_init__(self) -> None:
        require_token(self.evidence_type, field="health_evidence_type")
        if (
            not isinstance(self.identifier, str)
            or not self.identifier
            or self.identifier != self.identifier.strip()
            or len(self.identifier.encode("utf-8")) > 512
        ):
            raise DiscoveryHealthContractError(
                "health evidence identity must be bounded canonical text"
            )
        if not isinstance(self.observed_at, UtcTimestamp):
            raise DiscoveryHealthContractError(
                "health evidence time must be a typed UTC timestamp"
            )
        if self.digest is not None and (
            not isinstance(self.digest, str)
            or not self.digest.startswith("sha256:")
            or len(self.digest) != 71
            or self.digest.lower() != self.digest
        ):
            raise DiscoveryHealthContractError(
                "health evidence digest must be canonical SHA-256"
            )


@dataclass(frozen=True, slots=True)
class DiscoveryHealthAssessment:
    dimension: DiscoveryHealthDimension
    state: DiscoveryHealthState
    scope_type: str
    scope_id: str
    reason_code: str
    policy: HealthPolicy
    evidence: tuple[HealthEvidenceReference, ...]
    assessed_at: UtcTimestamp
    last_complete_observation_at: UtcTimestamp | None = None
    last_successful_observation_at: UtcTimestamp | None = None
    last_source_change_at: UtcTimestamp | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.dimension, DiscoveryHealthDimension):
            raise DiscoveryHealthContractError("health dimension must be typed")
        if not isinstance(self.state, DiscoveryHealthState):
            raise DiscoveryHealthContractError("health state must be typed")
        require_token(self.scope_type, field="health_scope_type")
        if (
            not isinstance(self.scope_id, str)
            or not self.scope_id
            or self.scope_id != self.scope_id.strip()
            or len(self.scope_id.encode("utf-8")) > 512
        ):
            raise DiscoveryHealthContractError(
                "health scope identity must be bounded canonical text"
            )
        require_token(self.reason_code, field="health_reason_code")
        if not isinstance(self.policy, HealthPolicy):
            raise DiscoveryHealthContractError("health policy must be typed")
        if not isinstance(self.assessed_at, UtcTimestamp):
            raise DiscoveryHealthContractError(
                "health assessed time must be a typed UTC timestamp"
            )
        if not isinstance(self.evidence, tuple) or len(self.evidence) > 64:
            raise DiscoveryHealthContractError(
                "health evidence must be a bounded tuple"
            )
        if any(not isinstance(item, HealthEvidenceReference) for item in self.evidence):
            raise DiscoveryHealthContractError(
                "health evidence references must be typed"
            )
        if any(
            item.observed_at.value > self.assessed_at.value
            for item in self.evidence
        ):
            raise DiscoveryHealthContractError(
                "health evidence cannot follow the assessment time"
            )
        evidence_keys = [
            (item.evidence_type, item.identifier, str(item.observed_at), item.digest)
            for item in self.evidence
        ]
        if evidence_keys != sorted(set(evidence_keys)):
            raise DiscoveryHealthContractError(
                "health evidence must be sorted and unique"
            )
        for field_name, value in (
            ("last_complete_observation_at", self.last_complete_observation_at),
            ("last_successful_observation_at", self.last_successful_observation_at),
            ("last_source_change_at", self.last_source_change_at),
        ):
            if value is not None and not isinstance(value, UtcTimestamp):
                raise DiscoveryHealthContractError(f"{field_name} must be typed")
            if value is not None and value.value > self.assessed_at.value:
                raise DiscoveryHealthContractError(
                    f"{field_name} cannot follow assessment time"
                )
        if (
            self.last_complete_observation_at is not None
            and self.last_successful_observation_at is not None
            and self.last_complete_observation_at.value
            > self.last_successful_observation_at.value
        ):
            raise DiscoveryHealthContractError(
                "complete observation cannot follow the successful observation"
            )


@dataclass(frozen=True, slots=True)
class SourceObservationHealthInput:
    definition_id: SourceDefinitionId
    definition_version_id: SourceDefinitionVersionId
    outcome_id: CheckOutcomeId | None
    outcome_kind: CheckOutcomeKind | None
    quarantine: QuarantineDisposition | None
    outcome_completed_at: UtcTimestamp | None
    last_complete_observation_at: UtcTimestamp | None
    last_successful_observation_at: UtcTimestamp | None
    last_source_change_at: UtcTimestamp | None
    rights_current: bool
    source_contract_current: bool
    semantic_lineage_valid: bool | None
    evidence: tuple[HealthEvidenceReference, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.definition_id, SourceDefinitionId):
            raise DiscoveryHealthContractError("source definition ID must be typed")
        if not isinstance(self.definition_version_id, SourceDefinitionVersionId):
            raise DiscoveryHealthContractError(
                "source definition version ID must be typed"
            )
        if (self.outcome_id is None) != (self.outcome_kind is None):
            raise DiscoveryHealthContractError(
                "Check outcome identity and kind must move together"
            )
        if self.outcome_id is not None and not isinstance(
            self.outcome_id, CheckOutcomeId
        ):
            raise DiscoveryHealthContractError("Check outcome ID must be typed")
        if self.outcome_kind is not None:
            from newsroom.checks.types import CheckOutcomeKind as _CheckOutcomeKind

            if not isinstance(self.outcome_kind, _CheckOutcomeKind):
                raise DiscoveryHealthContractError("Check outcome kind must be typed")
        if self.quarantine is not None:
            from newsroom.checks.types import (
                QuarantineDisposition as _QuarantineDisposition,
            )

            if not isinstance(self.quarantine, _QuarantineDisposition):
                raise DiscoveryHealthContractError("quarantine state must be typed")
        if self.outcome_id is None and (
            self.quarantine is not None or self.outcome_completed_at is not None
        ):
            raise DiscoveryHealthContractError(
                "outcome evidence cannot exist without an outcome"
            )
        for field_name, value in (
            ("outcome_completed_at", self.outcome_completed_at),
            ("last_complete_observation_at", self.last_complete_observation_at),
            ("last_successful_observation_at", self.last_successful_observation_at),
            ("last_source_change_at", self.last_source_change_at),
        ):
            if value is not None and not isinstance(value, UtcTimestamp):
                raise DiscoveryHealthContractError(f"{field_name} must be typed")
        if not isinstance(self.rights_current, bool):
            raise DiscoveryHealthContractError("rights currentness must be boolean")
        if not isinstance(self.source_contract_current, bool):
            raise DiscoveryHealthContractError(
                "source contract currentness must be boolean"
            )
        if self.semantic_lineage_valid is not None and not isinstance(
            self.semantic_lineage_valid, bool
        ):
            raise DiscoveryHealthContractError(
                "semantic lineage validity must be boolean or unknown"
            )
        if not isinstance(self.evidence, tuple):
            raise DiscoveryHealthContractError("source health evidence must be a tuple")


@dataclass(frozen=True, slots=True)
class ProjectionHealthInput:
    family_id: str
    generation_id: ProjectionGenerationId | None
    generation_state: ProjectionGenerationState | None
    service_available: bool | None
    query_valid: bool | None
    contracts_current: bool | None
    reconciliation_valid: bool | None
    contiguous_ledger_seq: int
    authority_watermark_ledger_seq: int
    open_gap_count: int
    dead_letter_count: int
    evidence: tuple[HealthEvidenceReference, ...] = ()

    def __post_init__(self) -> None:
        require_token(self.family_id, field="projection_health_family_id")
        if (self.generation_id is None) != (self.generation_state is None):
            raise DiscoveryHealthContractError(
                "projection generation identity and state must move together"
            )
        if self.generation_id is not None and not isinstance(
            self.generation_id, ProjectionGenerationId
        ):
            raise DiscoveryHealthContractError(
                "projection generation identity must be typed"
            )
        if self.generation_state is not None and not isinstance(
            self.generation_state, ProjectionGenerationState
        ):
            raise DiscoveryHealthContractError(
                "projection generation state must be typed"
            )
        for field_name, value in (
            ("service_available", self.service_available),
            ("query_valid", self.query_valid),
            ("contracts_current", self.contracts_current),
            ("reconciliation_valid", self.reconciliation_valid),
        ):
            if value is not None and not isinstance(value, bool):
                raise DiscoveryHealthContractError(f"{field_name} must be boolean")
        for field_name, value in (
            ("contiguous_ledger_seq", self.contiguous_ledger_seq),
            ("authority_watermark_ledger_seq", self.authority_watermark_ledger_seq),
            ("open_gap_count", self.open_gap_count),
            ("dead_letter_count", self.dead_letter_count),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise DiscoveryHealthContractError(
                    f"{field_name} must be a non-negative integer"
                )
        # Projection-authority events share the same immutable ledger as source
        # authority.  A contiguous projection checkpoint may therefore advance
        # beyond the latest non-projection authority event while recording its
        # own delivery, validation and promotion evidence.  Lag is the only
        # invalid health direction: the assessor compares ``<`` below.
        if not isinstance(self.evidence, tuple):
            raise DiscoveryHealthContractError(
                "projection health evidence must be a tuple"
            )


@dataclass(frozen=True, slots=True)
class CoveragePathHealthInput:
    path_id: str
    obligation_id: str
    responsibility: CoverageResponsibility
    contribution: CoverageContribution
    portfolio_functions: frozenset[PortfolioFunction]
    state: DiscoveryHealthState
    qualifies_as_substitute: bool = False
    evidence: tuple[HealthEvidenceReference, ...] = ()

    def __post_init__(self) -> None:
        require_token(self.path_id, field="coverage_path_id")
        require_token(self.obligation_id, field="coverage_obligation_id")
        if not isinstance(self.responsibility, CoverageResponsibility):
            raise DiscoveryHealthContractError(
                "coverage responsibility must be typed"
            )
        if not isinstance(self.contribution, CoverageContribution):
            raise DiscoveryHealthContractError("coverage contribution must be typed")
        if not isinstance(self.portfolio_functions, frozenset) or not all(
            isinstance(value, PortfolioFunction) for value in self.portfolio_functions
        ):
            raise DiscoveryHealthContractError(
                "coverage portfolio functions must be a typed frozenset"
            )
        if not isinstance(self.state, DiscoveryHealthState):
            raise DiscoveryHealthContractError("coverage path state must be typed")
        if not isinstance(self.qualifies_as_substitute, bool):
            raise DiscoveryHealthContractError(
                "coverage substitution flag must be boolean"
            )
        if not isinstance(self.evidence, tuple):
            raise DiscoveryHealthContractError("coverage evidence must be a tuple")


def _assessment(
    *,
    dimension: DiscoveryHealthDimension,
    state: DiscoveryHealthState,
    scope_type: str,
    scope_id: str,
    reason_code: str,
    policy: HealthPolicy,
    evidence: tuple[HealthEvidenceReference, ...],
    assessed_at: UtcTimestamp,
    source: SourceObservationHealthInput | None = None,
) -> DiscoveryHealthAssessment:
    return DiscoveryHealthAssessment(
        dimension=dimension,
        state=state,
        scope_type=scope_type,
        scope_id=scope_id,
        reason_code=reason_code,
        policy=policy,
        evidence=tuple(
            sorted(
                set(evidence),
                key=lambda item: (
                    item.evidence_type,
                    item.identifier,
                    str(item.observed_at),
                    item.digest or "",
                ),
            )
        ),
        assessed_at=assessed_at,
        last_complete_observation_at=(
            source.last_complete_observation_at if source is not None else None
        ),
        last_successful_observation_at=(
            source.last_successful_observation_at if source is not None else None
        ),
        last_source_change_at=(
            source.last_source_change_at if source is not None else None
        ),
    )


def assess_source_health(
    source: SourceObservationHealthInput,
    *,
    policy: HealthPolicy,
    assessed_at: UtcTimestamp,
) -> tuple[DiscoveryHealthAssessment, ...]:
    if not isinstance(source, SourceObservationHealthInput):
        raise TypeError("source health assessment requires typed input")
    if not isinstance(policy, HealthPolicy) or not isinstance(
        assessed_at, UtcTimestamp
    ):
        raise TypeError("source health assessment requires typed policy and time")

    scope_id = str(source.definition_version_id)
    assessments: list[DiscoveryHealthAssessment] = []

    contract_state = (
        DiscoveryHealthState.HEALTHY
        if source.source_contract_current and source.rights_current
        else DiscoveryHealthState.BLOCKED
    )
    contract_reason = (
        "SOURCE_CONTRACT_CURRENT"
        if contract_state is DiscoveryHealthState.HEALTHY
        else (
            "SOURCE_RIGHTS_NOT_CURRENT"
            if not source.rights_current
            else "SOURCE_CONTRACT_NOT_CURRENT"
        )
    )
    assessments.append(
        _assessment(
            dimension=DiscoveryHealthDimension.SOURCE_CONTRACT,
            state=contract_state,
            scope_type="SOURCE_DEFINITION_VERSION",
            scope_id=scope_id,
            reason_code=contract_reason,
            policy=policy,
            evidence=source.evidence,
            assessed_at=assessed_at,
            source=source,
        )
    )

    if source.semantic_lineage_valid is None:
        semantic_state = DiscoveryHealthState.UNKNOWN
        semantic_reason = "SEMANTIC_LINEAGE_NOT_ASSESSED"
    elif source.semantic_lineage_valid:
        semantic_state = DiscoveryHealthState.HEALTHY
        semantic_reason = "SEMANTIC_LINEAGE_VALID"
    else:
        semantic_state = DiscoveryHealthState.QUARANTINED
        semantic_reason = "SEMANTIC_LINEAGE_INVALID"
    assessments.append(
        _assessment(
            dimension=DiscoveryHealthDimension.SEMANTIC_LINEAGE,
            state=semantic_state,
            scope_type="SOURCE_DEFINITION_VERSION",
            scope_id=scope_id,
            reason_code=semantic_reason,
            policy=policy,
            evidence=source.evidence,
            assessed_at=assessed_at,
            source=source,
        )
    )

    kind = source.outcome_kind.value if source.outcome_kind is not None else None
    quarantine = source.quarantine.value if source.quarantine is not None else None
    if kind is None:
        access_state = parser_state = check_state = DiscoveryHealthState.UNKNOWN
        access_reason = "SOURCE_ACCESS_NOT_ATTEMPTED"
        parser_reason = "PARSER_NOT_ATTEMPTED"
        check_reason = "CHECK_NOT_ATTEMPTED"
    elif quarantine in {"REVIEW", "QUARANTINE"} or kind == "QUARANTINED_DISABLED":
        access_state = parser_state = check_state = DiscoveryHealthState.QUARANTINED
        access_reason = parser_reason = check_reason = "OUTCOME_QUARANTINED"
    elif kind in {"BLOCKED", "UNAUTHORISED"}:
        access_state = DiscoveryHealthState.BLOCKED
        parser_state = DiscoveryHealthState.UNKNOWN
        check_state = DiscoveryHealthState.BLOCKED
        access_reason = "SOURCE_ACCESS_BLOCKED"
        parser_reason = "PARSER_NOT_REACHED"
        check_reason = "CHECK_BLOCKED"
    elif kind in {
        "TRANSPORT_FAILED",
        "NOT_FOUND",
        "GONE",
    }:
        access_state = DiscoveryHealthState.UNAVAILABLE
        parser_state = DiscoveryHealthState.UNKNOWN
        check_state = DiscoveryHealthState.DEGRADED
        access_reason = "SOURCE_ACCESS_UNAVAILABLE"
        parser_reason = "PARSER_NOT_REACHED"
        check_reason = "CHECK_SOURCE_FAILURE"
    elif kind in {"RATE_LIMITED", "REDIRECTED"}:
        access_state = DiscoveryHealthState.DEGRADED
        parser_state = DiscoveryHealthState.UNKNOWN
        check_state = DiscoveryHealthState.DEGRADED
        access_reason = "SOURCE_ACCESS_DEGRADED"
        parser_reason = "PARSER_NOT_REACHED"
        check_reason = "CHECK_SOURCE_DEGRADED"
    elif kind in {"MALFORMED", "SHAPE_DRIFT"}:
        access_state = DiscoveryHealthState.HEALTHY
        parser_state = DiscoveryHealthState.BLOCKED
        check_state = DiscoveryHealthState.DEGRADED
        access_reason = "SOURCE_ACCESS_SUCCEEDED"
        parser_reason = "PARSER_CONTRACT_FAILURE"
        check_reason = "CHECK_PARSER_FAILURE"
    elif kind in {
        "SUCCESS_PARTIAL",
        "SUCCESS_TRUNCATED",
    }:
        access_state = DiscoveryHealthState.HEALTHY
        parser_state = DiscoveryHealthState.DEGRADED
        check_state = DiscoveryHealthState.DEGRADED
        access_reason = "SOURCE_ACCESS_SUCCEEDED"
        parser_reason = "PARSER_INCOMPLETE"
        check_reason = "CHECK_INCOMPLETE"
    else:
        access_state = parser_state = check_state = DiscoveryHealthState.HEALTHY
        access_reason = "SOURCE_ACCESS_SUCCEEDED"
        parser_reason = "PARSER_SUCCEEDED"
        check_reason = "CHECK_SUCCEEDED"

    for dimension, state, reason in (
        (DiscoveryHealthDimension.SOURCE_ACCESS, access_state, access_reason),
        (DiscoveryHealthDimension.PARSER, parser_state, parser_reason),
        (DiscoveryHealthDimension.CHECK_EXECUTION, check_state, check_reason),
    ):
        assessments.append(
            _assessment(
                dimension=dimension,
                state=state,
                scope_type="SOURCE_DEFINITION_VERSION",
                scope_id=scope_id,
                reason_code=reason,
                policy=policy,
                evidence=source.evidence,
                assessed_at=assessed_at,
                source=source,
            )
        )

    if source.last_successful_observation_at is None:
        freshness_state = DiscoveryHealthState.UNKNOWN
        freshness_reason = "SUCCESSFUL_OBSERVATION_NOT_ESTABLISHED"
    else:
        age = assessed_at.value - source.last_successful_observation_at.value
        if age > timedelta(seconds=policy.freshness_window_seconds):
            freshness_state = DiscoveryHealthState.STALE
            freshness_reason = "SUCCESSFUL_OBSERVATION_STALE"
        else:
            freshness_state = DiscoveryHealthState.HEALTHY
            freshness_reason = "SUCCESSFUL_OBSERVATION_CURRENT"
    assessments.append(
        _assessment(
            dimension=DiscoveryHealthDimension.OBSERVATION_FRESHNESS,
            state=freshness_state,
            scope_type="SOURCE_DEFINITION_VERSION",
            scope_id=scope_id,
            reason_code=freshness_reason,
            policy=policy,
            evidence=source.evidence,
            assessed_at=assessed_at,
            source=source,
        )
    )
    return tuple(sorted(assessments, key=lambda item: item.dimension.value))


def assess_projection_health(
    projection: ProjectionHealthInput,
    *,
    policy: HealthPolicy,
    assessed_at: UtcTimestamp,
) -> DiscoveryHealthAssessment:
    if not isinstance(projection, ProjectionHealthInput):
        raise TypeError("projection health assessment requires typed input")
    if not isinstance(policy, HealthPolicy) or not isinstance(
        assessed_at, UtcTimestamp
    ):
        raise TypeError("projection health assessment requires typed policy and time")

    if projection.generation_id is None:
        state = DiscoveryHealthState.UNKNOWN
        reason = "PROJECTION_GENERATION_NOT_ESTABLISHED"
    elif projection.service_available is False:
        state = DiscoveryHealthState.UNAVAILABLE
        reason = "PROJECTION_SERVICE_UNAVAILABLE"
    elif projection.service_available is None:
        state = DiscoveryHealthState.UNKNOWN
        reason = "PROJECTION_SERVICE_NOT_ASSESSED"
    elif projection.contracts_current is False:
        state = DiscoveryHealthState.BLOCKED
        reason = "PROJECTION_CONTRACT_MISMATCH"
    elif projection.reconciliation_valid is False or projection.query_valid is False:
        state = DiscoveryHealthState.QUARANTINED
        reason = "PROJECTION_VALIDATION_FAILED"
    elif projection.open_gap_count or projection.dead_letter_count:
        state = DiscoveryHealthState.BLOCKED
        reason = "PROJECTION_AUTHORITY_GAP"
    elif projection.contiguous_ledger_seq < projection.authority_watermark_ledger_seq:
        state = DiscoveryHealthState.STALE
        reason = "PROJECTION_WATERMARK_LAG"
    elif projection.generation_state is not ProjectionGenerationState.ACTIVE:
        state = DiscoveryHealthState.DEGRADED
        reason = "PROJECTION_GENERATION_NOT_ACTIVE"
    elif (
        projection.contracts_current is None
        or projection.reconciliation_valid is None
        or projection.query_valid is None
    ):
        state = DiscoveryHealthState.UNKNOWN
        reason = "PROJECTION_VALIDATION_NOT_ESTABLISHED"
    else:
        state = DiscoveryHealthState.HEALTHY
        reason = "PROJECTION_ACTIVE_AND_RECONCILED"
    return _assessment(
        dimension=DiscoveryHealthDimension.PROJECTION,
        state=state,
        scope_type="PROJECTION_FAMILY",
        scope_id=projection.family_id,
        reason_code=reason,
        policy=policy,
        evidence=projection.evidence,
        assessed_at=assessed_at,
    )


def summarize_source_path_state(
    assessments: tuple[DiscoveryHealthAssessment, ...],
) -> DiscoveryHealthState:
    """Collapse dimension-specific source evidence for coverage-path routing.

    The collapse is deliberately conservative: semantic quarantine and explicit
    contract blocks outrank availability, while a fresh successful source is
    healthy only when every required source dimension is positively healthy.
    """

    if not isinstance(assessments, tuple) or not assessments:
        raise DiscoveryHealthContractError(
            "source path state requires typed health assessments"
        )
    if any(not isinstance(item, DiscoveryHealthAssessment) for item in assessments):
        raise DiscoveryHealthContractError(
            "source path state assessments must be typed"
        )
    by_dimension = {item.dimension: item.state for item in assessments}
    if len(by_dimension) != len(assessments):
        raise DiscoveryHealthContractError(
            "source path state dimensions must be unique"
        )
    required = {
        DiscoveryHealthDimension.SOURCE_ACCESS,
        DiscoveryHealthDimension.SOURCE_CONTRACT,
        DiscoveryHealthDimension.PARSER,
        DiscoveryHealthDimension.CHECK_EXECUTION,
        DiscoveryHealthDimension.OBSERVATION_FRESHNESS,
        DiscoveryHealthDimension.SEMANTIC_LINEAGE,
    }
    if not required <= by_dimension.keys():
        raise DiscoveryHealthContractError(
            "source path state lacks required health dimensions"
        )
    states = tuple(by_dimension[item] for item in sorted(required, key=lambda value: value.value))
    if DiscoveryHealthState.QUARANTINED in states:
        return DiscoveryHealthState.QUARANTINED
    if DiscoveryHealthState.BLOCKED in states:
        return DiscoveryHealthState.BLOCKED
    if DiscoveryHealthState.UNAVAILABLE in states:
        return DiscoveryHealthState.UNAVAILABLE
    if DiscoveryHealthState.STALE in states:
        return DiscoveryHealthState.STALE
    if DiscoveryHealthState.DEGRADED in states:
        return DiscoveryHealthState.DEGRADED
    if all(state is DiscoveryHealthState.HEALTHY for state in states):
        return DiscoveryHealthState.HEALTHY
    return DiscoveryHealthState.UNKNOWN


def assess_coverage_availability(
    paths: tuple[CoveragePathHealthInput, ...],
    *,
    obligation_id: str,
    policy: HealthPolicy,
    assessed_at: UtcTimestamp,
) -> DiscoveryHealthAssessment:
    require_token(obligation_id, field="coverage_obligation_id")
    if not isinstance(paths, tuple):
        raise DiscoveryHealthContractError(
            "coverage assessment paths must be a tuple"
        )
    if any(not isinstance(item, CoveragePathHealthInput) for item in paths):
        raise DiscoveryHealthContractError("coverage paths must be typed")
    if any(item.obligation_id != obligation_id for item in paths):
        raise DiscoveryHealthContractError(
            "coverage paths must belong to the assessed obligation"
        )
    if len({item.path_id for item in paths}) != len(paths):
        raise DiscoveryHealthContractError("coverage path identities must be unique")

    active_anchors = tuple(
        item
        for item in paths
        if item.responsibility is CoverageResponsibility.ACTIVE
        and PortfolioFunction.ANCHOR in item.portfolio_functions
    )
    substitutes = tuple(
        item
        for item in paths
        if item.qualifies_as_substitute
        and PortfolioFunction.EXPLICIT_CONTINGENCY in item.portfolio_functions
    )
    healthy_states = {DiscoveryHealthState.HEALTHY}
    degraded_states = {DiscoveryHealthState.DEGRADED, DiscoveryHealthState.STALE}

    if not active_anchors:
        state = DiscoveryHealthState.UNKNOWN
        reason = "COVERAGE_ANCHOR_NOT_DEFINED"
    elif any(item.state in healthy_states for item in active_anchors):
        state = DiscoveryHealthState.HEALTHY
        reason = "COVERAGE_ACTIVE_ANCHOR_AVAILABLE"
    elif any(item.state in healthy_states for item in substitutes):
        state = DiscoveryHealthState.DEGRADED
        reason = "COVERAGE_EXPLICIT_CONTINGENCY_ACTIVE"
    elif any(item.state in degraded_states for item in active_anchors):
        state = DiscoveryHealthState.DEGRADED
        reason = "COVERAGE_ACTIVE_ANCHOR_DEGRADED"
    elif any(
        item.state is DiscoveryHealthState.QUARANTINED for item in active_anchors
    ):
        state = DiscoveryHealthState.QUARANTINED
        reason = "COVERAGE_ACTIVE_ANCHOR_QUARANTINED"
    elif any(item.state is DiscoveryHealthState.BLOCKED for item in active_anchors):
        state = DiscoveryHealthState.BLOCKED
        reason = "COVERAGE_ACTIVE_ANCHOR_BLOCKED"
    elif all(
        item.state is DiscoveryHealthState.UNAVAILABLE for item in active_anchors
    ):
        state = DiscoveryHealthState.BLOCKED
        reason = "COVERAGE_ACTIVE_ANCHOR_UNAVAILABLE"
    else:
        state = DiscoveryHealthState.UNKNOWN
        reason = "COVERAGE_ACTIVE_ANCHOR_UNKNOWN"

    evidence = tuple(
        item
        for path in sorted(paths, key=lambda value: value.path_id)
        for item in path.evidence
    )
    return _assessment(
        dimension=DiscoveryHealthDimension.COVERAGE_AVAILABILITY,
        state=state,
        scope_type="COVERAGE_OBLIGATION",
        scope_id=obligation_id,
        reason_code=reason,
        policy=policy,
        evidence=evidence,
        assessed_at=assessed_at,
    )


__all__ = [
    "CoveragePathHealthInput",
    "DiscoveryHealthAssessment",
    "DiscoveryHealthContractError",
    "DiscoveryHealthDimension",
    "DiscoveryHealthState",
    "HealthEvidenceReference",
    "HealthPolicy",
    "ProjectionHealthInput",
    "SourceObservationHealthInput",
    "assess_coverage_availability",
    "assess_projection_health",
    "assess_source_health",
    "summarize_source_path_state",
]
