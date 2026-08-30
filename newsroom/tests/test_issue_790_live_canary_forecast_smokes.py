"""Provider-free forecast smokes that gate #790 live canary preflight."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.issue_790_live_canary_preflight import (
    STEP21_FULL_PATH_TEST,
    _blocker_smokes,
    _focus_gate_hits,
    _graphiti_runtime_status,
    _inspection_sql_smoke,
    _invalid_sha256_paths,
    _latest_failure_red_green,
    _retry_exclusion_append_smoke,
)


def test_issue_790_forecast_blocker_smokes_all_pass() -> None:
    root = Path(__file__).resolve().parents[2]
    rows = _blocker_smokes(root)
    failed = [(name, detail) for name, ok, detail in rows if not ok]
    assert not failed, failed
    assert len(rows) >= 26
    names = {name for name, _, _ in rows}
    assert "B10 TEMPORAL: REFERENCE_TIME stuffing ignored; projected null/cues OK" in names
    assert "B14 dry-replay Step 14 stuffing ignored → projected null success" in names
    assert "B21 Step 19 execute→ingest→bind accepts COMPLETE+0" in names
    assert (
        "B22 Steps 20-21 marked and unmarked COMPLETE+0 avoid AMBIGUOUS_EFFECT"
        in names
    )
    assert "B23 failure/blocked/proposal-bearing ambiguity remains fail-closed" in names


def test_o07_accepts_only_exact_tip_focus_gates() -> None:
    tip = "a" * 40
    common = {
        "status": "completed",
        "conclusion": "success",
        "head_sha": tip,
    }
    assert _focus_gate_hits(
        [
            {**common, "name": "full-deterministic-health"},
            {**common, "name": "test"},
        ],
        tip=tip,
    ) == []
    assert _focus_gate_hits(
        [
            {**common, "name": "focus-gates", "head_sha": "b" * 40},
            {**common, "name": "focus-gates"},
        ],
        tip=tip,
    ) == [{**common, "name": "focus-gates"}]


def test_owner_activation_digest_gate_requires_exact_lowercase_sha256() -> None:
    valid = "sha256:" + "ab" * 32
    assert _invalid_sha256_paths(
        {
            "activation_digest": valid,
            "approval_payload": {"checked_candidate_digest": valid},
        }
    ) == []
    invalid = _invalid_sha256_paths(
        {
            "activation_digest": "sha256:" + "ab" * 31,
            "approval_payload": {"checked_candidate_digest": "sha256:" + "A" * 64},
        }
    )
    assert invalid == [
        "$.activation_digest",
        "$.approval_payload.checked_candidate_digest",
    ]


def test_pinned_runtime_gate_uses_real_adapter_import_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from newsroom.graphiti_adapter import real
    import scripts.issue_790_live_canary_preflight as preflight

    monkeypatch.setattr(
        real,
        "_load_graphiti",
        lambda: SimpleNamespace(Graphiti=object()),
    )
    monkeypatch.setattr(
        preflight.importlib.metadata,
        "version",
        lambda _name: "0.29.3",
    )
    ok, detail = _graphiti_runtime_status()
    assert ok is True
    assert "graphiti-core 0.29.3" in detail

    monkeypatch.setattr(
        preflight.importlib.metadata,
        "version",
        lambda _name: "0.29.2",
    )
    assert _graphiti_runtime_status()[0] is False


def test_latest_live_failure_requires_later_red_and_exact_main_green() -> None:
    tip = "a" * 40
    failure = {
        "created_at": "2026-08-30T21:32:36Z",
        "body": "## Step 21 live canary — **FAIL**\n- event: ledger `13361`",
    }
    diagnosis = {
        "created_at": "2026-08-30T21:38:43Z",
        "body": (
            "## Diagnosis\nFull-path red for ledger 13361\n"
            "Red commit: `" + "b" * 40 + "`\n"
            f"`uv run --frozen pytest -q {STEP21_FULL_PATH_TEST}`"
        ),
    }
    green = {
        "created_at": "2026-08-30T21:47:39Z",
        "body": (
            f"## Full-path repair\nexact-main {tip}; ledger 13361; "
            "Focus Gates succeeded"
        ),
    }
    assert _latest_failure_red_green([failure, diagnosis], tip=tip)[0] is False
    assert _latest_failure_red_green([failure, diagnosis, green], tip=tip) == (
        True,
        f"ledger 13361 red→green on {tip[:12]}",
    )
    later_failure = {
        "created_at": "2026-08-30T22:00:00Z",
        "body": "## Step 22 live canary — FAILED\nledger 14000",
    }
    assert _latest_failure_red_green(
        [failure, diagnosis, green, later_failure],
        tip=tip,
    )[0] is False


def test_inspection_sql_uses_ingest_identity_without_receipt_event_column() -> None:
    assert _inspection_sql_smoke() == (
        True,
        "receipt schema has ingest_id and no event_id",
    )


def test_retry_exclusion_apply_appends_all_exhausted_events_idempotently() -> None:
    ok, detail = _retry_exclusion_append_smoke()
    assert ok is True
    assert "13361" in detail
    assert "replay=stable" in detail
