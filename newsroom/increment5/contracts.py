from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import ClassVar, Mapping, TypeAlias

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.authority.types import UtcTimestamp, require_token


_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class Increment5ContractError(ValueError):
    """An Increment 5 contract or decision packet is malformed."""


class Increment5ProfileError(RuntimeError):
    """A retrieval profile is incompatible with its owner decision."""


class RetrievalProfileKind(StrEnum):
    FIXTURE_REPLAY = "FIXTURE_REPLAY"
    PRODUCTION = "PRODUCTION"


class RetrievalMode(StrEnum):
    EXACT = "EXACT"
    FULL_TEXT = "FULL_TEXT"
    VECTOR = "VECTOR"
    ADMITTED_GRAPH = "ADMITTED_GRAPH"


class RetrievalComponentKind(StrEnum):
    EMBEDDING = "EMBEDDING"
    PASSAGE = "PASSAGE"
    NORMALIZATION = "NORMALIZATION"
    FULL_TEXT_INDEX = "FULL_TEXT_INDEX"
    VECTOR_INDEX = "VECTOR_INDEX"
    GRAPH_QUERY = "GRAPH_QUERY"
    FUSION = "FUSION"
    DEDUPLICATION = "DEDUPLICATION"
    HYDRATION = "HYDRATION"
    DEGRADED_POLICY = "DEGRADED_POLICY"


class ComponentDisposition(StrEnum):
    BOUND_CONTRACT = "BOUND_CONTRACT"
    DISABLED_PENDING_OWNER_DECISION = "DISABLED_PENDING_OWNER_DECISION"
    BLOCKED_BY_DISABLED_DEPENDENCY = "BLOCKED_BY_DISABLED_DEPENDENCY"
    FIXTURE_REPLAY_ONLY = "FIXTURE_REPLAY_ONLY"


class DecisionPacketStatus(StrEnum):
    PENDING_OWNER_REVIEW = "PENDING_OWNER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DEFERRED = "DEFERRED"


class RuntimeAuthority(StrEnum):
    CONTRACT_AND_FIXTURE_REPLAY_ONLY = "CONTRACT_AND_FIXTURE_REPLAY_ONLY"
    PRODUCTION_QUALIFICATION = "PRODUCTION_QUALIFICATION"


def _bounded_text(
    value: str,
    *,
    field: str,
    maximum_bytes: int = 4096,
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > maximum_bytes
    ):
        raise Increment5ContractError(f"{field} must be bounded canonical text")
    return value


def _sorted_unique_tokens(
    value: tuple[str, ...],
    *,
    field: str,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise Increment5ContractError(f"{field} must be an immutable tuple")
    if not value and not allow_empty:
        raise Increment5ContractError(f"{field} cannot be empty")
    for item in value:
        try:
            require_token(item, field=field)
        except ValueError as exc:
            raise Increment5ContractError(
                f"{field} contains an invalid token"
            ) from exc
    if value != tuple(sorted(set(value))):
        raise Increment5ContractError(f"{field} must be sorted and unique")
    return value


@dataclass(frozen=True, slots=True)
class RetrievalComponentIdentity:
    """Digest-bound identity for one immutable retrieval component contract."""

    EXPECTED_KIND: ClassVar[RetrievalComponentKind]

    contract_id: str
    contract_version: str
    implementation_version: str
    disposition: ComponentDisposition
    configuration_digest: str
    compatibility_rule: str
    change_requires: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "contract_id",
            "contract_version",
            "implementation_version",
            "compatibility_rule",
        ):
            try:
                require_token(getattr(self, field_name), field=field_name)
            except ValueError as exc:
                raise Increment5ContractError(
                    f"{field_name} is not a valid contract token"
                ) from exc
        if not isinstance(self.disposition, ComponentDisposition):
            raise Increment5ContractError("component disposition must be typed")
        try:
            validate_sha256_digest(
                self.configuration_digest,
                field="component_configuration_digest",
            )
        except ValueError as exc:
            raise Increment5ContractError(
                "component configuration digest is invalid"
            ) from exc
        _sorted_unique_tokens(self.change_requires, field="change_requires")

    @property
    def kind(self) -> RetrievalComponentKind:
        return self.EXPECTED_KIND

    def canonical_value(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "implementation_version": self.implementation_version,
            "disposition": self.disposition.value,
            "configuration_digest": self.configuration_digest,
            "compatibility_rule": self.compatibility_rule,
            "change_requires": list(self.change_requires),
        }

    @property
    def identity_digest(self) -> str:
        return digest_bytes(canonical_json_bytes(self.canonical_value()))


