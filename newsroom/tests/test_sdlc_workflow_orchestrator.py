from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path

import pytest

import scripts.sdlc.workflow_orchestrator as orchestrator
from scripts.sdlc.artifact_envelope import GithubRunContext, artifact_name
from scripts.sdlc.contracts import ContractError
from scripts.sdlc.emit_evidence import canonical_json_bytes
from scripts.sdlc.github_transport import GitHubTransportError
from scripts.sdlc.run_gate import GateRunResult, LaneDeadline
from scripts.sdlc.shadow_decision import failure_shadow_decision
from scripts.sdlc.workflow_event import WorkflowEvent


HEAD = "1" * 40
TREE = "2" * 40
BASE = "3" * 40
BASE_TREE = "4" * 40


def _context(job_id: str = "decision") -> GithubRunContext:
    return GithubRunContext(
        repository="fol2/newsroom",
        repository_id=1153895518,
        head_repository="fol2/newsroom",
        head_repository_id=1153895518,
        run_id=12345,
        run_attempt=2,
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


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value) + b"\n")


@dataclass
class _FakeRoute:
    service_required: bool


@dataclass
class _FakeReceipt:
    route: _FakeRoute


@dataclass
class _FakeLane:
    lane_id: str
    service_required: bool

    @property
    def lane_identity(self) -> str:
        return "sha256:" + ("1" if self.lane_id == "core" else "2") * 64

    @property
    def receipt(self) -> _FakeReceipt:
        return _FakeReceipt(_FakeRoute(self.service_required))

    def as_dict(self) -> dict[str, object]:
        return {
            "lane_id": self.lane_id,
            "lane_identity": self.lane_identity,
            "service_required": self.service_required,
        }


class _FakeClient:
    def __init__(self, artifacts: list[dict[str, object]] | None = None) -> None:
        self.artifacts = artifacts or []

    def list_artifacts(self, _run_id: int) -> dict[str, object]:
        return {"artifacts": self.artifacts, "total_count": len(self.artifacts)}


def test_route_preparation_binds_exact_event_and_publishes_canonical_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context("route")
    event = _event()
    route = {
        "base_sha": BASE,
        "base_tree_sha": BASE_TREE,
        "head_sha": HEAD,
        "head_tree_sha": TREE,
        "service_required": True,
    }
    monkeypatch.setattr(orchestrator, "context_from_environment", lambda _root: context)
    monkeypatch.setattr(orchestrator, "derive_workflow_event", lambda _root: event)
    monkeypatch.setattr(
        orchestrator,
        "build_git_route",
        lambda _root, *, base_reference, head_reference: (
            route
            if (base_reference, head_reference) == (BASE, HEAD)
            else (_ for _ in ()).throw(AssertionError("wrong refs"))
        ),
    )

    output = orchestrator.prepare_route(
        repo_root=tmp_path, output_directory="route-output"
    )

    assert output.service_required is True
    assert output.artifact_name == f"newsroom-sdlc-route-12345-2-{HEAD}"
    for name in ("route.json", "event.json", "route-output.json"):
        payload = (tmp_path / "route-output" / name).read_bytes()
        assert payload.endswith(b"\n")
        assert payload == canonical_json_bytes(json.loads(payload)) + b"\n"


def test_route_preparation_rejects_event_route_identity_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(orchestrator, "context_from_environment", lambda _root: _context("route"))
    monkeypatch.setattr(orchestrator, "derive_workflow_event", lambda _root: _event())
    monkeypatch.setattr(
        orchestrator,
        "build_git_route",
        lambda *_args, **_kwargs: {
            "base_sha": BASE,
            "base_tree_sha": BASE_TREE,
            "head_sha": "9" * 40,
            "head_tree_sha": TREE,
        },
    )
    with pytest.raises(orchestrator.WorkflowOrchestratorError, match="route_event_identity"):
        orchestrator.prepare_route(repo_root=tmp_path, output_directory="route")
    assert not (tmp_path / "route").exists()


