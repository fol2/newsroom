from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Mapping

import pytest

from newsroom.authority.neo4j_admitted_graph_reader import Neo4jAdmittedGraphReadPort
from newsroom.increment5.admitted_graph_retriever import (
    ALLOWED_NODE_LABELS,
    ALLOWED_PREDICATES,
    GRAPH_MAX_FANOUT,
    AdmittedGraphContractError,
    AdmittedGraphPortError,
    AdmittedGraphPortTimeout,
    GraphProjectionEdge,
    GraphProjectionNode,
    canonical_node_digest,
)


GENERATION = "graph-generation-v1"
ROOT = "source:root"
VALID = "2026-08-06T08:59:00Z"
LOWER = "2026-07-06T08:59:00Z"


def query_text(query: object) -> str:
    value = getattr(query, "text", None)
    if isinstance(value, str):
        return value
    return str(query)


class FakeTransaction:
    def __init__(self, rows_by_operation: dict[str, list[dict[str, object]]]) -> None:
        self.rows_by_operation = rows_by_operation
        self.calls: list[tuple[str, dict[str, object], object]] = []

    def run(self, query: object, **parameters: object):
        text = query_text(query)
        self.calls.append((text, parameters, query))
        operation = "root" if "LIMIT 2" in text else "expand"
        return iter(self.rows_by_operation.get(operation, []))


class FakeSession:
    def __init__(self, transaction: FakeTransaction) -> None:
        self.transaction = transaction
        self.execute_calls: list[tuple[object, tuple[object, ...], dict[str, object]]] = []
        self.entered = False

    def __enter__(self) -> "FakeSession":
        self.entered = True
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.entered = False

    def execute_read(self, work, *args: object, **kwargs: object):
        self.execute_calls.append((work, args, kwargs))
        return work(self.transaction)


class FakeDriver:
    def __init__(self, rows_by_operation: dict[str, list[dict[str, object]]]) -> None:
        self.transaction = FakeTransaction(rows_by_operation)
        self.session_instance = FakeSession(self.transaction)
        self.session_configs: list[dict[str, object]] = []

    def session(self, **config: object) -> FakeSession:
        self.session_configs.append(config)
        return self.session_instance


def root_row() -> dict[str, object]:
    return {
        "canonical_id": ROOT,
        "identity_digest": canonical_node_digest(ROOT),
        "labels": ["Source"],
    }


def edge_row() -> dict[str, object]:
    return {
        "frontier_id": ROOT,
        "relation_id": "relation:root-revision",
        "source_id": ROOT,
        "target_id": "revision:one",
        "predicate": "DEVELOPMENT_OF",
        "source_labels": ["Source"],
        "target_labels": ["Revision"],
        "valid_from": "2020-01-01T00:00:00Z",
        "valid_to": "2035-01-01T00:00:00Z",
        "observed_at": "2026-08-01T00:00:00Z",
    }


def test_fixed_queries_are_read_only_and_have_no_mutation_clause() -> None:
    combined = "\n".join(
        (
            Neo4jAdmittedGraphReadPort.fixed_root_cypher(),
            Neo4jAdmittedGraphReadPort.fixed_expand_cypher(),
        )
    ).upper()
    for forbidden in (
        " CREATE ",
        " MERGE ",
        " SET ",
        " DELETE ",
        " DETACH ",
        " REMOVE ",
        " DROP ",
        " CALL ",
        " LOAD CSV ",
    ):
        assert forbidden not in f" {combined} "
    assert "MATCH" in combined
    assert "UNWIND" in combined


