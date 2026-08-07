from __future__ import annotations

import pytest

from newsroom.authority._neo4j_projection_system import (
    _open_neo4j_fulltext_reader_with_adapter,
)
from newsroom.authority.neo4j_fulltext_reader import (
    Neo4jFullTextReadError,
    Neo4jFullTextReadPhase,
    Neo4jFullTextReadRequest,
    Neo4jFullTextReadResult,
    Neo4jFullTextReadTimeout,
)
from newsroom.projection.neo4j._adapter import (
    _COMPONENT_QUERY,
    _FULLTEXT_INDEX_INVENTORY_QUERY,
    _FULLTEXT_READ_QUERY,
    _FULLTEXT_SOURCE_SCOPE_CANDIDATE_LIMIT,
    _Neo4jAdapter,
)

from .increment5b2_helpers import (
    GENERATION_ID,
    FakeDriver,
    RecordingUnitOfWorkFactory,
    SequenceClock,
    config,
    default_scenario,
    snapshot,
)


def test_authority_port_owns_three_fixed_server_timed_phases() -> None:
    clock = SequenceClock(
        (
            0,
            100_000_000,
            200_000_000,
            300_000_000,
            400_000_000,
            500_000_000,
            600_000_000,
            700_000_000,
            800_000_000,
        )
    )
    factory = RecordingUnitOfWorkFactory()
    driver = FakeDriver(default_scenario())
    adapter = _Neo4jAdapter(
        driver=driver,
        config=config(),
        driver_version="6.2.0",
        monotonic_ns=clock,
        unit_of_work_factory=factory,
    )
    reader = _open_neo4j_fulltext_reader_with_adapter(adapter)

    component = reader.read(
        Neo4jFullTextReadRequest.component(
            timeout_ns=5_000_000_000,
        )
    )
    indexes = reader.read(
        Neo4jFullTextReadRequest.index(
            index_name=snapshot().index_name,
            timeout_ns=4_800_000_000,
        )
    )
    rows = reader.read(
        Neo4jFullTextReadRequest.query(
            index_name=snapshot().index_name,
            lucene_expression=(
                "latin_terms:(synthetic) OR "
                "han_bigrams:(合成) OR "
                "retrieval_text:(synthetic)"
            ),
            generation_id=GENERATION_ID,
            source_ids=(),
            limit=9,
            timeout_ns=4_600_000_000,
        )
    )

    assert component.driver_version == "6.2.0"
    assert component.read_count == 1
    assert component.component == {
        "version": "2026.06.0",
        "edition": "community",
    }
    assert len(indexes.indexes) == 1
    assert len(rows.rows) == 2
    assert driver.execute_read_count == 3
    assert [statement for statement, _parameters in driver.calls] == [
        _COMPONENT_QUERY,
        _FULLTEXT_INDEX_INVENTORY_QUERY,
        _FULLTEXT_READ_QUERY,
    ]
    assert [round(float(item["timeout"]), 1) for item in factory.options] == [
        4.9,
        4.7,
        4.5,
    ]
    assert [item["metadata"]["newsroom_operation"] for item in factory.options] == [
        "increment5.fulltext.component",
        "increment5.fulltext.index",
        "increment5.fulltext.query",
    ]
    assert not hasattr(reader, "driver")
    assert not hasattr(reader, "session")
    assert not hasattr(reader, "execute_query")

    reader.close()
    reader.close()
    assert driver.closed is True


class _Neo4jRecordLike:
    def __init__(self, values: dict[str, object]) -> None:
        self._values = dict(values)

    def __iter__(self):
        return iter(self._values.values())

    def items(self):
        return self._values.items()


