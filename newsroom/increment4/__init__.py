"""Deterministic Increment 4 admitted entity/relation proof contracts."""

from importlib import import_module as _import_module

from .contracts import (
    INCREMENT4_ADMITTED_FAMILY_AGGREGATE_ID,
    INCREMENT4_ADMITTED_FAMILY_ID,
    INCREMENT4_ADMITTED_FAMILY_VERSION,
    INCREMENT4_ADMITTED_MAPPING_ID,
    INCREMENT4_ADMITTED_MAPPING_VERSION,
    INCREMENT4_ADMITTED_ONTOLOGY_ID,
    INCREMENT4_ADMITTED_ONTOLOGY_VERSION,
    INCREMENT4_ADMITTED_PROJECTOR_VERSION,
    increment4_admitted_contract_registry,
    increment4_admitted_family_v1,
    increment4_admitted_mapping_v1,
    increment4_admitted_ontology_v1,
)
from .models import (
    Increment4AdmittedProjectionSnapshot,
    Increment4EntityProjectionState,
    Increment4ProofContractError,
    Increment4RelationProjectionState,
    sorted_snapshot,
)
from .projection import build_increment4_admitted_batches


_NEO4J_EXPORTS = frozenset(
    {
        "Increment4Neo4jActiveReadRequest",
        "Increment4Neo4jBuildRequest",
        "Increment4Neo4jBuildResult",
        "Increment4Neo4jController",
        "Increment4Neo4jGenerationStatus",
        "Increment4Neo4jProofError",
    }
)


def __getattr__(name: str):
    if name in _NEO4J_EXPORTS:
        module = _import_module(f"{__name__}.neo4j")
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(name)


__all__ = [
    "INCREMENT4_ADMITTED_FAMILY_AGGREGATE_ID",
    "INCREMENT4_ADMITTED_FAMILY_ID",
    "INCREMENT4_ADMITTED_FAMILY_VERSION",
    "INCREMENT4_ADMITTED_MAPPING_ID",
    "INCREMENT4_ADMITTED_MAPPING_VERSION",
    "INCREMENT4_ADMITTED_ONTOLOGY_ID",
    "INCREMENT4_ADMITTED_ONTOLOGY_VERSION",
    "INCREMENT4_ADMITTED_PROJECTOR_VERSION",
    "Increment4AdmittedProjectionSnapshot",
    "Increment4Neo4jActiveReadRequest",
    "Increment4Neo4jBuildRequest",
    "Increment4Neo4jBuildResult",
    "Increment4Neo4jController",
    "Increment4Neo4jGenerationStatus",
    "Increment4Neo4jProofError",
    "Increment4EntityProjectionState",
    "Increment4ProofContractError",
    "Increment4RelationProjectionState",
    "build_increment4_admitted_batches",
    "increment4_admitted_contract_registry",
    "increment4_admitted_family_v1",
    "increment4_admitted_mapping_v1",
    "increment4_admitted_ontology_v1",
    "sorted_snapshot",
]
