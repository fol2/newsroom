"""Provider-free reconciliation of durable Graphiti spend reservations."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.control_plane.command_auth import HERMES_COMMAND_PRINCIPAL
from newsroom.control_plane.sqlite_profile import apply_control_plane_sqlite_profile
from newsroom.control_plane.store import (
    GRAPHITI_SPEND_FX_POLICY,
    append_ledger,
    graphiti_usd_to_gbp_microunits,
    is_exact_no_embedding_call,
)
from newsroom.control_plane.veto import assert_private_store
from newsroom.graphiti_adapter.embedding_meter import is_exact_provider_reported_usage


class GraphitiSpendReconciliationError(RuntimeError):
    """The retained evidence does not support an exact spend transition."""


class GraphitiSpendDisposition(StrEnum):
    RECONCILED = "RECONCILED"
    UNRECONCILED_REPORTED_MISSING = "UNRECONCILED_REPORTED_MISSING"
    RELEASED_BEFORE_PROVIDER_IO = "RELEASED_BEFORE_PROVIDER_IO"
    AMBIGUOUS_EFFECT_HOLD = "AMBIGUOUS_EFFECT_HOLD"


GRAPHITI_SPEND_RECONCILE_COMMAND_TYPE = "RECONCILE_GRAPHITI_SPEND"


@dataclass(frozen=True, slots=True)
class _GraphitiSpendReconciliationCommand:
    caller_principal: str
    writer_principal: str
    command_type: str
    idempotency_key: str
    expected_plan_digest: str


def _assert_command_authority(command: _GraphitiSpendReconciliationCommand) -> None:
    if command.caller_principal != HERMES_COMMAND_PRINCIPAL:
        raise PermissionError("Graphiti spend reconciliation requires Hermes")
    if command.writer_principal != "newsroom.control-plane.command-service":
        raise PermissionError("Graphiti spend reconciliation requires command service")
    if command.command_type != GRAPHITI_SPEND_RECONCILE_COMMAND_TYPE:
        raise PermissionError("Graphiti spend reconciliation command type differs")
    if not command.idempotency_key or not command.expected_plan_digest:
        raise GraphitiSpendReconciliationError(
            "Graphiti spend reconciliation command identity is incomplete"
        )


@dataclass(frozen=True, slots=True)
class GraphitiSpendTransition:
    spend_id: str
    ingest_id: str
    attempt_number: int
    disposition: GraphitiSpendDisposition
    evidence_basis: str
    attempt_outcome: str | None
    attempt_receipt_digest: str | None
    provider_leaf_count: int
    provider_leaves_digest: str
    provider_usage: dict[str, object] | None
    graph_journal_state: str
    graph_journal_digest: str
    graph_journal_evidence: dict[str, object]
    reserved_gbp_microunits: int
    source_proving_run_id: str
    source_generation_id: str | None
    source_actual_usd_microunits: int | None
    source_actual_gbp_microunits: int | None
    source_provider_usage: dict[str, object] | None
    source_dispatch_owner: str | None
    source_dispatch_lease_expires_at: str | None
    source_at: str
    actual_usd_microunits: int | None
    actual_gbp_microunits: int | None
    fx_policy: str
    source_status: str
    source_usage_basis: str
    target_status: str
    target_usage_basis: str
    unused_reservation_released: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "spend_id": self.spend_id,
            "ingest_id": self.ingest_id,
            "attempt_number": self.attempt_number,
            "disposition": self.disposition.value,
            "evidence_basis": self.evidence_basis,
            "attempt_outcome": self.attempt_outcome,
            "attempt_receipt_digest": self.attempt_receipt_digest,
            "provider_leaf_count": self.provider_leaf_count,
            "provider_leaves_digest": self.provider_leaves_digest,
            "provider_usage": self.provider_usage,
            "graph_journal_state": self.graph_journal_state,
            "graph_journal_digest": self.graph_journal_digest,
            "graph_journal_evidence": self.graph_journal_evidence,
            "reserved_gbp_microunits": self.reserved_gbp_microunits,
            "source_proving_run_id": self.source_proving_run_id,
            "source_generation_id": self.source_generation_id,
            "source_actual_usd_microunits": self.source_actual_usd_microunits,
            "source_actual_gbp_microunits": self.source_actual_gbp_microunits,
            "source_provider_usage": self.source_provider_usage,
            "source_dispatch_owner": self.source_dispatch_owner,
            "source_dispatch_lease_expires_at": (self.source_dispatch_lease_expires_at),
            "source_at": self.source_at,
            "actual_usd_microunits": self.actual_usd_microunits,
            "actual_gbp_microunits": self.actual_gbp_microunits,
            "fx_policy": self.fx_policy,
            "source_status": self.source_status,
            "source_usage_basis": self.source_usage_basis,
            "target_status": self.target_status,
            "target_usage_basis": self.target_usage_basis,
            "unused_reservation_released": self.unused_reservation_released,
        }


@dataclass(frozen=True, slots=True)
class GraphitiLiveReservationSnapshot:
    spend_id: str
    ingest_id: str
    attempt_number: int
    proving_run_id: str
    generation_id: str | None
    reserved_gbp_microunits: int
    status: str
    usage_basis: str
    actual_usd_microunits: int | None
    actual_gbp_microunits: int | None
    provider_usage: dict[str, object] | None
    dispatch_owner: str
    dispatch_lease_expires_at: str
    at: str

    def as_dict(self) -> dict[str, object]:
        return {
            "spend_id": self.spend_id,
            "ingest_id": self.ingest_id,
            "attempt_number": self.attempt_number,
            "proving_run_id": self.proving_run_id,
            "generation_id": self.generation_id,
            "reserved_gbp_microunits": self.reserved_gbp_microunits,
            "status": self.status,
            "usage_basis": self.usage_basis,
            "actual_usd_microunits": self.actual_usd_microunits,
            "actual_gbp_microunits": self.actual_gbp_microunits,
            "provider_usage": self.provider_usage,
            "dispatch_owner": self.dispatch_owner,
            "dispatch_lease_expires_at": self.dispatch_lease_expires_at,
            "at": self.at,
        }


@dataclass(frozen=True, slots=True)
class GraphitiSpendReconciliationPlan:
    evaluated_at: str
    transitions: tuple[GraphitiSpendTransition, ...]
    live_reservations: tuple[GraphitiLiveReservationSnapshot, ...]
    terminal_attempt_count: int
    planned_terminal_disposition_count: int
    provider_calls: int = 0

    @property
    def live_reservation_spend_ids(self) -> tuple[str, ...]:
        return tuple(item.spend_id for item in self.live_reservations)

    def _unsigned(self) -> dict[str, object]:
        return {
            "schema": "newsroom.control-plane.graphiti-spend-reconciliation-plan.v1",
            "evaluated_at": self.evaluated_at,
            "provider_calls": self.provider_calls,
            "transitions": [item.as_dict() for item in self.transitions],
            "live_reservations": [item.as_dict() for item in self.live_reservations],
            "live_reservation_spend_ids": list(self.live_reservation_spend_ids),
            "terminal_attempt_count": self.terminal_attempt_count,
            "planned_terminal_disposition_count": (
                self.planned_terminal_disposition_count
            ),
        }

    @property
    def plan_digest(self) -> str:
        return digest_bytes(canonical_json_bytes(self._unsigned()))

    def as_dict(self) -> dict[str, object]:
        return {**self._unsigned(), "plan_digest": self.plan_digest}


@dataclass(frozen=True, slots=True)
class GraphitiSpendReconciliationReceipt:
    idempotency_key: str
    plan_digest: str
    authenticated_principal: str
    applied_at: str
    applied_transition_count: int
    disposition_counts: dict[str, int]
    terminal_spend_disposition_count: int
    terminal_attempt_count: int
    live_reservation_count: int
    provider_calls: int
    ledger_digest: str
    receipt_digest: str

    def _unsigned(self) -> dict[str, object]:
        return {
            "schema": "newsroom.control-plane.graphiti-spend-reconciliation-receipt.v1",
            "idempotency_key": self.idempotency_key,
            "plan_digest": self.plan_digest,
            "authenticated_principal": self.authenticated_principal,
            "applied_at": self.applied_at,
            "applied_transition_count": self.applied_transition_count,
            "disposition_counts": dict(sorted(self.disposition_counts.items())),
            "terminal_spend_disposition_count": (self.terminal_spend_disposition_count),
            "terminal_attempt_count": self.terminal_attempt_count,
            "live_reservation_count": self.live_reservation_count,
            "provider_calls": self.provider_calls,
            "ledger_digest": self.ledger_digest,
            "public_dispatch": False,
            "graph_mutation": False,
        }

    def as_dict(self) -> dict[str, object]:
        return {**self._unsigned(), "receipt_digest": self.receipt_digest}

    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> GraphitiSpendReconciliationReceipt:
        counts = value.get("disposition_counts")
        if not isinstance(counts, Mapping):
            raise GraphitiSpendReconciliationError(
                "retained reconciliation receipt has invalid disposition counts"
            )
        allowed_dispositions = {item.value for item in GraphitiSpendDisposition}
        if any(
            not isinstance(key, str) or key not in allowed_dispositions
            for key in counts
        ):
            raise GraphitiSpendReconciliationError(
                "retained reconciliation receipt has unsupported dispositions"
            )
        receipt = cls(
            idempotency_key=str(value["idempotency_key"]),
            plan_digest=str(value["plan_digest"]),
            authenticated_principal=str(value["authenticated_principal"]),
            applied_at=str(value["applied_at"]),
            applied_transition_count=_required_non_negative_int(
                value["applied_transition_count"],
                field="applied_transition_count",
            ),
            disposition_counts={
                str(key): _required_non_negative_int(
                    item, field=f"disposition_counts.{key}"
                )
                for key, item in counts.items()
            },
            terminal_spend_disposition_count=_required_non_negative_int(
                value["terminal_spend_disposition_count"],
                field="terminal_spend_disposition_count",
            ),
            terminal_attempt_count=_required_non_negative_int(
                value["terminal_attempt_count"], field="terminal_attempt_count"
            ),
            live_reservation_count=_required_non_negative_int(
                value["live_reservation_count"], field="live_reservation_count"
            ),
            provider_calls=_required_non_negative_int(
                value["provider_calls"], field="provider_calls"
            ),
            ledger_digest=str(value["ledger_digest"]),
            receipt_digest=str(value["receipt_digest"]),
        )
        expected = digest_bytes(canonical_json_bytes(receipt._unsigned()))
        if receipt.receipt_digest != expected:
            raise GraphitiSpendReconciliationError(
                "retained reconciliation receipt digest differs from its bytes"
            )
        if (
            receipt.authenticated_principal != HERMES_COMMAND_PRINCIPAL
            or receipt.provider_calls != 0
            or sum(receipt.disposition_counts.values())
            != receipt.applied_transition_count
            or receipt.terminal_spend_disposition_count
            != receipt.terminal_attempt_count
        ):
            raise GraphitiSpendReconciliationError(
                "retained reconciliation receipt violates reconciliation invariants"
            )
        if canonical_json_bytes(value) != canonical_json_bytes(receipt.as_dict()):
            raise GraphitiSpendReconciliationError(
                "retained reconciliation receipt is not the exact canonical record"
            )
        return receipt


def _required_non_negative_int(value: object, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise GraphitiSpendReconciliationError(
            f"retained reconciliation receipt {field} is invalid"
        )
    return value


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_exact_zero(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == 0


def _string_object_mapping(
    value: Mapping[object, object], *, field: str
) -> dict[str, object]:
    if not all(isinstance(key, str) for key in value):
        raise GraphitiSpendReconciliationError(f"{field} keys must be strings")
    return {str(key): item for key, item in value.items()}


def _require_equal_usage_evidence(
    retained: Mapping[str, object],
    proposed: Mapping[str, object],
    *,
    field: str,
) -> None:
    if canonical_json_bytes(retained) != canonical_json_bytes(proposed):
        raise GraphitiSpendReconciliationError(
            f"graph journal provider usage differs from {field}"
        )


def _utc_text(value: datetime) -> str:
    instant = (
        value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    )
    return instant.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _instant(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return (
        parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    )


def _has_live_graphiti_dispatch_lease(
    *, status: object, owner: object, lease_expires_at: object, at: datetime
) -> bool:
    """Return whether a reservation has an exact owner/expiry pair live at ``at``."""

    if status != "RESERVED" or not isinstance(owner, str) or not owner.strip():
        return False
    if not isinstance(lease_expires_at, str) or not lease_expires_at:
        return False
    try:
        lease = _instant(lease_expires_at)
    except (TypeError, ValueError):
        return False
    return lease is not None and lease > at


def _json_object(value: object, *, field: str) -> dict[str, object] | None:
    if value is None:
        return None
    try:
        decoded = json.loads(str(value))
    except (json.JSONDecodeError, TypeError) as exc:
        raise GraphitiSpendReconciliationError(f"{field} is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise GraphitiSpendReconciliationError(f"{field} must be a JSON object")
    return decoded


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        is not None
    )


def _validate_attempt_receipt(
    row: sqlite3.Row | Mapping[str, object], receipt: Mapping[str, object] | None
) -> None:
    retained_digest = row["attempt_receipt_digest"]
    if receipt is None:
        if retained_digest is not None:
            raise GraphitiSpendReconciliationError(
                "attempt receipt digest exists without receipt bytes"
            )
        return
    unsigned = dict(receipt)
    supplied_digest = unsigned.pop("receipt_digest", None)
    calculated_digest = digest_bytes(canonical_json_bytes(unsigned))
    if supplied_digest != retained_digest or supplied_digest != calculated_digest:
        raise GraphitiSpendReconciliationError(
            "attempt receipt digest differs from its retained bytes"
        )
    if (
        not isinstance(receipt.get("ingest_id"), str)
        or receipt.get("ingest_id") != row["ingest_id"]
        or not _is_positive_int(receipt.get("attempt_number"))
        or receipt.get("attempt_number") != row["attempt_number"]
        or receipt.get("outcome") != row["attempt_outcome"]
    ):
        raise GraphitiSpendReconciliationError(
            "attempt receipt identity differs from its spend join"
        )
    if not isinstance(receipt.get("chat_invocations"), list):
        raise GraphitiSpendReconciliationError(
            "attempt receipt provider leaves are not a list"
        )
    provider_attempt = receipt.get("provider_attempt_number")
    if provider_attempt is not None and not _is_positive_int(provider_attempt):
        raise GraphitiSpendReconciliationError(
            "attempt receipt provider attempt is invalid"
        )


def _receipt_attributes_provider_usage_to_current(
    row: sqlite3.Row | Mapping[str, object], receipt: Mapping[str, object]
) -> bool:
    accounting = receipt.get("accounting")
    raw_usage = receipt.get("embedding_usage")
    retained_usage = _json_object(
        row["provider_usage_json"], field="current-attribution provider usage"
    )
    provider_attempt = receipt.get("provider_attempt_number")
    reported_provider_attempt = (
        accounting.get("reported_provider_attempt_number")
        if isinstance(accounting, Mapping)
        else None
    )
    return (
        isinstance(accounting, Mapping)
        and accounting.get("spend_id") == row["spend_id"]
        and _is_positive_int(reported_provider_attempt)
        and reported_provider_attempt == provider_attempt
        and _is_positive_int(provider_attempt)
        and accounting.get("reconciled_to_current_attempt") is True
        and row["status"] == "RECONCILED"
        and row["usage_basis"] == "PROVIDER_REPORTED"
        and isinstance(raw_usage, Mapping)
        and is_exact_provider_reported_usage(raw_usage)
        and retained_usage is not None
        and canonical_json_bytes(retained_usage) == canonical_json_bytes(raw_usage)
        and row["actual_usd_microunits"] == raw_usage.get("cost_usd_microunits")
    )


def _current_attribution_joins_uncharged_provider_attempt(
    rows_by_identity: Mapping[tuple[str, int], sqlite3.Row],
    row: sqlite3.Row,
    receipt: Mapping[str, object],
) -> bool:
    provider_attempt = receipt.get("provider_attempt_number")
    if (
        not _receipt_attributes_provider_usage_to_current(row, receipt)
        or not isinstance(provider_attempt, int)
        or isinstance(provider_attempt, bool)
        or provider_attempt < 1
        or provider_attempt >= row["attempt_number"]
    ):
        return False
    provider_row = rows_by_identity.get((str(row["ingest_id"]), provider_attempt))
    if provider_row is None:
        return False
    provider_usage = _json_object(
        provider_row["provider_usage_json"],
        field="referenced provider-attempt usage",
    )
    return (
        not isinstance(provider_usage, Mapping)
        or not is_exact_provider_reported_usage(provider_usage)
    ) and provider_row["actual_usd_microunits"] in {None, 0}


def _current_attribution_duplicates_charged_provider_attempt(
    rows_by_identity: Mapping[tuple[str, int], sqlite3.Row],
    row: sqlite3.Row,
    receipt: Mapping[str, object],
) -> bool:
    provider_attempt = receipt.get("provider_attempt_number")
    if (
        not _receipt_attributes_provider_usage_to_current(row, receipt)
        or not isinstance(provider_attempt, int)
        or isinstance(provider_attempt, bool)
        or provider_attempt < 1
        or provider_attempt >= row["attempt_number"]
    ):
        return False
    provider_row = rows_by_identity.get((str(row["ingest_id"]), provider_attempt))
    if provider_row is None:
        return False
    provider_usage = _json_object(
        provider_row["provider_usage_json"],
        field="charged referenced provider-attempt usage",
    )
    provider_receipt = _json_object(
        provider_row["attempt_receipt_json"],
        field="charged referenced provider-attempt receipt",
    )
    _validate_attempt_receipt(provider_row, provider_receipt)
    provider_receipt_usage = (
        None if provider_receipt is None else provider_receipt.get("embedding_usage")
    )
    receipt_usage = receipt.get("embedding_usage")
    return (
        isinstance(receipt_usage, Mapping)
        and is_exact_provider_reported_usage(receipt_usage)
        and (
            (
                isinstance(provider_usage, Mapping)
                and is_exact_provider_reported_usage(provider_usage)
                and canonical_json_bytes(provider_usage)
                == canonical_json_bytes(receipt_usage)
                and provider_row["actual_usd_microunits"]
                == provider_usage.get("cost_usd_microunits")
            )
            or (
                isinstance(provider_receipt_usage, Mapping)
                and is_exact_provider_reported_usage(provider_receipt_usage)
                and canonical_json_bytes(provider_receipt_usage)
                == canonical_json_bytes(receipt_usage)
            )
        )
    )


def _validate_journal_evidence(
    row: sqlite3.Row,
    journal: Mapping[str, object],
    receipt: Mapping[str, object] | None,
) -> None:
    if not journal:
        return
    supplied_digest = journal.get("evidence_digest")
    unsigned_journal = dict(journal)
    unsigned_journal.pop("evidence_digest", None)
    if not isinstance(supplied_digest, str) or supplied_digest != digest_bytes(
        canonical_json_bytes(unsigned_journal)
    ):
        raise GraphitiSpendReconciliationError(
            "graph journal evidence digest differs from its bytes"
        )
    if journal.get("evidence_source") != "GRAPH_JOURNAL_EXPORT_V1":
        raise GraphitiSpendReconciliationError(
            "graph journal evidence source is not durable"
        )
    if (
        not isinstance(journal.get("spend_id"), str)
        or journal.get("spend_id") != row["spend_id"]
        or not isinstance(journal.get("ingest_id"), str)
        or journal.get("ingest_id") != row["ingest_id"]
        or not _is_positive_int(journal.get("attempt_number"))
        or journal.get("attempt_number") != row["attempt_number"]
        or not isinstance(journal.get("journal_record_id"), str)
        or not journal.get("journal_record_id")
    ):
        raise GraphitiSpendReconciliationError(
            "graph journal identity differs from its spend join"
        )
    state = journal.get("state")
    if state not in {
        "ABSENT",
        "CREATED",
        "PENDING",
        "ROLLING_BACK",
        "COMPLETE",
        "RECOVERED_AMBIGUOUS",
    }:
        raise GraphitiSpendReconciliationError(
            "graph journal evidence has an unsupported state"
        )
    marker_attempt = journal.get("marker_attempt_number")
    provider_attempt = journal.get("provider_attempt_number")
    reconciliation_attempt = journal.get("reconciliation_attempt_number")
    if any(
        value is not None and not _is_positive_int(value)
        for value in (marker_attempt, provider_attempt, reconciliation_attempt)
    ):
        raise GraphitiSpendReconciliationError(
            "graph journal attempt coordinate is invalid"
        )
    if (
        state
        in {
            "PENDING",
            "ROLLING_BACK",
            "COMPLETE",
            "RECOVERED_AMBIGUOUS",
        }
        and marker_attempt != row["attempt_number"]
    ):
        recovered_complete = _recovered_without_provider_dispatch(row, journal, receipt)
        if not recovered_complete:
            raise GraphitiSpendReconciliationError(
                "graph journal attempt differs from its spend join"
            )
    dispatch_state = journal.get("provider_dispatch_state")
    if dispatch_state not in {"NOT_DISPATCHED", "DISPATCHED", "UNKNOWN"}:
        raise GraphitiSpendReconciliationError(
            "graph journal provider dispatch state is invalid"
        )
    if "provider_usage" in journal and state != "COMPLETE":
        raise GraphitiSpendReconciliationError(
            "provider-native usage requires a complete graph journal marker"
        )
    if "provider_usage" in journal and (
        not isinstance(journal["provider_usage"], Mapping)
        or not is_exact_provider_reported_usage(journal["provider_usage"])
    ):
        raise GraphitiSpendReconciliationError(
            "graph journal provider usage is not exact provider-native usage"
        )
    if state in {"ABSENT", "CREATED"} and dispatch_state != "NOT_DISPATCHED":
        raise GraphitiSpendReconciliationError(
            "pre-provider graph journal state has a dispatched effect"
        )
    if "provider_leaves" in journal and not isinstance(
        journal["provider_leaves"], list
    ):
        raise GraphitiSpendReconciliationError(
            "graph journal provider leaves are not a list"
        )
    current_marker = journal.get("marker_attempt_number") == row["attempt_number"]
    if (
        current_marker
        and receipt is not None
        and "provider_leaves" in journal
        and canonical_json_bytes(journal["provider_leaves"])
        != canonical_json_bytes(receipt.get("chat_invocations"))
    ):
        raise GraphitiSpendReconciliationError(
            "graph journal provider leaves differ from the attempt receipt"
        )
    if current_marker and receipt is not None:
        receipt_provider_attempt = receipt.get("provider_attempt_number")
        journal_provider_attempt = journal.get("provider_attempt_number")
        if (
            journal_provider_attempt is not None
            and journal_provider_attempt != receipt_provider_attempt
        ):
            raise GraphitiSpendReconciliationError(
                "graph journal provider attempt differs from the attempt receipt"
            )
        if (
            receipt_provider_attempt is None
            and journal.get("provider_dispatch_state") == "DISPATCHED"
        ):
            raise GraphitiSpendReconciliationError(
                "graph journal dispatch differs from the attempt receipt"
            )
    if (
        receipt is not None
        and receipt.get("provider_attempt_number") is not None
        and dispatch_state == "NOT_DISPATCHED"
        and not _recovered_without_provider_dispatch(row, journal, receipt)
    ):
        raise GraphitiSpendReconciliationError(
            "graph journal dispatch differs from the attempt receipt"
        )
    if receipt is not None:
        receipt_provider_attempt = receipt.get("provider_attempt_number")
        if (
            receipt_provider_attempt is not None
            and receipt_provider_attempt != row["attempt_number"]
            and (
                not _recovered_without_provider_dispatch(row, journal, receipt)
                or receipt_provider_attempt != journal.get("provider_attempt_number")
            )
        ):
            raise GraphitiSpendReconciliationError(
                "attempt receipt provider attempt differs from its spend join"
            )


def _recovered_without_provider_dispatch(
    row: sqlite3.Row,
    journal: Mapping[str, object],
    receipt: Mapping[str, object] | None,
) -> bool:
    marker_attempt = journal.get("marker_attempt_number")
    accounting = receipt.get("accounting") if receipt is not None else None
    provider_accounting = (
        accounting.get("provider_attempt") if isinstance(accounting, Mapping) else None
    )
    current_accounting = (
        accounting.get("current_attempt") if isinstance(accounting, Mapping) else None
    )
    return (
        receipt is not None
        and journal.get("state") == "COMPLETE"
        and isinstance(marker_attempt, int)
        and not isinstance(marker_attempt, bool)
        and marker_attempt < row["attempt_number"]
        and receipt.get("provider_attempt_number") == marker_attempt
        and journal.get("provider_attempt_number") == marker_attempt
        and journal.get("reconciliation_attempt_number") == row["attempt_number"]
        and journal.get("recovery_classification") == "RECOVERED_IMMUTABLE_COMPLETE"
        and journal.get("provider_dispatch_state") == "NOT_DISPATCHED"
        and isinstance(accounting, Mapping)
        and accounting.get("recovery_classification") == "RECOVERED_IMMUTABLE_COMPLETE"
        and isinstance(provider_accounting, Mapping)
        and provider_accounting.get("spend_id")
        == f"{row['ingest_id']}:{marker_attempt}"
        and provider_accounting.get("retained_attempt_receipt") is True
        and isinstance(current_accounting, Mapping)
        and current_accounting.get("spend_id") == row["spend_id"]
        and current_accounting.get("status") == "RECONCILED"
        and current_accounting.get("usage_basis") == "NO_EMBEDDING_CALL"
        and _is_exact_zero(current_accounting.get("actual_usd_microunits"))
        and _is_exact_zero(current_accounting.get("actual_gbp_microunits"))
        and current_accounting.get("unused_reservation_released") is True
    )


def _receipt_proves_pre_provider_refusal(
    receipt: Mapping[str, object] | None,
    journal: Mapping[str, object],
) -> bool:
    if receipt is None:
        return False
    embedding_usage = receipt.get("embedding_usage")
    return (
        receipt.get("outcome") in {"FAILED", "TIMEOUT", "CANCELLED", "REFUSED"}
        and receipt.get("provider_attempt_number") is None
        and receipt.get("chat_invocations") == []
        and journal.get("state") in {"ABSENT", "CREATED"}
        and journal.get("provider_dispatch_state") == "NOT_DISPATCHED"
        and (
            isinstance(embedding_usage, Mapping)
            and is_exact_no_embedding_call(embedding_usage)
        )
    )


def _read_only(path: str) -> sqlite3.Connection:
    resolved = _private_resolved_path(path)
    return sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)


def _private_resolved_path(path: str) -> Path:
    raw = Path(path).expanduser()
    assert_private_store(str(raw))
    resolved = raw.resolve()
    assert_private_store(str(resolved))
    return resolved


def _transition(
    row: sqlite3.Row,
    *,
    disposition: GraphitiSpendDisposition,
    evidence_basis: str,
    journal: Mapping[str, object],
    receipt: Mapping[str, object] | None,
    provider_usage: Mapping[str, object] | None = None,
) -> GraphitiSpendTransition:
    raw_leaves = journal.get("provider_leaves")
    if raw_leaves is None:
        raw_leaves = receipt.get("chat_invocations", []) if receipt is not None else []
    leaves = raw_leaves if isinstance(raw_leaves, list) else []
    journal_value = dict(journal)
    graph_journal_state = str(journal_value.get("state") or "UNOBSERVED")
    supplied_journal_digest = str(journal_value.pop("evidence_digest", "") or "")
    graph_journal_digest = digest_bytes(canonical_json_bytes(journal_value))
    if supplied_journal_digest and supplied_journal_digest != graph_journal_digest:
        raise GraphitiSpendReconciliationError(
            "graph journal evidence digest differs from its bytes"
        )
    actual_usd = row["actual_usd_microunits"]
    actual_gbp = row["actual_gbp_microunits"]
    source_provider_usage = _json_object(
        row["provider_usage_json"], field=f"source provider usage {row['spend_id']}"
    )
    fx_policy = GRAPHITI_SPEND_FX_POLICY
    if provider_usage is not None and is_exact_provider_reported_usage(provider_usage):
        cost = provider_usage["cost_usd_microunits"]
        if not isinstance(cost, int) or isinstance(cost, bool):
            raise GraphitiSpendReconciliationError("provider cost is not an integer")
        actual_usd = cost
        actual_gbp, fx_policy = graphiti_usd_to_gbp_microunits(cost)
    source_status = str(row["status"])
    source_usage_basis = str(row["usage_basis"])
    if disposition is GraphitiSpendDisposition.RECONCILED:
        target_status = "RECONCILED"
        target_usage_basis = "PROVIDER_REPORTED"
        released = True
    elif disposition is GraphitiSpendDisposition.RELEASED_BEFORE_PROVIDER_IO:
        actual_usd = 0
        actual_gbp, fx_policy = graphiti_usd_to_gbp_microunits(0)
        target_status = "RECONCILED"
        target_usage_basis = (
            "NO_EMBEDDING_CALL"
            if source_usage_basis == "NO_EMBEDDING_CALL"
            else "NO_PROVIDER_IO"
        )
        released = True
    elif disposition is GraphitiSpendDisposition.UNRECONCILED_REPORTED_MISSING:
        actual_usd = None
        actual_gbp = None
        target_status = "UNRECONCILED"
        target_usage_basis = "UNREPORTED"
        released = False
    else:
        actual_usd = None
        actual_gbp = None
        target_status = "UNRECONCILED"
        target_usage_basis = "AMBIGUOUS_EFFECT_HOLD"
        released = False
    return GraphitiSpendTransition(
        spend_id=str(row["spend_id"]),
        ingest_id=str(row["ingest_id"]),
        attempt_number=int(row["attempt_number"]),
        disposition=disposition,
        evidence_basis=evidence_basis,
        attempt_outcome=(
            None if row["attempt_outcome"] is None else str(row["attempt_outcome"])
        ),
        attempt_receipt_digest=(
            None
            if row["attempt_receipt_digest"] is None
            else str(row["attempt_receipt_digest"])
        ),
        provider_leaf_count=len(leaves),
        provider_leaves_digest=digest_bytes(canonical_json_bytes(leaves)),
        provider_usage=(dict(provider_usage) if provider_usage is not None else None),
        graph_journal_state=graph_journal_state,
        graph_journal_digest=graph_journal_digest,
        graph_journal_evidence=journal_value,
        reserved_gbp_microunits=int(row["reserved_gbp_microunits"]),
        source_proving_run_id=str(row["proving_run_id"]),
        source_generation_id=(
            None if row["generation_id"] is None else str(row["generation_id"])
        ),
        source_actual_usd_microunits=(
            None
            if row["actual_usd_microunits"] is None
            else int(row["actual_usd_microunits"])
        ),
        source_actual_gbp_microunits=(
            None
            if row["actual_gbp_microunits"] is None
            else int(row["actual_gbp_microunits"])
        ),
        source_provider_usage=source_provider_usage,
        source_dispatch_owner=(
            None if row["dispatch_owner"] is None else str(row["dispatch_owner"])
        ),
        source_dispatch_lease_expires_at=(
            None
            if row["dispatch_lease_expires_at"] is None
            else str(row["dispatch_lease_expires_at"])
        ),
        source_at=str(row["at"]),
        actual_usd_microunits=(None if actual_usd is None else int(actual_usd)),
        actual_gbp_microunits=(None if actual_gbp is None else int(actual_gbp)),
        fx_policy=fx_policy,
        source_status=source_status,
        source_usage_basis=source_usage_basis,
        target_status=target_status,
        target_usage_basis=target_usage_basis,
        unused_reservation_released=released,
    )


def _live_reservation_snapshot(row: sqlite3.Row) -> GraphitiLiveReservationSnapshot:
    provider_usage = _json_object(
        row["provider_usage_json"], field="live reservation provider usage"
    )
    owner = row["dispatch_owner"]
    lease_expires_at = row["dispatch_lease_expires_at"]
    if (
        not isinstance(owner, str)
        or not owner.strip()
        or not isinstance(lease_expires_at, str)
    ):
        raise GraphitiSpendReconciliationError(
            "live reservation does not have an exact dispatch lease"
        )
    return GraphitiLiveReservationSnapshot(
        spend_id=str(row["spend_id"]),
        ingest_id=str(row["ingest_id"]),
        attempt_number=int(row["attempt_number"]),
        proving_run_id=str(row["proving_run_id"]),
        generation_id=(
            None if row["generation_id"] is None else str(row["generation_id"])
        ),
        reserved_gbp_microunits=int(row["reserved_gbp_microunits"]),
        status=str(row["status"]),
        usage_basis=str(row["usage_basis"]),
        actual_usd_microunits=(
            None
            if row["actual_usd_microunits"] is None
            else int(row["actual_usd_microunits"])
        ),
        actual_gbp_microunits=(
            None
            if row["actual_gbp_microunits"] is None
            else int(row["actual_gbp_microunits"])
        ),
        provider_usage=provider_usage,
        dispatch_owner=owner,
        dispatch_lease_expires_at=lease_expires_at,
        at=str(row["at"]),
    )


_TRANSITION_EVIDENCE_COLUMNS = {
    "spend_id": "spend_id",
    "ingest_id": "ingest_id",
    "attempt_number": "attempt_number",
    "disposition": "disposition",
    "reserved_gbp_microunits": "reserved_gbp_microunits",
    "source_proving_run_id": "source_proving_run_id",
    "source_generation_id": "source_generation_id",
    "source_actual_usd_microunits": "source_actual_usd_microunits",
    "source_actual_gbp_microunits": "source_actual_gbp_microunits",
    "source_dispatch_owner": "source_dispatch_owner",
    "source_dispatch_lease_expires_at": "source_dispatch_lease_expires_at",
    "source_at": "source_at",
    "actual_usd_microunits": "actual_usd_microunits",
    "actual_gbp_microunits": "actual_gbp_microunits",
    "fx_policy": "fx_policy",
    "source_status": "source_status",
    "source_usage_basis": "source_usage_basis",
    "target_status": "target_status",
    "target_usage_basis": "target_usage_basis",
    "attempt_receipt_digest": "attempt_receipt_digest",
    "evidence_basis": "evidence_basis",
}
_TRANSITION_EVIDENCE_FIELDS = set(_TRANSITION_EVIDENCE_COLUMNS) | {
    "attempt_outcome",
    "provider_leaf_count",
    "provider_leaves_digest",
    "provider_usage",
    "graph_journal_state",
    "graph_journal_digest",
    "graph_journal_evidence",
    "unused_reservation_released",
    "source_provider_usage",
}


def _validate_retained_dispositions(connection: sqlite3.Connection) -> None:
    reconciliation_ledger_digests = (
        {
            str(row[0])
            for row in connection.execute(
                "SELECT digest FROM ledger "
                "WHERE kind='GRAPHITI_SPEND_RECONCILIATION_APPLIED'"
            ).fetchall()
        }
        if _table_exists(connection, "ledger")
        else set()
    )
    if not _table_exists(connection, "unpublished_graphiti_spend_dispositions"):
        if reconciliation_ledger_digests:
            raise GraphitiSpendReconciliationError(
                "reconciliation ledger events have no retained dispositions"
            )
        return
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT d.*,
               s.spend_id AS current_spend_id,
               s.ingest_id AS current_ingest_id,
               s.attempt_number AS current_attempt_number,
               s.proving_run_id AS current_proving_run_id,
               s.generation_id AS current_generation_id,
               s.reserved_gbp_microunits AS current_reserved_gbp_microunits,
               s.status AS current_status,
               s.usage_basis AS current_usage_basis,
               s.actual_usd_microunits AS current_actual_usd_microunits,
               s.actual_gbp_microunits AS current_actual_gbp_microunits,
               s.provider_usage_json AS current_provider_usage_json,
               s.dispatch_owner AS current_dispatch_owner,
               s.dispatch_lease_expires_at AS current_dispatch_lease_expires_at,
               s.at AS current_spend_at,
               r.outcome AS current_attempt_outcome,
               r.receipt_digest AS current_attempt_receipt_digest,
               r.receipt_json AS current_attempt_receipt_json
        FROM unpublished_graphiti_spend_dispositions d
        LEFT JOIN unpublished_graphiti_spend s ON s.spend_id=d.spend_id
        LEFT JOIN unpublished_graphiti_attempt_receipts r
          ON r.ingest_id=d.ingest_id AND r.attempt_number=d.attempt_number
        ORDER BY d.ingest_id, d.attempt_number
        """
    ).fetchall()
    command_counts: dict[str, Counter[str]] = {}
    command_evidence: dict[str, list[dict[str, object]]] = {}
    command_applied_at: dict[str, set[str]] = {}
    for row in rows:
        spend_id = str(row["spend_id"])
        if row["current_spend_id"] is None:
            raise GraphitiSpendReconciliationError(
                f"retained disposition {spend_id} has no spend row"
            )
        raw_evidence = str(row["evidence_json"])
        evidence = _json_object(
            raw_evidence, field=f"retained disposition evidence {spend_id}"
        )
        if evidence is None:
            raise GraphitiSpendReconciliationError(
                f"retained disposition evidence {spend_id} is absent"
            )
        if set(evidence) != _TRANSITION_EVIDENCE_FIELDS:
            raise GraphitiSpendReconciliationError(
                f"retained disposition evidence {spend_id} fields differ"
            )
        canonical_evidence = canonical_json_bytes(evidence)
        if raw_evidence.encode("utf-8") != canonical_evidence or row[
            "evidence_digest"
        ] != digest_bytes(canonical_evidence):
            raise GraphitiSpendReconciliationError(
                f"retained disposition evidence {spend_id} differs from its digest"
            )
        for evidence_field, column in _TRANSITION_EVIDENCE_COLUMNS.items():
            if canonical_json_bytes(
                evidence.get(evidence_field)
            ) != canonical_json_bytes(row[column]):
                raise GraphitiSpendReconciliationError(
                    f"retained disposition {spend_id} {evidence_field} differs"
                )
        source_provider_usage = _json_object(
            row["source_provider_usage_json"],
            field=f"retained source provider usage {spend_id}",
        )
        if canonical_json_bytes(
            evidence["source_provider_usage"]
        ) != canonical_json_bytes(source_provider_usage):
            raise GraphitiSpendReconciliationError(
                f"retained disposition {spend_id} source_provider_usage differs"
            )
        release = evidence.get("unused_reservation_released")
        if (
            not isinstance(release, bool)
            or int(release) != row["unused_reservation_released"]
        ):
            raise GraphitiSpendReconciliationError(
                f"retained disposition {spend_id} release decision differs"
            )
        try:
            GraphitiSpendDisposition(str(row["disposition"]))
        except ValueError as exc:
            raise GraphitiSpendReconciliationError(
                f"retained disposition {spend_id} is unsupported"
            ) from exc
        if (
            row["current_ingest_id"] != row["ingest_id"]
            or row["current_attempt_number"] != row["attempt_number"]
            or row["current_proving_run_id"] != row["source_proving_run_id"]
            or row["current_generation_id"] != row["source_generation_id"]
            or row["current_reserved_gbp_microunits"] != row["reserved_gbp_microunits"]
            or row["current_status"] != row["target_status"]
            or row["current_usage_basis"] != row["target_usage_basis"]
            or row["current_actual_usd_microunits"] != row["actual_usd_microunits"]
            or row["current_actual_gbp_microunits"] != row["actual_gbp_microunits"]
            or row["current_dispatch_owner"] is not None
            or row["current_dispatch_lease_expires_at"] is not None
            or row["current_spend_at"] != row["at"]
        ):
            raise GraphitiSpendReconciliationError(
                f"retained disposition {spend_id} differs from current spend state"
            )
        current_provider_usage = _json_object(
            row["current_provider_usage_json"],
            field=f"retained provider usage {spend_id}",
        )
        if canonical_json_bytes(evidence["provider_usage"]) != canonical_json_bytes(
            current_provider_usage
        ):
            raise GraphitiSpendReconciliationError(
                f"retained disposition {spend_id} provider usage differs"
            )
        receipt = _json_object(
            row["current_attempt_receipt_json"],
            field=f"attempt receipt {spend_id}",
        )
        _validate_attempt_receipt(
            {
                "attempt_receipt_digest": row["current_attempt_receipt_digest"],
                "ingest_id": row["ingest_id"],
                "attempt_number": row["attempt_number"],
                "attempt_outcome": row["current_attempt_outcome"],
            },
            receipt,
        )
        if row["attempt_receipt_digest"] != row["current_attempt_receipt_digest"]:
            raise GraphitiSpendReconciliationError(
                f"retained disposition {spend_id} attempt receipt differs"
            )
        if evidence["attempt_outcome"] != row["current_attempt_outcome"]:
            raise GraphitiSpendReconciliationError(
                f"retained disposition {spend_id} attempt outcome differs"
            )
        journal = evidence.get("graph_journal_evidence")
        if not isinstance(journal, Mapping) or evidence.get(
            "graph_journal_digest"
        ) != digest_bytes(canonical_json_bytes(journal)):
            raise GraphitiSpendReconciliationError(
                f"retained disposition {spend_id} graph journal differs"
            )
        if evidence["graph_journal_state"] != str(journal.get("state") or "UNOBSERVED"):
            raise GraphitiSpendReconciliationError(
                f"retained disposition {spend_id} graph journal state differs"
            )
        raw_leaves = journal.get("provider_leaves")
        if raw_leaves is None:
            raw_leaves = receipt.get("chat_invocations", []) if receipt else []
        if not isinstance(raw_leaves, list):
            raise GraphitiSpendReconciliationError(
                f"retained disposition {spend_id} provider leaves differ"
            )
        if evidence["provider_leaf_count"] != len(raw_leaves) or evidence[
            "provider_leaves_digest"
        ] != digest_bytes(canonical_json_bytes(raw_leaves)):
            raise GraphitiSpendReconciliationError(
                f"retained disposition {spend_id} provider leaves differ"
            )
        command_id = str(row["command_id"])
        command_counts.setdefault(command_id, Counter())[str(row["disposition"])] += 1
        command_evidence.setdefault(command_id, []).append(evidence)
        command_applied_at.setdefault(command_id, set()).add(str(row["at"]))
    if not _table_exists(
        connection, "unpublished_graphiti_spend_reconciliation_receipts"
    ):
        if command_counts or reconciliation_ledger_digests:
            raise GraphitiSpendReconciliationError(
                "retained dispositions have no reconciliation receipt table"
            )
        return
    receipt_keys = {
        str(row[0])
        for row in connection.execute(
            "SELECT idempotency_key "
            "FROM unpublished_graphiti_spend_reconciliation_receipts"
        ).fetchall()
    }
    missing_receipts = set(command_counts) - receipt_keys
    if missing_receipts:
        command_id = min(missing_receipts)
        raise GraphitiSpendReconciliationError(
            f"retained disposition command {command_id} has no receipt"
        )
    receipt_ledger_digests: set[str] = set()
    for command_id in sorted(receipt_keys):
        receipt = _retained_receipt(connection, command_id)
        if receipt is None:  # pragma: no cover - key came from the same transaction
            raise GraphitiSpendReconciliationError(
                f"retained disposition command {command_id} has no receipt"
            )
        receipt_ledger_digests.add(receipt.ledger_digest)
        actual_counts = dict(sorted(command_counts.get(command_id, Counter()).items()))
        retained_plan = _retained_plan(connection, command_id)
        retained_transitions = retained_plan.get("transitions")
        retained_live_ids = retained_plan.get("live_reservation_spend_ids")
        retained_live_reservations = retained_plan.get("live_reservations")
        if (
            not isinstance(retained_transitions, list)
            or not isinstance(retained_live_ids, list)
            or not isinstance(retained_live_reservations, list)
        ):
            raise GraphitiSpendReconciliationError(
                f"retained disposition command {command_id} has invalid plan transitions"
            )
        if retained_live_ids != [
            item.get("spend_id")
            for item in retained_live_reservations
            if isinstance(item, Mapping)
        ] or any(not isinstance(item, Mapping) for item in retained_live_reservations):
            raise GraphitiSpendReconciliationError(
                f"retained disposition command {command_id} has invalid live reservations"
            )
        expected_applied_at = (
            {receipt.applied_at} if receipt.applied_transition_count else set()
        )
        if (
            receipt.idempotency_key != command_id
            or receipt.applied_transition_count != sum(actual_counts.values())
            or receipt.disposition_counts != actual_counts
            or receipt.terminal_attempt_count
            != retained_plan.get("terminal_attempt_count")
            or receipt.terminal_spend_disposition_count
            != retained_plan.get("planned_terminal_disposition_count")
            or receipt.live_reservation_count != len(retained_live_ids)
            or command_applied_at.get(command_id, set()) != expected_applied_at
            or canonical_json_bytes(command_evidence.get(command_id, []))
            != canonical_json_bytes(retained_transitions)
        ):
            raise GraphitiSpendReconciliationError(
                f"retained disposition command {command_id} differs from its receipt"
            )
    if (
        len(receipt_ledger_digests) != len(receipt_keys)
        or receipt_ledger_digests != reconciliation_ledger_digests
    ):
        raise GraphitiSpendReconciliationError(
            "reconciliation ledger events differ from retained receipts"
        )


