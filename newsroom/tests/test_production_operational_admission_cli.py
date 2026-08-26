from __future__ import annotations

import base64
import subprocess
from pathlib import Path

import pytest

import scripts.production_operational_admission as command
from newsroom.production_admission import (
    OwnerAdmissionInstruction,
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
)


def _git(repo: Path, *arguments: str) -> str:
    return subprocess.check_output(("git", *arguments), cwd=repo, text=True).strip()


def _key_env(monkeypatch: pytest.MonkeyPatch, name: str, secret: bytes) -> None:
    monkeypatch.setenv(name, base64.b64encode(secret).decode("ascii"))


def test_exact_main_freeze_requires_a_clean_checkout_on_main(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Production Admission Test")
    (tmp_path / "subject.txt").write_text("exact\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "exact main")

    freeze = command.exact_main_freeze(tmp_path)

    assert freeze.exact_main_sha == _git(tmp_path, "rev-parse", "HEAD")
    assert freeze.exact_main_tree == _git(tmp_path, "rev-parse", "HEAD^{tree}")
    (tmp_path / "untracked.txt").write_text("drift\n", encoding="utf-8")
    with pytest.raises(ProductionAdmissionError, match="clean"):
        command.exact_main_freeze(tmp_path)


def test_cli_inspect_mint_and_verify_are_provider_free_and_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(command, "exact_main_freeze", lambda _root: _FREEZE)
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
    evidence_key_spec = f"{_EVIDENCE_KEY.key_id}=EVIDENCE_KEY"

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
    instruction = OwnerAdmissionInstruction.build(
        authority_issue_number=900,
        owner_identity="github:fol2",
        issued_at="2026-08-26T10:30:00Z",
        report=report,
        evidence_manifest=manifest,
        production_signing_key_id=_PRODUCTION_KEY.key_id,
        owner_signing_key=_OWNER_KEY,
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
        f"{_OWNER_KEY.key_id}=OWNER_KEY",
        "--production-key-env",
        f"{_PRODUCTION_KEY.key_id}=PRODUCTION_KEY",
    )
    assert command.main(("mint", *common, "--output", str(admission_path))) == 0
    assert command.main(("verify", *common, "--admission", str(admission_path))) == 0
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
