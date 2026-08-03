#!/usr/bin/env python3
"""Materialize the final Increment 5A review corrections on staging only.

The source branch already contains the validated qualification-scope digest
replacement. This helper performs the remaining closed-world ownership
correction as one set operation: GRPROD-002 and GRPROD-023 leave 5A, and the
computed 5E remainder grows from 114 to 116. The final PR commit is assembled
separately over the fixed base and does not include this helper.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE_HEAD = "024821fb813cd0ebe44998377bc2117c167e3dda"
EXPECTED_SCOPE = (
    "RETRIEVER_INDEX_FUSION_DEDUPLICATION_HYDRATION_DEGRADATION_"
    "AND_RECOVERY_ONLY"
)

MODEL = ROOT / "newsroom/increment5/_traceability_model.py"
ANCHORS = ROOT / "newsroom/increment5/_traceability_anchors.py"
TRACEABILITY = ROOT / "newsroom/increment5/traceability.py"
TRACEABILITY_TEST = ROOT / "newsroom/tests/test_increment5a_traceability.py"
DECISION = ROOT / (
    "docs/decisions/2026-08-02-increment-5a-production-retrieval-contract.md"
)
OPERATIONS = ROOT / "docs/operations/increment-5-production-retrieval-contract.md"
TRACEABILITY_DOC = ROOT / "docs/traceability/increment-5-production-retrieval.md"
QUALIFICATION_SCHEMA = ROOT / (
    "newsroom/increment5/data/increment5_qualification_profile_structural_v1.schema.json"
)
OUTPUT = ROOT / "increment5a-final-candidate-manifest.json"


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


def append_before(path: Path, marker: str, addition: str, *, label: str) -> None:
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
    structural = json.loads(QUALIFICATION_SCHEMA.read_text(encoding="utf-8"))
    scope = structural["properties"]["expected_outcome_scope"]["const"]
    if scope != EXPECTED_SCOPE:
        raise RuntimeError(f"qualification scope differs before finalization: {scope}")

    # Delivery is a partition. Removing exactly these two rows from the explicit
    # 5A set causes the closed-world remainder to own them in 5E automatically.
    replace_once(
        MODEL,
        '        "GRPROD-002",\n        "GRPROD-023",\n',
        "",
        label="remove production enforcement from 5A delivery",
    )
    replace_once(
        MODEL,
        "if len(DEFERRED_TO_5E_REQUIREMENTS) != 114:\n"
        '    raise RuntimeError("5E closed-world remainder must contain 114 requirements")\n',
        "if len(DEFERRED_TO_5E_REQUIREMENTS) != 116:\n"
        '    raise RuntimeError("5E closed-world remainder must contain 116 requirements")\n',
        label="5E remainder cardinality",
    )

    replace_once(
        ANCHORS,
        '    (\n        f"{_CONTRACT}#/payload/required_modes",\n'
        '        frozenset({"GRPROD-001", "GRPROD-002", "TRI-021"}),\n'
        "    ),\n",
        '    (\n        f"{_CONTRACT}#/payload/required_modes",\n'
        '        frozenset({"GRPROD-001", "TRI-021"}),\n'
        "    ),\n"
        "    (\n"
        '        "issue:#254:deferred:no-production-canary-or-complete-live-shadow-"\n'
        '        "without-graphrag",\n'
        '        frozenset({"GRPROD-002"}),\n'
        "    ),\n",
        label="GRPROD-002 deferred anchor",
    )
    replace_once(
        ANCHORS,
        '    (\n        f"{_CONTRACT}#/payload/components",\n'
        '        frozenset({"GRAG-050", "GRAG-052", "GRPROD-010", "GRPROD-023"}),\n'
        "    ),\n",
        '    (\n        f"{_CONTRACT}#/payload/components",\n'
        '        frozenset({"GRAG-050", "GRAG-052", "GRPROD-010"}),\n'
        "    ),\n"
        "    (\n"
        '        "issue:#254:deferred:graphrag-cannot-be-an-optional-"\n'
        '        "production-plugin",\n'
        '        frozenset({"GRPROD-023"}),\n'
        "    ),\n",
        label="GRPROD-023 deferred anchor",
    )

    replace_once(
        TRACEABILITY,
        "        Increment5DeliveryTrace.DELIVERED_IN_5A: 12,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5B: 1,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5C: 4,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5D: 16,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5E: 114,\n",
        "        Increment5DeliveryTrace.DELIVERED_IN_5A: 10,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5B: 1,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5C: 4,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5D: 16,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5E: 116,\n",
        label="runtime delivery distribution",
    )
    replace_once(
        TRACEABILITY,
        "    critical_5e = {\n"
        '        "TRI-028": (\n',
        "    critical_5e = {\n"
        '        "GRPROD-002": (\n'
        '            "issue:#254:deferred:no-production-canary-or-complete-"\n'
        '            "live-shadow-without-graphrag"\n'
        "        ),\n"
        '        "GRPROD-023": (\n'
        '            "issue:#254:deferred:graphrag-cannot-be-an-optional-"\n'
        '            "production-plugin"\n'
        "        ),\n"
        '        "TRI-028": (\n',
        label="critical production-enforcement ownership",
    )

    replace_once(
        TRACEABILITY_TEST,
        "        Increment5DeliveryTrace.DELIVERED_IN_5A: 12,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5B: 1,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5C: 4,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5D: 16,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5E: 114,\n",
        "        Increment5DeliveryTrace.DELIVERED_IN_5A: 10,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5B: 1,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5C: 4,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5D: 16,\n"
        "        Increment5DeliveryTrace.DEFERRED_TO_5E: 116,\n",
        label="test delivery distribution",
    )
    ownership_test = '''\n\ndef test_production_graphrag_enforcement_is_owned_by_5e() -> None:\n    rows = _rows()\n    expected = {\n        "GRPROD-002": (\n            "issue:#254:deferred:no-production-canary-or-complete-live-shadow-"\n            "without-graphrag"\n        ),\n        "GRPROD-023": (\n            "issue:#254:deferred:graphrag-cannot-be-an-optional-production-"\n            "plugin"\n        ),\n    }\n    for requirement, anchor in expected.items():\n        row = rows[requirement]\n        assert row.decision_trace is Increment5DecisionTrace.BOUND_BY_5A\n        assert row.delivery_trace is Increment5DeliveryTrace.DEFERRED_TO_5E\n        assert row.delivery_issue == 254\n        assert row.decision_anchor == anchor\n\n\n'''
    append_before(
        TRACEABILITY_TEST,
        "def test_every_requirement_has_one_explicit_anchor() -> None:\n",
        ownership_test,
        label="production GraphRAG ownership regression",
    )

    replace_once(
        DECISION,
        "- 5A / #250 — 12;\n",
        "- 5A / #250 — 10;\n",
        label="decision 5A count",
    )
    replace_once(
        DECISION,
        "- **5E / #254 — the exact closed-world remainder of 114 requirements.**\n",
        "- **5E / #254 — the exact closed-world remainder of 116 requirements.**\n",
        label="decision 5E count",
    )
    replace_once(
        DECISION,
        "This can qualify index construction, query execution, rank handling, fusion,\n"
        "hydration, degradation, and rebuild behaviour. It cannot establish embedding\n",
        "This can qualify index construction, query execution, rank handling, fusion,\n"
        "dependency-root deduplication, hydration, degradation, recovery, and rebuild\n"
        "behaviour. It cannot establish embedding\n",
        label="decision complete qualification surfaces",
    )
    replace_once(
        DECISION,
        "The qualification profile may use authenticated Neo4j and a signed,\n"
        "rights-cleared, repository-safe dataset manifest. Its evidence is limited to\n"
        "retriever, index, fusion, hydration, degradation, and recovery behaviour.\n",
        "The qualification profile may use authenticated Neo4j and a signed,\n"
        "rights-cleared, repository-safe dataset manifest. Its evidence is limited to\n"
        "retriever, index, fusion, dependency-root deduplication, hydration,\n"
        "degradation, and recovery behaviour.\n",
        label="decision profile outcome scope",
    )
    replace_once(
        DECISION,
        "These profiles are not production deployment profiles. Production rejection of\n"
        "fake, disabled, or omitted GraphRAG and production build/readiness validation\n"
        "remain 5E/#254 work.\n",
        "These profiles are not production deployment profiles. Production rejection of\n"
        "fake, disabled, or omitted GraphRAG and production build/readiness validation\n"
        "remain 5E/#254 work. `GRPROD-002` and `GRPROD-023` are therefore bound by\n"
        "5A but delivered only when #254 implements and verifies the production, canary,\n"
        "and complete-live-shadow rejection paths.\n",
        label="decision production enforcement ownership",
    )

    replace_once(
        OPERATIONS,
        "The exact delivery split is `12 / 1 / 4 / 16 / 114 / 7 / 1` for 5A, 5B, 5C,\n",
        "The exact delivery split is `10 / 1 / 4 / 16 / 116 / 7 / 1` for 5A, 5B, 5C,\n",
        label="operations delivery split",
    )
    replace_once(
        OPERATIONS,
        "  monitoring and incidents; security; rights purge; full reconciliation\n"
        "  recovery; containment; canary, rollback and rebuild; and actual-service\n"
        "  qualification.\n",
        "  monitoring and incidents; security; rights purge; full reconciliation\n"
        "  recovery; containment; production/canary/live-shadow GraphRAG enforcement;\n"
        "  rollback and rebuild; and actual-service qualification.\n",
        label="operations 5E production enforcement",
    )

    replace_once(
        TRACEABILITY_DOC,
        "- 5A contains the twelve contract, Plan, profile, non-activation, and\n",
        "- 5A contains the ten contract, Plan, profile, non-activation, and\n",
        label="traceability 5A derivation count",
    )
    replace_once(
        TRACEABILITY_DOC,
        "the 155-row inventory, the remaining 114 requirements belong to 5E. A newly\n",
        "the 155-row inventory, the remaining 116 requirements belong to 5E. A newly\n",
        label="traceability 5E derivation count",
    )
    replace_once(
        TRACEABILITY_DOC,
        "| 5A / #250 | 12 | contract, safe profiles, frozen Plan/Epoch protocol, and traceability |\n",
        "| 5A / #250 | 10 | contract, safe profiles, frozen Plan/Epoch protocol, and traceability |\n",
        label="traceability table 5A count",
    )
    replace_once(
        TRACEABILITY_DOC,
        "| 5E / #254 | 114 | closed-world evaluation, operational policy, monitoring, admission, queues, durability, reconciliation, containment, security, recovery, and qualification |\n",
        "| 5E / #254 | 116 | closed-world evaluation, production GraphRAG enforcement, operational policy, monitoring, admission, queues, durability, reconciliation, containment, security, recovery, and qualification |\n",
        label="traceability table 5E count",
    )
    replace_once(
        TRACEABILITY_DOC,
        "`DEVAL-010`, `DEVAL-011`, `DEVAL-012`, `DEVAL-051`, `DEVAL-072`,\n"
        "`DOPS-076`, `GRAG-052`, `GRAG-053`, `GRAG-058`, `GRPROD-002`,\n"
        "`GRPROD-023`, and `GRPROD-032`.\n",
        "`DEVAL-010`, `DEVAL-011`, `DEVAL-012`, `DEVAL-051`, `DEVAL-072`,\n"
        "`DOPS-076`, `GRAG-052`, `GRAG-053`, `GRAG-058`, and `GRPROD-032`.\n",
        label="traceability delivered-in-5A inventory",
    )
    replace_once(
        TRACEABILITY_DOC,
        "`DEVAL-011` points directly to the machine Plan’s `#/epoch_protocol`. Before a\n",
        "`GRPROD-002` and `GRPROD-023` remain 5E delivery. Their rules are bound by\n"
        "5A, but only #254 can implement and verify that production, canary, and complete\n"
        "live shadow reject omitted GraphRAG and cannot treat GraphRAG as an optional\n"
        "plugin.\n\n"
        "`DEVAL-011` points directly to the machine Plan’s `#/epoch_protocol`. Before a\n",
        label="traceability production enforcement explanation",
    )
    replace_once(
        TRACEABILITY_DOC,
        "- `GRAG-031` → 5D/#253: independent branches are not a hybrid until fusion and authoritative dependency-root deduplication exist.\n",
        "- `GRPROD-002` and `GRPROD-023` → 5E/#254: policy declarations do not deliver the production, canary, and complete-live-shadow no-omission/no-optional-plugin enforcement paths.\n"
        "- `GRAG-031` → 5D/#253: independent branches are not a hybrid until fusion and authoritative dependency-root deduplication exist.\n",
        label="traceability key production boundary",
    )

    model_text = MODEL.read_text(encoding="utf-8")
    delivered_section = model_text.split(
        "DELIVERED_IN_5A_REQUIREMENTS = frozenset(", 1
    )[1].split("DEFERRED_TO_5B_REQUIREMENTS", 1)[0]
    for requirement in ("GRPROD-002", "GRPROD-023"):
        if requirement in delivered_section:
            raise RuntimeError(f"{requirement} remains in 5A delivery")

    anchor_text = ANCHORS.read_text(encoding="utf-8")
    required_anchors = {
        "GRPROD-002": (
            "issue:#254:deferred:no-production-canary-or-complete-live-shadow-"
            "without-graphrag"
        ),
        "GRPROD-023": (
            "issue:#254:deferred:graphrag-cannot-be-an-optional-production-plugin"
        ),
    }
    for requirement, anchor in required_anchors.items():
        if requirement not in anchor_text or anchor not in anchor_text.replace('"\n        "', ""):
            raise RuntimeError(f"missing exact deferred anchor for {requirement}")

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
        "schema_version": "newsroom.increment5a.final-candidate.v1",
        "source_head": SOURCE_HEAD,
        "qualification_scope": EXPECTED_SCOPE,
        "delivery_counts": {
            "5A": 10,
            "5B": 1,
            "5C": 4,
            "5D": 16,
            "5E": 116,
            "INCREMENT_4": 7,
            "OUTSIDE_ACTIVATION": 1,
            "TOTAL": 155,
        },
        "moved_to_5e": sorted(required_anchors),
        "changed_paths": sorted(str(path.relative_to(ROOT)) for path in changed),
    }
    OUTPUT.write_bytes(canonical(result))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
