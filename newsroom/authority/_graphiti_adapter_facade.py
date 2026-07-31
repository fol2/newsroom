from __future__ import annotations

from collections.abc import Callable

from newsroom.authority.auth import AuthenticationProof
from newsroom.extraction.types import ExtractionRunId
from newsroom.graphiti_adapter import (
    GraphitiAdapterConfiguration,
    GraphitiAdapterConfigurationId,
    GraphitiAdapterConfigurationRecord,
    GraphitiAttemptId,
    GraphitiAttemptRecord,
    GraphitiAttemptRequest,
    GraphitiReplayApprovalRequest,
    GraphitiReplaySourceId,
    GraphitiReplaySourceRecord,
)


class GovernedGraphitiProposalAdapter:
    """Authenticated proposal-only facade with no raw output or private graph state."""

    __slots__ = (
        "__register_configuration",
        "__execute_attempt",
        "__approve_replay",
        "__configuration",
        "__attempt",
        "__attempt_history",
        "__replay_source",
    )

    def __init__(
        self,
        *,
        register_configuration: Callable[
            [GraphitiAdapterConfiguration, AuthenticationProof],
            GraphitiAdapterConfigurationRecord,
        ],
        execute_attempt: Callable[
            [GraphitiAttemptRequest, AuthenticationProof], GraphitiAttemptRecord
        ],
        approve_replay: Callable[
            [GraphitiReplayApprovalRequest, AuthenticationProof],
            GraphitiReplaySourceRecord,
        ],
        configuration: Callable[
            [GraphitiAdapterConfigurationId, AuthenticationProof],
            GraphitiAdapterConfigurationRecord,
        ],
        attempt: Callable[
            [GraphitiAttemptId, AuthenticationProof], GraphitiAttemptRecord
        ],
        attempt_history: Callable[
            [ExtractionRunId, int, AuthenticationProof],
            tuple[GraphitiAttemptRecord, ...],
        ],
        replay_source: Callable[
            [GraphitiReplaySourceId, AuthenticationProof],
            GraphitiReplaySourceRecord,
        ],
    ) -> None:
        self.__register_configuration = register_configuration
        self.__execute_attempt = execute_attempt
        self.__approve_replay = approve_replay
        self.__configuration = configuration
        self.__attempt = attempt
        self.__attempt_history = attempt_history
        self.__replay_source = replay_source

    def register_configuration(
        self,
        configuration: GraphitiAdapterConfiguration,
        *,
        proof: AuthenticationProof,
    ) -> GraphitiAdapterConfigurationRecord:
        return self.__register_configuration(configuration, proof)

    def execute_attempt(
        self,
        attempt: GraphitiAttemptRequest,
        *,
        proof: AuthenticationProof,
    ) -> GraphitiAttemptRecord:
        return self.__execute_attempt(attempt, proof)

    def approve_replay(
        self,
        request: GraphitiReplayApprovalRequest,
        *,
        proof: AuthenticationProof,
    ) -> GraphitiReplaySourceRecord:
        return self.__approve_replay(request, proof)

    def configuration(
        self,
        configuration_id: GraphitiAdapterConfigurationId,
        *,
        proof: AuthenticationProof,
    ) -> GraphitiAdapterConfigurationRecord:
        return self.__configuration(configuration_id, proof)

    def attempt(
        self,
        attempt_id: GraphitiAttemptId,
        *,
        proof: AuthenticationProof,
    ) -> GraphitiAttemptRecord:
        return self.__attempt(attempt_id, proof)

    def attempt_history(
        self,
        run_id: ExtractionRunId,
        *,
        limit: int,
        proof: AuthenticationProof,
    ) -> tuple[GraphitiAttemptRecord, ...]:
        return self.__attempt_history(run_id, limit, proof)

    def replay_source(
        self,
        replay_source_id: GraphitiReplaySourceId,
        *,
        proof: AuthenticationProof,
    ) -> GraphitiReplaySourceRecord:
        return self.__replay_source(replay_source_id, proof)


__all__ = ["GovernedGraphitiProposalAdapter"]
