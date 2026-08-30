"""Provider-free Step 20 proofs for the provider-result bridge."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from newsroom.control_plane.issue_790_disposition import (
    _issue_790_attempt_receipt_rows_for_event,
)
from newsroom.tests.test_issue_790_step16_activation import (
    _DISPOSITION,
    _EVENT_ID,
    _LEDGER,
    _insert_consumption,
    _prepare_recovery_store,
    _run_recovery,
    _seed_canary_event,
    _seed_primary_leaf,
    _table_count,
)


def test_attempt_receipt_inspection_resolves_event_through_ingest_id(
    tmp_path: Path,
) -> None:
    store = tmp_path / "inspection.sqlite3"
    connection = sqlite3.connect(store)
    connection.executescript(
        """
        CREATE TABLE model_work_envelopes(
            envelope_id TEXT PRIMARY KEY,
            cycle_id TEXT NOT NULL,
            record_json TEXT NOT NULL
        );
        CREATE TABLE unpublished_graphiti_attempt_receipts(
            ingest_id TEXT NOT NULL,
            attempt_number INTEGER NOT NULL,
            receipt_digest TEXT NOT NULL,
            receipt_json TEXT NOT NULL,
            at TEXT,
            PRIMARY KEY(ingest_id, attempt_number)
        );
        """
    )
    event_id = "sha256:" + "20" * 32
    ingest_id = "step20-ingest"
    receipt = {"outcome": "COMPLETE", "proposal_count": 0}
    connection.execute(
        "INSERT INTO model_work_envelopes VALUES(?,?,?)",
        (
            "envelope-1",
            event_id,
            json.dumps({"ingest_id": ingest_id}),
        ),
    )
    connection.execute(
        "INSERT INTO unpublished_graphiti_attempt_receipts VALUES(?,?,?,?,?)",
        (
            ingest_id,
            1,
            "sha256:" + "21" * 32,
            json.dumps(receipt),
            "2026-08-30T00:00:00.000000Z",
        ),
    )
    connection.commit()
    connection.close()

    rows = _issue_790_attempt_receipt_rows_for_event(store, event_id=event_id)

    assert rows == [("sha256:" + "21" * 32, json.dumps(receipt))]


def test_store_copy_rehearsal_seals_truthful_success_without_wider_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, activated = _prepare_recovery_store(tmp_path)
    _seed_canary_event(
        store,
        state="TERMINAL",
        attempt_count=1,
        provider_dispatched=True,
        terminal_at="2026-08-29T11:00:03.000000Z",
        event_id=_EVENT_ID,
        ledger_seq=_LEDGER,
    )
    _insert_consumption(
        store,
        plan_digest=str(activated["plan"]["canonical_digest"]),
    )
    _seed_primary_leaf(store, terminal=True)

    receipt = _run_recovery(
        tmp_path,
        monkeypatch,
        store=store,
        activated=activated,
        consume_calls=[],
        qualify_calls=[],
    )

    backup = tmp_path / "backup-0.sqlite3"
    assert backup.is_file()
    connection = sqlite3.connect(backup)
    assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    connection.close()
    assert receipt["canary_evidence_passed"] is True
    assert receipt["outcome"]["result_class"] == "TRUTHFUL_PROVIDER_SUCCESS"
    assert receipt["event_after"]["event"]["state"] == "TERMINAL"
    assert receipt["outcome"]["attempt_count"] == 1
    assert receipt["publication_performed"] is False
    assert receipt["public_dispatch_performed"] is False
    assert receipt["backlog_drain_performed"] is False
    assert receipt["worker_remained_unloaded"] is True
    assert receipt["retry_authorised"] is False
    assert receipt["disposition_digest"] == _DISPOSITION
    assert _table_count(store, "issue_790_bounded_canary_outcomes") == 1
