from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.types import require_token

from .models import ProjectionContractError
from .ontology import OntologyContract, ProjectionNodeType, ProjectionRelationType


@dataclass(frozen=True, slots=True)
class StructuralEventMapping:
    event_type: str
    required: bool
    node_types: frozenset[ProjectionNodeType]
    relation_types: frozenset[ProjectionRelationType]

    def __post_init__(self) -> None:
        require_token(self.event_type, field="structural_event_type")
        if not isinstance(self.required, bool):
            raise ProjectionContractError("mapping required flag must be boolean")
        if not isinstance(self.node_types, frozenset) or not self.node_types:
            raise ProjectionContractError("mapping node types must be non-empty")
        if not isinstance(self.relation_types, frozenset) or not self.relation_types:
            raise ProjectionContractError("mapping relation types must be non-empty")
        if any(not isinstance(item, ProjectionNodeType) for item in self.node_types):
            raise ProjectionContractError("mapping node types must be typed")
        if any(not isinstance(item, ProjectionRelationType) for item in self.relation_types):
            raise ProjectionContractError("mapping relation types must be typed")

    def canonical_value(self) -> dict[str, object]:
        return {
            "event_type": self.event_type,
            "required": self.required,
            "node_types": sorted(item.value for item in self.node_types),
            "relation_types": sorted(item.value for item in self.relation_types),
        }


@dataclass(frozen=True, slots=True)
class StructuralMappingContract:
    mapping_id: str
    mapping_version: str
    implementation_version: str
    ontology_contract_digest: str
    mappings: tuple[StructuralEventMapping, ...]

    def __post_init__(self) -> None:
        require_token(self.mapping_id, field="mapping_id")
        require_token(self.mapping_version, field="mapping_version")
        require_token(self.implementation_version, field="mapping_implementation_version")
        if not isinstance(self.mappings, tuple) or not self.mappings:
            raise ProjectionContractError("mapping contract requires event mappings")
        event_types = [item.event_type for item in self.mappings]
        if len(event_types) != len(set(event_types)):
            raise ProjectionContractError("mapping event types must be unique")

    def validate_against(self, ontology: OntologyContract) -> None:
        if ontology.contract_digest != self.ontology_contract_digest:
            raise ProjectionContractError("mapping ontology digest mismatch")
        for mapping in self.mappings:
            if not mapping.node_types <= ontology.node_types:
                raise ProjectionContractError("mapping references unknown node type")
            if not mapping.relation_types <= ontology.relation_types:
                raise ProjectionContractError("mapping references unknown relation type")

    def resolve(self, event_type: str) -> StructuralEventMapping | None:
        return next((item for item in self.mappings if item.event_type == event_type), None)

    def canonical_value(self) -> dict[str, object]:
        return {
            "mapping_id": self.mapping_id,
            "mapping_version": self.mapping_version,
            "implementation_version": self.implementation_version,
            "ontology_contract_digest": self.ontology_contract_digest,
            "mappings": [
                item.canonical_value()
                for item in sorted(self.mappings, key=lambda value: value.event_type)
            ],
        }

    @property
    def contract_digest(self) -> str:
        return digest_bytes(canonical_json_bytes(self.canonical_value()))


