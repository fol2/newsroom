from __future__ import annotations

import json
import os
from pathlib import Path
import stat

import pytest

from scripts.sdlc.junit_evidence import (
    JUnitEvidenceError,
    main as junit_main,
    summarize_junit,
)


def _write(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _suite(*cases: str, attributes: str = "") -> str:
    return f"<testsuite {attributes}>{''.join(cases)}</testsuite>"


def _case(
    name: str,
    *,
    classname: str = "tests.example",
    time: str = "0.001",
    terminal: str = "",
) -> str:
    return (
        f'<testcase classname="{classname}" name="{name}" time="{time}">'
        f"{terminal}</testcase>"
    )


def test_optional_skip_is_recorded_without_failing_the_gate(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "results.xml",
        _suite(
            _case("passes"),
            _case("optional", terminal='<skipped message="not selected"/>'),
            attributes='tests="999" failures="999" errors="999" skipped="999"',
        ),
    )

    summary = summarize_junit(
        tmp_path,
        ("results.xml",),
        optional_test_ids=("tests.example::optional",),
    )

    assert summary.outcome == "PASS"
    assert summary.test_count == 2
    assert summary.failure_count == 0
    assert summary.error_count == 0
    assert summary.skip_count == 1
    assert summary.required_skip_count == 0
    assert summary.duration_ms == 2
    assert summary.first_failure_fingerprint is None


def test_required_skip_fails_with_a_stable_fingerprint(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "results.xml",
        _suite(_case("required", terminal='<skipped message="unavailable"/>')),
    )

    first = summarize_junit(tmp_path, ("results.xml",))
    second = summarize_junit(tmp_path, ("results.xml",))

    assert first.outcome == "FAIL"
    assert first.required_skip_count == 1
    assert first.failure_count == first.error_count == 0
    assert first.first_failure_fingerprint == second.first_failure_fingerprint
    assert first.first_failure_fingerprint is not None
    assert first.first_failure_fingerprint.startswith("sha256:")


def test_failure_error_and_first_fingerprint_are_order_independent(
    tmp_path: Path,
) -> None:
    root_a = tmp_path / "one"
    root_b = tmp_path / "two"
    failure_a = (
        '<failure type="AssertionError" message="bad">'
        f"{root_a}/module.py:7: assertion failed"
        "</failure>"
    )
    failure_b = failure_a.replace(str(root_a), str(root_b))
    error = '<error type="RuntimeError" message="boom">trace</error>'
    _write(root_a, "a.xml", _suite(_case("z_error", terminal=error)))
    _write(root_a, "b.xml", _suite(_case("a_failure", terminal=failure_a)))
    _write(root_b, "a.xml", _suite(_case("z_error", terminal=error)))
    _write(root_b, "b.xml", _suite(_case("a_failure", terminal=failure_b)))

    summary_a = summarize_junit(root_a, ("a.xml", "b.xml"))
    reordered_a = summarize_junit(root_a, ("b.xml", "a.xml"))
    summary_b = summarize_junit(root_b, ("a.xml", "b.xml"))

    assert summary_a.outcome == "FAIL"
    assert summary_a.failure_count == 1
    assert summary_a.error_count == 1
    assert summary_a.first_failure_fingerprint == reordered_a.first_failure_fingerprint
    assert summary_a.first_failure_fingerprint == summary_b.first_failure_fingerprint
    assert summary_a.test_ids_digest == reordered_a.test_ids_digest
    assert summary_a.report_digests == reordered_a.report_digests


def test_report_digest_tracks_exact_bytes_while_test_manifest_stays_stable(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, "results.xml", _suite(_case("same")))
    first = summarize_junit(tmp_path, ("results.xml",))
    path.write_text(_suite(_case("same", time="0.002")), encoding="utf-8")
    second = summarize_junit(tmp_path, ("results.xml",))

    assert first.report_digests != second.report_digests
    assert first.test_ids_digest == second.test_ids_digest
    assert first.duration_ms != second.duration_ms


def test_namespace_junit_is_supported(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "results.xml",
        '<testsuites xmlns="urn:junit"><testsuite>'
        '<testcase classname="tests.ns" name="works" time="0"/>'
        "</testsuite></testsuites>",
    )

    summary = summarize_junit(tmp_path, ("results.xml",))

    assert summary.outcome == "PASS"
    assert summary.test_count == 1


def test_duplicate_or_conflicting_cases_fail_closed_without_echoing_test_id(
    tmp_path: Path,
) -> None:
    sensitive_id = "parameter-secret-value"
    _write(tmp_path, "one.xml", _suite(_case(sensitive_id)))
    _write(tmp_path, "two.xml", _suite(_case(sensitive_id)))
    with pytest.raises(JUnitEvidenceError, match="duplicate_testcase") as duplicate:
        summarize_junit(tmp_path, ("one.xml", "two.xml"))
    assert sensitive_id not in str(duplicate.value)

    _write(
        tmp_path,
        "conflict.xml",
        _suite(
            _case(
                sensitive_id,
                terminal="<failure>one</failure><error>two</error>",
            )
        ),
    )
    with pytest.raises(JUnitEvidenceError, match="conflicting_outcomes") as conflict:
        summarize_junit(tmp_path, ("conflict.xml",))
    assert sensitive_id not in str(conflict.value)


def test_normalized_duplicate_report_path_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "results.xml", _suite(_case("one")))

    with pytest.raises(JUnitEvidenceError, match="duplicate_report"):
        summarize_junit(tmp_path, ("results.xml", "./results.xml"))


