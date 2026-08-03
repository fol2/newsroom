#!/usr/bin/env python3
"""Materialize the closed one-request Increment 5D boundary on staging only.

The source is the verified one-commit candidate. This transformation audits the
whole 5D set against one rule: a 5D requirement must be completely enforceable
inside one read-only retrieval request. Five cross-request obligations move to
the computed 5E remainder together:

* downstream graph-outage decision fallback / Watch / Operational Hold;
* upstream source-collection and Lead-creation isolation;
* product-level outage degradation without graph-free production semantics;
* downstream Hypothesis/Candidate non-creation from an empty retrieval; and
* Candidate-admission enforcement of the current exact collision check.

The final PR commit is assembled separately over the fixed base and excludes
this helper and its staging manifest.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE_HEAD = "c478049b68e2905ab8970a77a20315f8d3d274aa"
MODEL = ROOT / "newsroom/increment5/_traceability_model.py"
ANCHORS = ROOT / "newsroom/increment5/_traceability_anchors.py"
TRACEABILITY = ROOT / "newsroom/increment5/traceability.py"
TRACEABILITY_TEST = ROOT / "newsroom/tests/test_increment5a_traceability.py"
DECISION = ROOT / (
    "docs/decisions/2026-08-02-increment-5a-production-retrieval-contract.md"
)
OPERATIONS = ROOT / "docs/operations/increment-5-production-retrieval-contract.md"
TRACEABILITY_DOC = ROOT / "docs/traceability/increment-5-production-retrieval.md"
OUTPUT = ROOT / "increment5a-request-boundary-manifest.json"

CROSS_REQUEST_ANCHORS = {
    "GRAG-044": (
        "issue:#254:deferred:graph-dependent-decision-exact-fallback-watch-or-"
        "operational-hold"
    ),
    "GRAG-045": (
        "issue:#254:deferred:source-collection-and-lead-creation-isolation-"
        "during-graph-outage"
    ),
    "GRPROD-024": (
        "issue:#254:deferred:system-outage-degradation-without-graph-free-"
        "production-profile"
    ),
    "TRI-024": (
        "issue:#254:deferred:empty-retrieval-cannot-create-hypothesis-or-"
        "candidate"
    ),
    "TRI-026": (
        "issue:#254:deferred:candidate-admission-requires-current-authoritative-"
        "collision-check"
    ),
}


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
    # One request may return advisory context, exact authority receipts, explicit
    # incompleteness and collision state. It cannot itself mutate a downstream
    # decision, admit a Candidate, run upstream collection, or define the product
    # profile during an outage.
    old_request = '''# 5D ends at one bounded retrieval request. It owns the hybrid result and its
# request-local authority semantics, not operational policy, health, queues,
# durable transition delivery, later reconciliation, containment, or incidents.
REQUEST_RETRIEVAL_REQUIREMENTS = frozenset(
    {
        "GRAG-031",
        "GRAG-032",
        "GRAG-040",
        "GRAG-041",
        "GRAG-042",
        "GRAG-043",
        "GRAG-044",
        "GRAG-045",
        "GRPROD-024",
        "TRI-020",
        "TRI-021",
        "TRI-023",
        "TRI-024",
        "TRI-025",
        "TRI-026",
        "TRI-027",
    }
)
'''
    new_request = '''# 5D ends at one bounded read-only retrieval request. It owns the hybrid result
# and request-local authority semantics. It does not own upstream collection,
# downstream decisions or Candidate admission, product-profile outage behaviour,
# operational policy, health, queues, durability, later reconciliation,
# containment, or incidents.
REQUEST_RETRIEVAL_REQUIREMENTS = frozenset(
    {
        "GRAG-031",
        "GRAG-032",
        "GRAG-040",
        "GRAG-041",
        "GRAG-042",
        "GRAG-043",
        "TRI-020",
        "TRI-021",
        "TRI-023",
        "TRI-025",
        "TRI-027",
    }
)

# These obligations consume retrieval state but cannot be completed by the
# retrieval request itself. They require upstream or downstream integration or
# system-level outage policy and therefore belong to the 5E remainder.
CROSS_REQUEST_INTEGRATION_REQUIREMENTS = frozenset(
    {
        "GRAG-044",
        "GRAG-045",
        "GRPROD-024",
        "TRI-024",
        "TRI-026",
    }
)
'''
    replace_once(MODEL, old_request, new_request, label="closed 5D request set")
    replace_once(
        MODEL,
        "if len(DEFERRED_TO_5E_REQUIREMENTS) != 117:\n"
        '    raise RuntimeError("5E closed-world remainder must contain 117 requirements")\n'
        "if not OPERATIONAL_DOPS.issubset(DEFERRED_TO_5E_REQUIREMENTS):\n",
        "if len(DEFERRED_TO_5E_REQUIREMENTS) != 122:\n"
        '    raise RuntimeError("5E closed-world remainder must contain 122 requirements")\n'
        "if not CROSS_REQUEST_INTEGRATION_REQUIREMENTS.issubset(\n"
        "    DEFERRED_TO_5E_REQUIREMENTS\n"
        "):\n"
        '    raise RuntimeError("cross-request integration requirements must belong to 5E")\n'
        "if REQUEST_RETRIEVAL_REQUIREMENTS.intersection(\n"
        "    CROSS_REQUEST_INTEGRATION_REQUIREMENTS\n"
        "):\n"
        '    raise RuntimeError("request-local and cross-request requirements overlap")\n'
        "if not OPERATIONAL_DOPS.issubset(DEFERRED_TO_5E_REQUIREMENTS):\n",
        label="5E cardinality and cross-request invariants",
    )

    # Remove Candidate-admission enforcement from the request-local authority
    # anchor while retaining the request's exact collision receipt boundary.
    replace_once(
        ANCHORS,
        '                "TRI-020",\n                "TRI-025",\n                "TRI-026",\n',
        '                "TRI-020",\n                "TRI-025",\n',
        label="TRI-026 authority anchor removal",
    )
    replace_once(
        ANCHORS,
        '                "GRAG-043",\n                "GRAG-044",\n'
        '                "GRPROD-024",\n                "TRI-023",\n'
        '                "TRI-024",\n                "TRI-027",\n',
        '                "GRAG-043",\n                "TRI-023",\n'
        '                "TRI-027",\n',
        label="cross-request outcome anchor removal",
    )
    replace_once(
        ANCHORS,
        '    (\n        f"{_CONTRACT}#/payload/delivery_boundaries/5D",\n'
        '        frozenset({"GRAG-045"}),\n    ),\n'
        '    (\n        "issue:#254:deferred:complete-graph-native-vertical-slice-"\n',
        '    (\n        "issue:#254:deferred:graph-dependent-decision-exact-fallback-"\n'
        '        "watch-or-operational-hold",\n        frozenset({"GRAG-044"}),\n    ),\n'
        '    (\n        "issue:#254:deferred:source-collection-and-lead-creation-"\n'
        '        "isolation-during-graph-outage",\n        frozenset({"GRAG-045"}),\n    ),\n'
        '    (\n        "issue:#254:deferred:system-outage-degradation-without-graph-"\n'
        '        "free-production-profile",\n        frozenset({"GRPROD-024"}),\n    ),\n'
        '    (\n        "issue:#254:deferred:empty-retrieval-cannot-create-hypothesis-"\n'
        '        "or-candidate",\n        frozenset({"TRI-024"}),\n    ),\n'
        '    (\n        "issue:#254:deferred:candidate-admission-requires-current-"\n'
        '        "authoritative-collision-check",\n        frozenset({"TRI-026"}),\n    ),\n'
        '    (\n        "issue:#254:deferred:complete-graph-native-vertical-slice-"\n',
        label="five exact cross-request anchors",
    )

    replace_once(
        TRACEABILITY,
        "    ALL_REQUIREMENTS,\n    DEFERRED_TO_5E_REQUIREMENTS,\n",
        "    ALL_REQUIREMENTS,\n    CROSS_REQUEST_INTEGRATION_REQUIREMENTS,\n"
        "    DEFERRED_TO_5E_REQUIREMENTS,\n",
        label="traceability cross-request import",
    )
    replace_once(
        TRACEABILITY,
        "        Increment5DeliveryTrace.DEFERRED_TO_5D: 16,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5E: 117,\n",
        "        Increment5DeliveryTrace.DEFERRED_TO_5D: 11,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5E: 122,\n",
        label="runtime delivery distribution",
    )
    replace_once(
        TRACEABILITY,
        "    if DELIVERY_GROUPS[Increment5DeliveryTrace.DEFERRED_TO_5E] != (\n"
        "        DEFERRED_TO_5E_REQUIREMENTS\n"
        "    ):\n"
        '        raise RuntimeError("5E differs from the closed-world remainder")\n'
        "    if any(item.startswith(\"DOPS-\") for item in REQUEST_RETRIEVAL_REQUIREMENTS):\n",
        "    if DELIVERY_GROUPS[Increment5DeliveryTrace.DEFERRED_TO_5E] != (\n"
        "        DEFERRED_TO_5E_REQUIREMENTS\n"
        "    ):\n"
        '        raise RuntimeError("5E differs from the closed-world remainder")\n'
        "    if not CROSS_REQUEST_INTEGRATION_REQUIREMENTS.issubset(\n"
        "        DELIVERY_GROUPS[Increment5DeliveryTrace.DEFERRED_TO_5E]\n"
        "    ):\n"
        '        raise RuntimeError("cross-request integration must be owned by 5E")\n'
        "    if REQUEST_RETRIEVAL_REQUIREMENTS.intersection(\n"
        "        CROSS_REQUEST_INTEGRATION_REQUIREMENTS\n"
        "    ):\n"
        '        raise RuntimeError("5D contains a cross-request integration requirement")\n'
        "    if any(item.startswith(\"DOPS-\") for item in REQUEST_RETRIEVAL_REQUIREMENTS):\n",
        label="runtime cross-request ownership checks",
    )
    replace_once(
        TRACEABILITY,
        "    critical_5e = {\n"
        '        "GRPROD-021": (\n',
        "    critical_5e = {\n"
        '        "GRAG-044": (\n'
        '            "issue:#254:deferred:graph-dependent-decision-exact-fallback-"\n'
        '            "watch-or-operational-hold"\n'
        "        ),\n"
        '        "GRAG-045": (\n'
        '            "issue:#254:deferred:source-collection-and-lead-creation-"\n'
        '            "isolation-during-graph-outage"\n'
        "        ),\n"
        '        "GRPROD-024": (\n'
        '            "issue:#254:deferred:system-outage-degradation-without-"\n'
        '            "graph-free-production-profile"\n'
        "        ),\n"
        '        "TRI-024": (\n'
        '            "issue:#254:deferred:empty-retrieval-cannot-create-"\n'
        '            "hypothesis-or-candidate"\n'
        "        ),\n"
        '        "TRI-026": (\n'
        '            "issue:#254:deferred:candidate-admission-requires-current-"\n'
        '            "authoritative-collision-check"\n'
        "        ),\n"
        '        "GRPROD-021": (\n',
        label="critical five-row 5E ownership",
    )

    replace_once(
        TRACEABILITY_TEST,
        "    ALL_REQUIREMENTS,\n    DEFERRED_TO_5E_REQUIREMENTS,\n",
        "    ALL_REQUIREMENTS,\n    CROSS_REQUEST_INTEGRATION_REQUIREMENTS,\n"
        "    DEFERRED_TO_5E_REQUIREMENTS,\n",
        label="test cross-request import",
    )
    replace_once(
        TRACEABILITY_TEST,
        "        Increment5DeliveryTrace.DEFERRED_TO_5D: 16,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5E: 117,\n",
        "        Increment5DeliveryTrace.DEFERRED_TO_5D: 11,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5E: 122,\n",
        label="test delivery distribution",
    )
    old_test_set = '''    assert REQUEST_RETRIEVAL_REQUIREMENTS == {
        "GRAG-031",
        "GRAG-032",
        "GRAG-040",
        "GRAG-041",
        "GRAG-042",
        "GRAG-043",
        "GRAG-044",
        "GRAG-045",
        "GRPROD-024",
        "TRI-020",
        "TRI-021",
        "TRI-023",
        "TRI-024",
        "TRI-025",
        "TRI-026",
        "TRI-027",
    }
'''
    new_test_set = '''    assert REQUEST_RETRIEVAL_REQUIREMENTS == {
        "GRAG-031",
        "GRAG-032",
        "GRAG-040",
        "GRAG-041",
        "GRAG-042",
        "GRAG-043",
        "TRI-020",
        "TRI-021",
        "TRI-023",
        "TRI-025",
        "TRI-027",
    }
'''
    replace_once(
        TRACEABILITY_TEST,
        old_test_set,
        new_test_set,
        label="test exact 5D request set",
    )
    cross_test = '''\n\ndef test_cross_request_integration_is_owned_by_5e() -> None:\n    rows = _rows()\n    expected = {\n        "GRAG-044": (\n            "issue:#254:deferred:graph-dependent-decision-exact-fallback-"\n            "watch-or-operational-hold"\n        ),\n        "GRAG-045": (\n            "issue:#254:deferred:source-collection-and-lead-creation-isolation-"\n            "during-graph-outage"\n        ),\n        "GRPROD-024": (\n            "issue:#254:deferred:system-outage-degradation-without-graph-free-"\n            "production-profile"\n        ),\n        "TRI-024": (\n            "issue:#254:deferred:empty-retrieval-cannot-create-hypothesis-or-"\n            "candidate"\n        ),\n        "TRI-026": (\n            "issue:#254:deferred:candidate-admission-requires-current-"\n            "authoritative-collision-check"\n        ),\n    }\n    assert CROSS_REQUEST_INTEGRATION_REQUIREMENTS == frozenset(expected)\n    assert not REQUEST_RETRIEVAL_REQUIREMENTS.intersection(\n        CROSS_REQUEST_INTEGRATION_REQUIREMENTS\n    )\n    for requirement, anchor in expected.items():\n        row = rows[requirement]\n        assert row.decision_trace is Increment5DecisionTrace.BOUND_BY_5A\n        assert row.delivery_trace is Increment5DeliveryTrace.DEFERRED_TO_5E\n        assert row.delivery_issue == 254\n        assert row.decision_anchor == anchor\n\n\n'''
    insert_before(
        TRACEABILITY_TEST,
        "def test_full_untrusted_input_boundary_belongs_to_5e() -> None:\n",
        cross_test,
        label="cross-request 5E regression",
    )

    replace_once(
        DECISION,
        "- 5D / #253 — 16;\n",
        "- 5D / #253 — 11;\n",
        label="decision 5D count",
    )
    replace_once(
        DECISION,
        "- **5E / #254 — the exact closed-world remainder of 117 requirements.**\n",
        "- **5E / #254 — the exact closed-world remainder of 122 requirements.**\n",
        label="decision 5E count",
    )
    old_decision_5d = '''- **5D / #253:** exact/source-native, formal-process, and explicit-lineage
  retrieval precedes approximate similarity; deterministic fusion and
  authoritative dependency-root deduplication then produce one request. 5D
  also owns complete projectable and hydratable
  `Source → Revision → Signal → Lead → Hypothesis → Candidate` lineage,
  authoritative hydration, freshness, collision checks, and request-level
  explicit outcomes. It stops before triage and Candidate-admission
  integration.
'''
    new_decision_5d = '''- **5D / #253:** exact/source-native, formal-process, and explicit-lineage
  retrieval precedes approximate similarity; deterministic fusion and
  authoritative dependency-root deduplication then produce one read-only
  request. 5D also owns complete projectable and hydratable
  `Source → Revision → Signal → Lead → Hypothesis → Candidate` lineage,
  authoritative hydration, freshness, the request's exact collision receipt,
  and honest request-level no-match or incomplete outcomes. It stops before
  upstream collection, downstream decisions, Hypothesis or Candidate effects,
  Candidate admission, and product-profile outage behaviour.
'''
    replace_once(
        DECISION,
        old_decision_5d,
        new_decision_5d,
        label="decision closed 5D boundary",
    )
    replace_once(
        DECISION,
        "  governed-projection → hybrid-retrieval → triage → Candidate-admission\n"
        "  vertical slice; full reconciliation recovery; scoped containment;\n",
        "  governed-projection → hybrid-retrieval → triage → Candidate-admission\n"
        "  vertical slice; downstream exact-fallback/Watch/Hold decisions; Candidate\n"
        "  non-creation and collision-gated admission; source-collection and Lead\n"
        "  isolation during graph loss; system outage policy; full reconciliation\n"
        "  recovery; scoped containment;\n",
        label="decision expanded 5E integration",
    )
    old_explain = '''Four independently working branches are not a hybrid system and cannot satisfy
`TRI-021`; exact-before-approximate orchestration, fusion, and dependency-aware
deduplication create that system in 5D. A stable request still does not satisfy
`GRPROD-021`: 5E must integrate and verify the complete graph-native path through
triage and Candidate admission. Likewise, request-level
`COMPLETE`/`INCOMPLETE`/`UNAVAILABLE` outcomes do not deliver `DOPS-050` full
'''
    new_explain = '''Four independently working branches are not a hybrid system and cannot satisfy
`TRI-021`; exact-before-approximate orchestration, fusion, and dependency-aware
deduplication create that system in 5D. A request may truthfully return no-match,
incomplete state, exact collision status, or graph unavailability, but it cannot
itself create or suppress a Hypothesis or Candidate, gate Candidate admission,
place a downstream decision into Watch or Operational Hold, keep upstream source
collection running, or define whether the product has become graph-free. Those
cross-request effects (`GRAG-044`, `GRAG-045`, `GRPROD-024`, `TRI-024`, and
`TRI-026`) belong to 5E together with `GRPROD-021`. Likewise, request-level
`COMPLETE`/`INCOMPLETE`/`UNAVAILABLE` outcomes do not deliver `DOPS-050` full
'''
    replace_once(
        DECISION,
        old_explain,
        new_explain,
        label="decision request-versus-integration explanation",
    )

    replace_once(
        OPERATIONS,
        "The exact delivery split is `10 / 0 / 4 / 16 / 117 / 7 / 1` for 5A, 5B, 5C,\n",
        "The exact delivery split is `10 / 0 / 4 / 11 / 122 / 7 / 1` for 5A, 5B, 5C,\n",
        label="operations delivery split",
    )
    old_ops_5d = '''- **5D / #253:** exact/source-native, formal-process, and explicit-lineage
  retrieval before approximate similarity; deterministic fusion, authoritative
  dependency-root deduplication, complete six-stage discovery lineage,
  hydration, freshness, collision checks, and request-level outcomes.
'''
    new_ops_5d = '''- **5D / #253:** exact/source-native, formal-process, and explicit-lineage
  retrieval before approximate similarity; deterministic fusion, authoritative
  dependency-root deduplication, complete six-stage discovery lineage,
  hydration, freshness, an exact request collision receipt, and honest
  request-level no-match or incomplete outcomes. It creates no upstream or
  downstream operational or editorial effect.
'''
    replace_once(
        OPERATIONS,
        old_ops_5d,
        new_ops_5d,
        label="operations closed 5D boundary",
    )
    replace_once(
        OPERATIONS,
        "  recovery; containment; the complete governed-projection/hybrid-retrieval/\n"
        "  triage/Candidate-admission vertical slice; production/canary/live-shadow\n",
        "  recovery; containment; the complete governed-projection/hybrid-retrieval/\n"
        "  triage/Candidate-admission vertical slice; downstream decision fallback,\n"
        "  Candidate non-creation and collision-gated admission, collection/Lead\n"
        "  isolation and system outage semantics; production/canary/live-shadow\n",
        label="operations expanded 5E integration",
    )
    replace_once(
        OPERATIONS,
        "An empty result is no-match only with `COMPLETE`.\n\n",
        "An empty result is no-match only with `COMPLETE`. This request outcome does\n"
        "not itself create a Hypothesis or Candidate, authorize Candidate admission,\n"
        "select Watch or Operational Hold, continue source collection, or change the\n"
        "product profile; those effects require 5E integration and current authority.\n\n",
        label="operations outcome effect boundary",
    )

    replace_once(
        TRACEABILITY_DOC,
        "- 5D contains exactly sixteen one-request retrieval requirements;\n",
        "- 5D contains exactly eleven request-local retrieval requirements;\n",
        label="traceability 5D derivation count",
    )
    replace_once(
        TRACEABILITY_DOC,
        "the 155-row inventory, the remaining 117 requirements belong to 5E. A newly\n",
        "the 155-row inventory, the remaining 122 requirements belong to 5E. A newly\n",
        label="traceability 5E remainder count",
    )
    replace_once(
        TRACEABILITY_DOC,
        "| 5D / #253 | 16 | one-request hybrid composition, lineage, hydration, collision, and outcomes |\n"
        "| 5E / #254 | 117 | closed-world evaluation, complete graph-native vertical integration, production GraphRAG enforcement, operational policy, monitoring, admission, queues, durability, reconciliation, containment, security, recovery, and qualification |\n",
        "| 5D / #253 | 11 | one read-only request: composition, lineage, hydration, exact collision receipt, and honest outcomes |\n"
        "| 5E / #254 | 122 | closed-world evaluation, cross-request integration and outage effects, complete graph-native vertical integration, production GraphRAG enforcement, operational policy, monitoring, admission, queues, durability, reconciliation, containment, security, recovery, and qualification |\n",
        label="traceability distribution table",
    )
    old_trace_5d = '''The complete 5D inventory is:

- `GRAG-031`, `GRAG-032`, and `GRAG-040`–`GRAG-045`;
- `GRPROD-024`; and
- `TRI-020`, `TRI-021`, and `TRI-023`–`TRI-027`.

`TRI-021` belongs here because only the composer can ensure that
source-native, formal-process, and explicit-lineage retrieval precedes
approximate similarity. Four independent 5B branches cannot establish that
ordering.

`GRPROD-021` belongs to 5E because a one-request Retrieval Context stops before
the required end-to-end triage and Candidate-admission integration.
'''
    new_trace_5d = '''The complete 5D inventory is:

- `GRAG-031`, `GRAG-032`, and `GRAG-040`–`GRAG-043`; and
- `TRI-020`, `TRI-021`, `TRI-023`, `TRI-025`, and `TRI-027`.

`TRI-021` belongs here because only the composer can ensure that
source-native, formal-process, and explicit-lineage retrieval precedes
approximate similarity. Four independent 5B branches cannot establish that
ordering.

Five obligations consume retrieval results but cross the request boundary and
therefore belong to 5E: `GRAG-044` downstream fallback/Watch/Hold decisions,
`GRAG-045` upstream collection and Lead isolation, `GRPROD-024` product-level
outage degradation, `TRI-024` downstream Hypothesis/Candidate non-creation, and
`TRI-026` Candidate-admission collision enforcement. `GRPROD-021` likewise
belongs to 5E because a Retrieval Context stops before end-to-end triage and
Candidate admission.
'''
    replace_once(
        TRACEABILITY_DOC,
        old_trace_5d,
        new_trace_5d,
        label="traceability exact closed 5D inventory",
    )
    replace_once(
        TRACEABILITY_DOC,
        "- `TRI-021` → 5D/#253: independent retrievers cannot establish exact-before-approximate ordering; the composer must enforce it.\n",
        "- `GRAG-044`, `GRAG-045`, `GRPROD-024`, `TRI-024`, and `TRI-026` → 5E/#254: request evidence cannot itself enforce downstream decisions or Candidate admission, continue upstream collection, or define product-level outage semantics.\n"
        "- `TRI-021` → 5D/#253: independent retrievers cannot establish exact-before-approximate ordering; the composer must enforce it.\n",
        label="traceability cross-request key boundary",
    )
    replace_once(
        TRACEABILITY_DOC,
        "row in 5C or 5D; any operational `DOPS-*` row other than `DOPS-076` assigned\n"
        "before 5E; `TRI-028` assigned before durable later reconciliation; material\n",
        "row in 5C or 5D; any cross-request integration row assigned to 5D; any\n"
        "operational `DOPS-*` row other than `DOPS-076` assigned before 5E; `TRI-028`\n"
        "assigned before durable later reconciliation; material\n",
        label="traceability verification invariant",
    )

    # Closed-world assertions after materialisation.
    model_text = MODEL.read_text(encoding="utf-8")
    request_section = model_text.split(
        "REQUEST_RETRIEVAL_REQUIREMENTS = frozenset(", 1
    )[1].split("CROSS_REQUEST_INTEGRATION_REQUIREMENTS", 1)[0]
    cross_section = model_text.split(
        "CROSS_REQUEST_INTEGRATION_REQUIREMENTS = frozenset(", 1
    )[1].split("DELIVERED_IN_5A_REQUIREMENTS", 1)[0]
    for requirement in CROSS_REQUEST_ANCHORS:
        if requirement in request_section or requirement not in cross_section:
            raise RuntimeError(f"cross-request partition differs: {requirement}")

    anchor_text = ANCHORS.read_text(encoding="utf-8").replace('"\n        "', "")
    for requirement, anchor in CROSS_REQUEST_ANCHORS.items():
        if requirement not in anchor_text or anchor not in anchor_text:
            raise RuntimeError(f"missing exact cross-request anchor: {requirement}")

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
        "schema_version": "newsroom.increment5a.request-boundary-audit.v1",
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
            "5D": 11,
            "5E": 122,
            "INCREMENT_4": 7,
            "OUTSIDE_ACTIVATION": 1,
            "TOTAL": 155,
        },
        "request_local_5d": sorted(
            {
                "GRAG-031",
                "GRAG-032",
                "GRAG-040",
                "GRAG-041",
                "GRAG-042",
                "GRAG-043",
                "TRI-020",
                "TRI-021",
                "TRI-023",
                "TRI-025",
                "TRI-027",
            }
        ),
        "moved_to_5e": sorted(CROSS_REQUEST_ANCHORS),
        "changed_paths": sorted(str(path.relative_to(ROOT)) for path in changed),
    }
    OUTPUT.write_bytes(canonical(result))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
