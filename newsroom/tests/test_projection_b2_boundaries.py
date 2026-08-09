from __future__ import annotations

from dataclasses import fields, is_dataclass
from functools import lru_cache
import inspect
from pathlib import Path

from .source_import_inventory import production_import_inventory

from newsroom.authority.neo4j_projection_system import (
    Neo4jProjectionAuthoritySystem,
    Neo4jStructuralProjector,
)
from newsroom.projection import neo4j as public_neo4j
from newsroom.projection.neo4j import (
    INCREMENT_1B2_TRACEABILITY,
    Neo4jProjectorConfig,
    StructuralActiveReadRequest,
    StructuralBatch,
    StructuralDeliveryRequest,
    StructuralGraphNodeView,
    StructuralGraphRelationView,
    StructuralGenerationValidationRequest,
    StructuralNode,
    StructuralRebuildRequest,
    StructuralRebuildResult,
    StructuralReadMetadata,
    StructuralReadRequest,
    StructuralReadResponse,
    StructuralRelation,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_PRIVATE_ADAPTER_IMPORTER = Path("newsroom/authority/_neo4j_projection_system.py")
_PRIVATE_DRIVER_IMPORTER = Path("newsroom/projection/neo4j/_adapter.py")
_FORBIDDEN_PUBLIC_FIELDS = {
    "cypher",
    "driver",
    "element_id",
    "internal_id",
    "labels",
    "neo4j_id",
    "properties",
    "query",
    "relation_name",
    "session",
}


@lru_cache(maxsize=1)
def _production_importers() -> tuple[frozenset[Path], frozenset[Path]]:
    adapter_importers: set[Path] = set()
    driver_importers: set[Path] = set()
    for relative, imports, parse_error in production_import_inventory():
        assert parse_error is None, f"{relative}: unreadable: {parse_error}"
        for _lineno, module in imports:
            if module == "newsroom.projection.neo4j._adapter":
                adapter_importers.add(relative)
            if module == "neo4j":
                driver_importers.add(relative)
    return frozenset(adapter_importers), frozenset(driver_importers)


def test_public_projector_exposes_only_bounded_structural_operations() -> None:
    methods = {
        name
        for name, value in vars(Neo4jStructuralProjector).items()
        if not name.startswith("_") and callable(value)
    }
    assert methods == {
        "deliver",
        "read",
        "read_active",
        "reconcile_active",
        "rebuild",
        "validate_generation",
    }
    assert set(Neo4jStructuralProjector.__slots__) == {
        "__deliver",
        "__read",
        "__read_active",
        "__reconcile_active",
        "__rebuild",
        "__validate",
    }
    assert "adapter" not in Neo4jProjectionAuthoritySystem.__slots__
    assert "driver" not in Neo4jProjectionAuthoritySystem.__slots__
    assert "cleanup" not in Neo4jProjectionAuthoritySystem.__slots__


def test_public_package_exposes_no_low_level_writer_or_arbitrary_cypher() -> None:
    public_names = set(public_neo4j.__all__)
    assert not {
        "_Neo4jAdapter",
        "_open_neo4j_adapter",
        "GraphDatabase",
        "bootstrap_schema",
        "cleanup_generation",
        "execute_cypher",
        "query",
        "run_cypher",
        "write_graph",
    } & public_names
    assert not any("cypher" in name.lower() for name in public_names)

    for name in public_names:
        value = getattr(public_neo4j, name)
        if inspect.isclass(value) and issubclass(value, BaseException):
            continue
        if inspect.isfunction(value) or inspect.isclass(value):
            parameters = set(inspect.signature(value).parameters)
            assert not _FORBIDDEN_PUBLIC_FIELDS & parameters


def test_public_typed_contracts_contain_no_internal_identity_or_property_maps() -> None:
    contracts = (
        Neo4jProjectorConfig,
        StructuralActiveReadRequest,
        StructuralBatch,
        StructuralDeliveryRequest,
        StructuralGraphNodeView,
        StructuralGraphRelationView,
        StructuralGenerationValidationRequest,
        StructuralNode,
        StructuralRebuildRequest,
        StructuralRebuildResult,
        StructuralReadMetadata,
        StructuralReadRequest,
        StructuralReadResponse,
        StructuralRelation,
    )
    for contract in contracts:
        assert is_dataclass(contract)
        names = {field.name for field in fields(contract)}
        assert not _FORBIDDEN_PUBLIC_FIELDS & names


def test_private_adapter_has_one_production_import_path() -> None:
    adapter_importers, _driver_importers = _production_importers()
    assert adapter_importers == {_PRIVATE_ADAPTER_IMPORTER}


def test_official_driver_is_imported_only_inside_private_adapter() -> None:
    _adapter_importers, driver_importers = _production_importers()
    assert driver_importers == {_PRIVATE_DRIVER_IMPORTER}


def test_traceability_names_permanent_boundary_service_and_operations_evidence() -> None:
    flattened = {
        reference
        for references in INCREMENT_1B2_TRACEABILITY.values()
        for reference in references
    }
    assert "newsroom.tests.test_projection_b2_boundaries" in flattened
    assert "newsroom.tests.test_projection_b2_neo4j_service" in flattened
    assert ".github.workflows.projection-b2-neo4j" in flattened
    assert "docs.operations.neo4j-b2-qualification" in flattened


def test_actual_service_workflow_masks_runtime_credentials() -> None:
    workflow = (
        _REPOSITORY_ROOT / ".github/workflows/projection-b2-neo4j.yml"
    ).read_text()
    assert "services:" not in workflow
    assert "NEO4J_AUTH: neo4j/" not in workflow
    assert "B2Disposable" not in workflow
    assert "secrets.token_urlsafe" in workflow
    assert 'echo "::add-mask::${NEO4J_ADMIN_PASSWORD}"' in workflow
    assert 'echo "::add-mask::${NEWSROOM_NEO4J_PROJECTOR_PASSWORD}"' in workflow
    assert "GITHUB_ENV" not in workflow
    assert '${RUNNER_TEMP}/newsroom-b2-neo4j-admin.env' in workflow
    assert '${RUNNER_TEMP}/newsroom-b2-neo4j-projector.env' in workflow
    assert 'chmod 600 "${admin_file}" "${projector_file}"' in workflow
    assert "docker run --detach" in workflow
    assert "--publish 127.0.0.1:7687:7687" in workflow
    assert "docker rm --force newsroom-b2-neo4j" in workflow
