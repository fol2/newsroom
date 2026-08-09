from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3
import uuid

import pytest

from newsroom.increment5.retrieval_qualification import (
    QUALIFICATION_CORPUS,
    QUALIFICATION_TARGET,
    QualificationDecision,
    QualificationReportJournal,
    QualificationSystem,
    RetrievalQualificationError,
    RetrievalQualificationEvaluator,
    build_qualification_epoch,
    run_fixture_qualification,
)

START = "2026-08-08T20:00:00Z"
END = "2026-08-08T20:01:00Z"
TREE = "a" * 40


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


def test_report_journal_retains_pass_fail_and_not_evaluated(tmp_path: Path) -> None:
    journal = QualificationReportJournal(tmp_path / "history.sqlite3")
    observations = run_fixture_qualification(
        target=QUALIFICATION_TARGET,
        corpus=QUALIFICATION_CORPUS,
    )
    reports = []

    pass_epoch, pass_report = _evaluate(observations)
    reports.append((pass_epoch, pass_report))

    failed_observations, _ = _replace_first_hybrid(
        observations,
        rights_purge_residual_count=1,
    )
    fail_epoch, fail_report = _evaluate(failed_observations)
    reports.append((fail_epoch, fail_report))

    not_evaluated_epoch, not_evaluated_report = _evaluate(observations[:-1])
    reports.append((not_evaluated_epoch, not_evaluated_report))

    for epoch, report in reports:
        journal.execute(
            run_id=report.run_id,
            epoch_digest=epoch.epoch_digest,
            producer=lambda report=report: report,
        )
    assert {report.decision for report in journal.history()} == {
        QualificationDecision.PASS,
        QualificationDecision.FAIL,
        QualificationDecision.NOT_EVALUATED,
    }

def test_report_journal_is_first_writer_wins_and_detects_corruption(tmp_path: Path) -> None:
    epoch, report = _evaluate()
    journal = QualificationReportJournal(tmp_path / "reports.sqlite3")
    assert journal.execute(
        run_id=report.run_id,
        epoch_digest=epoch.epoch_digest,
        producer=lambda: report,
    ) == report
    assert journal.execute(
        run_id=report.run_id,
        epoch_digest=epoch.epoch_digest,
        producer=lambda: report,
    ) == report
    assert journal.history() == (report,)

    other = build_qualification_epoch(
        target=QUALIFICATION_TARGET,
        corpus=QUALIFICATION_CORPUS,
        code_tree_sha="b" * 40,
    )
    with pytest.raises(RetrievalQualificationError, match="another Epoch"):
        journal.execute(
            run_id=report.run_id,
            epoch_digest=other.epoch_digest,
            producer=lambda: report,
        )

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
        rights_purge_residual_count=1,
    )
    replay_mismatch = RetrievalQualificationEvaluator().evaluate(
        run_id=report.run_id,
        target=QUALIFICATION_TARGET,
        corpus=QUALIFICATION_CORPUS,
        epoch=epoch,
        code_tree_sha=TREE,
        observations=tuple(observations),
        started_at=START,
        completed_at=END,
    )
    with pytest.raises(RetrievalQualificationError, match="deterministic replay"):
        journal.execute(
            run_id=report.run_id,
            epoch_digest=epoch.epoch_digest,
            producer=lambda: replay_mismatch,
        )

    with sqlite3.connect(tmp_path / "reports.sqlite3") as connection:
        connection.execute(
            "UPDATE increment5e1_qualification_reports SET report_bytes = ?",
            (b"{}",),
        )
    with pytest.raises(RetrievalQualificationError, match="corrupt"):
        journal.history()
