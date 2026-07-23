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
            ["newsroom/tests/test_projection_b2_neo4j_service.py"] if service else []
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
        "sha256:c3d391e503495d5d240d6ea49666c7de04389761c53eae3d5967e354a5b34ec8"
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

    monkeypatch.setattr(lane_module, "start_lane_deadline", lambda *_args: deadline)
    monkeypatch.setattr(
        lane_module,
        "_spec",
        lambda **kwargs: SimpleNamespace(
            gate_id=kwargs["gate_id"], phase=kwargs["phase"]
        ),
    )

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
    assert static["NEWSROOM_NEO4J_SERVICE_REQUIRED"] == "1"
    assert "NEWSROOM_NEO4J_PROJECTOR_PASSWORD" not in static


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


def test_core_test_command_runs_full_suite_and_conditional_clustering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = tmp_path / "report.xml"
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        lane_module,
        "_run_subprocess",
        lambda argv: calls.append(tuple(str(item) for item in argv)) or 0,
    )

    assert core_tests(repo_root=tmp_path, report=report, clustering=True) == 0
    assert calls[0][0:5] == (
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "newsroom/tests",
    )
    assert f"--junitxml={report}" in calls[0]
    assert calls[1][1] == "scripts/eval_clustering_metrics.py"


def test_optional_core_skips_are_exact_actual_service_cases() -> None:
    assert lane_module._OPTIONAL_CORE_TEST_IDS == tuple(
        sorted(lane_module._OPTIONAL_CORE_TEST_IDS)
    )
    assert len(lane_module._OPTIONAL_CORE_TEST_IDS) == 4
    assert all(
        value.startswith("newsroom.tests.test_projection_b2_neo4j_service::")
        for value in lane_module._OPTIONAL_CORE_TEST_IDS
    )


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
    assert captured["service_compatibility_digest"] == service_compatibility_digest()


def test_main_returns_typed_error_for_invalid_lane(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert lane_module.main(
        (
            "run",
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
