from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from newsroom.authority.canonical import digest_bytes, digest_canonical
from newsroom.control_plane.backlog_reconciliation import (
    ALLOWED_COMMAND_TYPES,
    COORDINATOR_NAME,
    CanonicalStoreGuardError,
    RAW_HTTP_RETENTION,
    ReconciliationCommand,
    ReconciliationCommandError,
    _backup_store,
    _readonly_connect,
    _write_coordinator,
    refuse_canonical_write,
    reconcile_effective_revision_backlog,
)
from newsroom.control_plane.command_auth import (
    COMMAND_SERVICE_PRINCIPAL,
    RECONCILE_COMMAND_TYPE,
)
from newsroom.control_plane.command_service import issue_reconciliation_command
from newsroom.control_plane.items import parse_observation
from newsroom.control_plane.paths import CANONICAL_PROVING_STORE
from newsroom.control_plane.store import connect
from newsroom.effective_revision import create_effective_revision_schema
from scripts.reconcile_effective_revision_backlog import main

_EVALUATED_AT = datetime(2026, 8, 21, 12, tzinfo=UTC)
_FIRST_POLL = "2026-08-20T00:00:00.000000Z"
_POLL_COUNT = 12
_HK_ITEMS = 6
_UK_ITEMS = 3


def _poll_at(ordinal: int) -> str:
    return f"2026-08-20T{ordinal:02d}:00:00.000000Z"


def _feed(source_id: str, count: int, *, dated: bool = False) -> bytes:
    items: list[str] = []
    for index in range(count):
        published = (
            "<pubDate>Thu, 01 Jan 2026 09:00:00 +0000</pubDate>" if dated else ""
        )
        items.append(
            f"<item><guid>{source_id}-{index}</guid>"
            f"<title>{source_id} item {index}</title>"
            f"<link>https://example.test/{source_id}/{index}</link>"
            f"{published}<description>unchanged body {source_id} {index}</description>"
            "</item>"
        )
    return f"<rss><channel>{''.join(items)}</channel></rss>".encode()


def _independent_digest(item: object) -> str:
    return digest_canonical(
        {
            "headline": item.headline,
            "body": item.retained_corpus_body,
            "canonical_url": item.canonical_url,
        }
    )


def _triples(source_id: str, body: bytes, url: str) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (source_id, item.item_key, _independent_digest(item))
        for item in parse_observation(source_id=source_id, url=url, body=body)
    )


def _file_digest(path: Path) -> str:
    payload = path.read_bytes()
    wal = Path(str(path) + "-wal")
    if wal.is_file():
        payload += wal.read_bytes()
    return hashlib.sha256(payload).hexdigest()


