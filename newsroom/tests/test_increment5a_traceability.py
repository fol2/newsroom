from __future__ import annotations

from collections import Counter
from pathlib import Path
import re

import pytest

from newsroom.increment5._traceability_anchors import ANCHOR_BY_REQUIREMENT
from newsroom.increment5._traceability_model import (
    ALL_REQUIREMENTS,
    CROSS_REQUEST_INTEGRATION_REQUIREMENTS,
    DEFERRED_TO_5C_REQUIREMENTS,
    DEFERRED_TO_5E_REQUIREMENTS,
    DEFERRED_TO_INCREMENT_6_REQUIREMENTS,
    DEFERRED_TO_INCREMENT_8_REQUIREMENTS,
    DELIVERED_IN_5A_REQUIREMENTS,
    DELIVERY_GROUPS,
    DEVAL_REQUIREMENTS,
    DOPS_REQUIREMENTS,
    INHERITED_AUTHORITY,
    OPERATIONAL_DOPS,
    OUTSIDE_INCREMENT_5_REQUIREMENTS,
    REQUEST_RETRIEVAL_REQUIREMENTS,
    Increment5DeliveryTrace,
    Increment5TraceabilityRow,
)
from newsroom.increment5.traceability import (
    INCREMENT_5_TRACEABILITY,
    validate_increment5_traceability,
)


ROOT = Path(__file__).resolve().parents[2]
DEVAL_SPEC = (
    ROOT
    / "docs/specs/editorial-automation/discovery-shadow-evaluation.md"
)
DOPS_SPEC = (
    ROOT
    / "docs/specs/editorial-automation/discovery-reliability-and-operations.md"
)
PLAN = (
    ROOT
    / "docs/plans/2026-08-06-010-increment-5-scope-and-gates-amendment.md"
)
HUMAN_MAP = ROOT / "docs/traceability/increment-5-production-retrieval.md"


def _spec_requirements(path: Path, prefix: str) -> frozenset[str]:
    pattern = re.compile(rf"^\*\*({prefix}-[0-9]{{3}})\s+—", re.MULTILINE)
    return frozenset(pattern.findall(path.read_text(encoding="utf-8")))


def _rows_by_id() -> dict[str, Increment5TraceabilityRow]:
    return {row.requirement_id: row for row in INCREMENT_5_TRACEABILITY}


def test_closed_world_inventory_matches_accepted_specs() -> None:
    assert _spec_requirements(DEVAL_SPEC, "DEVAL") == DEVAL_REQUIREMENTS
    assert _spec_requirements(DOPS_SPEC, "DOPS") == DOPS_REQUIREMENTS
    assert len(DEVAL_REQUIREMENTS) == 43
    assert len(DOPS_REQUIREMENTS) == 61
    assert len(ALL_REQUIREMENTS) == 155


def test_amended_delivery_groups_are_disjoint_and_complete() -> None:
    validate_increment5_traceability()

    seen: set[str] = set()
    for requirements in DELIVERY_GROUPS.values():
        assert not seen.intersection(requirements)
        seen.update(requirements)

    assert seen == set(ALL_REQUIREMENTS)
    assert len(INCREMENT_5_TRACEABILITY) == 155
    assert len({row.requirement_id for row in INCREMENT_5_TRACEABILITY}) == 155

    assert Counter(row.delivery_trace for row in INCREMENT_5_TRACEABILITY) == {
        Increment5DeliveryTrace.DELIVERED_IN_5A: 9,
        Increment5DeliveryTrace.DEFERRED_TO_5C: 2,
        Increment5DeliveryTrace.DEFERRED_TO_5D: 12,
        Increment5DeliveryTrace.DEFERRED_TO_5E: 9,
        Increment5DeliveryTrace.DEFERRED_TO_INCREMENT_6: 6,
        Increment5DeliveryTrace.DEFERRED_TO_INCREMENT_8: 110,
        Increment5DeliveryTrace.SATISFIED_BY_PRIOR_INCREMENT: 7,
    }


def test_increment5_is_bounded_retrieval_not_full_admission() -> None:
    assert DELIVERY_GROUPS[Increment5DeliveryTrace.DEFERRED_TO_5B] == frozenset()
    assert OUTSIDE_INCREMENT_5_REQUIREMENTS == frozenset()

    assert DEFERRED_TO_5C_REQUIREMENTS == {"GRAG-033", "GRAG-034"}
    assert REQUEST_RETRIEVAL_REQUIREMENTS == {
        "GRAG-031",
        "GRAG-032",
        "GRAG-035",
        "GRAG-040",
        "GRAG-041",
        "GRAG-043",
        "TRI-020",
        "TRI-021",
        "TRI-022",
        "TRI-023",
        "TRI-025",
        "TRI-027",
    }
    assert DEFERRED_TO_5E_REQUIREMENTS == {
        "GRAG-050",
        "GRAG-051",
        "GRAG-054",
        "GRAG-055",
        "GRAG-056",
        "GRPROD-001",
        "GRPROD-010",
        "GRPROD-015",
        "GRPROD-023",
    }

    assert not any(
        requirement.startswith(("DEVAL-", "DOPS-"))
        for requirement in DEFERRED_TO_5E_REQUIREMENTS
    )


