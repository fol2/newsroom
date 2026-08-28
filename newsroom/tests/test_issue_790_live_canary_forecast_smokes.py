"""Provider-free forecast smokes that gate #790 live canary preflight."""

from __future__ import annotations

from pathlib import Path

from scripts.issue_790_live_canary_preflight import _blocker_smokes


def test_issue_790_forecast_blocker_smokes_all_pass() -> None:
    root = Path(__file__).resolve().parents[2]
    rows = _blocker_smokes(root)
    failed = [(name, detail) for name, ok, detail in rows if not ok]
    assert not failed, failed
    assert len(rows) >= 20
    names = {name for name, _, _ in rows}
    assert "B10 TEMPORAL: REFERENCE_TIME stuffing rejected; null bounds OK" in names
    assert (
        "B14 dry-replay Step 14 REFERENCE_TIME valid_at → TEMPORAL_INVALID; null OK"
        in names
    )
