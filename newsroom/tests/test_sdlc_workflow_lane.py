from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import os
import sys

import pytest

import scripts.sdlc.workflow_lane as lane_module
from scripts.sdlc.command_spec import CommandRun, parse_command_spec
from scripts.sdlc.contracts import SdlcContract, load_contract
from scripts.sdlc.junit_evidence import JUnitSummary
from scripts.sdlc.run_gate import GateRunResult, LaneDeadline
from scripts.sdlc.workflow_lane import (
    WorkflowLaneError,
    _execute,
    _run_core,
    _run_service,
    _static_environment,
    core_tests,
    service_compatibility_digest,
    source_check,
)


REPO_ROOT = Path(__file__).parents[2]


def _contract(root: Path = REPO_ROOT) -> SdlcContract:
    source = load_contract(REPO_ROOT)
    if root == REPO_ROOT:
        return source
    return SdlcContract(root, source.source_path, source.data)


def _route(*, service: bool = False, clustering: bool = False) -> dict[str, object]:
    return {
        "base_sha": "a" * 40,
        "head_sha": "b" * 40,
        "base_tree_sha": "c" * 40,
        "head_tree_sha": "d" * 40,
        "risk_tier": (
            "R3_EXTERNAL_SERVICE_SECURITY" if service else "R1_LOCAL_CODE"
        ),
        "reasons": ["path:test:R1_LOCAL_CODE"],
        "core_required": True,
        "service_required": service,
        "clustering_required": clustering,
        "owner_authority_required": False,
        "core_tests": ["newsroom/tests"],
        "service_tests": (
            [
                "newsroom/tests/test_integrated_c1_neo4j_service.py",
                "newsroom/tests/test_projection_b2_neo4j_service.py",
                "newsroom/tests/test_projection_b3_neo4j_service.py",
            ]
            if service
            else []
        ),
        "sentinels": ["workflow_gate_contract_integrity"],
        "selected_test_manifest_digest": "sha256:" + "1" * 64,
        "schema_version": "newsroom.sdlc.route.v1",
        "contract_version": "sdlc-v2.2",
    }


def _spec(contract: SdlcContract, gate_id: str, phase: str):
    value = {
        "schema_version": "newsroom.sdlc.command-spec.v1",
        "gate_id": gate_id,
        "phase": phase,
        "argv": [sys.executable, "-c", "print('ok')"],
        "cwd": ".",
        "static_env": {},
        "pass_env": [],
        "redact_env": [],
        "executable_digest": lane_module.executable_digest(sys.executable)[1],
        "output_limit_bytes": 65536,
        "termination_grace_ms": 500,
    }
    return parse_command_spec(value, contract=contract)


def _run(gate_id: str, phase: str, result: str = "PASS") -> CommandRun:
    reason = f"{result}:{gate_id}:{phase}"
    return CommandRun(
        "sha256:" + "2" * 64,
        GateRunResult(
            gate_id,
            phase,
            result,
            reason,
            0 if result == "PASS" else 1,
            10,
            "",
            "",
            False,
            False,
        ),
    )


def test_service_compatibility_digest_is_fixed() -> None:
    assert service_compatibility_digest() == (
        "sha256:54ea1c6f4b99a7318abd756506b031c97e30133fef65e9a457c66152401dcb2d"
    )


def test_execute_uses_the_caller_shared_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract(tmp_path)
    first = _spec(contract, "source-integrity", "source")
    second = _spec(contract, "core-deterministic", "tests")
    deadline = LaneDeadline(100, 55_000)
    observed: list[LaneDeadline] = []

    def run_configured_gate(**kwargs):
        observed.append(kwargs["deadline"])
        return GateRunResult(
            kwargs["gate_id"],
            kwargs["phase"],
            "PASS",
            f"PASS:{kwargs['gate_id']}:{kwargs['phase']}",
            0,
            1,
            "",
            "",
            False,
            False,
        )

    monkeypatch.setattr(lane_module, "run_configured_gate", run_configured_gate)
    _execute(contract=contract, spec=first, deadline=deadline)
    _execute(contract=contract, spec=second, deadline=deadline)

    assert observed == [deadline, deadline]


