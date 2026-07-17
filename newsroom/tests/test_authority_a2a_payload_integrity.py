from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from newsroom.authority import AuthorityPersistenceError

from .authority_event_helpers import open_test_system
from .authority_helpers import command, proof


_IMMUTABLE_PAYLOAD_TRIGGER = """CREATE TRIGGER immutable_authority_payloads_update
BEFORE UPDATE ON authority_payloads BEGIN
SELECT RAISE(ABORT,'immutable authority payload'); END"""

_IMMUTABLE_EVENT_TRIGGER = """CREATE TRIGGER immutable_ledger_events_update
BEFORE UPDATE ON ledger_events BEGIN
SELECT RAISE(ABORT,'immutable ledger event'); END"""


def test_reopen_rehashes_exact_retained_payload_bytes(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    with open_test_system(database) as system:
        system.commands.execute(command(), proof=proof())

    conn = sqlite3.connect(database)
    try:
        conn.execute("DROP TRIGGER immutable_authority_payloads_update")
        conn.execute(
            "UPDATE authority_payloads SET payload_bytes=?",
            (b'{"count":2,"headline":"Tampered"}',),
        )
        conn.execute(_IMMUTABLE_PAYLOAD_TRIGGER)
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(AuthorityPersistenceError, match="payload digest"):
        open_test_system(database)


def test_reopen_revalidates_typed_event_identity(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    with open_test_system(database) as system:
        system.commands.execute(command(), proof=proof())

    conn = sqlite3.connect(database)
    try:
        conn.execute("DROP TRIGGER immutable_ledger_events_update")
        conn.execute("UPDATE ledger_events SET event_id='not-a-uuid'")
        conn.execute(_IMMUTABLE_EVENT_TRIGGER)
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(ValueError, match="identifier"):
        open_test_system(database)
