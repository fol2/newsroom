from __future__ import annotations

from typing import Any, Callable, TypeVar

from newsroom.authority._capability import _AuthorizedCommandGrant
from newsroom.authority.auth import AuthenticationProof
from newsroom.authority.models import InlinePayload, SemanticCommand
from newsroom.authority.service import CommandService
from newsroom.authority.types import AggregateId
from newsroom.discovery.admission_models import (
    AdmissionRecordState,
    SignalLeadAdmissionConflict,
    SignalLeadAdmissionRequest,
    SignalLeadAdmissionResult,
)
from newsroom.discovery.policy import (
    DISCOVERY_GATE_DECIDE_COMMAND,
    DISCOVERY_LEAD_DISPOSITION_RECORD_COMMAND,
    DISCOVERY_LEAD_OPEN_COMMAND,
    DISCOVERY_SIGNAL_ADMIT_COMMAND,
)
from newsroom.discovery.record_models import (
    DiscoverySignal,
    GateDecision,
    LeadDispositionDecision,
    NewsLead,
)
from newsroom.discovery.types import DiscoveryIdentifierReuse, DiscoverySemanticCollision

from ._discovery_store import _DiscoveryAuthorityStore

_Record = TypeVar("_Record")


class _SignalLeadAdmissionBoundary:
    """Crash-safe deterministic Signal → Gate → Lead admission.

    Every durable record remains an independently authorised command. All
    required grants are obtained before the first write, then exact replay
    resumes at the first missing record.
    """

    def __init__(
        self,
        *,
        store: _DiscoveryAuthorityStore,
        command_service: CommandService,
    ) -> None:
        self._store = store
        self._command_service = command_service

    def _authorize(
        self,
        request: Any,
        proof: AuthenticationProof,
        *,
        command_type: str,
        aggregate_id: AggregateId,
    ) -> _AuthorizedCommandGrant:
        return self._command_service._authorize_for_commit(
            SemanticCommand(
                command_type=command_type,
                aggregate_id=aggregate_id,
                expected_aggregate_version=0,
                payload=InlinePayload(request.canonical_value()),
                idempotency_key=request.idempotency_key,
            ),
            proof=proof,
        )

    @staticmethod
    def _state(record: Any) -> AdmissionRecordState:
        return (
            AdmissionRecordState.REPLAYED
            if bool(record.replayed)
            else AdmissionRecordState.CREATED
        )

    def _commit_or_reuse(
        self,
        *,
        commit: Callable[..., _Record],
        grant: _AuthorizedCommandGrant,
        request: Any,
        lookup: Callable[[Any], _Record | None],
        identifier: Any,
    ) -> tuple[_Record, AdmissionRecordState]:
        try:
            record = commit(grant, request=request)
            return record, self._state(record)
        except (DiscoveryIdentifierReuse, DiscoverySemanticCollision):
            retained = lookup(identifier)
            if retained is None or retained.canonical_digest != request.digest:
                raise
            return retained, AdmissionRecordState.REUSED

    def admit(
        self,
        request: SignalLeadAdmissionRequest,
        proof: AuthenticationProof,
    ) -> SignalLeadAdmissionResult:
        if not isinstance(request, SignalLeadAdmissionRequest):
            raise TypeError("Signal/Lead admission requires a typed plan")

        signal_grant = self._authorize(
            request.signal,
            proof,
            command_type=DISCOVERY_SIGNAL_ADMIT_COMMAND,
            aggregate_id=AggregateId(request.signal.signal_id.value),
        )
        gate_grant = self._authorize(
            request.gate,
            proof,
            command_type=DISCOVERY_GATE_DECIDE_COMMAND,
            aggregate_id=AggregateId(request.gate.decision_id.value),
        )
        lead_grant: _AuthorizedCommandGrant | None = None
        disposition_grant: _AuthorizedCommandGrant | None = None
        if request.lead is not None:
            lead_grant = self._authorize(
                request.lead,
                proof,
                command_type=DISCOVERY_LEAD_OPEN_COMMAND,
                aggregate_id=AggregateId(request.lead.lead_id.value),
            )
        if request.initial_disposition is not None:
            disposition_grant = self._authorize(
                request.initial_disposition,
                proof,
                command_type=DISCOVERY_LEAD_DISPOSITION_RECORD_COMMAND,
                aggregate_id=AggregateId(
                    request.initial_disposition.decision_id.value
                ),
            )

        signal, signal_state = self._commit_or_reuse(
            commit=self._store.commit_discovery_signal,
            grant=signal_grant,
            request=request.signal,
            lookup=self._store.discovery_signal,
            identifier=request.signal.signal_id,
        )
        if signal.request.signal_id != request.signal.signal_id:
            raise SignalLeadAdmissionConflict(
                "retained Signal identity differs from the authorised plan"
            )

        gate, gate_state = self._commit_or_reuse(
            commit=self._store.commit_gate_decision,
            grant=gate_grant,
            request=request.gate,
            lookup=self._store.gate_decision,
            identifier=request.gate.decision_id,
        )

        lead: NewsLead | None = None
        disposition: LeadDispositionDecision | None = None
        lead_state: AdmissionRecordState | None = None
        disposition_state: AdmissionRecordState | None = None
        if request.lead is not None:
            assert lead_grant is not None
            lead, lead_state = self._commit_or_reuse(
                commit=self._store.commit_news_lead,
                grant=lead_grant,
                request=request.lead,
                lookup=self._store.news_lead,
                identifier=request.lead.lead_id,
            )
        if request.initial_disposition is not None:
            assert disposition_grant is not None
            disposition, disposition_state = self._commit_or_reuse(
                commit=self._store.commit_lead_disposition,
                grant=disposition_grant,
                request=request.initial_disposition,
                lookup=self._store.lead_disposition,
                identifier=request.initial_disposition.decision_id,
            )

        return SignalLeadAdmissionResult(
            signal=signal,
            gate=gate,
            lead=lead,
            initial_disposition=disposition,
            signal_state=signal_state,
            gate_state=gate_state,
            lead_state=lead_state,
            disposition_state=disposition_state,
        )


__all__ = ["_SignalLeadAdmissionBoundary"]
