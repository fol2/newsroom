"""Provider-free reconciliation of durable Graphiti spend reservations."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.control_plane.sqlite_profile import apply_control_plane_sqlite_profile
from newsroom.control_plane.command_auth import HERMES_COMMAND_PRINCIPAL
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
    graph_journal_state: str
    graph_journal_digest: str
    graph_journal_evidence: dict[str, object]
    reserved_gbp_microunits: int
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
            "graph_journal_state": self.graph_journal_state,
            "graph_journal_digest": self.graph_journal_digest,
            "graph_journal_evidence": self.graph_journal_evidence,
            "reserved_gbp_microunits": self.reserved_gbp_microunits,
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
class GraphitiSpendReconciliationPlan:
    evaluated_at: str
    transitions: tuple[GraphitiSpendTransition, ...]
    live_reservation_spend_ids: tuple[str, ...]
    terminal_attempt_count: int
    planned_terminal_disposition_count: int
    provider_calls: int = 0

    def _unsigned(self) -> dict[str, object]:
        return {
            "schema": "newsroom.control-plane.graphiti-spend-reconciliation-plan.v1",
            "evaluated_at": self.evaluated_at,
            "provider_calls": self.provider_calls,
            "transitions": [item.as_dict() for item in self.transitions],
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
        return receipt


def _required_non_negative_int(value: object, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise GraphitiSpendReconciliationError(
            f"retained reconciliation receipt {field} is invalid"
        )
    return value


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
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (
        parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    )


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
    row: sqlite3.Row, receipt: Mapping[str, object] | None
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
        receipt.get("ingest_id") != row["ingest_id"]
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


def _validate_journal_evidence(
    row: sqlite3.Row,
    journal: Mapping[str, object],
    receipt: Mapping[str, object] | None,
) -> None:
    if not journal:
        return
    if journal.get("evidence_source") != "GRAPH_JOURNAL_EXPORT_V1":
        raise GraphitiSpendReconciliationError(
            "graph journal evidence source is not durable"
        )
    if (
        journal.get("spend_id") != row["spend_id"]
        or journal.get("ingest_id") != row["ingest_id"]
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
        recovered_complete = _recovered_without_provider_dispatch(row, journal)
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
    if "provider_leaves" in journal and not isinstance(
        journal["provider_leaves"], list
    ):
        raise GraphitiSpendReconciliationError(
            "graph journal provider leaves are not a list"
        )
    current_marker = journal.get("marker_attempt_number") == row["attempt_number"]
    if current_marker and receipt is not None and "provider_leaves" in journal:
        if journal["provider_leaves"] != receipt.get("chat_invocations"):
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


def _recovered_without_provider_dispatch(
    row: sqlite3.Row, journal: Mapping[str, object]
) -> bool:
    marker_attempt = journal.get("marker_attempt_number")
    return (
        journal.get("state") == "COMPLETE"
        and isinstance(marker_attempt, int)
        and not isinstance(marker_attempt, bool)
        and marker_attempt < row["attempt_number"]
        and journal.get("provider_attempt_number") == marker_attempt
        and journal.get("reconciliation_attempt_number") == row["attempt_number"]
        and journal.get("recovery_classification") == "RECOVERED_IMMUTABLE_COMPLETE"
        and journal.get("provider_dispatch_state") == "NOT_DISPATCHED"
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
        and (
            embedding_usage is None
            or (
                isinstance(embedding_usage, Mapping)
                and is_exact_no_embedding_call(embedding_usage)
            )
        )
        and journal.get("provider_dispatch_state") == "NOT_DISPATCHED"
        and journal.get("state") in {"ABSENT", "CREATED"}
    )


def _read_only(path: str) -> sqlite3.Connection:
    resolved = Path(path).expanduser().resolve()
    return sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)


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
        graph_journal_state=graph_journal_state,
        graph_journal_digest=graph_journal_digest,
        graph_journal_evidence=journal_value,
        reserved_gbp_microunits=int(row["reserved_gbp_microunits"]),
        actual_usd_microunits=(None if actual_usd is None else int(actual_usd)),
        actual_gbp_microunits=(None if actual_gbp is None else int(actual_gbp)),
        fx_policy=fx_policy,
        source_status=source_status,
        source_usage_basis=source_usage_basis,
        target_status=target_status,
        target_usage_basis=target_usage_basis,
        unused_reservation_released=released,
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
    journals = graph_journal_evidence or {}
    connection.row_factory = sqlite3.Row
    if not _table_exists(connection, "unpublished_graphiti_spend"):
        return GraphitiSpendReconciliationPlan(_utc_text(evaluated), (), (), 0, 0)
    disposition_join = (
        "LEFT JOIN unpublished_graphiti_spend_dispositions d "
        "ON d.spend_id=s.spend_id"
        if _table_exists(connection, "unpublished_graphiti_spend_dispositions")
        else ""
    )
    disposition_filter = "AND d.spend_id IS NULL" if disposition_join else ""
    rows = connection.execute(f"""
        SELECT s.*,
               r.outcome AS attempt_outcome,
               r.receipt_digest AS attempt_receipt_digest,
               r.receipt_json AS attempt_receipt_json
        FROM unpublished_graphiti_spend s
        LEFT JOIN unpublished_graphiti_attempt_receipts r
          ON r.ingest_id=s.ingest_id
         AND r.attempt_number=s.attempt_number
        {disposition_join}
        WHERE 1=1 {disposition_filter}
        ORDER BY s.ingest_id, s.attempt_number
        """).fetchall()

    transitions: list[GraphitiSpendTransition] = []
    live: list[str] = []
    for row in rows:
        spend_id = str(row["spend_id"])
        receipt = _json_object(
            row["attempt_receipt_json"], field=f"attempt receipt {spend_id}"
        )
        _validate_attempt_receipt(row, receipt)
        journal = journals.get(spend_id, {})
        _validate_journal_evidence(row, journal, receipt)
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
        if provider_usage is not None and receipt_provider_usage is not None:
            _require_equal_usage_evidence(
                provider_usage,
                receipt_provider_usage,
                field="attempt receipt usage",
            )
        elif provider_usage is None and receipt_provider_usage is not None:
            provider_usage = receipt_provider_usage
        elif (
            receipt is not None
            and provider_usage is not None
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
            if provider_usage is not None:
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
            provider_usage = proposed_usage
        status = str(row["status"])
        if status == "RESERVED":
            lease = _instant(
                None
                if row["dispatch_lease_expires_at"] is None
                else str(row["dispatch_lease_expires_at"])
            )
            if lease is not None and lease > evaluated:
                live.append(spend_id)
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
            if _receipt_proves_pre_provider_refusal(receipt, journal):
                transitions.append(
                    _transition(
                        row,
                        disposition=(
                            GraphitiSpendDisposition.RELEASED_BEFORE_PROVIDER_IO
                        ),
                        evidence_basis="PROVIDER_DISPATCH_STRUCTURALLY_RULED_OUT",
                        journal=journal,
                        receipt=receipt,
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
                disposition = (
                    GraphitiSpendDisposition.UNRECONCILED_REPORTED_MISSING
                )
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
        if _recovered_without_provider_dispatch(row, journal):
            transitions.append(
                _transition(
                    row,
                    disposition=(GraphitiSpendDisposition.RELEASED_BEFORE_PROVIDER_IO),
                    evidence_basis=(
                        "RECOVERED_COMPLETE_WITHOUT_SECOND_PROVIDER_DISPATCH"
                    ),
                    journal=journal,
                    receipt=receipt,
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
                )
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
        live_reservation_spend_ids=tuple(live),
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
            receipt_digest TEXT NOT NULL,
            receipt_json TEXT NOT NULL,
            at TEXT NOT NULL
        )
        """)