def _patch_collection_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    core: _FakeLane,
    service: _FakeLane | None = None,
    artifacts: list[dict[str, object]] | None = None,
) -> list[str]:
    fetched: list[str] = []
    client = _FakeClient(artifacts)
    monkeypatch.setattr(orchestrator, "context_from_environment", lambda _root: _context())
    monkeypatch.setattr(orchestrator, "derive_workflow_event", lambda _root: _event())
    monkeypatch.setattr(orchestrator, "load_contract", lambda _root: object())
    monkeypatch.setattr(
        orchestrator.GitHubActionsClient,
        "from_environment",
        classmethod(lambda cls, **kwargs: client),
    )

    def fetch(**kwargs):
        fetched.append(str(kwargs["artifact_name"]))
        Path(kwargs["output_parent"], kwargs["output_name"]).mkdir()
        return object()

    monkeypatch.setattr(orchestrator, "fetch_artifact_bundle", fetch)

    def verify(*, lane_id, **_kwargs):
        if lane_id == "core":
            return core
        assert service is not None
        return service

    monkeypatch.setattr(orchestrator, "verify_shadow_lane", verify)
    monkeypatch.setattr(
        orchestrator,
        "validate_collection",
        lambda value, *, contract: value,
    )
    return fetched


def test_collection_fetches_core_only_and_rejects_no_required_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fetched = _patch_collection_dependencies(
        monkeypatch, core=_FakeLane("core", False)
    )

    value = orchestrator.collect_decision_inputs(
        repo_root=tmp_path, output_directory="decision-input"
    )

    assert value["status"] == "READY"
    assert value["service"] is None
    assert fetched == [artifact_name(orchestrator._producer_context(_context(), "core"))]
    assert "GITHUB_TOKEN" not in (tmp_path / "decision-input/context.json").read_text()


def test_collection_fetches_service_exactly_when_core_route_requires_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fetched = _patch_collection_dependencies(
        monkeypatch,
        core=_FakeLane("core", True),
        service=_FakeLane("service", True),
    )

    value = orchestrator.collect_decision_inputs(
        repo_root=tmp_path, output_directory="decision-input"
    )

    assert value["status"] == "READY"
    assert value["service"]["lane_id"] == "service"
    assert fetched == [
        artifact_name(orchestrator._producer_context(_context(), "core")),
        artifact_name(orchestrator._producer_context(_context(), "service")),
    ]


def test_unexpected_service_artifact_becomes_typed_collection_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service_name = artifact_name(orchestrator._producer_context(_context(), "service"))
    _patch_collection_dependencies(
        monkeypatch,
        core=_FakeLane("core", False),
        artifacts=[{"name": service_name}],
    )

    value = orchestrator.collect_decision_inputs(
        repo_root=tmp_path, output_directory="decision-input"
    )

    assert value["status"] == "ERROR"
    assert value["failure_result"] == "EVIDENCE_MISMATCH"
    assert value["failure_code"] == "service_artifact_unexpected"
    assert value["core"] is None


def test_transport_error_is_redacted_to_stable_failure_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(orchestrator, "context_from_environment", lambda _root: _context())
    monkeypatch.setattr(orchestrator, "derive_workflow_event", lambda _root: _event())
    monkeypatch.setattr(orchestrator, "load_contract", lambda _root: object())
    monkeypatch.setattr(
        orchestrator.GitHubActionsClient,
        "from_environment",
        classmethod(lambda cls, **kwargs: _FakeClient()),
    )
    monkeypatch.setattr(
        orchestrator,
        "fetch_artifact_bundle",
        lambda **_kwargs: (_ for _ in ()).throw(
            GitHubTransportError("secret-value-must-not-escape")
        ),
    )

    value = orchestrator.collect_decision_inputs(
        repo_root=tmp_path, output_directory="decision-input"
    )

    assert value["status"] == "ERROR"
    assert value["failure_code"] == "artifact-transport"
    assert "secret-value" not in json.dumps(value)


