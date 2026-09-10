from __future__ import annotations

from collections.abc import Iterable, Iterator

from newsroom.authority._extraction_store_integrity import (
    _ExtractionIntegrityMixin,
)
from newsroom.authority._graphiti_adapter_store_integrity import (
    _GraphitiAdapterIntegrityMixin,
)


class _StreamingCursor:
    def __init__(self, rows: Iterable[object]) -> None:
        self._rows = iter(rows)

    def __iter__(self) -> Iterator[object]:
        return self._rows

    def fetchone(self) -> object | None:
        return next(self._rows, None)

    def fetchall(self) -> list[object]:
        raise AssertionError("high-cardinality opener query used fetchall")


class _StreamingConnection:
    def __init__(self, *, large_rows: tuple[bytes, ...]) -> None:
        self.large_rows = large_rows

    def execute(self, sql: str, _parameters: object = ()) -> _StreamingCursor:
        if "graphiti_workspace_policies" in sql:
            return _StreamingCursor(({"ordinal": item} for item in range(3)))
        if "graphiti_input_manifests" in sql:
            return _StreamingCursor(
                ({"canonical_bytes": value} for value in self.large_rows)
            )
        if "extractor_contracts" in sql:
            return _StreamingCursor(({"canonical_bytes": self.large_rows[0]},))
        if "extraction_run_versions" in sql:
            return _StreamingCursor(
                ({"canonical_bytes": value} for value in self.large_rows)
            )
        return _StreamingCursor(())


class _ExtractionProbe(_ExtractionIntegrityMixin):
    def __init__(self) -> None:
        self.sizes: list[int] = []

    def _contract_from_row(self, _conn, row, *, replayed):
        assert replayed is False
        self.sizes.append(len(row["canonical_bytes"]))

    def _run_version_from_row(self, _conn, row, *, replayed):
        assert replayed is False
        self.sizes.append(len(row["canonical_bytes"]))


class _GraphitiProbe(_GraphitiAdapterIntegrityMixin):
    def __init__(self) -> None:
        self.sizes: list[int] = []

    def _graphiti_workspace_policy_from_row(self, row):
        return row["ordinal"]

    def _graphiti_manifest_from_row(self, _conn, row):
        self.sizes.append(len(row["canonical_bytes"]))

    def _graphiti_configuration_from_row(self, *_args, **_kwargs):
        raise AssertionError("unexpected configuration row")

    def _graphiti_workspace_from_row(self, *_args, **_kwargs):
        raise AssertionError("unexpected workspace row")

    def _graphiti_cleanup_from_row(self, *_args, **_kwargs):
        raise AssertionError("unexpected cleanup row")

    def _graphiti_attempt_from_row(self, *_args, **_kwargs):
        raise AssertionError("unexpected attempt row")

    def _graphiti_replay_source_from_row(self, *_args, **_kwargs):
        raise AssertionError("unexpected replay row")

    def _validate_graphiti_attempt_heads(self, _conn):
        pass

    def _validate_graphiti_replay_bindings(self, _conn):
        pass

    def _validate_graphiti_event_coverage(self, _conn):
        pass


def test_high_cardinality_domain_openers_stream_large_rows() -> None:
    large_rows = tuple(bytes([ordinal]) * 1_000_000 for ordinal in range(1, 4))
    connection = _StreamingConnection(large_rows=large_rows)

    extraction = _ExtractionProbe()
    extraction._validate_all_extraction_rows(connection)  # type: ignore[arg-type]
    assert extraction.sizes == [1_000_000] * 4

    graphiti = _GraphitiProbe()
    graphiti._validate_graphiti_adapter_integrity(connection)  # type: ignore[arg-type]
    assert graphiti.sizes == [1_000_000] * 3