def test_core_lane_passes_one_deadline_to_both_gates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract(tmp_path)
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    deadline = LaneDeadline(200, 55_000)
    observed: list[LaneDeadline] = []
    specifications: list[dict[str, object]] = []

    monkeypatch.setattr(lane_module, "start_lane_deadline", lambda *_args: deadline)

    def capture_spec(**kwargs):
        specifications.append(kwargs)
        return SimpleNamespace(
            gate_id=kwargs["gate_id"], phase=kwargs["phase"]
        )

    monkeypatch.setattr(lane_module, "_spec", capture_spec)

    def execute(*, contract, spec, deadline):
        observed.append(deadline)
        return _run(spec.gate_id, spec.phase)

    monkeypatch.setattr(lane_module, "_execute", execute)
    monkeypatch.setattr(lane_module, "_report_summary", lambda **_kwargs: None)

    records = _run_core(
        root=tmp_path,
        artifact_root=artifact,
        contract=contract,
        route=_route(),
    )

    assert [(gate, phase) for gate, phase, *_ in records] == [
        ("source-integrity", "source"),
        ("core-deterministic", "tests"),
    ]
    assert observed == [deadline, deadline]
    source_spec = next(
        item for item in specifications if item["gate_id"] == "source-integrity"
    )
    core_spec = next(
        item for item in specifications if item["gate_id"] == "core-deterministic"
    )
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD" not in source_spec["static_env"]
    assert core_spec["static_env"]["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"


def test_static_environment_excludes_ambient_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-pass")
    monkeypatch.setenv("NEWSROOM_NEO4J_PROJECTOR_PASSWORD", "must-not-pass")
    environment = _static_environment()

    assert "GITHUB_TOKEN" not in environment
    assert "NEWSROOM_NEO4J_PROJECTOR_PASSWORD" not in environment
    assert environment["PYTHONHASHSEED"] == "0"
    assert environment["CI"] == "true"


def test_service_lane_requires_route_and_passes_only_projector_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract(tmp_path)
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    with pytest.raises(WorkflowLaneError, match="service_not_required"):
        _run_service(
            root=tmp_path,
            artifact_root=artifact,
            contract=contract,
            route=_route(),
        )

    artifact = tmp_path / "service"
    artifact.mkdir()
    captured = {}
    monkeypatch.setenv("NEWSROOM_NEO4J_PROJECTOR_PASSWORD", "secret")
    monkeypatch.setenv("NEWSROOM_NEO4J_COMPLETE_SERVICE_REQUIRED", "1")
    monkeypatch.setenv("NEWSROOM_NEO4J_INCREMENT_2D_SERVICE_REQUIRED", "1")
    monkeypatch.setenv("NEWSROOM_NEO4J_RETRIEVAL_SERVICE_REQUIRED", "1")
    monkeypatch.setenv("NEWSROOM_NEO4J_SERVICE_REQUIRED", "1")
    monkeypatch.setenv("NEWSROOM_NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEWSROOM_NEO4J_DATABASE", "neo4j")
    monkeypatch.setenv(
        "NEWSROOM_NEO4J_PROJECTOR_USERNAME", "newsroom_projector"
    )
    monkeypatch.setattr(
        lane_module,
        "_spec",
        lambda **kwargs: captured.setdefault("spec", kwargs) or SimpleNamespace(),
    )
    monkeypatch.setattr(
        lane_module, "start_lane_deadline", lambda *_args: LaneDeadline(1, 55_000)
    )
    monkeypatch.setattr(
        lane_module,
        "_execute",
        lambda **_kwargs: _run("service-neo4j", "tests"),
    )
    monkeypatch.setattr(lane_module, "_report_summary", lambda **_kwargs: None)

    records = _run_service(
        root=tmp_path,
        artifact_root=artifact,
        contract=contract,
        route=_route(service=True),
    )

    assert records[0][0:2] == ("service-neo4j", "tests")
    assert captured["spec"]["pass_env"] == (
        "NEWSROOM_NEO4J_PROJECTOR_PASSWORD",
    )
    static = captured["spec"]["static_env"]
    assert static["NEWSROOM_NEO4J_COMPLETE_SERVICE_REQUIRED"] == "1"
    assert static["NEWSROOM_NEO4J_INCREMENT_2D_SERVICE_REQUIRED"] == "1"
    assert static["NEWSROOM_NEO4J_RETRIEVAL_SERVICE_REQUIRED"] == "1"
    assert static["NEWSROOM_NEO4J_SERVICE_REQUIRED"] == "1"
    assert static["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert "NEWSROOM_NEO4J_PROJECTOR_PASSWORD" not in static
    argv = captured["spec"]["argv"]
    assert argv[:6] == [
        lane_module.shutil.which("uv"),
        "run",
        "--no-sync",
        "python",
        "-m",
        "scripts.sdlc.workflow_lane",
    ]
    assert argv[6:11] == [
        "service-tests",
        "--repo-root",
        ".",
        "--report",
        "service/gates/service-neo4j/tests/reports/pytest.xml",
    ]
    assert argv[11:] == _route(service=True)["service_tests"]


def test_source_check_compiles_exact_sources_and_runs_locked_integrity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "newsroom").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "newsroom/good.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "scripts/good.py").write_text("def ok():\n    return 1\n", encoding="utf-8")
    monkeypatch.setattr(lane_module, "load_contract", lambda _root: object())
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        lane_module,
        "_run_subprocess",
        lambda argv: commands.append(tuple(argv)) or 0,
    )

    assert source_check(
        repo_root=tmp_path, base_sha="a" * 40, head_sha="b" * 40
    ) == 0
    assert commands == [
        ("uv", "lock", "--check"),
        ("git", "diff", "--check", "a" * 40, "b" * 40, "--"),
    ]

    (tmp_path / "newsroom/bad.py").write_text("def broken(:\n", encoding="utf-8")
    with pytest.raises(SyntaxError):
        source_check(
            repo_root=tmp_path, base_sha="a" * 40, head_sha="b" * 40
        )


