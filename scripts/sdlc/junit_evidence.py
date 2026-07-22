from __future__ import annotations

import argparse
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Iterable, Sequence
import xml.etree.ElementTree as ET


SCHEMA_VERSION = "newsroom.sdlc.junit-summary.v1"
_MAX_REPORTS = 32
_MAX_REPORT_BYTES = 16 * 1024 * 1024
_MAX_TESTS = 100_000
_MAX_TEST_SECONDS = Decimal("60")
_MAX_FIELD_CHARS = 262_144
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class JUnitEvidenceError(ValueError):
    """Raised when JUnit bytes cannot become trustworthy gate evidence."""


@dataclass(frozen=True)
class JUnitSummary:
    outcome: str
    report_digests: tuple[tuple[str, str], ...]
    test_ids_digest: str
    test_count: int
    failure_count: int
    error_count: int
    skip_count: int
    required_skip_count: int
    duration_ms: int
    first_failure_fingerprint: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "outcome": self.outcome,
            "reports": [
                {"path": path, "digest": digest}
                for path, digest in self.report_digests
            ],
            "test_ids_digest": self.test_ids_digest,
            "test_count": self.test_count,
            "failure_count": self.failure_count,
            "error_count": self.error_count,
            "skip_count": self.skip_count,
            "required_skip_count": self.required_skip_count,
            "duration_ms": self.duration_ms,
            "first_failure_fingerprint": self.first_failure_fingerprint,
        }


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _safe_relative(root: Path, relative: str | Path, *, must_exist: bool) -> Path:
    candidate = Path(relative)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or ".." in candidate.parts
        or "\\" in str(relative)
    ):
        raise JUnitEvidenceError("path_escape")
    unresolved = root / candidate
    current = root
    for part in candidate.parts:
        current /= part
        if current.is_symlink():
            raise JUnitEvidenceError("symlink_input")
    resolved = unresolved.resolve()
    if not resolved.is_relative_to(root):
        raise JUnitEvidenceError("path_escape")
    if must_exist:
        try:
            metadata = os.lstat(unresolved)
        except FileNotFoundError as exc:
            raise JUnitEvidenceError("missing_report") from exc
        except OSError as exc:
            raise JUnitEvidenceError("report_stat") from exc
        if not stat.S_ISREG(metadata.st_mode):
            raise JUnitEvidenceError("non_regular_report")
    return unresolved


def _read_report(root: Path, relative: str) -> tuple[bytes, str]:
    path = _safe_relative(root, relative, must_exist=True)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise JUnitEvidenceError("report_open") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise JUnitEvidenceError("non_regular_report")
        if metadata.st_size <= 0 or metadata.st_size > _MAX_REPORT_BYTES:
            raise JUnitEvidenceError("report_size")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            payload = stream.read(_MAX_REPORT_BYTES + 1)
    finally:
        os.close(descriptor)
    if not payload or len(payload) > _MAX_REPORT_BYTES:
        raise JUnitEvidenceError("report_size")
    upper = payload.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise JUnitEvidenceError("xml_declaration_forbidden")
    return payload, path.relative_to(root).as_posix()


def _field(value: str | None, name: str) -> str:
    text = value or ""
    if len(text) > _MAX_FIELD_CHARS:
        raise JUnitEvidenceError(f"field_too_large:{name}")
    return text


def _case_id(case: ET.Element) -> str:
    name = _field(case.attrib.get("name"), "name").strip()
    if not name:
        raise JUnitEvidenceError("testcase_name_missing")
    owner = (
        _field(case.attrib.get("classname"), "classname").strip()
        or _field(case.attrib.get("file"), "file").strip()
        or "<unknown>"
    )
    return f"{owner}::{name}"


def _duration_seconds(case: ET.Element) -> Decimal:
    raw = case.attrib.get("time", "0").strip()
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise JUnitEvidenceError("invalid_test_duration") from exc
    if not value.is_finite() or value < 0 or value > _MAX_TEST_SECONDS:
        raise JUnitEvidenceError("invalid_test_duration")
    return value


def _normalized_failure_text(value: str, root: Path) -> str:
    text = _field(value, "failure_text")
    text = _ANSI.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = text.replace(str(root), "<repo>")
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def _failure_fingerprint(
    *,
    test_id: str,
    outcome: str,
    element: ET.Element,
    root: Path,
) -> str:
    payload = {
        "test_id": test_id,
        "outcome": outcome,
        "type": _field(element.attrib.get("type"), "failure_type"),
        "message": _normalized_failure_text(
            _field(element.attrib.get("message"), "failure_message"),
            root,
        ),
        "text": _normalized_failure_text("".join(element.itertext()), root),
    }
    return _sha256(_canonical_json(payload))


