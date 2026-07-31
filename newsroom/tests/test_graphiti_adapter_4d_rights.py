from __future__ import annotations

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


def _combined_registries(state):
    return merge_graphiti_adapter_authority_registries(
        command_registry=state.commands,
        payload_schemas=state.schemas,
    )


def _seed_attempt_and_replay(tmp_path):
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
        approval = system.graphiti.approve_replay(
            approval_request, proof=extraction_proof()
        )
    return state, request, attempt, approval, workspace_root


def _assert_attempt_surfaces_denied(
    state, request, attempt, approval, workspace_root
) -> None:
    with open_graphiti_system(state, workspace_root=workspace_root) as reopened:
        # Configuration authority contains no hydrated source expression and
        # remains readable; attempts and replay sources are provenance-bound.
        assert reopened.graphiti.configuration(
            request.configuration.configuration_id,
            proof=extraction_proof(),
        ).configuration == request.configuration
        for operation in (
            lambda: reopened.graphiti.attempt(
                attempt.attempt_id, proof=extraction_proof()
            ),
            lambda: reopened.graphiti.attempt_history(
                attempt.run_id, limit=10, proof=extraction_proof()
            ),
            lambda: reopened.graphiti.replay_source(
                approval.source.replay_source_id,
                proof=extraction_proof(),
            ),
        ):
            with pytest.raises(GraphitiAdapterRightsDenied):
                operation()


def test_governed_object_revocation_blocks_attempt_and_replay_current_use(
    tmp_path,
) -> None:
    state, request, attempt, approval, workspace_root = _seed_attempt_and_replay(
        tmp_path
    )
    commands, schemas = _combined_registries(state)
    with open_object_system(
        state.database,
        object_root=state.object_root,
        clock=lambda: SOURCE_NOW,
        command_registry=commands,
        payload_schema_registry=schemas,
    ) as objects:
        objects.objects.revoke(
            state.input_binding.passages[0].admission_id,
            reason_code="GRAPHITI_ADAPTER_RIGHTS_REVOKED",
            idempotency_key="graphiti-adapter-revoke-input-v1",
            proof=proof(),
        )

    _assert_attempt_surfaces_denied(
        state, request, attempt, approval, workspace_root
    )


def test_governed_object_tombstone_blocks_replay_without_deleting_history(
    tmp_path,
) -> None:
    state, request, attempt, approval, workspace_root = _seed_attempt_and_replay(
        tmp_path
    )
    commands, schemas = _combined_registries(state)
    passage = state.input_binding.passages[0]
    with open_object_system(
        state.database,
        object_root=state.object_root,
        clock=lambda: SOURCE_NOW,
        command_registry=commands,
        payload_schema_registry=schemas,
    ) as objects:
        deletion = objects.objects.request_deletion(
            passage.blob_digest,
            reason_code="GRAPHITI_ADAPTER_DELETE_REQUESTED",
            idempotency_key="graphiti-adapter-delete-input-v1",
            proof=proof(),
        )
        objects.objects.tombstone(
            deletion.deletion_id,
            reason_code="GRAPHITI_ADAPTER_TOMBSTONED",
            idempotency_key="graphiti-adapter-tombstone-input-v1",
            proof=proof(),
        )

    _assert_attempt_surfaces_denied(
        state, request, attempt, approval, workspace_root
    )


def test_new_source_definition_version_blocks_attempt_and_replay_current_use(
    tmp_path,
) -> None:
    from newsroom.sources import (
        SourceDefinitionVersionId,
        open_governed_source_registry_authority_system,
    )

    from .source_3a_helpers import (
        VERSION_2_ID,
        authenticator,
        authorizer,
        read_policy,
        version_request,
    )

    state, request, attempt, approval, workspace_root = _seed_attempt_and_replay(
        tmp_path
    )
    commands, schemas = _combined_registries(state)
    version_3 = SourceDefinitionVersionId.parse(
        "00000000-0000-4000-8000-000000004981"
    )
    with open_governed_source_registry_authority_system(
        path=state.database,
        registry=commands,
        payload_schemas=schemas,
        authenticator=authenticator(),
        authorizer=authorizer(),
        read_policy=read_policy(),
        clock=lambda: SOURCE_NOW,
    ) as sources:
        sources.sources.record_definition_version(
            version_request(
                version_id=version_3,
                version_number=3,
                previous_version_id=VERSION_2_ID,
                locator="fixture://increment-4d/source-v3",
                key="increment-4d-source-version-v3",
            ),
            proof=proof(),
        )

    _assert_attempt_surfaces_denied(
        state, request, attempt, approval, workspace_root
    )
