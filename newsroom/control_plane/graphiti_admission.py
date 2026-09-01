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
from newsroom.entities.types import EntityResolutionDecisionId
from newsroom.extraction.models import ProposalDraft
from newsroom.extraction.types import (
    EvidenceRange,
    ExtractionPassageId,
    ExtractionProposalKind,
    ProposalPredicateHint,
)
from newsroom.graphiti_adapter.admission import GraphitiProposalAdmissionAction
from newsroom.graphiti_adapter.evaluation_packet import GRAPHITI_WORKSPACE_GROUP
from newsroom.projection.models import ProjectionGenerationId

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
_MAX_ADMISSION_REQUEST_BYTES = 256 * 1024


class GraphitiAdmissionConsumerError(RuntimeError):
    """A durable receipt or governed admission response is invalid."""


def _exact_ingest_ids(
    ingest_ids: tuple[str, ...] | None,
) -> tuple[str, ...] | None:
    if ingest_ids is None:
        return None
    if (
        not isinstance(ingest_ids, tuple)
        or not ingest_ids
        or any(
            not isinstance(item, str)
            or not item
            or len(item.encode("utf-8")) > 256
            for item in ingest_ids
        )
        or ingest_ids != tuple(sorted(set(ingest_ids)))
    ):
        raise ValueError("exact Graphiti admission ingest identities are invalid")
    return ingest_ids


