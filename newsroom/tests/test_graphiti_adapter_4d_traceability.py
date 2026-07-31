from __future__ import annotations

import importlib
import re
from pathlib import Path

from newsroom.graphiti_adapter import (
    INCREMENT_4D_ADR_ANCHORS,
    INCREMENT_4D_DEFERRED,
    INCREMENT_4D_EXCLUSIONS,
    INCREMENT_4D_TRACEABILITY,
    REAL_GRAPHITI_RUNTIME_ENABLED,
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
        "DREC-070",
        "DREC-071",
        "DREC-074",
        "DREC-076",
        "DREC-077",
        "GRAG-020",
        "GRAG-021",
        "GRAG-022",
        "GRAG-023",
        "GRAG-024",
        "GRAG-025",
        "GRAG-026",
        "GRAG-027",
        "GRAG-028",
        "GRAG-034",
        "GRAG-035",
        "GRPROD-010",
        "GRPROD-011",
        "GRPROD-012",
        "GRPROD-013",
        "GRPROD-014",
        "GRPROD-015",
        "GRPROD-016",
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


def test_increment_4d_traceability_is_exact_and_non_overclaiming() -> None:
    identifiers = tuple(row.requirement_id for row in INCREMENT_4D_TRACEABILITY)
    assert len(identifiers) == len(set(identifiers))
    assert frozenset(identifiers) == _REQUIRED_IDS
    statuses = {row.requirement_id: row.status for row in INCREMENT_4D_TRACEABILITY}
    assert statuses["GRAG-020"].startswith("IMPLEMENTED_PROPOSAL_ONLY")
    assert statuses["GRAG-021"].startswith("IMPLEMENTED_LOGICALLY_ISOLATED")
    assert statuses["GRAG-025"].endswith("DEFERRED_4E")
    assert statuses["GRPROD-015"].startswith("IMPLEMENTED_EVALUATION_PRODUCTION")
    assert "DISABLED_AND_UNQUALIFIED" in statuses["GRPROD-016"]
    assert REAL_GRAPHITI_RUNTIME_ENABLED is False


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
    for row in INCREMENT_4D_TRACEABILITY:
        assert _resolve_symbol(row.implementation_symbol) is not None
        assert (root / row.test_node).is_file(), row.test_node


def test_accepted_adrs_exclusions_and_deferred_work_are_retained() -> None:
    root = Path(__file__).resolve().parents[2]
    assert INCREMENT_4D_ADR_ANCHORS == {
        "ADR-0001",
        "ADR-0002",
        "ADR-0004",
        "ADR-0005",
    }
    for number in ("0001", "0002", "0004", "0005"):
        assert tuple((root / "docs" / "adr").glob(f"{number}-*.md"))
    assert any("real Graphiti" in item for item in INCREMENT_4D_EXCLUSIONS)
    assert any("arbitrary Cypher" in item for item in INCREMENT_4D_EXCLUSIONS)
    assert any("Increment 4E" in item for item in INCREMENT_4D_DEFERRED)
    assert any("runtime decision packet" in item for item in INCREMENT_4D_DEFERRED)


def test_operations_and_review_retain_real_runtime_and_stop_boundaries() -> None:
    root = Path(__file__).resolve().parents[2]
    operations = (
        root / "docs/operations/increment-4d-graphiti-proposal-adapter.md"
    ).read_text(encoding="utf-8")
    review = (
        root / "docs/research/2026-07-31-increment-4d-substantive-review.md"
    ).read_text(encoding="utf-8")
    for phrase in (
        "schema v16",
        "graphiti.adapter.attempt.execute",
        "REAL_GRAPHITI_RUNTIME_ENABLED = False",
        "persist-before-admission",
        "DENY_ALL",
        "replay survives complete workspace loss",
        "Issue #229 / Increment 4E must not begin",
    ):
        assert phrase in operations
    for phrase in (
        "P1 findings:             0",
        "P2 findings corrected:  17",
        "P2-17",
        "Unresolved local P1/P2:  0",
        "real Graphiti/model execution remains disabled and unqualified",
        "This document is not final merge evidence",
        "Issue #229 remains blocked",
    ):
        assert phrase in review
