"""Stable Triage Work Item identities and immutable version authority.

This is the sole Increment 6A2 public module.  It records bounded manifests;
it grants no Proposal, Candidate, publication, evidence, egress, or operational
authority.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Self

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.discovery import (
    LeadDispositionDecision,
    LeadDispositionOutcome,
    NewsLead,
    WatchCondition,
)
from newsroom.increment5.retrieval_context import (
    RetrievalContextOutcome,
    RetrievalContextReceipt,
    RetrievalContextRequest,
)
from newsroom.increment6.outcomes import PrioritySelection
from newsroom.increment6.proposals import WorkItemBinding

TRIAGE_WORK_ITEM = "newsroom.increment6.triage-work-item.v1"
TRIAGE_WORK_ITEM_VERSION = "newsroom.increment6.triage-work-item-version.v1"
WORK_ITEM_CURRENT_STALE_RULES = "USE_TIME_EXACT_HEAD_AND_UPSTREAM_CURRENTNESS"
LEAD_DISPOSITION_WORK_ITEM_BINDING = "EXACT_IMMUTABLE_LEAD_AND_DISPOSITION"
WATCH_CONDITION_WORK_ITEM_BINDING = "EXACT_IMMUTABLE_WATCH_PROVENANCE"
SUPPLEMENTAL_DISCOVERY_REENTRY = "NEW_GOVERNED_DISCOVERY_LINEAGE_ONLY"

MAX_DECISION_LEADS = 32
MAX_CONTEXT_LEADS = 32
MAX_VERSION_BYTES = 262_144
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class WorkItemContractError(ValueError):
    """A Work Item manifest, replay, or authority claim is invalid."""


class WorkItemStaleError(WorkItemContractError):
    """The current Work Item Version is stale or unusable."""


class RetrievalBindingState(StrEnum):
    REQUEST_PENDING = "REQUEST_PENDING"
    RECEIPT = "RECEIPT"


class ReentryKind(StrEnum):
    DEADLINE = "DEADLINE"
    REVIEW = "REVIEW"
    EXPIRY = "EXPIRY"
    OPERATOR_CONDITION = "OPERATOR_CONDITION"


def _digest(value: str, field: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise WorkItemContractError(f"{field} must be a canonical SHA-256 digest")
    return value


def _uuid(value: str, field: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise WorkItemContractError(f"{field} must be a canonical UUID") from exc
    if str(parsed) != value:
        raise WorkItemContractError(f"{field} must be a canonical UUID")
    return value


def _decode(raw: bytes, *, maximum: int = MAX_VERSION_BYTES) -> dict[str, object]:
    if not isinstance(raw, bytes) or not raw or len(raw) > maximum:
        raise WorkItemContractError("canonical input is not bounded immutable bytes")

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise WorkItemContractError(f"duplicate object name: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        MemoryError,
    ) as exc:
        raise WorkItemContractError("canonical input is invalid UTF-8 JSON") from exc
    pending: list[tuple[object, int]] = [(value, 1)]
    nodes = 0
    while pending:
        current, depth = pending.pop()
        nodes += 1
        if depth > 32 or nodes > 16_384:
            raise WorkItemContractError("canonical input exceeds structural bounds")
        if isinstance(current, dict):
            pending.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            pending.extend((item, depth + 1) for item in current)
    try:
        canonical = canonical_json_bytes(value)
    except (ValueError, TypeError, RecursionError, MemoryError) as exc:
        raise WorkItemContractError("canonical input cannot be normalised") from exc
    if not isinstance(value, dict) or canonical != raw:
        raise WorkItemContractError("input is not exact canonical JSON")
    return value


def _exact(value: object, fields: set[str], name: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise WorkItemContractError(f"{name} fields are not exact")
    return value


@dataclass(frozen=True, slots=True)
class DecisionLeadBinding:
    lead_id: str
    lead_digest: str
    lead_event_id: str
    lead_aggregate_version: int
    gate_decision_id: str
    definition_id: str
    definition_version_id: str
    disposition_id: str
    disposition_digest: str
    disposition_event_id: str
    disposition_aggregate_version: int
    disposition_ordinal: int
    previous_disposition_id: str | None
    disposition_outcome: str
    lead_bytes: bytes
    disposition_bytes: bytes

    @classmethod
    def from_authority(
        cls, lead: NewsLead, disposition: LeadDispositionDecision
    ) -> Self:
        if not isinstance(lead, NewsLead) or not isinstance(
            disposition, LeadDispositionDecision
        ):
            raise WorkItemContractError(
                "decision Lead binding requires authority records"
            )
        if disposition.request.lead_id != lead.request.lead_id:
            raise WorkItemContractError("Lead disposition belongs to another Lead")
        if disposition.request.outcome is not LeadDispositionOutcome.QUEUED_FOR_TRIAGE:
            raise WorkItemContractError("decision Lead must be queued for triage")
        return cls(
            str(lead.request.lead_id),
            lead.canonical_digest,
            str(lead.event_id),
            lead.aggregate_version,
            str(lead.request.promoting_gate_decision_id),
            str(lead.request.definition_id),
            str(lead.request.definition_version_id),
            str(disposition.request.decision_id),
            disposition.canonical_digest,
            str(disposition.event_id),
            disposition.aggregate_version,
            disposition.request.decision_ordinal,
            None
            if disposition.request.previous_decision_id is None
            else str(disposition.request.previous_decision_id),
            disposition.request.outcome.value,
            lead.request.canonical_bytes,
            disposition.request.canonical_bytes,
        )

    def __post_init__(self) -> None:
        for value, field in (
            (self.lead_id, "lead_id"),
            (self.gate_decision_id, "gate_decision_id"),
            (self.definition_id, "definition_id"),
            (self.definition_version_id, "definition_version_id"),
            (self.disposition_id, "disposition_id"),
        ):
            _uuid(value, field)
        _digest(self.lead_digest, "lead_digest")
        _digest(self.disposition_digest, "disposition_digest")
        if self.disposition_outcome != LeadDispositionOutcome.QUEUED_FOR_TRIAGE.value:
            raise WorkItemContractError("decision Lead disposition is not queued")
        if self.disposition_ordinal < 1 or (self.disposition_ordinal == 1) != (
            self.previous_disposition_id is None
        ):
            raise WorkItemContractError("Lead disposition predecessor differs")
        if (
            digest_bytes(self.lead_bytes) != self.lead_digest
            or digest_bytes(self.disposition_bytes) != self.disposition_digest
        ):
            raise WorkItemContractError("Lead binding canonical bytes differ")
        lead = _decode(self.lead_bytes)
        disposition = _decode(self.disposition_bytes)
        if (
            lead.get("lead_id") != self.lead_id
            or lead.get("promoting_gate_decision_id") != self.gate_decision_id
            or lead.get("definition_id") != self.definition_id
            or lead.get("definition_version_id") != self.definition_version_id
            or disposition.get("decision_id") != self.disposition_id
            or disposition.get("lead_id") != self.lead_id
            or disposition.get("decision_ordinal") != self.disposition_ordinal
            or disposition.get("previous_decision_id") != self.previous_disposition_id
            or disposition.get("outcome") != self.disposition_outcome
        ):
            raise WorkItemContractError(
                "Lead binding scalars differ from canonical bytes"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "lead_id": self.lead_id,
            "lead_digest": self.lead_digest,
            "lead_event_id": self.lead_event_id,
            "lead_aggregate_version": self.lead_aggregate_version,
            "gate_decision_id": self.gate_decision_id,
            "definition_id": self.definition_id,
            "definition_version_id": self.definition_version_id,
            "disposition_id": self.disposition_id,
            "disposition_digest": self.disposition_digest,
            "disposition_event_id": self.disposition_event_id,
            "disposition_aggregate_version": self.disposition_aggregate_version,
            "disposition_ordinal": self.disposition_ordinal,
            "previous_disposition_id": self.previous_disposition_id,
            "disposition_outcome": self.disposition_outcome,
            "lead": _decode(self.lead_bytes),
            "disposition": _decode(self.disposition_bytes),
        }

    @classmethod
    def from_value(cls, value: object) -> Self:
        fields = {
            "lead_id",
            "lead_digest",
            "lead_event_id",
            "lead_aggregate_version",
            "gate_decision_id",
            "definition_id",
            "definition_version_id",
            "disposition_id",
            "disposition_digest",
            "disposition_event_id",
            "disposition_aggregate_version",
            "disposition_ordinal",
            "previous_disposition_id",
            "disposition_outcome",
            "lead",
            "disposition",
        }
        item = _exact(value, fields, "decision Lead binding")
        return cls(
            str(item["lead_id"]),
            str(item["lead_digest"]),
            str(item["lead_event_id"]),
            int(item["lead_aggregate_version"]),
            str(item["gate_decision_id"]),
            str(item["definition_id"]),
            str(item["definition_version_id"]),
            str(item["disposition_id"]),
            str(item["disposition_digest"]),
            str(item["disposition_event_id"]),
            int(item["disposition_aggregate_version"]),
            int(item["disposition_ordinal"]),
            None
            if item["previous_disposition_id"] is None
            else str(item["previous_disposition_id"]),
            str(item["disposition_outcome"]),
            canonical_json_bytes(item["lead"]),
            canonical_json_bytes(item["disposition"]),
        )


@dataclass(frozen=True, slots=True)
class ContextLeadBinding:
    lead_id: str
    lead_digest: str
    gate_decision_id: str
    definition_id: str
    definition_version_id: str
    lead_bytes: bytes

    @classmethod
    def from_authority(cls, lead: NewsLead) -> Self:
        return cls(
            str(lead.request.lead_id),
            lead.canonical_digest,
            str(lead.request.promoting_gate_decision_id),
            str(lead.request.definition_id),
            str(lead.request.definition_version_id),
            lead.request.canonical_bytes,
        )

    def __post_init__(self) -> None:
        _uuid(self.lead_id, "context lead_id")
        _digest(self.lead_digest, "context lead_digest")
        if digest_bytes(self.lead_bytes) != self.lead_digest:
            raise WorkItemContractError("context Lead canonical bytes differ")
        lead = _decode(self.lead_bytes)
        if (
            lead.get("lead_id") != self.lead_id
            or lead.get("promoting_gate_decision_id") != self.gate_decision_id
            or lead.get("definition_id") != self.definition_id
            or lead.get("definition_version_id") != self.definition_version_id
        ):
            raise WorkItemContractError(
                "context Lead scalars differ from canonical bytes"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "lead_id": self.lead_id,
            "lead_digest": self.lead_digest,
            "gate_decision_id": self.gate_decision_id,
            "definition_id": self.definition_id,
            "definition_version_id": self.definition_version_id,
            "lead": _decode(self.lead_bytes),
        }

    @classmethod
    def from_value(cls, value: object) -> Self:
        item = _exact(
            value,
            {
                "lead_id",
                "lead_digest",
                "gate_decision_id",
                "definition_id",
                "definition_version_id",
                "lead",
            },
            "context Lead binding",
        )
        return cls(
            str(item["lead_id"]),
            str(item["lead_digest"]),
            str(item["gate_decision_id"]),
            str(item["definition_id"]),
            str(item["definition_version_id"]),
            canonical_json_bytes(item["lead"]),
        )


@dataclass(frozen=True, slots=True)
class RetrievalInputBinding:
    state: RetrievalBindingState
    request_id: str
    request_digest: str
    request_bytes: bytes
    context_id: str | None = None
    context_digest: str | None = None
    outcome: str | None = None
    reason: str | None = None
    no_match: bool = False
    receipt_bytes: bytes | None = None

    @classmethod
    def request_pending(cls, request: RetrievalContextRequest) -> Self:
        return cls(
            RetrievalBindingState.REQUEST_PENDING,
            str(request.request_id),
            request.request_digest,
            request.canonical_bytes,
        )

    @classmethod
    def from_receipt(
        cls, request: RetrievalContextRequest, receipt: RetrievalContextReceipt
    ) -> Self:
        if (
            request.request_digest != receipt.request_digest
            or str(request.request_id) != receipt.request_id
        ):
            raise WorkItemContractError("retrieval receipt belongs to another request")
        return cls(
            RetrievalBindingState.RECEIPT,
            receipt.request_id,
            receipt.request_digest,
            request.canonical_bytes,
            receipt.context_id,
            receipt.receipt_digest,
            receipt.outcome.value,
            None if receipt.reason is None else receipt.reason.value,
            receipt.no_match,
            receipt.canonical_bytes,
        )

    def __post_init__(self) -> None:
        _uuid(self.request_id, "retrieval request_id")
        _digest(self.request_digest, "retrieval request_digest")
        if digest_bytes(self.request_bytes) != self.request_digest:
            raise WorkItemContractError("retrieval request bytes differ")
        request = _decode(self.request_bytes)
        if request.get("request_id") != self.request_id:
            raise WorkItemContractError("retrieval request identity differs from bytes")
        if self.state is RetrievalBindingState.REQUEST_PENDING:
            if (
                any(
                    value is not None
                    for value in (
                        self.context_id,
                        self.context_digest,
                        self.outcome,
                        self.reason,
                        self.receipt_bytes,
                    )
                )
                or self.no_match
            ):
                raise WorkItemContractError("pending retrieval contains a receipt")
        elif (
            self.receipt_bytes is None
            or self.context_id is None
            or self.context_digest is None
            or self.outcome is None
        ):
            raise WorkItemContractError("retrieval receipt binding is incomplete")
        else:
            _uuid(self.context_id, "retrieval context_id")
            _digest(self.context_digest, "retrieval context_digest")
            if digest_bytes(self.receipt_bytes) != self.context_digest:
                raise WorkItemContractError("retrieval receipt bytes differ")
            receipt = _decode(self.receipt_bytes)
            if (
                receipt.get("context_id") != self.context_id
                or receipt.get("request_id") != self.request_id
                or receipt.get("request_digest") != self.request_digest
                or receipt.get("outcome") != self.outcome
                or receipt.get("reason") != self.reason
                or receipt.get("no_match") is not self.no_match
            ):
                raise WorkItemContractError(
                    "retrieval receipt scalars differ from bytes"
                )

    @property
    def usable(self) -> bool:
        return (
            self.state is RetrievalBindingState.RECEIPT
            and self.outcome == RetrievalContextOutcome.COMPLETE.value
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "request_id": self.request_id,
            "request_digest": self.request_digest,
            "request": _decode(self.request_bytes),
            "context_id": self.context_id,
            "context_digest": self.context_digest,
            "outcome": self.outcome,
            "reason": self.reason,
            "no_match": self.no_match,
            "receipt": None
            if self.receipt_bytes is None
            else _decode(self.receipt_bytes),
        }

    @classmethod
    def from_value(cls, value: object) -> Self:
        item = _exact(
            value,
            {
                "state",
                "request_id",
                "request_digest",
                "request",
                "context_id",
                "context_digest",
                "outcome",
                "reason",
                "no_match",
                "receipt",
            },
            "retrieval binding",
        )
        return cls(
            RetrievalBindingState(item["state"]),
            str(item["request_id"]),
            str(item["request_digest"]),
            canonical_json_bytes(item["request"]),
            None if item["context_id"] is None else str(item["context_id"]),
            None if item["context_digest"] is None else str(item["context_digest"]),
            None if item["outcome"] is None else str(item["outcome"]),
            None if item["reason"] is None else str(item["reason"]),
            item["no_match"] is True,
            None if item["receipt"] is None else canonical_json_bytes(item["receipt"]),
        )


@dataclass(frozen=True, slots=True)
class WatchConditionWorkItemBinding:
    watch_condition_id: str
    watch_condition_digest: str
    lead_id: str
    watch_bytes: bytes

    @classmethod
    def from_authority(cls, watch: WatchCondition) -> Self:
        return cls(
            str(watch.request.watch_condition_id),
            watch.canonical_digest,
            str(watch.request.lead_id),
            watch.request.canonical_bytes,
        )

    def __post_init__(self) -> None:
        _uuid(self.watch_condition_id, "watch_condition_id")
        _uuid(self.lead_id, "watch lead_id")
        _digest(self.watch_condition_digest, "watch_condition_digest")
        if digest_bytes(self.watch_bytes) != self.watch_condition_digest:
            raise WorkItemContractError("Watch Condition bytes differ")
        watch = _decode(self.watch_bytes)
        if (
            watch.get("watch_condition_id") != self.watch_condition_id
            or watch.get("lead_id") != self.lead_id
        ):
            raise WorkItemContractError("Watch Condition scalars differ from bytes")

    def canonical_value(self) -> dict[str, object]:
        return {
            "watch_condition_id": self.watch_condition_id,
            "watch_condition_digest": self.watch_condition_digest,
            "lead_id": self.lead_id,
            "watch": _decode(self.watch_bytes),
        }

    @classmethod
    def from_value(cls, value: object) -> Self:
        item = _exact(
            value,
            {"watch_condition_id", "watch_condition_digest", "lead_id", "watch"},
            "Watch binding",
        )
        return cls(
            str(item["watch_condition_id"]),
            str(item["watch_condition_digest"]),
            str(item["lead_id"]),
            canonical_json_bytes(item["watch"]),
        )


@dataclass(frozen=True, slots=True)
class SupplementalDiscoveryReentry:
    source_work_item_id: str
    source_version_id: str
    source_version_digest: str
    source_lead_disposition_id: str
    watch: WatchConditionWorkItemBinding | None
    trigger_id: str
    check_request_id: str
    check_outcome_id: str
    signal_id: str
    gate_decision_id: str
    lead_id: str
    queued_disposition_id: str
    target_work_item_id: str
    target_version_id: str
    target_version_digest: str
    proposal_only_action: bool = False
    source_disposition_authorises_trigger: bool = False
    lineage_bindings: tuple[SupplementalLineageBinding, ...] = ()

    def __post_init__(self) -> None:
        for field in (
            "source_work_item_id",
            "source_version_id",
            "source_lead_disposition_id",
            "trigger_id",
            "check_request_id",
            "check_outcome_id",
            "signal_id",
            "gate_decision_id",
            "lead_id",
            "queued_disposition_id",
            "target_work_item_id",
            "target_version_id",
        ):
            _uuid(getattr(self, field), field)
        _digest(self.source_version_digest, "source_version_digest")
        _digest(self.target_version_digest, "target_version_digest")
        if self.proposal_only_action:
            raise WorkItemContractError(
                "proposal-only action cannot establish supplemental discovery"
            )
        if self.source_disposition_authorises_trigger:
            raise WorkItemContractError(
                "v18 does not prove Trigger authority from a source disposition"
            )
        if (
            self.source_work_item_id == self.target_work_item_id
            or self.source_version_id == self.target_version_id
        ):
            raise WorkItemContractError(
                "supplemental discovery must create a new Work Item lineage"
            )
        kinds = tuple(item.kind for item in self.lineage_bindings)
        expected = (
            "TRIGGER",
            "CHECK_REQUEST",
            "CHECK_OUTCOME",
            "SIGNAL",
            "GATE",
            "LEAD",
            "QUEUED_DISPOSITION",
        )
        if kinds != expected:
            raise WorkItemContractError(
                "supplemental discovery requires the exact governed lineage"
            )
        ids = (
            self.trigger_id,
            self.check_request_id,
            self.check_outcome_id,
            self.signal_id,
            self.gate_decision_id,
            self.lead_id,
            self.queued_disposition_id,
        )
        for index, (binding, identifier) in enumerate(
            zip(self.lineage_bindings, ids, strict=True)
        ):
            if binding.identifier != identifier or (
                index and binding.parent_id != ids[index - 1]
            ):
                raise WorkItemContractError(
                    "supplemental discovery lineage binding differs"
                )

    def canonical_value(self) -> dict[str, object]:
        return {
            field: getattr(self, field)
            for field in (
                "source_work_item_id",
                "source_version_id",
                "source_version_digest",
                "source_lead_disposition_id",
                "trigger_id",
                "check_request_id",
                "check_outcome_id",
                "signal_id",
                "gate_decision_id",
                "lead_id",
                "queued_disposition_id",
                "target_work_item_id",
                "target_version_id",
                "target_version_digest",
                "proposal_only_action",
                "source_disposition_authorises_trigger",
            )
        } | {
            "watch": None if self.watch is None else self.watch.canonical_value(),
            "lineage_bindings": [
                item.canonical_value() for item in self.lineage_bindings
            ],
        }


@dataclass(frozen=True, slots=True)
class SupplementalLineageBinding:
    kind: str
    identifier: str
    digest: str
    parent_id: str | None
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        _uuid(self.identifier, "supplemental lineage identity")
        if self.parent_id is not None:
            _uuid(self.parent_id, "supplemental lineage parent")
        _digest(self.digest, "supplemental lineage digest")
        if digest_bytes(self.canonical_bytes) != self.digest:
            raise WorkItemContractError("supplemental lineage bytes differ")
        value = _decode(self.canonical_bytes)
        if self.identifier not in value.values():
            raise WorkItemContractError("supplemental lineage identity is not retained")

    def canonical_value(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "identifier": self.identifier,
            "digest": self.digest,
            "parent_id": self.parent_id,
            "record": _decode(self.canonical_bytes),
        }


def _sorted_decision(
    value: tuple[DecisionLeadBinding, ...],
) -> tuple[DecisionLeadBinding, ...]:
    if not 1 <= len(value) <= MAX_DECISION_LEADS or any(
        not isinstance(v, DecisionLeadBinding) for v in value
    ):
        raise WorkItemContractError("decision Leads must be a bounded typed tuple")
    result = tuple(sorted(value, key=lambda v: v.lead_id))
    if len({v.lead_id for v in result}) != len(result):
        raise WorkItemContractError("decision Leads duplicate")
    return result


@dataclass(frozen=True, slots=True)
class TriageWorkItem:
    work_item_id: str
    decision_leads: tuple[DecisionLeadBinding, ...]
    decision_scope_digest: str
    schema_identity: str = TRIAGE_WORK_ITEM

    @classmethod
    def create(cls, decision_leads: tuple[DecisionLeadBinding, ...]) -> Self:
        leads = _sorted_decision(decision_leads)
        identity = [
            {
                "lead_id": v.lead_id,
                "lead_digest": v.lead_digest,
                "initial_disposition_id": v.disposition_id,
                "initial_disposition_digest": v.disposition_digest,
            }
            for v in leads
        ]
        scope_digest = digest_bytes(canonical_json_bytes(identity))
        return cls(
            str(uuid.uuid5(uuid.NAMESPACE_URL, f"{TRIAGE_WORK_ITEM}|{scope_digest}")),
            leads,
            scope_digest,
        )

    def __post_init__(self) -> None:
        _uuid(self.work_item_id, "work_item_id")
        _digest(self.decision_scope_digest, "decision_scope_digest")
        leads = _sorted_decision(self.decision_leads)
        identity = [
            {
                "lead_id": v.lead_id,
                "lead_digest": v.lead_digest,
                "initial_disposition_id": v.disposition_id,
                "initial_disposition_digest": v.disposition_digest,
            }
            for v in leads
        ]
        expected_scope = digest_bytes(canonical_json_bytes(identity))
        expected_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"{TRIAGE_WORK_ITEM}|{expected_scope}")
        )
        if (
            self.schema_identity != TRIAGE_WORK_ITEM
            or self.decision_leads != leads
            or self.decision_scope_digest != expected_scope
            or self.work_item_id != expected_id
        ):
            raise WorkItemContractError(
                "Work Item identity differs from exact initial decision scope"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_identity": self.schema_identity,
            "work_item_id": self.work_item_id,
            "decision_scope_digest": self.decision_scope_digest,
            "decision_leads": [v.canonical_value() for v in self.decision_leads],
        }

    @property
    def canonical_bytes(self) -> bytes:
        value = canonical_json_bytes(self.canonical_value())
        if len(value) > MAX_VERSION_BYTES:
            raise WorkItemContractError("Work Item exceeds fixed bound")
        return value

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        item = _exact(
            _decode(raw),
            {
                "schema_identity",
                "work_item_id",
                "decision_scope_digest",
                "decision_leads",
            },
            "Work Item",
        )
        value = cls(
            str(item["work_item_id"]),
            tuple(DecisionLeadBinding.from_value(v) for v in item["decision_leads"]),
            str(item["decision_scope_digest"]),
            str(item["schema_identity"]),
        )  # type: ignore[arg-type]
        if value.canonical_bytes != raw:
            raise WorkItemContractError("Work Item bytes differ")
        return value


@dataclass(frozen=True, slots=True)
class TriageWorkItemVersion:
    version_id: str
    work_item_id: str
    ordinal: int
    previous_version_id: str | None
    decision_leads: tuple[DecisionLeadBinding, ...]
    context_leads: tuple[ContextLeadBinding, ...]
    retrieval: RetrievalInputBinding
    priority: PrioritySelection
    watch: WatchConditionWorkItemBinding | None = None
    reentry_kind: ReentryKind | None = None
    schema_identity: str = TRIAGE_WORK_ITEM_VERSION

    def __post_init__(self) -> None:
        _uuid(self.version_id, "version_id")
        _uuid(self.work_item_id, "work_item_id")
        if not 1 <= self.ordinal <= 1_000_000 or (self.ordinal == 1) != (
            self.previous_version_id is None
        ):
            raise WorkItemContractError("Version ordinal and predecessor differ")
        expected = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"{self.work_item_id}|{self.ordinal}")
        )
        if self.version_id != expected:
            raise WorkItemContractError(
                "Version identity differs from Work Item and ordinal"
            )
        expected_previous = (
            None
            if self.ordinal == 1
            else str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL, f"{self.work_item_id}|{self.ordinal - 1}"
                )
            )
        )
        if self.previous_version_id != expected_previous:
            raise WorkItemContractError("Version predecessor identity differs")
        decisions = _sorted_decision(self.decision_leads)
        if decisions != self.decision_leads:
            raise WorkItemContractError("decision Leads are not canonical")
        contexts = tuple(sorted(self.context_leads, key=lambda v: v.lead_id))
        if (
            contexts != self.context_leads
            or len(contexts) > MAX_CONTEXT_LEADS
            or len({v.lead_id for v in contexts}) != len(contexts)
        ):
            raise WorkItemContractError(
                "context Leads are not bounded canonical unique values"
            )
        if {v.lead_id for v in decisions}.intersection(v.lead_id for v in contexts):
            raise WorkItemContractError("decision and context Lead scopes overlap")
        if (
            self.priority.work_identity != self.work_item_id
            or self.priority.work_version != self.version_id
        ):
            raise WorkItemContractError("Priority Selection back-reference differs")
        if self.reentry_kind is not None and (self.ordinal == 1 or self.watch is None):
            raise WorkItemContractError(
                "Watch condition re-entry requires a new successor Version"
            )
        if self.schema_identity != TRIAGE_WORK_ITEM_VERSION:
            raise WorkItemContractError("Version schema identity differs")

    @classmethod
    def create(
        cls,
        *,
        work_item_id: str,
        ordinal: int,
        previous_version_id: str | None,
        decision_leads: tuple[DecisionLeadBinding, ...],
        context_leads: tuple[ContextLeadBinding, ...],
        retrieval: RetrievalInputBinding,
        priority: PrioritySelection,
        watch: WatchConditionWorkItemBinding | None = None,
        reentry_kind: ReentryKind | None = None,
    ) -> Self:
        version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{work_item_id}|{ordinal}"))
        return cls(
            version_id,
            work_item_id,
            ordinal,
            previous_version_id,
            tuple(sorted(decision_leads, key=lambda v: v.lead_id)),
            tuple(sorted(context_leads, key=lambda v: v.lead_id)),
            retrieval,
            priority,
            watch,
            reentry_kind,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_identity": self.schema_identity,
            "version_id": self.version_id,
            "work_item_id": self.work_item_id,
            "ordinal": self.ordinal,
            "previous_version_id": self.previous_version_id,
            "decision_leads": [v.canonical_value() for v in self.decision_leads],
            "context_leads": [v.canonical_value() for v in self.context_leads],
            "retrieval": self.retrieval.canonical_value(),
            "priority": self.priority.canonical_value(),
            "watch": None if self.watch is None else self.watch.canonical_value(),
            "reentry_kind": None
            if self.reentry_kind is None
            else self.reentry_kind.value,
        }

    @property
    def canonical_bytes(self) -> bytes:
        value = canonical_json_bytes(self.canonical_value())
        if len(value) > MAX_VERSION_BYTES:
            raise WorkItemContractError("Version exceeds fixed bound")
        return value

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def proposal_binding(self) -> WorkItemBinding:
        return WorkItemBinding(
            self.work_item_id, self.version_id, self.canonical_digest
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        item = _exact(
            _decode(raw),
            {
                "schema_identity",
                "version_id",
                "work_item_id",
                "ordinal",
                "previous_version_id",
                "decision_leads",
                "context_leads",
                "retrieval",
                "priority",
                "watch",
                "reentry_kind",
            },
            "Work Item Version",
        )
        value = cls(
            str(item["version_id"]),
            str(item["work_item_id"]),
            int(item["ordinal"]),
            None
            if item["previous_version_id"] is None
            else str(item["previous_version_id"]),
            tuple(DecisionLeadBinding.from_value(v) for v in item["decision_leads"]),
            tuple(ContextLeadBinding.from_value(v) for v in item["context_leads"]),
            RetrievalInputBinding.from_value(item["retrieval"]),
            PrioritySelection.from_mapping(item["priority"]),
            None
            if item["watch"] is None
            else WatchConditionWorkItemBinding.from_value(item["watch"]),
            None if item["reentry_kind"] is None else ReentryKind(item["reentry_kind"]),
            str(item["schema_identity"]),
        )  # type: ignore[arg-type]
        if value.canonical_bytes != raw:
            raise WorkItemContractError("Version bytes differ")
        return value


@dataclass(frozen=True, slots=True)
class WorkItemCurrentAssessment:
    work_item_id: str
    version_id: str
    version_digest: str
    current: bool
    usable: bool
    stale_reasons: tuple[str, ...]


class TriageWorkItemStore:
    """Transactional append-only Work Item store over the authority database."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        if not isinstance(connection, sqlite3.Connection) or connection.in_transaction:
            raise WorkItemContractError("store requires an idle sqlite3 connection")
        connection.execute("PRAGMA foreign_keys=ON")
        if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise WorkItemContractError("foreign keys must be enabled")
        self._connection = connection
        self._verify_integrity()

    def _begin(self) -> None:
        if self._connection.in_transaction:
            raise WorkItemContractError("connection has an active transaction")
        self._connection.execute("BEGIN IMMEDIATE")

    def _rollback(self) -> None:
        if self._connection.in_transaction:
            self._connection.execute("ROLLBACK")

    def create_or_replay(
        self, item: TriageWorkItem, version: TriageWorkItemVersion
    ) -> TriageWorkItemVersion:
        if (
            version.work_item_id != item.work_item_id
            or version.ordinal != 1
            or version.decision_leads != item.decision_leads
        ):
            raise WorkItemContractError("initial Version differs from Work Item")
        self._begin()
        try:
            self._require_upstream(version, initial=True)
            self._reject_overlap(item)
            self._connection.execute(
                "INSERT OR IGNORE INTO triage_work_items VALUES(?,?,?,?,?,?,?)",
                (
                    item.work_item_id,
                    TRIAGE_WORK_ITEM,
                    item.decision_scope_digest,
                    len(item.decision_leads),
                    item.canonical_bytes,
                    item.canonical_digest,
                    self._recorded_at(),
                ),
            )
            row = self._connection.execute(
                "SELECT canonical_bytes FROM triage_work_items WHERE work_item_id=?",
                (item.work_item_id,),
            ).fetchone()
            if row is None or bytes(row[0]) != item.canonical_bytes:
                raise WorkItemContractError("Work Item replay diverges")
            self._insert_version(version)
            self._connection.execute(
                "INSERT OR IGNORE INTO triage_work_item_heads VALUES(?,?,?,?,?)",
                (
                    item.work_item_id,
                    version.version_id,
                    1,
                    version.canonical_digest,
                    self._recorded_at(),
                ),
            )
            head = self._head(item.work_item_id)
            if head != (version.version_id, 1, version.canonical_digest):
                raise WorkItemContractError("Work Item create replay diverges")
            self._connection.execute("COMMIT")
            return version
        except Exception:
            self._rollback()
            raise

    def append_version(
        self,
        expected_head_id: str,
        expected_head_digest: str,
        version: TriageWorkItemVersion,
    ) -> TriageWorkItemVersion:
        self._begin()
        try:
            head = self._head(version.work_item_id)
            if head[0] != expected_head_id or head[2] != expected_head_digest:
                raise WorkItemContractError("stale expected Work Item head")
            if version.ordinal != head[1] + 1 or version.previous_version_id != head[0]:
                raise WorkItemContractError("Version is not the immediate successor")
            item = self._load_item(version.work_item_id)
            if tuple(
                (v.lead_id, v.lead_digest) for v in version.decision_leads
            ) != tuple((v.lead_id, v.lead_digest) for v in item.decision_leads):
                raise WorkItemContractError("stable decision Lead identity changed")
            self._require_upstream(version, initial=False)
            self._insert_version(version)
            self._connection.execute(
                "UPDATE triage_work_item_heads SET current_version_id=?,current_ordinal=?,current_version_digest=?,updated_at=? WHERE work_item_id=?",
                (
                    version.version_id,
                    version.ordinal,
                    version.canonical_digest,
                    self._recorded_at(),
                    version.work_item_id,
                ),
            )
            self._connection.execute("COMMIT")
            return version
        except Exception:
            self._rollback()
            raise

    def load_version(self, version_id: str) -> TriageWorkItemVersion:
        _uuid(version_id, "version_id")
        row = self._connection.execute(
            "SELECT canonical_bytes,canonical_digest FROM triage_work_item_versions WHERE version_id=?",
            (version_id,),
        ).fetchone()
        if row is None:
            raise WorkItemContractError("unknown Work Item Version")
        value = TriageWorkItemVersion.from_canonical_bytes(bytes(row[0]))
        if value.canonical_digest != row[1]:
            raise WorkItemContractError("Version digest differs")
        return value

    def current_version(self, work_item_id: str) -> TriageWorkItemVersion:
        return self.load_version(self._head(work_item_id)[0])

    def assess_current(self, work_item_id: str) -> WorkItemCurrentAssessment:
        self._begin()
        try:
            head = self._head(work_item_id)
            version = self.load_version(head[0])
            reasons = self._upstream_reasons(version)
            current = not reasons
            if not version.retrieval.usable:
                reasons.append("retrieval_not_complete")
            result = WorkItemCurrentAssessment(
                work_item_id,
                version.version_id,
                version.canonical_digest,
                current,
                current and version.retrieval.usable,
                tuple(sorted(set(reasons))),
            )
            self._connection.execute("COMMIT")
            return result
        except Exception:
            self._rollback()
            raise

    def require_usable_current(self, work_item_id: str) -> TriageWorkItemVersion:
        self._begin()
        try:
            head = self._head(work_item_id)
            version = self.load_version(head[0])
            if version.canonical_digest != head[2]:
                raise WorkItemContractError("Work Item head digest differs")
            reasons = self._upstream_reasons(version)
            if not version.retrieval.usable:
                reasons.append("retrieval_not_complete")
            if reasons:
                raise WorkItemStaleError(";".join(sorted(set(reasons))))
            self._connection.execute("COMMIT")
            return version
        except Exception:
            self._rollback()
            raise

    def _insert_version(self, v: TriageWorkItemVersion) -> None:
        item = self._load_item(v.work_item_id)
        self._connection.execute(
            "INSERT OR IGNORE INTO triage_work_item_versions VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                v.version_id,
                TRIAGE_WORK_ITEM_VERSION,
                v.work_item_id,
                v.ordinal,
                v.previous_version_id,
                item.decision_scope_digest,
                v.retrieval.outcome or v.retrieval.state.value,
                v.canonical_bytes,
                v.canonical_digest,
                self._recorded_at(),
            ),
        )
        row = self._connection.execute(
            "SELECT canonical_bytes FROM triage_work_item_versions WHERE version_id=?",
            (v.version_id,),
        ).fetchone()
        if row is None or bytes(row[0]) != v.canonical_bytes:
            raise WorkItemContractError("Version replay diverges")

    def _head(self, work_item_id: str) -> tuple[str, int, str]:
        row = self._connection.execute(
            "SELECT current_version_id,current_ordinal,current_version_digest FROM triage_work_item_heads WHERE work_item_id=?",
            (work_item_id,),
        ).fetchone()
        if row is None:
            raise WorkItemContractError("unknown Work Item")
        return str(row[0]), int(row[1]), str(row[2])

    def _recorded_at(self) -> str:
        return str(
            self._connection.execute(
                "SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')"
            ).fetchone()[0]
        )

    def _load_item(self, work_item_id: str) -> TriageWorkItem:
        row = self._connection.execute(
            "SELECT canonical_bytes,canonical_digest FROM triage_work_items WHERE work_item_id=?",
            (work_item_id,),
        ).fetchone()
        if row is None:
            raise WorkItemContractError("unknown Work Item")
        value = TriageWorkItem.from_canonical_bytes(bytes(row[0]))
        if value.canonical_digest != row[1]:
            raise WorkItemContractError("Work Item digest differs")
        return value

    def _upstream_reasons(self, v: TriageWorkItemVersion) -> list[str]:
        reasons: list[str] = []
        for lead in v.decision_leads:
            row = self._connection.execute(
                "SELECT canonical_digest FROM news_leads WHERE lead_id=?",
                (lead.lead_id,),
            ).fetchone()
            if row is None or row[0] != lead.lead_digest:
                reasons.append(f"lead:{lead.lead_id}")
            gate = self._connection.execute(
                "SELECT current_decision_id FROM discovery_gate_decision_heads WHERE signal_id=(SELECT signal_id FROM news_leads WHERE lead_id=?)",
                (lead.lead_id,),
            ).fetchone()
            if gate is None or gate[0] != lead.gate_decision_id:
                reasons.append(f"gate:{lead.lead_id}")
            source = self._connection.execute(
                "SELECT current_version_id FROM source_definition_version_heads WHERE definition_id=?",
                (lead.definition_id,),
            ).fetchone()
            if source is None or source[0] != lead.definition_version_id:
                reasons.append(f"source:{lead.lead_id}")
            disp = self._connection.execute(
                "SELECT h.current_decision_id,d.canonical_digest,d.outcome FROM lead_disposition_heads h JOIN lead_disposition_decisions d ON d.decision_id=h.current_decision_id WHERE h.lead_id=?",
                (lead.lead_id,),
            ).fetchone()
            if disp is None or tuple(disp) != (
                lead.disposition_id,
                lead.disposition_digest,
                LeadDispositionOutcome.QUEUED_FOR_TRIAGE.value,
            ):
                reasons.append(f"disposition:{lead.lead_id}")
        for lead in v.context_leads:
            row = self._connection.execute(
                "SELECT canonical_digest,canonical_bytes FROM news_leads WHERE lead_id=?",
                (lead.lead_id,),
            ).fetchone()
            if (
                row is None
                or row[0] != lead.lead_digest
                or bytes(row[1]) != lead.lead_bytes
            ):
                reasons.append(f"context:{lead.lead_id}")
        if v.watch is not None:
            row = self._connection.execute(
                "SELECT canonical_digest FROM discovery_watch_conditions WHERE watch_condition_id=?",
                (v.watch.watch_condition_id,),
            ).fetchone()
            if row is None or row[0] != v.watch.watch_condition_digest:
                reasons.append("watch")
        if v.retrieval.state is RetrievalBindingState.RECEIPT:
            table = self._connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='increment5d2_retrieval_contexts'"
            ).fetchone()
            if table is None:
                reasons.append("retrieval_authority_unavailable")
            else:
                rows = self._connection.execute(
                    "SELECT request_digest,receipt_digest,receipt_bytes "
                    "FROM increment5d2_retrieval_contexts LIMIT 1025"
                ).fetchall()
                if len(rows) > 1024:
                    reasons.append("retrieval_authority_scan_bound")
                elif not any(
                    row[0] == v.retrieval.request_digest
                    and row[1] == v.retrieval.context_digest
                    and bytes(row[2]) == v.retrieval.receipt_bytes
                    for row in rows
                ):
                    reasons.append("retrieval_authority_differs")
        return reasons

    def _require_upstream(self, v: TriageWorkItemVersion, *, initial: bool) -> None:
        reasons = self._upstream_reasons(v)
        if reasons:
            raise WorkItemContractError(
                "upstream authority differs: " + ",".join(reasons)
            )
        if initial and any(
            x.disposition_ordinal != 1 or x.previous_disposition_id is not None
            for x in v.decision_leads
        ):
            raise WorkItemContractError(
                "initial decision Leads require ordinal-one queue dispositions"
            )

    def _reject_overlap(self, item: TriageWorkItem) -> None:
        scope = {v.lead_id for v in item.decision_leads}
        for row in self._connection.execute(
            "SELECT i.canonical_bytes FROM triage_work_items i JOIN triage_work_item_heads h ON h.work_item_id=i.work_item_id WHERE i.work_item_id!=?",
            (item.work_item_id,),
        ):
            other = self._load_item(
                TriageWorkItem.from_canonical_bytes(bytes(row[0])).work_item_id
            )
            other_scope = {v.lead_id for v in other.decision_leads}
            other_version = self.current_version(other.work_item_id)
            if not self._upstream_reasons(other_version) and scope.intersection(
                other_scope
            ):
                raise WorkItemContractError("active decision Lead scopes overlap")

    def _verify_integrity(self) -> None:
        tables = {
            r[0]
            for r in self._connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "triage_work_items" not in tables:
            return
        for row in self._connection.execute(
            "SELECT work_item_id,decision_scope_digest,decision_lead_count,canonical_bytes,canonical_digest FROM triage_work_items"
        ):
            item = TriageWorkItem.from_canonical_bytes(bytes(row[3]))
            if (
                item.work_item_id != row[0]
                or item.decision_scope_digest != row[1]
                or len(item.decision_leads) != row[2]
                or item.canonical_digest != row[4]
            ):
                raise WorkItemContractError("Work Item retained bytes differ")
        previous_by_item: dict[str, tuple[int, str]] = {}
        for row in self._connection.execute(
            "SELECT version_id,work_item_id,ordinal,previous_version_id,decision_scope_digest,retrieval_outcome,canonical_bytes,canonical_digest FROM triage_work_item_versions ORDER BY work_item_id,ordinal"
        ):
            version = TriageWorkItemVersion.from_canonical_bytes(bytes(row[6]))
            item = self._load_item(version.work_item_id)
            prior = previous_by_item.get(version.work_item_id)
            if (
                version.version_id != row[0]
                or version.work_item_id != row[1]
                or version.ordinal != row[2]
                or version.previous_version_id != row[3]
                or item.decision_scope_digest != row[4]
                or (version.retrieval.outcome or version.retrieval.state.value)
                != row[5]
                or version.canonical_digest != row[7]
                or (prior is None and version.ordinal != 1)
                or (
                    prior is not None
                    and (
                        version.ordinal != prior[0] + 1
                        or version.previous_version_id != prior[1]
                    )
                )
            ):
                raise WorkItemContractError("Version retained bytes differ")
            previous_by_item[version.work_item_id] = (
                version.ordinal,
                version.version_id,
            )
            missing = self._immutable_lineage_reasons(version)
            if missing:
                raise WorkItemContractError(
                    "Version immutable lineage differs: " + ",".join(missing)
                )
        for row in self._connection.execute(
            "SELECT work_item_id,current_version_id,current_ordinal,current_version_digest FROM triage_work_item_heads"
        ):
            version = self.load_version(str(row[1]))
            maximum = self._connection.execute(
                "SELECT MAX(ordinal) FROM triage_work_item_versions WHERE work_item_id=?",
                (row[0],),
            ).fetchone()[0]
            if (
                version.work_item_id != row[0]
                or version.ordinal != row[2]
                or version.canonical_digest != row[3]
                or maximum != row[2]
            ):
                raise WorkItemContractError("Work Item head is not rebuildable")

    def _immutable_lineage_reasons(self, version: TriageWorkItemVersion) -> list[str]:
        reasons: list[str] = []
        for lead in version.decision_leads:
            retained = self._connection.execute(
                "SELECT canonical_digest,canonical_bytes FROM news_leads WHERE lead_id=?",
                (lead.lead_id,),
            ).fetchone()
            if (
                retained is None
                or retained[0] != lead.lead_digest
                or bytes(retained[1]) != lead.lead_bytes
            ):
                reasons.append(f"lead:{lead.lead_id}")
            disposition = self._connection.execute(
                "SELECT canonical_digest,outcome,canonical_bytes FROM lead_disposition_decisions WHERE decision_id=?",
                (lead.disposition_id,),
            ).fetchone()
            if (
                disposition is None
                or disposition[0] != lead.disposition_digest
                or disposition[1] != lead.disposition_outcome
                or bytes(disposition[2]) != lead.disposition_bytes
            ):
                reasons.append(f"disposition:{lead.lead_id}")
        for lead in version.context_leads:
            retained = self._connection.execute(
                "SELECT canonical_digest,canonical_bytes FROM news_leads WHERE lead_id=?",
                (lead.lead_id,),
            ).fetchone()
            if (
                retained is None
                or retained[0] != lead.lead_digest
                or bytes(retained[1]) != lead.lead_bytes
            ):
                reasons.append(f"context:{lead.lead_id}")
        if version.watch is not None:
            watch = self._connection.execute(
                "SELECT canonical_digest FROM discovery_watch_conditions WHERE watch_condition_id=?",
                (version.watch.watch_condition_id,),
            ).fetchone()
            if watch is None or watch[0] != version.watch.watch_condition_digest:
                reasons.append("watch")
        return reasons


__all__ = [
    "LEAD_DISPOSITION_WORK_ITEM_BINDING",
    "SUPPLEMENTAL_DISCOVERY_REENTRY",
    "TRIAGE_WORK_ITEM",
    "TRIAGE_WORK_ITEM_VERSION",
    "WATCH_CONDITION_WORK_ITEM_BINDING",
    "WORK_ITEM_CURRENT_STALE_RULES",
    "ContextLeadBinding",
    "DecisionLeadBinding",
    "ReentryKind",
    "RetrievalBindingState",
    "RetrievalInputBinding",
    "SupplementalDiscoveryReentry",
    "SupplementalLineageBinding",
    "TriageWorkItem",
    "TriageWorkItemStore",
    "TriageWorkItemVersion",
    "WatchConditionWorkItemBinding",
    "WorkItemContractError",
    "WorkItemCurrentAssessment",
    "WorkItemStaleError",
]
