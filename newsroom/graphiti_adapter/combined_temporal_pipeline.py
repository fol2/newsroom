"""Existing Graphiti pipeline adapter for combined-temporal proposals."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
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


class CombinedTemporalPipeline(Protocol):
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
        try:
            marker = await self.guard.begin()
        except Exception as exc:
            raise CombinedTemporalPipelineError(
                "combined-temporal journal could not start",
                graph_effect_attempted=False,
                rollback_completed=False,
            ) from exc
        if marker.state is not GuardState.CREATED:
            rollback_completed = marker.state is GuardState.RECOVERED_AMBIGUOUS
            if marker.state in {GuardState.PENDING, GuardState.ROLLING_BACK}:
                try:
                    rollback_completed = await self.guard.rollback_pending(
                        chat_invocations=self.chat_receipt(),
                        embedding_usage=self.embedding_receipt(),
                        reason="RECOVERED_PENDING_PROCESS_DEATH",
                    )
                except Exception:
                    rollback_completed = False
            raise CombinedTemporalPipelineError(
                "combined-temporal journal is not newly created",
                graph_effect_attempted=True,
                rollback_completed=rollback_completed,
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
            await self.persist_graph(resolved_nodes, guarded)
            await self.guard.record_pending_telemetry(
                chat_invocations=self.chat_receipt(),
                embedding_usage=self.embedding_receipt(),
            )
            await self.guard.restore_preexisting()
            durable_receipt = dict(receipt)
            durable_receipt.setdefault("provider_attempt_number", 1)
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
            raise CombinedTemporalPipelineError(
                "combined-temporal pipeline failed",
                graph_effect_attempted=True,
                rollback_completed=rollback_completed,
            ) from exc

        original_ids = {str(node.uuid) for node in nodes}
        resolutions = tuple(
            "NEW" if str(node.uuid) in original_ids else "RESOLVED_EXISTING"
            for node in resolved_nodes
        )
        for node, resolution in zip(resolved_nodes, resolutions, strict=True):
            attributes = dict(getattr(node, "attributes", {}) or {})
            attributes["resolution"] = resolution
            node.attributes = attributes
        return CombinedTemporalPipelineResult(
            nodes=tuple(resolved_nodes),
            edges=tuple(guarded),
            guarded_edges=tuple(guarded),
            node_resolutions=resolutions,
            graph_effect_attempted=True,
            embedding_skipped=False,
            journal_skipped=False,
            rollback_skipped=True,
        )


__all__ = [
    "CombinedTemporalPipeline",
    "CombinedTemporalPipelineError",
    "CombinedTemporalPipelineResult",
    "ExistingGraphitiPipeline",
]
