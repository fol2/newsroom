from __future__ import annotations

from dataclasses import replace
import json
import uuid

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment5.retrieval_qualification import (
    CORPUS_SPEC_DIGEST,
    CORPUS_SPEC_PATH,
    MODE_ORDER,
    QUALIFICATION_CORPUS,
    QUALIFICATION_TARGET,
    CORPUS_SPEC,
    TARGET_SPEC,
    TARGET_SPEC_DIGEST,
    TARGET_SPEC_PATH,
    QualificationDecision,
    QualificationObservation,
    QualificationOutcome,
    QualificationReport,
    QualificationSystem,
    RetrievalQualificationError,
    RetrievalQualificationEvaluator,
    build_qualification_epoch,
    load_qualification_corpus,
    load_qualification_target,
    rederive_qualification_corpus,
    run_fixture_qualification,
)

TREE = "a" * 40
START = "2026-08-08T20:00:00Z"
END = "2026-08-08T20:01:00Z"


def _evaluate(observations=None, *, tree: str = TREE):
    epoch = build_qualification_epoch(
        target=QUALIFICATION_TARGET,
        corpus=QUALIFICATION_CORPUS,
        code_tree_sha=tree,
    )
    report = RetrievalQualificationEvaluator().evaluate(
        run_id=str(uuid.uuid4()),
        target=QUALIFICATION_TARGET,
        corpus=QUALIFICATION_CORPUS,
        epoch=epoch,
        code_tree_sha=tree,
        observations=(
            run_fixture_qualification(
                target=QUALIFICATION_TARGET,
                corpus=QUALIFICATION_CORPUS,
            )
            if observations is None
            else observations
        ),
        started_at=START,
        completed_at=END,
    )
    return epoch, report


def _replace_first_hybrid(observations, **changes):
    values = list(observations)
    index = next(
        index
        for index, item in enumerate(values)
        if item.system is QualificationSystem.HYBRID
    )
    values[index] = replace(values[index], **changes)
    return tuple(values), QUALIFICATION_CORPUS.cases[0]


def _replace_first_system(observations, system, **changes):
    values = list(observations)
    index = next(
        index
        for index, item in enumerate(values)
        if item.system is system
    )
    values[index] = replace(values[index], **changes)
    return tuple(values)



def test_machine_specs_are_exact_canonical_content_addressed_bytes() -> None:
    for path, expected in (
        (TARGET_SPEC_PATH, TARGET_SPEC_DIGEST),
        (CORPUS_SPEC_PATH, CORPUS_SPEC_DIGEST),
    ):
        raw = path.read_bytes()
        assert digest_bytes(raw) == expected
        assert canonical_json_bytes(json.loads(raw.decode("utf-8"))) == raw

def test_frozen_target_and_corpus_cover_exact_retrieval_boundary() -> None:
    assert QUALIFICATION_TARGET.qualification_target is QualificationSystem.HYBRID
    assert QUALIFICATION_TARGET.systems == tuple(QualificationSystem)
    assert QUALIFICATION_TARGET.required_modes == MODE_ORDER
    assert QUALIFICATION_TARGET.graph_engine_image == "neo4j:2026.06.0-community-trixie"
    assert QUALIFICATION_TARGET.graph_driver_version == "6.2.0"
    assert QUALIFICATION_TARGET.graph_mandatory is True
    assert QUALIFICATION_TARGET.fake_or_noop_allowed is False
    assert QUALIFICATION_TARGET.embedding_quality_qualified is False
    assert QUALIFICATION_TARGET.external_call_limit == 0
    assert QUALIFICATION_TARGET.provider_spend_micros == 0
    assert len(QUALIFICATION_CORPUS.cases) == 100
    assert {case.language for case in QUALIFICATION_CORPUS.cases} == {
        "EN_GB",
        "MIXED_EN_GB_ZH_HANT_HK",
        "ZH_HANT_HK",
    }
    assert all(
        tuple(mode for mode, _ in case.fixture_hits) == MODE_ORDER
        for case in QUALIFICATION_CORPUS.cases
    )
    assert all(
        case.label_digest != case.fixture_digest
        for case in QUALIFICATION_CORPUS.cases
    )


