"""Build the coherent Increment 5B Tier-M service reconciliation atom."""
from __future__ import annotations

import ast
from pathlib import Path

from scripts.support import repair_increment5b_tierm_v4 as base


FILES = (
    ".github/workflows/evidence.yml",
    "newsroom/tests/test_increment5b_tierm_service_reconciliation.py",
    "newsroom/tests/test_integrated_c1_sdlc_contract.py",
    "newsroom/tests/test_sdlc_workflow_lane.py",
    "scripts/sdlc/workflow_lane.py",
)
_ORIGINAL_PATCH = base.patch


def _sorted_optional_inventory(text: str) -> str:
    marker = "_OPTIONAL_CORE_TEST_IDS = "
    start = text.index(marker) + len(marker)
    end = text.index("\n_SERVICE_CONFIGURATION", start)
    values = ast.literal_eval(text[start:end])
    if not isinstance(values, tuple) or not all(isinstance(item, str) for item in values):
        raise SystemExit("optional-core inventory is not a tuple of test identities")
    expected = tuple(sorted(values))
    if len(expected) != len(set(expected)):
        raise SystemExit("optional-core inventory contains duplicate test identities")
    rendered = "(\n" + "".join(f"    {item!r},\n" for item in expected) + ")"
    return text[:start] + rendered + text[end:]


def _insert_before_once(text: str, anchor: str, insertion: str, *, field: str) -> str:
    if text.count(anchor) != 1:
        raise SystemExit(f"{field} anchor drifted")
    if base.FIRST in text or base.SECOND in text:
        raise SystemExit(f"{field} already contains Increment 5B4 identities")
    return text.replace(anchor, insertion + anchor, 1)


def patch(product: Path) -> None:
    _ORIGINAL_PATCH(product)

    lane = product / "scripts/sdlc/workflow_lane.py"
    lane.write_text(
        _sorted_optional_inventory(lane.read_text(encoding="utf-8")),
        encoding="utf-8",
    )

    workflow_tests = product / "newsroom/tests/test_sdlc_workflow_lane.py"
    workflow_text = workflow_tests.read_text(encoding="utf-8")
    workflow_anchor = (
        "        'newsroom.tests.test_increment_2d_neo4j_service::"
        "test_actual_service_complete_increment_2_proof_admits_replays_and_restarts',\n"
    )
    workflow_insertion = f"        {base.FIRST!r},\n        {base.SECOND!r},\n"
    workflow_tests.write_text(
        _insert_before_once(
            workflow_text,
            workflow_anchor,
            workflow_insertion,
            field="workflow-lane exact inventory",
        ),
        encoding="utf-8",
    )

    integrated_tests = product / "newsroom/tests/test_integrated_c1_sdlc_contract.py"
    integrated_text = integrated_tests.read_text(encoding="utf-8")
    integrated_anchor = (
        "        'newsroom.tests.test_increment_2d_neo4j_service::"
        "test_actual_service_complete_increment_2_proof_admits_replays_and_restarts',\n"
    )
    integrated_insertion = f"        {base.FIRST!r},\n        {base.SECOND!r},\n"
    integrated_text = _insert_before_once(
        integrated_text,
        integrated_anchor,
        integrated_insertion,
        field="integrated exact inventory",
    )
    if integrated_text.count("    assert len(optional) == 38\n") != 1:
        raise SystemExit("integrated optional count anchor drifted")
    integrated_tests.write_text(
        integrated_text.replace(
            "    assert len(optional) == 38\n",
            "    assert len(optional) == 40\n",
            1,
        ),
        encoding="utf-8",
    )


def main() -> None:
    base.FILES = FILES
    base.patch = patch
    base.main()


if __name__ == "__main__":
    main()
