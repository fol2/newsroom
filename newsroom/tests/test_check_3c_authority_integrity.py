from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from newsroom.authority import AuthorityPersistenceError, AuthoritySchemaError

from .check_3c_authority_helpers import open_check_system
from .test_check_3c_authority_store import seed_complete_fixture
from .source_3a_helpers import (
    VERSION_1_ID as SOURCE_VERSION_1_ID,
    VERSION_2_ID as SOURCE_VERSION_2_ID,
    definition_request as source_definition_request,
    item_request as source_item_request,
    occurrence_request as source_occurrence_request,
    open_source_system as open_source_only_system,
    proof as source_proof,
    representation_request as source_representation_request,
    revision_request as source_revision_request,
    version_request as source_version_request,
)


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


@pytest.mark.parametrize(
    ("column", "tampered_value"),
    (
        ("observed_items_bytes", b"[]"),
        ("observed_item_count", 0),
    ),
)
def test_startup_rejects_observed_item_provenance_tampering(
    tmp_path: Path,
    column: str,
    tampered_value: object,
) -> None:
    database = tmp_path / f"observed-item-{column}.sqlite3"
    seed_complete_fixture(database)

    with sqlite3.connect(database) as conn:
        trigger = _trigger_sql(conn, "immutable_check_outcomes_update")
        conn.execute("DROP TRIGGER immutable_check_outcomes_update")
        if column == "observed_item_count":
            conn.execute("PRAGMA ignore_check_constraints=ON")
        conn.execute(
            f"UPDATE check_outcomes SET {column}=?",
            (tampered_value,),
        )
        if column == "observed_item_count":
            conn.execute("PRAGMA ignore_check_constraints=OFF")
        conn.execute(trigger)
        conn.commit()

    with pytest.raises(
        AuthorityPersistenceError,
        match="Check Outcome|check_outcomes",
    ):
        open_check_system(database)


def test_startup_rejects_missing_observed_item_index_row(
    tmp_path: Path,
) -> None:
    database = tmp_path / "missing-observed-item-index.sqlite3"
    seed_complete_fixture(database)

    with sqlite3.connect(database) as conn:
        trigger = _trigger_sql(
            conn,
            "immutable_check_outcome_observed_items_delete",
        )
        conn.execute(
            "DROP TRIGGER immutable_check_outcome_observed_items_delete"
        )
        conn.execute("DELETE FROM check_outcome_observed_items")
        conn.execute(trigger)
        conn.commit()

    with pytest.raises(
        AuthorityPersistenceError,
        match="observed-item index",
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
        with pytest.raises(
            sqlite3.IntegrityError,
            match="immutable Check Outcome observed item",
        ):
            conn.execute(
                "UPDATE check_outcome_observed_items SET item_digest=?",
                ("sha256:" + "0" * 64,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="retained"):
            conn.execute("DELETE FROM observable_transitions")
        with pytest.raises(sqlite3.IntegrityError, match="invalid baseline-head"):
            conn.execute(
                "UPDATE baseline_decision_heads SET updated_at=?",
                ("2042-03-12T11:00:00.000000Z",),
            )


def test_check_startup_rejects_source_occurrence_without_retained_outcome(
    tmp_path: Path,
) -> None:
    database = tmp_path / "orphan-occurrence.sqlite3"
    with open_source_only_system(database) as source_system:
        source_system.sources.register_definition(
            source_definition_request(),
            proof=source_proof(),
        )
        source_system.sources.record_definition_version(
            source_version_request(),
            proof=source_proof(),
        )
        source_system.sources.register_item(
            source_item_request(),
            proof=source_proof(),
        )
        source_system.sources.record_definition_version(
            source_version_request(
                version_id=SOURCE_VERSION_2_ID,
                version_number=2,
                previous_version_id=SOURCE_VERSION_1_ID,
                locator="fixture://increment-3a/orphan-occurrence-v2",
                key="orphan-occurrence-source-version-v2",
            ),
            proof=source_proof(),
        )
        source_system.sources.record_revision(
            source_revision_request(),
            proof=source_proof(),
        )
        source_system.sources.record_representation(
            source_representation_request(),
            proof=source_proof(),
        )
        source_system.sources.record_occurrence(
            source_occurrence_request(),
            proof=source_proof(),
        )

    with pytest.raises(
        AuthorityPersistenceError,
        match="occurrence lacks exact Check link",
    ):
        open_check_system(database)


def test_startup_rejects_tampered_baseline_head_timestamp(
    tmp_path: Path,
) -> None:
    database = tmp_path / "baseline-head-time.sqlite3"
    seed_complete_fixture(database)

    with sqlite3.connect(database) as conn:
        trigger = _trigger_sql(conn, "baseline_head_update_guard")
        conn.execute("DROP TRIGGER baseline_head_update_guard")
        conn.execute(
            "UPDATE baseline_decision_heads SET updated_at=?",
            ("2042-03-12T12:00:00.000000Z",),
        )
        conn.execute(trigger)
        conn.commit()

    with pytest.raises(
        AuthorityPersistenceError,
        match="baseline head differs",
    ):
        open_check_system(database)
