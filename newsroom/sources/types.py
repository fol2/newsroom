from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Iterable

from newsroom.authority.canonical import digest_canonical, validate_sha256_digest
from newsroom.authority.types import (
    TimePrecision,
    UUIDv4Id,
    UtcTimestamp,
    require_scope,
    require_token,
)


class SourceAuthorityError(RuntimeError):
    """Base error for governed source-registry authority."""


class SourceContractError(ValueError):
    """A source-registry value or immutable contract is malformed."""


class SourceStateError(SourceAuthorityError):
    """Current retained source authority cannot support the requested change."""


class SourceSemanticCollision(SourceStateError):
    """A different stable identity already occupies an exact semantic identity."""


class SourceVersionConflict(SourceStateError):
    """A source version request is not pinned to the exact current version head."""


class SourceIdentifierReuse(SourceStateError):
    """A retained source identity is being reused for different semantics."""


class SourceDefinitionId(UUIDv4Id):
    pass


class SourceDefinitionVersionId(UUIDv4Id):
    pass


class SourceItemId(UUIDv4Id):
    pass


class SourceRevisionId(UUIDv4Id):
    pass


class DiscoveryRepresentationId(UUIDv4Id):
    pass


class DiscoveryOccurrenceId(UUIDv4Id):
    pass


class LocatorContinuityDecisionId(UUIDv4Id):
    pass


class CheckOutcomeId(UUIDv4Id):
    """Forward-compatible identity seam; Check authority is introduced in 3C."""


class SourceRole(StrEnum):
    ORIGINATING_AUTHORITY = "ORIGINATING_AUTHORITY"
    RESPONSIBLE_OPERATOR = "RESPONSIBLE_OPERATOR"
    PLANNED_AGENDA = "PLANNED_AGENDA"
    ESTABLISHED_MEDIA_RADAR = "ESTABLISHED_MEDIA_RADAR"
    SPECIALIST_OR_LOCAL_RADAR = "SPECIALIST_OR_LOCAL_RADAR"
    MANUAL_EDITOR_READER_LEAD = "MANUAL_EDITOR_READER_LEAD"


class PortfolioFunction(StrEnum):
    ANCHOR = "ANCHOR"
    COMPLEMENT = "COMPLEMENT"
    COMPARATOR = "COMPARATOR"
    EXPLICIT_CONTINGENCY = "EXPLICIT_CONTINGENCY"
    MANUAL_ONLY = "MANUAL_ONLY"


class CoverageResponsibility(StrEnum):
    ACTIVE = "ACTIVE"
    BEST_EFFORT = "BEST_EFFORT"
    EXPLICIT_DEFERRED_GAP = "EXPLICIT_DEFERRED_GAP"
    OPERATIONAL_RESILIENCE = "OPERATIONAL_RESILIENCE"
    EVALUATION = "EVALUATION"


class CoverageContribution(StrEnum):
    DETECTION_PATH = "DETECTION_PATH"
    OCCURRENCE_CONFIRMATION = "OCCURRENCE_CONFIRMATION"
    REVISION_VISIBILITY = "REVISION_VISIBILITY"
    URGENT_FAST_PATH = "URGENT_FAST_PATH"
    REDUNDANCY = "REDUNDANCY"
    COMPARATOR = "COMPARATOR"


class SourceDependencyKind(StrEnum):
    ORIGINATING_MATERIAL = "ORIGINATING_MATERIAL"
    SYNDICATION = "SYNDICATION"
    WIRE = "WIRE"
    PRESS_RELEASE = "PRESS_RELEASE"
    SHARED_DATA = "SHARED_DATA"
    EDITORIAL_SELECTION = "EDITORIAL_SELECTION"
    TRANSPORT = "TRANSPORT"
    AUTHENTICATION = "AUTHENTICATION"
    CREDENTIAL = "CREDENTIAL"
    OTHER = "OTHER"


class ObservationModel(StrEnum):
    APPEND_ONLY = "APPEND_ONLY"
    MUTABLE_ITEM = "MUTABLE_ITEM"
    COMPLETE_CURRENT_STATE = "COMPLETE_CURRENT_STATE"
    ROLLING_LIST = "ROLLING_LIST"
    EXPLICIT_DELTA = "EXPLICIT_DELTA"
    PLANNED_AGENDA = "PLANNED_AGENDA"


