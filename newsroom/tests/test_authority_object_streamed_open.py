from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import sqlite3

import pytest

from newsroom.authority import AuthorityPersistenceError, HydrationRequest
from newsroom.authority._object_store_base import _ObjectStoreBase

from .authority_a2b_helpers import admit, open_object_system
from .authority_helpers import proof


_OBJECT_IMMUTABLE_QUERIES = frozenset(
    {
        "SELECT canonical_bytes,contract_digest FROM rights_policy_contracts",
        "SELECT canonical_bytes,contract_digest FROM hydration_policy_contracts",
        "SELECT canonical_bytes,definition_digest FROM object_admission_definitions",
        "SELECT canonical_bytes,canonical_digest FROM object_admission_preflights",
        "SELECT canonical_bytes,canonical_digest FROM object_rights_decisions",
        "SELECT canonical_bytes,canonical_digest FROM object_access_decisions",
    }
)

_ACCESS_UPDATE_TRIGGER = """CREATE TRIGGER immutable_object_access_decisions_update
BEFORE UPDATE ON object_access_decisions BEGIN
SELECT RAISE(ABORT,'immutable object access decision'); END"""


class _StreamingCursor:
    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self._cursor = cursor

    def __iter__(self) -> Iterator[sqlite3.Row]:
        return iter(self._cursor)

    def fetchall(self) -> list[sqlite3.Row]:
        raise AssertionError("object immutable validation must stream rows")


class _StreamingConnection:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self.streamed_queries: list[str] = []

    def execute(
        self, sql: str, parameters: tuple[object, ...] = ()
    ) -> sqlite3.Cursor | _StreamingCursor:
        cursor = self._connection.execute(sql, parameters)
        normalised = " ".join(sql.split())
        if not parameters and normalised in _OBJECT_IMMUTABLE_QUERIES:
            self.streamed_queries.append(normalised)
            return _StreamingCursor(cursor)
        return cursor


class _NoopIntegrity:
    def _validate_immutable_records(self, _connection: object) -> None:
        pass


class _ObjectIntegrityProbe(_ObjectStoreBase, _NoopIntegrity):
    pass


def _seed_access_decisions(database: Path) -> None:
    with open_object_system(database) as system:
        for index in range(3):
            admission = admit(system, key=f"stream-{index}").admission
            system.objects.hydrate(
                HydrationRequest(admission.admission_id, "project.discovery"),
                proof=proof(),
            )


def test_object_immutable_validation_streams_every_full_table(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    _seed_access_decisions(database)

    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        streaming = _StreamingConnection(connection)
        _ObjectIntegrityProbe()._validate_immutable_records(
            streaming  # type: ignore[arg-type]
        )
    finally:
        connection.close()

    assert frozenset(streaming.streamed_queries) == _OBJECT_IMMUTABLE_QUERIES


@pytest.mark.parametrize("record_position", (0, 1, 2))
def test_reopen_streams_and_rejects_access_tamper_at_every_position(
    tmp_path: Path, record_position: int
) -> None:
    database = tmp_path / f"authority-{record_position}.sqlite3"
    _seed_access_decisions(database)

    connection = sqlite3.connect(database)
    try:
        access_ids = connection.execute(
            "SELECT access_decision_id FROM object_access_decisions "
            "ORDER BY rowid"
        ).fetchall()
        connection.execute("DROP TRIGGER immutable_object_access_decisions_update")
        connection.execute(
            "UPDATE object_access_decisions SET canonical_bytes=? "
            "WHERE access_decision_id=?",
            (b"{}", access_ids[record_position][0]),
        )
        connection.execute(_ACCESS_UPDATE_TRIGGER)
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(
        AuthorityPersistenceError,
        match="immutable object_access_decisions canonical digest mismatch",
    ):
        open_object_system(database)
