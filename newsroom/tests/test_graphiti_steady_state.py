from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import newsroom.control_plane.read_only_snapshot as snapshot_module
from newsroom.authority.canonical import digest_bytes, digest_canonical
from newsroom.control_plane.graphiti_events import (
    GRAPHITI_EVENT_PROJECTION_GENERATION,
    GRAPHITI_EVENT_PROJECTOR_VERSION,
)
from newsroom.control_plane.graphiti_steady_state import (
    build_graphiti_steady_state_packet,
    write_content_addressed_packet,
)
from newsroom.control_plane.read_only_snapshot import (
    ReadOnlySnapshotError,
    read_only_snapshot,
)
from newsroom.control_plane.store import connect
from newsroom.increment9.proving import PROVING_GATES, SOURCE_IDS, SOURCE_URLS
from scripts import graphiti_steady_state_report

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
        # Legacy projected events retained resolved units before this field
        # was populated; terminal receipt accounting must use unit_refs.
        "landed_ingest_ids": [],
        "landed_payload_digest": payload_digest,
        "unit_refs": [{"ingest_id": "ingest-1"}],
    }
    receipt = {
        "ingest_id": "ingest-1",
        "outcome": "COMPLETE",
        "proposal_count": 0,
        "entity_count": 0,
        "relation_count": 0,
        "raw_output_digest": "sha256:" + "3" * 64,
        "proposals": [],
    }
    receipt_digest = digest_canonical(receipt)
    receipt = {**receipt, "receipt_digest": receipt_digest}
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
            receipt_digest,
            at,
        ),
    )
    connection.execute(
        "INSERT INTO unpublished_graphiti_attempt_receipts("
        "ingest_id,attempt_number,outcome,receipt_digest,receipt_json,at) "
        "VALUES(?,?,?,?,?,?)",
        (
            "ingest-1",
            1,
            "COMPLETE",
            receipt_digest,
            json.dumps(receipt, sort_keys=True),
            at,
        ),
    )
    connection.execute(
        "INSERT INTO unpublished_graphiti_receipts(ingest_id,receipt_json) VALUES(?,?)",
        ("ingest-1", json.dumps(receipt, sort_keys=True)),
    )
    connection.commit()


def _turn_terminal_receipt_into_historical_raw_only(
    connection: sqlite3.Connection,
) -> None:
    row = connection.execute(
        "SELECT receipt_json FROM unpublished_graphiti_receipts WHERE ingest_id='ingest-1'"
    ).fetchone()
    assert row is not None
    receipt = json.loads(str(row[0]))
    receipt.pop("receipt_digest")
    receipt["proposal_count"] = 1
    receipt["proposals"] = [{"local_id": "historical-raw-only"}]
    receipt_digest = digest_canonical(receipt)
    retained = {**receipt, "receipt_digest": receipt_digest}
    retained_json = json.dumps(retained, sort_keys=True)
    connection.execute(
        "UPDATE unpublished_graphiti_ingest SET proposal_count=1,receipt_digest=? "
        "WHERE ingest_id='ingest-1'",
        (receipt_digest,),
    )
    connection.execute(
        "UPDATE unpublished_graphiti_receipts SET receipt_json=? "
        "WHERE ingest_id='ingest-1'",
        (retained_json,),
    )
    connection.execute(
        "UPDATE unpublished_graphiti_attempt_receipts "
        "SET receipt_digest=?,receipt_json=? WHERE ingest_id='ingest-1'",
        (receipt_digest, retained_json),
    )
    connection.execute(
        "UPDATE unpublished_graphiti_revision_events SET proposal_count=1"
    )
    connection.commit()


