from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import newsroom.control_plane.read_only_snapshot as snapshot_module
from newsroom.authority.auth import (
    AuthenticationProof,
    StaticAuthenticator,
    StaticPrincipal,
)
from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
)
from newsroom.authority.migrations import MIGRATIONS
from newsroom.authority.types import UtcTimestamp
from newsroom.control_plane.command_service import ControlPlaneCommandService
from newsroom.control_plane.graphiti_events import (
    GRAPHITI_EVENT_PROJECTION_GENERATION,
    GRAPHITI_EVENT_PROJECTOR_VERSION,
)
from newsroom.control_plane.graphiti_admission import (
    GRAPHITI_ADMISSION_GENERATION_IDENTITY_VERSION,
    GRAPHITI_ADMISSION_RECONCILIATION_SCHEMA_VERSION,
    GraphitiAdmissionConsumerError,
    GraphitiGovernedDecision,
    GraphitiProjectionReconciliationReceipt,
)
from newsroom.control_plane.graphiti_steady_state import (
    GraphitiCampaignRuntime,
    _mint_graphiti_campaign_runtime,
    _spend,
    build_graphiti_steady_state_packet,
    graphiti_operational_partition_snapshot,
    validate_graphiti_campaign_packet,
    write_content_addressed_packet,
)

from newsroom.control_plane.graphiti_spend_reconciliation import (
    plan_graphiti_spend_reconciliation,
)
from newsroom.control_plane.read_only_snapshot import (
    ReadOnlySnapshotError,
    read_only_snapshot,
)
from newsroom.control_plane.store import (
    connect,
    effective_revision_landed_payload,
    insert_graphiti_attempt_receipt,
    reconcile_graphiti_spend,
    reserve_graphiti_spend,
)
from newsroom.effective_revision import EffectiveRevisionIdentity
from newsroom.extraction.types import ExtractionProposalKind
from newsroom.graphiti_adapter.admission import GraphitiProposalAdmissionAction
from newsroom.graphiti_adapter.identity import attempt_ids, typed_id
from newsroom.increment9.proving import PROVING_GATES, SOURCE_IDS, SOURCE_URLS
from newsroom.increment4.contracts import (
    increment4_admitted_family_v1,
    increment4_admitted_mapping_v1,
    increment4_admitted_ontology_v1,
)
from newsroom.projection import ProjectionGenerationId
from newsroom.projection.neo4j import StructuralReconciliationView
from scripts import graphiti_steady_state_report

GRAPH_DESTINATION_ID = "sha256:" + "9" * 64
NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)


def _stores(tmp_path: Path) -> tuple[Path, Path, sqlite3.Connection]:
    proving = tmp_path / "proving.sqlite3"
    sqlite3.connect(proving).execute(
        "CREATE TABLE proof(value TEXT)"
    ).connection.close()
    unpublished = tmp_path / "unpublished.sqlite3"
    connection = connect(str(unpublished))
    return proving, unpublished, connection


def test_spend_accepts_authenticated_retained_hold_but_not_unclassified_row(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    spend_id = "retained-hold:1"
    assert reserve_graphiti_spend(
        connection,
        spend_id=spend_id,
        ingest_id="retained-hold",
        attempt_number=1,
        proving_run_id="run-1",
        generation_id="generation",
        reserved_gbp_microunits=500_000,
        ceiling_gbp_microunits=1_000_000,
    )
    accounting = reconcile_graphiti_spend(
        connection, spend_id=spend_id, embedding_usage=None
    )
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="retained-hold",
        attempt_number=1,
        outcome="FAILED",
        receipt={
            "ingest_id": "retained-hold",
            "attempt_number": 1,
            "outcome": "FAILED",
            "provider_attempt_number": 1,
            "chat_invocations": [],
            "embedding_usage": None,
            "accounting": accounting,
        },
    )
    connection.commit()
    connection.close()
    evaluated_at = datetime(2026, 9, 1, 12, tzinfo=UTC)
    plan = plan_graphiti_spend_reconciliation(str(path), evaluated_at=evaluated_at)
    service = ControlPlaneCommandService(
        authenticator=StaticAuthenticator(
            credentials={
                "operator-token": StaticPrincipal(principal_id="newsroom.hermes")
            },
            authority_domain="newsroom.control-plane",
        )
    )
    service.reconcile_graphiti_spend(
        unpublished_store=str(path),
        dry_run_plan=plan.as_dict(),
        evaluated_at=evaluated_at,
        idempotency_key="retained-hold",
        expected_plan_digest=plan.plan_digest,
        proof=AuthenticationProof(method="STATIC_TOKEN", credential="operator-token"),
    )

    connection = sqlite3.connect(path)
    spend, blockers = _spend(connection)
    connection.close()

    assert blockers == []
    assert spend["status_counts"]["UNRECONCILED"] == 1
    assert spend["reserved_gbp_microunits_by_status"]["UNRECONCILED"] == 500_000
    assert spend["authenticated_retained_typed_hold_count"] == 1
    assert spend["retained_typed_hold_disposition_counts"] == {
        "UNRECONCILED_REPORTED_MISSING": 1
    }
    assert spend["undispositioned_unresolved_attempt_count"] == 0

    connection = connect(str(path))
    assert reserve_graphiti_spend(
        connection,
        spend_id="unclassified:1",
        ingest_id="unclassified",
        attempt_number=1,
        proving_run_id="run-1",
        generation_id="generation",
        reserved_gbp_microunits=250_000,
        ceiling_gbp_microunits=1_000_000,
    )
    connection.commit()
    spend, blockers = _spend(connection)
    connection.close()

    assert blockers == ["GRAPHITI_SPEND_UNRECONCILED"]
    assert spend["authenticated_retained_typed_hold_count"] == 1
    assert spend["undispositioned_unresolved_attempt_count"] == 1
    assert spend["undispositioned_unresolved_reserved_gbp_microunits"] == 250_000

    connection = connect(str(path))
    connection.execute(
        "UPDATE unpublished_graphiti_spend_dispositions SET evidence_json='{}' "
        "WHERE spend_id=?",
        (spend_id,),
    )
    connection.commit()
    connection.close()
    proving = tmp_path / "proving.sqlite3"
    sqlite3.connect(proving).execute(
        "CREATE TABLE proof(value TEXT)"
    ).connection.close()

    packet = _packet(proving, path)

    assert packet["verdict"] == "NO_GO"
    assert "GRAPHITI_SPEND_EVIDENCE_INTEGRITY_FAILURE" in packet["blockers"]
    assert packet["usage_and_spend"]["retained_disposition_integrity_valid"] is False
    assert packet["usage_and_spend"]["authenticated_retained_typed_hold_count"] == 0