class StructuralMappingRegistry:
    def __init__(
        self,
        contracts: Iterable[StructuralMappingContract],
        *,
        current_versions: dict[str, str] | None = None,
    ) -> None:
        by_key: dict[tuple[str, str], StructuralMappingContract] = {}
        versions: dict[str, list[str]] = {}
        for contract in contracts:
            key = (contract.mapping_id, contract.mapping_version)
            if key in by_key:
                raise ProjectionContractError("duplicate mapping contract")
            by_key[key] = contract
            versions.setdefault(contract.mapping_id, []).append(contract.mapping_version)
        if not by_key:
            raise ProjectionContractError("mapping registry cannot be empty")
        requested = dict(current_versions or {})
        selected: dict[str, str] = {}
        for mapping_id, available in versions.items():
            if mapping_id in requested:
                version = requested.pop(mapping_id)
            elif len(available) == 1:
                version = available[0]
            else:
                raise ProjectionContractError("mapping current version must be explicit")
            if (mapping_id, version) not in by_key:
                raise ProjectionContractError("unknown current mapping version")
            selected[mapping_id] = version
        if requested:
            raise ProjectionContractError("current mapping version names unknown contract")
        self._by_key = by_key
        self._current = selected

    def resolve(self, mapping_id: str, version: str | None = None) -> StructuralMappingContract:
        selected = self._current.get(mapping_id) if version is None else version
        try:
            return self._by_key[(mapping_id, selected or "")]
        except KeyError as exc:
            raise ProjectionContractError(f"unknown mapping: {mapping_id}/{selected}") from exc

    def resolve_digest(self, digest: str) -> StructuralMappingContract:
        matches = [item for item in self._by_key.values() if item.contract_digest == digest]
        if len(matches) != 1:
            raise ProjectionContractError("unknown or ambiguous mapping digest")
        return matches[0]

    def contracts(self) -> tuple[StructuralMappingContract, ...]:
        return tuple(self._by_key[key] for key in sorted(self._by_key))


def native_structural_mapping_v1(ontology: OntologyContract) -> StructuralMappingContract:
    mappings = (
        StructuralEventMapping("authority.aggregate.versioned", True, frozenset({ProjectionNodeType.AUTHORITY_AGGREGATE, ProjectionNodeType.AUTHORITY_VERSION, ProjectionNodeType.PAYLOAD, ProjectionNodeType.LEDGER_EVENT}), frozenset({ProjectionRelationType.HAS_VERSION, ProjectionRelationType.CONTAINS_PAYLOAD, ProjectionRelationType.PROJECTED_FROM_EVENT})),
        StructuralEventMapping("source.item.versioned", True, frozenset({ProjectionNodeType.SOURCE_ITEM, ProjectionNodeType.AUTHORITY_VERSION, ProjectionNodeType.LEDGER_EVENT}), frozenset({ProjectionRelationType.HAS_VERSION, ProjectionRelationType.PROJECTED_FROM_EVENT})),
        StructuralEventMapping("source.item.revised", True, frozenset({ProjectionNodeType.SOURCE_ITEM, ProjectionNodeType.SOURCE_REVISION, ProjectionNodeType.LEDGER_EVENT}), frozenset({ProjectionRelationType.HAS_REVISION, ProjectionRelationType.PROJECTED_FROM_EVENT})),
        StructuralEventMapping("source.revision.represented", True, frozenset({ProjectionNodeType.SOURCE_REVISION, ProjectionNodeType.SOURCE_REPRESENTATION, ProjectionNodeType.LEDGER_EVENT}), frozenset({ProjectionRelationType.HAS_REPRESENTATION, ProjectionRelationType.PROJECTED_FROM_EVENT})),
        StructuralEventMapping("signal.created", True, frozenset({ProjectionNodeType.SOURCE_REVISION, ProjectionNodeType.SIGNAL, ProjectionNodeType.LEDGER_EVENT}), frozenset({ProjectionRelationType.PRODUCED_SIGNAL, ProjectionRelationType.PROJECTED_FROM_EVENT})),
        StructuralEventMapping("lead.promoted", True, frozenset({ProjectionNodeType.SIGNAL, ProjectionNodeType.LEAD, ProjectionNodeType.LEDGER_EVENT}), frozenset({ProjectionRelationType.PROMOTED_TO_LEAD, ProjectionRelationType.PROJECTED_FROM_EVENT})),
        StructuralEventMapping("candidate.derived", False, frozenset({ProjectionNodeType.LEAD, ProjectionNodeType.AUTHORITY_AGGREGATE, ProjectionNodeType.LEDGER_EVENT}), frozenset({ProjectionRelationType.DERIVED_FROM, ProjectionRelationType.PROJECTED_FROM_EVENT})),
    )
    contract = StructuralMappingContract(
        mapping_id="newsroom.structural",
        mapping_version="mapping-v1",
        implementation_version="mapping-python-v1",
        ontology_contract_digest=ontology.contract_digest,
        mappings=mappings,
    )
    contract.validate_against(ontology)
    return contract
