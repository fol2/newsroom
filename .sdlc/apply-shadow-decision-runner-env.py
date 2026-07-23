from __future__ import annotations

from pathlib import Path

SOURCE = Path("scripts/sdlc/shadow_decision.py")
TEST = Path("newsroom/tests/test_sdlc_shadow_decision.py")

source = SOURCE.read_text(encoding="utf-8")
old_source = '''        or receipt.consumer_job_id != context.job_id
        or receipt.workflow_ref != context.workflow_ref
'''
new_source = '''        or receipt.consumer_job_id != context.job_id
        or receipt.consumer_runner_environment != context.runner_environment
        or receipt.workflow_ref != context.workflow_ref
'''
if source.count(old_source) != 1:
    raise SystemExit("source runner-environment replacement mismatch")
SOURCE.write_text(source.replace(old_source, new_source), encoding="utf-8")

tests = TEST.read_text(encoding="utf-8")
old_fixture = '''    consumer_job_id: str = "decision"
    workflow_ref: str = "fol2/newsroom/.github/workflows/evidence.yml@refs/pull/10/merge"
'''
new_fixture = '''    consumer_job_id: str = "decision"
    consumer_runner_environment: str = "github-hosted"
    workflow_ref: str = "fol2/newsroom/.github/workflows/evidence.yml@refs/pull/10/merge"
'''
if tests.count(old_fixture) != 1:
    raise SystemExit("test fixture runner-environment replacement mismatch")
tests = tests.replace(old_fixture, new_fixture)
marker = "def test_consumer_runner_environment_must_match_decision_context("
if marker in tests:
    raise SystemExit("runner-environment test already present")
tests += '''


def test_consumer_runner_environment_must_match_decision_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = _route()
    core = _lane("core", route)
    mismatched = replace(
        core,
        receipt=replace(
            core.receipt,
            consumer_runner_environment="self-hosted",
        ),
    )
    _patch_lane_validator(monkeypatch, mismatched)

    with pytest.raises(ShadowDecisionError, match="lane_context"):
        aggregate_shadow_decision(
            context=_context(),
            event=_event(),
            core=mismatched,  # type: ignore[arg-type]
            service=None,
            contract=_contract(),
        )
'''
TEST.write_text(tests, encoding="utf-8")