def test_core_test_command_runs_persistent_workers_and_conditional_clustering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = tmp_path / "report.xml"
    worker_calls: list[tuple[Path, Path]] = []
    clustering_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        lane_module,
        "_run_core_pytest_workers",
        lambda *, root, report: worker_calls.append((root, report)) or 0,
    )
    monkeypatch.setattr(
        lane_module,
        "_run_subprocess",
        lambda argv: clustering_calls.append(
            tuple(str(item) for item in argv)
        ) or 0,
    )

    assert core_tests(repo_root=tmp_path, report=report, clustering=True) == 0
    assert worker_calls == [(tmp_path.resolve(), report.resolve())]
    assert len(clustering_calls) == 1
    assert clustering_calls[0][1] == "scripts/eval_clustering_metrics.py"

    monkeypatch.setattr(
        lane_module,
        "_run_core_pytest_workers",
        lambda **_kwargs: 7,
    )
    clustering_calls.clear()
    assert core_tests(repo_root=tmp_path, report=report, clustering=True) == 7
    assert clustering_calls == []


def test_core_test_inventory_is_sorted_complete_and_rejects_symlinks(
    tmp_path: Path,
) -> None:
    test_root = tmp_path / "newsroom/tests"
    test_root.mkdir(parents=True)
    expected: list[str] = []
    for index in range(lane_module._CORE_WORKER_COUNT):
        path = test_root / f"test_{index}.py"
        path.write_text("def test_ok(): assert True\n", encoding="utf-8")
        expected.append(path.relative_to(tmp_path).as_posix())

    assert lane_module._core_test_files(tmp_path) == tuple(sorted(expected))

    if os.name != "posix":
        pytest.skip("symlink evidence is POSIX-specific")
    target = test_root / "outside.py"
    target.write_text("def test_outside(): assert True\n", encoding="utf-8")
    (test_root / "test_link.py").symlink_to(target)
    with pytest.raises(WorkflowLaneError, match="core_test_file"):
        lane_module._core_test_files(tmp_path)


def test_core_worker_command_is_pinned_persistent_and_file_scoped(
    tmp_path: Path,
) -> None:
    report = tmp_path / "report.xml"
    basetemp = tmp_path / "basetemp"
    command = lane_module._core_worker_command(
        report=report,
        basetemp=basetemp,
    )

    assert lane_module._CORE_WORKER_COUNT == 6
    assert lane_module._CORE_DISTRIBUTION == "loadfile"
    assert command[:13] == (
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--assert=plain",
        "-p",
        "no:cacheprovider",
        "-p",
        "xdist.plugin",
        "-n",
        "6",
        "--dist=loadfile",
        "--max-worker-restart=0",
    )
    assert command[13:14] == lane_module._CORE_TESTS == (
        "newsroom/tests",
    )
    assert command[-2:] == (
        f"--basetemp={basetemp}",
        f"--junitxml={report}",
    )


def test_persistent_core_dependency_is_exactly_pinned() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert pyproject.count('"pytest-xdist==3.8.0"') == 2


def test_service_shards_cover_exact_inventory_deterministically(
    tmp_path: Path,
) -> None:
    test_root = tmp_path / "newsroom/tests"
    test_root.mkdir(parents=True)
    expected: list[str] = []
    for index, size in enumerate((900, 800, 700, 600, 500, 400)):
        path = test_root / f"test_{index}_neo4j_service.py"
        path.write_text("#" * size + "\n", encoding="utf-8")
        expected.append(path.relative_to(tmp_path).as_posix())

    first = lane_module._service_test_shards(tmp_path, tuple(sorted(expected)))
    second = lane_module._service_test_shards(tmp_path, tuple(sorted(expected)))

    assert first == second
    assert len(first) == lane_module._SERVICE_SHARD_COUNT == 2
    assert all(first)
    flattened = tuple(item for shard in first for item in shard)
    assert len(flattened) == len(set(flattened))
    assert tuple(sorted(flattened)) == tuple(sorted(expected))


def test_service_shard_command_is_isolated_and_diagnostic(
    tmp_path: Path,
) -> None:
    report = tmp_path / "report.xml"
    basetemp = tmp_path / "basetemp"
    command = lane_module._service_shard_command(
        test_files=(
            "newsroom/tests/test_one_neo4j_service.py",
            "newsroom/tests/test_two_neo4j_service.py",
        ),
        report=report,
        basetemp=basetemp,
    )

    assert command[:7] == (
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--assert=plain",
        "-p",
        "no:cacheprovider",
    )
    assert command[7:9] == (
        "newsroom/tests/test_one_neo4j_service.py",
        "newsroom/tests/test_two_neo4j_service.py",
    )
    assert command[-2:] == (
        f"--basetemp={basetemp}",
        f"--junitxml={report}",
    )


def test_service_test_inventory_rejects_partial_topology(
    tmp_path: Path,
) -> None:
    test_root = tmp_path / "newsroom/tests"
    test_root.mkdir(parents=True)
    first = test_root / "test_first_neo4j_service.py"
    second = test_root / "test_second_neo4j_service.py"
    first.write_text("def test_first(): assert True\n", encoding="utf-8")
    second.write_text("def test_second(): assert True\n", encoding="utf-8")

    with pytest.raises(WorkflowLaneError, match="service_test_topology"):
        lane_module._service_test_files(
            tmp_path,
            (first.relative_to(tmp_path).as_posix(),),
        )


def _junit_case(name: str) -> str:
    return (
        '<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0">'
        f'<testcase classname="tests.shard" name="{name}" time="0.001"/>'
        "</testsuite></testsuites>"
    )


