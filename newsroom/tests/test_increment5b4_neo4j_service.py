from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from typing import Iterator

import pytest

from newsroom.authority.neo4j_admitted_graph_reader import Neo4jAdmittedGraphReadPort
from newsroom.increment5.admitted_graph_retriever import canonical_node_digest


neo4j = pytest.importorskip("neo4j")


def _setting(*names: str, default: str | None = None) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


@contextmanager
def actual_driver() -> Iterator[tuple[object, str | None]]:
    uri = _setting("NEWSROOM_NEO4J_URI", "NEO4J_URI")
    password = _setting("NEWSROOM_NEO4J_PASSWORD", "NEO4J_PASSWORD")
    if uri is None or password is None:
        pytest.skip("authenticated Neo4j service settings are not available")
    user = _setting("NEWSROOM_NEO4J_USER", "NEO4J_USER", default="neo4j")
    database = _setting("NEWSROOM_NEO4J_DATABASE", "NEO4J_DATABASE")
    driver = neo4j.GraphDatabase.driver(uri, auth=(user, password))
    try:
        driver.verify_connectivity()
        yield driver, database
    finally:
        driver.close()


def _session(driver: object, database: str | None):
    config: dict[str, object] = {}
    if database is not None:
        config["database"] = database
    return driver.session(**config)


def _cleanup(driver: object, database: str | None, generations: list[str]) -> None:
    with _session(driver, database) as session:
        session.run(
            "MATCH (n) WHERE n.generation_id IN $generations DETACH DELETE n",
            generations=generations,
        ).consume()


