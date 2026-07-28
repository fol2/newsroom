from __future__ import annotations

import ast
from pathlib import Path

from newsroom.discovery import (
    INCREMENT_3D_DEFERRED,
    INCREMENT_3D_EXCLUSIONS,
    INCREMENT_3D_TRACEABILITY,
)


def test_increment_3d_traceability_has_complete_unique_review_groups() -> None:
    assert len(INCREMENT_3D_TRACEABILITY) == 15
    assert len(INCREMENT_3D_TRACEABILITY) == len(set(INCREMENT_3D_TRACEABILITY))
    assert all(key.startswith("3D-") for key in INCREMENT_3D_TRACEABILITY)
    assert all(value for value in INCREMENT_3D_TRACEABILITY.values())

    flattened = {
        item
        for values in INCREMENT_3D_TRACEABILITY.values()
        for item in values
    }
    assert "newsroom.tests.test_discovery_3d_contracts" in flattened
    assert "newsroom.tests.test_discovery_3d_payloads" in flattened
    assert "newsroom.tests.test_discovery_3d_policy" in flattened
    assert "newsroom.tests.test_discovery_3d_traceability" in flattened


def test_increment_3d_explicitly_excludes_later_authority_and_public_effects() -> None:
    required = {
        "REAL_NETWORK_OR_SOCKET_ACCESS",
        "TRIAGE_WORK_ITEM_RETRIEVAL_OR_MODEL_PROPOSAL",
        "EVENT_HYPOTHESIS_STORY_CANDIDATE_OR_EVIDENCE_HANDOFF_AUTHORITY",
        "NEO4J_DISCOVERY_LINEAGE_OR_HEALTH_INCREMENT_3E",
        "MODEL_GRAPHITI_EMBEDDING_SEARCH_OR_ARBITRARY_CYPHER",
        "NUMERIC_GLOBAL_SCORE_MEDIA_VOLUME_OR_CATEGORY_QUOTA_AUTHORITY",
        "FACTUAL_TRUTH_EVIDENCE_OR_PUBLICATION_AUTHORITY",
        "PUBLIC_EFFECT",
    }
    assert required <= INCREMENT_3D_EXCLUSIONS
    assert {
        "DISCOVERY_LINEAGE_PROJECTION_AND_HEALTH_INCREMENT_3E",
        "FULL_TRIAGE_WORK_ITEMS_RETRIEVAL_AND_MODEL_PROPOSALS_LATER_INCREMENT",
        "EVENT_HYPOTHESIS_AND_CANDIDATE_AUTHORITY_LATER_INCREMENT",
        "EDITORIAL_LEAD_DISPOSITIONS_LATER_INCREMENT",
    } <= INCREMENT_3D_DEFERRED


def test_discovery_package_has_no_external_io_or_later_workflow_imports() -> None:
    root = Path(__file__).resolve().parents[1] / "discovery"
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
        "newsroom.evidence",
        "newsroom.graph",
        "newsroom.models",
        "newsroom.publication",
        "newsroom.search",
        "newsroom.triage",
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


def test_increment_3d_operations_review_and_transport_cleanup_are_retained() -> None:
    root = Path(__file__).resolve().parents[2]
    required = (
        root / "docs/operations/increment-3d-signal-lead-authority.md",
        root / "docs/research/2026-07-28-increment-3d-design-record.md",
        root / "docs/research/2026-07-28-increment-3d-substantive-review.md",
    )
    assert all(path.is_file() and path.stat().st_size > 1000 for path in required)

    forbidden = (
        root / ".github/increment-3d-store-manifest.json",
        root / ".github/increment-3d-store-payload",
        root / ".github/workflows/materialize-increment-3d-store.yml",
        root / ".github/workflows/export-increment-3d-recovery-source.yml",
    )
    assert all(not path.exists() for path in forbidden)
