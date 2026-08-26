from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path

import pytest

import scripts.production_operational_admission as command
from newsroom.production_admission import (
    PRODUCTION_GATE_IDS,
    OwnerIssueRecord,
    ProductionAdmissionError,
    ProductionOperationalAdmission,
    ProductionReadinessReport,
    inspect_readiness,
)
from newsroom.tests.test_production_operational_admission import (
    _EVIDENCE_KEY,
    _FREEZE,
    _OWNER_KEY,
    _PRODUCTION_KEY,
    _complete_evidence,
    _owner_instruction,
    _owner_issue_record,
)


def _git(repo: Path, *arguments: str) -> str:
    return subprocess.check_output(("git", *arguments), cwd=repo, text=True).strip()


def _key_env(monkeypatch: pytest.MonkeyPatch, name: str, secret: bytes) -> None:
    monkeypatch.setenv(name, base64.b64encode(secret).decode("ascii"))


def test_key_environment_cannot_self_assert_a_production_key_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _key_env(monkeypatch, "EVIDENCE_KEY", _EVIDENCE_KEY.secret)

    keys = command._keyring(
        ("EVIDENCE_KEY",),
        key_class=_EVIDENCE_KEY.key_class,
    )

    assert keys == {_EVIDENCE_KEY.key_id: _EVIDENCE_KEY}
    with pytest.raises(ProductionAdmissionError, match="environment variable"):
        command._keyring(
            (f"{_EVIDENCE_KEY.key_id}=EVIDENCE_KEY",),
            key_class=_EVIDENCE_KEY.key_class,
        )


