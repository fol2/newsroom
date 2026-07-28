from __future__ import annotations

from typing import Callable

from newsroom.authority.auth import AuthenticationProof
from newsroom.discovery.admission_models import (
    SignalLeadAdmissionRequest,
    SignalLeadAdmissionResult,
)
from newsroom.discovery.models import (
    DiscoverySignalRequest,
    GateDecisionRequest,
    LeadDispositionDecisionRequest,
    NewsLeadRequest,
    WatchConditionRequest,
)
from newsroom.discovery.read_models import DiscoveryCurrentStatus
from newsroom.discovery.record_models import (
    DiscoverySignal,
    GateDecision,
    LeadDispositionDecision,
    NewsLead,
    WatchCondition,
)
from newsroom.discovery.types import (
    DiscoverySignalId,
    GateDecisionId,
    LeadDispositionDecisionId,
    NewsLeadId,
    WatchConditionId,
)
from newsroom.sources import SourceRevisionId


class GovernedDiscovery:
    """Typed public Signal/Gate/Lead facade; raw storage never escapes."""

    __slots__ = (
        "__admit_signal",
        "__decide_gate",
        "__open_lead",
        "__record_watch_condition",
        "__record_lead_disposition",
        "__admit_signal_to_lead",
        "__signal",
        "__gate",
        "__current_gate",
        "__gates",
        "__lead",
        "__lead_for_signal",
        "__watch_condition",
        "__disposition",
        "__current_disposition",
        "__dispositions",
        "__signals_for_revision",
        "__current_status",
    )

    def __init__(
        self,
        *,
        admit_signal: Callable[[DiscoverySignalRequest, AuthenticationProof], DiscoverySignal],
        decide_gate: Callable[[GateDecisionRequest, AuthenticationProof], GateDecision],
        open_lead: Callable[[NewsLeadRequest, AuthenticationProof], NewsLead],
        record_watch_condition: Callable[[WatchConditionRequest, AuthenticationProof], WatchCondition],
        record_lead_disposition: Callable[[LeadDispositionDecisionRequest, AuthenticationProof], LeadDispositionDecision],
        admit_signal_to_lead: Callable[[SignalLeadAdmissionRequest, AuthenticationProof], SignalLeadAdmissionResult],
        signal: Callable[[DiscoverySignalId, AuthenticationProof], DiscoverySignal],
        gate: Callable[[GateDecisionId, AuthenticationProof], GateDecision],
        current_gate: Callable[[DiscoverySignalId, AuthenticationProof], GateDecision],
        gates: Callable[[DiscoverySignalId, int, AuthenticationProof], tuple[GateDecision, ...]],
        lead: Callable[[NewsLeadId, AuthenticationProof], NewsLead],
        lead_for_signal: Callable[[DiscoverySignalId, AuthenticationProof], NewsLead],
        watch_condition: Callable[[WatchConditionId, AuthenticationProof], WatchCondition],
        disposition: Callable[[LeadDispositionDecisionId, AuthenticationProof], LeadDispositionDecision],
        current_disposition: Callable[[NewsLeadId, AuthenticationProof], LeadDispositionDecision],
        dispositions: Callable[[NewsLeadId, int, AuthenticationProof], tuple[LeadDispositionDecision, ...]],
        signals_for_revision: Callable[[SourceRevisionId, int, AuthenticationProof], tuple[DiscoverySignal, ...]],
        current_status: Callable[[DiscoverySignalId, AuthenticationProof], DiscoveryCurrentStatus],
    ) -> None:
        self.__admit_signal = admit_signal
        self.__decide_gate = decide_gate
        self.__open_lead = open_lead
        self.__record_watch_condition = record_watch_condition
        self.__record_lead_disposition = record_lead_disposition
        self.__admit_signal_to_lead = admit_signal_to_lead
        self.__signal = signal
        self.__gate = gate
        self.__current_gate = current_gate
        self.__gates = gates
        self.__lead = lead
        self.__lead_for_signal = lead_for_signal
        self.__watch_condition = watch_condition
        self.__disposition = disposition
        self.__current_disposition = current_disposition
        self.__dispositions = dispositions
        self.__signals_for_revision = signals_for_revision
        self.__current_status = current_status

    def admit_signal(self, request: DiscoverySignalRequest, *, proof: AuthenticationProof) -> DiscoverySignal:
        return self.__admit_signal(request, proof)

    def decide_gate(self, request: GateDecisionRequest, *, proof: AuthenticationProof) -> GateDecision:
        return self.__decide_gate(request, proof)

    def open_lead(self, request: NewsLeadRequest, *, proof: AuthenticationProof) -> NewsLead:
        return self.__open_lead(request, proof)

    def record_watch_condition(self, request: WatchConditionRequest, *, proof: AuthenticationProof) -> WatchCondition:
        return self.__record_watch_condition(request, proof)

    def record_lead_disposition(self, request: LeadDispositionDecisionRequest, *, proof: AuthenticationProof) -> LeadDispositionDecision:
        return self.__record_lead_disposition(request, proof)

    def admit_signal_to_lead(self, request: SignalLeadAdmissionRequest, *, proof: AuthenticationProof) -> SignalLeadAdmissionResult:
        return self.__admit_signal_to_lead(request, proof)

    def signal(self, signal_id: DiscoverySignalId, *, proof: AuthenticationProof) -> DiscoverySignal:
        return self.__signal(signal_id, proof)

    def gate(self, decision_id: GateDecisionId, *, proof: AuthenticationProof) -> GateDecision:
        return self.__gate(decision_id, proof)

    def current_gate(self, signal_id: DiscoverySignalId, *, proof: AuthenticationProof) -> GateDecision:
        return self.__current_gate(signal_id, proof)

    def gates(self, signal_id: DiscoverySignalId, *, limit: int, proof: AuthenticationProof) -> tuple[GateDecision, ...]:
        return self.__gates(signal_id, limit, proof)

    def lead(self, lead_id: NewsLeadId, *, proof: AuthenticationProof) -> NewsLead:
        return self.__lead(lead_id, proof)

    def lead_for_signal(self, signal_id: DiscoverySignalId, *, proof: AuthenticationProof) -> NewsLead:
        return self.__lead_for_signal(signal_id, proof)

    def watch_condition(self, watch_id: WatchConditionId, *, proof: AuthenticationProof) -> WatchCondition:
        return self.__watch_condition(watch_id, proof)

    def disposition(self, decision_id: LeadDispositionDecisionId, *, proof: AuthenticationProof) -> LeadDispositionDecision:
        return self.__disposition(decision_id, proof)

    def current_disposition(self, lead_id: NewsLeadId, *, proof: AuthenticationProof) -> LeadDispositionDecision:
        return self.__current_disposition(lead_id, proof)

    def dispositions(self, lead_id: NewsLeadId, *, limit: int, proof: AuthenticationProof) -> tuple[LeadDispositionDecision, ...]:
        return self.__dispositions(lead_id, limit, proof)

    def signals_for_revision(self, revision_id: SourceRevisionId, *, limit: int, proof: AuthenticationProof) -> tuple[DiscoverySignal, ...]:
        return self.__signals_for_revision(revision_id, limit, proof)

    def current_status(self, signal_id: DiscoverySignalId, *, proof: AuthenticationProof) -> DiscoveryCurrentStatus:
        return self.__current_status(signal_id, proof)


__all__ = ["GovernedDiscovery"]
