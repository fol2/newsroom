from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from newsroom.authority import AuthorityPersistenceError, AuthoritySchemaError

from .check_3c_authority_helpers import open_check_system
from .test_check_3c_authority_store import seed_complete_fixture


def _trigger_sql(conn: sqlite3.Connection, name: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",
        (name,),
    ).fetchone()
    assert row is not None and isinstance(row[0], str)
    return str(row[0])


def test_startup_rejects_normalized_check_request_tampering(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seed_complete_fixture(database)

    with sqlite3.connect(database) as conn:
        trigger = _trigger_sql(conn, "immutable_check_requests_update")
        conn.execute("DROP TRIGGER immutable_check_requests_update")
        conn.execute(
            "UPDATE check_requests SET purpose=?",
            ("Tampered purpose outside canonical payload.",),
        )
        conn.execute(trigger)
        conn.commit()

    with pytest.raises(
        AuthorityPersistenceError,
        match="Check Request",
    ):
        open_check_system(database)


def test_startup_rejects_missing_post_v11_occurrence_link(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seed_complete_fixture(database)

    with sqlite3.connect(database) as conn:
        trigger = _trigger_sql(
            conn,
            "immutable_occurrence_check_links_delete",
        )
        conn.execute(
            "DROP TRIGGER immutable_occurrence_check_links_delete"
        )
        conn.execute("DELETE FROM discovery_occurrence_check_links")
        conn.execute(trigger)
        conn.commit()

    with pytest.raises(
        AuthorityPersistenceError,
        match="occurrence lacks exact Check link",
    ):
        open_check_system(database)


def test_startup_rejects_orphaned_check_outcome_history(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seed_complete_fixture(database)

    with sqlite3.connect(database) as conn:
        trigger = _trigger_sql(conn, "immutable_check_outcomes_delete")
        conn.execute("DROP TRIGGER immutable_check_outcomes_delete")
        conn.execute("DELETE FROM check_outcomes")
        conn.execute(trigger)
        conn.commit()

    with pytest.raises((AuthoritySchemaError, AuthorityPersistenceError)):
        open_check_system(database)


def test_check_tables_and_heads_are_immutable_under_normal_sql(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seed_complete_fixture(database)

    with sqlite3.connect(database) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="immutable Check Outcome"):
            conn.execute(
                "UPDATE check_outcomes SET reason_codes_bytes=?",
                (b"[]",),
            )
        with pytest.raises(sqlite3.IntegrityError, match="retained"):
            conn.execute("DELETE FROM observable_transitions")
        with pytest.raises(sqlite3.IntegrityError, match="invalid baseline-head"):
            conn.execute(
                "UPDATE baseline_decision_heads SET updated_at=?",
                ("2042-03-12T11:00:00.000000Z",),
            )