def _nonterminal_obligation(
    connection: sqlite3.Connection,
    *,
    ledger_seq: int,
    item_key: str,
    ingest_id: str,
    with_event: bool = True,
    provider_dispatched: int = 0,
) -> None:
    at = "2026-09-01T12:00:00.000000Z"
    ledger_digest = f"sha256:{ledger_seq:064x}"
    payload_digest = f"sha256:{ledger_seq + 100:064x}"
    revision_digest = f"revision-{item_key}"
    previous = connection.execute(
        "SELECT digest FROM ledger ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    connection.execute(
        "INSERT INTO ledger(seq,at,kind,payload_digest,payload_json,prev_digest,"
        "digest) VALUES(?,?,?,?,?,?,?)",
        (
            ledger_seq,
            at,
            "EFFECTIVE_REVISION_LANDED",
            payload_digest,
            "{}",
            "GENESIS" if previous is None else str(previous[0]),
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
            item_key,
            revision_digest,
            "",
            "",
            at,
            json.dumps([ingest_id]),
            0,
            payload_digest,
            ledger_digest,
            at,
        ),
    )
    if not with_event:
        return
    manifest = {
        "event_type": "EFFECTIVE_SOURCE_REVISION_LANDED",
        "ledger_seq": ledger_seq,
        "ledger_digest": ledger_digest,
        "landed_ingest_ids": [ingest_id],
        "landed_payload_digest": payload_digest,
        "unit_refs": [
            {
                "ingest_id": ingest_id,
                "revision_id": f"revision-id-{item_key}",
                "representation_digest": f"representation-{item_key}",
                "chunk_digest": f"chunk-{item_key}",
                "chunk_ordinal": 1,
                "predecessor_ingest_id": None,
            }
        ],
    }
    connection.execute(
        "INSERT INTO unpublished_graphiti_revision_events("
        "event_id,ledger_seq,ledger_digest,source_id,item_key,revision_digest,"
        "published_at,updated_at,landed_at,manifest_json,manifest_digest,"
        "unit_count,projector_version,projection_generation,state,attempt_count,"
        "available_at,provider_dispatched) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            ledger_digest,
            ledger_seq,
            ledger_digest,
            "source",
            item_key,
            revision_digest,
            "",
            "",
            at,
            json.dumps(manifest, sort_keys=True),
            digest_canonical(manifest),
            1,
            GRAPHITI_EVENT_PROJECTOR_VERSION,
            GRAPHITI_EVENT_PROJECTION_GENERATION,
            "QUEUED",
            0,
            at,
            provider_dispatched,
        ),
    )


def _current_unit(*, item_key: str, ingest_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        source_id="source",
        item_key=item_key,
        revision_digest=f"revision-{item_key}",
        published_at=None,
        updated_at=None,
        ingest_id=ingest_id,
        proving_run_id="run",
        observation_digest="observation",
        revision_id=f"revision-id-{item_key}",
        representation_digest=f"representation-{item_key}",
        digest=f"chunk-{item_key}",
        chunk_ordinal=1,
        chunk_count=1,
        predecessor_ingest_id=None,
        observed_at="2026-09-01T12:00:00.000000Z",
        effective_pull_first_observed_at="2026-09-01T12:00:00.000000Z",
        authority=None,
    )


def _packet(proving: Path, unpublished: Path, **kwargs: object) -> dict[str, object]:
    return build_graphiti_steady_state_packet(
        proving_store=proving,
        unpublished_store=unpublished,
        head_sha="head",
        tree_sha="tree",
        observed_at=NOW,
        **kwargs,
    )