def test_error_collection_validates_and_identity_tampering_fails() -> None:
    value = orchestrator._collection_value(
        context=_context(),
        event=None,
        core=None,
        service=None,
        status="ERROR",
        failure_result="EVIDENCE_MISMATCH",
        failure_code="missing-core",
    )
    assert orchestrator.validate_collection(value, contract=None) == value
    changed = dict(value)
    changed["failure_code"] = "other"
    with pytest.raises(orchestrator.WorkflowOrchestratorError, match="collection_identity"):
        orchestrator.validate_collection(changed, contract=None)


def test_ready_collection_requires_service_exactly_when_route_requires_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = _FakeLane("core", True)
    value = orchestrator._collection_value(
        context=_context(),
        event=_event(),
        core=core,  # type: ignore[arg-type]
        service=None,
        status="READY",
        failure_result=None,
        failure_code=None,
    )
    monkeypatch.setattr(
        orchestrator,
        "validate_shadow_lane_record",
        lambda raw, *, contract: core,
    )
    with pytest.raises(orchestrator.WorkflowOrchestratorError, match="collection_service"):
        orchestrator.validate_collection(value, contract=object())  # type: ignore[arg-type]


def test_invalid_collection_after_trusted_context_yields_typed_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "context.json", _context().as_dict())
    _write(tmp_path / "collection.json", {"invalid": True})
    monkeypatch.setattr(orchestrator, "load_contract", lambda _root: object())

    decision = orchestrator.decision_from_collection(
        repo_root=tmp_path,
        context_path="context.json",
        collection_path="collection.json",
    )

    assert decision.result == "EVIDENCE_MISMATCH"
    assert decision.result_reason == "EVIDENCE_MISMATCH:decision:invalid-collection"


def test_bounded_decision_timeout_publishes_failure_without_ambient_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "context.json", _context().as_dict())
    _write(tmp_path / "collection.json", {"ignored": True})
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-cross-boundary")
    monkeypatch.setattr(orchestrator, "load_contract", lambda _root: object())
    monkeypatch.setattr(
        orchestrator,
        "start_lane_deadline",
        lambda *_args: LaneDeadline(1, 5_000),
    )
    captured = {}

    def run(**kwargs):
        captured.update(kwargs)
        return GateRunResult(
            "evidence-finalize",
            "decision",
            "BUDGET_EXCEEDED",
            "BUDGET_EXCEEDED:evidence-finalize:decision",
            None,
            4_750,
            "",
            "",
            False,
            False,
        )

    monkeypatch.setattr(orchestrator, "run_configured_gate", run)

    decision = orchestrator.run_bounded_decision(
        repo_root=tmp_path,
        context_path="context.json",
        collection_path="collection.json",
        output_path="decision.json",
    )

    assert decision.result == "BUDGET_EXCEEDED"
    assert decision.result_reason == "BUDGET_EXCEEDED:decision:finalization-timeout"
    assert "GITHUB_TOKEN" not in captured["env"]
    assert "must-not-cross-boundary" not in (tmp_path / "decision.json").read_text()


def test_contract_load_failure_after_context_still_publishes_typed_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "context.json", _context().as_dict())
    _write(tmp_path / "collection.json", {"ignored": True})
    monkeypatch.setattr(
        orchestrator,
        "load_contract",
        lambda _root: (_ for _ in ()).throw(ContractError("broken")),
    )

    decision = orchestrator.run_bounded_decision(
        repo_root=tmp_path,
        context_path="context.json",
        collection_path="collection.json",
        output_path="decision.json",
    )

    assert decision.result == "EVIDENCE_MISMATCH"
    assert decision.result_reason == "EVIDENCE_MISMATCH:decision:contract-load"
    assert (tmp_path / "decision.json").is_file()


