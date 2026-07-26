from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from newsroom.projection import INTEGRATED_FIXTURE_V2_PROJECTION
from newsroom.projection.neo4j._retrieval_adapter import (
    _ADMITTED_GRAPH_QUERY_TEMPLATE,
    _FULLTEXT_QUERY,
    _VECTOR_QUERY,
    _HybridRetrievalNeo4jAdapter,
    _exact_query,
)
from newsroom.projection.neo4j.models import (
    NEO4J_B2_DRIVER_VERSION,
    Neo4jCompatibilityError,
    Neo4jConnectionError,
    Neo4jIdentityConflict,
    Neo4jProjectorConfig,
    Neo4jReadError,
)
from newsroom.retrieval import (
    HYBRID_FIXTURE_POLICY_V1,
    INTEGRATED_FIXTURE_V2_RETRIEVAL,
    RetrievalBranch,
)

from .complete_projection_2b_helpers import complete_identity


_QUERY_DIGEST = "sha256:" + "4" * 64
_PRIOR_ROOT = "candidate:00000000-0000-4000-8000-000000002012"


class _Transaction:
    def __init__(self, rows: Callable[[str, dict[str, object]], list[dict[str, object]]]) -> None:
        self._rows = rows
        self.statements: list[tuple[str, dict[str, object]]] = []

    def run(self, statement: str, parameters: dict[str, object] | None = None):
        values = parameters or {}
        self.statements.append((statement, values))
        return list(self._rows(statement, values))


class _Session:
    def __init__(self, transaction: _Transaction) -> None:
        self.transaction = transaction

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute_read(self, callback, *args):
        return callback(self.transaction, *args)


class _Driver:
    def __init__(self, transaction: _Transaction) -> None:
        self.transaction = transaction
        self.databases: list[str] = []
        self.close_count = 0

    def session(self, *, database: str):
        self.databases.append(database)
        return _Session(self.transaction)

    def close(self) -> None:
        self.close_count += 1


class _Clock:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> int:
        self.value += 1_000_000
        return self.value


class _SequenceClock:
    def __init__(self, values: tuple[int, ...]) -> None:
        self._values = iter(values)

    def __call__(self) -> int:
        return next(self._values)


class _UnitOfWorkFactory:
    def __init__(self) -> None:
        self.configurations: list[tuple[float, dict[str, object]]] = []

    def __call__(self, *, timeout: float, metadata: dict[str, object]):
        self.configurations.append((timeout, dict(metadata)))

        def decorate(callback):
            return callback

        return decorate


def _rows(statement: str, parameters: dict[str, object]) -> list[dict[str, object]]:
    if "dbms.components" in statement:
        assert parameters == {}
        return [{"version": "2026.06.0", "edition": "community"}]
    assert parameters["limit"] == 8
    if "revision_id IN $revision_ids" in statement:
        return [
            {
                "passage_id": "ifv2-prior-en",
                "source_identity": "00000000-0000-4000-8000-000000002004",
                "score": 1.0,
            },
            {
                "passage_id": "ifv2-prior-zh-hk",
                "source_identity": "00000000-0000-4000-8000-000000002004",
                "score": 1.0,
            },
        ]
    if "DEVELOPMENT_OF*1..2" in statement:
        assert parameters["fanout"] == 32
        return [
            {
                "target_id": "00000000-0000-4000-8000-000000002010",
                "relation_keys": ["sha256:" + "7" * 64],
                "depth": 1,
                "score": 1.0,
            }
        ]
    if "db.index.fulltext.queryNodes" in statement:
        return [
            {"passage_id": "ifv2-new-en", "score": 7.0},
            {"passage_id": "ifv2-prior-en", "score": 4.0},
            {"passage_id": "ifv2-distinct-jurisdiction", "score": 1.0},
        ]
    if "db.index.vector.queryNodes" in statement:
        assert len(parameters["vector"]) == 16
        return [
            {"passage_id": "ifv2-new-en", "score": 1.0},
            {"passage_id": "ifv2-new-zh-hk", "score": 0.99},
            {"passage_id": "ifv2-incompatible-formal-id", "score": 0.98},
            {"passage_id": "ifv2-prior-zh-hk", "score": 0.75},
        ]
    raise AssertionError("unexpected query")