def test_root_read_uses_only_repository_owned_allowlist_and_read_session() -> None:
    driver = FakeDriver({"root": [root_row()]})
    port = Neo4jAdmittedGraphReadPort(driver, database="neo4j", monotonic_ns=lambda: 0)
    result = port.read_root(
        generation_id=GENERATION,
        canonical_id=ROOT,
        timeout_ms=5_000,
    )
    assert result == GraphProjectionNode(
        generation_id=GENERATION,
        canonical_id=ROOT,
        identity_digest=canonical_node_digest(ROOT),
        labels=("Source",),
    )
    assert driver.session_configs == [
        {"default_access_mode": "READ", "database": "neo4j"}
    ]
    text, params, query = driver.transaction.calls[0]
    assert text == Neo4jAdmittedGraphReadPort.fixed_root_cypher()
    assert params == {
        "generation_id": GENERATION,
        "canonical_id": ROOT,
        "allowed_labels": list(ALLOWED_NODE_LABELS),
    }
    assert getattr(query, "timeout", 5.0) is not None
    assert driver.session_instance.execute_calls[0][2] == {
        "timeout": pytest.approx(5.0)
    }


def test_root_missing_returns_none() -> None:
    port = Neo4jAdmittedGraphReadPort(
        FakeDriver({"root": []}),
        monotonic_ns=lambda: 0,
    )
    assert (
        port.read_root(
            generation_id=GENERATION,
            canonical_id=ROOT,
            timeout_ms=5_000,
        )
        is None
    )


def test_root_ambiguity_fails_closed() -> None:
    port = Neo4jAdmittedGraphReadPort(
        FakeDriver({"root": [root_row(), root_row()]}),
        monotonic_ns=lambda: 0,
    )
    with pytest.raises(AdmittedGraphPortError, match="ambiguous"):
        port.read_root(
            generation_id=GENERATION,
            canonical_id=ROOT,
            timeout_ms=5_000,
        )


def test_frontier_expansion_uses_fixed_predicates_labels_order_and_limit() -> None:
    driver = FakeDriver({"expand": [edge_row()]})
    port = Neo4jAdmittedGraphReadPort(driver, monotonic_ns=lambda: 0)
    result = port.expand_frontier(
        generation_id=GENERATION,
        frontier_ids=(ROOT,),
        query_valid_time=VALID,
        temporal_lower_bound=LOWER,
        timeout_ms=5_000,
    )
    assert result == (
        GraphProjectionEdge(
            generation_id=GENERATION,
            frontier_id=ROOT,
            relation_id="relation:root-revision",
            source_id=ROOT,
            target_id="revision:one",
            predicate="DEVELOPMENT_OF",
            source_labels=("Source",),
            target_labels=("Revision",),
            valid_from="2020-01-01T00:00:00Z",
            valid_to="2035-01-01T00:00:00Z",
            observed_at="2026-08-01T00:00:00Z",
        ),
    )
    text, params, _query = driver.transaction.calls[0]
    assert text == Neo4jAdmittedGraphReadPort.fixed_expand_cypher()
    assert params["generation_id"] == GENERATION
    assert params["frontier_ids"] == [ROOT]
    assert params["allowed_labels"] == list(ALLOWED_NODE_LABELS)
    assert params["allowed_predicates"] == list(ALLOWED_PREDICATES)
    assert params["query_valid_time"] == VALID
    assert params["temporal_lower_bound"] == LOWER
    assert params["absolute_row_limit"] == GRAPH_MAX_FANOUT + 1


def test_empty_frontier_returns_without_opening_session() -> None:
    driver = FakeDriver({})
    port = Neo4jAdmittedGraphReadPort(driver, monotonic_ns=lambda: 0)
    assert (
        port.expand_frontier(
            generation_id=GENERATION,
            frontier_ids=(),
            query_valid_time=VALID,
            temporal_lower_bound=LOWER,
            timeout_ms=5_000,
        )
        == ()
    )
    assert driver.session_configs == []


def test_frontier_must_be_sorted_unique_and_bounded() -> None:
    port = Neo4jAdmittedGraphReadPort(FakeDriver({}), monotonic_ns=lambda: 0)
    with pytest.raises(AdmittedGraphContractError, match="sorted and unique"):
        port.expand_frontier(
            generation_id=GENERATION,
            frontier_ids=("source:z", "source:a"),
            query_valid_time=VALID,
            temporal_lower_bound=LOWER,
            timeout_ms=5_000,
        )
    with pytest.raises(AdmittedGraphContractError, match="fan-out"):
        port.expand_frontier(
            generation_id=GENERATION,
            frontier_ids=tuple(f"source:{index:02d}" for index in range(33)),
            query_valid_time=VALID,
            temporal_lower_bound=LOWER,
            timeout_ms=5_000,
        )


