from __future__ import annotations

from pathlib import Path

from newsroom.increment5.traceability import (
    INCREMENT_5_TRACEABILITY,
    Increment5DecisionTrace,
    Increment5DeliveryTrace,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_grag_053_uses_the_reviewed_package_neutrality_decision() -> None:
    rows = {row.requirement_id: row for row in INCREMENT_5_TRACEABILITY}
    row = rows["GRAG-053"]
    expected_anchor = (
        "docs/decisions/2026-08-02-increment-5a-production-retrieval-contract.md"
        "#package-neutrality"
    )

    assert row.decision_trace is Increment5DecisionTrace.BOUND_BY_5A
    assert row.delivery_trace is Increment5DeliveryTrace.DELIVERED_IN_5A
    assert row.delivery_issue == 250
    assert row.decision_anchor == expected_anchor
    assert rows["GRPROD-012"].decision_anchor.endswith(
        "#/payload/change_control"
    )

    decision = (
        _REPOSITORY_ROOT
        / "docs/decisions/2026-08-02-increment-5a-production-retrieval-contract.md"
    ).read_text(encoding="utf-8")
    assert "## Package neutrality" in decision
    assert (
        "must not be equated with mandatory use of microsoft graphrag "
        "community summarisation"
    ) in decision.lower()
    assert "not required runtime dependencies" in decision
    assert "cannot satisfy a required retrieval mode" in decision
