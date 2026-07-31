from __future__ import annotations

import sqlite3

import pytest

from newsroom.authority.persistence import (
    AuthorityPersistenceError,
    AuthoritySchemaError,
)
from newsroom.extraction.types import FixtureExtractionCase
from newsroom.graphiti_adapter import GraphitiAdapterContractError

from .extraction_4a_helpers import extraction_proof
from .graphiti_adapter_4d_authority_helpers import (
    approval_from_authority,
    fake_attempt,
    open_graphiti_system,
    replay_attempt_for_next_version,
    seed_graphiti_authority_fixture,
)


def _seed_complete_authority(tmp_path):
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
        replay = system.graphiti.approve_replay(
            approval_request, proof=extraction_proof()
        )
    return state, request, attempt, replay, workspace_root


def _disable_trigger(conn: sqlite3.Connection, name: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",
        (name,),
    ).fetchone()
    assert row is not None and row[0]
    conn.execute(f'DROP TRIGGER "{name}"')
    return str(row[0])


def _expect_reopen_failure(state, workspace_root, match: str) -> None:
    with pytest.raises(
        (
            AuthorityPersistenceError,
            AuthoritySchemaError,
            GraphitiAdapterContractError,
        )
    ) as caught:
        open_graphiti_system(state, workspace_root=workspace_root)
    messages: list[str] = []
    current: BaseException | None = caught.value
    while current is not None:
        messages.append(str(current))
        current = current.__cause__
    assert any(match in message for message in messages), messages


@pytest.mark.parametrize(
    ("table", "column", "value", "message"),
    (
        (
            "graphiti_adapter_configurations",
            "execution_profile",
            "REPLAY",
            "immutable graphiti_adapter_configurations",
        ),
        (
            "graphiti_input_manifest_passages",
            "language",
            "en-US",
            "immutable graphiti_input_manifest_passages",
        ),
        (
            "graphiti_adapter_attempts",
            "failure_code",
            "TAMPERED",
            "immutable graphiti_adapter_attempts",
        ),
        (
            "graphiti_replay_sources",
            "eligibility",
            "MALFORMED_OUTPUT",
            "immutable graphiti_replay_sources",
        ),
    ),
)
def test_graphiti_authority_rows_are_immutable(
    tmp_path, table: str, column: str, value: str, message: str
) -> None:
    state, _request, _attempt, _replay, _workspace_root = _seed_complete_authority(
        tmp_path
    )
    conn = sqlite3.connect(state.database)
    try:
        with pytest.raises(sqlite3.IntegrityError, match=message):
            conn.execute(f"UPDATE {table} SET {column}=?", (value,))
    finally:
        conn.close()


def test_trigger_bypassed_manifest_passage_tamper_fails_checked_reopen(
    tmp_path,
) -> None:
    state, _request, _attempt, _replay, workspace_root = _seed_complete_authority(
        tmp_path
    )
    conn = sqlite3.connect(state.database)
    try:
        trigger = _disable_trigger(
            conn, "immutable_graphiti_input_manifest_passages_update"
        )
        conn.execute(
            "UPDATE graphiti_input_manifest_passages SET language='en-US' "
            "WHERE passage_ordinal=1"
        )
        conn.execute(trigger)
        conn.commit()
    finally:
        conn.close()

    _expect_reopen_failure(
        state, workspace_root, "manifest passage canonical data differs"
    )


def test_missing_attempt_head_fails_checked_reopen(tmp_path) -> None:
    state, _request, _attempt, _replay, workspace_root = _seed_complete_authority(
        tmp_path
    )
    conn = sqlite3.connect(state.database)
    try:
        trigger = _disable_trigger(conn, "graphiti_attempt_head_delete_guard")
        conn.execute("DELETE FROM graphiti_adapter_attempt_heads")
        conn.execute(trigger)
        conn.commit()
    finally:
        conn.close()

    _expect_reopen_failure(state, workspace_root, "attempt head is missing")


def test_missing_replay_binding_fails_checked_reopen(tmp_path) -> None:
    state = seed_graphiti_authority_fixture(
        tmp_path / "authority",
        fixture_case=FixtureExtractionCase.BILINGUAL_PARTIAL,
    )
    source_request = fake_attempt(
        state, fixture_case=FixtureExtractionCase.BILINGUAL_PARTIAL
    )
    workspace_root = (tmp_path / "workspace").resolve()
    with open_graphiti_system(state, workspace_root=workspace_root) as system:
        system.graphiti.register_configuration(
            source_request.configuration, proof=extraction_proof()
        )
        source_attempt = system.graphiti.execute_attempt(
            source_request, proof=extraction_proof()
        )
    approval_request = approval_from_authority(state, source_attempt)
    with open_graphiti_system(state, workspace_root=workspace_root) as system:
        approval = system.graphiti.approve_replay(
            approval_request, proof=extraction_proof()
        )
        replay_request = replay_attempt_for_next_version(
            state, source_attempt, approval.source
        )
        system.graphiti.register_configuration(
            replay_request.configuration, proof=extraction_proof()
        )
        system.graphiti.execute_attempt(
            replay_request, proof=extraction_proof()
        )

    conn = sqlite3.connect(state.database)
    try:
        trigger = _disable_trigger(
            conn, "immutable_graphiti_adapter_attempt_replays_delete"
        )
        conn.execute("DELETE FROM graphiti_adapter_attempt_replays")
        conn.execute(trigger)
        conn.commit()
    finally:
        conn.close()

    _expect_reopen_failure(
        state, workspace_root, "approved replay attempt requires exact replay source authority"
    )


def test_recreated_private_workspace_blocks_reopen_until_removed(tmp_path) -> None:
    state, request, _attempt, _replay, workspace_root = _seed_complete_authority(
        tmp_path
    )
    namespace = (
        f"{request.configuration.workspace_policy.namespace_prefix}-"
        f"{request.workspace_id}"
    )
    private = workspace_root / namespace
    private.mkdir(parents=True)
    try:
        _expect_reopen_failure(
            state, workspace_root, "workspace still exists after cleanup"
        )
    finally:
        private.rmdir()

    with open_graphiti_system(state, workspace_root=workspace_root):
        pass