@dataclass(frozen=True, slots=True)
class EmbeddingContractIdentity(RetrievalComponentIdentity):
    EXPECTED_KIND: ClassVar[RetrievalComponentKind] = (
        RetrievalComponentKind.EMBEDDING
    )


@dataclass(frozen=True, slots=True)
class PassageContractIdentity(RetrievalComponentIdentity):
    EXPECTED_KIND: ClassVar[RetrievalComponentKind] = RetrievalComponentKind.PASSAGE


@dataclass(frozen=True, slots=True)
class NormalizationContractIdentity(RetrievalComponentIdentity):
    EXPECTED_KIND: ClassVar[RetrievalComponentKind] = (
        RetrievalComponentKind.NORMALIZATION
    )


@dataclass(frozen=True, slots=True)
class FullTextIndexContractIdentity(RetrievalComponentIdentity):
    EXPECTED_KIND: ClassVar[RetrievalComponentKind] = (
        RetrievalComponentKind.FULL_TEXT_INDEX
    )


@dataclass(frozen=True, slots=True)
class VectorIndexContractIdentity(RetrievalComponentIdentity):
    EXPECTED_KIND: ClassVar[RetrievalComponentKind] = (
        RetrievalComponentKind.VECTOR_INDEX
    )


@dataclass(frozen=True, slots=True)
class GraphQueryContractIdentity(RetrievalComponentIdentity):
    EXPECTED_KIND: ClassVar[RetrievalComponentKind] = (
        RetrievalComponentKind.GRAPH_QUERY
    )


@dataclass(frozen=True, slots=True)
class FusionContractIdentity(RetrievalComponentIdentity):
    EXPECTED_KIND: ClassVar[RetrievalComponentKind] = RetrievalComponentKind.FUSION


@dataclass(frozen=True, slots=True)
class DeduplicationContractIdentity(RetrievalComponentIdentity):
    EXPECTED_KIND: ClassVar[RetrievalComponentKind] = (
        RetrievalComponentKind.DEDUPLICATION
    )


@dataclass(frozen=True, slots=True)
class HydrationContractIdentity(RetrievalComponentIdentity):
    EXPECTED_KIND: ClassVar[RetrievalComponentKind] = (
        RetrievalComponentKind.HYDRATION
    )


@dataclass(frozen=True, slots=True)
class DegradedPolicyContractIdentity(RetrievalComponentIdentity):
    EXPECTED_KIND: ClassVar[RetrievalComponentKind] = (
        RetrievalComponentKind.DEGRADED_POLICY
    )


TypedComponentIdentity: TypeAlias = (
    EmbeddingContractIdentity
    | PassageContractIdentity
    | NormalizationContractIdentity
    | FullTextIndexContractIdentity
    | VectorIndexContractIdentity
    | GraphQueryContractIdentity
    | FusionContractIdentity
    | DeduplicationContractIdentity
    | HydrationContractIdentity
    | DegradedPolicyContractIdentity
)


_COMPONENT_IDENTITY_TYPES: Mapping[
    RetrievalComponentKind,
    type[RetrievalComponentIdentity],
] = {
    RetrievalComponentKind.EMBEDDING: EmbeddingContractIdentity,
    RetrievalComponentKind.PASSAGE: PassageContractIdentity,
    RetrievalComponentKind.NORMALIZATION: NormalizationContractIdentity,
    RetrievalComponentKind.FULL_TEXT_INDEX: FullTextIndexContractIdentity,
    RetrievalComponentKind.VECTOR_INDEX: VectorIndexContractIdentity,
    RetrievalComponentKind.GRAPH_QUERY: GraphQueryContractIdentity,
    RetrievalComponentKind.FUSION: FusionContractIdentity,
    RetrievalComponentKind.DEDUPLICATION: DeduplicationContractIdentity,
    RetrievalComponentKind.HYDRATION: HydrationContractIdentity,
    RetrievalComponentKind.DEGRADED_POLICY: DegradedPolicyContractIdentity,
}


