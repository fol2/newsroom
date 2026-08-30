from __future__ import annotations

from dataclasses import replace

import pytest

from newsroom.authority.canonical import digest_canonical
from newsroom.extraction import ExtractionContractError
from newsroom.extraction.types import FixtureExtractionCase
from newsroom.graphiti_adapter import (
    ApprovedReplayBundle,
    ApprovedReplayGraphitiAdapter,
    DeterministicFakeGraphitiAdapter,
    GraphitiAdapterContractError,
    GraphitiAdapterOutcome,
    GraphitiAdapterStateError,
    GraphitiCleanupReason,
    GraphitiProposalProducerBridge,
    GraphitiReplayError,
    GraphitiReplayEligibility,
    GraphitiRuntimeMode,
)

from .extraction_4a_helpers import (
    seed_extraction_fixture,
    seed_homonym_extraction_fixture,
)
from .graphiti_adapter_4d_helpers import (
    ADAPTER_NOW,
    fake_attempt,
    produced_for,
    replay_attempt,
    replay_bundle,
    replay_source_for,
)


@pytest.mark.parametrize(
    ("fixture_case", "expected_outcome", "expected_reason", "proposal_count"),
    (
        (
            FixtureExtractionCase.BILINGUAL_COMPLETE,
            GraphitiAdapterOutcome.COMPLETE,
            GraphitiCleanupReason.NORMAL,
            4,
        ),
        (
            FixtureExtractionCase.BILINGUAL_PARTIAL,
            GraphitiAdapterOutcome.PARTIAL,
            GraphitiCleanupReason.PARTIAL,
            3,
        ),
        (
            FixtureExtractionCase.RETRYABLE_FAILURE,
            GraphitiAdapterOutcome.FAILED,
            GraphitiCleanupReason.FAILED,
            0,
        ),
        (
            FixtureExtractionCase.BLOCKING_FAILURE,
            GraphitiAdapterOutcome.PROVIDER_REJECTED,
            GraphitiCleanupReason.PROVIDER_REJECTED,
            0,
        ),
        (
            FixtureExtractionCase.INVALID_OUTPUT,
            GraphitiAdapterOutcome.MALFORMED_OUTPUT,
            GraphitiCleanupReason.MALFORMED_OUTPUT,
            0,
        ),
    ),
)
def test_deterministic_fake_uses_final_interface_and_always_cleans(
    tmp_path,
    fixture_case,
    expected_outcome,
    expected_reason,
    proposal_count,
) -> None:
    state = seed_extraction_fixture(tmp_path / "authority")
    attempt = fake_attempt(state, fixture_case=fixture_case)
    workspace_root = (tmp_path / "workspace").resolve()
    execution = DeterministicFakeGraphitiAdapter(
        clock=lambda: ADAPTER_NOW
    ).execute(attempt=attempt, workspace_root=workspace_root)

    assert execution.outcome is expected_outcome
    assert execution.cleanup_receipt.reason is expected_reason
    assert execution.cleanup_receipt.workspace_absent is True
    assert execution.cleanup_receipt.file_count == 1
    assert len(execution.produced.proposals) == proposal_count
    assert not (workspace_root / execution.workspace.namespace).exists()
    rendered = str(execution.canonical_value())
    assert "private-node" not in rendered
    assert "private-relation" not in rendered
    assert "cypher" not in rendered.lower()


