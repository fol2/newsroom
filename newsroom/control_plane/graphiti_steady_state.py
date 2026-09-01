"""Provider-free, read-only Graphiti steady-state evidence packet."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from collections import Counter
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping

from newsroom.authority.canonical import (
    digest_bytes,
    digest_canonical,
    validate_sha256_digest,
)
from newsroom.authority.migrations import MIGRATIONS
from newsroom.control_plane.graphiti_admission import graphiti_admission_telemetry
from newsroom.control_plane.corpus import CorpusIngestUnit
from newsroom.control_plane.cycle import load_graphiti_units_from_connection
from newsroom.control_plane.graphiti_events import (
    GRAPHITI_EVENT_STATES,
    GraphitiRevisionEvent,
    graphiti_unit_binding_reason,
)
from newsroom.control_plane.issue_790_canary import graphiti_excluded_event_ids
from newsroom.control_plane.read_only_snapshot import read_only_snapshot
from newsroom.increment9.proving import (
    PROVING_GATES,
    RIGHTS_GATE_BY_SOURCE,
    SOURCE_IDS,
    SOURCE_URLS,
)
from newsroom.graphiti_adapter.identity import attempt_ids
from newsroom.increment4.contracts import (
    INCREMENT4_ADMITTED_FAMILY_ID,
    INCREMENT4_ADMITTED_MAPPING_ID,
    INCREMENT4_ADMITTED_MAPPING_VERSION,
    INCREMENT4_ADMITTED_ONTOLOGY_ID,
    INCREMENT4_ADMITTED_ONTOLOGY_VERSION,
    INCREMENT4_ADMITTED_PROJECTOR_VERSION,
    increment4_admitted_family_v1,
    increment4_admitted_mapping_v1,
    increment4_admitted_ontology_v1,
)
from newsroom.projection import ProjectionGenerationId

SCHEMA_VERSION = "newsroom.graphiti-steady-state-packet.v3"

CAMPAIGN_SCHEMA_VERSION = "newsroom.graphiti-bounded-campaign-input.v1"

_REQUIRED_STOP_CONDITIONS = frozenset(
    {
        "CAP_REACHED",
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
        "CIRCUIT_OPEN",
        "WALL_TIME_CAP_REACHED",
    }
)

_RAMP_ENTRY_BASE = frozenset(
    {"EXACT_SNAPSHOT_AND_IDENTITY_RECONFIRMED", "OWNER_F4_GO_RETAINED"}
)
_RAMP_ADVANCE_BASE = frozenset(
    {
        "ALL_EXACT_RECEIPTS_RECONCILED",
        "CAPS_AND_ACCOUNTING_RECONCILED",
        "NO_STOP_CONDITION_OBSERVED",
    }
)

HISTORICAL_PARTITION_CATEGORIES = (
    "VERIFIED_TERMINAL",
    "CURRENT_DISPATCH_PREFLIGHT_CANDIDATE",
    "RIGHTS_OR_INPUT_HELD",
    "NON_REPLAYABLE_OR_AMBIGUOUS_EFFECT_HOLD",
    "UNCLASSIFIED",
)


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def _schema_fingerprint(connection: sqlite3.Connection) -> str:
    rows = connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
    ).fetchall()
    return digest_canonical(
        [
            {
                "type": str(row[0]),
                "name": str(row[1]),
                "table": str(row[2]),
                "sql": str(row[3]),
            }
            for row in rows
        ]
    )


def _store_descriptor(snapshot: object) -> dict[str, object]:
    connection = snapshot.connection
    tables = _tables(connection)
    migrations = (
        [
            {"version": int(row[0]), "name": str(row[1]), "checksum": str(row[2])}
            for row in connection.execute(
                "SELECT version,name,checksum FROM authority_migrations ORDER BY version"
            )
        ]
        if "authority_migrations" in tables
        else []
    )
    watermark = (
        int(
            connection.execute(
                "SELECT COALESCE(MAX(ledger_seq),0) FROM ledger_events"
            ).fetchone()[0]
        )
        if "ledger_events" in tables
        else (
            int(connection.execute("SELECT COALESCE(MAX(seq),0) FROM ledger").fetchone()[0])
            if "ledger" in tables
            else 0
        )
    )
    value: dict[str, object] = {
        "source_path": snapshot.source_path,
        "source_files": list(snapshot.source_files),
        "snapshot_files": list(snapshot.snapshot_files),
        "schema_fingerprint": _schema_fingerprint(connection),
        "migration_identity": migrations,
        "watermark": watermark,
    }
    return {**value, "descriptor_digest": digest_canonical(value)}


def _authority_snapshot_evidence(
    connection: sqlite3.Connection,
) -> tuple[dict[str, object], list[str]]:
    tables = _tables(connection)
    required = {
        "authority_migrations",
        "ledger_events",
        "extraction_proposals",
        "graphiti_adapter_attempts",
        "entity_resolution_decisions",
        "editorial_relation_decisions",
        "projection_ontology_contracts",
        "projection_mapping_contracts",
        "projection_family_definitions",
        "projection_families",
        "projection_generations",
    }
    if not required.issubset(tables):
        return {"schema_present": False}, ["AUTHORITY_STORE_SCHEMA_INCOMPLETE"]
    actual_migrations = [
        (int(row[0]), str(row[1]), str(row[2]))
        for row in connection.execute(
            "SELECT version,name,checksum FROM authority_migrations ORDER BY version"
        )
    ]
    expected_migrations = [
        (int(item.version), str(item.name), str(item.checksum)) for item in MIGRATIONS
    ]
    migration_valid = bool(actual_migrations) and actual_migrations == expected_migrations[
        : len(actual_migrations)
    ]
    max_version = max((item[0] for item in actual_migrations), default=0)
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    blockers: list[str] = []
    if not migration_valid or user_version != max_version or max_version < 16:
        blockers.append("AUTHORITY_MIGRATION_HISTORY_INVALID")
    if integrity != "ok":
        blockers.append("AUTHORITY_STORE_INTEGRITY_FAILURE")

    graph_rows = connection.execute(
        "SELECT g.generation_id,g.state,g.validated_through_ledger_seq,"
        "g.family_id,d.projector_version,o.ontology_id,o.ontology_version,"
        "m.mapping_id,m.mapping_version,o.contract_digest,m.contract_digest,"
        "d.definition_digest FROM projection_generations AS g "
        "JOIN projection_families AS f ON f.family_id=g.family_id "
        "JOIN projection_family_definitions AS d "
        "ON d.definition_digest=f.definition_digest "
        "JOIN projection_ontology_contracts AS o "
        "ON o.contract_digest=d.ontology_contract_digest "
        "JOIN projection_mapping_contracts AS m "
        "ON m.contract_digest=d.mapping_contract_digest "
        "WHERE g.family_id=? AND g.state='ACTIVE'",
        (INCREMENT4_ADMITTED_FAMILY_ID,),
    ).fetchall()
    graph_readback: dict[str, object] | None = None
    if len(graph_rows) != 1:
        blockers.append("ACTIVE_GRAPH_GENERATION_READBACK_INVALID")
    else:
        row = graph_rows[0]
        validated_through = row[2]
        if (
            isinstance(validated_through, bool)
            or not isinstance(validated_through, int)
            or validated_through < 0
        ):
            blockers.append("ACTIVE_GRAPH_WATERMARK_INVALID")
            validated_through = -1
        graph_readback = {
            "generation_id": str(row[0]),
            "state": str(row[1]),
            "validated_through_ledger_seq": validated_through,
            "family_id": str(row[3]),
            "projector_version": str(row[4]),
            "ontology_id": str(row[5]),
            "ontology_version": str(row[6]),
            "mapping_id": str(row[7]),
            "mapping_version": str(row[8]),
            "ontology_contract_digest": str(row[9]),
            "mapping_contract_digest": str(row[10]),
            "family_definition_digest": str(row[11]),
        }
        expected_graph = {
            "family_id": INCREMENT4_ADMITTED_FAMILY_ID,
            "projector_version": INCREMENT4_ADMITTED_PROJECTOR_VERSION,
            "ontology_id": INCREMENT4_ADMITTED_ONTOLOGY_ID,
            "ontology_version": INCREMENT4_ADMITTED_ONTOLOGY_VERSION,
            "mapping_id": INCREMENT4_ADMITTED_MAPPING_ID,
            "mapping_version": INCREMENT4_ADMITTED_MAPPING_VERSION,
        }
        if any(graph_readback.get(key) != value for key, value in expected_graph.items()):
            blockers.append("ACTIVE_GRAPH_IDENTITY_INVALID")
        ontology = increment4_admitted_ontology_v1()
        mapping = increment4_admitted_mapping_v1(ontology)
        family = increment4_admitted_family_v1(ontology, mapping)
        if (
            graph_readback["ontology_contract_digest"] != ontology.contract_digest
            or graph_readback["mapping_contract_digest"] != mapping.contract_digest
            or graph_readback["family_definition_digest"] != family.digest
        ):
            blockers.append("ACTIVE_GRAPH_CONTRACT_DIGEST_INVALID")
        try:
            ProjectionGenerationId.parse(str(graph_readback["generation_id"]))
        except (TypeError, ValueError):
            blockers.append("ACTIVE_GRAPH_GENERATION_ID_INVALID")
        if (
            graph_readback["validated_through_ledger_seq"] < 0
            or graph_readback["validated_through_ledger_seq"]
            > int(
                connection.execute(
                    "SELECT COALESCE(MAX(ledger_seq),0) FROM ledger_events"
                ).fetchone()[0]
            )
        ):
            blockers.append("ACTIVE_GRAPH_WATERMARK_INVALID")
        for field in (
            "ontology_contract_digest",
            "mapping_contract_digest",
            "family_definition_digest",
        ):
            try:
                validate_sha256_digest(graph_readback[field], field=field)
            except (TypeError, ValueError):
                blockers.append("ACTIVE_GRAPH_CONTRACT_DIGEST_INVALID")
                break
    value = {
        "schema_present": True,
        "migration_history_digest": digest_canonical(actual_migrations),
        "migration_history_valid": migration_valid,
        "user_version": user_version,
        "watermark": int(
            connection.execute(
                "SELECT COALESCE(MAX(ledger_seq),0) FROM ledger_events"
            ).fetchone()[0]
        ),
        "integrity_check": integrity,
        "active_projection_authority": graph_readback,
    }
    return value, blockers


def _has_exact_durable_proposal_authority(
    authority: sqlite3.Connection | None,
    unpublished: sqlite3.Connection,
    ingest_ids: tuple[str, ...],
) -> bool:
    retained_rows = [
        unpublished.execute(
            "SELECT ingest.proposal_count,receipt.receipt_json "
            "FROM unpublished_graphiti_ingest AS ingest "
            "JOIN unpublished_graphiti_receipts AS receipt USING(ingest_id) "
            "WHERE ingest.ingest_id=?",
            (ingest_id,),
        ).fetchone()
        for ingest_id in ingest_ids
    ]
    if any(row is None for row in retained_rows):
        return False
    if all(int(row[0]) == 0 for row in retained_rows if row is not None):
        return True
    if authority is None:
        return False
    authority_tables = _tables(authority)
    if not {"graphiti_adapter_attempts", "extraction_proposals"}.issubset(
        authority_tables
    ):
        return False
    for ingest_id, retained in zip(ingest_ids, retained_rows, strict=True):
        assert retained is not None
        proposal_count = int(retained[0])
        if proposal_count == 0:
            continue
        try:
            receipt = json.loads(str(retained[1]))
            attempt_number = receipt["attempt_number"]
            proposals = receipt["proposals"]
            if (
                isinstance(attempt_number, bool)
                or not isinstance(attempt_number, int)
                or attempt_number <= 0
                or not isinstance(proposals, list)
                or len(proposals) != proposal_count
            ):
                return False
            attempt_id = str(attempt_ids(ingest_id, attempt_number)[0])
            attempt = authority.execute(
                "SELECT outcome,proposal_count,proposal_set_id,extraction_output_id,"
                "run_id,run_version_id FROM graphiti_adapter_attempts "
                "WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if (
                attempt is None
                or str(attempt[0]) not in {"COMPLETE", "PARTIAL"}
                or int(attempt[1]) != proposal_count
                or attempt[2] is None
                or attempt[3] is None
            ):
                return False
            envelopes = authority.execute(
                "SELECT local_id,semantic_digest,output_id,run_id,run_version_id "
                "FROM extraction_proposals WHERE proposal_set_id=? "
                "ORDER BY local_id",
                (str(attempt[2]),),
            ).fetchall()
            raw_by_local_id = {
                str(item["local_id"]): digest_canonical(item)
                for item in proposals
                if isinstance(item, Mapping) and isinstance(item.get("local_id"), str)
            }
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, sqlite3.Error):
            return False
        if len(raw_by_local_id) != proposal_count or len(envelopes) != proposal_count:
            return False
        if any(
            raw_by_local_id.get(str(row[0])) != str(row[1])
            or str(row[2]) != str(attempt[3])
            or str(row[3]) != str(attempt[4])
            or str(row[4]) != str(attempt[5])
            for row in envelopes
        ):
            return False
    return True


def _proving_accounting(
    connection: sqlite3.Connection,
) -> tuple[dict[str, object], list[str]]:
    required = {
        "proving_runs",
        "proving_gates",
        "proving_observations",
        "proving_source_health",
    }
    if not required.issubset(_tables(connection)):
        return {"schema_present": False}, ["PROVING_ACCOUNTABILITY_SCHEMA_MISSING"]
    run = connection.execute(
        "SELECT run_id,started_at,publication,public_dispatch,openrouter_invoked,"
        "spend_gbp_minor FROM proving_runs ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    if run is None:
        return {"schema_present": True, "latest_run_id": None}, [
            "PROVING_RUN_MISSING"
        ]
    run_id = str(run[0])
    gate_rows = connection.execute(
        "SELECT gate_id,status FROM proving_gates WHERE run_id=? ORDER BY gate_id",
        (run_id,),
    ).fetchall()
    gate_statuses = {str(gate_id): str(status) for gate_id, status in gate_rows}
    source_rows = connection.execute(
        "SELECT source_id,status,endpoint,reason FROM proving_source_health "
        "WHERE run_id=? ORDER BY source_id",
        (run_id,),
    ).fetchall()
    retained_source_ids = {str(row[0]) for row in source_rows}
    missing_source_ids = sorted(set(SOURCE_IDS) - retained_source_ids)
    unexpected_source_ids = sorted(retained_source_ids - set(SOURCE_IDS))
    sources: list[dict[str, object]] = []
    unaccounted: list[str] = []
    successful = held = 0
    for source_id, status, endpoint, reason in source_rows:
        source_id = str(source_id)
        status = str(status)
        endpoint = str(endpoint)
        observation = connection.execute(
            "SELECT fetched_at,url,status_code,body_digest,item_count,error,body "
            "FROM proving_observations WHERE run_id=? AND source_id=? "
            "ORDER BY fetched_at DESC LIMIT 1",
            (run_id, source_id),
        ).fetchone()
        expected_endpoint = SOURCE_URLS.get(source_id)
        body_digest_valid = bool(
            observation is not None
            and isinstance(observation[6], bytes)
            and digest_bytes(observation[6]) == str(observation[3])
        )
        rights_gate_status = gate_statuses.get(
            RIGHTS_GATE_BY_SOURCE.get(source_id, "")
        )
        observation_success = bool(
            status == "ACTIVE"
            and observation is not None
            and int(observation[2]) == 200
            and observation[5] is None
            and str(observation[1]) == endpoint
            and endpoint == expected_endpoint
            and body_digest_valid
            and rights_gate_status == "PASS"
        )
        typed_hold = bool(
            status in {"DEGRADED", "HELD", "BLOCKED"}
            and reason
            and endpoint == expected_endpoint
        )
        if observation_success:
            successful += 1
        elif typed_hold:
            held += 1
        else:
            unaccounted.append(source_id)
        sources.append(
            {
                "source_id": source_id,
                "status": status,
                "endpoint": endpoint,
                "reason": None if reason is None else str(reason),
                "observation_success": observation_success,
                "typed_hold": typed_hold,
                "rights_gate_status": rights_gate_status,
                "observed_at": None if observation is None else str(observation[0]),
                "body_digest": None if observation is None else str(observation[3]),
                "body_digest_valid": body_digest_valid,
                "item_count": None if observation is None else int(observation[4]),
            }
        )
    missing_gate_ids = sorted(set(PROVING_GATES) - set(gate_statuses))
    non_pass_gates = sorted(
        gate_id for gate_id, status in gate_statuses.items() if status != "PASS"
    )
    external_effects = {
        "publication": int(run[2]),
        "public_dispatch": int(run[3]),
        "openrouter_invoked": int(run[4]),
        "spend_gbp_minor": int(run[5]),
    }
    blockers: list[str] = []
    if missing_source_ids or unexpected_source_ids:
        blockers.append("PROVING_SOURCE_MANIFEST_DIFFERS")
    if unaccounted:
        blockers.append("PROVING_SOURCE_UNACCOUNTED")
    if missing_gate_ids:
        blockers.append("PROVING_GATE_MISSING")
    if non_pass_gates:
        blockers.append("PROVING_GATE_NOT_PASS")
    if any(external_effects.values()):
        blockers.append("PROVING_RUN_EXTERNAL_EFFECT_PRESENT")
    return {
        "schema_present": True,
        "latest_run_id": run_id,
        "started_at": str(run[1]),
        "source_count": len(source_rows),
        "expected_source_ids": list(SOURCE_IDS),
        "source_manifest_digest": digest_canonical(
            {
                "source_ids": list(SOURCE_IDS),
                "source_urls": SOURCE_URLS,
            }
        ),
        "missing_source_ids": missing_source_ids,
        "unexpected_source_ids": unexpected_source_ids,
        "successful_observation_count": successful,
        "typed_hold_count": held,
        "unaccounted_source_ids": unaccounted,
        "sources": sources,
        "gate_status_counts": dict(sorted(Counter(gate_statuses.values()).items())),
        "missing_gate_ids": missing_gate_ids,
        "non_pass_gate_ids": non_pass_gates,
        "external_effects": external_effects,
    }, blockers


def _event_accounting(
    connection: sqlite3.Connection,
) -> tuple[dict[str, object], list[str]]:
    blockers: list[str] = []
    required = {
        "unpublished_effective_revision_landed",
        "unpublished_graphiti_revision_events",
    }
    if not required.issubset(_tables(connection)):
        return {
            "landed_revision_count": 0,
            "event_count": 0,
            "missing_event_ledger_sequences": [],
            "orphan_event_ledger_sequences": [],
            "one_to_one": False,
        }, ["EVENT_ACCOUNTING_SCHEMA_MISSING"]
    landed = {
        int(row[0]): str(row[1])
        for row in connection.execute(
            "SELECT ledger.seq, landed.ledger_digest "
            "FROM unpublished_effective_revision_landed AS landed "
            "JOIN ledger ON ledger.digest=landed.ledger_digest "
            "WHERE NOT (landed.legacy_v10=1 AND EXISTS ("
            "SELECT 1 FROM unpublished_effective_revision_landed AS marker "
            "WHERE marker.legacy_v10=0 "
            "AND marker.source_id=landed.source_id "
            "AND marker.item_key=landed.item_key "
            "AND marker.revision_digest=landed.revision_digest "
            "AND marker.first_observed_at=landed.first_observed_at "
            "AND (marker.published_at<>'' OR marker.updated_at<>'')))"
        )
    }
    events = {
        int(row[0]): str(row[1])
        for row in connection.execute(
            "SELECT ledger_seq, ledger_digest FROM unpublished_graphiti_revision_events"
        )
    }
    missing = sorted(set(landed) - set(events))
    orphan = sorted(set(events) - set(landed))
    contradictions = sorted(
        seq
        for seq in set(landed) & set(events)
        if landed[seq] != events[seq]
    )
    if missing:
        blockers.append("LANDED_REVISION_EVENT_MISSING")
    if orphan:
        blockers.append("GRAPHITI_EVENT_ORPHANED")
    if contradictions:
        blockers.append("LANDED_EVENT_IDENTITY_CONTRADICTION")
    return {
        "landed_revision_count": len(landed),
        "event_count": len(events),
        "missing_event_ledger_sequences": missing,
        "orphan_event_ledger_sequences": orphan,
        "contradictory_ledger_sequences": contradictions,
        "one_to_one": not (missing or orphan or contradictions),
    }, blockers


def _events_and_receipts(
    connection: sqlite3.Connection,
) -> tuple[dict[str, object], dict[str, object], list[str]]:
    blockers: list[str] = []
    tables = _tables(connection)
    required = {
        "unpublished_graphiti_revision_events",
        "unpublished_graphiti_ingest",
        "unpublished_graphiti_receipts",
        "unpublished_graphiti_attempt_receipts",
    }
    if not required.issubset(tables):
        return (
            {"state_counts": {}, "integrity_failures": []},
            {"terminal_ingest_count": 0, "integrity_failures": []},
            ["TERMINAL_RECEIPT_SCHEMA_MISSING"],
        )
    rows = connection.execute(
        "SELECT event_id,ledger_seq,ledger_digest,state,proposal_count,unit_count,"
        "manifest_json,manifest_digest "
        "FROM unpublished_graphiti_revision_events ORDER BY ledger_seq"
    ).fetchall()
    states = Counter(str(row[3]) for row in rows)
    unknown = sorted(set(states) - set(GRAPHITI_EVENT_STATES))
    if unknown:
        blockers.append("UNKNOWN_EVENT_STATE")
    event_failures: list[dict[str, str]] = []
    receipt_failures: list[dict[str, str]] = []
    terminal_ingests: set[str] = set()
    zero_proposal = 0
    for (
        event_id,
        ledger_seq,
        ledger_digest,
        state,
        event_proposals,
        unit_count,
        manifest_json,
        manifest_digest,
    ) in rows:
        try:
            manifest = json.loads(str(manifest_json))
            unit_refs = manifest.get("unit_refs")
            landed_ingest_ids = manifest.get("landed_ingest_ids")
            if (
                not isinstance(manifest, dict)
                or digest_canonical(manifest) != str(manifest_digest)
                or manifest.get("ledger_seq") != int(ledger_seq)
                or manifest.get("ledger_digest") != str(ledger_digest)
                or str(event_id) != str(ledger_digest)
                or not isinstance(unit_refs, list)
                or not all(isinstance(item, dict) for item in unit_refs)
                or not isinstance(landed_ingest_ids, list)
                or not all(isinstance(item, str) for item in landed_ingest_ids)
            ):
                raise ValueError
            ingest_ids = [item.get("ingest_id") for item in unit_refs]
            if (
                len(unit_refs) != int(unit_count)
                or not all(isinstance(item, str) and item for item in ingest_ids)
                or len(set(ingest_ids)) != len(ingest_ids)
                or len(set(landed_ingest_ids)) != len(landed_ingest_ids)
                or (
                    landed_ingest_ids
                    and ingest_ids
                    and tuple(ingest_ids) != tuple(landed_ingest_ids)
                )
            ):
                raise ValueError
        except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
            event_failures.append(
                {"event_id": str(event_id), "reason": "MALFORMED_EVENT_MANIFEST"}
            )
            continue
        if state != "TERMINAL":
            continue
        if not ingest_ids:
            event_failures.append(
                {
                    "event_id": str(event_id),
                    "reason": "TERMINAL_EVENT_HAS_NO_RESOLVED_UNITS",
                }
            )
            continue
        proposal_sum = 0
        for ingest_id in ingest_ids:
            assert isinstance(ingest_id, str)
            if ingest_id in terminal_ingests:
                receipt_failures.append(
                    {
                        "ingest_id": ingest_id,
                        "reason": "INGEST_BOUND_TO_MULTIPLE_TERMINAL_EVENTS",
                    }
                )
            terminal_ingests.add(ingest_id)
            row = connection.execute(
                "SELECT ingest.outcome,ingest.proposal_count,ingest.entity_count,"
                "ingest.relation_count,ingest.receipt_digest,receipt.receipt_json,"
                "attempt.receipt_digest,attempt.receipt_json "
                "FROM unpublished_graphiti_ingest "
                "AS ingest LEFT JOIN unpublished_graphiti_receipts AS receipt "
                "USING(ingest_id) LEFT JOIN unpublished_graphiti_attempt_receipts "
                "AS attempt ON attempt.ingest_id=ingest.ingest_id "
                "AND attempt.receipt_digest=ingest.receipt_digest "
                "WHERE ingest.ingest_id=?",
                (ingest_id,),
            ).fetchone()
            if row is None or row[0] not in {"COMPLETE", "PARTIAL"} or row[5] is None:
                receipt_failures.append(
                    {
                        "ingest_id": ingest_id,
                        "reason": "TERMINAL_INGEST_OR_RECEIPT_MISSING",
                    }
                )
                continue
            try:
                receipt = json.loads(str(row[5]))
            except json.JSONDecodeError:
                receipt_failures.append(
                    {"ingest_id": ingest_id, "reason": "RECEIPT_JSON_INVALID"}
                )
                continue
            proposal_sum += int(row[1])
            proposals = receipt.get("proposals") if isinstance(receipt, dict) else None
            if not isinstance(proposals, list) or len(proposals) != int(row[1]):
                receipt_failures.append(
                    {
                        "ingest_id": ingest_id,
                        "reason": "RECEIPT_PROPOSAL_COUNT_CONTRADICTION",
                    }
                )
                continue
            unsigned_receipt = dict(receipt)
            supplied_digest = unsigned_receipt.pop("receipt_digest", None)
            if (
                supplied_digest != str(row[4])
                or digest_canonical(unsigned_receipt) != str(row[4])
            ):
                receipt_failures.append(
                    {
                        "ingest_id": ingest_id,
                        "reason": "RECEIPT_ENVELOPE_DIGEST_CONTRADICTION",
                    }
                )
                continue
            if row[6] != row[4] or row[7] != row[5]:
                receipt_failures.append(
                    {
                        "ingest_id": ingest_id,
                        "reason": "ATTEMPT_RECEIPT_COPY_CONTRADICTION",
                    }
                )
                continue
            raw_digest = receipt.get("raw_output_digest")
            try:
                validate_sha256_digest(
                    raw_digest,
                    field="Graphiti receipt raw output digest",
                )
            except (TypeError, ValueError):
                receipt_failures.append(
                    {
                        "ingest_id": ingest_id,
                        "reason": "RAW_OUTPUT_DIGEST_INVALID",
                    }
                )
                continue
            if (
                receipt.get("ingest_id") != ingest_id
                or receipt.get("outcome") != row[0]
                or receipt.get("proposal_count") != int(row[1])
                or receipt.get("entity_count") != int(row[2])
                or receipt.get("relation_count") != int(row[3])
            ):
                receipt_failures.append(
                    {
                        "ingest_id": ingest_id,
                        "reason": "RECEIPT_INGEST_BINDING_CONTRADICTION",
                    }
                )
                continue
            if int(row[1]) == 0:
                zero_proposal += 1
        if event_proposals is None or int(event_proposals) != proposal_sum:
            receipt_failures.append(
                {
                    "event_id": str(event_id),
                    "reason": "EVENT_PROPOSAL_COUNT_CONTRADICTION",
                }
            )
    nonterminal = sum(count for state, count in states.items() if state != "TERMINAL")
    if event_failures:
        blockers.append("EVENT_MANIFEST_INTEGRITY_FAILURE")
    if receipt_failures:
        blockers.append("TERMINAL_RECEIPT_INTEGRITY_FAILURE")
    return {
        "state_counts": {
            key: states.get(key, 0) for key in sorted(GRAPHITI_EVENT_STATES)
        },
        "terminal_event_count": states.get("TERMINAL", 0),
        "nonterminal_event_count": nonterminal,
        "integrity_failures": event_failures,
    }, {
        "terminal_ingest_count": len(terminal_ingests),
        "zero_proposal_success_count": zero_proposal,
        "zero_proposal_is_success": True,
        "integrity_failures": receipt_failures,
    }, blockers


def _historical_partition(
    proving: sqlite3.Connection,
    unpublished: sqlite3.Connection,
    *,
    authority: sqlite3.Connection | None,
    observed_at: datetime,
    event_evidence: Mapping[str, object],
    receipt_evidence: Mapping[str, object],
) -> tuple[dict[str, object], list[str]]:
    """Partition every effective landed revision without provider effects."""

    required = {
        "ledger",
        "unpublished_effective_revision_landed",
        "unpublished_graphiti_revision_events",
    }
    if not required.issubset(_tables(unpublished)):
        return {
            "universe_count": 0,
            "partitioned_count": 0,
            "disjoint": False,
            "total": False,
            "categories": {},
        }, ["HISTORICAL_PARTITION_SCHEMA_MISSING"]

    landed_rows = unpublished.execute(
        "SELECT ledger.seq,ledger.digest,landed.source_id,landed.item_key,"
        "landed.revision_digest,landed.published_at,landed.updated_at "
        "FROM unpublished_effective_revision_landed AS landed "
        "JOIN ledger ON ledger.digest=landed.ledger_digest "
        "WHERE NOT (landed.legacy_v10=1 AND EXISTS ("
        "SELECT 1 FROM unpublished_effective_revision_landed AS marker "
        "WHERE marker.legacy_v10=0 "
        "AND marker.source_id=landed.source_id "
        "AND marker.item_key=landed.item_key "
        "AND marker.revision_digest=landed.revision_digest "
        "AND marker.first_observed_at=landed.first_observed_at "
        "AND (marker.published_at<>'' OR marker.updated_at<>''))) "
        "ORDER BY ledger.seq"
    ).fetchall()
    event_rows = unpublished.execute(
        "SELECT event_id,ledger_seq,ledger_digest,source_id,item_key,"
        "revision_digest,published_at,updated_at,unit_count,manifest_json,"
        "manifest_digest,state,attempt_count,available_at,claim_owner,"
        "claim_expires_at,provider_dispatched "
        "FROM unpublished_graphiti_revision_events ORDER BY ledger_seq"
    ).fetchall()
    events_by_ledger = {int(row[1]): row for row in event_rows}
    terminal_receipt_schema_present = {
        "unpublished_graphiti_ingest",
        "unpublished_graphiti_receipts",
        "unpublished_graphiti_attempt_receipts",
    }.issubset(_tables(unpublished))

    event_integrity_failures = {
        str(item.get("event_id"))
        for item in event_evidence.get("integrity_failures", [])
        if isinstance(item, Mapping) and item.get("event_id") is not None
    }
    receipt_integrity_failures = {
        str(item.get(key))
        for item in receipt_evidence.get("integrity_failures", [])
        if isinstance(item, Mapping)
        for key in ("event_id", "ingest_id")
        if item.get(key) is not None
    }

    unit_resolution_available = True
    try:
        units = load_graphiti_units_from_connection(
            proving,
            evaluated_at=observed_at,
        )
    except (sqlite3.Error, ValueError):
        units = ()
        unit_resolution_available = False
    units_by_revision: dict[
        tuple[str, str, str, str, str], list[CorpusIngestUnit]
    ] = {}
    for unit in units:
        key = (
            unit.source_id,
            unit.item_key,
            unit.revision_digest,
            unit.published_at or "",
            unit.updated_at or "",
        )
        units_by_revision.setdefault(key, []).append(unit)

    excluded_event_ids = graphiti_excluded_event_ids(unpublished)

    assignments: dict[str, list[int]] = {
        category: [] for category in HISTORICAL_PARTITION_CATEGORIES
    }
    reason_counts: dict[str, Counter[str]] = {
        category: Counter() for category in HISTORICAL_PARTITION_CATEGORIES
    }
    candidate_events: list[dict[str, object]] = []
    now_text = observed_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    for landed in landed_rows:
        ledger_seq = int(landed[0])
        ledger_digest = str(landed[1])
        event_row = events_by_ledger.get(ledger_seq)
        category: str
        reason: str
        if event_row is None:
            category = "RIGHTS_OR_INPUT_HELD"
            reason = "EVENT_PROJECTION_MISSING"
        else:
            event_id = str(event_row[0])
            try:
                manifest = json.loads(str(event_row[9]))
                unit_refs = manifest.get("unit_refs")
                landed_ingest_ids = manifest.get("landed_ingest_ids")
                if (
                    not isinstance(manifest, dict)
                    or digest_canonical(manifest) != str(event_row[10])
                    or event_id != ledger_digest
                    or str(event_row[2]) != ledger_digest
                    or tuple(str(value) for value in event_row[3:8])
                    != tuple(str(value) for value in landed[2:7])
                    or manifest.get("ledger_seq") != ledger_seq
                    or manifest.get("ledger_digest") != ledger_digest
                    or not isinstance(unit_refs, list)
                    or not all(isinstance(item, dict) for item in unit_refs)
                    or not isinstance(landed_ingest_ids, list)
                    or not all(isinstance(item, str) for item in landed_ingest_ids)
                ):
                    raise ValueError
                resolved_ingest_ids = tuple(
                    item.get("ingest_id") for item in unit_refs
                )
                if (
                    len(unit_refs) != int(event_row[8])
                    or not all(
                        isinstance(item, str) and item
                        for item in resolved_ingest_ids
                    )
                    or len(set(resolved_ingest_ids)) != len(resolved_ingest_ids)
                    or len(set(landed_ingest_ids)) != len(landed_ingest_ids)
                    or (
                        resolved_ingest_ids
                        and landed_ingest_ids
                        and resolved_ingest_ids != tuple(landed_ingest_ids)
                    )
                ):
                    raise ValueError
            except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
                category = "UNCLASSIFIED"
                reason = "EVENT_MANIFEST_UNVERIFIED"
            else:
                state = str(event_row[11])
                if state == "TERMINAL":
                    terminal_integrity_keys = {event_id, *resolved_ingest_ids}
                    if not terminal_receipt_schema_present:
                        category = "UNCLASSIFIED"
                        reason = "TERMINAL_RECEIPT_SCHEMA_UNAVAILABLE"
                    elif event_id in event_integrity_failures or (
                        terminal_integrity_keys & receipt_integrity_failures
                    ):
                        category = "UNCLASSIFIED"
                        reason = "TERMINAL_OUTCOME_UNVERIFIED"
                    elif not _has_exact_durable_proposal_authority(
                        authority,
                        unpublished,
                        tuple(str(item) for item in resolved_ingest_ids),
                    ):
                        category = "NON_REPLAYABLE_OR_AMBIGUOUS_EFFECT_HOLD"
                        reason = "IMMUTABLE_RAW_PROPOSAL_WITHOUT_DURABLE_ENVELOPE"
                    else:
                        category = "VERIFIED_TERMINAL"
                        reason = "TERMINAL_EVENT_AND_RECEIPTS_VERIFIED"
                elif state not in GRAPHITI_EVENT_STATES:
                    category = "UNCLASSIFIED"
                    reason = "EVENT_STATE_UNRECOGNISED"
                elif (
                    event_id in excluded_event_ids
                    or bool(event_row[16])
                    or state in {"CONFIGURATION_HELD", "DEAD_LETTER"}
                ):
                    category = "NON_REPLAYABLE_OR_AMBIGUOUS_EFFECT_HOLD"
                    reason = "EVENT_HISTORY_OR_EFFECT_REQUIRES_ADJUDICATION"
                elif (
                    state != "QUEUED"
                    or int(event_row[12]) != 0
                    or str(event_row[13]) > now_text
                    or event_row[14] is not None
                    or event_row[15] is not None
                ):
                    category = "RIGHTS_OR_INPUT_HELD"
                    reason = "EVENT_NOT_FRESH_AND_CLAIMABLE"
                else:
                    event = GraphitiRevisionEvent(
                        event_id=event_id,
                        ledger_seq=ledger_seq,
                        source_id=str(event_row[3]),
                        item_key=str(event_row[4]),
                        revision_digest=str(event_row[5]),
                        published_at=str(event_row[6]),
                        updated_at=str(event_row[7]),
                        expected_unit_count=int(event_row[8]),
                        landed_ingest_ids=tuple(landed_ingest_ids),
                        landed_payload_digest=str(
                            manifest.get("landed_payload_digest") or ""
                        ),
                        unit_refs=tuple(unit_refs),
                        state=state,
                        attempt_count=int(event_row[12]),
                        units=(),
                    )
                    revision_key = (
                        event.source_id,
                        event.item_key,
                        event.revision_digest,
                        event.published_at,
                        event.updated_at,
                    )
                    current_units = tuple(units_by_revision.get(revision_key, ()))
                    binding_reason = graphiti_unit_binding_reason(
                        event,
                        current_units,
                    )
                    if binding_reason is None:
                        category = "CURRENT_DISPATCH_PREFLIGHT_CANDIDATE"
                        reason = "CURRENT_RIGHTS_INPUT_AND_BINDING_VERIFIED"
                        candidate_events.append(
                            {
                                "event_id": event_id,
                                "ledger_seq": ledger_seq,
                                "manifest_digest": str(event_row[10]),
                                "ingest_ids": list(resolved_ingest_ids),
                            }
                        )
                    else:
                        category = "RIGHTS_OR_INPUT_HELD"
                        reason = binding_reason
        assignments[category].append(ledger_seq)
        reason_counts[category][reason] += 1

    all_sequences = [seq for values in assignments.values() for seq in values]
    disjoint = len(all_sequences) == len(set(all_sequences))
    universe_sequences = [int(row[0]) for row in landed_rows]
    total = sorted(all_sequences) == sorted(universe_sequences)
    categories = {
        category: {
            "count": len(assignments[category]),
            "ledger_sequences": assignments[category],
            "reason_counts": dict(sorted(reason_counts[category].items())),
            **(
                {"dispatch_authorised": False}
                if category == "CURRENT_DISPATCH_PREFLIGHT_CANDIDATE"
                else {}
            ),
        }
        for category in HISTORICAL_PARTITION_CATEGORIES
    }
    evidence_without_digest: dict[str, object] = {
        "universe": "LEGACY_FILTERED_EFFECTIVE_REVISION_LANDED",
        "universe_count": len(universe_sequences),
        "partitioned_count": len(all_sequences),
        "disjoint": disjoint,
        "total": total,
        "categories": categories,
        "current_preflight_candidates": candidate_events,
        "current_preflight_candidate_manifest_digest": digest_canonical(
            candidate_events
        ),
    }
    blockers: list[str] = []
    if not unit_resolution_available:
        blockers.append("CURRENT_RIGHTS_INPUT_RESOLUTION_UNAVAILABLE")
    if not disjoint or not total:
        blockers.append("HISTORICAL_PARTITION_NOT_TOTAL_AND_DISJOINT")
    if assignments["UNCLASSIFIED"]:
        blockers.append("HISTORICAL_OBLIGATION_UNCLASSIFIED")
    return {
        **evidence_without_digest,
        "partition_digest": digest_canonical(evidence_without_digest),
    }, blockers


def _admission(
    connection: sqlite3.Connection, *, observed_at: datetime
) -> tuple[dict[str, object], list[str]]:
    required = {
        "unpublished_graphiti_ingest",
        "unpublished_graphiti_admission_queue",
        "unpublished_graphiti_admission_decisions",
        "unpublished_graphiti_projection_receipts",
        "unpublished_graphiti_projection_tombstones",
        "unpublished_graphiti_projection_reconciliations",
        "unpublished_graphiti_admission_receipt_failures",
    }
    if not required.issubset(_tables(connection)):
        return {"schema_present": False}, ["ADMISSION_TELEMETRY_SCHEMA_MISSING"]
    value = graphiti_admission_telemetry(
        connection, now=observed_at
    ).canonical_value()
    value["schema_present"] = True
    blockers = []
    if value["dead_letter_count"]:
        blockers.append("ADMISSION_DEAD_LETTER_PRESENT")
    if value["integrity_hold_receipt_count"]:
        blockers.append("ADMISSION_INTEGRITY_HOLD_PRESENT")
    if value["admitted_count"] and not value["projection_reconciled"]:
        blockers.append("ADMISSION_PROJECTION_UNRECONCILED")
    return value, blockers


def _spend(connection: sqlite3.Connection) -> tuple[dict[str, object], list[str]]:
    if "unpublished_graphiti_spend" not in _tables(connection):
        return {"schema_present": False}, ["GRAPHITI_SPEND_SCHEMA_MISSING"]
    rows = connection.execute(
        "SELECT status,COUNT(*),COALESCE(SUM(reserved_gbp_microunits),0),"
        "COALESCE(SUM(actual_gbp_microunits),0),"
        "COALESCE(SUM(actual_usd_microunits),0),"
        "SUM(CASE WHEN provider_usage_json IS NOT NULL THEN 1 ELSE 0 END) "
        "FROM unpublished_graphiti_spend GROUP BY status"
    ).fetchall()
    counts = {str(row[0]): int(row[1]) for row in rows}
    unreconciled = counts.get("UNRECONCILED", 0) + counts.get("RESERVED", 0)
    return {
        "schema_present": True,
        "status_counts": {
            key: counts.get(key, 0)
            for key in ("RECONCILED", "RESERVED", "UNRECONCILED")
        },
        "reserved_gbp_microunits": sum(
            int(row[2])
            for row in rows
            if row[0] in {"RESERVED", "UNRECONCILED"}
        ),
        "actual_gbp_microunits": sum(
            int(row[3]) for row in rows if row[0] == "RECONCILED"
        ),
        "actual_usd_microunits": sum(
            int(row[4]) for row in rows if row[0] == "RECONCILED"
        ),
        "provider_usage_record_count": sum(int(row[5]) for row in rows),
        "unreconciled_attempt_count": unreconciled,
    }, (["GRAPHITI_SPEND_UNRECONCILED"] if unreconciled else [])


def _campaign_evidence(
    campaign: Mapping[str, object] | None,
    *,
    head_sha: str,
    tree_sha: str,
    store_descriptors: Mapping[str, Mapping[str, object]],
    historical_partition: Mapping[str, object],
    authority_evidence: Mapping[str, object],
) -> tuple[dict[str, object], list[str]]:
    if campaign is None:
        return {"configured": False, "campaign_authorised": False}, [
            "CAMPAIGN_INPUT_MISSING"
        ]

    blockers: list[str] = []

    expected_campaign_fields = {
        "schema_version",
        "code_identity",
        "focus_gate",
        "source_snapshot_digests",
        "cohort",
        "selection_policy",
        "provider",
        "graph",
        "caps",
        "ramp",
        "recovery",
        "immediate_stop_conditions",
        "success_objectives",
        "campaign_authorised",
    }
    if set(campaign) != expected_campaign_fields:
        blockers.append("CAMPAIGN_FIELDS_INVALID")

    def mapping(value: object, field: str) -> Mapping[str, object]:
        if not isinstance(value, Mapping):
            blockers.append(f"{field}_INVALID")
            return {}
        return value

    def token(value: object, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            blockers.append(f"{field}_INVALID")
            return ""
        return value

    def finite(value: object, field: str, *, positive: bool = False) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < (1 if positive else 0)
        ):
            blockers.append(f"{field}_INVALID")
            return 0
        return value

    if campaign.get("schema_version") != CAMPAIGN_SCHEMA_VERSION:
        blockers.append("CAMPAIGN_SCHEMA_INVALID")
    code = mapping(campaign.get("code_identity"), "CAMPAIGN_CODE_IDENTITY")
    if code != {"head_sha": head_sha, "tree_sha": tree_sha}:
        blockers.append("CAMPAIGN_CODE_IDENTITY_DRIFT")
    focus = mapping(campaign.get("focus_gate"), "FOCUS_GATE_EVIDENCE")
    focus_digest = token(focus.get("manifest_digest"), "FOCUS_GATE_MANIFEST_DIGEST")
    try:
        validate_sha256_digest(focus_digest, field="Focus Gate manifest digest")
    except (TypeError, ValueError):
        blockers.append("FOCUS_GATE_MANIFEST_DIGEST_INVALID")
    if (
        focus.get("head_sha") != head_sha
        or focus.get("tree_sha") != tree_sha
        or focus.get("conclusion") != "SUCCESS"
    ):
        blockers.append("EXACT_HEAD_FOCUS_GATE_NOT_PROVEN")

    expected_snapshots = mapping(
        campaign.get("source_snapshot_digests"), "SOURCE_SNAPSHOT_BINDINGS"
    )
    actual_snapshot_digests = {
        name: descriptor["descriptor_digest"]
        for name, descriptor in store_descriptors.items()
    }
    if dict(expected_snapshots) != actual_snapshot_digests:
        blockers.append("SOURCE_SNAPSHOT_DRIFT")

    candidates = historical_partition.get("current_preflight_candidates")
    if not isinstance(candidates, list):
        candidates = []
        blockers.append("CURRENT_PREFLIGHT_COHORT_UNAVAILABLE")
    derived_event_ids = [
        str(item.get("event_id"))
        for item in candidates
        if isinstance(item, Mapping)
    ]
    cohort = mapping(campaign.get("cohort"), "CAMPAIGN_COHORT")
    selected_event_ids = cohort.get("event_ids")
    if (
        not isinstance(selected_event_ids, list)
        or not all(isinstance(item, str) and item for item in selected_event_ids)
        or not selected_event_ids
        or selected_event_ids != derived_event_ids
        or len(set(item for item in selected_event_ids if isinstance(item, str)))
        != len(selected_event_ids)
        or cohort.get("manifest_digest")
        != historical_partition.get("current_preflight_candidate_manifest_digest")
    ):
        blockers.append("CAMPAIGN_COHORT_DIFFERS_FROM_CURRENT_PREFLIGHT")

    selection = mapping(campaign.get("selection_policy"), "SELECTION_POLICY")
    selection_value = {
        "policy_id": token(selection.get("policy_id"), "SELECTION_POLICY_ID"),
        "policy_version": token(
            selection.get("policy_version"), "SELECTION_POLICY_VERSION"
        ),
    }
    selection_digest = selection.get("digest")
    if selection_digest != digest_canonical(selection_value):
        blockers.append("SELECTION_POLICY_DIGEST_INVALID")

    provider = mapping(campaign.get("provider"), "PROVIDER_IDENTITIES")
    provider_value = {
        key: token(provider.get(key), f"{key.upper()}_IDENTITY")
        for key in ("provider_id", "model_id", "embedding_model_id")
    }
    graph = mapping(campaign.get("graph"), "GRAPH_IDENTITIES")
    graph_value = {
        key: token(graph.get(key), f"GRAPH_{key.upper()}")
        for key in (
            "destination_id",
            "family_id",
            "ontology_id",
            "ontology_version",
            "ontology_contract_digest",
            "mapping_id",
            "mapping_version",
            "mapping_contract_digest",
            "projector_version",
            "current_generation_id",
        )
    }
    graph_readback = authority_evidence.get("active_projection_authority")
    if not isinstance(graph_readback, Mapping):
        blockers.append("ACTIVE_GRAPH_GENERATION_READBACK_INVALID")
    else:
        exact_readback_fields = {
            "family_id": "family_id",
            "ontology_id": "ontology_id",
            "ontology_version": "ontology_version",
            "ontology_contract_digest": "ontology_contract_digest",
            "mapping_id": "mapping_id",
            "mapping_version": "mapping_version",
            "mapping_contract_digest": "mapping_contract_digest",
            "projector_version": "projector_version",
            "current_generation_id": "generation_id",
        }
        if any(
            graph_value[campaign_field] != graph_readback[readback_field]
            for campaign_field, readback_field in exact_readback_fields.items()
        ):
            blockers.append("CAMPAIGN_GRAPH_IDENTITY_DIFFERS_FROM_AUTHORITY")
    # The canonical authority store proves projection authority, not the actual
    # external graph destination. A worker-owned authenticated graph readback is
    # required before this identity can support an F4 READY packet.
    blockers.append("GRAPH_DESTINATION_READBACK_UNAVAILABLE")
    target_generation_id = digest_canonical(
        {
            "current_generation_id": graph_value["current_generation_id"],
            "projector_version": graph_value["projector_version"],
            "source_snapshot_digests": actual_snapshot_digests,
            "cohort_manifest_digest": historical_partition.get(
                "current_preflight_candidate_manifest_digest"
            ),
            "selection_policy_digest": selection_digest,
        }
    )
    if graph.get("target_generation_id") != target_generation_id:
        blockers.append("TARGET_GENERATION_DERIVATION_INVALID")
    graph_value["target_generation_id"] = target_generation_id

    caps = mapping(campaign.get("caps"), "CAMPAIGN_CAPS")
    per_event = mapping(caps.get("per_event"), "PER_EVENT_CAPS")
    total = mapping(caps.get("total"), "TOTAL_CAPS")
    rate = mapping(caps.get("rate"), "RATE_CAPS")
    count_names = (
        "proposals",
        "entity_admits",
        "relation_admits",
        "effects",
        "retries",
        "fallbacks",
    )
    caps_value = {
        "per_event": {
            name: finite(per_event.get(name), f"PER_EVENT_{name.upper()}_CAP")
            for name in count_names
        },
        "total": {
            "events": finite(total.get("events"), "TOTAL_EVENT_CAP", positive=True),
            **{
                name: finite(total.get(name), f"TOTAL_{name.upper()}_CAP")
                for name in count_names
            },
            "wall_time_seconds": finite(
                total.get("wall_time_seconds"), "TOTAL_WALL_TIME_CAP", positive=True
            ),
            "spend_gbp_microunits": finite(
                total.get("spend_gbp_microunits"), "TOTAL_SPEND_CAP"
            ),
        },
        "rate": {
            "events_per_minute": finite(
                rate.get("events_per_minute"), "EVENT_RATE_CAP", positive=True
            )
        },
    }
    if derived_event_ids and caps_value["total"]["events"] < len(derived_event_ids):
        blockers.append("TOTAL_EVENT_CAP_BELOW_SELECTED_COHORT")
    if (
        caps_value["per_event"]["fallbacks"] != 0
        or caps_value["total"]["fallbacks"] != 0
    ):
        blockers.append("FALLBACK_CAP_MUST_BE_ZERO")

    ramp = mapping(campaign.get("ramp"), "RAMP_ENTRY")
    phases = ramp.get("phases")
    ramp_phases: list[dict[str, object]] = []
    if not isinstance(phases, list) or not phases:
        blockers.append("RAMP_PHASES_INVALID")
    else:
        prior_limit = 0
        for index, raw_phase in enumerate(phases):
            phase = mapping(raw_phase, f"RAMP_PHASE_{index + 1}")
            phase_id = token(phase.get("phase_id"), f"RAMP_PHASE_{index + 1}_ID")
            event_limit = finite(
                phase.get("event_limit"),
                f"RAMP_PHASE_{index + 1}_EVENT_LIMIT",
                positive=True,
            )
            entry = phase.get("entry_conditions")
            advance = phase.get("advance_conditions")
            if (
                not isinstance(entry, list)
                or not entry
                or not all(isinstance(item, str) and item for item in entry)
                or entry != sorted(set(entry))
                or not _RAMP_ENTRY_BASE.issubset(entry)
            ):
                blockers.append(f"RAMP_PHASE_{index + 1}_ENTRY_INVALID")
                entry = []
            if (
                not isinstance(advance, list)
                or not advance
                or not all(isinstance(item, str) and item for item in advance)
                or advance != sorted(set(advance))
                or not _RAMP_ADVANCE_BASE.issubset(advance)
            ):
                blockers.append(f"RAMP_PHASE_{index + 1}_ADVANCE_INVALID")
                advance = []
            if event_limit <= prior_limit:
                blockers.append("RAMP_PHASE_LIMITS_NOT_STRICTLY_INCREASING")
            prior_limit = event_limit
            ramp_phases.append(
                {
                    "phase_id": phase_id,
                    "event_limit": event_limit,
                    "entry_conditions": entry,
                    "advance_conditions": advance,
                }
            )
        if prior_limit != caps_value["total"]["events"]:
            blockers.append("RAMP_FINAL_PHASE_DIFFERS_FROM_EVENT_CAP")
    ramp_value = {"phases": ramp_phases}

    recovery = mapping(campaign.get("recovery"), "RECOVERY_BINDINGS")
    recovery_value = {
        key: token(recovery.get(key), f"{key.upper()}_IDENTITY")
        for key in (
            "backup_identity",
            "rollback_procedure_id",
            "reconciliation_procedure_id",
        )
    }
    stops = campaign.get("immediate_stop_conditions")
    if (
        not isinstance(stops, list)
        or not all(isinstance(item, str) and item for item in stops)
        or len(stops) != len(set(item for item in stops if isinstance(item, str)))
        or not _REQUIRED_STOP_CONDITIONS.issubset(
            item for item in stops if isinstance(item, str)
        )
    ):
        blockers.append("IMMEDIATE_STOP_CONDITIONS_INCOMPLETE")
        stops = [] if not isinstance(stops, list) else stops

    objectives = mapping(campaign.get("success_objectives"), "SUCCESS_OBJECTIVES")
    required_objectives = {"watermark", "backlog", "velocity", "lag", "reconciliation"}
    if set(objectives) != required_objectives or any(
        not isinstance(objectives.get(key), (str, int, float))
        or isinstance(objectives.get(key), bool)
        for key in required_objectives
    ):
        blockers.append("SUCCESS_OBJECTIVES_INCOMPLETE")

    if campaign.get("campaign_authorised") is not False:
        blockers.append("CAMPAIGN_AUTHORITY_BOUNDARY_INVALID")
    value = {
        "configured": True,
        "campaign_input_digest": digest_canonical(campaign),
        "code_identity": dict(code),
        "focus_gate": dict(focus),
        "source_snapshot_digests": actual_snapshot_digests,
        "cohort": {
            "event_ids": derived_event_ids,
            "manifest_digest": historical_partition.get(
                "current_preflight_candidate_manifest_digest"
            ),
            "dispatch_authorised": False,
            "claim_performed": False,
        },
        "selection_policy": {**selection_value, "digest": selection_digest},
        "provider": provider_value,
        "graph": graph_value,
        "caps": caps_value,
        "ramp": ramp_value,
        "recovery": recovery_value,
        "immediate_stop_conditions": stops,
        "success_objectives": dict(objectives),
        "objectives_are_prospective": True,
        "campaign_authorised": False,
    }
    # The present worker does not consume or enforce this packet. Packet
    # completeness must never be presented as runtime campaign enforcement.
    blockers.append("RUNTIME_CAMPAIGN_ENFORCEMENT_UNPROVEN")
    return value, blockers


def build_graphiti_steady_state_packet(
    *,
    proving_store: str | Path,
    unpublished_store: str | Path,
    head_sha: str,
    tree_sha: str,
    observed_at: datetime,
    authority_store: str | Path | None = None,
    campaign_input: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build a stable report without invoking a provider or mutating either store."""

    if observed_at.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    with ExitStack() as stack:
        proving = stack.enter_context(read_only_snapshot(proving_store))
        unpublished = stack.enter_context(read_only_snapshot(unpublished_store))
        authority = (
            stack.enter_context(read_only_snapshot(authority_store))
            if authority_store is not None
            else None
        )
        proving_accounting, proving_blockers = _proving_accounting(
            proving.connection
        )
        accounting, accounting_blockers = _event_accounting(unpublished.connection)
        events, receipts, receipt_blockers = _events_and_receipts(
            unpublished.connection
        )
        historical_partition, partition_blockers = _historical_partition(
            proving.connection,
            unpublished.connection,
            authority=None if authority is None else authority.connection,
            observed_at=observed_at,
            event_evidence=events,
            receipt_evidence=receipts,
        )
        admission, admission_blockers = _admission(
            unpublished.connection, observed_at=observed_at
        )
        spend, spend_blockers = _spend(unpublished.connection)
        store_descriptors = {
            "proving": _store_descriptor(proving),
            "unpublished": _store_descriptor(unpublished),
        }
        authority_blockers: list[str] = []
        authority_evidence: dict[str, object] = {"configured": False}
        if authority is None:
            authority_blockers.append("AUTHORITY_STORE_UNCONFIGURED")
        else:
            store_descriptors["authority"] = _store_descriptor(authority)
            authority_evidence, authority_blockers = _authority_snapshot_evidence(
                authority.connection
            )
        campaign, campaign_blockers = _campaign_evidence(
            campaign_input,
            head_sha=head_sha,
            tree_sha=tree_sha,
            store_descriptors=store_descriptors,
            historical_partition=historical_partition,
            authority_evidence=authority_evidence,
        )
        blockers = (
            proving_blockers
            + accounting_blockers
            + receipt_blockers
            + partition_blockers
            + admission_blockers
            + spend_blockers
            + authority_blockers
            + campaign_blockers
        )
        blocker_values = sorted(set(blockers))
        ready = not blocker_values
        body: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "code_identity": {"head_sha": head_sha, "tree_sha": tree_sha},
            "observed_at": observed_at.astimezone(UTC)
            .isoformat()
            .replace("+00:00", "Z"),
            "store_snapshots": store_descriptors,
            "proving_accountability": proving_accounting,
            "authority_snapshot_evidence": authority_evidence,
            "runtime_composition": {
                "state": "PACKET_ONLY_NOT_RUNTIME_ENFORCED",
                "authority_store_configured": authority is not None,
                "durable_proposal_envelope_binding": True,
                "admission_policy_configured": True,
                "full_generation_projector_configured": True,
                "campaign_packet_enforced": False,
                "actual_graph_readback_observed": False,
                "campaign_authorised": False,
            },
            "bounded_campaign": campaign,
            "landed_event_accounting": accounting,
            "events": events,
            "terminal_receipts": receipts,
            "historical_partition": historical_partition,
            "admission": admission,
            "usage_and_spend": spend,
            "non_effects": {
                "provider_calls": 0,
                "store_mutations": 0,
                "service_loads": 0,
                "publication_effects": 0,
                "production_admission_effects": 0,
            },
            "blockers": blocker_values,
            "verdict": "READY_FOR_OWNER_DECISION" if ready else "NO_GO",
            "readiness": (
                "F4_CAMPAIGN_READY_FOR_OWNER_DECISION"
                if ready
                else "ENGINEERING_PREPARATION_ONLY"
            ),
        }
        return {**body, "packet_digest": digest_canonical(body)}


def write_content_addressed_packet(
    packet: Mapping[str, object], directory: str | Path
) -> Path:
    digest = str(packet.get("packet_digest") or "")
    if not digest.startswith("sha256:"):
        raise ValueError("packet has no canonical digest")
    body = {key: value for key, value in packet.items() if key != "packet_digest"}
    if digest_canonical(body) != digest:
        raise ValueError("packet canonical digest differs")
    output = Path(directory) / (
        f"graphiti-steady-state-{digest.removeprefix('sha256:')}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.",
        dir=output.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return output
