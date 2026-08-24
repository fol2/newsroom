"""Durably drain retained Graphiti proposals through governed admission.

The consumer owns queueing, leases, retry state and receipts only.  Governed
entity/relation authority and the admitted projector remain behind injected
ports, so Graphiti itself receives neither ledger nor projector capability.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
    validate_sha256_digest,
)
from newsroom.extraction.models import ProposalDraft
from newsroom.extraction.types import (
    EvidenceRange,
    ExtractionPassageId,
    ExtractionProposalKind,
    ProposalPredicateHint,
)
from newsroom.graphiti_adapter.admission import GraphitiProposalAdmissionAction


_TERMINAL_INGEST_OUTCOMES = frozenset({"COMPLETE", "PARTIAL"})
_PROJECTABLE_KINDS = frozenset(
    {
        ExtractionProposalKind.ENTITY_MENTION,
        ExtractionProposalKind.ENTITY_EQUIVALENCE,
        ExtractionProposalKind.RELATION,
    }
)
_LINEAGE_FIELDS = (
    "ingest_id",
    "source_id",
    "item_key",
    "revision_id",
    "authority_record_ids",
    "generation_id",
    "episode_uuid",
    "reference_time",
    "temporal_basis",
)


class GraphitiAdmissionConsumerError(RuntimeError):
    """A durable receipt or governed admission response is invalid."""


@dataclass(frozen=True, slots=True)
class GraphitiAdmissionRequest:
    queue_seq: int
    proposal_key: str
    source_receipt_digest: str
    proposal: ProposalDraft
    proposal_payload: Mapping[str, object]
    evidence_passages: tuple[Mapping[str, object], ...]
    entity_payload: Mapping[str, object] | None
    relation_payload: Mapping[str, object] | None
    source_lineage: Mapping[str, object]

    def canonical_value(self) -> dict[str, object]:
        return {
            "queue_seq": self.queue_seq,
            "proposal_key": self.proposal_key,
            "source_receipt_digest": self.source_receipt_digest,
            "proposal": dict(self.proposal_payload),
            "evidence_passages": [dict(item) for item in self.evidence_passages],
            "entity_payload": (
                None if self.entity_payload is None else dict(self.entity_payload)
            ),
            "relation_payload": (
                None if self.relation_payload is None else dict(self.relation_payload)
            ),
            "source_lineage": dict(self.source_lineage),
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class GraphitiGovernedDecision:
    proposal_key: str
    proposal_digest: str
    proposal_kind: ExtractionProposalKind
    proposal_local_id: str
    action: GraphitiProposalAdmissionAction
    decision_id: str
    authority_ledger_seq: int
    reason_code: str
    authority_receipt_digest: str

    def __post_init__(self) -> None:
        if not self.proposal_key or not self.decision_id or not self.reason_code:
            raise GraphitiAdmissionConsumerError(
                "governed admission decision identity is incomplete"
            )
        validate_sha256_digest(
            self.proposal_digest,
            field="Graphiti governed admission proposal digest",
        )
        if self.proposal_kind not in _PROJECTABLE_KINDS:
            raise GraphitiAdmissionConsumerError(
                "governed admission decision proposal kind is invalid"
            )
        if not self.proposal_local_id:
            raise GraphitiAdmissionConsumerError(
                "governed admission decision proposal local identity is incomplete"
            )
        if not isinstance(self.action, GraphitiProposalAdmissionAction):
            raise GraphitiAdmissionConsumerError(
                "governed admission decision action must be typed"
            )
        if (
            isinstance(self.authority_ledger_seq, bool)
            or not isinstance(self.authority_ledger_seq, int)
            or self.authority_ledger_seq <= 0
        ):
            raise GraphitiAdmissionConsumerError(
                "governed admission decision needs a positive ledger sequence"
            )
        validate_sha256_digest(
            self.authority_receipt_digest,
            field="Graphiti governed admission receipt digest",
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "proposal_key": self.proposal_key,
            "proposal_digest": self.proposal_digest,
            "proposal_kind": self.proposal_kind.value,
            "proposal_local_id": self.proposal_local_id,
            "action": self.action.value,
            "decision_id": self.decision_id,
            "authority_ledger_seq": self.authority_ledger_seq,
            "reason_code": self.reason_code,
            "authority_receipt_digest": self.authority_receipt_digest,
        }


@dataclass(frozen=True, slots=True)
class GraphitiProjectionRequest:
    request: GraphitiAdmissionRequest
    decision: GraphitiGovernedDecision


@dataclass(frozen=True, slots=True)
class GraphitiProjectionReceipt:
    proposal_key: str
    decision_id: str
    effect_id: str
    authority_watermark: int
    receipt_digest: str

    def __post_init__(self) -> None:
        if not self.proposal_key or not self.decision_id or not self.effect_id:
            raise GraphitiAdmissionConsumerError(
                "governed projection receipt identity is incomplete"
            )
        if (
            isinstance(self.authority_watermark, bool)
            or not isinstance(self.authority_watermark, int)
            or self.authority_watermark <= 0
        ):
            raise GraphitiAdmissionConsumerError(
                "governed projection receipt needs a positive authority watermark"
            )
        validate_sha256_digest(
            self.receipt_digest,
            field="Graphiti governed projection receipt digest",
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "proposal_key": self.proposal_key,
            "decision_id": self.decision_id,
            "effect_id": self.effect_id,
            "authority_watermark": self.authority_watermark,
            "receipt_digest": self.receipt_digest,
        }


class GovernedGraphitiAdmissionAuthority(Protocol):
    def decide(
        self,
        request: GraphitiAdmissionRequest,
        *,
        required_action: GraphitiProposalAdmissionAction | None,
        idempotency_key: str,
    ) -> GraphitiGovernedDecision: ...


class GovernedGraphitiProjector(Protocol):
    def deliver(
        self,
        request: GraphitiProjectionRequest,
        *,
        idempotency_key: str,
    ) -> GraphitiProjectionReceipt: ...

    def tombstone(
        self,
        request: GraphitiProjectionRequest,
        *,
        idempotency_key: str,
    ) -> GraphitiProjectionReceipt: ...


class GraphitiRightsAuthority(Protocol):
    def is_current(self, request: GraphitiAdmissionRequest) -> bool: ...


@dataclass(frozen=True, slots=True)
class GraphitiAdmissionDrainReport:
    claimed: int = 0
    decided: int = 0
    projected: int = 0
    failed: int = 0
    dead_lettered: int = 0


@dataclass(frozen=True, slots=True)
class GraphitiAdmissionTelemetry:
    proposal_denominator: int
    admitted_count: int
    rejected_count: int
    held_count: int
    dead_letter_count: int
    revoked_count: int
    projected_count: int
    admission_backlog: int
    integrity_hold_receipt_count: int
    oldest_lag_seconds: int
    contiguous_projection_watermark: int | None
    provider_model_calls: int = 0

    def canonical_value(self) -> dict[str, object]:
        return {
            "proposal_denominator": self.proposal_denominator,
            "admitted_count": self.admitted_count,
            "rejected_count": self.rejected_count,
            "held_count": self.held_count,
            "dead_letter_count": self.dead_letter_count,
            "revoked_count": self.revoked_count,
            "projected_count": self.projected_count,
            "admission_backlog": self.admission_backlog,
            "integrity_hold_receipt_count": self.integrity_hold_receipt_count,
            "oldest_lag_seconds": self.oldest_lag_seconds,
            "contiguous_projection_watermark": (
                self.contiguous_projection_watermark
            ),
            "provider_model_calls": self.provider_model_calls,
        }


def _mapping(value: object, *, field: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) for key in value
    ):
        raise GraphitiAdmissionConsumerError(f"{field} must be an object")
    return dict(value)


def _mapping_tuple(value: object, *, field: str) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list):
        raise GraphitiAdmissionConsumerError(f"{field} must be a list")
    return tuple(_mapping(item, field=f"{field} item") for item in value)


def _parse_proposal(value: Mapping[str, object]) -> ProposalDraft:
    raw = dict(value)
    expected_keys = {
        "local_id",
        "kind",
        "subject_placeholder",
        "object_placeholder",
        "predicate_hint",
        "confidence_basis_points",
        "uncertainty_codes",
        "rationale_codes",
        "evidence",
    }
    if set(raw) != expected_keys:
        raise GraphitiAdmissionConsumerError(
            "Graphiti proposal payload fields differ from the typed contract"
        )
    evidence_raw = raw["evidence"]
    if not isinstance(evidence_raw, list):
        raise GraphitiAdmissionConsumerError("Graphiti proposal evidence must be a list")
    evidence: list[EvidenceRange] = []
    for item in evidence_raw:
        evidence_value = _mapping(item, field="Graphiti proposal evidence")
        if set(evidence_value) != {
            "passage_id",
            "start_byte",
            "end_byte",
            "evidence_text_digest",
        }:
            raise GraphitiAdmissionConsumerError(
                "Graphiti proposal evidence fields differ from the typed contract"
            )
        evidence.append(
            EvidenceRange(
                passage_id=ExtractionPassageId.parse(
                    str(evidence_value["passage_id"])
                ),
                start_byte=evidence_value["start_byte"],  # type: ignore[arg-type]
                end_byte=evidence_value["end_byte"],  # type: ignore[arg-type]
                evidence_text_digest=str(evidence_value["evidence_text_digest"]),
            )
        )
    try:
        kind = ExtractionProposalKind(str(raw["kind"]))
        predicate = (
            None
            if raw["predicate_hint"] is None
            else ProposalPredicateHint(str(raw["predicate_hint"]))
        )
        draft = ProposalDraft(
            local_id=str(raw["local_id"]),
            kind=kind,
            subject_placeholder=str(raw["subject_placeholder"]),
            object_placeholder=(
                None
                if raw["object_placeholder"] is None
                else str(raw["object_placeholder"])
            ),
            predicate_hint=predicate,
            confidence_basis_points=raw["confidence_basis_points"],  # type: ignore[arg-type]
            uncertainty_codes=tuple(raw["uncertainty_codes"]),  # type: ignore[arg-type]
            rationale_codes=tuple(raw["rationale_codes"]),  # type: ignore[arg-type]
            evidence=tuple(evidence),
        )
    except (TypeError, ValueError) as exc:
        raise GraphitiAdmissionConsumerError(
            "Graphiti proposal payload is not a typed proposal"
        ) from exc
    if draft.kind not in _PROJECTABLE_KINDS or draft.canonical_value() != raw:
        raise GraphitiAdmissionConsumerError(
            "Graphiti proposal payload differs after typed mapping"
        )
    return draft


def _request_from_value(value: Mapping[str, object]) -> GraphitiAdmissionRequest:
    raw = dict(value)
    proposal_payload = _mapping(raw["proposal"], field="proposal")
    entity_raw = raw.get("entity_payload")
    relation_raw = raw.get("relation_payload")
    return GraphitiAdmissionRequest(
        queue_seq=int(raw["queue_seq"]),
        proposal_key=str(raw["proposal_key"]),
        source_receipt_digest=str(raw["source_receipt_digest"]),
        proposal=_parse_proposal(proposal_payload),
        proposal_payload=proposal_payload,
        evidence_passages=tuple(
            _mapping(item, field="evidence passage")
            for item in raw["evidence_passages"]  # type: ignore[union-attr]
        ),
        entity_payload=(
            None if entity_raw is None else _mapping(entity_raw, field="entity payload")
        ),
        relation_payload=(
            None
            if relation_raw is None
            else _mapping(relation_raw, field="relation payload")
        ),
        source_lineage=_mapping(raw["source_lineage"], field="source lineage"),
    )


def _decision_from_json(value: str) -> GraphitiGovernedDecision:
    raw = _mapping(json.loads(value), field="retained admission decision")
    return GraphitiGovernedDecision(
        proposal_key=str(raw["proposal_key"]),
        proposal_digest=str(raw["proposal_digest"]),
        proposal_kind=ExtractionProposalKind(str(raw["proposal_kind"])),
        proposal_local_id=str(raw["proposal_local_id"]),
        action=GraphitiProposalAdmissionAction(str(raw["action"])),
        decision_id=str(raw["decision_id"]),
        authority_ledger_seq=int(raw["authority_ledger_seq"]),
        reason_code=str(raw["reason_code"]),
        authority_receipt_digest=str(raw["authority_receipt_digest"]),
    )


@contextmanager
def _transaction(connection: sqlite3.Connection):
    if connection.in_transaction:
        name = "graphiti_admission_savepoint"
        connection.execute(f"SAVEPOINT {name}")
        try:
            yield
            connection.execute(f"RELEASE SAVEPOINT {name}")
        except Exception:
            connection.execute(f"ROLLBACK TO SAVEPOINT {name}")
            connection.execute(f"RELEASE SAVEPOINT {name}")
            raise
        return
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
        connection.commit()
    except Exception:
        connection.rollback()
        raise


class GraphitiAdmissionConsumer:
    """Provider-free durable consumer for retained proposal receipts."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        authority: GovernedGraphitiAdmissionAuthority,
        projector: GovernedGraphitiProjector,
        rights: GraphitiRightsAuthority,
        clock: Callable[[], datetime] | None = None,
        max_attempts: int = 3,
        lease_seconds: int = 60,
    ) -> None:
        if max_attempts <= 0 or lease_seconds <= 0:
            raise ValueError("admission retry and lease bounds must be positive")
        self._connection = connection
        self._authority = authority
        self._projector = projector
        self._rights = rights
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._max_attempts = max_attempts
        self._lease_seconds = lease_seconds

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise GraphitiAdmissionConsumerError("admission clock must be timezone-aware")
        return value.astimezone(UTC)

    @staticmethod
    def _time_text(value: datetime) -> str:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    def enqueue_complete_receipts(self) -> int:
        rows = self._connection.execute(
            """
            SELECT ingest.ingest_id, ingest.outcome, ingest.proposal_count,
                   ingest.receipt_digest, receipt.receipt_json
            FROM unpublished_graphiti_ingest AS ingest
            JOIN unpublished_graphiti_receipts AS receipt USING(ingest_id)
            WHERE ingest.outcome IN ('COMPLETE','PARTIAL')
            ORDER BY ingest.at, ingest.ingest_id
            """
        ).fetchall()
        enqueued = 0
        for row in rows:
            ingest_id = str(row[0])
            receipt_digest = str(row[3])
            try:
                requests = self._map_receipt(
                    ingest_id=ingest_id,
                    outcome=str(row[1]),
                    proposal_count=int(row[2]),
                    receipt_digest=receipt_digest,
                    receipt_json=str(row[4]),
                )
                with _transaction(self._connection):
                    for request_parts in requests:
                        enqueued += self._insert_request(*request_parts)
                    self._connection.execute(
                        "DELETE FROM unpublished_graphiti_admission_receipt_failures "
                        "WHERE ingest_id=?",
                        (ingest_id,),
                    )
            except (GraphitiAdmissionConsumerError, TypeError, ValueError, json.JSONDecodeError) as exc:
                self._record_receipt_failure(
                    ingest_id=ingest_id,
                    receipt_digest=receipt_digest,
                    detail=str(exc),
                )
        return enqueued

    def _map_receipt(
        self,
        *,
        ingest_id: str,
        outcome: str,
        proposal_count: int,
        receipt_digest: str,
        receipt_json: str,
    ) -> tuple[
        tuple[
            str,
            str,
            str,
            ProposalDraft,
            dict[str, object],
            tuple[dict[str, object], ...],
            dict[str, object] | None,
            dict[str, object] | None,
            dict[str, object],
        ],
        ...,
    ]:
        if outcome not in _TERMINAL_INGEST_OUTCOMES:
            raise GraphitiAdmissionConsumerError(
                "only terminal proposal receipts may enter admission"
            )
        receipt = _mapping(json.loads(receipt_json), field="Graphiti receipt")
        unsigned = dict(receipt)
        supplied_digest = unsigned.pop("receipt_digest", None)
        actual_digest = digest_bytes(canonical_json_bytes(unsigned))
        if supplied_digest != receipt_digest or actual_digest != receipt_digest:
            raise GraphitiAdmissionConsumerError(
                "Graphiti retained receipt integrity differs"
            )
        if (
            receipt.get("ingest_id") != ingest_id
            or receipt.get("outcome") != outcome
            or receipt.get("workspace_group") != "newsroom-eval-proposal"
            or receipt.get("profile") != "EVALUATION"
        ):
            raise GraphitiAdmissionConsumerError(
                "Graphiti terminal receipt authority binding differs"
            )
        proposals = _mapping_tuple(receipt.get("proposals"), field="proposals")
        passages = _mapping_tuple(receipt.get("passages"), field="passages")
        entities = _mapping_tuple(receipt.get("entities"), field="entities")
        relations = _mapping_tuple(receipt.get("relations"), field="relations")
        if proposal_count != len(proposals) or receipt.get("proposal_count") != len(
            proposals
        ):
            raise GraphitiAdmissionConsumerError(
                "Graphiti terminal proposal denominator differs"
            )
        lineage = {field: receipt.get(field) for field in _LINEAGE_FIELDS}
        if any(value is None for value in lineage.values()):
            raise GraphitiAdmissionConsumerError(
                "Graphiti source lineage is incomplete"
            )
        self._validate_authority_records(receipt, lineage)
        passages_by_id = {
            str(item.get("passage_id")): item for item in passages
        }
        if len(passages_by_id) != len(passages):
            raise GraphitiAdmissionConsumerError(
                "Graphiti evidence passage identities must be unique"
            )
        entities_by_id = {
            str(item.get("local_id")): item
            for item in entities
            if item.get("local_id") is not None
        }
        relations_by_id = {
            str(item.get("local_id")): item
            for item in relations
            if item.get("local_id") is not None
        }
        result = []
        local_ids: set[str] = set()
        for proposal_payload in proposals:
            proposal = _parse_proposal(proposal_payload)
            if proposal.local_id in local_ids:
                raise GraphitiAdmissionConsumerError(
                    "Graphiti proposal local identities must be unique"
                )
            local_ids.add(proposal.local_id)
            for evidence in proposal.evidence:
                passage = passages_by_id.get(str(evidence.passage_id))
                if passage is None:
                    raise GraphitiAdmissionConsumerError(
                        "Graphiti proposal evidence passage is missing"
                    )
                byte_length = passage.get("byte_length")
                if (
                    isinstance(byte_length, bool)
                    or not isinstance(byte_length, int)
                    or evidence.end_byte > byte_length
                ):
                    raise GraphitiAdmissionConsumerError(
                        "Graphiti proposal evidence exceeds retained passage bytes"
                    )
            relation_payload = relations_by_id.get(proposal.local_id)
            entity_payload = entities_by_id.get(proposal.local_id)
            if proposal.kind is ExtractionProposalKind.RELATION:
                if relation_payload is None:
                    raise GraphitiAdmissionConsumerError(
                        "Graphiti relation proposal lacks endpoint and temporal receipt"
                    )
                for field in (
                    "source_node_uuid",
                    "target_node_uuid",
                    "valid_at",
                    "invalid_at",
                    "expired_at",
                ):
                    if field not in relation_payload:
                        raise GraphitiAdmissionConsumerError(
                            "Graphiti relation endpoint or temporal receipt is incomplete"
                        )
            proposal_key = digest_canonical(
                {
                    "source_receipt_digest": receipt_digest,
                    "proposal_local_id": proposal.local_id,
                    "proposal_digest": proposal.digest,
                }
            )
            result.append(
                (
                    proposal_key,
                    ingest_id,
                    str(lineage["revision_id"]),
                    proposal,
                    proposal_payload,
                    passages,
                    entity_payload,
                    relation_payload,
                    lineage,
                )
            )
        return tuple(result)

    def _validate_authority_records(
        self,
        receipt: Mapping[str, object],
        lineage: Mapping[str, object],
    ) -> None:
        record_ids = receipt.get("authority_record_ids")
        if not isinstance(record_ids, list) or not record_ids:
            raise GraphitiAdmissionConsumerError(
                "Graphiti receipt lacks retained source authority"
            )
        records: list[dict[str, object]] = []
        for record_id in record_ids:
            row = self._connection.execute(
                "SELECT record_digest, record_json "
                "FROM unpublished_graphiti_authority_records WHERE record_id=?",
                (str(record_id),),
            ).fetchone()
            if row is None:
                raise GraphitiAdmissionConsumerError(
                    "Graphiti receipt source authority record is missing"
                )
            raw = str(row[1])
            if digest_bytes(raw.encode("utf-8")) != str(row[0]):
                raise GraphitiAdmissionConsumerError(
                    "Graphiti receipt source authority integrity differs"
                )
            records.append(_mapping(json.loads(raw), field="source authority record"))
        revision_id = lineage["revision_id"]
        admitted = any(
            item.get("record_type") == "OBJECT_ADMISSION"
            and item.get("revision_id") == revision_id
            and item.get("decision") == "ADMIT"
            for item in records
        )
        accessible = any(
            item.get("record_type") == "OBJECT_ACCESS_DECISION"
            and item.get("revision_id") == revision_id
            and item.get("decision") == "ALLOW"
            for item in records
        )
        if not admitted or not accessible:
            raise GraphitiAdmissionConsumerError(
                "Graphiti proposal source rights are not admission-current"
            )

    def _insert_request(
        self,
        proposal_key: str,
        ingest_id: str,
        revision_id: str,
        proposal: ProposalDraft,
        proposal_payload: dict[str, object],
        passages: tuple[dict[str, object], ...],
        entity_payload: dict[str, object] | None,
        relation_payload: dict[str, object] | None,
        lineage: dict[str, object],
    ) -> int:
        retained = self._connection.execute(
            "SELECT proposal_digest FROM unpublished_graphiti_admission_queue "
            "WHERE proposal_key=?",
            (proposal_key,),
        ).fetchone()
        if retained is not None:
            if str(retained[0]) != proposal.digest:
                raise GraphitiAdmissionConsumerError(
                    "Graphiti admission proposal identity was reused"
                )
            return 0
        now = self._time_text(self._now())
        cursor = self._connection.execute(
            """
            INSERT INTO unpublished_graphiti_admission_queue(
                proposal_key, ingest_id, source_revision_id,
                source_receipt_digest, proposal_digest, proposal_kind,
                request_json, request_digest, state, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,'READY',?,?)
            """,
            (
                proposal_key,
                ingest_id,
                revision_id,
                str(lineage.get("receipt_digest") or "") or proposal_key,
                proposal.digest,
                proposal.kind.value,
                "{}",
                proposal_key,
                now,
                now,
            ),
        )
        queue_seq = int(cursor.lastrowid)
        source_receipt_digest = str(
            self._connection.execute(
                "SELECT receipt_digest FROM unpublished_graphiti_ingest "
                "WHERE ingest_id=?",
                (ingest_id,),
            ).fetchone()[0]
        )
        request = GraphitiAdmissionRequest(
            queue_seq=queue_seq,
            proposal_key=proposal_key,
            source_receipt_digest=source_receipt_digest,
            proposal=proposal,
            proposal_payload=proposal_payload,
            evidence_passages=passages,
            entity_payload=entity_payload,
            relation_payload=relation_payload,
            source_lineage=lineage,
        )
        self._connection.execute(
            "UPDATE unpublished_graphiti_admission_queue "
            "SET source_receipt_digest=?, request_json=?, request_digest=? "
            "WHERE proposal_key=?",
            (
                source_receipt_digest,
                canonical_json_bytes(request.canonical_value()).decode("utf-8"),
                request.digest,
                proposal_key,
            ),
        )
        return 1

    def _record_receipt_failure(
        self, *, ingest_id: str, receipt_digest: str, detail: str
    ) -> None:
        now = self._time_text(self._now())
        with _transaction(self._connection):
            self._connection.execute(
                """
                INSERT INTO unpublished_graphiti_admission_receipt_failures(
                    ingest_id, receipt_digest, failure_code, detail,
                    occurrence_count, first_seen_at, last_seen_at
                ) VALUES(?,?,'INTEGRITY_INVALID',?,1,?,?)
                ON CONFLICT(ingest_id) DO UPDATE SET
                    receipt_digest=excluded.receipt_digest,
                    failure_code=excluded.failure_code,
                    detail=excluded.detail,
                    occurrence_count=occurrence_count+1,
                    last_seen_at=excluded.last_seen_at
                """,
                (ingest_id, receipt_digest, detail[:4096], now, now),
            )

    def _claim_next(self, worker_id: str) -> tuple[str, GraphitiAdmissionRequest, str] | None:
        if not worker_id or len(worker_id.encode("utf-8")) > 256:
            raise ValueError("admission worker identity is invalid")
        now = self._now()
        now_text = self._time_text(now)
        until = self._time_text(now + timedelta(seconds=self._lease_seconds))
        with _transaction(self._connection):
            row = self._connection.execute(
                """
                SELECT proposal_key, request_json, request_digest, state,
                       source_receipt_digest, proposal_digest, proposal_kind
                FROM unpublished_graphiti_admission_queue
                WHERE state='READY'
                   OR (state='CLAIMED' AND claim_until<=?)
                   OR (state='DECIDED' AND (claim_until IS NULL OR claim_until<=?))
                ORDER BY queue_seq
                LIMIT 1
                """,
                (now_text, now_text),
            ).fetchone()
            if row is None:
                return None
            (
                proposal_key,
                request_json,
                request_digest,
                state,
                source_receipt_digest,
                proposal_digest,
                proposal_kind,
            ) = map(str, row)
            request = _request_from_value(
                _mapping(json.loads(request_json), field="queued admission request")
            )
            if (
                request.digest != request_digest
                or request.proposal_key != proposal_key
                or request.source_receipt_digest != source_receipt_digest
                or request.proposal.digest != proposal_digest
                or request.proposal.kind.value != proposal_kind
            ):
                raise GraphitiAdmissionConsumerError(
                    "queued Graphiti admission request integrity differs"
                )
            updated = self._connection.execute(
                """
                UPDATE unpublished_graphiti_admission_queue
                SET state=CASE WHEN state='DECIDED' THEN 'DECIDED' ELSE 'CLAIMED' END,
                    claim_owner=?, claim_until=?, updated_at=?
                WHERE proposal_key=?
                  AND (state='READY'
                    OR (state='CLAIMED' AND claim_until<=?)
                    OR (state='DECIDED' AND (claim_until IS NULL OR claim_until<=?)))
                """,
                (worker_id, until, now_text, proposal_key, now_text, now_text),
            ).rowcount
            if updated != 1:
                return None
        return proposal_key, request, state

    def drain(self, *, worker_id: str, limit: int = 100) -> GraphitiAdmissionDrainReport:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("admission drain limit must be positive")
        claimed = decided = projected = failed = dead_lettered = 0
        for _ in range(limit):
            claim = self._claim_next(worker_id)
            if claim is None:
                break
            proposal_key, request, previous_state = claim
            claimed += 1
            try:
                decision = (
                    self._retained_decision(proposal_key)
                    if previous_state == "DECIDED"
                    else None
                )
                if decision is None:
                    required_action = (
                        None
                        if self._rights.is_current(request)
                        else GraphitiProposalAdmissionAction.REJECT
                    )
                    decision = self._authority.decide(
                        request,
                        required_action=required_action,
                        idempotency_key=f"graphiti-admit:{proposal_key}",
                    )
                    if (
                        required_action is not None
                        and decision.action is not required_action
                    ):
                        raise GraphitiAdmissionConsumerError(
                            "governed authority did not honour the rights rejection"
                        )
                    self._retain_decision(request, decision)
                    decided += 1
                if decision.action is GraphitiProposalAdmissionAction.ADMIT:
                    if not self._rights.is_current(request):
                        self._mark_revoked_before_projection(request)
                        continue
                    delivery = GraphitiProjectionRequest(request, decision)
                    receipt = self._projector.deliver(
                        delivery,
                        idempotency_key=f"graphiti-project:{proposal_key}:{decision.decision_id}",
                    )
                    self._retain_projection(request, decision, receipt)
                    projected += 1
            except Exception as exc:
                failed += 1
                if self._record_work_failure(proposal_key, exc):
                    dead_lettered += 1
        return GraphitiAdmissionDrainReport(
            claimed=claimed,
            decided=decided,
            projected=projected,
            failed=failed,
            dead_lettered=dead_lettered,
        )

    def _mark_revoked_before_projection(
        self, request: GraphitiAdmissionRequest
    ) -> None:
        now = self._time_text(self._now())
        with _transaction(self._connection):
            self._connection.execute(
                """
                UPDATE unpublished_graphiti_admission_queue
                SET state='REVOKED', claim_owner=NULL, claim_until=NULL,
                    last_error='RIGHTS_REVOKED_BEFORE_PROJECTION', updated_at=?
                WHERE proposal_key=?
                """,
                (now, request.proposal_key),
            )

    def _retained_decision(self, proposal_key: str) -> GraphitiGovernedDecision | None:
        row = self._connection.execute(
            "SELECT decision_json FROM unpublished_graphiti_admission_decisions "
            "WHERE proposal_key=?",
            (proposal_key,),
        ).fetchone()
        return None if row is None else _decision_from_json(str(row[0]))

    def _retain_decision(
        self,
        request: GraphitiAdmissionRequest,
        decision: GraphitiGovernedDecision,
    ) -> None:
        if decision.proposal_key != request.proposal_key:
            raise GraphitiAdmissionConsumerError(
                "governed admission decision names another proposal"
            )
        if (
            decision.proposal_digest != request.proposal.digest
            or decision.proposal_kind is not request.proposal.kind
            or decision.proposal_local_id != request.proposal.local_id
        ):
            raise GraphitiAdmissionConsumerError(
                "governed admission decision does not bind the exact proposal"
            )
        value = decision.canonical_value()
        encoded = canonical_json_bytes(value).decode("utf-8")
        retained_digest = digest_bytes(encoded.encode("utf-8"))
        now = self._time_text(self._now())
        state = (
            "DECIDED"
            if decision.action is GraphitiProposalAdmissionAction.ADMIT
            else "TERMINAL"
        )
        with _transaction(self._connection):
            existing = self._connection.execute(
                "SELECT decision_json FROM unpublished_graphiti_admission_decisions "
                "WHERE proposal_key=?",
                (request.proposal_key,),
            ).fetchone()
            if existing is not None and str(existing[0]) != encoded:
                raise GraphitiAdmissionConsumerError(
                    "Graphiti proposal already has another governed decision"
                )
            self._connection.execute(
                """
                INSERT OR IGNORE INTO unpublished_graphiti_admission_decisions(
                    proposal_key, action, decision_id, authority_ledger_seq,
                    reason_code, authority_receipt_digest, decision_json,
                    decision_digest, decided_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    request.proposal_key,
                    decision.action.value,
                    decision.decision_id,
                    decision.authority_ledger_seq,
                    decision.reason_code,
                    decision.authority_receipt_digest,
                    encoded,
                    retained_digest,
                    now,
                ),
            )
            self._connection.execute(
                """
                UPDATE unpublished_graphiti_admission_queue
                SET state=?, claim_owner=NULL, claim_until=NULL,
                    last_error=NULL, updated_at=?
                WHERE proposal_key=?
                """,
                (state, now, request.proposal_key),
            )

    def _retain_projection(
        self,
        request: GraphitiAdmissionRequest,
        decision: GraphitiGovernedDecision,
        receipt: GraphitiProjectionReceipt,
    ) -> None:
        if (
            receipt.proposal_key != request.proposal_key
            or receipt.decision_id != decision.decision_id
            or receipt.authority_watermark < decision.authority_ledger_seq
        ):
            raise GraphitiAdmissionConsumerError(
                "governed projection receipt differs from admission authority"
            )
        value = receipt.canonical_value()
        encoded = canonical_json_bytes(value).decode("utf-8")
        now = self._time_text(self._now())
        with _transaction(self._connection):
            existing = self._connection.execute(
                "SELECT receipt_json FROM unpublished_graphiti_projection_receipts "
                "WHERE proposal_key=?",
                (request.proposal_key,),
            ).fetchone()
            if existing is not None and str(existing[0]) != encoded:
                raise GraphitiAdmissionConsumerError(
                    "Graphiti admitted projection effect identity changed"
                )
            self._connection.execute(
                """
                INSERT OR IGNORE INTO unpublished_graphiti_projection_receipts(
                    proposal_key, effect_id, authority_watermark,
                    receipt_json, receipt_digest, projected_at
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    request.proposal_key,
                    receipt.effect_id,
                    receipt.authority_watermark,
                    encoded,
                    receipt.receipt_digest,
                    now,
                ),
            )
            self._connection.execute(
                """
                UPDATE unpublished_graphiti_admission_queue
                SET state='PROJECTED', claim_owner=NULL, claim_until=NULL,
                    last_error=NULL, updated_at=?
                WHERE proposal_key=?
                """,
                (now, request.proposal_key),
            )

    def _record_work_failure(self, proposal_key: str, exc: Exception) -> bool:
        now = self._time_text(self._now())
        with _transaction(self._connection):
            row = self._connection.execute(
                "SELECT state, attempt_count FROM unpublished_graphiti_admission_queue "
                "WHERE proposal_key=?",
                (proposal_key,),
            ).fetchone()
            if row is None:
                raise GraphitiAdmissionConsumerError(
                    "failed admission work item disappeared"
                )
            state = str(row[0])
            attempts = int(row[1]) + 1
            dead = attempts >= self._max_attempts
            retry_state = "DECIDED" if state == "DECIDED" else "READY"
            self._connection.execute(
                """
                UPDATE unpublished_graphiti_admission_queue
                SET state=?, attempt_count=?, last_error=?, claim_owner=NULL,
                    claim_until=NULL, updated_at=?
                WHERE proposal_key=?
                """,
                (
                    "DEAD_LETTER" if dead else retry_state,
                    attempts,
                    f"{type(exc).__name__}: {exc}"[:4096],
                    now,
                    proposal_key,
                ),
            )
        return dead

    def reconcile_rights(self, *, limit: int = 100) -> int:
        rows = self._connection.execute(
            """
            SELECT queue.proposal_key, queue.request_json, decision.decision_json
            FROM unpublished_graphiti_admission_queue AS queue
            JOIN unpublished_graphiti_admission_decisions AS decision
              USING(proposal_key)
            JOIN unpublished_graphiti_projection_receipts AS projection
              USING(proposal_key)
            LEFT JOIN unpublished_graphiti_projection_tombstones AS tombstone
              USING(proposal_key)
            WHERE decision.action='ADMIT' AND tombstone.proposal_key IS NULL
            ORDER BY queue.queue_seq
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        revoked = 0
        for proposal_key, request_json, decision_json in rows:
            request = _request_from_value(
                _mapping(json.loads(str(request_json)), field="queued admission request")
            )
            if self._rights.is_current(request):
                continue
            decision = _decision_from_json(str(decision_json))
            delivery = GraphitiProjectionRequest(request, decision)
            receipt = self._projector.tombstone(
                delivery,
                idempotency_key=f"graphiti-tombstone:{proposal_key}:{decision.decision_id}",
            )
            if (
                receipt.proposal_key != proposal_key
                or receipt.decision_id != decision.decision_id
            ):
                raise GraphitiAdmissionConsumerError(
                    "governed tombstone receipt names another proposal"
                )
            if receipt.authority_watermark < decision.authority_ledger_seq:
                raise GraphitiAdmissionConsumerError(
                    "governed tombstone watermark precedes admission authority"
                )
            encoded = canonical_json_bytes(receipt.canonical_value()).decode("utf-8")
            now = self._time_text(self._now())
            with _transaction(self._connection):
                self._connection.execute(
                    """
                    INSERT OR IGNORE INTO unpublished_graphiti_projection_tombstones(
                        proposal_key, effect_id, authority_watermark,
                        receipt_json, receipt_digest, tombstoned_at
                    ) VALUES(?,?,?,?,?,?)
                    """,
                    (
                        proposal_key,
                        receipt.effect_id,
                        receipt.authority_watermark,
                        encoded,
                        receipt.receipt_digest,
                        now,
                    ),
                )
                self._connection.execute(
                    "UPDATE unpublished_graphiti_admission_queue "
                    "SET state='REVOKED', updated_at=? WHERE proposal_key=?",
                    (now, proposal_key),
                )
            revoked += 1
        return revoked

    def telemetry(self) -> GraphitiAdmissionTelemetry:
        return graphiti_admission_telemetry(
            self._connection,
            now=self._now(),
        )


def graphiti_admission_telemetry(
    connection: sqlite3.Connection,
    *,
    now: datetime | None = None,
) -> GraphitiAdmissionTelemetry:
    denominator = int(
        connection.execute(
            "SELECT COALESCE(SUM(proposal_count),0) "
            "FROM unpublished_graphiti_ingest "
            "WHERE outcome IN ('COMPLETE','PARTIAL')"
        ).fetchone()[0]
    )
    action_counts = {
        str(row[0]): int(row[1])
        for row in connection.execute(
            "SELECT action, COUNT(*) FROM unpublished_graphiti_admission_decisions "
            "GROUP BY action"
        )
    }
    decision_count = sum(action_counts.values())
    dead_letters = int(
        connection.execute(
            "SELECT COUNT(*) FROM unpublished_graphiti_admission_queue "
            "WHERE state='DEAD_LETTER'"
        ).fetchone()[0]
    )
    revoked = int(
        connection.execute(
            "SELECT COUNT(*) FROM unpublished_graphiti_admission_queue "
            "WHERE state='REVOKED'"
        ).fetchone()[0]
    )
    projected = int(
        connection.execute(
            "SELECT COUNT(*) FROM unpublished_graphiti_projection_receipts"
        ).fetchone()[0]
    )
    integrity_holds = int(
        connection.execute(
            "SELECT COUNT(*) FROM unpublished_graphiti_admission_receipt_failures"
        ).fetchone()[0]
    )
    watermark: int | None = None
    if integrity_holds == 0:
        for queue_seq, state, action, projected_flag in connection.execute(
            """
            SELECT queue.queue_seq, queue.state, decision.action,
                   CASE WHEN projection.proposal_key IS NULL THEN 0 ELSE 1 END
            FROM unpublished_graphiti_admission_queue AS queue
            LEFT JOIN unpublished_graphiti_admission_decisions AS decision
              USING(proposal_key)
            LEFT JOIN unpublished_graphiti_projection_receipts AS projection
              USING(proposal_key)
            ORDER BY queue.queue_seq
            """
        ):
            terminal = state == "REVOKED" or action in {"REJECT", "HOLD"} or (
                action == "ADMIT" and int(projected_flag) == 1
            )
            if not terminal:
                break
            watermark = int(queue_seq)
    current = (now or datetime.now(tz=UTC)).astimezone(UTC)
    lag_rows = connection.execute(
        """
        SELECT created_at FROM unpublished_graphiti_admission_queue AS queue
        LEFT JOIN unpublished_graphiti_admission_decisions AS decision
          USING(proposal_key)
        WHERE queue.state NOT IN ('TERMINAL','PROJECTED','REVOKED')
        UNION ALL
        SELECT first_seen_at FROM unpublished_graphiti_admission_receipt_failures
        """
    ).fetchall()
    lags = []
    for row in lag_rows:
        try:
            instant = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
        except ValueError:
            continue
        lags.append(max(int((current - instant.astimezone(UTC)).total_seconds()), 0))
    return GraphitiAdmissionTelemetry(
        proposal_denominator=denominator,
        admitted_count=action_counts.get("ADMIT", 0),
        rejected_count=action_counts.get("REJECT", 0),
        held_count=action_counts.get("HOLD", 0),
        dead_letter_count=dead_letters,
        revoked_count=revoked,
        projected_count=projected,
        admission_backlog=max(denominator - decision_count, 0),
        integrity_hold_receipt_count=integrity_holds,
        oldest_lag_seconds=max(lags, default=0),
        contiguous_projection_watermark=watermark,
    )


__all__ = [
    "GovernedGraphitiAdmissionAuthority",
    "GovernedGraphitiProjector",
    "GraphitiAdmissionConsumer",
    "GraphitiAdmissionConsumerError",
    "GraphitiAdmissionDrainReport",
    "GraphitiAdmissionRequest",
    "GraphitiAdmissionTelemetry",
    "GraphitiGovernedDecision",
    "GraphitiProjectionReceipt",
    "GraphitiProjectionRequest",
    "GraphitiProposalAdmissionAction",
    "GraphitiRightsAuthority",
    "graphiti_admission_telemetry",
]
