from __future__ import annotations

import pytest

from newsroom.authority._neo4j_projection_system import (
    _open_neo4j_fulltext_reader_with_adapter,
)
from newsroom.authority.neo4j_fulltext_reader import (
    Neo4jFullTextReadError,
    Neo4jFullTextReadPhase,
    Neo4jFullTextReadRequest,
    Neo4jFullTextReadTimeout,
)
from newsroom.projection.neo4j._adapter import (
    _COMPONENT_QUERY,
    _FULLTEXT_INDEX_INVENTORY_QUERY,
    _FULLTEXT_READ_QUERY,
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
        assert limit == 9
        return (
            _Neo4jRecordLike(
                {
                    "generation_id": generation_id,
                    "passage_id": "p-en",
                    "score": 1.0,
                }
            ),
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
            limit=10,
            timeout_ns=5_000_000_000,
        )
    with pytest.raises(Neo4jFullTextReadError, match="timeout"):
        Neo4jFullTextReadRequest.component(
            timeout_ns=5_000_000_001,
        )


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
