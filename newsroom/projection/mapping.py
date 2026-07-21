from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.types import require_token

from .models import ProjectionContractError
from .ontology import OntologyContract, ProjectionNodeType, ProjectionRelationType


class ProjectionIdentitySource(StrEnum):
    AGGREGATE = "AGGREGATE"
    AGGREGATE_VERSION = "AGGREGATE_VERSION"
    EVENT = "EVENT"
    PAYLOAD = "PAYLOAD"
    PAYLOAD_FIELD = "PAYLOAD_FIELD"


@dataclass(frozen=True, slots=True)
class StructuralNodeBinding:
    alias: str
    node_type: ProjectionNodeType
    identity_source: ProjectionIdentitySource
    payload_field: str | None = None

    def __post_init__(self) -> None:
        require_token(self.alias, field="projection_node_alias")
        if not isinstance(self.node_type, ProjectionNodeType):
            raise ProjectionContractError("node binding type must be typed")
        if not isinstance(self.identity_source, ProjectionIdentitySource):
            raise ProjectionContractError("node identity source must be typed")
        if self.identity_source is ProjectionIdentitySource.PAYLOAD_FIELD:
            require_token(self.payload_field or "", field="projection_payload_field")
        elif self.payload_field is not None:
            raise ProjectionContractError(
                "payload_field applies only to PAYLOAD_FIELD identities"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "alias": self.alias,
            "node_type": self.node_type.value,
            "identity_source": self.identity_source.value,
            "payload_field": self.payload_field,
        }


@dataclass(frozen=True, slots=True)
class StructuralRelationBinding:
    relation_type: ProjectionRelationType
    source_alias: str
    target_alias: str

    def __post_init__(self) -> None:
        if not isinstance(self.relation_type, ProjectionRelationType):
            raise ProjectionContractError("relation binding type must be typed")
        require_token(self.source_alias, field="projection_relation_source_alias")
        require_token(self.target_alias, field="projection_relation_target_alias")
        if self.source_alias == self.target_alias:
            raise ProjectionContractError("structural relation endpoints must differ")

    def canonical_value(self) -> dict[str, object]:
        return {
            "relation_type": self.relation_type.value,
            "source_alias": self.source_alias,
            "target_alias": self.target_alias,
        }


