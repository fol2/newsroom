from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from newsroom.authority.canonical import digest_canonical
from newsroom.control_plane.graphiti_events import (
    GRAPHITI_EVENT_PROJECTION_GENERATION,
    GRAPHITI_EVENT_PROJECTOR_VERSION,
)
from newsroom.control_plane.graphiti_steady_state import (
    AdmissionRuntimeComposition,
    build_graphiti_steady_state_packet,
    write_content_addressed_packet,
)
from newsroom.control_plane.read_only_snapshot import read_only_snapshot
from newsroom.control_plane.store import connect

NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)


def _stores(tmp_path: Path) -> tuple[Path, Path, sqlite3.Connection]:
    proving = tmp_path / "proving.sqlite3"
    sqlite3.connect(proving).execute(
        "CREATE TABLE proof(value TEXT)"
    ).connection.close()
    unpublished = tmp_path / "unpublished.sqlite3"
    connection = connect(str(unpublished))
    return proving, unpublished, connection


def _terminal_zero_proposal(connection: sqlite3.Connection) -> None:
    at = "2026-09-01T12:00:00.000000Z"
    ledger_digest = "sha256:" + "1" * 64
    payload_digest = "sha256:" + "2" * 64
    manifest = {
        "event_type": "EFFECTIVE_SOURCE_REVISION_LANDED",
        "ledger_seq": 1,
        "ledger_digest": ledger_digest,
        "landed_ingest_ids": ["ingest-1"],
        "landed_payload_digest": payload_digest,
        "unit_refs": [],
    }
    receipt = {"raw_output_digest": "sha256:" + "3" * 64, "proposals": []}
    connection.execute(
        "INSERT INTO ledger(seq,at,kind,payload_digest,payload_json,prev_digest,"
        "digest) VALUES(1,?,?,?,?,?,?)",
        (
            at,
            "EFFECTIVE_REVISION_LANDED",
            payload_digest,
            "{}",
            "GENESIS",
            ledger_digest,
        ),
    )
    connection.execute(
        "INSERT INTO unpublished_effective_revision_landed("
        "source_id,item_key,revision_digest,published_at,updated_at,"
        "first_observed_at,ingest_ids_json,legacy_v10,payload_digest,"
        "ledger_digest,at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            "source",
            "item",
            "revision",
            "",
            "",
            at,
            '["ingest-1"]',
            0,
            payload_digest,
            ledger_digest,
            at,
        ),
    )
    connection.execute(
        "INSERT INTO unpublished_graphiti_revision_events("
        "event_id,ledger_seq,ledger_digest,source_id,item_key,revision_digest,"
        "published_at,updated_at,landed_at,manifest_json,manifest_digest,"
        "unit_count,projector_version,projection_generation,state,attempt_count,"
        "available_at,provider_dispatched,terminal_at,proposal_count) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            ledger_digest,
            1,
            ledger_digest,
            "source",
            "item",
            "revision",
            "",
            "",
            at,
            json.dumps(manifest, sort_keys=True),
            digest_canonical(manifest),
            1,
            GRAPHITI_EVENT_PROJECTOR_VERSION,
            GRAPHITI_EVENT_PROJECTION_GENERATION,
            "TERMINAL",
            1,
            at,
            1,
            at,
            0,
        ),
    )
    connection.execute(
        "INSERT INTO unpublished_graphiti_ingest("
        "ingest_id,source_id,item_key,outcome,proposal_count,entity_count,"
        "relation_count,failure_code,temporal_basis,reference_time,generation_id,"
        "receipt_digest,at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "ingest-1",
            "source",
            "item",
            "COMPLETE",
            0,
            0,
            0,
            "",
            "PUBLISHED_AT",
            at,
            "generation",
            receipt["raw_output_digest"],
            at,
        ),
    )
    connection.execute(
        "INSERT INTO unpublished_graphiti_receipts(ingest_id,receipt_json) VALUES(?,?)",
        ("ingest-1", json.dumps(receipt, sort_keys=True)),
    )
    connection.commit()


