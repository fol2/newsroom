from __future__ import annotations

import sqlite3

import pytest

from newsroom.authority import AuthorityPersistenceError, canonical_json_bytes
from newsroom.authority.canonical import digest_bytes

from .authority_event_helpers import open_test_system
from .authority_helpers import command, proof
from .graphiti_adapter_4d_migration_helpers import _drop_v36_shared_scope_schema


def _v35_path(tmp_path):
    path = tmp_path / "authority.sqlite3"
    with open_test_system(path) as system:
        first = system.commands.execute(command(key="scope-one"), proof=proof())
        second = system.commands.execute(command(key="scope-two"), proof=proof())
        originals = tuple(
            (
                item.event_id,
                system.events.provenance(
                    item.event_id, proof=proof()
                ).authorization_decision,
            )
            for item in (first, second)
        )
    with sqlite3.connect(path) as connection:
        _drop_v36_shared_scope_schema(connection)
        connection.commit()
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 35
    return path, originals


def test_v35_decisions_migrate_to_one_lossless_scope_content(tmp_path) -> None:
    path, originals = _v35_path(tmp_path)
    with open_test_system(path) as system:
        rebuilt = tuple(
            system.events.provenance(event_id, proof=proof()).authorization_decision
            for event_id, _item in originals
        )
    assert tuple(item.canonical_bytes for item in rebuilt) == tuple(
        item.canonical_bytes for _event_id, item in originals
    )
    assert tuple(item.canonical_digest for item in rebuilt) == tuple(
        item.canonical_digest for _event_id, item in originals
    )
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 36
        assert connection.execute(
            "SELECT count(*) FROM authorization_scope_contents"
        ).fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("tamper", ("same_count_scope", "noncanonical_decision", "indexed_reason"))
def test_v35_conversion_rejects_contradiction_and_rolls_back(tmp_path, tamper: str) -> None:
    path, _ = _v35_path(tmp_path)
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER immutable_authorization_decisions_update")
        if tamper == "same_count_scope":
            raw = bytes(connection.execute(
                "SELECT effective_scopes FROM authorization_decisions LIMIT 1"
            ).fetchone()[0])
            connection.execute(
                "UPDATE authorization_decisions SET effective_scopes=? "
                "WHERE rowid=(SELECT min(rowid) FROM authorization_decisions)",
                (raw.replace(b"admitted", b"admittxd"),),
            )
        elif tamper == "noncanonical_decision":
            connection.execute(
                "UPDATE authorization_decisions SET canonical_bytes=X'7B207D' "
                "WHERE rowid=(SELECT min(rowid) FROM authorization_decisions)"
            )
        else:
            connection.execute(
                "UPDATE authorization_decisions SET reason_code='CHANGED' "
                "WHERE rowid=(SELECT min(rowid) FROM authorization_decisions)"
            )
        connection.commit()
    with pytest.raises((sqlite3.IntegrityError, sqlite3.DatabaseError)):
        with open_test_system(path):
            pass
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 35
        assert connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE name='authorization_scope_contents'"
        ).fetchone() is None


@pytest.mark.parametrize("tamper", ("shared_content", "retarget", "orphan"))
def test_reopen_rejects_shared_scope_corruption(tmp_path, tamper: str) -> None:
    path = tmp_path / "authority.sqlite3"
    with open_test_system(path) as system:
        first = system.commands.execute(command(key="scope-one"), proof=proof())
        system.commands.execute(command(key="scope-two"), proof=proof())
        before = system.events.provenance(first.event_id, proof=proof()).authorization_decision
    with sqlite3.connect(path) as connection:
        if tamper == "shared_content":
            connection.execute("DROP TRIGGER immutable_authorization_scope_contents_update")
            row = connection.execute(
                "SELECT scope_content_digest,canonical_bytes "
                "FROM authorization_scope_contents LIMIT 1"
            ).fetchone()
            changed = bytes(row[1]).replace(b"admitted", b"admittxd", 1)
            assert len(changed) == len(row[1]) and changed != row[1]
            connection.execute(
                "UPDATE authorization_scope_contents SET canonical_bytes=? "
                "WHERE scope_content_digest=?", (changed, row[0]),
            )
        else:
            decision_id = str(before.authorization_decision_id)
            connection.execute("DROP TRIGGER immutable_authorization_decisions_update")
            target = "sha256:" + ("f" if tamper == "retarget" else "e") * 64
            if tamper == "retarget":
                content = canonical_json_bytes(["authority.different"])
                target = digest_bytes(content)
                connection.execute(
                    "INSERT INTO authorization_scope_contents VALUES(?,?)",
                    (target, content),
                )
            else:
                connection.execute("PRAGMA foreign_keys=OFF")
            connection.execute(
                "UPDATE authorization_decisions SET scope_content_digest=? "
                "WHERE authorization_decision_id=?", (target, decision_id),
            )
    with pytest.raises((AuthorityPersistenceError, sqlite3.IntegrityError, sqlite3.DatabaseError)):
        with open_test_system(path):
            pass
