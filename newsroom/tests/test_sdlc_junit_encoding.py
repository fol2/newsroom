from __future__ import annotations

from pathlib import Path

import pytest

from scripts.sdlc.junit_evidence import JUnitEvidenceError, summarize_junit


def test_non_utf8_junit_cannot_bypass_declaration_scan(tmp_path: Path) -> None:
    payload = (
        '<!DOCTYPE x [<!ENTITY data SYSTEM "file:///etc/passwd">]>'
        '<testsuite><testcase classname="x" name="y">'
        "<failure>&data;</failure></testcase></testsuite>"
    ).encode("utf-16")
    (tmp_path / "encoded.xml").write_bytes(payload)

    with pytest.raises(JUnitEvidenceError, match="invalid_encoding"):
        summarize_junit(tmp_path, ("encoded.xml",))
