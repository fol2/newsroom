from __future__ import annotations

import sqlite3
import stat
from pathlib import Path

from newsroom.tests import test_increment6f2_feedback_store as feedback


def test_feedback_template_clones_are_file_and_object_isolated(tmp_path: Path) -> None:
    records = ("record-1",)
    feedback._location(tmp_path / "warm", records)
    first = feedback._location(tmp_path / "first", records)
    second = feedback._location(tmp_path / "second", records)
    snapshot = feedback._LOCATION_SNAPSHOTS[records]

    first_database = Path(first.candidate.seed[1])
    second_database = Path(second.candidate.seed[1])
    first_retrieval = Path(first.args["retrieval_authority"]._path)
    second_retrieval = Path(second.args["retrieval_authority"]._path)
    template_retrieval = Path(snapshot.seed_tail[0][1]._path)

    assert len({first_database, second_database}) == 2
    assert len({first_retrieval, second_retrieval, template_retrieval}) == 3
    assert first.args["retrieval_authority"] is not second.args["retrieval_authority"]
    assert stat.S_IMODE(first_database.stat().st_mode) == 0o600
    assert stat.S_IMODE(second_database.stat().st_mode) == 0o600
    assert stat.S_IMODE(first_retrieval.stat().st_mode) == 0o600
    assert stat.S_IMODE(second_retrieval.stat().st_mode) == 0o600

    template_database_bytes = snapshot.database_bytes
    template_retrieval_bytes = template_retrieval.read_bytes()
    second_retrieval_bytes = second_retrieval.read_bytes()
    with sqlite3.connect(first_database, isolation_level=None) as first_connection:
        with sqlite3.connect(
            second_database, isolation_level=None
        ) as second_connection:
            assert first_connection is not second_connection
            second_version = second_connection.execute("PRAGMA user_version").fetchone()
            first_connection.execute("PRAGMA user_version=1")
            assert (
                second_connection.execute("PRAGMA user_version").fetchone()
                == second_version
            )

    first_retrieval.write_bytes(first_retrieval.read_bytes() + b"isolated")
    assert snapshot.database_bytes == template_database_bytes
    assert template_retrieval.read_bytes() == template_retrieval_bytes
    assert second_retrieval.read_bytes() == second_retrieval_bytes
