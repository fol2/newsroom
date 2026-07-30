from __future__ import annotations

import importlib
import re
from pathlib import Path

from newsroom.relations import (
    INCREMENT_4C_ADR_ANCHORS,
    INCREMENT_4C_DEFERRED,
    INCREMENT_4C_EXCLUSIONS,
    INCREMENT_4C_TRACEABILITY,
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
        "DREC-043",
        "DREC-054",
        "DREC-070",
        "DREC-071",
        "DREC-073",
        "DREC-074",
        "DREC-076",
        "DREC-077",
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
        "GRAG-031",
        "GRAG-032",
        "GRAG-033",
        "GRAG-034",
        "GRAG-035",
        "GRPROD-003",
        "GRPROD-005",
        "GRPROD-013",
        "GRPROD-016",
        "GRPROD-020",
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


def test_increment_4c_traceability_is_exact_and_non_overclaiming() -> None:
    identifiers = tuple(row.requirement_id for row in INCREMENT_4C_TRACEABILITY)
    assert len(identifiers) == len(set(identifiers))
    assert frozenset(identifiers) == _REQUIRED_IDS
    status = {row.requirement_id: row.status for row in INCREMENT_4C_TRACEABILITY}
    assert status["GRAG-013"].startswith("IMPLEMENTED_SUBJECT_OBJECT")
    assert status["GRAG-015"] == (
        "IMPLEMENTED_MATERIAL_UNRESOLVED_IDENTITY_ADMISSION_BLOCK"
    )
    assert status["GRAG-021"].endswith("DEFERRED_4D")
    assert status["GRAG-031"].startswith("HYBRID_RETRIEVAL_DEFERRED")
    assert status["GRPROD-016"].endswith("DEFERRED_4E")


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
    for row in INCREMENT_4C_TRACEABILITY:
        assert _resolve_symbol(row.implementation_symbol) is not None
        assert (root / row.test_node).is_file(), row.test_node


def test_accepted_adrs_exclusions_and_deferred_work_are_retained() -> None:
    root = Path(__file__).resolve().parents[2]
    assert INCREMENT_4C_ADR_ANCHORS == {
        "ADR-0001",
        "ADR-0002",
        "ADR-0004",
        "ADR-0005",
    }
    for number in ("0001", "0002", "0004", "0005"):
        assert tuple((root / "docs" / "adr").glob(f"{number}-*.md"))
    assert any("real Graphiti" in item for item in INCREMENT_4C_EXCLUSIONS)
    assert any("Increment 4D" in item for item in INCREMENT_4C_EXCLUSIONS)
    assert any("actual-Neo4j" in item for item in INCREMENT_4C_DEFERRED)
    assert any("runtime decision packet" in item for item in INCREMENT_4C_DEFERRED)


def test_operations_and_substantive_review_retain_stop_and_evidence_boundaries() -> None:
    root = Path(__file__).resolve().parents[2]
    operations = (
        root / "docs/operations/increment-4c-general-relation-authority.md"
    ).read_text(encoding="utf-8")
    review = (
        root / "docs/research/2026-07-30-increment-4c-substantive-review.md"
    ).read_text(encoding="utf-8")

    for phrase in (
        "schema v15",
        "editorial.relation.proposal.record",
        "A material dependency blocks `ACCEPT`",
        "rebuild_governed_editorial_relation_current_projection",
        "TOMBSTONED",
        "[HOLD v1, ACCEPT v2]",
        "Issue #228 / Increment 4D must not begin",
        "real Graphiti, model or embedding execution",
    ):
        assert phrase in operations
    for phrase in (
        "P1 findings:             0",
        "P2 findings corrected:  16",
        "P2-16",
        "139 passed",
        "Unresolved local P1/P2:  0",
        "This document is not final merge evidence",
        "Issue #228 remains blocked",
    ):
        assert phrase in review
