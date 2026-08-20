from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from threading import RLock
from typing import Any, Callable

from newsroom.authority._security import _AuthorizationRequest
from newsroom.authority.auth import AuthenticationProof
from newsroom.authority.canonical import digest_canonical
from newsroom.authority.models import InlinePayload, SemanticCommand
from newsroom.authority.service import CommandService
from newsroom.authority.types import AggregateId, TrustScope, UtcTimestamp
from newsroom.extraction.models import ExtractionUsage, ProducedExtraction
from newsroom.extraction.policy import EXTRACTION_RUN_EXECUTE_COMMAND
from newsroom.extraction.types import (
    ExtractionFailureCode,
    ExtractionOutcome,
    authority_elapsed_ms,
)
from newsroom.graphiti_adapter import (
    ApprovedReplayGraphitiAdapter,
    DeterministicFakeGraphitiAdapter,
    GraphitiAdapterConfiguration,
    GraphitiAdapterConfigurationId,
    GraphitiAdapterConfigurationRecord,
    GraphitiAdapterExecution,
    GraphitiAdapterOutcome,
    GraphitiAdapterReadPolicy,
    GraphitiAttemptId,
    GraphitiAttemptRecord,
    GraphitiAttemptRequest,
    GraphitiCleanupReason,
    GraphitiReplayApprovalRequest,
    GraphitiReplaySourceId,
    GraphitiReplaySourceRecord,
    GraphitiRuntimeMode,
)
from newsroom.graphiti_adapter.policy import (
    GRAPHITI_ATTEMPT_EXECUTE_COMMAND,
    GRAPHITI_CONFIGURATION_REGISTER_COMMAND,
    GRAPHITI_REPLAY_APPROVE_COMMAND,
)
from newsroom.graphiti_adapter.producer import GraphitiProposalProducerBridge
from newsroom.graphiti_adapter.real import RealGraphitiAdapter

from ._graphiti_adapter_store import _GraphitiAdapterAuthorityStore


_GRAPHITI_READ_SCHEMA_DIGEST = digest_canonical(
    {
        "contract": "graphiti-proposal-adapter-authority-read-no-payload-v1",
        "payload_mode": "NO_PAYLOAD",
        "surfaces": ["CONFIGURATION", "ATTEMPT", "REPLAY_APPROVAL"],
        "raw_output": "EXCLUDED",
    }
)