@dataclass(frozen=True, slots=True)
class StructuralEventMapping:
    event_type: str
    required: bool
    nodes: tuple[StructuralNodeBinding, ...]
    relations: tuple[StructuralRelationBinding, ...]

    def __post_init__(self) -> None:
        require_token(self.event_type, field="structural_event_type")
        if not isinstance(self.required, bool):
            raise ProjectionContractError("mapping required flag must be boolean")
        if not isinstance(self.nodes, tuple) or not self.nodes:
            raise ProjectionContractError("mapping node bindings must be non-empty")
        if not isinstance(self.relations, tuple) or not self.relations:
            raise ProjectionContractError("mapping relation bindings must be non-empty")
        aliases = [item.alias for item in self.nodes]
        if len(aliases) != len(set(aliases)):
            raise ProjectionContractError("mapping node aliases must be unique")
        known = set(aliases)
        for relation in self.relations:
            if relation.source_alias not in known or relation.target_alias not in known:
                raise ProjectionContractError(
                    "mapping relation references unknown node alias"
                )
        relation_keys = [
            (item.relation_type, item.source_alias, item.target_alias)
            for item in self.relations
        ]
        if len(relation_keys) != len(set(relation_keys)):
            raise ProjectionContractError("mapping relation bindings must be unique")

    @property
    def node_types(self) -> frozenset[ProjectionNodeType]:
        return frozenset(item.node_type for item in self.nodes)

    @property
    def relation_types(self) -> frozenset[ProjectionRelationType]:
        return frozenset(item.relation_type for item in self.relations)

    def canonical_value(self) -> dict[str, object]:
        return {
            "event_type": self.event_type,
            "required": self.required,
            "nodes": [
                item.canonical_value()
                for item in sorted(self.nodes, key=lambda value: value.alias)
            ],
            "relations": [
                item.canonical_value()
                for item in sorted(
                    self.relations,
                    key=lambda value: (
                        value.relation_type.value,
                        value.source_alias,
                        value.target_alias,
                    ),
                )
            ],
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
        node_definitions = {item.node_type: item for item in ontology.nodes}
        relation_definitions = {
            item.relation_type: item for item in ontology.relations
        }
        for mapping in self.mappings:
            if not mapping.node_types <= ontology.node_types:
                raise ProjectionContractError("mapping references unknown node type")
            if not mapping.relation_types <= ontology.relation_types:
                raise ProjectionContractError("mapping references unknown relation type")
            aliases = {item.alias: item for item in mapping.nodes}
            for binding in mapping.nodes:
                if binding.node_type not in node_definitions:
                    raise ProjectionContractError("mapping node definition is absent")
            for relation in mapping.relations:
                definition = relation_definitions[relation.relation_type]
                source_type = aliases[relation.source_alias].node_type
                target_type = aliases[relation.target_alias].node_type
                if source_type not in definition.source_types:
                    raise ProjectionContractError(
                        "mapping relation source type is not allowed"
                    )
                if target_type not in definition.target_types:
                    raise ProjectionContractError(
                        "mapping relation target type is not allowed"
                    )

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


def _node(
    alias: str,
    node_type: ProjectionNodeType,
    identity_source: ProjectionIdentitySource,
    payload_field: str | None = None,
) -> StructuralNodeBinding:
    return StructuralNodeBinding(alias, node_type, identity_source, payload_field)


def _relation(
    relation_type: ProjectionRelationType,
    source_alias: str,
    target_alias: str,
) -> StructuralRelationBinding:
    return StructuralRelationBinding(relation_type, source_alias, target_alias)


def native_structural_mapping_v1(ontology: OntologyContract) -> StructuralMappingContract:
    mappings = (
        StructuralEventMapping(
            "authority.aggregate.versioned",
            True,
            (
                _node("aggregate", ProjectionNodeType.AUTHORITY_AGGREGATE, ProjectionIdentitySource.AGGREGATE),
                _node("version", ProjectionNodeType.AUTHORITY_VERSION, ProjectionIdentitySource.AGGREGATE_VERSION),
                _node("payload", ProjectionNodeType.PAYLOAD, ProjectionIdentitySource.PAYLOAD),
                _node("event", ProjectionNodeType.LEDGER_EVENT, ProjectionIdentitySource.EVENT),
            ),
            (
                _relation(ProjectionRelationType.HAS_VERSION, "aggregate", "version"),
                _relation(ProjectionRelationType.CONTAINS_PAYLOAD, "version", "payload"),
                _relation(ProjectionRelationType.PROJECTED_FROM_EVENT, "aggregate", "event"),
                _relation(ProjectionRelationType.PROJECTED_FROM_EVENT, "version", "event"),
                _relation(ProjectionRelationType.PROJECTED_FROM_EVENT, "payload", "event"),
            ),
        ),
        StructuralEventMapping(
            "source.item.versioned",
            True,
            (
                _node("item", ProjectionNodeType.SOURCE_ITEM, ProjectionIdentitySource.AGGREGATE),
                _node("version", ProjectionNodeType.AUTHORITY_VERSION, ProjectionIdentitySource.AGGREGATE_VERSION),
                _node("event", ProjectionNodeType.LEDGER_EVENT, ProjectionIdentitySource.EVENT),
            ),
            (
                _relation(ProjectionRelationType.HAS_VERSION, "item", "version"),
                _relation(ProjectionRelationType.PROJECTED_FROM_EVENT, "item", "event"),
                _relation(ProjectionRelationType.PROJECTED_FROM_EVENT, "version", "event"),
            ),
        ),
        StructuralEventMapping(
            "source.item.revised",
            True,
            (
                _node("item", ProjectionNodeType.SOURCE_ITEM, ProjectionIdentitySource.PAYLOAD_FIELD, "source_item_id"),
                _node("revision", ProjectionNodeType.SOURCE_REVISION, ProjectionIdentitySource.AGGREGATE),
                _node("event", ProjectionNodeType.LEDGER_EVENT, ProjectionIdentitySource.EVENT),
            ),
            (
                _relation(ProjectionRelationType.HAS_REVISION, "item", "revision"),
                _relation(ProjectionRelationType.PROJECTED_FROM_EVENT, "revision", "event"),
            ),
        ),
        StructuralEventMapping(
            "source.revision.represented",
            True,
            (
                _node("revision", ProjectionNodeType.SOURCE_REVISION, ProjectionIdentitySource.PAYLOAD_FIELD, "source_revision_id"),
                _node("representation", ProjectionNodeType.SOURCE_REPRESENTATION, ProjectionIdentitySource.AGGREGATE),
                _node("event", ProjectionNodeType.LEDGER_EVENT, ProjectionIdentitySource.EVENT),
            ),
            (
                _relation(ProjectionRelationType.HAS_REPRESENTATION, "revision", "representation"),
                _relation(ProjectionRelationType.PROJECTED_FROM_EVENT, "representation", "event"),
            ),
        ),
        StructuralEventMapping(
            "signal.created",
            True,
            (
                _node("revision", ProjectionNodeType.SOURCE_REVISION, ProjectionIdentitySource.PAYLOAD_FIELD, "source_revision_id"),
                _node("signal", ProjectionNodeType.SIGNAL, ProjectionIdentitySource.AGGREGATE),
                _node("event", ProjectionNodeType.LEDGER_EVENT, ProjectionIdentitySource.EVENT),
            ),
            (
                _relation(ProjectionRelationType.PRODUCED_SIGNAL, "revision", "signal"),
                _relation(ProjectionRelationType.PROJECTED_FROM_EVENT, "signal", "event"),
            ),
        ),
        StructuralEventMapping(
            "lead.promoted",
            True,
            (
                _node("signal", ProjectionNodeType.SIGNAL, ProjectionIdentitySource.PAYLOAD_FIELD, "signal_id"),
                _node("lead", ProjectionNodeType.LEAD, ProjectionIdentitySource.AGGREGATE),
                _node("event", ProjectionNodeType.LEDGER_EVENT, ProjectionIdentitySource.EVENT),
            ),
            (
                _relation(ProjectionRelationType.PROMOTED_TO_LEAD, "signal", "lead"),
                _relation(ProjectionRelationType.PROJECTED_FROM_EVENT, "lead", "event"),
            ),
        ),
        StructuralEventMapping(
            "candidate.derived",
            False,
            (
                _node("lead", ProjectionNodeType.LEAD, ProjectionIdentitySource.PAYLOAD_FIELD, "lead_id"),
                _node("candidate", ProjectionNodeType.AUTHORITY_AGGREGATE, ProjectionIdentitySource.AGGREGATE),
                _node("event", ProjectionNodeType.LEDGER_EVENT, ProjectionIdentitySource.EVENT),
            ),
            (
                _relation(ProjectionRelationType.DERIVED_FROM, "candidate", "lead"),
                _relation(ProjectionRelationType.PROJECTED_FROM_EVENT, "candidate", "event"),
            ),
        ),
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
