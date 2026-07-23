from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json

import pytest

import scripts.sdlc.workflow_budget as budget
from scripts.sdlc.artifact_envelope import GithubRunContext
from scripts.sdlc.classify_change import sha256_identity
from scripts.sdlc.contracts import SdlcContract, load_contract
from scripts.sdlc.emit_evidence import canonical_json_bytes
from scripts.sdlc.run_gate import GateRunResult, LaneDeadline
from scripts.sdlc.workflow_event import WorkflowEvent
from scripts.sdlc.workflow_orchestrator import RouteOutput


REPO_ROOT = Path(__file__).parents[2]
HEAD = "1" * 40
TREE = "2" * 40
BASE = "3" * 40
BASE_TREE = "4" * 40


def _contract(root: Path = REPO_ROOT) -> SdlcContract:
    source = load_contract(REPO_ROOT)
    if root == REPO_ROOT:
        return source
    return SdlcContract(root, source.source_path, source.data)


def _context(job_id: str) -> GithubRunContext:
    return GithubRunContext(
        repository="fol2/newsroom",
        repository_id=1153895518,
        head_repository="fol2/newsroom",
        head_repository_id=1153895518,
        run_id=9876,
        run_attempt=3,
        job_id=job_id,
        workflow_ref=(
            "fol2/newsroom/.github/workflows/evidence.yml@refs/pull/10/merge"
        ),
        workflow_sha="5" * 40,
        event_name="pull_request",
        event_sha="6" * 40,
        evaluated_sha=HEAD,
        evaluated_tree_sha=TREE,
        ref="refs/pull/10/merge",
        runner_environment="github-hosted",
    )


def _event() -> WorkflowEvent:
    return WorkflowEvent(
        repository="fol2/newsroom",
        repository_id=1153895518,
        head_repository="fol2/newsroom",
        head_repository_id=1153895518,
        event_name="pull_request",
        event_sha="6" * 40,
        base_sha=BASE,
        base_tree_sha=BASE_TREE,
        evaluated_sha=HEAD,
        evaluated_tree_sha=TREE,
        ref="refs/pull/10/merge",
    )


def _ambient(job_id: str, *, service: bool = False) -> dict[str, str]:
    value = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": "fol2/newsroom",
        "GITHUB_REPOSITORY_ID": "1153895518",
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_SHA": "6" * 40,
        "GITHUB_EVENT_PATH": "/tmp/event.json",
        "GITHUB_JOB": job_id,
        "GITHUB_WORKFLOW_SHA": "5" * 40,
        "GITHUB_WORKFLOW_REF": (
            "fol2/newsroom/.github/workflows/evidence.yml@refs/pull/10/merge"
        ),
        "GITHUB_RUN_ID": "9876",
        "GITHUB_RUN_ATTEMPT": "3",
        "GITHUB_REF": "refs/pull/10/merge",
        "RUNNER_ENVIRONMENT": "github-hosted",
        "CI": "ambient-value-is-ignored",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/opt/uv:/usr/bin:/bin",
        "HOME": "/home/runner",
        "RUNNER_TEMP": "/tmp/runner",
        "UV_CACHE_DIR": "/tmp/uv-cache",
        "GITHUB_TOKEN": "must-not-pass",
        "NEO4J_ADMIN_PASSWORD": "must-not-pass",
        "NEWSROOM_NEO4J_PROJECTOR_PASSWORD": "must-not-pass",
    }
    if service:
        value.update(budget._SERVICE_CONFIGURATION)
    return value


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _route(contract: SdlcContract) -> dict[str, object]:
    manifest = {
        "core_tests": ["newsroom/tests"],
        "service_tests": [],
        "sentinels": list(contract.sentinels),
    }
    return {
        "schema_version": "newsroom.sdlc.route.v1",
        "contract_version": contract.contract_version,
        "base_sha": BASE,
        "head_sha": HEAD,
        "base_tree_sha": BASE_TREE,
        "head_tree_sha": TREE,
        "risk_tier": "R1_LOCAL_CODE",
        "reasons": ["path:newsroom/example.py:local_code:R1_LOCAL_CODE"],
        "core_required": True,
        "service_required": False,
        "clustering_required": False,
        "owner_authority_required": False,
        "core_tests": ["newsroom/tests"],
        "service_tests": [],
        "sentinels": list(contract.sentinels),
        "selected_test_manifest_digest": sha256_identity(manifest),
    }


def _run(gate_id: str, phase: str, result: str = "PASS") -> GateRunResult:
    return GateRunResult(
        gate_id=gate_id,
        phase=phase,
        result=result,
        result_reason=f"{result}:{gate_id}:{phase}",
        returncode=0 if result == "PASS" else None,
        execution_ms=25,
        stdout="",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
    )