class BaselinePolicyKind(StrEnum):
    MAINTAINED_DOCUMENT = "MAINTAINED_DOCUMENT"
    BOUNDED_BACKFILL = "BOUNDED_BACKFILL"
    COMPLETE_STATE_FIRST_OBSERVED_ACTIVE = "COMPLETE_STATE_FIRST_OBSERVED_ACTIVE"
    PLANNED_AGENDA_FUTURE_ONLY = "PLANNED_AGENDA_FUTURE_ONLY"
    EXPLICIT_DELTA_SEQUENCE = "EXPLICIT_DELTA_SEQUENCE"
    MANUAL_ONLY = "MANUAL_ONLY"


class SourceLifecycleStage(StrEnum):
    RESEARCH_CANDIDATE = "RESEARCH_CANDIDATE"
    HELD_CANDIDATE = "HELD_CANDIDATE"
    SHADOW_SHORTLISTED = "SHADOW_SHORTLISTED"
    COMPARATOR_ONLY = "COMPARATOR_ONLY"
    PRODUCTION_ELIGIBLE = "PRODUCTION_ELIGIBLE"
    RETIRED = "RETIRED"
    REJECTED = "REJECTED"


class SourceItemIdentityKind(StrEnum):
    SOURCE_NATIVE = "SOURCE_NATIVE"
    COMPOSITE = "COMPOSITE"
    ASSIGNED_WITH_UNCERTAINTY = "ASSIGNED_WITH_UNCERTAINTY"


class LocatorContinuityOutcome(StrEnum):
    SAME_ITEM = "SAME_ITEM"
    DIFFERENT_ITEM = "DIFFERENT_ITEM"
    POSSIBLE_REPLACEMENT = "POSSIBLE_REPLACEMENT"
    POSSIBLE_EQUIVALENCE = "POSSIBLE_EQUIVALENCE"
    UNCERTAIN = "UNCERTAIN"


class DiscoveryOccurrenceKind(StrEnum):
    FIRST_OBSERVED = "FIRST_OBSERVED"
    REOBSERVED = "REOBSERVED"
    DELIVERED = "DELIVERED"


EXECUTION_AUTHORITY_DISABLED = "FIXTURE_REPLAY_ONLY_DISABLED"