def _seed_proving_accountability(
    proving: Path,
    *,
    held_source_id: str | None = None,
) -> None:
    connection = sqlite3.connect(proving)
    connection.executescript(
        """
        DROP TABLE proof;
        CREATE TABLE proving_runs(
            run_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            publication INTEGER NOT NULL,
            public_dispatch INTEGER NOT NULL,
            openrouter_invoked INTEGER NOT NULL,
            spend_gbp_minor INTEGER NOT NULL
        );
        CREATE TABLE proving_gates(
            run_id TEXT NOT NULL,
            gate_id TEXT NOT NULL,
            status TEXT NOT NULL,
            reason TEXT NOT NULL,
            PRIMARY KEY(run_id, gate_id)
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
            error TEXT,
            PRIMARY KEY(run_id, source_id, body_digest)
        );
        CREATE TABLE proving_source_health(
            source_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            status TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            attempts INTEGER NOT NULL,
            reason TEXT,
            next_retry_at TEXT,
            recovered_at TEXT,
            PRIMARY KEY(run_id, source_id)
        );
        """
    )
    connection.execute(
        "INSERT INTO proving_runs VALUES(?,?,?,?,?,?)",
        ("run-1", "2026-09-01T12:00:00Z", 0, 0, 0, 0),
    )
    connection.executemany(
        "INSERT INTO proving_gates VALUES(?,?,?,?)",
        (("run-1", gate_id, "PASS", "fixture") for gate_id in PROVING_GATES),
    )
    for source_id in SOURCE_IDS:
        body = source_id.encode()
        connection.execute(
            "INSERT INTO proving_observations VALUES(?,?,?,?,?,?,?,?,?)",
            (
                source_id,
                "run-1",
                "2026-09-01T12:00:00Z",
                SOURCE_URLS[source_id],
                200,
                digest_bytes(body),
                body,
                1,
                None,
            ),
        )
        held = source_id == held_source_id
        connection.execute(
            "INSERT INTO proving_source_health VALUES(?,?,?,?,?,?,?,?)",
            (
                source_id,
                "run-1",
                "HELD" if held else "ACTIVE",
                SOURCE_URLS[source_id],
                1,
                "EXPLICIT_FIXTURE_HOLD" if held else None,
                None,
                None,
            ),
        )
    connection.commit()
    connection.close()