def _plan_from_connection(
    connection: sqlite3.Connection,
    *,
    evaluated_at: datetime,
    graph_journal_evidence: Mapping[str, Mapping[str, object]] | None,
) -> GraphitiSpendReconciliationPlan:
    evaluated = (
        evaluated_at.replace(tzinfo=UTC)
        if evaluated_at.tzinfo is None
        else evaluated_at.astimezone(UTC)
    )
    if graph_journal_evidence is None:
        journals: Mapping[str, Mapping[str, object]] = {}
    elif not isinstance(graph_journal_evidence, Mapping) or any(
        not isinstance(key, str) or not isinstance(item, Mapping)
        for key, item in graph_journal_evidence.items()
    ):
        raise GraphitiSpendReconciliationError(
            "graph journal evidence must map spend IDs to evidence objects"
        )
    else:
        journals = graph_journal_evidence
    connection.row_factory = sqlite3.Row
    if not _table_exists(connection, "unpublished_graphiti_spend"):
        if journals:
            raise GraphitiSpendReconciliationError(
                "graph journal evidence does not join a spend row"
            )
        return GraphitiSpendReconciliationPlan(_utc_text(evaluated), (), (), 0, 0)
    _validate_retained_dispositions(connection)
    disposition_join = (
        "LEFT JOIN unpublished_graphiti_spend_dispositions d ON d.spend_id=s.spend_id"
        if _table_exists(connection, "unpublished_graphiti_spend_dispositions")
        else ""
    )
    disposition_projection = (
        "d.spend_id AS retained_disposition_spend_id"
        if disposition_join
        else "NULL AS retained_disposition_spend_id"
    )
    rows = connection.execute(f"""
        SELECT s.*,
               r.outcome AS attempt_outcome,
               r.receipt_digest AS attempt_receipt_digest,
               r.receipt_json AS attempt_receipt_json,
               {disposition_projection}
        FROM unpublished_graphiti_spend s
        LEFT JOIN unpublished_graphiti_attempt_receipts r
          ON r.ingest_id=s.ingest_id
         AND r.attempt_number=s.attempt_number
        {disposition_join}
        ORDER BY s.ingest_id, s.attempt_number
        """).fetchall()
    candidate_rows = [
        row for row in rows if row["retained_disposition_spend_id"] is None
    ]

    rows_by_identity = {
        (str(row["ingest_id"]), int(row["attempt_number"])): row for row in rows
    }
    recovered_prior_usage: dict[str, dict[str, object]] = {}
    for recovery_row in candidate_rows:
        recovery_spend_id = str(recovery_row["spend_id"])
        recovery_journal = journals.get(recovery_spend_id, {})
        recovery_receipt = _json_object(
            recovery_row["attempt_receipt_json"],
            field=f"attempt receipt {recovery_spend_id}",
        )
        _validate_attempt_receipt(recovery_row, recovery_receipt)
        _validate_journal_evidence(recovery_row, recovery_journal, recovery_receipt)
        if not _recovered_without_provider_dispatch(
            recovery_row, recovery_journal, recovery_receipt
        ):
            continue
        if recovery_receipt is None:
            continue
        provider_attempt = recovery_receipt.get("provider_attempt_number")
        raw_usage = recovery_receipt.get("embedding_usage")
        journal_usage = recovery_journal.get("provider_usage")
        if not isinstance(provider_attempt, int) or isinstance(provider_attempt, bool):
            raise GraphitiSpendReconciliationError(
                "recovered provider attempt is not exactly bound"
            )
        prior_row = rows_by_identity.get(
            (str(recovery_row["ingest_id"]), provider_attempt)
        )
        if prior_row is None:
            raise GraphitiSpendReconciliationError(
                "recovered provider usage does not join its provider attempt"
            )
        prior_receipt = _json_object(
            prior_row["attempt_receipt_json"],
            field=f"attempt receipt {prior_row['spend_id']}",
        )
        _validate_attempt_receipt(prior_row, prior_receipt)
        if (
            prior_receipt is None
            or "provider_leaves" not in recovery_journal
            or canonical_json_bytes(recovery_journal["provider_leaves"])
            != canonical_json_bytes(prior_receipt.get("chat_invocations"))
        ):
            raise GraphitiSpendReconciliationError(
                "recovered provider leaves differ from the provider attempt receipt"
            )
        recovery_leaves = recovery_receipt.get("chat_invocations")
        prior_leaves = prior_receipt.get("chat_invocations")
        if recovery_leaves != [] and canonical_json_bytes(
            recovery_leaves
        ) != canonical_json_bytes(prior_leaves):
            raise GraphitiSpendReconciliationError(
                "recovered current receipt leaves differ from the provider attempt receipt"
            )
        if raw_usage is None:
            continue
        if (
            not isinstance(raw_usage, Mapping)
            or not is_exact_provider_reported_usage(raw_usage)
            or not isinstance(journal_usage, Mapping)
        ):
            raise GraphitiSpendReconciliationError(
                "recovered provider usage is not exactly bound"
            )
        usage = _string_object_mapping(raw_usage, field="recovered provider usage")
        _require_equal_usage_evidence(
            usage,
            _string_object_mapping(journal_usage, field="recovered journal usage"),
            field="recovered attempt receipt usage",
        )
        if prior_row["retained_disposition_spend_id"] is not None:
            prior_receipt_usage = (
                None if prior_receipt is None else prior_receipt.get("embedding_usage")
            )
            prior_spend_usage = _json_object(
                prior_row["provider_usage_json"],
                field="previously dispositioned provider usage",
            )
            if (
                not isinstance(prior_receipt_usage, Mapping)
                or not is_exact_provider_reported_usage(prior_receipt_usage)
                or not isinstance(prior_spend_usage, Mapping)
                or not is_exact_provider_reported_usage(prior_spend_usage)
            ):
                raise GraphitiSpendReconciliationError(
                    "recovered provider usage differs from its retained provider attempt"
                )
            _require_equal_usage_evidence(
                usage,
                prior_receipt_usage,
                field="retained provider attempt receipt usage",
            )
            _require_equal_usage_evidence(
                usage,
                prior_spend_usage,
                field="retained provider attempt spend usage",
            )
        prior_spend_id = str(prior_row["spend_id"])
        existing = recovered_prior_usage.get(prior_spend_id)
        if existing is not None:
            _require_equal_usage_evidence(
                existing, usage, field="another recovered retry usage"
            )
        recovered_prior_usage[prior_spend_id] = usage

    transitions: list[GraphitiSpendTransition] = []
    live: list[GraphitiLiveReservationSnapshot] = []
    observed_spend_ids: set[str] = set()
    for row in candidate_rows:
        spend_id = str(row["spend_id"])
        observed_spend_ids.add(spend_id)
        receipt = _json_object(
            row["attempt_receipt_json"], field=f"attempt receipt {spend_id}"
        )
        _validate_attempt_receipt(row, receipt)
        journal = journals.get(spend_id, {})
        _validate_journal_evidence(row, journal, receipt)
        duplicate_current_attribution = (
            receipt is not None
            and _current_attribution_duplicates_charged_provider_attempt(
                rows_by_identity, row, receipt
            )
        )
        if (
            receipt is not None
            and receipt.get("provider_attempt_number") is not None
            and receipt.get("provider_attempt_number") != row["attempt_number"]
            and not _recovered_without_provider_dispatch(row, journal, receipt)
            and not _current_attribution_joins_uncharged_provider_attempt(
                rows_by_identity, row, receipt
            )
            and not duplicate_current_attribution
        ):
            raise GraphitiSpendReconciliationError(
                "attempt receipt provider attempt differs from its spend join"
            )
        provider_usage = _json_object(
            row["provider_usage_json"], field=f"provider usage {spend_id}"
        )
        receipt_provider_usage: dict[str, object] | None = None
        if receipt is not None and receipt.get("embedding_usage") is not None:
            raw_receipt_usage = receipt["embedding_usage"]
            if not isinstance(raw_receipt_usage, Mapping):
                raise GraphitiSpendReconciliationError(
                    "attempt receipt provider usage is not an object"
                )
            receipt_provider_usage = _string_object_mapping(
                raw_receipt_usage, field="attempt receipt provider usage"
            )
        recovered_without_dispatch = _recovered_without_provider_dispatch(
            row, journal, receipt
        )
        receipt_usage_is_prior_attempt = (
            recovered_without_dispatch
            and receipt is not None
            and receipt.get("provider_attempt_number") != row["attempt_number"]
        )
        if (
            provider_usage is not None
            and receipt_provider_usage is not None
            and not receipt_usage_is_prior_attempt
        ):
            _require_equal_usage_evidence(
                provider_usage,
                receipt_provider_usage,
                field="attempt receipt usage",
            )
        elif (
            provider_usage is None
            and receipt_provider_usage is not None
            and not receipt_usage_is_prior_attempt
        ):
            provider_usage = receipt_provider_usage
        elif (
            receipt is not None
            and provider_usage is not None
            and receipt_provider_usage is None
            and (
                is_exact_provider_reported_usage(provider_usage)
                or is_exact_no_embedding_call(provider_usage)
            )
        ):
            raise GraphitiSpendReconciliationError(
                "retained spend provider usage differs from missing attempt receipt usage"
            )
        journal_provider_usage = journal.get("provider_usage")
        if isinstance(journal_provider_usage, Mapping):
            proposed_usage = _string_object_mapping(
                journal_provider_usage, field="provider usage"
            )
            if provider_usage is not None and not receipt_usage_is_prior_attempt:
                _require_equal_usage_evidence(
                    provider_usage,
                    proposed_usage,
                    field="retained spend usage",
                )
            if receipt is not None:
                if receipt_provider_usage is not None:
                    _require_equal_usage_evidence(
                        receipt_provider_usage,
                        proposed_usage,
                        field="attempt receipt usage",
                    )
                elif receipt.get("provider_attempt_number") is not None:
                    raise GraphitiSpendReconciliationError(
                        "graph journal provider usage differs from missing attempt receipt usage"
                    )
            if provider_usage is None and receipt_provider_usage is None:
                raise GraphitiSpendReconciliationError(
                    "graph journal provider usage is not independently retained"
                )
            if not receipt_usage_is_prior_attempt:
                provider_usage = proposed_usage
        prior_usage = recovered_prior_usage.get(spend_id)
        if prior_usage is not None:
            if provider_usage is not None and is_exact_provider_reported_usage(
                provider_usage
            ):
                _require_equal_usage_evidence(
                    provider_usage, prior_usage, field="recovered prior usage"
                )
            else:
                provider_usage = prior_usage
        status = str(row["status"])
        if _receipt_proves_pre_provider_refusal(receipt, journal):
            transitions.append(
                _transition(
                    row,
                    disposition=GraphitiSpendDisposition.RELEASED_BEFORE_PROVIDER_IO,
                    evidence_basis="PROVIDER_DISPATCH_STRUCTURALLY_RULED_OUT",
                    journal=journal,
                    receipt=receipt,
                    provider_usage=provider_usage,
                )
            )
            continue
        if recovered_without_dispatch:
            transitions.append(
                _transition(
                    row,
                    disposition=GraphitiSpendDisposition.RELEASED_BEFORE_PROVIDER_IO,
                    evidence_basis=(
                        "RECOVERED_COMPLETE_WITHOUT_SECOND_PROVIDER_DISPATCH"
                    ),
                    journal=journal,
                    receipt=receipt,
                    provider_usage=provider_usage,
                )
            )
            continue
        if duplicate_current_attribution:
            transitions.append(
                _transition(
                    row,
                    disposition=GraphitiSpendDisposition.AMBIGUOUS_EFFECT_HOLD,
                    evidence_basis="DUPLICATE_CROSS_ATTEMPT_PROVIDER_ATTRIBUTION",
                    journal=journal,
                    receipt=receipt,
                    provider_usage=provider_usage,
                )
            )
            continue
        if (
            receipt is None
            and provider_usage is not None
            and (
                is_exact_provider_reported_usage(provider_usage)
                or is_exact_no_embedding_call(provider_usage)
            )
        ):
            transitions.append(
                _transition(
                    row,
                    disposition=GraphitiSpendDisposition.AMBIGUOUS_EFFECT_HOLD,
                    evidence_basis="PROVIDER_USAGE_WITHOUT_DURABLE_ATTEMPT_RECEIPT",
                    journal=journal,
                    receipt=receipt,
                    provider_usage=provider_usage,
                )
            )
            continue
        if status == "RESERVED":
            if _has_live_graphiti_dispatch_lease(
                status=row["status"],
                owner=row["dispatch_owner"],
                lease_expires_at=row["dispatch_lease_expires_at"],
                at=evaluated,
            ):
                live.append(_live_reservation_snapshot(row))
                continue
            if provider_usage is not None and is_exact_provider_reported_usage(
                provider_usage
            ):
                transitions.append(
                    _transition(
                        row,
                        disposition=GraphitiSpendDisposition.RECONCILED,
                        evidence_basis="PROVIDER_NATIVE_USAGE_RECOVERED",
                        journal=journal,
                        receipt=receipt,
                        provider_usage=provider_usage,
                    )
                )
                continue
            transitions.append(
                _transition(
                    row,
                    disposition=GraphitiSpendDisposition.AMBIGUOUS_EFFECT_HOLD,
                    evidence_basis="STALE_RESERVATION_WITHOUT_TERMINAL_USAGE",
                    journal=journal,
                    receipt=receipt,
                    provider_usage=provider_usage,
                )
            )
            continue
        if status == "RECONCILED":
            if provider_usage is not None and is_exact_provider_reported_usage(
                provider_usage
            ):
                disposition = GraphitiSpendDisposition.RECONCILED
                basis = "PROVIDER_NATIVE_USAGE_RETAINED"
            elif provider_usage is not None and is_exact_no_embedding_call(
                provider_usage
            ):
                disposition = GraphitiSpendDisposition.RELEASED_BEFORE_PROVIDER_IO
                basis = "CANONICAL_NO_EMBEDDING_CALL_RETAINED"
            else:
                disposition = GraphitiSpendDisposition.UNRECONCILED_REPORTED_MISSING
                basis = "RECONCILED_ROW_WITHOUT_EXACT_PROVIDER_USAGE"
            transitions.append(
                _transition(
                    row,
                    disposition=disposition,
                    evidence_basis=basis,
                    journal=journal,
                    receipt=receipt,
                    provider_usage=provider_usage,
                )
            )
            continue
        if provider_usage is not None and is_exact_provider_reported_usage(
            provider_usage
        ):
            transitions.append(
                _transition(
                    row,
                    disposition=GraphitiSpendDisposition.RECONCILED,
                    evidence_basis="PROVIDER_NATIVE_USAGE_RECOVERED",
                    journal=journal,
                    receipt=receipt,
                    provider_usage=provider_usage,
                )
            )
            continue
        if receipt is not None:
            transitions.append(
                _transition(
                    row,
                    disposition=(
                        GraphitiSpendDisposition.UNRECONCILED_REPORTED_MISSING
                    ),
                    evidence_basis="TERMINAL_ATTEMPT_WITHOUT_PROVIDER_NATIVE_USAGE",
                    journal=journal,
                    receipt=receipt,
                    provider_usage=provider_usage,
                )
            )
        else:
            transitions.append(
                _transition(
                    row,
                    disposition=GraphitiSpendDisposition.AMBIGUOUS_EFFECT_HOLD,
                    evidence_basis="UNRECONCILED_WITHOUT_TERMINAL_RECEIPT",
                    journal=journal,
                    receipt=None,
                    provider_usage=provider_usage,
                )
            )
    unused_journal_spend_ids = set(journals) - observed_spend_ids
    if unused_journal_spend_ids:
        raise GraphitiSpendReconciliationError(
            "graph journal evidence does not join a retained spend: "
            + ", ".join(sorted(unused_journal_spend_ids))
        )
    terminal_attempt_count = int(
        connection.execute(
            "SELECT COUNT(*) FROM unpublished_graphiti_attempt_receipts"
        ).fetchone()[0]
    )
    retained_terminal_disposition_count = 0
    if _table_exists(connection, "unpublished_graphiti_spend_dispositions"):
        retained_terminal_disposition_count = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM unpublished_graphiti_spend_dispositions d
                JOIN unpublished_graphiti_attempt_receipts r
                  ON r.ingest_id=d.ingest_id
                 AND r.attempt_number=d.attempt_number
                """
            ).fetchone()[0]
        )
    planned_terminal_disposition_count = retained_terminal_disposition_count + sum(
        item.attempt_receipt_digest is not None for item in transitions
    )
    if planned_terminal_disposition_count != terminal_attempt_count:
        raise GraphitiSpendReconciliationError(
            "terminal attempt count differs from terminal spend disposition count"
        )
    return GraphitiSpendReconciliationPlan(
        evaluated_at=_utc_text(evaluated),
        transitions=tuple(transitions),
        live_reservations=tuple(live),
        terminal_attempt_count=terminal_attempt_count,
        planned_terminal_disposition_count=planned_terminal_disposition_count,
    )


def plan_graphiti_spend_reconciliation(
    path: str,
    *,
    evaluated_at: datetime,
    graph_journal_evidence: Mapping[str, Mapping[str, object]] | None = None,
) -> GraphitiSpendReconciliationPlan:
    """List evidence-bound transitions without opening the store for writing."""

    connection = _read_only(path)
    try:
        return _plan_from_connection(
            connection,
            evaluated_at=evaluated_at,
            graph_journal_evidence=graph_journal_evidence,
        )
    finally:
        connection.close()


def _ensure_reconciliation_schema(connection: sqlite3.Connection) -> None:
    connection.execute("""
        CREATE TABLE IF NOT EXISTS unpublished_graphiti_spend_dispositions(
            spend_id TEXT PRIMARY KEY,
            ingest_id TEXT NOT NULL,
            attempt_number INTEGER NOT NULL,
            disposition TEXT NOT NULL CHECK(disposition IN (
                'RECONCILED',
                'UNRECONCILED_REPORTED_MISSING',
                'RELEASED_BEFORE_PROVIDER_IO',
                'AMBIGUOUS_EFFECT_HOLD'
            )),
            reserved_gbp_microunits INTEGER NOT NULL,
            source_proving_run_id TEXT NOT NULL,
            source_generation_id TEXT,
            source_actual_usd_microunits INTEGER,
            source_actual_gbp_microunits INTEGER,
            source_provider_usage_json TEXT,
            source_dispatch_owner TEXT,
            source_dispatch_lease_expires_at TEXT,
            source_at TEXT NOT NULL,
            actual_usd_microunits INTEGER,
            actual_gbp_microunits INTEGER,
            fx_policy TEXT NOT NULL,
            source_status TEXT NOT NULL,
            source_usage_basis TEXT NOT NULL,
            target_status TEXT NOT NULL,
            target_usage_basis TEXT NOT NULL,
            unused_reservation_released INTEGER NOT NULL CHECK(
                unused_reservation_released IN (0, 1)
            ),
            evidence_basis TEXT NOT NULL,
            attempt_receipt_digest TEXT,
            evidence_digest TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            command_id TEXT NOT NULL,
            at TEXT NOT NULL,
            UNIQUE(ingest_id, attempt_number)
        )
        """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS unpublished_graphiti_spend_reconciliation_receipts(
            idempotency_key TEXT PRIMARY KEY,
            plan_digest TEXT NOT NULL,
            plan_json TEXT NOT NULL,
            receipt_digest TEXT NOT NULL,
            receipt_json TEXT NOT NULL,
            at TEXT NOT NULL
        )
        """)
    receipt_columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(unpublished_graphiti_spend_reconciliation_receipts)"
        ).fetchall()
    }
    if "plan_json" not in receipt_columns:
        connection.execute(
            "ALTER TABLE unpublished_graphiti_spend_reconciliation_receipts "
            "ADD COLUMN plan_json TEXT"
        )


