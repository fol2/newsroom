from __future__ import annotations

from pathlib import Path
from typing import Callable

from newsroom.authority.types import UtcTimestamp

from .models import (
    ApprovedReplayBundle,
    GraphitiAdapterExecution,
    GraphitiAttemptRequest,
    GraphitiWorkspaceDescriptor,
    adapter_outcome_for,
)
from .types import (
    GraphitiAdapterContractError,
    GraphitiCleanupReason,
    GraphitiReplayError,
    GraphitiRuntimeMode,
)
from .workspace import DisposableProposalWorkspace


class ApprovedReplayGraphitiAdapter:
    """Read an explicitly approved retained result through the final interface."""

    __slots__ = ("_bundle", "_clock")

    def __init__(
        self,
        *,
        bundle: ApprovedReplayBundle,
        clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
    ) -> None:
        if not isinstance(bundle, ApprovedReplayBundle):
            raise GraphitiAdapterContractError("approved replay bundle must be typed")
        self._bundle = bundle
        self._clock = clock

    def execute(
        self,
        *,
        attempt: GraphitiAttemptRequest,
        workspace_root: object,
    ) -> GraphitiAdapterExecution:
        if not isinstance(attempt, GraphitiAttemptRequest):
            raise GraphitiAdapterContractError("replay adapter needs a typed attempt")
        if not isinstance(workspace_root, Path):
            raise GraphitiAdapterContractError(
                "replay adapter workspace root must be a pathlib Path"
            )
        configuration = attempt.configuration
        if configuration.runtime_mode is not GraphitiRuntimeMode.APPROVED_REPLAY:
            raise GraphitiAdapterContractError(
                "approved replay rejects a non-replay configuration"
            )
        configuration.require_execution_authorized()
        if attempt.replay_source != self._bundle.source:
            raise GraphitiReplayError(
                "attempt replay source differs from the approved retained bundle"
            )

        started_at = self._clock()
        workspace = GraphitiWorkspaceDescriptor(
            workspace_id=attempt.workspace_id,
            configuration_id=configuration.configuration_id,
            policy_id=configuration.workspace_policy.policy_id,
            policy_digest=configuration.workspace_policy.canonical_digest,
            namespace=(
                f"{configuration.workspace_policy.namespace_prefix}-"
                f"{str(attempt.workspace_id)}"
            ),
            created_at=started_at,
        )
        private = DisposableProposalWorkspace(
            root=workspace_root,
            descriptor=workspace,
            policy=configuration.workspace_policy,
        )
        private.activate()
        try:
            # A replay never runs Graphiti, a model, embeddings, or the fixture
            # producer.  The empty private graph proves the same disposable
            # workspace lifecycle without becoming a second authority store.
            private.write_private_graph(nodes=(), relations=())
            produced = self._bundle.produced
            outcome = adapter_outcome_for(produced)
            ended_at = self._clock()
            cleanup = private.cleanup(
                receipt_id=attempt.cleanup_receipt_id,
                reason=(
                    GraphitiCleanupReason.MALFORMED_OUTPUT
                    if outcome.value == "MALFORMED_OUTPUT"
                    else (
                        GraphitiCleanupReason.PARTIAL
                        if outcome.value == "PARTIAL"
                        else GraphitiCleanupReason.NORMAL
                    )
                ),
                recorded_at=ended_at,
            )
        except Exception:
            if private.exists:
                private.cleanup(
                    receipt_id=attempt.cleanup_receipt_id,
                    reason=GraphitiCleanupReason.FAILED,
                    recorded_at=self._clock(),
                )
            raise

        return GraphitiAdapterExecution(
            attempt=attempt,
            outcome=outcome,
            failure_code=produced.failure_code.value,
            produced=produced,
            workspace=workspace,
            cleanup_receipt=cleanup,
            started_at=started_at,
            ended_at=ended_at,
        )


__all__ = ["ApprovedReplayGraphitiAdapter"]