def _open_proving(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE proving_runs(
            run_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            publication INTEGER NOT NULL DEFAULT 0,
            public_dispatch INTEGER NOT NULL DEFAULT 0,
            openrouter_invoked INTEGER NOT NULL DEFAULT 0,
            spend_gbp_minor INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE proving_observations(
            source_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            url TEXT NOT NULL,
            status_code INTEGER NOT NULL,
            body_digest TEXT NOT NULL,
            body BLOB NOT NULL,
            item_count INTEGER NOT NULL,
            error TEXT
        );
        """
    )
    create_effective_revision_schema(connection)
    return connection


def _insert_observation(
    connection: sqlite3.Connection,
    *,
    source_id: str,
    run_id: str,
    fetched_at: str,
    url: str,
    body: bytes,
    status_code: int = 200,
    error: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO proving_runs(
            run_id, started_at, publication, public_dispatch,
            openrouter_invoked, spend_gbp_minor
        ) VALUES(?,?,0,0,0,0)
        ON CONFLICT(run_id) DO NOTHING
        """,
        (run_id, fetched_at),
    )
    connection.execute(
        "INSERT INTO proving_observations VALUES(?,?,?,?,?,?,?,?,?)",
        (
            source_id,
            run_id,
            fetched_at,
            url,
            status_code,
            digest_bytes(body),
            body,
            1,
            error,
        ),
    )


def _amplified_stores(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    proving = tmp_path / "proving_store.sqlite3"
    unpublished = tmp_path / "unpublished_store.sqlite3"
    connection = _open_proving(proving)
    sources = (
        ("HK-04", "https://example.test/hk-04.xml", _feed("HK-04", _HK_ITEMS)),
        ("UK-10", "https://example.test/uk-10.xml", _feed("UK-10", _UK_ITEMS)),
        (
            "UK-01",
            "https://example.test/uk-01.xml",
            _feed("UK-01", 1, dated=True),
        ),
    )
    for ordinal in range(_POLL_COUNT):
        fetched_at = _poll_at(ordinal)
        run_id = f"run-{ordinal + 1}"
        for source_id, url, body in sources:
            _insert_observation(
                connection,
                source_id=source_id,
                run_id=run_id,
                fetched_at=fetched_at,
                url=url,
                body=body,
            )
    last_at = _poll_at(_POLL_COUNT - 1)
    expected: set[tuple[str, str, str]] = set()
    late: list[tuple[str, str, str]] = []
    for source_id, url, body in sources:
        for triple in _triples(source_id, body, url):
            expected.add(triple)
            late.append(triple)
    already_correct = set(late[:2])
    for source_id, item_key, digest in late:
        first_seen_at = (
            _FIRST_POLL if (source_id, item_key, digest) in already_correct else last_at
        )
        connection.execute(
            """
            INSERT INTO proving_revision_first_seen(
                source_id, item_key, revision_digest, first_seen_at
            ) VALUES(?,?,?,?)
            """,
            (source_id, item_key, digest, first_seen_at),
        )
    connection.commit()
    connection.close()

    store = connect(str(unpublished))
    store.execute(
        "INSERT INTO ledger(at, kind, payload_digest, prev_digest, digest) "
        "VALUES(?,?,?,?,?)",
        (
            _FIRST_POLL,
            "PRIVATE_CYCLE_START",
            "sha256:" + ("aa" * 32),
            "sha256:" + ("00" * 32),
            "sha256:" + ("bb" * 32),
        ),
    )
    store.execute(
        """
        INSERT INTO unpublished_graphiti_attempt_receipts(
            ingest_id, attempt_number, outcome, receipt_digest, receipt_json, at
        ) VALUES(?,?,?,?,?,?)
        """,
        (
            "ingest-old-1",
            1,
            "COMPLETE",
            "sha256:" + ("cc" * 32),
            json.dumps({"ingest_id": "ingest-old-1", "observed_at": _FIRST_POLL}),
            _FIRST_POLL,
        ),
    )
    for ingest_id in ("ingest-old-1", "ingest-old-2"):
        store.execute(
            """
            INSERT INTO unpublished_graphiti_ingest(
                ingest_id, source_id, item_key, outcome, proposal_count,
                entity_count, relation_count, failure_code, temporal_basis,
                reference_time, generation_id, receipt_digest, at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                ingest_id,
                "HK-04",
                "HK-04-0",
                "COMPLETE",
                0,
                0,
                0,
                "",
                "OBSERVED_FALLBACK",
                _FIRST_POLL,
                "generation",
                "sha256:" + ("dd" * 32),
                _FIRST_POLL,
            ),
        )
    store.execute(
        """
        INSERT INTO unpublished_graphiti_ingest(
            ingest_id, source_id, item_key, outcome, proposal_count,
            entity_count, relation_count, failure_code, temporal_basis,
            reference_time, generation_id, receipt_digest, at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "ingest-uk10-unique",
            "UK-10",
            "UK-10-0",
            "COMPLETE",
            0,
            0,
            0,
            "",
            "OBSERVED_FALLBACK",
            _FIRST_POLL,
            "generation",
            "sha256:" + ("dd" * 32),
            _FIRST_POLL,
        ),
    )
    store.commit()
    store.close()
    old_n = _HK_ITEMS * _POLL_COUNT + _UK_ITEMS * _POLL_COUNT + 1
    meta = {
        "expected": frozenset(expected),
        "old_n": old_n,
        "new_n": len(expected),
        "late_count": len(late) - len(already_correct),
        "already_correct": len(already_correct),
    }
    return proving, unpublished, meta


def _command(mapping_digest: str, *, key: str | None = None) -> ReconciliationCommand:
    return issue_reconciliation_command(
        idempotency_key=key or f"test-{uuid.uuid4()}",
        expected_mapping_digest=mapping_digest,
    )


def _run(
    proving: Path,
    unpublished: Path,
    tmp_path: Path,
    *,
    mode: str,
    dry_run_receipt: dict[str, object] | None = None,
    command: ReconciliationCommand | None = None,
) -> object:
    live_command = None
    if mode == "live":
        digest = (
            ""
            if dry_run_receipt is None
            else str(dry_run_receipt["mapping_digest"])
        )
        live_command = command or _command(digest)
    return reconcile_effective_revision_backlog(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        mode=mode,  # type: ignore[arg-type]
        dry_run_receipt=dry_run_receipt,
        receipt_path=tmp_path / f"{mode}-receipt.json",
        backup_dir=tmp_path / "backups" if mode == "live" else None,
        evaluated_at=_EVALUATED_AT,
        command=live_command,
    )


def test_independent_recount_does_not_use_identity_code_path() -> None:
    source = Path("newsroom/control_plane/backlog_reconciliation.py").read_text(
        encoding="utf-8"
    )
    assert "from newsroom.effective_revision" not in source
    assert "from newsroom.graphiti_adapter.identity" not in source
    assert "unique_chunk_units" not in source
    assert "revisions_from" not in source
    assert "EffectiveRevisionIdentity" not in source
    assert "content_digest" not in source


def test_retention_constant_matches_cycle() -> None:
    from newsroom.control_plane.cycle import _RAW_HTTP_RETENTION

    assert RAW_HTTP_RETENTION == _RAW_HTTP_RETENTION


def test_reconcile_retained_fixture_matches_independent_dedupe(tmp_path: Path) -> None:
    proving, unpublished, meta = _amplified_stores(tmp_path)
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    assert dry.new_effective_revision_count == meta["new_n"]
    assert dry.old_identity_count == meta["old_n"]
    assert dry.new_effective_revision_count == 10
    assert dry.old_identity_count == 109
    assert dry.old_identity_count != dry.new_effective_revision_count
    by_source = {row["source_id"]: row for row in dry.per_source}
    assert by_source["HK-04"]["amplification_before"] == "12.00x"
    assert by_source["UK-10"]["amplification_before"] == "12.00x"
    assert by_source["UK-01"]["amplification_before"] == "1.00x"
    assert all(row["amplification_after"] == "1.00x" for row in dry.per_source)
    assert len(dry.first_seen_corrections) == meta["late_count"]
    live = _run(
        proving,
        unpublished,
        tmp_path,
        mode="live",
        dry_run_receipt=dry.as_dict(),
    )
    assert live.new_effective_revision_count == dry.new_effective_revision_count
    connection = sqlite3.connect(proving)
    rows = {
        (str(source_id), str(item_key), str(digest)): str(seen)
        for source_id, item_key, digest, seen in connection.execute(
            """
            SELECT source_id, item_key, revision_digest, first_seen_at
            FROM proving_revision_first_seen
            """
        )
    }
    connection.close()
    assert set(rows) == meta["expected"]
    assert all(seen == _FIRST_POLL for seen in rows.values())
    for correction in live.first_seen_corrections:
        assert correction["old_first_seen_at"] != correction["new_first_seen_at"]
        assert correction["identity_remap"]["old"]["first_observed_at"] == (
            correction["old_first_seen_at"]
        )
        assert correction["identity_remap"]["new"]["first_observed_at"] == _FIRST_POLL


def test_dry_run_mutates_nothing_and_matches_live(tmp_path: Path) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    before_proving = _file_digest(proving)
    before_unpublished = _file_digest(unpublished)
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    assert dry.mutated is False
    assert dry.remapped_count == 0
    assert _file_digest(proving) == before_proving
    assert _file_digest(unpublished) == before_unpublished
    live = _run(
        proving,
        unpublished,
        tmp_path,
        mode="live",
        dry_run_receipt=dry.as_dict(),
    )
    assert live.mutated is True
    assert live.mapping_digest == dry.mapping_digest
    assert live.old_identity_count == dry.old_identity_count
    assert live.new_effective_revision_count == dry.new_effective_revision_count
    assert live.remapped_count > 0


def test_append_only_records_remain_resolvable(tmp_path: Path) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    proving_conn = sqlite3.connect(proving)
    unpublished_conn = sqlite3.connect(unpublished)
    observations = {
        tuple(row)
        for row in proving_conn.execute(
            "SELECT run_id, source_id, fetched_at, body_digest FROM proving_observations"
        )
    }
    ledger = {row[0] for row in unpublished_conn.execute("SELECT digest FROM ledger")}
    receipts = {
        tuple(row)
        for row in unpublished_conn.execute(
            "SELECT ingest_id, attempt_number FROM unpublished_graphiti_attempt_receipts"
        )
    }
    ingests = {
        row[0]
        for row in unpublished_conn.execute(
            "SELECT ingest_id FROM unpublished_graphiti_ingest"
        )
    }
    proving_conn.close()
    unpublished_conn.close()
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    live = _run(
        proving,
        unpublished,
        tmp_path,
        mode="live",
        dry_run_receipt=dry.as_dict(),
    )
    assert live.no_loss_proof["lost"] is False
    proving_conn = sqlite3.connect(proving)
    unpublished_conn = sqlite3.connect(unpublished)
    assert observations <= {
        tuple(row)
        for row in proving_conn.execute(
            "SELECT run_id, source_id, fetched_at, body_digest FROM proving_observations"
        )
    }
    assert ledger <= {
        row[0] for row in unpublished_conn.execute("SELECT digest FROM ledger")
    }
    assert receipts <= {
        tuple(row)
        for row in unpublished_conn.execute(
            "SELECT ingest_id, attempt_number FROM unpublished_graphiti_attempt_receipts"
        )
    }
    assert ingests <= {
        row[0]
        for row in unpublished_conn.execute(
            "SELECT ingest_id FROM unpublished_graphiti_ingest"
        )
    }
    proving_conn.close()
    unpublished_conn.close()


def test_rerun_is_idempotent(tmp_path: Path) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    first = _run(
        proving,
        unpublished,
        tmp_path,
        mode="live",
        dry_run_receipt=dry.as_dict(),
    )
    second_dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    assert second_dry.mapping_digest == first.mapping_digest
    assert second_dry.first_seen_corrections == ()
    second = _run(
        proving,
        unpublished,
        tmp_path / "second",
        mode="live",
        dry_run_receipt=second_dry.as_dict(),
    )
    assert second.mapping_digest == first.mapping_digest
    assert second.remapped_count == 0


def test_unresolved_collisions_are_enumerated_not_merged(tmp_path: Path) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    assert dry.unresolved_collisions
    assert all(item["merged"] is False for item in dry.unresolved_collisions)
    kinds = {item["kind"] for item in dry.unresolved_collisions}
    assert "GRAPH_EFFECT_MULTIPLE_TERMINAL" in kinds
    ingest_ids = set(dry.unresolved_collisions[0]["ingest_ids"])
    assert ingest_ids == {"ingest-old-1", "ingest-old-2"}
    live = _run(
        proving,
        unpublished,
        tmp_path,
        mode="live",
        dry_run_receipt=dry.as_dict(),
    )
    connection = sqlite3.connect(unpublished)
    remaining = {
        row[0]
        for row in connection.execute("SELECT ingest_id FROM unpublished_graphiti_ingest")
    }
    connection.close()
    assert remaining == ingest_ids
    assert live.unresolved_collisions == dry.unresolved_collisions


def test_g2_drift_refuses_live_mutation(tmp_path: Path) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    before = _file_digest(proving)
    drifted = dict(dry.as_dict())
    drifted["mapping_digest"] = "sha256:" + ("ee" * 32)
    with pytest.raises(Exception, match="G2"):
        _run(
            proving,
            unpublished,
            tmp_path,
            mode="live",
            dry_run_receipt=drifted,
        )
    assert _file_digest(proving) == before


def test_g1_refuses_unattributed_digest_mismatch(tmp_path: Path) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    connection = sqlite3.connect(proving)
    connection.execute(
        """
        INSERT INTO proving_revision_first_seen(
            source_id, item_key, revision_digest, first_seen_at
        ) VALUES(?,?,?,?)
        """,
        ("HK-04", "HK-04-0", "sha256:" + ("ff" * 32), _FIRST_POLL),
    )
    connection.commit()
    connection.close()
    with pytest.raises(Exception, match="G1"):
        _run(proving, unpublished, tmp_path, mode="dry-run")


def test_retention_window_bounded_inaccuracy_is_typed(tmp_path: Path) -> None:
    proving = tmp_path / "proving_store.sqlite3"
    unpublished = tmp_path / "unpublished_store.sqlite3"
    connection = _open_proving(proving)
    body = _feed("HK-04", 1)
    url = "https://example.test/hk-04.xml"
    _insert_observation(
        connection,
        source_id="HK-04",
        run_id="run-old",
        fetched_at="2026-08-10T00:00:00.000000Z",
        url=url,
        body=b"<rss><channel></channel></rss>",
        status_code=500,
        error="pruned",
    )
    _insert_observation(
        connection,
        source_id="HK-04",
        run_id="run-new",
        fetched_at=_FIRST_POLL,
        url=url,
        body=body,
    )
    triple = _triples("HK-04", body, url)[0]
    connection.execute(
        """
        INSERT INTO proving_revision_first_seen(
            source_id, item_key, revision_digest, first_seen_at
        ) VALUES(?,?,?,?)
        """,
        (*triple, "2026-08-20T11:00:00.000000Z"),
    )
    connection.commit()
    connection.close()
    connect(str(unpublished)).close()
    dry = reconcile_effective_revision_backlog(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        mode="dry-run",
        receipt_path=tmp_path / "receipt.json",
        evaluated_at=_EVALUATED_AT,
    )
    assert dry.retention_window_bounded_inaccuracies
    bounded = dry.retention_window_bounded_inaccuracies[0]
    assert bounded["not_true_first_landing"] is True
    assert bounded["rule"] == "RETENTION_WINDOW_BOUNDED_INACCURACY"
    assert dry.first_seen_corrections[0]["retention_window_bounded_inaccuracy"] is True
    assert dry.first_seen_corrections[0]["new_first_seen_at"] == _FIRST_POLL


def test_source_version_rule_is_attributed(tmp_path: Path) -> None:
    proving = tmp_path / "proving_store.sqlite3"
    unpublished = tmp_path / "unpublished_store.sqlite3"
    connection = _open_proving(proving)
    first = (
        "<rss><channel><item><guid>same</guid><title>Same</title>"
        "<pubDate>Thu, 01 Jan 2026 09:00:00 +0000</pubDate>"
        "<description>body</description></item></channel></rss>"
    ).encode()
    second = (
        "<rss><channel><item><guid>same</guid><title>Same</title>"
        "<pubDate>Fri, 02 Jan 2026 09:00:00 +0000</pubDate>"
        "<description>body</description></item></channel></rss>"
    ).encode()
    url = "https://example.test/dated.xml"
    _insert_observation(
        connection,
        source_id="UK-01",
        run_id="run-1",
        fetched_at=_FIRST_POLL,
        url=url,
        body=first,
    )
    _insert_observation(
        connection,
        source_id="UK-01",
        run_id="run-2",
        fetched_at=_poll_at(1),
        url=url,
        body=second,
    )
    connection.commit()
    connection.close()
    connect(str(unpublished)).close()
    dry = reconcile_effective_revision_backlog(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        mode="dry-run",
        receipt_path=tmp_path / "receipt.json",
        evaluated_at=_EVALUATED_AT,
    )
    assert dry.new_effective_revision_count == 2
    rules = [
        row
        for row in dry.attributed_source_version_rules
        if row["rule"] == "SOURCE_SUPPLIED_VERSION_MARKER"
    ]
    assert len(rules) == 1
    assert rules[0]["marker_count"] == 2


def test_canonical_store_refuses_writable_open() -> None:
    with pytest.raises(CanonicalStoreGuardError, match="canonical store"):
        refuse_canonical_write(
            str(CANONICAL_PROVING_STORE), allow_canonical_mutation=False
        )


def test_cli_dry_run_and_live(tmp_path: Path) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    dry_receipt = tmp_path / "dry.json"
    live_receipt = tmp_path / "live.json"
    assert (
        main(
            [
                "dry-run",
                "--proving",
                str(proving),
                "--unpublished",
                str(unpublished),
                "--receipt",
                str(dry_receipt),
                "--evaluated-at",
                "2026-08-21T12:00:00.000000Z",
            ]
        )
        == 0
    )
    assert dry_receipt.is_file()
    digest = json.loads(dry_receipt.read_text(encoding="utf-8"))["mapping_digest"]
    assert (
        main(
            [
                "live",
                "--proving",
                str(proving),
                "--unpublished",
                str(unpublished),
                "--receipt",
                str(live_receipt),
                "--dry-run-receipt",
                str(dry_receipt),
                "--backup-dir",
                str(tmp_path / "backups"),
                "--evaluated-at",
                "2026-08-21T12:00:00.000000Z",
                "--idempotency-key",
                "cli-live-1",
                "--expected-mapping-digest",
                digest,
            ]
        )
        == 0
    )
    written = json.loads(live_receipt.read_text(encoding="utf-8"))
    assert written["gates"]["G1"] == "pass"
    assert written["gates"]["G2"] == "pass"
    assert written["gates"]["G3"] == "pass"
    assert written["gates"]["G5"] == "pass"
    assert written["no_loss_proof"]["lost"] is False
    assert written["command"]["idempotency_key"] == "cli-live-1"
    assert written["command"]["caller_principal"] == COMMAND_SERVICE_PRINCIPAL
    assert written["command"]["command_type"] == RECONCILE_COMMAND_TYPE


def test_live_requires_authenticated_command(tmp_path: Path) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    with pytest.raises(ReconciliationCommandError, match="authenticated command-service"):
        _run(
            proving,
            unpublished,
            tmp_path,
            mode="live",
            dry_run_receipt=dry.as_dict(),
            command=ReconciliationCommand(
                caller_principal="agent.worker",
                command_type=next(iter(ALLOWED_COMMAND_TYPES)),
                idempotency_key="bad-principal",
                expected_mapping_digest=dry.mapping_digest,
            ),
        )
    with pytest.raises(ReconciliationCommandError, match="authenticated command-service"):
        _run(
            proving,
            unpublished,
            tmp_path,
            mode="live",
            dry_run_receipt=dry.as_dict(),
            command=ReconciliationCommand(
                caller_principal=COMMAND_SERVICE_PRINCIPAL,
                command_type=RECONCILE_COMMAND_TYPE,
                idempotency_key="self-claim",
                expected_mapping_digest=dry.mapping_digest,
            ),
        )
    with pytest.raises(ReconciliationCommandError, match="mapping digest"):
        _run(
            proving,
            unpublished,
            tmp_path,
            mode="live",
            dry_run_receipt=dry.as_dict(),
            command=_command("sha256:" + ("00" * 32)),
        )


def test_live_command_is_idempotent_for_the_same_key(tmp_path: Path) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    command = _command(dry.mapping_digest, key="same-live")
    first = _run(
        proving,
        unpublished,
        tmp_path,
        mode="live",
        dry_run_receipt=dry.as_dict(),
        command=command,
    )
    second = _run(
        proving,
        unpublished,
        tmp_path / "again",
        mode="live",
        dry_run_receipt=dry.as_dict(),
        command=command,
    )
    assert first.mutated is True
    assert second.mapping_digest == first.mapping_digest
    assert second.remapped_count == first.remapped_count


def test_retained_effects_are_remapped_with_old_ingest_id(tmp_path: Path) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    _run(
        proving,
        unpublished,
        tmp_path,
        mode="live",
        dry_run_receipt=dry.as_dict(),
    )
    connection = sqlite3.connect(unpublished)
    remapped = {
        str(old_ingest_id)
        for (old_ingest_id,) in connection.execute(
            """
            SELECT old_ingest_id
            FROM unpublished_effective_revision_remap
            WHERE kind='RETAINED_EFFECT_REMAP'
              AND old_ingest_id IS NOT NULL
            """
        )
    }
    tables = {
        str(name)
        for (name,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    connection.close()
    assert remapped == {"ingest-uk10-unique"}
    proving_conn = sqlite3.connect(proving)
    proving_tables = {
        str(name)
        for (name,) in proving_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    proving_conn.close()
    assert "proving_revision_first_seen" in proving_tables
    assert "proving_backfill_watermark" in proving_tables
    assert "unpublished_effective_revision_remap" in tables


def test_sqlite_profile_enables_foreign_keys(tmp_path: Path) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    proving_conn = _readonly_connect(str(proving))
    unpublished_conn = _readonly_connect(str(unpublished))
    try:
        assert proving_conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert unpublished_conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        proving_conn.close()
        unpublished_conn.close()


def test_live_backup_is_mode_restricted_and_digest_verified(tmp_path: Path) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    _run(
        proving,
        unpublished,
        tmp_path,
        mode="live",
        dry_run_receipt=dry.as_dict(),
    )
    backup_dir = tmp_path / "backups"
    proving_backup = backup_dir / "proving_store.sqlite3"
    sidecar = Path(str(proving_backup) + ".sha256")
    assert oct(backup_dir.stat().st_mode & 0o777) == "0o700"
    assert oct(proving_backup.stat().st_mode & 0o777) == "0o600"
    assert oct(sidecar.stat().st_mode & 0o777) == "0o600"
    expected = "sha256:" + hashlib.sha256(proving_backup.read_bytes()).hexdigest()
    assert sidecar.read_text(encoding="utf-8").strip() == expected
    coordinator = json.loads(
        (backup_dir / COORDINATOR_NAME).read_text(encoding="utf-8")
    )
    assert coordinator["status"] == "COMPLETE"


def test_incomplete_coordinator_restores_split_brain_before_retry(
    tmp_path: Path,
) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    backup_dir = tmp_path / "backups"
    _backup_store(proving, backup_dir / "proving_store.sqlite3")
    _backup_store(unpublished, backup_dir / "unpublished_store.sqlite3")
    _write_coordinator(
        backup_dir / COORDINATOR_NAME,
        {"status": "STARTED", "mapping_digest": dry.mapping_digest},
    )
    split = sqlite3.connect(proving)
    split.execute(
        """
        INSERT INTO proving_runs(
            run_id, started_at, publication, public_dispatch,
            openrouter_invoked, spend_gbp_minor
        ) VALUES('canary-split', ?, 0, 0, 0, 0)
        """,
        (_FIRST_POLL,),
    )
    split.commit()
    split.close()
    live = _run(
        proving,
        unpublished,
        tmp_path,
        mode="live",
        dry_run_receipt=dry.as_dict(),
    )
    proving_conn = sqlite3.connect(proving)
    canary = proving_conn.execute(
        "SELECT 1 FROM proving_runs WHERE run_id='canary-split'"
    ).fetchone()
    first_seen = {
        str(seen)
        for (seen,) in proving_conn.execute(
            "SELECT first_seen_at FROM proving_revision_first_seen"
        )
    }
    proving_conn.close()
    unpublished_conn = sqlite3.connect(unpublished)
    remapped = unpublished_conn.execute(
        "SELECT COUNT(*) FROM unpublished_effective_revision_remap"
    ).fetchone()[0]
    unpublished_conn.close()
    assert canary is None
    assert first_seen == {_FIRST_POLL}
    assert remapped > 0
    assert live.no_loss_proof["lost"] is False
    assert live.mutated is True


def test_g2_refuses_effect_map_drift_after_dry_run(tmp_path: Path) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    connection = sqlite3.connect(unpublished)
    connection.execute(
        """
        INSERT INTO unpublished_graphiti_ingest(
            ingest_id, source_id, item_key, outcome, proposal_count,
            entity_count, relation_count, failure_code, temporal_basis,
            reference_time, generation_id, receipt_digest, at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "ingest-uk10-later",
            "UK-10",
            "UK-10-1",
            "COMPLETE",
            0,
            0,
            0,
            "",
            "OBSERVED_FALLBACK",
            _FIRST_POLL,
            "generation",
            "sha256:" + ("ee" * 32),
            _FIRST_POLL,
        ),
    )
    connection.commit()
    connection.close()
    with pytest.raises(Exception, match="G2"):
        _run(
            proving,
            unpublished,
            tmp_path,
            mode="live",
            dry_run_receipt=dry.as_dict(),
        )


def test_g3_backup_is_taken_before_unpublished_schema_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import newsroom.control_plane.backlog_reconciliation as backlog

    proving, unpublished, _meta = _amplified_stores(tmp_path)
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    order: list[str] = []
    real_backup = backlog._backup_store
    real_connect = backlog.connect_unpublished

    def tracked_backup(source: Path, destination: Path) -> dict[str, str]:
        order.append("backup")
        return real_backup(source, destination)

    def tracked_connect(path: str) -> sqlite3.Connection:
        order.append("connect_unpublished")
        return real_connect(path)

    monkeypatch.setattr(backlog, "_backup_store", tracked_backup)
    monkeypatch.setattr(backlog, "connect_unpublished", tracked_connect)
    _run(
        proving,
        unpublished,
        tmp_path,
        mode="live",
        dry_run_receipt=dry.as_dict(),
    )
    assert "backup" in order
    assert "connect_unpublished" in order
    assert order.index("backup") < order.index("connect_unpublished")


def test_colliding_effects_are_not_remapped_to_the_same_revision(
    tmp_path: Path,
) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    colliding = next(
        item
        for item in dry.unresolved_collisions
        if item["kind"] == "GRAPH_EFFECT_MULTIPLE_TERMINAL"
    )
    assert colliding["merged"] is False
    assert set(colliding["ingest_ids"]) == {"ingest-old-1", "ingest-old-2"}
    live = _run(
        proving,
        unpublished,
        tmp_path,
        mode="live",
        dry_run_receipt=dry.as_dict(),
    )
    connection = sqlite3.connect(unpublished)
    remapped = {
        str(old_ingest_id)
        for (old_ingest_id,) in connection.execute(
            """
            SELECT old_ingest_id
            FROM unpublished_effective_revision_remap
            WHERE kind='RETAINED_EFFECT_REMAP'
              AND old_ingest_id IN ('ingest-old-1', 'ingest-old-2')
            """
        )
    }
    connection.close()
    assert remapped == set()
    assert live.unresolved_collisions == dry.unresolved_collisions
