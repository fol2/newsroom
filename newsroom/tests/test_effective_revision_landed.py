from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes, digest_canonical
from newsroom.control_plane.cycle import run_cycle
from newsroom.control_plane.store import (
    EFFECTIVE_REVISION_LANDED,
    connect,
    effective_revision_landed_payload,
    emit_effective_revision_landed,
    list_landed_revisions,
)
from newsroom.control_plane.writer import FixtureWriter
from newsroom.effective_revision import (
    EffectiveRevisionIdentity,
    create_effective_revision_schema,
    retain_observation_revision_first_seen,
)
from newsroom.increment9.proving import PROVING_GATES, SOURCE_URLS
from newsroom.tests.test_control_plane_private_beta import _cycle_rights_inventory

_URL = SOURCE_URLS["UK-01"]
_CLOCK = datetime(2026, 8, 21, tzinfo=UTC)


def _atom_feed(count: int) -> bytes:
    entries = "".join(
        f"<entry><id>{ordinal}</id><title>Item {ordinal}</title></entry>"
        for ordinal in range(count)
    )
    return f"<feed>{entries}</feed>".encode()


def _add_proving_run(
    proving: Path,
    *,
    run_id: str,
    body: bytes,
    fetched_at: str,
    rights_now: str = "2026-08-20T00:00:00.000000Z",
) -> None:
    connection = sqlite3.connect(proving)
    create_effective_revision_schema(connection)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS proving_runs(
            run_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            publication INTEGER NOT NULL DEFAULT 0,
            public_dispatch INTEGER NOT NULL DEFAULT 0,
            openrouter_invoked INTEGER NOT NULL DEFAULT 0,
            spend_gbp_minor INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS proving_observations(
            source_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            url TEXT NOT NULL,
            status_code INTEGER NOT NULL,
            body_digest TEXT NOT NULL,
            body BLOB NOT NULL,
            item_count INTEGER NOT NULL,
            error TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS proving_gates(
            run_id TEXT NOT NULL,
            gate_id TEXT NOT NULL,
            status TEXT NOT NULL,
            reason TEXT NOT NULL,
            PRIMARY KEY(run_id, gate_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS proving_rights_packets(
            run_id TEXT NOT NULL,
            gate_id TEXT NOT NULL,
            packet_digest TEXT NOT NULL,
            packet_json TEXT NOT NULL,
            assessed_at TEXT NOT NULL,
            PRIMARY KEY(run_id, gate_id)
        )
        """
    )
    connection.execute(
        """
        INSERT INTO proving_runs(
            run_id, started_at, publication, public_dispatch,
            openrouter_invoked, spend_gbp_minor
        ) VALUES(?,?,0,0,0,0)
        """,
        (run_id, fetched_at),
    )
    connection.execute(
        "INSERT INTO proving_observations VALUES(?,?,?,?,?,?,?,?,?)",
        (
            "UK-01",
            run_id,
            fetched_at,
            _URL,
            200,
            digest_bytes(body),
            body,
            1,
            None,
        ),
    )
    retain_observation_revision_first_seen(
        connection,
        source_id="UK-01",
        url=_URL,
        body=body,
        observed_at=fetched_at,
    )
    for gate_id in PROVING_GATES:
        if gate_id.startswith("RIGHTS_") and gate_id != "RIGHTS_UK-01":
            continue
        connection.execute(
            "INSERT INTO proving_gates VALUES(?,?,?,?)",
            (run_id, gate_id, "PASS", "fixture"),
        )
    packet = _cycle_rights_inventory("RIGHTS_UK-01")
    packet["now"] = rights_now
    packet_bytes = canonical_json_bytes(packet)
    connection.execute(
        "INSERT INTO proving_rights_packets VALUES(?,?,?,?,?)",
        (
            run_id,
            "RIGHTS_UK-01",
            digest_bytes(packet_bytes),
            packet_bytes.decode("utf-8"),
            rights_now,
        ),
    )
    connection.commit()
    connection.close()


def _cycle(proving: Path, unpublished: Path) -> None:
    run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        clock=lambda: _CLOCK,
    )


def _landed(unpublished: Path) -> tuple[tuple[str, str, str, str], ...]:
    connection = sqlite3.connect(unpublished)
    rows = tuple(
        (str(source_id), str(item_key), str(revision_digest), str(first_observed_at))
        for source_id, item_key, revision_digest, first_observed_at in connection.execute(
            """
            SELECT source_id, item_key, revision_digest, first_observed_at
            FROM unpublished_effective_revision_landed
            ORDER BY source_id, item_key, revision_digest
            """
        )
    )
    ledger = connection.execute(
        "SELECT COUNT(*) FROM ledger WHERE kind=?",
        (EFFECTIVE_REVISION_LANDED,),
    ).fetchone()[0]
    connection.close()
    assert ledger == len(rows)
    return rows


def test_two_new_feed_entries_emit_exactly_two_landed_records(tmp_path: Path) -> None:
    proving = tmp_path / "proving.sqlite3"
    unpublished = tmp_path / "unpublished.sqlite3"
    _add_proving_run(
        proving,
        run_id="run-1",
        body=_atom_feed(2),
        fetched_at="2026-08-20T00:00:00.000000Z",
    )
    _cycle(proving, unpublished)
    assert len(_landed(unpublished)) == 2


def test_unusable_observation_does_not_emit_a_landed_or_coverage_obligation(
    tmp_path: Path,
) -> None:
    proving = tmp_path / "proving.sqlite3"
    unpublished = tmp_path / "unpublished.sqlite3"
    body = b"<root><item><guid>x</guid><title>Wrong root</title></item></root>"
    _add_proving_run(
        proving,
        run_id="run-1",
        body=body,
        fetched_at="2026-08-20T00:00:00.000000Z",
    )

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=0,
        clock=lambda: _CLOCK,
    )

    assert _landed(unpublished) == ()
    assert report.poll_observation_count == 0
    assert report.feed_snapshot_item_count == 0
    assert report.effective_pull_count == 0


def test_repoll_unchanged_200_item_feed_emits_zero_new_landed_records(
    tmp_path: Path,
) -> None:
    proving = tmp_path / "proving.sqlite3"
    unpublished = tmp_path / "unpublished.sqlite3"
    body = _atom_feed(200)
    _add_proving_run(
        proving,
        run_id="run-1",
        body=body,
        fetched_at="2026-08-20T00:00:00.000000Z",
    )
    _cycle(proving, unpublished)
    assert len(_landed(unpublished)) == 200
    _add_proving_run(
        proving,
        run_id="run-2",
        body=body,
        fetched_at="2026-08-20T01:00:00.000000Z",
    )
    _cycle(proving, unpublished)
    assert len(_landed(unpublished)) == 200


def test_rights_renewal_restart_and_replay_emit_zero_duplicate_landed_records(
    tmp_path: Path,
) -> None:
    proving = tmp_path / "proving.sqlite3"
    unpublished = tmp_path / "unpublished.sqlite3"
    body = b"<feed><entry><title>a</title></entry></feed>"
    _add_proving_run(
        proving,
        run_id="run-1",
        body=body,
        fetched_at="2026-08-20T00:00:00.000000Z",
        rights_now="2026-08-20T00:00:00.000000Z",
    )
    _cycle(proving, unpublished)
    assert len(_landed(unpublished)) == 1
    _add_proving_run(
        proving,
        run_id="run-2",
        body=body,
        fetched_at="2026-08-21T00:00:00.000000Z",
        rights_now="2026-08-21T00:00:00.000000Z",
    )
    restarted = sqlite3.connect(unpublished)
    restarted.close()
    _cycle(proving, unpublished)
    assert len(_landed(unpublished)) == 1
    _cycle(proving, unpublished)
    assert len(_landed(unpublished)) == 1


def test_crash_between_revision_commit_and_emission_replays_to_one_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proving = tmp_path / "proving.sqlite3"
    unpublished = tmp_path / "unpublished.sqlite3"
    body = b"<feed><entry><title>a</title></entry></feed>"
    _add_proving_run(
        proving,
        run_id="run-1",
        body=body,
        fetched_at="2026-08-20T00:00:00.000000Z",
    )
    proving_state = sqlite3.connect(proving)
    first_seen = proving_state.execute(
        "SELECT COUNT(*) FROM proving_revision_first_seen"
    ).fetchone()[0]
    proving_state.close()
    assert first_seen == 1

    def crash_after_revision_commit(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("crash between revision commit and landed emission")

    monkeypatch.setattr(
        "newsroom.control_plane.cycle._emit_effective_revision_landed",
        crash_after_revision_commit,
    )
    with pytest.raises(RuntimeError, match="crash between revision commit"):
        _cycle(proving, unpublished)
    assert _landed(unpublished) == ()

    monkeypatch.undo()
    _cycle(proving, unpublished)
    assert len(_landed(unpublished)) == 1
    _cycle(proving, unpublished)
    assert len(_landed(unpublished)) == 1


def test_crash_replay_emits_landed_record_after_raw_body_retention(
    tmp_path: Path,
) -> None:
    proving = tmp_path / "proving.sqlite3"
    unpublished = tmp_path / "unpublished.sqlite3"
    _add_proving_run(
        proving,
        run_id="run-1",
        body=b"<feed><entry><title>a</title></entry></feed>",
        fetched_at="2026-08-01T00:00:00.000000Z",
    )

    _cycle(proving, unpublished)

    assert len(_landed(unpublished)) == 1


def test_legacy_revision_without_pull_ledger_emits_landed_record(
    tmp_path: Path,
) -> None:
    proving = tmp_path / "proving.sqlite3"
    unpublished = tmp_path / "unpublished.sqlite3"
    _add_proving_run(
        proving,
        run_id="run-1",
        body=b"<feed><entry><title>a</title></entry></feed>",
        fetched_at="2026-08-01T00:00:00.000000Z",
    )
    connection = sqlite3.connect(proving)
    connection.execute("DELETE FROM proving_effective_pull_first_seen")
    connection.execute("UPDATE proving_observations SET status_code=500")
    connection.commit()
    connection.close()

    _cycle(proving, unpublished)

    assert len(_landed(unpublished)) == 1


def test_landed_record_key_is_effective_revision_identity_only(tmp_path: Path) -> None:
    first_observed = "2026-08-20T00:00:00.000000Z"
    later_fetch = "2026-08-20T01:00:00.000000Z"
    identity = EffectiveRevisionIdentity(
        source_id="UK-01",
        item_key="item",
        revision_digest="sha256:" + ("ab" * 32),
        first_observed_at=first_observed,
    )
    later_observation = EffectiveRevisionIdentity(
        source_id=identity.source_id,
        item_key=identity.item_key,
        revision_digest=identity.revision_digest,
        first_observed_at=first_observed,
    )
    unpublished = tmp_path / "unpublished.sqlite3"
    connection = connect(str(unpublished))
    assert emit_effective_revision_landed(connection, identity) is True
    assert emit_effective_revision_landed(connection, later_observation) is False
    payload_digest, = connection.execute(
        "SELECT payload_digest FROM unpublished_effective_revision_landed"
    ).fetchone()
    ledger_payload, = connection.execute(
        "SELECT payload_digest FROM ledger WHERE kind=?",
        (EFFECTIVE_REVISION_LANDED,),
    ).fetchone()
    connection.commit()
    connection.close()
    expected_payload = effective_revision_landed_payload(identity)
    assert payload_digest == digest_canonical(expected_payload)
    assert ledger_payload == payload_digest
    assert "fetched_at" not in expected_payload
    assert "observed_at" not in expected_payload
    assert "run_id" not in expected_payload
    proving = tmp_path / "proving.sqlite3"
    unpublished_cycle = tmp_path / "unpublished-cycle.sqlite3"
    body = b"<feed><entry><title>a</title></entry></feed>"
    _add_proving_run(
        proving,
        run_id="run-1",
        body=body,
        fetched_at=first_observed,
    )
    _cycle(proving, unpublished_cycle)
    _add_proving_run(
        proving,
        run_id="run-2",
        body=body,
        fetched_at=later_fetch,
    )
    _cycle(proving, unpublished_cycle)
    rows = _landed(unpublished_cycle)
    assert len(rows) == 1
    assert rows[0][3] == first_observed


def test_landed_schema_crash_recovers_v10_rows(tmp_path: Path) -> None:
    unpublished = tmp_path / "stranded.sqlite3"
    raw = sqlite3.connect(unpublished)
    raw.execute(
        """
        CREATE TABLE unpublished_effective_revision_landed (
            source_id TEXT NOT NULL,
            item_key TEXT NOT NULL,
            revision_digest TEXT NOT NULL,
            first_observed_at TEXT NOT NULL,
            payload_digest TEXT NOT NULL,
            ledger_digest TEXT NOT NULL,
            at TEXT NOT NULL,
            PRIMARY KEY(source_id, item_key, revision_digest)
        ) WITHOUT ROWID
        """
    )
    raw.execute(
        """
        INSERT INTO unpublished_effective_revision_landed
        VALUES(?,?,?,?,?,?,?)
        """,
        (
            "UK-01",
            "item",
            "sha256:" + ("ab" * 32),
            "2026-08-20T00:00:00.000000Z",
            "sha256:" + ("cd" * 32),
            "sha256:" + ("ef" * 32),
            "2026-08-20T00:00:00.000000Z",
        ),
    )
    raw.execute(
        "ALTER TABLE unpublished_effective_revision_landed "
        "RENAME TO unpublished_effective_revision_landed_v10"
    )
    raw.commit()
    raw.close()
    connection = connect(str(unpublished))
    new_rows = connection.execute(
        "SELECT COUNT(*) FROM unpublished_effective_revision_landed"
    ).fetchone()[0]
    stranded = connection.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type='table' AND name='unpublished_effective_revision_landed_v10'
        """
    ).fetchone()
    recovered = connection.execute(
        """
        SELECT source_id, item_key, revision_digest, first_observed_at
        FROM unpublished_effective_revision_landed
        """
    ).fetchone()
    connection.close()
    assert new_rows == 1
    assert stranded is None
    assert recovered == (
        "UK-01",
        "item",
        "sha256:" + ("ab" * 32),
        "2026-08-20T00:00:00.000000Z",
    )


def test_v10_recovery_preserves_an_earlier_undated_pull(
    tmp_path: Path,
) -> None:
    unpublished = tmp_path / "v10.sqlite3"
    raw = sqlite3.connect(unpublished)
    raw.execute(
        """
        CREATE TABLE unpublished_effective_revision_landed (
            source_id TEXT NOT NULL,
            item_key TEXT NOT NULL,
            revision_digest TEXT NOT NULL,
            first_observed_at TEXT NOT NULL,
            payload_digest TEXT NOT NULL,
            ledger_digest TEXT NOT NULL,
            at TEXT NOT NULL,
            PRIMARY KEY(source_id, item_key, revision_digest)
        ) WITHOUT ROWID
        """
    )
    digest = "sha256:" + ("ab" * 32)
    raw.execute(
        "INSERT INTO unpublished_effective_revision_landed VALUES(?,?,?,?,?,?,?)",
        (
            "UK-01", "item", digest, "2026-08-20T00:00:00.000000Z",
            "sha256:" + ("cd" * 32), "sha256:" + ("ef" * 32),
            "2026-08-20T00:00:00.000000Z",
        ),
    )
    raw.commit()
    raw.close()

    connection = connect(str(unpublished))
    identity = EffectiveRevisionIdentity(
        source_id="UK-01",
        item_key="item",
        revision_digest=digest,
        first_observed_at="2026-08-20T01:00:00.000000Z",
    )
    assert emit_effective_revision_landed(
        connection,
        identity,
        updated_at="2026-08-20T00:30:00.000000Z",
        landed_at="2026-08-20T01:00:00.000000Z",
    )

    revisions = list_landed_revisions(connection)
    connection.close()

    assert len(revisions) == 2
    assert {revision.updated_at for revision in revisions} == {
        None,
        "2026-08-20T00:30:00.000000Z",
    }


def test_emit_landed_uses_pull_landing_time_for_version_markers(
    tmp_path: Path,
) -> None:
    identity = EffectiveRevisionIdentity(
        source_id="UK-01",
        item_key="item",
        revision_digest="sha256:" + ("ab" * 32),
        first_observed_at="2026-08-20T00:01:00.000000Z",
    )
    unpublished = tmp_path / "unpublished.sqlite3"
    connection = connect(str(unpublished))
    assert emit_effective_revision_landed(
        connection,
        identity,
        updated_at="2026-08-20T00:00:00.000000Z",
        landed_at="2026-08-20T00:01:00.000000Z",
    )
    assert emit_effective_revision_landed(
        connection,
        identity,
        updated_at="2026-08-20T02:00:00.000000Z",
        landed_at="2026-08-20T02:01:00.000000Z",
    )
    rows = list(
        connection.execute(
            """
            SELECT updated_at, first_observed_at
            FROM unpublished_effective_revision_landed
            ORDER BY updated_at
            """
        )
    )
    connection.close()
    assert rows == [
        ("2026-08-20T00:00:00.000000Z", "2026-08-20T00:01:00.000000Z"),
        ("2026-08-20T02:00:00.000000Z", "2026-08-20T02:01:00.000000Z"),
    ]


def test_landed_projection_applies_a_receipted_first_seen_correction(
    tmp_path: Path,
) -> None:
    old_at = "2026-08-20T11:00:00.000000Z"
    corrected_at = "2026-08-20T00:00:00.000000Z"
    identity = EffectiveRevisionIdentity(
        source_id="UK-01",
        item_key="item",
        revision_digest="sha256:" + ("ab" * 32),
        first_observed_at=old_at,
    )
    connection = connect(str(tmp_path / "corrected.sqlite3"))
    assert emit_effective_revision_landed(connection, identity)
    connection.execute(
        """
        INSERT INTO unpublished_effective_revision_remap(
            mapping_id, source_id, item_key, revision_digest, published_at,
            updated_at, old_observed_fallback_at, new_first_observed_at, kind,
            retention_window_bounded_inaccuracy, old_ingest_id, new_ingest_id, at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "sha256:" + ("12" * 32),
            identity.source_id,
            identity.item_key,
            identity.revision_digest,
            "",
            "",
            old_at,
            corrected_at,
            "FIRST_SEEN_CORRECTION",
            0,
            None,
            None,
            corrected_at,
        ),
    )
    connection.commit()

    revisions = list_landed_revisions(connection)
    connection.close()

    assert len(revisions) == 1
    assert revisions[0].observed_at == corrected_at
    assert revisions[0].source_time == corrected_at
