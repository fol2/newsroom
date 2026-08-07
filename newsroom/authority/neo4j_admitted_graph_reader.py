"""Fixed read-only Neo4j port for Increment 5B4 admitted-graph retrieval.

The public surface accepts only an exact generation, a canonical root or a
bounded frontier, the reviewed temporal values and the remaining timeout.  All
Cypher, labels, relationship types, directions, ordering and limits are
repository-owned constants.  No driver, session, transaction or write
capability crosses the port.
"""

from __future__ import annotations

import threading
import time
from contextlib import AbstractContextManager
from typing import Any, Callable, Iterable, Mapping, Protocol

from newsroom.increment5.admitted_graph_retriever import (
    ALLOWED_NODE_LABELS,
    ALLOWED_PREDICATES,
    GRAPH_MAX_FANOUT,
    AdmittedGraphContractError,
    AdmittedGraphPortError,
    AdmittedGraphPortTimeout,
    GraphProjectionEdge,
    GraphProjectionNode,
)


_ROOT_CYPHER = """
MATCH (n {generation_id: $generation_id, canonical_id: $canonical_id})
WHERE any(label_name IN labels(n) WHERE label_name IN $allowed_labels)
RETURN
  n.canonical_id AS canonical_id,
  n.identity_digest AS identity_digest,
  labels(n) AS labels
ORDER BY n.canonical_id ASC, n.identity_digest ASC
LIMIT 2
""".strip()

_EXPAND_CYPHER = """
UNWIND $frontier_ids AS requested_frontier_id
MATCH (frontier {generation_id: $generation_id, canonical_id: requested_frontier_id})
WHERE any(label_name IN labels(frontier) WHERE label_name IN $allowed_labels)
MATCH (frontier)-[relation]-(other {generation_id: $generation_id})
WHERE
  type(relation) IN $allowed_predicates
  AND relation.generation_id = $generation_id
  AND any(label_name IN labels(other) WHERE label_name IN $allowed_labels)
  AND relation.valid_from <= $query_valid_time
  AND $query_valid_time < relation.valid_to
  AND relation.observed_at >= $temporal_lower_bound
  AND relation.observed_at <= $query_valid_time
RETURN
  requested_frontier_id AS frontier_id,
  relation.relation_id AS relation_id,
  startNode(relation).canonical_id AS source_id,
  endNode(relation).canonical_id AS target_id,
  type(relation) AS predicate,
  labels(startNode(relation)) AS source_labels,
  labels(endNode(relation)) AS target_labels,
  relation.valid_from AS valid_from,
  relation.valid_to AS valid_to,
  relation.observed_at AS observed_at
ORDER BY
  frontier_id ASC,
  predicate ASC,
  source_id ASC,
  target_id ASC,
  relation_id ASC
LIMIT $absolute_row_limit
""".strip()


class _Result(Protocol):
    def __iter__(self) -> Iterable[Mapping[str, Any]]:
        ...


class _Transaction(Protocol):
    def run(self, query: str, **parameters: object) -> _Result:
        ...


class _Session(AbstractContextManager[Any], Protocol):
    def execute_read(
        self,
        work: Callable[[_Transaction], object],
        **transaction_config: object,
    ) -> object:
        ...


class _Driver(Protocol):
    def session(self, **config: object) -> _Session:
        ...


def _record_value(record: Mapping[str, Any], name: str) -> Any:
    try:
        return record[name]
    except (KeyError, TypeError) as exc:
        raise AdmittedGraphPortError(f"Neo4j record is missing {name}") from exc


def _text(record: Mapping[str, Any], name: str) -> str:
    value = _record_value(record, name)
    if not isinstance(value, str):
        raise AdmittedGraphPortError(f"Neo4j field {name} must be text")
    return value


def _labels(record: Mapping[str, Any], name: str) -> tuple[str, ...]:
    value = _record_value(record, name)
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(item, str) for item in value
    ):
        raise AdmittedGraphPortError(f"Neo4j field {name} must be a label sequence")
    return tuple(sorted(set(value)))


