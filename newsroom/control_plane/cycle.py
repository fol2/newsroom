"""Governed unpublished cycle: Signal → Lead → Hypothesis → Candidate → Evidence → write.

Graphiti corpus ingest is independent of CONT writes (GING-001).
"""

from __future__ import annotations

import json
import math
import sqlite3
import uuid
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ContextManager, Final, Protocol, TypedDict, cast

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
    validate_sha256_digest,
)
from newsroom.authority.types import require_token
from newsroom.control_plane.admission import (
    DeterministicWriteAdmission,
    WriteAdmissionDecision,
    select_write_ready,
    validate_admission_binding,
)
from newsroom.control_plane.corpus import (
    CorpusIngestUnit,
    EffectivePullFirstSeen,
    merge_durable_revisions,
    revisions_from,
    unique_chunk_units,
    units_from,
)
from newsroom.control_plane.drafting import DraftOutcomeRecord
from newsroom.control_plane.editorial import (
    GroupedObservation,
    StoryCandidateRecord,
    form_candidates,
)
from newsroom.control_plane.evidence import EvidencePackage, retained_package_for
from newsroom.control_plane.governed_context import GovernedContext
from newsroom.control_plane.graphiti import (
    GRAPHITI_RESULT_STAGE_CYCLE_RESULT_BINDING,
    GRAPHITI_RESULT_STAGE_UNCLASSIFIED,
    GovernedRealGraphitiPort,
    GraphitiCycleResult,
    GraphitiPort,
    GraphitiResultStageError,
)
from newsroom.control_plane.graphiti_events import (
    ConfigurationGraphitiEventFailure,
    GraphitiDispatchGate,
    GraphitiDispatchResult,
    GraphitiEventQueue,
    GraphitiProcessResult,
    GraphitiRevisionEvent,
    SystemicGraphitiEventFailure,
    ensure_graphiti_event_schema,
    graphiti_unit_binding_reason,
)
from newsroom.control_plane.items import parse_observation
from newsroom.control_plane.issue_790_canary import (
    Issue790CanaryRepository,
    graphiti_retry_excluded,
)
from newsroom.control_plane.model_usage import (
    InvocationAllocation,
    InvocationEfficiencyPolicy,
    InvocationTerminal,
    ModelUsageAdmissionError,
    ModelUsageService,
    UsageComponents,
    UsageStatus,
    WorkEnvelope,
    WorkloadClass,
)
from newsroom.control_plane.paths import (
    require_canonical_proving_store,
    require_canonical_unpublished_store,
)
from newsroom.control_plane.sqlite_profile import apply_control_plane_sqlite_profile
from newsroom.control_plane.store import (
    GraphitiSpendCeilingExceeded,
    append_ledger,
    claim_graphiti_attempt,
    clear_graphiti_failure,
    complete_writer_provider_attempt,
    connect,
    emit_effective_revision_landed,
    graphiti_coverage,
    graphiti_failure_state,
    has_candidate,
    has_graphiti_ingest,
    insert_graphiti_attempt_receipt,
    insert_graphiti_ingest,
    insert_payload,
    is_exact_no_embedding_call,
    list_landed_revisions,
    list_remapped_ingest_effects,
    next_graphiti_attempt_number,
    reconcile_graphiti_spend,
    record_graphiti_coverage,
    record_graphiti_failure,
    release_graphiti_attempt_claim,
    reserve_graphiti_spend,
    reserve_write_candidate_attempt,
    reserve_writer_provider_attempt,
    retain_draft_outcome,
    retain_graphiti_authority_records,
    retain_write_admission_decision,
    retain_write_selection,
)
from newsroom.control_plane.surface import UnpublishedSurfacePayload
from newsroom.control_plane.veto import VetoError, assert_private_store
from newsroom.control_plane.writer import (
    WriterCopy,
    WriterDispatchError,
    WriterInvocationManifest,
    WriterPort,
    WriterRoute,
    WriterValidatorResult,
    require_permitted_context,
    validate_writer_copy,
)
from newsroom.effective_revision import (
    EffectiveRevisionIdentity,
    EffectiveRevisionIdentityResolver,
    backfill_missing_first_seen,
    create_effective_revision_schema,
)
from newsroom.graphiti_adapter.cli_process import (
    validated_process_exit_diagnostic,
    validated_timeout_diagnostics,
    validated_transport_qualification,
)
from newsroom.graphiti_adapter.contracts import GRAPHITI_PROMPT_COMPONENT
from newsroom.graphiti_adapter.evaluation_packet import (
    GRAPHITI_CHAT_FALLBACK,
    GRAPHITI_CHAT_MODEL,
    GRAPHITI_CORE_RELEASE,
    GRAPHITI_EMBEDDING_MODEL,
    GRAPHITI_EVALUATION_DESTINATION_TOKENS,
    GRAPHITI_EXTRACTION_TIMEOUT_MS,
    GRAPHITI_GENERATION_ID,
    GRAPHITI_WORKSPACE_GROUP,
    OD_011_CASH_CEILING_GBP,
    OPENROUTER_API,
)
from newsroom.graphiti_adapter.recovery_vocabulary import (
    GraphitiRecoveryClassification,
)
from newsroom.graphiti_adapter.usage_meter import (
    is_exact_predispatch_no_provider_call,
    summarise_graphiti_usage,
)
from newsroom.increment9.proving import (
    FORBIDDEN_STORE_MARKERS,
    GLOBAL_PROVING_GATES,
    assess_content,
)
from newsroom.increment9.rights import assess_rights

_PROVING_RUN_LATEST_ORDER = "rowid DESC"
_PROVING_RUN_EARLIEST_ORDER = "rowid ASC"
_PROVING_FENCE_TIMEOUT_SECONDS = 5.0
_RAW_HTTP_RETENTION: Final = timedelta(days=7)
GRAPHITI_UNIT_RESERVATION_GBP_MICROUNITS: Final[int] = 500_000
_GRAPHITI_RECOVERY_CLOSED_LEDGER_KIND: Final[str] = "GRAPHITI_EVALUATION_RECOVERY_CLOSED"
_CLOSED_MARKER_RECOVERIES: Final[
    frozenset[GraphitiRecoveryClassification]
] = frozenset(
    {
        GraphitiRecoveryClassification.RECOVERED_AMBIGUOUS,
        GraphitiRecoveryClassification.RECOVERED_PENDING_PROCESS_DEATH,
    }
)


class _ProvingFenceUnavailable(RuntimeError):
    """The provider boundary could not acquire a proving-writer fence."""


class _ProviderAttemptRecoveryAccounting(TypedDict):
    spend_id: str
    status: str
    retained_attempt_receipt: bool
    reconciled_again: bool
    accounting: dict[str, object] | None


class GraphitiAdmissionCycleAtom(Protocol):
    """Bounded admission work configured by the Hermes composition root."""

    def enqueue_complete_receipts(
        self, *, ingest_ids: tuple[str, ...] | None = None
    ) -> int: ...

    def drain(
        self,
        *,
        worker_id: str,
        limit: int = 100,
        ingest_ids: tuple[str, ...] | None = None,
    ) -> object: ...

    def reconcile_rights(
        self,
        *,
        limit: int = 100,
        ingest_ids: tuple[str, ...] | None = None,
    ) -> int: ...


GraphitiAdmissionFactory = Callable[
    [sqlite3.Connection], GraphitiAdmissionCycleAtom
]


@dataclass(frozen=True, slots=True)
class _DispatchAuthority:
    rights: dict[str, object]
    deadline: datetime
    owner_stop_check: Callable[[], None]


@dataclass(frozen=True, slots=True)
class CycleReport:
    cycle_id: str
    proving_run_id: str
    minted: int
    duplicate: int
    sources: int
    candidates: int
    ledger_digest: str
    writer_id: str
    graphiti: int = 0
    eligible: int = 0
    poll_observation_count: int = 0
    feed_snapshot_item_count: int = 0
    effective_pull_count: int = 0
    candidates_considered: int = 0
    write_ready: int = 0
    admission_hold: int = 0
    admission_reject: int = 0
    selected_write_ready: int = 0
    candidate_attempts: int = 0
    provider_dispatches: int = 0
    primary_dispatches: int = 0
    fallback_dispatches: int = 0
    draft_accepted: int = 0
    draft_hold: int = 0
    draft_reject: int = 0
    accepted_payload_count: int = 0
    writer_circuit_open: bool = False
    writer_circuit_open_reason: str = ""
    no_useful_output_circuit_open: bool = False
    no_useful_output_circuit_open_reason: str = ""
    candidate_budget_exhausted: bool = False
    provider_budget_exhausted: bool = False
    fallback_budget_exhausted: bool = False
    write_budget_exhausted: bool = False
    admission_reason_counts: tuple[tuple[str, int], ...] = ()
    draft_reason_counts: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class _WriteLoopResult:
    minted: int
    duplicate: int
    selected: int
    candidate_attempts: int
    provider_dispatches: int
    primary_dispatches: int
    fallback_dispatches: int
    draft_counts: tuple[tuple[str, int], ...]
    draft_reasons: tuple[tuple[str, int], ...]
    writer_circuit_open: bool
    writer_circuit_open_reason: str
    no_useful_output_circuit_open: bool
    no_useful_output_circuit_open_reason: str
    candidate_budget_exhausted: bool
    provider_budget_exhausted: bool
    fallback_budget_exhausted: bool
    write_budget_exhausted: bool


@dataclass(frozen=True, slots=True)
class _ProvingObservation:
    run_id: str
    source_id: str
    url: str
    fetched_at: str
    status_code: int
    body_digest: str
    body: bytes
    rights_authority_run_id: str
    rights_gate_id: str
    rights_gate_reason: str
    item_count: int


def _now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("retained UTC timestamp lacks timezone")
    return parsed.astimezone(UTC)


def assert_no_owner_emergency_stop(proving_store: str) -> None:
    """Fail closed unless the latest proving authority retains the stop gate PASS."""

    with owner_emergency_stop_fence(proving_store):
        pass


def _assert_owner_emergency_stop_clear(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "WITH latest AS (SELECT run_id FROM proving_runs "
        f"ORDER BY {_PROVING_RUN_LATEST_ORDER} LIMIT 1) "
        "SELECT g.status FROM latest "
        "JOIN proving_gates g ON g.run_id=latest.run_id "
        "AND g.gate_id='NO_ACTIVE_HUMAN_EMERGENCY_STOP'"
    ).fetchone()
    if row != ("PASS",):
        raise VetoError("owner emergency stop is active or unproved")


@contextmanager
def owner_emergency_stop_fence(proving_store: str) -> Iterator[None]:
    """Hold the owner-stop authority stable across one provider dispatch."""

    timeout_ms = max(1, int(_PROVING_FENCE_TIMEOUT_SECONDS * 1_000))
    connection = sqlite3.connect(
        proving_store, timeout=_PROVING_FENCE_TIMEOUT_SECONDS
    )
    apply_control_plane_sqlite_profile(
        connection, wal=None, busy_timeout_ms=timeout_ms
    )
    try:
        try:
            connection.execute("BEGIN IMMEDIATE")
            _assert_owner_emergency_stop_clear(connection)
        except sqlite3.OperationalError as exc:
            raise VetoError("owner emergency stop authority is unavailable") from exc
        yield
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()


def _dispatch_valid_until(evaluated_at: datetime) -> str:
    return _utc_text(
        evaluated_at + timedelta(milliseconds=GRAPHITI_EXTRACTION_TIMEOUT_MS)
    )