def component_identity(
    *,
    kind: RetrievalComponentKind,
    contract_id: str,
    contract_version: str,
    implementation_version: str,
    disposition: ComponentDisposition,
    configuration_digest: str,
    compatibility_rule: str,
    change_requires: tuple[str, ...],
) -> TypedComponentIdentity:
    if not isinstance(kind, RetrievalComponentKind):
        raise Increment5ContractError("component kind must be typed")
    identity_type = _COMPONENT_IDENTITY_TYPES[kind]
    return identity_type(
        contract_id=contract_id,
        contract_version=contract_version,
        implementation_version=implementation_version,
        disposition=disposition,
        configuration_digest=configuration_digest,
        compatibility_rule=compatibility_rule,
        change_requires=change_requires,
    )


@dataclass(frozen=True, slots=True)
class Increment5AContractBundle:
    """Exact, implementation-neutral retrieval contract selected by 5A."""

    decision_id: str
    decision_version: str
    implementation_base: str
    production_profile_schema_digest: str
    fixture_replay_profile_schema_digest: str
    required_modes: tuple[RetrievalMode, ...]
    named_tools: tuple[str, ...]
    authoritative_hydration_system: str
    candidate_collision_system: str
    components: tuple[TypedComponentIdentity, ...]
    fusion_is_authority: bool = False
    projection_is_authority: bool = False

    def __post_init__(self) -> None:
        for field_name in ("decision_id", "decision_version"):
            try:
                require_token(getattr(self, field_name), field=field_name)
            except ValueError as exc:
                raise Increment5ContractError(
                    f"{field_name} is not a valid contract token"
                ) from exc
        if _COMMIT_SHA.fullmatch(self.implementation_base) is None:
            raise Increment5ContractError(
                "implementation base must be an exact lowercase commit SHA"
            )
        for field_name in (
            "production_profile_schema_digest",
            "fixture_replay_profile_schema_digest",
        ):
            try:
                validate_sha256_digest(getattr(self, field_name), field=field_name)
            except ValueError as exc:
                raise Increment5ContractError(
                    f"{field_name} is not a canonical digest"
                ) from exc
        expected_modes = (
            RetrievalMode.EXACT,
            RetrievalMode.FULL_TEXT,
            RetrievalMode.VECTOR,
            RetrievalMode.ADMITTED_GRAPH,
        )
        if self.required_modes != expected_modes:
            raise Increment5ContractError(
                "Increment 5 requires exact, full-text, vector and graph modes"
            )
        expected_tools = (
            "find_related_event_candidates",
            "get_event_or_process_timeline",
            "find_source_revision_impact",
            "find_shared_origin_dependencies",
            "find_conflicting_relation_candidates",
            "get_candidate_provenance",
        )
        if self.named_tools != expected_tools:
            raise Increment5ContractError(
                "Increment 5 named-tool inventory differs from the accepted family"
            )
        for tool in self.named_tools:
            try:
                require_token(tool, field="named_retrieval_tool")
            except ValueError as exc:
                raise Increment5ContractError(
                    "named retrieval tool is not a valid token"
                ) from exc
        if (
            self.authoritative_hydration_system
            != "sqlite-ledger-and-governed-objects"
        ):
            raise Increment5ContractError(
                "retrieval hydration must return to retained authority"
            )
        if self.candidate_collision_system != "sqlite-authoritative-exact-collision":
            raise Increment5ContractError(
                "Candidate collision checks must remain authoritative and exact"
            )
        if not isinstance(self.components, tuple):
            raise Increment5ContractError(
                "retrieval component identities must be immutable"
            )
        expected_kinds = tuple(RetrievalComponentKind)
        actual_kinds = tuple(item.kind for item in self.components)
        if actual_kinds != expected_kinds:
            raise Increment5ContractError(
                "retrieval component inventory must contain every typed seam exactly once"
            )
        identity_digests = tuple(item.identity_digest for item in self.components)
        if len(identity_digests) != len(set(identity_digests)):
            raise Increment5ContractError(
                "retrieval component identities must be unique"
            )
        if self.fusion_is_authority or self.projection_is_authority:
            raise Increment5ContractError(
                "rank, fusion and projections cannot become editorial authority"
            )

    @property
    def component_by_kind(
        self,
    ) -> dict[RetrievalComponentKind, TypedComponentIdentity]:
        return {item.kind: item for item in self.components}

    def canonical_value(self) -> dict[str, object]:
        return {
            "decision_id": self.decision_id,
            "decision_version": self.decision_version,
            "implementation_base": self.implementation_base,
            "production_profile_schema_digest": (
                self.production_profile_schema_digest
            ),
            "fixture_replay_profile_schema_digest": (
                self.fixture_replay_profile_schema_digest
            ),
            "required_modes": [item.value for item in self.required_modes],
            "named_tools": list(self.named_tools),
            "authoritative_hydration_system": self.authoritative_hydration_system,
            "candidate_collision_system": self.candidate_collision_system,
            "components": [item.canonical_value() for item in self.components],
            "fusion_is_authority": self.fusion_is_authority,
            "projection_is_authority": self.projection_is_authority,
        }

    @property
    def contract_digest(self) -> str:
        return digest_bytes(canonical_json_bytes(self.canonical_value()))