class _RecordReturningAdapter:
    driver_version = "6.2.0"

    def __init__(self) -> None:
        self.closed = False

    def read_increment5_fulltext(
        self,
        *,
        phase: str,
        index_name: str | None,
        lucene_expression: str | None,
        generation_id: str | None,
        source_ids: tuple[str, ...],
        limit: int,
        timeout_ns: int,
    ):
        assert timeout_ns > 0
        if phase == "COMPONENT":
            return _Neo4jRecordLike(
                {
                    "version": "2026.06.0",
                    "edition": "community",
                }
            )
        if phase == "INDEX":
            return (
                _Neo4jRecordLike(
                    {
                        "name": index_name or "",
                        "state": "ONLINE",
                    }
                ),
            )
        assert lucene_expression
        assert generation_id
        assert source_ids == ()
        assert limit == 9
        return _Neo4jRecordLike(
            {
                "candidate_overflow": False,
                "rows": [
                    _Neo4jRecordLike(
                        {
                            "generation_id": generation_id,
                            "passage_id": "p-en",
                            "score": 1.0,
                        }
                    )
                ],
            }
        )

    def close(self) -> None:
        self.closed = True


def test_authority_port_copies_neo4j_records_to_plain_mappings() -> None:
    adapter = _RecordReturningAdapter()
    reader = _open_neo4j_fulltext_reader_with_adapter(adapter)

    component = reader.read(
        Neo4jFullTextReadRequest.component(timeout_ns=5_000_000_000)
    )
    indexes = reader.read(
        Neo4jFullTextReadRequest.index(
            index_name=snapshot().index_name,
            timeout_ns=4_900_000_000,
        )
    )
    rows = reader.read(
        Neo4jFullTextReadRequest.query(
            index_name=snapshot().index_name,
            lucene_expression="retrieval_text:(synthetic)",
            generation_id=GENERATION_ID,
            source_ids=(),
            limit=9,
            timeout_ns=4_800_000_000,
        )
    )

    assert component.component == {
        "version": "2026.06.0",
        "edition": "community",
    }
    assert indexes.indexes == (
        {
            "name": snapshot().index_name,
            "state": "ONLINE",
        },
    )
    assert rows.rows == (
        {
            "generation_id": str(GENERATION_ID),
            "passage_id": "p-en",
            "score": 1.0,
        },
    )
    reader.close()
    assert adapter.closed is True


def test_authority_port_rejects_generic_or_unbounded_read_controls() -> None:
    with pytest.raises(Neo4jFullTextReadError, match="controls"):
        Neo4jFullTextReadRequest(
            phase=Neo4jFullTextReadPhase.COMPONENT,
            timeout_ns=5_000_000_000,
            index_name=snapshot().index_name,
        )
    with pytest.raises(Neo4jFullTextReadError, match="limit"):
        Neo4jFullTextReadRequest.query(
            index_name=snapshot().index_name,
            lucene_expression="retrieval_text:(synthetic)",
            generation_id=GENERATION_ID,
            source_ids=(),
            limit=10,
            timeout_ns=5_000_000_000,
        )
    with pytest.raises(Neo4jFullTextReadError, match="timeout"):
        Neo4jFullTextReadRequest.component(
            timeout_ns=5_000_000_001,
        )


class _ClockConsumingLock:
    def __init__(self, clock: SequenceClock) -> None:
        self._clock = clock

    def __enter__(self):
        self._clock()
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def test_authority_port_charges_lock_wait_to_phase_timeout() -> None:
    clock = SequenceClock((0, 5_000_000_001, 5_000_000_001))
    factory = RecordingUnitOfWorkFactory()
    driver = FakeDriver(default_scenario())
    adapter = _Neo4jAdapter(
        driver=driver,
        config=config(),
        driver_version="6.2.0",
        monotonic_ns=clock,
        unit_of_work_factory=factory,
    )
    adapter._lock = _ClockConsumingLock(clock)
    reader = _open_neo4j_fulltext_reader_with_adapter(adapter)

    with pytest.raises(Neo4jFullTextReadTimeout, match="timed out"):
        reader.read(
            Neo4jFullTextReadRequest.component(
                timeout_ns=5_000_000_000,
            )
        )

    assert factory.options == []
    assert driver.calls == []
    assert driver.execute_read_count == 0


