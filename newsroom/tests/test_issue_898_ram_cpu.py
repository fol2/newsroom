from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from newsroom.control_plane.paths import CANONICAL_PROVING_STORE
from newsroom.control_plane import cycle as cycle_module
from newsroom.research.issue_898_ram_cpu import (
    UNOBSERVED,
    canonical_json,
    case_admission_generation,
    case_resolve_event,
    decide,
    digest_text,
    fixture_rows,
    measure,
    prepare_event_identity,
    raw_http_cutoff,
    refuse_canonical_store,
    scan_observations,
    sqlite_backup_snapshot,
    summarise_case,
    CLOCK,
    write_proving_store,
    write_unpublished_store,
)


def test_refuse_canonical_store() -> None:
    with pytest.raises(RuntimeError, match="canonical store"):
        refuse_canonical_store(CANONICAL_PROVING_STORE)


def test_unobserved_is_not_zero() -> None:
    summary = summarise_case(
        "missing",
        [{"status": UNOBSERVED, "outcome": {}}],
    )
    assert summary["max_peak_rss_bytes"] is UNOBSERVED
    assert summary["median_cpu_seconds"] is UNOBSERVED
    assert summary["max_peak_rss_bytes"] != 0


def test_measure_primary_disables_tracemalloc() -> None:
    result = measure(lambda: {"ok": True})
    assert result["tracemalloc_enabled"] is False
    assert result["tracemalloc_peak_bytes"] is UNOBSERVED
    assert result["tracemalloc_current_bytes"] is UNOBSERVED