def test_cross_request_effects_are_owned_by_increment6() -> None:
    expected = {
        "GRAG-042",
        "GRAG-044",
        "GRPROD-021",
        "TRI-024",
        "TRI-026",
        "TRI-028",
    }
    assert DEFERRED_TO_INCREMENT_6_REQUIREMENTS == expected
    assert CROSS_REQUEST_INTEGRATION_REQUIREMENTS == expected

    rows = _rows_by_id()
    for requirement in expected:
        assert rows[requirement].delivery_trace is (
            Increment5DeliveryTrace.DEFERRED_TO_INCREMENT_6
        )
        assert rows[requirement].delivery_issue == 146

    assert not expected.intersection(REQUEST_RETRIEVAL_REQUIREMENTS)


def test_full_evaluation_and_operations_are_owned_by_increment8() -> None:
    rows = _rows_by_id()

    assert (
        DEVAL_REQUIREMENTS.difference(DELIVERED_IN_5A_REQUIREMENTS)
        == DEVAL_REQUIREMENTS.intersection(
            DEFERRED_TO_INCREMENT_8_REQUIREMENTS
        )
    )
    assert OPERATIONAL_DOPS == DOPS_REQUIREMENTS.intersection(
        DEFERRED_TO_INCREMENT_8_REQUIREMENTS
    )

    for requirement in (
        DEVAL_REQUIREMENTS.difference(DELIVERED_IN_5A_REQUIREMENTS)
        | OPERATIONAL_DOPS
    ):
        assert rows[requirement].delivery_trace is (
            Increment5DeliveryTrace.DEFERRED_TO_INCREMENT_8
        )
        assert rows[requirement].delivery_issue == 148

    for requirement in {
        "GRAG-045",
        "GRAG-046",
        "GRAG-057",
        "GRPROD-002",
        "GRPROD-004",
        "GRPROD-011",
        "GRPROD-012",
        "GRPROD-022",
        "GRPROD-024",
        "GRPROD-030",
        "GRPROD-031",
    }:
        assert rows[requirement].delivery_issue == 148


def test_existing_5a_and_increment4_evidence_remain_exact() -> None:
    rows = _rows_by_id()

    assert {
        requirement
        for requirement, row in rows.items()
        if row.delivery_trace is Increment5DeliveryTrace.DELIVERED_IN_5A
    } == DELIVERED_IN_5A_REQUIREMENTS

    for requirement in INHERITED_AUTHORITY:
        row = rows[requirement]
        assert row.delivery_issue == 144
        assert row.delivery_target == "increment-4-accepted-authority"
        assert (
            row.verification_target
            == "main@c9e31879421083e82e2538d57087d04e9b454d34"
        )
        assert row.decision_anchor == (
            "main@c9e31879421083e82e2538d57087d04e9b454d34:"
            f"newsroom/increment4/traceability.py#{requirement}"
        )


def test_decision_anchors_cover_every_requirement_without_issue_as_authority() -> None:
    assert frozenset(ANCHOR_BY_REQUIREMENT) == ALL_REQUIREMENTS
    for requirement, anchor in ANCHOR_BY_REQUIREMENT.items():
        assert anchor == anchor.strip()
        assert anchor
        assert not anchor.startswith("issue:")
        if requirement in INHERITED_AUTHORITY:
            assert anchor.startswith(
                "main@c9e31879421083e82e2538d57087d04e9b454d34:"
            )
        elif requirement.startswith(("GRAG-", "GRPROD-", "TRI-", "DEVAL-", "DOPS-")):
            assert "#" in anchor

    assert ANCHOR_BY_REQUIREMENT["DEVAL-011"].endswith(
        "#/epoch_protocol"
    )
    assert ANCHOR_BY_REQUIREMENT["DOPS-076"].endswith(
        "#/payload/non_effects"
    )


def test_human_map_and_amendment_record_the_transfers() -> None:
    plan = PLAN.read_text(encoding="utf-8")
    human_map = HUMAN_MAP.read_text(encoding="utf-8")

    for text in (plan, human_map):
        assert "9 / 0 / 2 / 12 / 9 / 6 / 110 / 7" in text
        assert "#146" in text
        assert "#148" in text
        assert "GRAG-042" in text
        assert "TRI-028" in text
        assert "GRPROD-022" in text
        assert "123" not in text

    assert "Tier L" in plan
    assert "Tier S" in plan
    assert "Tier M" in plan
    assert "full evaluation" in plan.lower()
    assert "operational admission" in plan.lower()


def test_traceability_row_rejects_unknown_delivery_issue() -> None:
    row = INCREMENT_5_TRACEABILITY[0]
    with pytest.raises(ValueError, match="outside the admitted chain"):
        Increment5TraceabilityRow(
            requirement_id=row.requirement_id,
            decision_anchor=row.decision_anchor,
            decision_trace=row.decision_trace,
            delivery_trace=row.delivery_trace,
            delivery_issue=999,
            delivery_target=row.delivery_target,
            verification_target=row.verification_target,
        )