def _adapter(rows=_rows, *, clock=None):
    transaction = _Transaction(rows)
    driver = _Driver(transaction)
    unit_of_work = _UnitOfWorkFactory()
    adapter = _HybridRetrievalNeo4jAdapter(
        driver=driver,
        config=Neo4jProjectorConfig(
            uri="bolt://localhost:7687",
            database="neo4j",
            username="newsroom_projector",
            password="fixture-password",
        ),
        driver_version=NEO4J_B2_DRIVER_VERSION,
        monotonic_ns=clock or _Clock(),
        unit_of_work_factory=unit_of_work,
    )
    return adapter, driver, transaction, unit_of_work


def test_adapter_executes_four_fixed_server_owned_queries_once() -> None:
    adapter, driver, transaction, unit_of_work = _adapter()

    executions = adapter.run_bounded_hybrid_branches(
        identity=complete_identity(),
        fixture=INTEGRATED_FIXTURE_V2_PROJECTION,
        retrieval_contract=INTEGRATED_FIXTURE_V2_RETRIEVAL,
        policy=HYBRID_FIXTURE_POLICY_V1,
        query_digest=_QUERY_DIGEST,
    )

    assert tuple(item.branch for item in executions) == tuple(RetrievalBranch)
    assert [len(item.hits) for item in executions] == [2, 1, 3, 4]
    assert driver.databases == ["neo4j"]
    assert len(transaction.statements) == 5
    assert [item[0] for item in unit_of_work.configurations] == pytest.approx(
        [4.999, 4.997, 4.995, 4.993, 4.991]
    )
    assert [item[1] for item in unit_of_work.configurations] == [
        {
            "newsroom_tool": "find_related_event_candidates",
            "newsroom_branch": branch,
        }
        for branch in ("COMPATIBILITY", *(item.value for item in RetrievalBranch))
    ]
    statements = [item[0] for item in transaction.statements]
    assert "dbms.components" in statements[0]
    assert "revision_id IN $revision_ids" in statements[1]
    assert "DEVELOPMENT_OF*1..2" in statements[2]
    assert "db.index.fulltext.queryNodes" in statements[3]
    assert "db.index.vector.queryNodes" in statements[4]
    assert all("$limit" in statement for statement in statements[1:])
    assert all("CALLER" not in statement.upper() for statement in statements)
    assert executions[0].hits[0].dependency_root_id == _PRIOR_ROOT
    assert executions[0].hits[0].source_kind == "GOVERNED_REVISION"
    assert executions[0].hits[0].source_identity.endswith("2004")
    assert executions[1].hits[0].dependency_root_id == _PRIOR_ROOT
    assert executions[1].hits[0].source_identity.startswith("sha256:")
    assert executions[2].query_id == "fixture-fulltext-en-update"
    assert executions[3].query_id == "fixture-vector-new-en"


def test_one_total_deadline_prevents_starting_a_later_branch() -> None:
    clock = _SequenceClock(
        (
            0,
            0,
            100_000_000,
            4_900_000_000,
            5_000_000_000,
            5_000_000_000,
        )
    )
    adapter, _driver, transaction, unit_of_work = _adapter(clock=clock)

    with pytest.raises(Neo4jReadError, match="exhausted"):
        adapter.run_bounded_hybrid_branches(
            identity=complete_identity(),
            fixture=INTEGRATED_FIXTURE_V2_PROJECTION,
            retrieval_contract=INTEGRATED_FIXTURE_V2_RETRIEVAL,
            policy=HYBRID_FIXTURE_POLICY_V1,
            query_digest=_QUERY_DIGEST,
        )

    assert len(transaction.statements) == 2
    assert unit_of_work.configurations == [
        (
            5.0,
            {
                "newsroom_tool": "find_related_event_candidates",
                "newsroom_branch": "COMPATIBILITY",
            },
        ),
        (
            0.1,
            {
                "newsroom_tool": "find_related_event_candidates",
                "newsroom_branch": RetrievalBranch.EXACT.value,
            },
        ),
    ]