def test_malformed_root_and_edge_records_fail_closed() -> None:
    bad_root = root_row()
    bad_root.pop("identity_digest")
    with pytest.raises(AdmittedGraphPortError, match="missing identity_digest"):
        Neo4jAdmittedGraphReadPort(
            FakeDriver({"root": [bad_root]}),
            monotonic_ns=lambda: 0,
        ).read_root(
            generation_id=GENERATION,
            canonical_id=ROOT,
            timeout_ms=5_000,
        )

    bad_edge = edge_row()
    bad_edge["source_labels"] = "Source"
    with pytest.raises(AdmittedGraphPortError, match="label sequence"):
        Neo4jAdmittedGraphReadPort(
            FakeDriver({"expand": [bad_edge]}),
            monotonic_ns=lambda: 0,
        ).expand_frontier(
            generation_id=GENERATION,
            frontier_ids=(ROOT,),
            query_valid_time=VALID,
            temporal_lower_bound=LOWER,
            timeout_ms=5_000,
        )


def test_lock_wait_is_inside_timeout_budget() -> None:
    port = Neo4jAdmittedGraphReadPort(FakeDriver({}), monotonic_ns=lambda: 0)
    lock = getattr(port, "_Neo4jAdmittedGraphReadPort__lock")
    assert lock.acquire(blocking=False)
    try:
        with pytest.raises(AdmittedGraphPortTimeout, match="lock wait"):
            port.read_root(
                generation_id=GENERATION,
                canonical_id=ROOT,
                timeout_ms=1,
            )
    finally:
        lock.release()


def test_elapsed_lock_time_reduces_query_timeout() -> None:
    values = iter((0, 2_000_000))
    driver = FakeDriver({"root": [root_row()]})
    port = Neo4jAdmittedGraphReadPort(driver, monotonic_ns=lambda: next(values))
    port.read_root(
        generation_id=GENERATION,
        canonical_id=ROOT,
        timeout_ms=5,
    )
    query = driver.transaction.calls[0][2]
    timeout = getattr(query, "timeout", None)
    if timeout is not None:
        assert timeout == pytest.approx(0.003)


def test_non_positive_timeout_is_rejected() -> None:
    port = Neo4jAdmittedGraphReadPort(FakeDriver({}), monotonic_ns=lambda: 0)
    with pytest.raises(AdmittedGraphContractError, match="positive"):
        port.read_root(
            generation_id=GENERATION,
            canonical_id=ROOT,
            timeout_ms=0,
        )


def test_driver_session_transaction_and_raw_query_do_not_cross_public_surface() -> None:
    public_methods = {
        name
        for name, value in inspect.getmembers(
            Neo4jAdmittedGraphReadPort,
            predicate=inspect.isfunction,
        )
        if not name.startswith("_")
    }
    assert public_methods == {
        "expand_frontier",
        "fixed_expand_cypher",
        "fixed_root_cypher",
        "read_root",
    }
    signatures = {
        name: set(inspect.signature(getattr(Neo4jAdmittedGraphReadPort, name)).parameters)
        for name in ("read_root", "expand_frontier")
    }
    forbidden = {"query", "cypher", "predicate", "label", "direction", "session", "driver"}
    assert signatures["read_root"].isdisjoint(forbidden)
    assert signatures["expand_frontier"].isdisjoint(forbidden)


def test_adapter_imports_no_write_capability_or_credentials() -> None:
    import newsroom.authority.neo4j_admitted_graph_reader as module

    source = inspect.getsource(module).lower()
    assert "execute_write" not in source
    assert "write_transaction" not in source
    assert "password" not in source
    assert "credential" not in source
    assert "auth=" not in source


def test_fixed_expand_query_closes_the_observation_window() -> None:
    text = Neo4jAdmittedGraphReadPort.fixed_expand_cypher()
    assert "relation.observed_at >= $temporal_lower_bound" in text
    assert "relation.observed_at <= $query_valid_time" in text