def test_decision_output_never_overwrites(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path / "context.json", _context().as_dict())
    _write(tmp_path / "collection.json", {"ignored": True})
    _write(tmp_path / "decision.json", {"existing": True})
    monkeypatch.setattr(orchestrator, "load_contract", lambda _root: object())
    with pytest.raises(orchestrator.WorkflowOrchestratorError, match="output_exists"):
        orchestrator.run_bounded_decision(
            repo_root=tmp_path,
            context_path="context.json",
            collection_path="collection.json",
            output_path="decision.json",
        )


def test_input_paths_cannot_escape_repository(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"outside-{tmp_path.name}.json"
    _write(outside, _context().as_dict())
    with pytest.raises(orchestrator.WorkflowOrchestratorError, match="input_path"):
        orchestrator._load_context(tmp_path, outside)


def test_enforce_returns_nonzero_for_typed_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    decision = failure_shadow_decision(context=_context(), code="missing-core")
    _write(tmp_path / "decision.json", decision.as_dict())
    monkeypatch.setattr(orchestrator, "load_contract", lambda _root: object())

    assert orchestrator.enforce_decision(
        repo_root=tmp_path, decision_path="decision.json"
    ) == 1
    assert decision.decision_identity in capsys.readouterr().out


def test_route_and_decision_artifact_names_are_attempt_scoped() -> None:
    route = orchestrator._route_artifact_name(_context("route"))
    core = artifact_name(orchestrator._producer_context(_context(), "core"))
    service = artifact_name(orchestrator._producer_context(_context(), "service"))
    assert "-12345-2-" in route
    assert core != service
    assert HEAD in core and HEAD in service



def test_canonical_loader_rejects_symlink_input(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    _write(target, {"value": 1})
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(orchestrator.WorkflowOrchestratorError, match="machine_json"):
        orchestrator._canonical_load(link)


def test_missing_collection_after_context_yields_typed_decision_without_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "context.json", _context().as_dict())
    monkeypatch.setattr(orchestrator, "load_contract", lambda _root: object())
    monkeypatch.setattr(
        orchestrator,
        "run_configured_gate",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("child must not run")),
    )

    decision = orchestrator.run_bounded_decision(
        repo_root=tmp_path,
        context_path="context.json",
        collection_path="missing.json",
        output_path="decision.json",
    )

    assert decision.result == "EVIDENCE_MISMATCH"
    assert decision.result_reason == "EVIDENCE_MISMATCH:decision:invalid-collection"


def test_watchdog_environment_failure_is_typed_after_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "context.json", _context().as_dict())
    _write(tmp_path / "collection.json", {"ignored": True})
    monkeypatch.setattr(orchestrator, "load_contract", lambda _root: object())
    monkeypatch.setattr(
        orchestrator,
        "start_lane_deadline",
        lambda *_args: LaneDeadline(1, 5_000),
    )
    monkeypatch.setattr(
        orchestrator,
        "run_configured_gate",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("unavailable")),
    )

    decision = orchestrator.run_bounded_decision(
        repo_root=tmp_path,
        context_path="context.json",
        collection_path="collection.json",
        output_path="decision.json",
    )

    assert decision.result == "ENVIRONMENT_ERROR"
    assert decision.result_reason == "ENVIRONMENT_ERROR:decision:finalization-environment"


def test_final_decision_environment_is_fixed_and_secret_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANG", "attacker-controlled")
    monkeypatch.setenv("PATH", "/tmp/untrusted")
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    assert orchestrator._decision_environment() == {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        "PYTHONHASHSEED": "0",
        "PYTHONUTF8": "1",
    }



