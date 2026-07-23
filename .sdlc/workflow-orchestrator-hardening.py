from __future__ import annotations

from pathlib import Path

SOURCE = Path("scripts/sdlc/workflow_orchestrator.py")
TEST = Path("newsroom/tests/test_sdlc_workflow_orchestrator.py")

source = SOURCE.read_text(encoding="utf-8")
old_load = '''        payload = _safe_machine_file(path.resolve(), maximum=maximum, code="machine_file")
'''
new_load = '''        absolute = path if path.is_absolute() else path.absolute()
        payload = _safe_machine_file(absolute, maximum=maximum, code="machine_file")
'''
if source.count(old_load) != 1:
    raise SystemExit("canonical loader replacement mismatch")
source = source.replace(old_load, new_load)

old_environment = '''def _decision_environment() -> dict[str, str]:
    return {
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONHASHSEED": "0",
        "PYTHONUTF8": "1",
    }
'''
new_environment = '''def _decision_environment() -> dict[str, str]:
    return {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        "PYTHONHASHSEED": "0",
        "PYTHONUTF8": "1",
    }
'''
if source.count(old_environment) != 1:
    raise SystemExit("decision environment replacement mismatch")
source = source.replace(old_environment, new_environment)

old_run = '''    temporary = Path(tempfile.mkdtemp(prefix=".shadow-decision.", dir=output.parent))
    try:
        child = temporary / "decision.json"
        deadline = start_lane_deadline(contract, "evidence-finalize")
        run = run_configured_gate(
            contract=contract,
            gate_id="evidence-finalize",
            phase="decision",
            argv=(
                sys.executable,
                "-m",
                "scripts.sdlc.workflow_orchestrator",
                "decision-child",
                "--repo-root",
                str(root),
                "--context",
                str(_safe_input(root, context_path)),
                "--collection",
                str(_safe_input(root, collection_path)),
                "--output",
                str(child),
            ),
            deadline=deadline,
            cwd=root,
            env=_decision_environment(),
            output_limit_bytes=65_536,
            termination_grace_seconds=0.25,
        )
        decision: ShadowDecision
'''
new_run = '''    try:
        collection_input = _safe_input(root, collection_path)
    except WorkflowOrchestratorError:
        decision = failure_shadow_decision(
            context=context, code="invalid-collection", result="EVIDENCE_MISMATCH"
        )
        decision = validate_shadow_decision(decision.as_dict(), contract=contract)
        _private_write(output, decision.as_dict())
        return decision
    temporary = Path(tempfile.mkdtemp(prefix=".shadow-decision.", dir=output.parent))
    try:
        child = temporary / "decision.json"
        try:
            deadline = start_lane_deadline(contract, "evidence-finalize")
            run = run_configured_gate(
                contract=contract,
                gate_id="evidence-finalize",
                phase="decision",
                argv=(
                    sys.executable,
                    "-m",
                    "scripts.sdlc.workflow_orchestrator",
                    "decision-child",
                    "--repo-root",
                    str(root),
                    "--context",
                    str(_safe_input(root, context_path)),
                    "--collection",
                    str(collection_input),
                    "--output",
                    str(child),
                ),
                deadline=deadline,
                cwd=root,
                env=_decision_environment(),
                output_limit_bytes=65_536,
                termination_grace_seconds=0.25,
            )
        except (GateRunError, OSError):
            run = GateRunResult(
                "evidence-finalize",
                "decision",
                "ENVIRONMENT_ERROR",
                "ENVIRONMENT_ERROR:evidence-finalize:decision:watchdog",
                None,
                0,
                "",
                "",
                False,
                False,
            )
        decision: ShadowDecision
'''
if source.count(old_run) != 1:
    raise SystemExit("bounded decision replacement mismatch")
source = source.replace(old_run, new_run)
SOURCE.write_text(source, encoding="utf-8")

tests = TEST.read_text(encoding="utf-8")
marker = "def test_canonical_loader_rejects_symlink_input("
if marker in tests:
    raise SystemExit("orchestrator hardening tests already present")
tests += '''


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
'''
TEST.write_text(tests, encoding="utf-8")