class Neo4jAdmittedGraphReadPort:
    """Lock-bounded fixed-operation Neo4j read port.

    `driver` is deliberately typed as a minimal protocol.  Construction of the
    authenticated least-privileged driver remains outside this class and is
    qualified in 5E; this port never receives authentication material and never exposes the
    driver to the retriever.
    """

    def __init__(
        self,
        driver: _Driver,
        *,
        database: str | None = None,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self.__driver = driver
        self.__database = database
        self.__monotonic_ns = monotonic_ns
        self.__lock = threading.Lock()

    @staticmethod
    def fixed_root_cypher() -> str:
        return _ROOT_CYPHER

    @staticmethod
    def fixed_expand_cypher() -> str:
        return _EXPAND_CYPHER

    def _within_lock(
        self,
        *,
        timeout_ms: int,
        operation: Callable[[float], object],
    ) -> object:
        if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or timeout_ms <= 0:
            raise AdmittedGraphContractError("Neo4j timeout_ms must be positive")
        started = self.__monotonic_ns()
        acquired = self.__lock.acquire(timeout=timeout_ms / 1_000)
        if not acquired:
            raise AdmittedGraphPortTimeout("Neo4j adapter lock wait exhausted the budget")
        try:
            elapsed_ms = max(0, (self.__monotonic_ns() - started) // 1_000_000)
            remaining_ms = timeout_ms - elapsed_ms
            if remaining_ms <= 0:
                raise AdmittedGraphPortTimeout(
                    "Neo4j adapter lock wait exhausted the cumulative budget"
                )
            try:
                return operation(remaining_ms / 1_000)
            except AdmittedGraphPortTimeout:
                raise
            except Exception as exc:
                if exc.__class__.__name__ in {
                    "ServiceUnavailable",
                    "SessionExpired",
                    "DriverError",
                    "Neo4jError",
                    "TransactionError",
                }:
                    raise AdmittedGraphPortError("Neo4j fixed read failed") from exc
                raise
        finally:
            self.__lock.release()

    def _session(self) -> _Session:
        config: dict[str, object] = {"default_access_mode": "READ"}
        if self.__database is not None:
            config["database"] = self.__database
        return self.__driver.session(**config)

    def read_root(
        self,
        *,
        generation_id: str,
        canonical_id: str,
        timeout_ms: int,
    ) -> GraphProjectionNode | None:
        def operation(timeout_seconds: float) -> GraphProjectionNode | None:
            def work(transaction: _Transaction) -> tuple[Mapping[str, Any], ...]:
                result = transaction.run(
                    _ROOT_CYPHER,
                    generation_id=generation_id,
                    canonical_id=canonical_id,
                    allowed_labels=list(ALLOWED_NODE_LABELS),
                )
                return tuple(result)

            setattr(work, "timeout", timeout_seconds)
            with self._session() as session:
                rows = session.execute_read(work)
            if not isinstance(rows, tuple):
                raise AdmittedGraphPortError("Neo4j root read returned an invalid shape")
            if not rows:
                return None
            if len(rows) != 1:
                raise AdmittedGraphPortError("Neo4j root projection is ambiguous")
            row = rows[0]
            return GraphProjectionNode(
                generation_id=generation_id,
                canonical_id=_text(row, "canonical_id"),
                identity_digest=_text(row, "identity_digest"),
                labels=_labels(row, "labels"),
            )

        result = self._within_lock(timeout_ms=timeout_ms, operation=operation)
        if result is not None and not isinstance(result, GraphProjectionNode):
            raise AdmittedGraphPortError("Neo4j root read returned an invalid node")
        return result

    def expand_frontier(
        self,
        *,
        generation_id: str,
        frontier_ids: tuple[str, ...],
        query_valid_time: str,
        temporal_lower_bound: str,
        timeout_ms: int,
    ) -> tuple[GraphProjectionEdge, ...]:
        if not frontier_ids:
            return ()
        if len(frontier_ids) > GRAPH_MAX_FANOUT:
            raise AdmittedGraphContractError("frontier exceeds the fixed fan-out bound")
        if frontier_ids != tuple(sorted(set(frontier_ids))):
            raise AdmittedGraphContractError(
                "frontier identities must be sorted and unique"
            )
        absolute_limit = len(frontier_ids) * (GRAPH_MAX_FANOUT + 1)

        def operation(timeout_seconds: float) -> tuple[GraphProjectionEdge, ...]:
            def work(transaction: _Transaction) -> tuple[Mapping[str, Any], ...]:
                result = transaction.run(
                    _EXPAND_CYPHER,
                    generation_id=generation_id,
                    frontier_ids=list(frontier_ids),
                    allowed_labels=list(ALLOWED_NODE_LABELS),
                    allowed_predicates=list(ALLOWED_PREDICATES),
                    query_valid_time=query_valid_time,
                    temporal_lower_bound=temporal_lower_bound,
                    absolute_row_limit=absolute_limit,
                )
                return tuple(result)

            setattr(work, "timeout", timeout_seconds)
            with self._session() as session:
                rows = session.execute_read(work)
            if not isinstance(rows, tuple):
                raise AdmittedGraphPortError("Neo4j expansion returned an invalid shape")
            return tuple(
                GraphProjectionEdge(
                    generation_id=generation_id,
                    frontier_id=_text(row, "frontier_id"),
                    relation_id=_text(row, "relation_id"),
                    source_id=_text(row, "source_id"),
                    target_id=_text(row, "target_id"),
                    predicate=_text(row, "predicate"),
                    source_labels=_labels(row, "source_labels"),
                    target_labels=_labels(row, "target_labels"),
                    valid_from=_text(row, "valid_from"),
                    valid_to=_text(row, "valid_to"),
                    observed_at=_text(row, "observed_at"),
                )
                for row in rows
            )

        result = self._within_lock(timeout_ms=timeout_ms, operation=operation)
        if not isinstance(result, tuple) or not all(
            isinstance(item, GraphProjectionEdge) for item in result
        ):
            raise AdmittedGraphPortError("Neo4j expansion returned invalid edges")
        return result


__all__ = ["Neo4jAdmittedGraphReadPort"]
