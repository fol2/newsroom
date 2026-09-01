"""Ordinary F1 lock for live 13690 GuardError after CanonicalizationError."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from newsroom.authority.canonical import CanonicalizationError, canonical_json_bytes
from newsroom.graphiti_adapter.combined_temporal_pipeline import (
    CombinedTemporalPipelineError,
    ExistingGraphitiPipeline,
)
from newsroom.graphiti_adapter.neo4j_guard import GuardError, GuardState


class _ClaimingGuard:
    """Marker lifecycle that matches Neo4jMutationGuard claim consumption."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.marker_state: GuardState | None = None
        self.recovery_reason: str | None = None
        self.snapshot_rows: list[str] = []
        self.completed_receipt: dict[str, object] | None = None

    async def completed_raw(self) -> dict[str, object]:
        self.calls.append("completed")
        assert self.completed_receipt is not None
        return self.completed_receipt

    async def begin(self) -> Any:
        self.calls.append("begin")
        self.marker_state = GuardState.PENDING
        self.snapshot_rows = ["preexisting"]
        self.recovery_reason = None
        return SimpleNamespace(
            state=GuardState.CREATED,
            chat_invocations=({"model": "retained"},),
            embedding_usage={"usage_basis": "RETAINED"},
        )

    async def record_pending_telemetry(self, **_kwargs: Any) -> None:
        self.calls.append("telemetry")
        if self.marker_state is not GuardState.PENDING:
            raise GuardError("Graphiti telemetry lost its pending claim")

    @asynccontextmanager
    async def fenced_graph_mutation(self) -> AsyncIterator[None]:
        self.calls.append("fence")
        try:
            yield
        finally:
            self.calls.append("unfence")

    async def restore_preexisting(self) -> None:
        self.calls.append("restore")

    async def discard_uncommitted_generation(self) -> None:
        self.calls.append("discard")
        if self.marker_state is not GuardState.PENDING:
            raise GuardError(
                "Graphiti marker cannot discard an uncommitted generation"
            )

    async def complete(self, receipt: dict[str, object]) -> None:
        if self.marker_state is not GuardState.PENDING:
            raise GuardError("Graphiti completion marker transition did not commit")
        assert receipt["provider_attempt_number"] == 1
        self.completed_receipt = dict(receipt)
        self.marker_state = GuardState.COMPLETE
        self.snapshot_rows = []
        self.calls.append("complete")

    async def rollback_pending(self, **kwargs: Any) -> bool:
        self.calls.append("rollback")
        if self.marker_state is not GuardState.PENDING:
            raise GuardError("Graphiti marker cannot enter rollback")
        self.marker_state = GuardState.RECOVERED_AMBIGUOUS
        self.recovery_reason = str(kwargs.get("reason") or "")
        self.snapshot_rows = []
        return True


class _NonClaimingGuard:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.completed_receipt: dict[str, object] | None = None

    async def completed_raw(self) -> dict[str, object]:
        assert self.completed_receipt is not None
        return self.completed_receipt

    async def begin(self) -> Any:
        self.calls.append("begin")
        return SimpleNamespace(
            state=GuardState.CREATED,
            chat_invocations=({"model": "retained"},),
            embedding_usage={"usage_basis": "RETAINED"},
        )

    async def record_pending_telemetry(self, **_kwargs: Any) -> None:
        self.calls.append("telemetry")

    @asynccontextmanager
    async def fenced_graph_mutation(self) -> AsyncIterator[None]:
        self.calls.append("fence")
        try:
            yield
        finally:
            self.calls.append("unfence")

    async def restore_preexisting(self) -> None:
        self.calls.append("restore")

    async def discard_uncommitted_generation(self) -> None:
        self.calls.append("discard")

    async def complete(self, receipt: dict[str, object]) -> None:
        self.completed_receipt = dict(receipt)
        self.calls.append("complete")

    async def rollback_pending(self, **_kwargs: Any) -> bool:
        self.calls.append("rollback")
        return True


def _node(uuid: str) -> Any:
    return SimpleNamespace(uuid=uuid, attributes={})


def _edge() -> Any:
    return SimpleNamespace(
        source_node_uuid="local-source",
        target_node_uuid="local-target",
        name="ASKED_ABOUT",
        fact="asked about",
    )


