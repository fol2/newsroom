from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import (
    DiscoverySignalRequest,
    GateDecisionRequest,
    LeadDispositionDecisionRequest,
    NewsLeadRequest,
)
from .record_models import (
    DiscoverySignal,
    GateDecision,
    LeadDispositionDecision,
    NewsLead,
)
from .types import GateOutcome, LeadDispositionOutcome


class SignalLeadAdmissionError(RuntimeError):
    """Base error for deterministic Signal → Gate → Lead admission."""


class SignalLeadAdmissionConflict(SignalLeadAdmissionError):
    """The supplied admission plan conflicts with retained or typed authority."""


class AdmissionRecordState(StrEnum):
    CREATED = "CREATED"
    REUSED = "REUSED"
    REPLAYED = "REPLAYED"


@dataclass(frozen=True, slots=True)
class SignalLeadAdmissionRequest:
    signal: DiscoverySignalRequest
    gate: GateDecisionRequest
    lead: NewsLeadRequest | None
    initial_disposition: LeadDispositionDecisionRequest | None

    def __post_init__(self) -> None:
        if not isinstance(self.signal, DiscoverySignalRequest):
            raise TypeError("Signal admission requires a typed Signal request")
        if not isinstance(self.gate, GateDecisionRequest):
            raise TypeError("Signal admission requires a typed Gate request")
        if self.gate.signal_id != self.signal.signal_id:
            raise SignalLeadAdmissionConflict(
                "Gate Decision must consume the exact supplied Signal"
            )
        promoted = self.gate.outcome is GateOutcome.PROMOTED_TO_LEAD
        if promoted:
            if not isinstance(self.lead, NewsLeadRequest):
                raise SignalLeadAdmissionConflict(
                    "a promoted Signal requires one typed News Lead"
                )
            if not isinstance(
                self.initial_disposition,
                LeadDispositionDecisionRequest,
            ):
                raise SignalLeadAdmissionConflict(
                    "a promoted Signal requires one initial Lead disposition"
                )
            if (
                self.lead.signal_id != self.signal.signal_id
                or self.lead.promoting_gate_decision_id
                != self.gate.decision_id
                or self.lead.definition_id != self.signal.definition_id
                or self.lead.definition_version_id
                != self.gate.evaluated_definition_version_id
                or self.lead.item_id != self.signal.item_id
                or self.lead.revision_id != self.signal.revision_id
                or self.lead.representation_id != self.signal.representation_id
                or self.lead.occurrence_id != self.signal.occurrence_id
                or self.lead.transition_id != self.signal.transition_id
            ):
                raise SignalLeadAdmissionConflict(
                    "News Lead lineage differs from the exact promoted Signal"
                )
            if (
                self.initial_disposition.lead_id != self.lead.lead_id
                or self.initial_disposition.gate_decision_id
                != self.gate.decision_id
                or self.initial_disposition.decision_ordinal != 1
                or self.initial_disposition.previous_decision_id is not None
                or self.initial_disposition.outcome
                is not LeadDispositionOutcome.QUEUED_FOR_TRIAGE
                or self.initial_disposition.urgency_route != self.lead.urgency
            ):
                raise SignalLeadAdmissionConflict(
                    "initial Lead disposition must queue the exact new Lead"
                )
        elif self.lead is not None or self.initial_disposition is not None:
            raise SignalLeadAdmissionConflict(
                "non-promoting Gate Decision cannot create Lead authority"
            )


@dataclass(frozen=True, slots=True)
class SignalLeadAdmissionResult:
    signal: DiscoverySignal
    gate: GateDecision
    lead: NewsLead | None
    initial_disposition: LeadDispositionDecision | None
    signal_state: AdmissionRecordState
    gate_state: AdmissionRecordState
    lead_state: AdmissionRecordState | None
    disposition_state: AdmissionRecordState | None

    @property
    def replayed(self) -> bool:
        states = [self.signal_state, self.gate_state]
        if self.lead_state is not None:
            states.append(self.lead_state)
        if self.disposition_state is not None:
            states.append(self.disposition_state)
        return all(state is AdmissionRecordState.REPLAYED for state in states)


__all__ = [
    "AdmissionRecordState",
    "SignalLeadAdmissionConflict",
    "SignalLeadAdmissionError",
    "SignalLeadAdmissionRequest",
    "SignalLeadAdmissionResult",
]
