from __future__ import annotations

from contextlib import closing
import sqlite3

import pytest

from newsroom.graphiti_adapter import GraphitiAdapterRightsDenied
from newsroom.graphiti_adapter.policy import (
    merge_graphiti_adapter_authority_registries,
)

from .authority_a2b_helpers import open_object_system
from .extraction_4a_helpers import extraction_proof
from .graphiti_adapter_4d_authority_helpers import (
    approval_from_authority,
    fake_attempt,
    open_graphiti_system,
    seed_graphiti_authority_fixture,
)
from .source_3a_helpers import SOURCE_NOW, proof


def test_graphiti_adapter_reads_recheck_rights_after_object_revocation(
    tmp_path,
) -> None:
    state = seed_graphiti_authority_fixture(tmp_path / "authority")
    request = fake_attempt(state)
    workspace_root = (tmp_path / "workspace").resolve()
    with open_graphiti_system(state, workspace_root=workspace_root) as system:
        system.graphiti.register_configuration(
            request.configuration,
            proof=extraction_proof(),
        )
        attempt = system.graphiti.execute_attempt(
            request,
            proof=extraction_proof(),
        )
    approval_request = approval_from_authority(state, attempt)
    with open_graphiti_system(state, workspace_root=workspace_root) as system:
        replay = system.graphiti.approve_replay(
            approval_request,
            proof=extraction_proof(),
        )

    commands, schemas = merge_graphiti_adapter_authority_registries(
        command_registry=state.commands,
        payload_schemas=state.schemas,
    )
    with open_object_system(
        state.database,
        object_root=state.object_root,
        clock=lambda: SOURCE_NOW,
        command_registry=commands,
        payload_schema_registry=schemas,
    ) as objects:
        objects.objects.revoke(
            state.input_binding.passages[0].admission_id,
            reason_code="A2B_GRAPHITI_INPUT_REVOKED",
            idempotency_key="a2b-graphiti-input-revoked-v1",
            proof=proof(),
        )

    with open_graphiti_system(state, workspace_root=workspace_root) as reopened:
        assert reopened.graphiti.configuration(
            request.configuration.configuration_id,
            proof=extraction_proof(),
        ).configuration == request.configuration
        for operation in (
            lambda: reopened.graphiti.attempt(
                attempt.attempt_id,
                proof=extraction_proof(),
            ),
            lambda: reopened.graphiti.attempt_history(
                attempt.run_id,
                limit=10,
                proof=extraction_proof(),
            ),
            lambda: reopened.graphiti.replay_source(
                replay.source.replay_source_id,
                proof=extraction_proof(),
            ),
        ):
            with pytest.raises(GraphitiAdapterRightsDenied):
                operation()

    with closing(sqlite3.connect(state.database)) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM graphiti_adapter_configurations"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM graphiti_adapter_attempts"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM graphiti_replay_sources"
        ).fetchone()[0] == 1
