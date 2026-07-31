from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from newsroom.graphiti_adapter import DeterministicFakeGraphitiAdapter

from .extraction_4a_helpers import extraction_proof
from .graphiti_adapter_4d_authority_helpers import (
    approval_from_authority,
    fake_attempt,
    open_graphiti_system,
    seed_graphiti_authority_fixture,
)


def _count(path, table: str) -> int:
    conn = sqlite3.connect(path)
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        conn.close()


def test_concurrent_identical_configuration_registration_is_one_commit_plus_replay(
    tmp_path,
) -> None:
    state = seed_graphiti_authority_fixture(tmp_path / "authority")
    request = fake_attempt(state)
    workspace_root = (tmp_path / "workspace").resolve()

    with open_graphiti_system(state, workspace_root=workspace_root) as system:
        def submit():
            return system.graphiti.register_configuration(
                request.configuration, proof=extraction_proof()
            )

        with ThreadPoolExecutor(max_workers=6) as executor:
            results = tuple(executor.map(lambda _index: submit(), range(6)))

    assert sum(not result.replayed for result in results) == 1
    assert sum(result.replayed for result in results) == 5
    assert len({result.authority_event_id for result in results}) == 1
    assert _count(state.database, "graphiti_adapter_configurations") == 1


def test_concurrent_identical_attempt_executes_adapter_once_and_replays(
    tmp_path, monkeypatch
) -> None:
    state = seed_graphiti_authority_fixture(tmp_path / "authority")
    request = fake_attempt(state)
    workspace_root = (tmp_path / "workspace").resolve()
    original = DeterministicFakeGraphitiAdapter.execute
    calls = 0
    calls_lock = Lock()

    def counted(self, *, attempt, workspace_root):
        nonlocal calls
        with calls_lock:
            calls += 1
        return original(self, attempt=attempt, workspace_root=workspace_root)

    monkeypatch.setattr(DeterministicFakeGraphitiAdapter, "execute", counted)
    with open_graphiti_system(state, workspace_root=workspace_root) as system:
        system.graphiti.register_configuration(
            request.configuration, proof=extraction_proof()
        )

        def submit():
            return system.graphiti.execute_attempt(
                request, proof=extraction_proof()
            )

        with ThreadPoolExecutor(max_workers=6) as executor:
            results = tuple(executor.map(lambda _index: submit(), range(6)))

    assert calls == 1
    assert sum(not result.replayed for result in results) == 1
    assert sum(result.replayed for result in results) == 5
    assert len({result.authority_event_id for result in results}) == 1
    assert _count(state.database, "graphiti_adapter_attempts") == 1
    assert _count(state.database, "extraction_run_versions") == 1
    assert not any(workspace_root.glob("*"))


def test_concurrent_identical_replay_approval_is_one_commit_plus_replay(
    tmp_path,
) -> None:
    state = seed_graphiti_authority_fixture(tmp_path / "authority")
    request = fake_attempt(state)
    workspace_root = (tmp_path / "workspace").resolve()
    with open_graphiti_system(state, workspace_root=workspace_root) as system:
        system.graphiti.register_configuration(
            request.configuration, proof=extraction_proof()
        )
        attempt = system.graphiti.execute_attempt(
            request, proof=extraction_proof()
        )
    approval_request = approval_from_authority(state, attempt)

    with open_graphiti_system(state, workspace_root=workspace_root) as system:
        def submit():
            return system.graphiti.approve_replay(
                approval_request, proof=extraction_proof()
            )

        with ThreadPoolExecutor(max_workers=6) as executor:
            results = tuple(executor.map(lambda _index: submit(), range(6)))

    assert sum(not result.replayed for result in results) == 1
    assert sum(result.replayed for result in results) == 5
    assert len({result.authority_event_id for result in results}) == 1
    assert _count(state.database, "graphiti_replay_sources") == 1