def test_collection_uses_bounded_github_request_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed = {}
    client = _FakeClient()
    monkeypatch.setattr(orchestrator, "context_from_environment", lambda _root: _context())
    monkeypatch.setattr(orchestrator, "derive_workflow_event", lambda _root: _event())
    monkeypatch.setattr(orchestrator, "load_contract", lambda _root: object())
    monkeypatch.setattr(
        orchestrator.GitHubActionsClient,
        "from_environment",
        classmethod(
            lambda cls, **kwargs: observed.update(kwargs) or client
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "fetch_artifact_bundle",
        lambda **_kwargs: (_ for _ in ()).throw(GitHubTransportError("missing")),
    )

    orchestrator.collect_decision_inputs(
        repo_root=tmp_path, output_directory="decision-input"
    )

    assert observed == {"timeout_seconds": 5.0}


def test_collection_validation_failure_becomes_typed_error_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = _FakeLane("core", False)
    client = _FakeClient()
    monkeypatch.setattr(orchestrator, "context_from_environment", lambda _root: _context())
    monkeypatch.setattr(orchestrator, "derive_workflow_event", lambda _root: _event())
    monkeypatch.setattr(orchestrator, "load_contract", lambda _root: object())
    monkeypatch.setattr(
        orchestrator.GitHubActionsClient,
        "from_environment",
        classmethod(lambda cls, **kwargs: client),
    )
    monkeypatch.setattr(
        orchestrator,
        "fetch_artifact_bundle",
        lambda **kwargs: Path(kwargs["output_parent"], kwargs["output_name"]).mkdir(),
    )
    monkeypatch.setattr(orchestrator, "verify_shadow_lane", lambda **_kwargs: core)
    real_validate = orchestrator.validate_collection
    calls = 0

    def validate(value, *, contract):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise orchestrator.WorkflowOrchestratorError("collection_evidence")
        return real_validate(value, contract=contract)

    monkeypatch.setattr(orchestrator, "validate_collection", validate)

    value = orchestrator.collect_decision_inputs(
        repo_root=tmp_path, output_directory="decision-input"
    )

    assert value["status"] == "ERROR"
    assert value["failure_code"] == "collection-validation"
    assert (tmp_path / "decision-input/context.json").is_file()
    assert (tmp_path / "decision-input/collection.json").is_file()


def test_contract_filesystem_failure_after_context_is_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "context.json", _context().as_dict())
    _write(tmp_path / "collection.json", {"ignored": True})
    monkeypatch.setattr(
        orchestrator,
        "load_contract",
        lambda _root: (_ for _ in ()).throw(OSError("unavailable")),
    )

    decision = orchestrator.run_bounded_decision(
        repo_root=tmp_path,
        context_path="context.json",
        collection_path="collection.json",
        output_path="decision.json",
    )

    assert decision.result == "EVIDENCE_MISMATCH"
    assert decision.result_reason == "EVIDENCE_MISMATCH:decision:contract-load"


def test_decision_child_rejects_symlinked_output_parent(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(orchestrator.WorkflowOrchestratorError, match="child_output"):
        orchestrator._decision_child(
            repo_root=tmp_path,
            context_path="context.json",
            collection_path="collection.json",
            output_path=linked / "decision.json",
        )



def test_parent_rejects_child_decision_for_another_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context()
    _write(tmp_path / "context.json", context.as_dict())
    _write(tmp_path / "collection.json", {"ignored": True})
    monkeypatch.setattr(orchestrator, "load_contract", lambda _root: object())
    monkeypatch.setattr(
        orchestrator,
        "start_lane_deadline",
        lambda *_args: LaneDeadline(1, 5_000),
    )

    def run(**kwargs):
        argv = list(kwargs["argv"])
        child = Path(argv[argv.index("--output") + 1])
        other = replace(context, run_id=context.run_id + 1)
        decision = failure_shadow_decision(context=other, code="other-run")
        _write(child, decision.as_dict())
        return GateRunResult(
            "evidence-finalize",
            "decision",
            "PASS",
            "PASS:evidence-finalize:decision",
            0,
            1,
            "",
            "",
            False,
            False,
        )

    monkeypatch.setattr(orchestrator, "run_configured_gate", run)

    decision = orchestrator.run_bounded_decision(
        repo_root=tmp_path,
        context_path="context.json",
        collection_path="collection.json",
        output_path="decision.json",
    )

    assert decision.context == context
    assert decision.result == "EVIDENCE_MISMATCH"
    assert decision.result_reason == "EVIDENCE_MISMATCH:decision:invalid-decision-output"
