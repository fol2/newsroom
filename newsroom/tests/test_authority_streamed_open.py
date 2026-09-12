from __future__ import annotations

from collections.abc import Iterator
import json
from pathlib import Path
import sqlite3

import pytest

from newsroom.authority import AuthorityPersistenceError, canonical_json_bytes
from newsroom.authority._event_store import _EventAuthorityStore

from .authority_event_helpers import open_test_system
from .authority_helpers import FIXED_NOW, command, make_service, proof


_STREAMED_QUERIES = frozenset(
    {
        "SELECT * FROM payload_schema_contracts",
        "SELECT * FROM command_definitions",
        "SELECT * FROM authentication_contexts",
        "SELECT * FROM authorization_requests",
        "SELECT * FROM authorization_scope_contents",
        "SELECT d.*,s.canonical_bytes AS selected_scope_canonical_bytes "
        "FROM authorization_decisions d LEFT JOIN authorization_scope_contents s "
        "ON s.scope_content_digest=d.scope_content_digest",
        "SELECT command_id,result_digest,result_bytes FROM authority_commands",
        "SELECT * FROM authority_payloads",
        "SELECT * FROM ledger_events ORDER BY ledger_seq",
    }
)

_PER_DECISION_SCOPE_QUERY = (
    "SELECT scope_content_digest,canonical_bytes FROM authorization_scope_contents "
    "WHERE scope_content_digest=?"
)

_PAYLOAD_UPDATE_TRIGGER = """CREATE TRIGGER immutable_authority_payloads_update
BEFORE UPDATE ON authority_payloads BEGIN
SELECT RAISE(ABORT,'immutable authority payload'); END"""

_COMMAND_UPDATE_TRIGGER = """CREATE TRIGGER immutable_authority_commands_update
BEFORE UPDATE ON authority_commands BEGIN
SELECT RAISE(ABORT,'immutable authority command'); END"""


class _StreamingCursor:
    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self._cursor = cursor

    def __iter__(self) -> Iterator[sqlite3.Row]:
        return iter(self._cursor)

    def fetchall(self) -> list[sqlite3.Row]:
        raise AssertionError("full-table integrity validation must stream rows")


class _StreamingConnection:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self.streamed_queries: list[str] = []

    def execute(
        self, sql: str, parameters: tuple[object, ...] = ()
    ) -> sqlite3.Cursor | _StreamingCursor:
        cursor = self._connection.execute(sql, parameters)
        normalised = " ".join(sql.split())
        if parameters and normalised == _PER_DECISION_SCOPE_QUERY:
            raise AssertionError("streamed OPEN cannot look up scopes per decision")
        if not parameters and normalised in _STREAMED_QUERIES:
            self.streamed_queries.append(normalised)
            return _StreamingCursor(cursor)
        return cursor


def _store(path: Path, service: object) -> _EventAuthorityStore:
    return _EventAuthorityStore(
        path,
        issuer=service._issuer,  # type: ignore[attr-defined]
        command_registry=service._registry,  # type: ignore[attr-defined]
        payload_schemas=service._payload_schemas,  # type: ignore[attr-defined]
        command_service_version="authority-command-v1",
        clock=lambda: FIXED_NOW,
    )


def test_core_immutable_record_validation_streams_every_full_table(
    tmp_path: Path,
) -> None:
    service = make_service()
    with _store(tmp_path / "authority.sqlite3", service) as store:
        for index in range(3):
            grant = service._authorize_for_commit(  # type: ignore[attr-defined]
                command(key=f"stream-{index}"), proof=proof()
            )
            store.commit(grant)

        connection = _StreamingConnection(store._connection)
        store._validate_immutable_records(connection)  # type: ignore[arg-type]

    assert frozenset(connection.streamed_queries) == _STREAMED_QUERIES


@pytest.mark.parametrize("tamper", ("missing", "mutated"))
def test_streamed_decision_validation_rejects_scope_corruption(
    tmp_path: Path, tamper: str
) -> None:
    service = make_service()
    with _store(tmp_path / "authority.sqlite3", service) as store:
        grant = service._authorize_for_commit(  # type: ignore[attr-defined]
            command(key="stream-corrupt"), proof=proof()
        )
        store.commit(grant)
        connection = store._connection
        if tamper == "missing":
            trigger = connection.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE name='immutable_authorization_decisions_update'"
            ).fetchone()[0]
            connection.execute("PRAGMA foreign_keys=OFF")
            connection.execute("DROP TRIGGER immutable_authorization_decisions_update")
            connection.execute(
                "UPDATE authorization_decisions SET scope_content_digest=?",
                ("sha256:" + "f" * 64,),
            )
            connection.execute(trigger)
            expected = "effective scopes are missing"
        else:
            trigger = connection.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE name='immutable_authorization_scope_contents_update'"
            ).fetchone()[0]
            row = connection.execute(
                "SELECT scope_content_digest,canonical_bytes "
                "FROM authorization_scope_contents LIMIT 1"
            ).fetchone()
            scopes = json.loads(bytes(row[1]))
            scopes[0] = scopes[0][:-1] + ("x" if scopes[0][-1] != "x" else "y")
            changed = canonical_json_bytes(scopes)
            assert changed != bytes(row[1]) and len(changed) == len(row[1])
            connection.execute(
                "DROP TRIGGER immutable_authorization_scope_contents_update"
            )
            connection.execute(
                "UPDATE authorization_scope_contents SET canonical_bytes=? "
                "WHERE scope_content_digest=?",
                (changed, row[0]),
            )
            connection.execute(trigger)
            expected = "effective scopes digest differs"

        with pytest.raises(AuthorityPersistenceError, match=expected):
            store._validate_immutable_records(  # type: ignore[arg-type]
                _StreamingConnection(connection)
            )


@pytest.mark.parametrize("record_position", (0, 1, 2))
@pytest.mark.parametrize("record_kind", ("payload", "result"))
def test_reopen_streams_and_rejects_tamper_at_every_position(
    tmp_path: Path, record_position: int, record_kind: str
) -> None:
    database = tmp_path / f"authority-{record_kind}-{record_position}.sqlite3"
    with open_test_system(database) as system:
        for index in range(3):
            system.commands.execute(command(key=f"record-{index}"), proof=proof())

    connection = sqlite3.connect(database)
    try:
        rows = connection.execute(
            "SELECT c.command_id,c.payload_id FROM authority_commands c "
            "JOIN ledger_events e ON e.command_id=c.command_id "
            "ORDER BY e.ledger_seq"
        ).fetchall()
        command_id, payload_id = rows[record_position]
        if record_kind == "payload":
            connection.execute("DROP TRIGGER immutable_authority_payloads_update")
            connection.execute(
                "UPDATE authority_payloads SET payload_bytes=? WHERE payload_id=?",
                (b'{"count":2,"headline":"tampered"}', payload_id),
            )
            connection.execute(_PAYLOAD_UPDATE_TRIGGER)
        else:
            connection.execute("DROP TRIGGER immutable_authority_commands_update")
            connection.execute(
                "UPDATE authority_commands SET result_bytes=? WHERE command_id=?",
                (b"{}", command_id),
            )
            connection.execute(_COMMAND_UPDATE_TRIGGER)
        connection.commit()
    finally:
        connection.close()

    expected = "payload digest" if record_kind == "payload" else "result digest"
    with pytest.raises(AuthorityPersistenceError, match=expected):
        open_test_system(database)
