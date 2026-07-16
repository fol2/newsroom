from __future__ import annotations

import ast
from pathlib import Path

import newsroom.authority as authority
from newsroom.authority import INCREMENT_1A_TRACEABILITY


def test_increment_1a_traceability_has_required_authority_records() -> None:
    required = {
        "ADR-0001",
        "ADR-0002",
        "ADR-0004",
        "DREC-001",
        "DREC-016",
        "DREC-070",
        "GRAG-001",
        "GRAG-002",
        "GRAG-003",
        "GRAG-004",
        "GRAG-005",
        "GRAG-010",
        "GRAG-030",
        "GRPROD-005",
        "GRPROD-020",
    }

    assert required <= set(INCREMENT_1A_TRACEABILITY)
    assert all(INCREMENT_1A_TRACEABILITY[item] for item in required)


def test_authority_package_has_no_graphiti_neo4j_or_legacy_imports() -> None:
    package_dir = Path(authority.__file__).resolve().parent
    imported: set[str] = set()
    for source_path in package_dir.glob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

    forbidden_prefixes = (
        "neo4j",
        "graphiti",
        "newsroom.news_pool",
        "newsroom.event_manager",
        "newsroom.runner",
        "newsroom.gateway",
    )
    assert not {
        module
        for module in imported
        if module.startswith(forbidden_prefixes)
    }
