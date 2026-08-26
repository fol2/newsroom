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


def test_keyring_loads_only_the_fixed_keychain_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[str] = []

    def keychain_secret(key_id: str) -> bytes:
        requested.append(key_id)
        return _EVIDENCE_KEY.secret

    monkeypatch.setattr(command, "_keychain_secret", keychain_secret)
    monkeypatch.setenv("EVIDENCE_KEY", "ignored-caller-secret")

    keys = command._keyring(key_class=_EVIDENCE_KEY.key_class)

    assert keys == {_EVIDENCE_KEY.key_id: _EVIDENCE_KEY}
    assert requested == [_EVIDENCE_KEY.key_id]


def test_keychain_loader_uses_the_fixed_account_and_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trusted_security = tmp_path / "security"
    trusted_security.write_text("fixed executable", encoding="utf-8")
    monkeypatch.setattr(command, "_TRUSTED_SECURITY", trusted_security)
    seen: dict[str, object] = {}

    def run(
        arguments: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        seen["arguments"] = arguments
        seen.update(kwargs)
        return subprocess.CompletedProcess(
            arguments,
            0,
            stdout=base64.b64encode(_EVIDENCE_KEY.secret).decode("ascii") + "\n",
            stderr="",
        )

    monkeypatch.setattr(command.subprocess, "run", run)

    assert command._keychain_secret(_EVIDENCE_KEY.key_id) == _EVIDENCE_KEY.secret
    assert seen["arguments"] == (
        str(trusted_security),
        "find-generic-password",
        "-a",
        "newsroom-production-admission",
        "-s",
        "newsroom-evidence-v1",
        "-w",
    )
    with pytest.raises(ProductionAdmissionError, match="reference differs"):
        command._keychain_secret("keychain:caller-selected")


def test_exact_main_freeze_requires_a_clean_checkout_on_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Production Admission Test")
    (tmp_path / "subject.txt").write_text("exact\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "exact main")
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")
    monkeypatch.setattr(
        command,
        "_live_main_sha",
        lambda: _git(tmp_path, "rev-parse", "HEAD"),
    )

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


def test_live_main_lookup_uses_only_the_canonical_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trusted_git = tmp_path / "git"
    trusted_git.write_text("fixed executable", encoding="utf-8")
    monkeypatch.setattr(command, "_TRUSTED_GIT", trusted_git)
    seen: dict[str, object] = {}

    def run(
        arguments: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        seen["arguments"] = arguments
        seen.update(kwargs)
        return subprocess.CompletedProcess(
            arguments,
            0,
            stdout=f"{'e' * 40}\trefs/heads/main\n",
            stderr="",
        )

    monkeypatch.setattr(command.subprocess, "run", run)

    assert command._live_main_sha() == "e" * 40
    assert seen["arguments"] == (
        str(trusted_git),
        "ls-remote",
        "--exit-code",
        "https://github.com/fol2/newsroom.git",
        "refs/heads/main",
    )
    assert seen["cwd"] == Path("/")
    assert seen["env"] == command._GIT_ENVIRONMENT


def test_exact_main_freeze_rejects_a_stale_retained_origin_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Production Admission Test")
    (tmp_path / "subject.txt").write_text("exact\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "retained main")
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")
    monkeypatch.setattr(command, "_live_main_sha", lambda: "f" * 40)

    with pytest.raises(ProductionAdmissionError, match="live GitHub main"):
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
    monkeypatch.setattr(command, "_live_main_sha", lambda: expected_sha)

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
    key_secrets = {
        _EVIDENCE_KEY.key_id: _EVIDENCE_KEY.secret,
        _OWNER_KEY.key_id: _OWNER_KEY.secret,
        _PRODUCTION_KEY.key_id: _PRODUCTION_KEY.secret,
    }
    monkeypatch.setattr(command, "_keychain_secret", key_secrets.__getitem__)
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
        "--readiness-report",
        str(report_path),
        "--owner-instruction",
        str(instruction_path),
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