def bounded_text(
    value: str,
    *,
    field: str,
    maximum_bytes: int = 4096,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise SourceContractError(f"{field} must be canonical text")
    if not allow_empty and not value:
        raise SourceContractError(f"{field} cannot be empty")
    if len(value.encode("utf-8")) > maximum_bytes:
        raise SourceContractError(f"{field} exceeds its byte bound")
    return value


def bounded_text_tuple(
    value: tuple[str, ...],
    *,
    field: str,
    allow_empty: bool = False,
    maximum_items: int = 32,
    maximum_item_bytes: int = 1024,
) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise SourceContractError(f"{field} must be an immutable tuple")
    if not allow_empty and not value:
        raise SourceContractError(f"{field} cannot be empty")
    if len(value) > maximum_items:
        raise SourceContractError(f"{field} exceeds its item bound")
    normalized = tuple(
        bounded_text(
            item,
            field=field,
            maximum_bytes=maximum_item_bytes,
        )
        for item in value
    )
    if normalized != tuple(sorted(set(normalized))):
        raise SourceContractError(f"{field} must be sorted and unique")
    return normalized


def typed_enum_tuple(
    value: tuple[StrEnum, ...],
    *,
    enum_type: type[StrEnum],
    field: str,
    allow_empty: bool = False,
) -> tuple[StrEnum, ...]:
    if not isinstance(value, tuple):
        raise SourceContractError(f"{field} must be an immutable tuple")
    if not allow_empty and not value:
        raise SourceContractError(f"{field} cannot be empty")
    if any(not isinstance(item, enum_type) for item in value):
        raise SourceContractError(f"{field} entries must be typed")
    if value != tuple(sorted(set(value), key=lambda item: item.value)):
        raise SourceContractError(f"{field} must be sorted and unique")
    return value


def canonical_digest(value: str, *, field: str) -> str:
    normalized = validate_sha256_digest(value, field=field)
    if normalized != value:
        raise SourceContractError(f"{field} must use canonical lowercase text")
    return value


@dataclass(frozen=True, slots=True)
class VersionedPolicyRef:
    policy_id: str
    policy_version: str

    def __post_init__(self) -> None:
        require_token(self.policy_id, field="policy_id")
        require_token(self.policy_version, field="policy_version")

    def canonical_value(self) -> dict[str, str]:
        return {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
        }


@dataclass(frozen=True, slots=True)
class RightsReference:
    rights_decision_id: str
    rights_policy_version: str
    allowed_use: str
    retention_scope: str

    def __post_init__(self) -> None:
        UUIDv4Id.parse(self.rights_decision_id)
        require_token(self.rights_policy_version, field="rights_policy_version")
        require_scope(self.allowed_use, field="source_allowed_use")
        require_scope(self.retention_scope, field="source_retention_scope")

    def canonical_value(self) -> dict[str, str]:
        return {
            "rights_decision_id": self.rights_decision_id,
            "rights_policy_version": self.rights_policy_version,
            "allowed_use": self.allowed_use,
            "retention_scope": self.retention_scope,
        }


@dataclass(frozen=True, slots=True)
class BaselinePolicy:
    reference: VersionedPolicyRef
    kind: BaselinePolicyKind
    freshness_window_seconds: int | None = None
    reset_requires_decision: bool = True
    notes: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.reference, VersionedPolicyRef):
            raise SourceContractError("baseline policy reference must be typed")
        if not isinstance(self.kind, BaselinePolicyKind):
            raise SourceContractError("baseline policy kind must be typed")
        if self.freshness_window_seconds is not None and (
            isinstance(self.freshness_window_seconds, bool)
            or not isinstance(self.freshness_window_seconds, int)
            or self.freshness_window_seconds <= 0
            or self.freshness_window_seconds > 366 * 24 * 60 * 60
        ):
            raise SourceContractError("baseline freshness window is invalid")
        if self.kind is BaselinePolicyKind.BOUNDED_BACKFILL:
            if self.freshness_window_seconds is None:
                raise SourceContractError(
                    "bounded-backfill baseline requires a freshness window"
                )
        elif self.freshness_window_seconds is not None:
            raise SourceContractError(
                "only bounded-backfill baselines carry a freshness window"
            )
        if not isinstance(self.reset_requires_decision, bool):
            raise SourceContractError("baseline reset flag must be boolean")
        bounded_text(
            self.notes,
            field="baseline_notes",
            maximum_bytes=2048,
            allow_empty=True,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "reference": self.reference.canonical_value(),
            "kind": self.kind.value,
            "freshness_window_seconds": self.freshness_window_seconds,
            "reset_requires_decision": self.reset_requires_decision,
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class SourceRoleAssignment:
    role: SourceRole
    purpose: str
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.role, SourceRole):
            raise SourceContractError("source role must be typed")
        bounded_text(self.purpose, field="source_role_purpose", maximum_bytes=2048)
        bounded_text_tuple(
            self.limitations,
            field="source_role_limitations",
            allow_empty=True,
            maximum_items=16,
            maximum_item_bytes=1024,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "role": self.role.value,
            "purpose": self.purpose,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class CoverageMapping:
    obligation_id: str
    responsibility: CoverageResponsibility
    contribution: CoverageContribution
    geographies: tuple[str, ...]
    languages: tuple[str, ...]
    limitations: tuple[str, ...]
    explicit_gap_id: str | None = None

    def __post_init__(self) -> None:
        require_token(self.obligation_id, field="coverage_obligation_id")
        if not isinstance(self.responsibility, CoverageResponsibility):
            raise SourceContractError("coverage responsibility must be typed")
        if not isinstance(self.contribution, CoverageContribution):
            raise SourceContractError("coverage contribution must be typed")
        bounded_text_tuple(
            self.geographies,
            field="coverage_geographies",
            maximum_items=16,
            maximum_item_bytes=64,
        )
        bounded_text_tuple(
            self.languages,
            field="coverage_languages",
            maximum_items=16,
            maximum_item_bytes=64,
        )
        bounded_text_tuple(
            self.limitations,
            field="coverage_limitations",
            allow_empty=True,
            maximum_items=16,
            maximum_item_bytes=1024,
        )
        if self.explicit_gap_id is not None:
            require_token(self.explicit_gap_id, field="explicit_coverage_gap_id")
        if self.responsibility is CoverageResponsibility.EXPLICIT_DEFERRED_GAP:
            if self.explicit_gap_id is None:
                raise SourceContractError(
                    "deferred coverage mapping requires an explicit gap identity"
                )
        elif self.explicit_gap_id is not None:
            raise SourceContractError(
                "only deferred coverage mappings may carry an explicit gap identity"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "obligation_id": self.obligation_id,
            "responsibility": self.responsibility.value,
            "contribution": self.contribution.value,
            "geographies": list(self.geographies),
            "languages": list(self.languages),
            "limitations": list(self.limitations),
            "explicit_gap_id": self.explicit_gap_id,
        }


@dataclass(frozen=True, slots=True)
class SourceDependency:
    dependency_id: str
    kind: SourceDependencyKind
    description: str
    upstream_source_definition_id: SourceDefinitionId | None = None

    def __post_init__(self) -> None:
        require_token(self.dependency_id, field="source_dependency_id")
        if not isinstance(self.kind, SourceDependencyKind):
            raise SourceContractError("source dependency kind must be typed")
        bounded_text(
            self.description,
            field="source_dependency_description",
            maximum_bytes=2048,
        )
        if self.upstream_source_definition_id is not None and not isinstance(
            self.upstream_source_definition_id, SourceDefinitionId
        ):
            raise SourceContractError(
                "upstream source definition identity must be typed"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "dependency_id": self.dependency_id,
            "kind": self.kind.value,
            "description": self.description,
            "upstream_source_definition_id": (
                None
                if self.upstream_source_definition_id is None
                else str(self.upstream_source_definition_id)
            ),
        }


@dataclass(frozen=True, slots=True)
class ExplicitSourceGap:
    gap_id: str
    gap_class: str
    description: str
    launch_blocking: bool

    def __post_init__(self) -> None:
        require_token(self.gap_id, field="source_gap_id")
        require_token(self.gap_class, field="source_gap_class")
        bounded_text(
            self.description,
            field="source_gap_description",
            maximum_bytes=2048,
        )
        if not isinstance(self.launch_blocking, bool):
            raise SourceContractError("source gap launch flag must be boolean")

    def canonical_value(self) -> dict[str, object]:
        return {
            "gap_id": self.gap_id,
            "gap_class": self.gap_class,
            "description": self.description,
            "launch_blocking": self.launch_blocking,
        }


@dataclass(frozen=True, slots=True)
class IdentityComponent:
    name: str
    value: str

    def __post_init__(self) -> None:
        require_token(self.name, field="identity_component_name")
        bounded_text(
            self.value,
            field="identity_component_value",
            maximum_bytes=2048,
        )

    def canonical_value(self) -> dict[str, str]:
        return {"name": self.name, "value": self.value}


@dataclass(frozen=True, slots=True)
class SourceTime:
    precision: TimePrecision
    value: str | None = None
    conflicting_values: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.precision, TimePrecision):
            raise SourceContractError("source time precision must be typed")
        if self.precision is TimePrecision.UNKNOWN:
            if self.value is not None or self.conflicting_values:
                raise SourceContractError("unknown source time cannot carry values")
            return
        if self.precision is TimePrecision.CONFLICTING:
            if self.value is not None:
                raise SourceContractError("conflicting source time has no single value")
            bounded_text_tuple(
                self.conflicting_values,
                field="conflicting_source_times",
                maximum_items=8,
                maximum_item_bytes=128,
            )
            if len(self.conflicting_values) < 2:
                raise SourceContractError(
                    "conflicting source time requires at least two alternatives"
                )
            return
        if self.conflicting_values:
            raise SourceContractError(
                "source time alternatives are valid only when conflicting"
            )
        if self.value is None:
            raise SourceContractError("known source time requires a value")
        bounded_text(
            self.value,
            field="source_time_value",
            maximum_bytes=128,
        )
        if self.precision is TimePrecision.DATE_ONLY:
            try:
                parsed_date = date.fromisoformat(self.value)
            except ValueError as exc:
                raise SourceContractError("date-only source time is invalid") from exc
            if parsed_date.isoformat() != self.value:
                raise SourceContractError("date-only source time is not canonical")
            return
        parsed_time = UtcTimestamp.parse(self.value)
        if parsed_time.to_text() != self.value:
            raise SourceContractError("source time must use canonical UTC text")

    @classmethod
    def unknown(cls) -> "SourceTime":
        return cls(TimePrecision.UNKNOWN)

    @classmethod
    def exact(cls, value: UtcTimestamp) -> "SourceTime":
        if not isinstance(value, UtcTimestamp):
            raise SourceContractError("exact source time requires typed UTC")
        return cls(TimePrecision.EXACT, value.to_text())

    def canonical_value(self) -> dict[str, object]:
        return {
            "precision": self.precision.value,
            "value": self.value,
            "conflicting_values": list(self.conflicting_values),
        }