def _validated_producer_failure(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("graphiti producer failure is invalid")
    try:
        return require_token(value, field="graphiti producer failure")
    except ValueError as exc:
        raise ValueError("graphiti producer failure is invalid") from exc


def _validate_chat_invocation_diagnostics(
    invocations: tuple[dict[str, object], ...],
) -> None:
    """Reject unvalidated diagnostic leaves before durable propagation."""

    for invocation in invocations:
        if not isinstance(invocation, dict):
            raise ValueError("graphiti chat invocation is invalid")
        if "transport_diagnostic" in invocation:
            validated_timeout_diagnostics([invocation["transport_diagnostic"]])
        if "transport_qualification" in invocation:
            validated_transport_qualification(invocation["transport_qualification"])
        if "process_exit_diagnostic" in invocation:
            validated_process_exit_diagnostic(invocation["process_exit_diagnostic"])


def _canonical_digest_or_none(value: object) -> str | None:
    try:
        return digest_bytes(canonical_json_bytes(value))
    except (TypeError, ValueError, UnicodeError):
        return None


def _validated_raw_output_digest_or_none(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    unsigned = dict(value)
    supplied = unsigned.pop("raw_output_digest", None)
    try:
        calculated = digest_bytes(canonical_json_bytes(unsigned))
    except (TypeError, ValueError, UnicodeError):
        return None
    return supplied if isinstance(supplied, str) and supplied == calculated else None


def _rejected_result_metadata(
    result: GraphitiCycleResult | None,
) -> dict[str, object]:
    """Describe rejected provider material without retaining its raw content."""

    if result is None:
        return {
            "returned_raw_receipt_digest": None,
            "returned_validated_raw_digest": None,
            "chat_invocation_count": 0,
            "chat_invocations_digest": None,
            "embedding_usage_digest": None,
            "chat_invocations": [],
            "embedding_usage": None,
            "token_usage": None,
        }
    invocations = list(result.chat_invocations)
    return {
        "returned_raw_receipt_digest": _canonical_digest_or_none(
            result.raw_receipt
        ),
        "returned_validated_raw_digest": _validated_raw_output_digest_or_none(
            result.raw_receipt
        ),
        "chat_invocation_count": len(invocations),
        "chat_invocations_digest": _canonical_digest_or_none(invocations),
        "embedding_usage_digest": _canonical_digest_or_none(
            result.embedding_usage
        ),
        "chat_invocations": [],
        "embedding_usage": None,
        "token_usage": None,
    }


def _rejected_provider_attempt_number(
    result: GraphitiCycleResult | None,
) -> int | None:
    if result is None:
        return None
    value = result.provider_attempt_number
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
        else None
    )


def _bind_result(
    unit: CorpusIngestUnit,
    result: GraphitiCycleResult,
    *,
    authority_connection: sqlite3.Connection | None = None,
) -> GraphitiCycleResult:
    if (result.ingest_id, result.source_id, result.item_key) != (
        unit.ingest_id,
        unit.source_id,
        unit.item_key,
    ):
        raise ValueError("graphiti result identity differs from ingest unit")
    temporal = unit.temporal()
    if result.attempt_number != unit.attempt_number:
        raise ValueError("graphiti result attempt differs from ingest unit")
    if not 1 <= result.provider_attempt_number <= unit.attempt_number:
        raise ValueError("graphiti provider attempt is outside the ingest retry history")
    if result.generation_id != GRAPHITI_GENERATION_ID:
        raise ValueError("graphiti result generation differs from authorised generation")
    if result.workspace_group != GRAPHITI_WORKSPACE_GROUP:
        raise ValueError("graphiti result workspace differs from authorised generation")
    if (result.temporal_basis, result.reference_time) != (
        temporal.basis,
        temporal.reference_time.to_text(),
    ):
        raise ValueError("graphiti result temporal mapping differs from ingest unit")
    if result.episode_uuid != unit.ingest_id:
        raise ValueError("graphiti result episode UUID differs from ingest identity")
    if result.predecessor_episode_uuid != unit.predecessor_ingest_id:
        raise ValueError("graphiti result predecessor differs from ordered corpus chunk")
    raw = result.raw_receipt
    if not isinstance(raw, dict):
        raise ValueError("graphiti result needs a retained raw attempt receipt")
    raw_value = dict(raw)
    supplied_digest = raw_value.pop("raw_output_digest", None)
    calculated_digest = digest_bytes(canonical_json_bytes(raw_value))
    if supplied_digest != calculated_digest or result.receipt_digest != calculated_digest:
        raise ValueError("graphiti raw receipt digest differs from canonical content")
    if "timeout_diagnostics" in raw:
        validated_timeout_diagnostics(raw["timeout_diagnostics"])
    if "producer_failure" in raw:
        _validated_producer_failure(raw["producer_failure"])
    _validate_chat_invocation_diagnostics(result.chat_invocations)
    if (
        raw.get("generation_id") != GRAPHITI_GENERATION_ID
        or raw.get("episode_uuid") != unit.ingest_id
        or raw.get("temporal_basis") != temporal.basis
        or raw.get("reference_time") != temporal.reference_time.to_text()
        or raw.get("attempt_number") != unit.attempt_number
        or raw.get("provider_attempt_number") != result.provider_attempt_number
        or raw.get("predecessor_episode_uuid") != unit.predecessor_ingest_id
        or raw.get("framework") != result.framework
        or raw.get("chat") != result.chat
        or raw.get("chat_fallback") != result.chat_fallback
        or raw.get("embedding") != result.embedding
        or raw.get("prompt_version") != result.prompt_version
        or raw.get("usage_basis") != result.usage_basis
    ):
        raise ValueError("graphiti raw receipt binding differs from ingest unit")
    passages = raw.get("passages")
    if not isinstance(passages, list) or len(passages) != 1:
        raise ValueError("graphiti result needs exact single-passage provenance")
    passage = passages[0]
    expected_text = " ".join(unit.episode_body.split())
    expected_bytes = expected_text.encode("utf-8")
    expected_digest = digest_bytes(expected_bytes)
    if not isinstance(passage, dict) or (
        passage.get("byte_offset") != 0
        or passage.get("byte_length") != len(expected_text.encode("utf-8"))
        or passage.get("blob_digest") != expected_digest
        or passage.get("text_digest") != expected_digest
    ):
        raise ValueError("graphiti passage provenance differs from ingest bytes")
    if unit.authority is not None:
        if passage.get("admission_id") != unit.authority.admission_id:
            raise ValueError("graphiti passage admission differs from retained records")
        retained_access = passage.get("access_decision_id")
        if retained_access != unit.authority.access_decision_id:
            retained = None
            if authority_connection is not None and isinstance(retained_access, str):
                retained = authority_connection.execute(
                    """
                    SELECT record_digest, record_json
                    FROM unpublished_graphiti_authority_records
                    WHERE record_id=? AND record_type='OBJECT_ACCESS_DECISION'
                    """,
                    (retained_access,),
                ).fetchone()
            current_access = next(
                (
                    item
                    for item in unit.authority.records
                    if item.get("record_type") == "OBJECT_ACCESS_DECISION"
                ),
                None,
            )
            if retained is None or current_access is None:
                raise ValueError(
                    "graphiti passage access decision is neither current nor retained"
                )
            try:
                retained_record = json.loads(str(retained[1]))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "retained Graphiti access decision is malformed"
                ) from exc
            if (
                not isinstance(retained_record, dict)
                or digest_bytes(canonical_json_bytes(retained_record)) != str(retained[0])
                or retained_record.get("record_id") != retained_access
                or retained_record.get("record_type") != "OBJECT_ACCESS_DECISION"
                or retained_record.get("revision_id") != unit.authority.revision_id
                or retained_record.get("decision") != "ALLOW"
                or retained_record.get("principal_id") != "newsroom.control-plane"
                or retained_record.get("purpose") != "graphiti.corpus-ingest"
                or retained_record.get("rights_gate_status") != "PASS"
                or retained_record.get("rights_gate_id")
                != current_access.get("rights_gate_id")
            ):
                raise ValueError(
                    "retained Graphiti access decision does not bind this revision"
                )
    if tuple(cast(tuple[object, ...], raw.get("proposals", ()))) != result.proposals:
        raise ValueError("graphiti proposal receipt differs from bound raw receipt")
    if result.proposal_count != len(result.proposals):
        raise ValueError("graphiti proposal count differs from retained proposals")
    if (
        tuple(cast(tuple[object, ...], raw.get("entities", ()))) != result.entities
        or tuple(cast(tuple[object, ...], raw.get("relations", ()))) != result.relations
        or tuple(cast(tuple[object, ...], raw.get("passages", ()))) != result.passages
        or tuple(cast(tuple[object, ...], raw.get("chat_invocations", ())))
        != result.chat_invocations
        or raw.get("embedding_usage") != result.embedding_usage
        or raw.get("token_usage") != result.token_usage
        or raw.get("entity_count") != result.entity_count
        or raw.get("relation_count") != result.relation_count
        or raw.get("proposal_count") != result.proposal_count
        or raw.get("chat_invocation_count") != len(result.chat_invocations)
    ):
        raise ValueError("graphiti result fields differ from bound raw receipt")
    passage_id = passage.get("passage_id")
    for proposal in result.proposals:
        evidence = proposal.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("graphiti proposal needs retained passage evidence")
        for item in evidence:
            if (
                not isinstance(item, dict)
                or item.get("passage_id") != passage_id
                or not isinstance(item.get("start_byte"), int)
                or not isinstance(item.get("end_byte"), int)
                or int(item["start_byte"]) < 0
                or int(item["end_byte"]) > int(passage["byte_length"])
                or int(item["start_byte"]) >= int(item["end_byte"])
            ):
                raise ValueError("graphiti proposal evidence is outside the bound passage")
            start_byte = int(item["start_byte"])
            end_byte = int(item["end_byte"])
            if item.get("evidence_text_digest") != digest_bytes(
                expected_bytes[start_byte:end_byte]
            ):
                raise ValueError(
                    "graphiti proposal evidence digest differs from passage bytes"
                )
    return result


def _result_token_usage(result: GraphitiCycleResult) -> dict[str, object]:
    return result.token_usage or summarise_graphiti_usage(
        chat_invocations=result.chat_invocations,
        embedding_usage=result.embedding_usage,
    )


def _receipt(
    unit: CorpusIngestUnit,
    result: GraphitiCycleResult,
    *,
    accounting: dict[str, object],
) -> dict[str, object]:
    receipt: dict[str, object] = {
        "ingest_id": unit.ingest_id,
        "source_id": unit.source_id,
        "item_key": unit.item_key,
        "proving_run_id": unit.proving_run_id,
        "observation_digest": unit.observation_digest,
        "published_at": unit.published_at,
        "updated_at": unit.updated_at,
        "observed_at": unit.observed_at,
        "chunk_ordinal": unit.chunk_ordinal,
        "chunk_count": unit.chunk_count,
        "predecessor_ingest_id": unit.predecessor_ingest_id,
        "attempt_number": unit.attempt_number,
        "provider_attempt_number": result.provider_attempt_number,
        "revision_id": unit.revision_id,
        "authority_record_ids": (
            []
            if unit.authority is None
            else [str(item["record_id"]) for item in unit.authority.records]
        ),
        "outcome": result.outcome,
        "proposal_count": result.proposal_count,
        "entity_count": result.entity_count,
        "relation_count": result.relation_count,
        "failure_code": result.failure_code,
        "temporal_basis": result.temporal_basis,
        "reference_time": result.reference_time,
        "generation_id": result.generation_id,
        "workspace_group": GRAPHITI_WORKSPACE_GROUP,
        "episode_uuid": result.episode_uuid,
        "entities": list(result.entities),
        "relations": list(result.relations),
        "proposals": list(result.proposals),
        "passages": list(result.passages),
        "chat_invocations": list(result.chat_invocations),
        "embedding_usage": result.embedding_usage,
        "token_usage": _result_token_usage(result),
        "accounting": accounting,
        "request_tokens": result.request_tokens,
        "response_tokens": result.response_tokens,
        "cost_microunits": result.cost_microunits,
        "usage_basis": result.usage_basis,
        "prompt_version": result.prompt_version or GRAPHITI_PROMPT_COMPONENT.component_version,
        "chat_subscription_not_debited": True,
        "framework": result.framework or GRAPHITI_CORE_RELEASE,
        "chat": result.chat or GRAPHITI_CHAT_MODEL,
        "chat_fallback": result.chat_fallback or GRAPHITI_CHAT_FALLBACK,
        "embedding": result.embedding or GRAPHITI_EMBEDDING_MODEL,
        "raw_output_digest": result.receipt_digest,
        "receipt_digest": "",
        "profile": "EVALUATION",
    }
    raw = result.raw_receipt
    if isinstance(raw, dict):
        for key in ("dispatch_state", "setup_failure"):
            if key in raw:
                receipt[key] = raw[key]
        fine = raw.get("combined_temporal_failure_code")
        if isinstance(fine, str) and fine:
            receipt["combined_temporal_failure_code"] = fine
        if "timeout_diagnostics" in raw:
            receipt["timeout_diagnostics"] = validated_timeout_diagnostics(
                raw["timeout_diagnostics"]
            )
        if "producer_failure" in raw:
            receipt["producer_failure"] = _validated_producer_failure(
                raw["producer_failure"]
            )
    return receipt


def _retain_attempt_receipt(
    unpublished: sqlite3.Connection,
    *,
    unit: CorpusIngestUnit,
    result: GraphitiCycleResult,
    accounting: dict[str, object],
    dispatch_rights: dict[str, object],
    recovery_classification: GraphitiRecoveryClassification | None = None,
) -> tuple[dict[str, object], str]:
    """Retain one bound attempt receipt and its canonical ledger event."""

    receipt = _receipt(unit, result, accounting=accounting)
    receipt["dispatch_rights"] = dispatch_rights
    if recovery_classification is not None:
        receipt["recovery_classification"] = recovery_classification
    final_digest = insert_graphiti_attempt_receipt(
        unpublished,
        ingest_id=unit.ingest_id,
        attempt_number=unit.attempt_number,
        outcome=result.outcome,
        receipt=receipt,
    )
    receipt["receipt_digest"] = final_digest
    append_ledger(unpublished, "GRAPHITI_EVALUATION_ATTEMPT", receipt)
    return receipt, final_digest


def _queue(
    unpublished: sqlite3.Connection,
    units: tuple[CorpusIngestUnit, ...],
) -> list[tuple[int, str, str, int, int, str, CorpusIngestUnit]]:
    queued: list[tuple[int, str, str, int, int, str, CorpusIngestUnit]] = []
    for unit in units:
        if has_graphiti_ingest(unpublished, unit.ingest_id):
            continue
        retries, dead = graphiti_failure_state(unpublished, unit.ingest_id)
        if dead:
            continue
        if (
            unit.predecessor_ingest_id is not None
            and not has_graphiti_ingest(unpublished, unit.predecessor_ingest_id)
        ):
            continue
        queued.append(
            (
                int(retries == 0),
                unit.observed_at,
                unit.revision_id,
                unit.chunk_ordinal,
                retries,
                unit.ingest_id,
                unit,
            )
        )
    queued.sort()
    return queued


def _fail(
    unpublished: sqlite3.Connection,
    unit: CorpusIngestUnit,
    *,
    outcome: str,
    failure_code: str,
) -> None:
    record_graphiti_failure(
        unpublished,
        ingest_id=unit.ingest_id,
        source_id=unit.source_id,
        item_key=unit.item_key,
        outcome=outcome,
        failure_code=failure_code,
    )


def _reconcile_no_embedding_spend(
    unpublished: sqlite3.Connection, *, spend_id: str
) -> dict[str, object]:
    accounting = reconcile_graphiti_spend(
        unpublished,
        spend_id=spend_id,
        embedding_usage={
            "requests": [],
            "request_count": 0,
            "embedding_tokens": 0,
            "cost_usd_microunits": 0,
            "usage_basis": "NO_EMBEDDING_CALL",
        },
    )
    append_ledger(unpublished, "GRAPHITI_SPEND_RECONCILE", accounting)
    return accounting


def _reports_no_embedding_call(result: GraphitiCycleResult) -> bool:
    return is_exact_no_embedding_call(result.embedding_usage)


def _recovery_classification(
    result: GraphitiCycleResult,
) -> GraphitiRecoveryClassification | None:
    raw = result.raw_receipt if isinstance(result.raw_receipt, dict) else {}
    try:
        return GraphitiRecoveryClassification(str(raw.get("recovery_classification")))
    except ValueError:
        return None


def _proves_no_provider_dispatch(result: GraphitiCycleResult) -> bool:
    raw = result.raw_receipt if isinstance(result.raw_receipt, dict) else {}
    if not _reports_no_embedding_call(result):
        return False
    if not result.chat_invocations:
        return raw.get("dispatch_state") == "NOT_DISPATCHED"
    return raw.get("dispatch_state") in {None, "NOT_DISPATCHED"} and all(
        is_exact_predispatch_no_provider_call(item)
        for item in result.chat_invocations
    )


def _preserve_reused_unresolved_spend(
    unpublished: sqlite3.Connection,
    *,
    spend_id: str,
    owner_id: str,
) -> dict[str, object]:
    released = release_graphiti_attempt_claim(
        unpublished,
        spend_id=spend_id,
        owner_id=owner_id,
    )
    accounting: dict[str, object] = {
        "spend_id": spend_id,
        "status": "RESERVED",
        "usage_basis": "PENDING_PROVIDER_REPORT",
        "reused_unresolved_reservation": True,
        "dispatch_claim_released": released,
    }
    append_ledger(unpublished, "GRAPHITI_SPEND_UNRESOLVED", accounting)
    return accounting


def _retained_provider_raw_digest(
    *,
    unit: CorpusIngestUnit,
    result: GraphitiCycleResult,
    provider_attempt: int,
    receipt_digest: object,
    receipt_json: object,
) -> str | None:
    if not isinstance(receipt_digest, str) or not isinstance(receipt_json, str):
        return None
    try:
        retained = json.loads(receipt_json)
        if not isinstance(retained, dict):
            return None
        unsigned = dict(retained)
        supplied_digest = unsigned.pop("receipt_digest", None)
        calculated_digest = digest_bytes(canonical_json_bytes(unsigned))
    except (TypeError, ValueError, UnicodeError):
        return None
    sanitised_digest = retained.get("returned_validated_raw_digest")
    if isinstance(sanitised_digest, str):
        try:
            validate_sha256_digest(
                sanitised_digest,
                field="returned validated raw digest",
            )
        except ValueError:
            return None
        if (
            supplied_digest == receipt_digest == calculated_digest
            and retained.get("ingest_id") == unit.ingest_id
            and retained.get("attempt_number") == provider_attempt
            and retained.get("provider_attempt_number") == provider_attempt
            and retained.get("embedding_usage_digest")
            == _canonical_digest_or_none(result.embedding_usage)
            and retained.get("chat_invocations_digest")
            == _canonical_digest_or_none(list(result.chat_invocations))
        ):
            return sanitised_digest
        return None
    envelope_matches = (
        supplied_digest == receipt_digest == calculated_digest
        and retained.get("ingest_id") == unit.ingest_id
        and retained.get("attempt_number") == provider_attempt
        and retained.get("provider_attempt_number") == provider_attempt
        and retained.get("embedding_usage") == result.embedding_usage
        and retained.get("chat_invocations") == list(result.chat_invocations)
    )
    if not envelope_matches:
        return None
    nested = retained.get("returned_raw_receipt")
    if isinstance(nested, dict):
        nested_unsigned = dict(nested)
        nested_digest = nested_unsigned.pop("raw_output_digest", None)
        try:
            calculated_nested_digest = digest_bytes(
                canonical_json_bytes(nested_unsigned)
            )
        except (TypeError, ValueError, UnicodeError):
            return None
        if (
            isinstance(nested_digest, str)
            and calculated_nested_digest == nested_digest
            and nested.get("generation_id") == GRAPHITI_GENERATION_ID
            and nested.get("workspace_group") == GRAPHITI_WORKSPACE_GROUP
            and nested.get("episode_uuid") == unit.ingest_id
            and nested.get("attempt_number") == provider_attempt
            and nested.get("provider_attempt_number") == provider_attempt
            and nested.get("embedding_usage") == result.embedding_usage
            and nested.get("chat_invocations") == list(result.chat_invocations)
        ):
            return nested_digest
        return None
    raw_output_digest = retained.get("raw_output_digest")
    if (
        isinstance(raw_output_digest, str)
        and retained.get("generation_id") == GRAPHITI_GENERATION_ID
        and retained.get("workspace_group") == GRAPHITI_WORKSPACE_GROUP
        and retained.get("episode_uuid") == unit.ingest_id
    ):
        return raw_output_digest
    return None


