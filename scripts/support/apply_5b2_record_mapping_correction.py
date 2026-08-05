from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(relative_path: str, old: str, new: str) -> None:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"5B2 record-mapping anchor differs for {relative_path}: count={count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "newsroom/authority/_neo4j_projection_system.py",
        "from collections.abc import Callable\n",
        "from collections.abc import Callable, Mapping\n",
    )

    replace_once(
        "newsroom/authority/_neo4j_projection_system.py",
        """def _open_neo4j_fulltext_reader_with_adapter(
    adapter: _StructuralGraphAdapter,
) -> Neo4jFullTextReader:
""",
        """def _increment5_fulltext_record_mapping(
    value: Any,
    *,
    identity: str,
) -> dict[str, object]:
    if isinstance(value, Mapping):
        record = dict(value)
    else:
        try:
            record = dict(value.items())
        except Exception:
            raise Neo4jFullTextReadError(
                f\"Neo4j full-text authority read returned malformed {identity}\"
            ) from None
    if any(not isinstance(key, str) for key in record):
        raise Neo4jFullTextReadError(
            f\"Neo4j full-text authority read returned malformed {identity}\"
        )
    return record


def _open_neo4j_fulltext_reader_with_adapter(
    adapter: _StructuralGraphAdapter,
) -> Neo4jFullTextReader:
""",
    )

    replace_once(
        "newsroom/authority/_neo4j_projection_system.py",
        """        if request.phase is Neo4jFullTextReadPhase.COMPONENT:
            return Neo4jFullTextReadResult(
                phase=request.phase,
                component=value,
                driver_version=adapter.driver_version,
            )
        try:
            records = tuple(value)
        except Exception:
            raise Neo4jFullTextReadError(
                \"Neo4j full-text authority read returned malformed rows\"
            ) from None
""",
        """        if request.phase is Neo4jFullTextReadPhase.COMPONENT:
            component = (
                None
                if value is None
                else _increment5_fulltext_record_mapping(
                    value,
                    identity=\"component\",
                )
            )
            return Neo4jFullTextReadResult(
                phase=request.phase,
                component=component,
                driver_version=adapter.driver_version,
            )
        try:
            records = tuple(
                _increment5_fulltext_record_mapping(
                    item,
                    identity=\"row\",
                )
                for item in value
            )
        except Neo4jFullTextReadError:
            raise
        except Exception:
            raise Neo4jFullTextReadError(
                \"Neo4j full-text authority read returned malformed rows\"
            ) from None
""",
    )

    replace_once(
        "newsroom/tests/test_increment5b2_neo4j_authority_port.py",
        """def test_authority_port_rejects_generic_or_unbounded_read_controls() -> None:
""",
        """class _Neo4jRecordLike:
    def __init__(self, values: dict[str, object]) -> None:
        self._values = dict(values)

    def __iter__(self):
        return iter(self._values.values())

    def items(self):
        return self._values.items()


class _RecordReturningAdapter:
    driver_version = \"6.2.0\"

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
        if phase == \"COMPONENT\":
            return _Neo4jRecordLike(
                {
                    \"version\": \"2026.06.0\",
                    \"edition\": \"community\",
                }
            )
        if phase == \"INDEX\":
            return (
                _Neo4jRecordLike(
                    {
                        \"name\": index_name or \"\",
                        \"state\": \"ONLINE\",
                    }
                ),
            )
        assert lucene_expression
        assert generation_id
        assert limit == 9
        return (
            _Neo4jRecordLike(
                {
                    \"generation_id\": generation_id,
                    \"passage_id\": \"p-en\",
                    \"score\": 1.0,
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
            lucene_expression=\"retrieval_text:(synthetic)\",
            generation_id=GENERATION_ID,
            limit=9,
            timeout_ns=4_800_000_000,
        )
    )

    assert component.component == {
        \"version\": \"2026.06.0\",
        \"edition\": \"community\",
    }
    assert indexes.indexes == (
        {
            \"name\": snapshot().index_name,
            \"state\": \"ONLINE\",
        },
    )
    assert rows.rows == (
        {
            \"generation_id\": str(GENERATION_ID),
            \"passage_id\": \"p-en\",
            \"score\": 1.0,
        },
    )
    reader.close()
    assert adapter.closed is True


def test_authority_port_rejects_generic_or_unbounded_read_controls() -> None:
""",
    )


if __name__ == "__main__":
    main()