def test_queries_fix_relation_type_depth_and_generation_names() -> None:
    names = __import__(
        "newsroom.projection.neo4j.complete_models", fromlist=["complete_generation_names"]
    ).complete_generation_names(
        complete_identity(),
        INTEGRATED_FIXTURE_V2_PROJECTION.fulltext_contract,
        INTEGRATED_FIXTURE_V2_PROJECTION.vector_contract,
    )

    exact = _exact_query(names)
    assert names.document_label in exact
    assert "DEVELOPMENT_OF*1..2" in _ADMITTED_GRAPH_QUERY_TEMPLATE
    assert "relation.trust_scope = 'ADMITTED'" in _ADMITTED_GRAPH_QUERY_TEMPLATE
    assert "relation.predicate = 'DEVELOPMENT_OF'" in _ADMITTED_GRAPH_QUERY_TEMPLATE
    assert "$index_name" in _FULLTEXT_QUERY and "$query" in _FULLTEXT_QUERY
    assert "$index_name" in _VECTOR_QUERY and "$vector" in _VECTOR_QUERY
    for forbidden in ("caller_label", "caller_predicate", "caller_cypher"):
        assert forbidden not in "\n".join((exact, _ADMITTED_GRAPH_QUERY_TEMPLATE, _FULLTEXT_QUERY, _VECTOR_QUERY))


def test_unknown_projection_result_fails_closed() -> None:
    def rows(statement: str, parameters: dict[str, object]):
        if "revision_id IN $revision_ids" in statement:
            return [{"passage_id": "unknown-passage", "score": 1.0}]
        return _rows(statement, parameters)

    adapter, _driver, _transaction, _unit_of_work = _adapter(rows)
    with pytest.raises(Neo4jIdentityConflict, match="checked fixture"):
        adapter.run_bounded_hybrid_branches(
            identity=complete_identity(),
            fixture=INTEGRATED_FIXTURE_V2_PROJECTION,
            retrieval_contract=INTEGRATED_FIXTURE_V2_RETRIEVAL,
            policy=HYBRID_FIXTURE_POLICY_V1,
            query_digest=_QUERY_DIGEST,
        )


def test_graph_result_requires_checked_target_and_admitted_relation_evidence() -> None:
    def rows(statement: str, parameters: dict[str, object]):
        if "DEVELOPMENT_OF*1..2" in statement:
            return [
                {
                    "target_id": "attacker-selected-target",
                    "relation_keys": [],
                    "depth": 1,
                    "score": 1.0,
                }
            ]
        return _rows(statement, parameters)

    adapter, _driver, _transaction, _unit_of_work = _adapter(rows)
    with pytest.raises(Neo4jIdentityConflict, match="checked fixture"):
        adapter.run_bounded_hybrid_branches(
            identity=complete_identity(),
            fixture=INTEGRATED_FIXTURE_V2_PROJECTION,
            retrieval_contract=INTEGRATED_FIXTURE_V2_RETRIEVAL,
            policy=HYBRID_FIXTURE_POLICY_V1,
            query_digest=_QUERY_DIGEST,
        )


@pytest.mark.parametrize(
    ("query_marker", "invalid_score", "message"),
    (
        ("revision_id IN $revision_ids", 0.99, "exact retrieval row"),
        ("DEVELOPMENT_OF*1..2", 1.1, "graph retrieval row"),
        ("db.index.vector.queryNodes", 1.01, "vector retrieval row"),
    ),
)
def test_branch_score_domains_fail_closed(
    query_marker: str,
    invalid_score: float,
    message: str,
) -> None:
    def rows(statement: str, parameters: dict[str, object]):
        retained = _rows(statement, parameters)
        if query_marker in statement:
            return [{**retained[0], "score": invalid_score}]
        return retained

    adapter, _driver, _transaction, _unit_of_work = _adapter(rows)
    with pytest.raises(Neo4jIdentityConflict, match=message):
        adapter.run_bounded_hybrid_branches(
            identity=complete_identity(),
            fixture=INTEGRATED_FIXTURE_V2_PROJECTION,
            retrieval_contract=INTEGRATED_FIXTURE_V2_RETRIEVAL,
            policy=HYBRID_FIXTURE_POLICY_V1,
            query_digest=_QUERY_DIGEST,
        )


