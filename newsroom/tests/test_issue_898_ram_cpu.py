from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from newsroom.control_plane.paths import CANONICAL_PROVING_STORE
from newsroom.research.issue_898_ram_cpu import (
    UNOBSERVED,
    decide,
    fixture_rows,
    refuse_canonical_store,
    summarise_case,
    write_proving_store,
    write_unpublished_store,
    case_resolve_event,
    case_admission_generation,
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


def test_malformed_and_empty_do_not_claim_queue(tmp_path: Path) -> None:
    unpublished = tmp_path / "unpublished.sqlite3"
    write_unpublished_store(unpublished)
    before = unpublished.stat().st_mtime_ns
    for kind in ("malformed", "empty"):
        proving = tmp_path / f"{kind}.sqlite3"
        write_proving_store(proving, fixture_rows(kind))
        result = case_resolve_event(str(proving))
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


def test_resolve_does_not_open_canonical(tmp_path: Path) -> None:
    proving = tmp_path / "proving.sqlite3"
    write_proving_store(proving, fixture_rows("solo"))
    result = case_resolve_event(str(proving))
    assert result["status"] == "OK"
    assert result["outcome"]["queue_claimed"] is False
    assert result["outcome"]["unit_count"] >= 1
    assert result["outcome"]["selected_unit_count"] >= 1


def test_admission_generation_is_provider_free() -> None:
    result = case_admission_generation()
    assert result["status"] == "OK"
    assert result["outcome"]["generation_id_present"] is True


def test_go_gate_is_no_go_when_h2_leads() -> None:
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
            "C7_admission_generation": {
                "max_peak_rss_bytes": 90 * 1024 * 1024,
                "median_cpu_seconds": 0.2,
                "max_retained_rss_bytes": 85 * 1024 * 1024,
            },
        }
    )
    assert decision["go_or_no_go"] == "NO_GO"
    assert decision["h2_leads"] is True
    assert "exact row selection" in decision["reason"]