def test_increment5b4_fixed_port_reads_only_exact_generation_and_allowed_state() -> None:
    with actual_driver() as (driver, database):
        generation = f"i5b4-{uuid.uuid4()}"
        other_generation = f"i5b4-other-{uuid.uuid4()}"
        generations = [generation, other_generation]
        try:
            with _session(driver, database) as session:
                session.run(
                    """
                    CREATE (root:Source {
                      generation_id: $generation,
                      canonical_id: 'source:root',
                      identity_digest: $root_digest
                    })
                    CREATE (revision:Revision {
                      generation_id: $generation,
                      canonical_id: 'revision:one',
                      identity_digest: $revision_digest
                    })
                    CREATE (candidate:Candidate {
                      generation_id: $generation,
                      canonical_id: 'candidate:one',
                      identity_digest: $candidate_digest
                    })
                    CREATE (blocked:Lead {
                      generation_id: $generation,
                      canonical_id: 'lead:disallowed-relation',
                      identity_digest: $blocked_digest
                    })
                    CREATE (old:Signal {
                      generation_id: $generation,
                      canonical_id: 'signal:old',
                      identity_digest: $old_digest
                    })
                    CREATE (foreign:Revision {
                      generation_id: $other_generation,
                      canonical_id: 'revision:foreign',
                      identity_digest: $foreign_digest
                    })
                    CREATE (root)-[:DEVELOPMENT_OF {
                      generation_id: $generation,
                      relation_id: 'relation:root-revision',
                      valid_from: '2020-01-01T00:00:00Z',
                      valid_to: '2035-01-01T00:00:00Z',
                      observed_at: '2026-08-01T00:00:00Z'
                    }]->(revision)
                    CREATE (revision)-[:ABOUT_EVENT {
                      generation_id: $generation,
                      relation_id: 'relation:revision-candidate',
                      valid_from: '2020-01-01T00:00:00Z',
                      valid_to: '2035-01-01T00:00:00Z',
                      observed_at: '2026-08-01T00:00:00Z'
                    }]->(candidate)
                    CREATE (root)-[:NOT_ADMITTED {
                      generation_id: $generation,
                      relation_id: 'relation:disallowed',
                      valid_from: '2020-01-01T00:00:00Z',
                      valid_to: '2035-01-01T00:00:00Z',
                      observed_at: '2026-08-01T00:00:00Z'
                    }]->(blocked)
                    CREATE (root)-[:SUPPORTS {
                      generation_id: $generation,
                      relation_id: 'relation:old',
                      valid_from: '2020-01-01T00:00:00Z',
                      valid_to: '2035-01-01T00:00:00Z',
                      observed_at: '2026-06-01T00:00:00Z'
                    }]->(old)
                    CREATE (root)-[:DEVELOPMENT_OF {
                      generation_id: $other_generation,
                      relation_id: 'relation:cross-generation',
                      valid_from: '2020-01-01T00:00:00Z',
                      valid_to: '2035-01-01T00:00:00Z',
                      observed_at: '2026-08-01T00:00:00Z'
                    }]->(foreign)
                    """,
                    generation=generation,
                    other_generation=other_generation,
                    root_digest=canonical_node_digest("source:root"),
                    revision_digest=canonical_node_digest("revision:one"),
                    candidate_digest=canonical_node_digest("candidate:one"),
                    blocked_digest=canonical_node_digest("lead:disallowed-relation"),
                    old_digest=canonical_node_digest("signal:old"),
                    foreign_digest=canonical_node_digest("revision:foreign"),
                ).consume()

            port = Neo4jAdmittedGraphReadPort(driver, database=database)
            root = port.read_root(
                generation_id=generation,
                canonical_id="source:root",
                timeout_ms=5_000,
            )
            assert root is not None
            assert root.generation_id == generation
            assert root.canonical_id == "source:root"
            assert root.identity_digest == canonical_node_digest("source:root")
            assert root.labels == ("Source",)

            first = port.expand_frontier(
                generation_id=generation,
                frontier_ids=("source:root",),
                query_valid_time="2026-08-06T08:59:00Z",
                temporal_lower_bound="2026-07-06T08:59:00Z",
                timeout_ms=5_000,
            )
            assert [edge.relation_id for edge in first] == [
                "relation:root-revision"
            ]
            assert first[0].source_id == "source:root"
            assert first[0].target_id == "revision:one"
            assert first[0].predicate == "DEVELOPMENT_OF"

            second = port.expand_frontier(
                generation_id=generation,
                frontier_ids=("revision:one",),
                query_valid_time="2026-08-06T08:59:00Z",
                temporal_lower_bound="2026-07-06T08:59:00Z",
                timeout_ms=5_000,
            )
            assert [edge.relation_id for edge in second] == [
                "relation:revision-candidate",
                "relation:root-revision",
            ]
            assert all(edge.generation_id == generation for edge in second)
            assert all(edge.target_id != "revision:foreign" for edge in first + second)
            assert all(edge.relation_id != "relation:disallowed" for edge in first + second)
            assert all(edge.relation_id != "relation:old" for edge in first + second)
        finally:
            _cleanup(driver, database, generations)


def test_increment5b4_fixed_port_excludes_future_observations() -> None:
    with actual_driver() as (driver, database):
        generation = f"i5b4-future-{uuid.uuid4()}"
        try:
            with _session(driver, database) as session:
                session.run(
                    """
                    CREATE (root:Source {
                      generation_id: $generation,
                      canonical_id: 'source:root',
                      identity_digest: $root_digest
                    })
                    CREATE (future:Signal {
                      generation_id: $generation,
                      canonical_id: 'signal:future',
                      identity_digest: $future_digest
                    })
                    CREATE (root)-[:ABOUT_EVENT {
                      generation_id: $generation,
                      relation_id: 'relation:future-observation',
                      valid_from: '2020-01-01T00:00:00Z',
                      valid_to: '2035-01-01T00:00:00Z',
                      observed_at: '2026-08-07T00:00:00Z'
                    }]->(future)
                    """,
                    generation=generation,
                    root_digest=canonical_node_digest("source:root"),
                    future_digest=canonical_node_digest("signal:future"),
                ).consume()
            port = Neo4jAdmittedGraphReadPort(driver, database=database)
            edges = port.expand_frontier(
                generation_id=generation,
                frontier_ids=("source:root",),
                query_valid_time="2026-08-06T08:59:00Z",
                temporal_lower_bound="2026-07-06T08:59:00Z",
                timeout_ms=5_000,
            )
            assert edges == ()
        finally:
            _cleanup(driver, database, [generation])