def test_sqlite_backup_is_consistent_and_not_size_reuse(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE proving_observations(body BLOB)")
    connection.execute("INSERT INTO proving_observations VALUES(?)", (b"abc",))
    connection.commit()
    connection.close()
    first = tmp_path / "snap-a.sqlite3"
    second = tmp_path / "snap-b.sqlite3"
    meta_a = sqlite_backup_snapshot(source, first)
    meta_b = sqlite_backup_snapshot(source, second)
    assert meta_a["status"] == "COPIED"
    assert meta_a["reused_existing_copy"] is False
    assert meta_a["method"] == "sqlite3.Connection.backup"
    assert meta_a["copy_digest"] == meta_b["copy_digest"]
    assert meta_a["observation_count"] == 1
    copied = sqlite3.connect(first)
    assert copied.execute("SELECT body FROM proving_observations").fetchone()[0] == b"abc"
    copied.close()


def test_malformed_and_empty_do_not_claim_queue(tmp_path: Path) -> None:
    unpublished = tmp_path / "unpublished.sqlite3"
    write_unpublished_store(unpublished)
    before = unpublished.stat().st_mtime_ns
    for kind in ("malformed", "empty"):
        proving = tmp_path / f"{kind}.sqlite3"
        write_proving_store(proving, fixture_rows(kind))
        event = prepare_event_identity(str(proving), CLOCK)
        result = case_resolve_event(str(proving), event)
        assert result["status"] in {"OK", "ERROR"}
        assert result["outcome"].get("queue_claimed") is not True
    connection = sqlite3.connect(unpublished)
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    connection.close()
    if "unpublished_graphiti_revision_events" in tables:
        connection = sqlite3.connect(unpublished)
        claimed = connection.execute(
            "SELECT COUNT(*) FROM unpublished_graphiti_revision_events "
            "WHERE state!='QUEUED'"
        ).fetchone()[0]
        connection.close()
        assert claimed == 0
    assert unpublished.stat().st_mtime_ns == before


def test_resolve_uses_prepared_event_and_one_runtime_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proving = tmp_path / "proving.sqlite3"
    write_proving_store(proving, fixture_rows("solo"))
    event = prepare_event_identity(str(proving), CLOCK)
    assert event["status"] == "OK"
    assert event["expected_selected_count"] >= 1
    calls: list[int] = []
    real = cycle_module._resolve_graphiti_event_units

    def wrapped(**kwargs: object) -> object:
        calls.append(1)
        return real(**kwargs)

    monkeypatch.setattr(cycle_module, "_resolve_graphiti_event_units", wrapped)
    result = case_resolve_event(str(proving), event)
    assert calls == [1]
    assert result["status"] == "OK"
    assert result["outcome"]["queue_claimed"] is False
    assert result["outcome"]["selected_unit_count"] >= 1
    assert result["tracemalloc_peak_bytes"] is UNOBSERVED


def test_resolve_does_not_open_canonical(tmp_path: Path) -> None:
    proving = tmp_path / "proving.sqlite3"
    write_proving_store(proving, fixture_rows("solo"))
    event = prepare_event_identity(str(proving), CLOCK)
    result = case_resolve_event(str(proving), event)
    assert result["status"] == "OK"
    assert result["outcome"]["queue_claimed"] is False
    assert result["outcome"]["selected_unit_count"] >= 1


def test_observation_scan_digest_is_stable(tmp_path: Path) -> None:
    proving = tmp_path / "proving.sqlite3"
    write_proving_store(proving, fixture_rows("representative"))
    cutoff = raw_http_cutoff(CLOCK)
    first = scan_observations(str(proving), cutoff)
    second = scan_observations(str(proving), cutoff)
    assert first["manifest_digest"] == second["manifest_digest"]
    assert first["row_count"] >= 1
    assert first["schema"] == "newsroom.issue-898.observation-scan.v1"
    assert first["manifest_digest"].startswith("sha256:")


def test_canonical_json_orders_keys() -> None:
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    assert digest_text(canonical_json({"a": 1})) == digest_text('{"a":1}')


def test_admission_generation_is_provider_free() -> None:
    result = case_admission_generation()
    assert result["status"] == "OK"
    assert result["outcome"]["generation_id_present"] is True


def test_decide_holds_without_rust() -> None:
    decision = decide(
        {
            "A2_import_cycle": {
                "max_peak_rss_bytes": 80 * 1024 * 1024,
                "median_cpu_seconds": 0.1,
                "max_retained_rss_bytes": 70 * 1024 * 1024,
            },
            "C5_load_graphiti_units": {
                "max_peak_rss_bytes": 400 * 1024 * 1024,
                "median_cpu_seconds": 1.2,
                "max_retained_rss_bytes": 350 * 1024 * 1024,
            },
        }
    )
    assert decision["go_or_no_go"] == "HOLD"
    assert "exact row selection" not in decision["reason"]


def test_decide_go_when_rust_scan_clears_gate() -> None:
    digest_run = {
        "status": "OK",
        "outcome": {"manifest_digest": "sha256:" + ("ab" * 32)},
    }
    decision = decide(
        {
            "R0_rust_process_baseline": {
                "max_peak_rss_bytes": 2 * 1024 * 1024,
                "runs": [{"status": "OK", "outcome": {}}],
            },
            "R1_python_observation_scan": {
                "max_peak_rss_bytes": 400 * 1024 * 1024,
                "median_cpu_seconds": 2.0,
                "runs": [digest_run],
            },
            "R1_rust_observation_scan": {
                "max_peak_rss_bytes": 40 * 1024 * 1024,
                "median_cpu_seconds": 0.4,
                "runs": [digest_run],
            },
            "R1_rust_e2e_parent": {
                "max_peak_rss_bytes": 50 * 1024 * 1024,
                "median_cpu_seconds": 0.5,
                "runs": [digest_run],
            },
            "R2_bounded_candidate": {
                "runs": [{"status": "HOLD", "mode": "r2", "outcome": {}}],
            },
        }
    )
    assert decision["go_or_no_go"] == "GO"
    assert decision["unit_parity_claimed"] is False


def test_decide_no_go_when_rust_does_not_clear_gate() -> None:
    digest_run = {
        "status": "OK",
        "outcome": {"manifest_digest": "sha256:" + ("ab" * 32)},
    }
    decision = decide(
        {
            "R0_rust_process_baseline": {
                "max_peak_rss_bytes": 2 * 1024 * 1024,
                "runs": [{"status": "OK", "outcome": {}}],
            },
            "R1_python_observation_scan": {
                "max_peak_rss_bytes": 100 * 1024 * 1024,
                "median_cpu_seconds": 1.0,
                "runs": [digest_run],
            },
            "R1_rust_observation_scan": {
                "max_peak_rss_bytes": 95 * 1024 * 1024,
                "median_cpu_seconds": 0.9,
                "runs": [digest_run],
            },
            "R1_rust_e2e_parent": {
                "max_peak_rss_bytes": 98 * 1024 * 1024,
                "median_cpu_seconds": 1.0,
                "runs": [digest_run],
            },
        }
    )
    assert decision["go_or_no_go"] == "NO_GO"