def test_graph_score_must_match_returned_path_depth() -> None:
    def rows(statement: str, parameters: dict[str, object]):
        retained = _rows(statement, parameters)
        if "DEVELOPMENT_OF*1..2" in statement:
            return [
                {
                    **retained[0],
                    "relation_keys": [
                        "sha256:" + "7" * 64,
                        "sha256:" + "8" * 64,
                    ],
                    "depth": 2,
                    "score": 1.0,
                }
            ]
        return retained

    adapter, _driver, _transaction, _unit_of_work = _adapter(rows)
    with pytest.raises(Neo4jIdentityConflict, match="path depth"):
        adapter.run_bounded_hybrid_branches(
            identity=complete_identity(),
            fixture=INTEGRATED_FIXTURE_V2_PROJECTION,
            retrieval_contract=INTEGRATED_FIXTURE_V2_RETRIEVAL,
            policy=HYBRID_FIXTURE_POLICY_V1,
            query_digest=_QUERY_DIGEST,
        )


@pytest.mark.parametrize(
    ("component_rows", "message"),
    (
        ([], "identify one component"),
        (
            [{"version": "2026.06.0"}],
            "malformed compatibility metadata",
        ),
        (
            [
                {"version": "2026.06.0", "edition": "community"},
                {"version": "2026.06.0", "edition": "community"},
            ],
            "identify one component",
        ),
    ),
)
def test_adapter_rejects_missing_or_malformed_live_component_evidence(
    component_rows: list[dict[str, object]],
    message: str,
) -> None:
    def rows(
        statement: str,
        parameters: dict[str, object],
    ) -> list[dict[str, object]]:
        if "dbms.components" in statement:
            return component_rows
        return _rows(statement, parameters)

    adapter, _driver, transaction, _unit_of_work = _adapter(rows)
    with pytest.raises(Neo4jCompatibilityError, match=message):
        adapter.run_bounded_hybrid_branches(
            identity=complete_identity(),
            fixture=INTEGRATED_FIXTURE_V2_PROJECTION,
            retrieval_contract=INTEGRATED_FIXTURE_V2_RETRIEVAL,
            policy=HYBRID_FIXTURE_POLICY_V1,
            query_digest=_QUERY_DIGEST,
        )
    assert len(transaction.statements) == 1


def test_adapter_rejects_a_nonqualified_live_server() -> None:
    def incompatible(
        statement: str,
        parameters: dict[str, object],
    ) -> list[dict[str, object]]:
        if "dbms.components" in statement:
            return [{"version": "2026.07.0", "edition": "community"}]
        return _rows(statement, parameters)

    adapter, _driver, transaction, _unit_of_work = _adapter(incompatible)
    with pytest.raises(Neo4jCompatibilityError, match="qualified target"):
        adapter.run_bounded_hybrid_branches(
            identity=complete_identity(),
            fixture=INTEGRATED_FIXTURE_V2_PROJECTION,
            retrieval_contract=INTEGRATED_FIXTURE_V2_RETRIEVAL,
            policy=HYBRID_FIXTURE_POLICY_V1,
            query_digest=_QUERY_DIGEST,
        )
    assert len(transaction.statements) == 1


def test_closed_adapter_rejects_reads_and_closes_driver_once() -> None:
    adapter, driver, _transaction, _unit_of_work = _adapter()
    adapter.close()
    adapter.close()
    assert driver.close_count == 1
    with pytest.raises(Neo4jConnectionError, match="closed"):
        adapter.run_bounded_hybrid_branches(
            identity=complete_identity(),
            fixture=INTEGRATED_FIXTURE_V2_PROJECTION,
            retrieval_contract=INTEGRATED_FIXTURE_V2_RETRIEVAL,
            policy=HYBRID_FIXTURE_POLICY_V1,
            query_digest=_QUERY_DIGEST,
        )


def test_adapter_exposes_only_the_read_and_close_capabilities() -> None:
    public = {
        name
        for name in dir(_HybridRetrievalNeo4jAdapter)
        if not name.startswith("_")
    }
    assert public == {"close", "run_bounded_hybrid_branches"}


def test_adapter_rejects_a_nonqualified_driver_version() -> None:
    transaction = _Transaction(_rows)
    with pytest.raises(Neo4jConnectionError, match="exact qualified version"):
        _HybridRetrievalNeo4jAdapter(
            driver=_Driver(transaction),
            config=Neo4jProjectorConfig(
                uri="bolt://localhost:7687",
                database="neo4j",
                username="newsroom_projector",
                password="fixture-password",
            ),
            driver_version="0.0.0",
            monotonic_ns=_Clock(),
            unit_of_work_factory=_UnitOfWorkFactory(),
        )