def test_persistent_core_runner_invokes_one_session_and_propagates_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_root = tmp_path / "newsroom/tests"
    test_root.mkdir(parents=True)
    for index in range(lane_module._CORE_WORKER_COUNT):
        (test_root / f"test_{index}.py").write_text(
            "def test_ok(): assert True\n",
            encoding="utf-8",
        )
    report = tmp_path / "pytest.xml"
    calls: list[tuple[tuple[str, ...], Path, bool]] = []

    def run(argv, *, cwd, check):
        calls.append((tuple(argv), cwd, check))
        return SimpleNamespace(returncode=9)

    monkeypatch.setattr(lane_module.subprocess, "run", run)

    assert lane_module._run_core_pytest_workers(
        root=tmp_path,
        report=report,
    ) == 9
    assert len(calls) == 1
    command, cwd, check = calls[0]
    assert cwd == tmp_path
    assert check is False
    assert command.count("xdist.plugin") == 1
    assert "--dist=loadfile" in command
    assert "--max-worker-restart=0" in command


def test_parallel_service_runner_merges_all_shards_and_propagates_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = tmp_path / "pytest.xml"
    shards = (
        ("newsroom/tests/test_service_a.py",),
        ("newsroom/tests/test_service_b.py",),
    )
    monkeypatch.setattr(
        lane_module,
        "_service_test_shards",
        lambda _root, _paths: shards,
    )

    def fake_run(*, argv, root, log):
        assert root == tmp_path
        report_argument = next(
            item for item in argv if str(item).startswith("--junitxml=")
        )
        shard_report = Path(str(report_argument).split("=", 1)[1])
        index = int(shard_report.stem.rsplit("-", 1)[1])
        shard_report.write_text(
            _junit_case(f"service_{index}"), encoding="utf-8"
        )
        log.write_text(f"service shard {index}\n", encoding="utf-8")
        return 7 if index == 1 else 0

    monkeypatch.setattr(lane_module, "_run_pytest_shard", fake_run)

    assert lane_module._run_service_pytest_shards(
        root=tmp_path,
        report=report,
        test_paths=("ignored-a", "ignored-b"),
    ) == 7
    assert lane_module.summarize_junit(
        tmp_path, (report.name,)
    ).test_count == 2
    assert not tuple(tmp_path.glob("pytest-shard-*.xml"))


def test_optional_core_skips_are_exact_actual_service_cases() -> None:
    expected = (
        'newsroom.tests.test_complete_projection_2b_neo4j_service::test_actual_service_complete_generation_queries_and_promotes_exact_state',
        'newsroom.tests.test_complete_projection_2b_neo4j_service::test_actual_service_partial_or_contract_mismatched_state_fails_closed[deleted-document]',
        'newsroom.tests.test_complete_projection_2b_neo4j_service::test_actual_service_partial_or_contract_mismatched_state_fails_closed[missing-vector-index]',
        'newsroom.tests.test_complete_projection_2b_neo4j_service::test_actual_service_partial_or_contract_mismatched_state_fails_closed[wrong-fulltext-analyzer]',
        'newsroom.tests.test_complete_projection_2b_neo4j_service::test_actual_service_partial_or_contract_mismatched_state_fails_closed[wrong-vector-dimensions]',
        'newsroom.tests.test_complete_projection_2b_neo4j_service::test_actual_service_replacement_generation_recovers_from_authority_only',
        'newsroom.tests.test_complete_projection_2b_neo4j_service::test_actual_service_revocation_and_tombstone_remove_current_derivatives',
        'newsroom.tests.test_complete_projection_2b_neo4j_service::test_actual_service_wrong_watermark_generation_and_vector_dimension_fail_closed',
        'newsroom.tests.test_increment_2d_neo4j_service::test_actual_service_complete_increment_2_proof_admits_replays_and_restarts',
        'newsroom.tests.test_increment_2d_neo4j_service::test_actual_service_complete_proof_fails_closed_when_required_surface_is_lost[fulltext]',
        'newsroom.tests.test_increment_2d_neo4j_service::test_actual_service_complete_proof_fails_closed_when_required_surface_is_lost[relation]',
        'newsroom.tests.test_increment_2d_neo4j_service::test_actual_service_complete_proof_fails_closed_when_required_surface_is_lost[vector]',
        'newsroom.tests.test_increment_2d_neo4j_service::test_actual_service_dead_letter_blocks_complete_candidate_proof',
        'newsroom.tests.test_increment_2d_neo4j_service::test_actual_service_governed_deletion_purges_derivative_and_never_requalifies',
        'newsroom.tests.test_increment_2d_neo4j_service::test_actual_service_relation_revocation_changes_later_context_without_rewrite',
        'newsroom.tests.test_increment_2d_neo4j_service::test_actual_service_replacement_generation_deduplicates_candidate_authority',
        'newsroom.tests.test_increment_2d_neo4j_service::test_actual_service_required_gap_blocks_complete_candidate_proof',
        'newsroom.tests.test_integrated_c1_neo4j_service::test_actual_service_integrated_foundation_replay_recovery_and_tombstone',
        'newsroom.tests.test_projection_b2_neo4j_service::test_actual_service_private_adapter_exact_duplicate_and_digest_conflict',
        'newsroom.tests.test_projection_b2_neo4j_service::test_actual_service_public_round_trip_duplicate_and_generation_isolation',
        'newsroom.tests.test_projection_b2_neo4j_service::test_actual_service_requires_explicit_authentication_configuration',
        'newsroom.tests.test_projection_b2_neo4j_service::test_actual_service_wrong_projector_credential_fails_closed_without_secret',
        'newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_3e_projects_complete_lineage_and_recovers_graph_loss',
        'newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_3e_replacement_generation_becomes_only_active_lineage',
        'newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_active_generation_revalidates_after_incremental_delivery',
        'newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_active_read_resolves_only_authority_promoted_generation',
        'newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_graph_loss_and_process_restart_rebuild_from_authority',
        'newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_promotion_rejects_graph_loss_after_validation',
        'newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_rebuild_cleanup_cannot_cross_generation_namespace',
        'newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_tombstone_does_not_resurrect_after_wipe_rebuild',
        'newsroom.tests.test_retrieval_2c_neo4j_service::test_actual_service_executes_all_four_branches_and_hydrates_authority',
        'newsroom.tests.test_retrieval_2c_neo4j_service::test_actual_service_missing_admitted_relation_is_incomplete_not_no_match',
        'newsroom.tests.test_retrieval_2c_neo4j_service::test_actual_service_missing_fulltext_index_is_unavailable_not_no_match',
        'newsroom.tests.test_retrieval_2c_neo4j_service::test_actual_service_missing_vector_index_is_unavailable_not_no_match',
    )
    assert lane_module._OPTIONAL_CORE_TEST_IDS == expected
    assert lane_module._OPTIONAL_CORE_TEST_IDS == tuple(sorted(expected))