def _pipeline(guard: object) -> ExistingGraphitiPipeline:
    async def resolve_nodes(
        _nodes: list[Any],
    ) -> tuple[list[Any], dict[str, str], list[tuple[Any, Any]]]:
        original_ids = [str(node.uuid) for node in _nodes]
        resolved = [SimpleNamespace(**vars(node)) for node in _nodes]
        resolved[0].uuid = "existing-source"
        resolved[1].uuid = "existing-target"
        return (
            resolved,
            {
                original_ids[0]: "existing-source",
                original_ids[1]: "existing-target",
            },
            [],
        )

    def resolve_pointers(edges: list[Any], uuid_map: dict[str, str]) -> list[Any]:
        for edge in edges:
            edge.source_node_uuid = uuid_map[edge.source_node_uuid]
            edge.target_node_uuid = uuid_map[edge.target_node_uuid]
        return edges

    async def create_embeddings(_embedder: Any, edges: list[Any]) -> None:
        for edge in edges:
            edge.fact_embedding = [0.25]

    async def persist_graph(_nodes: list[Any], _edges: list[Any]) -> None:
        return None

    return ExistingGraphitiPipeline(
        guard=guard,  # type: ignore[arg-type]
        resolve_nodes=resolve_nodes,
        resolve_pointers=resolve_pointers,
        create_embeddings=create_embeddings,
        persist_graph=persist_graph,
        embedder=object(),
        run_async=asyncio.run,
        chat_receipt=lambda: [{"model": "composer-2.5"}],
        embedding_receipt=lambda: {"usage_basis": "PROVIDER_REPORTED"},
    )


def test_claiming_guard_float_fact_embedding_seals_without_recovered_ambiguous() -> None:
    """Live 13690: rollback-then-seal left RECOVERED_AMBIGUOUS and GuardError."""

    guard = _ClaimingGuard()
    persist_calls: list[object] = []
    sealed: list[tuple[list[object], list[object]]] = []
    pipeline = _pipeline(guard)

    async def persist_graph(nodes: list[Any], edges: list[Any]) -> None:
        persist_calls.append((list(nodes), list(edges)))
        guard.calls.append("persist")

    def complete_receipt(
        nodes: list[Any], edges: list[Any], receipt: object
    ) -> dict[str, object]:
        payload = dict(receipt)  # type: ignore[arg-type]
        sealed.append((list(nodes), list(edges)))
        canonical_json_bytes(payload)
        return payload

    pipeline.persist_graph = persist_graph
    pipeline.complete_receipt = complete_receipt
    edge = _edge()
    edge.uuid = "edge-1"
    result = pipeline.execute(
        nodes=(_node("local-source"), _node("local-target")),
        edges=(edge,),
        receipt={
            "provider_attempt_number": 1,
            "proposal_receipt": {
                "entity_mentions": [{"local_id": 0}, {"local_id": 1}],
                "relation_proposals": [{"local_id": 0}],
            },
        },
    )

    assert persist_calls != []
    assert "rollback" not in guard.calls
    assert "discard" in guard.calls
    assert "complete" in guard.calls
    assert guard.marker_state is GuardState.COMPLETE
    assert guard.recovery_reason is None
    assert guard.snapshot_rows == []
    assert sealed[-1] == ([], [])
    assert result.completed_receipt is not None
    assert result.completed_receipt["zero_proposal_effect"] == "EXPLICIT"
    canonical_json_bytes(dict(result.completed_receipt))


def test_non_fact_embedding_canonicalization_error_stays_fail_closed() -> None:
    """Other CanonicalizationError must not be sealed as explicit zero."""

    guard = _NonClaimingGuard()
    pipeline = _pipeline(guard)
    edge = _edge()
    edge.uuid = "edge-1"

    def complete_receipt(
        _nodes: list[Any], _edges: list[Any], _receipt: object
    ) -> dict[str, object]:
        raise CanonicalizationError("unsupported value type at $.other")

    pipeline.complete_receipt = complete_receipt
    with pytest.raises(CombinedTemporalPipelineError):
        pipeline.execute(
            nodes=(_node("local-source"), _node("local-target")),
            edges=(edge,),
            receipt={
                "provider_attempt_number": 1,
                "proposal_receipt": {
                    "entity_mentions": [{"local_id": 0}, {"local_id": 1}],
                    "relation_proposals": [{"local_id": 0}],
                },
            },
        )

    assert "rollback" in guard.calls
    assert "complete" not in guard.calls
    assert "discard" not in guard.calls
