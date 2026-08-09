"""Mandatory family, slice, triage, and branch gates for Increment 5E1."""

from __future__ import annotations

from collections.abc import Mapping

from ._retrieval_qualification_common import MODE_ORDER, QualificationSystem
from ._retrieval_qualification_contracts import QualificationCorpus
from ._retrieval_qualification_evidence import QualificationObservation
from ._retrieval_qualification_measurement import _ppm, _slice_metric


def _family_metrics(
    corpus: QualificationCorpus,
    observations: Mapping[
        tuple[str, QualificationSystem],
        QualificationObservation,
    ],
    plan: Mapping[str, object],
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[str],
]:
    minima = plan["exposure_minima"]
    results: list[dict[str, object]] = []
    blockers: list[str] = []
    for family in plan["mandatory_query_families"]:
        family_id = family["family_id"]
        selected = [case for case in corpus.cases if case.family_id == family_id]
        hybrid = [
            observations[(case.case_id, QualificationSystem.HYBRID)]
            for case in selected
        ]
        returned = sum(len(item.ranked_roots) for item in hybrid)
        true_positive = sum(
            case.expected_root in item.ranked_roots
            for case, item in zip(selected, hybrid, strict=True)
        )
        required_slices = [
            _slice_metric(slice_id, selected, observations)
            for slice_id in family["required_slices"]
        ]
        criteria = family["acceptance_criteria"]
        precision = _ppm(true_positive, returned)
        recall = _ppm(true_positive, len(selected))
        provenance = _ppm(
            sum(item.provenance_complete for item in hybrid),
            len(hybrid),
        )
        temporal_errors = sum(not item.temporal_correct for item in hybrid)
        distractor_cases = [
            case
            for case in selected
            if "DISTRACTOR_FALSE_MERGE" in case.slice_labels
        ]
        distractor_errors = sum(
            case.prohibited_root
            in observations[
                (case.case_id, QualificationSystem.HYBRID)
            ].ranked_roots
            for case in distractor_cases
        )
        distractor_precision = _ppm(
            len(distractor_cases) - distractor_errors,
            len(distractor_cases),
        )
        family_exposure_blockers: list[str] = []
        if (
            len(selected)
            < minima["minimum_cases_by_query_family"][family_id]
        ):
            family_exposure_blockers.append(
                f"FAMILY_EXPOSURE:{family_id}:CASES"
            )
        family_slice_minimum = minima[
            "minimum_relevant_cases_per_family_required_slice"
        ]
        family_exposure_blockers.extend(
            f"FAMILY_EXPOSURE:{family_id}:{item['slice_id']}"
            for item in required_slices
            if item["case_count"] < family_slice_minimum
        )
        quality_passed = (
            precision >= criteria["minimum_precision_ppm"]
            and recall >= criteria["minimum_recall_ppm"]
            and all(
                item["recall_at_12_ppm"]
                >= criteria["minimum_required_slice_recall_ppm"]
                for item in required_slices
            )
            and provenance
            >= criteria.get("minimum_provenance_completeness_ppm", 0)
            and temporal_errors
            <= criteria.get("temporal_correctness_error_count_max", 0)
            and distractor_precision
            >= criteria.get("distractor_false_merge_precision_ppm", 0)
        )
        passed = not family_exposure_blockers and quality_passed
        results.append(
            {
                "family_id": family_id,
                "case_count": len(selected),
                "expected_root_count": len(selected),
                "returned_root_count": returned,
                "true_positive_count": true_positive,
                "false_positive_count": returned - true_positive,
                "false_negative_count": len(selected) - true_positive,
                "precision_ppm": precision,
                "recall_ppm": recall,
                "required_slices": required_slices,
                "provenance_completeness_ppm": provenance,
                "temporal_correctness_error_count": temporal_errors,
                "distractor_false_merge_opportunity_count": len(
                    distractor_cases
                ),
                "distractor_false_merge_error_count": distractor_errors,
                "distractor_false_merge_precision_ppm": distractor_precision,
                "passed": passed,
            }
        )
        blockers.extend(family_exposure_blockers)
        if not family_exposure_blockers and not quality_passed:
            blockers.append(f"MANDATORY_FAMILY:{family_id}")

    global_slices: list[dict[str, object]] = []
    for slice_id in plan["contract_evaluation_summary"]["required_slices"]:
        metric = _slice_metric(slice_id, corpus.cases, observations)
        global_slices.append(metric)
        if (
            metric["case_count"]
            < minima["minimum_relevant_cases_by_required_slice"][slice_id]
        ):
            blockers.append(f"SLICE_EXPOSURE:{slice_id}")
        elif (
            metric["recall_at_12_ppm"]
            < plan["contract_evaluation_summary"]["thresholds"][
                "required_slice_recall_at_12_min_ppm"
            ]
        ):
            blockers.append(f"REQUIRED_SLICE:{slice_id}")
    return results, global_slices, blockers


