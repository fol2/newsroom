from __future__ import annotations

import sqlite3
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from newsroom.tests import feedback_adapter_fastpath, feedback_cache_support
from newsroom.tests import test_increment6f2_feedback_store as feedback
from newsroom.tests.authority_store_conformance import AuthorityValue

_ROLLBACK_RECORDS = ("record-rollback-normal", "record-rollback-abort")


def test_feedback_template_clones_are_file_and_object_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selection = (
        (
            "newsroom/tests/test_increment6f2_feedback_cache.py::"
            "test_feedback_template_clones_are_file_and_object_isolated"
        ),
        (
            "newsroom/tests/test_increment6f2_feedback_store.py::"
            "test_real_feedback_store_passes_required_conformance_probe"
            "[transaction_rollback-abort]"
        ),
    )
    selected = feedback_cache_support._selected_keys(selection, feedback)
    assert _ROLLBACK_RECORDS in selected
    assert (
        feedback_cache_support._selected_keys(
            (
                "newsroom/tests/test_increment6f2_feedback_system.py::"
                + "test_accept_replay_snapshot_and_direct_tamper_fail_closed",
            ),
            feedback,
        )
        == ()
    )

    records = _ROLLBACK_RECORDS
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
    with (
        sqlite3.connect(first_database, isolation_level=None) as first_connection,
        sqlite3.connect(second_database, isolation_level=None) as second_connection,
    ):
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

    shared_candidate_seed = feedback.candidate_fixture._SeedSnapshot(
        b"candidate", ({"mutable": []},)
    )
    first_candidate_seed = shared_candidate_seed.fork()
    second_candidate_seed = shared_candidate_seed.fork()
    first_candidate_seed.tail[0]["mutable"].append("isolated")
    assert first_candidate_seed is not second_candidate_seed
    assert first_candidate_seed.tail[0] is not second_candidate_seed.tail[0]
    assert shared_candidate_seed.tail[0]["mutable"] == []
    assert second_candidate_seed.tail[0]["mutable"] == []
    candidate_retrieval_source = tmp_path / "candidate-retrieval-source.sqlite3"
    candidate_retrieval_source.write_bytes(b"retrieval")
    candidate_snapshot = feedback.candidate_fixture._SeedSnapshot(
        b"candidate", ((None, SimpleNamespace(_path=candidate_retrieval_source)),)
    )
    first_candidate_location = candidate_snapshot.clone(
        tmp_path / "candidate-location-first"
    )
    second_candidate_location = candidate_snapshot.clone(
        tmp_path / "candidate-location-second"
    )
    assert first_candidate_location[0][1] is not second_candidate_location[0][1]
    assert first_candidate_location[0][1]._path != second_candidate_location[0][1]._path

    selected = (("record-1",), _ROLLBACK_RECORDS)
    candidate_snapshot = object()
    system_seed = (object(), object(), object(), object())
    system_snapshot = object()
    candidate_builds = 0
    system_builds = 0
    locations: list[tuple[tuple[str, ...], object]] = []
    build_root = tmp_path / "single-candidate-seed"

    def seed_snapshot(root: Path) -> object:
        nonlocal candidate_builds
        candidate_builds += 1
        assert root == build_root / "candidate-seed"
        return candidate_snapshot

    def build_system_seed(
        root: Path, *, candidate_seed_snapshot: object
    ) -> tuple[object, ...]:
        nonlocal system_builds
        system_builds += 1
        assert root == build_root / "system-seed"
        assert candidate_seed_snapshot is candidate_snapshot
        return system_seed

    def build_location(
        root: Path,
        records: tuple[str, ...],
        *,
        system_seed: object | None = None,
        system_seed_snapshot: object | None = None,
    ) -> object:
        assert system_seed is None
        assert system_seed_snapshot is system_snapshot
        location = (records, root)
        locations.append(location)
        return location

    monkeypatch.setattr(feedback.candidate_fixture, "_seed_snapshot", seed_snapshot)
    monkeypatch.setattr(feedback.system_fixture, "_seed", build_system_seed)
    monkeypatch.setattr(feedback, "_build_location", build_location)
    monkeypatch.setattr(
        feedback_cache_support,
        "_system_seed_snapshot",
        lambda value: system_snapshot if value is system_seed else None,
    )
    monkeypatch.setattr(
        feedback_cache_support,
        "_snapshot",
        lambda location: {"location": location},
    )

    built = feedback_cache_support._build(selected, feedback, build_root)

    assert candidate_builds == 1
    assert system_builds == 1
    assert locations == [
        (("record-1",), build_root / "template-0"),
        (_ROLLBACK_RECORDS, build_root / "template-1"),
    ]
    assert built["template_keys"] == selected
    assert built["candidate_seed"] is candidate_snapshot
    assert built["system_seed"] is system_snapshot


def test_feedback_submit_uses_verified_result_and_reads_still_use_facade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feedback_adapter_fastpath._install(feedback)
    command = feedback.candidate_fixture._generic("record-rollback-normal")
    location = feedback._location(tmp_path / "fastpath", _ROLLBACK_RECORDS)
    handle = feedback._Handle(location)
    root = handle._opened()
    original_load = root.load

    def reject_redundant_read(*args: object, **kwargs: object) -> object:
        raise AssertionError("write result performed a redundant facade read")

    monkeypatch.setattr(root, "load", reject_redundant_read)
    monkeypatch.setattr(root, "dispositions", reject_redundant_read)
    try:
        assert handle.submit(command) == AuthorityValue.from_command(command)

        calls = 0

        def observed_load(*args: object, **kwargs: object) -> object:
            nonlocal calls
            calls += 1
            return original_load(*args, **kwargs)

        monkeypatch.setattr(root, "load", observed_load)
        assert handle.observe(command.record_id) is not None
        assert handle.history()
        assert calls == 1
    finally:
        handle.close()
