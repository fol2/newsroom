#!/usr/bin/env python3
"""Materialize the final two Increment 5A ownership corrections on staging.

The input is the verified one-commit candidate. This helper performs two
closed-world moves without changing contract/profile/Plan identities:

* TRI-021 moves from 5B to 5D, where the hybrid composer can enforce
  exact/source-native/formal-process/lineage precedence before approximate
  similarity.
* GRPROD-021 moves from 5D to 5E, where the complete vertical integration and
  qualification path reaches triage and Candidate admission.

The final PR commit is assembled separately over the fixed base and excludes
this helper and its staging manifest.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE_HEAD = "b320ce8fd85c699e64726cf779b352e559087c1d"
MODEL = ROOT / "newsroom/increment5/_traceability_model.py"
ANCHORS = ROOT / "newsroom/increment5/_traceability_anchors.py"
TRACEABILITY = ROOT / "newsroom/increment5/traceability.py"
TRACEABILITY_TEST = ROOT / "newsroom/tests/test_increment5a_traceability.py"
DECISION = ROOT / (
    "docs/decisions/2026-08-02-increment-5a-production-retrieval-contract.md"
)
OPERATIONS = ROOT / "docs/operations/increment-5-production-retrieval-contract.md"
TRACEABILITY_DOC = ROOT / "docs/traceability/increment-5-production-retrieval.md"
OUTPUT = ROOT / "increment5a-final-boundary-manifest.json"

TRI_021_ANCHOR = (
    "issue:#253:deferred:exact-source-formal-process-and-explicit-lineage-"
    "before-approximate-similarity"
)
GRPROD_021_ANCHOR = (
    "issue:#254:deferred:complete-graph-native-vertical-slice-through-triage-"
    "and-candidate-admission"
)


def canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8", errors="strict")


def replace_once(path: Path, old: str, new: str, *, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{label} replacement count differs in {path.relative_to(ROOT)}: {count}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


def insert_before(path: Path, marker: str, addition: str, *, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if addition.strip() in text:
        raise RuntimeError(f"{label} already exists in {path.relative_to(ROOT)}")
    count = text.count(marker)
    if count != 1:
        raise RuntimeError(
            f"{label} marker count differs in {path.relative_to(ROOT)}: {count}"
        )
    path.write_text(text.replace(marker, addition + marker), encoding="utf-8")


def main() -> None:
    # Whole-requirement ownership only: 5B contributes branch implementations,
    # but it cannot independently close TRI-021 without the 5D composer.
    replace_once(
        MODEL,
        '        "GRPROD-021",\n        "GRPROD-024",\n        "TRI-020",\n',
        '        "GRPROD-024",\n        "TRI-020",\n        "TRI-021",\n',
        label="swap GRPROD-021 for TRI-021 in 5D",
    )
    replace_once(
        MODEL,
        'DEFERRED_TO_5B_REQUIREMENTS = frozenset({"TRI-021"})\n',
        "# 5B is a partial implementation dependency. Four independent branches\n"
        "# are necessary for later composition, but no selected whole requirement\n"
        "# is complete before 5D applies exact-first orchestration and fusion.\n"
        "DEFERRED_TO_5B_REQUIREMENTS = frozenset()\n",
        label="empty whole-requirement 5B set",
    )
    replace_once(
        MODEL,
        "if len(DEFERRED_TO_5E_REQUIREMENTS) != 116:\n"
        '    raise RuntimeError("5E closed-world remainder must contain 116 requirements")\n',
        "if len(DEFERRED_TO_5E_REQUIREMENTS) != 117:\n"
        '    raise RuntimeError("5E closed-world remainder must contain 117 requirements")\n',
        label="5E remainder cardinality",
    )

    replace_once(
        ANCHORS,
        '    (\n        f"{_CONTRACT}#/payload/required_modes",\n'
        '        frozenset({"GRPROD-001", "TRI-021"}),\n'
        "    ),\n",
        '    (f"{_CONTRACT}#/payload/required_modes", frozenset({"GRPROD-001"})),\n'
        "    (\n"
        '        "issue:#253:deferred:exact-source-formal-process-and-explicit-"\n'
        '        "lineage-before-approximate-similarity",\n'
        '        frozenset({"TRI-021"}),\n'
        "    ),\n",
        label="TRI-021 composition anchor",
    )
    replace_once(
        ANCHORS,
        '    (\n        f"{_CONTRACT}#/payload/delivery_boundaries/5D",\n'
        '        frozenset({"GRAG-045", "GRPROD-021"}),\n'
        "    ),\n",
        '    (\n        f"{_CONTRACT}#/payload/delivery_boundaries/5D",\n'
        '        frozenset({"GRAG-045"}),\n'
        "    ),\n"
        "    (\n"
        '        "issue:#254:deferred:complete-graph-native-vertical-slice-"\n'
        '        "through-triage-and-candidate-admission",\n'
        '        frozenset({"GRPROD-021"}),\n'
        "    ),\n",
        label="GRPROD-021 vertical-integration anchor",
    )

    replace_once(
        TRACEABILITY,
        "        Increment5DeliveryTrace.DELIVERED_IN_5A: 10,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5B: 1,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5C: 4,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5D: 16,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5E: 116,\n",
        "        Increment5DeliveryTrace.DELIVERED_IN_5A: 10,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5B: 0,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5C: 4,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5D: 16,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5E: 117,\n",
        label="runtime delivery distribution",
    )
    replace_once(
        TRACEABILITY,
        "    if DELIVERY_GROUPS[Increment5DeliveryTrace.DEFERRED_TO_5D] != (\n"
        "        REQUEST_RETRIEVAL_REQUIREMENTS\n"
        "    ):\n"
        '        raise RuntimeError("5D differs from the exact one-request retrieval boundary")\n',
        "    if DELIVERY_GROUPS[Increment5DeliveryTrace.DEFERRED_TO_5B]:\n"
        "        raise RuntimeError(\n"
        '            "5B branch implementation cannot claim a complete requirement"\n'
        "        )\n"
        "    if DELIVERY_GROUPS[Increment5DeliveryTrace.DEFERRED_TO_5D] != (\n"
        "        REQUEST_RETRIEVAL_REQUIREMENTS\n"
        "    ):\n"
        '        raise RuntimeError("5D differs from the exact one-request retrieval boundary")\n',
        label="5B whole-requirement invariant",
    )
    replace_once(
        TRACEABILITY,
        "        \"GRAG-042\": (\n"
        "            \"issue:#253:deferred:source-revision-signal-lead-hypothesis-and-\"\n"
        "            \"candidate-lineage-projection-and-hydration\"\n"
        "        ),\n"
        "    }\n",
        "        \"GRAG-042\": (\n"
        "            \"issue:#253:deferred:source-revision-signal-lead-hypothesis-and-\"\n"
        "            \"candidate-lineage-projection-and-hydration\"\n"
        "        ),\n"
        "        \"TRI-021\": (\n"
        "            \"issue:#253:deferred:exact-source-formal-process-and-explicit-\"\n"
        "            \"lineage-before-approximate-similarity\"\n"
        "        ),\n"
        "    }\n",
        label="critical TRI-021 5D invariant",
    )
    replace_once(
        TRACEABILITY,
        "    critical_5e = {\n"
        '        "GRPROD-002": (\n',
        "    critical_5e = {\n"
        '        "GRPROD-021": (\n'
        '            "issue:#254:deferred:complete-graph-native-vertical-slice-"\n'
        '            "through-triage-and-candidate-admission"\n'
        "        ),\n"
        '        "GRPROD-002": (\n',
        label="critical GRPROD-021 5E invariant",
    )

    replace_once(
        TRACEABILITY_TEST,
        "        Increment5DeliveryTrace.DELIVERED_IN_5A: 10,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5B: 1,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5C: 4,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5D: 16,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5E: 116,\n",
        "        Increment5DeliveryTrace.DELIVERED_IN_5A: 10,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5B: 0,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5C: 4,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5D: 16,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5E: 117,\n",
        label="test delivery distribution",
    )
    replace_once(
        TRACEABILITY_TEST,
        '        "GRPROD-021",\n        "GRPROD-024",\n        "TRI-020",\n',
        '        "GRPROD-024",\n        "TRI-020",\n        "TRI-021",\n',
        label="test 5D inventory swap",
    )
    replace_once(
        TRACEABILITY_TEST,
        "def test_5d_is_exactly_one_request_retrieval_semantics() -> None:\n",
        "def test_5b_is_partial_branch_delivery_without_whole_requirement_credit() -> None:\n"
        "    assert DELIVERY_GROUPS[Increment5DeliveryTrace.DEFERRED_TO_5B] == frozenset()\n\n\n"
        "def test_5d_is_exactly_one_request_retrieval_semantics() -> None:\n",
        label="5B zero-whole-requirement test",
    )
    replace_once(
        TRACEABILITY_TEST,
        "    assert rows[\"GRAG-042\"].decision_anchor == (\n"
        "        \"issue:#253:deferred:source-revision-signal-lead-hypothesis-and-\"\n"
        "        \"candidate-lineage-projection-and-hydration\"\n"
        "    )\n"
        "    assert all(\n"
        "        rows[item].delivery_trace is Increment5DeliveryTrace.DEFERRED_TO_5D\n"
        "        for item in (\"GRAG-031\", \"GRAG-042\")\n"
        "    )\n",
        "    assert rows[\"GRAG-042\"].decision_anchor == (\n"
        "        \"issue:#253:deferred:source-revision-signal-lead-hypothesis-and-\"\n"
        "        \"candidate-lineage-projection-and-hydration\"\n"
        "    )\n"
        "    assert rows[\"TRI-021\"].decision_anchor == (\n"
        "        \"issue:#253:deferred:exact-source-formal-process-and-explicit-\"\n"
        "        \"lineage-before-approximate-similarity\"\n"
        "    )\n"
        "    assert all(\n"
        "        rows[item].delivery_trace is Increment5DeliveryTrace.DEFERRED_TO_5D\n"
        "        for item in (\"GRAG-031\", \"GRAG-042\", \"TRI-021\")\n"
        "    )\n",
        label="TRI-021 ownership regression",
    )
    vertical_test = '''\n\ndef test_complete_graph_native_vertical_slice_is_owned_by_5e() -> None:\n    row = _rows()["GRPROD-021"]\n    assert row.decision_trace is Increment5DecisionTrace.BOUND_BY_5A\n    assert row.delivery_trace is Increment5DeliveryTrace.DEFERRED_TO_5E\n    assert row.delivery_issue == 254\n    assert row.decision_anchor == (\n        "issue:#254:deferred:complete-graph-native-vertical-slice-through-"\n        "triage-and-candidate-admission"\n    )\n\n\n'''
    insert_before(
        TRACEABILITY_TEST,
        "def test_production_graphrag_enforcement_is_owned_by_5e() -> None:\n",
        vertical_test,
        label="GRPROD-021 ownership regression",
    )

    replace_once(
        DECISION,
        "- 5B / #251 — 1;\n",
        "- 5B / #251 — 0 complete requirements (partial branch implementation);\n",
        label="decision 5B count",
    )
    replace_once(
        DECISION,
        "- **5E / #254 — the exact closed-world remainder of 116 requirements.**\n",
        "- **5E / #254 — the exact closed-world remainder of 117 requirements.**\n",
        label="decision 5E count",
    )
    replace_once(
        DECISION,
        "- **5B / #251:** four independent typed retrievers and exact branch receipts;\n"
        "  no final fusion or dependency-root deduplication.\n",
        "- **5B / #251:** four independent typed retrievers and exact branch receipts;\n"
        "  no final fusion, dependency-root deduplication, or exact-before-approximate\n"
        "  orchestration. It is a partial implementation dependency and closes no\n"
        "  selected whole requirement by itself.\n",
        label="decision truthful 5B boundary",
    )
    replace_once(
        DECISION,
        "- **5D / #253:** deterministic fusion, authoritative dependency-root\n"
        "  deduplication, complete projectable and hydratable\n"
        "  `Source → Revision → Signal → Lead → Hypothesis → Candidate` lineage,\n"
        "  authoritative hydration, freshness, collision checks, and request-level\n"
        "  explicit outcomes.\n",
        "- **5D / #253:** exact/source-native, formal-process, and explicit-lineage\n"
        "  retrieval precedes approximate similarity; deterministic fusion and\n"
        "  authoritative dependency-root deduplication then produce one request. 5D\n"
        "  also owns complete projectable and hydratable\n"
        "  `Source → Revision → Signal → Lead → Hypothesis → Candidate` lineage,\n"
        "  authoritative hydration, freshness, collision checks, and request-level\n"
        "  explicit outcomes. It stops before triage and Candidate-admission\n"
        "  integration.\n",
        label="decision TRI-021 5D boundary",
    )
    replace_once(
        DECISION,
        "  queues; durability; least-privilege credentials and egress; full\n"
        "  reconciliation recovery; scoped containment; security; purge; rollback;\n"
        "  rebuild; and actual-Neo4j evidence.\n",
        "  queues; durability; least-privilege credentials and egress; the complete\n"
        "  governed-projection → hybrid-retrieval → triage → Candidate-admission\n"
        "  vertical slice; full reconciliation recovery; scoped containment;\n"
        "  security; purge; rollback; rebuild; and actual-Neo4j evidence.\n",
        label="decision GRPROD-021 5E boundary",
    )
    replace_once(
        DECISION,
        "Four independently working branches are not a hybrid system; fusion and\n"
        "dependency-aware deduplication create that system in 5D. Likewise, request-level\n",
        "Four independently working branches are not a hybrid system and cannot satisfy\n"
        "`TRI-021`; exact-before-approximate orchestration, fusion, and dependency-aware\n"
        "deduplication create that system in 5D. A stable request still does not satisfy\n"
        "`GRPROD-021`: 5E must integrate and verify the complete graph-native path through\n"
        "triage and Candidate admission. Likewise, request-level\n",
        label="decision final integration distinction",
    )

    replace_once(
        OPERATIONS,
        "The exact delivery split is `10 / 1 / 4 / 16 / 116 / 7 / 1` for 5A, 5B, 5C,\n",
        "The exact delivery split is `10 / 0 / 4 / 16 / 117 / 7 / 1` for 5A, 5B, 5C,\n",
        label="operations delivery split",
    )
    replace_once(
        OPERATIONS,
        "- **5B / #251:** four independent retriever branches and exact receipts.\n",
        "- **5B / #251:** four independent retriever branches and exact receipts.\n"
        "  This is partial implementation: it closes no selected whole requirement\n"
        "  until 5D composes the branches.\n",
        label="operations 5B partial boundary",
    )
    replace_once(
        OPERATIONS,
        "- **5D / #253:** deterministic fusion, authoritative dependency-root\n"
        "  deduplication, complete six-stage discovery lineage, hydration, freshness,\n"
        "  collision checks, and request-level outcomes.\n",
        "- **5D / #253:** exact/source-native, formal-process, and explicit-lineage\n"
        "  retrieval before approximate similarity; deterministic fusion, authoritative\n"
        "  dependency-root deduplication, complete six-stage discovery lineage,\n"
        "  hydration, freshness, collision checks, and request-level outcomes.\n",
        label="operations TRI-021 5D boundary",
    )
    replace_once(
        OPERATIONS,
        "  recovery; containment; production/canary/live-shadow GraphRAG enforcement;\n"
        "  rollback and rebuild; and actual-service qualification.\n",
        "  recovery; containment; the complete governed-projection/hybrid-retrieval/\n"
        "  triage/Candidate-admission vertical slice; production/canary/live-shadow\n"
        "  GraphRAG enforcement; rollback and rebuild; and actual-service\n"
        "  qualification.\n",
        label="operations GRPROD-021 5E boundary",
    )

    replace_once(
        TRACEABILITY_DOC,
        "- 5B contains only `TRI-021`;\n",
        "- 5B supplies four branch implementations but closes no selected whole\n"
        "  requirement before composition;\n",
        label="traceability 5B derivation",
    )
    replace_once(
        TRACEABILITY_DOC,
        "the 155-row inventory, the remaining 116 requirements belong to 5E. A newly\n",
        "the 155-row inventory, the remaining 117 requirements belong to 5E. A newly\n",
        label="traceability 5E remainder count",
    )
    replace_once(
        TRACEABILITY_DOC,
        "| 5B / #251 | 1 | four independent typed retrievers and receipts |\n",
        "| 5B / #251 | 0 | partial branch implementations; no complete selected requirement |\n",
        label="traceability table 5B",
    )
    replace_once(
        TRACEABILITY_DOC,
        "| 5E / #254 | 116 | closed-world evaluation, production GraphRAG enforcement, operational policy, monitoring, admission, queues, durability, reconciliation, containment, security, recovery, and qualification |\n",
        "| 5E / #254 | 117 | closed-world evaluation, complete graph-native vertical integration, production GraphRAG enforcement, operational policy, monitoring, admission, queues, durability, reconciliation, containment, security, recovery, and qualification |\n",
        label="traceability table 5E",
    )
    replace_once(
        TRACEABILITY_DOC,
        "The complete 5D inventory is:\n\n"
        "- `GRAG-031`, `GRAG-032`, and `GRAG-040`–`GRAG-045`;\n"
        "- `GRPROD-021` and `GRPROD-024`; and\n"
        "- `TRI-020` and `TRI-023`–`TRI-027`.\n",
        "The complete 5D inventory is:\n\n"
        "- `GRAG-031`, `GRAG-032`, and `GRAG-040`–`GRAG-045`;\n"
        "- `GRPROD-024`; and\n"
        "- `TRI-020`, `TRI-021`, and `TRI-023`–`TRI-027`.\n\n"
        "`TRI-021` belongs here because only the composer can ensure that\n"
        "source-native, formal-process, and explicit-lineage retrieval precedes\n"
        "approximate similarity. Four independent 5B branches cannot establish that\n"
        "ordering.\n\n"
        "`GRPROD-021` belongs to 5E because a one-request Retrieval Context stops before\n"
        "the required end-to-end triage and Candidate-admission integration.\n",
        label="traceability exact 5D inventory",
    )
    replace_once(
        TRACEABILITY_DOC,
        "- `GRPROD-002` and `GRPROD-023` → 5E/#254: policy declarations do not deliver the production, canary, and complete-live-shadow no-omission/no-optional-plugin enforcement paths.\n",
        "- `TRI-021` → 5D/#253: independent retrievers cannot establish exact-before-approximate ordering; the composer must enforce it.\n"
        "- `GRPROD-021` → 5E/#254: a one-request hybrid result is not the complete graph-native vertical slice through triage and Candidate admission.\n"
        "- `GRPROD-002` and `GRPROD-023` → 5E/#254: policy declarations do not deliver the production, canary, and complete-live-shadow no-omission/no-optional-plugin enforcement paths.\n",
        label="traceability final key boundaries",
    )

    model_text = MODEL.read_text(encoding="utf-8")
    request_section = model_text.split(
        "REQUEST_RETRIEVAL_REQUIREMENTS = frozenset(", 1
    )[1].split("DELIVERED_IN_5A_REQUIREMENTS", 1)[0]
    if "TRI-021" not in request_section or "GRPROD-021" in request_section:
        raise RuntimeError("5D whole-requirement inventory differs after correction")
    if "DEFERRED_TO_5B_REQUIREMENTS = frozenset()" not in model_text:
        raise RuntimeError("5B whole-requirement set is not empty")

    anchor_text = ANCHORS.read_text(encoding="utf-8").replace('"\n        "', "")
    for requirement, anchor in {
        "TRI-021": TRI_021_ANCHOR,
        "GRPROD-021": GRPROD_021_ANCHOR,
    }.items():
        if requirement not in anchor_text or anchor not in anchor_text:
            raise RuntimeError(f"missing exact corrected anchor for {requirement}")

    changed = [
        MODEL,
        ANCHORS,
        TRACEABILITY,
        TRACEABILITY_TEST,
        DECISION,
        OPERATIONS,
        TRACEABILITY_DOC,
    ]
    result = {
        "schema_version": "newsroom.increment5a.final-boundary-review.v1",
        "source_head": SOURCE_HEAD,
        "contract_digest_unchanged": (
            "sha256:51a3837ad9cdb70fe8aaa4242997b191c7e848bb1d391c6940cccc2bd45ba06c"
        ),
        "evaluation_plan_digest_unchanged": (
            "sha256:c9d169c46a939573ffc6563704adfae973655f6394293ce591ec689f76a30959"
        ),
        "delivery_counts": {
            "5A": 10,
            "5B": 0,
            "5C": 4,
            "5D": 16,
            "5E": 117,
            "INCREMENT_4": 7,
            "OUTSIDE_ACTIVATION": 1,
            "TOTAL": 155,
        },
        "moves": {
            "TRI-021": "5B_TO_5D",
            "GRPROD-021": "5D_TO_5E",
        },
        "changed_paths": sorted(str(path.relative_to(ROOT)) for path in changed),
    }
    OUTPUT.write_bytes(canonical(result))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
