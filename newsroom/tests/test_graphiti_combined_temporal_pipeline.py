"""Provider-free contract tests for the existing Graphiti pipeline adapter."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from newsroom.graphiti_adapter import real
from newsroom.graphiti_adapter.combined_temporal_pipeline import (
    CombinedTemporalPipelineError,
    ExistingGraphitiPipeline,
)
from newsroom.graphiti_adapter.neo4j_guard import GuardState


class _Guard:
    def __init__(self, state: GuardState = GuardState.CREATED) -> None:
        self.calls: list[str] = []
        self.state = state

    async def begin(self) -> Any:
        self.calls.append("begin")
        return SimpleNamespace(state=self.state)

    async def record_pending_telemetry(self, **_kwargs: Any) -> None:
        self.calls.append("telemetry")

    async def restore_preexisting(self) -> None:
        self.calls.append("restore")

    async def complete(self, receipt: dict[str, object]) -> None:
        assert receipt["provider_attempt_number"] == 1
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


def _pipeline(
    guard: _Guard,
    *,
    fail_embedding: bool = False,
) -> ExistingGraphitiPipeline:
    async def resolve_nodes(
        _nodes: list[Any],
    ) -> tuple[list[Any], dict[str, str], list[tuple[Any, Any]]]:
        guard.calls.append("resolve")
        return (
            [_node("existing-source"), _node("existing-target")],
            {
                "local-source": "existing-source",
                "local-target": "existing-target",
            },
            [],
        )

    def resolve_pointers(edges: list[Any], uuid_map: dict[str, str]) -> list[Any]:
        guard.calls.append("pointers")
        for edge in edges:
            edge.source_node_uuid = uuid_map[edge.source_node_uuid]
            edge.target_node_uuid = uuid_map[edge.target_node_uuid]
        return edges

    async def create_embeddings(_embedder: Any, edges: list[Any]) -> None:
        guard.calls.append("embed")
        if fail_embedding:
            raise RuntimeError("embedding failed")
        for edge in edges:
            edge.fact_embedding = [0.25]

    async def persist_graph(_nodes: list[Any], _edges: list[Any]) -> None:
        guard.calls.append("persist")

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


def test_existing_pipeline_resolves_embeds_and_completes_durable_journal() -> None:
    guard = _Guard()
    edge = _edge()
    result = _pipeline(guard).execute(
        nodes=(_node("local-source"), _node("local-target")),
        edges=(edge,),
        receipt={"provider_attempt_number": 1},
    )

    assert guard.calls == [
        "begin",
        "resolve",
        "pointers",
        "embed",
        "persist",
        "telemetry",
        "restore",
        "complete",
    ]
    assert result.node_resolutions == (
        "RESOLVED_EXISTING",
        "RESOLVED_EXISTING",
    )
    assert edge.source_node_uuid == "existing-source"
    assert edge.target_node_uuid == "existing-target"
    assert edge.fact_embedding == [0.25]
    assert result.graph_effect_attempted is True
    assert result.rollback_skipped is True


def test_existing_pipeline_rolls_back_embedding_failure() -> None:
    guard = _Guard()
    with pytest.raises(CombinedTemporalPipelineError) as captured:
        _pipeline(guard, fail_embedding=True).execute(
            nodes=(_node("local-source"), _node("local-target")),
            edges=(_edge(),),
            receipt={"provider_attempt_number": 1},
        )

    assert captured.value.graph_effect_attempted is True
    assert captured.value.rollback_completed is True
    assert guard.calls == ["begin", "resolve", "pointers", "embed", "rollback"]


def test_existing_pipeline_does_not_roll_back_a_complete_marker() -> None:
    guard = _Guard(GuardState.COMPLETE)
    with pytest.raises(CombinedTemporalPipelineError) as captured:
        _pipeline(guard).execute(
            nodes=(_node("local-source"), _node("local-target")),
            edges=(_edge(),),
            receipt={},
        )

    assert captured.value.graph_effect_attempted is True
    assert captured.value.rollback_completed is False
    assert guard.calls == ["begin"]


def test_real_factory_uses_graphiti_types_and_bulk_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = _Guard()
    calls: list[str] = []

    class RuntimeObject:
        def __init__(self, **values: Any) -> None:
            vars(self).update(values)

    async def resolve_nodes(
        _clients: Any,
        nodes: list[Any],
        _episode: Any,
        _previous: list[Any],
        _entity_types: Any,
    ) -> tuple[list[Any], dict[str, str], list[tuple[Any, Any]]]:
        calls.append("resolve")
        return nodes, {node.uuid: node.uuid for node in nodes}, []

    def resolve_pointers(edges: list[Any], _uuid_map: dict[str, str]) -> list[Any]:
        calls.append("pointers")
        return edges

    async def create_embeddings(_embedder: Any, edges: list[Any]) -> None:
        calls.append("embed")
        for edge in edges:
            edge.fact_embedding = [0.5]

    runtime = SimpleNamespace(
        EntityNode=RuntimeObject,
        EntityEdge=RuntimeObject,
        resolve_extracted_nodes=resolve_nodes,
        resolve_edge_pointers=resolve_pointers,
        create_entity_edge_embeddings=create_embeddings,
    )
    monkeypatch.setattr(real, "_load_graphiti", lambda: runtime)

    class Graphiti:
        clients = SimpleNamespace(
            llm_client=SimpleNamespace(invocations=[]),
            embedder=SimpleNamespace(receipt=lambda: {"usage_basis": "TEST"}),
        )

        async def _process_episode_data(self, *args: Any) -> None:
            assert isinstance(args[1][0], RuntimeObject)
            assert isinstance(args[2][0], RuntimeObject)
            calls.append("persist")

    now = datetime.now(tz=UTC)
    proposal_nodes = tuple(
        SimpleNamespace(
            uuid=value,
            name=value,
            group_id="test",
            labels=["Entity"],
            created_at=now,
            summary="",
            attributes={},
        )
        for value in ("source", "target")
    )
    proposal_edge = SimpleNamespace(
        uuid="edge",
        group_id="test",
        source_node_uuid="source",
        target_node_uuid="target",
        created_at=now,
        name="ASKED_ABOUT",
        fact="asked about",
        fact_embedding=None,
        episodes=["episode"],
        expired_at=None,
        valid_at=None,
        invalid_at=None,
        reference_time=now,
        attributes={},
    )
    pipeline = real.combined_temporal_pipeline_for(
        graphiti=Graphiti(),
        guard=guard,  # type: ignore[arg-type]
        episode=SimpleNamespace(group_id="test"),
    )
    result = pipeline.execute(
        nodes=proposal_nodes,
        edges=(proposal_edge,),
        receipt={},
    )

    assert calls == ["resolve", "pointers", "embed", "persist"]
    assert isinstance(result.nodes[0], RuntimeObject)
    assert isinstance(result.edges[0], RuntimeObject)
    assert result.edges[0].fact_embedding == [0.5]
