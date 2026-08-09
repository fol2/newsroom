"""Frozen Epoch construction and deterministic fixture observations."""

from __future__ import annotations

from fractions import Fraction

from ._retrieval_qualification_common import (
    MODE_ORDER,
    RESULT_LIMIT,
    RRF_K,
    QualificationMode,
    QualificationOutcome,
    QualificationSystem,
    digest,
    thaw,
)
from ._retrieval_qualification_contracts import (
    QualificationCase,
    QualificationCorpus,
    QualificationEpoch,
    QualificationTarget,
)
from ._retrieval_qualification_corpus import (
    validate_qualification_corpus_content_identities,
)
from ._retrieval_qualification_target import (
    validate_qualification_target_identity,
)
from ._retrieval_qualification_evidence import QualificationObservation
from .evaluation_plan import INCREMENT_5_EVALUATION_PLAN


def build_qualification_epoch(
    *,
    target: QualificationTarget,
    corpus: QualificationCorpus,
    code_tree_sha: str,
    epoch_id: str = "increment5-retrieval-qualification-epoch-v1",
) -> QualificationEpoch:
    validate_qualification_target_identity(target)
    validate_qualification_corpus_content_identities(corpus)
    return _derive_qualification_epoch(
        target=target,
        corpus=corpus,
        code_tree_sha=code_tree_sha,
        epoch_id=epoch_id,
    )


def _derive_qualification_epoch(
    *,
    target: QualificationTarget,
    corpus: QualificationCorpus,
    code_tree_sha: str,
    epoch_id: str,
) -> QualificationEpoch:
    plan = thaw(INCREMENT_5_EVALUATION_PLAN)
    return QualificationEpoch(
        epoch_id=epoch_id,
        contract_digest=target.contract_digest,
        evaluation_plan_digest=target.evaluation_plan_digest,
        target_manifest_digest=target.manifest_digest,
        component_digests=target.component_digests,
        source_inventory_digest=corpus.source_inventory_digest,
        source_provider_versions_digest=digest(
            {
                "graph_engine_family": target.graph_engine_family,
                "graph_engine_image": target.graph_engine_image,
                "proposal_framework_family": target.proposal_framework_family,
                "proposal_execution_status": target.proposal_execution_status,
                "vector_scope": target.vector_scope,
            }
        ),
        adapter_parser_versions_digest=digest(
            {
                "graph_driver_version": target.graph_driver_version,
                "corpus_generator_version": corpus.generator_version,
                "runner_version": "increment5-fixture-qualification-runner-v1",
            }
        ),
        query_set_digest=corpus.query_set_digest,
        threshold_set_digest=digest(
            {
                "contract_thresholds": plan["contract_evaluation_summary"][
                    "thresholds"
                ],
                "mandatory_query_families": plan["mandatory_query_families"],
                "zero_tolerance_gates": plan["zero_tolerance_gates"],
            }
        ),
        policy_set_digest=digest(
            {
                "decision_scope": plan["decision_scope"],
                "epoch_protocol": plan["epoch_protocol"],
                "exposure_minima": plan["exposure_minima"],
                "triage_error_protocol": plan["triage_error_protocol"],
            }
        ),
        dataset_manifest_digest=corpus.dataset_manifest_digest,
        label_adjudication_policy_digest=corpus.label_policy_digest,
        code_tree_sha=code_tree_sha,
        generation_id=target.generation_id,
    )


def _hybrid(
    case: QualificationCase,
) -> tuple[tuple[str, ...], tuple[QualificationMode, ...]]:
    ranks: dict[str, dict[QualificationMode, int]] = {}
    for mode, roots in case.fixture_hits:
        for rank, root in enumerate(roots, 1):
            ranks.setdefault(root, {})[mode] = rank

    def order(root: str) -> tuple[object, ...]:
        modes = ranks[root]
        score = sum(
            (Fraction(1, RRF_K + rank) for rank in modes.values()),
            Fraction(),
        )
        return (
            0 if QualificationMode.EXACT in modes else 1,
            -score,
            min(modes.values()),
            root,
        )

    roots = tuple(sorted(ranks, key=order))[:RESULT_LIMIT]
    modes = tuple(
        mode
        for mode in MODE_ORDER
        if any(mode in ranks[root] for root in roots)
    )
    return roots, modes


def run_fixture_qualification(
    *,
    target: QualificationTarget,
    corpus: QualificationCorpus,
) -> tuple[QualificationObservation, ...]:
    validate_qualification_target_identity(target)
    validate_qualification_corpus_content_identities(corpus)
    system_mode = {
        QualificationSystem.EXACT_ONLY: QualificationMode.EXACT,
        QualificationSystem.FULL_TEXT_ONLY: QualificationMode.FULL_TEXT,
        QualificationSystem.VECTOR_ONLY: QualificationMode.VECTOR,
        QualificationSystem.ADMITTED_GRAPH_ONLY: QualificationMode.ADMITTED_GRAPH,
    }
    base_latency = {
        QualificationMode.EXACT: 5,
        QualificationMode.FULL_TEXT: 15,
        QualificationMode.VECTOR: 22,
        QualificationMode.ADMITTED_GRAPH: 28,
    }
    observations: list[QualificationObservation] = []
    for case in corpus.cases:
        for system in target.systems:
            if system is QualificationSystem.HYBRID:
                roots, modes = _hybrid(case)
                latency_ms = 50 + case.sequence % 47
            else:
                mode = system_mode[system]
                roots = case.fixture_mapping[mode]
                modes = (mode,) if roots else ()
                latency_ms = base_latency[mode] + case.sequence % 23
            observations.append(
                QualificationObservation(
                    case_id=case.case_id,
                    system=system,
                    outcome=QualificationOutcome.COMPLETE,
                    ranked_roots=roots,
                    contributing_modes=modes,
                    latency_ms=latency_ms,
                    provenance_complete=True,
                    trust_labels_complete=True,
                    temporal_correct=True,
                    candidate_disposition_count=case.expected_candidate_count,
                )
            )
    return tuple(observations)
