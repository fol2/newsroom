"""Emit and retain one deterministic Increment 5E1 fixture qualification report."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import uuid

from newsroom.increment5.retrieval_qualification import (
    QUALIFICATION_CORPUS,
    QUALIFICATION_TARGET,
    QualificationDecision,
    QualificationReportJournal,
    RetrievalQualificationEvaluator,
    build_qualification_epoch,
    run_fixture_qualification,
)


def _current_tree() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD^{tree}"],
        text=True,
    ).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--code-tree-sha", default=None)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--started-at",
        default="2026-08-08T20:00:00Z",
    )
    parser.add_argument(
        "--completed-at",
        default="2026-08-08T20:01:00Z",
    )
    arguments = parser.parse_args(argv)

    epoch = build_qualification_epoch(
        target=QUALIFICATION_TARGET,
        corpus=QUALIFICATION_CORPUS,
        code_tree_sha=arguments.code_tree_sha or _current_tree(),
    )
    run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, epoch.epoch_digest))
    observations = run_fixture_qualification(
        target=QUALIFICATION_TARGET,
        corpus=QUALIFICATION_CORPUS,
    )
    evaluator = RetrievalQualificationEvaluator()
    journal = QualificationReportJournal(arguments.journal)
    report = journal.execute(
        run_id=run_id,
        epoch_digest=epoch.epoch_digest,
        producer=lambda: evaluator.evaluate(
            run_id=run_id,
            target=QUALIFICATION_TARGET,
            corpus=QUALIFICATION_CORPUS,
            epoch=epoch,
            observations=observations,
            started_at=arguments.started_at,
            completed_at=arguments.completed_at,
        ),
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_bytes(report.canonical_bytes)
    print(
        report.decision.value,
        report.reason,
        report.report_digest,
    )
    return 0 if report.decision is QualificationDecision.PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
