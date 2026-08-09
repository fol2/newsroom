"""Deterministic system, slice, and exposure measurements for Increment 5E1."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
import math

from ._retrieval_qualification_common import (
    PPM,
    RESULT_LIMIT,
    QualificationMode,
    QualificationOutcome,
    QualificationSystem,
)
from ._retrieval_qualification_contracts import (
    QualificationCase,
    QualificationCorpus,
)
from ._retrieval_qualification_evidence import QualificationObservation


def _ppm(numerator: int, denominator: int, empty: int = PPM) -> int:
    return empty if denominator == 0 else numerator * PPM // denominator


def _p95(values: Sequence[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[math.ceil(len(ordered) * 0.95) - 1]


def _first_rank(roots: tuple[str, ...], expected: str) -> int | None:
    return next(
        (
            rank
            for rank, root in enumerate(roots[:RESULT_LIMIT], 1)
            if root == expected
        ),
        None,
    )


def _system_metrics(
    system: QualificationSystem,
    cases: Sequence[QualificationCase],
    observations: Mapping[
        tuple[str, QualificationSystem],
        QualificationObservation,
    ],
) -> dict[str, object]:
    selected = [observations[(case.case_id, system)] for case in cases]
    returned_root_count = sum(len(item.ranked_roots) for item in selected)
    true_positive_count = sum(
        case.expected_root in item.ranked_roots
        for case, item in zip(cases, selected, strict=True)
    )
    false_positive_count = sum(
        sum(root != case.expected_root for root in item.ranked_roots)
        for case, item in zip(cases, selected, strict=True)
    )
    reciprocal_rank_ppm = sum(
        PPM // rank
        if (rank := _first_rank(item.ranked_roots, case.expected_root))
        else 0
        for case, item in zip(cases, selected, strict=True)
    )
    exact_cases = [
        (case, item)
        for case, item in zip(cases, selected, strict=True)
        if case.fixture_mapping[QualificationMode.EXACT]
    ]
    exact_top_hits = sum(
        bool(item.ranked_roots)
        and item.ranked_roots[0] == case.expected_root
        for case, item in exact_cases
    )
    return {
        "system": system.value,
        "decision_bearing": system is QualificationSystem.HYBRID,
        "case_count": len(cases),
        "complete_count": sum(
            item.outcome is QualificationOutcome.COMPLETE
            for item in selected
        ),
        "non_complete_count": sum(
            item.outcome is not QualificationOutcome.COMPLETE
            for item in selected
        ),
        "expected_root_count": len(cases),
        "returned_root_count": returned_root_count,
        "true_positive_count": true_positive_count,
        "false_positive_count": false_positive_count,
        "false_negative_count": len(cases) - true_positive_count,
        "precision_ppm": _ppm(true_positive_count, returned_root_count),
        "recall_at_12_ppm": _ppm(true_positive_count, len(cases)),
        "mrr_at_12_ppm": reciprocal_rank_ppm // len(cases),
        "exact_identifier_case_count": len(exact_cases),
        "exact_identifier_top_hit_count": exact_top_hits,
        "exact_identifier_precision_at_1_ppm": _ppm(
            exact_top_hits,
            len(exact_cases),
        ),
        "provenance_completeness_ppm": _ppm(
            sum(item.provenance_complete for item in selected),
            len(cases),
        ),
        "trust_label_completeness_ppm": _ppm(
            sum(item.trust_labels_complete for item in selected),
            len(cases),
        ),
        "p95_latency_ms": _p95([item.latency_ms for item in selected]),
        "truncation_count": sum(item.truncated for item in selected),
        "false_no_match_count": sum(
            item.outcome is QualificationOutcome.COMPLETE
            and not item.ranked_roots
            for item in selected
        ),
        "temporal_correctness_error_count": sum(
            not item.temporal_correct for item in selected
        ),
        "rights_purge_residual_count": sum(
            item.rights_purge_residual_count for item in selected
        ),
        "scope_escape_count": sum(item.scope_escape_count for item in selected),
        "write_attempt_success_count": sum(
            item.write_attempt_success_count for item in selected
        ),
        "rebuild_reproducibility_mismatch_count": sum(
            item.rebuild_reproducibility_mismatch_count
            for item in selected
        ),
        "candidate_disposition_count": sum(
            item.candidate_disposition_count for item in selected
        ),
        "vector_fixture_replay_only": (
            system is QualificationSystem.VECTOR_ONLY
        ),
    }


def _slice_metric(
    slice_id: str,
    cases: Sequence[QualificationCase],
    observations: Mapping[
        tuple[str, QualificationSystem],
        QualificationObservation,
    ],
) -> dict[str, object]:
    selected = [case for case in cases if slice_id in case.slice_labels]
    relevant_hits = sum(
        case.expected_root
        in observations[
            (case.case_id, QualificationSystem.HYBRID)
        ].ranked_roots
        for case in selected
    )
    return {
        "slice_id": slice_id,
        "case_count": len(selected),
        "expected_root_count": len(selected),
        "relevant_hit_count": relevant_hits,
        "recall_at_12_ppm": _ppm(relevant_hits, len(selected)),
    }


def _exposure_metrics(
    corpus: QualificationCorpus,
    plan: Mapping[str, object],
) -> tuple[list[dict[str, object]], list[str]]:
    minima = plan["exposure_minima"]
    family_counts = Counter(case.family_id for case in corpus.cases)
    case_type_counts = Counter(case.case_type for case in corpus.cases)
    slice_counts = Counter(
        label for case in corpus.cases for label in case.slice_labels
    )
    rows: list[dict[str, object]] = []
    blockers: list[str] = []

    def add(dimension: str, name: str, count: int, required: int) -> None:
        sufficient = count >= required
        rows.append(
            {
                "dimension": dimension,
                "name": name,
                "count": count,
                "required_minimum": required,
                "sufficient": sufficient,
            }
        )
        if not sufficient:
            blockers.append(f"EXPOSURE:{dimension}:{name}")

    add(
        "TOTAL",
        "UNIQUE_CASES",
        len(corpus.cases),
        minima["minimum_total_unique_qualification_cases"],
    )
    for family_id, required in minima["minimum_cases_by_query_family"].items():
        add("FAMILY", family_id, family_counts[family_id], required)
    required_case_types = sorted(
        {
            case_type
            for family in plan["mandatory_query_families"]
            for case_type in family["required_case_types"]
        }
    )
    for case_type in required_case_types:
        add(
            "CASE_TYPE",
            case_type,
            case_type_counts[case_type],
            minima["minimum_cases_per_required_case_type"],
        )
    for slice_id, required in minima[
        "minimum_relevant_cases_by_required_slice"
    ].items():
        add("SLICE", slice_id, slice_counts[slice_id], required)
    return rows, blockers