def test_complete_fixture_qualification_is_pass_and_ablations_are_separate() -> None:
    epoch, report = _evaluate()
    assert report.decision is QualificationDecision.PASS
    assert report.reason == "PASS"
    assert report.blockers == ()
    assert report.epoch_digest == epoch.epoch_digest
    assert report.observation_count == 500
    systems = {item["system"]: item for item in report.metrics["systems"]}
    assert systems["HYBRID"]["decision_bearing"] is True
    assert systems["HYBRID"]["recall_at_12_ppm"] == 1_000_000
    assert systems["HYBRID"]["mrr_at_12_ppm"] == 1_000_000
    assert systems["HYBRID"]["provenance_completeness_ppm"] == 1_000_000
    assert all(
        item["decision_bearing"] is False
        for name, item in systems.items()
        if name != "HYBRID"
    )
    assert systems["VECTOR_ONLY"]["vector_fixture_replay_only"] is True
    assert report.comparative_results_decision_bearing is False
    assert report.embedding_quality_qualified is False


def test_missing_duplicate_and_unexpected_observations_are_not_evaluated() -> None:
    observations = run_fixture_qualification(
        target=QUALIFICATION_TARGET,
        corpus=QUALIFICATION_CORPUS,
    )
    _, missing = _evaluate(observations[:-1])
    assert missing.decision is QualificationDecision.NOT_EVALUATED
    assert "MISSING_OBSERVATIONS:1" in missing.blockers

    _, duplicate = _evaluate((*observations, observations[0]))
    assert duplicate.decision is QualificationDecision.NOT_EVALUATED
    assert any(
        item.startswith("DUPLICATE_OBSERVATION:")
        for item in duplicate.blockers
    )

    extra = replace(observations[0], case_id="i5q-unexpected")
    _, unexpected = _evaluate((*observations, extra))
    assert unexpected.decision is QualificationDecision.NOT_EVALUATED
    assert "UNEXPECTED_OBSERVATIONS:1" in unexpected.blockers


def test_rights_temporal_scope_write_and_rebuild_violations_fail_closed() -> None:
    observations = run_fixture_qualification(
        target=QUALIFICATION_TARGET,
        corpus=QUALIFICATION_CORPUS,
    )
    changes = (
        {"rights_purge_residual_count": 1},
        {"temporal_correct": False},
        {"scope_escape_count": 1},
        {"write_attempt_success_count": 1},
        {"rebuild_reproducibility_mismatch_count": 1},
    )
    for change in changes:
        modified, _ = _replace_first_hybrid(observations, **change)
        _, report = _evaluate(modified)
        assert report.decision is QualificationDecision.FAIL
        assert report.blockers


@pytest.mark.parametrize(
    ("system", "change"),
    [
        (
            QualificationSystem.ADMITTED_GRAPH_ONLY,
            {"rights_purge_residual_count": 1},
        ),
        (QualificationSystem.EXACT_ONLY, {"scope_escape_count": 1}),
        (
            QualificationSystem.FULL_TEXT_ONLY,
            {"write_attempt_success_count": 1},
        ),
        (
            QualificationSystem.VECTOR_ONLY,
            {"rights_purge_residual_count": 1},
        ),
    ],
)
def test_safety_and_rights_violations_in_any_executed_system_block(
    system,
    change,
) -> None:
    observations = run_fixture_qualification(
        target=QUALIFICATION_TARGET,
        corpus=QUALIFICATION_CORPUS,
    )
    modified = _replace_first_system(observations, system, **change)
    _, report = _evaluate(modified)
    assert report.decision is QualificationDecision.FAIL
    assert any(system.value in blocker for blocker in report.blockers)


