from __future__ import annotations

import ast
from pathlib import Path

from newsroom.checks import (
    INCREMENT_3C_DEFERRED,
    INCREMENT_3C_EXCLUSIONS,
    INCREMENT_3C_TRACEABILITY,
)


def test_increment_3c_traceability_has_complete_unique_review_groups() -> None:
    assert len(INCREMENT_3C_TRACEABILITY) == 13
    assert len(INCREMENT_3C_TRACEABILITY) == len(set(INCREMENT_3C_TRACEABILITY))
    assert all(key.startswith("3C-") for key in INCREMENT_3C_TRACEABILITY)
    assert all(value for value in INCREMENT_3C_TRACEABILITY.values())

    flattened = {
        item
        for values in INCREMENT_3C_TRACEABILITY.values()
        for item in values
    }
    assert "newsroom.tests.test_check_3c_contracts" in flattened
    assert "newsroom.tests.test_check_3c_baselines" in flattened
    assert "newsroom.tests.test_check_3c_transitions" in flattened
    assert "newsroom.tests.test_check_3c_agenda" in flattened
    assert "newsroom.tests.test_check_3c_findings" in flattened
    assert "newsroom.tests.test_check_3c_traceability" in flattened
    assert "newsroom.tests.test_check_3c_admission" in flattened
    assert "newsroom.tests.test_check_3c_admission_findings" in flattened
    assert "newsroom.tests.test_check_3c_model_policies" in flattened
    assert "newsroom.tests.test_check_3c_concurrency" in flattened


def test_increment_3c_explicitly_excludes_later_authority_and_public_effects() -> None:
    required = {
        "REAL_NETWORK_OR_SOCKET_ACCESS",
        "DISCOVERY_SIGNAL_GATE_OR_LEAD_AUTHORITY_INCREMENT_3D",
        "NEO4J_DISCOVERY_LINEAGE_OR_HEALTH_INCREMENT_3E",
        "MODEL_GRAPHITI_EMBEDDING_SEARCH_OR_ARBITRARY_CYPHER",
        "SOURCE_SHADOW_CANARY_PRODUCTION_PUBLICATION_OR_SPENDING",
        "EDITORIAL_MATERIALITY_TRUTH_OR_NEWSWORTHINESS_DECISION",
        "PUBLIC_EFFECT",
    }
    assert required <= INCREMENT_3C_EXCLUSIONS
    assert {
        "DISCOVERY_SIGNAL_ADMISSION_INCREMENT_3D",
        "DETERMINISTIC_GATE_DECISIONS_INCREMENT_3D",
        "NEWS_LEAD_URGENCY_AND_WATCH_CONDITIONS_INCREMENT_3D",
        "DISCOVERY_LINEAGE_PROJECTION_AND_HEALTH_INCREMENT_3E",
    } <= INCREMENT_3C_DEFERRED


def test_checks_package_has_no_external_io_or_later_workflow_imports() -> None:
    root = Path(__file__).resolve().parents[1] / "checks"
    forbidden_import_roots = {
        "asyncio",
        "httpx",
        "neo4j",
        "requests",
        "socket",
        "urllib",
    }
    forbidden_newsroom_roots = {
        "newsroom.candidates",
        "newsroom.graph",
        "newsroom.leads",
        "newsroom.models",
        "newsroom.publication",
        "newsroom.signals",
    }

    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                names = {node.module or ""}
            else:
                continue
            assert not any(
                name.split(".", 1)[0] in forbidden_import_roots
                for name in names
            ), (path, names)
            assert not any(
                any(
                    name == forbidden or name.startswith(forbidden + ".")
                    for forbidden in forbidden_newsroom_roots
                )
                for name in names
            ), (path, names)
