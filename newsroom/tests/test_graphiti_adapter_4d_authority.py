from __future__ import annotations

from dataclasses import replace

import pytest

from newsroom.graphiti_adapter import (
    GraphitiAdapterIdentifierReuse,
    GraphitiAdapterOutcome,
)

from .extraction_4a_helpers import extraction_proof
from .graphiti_adapter_4d_authority_helpers import (
    GRAPHITI_SCOPES,
    fake_attempt,
    open_graphiti_system,
    seed_graphiti_authority_fixture,
)


def test_configuration_and_fake_attempt_are_atomic_replayable_and_readable(
    tmp_path,
) -> None:
    state = seed_graphiti_authority_fixture(tmp_path / "authority")
    attempt = fake_attempt(state)
    workspace_root = (tmp_path / "workspace").resolve()

    with open_graphiti_system(
        state, workspace_root=workspace_root
    ) as system:
        configuration = system.graphiti.register_configuration(
            attempt.configuration, proof=extraction_proof()
        )
        replayed_configuration = system.graphiti.register_configuration(
            attempt.configuration, proof=extraction_proof()
        )
        assert configuration.replayed is False
        assert replayed_configuration.replayed is True

        retained = system.graphiti.execute_attempt(attempt, proof=extraction_proof())
        replayed = system.graphiti.execute_attempt(attempt, proof=extraction_proof())
        assert retained.outcome is GraphitiAdapterOutcome.COMPLETE
        assert retained.output_id is not None
        assert retained.proposal_set_id is not None
        assert retained.cleanup_receipt.workspace_absent is True
        assert replayed == replace(retained, replayed=True)
        assert system.graphiti.configuration(
            attempt.configuration.configuration_id,
            proof=extraction_proof(),
        ).configuration == attempt.configuration
        assert system.graphiti.attempt(
            attempt.attempt_id, proof=extraction_proof()
        ) == retained
        assert system.graphiti.manifest_for_attempt(
            attempt.attempt_id, proof=extraction_proof()
        ) == attempt.manifest
        assert system.graphiti.attempt_history(
            attempt.extraction_request.run_id,
            limit=10,
            proof=extraction_proof(),
        ) == (retained,)

    assert not workspace_root.joinpath(
        f"{attempt.configuration.workspace_policy.namespace_prefix}-"
        f"{attempt.workspace_id}"
    ).exists()

    with open_graphiti_system(
        state, workspace_root=workspace_root
    ) as reopened:
        assert reopened.graphiti.attempt(
            attempt.attempt_id, proof=extraction_proof()
        ).outcome is GraphitiAdapterOutcome.COMPLETE
        assert reopened.graphiti.manifest_for_attempt(
            attempt.attempt_id, proof=extraction_proof()
        ) == attempt.manifest


def test_configuration_identifier_reuse_and_read_scopes_fail_closed(tmp_path) -> None:
    state = seed_graphiti_authority_fixture(tmp_path / "authority")
    attempt = fake_attempt(state)
    workspace_root = (tmp_path / "workspace").resolve()

    with open_graphiti_system(state, workspace_root=workspace_root) as system:
        system.graphiti.register_configuration(
            attempt.configuration, proof=extraction_proof()
        )
        changed = replace(
            attempt.configuration,
            idempotency_key="increment-4d-qualification-config-v2",
            framework=replace(
                attempt.configuration.framework,
                component_version="graphiti-placeholder-v2",
            ),
        )
        with pytest.raises(GraphitiAdapterIdentifierReuse):
            system.graphiti.register_configuration(
                changed, proof=extraction_proof()
            )

    only_execute = frozenset(
        {
            "authority.graphiti.execute",
            "authority.extraction.execute",
        }
    )
    with open_graphiti_system(
        state,
        workspace_root=workspace_root,
        scopes=only_execute,
    ) as restricted:
        with pytest.raises(PermissionError):
            restricted.graphiti.configuration(
                attempt.configuration.configuration_id,
                proof=extraction_proof(),
            )