@dataclass(frozen=True, slots=True)
class SourceRegistryReadPolicy:
    policy_id: str
    purpose: str
    metadata_required_scope: str
    sensitive_required_scope: str
    allowed_principal_ids: frozenset[str]
    max_results: int = 1000

    def __post_init__(self) -> None:
        require_token(self.policy_id, field="source_read_policy_id")
        require_token(self.purpose, field="source_read_purpose")
        require_scope(
            self.metadata_required_scope,
            field="source_metadata_read_scope",
        )
        require_scope(
            self.sensitive_required_scope,
            field="source_sensitive_read_scope",
        )
        if self.metadata_required_scope == self.sensitive_required_scope:
            raise SourceContractError(
                "source metadata and sensitive reads require distinct scopes"
            )
        if (
            not isinstance(self.allowed_principal_ids, frozenset)
            or not self.allowed_principal_ids
        ):
            raise SourceContractError(
                "source read principals must be a non-empty frozenset"
            )
        for principal_id in self.allowed_principal_ids:
            require_token(principal_id, field="source_reader_principal")
        if (
            isinstance(self.max_results, bool)
            or not isinstance(self.max_results, int)
            or self.max_results <= 0
            or self.max_results > 10_000
        ):
            raise SourceContractError(
                "source read maximum must be between 1 and 10000"
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
                "source reader principal is outside the read policy"
            )

    def require_limit(self, limit: int) -> None:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit <= 0
            or limit > self.max_results
        ):
            raise PermissionError("source read limit exceeds the read policy")


