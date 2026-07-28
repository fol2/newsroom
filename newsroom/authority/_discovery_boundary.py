from __future__ import annotations

from typing import Any, Callable, TypeVar

from newsroom.authority._security import _AuthorizationRequest
from newsroom.authority.auth import AuthenticationProof
from newsroom.authority.canonical import digest_canonical
from newsroom.authority.models import InlinePayload, SemanticCommand
from newsroom.authority.service import CommandService
from newsroom.authority.types import AggregateId, UtcTimestamp
from newsroom.discovery.models import (
    DiscoverySignalRequest,
    GateDecisionRequest,
    LeadDispositionDecisionRequest,
    NewsLeadRequest,
    WatchConditionRequest,
)
from newsroom.discovery.policy import (
    DISCOVERY_GATE_DECIDE_COMMAND,
    DISCOVERY_LEAD_DISPOSITION_RECORD_COMMAND,
    DISCOVERY_LEAD_OPEN_COMMAND,
    DISCOVERY_SIGNAL_ADMIT_COMMAND,
    DISCOVERY_WATCH_CONDITION_RECORD_COMMAND,
)
from newsroom.discovery.record_models import (
    DiscoverySignal,
    GateDecision,
    LeadDispositionDecision,
    NewsLead,
    WatchCondition,
)
from newsroom.discovery.read_models import DiscoveryCurrentStatus
from newsroom.discovery.types import (
    DiscoveryReadPolicy,
    DiscoverySignalId,
    GateDecisionId,
    LeadDispositionDecisionId,
    NewsLeadId,
    WatchConditionId,
)
from newsroom.sources import SourceRevisionId

from ._discovery_store import _DiscoveryAuthorityStore

_Record = TypeVar("_Record")
_DISCOVERY_READ_SCHEMA_DIGEST = digest_canonical(
    {
        "contract": "discovery-signal-lead-read-no-payload-v1",
        "payload_mode": "NO_PAYLOAD",
        "redaction": "typed-record-or-bounded-current-status",
    }
)


