"""Unique pre-dispatch prepare for issue #790. One decision digest, fail-closed.

Preflight READY, live apply, and ``run_issue_790_canary`` consume this module.
``available_at`` is class C (audit only) and must not become a new authority gate.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from newsroom.authority.canonical import digest_canonical

from newsroom.control_plane.issue_790_canary import (
    RetryForbiddenSafetyError,
    RetryForbiddenSafetyState,
    retry_forbidden_has_claim_columns,
    retry_forbidden_live_select,
    retry_forbidden_live_snapshot,
    unmatched_bounded_canary_consumption,
)
from newsroom.control_plane.issue_790_contract import ISSUE_790_STEP22_PENDING_DIGEST
from newsroom.control_plane.issue_790_disposition import Issue790DispositionError
from newsroom.graphiti_adapter.combined_temporal_projection import (
    PROJECTION_POLICY_DIGEST,
)

PrepareRole = Literal["preflight", "apply", "canary"]

CANDIDATE_EVENT_ID = (
    "sha256:b39a1e6ea465ca4a993893d4ae51c94ca9ac3e0db7f4fd70a8c780367263be6b"
)
CANDIDATE_LEDGER_SEQ = 13665
TRACKED_PLAN_NAME = "issue-790-bounded-graphiti-canary"

PREPARED_CANARY_ABSENT = "PREPARED_CANARY_ABSENT"
PREPARED_CANARY_DIGEST_DRIFT = "PREPARED_CANARY_DIGEST_DRIFT"
PREPARED_CANARY_RECORD_INVALID = "PREPARED_CANARY_RECORD_INVALID"
PREPARED_CANARY_RECORD_SCHEMA = "newsroom.issue-790.prepared-canary.v1"
BOUNDED_CANARY_AUTHORITY_CONSUMED = "BOUNDED_CANARY_AUTHORITY_CONSUMED"

FIELD_CLASSIFICATION: dict[str, str] = {
    "exact_head": "A",
    "candidate_event_id": "A",
    "candidate_ledger_seq": "A",
    "candidate_manifest_digest": "A",
    "plan_pending_digest": "A",
    "retry_forbidden_event_ids": "A",
    "projection_policy_digest": "A",
    "call_shape_policy_digest": "A",
    "fallback_mode": "A",
    "event_binding": "A",
    "retry_safety_states": "B",
    "candidate_state": "B",
    "candidate_attempt_count": "B",
    "candidate_provider_dispatched": "B",
    "candidate_claim_present": "B",
    "retry_claim_present": "B",
    "consumption_present": "B",
    "outcome_present": "B",
    "receipt_present": "B",
    "non_effects": "A",
    "available_at": "C",
    "claim_expires_at": "C",
    "observed_at": "C",
    "historical_snapshot_time": "C",
    "provider_response": "D",
    "usage": "D",
    "latency": "D",
    "network": "D",
    "graph_embedding": "D",
}


@dataclass(frozen=True, slots=True)
class FailBranch:
    """One pre-provider-transport fail-closed condition."""

    invariant: str
    failure_code: str
    preflight_checks: bool
    positive_test: str
    negative_test: str
    zero_provider_calls: bool = True


FAIL_BRANCH_INVENTORY: tuple[FailBranch, ...] = (
    FailBranch(
        "exact_head_present",
        "EXACT_HEAD_ABSENT",
        True,
        "test_ready_digest_is_stable_for_unchanged_copy",
        "test_missing_exact_head_fail_closes",
    ),
    FailBranch(
        "candidate_identity",
        "CANDIDATE_IDENTITY",
        True,
        "test_step22_spent_13665_successor_unused_attempt_zero_survives_full_path",
        "test_cli_flags_disagree_with_unused_candidate_fail_closes",
    ),
    FailBranch(
        "store_readable",
        "STORE_ABSENT",
        True,
        "test_ready_digest_is_stable_for_unchanged_copy",
        "test_missing_store_fail_closes",
    ),
    FailBranch(
        "paths_disjoint",
        "PATHS_ALIAS",
        True,
        "test_ready_implies_dispatch_started",
        "test_alias_proving_live_paths_fail_close",
    ),
    FailBranch(
        "retry_forbidden_safety_state",
        "RETRY_FORBIDDEN_SAFETY_STATE",
        True,
        "test_prepared_canary_accepts_13361_available_at_drift",
        "test_exhausted_safety_mutation_fail_closes",
    ),
    FailBranch(
        "claim_or_lease_absent",
        "RETRY_FORBIDDEN_SAFETY_STATE",
        True,
        "test_prepared_canary_accepts_13361_available_at_drift",
        "test_claim_or_lease_fail_closes",
    ),
    FailBranch(
        "candidate_untouched",
        "CANDIDATE_NOT_FRESH",
        True,
        "test_ready_implies_dispatch_started",
        "test_candidate_claim_fail_closes",
    ),
    FailBranch(
        "unmatched_plan_consumption",
        BOUNDED_CANARY_AUTHORITY_CONSUMED,
        True,
        "test_step22_sealed_13689_abort_allows_successor_unused_without_already_consumed",
        "test_step22_unmatched_13689_consumption_blocks_successor_ready_before_backup",
    ),
    FailBranch(
        "prepared_canary_present",
        PREPARED_CANARY_ABSENT,
        True,
        "test_canary_consumes_prepared_digest_only",
        "test_missing_prepared_canary_fail_closes_before_dispatch",
    ),
    FailBranch(
        "prepared_canary_digest_stable",
        PREPARED_CANARY_DIGEST_DRIFT,
        True,
        "test_ready_implies_dispatch_started",
        "test_digest_drift_fail_closes_before_dispatch",
    ),
    FailBranch(
        "prepared_canary_record_valid",
        PREPARED_CANARY_RECORD_INVALID,
        True,
        "test_prepared_canary_record_round_trip",
        "test_prepared_canary_record_tamper_fail_closes",
    ),
    FailBranch(
        "live_store_write_refused",
        "LIVE_STORE_WRITE_REFUSED",
        True,
        "test_ready_implies_dispatch_started",
        "test_rehearsal_refuses_canonical_live_store_paths",
    ),
    FailBranch(
        "retry_forbidden_target",
        "RETRY_FORBIDDEN_TARGET",
        True,
        "test_spent_13665_is_retry_forbidden_target",
        "test_retry_forbidden_target_fail_closes",
    ),
    FailBranch(
        "event_identity",
        "EVENT_IDENTITY_INVALID",
        True,
        "test_ready_implies_dispatch_started",
        "test_event_identity_invalid_fail_closes",
    ),
    FailBranch(
        "dispatch_before_crash_unconsumed",
        "REHEARSAL_CRASH_BEFORE_DISPATCH",
        True,
        "test_dispatch_before_crash_leaves_candidate_unconsumed",
        "test_dispatch_before_crash_leaves_candidate_unconsumed",
    ),
)


LIVE_ONLY_PREDISPATCH_GATES: tuple[str, ...] = (
    "approved_plan_is_live_authority",
    "exact_main_operational_evidence",
    "worker_unloaded",
    "store_target_fingerprint",
    "sequence_predecessor",
    "canary_route_closed",
    "step16_runtime_semantics",
    "event_circuit_policy",
)


@dataclass(frozen=True, slots=True)
class PreparedCanary:
    """Canonical pre-dispatch decision. Digest hashes class A and B only."""

    exact_head: str
    candidate_identity: dict[str, object]
    safety_state: dict[str, object]
    plan_identity: dict[str, object]
    retry_exclusion_identity: dict[str, object]
    runtime_identity: dict[str, object]
    non_effects: tuple[str, ...]
    decision_digest: str
    observations: dict[str, object] = field(default_factory=dict)
    qualification_evidence: dict[str, object] | None = None
    record_digest: str | None = None

    def as_decision_payload(self) -> dict[str, object]:
        return _decision_payload(
            exact_head=self.exact_head,
            candidate_identity=self.candidate_identity,
            safety_state=self.safety_state,
            plan_identity=self.plan_identity,
            retry_exclusion_identity=self.retry_exclusion_identity,
            runtime_identity=self.runtime_identity,
            non_effects=self.non_effects,
            qualification_identity=_qualification_identity(
                self.qualification_evidence
            ),
        )


class PreparedCanaryError(Issue790DispositionError):
    """Named fail-closed prepare or digest-consume error. Provider I/O stays 0."""

    classification = "PREDISPATCH_BINDING_FAILURE"

    def __init__(self, message: str, *, failure_code: str) -> None:
        super().__init__(message)
        self.failure_code = failure_code


def _decision_payload(
    *,
    exact_head: str,
    candidate_identity: Mapping[str, object],
    safety_state: Mapping[str, object],
    plan_identity: Mapping[str, object],
    retry_exclusion_identity: Mapping[str, object],
    runtime_identity: Mapping[str, object],
    non_effects: Sequence[str],
    qualification_identity: Mapping[str, object] | None,
) -> dict[str, object]:
    return {
        "candidate_identity": dict(candidate_identity),
        "exact_head": exact_head,
        "non_effects": list(non_effects),
        "plan_identity": dict(plan_identity),
        "retry_exclusion_identity": dict(retry_exclusion_identity),
        "runtime_identity": dict(runtime_identity),
        "safety_state": dict(safety_state),
        "qualification_identity": (
            None
            if qualification_identity is None
            else dict(qualification_identity)
        ),
    }


def _op():
    from newsroom.control_plane import issue_790_disposition as op

    return op


def _raise(code: str, message: str) -> None:
    raise PreparedCanaryError(message, failure_code=code)


def _qualification_identity(
    qualification: Mapping[str, object] | None,
) -> dict[str, object] | None:
    """Return stable provider-free eligibility, excluding the check instant."""

    if qualification is None:
        return None
    retained = dict(qualification)
    supplied = retained.pop("evidence_digest", None)
    if supplied != digest_canonical(retained):
        _raise(
            PREPARED_CANARY_RECORD_INVALID,
            "prepared canary qualification digest differs",
        )
    retained.pop("evaluated_at", None)
    return retained


def prepared_canary_record(prepared: PreparedCanary) -> dict[str, object]:
    """Serialise one content-addressed cross-process canary decision."""

    decision = prepared.as_decision_payload()
    if prepared.decision_digest != digest_canonical(decision):
        _raise(
            PREPARED_CANARY_RECORD_INVALID,
            "prepared canary decision digest differs",
        )
    unsigned: dict[str, object] = {
        "schema_version": PREPARED_CANARY_RECORD_SCHEMA,
        "decision": decision,
        "decision_digest": prepared.decision_digest,
        "observations": dict(prepared.observations),
        "qualification_evidence": (
            None
            if prepared.qualification_evidence is None
            else dict(prepared.qualification_evidence)
        ),
    }
    record_digest = digest_canonical(unsigned)
    if prepared.record_digest not in {None, record_digest}:
        _raise(
            PREPARED_CANARY_RECORD_INVALID,
            "prepared canary record digest differs",
        )
    return {**unsigned, "record_digest": record_digest}


def prepared_canary_from_record(
    value: Mapping[str, object],
) -> PreparedCanary:
    """Validate and reconstruct a cross-process PreparedCanary artefact."""

    record = dict(value)
    expected_fields = {
        "decision",
        "decision_digest",
        "observations",
        "qualification_evidence",
        "record_digest",
        "schema_version",
    }
    if set(record) != expected_fields:
        _raise(
            PREPARED_CANARY_RECORD_INVALID,
            "prepared canary record fields differ",
        )
    supplied_record_digest = record.pop("record_digest")
    if (
        record.get("schema_version") != PREPARED_CANARY_RECORD_SCHEMA
        or supplied_record_digest != digest_canonical(record)
    ):
        _raise(
            PREPARED_CANARY_RECORD_INVALID,
            "prepared canary record digest differs",
        )
    decision = record.get("decision")
    observations = record.get("observations")
    qualification = record.get("qualification_evidence")
    if (
        not isinstance(decision, dict)
        or not isinstance(observations, dict)
        or (qualification is not None and not isinstance(qualification, dict))
    ):
        _raise(
            PREPARED_CANARY_RECORD_INVALID,
            "prepared canary record content differs",
        )
    decision_digest = record.get("decision_digest")
    if decision_digest != digest_canonical(decision):
        _raise(
            PREPARED_CANARY_RECORD_INVALID,
            "prepared canary decision digest differs",
        )
    expected_decision_fields = {
        "candidate_identity",
        "exact_head",
        "non_effects",
        "plan_identity",
        "qualification_identity",
        "retry_exclusion_identity",
        "runtime_identity",
        "safety_state",
    }
    if set(decision) != expected_decision_fields:
        _raise(
            PREPARED_CANARY_RECORD_INVALID,
            "prepared canary decision fields differ",
        )
    mapping_fields = (
        "candidate_identity",
        "plan_identity",
        "retry_exclusion_identity",
        "runtime_identity",
        "safety_state",
    )
    if (
        not isinstance(decision.get("exact_head"), str)
        or not isinstance(decision.get("non_effects"), list)
        or not all(
            isinstance(item, str)
            for item in decision.get("non_effects", [])
        )
        or not all(isinstance(decision.get(field), dict) for field in mapping_fields)
    ):
        _raise(
            PREPARED_CANARY_RECORD_INVALID,
            "prepared canary decision content differs",
        )
    qualification_identity = decision.get("qualification_identity")
    if qualification_identity is not None and not isinstance(
        qualification_identity, dict
    ):
        _raise(
            PREPARED_CANARY_RECORD_INVALID,
            "prepared canary qualification identity differs",
        )
    if _qualification_identity(qualification) != qualification_identity:
        _raise(
            PREPARED_CANARY_RECORD_INVALID,
            "prepared canary qualification identity differs",
        )
    prepared = PreparedCanary(
        exact_head=str(decision["exact_head"]),
        candidate_identity=dict(decision["candidate_identity"]),  # type: ignore[arg-type]
        safety_state=dict(decision["safety_state"]),  # type: ignore[arg-type]
        plan_identity=dict(decision["plan_identity"]),  # type: ignore[arg-type]
        retry_exclusion_identity=dict(  # type: ignore[arg-type]
            decision["retry_exclusion_identity"]
        ),
        runtime_identity=dict(decision["runtime_identity"]),  # type: ignore[arg-type]
        non_effects=tuple(decision["non_effects"]),  # type: ignore[arg-type]
        decision_digest=str(decision_digest),
        observations=dict(observations),
        qualification_evidence=(
            None if qualification is None else dict(qualification)
        ),
        record_digest=str(supplied_record_digest),
    )
    if prepared.as_decision_payload() != decision:
        _raise(
            PREPARED_CANARY_RECORD_INVALID,
            "prepared canary decision payload differs",
        )
    return prepared


def consume_prepared_canary(
    prepared: PreparedCanary | None,
    *,
    expected: PreparedCanary,
) -> PreparedCanary:
    """The only canary comparison: the shared decision digest must match."""

    if prepared is None:
        _raise(PREPARED_CANARY_ABSENT, "prepared canary is absent")
    if prepared.decision_digest != expected.decision_digest:
        _raise(
            PREPARED_CANARY_DIGEST_DRIFT,
            "prepared canary decision digest differs",
        )
    if prepared.as_decision_payload() != expected.as_decision_payload():
        _raise(
            PREPARED_CANARY_DIGEST_DRIFT,
            "prepared canary decision payload differs",
        )
    return prepared


def eligible_unused_candidate_rows(
    rows: Sequence[tuple[object, ...]],
    *,
    forbidden_event_ids: set[str],
    forbidden_seqs: set[int],
    floor: int,
) -> tuple[tuple[object, ...], ...]:
    """Keep only post-exhaustion QUEUED attempt-0 rows above the exclusion floor."""

    return tuple(
        row
        for row in rows
        if str(row[0]) not in forbidden_event_ids
        and int(row[1]) not in forbidden_seqs
        and int(row[1]) > floor
    )


def _forbidden_identities(
    store: Path | None,
    plan: Mapping[str, object],
) -> tuple[set[str], set[int]]:
    """Durable and plan retry-forbidden identities. Consumption is resume, not retry."""

    ids: set[str] = set()
    seqs: set[int] = set(_op()._RETRY_FORBIDDEN_LEDGER_SEQS)
    retry_events = plan.get("retry_forbidden_events")
    if isinstance(retry_events, list):
        for item in retry_events:
            if not isinstance(item, dict):
                continue
            event_id = item.get("event_id")
            ledger_seq = item.get("ledger_seq")
            if isinstance(event_id, str):
                ids.add(event_id)
            if isinstance(ledger_seq, int) and not isinstance(ledger_seq, bool):
                seqs.add(ledger_seq)
    if store is None:
        return ids, seqs
    connection = sqlite3.connect(f"{store.absolute().as_uri()}?mode=ro", uri=True)
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "issue_790_graphiti_retry_exclusions" in tables:
            for event_id, ledger_seq in connection.execute(
                "SELECT event_id, ledger_seq FROM issue_790_graphiti_retry_exclusions"
            ):
                ids.add(str(event_id))
                seqs.add(int(ledger_seq))
    finally:
        connection.close()
    return ids, seqs


def unused_queued_attempt_zero_candidates(
    store: Path,
    plan: Mapping[str, object],
) -> tuple[tuple[str, int], ...]:
    """Current unused QUEUED attempt-0 identities, highest ledger first."""

    forbidden_ids, forbidden_seqs = _forbidden_identities(store, plan)
    floor = max(_op()._RETRY_FORBIDDEN_LEDGER_SEQS)
    connection = sqlite3.connect(f"{store.absolute().as_uri()}?mode=ro", uri=True)
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "unpublished_graphiti_revision_events" not in tables:
            return ()
        rows = connection.execute(
            "SELECT event_id,ledger_seq,state,attempt_count,provider_dispatched "
            "FROM unpublished_graphiti_revision_events "
            "WHERE state='QUEUED' AND attempt_count=0 AND provider_dispatched=0 "
            "ORDER BY ledger_seq DESC LIMIT 40"
        ).fetchall()
    finally:
        connection.close()
    eligible = eligible_unused_candidate_rows(
        rows,
        forbidden_event_ids=forbidden_ids,
        forbidden_seqs=forbidden_seqs,
        floor=floor,
    )
    return tuple((str(row[0]), int(row[1])) for row in eligible)


def _event_is_untouched_attempt_zero(
    store: Path,
    *,
    event_id: str,
    ledger_seq: int,
) -> bool | None:
    connection = sqlite3.connect(f"{store.absolute().as_uri()}?mode=ro", uri=True)
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "unpublished_graphiti_revision_events" not in tables:
            return None
        row = connection.execute(
            "SELECT state,attempt_count,provider_dispatched "
            "FROM unpublished_graphiti_revision_events "
            "WHERE event_id=? AND ledger_seq=?",
            (event_id, ledger_seq),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return None
    return str(row[0]) == "QUEUED" and int(row[1]) == 0 and not bool(row[2])


def _qualification_is_current_unused(
    store: Path | None,
    *,
    event_id: str,
    ledger_seq: int,
) -> bool:
    if store is None:
        return True
    untouched = _event_is_untouched_attempt_zero(
        store, event_id=event_id, ledger_seq=ledger_seq
    )
    return untouched is not False


def _spent_or_retry_forbidden(
    store: Path | None,
    plan: Mapping[str, object],
    *,
    event_id: str,
    ledger_seq: int,
) -> bool:
    forbidden_ids, forbidden_seqs = _forbidden_identities(store, plan)
    if event_id in forbidden_ids or ledger_seq in forbidden_seqs:
        return True
    if store is None:
        return False
    untouched = _event_is_untouched_attempt_zero(
        store, event_id=event_id, ledger_seq=ledger_seq
    )
    if (
        event_id == CANDIDATE_EVENT_ID
        and ledger_seq == CANDIDATE_LEDGER_SEQ
        and untouched is not True
    ):
        return True
    if untouched is False and not _canary_flags(
        store, event_id=event_id, ledger_seq=ledger_seq
    )["consumption_present"]:
        return True
    return False


def _unmatched_consumption_identity(store: Path) -> tuple[str, int] | None:
    connection = sqlite3.connect(f"{store.absolute().as_uri()}?mode=ro", uri=True)
    try:
        return unmatched_bounded_canary_consumption(connection)
    finally:
        connection.close()


def _reject_unmatched_plan_consumption(
    store: Path | None, *, event_id: str | None, ledger_seq: int | None
) -> None:
    """Fail-closed when a different event already consumed the bound plan."""

    if store is None or event_id is None or ledger_seq is None:
        return
    unmatched = _unmatched_consumption_identity(store)
    if unmatched is None or unmatched == (event_id, ledger_seq):
        return
    _raise(
        BOUNDED_CANARY_AUTHORITY_CONSUMED,
        "bounded canary authority is already consumed",
    )


def _candidate_from_plan(
    plan: Mapping[str, object],
    *,
    event_id: str | None,
    ledger_seq: int | None,
    role: PrepareRole,
    store: Path | None = None,
) -> tuple[str | None, int | None]:
    selected = _op()._step18_candidate_qualification(plan)
    selected_live: tuple[str, int] | None = None
    if selected is not None:
        selected_tuple = (str(selected["event_id"]), int(selected["ledger_seq"]))
        if _qualification_is_current_unused(
            store, event_id=selected_tuple[0], ledger_seq=selected_tuple[1]
        ):
            selected_live = selected_tuple
    live = unused_queued_attempt_zero_candidates(store, plan)[:1] if store is not None else ()
    live_bind = live[0] if live else None
    bound = live_bind or selected_live

    if event_id is not None and ledger_seq is not None:
        requested = (event_id, ledger_seq)
        if not event_id.startswith("sha256:"):
            return requested
        if _spent_or_retry_forbidden(store, plan, event_id=event_id, ledger_seq=ledger_seq):
            _raise("RETRY_FORBIDDEN_TARGET", "bounded canary targeted a retained failure")
        if live_bind is not None and requested != live_bind:
            if store is not None and _unmatched_consumption_identity(store) == requested:
                _reject_unmatched_plan_consumption(
                    store, event_id=event_id, ledger_seq=ledger_seq
                )
                return requested
            if (
                store is not None
                and _event_is_untouched_attempt_zero(
                    store, event_id=event_id, ledger_seq=ledger_seq
                )
                is False
            ):
                _raise(
                    "RETRY_FORBIDDEN_TARGET",
                    "bounded canary targeted a retained failure",
                )
            _raise("CANDIDATE_IDENTITY", "bounded canary candidate identity differs")
        if bound is not None and requested != bound:
            _raise("CANDIDATE_IDENTITY", "bounded canary candidate identity differs")
        _reject_unmatched_plan_consumption(
            store, event_id=event_id, ledger_seq=ledger_seq
        )
        return requested

    if bound is None:
        if role == "apply":
            return None, None
        if store is not None:
            _raise("CANDIDATE_NOT_FRESH", "bounded canary event is not untouched")
        return CANDIDATE_EVENT_ID, CANDIDATE_LEDGER_SEQ
    if event_id is not None and event_id != bound[0]:
        _raise("CANDIDATE_IDENTITY", "bounded canary candidate identity differs")
    if ledger_seq is not None and ledger_seq != bound[1]:
        _raise("CANDIDATE_IDENTITY", "bounded canary candidate identity differs")
    _reject_unmatched_plan_consumption(store, event_id=bound[0], ledger_seq=bound[1])
    return bound


def _row_claim_present(row: Mapping[str, object]) -> bool:
    return (
        row.get("claim_owner") is not None or row.get("claim_expires_at") is not None
    )


def _canary_flags(store: Path, *, event_id: str, ledger_seq: int) -> dict[str, bool]:
    flags = {
        "consumption_present": False,
        "outcome_present": False,
        "receipt_present": False,
    }
    connection = sqlite3.connect(f"{store.absolute().as_uri()}?mode=ro", uri=True)
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "issue_790_bounded_canary_consumptions" in tables:
            flags["consumption_present"] = (
                connection.execute(
                    "SELECT 1 FROM issue_790_bounded_canary_consumptions "
                    "WHERE event_id=? OR ledger_seq=? LIMIT 1",
                    (event_id, ledger_seq),
                ).fetchone()
                is not None
            )
        if "issue_790_bounded_canary_outcomes" in tables:
            flags["outcome_present"] = (
                connection.execute(
                    "SELECT 1 FROM issue_790_bounded_canary_outcomes "
                    "WHERE event_id=? OR ledger_seq=? LIMIT 1",
                    (event_id, ledger_seq),
                ).fetchone()
                is not None
            )
            flags["receipt_present"] = flags["outcome_present"]
    finally:
        connection.close()
    return flags


def prepare_issue_790_canary(
    *,
    store: Path,
    plan: Mapping[str, object],
    observed_at: datetime,
    exact_head: str,
    event_id: str | None = None,
    ledger_seq: int | None = None,
    proving_store: Path | None = None,
    role: PrepareRole = "canary",
) -> PreparedCanary:
    """Read-only A/B prepare. Does not write Mini or rehearsal stores."""

    op = _op()
    if not exact_head or not isinstance(exact_head, str):
        _raise("EXACT_HEAD_ABSENT", "exact head is absent")
    try:
        store = op._canonical_existing_file(store, field="source unpublished store")
    except Issue790DispositionError as exc:
        raise PreparedCanaryError(str(exc), failure_code="STORE_ABSENT") from exc

    bound_event_id, bound_ledger_seq = _candidate_from_plan(
        plan, event_id=event_id, ledger_seq=ledger_seq, role=role, store=store
    )
    sequence = plan.get("sequence") if isinstance(plan.get("sequence"), dict) else {}
    ordinal = sequence.get("sequence_ordinal")
    if bound_ledger_seq is not None and bound_ledger_seq in op._RETRY_FORBIDDEN_LEDGER_SEQS:
        _raise("RETRY_FORBIDDEN_TARGET", "bounded canary targeted a retained failure")
    if bound_event_id is not None and not bound_event_id.startswith("sha256:"):
        _raise("EVENT_IDENTITY_INVALID", "bounded canary event identity is invalid")
    try:
        if proving_store is not None:
            proving_store = op._canonical_existing_file(
                proving_store,
                field="source proving store",
            )
            op.assert_issue_790_paths_disjoint(store, proving_store)
    except Issue790DispositionError as exc:
        message = str(exc)
        code = "PATHS_ALIAS" if "alias" in message else "STORE_ABSENT"
        raise PreparedCanaryError(message, failure_code=code) from exc

    retry_events = plan.get("retry_forbidden_events")
    if not isinstance(retry_events, list) or not retry_events:
        _raise("RETRY_FORBIDDEN_SAFETY_STATE", "retry-forbidden events are absent")
    try:
        live_retry = op._require_retry_events_unchanged(store, plan)
    except Issue790DispositionError as exc:
        raise PreparedCanaryError(
            str(exc),
            failure_code="RETRY_FORBIDDEN_SAFETY_STATE",
        ) from exc
    except RetryForbiddenSafetyError as exc:
        raise PreparedCanaryError(
            str(exc),
            failure_code="RETRY_FORBIDDEN_SAFETY_STATE",
        ) from exc

    safety_states = [
        asdict(RetryForbiddenSafetyState.from_mapping(item)) for item in live_retry
    ]
    retry_claim_present = any(_row_claim_present(item) for item in live_retry)
    retry_ids = [str(item["event_id"]) for item in live_retry]
    observations = {
        "retry_forbidden": [
            {
                "available_at": item.get("available_at"),
                "ledger_seq": item.get("ledger_seq"),
            }
            for item in live_retry
        ]
    }

    candidate_row: dict[str, object] | None = None
    manifest_row = None
    if bound_event_id is not None and bound_ledger_seq is not None:
        connection = sqlite3.connect(f"{store.absolute().as_uri()}?mode=ro", uri=True)
        try:
            has_claims = retry_forbidden_has_claim_columns(connection)
            row = connection.execute(
                retry_forbidden_live_select(has_claims=has_claims)
                + " WHERE event_id=? AND ledger_seq=?",
                (bound_event_id, bound_ledger_seq),
            ).fetchone()
            if row is not None:
                candidate_row = retry_forbidden_live_snapshot(row, has_claims=has_claims)
            manifest_row = connection.execute(
                "SELECT manifest_digest,state,attempt_count,provider_dispatched,"
                "claim_owner,claim_expires_at FROM unpublished_graphiti_revision_events "
                "WHERE event_id=? AND ledger_seq=?",
                (bound_event_id, bound_ledger_seq),
            ).fetchone()
        finally:
            connection.close()

    flags = (
        _canary_flags(store, event_id=bound_event_id, ledger_seq=bound_ledger_seq)
        if bound_event_id is not None and bound_ledger_seq is not None
        else {
            "consumption_present": False,
            "outcome_present": False,
            "receipt_present": False,
        }
    )
    require_candidate_row = (
        role in {"preflight", "canary"}
        and bound_event_id is not None
        and bound_ledger_seq is not None
    )
    if require_candidate_row and manifest_row is None:
        _raise("CANDIDATE_NOT_FRESH", "bounded canary event identity is absent")
    candidate_claim_present = False
    candidate_state = None
    candidate_attempt = None
    candidate_dispatched = None
    manifest_digest = None
    if manifest_row is not None:
        manifest_digest = str(manifest_row[0])
        candidate_state = str(manifest_row[1])
        candidate_attempt = int(manifest_row[2])
        candidate_dispatched = bool(manifest_row[3])
        candidate_claim_present = manifest_row[4] is not None or manifest_row[5] is not None
        resume = flags["consumption_present"]
        if require_candidate_row and not resume and (
            candidate_state != "QUEUED"
            or candidate_attempt != 0
            or candidate_dispatched is not False
            or candidate_claim_present
        ):
            _raise("CANDIDATE_NOT_FRESH", "bounded canary event is not untouched")
    if candidate_row is not None:
        observations["candidate_available_at"] = candidate_row.get("available_at")

    qualification: dict[str, object] | None = None
    if require_candidate_row and proving_store is not None and not flags["consumption_present"]:
        try:
            qualification = op._qualify_issue_790_event(
                proving_store=proving_store,
                unpublished_store=store,
                event_id=bound_event_id,
                ledger_seq=bound_ledger_seq,
                observed_at=observed_at,
                plan=plan,
            )
        except (
            Issue790DispositionError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
            sqlite3.Error,
        ) as exc:
            raise PreparedCanaryError(
                f"bounded canary provider-free preflight failed: {exc}",
                failure_code="CANDIDATE_NOT_FRESH",
            ) from exc
        if qualification.get("event_manifest_digest") != manifest_digest:
            _raise("CANDIDATE_IDENTITY", "bounded canary candidate manifest differs")

    non_effects = plan.get("non_effects")
    if not isinstance(non_effects, list) or not all(
        isinstance(item, str) for item in non_effects
    ):
        non_effects = []
    candidate_identity = {
        "event_id": bound_event_id,
        "event_manifest_digest": manifest_digest,
        "ledger_seq": bound_ledger_seq,
    }
    safety_state = {
        "candidate_attempt_count": candidate_attempt,
        "candidate_claim_present": candidate_claim_present,
        "candidate_provider_dispatched": candidate_dispatched,
        "candidate_state": candidate_state,
        "consumption_present": flags["consumption_present"],
        "outcome_present": flags["outcome_present"],
        "receipt_present": flags["receipt_present"],
        "retry_claim_present": retry_claim_present,
        "retry_safety_states": safety_states,
    }
    plan_identity = {
        "candidate_event_id": bound_event_id,
        "candidate_ledger_seq": bound_ledger_seq,
        "pending_digest": (
            ISSUE_790_STEP22_PENDING_DIGEST
            if ordinal == 22
            else str(plan.get("canonical_digest") or "")
        ),
        "tracked_plan": TRACKED_PLAN_NAME,
    }
    retry_exclusion_identity = {
        "retry_forbidden_event_ids": retry_ids,
        "retry_safety_states": safety_states,
    }
    runtime_identity = {
        "call_shape_policy_digest": sequence.get("call_shape_policy_digest"),
        "event_binding": "EXPLICIT_QUEUED_ATTEMPT_ZERO_EVENT",
        "fallback_mode": "DISABLED_BEFORE_PROVIDER_DISPATCH",
        "projection_policy_digest": sequence.get(
            "projection_policy_digest", PROJECTION_POLICY_DIGEST
        ),
    }
    payload = _decision_payload(
        exact_head=exact_head,
        candidate_identity=candidate_identity,
        safety_state=safety_state,
        plan_identity=plan_identity,
        retry_exclusion_identity=retry_exclusion_identity,
        runtime_identity=runtime_identity,
        non_effects=tuple(non_effects),
        qualification_identity=_qualification_identity(qualification),
    )
    return PreparedCanary(
        exact_head=exact_head,
        candidate_identity=candidate_identity,
        safety_state=safety_state,
        plan_identity=plan_identity,
        retry_exclusion_identity=retry_exclusion_identity,
        runtime_identity=runtime_identity,
        non_effects=tuple(non_effects),
        decision_digest=digest_canonical(payload),
        observations=observations,
        qualification_evidence=qualification,
    )


__all__ = [
    "BOUNDED_CANARY_AUTHORITY_CONSUMED",
    "CANDIDATE_EVENT_ID",
    "CANDIDATE_LEDGER_SEQ",
    "FAIL_BRANCH_INVENTORY",
    "FIELD_CLASSIFICATION",
    "LIVE_ONLY_PREDISPATCH_GATES",
    "PREPARED_CANARY_ABSENT",
    "PREPARED_CANARY_DIGEST_DRIFT",
    "PREPARED_CANARY_RECORD_INVALID",
    "PREPARED_CANARY_RECORD_SCHEMA",
    "PreparedCanary",
    "PreparedCanaryError",
    "consume_prepared_canary",
    "eligible_unused_candidate_rows",
    "prepared_canary_from_record",
    "prepared_canary_record",
    "prepare_issue_790_canary",
    "unused_queued_attempt_zero_candidates",
]
