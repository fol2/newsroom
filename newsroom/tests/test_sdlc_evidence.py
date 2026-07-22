from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import stat
import subprocess

from jsonschema import Draft202012Validator, FormatChecker
import pytest

from scripts.sdlc.classify_change import resolve_commit, resolve_tree
from scripts.sdlc.contracts import SdlcContract, load_contract
from scripts.sdlc.emit_evidence import (
    EvidenceError,
    build_gate_evidence,
    canonical_json_bytes,
    main as evidence_main,
    sha256_identity,
    validate_evidence_record,
)


REPO_ROOT = Path(__file__).parents[2]
COMMAND_DIGEST = "sha256:" + "a" * 64
SERVICE_DIGEST = "sha256:" + "b" * 64
REPORT_DIGEST = "sha256:" + "c" * 64
TEST_IDS_DIGEST = "sha256:" + "d" * 64
FAILURE_DIGEST = "sha256:" + "e" * 64
_MISSING = object()


def _git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _copy_contract(root: Path) -> None:
    paths = (
        ".sdlc/gates.toml",
        ".sdlc/evidence.schema.json",
        ".sdlc/route.schema.json",
        "docs/specs/sdlc/high-performance-evidence-sdlc.md",
        "docs/specs/sdlc/2026-07-22-sdlc-v2-owner-acceptance.md",
    )
    for relative in paths:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / relative, target)


def _repository(tmp_path: Path) -> tuple[SdlcContract, str, str]:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "SDLC Test")
    _copy_contract(tmp_path)
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "fixture")
    head = resolve_commit(tmp_path, "HEAD")
    tree = resolve_tree(tmp_path, head)
    return load_contract(tmp_path), head, tree


def _route(
    contract: SdlcContract,
    head: str,
    tree: str,
    *,
    risk_tier: str = "R0_DOCUMENTATION",
) -> dict[str, object]:
    service_required = contract.service_required(risk_tier)
    core_tests = ["newsroom/tests"]
    service_tests = (
        ["newsroom/tests/test_projection_b2_neo4j_service.py"]
        if service_required
        else []
    )
    sentinels = list(contract.sentinels)
    manifest_digest = sha256_identity(
        {
            "core_tests": core_tests,
            "service_tests": service_tests,
            "sentinels": sentinels,
        }
    )
    return {
        "schema_version": "newsroom.sdlc.route.v1",
        "contract_version": contract.contract_version,
        "base_sha": head,
        "head_sha": head,
        "base_tree_sha": tree,
        "head_tree_sha": tree,
        "risk_tier": risk_tier,
        "reasons": ["no_changes"],
        "core_required": True,
        "service_required": service_required,
        "clustering_required": False,
        "owner_authority_required": contract.owner_authority_required(risk_tier),
        "core_tests": core_tests,
        "service_tests": service_tests,
        "sentinels": sentinels,
        "selected_test_manifest_digest": manifest_digest,
    }