def _triage_metrics(
    corpus: QualificationCorpus,
    observations: Mapping[
        tuple[str, QualificationSystem],
        QualificationObservation,
    ],
    plan: Mapping[str, object],
) -> tuple[list[dict[str, object]], list[str]]:
    minimum = plan["exposure_minima"][
        "minimum_relevant_cases_per_triage_error_class"
    ]
    results: list[dict[str, object]] = []
    blockers: list[str] = []
    for error_class in plan["triage_error_protocol"]["error_classes"]:
        class_id = error_class["class_id"]
        eligible_labels = set(error_class["eligible_case_labels"])
        selected = [
            case
            for case in corpus.cases
            if eligible_labels
            & (set(case.slice_labels) | set(case.triage_labels))
        ]
        errors = 0
        for case in selected:
            observation = observations[
                (case.case_id, QualificationSystem.HYBRID)
            ]
            if class_id in {"FALSE_MERGE", "SNOWBALL_ABSORPTION"}:
                errors += case.prohibited_root in observation.ranked_roots
            elif class_id in {
                "FRAGMENTATION",
                "FALSE_OR_MISSED_DEVELOPMENT",
            }:
                errors += case.expected_root not in observation.ranked_roots
            elif class_id == "DUPLICATE_CANDIDATE_CREATION":
                errors += (
                    observation.candidate_disposition_count
                    > case.expected_candidate_count
                )
            else:
                errors += (
                    case.expected_candidate_count == 0
                    and observation.candidate_disposition_count > 0
                )
        results.append(
            {
                "class_id": class_id,
                "opportunity_count": len(selected),
                "error_count": errors,
                "rate_ppm": _ppm(errors, len(selected), 0),
                "automatic_blocker": error_class["automatic_blocker"],
            }
        )
        if len(selected) < minimum:
            blockers.append(f"TRIAGE_EXPOSURE:{class_id}")
        elif error_class["automatic_blocker"] and errors:
            blockers.append(f"TRIAGE_BLOCKER:{class_id}")
    return results, blockers


def _branch_contributions(
    corpus: QualificationCorpus,
    observations: Mapping[
        tuple[str, QualificationSystem],
        QualificationObservation,
    ],
) -> list[dict[str, object]]:
    hybrid = [
        observations[(case.case_id, QualificationSystem.HYBRID)]
        for case in corpus.cases
    ]
    results: list[dict[str, object]] = []
    for mode in MODE_ORDER:
        selected = [item for item in hybrid if mode in item.contributing_modes]
        relevant = sum(
            case.expected_root in item.ranked_roots
            for case, item in zip(corpus.cases, hybrid, strict=True)
            if mode in item.contributing_modes
        )
        results.append(
            {
                "mode": mode.value,
                "contributed_case_count": len(selected),
                "relevant_hit_case_count": relevant,
                "unique_dependency_root_count": len(
                    {
                        root
                        for item in selected
                        for root in item.ranked_roots
                    }
                ),
            }
        )
    return results


