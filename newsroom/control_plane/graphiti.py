"""EVALUATION Graphiti runner for corpus ingest, decoupled from CONT writes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol

from newsroom.control_plane.corpus import CorpusIngestUnit
from newsroom.graphiti_adapter.evaluation_packet import (
    GRAPHITI_CHAT_FALLBACK,
    GRAPHITI_CHAT_MODEL,
    GRAPHITI_CORE_RELEASE,
    GRAPHITI_EMBEDDING_MODEL,
    GRAPHITI_GENERATION_ID,
    GRAPHITI_WORKSPACE_GROUP,
)


@dataclass(frozen=True, slots=True)
class GraphitiCycleResult:
    ingest_id: str
    source_id: str
    item_key: str
    outcome: str
    proposal_count: int
    entity_count: int
    relation_count: int
    failure_code: str
    temporal_basis: str
    reference_time: str
    generation_id: str = GRAPHITI_GENERATION_ID
    receipt_digest: str = ""
    workspace_group: str = GRAPHITI_WORKSPACE_GROUP
    episode_uuid: str = ""
    entities: tuple[dict[str, object], ...] = ()
    relations: tuple[dict[str, object], ...] = ()
    chat_invocations: tuple[dict[str, str], ...] = ()
    request_tokens: int = 0
    response_tokens: int = 0
    cost_microunits: int = 0
    framework: str = GRAPHITI_CORE_RELEASE
    chat: str = GRAPHITI_CHAT_MODEL
    chat_fallback: str = GRAPHITI_CHAT_FALLBACK
    embedding: str = GRAPHITI_EMBEDDING_MODEL


class GraphitiPort(Protocol):
    def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult: ...


class EvaluationGraphitiRunner:
    """Real Graphiti under EVALUATION. Does not write the ledger or admitted labels."""

    def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
        from newsroom.graphiti_adapter.evaluation_attempt import evaluation_attempt_for_body
        from newsroom.graphiti_adapter.real import RealGraphitiAdapter

        temporal = unit.temporal()
        attempt = evaluation_attempt_for_body(
            episode_body=unit.episode_body,
            ingest_id=unit.ingest_id,
            published_at=unit.published_at,
            updated_at=unit.updated_at,
            observed_at=unit.observed_at,
        )
        with TemporaryDirectory() as root:
            execution = RealGraphitiAdapter().execute(
                attempt=attempt,
                workspace_root=Path(root),
            )
        raw = execution.produced.raw_output_value
        payload = raw if isinstance(raw, dict) else {}
        relations = (
            tuple(payload["relations"])
            if isinstance(payload.get("relations"), list)
            else ()
        )
        entities = (
            tuple(payload["entities"])
            if isinstance(payload.get("entities"), list)
            else ()
        )
        invocations = payload.get("chat_invocations")
        usage = execution.produced.usage
        return GraphitiCycleResult(
            ingest_id=unit.ingest_id,
            source_id=unit.source_id,
            item_key=unit.item_key,
            outcome=execution.outcome.value,
            proposal_count=len(execution.produced.proposals) + len(relations),
            entity_count=len(entities),
            relation_count=len(relations),
            failure_code=execution.failure_code,
            temporal_basis=temporal.basis,
            reference_time=temporal.reference_time.to_text(),
            generation_id=GRAPHITI_GENERATION_ID,
            receipt_digest=str(payload.get("raw_output_digest") or ""),
            episode_uuid=str(payload.get("episode_uuid") or unit.ingest_id),
            entities=entities,
            relations=relations,
            chat_invocations=tuple(invocations) if isinstance(invocations, list) else (),
            request_tokens=usage.request_tokens,
            response_tokens=usage.response_tokens,
            cost_microunits=usage.cost_microunits,
        )


__all__ = ["EvaluationGraphitiRunner", "GraphitiCycleResult", "GraphitiPort"]