def test_evidence_uses_zero_producer_timing_and_service_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract(tmp_path)
    captured = {}
    monkeypatch.setattr(lane_module, "installed_uv_version", lambda: "0.8.0")
    monkeypatch.setattr(
        lane_module,
        "build_gate_evidence",
        lambda **kwargs: captured.update(kwargs) or {"result": "PASS"},
    )
    run = _run("service-neo4j", "tests")
    summary = JUnitSummary(
        "PASS",
        (("report.xml", "sha256:" + "3" * 64),),
        "sha256:" + "4" * 64,
        1,
        0,
        0,
        0,
        0,
        1,
        None,
    )

    lane_module._evidence(
        repo_root=tmp_path,
        contract=contract,
        route=_route(service=True),
        command_run=run.as_dict(),
        summary=summary,
        runner_kind="github-hosted",
        service_digest=service_compatibility_digest(),
    )

    assert captured["queue_ms"] == 0
    assert captured["bootstrap_ms"] == 0
    assert captured["finalize_ms"] == 0
    assert captured["cache_key"] is None
    assert captured["cache_hit"] is False
    assert captured["service_compatibility_digest"] == service_compatibility_digest()


def test_main_returns_typed_error_for_invalid_lane(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert lane_module.main(
        (
            "execute",
            "--repo-root",
            str(tmp_path),
            "--route",
            "missing.json",
            "--lane",
            "core",
            "--artifact-root",
            "artifact",
        )
    ) == 2
    assert capsys.readouterr().err.startswith("EVIDENCE_MISMATCH:workflow-lane:")



def test_route_loader_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    route = tmp_path / "route.json"
    route.write_text('{"schema_version":"x","schema_version":"y"}', encoding="utf-8")
    with pytest.raises(WorkflowLaneError, match="input_json"):
        lane_module._load_json(tmp_path, route)


def test_service_configuration_is_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract(tmp_path)
    artifact = tmp_path / "artifact-exact"
    artifact.mkdir()
    monkeypatch.setenv("NEWSROOM_NEO4J_COMPLETE_SERVICE_REQUIRED", "1")
    monkeypatch.setenv("NEWSROOM_NEO4J_INCREMENT_2D_SERVICE_REQUIRED", "1")
    monkeypatch.setenv("NEWSROOM_NEO4J_RETRIEVAL_SERVICE_REQUIRED", "1")
    monkeypatch.setenv("NEWSROOM_NEO4J_SERVICE_REQUIRED", "1")
    monkeypatch.setenv("NEWSROOM_NEO4J_URI", "bolt://remote.example:7687")
    monkeypatch.setenv("NEWSROOM_NEO4J_DATABASE", "neo4j")
    monkeypatch.setenv("NEWSROOM_NEO4J_PROJECTOR_USERNAME", "newsroom_projector")
    with pytest.raises(WorkflowLaneError, match="service_configuration"):
        _run_service(
            root=tmp_path,
            artifact_root=artifact,
            contract=contract,
            route=_route(service=True),
        )


def test_evidence_runner_kind_is_not_hard_coded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract(tmp_path)
    captured = {}
    monkeypatch.setattr(lane_module, "installed_uv_version", lambda: "0.8.0")
    monkeypatch.setattr(
        lane_module,
        "build_gate_evidence",
        lambda **kwargs: captured.update(kwargs) or {"result": "PASS"},
    )
    lane_module._evidence(
        repo_root=tmp_path,
        contract=contract,
        route=_route(),
        command_run=_run("source-integrity", "source").as_dict(),
        summary=None,
        runner_kind="self-hosted",
        service_digest=None,
    )
    assert captured["runner_kind"] == "self-hosted"


def test_execute_and_finalize_are_distinct_cli_phases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    execution = lane_module.LaneExecutionOutput(
        "core", "artifact", (("source-integrity", "source", "PASS"),)
    )
    final = lane_module.LaneOutput(
        "core", "artifact", "sha256:" + "5" * 64, (("source-integrity", "source", "PASS"),)
    )
    monkeypatch.setattr(
        lane_module,
        "execute_lane",
        lambda **kwargs: calls.append(("execute", kwargs)) or execution,
    )
    monkeypatch.setattr(
        lane_module,
        "finalize_lane",
        lambda **kwargs: calls.append(("finalize", kwargs)) or final,
    )
    for command in ("execute", "finalize"):
        assert lane_module.main(
            (
                command,
                "--repo-root",
                str(tmp_path),
                "--route",
                "route.json",
                "--lane",
                "core",
                "--artifact-root",
                "artifact",
            )
        ) == 0
    assert [name for name, _ in calls] == ["execute", "finalize"]



def test_route_loader_requires_canonical_json(tmp_path: Path) -> None:
    route = tmp_path / "route-noncanonical.json"
    route.write_text('{"value": 1}\n', encoding="utf-8")
    with pytest.raises(WorkflowLaneError, match="input_canonical"):
        lane_module._load_json(tmp_path, route)


def test_execute_phase_does_not_parse_junit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract(tmp_path)
    artifact = tmp_path / "artifact-no-finalize"
    artifact.mkdir()
    monkeypatch.setattr(
        lane_module, "start_lane_deadline", lambda *_args: LaneDeadline(1, 55_000)
    )
    monkeypatch.setattr(
        lane_module,
        "_expected_spec",
        lambda **kwargs: SimpleNamespace(
            gate_id=kwargs["gate_id"], phase=kwargs["phase"]
        ),
    )
    monkeypatch.setattr(
        lane_module,
        "_execute",
        lambda *, contract, spec, deadline: _run(spec.gate_id, spec.phase),
    )
    monkeypatch.setattr(
        lane_module,
        "_report_summary",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("finalization only")),
    )
    records = _run_core(
        root=tmp_path,
        artifact_root=artifact,
        contract=contract,
        route=_route(),
    )
    assert all(summary is None for _, _, _, summary, _ in records)