def test_result_contract_allows_empty_terminal_success_but_not_failure_proposals(
    tmp_path,
) -> None:
    state = seed_extraction_fixture(tmp_path / "authority")

    def execute(fixture_case: FixtureExtractionCase, suffix: str):
        attempt = fake_attempt(state, fixture_case=fixture_case)
        return DeterministicFakeGraphitiAdapter(
            clock=lambda: ADAPTER_NOW
        ).execute(
            attempt=attempt,
            workspace_root=(tmp_path / f"workspace-{suffix}").resolve(),
        )

    complete = execute(FixtureExtractionCase.BILINGUAL_COMPLETE, "complete")
    partial = execute(FixtureExtractionCase.BILINGUAL_PARTIAL, "partial")
    failed = execute(FixtureExtractionCase.RETRYABLE_FAILURE, "failed")
    blocked = execute(FixtureExtractionCase.BLOCKING_FAILURE, "blocked")

    assert complete.outcome is GraphitiAdapterOutcome.COMPLETE
    assert complete.produced.proposals
    assert partial.outcome is GraphitiAdapterOutcome.PARTIAL
    assert partial.produced.proposals
    assert replace(
        complete,
        produced=replace(
            complete.produced,
            proposals=(),
            usage=replace(
                complete.produced.usage,
                proposal_count=0,
                evidence_range_count=0,
            ),
        ),
    ).outcome is GraphitiAdapterOutcome.COMPLETE
    assert replace(
        partial,
        produced=replace(
            partial.produced,
            proposals=(),
            usage=replace(
                partial.produced.usage,
                proposal_count=0,
                evidence_range_count=0,
            ),
        ),
    ).outcome is GraphitiAdapterOutcome.PARTIAL

    proposal = complete.produced.proposals[0]
    for execution in (failed, blocked):
        with pytest.raises(ExtractionContractError):
            replace(
                execution.produced,
                proposals=(proposal,),
                usage=replace(
                    execution.produced.usage,
                    proposal_count=1,
                    evidence_range_count=len(proposal.evidence),
                ),
            )


def test_homonym_fixture_runs_through_same_adapter_contract(tmp_path) -> None:
    state = seed_homonym_extraction_fixture(tmp_path / "authority")
    attempt = fake_attempt(
        state,
        fixture_case=FixtureExtractionCase.BILINGUAL_HOMONYM,
    )
    execution = DeterministicFakeGraphitiAdapter(
        clock=lambda: ADAPTER_NOW
    ).execute(
        attempt=attempt,
        workspace_root=(tmp_path / "workspace").resolve(),
    )
    assert execution.outcome is GraphitiAdapterOutcome.COMPLETE
    assert len(execution.produced.proposals) == 6
    assert execution.cleanup_receipt.private_node_count == 6
    assert execution.cleanup_receipt.workspace_absent is True


def test_fake_failure_after_activation_removes_workspace(tmp_path) -> None:
    state = seed_extraction_fixture(tmp_path / "authority")
    # The exact contract asks for the homonym fixture while the governed bytes
    # are the ordinary bilingual fixture. The producer must reject those bytes
    # after workspace activation, and the adapter must leave no private state.
    attempt = fake_attempt(
        state,
        fixture_case=FixtureExtractionCase.BILINGUAL_HOMONYM,
    )
    workspace_root = (tmp_path / "workspace").resolve()
    with pytest.raises(Exception, match="approved fixture bytes"):
        DeterministicFakeGraphitiAdapter(clock=lambda: ADAPTER_NOW).execute(
            attempt=attempt,
            workspace_root=workspace_root,
        )
    assert not (workspace_root / f"graphiti-qualification-{attempt.workspace_id}").exists()


def test_producer_bridge_is_exact_and_one_shot(tmp_path) -> None:
    state = seed_extraction_fixture(tmp_path / "authority")
    attempt = fake_attempt(state)
    bridge = GraphitiProposalProducerBridge(
        adapter=DeterministicFakeGraphitiAdapter(clock=lambda: ADAPTER_NOW),
        attempt=attempt,
        workspace_root=(tmp_path / "workspace").resolve(),
    )
    with pytest.raises(GraphitiAdapterStateError, match="before producer"):
        _ = bridge.execution
    produced = bridge.produce(
        contract=attempt.extraction_contract,
        request=attempt.extraction_request,
    )
    assert produced == bridge.execution.produced
    assert bridge.execution.outcome is GraphitiAdapterOutcome.COMPLETE
    with pytest.raises(GraphitiAdapterStateError, match="one-shot"):
        bridge.produce(
            contract=attempt.extraction_contract,
            request=attempt.extraction_request,
        )


