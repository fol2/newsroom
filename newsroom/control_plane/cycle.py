"""Governed unpublished cycle: Signal → Lead → Hypothesis → Candidate → Evidence → write.

Graphiti corpus ingest is independent of CONT writes (GING-001).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from newsroom.control_plane.corpus import units_from
from newsroom.control_plane.editorial import GroupedObservation, form_candidates
from newsroom.control_plane.evidence import package_for
from newsroom.control_plane.graphiti import GraphitiCycleResult, GraphitiPort
from newsroom.control_plane.items import parse_observation
from newsroom.control_plane.store import (
    append_ledger,
    clear_graphiti_failure,
    connect,
    graphiti_coverage,
    graphiti_failure_state,
    has_candidate,
    has_graphiti_ingest,
    insert_graphiti_ingest,
    insert_payload,
    record_graphiti_coverage,
    record_graphiti_failure,
    spend_reserved,
)
from newsroom.control_plane.surface import UnpublishedSurfacePayload
from newsroom.control_plane.veto import VetoError, assert_private_store
from newsroom.control_plane.writer import WriterPort
from newsroom.graphiti_adapter.contracts import GRAPHITI_PROMPT_COMPONENT
from newsroom.graphiti_adapter.evaluation_packet import (
    GRAPHITI_CHAT_FALLBACK,
    GRAPHITI_CHAT_MODEL,
    GRAPHITI_CORE_RELEASE,
    GRAPHITI_EMBEDDING_MODEL,
    GRAPHITI_GENERATION_ID,
    GRAPHITI_WORKSPACE_GROUP,
    OD_011_CASH_CEILING_GBP,
    OPENROUTER_API,
)
from newsroom.increment9.proving import FORBIDDEN_STORE_MARKERS, rights_permitted_sources


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
    eligible: int = 0


def _latest_run(connection: sqlite3.Connection) -> str | None:
    row = connection.execute(
        "SELECT run_id FROM proving_runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def _now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _bind_result(unit, result: GraphitiCycleResult) -> GraphitiCycleResult:
    if (result.ingest_id, result.source_id, result.item_key) != (
        unit.ingest_id,
        unit.source_id,
        unit.item_key,
    ):
        raise ValueError("graphiti result identity differs from ingest unit")
    return result


def _receipt(unit, result: GraphitiCycleResult) -> dict[str, object]:
    return {
        "ingest_id": unit.ingest_id,
        "source_id": unit.source_id,
        "item_key": unit.item_key,
        "proving_run_id": unit.proving_run_id,
        "observation_digest": unit.observation_digest,
        "published_at": unit.published_at,
        "updated_at": unit.updated_at,
        "observed_at": unit.observed_at,
        "chunk_ordinal": unit.chunk_ordinal,
        "outcome": result.outcome,
        "proposal_count": result.proposal_count,
        "entity_count": result.entity_count,
        "relation_count": result.relation_count,
        "failure_code": result.failure_code,
        "temporal_basis": result.temporal_basis,
        "reference_time": result.reference_time,
        "generation_id": result.generation_id,
        "workspace_group": GRAPHITI_WORKSPACE_GROUP,
        "episode_uuid": result.episode_uuid,
        "entities": list(result.entities),
        "relations": list(result.relations),
        "chat_invocations": list(result.chat_invocations),
        "request_tokens": result.request_tokens,
        "response_tokens": result.response_tokens,
        "cost_microunits": result.cost_microunits,
        "usage_basis": result.usage_basis,
        "prompt_version": result.prompt_version or GRAPHITI_PROMPT_COMPONENT.component_version,
        "chat_subscription_not_debited": True,
        "framework": result.framework or GRAPHITI_CORE_RELEASE,
        "chat": result.chat or GRAPHITI_CHAT_MODEL,
        "chat_fallback": result.chat_fallback or GRAPHITI_CHAT_FALLBACK,
        "embedding": result.embedding or GRAPHITI_EMBEDDING_MODEL,
        "receipt_digest": result.receipt_digest,
        "profile": "EVALUATION",
    }


def _queue(unpublished: sqlite3.Connection, units):
    queued = []
    for unit in units:
        if has_graphiti_ingest(unpublished, unit.ingest_id):
            continue
        retries, dead = graphiti_failure_state(unpublished, unit.ingest_id)
        if dead:
            continue
        queued.append((retries, unit.ingest_id, unit))
    queued.sort()
    return queued


def _fail(unpublished: sqlite3.Connection, unit, *, outcome: str, failure_code: str) -> None:
    record_graphiti_failure(
        unpublished,
        ingest_id=unit.ingest_id,
        source_id=unit.source_id,
        item_key=unit.item_key,
        outcome=outcome,
        failure_code=failure_code,
    )


def _ingest(
    unpublished: sqlite3.Connection,
    *,
    graphiti: GraphitiPort,
    units,
    max_graphiti: int,
    proving_run_id: str,
) -> int:
    if not spend_reserved(unpublished):
        append_ledger(
            unpublished,
            "GRAPHITI_SPEND_RESERVE",
            {
                "profile": "EVALUATION",
                "metered_api": OPENROUTER_API,
                "metered_use": "embeddings",
                "chat": GRAPHITI_CHAT_MODEL,
                "chat_fallback": GRAPHITI_CHAT_FALLBACK,
                "chat_subscription_not_debited": True,
                "od_011_cash_ceiling_gbp": OD_011_CASH_CEILING_GBP,
                "prespent": False,
                "hosts": ["openrouter.ai"],
                "generation_id": GRAPHITI_GENERATION_ID,
                "proving_run_id": proving_run_id,
            },
        )
    attempted = 0
    for _retries, _ingest_id, unit in _queue(unpublished, units):
        if attempted >= max_graphiti:
            break
        attempted += 1
        try:
            result = _bind_result(unit, graphiti.ingest(unit))
        except VetoError:
            raise
        except (RuntimeError, ValueError, OSError, json.JSONDecodeError):
            _fail(
                unpublished,
                unit,
                outcome="FAILED",
                failure_code="PRODUCER_INTERNAL_ERROR",
            )
            continue
        receipt = _receipt(unit, result)
        append_ledger(unpublished, "GRAPHITI_EVALUATION_ATTEMPT", receipt)
        if result.outcome in {"COMPLETE", "PARTIAL"}:
            insert_graphiti_ingest(
                unpublished,
                ingest_id=unit.ingest_id,
                source_id=unit.source_id,
                item_key=unit.item_key,
                outcome=result.outcome,
                proposal_count=result.proposal_count,
                entity_count=result.entity_count,
                relation_count=result.relation_count,
                failure_code=result.failure_code,
                temporal_basis=result.temporal_basis,
                reference_time=result.reference_time,
                generation_id=result.generation_id,
                receipt_digest=result.receipt_digest,
                receipt=receipt,
            )
            clear_graphiti_failure(unpublished, unit.ingest_id)
        else:
            _fail(
                unpublished,
                unit,
                outcome=result.outcome,
                failure_code=result.failure_code,
            )
    return attempted


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
        permitted = rights_permitted_sources(proving, run_id)
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
    for source_id, url, fetched_at, status_code, body_digest, body in rows:
        if source_id not in permitted:
            continue
        if int(status_code) != 200 or not body:
            continue
        sources += 1
        for item in parse_observation(source_id=source_id, url=url, body=body):
            observations.append(
                GroupedObservation(
                    source_id=source_id,
                    observation_digest=body_digest,
                    item=item,
                    observed_at=str(fetched_at),
                )
            )

    candidates = form_candidates(tuple(observations))
    units = units_from(tuple(observations), proving_run_id=run_id)
    unpublished = connect(unpublished_store)
    minted = 0
    duplicate = 0
    graphiti_ok = 0
    try:
        append_ledger(
            unpublished,
            "PRIVATE_CYCLE_START",
            {
                "proving_run_id": run_id,
                "observations": len(rows),
                "candidates": len(candidates),
                "eligible_source_revisions": len(units),
                "writer_id": writer.writer_id,
            },
        )
        if graphiti is not None:
            graphiti_ok = _ingest(
                unpublished,
                graphiti=graphiti,
                units=units,
                max_graphiti=max_graphiti,
                proving_run_id=run_id,
            )
            unpublished.commit()
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
        coverage = graphiti_coverage(
            unpublished,
            eligible_ids=tuple(unit.ingest_id for unit in units),
            observed_at=tuple(unit.observed_at for unit in units),
        )
        record_graphiti_coverage(unpublished, coverage)
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
                **coverage,
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
        len(units),
    )
