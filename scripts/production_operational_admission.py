"""Inspect, mint and verify production Operational Admission records.

The command performs Git and local-file reads only.  It never invokes a
provider, publication adapter or production writer.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from newsroom.production_admission import (
    AuthenticationKey,
    FreezeIdentity,
    GateAttestation,
    KeyClass,
    OwnerAdmissionInstruction,
    ProductionAdmissionError,
    ProductionEvidenceManifest,
    ProductionOperationalAdmission,
    ProductionReadinessReport,
    inspect_readiness,
    mint_production_operational_admission,
)


def _git(repo_root: Path, *arguments: str, check: bool = True) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if check and completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ProductionAdmissionError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout.strip()


def exact_main_freeze(repo_root: Path) -> FreezeIdentity:
    """Resolve one clean checkout whose HEAD is the exact local/remote main."""

    root = repo_root.resolve(strict=True)
    head = _git(root, "rev-parse", "--verify", "HEAD^{commit}")
    tree = _git(root, "rev-parse", "--verify", "HEAD^{tree}")
    main = _git(root, "rev-parse", "--verify", "refs/heads/main^{commit}")
    if head != main:
        raise ProductionAdmissionError("checkout HEAD is not exact main")
    remote_present = (
        subprocess.run(
            ("git", "show-ref", "--verify", "--quiet", "refs/remotes/origin/main"),
            cwd=root,
            check=False,
            capture_output=True,
            timeout=10,
        ).returncode
        == 0
    )
    if remote_present:
        remote = _git(
            root,
            "rev-parse",
            "--verify",
            "refs/remotes/origin/main^{commit}",
        )
        if head != remote:
            raise ProductionAdmissionError("checkout HEAD differs from origin/main")
    status = subprocess.run(
        (
            "git",
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ),
        cwd=root,
        check=False,
        capture_output=True,
        timeout=10,
    )
    if status.returncode != 0:
        raise ProductionAdmissionError("clean-checkout inspection failed")
    if status.stdout:
        raise ProductionAdmissionError("production admission requires a clean checkout")
    return FreezeIdentity(exact_main_sha=head, exact_main_tree=tree)


def _keyring(
    specifications: Sequence[str], *, key_class: KeyClass
) -> dict[str, AuthenticationKey]:
    keys: dict[str, AuthenticationKey] = {}
    for specification in specifications:
        if "=" not in specification:
            raise ProductionAdmissionError(
                "key specification must be KEY_ID=ENVIRONMENT_VARIABLE"
            )
        key_id, variable = specification.split("=", 1)
        if not key_id or not variable or key_id in keys:
            raise ProductionAdmissionError("key specification differs")
        encoded = os.environ.get(variable)
        if encoded is None:
            raise ProductionAdmissionError(f"key environment is absent: {variable}")
        try:
            secret = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ProductionAdmissionError(
                f"key environment is not canonical base64: {variable}"
            ) from exc
        keys[key_id] = AuthenticationKey(key_id, key_class, secret)
    return keys


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
    parser.add_argument("--evidence-key-env", action="append", default=[])


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
    evidence_keys = _keyring(
        arguments.evidence_key_env, key_class=KeyClass.EVIDENCE_AUTHORITY
    )
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
    manifest = _manifest(arguments.evidence_manifest)
    attestations = _attestations(arguments.attestation_directory)
    evidence_keys = _keyring(
        arguments.evidence_key_env, key_class=KeyClass.EVIDENCE_AUTHORITY
    )
    report = inspect_readiness(
        freeze=freeze,
        evidence_manifest=manifest,
        attestations=attestations,
        trusted_evidence_keys=evidence_keys,
    )
    _write_exclusive(arguments.output, report.canonical_bytes)
    print(f"readiness_report_digest={report.digest}")
    print(f"ready_for_admission={str(report.ready_for_admission).lower()}")
    return 0 if report.ready_for_admission else 2


def _mint(arguments: argparse.Namespace) -> int:
    freeze, manifest, attestations, evidence_keys, report = _load_current_report(
        arguments
    )
    instruction = OwnerAdmissionInstruction.from_canonical_bytes(
        arguments.owner_instruction.read_bytes()
    )
    owner_keys = _keyring(
        arguments.owner_key_env, key_class=KeyClass.HUMAN_ACCOUNTABLE_OWNER
    )
    production_keys = _keyring(
        arguments.production_key_env,
        key_class=KeyClass.PRODUCTION_OPERATIONAL_ADMISSION,
    )
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
    owner_keys = _keyring(
        arguments.owner_key_env, key_class=KeyClass.HUMAN_ACCOUNTABLE_OWNER
    )
    production_keys = _keyring(
        arguments.production_key_env,
        key_class=KeyClass.PRODUCTION_OPERATIONAL_ADMISSION,
    )
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
    inspect_parser.add_argument("--evidence-key-env", action="append", default=[])
    inspect_parser.add_argument("--output", required=True, type=Path)
    inspect_parser.set_defaults(handler=_inspect)

    mint_parser = subparsers.add_parser("mint")
    _add_evidence_arguments(mint_parser)
    mint_parser.add_argument("--readiness-report", required=True, type=Path)
    mint_parser.add_argument("--owner-instruction", required=True, type=Path)
    mint_parser.add_argument("--owner-key-env", action="append", default=[])
    mint_parser.add_argument("--production-key-env", action="append", default=[])
    mint_parser.add_argument("--output", required=True, type=Path)
    mint_parser.set_defaults(handler=_mint)

    verify_parser = subparsers.add_parser("verify")
    _add_evidence_arguments(verify_parser)
    verify_parser.add_argument("--readiness-report", required=True, type=Path)
    verify_parser.add_argument("--owner-instruction", required=True, type=Path)
    verify_parser.add_argument("--owner-key-env", action="append", default=[])
    verify_parser.add_argument("--production-key-env", action="append", default=[])
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