def _reconcile_result_spend(
    unpublished: sqlite3.Connection,
    *,
    unit: CorpusIngestUnit,
    attempt_number: int,
    result: GraphitiCycleResult,
    binding_validated: bool,
) -> dict[str, object]:
    """Attribute returned provider telemetry without trusting invalid identity fields."""

    spend_id = f"{unit.ingest_id}:{attempt_number}"
    if not binding_validated:
        accounting = reconcile_graphiti_spend(
            unpublished,
            spend_id=spend_id,
            embedding_usage=None,
        )
        accounting.update(
            {
                "telemetry_binding": "REJECTED",
                "reported_embedding_usage_digest": _canonical_digest_or_none(
                    result.embedding_usage
                ),
            }
        )
        append_ledger(unpublished, "GRAPHITI_SPEND_RECONCILE", accounting)
        return accounting

    reported_attempt = result.provider_attempt_number
    provider_spend_id = f"{unit.ingest_id}:{reported_attempt}"
    provider_state = unpublished.execute(
        """
        SELECT status,
               (
                   SELECT receipt.receipt_digest
                   FROM unpublished_graphiti_attempt_receipts AS receipt
                   WHERE receipt.ingest_id=spend.ingest_id
                     AND receipt.attempt_number=spend.attempt_number
               ),
               (
                   SELECT receipt.receipt_json
                   FROM unpublished_graphiti_attempt_receipts AS receipt
                   WHERE receipt.ingest_id=spend.ingest_id
                     AND receipt.attempt_number=spend.attempt_number
               )
        FROM unpublished_graphiti_spend AS spend
        WHERE spend_id=?
        """,
        (provider_spend_id,),
    ).fetchone()
    raw = result.raw_receipt if isinstance(result.raw_receipt, dict) else {}
    recovery_classification = _recovery_classification(result)
    recovered_digest = raw.get("recovered_validated_raw_digest")
    retained_raw_digest = (
        _retained_provider_raw_digest(
            unit=unit,
            result=result,
            provider_attempt=reported_attempt,
            receipt_digest=provider_state[1],
            receipt_json=provider_state[2],
        )
        if provider_state is not None
        else None
    )
    retained_provider_receipt = retained_raw_digest is not None
    validated_no_dispatch_recovery = (
        binding_validated
        and provider_spend_id != spend_id
        and provider_state is not None
        and retained_provider_receipt
        and recovery_classification
        is GraphitiRecoveryClassification.RECOVERED_IMMUTABLE_COMPLETE
        and recovered_digest == retained_raw_digest
    )
    if provider_spend_id == spend_id or not validated_no_dispatch_recovery:
        accounting = reconcile_graphiti_spend(
            unpublished,
            spend_id=spend_id,
            embedding_usage=result.embedding_usage,
        )
        if provider_spend_id != spend_id:
            accounting["reported_provider_attempt_number"] = reported_attempt
            accounting["reconciled_to_current_attempt"] = True
        append_ledger(unpublished, "GRAPHITI_SPEND_RECONCILE", accounting)
        return accounting

    assert provider_state is not None
    if str(provider_state[0]) == "RECONCILED":
        provider_attempt: _ProviderAttemptRecoveryAccounting = {
            "spend_id": provider_spend_id,
            "status": "RECONCILED",
            "retained_attempt_receipt": retained_provider_receipt,
            "reconciled_again": False,
            "accounting": None,
        }
    else:
        provider_accounting = reconcile_graphiti_spend(
            unpublished,
            spend_id=provider_spend_id,
            embedding_usage=result.embedding_usage,
        )
        append_ledger(
            unpublished, "GRAPHITI_SPEND_RECONCILE", provider_accounting
        )
        provider_attempt = {
            "spend_id": provider_spend_id,
            "status": str(provider_accounting["status"]),
            "retained_attempt_receipt": retained_provider_receipt,
            "reconciled_again": True,
            "accounting": provider_accounting,
        }
    current_accounting = _reconcile_no_embedding_spend(
        unpublished, spend_id=spend_id
    )
    return {
        "provider_attempt": provider_attempt,
        "current_attempt": current_accounting,
        "recovery_classification": recovery_classification,
    }


def _ingest(
    unpublished: sqlite3.Connection,
    *,
    graphiti: GraphitiPort,
    units: tuple[CorpusIngestUnit, ...],
    max_graphiti: int,
    rights_check: Callable[[CorpusIngestUnit], dict[str, object] | None],
    rights_fence: Callable[
        [CorpusIngestUnit], ContextManager[_DispatchAuthority | None]
    ],
    clock: Callable[[], datetime],
    on_systemic_failure: Callable[[str, bool], None] | None = None,
    model_usage: ModelUsageService | None = None,
    cycle_id: str | None = None,
) -> int:
    if isinstance(graphiti, GovernedRealGraphitiPort) and (
        model_usage is None
        or not callable(getattr(graphiti, "ingest_with_usage", None))
    ):
        return 0

    def finalise_usage(
        unit: CorpusIngestUnit,
        *,
        outcome: str,
        outcome_record_id: str,
        retained_proposal_count: int,
    ) -> None:
        finalise = getattr(graphiti, "finalise_usage", None)
        if callable(finalise):
            finalise(
                unit,
                outcome=outcome,
                outcome_record_id=outcome_record_id,
                retained_proposal_count=retained_proposal_count,
                terminal_at=clock().astimezone(UTC),
                connection=unpublished,
            )

    def systemic_result_failure(result: GraphitiCycleResult) -> str | None:
        if result.failure_code != "PRODUCER_INTERNAL_ERROR":
            return None
        if result_proves_no_provider_dispatch(result) and any(
            invocation.get("outcome")
            in {"PREDISPATCH_REFUSED", "EXECUTABLE_NOT_FOUND"}
            for invocation in result.chat_invocations
        ):
            return "CLI_PREDISPATCH_CONFIGURATION_REFUSED"
        raw = result.raw_receipt
        if not isinstance(raw, dict):
            return None
        failure = raw.get("setup_failure") or raw.get("producer_failure")
        return str(failure) if isinstance(failure, str) and failure else None

    def result_proves_no_provider_dispatch(result: GraphitiCycleResult) -> bool:
        if (
            model_usage is not None
            and cycle_id is not None
            and model_usage.has_committed_provider_dispatch(cycle_id=cycle_id)
        ):
            return False
        return _proves_no_provider_dispatch(result)

    attempted = 0
    for (
        _is_retry,
        _observed_at,
        _revision_id,
        _chunk_ordinal,
        _retries,
        _ingest_id,
        unit,
    ) in _queue(unpublished, units):
        if attempted >= max_graphiti:
            break
        dispatch_rights = rights_check(unit)
        if dispatch_rights is None:
            append_ledger(
                unpublished,
                "GRAPHITI_RIGHTS_HOLD",
                {
                    "ingest_id": unit.ingest_id,
                    "source_id": unit.source_id,
                    "proving_run_id": unit.proving_run_id,
                    "reason": "NO_CURRENT_DISPATCH_RIGHTS",
                    "provider_dispatched": False,
                },
            )
            unpublished.commit()
            continue
        append_ledger(
            unpublished,
            "GRAPHITI_RIGHTS_DISPATCH",
            {
                **dispatch_rights,
                "ingest_id": unit.ingest_id,
                "proving_run_id": unit.proving_run_id,
                "provider_dispatched": False,
            },
        )
        unpublished.commit()
        attempt_number = next_graphiti_attempt_number(unpublished, unit.ingest_id)
        unit = replace(unit, attempt_number=attempt_number)
        if unit.authority is None:
            raise ValueError("corpus ingest requires retained authority records")
        retain_graphiti_authority_records(unpublished, unit.authority.records)
        spend_id = f"{unit.ingest_id}:{attempt_number}"
        try:
            reserved = reserve_graphiti_spend(
                unpublished,
                spend_id=spend_id,
                ingest_id=unit.ingest_id,
                attempt_number=attempt_number,
                proving_run_id=unit.proving_run_id,
                generation_id=GRAPHITI_GENERATION_ID,
                reserved_gbp_microunits=GRAPHITI_UNIT_RESERVATION_GBP_MICROUNITS,
                ceiling_gbp_microunits=OD_011_CASH_CEILING_GBP * 1_000_000,
            )
        except GraphitiSpendCeilingExceeded:
            append_ledger(
                unpublished,
                "GRAPHITI_SPEND_HOLD",
                {
                    "ingest_id": unit.ingest_id,
                    "attempt_number": attempt_number,
                    "proving_run_id": unit.proving_run_id,
                    "reason": "OD_011_CASH_CEILING",
                    "ceiling_gbp_microunits": (
                        OD_011_CASH_CEILING_GBP * 1_000_000
                    ),
                    "writer_continues": True,
                },
            )
            unpublished.commit()
            break
        if reserved:
            append_ledger(
                unpublished,
                "GRAPHITI_SPEND_RESERVE",
                {
                    "spend_id": spend_id,
                    "ingest_id": unit.ingest_id,
                    "attempt_number": attempt_number,
                    "profile": "EVALUATION",
                    "metered_api": OPENROUTER_API,
                    "metered_use": "embeddings",
                    "reserved_gbp_microunits": (
                        GRAPHITI_UNIT_RESERVATION_GBP_MICROUNITS
                    ),
                    "chat": GRAPHITI_CHAT_MODEL,
                    "chat_fallback": GRAPHITI_CHAT_FALLBACK,
                    "chat_subscription_not_debited": True,
                    "od_011_cash_ceiling_gbp": OD_011_CASH_CEILING_GBP,
                    "prespent": False,
                    "hosts": ["openrouter.ai"],
                    "generation_id": GRAPHITI_GENERATION_ID,
                    "proving_run_id": unit.proving_run_id,
                },
            )
        unpublished.commit()
        returned_result: GraphitiCycleResult | None = None
        result_failure_stage = GRAPHITI_RESULT_STAGE_UNCLASSIFIED
        owner_id: str | None = None
        try:
            # Re-read under a proving-writer fence after all local commits, then
            # retain the fence through the synchronous provider handoff.
            with rights_fence(unit) as dispatch_authority:
                if dispatch_authority is None:
                    if reserved:
                        _reconcile_no_embedding_spend(
                            unpublished, spend_id=spend_id
                        )
                    append_ledger(
                        unpublished,
                        "GRAPHITI_RIGHTS_HOLD",
                        {
                            "ingest_id": unit.ingest_id,
                            "source_id": unit.source_id,
                            "attempt_number": attempt_number,
                            "proving_run_id": unit.proving_run_id,
                            "reason": "AUTHORITY_REVOKED_BEFORE_PROVIDER_DISPATCH",
                            "provider_dispatched": False,
                        },
                    )
                    unpublished.commit()
                    continue
                final_dispatch_rights = dispatch_authority.rights
                claim_instant = clock().astimezone(UTC)
                owner_id = f"graphiti-dispatch-{uuid.uuid4()}"
                lease_expires_at = claim_instant + timedelta(minutes=15)
                claimed = claim_graphiti_attempt(
                    unpublished,
                    spend_id=spend_id,
                    generation_id=GRAPHITI_GENERATION_ID,
                    owner_id=owner_id,
                    claimed_at=_utc_text(claim_instant),
                    lease_expires_at=_utc_text(lease_expires_at),
                )
                if not claimed:
                    append_ledger(
                        unpublished,
                        "GRAPHITI_ATTEMPT_BUSY",
                        {
                            "spend_id": spend_id,
                            "ingest_id": unit.ingest_id,
                            "attempt_number": attempt_number,
                            "reason": "ACTIVE_DISPATCH_LEASE",
                            "provider_dispatched": False,
                        },
                    )
                    unpublished.commit()
                    break
                append_ledger(
                    unpublished,
                    "GRAPHITI_ATTEMPT_CLAIM",
                    {
                        "spend_id": spend_id,
                        "ingest_id": unit.ingest_id,
                        "attempt_number": attempt_number,
                        "owner_id": owner_id,
                        "lease_expires_at": _utc_text(lease_expires_at),
                        "provider_dispatched": False,
                    },
                )
                unpublished.commit()
                dispatch_rights = final_dispatch_rights
                attempted += 1
                ingest_with_usage = getattr(graphiti, "ingest_with_usage", None)
                if model_usage is not None and callable(ingest_with_usage):
                    usage_arguments: dict[str, object] = {
                        "model_usage": model_usage,
                        "cycle_id": cycle_id or unit.proving_run_id,
                        "deadline": (
                            dispatch_authority.deadline
                            if isinstance(graphiti, GovernedRealGraphitiPort)
                            else None
                        ),
                        "dispatch_authority": final_dispatch_rights,
                        "owner_stop_check": dispatch_authority.owner_stop_check,
                    }
                    returned_result = cast(
                        GraphitiCycleResult,
                        ingest_with_usage(
                            unit,
                            **usage_arguments,
                        ),
                    )
                elif isinstance(graphiti, GovernedRealGraphitiPort):
                    returned_result = graphiti.ingest_until(
                        unit,
                        deadline=dispatch_authority.deadline,
                    )
                else:
                    returned_result = graphiti.ingest(unit)
            result_failure_stage = GRAPHITI_RESULT_STAGE_CYCLE_RESULT_BINDING
            result = _bind_result(
                unit,
                returned_result,
                authority_connection=unpublished,
            )
        except _ProvingFenceUnavailable:
            if reserved:
                _reconcile_no_embedding_spend(unpublished, spend_id=spend_id)
            append_ledger(
                unpublished,
                "GRAPHITI_RIGHTS_HOLD",
                {
                    "ingest_id": unit.ingest_id,
                    "source_id": unit.source_id,
                    "attempt_number": attempt_number,
                    "proving_run_id": unit.proving_run_id,
                    "reason": "PROVING_FENCE_UNAVAILABLE",
                    "provider_dispatched": False,
                },
            )
            unpublished.commit()
            break
        except VetoError:
            raise
        except (RuntimeError, ValueError, OSError, json.JSONDecodeError) as exc:
            preserve_unresolved = (
                not reserved
                and owner_id is not None
                and (
                    returned_result is None
                    or _reports_no_embedding_call(returned_result)
                )
            )
            if preserve_unresolved:
                assert owner_id is not None
                dispatch_state = (
                    "NOT_DISPATCHED"
                    if returned_result is not None
                    and result_proves_no_provider_dispatch(returned_result)
                    else "UNKNOWN"
                )
                accounting = _preserve_reused_unresolved_spend(
                    unpublished,
                    spend_id=spend_id,
                    owner_id=owner_id,
                )
                append_ledger(
                    unpublished,
                    "GRAPHITI_EVALUATION_RETRY_HELD",
                    {
                        "ingest_id": unit.ingest_id,
                        "attempt_number": attempt_number,
                        "failure": type(exc).__name__,
                        "accounting": accounting,
                        "provider_dispatch_state": dispatch_state,
                        **_rejected_result_metadata(returned_result),
                    },
                )
                unpublished.commit()
                continue
            if returned_result is None:
                accounting = reconcile_graphiti_spend(
                    unpublished, spend_id=spend_id, embedding_usage=None
                )
                append_ledger(unpublished, "GRAPHITI_SPEND_RECONCILE", accounting)
            else:
                accounting = _reconcile_result_spend(
                    unpublished,
                    unit=unit,
                    attempt_number=attempt_number,
                    result=returned_result,
                    binding_validated=False,
                )
            systemic_exception = isinstance(exc, (OSError, RuntimeError)) and (
                on_systemic_failure is not None
            )
            if not systemic_exception:
                _fail(
                    unpublished,
                    unit,
                    outcome="FAILED",
                    failure_code="PRODUCER_INTERNAL_ERROR",
                )
            failure_receipt = {
                "ingest_id": unit.ingest_id,
                "source_id": unit.source_id,
                "item_key": unit.item_key,
                "proving_run_id": unit.proving_run_id,
                "attempt_number": attempt_number,
                "outcome": "FAILED",
                "failure_code": "PRODUCER_INTERNAL_ERROR",
                "binding_failure": "RESULT_CONTRACT_REJECTED",
                "binding_failure_type": type(exc).__name__,
                "binding_failure_stage": (
                    exc.stage
                    if isinstance(exc, GraphitiResultStageError)
                    else result_failure_stage
                ),
                **_rejected_result_metadata(returned_result),
                "provider_attempt_number": (
                    _rejected_provider_attempt_number(returned_result)
                ),
                "accounting": accounting,
                "authority_record_ids": [
                    str(item["record_id"]) for item in unit.authority.records
                ],
                "dispatch_rights": dispatch_rights,
                "receipt_digest": "",
            }
            final_digest = insert_graphiti_attempt_receipt(
                unpublished,
                ingest_id=unit.ingest_id,
                attempt_number=attempt_number,
                outcome="FAILED",
                receipt=failure_receipt,
            )
            failure_receipt["receipt_digest"] = final_digest
            append_ledger(unpublished, "GRAPHITI_EVALUATION_ATTEMPT", failure_receipt)
            finalise_usage(
                unit,
                outcome="GRAPHITI_REJECTED_BINDING",
                outcome_record_id=final_digest,
                retained_proposal_count=0,
            )
            unpublished.commit()
            if systemic_exception and on_systemic_failure is not None:
                on_systemic_failure(type(exc).__name__, attempted > 0)
            continue
        terminal_outcome = result.outcome in {"COMPLETE", "PARTIAL"}
        systemic_failure = systemic_result_failure(result)
        recovery_classification = _recovery_classification(result)
        marker_recovery = (
            recovery_classification
            if recovery_classification in _CLOSED_MARKER_RECOVERIES
            else None
        )
        if (
            not reserved
            and owner_id is not None
            and not terminal_outcome
            and _reports_no_embedding_call(result)
        ):
            accounting = _preserve_reused_unresolved_spend(
                unpublished,
                spend_id=spend_id,
                owner_id=owner_id,
            )
            transition_payload: dict[str, object] = {
                "ingest_id": unit.ingest_id,
                "attempt_number": attempt_number,
                "failure_code": result.failure_code,
                "accounting": accounting,
                "chat_invocations": list(result.chat_invocations),
                "embedding_usage": result.embedding_usage,
                "token_usage": _result_token_usage(result),
                "provider_dispatch_state": (
                    "NOT_DISPATCHED"
                    if result_proves_no_provider_dispatch(result)
                    else "UNKNOWN"
                ),
            }
            if marker_recovery is not None:
                transition_payload["recovery_classification"] = marker_recovery
                append_ledger(
                    unpublished,
                    _GRAPHITI_RECOVERY_CLOSED_LEDGER_KIND,
                    transition_payload,
                )
                if systemic_failure is None:
                    _fail(
                        unpublished,
                        unit,
                        outcome=result.outcome,
                        failure_code=result.failure_code,
                    )
                _marker_receipt, marker_digest = _retain_attempt_receipt(
                    unpublished,
                    unit=unit,
                    result=result,
                    accounting=accounting,
                    dispatch_rights=dispatch_rights,
                    recovery_classification=marker_recovery,
                )
                finalise_usage(
                    unit,
                    outcome=f"GRAPHITI_{result.outcome}",
                    outcome_record_id=marker_digest,
                    retained_proposal_count=0,
                )
            else:
                append_ledger(
                    unpublished,
                    "GRAPHITI_EVALUATION_RETRY_HELD",
                    transition_payload,
                )
                finalise_usage(
                    unit,
                    outcome="GRAPHITI_RETRY_HELD",
                    outcome_record_id=spend_id,
                    retained_proposal_count=0,
                )
            unpublished.commit()
            if systemic_failure is not None and on_systemic_failure is not None:
                on_systemic_failure(
                    systemic_failure,
                    attempted > 0
                    and not result_proves_no_provider_dispatch(result),
                )
            continue
        accounting = _reconcile_result_spend(
            unpublished,
            unit=unit,
            attempt_number=attempt_number,
            result=result,
            binding_validated=True,
        )
        receipt, final_digest = _retain_attempt_receipt(
            unpublished,
            unit=unit,
            result=result,
            accounting=accounting,
            dispatch_rights=dispatch_rights,
            recovery_classification=(
                recovery_classification if terminal_outcome else marker_recovery
            ),
        )
        if terminal_outcome:
            insert_graphiti_ingest(
                unpublished,
                ingest_id=unit.ingest_id,
                source_id=unit.source_id,
                item_key=unit.item_key,
                outcome=result.outcome,
                proposal_count=result.proposal_count,
                entity_count=result.entity_count,
                relation_count=result.relation_count,
                failure_code=result.failure_code,
                temporal_basis=result.temporal_basis,
                reference_time=result.reference_time,
                generation_id=result.generation_id,
                receipt_digest=final_digest,
                receipt=receipt,
            )
            clear_graphiti_failure(unpublished, unit.ingest_id)
        else:
            if systemic_failure is None:
                _fail(
                    unpublished,
                    unit,
                    outcome=result.outcome,
                    failure_code=result.failure_code,
                )
        finalise_usage(
            unit,
            outcome=(
                "GRAPHITI_SUCCESS_ZERO_PROPOSALS"
                if result.outcome == "COMPLETE" and result.proposal_count == 0
                else "GRAPHITI_SUCCESS"
                if result.outcome == "COMPLETE"
                else f"GRAPHITI_{result.outcome}"
            ),
            outcome_record_id=final_digest,
            retained_proposal_count=(
                result.proposal_count if terminal_outcome else 0
            ),
        )
        unpublished.commit()
        if systemic_failure is not None and on_systemic_failure is not None:
            on_systemic_failure(
                systemic_failure,
                attempted > 0 and not result_proves_no_provider_dispatch(result),
            )
    return attempted