def test_authority_port_maps_server_timeout_to_typed_failure() -> None:
    clock = SequenceClock((0, 100_000_000, 200_000_000))
    driver = FakeDriver(default_scenario())
    driver.scenario.failure_on = "query"
    adapter = _Neo4jAdapter(
        driver=driver,
        config=config(),
        driver_version="6.2.0",
        monotonic_ns=clock,
        unit_of_work_factory=RecordingUnitOfWorkFactory(),
    )
    reader = _open_neo4j_fulltext_reader_with_adapter(adapter)

    with pytest.raises(Neo4jFullTextReadTimeout, match="timed out"):
        reader.read(
            Neo4jFullTextReadRequest.query(
                index_name=snapshot().index_name,
                lucene_expression="retrieval_text:(synthetic)",
                generation_id=GENERATION_ID,
                source_ids=(),
                limit=9,
                timeout_ns=5_000_000_000,
            )
        )


def test_authority_port_redacts_unavailable_adapter_failure() -> None:
    clock = SequenceClock((0, 100_000_000, 200_000_000))
    driver = FakeDriver(default_scenario())
    driver.scenario.failure_on = "component"
    adapter = _Neo4jAdapter(
        driver=driver,
        config=config(),
        driver_version="6.2.0",
        monotonic_ns=clock,
        unit_of_work_factory=RecordingUnitOfWorkFactory(),
    )
    reader = _open_neo4j_fulltext_reader_with_adapter(adapter)

    with pytest.raises(Neo4jFullTextReadError, match="unavailable") as failure:
        reader.read(
            Neo4jFullTextReadRequest.component(
                timeout_ns=5_000_000_000,
            )
        )
    assert "component read failed" not in str(failure.value)

def test_authority_port_uses_source_scope_only_for_bounded_candidate_scan() -> None:
    source_ids = ("source:a", "source:b")
    clock = SequenceClock((0, 100_000_000, 200_000_000))
    driver = FakeDriver(default_scenario())
    adapter = _Neo4jAdapter(
        driver=driver,
        config=config(),
        driver_version="6.2.0",
        monotonic_ns=clock,
        unit_of_work_factory=RecordingUnitOfWorkFactory(),
    )
    reader = _open_neo4j_fulltext_reader_with_adapter(adapter)

    result = reader.read(
        Neo4jFullTextReadRequest.query(
            index_name=snapshot().index_name,
            lucene_expression="retrieval_text:(synthetic)",
            generation_id=GENERATION_ID,
            source_ids=source_ids,
            limit=9,
            timeout_ns=5_000_000_000,
        )
    )

    assert result.candidate_overflow is False
    statement, parameters = driver.calls[-1]
    assert source_ids[0] not in statement
    assert source_ids[1] not in statement
    assert "source_ids" not in parameters
    assert parameters["candidate_limit"] == _FULLTEXT_SOURCE_SCOPE_CANDIDATE_LIMIT
    assert set(parameters) == {
        "index_name",
        "query",
        "generation_id",
        "candidate_limit",
        "limit",
    }


def test_authority_read_request_rejects_malformed_source_scope() -> None:
    kwargs = {
        "index_name": snapshot().index_name,
        "lucene_expression": "retrieval_text:(synthetic)",
        "generation_id": GENERATION_ID,
        "limit": 9,
        "timeout_ns": 5_000_000_000,
    }
    with pytest.raises(Neo4jFullTextReadError, match="sorted and unique"):
        Neo4jFullTextReadRequest.query(
            source_ids=("source:b", "source:a"),
            **kwargs,
        )
    with pytest.raises(Neo4jFullTextReadError, match="fixed bound"):
        Neo4jFullTextReadRequest.query(
            source_ids=tuple(f"source:{index}" for index in range(9)),
            **kwargs,
        )
    with pytest.raises(Neo4jFullTextReadError, match="bounded canonical text"):
        Neo4jFullTextReadRequest.query(
            source_ids=(" source:a",),
            **kwargs,
        )


def test_query_envelope_requires_exact_boolean_overflow_and_rows_shape() -> None:
    with pytest.raises(Neo4jFullTextReadError, match="overflow flag"):
        Neo4jFullTextReadResult(
            phase=Neo4jFullTextReadPhase.QUERY,
            rows=(),
            candidate_overflow=0,
            driver_version="6.2.0",
        )
