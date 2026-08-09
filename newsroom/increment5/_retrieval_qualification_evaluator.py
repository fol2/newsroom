"""Decision-bearing Increment 5E1 qualification evaluator."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
import uuid

from ._retrieval_qualification_common import (
    QualificationDecision,
    QualificationOutcome,
    QualificationSystem,
    RetrievalQualificationError,
    digest,
    parse_utc,
    thaw,
)
from ._retrieval_qualification_contracts import (
    QualificationCorpus,
    QualificationEpoch,
    QualificationTarget,
)
from ._retrieval_qualification_evidence import (
    QualificationObservation,
    QualificationReport,
)
from ._retrieval_qualification_gates import (
    _branch_contributions,
    _family_metrics,
    _triage_metrics,
)
from ._retrieval_qualification_measurement import (
    _exposure_metrics,
    _system_metrics,
)
from .evaluation_plan import INCREMENT_5_EVALUATION_PLAN
from ._retrieval_qualification_run import build_qualification_epoch


_CROSS_SYSTEM_SAFETY_OR_RIGHTS_METRICS = (
    "rights_purge_residual_count",
    "scope_escape_count",
    "write_attempt_success_count",
)


class RetrievalQualificationEvaluator:
    """Evaluate one exact Epoch without creating authority or public effects."""

    def evaluate(
        self,
        *,
        run_id: str,
        target: QualificationTarget,
        corpus: QualificationCorpus,
        epoch: QualificationEpoch,
        code_tree_sha: str,
        observations: Sequence[QualificationObservation],
        started_at: str,
        completed_at: str,
    ) -> QualificationReport:
        try:
            if str(uuid.UUID(run_id)) != run_id:
                raise ValueError
        except ValueError as exc:
            raise RetrievalQualificationError("run_id must be a UUID") from exc
        expected_epoch = build_qualification_epoch(
            target=target,
            corpus=corpus,
            code_tree_sha=code_tree_sha,
            epoch_id=epoch.epoch_id,
        )
        if epoch != expected_epoch:
            raise RetrievalQualificationError("Epoch binding differs")
        parse_utc(started_at, field="started_at")
        parse_utc(completed_at, field="completed_at")

        expected = {
            (case.case_id, system)
            for case in corpus.cases
            for system in target.systems
        }
        observation_map: dict[
            tuple[str, QualificationSystem],
            QualificationObservation,
        ] = {}
        blockers: list[str] = []
        for observation in observations:
            key = (observation.case_id, observation.system)
            if key in observation_map:
                blockers.append(
                    "DUPLICATE_OBSERVATION:"
                    f"{observation.case_id}:{observation.system.value}"
                )
            observation_map[key] = observation
        missing = expected - observation_map.keys()
        unexpected = observation_map.keys() - expected
        if missing:
            blockers.append(f"MISSING_OBSERVATIONS:{len(missing)}")
        if unexpected:
            blockers.append(f"UNEXPECTED_OBSERVATIONS:{len(unexpected)}")

        non_complete_counts = Counter(
            (observation.system, observation.outcome)
            for observation in observations
            if observation.outcome is not QualificationOutcome.COMPLETE
        )
        blockers.extend(
            "NON_COMPLETE_OBSERVATIONS:"
            f"{system.value}:{outcome.value}:{count}"
            for (system, outcome), count in sorted(
                non_complete_counts.items(),
                key=lambda item: (item[0][0].value, item[0][1].value),
            )
        )

        plan = thaw(INCREMENT_5_EVALUATION_PLAN)
        exposure, exposure_blockers = _exposure_metrics(corpus, plan)
        blockers.extend(exposure_blockers)
        coverage_complete = (
            not missing
            and not unexpected
            and not any(
                blocker.startswith("DUPLICATE_OBSERVATION:")
                for blocker in blockers
            )
        )
        systems: list[dict[str, object]] = []
        families: list[dict[str, object]] = []
        slices: list[dict[str, object]] = []
        triage: list[dict[str, object]] = []
        contributions: list[dict[str, object]] = []
        if coverage_complete:
            systems = [
                _system_metrics(system, corpus.cases, observation_map)
                for system in target.systems
            ]
            hybrid = next(
                item for item in systems if item["system"] == "HYBRID"
            )
            thresholds = plan["contract_evaluation_summary"]["thresholds"]
            threshold_checks = {
                "aggregate_recall_at_12_min_ppm": (
                    hybrid["recall_at_12_ppm"]
                    >= thresholds["aggregate_recall_at_12_min_ppm"]
                ),
                "aggregate_mrr_at_12_min_ppm": (
                    hybrid["mrr_at_12_ppm"]
                    >= thresholds["aggregate_mrr_at_12_min_ppm"]
                ),
                "exact_identifier_precision_at_1_ppm": (
                    hybrid["exact_identifier_precision_at_1_ppm"]
                    == thresholds["exact_identifier_precision_at_1_ppm"]
                ),
                "provenance_completeness_ppm": (
                    hybrid["provenance_completeness_ppm"]
                    == thresholds["provenance_completeness_ppm"]
                ),
                "trust_label_completeness_ppm": (
                    hybrid["trust_label_completeness_ppm"]
                    == thresholds["trust_label_completeness_ppm"]
                ),
                "p95_latency_ms_max": (
                    hybrid["p95_latency_ms"]
                    <= thresholds["p95_latency_ms_max"]
                ),
                "false_no_match_count": hybrid["false_no_match_count"] == 0,
                "temporal_correctness_error_count": (
                    hybrid["temporal_correctness_error_count"] == 0
                ),
                "rebuild_reproducibility_mismatch_count": (
                    hybrid["rebuild_reproducibility_mismatch_count"] == 0
                ),
            }
            blockers.extend(
                f"TARGET_THRESHOLD:{name}"
                for name, passed in threshold_checks.items()
                if not passed
            )
            blockers.extend(
                "EXECUTED_SYSTEM_SAFETY_OR_RIGHTS:"
                f"{system['system']}:{metric}"
                for system in systems
                for metric in _CROSS_SYSTEM_SAFETY_OR_RIGHTS_METRICS
                if system[metric] != 0
            )
            families, slices, family_blockers = _family_metrics(
                corpus,
                observation_map,
                plan,
            )
            blockers.extend(family_blockers)
            triage, triage_blockers = _triage_metrics(
                corpus,
                observation_map,
                plan,
            )
            blockers.extend(triage_blockers)
            contributions = _branch_contributions(corpus, observation_map)

        blockers = sorted(set(blockers))
        under_exposed = any(
            blocker.startswith(
                ("EXPOSURE:", "FAMILY_EXPOSURE:", "SLICE_EXPOSURE:", "TRIAGE_EXPOSURE:")
            )
            for blocker in blockers
        )
        if not coverage_complete or under_exposed or non_complete_counts:
            decision = QualificationDecision.NOT_EVALUATED
            reason = "EVIDENCE_NOT_QUALIFIABLE"
        elif blockers:
            decision = QualificationDecision.FAIL
            reason = "QUALIFICATION_GATE_FAILED"
        else:
            decision = QualificationDecision.PASS
            reason = "PASS"
        metrics = {
            "exposure": exposure,
            "systems": systems,
            "mandatory_families": families,
            "required_slices": slices,
            "triage_error_classes": triage,
            "branch_contributions": contributions,
        }
        evidence_digest = digest(
            {
                "metrics": metrics,
                "blockers": blockers,
                "observation_count": len(observations),
                "expected_observation_count": len(expected),
            }
        )
        report_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                "|".join(
                    (
                        run_id,
                        epoch.epoch_digest,
                        decision.value,
                        reason,
                        evidence_digest,
                    )
                ),
            )
        )
        return QualificationReport(
            report_id=report_id,
            run_id=run_id,
            epoch_digest=epoch.epoch_digest,
            code_tree_sha=epoch.code_tree_sha,
            target_manifest_digest=target.manifest_digest,
            corpus_spec_digest=corpus.corpus_spec_digest,
            dataset_manifest_digest=corpus.dataset_manifest_digest,
            started_at=started_at,
            completed_at=completed_at,
            decision=decision,
            reason=reason,
            metrics=metrics,
            blockers=tuple(blockers),
            observation_count=len(observations),
            expected_observation_count=len(expected),
        )