def sorted_role_assignments(
    values: Iterable[SourceRoleAssignment],
) -> tuple[SourceRoleAssignment, ...]:
    items = tuple(sorted(values, key=lambda item: item.role.value))
    if len(items) != len({item.role for item in items}):
        raise SourceContractError("source roles must be unique")
    return items


def sorted_coverage_mappings(
    values: Iterable[CoverageMapping],
) -> tuple[CoverageMapping, ...]:
    items = tuple(
        sorted(
            values,
            key=lambda item: (
                item.obligation_id,
                item.responsibility.value,
                item.contribution.value,
            ),
        )
    )
    keys = {
        (item.obligation_id, item.responsibility, item.contribution)
        for item in items
    }
    if len(items) != len(keys):
        raise SourceContractError("coverage mappings must be unique")
    return items


def sorted_dependencies(
    values: Iterable[SourceDependency],
) -> tuple[SourceDependency, ...]:
    items = tuple(sorted(values, key=lambda item: item.dependency_id))
    if len(items) != len({item.dependency_id for item in items}):
        raise SourceContractError("source dependencies must be unique")
    return items


def sorted_source_gaps(
    values: Iterable[ExplicitSourceGap],
) -> tuple[ExplicitSourceGap, ...]:
    items = tuple(sorted(values, key=lambda item: item.gap_id))
    if len(items) != len({item.gap_id for item in items}):
        raise SourceContractError("source gaps must be unique")
    return items


def sorted_identity_components(
    values: Iterable[IdentityComponent],
) -> tuple[IdentityComponent, ...]:
    items = tuple(sorted(values, key=lambda item: item.name))
    if len(items) != len({item.name for item in items}):
        raise SourceContractError("identity component names must be unique")
    return items


__all__ = [
    "BaselinePolicy",
    "BaselinePolicyKind",
    "CheckOutcomeId",
    "CoverageContribution",
    "CoverageMapping",
    "CoverageResponsibility",
    "DiscoveryOccurrenceId",
    "DiscoveryOccurrenceKind",
    "DiscoveryRepresentationId",
    "EXECUTION_AUTHORITY_DISABLED",
    "ExplicitSourceGap",
    "IdentityComponent",
    "LocatorContinuityDecisionId",
    "LocatorContinuityOutcome",
    "ObservationModel",
    "PortfolioFunction",
    "RightsReference",
    "SourceAuthorityError",
    "SourceContractError",
    "SourceDefinitionId",
    "SourceDefinitionVersionId",
    "SourceDependency",
    "SourceDependencyKind",
    "SourceIdentifierReuse",
    "SourceItemId",
    "SourceItemIdentityKind",
    "SourceLifecycleStage",
    "SourceRegistryReadPolicy",
    "SourceRevisionId",
    "SourceRole",
    "SourceRoleAssignment",
    "SourceSemanticCollision",
    "SourceStateError",
    "SourceTime",
    "SourceVersionConflict",
    "VersionedPolicyRef",
    "bounded_text",
    "bounded_text_tuple",
    "canonical_digest",
    "sorted_coverage_mappings",
    "sorted_dependencies",
    "sorted_identity_components",
    "sorted_role_assignments",
    "sorted_source_gaps",
    "typed_enum_tuple",
]