def _packet(proving: Path, unpublished: Path, **kwargs: object) -> dict[str, object]:
    return build_graphiti_steady_state_packet(
        proving_store=proving,
        unpublished_store=unpublished,
        head_sha="head",
        tree_sha="tree",
        observed_at=NOW,
        **kwargs,
    )


def test_wal_snapshot_does_not_change_source_files(tmp_path: Path) -> None:
    path = tmp_path / "wal.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE evidence(value TEXT)")
    connection.execute("INSERT INTO evidence VALUES('retained')")
    connection.commit()
    paths = (path, Path(f"{path}-wal"), Path(f"{path}-shm"))
    before = tuple(item.read_bytes() for item in paths)

    with read_only_snapshot(path) as snapshot:
        assert snapshot.connection.execute(
            "SELECT value FROM evidence"
        ).fetchone() == ("retained",)
        assert snapshot.connection.execute("PRAGMA query_only").fetchone() == (1,)

    assert tuple(item.read_bytes() for item in paths) == before
    connection.close()


def test_default_uncomposed_is_explicit_no_go(tmp_path: Path) -> None:
    proving, unpublished, connection = _stores(tmp_path)
    connection.close()

    packet = _packet(proving, unpublished)

    assert packet["verdict"] == "NO_GO"
    assert packet["readiness"] == "READY_FOR_F4_ENGINEERING_GAP"
    assert "ADMISSION_RUNTIME_UNCOMPOSED" in packet["blockers"]
    assert packet["non_effects"] == {
        "provider_calls": 0,
        "store_mutations": 0,
        "service_loads": 0,
        "publication_effects": 0,
        "production_admission_effects": 0,
    }


def test_zero_proposal_terminal_receipt_is_success(tmp_path: Path) -> None:
    proving, unpublished, connection = _stores(tmp_path)
    _terminal_zero_proposal(connection)
    connection.close()

    packet = _packet(
        proving,
        unpublished,
        admission_runtime=AdmissionRuntimeComposition.COMPOSED,
    )

    assert packet["terminal_receipts"]["zero_proposal_success_count"] == 1
    assert packet["terminal_receipts"]["integrity_failures"] == []
    assert packet["landed_event_accounting"]["one_to_one"] is True


def test_tampered_receipt_is_machine_readable_no_go(tmp_path: Path) -> None:
    proving, unpublished, connection = _stores(tmp_path)
    _terminal_zero_proposal(connection)
    connection.execute(
        "UPDATE unpublished_graphiti_receipts SET receipt_json=? "
        "WHERE ingest_id='ingest-1'",
        (json.dumps({"raw_output_digest": "tampered", "proposals": []}),),
    )
    connection.commit()
    connection.close()

    packet = _packet(
        proving,
        unpublished,
        admission_runtime=AdmissionRuntimeComposition.COMPOSED,
    )

    assert packet["verdict"] == "NO_GO"
    assert "TERMINAL_RECEIPT_INTEGRITY_FAILURE" in packet["blockers"]
    assert packet["terminal_receipts"]["integrity_failures"] == [
        {"ingest_id": "ingest-1", "reason": "RECEIPT_DIGEST_CONTRADICTION"}
    ]


def test_digest_is_stable_and_output_is_create_exclusive(tmp_path: Path) -> None:
    proving, unpublished, connection = _stores(tmp_path)
    connection.close()
    first = _packet(proving, unpublished)
    second = _packet(proving, unpublished)

    assert first == second
    output = write_content_addressed_packet(first, tmp_path / "packets")
    assert output.name.endswith(
        f"{str(first['packet_digest']).removeprefix('sha256:')}.json"
    )
    with pytest.raises(FileExistsError):
        write_content_addressed_packet(first, tmp_path / "packets")
