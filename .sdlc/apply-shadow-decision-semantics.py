from __future__ import annotations

from pathlib import Path

SOURCE = Path("scripts/sdlc/shadow_decision.py")
TEST = Path("newsroom/tests/test_sdlc_shadow_decision.py")

source = SOURCE.read_text(encoding="utf-8")
old = '''        if self.lanes:
            if self.event is None or "core" not in set(lane_ids):
                raise ShadowDecisionError("lane_event")
            if (self.result == "PASS") is not (self.first_failure is None):
                raise ShadowDecisionError("first_failure")
        elif (
            self.event is not None
            or self.result == "PASS"
            or self.first_failure is None
            or self.first_failure.lane_id != "decision"
        ):
            raise ShadowDecisionError("failure_record")
'''
new = '''        if self.lanes:
            if self.event is None or "core" not in set(lane_ids):
                raise ShadowDecisionError("lane_event")
            if (self.result == "PASS") is not (self.first_failure is None):
                raise ShadowDecisionError("first_failure")
            if self.first_failure is not None:
                if self.first_failure.result != self.result:
                    raise ShadowDecisionError("first_failure")
                expected_reason = (
                    f"{self.result}:decision:{self.first_failure.lane_id}:"
                    f"{self.first_failure.gate_id}:{self.first_failure.phase}"
                )
                if self.result_reason != expected_reason:
                    raise ShadowDecisionError("first_failure")
        elif (
            self.event is not None
            or self.result == "PASS"
            or self.first_failure is None
            or self.first_failure.lane_id != "decision"
            or self.first_failure.result != self.result
            or self.first_failure.result_reason != self.result_reason
        ):
            raise ShadowDecisionError("failure_record")
'''
if source.count(old) != 1:
    raise SystemExit("source semantic replacement mismatch")
SOURCE.write_text(source.replace(old, new), encoding="utf-8")

tests = TEST.read_text(encoding="utf-8")
marker = "def test_direct_failure_summary_must_match_top_level_decision("
if marker in tests:
    raise SystemExit("semantic test already present")
tests += '''


def test_direct_failure_summary_must_match_top_level_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = _route()
    failed_lane = _lane(
        "core",
        route,
        gates=(
            _gate("source-integrity", "source"),
            _gate("core-deterministic", "tests", required_skip=True),
        ),
    )
    _patch_lane_validator(monkeypatch, failed_lane)
    decision = aggregate_shadow_decision(
        context=_context(),
        event=_event(),
        core=failed_lane,  # type: ignore[arg-type]
        service=None,
        contract=_contract(),
    )
    assert decision.first_failure is not None
    mismatched = replace(
        decision.first_failure,
        result="ENVIRONMENT_ERROR",
        result_reason="ENVIRONMENT_ERROR:core:job",
    )
    with pytest.raises(ShadowDecisionError, match="first_failure"):
        replace(decision, first_failure=mismatched)

    typed = failure_shadow_decision(context=_context(), code="missing-core")
    assert typed.first_failure is not None
    changed = replace(
        typed.first_failure,
        result_reason="EVIDENCE_MISMATCH:decision:other",
    )
    with pytest.raises(ShadowDecisionError, match="failure_record"):
        replace(typed, first_failure=changed)
'''
TEST.write_text(tests, encoding="utf-8")
