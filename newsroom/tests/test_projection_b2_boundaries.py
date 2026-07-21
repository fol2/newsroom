from __future__ import annotations

import ast
from dataclasses import fields, is_dataclass
import inspect
from pathlib import Path

from newsroom.authority.neo4j_projection_system import (
    Neo4jProjectionAuthoritySystem,
    Neo4jStructuralProjector,
)
from newsroom.projection import neo4j as public_neo4j
from newsroom.projection.neo4j import (
    INCREMENT_1B2_TRACEABILITY,
    Neo4jProjectorConfig,
    StructuralBatch,
    StructuralDeliveryRequest,
    StructuralGraphNodeView,
    StructuralGraphRelationView,
    StructuralNode,
    StructuralRebuildRequest,
    StructuralRebuildResult,
    StructuralReadMetadata,
    StructuralReadRequest,
    StructuralReadResponse,
    StructuralRelation,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_PRODUCTION_ROOT = _REPOSITORY_ROOT / "newsroom"
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


def _production_python_files() -> tuple[Path, ...]:
    return tuple(
        path
        for path in sorted(_PRODUCTION_ROOT.rglob("*.py"))
        if "tests" not in path.parts and "__pycache__" not in path.parts
    )


def _relative(path: Path) -> Path:
    return path.relative_to(_REPOSITORY_ROOT)


def test_public_projector_exposes_only_delivery_read_and_rebuild() -> None:
    methods = {
        name
        for name, value in vars(Neo4jStructuralProjector).items()
        if not name.startswith("_") and callable(value)
    }
    assert methods == {"deliver", "read", "rebuild"}
    assert set(Neo4jStructuralProjector.__slots__) == {
        "__deliver",
        "__read",
        "__rebuild",
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
        StructuralBatch,
        StructuralDeliveryRequest,
        StructuralGraphNodeView,
        StructuralGraphRelationView,
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
    importers: set[Path] = set()
    for path in _production_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == (
                "newsroom.projection.neo4j._adapter"
            ):
                importers.add(_relative(path))
            if isinstance(node, ast.Import):
                if any(
                    alias.name == "newsroom.projection.neo4j._adapter"
                    for alias in node.names
                ):
                    importers.add(_relative(path))
    assert importers == {_PRIVATE_ADAPTER_IMPORTER}


def test_official_driver_is_imported_only_inside_private_adapter() -> None:
    importers: set[Path] = set()
    for path in _production_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "neo4j":
                importers.add(_relative(path))
            if isinstance(node, ast.Import) and any(
                alias.name == "neo4j" for alias in node.names
            ):
                importers.add(_relative(path))
    assert importers == {_PRIVATE_DRIVER_IMPORTER}


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
    assert '>> "${GITHUB_ENV}"' in workflow
    assert "docker run --detach" in workflow
    assert "--publish 127.0.0.1:7687:7687" in workflow
    assert "docker rm --force newsroom-b2-neo4j" in workflow