def test_child_environment_is_minimal_and_preserves_exact_static_inputs() -> None:
    environment = budget._child_environment(
        ambient=_ambient("core"), service=False, preserve_lane_static=True
    )

    assert environment["CI"] == "true"
    assert environment["PATH"] == "/opt/uv:/usr/bin:/bin"
    assert environment["HOME"] == "/home/runner"
    assert environment["GITHUB_JOB"] == "core"
    assert "GITHUB_TOKEN" not in environment
    assert "NEO4J_ADMIN_PASSWORD" not in environment
    assert "NEWSROOM_NEO4J_PROJECTOR_PASSWORD" not in environment


def test_service_child_environment_requires_exact_nonsecret_configuration() -> None:
    environment = budget._child_environment(
        ambient=_ambient("service", service=True),
        service=True,
        preserve_lane_static=True,
    )
    assert all(
        environment[name] == value
        for name, value in budget._SERVICE_CONFIGURATION.items()
    )
    assert "NEWSROOM_NEO4J_PROJECTOR_PASSWORD" not in environment

    wrong = _ambient("service", service=True)
    wrong["NEWSROOM_NEO4J_URI"] = "bolt://remote.example:7687"
    with pytest.raises(budget.WorkflowBudgetError, match="service_environment"):
        budget._child_environment(
            ambient=wrong, service=True, preserve_lane_static=True
        )


def test_missing_github_context_fails_closed() -> None:
    ambient = _ambient("route")
    ambient.pop("GITHUB_RUN_ATTEMPT")
    with pytest.raises(budget.WorkflowBudgetError, match="github_environment"):
        budget._child_environment(
            ambient=ambient, service=False, preserve_lane_static=False
        )