def test_finalizer_rejects_unexpected_command_spec_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract(tmp_path)
    route = _route()
    artifact = tmp_path / "artifact"
    run_path = artifact / "gates/source-integrity/source/command-run.json"
    run_path.parent.mkdir(parents=True)
    report = run_path.parent / "reports/pytest.xml"
    context = SimpleNamespace(runner_environment="github-hosted")
    command = _run("source-integrity", "source").as_dict()
    monkeypatch.setattr(
        lane_module, "_context_route", lambda **_kwargs: (contract, context, route)
    )
    monkeypatch.setattr(lane_module, "_existing_artifact_root", lambda *_args: artifact)
    monkeypatch.setattr(
        lane_module, "_validate_route", lambda _contract, value: route
    )
    monkeypatch.setattr(
        lane_module,
        "_load_json",
        lambda _root, value: route if Path(value).name == "route.json" else command,
    )
    monkeypatch.setattr(
        lane_module,
        "_layout",
        lambda *_args: (("source-integrity", "source", run_path, report),),
    )
    monkeypatch.setattr(
        lane_module,
        "_expected_spec",
        lambda **_kwargs: SimpleNamespace(digest="sha256:" + "3" * 64),
    )
    with pytest.raises(WorkflowLaneError, match="command_spec_digest"):
        lane_module.finalize_lane(
            repo_root=tmp_path,
            route_path="route.json",
            lane_id="core",
            artifact_root="artifact",
        )


def test_finalizer_discards_interrupted_service_shard_reports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract(tmp_path)
    route = _route(service=True)
    artifact = tmp_path / "artifact-interrupted-shards"
    run_path = artifact / "gates/service-neo4j/tests/command-run.json"
    report = run_path.parent / "reports/pytest.xml"
    report.parent.mkdir(parents=True)
    partials = tuple(
        report.with_name(f"pytest-shard-{index:02d}.xml")
        for index in range(lane_module._SERVICE_SHARD_COUNT)
    )
    for index, path in enumerate(partials):
        path.write_text(_junit_case(f"partial_{index}"), encoding="utf-8")
    context = SimpleNamespace(runner_environment="github-hosted")
    command = _run(
        "service-neo4j",
        "tests",
        "BUDGET_EXCEEDED",
    ).as_dict()
    monkeypatch.setattr(
        lane_module, "_context_route", lambda **_kwargs: (contract, context, route)
    )
    monkeypatch.setattr(lane_module, "_existing_artifact_root", lambda *_args: artifact)
    monkeypatch.setattr(
        lane_module, "_validate_route", lambda _contract, value: route
    )
    monkeypatch.setattr(
        lane_module,
        "_load_json",
        lambda _root, value: route if Path(value).name == "route.json" else command,
    )
    monkeypatch.setattr(
        lane_module,
        "_layout",
        lambda *_args: (("service-neo4j", "tests", run_path, report),),
    )
    monkeypatch.setattr(
        lane_module,
        "_expected_spec",
        lambda **_kwargs: SimpleNamespace(digest=command["command_spec_digest"]),
    )
    monkeypatch.setattr(
        lane_module,
        "_evidence",
        lambda **_kwargs: {
            "schema_version": "newsroom.sdlc.evidence.v1",
            "result": "BUDGET_EXCEEDED",
        },
    )

    def create_envelope(**_kwargs):
        assert not tuple(report.parent.glob("pytest-shard-*.xml"))
        return SimpleNamespace(
            envelope_identity="sha256:" + "6" * 64,
            as_dict=lambda: {"schema_version": "test-envelope"},
        )

    monkeypatch.setattr(lane_module, "create_envelope", create_envelope)
    monkeypatch.setattr(lane_module, "validate_envelope", lambda _value: None)
    monkeypatch.setattr(lane_module, "artifact_name", lambda _context: "artifact")

    output = lane_module.finalize_lane(
        repo_root=tmp_path,
        route_path="route.json",
        lane_id="service",
        artifact_root="artifact-interrupted-shards",
    )

    assert output.gate_results == (
        ("service-neo4j", "tests", "BUDGET_EXCEEDED"),
    )
    assert all(not path.exists() for path in partials)


