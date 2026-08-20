"""Governed unpublished cycle: Signal → Lead → Hypothesis → Candidate → Evidence → write.

Graphiti corpus ingest is independent of CONT writes (GING-001).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.control_plane.corpus import (
    CorpusIngestUnit,
    revisions_from,
    units_from,
)
from newsroom.control_plane.editorial import GroupedObservation, form_candidates
from newsroom.control_plane.evidence import package_for
from newsroom.control_plane.graphiti import GraphitiCycleResult, GraphitiPort
from newsroom.control_plane.items import parse_observation
from newsroom.control_plane.store import (
    append_ledger,
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
    GRAPHITI_GENERATION_ID,
    GRAPHITI_WORKSPACE_GROUP,
    OD_011_CASH_CEILING_GBP,
    OPENROUTER_API,
)
from newsroom.increment9.proving import FORBIDDEN_STORE_MARKERS, PROVING_GATES


GLOBAL_PROVING_GATES = frozenset(
    gate_id for gate_id in PROVING_GATES if not gate_id.startswith("RIGHTS_")
)


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


def _bind_result(
    unit: CorpusIngestUnit, result: GraphitiCycleResult
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
    expected_digest = digest_bytes(expected_text.encode("utf-8"))
    if not isinstance(passage, dict) or (
        passage.get("byte_offset") != 0
        or passage.get("byte_length") != len(expected_text.encode("utf-8"))
        or passage.get("blob_digest") != expected_digest
        or passage.get("text_digest") != expected_digest
    ):
        raise ValueError("graphiti passage provenance differs from ingest bytes")
    if unit.authority is not None and (
        passage.get("admission_id") != unit.authority.admission_id
        or passage.get("access_decision_id") != unit.authority.access_decision_id
    ):
        raise ValueError("graphiti passage authority differs from retained records")
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


def _reconcile_result_spend(
    unpublished: sqlite3.Connection,
    *,
    unit: CorpusIngestUnit,
    attempt_number: int,
    result: GraphitiCycleResult,
) -> dict[str, object]:
    """Attribute returned provider telemetry without trusting invalid identity fields."""

    spend_id = f"{unit.ingest_id}:{attempt_number}"
    reported_attempt = result.provider_attempt_number
    provider_spend_id = f"{unit.ingest_id}:{reported_attempt}"
    provider_exists = unpublished.execute(
        "SELECT 1 FROM unpublished_graphiti_spend WHERE spend_id=?",
        (provider_spend_id,),
    ).fetchone()
    if provider_spend_id == spend_id or provider_exists is None:
        accounting = reconcile_graphiti_spend(
            unpublished,
            spend_id=spend_id,
            embedding_usage=result.embedding_usage,
        )
        if provider_exists is None and provider_spend_id != spend_id:
            accounting["reported_provider_attempt_number"] = reported_attempt
            accounting["reconciled_to_current_attempt"] = True
        append_ledger(unpublished, "GRAPHITI_SPEND_RECONCILE", accounting)
        return accounting

    provider_accounting = reconcile_graphiti_spend(
        unpublished,
        spend_id=provider_spend_id,
        embedding_usage=result.embedding_usage,
    )
    current_accounting = reconcile_graphiti_spend(
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
    append_ledger(unpublished, "GRAPHITI_SPEND_RECONCILE", provider_accounting)
    append_ledger(unpublished, "GRAPHITI_SPEND_RECONCILE", current_accounting)
    return {
        "provider_attempt": provider_accounting,
        "current_attempt": current_accounting,
    }


def _ingest(
    unpublished: sqlite3.Connection,
    *,
    graphiti: GraphitiPort,
    units: tuple[CorpusIngestUnit, ...],
    max_graphiti: int,
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
        attempted += 1
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
        try:
            returned_result = graphiti.ingest(unit)
            result = _bind_result(unit, returned_result)
        except VetoError:
            raise
        except (RuntimeError, ValueError, OSError, json.JSONDecodeError) as exc:
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
        accounting = _reconcile_result_spend(
            unpublished,
            unit=unit,
            attempt_number=attempt_number,
            result=result,
        )
        receipt = _receipt(unit, result, accounting=accounting)
        final_digest = insert_graphiti_attempt_receipt(
            unpublished,
            ingest_id=unit.ingest_id,
            attempt_number=attempt_number,
            outcome=result.outcome,
            receipt=receipt,
        )
        receipt["receipt_digest"] = final_digest
        append_ledger(unpublished, "GRAPHITI_EVALUATION_ATTEMPT", receipt)
        if result.outcome in {"COMPLETE", "PARTIAL"}:
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


def _permitted_rows(
    proving: sqlite3.Connection,
) -> tuple[str, tuple[_ProvingObservation, ...], tuple[_ProvingObservation, ...]]:
    runs = proving.execute(
        "SELECT run_id FROM proving_runs ORDER BY started_at, run_id"
    ).fetchall()
    if not runs:
        raise ValueError("proving store has no runs")
    latest_run_id = str(runs[-1][0])
    current_gates = {
        str(gate_id): (str(status), str(reason))
        for gate_id, status, reason in proving.execute(
            "SELECT gate_id, status, reason FROM proving_gates WHERE run_id=?",
            (latest_run_id,),
        )
    }
    if any(
        current_gates.get(gate_id, ("MISSING", ""))[0] != "PASS"
        for gate_id in GLOBAL_PROVING_GATES
    ):
        return latest_run_id, (), ()
    current_rights = {
        gate_id: decision
        for gate_id, decision in current_gates.items()
        if str(gate_id).startswith("RIGHTS_")
    }
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
            gate_id = f"RIGHTS_{source_id}"
            current = current_rights.get(gate_id)
            if (
                current is None
                or current[0] != "PASS"
                or int(status_code) != 200
                or not body
            ):
                continue
            row = _ProvingObservation(
                run_id=run_id,
                source_id=str(source_id),
                url=str(url),
                fetched_at=str(fetched_at),
                status_code=int(status_code),
                body_digest=str(body_digest),
                body=bytes(body),
                rights_authority_run_id=latest_run_id,
                rights_gate_id=gate_id,
                rights_gate_reason=current[1],
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
) -> CycleReport:
    assert_private_store(unpublished_store)
    lowered = proving_store.lower()
    if any(marker in lowered for marker in FORBIDDEN_STORE_MARKERS):
        raise ValueError("proving store must not alias production or news_pool")
    proving = sqlite3.connect(proving_store)
    proving.execute("PRAGMA query_only=ON")
    try:
        run_id, latest_rows, corpus_rows = _permitted_rows(proving)
    finally:
        proving.close()

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