def _backfill_legacy_retained_plan(
    connection: sqlite3.Connection,
    *,
    idempotency_key: str,
    expected_plan_digest: str,
    dry_run_plan: Mapping[str, object],
) -> None:
    connection.execute(
        "UPDATE unpublished_graphiti_spend_reconciliation_receipts "
        "SET plan_json=? WHERE idempotency_key=? AND plan_digest=? "
        "AND plan_json IS NULL",
        (
            canonical_json_bytes(dry_run_plan).decode("utf-8"),
            idempotency_key,
            expected_plan_digest,
        ),
    )


def _retained_receipt(
    connection: sqlite3.Connection, idempotency_key: str
) -> GraphitiSpendReconciliationReceipt | None:
    row = connection.execute(
        "SELECT idempotency_key, plan_digest, receipt_digest, receipt_json, at FROM "
        "unpublished_graphiti_spend_reconciliation_receipts "
        "WHERE idempotency_key=?",
        (idempotency_key,),
    ).fetchone()
    if row is None:
        return None
    raw_receipt = str(row[3])
    value = _json_object(raw_receipt, field="retained reconciliation receipt")
    if value is None:
        raise GraphitiSpendReconciliationError(
            "retained reconciliation receipt is absent"
        )
    if raw_receipt.encode("utf-8") != canonical_json_bytes(value):
        raise GraphitiSpendReconciliationError(
            "retained reconciliation receipt is not the exact canonical record"
        )
    receipt = GraphitiSpendReconciliationReceipt.from_dict(value)
    if (
        row[0] != receipt.idempotency_key
        or row[1] != receipt.plan_digest
        or row[2] != receipt.receipt_digest
        or row[4] != receipt.applied_at
    ):
        raise GraphitiSpendReconciliationError(
            "retained reconciliation receipt columns differ from its bytes"
        )
    _retained_plan(connection, idempotency_key)
    _validate_reconciliation_ledger(connection, receipt)
    return receipt


