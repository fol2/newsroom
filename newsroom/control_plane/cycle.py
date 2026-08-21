"""Governed unpublished cycle: Signal → Lead → Hypothesis → Candidate → Evidence → write.

Graphiti corpus ingest is independent of CONT writes (GING-001).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Callable, ContextManager, Iterator, TypedDict

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.control_plane.corpus import (
    CorpusIngestUnit,
    revisions_from,
    units_from,
)
from newsroom.control_plane.editorial import GroupedObservation, form_candidates
from newsroom.control_plane.evidence import package_for
from newsroom.control_plane.graphiti import (
    GovernedRealGraphitiPort,
    GraphitiCycleResult,
    GraphitiPort,
)
from newsroom.control_plane.items import parse_observation
from newsroom.control_plane.paths import (
    require_canonical_proving_store,
    require_canonical_unpublished_store,
)
from newsroom.control_plane.store import (
    append_ledger,
    claim_graphiti_attempt,
    clear_graphiti_failure,
    connect,
    graphiti_coverage,
    graphiti_failure_state,
    GraphitiSpendCeilingExceeded,
    has_candidate,
    has_graphiti_ingest,
    insert_graphiti_ingest,
    insert_graphiti_attempt_receipt,
    insert_payload,
    next_graphiti_attempt_number,
    record_graphiti_coverage,
    record_graphiti_failure,
    reconcile_graphiti_spend,
    release_graphiti_attempt_claim,
    reserve_graphiti_spend,
    retain_graphiti_authority_records,
)
from newsroom.control_plane.surface import UnpublishedSurfacePayload
from newsroom.control_plane.veto import VetoError, assert_private_store
from newsroom.control_plane.writer import WriterPort
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
from newsroom.increment9.proving import (
    FORBIDDEN_STORE_MARKERS,
    PROVING_GATES,
)
from newsroom.increment9.rights import assess_rights


GLOBAL_PROVING_GATES = frozenset(
    gate_id for gate_id in PROVING_GATES if not gate_id.startswith("RIGHTS_")
)
_PROVING_RUN_LATEST_ORDER = "rowid DESC"
_PROVING_RUN_EARLIEST_ORDER = "rowid ASC"
_PROVING_FENCE_TIMEOUT_SECONDS = 5.0


class _ProvingFenceUnavailable(RuntimeError):
    """The provider boundary could not acquire a proving-writer fence."""


class _ProviderAttemptRecoveryAccounting(TypedDict):
    spend_id: str
    status: str
    retained_attempt_receipt: bool
    reconciled_again: bool
    accounting: dict[str, object] | None


@dataclass(frozen=True, slots=True)
class _DispatchAuthority:
    rights: dict[str, object]
    deadline: datetime


@dataclass(frozen=True, slots=True)
class CycleReport:
    proving_run_id: str
    minted: int
    duplicate: int
    sources: int
    candidates: int
    ledger_digest: str
    writer_id: str
    graphiti: int = 0
    eligible: int = 0


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


def _now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _dispatch_valid_until(evaluated_at: datetime) -> str:
    return _utc_text(
        evaluated_at + timedelta(milliseconds=GRAPHITI_EXTRACTION_TIMEOUT_MS)
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
    if tuple(raw.get("proposals", ())) != result.proposals:
        raise ValueError("graphiti proposal receipt differs from bound raw receipt")
    if result.proposal_count != len(result.proposals):
        raise ValueError("graphiti proposal count differs from retained proposals")
    if (
        tuple(raw.get("entities", ())) != result.entities
        or tuple(raw.get("relations", ())) != result.relations
        or tuple(raw.get("passages", ())) != result.passages
        or tuple(raw.get("chat_invocations", ())) != result.chat_invocations
        or raw.get("embedding_usage") != result.embedding_usage
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
    return receipt


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
    usage = result.embedding_usage if isinstance(result.embedding_usage, dict) else {}
    return (
        usage.get("usage_basis") == "NO_EMBEDDING_CALL"
        and usage.get("requests") == []
        and usage.get("request_count") == 0
        and usage.get("embedding_tokens") == 0
        and usage.get("cost_usd_microunits") == 0
    )


def _proves_no_provider_dispatch(result: GraphitiCycleResult) -> bool:
    raw = result.raw_receipt if isinstance(result.raw_receipt, dict) else {}
    return (
        raw.get("dispatch_state") == "NOT_DISPATCHED"
        and _reports_no_embedding_call(result)
        and not result.chat_invocations
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
    try:
        recovery_classification = GraphitiRecoveryClassification(
            str(raw.get("recovery_classification"))
        )
    except ValueError:
        recovery_classification = None
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
) -> int:
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
                reserved_gbp_microunits=500_000,
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
                    "reserved_gbp_microunits": 500_000,
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
                if isinstance(graphiti, GovernedRealGraphitiPort):
                    returned_result = graphiti.ingest_until(
                        unit,
                        deadline=dispatch_authority.deadline,
                    )
                else:
                    returned_result = graphiti.ingest(unit)
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
                dispatch_state = (
                    "NOT_DISPATCHED"
                    if returned_result is not None
                    and _proves_no_provider_dispatch(returned_result)
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
                        "chat_invocations": (
                            []
                            if returned_result is None
                            else list(returned_result.chat_invocations)
                        ),
                        "embedding_usage": (
                            None
                            if returned_result is None
                            else returned_result.embedding_usage
                        ),
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
                "binding_failure": str(exc),
                "returned_raw_receipt": (
                    None
                    if returned_result is None
                    else returned_result.raw_receipt
                ),
                "chat_invocations": (
                    []
                    if returned_result is None
                    else list(returned_result.chat_invocations)
                ),
                "embedding_usage": (
                    None
                    if returned_result is None
                    else returned_result.embedding_usage
                ),
                "provider_attempt_number": (
                    None
                    if returned_result is None
                    else returned_result.provider_attempt_number
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
            unpublished.commit()
            continue
        terminal_outcome = result.outcome in {"COMPLETE", "PARTIAL"}
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
            append_ledger(
                unpublished,
                "GRAPHITI_EVALUATION_RETRY_HELD",
                {
                    "ingest_id": unit.ingest_id,
                    "attempt_number": attempt_number,
                    "failure_code": result.failure_code,
                    "accounting": accounting,
                    "chat_invocations": list(result.chat_invocations),
                    "embedding_usage": result.embedding_usage,
                    "provider_dispatch_state": (
                        "NOT_DISPATCHED"
                        if _proves_no_provider_dispatch(result)
                        else "UNKNOWN"
                    ),
                },
            )
            unpublished.commit()
            continue
        accounting = _reconcile_result_spend(
            unpublished,
            unit=unit,
            attempt_number=attempt_number,
            result=result,
            binding_validated=True,
        )
        receipt = _receipt(unit, result, accounting=accounting)
        receipt["dispatch_rights"] = dispatch_rights
        final_digest = insert_graphiti_attempt_receipt(
            unpublished,
            ingest_id=unit.ingest_id,
            attempt_number=attempt_number,
            outcome=result.outcome,
            receipt=receipt,
        )
        receipt["receipt_digest"] = final_digest
        append_ledger(unpublished, "GRAPHITI_EVALUATION_ATTEMPT", receipt)
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
            _fail(
                unpublished,
                unit,
                outcome=result.outcome,
                failure_code=result.failure_code,
            )
        unpublished.commit()
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
            SELECT source_id, url, fetched_at, status_code, body_digest, body
            FROM proving_observations
            WHERE run_id=?
            ORDER BY source_id, fetched_at, body_digest
            """,
            (run_id,),
        ).fetchall()
        for source_id, url, fetched_at, status_code, body_digest, body in values:
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
            ):
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
                body=bytes(body),
                rights_authority_run_id=latest_run_id,
                rights_gate_id=gate_id,
                rights_gate_reason=canonical_json_bytes(stable_rights).decode("utf-8"),
            )
            all_rows.append(row)
            if run_id == latest_run_id:
                latest_rows.append(row)
    return latest_run_id, tuple(latest_rows), tuple(all_rows)


