"""Governed unpublished cycle: Signal → Lead → Hypothesis → Candidate → Evidence → write."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from newsroom.control_plane.editorial import GroupedObservation, form_candidates
from newsroom.control_plane.evidence import package_for
from newsroom.control_plane.graphiti import GraphitiPort
from newsroom.control_plane.items import parse_observation
from newsroom.control_plane.store import (
    append_ledger,
    connect,
    has_candidate,
    has_graphiti_attempt,
    insert_graphiti_attempt,
    insert_payload,
    spend_reserved,
)
from newsroom.control_plane.surface import UnpublishedSurfacePayload
from newsroom.control_plane.veto import VetoError, assert_private_store
from newsroom.control_plane.writer import WriterPort
from newsroom.graphiti_adapter.evaluation_packet import (
    GRAPHITI_WORKSPACE_GROUP,
    OD_011_CASH_CEILING_GBP,
    OPENROUTER_API,
)
from newsroom.increment9.proving import FORBIDDEN_STORE_MARKERS


@dataclass(frozen=True, slots=True)
class CycleReport:
    proving_run_id: str
    minted: int
    duplicate: int
    sources: int
    candidates: int
    ledger_digest: str
    writer_id: str
    graphiti: int = 0


def _latest_run(connection: sqlite3.Connection) -> str | None:
    row = connection.execute(
        "SELECT run_id FROM proving_runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def _now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def run_cycle(
    *,
    proving_store: str,
    unpublished_store: str,
    writer: WriterPort,
    max_writes: int = 5,
    graphiti: GraphitiPort | None = None,
    max_graphiti: int = 1,
) -> CycleReport:
    assert_private_store(unpublished_store)
    lowered = proving_store.lower()
    if any(marker in lowered for marker in FORBIDDEN_STORE_MARKERS):
        raise ValueError("proving store must not alias production or news_pool")
    proving = sqlite3.connect(proving_store)
    proving.execute("PRAGMA query_only=ON")
    try:
        run_id = _latest_run(proving)
        if run_id is None:
            raise ValueError("proving store has no runs")
        rows = proving.execute(
            """
            SELECT source_id, url, fetched_at, status_code, body_digest, body
            FROM proving_observations
            WHERE run_id=?
            ORDER BY source_id
            """,
            (run_id,),
        ).fetchall()
    finally:
        proving.close()

    observations: list[GroupedObservation] = []
    sources = 0
    for source_id, url, _fetched_at, status_code, body_digest, body in rows:
        if int(status_code) != 200 or not body:
            continue
        sources += 1
        for item in parse_observation(source_id=source_id, url=url, body=body):
            observations.append(
                GroupedObservation(
                    source_id=source_id,
                    observation_digest=body_digest,
                    item=item,
                )
            )

    candidates = form_candidates(tuple(observations))
    unpublished = connect(unpublished_store)
    minted = 0
    duplicate = 0
    try:
        append_ledger(
            unpublished,
            "PRIVATE_CYCLE_START",
            {
                "proving_run_id": run_id,
                "observations": len(rows),
                "candidates": len(candidates),
                "writer_id": writer.writer_id,
            },
        )
        for candidate in candidates:
            if minted >= max_writes:
                break
            if has_candidate(unpublished, candidate.candidate_id):
                duplicate += 1
                continue
            package = package_for(candidate)
            try:
                copy = writer.write(candidate, package)
                payload = UnpublishedSurfacePayload(
                    payload_kind="unpublished_surface_payload",
                    publication_bundle=False,
                    auto_publish=False,
                    language="ZH_HANT_HK",
                    title=copy.title,
                    body=copy.body,
                    evidence_package_digest=package.digest,
                    story_candidate_id=candidate.candidate_id,
                    event_hypothesis_id=candidate.hypothesis_id,
                    source_lineage=tuple(
                        sorted({item.source_id for item in candidate.items})
                    ),
                    generated_at=_now(),
                    status="UNPUBLISHED",
                    writer_id=copy.writer_id,
                )
            except VetoError:
                raise
            except (RuntimeError, ValueError, OSError, json.JSONDecodeError):
                continue
            if insert_payload(unpublished, payload):
                minted += 1
            else:
                duplicate += 1
        graphiti_ok = 0
        if graphiti is not None:
            if not spend_reserved(unpublished):
                append_ledger(
                    unpublished,
                    "GRAPHITI_SPEND_RESERVE",
                    {
                        "profile": "EVALUATION",
                        "metered_api": OPENROUTER_API,
                        "od_011_cash_ceiling_gbp": OD_011_CASH_CEILING_GBP,
                        "prespent": False,
                        "hosts": ["openrouter.ai"],
                    },
                )
            for candidate in candidates:
                if graphiti_ok >= max_graphiti:
                    break
                if has_graphiti_attempt(unpublished, candidate.candidate_id):
                    continue
                package = package_for(candidate)
                try:
                    result = graphiti.extract(package)
                except VetoError:
                    raise
                except (RuntimeError, ValueError, OSError, json.JSONDecodeError):
                    continue
                append_ledger(
                    unpublished,
                    "GRAPHITI_EVALUATION_ATTEMPT",
                    {
                        "story_candidate_id": candidate.candidate_id,
                        "evidence_package_digest": package.digest,
                        "outcome": result.outcome,
                        "proposal_count": result.proposal_count,
                        "failure_code": result.failure_code,
                        "workspace_group": GRAPHITI_WORKSPACE_GROUP,
                        "profile": "EVALUATION",
                    },
                )
                if result.outcome in {"COMPLETE", "PARTIAL"}:
                    insert_graphiti_attempt(
                        unpublished,
                        candidate_id=candidate.candidate_id,
                        outcome=result.outcome,
                        proposal_count=result.proposal_count,
                        failure_code=result.failure_code,
                    )
                graphiti_ok += 1
        digest = append_ledger(
            unpublished,
            "PRIVATE_CYCLE_CLOSE",
            {
                "proving_run_id": run_id,
                "minted": minted,
                "duplicate": duplicate,
                "sources": sources,
                "candidates": len(candidates),
                "writer_id": writer.writer_id,
                "graphiti": graphiti_ok,
            },
        )
        unpublished.commit()
    finally:
        unpublished.close()
    return CycleReport(
        run_id,
        minted,
        duplicate,
        sources,
        len(candidates),
        digest,
        writer.writer_id,
        graphiti_ok,
    )
