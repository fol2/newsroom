from __future__ import annotations

from pathlib import Path

SOURCE = Path("scripts/sdlc/workflow_orchestrator.py")
TEST = Path("newsroom/tests/test_sdlc_workflow_orchestrator.py")

source = SOURCE.read_text(encoding="utf-8")
old = '''                decision = validate_shadow_decision(
                    _canonical_load(child), contract=contract
                )
            except (WorkflowOrchestratorError, ShadowDecisionError):
'''
new = '''                candidate = validate_shadow_decision(
                    _canonical_load(child), contract=contract
                )
                if candidate.context != context:
                    raise WorkflowOrchestratorError("decision_context")
                decision = candidate
            except (WorkflowOrchestratorError, ShadowDecisionError):
'''
if source.count(old) != 1:
    raise SystemExit("decision context replacement mismatch")
SOURCE.write_text(source.replace(old, new), encoding="utf-8")

tests = TEST.read_text(encoding="utf-8")
old_import = '''from dataclasses import dataclass
'''
new_import = '''from dataclasses import dataclass, replace
'''
if tests.count(old_import) != 1:
    raise SystemExit("dataclass import mismatch")
tests = tests.replace(old_import, new_import)
marker = "def test_parent_rejects_child_decision_for_another_context("
if marker in tests:
    raise SystemExit("context test already present")
tests += '''


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
'''
TEST.write_text(tests, encoding="utf-8")