def summarize_junit(
    repo_root: str | Path,
    reports: Iterable[str | Path],
    *,
    optional_test_ids: Iterable[str] = (),
) -> JUnitSummary:
    root = Path(repo_root).resolve()
    if not root.is_dir():
        raise JUnitEvidenceError("repo_root_missing")
    report_names = tuple(str(item) for item in reports)
    if not report_names or len(report_names) > _MAX_REPORTS:
        raise JUnitEvidenceError("report_count")
    optional_values = tuple(optional_test_ids)
    if len(optional_values) > _MAX_TESTS:
        raise JUnitEvidenceError("optional_test_count")
    if any(not item or len(item) > _MAX_FIELD_CHARS for item in optional_values):
        raise JUnitEvidenceError("optional_test_id_invalid")
    optional = frozenset(optional_values)

    cases: dict[str, tuple[str, ET.Element | None, Decimal]] = {}
    report_digests: list[tuple[str, str]] = []
    seen_reports: set[str] = set()
    for report in report_names:
        payload, normalized_path = _read_report(root, report)
        if normalized_path in seen_reports:
            raise JUnitEvidenceError("duplicate_report")
        seen_reports.add(normalized_path)
        try:
            document = ET.fromstring(payload)
        except ET.ParseError as exc:
            raise JUnitEvidenceError("invalid_xml") from exc
        if _local_name(document.tag) not in {"testsuite", "testsuites"}:
            raise JUnitEvidenceError("invalid_junit_root")
        report_digests.append((normalized_path, _sha256(payload)))
        for case in (
            item for item in document.iter() if _local_name(item.tag) == "testcase"
        ):
            test_id = _case_id(case)
            if test_id in cases:
                raise JUnitEvidenceError("duplicate_testcase")
            terminals = [
                child
                for child in case
                if _local_name(child.tag) in {"failure", "error", "skipped"}
            ]
            if len(terminals) > 1:
                raise JUnitEvidenceError("conflicting_outcomes")
            outcome = _local_name(terminals[0].tag) if terminals else "passed"
            cases[test_id] = (
                outcome,
                terminals[0] if terminals else None,
                _duration_seconds(case),
            )
            if len(cases) > _MAX_TESTS:
                raise JUnitEvidenceError("test_count")

    if not cases:
        raise JUnitEvidenceError("no_testcases")
    if optional - cases.keys():
        raise JUnitEvidenceError("optional_test_missing")

    failure_count = error_count = skip_count = required_skip_count = 0
    gate_failures: list[tuple[str, str, str]] = []
    duration = Decimal(0)
    for test_id in sorted(cases):
        outcome, terminal, seconds = cases[test_id]
        duration += seconds
        if outcome == "failure":
            failure_count += 1
        elif outcome == "error":
            error_count += 1
        elif outcome == "skipped":
            skip_count += 1
            if test_id not in optional:
                required_skip_count += 1
        if outcome in {"failure", "error"} or (
            outcome == "skipped" and test_id not in optional
        ):
            assert terminal is not None
            gate_failures.append(
                (
                    test_id,
                    outcome,
                    _failure_fingerprint(
                        test_id=test_id,
                        outcome=outcome,
                        element=terminal,
                        root=root,
                    ),
                )
            )

    outcome = (
        "FAIL"
        if failure_count or error_count or required_skip_count
        else "PASS"
    )
    duration_ms = int(
        (duration * 1000).to_integral_value(rounding=ROUND_HALF_UP)
    )
    first_fingerprint = (
        sorted(gate_failures, key=lambda item: (item[0], item[1]))[0][2]
        if gate_failures
        else None
    )
    return JUnitSummary(
        outcome=outcome,
        report_digests=tuple(sorted(report_digests)),
        test_ids_digest=_sha256(_canonical_json(sorted(cases))),
        test_count=len(cases),
        failure_count=failure_count,
        error_count=error_count,
        skip_count=skip_count,
        required_skip_count=required_skip_count,
        duration_ms=duration_ms,
        first_failure_fingerprint=first_fingerprint,
    )


def _write_output(
    root: Path,
    relative: str,
    rendered: str,
    *,
    report_paths: frozenset[str],
) -> None:
    path = _safe_relative(root, relative, must_exist=False)
    normalized = path.relative_to(root).as_posix()
    if normalized in report_paths:
        raise JUnitEvidenceError("output_overwrites_report")
    if path.suffix != ".json":
        raise JUnitEvidenceError("output_extension")
    if not path.parent.is_dir():
        raise JUnitEvidenceError("output_parent_missing")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise JUnitEvidenceError("output_exists") from exc
    except OSError as exc:
        raise JUnitEvidenceError("output_open") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(rendered)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize exact JUnit evidence")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--report", action="append", required=True)
    parser.add_argument("--optional-test-id", action="append", default=[])
    parser.add_argument("--output")
    arguments = parser.parse_args(argv)
    root = Path(arguments.repo_root).resolve()
    try:
        summary = summarize_junit(
            root,
            arguments.report,
            optional_test_ids=arguments.optional_test_id,
        )
        rendered = json.dumps(
            summary.as_dict(),
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
        if arguments.output:
            _write_output(
                root,
                arguments.output,
                rendered,
                report_paths=frozenset(path for path, _ in summary.report_digests),
            )
        else:
            sys.stdout.write(rendered)
    except (JUnitEvidenceError, OSError, UnicodeError) as exc:
        reason = str(exc) or type(exc).__name__
        print(f"EVIDENCE_MISMATCH:junit:{reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
