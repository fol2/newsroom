"""Existing Graphiti pipeline adapter for combined-temporal proposals."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from newsroom.graphiti_adapter.edge_guard import guard_extracted_edges
from newsroom.graphiti_adapter.neo4j_guard import GuardState, Neo4jMutationGuard

ResolveNodes = Callable[
    [list[Any]],
    Awaitable[tuple[list[Any], dict[str, str], list[tuple[Any, Any]]]],
]
ResolvePointers = Callable[[list[Any], dict[str, str]], list[Any]]
CreateEmbeddings = Callable[[Any, list[Any]], Awaitable[None]]
PersistGraph = Callable[[list[Any], list[Any]], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class CombinedTemporalPipelineResult:
    nodes: tuple[Any, ...]
    edges: tuple[Any, ...]
    guarded_edges: tuple[Any, ...]
    node_resolutions: tuple[str, ...]
    graph_effect_attempted: bool
    embedding_skipped: bool
    journal_skipped: bool
    rollback_skipped: bool
    completed_receipt: Mapping[str, object] | None = None


class CombinedTemporalPipeline(Protocol):
    def prepare_attempt(self) -> Mapping[str, object] | None: ...

    def complete_failure(
        self, receipt: Mapping[str, object]
    ) -> Mapping[str, object]: ...

    def execute(
        self,
        *,
        nodes: tuple[Any, ...],
        edges: tuple[Any, ...],
        receipt: Mapping[str, object],
    ) -> CombinedTemporalPipelineResult: ...


class CombinedTemporalPipelineError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        graph_effect_attempted: bool,
        rollback_completed: bool,
    ) -> None:
        super().__init__(message)
        self.graph_effect_attempted = graph_effect_attempted
        self.rollback_completed = rollback_completed


def _durable_receipt(
    receipt: Mapping[str, object],
    *,
    nodes: list[Any],
    edges: list[Any],
    resolutions: tuple[str, ...],
    chat_invocations: list[dict[str, object]],
    embedding_usage: dict[str, object],
) -> dict[str, object]:
    durable = dict(receipt)
    durable.setdefault("provider_attempt_number", 1)
    durable["pipeline_chat_invocations"] = [dict(item) for item in chat_invocations]
    durable["embedding_usage"] = dict(embedding_usage)
    durable["invocation_count"] = int(durable.get("invocation_count", 0)) + len(
        chat_invocations
    )
    proposal_raw = durable.get("proposal_receipt")
    if not isinstance(proposal_raw, Mapping):
        return durable
    proposal = dict(proposal_raw)
    mentions_raw = proposal.get("entity_mentions")
    relations_raw = proposal.get("relation_proposals")
    if not isinstance(mentions_raw, list) or len(mentions_raw) != len(nodes):
        raise ValueError("entity mention receipt does not match resolved nodes")
    if not isinstance(relations_raw, list) or len(relations_raw) != len(edges):
        raise ValueError("relation proposal receipt does not match guarded edges")

    mentions: list[dict[str, object]] = []
    for raw, node, resolution in zip(mentions_raw, nodes, resolutions, strict=True):
        if not isinstance(raw, Mapping):
            raise ValueError("entity mention receipt is malformed")
        item = dict(raw)
        item.update(
            {
                "canonical_identity": str(node.uuid),
                "resolution": resolution,
            }
        )
        mentions.append(item)

    relations: list[dict[str, object]] = []
    for raw, edge in zip(relations_raw, edges, strict=True):
        if not isinstance(raw, Mapping):
            raise ValueError("relation proposal receipt is malformed")
        item = dict(raw)
        item.update(
            {
                "proposal_identity": str(edge.uuid),
                "source_identity": str(edge.source_node_uuid),
                "target_identity": str(edge.target_node_uuid),
                "fact_embedding": getattr(edge, "fact_embedding", None),
            }
        )
        relations.append(item)
    proposal["entity_mentions"] = mentions
    proposal["relation_proposals"] = relations
    proposal["node_resolutions"] = list(resolutions)
    durable["proposal_receipt"] = proposal
    return durable


@dataclass(slots=True)
class ExistingGraphitiPipeline:
    """Bind proposals to Graphiti resolution, embedding and durable rollback."""

    guard: Neo4jMutationGuard
    resolve_nodes: ResolveNodes
    resolve_pointers: ResolvePointers
    create_embeddings: CreateEmbeddings
    persist_graph: PersistGraph
    embedder: Any
    run_async: Callable[[Awaitable[Any]], Any]
    chat_receipt: Callable[[], list[dict[str, object]]]
    embedding_receipt: Callable[[], dict[str, object]]
    expected_group_id: str | None = None
    expected_episode_uuid: str | None = None
    expected_ingest_id: str | None = None
    _attempt_started: bool = field(default=False, init=False)

    def prepare_attempt(self) -> Mapping[str, object] | None:
        return self.run_async(self._prepare_attempt())

    async def _prepare_attempt(self) -> Mapping[str, object] | None:
        try:
            marker = await self.guard.begin()
        except Exception as exc:
            raise CombinedTemporalPipelineError(
                "combined-temporal journal could not start",
                graph_effect_attempted=False,
                rollback_completed=False,
            ) from exc
        if marker.state is GuardState.CREATED:
            self._attempt_started = True
            return None
        if marker.state is GuardState.COMPLETE:
            try:
                return await self.guard.completed_raw()
            except Exception as exc:
                raise CombinedTemporalPipelineError(
                    "combined-temporal completed receipt is malformed",
                    graph_effect_attempted=False,
                    rollback_completed=False,
                ) from exc
        rollback_completed = marker.state is GuardState.RECOVERED_AMBIGUOUS
        if marker.state in {GuardState.PENDING, GuardState.ROLLING_BACK}:
            try:
                rollback_completed = await self.guard.rollback_pending(
                    chat_invocations=[dict(item) for item in marker.chat_invocations],
                    embedding_usage=dict(marker.embedding_usage or {}),
                    reason="RECOVERED_BEFORE_PROVIDER_RETRY",
                )
            except Exception:
                rollback_completed = False
        raise CombinedTemporalPipelineError(
            "combined-temporal journal blocks another provider leaf",
            graph_effect_attempted=True,
            rollback_completed=rollback_completed,
        )

    def complete_failure(
        self, receipt: Mapping[str, object]
    ) -> Mapping[str, object]:
        return self.run_async(self._complete_failure(receipt))

    async def _complete_failure(
        self, receipt: Mapping[str, object]
    ) -> Mapping[str, object]:
        if not self._attempt_started:
            raise CombinedTemporalPipelineError(
                "combined-temporal failed leaf has no pending journal",
                graph_effect_attempted=False,
                rollback_completed=False,
            )
        chat_invocations = self.chat_receipt()
        embedding_usage = self.embedding_receipt()
        durable = _durable_receipt(
            receipt,
            nodes=[],
            edges=[],
            resolutions=(),
            chat_invocations=chat_invocations,
            embedding_usage=embedding_usage,
        )
        await self.guard.record_pending_telemetry(
            chat_invocations=chat_invocations,
            embedding_usage=embedding_usage,
        )
        await self.guard.complete(durable)
        self._attempt_started = False
        return durable

    def execute(
        self,
        *,
        nodes: tuple[Any, ...],
        edges: tuple[Any, ...],
        receipt: Mapping[str, object],
    ) -> CombinedTemporalPipelineResult:
        return self.run_async(self._execute(nodes=nodes, edges=edges, receipt=receipt))

    async def _execute(
        self,
        *,
        nodes: tuple[Any, ...],
        edges: tuple[Any, ...],
        receipt: Mapping[str, object],
    ) -> CombinedTemporalPipelineResult:
        self._validate_context(nodes=nodes, edges=edges, receipt=receipt)
        if not self._attempt_started:
            completed = await self._prepare_attempt()
            if completed is not None:
                raise CombinedTemporalPipelineError(
                    "combined-temporal completed result must be replayed "
                    "before execution",
                    graph_effect_attempted=False,
                    rollback_completed=False,
                )
        if not nodes and not edges:
            chat_invocations = self.chat_receipt()
            embedding_usage = self.embedding_receipt()
            await self.guard.record_pending_telemetry(
                chat_invocations=chat_invocations,
                embedding_usage=embedding_usage,
            )
            durable_receipt = _durable_receipt(
                receipt,
                nodes=[],
                edges=[],
                resolutions=(),
                chat_invocations=chat_invocations,
                embedding_usage=embedding_usage,
            )
            await self.guard.complete(durable_receipt)
            self._attempt_started = False
            return CombinedTemporalPipelineResult(
                nodes=(),
                edges=(),
                guarded_edges=(),
                node_resolutions=(),
                graph_effect_attempted=False,
                embedding_skipped=True,
                journal_skipped=False,
                rollback_skipped=True,
                completed_receipt=durable_receipt,
            )
        try:
            resolved_nodes, uuid_map, _duplicates = await self.resolve_nodes(
                list(nodes)
            )
            guarded, _invalidated, episode_edges = await guard_extracted_edges(
                extracted_edges=list(edges),
                uuid_map=uuid_map,
                embedder=self.embedder,
                resolve_pointers=self.resolve_pointers,
                create_embeddings=self.create_embeddings,
            )
            if len(guarded) != len(edges) or len(episode_edges) != len(edges):
                raise RuntimeError("edge guard dropped a combined-temporal relation")
            original_ids = {str(node.uuid) for node in nodes}
            resolutions = tuple(
                "NEW" if str(node.uuid) in original_ids else "RESOLVED_EXISTING"
                for node in resolved_nodes
            )
            for node, resolution in zip(resolved_nodes, resolutions, strict=True):
                attributes = dict(getattr(node, "attributes", {}) or {})
                attributes["resolution"] = resolution
                node.attributes = attributes
            async with self.guard.fenced_graph_mutation():
                await self.persist_graph(resolved_nodes, guarded)
            chat_invocations = self.chat_receipt()
            embedding_usage = self.embedding_receipt()
            await self.guard.record_pending_telemetry(
                chat_invocations=chat_invocations,
                embedding_usage=embedding_usage,
            )
            await self.guard.restore_preexisting()
            durable_receipt = _durable_receipt(
                receipt,
                nodes=resolved_nodes,
                edges=guarded,
                resolutions=resolutions,
                chat_invocations=chat_invocations,
                embedding_usage=embedding_usage,
            )
            await self.guard.complete(durable_receipt)
        except Exception as exc:
            rollback_completed = False
            try:
                rollback_completed = await self.guard.rollback_pending(
                    chat_invocations=self.chat_receipt(),
                    embedding_usage=self.embedding_receipt(),
                    reason=type(exc).__name__,
                )
            except Exception:
                rollback_completed = False
            self._attempt_started = False
            raise CombinedTemporalPipelineError(
                "combined-temporal pipeline failed",
                graph_effect_attempted=True,
                rollback_completed=rollback_completed,
            ) from exc

        self._attempt_started = False

        return CombinedTemporalPipelineResult(
            nodes=tuple(resolved_nodes),
            edges=tuple(guarded),
            guarded_edges=tuple(guarded),
            node_resolutions=resolutions,
            graph_effect_attempted=True,
            embedding_skipped=False,
            journal_skipped=False,
            rollback_skipped=True,
            completed_receipt=durable_receipt,
        )

    def _validate_context(
        self,
        *,
        nodes: tuple[Any, ...],
        edges: tuple[Any, ...],
        receipt: Mapping[str, object],
    ) -> None:
        if self.expected_group_id is None:
            return
        proposal = receipt.get("proposal_receipt")
        if (
            receipt.get("ingest_id") != self.expected_ingest_id
            or not isinstance(proposal, Mapping)
            or proposal.get("episode_id") != self.expected_episode_uuid
            or any(str(node.group_id) != self.expected_group_id for node in nodes)
            or any(str(edge.group_id) != self.expected_group_id for edge in edges)
            or any(
                list(edge.episodes) != [self.expected_episode_uuid]
                for edge in edges
            )
        ):
            raise CombinedTemporalPipelineError(
                "combined-temporal pipeline identity differs",
                graph_effect_attempted=False,
                rollback_completed=False,
            )


__all__ = [
    "CombinedTemporalPipeline",
    "CombinedTemporalPipelineError",
    "CombinedTemporalPipelineResult",
    "ExistingGraphitiPipeline",
]
