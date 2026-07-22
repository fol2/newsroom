from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import stat
import subprocess

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
        runner_environment="github-hosted",
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


def _gate_run(*, result: str = "PASS", returncode: int | None = 0) -> dict[str, object]:
    reason = (
        "PASS:core-deterministic:tests"
        if result == "PASS"
        else f"FAIL:core-deterministic:tests:exit={returncode}"
    )
    return {
        "schema_version": "newsroom.sdlc.gate-run.v1",
        "gate_id": "core-deterministic",
        "phase": "tests",
        "result": result,
        "result_reason": reason,
        "returncode": returncode,
        "execution_ms": 321,
        "stdout": "",
        "stderr": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
    }


def _command_run(*, result: str = "PASS", returncode: int | None = 0) -> dict[str, object]:
    return {
        "schema_version": "newsroom.sdlc.command-run.v1",
        "command_spec_digest": "sha256:" + "1" * 64,
        "gate_run": _gate_run(result=result, returncode=returncode),
    }


def _junit(raw_digest: str) -> dict[str, object]:
    return {
        "schema_version": "newsroom.sdlc.junit-summary.v1",
        "outcome": "PASS",
        "reports": [{"path": "results.xml", "digest": raw_digest}],
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
    record: dict[str, object] = {
        "schema_version": "newsroom.sdlc.evidence.v1",
        "evidence_identity": "",
        "gate_id": "core-deterministic",
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
        "result": "PASS",
        "result_reason": "PASS:core-deterministic:tests",
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
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_bytes(canonical_json_bytes(value) + b"\n")


def _artifact(
    repo: Path,
    contract: SdlcContract,
    producer: GithubRunContext,
) -> tuple[Path, dict[str, object]]:
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
    _write_json(root, "route.json", route)
    _write_json(root, "command.json", command)
    _write_json(root, "junit.json", junit)
    _write_json(root, "evidence.json", evidence)
    (root / "results.xml").write_bytes(raw)
    envelope = create_envelope(
        repo_root=repo,
        artifact_root=root,
        context=producer,
        files=(
            ("route", "route.json"),
            ("command_run", "command.json"),
            ("junit_summary", "junit.json"),
            ("gate_evidence", "evidence.json"),
        ),
    )
    _write_json(root, "envelope.json", envelope.as_dict())
    return root, envelope.as_dict()


def _metadata(envelope: dict[str, object]) -> dict[str, object]:
    context = envelope["context"]
    assert isinstance(context, dict)
    artifact_id = 99123
    return {
        "id": artifact_id,
        "name": envelope["artifact_name"],
        "size_in_bytes": 4096,
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
        "digest": "sha256:" + "5" * 64,
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
    dict[str, object],
]:
    repo, head, tree = _repository(tmp_path)
    contract = _contract(repo)
    producer = _context(head, tree, job="core")
    consumer = _context(head, tree, job="decision")
    artifact_root, envelope = _artifact(repo, contract, producer)
    return repo, contract, producer, consumer, artifact_root, _metadata(envelope)


def test_full_artifact_receipt_reconciles_outer_inner_and_raw_evidence(
    tmp_path: Path,
) -> None:
    repo, contract, producer, consumer, artifact_root, metadata = _fixture(tmp_path)

    receipt = verify_artifact(
        repo_root=repo,
        artifact_root=artifact_root,
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
    assert len(receipt.entry_digests) == 4
    assert len(receipt.raw_reports) == 1
    assert receipt.raw_reports[0].path == "results.xml"
    assert validate_receipt(receipt.as_dict()) == receipt


def test_metadata_rejects_wrong_name_run_repo_head_url_expiry_or_digest(
    tmp_path: Path,
) -> None:
    repo, contract, _, consumer, artifact_root, metadata = _fixture(tmp_path)
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
    repo, contract, producer, consumer, artifact_root, metadata = _fixture(tmp_path)
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
            metadata_value=metadata,
            decision_context=producer,
            expected_job_id="core",
            contract=contract,
            now=NOW,
        )


def test_entry_raw_report_and_extra_file_tampering_fail_closed(tmp_path: Path) -> None:
    repo, contract, _, consumer, artifact_root, metadata = _fixture(tmp_path)
    cases = (
        ("command.json", b"{}\n", "entry_digest"),
        ("results.xml", b"changed\n", "raw_report_digest"),
    )
    for name, replacement, reason in cases:
        original = (artifact_root / name).read_bytes()
        (artifact_root / name).write_bytes(replacement)
        with pytest.raises(ArtifactReceiptError, match=reason):
            verify_artifact(
                repo_root=repo,
                artifact_root=artifact_root,
                metadata_value=metadata,
                decision_context=consumer,
                expected_job_id="core",
                contract=contract,
                now=NOW,
            )
        (artifact_root / name).write_bytes(original)

    (artifact_root / "extra.txt").write_text("unlisted", encoding="utf-8")
    with pytest.raises(ArtifactReceiptError, match="artifact_extra_files"):
        verify_artifact(
            repo_root=repo,
            artifact_root=artifact_root,
            metadata_value=metadata,
            decision_context=consumer,
            expected_job_id="core",
            contract=contract,
            now=NOW,
        )


def test_gate_input_result_and_junit_pairing_tampering_fail_closed(
    tmp_path: Path,
) -> None:
    repo, contract, _, consumer, artifact_root, metadata = _fixture(tmp_path)
    evidence_path = artifact_root / "evidence.json"
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
    _rewrite_envelope_entry(artifact_root, "evidence.json")
    with pytest.raises(ArtifactReceiptError, match="gate_inputs_digest"):
        verify_artifact(
            repo_root=repo,
            artifact_root=artifact_root,
            metadata_value=metadata,
            decision_context=consumer,
            expected_job_id="core",
            contract=contract,
            now=NOW,
        )

    artifact_root, _ = _artifact(repo, contract, _context(consumer.evaluated_sha, consumer.evaluated_tree_sha, job="core"))
    metadata = _metadata(json.loads((artifact_root / "envelope.json").read_text(encoding="utf-8")))
    junit_path = artifact_root / "junit.json"
    junit = json.loads(junit_path.read_text(encoding="utf-8"))
    junit["test_count"] = 2
    junit_path.write_bytes(canonical_json_bytes(junit) + b"\n")
    _rewrite_envelope_entry(artifact_root, "junit.json")
    with pytest.raises(ArtifactReceiptError, match="junit_pairing"):
        verify_artifact(
            repo_root=repo,
            artifact_root=artifact_root,
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
    repo, contract, _, consumer, artifact_root, metadata = _fixture(tmp_path)
    receipt = verify_artifact(
        repo_root=repo,
        artifact_root=artifact_root,
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
    repo, contract, _, consumer, artifact_root, metadata = _fixture(tmp_path)
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    monkeypatch.setattr(receipt_module, "context_from_environment", lambda _root: consumer)
    monkeypatch.setattr(receipt_module, "load_contract", lambda _root: contract)
    arguments = (
        "--repo-root",
        str(repo),
        "--artifact-root",
        str(artifact_root.relative_to(repo)),
        "--metadata",
        str(metadata_path),
        "--expected-job",
        "core",
        "--output",
        "receipt.json",
    )

    assert receipt_main(arguments) == 0
    output = repo / "receipt.json"
    receipt = validate_receipt(json.loads(output.read_text(encoding="utf-8")))
    assert receipt.producer_job_id == "core"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert capsys.readouterr().err == ""

    original = output.read_bytes()
    assert receipt_main(arguments) == 2
    assert output.read_bytes() == original
    assert capsys.readouterr().err.strip() == (
        "EVIDENCE_MISMATCH:artifact-receipt:output_exists"
    )
