"""Inspect, mint and verify production Operational Admission records.

The command performs read-only GitHub, Git, local-file and Keychain reads.  It
never invokes a provider, publication adapter or production writer.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import pwd
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from newsroom.production_admission import (
    AuthenticationKey,
    FreezeIdentity,
    GateAttestation,
    KeyClass,
    KeyProvenance,
    OwnerAdmissionInstruction,
    OwnerIssueRecord,
    ProductionAdmissionError,
    ProductionEvidenceManifest,
    ProductionOperationalAdmission,
    ProductionReadinessReport,
    blocked_readiness_report,
    inspect_readiness,
    mint_production_operational_admission,
    production_key_id,
)

_TRUSTED_GIT = Path("/usr/bin/git")
_TRUSTED_SECURITY = Path("/usr/bin/security")
_CANONICAL_REPOSITORY_URL = "https://github.com/fol2/newsroom.git"
_CANONICAL_MAIN_REF = "refs/heads/main"
_KEYCHAIN_ACCOUNT = "newsroom-production-admission"
_TRUSTED_GH_CANDIDATES = (
    Path("/opt/homebrew/bin/gh"),
    Path("/usr/local/bin/gh"),
)
_GIT_ENVIRONMENT = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_TERMINAL_PROMPT": "0",
    "LANG": "C",
    "LC_ALL": "C",
    "PATH": "/usr/bin:/bin",
}


def _run_git(repo_root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    if not _TRUSTED_GIT.is_file():
        raise ProductionAdmissionError("trusted Git executable is unavailable")
    return subprocess.run(
        (
            str(_TRUSTED_GIT),
            "-c",
            f"core.worktree={repo_root}",
            *arguments,
        ),
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        env=_GIT_ENVIRONMENT,
    )


def _git(repo_root: Path, *arguments: str, check: bool = True) -> str:
    completed = _run_git(repo_root, *arguments)
    if check and completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ProductionAdmissionError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout.strip()


def _live_main_sha() -> str:
    """Read the current canonical GitHub main identity without mutating refs."""

    if not _TRUSTED_GIT.is_file():
        raise ProductionAdmissionError("trusted Git executable is unavailable")
    completed = subprocess.run(
        (
            str(_TRUSTED_GIT),
            "ls-remote",
            "--exit-code",
            _CANONICAL_REPOSITORY_URL,
            _CANONICAL_MAIN_REF,
        ),
        cwd=Path("/"),
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
        env=_GIT_ENVIRONMENT,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ProductionAdmissionError(f"live GitHub main lookup failed: {detail}")
    match = re.fullmatch(
        rf"([0-9a-f]{{40}})\t{re.escape(_CANONICAL_MAIN_REF)}",
        completed.stdout.strip(),
    )
    if match is None:
        raise ProductionAdmissionError("live GitHub main identity differs")
    return match.group(1)


def exact_main_freeze(repo_root: Path) -> FreezeIdentity:
    """Resolve one clean checkout whose HEAD is the exact local/remote main."""

    root = repo_root.resolve(strict=True)
    head = _git(root, "rev-parse", "--verify", "HEAD^{commit}")
    tree = _git(root, "rev-parse", "--verify", "HEAD^{tree}")
    main = _git(root, "rev-parse", "--verify", "refs/heads/main^{commit}")
    if head != main:
        raise ProductionAdmissionError("checkout HEAD is not exact main")
    remote_present = (
        _run_git(
            root,
            "show-ref",
            "--verify",
            "--quiet",
            "refs/remotes/origin/main",
        ).returncode
        == 0
    )
    if not remote_present:
        raise ProductionAdmissionError("origin/main is unavailable")
    remote = _git(
        root,
        "rev-parse",
        "--verify",
        "refs/remotes/origin/main^{commit}",
    )
    if head != remote:
        raise ProductionAdmissionError("checkout HEAD differs from origin/main")
    status = _run_git(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    )
    if status.returncode != 0:
        raise ProductionAdmissionError("clean-checkout inspection failed")
    if status.stdout:
        raise ProductionAdmissionError("production admission requires a clean checkout")
    if head != _live_main_sha():
        raise ProductionAdmissionError("checkout HEAD differs from live GitHub main")
    return FreezeIdentity(exact_main_sha=head, exact_main_tree=tree)


def _current_owner_issue(issue_number: int) -> OwnerIssueRecord:
    executable = next(
        (candidate for candidate in _TRUSTED_GH_CANDIDATES if candidate.is_file()),
        None,
    )
    if executable is None:
        raise ProductionAdmissionError("trusted GitHub CLI is unavailable")
    environment = {
        **_GIT_ENVIRONMENT,
        "GH_HOST": "github.com",
        "HOME": pwd.getpwuid(os.getuid()).pw_dir,
    }
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        if name in os.environ:
            environment[name] = os.environ[name]
    completed = subprocess.run(
        (
            str(executable),
            "api",
            f"repos/fol2/newsroom/issues/{issue_number}",
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
        env=environment,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ProductionAdmissionError(f"owner issue live lookup failed: {detail}")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ProductionAdmissionError("owner issue live lookup is not JSON") from exc
    return OwnerIssueRecord.from_github_api(value)


def _keychain_secret(key_id: str) -> bytes:
    """Load one fixed production trust root from the macOS Keychain."""

    if not _TRUSTED_SECURITY.is_file():
        raise ProductionAdmissionError("trusted Keychain executable is unavailable")
    configured_key_ids = frozenset(production_key_id(item) for item in KeyClass)
    if key_id not in configured_key_ids:
        raise ProductionAdmissionError("production Keychain reference differs")
    service = key_id.removeprefix("keychain:")
    completed = subprocess.run(
        (
            str(_TRUSTED_SECURITY),
            "find-generic-password",
            "-a",
            _KEYCHAIN_ACCOUNT,
            "-s",
            service,
            "-w",
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        env={
            "HOME": pwd.getpwuid(os.getuid()).pw_dir,
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": "/usr/bin:/bin",
        },
    )
    if completed.returncode != 0:
        raise ProductionAdmissionError(f"production Keychain item is absent: {key_id}")
    encoded = completed.stdout.strip()
    try:
        secret = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ProductionAdmissionError(
            f"production Keychain item is not canonical base64: {key_id}"
        ) from exc
    if base64.b64encode(secret).decode("ascii") != encoded:
        raise ProductionAdmissionError(
            f"production Keychain item is not canonical base64: {key_id}"
        )
    return secret


def _keyring(*, key_class: KeyClass) -> dict[str, AuthenticationKey]:
    key_id = production_key_id(key_class)
    return {
        key_id: AuthenticationKey(
            key_id,
            key_class,
            KeyProvenance.PRODUCTION_TRUST_ROOT,
            _keychain_secret(key_id),
        )
    }


def _manifest(path: Path | None) -> ProductionEvidenceManifest | None:
    if path is None:
        return None
    return ProductionEvidenceManifest.from_canonical_bytes(path.read_bytes())


def _attestations(directory: Path | None) -> tuple[GateAttestation, ...]:
    if directory is None:
        return ()
    if not directory.is_dir() or directory.is_symlink():
        raise ProductionAdmissionError("attestation directory is unavailable")
    paths = tuple(sorted(directory.glob("*.json")))
    return tuple(
        GateAttestation.from_canonical_bytes(path.read_bytes()) for path in paths
    )


def _write_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as output:
            output.write(payload)
    except FileExistsError as exc:
        raise ProductionAdmissionError(f"output already exists: {path}") from exc


def _add_evidence_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--evidence-manifest", required=True, type=Path)
    parser.add_argument("--attestation-directory", required=True, type=Path)


def _load_current_report(
    arguments: argparse.Namespace,
) -> tuple[
    FreezeIdentity,
    ProductionEvidenceManifest,
    tuple[GateAttestation, ...],
    dict[str, AuthenticationKey],
    ProductionReadinessReport,
]:
    freeze = exact_main_freeze(arguments.repo_root)
    manifest = _manifest(arguments.evidence_manifest)
    if manifest is None:  # pragma: no cover - required by argparse
        raise ProductionAdmissionError("production evidence manifest is required")
    attestations = _attestations(arguments.attestation_directory)
    evidence_keys = _keyring(key_class=KeyClass.EVIDENCE_AUTHORITY)
    report = ProductionReadinessReport.from_canonical_bytes(
        arguments.readiness_report.read_bytes()
    )
    current = inspect_readiness(
        freeze=freeze,
        evidence_manifest=manifest,
        attestations=attestations,
        trusted_evidence_keys=evidence_keys,
    )
    if current != report:
        raise ProductionAdmissionError("retained readiness report is not current")
    return freeze, manifest, attestations, evidence_keys, report


def _inspect(arguments: argparse.Namespace) -> int:
    freeze = exact_main_freeze(arguments.repo_root)
    try:
        manifest = _manifest(arguments.evidence_manifest)
    except (OSError, ProductionAdmissionError):
        report = blocked_readiness_report(
            freeze=freeze,
            blocker="INVALID_PRODUCTION_EVIDENCE_MANIFEST",
        )
    else:
        if manifest is None:
            report = inspect_readiness(
                freeze=freeze,
                evidence_manifest=None,
                attestations=(),
                trusted_evidence_keys={},
            )
        else:
            report = _inspect_retained_evidence(arguments, freeze, manifest)
    _write_exclusive(arguments.output, report.canonical_bytes)
    print(f"readiness_report_digest={report.digest}")
    print(f"ready_for_admission={str(report.ready_for_admission).lower()}")
    return 0 if report.ready_for_admission else 2


def _inspect_retained_evidence(
    arguments: argparse.Namespace,
    freeze: FreezeIdentity,
    manifest: ProductionEvidenceManifest,
) -> ProductionReadinessReport:
    """Inspect one parsed manifest while converting malformed inputs to blockers."""

    try:
        attestations = _attestations(arguments.attestation_directory)
    except (OSError, ProductionAdmissionError):
        return blocked_readiness_report(
            freeze=freeze,
            blocker="INVALID_GATE_ATTESTATION_DOCUMENT",
        )
    try:
        evidence_keys = _keyring(key_class=KeyClass.EVIDENCE_AUTHORITY)
    except ProductionAdmissionError:
        return blocked_readiness_report(
            freeze=freeze,
            blocker="INVALID_EVIDENCE_TRUST_CONFIGURATION",
        )
    return inspect_readiness(
        freeze=freeze,
        evidence_manifest=manifest,
        attestations=attestations,
        trusted_evidence_keys=evidence_keys,
    )


def _mint(arguments: argparse.Namespace) -> int:
    freeze, manifest, attestations, evidence_keys, report = _load_current_report(
        arguments
    )
    instruction = OwnerAdmissionInstruction.from_canonical_bytes(
        arguments.owner_instruction.read_bytes()
    )
    current_owner_issue = _current_owner_issue(instruction.authority_issue_number)
    owner_keys = _keyring(key_class=KeyClass.HUMAN_ACCOUNTABLE_OWNER)
    production_keys = _keyring(key_class=KeyClass.PRODUCTION_OPERATIONAL_ADMISSION)
    production_key = production_keys.get(instruction.production_signing_key_id)
    if production_key is None:
        raise ProductionAdmissionError("instruction-named production key is absent")
    admission = mint_production_operational_admission(
        freeze=freeze,
        report=report,
        evidence_manifest=manifest,
        attestations=attestations,
        trusted_evidence_keys=evidence_keys,
        owner_instruction=instruction,
        current_owner_issue=current_owner_issue,
        trusted_owner_keys=owner_keys,
        production_signing_key=production_key,
    )
    _write_exclusive(arguments.output, admission.canonical_bytes)
    print(f"production_operational_admission_digest={admission.digest}")
    return 0


def _verify(arguments: argparse.Namespace) -> int:
    _freeze, manifest, _attestations_value, _evidence_keys, report = (
        _load_current_report(arguments)
    )
    instruction = OwnerAdmissionInstruction.from_canonical_bytes(
        arguments.owner_instruction.read_bytes()
    )
    owner_keys = _keyring(key_class=KeyClass.HUMAN_ACCOUNTABLE_OWNER)
    production_keys = _keyring(key_class=KeyClass.PRODUCTION_OPERATIONAL_ADMISSION)
    admission = ProductionOperationalAdmission.from_canonical_bytes(
        arguments.admission.read_bytes(),
        report=report,
        evidence_manifest=manifest,
        owner_instruction=instruction,
        trusted_owner_keys=owner_keys,
        trusted_production_keys=production_keys,
    )
    print(f"production_operational_admission_digest={admission.digest}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--repo-root", required=True, type=Path)
    inspect_parser.add_argument("--evidence-manifest", type=Path)
    inspect_parser.add_argument("--attestation-directory", type=Path)
    inspect_parser.add_argument("--output", required=True, type=Path)
    inspect_parser.set_defaults(handler=_inspect)

    mint_parser = subparsers.add_parser("mint")
    _add_evidence_arguments(mint_parser)
    mint_parser.add_argument("--readiness-report", required=True, type=Path)
    mint_parser.add_argument("--owner-instruction", required=True, type=Path)
    mint_parser.add_argument("--output", required=True, type=Path)
    mint_parser.set_defaults(handler=_mint)

    verify_parser = subparsers.add_parser("verify")
    _add_evidence_arguments(verify_parser)
    verify_parser.add_argument("--readiness-report", required=True, type=Path)
    verify_parser.add_argument("--owner-instruction", required=True, type=Path)
    verify_parser.add_argument("--admission", required=True, type=Path)
    verify_parser.set_defaults(handler=_verify)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return int(arguments.handler(arguments))
    except (OSError, subprocess.SubprocessError, ProductionAdmissionError) as exc:
        print(f"PRODUCTION_ADMISSION_BLOCKED:{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