def _retained_plan(
    connection: sqlite3.Connection, idempotency_key: str
) -> dict[str, object]:
    row = connection.execute(
        "SELECT plan_digest, plan_json FROM "
        "unpublished_graphiti_spend_reconciliation_receipts "
        "WHERE idempotency_key=?",
        (idempotency_key,),
    ).fetchone()
    if row is None:
        raise GraphitiSpendReconciliationError("retained reconciliation plan is absent")
    raw_plan = str(row[1])
    plan = _json_object(raw_plan, field="retained reconciliation plan")
    if plan is None or raw_plan.encode("utf-8") != canonical_json_bytes(plan):
        raise GraphitiSpendReconciliationError(
            "retained reconciliation plan is not the exact canonical record"
        )
    _validate_supplied_plan(plan, str(row[0]))
    return plan


def _validate_reconciliation_ledger(
    connection: sqlite3.Connection, receipt: GraphitiSpendReconciliationReceipt
) -> None:
    event = {
        "idempotency_key": receipt.idempotency_key,
        "plan_digest": receipt.plan_digest,
        "authenticated_principal": receipt.authenticated_principal,
        "applied_transition_count": receipt.applied_transition_count,
        "disposition_counts": dict(sorted(receipt.disposition_counts.items())),
        "applied_at": receipt.applied_at,
        "terminal_spend_disposition_count": (receipt.terminal_spend_disposition_count),
        "terminal_attempt_count": receipt.terminal_attempt_count,
        "live_reservation_count": receipt.live_reservation_count,
        "provider_calls": receipt.provider_calls,
        "public_dispatch": False,
        "graph_mutation": False,
    }
    row = connection.execute(
        "SELECT seq, at, kind, payload_digest, prev_digest, digest "
        "FROM ledger WHERE digest=?",
        (receipt.ledger_digest,),
    ).fetchone()
    expected_payload_digest = digest_bytes(canonical_json_bytes(event))
    if (
        row is None
        or row[2] != "GRAPHITI_SPEND_RECONCILIATION_APPLIED"
        or row[3] != expected_payload_digest
    ):
        raise GraphitiSpendReconciliationError(
            "retained reconciliation receipt differs from its ledger event"
        )
    previous_digest = "sha256:" + ("0" * 64)
    for expected_seq, chain_row in enumerate(
        connection.execute(
            "SELECT seq, at, kind, payload_digest, prev_digest, digest "
            "FROM ledger ORDER BY seq"
        ).fetchall(),
        start=1,
    ):
        expected_row_digest = digest_bytes(
            canonical_json_bytes(
                {
                    "at": chain_row[1],
                    "kind": chain_row[2],
                    "payload_digest": chain_row[3],
                    "prev": chain_row[4],
                }
            )
        )
        if (
            chain_row[0] != expected_seq
            or chain_row[4] != previous_digest
            or chain_row[5] != expected_row_digest
        ):
            raise GraphitiSpendReconciliationError(
                "retained reconciliation ledger chain differs"
            )
        previous_digest = str(chain_row[5])


