from __future__ import annotations

import inspect
from pathlib import Path

from newsroom.increment5.named_tool_contracts import NamedToolId
from newsroom.increment5.named_tool_dispatch import (
    NAMED_TOOL_ROUTES,
    NamedToolExecutionRoute,
)


ROOT = Path(__file__).resolve().parents[2]
OPERATIONS = ROOT / "docs/operations/increment-5c2-six-named-tools.md"
TRACEABILITY = ROOT / "docs/traceability/increment-5c2-six-named-tools.md"
ACCEPTED_MAP = ROOT / "docs/traceability/increment-5-production-retrieval.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_operations_and_traceability_cover_exact_six_tool_inventory() -> None:
    operations = _read(OPERATIONS)
    traceability = _read(TRACEABILITY)
    expected = {item.value for item in NamedToolId}
    assert set(NAMED_TOOL_ROUTES) == set(NamedToolId)
    assert {
        tool.value
        for tool, route in NAMED_TOOL_ROUTES.items()
        if route is NamedToolExecutionRoute.BRANCH
    } == {
        NamedToolId.EXACT_AUTHORITY_LOOKUP.value,
        NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL.value,
        NamedToolId.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL.value,
        NamedToolId.BOUNDED_ADMITTED_GRAPH_TRAVERSAL.value,
    }
    assert {
        tool.value
        for tool, route in NAMED_TOOL_ROUTES.items()
        if route is NamedToolExecutionRoute.AUTHORITY
    } == {
        NamedToolId.CURRENT_COLLISION_AND_AUTHORITY_HYDRATION_LOOKUP.value,
        NamedToolId.BOUNDED_SOURCE_REVISION_IMPACT_LOOKUP.value,
    }
    for identity in expected:
        assert f"`{identity}`" in operations
        assert f"`{identity}`" in traceability


def test_traceability_retains_exact_closed_world_5c_ownership() -> None:
    accepted = _read(ACCEPTED_MAP)
    traceability = _read(TRACEABILITY)
    assert "The exact 5C set is:\n\n`GRAG-033`, `GRAG-034`." in accepted
    assert (
        "The complete 5C ownership set remains exactly:\n\n"
        "`GRAG-033`, `GRAG-034`."
    ) in traceability
    assert "`GRAG-035` and `TRI-022` remain owned" in traceability
    assert "`GRAG-033`, `GRAG-034`, `GRAG-035`" not in traceability


def test_records_keep_internal_audit_bytes_outside_caller_payload() -> None:
    operations = _read(OPERATIONS)
    traceability = _read(TRACEABILITY)
    assert "internal audit evidence, not caller response payload" in operations
    assert "does not expand the caller payload" in traceability
    assert "INCOMPLETE / RESPONSE_LIMIT_EXCEEDED" in operations


def test_records_keep_5d_increment6_and_increment8_boundaries_explicit() -> None:
    operations = _read(OPERATIONS)
    traceability = _read(TRACEABILITY)
    for text in (operations, traceability):
        assert "5D" in text
        assert "Increment 6" in text
        assert "Increment 8" in text
        assert "Candidate" in text
        assert "production activation" in text
    assert "factual bytes and complete hydration remain 5D" in operations
    assert "`GRAG-035` composed graph/hybrid response metadata" in traceability
    assert "`TRI-022` complete request-level Retrieval Context" in traceability


def test_source_scope_false_no_match_repair_is_normative_and_bounded() -> None:
    operations = _read(OPERATIONS)
    traceability = _read(TRACEABILITY)
    assert "scans at most 65" in operations
    assert "before source filtering" in operations
    assert "SOURCE_SCOPE_SCAN_BOUND_EXCEEDED" in operations
    assert "lower-ranked in-scope match" in traceability
    assert "actual-Neo4j regressions" in traceability


def test_source_impact_query_valid_cutoff_is_normative() -> None:
    operations = _read(OPERATIONS)
    traceability = _read(TRACEABILITY)
    assert "close the observation window at the exact query-valid time" in operations
    assert "both observed and recorded" in operations
    assert "cannot retrospectively hide" in operations
    assert "future or late-recorded successors" in traceability
    assert "future-observation" in traceability


def test_branch_kernel_description_matches_completed_parallel_architecture() -> None:
    import newsroom.increment5.named_tool_branch_execution as module

    source = inspect.getsource(module)
    header = source.split('"""', 2)[1]
    assert "four branch-backed Increment 5C tools" in header
    assert "parallel authority execution kernel" in header
    assert "remain later commits" not in header
    assert "5C2B" not in header