@dataclass(frozen=True, slots=True)
class GraphitiAdmissionRequest:
    queue_seq: int
    proposal_key: str
    source_receipt_digest: str
    proposal: ProposalDraft
    proposal_payload: Mapping[str, object]
    evidence_passages: tuple[Mapping[str, object], ...]
    proposed_endpoints: tuple[str, str] | None
    relation_statement: str | None
    relation_temporal_bounds: Mapping[str, object] | None
    source_lineage: Mapping[str, object]

    def __post_init__(self) -> None:
        if self.proposal.kind is ExtractionProposalKind.RELATION:
            expected = (
                self.proposal.subject_placeholder,
                self.proposal.object_placeholder,
            )
            if (
                self.proposed_endpoints != expected
                or not self.relation_statement
                or self.relation_temporal_bounds is None
                or set(self.relation_temporal_bounds)
                != {"valid_at", "invalid_at", "expired_at"}
            ):
                raise GraphitiAdmissionConsumerError(
                    "relation admission mapping lacks proposed endpoints or temporal evidence"
                )
        elif any(
            value is not None
            for value in (
                self.proposed_endpoints,
                self.relation_statement,
                self.relation_temporal_bounds,
            )
        ):
            raise GraphitiAdmissionConsumerError(
                "entity admission mapping cannot carry relation evidence"
            )
        if not self.evidence_passages:
            raise GraphitiAdmissionConsumerError(
                "admission request needs referenced passage metadata"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "queue_seq": self.queue_seq,
            "proposal_key": self.proposal_key,
            "source_receipt_digest": self.source_receipt_digest,
            "proposal": dict(self.proposal_payload),
            "evidence_passages": [dict(item) for item in self.evidence_passages],
            "proposed_endpoints": (
                None if self.proposed_endpoints is None else list(self.proposed_endpoints)
            ),
            "relation_statement": self.relation_statement,
            "relation_temporal_bounds": (
                None
                if self.relation_temporal_bounds is None
                else dict(self.relation_temporal_bounds)
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
    endpoint_resolution_decision_ids: tuple[str, ...] = ()
    resolved_endpoint_names: tuple[str, ...] = ()
    provider_model_calls: int = 0

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
        if self.proposal_kind is ExtractionProposalKind.RELATION:
            if (
                self.action is GraphitiProposalAdmissionAction.ADMIT
                and (
                    len(self.endpoint_resolution_decision_ids) != 2
                    or len(set(self.endpoint_resolution_decision_ids)) != 2
                    or any(not item for item in self.endpoint_resolution_decision_ids)
                    or len(self.resolved_endpoint_names) != 2
                )
            ):
                raise GraphitiAdmissionConsumerError(
                    "relation admission requires two effective endpoint resolutions"
                )
            for decision_id in self.endpoint_resolution_decision_ids:
                try:
                    EntityResolutionDecisionId.parse(decision_id)
                except (TypeError, ValueError) as exc:
                    raise GraphitiAdmissionConsumerError(
                        "relation endpoint resolution identity must be UUIDv4"
                    ) from exc
        elif self.endpoint_resolution_decision_ids or self.resolved_endpoint_names:
            raise GraphitiAdmissionConsumerError(
                "entity resolution decision cannot name relation endpoints"
            )
        if self.provider_model_calls != 0:
            raise GraphitiAdmissionConsumerError(
                "admission authority must make zero provider/model calls"
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
            "endpoint_resolution_decision_ids": list(
                self.endpoint_resolution_decision_ids
            ),
            "resolved_endpoint_names": list(self.resolved_endpoint_names),
            "provider_model_calls": self.provider_model_calls,
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
    projector_family_id: str = "graph.increment4.admitted"
    generation_id: str = ""
    schema_version: str = "newsroom.increment4.admitted-projection.v1"
    trust_scope: str = "ADMITTED"
    provider_model_calls: int = 0

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
        if self.projector_family_id != "graph.increment4.admitted":
            raise GraphitiAdmissionConsumerError(
                "projection receipt is outside the Increment 4 admitted family"
            )
        if not self.generation_id:
            raise GraphitiAdmissionConsumerError(
                "projection receipt needs a governed generation identity"
            )
        try:
            ProjectionGenerationId.parse(self.generation_id)
        except (TypeError, ValueError) as exc:
            raise GraphitiAdmissionConsumerError(
                "projection receipt generation identity must be UUIDv4"
            ) from exc
        if (
            self.schema_version != "newsroom.increment4.admitted-projection.v1"
            or self.trust_scope != "ADMITTED"
        ):
            raise GraphitiAdmissionConsumerError(
                "projection receipt schema or trust scope differs"
            )
        if self.provider_model_calls != 0:
            raise GraphitiAdmissionConsumerError(
                "admission and projection must make zero provider/model calls"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "proposal_key": self.proposal_key,
            "decision_id": self.decision_id,
            "effect_id": self.effect_id,
            "authority_watermark": self.authority_watermark,
            "receipt_digest": self.receipt_digest,
            "projector_family_id": self.projector_family_id,
            "generation_id": self.generation_id,
            "schema_version": self.schema_version,
            "trust_scope": self.trust_scope,
            "provider_model_calls": self.provider_model_calls,
        }


@dataclass(frozen=True, slots=True)
class GraphitiProjectionReconciliationReceipt:
    generation_id: str
    expected_effect_ids: tuple[str, ...]
    actual_effect_ids: tuple[str, ...]
    authority_watermark: int
    receipt_digest: str
    projector_family_id: str = "graph.increment4.admitted"
    provider_model_calls: int = 0

    def __post_init__(self) -> None:
        if not self.generation_id:
            raise GraphitiAdmissionConsumerError(
                "projection reconciliation needs a generation identity"
            )
        try:
            ProjectionGenerationId.parse(self.generation_id)
        except (TypeError, ValueError) as exc:
            raise GraphitiAdmissionConsumerError(
                "projection reconciliation generation identity must be UUIDv4"
            ) from exc
        if (
            self.expected_effect_ids
            != tuple(sorted(set(self.expected_effect_ids)))
            or self.actual_effect_ids != tuple(sorted(set(self.actual_effect_ids)))
        ):
            raise GraphitiAdmissionConsumerError(
                "projection reconciliation effect identities must be sorted and unique"
            )
        if self.expected_effect_ids != self.actual_effect_ids:
            raise GraphitiAdmissionConsumerError(
                "admitted projection does not reconcile to governed SQLite authority"
            )
        if self.projector_family_id != "graph.increment4.admitted":
            raise GraphitiAdmissionConsumerError(
                "projection reconciliation family differs from Increment 4"
            )
        if self.authority_watermark <= 0:
            raise GraphitiAdmissionConsumerError(
                "projection reconciliation needs a positive authority watermark"
            )
        validate_sha256_digest(
            self.receipt_digest,
            field="Graphiti projection reconciliation digest",
        )
        if self.provider_model_calls != 0:
            raise GraphitiAdmissionConsumerError(
                "projection reconciliation must make zero provider/model calls"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "generation_id": self.generation_id,
            "expected_effect_ids": list(self.expected_effect_ids),
            "actual_effect_ids": list(self.actual_effect_ids),
            "authority_watermark": self.authority_watermark,
            "receipt_digest": self.receipt_digest,
            "projector_family_id": self.projector_family_id,
            "provider_model_calls": self.provider_model_calls,
        }


class GovernedGraphitiAdmissionAuthority(Protocol):
    def decide_entity_resolution(
        self,
        request: GraphitiAdmissionRequest,
        *,
        required_action: GraphitiProposalAdmissionAction | None,
        idempotency_key: str,
    ) -> GraphitiGovernedDecision: ...

    def decide_relation_admission(
        self,
        request: GraphitiAdmissionRequest,
        *,
        required_action: GraphitiProposalAdmissionAction | None,
        idempotency_key: str,
    ) -> GraphitiGovernedDecision: ...

    def relation_endpoint_resolutions_current(
        self,
        request: GraphitiAdmissionRequest,
        decision: GraphitiGovernedDecision,
    ) -> bool:
        """Re-read both effective Entity Resolution Decisions from authority."""
        ...


class GovernedGraphitiProjector(Protocol):
    def recover_increment4_admitted_receipt(
        self, *, idempotency_key: str
    ) -> GraphitiProjectionReceipt | None: ...

    def deliver_increment4_admitted(
        self,
        request: GraphitiProjectionRequest,
        *,
        idempotency_key: str,
    ) -> GraphitiProjectionReceipt: ...

    def tombstone_increment4_admitted(
        self,
        request: GraphitiProjectionRequest,
        *,
        idempotency_key: str,
    ) -> GraphitiProjectionReceipt: ...

    def reconcile_increment4_admitted(
        self,
        expected: tuple[GraphitiProjectionReceipt, ...],
        *,
        generation_id: str,
    ) -> GraphitiProjectionReconciliationReceipt: ...


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
    projection_gap_count: int
    projection_reconciled: bool
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
            "projection_gap_count": self.projection_gap_count,
            "projection_reconciled": self.projection_reconciled,
            "provider_model_calls": self.provider_model_calls,
        }


@dataclass(frozen=True, slots=True)
class _MappedProposal:
    proposal_key: str
    ingest_id: str
    source_revision_id: str
    source_receipt_digest: str
    proposal: ProposalDraft
    proposal_payload: dict[str, object]
    evidence_passages: tuple[dict[str, object], ...]
    proposed_endpoints: tuple[str, str] | None
    relation_statement: str | None
    relation_temporal_bounds: dict[str, object] | None
    private_graph_receipt: dict[str, object] | None
    source_lineage: dict[str, object]


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


def _exact_integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GraphitiAdmissionConsumerError(f"{field} must be an exact integer")
    return value


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


def graphiti_admission_request_from_value(
    value: Mapping[str, object],
) -> GraphitiAdmissionRequest:
    raw = dict(value)
    proposal_payload = _mapping(raw["proposal"], field="proposal")
    endpoints_raw = raw.get("proposed_endpoints")
    temporal_raw = raw.get("relation_temporal_bounds")
    return GraphitiAdmissionRequest(
        queue_seq=_exact_integer(raw["queue_seq"], field="queue sequence"),
        proposal_key=str(raw["proposal_key"]),
        source_receipt_digest=str(raw["source_receipt_digest"]),
        proposal=_parse_proposal(proposal_payload),
        proposal_payload=proposal_payload,
        evidence_passages=tuple(
            _mapping(item, field="evidence passage")
            for item in raw["evidence_passages"]  # type: ignore[union-attr]
        ),
        proposed_endpoints=(
            None
            if endpoints_raw is None
            else (str(endpoints_raw[0]), str(endpoints_raw[1]))  # type: ignore[index]
        ),
        relation_statement=(
            None
            if raw.get("relation_statement") is None
            else str(raw["relation_statement"])
        ),
        relation_temporal_bounds=(
            None
            if temporal_raw is None
            else _mapping(temporal_raw, field="relation temporal bounds")
        ),
        source_lineage=_mapping(raw["source_lineage"], field="source lineage"),
    )


def graphiti_governed_decision_from_json(value: str) -> GraphitiGovernedDecision:
    raw = _mapping(json.loads(value), field="retained admission decision")
    return GraphitiGovernedDecision(
        proposal_key=str(raw["proposal_key"]),
        proposal_digest=str(raw["proposal_digest"]),
        proposal_kind=ExtractionProposalKind(str(raw["proposal_kind"])),
        proposal_local_id=str(raw["proposal_local_id"]),
        action=GraphitiProposalAdmissionAction(str(raw["action"])),
        decision_id=str(raw["decision_id"]),
        authority_ledger_seq=_exact_integer(
            raw["authority_ledger_seq"], field="authority ledger sequence"
        ),
        reason_code=str(raw["reason_code"]),
        authority_receipt_digest=str(raw["authority_receipt_digest"]),
        endpoint_resolution_decision_ids=tuple(
            str(item) for item in raw["endpoint_resolution_decision_ids"]  # type: ignore[union-attr]
        ),
        resolved_endpoint_names=tuple(
            str(item) for item in raw["resolved_endpoint_names"]  # type: ignore[union-attr]
        ),
        provider_model_calls=_exact_integer(
            raw["provider_model_calls"], field="provider model calls"
        ),
    )


def graphiti_projection_receipt_from_json(value: str) -> GraphitiProjectionReceipt:
    raw = _mapping(json.loads(value), field="retained projection receipt")
    return GraphitiProjectionReceipt(
        proposal_key=str(raw["proposal_key"]),
        decision_id=str(raw["decision_id"]),
        effect_id=str(raw["effect_id"]),
        authority_watermark=_exact_integer(
            raw["authority_watermark"], field="projection authority watermark"
        ),
        receipt_digest=str(raw["receipt_digest"]),
        projector_family_id=str(raw["projector_family_id"]),
        generation_id=str(raw["generation_id"]),
        schema_version=str(raw["schema_version"]),
        trust_scope=str(raw["trust_scope"]),
        provider_model_calls=_exact_integer(
            raw["provider_model_calls"], field="provider model calls"
        ),
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
        projection_generation_id: str,
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
        self._projection_generation_id = str(
            ProjectionGenerationId.parse(projection_generation_id)
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise GraphitiAdmissionConsumerError("admission clock must be timezone-aware")
        return value.astimezone(UTC)

    @staticmethod
    def _time_text(value: datetime) -> str:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    def enqueue_complete_receipts(
        self, *, ingest_ids: tuple[str, ...] | None = None
    ) -> int:
        exact = _exact_ingest_ids(ingest_ids)
        statement = """
            SELECT ingest.ingest_id, ingest.outcome, ingest.proposal_count,
                   ingest.entity_count, ingest.relation_count,
                   ingest.receipt_digest, receipt.receipt_json
            FROM unpublished_graphiti_ingest AS ingest
            JOIN unpublished_graphiti_receipts AS receipt USING(ingest_id)
            WHERE ingest.outcome IN ('COMPLETE','PARTIAL')
            """
        parameters: tuple[object, ...] = ()
        if exact is not None:
            statement += " AND ingest.ingest_id IN (" + ",".join(
                "?" for _ in exact
            ) + ")"
            parameters = exact
        statement += " ORDER BY ingest.at, ingest.ingest_id"
        rows = self._connection.execute(statement, parameters).fetchall()
        if exact is not None and tuple(sorted(str(row[0]) for row in rows)) != exact:
            raise GraphitiAdmissionConsumerError(
                "exact Graphiti admission receipts are missing or non-terminal"
            )
        mapped_receipts: list[tuple[str, tuple[_MappedProposal, ...]]] = []
        for row in rows:
            ingest_id = str(row[0])
            receipt_digest = str(row[5])
            try:
                requests = self._map_receipt(
                    ingest_id=ingest_id,
                    outcome=str(row[1]),
                    proposal_count=int(row[2]),
                    entity_count=int(row[3]),
                    relation_count=int(row[4]),
                    receipt_digest=receipt_digest,
                    receipt_json=str(row[6]),
                )
            except (
                GraphitiAdmissionConsumerError,
                IndexError,
                KeyError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                self._record_receipt_failure(
                    ingest_id=ingest_id,
                    receipt_digest=receipt_digest,
                    detail=str(exc),
                )
                if exact is not None:
                    raise GraphitiAdmissionConsumerError(
                        "exact Graphiti admission receipt is invalid: "
                        f"{ingest_id}"
                    ) from exc
                continue
            mapped_receipts.append((ingest_id, requests))
        enqueued = 0
        with _transaction(self._connection):
            for ingest_id, requests in mapped_receipts:
                for mapped in requests:
                    enqueued += self._insert_request(mapped)
                self._connection.execute(
                    "DELETE FROM unpublished_graphiti_admission_receipt_failures "
                    "WHERE ingest_id=?",
                    (ingest_id,),
                )
        return enqueued

    def _map_receipt(
        self,
        *,
        ingest_id: str,
        outcome: str,
        proposal_count: int,
        entity_count: int,
        relation_count: int,
        receipt_digest: str,
        receipt_json: str,
    ) -> tuple[_MappedProposal, ...]:
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
            or receipt.get("workspace_group") != GRAPHITI_WORKSPACE_GROUP
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
        if (
            entity_count != len(entities)
            or relation_count != len(relations)
            or receipt.get("entity_count") != entity_count
            or receipt.get("relation_count") != relation_count
        ):
            raise GraphitiAdmissionConsumerError(
                "Graphiti terminal entity or relation denominator differs"
            )
        lineage = {field: receipt.get(field) for field in _LINEAGE_FIELDS}
        if any(value is None for value in lineage.values()):
            raise GraphitiAdmissionConsumerError(
                "Graphiti source lineage is incomplete"
            )
        passages_by_id = {
            str(item.get("passage_id")): item for item in passages
        }
        if len(passages_by_id) != len(passages):
            raise GraphitiAdmissionConsumerError(
                "Graphiti evidence passage identities must be unique"
            )
        self._validate_authority_records(receipt, lineage, passages)
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
        if len(entities_by_id) != len(entities) or len(relations_by_id) != len(
            relations
        ):
            raise GraphitiAdmissionConsumerError(
                "Graphiti entity and relation receipt identities must be unique"
            )
        result = []
        local_ids: set[str] = set()
        entity_local_ids: set[str] = set()
        relation_local_ids: set[str] = set()
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
            relation_statement: str | None = None
            relation_temporal_bounds: dict[str, object] | None = None
            proposed_endpoints: tuple[str, str] | None = None
            if proposal.kind is ExtractionProposalKind.RELATION:
                relation_local_ids.add(proposal.local_id)
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
                relation_statement = str(relation_payload.get("fact") or "")
                if not relation_statement:
                    raise GraphitiAdmissionConsumerError(
                        "Graphiti relation proposal lacks its retained statement"
                    )
                relation_temporal_bounds = {
                    field: relation_payload[field]
                    for field in ("valid_at", "invalid_at", "expired_at")
                }
                proposed_endpoints = (
                    proposal.subject_placeholder,
                    str(proposal.object_placeholder),
                )
            elif (
                entity_payload is None
                or entity_payload.get("name") != proposal.subject_placeholder
                or entity_payload.get("source_registry_id") is True
            ):
                raise GraphitiAdmissionConsumerError(
                    "Graphiti entity proposal lacks its retained mention receipt"
                )
            else:
                entity_local_ids.add(proposal.local_id)
            referenced_passages = tuple(
                passages_by_id[str(evidence.passage_id)]
                for evidence in proposal.evidence
            )
            proposal_key = digest_canonical(
                {
                    "source_receipt_digest": receipt_digest,
                    "proposal_local_id": proposal.local_id,
                    "proposal_digest": proposal.digest,
                }
            )
            result.append(
                _MappedProposal(
                    proposal_key=proposal_key,
                    ingest_id=ingest_id,
                    source_revision_id=str(lineage["revision_id"]),
                    source_receipt_digest=receipt_digest,
                    proposal=proposal,
                    proposal_payload=proposal_payload,
                    evidence_passages=referenced_passages,
                    proposed_endpoints=proposed_endpoints,
                    relation_statement=relation_statement,
                    relation_temporal_bounds=relation_temporal_bounds,
                    private_graph_receipt=(
                        None if relation_payload is None else relation_payload
                    ),
                    source_lineage=lineage,
                )
            )
        if (
            entity_local_ids != set(entities_by_id)
            or relation_local_ids != set(relations_by_id)
        ):
            raise GraphitiAdmissionConsumerError(
                "Graphiti entity or relation receipts do not exactly cover proposals"
            )
        return tuple(result)

    def _validate_authority_records(
        self,
        receipt: Mapping[str, object],
        lineage: Mapping[str, object],
        passages: tuple[dict[str, object], ...],
    ) -> None:
        record_ids = receipt.get("authority_record_ids")
        if not isinstance(record_ids, list) or not record_ids:
            raise GraphitiAdmissionConsumerError(
                "Graphiti receipt lacks retained source authority"
            )
        if len({str(item) for item in record_ids}) != len(record_ids):
            raise GraphitiAdmissionConsumerError(
                "Graphiti source authority record identities must be unique"
            )
        records: dict[str, dict[str, object]] = {}
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
            record = _mapping(json.loads(raw), field="source authority record")
            if record.get("record_id") != str(record_id):
                raise GraphitiAdmissionConsumerError(
                    "Graphiti source authority record identity differs"
                )
            records[str(record_id)] = record
        revision_id = str(lineage["revision_id"])
        revision = records.get(revision_id)
        if (
            revision is None
            or revision.get("record_type") != "SOURCE_REVISION"
            or revision.get("source_id") != lineage["source_id"]
            or revision.get("item_key") != lineage["item_key"]
        ):
            raise GraphitiAdmissionConsumerError(
                "Graphiti source revision authority binding differs"
            )
        for passage in passages:
            admission = records.get(str(passage.get("admission_id") or ""))
            access = records.get(str(passage.get("access_decision_id") or ""))
            if (
                admission is None
                or admission.get("record_type") != "OBJECT_ADMISSION"
                or admission.get("revision_id") != revision_id
                or admission.get("decision") != "ADMIT"
                or access is None
                or access.get("record_type") != "OBJECT_ACCESS_DECISION"
                or access.get("revision_id") != revision_id
                or access.get("decision") != "ALLOW"
            ):
                raise GraphitiAdmissionConsumerError(
                    "Graphiti passage rights do not bind retained source authority"
                )
        if not passages:
            raise GraphitiAdmissionConsumerError(
                "Graphiti proposal source has no retained passages"
            )

    def _insert_request(self, mapped: _MappedProposal) -> int:
        retained = self._connection.execute(
            "SELECT proposal_digest FROM unpublished_graphiti_admission_queue "
            "WHERE proposal_key=?",
            (mapped.proposal_key,),
        ).fetchone()
        if retained is not None:
            if str(retained[0]) != mapped.proposal.digest:
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
                mapped.proposal_key,
                mapped.ingest_id,
                mapped.source_revision_id,
                mapped.source_receipt_digest,
                mapped.proposal.digest,
                mapped.proposal.kind.value,
                "{}",
                mapped.proposal_key,
                now,
                now,
            ),
        )
        if cursor.lastrowid is None:
            raise GraphitiAdmissionConsumerError(
                "Graphiti admission queue did not return an identity"
            )
        queue_seq = cursor.lastrowid
        request = GraphitiAdmissionRequest(
            queue_seq=queue_seq,
            proposal_key=mapped.proposal_key,
            source_receipt_digest=mapped.source_receipt_digest,
            proposal=mapped.proposal,
            proposal_payload=mapped.proposal_payload,
            evidence_passages=mapped.evidence_passages,
            proposed_endpoints=mapped.proposed_endpoints,
            relation_statement=mapped.relation_statement,
            relation_temporal_bounds=mapped.relation_temporal_bounds,
            source_lineage=mapped.source_lineage,
        )
        retained_request = request.canonical_value()
        retained_request["private_graph_receipt"] = mapped.private_graph_receipt
        request_bytes = canonical_json_bytes(retained_request)
        if len(request_bytes) > _MAX_ADMISSION_REQUEST_BYTES:
            raise GraphitiAdmissionConsumerError(
                "Graphiti admission request exceeds its SQLite manifest bound"
            )
        self._connection.execute(
            "UPDATE unpublished_graphiti_admission_queue "
            "SET source_receipt_digest=?, request_json=?, request_digest=? "
            "WHERE proposal_key=?",
            (
                mapped.source_receipt_digest,
                request_bytes.decode("utf-8"),
                digest_bytes(request_bytes),
                mapped.proposal_key,
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

    def _claim_next(
        self,
        worker_id: str,
        *,
        ingest_ids: tuple[str, ...] | None = None,
    ) -> tuple[str, GraphitiAdmissionRequest, str] | None:
        if not worker_id or len(worker_id.encode("utf-8")) > 256:
            raise ValueError("admission worker identity is invalid")
        exact = _exact_ingest_ids(ingest_ids)
        now = self._now()
        now_text = self._time_text(now)
        until = self._time_text(now + timedelta(seconds=self._lease_seconds))
        with _transaction(self._connection):
            while True:
                statement = """
                    SELECT proposal_key, ingest_id, request_json, request_digest,
                           state, source_receipt_digest, proposal_digest,
                           proposal_kind
                    FROM unpublished_graphiti_admission_queue
                    WHERE (state='READY'
                       OR (state='CLAIMED' AND claim_until<=?)
                       OR (state='DECIDED' AND (claim_until IS NULL OR claim_until<=?)))
                    """
                parameters: tuple[object, ...] = (now_text, now_text)
                if exact is not None:
                    statement += " AND ingest_id IN (" + ",".join(
                        "?" for _ in exact
                    ) + ")"
                    parameters = (*parameters, *exact)
                statement += " ORDER BY queue_seq LIMIT 1"
                row = self._connection.execute(statement, parameters).fetchone()
                if row is None:
                    return None
                (
                    proposal_key,
                    ingest_id,
                    request_json,
                    request_digest,
                    state,
                    source_receipt_digest,
                    proposal_digest,
                    proposal_kind,
                ) = map(str, row)
                try:
                    retained_request = _mapping(
                        json.loads(request_json),
                        field="queued admission request",
                    )
                    request = graphiti_admission_request_from_value(retained_request)
                    if (
                        digest_bytes(canonical_json_bytes(retained_request))
                        != request_digest
                        or request.proposal_key != proposal_key
                        or request.source_receipt_digest != source_receipt_digest
                        or request.proposal.digest != proposal_digest
                        or request.proposal.kind.value != proposal_kind
                    ):
                        raise GraphitiAdmissionConsumerError(
                            "queued Graphiti admission request integrity differs"
                        )
                except (
                    GraphitiAdmissionConsumerError,
                    IndexError,
                    KeyError,
                    TypeError,
                    ValueError,
                    json.JSONDecodeError,
                ) as exc:
                    detail = f"{type(exc).__name__}: {exc}"[:4096]
                    self._connection.execute(
                        """
                        UPDATE unpublished_graphiti_admission_queue
                        SET state='DEAD_LETTER', attempt_count=?, last_error=?,
                            claim_owner=NULL, claim_until=NULL, updated_at=?
                        WHERE proposal_key=?
                        """,
                        (self._max_attempts, detail, now_text, proposal_key),
                    )
                    self._connection.execute(
                        """
                        INSERT INTO unpublished_graphiti_admission_receipt_failures(
                            ingest_id, receipt_digest, failure_code, detail,
                            occurrence_count, first_seen_at, last_seen_at
                        ) VALUES(?,?,'QUEUE_INTEGRITY_INVALID',?,1,?,?)
                        ON CONFLICT(ingest_id) DO UPDATE SET
                            failure_code=excluded.failure_code,
                            detail=excluded.detail,
                            occurrence_count=occurrence_count+1,
                            last_seen_at=excluded.last_seen_at
                        """,
                        (
                            ingest_id,
                            source_receipt_digest,
                            detail,
                            now_text,
                            now_text,
                        ),
                    )
                    continue
                updated = self._connection.execute(
                    """
                    UPDATE unpublished_graphiti_admission_queue
                    SET state=CASE
                          WHEN state='DECIDED' THEN 'DECIDED' ELSE 'CLAIMED'
                        END,
                        claim_owner=?, claim_until=?, updated_at=?
                    WHERE proposal_key=?
                      AND (state='READY'
                        OR (state='CLAIMED' AND claim_until<=?)
                        OR (state='DECIDED'
                            AND (claim_until IS NULL OR claim_until<=?)))
                    """,
                    (worker_id, until, now_text, proposal_key, now_text, now_text),
                ).rowcount
                if updated != 1:
                    continue
                break
        return proposal_key, request, state

    def drain(
        self,
        *,
        worker_id: str,
        limit: int = 100,
        ingest_ids: tuple[str, ...] | None = None,
    ) -> GraphitiAdmissionDrainReport:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("admission drain limit must be positive")
        exact = _exact_ingest_ids(ingest_ids)
        claimed = decided = projected = failed = dead_lettered = 0
        for _ in range(limit):
            claim = self._claim_next(worker_id, ingest_ids=exact)
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
                    decide = (
                        self._authority.decide_relation_admission
                        if request.proposal.kind is ExtractionProposalKind.RELATION
                        else self._authority.decide_entity_resolution
                    )
                    decision = decide(
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
                    if (
                        request.proposal.kind is ExtractionProposalKind.RELATION
                        and decision.action
                        is GraphitiProposalAdmissionAction.ADMIT
                        and not self._authority.relation_endpoint_resolutions_current(
                            request, decision
                        )
                    ):
                        raise GraphitiAdmissionConsumerError(
                            "relation endpoints lack current governed resolutions"
                        )
                    self._retain_decision(request, decision)
                    decided += 1
                if decision.action is GraphitiProposalAdmissionAction.ADMIT:
                    endpoints_current = not (
                        request.proposal.kind is ExtractionProposalKind.RELATION
                    ) or self._authority.relation_endpoint_resolutions_current(
                        request, decision
                    )
                    rights_current = self._rights.is_current(request)
                    if not endpoints_current or not rights_current:
                        if previous_state == "DECIDED":
                            recovered = (
                                self._projector.recover_increment4_admitted_receipt(
                                    idempotency_key=(
                                        f"graphiti-project:{proposal_key}:"
                                        f"{decision.decision_id}"
                                    )
                                )
                            )
                            if recovered is not None:
                                self._retain_projection(
                                    request, decision, recovered
                                )
                                try:
                                    self._tombstone_projection(
                                        proposal_key=proposal_key,
                                        request=request,
                                        decision=decision,
                                    )
                                except Exception as exc:
                                    failed += 1
                                    if self._record_rights_reconciliation_failure(
                                        proposal_key, exc
                                    ):
                                        dead_lettered += 1
                                continue
                        self._mark_revoked_before_projection(request)
                        continue
                    if (
                        request.proposal.kind is ExtractionProposalKind.RELATION
                        and not self._authority.relation_endpoint_resolutions_current(
                            request, decision
                        )
                    ):
                        raise GraphitiAdmissionConsumerError(
                            "relation endpoints are no longer governed-current"
                        )
                    delivery = GraphitiProjectionRequest(request, decision)
                    receipt = self._projector.deliver_increment4_admitted(
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
        return None if row is None else graphiti_governed_decision_from_json(str(row[0]))

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
        if (
            decision.action is GraphitiProposalAdmissionAction.ADMIT
            and request.proposal.kind is ExtractionProposalKind.RELATION
            and decision.resolved_endpoint_names != request.proposed_endpoints
        ):
            raise GraphitiAdmissionConsumerError(
                "relation authority did not resolve the exact proposed endpoints"
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
            if existing is None:
                self._connection.execute(
                    """
                    INSERT INTO unpublished_graphiti_admission_decisions(
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
                    attempt_count=0, last_error=NULL, updated_at=?
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
            or receipt.authority_watermark != decision.authority_ledger_seq
            or receipt.generation_id != self._projection_generation_id
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
            if existing is None:
                self._connection.execute(
                    """
                    INSERT INTO unpublished_graphiti_projection_receipts(
                        proposal_key, effect_id, authority_watermark,
                        projector_family_id, generation_id, schema_version,
                        trust_scope, receipt_json, receipt_digest, projected_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        request.proposal_key,
                        receipt.effect_id,
                        receipt.authority_watermark,
                        receipt.projector_family_id,
                        receipt.generation_id,
                        receipt.schema_version,
                        receipt.trust_scope,
                        encoded,
                        receipt.receipt_digest,
                        now,
                    ),
                )
            self._connection.execute(
                """
                UPDATE unpublished_graphiti_admission_queue
                SET state='PROJECTED', claim_owner=NULL, claim_until=NULL,
                    attempt_count=0, last_error=NULL, updated_at=?
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

    def reconcile_rights(
        self,
        *,
        limit: int = 100,
        ingest_ids: tuple[str, ...] | None = None,
    ) -> int:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("rights reconciliation limit must be positive")
        exact = _exact_ingest_ids(ingest_ids)
        statement = """
            SELECT queue.proposal_key, queue.request_json, decision.decision_json
            FROM unpublished_graphiti_admission_queue AS queue
            JOIN unpublished_graphiti_admission_decisions AS decision
              USING(proposal_key)
            JOIN unpublished_graphiti_projection_receipts AS projection
              USING(proposal_key)
            LEFT JOIN unpublished_graphiti_projection_tombstones AS tombstone
              USING(proposal_key)
            WHERE decision.action='ADMIT' AND tombstone.proposal_key IS NULL
              AND queue.state='PROJECTED'
            """
        parameters: tuple[object, ...] = ()
        if exact is not None:
            statement += " AND queue.ingest_id IN (" + ",".join(
                "?" for _ in exact
            ) + ")"
            parameters = exact
        statement += " ORDER BY queue.queue_seq"
        rows = self._connection.execute(statement, parameters).fetchall()
        revoked = 0
        for proposal_key, request_json, decision_json in rows:
            if revoked >= limit:
                break
            try:
                request = graphiti_admission_request_from_value(
                    _mapping(
                        json.loads(str(request_json)),
                        field="queued admission request",
                    )
                )
                if self._rights.is_current(request):
                    continue
                decision = graphiti_governed_decision_from_json(str(decision_json))
                self._tombstone_projection(
                    proposal_key=str(proposal_key),
                    request=request,
                    decision=decision,
                )
            except Exception as exc:
                self._record_rights_reconciliation_failure(
                    str(proposal_key), exc
                )
                continue
            revoked += 1
        return revoked

    def _record_rights_reconciliation_failure(
        self, proposal_key: str, exc: Exception
    ) -> bool:
        now = self._time_text(self._now())
        with _transaction(self._connection):
            self._connection.execute(
                """
                UPDATE unpublished_graphiti_admission_queue
                SET attempt_count=attempt_count+1,
                    state=CASE WHEN attempt_count+1>=? THEN 'DEAD_LETTER'
                               ELSE state END,
                    last_error=?, updated_at=?
                WHERE proposal_key=? AND state='PROJECTED'
                """,
                (
                    self._max_attempts,
                    f"RIGHTS_RECONCILIATION: {type(exc).__name__}: {exc}"[:4096],
                    now,
                    proposal_key,
                ),
            )
            state = self._connection.execute(
                "SELECT state FROM unpublished_graphiti_admission_queue "
                "WHERE proposal_key=?",
                (proposal_key,),
            ).fetchone()
        return state is not None and str(state[0]) == "DEAD_LETTER"

    def _tombstone_projection(
        self,
        *,
        proposal_key: str,
        request: GraphitiAdmissionRequest,
        decision: GraphitiGovernedDecision,
    ) -> None:
        delivery = GraphitiProjectionRequest(request, decision)
        receipt = self._projector.tombstone_increment4_admitted(
            delivery,
            idempotency_key=f"graphiti-tombstone:{proposal_key}:{decision.decision_id}",
        )
        if (
            receipt.proposal_key != proposal_key
            or receipt.decision_id != decision.decision_id
            or receipt.generation_id != self._projection_generation_id
        ):
            raise GraphitiAdmissionConsumerError(
                "governed tombstone receipt names another proposal"
            )
        original = self._connection.execute(
            "SELECT generation_id, authority_watermark "
            "FROM unpublished_graphiti_projection_receipts WHERE proposal_key=?",
            (proposal_key,),
        ).fetchone()
        if (
            original is None
            or str(original[0]) != receipt.generation_id
            or receipt.authority_watermark < int(original[1])
        ):
            raise GraphitiAdmissionConsumerError(
                "governed tombstone watermark precedes admission authority"
            )
        encoded = canonical_json_bytes(receipt.canonical_value()).decode("utf-8")
        now = self._time_text(self._now())
        with _transaction(self._connection):
            existing = self._connection.execute(
                "SELECT receipt_json "
                "FROM unpublished_graphiti_projection_tombstones "
                "WHERE proposal_key=?",
                (proposal_key,),
            ).fetchone()
            if existing is not None and str(existing[0]) != encoded:
                raise GraphitiAdmissionConsumerError(
                    "Graphiti projection tombstone identity changed"
                )
            if existing is None:
                self._connection.execute(
                    """
                    INSERT INTO unpublished_graphiti_projection_tombstones(
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
                """
                UPDATE unpublished_graphiti_admission_queue
                SET state='REVOKED', attempt_count=0, last_error=NULL, updated_at=?
                WHERE proposal_key=?
                """,
                (now, proposal_key),
            )

    def reconcile_projection(
        self, *, generation_id: str
    ) -> GraphitiProjectionReconciliationReceipt:
        if not generation_id:
            raise ValueError("projection reconciliation generation is required")
        if generation_id != self._projection_generation_id:
            raise GraphitiAdmissionConsumerError(
                "projection reconciliation generation differs from consumer authority"
            )
        rights_failures = int(
            self._connection.execute(
                "SELECT COUNT(*) FROM unpublished_graphiti_admission_queue "
                "WHERE last_error LIKE 'RIGHTS_RECONCILIATION:%'"
            ).fetchone()[0]
        )
        if rights_failures:
            raise GraphitiAdmissionConsumerError(
                "projection reconciliation is blocked by rights tombstone failures"
            )
        rows = self._connection.execute(
            """
            SELECT queue.proposal_key, queue.request_json, projection.receipt_json
            FROM unpublished_graphiti_admission_decisions AS decision
            JOIN unpublished_graphiti_admission_queue AS queue USING(proposal_key)
            LEFT JOIN unpublished_graphiti_projection_receipts AS projection
              USING(proposal_key)
            LEFT JOIN unpublished_graphiti_projection_tombstones AS tombstone
              USING(proposal_key)
            WHERE decision.action='ADMIT' AND queue.state!='REVOKED'
              AND tombstone.proposal_key IS NULL
            ORDER BY queue.queue_seq
            """,
        ).fetchall()
        expected_items: list[GraphitiProjectionReceipt] = []
        missing: list[str] = []
        for proposal_key, request_json, projection_json in rows:
            graphiti_admission_request_from_value(
                _mapping(
                    json.loads(str(request_json)),
                    field="queued admission request",
                )
            )
            if projection_json is None:
                missing.append(str(proposal_key))
                continue
            projection = graphiti_projection_receipt_from_json(str(projection_json))
            if projection.generation_id != generation_id:
                raise GraphitiAdmissionConsumerError(
                    "admitted projection receipt belongs to another generation"
                )
            expected_items.append(projection)
        if missing:
            raise GraphitiAdmissionConsumerError(
                "admitted projection has missing governed effects: "
                + ",".join(missing[:10])
            )
        expected = tuple(sorted(expected_items, key=lambda item: item.effect_id))
        if expected:
            required_watermark = max(
                item.authority_watermark for item in expected
            )
        else:
            tombstone_watermark = self._connection.execute(
                """
                SELECT MAX(tombstone.authority_watermark)
                FROM unpublished_graphiti_projection_tombstones AS tombstone
                JOIN unpublished_graphiti_projection_receipts AS projection
                  USING(proposal_key)
                WHERE projection.generation_id=?
                """,
                (generation_id,),
            ).fetchone()[0]
            if tombstone_watermark is None:
                raise GraphitiAdmissionConsumerError(
                    "projection reconciliation has no governed generation evidence"
                )
            required_watermark = int(tombstone_watermark)
        receipt = self._projector.reconcile_increment4_admitted(
            expected,
            generation_id=generation_id,
        )
        expected_ids = tuple(sorted(item.effect_id for item in expected))
        if (
            receipt.generation_id != generation_id
            or receipt.expected_effect_ids != expected_ids
            or receipt.authority_watermark != required_watermark
        ):
            raise GraphitiAdmissionConsumerError(
                "projection reconciliation receipt differs from governed authority"
            )
        encoded = canonical_json_bytes(receipt.canonical_value()).decode("utf-8")
        now = self._time_text(self._now())
        with _transaction(self._connection):
            existing = self._connection.execute(
                "SELECT receipt_json "
                "FROM unpublished_graphiti_projection_reconciliations "
                "WHERE receipt_digest=?",
                (receipt.receipt_digest,),
            ).fetchone()
            if existing is not None and str(existing[0]) != encoded:
                raise GraphitiAdmissionConsumerError(
                    "projection reconciliation digest was reused"
                )
            if existing is None:
                self._connection.execute(
                    """
                    INSERT INTO unpublished_graphiti_projection_reconciliations(
                        receipt_digest, projector_family_id, generation_id,
                        authority_watermark, receipt_json, reconciled_at
                    ) VALUES(?,?,?,?,?,?)
                    """,
                    (
                        receipt.receipt_digest,
                        receipt.projector_family_id,
                        receipt.generation_id,
                        receipt.authority_watermark,
                        encoded,
                        now,
                    ),
                )
        return receipt

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
    active_admitted = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM unpublished_graphiti_admission_decisions AS decision
            JOIN unpublished_graphiti_admission_queue AS queue USING(proposal_key)
            WHERE decision.action='ADMIT' AND queue.state!='REVOKED'
            """
        ).fetchone()[0]
    )
    active_effect_ids = tuple(
        str(row[0])
        for row in connection.execute(
            """
            SELECT projection.effect_id
            FROM unpublished_graphiti_projection_receipts AS projection
            LEFT JOIN unpublished_graphiti_projection_tombstones AS tombstone
              USING(proposal_key)
            WHERE tombstone.proposal_key IS NULL
            ORDER BY projection.effect_id
            """
        )
    )
    reconciliation_row = connection.execute(
        "SELECT receipt_json FROM unpublished_graphiti_projection_reconciliations "
        "ORDER BY reconciled_at DESC LIMIT 1"
    ).fetchone()
    reconciled = False
    rights_tombstone_failures = int(
        connection.execute(
            "SELECT COUNT(*) FROM unpublished_graphiti_admission_queue "
            "WHERE last_error LIKE 'RIGHTS_RECONCILIATION:%'"
        ).fetchone()[0]
    )
    if reconciliation_row is not None:
        reconciliation = _mapping(
            json.loads(str(reconciliation_row[0])),
            field="projection reconciliation telemetry",
        )
        generation_effect_ids = tuple(
            str(row[0])
            for row in connection.execute(
                """
                SELECT projection.effect_id
                FROM unpublished_graphiti_projection_receipts AS projection
                LEFT JOIN unpublished_graphiti_projection_tombstones AS tombstone
                  USING(proposal_key)
                WHERE projection.generation_id=?
                  AND tombstone.proposal_key IS NULL
                ORDER BY projection.effect_id
                """,
                (str(reconciliation.get("generation_id") or ""),),
            )
        )
        actual_effect_ids = reconciliation.get("actual_effect_ids")
        reconciled = (
            rights_tombstone_failures == 0
            and isinstance(actual_effect_ids, list)
            and tuple(actual_effect_ids) == generation_effect_ids
            and active_admitted == len(active_effect_ids)
        )
    integrity_holds = int(
        connection.execute(
            "SELECT COUNT(*) FROM unpublished_graphiti_admission_receipt_failures"
        ).fetchone()[0]
    )
    failure_order_row = connection.execute(
        """
        SELECT ingest.at, failure.ingest_id
        FROM unpublished_graphiti_admission_receipt_failures AS failure
        JOIN unpublished_graphiti_ingest AS ingest USING(ingest_id)
        ORDER BY ingest.at, failure.ingest_id
        LIMIT 1
        """
    ).fetchone()
    failure_order = (
        None
        if failure_order_row is None
        else (str(failure_order_row[0]), str(failure_order_row[1]))
    )
    watermark: int | None = None
    for (
        queue_seq,
        ingest_at,
        ingest_id,
        state,
        action,
        decision_watermark,
        projection_watermark,
    ) in connection.execute(
        """
        SELECT queue.queue_seq, ingest.at, queue.ingest_id, queue.state,
               decision.action, decision.authority_ledger_seq,
               projection.authority_watermark
        FROM unpublished_graphiti_admission_queue AS queue
        JOIN unpublished_graphiti_ingest AS ingest USING(ingest_id)
        LEFT JOIN unpublished_graphiti_admission_decisions AS decision
          USING(proposal_key)
        LEFT JOIN unpublished_graphiti_projection_receipts AS projection
          USING(proposal_key)
        ORDER BY queue.queue_seq
        """
    ):
        del queue_seq
        if failure_order is not None and failure_order <= (
            str(ingest_at),
            str(ingest_id),
        ):
            break
        candidate = (
            projection_watermark
            if action == "ADMIT" and projection_watermark is not None
            else decision_watermark
        )
        terminal = state == "REVOKED" or action in {"REJECT", "HOLD"} or (
            action == "ADMIT" and projection_watermark is not None
        )
        if not terminal or candidate is None:
            break
        candidate_value = int(candidate)
        if watermark is not None and candidate_value < watermark:
            break
        watermark = candidate_value
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
        projection_gap_count=(
            max(active_admitted - len(active_effect_ids), 0)
            + rights_tombstone_failures
        ),
        projection_reconciled=reconciled,
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
    "GraphitiProjectionReconciliationReceipt",
    "GraphitiProjectionRequest",
    "GraphitiProposalAdmissionAction",
    "GraphitiRightsAuthority",
    "graphiti_admission_request_from_value",
    "graphiti_admission_telemetry",
    "graphiti_governed_decision_from_json",
    "graphiti_projection_receipt_from_json",
]