def test_shard_report_cleanup_rejects_unexpected_identity(tmp_path: Path) -> None:
    report = tmp_path / "pytest.xml"
    unexpected = report.with_name(
        f"pytest-shard-{lane_module._SERVICE_SHARD_COUNT:02d}.xml"
    )
    unexpected.write_text(_junit_case("unexpected"), encoding="utf-8")

    with pytest.raises(WorkflowLaneError, match="shard_report_identity"):
        lane_module._discard_incomplete_shard_reports(
            report=report,
            shard_count=lane_module._SERVICE_SHARD_COUNT,
        )


def test_failed_finalization_removes_derived_partial_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract(tmp_path)
    route = _route()
    artifact = tmp_path / "artifact-cleanup"
    run_path = artifact / "gates/source-integrity/source/command-run.json"
    run_path.parent.mkdir(parents=True)
    report = run_path.parent / "reports/pytest.xml"
    context = SimpleNamespace(runner_environment="github-hosted")
    command = _run("source-integrity", "source").as_dict()
    monkeypatch.setattr(
        lane_module, "_context_route", lambda **_kwargs: (contract, context, route)
    )
    monkeypatch.setattr(lane_module, "_existing_artifact_root", lambda *_args: artifact)
    monkeypatch.setattr(
        lane_module, "_validate_route", lambda _contract, value: route
    )
    monkeypatch.setattr(
        lane_module,
        "_load_json",
        lambda _root, value: route if Path(value).name == "route.json" else command,
    )
    monkeypatch.setattr(
        lane_module,
        "_layout",
        lambda *_args: (("source-integrity", "source", run_path, report),),
    )
    monkeypatch.setattr(
        lane_module,
        "_expected_spec",
        lambda **_kwargs: SimpleNamespace(digest=command["command_spec_digest"]),
    )
    monkeypatch.setattr(lane_module, "_report_summary", lambda **_kwargs: None)
    monkeypatch.setattr(
        lane_module,
        "_evidence",
        lambda **_kwargs: {
            "schema_version": "newsroom.sdlc.evidence.v1",
            "result": "PASS",
        },
    )
    monkeypatch.setattr(
        lane_module,
        "create_envelope",
        lambda **_kwargs: (_ for _ in ()).throw(WorkflowLaneError("envelope")),
    )
    with pytest.raises(WorkflowLaneError, match="envelope"):
        lane_module.finalize_lane(
            repo_root=tmp_path,
            route_path="route.json",
            lane_id="core",
            artifact_root="artifact-cleanup",
        )
    assert not (run_path.parent / "gate-evidence.json").exists()
    assert not (artifact / "envelope.json").exists()


def test_combined_run_cli_is_not_exposed() -> None:
    with pytest.raises(SystemExit):
        lane_module.main(("run",))



@pytest.mark.parametrize(
    ("service_required", "field", "value"),
    [
        (False, "core_tests", ["newsroom/tests/test_sdlc_workflow_lane.py"]),
        (True, "service_tests", ["--collect-only"]),
        (False, "sentinels", ["invented_sentinel"]),
    ],
)
def test_route_test_topology_is_repository_owned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    service_required: bool,
    field: str,
    value: list[str],
) -> None:
    contract = _contract(tmp_path)
    expected_service = (
        ("newsroom/tests/test_projection_b2_neo4j_service.py",)
        if service_required
        else ()
    )
    monkeypatch.setattr(
        lane_module,
        "_repository_service_tests",
        lambda _root: expected_service,
    )
    route = _route(service=service_required)
    route["sentinels"] = list(contract.sentinels)
    route[field] = value

    with pytest.raises(WorkflowLaneError, match="test_topology"):
        lane_module._validate_test_topology(contract, route)


def test_exact_route_test_topology_is_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract(tmp_path)
    service_tests = (
        "newsroom/tests/test_integrated_c1_neo4j_service.py",
        "newsroom/tests/test_projection_b2_neo4j_service.py",
        "newsroom/tests/test_projection_b3_neo4j_service.py",
    )
    monkeypatch.setattr(
        lane_module,
        "_repository_service_tests",
        lambda _root: service_tests,
    )
    route = _route(service=True)
    route["sentinels"] = list(contract.sentinels)

    lane_module._validate_test_topology(contract, route)



