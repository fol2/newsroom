from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from newsroom.authority import AuthenticationError
from newsroom.authority.auth import (
    AuthenticationProof,
    StaticAuthenticator,
    StaticPrincipal,
)
from newsroom.authority.canonical import digest_bytes, digest_canonical
from newsroom.control_plane.backlog_reconciliation import (
    COORDINATOR_NAME,
    RAW_HTTP_RETENTION,
    BacklogReconciliationError,
    CanonicalStoreGuardError,
    ReconciliationCommandError,
    _backup_store,
    _census_unpublished,
    _readonly_connect,
    _restore_incomplete_dual_store,
    _store_identity,
    _write_coordinator,
    reconcile_effective_revision_backlog,
    refuse_canonical_write,
)
from newsroom.control_plane.command_auth import HERMES_COMMAND_PRINCIPAL
from newsroom.control_plane.command_service import ControlPlaneCommandService
from newsroom.control_plane.items import parse_observation
from newsroom.control_plane.paths import CANONICAL_PROVING_STORE
from newsroom.control_plane.sqlite_profile import apply_control_plane_sqlite_profile
from newsroom.control_plane.store import connect, ensure_reconciliation_schema
from newsroom.effective_revision import create_effective_revision_schema
from scripts.reconcile_effective_revision_backlog import main