class _DiscoveryBoundary:
    """Authenticated command/read boundary for Increment 3D authority."""

    def __init__(
        self,
        *,
        store: _DiscoveryAuthorityStore,
        command_service: CommandService,
        authenticator: Any,
        authorizer: Any,
        read_policy: DiscoveryReadPolicy,
        clock: Callable[[], UtcTimestamp],
    ) -> None:
        self._store = store
        self._command_service = command_service
        self._authenticator = authenticator
        self._authorizer = authorizer
        self._read_policy = read_policy
        self._clock = clock

    def _commit(
        self,
        request: Any,
        proof: AuthenticationProof,
        *,
        command_type: str,
        aggregate_id: AggregateId,
        commit: Callable[..., _Record],
    ) -> _Record:
        command = SemanticCommand(
            command_type=command_type,
            aggregate_id=aggregate_id,
            expected_aggregate_version=0,
            payload=InlinePayload(request.canonical_value()),
            idempotency_key=request.idempotency_key,
        )
        grant = self._command_service._authorize_for_commit(command, proof=proof)
        return commit(grant, request=request)

    def admit_signal(
        self,
        request: DiscoverySignalRequest,
        proof: AuthenticationProof,
    ) -> DiscoverySignal:
        if not isinstance(request, DiscoverySignalRequest):
            raise TypeError("Discovery Signal must be typed")
        return self._commit(
            request,
            proof,
            command_type=DISCOVERY_SIGNAL_ADMIT_COMMAND,
            aggregate_id=AggregateId(request.signal_id.value),
            commit=self._store.commit_discovery_signal,
        )

    def decide_gate(
        self,
        request: GateDecisionRequest,
        proof: AuthenticationProof,
    ) -> GateDecision:
        if not isinstance(request, GateDecisionRequest):
            raise TypeError("Gate Decision must be typed")
        return self._commit(
            request,
            proof,
            command_type=DISCOVERY_GATE_DECIDE_COMMAND,
            aggregate_id=AggregateId(request.decision_id.value),
            commit=self._store.commit_gate_decision,
        )

    def open_lead(
        self,
        request: NewsLeadRequest,
        proof: AuthenticationProof,
    ) -> NewsLead:
        if not isinstance(request, NewsLeadRequest):
            raise TypeError("News Lead must be typed")
        return self._commit(
            request,
            proof,
            command_type=DISCOVERY_LEAD_OPEN_COMMAND,
            aggregate_id=AggregateId(request.lead_id.value),
            commit=self._store.commit_news_lead,
        )

    def record_watch_condition(
        self,
        request: WatchConditionRequest,
        proof: AuthenticationProof,
    ) -> WatchCondition:
        if not isinstance(request, WatchConditionRequest):
            raise TypeError("Watch Condition must be typed")
        return self._commit(
            request,
            proof,
            command_type=DISCOVERY_WATCH_CONDITION_RECORD_COMMAND,
            aggregate_id=AggregateId(request.watch_condition_id.value),
            commit=self._store.commit_watch_condition,
        )

    def record_lead_disposition(
        self,
        request: LeadDispositionDecisionRequest,
        proof: AuthenticationProof,
    ) -> LeadDispositionDecision:
        if not isinstance(request, LeadDispositionDecisionRequest):
            raise TypeError("Lead Disposition Decision must be typed")
        return self._commit(
            request,
            proof,
            command_type=DISCOVERY_LEAD_DISPOSITION_RECORD_COMMAND,
            aggregate_id=AggregateId(request.decision_id.value),
            commit=self._store.commit_lead_disposition,
        )

    def _authorize_read(
        self,
        proof: AuthenticationProof,
        *,
        operation: str,
        aggregate_type: str,
        aggregate_id: str,
        sensitive: bool,
        limit: int | None = None,
    ) -> None:
        now = self._clock()
        authentication = self._authenticator.authenticate(proof, now=now)
        authentication.require_current(now)
        self._read_policy.require_principal(authentication.principal_id)
        if limit is not None:
            self._read_policy.require_limit(limit)
        required_scope = (
            self._read_policy.sensitive_required_scope
            if sensitive
            else self._read_policy.metadata_required_scope
        )
        stable = digest_canonical(
            {
                "contract": "discovery-signal-lead-read-v1",
                "policy_digest": self._read_policy.digest,
                "operation": operation,
                "aggregate_type": aggregate_type,
                "aggregate_id": aggregate_id,
                "sensitive": sensitive,
                "limit": limit,
            }
        )
        unsigned = {
            "authentication_context_id": str(authentication.authentication_context_id),
            "principal_id": authentication.principal_id,
            "authority_domain": authentication.authority_domain,
            "operation_type": operation,
            "required_scope": required_scope,
            "stable_semantic_request_digest": stable,
            "command_definition_digest": _DISCOVERY_READ_SCHEMA_DIGEST,
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "event_type": "discovery.signal_lead.read",
            "event_schema_version": 1,
            "payload_mode": "NO_PAYLOAD",
            "payload_schema_version": "discovery_signal_lead_read_v1",
            "payload_schema_contract_version": (
                "discovery-signal-lead-read-no-payload-v1"
            ),
            "payload_schema_contract_digest": _DISCOVERY_READ_SCHEMA_DIGEST,
            "payload_canonicalizer_version": "discovery-signal-lead-none-v1",
            "trust_scope": "ADMITTED",
            "security_scope": "authority.discovery",
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
            command_definition_digest=_DISCOVERY_READ_SCHEMA_DIGEST,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type="discovery.signal_lead.read",
            event_schema_version=1,
            payload_mode="NO_PAYLOAD",
            payload_schema_version="discovery_signal_lead_read_v1",
            payload_schema_contract_version=(
                "discovery-signal-lead-read-no-payload-v1"
            ),
            payload_schema_contract_digest=_DISCOVERY_READ_SCHEMA_DIGEST,
            payload_canonicalizer_version="discovery-signal-lead-none-v1",
            trust_scope="ADMITTED",
            security_scope="authority.discovery",
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
            raise PermissionError("discovery read authorization provenance differs")
        decision.require_allowed()

    def signal(
        self,
        signal_id: DiscoverySignalId,
        proof: AuthenticationProof,
    ) -> DiscoverySignal:
        if not isinstance(signal_id, DiscoverySignalId):
            raise TypeError("Discovery Signal identity must be typed")
        self._authorize_read(
            proof,
            operation="read:discovery:signal",
            aggregate_type="discovery_signal",
            aggregate_id=str(signal_id),
            sensitive=True,
        )
        value = self._store.discovery_signal(signal_id)
        if value is None:
            raise LookupError("Discovery Signal is not retained")
        return value

    def gate(
        self,
        decision_id: GateDecisionId,
        proof: AuthenticationProof,
    ) -> GateDecision:
        if not isinstance(decision_id, GateDecisionId):
            raise TypeError("Gate Decision identity must be typed")
        self._authorize_read(
            proof,
            operation="read:discovery:gate",
            aggregate_type="gate_decision",
            aggregate_id=str(decision_id),
            sensitive=True,
        )
        value = self._store.gate_decision(decision_id)
        if value is None:
            raise LookupError("Gate Decision is not retained")
        return value

    def current_gate(
        self,
        signal_id: DiscoverySignalId,
        proof: AuthenticationProof,
    ) -> GateDecision:
        if not isinstance(signal_id, DiscoverySignalId):
            raise TypeError("Discovery Signal identity must be typed")
        self._authorize_read(
            proof,
            operation="read:discovery:current_gate",
            aggregate_type="discovery_signal",
            aggregate_id=str(signal_id),
            sensitive=False,
        )
        value = self._store.current_gate_decision(signal_id)
        if value is None:
            raise LookupError("current Gate Decision is not retained")
        return value

    def gates(
        self,
        signal_id: DiscoverySignalId,
        limit: int,
        proof: AuthenticationProof,
    ) -> tuple[GateDecision, ...]:
        if not isinstance(signal_id, DiscoverySignalId):
            raise TypeError("Discovery Signal identity must be typed")
        self._authorize_read(
            proof,
            operation="read:discovery:gates",
            aggregate_type="discovery_signal",
            aggregate_id=str(signal_id),
            sensitive=True,
            limit=limit,
        )
        return self._store.gate_decisions_for_signal(signal_id, limit=limit)

    def lead(self, lead_id: NewsLeadId, proof: AuthenticationProof) -> NewsLead:
        if not isinstance(lead_id, NewsLeadId):
            raise TypeError("News Lead identity must be typed")
        self._authorize_read(
            proof,
            operation="read:discovery:lead",
            aggregate_type="news_lead",
            aggregate_id=str(lead_id),
            sensitive=True,
        )
        value = self._store.news_lead(lead_id)
        if value is None:
            raise LookupError("News Lead is not retained")
        return value

    def lead_for_signal(
        self,
        signal_id: DiscoverySignalId,
        proof: AuthenticationProof,
    ) -> NewsLead:
        if not isinstance(signal_id, DiscoverySignalId):
            raise TypeError("Discovery Signal identity must be typed")
        self._authorize_read(
            proof,
            operation="read:discovery:lead_for_signal",
            aggregate_type="discovery_signal",
            aggregate_id=str(signal_id),
            sensitive=False,
        )
        value = self._store.lead_for_signal(signal_id)
        if value is None:
            raise LookupError("promoted Signal has no News Lead")
        return value

    def watch_condition(
        self,
        watch_id: WatchConditionId,
        proof: AuthenticationProof,
    ) -> WatchCondition:
        if not isinstance(watch_id, WatchConditionId):
            raise TypeError("Watch Condition identity must be typed")
        self._authorize_read(
            proof,
            operation="read:discovery:watch",
            aggregate_type="watch_condition",
            aggregate_id=str(watch_id),
            sensitive=True,
        )
        value = self._store.watch_condition(watch_id)
        if value is None:
            raise LookupError("Watch Condition is not retained")
        return value

    def disposition(
        self,
        decision_id: LeadDispositionDecisionId,
        proof: AuthenticationProof,
    ) -> LeadDispositionDecision:
        if not isinstance(decision_id, LeadDispositionDecisionId):
            raise TypeError("Lead Disposition Decision identity must be typed")
        self._authorize_read(
            proof,
            operation="read:discovery:disposition",
            aggregate_type="lead_disposition_decision",
            aggregate_id=str(decision_id),
            sensitive=True,
        )
        value = self._store.lead_disposition(decision_id)
        if value is None:
            raise LookupError("Lead Disposition Decision is not retained")
        return value

    def current_disposition(
        self,
        lead_id: NewsLeadId,
        proof: AuthenticationProof,
    ) -> LeadDispositionDecision:
        if not isinstance(lead_id, NewsLeadId):
            raise TypeError("News Lead identity must be typed")
        self._authorize_read(
            proof,
            operation="read:discovery:current_disposition",
            aggregate_type="news_lead",
            aggregate_id=str(lead_id),
            sensitive=False,
        )
        value = self._store.current_lead_disposition(lead_id)
        if value is None:
            raise LookupError("current Lead Disposition is not retained")
        return value

    def dispositions(
        self,
        lead_id: NewsLeadId,
        limit: int,
        proof: AuthenticationProof,
    ) -> tuple[LeadDispositionDecision, ...]:
        if not isinstance(lead_id, NewsLeadId):
            raise TypeError("News Lead identity must be typed")
        self._authorize_read(
            proof,
            operation="read:discovery:dispositions",
            aggregate_type="news_lead",
            aggregate_id=str(lead_id),
            sensitive=True,
            limit=limit,
        )
        return self._store.lead_dispositions(lead_id, limit=limit)

    def signals_for_revision(
        self,
        revision_id: SourceRevisionId,
        limit: int,
        proof: AuthenticationProof,
    ) -> tuple[DiscoverySignal, ...]:
        if not isinstance(revision_id, SourceRevisionId):
            raise TypeError("Source Revision identity must be typed")
        self._authorize_read(
            proof,
            operation="read:discovery:signals_for_revision",
            aggregate_type="source_revision",
            aggregate_id=str(revision_id),
            sensitive=True,
            limit=limit,
        )
        return self._store.signals_for_revision(str(revision_id), limit=limit)

    def current_status(
        self,
        signal_id: DiscoverySignalId,
        proof: AuthenticationProof,
    ) -> DiscoveryCurrentStatus:
        if not isinstance(signal_id, DiscoverySignalId):
            raise TypeError("Discovery Signal identity must be typed")
        self._authorize_read(
            proof,
            operation="read:discovery:current_status",
            aggregate_type="discovery_signal",
            aggregate_id=str(signal_id),
            sensitive=False,
        )
        return self._store.discovery_current_status(signal_id)


__all__ = ["_DiscoveryBoundary"]