@dataclass(frozen=True, slots=True)
class RetrievalBudgetContract:
    timeout_ms: int
    branch_result_limit: int
    retained_candidate_limit: int
    response_byte_limit: int
    max_external_calls_per_request: int
    max_gross_cost_microunits_per_request: int

    def __post_init__(self) -> None:
        expected = {
            "timeout_ms": 5_000,
            "branch_result_limit": 8,
            "retained_candidate_limit": 12,
            "response_byte_limit": 262_144,
            "max_external_calls_per_request": 0,
            "max_gross_cost_microunits_per_request": 0,
        }
        for field_name, required in expected.items():
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise Increment5ContractError(
                    f"{field_name} must be a non-negative integer"
                )
            if value != required:
                raise Increment5ContractError(
                    f"{field_name} differs from the exact 5A zero-spend budget"
                )

    def canonical_value(self) -> dict[str, int]:
        return {
            "timeout_ms": self.timeout_ms,
            "branch_result_limit": self.branch_result_limit,
            "retained_candidate_limit": self.retained_candidate_limit,
            "response_byte_limit": self.response_byte_limit,
            "max_external_calls_per_request": (
                self.max_external_calls_per_request
            ),
            "max_gross_cost_microunits_per_request": (
                self.max_gross_cost_microunits_per_request
            ),
        }