_EVALUATED_AT = datetime(2026, 8, 21, 12, tzinfo=UTC)
_FIRST_POLL = "2026-08-20T00:00:00.000000Z"
_POLL_COUNT = 12
_HK_ITEMS = 6
_UK_ITEMS = 3
_COMMAND_TOKEN = "test-command-service-token"
_COMMAND_PROOF = AuthenticationProof(method="STATIC_TOKEN", credential=_COMMAND_TOKEN)
_COMMAND_SERVICE = ControlPlaneCommandService(
    authenticator=StaticAuthenticator(
        credentials={_COMMAND_TOKEN: StaticPrincipal(HERMES_COMMAND_PRINCIPAL)},
        authority_domain="newsroom.control-plane",
    )
)


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
    digests = {
        (source_id, item_key): digest for source_id, item_key, digest in expected
    }
    lineage = (
        ("ingest-old-1", "HK-04", "HK-04-0", 1, "COMPLETE"),
        ("ingest-old-2", "HK-04", "HK-04-0", 2, "COMPLETE"),
        ("ingest-uk10-unique", "UK-10", "UK-10-0", 1, "COMPLETE"),
        ("ingest-dead-letter", "UK-10", "UK-10-1", 1, "FAILED"),
    )
    for ingest_id, source_id, item_key, ordinal, outcome in lineage:
        store.execute(
            """
            INSERT INTO unpublished_graphiti_attempt_receipts(
                ingest_id, attempt_number, outcome, receipt_digest, receipt_json, at
            ) VALUES(?,?,?,?,?,?)
            """,
            (
                ingest_id,
                1,
                outcome,
                digest_canonical({"ingest_id": ingest_id}),
                json.dumps(
                    {
                        "ingest_id": ingest_id,
                        "source_id": source_id,
                        "item_key": item_key,
                        "revision_digest": digests[(source_id, item_key)],
                        "chunk_ordinal": ordinal,
                        "observed_at": _FIRST_POLL,
                    }
                ),
                _FIRST_POLL,
            ),
        )
    for source_id, item_key, ingest_ids in (
        ("HK-04", "HK-04-0", ("ingest-new-hk-1", "ingest-new-hk-2")),
        ("UK-10", "UK-10-0", ("ingest-new-uk10-0",)),
        ("UK-10", "UK-10-1", ("ingest-new-uk10-1",)),
    ):
        store.execute(
            """
            INSERT INTO unpublished_effective_revision_landed(
                source_id, item_key, revision_digest, published_at, updated_at,
                first_observed_at, ingest_ids_json, payload_digest,
                ledger_digest, at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                source_id,
                item_key,
                digests[(source_id, item_key)],
                "",
                "",
                _FIRST_POLL,
                json.dumps(ingest_ids),
                digest_canonical({"landed": [source_id, item_key]}),
                digest_canonical({"ledger": [source_id, item_key]}),
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
    store.execute(
        """
        INSERT INTO unpublished_graphiti_failures(
            ingest_id, source_id, item_key, retry_count, last_outcome,
            last_failure_code, dead_lettered, at
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            "ingest-dead-letter",
            "UK-10",
            "UK-10-1",
            3,
            "FAILED",
            "PROVIDER_ERROR",
            1,
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


def _run(
    proving: Path,
    unpublished: Path,
    tmp_path: Path,
    *,
    mode: str,
    dry_run_receipt: dict[str, object] | None = None,
    key: str | None = None,
    expected_mapping_digest: str | None = None,
    proof: AuthenticationProof = _COMMAND_PROOF,
) -> object:
    if mode == "live":
        digest = (
            "" if dry_run_receipt is None else str(dry_run_receipt["mapping_digest"])
        )
        return _COMMAND_SERVICE.reconcile_effective_revision_backlog(
            proving_store=str(proving),
            unpublished_store=str(unpublished),
            dry_run_receipt=dry_run_receipt or {},
            receipt_path=tmp_path / "live-receipt.json",
            backup_dir=tmp_path / "backups",
            evaluated_at=_EVALUATED_AT,
            idempotency_key=key or f"test-{uuid.uuid4()}",
            expected_mapping_digest=expected_mapping_digest or digest,
            proof=proof,
        )
    return reconcile_effective_revision_backlog(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        mode="dry-run",
        receipt_path=tmp_path / "dry-run-receipt.json",
        evaluated_at=_EVALUATED_AT,
    )


def _coordinator_payload(
    proving: Path, unpublished: Path, backup_dir: Path, *, status: str
) -> dict[str, object]:
    proving_backup = backup_dir / "proving_store.sqlite3"
    unpublished_backup = backup_dir / "unpublished_store.sqlite3"
    proving_result = _backup_store(proving, proving_backup)
    unpublished_result = _backup_store(unpublished, unpublished_backup)
    return {
        "status": status,
        "mapping_digest": "sha256:test",
        "proving_store": _store_identity(proving),
        "unpublished_store": _store_identity(unpublished),
        "proving_backup": str(proving_backup.resolve()),
        "unpublished_backup": str(unpublished_backup.resolve()),
        "proving_backup_digest": proving_result["digest"],
        "unpublished_backup_digest": unpublished_result["digest"],
    }


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
    assert live.gates["G4"] == "pass"
    assert live.command is not None
    assert live.command["caller_principal"] == HERMES_COMMAND_PRINCIPAL
    assert (
        live.command["writer_principal"]
        == "newsroom.control-plane.command-service"
    )
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
        assert (
            correction["identity_remap"]["old"]["first_observed_at"]
            == (correction["old_first_seen_at"])
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


def test_post_reconciliation_corpus_consumes_bound_remap_effects(
    tmp_path: Path,
) -> None:
    from newsroom.control_plane.corpus import merge_durable_revisions
    from newsroom.control_plane.store import list_remapped_ingest_effects

    proving, unpublished, _meta = _amplified_stores(tmp_path)
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    _run(
        proving,
        unpublished,
        tmp_path,
        mode="live",
        dry_run_receipt=dry.as_dict(),
    )
    proving_connection = sqlite3.connect(proving)
    first_seen = tuple(
        (str(source), str(item), str(digest), str(seen))
        for source, item, digest, seen in proving_connection.execute(
            "SELECT source_id,item_key,revision_digest,first_seen_at "
            "FROM proving_revision_first_seen"
        )
    )
    proving_connection.close()
    unpublished_connection = sqlite3.connect(unpublished)
    effects = list_remapped_ingest_effects(unpublished_connection)
    unpublished_connection.close()

    assert effects and len(effects[0]) == 7
    assert merge_durable_revisions(
        window_revisions=(), first_seen=first_seen, remapped_effects=effects
    )


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
    assert second.gates["G4"] == "pass"


def test_mapping_digest_binds_first_seen_correction_inputs(tmp_path: Path) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    first = _run(proving, unpublished, tmp_path, mode="dry-run")
    connection = sqlite3.connect(proving)
    connection.execute(
        """
        UPDATE proving_revision_first_seen SET first_seen_at=?
        WHERE (source_id, item_key, revision_digest) = (
            SELECT source_id, item_key, revision_digest
            FROM proving_revision_first_seen LIMIT 1
        )
        """,
        ("2026-08-20T11:59:00.000000Z",),
    )
    connection.commit()
    connection.close()

    second = _run(proving, unpublished, tmp_path, mode="dry-run")

    assert second.first_seen_corrections != first.first_seen_corrections
    assert second.mapping_digest != first.mapping_digest


def test_retention_never_moves_durable_first_seen_later(tmp_path: Path) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    durable_at = "2026-08-19T00:00:00.000000Z"
    connection = sqlite3.connect(proving)
    source_id, item_key, revision_digest = connection.execute(
        """SELECT source_id, item_key, revision_digest
           FROM proving_revision_first_seen
           WHERE source_id='HK-04'
           LIMIT 1"""
    ).fetchone()
    connection.execute(
        """UPDATE proving_revision_first_seen SET first_seen_at=?
           WHERE source_id=? AND item_key=? AND revision_digest=?""",
        (durable_at, source_id, item_key, revision_digest),
    )
    connection.execute(
        """INSERT INTO proving_effective_pull_first_seen(
               source_id,item_key,revision_digest,published_at,updated_at,first_seen_at
           ) VALUES(?,?,?,'','',?)""",
        (source_id, item_key, revision_digest, "2026-08-20T00:00:00.000000Z"),
    )
    connection.commit()
    connection.close()

    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    assert not any(
        row["source_id"] == source_id
        and row["item_key"] == item_key
        and row["revision_digest"] == revision_digest
        for row in dry.first_seen_corrections
    )
    _run(
        proving,
        unpublished,
        tmp_path,
        mode="live",
        dry_run_receipt=dry.as_dict(),
    )
    connection = sqlite3.connect(proving)
    revision_seen = connection.execute(
        """SELECT first_seen_at FROM proving_revision_first_seen
           WHERE source_id=? AND item_key=? AND revision_digest=?""",
        (source_id, item_key, revision_digest),
    ).fetchone()[0]
    pull_seen = connection.execute(
        """SELECT first_seen_at FROM proving_effective_pull_first_seen
           WHERE source_id=? AND item_key=? AND revision_digest=?""",
        (source_id, item_key, revision_digest),
    ).fetchone()[0]
    connection.close()
    assert revision_seen == durable_at
    assert pull_seen == durable_at


def test_append_only_census_distinguishes_version_markers(tmp_path: Path) -> None:
    connection = connect(str(tmp_path / "unpublished.sqlite3"))
    digest = "sha256:" + ("ab" * 32)
    for marker in ("2026-08-20T01:00:00.000000Z", "2026-08-20T02:00:00.000000Z"):
        connection.execute(
            """
            INSERT INTO unpublished_effective_revision_landed(
                source_id, item_key, revision_digest, published_at, updated_at,
                first_observed_at, ingest_ids_json, payload_digest,
                ledger_digest, at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "UK-01",
                "item",
                digest,
                "",
                marker,
                marker,
                "[]",
                "sha256:" + ("cd" * 32),
                "sha256:" + ("ef" * 32),
                marker,
            ),
        )
    before = _census_unpublished(connection)
    connection.execute(
        "DELETE FROM unpublished_effective_revision_landed WHERE updated_at=?",
        ("2026-08-20T02:00:00.000000Z",),
    )
    after = _census_unpublished(connection)
    connection.close()

    assert len(before["unpublished_effective_revision_landed"]) == 2
    assert len(after["unpublished_effective_revision_landed"]) == 1


def test_shared_reconciliation_schema_does_not_commit_callers_transaction() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute("BEGIN IMMEDIATE")

    ensure_reconciliation_schema(connection)

    assert connection.in_transaction
    connection.rollback()
    connection.close()


def test_v10_store_dry_run_and_live_preserve_landed_rows(tmp_path: Path) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    connection = sqlite3.connect(unpublished)
    connection.execute("DROP TABLE unpublished_effective_revision_landed")
    connection.execute(
        """
        CREATE TABLE unpublished_effective_revision_landed(
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
    connection.execute(
        """
        INSERT INTO unpublished_effective_revision_landed VALUES(?,?,?,?,?,?,?)
        """,
        (
            "UK-01",
            "legacy-item",
            "sha256:" + ("ab" * 32),
            _FIRST_POLL,
            "sha256:" + ("cd" * 32),
            "sha256:" + ("ef" * 32),
            _FIRST_POLL,
        ),
    )
    connection.commit()
    connection.close()
    before = _file_digest(unpublished)

    receipt = _run(proving, unpublished, tmp_path, mode="dry-run")

    assert receipt.gates["G1"] == "pass"
    assert _file_digest(unpublished) == before
    live = _run(
        proving,
        unpublished,
        tmp_path,
        mode="live",
        dry_run_receipt=receipt.as_dict(),
    )
    connection = sqlite3.connect(unpublished)
    assert connection.execute(
        "SELECT 1 FROM unpublished_effective_revision_landed "
        "WHERE item_key='legacy-item' AND legacy_v10=1"
    ).fetchone()
    connection.close()
    assert live.no_loss_proof["lost"] is False


def test_terminal_chunks_share_one_effective_pull_without_collision(
    tmp_path: Path,
) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    assert dry.unresolved_collisions == ()
    live = _run(
        proving,
        unpublished,
        tmp_path,
        mode="live",
        dry_run_receipt=dry.as_dict(),
    )
    connection = sqlite3.connect(unpublished)
    remapped = {
        row[0]
        for row in connection.execute(
            "SELECT old_ingest_id FROM unpublished_effective_revision_remap "
            "WHERE kind='RETAINED_LINEAGE_REMAP'"
        )
    }
    connection.close()
    assert {"ingest-old-1", "ingest-old-2"} <= remapped
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
    revision_digest = _triples("UK-01", second, url)[0][2]
    marker = "2026-01-02T09:00:00.000000Z"
    retained = connect(str(unpublished))
    retained.execute(
        "INSERT INTO unpublished_graphiti_failures VALUES(?,?,?,?,?,?,?,?)",
        ("failed-version", "UK-01", "same", 3, "FAILED", "ERROR", 1, _FIRST_POLL),
    )
    authority = {
        "record_id": "revision-second",
        "record_type": "SOURCE_REVISION",
        "source_id": "UK-01",
        "item_key": "same",
        "revision_digest": revision_digest,
        "published_at": marker,
        "updated_at": None,
        "chunk_ordinal": 1,
    }
    retained.execute(
        "INSERT INTO unpublished_graphiti_authority_records VALUES(?,?,?,?,?)",
        (
            "revision-second",
            "SOURCE_REVISION",
            digest_canonical(authority),
            json.dumps(authority),
            _FIRST_POLL,
        ),
    )
    receipt = {
        "ingest_id": "failed-version",
        "source_id": "UK-01",
        "item_key": "same",
        "revision_id": "revision-second",
        "published_at": marker,
        "updated_at": None,
    }
    retained.execute(
        "INSERT INTO unpublished_graphiti_attempt_receipts VALUES(?,?,?,?,?,?)",
        (
            "failed-version",
            1,
            "FAILED",
            digest_canonical(receipt),
            json.dumps(receipt),
            _FIRST_POLL,
        ),
    )
    retained.execute(
        """
        INSERT INTO unpublished_effective_revision_landed(
            source_id, item_key, revision_digest, published_at, updated_at,
            first_observed_at, ingest_ids_json, payload_digest, ledger_digest, at
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "UK-01",
            "same",
            revision_digest,
            marker,
            "",
            _poll_at(1),
            '["new-version"]',
            "sha256:" + ("12" * 32),
            "sha256:" + ("34" * 32),
            _poll_at(1),
        ),
    )
    retained.commit()
    retained.close()
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    assert dry.new_effective_revision_count == 2
    rules = [
        row
        for row in dry.attributed_source_version_rules
        if row["rule"] == "SOURCE_SUPPLIED_VERSION_MARKER"
    ]
    assert len(rules) == 1
    assert rules[0]["marker_count"] == 2
    assert dry.unresolved_collisions == ()
    _run(
        proving,
        unpublished,
        tmp_path,
        mode="live",
        dry_run_receipt=dry.as_dict(),
    )
    connection = sqlite3.connect(unpublished)
    remapped_marker = connection.execute(
        "SELECT published_at FROM unpublished_effective_revision_remap "
        "WHERE old_ingest_id='failed-version'"
    ).fetchone()[0]
    connection.close()
    assert remapped_marker == marker


def test_canonical_store_refuses_writable_open() -> None:
    with pytest.raises(CanonicalStoreGuardError, match="canonical store"):
        refuse_canonical_write(
            str(CANONICAL_PROVING_STORE), allow_canonical_mutation=False
        )


def test_cli_is_read_only_even_with_caller_supplied_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEWSROOM_COMMAND_SERVICE_TOKEN", _COMMAND_TOKEN)
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    dry_receipt = tmp_path / "dry.json"
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
    with pytest.raises(SystemExit):
        main(
            [
                "live",
                "--proving",
                str(proving),
                "--unpublished",
                str(unpublished),
                "--receipt",
                str(tmp_path / "live.json"),
            ]
        )


def test_live_requires_authenticated_command(tmp_path: Path) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    with pytest.raises(BacklogReconciliationError, match="ControlPlaneCommandService"):
        reconcile_effective_revision_backlog(
            proving_store=str(proving),
            unpublished_store=str(unpublished),
            mode="live",  # type: ignore[arg-type]
        )
    with pytest.raises(AuthenticationError, match="invalid authentication"):
        _run(
            proving,
            unpublished,
            tmp_path,
            mode="live",
            dry_run_receipt=dry.as_dict(),
            proof=AuthenticationProof(
                method="STATIC_TOKEN", credential="caller-supplied-token"
            ),
        )
    with pytest.raises(ReconciliationCommandError, match="mapping digest"):
        _run(
            proving,
            unpublished,
            tmp_path,
            mode="live",
            dry_run_receipt=dry.as_dict(),
            expected_mapping_digest="sha256:" + ("00" * 32),
        )


def test_live_rejects_a_live_receipt_as_dry_run_proof(tmp_path: Path) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    receipt = _run(proving, unpublished, tmp_path, mode="dry-run").as_dict()
    receipt.update(mode="live", mutated=True)
    with pytest.raises(BacklogReconciliationError, match="not a dry-run"):
        _run(
            proving,
            unpublished,
            tmp_path,
            mode="live",
            dry_run_receipt=receipt,
        )


def test_dry_receipt_is_bound_to_its_store_pair(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    proving_a, unpublished_a, _meta = _amplified_stores(tmp_path / "a")
    proving_b, unpublished_b, _meta = _amplified_stores(tmp_path / "b")
    dry_a = _run(proving_a, unpublished_a, tmp_path / "a", mode="dry-run")

    with pytest.raises(BacklogReconciliationError, match="other stores"):
        _run(
            proving_b,
            unpublished_b,
            tmp_path / "b",
            mode="live",
            dry_run_receipt=dry_a.as_dict(),
        )


def test_command_service_rejects_invalid_authentication(tmp_path: Path) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    with pytest.raises(AuthenticationError, match="invalid authentication"):
        _COMMAND_SERVICE.reconcile_effective_revision_backlog(
            proving_store=str(proving),
            unpublished_store=str(unpublished),
            dry_run_receipt=dry.as_dict(),
            receipt_path=tmp_path / "live.json",
            backup_dir=tmp_path / "backups",
            proof=AuthenticationProof(method="STATIC_TOKEN", credential="wrong"),
            idempotency_key="invalid",
            expected_mapping_digest=dry.mapping_digest,
        )


def test_live_transaction_has_a_time_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    calls = 0

    def elapsed() -> float:
        nonlocal calls
        calls += 1
        return 0.0 if calls == 1 else 10.0

    monkeypatch.setattr(
        "newsroom.control_plane.command_service.time.monotonic", elapsed
    )
    with pytest.raises(BacklogReconciliationError, match="five-second"):
        _run(
            proving,
            unpublished,
            tmp_path,
            mode="live",
            dry_run_receipt=dry.as_dict(),
        )


def test_live_command_is_idempotent_for_the_same_key(tmp_path: Path) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    first = _run(
        proving,
        unpublished,
        tmp_path,
        mode="live",
        dry_run_receipt=dry.as_dict(),
        key="same-live",
    )
    second = _run(
        proving,
        unpublished,
        tmp_path / "again",
        mode="live",
        dry_run_receipt=dry.as_dict(),
        key="same-live",
    )
    assert first.mutated is True
    assert second.mapping_digest == first.mapping_digest
    assert second.remapped_count == first.remapped_count


def test_completed_command_cannot_be_replayed_for_copied_stores(tmp_path: Path) -> None:
    source = tmp_path / "source"
    copied = tmp_path / "copied"
    source.mkdir()
    copied.mkdir()
    proving, unpublished, _meta = _amplified_stores(source)
    dry = _run(proving, unpublished, source, mode="dry-run")
    _run(
        proving,
        unpublished,
        source,
        mode="live",
        dry_run_receipt=dry.as_dict(),
        key="store-bound-command",
    )
    proving_copy = copied / "proving.sqlite3"
    unpublished_copy = copied / "unpublished.sqlite3"
    _backup_store(proving, proving_copy)
    _backup_store(unpublished, unpublished_copy)
    copied_dry = _run(
        proving_copy, unpublished_copy, copied, mode="dry-run"
    )

    with pytest.raises(ReconciliationCommandError, match="other stores"):
        _run(
            proving_copy,
            unpublished_copy,
            copied,
            mode="live",
            dry_run_receipt=copied_dry.as_dict(),
            key="store-bound-command",
        )


def test_command_schema_preserves_unknown_legacy_writer(tmp_path: Path) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    connection = sqlite3.connect(unpublished)
    connection.execute("DROP TABLE unpublished_reconciliation_commands")
    connection.executescript(
        """
        CREATE TABLE unpublished_reconciliation_commands(
            idempotency_key TEXT PRIMARY KEY,
            caller_principal TEXT NOT NULL,
            command_type TEXT NOT NULL,
            expected_mapping_digest TEXT NOT NULL,
            receipt_json TEXT NOT NULL,
            at TEXT NOT NULL
        );
        INSERT INTO unpublished_reconciliation_commands VALUES(
            'legacy','legacy.caller','legacy.command','sha256:legacy','{}',
            '2026-08-20T00:00:00.000000Z'
        );
        """
    )
    connection.commit()
    connection.close()
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")

    _run(
        proving,
        unpublished,
        tmp_path,
        mode="live",
        dry_run_receipt=dry.as_dict(),
        key="new-command",
    )

    connection = sqlite3.connect(unpublished)
    writers = dict(
        connection.execute(
            "SELECT idempotency_key, writer_principal "
            "FROM unpublished_reconciliation_commands"
        )
    )
    connection.close()
    assert writers["legacy"] is None
    assert writers["new-command"] == "newsroom.control-plane.command-service"


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
            WHERE kind='RETAINED_LINEAGE_REMAP'
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
    assert remapped == {
        "ingest-dead-letter",
        "ingest-old-1",
        "ingest-old-2",
        "ingest-uk10-unique",
    }
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


def test_spend_only_lineage_is_an_explicit_collision(tmp_path: Path) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    connection = sqlite3.connect(unpublished)
    connection.execute(
        """
        INSERT INTO unpublished_graphiti_spend(
            spend_id, ingest_id, attempt_number, proving_run_id,
            reserved_gbp_microunits, usage_basis, status, at
        ) VALUES('spend-only:1','spend-only',1,'run-1',1,'RESERVATION',
                 'UNRECONCILED',?)
        """,
        (_FIRST_POLL,),
    )
    connection.commit()
    connection.close()

    dry = _run(proving, unpublished, tmp_path, mode="dry-run")

    assert any(
        collision["ingest_ids"] == ["spend-only"]
        for collision in dry.unresolved_collisions
    )


def test_durable_orphan_is_in_the_exact_denominator(tmp_path: Path) -> None:
    from newsroom.control_plane.corpus import merge_durable_revisions

    proving, unpublished, _meta = _amplified_stores(tmp_path)
    connection = sqlite3.connect(proving)
    connection.execute(
        """
        INSERT INTO proving_revision_first_seen(
            source_id, item_key, revision_digest, first_seen_at
        ) VALUES('UK-99','expired','sha256:orphan',?)
        """,
        (_FIRST_POLL,),
    )
    connection.commit()
    first_seen = tuple(
        map(str, row)
        for row in connection.execute(
            "SELECT source_id,item_key,revision_digest,first_seen_at "
            "FROM proving_revision_first_seen"
        )
    )
    connection.close()

    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    runtime = merge_durable_revisions(window_revisions=(), first_seen=first_seen)

    assert dry.new_effective_revision_count == len(runtime)


def test_marker_specific_durable_orphans_are_counted_and_digested(
    tmp_path: Path,
) -> None:
    from newsroom.control_plane.corpus import (
        EffectivePullFirstSeen,
        merge_durable_revisions,
    )

    proving, unpublished, _meta = _amplified_stores(tmp_path)
    baseline = _run(proving, unpublished, tmp_path, mode="dry-run")
    connection = sqlite3.connect(proving)
    connection.execute(
        "INSERT INTO proving_revision_first_seen VALUES('UK-99','expired',?,?)",
        ("sha256:marker-orphan", _FIRST_POLL),
    )
    connection.executemany(
        """
        INSERT INTO proving_effective_pull_first_seen(
            source_id,item_key,revision_digest,published_at,updated_at,first_seen_at
        ) VALUES('UK-99','expired',?,?,?,?)
        """,
        (
            ("sha256:marker-orphan", "2026-08-19T00:00:00Z", "", _FIRST_POLL),
            ("sha256:marker-orphan", "2026-08-20T00:00:00Z", "", _FIRST_POLL),
        ),
    )
    connection.commit()
    with_markers = _run(proving, unpublished, tmp_path, mode="dry-run")
    connection.execute(
        "DELETE FROM proving_effective_pull_first_seen "
        "WHERE published_at='2026-08-20T00:00:00Z'"
    )
    connection.commit()
    connection.close()
    one_marker = _run(proving, unpublished, tmp_path, mode="dry-run")

    assert with_markers.new_effective_revision_count == (
        baseline.new_effective_revision_count + 2
    )
    assert one_marker.new_effective_revision_count == (
        baseline.new_effective_revision_count + 1
    )
    assert one_marker.mapping_digest != with_markers.mapping_digest
    marker_rule = next(
        rule
        for rule in with_markers.attributed_source_version_rules
        if rule["rule"] == "SOURCE_SUPPLIED_VERSION_MARKER"
        and rule["source_id"] == "UK-99"
    )
    assert marker_rule["marker_count"] == 2
    runtime = merge_durable_revisions(
        window_revisions=(),
        first_seen=(("UK-99", "expired", "sha256:marker-orphan", _FIRST_POLL),),
        pull_first_seen=(
            EffectivePullFirstSeen(
                "UK-99",
                "expired",
                "sha256:marker-orphan",
                "2026-08-19T00:00:00Z",
                "",
                _FIRST_POLL,
            ),
            EffectivePullFirstSeen(
                "UK-99",
                "expired",
                "sha256:marker-orphan",
                "2026-08-20T00:00:00Z",
                "",
                _FIRST_POLL,
            ),
        ),
    )
    assert len(runtime) == 2
    assert {revision.published_at for revision in runtime} == {
        "2026-08-19T00:00:00Z",
        "2026-08-20T00:00:00Z",
    }


def test_pruned_marker_is_counted_when_same_revision_remains_retained(
    tmp_path: Path,
) -> None:
    proving, unpublished, meta = _amplified_stores(tmp_path)
    baseline = _run(proving, unpublished, tmp_path, mode="dry-run")
    source_id, item_key, revision_digest = next(
        triple for triple in meta["expected"] if triple[0] == "UK-01"
    )
    connection = sqlite3.connect(proving)
    connection.execute(
        """
        INSERT INTO proving_effective_pull_first_seen(
            source_id,item_key,revision_digest,published_at,updated_at,first_seen_at
        ) VALUES(?,?,?,?,?,?)
        """,
        (
            source_id,
            item_key,
            revision_digest,
            "2025-12-31T09:00:00.000000Z",
            "",
            _FIRST_POLL,
        ),
    )
    connection.commit()
    connection.close()

    dry = _run(proving, unpublished, tmp_path, mode="dry-run")

    assert dry.new_effective_revision_count == baseline.new_effective_revision_count + 1
    rule = next(
        rule
        for rule in dry.attributed_source_version_rules
        if rule["rule"] == "SOURCE_SUPPLIED_VERSION_MARKER"
        and rule["source_id"] == "UK-01"
    )
    assert rule["marker_count"] == 2


def test_pruned_content_revision_is_not_rejected_as_a_digest_mismatch(
    tmp_path: Path,
) -> None:
    proving, unpublished, meta = _amplified_stores(tmp_path)
    baseline = _run(proving, unpublished, tmp_path, mode="dry-run")
    source_id, item_key, _digest = next(
        triple for triple in meta["expected"] if triple[0] == "UK-01"
    )
    connection = sqlite3.connect(proving)
    connection.execute(
        "INSERT INTO proving_revision_first_seen VALUES(?,?,?,?)",
        (source_id, item_key, "sha256:pruned-content", _FIRST_POLL),
    )
    connection.commit()
    connection.close()

    dry = _run(proving, unpublished, tmp_path, mode="dry-run")

    assert dry.new_effective_revision_count == baseline.new_effective_revision_count + 1
    assert any(
        rule["rule"] == "FIRST_SEEN_WITHOUT_RETAINED_OBSERVATION"
        and rule["revision_digest"] == "sha256:pruned-content"
        for rule in dry.attributed_source_version_rules
    )


def test_coverage_rows_are_part_of_the_append_only_census(tmp_path: Path) -> None:
    _proving, unpublished, _meta = _amplified_stores(tmp_path)
    connection = sqlite3.connect(unpublished)
    connection.execute(
        "INSERT INTO unpublished_graphiti_coverage(at, coverage_json) VALUES(?,?)",
        (_FIRST_POLL, "{}"),
    )
    before = _census_unpublished(connection)
    connection.execute("DELETE FROM unpublished_graphiti_coverage")
    after = _census_unpublished(connection)
    connection.close()

    assert before["unpublished_graphiti_coverage"] == frozenset({"1"})
    assert after["unpublished_graphiti_coverage"] == frozenset()


def test_sqlite_profile_enables_durable_writer_pragmas(tmp_path: Path) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    proving_conn = _readonly_connect(str(proving))
    unpublished_conn = _readonly_connect(str(unpublished))
    try:
        assert proving_conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert unpublished_conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert proving_conn.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert unpublished_conn.execute("PRAGMA synchronous").fetchone()[0] == 2
    finally:
        proving_conn.close()
        unpublished_conn.close()
    writer = sqlite3.connect(tmp_path / "profile.sqlite3")
    writer.execute("PRAGMA synchronous=OFF")
    apply_control_plane_sqlite_profile(writer)
    assert writer.execute("PRAGMA synchronous").fetchone()[0] == 2
    writer.close()


def test_committed_recovery_restores_both_stores_to_wal(tmp_path: Path) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    coordinator = _coordinator_payload(
        proving, unpublished, backup_dir, status="COMMITTED"
    )
    for path in (proving, unpublished):
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.close()
    _write_coordinator(
        backup_dir / COORDINATOR_NAME,
        coordinator,
    )

    assert not _restore_incomplete_dual_store(proving, unpublished, backup_dir)

    for path in (proving, unpublished):
        connection = sqlite3.connect(path)
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        connection.close()
    coordinator = json.loads(
        (backup_dir / COORDINATOR_NAME).read_text(encoding="utf-8")
    )
    assert coordinator["status"] == "COMPLETE"


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


def test_incomplete_coordinator_preserves_concurrent_append_before_retry(
    tmp_path: Path,
) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    backup_dir = tmp_path / "backups"
    _write_coordinator(
        backup_dir / COORDINATOR_NAME,
        {
            **_coordinator_payload(proving, unpublished, backup_dir, status="STARTED"),
            "mapping_digest": dry.mapping_digest,
        },
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
    assert canary is not None
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


def test_g2_rechecks_effect_drift_under_the_mutation_fence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import newsroom.control_plane.backlog_reconciliation as backlog

    proving, unpublished, _meta = _amplified_stores(tmp_path)
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    real_build_plan = backlog._build_plan
    calls = 0

    def build_plan_then_drift(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        plan = real_build_plan(*args, **kwargs)
        if calls == 2:
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
                    "ingest-after-g2",
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
                    "sha256:" + ("ef" * 32),
                    _FIRST_POLL,
                ),
            )
            connection.commit()
            connection.close()
        return plan

    monkeypatch.setattr(backlog, "_build_plan", build_plan_then_drift)
    with pytest.raises(BacklogReconciliationError, match="changed while planning"):
        _run(
            proving,
            unpublished,
            tmp_path,
            mode="live",
            dry_run_receipt=dry.as_dict(),
        )
    connection = sqlite3.connect(unpublished)
    assert connection.execute(
        "SELECT 1 FROM unpublished_graphiti_ingest WHERE ingest_id='ingest-after-g2'"
    ).fetchone()
    connection.close()


def test_data_version_fence_rejects_append_between_plan_and_census(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import newsroom.control_plane.backlog_reconciliation as backlog

    proving, unpublished, _meta = _amplified_stores(tmp_path)
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    real_census = backlog._census_unpublished
    calls = 0

    def census_after_append(connection: sqlite3.Connection) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            writer = sqlite3.connect(unpublished)
            writer.execute(
                """
                INSERT INTO unpublished_graphiti_failures(
                    ingest_id, source_id, item_key, retry_count, last_outcome,
                    last_failure_code, dead_lettered, at
                ) VALUES('concurrent-failure','UK-10','UK-10-1',1,
                         'FAILED','CONCURRENT',0,?)
                """,
                (_FIRST_POLL,),
            )
            writer.commit()
            writer.close()
        return real_census(connection)

    monkeypatch.setattr(backlog, "_census_unpublished", census_after_append)
    with pytest.raises(BacklogReconciliationError, match="changed before mutation"):
        _run(
            proving,
            unpublished,
            tmp_path,
            mode="live",
            dry_run_receipt=dry.as_dict(),
        )
    connection = sqlite3.connect(unpublished)
    assert connection.execute(
        "SELECT 1 FROM unpublished_graphiti_failures "
        "WHERE ingest_id='concurrent-failure'"
    ).fetchone()
    connection.close()
    coordinator = json.loads(
        (tmp_path / "backups" / COORDINATOR_NAME).read_text(encoding="utf-8")
    )
    assert coordinator["status"] == "ABORTED"


def test_g3_backup_is_taken_before_unpublished_schema_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import newsroom.control_plane.backlog_reconciliation as backlog

    proving, unpublished, _meta = _amplified_stores(tmp_path)
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    order: list[str] = []
    real_backup = backlog._backup_store
    real_ensure = backlog._ensure_landed_schema

    def tracked_backup(source: Path, destination: Path) -> dict[str, str]:
        order.append("backup")
        return real_backup(source, destination)

    def tracked_ensure(connection: sqlite3.Connection) -> None:
        order.append("ensure_landed_schema")
        real_ensure(connection)

    monkeypatch.setattr(backlog, "_backup_store", tracked_backup)
    monkeypatch.setattr(backlog, "_ensure_landed_schema", tracked_ensure)
    _run(
        proving,
        unpublished,
        tmp_path,
        mode="live",
        dry_run_receipt=dry.as_dict(),
    )
    assert "backup" in order
    assert "ensure_landed_schema" in order
    assert order.index("backup") < order.index("ensure_landed_schema")


def test_all_retained_chunks_are_bound_to_the_effective_pull(
    tmp_path: Path,
) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    assert dry.unresolved_collisions == ()
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
            WHERE kind='RETAINED_LINEAGE_REMAP'
              AND old_ingest_id IN ('ingest-old-1', 'ingest-old-2')
            """
        )
    }
    connection.close()
    assert remapped == {"ingest-old-1", "ingest-old-2"}
    assert live.unresolved_collisions == dry.unresolved_collisions


def test_dry_run_does_not_create_sqlite_sidecars(tmp_path: Path) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    sidecars = [
        Path(str(path) + suffix)
        for path in (proving, unpublished)
        for suffix in ("-wal", "-shm")
    ]
    assert not any(path.exists() for path in sidecars)
    _run(proving, unpublished, tmp_path, mode="dry-run")
    assert not any(path.exists() for path in sidecars)


def test_dry_run_does_not_touch_a_complete_wal_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    proving, unpublished, _meta = _amplified_stores(source)
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()

    def copy_with_wal(path: Path, *, proving_store: bool) -> Path:
        writer = sqlite3.connect(path)
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        if proving_store:
            writer.execute(
                "INSERT INTO proving_runs VALUES('wal-only', ?, 0, 0, 0, 0)",
                (_FIRST_POLL,),
            )
        else:
            writer.execute(
                "INSERT INTO unpublished_graphiti_coverage(at, coverage_json) "
                "VALUES(?, '{\"wal_only\":true}')",
                (_FIRST_POLL,),
            )
        writer.commit()
        copied = snapshot / path.name
        for suffix in ("", "-wal", "-shm"):
            shutil.copy2(Path(str(path) + suffix), Path(str(copied) + suffix))
        writer.close()
        return copied

    proving_copy = copy_with_wal(proving, proving_store=True)
    unpublished_copy = copy_with_wal(unpublished, proving_store=False)
    files = tuple(
        Path(str(path) + suffix)
        for path in (proving_copy, unpublished_copy)
        for suffix in ("", "-wal", "-shm")
    )
    before = tuple(
        (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
        for path in files
    )

    dry = _run(proving_copy, unpublished_copy, tmp_path, mode="dry-run")

    after = tuple(
        (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
        for path in files
    )
    assert dry.old_identity_count > 0
    assert after == before


def test_read_only_open_refuses_an_incomplete_sidecar_pair(tmp_path: Path) -> None:
    proving, _unpublished, _meta = _amplified_stores(tmp_path)
    wal = Path(str(proving) + "-wal")
    shm = Path(str(proving) + "-shm")
    wal.write_bytes(b"")
    with pytest.raises(BacklogReconciliationError, match="incomplete WAL"):
        _readonly_connect(str(proving))
    assert wal.read_bytes() == b""
    assert not shm.exists()


def test_backlog_module_has_no_live_mutation_entrypoint() -> None:
    import newsroom.control_plane.backlog_reconciliation as backlog

    assert not hasattr(backlog, "_reconcile_effective_revision_backlog")
    assert not hasattr(backlog, "_apply_crash_atomic_live_mutations")


def test_authentication_precedes_recovery(tmp_path: Path) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    backup_dir = tmp_path / "backups"
    _write_coordinator(
        backup_dir / COORDINATOR_NAME,
        _coordinator_payload(proving, unpublished, backup_dir, status="STARTED"),
    )
    connection = sqlite3.connect(proving)
    connection.execute(
        "INSERT INTO proving_runs VALUES('post-backup', ?, 0, 0, 0, 0)",
        (_FIRST_POLL,),
    )
    connection.commit()
    connection.close()

    with pytest.raises(AuthenticationError):
        _run(
            proving,
            unpublished,
            tmp_path,
            mode="live",
            dry_run_receipt=dry.as_dict(),
            proof=AuthenticationProof(method="STATIC_TOKEN", credential="wrong"),
        )
    connection = sqlite3.connect(proving)
    assert connection.execute(
        "SELECT 1 FROM proving_runs WHERE run_id='post-backup'"
    ).fetchone()
    connection.close()


def test_only_authenticated_hermes_may_submit_a_live_command(tmp_path: Path) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    service = ControlPlaneCommandService(
        authenticator=StaticAuthenticator(
            credentials={"other": StaticPrincipal("principal.other")},
            authority_domain="newsroom.control-plane",
        )
    )
    with pytest.raises(ReconciliationCommandError, match="caller principal"):
        service.reconcile_effective_revision_backlog(
            proving_store=str(proving),
            unpublished_store=str(unpublished),
            dry_run_receipt=dry.as_dict(),
            backup_dir=tmp_path / "backups",
            evaluated_at=_EVALUATED_AT,
            idempotency_key="other-caller",
            expected_mapping_digest=dry.mapping_digest,
            proof=AuthenticationProof(method="STATIC_TOKEN", credential="other"),
        )
    assert not (tmp_path / "backups" / COORDINATOR_NAME).exists()


def test_coordinator_refuses_a_different_store_pair(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    proving_a, unpublished_a, _meta = _amplified_stores(tmp_path / "a")
    proving_b, unpublished_b, _meta = _amplified_stores(tmp_path / "b")
    backup_dir = tmp_path / "backups"
    _write_coordinator(
        backup_dir / COORDINATOR_NAME,
        _coordinator_payload(proving_a, unpublished_a, backup_dir, status="STARTED"),
    )
    connection = sqlite3.connect(unpublished_b)
    connection.execute(
        "INSERT INTO unpublished_graphiti_coverage(at, coverage_json) VALUES(?,?)",
        (_FIRST_POLL, '{"b_only":true}'),
    )
    connection.commit()
    connection.close()

    with pytest.raises(BacklogReconciliationError, match="not bound"):
        _restore_incomplete_dual_store(proving_b, unpublished_b, backup_dir)
    connection = sqlite3.connect(unpublished_b)
    assert connection.execute(
        "SELECT 1 FROM unpublished_graphiti_coverage "
        "WHERE coverage_json='{\"b_only\":true}'"
    ).fetchone()
    connection.close()


def test_coordinator_refuses_replacement_database_at_the_same_path(
    tmp_path: Path,
) -> None:
    proving, unpublished, _meta = _amplified_stores(tmp_path)
    backup_dir = tmp_path / "backups"
    _write_coordinator(
        backup_dir / COORDINATOR_NAME,
        _coordinator_payload(proving, unpublished, backup_dir, status="STARTED"),
    )
    replacement = tmp_path / "replacement.sqlite3"
    shutil.copy2(proving, replacement)
    connection = sqlite3.connect(replacement)
    connection.execute(
        "INSERT INTO proving_runs VALUES('replacement-only', ?, 0, 0, 0, 0)",
        (_FIRST_POLL,),
    )
    connection.commit()
    connection.close()
    os.replace(replacement, proving)

    with pytest.raises(BacklogReconciliationError, match="not bound"):
        _restore_incomplete_dual_store(proving, unpublished, backup_dir)
    connection = sqlite3.connect(proving)
    assert connection.execute(
        "SELECT 1 FROM proving_runs WHERE run_id='replacement-only'"
    ).fetchone()
    connection.close()


def test_second_delete_failure_restores_both_wal_profiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import newsroom.control_plane.backlog_reconciliation as backlog

    proving, unpublished, _meta = _amplified_stores(tmp_path)
    dry = _run(proving, unpublished, tmp_path, mode="dry-run")
    real_set = backlog._set_journal_mode

    def fail_second(path: Path, mode: str) -> None:
        if path == unpublished and mode == "DELETE":
            raise RuntimeError("injected journal transition failure")
        real_set(path, mode)

    monkeypatch.setattr(backlog, "_set_journal_mode", fail_second)
    with pytest.raises(RuntimeError, match="injected"):
        _run(
            proving,
            unpublished,
            tmp_path,
            mode="live",
            dry_run_receipt=dry.as_dict(),
        )
    for path in (proving, unpublished):
        connection = sqlite3.connect(path)
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        connection.close()
