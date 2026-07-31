from __future__ import annotations

from pathlib import Path
from typing import Callable

from newsroom.authority.types import UtcTimestamp
from newsroom.extraction.fixtures import fixture_case_for_contract
from newsroom.extraction.producer import DeterministicFixtureExtractor
from newsroom.extraction.types import FixtureExtractionCase

from .models import (
    GraphitiAdapterExecution,
    GraphitiAttemptRequest,
    GraphitiWorkspaceDescriptor,
    adapter_outcome_for,
)
from .types import (
    GraphitiAdapterContractError,
    GraphitiCleanupReason,
    GraphitiRuntimeMode,
)
from .workspace import DisposableProposalWorkspace


_REASON_BY_OUTCOME = {
    "COMPLETE": GraphitiCleanupReason.NORMAL,
    "PARTIAL": GraphitiCleanupReason.PARTIAL,
    "TIMEOUT": GraphitiCleanupReason.TIMEOUT,
    "MALFORMED_OUTPUT": GraphitiCleanupReason.MALFORMED_OUTPUT,
    "PROVIDER_REJECTED": GraphitiCleanupReason.PROVIDER_REJECTED,
    "POLICY_BLOCKED": GraphitiCleanupReason.POLICY_BLOCKED,
    "FAILED": GraphitiCleanupReason.FAILED,
    "AMBIGUOUS_EFFECT": GraphitiCleanupReason.AMBIGUOUS_EFFECT,
}


class DeterministicFakeGraphitiAdapter:
    """Repository-owned fake through the final proposal-only interface."""

    __slots__ = ("_clock", "_producer")

    def __init__(
        self,
        *,
        clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
    ) -> None:
        self._clock = clock
        self._producer = DeterministicFixtureExtractor()

    def execute(
        self,
        *,
        attempt: GraphitiAttemptRequest,
        workspace_root: object,
    ) -> GraphitiAdapterExecution:
        if not isinstance(attempt, GraphitiAttemptRequest):
            raise GraphitiAdapterContractError("fake adapter needs a typed attempt")
        if not isinstance(workspace_root, Path):
            raise GraphitiAdapterContractError(
                "fake adapter workspace root must be a pathlib Path"
            )
        configuration = attempt.configuration
        if configuration.runtime_mode is not GraphitiRuntimeMode.DETERMINISTIC_FAKE:
            raise GraphitiAdapterContractError(
                "deterministic fake rejects a non-fake configuration"
            )
        configuration.require_execution_authorized()
        fixture_case = fixture_case_for_contract(attempt.extraction_contract)
        if fixture_case is not configuration.fixture_case:
            raise GraphitiAdapterContractError(
                "adapter fixture case differs from the exact extractor contract"
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
            produced = self._producer.produce(
                contract=attempt.extraction_contract,
                request=attempt.extraction_request,
            )
            outcome = adapter_outcome_for(produced)
            nodes = tuple(
                {
                    "private_node_id": f"private-node-{index:04d}",
                    "proposal_local_id": proposal.local_id,
                    "proposal_kind": proposal.kind.value,
                    "proposal_digest": proposal.digest,
                }
                for index, proposal in enumerate(produced.proposals, start=1)
            )
            relations = tuple(
                {
                    "private_relation_id": f"private-relation-{index:04d}",
                    "proposal_local_id": proposal.local_id,
                    "predicate": proposal.predicate_hint.value,
                    "proposal_digest": proposal.digest,
                }
                for index, proposal in enumerate(
                    (
                        item
                        for item in produced.proposals
                        if item.predicate_hint is not None
                    ),
                    start=1,
                )
            )
            private.write_private_graph(nodes=nodes, relations=relations)
            ended_at = self._clock()
            cleanup = private.cleanup(
                receipt_id=attempt.cleanup_receipt_id,
                reason=_REASON_BY_OUTCOME[outcome.value],
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


__all__ = ["DeterministicFakeGraphitiAdapter"]