def run_cycle(
    *,
    proving_store: str,
    unpublished_store: str,
    writer: WriterPort,
    max_writes: int = 5,
    graphiti: GraphitiPort | None = None,
    max_graphiti: int = 1,
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
) -> CycleReport:
    if isinstance(graphiti, GovernedRealGraphitiPort):
        require_canonical_proving_store(proving_store)
        require_canonical_unpublished_store(unpublished_store)
    assert_private_store(unpublished_store)
    lowered = proving_store.lower()
    if any(marker in lowered for marker in FORBIDDEN_STORE_MARKERS):
        raise ValueError("proving store must not alias production or news_pool")
    admission_evaluated_at = clock().astimezone(UTC)
    proving = sqlite3.connect(proving_store)
    proving.execute("PRAGMA query_only=ON")
    try:
        run_id, latest_rows, corpus_rows = _permitted_rows(
            proving,
            evaluated_at=_utc_text(admission_evaluated_at),
            required_valid_until=_dispatch_valid_until(admission_evaluated_at),
        )
    finally:
        proving.close()

    def rights_check(unit: CorpusIngestUnit) -> dict[str, object] | None:
        current = sqlite3.connect(proving_store)
        current.execute("PRAGMA query_only=ON")
        try:
            evaluated_at = clock().astimezone(UTC)
            return _dispatch_rights_decision(
                current,
                source_id=unit.source_id,
                source_url=unit.source_definition_url,
                evaluated_at=_utc_text(evaluated_at),
                required_valid_until=_dispatch_valid_until(evaluated_at),
            )
        finally:
            current.close()

    @contextmanager
    def rights_fence(
        unit: CorpusIngestUnit,
    ) -> Iterator[_DispatchAuthority | None]:
        timeout_ms = max(1, int(_PROVING_FENCE_TIMEOUT_SECONDS * 1_000))
        current = sqlite3.connect(
            proving_store, timeout=_PROVING_FENCE_TIMEOUT_SECONDS
        )
        current.execute(f"PRAGMA busy_timeout={timeout_ms}")
        try:
            try:
                current.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                raise _ProvingFenceUnavailable(
                    "proving writer fence was unavailable"
                ) from exc
            evaluated_at = clock().astimezone(UTC)
            decision = _dispatch_rights_decision(
                current,
                source_id=unit.source_id,
                source_url=unit.source_definition_url,
                evaluated_at=_utc_text(evaluated_at),
                required_valid_until=_dispatch_valid_until(evaluated_at),
            )
            yield (
                None
                if decision is None
                else _DispatchAuthority(
                    rights=decision,
                    deadline=evaluated_at
                    + timedelta(milliseconds=GRAPHITI_EXTRACTION_TIMEOUT_MS),
                )
            )
        finally:
            if current.in_transaction:
                current.rollback()
            current.close()

    observations = _parsed_observations(latest_rows)
    unit_by_id: dict[str, CorpusIngestUnit] = {}
    for row in corpus_rows:
        for unit in units_from(
            _parsed_observations((row,)),
            proving_run_id=row.run_id,
            rights_authority_run_id=row.rights_authority_run_id,
            rights_gate_id=row.rights_gate_id,
            rights_gate_reason=row.rights_gate_reason,
            source_definition_url=row.url,
        ):
            unit_by_id.setdefault(unit.ingest_id, unit)
    units = tuple(
        sorted(
            unit_by_id.values(), key=lambda item: (item.observed_at, item.ingest_id)
        )
    )
    revisions = revisions_from(units)
    candidates = form_candidates(observations)
    sources = len({row.source_id for row in latest_rows})
    unpublished = connect(unpublished_store)
    minted = 0
    duplicate = 0
    graphiti_ok = 0
    try:
        append_ledger(
            unpublished,
            "PRIVATE_CYCLE_START",
            {
                "proving_run_id": run_id,
                "observations": len(latest_rows),
                "candidates": len(candidates),
                "eligible_source_revisions": len(revisions),
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
            )
            unpublished.commit()
        for candidate in candidates:
            if minted >= max_writes:
                break
            if has_candidate(unpublished, candidate.candidate_id):
                duplicate += 1
                continue
            package = package_for(candidate)
            try:
                copy = writer.write(candidate, package)
                payload = UnpublishedSurfacePayload(
                    payload_kind="unpublished_surface_payload",
                    publication_bundle=False,
                    auto_publish=False,
                    language="ZH_HANT_HK",
                    title=copy.title,
                    body=copy.body,
                    evidence_package_digest=package.digest,
                    story_candidate_id=candidate.candidate_id,
                    event_hypothesis_id=candidate.hypothesis_id,
                    source_lineage=tuple(
                        sorted({item.source_id for item in candidate.items})
                    ),
                    generated_at=_now(),
                    status="UNPUBLISHED",
                    writer_id=copy.writer_id,
                )
            except VetoError:
                raise
            except (RuntimeError, ValueError, OSError, json.JSONDecodeError):
                continue
            if insert_payload(unpublished, payload):
                minted += 1
            else:
                duplicate += 1
        coverage = graphiti_coverage(
            unpublished,
            revisions=revisions,
        )
        record_graphiti_coverage(unpublished, coverage)
        digest = append_ledger(
            unpublished,
            "PRIVATE_CYCLE_CLOSE",
            {
                "proving_run_id": run_id,
                "minted": minted,
                "duplicate": duplicate,
                "sources": sources,
                "candidates": len(candidates),
                "writer_id": writer.writer_id,
                "graphiti": graphiti_ok,
                **coverage,
            },
        )
        unpublished.commit()
    finally:
        unpublished.close()
    return CycleReport(
        run_id,
        minted,
        duplicate,
        sources,
        len(candidates),
        digest,
        writer.writer_id,
        graphiti_ok,
        len(revisions),
    )
