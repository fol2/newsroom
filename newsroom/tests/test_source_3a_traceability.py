from __future__ import annotations

import ast
from pathlib import Path

from newsroom.sources import (
    EXECUTION_AUTHORITY_DISABLED,
    INCREMENT_3A_DEFERRED,
    INCREMENT_3A_EXCLUSIONS,
    INCREMENT_3A_TRACEABILITY,
)


def test_increment_3a_traceability_is_complete_and_explicit() -> None:
    assert len(INCREMENT_3A_TRACEABILITY) == 12
    assert all(key.startswith("3A-") for key in INCREMENT_3A_TRACEABILITY)
    assert all(value for value in INCREMENT_3A_TRACEABILITY.values())
    assert "LIVE_SOURCE_NETWORK_REQUEST_RSS_ATOM_JSON_DOCUMENT_OR_AGENDA_FETCH" in (
        INCREMENT_3A_EXCLUSIONS
    )
    assert "GENERIC_TRANSPORT_AND_PARSER_BOUNDARY_INCREMENT_3B" in (
        INCREMENT_3A_DEFERRED
    )
    assert EXECUTION_AUTHORITY_DISABLED == "FIXTURE_REPLAY_ONLY_DISABLED"


def test_increment_3a_modules_do_not_import_network_or_model_clients() -> None:
    root = Path(__file__).parents[1]
    paths = list((root / "sources").glob("*.py"))
    paths.extend(
        root / "authority" / name
        for name in (
            "_source_registry_system.py",
            "_source_registry_store.py",
            "_source_registry_store_common.py",
            "_source_registry_store_definitions.py",
            "_source_registry_store_lineage.py",
            "_source_registry_store_read.py",
            "_source_registry_store_integrity.py",
            "source_registry_system.py",
            "source_registry_migrations.py",
        )
    )
    banned = {
        "aiohttp",
        "feedparser",
        "httpx",
        "neo4j",
        "openai",
        "requests",
        "socket",
        "urllib.request",
    }
    imported: set[str] = set()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported.add(node.module)
    assert not {name for name in imported if name in banned}
