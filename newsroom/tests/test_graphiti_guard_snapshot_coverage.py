from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace

import pytest

from newsroom.graphiti_adapter.neo4j_guard import GuardError, Neo4jMutationGuard


_NODE = {
    "snapshot_identity": "snapshot-node-1",
    "snapshot": {
        "uuid": "node-1", "embedding": [1.0, 2.0],
        "_newsroom_source_uuid": "node-1", "_newsroom_source_labels": ["Entity"],
    },
    "current": {"uuid": "node-1", "embedding": [1.0, 2.0]},
    "current_labels": ["Entity"],
}
_RELATIONSHIP = {
    "snapshot_identity": "snapshot-relationship-1",
    "snapshot": {
        "uuid": "relationship-1", "weight": 1.0,
        "_newsroom_source_uuid": "node-1", "_newsroom_target_uuid": "node-2",
        "_newsroom_relationship_type": "RELATES_TO",
    },
    "current": {"uuid": "relationship-1", "weight": 1.0},
    "source_uuid": "node-1", "target_uuid": "node-2", "relationship_type": "RELATES_TO",
}


class _Result:
    def __init__(self, records):
        self.records = records

    def __iter__(self):
        raise AssertionError("snapshot property records must remain streamed")

    async def single(self, *, strict=False):
        assert strict and len(self.records) == 1
        return self.records[0]

    async def __aiter__(self):
        for record in self.records:
            if isinstance(record, BaseException):
                raise record
            yield record


class _RetryTransaction(Exception):
    pass


def _guard(
    *, nodes=(), relationships=(), expected_nodes=0, expected_relationships=0,
    node_attempts=None,
):
    queries = []
    phases = [
        node_attempts or [(expected_nodes, nodes)],
        [(expected_relationships, relationships)],
    ]

    class Transaction:
        def __init__(self, count, records):
            self.count = count
            self.records = records

        async def run(self, query, **params):
            assert params == {"snapshot_id": "episode-id:1"}
            assert "OPTIONAL MATCH" not in query, "per-snapshot full scans must be set-based"
            queries.append(query)
            if "RETURN count(s) AS snapshot_count" in query:
                return _Result([{"snapshot_count": self.count}])
            assert "elementId(s) AS snapshot_identity" in query
            return _Result(self.records)

    class Session:
        def __init__(self):
            self.attempts = phases.pop(0)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute_write(self, callback):
            for index, (count, records) in enumerate(self.attempts):
                try:
                    await callback(Transaction(count, records))
                    return
                except _RetryTransaction:
                    assert index < len(self.attempts) - 1
            raise AssertionError("no transaction attempt completed")

    guard = Neo4jMutationGuard(
        SimpleNamespace(session=Session), group_id="group-id", episode_uuid="episode-id",
        attempt_number=1, input_digest="sha256:" + "0" * 64,
    )
    return guard, queries


def test_guard_streams_set_based_matches_with_exact_snapshot_coverage() -> None:
    guard, queries = _guard(
        nodes=[_NODE], relationships=[_RELATIONSHIP],
        expected_nodes=1, expected_relationships=1,
    )
    asyncio.run(guard.assert_preexisting_unchanged())
    assert len(queries) == 4


@pytest.mark.parametrize("kind", ["node", "relationship"])
@pytest.mark.parametrize("duplicate_survivor", [False, True])
def test_guard_rejects_missing_snapshot_even_if_another_original_matches_twice(
    kind: str, duplicate_survivor: bool,
) -> None:
    record = _NODE if kind == "node" else _RELATIONSHIP
    records = [record, copy.deepcopy(record)] if duplicate_survivor else []
    kwargs = (
        {"nodes": records, "expected_nodes": 2 if duplicate_survivor else 1}
        if kind == "node" else
        {"relationships": records, "expected_relationships": 2 if duplicate_survivor else 1}
    )
    guard, _ = _guard(**kwargs)
    with pytest.raises(GuardError, match=f"pre-existing Graphiti {kind} is missing"):
        asyncio.run(guard.assert_preexisting_unchanged())