def test_false_no_match_false_merge_and_candidate_disposition_fail() -> None:
    observations = run_fixture_qualification(
        target=QUALIFICATION_TARGET,
        corpus=QUALIFICATION_CORPUS,
    )
    modified, case = _replace_first_hybrid(
        observations,
        ranked_roots=(),
        contributing_modes=(),
    )
    _, no_match = _evaluate(modified)
    assert no_match.decision is QualificationDecision.FAIL
    assert any("false_no_match" in item for item in no_match.blockers)

    related_case_index = next(
        index
        for index, case in enumerate(QUALIFICATION_CORPUS.cases)
        if case.case_type == "RELATED_BUT_DISTINCT_EVENT"
    )
    related_observation_index = related_case_index * len(tuple(QualificationSystem)) + 3
    related_case = QUALIFICATION_CORPUS.cases[related_case_index]
    values = list(observations)
    values[related_observation_index] = replace(
        values[related_observation_index],
        ranked_roots=(related_case.prohibited_root,),
    )
    _, false_merge = _evaluate(tuple(values))
    assert false_merge.decision is QualificationDecision.FAIL
    assert any("FALSE_MERGE" in item for item in false_merge.blockers)

    same_state_index = next(
        index
        for index, item in enumerate(observations)
        if item.system is QualificationSystem.HYBRID
        and QUALIFICATION_CORPUS.cases[index // 5].case_type == "SAME_EVENT_STATE"
    )
    values = list(observations)
    values[same_state_index] = replace(
        values[same_state_index],
        candidate_disposition_count=1,
    )
    _, unnecessary = _evaluate(tuple(values))
    assert unnecessary.decision is QualificationDecision.PASS
    triage = {
        item["class_id"]: item
        for item in unnecessary.metrics["triage_error_classes"]
    }
    assert triage["UNNECESSARY_CANDIDATE_CREATION"]["error_count"] == 1
    assert triage["UNNECESSARY_CANDIDATE_CREATION"]["automatic_blocker"] is False



def test_complete_coverage_with_non_complete_outcome_is_not_evaluated() -> None:
    observations = list(
        run_fixture_qualification(
            target=QUALIFICATION_TARGET,
            corpus=QUALIFICATION_CORPUS,
        )
    )
    hybrid_index = next(
        index
        for index, item in enumerate(observations)
        if item.system is QualificationSystem.HYBRID
    )
    observations[hybrid_index] = replace(
        observations[hybrid_index],
        outcome=QualificationOutcome.UNAVAILABLE,
        ranked_roots=(),
        contributing_modes=(),
    )
    _, report = _evaluate(tuple(observations))
    assert report.decision is QualificationDecision.NOT_EVALUATED
    assert report.reason == "EVIDENCE_NOT_QUALIFIABLE"
    assert any(
        item.startswith("NON_COMPLETE_OBSERVATIONS:HYBRID:UNAVAILABLE:")
        for item in report.blockers
    )

def test_non_complete_observation_cannot_expose_results_or_effects() -> None:
    case = QUALIFICATION_CORPUS.cases[0]
    with pytest.raises(RetrievalQualificationError, match="non-complete"):
        QualificationObservation(
            case_id=case.case_id,
            system=QualificationSystem.HYBRID,
            outcome=QualificationOutcome.UNAVAILABLE,
            ranked_roots=(case.expected_root,),
            contributing_modes=MODE_ORDER,
            latency_ms=1,
            provenance_complete=True,
            trust_labels_complete=True,
            temporal_correct=True,
        )
    with pytest.raises(RetrievalQualificationError, match="forbidden effect"):
        replace(
            run_fixture_qualification(
                target=QUALIFICATION_TARGET,
                corpus=QUALIFICATION_CORPUS,
            )[0],
            external_call_count=1,
        )



def test_slice_and_triage_denominators_are_truthful_and_plan_derived() -> None:
    _, report = _evaluate()
    exposure = {
        (item["dimension"], item["name"]): item
        for item in report.metrics["exposure"]
    }
    assert exposure[("SLICE", "EN_GB")]["count"] == 34
    assert exposure[("SLICE", "MIXED_EN_GB_ZH_HANT_HK")]["count"] == 33
    assert exposure[("SLICE", "ZH_HANT_HK")]["count"] == 33
    assert exposure[("SLICE", "DISTRACTOR_FALSE_MERGE")]["count"] == 20
    assert exposure[("SLICE", "TEMPORAL_CUTOFF")]["count"] == 20

    triage = {
        item["class_id"]: item
        for item in report.metrics["triage_error_classes"]
    }
    assert triage["FALSE_MERGE"]["opportunity_count"] == 20
    assert triage["FRAGMENTATION"]["opportunity_count"] == 20
    assert triage["SNOWBALL_ABSORPTION"]["opportunity_count"] == 30
    assert triage["FALSE_OR_MISSED_DEVELOPMENT"]["opportunity_count"] == 40
    assert triage["DUPLICATE_CANDIDATE_CREATION"]["opportunity_count"] == 70
    assert triage["UNNECESSARY_CANDIDATE_CREATION"]["opportunity_count"] == 30

    families = {
        item["family_id"]: item
        for item in report.metrics["mandatory_families"]
    }
    event = families["EVENT_AND_DEVELOPMENT_PRECISION"]
    assert event["distractor_false_merge_opportunity_count"] == 20
    assert event["distractor_false_merge_error_count"] == 0
    assert event["distractor_false_merge_precision_ppm"] == 1_000_000
    assert all(item["passed"] is True for item in families.values())



def test_family_required_slice_underexposure_is_not_evaluated() -> None:
    observations = run_fixture_qualification(
        target=QUALIFICATION_TARGET,
        corpus=QUALIFICATION_CORPUS,
    )
    cases = list(QUALIFICATION_CORPUS.cases)
    index = next(
        index
        for index, case in enumerate(cases)
        if case.family_id == "EVENT_AND_DEVELOPMENT_PRECISION"
        and case.language == "EN_GB"
    )
    cases[index] = replace(
        cases[index],
        slice_labels=tuple(
            label for label in cases[index].slice_labels if label != "EN_GB"
        ),
    )
    corpus = rederive_qualification_corpus(
        replace(QUALIFICATION_CORPUS, cases=tuple(cases))
    )
    epoch = build_qualification_epoch(
        target=QUALIFICATION_TARGET,
        corpus=corpus,
        code_tree_sha=TREE,
    )
    report = RetrievalQualificationEvaluator().evaluate(
        run_id=str(uuid.uuid4()),
        target=QUALIFICATION_TARGET,
        corpus=corpus,
        epoch=epoch,
        code_tree_sha=TREE,
        observations=observations,
        started_at=START,
        completed_at=END,
    )
    assert report.decision is QualificationDecision.NOT_EVALUATED
    assert (
        "FAMILY_EXPOSURE:EVENT_AND_DEVELOPMENT_PRECISION:EN_GB"
        in report.blockers
    )
    assert "MANDATORY_FAMILY:EVENT_AND_DEVELOPMENT_PRECISION" not in report.blockers

def test_report_metrics_are_deeply_immutable() -> None:
    _, report = _evaluate()
    before = report.report_digest
    with pytest.raises(TypeError):
        report.metrics["systems"] = ()
    with pytest.raises(TypeError):
        report.metrics["systems"][0]["case_count"] = 0
    assert report.report_digest == before

def test_report_round_trip_and_identity_tamper_fail_closed() -> None:
    _, report = _evaluate()
    assert QualificationReport.from_canonical_bytes(report.canonical_bytes) == report
    value = json.loads(report.canonical_bytes)
    value["report_id"] = str(uuid.uuid4())
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(RetrievalQualificationError, match="identity differs"):
        QualificationReport.from_canonical_bytes(raw)


def test_epoch_identity_changes_with_code_tree_and_mismatch_is_rejected() -> None:
    first = build_qualification_epoch(
        target=QUALIFICATION_TARGET,
        corpus=QUALIFICATION_CORPUS,
        code_tree_sha="a" * 40,
    )
    second = build_qualification_epoch(
        target=QUALIFICATION_TARGET,
        corpus=QUALIFICATION_CORPUS,
        code_tree_sha="b" * 40,
    )
    assert first.epoch_digest != second.epoch_digest
    observations = run_fixture_qualification(
        target=QUALIFICATION_TARGET,
        corpus=QUALIFICATION_CORPUS,
    )
    with pytest.raises(
        RetrievalQualificationError,
        match="target identity|Epoch binding",
    ):
        RetrievalQualificationEvaluator().evaluate(
            run_id=str(uuid.uuid4()),
            target=replace(
                QUALIFICATION_TARGET,
                generation_id="different-generation",
            ),
            corpus=QUALIFICATION_CORPUS,
            epoch=first,
            code_tree_sha=TREE,
            observations=observations,
            started_at=START,
            completed_at=END,
        )


def test_caller_modified_corpus_cannot_reuse_stale_content_identities() -> None:
    cases = list(QUALIFICATION_CORPUS.cases)
    case = cases[0]
    changed_root = "authority-root:caller-modified"
    cases[0] = replace(
        case,
        expected_root=changed_root,
        fixture_hits=tuple(
            (mode, (changed_root,) if roots else ())
            for mode, roots in case.fixture_hits
        ),
    )
    changed = replace(QUALIFICATION_CORPUS, cases=tuple(cases))

    with pytest.raises(RetrievalQualificationError, match="content identities"):
        build_qualification_epoch(
            target=QUALIFICATION_TARGET,
            corpus=changed,
            code_tree_sha=TREE,
        )
    with pytest.raises(RetrievalQualificationError, match="content identities"):
        run_fixture_qualification(
            target=QUALIFICATION_TARGET,
            corpus=changed,
        )

    rederived = rederive_qualification_corpus(changed)
    assert rederived.dataset_manifest_digest != (
        QUALIFICATION_CORPUS.dataset_manifest_digest
    )
    assert rederived.cases[0].label_digest != case.label_digest
    assert rederived.cases[0].fixture_digest != case.fixture_digest
    changed_epoch = build_qualification_epoch(
        target=QUALIFICATION_TARGET,
        corpus=rederived,
        code_tree_sha=TREE,
    )
    assert changed_epoch.dataset_manifest_digest == (
        rederived.dataset_manifest_digest
    )


@pytest.mark.parametrize(
    "field",
    [
        "source_provider_versions_digest",
        "adapter_parser_versions_digest",
        "threshold_set_digest",
        "policy_set_digest",
    ],
)
def test_every_derived_epoch_identity_is_revalidated_before_evaluation(
    field: str,
) -> None:
    epoch = build_qualification_epoch(
        target=QUALIFICATION_TARGET,
        corpus=QUALIFICATION_CORPUS,
        code_tree_sha=TREE,
    )
    changed = replace(epoch, **{field: "sha256:" + "b" * 64})
    observations = run_fixture_qualification(
        target=QUALIFICATION_TARGET,
        corpus=QUALIFICATION_CORPUS,
    )
    with pytest.raises(RetrievalQualificationError, match="Epoch binding"):
        RetrievalQualificationEvaluator().evaluate(
            run_id=str(uuid.uuid4()),
            target=QUALIFICATION_TARGET,
            corpus=QUALIFICATION_CORPUS,
            epoch=changed,
            code_tree_sha=TREE,
            observations=observations,
            started_at=START,
            completed_at=END,
        )


def test_epoch_code_tree_and_exact_target_are_independently_revalidated() -> None:
    epoch = build_qualification_epoch(
        target=QUALIFICATION_TARGET,
        corpus=QUALIFICATION_CORPUS,
        code_tree_sha=TREE,
    )
    observations = run_fixture_qualification(
        target=QUALIFICATION_TARGET,
        corpus=QUALIFICATION_CORPUS,
    )
    with pytest.raises(RetrievalQualificationError, match="Epoch binding"):
        RetrievalQualificationEvaluator().evaluate(
            run_id=str(uuid.uuid4()),
            target=QUALIFICATION_TARGET,
            corpus=QUALIFICATION_CORPUS,
            epoch=replace(epoch, code_tree_sha="b" * 40),
            code_tree_sha=TREE,
            observations=observations,
            started_at=START,
            completed_at=END,
        )

    changed_target = replace(
        QUALIFICATION_TARGET,
        profile_id="CALLER_SELECTED_TARGET",
    )
    with pytest.raises(RetrievalQualificationError, match="target identity"):
        build_qualification_epoch(
            target=changed_target,
            corpus=QUALIFICATION_CORPUS,
            code_tree_sha=TREE,
        )


def test_reviewed_target_and_corpus_tamper_fail_closed() -> None:
    target = json.loads(TARGET_SPEC_PATH.read_text(encoding="utf-8"))
    target["external_call_limit"] = 1
    with pytest.raises(RetrievalQualificationError, match="reviewed v1"):
        load_qualification_target(target)

    corpus = json.loads(CORPUS_SPEC_PATH.read_text(encoding="utf-8"))
    corpus["expected_case_count"] = 99
    with pytest.raises(RetrievalQualificationError, match="reviewed v1"):
        load_qualification_corpus(corpus)