def test_approved_replay_returns_exact_retained_result_without_fixture_execution(
    tmp_path,
) -> None:
    state = seed_extraction_fixture(tmp_path / "authority")
    source_attempt = fake_attempt(state)
    produced = produced_for(source_attempt)
    bundle = replay_bundle(source_attempt, produced)
    attempt = replay_attempt(source_attempt, bundle.source)
    assert attempt.configuration.runtime_mode is GraphitiRuntimeMode.APPROVED_REPLAY

    execution = ApprovedReplayGraphitiAdapter(
        bundle=bundle,
        clock=lambda: ADAPTER_NOW,
    ).execute(
        attempt=attempt,
        workspace_root=(tmp_path / "replay-workspace").resolve(),
    )
    assert execution.produced == produced
    assert execution.outcome is GraphitiAdapterOutcome.COMPLETE
    assert execution.cleanup_receipt.private_node_count == 0
    assert execution.cleanup_receipt.private_relation_count == 0
    assert execution.cleanup_receipt.workspace_absent is True


def test_malformed_output_is_eligible_for_exact_replay(tmp_path) -> None:
    state = seed_extraction_fixture(tmp_path / "authority")
    source_attempt = fake_attempt(
        state,
        fixture_case=FixtureExtractionCase.INVALID_OUTPUT,
    )
    produced = produced_for(source_attempt)
    bundle = replay_bundle(source_attempt, produced)
    assert bundle.source.eligibility is GraphitiReplayEligibility.MALFORMED_OUTPUT
    assert bundle.source.source_proposal_set_id is None

    attempt = replay_attempt(source_attempt, bundle.source)
    execution = ApprovedReplayGraphitiAdapter(
        bundle=bundle,
        clock=lambda: ADAPTER_NOW,
    ).execute(
        attempt=attempt,
        workspace_root=(tmp_path / "replay-workspace").resolve(),
    )
    assert execution.outcome is GraphitiAdapterOutcome.MALFORMED_OUTPUT
    assert execution.produced.raw_output_digest == produced.raw_output_digest


def test_replay_digest_or_source_change_fails_closed(tmp_path) -> None:
    state = seed_extraction_fixture(tmp_path / "authority")
    source_attempt = fake_attempt(state)
    produced = produced_for(source_attempt)
    source = replay_source_for(source_attempt, produced)

    with pytest.raises(GraphitiReplayError, match="payload digest"):
        ApprovedReplayBundle(
            source=replace(
                source,
                replay_payload_digest=digest_canonical({"changed": True}),
            ),
            produced=produced,
        )

    bundle = ApprovedReplayBundle(source=source, produced=produced)
    attempt = replay_attempt(source_attempt, source)
    changed = replace(
        source,
        approval_event_digest=digest_canonical({"approval": "changed"}),
    )
    with pytest.raises(GraphitiReplayError, match="differs"):
        ApprovedReplayGraphitiAdapter(
            bundle=bundle,
            clock=lambda: ADAPTER_NOW,
        ).execute(
            attempt=replace(attempt, replay_source=changed),
            workspace_root=(tmp_path / "changed-workspace").resolve(),
        )


def test_replay_rejects_ineligible_failed_output(tmp_path) -> None:
    state = seed_extraction_fixture(tmp_path / "authority")
    source_attempt = fake_attempt(
        state,
        fixture_case=FixtureExtractionCase.RETRYABLE_FAILURE,
    )
    produced = produced_for(source_attempt)
    complete_attempt = fake_attempt(state)
    complete_source = replay_source_for(complete_attempt, produced_for(complete_attempt))
    with pytest.raises(GraphitiReplayError, match="not eligible"):
        ApprovedReplayBundle(source=complete_source, produced=produced)
