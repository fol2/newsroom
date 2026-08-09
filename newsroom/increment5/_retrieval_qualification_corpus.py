"""Frozen repository-owned qualification corpus loader for Increment 5E1."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from ._retrieval_qualification_common import (
    CORPUS_SPEC,
    CORPUS_SPEC_DIGEST,
    MODE_ORDER,
    QualificationMode,
    RetrievalQualificationError,
    digest,
    thaw,
)
from ._retrieval_qualification_contracts import (
    QualificationCase,
    QualificationCorpus,
)
from .decision import INCREMENT_5A_CONTRACT_DIGEST
from .evaluation_plan import EVALUATION_PLAN_DIGEST, INCREMENT_5_EVALUATION_PLAN


def _case_label_value(case: QualificationCase) -> dict[str, object]:
    return {
        "case_id": case.case_id,
        "family_id": case.family_id,
        "case_type": case.case_type,
        "language": case.language,
        "query_valid_time": case.query_valid_time,
        "expected_root": case.expected_root,
        "prohibited_root": case.prohibited_root,
        "slice_labels": list(case.slice_labels),
        "triage_labels": list(case.triage_labels),
        "expected_candidate_count": case.expected_candidate_count,
    }


def _case_fixture_value(case: QualificationCase) -> dict[str, object]:
    return {
        "case_id": case.case_id,
        "fixture_hits": [
            {"mode": mode.value, "roots": list(roots)}
            for mode, roots in case.fixture_hits
        ],
        "source_inventory_ids": list(case.source_inventory_ids),
    }


def rederive_qualification_corpus(
    corpus: QualificationCorpus,
) -> QualificationCorpus:
    """Return the corpus with every content-derived identity recomputed."""

    cases = tuple(
        replace(
            case,
            label_digest=digest(_case_label_value(case)),
            fixture_digest=digest(_case_fixture_value(case)),
        )
        for case in corpus.cases
    )
    source_inventory = sorted(
        {
            source_id
            for case in cases
            for source_id in case.source_inventory_ids
        }
    )
    return replace(
        corpus,
        cases=cases,
        query_set_digest=digest(
            [
                {
                    "case_id": case.case_id,
                    "query_valid_time": case.query_valid_time,
                }
                for case in cases
            ]
        ),
        source_inventory_digest=digest(source_inventory),
        dataset_manifest_digest=digest(
            [
                {
                    "case_id": case.case_id,
                    "family_id": case.family_id,
                    "case_type": case.case_type,
                    "language": case.language,
                    "label_digest": case.label_digest,
                    "fixture_digest": case.fixture_digest,
                }
                for case in cases
            ]
        ),
    )


def validate_qualification_corpus_content_identities(
    corpus: QualificationCorpus,
) -> None:
    """Fail closed when supplied content reuses any stale stored identity."""

    spec = thaw(CORPUS_SPEC)
    if (
        corpus.corpus_id != spec["corpus_id"]
        or corpus.generator_version != spec["generator_version"]
        or corpus.label_policy_digest != digest(spec["label_policy"])
        or corpus.corpus_spec_digest != CORPUS_SPEC_DIGEST
    ):
        raise RetrievalQualificationError(
            "qualification corpus policy identity differs"
        )
    if rederive_qualification_corpus(corpus) != corpus:
        raise RetrievalQualificationError(
            "qualification corpus content identities differ"
        )


def _candidate_count(case_type: str) -> int:
    return 0 if case_type in {
        "SAME_EVENT_STATE",
        "CORRECTION_IMPACT",
        "TEMPORAL_CUTOFF",
    } else 1


def _semantic_slice_labels(
    *,
    family_id: str,
    case_type: str,
    language: str,
    sequence: int,
    global_slices: Sequence[Sequence[object]],
) -> set[str]:
    labels = {language}
    if family_id == "EVENT_AND_DEVELOPMENT_PRECISION" and case_type in {
        "DEVELOPMENT_OF_EXISTING_EVENT",
        "RELATED_BUT_DISTINCT_EVENT",
    }:
        labels.add("DISTRACTOR_FALSE_MERGE")
    if family_id == "SOURCE_REVISION_IMPACT" and case_type in {
        "CORRECTION_IMPACT",
        "SUPERSESSION_IMPACT",
    }:
        labels.add("CORRECTION_AND_SUPERSESSION")
    if family_id == "SOURCE_REVISION_IMPACT" and case_type == "CORRECTION_IMPACT":
        labels.add("TEMPORAL_CUTOFF")
    if family_id == "LONG_RUNNING_POLICY_CASE_OR_PROCESS_TIMELINE":
        labels.add("LONG_RUNNING_TIMELINE")
        if case_type == "TEMPORAL_CUTOFF":
            labels.add("TEMPORAL_CUTOFF")
    for name, first, last in global_slices:
        if int(first) <= sequence <= int(last):
            labels.add(str(name))
    return labels


def _triage_labels(
    case_type: str,
    expected_candidate_count: int,
) -> tuple[str, ...]:
    labels = {case_type}
    labels.add(
        "SINGLE_CANDIDATE_EXPECTED"
        if expected_candidate_count == 1
        else "NO_CANDIDATE_EXPECTED"
    )
    return tuple(sorted(labels))


def _signals(
    case_type: str,
    language: str,
    sequence: int,
) -> dict[QualificationMode, bool]:
    values = {
        QualificationMode.EXACT: (
            case_type
            in {
                "SAME_EVENT_STATE",
                "DOWNSTREAM_CANDIDATE_IMPACT",
                "TEMPORAL_CUTOFF",
            }
            or sequence % 2 == 0
        ),
        QualificationMode.FULL_TEXT: (
            language != "ZH_HANT_HK" or sequence % 3 != 0
        ),
        QualificationMode.VECTOR: sequence % 4 != 0,
        QualificationMode.ADMITTED_GRAPH: case_type
        in {
            "DEVELOPMENT_OF_EXISTING_EVENT",
            "CORRECTION_IMPACT",
            "SUPERSESSION_IMPACT",
            "CORRECTION",
            "ORDERED_DEVELOPMENT",
            "SUPERSESSION",
            "TEMPORAL_CUTOFF",
        },
    }
    if not any(values.values()):
        values[QualificationMode.FULL_TEXT] = True
    return values


def load_qualification_corpus(
    spec: Mapping[str, object] = CORPUS_SPEC,
) -> QualificationCorpus:
    value = thaw(spec)
    plan = thaw(INCREMENT_5_EVALUATION_PLAN)
    minima = plan["exposure_minima"]
    if digest(value) != CORPUS_SPEC_DIGEST:
        raise RetrievalQualificationError(
            "qualification corpus differs from reviewed v1"
        )
    if (
        value["contract_digest"] != INCREMENT_5A_CONTRACT_DIGEST
        or value["evaluation_plan_digest"] != EVALUATION_PLAN_DIGEST
        or value["expected_case_count"]
        != minima["minimum_total_unique_qualification_cases"]
    ):
        raise RetrievalQualificationError("corpus contract differs")
    expected_families = plan["mandatory_query_families"]
    if [item["family_id"] for item in value["families"]] != [
        item["family_id"] for item in expected_families
    ]:
        raise RetrievalQualificationError("corpus family inventory differs")
    for actual, expected in zip(
        value["families"],
        expected_families,
        strict=True,
    ):
        expected_count = minima["minimum_cases_by_query_family"][
            expected["family_id"]
        ]
        if (
            actual["count"] != expected_count
            or [item[0] for item in actual["case_types"]]
            != expected["required_case_types"]
            or any(
                item[1] != minima["minimum_cases_per_required_case_type"]
                for item in actual["case_types"]
            )
            or actual["required_slices"] != expected["required_slices"]
        ):
            raise RetrievalQualificationError("corpus exposure differs")
    semantics = value["fixture_semantics"]
    policy = value["label_policy"]
    if (
        semantics["contains_personal_data"]
        or semantics["contains_secrets_or_credentials"]
        or semantics["contains_protected_source_expression"]
        or not semantics["labels_and_branch_results_are_separate"]
        or not semantics["graph_results_are_admitted_only"]
        or not semantics["vector_results_are_fixed_point_fixture_replay_only"]
        or semantics["raw_scores_compared_across_modes"]
        or policy["human_review_or_adjudication_required"]
        or policy["calibration_cases_count"]
        or policy["cross_family_case_reuse_allowed"]
    ):
        raise RetrievalQualificationError("corpus safety policy differs")

    languages = tuple(value["language_cycle"])
    cases: list[QualificationCase] = []
    sequence = 0
    for family in value["families"]:
        for case_type, count in family["case_types"]:
            for _ in range(count):
                sequence += 1
                case_id = f"{value['case_id_prefix']}-{sequence:03d}"
                language = languages[(sequence - 1) % len(languages)]
                slices = _semantic_slice_labels(
                    family_id=family["family_id"],
                    case_type=case_type,
                    language=language,
                    sequence=sequence,
                    global_slices=value["global_slices"],
                )
                expected_root = f"authority-root:{case_id}"
                prohibited_root = f"distractor-root:{case_id}"
                query_time = (
                    datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=sequence)
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
                candidate_count = _candidate_count(case_type)
                triage_labels = _triage_labels(case_type, candidate_count)
                signals = _signals(case_type, language, sequence)
                fixture_hits = tuple(
                    (mode, (expected_root,) if signals[mode] else ())
                    for mode in MODE_ORDER
                )
                source_ids = (
                    f"fixture-source:{family['family_id'].lower()}",
                )
                case = QualificationCase(
                    case_id=case_id,
                    sequence=sequence,
                    family_id=family["family_id"],
                    case_type=case_type,
                    language=language,
                    query_valid_time=query_time,
                    expected_root=expected_root,
                    prohibited_root=prohibited_root,
                    slice_labels=tuple(sorted(slices)),
                    triage_labels=triage_labels,
                    expected_candidate_count=candidate_count,
                    fixture_hits=fixture_hits,
                    source_inventory_ids=source_ids,
                    label_digest="sha256:" + "0" * 64,
                    fixture_digest="sha256:" + "0" * 64,
                )
                cases.append(
                    replace(
                        case,
                        label_digest=digest(_case_label_value(case)),
                        fixture_digest=digest(_case_fixture_value(case)),
                    )
                )
    source_inventory = sorted(
        {
            source_id
            for case in cases
            for source_id in case.source_inventory_ids
        }
    )
    corpus = QualificationCorpus(
        corpus_id=value["corpus_id"],
        generator_version=value["generator_version"],
        cases=tuple(cases),
        query_set_digest=digest(
            [
                {
                    "case_id": case.case_id,
                    "query_valid_time": case.query_valid_time,
                }
                for case in cases
            ]
        ),
        label_policy_digest=digest(policy),
        source_inventory_digest=digest(source_inventory),
        dataset_manifest_digest=digest(
            [
                {
                    "case_id": case.case_id,
                    "family_id": case.family_id,
                    "case_type": case.case_type,
                    "language": case.language,
                    "label_digest": case.label_digest,
                    "fixture_digest": case.fixture_digest,
                }
                for case in cases
            ]
        ),
        corpus_spec_digest=CORPUS_SPEC_DIGEST,
    )
    validate_qualification_corpus_content_identities(corpus)
    return corpus