class _GraphitiAdapterBoundary:
    def __init__(
        self,
        *,
        store: _GraphitiAdapterAuthorityStore,
        command_service: CommandService,
        authenticator: Any,
        authorizer: Any,
        read_policy: GraphitiAdapterReadPolicy,
        workspace_root: Path,
        clock: Callable[[], UtcTimestamp],
    ) -> None:
        self._store = store
        self._command_service = command_service
        self._authenticator = authenticator
        self._authorizer = authorizer
        self._read_policy = read_policy
        self._workspace_root = workspace_root
        self._clock = clock
        self._command_lock = RLock()

    def register_configuration(
        self,
        configuration: GraphitiAdapterConfiguration,
        proof: AuthenticationProof,
    ) -> GraphitiAdapterConfigurationRecord:
        with self._command_lock:
            return self._register_configuration_locked(configuration, proof)

    def _register_configuration_locked(
        self,
        configuration: GraphitiAdapterConfiguration,
        proof: AuthenticationProof,
    ) -> GraphitiAdapterConfigurationRecord:
        if not isinstance(configuration, GraphitiAdapterConfiguration):
            raise TypeError("adapter configuration must be typed")
        command = SemanticCommand(
            command_type=GRAPHITI_CONFIGURATION_REGISTER_COMMAND,
            aggregate_id=AggregateId(configuration.configuration_id.value),
            expected_aggregate_version=0,
            payload=InlinePayload(configuration.canonical_value()),
            idempotency_key=configuration.idempotency_key,
        )
        grant = self._command_service._authorize_for_commit(command, proof=proof)
        return self._store.commit_graphiti_configuration(
            grant, configuration=configuration
        )

    @staticmethod
    def _normalized_execution(
        execution: GraphitiAdapterExecution,
    ) -> GraphitiAdapterExecution:
        elapsed_ms = authority_elapsed_ms(
            execution.started_at, execution.ended_at
        )
        request = execution.attempt.extraction_request
        if elapsed_ms > request.budget.timeout_ms:
            produced = ProducedExtraction(
                outcome=ExtractionOutcome.RETRYABLE_FAILURE,
                failure_code=ExtractionFailureCode.EXECUTION_TIMEOUT,
                validation=None,
                raw_output_value=None,
                proposals=(),
                usage=ExtractionUsage(
                    elapsed_ms=elapsed_ms,
                    input_bytes=request.input_binding.input_bytes,
                    output_bytes=0,
                    proposal_count=0,
                    evidence_range_count=0,
                    request_tokens=execution.produced.usage.request_tokens,
                    response_tokens=execution.produced.usage.response_tokens,
                    cost_microunits=execution.produced.usage.cost_microunits,
                ),
            )
            cleanup = replace(
                execution.cleanup_receipt,
                reason=GraphitiCleanupReason.TIMEOUT,
            )
            return GraphitiAdapterExecution(
                attempt=execution.attempt,
                outcome=GraphitiAdapterOutcome.TIMEOUT,
                failure_code=ExtractionFailureCode.EXECUTION_TIMEOUT.value,
                produced=produced,
                workspace=execution.workspace,
                cleanup_receipt=cleanup,
                started_at=execution.started_at,
                ended_at=execution.ended_at,
            )
        produced = replace(
            execution.produced,
            usage=replace(execution.produced.usage, elapsed_ms=elapsed_ms),
        )
        return replace(execution, produced=produced)

    def execute_attempt(
        self,
        attempt: GraphitiAttemptRequest,
        proof: AuthenticationProof,
    ) -> GraphitiAttemptRecord:
        with self._command_lock:
            return self._execute_attempt_locked(attempt, proof)

    def _execute_attempt_locked(
        self,
        attempt: GraphitiAttemptRequest,
        proof: AuthenticationProof,
    ) -> GraphitiAttemptRecord:
        if not isinstance(attempt, GraphitiAttemptRequest):
            raise TypeError("adapter attempt must be typed")
        adapter_command = SemanticCommand(
            command_type=GRAPHITI_ATTEMPT_EXECUTE_COMMAND,
            aggregate_id=AggregateId(attempt.attempt_id.value),
            expected_aggregate_version=0,
            payload=InlinePayload(attempt.canonical_value()),
            idempotency_key=attempt.idempotency_key,
        )
        adapter_grant = self._command_service._authorize_for_commit(
            adapter_command, proof=proof
        )
        if adapter_grant.replay_of_command_id is not None:
            return self._store.commit_graphiti_attempt(
                adapter_grant,
                None,
                attempt=attempt,
                execution=None,
            )

        self._store.preflight_graphiti_attempt(
            attempt=attempt,
            principal_id=adapter_grant.authentication.principal_id,
        )
        extraction_command = SemanticCommand(
            command_type=EXTRACTION_RUN_EXECUTE_COMMAND,
            aggregate_id=AggregateId(
                attempt.extraction_request.run_version_id.value
            ),
            expected_aggregate_version=0,
            payload=InlinePayload(attempt.extraction_request.canonical_value()),
            idempotency_key=attempt.extraction_request.idempotency_key,
        )
        extraction_grant = self._command_service._authorize_for_commit(
            extraction_command, proof=proof
        )
        if extraction_grant.replay_of_command_id is not None:
            return self._store.commit_graphiti_attempt(
                adapter_grant,
                extraction_grant,
                attempt=attempt,
                execution=None,
            )

        if attempt.configuration.runtime_mode is GraphitiRuntimeMode.DETERMINISTIC_FAKE:
            adapter = DeterministicFakeGraphitiAdapter(clock=self._clock)
        elif attempt.configuration.runtime_mode is GraphitiRuntimeMode.APPROVED_REPLAY:
            assert attempt.replay_source is not None
            bundle = self._store.approved_graphiti_replay_bundle(
                attempt.replay_source.replay_source_id
            )
            adapter = ApprovedReplayGraphitiAdapter(
                bundle=bundle,
                clock=self._clock,
            )
        else:
            attempt.configuration.require_execution_authorized()
            adapter = RealGraphitiAdapter(clock=self._clock)

        bridge = GraphitiProposalProducerBridge(
            adapter=adapter,
            attempt=attempt,
            workspace_root=self._workspace_root,
        )
        bridge.produce(
            contract=attempt.extraction_contract,
            request=attempt.extraction_request,
        )
        execution = self._normalized_execution(bridge.execution)
        return self._store.commit_graphiti_attempt(
            adapter_grant,
            extraction_grant,
            attempt=attempt,
            execution=execution,
        )

    def approve_replay(
        self,
        request: GraphitiReplayApprovalRequest,
        proof: AuthenticationProof,
    ) -> GraphitiReplaySourceRecord:
        with self._command_lock:
            return self._approve_replay_locked(request, proof)

    def _approve_replay_locked(
        self,
        request: GraphitiReplayApprovalRequest,
        proof: AuthenticationProof,
    ) -> GraphitiReplaySourceRecord:
        if not isinstance(request, GraphitiReplayApprovalRequest):
            raise TypeError("adapter replay approval must be typed")
        command = SemanticCommand(
            command_type=GRAPHITI_REPLAY_APPROVE_COMMAND,
            aggregate_id=AggregateId(request.replay_source_id.value),
            expected_aggregate_version=0,
            payload=InlinePayload(request.canonical_value()),
            idempotency_key=request.idempotency_key,
        )
        grant = self._command_service._authorize_for_commit(command, proof=proof)
        return self._store.commit_graphiti_replay_approval(grant, request=request)

    def _authorize_read(
        self,
        proof: AuthenticationProof,
        *,
        operation: str,
        aggregate_type: str,
        aggregate_id: str,
        required_scope: str,
        trust_scope: TrustScope,
        limit: int | None = None,
    ) -> None:
        now = self._clock()
        authentication = self._authenticator.authenticate(proof, now=now)
        authentication.require_current(now)
        self._read_policy.require_principal(authentication.principal_id)
        if limit is not None:
            self._read_policy.require_limit(limit)
        stable = digest_canonical(
            {
                "contract": "graphiti-proposal-adapter-authority-read-v1",
                "policy_digest": self._read_policy.digest,
                "operation": operation,
                "aggregate_type": aggregate_type,
                "aggregate_id": aggregate_id,
                "required_scope": required_scope,
                "trust_scope": trust_scope.value,
                "limit": limit,
            }
        )
        unsigned = {
            "authentication_context_id": str(
                authentication.authentication_context_id
            ),
            "principal_id": authentication.principal_id,
            "authority_domain": authentication.authority_domain,
            "operation_type": operation,
            "required_scope": required_scope,
            "stable_semantic_request_digest": stable,
            "command_definition_digest": _GRAPHITI_READ_SCHEMA_DIGEST,
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "event_type": "graphiti.adapter.authority.read",
            "event_schema_version": 1,
            "payload_mode": "NO_PAYLOAD",
            "payload_schema_version": "graphiti_adapter_authority_read_v1",
            "payload_schema_contract_version": (
                "graphiti-proposal-adapter-authority-read-no-payload-v1"
            ),
            "payload_schema_contract_digest": _GRAPHITI_READ_SCHEMA_DIGEST,
            "payload_canonicalizer_version": "graphiti-adapter-none-v1",
            "trust_scope": trust_scope.value,
            "security_scope": "authority.graphiti_adapter",
            "retention_scope": "authority.audit",
            "object_class": None,
            "allowed_use": None,
        }
        request = _AuthorizationRequest(
            authentication_context_id=authentication.authentication_context_id,
            principal_id=authentication.principal_id,
            authority_domain=authentication.authority_domain,
            operation_type=operation,
            required_scope=required_scope,
            stable_semantic_request_digest=stable,
            command_definition_digest=_GRAPHITI_READ_SCHEMA_DIGEST,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type="graphiti.adapter.authority.read",
            event_schema_version=1,
            payload_mode="NO_PAYLOAD",
            payload_schema_version="graphiti_adapter_authority_read_v1",
            payload_schema_contract_version=(
                "graphiti-proposal-adapter-authority-read-no-payload-v1"
            ),
            payload_schema_contract_digest=_GRAPHITI_READ_SCHEMA_DIGEST,
            payload_canonicalizer_version="graphiti-adapter-none-v1",
            trust_scope=trust_scope.value,
            security_scope="authority.graphiti_adapter",
            retention_scope="authority.audit",
            object_class=None,
            allowed_use=None,
            request_digest=digest_canonical(unsigned),
        )
        decision = self._authorizer.authorize(authentication, request, now=now)
        if (
            decision.authentication_context_id
            != authentication.authentication_context_id
            or decision.authorization_request_digest != request.request_digest
        ):
            raise PermissionError(
                "Graphiti adapter read authorization provenance differs"
            )
        decision.require_allowed()

    def configuration(
        self,
        configuration_id: GraphitiAdapterConfigurationId,
        proof: AuthenticationProof,
    ) -> GraphitiAdapterConfigurationRecord:
        self._authorize_read(
            proof,
            operation="read:graphiti_adapter:configuration",
            aggregate_type="graphiti_adapter_configuration",
            aggregate_id=str(configuration_id),
            required_scope=self._read_policy.configuration_required_scope,
            trust_scope=TrustScope.ADMITTED,
        )
        return self._store.graphiti_configuration(configuration_id)

    def attempt(
        self,
        attempt_id: GraphitiAttemptId,
        proof: AuthenticationProof,
    ) -> GraphitiAttemptRecord:
        self._authorize_read(
            proof,
            operation="read:graphiti_adapter:attempt",
            aggregate_type="graphiti_adapter_attempt",
            aggregate_id=str(attempt_id),
            required_scope=self._read_policy.attempt_required_scope,
            trust_scope=TrustScope.PROPOSED,
        )
        return self._store.graphiti_attempt(attempt_id)

    def attempt_history(
        self,
        run_id,
        limit: int,
        proof: AuthenticationProof,
    ) -> tuple[GraphitiAttemptRecord, ...]:
        self._authorize_read(
            proof,
            operation="read:graphiti_adapter:attempt_history",
            aggregate_type="graphiti_adapter_attempt_stream",
            aggregate_id=str(run_id),
            required_scope=self._read_policy.attempt_required_scope,
            trust_scope=TrustScope.PROPOSED,
            limit=limit,
        )
        return self._store.graphiti_attempt_history(run_id, limit=limit)

    def replay_source(
        self,
        replay_source_id: GraphitiReplaySourceId,
        proof: AuthenticationProof,
    ) -> GraphitiReplaySourceRecord:
        self._authorize_read(
            proof,
            operation="read:graphiti_adapter:replay_source",
            aggregate_type="graphiti_replay_source",
            aggregate_id=str(replay_source_id),
            required_scope=self._read_policy.replay_required_scope,
            trust_scope=TrustScope.ADMITTED,
        )
        return self._store.graphiti_replay_source(replay_source_id)


__all__ = ["_GraphitiAdapterBoundary"]