def test_approved_replay_uses_new_run_and_survives_workspace_loss(tmp_path) -> None:
    from .graphiti_adapter_4d_authority_helpers import (
        approval_from_authority,
        replay_attempt_for_next_version,
    )

    from newsroom.extraction.types import FixtureExtractionCase

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
        assert approval.replayed is False
        replay_request = replay_attempt_for_next_version(
            state, source_attempt, approval.source
        )
        system.graphiti.register_configuration(
            replay_request.configuration, proof=extraction_proof()
        )
        replay_attempt = system.graphiti.execute_attempt(
            replay_request, proof=extraction_proof()
        )
        assert replay_attempt.outcome is GraphitiAdapterOutcome.PARTIAL
        assert replay_attempt.output_id is not None
        assert replay_attempt.proposal_set_id is not None
        assert replay_attempt.cleanup_receipt.workspace_absent is True
        assert system.graphiti.replay_source(
            approval.source.replay_source_id,
            proof=extraction_proof(),
        ) == approval

    # Both workspaces are disposable. Checked reopen reads retained SQLite and
    # governed objects only; no private workspace is a recovery dependency.
    assert not any(workspace_root.glob("*"))
    with open_graphiti_system(state, workspace_root=workspace_root) as reopened:
        retained = reopened.graphiti.attempt(
            replay_request.attempt_id, proof=extraction_proof()
        )
        assert retained.outcome is GraphitiAdapterOutcome.PARTIAL


def test_complete_approved_replay_uses_retained_payload_without_fake_execution(
    tmp_path, monkeypatch
) -> None:
    from newsroom.graphiti_adapter import (
        ApprovedReplayGraphitiAdapter,
        DeterministicFakeGraphitiAdapter,
    )

    from .graphiti_adapter_4d_authority_helpers import (
        approval_from_authority,
        replay_attempt_for_new_budgeted_run,
    )

    state = seed_graphiti_authority_fixture(tmp_path / "authority")
    source_request = fake_attempt(state)
    workspace_root = (tmp_path / "workspace").resolve()
    with open_graphiti_system(state, workspace_root=workspace_root) as system:
        system.graphiti.register_configuration(
            source_request.configuration, proof=extraction_proof()
        )
        source_attempt = system.graphiti.execute_attempt(
            source_request, proof=extraction_proof()
        )
    approval_request = approval_from_authority(state, source_attempt)

    replay_calls = 0
    original_replay = ApprovedReplayGraphitiAdapter.execute

    def counted_replay(self, *, attempt, workspace_root):
        nonlocal replay_calls
        replay_calls += 1
        return original_replay(self, attempt=attempt, workspace_root=workspace_root)

    def forbidden_fake(*_args, **_kwargs):
        raise AssertionError("approved replay reran deterministic fake extraction")

    monkeypatch.setattr(ApprovedReplayGraphitiAdapter, "execute", counted_replay)
    monkeypatch.setattr(DeterministicFakeGraphitiAdapter, "execute", forbidden_fake)

    with open_graphiti_system(state, workspace_root=workspace_root) as system:
        approval = system.graphiti.approve_replay(
            approval_request, proof=extraction_proof()
        )
        replay_request = replay_attempt_for_new_budgeted_run(
            state, approval.source
        )
        system.graphiti.register_configuration(
            replay_request.configuration, proof=extraction_proof()
        )
        retained = system.graphiti.execute_attempt(
            replay_request, proof=extraction_proof()
        )
        replayed = system.graphiti.execute_attempt(
            replay_request, proof=extraction_proof()
        )

    assert replay_calls == 1
    assert retained.outcome is GraphitiAdapterOutcome.COMPLETE
    assert replayed == replace(retained, replayed=True)
    assert retained.cleanup_receipt.workspace_absent is True
    assert not any(workspace_root.glob("*"))
