from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import zipfile

import pytest

import scripts.sdlc.artifact_receipt as receipt_module
from scripts.sdlc.artifact_envelope import (
    GithubRunContext,
    artifact_name,
    create_envelope,
)
from scripts.sdlc.artifact_receipt import (
    ArtifactReceiptError,
    main as receipt_main,
    validate_metadata,
    validate_receipt,
    verify_artifact,
)
from scripts.sdlc.classify_change import resolve_commit, resolve_tree
from scripts.sdlc.contracts import SdlcContract, load_contract
from scripts.sdlc.emit_evidence import canonical_json_bytes, sha256_identity


REPO_ROOT = Path(__file__).parents[2]
NOW = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)


def _git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "sdlc@example.invalid")
    _git(repo, "config", "user.name", "SDLC Test")
    (repo / "tracked.txt").write_text("exact\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "exact")
    head = resolve_commit(repo, "HEAD")
    return repo, head, resolve_tree(repo, head)


def _contract(repo: Path) -> SdlcContract:
    source = load_contract(REPO_ROOT)
    return SdlcContract(repo, source.source_path, source.data)


def _context(
    head: str,
    tree: str,
    *,
    job: str,
    run_id: int = 777,
    run_attempt: int = 2,
    workflow_sha: str = "a" * 40,
    runner_environment: str = "github-hosted",
) -> GithubRunContext:
    return GithubRunContext(
        repository="fol2/newsroom",
        repository_id=1153895518,
        head_repository="fol2/newsroom",
        head_repository_id=1153895518,
        run_id=run_id,
        run_attempt=run_attempt,
        job_id=job,
        workflow_ref="fol2/newsroom/.github/workflows/evidence.yml@refs/pull/10/merge",
        workflow_sha=workflow_sha,
        event_name="pull_request",
        event_sha="b" * 40,
        evaluated_sha=head,
        evaluated_tree_sha=tree,
        ref="refs/pull/10/merge",
        runner_environment=runner_environment,
    )


def _route(contract: SdlcContract, head: str, tree: str) -> dict[str, object]:
    manifest = {
        "core_tests": ["newsroom/tests"],
        "service_tests": [],
        "sentinels": list(contract.sentinels),
    }
    return {
        "schema_version": "newsroom.sdlc.route.v1",
        "contract_version": contract.contract_version,
        "base_sha": head,
        "head_sha": head,
        "base_tree_sha": tree,
        "head_tree_sha": tree,
        "risk_tier": "R1_LOCAL_CODE",
        "reasons": ["path:newsroom/example.py:local_code:R1_LOCAL_CODE"],
        "core_required": True,
        "service_required": False,
        "clustering_required": False,
        "owner_authority_required": False,
        "core_tests": manifest["core_tests"],
        "service_tests": manifest["service_tests"],
        "sentinels": manifest["sentinels"],
        "selected_test_manifest_digest": sha256_identity(manifest),
    }


def _gate_run(
    *,
    result: str = "PASS",
    returncode: int | None = 0,
    phase: str = "tests",
) -> dict[str, object]:
    reason = (
        f"PASS:core-deterministic:{phase}"
        if result == "PASS"
        else f"FAIL:core-deterministic:{phase}:exit={returncode}"
    )
    return {
        "schema_version": "newsroom.sdlc.gate-run.v1",
        "gate_id": "core-deterministic",
        "phase": phase,
        "result": result,
        "result_reason": reason,
        "returncode": returncode,
        "execution_ms": 321,
        "stdout": "",
        "stderr": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
    }


def _command_run(
    *,
    result: str = "PASS",
    returncode: int | None = 0,
    phase: str = "tests",
    digest_digit: str = "1",
) -> dict[str, object]:
    return {
        "schema_version": "newsroom.sdlc.command-run.v1",
        "command_spec_digest": "sha256:" + digest_digit * 64,
        "gate_run": _gate_run(
            result=result,
            returncode=returncode,
            phase=phase,
        ),
    }


def _junit(
    raw_digest: str,
    *,
    gate_id: str = "core-deterministic",
    phase: str = "tests",
) -> dict[str, object]:
    return {
        "schema_version": "newsroom.sdlc.junit-summary.v1",
        "outcome": "PASS",
        "reports": [
            {
                "path": f"gates/{gate_id}/{phase}/reports/results.xml",
                "digest": raw_digest,
            }
        ],
        "test_ids_digest": "sha256:" + "2" * 64,
        "test_count": 1,
        "failure_count": 0,
        "error_count": 0,
        "skip_count": 0,
        "required_skip_count": 0,
        "duration_ms": 1,
        "first_failure_fingerprint": None,
    }


def _gate_inputs(route: dict[str, object], command: dict[str, object]) -> str:
    gate_run = command["gate_run"]
    assert isinstance(gate_run, dict)
    return sha256_identity(
        {
            "command_spec_digest": command["command_spec_digest"],
            "gate_id": gate_run["gate_id"],
            "head_tree_sha": route["head_tree_sha"],
            "phase": gate_run["phase"],
            "route_digest": sha256_identity(route),
            "selected_test_manifest_digest": route[
                "selected_test_manifest_digest"
            ],
        }
    )


def _evidence(
    contract: SdlcContract,
    route: dict[str, object],
    command: dict[str, object],
) -> dict[str, object]:
    gate_run = command["gate_run"]
    assert isinstance(gate_run, dict)
    record: dict[str, object] = {
        "schema_version": "newsroom.sdlc.evidence.v1",
        "evidence_identity": "",
        "gate_id": gate_run["gate_id"],
        "gate_contract_version": contract.contract_version,
        "risk_classifier_version": contract.classifier_version,
        "repository": "fol2/newsroom",
        "base_sha": route["base_sha"],
        "head_sha": route["head_sha"],
        "base_tree_sha": route["base_tree_sha"],
        "tree_sha": route["head_tree_sha"],
        "risk_tier": route["risk_tier"],
        "risk_reasons": route["reasons"],
        "runner_kind": "github-hosted",
        "queue_ms": 1,
        "bootstrap_ms": 2,
        "execution_ms": 321,
        "finalize_ms": 3,
        "cache_key": None,
        "cache_hit": False,
        "python_version": "3.12.0",
        "uv_version": "0.8.0",
        "lockfile_digest": "sha256:" + "3" * 64,
        "toolchain_digest": "sha256:" + "4" * 64,
        "service_compatibility_digest": None,
        "selected_test_manifest_digest": route["selected_test_manifest_digest"],
        "gate_inputs_digest": _gate_inputs(route, command),
        "selected_tests": ["newsroom/tests"],
        "sentinel_tests": route["sentinels"],
        "random_sample_seed": None,
        "random_sample_tests": [],
        "test_count": 1,
        "failure_count": 0,
        "error_count": 0,
        "skip_count": 0,
        "required_skip_count": 0,
        "first_failure_fingerprint": None,
        "result": gate_run["result"],
        "result_reason": gate_run["result_reason"],
        "created_at": "2026-07-22T11:59:00Z",
    }
    record["evidence_identity"] = sha256_identity(
        {
            "repository_tree_sha": record["tree_sha"],
            "base_tree_sha": record["base_tree_sha"],
            "gate_contract_version": record["gate_contract_version"],
            "risk_classifier_version": record["risk_classifier_version"],
            "lockfile_digest": record["lockfile_digest"],
            "toolchain_digest": record["toolchain_digest"],
            "service_compatibility_digest": record[
                "service_compatibility_digest"
            ],
            "selected_test_manifest_digest": record[
                "selected_test_manifest_digest"
            ],
            "gate_inputs_digest": record["gate_inputs_digest"],
        }
    )
    return record


def _write_json(root: Path, name: str, value: dict[str, object]) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _write_archive(root: Path, archive_path: Path) -> None:
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            relative = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(2026, 7, 22, 12, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(info, path.read_bytes())


def _artifact(
    repo: Path,
    contract: SdlcContract,
    producer: GithubRunContext,
) -> tuple[Path, dict[str, object], Path]:
    root = repo / "artifact"
    raw = (
        b'<testsuite><testcase classname="tests.example" '
        b'name="works" time="0.001"/></testsuite>\n'
    )
    raw_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    route = _route(contract, producer.evaluated_sha, producer.evaluated_tree_sha)
    command = _command_run()
    junit = _junit(raw_digest)
    evidence = _evidence(contract, route, command)
    gate_root = "gates/core-deterministic/tests"
    command_path = f"{gate_root}/command-run.json"
    junit_path = f"{gate_root}/junit-summary.json"
    evidence_path = f"{gate_root}/gate-evidence.json"
    report_path = f"{gate_root}/reports/results.xml"
    _write_json(root, "route.json", route)
    _write_json(root, command_path, command)
    _write_json(root, junit_path, junit)
    _write_json(root, evidence_path, evidence)
    report = root / report_path
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_bytes(raw)
    envelope = create_envelope(
        repo_root=repo,
        artifact_root=root,
        context=producer,
        files=(
            ("route", "route.json"),
            ("command_run", command_path),
            ("junit_summary", junit_path),
            ("gate_evidence", evidence_path),
        ),
    )
    _write_json(root, "envelope.json", envelope.as_dict())
    archive_path = repo / "artifact.zip"
    _write_archive(root, archive_path)
    return root, envelope.as_dict(), archive_path


def _metadata(
    envelope: dict[str, object],
    archive_path: Path,
) -> dict[str, object]:
    context = envelope["context"]
    assert isinstance(context, dict)
    artifact_id = 99123
    archive_bytes = archive_path.read_bytes()
    return {
        "id": artifact_id,
        "name": envelope["artifact_name"],
        "size_in_bytes": len(archive_bytes),
        "url": (
            "https://api.github.com/repos/fol2/newsroom/actions/artifacts/"
            f"{artifact_id}"
        ),
        "archive_download_url": (
            "https://api.github.com/repos/fol2/newsroom/actions/artifacts/"
            f"{artifact_id}/zip"
        ),
        "expired": False,
        "created_at": "2026-07-22T11:58:00Z",
        "updated_at": "2026-07-22T11:59:00Z",
        "expires_at": "2026-08-21T11:58:00Z",
        "digest": "sha256:" + hashlib.sha256(archive_bytes).hexdigest(),
        "workflow_run": {
            "id": context["run_id"],
            "repository_id": context["repository_id"],
            "head_repository_id": context["head_repository_id"],
            "head_branch": "agent/example",
            "head_sha": context["evaluated_sha"],
        },
        "extra_future_api_field": "ignored",
    }


def _fixture(tmp_path: Path) -> tuple[
    Path,
    SdlcContract,
    GithubRunContext,
    GithubRunContext,
    Path,
    Path,
    dict[str, object],
]:
    repo, head, tree = _repository(tmp_path)
    contract = _contract(repo)
    producer = _context(head, tree, job="core", runner_environment="self-hosted")
    consumer = _context(head, tree, job="decision", runner_environment="github-hosted")
    artifact_root, envelope, archive_path = _artifact(repo, contract, producer)
    return (
        repo,
        contract,
        producer,
        consumer,
        artifact_root,
        archive_path,
        _metadata(envelope, archive_path),
    )


def test_full_artifact_receipt_reconciles_outer_inner_and_raw_evidence(
    tmp_path: Path,
) -> None:
    repo, contract, producer, consumer, artifact_root, archive_path, metadata = _fixture(tmp_path)

    receipt = verify_artifact(
        repo_root=repo,
        artifact_root=artifact_root,
        archive_path=archive_path,
        metadata_value=metadata,
        decision_context=consumer,
        expected_job_id="core",
        contract=contract,
        now=NOW,
    )

    assert receipt.metadata.artifact_id == 99123
    assert receipt.producer_job_id == producer.job_id
    assert receipt.consumer_job_id == consumer.job_id
    assert receipt.repository == "fol2/newsroom"
    assert receipt.repository_id == 1153895518
    assert receipt.head_repository == "fol2/newsroom"
    assert receipt.head_repository_id == 1153895518
    assert receipt.route.base_sha == producer.evaluated_sha
    assert receipt.route.base_tree_sha == producer.evaluated_tree_sha
    assert receipt.metadata.head_sha == producer.evaluated_sha
    assert receipt.metadata.head_sha != producer.event_sha
    assert receipt.ref == producer.ref
    assert receipt.producer_runner_environment == "self-hosted"
    assert receipt.consumer_runner_environment == "github-hosted"
    assert len(receipt.entry_digests) == 4
    assert receipt.route.contract_version == contract.contract_version
    assert receipt.route.risk_classifier_version == contract.classifier_version
    assert receipt.route.risk_tier == "R1_LOCAL_CODE"
    assert receipt.route.core_required is True
    assert receipt.route.service_required is False
    assert receipt.route.clustering_required is False
    assert receipt.route.owner_authority_required is False
    assert receipt.route.route_digest == sha256_identity(
        json.loads((artifact_root / "route.json").read_text(encoding="utf-8"))
    )
    assert len(receipt.raw_reports) == 1
    assert receipt.raw_reports[0].path == "gates/core-deterministic/tests/reports/results.xml"
    assert len(receipt.gate_decisions) == 1
    decision = receipt.gate_decisions[0]
    assert (decision.gate_id, decision.phase, decision.result) == (
        "core-deterministic",
        "tests",
        "PASS",
    )
    assert decision.execution_ms == 321
    assert decision.test_count == 1
    assert decision.command_spec_digest == "sha256:" + "1" * 64
    assert decision.evidence_identity == json.loads(
        (
            artifact_root
            / "gates/core-deterministic/tests/gate-evidence.json"
        ).read_text(encoding="utf-8")
    )["evidence_identity"]
    assert validate_receipt(receipt.as_dict(), contract=contract) == receipt


def test_metadata_rejects_wrong_name_run_repo_head_url_expiry_or_digest(
    tmp_path: Path,
) -> None:
    repo, contract, _, consumer, artifact_root, archive_path, metadata = _fixture(tmp_path)
    envelope = receipt_module._read_envelope(artifact_root)
    cases: list[tuple[tuple[str, ...], object, str]] = [
        (("name",), "wrong", "artifact_name"),
        (("workflow_run", "id"), 999, "artifact_workflow_identity"),
        (("workflow_run", "repository_id"), 999, "artifact_workflow_identity"),
        (("workflow_run", "head_repository_id"), 999, "artifact_workflow_identity"),
        (("workflow_run", "head_sha"), "0" * 40, "artifact_workflow_identity"),
        (("url",), "https://example.invalid", "artifact_url"),
        (("digest",), "not-a-digest", "artifact_digest"),
        (("expired",), True, "artifact_expired"),
        (("expires_at",), "2026-07-22T11:00:00Z", "artifact_time"),
    ]
    for path, value, reason in cases:
        changed = deepcopy(metadata)
        target = changed
        for part in path[:-1]:
            target = target[part]  # type: ignore[assignment,index]
        target[path[-1]] = value  # type: ignore[index]
        with pytest.raises(ArtifactReceiptError, match=reason):
            validate_metadata(
                changed,
                envelope=envelope,
                decision_context=consumer,
                now=NOW,
            )


def test_cross_attempt_head_workflow_or_job_context_fails_closed(tmp_path: Path) -> None:
    repo, contract, producer, consumer, artifact_root, archive_path, metadata = _fixture(tmp_path)
    variants = [
        _context(
            consumer.evaluated_sha,
            consumer.evaluated_tree_sha,
            job="decision",
            run_attempt=3,
        ),
        _context(
            consumer.evaluated_sha,
            consumer.evaluated_tree_sha,
            job="decision",
            workflow_sha="c" * 40,
        ),
    ]
    for changed_consumer in variants:
        with pytest.raises(ArtifactReceiptError, match="producer_context"):
            verify_artifact(
                repo_root=repo,
                artifact_root=artifact_root,
                archive_path=archive_path,
                metadata_value=metadata,
                decision_context=changed_consumer,
                expected_job_id="core",
                contract=contract,
                now=NOW,
            )

    with pytest.raises(ArtifactReceiptError, match="producer_job"):
        verify_artifact(
            repo_root=repo,
            artifact_root=artifact_root,
            archive_path=archive_path,
            metadata_value=metadata,
            decision_context=consumer,
            expected_job_id="service",
            contract=contract,
            now=NOW,
        )
    with pytest.raises(ArtifactReceiptError, match="producer_job"):
        verify_artifact(
            repo_root=repo,
            artifact_root=artifact_root,
            archive_path=archive_path,
            metadata_value=metadata,
            decision_context=producer,
            expected_job_id="core",
            contract=contract,
            now=NOW,
        )


def test_entry_raw_report_and_extra_file_tampering_fail_closed(tmp_path: Path) -> None:
    repo, contract, _, consumer, artifact_root, archive_path, metadata = _fixture(tmp_path)
    command_path = "gates/core-deterministic/tests/command-run.json"
    report_path = "gates/core-deterministic/tests/reports/results.xml"
    command_payload = (artifact_root / command_path).read_bytes()
    command_replacement = bytes([command_payload[0] ^ 1]) + command_payload[1:]
    cases = (
        (command_path, command_replacement, "entry_digest"),
        (report_path, b"changed\n", "raw_report_digest"),
    )
    for name, replacement, reason in cases:
        original = (artifact_root / name).read_bytes()
        (artifact_root / name).write_bytes(replacement)
        archive_path.unlink()
        _write_archive(artifact_root, archive_path)
        metadata = _metadata(
            json.loads((artifact_root / "envelope.json").read_text(encoding="utf-8")),
            archive_path,
        )
        with pytest.raises(ArtifactReceiptError, match=reason):
            verify_artifact(
                repo_root=repo,
                artifact_root=artifact_root,
                archive_path=archive_path,
                metadata_value=metadata,
                decision_context=consumer,
                expected_job_id="core",
                contract=contract,
                now=NOW,
            )
        (artifact_root / name).write_bytes(original)
        archive_path.unlink()
        _write_archive(artifact_root, archive_path)
        metadata = _metadata(
            json.loads((artifact_root / "envelope.json").read_text(encoding="utf-8")),
            archive_path,
        )

    (artifact_root / "extra.txt").write_text("unlisted", encoding="utf-8")
    archive_path.unlink()
    _write_archive(artifact_root, archive_path)
    metadata = _metadata(
        json.loads((artifact_root / "envelope.json").read_text(encoding="utf-8")),
        archive_path,
    )
    with pytest.raises(ArtifactReceiptError, match="artifact_extra_files"):
        verify_artifact(
            repo_root=repo,
            artifact_root=artifact_root,
            archive_path=archive_path,
            metadata_value=metadata,
            decision_context=consumer,
            expected_job_id="core",
            contract=contract,
            now=NOW,
        )


def test_gate_input_result_and_junit_pairing_tampering_fail_closed(
    tmp_path: Path,
) -> None:
    repo, contract, _, consumer, artifact_root, archive_path, metadata = _fixture(tmp_path)
    evidence_path = artifact_root / "gates/core-deterministic/tests/gate-evidence.json"
    original = json.loads(evidence_path.read_text(encoding="utf-8"))

    changed = deepcopy(original)
    changed["gate_inputs_digest"] = "sha256:" + "0" * 64
    changed["evidence_identity"] = sha256_identity(
        {
            "repository_tree_sha": changed["tree_sha"],
            "base_tree_sha": changed["base_tree_sha"],
            "gate_contract_version": changed["gate_contract_version"],
            "risk_classifier_version": changed["risk_classifier_version"],
            "lockfile_digest": changed["lockfile_digest"],
            "toolchain_digest": changed["toolchain_digest"],
            "service_compatibility_digest": changed[
                "service_compatibility_digest"
            ],
            "selected_test_manifest_digest": changed[
                "selected_test_manifest_digest"
            ],
            "gate_inputs_digest": changed["gate_inputs_digest"],
        }
    )
    evidence_path.write_bytes(canonical_json_bytes(changed) + b"\n")
    _rewrite_envelope_entry(artifact_root, "gates/core-deterministic/tests/gate-evidence.json")
    _write_archive(artifact_root, archive_path)
    metadata = _metadata(
        json.loads((artifact_root / "envelope.json").read_text(encoding="utf-8")),
        archive_path,
    )
    with pytest.raises(ArtifactReceiptError, match="gate_inputs_digest"):
        verify_artifact(
            repo_root=repo,
            artifact_root=artifact_root,
            archive_path=archive_path,
            metadata_value=metadata,
            decision_context=consumer,
            expected_job_id="core",
            contract=contract,
            now=NOW,
        )

    artifact_root, _, archive_path = _artifact(
        repo,
        contract,
        _context(consumer.evaluated_sha, consumer.evaluated_tree_sha, job="core"),
    )
    envelope_value = json.loads(
        (artifact_root / "envelope.json").read_text(encoding="utf-8")
    )
    metadata = _metadata(envelope_value, archive_path)
    junit_path = artifact_root / "gates/core-deterministic/tests/junit-summary.json"
    junit = json.loads(junit_path.read_text(encoding="utf-8"))
    junit["test_count"] = 2
    junit_path.write_bytes(canonical_json_bytes(junit) + b"\n")
    _rewrite_envelope_entry(artifact_root, "gates/core-deterministic/tests/junit-summary.json")
    archive_path.unlink()
    _write_archive(artifact_root, archive_path)
    metadata = _metadata(
        json.loads((artifact_root / "envelope.json").read_text(encoding="utf-8")),
        archive_path,
    )
    with pytest.raises(ArtifactReceiptError, match="junit_pairing"):
        verify_artifact(
            repo_root=repo,
            artifact_root=artifact_root,
            archive_path=archive_path,
            metadata_value=metadata,
            decision_context=consumer,
            expected_job_id="core",
            contract=contract,
            now=NOW,
        )


def test_execution_and_unknown_gate_mismatch_fail_closed(tmp_path: Path) -> None:
    repo, contract, _, consumer, artifact_root, archive_path, metadata = _fixture(
        tmp_path
    )
    evidence_relative = "gates/core-deterministic/tests/gate-evidence.json"
    evidence_path = artifact_root / evidence_relative
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["execution_ms"] = 322
    evidence_path.write_bytes(canonical_json_bytes(evidence) + b"\n")
    _rewrite_envelope_entry(artifact_root, evidence_relative)
    archive_path.unlink()
    _write_archive(artifact_root, archive_path)
    metadata = _metadata(
        json.loads((artifact_root / "envelope.json").read_text(encoding="utf-8")),
        archive_path,
    )
    with pytest.raises(ArtifactReceiptError, match="evidence_execution"):
        verify_artifact(
            repo_root=repo,
            artifact_root=artifact_root,
            archive_path=archive_path,
            metadata_value=metadata,
            decision_context=consumer,
            expected_job_id="core",
            contract=contract,
            now=NOW,
        )

    artifact_root, envelope, archive_path = _artifact(
        repo,
        contract,
        _context(consumer.evaluated_sha, consumer.evaluated_tree_sha, job="core"),
    )
    command_relative = "gates/core-deterministic/tests/command-run.json"
    command_path = artifact_root / command_relative
    command = json.loads(command_path.read_text(encoding="utf-8"))
    command["gate_run"]["gate_id"] = "unknown-gate"
    command["gate_run"]["result_reason"] = "PASS:unknown-gate:tests"
    command_path.write_bytes(canonical_json_bytes(command) + b"\n")
    _rewrite_envelope_entry(artifact_root, command_relative)
    archive_path.unlink()
    _write_archive(artifact_root, archive_path)
    metadata = _metadata(
        json.loads((artifact_root / "envelope.json").read_text(encoding="utf-8")),
        archive_path,
    )
    with pytest.raises(ArtifactReceiptError, match="gate_not_accepted"):
        verify_artifact(
            repo_root=repo,
            artifact_root=artifact_root,
            archive_path=archive_path,
            metadata_value=metadata,
            decision_context=consumer,
            expected_job_id="core",
            contract=contract,
            now=NOW,
        )


def _rewrite_envelope_entry(root: Path, path: str) -> None:
    envelope_path = root / "envelope.json"
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    payload = (root / path).read_bytes()
    for entry in envelope["entries"]:
        if entry["path"] == path:
            entry["size_bytes"] = len(payload)
            entry["digest"] = "sha256:" + hashlib.sha256(payload).hexdigest()
    identity_inputs = {
        "schema_version": envelope["schema_version"],
        "artifact_name": envelope["artifact_name"],
        "context": envelope["context"],
        "entries": envelope["entries"],
    }
    envelope["envelope_identity"] = sha256_identity(identity_inputs)
    envelope_path.write_bytes(canonical_json_bytes(envelope) + b"\n")


def test_receipt_validator_rejects_identity_shape_and_order_tampering(
    tmp_path: Path,
) -> None:
    repo, contract, _, consumer, artifact_root, archive_path, metadata = _fixture(tmp_path)
    receipt = verify_artifact(
        repo_root=repo,
        artifact_root=artifact_root,
        archive_path=archive_path,
        metadata_value=metadata,
        decision_context=consumer,
        expected_job_id="core",
        contract=contract,
        now=NOW,
    ).as_dict()

    changed = deepcopy(receipt)
    changed["receipt_identity"] = "sha256:" + "0" * 64
    with pytest.raises(ArtifactReceiptError, match="receipt_identity"):
        validate_receipt(changed)

    changed = deepcopy(receipt)
    changed["metadata"]["unknown"] = True  # type: ignore[index]
    changed["receipt_identity"] = _receipt_identity(changed)
    with pytest.raises(ArtifactReceiptError, match="receipt_metadata"):
        validate_receipt(changed)

    changed = deepcopy(receipt)
    changed["entries"] = list(reversed(changed["entries"]))  # type: ignore[arg-type]
    changed["receipt_identity"] = _receipt_identity(changed)
    with pytest.raises(ArtifactReceiptError, match="receipt_entries"):
        validate_receipt(changed)


def _receipt_identity(value: dict[str, object]) -> str:
    return sha256_identity(
        {key: item for key, item in value.items() if key != "receipt_identity"}
    )


def test_cli_writes_private_non_overwriting_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, contract, _, consumer, artifact_root, archive_path, metadata = _fixture(tmp_path)
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    monkeypatch.setattr(receipt_module, "context_from_environment", lambda _root: consumer)
    monkeypatch.setattr(receipt_module, "load_contract", lambda _root: contract)
    arguments = (
        "--repo-root",
        str(repo),
        "--artifact-root",
        str(artifact_root.relative_to(repo)),
        "--archive",
        str(archive_path),
        "--metadata",
        str(metadata_path),
        "--expected-job",
        "core",
        "--output",
        "receipt.json",
    )

    assert receipt_main(arguments) == 0
    output = repo / "receipt.json"
    receipt = validate_receipt(
        json.loads(output.read_text(encoding="utf-8")),
        contract=contract,
    )
    assert receipt.producer_job_id == "core"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert capsys.readouterr().err == ""

    original = output.read_bytes()
    assert receipt_main(arguments) == 2
    assert output.read_bytes() == original
    assert capsys.readouterr().err.strip() == (
        "EVIDENCE_MISMATCH:artifact-receipt:output_exists"
    )



def test_metadata_uses_evaluated_head_and_rejects_future_api_time(
    tmp_path: Path,
) -> None:
    repo, contract, producer, consumer, artifact_root, archive_path, metadata = _fixture(
        tmp_path
    )
    envelope = receipt_module._read_envelope(artifact_root)

    assert metadata["workflow_run"]["head_sha"] == producer.evaluated_sha  # type: ignore[index]
    assert producer.event_sha != producer.evaluated_sha

    changed = deepcopy(metadata)
    changed["workflow_run"]["head_sha"] = producer.event_sha  # type: ignore[index]
    with pytest.raises(ArtifactReceiptError, match="artifact_workflow_identity"):
        validate_metadata(
            changed,
            envelope=envelope,
            decision_context=consumer,
            now=NOW,
        )

    changed = deepcopy(metadata)
    changed["updated_at"] = "2026-07-22T12:01:00Z"
    with pytest.raises(ArtifactReceiptError, match="artifact_time"):
        validate_metadata(
            changed,
            envelope=envelope,
            decision_context=consumer,
            now=NOW,
        )


def test_outer_archive_digest_size_zip_inventory_and_extraction_are_verified(
    tmp_path: Path,
) -> None:
    repo, contract, _, consumer, artifact_root, archive_path, metadata = _fixture(
        tmp_path
    )
    original_archive = archive_path.read_bytes()
    report_path = artifact_root / "gates/core-deterministic/tests/reports/results.xml"
    original_report = report_path.read_bytes()

    changed = deepcopy(metadata)
    changed["digest"] = "sha256:" + "0" * 64
    with pytest.raises(ArtifactReceiptError, match="archive_digest"):
        verify_artifact(
            repo_root=repo,
            artifact_root=artifact_root,
            archive_path=archive_path,
            metadata_value=changed,
            decision_context=consumer,
            expected_job_id="core",
            contract=contract,
            now=NOW,
        )

    changed = deepcopy(metadata)
    changed["size_in_bytes"] = int(changed["size_in_bytes"]) + 1
    with pytest.raises(ArtifactReceiptError, match="archive_size"):
        verify_artifact(
            repo_root=repo,
            artifact_root=artifact_root,
            archive_path=archive_path,
            metadata_value=changed,
            decision_context=consumer,
            expected_job_id="core",
            contract=contract,
            now=NOW,
        )

    archive_path.write_bytes(b"not-a-zip")
    changed = _metadata(
        json.loads((artifact_root / "envelope.json").read_text(encoding="utf-8")),
        archive_path,
    )
    with pytest.raises(ArtifactReceiptError, match="archive_zip"):
        verify_artifact(
            repo_root=repo,
            artifact_root=artifact_root,
            archive_path=archive_path,
            metadata_value=changed,
            decision_context=consumer,
            expected_job_id="core",
            contract=contract,
            now=NOW,
        )

    archive_path.write_bytes(original_archive)
    changed_report = bytearray(original_report)
    changed_report[-2] = ord("X") if changed_report[-2] != ord("X") else ord("Y")
    report_path.write_bytes(changed_report)
    with pytest.raises(ArtifactReceiptError, match="archive_extraction"):
        verify_artifact(
            repo_root=repo,
            artifact_root=artifact_root,
            archive_path=archive_path,
            metadata_value=metadata,
            decision_context=consumer,
            expected_job_id="core",
            contract=contract,
            now=NOW,
        )
    report_path.write_bytes(original_report)

    malicious = repo / "malicious.zip"
    with zipfile.ZipFile(malicious, "w") as archive:
        archive.writestr("../escape.json", b"{}")
    changed = _metadata(
        json.loads((artifact_root / "envelope.json").read_text(encoding="utf-8")),
        malicious,
    )
    with pytest.raises(ArtifactReceiptError, match="archive_member"):
        verify_artifact(
            repo_root=repo,
            artifact_root=artifact_root,
            archive_path=malicious,
            metadata_value=changed,
            decision_context=consumer,
            expected_job_id="core",
            contract=contract,
            now=NOW,
        )

    control = repo / "control.zip"
    with zipfile.ZipFile(control, "w") as archive:
        archive.writestr("bad\nname.json", b"{}")
    changed = _metadata(
        json.loads((artifact_root / "envelope.json").read_text(encoding="utf-8")),
        control,
    )
    with pytest.raises(ArtifactReceiptError, match="archive_member"):
        verify_artifact(
            repo_root=repo,
            artifact_root=artifact_root,
            archive_path=control,
            metadata_value=changed,
            decision_context=consumer,
            expected_job_id="core",
            contract=contract,
            now=NOW,
        )


def test_extracted_files_cannot_change_after_archive_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, contract, _, consumer, artifact_root, archive_path, metadata = _fixture(
        tmp_path
    )
    original_verify = receipt_module._verify_archive

    def mutate_after_verification(*args: object, **kwargs: object) -> object:
        entries = original_verify(*args, **kwargs)
        command_path = (
            artifact_root
            / "gates/core-deterministic/tests/command-run.json"
        )
        command = json.loads(command_path.read_text(encoding="utf-8"))
        command["gate_run"]["stdout"] = "changed-after-archive\n"
        command_path.write_bytes(canonical_json_bytes(command) + b"\n")
        _rewrite_envelope_entry(
            artifact_root,
            "gates/core-deterministic/tests/command-run.json",
        )
        return entries

    monkeypatch.setattr(receipt_module, "_verify_archive", mutate_after_verification)

    with pytest.raises(ArtifactReceiptError, match="archive_extraction"):
        verify_artifact(
            repo_root=repo,
            artifact_root=artifact_root,
            archive_path=archive_path,
            metadata_value=metadata,
            decision_context=consumer,
            expected_job_id="core",
            contract=contract,
            now=NOW,
        )


@pytest.mark.skipif(os.name != "posix", reason="symlink evidence is POSIX-specific")
def test_archive_symlink_is_rejected_before_open(tmp_path: Path) -> None:
    repo, contract, _, consumer, artifact_root, archive_path, metadata = _fixture(
        tmp_path
    )
    link = repo / "artifact-link.zip"
    link.symlink_to(archive_path)

    with pytest.raises(ArtifactReceiptError, match="archive_symlink"):
        verify_artifact(
            repo_root=repo,
            artifact_root=artifact_root,
            archive_path=link,
            metadata_value=metadata,
            decision_context=consumer,
            expected_job_id="core",
            contract=contract,
            now=NOW,
        )


def test_same_gate_multiple_phases_pair_by_content_bound_paths(tmp_path: Path) -> None:
    repo, head, tree = _repository(tmp_path)
    contract = _contract(repo)
    producer = _context(head, tree, job="core", runner_environment="self-hosted")
    consumer = _context(head, tree, job="decision")
    root = repo / "artifact"
    route = _route(contract, head, tree)
    _write_json(root, "route.json", route)
    files: list[tuple[str, str]] = [("route", "route.json")]

    for index, phase in enumerate(("compile", "tests"), start=1):
        raw = (
            b'<testsuite><testcase classname="tests.example" '
            b'name="works" time="0.001"/></testsuite>\n'
        )
        raw_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        result = "FAIL" if phase == "tests" else "PASS"
        returncode = 7 if result == "FAIL" else 0
        command = _command_run(
            result=result,
            returncode=returncode,
            phase=phase,
            digest_digit=str(index),
        )
        junit = _junit(raw_digest, phase=phase)
        evidence = _evidence(contract, route, command)
        prefix = f"gates/core-deterministic/{phase}"
        command_path = f"{prefix}/command-run.json"
        junit_path = f"{prefix}/junit-summary.json"
        evidence_path = f"{prefix}/gate-evidence.json"
        report_path = f"{prefix}/reports/results.xml"
        _write_json(root, command_path, command)
        _write_json(root, junit_path, junit)
        _write_json(root, evidence_path, evidence)
        report = root / report_path
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_bytes(raw)
        files.extend(
            (
                ("command_run", command_path),
                ("junit_summary", junit_path),
                ("gate_evidence", evidence_path),
            )
        )

    envelope = create_envelope(
        repo_root=repo,
        artifact_root=root,
        context=producer,
        files=files,
    )
    _write_json(root, "envelope.json", envelope.as_dict())
    archive_path = repo / "artifact.zip"
    _write_archive(root, archive_path)
    metadata = _metadata(envelope.as_dict(), archive_path)

    receipt = verify_artifact(
        repo_root=repo,
        artifact_root=root,
        archive_path=archive_path,
        metadata_value=metadata,
        decision_context=consumer,
        expected_job_id="core",
        contract=contract,
        now=NOW,
    )

    assert [role for role, _, _ in receipt.entry_digests].count("command_run") == 2
    assert [role for role, _, _ in receipt.entry_digests].count("gate_evidence") == 2
    assert len(receipt.raw_reports) == 2
    assert [
        (decision.phase, decision.result, decision.result_reason)
        for decision in receipt.gate_decisions
    ] == [
        ("compile", "PASS", "PASS:core-deterministic:compile"),
        ("tests", "FAIL", "FAIL:core-deterministic:tests:exit=7"),
    ]
    assert validate_receipt(receipt.as_dict(), contract=contract) == receipt


def test_receipt_validator_rejects_unknown_roles_missing_reports_and_runner_drift(
    tmp_path: Path,
) -> None:
    repo, contract, _, consumer, artifact_root, archive_path, metadata = _fixture(
        tmp_path
    )
    receipt = verify_artifact(
        repo_root=repo,
        artifact_root=artifact_root,
        archive_path=archive_path,
        metadata_value=metadata,
        decision_context=consumer,
        expected_job_id="core",
        contract=contract,
        now=NOW,
    ).as_dict()

    changed = deepcopy(receipt)
    for entry in changed["entries"]:  # type: ignore[index]
        if entry["role"] == "command_run":
            entry["role"] = "unknown"
            break
    changed["entries"] = sorted(  # type: ignore[index]
        changed["entries"], key=lambda item: (item["role"], item["path"])
    )
    changed["receipt_identity"] = _receipt_identity(changed)
    with pytest.raises(ArtifactReceiptError, match="receipt_entries"):
        validate_receipt(changed)

    changed = deepcopy(receipt)
    changed["raw_reports"] = []
    changed["receipt_identity"] = _receipt_identity(changed)
    with pytest.raises(ArtifactReceiptError, match="receipt_reports"):
        validate_receipt(changed)

    changed = deepcopy(receipt)
    changed["producer_runner_environment"] = "mystery"
    changed["receipt_identity"] = _receipt_identity(changed)
    with pytest.raises(ArtifactReceiptError, match="runner_environment"):
        validate_receipt(changed)

    changed = deepcopy(receipt)
    changed["route"]["service_required"] = True  # type: ignore[index]
    changed["receipt_identity"] = _receipt_identity(changed)
    with pytest.raises(ArtifactReceiptError, match="route_contract"):
        validate_receipt(changed, contract=contract)

    changed = deepcopy(receipt)
    del changed["route"]["route_digest"]  # type: ignore[index]
    changed["receipt_identity"] = _receipt_identity(changed)
    with pytest.raises(ArtifactReceiptError, match="receipt_route"):
        validate_receipt(changed, contract=contract)

    changed = deepcopy(receipt)
    changed["evaluated_sha"] = changed["event_sha"]
    changed["receipt_identity"] = _receipt_identity(changed)
    with pytest.raises(ArtifactReceiptError, match="receipt_metadata_identity"):
        validate_receipt(changed)

    changed = deepcopy(receipt)
    changed["gate_decisions"] = []
    changed["receipt_identity"] = _receipt_identity(changed)
    with pytest.raises(ArtifactReceiptError, match="receipt_decisions"):
        validate_receipt(changed)

    changed = deepcopy(receipt)
    decision = changed["gate_decisions"][0]  # type: ignore[index]
    decision["failure_count"] = 1
    decision["first_failure_fingerprint"] = "sha256:" + "f" * 64
    changed["receipt_identity"] = _receipt_identity(changed)
    with pytest.raises(ArtifactReceiptError, match="decision_pass"):
        validate_receipt(changed)

    changed = deepcopy(receipt)
    decision = changed["gate_decisions"][0]  # type: ignore[index]
    decision["test_count"] = 0
    changed["receipt_identity"] = _receipt_identity(changed)
    with pytest.raises(ArtifactReceiptError, match="receipt_decisions"):
        validate_receipt(changed)

    changed = deepcopy(receipt)
    decision = changed["gate_decisions"][0]  # type: ignore[index]
    decision["result_reason"] = "PASS:another-gate:tests"
    changed["receipt_identity"] = _receipt_identity(changed)
    with pytest.raises(ArtifactReceiptError, match="decision_result_reason"):
        validate_receipt(changed)

    changed = deepcopy(receipt)
    decision = changed["gate_decisions"][0]  # type: ignore[index]
    decision["result_reason"] = "PASS:core-deterministic:other-phase"
    changed["receipt_identity"] = _receipt_identity(changed)
    with pytest.raises(ArtifactReceiptError, match="decision_result_reason"):
        validate_receipt(changed)

    changed = deepcopy(receipt)
    decision = changed["gate_decisions"][0]  # type: ignore[index]
    decision["result"] = "FAIL"
    decision["result_reason"] = "FAIL:core-deterministic:tests:exit=0"
    changed["receipt_identity"] = _receipt_identity(changed)
    with pytest.raises(ArtifactReceiptError, match="decision_result_reason"):
        validate_receipt(changed)

    changed = deepcopy(receipt)
    old_gate = "core-deterministic"
    new_gate = "unknown-gate"
    for entry in changed["entries"]:  # type: ignore[index]
        entry["path"] = entry["path"].replace(
            f"gates/{old_gate}/", f"gates/{new_gate}/"
        )
    changed["entries"] = sorted(  # type: ignore[index]
        changed["entries"], key=lambda item: (item["role"], item["path"])
    )
    for report in changed["raw_reports"]:  # type: ignore[index]
        report["summary_path"] = report["summary_path"].replace(
            f"gates/{old_gate}/", f"gates/{new_gate}/"
        )
        report["path"] = report["path"].replace(
            f"gates/{old_gate}/", f"gates/{new_gate}/"
        )
    decision = changed["gate_decisions"][0]  # type: ignore[index]
    decision["gate_id"] = new_gate
    decision["result_reason"] = f"PASS:{new_gate}:tests"
    changed["receipt_identity"] = _receipt_identity(changed)
    with pytest.raises(ArtifactReceiptError, match="decision_gate_contract"):
        validate_receipt(changed, contract=contract)