def _gate_run(
    gate_id: str = "core-deterministic",
    *,
    result: str = "PASS",
) -> dict[str, object]:
    returncode = 0 if result == "PASS" else 7 if result == "FAIL" else None
    reason = (
        f"PASS:{gate_id}:tests"
        if result == "PASS"
        else f"FAIL:{gate_id}:tests:exit=7"
        if result == "FAIL"
        else f"{result}:{gate_id}:tests"
    )
    return {
        "schema_version": "newsroom.sdlc.gate-run.v1",
        "gate_id": gate_id,
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


def _junit(*, required_skip: bool = False) -> dict[str, object]:
    return {
        "schema_version": "newsroom.sdlc.junit-summary.v1",
        "outcome": "FAIL" if required_skip else "PASS",
        "reports": [{"path": "results.xml", "digest": REPORT_DIGEST}],
        "test_ids_digest": TEST_IDS_DIGEST,
        "test_count": 3,
        "failure_count": 0,
        "error_count": 0,
        "skip_count": 1 if required_skip else 0,
        "required_skip_count": 1 if required_skip else 0,
        "duration_ms": 42,
        "first_failure_fingerprint": FAILURE_DIGEST if required_skip else None,
    }


def _build(
    contract: SdlcContract,
    route: dict[str, object],
    *,
    gate_run: dict[str, object] | None = None,
    junit: object = _MISSING,
    command_digest: str = COMMAND_DIGEST,
    service_digest: str | None = None,
    queue_ms: int = 1,
    bootstrap_ms: int = 2,
    finalize_ms: int = 3,
    created_at: str = "2026-07-22T07:30:00Z",
) -> dict[str, object]:
    run = gate_run or _gate_run()
    if junit is _MISSING:
        selected_junit: object | None = (
            _junit() if run["result"] == "PASS" else None
        )
    else:
        selected_junit = junit
    return build_gate_evidence(
        repo_root=contract.repo_root,
        contract=contract,
        route=route,
        gate_run=run,
        junit_summary=selected_junit,
        runner_kind="github-hosted",
        queue_ms=queue_ms,
        bootstrap_ms=bootstrap_ms,
        finalize_ms=finalize_ms,
        cache_key=None,
        cache_hit=False,
        uv_version="0.8.0",
        command_spec_digest=command_digest,
        service_compatibility_digest=service_digest,
        created_at=created_at,
    )


def test_canonical_json_has_a_fixed_no_float_vector() -> None:
    value = {"b": ["x", None, True], "a": 1}

    assert canonical_json_bytes(value) == b'{"a":1,"b":["x",null,true]}'
    assert sha256_identity(value) == (
        "sha256:f3b8a4ec6b2ad1666747731d5601847491e0ae81f0585f2b1edb8aa823e8f3ff"
    )
    with pytest.raises(EvidenceError, match="canonical_value_type"):
        canonical_json_bytes({"not_allowed": 1.5})


def test_pass_record_is_exact_schema_valid_and_omits_process_output(
    tmp_path: Path,
) -> None:
    contract, head, tree = _repository(tmp_path)
    record = _build(contract, _route(contract, head, tree))
    schema = json.loads(
        (REPO_ROOT / ".sdlc" / "evidence.schema.json").read_text(encoding="utf-8")
    )

    Draft202012Validator(schema, format_checker=FormatChecker()).validate(record)
    assert record["result"] == "PASS"
    assert record["evidence_identity"].startswith("sha256:")
    assert record["lockfile_digest"] == (
        "sha256:" + hashlib.sha256(b"version = 1\n").hexdigest()
    )
    assert record["selected_tests"] == ["newsroom/tests"]
    assert record["test_count"] == 3
    assert "stdout" not in record
    assert "stderr" not in record


def test_identity_ignores_observation_time_but_changes_with_command_inputs(
    tmp_path: Path,
) -> None:
    contract, head, tree = _repository(tmp_path)
    route = _route(contract, head, tree)
    first = _build(contract, route)
    different_timings = _build(
        contract,
        route,
        queue_ms=999,
        bootstrap_ms=888,
        finalize_ms=777,
        created_at="2026-07-22T08:00:00Z",
    )
    different_command = _build(
        contract,
        route,
        command_digest="sha256:" + "f" * 64,
    )

    assert first["evidence_identity"] == different_timings["evidence_identity"]
    assert first["gate_inputs_digest"] == different_timings["gate_inputs_digest"]
    assert first["evidence_identity"] != different_command["evidence_identity"]
    assert first["gate_inputs_digest"] != different_command["gate_inputs_digest"]


def test_required_skip_downgrades_process_pass_and_pass_tamper_is_rejected(
    tmp_path: Path,
) -> None:
    contract, head, tree = _repository(tmp_path)
    record = _build(
        contract,
        _route(contract, head, tree),
        junit=_junit(required_skip=True),
    )

    assert record["result"] == "FAIL"
    assert record["result_reason"] == "FAIL:core-deterministic:junit"
    assert record["required_skip_count"] == 1
    assert record["first_failure_fingerprint"] == FAILURE_DIGEST

    tampered = deepcopy(record)
    tampered["result"] = "PASS"
    tampered["result_reason"] = "PASS:core-deterministic:junit"
    with pytest.raises(EvidenceError, match="pass_invariant"):
        validate_evidence_record(tampered)


def test_route_manifest_and_identity_tamper_fail_closed(tmp_path: Path) -> None:
    contract, head, tree = _repository(tmp_path)
    route = _route(contract, head, tree)
    route["core_tests"] = ["newsroom/other-tests"]
    with pytest.raises(EvidenceError, match="route_selected_manifest_mismatch"):
        _build(contract, route)

    valid = _build(contract, _route(contract, head, tree))
    valid["gate_inputs_digest"] = "sha256:" + "0" * 64
    with pytest.raises(EvidenceError, match="evidence_identity_mismatch"):
        validate_evidence_record(valid)


def test_selected_gate_requires_junit_and_service_gate_requires_compatibility(
    tmp_path: Path,
) -> None:
    contract, head, tree = _repository(tmp_path)
    route = _route(contract, head, tree)
    with pytest.raises(EvidenceError, match="junit_required"):
        _build(contract, route, junit=None, gate_run=_gate_run())

    service_route = _route(
        contract,
        head,
        tree,
        risk_tier="R3_EXTERNAL_SERVICE_SECURITY",
    )
    service_run = _gate_run("service-neo4j")
    with pytest.raises(EvidenceError, match="service_compatibility_required"):
        _build(
            contract,
            service_route,
            gate_run=service_run,
            junit=_junit(),
        )
    service_record = _build(
        contract,
        service_route,
        gate_run=service_run,
        junit=_junit(),
        service_digest=SERVICE_DIGEST,
    )
    assert service_record["service_compatibility_digest"] == SERVICE_DIGEST

    with pytest.raises(EvidenceError, match="service_compatibility_unexpected"):
        _build(
            contract,
            route,
            service_digest=SERVICE_DIGEST,
        )


def test_gate_run_and_junit_internal_inconsistency_are_rejected(
    tmp_path: Path,
) -> None:
    contract, head, tree = _repository(tmp_path)
    route = _route(contract, head, tree)
    invalid_run = _gate_run()
    invalid_run["result_reason"] = "FAIL:core-deterministic:tests:exit=7"
    with pytest.raises(EvidenceError, match="gate_run_reason"):
        _build(contract, route, gate_run=invalid_run, junit=_junit())

    invalid_junit = _junit()
    invalid_junit["required_skip_count"] = 1
    with pytest.raises(EvidenceError, match="junit_required_skip_count"):
        _build(contract, route, junit=invalid_junit)


def test_exact_git_blob_wins_over_dirty_worktree_lockfile(tmp_path: Path) -> None:
    contract, head, tree = _repository(tmp_path)
    (tmp_path / "uv.lock").write_text("tampered = true\n", encoding="utf-8")

    record = _build(contract, _route(contract, head, tree))

    assert record["lockfile_digest"] == (
        "sha256:" + hashlib.sha256(b"version = 1\n").hexdigest()
    )
    assert record["lockfile_digest"] != (
        "sha256:" + hashlib.sha256(b"tampered = true\n").hexdigest()
    )


def test_head_or_base_tree_mismatch_is_rejected(tmp_path: Path) -> None:
    contract, head, tree = _repository(tmp_path)
    wrong_head = _route(contract, head, tree)
    wrong_head["head_sha"] = "0" * 40
    with pytest.raises(EvidenceError, match="head_mismatch"):
        _build(contract, wrong_head)

    wrong_tree = _route(contract, head, tree)
    wrong_tree["base_tree_sha"] = "1" * 40
    with pytest.raises(EvidenceError, match="base_tree_mismatch"):
        _build(contract, wrong_tree)


def test_cli_emits_private_schema_valid_record_and_never_overwrites(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    contract, head, tree = _repository(tmp_path)
    route = _route(contract, head, tree)
    inputs = {
        "route.json": route,
        "gate-run.json": _gate_run(),
        "junit.json": _junit(),
    }
    for name, value in inputs.items():
        (tmp_path / name).write_text(
            json.dumps(value, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

    arguments = (
        "--repo-root",
        str(tmp_path),
        "--route",
        "route.json",
        "--gate-run",
        "gate-run.json",
        "--junit-summary",
        "junit.json",
        "--runner-kind",
        "github-hosted",
        "--queue-ms",
        "1",
        "--bootstrap-ms",
        "2",
        "--finalize-ms",
        "3",
        "--uv-version",
        "0.8.0",
        "--command-spec-digest",
        COMMAND_DIGEST,
        "--created-at",
        "2026-07-22T07:30:00Z",
        "--output",
        "evidence.json",
    )
    assert evidence_main(arguments) == 0
    record = json.loads((tmp_path / "evidence.json").read_text(encoding="utf-8"))
    assert validate_evidence_record(record) == record
    assert stat.S_IMODE((tmp_path / "evidence.json").stat().st_mode) == 0o600
    assert capsys.readouterr().err == ""

    assert evidence_main(arguments) == 2
    assert "EVIDENCE_MISMATCH:gate:output_exists" in capsys.readouterr().err