def test_spend_incomplete_retained_receipt_is_machine_readable_no_go(
    tmp_path: Path,
) -> None:
    proving, unpublished, connection = _stores(tmp_path)
    connection.close()
    plan = plan_graphiti_spend_reconciliation(
        str(unpublished), evaluated_at=NOW
    )
    service = ControlPlaneCommandService(
        authenticator=StaticAuthenticator(
            credentials={
                "operator-token": StaticPrincipal(principal_id="newsroom.hermes")
            },
            authority_domain="newsroom.control-plane",
        )
    )
    service.reconcile_graphiti_spend(
        unpublished_store=str(unpublished),
        dry_run_plan=plan.as_dict(),
        evaluated_at=NOW,
        idempotency_key="incomplete-retained-receipt",
        expected_plan_digest=plan.plan_digest,
        proof=AuthenticationProof(method="STATIC_TOKEN", credential="operator-token"),
    )
    connection = sqlite3.connect(unpublished)
    connection.execute(
        "UPDATE unpublished_graphiti_spend_reconciliation_receipts "
        "SET receipt_json=?",
        (canonical_json_bytes({"disposition_counts": {}}).decode("utf-8"),),
    )
    connection.commit()
    connection.close()

    packet = _packet(proving, unpublished)

    assert packet["verdict"] == "NO_GO"
    assert "GRAPHITI_SPEND_EVIDENCE_INTEGRITY_FAILURE" in packet["blockers"]
    assert packet["usage_and_spend"]["retained_disposition_integrity_valid"] is False
    assert packet["usage_and_spend"]["authenticated_retained_typed_hold_count"] == 0


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


