"""Provider-free, read-only Graphiti steady-state evidence packet."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Mapping

from newsroom.authority.canonical import digest_canonical
from newsroom.control_plane.graphiti_admission import graphiti_admission_telemetry
from newsroom.control_plane.graphiti_events import GRAPHITI_EVENT_STATES
from newsroom.control_plane.read_only_snapshot import read_only_snapshot

SCHEMA_VERSION = "newsroom.graphiti-steady-state-packet.v1"


class AdmissionRuntimeComposition(StrEnum):
    UNCOMPOSED = "UNCOMPOSED"
    COMPOSED = "COMPOSED"


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


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
    }
    if not required.issubset(tables):
        return (
            {"state_counts": {}},
            {"terminal_ingest_count": 0, "integrity_failures": []},
            ["TERMINAL_RECEIPT_SCHEMA_MISSING"],
        )
    rows = connection.execute(
        "SELECT event_id,state,proposal_count,manifest_json "
        "FROM unpublished_graphiti_revision_events ORDER BY ledger_seq"
    ).fetchall()
    states = Counter(str(row[1]) for row in rows)
    unknown = sorted(set(states) - set(GRAPHITI_EVENT_STATES))
    if unknown:
        blockers.append("UNKNOWN_EVENT_STATE")
    failures: list[dict[str, str]] = []
    terminal_ingests: set[str] = set()
    zero_proposal = 0
    for event_id, state, event_proposals, manifest_json in rows:
        if state != "TERMINAL":
            continue
        try:
            manifest = json.loads(str(manifest_json))
            ingest_ids = manifest.get("landed_ingest_ids")
            if not isinstance(ingest_ids, list) or not all(
                isinstance(item, str) for item in ingest_ids
            ) or len(set(ingest_ids)) != len(ingest_ids):
                raise ValueError
        except (json.JSONDecodeError, ValueError, AttributeError):
            failures.append(
                {"event_id": str(event_id), "reason": "MALFORMED_EVENT_MANIFEST"}
            )
            continue
        proposal_sum = 0
        for ingest_id in ingest_ids:
            terminal_ingests.add(ingest_id)
            row = connection.execute(
                "SELECT outcome,proposal_count,receipt_digest,receipt_json "
                "FROM unpublished_graphiti_ingest "
                "LEFT JOIN unpublished_graphiti_receipts USING(ingest_id) "
                "WHERE ingest_id=?",
                (ingest_id,),
            ).fetchone()
            if row is None or row[0] not in {"COMPLETE", "PARTIAL"} or row[3] is None:
                failures.append(
                    {
                        "ingest_id": ingest_id,
                        "reason": "TERMINAL_INGEST_OR_RECEIPT_MISSING",
                    }
                )
                continue
            try:
                receipt = json.loads(str(row[3]))
            except json.JSONDecodeError:
                failures.append(
                    {"ingest_id": ingest_id, "reason": "RECEIPT_JSON_INVALID"}
                )
                continue
            proposals = receipt.get("proposals") if isinstance(receipt, dict) else None
            if not isinstance(proposals, list) or len(proposals) != int(row[1]):
                failures.append(
                    {
                        "ingest_id": ingest_id,
                        "reason": "RECEIPT_PROPOSAL_COUNT_CONTRADICTION",
                    }
                )
                continue
            raw_digest = receipt.get("raw_output_digest")
            if not isinstance(raw_digest, str) or raw_digest != str(row[2]):
                failures.append(
                    {
                        "ingest_id": ingest_id,
                        "reason": "RECEIPT_DIGEST_CONTRADICTION",
                    }
                )
                continue
            proposal_sum += int(row[1])
            if int(row[1]) == 0:
                zero_proposal += 1
        if event_proposals is None or int(event_proposals) != proposal_sum:
            failures.append(
                {
                    "event_id": str(event_id),
                    "reason": "EVENT_PROPOSAL_COUNT_CONTRADICTION",
                }
            )
    nonterminal = sum(count for state, count in states.items() if state != "TERMINAL")
    if nonterminal:
        blockers.append("EVENTS_NOT_TERMINAL")
    if failures:
        blockers.append("TERMINAL_RECEIPT_INTEGRITY_FAILURE")
    return {
        "state_counts": {
            key: states.get(key, 0) for key in sorted(GRAPHITI_EVENT_STATES)
        },
        "terminal_event_count": states.get("TERMINAL", 0),
        "nonterminal_event_count": nonterminal,
    }, {
        "terminal_ingest_count": len(terminal_ingests),
        "zero_proposal_success_count": zero_proposal,
        "zero_proposal_is_success": True,
        "integrity_failures": failures,
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
    if value["admission_backlog"]:
        blockers.append("ADMISSION_BACKLOG_PRESENT")
    if value["dead_letter_count"]:
        blockers.append("ADMISSION_DEAD_LETTER_PRESENT")
    if value["integrity_hold_receipt_count"]:
        blockers.append("ADMISSION_INTEGRITY_HOLD_PRESENT")
    if value["projection_gap_count"]:
        blockers.append("ADMISSION_PROJECTION_GAP_PRESENT")
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


def build_graphiti_steady_state_packet(
    *,
    proving_store: str | Path,
    unpublished_store: str | Path,
    head_sha: str,
    tree_sha: str,
    observed_at: datetime,
    admission_runtime: AdmissionRuntimeComposition = (
        AdmissionRuntimeComposition.UNCOMPOSED
    ),
) -> dict[str, object]:
    """Build a stable report without invoking a provider or mutating either store."""

    if observed_at.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    with (
        read_only_snapshot(proving_store) as proving,
        read_only_snapshot(unpublished_store) as unpublished,
    ):
        accounting, accounting_blockers = _event_accounting(unpublished.connection)
        events, receipts, receipt_blockers = _events_and_receipts(
            unpublished.connection
        )
        admission, admission_blockers = _admission(
            unpublished.connection, observed_at=observed_at
        )
        spend, spend_blockers = _spend(unpublished.connection)
        blockers = (
            accounting_blockers
            + receipt_blockers
            + admission_blockers
            + spend_blockers
        )
        if admission_runtime is AdmissionRuntimeComposition.UNCOMPOSED:
            blockers.append("ADMISSION_RUNTIME_UNCOMPOSED")
        blocker_values = sorted(set(blockers))
        body: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "code_identity": {"head_sha": head_sha, "tree_sha": tree_sha},
            "observed_at": observed_at.astimezone(UTC)
            .isoformat()
            .replace("+00:00", "Z"),
            "store_snapshots": {
                "proving": {
                    "source_path": proving.source_path,
                    "source_files": list(proving.source_files),
                    "snapshot_files": list(proving.snapshot_files),
                },
                "unpublished": {
                    "source_path": unpublished.source_path,
                    "source_files": list(unpublished.source_files),
                    "snapshot_files": list(unpublished.snapshot_files),
                },
            },
            "runtime_composition": admission_runtime.value,
            "landed_event_accounting": accounting,
            "events": events,
            "terminal_receipts": receipts,
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
            "verdict": "GO" if not blocker_values else "NO_GO",
            "readiness": (
                "READY_FOR_F4"
                if not blocker_values
                else "READY_FOR_F4_ENGINEERING_GAP"
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
    with output.open("x", encoding="utf-8") as handle:
        json.dump(packet, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return output