@dataclass(frozen=True, slots=True)
class Increment5ADecisionPacket:
    """Immutable parsed decision packet plus truthful execution authority."""

    schema_version: str
    status: DecisionPacketStatus
    owner: str
    prepared_at: UtcTimestamp
    issue_number: int
    parent_issue_number: int
    programme_issue_number: int
    runtime_authority: RuntimeAuthority
    approved_profiles: tuple[RetrievalProfileKind, ...]
    blocked_profiles: tuple[RetrievalProfileKind, ...]
    unresolved_decisions: tuple[str, ...]
    budgets: RetrievalBudgetContract
    payload_digest: str
    record_digest: str
    bundle: Increment5AContractBundle

    def __post_init__(self) -> None:
        try:
            require_token(self.schema_version, field="decision_schema_version")
        except ValueError as exc:
            raise Increment5ContractError(
                "decision schema version is not a valid token"
            ) from exc
        if not isinstance(self.status, DecisionPacketStatus):
            raise Increment5ContractError("decision status must be typed")
        _bounded_text(self.owner, field="owner", maximum_bytes=256)
        if not isinstance(self.prepared_at, UtcTimestamp):
            raise Increment5ContractError("decision prepared_at must be typed")
        for field_name in (
            "issue_number",
            "parent_issue_number",
            "programme_issue_number",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise Increment5ContractError(f"{field_name} must be positive")
        if not isinstance(self.runtime_authority, RuntimeAuthority):
            raise Increment5ContractError("runtime authority must be typed")
        if (
            not isinstance(self.approved_profiles, tuple)
            or len(self.approved_profiles) != len(set(self.approved_profiles))
            or not all(
                isinstance(item, RetrievalProfileKind)
                for item in self.approved_profiles
            )
        ):
            raise Increment5ContractError(
                "approved profiles must be unique typed values"
            )
        if (
            not isinstance(self.blocked_profiles, tuple)
            or len(self.blocked_profiles) != len(set(self.blocked_profiles))
            or not all(
                isinstance(item, RetrievalProfileKind)
                for item in self.blocked_profiles
            )
        ):
            raise Increment5ContractError(
                "blocked profiles must be unique typed values"
            )
        if set(self.approved_profiles) & set(self.blocked_profiles):
            raise Increment5ContractError(
                "a retrieval profile cannot be both approved and blocked"
            )
        if set(self.approved_profiles) | set(self.blocked_profiles) != set(
            RetrievalProfileKind
        ):
            raise Increment5ContractError(
                "every retrieval profile must be explicitly approved or blocked"
            )
        if not isinstance(self.unresolved_decisions, tuple):
            raise Increment5ContractError(
                "unresolved decisions must be an immutable tuple"
            )
        for item in self.unresolved_decisions:
            _bounded_text(item, field="unresolved_decision", maximum_bytes=512)
        if self.unresolved_decisions != tuple(sorted(set(self.unresolved_decisions))):
            raise Increment5ContractError(
                "unresolved decisions must be sorted and unique"
            )
        if not isinstance(self.budgets, RetrievalBudgetContract):
            raise Increment5ContractError("decision budgets must be typed")
        for field_name in ("payload_digest", "record_digest"):
            try:
                validate_sha256_digest(getattr(self, field_name), field=field_name)
            except ValueError as exc:
                raise Increment5ContractError(
                    f"{field_name} is not a canonical digest"
                ) from exc
        if not isinstance(self.bundle, Increment5AContractBundle):
            raise Increment5ContractError("decision bundle must be typed")

        if self.status is not DecisionPacketStatus.APPROVED:
            if self.runtime_authority is not RuntimeAuthority.CONTRACT_AND_FIXTURE_REPLAY_ONLY:
                raise Increment5ContractError(
                    "an unapproved packet cannot grant production qualification"
                )
            if self.approved_profiles != (RetrievalProfileKind.FIXTURE_REPLAY,):
                raise Increment5ContractError(
                    "an unapproved packet may permit fixture replay only"
                )
            if self.blocked_profiles != (RetrievalProfileKind.PRODUCTION,):
                raise Increment5ContractError(
                    "an unapproved packet must block the production profile"
                )

    @property
    def production_authorized(self) -> bool:
        return (
            self.status is DecisionPacketStatus.APPROVED
            and self.runtime_authority is RuntimeAuthority.PRODUCTION_QUALIFICATION
            and RetrievalProfileKind.PRODUCTION in self.approved_profiles
            and not self.unresolved_decisions
        )

    def require_profile(self, profile: RetrievalProfileKind) -> None:
        if not isinstance(profile, RetrievalProfileKind):
            raise Increment5ProfileError("retrieval profile must be typed")
        if profile in self.blocked_profiles or profile not in self.approved_profiles:
            raise Increment5ProfileError(
                f"{profile.value} is not authorized by the exact decision packet"
            )
        if profile is RetrievalProfileKind.PRODUCTION and not self.production_authorized:
            raise Increment5ProfileError(
                "production qualification requires an approved, complete owner decision"
            )