def _parsed_observations(
    rows: tuple[_ProvingObservation, ...],
) -> tuple[GroupedObservation, ...]:
    observations: list[GroupedObservation] = []
    for row in rows:
        for item in parse_observation(
            source_id=row.source_id, url=row.url, body=row.body
        ):
            observations.append(
                GroupedObservation(
                    source_id=row.source_id,
                    observation_digest=row.body_digest,
                    item=item,
                    observed_at=row.fetched_at,
                )
            )
    return tuple(observations)


def _current_rights_decision(
    proving: sqlite3.Connection,
    *,
    run_id: str,
    source_id: str,
    source_url: str,
    evaluated_at: str,
    required_valid_until: str | None = None,
) -> dict[str, object] | None:
    """Re-evaluate one run's retained source packet."""

    gate_id = f"RIGHTS_{source_id}"
    try:
        retained = proving.execute(
            """
            SELECT gate.status, packet.packet_digest, packet.packet_json
            FROM proving_gates AS gate
            JOIN proving_rights_packets AS packet
              ON packet.run_id=gate.run_id AND packet.gate_id=gate.gate_id
            WHERE gate.run_id=? AND gate.gate_id=?
            """,
            (run_id, gate_id),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if retained is None or str(retained[0]) != "PASS":
        return None
    return _rights_decision_from_packet(
        run_id=run_id,
        source_id=source_id,
        source_url=source_url,
        evaluated_at=evaluated_at,
        packet_digest=str(retained[1]),
        packet_json=str(retained[2]),
        required_valid_until=required_valid_until,
    )


def _rights_decision_from_packet(
    *,
    run_id: str,
    source_id: str,
    source_url: str,
    evaluated_at: str,
    packet_digest: str,
    packet_json: str,
    required_valid_until: str | None = None,
) -> dict[str, object] | None:
    gate_id = f"RIGHTS_{source_id}"
    try:
        packet = json.loads(packet_json)
    except json.JSONDecodeError:
        return None
    if digest_bytes(canonical_json_bytes(packet)) != packet_digest:
        return None
    verdict = assess_rights(gate_id, inventory=packet, now=evaluated_at)
    if (
        verdict.status != "PASS"
        or verdict.gate_id != gate_id
        or not verdict.endpoint
        or source_url != verdict.endpoint
        or not verdict.expires_at
        or not verdict.terms_url
        or not verdict.terms_digest
        or (
            required_valid_until is not None
            and verdict.expires_at <= required_valid_until
        )
    ):
        return None
    return {
        "status": "PASS",
        "gate_id": gate_id,
        "source_id": source_id,
        "source_definition_url": source_url,
        "rights_endpoint": verdict.endpoint,
        "rights_destinations": verdict.destinations,
        "packet_digest": packet_digest,
        "expires_at": verdict.expires_at,
        "terms_url": verdict.terms_url,
        "terms_digest": verdict.terms_digest,
        "evaluated_at": evaluated_at,
        "rights_authority_run_id": run_id,
    }


def _dispatch_rights_decision(
    proving: sqlite3.Connection,
    *,
    source_id: str,
    source_url: str,
    evaluated_at: str,
    required_valid_until: str | None = None,
) -> dict[str, object] | None:
    """Read latest-run vetoes and source rights in one SQLite snapshot."""

    required_gates = tuple(sorted(GLOBAL_PROVING_GATES))
    placeholders = ",".join("?" for _ in required_gates)
    gate_id = f"RIGHTS_{source_id}"
    try:
        retained = proving.execute(
            f"""
            WITH latest AS (
                SELECT run_id
                FROM proving_runs
                ORDER BY {_PROVING_RUN_LATEST_ORDER}
                LIMIT 1
            ),
            global_authority AS (
                SELECT COUNT(DISTINCT gate.gate_id) AS passed_count
                FROM proving_gates AS gate
                JOIN latest ON latest.run_id=gate.run_id
                WHERE gate.gate_id IN ({placeholders})
                  AND gate.status='PASS'
            )
            SELECT latest.run_id, source_gate.status,
                   packet.packet_digest, packet.packet_json
            FROM latest
            JOIN global_authority
              ON global_authority.passed_count=?
            JOIN proving_gates AS source_gate
              ON source_gate.run_id=latest.run_id
             AND source_gate.gate_id=?
            JOIN proving_rights_packets AS packet
              ON packet.run_id=source_gate.run_id
             AND packet.gate_id=source_gate.gate_id
            """,
            (*required_gates, len(required_gates), gate_id),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if retained is None or str(retained[1]) != "PASS":
        return None
    decision = _rights_decision_from_packet(
        run_id=str(retained[0]),
        source_id=source_id,
        source_url=source_url,
        evaluated_at=evaluated_at,
        packet_digest=str(retained[2]),
        packet_json=str(retained[3]),
        required_valid_until=required_valid_until,
    )
    if decision is None:
        return None
    destinations = decision.get("rights_destinations")
    if not isinstance(destinations, tuple) or not GRAPHITI_EVALUATION_DESTINATION_TOKENS.issubset(
        destinations
    ):
        return None
    return decision


def _latest_run_id(proving: sqlite3.Connection) -> str | None:
    row = proving.execute(
        f"SELECT run_id FROM proving_runs ORDER BY {_PROVING_RUN_LATEST_ORDER} LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return str(row[0])


def _latest_run_with_global_authority(
    proving: sqlite3.Connection,
) -> str | None:
    run_id = _latest_run_id(proving)
    if run_id is None:
        return None
    gates = {
        str(gate_id): str(status)
        for gate_id, status in proving.execute(
            "SELECT gate_id, status FROM proving_gates WHERE run_id=?",
            (run_id,),
        ).fetchall()
    }
    if any(gates.get(gate_id) != "PASS" for gate_id in GLOBAL_PROVING_GATES):
        return None
    return run_id


def _permitted_rows(
    proving: sqlite3.Connection,
    *,
    evaluated_at: str,
    required_valid_until: str | None = None,
) -> tuple[str, tuple[_ProvingObservation, ...], tuple[_ProvingObservation, ...]]:
    raw_http_cutoff = _utc_text(
        datetime.fromisoformat(evaluated_at.replace("Z", "+00:00"))
        - _RAW_HTTP_RETENTION
    )
    runs = proving.execute(
        f"SELECT run_id FROM proving_runs ORDER BY {_PROVING_RUN_EARLIEST_ORDER}"
    ).fetchall()
    latest_run_id = _latest_run_id(proving)
    if not runs or latest_run_id is None:
        raise ValueError("proving store has no runs")
    if _latest_run_with_global_authority(proving) != latest_run_id:
        return latest_run_id, (), ()
    all_rows: list[_ProvingObservation] = []
    latest_rows: list[_ProvingObservation] = []
    for (raw_run_id,) in runs:
        run_id = str(raw_run_id)
        values = proving.execute(
            """
            SELECT source_id, url, fetched_at, status_code, body_digest, body, error
            FROM proving_observations
            WHERE run_id=? AND fetched_at>=?
            ORDER BY source_id, fetched_at, body_digest
            """,
            (run_id, raw_http_cutoff),
        ).fetchall()
        for source_id, url, fetched_at, status_code, body_digest, body, error in values:
            source_id_text = str(source_id)
            source_url = str(url)
            current = _current_rights_decision(
                proving,
                run_id=latest_run_id,
                source_id=source_id_text,
                source_url=source_url,
                evaluated_at=evaluated_at,
                required_valid_until=required_valid_until,
            )
            if (
                current is None
                or int(status_code) != 200
                or not body
                or error is not None
            ):
                continue
            body_bytes = bytes(body)
            assessment = assess_content(source_url, body_bytes)
            if not assessment.usable:
                continue
            stable_rights = dict(current)
            stable_rights.pop("evaluated_at", None)
            gate_id = str(current["gate_id"])
            row = _ProvingObservation(
                run_id=run_id,
                source_id=source_id_text,
                url=source_url,
                fetched_at=str(fetched_at),
                status_code=int(status_code),
                body_digest=str(body_digest),
                body=body_bytes,
                rights_authority_run_id=latest_run_id,
                rights_gate_id=gate_id,
                rights_gate_reason=canonical_json_bytes(stable_rights).decode("utf-8"),
                item_count=assessment.item_count,
            )
            all_rows.append(row)
            if run_id == latest_run_id:
                latest_rows.append(row)
    return latest_run_id, tuple(latest_rows), tuple(all_rows)


def _emit_effective_revision_landed(
    unpublished: sqlite3.Connection,
    units: tuple[CorpusIngestUnit, ...],
    first_seen: tuple[tuple[str, str, str, str], ...],
    pull_first_seen: tuple[EffectivePullFirstSeen, ...],
    permitted_source_ids: frozenset[str],
) -> None:
    grouped: dict[tuple[str, str, str, str, str], list[CorpusIngestUnit]] = {}
    for unit in units:
        grouped.setdefault(unit.coverage_key(), []).append(unit)
    for chunks in grouped.values():
        ordered = sorted(chunks, key=lambda item: item.chunk_ordinal)
        first = ordered[0]
        emit_effective_revision_landed(
            unpublished,
            first.effective_revision,
            published_at=first.published_at or "",
            updated_at=first.updated_at or "",
            ingest_ids=tuple(item.ingest_id for item in ordered),
            landed_at=min(item.coverage_first_observed_at for item in ordered),
        )
    first_seen_by_revision = {
        (source_id, item_key, revision_digest): observed_at
        for source_id, item_key, revision_digest, observed_at in first_seen
    }
    pull_revisions: set[tuple[str, str, str]] = set()
    for pull in pull_first_seen:
        pull_revisions.add((pull.source_id, pull.item_key, pull.revision_digest))
        if pull.source_id not in permitted_source_ids:
            continue
        revision_first_seen = first_seen_by_revision.get(
            (pull.source_id, pull.item_key, pull.revision_digest)
        )
        if revision_first_seen is None:
            continue
        identity = EffectiveRevisionIdentity(
            source_id=pull.source_id,
            item_key=pull.item_key,
            revision_digest=pull.revision_digest,
            first_observed_at=revision_first_seen,
        )
        emit_effective_revision_landed(
            unpublished,
            identity,
            published_at=pull.published_at,
            updated_at=pull.updated_at,
            landed_at=pull.first_observed_at,
        )
    for revision, observed_at in first_seen_by_revision.items():
        source_id, item_key, revision_digest = revision
        if source_id not in permitted_source_ids or revision in pull_revisions:
            continue
        emit_effective_revision_landed(
            unpublished,
            EffectiveRevisionIdentity(
                source_id=source_id,
                item_key=item_key,
                revision_digest=revision_digest,
                first_observed_at=observed_at,
            ),
        )


def _backfill_proving_first_seen(proving_store: str) -> None:
    """Backfill missing first-seen rows for pre-existing revisions."""
    timeout_ms = max(1, int(_PROVING_FENCE_TIMEOUT_SECONDS * 1_000))
    connection = sqlite3.connect(
        proving_store, timeout=_PROVING_FENCE_TIMEOUT_SECONDS
    )
    apply_control_plane_sqlite_profile(
        connection, wal=None, busy_timeout_ms=timeout_ms
    )
    try:
        create_effective_revision_schema(connection)
        backfill_missing_first_seen(connection)
    finally:
        connection.close()


def _rights_permitted_source_ids(
    proving: sqlite3.Connection,
    run_id: str,
    *,
    evaluated_at: str,
    required_valid_until: str | None = None,
) -> frozenset[str]:
    if _latest_run_with_global_authority(proving) != run_id:
        return frozenset()
    permitted: set[str] = set()
    for gate_id, status in proving.execute(
        "SELECT gate_id, status FROM proving_gates WHERE run_id=?",
        (run_id,),
    ):
        if not str(gate_id).startswith("RIGHTS_") or str(status) != "PASS":
            continue
        source_id = str(gate_id).removeprefix("RIGHTS_")
        url_row = proving.execute(
            """
            SELECT url FROM proving_observations
            WHERE source_id=?
            ORDER BY fetched_at DESC
            LIMIT 1
            """,
            (source_id,),
        ).fetchone()
        if url_row is None:
            continue
        if (
            _current_rights_decision(
                proving,
                run_id=run_id,
                source_id=source_id,
                source_url=str(url_row[0]),
                evaluated_at=evaluated_at,
                required_valid_until=required_valid_until,
            )
            is None
        ):
            continue
        permitted.add(source_id)
    return frozenset(permitted)


def _load_first_seen(
    proving: sqlite3.Connection,
) -> tuple[tuple[str, str, str, str], ...]:
    exists = proving.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type='table' AND name='proving_revision_first_seen'
        """
    ).fetchone()
    if exists is None:
        return ()
    return tuple(
        (str(source_id), str(item_key), str(revision_digest), str(first_seen_at))
        for source_id, item_key, revision_digest, first_seen_at in proving.execute(
            """
            SELECT source_id, item_key, revision_digest, first_seen_at
            FROM proving_revision_first_seen
            """
        )
    )


def _load_pull_first_seen(
    proving: sqlite3.Connection,
) -> tuple[EffectivePullFirstSeen, ...]:
    exists = proving.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type='table' AND name='proving_effective_pull_first_seen'
        """
    ).fetchone()
    if exists is None:
        return ()
    return tuple(
        EffectivePullFirstSeen(*(str(value or "") for value in row))
        for row in proving.execute(
            """
            SELECT source_id, item_key, revision_digest, published_at,
                   updated_at, first_seen_at
            FROM proving_effective_pull_first_seen
            """
        )
    )


def _payload_digest(payload: UnpublishedSurfacePayload) -> str:
    return digest_bytes(
        canonical_json_bytes(
            {
                "payload_kind": payload.payload_kind,
                "publication_bundle": payload.publication_bundle,
                "auto_publish": payload.auto_publish,
                "language": payload.language,
                "title": payload.title,
                "body": payload.body,
                "evidence_package_digest": payload.evidence_package_digest,
                "story_candidate_id": payload.story_candidate_id,
                "event_hypothesis_id": payload.event_hypothesis_id,
                "source_lineage": payload.source_lineage,
                "generated_at": payload.generated_at,
                "status": payload.status,
                "writer_id": payload.writer_id,
            }
        )
    )


def _dispatch_writer(
    writer: WriterPort,
    candidate: StoryCandidateRecord,
    package: EvidencePackage,
    *,
    route: WriterRoute,
) -> WriterCopy:
    require_permitted_context(candidate, package)
    dispatch = getattr(writer, "dispatch", None)
    if callable(dispatch):
        return cast(WriterCopy, dispatch(candidate, package, route=route))
    if route == "FALLBACK":
        raise WriterDispatchError(
            "writer exposes no fallback route",
            failure_class="CANDIDATE_LOCAL",
            reason_code="FALLBACK_ROUTE_UNAVAILABLE",
        )
    try:
        return writer.write(candidate, package)
    except VetoError:
        raise
    except WriterDispatchError:
        raise
    except (RuntimeError, ValueError, OSError, json.JSONDecodeError) as exc:
        raise WriterDispatchError(
            str(exc),
            failure_class="UNKNOWN",
            reason_code="UNKNOWN_WRITER_FAILURE",
        ) from exc


def _complete_writer_usage(
    model_usage: ModelUsageService,
    allocation: InvocationAllocation,
    *,
    outcome: str,
    failure_class: str | None,
    usage: dict[str, object] | None,
    dispatch_at: datetime | None,
    completed_at: datetime,
    provider_dispatched: bool = True,
    policy: InvocationEfficiencyPolicy,
) -> None:
    usage_value = usage if isinstance(usage, dict) else {}
    reported = usage_value.get("usage_basis") == "PROVIDER_REPORTED"
    if not provider_dispatched:
        components = UsageComponents(total_tokens=0, provenance="CLI_DERIVED")
        usage_status = UsageStatus.REPORTED
        telemetry_digest = None
    elif reported:
        components = UsageComponents(
            input_tokens=cast(int | None, usage_value.get("input_tokens")),
            output_tokens=cast(int | None, usage_value.get("output_tokens")),
            cached_read_tokens=cast(int | None, usage_value.get("cached_read_tokens")),
            cached_write_tokens=cast(int | None, usage_value.get("cached_write_tokens")),
            reasoning_tokens=cast(int | None, usage_value.get("reasoning_tokens")),
            context_tokens=cast(int | None, usage_value.get("context_tokens")),
            total_tokens=cast(int | None, usage_value.get("total_tokens")),
            provenance="PROVIDER_REPORTED",
        )
        usage_status = UsageStatus.REPORTED
        telemetry_digest = digest_bytes(canonical_json_bytes(usage_value))
    else:
        ceiling = policy.hard_estimate_ceiling_tokens
        components = (
            UsageComponents(
                total_tokens=ceiling,
                provenance="BOUNDED_ESTIMATE",
            )
            if ceiling is not None
            else UsageComponents(provenance="UNAVAILABLE")
        )
        usage_status = (
            UsageStatus.ESTIMATED
            if ceiling is not None
            else UsageStatus.UNREPORTED
        )
        telemetry_digest = None
    model_usage.complete(
        InvocationTerminal.create(
            invocation_id=allocation.invocation_id,
            outcome=outcome,
            failure_class=failure_class,
            usage_status=usage_status,
            components=components,
            dispatch_at=dispatch_at if provider_dispatched else None,
            completed_at=completed_at,
            observed_at=completed_at,
            provider_telemetry_digest=telemetry_digest,
            raw_telemetry_pointer=(
                "sqlite-private://model_provider_telemetry/"
                f"{allocation.invocation_id}"
                if reported
                else None
            ),
            subscription_cli_chat_not_cash_debited=True,
            pre_dispatch_zero_proved=not provider_dispatched,
            estimate_policy_digest=(
                policy.canonical_digest
                if usage_status is UsageStatus.ESTIMATED
                else None
            ),
            estimate_calculation=(
                "qualified_policy.hard_estimate_ceiling_tokens="
                f"{policy.hard_estimate_ceiling_tokens}"
                if usage_status is UsageStatus.ESTIMATED
                else None
            ),
        ),
        provider_telemetry=usage_value if reported else None,
    )


def _run_write_loop(
    unpublished: sqlite3.Connection,
    *,
    writer: WriterPort,
    admitted: tuple[
        tuple[StoryCandidateRecord, EvidencePackage, WriteAdmissionDecision], ...
    ],
    max_writes: int,
    max_write_ready_candidates: int,
    max_writer_provider_dispatches: int,
    max_writer_fallback_dispatches: int,
    selected_at: str,
    cycle_execution_id: str,
    writer_dispatch_fence: Callable[[], None] | None,
    writer_owner_stop_fence: Callable[[], ContextManager[None]] | None,
    model_usage: ModelUsageService | None,
    clock: Callable[[], datetime],
) -> _WriteLoopResult:
    permitted: list[
        tuple[StoryCandidateRecord, EvidencePackage, WriteAdmissionDecision]
    ] = []
    for candidate, package, decision in admitted:
        try:
            require_permitted_context(candidate, package)
        except WriterDispatchError:
            continue
        permitted.append((candidate, package, decision))
    admitted = tuple(permitted)
    duplicate = 0
    for candidate, package, decision in admitted:
        if decision.decision == "WRITE_READY" and has_candidate(
            unpublished, candidate.candidate_id
        ):
            duplicate += 1
            continue
    selection_limit = min(max_write_ready_candidates, 5)
    if max_writes <= 0 or max_writer_provider_dispatches <= 0:
        selection_limit = 0
    selected = select_write_ready(
        tuple(
            item
            for item in admitted
            if not (
                item[2].decision == "WRITE_READY"
                and has_candidate(unpublished, item[0].candidate_id)
            )
        ),
        limit=selection_limit,
        selected_at=selected_at,
    )
    for _candidate, _package, _decision, selection in selected:
        retain_write_selection(unpublished, selection)
        append_ledger(unpublished, "WRITE_READY_SELECTION", selection.as_record())

    minted = 0
    candidate_attempts = 0
    provider_dispatches = 0
    primary_dispatches = 0
    fallback_dispatches = 0
    draft_counts: Counter[str] = Counter()
    draft_reasons: Counter[str] = Counter()
    writer_circuit_reason = ""
    no_useful_reason = ""

    def outcome(
        *,
        decision: WriteAdmissionDecision,
        candidate_attempt_id: str,
        provider_attempt_ids: tuple[str, ...],
        result: str,
        validators: tuple[WriterValidatorResult, ...],
        reasons: tuple[str, ...],
        payload_digest: str | None = None,
        usage_envelope_id: str | None = None,
        rejected_copy: WriterCopy | None = None,
    ) -> None:
        terminal_at = clock().astimezone(UTC)
        record = DraftOutcomeRecord.create(
            write_admission_decision_id=decision.decision_id,
            candidate_id=decision.candidate_id,
            evidence_package_digest=decision.evidence_package_digest,
            provider_attempt_ids=provider_attempt_ids,
            outcome=result,  # type: ignore[arg-type]
            validator_results=validators,
            stable_reason_codes=reasons,
            payload_digest=payload_digest,
            recorded_at=_utc_text(terminal_at),
            candidate_attempt_id=candidate_attempt_id,
            rejected_title=None if rejected_copy is None else rejected_copy.title,
            rejected_body=None if rejected_copy is None else rejected_copy.body,
        )
        retain_draft_outcome(unpublished, record)
        append_ledger(unpublished, "DRAFT_OUTCOME", record.as_record())
        draft_counts[result] += 1
        draft_reasons.update(reasons)
        if model_usage is not None and usage_envelope_id is not None:
            model_usage.record_work_outcome(
                envelope_id=usage_envelope_id,
                outcome=result,
                outcome_record_id=record.outcome_id,
                payload_digest=payload_digest,
                terminal_at=terminal_at,
                accepted_provider_attempt_id=(
                    provider_attempt_ids[-1]
                    if result == "ACCEPTED" and provider_attempt_ids
                    else None
                ),
                stable_reason_codes=reasons,
                connection=unpublished,
            )

    for candidate, package, decision, _selection in selected:
        if minted >= min(max_writes, 5) or writer_circuit_reason or no_useful_reason:
            break
        if provider_dispatches >= max_writer_provider_dispatches:
            break
        candidate_attempts += 1
        candidate_attempt_id = reserve_write_candidate_attempt(
            unpublished,
            cycle_execution_id=cycle_execution_id,
            decision_id=decision.decision_id,
            candidate_id=candidate.candidate_id,
            evidence_package_digest=package.digest,
            ordinal=candidate_attempts,
        )
        append_ledger(
            unpublished,
            "WRITE_CANDIDATE_ATTEMPT_RESERVED",
            {
                "candidate_attempt_id": candidate_attempt_id,
                "decision_id": decision.decision_id,
                "candidate_id": candidate.candidate_id,
                "evidence_package_digest": package.digest,
                "ordinal": candidate_attempts,
            },
        )
        unpublished.commit()
        provider_attempt_ids: list[str] = []
        usage_invocation_ids: list[str] = []
        validators: tuple[WriterValidatorResult, ...] = ()
        accepted_copy: WriterCopy | None = None
        last_rejected_copy: WriterCopy | None = None
        last_reason = "NO_USEFUL_OUTPUT"
        candidate_hold_reason = ""
        usage_envelope_id: str | None = None
        if model_usage is not None:
            usage_envelope = WorkEnvelope.create(
                cycle_id=cycle_execution_id,
                workload_class=WorkloadClass.CONT_WRITER_PRIMARY,
                admitted_at=_parse_utc(selected_at),
                admission_decision_id=decision.decision_id,
                candidate_id=candidate.candidate_id,
                hypothesis_digest=digest_bytes(
                    canonical_json_bytes({"hypothesis_id": candidate.hypothesis_id})
                ),
                evidence_package_digest=package.digest,
                ingest_id=None,
                graphiti_attempt_id=None,
            )
            model_usage.open_envelope(usage_envelope)
            usage_envelope_id = usage_envelope.envelope_id

        for route in ("PRIMARY", "FALLBACK"):
            if route == "FALLBACK":
                if fallback_dispatches >= max_writer_fallback_dispatches:
                    last_reason = "FALLBACK_BUDGET_EXHAUSTED"
                    break
                if provider_dispatches >= max_writer_provider_dispatches:
                    last_reason = "PROVIDER_BUDGET_EXHAUSTED"
                    break
            if writer_dispatch_fence is not None:
                try:
                    writer_dispatch_fence()
                except VetoError:
                    outcome(
                        decision=decision,
                        candidate_attempt_id=candidate_attempt_id,
                        provider_attempt_ids=tuple(provider_attempt_ids),
                        result="HOLD",
                        validators=validators,
                        reasons=("OWNER_EMERGENCY_STOP",),
                        usage_envelope_id=usage_envelope_id,
                    )
                    unpublished.commit()
                    raise
            usage_allocation: InvocationAllocation | None = None
            usage_policy: InvocationEfficiencyPolicy | None = None
            usage_dispatch_at: datetime | None = None
            if model_usage is not None:
                manifest_method = getattr(writer, "invocation_manifest", None)
                if not callable(manifest_method):
                    last_reason = "MODEL_USAGE_CONTRACT_UNAVAILABLE"
                    break
                manifest = cast(
                    WriterInvocationManifest,
                    manifest_method(candidate, package, route=route),
                )
                workload_class = (
                    WorkloadClass.CONT_WRITER_PRIMARY
                    if route == "PRIMARY"
                    else WorkloadClass.CONT_WRITER_FALLBACK
                )
                try:
                    # End any read transaction before the shared usage
                    # authority takes its pre-dispatch write claim.
                    unpublished.commit()
                    model_usage.retain_context_manifest(manifest.as_record())
                    usage_policy = model_usage.qualified_policy(
                        workload_class=workload_class,
                        provider=manifest.provider,
                        route=manifest.route,
                        model=manifest.model,
                        reasoning=manifest.reasoning,
                        candidate_id=candidate.candidate_id,
                        implementation_revision=manifest.implementation_revision,
                        config_identity=manifest.config_identity,
                    )
                    manifest_controls = (
                        manifest.one_turn,
                        manifest.exact_input,
                        manifest.skills_enabled,
                        manifest.tools_enabled,
                        manifest.mcp_enabled,
                        manifest.prior_message_count,
                    )
                    policy_controls = (
                        usage_policy.one_turn,
                        usage_policy.exact_input,
                        usage_policy.skills_enabled,
                        usage_policy.tools_enabled,
                        usage_policy.mcp_enabled,
                        usage_policy.prior_message_count,
                    )
                    if manifest_controls != policy_controls:
                        raise ModelUsageAdmissionError(
                            "writer invocation controls do not match qualified policy"
                        )
                    if usage_policy.command_semantic_version != "UNSPECIFIED" and (
                        manifest.schema_version
                        != usage_policy.context_manifest_schema_version
                        or manifest.command_semantic_version
                        != usage_policy.command_semantic_version
                        or manifest.command_flags != usage_policy.command_flags
                        or manifest.disabled_capabilities
                        != usage_policy.disabled_capabilities
                        or manifest.implementation_revision
                        != usage_policy.implementation_revision
                        or manifest.implementation_worktree_clean is not True
                    ):
                        raise ModelUsageAdmissionError(
                            "writer manifest contract does not match qualified policy"
                        )
                    allocated_at = clock().astimezone(UTC)
                    usage_allocation = InvocationAllocation.create(
                        envelope_id=usage_envelope_id,
                        cycle_id=cycle_execution_id,
                        leaf_ordinal=len(provider_attempt_ids) + 1,
                        workload_class=workload_class,
                        invocation_policy_digest=usage_policy.canonical_digest,
                        provider=manifest.provider,
                        route=manifest.route,
                        model=manifest.model,
                        reasoning=manifest.reasoning,
                        prompt_contract_version=manifest.prompt_contract_version,
                        prompt_bytes=manifest.prompt_bytes,
                        prompt_digest=manifest.prompt_digest,
                        request_digest=manifest.request_digest,
                        output_schema_digest=manifest.output_schema_digest,
                        max_output_tokens=usage_policy.max_output_tokens,
                        context_manifest_digest=manifest.context_manifest_digest,
                        context_identity=manifest.context_identity,
                        config_identity=manifest.config_identity,
                        one_turn=manifest.one_turn,
                        exact_input=manifest.exact_input,
                        skills_enabled=manifest.skills_enabled,
                        tools_enabled=manifest.tools_enabled,
                        mcp_enabled=manifest.mcp_enabled,
                        prior_message_count=manifest.prior_message_count,
                        allocated_at=allocated_at,
                        recovery_deadline_at=allocated_at + timedelta(minutes=6),
                        parent_invocation_id=(
                            None
                            if not usage_invocation_ids
                            else usage_invocation_ids[0]
                        ),
                    )
                    model_usage.allocate(
                        usage_allocation, owner_emergency_stop=False
                    )
                    usage_invocation_ids.append(usage_allocation.invocation_id)
                except ModelUsageAdmissionError as exc:
                    last_reason = exc.reason_code
                    if exc.reason_code == "EXACT_INPUT_EXCEEDS_QUALIFIED_BOUND":
                        candidate_hold_reason = exc.reason_code
                    else:
                        writer_circuit_reason = exc.reason_code
                    break
            provider_dispatches += 1
            if route == "PRIMARY":
                primary_dispatches += 1
            else:
                fallback_dispatches += 1
            provider_attempt_id = reserve_writer_provider_attempt(
                unpublished,
                candidate_attempt_id=candidate_attempt_id,
                route=route,
                ordinal=provider_dispatches,
            )
            if model_usage is not None and usage_allocation is not None:
                model_usage.link_provider_attempt(
                    invocation_id=usage_allocation.invocation_id,
                    provider_attempt_id=provider_attempt_id,
                    linked_at=clock().astimezone(UTC),
                    connection=unpublished,
                )
            provider_attempt_ids.append(provider_attempt_id)
            append_ledger(
                unpublished,
                "WRITER_PROVIDER_DISPATCH_RESERVED",
                {
                    "provider_attempt_id": provider_attempt_id,
                    "candidate_attempt_id": candidate_attempt_id,
                    "route": route,
                    "ordinal": provider_dispatches,
                },
            )
            unpublished.commit()
            if model_usage is not None and usage_allocation is not None:
                usage_dispatch_at = clock().astimezone(UTC)
            try:
                if writer_owner_stop_fence is None:
                    copy = _dispatch_writer(
                        writer,
                        candidate,
                        package,
                        route=route,
                    )
                else:
                    with writer_owner_stop_fence():
                        copy = _dispatch_writer(
                            writer,
                            candidate,
                            package,
                            route=route,
                        )
                if model_usage is not None and usage_allocation is not None:
                    model_usage.observe_transport(
                        invocation_id=usage_allocation.invocation_id,
                        observed_at=cast(datetime, usage_dispatch_at),
                        state="DISPATCH_STARTED",
                        evidence_digest=digest_bytes(
                            canonical_json_bytes(
                                {
                                    "provider_attempt_id": provider_attempt_id,
                                    "route": route,
                                    "request_digest": usage_allocation.request_digest,
                                }
                            )
                        ),
                    )
            except VetoError:
                if model_usage is not None and usage_allocation is not None:
                    _complete_writer_usage(
                        model_usage,
                        usage_allocation,
                        outcome="VETOED_BEFORE_PROVIDER_DISPATCH",
                        failure_class="OWNER_EMERGENCY_STOP",
                        usage=None,
                        dispatch_at=None,
                        completed_at=clock().astimezone(UTC),
                        provider_dispatched=False,
                        policy=cast(InvocationEfficiencyPolicy, usage_policy),
                    )
                complete_writer_provider_attempt(
                    unpublished,
                    provider_attempt_id=provider_attempt_id,
                    status="FAILED",
                    reason_code="OWNER_EMERGENCY_STOP",
                )
                outcome(
                    decision=decision,
                    candidate_attempt_id=candidate_attempt_id,
                    provider_attempt_ids=tuple(provider_attempt_ids),
                    result="HOLD",
                    validators=validators,
                    reasons=("OWNER_EMERGENCY_STOP",),
                    usage_envelope_id=usage_envelope_id,
                )
                unpublished.commit()
                raise
            except WriterDispatchError as exc:
                if model_usage is not None and usage_allocation is not None:
                    if exc.provider_dispatched:
                        model_usage.observe_transport(
                            invocation_id=usage_allocation.invocation_id,
                            observed_at=cast(datetime, usage_dispatch_at),
                            state="DISPATCH_STARTED",
                            evidence_digest=digest_bytes(
                                canonical_json_bytes(
                                    {
                                        "provider_attempt_id": provider_attempt_id,
                                        "route": route,
                                        "request_digest": usage_allocation.request_digest,
                                    }
                                )
                            ),
                        )
                    completed_at = clock().astimezone(UTC)
                    _complete_writer_usage(
                        model_usage,
                        usage_allocation,
                        outcome="FAILED",
                        failure_class=exc.reason_code,
                        usage=exc.usage,
                        dispatch_at=usage_dispatch_at,
                        completed_at=completed_at,
                        provider_dispatched=exc.provider_dispatched,
                        policy=cast(InvocationEfficiencyPolicy, usage_policy),
                    )
                    if not exc.provider_dispatched:
                        provider_dispatches -= 1
                        if route == "PRIMARY":
                            primary_dispatches -= 1
                        else:
                            fallback_dispatches -= 1
                complete_writer_provider_attempt(
                    unpublished,
                    provider_attempt_id=provider_attempt_id,
                    status="FAILED",
                    reason_code=exc.reason_code,
                )
                last_reason = exc.reason_code
                if exc.failure_class == "SYSTEMIC":
                    writer_circuit_reason = exc.reason_code
                    break
                if route == "PRIMARY" and exc.failure_class == "FALLBACK_ELIGIBLE":
                    continue
                break
            validators = validate_writer_copy(copy, package)
            failed = tuple(item.reason_code for item in validators if item.result == "FAIL")
            if model_usage is not None and usage_allocation is not None:
                completed_at = clock().astimezone(UTC)
                telemetry_missing = (
                    copy.usage is None
                    or copy.usage.get("usage_basis") != "PROVIDER_REPORTED"
                )
                _complete_writer_usage(
                    model_usage,
                    usage_allocation,
                    outcome=("REJECTED_OUTPUT" if failed else "ACCEPTED_OUTPUT"),
                    failure_class=(
                        failed[0]
                        if failed
                        else "MISSING_PROVIDER_TELEMETRY"
                        if telemetry_missing
                        else None
                    ),
                    usage=copy.usage,
                    dispatch_at=usage_dispatch_at,
                    completed_at=completed_at,
                    policy=cast(InvocationEfficiencyPolicy, usage_policy),
                )
            if failed:
                complete_writer_provider_attempt(
                    unpublished,
                    provider_attempt_id=provider_attempt_id,
                    status="REJECTED_OUTPUT",
                    reason_code=failed[0],
                )
                last_reason = failed[0]
                last_rejected_copy = copy
                if route == "PRIMARY":
                    continue
                break
            complete_writer_provider_attempt(
                unpublished,
                provider_attempt_id=provider_attempt_id,
                status="COMPLETE",
                reason_code="VALIDATED_DRAFT",
            )
            accepted_copy = copy
            break

        if accepted_copy is None:
            result = (
                "HOLD"
                if writer_circuit_reason or candidate_hold_reason
                else "REJECT"
            )
            outcome(
                decision=decision,
                candidate_attempt_id=candidate_attempt_id,
                provider_attempt_ids=tuple(provider_attempt_ids),
                result=result,
                validators=validators,
                reasons=(last_reason,),
                usage_envelope_id=usage_envelope_id,
                rejected_copy=last_rejected_copy,
            )
            if not writer_circuit_reason and not candidate_hold_reason:
                no_useful_reason = last_reason
            unpublished.commit()
            continue

        payload = UnpublishedSurfacePayload(
            payload_kind="unpublished_surface_payload",
            publication_bundle=False,
            auto_publish=False,
            language="ZH_HANT_HK",
            title=accepted_copy.title,
            body=accepted_copy.body,
            evidence_package_digest=package.digest,
            story_candidate_id=candidate.candidate_id,
            event_hypothesis_id=candidate.hypothesis_id,
            source_lineage=tuple(sorted({item.source_id for item in candidate.items})),
            generated_at=_now(),
            status="UNPUBLISHED",
            writer_id=accepted_copy.writer_id,
        )
        if insert_payload(unpublished, payload):
            minted += 1
            outcome(
                decision=decision,
                candidate_attempt_id=candidate_attempt_id,
                provider_attempt_ids=tuple(provider_attempt_ids),
                result="ACCEPTED",
                validators=validators,
                reasons=("VALIDATED_AND_INSERTED",),
                payload_digest=_payload_digest(payload),
                usage_envelope_id=usage_envelope_id,
            )
        else:
            duplicate += 1
            outcome(
                decision=decision,
                candidate_attempt_id=candidate_attempt_id,
                provider_attempt_ids=tuple(provider_attempt_ids),
                result="HOLD",
                validators=validators,
                reasons=("DUPLICATE_INSERT_RACE",),
                usage_envelope_id=usage_envelope_id,
            )
        unpublished.commit()

    return _WriteLoopResult(
        minted=minted,
        duplicate=duplicate,
        selected=len(selected),
        candidate_attempts=candidate_attempts,
        provider_dispatches=provider_dispatches,
        primary_dispatches=primary_dispatches,
        fallback_dispatches=fallback_dispatches,
        draft_counts=tuple(sorted(draft_counts.items())),
        draft_reasons=tuple(sorted(draft_reasons.items())),
        writer_circuit_open=bool(writer_circuit_reason),
        writer_circuit_open_reason=writer_circuit_reason,
        no_useful_output_circuit_open=bool(no_useful_reason),
        no_useful_output_circuit_open_reason=no_useful_reason,
        candidate_budget_exhausted=(
            min(max_write_ready_candidates, 5) > 0
            and candidate_attempts >= min(max_write_ready_candidates, 5)
        ),
        provider_budget_exhausted=(
            max_writer_provider_dispatches > 0
            and provider_dispatches >= max_writer_provider_dispatches
        ),
        fallback_budget_exhausted=(
            max_writer_fallback_dispatches > 0
            and fallback_dispatches >= max_writer_fallback_dispatches
        ),
        write_budget_exhausted=(
            min(max_writes, 5) > 0 and minted >= min(max_writes, 5)
        ),
    )


def _graphiti_dispatch_controls(
    proving_store: str,
    *,
    clock: Callable[[], datetime],
    max_dispatch_seconds: float | None = None,
) -> tuple[
    Callable[[CorpusIngestUnit], dict[str, object] | None],
    Callable[[CorpusIngestUnit], ContextManager[_DispatchAuthority | None]],
]:
    fixed_timeout_seconds = GRAPHITI_EXTRACTION_TIMEOUT_MS / 1_000
    if max_dispatch_seconds is None:
        dispatch_seconds = fixed_timeout_seconds
    elif (
        isinstance(max_dispatch_seconds, bool)
        or not isinstance(max_dispatch_seconds, (int, float))
        or not math.isfinite(float(max_dispatch_seconds))
        or max_dispatch_seconds <= 0
    ):
        raise ValueError(
            "maximum Graphiti dispatch seconds must be finite and positive"
        )
    else:
        dispatch_seconds = min(float(max_dispatch_seconds), fixed_timeout_seconds)

    fixed_deadline = (
        None
        if max_dispatch_seconds is None
        else clock().astimezone(UTC) + timedelta(seconds=dispatch_seconds)
    )

    def deadline_for(evaluated_at: datetime) -> datetime:
        return fixed_deadline or evaluated_at + timedelta(seconds=dispatch_seconds)

    def rights_check(unit: CorpusIngestUnit) -> dict[str, object] | None:
        current = sqlite3.connect(proving_store)
        apply_control_plane_sqlite_profile(current, query_only=True)
        try:
            evaluated_at = clock().astimezone(UTC)
            if fixed_deadline is not None and evaluated_at >= fixed_deadline:
                return None
            return _dispatch_rights_decision(
                current,
                source_id=unit.source_id,
                source_url=unit.source_definition_url,
                evaluated_at=_utc_text(evaluated_at),
                required_valid_until=_utc_text(deadline_for(evaluated_at)),
            )
        finally:
            current.close()

    @contextmanager
    def rights_fence(
        unit: CorpusIngestUnit,
    ) -> Iterator[_DispatchAuthority | None]:
        timeout_ms = max(1, int(_PROVING_FENCE_TIMEOUT_SECONDS * 1_000))
        current = sqlite3.connect(proving_store, timeout=_PROVING_FENCE_TIMEOUT_SECONDS)
        apply_control_plane_sqlite_profile(
            current, wal=None, busy_timeout_ms=timeout_ms
        )
        fence_active = False
        try:
            try:
                current.execute("BEGIN IMMEDIATE")
                _assert_owner_emergency_stop_clear(current)
            except sqlite3.OperationalError as exc:
                raise _ProvingFenceUnavailable(
                    "proving writer fence was unavailable"
                ) from exc
            fence_active = True

            def prove_owner_stop_clear() -> None:
                # BEGIN IMMEDIATE excludes any proving-gate writer. Rechecking
                # this active fence therefore proves the PASS row read above
                # without attempting a self-deadlocking second transaction.
                if not fence_active:
                    raise VetoError(
                        "Graphiti owner emergency-stop fence is no longer active"
                    )

            evaluated_at = clock().astimezone(UTC)
            deadline = deadline_for(evaluated_at)
            decision = (
                None
                if fixed_deadline is not None and evaluated_at >= fixed_deadline
                else _dispatch_rights_decision(
                    current,
                    source_id=unit.source_id,
                    source_url=unit.source_definition_url,
                    evaluated_at=_utc_text(evaluated_at),
                    required_valid_until=_utc_text(deadline),
                )
            )
            yield (
                None
                if decision is None
                else _DispatchAuthority(
                    rights=decision,
                    deadline=deadline,
                    owner_stop_check=prove_owner_stop_clear,
                )
            )
        finally:
            fence_active = False
            if current.in_transaction:
                current.rollback()
            current.close()

    return rights_check, rights_fence


def _resolve_graphiti_event_units(
    *,
    proving_store: str,
    event: GraphitiRevisionEvent,
    evaluated_at: datetime,
) -> tuple[CorpusIngestUnit, ...]:
    units = load_graphiti_units(
        proving_store=proving_store,
        evaluated_at=evaluated_at,
    )
    selected = tuple(
        unit
        for unit in units
        if (
            unit.source_id,
            unit.item_key,
            unit.revision_digest,
            unit.published_at or "",
            unit.updated_at or "",
        )
        == (
            event.source_id,
            event.item_key,
            event.revision_digest,
            event.published_at,
            event.updated_at,
        )
    )
    if event.unit_refs:
        expected_refs = tuple(
            (
                ref.get("ingest_id"),
                ref.get("chunk_digest"),
                ref.get("chunk_ordinal"),
                ref.get("predecessor_ingest_id"),
            )
            for ref in event.unit_refs
        )
        actual_refs = tuple(
            (
                unit.ingest_id,
                unit.digest,
                unit.chunk_ordinal,
                unit.predecessor_ingest_id,
            )
            for unit in selected
        )
        if actual_refs != expected_refs:
            return ()
    return selected


def load_graphiti_units(
    *,
    proving_store: str,
    evaluated_at: datetime,
) -> tuple[CorpusIngestUnit, ...]:
    """Resolve current rights-permitted Graphiti units without queue effects."""

    proving = sqlite3.connect(proving_store)
    apply_control_plane_sqlite_profile(proving, query_only=True)
    try:
        return load_graphiti_units_from_connection(
            proving,
            evaluated_at=evaluated_at,
        )
    finally:
        proving.close()


def load_graphiti_units_from_connection(
    proving: sqlite3.Connection,
    *,
    evaluated_at: datetime,
) -> tuple[CorpusIngestUnit, ...]:
    """Resolve current rights-permitted units from an existing read-only view."""

    collected: list[CorpusIngestUnit] = []
    _run_id, _latest, corpus_rows = _permitted_rows(
        proving,
        evaluated_at=_utc_text(evaluated_at),
        required_valid_until=_dispatch_valid_until(evaluated_at),
    )
    resolver = EffectiveRevisionIdentityResolver(proving)
    for row in corpus_rows:
        collected.extend(
            units_from(
                _parsed_observations((row,)),
                proving_run_id=row.run_id,
                rights_authority_run_id=row.rights_authority_run_id,
                rights_gate_id=row.rights_gate_id,
                rights_gate_reason=row.rights_gate_reason,
                source_definition_url=row.url,
                effective_revision_resolver=resolver,
            )
        )
    return unique_chunk_units(tuple(collected))


def qualify_fresh_graphiti_event(
    *,
    proving_store: str,
    unpublished_store: str,
    event_id: str,
    ledger_seq: int,
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
) -> dict[str, object]:
    """Resolve current input and rights for one untouched event without writes."""

    evaluated_at = clock().astimezone(UTC)
    unpublished = sqlite3.connect(
        f"{Path(unpublished_store).absolute().as_uri()}?mode=ro",
        uri=True,
    )
    apply_control_plane_sqlite_profile(unpublished, query_only=True)
    try:
        row = unpublished.execute(
            "SELECT event_id,ledger_seq,source_id,item_key,revision_digest,"
            "published_at,updated_at,unit_count,manifest_json,manifest_digest,"
            "state,attempt_count,available_at,claim_owner,claim_expires_at,"
            "ledger_digest "
            "FROM unpublished_graphiti_revision_events "
            "WHERE event_id=? AND ledger_seq=?",
            (event_id, ledger_seq),
        ).fetchone()
        retry_excluded = graphiti_retry_excluded(
            unpublished,
            event_id=event_id,
        )
    finally:
        unpublished.close()
    if retry_excluded:
        raise ValueError("bounded Graphiti event is durably retry-excluded")
    if (
        row is None
        or str(row[10]) != "QUEUED"
        or int(row[11]) != 0
        or str(row[12]) > _utc_text(evaluated_at)
        or row[13] is not None
        or row[14] is not None
    ):
        raise ValueError("bounded Graphiti event is not fresh and claimable")
    try:
        manifest = json.loads(str(row[8]))
    except json.JSONDecodeError as exc:
        raise ValueError("bounded Graphiti event manifest is malformed") from exc
    if (
        not isinstance(manifest, dict)
        or digest_canonical(manifest) != str(row[9])
        or manifest.get("ledger_seq") != int(row[1])
        or manifest.get("ledger_digest") != str(row[15])
    ):
        raise ValueError("bounded Graphiti event manifest differs")
    unit_refs = manifest.get("unit_refs")
    landed_ingest_ids = manifest.get("landed_ingest_ids")
    landed_payload_digest = manifest.get("landed_payload_digest")
    if (
        not isinstance(unit_refs, list)
        or not all(isinstance(item, dict) for item in unit_refs)
        or not isinstance(landed_ingest_ids, list)
        or not all(isinstance(item, str) for item in landed_ingest_ids)
        or not isinstance(landed_payload_digest, str)
    ):
        raise ValueError("bounded Graphiti event object is malformed")
    event = GraphitiRevisionEvent(
        event_id=str(row[0]),
        ledger_seq=int(row[1]),
        source_id=str(row[2]),
        item_key=str(row[3]),
        revision_digest=str(row[4]),
        published_at=str(row[5]),
        updated_at=str(row[6]),
        expected_unit_count=int(row[7]),
        landed_ingest_ids=tuple(landed_ingest_ids),
        landed_payload_digest=landed_payload_digest,
        unit_refs=tuple(unit_refs),
        state="QUEUED",
        attempt_count=0,
        units=(),
    )
    units = _resolve_graphiti_event_units(
        proving_store=proving_store,
        event=event,
        evaluated_at=evaluated_at,
    )
    if not units:
        raise ValueError("bounded Graphiti event canonical input is unavailable")
    proving = sqlite3.connect(proving_store)
    apply_control_plane_sqlite_profile(proving, query_only=True)
    try:
        _assert_owner_emergency_stop_clear(proving)
    finally:
        proving.close()
    rights_check, _rights_fence = _graphiti_dispatch_controls(
        proving_store,
        clock=lambda: evaluated_at,
    )
    rights_decisions = tuple(rights_check(unit) for unit in units)
    if any(decision is None for decision in rights_decisions):
        raise ValueError("bounded Graphiti event lacks current dispatch rights")
    binding_reason = graphiti_unit_binding_reason(event, units)
    if binding_reason is not None:
        raise ValueError(binding_reason)
    evidence_without_digest: dict[str, object] = {
        "schema_version": "newsroom.graphiti-fresh-event-preflight.v1",
        "event_id": event.event_id,
        "ledger_seq": event.ledger_seq,
        "ledger_digest": str(row[15]),
        "event_state": event.state,
        "event_attempt_count": event.attempt_count,
        "event_manifest_digest": str(row[9]),
        "resolved_units": [
            {
                "ingest_id": unit.ingest_id,
                "revision_id": unit.revision_id,
                "representation_digest": unit.representation_digest,
                "chunk_digest": unit.digest,
                "chunk_ordinal": unit.chunk_ordinal,
                "predecessor_ingest_id": unit.predecessor_ingest_id,
            }
            for unit in units
        ],
        # ``evaluated_at`` proves when the decision was checked, but is not
        # part of the underlying rights authority.  Keeping it outside these
        # digests lets a prepared canary bind the same still-valid authority
        # when the live command rechecks it at a later instant.
        "rights_decision_digests": [
            digest_canonical(
                {
                    key: value
                    for key, value in decision.items()
                    if key != "evaluated_at"
                }
            )
            for decision in rights_decisions
            if decision is not None
        ],
        "owner_emergency_stop_clear": True,
        "provider_calls": 0,
        "store_mutations": 0,
        "evaluated_at": _utc_text(evaluated_at),
    }
    return {
        **evidence_without_digest,
        "evidence_digest": digest_canonical(evidence_without_digest),
    }


def consume_next_graphiti_event(
    *,
    proving_store: str,
    unpublished_store: str,
    graphiti: GraphitiPort,
    owner_id: str,
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    model_usage: ModelUsageService | None = None,
    event_id: str | None = None,
    require_fresh: bool = False,
    recover_model_usage: bool = True,
    canary_consumption_digest: str | None = None,
    max_dispatch_seconds: float | None = None,
    prepared_event_preflight: Mapping[str, object] | None = None,
    max_reserved_gbp_microunits: int | None = None,
) -> GraphitiProcessResult | None:
    """Claim and process one durable revision, independently from source polling."""

    if max_reserved_gbp_microunits is not None and (
        isinstance(max_reserved_gbp_microunits, bool)
        or not isinstance(max_reserved_gbp_microunits, int)
        or max_reserved_gbp_microunits <= 0
    ):
        raise ValueError("maximum Graphiti reserved spend must be positive")
    if prepared_event_preflight is not None:
        if event_id is None or canary_consumption_digest is not None:
            raise ValueError("prepared Graphiti preflight requires one exact event")
        prepared = dict(prepared_event_preflight)
        supplied_digest = prepared.pop("evidence_digest", None)
        if (
            supplied_digest != digest_canonical(prepared)
            or prepared.get("schema_version")
            != "newsroom.graphiti-fresh-event-preflight.v1"
            or prepared.get("event_id") != event_id
            or not isinstance(prepared.get("ledger_digest"), str)
            or not prepared.get("ledger_digest")
            or isinstance(prepared.get("ledger_seq"), bool)
            or not isinstance(prepared.get("ledger_seq"), int)
            or prepared.get("event_state") != "QUEUED"
            or prepared.get("event_attempt_count") != 0
            or not isinstance(prepared.get("event_manifest_digest"), str)
            or prepared.get("owner_emergency_stop_clear") is not True
            or prepared.get("provider_calls") != 0
            or prepared.get("store_mutations") != 0
            or not isinstance(prepared.get("resolved_units"), list)
            or not prepared["resolved_units"]
        ):
            raise ValueError("prepared Graphiti preflight differs")

    if isinstance(graphiti, GovernedRealGraphitiPort) and getattr(
        graphiti, "requires_canonical_control_plane_stores", True
    ):
        require_canonical_proving_store(proving_store)
        require_canonical_unpublished_store(unpublished_store)
        if model_usage is None:
            model_usage = ModelUsageService(unpublished_store)
        if recover_model_usage:
            model_usage.recover_unresolved(observed_at=clock().astimezone(UTC))
    rights_check, rights_fence = _graphiti_dispatch_controls(
        proving_store,
        clock=clock,
        max_dispatch_seconds=max_dispatch_seconds,
    )
    queue = GraphitiEventQueue(unpublished_store, clock=clock)
    resolved_units: dict[str, tuple[CorpusIngestUnit, ...]] = {}
    required_preflight: Mapping[str, object] | None = prepared_event_preflight
    preflight_drift_reason = "PREPARED_EVENT_INPUT_DRIFT"
    if canary_consumption_digest is not None:
        if event_id is None:
            raise ValueError("bounded canary requires an exact event")
        required_preflight = Issue790CanaryRepository.open_existing(
            unpublished_store
        ).preflight_for_consumption(
            consumption_digest=canary_consumption_digest,
            event_id=event_id,
            owner_id=owner_id,
        )
        preflight_drift_reason = "CANARY_PREFLIGHT_INPUT_DRIFT"

    def units_for(event: GraphitiRevisionEvent) -> tuple[CorpusIngestUnit, ...]:
        cached = resolved_units.get(event.event_id)
        if cached is not None:
            return cached
        selected = _resolve_graphiti_event_units(
            proving_store=proving_store,
            event=event,
            evaluated_at=clock().astimezone(UTC),
        )
        resolved_units[event.event_id] = selected
        return selected

    def gate(event: GraphitiRevisionEvent) -> GraphitiDispatchGate:
        units = units_for(event)
        if not units:
            return GraphitiDispatchGate.hold("CANONICAL_INPUT_UNAVAILABLE")
        if required_preflight is not None:
            retained = sqlite3.connect(
                f"{Path(unpublished_store).absolute().as_uri()}?mode=ro",
                uri=True,
            )
            apply_control_plane_sqlite_profile(retained, query_only=True)
            try:
                current_identity = retained.execute(
                    "SELECT ledger_seq,ledger_digest,manifest_digest "
                    "FROM unpublished_graphiti_revision_events WHERE event_id=?",
                    (event.event_id,),
                ).fetchone()
            finally:
                retained.close()
            expected = required_preflight.get("resolved_units")
            actual = [
                {
                    "ingest_id": unit.ingest_id,
                    "revision_id": unit.revision_id,
                    "representation_digest": unit.representation_digest,
                    "chunk_digest": unit.digest,
                    "chunk_ordinal": unit.chunk_ordinal,
                    "predecessor_ingest_id": unit.predecessor_ingest_id,
                }
                for unit in units
            ]
            if (
                current_identity is None
                or required_preflight.get("event_id") != event.event_id
                or required_preflight.get("ledger_seq") != event.ledger_seq
                or int(current_identity[0]) != event.ledger_seq
                or (
                    "ledger_digest" in required_preflight
                    and required_preflight.get("ledger_digest")
                    != str(current_identity[1])
                )
                or required_preflight.get("event_manifest_digest")
                != str(current_identity[2])
                or expected != actual
            ):
                return GraphitiDispatchGate.hold(preflight_drift_reason)
        if (
            max_reserved_gbp_microunits is not None
            and len(units) * GRAPHITI_UNIT_RESERVATION_GBP_MICROUNITS
            > max_reserved_gbp_microunits
        ):
            return GraphitiDispatchGate.hold("RESERVED_SPEND_BOUND_EXCEEDED")
        for unit in units:
            if rights_check(unit) is None:
                return GraphitiDispatchGate.hold("NO_CURRENT_DISPATCH_RIGHTS")
        binding_reason = graphiti_unit_binding_reason(event, units)
        if binding_reason is not None:
            return GraphitiDispatchGate.hold(binding_reason)
        queue.bind_resolved_units(event, owner_id=owner_id, units=units)
        return GraphitiDispatchGate.allow()

    def dispatch(event: GraphitiRevisionEvent) -> GraphitiDispatchResult:
        event = replace(event, units=units_for(event))
        unpublished = connect(unpublished_store)
        try:
            ingest_ids = tuple(unit.ingest_id for unit in event.units)
            provider_dispatched = False

            def committed_provider_dispatch() -> bool:
                return bool(
                    model_usage is not None
                    and model_usage.has_committed_provider_dispatch(
                        cycle_id=event.event_id
                    )
                )

            def systemic_failure(code: str, _dispatched: bool) -> None:
                dispatched = committed_provider_dispatch()
                if code == "CLI_PREDISPATCH_CONFIGURATION_REFUSED":
                    raise ConfigurationGraphitiEventFailure(
                        code, provider_dispatched=dispatched
                    )
                raise SystemicGraphitiEventFailure(
                    code, provider_dispatched=dispatched
                )

            # _queue() exposes only the next predecessor-qualified chunk. Keep
            # one revision attempt bounded while draining its ordered chunks.
            for _chunk in event.units:
                attempted = _ingest(
                    unpublished,
                    graphiti=graphiti,
                    units=event.units,
                    max_graphiti=1,
                    rights_check=rights_check,
                    rights_fence=rights_fence,
                    clock=clock,
                    on_systemic_failure=systemic_failure,
                    model_usage=model_usage,
                    cycle_id=event.event_id,
                )
                provider_dispatched = (
                    provider_dispatched or committed_provider_dispatch()
                )
                if all(has_graphiti_ingest(unpublished, item) for item in ingest_ids):
                    placeholders = ",".join("?" for _ in ingest_ids)
                    proposal_count = int(
                        unpublished.execute(
                            f"SELECT COALESCE(SUM(proposal_count),0) "
                            f"FROM unpublished_graphiti_ingest "
                            f"WHERE ingest_id IN ({placeholders})",
                            ingest_ids,
                        ).fetchone()[0]
                    )
                    return GraphitiDispatchResult.terminal(
                        proposal_count=proposal_count,
                        provider_dispatched=provider_dispatched,
                    )
                failure_rows = list(
                    unpublished.execute(
                        f"""
                        SELECT dead_lettered,last_failure_code
                        FROM unpublished_graphiti_failures
                        WHERE ingest_id IN ({",".join("?" for _ in ingest_ids)})
                        ORDER BY at DESC
                        """,
                        ingest_ids,
                    )
                )
                if failure_rows:
                    failure_code = str(failure_rows[0][1])
                    if any(bool(row[0]) for row in failure_rows):
                        return GraphitiDispatchResult.dead_letter(
                            failure_code=failure_code,
                            provider_dispatched=provider_dispatched,
                        )
                    return GraphitiDispatchResult.retry_held(
                        failure_code=failure_code,
                        provider_dispatched=provider_dispatched,
                    )
                if attempted == 0:
                    break
            return GraphitiDispatchResult.retry_held(
                failure_code="DISPATCH_INCOMPLETE",
                provider_dispatched=provider_dispatched,
            )
        finally:
            unpublished.close()

    return queue.process_one(
        owner_id=owner_id,
        gate=gate,
        dispatch=dispatch,
        event_id=event_id,
        require_fresh=require_fresh,
        canary_consumption_digest=canary_consumption_digest,
    )


def run_cycle(
    *,
    proving_store: str,
    unpublished_store: str,
    writer: WriterPort,
    max_writes: int = 5,
    graphiti: GraphitiPort | None = None,
    max_graphiti: int = 1,
    graphiti_admission_factory: GraphitiAdmissionFactory | None = None,
    max_graphiti_admissions: int = 100,
    evidence_package_builder: Callable[[StoryCandidateRecord], EvidencePackage]
    | None = None,
    governed_context_builder: Callable[
        [tuple[GroupedObservation, ...]], GovernedContext
    ]
    | None = None,
    max_write_ready_candidates: int = 5,
    max_writer_provider_dispatches: int = 5,
    max_writer_fallback_dispatches: int = 1,
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    cycle_id: str | None = None,
    writer_dispatch_fence: Callable[[], None] | None = None,
    model_usage: ModelUsageService | None = None,
) -> CycleReport:
    if cycle_id is None:
        cycle_id = str(uuid.uuid4())
    else:
        try:
            if str(uuid.UUID(cycle_id)) != cycle_id:
                raise ValueError
        except ValueError as exc:
            raise ValueError("cycle_id must be a canonical UUID") from exc
    for name, value in (
        ("max_writes", max_writes),
        ("max_write_ready_candidates", max_write_ready_candidates),
        ("max_writer_provider_dispatches", max_writer_provider_dispatches),
        ("max_writer_fallback_dispatches", max_writer_fallback_dispatches),
    ):
        if value < 0:
            raise ValueError(f"{name} must be non-negative")
    if (
        isinstance(max_graphiti_admissions, bool)
        or not isinstance(max_graphiti_admissions, int)
        or max_graphiti_admissions <= 0
    ):
        raise ValueError("maximum Graphiti admissions must be positive")
    if evidence_package_builder is None:
        evidence_package_builder = lambda candidate: retained_package_for(
            candidate,
            proving_store=proving_store,
        )
    if isinstance(graphiti, GovernedRealGraphitiPort) and getattr(
        graphiti, "requires_canonical_control_plane_stores", True
    ):
        require_canonical_proving_store(proving_store)
        require_canonical_unpublished_store(unpublished_store)
    assert_private_store(unpublished_store)
    lowered = proving_store.lower()
    if any(marker in lowered for marker in FORBIDDEN_STORE_MARKERS):
        raise ValueError("proving store must not alias production or news_pool")
    admission_evaluated_at = clock().astimezone(UTC)
    _backfill_proving_first_seen(proving_store)
    proving = sqlite3.connect(proving_store)
    apply_control_plane_sqlite_profile(proving, query_only=True)
    try:
        run_id, latest_rows, corpus_rows = _permitted_rows(
            proving,
            evaluated_at=_utc_text(admission_evaluated_at),
            required_valid_until=_dispatch_valid_until(admission_evaluated_at),
        )
    finally:
        proving.close()

    rights_check, rights_fence = _graphiti_dispatch_controls(
        proving_store, clock=clock
    )

    observations = _parsed_observations(latest_rows)
    collected_units: list[CorpusIngestUnit] = []
    proving = sqlite3.connect(proving_store)
    apply_control_plane_sqlite_profile(proving, query_only=True)
    try:
        permitted_source_ids = _rights_permitted_source_ids(
            proving,
            run_id,
            evaluated_at=_utc_text(admission_evaluated_at),
            required_valid_until=_dispatch_valid_until(admission_evaluated_at),
        )
        first_seen = _load_first_seen(proving)
        pull_first_seen = _load_pull_first_seen(proving)
        effective_revision_resolver = EffectiveRevisionIdentityResolver(proving)
        for row in corpus_rows:
            collected_units.extend(
                units_from(
                    _parsed_observations((row,)),
                    proving_run_id=row.run_id,
                    rights_authority_run_id=row.rights_authority_run_id,
                    rights_gate_id=row.rights_gate_id,
                    rights_gate_reason=row.rights_gate_reason,
                    source_definition_url=row.url,
                    effective_revision_resolver=effective_revision_resolver,
                )
            )
    finally:
        proving.close()
    units = unique_chunk_units(tuple(collected_units))
    window_revisions = revisions_from(units)
    poll_observation_count = len(corpus_rows)
    feed_snapshot_item_count = sum(row.item_count for row in latest_rows)
    candidates = form_candidates(
        observations,
        governed_context_builder=governed_context_builder,
    )
    sources = len({row.source_id for row in latest_rows})
    unpublished = connect(unpublished_store)
    ensure_graphiti_event_schema(unpublished)
    graphiti_ok = 0
    admission_policy = DeterministicWriteAdmission()
    admission_counts: Counter[str] = Counter()
    admission_reasons: Counter[str] = Counter()
    decisions: list[
        tuple[StoryCandidateRecord, EvidencePackage, WriteAdmissionDecision]
    ] = []
    write_result = _WriteLoopResult(
        minted=0,
        duplicate=0,
        selected=0,
        candidate_attempts=0,
        provider_dispatches=0,
        primary_dispatches=0,
        fallback_dispatches=0,
        draft_counts=(),
        draft_reasons=(),
        writer_circuit_open=False,
        writer_circuit_open_reason="",
        no_useful_output_circuit_open=False,
        no_useful_output_circuit_open_reason="",
        candidate_budget_exhausted=False,
        provider_budget_exhausted=False,
        fallback_budget_exhausted=False,
        write_budget_exhausted=False,
    )
    try:
        unpublished.execute("BEGIN IMMEDIATE")
        _emit_effective_revision_landed(
            unpublished,
            units,
            first_seen,
            pull_first_seen,
            permitted_source_ids,
        )
        revisions = merge_durable_revisions(
            window_revisions=window_revisions,
            first_seen=first_seen,
            pull_first_seen=pull_first_seen,
            landed=list_landed_revisions(unpublished),
            remapped_effects=list_remapped_ingest_effects(unpublished),
            permitted_source_ids=permitted_source_ids,
        )
        effective_pull_count = len(revisions)
        append_ledger(
            unpublished,
            "PRIVATE_CYCLE_START",
            {
                "proving_run_id": run_id,
                "cycle_id": cycle_id,
                "observations": len(latest_rows),
                "poll_observation_count": poll_observation_count,
                "feed_snapshot_item_count": feed_snapshot_item_count,
                "effective_pull_count": effective_pull_count,
                "candidates": len(candidates),
                "eligible_source_revisions": effective_pull_count,
                "eligible_ingest_chunks": len(units),
                "writer_id": writer.writer_id,
            },
        )
        if graphiti is not None:
            graphiti_ok = _ingest(
                unpublished,
                graphiti=graphiti,
                units=units,
                max_graphiti=max_graphiti,
                rights_check=rights_check,
                rights_fence=rights_fence,
                clock=clock,
                model_usage=model_usage,
                cycle_id=cycle_id,
            )
            unpublished.commit()
        if graphiti_admission_factory is not None:
            admission = graphiti_admission_factory(unpublished)
            admission.enqueue_complete_receipts()
            admission.drain(
                worker_id=f"hermes-cycle:{run_id}",
                limit=max_graphiti_admissions,
            )
            admission.reconcile_rights(limit=max_graphiti_admissions)
            unpublished.commit()
        for candidate in candidates:
            package = evidence_package_builder(candidate)
            decision = admission_policy.decide(
                candidate,
                package,
                decided_at=_utc_text(admission_evaluated_at),
            )
            validate_admission_binding(decision, candidate, package)
            retain_write_admission_decision(unpublished, decision)
            append_ledger(
                unpublished,
                "WRITE_ADMISSION_DECISION",
                decision.as_record(),
            )
            unpublished.commit()
            if model_usage is not None and decision.decision in {"HOLD", "REJECT"}:
                model_usage.retain_zero_call_admission(
                    decision_id=decision.decision_id,
                    decision=decision.decision,
                    cycle_id=cycle_id,
                    recorded_at=admission_evaluated_at,
                )
            decisions.append((candidate, package, decision))
            admission_counts[decision.decision] += 1
            admission_reasons.update(decision.stable_reason_codes)

        def exact_writer_dispatch_fence() -> None:
            if writer_dispatch_fence is not None:
                writer_dispatch_fence()
            assert_no_owner_emergency_stop(proving_store)

        write_result = _run_write_loop(
            unpublished,
            writer=writer,
            admitted=tuple(decisions),
            max_writes=max_writes,
            max_write_ready_candidates=min(max_write_ready_candidates, 5),
            max_writer_provider_dispatches=min(max_writer_provider_dispatches, 5),
            max_writer_fallback_dispatches=min(max_writer_fallback_dispatches, 1),
            selected_at=_utc_text(admission_evaluated_at),
            cycle_execution_id=cycle_id,
            writer_dispatch_fence=exact_writer_dispatch_fence,
            writer_owner_stop_fence=lambda: owner_emergency_stop_fence(
                proving_store
            ),
            model_usage=model_usage,
            clock=clock,
        )
        coverage = graphiti_coverage(
            unpublished,
            revisions=revisions,
            poll_observation_count=poll_observation_count,
            feed_snapshot_item_count=feed_snapshot_item_count,
        )
        record_graphiti_coverage(unpublished, coverage)
        digest = append_ledger(
            unpublished,
            "PRIVATE_CYCLE_CLOSE",
            {
                "proving_run_id": run_id,
                "cycle_id": cycle_id,
                "minted": write_result.minted,
                "duplicate": write_result.duplicate,
                "sources": sources,
                "candidates": len(candidates),
                "candidates_considered": len(candidates),
                "admission_counts": dict(sorted(admission_counts.items())),
                "admission_reason_counts": dict(sorted(admission_reasons.items())),
                "selected_write_ready": write_result.selected,
                "candidate_attempts": write_result.candidate_attempts,
                "provider_dispatches": write_result.provider_dispatches,
                "primary_dispatches": write_result.primary_dispatches,
                "fallback_dispatches": write_result.fallback_dispatches,
                "draft_outcomes": dict(write_result.draft_counts),
                "draft_reason_counts": dict(write_result.draft_reasons),
                "accepted_payload_count": write_result.minted,
                "writer_circuit_open": write_result.writer_circuit_open,
                "writer_circuit_open_reason": write_result.writer_circuit_open_reason,
                "no_useful_output_circuit_open": (
                    write_result.no_useful_output_circuit_open
                ),
                "no_useful_output_circuit_open_reason": (
                    write_result.no_useful_output_circuit_open_reason
                ),
                "candidate_budget_exhausted": write_result.candidate_budget_exhausted,
                "provider_budget_exhausted": write_result.provider_budget_exhausted,
                "fallback_budget_exhausted": write_result.fallback_budget_exhausted,
                "write_budget_exhausted": write_result.write_budget_exhausted,
                "writer_id": writer.writer_id,
                "graphiti": graphiti_ok,
                **coverage,
            },
        )
        unpublished.commit()
    finally:
        unpublished.close()
    draft_counts = dict(write_result.draft_counts)
    return CycleReport(
        cycle_id=cycle_id,
        proving_run_id=run_id,
        minted=write_result.minted,
        duplicate=write_result.duplicate,
        sources=sources,
        candidates=len(candidates),
        ledger_digest=digest,
        writer_id=writer.writer_id,
        graphiti=graphiti_ok,
        eligible=effective_pull_count,
        poll_observation_count=poll_observation_count,
        feed_snapshot_item_count=feed_snapshot_item_count,
        effective_pull_count=effective_pull_count,
        candidates_considered=len(candidates),
        write_ready=admission_counts["WRITE_READY"],
        admission_hold=admission_counts["HOLD"],
        admission_reject=admission_counts["REJECT"],
        selected_write_ready=write_result.selected,
        candidate_attempts=write_result.candidate_attempts,
        provider_dispatches=write_result.provider_dispatches,
        primary_dispatches=write_result.primary_dispatches,
        fallback_dispatches=write_result.fallback_dispatches,
        draft_accepted=draft_counts.get("ACCEPTED", 0),
        draft_hold=draft_counts.get("HOLD", 0),
        draft_reject=draft_counts.get("REJECT", 0),
        accepted_payload_count=write_result.minted,
        writer_circuit_open=write_result.writer_circuit_open,
        writer_circuit_open_reason=write_result.writer_circuit_open_reason,
        no_useful_output_circuit_open=write_result.no_useful_output_circuit_open,
        no_useful_output_circuit_open_reason=(
            write_result.no_useful_output_circuit_open_reason
        ),
        candidate_budget_exhausted=write_result.candidate_budget_exhausted,
        provider_budget_exhausted=write_result.provider_budget_exhausted,
        fallback_budget_exhausted=write_result.fallback_budget_exhausted,
        write_budget_exhausted=write_result.write_budget_exhausted,
        admission_reason_counts=tuple(sorted(admission_reasons.items())),
        draft_reason_counts=write_result.draft_reasons,
    )