def test_exact_main_freeze_requires_a_clean_checkout_on_main(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Production Admission Test")
    (tmp_path / "subject.txt").write_text("exact\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "exact main")
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")

    freeze = command.exact_main_freeze(tmp_path)

    assert freeze.exact_main_sha == _git(tmp_path, "rev-parse", "HEAD")
    assert freeze.exact_main_tree == _git(tmp_path, "rev-parse", "HEAD^{tree}")
    (tmp_path / "untracked.txt").write_text("drift\n", encoding="utf-8")
    with pytest.raises(ProductionAdmissionError, match="clean"):
        command.exact_main_freeze(tmp_path)


def test_exact_main_freeze_requires_retained_origin_main_authority(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Production Admission Test")
    (tmp_path / "subject.txt").write_text("exact\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "exact main")

    with pytest.raises(ProductionAdmissionError, match="origin/main is unavailable"):
        command.exact_main_freeze(tmp_path)


def test_exact_main_freeze_ignores_path_and_git_environment_redirection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    _git(checkout, "init", "-b", "main")
    _git(checkout, "config", "user.email", "test@example.invalid")
    _git(checkout, "config", "user.name", "Production Admission Test")
    (checkout / "subject.txt").write_text("exact\n", encoding="utf-8")
    _git(checkout, "add", ".")
    _git(checkout, "commit", "-m", "exact main")
    _git(checkout, "update-ref", "refs/remotes/origin/main", "HEAD")
    expected_sha = _git(checkout, "rev-parse", "HEAD")
    expected_tree = _git(checkout, "rev-parse", "HEAD^{tree}")

    redirected = tmp_path / "redirected"
    redirected.mkdir()
    _git(redirected, "init", "-b", "main")
    _git(redirected, "config", "user.email", "test@example.invalid")
    _git(redirected, "config", "user.name", "Production Admission Test")
    (redirected / "subject.txt").write_text("redirected\n", encoding="utf-8")
    _git(redirected, "add", ".")
    _git(redirected, "commit", "-m", "redirected main")

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    marker = tmp_path / "fake-git-ran"
    fake_git = fake_bin / "git"
    fake_git.write_text(
        f"#!/bin/sh\nprintf invoked > {str(marker)!r}\nprintf '%040d\\n' 0\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")
    monkeypatch.setenv("GIT_DIR", str(redirected / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(redirected))

    freeze = command.exact_main_freeze(checkout)

    assert freeze.exact_main_sha == expected_sha
    assert freeze.exact_main_tree == expected_tree
    assert not marker.exists()


def test_cli_inspect_mint_and_verify_are_provider_free_and_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(command, "exact_main_freeze", lambda _root: _FREEZE)
    checked_owner_issues: list[int] = []

    def current_owner_issue(issue_number: int) -> OwnerIssueRecord:
        checked_owner_issues.append(issue_number)
        return _owner_issue_record(issue_number)

    monkeypatch.setattr(command, "_current_owner_issue", current_owner_issue)
    _key_env(monkeypatch, "EVIDENCE_KEY", _EVIDENCE_KEY.secret)
    _key_env(monkeypatch, "OWNER_KEY", _OWNER_KEY.secret)
    _key_env(monkeypatch, "PRODUCTION_KEY", _PRODUCTION_KEY.secret)
    manifest, attestations = _complete_evidence()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(manifest.canonical_bytes)
    attestation_directory = tmp_path / "attestations"
    attestation_directory.mkdir()
    for item in attestations:
        (attestation_directory / f"{item.gate_id.value}.json").write_bytes(
            item.canonical_bytes
        )
    report_path = tmp_path / "report.json"
    evidence_key_spec = "EVIDENCE_KEY"

    assert (
        command.main(
            (
                "inspect",
                "--repo-root",
                str(tmp_path),
                "--evidence-manifest",
                str(manifest_path),
                "--attestation-directory",
                str(attestation_directory),
                "--evidence-key-env",
                evidence_key_spec,
                "--output",
                str(report_path),
            )
        )
        == 0
    )
    report = ProductionReadinessReport.from_canonical_bytes(report_path.read_bytes())
    instruction = _owner_instruction(
        report=report,
        manifest=manifest,
    )
    instruction_path = tmp_path / "instruction.json"
    instruction_path.write_bytes(instruction.canonical_bytes)
    admission_path = tmp_path / "admission.json"

    common = (
        "--repo-root",
        str(tmp_path),
        "--evidence-manifest",
        str(manifest_path),
        "--attestation-directory",
        str(attestation_directory),
        "--evidence-key-env",
        evidence_key_spec,
        "--readiness-report",
        str(report_path),
        "--owner-instruction",
        str(instruction_path),
        "--owner-key-env",
        "OWNER_KEY",
        "--production-key-env",
        "PRODUCTION_KEY",
    )
    assert command.main(("mint", *common, "--output", str(admission_path))) == 0
    assert command.main(("verify", *common, "--admission", str(admission_path))) == 0
    assert checked_owner_issues == [900]
    admission = ProductionOperationalAdmission.from_canonical_bytes(
        admission_path.read_bytes(),
        report=report,
        evidence_manifest=manifest,
        owner_instruction=instruction,
        trusted_owner_keys={_OWNER_KEY.key_id: _OWNER_KEY},
        trusted_production_keys={_PRODUCTION_KEY.key_id: _PRODUCTION_KEY},
    )
    assert admission.production_activation_authorised is False


def test_cli_retains_a_complete_blocked_report_when_manifest_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(command, "exact_main_freeze", lambda _root: _FREEZE)
    output = tmp_path / "blocked.json"

    assert (
        command.main(
            (
                "inspect",
                "--repo-root",
                str(tmp_path),
                "--output",
                str(output),
            )
        )
        == 2
    )
    report = ProductionReadinessReport.from_canonical_bytes(output.read_bytes())
    expected = inspect_readiness(
        freeze=_FREEZE,
        evidence_manifest=None,
        attestations=(),
        trusted_evidence_keys={},
    )
    assert report == expected


@pytest.mark.parametrize(
    ("invalid_path", "expected_blocker"),
    (
        ("manifest", "INVALID_PRODUCTION_EVIDENCE_MANIFEST"),
        ("attestation", "INVALID_GATE_ATTESTATION_DOCUMENT"),
    ),
)
def test_cli_retains_a_complete_blocked_report_for_malformed_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_path: str,
    expected_blocker: str,
) -> None:
    monkeypatch.setattr(command, "exact_main_freeze", lambda _root: _FREEZE)
    manifest, attestations = _complete_evidence()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(
        b"{}" if invalid_path == "manifest" else manifest.canonical_bytes
    )
    attestation_directory = tmp_path / "attestations"
    attestation_directory.mkdir()
    for item in attestations:
        payload = (
            b"{}"
            if invalid_path == "attestation" and item.gate_id == PRODUCTION_GATE_IDS[0]
            else item.canonical_bytes
        )
        (attestation_directory / f"{item.gate_id.value}.json").write_bytes(payload)
    output = tmp_path / "blocked.json"

    assert (
        command.main(
            (
                "inspect",
                "--repo-root",
                str(tmp_path),
                "--evidence-manifest",
                str(manifest_path),
                "--attestation-directory",
                str(attestation_directory),
                "--output",
                str(output),
            )
        )
        == 2
    )
    report = ProductionReadinessReport.from_canonical_bytes(output.read_bytes())
    assert tuple(gate.gate_id for gate in report.gates) == PRODUCTION_GATE_IDS
    assert all(gate.blockers == (expected_blocker,) for gate in report.gates)