@pytest.mark.parametrize("duration", ["-1", "NaN", "Infinity", "60.001", "1e999999"])
def test_invalid_or_oversized_duration_is_rejected(
    tmp_path: Path,
    duration: str,
) -> None:
    _write(tmp_path, "results.xml", _suite(_case("bad", time=duration)))

    with pytest.raises(JUnitEvidenceError, match="invalid_test_duration"):
        summarize_junit(tmp_path, ("results.xml",))


def test_empty_report_and_missing_optional_test_fail_closed(tmp_path: Path) -> None:
    _write(tmp_path, "empty.xml", "<testsuite/>")
    with pytest.raises(JUnitEvidenceError, match="no_testcases"):
        summarize_junit(tmp_path, ("empty.xml",))

    _write(tmp_path, "results.xml", _suite(_case("present")))
    with pytest.raises(JUnitEvidenceError, match="optional_test_missing"):
        summarize_junit(
            tmp_path,
            ("results.xml",),
            optional_test_ids=("tests.example::missing",),
        )


def test_external_entity_declarations_are_rejected_before_parsing(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "results.xml",
        '<!DOCTYPE x [<!ENTITY data SYSTEM "file:///etc/passwd">]>'
        '<testsuite><testcase classname="x" name="y">'
        "<failure>&data;</failure></testcase></testsuite>",
    )

    with pytest.raises(JUnitEvidenceError, match="xml_declaration_forbidden"):
        summarize_junit(tmp_path, ("results.xml",))


def test_path_escape_symlink_and_non_regular_report_are_rejected(
    tmp_path: Path,
) -> None:
    outside = _write(
        tmp_path.parent,
        f"outside-{tmp_path.name}.xml",
        _suite(_case("outside")),
    )
    with pytest.raises(JUnitEvidenceError, match="path_escape"):
        summarize_junit(tmp_path, (f"../{outside.name}",))

    link = tmp_path / "link.xml"
    link.symlink_to(outside)
    with pytest.raises(JUnitEvidenceError, match="symlink_input"):
        summarize_junit(tmp_path, ("link.xml",))

    if os.name == "posix":
        fifo = tmp_path / "fifo.xml"
        os.mkfifo(fifo)
        with pytest.raises(JUnitEvidenceError, match="non_regular_report"):
            summarize_junit(tmp_path, ("fifo.xml",))


def test_cli_writes_private_new_json_and_does_not_overwrite_inputs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = _write(
        tmp_path,
        "results.xml",
        _suite(_case("required", terminal="<failure>no</failure>")),
    )

    exit_code = junit_main(
        (
            "--repo-root",
            str(tmp_path),
            "--report",
            "results.xml",
            "--output",
            "summary.json",
        )
    )
    payload = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload["outcome"] == "FAIL"
    assert payload["required_skip_count"] == 0
    assert stat.S_IMODE((tmp_path / "summary.json").stat().st_mode) == 0o600
    assert report.read_text(encoding="utf-8").startswith("<testsuite")
    assert capsys.readouterr().err == ""

    assert junit_main(
        (
            "--repo-root",
            str(tmp_path),
            "--report",
            "results.xml",
            "--output",
            "summary.json",
        )
    ) == 2
    assert "output_exists" in capsys.readouterr().err

    assert junit_main(
        (
            "--repo-root",
            str(tmp_path),
            "--report",
            "results.xml",
            "--output",
            "results.xml",
        )
    ) == 2
    assert "output_overwrites_report" in capsys.readouterr().err


def test_cli_invalid_xml_returns_typed_mismatch_without_raw_xml(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sensitive = "xml-secret-value"
    _write(tmp_path, "bad.xml", f"<testsuite>{sensitive}")

    exit_code = junit_main(
        (
            "--repo-root",
            str(tmp_path),
            "--report",
            "bad.xml",
        )
    )
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.out == ""
    assert captured.err.strip() == "EVIDENCE_MISMATCH:junit:invalid_xml"
    assert sensitive not in captured.err