@pytest.mark.parametrize("kind", ["node", "relationship"])
def test_guard_validates_all_duplicate_originals_without_changing_legacy_acceptance(kind: str) -> None:
    record = _NODE if kind == "node" else _RELATIONSHIP
    records = [record, copy.deepcopy(record)]
    kwargs = (
        {"nodes": records, "expected_nodes": 1} if kind == "node" else
        {"relationships": records, "expected_relationships": 1}
    )
    guard, _ = _guard(**kwargs)
    asyncio.run(guard.assert_preexisting_unchanged())


@pytest.mark.parametrize(("kind", "path", "value"), [
    ("node", ("snapshot",), None),
    ("node", ("current",), None),
    ("node", ("current", "uuid"), "different"),
    ("node", ("current", "embedding"), [2.0, 1.0]),
    ("node", ("current", "extra"), True),
    ("node", ("current_labels",), ["Other"]),
    ("relationship", ("snapshot",), None),
    ("relationship", ("current",), None),
    ("relationship", ("current", "uuid"), "different"),
    ("relationship", ("current", "weight"), 2.0),
    ("relationship", ("current", "extra"), True),
    ("relationship", ("source_uuid",), "other-source"),
    ("relationship", ("target_uuid",), "other-target"),
    ("relationship", ("relationship_type",), "OTHER"),
])
def test_guard_rejects_each_corruption_surface_even_after_a_valid_duplicate(
    kind: str, path: tuple[str, ...], value: object,
) -> None:
    record = _NODE if kind == "node" else _RELATIONSHIP
    changed = copy.deepcopy(record)
    target = changed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    kwargs = (
        {"nodes": [record, changed], "expected_nodes": 1} if kind == "node" else
        {"relationships": [record, changed], "expected_relationships": 1}
    )
    guard, _ = _guard(**kwargs)
    with pytest.raises(GuardError, match="pre-existing Graphiti"):
        asyncio.run(guard.assert_preexisting_unchanged())


def test_guard_accepts_empty_snapshot_sets() -> None:
    guard, queries = _guard()
    asyncio.run(guard.assert_preexisting_unchanged())
    assert len(queries) == 4


@pytest.mark.parametrize("kind", ["node", "relationship"])
def test_guard_partial_cancellation_never_finishes_coverage(kind: str) -> None:
    record = _NODE if kind == "node" else _RELATIONSHIP
    records = [record, asyncio.CancelledError()]
    kwargs = (
        {"nodes": records, "expected_nodes": 1} if kind == "node" else
        {"relationships": records, "expected_relationships": 1}
    )
    guard, queries = _guard(**kwargs)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(guard.assert_preexisting_unchanged())
    assert len(queries) == (2 if kind == "node" else 4)


@pytest.mark.parametrize("second_count", [1, 2])
def test_guard_transaction_retry_recounts_and_does_not_reuse_partial_coverage(second_count: int) -> None:
    second = copy.deepcopy(_NODE)
    second["snapshot_identity"] = "snapshot-node-2"
    guard, queries = _guard(node_attempts=[
        (3, [_NODE, _RetryTransaction()]),
        (second_count, [second]),
    ])
    if second_count == 1:
        asyncio.run(guard.assert_preexisting_unchanged())
        assert len(queries) == 6
    else:
        with pytest.raises(GuardError, match="node is missing"):
            asyncio.run(guard.assert_preexisting_unchanged())
        assert len(queries) == 4


@pytest.mark.parametrize("identity", [None, "", 12])
def test_guard_rejects_absent_snapshot_coverage_identity(identity: object) -> None:
    record = {**_NODE, "snapshot_identity": identity}
    guard, _ = _guard(nodes=[record], expected_nodes=1)
    with pytest.raises(GuardError, match="coverage identity is absent"):
        asyncio.run(guard.assert_preexisting_unchanged())


@pytest.mark.parametrize("count", [None, -1, True, "1"])
def test_guard_rejects_invalid_snapshot_coverage_count(count: object) -> None:
    guard, _ = _guard(nodes=[_NODE], expected_nodes=count)
    with pytest.raises(GuardError, match="coverage count is invalid"):
        asyncio.run(guard.assert_preexisting_unchanged())
