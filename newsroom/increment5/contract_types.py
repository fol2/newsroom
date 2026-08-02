"""Typed, immutable views of the reviewed Increment 5A contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class Increment5ContractError(ValueError):
    """The checked Increment 5A contract is not the reviewed v1 content."""


class ContractStatus(StrEnum):
    OWNER_ACCEPTED_ON_MERGE = "OWNER_ACCEPTED_ON_MERGE"


class ContractEffect(StrEnum):
    IMPLEMENTATION_AND_NON_PRODUCTION_QUALIFICATION = (
        "IMPLEMENTATION_AND_NON_PRODUCTION_QUALIFICATION_OF_ISSUES_251_254_ONLY"
    )


class RetrievalProfileKind(StrEnum):
    FIXTURE_REPLAY = "FIXTURE_REPLAY"
    PRODUCTION_SHAPED_QUALIFICATION = "PRODUCTION_SHAPED_QUALIFICATION"


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
    BOUND_FOR_IMPLEMENTATION = "BOUND_FOR_IMPLEMENTATION"
    QUALIFICATION_ONLY = "QUALIFICATION_ONLY"
    DISABLED_IN_INCREMENT_5_V1 = "DISABLED_IN_INCREMENT_5_V1"


def freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({name: freeze(item) for name, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class RetrievalComponentContract:
    kind: RetrievalComponentKind
    contract_id: str
    contract_version: str
    implementation_version: str
    disposition: ComponentDisposition
    compatibility_rule: str
    change_requires: tuple[str, ...]
    configuration: Mapping[str, Any]
    identity_digest: str


@dataclass(frozen=True, slots=True)
class Increment5AContract:
    schema_version: str
    contract_id: str
    contract_version: str
    status: ContractStatus
    effect: ContractEffect
    owner: str
    accepted_date: str
    implementation_base: str
    issue_number: int
    parent_issue_number: int
    programme_issue_number: int
    pr_number: int
    effective_when: str
    approved_profiles: tuple[RetrievalProfileKind, ...]
    required_modes: tuple[RetrievalMode, ...]
    named_tools: tuple[str, ...]
    components: tuple[RetrievalComponentContract, ...]
    component_digests: Mapping[str, str]
    profile_schema_digests: Mapping[str, str]
    payload_digest: str
    contract_digest: str
    payload: Mapping[str, Any]

    @property
    def production_activation_authorized(self) -> bool:
        return False

    @property
    def component_by_kind(
        self,
    ) -> Mapping[RetrievalComponentKind, RetrievalComponentContract]:
        return MappingProxyType({component.kind: component for component in self.components})

    def require_profile(self, profile: RetrievalProfileKind) -> RetrievalProfileKind:
        if not isinstance(profile, RetrievalProfileKind):
            raise Increment5ContractError("retrieval profile must be typed")
        if profile not in self.approved_profiles:
            raise Increment5ContractError(f"{profile.value} is not admitted by Increment 5A")
        return profile