def test_cache_evidence_is_exact_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEWSROOM_SDLC_CACHE_KEY", raising=False)
    monkeypatch.delenv("NEWSROOM_SDLC_CACHE_HIT", raising=False)
    assert lane_module._cache_evidence() == (None, False)

    monkeypatch.setenv("NEWSROOM_SDLC_CACHE_KEY", "uv-linux-py312-lock")
    monkeypatch.setenv("NEWSROOM_SDLC_CACHE_HIT", "false")
    assert lane_module._cache_evidence() == ("uv-linux-py312-lock", False)

    monkeypatch.setenv("NEWSROOM_SDLC_CACHE_HIT", "true")
    assert lane_module._cache_evidence() == ("uv-linux-py312-lock", True)

    monkeypatch.delenv("NEWSROOM_SDLC_CACHE_KEY")
    with pytest.raises(WorkflowLaneError, match="cache_environment"):
        lane_module._cache_evidence()

    monkeypatch.setenv("NEWSROOM_SDLC_CACHE_KEY", "key")
    monkeypatch.setenv("NEWSROOM_SDLC_CACHE_HIT", "maybe")
    with pytest.raises(WorkflowLaneError, match="cache_environment"):
        lane_module._cache_evidence()

    monkeypatch.setenv("NEWSROOM_SDLC_CACHE_KEY", "bad\nkey")
    monkeypatch.setenv("NEWSROOM_SDLC_CACHE_HIT", "false")
    with pytest.raises(WorkflowLaneError, match="cache_environment"):
        lane_module._cache_evidence()

    monkeypatch.setenv("NEWSROOM_SDLC_CACHE_KEY", "x" * 513)
    with pytest.raises(WorkflowLaneError, match="cache_environment"):
        lane_module._cache_evidence()


def test_gate_evidence_records_exact_cache_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract(tmp_path)
    captured = {}
    monkeypatch.setenv("NEWSROOM_SDLC_CACHE_KEY", "uv-cache-exact-key")
    monkeypatch.setenv("NEWSROOM_SDLC_CACHE_HIT", "true")
    monkeypatch.setattr(lane_module, "installed_uv_version", lambda: "0.8.0")
    monkeypatch.setattr(
        lane_module,
        "build_gate_evidence",
        lambda **kwargs: captured.update(kwargs) or {"result": "PASS"},
    )

    lane_module._evidence(
        repo_root=tmp_path,
        contract=contract,
        route=_route(),
        command_run=_run("source-integrity", "source").as_dict(),
        summary=None,
        runner_kind="github-hosted",
        service_digest=None,
    )

    assert captured["cache_key"] == "uv-cache-exact-key"
    assert captured["cache_hit"] is True



def test_expected_spec_uses_uv_run_to_preserve_locked_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract(tmp_path)
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    captured: dict[str, object] = {}
    monkeypatch.setattr(lane_module.shutil, "which", lambda name: "/opt/uv/bin/uv")
    monkeypatch.setattr(
        lane_module,
        "_spec",
        lambda **kwargs: captured.update(kwargs) or SimpleNamespace(),
    )

    lane_module._expected_spec(
        root=tmp_path,
        artifact_root=artifact,
        contract=contract,
        route=_route(),
        gate_id="core-deterministic",
        phase="tests",
    )

    assert captured["argv"][:6] == [
        "/opt/uv/bin/uv",
        "run",
        "--no-sync",
        "python",
        "-m",
        "scripts.sdlc.workflow_lane",
    ]


def test_uv_command_fails_closed_when_uv_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lane_module.shutil, "which", lambda name: None)
    with pytest.raises(WorkflowLaneError, match="uv_executable"):
        lane_module._uv_command("-c", "print('never')")


def test_uv_command_uses_the_locked_project_environment() -> None:
    completed = lane_module.subprocess.run(
        lane_module._uv_command("-c", "import pytest"),
        cwd=REPO_ROOT,
        check=False,
        stdout=lane_module.subprocess.PIPE,
        stderr=lane_module.subprocess.PIPE,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")



def test_report_summary_records_artifact_relative_raw_report_path(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / ".sdlc-run" / "core"
    report = artifact / "gates/core-deterministic/tests/reports/pytest.xml"
    report.parent.mkdir(parents=True)
    report.write_text(
        '<testsuite><testcase classname="example" name="test_ok" time="0.001"/></testsuite>',
        encoding="utf-8",
    )

    original = lane_module.summarize_junit(
        tmp_path,
        (report.relative_to(tmp_path).as_posix(),),
    )
    summary = lane_module._report_summary(
        repo_root=tmp_path,
        artifact_root=artifact,
        report=report,
        optional_test_ids=(),
    )

    assert summary is not None
    assert summary.report_digests == (
        (
            "gates/core-deterministic/tests/reports/pytest.xml",
            original.report_digests[0][1],
        ),
    )
    assert summary.test_ids_digest == original.test_ids_digest
    assert summary.test_count == original.test_count == 1
    assert summary.first_failure_fingerprint == original.first_failure_fingerprint


def test_report_summary_rejects_report_outside_artifact_root(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    report = tmp_path / "outside.xml"
    report.write_text(
        '<testsuite><testcase classname="example" name="test_ok"/></testsuite>',
        encoding="utf-8",
    )
    with pytest.raises(WorkflowLaneError, match="report_path"):
        lane_module._report_summary(
            repo_root=tmp_path,
            artifact_root=artifact,
            report=report,
            optional_test_ids=(),
        )
