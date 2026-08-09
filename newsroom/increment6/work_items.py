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
from pathlib import Path
from typing import Self

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.checks import CheckOutcome, CheckRequest, TriggerRef
from newsroom.discovery import (
    DiscoverySignal,
    GateDecision,
    LeadDispositionDecision,
    LeadDispositionOutcome,
    NewsLead,
    WatchCondition,
)
from newsroom.increment5.retrieval_context import (
    RetrievalContextOutcome,
    RetrievalContextReason,
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


def _exact_int(value: object, field: str, *, minimum: int = 1) -> int:
    if type(value) is not int or value < minimum:
        raise WorkItemContractError(f"{field} must be an exact positive integer")
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
    except WorkItemContractError:
        raise
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
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
        _uuid(self.lead_event_id, "lead_event_id")
        _uuid(self.disposition_event_id, "disposition_event_id")
        _exact_int(self.lead_aggregate_version, "lead_aggregate_version")
        _exact_int(
            self.disposition_aggregate_version,
            "disposition_aggregate_version",
        )
        _exact_int(self.disposition_ordinal, "disposition_ordinal")
        if self.previous_disposition_id is not None:
            _uuid(self.previous_disposition_id, "previous_disposition_id")
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

    def stable_lead_value(self) -> tuple[object, ...]:
        return (
            self.lead_id,
            self.lead_digest,
            self.lead_event_id,
            self.lead_aggregate_version,
            self.gate_decision_id,
            self.definition_id,
            self.definition_version_id,
            self.lead_bytes,
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
            _exact_int(item["lead_aggregate_version"], "lead_aggregate_version"),
            str(item["gate_decision_id"]),
            str(item["definition_id"]),
            str(item["definition_version_id"]),
            str(item["disposition_id"]),
            str(item["disposition_digest"]),
            str(item["disposition_event_id"]),
            _exact_int(
                item["disposition_aggregate_version"],
                "disposition_aggregate_version",
            ),
            _exact_int(item["disposition_ordinal"], "disposition_ordinal"),
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
    lead_event_id: str
    lead_aggregate_version: int
    gate_decision_id: str
    definition_id: str
    definition_version_id: str
    lead_bytes: bytes

    @classmethod
    def from_authority(cls, lead: NewsLead) -> Self:
        return cls(
            str(lead.request.lead_id),
            lead.canonical_digest,
            str(lead.event_id),
            lead.aggregate_version,
            str(lead.request.promoting_gate_decision_id),
            str(lead.request.definition_id),
            str(lead.request.definition_version_id),
            lead.request.canonical_bytes,
        )

    def __post_init__(self) -> None:
        _uuid(self.lead_id, "context lead_id")
        _digest(self.lead_digest, "context lead_digest")
        _uuid(self.lead_event_id, "context Lead authority event")
        _exact_int(self.lead_aggregate_version, "context Lead aggregate version")
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
            "lead_event_id": self.lead_event_id,
            "lead_aggregate_version": self.lead_aggregate_version,
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
                "lead_event_id",
                "lead_aggregate_version",
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
            str(item["lead_event_id"]),
            _exact_int(
                item["lead_aggregate_version"], "context Lead aggregate version"
            ),
            str(item["gate_decision_id"]),
            str(item["definition_id"]),
            str(item["definition_version_id"]),
            canonical_json_bytes(item["lead"]),
        )


@dataclass(frozen=True, slots=True)
class RetrievalInputBinding:
    state: RetrievalBindingState
    request_id: str
    idempotency_key: str
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
            request.idempotency_key,
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
            request.idempotency_key,
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
        if (
            not isinstance(self.idempotency_key, str)
            or not self.idempotency_key
            or len(self.idempotency_key.encode("utf-8")) > 512
        ):
            raise WorkItemContractError("retrieval idempotency key is invalid")
        _digest(self.request_digest, "retrieval request_digest")
        if digest_bytes(self.request_bytes) != self.request_digest:
            raise WorkItemContractError("retrieval request bytes differ")
        request = _decode(self.request_bytes)
        if (
            request.get("request_id") != self.request_id
            or request.get("idempotency_key") != self.idempotency_key
        ):
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
            try:
                RetrievalContextOutcome(self.outcome)
                if self.reason is not None:
                    RetrievalContextReason(self.reason)
            except (TypeError, ValueError) as exc:
                raise WorkItemContractError(
                    "retrieval outcome or reason is unsupported"
                ) from exc
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
            "idempotency_key": self.idempotency_key,
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
                "idempotency_key",
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
        try:
            state = RetrievalBindingState(item["state"])
        except (TypeError, ValueError) as exc:
            raise WorkItemContractError(
                "retrieval binding state is unsupported"
            ) from exc
        if type(item["no_match"]) is not bool:
            raise WorkItemContractError("retrieval no_match must be boolean")
        return cls(
            state,
            str(item["request_id"]),
            str(item["idempotency_key"]),
            str(item["request_digest"]),
            canonical_json_bytes(item["request"]),
            None if item["context_id"] is None else str(item["context_id"]),
            None if item["context_digest"] is None else str(item["context_digest"]),
            None if item["outcome"] is None else str(item["outcome"]),
            None if item["reason"] is None else str(item["reason"]),
            item["no_match"],
            None if item["receipt"] is None else canonical_json_bytes(item["receipt"]),
        )


class RetrievalContextAuthority:
    """Read-only exact adapter over the separate Increment 5 journal."""

    def __init__(
        self,
        journal_path: Path,
        records: Mapping[
            str, tuple[RetrievalContextRequest, RetrievalContextReceipt | None]
        ],
    ) -> None:
        self._path = Path(journal_path)
        if not self._path.is_file():
            raise WorkItemContractError("retrieval authority journal is absent")
        if not isinstance(records, Mapping) or any(
            not isinstance(digest, str)
            or not isinstance(pair, tuple)
            or len(pair) != 2
            or not isinstance(pair[0], RetrievalContextRequest)
            or (
                pair[1] is not None and not isinstance(pair[1], RetrievalContextReceipt)
            )
            or digest != pair[0].request_digest
            for digest, pair in records.items()
        ):
            raise WorkItemContractError("retrieval authority records differ")
        self._records = dict(records)

    def attach(self, connection: sqlite3.Connection) -> None:
        attached = {
            str(row[1]): str(row[2])
            for row in connection.execute("PRAGMA database_list")
        }
        if "retrieval_authority" not in attached:
            connection.execute(
                "ATTACH DATABASE ? AS retrieval_authority", (str(self._path),)
            )
        elif Path(attached["retrieval_authority"]).resolve() != self._path.resolve():
            raise WorkItemContractError("another retrieval authority is attached")
        contexts = tuple(
            str(row[1])
            for row in connection.execute(
                "PRAGMA retrieval_authority.table_info(increment5d2_retrieval_contexts)"
            )
        )
        purges = tuple(
            str(row[1])
            for row in connection.execute(
                "PRAGMA retrieval_authority.table_info(increment5d2_retrieval_context_purges)"
            )
        )
        if contexts != (
            "idempotency_key",
            "request_digest",
            "receipt_digest",
            "receipt_bytes",
        ) or purges != (
            "purge_id",
            "idempotency_key",
            "request_digest",
            "prior_receipt_digest",
            "purge_receipt_digest",
            "purge_receipt_bytes",
        ):
            raise WorkItemContractError("retrieval authority journal schema differs")
        context_indexes = {
            str(row[1]): str(row[3])
            for row in connection.execute(
                "PRAGMA retrieval_authority.index_list(increment5d2_retrieval_contexts)"
            )
        }
        purge_indexes = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA retrieval_authority.index_list("
                "increment5d2_retrieval_context_purges)"
            )
        }
        if (
            not any(origin == "pk" for origin in context_indexes.values())
            or "increment5d2_retrieval_context_purges_by_key" not in purge_indexes
        ):
            raise WorkItemContractError("retrieval authority indexes differ")

    def verify(
        self, connection: sqlite3.Connection, binding: RetrievalInputBinding
    ) -> None:
        try:
            purge = connection.execute(
                "SELECT purge_id FROM "
                "retrieval_authority.increment5d2_retrieval_context_purges "
                "WHERE idempotency_key=?",
                (binding.idempotency_key,),
            ).fetchone()
            row = connection.execute(
                "SELECT request_digest,receipt_digest,receipt_bytes "
                "FROM retrieval_authority.increment5d2_retrieval_contexts "
                "WHERE idempotency_key=?",
                (binding.idempotency_key,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise WorkItemContractError("retrieval authority journal differs") from exc
        if purge is not None:
            raise WorkItemContractError("retrieval authority was purged")
        if binding.state is RetrievalBindingState.REQUEST_PENDING:
            if row is not None:
                raise WorkItemContractError("pending retrieval already has a receipt")
        elif row is None:
            raise WorkItemContractError("retrieval authority retained bytes differ")
        try:
            request, receipt = self._records[binding.request_digest]
        except Exception as exc:
            raise WorkItemContractError(
                "retrieval authority resolution failed"
            ) from exc
        if (
            not isinstance(request, RetrievalContextRequest)
            or request.request_digest != binding.request_digest
            or request.request_id != binding.request_id
            or request.idempotency_key != binding.idempotency_key
            or request.canonical_bytes != binding.request_bytes
        ):
            raise WorkItemContractError("retrieval authority request differs")
        if (
            binding.state is RetrievalBindingState.REQUEST_PENDING
            and receipt is not None
        ):
            raise WorkItemContractError("pending retrieval already has a receipt")
        if binding.state is RetrievalBindingState.RECEIPT and (
            not isinstance(receipt, RetrievalContextReceipt)
            or receipt.request_digest != request.request_digest
            or receipt.request_id != request.request_id
            or receipt.context_id != binding.context_id
            or receipt.receipt_digest != binding.context_digest
            or receipt.canonical_bytes != binding.receipt_bytes
            or receipt.outcome.value != binding.outcome
            or (None if receipt.reason is None else receipt.reason.value)
            != binding.reason
            or receipt.no_match != binding.no_match
        ):
            raise WorkItemContractError("retrieval authority receipt differs")
        if binding.state is RetrievalBindingState.REQUEST_PENDING:
            return
        if (
            row is None
            or row[0] != binding.request_digest
            or row[1] != binding.context_digest
            or bytes(row[2]) != binding.receipt_bytes
            or digest_bytes(bytes(row[2])) != row[1]
        ):
            raise WorkItemContractError("retrieval authority retained bytes differ")


@dataclass(frozen=True, slots=True)
class WatchConditionWorkItemBinding:
    watch_condition_id: str
    watch_condition_digest: str
    lead_id: str
    watch_bytes: bytes
    watch_event_id: str
    watch_aggregate_version: int
    source_disposition_id: str
    source_disposition_digest: str
    source_disposition_ordinal: int
    source_previous_disposition_id: str | None
    source_disposition_bytes: bytes
    source_disposition_event_id: str
    source_disposition_aggregate_version: int

    @classmethod
    def from_authority(
        cls, watch: WatchCondition, source_disposition: LeadDispositionDecision
    ) -> Self:
        request = source_disposition.request
        if (
            request.outcome is not LeadDispositionOutcome.WATCH_DEFER
            or request.watch_condition_id != watch.request.watch_condition_id
            or request.lead_id != watch.request.lead_id
            or request.next_action.kind.value != "RESUME_ON_WATCH"
        ):
            raise WorkItemContractError("Watch source disposition differs")
        return cls(
            str(watch.request.watch_condition_id),
            watch.canonical_digest,
            str(watch.request.lead_id),
            watch.request.canonical_bytes,
            str(watch.event_id),
            watch.aggregate_version,
            str(request.decision_id),
            source_disposition.canonical_digest,
            request.decision_ordinal,
            None
            if request.previous_decision_id is None
            else str(request.previous_decision_id),
            request.canonical_bytes,
            str(source_disposition.event_id),
            source_disposition.aggregate_version,
        )

    def __post_init__(self) -> None:
        _uuid(self.watch_condition_id, "watch_condition_id")
        _uuid(self.lead_id, "watch lead_id")
        _digest(self.watch_condition_digest, "watch_condition_digest")
        _uuid(self.watch_event_id, "Watch authority event")
        _exact_int(self.watch_aggregate_version, "Watch aggregate version")
        _uuid(self.source_disposition_id, "Watch source disposition")
        _digest(self.source_disposition_digest, "Watch source disposition digest")
        _exact_int(self.source_disposition_ordinal, "Watch source disposition ordinal")
        _uuid(self.source_disposition_event_id, "Watch disposition authority event")
        _exact_int(
            self.source_disposition_aggregate_version,
            "Watch disposition aggregate version",
        )
        if self.source_previous_disposition_id is not None:
            _uuid(self.source_previous_disposition_id, "Watch source predecessor")
        if digest_bytes(self.watch_bytes) != self.watch_condition_digest:
            raise WorkItemContractError("Watch Condition bytes differ")
        watch = _decode(self.watch_bytes)
        if (
            watch.get("watch_condition_id") != self.watch_condition_id
            or watch.get("lead_id") != self.lead_id
        ):
            raise WorkItemContractError("Watch Condition scalars differ from bytes")
        source = _decode(self.source_disposition_bytes)
        next_action = source.get("next_action")
        if (
            digest_bytes(self.source_disposition_bytes)
            != self.source_disposition_digest
            or source.get("decision_id") != self.source_disposition_id
            or source.get("lead_id") != self.lead_id
            or source.get("decision_ordinal") != self.source_disposition_ordinal
            or source.get("previous_decision_id") != self.source_previous_disposition_id
            or source.get("outcome") != LeadDispositionOutcome.WATCH_DEFER.value
            or source.get("watch_condition_id") != self.watch_condition_id
            or not isinstance(next_action, dict)
            or next_action.get("kind") != "RESUME_ON_WATCH"
        ):
            raise WorkItemContractError("Watch source disposition bytes differ")

    def canonical_value(self) -> dict[str, object]:
        return {
            "watch_condition_id": self.watch_condition_id,
            "watch_condition_digest": self.watch_condition_digest,
            "lead_id": self.lead_id,
            "watch": _decode(self.watch_bytes),
            "watch_event_id": self.watch_event_id,
            "watch_aggregate_version": self.watch_aggregate_version,
            "source_disposition_id": self.source_disposition_id,
            "source_disposition_digest": self.source_disposition_digest,
            "source_disposition_ordinal": self.source_disposition_ordinal,
            "source_previous_disposition_id": self.source_previous_disposition_id,
            "source_disposition": _decode(self.source_disposition_bytes),
            "source_disposition_event_id": self.source_disposition_event_id,
            "source_disposition_aggregate_version": self.source_disposition_aggregate_version,
        }

    @classmethod
    def from_value(cls, value: object) -> Self:
        item = _exact(
            value,
            {
                "watch_condition_id",
                "watch_condition_digest",
                "lead_id",
                "watch",
                "watch_event_id",
                "watch_aggregate_version",
                "source_disposition_id",
                "source_disposition_digest",
                "source_disposition_ordinal",
                "source_previous_disposition_id",
                "source_disposition",
                "source_disposition_event_id",
                "source_disposition_aggregate_version",
            },
            "Watch binding",
        )
        return cls(
            str(item["watch_condition_id"]),
            str(item["watch_condition_digest"]),
            str(item["lead_id"]),
            canonical_json_bytes(item["watch"]),
            str(item["watch_event_id"]),
            _exact_int(item["watch_aggregate_version"], "Watch aggregate version"),
            str(item["source_disposition_id"]),
            str(item["source_disposition_digest"]),
            _exact_int(
                item["source_disposition_ordinal"], "Watch source disposition ordinal"
            ),
            None
            if item["source_previous_disposition_id"] is None
            else str(item["source_previous_disposition_id"]),
            canonical_json_bytes(item["source_disposition"]),
            str(item["source_disposition_event_id"]),
            _exact_int(
                item["source_disposition_aggregate_version"],
                "Watch disposition aggregate version",
            ),
        )


@dataclass(frozen=True, slots=True)
class SupplementalDiscoveryReentry:
    source_work_item_id: str
    source_version_id: str
    source_version_digest: str
    source_lead_disposition_id: str
    source_lead_disposition_digest: str
    source_lead_disposition_bytes: bytes
    source_lead_disposition_event_id: str
    source_lead_disposition_aggregate_version: int
    source_lead_disposition_outcome: str
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
    proposal_only_action: bool = False
    source_disposition_authorises_trigger: bool = False
    lineage_bindings: tuple[SupplementalLineageBinding, ...] = ()

    def __post_init__(self) -> None:
        for field in (
            "source_work_item_id",
            "source_version_id",
            "source_lead_disposition_id",
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
        if (
            not isinstance(self.trigger_id, str)
            or not self.trigger_id
            or len(self.trigger_id.encode("utf-8")) > 256
        ):
            raise WorkItemContractError("trigger_id must be a bounded token")
        _digest(self.source_version_digest, "source_version_digest")
        _digest(
            self.source_lead_disposition_digest,
            "source Lead disposition digest",
        )
        _uuid(
            self.source_lead_disposition_event_id,
            "source Lead disposition event",
        )
        _exact_int(
            self.source_lead_disposition_aggregate_version,
            "source Lead disposition aggregate version",
        )
        source_disposition = _decode(self.source_lead_disposition_bytes)
        if (
            digest_bytes(self.source_lead_disposition_bytes)
            != self.source_lead_disposition_digest
            or source_disposition.get("decision_id") != self.source_lead_disposition_id
            or source_disposition.get("outcome") != self.source_lead_disposition_outcome
        ):
            raise WorkItemContractError("source Lead disposition bytes differ")
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
        request_value = _decode(self.lineage_bindings[1].canonical_bytes)
        retained_trigger = request_value.get("trigger")
        if (
            not isinstance(retained_trigger, dict)
            or canonical_json_bytes(retained_trigger)
            != self.lineage_bindings[0].canonical_bytes
            or digest_bytes(canonical_json_bytes(retained_trigger))
            != self.lineage_bindings[0].digest
        ):
            raise WorkItemContractError(
                "supplemental Trigger differs from the Check Request"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            field: getattr(self, field)
            for field in (
                "source_work_item_id",
                "source_version_id",
                "source_version_digest",
                "source_lead_disposition_id",
                "source_lead_disposition_digest",
                "source_lead_disposition_event_id",
                "source_lead_disposition_aggregate_version",
                "source_lead_disposition_outcome",
                "trigger_id",
                "check_request_id",
                "check_outcome_id",
                "signal_id",
                "gate_decision_id",
                "lead_id",
                "queued_disposition_id",
                "target_work_item_id",
                "target_version_id",
                "proposal_only_action",
                "source_disposition_authorises_trigger",
            )
        } | {
            "source_lead_disposition": _decode(self.source_lead_disposition_bytes),
            "watch": None if self.watch is None else self.watch.canonical_value(),
            "lineage_bindings": [
                item.canonical_value() for item in self.lineage_bindings
            ],
        }

    @classmethod
    def from_value(cls, value: object) -> Self:
        item = _exact(
            value,
            {
                "source_work_item_id",
                "source_version_id",
                "source_version_digest",
                "source_lead_disposition_id",
                "source_lead_disposition_digest",
                "source_lead_disposition",
                "source_lead_disposition_event_id",
                "source_lead_disposition_aggregate_version",
                "source_lead_disposition_outcome",
                "watch",
                "trigger_id",
                "check_request_id",
                "check_outcome_id",
                "signal_id",
                "gate_decision_id",
                "lead_id",
                "queued_disposition_id",
                "target_work_item_id",
                "target_version_id",
                "proposal_only_action",
                "source_disposition_authorises_trigger",
                "lineage_bindings",
            },
            "supplemental discovery re-entry",
        )
        if (
            type(item["proposal_only_action"]) is not bool
            or type(item["source_disposition_authorises_trigger"]) is not bool
        ):
            raise WorkItemContractError("supplemental authority flags must be boolean")
        if not isinstance(item["lineage_bindings"], list):
            raise WorkItemContractError("supplemental lineage must be an array")
        return cls(
            str(item["source_work_item_id"]),
            str(item["source_version_id"]),
            str(item["source_version_digest"]),
            str(item["source_lead_disposition_id"]),
            str(item["source_lead_disposition_digest"]),
            canonical_json_bytes(item["source_lead_disposition"]),
            str(item["source_lead_disposition_event_id"]),
            _exact_int(
                item["source_lead_disposition_aggregate_version"],
                "source Lead disposition aggregate version",
            ),
            str(item["source_lead_disposition_outcome"]),
            None
            if item["watch"] is None
            else WatchConditionWorkItemBinding.from_value(item["watch"]),
            str(item["trigger_id"]),
            str(item["check_request_id"]),
            str(item["check_outcome_id"]),
            str(item["signal_id"]),
            str(item["gate_decision_id"]),
            str(item["lead_id"]),
            str(item["queued_disposition_id"]),
            str(item["target_work_item_id"]),
            str(item["target_version_id"]),
            item["proposal_only_action"],
            item["source_disposition_authorises_trigger"],
            tuple(
                SupplementalLineageBinding.from_value(v)
                for v in item["lineage_bindings"]
            ),
        )


@dataclass(frozen=True, slots=True)
class SupplementalLineageBinding:
    kind: str
    identifier: str
    digest: str
    parent_id: str | None
    canonical_bytes: bytes
    authority_event_id: str | None = None
    authority_aggregate_version: int | None = None

    @classmethod
    def from_authority(
        cls,
        record: TriggerRef
        | CheckRequest
        | CheckOutcome
        | DiscoverySignal
        | GateDecision
        | NewsLead
        | LeadDispositionDecision,
    ) -> Self:
        if isinstance(record, TriggerRef):
            raw = canonical_json_bytes(record.canonical_value())
            return cls("TRIGGER", record.trigger_id, digest_bytes(raw), None, raw)
        kinds: tuple[tuple[type[object], str, str, str | None], ...] = (
            (CheckRequest, "CHECK_REQUEST", "request_id", None),
            (CheckOutcome, "CHECK_OUTCOME", "outcome_id", "request_id"),
            (DiscoverySignal, "SIGNAL", "signal_id", "check_outcome_id"),
            (GateDecision, "GATE", "decision_id", "signal_id"),
            (NewsLead, "LEAD", "lead_id", "promoting_gate_decision_id"),
            (
                LeadDispositionDecision,
                "QUEUED_DISPOSITION",
                "decision_id",
                "lead_id",
            ),
        )
        for record_type, kind, identity_field, parent_field in kinds:
            if isinstance(record, record_type):
                request = record.request
                parent = (
                    str(request.trigger.trigger_id)
                    if kind == "CHECK_REQUEST"
                    else str(getattr(request, parent_field))
                )
                return cls(
                    kind,
                    str(getattr(request, identity_field)),
                    record.canonical_digest,
                    parent,
                    request.canonical_bytes,
                    str(record.event_id),
                    record.aggregate_version,
                )
        raise WorkItemContractError("supplemental authority record is unsupported")

    def __post_init__(self) -> None:
        if self.kind == "TRIGGER":
            if not isinstance(self.identifier, str) or not self.identifier:
                raise WorkItemContractError("supplemental Trigger identity differs")
        else:
            _uuid(self.identifier, "supplemental lineage identity")
        if self.kind == "TRIGGER":
            if (
                self.authority_event_id is not None
                or self.authority_aggregate_version is not None
            ):
                raise WorkItemContractError("TriggerRef has no event authority")
        else:
            _uuid(self.authority_event_id, "supplemental authority event")
            _exact_int(
                self.authority_aggregate_version,
                "supplemental authority aggregate version",
            )
        if self.parent_id is not None:
            if self.kind == "CHECK_REQUEST":
                if not self.parent_id:
                    raise WorkItemContractError("supplemental Trigger parent differs")
            else:
                _uuid(self.parent_id, "supplemental lineage parent")
        _digest(self.digest, "supplemental lineage digest")
        if digest_bytes(self.canonical_bytes) != self.digest:
            raise WorkItemContractError("supplemental lineage bytes differ")
        value = _decode(self.canonical_bytes)
        exact_fields = {
            "TRIGGER": {
                "kind",
                "trigger_id",
                "trigger_version",
                "expected_window_digest",
            },
            "CHECK_REQUEST": {
                "adapter_request_digest",
                "baseline_policy",
                "coverage",
                "definition_id",
                "definition_version_id",
                "producer_slot_digest",
                "purpose",
                "request_id",
                "requested_at",
                "revision_policy",
                "rights_decision_id",
                "rights_policy_version",
                "transition_policy",
                "trigger",
                "validator_policy",
            },
            "CHECK_OUTCOME": {
                "admission_semantic_digest",
                "attempt_id",
                "candidate_observations",
                "capture_digest",
                "completed_at",
                "definition_id",
                "definition_version_id",
                "incomplete",
                "kind",
                "observed_items",
                "outcome_id",
                "parser_result_digest",
                "producer_slot_digest",
                "proposal_id",
                "quarantine",
                "reason_codes",
                "receipt_digest",
                "representation_digest",
                "request_id",
                "source_body_digest",
                "validator_digest",
            },
            "SIGNAL": {
                "admission_policy",
                "admitted_at",
                "check_outcome_id",
                "definition_id",
                "definition_version_id",
                "discriminator",
                "incomplete",
                "item_id",
                "occurrence_id",
                "operational_finding_ids",
                "purpose",
                "representation_id",
                "revision_id",
                "signal_id",
                "transition_id",
            },
            "GATE": {
                "basis",
                "coverage",
                "decided_at",
                "decision_id",
                "decision_ordinal",
                "duplicate_policy",
                "evaluated_definition_version_id",
                "exclusion_policy",
                "gate_policy",
                "newness_policy",
                "next_action",
                "outcome",
                "outcome_taxonomy_version",
                "previous_decision_id",
                "primary_reason",
                "reason_taxonomy_version",
                "rights_decision_id",
                "rights_policy_version",
                "signal_admission_policy",
                "signal_id",
                "supporting_reasons",
                "terminality",
                "time_validity_policy",
            },
            "LEAD": {
                "coverage",
                "created_at",
                "definition_id",
                "definition_version_id",
                "incompleteness_warnings",
                "item_id",
                "lead_id",
                "lead_policy",
                "occurrence_id",
                "outcome_taxonomy_version",
                "portfolio_functions",
                "promoting_gate_decision_id",
                "reason_taxonomy_version",
                "representation_id",
                "revision_id",
                "signal_id",
                "source_dependencies",
                "source_roles",
                "transition_id",
                "transition_kind",
                "urgency",
            },
            "QUEUED_DISPOSITION": {
                "decided_at",
                "decision_id",
                "decision_ordinal",
                "disposition_policy",
                "gate_decision_id",
                "lead_id",
                "next_action",
                "outcome",
                "outcome_taxonomy_version",
                "previous_decision_id",
                "primary_reason",
                "reason_taxonomy_version",
                "supporting_reasons",
                "terminality",
                "urgency_route",
                "watch_condition_id",
            },
        }
        if self.kind not in exact_fields or set(value) != exact_fields[self.kind]:
            raise WorkItemContractError("supplemental lineage canonical schema differs")
        identity_fields = {
            "TRIGGER": "trigger_id",
            "CHECK_REQUEST": "request_id",
            "CHECK_OUTCOME": "outcome_id",
            "SIGNAL": "signal_id",
            "GATE": "decision_id",
            "LEAD": "lead_id",
            "QUEUED_DISPOSITION": "decision_id",
        }
        if (
            self.kind not in identity_fields
            or value.get(identity_fields[self.kind]) != self.identifier
        ):
            raise WorkItemContractError("supplemental lineage identity is not retained")
        if self.kind == "CHECK_REQUEST":
            trigger = value.get("trigger")
            retained_parent = (
                trigger.get("trigger_id") if isinstance(trigger, dict) else None
            )
        else:
            parent_fields = {
                "CHECK_OUTCOME": "request_id",
                "SIGNAL": "check_outcome_id",
                "GATE": "signal_id",
                "LEAD": "promoting_gate_decision_id",
                "QUEUED_DISPOSITION": "lead_id",
            }
            retained_parent = (
                value.get(parent_fields[self.kind])
                if self.kind in parent_fields
                else None
            )
        if self.kind != "TRIGGER" and retained_parent != self.parent_id:
            raise WorkItemContractError(
                "supplemental lineage parent differs from bytes"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "identifier": self.identifier,
            "digest": self.digest,
            "parent_id": self.parent_id,
            "authority_event_id": self.authority_event_id,
            "authority_aggregate_version": self.authority_aggregate_version,
            "record": _decode(self.canonical_bytes),
        }

    @classmethod
    def from_value(cls, value: object) -> Self:
        item = _exact(
            value,
            {
                "kind",
                "identifier",
                "digest",
                "parent_id",
                "authority_event_id",
                "authority_aggregate_version",
                "record",
            },
            "supplemental lineage binding",
        )
        return cls(
            str(item["kind"]),
            str(item["identifier"]),
            str(item["digest"]),
            None if item["parent_id"] is None else str(item["parent_id"]),
            canonical_json_bytes(item["record"]),
            None
            if item["authority_event_id"] is None
            else str(item["authority_event_id"]),
            None
            if item["authority_aggregate_version"] is None
            else _exact_int(
                item["authority_aggregate_version"],
                "supplemental authority aggregate version",
            ),
        )


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
    supplemental_reentry: SupplementalDiscoveryReentry | None = None
    schema_identity: str = TRIAGE_WORK_ITEM_VERSION

    def __post_init__(self) -> None:
        _uuid(self.version_id, "version_id")
        _uuid(self.work_item_id, "work_item_id")
        _exact_int(self.ordinal, "Version ordinal")
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
        if self.watch is not None:
            if not isinstance(self.reentry_kind, ReentryKind):
                raise WorkItemContractError("Watch re-entry kind must be typed")
            matching = [
                lead
                for lead in self.decision_leads
                if lead.lead_id == self.watch.lead_id
            ]
            if len(matching) != 1:
                raise WorkItemContractError("Watch does not belong to a decision Lead")
            target = matching[0]
            if (
                target.disposition_ordinal != self.watch.source_disposition_ordinal + 1
                or target.previous_disposition_id != self.watch.source_disposition_id
            ):
                raise WorkItemContractError(
                    "Watch re-entry queue is not the immediate successor"
                )
            watch_value = _decode(self.watch.watch_bytes)
            required = {
                ReentryKind.REVIEW: "review_at",
                ReentryKind.EXPIRY: "expires_at",
                ReentryKind.OPERATOR_CONDITION: "operator_review_condition",
            }
            condition_is_bound = (
                bool(watch_value.get("expected_occurrence"))
                and bool(watch_value.get("review_at"))
                if self.reentry_kind is ReentryKind.DEADLINE
                else bool(watch_value.get(required[self.reentry_kind]))
            )
            if not condition_is_bound:
                raise WorkItemContractError(
                    "Watch re-entry kind differs from its condition"
                )
            if watch_value.get("corroborating_lead_id") is not None or watch_value.get(
                "resume_transition_kinds"
            ):
                raise WorkItemContractError(
                    "observable Watch transition requires a new Lead lineage"
                )
        if self.supplemental_reentry is not None:
            proof = self.supplemental_reentry
            if (
                proof.target_work_item_id != self.work_item_id
                or proof.target_version_id != self.version_id
                or proof.lead_id not in {lead.lead_id for lead in self.decision_leads}
                or proof.queued_disposition_id
                not in {lead.disposition_id for lead in self.decision_leads}
            ):
                raise WorkItemContractError("supplemental target Version differs")
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
        supplemental_reentry: SupplementalDiscoveryReentry | None = None,
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
            supplemental_reentry,
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
            "supplemental_reentry": None
            if self.supplemental_reentry is None
            else self.supplemental_reentry.canonical_value(),
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
                "supplemental_reentry",
            },
            "Work Item Version",
        )
        reentry: ReentryKind | None = None
        if item["reentry_kind"] is not None:
            try:
                reentry = ReentryKind(item["reentry_kind"])
            except (TypeError, ValueError) as exc:
                raise WorkItemContractError("re-entry kind is unsupported") from exc
        value = cls(
            str(item["version_id"]),
            str(item["work_item_id"]),
            _exact_int(item["ordinal"], "version ordinal"),
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
            reentry,
            None
            if item["supplemental_reentry"] is None
            else SupplementalDiscoveryReentry.from_value(item["supplemental_reentry"]),
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

    def __init__(
        self,
        connection: sqlite3.Connection,
        retrieval_authority: RetrievalContextAuthority | None = None,
    ) -> None:
        if not isinstance(connection, sqlite3.Connection) or connection.in_transaction:
            raise WorkItemContractError("store requires an idle sqlite3 connection")
        connection.execute("PRAGMA foreign_keys=ON")
        if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise WorkItemContractError("foreign keys must be enabled")
        self._connection = connection
        self._retrieval_authority = retrieval_authority
        if retrieval_authority is not None:
            retrieval_authority.attach(connection)
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
            existing_item = self._connection.execute(
                "SELECT canonical_bytes FROM triage_work_items WHERE work_item_id=?",
                (item.work_item_id,),
            ).fetchone()
            existing_version = self._connection.execute(
                "SELECT canonical_bytes FROM triage_work_item_versions WHERE version_id=?",
                (version.version_id,),
            ).fetchone()
            if existing_item is not None or existing_version is not None:
                if (
                    existing_item is None
                    or existing_version is None
                    or bytes(existing_item[0]) != item.canonical_bytes
                    or bytes(existing_version[0]) != version.canonical_bytes
                ):
                    raise WorkItemContractError("Work Item replay diverges")
                self._connection.execute("COMMIT")
                return version
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
            existing = self._connection.execute(
                "SELECT canonical_bytes FROM triage_work_item_versions WHERE version_id=?",
                (version.version_id,),
            ).fetchone()
            if existing is not None:
                if (
                    bytes(existing[0]) != version.canonical_bytes
                    or version.previous_version_id != expected_head_id
                    or self.load_version(expected_head_id).canonical_digest
                    != expected_head_digest
                ):
                    raise WorkItemContractError("Version replay diverges")
                self._connection.execute("COMMIT")
                return version
            head = self._head(version.work_item_id)
            if head[0] != expected_head_id or head[2] != expected_head_digest:
                raise WorkItemContractError("stale expected Work Item head")
            if version.ordinal != head[1] + 1 or version.previous_version_id != head[0]:
                raise WorkItemContractError("Version is not the immediate successor")
            item = self._load_item(version.work_item_id)
            if tuple(v.stable_lead_value() for v in version.decision_leads) != tuple(
                v.stable_lead_value() for v in item.decision_leads
            ):
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
                "SELECT canonical_digest,canonical_bytes,authority_event_id,"
                "authority_aggregate_version FROM news_leads WHERE lead_id=?",
                (lead.lead_id,),
            ).fetchone()
            if row is None or tuple(row) != (
                lead.lead_digest,
                lead.lead_bytes,
                lead.lead_event_id,
                lead.lead_aggregate_version,
            ):
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
                "SELECT h.current_decision_id,d.canonical_digest,d.outcome,"
                "d.canonical_bytes,d.authority_event_id,d.authority_aggregate_version,"
                "d.decision_ordinal,d.previous_decision_id,d.lead_id "
                "FROM lead_disposition_heads h JOIN lead_disposition_decisions d "
                "ON d.decision_id=h.current_decision_id WHERE h.lead_id=?",
                (lead.lead_id,),
            ).fetchone()
            if disp is None or tuple(disp) != (
                lead.disposition_id,
                lead.disposition_digest,
                LeadDispositionOutcome.QUEUED_FOR_TRIAGE.value,
                lead.disposition_bytes,
                lead.disposition_event_id,
                lead.disposition_aggregate_version,
                lead.disposition_ordinal,
                lead.previous_disposition_id,
                lead.lead_id,
            ):
                reasons.append(f"disposition:{lead.lead_id}")
        for lead in v.context_leads:
            row = self._connection.execute(
                "SELECT canonical_digest,canonical_bytes,authority_event_id,"
                "authority_aggregate_version FROM news_leads WHERE lead_id=?",
                (lead.lead_id,),
            ).fetchone()
            if (
                row is None
                or row[0] != lead.lead_digest
                or bytes(row[1]) != lead.lead_bytes
                or row[2] != lead.lead_event_id
                or row[3] != lead.lead_aggregate_version
            ):
                reasons.append(f"context:{lead.lead_id}")
        if v.watch is not None:
            row = self._connection.execute(
                "SELECT canonical_digest,canonical_bytes,lead_id,authority_event_id,"
                "authority_aggregate_version FROM discovery_watch_conditions "
                "WHERE watch_condition_id=?",
                (v.watch.watch_condition_id,),
            ).fetchone()
            source = self._connection.execute(
                "SELECT canonical_digest,canonical_bytes,lead_id,decision_ordinal,"
                "previous_decision_id,outcome,watch_condition_id,authority_event_id,"
                "authority_aggregate_version "
                "FROM lead_disposition_decisions WHERE decision_id=?",
                (v.watch.source_disposition_id,),
            ).fetchone()
            if (
                row is None
                or tuple(row)
                != (
                    v.watch.watch_condition_digest,
                    v.watch.watch_bytes,
                    v.watch.lead_id,
                    v.watch.watch_event_id,
                    v.watch.watch_aggregate_version,
                )
                or source is None
                or tuple(source)
                != (
                    v.watch.source_disposition_digest,
                    v.watch.source_disposition_bytes,
                    v.watch.lead_id,
                    v.watch.source_disposition_ordinal,
                    v.watch.source_previous_disposition_id,
                    LeadDispositionOutcome.WATCH_DEFER.value,
                    v.watch.watch_condition_id,
                    v.watch.source_disposition_event_id,
                    v.watch.source_disposition_aggregate_version,
                )
            ):
                reasons.append("watch")
        if self._retrieval_authority is not None:
            try:
                self._retrieval_authority.verify(self._connection, v.retrieval)
            except WorkItemContractError:
                reasons.append("retrieval_authority_differs")
        elif v.retrieval.state is RetrievalBindingState.RECEIPT:
            reasons.append("retrieval_authority_unavailable")
        if v.supplemental_reentry is not None:
            reasons.extend(self._supplemental_reasons(v.supplemental_reentry))
        return reasons

    def _supplemental_reasons(self, proof: SupplementalDiscoveryReentry) -> list[str]:
        reasons: list[str] = []
        try:
            source = self.load_version(proof.source_version_id)
        except WorkItemContractError:
            return ["supplemental_source_version"]
        if (
            source.work_item_id != proof.source_work_item_id
            or source.canonical_digest != proof.source_version_digest
        ):
            reasons.append("supplemental_source_version")
        source_binding = next(
            (
                lead
                for lead in source.decision_leads
                if lead.disposition_id == proof.source_lead_disposition_id
            ),
            None,
        )
        source_disposition = self._connection.execute(
            "SELECT lead_id,canonical_digest,canonical_bytes,authority_event_id,"
            "authority_aggregate_version,outcome FROM lead_disposition_decisions "
            "WHERE decision_id=?",
            (proof.source_lead_disposition_id,),
        ).fetchone()
        if (
            source_binding is None
            or source_disposition is None
            or tuple(source_disposition)
            != (
                source_binding.lead_id,
                proof.source_lead_disposition_digest,
                proof.source_lead_disposition_bytes,
                proof.source_lead_disposition_event_id,
                proof.source_lead_disposition_aggregate_version,
                proof.source_lead_disposition_outcome,
            )
            or proof.source_lead_disposition_digest != source_binding.disposition_digest
            or proof.source_lead_disposition_bytes != source_binding.disposition_bytes
            or proof.source_lead_disposition_event_id
            != source_binding.disposition_event_id
            or proof.source_lead_disposition_aggregate_version
            != source_binding.disposition_aggregate_version
            or proof.source_lead_disposition_outcome
            != source_binding.disposition_outcome
        ):
            reasons.append("supplemental_source_disposition")
        table_map = {
            "CHECK_REQUEST": ("check_requests", "request_id", "trigger_id"),
            "CHECK_OUTCOME": ("check_outcomes", "outcome_id", "request_id"),
            "SIGNAL": ("discovery_signals", "signal_id", "check_outcome_id"),
            "GATE": ("discovery_gate_decisions", "decision_id", "signal_id"),
            "LEAD": ("news_leads", "lead_id", "promoting_gate_decision_id"),
            "QUEUED_DISPOSITION": (
                "lead_disposition_decisions",
                "decision_id",
                "lead_id",
            ),
        }
        for binding in proof.lineage_bindings:
            if binding.kind == "TRIGGER":
                continue
            table, column, parent_column = table_map[binding.kind]
            row = self._connection.execute(
                f"SELECT canonical_digest,canonical_bytes,authority_event_id,"
                f"authority_aggregate_version,{parent_column} FROM {table} "
                f"WHERE {column}=?",
                (binding.identifier,),
            ).fetchone()
            if (
                row is None
                or row[0] != binding.digest
                or bytes(row[1]) != binding.canonical_bytes
                or row[2] != binding.authority_event_id
                or row[3] != binding.authority_aggregate_version
                or row[4] != binding.parent_id
            ):
                reasons.append(f"supplemental_{binding.kind.lower()}")
            if binding.kind == "QUEUED_DISPOSITION":
                outcome = self._connection.execute(
                    "SELECT outcome FROM lead_disposition_decisions "
                    "WHERE decision_id=?",
                    (binding.identifier,),
                ).fetchone()
                if outcome != (LeadDispositionOutcome.QUEUED_FOR_TRIAGE.value,):
                    reasons.append("supplemental_queued_disposition")
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
            version_stable_scope = tuple(
                lead.stable_lead_value() for lead in version.decision_leads
            )
            item_stable_scope = tuple(
                lead.stable_lead_value() for lead in item.decision_leads
            )
            if (
                version.version_id != row[0]
                or version.work_item_id != row[1]
                or version.ordinal != row[2]
                or version.previous_version_id != row[3]
                or item.decision_scope_digest != row[4]
                or version_stable_scope != item_stable_scope
                or (
                    version.ordinal == 1
                    and version.decision_leads != item.decision_leads
                )
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
                "SELECT canonical_digest,canonical_bytes,authority_event_id,"
                "authority_aggregate_version FROM news_leads WHERE lead_id=?",
                (lead.lead_id,),
            ).fetchone()
            if (
                retained is None
                or retained[0] != lead.lead_digest
                or bytes(retained[1]) != lead.lead_bytes
                or retained[2] != lead.lead_event_id
                or retained[3] != lead.lead_aggregate_version
            ):
                reasons.append(f"lead:{lead.lead_id}")
            disposition = self._connection.execute(
                "SELECT canonical_digest,outcome,canonical_bytes,authority_event_id,"
                "authority_aggregate_version,decision_ordinal,previous_decision_id,lead_id "
                "FROM lead_disposition_decisions WHERE decision_id=?",
                (lead.disposition_id,),
            ).fetchone()
            if (
                disposition is None
                or disposition[0] != lead.disposition_digest
                or disposition[1] != lead.disposition_outcome
                or bytes(disposition[2]) != lead.disposition_bytes
                or disposition[3] != lead.disposition_event_id
                or disposition[4] != lead.disposition_aggregate_version
                or disposition[5] != lead.disposition_ordinal
                or disposition[6] != lead.previous_disposition_id
                or disposition[7] != lead.lead_id
            ):
                reasons.append(f"disposition:{lead.lead_id}")
        for lead in version.context_leads:
            retained = self._connection.execute(
                "SELECT canonical_digest,canonical_bytes,authority_event_id,"
                "authority_aggregate_version FROM news_leads WHERE lead_id=?",
                (lead.lead_id,),
            ).fetchone()
            if (
                retained is None
                or retained[0] != lead.lead_digest
                or bytes(retained[1]) != lead.lead_bytes
                or retained[2] != lead.lead_event_id
                or retained[3] != lead.lead_aggregate_version
            ):
                reasons.append(f"context:{lead.lead_id}")
        if version.watch is not None:
            watch = self._connection.execute(
                "SELECT canonical_digest,canonical_bytes,lead_id,authority_event_id,"
                "authority_aggregate_version FROM discovery_watch_conditions "
                "WHERE watch_condition_id=?",
                (version.watch.watch_condition_id,),
            ).fetchone()
            source = self._connection.execute(
                "SELECT canonical_digest,canonical_bytes,lead_id,decision_ordinal,"
                "previous_decision_id,outcome,watch_condition_id,authority_event_id,"
                "authority_aggregate_version FROM lead_disposition_decisions "
                "WHERE decision_id=?",
                (version.watch.source_disposition_id,),
            ).fetchone()
            if (
                watch is None
                or tuple(watch)
                != (
                    version.watch.watch_condition_digest,
                    version.watch.watch_bytes,
                    version.watch.lead_id,
                    version.watch.watch_event_id,
                    version.watch.watch_aggregate_version,
                )
                or source is None
                or tuple(source)
                != (
                    version.watch.source_disposition_digest,
                    version.watch.source_disposition_bytes,
                    version.watch.lead_id,
                    version.watch.source_disposition_ordinal,
                    version.watch.source_previous_disposition_id,
                    LeadDispositionOutcome.WATCH_DEFER.value,
                    version.watch.watch_condition_id,
                    version.watch.source_disposition_event_id,
                    version.watch.source_disposition_aggregate_version,
                )
            ):
                reasons.append("watch")
        if self._retrieval_authority is not None:
            try:
                self._retrieval_authority.verify(self._connection, version.retrieval)
            except WorkItemContractError:
                reasons.append("retrieval")
        elif version.retrieval.state is RetrievalBindingState.RECEIPT:
            reasons.append("retrieval")
        if version.supplemental_reentry is not None:
            reasons.extend(self._supplemental_reasons(version.supplemental_reentry))
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
    "RetrievalContextAuthority",
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