def _retained_receipt(
    connection: sqlite3.Connection, idempotency_key: str
) -> GraphitiSpendReconciliationReceipt | None:
    row = connection.execute(
        "SELECT receipt_json FROM "
        "unpublished_graphiti_spend_reconciliation_receipts "
        "WHERE idempotency_key=?",
        (idempotency_key,),
    ).fetchone()
    if row is None:
        return None
    value = _json_object(row[0], field="retained reconciliation receipt")
    if value is None:
        raise GraphitiSpendReconciliationError(
            "retained reconciliation receipt is absent"
        )
    return GraphitiSpendReconciliationReceipt.from_dict(value)


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
    assert_private_store(path)
    connection = sqlite3.connect(str(Path(path).expanduser().resolve()))
    apply_control_plane_sqlite_profile(connection)
    try:
        connection.execute("BEGIN IMMEDIATE")
        _ensure_reconciliation_schema(connection)
        retained = _retained_receipt(connection, command.idempotency_key)
        if retained is not None:
            if retained.plan_digest != command.expected_plan_digest:
                raise GraphitiSpendReconciliationError(
                    "idempotency key was reused for a different plan"
                )
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
        if live_plan.as_dict() != dict(dry_run_plan):
            raise GraphitiSpendReconciliationError(
                "dry-run plan bytes differ from the live plan"
            )

        applied_at = _utc_text(datetime.now(tz=UTC))
        counts: dict[str, int] = {}
        for transition in live_plan.transitions:
            evidence = transition.as_dict()
            evidence_json = canonical_json_bytes(evidence).decode("utf-8")
            evidence_digest = digest_bytes(evidence_json.encode("utf-8"))
            connection.execute(
                """
                INSERT INTO unpublished_graphiti_spend_dispositions(
                    spend_id, ingest_id, attempt_number, disposition,
                    reserved_gbp_microunits, actual_usd_microunits,
                    actual_gbp_microunits, fx_policy, source_status,
                    source_usage_basis, target_status, target_usage_basis,
                    unused_reservation_released, evidence_basis,
                    attempt_receipt_digest, evidence_digest, evidence_json,
                    command_id, at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    transition.spend_id,
                    transition.ingest_id,
                    transition.attempt_number,
                    transition.disposition.value,
                    transition.reserved_gbp_microunits,
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
            recovered_usage = transition.graph_journal_evidence.get("provider_usage")
            retained_usage = (
                canonical_json_bytes(recovered_usage).decode("utf-8")
                if isinstance(recovered_usage, Mapping)
                and is_exact_provider_reported_usage(recovered_usage)
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
                idempotency_key, plan_digest, receipt_digest, receipt_json, at
            ) VALUES(?,?,?,?,?)
            """,
            (
                command.idempotency_key,
                live_plan.plan_digest,
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
