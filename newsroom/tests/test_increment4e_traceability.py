from __future__ import annotations

import importlib
import re
from pathlib import Path

from newsroom.graphiti_adapter import REAL_GRAPHITI_RUNTIME_ENABLED
from newsroom.increment4 import (
    INCREMENT_4E_ADR_ANCHORS,
    INCREMENT_4E_DEFERRED,
    INCREMENT_4E_EXCLUSIONS,
    INCREMENT_4E_TRACEABILITY,
)


_REQUIRED_IDS = frozenset(
    {
        "DREC-001",
        "DREC-003",
        "DREC-004",
        "DREC-005",
        "DREC-006",
        "DREC-007",
        "DREC-016",
        "DREC-041",
        "DREC-042",
        "DREC-045",
        "DREC-054",
        "DREC-070",
        "DREC-071",
        "DREC-073",
        "DREC-074",
        "DREC-076",
        "DREC-077",
        "GRAG-002",
        "GRAG-004",
        "GRAG-005",
        "GRAG-010",
        "GRAG-011",
        "GRAG-012",
        "GRAG-013",
        "GRAG-014",
        "GRAG-015",
        "GRAG-016",
        "GRAG-020",
        "GRAG-021",
        "GRAG-022",
        "GRAG-023",
        "GRAG-024",
        "GRAG-025",
        "GRAG-026",
        "GRAG-027",
        "GRAG-028",
        "GRAG-030",
        "GRAG-032",
        "GRAG-033",
        "GRAG-034",
        "GRAG-035",
        "GRAG-041",
        "GRAG-043",
        "GRAG-050",
        "GRAG-056",
        "GRAG-057",
        "GRAG-058",
        "GRPROD-003",
        "GRPROD-005",
        "GRPROD-010",
        "GRPROD-011",
        "GRPROD-012",
        "GRPROD-013",
        "GRPROD-014",
        "GRPROD-015",
        "GRPROD-016",
        "GRPROD-020",
        "GRPROD-024",
        "GRPROD-030",
        "GRPROD-031",
        "GRPROD-032",
    }
)


def _resolve_symbol(reference: str) -> object:
    module_name, path = reference.split(":", 1)
    value: object = importlib.import_module(module_name)
    for component in path.split("."):
        value = getattr(value, component)
    return value


def _requirement_ids(path: Path, prefix: str) -> frozenset[str]:
    text = path.read_text(encoding="utf-8")
    return frozenset(re.findall(rf"\*\*({prefix}-\d{{3}})\s", text))


def test_increment_4e_traceability_is_exact_and_non_overclaiming() -> None:
    identifiers = tuple(row.requirement_id for row in INCREMENT_4E_TRACEABILITY)
    assert len(identifiers) == len(set(identifiers))
    assert frozenset(identifiers) == _REQUIRED_IDS
    statuses = {row.requirement_id: row.status for row in INCREMENT_4E_TRACEABILITY}
    assert statuses["GRAG-015"].startswith("IMPLEMENTED_MATERIAL_UNRESOLVED")
    assert statuses["GRAG-021"].startswith("IMPLEMENTED_COMPLETE_PROPOSAL_WORKSPACE_LOSS")
    assert statuses["GRAG-028"].startswith("IMPLEMENTED_TOMBSTONE_PURGE")
    assert statuses["GRPROD-016"].startswith("IMPLEMENTED_PERMANENT_AUTHENTICATED")
    assert statuses["GRPROD-030"].endswith("DEFERRED")
    assert REAL_GRAPHITI_RUNTIME_ENABLED is True


def test_traceability_uses_only_accepted_requirement_identifiers() -> None:
    root = Path(__file__).resolve().parents[2]
    accepted = (
        _requirement_ids(
            root / "docs/specs/editorial-automation/discovery-record-semantics.md",
            "DREC",
        )
        | _requirement_ids(
            root
            / "docs/specs/editorial-automation/governed-graphrag-and-knowledge-projection.md",
            "GRAG",
        )
        | _requirement_ids(
            root
            / "docs/specs/editorial-automation/graphrag-native-production-deployment.md",
            "GRPROD",
        )
    )
    assert _REQUIRED_IDS <= accepted


def test_every_traceability_symbol_and_test_path_exists() -> None:
    root = Path(__file__).resolve().parents[2]
    for row in INCREMENT_4E_TRACEABILITY:
        assert _resolve_symbol(row.implementation_symbol) is not None
        assert (root / row.test_node).is_file(), row.test_node


def test_accepted_adrs_exclusions_and_deferred_work_are_retained() -> None:
    root = Path(__file__).resolve().parents[2]
    assert INCREMENT_4E_ADR_ANCHORS == {
        "ADR-0001",
        "ADR-0002",
        "ADR-0004",
        "ADR-0005",
    }
    for number in ("0001", "0002", "0004", "0005"):
        assert tuple((root / "docs" / "adr").glob(f"{number}-*.md"))
    assert any("real Graphiti" in item for item in INCREMENT_4E_EXCLUSIONS)
    assert any("publication" in item for item in INCREMENT_4E_EXCLUSIONS)
    assert any("runtime decision packet" in item for item in INCREMENT_4E_DEFERRED)
    assert any("Increment 5" in item for item in INCREMENT_4E_DEFERRED)


def test_operations_and_review_retain_proof_rollback_and_stop_boundaries() -> None:
    root = Path(__file__).resolve().parents[2]
    operations = (
        root / "docs/operations/increment-4e-bilingual-actual-neo4j-proof.md"
    ).read_text(encoding="utf-8")
    review = (
        root / "docs/research/2026-07-31-increment-4e-substantive-review.md"
    ).read_text(encoding="utf-8")
    for phrase in (
        "graph.increment4.admitted",
        "downstream entity and relation authority to the approved replay output",
        "[HOLD v1, ACCEPT v2]",
        "zero-node, zero-relation admitted generation",
        "replay cannot resurrect",
        "test_increment4e_neo4j_service.py",
        "Increment 5 must not start",
        "Real Graphiti, model and embedding execution remains unqualified in this unit",
    ):
        assert phrase in operations
    for phrase in (
        "P1 findings:             0",
        "P2 findings corrected:  18",
        "P2-18",
        "Unresolved local P1/P2:  0",
        "This document is not final merge evidence",
        "real Graphiti, model, embedding, live-source, publication or production runtime",
        "Issue #229 and parent #144 remain open",
    ):
        assert phrase in review
