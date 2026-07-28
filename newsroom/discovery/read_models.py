from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .record_models import (
    DiscoverySignal,
    GateDecision,
    LeadDispositionDecision,
    NewsLead,
    WatchCondition,
)
from .types import GateOutcome, LeadDispositionOutcome, NextAction, UrgencyRoute


class DiscoveryCurrentPhase(StrEnum):
    SIGNAL_ADMITTED = "SIGNAL_ADMITTED"
    SIGNAL_SUPPRESSED = "SIGNAL_SUPPRESSED"
    SIGNAL_OPERATIONAL_HOLD = "SIGNAL_OPERATIONAL_HOLD"
    LEAD_QUEUED = "LEAD_QUEUED"
    LEAD_OPERATIONAL_HOLD = "LEAD_OPERATIONAL_HOLD"
    LEAD_WATCH_DEFER = "LEAD_WATCH_DEFER"


class DiscoveryCurrentActionSource(StrEnum):
    GATE_DECISION = "GATE_DECISION"
    LEAD_DISPOSITION = "LEAD_DISPOSITION"


@dataclass(frozen=True, slots=True)
class DiscoveryCurrentStatus:
    signal: DiscoverySignal
    current_gate: GateDecision
    lead: NewsLead | None
    current_disposition: LeadDispositionDecision | None
    watch_condition: WatchCondition | None
    phase: DiscoveryCurrentPhase
    action_source: DiscoveryCurrentActionSource
    next_action: NextAction | None
    urgency_route: UrgencyRoute | None

    def __post_init__(self) -> None:
        if self.current_gate.request.signal_id != self.signal.request.signal_id:
            raise ValueError("current Gate Decision differs from Signal")
        if self.lead is None:
            if self.current_disposition is not None or self.watch_condition is not None:
                raise ValueError("Signal-only current status cannot retain Lead state")
            if self.action_source is not DiscoveryCurrentActionSource.GATE_DECISION:
                raise ValueError("Signal-only status must derive action from Gate")
            if self.urgency_route is not None:
                raise ValueError("Signal-only status cannot claim Lead urgency")
        else:
            if self.lead.request.signal_id != self.signal.request.signal_id:
                raise ValueError("current Lead differs from Signal")
            if self.current_disposition is None:
                raise ValueError("Lead current status requires a disposition")
            if (
                self.current_disposition.request.lead_id
                != self.lead.request.lead_id
            ):
                raise ValueError("current disposition differs from Lead")
            if self.action_source is not DiscoveryCurrentActionSource.LEAD_DISPOSITION:
                raise ValueError("Lead status must derive action from disposition")
            if self.urgency_route != self.lead.request.urgency.route:
                raise ValueError("current status urgency differs from Lead")
        if self.phase is DiscoveryCurrentPhase.SIGNAL_SUPPRESSED and self.current_gate.request.outcome not in {
            GateOutcome.SUPPRESSED_DUPLICATE,
            GateOutcome.SUPPRESSED_NON_CHANGE,
            GateOutcome.REJECTED_CLEAR_EXCLUSION,
        }:
            raise ValueError("suppressed phase requires a terminal Gate suppression")
        if self.phase is DiscoveryCurrentPhase.SIGNAL_OPERATIONAL_HOLD and self.current_gate.request.outcome is not GateOutcome.OPERATIONAL_HOLD:
            raise ValueError("Signal hold phase requires operational-hold Gate")
        if self.phase is DiscoveryCurrentPhase.LEAD_QUEUED and self.current_disposition is not None and self.current_disposition.request.outcome is not LeadDispositionOutcome.QUEUED_FOR_TRIAGE:
            raise ValueError("queued phase requires queued Lead disposition")
        if self.phase is DiscoveryCurrentPhase.LEAD_OPERATIONAL_HOLD and self.current_disposition is not None and self.current_disposition.request.outcome is not LeadDispositionOutcome.OPERATIONAL_HOLD:
            raise ValueError("Lead hold phase requires operational-hold disposition")
        if self.phase is DiscoveryCurrentPhase.LEAD_WATCH_DEFER:
            if self.current_disposition is None or self.current_disposition.request.outcome is not LeadDispositionOutcome.WATCH_DEFER or self.watch_condition is None:
                raise ValueError("watch phase requires exact disposition and Watch Condition")


__all__ = [
    "DiscoveryCurrentActionSource",
    "DiscoveryCurrentPhase",
    "DiscoveryCurrentStatus",
]