def _authority_store(tmp_path: Path) -> Path:
    path = tmp_path / "authority.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE authority_migrations(
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at TEXT NOT NULL
        );
        CREATE TABLE ledger_events(ledger_seq INTEGER PRIMARY KEY);
        CREATE TABLE extraction_proposals(proposal_id TEXT PRIMARY KEY);
        CREATE TABLE entity_resolution_decisions(decision_id TEXT PRIMARY KEY);
        CREATE TABLE editorial_relation_decisions(decision_id TEXT PRIMARY KEY);
        CREATE TABLE graphiti_adapter_attempts(attempt_id TEXT PRIMARY KEY);
        INSERT INTO ledger_events VALUES(7);
        """
    )
    connection.executemany(
        "INSERT INTO authority_migrations VALUES(?,?,?,?)",
        (
            (13, "extraction_run_authority_v13", "sha256:" + "a" * 64, NOW.isoformat()),
            (14, "entity_resolution_authority_v14", "sha256:" + "b" * 64, NOW.isoformat()),
            (15, "editorial_relation_authority_v15", "sha256:" + "c" * 64, NOW.isoformat()),
            (16, "graphiti_proposal_adapter_v16", "sha256:" + "d" * 64, NOW.isoformat()),
        ),
    )
    connection.commit()
    connection.close()
    return path


def _campaign_input(packet: dict[str, object]) -> dict[str, object]:
    snapshots = packet["store_snapshots"]
    assert isinstance(snapshots, dict)
    snapshot_digests = {
        name: value["descriptor_digest"] for name, value in snapshots.items()
    }
    partition = packet["historical_partition"]
    assert isinstance(partition, dict)
    candidates = partition["current_preflight_candidates"]
    assert isinstance(candidates, list)
    selection = {
        "policy_id": "issue-895-current-preflight",
        "policy_version": "v1",
    }
    graph = {
        "destination_id": "neo4j-production",
        "family_id": "increment4",
        "ontology_version": "increment4-v1",
        "mapping_version": "graphiti-admission-v1",
        "projector_version": "increment4e-full-current-v1",
        "current_generation_id": "generation-active",
    }
    target_generation_id = digest_canonical(
        {
            "current_generation_id": graph["current_generation_id"],
            "projector_version": graph["projector_version"],
            "source_snapshot_digests": snapshot_digests,
            "cohort_manifest_digest": partition[
                "current_preflight_candidate_manifest_digest"
            ],
            "selection_policy_digest": digest_canonical(selection),
        }
    )
    return {
        "schema_version": "newsroom.graphiti-bounded-campaign-input.v1",
        "code_identity": {"head_sha": "head", "tree_sha": "tree"},
        "focus_gate": {
            "head_sha": "head",
            "tree_sha": "tree",
            "conclusion": "SUCCESS",
            "manifest_digest": "sha256:" + "f" * 64,
        },
        "source_snapshot_digests": snapshot_digests,
        "cohort": {
            "event_ids": [item["event_id"] for item in candidates],
            "manifest_digest": partition[
                "current_preflight_candidate_manifest_digest"
            ],
        },
        "selection_policy": {**selection, "digest": digest_canonical(selection)},
        "provider": {
            "provider_id": "provider",
            "model_id": "model",
            "embedding_model_id": "embedding",
        },
        "graph": {**graph, "target_generation_id": target_generation_id},
        "caps": {
            "per_event": {
                "proposals": 20,
                "entity_admits": 10,
                "relation_admits": 10,
                "effects": 20,
                "retries": 1,
                "fallbacks": 0,
            },
            "total": {
                "events": len(candidates),
                "proposals": 20,
                "entity_admits": 10,
                "relation_admits": 10,
                "effects": 20,
                "retries": 1,
                "fallbacks": 0,
                "wall_time_seconds": 600,
                "spend_gbp_microunits": 1000000,
            },
            "rate": {"events_per_minute": 1},
        },
        "ramp": {
            "initial_events": 1,
            "increment_events": 1,
            "observation_seconds": 60,
        },
        "recovery": {
            "backup_identity": "backup-before-campaign",
            "rollback_procedure_id": "restore-active-generation",
            "reconciliation_procedure_id": "increment4-full-reconciliation",
        },
        "immediate_stop_conditions": [
            "CAP_REACHED",
            "CONFIG_DRIFT",
            "INTEGRITY_FAILURE",
            "PROVIDER_FAILURE",
            "RECONCILIATION_FAILURE",
            "RIGHTS_DRIFT",
            "SNAPSHOT_DRIFT",
        ],
        "success_objectives": {
            "watermark": "selected cohort terminal",
            "backlog": 0,
            "velocity": "positive",
            "lag": "bounded",
            "reconciliation": "exact",
        },
        "campaign_authorised": False,
    }


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


def test_snapshot_rejects_wal_topology_created_during_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "plain.sqlite3"
    sqlite3.connect(path).execute("CREATE TABLE evidence(value TEXT)").connection.close()
    original_copy = snapshot_module._copy_with_digest

    def copy_then_add_wal(source: Path, destination: Path) -> str:
        digest = original_copy(source, destination)
        Path(f"{path}-wal").touch()
        Path(f"{path}-shm").touch()
        return digest

    monkeypatch.setattr(snapshot_module, "_copy_with_digest", copy_then_add_wal)

    with pytest.raises(ReadOnlySnapshotError, match="changed while taking"):
        with read_only_snapshot(path):
            pytest.fail("changed WAL topology was accepted")


def test_missing_campaign_inputs_are_finite_no_go(tmp_path: Path) -> None:
    proving, unpublished, connection = _stores(tmp_path)
    connection.close()

    packet = _packet(proving, unpublished)

    assert packet["verdict"] == "NO_GO"
    assert packet["readiness"] == "ENGINEERING_PREPARATION_ONLY"
    assert "AUTHORITY_STORE_UNCONFIGURED" in packet["blockers"]
    assert "CAMPAIGN_INPUT_MISSING" in packet["blockers"]
    assert packet["runtime_composition"]["durable_proposal_envelope_binding"] is True
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

    packet = _packet(proving, unpublished)

    assert packet["terminal_receipts"]["zero_proposal_success_count"] == 1
    assert packet["terminal_receipts"]["integrity_failures"] == []
    assert packet["landed_event_accounting"]["one_to_one"] is True


def test_historical_partition_is_total_disjoint_and_candidates_are_unauthorised(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proving, unpublished, connection = _stores(tmp_path)
    _terminal_zero_proposal(connection)
    _nonterminal_obligation(
        connection,
        ledger_seq=2,
        item_key="candidate",
        ingest_id="candidate-ingest",
    )
    _nonterminal_obligation(
        connection,
        ledger_seq=3,
        item_key="rights-held",
        ingest_id="held-ingest",
    )
    _nonterminal_obligation(
        connection,
        ledger_seq=4,
        item_key="changed",
        ingest_id="landed-ingest",
    )
    _nonterminal_obligation(
        connection,
        ledger_seq=5,
        item_key="no-event",
        ingest_id="missing-event-ingest",
        with_event=False,
    )
    _nonterminal_obligation(
        connection,
        ledger_seq=6,
        item_key="ambiguous-effect",
        ingest_id="ambiguous-ingest",
        provider_dispatched=1,
    )
    connection.commit()
    connection.close()
    calls = 0

    def load_once(_connection, *, evaluated_at):
        nonlocal calls
        calls += 1
        assert evaluated_at == NOW
        return (
            _current_unit(
                item_key="candidate",
                ingest_id="candidate-ingest",
            ),
            _current_unit(
                item_key="changed",
                ingest_id="current-ingest",
            ),
        )

    monkeypatch.setattr(
        "newsroom.control_plane.graphiti_steady_state."
        "load_graphiti_units_from_connection",
        load_once,
    )

    partition = _packet(proving, unpublished)["historical_partition"]

    assert calls == 1
    assert partition["universe_count"] == 6
    assert partition["partitioned_count"] == 6
    assert partition["disjoint"] is True
    assert partition["total"] is True
    assert partition["categories"]["VERIFIED_TERMINAL"]["ledger_sequences"] == [1]
    candidate = partition["categories"][
        "CURRENT_DISPATCH_PREFLIGHT_CANDIDATE"
    ]
    assert candidate["ledger_sequences"] == [2]
    assert candidate["dispatch_authorised"] is False
    assert partition["categories"]["RIGHTS_OR_INPUT_HELD"][
        "ledger_sequences"
    ] == [3, 4, 5]
    assert partition["categories"][
        "NON_REPLAYABLE_OR_AMBIGUOUS_EFFECT_HOLD"
    ]["ledger_sequences"] == [6]


def test_complete_exact_campaign_is_ready_without_authorising_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proving, unpublished, connection = _stores(tmp_path)
    _nonterminal_obligation(
        connection,
        ledger_seq=1,
        item_key="candidate",
        ingest_id="candidate-ingest",
    )
    _nonterminal_obligation(
        connection,
        ledger_seq=2,
        item_key="historical-hold",
        ingest_id="held-ingest",
        provider_dispatched=1,
    )
    connection.commit()
    connection.close()
    _seed_proving_accountability(proving)
    authority = _authority_store(tmp_path)
    monkeypatch.setattr(
        "newsroom.control_plane.graphiti_steady_state."
        "load_graphiti_units_from_connection",
        lambda _connection, *, evaluated_at: (
            _current_unit(item_key="candidate", ingest_id="candidate-ingest"),
        ),
    )

    preparation = _packet(proving, unpublished, authority_store=authority)
    campaign = _campaign_input(preparation)
    packet = _packet(
        proving,
        unpublished,
        authority_store=authority,
        campaign_input=campaign,
    )

    assert packet["blockers"] == []
    assert packet["verdict"] == "READY_FOR_OWNER_DECISION"
    assert packet["readiness"] == "F4_CAMPAIGN_READY_FOR_OWNER_DECISION"
    assert packet["bounded_campaign"]["campaign_authorised"] is False
    assert packet["bounded_campaign"]["cohort"]["dispatch_authorised"] is False
    assert packet["bounded_campaign"]["cohort"]["claim_performed"] is False
    assert packet["historical_partition"]["categories"][
        "NON_REPLAYABLE_OR_AMBIGUOUS_EFFECT_HOLD"
    ]["count"] == 1
    assert packet["runtime_composition"] == {
        "state": "PROVIDER_FREE_ENGINEERING_COMPLETE",
        "authority_store_configured": True,
        "durable_proposal_envelope_binding": True,
        "admission_policy_configured": True,
        "full_generation_projector_configured": True,
        "campaign_authorised": False,
    }


def test_self_addressed_cohort_and_snapshot_drift_are_no_go(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proving, unpublished, connection = _stores(tmp_path)
    _nonterminal_obligation(
        connection,
        ledger_seq=1,
        item_key="candidate",
        ingest_id="candidate-ingest",
    )
    connection.commit()
    connection.close()
    _seed_proving_accountability(proving)
    authority = _authority_store(tmp_path)
    monkeypatch.setattr(
        "newsroom.control_plane.graphiti_steady_state."
        "load_graphiti_units_from_connection",
        lambda _connection, *, evaluated_at: (
            _current_unit(item_key="candidate", ingest_id="candidate-ingest"),
        ),
    )
    preparation = _packet(proving, unpublished, authority_store=authority)
    campaign = _campaign_input(preparation)
    campaign["cohort"] = {
        "event_ids": ["self-addressed-event"],
        "manifest_digest": campaign["cohort"]["manifest_digest"],
    }
    campaign["source_snapshot_digests"] = {
        **campaign["source_snapshot_digests"],
        "authority": "sha256:" + "0" * 64,
    }

    packet = _packet(
        proving,
        unpublished,
        authority_store=authority,
        campaign_input=campaign,
    )

    assert packet["verdict"] == "NO_GO"
    assert "CAMPAIGN_COHORT_DIFFERS_FROM_CURRENT_PREFLIGHT" in packet["blockers"]
    assert "SOURCE_SNAPSHOT_DRIFT" in packet["blockers"]


def test_unverified_terminal_is_unclassified_in_historical_partition(
    tmp_path: Path,
) -> None:
    proving, unpublished, connection = _stores(tmp_path)
    _terminal_zero_proposal(connection)
    connection.execute(
        "UPDATE unpublished_graphiti_receipts SET receipt_json=? "
        "WHERE ingest_id='ingest-1'",
        (json.dumps({"raw_output_digest": "tampered", "proposals": []}),),
    )
    connection.commit()
    connection.close()

    partition = _packet(proving, unpublished)["historical_partition"]

    assert partition["categories"]["VERIFIED_TERMINAL"]["count"] == 0
    assert partition["categories"]["UNCLASSIFIED"]["ledger_sequences"] == [1]
    assert partition["categories"]["UNCLASSIFIED"]["reason_counts"] == {
        "TERMINAL_OUTCOME_UNVERIFIED": 1
    }


def test_historical_raw_only_proposal_is_immutable_non_blocking_hold(
    tmp_path: Path,
) -> None:
    proving, unpublished, connection = _stores(tmp_path)
    _terminal_zero_proposal(connection)
    _turn_terminal_receipt_into_historical_raw_only(connection)
    connection.close()

    packet = _packet(proving, unpublished)
    hold = packet["historical_partition"]["categories"][
        "NON_REPLAYABLE_OR_AMBIGUOUS_EFFECT_HOLD"
    ]

    assert hold["ledger_sequences"] == [1]
    assert hold["reason_counts"] == {
        "IMMUTABLE_RAW_PROPOSAL_WITHOUT_DURABLE_ENVELOPE": 1
    }
    assert "HISTORICAL_EFFECT_ADJUDICATION_REQUIRED" not in packet["blockers"]


def test_event_manifest_rejects_resolved_landed_identity_mismatch(
    tmp_path: Path,
) -> None:
    proving, unpublished, connection = _stores(tmp_path)
    _terminal_zero_proposal(connection)
    row = connection.execute(
        "SELECT manifest_json FROM unpublished_graphiti_revision_events"
    ).fetchone()
    assert row is not None
    manifest = json.loads(str(row[0]))
    manifest["landed_ingest_ids"] = ["different-ingest"]
    connection.execute(
        "UPDATE unpublished_graphiti_revision_events "
        "SET manifest_json=?,manifest_digest=?",
        (json.dumps(manifest, sort_keys=True), digest_canonical(manifest)),
    )
    connection.commit()
    connection.close()

    packet = _packet(proving, unpublished)

    assert "EVENT_MANIFEST_INTEGRITY_FAILURE" in packet["blockers"]
    assert packet["events"]["integrity_failures"] == [
        {
            "event_id": "sha256:" + "1" * 64,
            "reason": "MALFORMED_EVENT_MANIFEST",
        }
    ]


def test_explicit_source_hold_is_not_counted_as_successful_observation(
    tmp_path: Path,
) -> None:
    proving, unpublished, connection = _stores(tmp_path)
    connection.close()
    _seed_proving_accountability(proving, held_source_id=SOURCE_IDS[0])

    packet = _packet(proving, unpublished)
    accountability = packet["proving_accountability"]

    assert accountability["successful_observation_count"] == len(SOURCE_IDS) - 1
    assert accountability["typed_hold_count"] == 1
    assert accountability["unaccounted_source_ids"] == []
    assert "PROVING_SOURCE_UNACCOUNTED" not in packet["blockers"]


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

    packet = _packet(proving, unpublished)

    assert packet["verdict"] == "NO_GO"
    assert "TERMINAL_RECEIPT_INTEGRITY_FAILURE" in packet["blockers"]
    assert packet["terminal_receipts"]["integrity_failures"] == [
        {
            "ingest_id": "ingest-1",
            "reason": "RECEIPT_ENVELOPE_DIGEST_CONTRADICTION",
        }
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


def test_content_addressed_output_is_not_left_partial_when_publish_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proving, unpublished, connection = _stores(tmp_path)
    connection.close()
    packet = _packet(proving, unpublished)
    output_dir = tmp_path / "packets"

    def fail_publish(_source, _destination) -> None:
        raise OSError("fixture publish failure")

    monkeypatch.setattr("newsroom.control_plane.graphiti_steady_state.os.link", fail_publish)
    with pytest.raises(OSError, match="fixture publish failure"):
        write_content_addressed_packet(packet, output_dir)

    assert list(output_dir.iterdir()) == []


def test_report_requires_clean_exact_main(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        ("status", "--porcelain=v1", "--untracked-files=all"): "",
        ("rev-parse", "HEAD"): "head",
        ("rev-parse", "origin/main"): "head",
        ("rev-parse", "HEAD^{tree}"): "tree",
    }
    monkeypatch.setattr(
        graphiti_steady_state_report,
        "_git",
        lambda *args: values[args],
    )

    assert graphiti_steady_state_report._exact_main_identity() == ("head", "tree")

    values[("status", "--porcelain=v1", "--untracked-files=all")] = " M file"
    with pytest.raises(RuntimeError, match="clean worktree"):
        graphiti_steady_state_report._exact_main_identity()

    values[("status", "--porcelain=v1", "--untracked-files=all")] = ""
    values[("rev-parse", "origin/main")] = "other"
    with pytest.raises(RuntimeError, match="exact origin/main"):
        graphiti_steady_state_report._exact_main_identity()


def test_report_git_commands_are_anchored_to_executing_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class Result:
        stdout = "value\n"

    def run(command, **kwargs):
        observed["command"] = command
        observed.update(kwargs)
        return Result()

    monkeypatch.setattr(graphiti_steady_state_report.subprocess, "run", run)

    assert graphiti_steady_state_report._git("rev-parse", "HEAD") == "value"
    assert observed["cwd"] == graphiti_steady_state_report.REPOSITORY_ROOT


@pytest.mark.parametrize(
    ("verdict", "expected_exit"),
    (("READY_FOR_OWNER_DECISION", 0), ("NO_GO", 2)),
)
def test_report_exit_zero_only_for_owner_decision_ready(
    verdict: str,
    expected_exit: int,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        graphiti_steady_state_report,
        "_exact_main_identity",
        lambda: ("head", "tree"),
    )
    monkeypatch.setattr(
        graphiti_steady_state_report,
        "build_graphiti_steady_state_packet",
        lambda **_kwargs: {"verdict": verdict},
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "graphiti_steady_state_report.py",
            "--proving",
            "proving.sqlite3",
            "--unpublished",
            "unpublished.sqlite3",
        ],
    )

    assert graphiti_steady_state_report.main() == expected_exit
    assert json.loads(capsys.readouterr().out) == {"verdict": verdict}