def test_route_bundle_is_cross_bound_to_event_context_and_identity(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    context = _context("route")
    event = _event()
    route = _route(contract)
    directory = tmp_path / "route-output"
    directory.mkdir()
    output = RouteOutput(
        artifact_name=budget._route_artifact_name(context),
        service_required=False,
        route_identity=sha256_identity(route),
        event_identity=str(event.as_dict()["event_identity"]),
    )
    _write(directory / "route.json", route)
    _write(directory / "event.json", event.as_dict())
    _write(directory / "route-output.json", output.as_dict())

    assert budget.validate_route_bundle(
        repo_root=tmp_path,
        output_directory="route-output",
        context=context,
        contract=contract,
    ) == output

    changed = output.as_dict()
    changed["route_identity"] = "sha256:" + "9" * 64
    (directory / "route-output.json").unlink()
    _write(directory / "route-output.json", changed)
    with pytest.raises(budget.WorkflowBudgetError, match="route_identity"):
        budget.validate_route_bundle(
            repo_root=tmp_path,
            output_directory="route-output",
            context=context,
            contract=contract,
        )


def test_bounded_route_uses_accepted_route_gate_and_secret_free_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context("route")
    contract = _contract(tmp_path)
    deadline = LaneDeadline(100, 55_000)
    observed = {}
    monkeypatch.setattr(budget, "context_from_environment", lambda _root: context)
    monkeypatch.setattr(budget, "load_contract", lambda _root: contract)
    monkeypatch.setattr(budget, "start_lane_deadline", lambda *_args: deadline)
    monkeypatch.setattr(
        budget,
        "_child_environment",
        lambda **_kwargs: {"PATH": "/usr/bin:/bin"},
    )

    def run(**kwargs):
        observed.update(kwargs)
        return _run("route", "classify")

    monkeypatch.setattr(budget, "run_configured_gate", run)
    monkeypatch.setattr(
        budget,
        "validate_route_bundle",
        lambda **_kwargs: RouteOutput("artifact", False, "sha256:" + "1" * 64, "sha256:" + "2" * 64),
    )

    result = budget.run_bounded_route(
        repo_root=tmp_path, output_directory="route-output"
    )

    assert result.result == "PASS"
    assert observed["gate_id"] == "route"
    assert observed["phase"] == "classify"
    assert observed["deadline"] is deadline
    assert observed["argv"][0] == budget.sys.executable
    assert observed["argv"][2:5] == (
        "scripts.sdlc.workflow_orchestrator",
        "route",
        "--repo-root",
    )
    assert "GITHUB_TOKEN" not in observed["env"]


def test_route_budget_failure_removes_partial_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context("route")
    contract = _contract(tmp_path)
    monkeypatch.setattr(budget, "context_from_environment", lambda _root: context)
    monkeypatch.setattr(budget, "load_contract", lambda _root: contract)
    monkeypatch.setattr(
        budget, "start_lane_deadline", lambda *_args: LaneDeadline(100, 55_000)
    )
    monkeypatch.setattr(
        budget,
        "_child_environment",
        lambda **_kwargs: {"PATH": "/usr/bin:/bin"},
    )

    def run(**_kwargs):
        output = tmp_path / "route-output"
        output.mkdir()
        (output / "partial").write_text("partial", encoding="utf-8")
        return _run("route", "classify", "BUDGET_EXCEEDED")

    monkeypatch.setattr(budget, "run_configured_gate", run)

    result = budget.run_bounded_route(
        repo_root=tmp_path, output_directory="route-output"
    )

    assert result.result == "BUDGET_EXCEEDED"
    assert not (tmp_path / "route-output").exists()


def test_lane_finalization_uses_accepted_five_second_gate_and_exact_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context("core")
    contract = _contract(tmp_path)
    deadline = LaneDeadline(100, 5_000)
    _write(tmp_path / "route.json", {"route": True})
    (tmp_path / "artifact").mkdir()
    observed = {}
    monkeypatch.setattr(budget, "context_from_environment", lambda _root: context)
    monkeypatch.setattr(budget, "load_contract", lambda _root: contract)
    monkeypatch.setattr(budget, "start_lane_deadline", lambda *_args: deadline)
    monkeypatch.setattr(
        budget,
        "_child_environment",
        lambda **_kwargs: {"PATH": "/usr/bin:/bin"},
    )

    def run(**kwargs):
        observed.update(kwargs)
        return _run("evidence-finalize", "core-lane")

    monkeypatch.setattr(budget, "run_configured_gate", run)
    monkeypatch.setattr(budget, "_validate_lane_output", lambda **_kwargs: {})

    result = budget.run_bounded_lane_finalization(
        repo_root=tmp_path,
        route_path="route.json",
        lane_id="core",
        artifact_root="artifact",
        output_path="lane-output.json",
    )

    assert result.result == "PASS"
    assert observed["gate_id"] == "evidence-finalize"
    assert observed["phase"] == "core-lane"
    assert observed["deadline"] is deadline
    assert observed["argv"][2:5] == (
        "scripts.sdlc.workflow_lane",
        "finalize",
        "--repo-root",
    )
    assert "GITHUB_TOKEN" not in observed["env"]


def test_invalid_lane_output_converts_pass_to_evidence_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context("core")
    contract = _contract(tmp_path)
    _write(tmp_path / "route.json", {"route": True})
    (tmp_path / "artifact").mkdir()
    monkeypatch.setattr(budget, "context_from_environment", lambda _root: context)
    monkeypatch.setattr(budget, "load_contract", lambda _root: contract)
    monkeypatch.setattr(
        budget, "start_lane_deadline", lambda *_args: LaneDeadline(100, 5_000)
    )
    monkeypatch.setattr(
        budget,
        "_child_environment",
        lambda **_kwargs: {"PATH": "/usr/bin:/bin"},
    )

    def run(**_kwargs):
        _write(tmp_path / "lane-output.json", {"invalid": True})
        return _run("evidence-finalize", "core-lane")

    monkeypatch.setattr(budget, "run_configured_gate", run)
    monkeypatch.setattr(
        budget,
        "_validate_lane_output",
        lambda **_kwargs: (_ for _ in ()).throw(
            budget.WorkflowBudgetError("lane_output")
        ),
    )

    result = budget.run_bounded_lane_finalization(
        repo_root=tmp_path,
        route_path="route.json",
        lane_id="core",
        artifact_root="artifact",
        output_path="lane-output.json",
    )

    assert result.result == "EVIDENCE_MISMATCH"
    assert result.result_reason.endswith(":lane-output")
    assert not (tmp_path / "lane-output.json").exists()


def test_lane_job_identity_is_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        budget, "context_from_environment", lambda _root: _context("decision")
    )
    with pytest.raises(budget.WorkflowBudgetError, match="lane_job"):
        budget.run_bounded_lane_finalization(
            repo_root=tmp_path,
            route_path="missing.json",
            lane_id="core",
            artifact_root="missing",
            output_path="lane-output.json",
        )


def test_cli_returns_typed_budget_exit_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        budget,
        "run_bounded_route",
        lambda **_kwargs: _run("route", "classify", "BUDGET_EXCEEDED"),
    )

    assert budget.main(("route", "--output-directory", "route")) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["result"] == "BUDGET_EXCEEDED"
    assert payload["schema_version"] == "newsroom.sdlc.gate-run.v1"



def test_route_child_environment_is_fixed_and_drops_uv_cache() -> None:
    environment = budget._child_environment(
        ambient=_ambient("route"),
        service=False,
        preserve_lane_static=False,
    )

    assert environment["PATH"] == "/usr/bin:/bin"
    assert environment["HOME"] == "/tmp/runner"
    assert environment["TMPDIR"] == "/tmp/runner"
    assert "UV_CACHE_DIR" not in environment
    assert "GITHUB_TOKEN" not in environment


def test_service_profile_cannot_use_route_environment() -> None:
    with pytest.raises(budget.WorkflowBudgetError, match="service_environment"):
        budget._child_environment(
            ambient=_ambient("service", service=True),
            service=True,
            preserve_lane_static=False,
        )