def _bind_terminal_raw_proposal_to_authority(
    unpublished: Path,
    authority: Path,
) -> None:
    unpublished_connection = sqlite3.connect(unpublished)
    row = unpublished_connection.execute(
        "SELECT receipt_json FROM unpublished_graphiti_receipts "
        "WHERE ingest_id='ingest-1'"
    ).fetchone()
    assert row is not None
    receipt = json.loads(str(row[0]))
    receipt.pop("receipt_digest")
    receipt["attempt_number"] = 1
    raw = dict(receipt)
    raw.pop("raw_output_digest", None)
    raw["raw_output_digest"] = digest_bytes(canonical_json_bytes(raw))
    receipt["raw_output_digest"] = raw["raw_output_digest"]
    raw_bytes = canonical_json_bytes(raw)
    receipt_digest = digest_canonical(receipt)
    retained_json = json.dumps(
        {**receipt, "receipt_digest": receipt_digest}, sort_keys=True
    )
    unpublished_connection.execute(
        "UPDATE unpublished_graphiti_ingest SET receipt_digest=? "
        "WHERE ingest_id='ingest-1'",
        (receipt_digest,),
    )
    unpublished_connection.execute(
        "UPDATE unpublished_graphiti_receipts SET receipt_json=? "
        "WHERE ingest_id='ingest-1'",
        (retained_json,),
    )
    unpublished_connection.execute(
        "UPDATE unpublished_graphiti_attempt_receipts "
        "SET receipt_digest=?,receipt_json=? WHERE ingest_id='ingest-1'",
        (receipt_digest, retained_json),
    )
    unpublished_connection.commit()
    unpublished_connection.close()

    proposal = receipt["proposals"][0]
    authority_connection = sqlite3.connect(authority)
    authority_connection.execute(
        "INSERT INTO graphiti_adapter_attempts VALUES(?,?,?,?,?,?,?)",
        (
            str(attempt_ids("ingest-1", 1)[0]),
            "COMPLETE",
            1,
            "proposal-set",
            "output",
            "run",
            "run-version",
        ),
    )
    authority_connection.execute(
        "INSERT INTO extraction_outputs VALUES(?,?,?,?,?)",
        (
            "output",
            "run",
            "run-version",
            raw_bytes,
            digest_bytes(raw_bytes),
        ),
    )
    authority_connection.execute(
        "INSERT INTO extraction_proposals VALUES(?,?,?,?,?,?,?)",
        (
            "proposal-id",
            "proposal-set",
            "output",
            "run",
            "run-version",
            proposal["local_id"],
            digest_canonical(proposal),
        ),
    )
    authority_connection.commit()
    authority_connection.close()


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
    revision_digest = f"revision-{item_key}"
    identity = EffectiveRevisionIdentity(
        source_id="source",
        item_key=item_key,
        revision_digest=revision_digest,
        first_observed_at=at,
    )
    payload = effective_revision_landed_payload(
        identity,
        ingest_ids=(ingest_id,),
        first_observed_at=at,
    )
    payload_digest = digest_canonical(payload)
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
            canonical_json_bytes(payload).decode("utf-8"),
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
        CREATE TABLE extraction_proposals(
            proposal_id TEXT PRIMARY KEY,
            proposal_set_id TEXT NOT NULL,
            output_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            run_version_id TEXT NOT NULL,
            local_id TEXT NOT NULL,
            semantic_digest TEXT NOT NULL
        );
        CREATE TABLE extraction_outputs(
            output_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            run_version_id TEXT NOT NULL,
            canonical_bytes BLOB NOT NULL,
            canonical_digest TEXT NOT NULL
        );
        CREATE TABLE entity_resolution_decisions(decision_id TEXT PRIMARY KEY);
        CREATE TABLE editorial_relation_decisions(decision_id TEXT PRIMARY KEY);
        CREATE TABLE graphiti_adapter_attempts(
            attempt_id TEXT PRIMARY KEY,
            outcome TEXT NOT NULL,
            proposal_count INTEGER NOT NULL,
            proposal_set_id TEXT,
            extraction_output_id TEXT,
            run_id TEXT NOT NULL,
            run_version_id TEXT NOT NULL
        );
        CREATE TABLE projection_ontology_contracts(
            contract_digest TEXT PRIMARY KEY,
            ontology_id TEXT NOT NULL,
            ontology_version TEXT NOT NULL
        );
        CREATE TABLE projection_mapping_contracts(
            contract_digest TEXT PRIMARY KEY,
            mapping_id TEXT NOT NULL,
            mapping_version TEXT NOT NULL,
            ontology_contract_digest TEXT NOT NULL
        );
        CREATE TABLE projection_family_definitions(
            definition_digest TEXT PRIMARY KEY,
            family_id TEXT NOT NULL,
            definition_version TEXT NOT NULL,
            projector_version TEXT NOT NULL,
            ontology_contract_digest TEXT NOT NULL,
            mapping_contract_digest TEXT NOT NULL
        );
        CREATE TABLE projection_families(
            family_id TEXT PRIMARY KEY,
            definition_digest TEXT NOT NULL
        );
        CREATE TABLE projection_generations(
            generation_id TEXT PRIMARY KEY,
            family_id TEXT NOT NULL,
            state TEXT NOT NULL,
            validated_through_ledger_seq INTEGER NOT NULL
        );
        INSERT INTO ledger_events VALUES(7);
        """
    )
    ontology = increment4_admitted_ontology_v1()
    mapping = increment4_admitted_mapping_v1(ontology)
    family = increment4_admitted_family_v1(ontology, mapping)
    connection.executemany(
        "INSERT INTO authority_migrations VALUES(?,?,?,?)",
        tuple(
            (int(item.version), str(item.name), str(item.checksum), NOW.isoformat())
            for item in MIGRATIONS
        ),
    )
    connection.execute(f"PRAGMA user_version={max(int(item.version) for item in MIGRATIONS)}")
    connection.execute(
        "INSERT INTO projection_ontology_contracts VALUES(?,?,?)",
        (ontology.contract_digest, ontology.ontology_id, ontology.ontology_version),
    )
    connection.execute(
        "INSERT INTO projection_mapping_contracts VALUES(?,?,?,?)",
        (
            mapping.contract_digest,
            mapping.mapping_id,
            mapping.mapping_version,
            mapping.ontology_contract_digest,
        ),
    )
    connection.execute(
        "INSERT INTO projection_family_definitions VALUES(?,?,?,?,?,?)",
        (
            family.digest,
            family.family_id,
            family.definition_version,
            family.projector_version,
            family.ontology_contract_digest,
            family.mapping_contract_digest,
        ),
    )
    connection.execute(
        "INSERT INTO projection_families VALUES(?,?)",
        (family.family_id, family.digest),
    )
    connection.execute(
        "INSERT INTO projection_generations VALUES(?,?,?,?)",
        (
            "00000000-0000-4000-8000-000000000895",
            family.family_id,
            "ACTIVE",
            7,
        ),
    )
    connection.commit()
    connection.close()
    return path


def _campaign_input(packet: dict[str, object]) -> dict[str, object]:
    partition = packet["historical_partition"]
    assert isinstance(partition, dict)
    candidates = partition["current_preflight_candidates"]
    assert isinstance(candidates, list)
    selection = {
        "policy_id": "issue-895-current-preflight",
        "policy_version": "v1",
    }
    return {
        "schema_version": "newsroom.graphiti-bounded-campaign-input.v3",
        "focus_gate": {
            "head_sha": "head",
            "tree_sha": "tree",
            "conclusion": "SUCCESS",
            "manifest_digest": "sha256:" + "f" * 64,
        },
        "selection_policy": selection,
        "provider": {
            "provider_id": "provider",
            "model_id": "model",
            "embedding_provider_id": "embedding-provider",
            "embedding_model_id": "embedding",
        },
        "graph": {"destination_id": GRAPH_DESTINATION_ID},
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
            "phases": [
                {
                    "phase_id": "phase-1",
                    "event_limit": len(candidates),
                    "entry_conditions": [
                        "EXACT_SNAPSHOT_AND_IDENTITY_RECONFIRMED",
                        "OWNER_F4_GO_RETAINED",
                    ],
                    "advance_conditions": [
                        "ALL_EXACT_RECEIPTS_RECONCILED",
                        "CAPS_AND_ACCOUNTING_RECONCILED",
                        "NO_STOP_CONDITION_OBSERVED",
                    ],
                }
            ]
        },
        "recovery": {
            "backup_identity": "backup-before-campaign",
            "rollback_procedure_id": "restore-active-generation",
            "reconciliation_procedure_id": "increment4-full-reconciliation",
        },
        "immediate_stop_conditions": [
            "CAP_REACHED",
            "CIRCUIT_OPEN",
            "CONFIG_DRIFT",
            "EXACT_RECEIPT_DRIFT",
            "GRAPH_IDENTITY_DRIFT",
            "IDENTITY_DRIFT",
            "INTEGRITY_FAILURE",
            "PROVIDER_FAILURE",
            "PROVIDER_USAGE_DRIFT",
            "PROJECTION_GENERATION_DRIFT",
            "RATE_CAP_REACHED",
            "RECONCILIATION_FAILURE",
            "RECONCILIATION_DRIFT",
            "RIGHTS_DRIFT",
            "SNAPSHOT_DRIFT",
            "SPEND_ACCOUNTING_DRIFT",
            "WALL_TIME_CAP_REACHED",
        ],
        "success_objectives": {
            "watermark": "selected cohort terminal",
            "backlog": 0,
            "velocity": "service_at_least_arrival",
            "lag": {"max_oldest_eligible_seconds": 300},
            "reconciliation": "exact",
        },
        "campaign_authorised": False,
    }


def _graph_destination_reconciliation(
    packet: dict[str, object],
    *,
    family_id: str | None = None,
    generation_id: str | None = None,
    checkpoint_ledger_seq: int | None = None,
    serving_time: str | None = None,
) -> StructuralReconciliationView:
    authority_evidence = packet["authority_snapshot_evidence"]
    assert isinstance(authority_evidence, dict)
    graph = authority_evidence["active_projection_authority"]
    assert isinstance(graph, dict)
    return StructuralReconciliationView(
        family_id=family_id or str(graph["family_id"]),
        generation_id=ProjectionGenerationId.parse(
            generation_id or str(graph["generation_id"])
        ),
        checkpoint_ledger_seq=(
            int(graph["validated_through_ledger_seq"])
            if checkpoint_ledger_seq is None
            else checkpoint_ledger_seq
        ),
        projection_state_digest="sha256:" + "d" * 64,
        serving_time=UtcTimestamp.parse(
            serving_time or str(packet["observed_at"])
        ),
    )


def _governed_runtime(packet: dict[str, object]) -> GraphitiCampaignRuntime:
    stores = packet["store_snapshots"]
    assert isinstance(stores, dict)
    authority = stores["authority"]
    assert isinstance(authority, dict)
    return _mint_graphiti_campaign_runtime(
        graphiti=object(),
        admission_factory=lambda _connection: object(),
        graph_state_fence=lambda _campaign: {},
        graph_destination_id=GRAPH_DESTINATION_ID,
        authority_store_source_path=str(authority["source_path"]),
        authority_store_descriptor_digest=str(authority["descriptor_digest"]),
    )


def _bounded_candidate_packet(
    proving: Path,
    unpublished: Path,
    authority: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    monkeypatch.setattr(
        "newsroom.control_plane.graphiti_steady_state."
        "load_graphiti_units_from_connection",
        lambda _connection, *, evaluated_at: (
            _current_unit(item_key="candidate", ingest_id="candidate-ingest"),
        ),
    )
    preparation = _packet(
        proving,
        unpublished,
        authority_store=authority,
    )
    return _packet(
        proving,
        unpublished,
        authority_store=authority,
        campaign_input=_campaign_input(preparation),
        graph_destination_reconciliation=(
            _graph_destination_reconciliation(preparation)
        ),
        governed_runtime=_governed_runtime(preparation),
    )


def _seed_admission_obligation(
    connection: sqlite3.Connection,
    *,
    action: str | None,
) -> None:
    at = "2026-09-01T12:00:00.000000Z"
    proposal_key = "proposal-1"
    connection.execute(
        "INSERT INTO unpublished_graphiti_admission_queue("
        "proposal_key,ingest_id,source_revision_id,source_receipt_digest,"
        "proposal_digest,proposal_kind,request_json,request_digest,state,"
        "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            proposal_key,
            "proposal-ingest",
            "proposal-revision",
            "sha256:" + "1" * 64,
            "sha256:" + "2" * 64,
            "ENTITY_MENTION",
            "{}",
            "sha256:" + "3" * 64,
            "READY" if action is None else "TERMINAL",
            at,
            at,
        ),
    )
    if action is not None:
        decision = GraphitiGovernedDecision(
            proposal_key=proposal_key,
            proposal_digest="sha256:" + "2" * 64,
            proposal_kind=ExtractionProposalKind.ENTITY_MENTION,
            proposal_local_id="proposal-local-1",
            action=GraphitiProposalAdmissionAction(action),
            decision_id="decision-1",
            authority_ledger_seq=1,
            reason_code="FIXTURE_POLICY",
            authority_receipt_digest="sha256:" + "4" * 64,
        )
        decision_json = canonical_json_bytes(decision.canonical_value()).decode(
            "utf-8"
        )
        connection.execute(
            "INSERT INTO unpublished_graphiti_admission_decisions("
            "proposal_key,action,decision_id,authority_ledger_seq,reason_code,"
            "authority_receipt_digest,decision_json,decision_digest,decided_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (
                proposal_key,
                action,
                "decision-1",
                1,
                "FIXTURE_POLICY",
                "sha256:" + "4" * 64,
                decision_json,
                digest_bytes(decision_json.encode("utf-8")),
                at,
            ),
        )
    connection.commit()


def test_campaign_runtime_rejects_non_governed_construction_token() -> None:
    with pytest.raises(
        TypeError, match="campaign runtimes require the governed worker composer"
    ):
        GraphitiCampaignRuntime(
            graphiti=object(),
            admission_factory=lambda _connection: object(),
            graph_state_fence=lambda _campaign: {},
            authority_store_source_path="/authority.sqlite3",
            authority_store_descriptor_digest="sha256:" + "a" * 64,
            graph_destination_id=GRAPH_DESTINATION_ID,
            _construction_token=object(),
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
    assert packet["runtime_composition"]["durable_proposal_envelope_binding"] is False
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
    legacy_manifest = json.loads(
        connection.execute(
            "SELECT manifest_json FROM unpublished_graphiti_revision_events "
            "WHERE ledger_seq=2"
        ).fetchone()[0]
    )
    legacy_manifest["landed_ingest_ids"] = []
    legacy_manifest["unit_refs"] = []
    connection.execute(
        "UPDATE unpublished_graphiti_revision_events "
        "SET unit_count=0,manifest_json=?,manifest_digest=? WHERE ledger_seq=2",
        (
            json.dumps(legacy_manifest, sort_keys=True),
            digest_canonical(legacy_manifest),
        ),
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
                ingest_id="hydrated-current-ingest",
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
    assert partition["current_preflight_candidates"][0]["ingest_ids"] == [
        "hydrated-current-ingest"
    ]
    assert partition["categories"]["RIGHTS_OR_INPUT_HELD"][
        "ledger_sequences"
    ] == [3, 4, 5]
    assert partition["categories"]["RIGHTS_OR_INPUT_HELD"]["reason_counts"][
        "RESOLVED_INGEST_IDS_DIFFER_FROM_LANDED"
    ] == 1
    assert partition["categories"][
        "NON_REPLAYABLE_OR_AMBIGUOUS_EFFECT_HOLD"
    ]["ledger_sequences"] == [6]


def test_operational_partition_reuses_fresh_gap_and_hold_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proving, _unpublished, connection = _stores(tmp_path)
    _nonterminal_obligation(
        connection,
        ledger_seq=1,
        item_key="candidate",
        ingest_id="candidate-ingest",
    )
    _nonterminal_obligation(
        connection,
        ledger_seq=2,
        item_key="projectable-gap",
        ingest_id="gap-ingest",
        with_event=False,
    )
    _nonterminal_obligation(
        connection,
        ledger_seq=3,
        item_key="claimed-history",
        ingest_id="claimed-ingest",
    )
    connection.execute(
        "UPDATE unpublished_graphiti_revision_events SET state='CLAIMED',"
        "claim_owner='historical-worker',claim_expires_at=? WHERE ledger_seq=3",
        ("2026-09-01T12:05:00.000000Z",),
    )
    _nonterminal_obligation(
        connection,
        ledger_seq=4,
        item_key="rights-held-gap",
        ingest_id="held-ingest",
        with_event=False,
    )
    connection.commit()
    proving_connection = sqlite3.connect(proving)
    authority = sqlite3.connect(":memory:")
    monkeypatch.setattr(
        "newsroom.control_plane.graphiti_steady_state."
        "load_graphiti_units_from_connection",
        lambda _connection, *, evaluated_at: (
            _current_unit(item_key="candidate", ingest_id="candidate-ingest"),
            _current_unit(item_key="projectable-gap", ingest_id="gap-ingest"),
        ),
    )

    snapshot = graphiti_operational_partition_snapshot(
        proving_connection,
        connection,
        authority=authority,
        observed_at=NOW,
    )

    assert [item["kind"] for item in snapshot["actionable"]] == [
        "FRESH_EVENT",
        "PROJECT_EVENT_GAP",
    ]
    assert [item["ledger_seq"] for item in snapshot["holds"]] == [3, 4]
    assert snapshot["snapshot_digest"] == digest_canonical(
        {key: value for key, value in snapshot.items() if key != "snapshot_digest"}
    )
    authority.close()
    proving_connection.close()
    connection.close()


def test_complete_packet_remains_no_go_without_graph_readback(
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

    assert packet["verdict"] == "NO_GO"
    assert packet["readiness"] == "ENGINEERING_PREPARATION_ONLY"
    assert "GRAPH_DESTINATION_READBACK_UNAVAILABLE" in packet["blockers"]
    assert packet["bounded_campaign"]["campaign_authorised"] is False
    assert packet["bounded_campaign"]["cohort"]["dispatch_authorised"] is False
    assert packet["bounded_campaign"]["cohort"]["claim_performed"] is False
    assert packet["historical_partition"]["categories"][
        "NON_REPLAYABLE_OR_AMBIGUOUS_EFFECT_HOLD"
    ]["count"] == 1
    assert packet["runtime_composition"] == {
        "state": "CANONICAL_OPERATOR_RUNTIME_UNCONFIGURED",
        "authority_store_configured": True,
        "graph_destination_id": None,
        "authority_store_source_path": None,
        "authority_store_descriptor_digest": None,
        "durable_proposal_envelope_binding": False,
        "admission_policy_configured": False,
        "full_generation_projector_configured": False,
        "dormant_worker_path_wired": False,
        "campaign_packet_enforced": False,
        "actual_graph_readback_observed": False,
        "campaign_authorised": False,
    }


def test_owner_input_rejects_extra_derived_fields(
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
    campaign["code_identity"] = {"head_sha": "head", "tree_sha": "tree"}
    campaign["cohort"] = {
        "event_ids": ["self-addressed-event"],
        "manifest_digest": "sha256:" + "0" * 64,
    }
    campaign["source_snapshot_digests"] = {}

    packet = _packet(
        proving,
        unpublished,
        authority_store=authority,
        campaign_input=campaign,
    )

    assert packet["verdict"] == "NO_GO"
    assert "CAMPAIGN_FIELDS_INVALID" in packet["blockers"]


def test_authenticated_graph_readback_builds_valid_ready_packet(
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
    reconciliation = _graph_destination_reconciliation(preparation)
    runtime = _governed_runtime(preparation)

    packet = _packet(
        proving,
        unpublished,
        authority_store=authority,
        campaign_input=campaign,
        graph_destination_reconciliation=reconciliation,
        governed_runtime=runtime,
    )

    assert packet["verdict"] == "READY_FOR_OWNER_DECISION"
    assert packet["readiness"] == "F4_CAMPAIGN_READY_FOR_OWNER_DECISION"
    assert packet["blockers"] == []
    assert packet["bounded_campaign"]["cohort"] == {
        "event_ids": ["sha256:" + f"{1:064x}"],
        "manifest_digest": packet["historical_partition"][
            "current_preflight_candidate_manifest_digest"
        ],
        "events": packet["historical_partition"]["current_preflight_candidates"],
        "dispatch_authorised": False,
        "claim_performed": False,
    }
    assert packet["bounded_campaign"]["graph_destination_readback"] == {
        "destination_id": GRAPH_DESTINATION_ID,
        "family_id": reconciliation.family_id,
        "generation_id": str(reconciliation.generation_id),
        "checkpoint_ledger_seq": reconciliation.checkpoint_ledger_seq,
        "projection_state_digest": reconciliation.projection_state_digest,
        "serving_time": reconciliation.serving_time.to_text(),
    }
    assert packet["runtime_composition"]["actual_graph_readback_observed"] is True
    assert packet["runtime_composition"]["authority_store_source_path"] == (
        packet["store_snapshots"]["authority"]["source_path"]
    )
    assert packet["runtime_composition"][
        "authority_store_descriptor_digest"
    ] == packet["store_snapshots"]["authority"]["descriptor_digest"]
    assert packet["runtime_composition"]["graph_destination_id"] == (
        GRAPH_DESTINATION_ID
    )
    assert validate_graphiti_campaign_packet(packet) == packet["bounded_campaign"]

    cap_drift = json.loads(json.dumps(packet))
    cap_drift["bounded_campaign"]["caps"]["total"]["events"] = 2
    cap_drift["packet_digest"] = digest_canonical(
        {key: value for key, value in cap_drift.items() if key != "packet_digest"}
    )
    with pytest.raises(ValueError, match="caps differ"):
        validate_graphiti_campaign_packet(cap_drift)

    ramp_drift = json.loads(json.dumps(packet))
    ramp_drift["bounded_campaign"]["ramp"]["phases"][-1]["event_limit"] = 2
    ramp_drift["packet_digest"] = digest_canonical(
        {key: value for key, value in ramp_drift.items() if key != "packet_digest"}
    )
    with pytest.raises(ValueError, match="cohort cap differs"):
        validate_graphiti_campaign_packet(ramp_drift)

    stop_drift = json.loads(json.dumps(packet))
    stop_drift["bounded_campaign"]["immediate_stop_conditions"].remove(
        "RIGHTS_DRIFT"
    )
    stop_drift["packet_digest"] = digest_canonical(
        {key: value for key, value in stop_drift.items() if key != "packet_digest"}
    )
    with pytest.raises(ValueError, match="stop conditions differ"):
        validate_graphiti_campaign_packet(stop_drift)

    runtime_graph_drift = json.loads(json.dumps(packet))
    runtime_graph_drift["runtime_composition"]["graph_destination_id"] = (
        "sha256:" + "8" * 64
    )
    runtime_graph_drift["packet_digest"] = digest_canonical(
        {
            key: value
            for key, value in runtime_graph_drift.items()
            if key != "packet_digest"
        }
    )
    with pytest.raises(ValueError, match="graph readback differs"):
        validate_graphiti_campaign_packet(runtime_graph_drift)


def test_admission_backlog_blocks_owner_decision_ready(
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
    _seed_admission_obligation(connection, action=None)
    connection.close()
    _seed_proving_accountability(proving)
    authority = _authority_store(tmp_path)

    packet = _bounded_candidate_packet(
        proving,
        unpublished,
        authority,
        monkeypatch,
    )

    assert packet["verdict"] == "NO_GO"
    assert packet["admission"]["proposal_denominator"] == 1
    assert packet["admission"]["admission_backlog"] == 1
    assert packet["admission"]["projection_reconciled"] is False
    assert "ADMISSION_BACKLOG_PRESENT" in packet["blockers"]
    assert "ADMISSION_PROJECTION_UNRECONCILED" in packet["blockers"]
    assert "ADMISSION_DEAD_LETTER_PRESENT" not in packet["blockers"]
    assert "ADMISSION_INTEGRITY_HOLD_PRESENT" not in packet["blockers"]


def test_all_hold_admission_rejects_unbound_reconciliation(
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
    _seed_admission_obligation(connection, action="HOLD")
    connection.close()
    _seed_proving_accountability(proving)
    authority = _authority_store(tmp_path)

    unreconciled = _bounded_candidate_packet(
        proving,
        unpublished,
        authority,
        monkeypatch,
    )

    assert unreconciled["verdict"] == "NO_GO"
    assert unreconciled["admission"]["proposal_denominator"] == 1
    assert unreconciled["admission"]["admitted_count"] == 0
    assert unreconciled["admission"]["held_count"] == 1
    assert unreconciled["admission"]["admission_backlog"] == 0
    assert unreconciled["admission"]["projection_reconciled"] is False
    assert "ADMISSION_PROJECTION_UNRECONCILED" in unreconciled["blockers"]
    assert "ADMISSION_BACKLOG_PRESENT" not in unreconciled["blockers"]

    connection = sqlite3.connect(unpublished)
    receipt = GraphitiProjectionReconciliationReceipt(
        generation_id="00000000-0000-4000-8000-000000000895",
        expected_effect_ids=(),
        actual_effect_ids=(),
        authority_watermark=1,
        receipt_digest="sha256:" + "5" * 64,
    ).canonical_value()
    connection.execute(
        "INSERT INTO unpublished_graphiti_projection_reconciliations("
        "receipt_digest,projector_family_id,generation_id,"
        "authority_watermark,receipt_json,reconciled_at) VALUES(?,?,?,?,?,?)",
        (
            receipt["receipt_digest"],
            receipt["projector_family_id"],
            receipt["generation_id"],
            1,
            canonical_json_bytes(receipt).decode("utf-8"),
            "2026-09-01T12:00:00.000000Z",
        ),
    )
    connection.commit()
    connection.close()

    unbound = _bounded_candidate_packet(
        proving,
        unpublished,
        authority,
        monkeypatch,
    )

    assert unbound["verdict"] == "NO_GO"
    assert unbound["admission"]["telemetry_projection_reconciled"] is True
    assert unbound["admission"]["projection_reconciled"] is False
    assert unbound["admission"]["exact_cohort_reconciliation"]["total"] is False
    assert "ADMISSION_PROJECTION_UNRECONCILED" in unbound["blockers"]


def test_orphan_reconciliation_blocks_without_a_proposal_denominator(
    tmp_path: Path,
) -> None:
    proving, unpublished, connection = _stores(tmp_path)
    receipt = GraphitiProjectionReconciliationReceipt(
        generation_id="00000000-0000-4000-8000-000000000895",
        expected_effect_ids=(),
        actual_effect_ids=(),
        authority_watermark=1,
        receipt_digest="sha256:" + "5" * 64,
    ).canonical_value()
    connection.execute(
        "INSERT INTO unpublished_graphiti_projection_reconciliations("
        "receipt_digest,projector_family_id,generation_id,"
        "authority_watermark,receipt_json,reconciled_at) VALUES(?,?,?,?,?,?)",
        (
            receipt["receipt_digest"],
            receipt["projector_family_id"],
            receipt["generation_id"],
            1,
            canonical_json_bytes(receipt).decode("utf-8"),
            "2026-09-01T12:00:00.000000Z",
        ),
    )
    connection.commit()
    connection.close()

    packet = _packet(proving, unpublished)

    assert packet["admission"]["proposal_denominator"] == 0
    assert packet["admission"]["exact_cohort_reconciliation"]["total"] is False
    assert "ADMISSION_PROJECTION_UNRECONCILED" in packet["blockers"]


def test_exact_all_hold_generation_reconciliation_is_ready(
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
    _seed_admission_obligation(connection, action="HOLD")
    cohort_digest = "sha256:" + "6" * 64
    generation_id = str(
        typed_id(
            ProjectionGenerationId,
            GRAPHITI_ADMISSION_GENERATION_IDENTITY_VERSION,
            cohort_digest,
        )
    )
    raw_receipt = GraphitiProjectionReconciliationReceipt(
        generation_id=generation_id,
        expected_effect_ids=(),
        actual_effect_ids=(),
        authority_watermark=1,
        receipt_digest="sha256:" + "7" * 64,
    )
    binding = {
        "schema_version": GRAPHITI_ADMISSION_RECONCILIATION_SCHEMA_VERSION,
        "cohort_digest": cohort_digest,
        "ingest_ids": ["proposal-ingest"],
        "raw_receipt": raw_receipt.canonical_value(),
    }
    connection.execute(
        "INSERT INTO unpublished_graphiti_projection_reconciliations("
        "receipt_digest,projector_family_id,generation_id,"
        "authority_watermark,receipt_json,reconciled_at) VALUES(?,?,?,?,?,?)",
        (
            raw_receipt.receipt_digest,
            raw_receipt.projector_family_id,
            raw_receipt.generation_id,
            raw_receipt.authority_watermark,
            canonical_json_bytes(binding).decode("utf-8"),
            "2026-09-01T12:00:00.000000Z",
        ),
    )
    connection.commit()
    connection.close()
    _seed_proving_accountability(proving)
    authority = _authority_store(tmp_path)
    def exact_identity(
        exact_connection: sqlite3.Connection,
        *,
        ingest_ids: tuple[str, ...],
        require_terminal_states: bool,
    ) -> tuple[str, str]:
        assert ingest_ids == ("proposal-ingest",)
        assert require_terminal_states is True
        state = exact_connection.execute(
            "SELECT state FROM unpublished_graphiti_admission_queue "
            "WHERE proposal_key='proposal-1'"
        ).fetchone()[0]
        if state != "TERMINAL":
            raise GraphitiAdmissionConsumerError(
                "exact generation decision integrity differs"
            )
        return cohort_digest, generation_id

    monkeypatch.setattr(
        "newsroom.control_plane.graphiti_steady_state."
        "graphiti_decided_cohort_generation_identity",
        exact_identity,
    )

    mismatched = _bounded_candidate_packet(
        proving,
        unpublished,
        authority,
        monkeypatch,
    )

    assert mismatched["verdict"] == "NO_GO"
    assert mismatched["admission"]["exact_cohort_reconciliation"][
        "latest_generation_id"
    ] == generation_id
    assert "ADMISSION_ACTIVE_GENERATION_DRIFT" in mismatched["blockers"]

    authority_connection = sqlite3.connect(authority)
    authority_connection.execute(
        "UPDATE projection_generations SET generation_id=? WHERE state='ACTIVE'",
        (generation_id,),
    )
    authority_connection.commit()
    authority_connection.close()

    packet = _bounded_candidate_packet(
        proving,
        unpublished,
        authority,
        monkeypatch,
    )

    assert packet["verdict"] == "READY_FOR_OWNER_DECISION"
    assert packet["admission"]["projection_reconciled"] is True
    assert packet["admission"]["exact_cohort_reconciliation"]["total"] is True
    assert packet["admission"]["exact_cohort_reconciliation"]["disjoint"] is True
    assert packet["blockers"] == []
    assert validate_graphiti_campaign_packet(packet) == packet["bounded_campaign"]

    generation_drift = json.loads(json.dumps(packet))
    generation_drift["admission"]["exact_cohort_reconciliation"][
        "latest_generation_id"
    ] = "00000000-0000-4000-8000-000000000895"
    generation_drift["packet_digest"] = digest_canonical(
        {
            key: value
            for key, value in generation_drift.items()
            if key != "packet_digest"
        }
    )
    with pytest.raises(ValueError, match="active generation differs"):
        validate_graphiti_campaign_packet(generation_drift)

    connection = sqlite3.connect(unpublished)
    connection.execute(
        "UPDATE unpublished_graphiti_admission_queue SET state='READY' "
        "WHERE proposal_key='proposal-1'"
    )
    connection.commit()
    connection.close()

    corrupt_state = _bounded_candidate_packet(
        proving,
        unpublished,
        authority,
        monkeypatch,
    )

    assert corrupt_state["admission"]["admission_backlog"] == 0
    assert corrupt_state["admission"]["telemetry_projection_reconciled"] is True
    assert corrupt_state["admission"]["projection_reconciled"] is False
    assert corrupt_state["verdict"] == "NO_GO"
    assert "ADMISSION_PROJECTION_UNRECONCILED" in corrupt_state["blockers"]


def test_untyped_caller_graph_readback_is_no_go(
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
    packet = _packet(
        proving,
        unpublished,
        authority_store=authority,
        campaign_input=_campaign_input(preparation),
        graph_destination_reconciliation={  # type: ignore[arg-type]
            "destination_id": GRAPH_DESTINATION_ID,
            "generation_id": "00000000-0000-4000-8000-000000000895",
            "readback_digest": "sha256:" + "0" * 64,
        },
        governed_runtime=_governed_runtime(preparation),
    )

    assert packet["verdict"] == "NO_GO"
    assert "GRAPH_DESTINATION_READBACK_INVALID" in packet["blockers"]
    assert packet["runtime_composition"]["actual_graph_readback_observed"] is False


def test_runtime_authority_descriptor_drift_is_no_go(
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
    runtime = _governed_runtime(preparation)
    drifted_runtime = _mint_graphiti_campaign_runtime(
        graphiti=runtime.graphiti,
        admission_factory=runtime.admission_factory,
        graph_state_fence=runtime.graph_state_fence,
        graph_destination_id=runtime.graph_destination_id,
        authority_store_source_path=runtime.authority_store_source_path,
        authority_store_descriptor_digest="sha256:" + "0" * 64,
    )

    packet = _packet(
        proving,
        unpublished,
        authority_store=authority,
        campaign_input=_campaign_input(preparation),
        graph_destination_reconciliation=(
            _graph_destination_reconciliation(preparation)
        ),
        governed_runtime=drifted_runtime,
    )

    assert packet["verdict"] == "NO_GO"
    assert "CANONICAL_OPERATOR_RUNTIME_UNCONFIGURED" in packet["blockers"]
    assert packet["runtime_composition"]["authority_store_descriptor_digest"] == (
        "sha256:" + "0" * 64
    )
    assert packet["runtime_composition"]["campaign_packet_enforced"] is False


def test_runtime_graph_destination_drift_is_deterministic_no_go(
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
    campaign["graph"] = {"destination_id": "sha256:" + "8" * 64}

    packet = _packet(
        proving,
        unpublished,
        authority_store=authority,
        campaign_input=campaign,
        graph_destination_reconciliation=(
            _graph_destination_reconciliation(preparation)
        ),
        governed_runtime=_governed_runtime(preparation),
    )

    assert packet["verdict"] == "NO_GO"
    assert "GRAPH_DESTINATION_RUNTIME_BINDING_INVALID" in packet["blockers"]
    assert packet["runtime_composition"]["campaign_packet_enforced"] is False
    assert packet["runtime_composition"]["graph_destination_id"] == (
        GRAPH_DESTINATION_ID
    )


def test_unminted_runtime_instance_cannot_seal_ready_packet(
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
    unminted_runtime = object.__new__(GraphitiCampaignRuntime)
    object.__setattr__(
        unminted_runtime,
        "_GraphitiCampaignRuntime__construction_token",
        object(),
    )

    packet = _packet(
        proving,
        unpublished,
        authority_store=authority,
        campaign_input=_campaign_input(preparation),
        graph_destination_reconciliation=(
            _graph_destination_reconciliation(preparation)
        ),
        governed_runtime=unminted_runtime,
    )

    assert packet["verdict"] == "NO_GO"
    assert "CANONICAL_OPERATOR_RUNTIME_UNCONFIGURED" in packet["blockers"]
    assert packet["runtime_composition"]["state"] == (
        "CANONICAL_OPERATOR_RUNTIME_UNCONFIGURED"
    )
    assert packet["runtime_composition"]["campaign_packet_enforced"] is False


@pytest.mark.parametrize(
    "reconciliation_overrides",
    (
        {"family_id": "graph.different"},
        {"generation_id": "00000000-0000-4000-8000-000000000000"},
        {"checkpoint_ledger_seq": 8},
        {"serving_time": "2026-09-01T13:00:00Z"},
    ),
)
def test_graph_reconciliation_identity_drift_is_no_go(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reconciliation_overrides: dict[str, object],
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
    reconciliation = _graph_destination_reconciliation(
        preparation,
        **reconciliation_overrides,  # type: ignore[arg-type]
    )

    packet = _packet(
        proving,
        unpublished,
        authority_store=authority,
        campaign_input=_campaign_input(preparation),
        graph_destination_reconciliation=reconciliation,
        governed_runtime=_governed_runtime(preparation),
    )

    assert packet["verdict"] == "NO_GO"
    assert "GRAPH_DESTINATION_READBACK_INVALID" in packet["blockers"]


def test_typed_graph_readback_without_operator_runtime_is_no_go(
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
    packet = _packet(
        proving,
        unpublished,
        authority_store=authority,
        campaign_input=_campaign_input(preparation),
        graph_destination_reconciliation=(
            _graph_destination_reconciliation(preparation)
        ),
    )

    assert packet["verdict"] == "NO_GO"
    assert "CANONICAL_OPERATOR_RUNTIME_UNCONFIGURED" in packet["blockers"]
    assert packet["runtime_composition"] == {
        "state": "CANONICAL_OPERATOR_RUNTIME_UNCONFIGURED",
        "authority_store_configured": True,
        "graph_destination_id": None,
        "authority_store_source_path": None,
        "authority_store_descriptor_digest": None,
        "durable_proposal_envelope_binding": False,
        "admission_policy_configured": False,
        "full_generation_projector_configured": False,
        "dormant_worker_path_wired": False,
        "campaign_packet_enforced": False,
        "actual_graph_readback_observed": True,
        "campaign_authorised": False,
    }


def test_campaign_packet_validator_rejects_digest_drift(
    tmp_path: Path,
) -> None:
    proving, unpublished, connection = _stores(tmp_path)
    connection.close()
    packet = _packet(proving, unpublished)
    packet["packet_digest"] = "sha256:" + "0" * 64

    with pytest.raises(ValueError, match="canonical digest differs"):
        validate_graphiti_campaign_packet(packet)


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


def test_historical_proposal_is_verified_only_from_exact_4a_4d_snapshot(
    tmp_path: Path,
) -> None:
    proving, unpublished, connection = _stores(tmp_path)
    _terminal_zero_proposal(connection)
    _turn_terminal_receipt_into_historical_raw_only(connection)
    connection.close()
    authority = _authority_store(tmp_path)
    _bind_terminal_raw_proposal_to_authority(unpublished, authority)

    packet = _packet(proving, unpublished, authority_store=authority)

    assert packet["historical_partition"]["categories"]["VERIFIED_TERMINAL"][
        "ledger_sequences"
    ] == [1]
    assert packet["historical_partition"]["categories"][
        "NON_REPLAYABLE_OR_AMBIGUOUS_EFFECT_HOLD"
    ]["count"] == 0


def test_non_terminal_4d_partial_attempt_is_not_future_admission_authority(
    tmp_path: Path,
) -> None:
    proving, unpublished, connection = _stores(tmp_path)
    _terminal_zero_proposal(connection)
    _turn_terminal_receipt_into_historical_raw_only(connection)
    connection.close()
    authority = _authority_store(tmp_path)
    _bind_terminal_raw_proposal_to_authority(unpublished, authority)
    authority_connection = sqlite3.connect(authority)
    authority_connection.execute(
        "UPDATE graphiti_adapter_attempts SET outcome='PARTIAL'"
    )
    authority_connection.commit()
    authority_connection.close()

    packet = _packet(proving, unpublished, authority_store=authority)

    hold = packet["historical_partition"]["categories"][
        "NON_REPLAYABLE_OR_AMBIGUOUS_EFFECT_HOLD"
    ]
    assert hold["ledger_sequences"] == [1]
    assert hold["reason_counts"] == {
        "IMMUTABLE_RAW_PROPOSAL_WITHOUT_DURABLE_ENVELOPE": 1
    }


def test_internally_valid_raw_output_drift_keeps_historical_proposal_on_hold(
    tmp_path: Path,
) -> None:
    proving, unpublished, connection = _stores(tmp_path)
    _terminal_zero_proposal(connection)
    _turn_terminal_receipt_into_historical_raw_only(connection)
    connection.close()
    authority = _authority_store(tmp_path)
    _bind_terminal_raw_proposal_to_authority(unpublished, authority)
    authority_connection = sqlite3.connect(authority)
    row = authority_connection.execute(
        "SELECT canonical_bytes FROM extraction_outputs WHERE output_id='output'"
    ).fetchone()
    assert row is not None
    raw = json.loads(bytes(row[0]))
    raw.pop("raw_output_digest")
    raw["proposals"][0]["local_id"] = "different-retained-proposal"
    raw["raw_output_digest"] = digest_bytes(canonical_json_bytes(raw))
    raw_bytes = canonical_json_bytes(raw)
    authority_connection.execute(
        "UPDATE extraction_outputs SET canonical_bytes=?,canonical_digest=? "
        "WHERE output_id='output'",
        (raw_bytes, digest_bytes(raw_bytes)),
    )
    authority_connection.commit()
    authority_connection.close()

    packet = _packet(proving, unpublished, authority_store=authority)

    hold = packet["historical_partition"]["categories"][
        "NON_REPLAYABLE_OR_AMBIGUOUS_EFFECT_HOLD"
    ]
    assert hold["ledger_sequences"] == [1]
    assert hold["reason_counts"] == {
        "IMMUTABLE_RAW_PROPOSAL_WITHOUT_DURABLE_ENVELOPE": 1
    }


def test_forged_admission_queue_does_not_create_durable_4a_4d_authority(
    tmp_path: Path,
) -> None:
    proving, unpublished, connection = _stores(tmp_path)
    _terminal_zero_proposal(connection)
    _turn_terminal_receipt_into_historical_raw_only(connection)
    receipt_digest = connection.execute(
        "SELECT receipt_digest FROM unpublished_graphiti_ingest "
        "WHERE ingest_id='ingest-1'"
    ).fetchone()[0]
    forged_request = {
        "proposal_authority_binding": {
            "proposal_envelope": {"local_id": "historical-raw-only"}
        }
    }
    connection.execute(
        "INSERT INTO unpublished_graphiti_admission_queue("
        "proposal_key,ingest_id,source_revision_id,source_receipt_digest,"
        "proposal_digest,proposal_kind,request_json,request_digest,state,"
        "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            "forged-key",
            "ingest-1",
            "revision",
            str(receipt_digest),
            "sha256:" + "1" * 64,
            "ENTITY_MENTION",
            json.dumps(forged_request, sort_keys=True),
            digest_canonical(forged_request),
            "READY",
            NOW.isoformat(),
            NOW.isoformat(),
        ),
    )
    connection.commit()
    connection.close()
    authority = _authority_store(tmp_path)

    packet = _packet(proving, unpublished, authority_store=authority)

    hold = packet["historical_partition"]["categories"][
        "NON_REPLAYABLE_OR_AMBIGUOUS_EFFECT_HOLD"
    ]
    assert hold["reason_counts"] == {
        "IMMUTABLE_RAW_PROPOSAL_WITHOUT_DURABLE_ENVELOPE": 1
    }


def test_arbitrary_migration_checksum_and_owner_supplied_generation_are_no_go(
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
    campaign["graph"]["current_generation_id"] = "self-addressed-generation"
    authority_connection = sqlite3.connect(authority)
    authority_connection.execute(
        "UPDATE authority_migrations SET checksum=? WHERE version=16",
        ("sha256:" + "0" * 64,),
    )
    authority_connection.commit()
    authority_connection.close()

    packet = _packet(
        proving,
        unpublished,
        authority_store=authority,
        campaign_input=campaign,
    )

    assert "AUTHORITY_MIGRATION_HISTORY_INVALID" in packet["blockers"]
    assert "GRAPH_IDENTITY_FIELDS_INVALID" in packet["blockers"]


def test_fallback_stop_and_ramp_contracts_fail_closed(
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
    campaign["caps"]["per_event"]["fallbacks"] = 1
    campaign["immediate_stop_conditions"].remove("EXACT_RECEIPT_DRIFT")
    phase = campaign["ramp"]["phases"][0]
    phase["entry_conditions"] = ["OWNER_F4_GO_RETAINED", "OWNER_F4_GO_RETAINED"]

    packet = _packet(
        proving,
        unpublished,
        authority_store=authority,
        campaign_input=campaign,
    )

    assert "FALLBACK_CAP_MUST_BE_ZERO" in packet["blockers"]
    assert "IMMEDIATE_STOP_CONDITIONS_INCOMPLETE" in packet["blockers"]
    assert "RAMP_PHASE_1_ENTRY_INVALID" in packet["blockers"]


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
