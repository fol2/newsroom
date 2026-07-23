from __future__ import annotations

from pathlib import Path

LANE = Path("scripts/sdlc/workflow_lane.py")
BUDGET = Path("scripts/sdlc/workflow_budget.py")
LANE_TEST = Path("newsroom/tests/test_sdlc_workflow_lane.py")

lane = LANE.read_text(encoding="utf-8")
old_lane = '''_MAX_CACHE_KEY_CHARS = 2048
'''
new_lane = '''_MAX_CACHE_KEY_CHARS = 512
'''
if lane.count(old_lane) != 1:
    raise SystemExit("cache key limit mismatch")
LANE.write_text(lane.replace(old_lane, new_lane), encoding="utf-8")

budget = BUDGET.read_text(encoding="utf-8")
old_budget = '''                    value, "cache_environment", maximum=2048
'''
new_budget = '''                    value, "cache_environment", maximum=512
'''
if budget.count(old_budget) != 1:
    raise SystemExit("cache wrapper limit mismatch")
BUDGET.write_text(budget.replace(old_budget, new_budget), encoding="utf-8")

tests = LANE_TEST.read_text(encoding="utf-8")
marker = '''    monkeypatch.setenv("NEWSROOM_SDLC_CACHE_KEY", "bad\\nkey")
    monkeypatch.setenv("NEWSROOM_SDLC_CACHE_HIT", "false")
    with pytest.raises(WorkflowLaneError, match="cache_environment"):
        lane_module._cache_evidence()
'''
replacement = '''    monkeypatch.setenv("NEWSROOM_SDLC_CACHE_KEY", "bad\\nkey")
    monkeypatch.setenv("NEWSROOM_SDLC_CACHE_HIT", "false")
    with pytest.raises(WorkflowLaneError, match="cache_environment"):
        lane_module._cache_evidence()

    monkeypatch.setenv("NEWSROOM_SDLC_CACHE_KEY", "x" * 513)
    with pytest.raises(WorkflowLaneError, match="cache_environment"):
        lane_module._cache_evidence()
'''
if tests.count(marker) != 1:
    raise SystemExit("cache limit test insertion mismatch")
LANE_TEST.write_text(tests.replace(marker, replacement), encoding="utf-8")