def _validate_supplied_plan(
    dry_run_plan: Mapping[str, object], expected_plan_digest: str
) -> None:
    supplied_plan = dict(dry_run_plan)
    supplied_plan_digest = supplied_plan.pop("plan_digest", None)
    if (
        supplied_plan_digest != expected_plan_digest
        or digest_bytes(canonical_json_bytes(supplied_plan)) != expected_plan_digest
    ):
        raise GraphitiSpendReconciliationError(
            "dry-run plan bytes differ from the expected plan digest"
        )


def _apply_graphiti_spend_reconciliation(
    path: str,
    *,
    dry_run_plan: Mapping[str, object],
    evaluated_at: datetime,
    graph_journal_evidence: Mapping[str, Mapping[str, object]] | None,
    command: _GraphitiSpendReconciliationCommand,
) -> GraphitiSpendReconciliationReceipt:
    """Apply one authenticated plan atomically and retain its canonical receipt."""

    _assert_command_authority(command)
    resolved_path = _private_resolved_path(path)
    connection = sqlite3.connect(str(resolved_path))
    apply_control_plane_sqlite_profile(connection)
    try:
        connection.execute("BEGIN IMMEDIATE")
        _ensure_reconciliation_schema(connection)
        retained_identity = connection.execute(
            "SELECT plan_digest FROM "
            "unpublished_graphiti_spend_reconciliation_receipts "
            "WHERE idempotency_key=?",
            (command.idempotency_key,),
        ).fetchone()
        if (
            retained_identity is not None
            and retained_identity[0] != command.expected_plan_digest
        ):
            raise GraphitiSpendReconciliationError(
                "idempotency key was reused for a different plan"
            )
        _validate_supplied_plan(dry_run_plan, command.expected_plan_digest)
        _backfill_legacy_retained_plan(
            connection,
            idempotency_key=command.idempotency_key,
            expected_plan_digest=command.expected_plan_digest,
            dry_run_plan=dry_run_plan,
        )
        retained = _retained_receipt(connection, command.idempotency_key)
        if retained is not None:
            retained_plan = _retained_plan(connection, command.idempotency_key)
            if canonical_json_bytes(retained_plan) != canonical_json_bytes(
                dry_run_plan
            ):
                raise GraphitiSpendReconciliationError(
                    "idempotent dry-run plan differs from the retained plan"
                )
            _validate_retained_dispositions(connection)
            connection.commit()
            return retained
        live_plan = _plan_from_connection(
            connection,
            evaluated_at=evaluated_at,
            graph_journal_evidence=graph_journal_evidence,
        )
        if live_plan.plan_digest != command.expected_plan_digest:
            raise GraphitiSpendReconciliationError(
                "store changed after the dry-run plan"
            )
        if canonical_json_bytes(live_plan.as_dict()) != canonical_json_bytes(
            dry_run_plan
        ):
            raise GraphitiSpendReconciliationError(
                "dry-run plan bytes differ from the live plan"
            )

        apply_instant = datetime.now(tz=UTC)
        for transition in live_plan.transitions:
            if _has_live_graphiti_dispatch_lease(
                status=transition.source_status,
                owner=transition.source_dispatch_owner,
                lease_expires_at=transition.source_dispatch_lease_expires_at,
                at=apply_instant,
            ):
                raise GraphitiSpendReconciliationError(
                    "active dispatch lease cannot be reconciled"
                )
        for reservation in live_plan.live_reservations:
            if not _has_live_graphiti_dispatch_lease(
                status=reservation.status,
                owner=reservation.dispatch_owner,
                lease_expires_at=reservation.dispatch_lease_expires_at,
                at=apply_instant,
            ):
                raise GraphitiSpendReconciliationError(
                    "planned live dispatch lease is no longer active"
                )
        applied_at = _utc_text(apply_instant)
        counts: dict[str, int] = {}
        for transition in live_plan.transitions:
            evidence = transition.as_dict()
            evidence_json = canonical_json_bytes(evidence).decode("utf-8")
            evidence_digest = digest_bytes(evidence_json.encode("utf-8"))
            connection.execute(
                """
                INSERT INTO unpublished_graphiti_spend_dispositions(
                    spend_id, ingest_id, attempt_number, disposition,
                    reserved_gbp_microunits, source_proving_run_id,
                    source_generation_id, source_actual_usd_microunits,
                    source_actual_gbp_microunits, source_provider_usage_json,
                    source_dispatch_owner, source_dispatch_lease_expires_at,
                    source_at, actual_usd_microunits,
                    actual_gbp_microunits, fx_policy, source_status,
                    source_usage_basis, target_status, target_usage_basis,
                    unused_reservation_released, evidence_basis,
                    attempt_receipt_digest, evidence_digest, evidence_json,
                    command_id, at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    transition.spend_id,
                    transition.ingest_id,
                    transition.attempt_number,
                    transition.disposition.value,
                    transition.reserved_gbp_microunits,
                    transition.source_proving_run_id,
                    transition.source_generation_id,
                    transition.source_actual_usd_microunits,
                    transition.source_actual_gbp_microunits,
                    (
                        None
                        if transition.source_provider_usage is None
                        else canonical_json_bytes(
                            transition.source_provider_usage
                        ).decode("utf-8")
                    ),
                    transition.source_dispatch_owner,
                    transition.source_dispatch_lease_expires_at,
                    transition.source_at,
                    transition.actual_usd_microunits,
                    transition.actual_gbp_microunits,
                    transition.fx_policy,
                    transition.source_status,
                    transition.source_usage_basis,
                    transition.target_status,
                    transition.target_usage_basis,
                    int(transition.unused_reservation_released),
                    transition.evidence_basis,
                    transition.attempt_receipt_digest,
                    evidence_digest,
                    evidence_json,
                    command.idempotency_key,
                    applied_at,
                ),
            )
            recovered_usage = transition.provider_usage
            retained_usage = (
                canonical_json_bytes(recovered_usage).decode("utf-8")
                if isinstance(recovered_usage, Mapping)
                and (
                    is_exact_provider_reported_usage(recovered_usage)
                    or is_exact_no_embedding_call(recovered_usage)
                )
                else None
            )
            connection.execute(
                """
                UPDATE unpublished_graphiti_spend
                SET status=?, actual_usd_microunits=?,
                    actual_gbp_microunits=?, usage_basis=?,
                    provider_usage_json=COALESCE(?, provider_usage_json),
                    dispatch_owner=NULL, dispatch_lease_expires_at=NULL, at=?
                WHERE spend_id=?
                """,
                (
                    transition.target_status,
                    transition.actual_usd_microunits,
                    transition.actual_gbp_microunits,
                    transition.target_usage_basis,
                    retained_usage,
                    applied_at,
                    transition.spend_id,
                ),
            )
            counts[transition.disposition.value] = (
                counts.get(transition.disposition.value, 0) + 1
            )

        event = {
            "idempotency_key": command.idempotency_key,
            "plan_digest": live_plan.plan_digest,
            "authenticated_principal": command.caller_principal,
            "applied_transition_count": len(live_plan.transitions),
            "disposition_counts": dict(sorted(counts.items())),
            "applied_at": applied_at,
            "terminal_spend_disposition_count": (
                live_plan.planned_terminal_disposition_count
            ),
            "terminal_attempt_count": live_plan.terminal_attempt_count,
            "live_reservation_count": len(live_plan.live_reservation_spend_ids),
            "provider_calls": 0,
            "public_dispatch": False,
            "graph_mutation": False,
        }
        ledger_digest = append_ledger(
            connection, "GRAPHITI_SPEND_RECONCILIATION_APPLIED", event
        )
        terminal_count = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM unpublished_graphiti_spend_dispositions d
                JOIN unpublished_graphiti_attempt_receipts r
                  ON r.ingest_id=d.ingest_id
                 AND r.attempt_number=d.attempt_number
                """
            ).fetchone()[0]
        )
        terminal_attempt_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM unpublished_graphiti_attempt_receipts"
            ).fetchone()[0]
        )
        if terminal_count != terminal_attempt_count:
            raise GraphitiSpendReconciliationError(
                "terminal attempt count differs from terminal spend disposition count"
            )
        unsigned_receipt = GraphitiSpendReconciliationReceipt(
            idempotency_key=command.idempotency_key,
            plan_digest=live_plan.plan_digest,
            authenticated_principal=command.caller_principal,
            applied_at=applied_at,
            applied_transition_count=len(live_plan.transitions),
            disposition_counts=counts,
            terminal_spend_disposition_count=terminal_count,
            terminal_attempt_count=terminal_attempt_count,
            live_reservation_count=len(live_plan.live_reservation_spend_ids),
            provider_calls=0,
            ledger_digest=ledger_digest,
            receipt_digest="",
        )
        receipt_digest = digest_bytes(
            canonical_json_bytes(unsigned_receipt._unsigned())
        )
        receipt = GraphitiSpendReconciliationReceipt(
            idempotency_key=unsigned_receipt.idempotency_key,
            plan_digest=unsigned_receipt.plan_digest,
            authenticated_principal=unsigned_receipt.authenticated_principal,
            applied_at=unsigned_receipt.applied_at,
            applied_transition_count=unsigned_receipt.applied_transition_count,
            disposition_counts=unsigned_receipt.disposition_counts,
            terminal_spend_disposition_count=(
                unsigned_receipt.terminal_spend_disposition_count
            ),
            terminal_attempt_count=unsigned_receipt.terminal_attempt_count,
            live_reservation_count=unsigned_receipt.live_reservation_count,
            provider_calls=unsigned_receipt.provider_calls,
            ledger_digest=unsigned_receipt.ledger_digest,
            receipt_digest=receipt_digest,
        )
        receipt_json = canonical_json_bytes(receipt.as_dict()).decode("utf-8")
        connection.execute(
            """
            INSERT INTO unpublished_graphiti_spend_reconciliation_receipts(
                idempotency_key, plan_digest, plan_json,
                receipt_digest, receipt_json, at
            ) VALUES(?,?,?,?,?,?)
            """,
            (
                command.idempotency_key,
                live_plan.plan_digest,
                canonical_json_bytes(live_plan.as_dict()).decode("utf-8"),
                receipt_digest,
                receipt_json,
                applied_at,
            ),
        )
        connection.commit()
        return receipt
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()


__all__ = [
    "GraphitiSpendDisposition",
    "GraphitiSpendReconciliationError",
    "GraphitiSpendReconciliationPlan",
    "GraphitiSpendReconciliationReceipt",
    "GraphitiSpendTransition",
    "plan_graphiti_spend_reconciliation",
]
