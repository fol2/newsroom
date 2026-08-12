"""Deterministic Discovery Signal, gate, and News Lead contracts."""

from .admission_models import (
    SignalLeadAdmissionConflict,
    SignalLeadAdmissionError,
    SignalLeadAdmissionRequest,
    SignalLeadAdmissionResult,
)
from .models import (
    DiscoverySignalRequest,
    GateDecisionRequest,
    LeadDispositionDecisionRequest,
    NewsLeadRequest,
    WatchConditionRequest,
)
from .read_models import (
    DiscoveryCurrentActionSource,
    DiscoveryCurrentPhase,
    DiscoveryCurrentStatus,
)
from .record_models import (
    DiscoverySignal,
    GateDecision,
    LeadDispositionDecision,
    NewsLead,
    WatchCondition,
)
from .traceability import (
    INCREMENT_3D_DEFERRED,
    INCREMENT_3D_EXCLUSIONS,
    INCREMENT_3D_TRACEABILITY,
)
from .types import (
    ACTIVE_INCREMENT_3D_DISPOSITIONS,
    DecisionTerminality,
    DiscoveryAuthorityError,
    DiscoveryContractError,
    DiscoveryIdentifierReuse,
    DiscoveryReadPolicy,
    DiscoverySemanticCollision,
    DiscoverySignalId,
    DiscoveryStateError,
    DiscoveryVersionConflict,
    GateBasis,
    GateDecisionId,
    GateOutcome,
    LeadDispositionDecisionId,
    LeadDispositionOutcome,
    NewsLeadId,
    NextAction,
    NextActionKind,
    ObservableNewness,
    ReasonBasisClass,
    ReasonReference,
    ScopeDisposition,
    StructuredReason,
    TimeValidity,
    UrgencyBasis,
    UrgencyRoute,
    WatchConditionId,
    deterministic_gate_outcome,
    permitted_newness_for_transition,
)

_GOVERNING_PRODUCER_PORT_TOKEN = object()


class DiscoveryGoverningProducerReadPort:
    __slots__ = ("__read",)

    def __init__(self, token: object, read: object) -> None:
        if token is not _GOVERNING_PRODUCER_PORT_TOKEN or not callable(read):
            raise DiscoveryContractError("Discovery port is authority-private")
        self.__read = read

    def require_current_governing_producers(
        self, lead_ids: tuple[NewsLeadId, ...]
    ) -> tuple[tuple[NewsLead, DiscoverySignal, GateDecision], ...]:
        try:
            result = self.__read(lead_ids)
            if type(result) is not tuple or any(
                type(item) is not tuple
                or len(item) != 3
                or tuple(map(type, item)) != (NewsLead, DiscoverySignal, GateDecision)
                for item in result
            ):
                raise DiscoveryContractError("Discovery read returned forged records")
            return result
        except DiscoveryContractError:
            raise
        except Exception as exc:
            raise DiscoveryContractError("Discovery transaction read failed") from exc


def _compose_discovery_governing_producer_read_port(read: object):
    return DiscoveryGoverningProducerReadPort(_GOVERNING_PRODUCER_PORT_TOKEN, read)


__all__ = [  # noqa: RUF022 - preserve established public grouping
    "ACTIVE_INCREMENT_3D_DISPOSITIONS",
    "DecisionTerminality",
    "DiscoveryAuthorityError",
    "DiscoveryContractError",
    "DiscoveryCurrentActionSource",
    "DiscoveryCurrentPhase",
    "DiscoveryCurrentStatus",
    "DiscoveryGoverningProducerReadPort",
    "DiscoveryIdentifierReuse",
    "DiscoveryReadPolicy",
    "DiscoverySemanticCollision",
    "DiscoverySignal",
    "DiscoverySignalId",
    "DiscoverySignalRequest",
    "DiscoveryStateError",
    "DiscoveryVersionConflict",
    "INCREMENT_3D_DEFERRED",
    "INCREMENT_3D_EXCLUSIONS",
    "INCREMENT_3D_TRACEABILITY",
    "GateBasis",
    "GateDecision",
    "GateDecisionId",
    "GateDecisionRequest",
    "GateOutcome",
    "LeadDispositionDecision",
    "LeadDispositionDecisionId",
    "LeadDispositionDecisionRequest",
    "LeadDispositionOutcome",
    "NewsLead",
    "NewsLeadId",
    "NewsLeadRequest",
    "NextAction",
    "NextActionKind",
    "ObservableNewness",
    "ReasonBasisClass",
    "ReasonReference",
    "ScopeDisposition",
    "SignalLeadAdmissionConflict",
    "SignalLeadAdmissionError",
    "SignalLeadAdmissionRequest",
    "SignalLeadAdmissionResult",
    "StructuredReason",
    "TimeValidity",
    "UrgencyBasis",
    "UrgencyRoute",
    "WatchCondition",
    "WatchConditionId",
    "WatchConditionRequest",
    "deterministic_gate_outcome",
    "permitted_newness_for_transition",
]

from .payloads import (
    discovery_signal_payload,
    gate_decision_payload,
    lead_disposition_payload,
    news_lead_payload,
    watch_condition_payload,
)
from .policy import (
    DISCOVERY_GATE_DECIDE_COMMAND,
    DISCOVERY_LEAD_DISPOSITION_RECORD_COMMAND,
    DISCOVERY_LEAD_OPEN_COMMAND,
    DISCOVERY_SIGNAL_ADMIT_COMMAND,
    DISCOVERY_SIGNAL_LEAD_COMMAND_TYPES,
    DISCOVERY_WATCH_CONDITION_RECORD_COMMAND,
    discovery_signal_lead_command_definitions,
    discovery_signal_lead_payload_contracts,
    merge_discovery_signal_lead_registries,
)

__all__ += [
    "DISCOVERY_GATE_DECIDE_COMMAND",
    "DISCOVERY_LEAD_DISPOSITION_RECORD_COMMAND",
    "DISCOVERY_LEAD_OPEN_COMMAND",
    "DISCOVERY_SIGNAL_ADMIT_COMMAND",
    "DISCOVERY_SIGNAL_LEAD_COMMAND_TYPES",
    "DISCOVERY_WATCH_CONDITION_RECORD_COMMAND",
    "discovery_signal_lead_command_definitions",
    "discovery_signal_lead_payload_contracts",
    "discovery_signal_payload",
    "gate_decision_payload",
    "lead_disposition_payload",
    "merge_discovery_signal_lead_registries",
    "news_lead_payload",
    "watch_condition_payload",
]
