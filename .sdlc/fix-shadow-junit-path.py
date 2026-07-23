from __future__ import annotations

from pathlib import Path

SOURCE = Path("scripts/sdlc/workflow_lane.py")
TEST = Path("newsroom/tests/test_sdlc_workflow_lane.py")

source = SOURCE.read_text(encoding="utf-8")
old_function = '''def _report_summary(
    *,
    repo_root: Path,
    report: Path,
    optional_test_ids: Sequence[str],
) -> JUnitSummary | None:
    if not report.is_file():
        return None
    return summarize_junit(
        repo_root,
        (report.relative_to(repo_root).as_posix(),),
        optional_test_ids=optional_test_ids,
    )
'''
new_function = '''def _report_summary(
    *,
    repo_root: Path,
    artifact_root: Path,
    report: Path,
    optional_test_ids: Sequence[str],
) -> JUnitSummary | None:
    if not report.is_file():
        return None
    try:
        repository_relative = report.relative_to(repo_root).as_posix()
        artifact_relative = report.relative_to(artifact_root).as_posix()
    except ValueError as exc:
        raise WorkflowLaneError("report_path") from exc
    summary = summarize_junit(
        repo_root,
        (repository_relative,),
        optional_test_ids=optional_test_ids,
    )
    if len(summary.report_digests) != 1 or summary.report_digests[0][0] != repository_relative:
        raise WorkflowLaneError("report_summary")
    return JUnitSummary(
        outcome=summary.outcome,
        report_digests=((artifact_relative, summary.report_digests[0][1]),),
        test_ids_digest=summary.test_ids_digest,
        test_count=summary.test_count,
        failure_count=summary.failure_count,
        error_count=summary.error_count,
        skip_count=summary.skip_count,
        required_skip_count=summary.required_skip_count,
        duration_ms=summary.duration_ms,
        first_failure_fingerprint=summary.first_failure_fingerprint,
    )
'''
if source.count(old_function) != 1:
    raise SystemExit("report summary function mismatch")
source = source.replace(old_function, new_function)
old_call = '''        summary = _report_summary(
            repo_root=root, report=report, optional_test_ids=optional
        )
'''
new_call = '''        summary = _report_summary(
            repo_root=root,
            artifact_root=output,
            report=report,
            optional_test_ids=optional,
        )
'''
if source.count(old_call) != 1:
    raise SystemExit("report summary call mismatch")
source = source.replace(old_call, new_call)
SOURCE.write_text(source, encoding="utf-8")

tests = TEST.read_text(encoding="utf-8")
if "test_report_summary_records_artifact_relative_raw_report_path" in tests:
    raise SystemExit("report path tests already present")
tests += '''


def test_report_summary_records_artifact_relative_raw_report_path(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / ".sdlc-run" / "core"
    report = artifact / "gates/core-deterministic/tests/reports/pytest.xml"
    report.parent.mkdir(parents=True)
    report.write_text(
        '<testsuite><testcase classname="example" name="test_ok" time="0.001"/></testsuite>',
        encoding="utf-8",
    )

    original = lane_module.summarize_junit(
        tmp_path,
        (report.relative_to(tmp_path).as_posix(),),
    )
    summary = lane_module._report_summary(
        repo_root=tmp_path,
        artifact_root=artifact,
        report=report,
        optional_test_ids=(),
    )

    assert summary is not None
    assert summary.report_digests == (
        (
            "gates/core-deterministic/tests/reports/pytest.xml",
            original.report_digests[0][1],
        ),
    )
    assert summary.test_ids_digest == original.test_ids_digest
    assert summary.test_count == original.test_count == 1
    assert summary.first_failure_fingerprint == original.first_failure_fingerprint


def test_report_summary_rejects_report_outside_artifact_root(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    report = tmp_path / "outside.xml"
    report.write_text(
        '<testsuite><testcase classname="example" name="test_ok"/></testsuite>',
        encoding="utf-8",
    )
    with pytest.raises(WorkflowLaneError, match="report_path"):
        lane_module._report_summary(
            repo_root=tmp_path,
            artifact_root=artifact,
            report=report,
            optional_test_ids=(),
        )
'''
TEST.write_text(tests, encoding="utf-8")
