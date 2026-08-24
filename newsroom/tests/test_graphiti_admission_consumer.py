from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.control_plane.graphiti_admission import (
    GraphitiAdmissionConsumer,
    GraphitiGovernedDecision,
    GraphitiProjectionReceipt,
    GraphitiProposalAdmissionAction,
)
from newsroom.control_plane.store import (
    connect,
    insert_graphiti_attempt_receipt,
    insert_graphiti_ingest,
    retain_graphiti_authority_records,
)
from newsroom.extraction.models import ProposalDraft
from newsroom.extraction.types import (
    EvidenceRange,
    ExtractionPassageId,
    ExtractionProposalKind,
    ProposalPredicateHint,
)


NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
DIGEST_A = "sha256:" + ("a1" * 32)
DIGEST_B = "sha256:" + ("b2" * 32)


def _draft(local_id: str, kind: ExtractionProposalKind) -> ProposalDraft:
    relation = kind is ExtractionProposalKind.RELATION
    return ProposalDraft(
        local_id=local_id,
        kind=kind,
        subject_placeholder="Alice",
        object_placeholder="Example Council" if relation else None,
        predicate_hint=ProposalPredicateHint.ABOUT_EVENT if relation else None,
        confidence_basis_points=None,
        uncertainty_codes=("REQUIRES_RELATION_ADMISSION",) if relation else (),
        rationale_codes=("GRAPHITI_EVALUATION_SPAN",),
        evidence=(
            EvidenceRange(
                passage_id=ExtractionPassageId.parse(
                    "00000000-0000-4000-8000-000000007581"
                ),
                start_byte=0,
                end_byte=5,
                evidence_text_digest=DIGEST_A,
            ),
        ),
    )


def _seed_receipt(connection, *drafts: ProposalDraft) -> dict[str, object]:
    ingest_id = "sha256:" + ("75" * 32)
    revision_id = "00000000-0000-4000-8000-000000007580"
    passage = {
        "passage_id": "00000000-0000-4000-8000-000000007581",
        "admission_id": "00000000-0000-4000-8000-000000007582",
        "access_decision_id": "00000000-0000-4000-8000-000000007583",
        "byte_offset": 0,
        "byte_length": 128,
        "blob_digest": DIGEST_B,
        "text_digest": DIGEST_B,
    }
    records = (
        {
            "record_type": "SOURCE_REVISION",
            "record_id": revision_id,
            "source_id": "UK-01",
            "item_key": "item-758",
        },
        {
            "record_type": "OBJECT_ADMISSION",
            "record_id": passage["admission_id"],
            "revision_id": revision_id,
            "decision": "ADMIT",
        },
        {
            "record_type": "OBJECT_ACCESS_DECISION",
            "record_id": passage["access_decision_id"],
            "revision_id": revision_id,
            "decision": "ALLOW",
        },
    )
    retain_graphiti_authority_records(connection, records)
    relations = [
        {
            "local_id": item.local_id,
            "uuid": f"private-{item.local_id}",
            "name": "ABOUT_EVENT",
            "fact": "Alice briefed Example Council",
            "source_node_uuid": "private-alice",
            "target_node_uuid": "private-council",
            "valid_at": "2026-08-20T00:00:00Z",
            "invalid_at": None,
            "expired_at": None,
            "proposal_status": "PROPOSED",
        }
        for item in drafts
        if item.kind is ExtractionProposalKind.RELATION
    ]
    receipt: dict[str, object] = {
        "ingest_id": ingest_id,
        "source_id": "UK-01",
        "item_key": "item-758",
        "revision_id": revision_id,
        "outcome": "COMPLETE",
        "proposal_count": len(drafts),
        "entity_count": sum(
            item.kind is not ExtractionProposalKind.RELATION for item in drafts
        ),
        "relation_count": len(relations),
        "failure_code": "NONE",
        "generation_id": "newsroom-eval-generation-758",
        "workspace_group": "newsroom-eval-proposal",
        "episode_uuid": ingest_id,
        "reference_time": "2026-08-20T00:00:00Z",
        "temporal_basis": "SOURCE_PUBLISHED",
        "authority_record_ids": [item["record_id"] for item in records],
        "proposals": [item.canonical_value() for item in drafts],
        "passages": [passage],
        "entities": [],
        "relations": relations,
        "profile": "EVALUATION",
        "receipt_digest": "",
    }
    retained_digest = insert_graphiti_attempt_receipt(
        connection,
        ingest_id=ingest_id,
        attempt_number=1,
        outcome="COMPLETE",
        receipt=receipt,
    )
    receipt["receipt_digest"] = retained_digest
    assert insert_graphiti_ingest(
        connection,
        ingest_id=ingest_id,
        source_id="UK-01",
        item_key="item-758",
        outcome="COMPLETE",
        proposal_count=len(drafts),
        entity_count=int(receipt["entity_count"]),
        relation_count=len(relations),
        failure_code="NONE",
        temporal_basis="SOURCE_PUBLISHED",
        reference_time="2026-08-20T00:00:00Z",
        generation_id="newsroom-eval-generation-758",
        receipt_digest=retained_digest,
        receipt=receipt,
    )
    connection.commit()
    return receipt


class _Authority:
    def __init__(self, actions: dict[str, GraphitiProposalAdmissionAction]) -> None:
        self.actions = actions
        self.calls: list[tuple[object, object, str]] = []
        self.effects: dict[str, GraphitiGovernedDecision] = {}

    def decide(self, request, *, required_action, idempotency_key):
        self.calls.append((request, required_action, idempotency_key))
        action = required_action or self.actions[request.proposal.local_id]
        decision = GraphitiGovernedDecision(
            proposal_key=request.proposal_key,
            proposal_digest=request.proposal.digest,
            proposal_kind=request.proposal.kind,
            proposal_local_id=request.proposal.local_id,
            action=action,
            decision_id=f"decision:{request.proposal_key}",
            authority_ledger_seq=request.queue_seq + 100,
            reason_code=(
                "RIGHTS_REVOKED" if required_action is not None else "FIXTURE_POLICY"
            ),
            authority_receipt_digest=DIGEST_A,
        )
        return self.effects.setdefault(idempotency_key, decision)


class _Projector:
    def __init__(self) -> None:
        self.deliveries: dict[str, GraphitiProjectionReceipt] = {}
        self.tombstones: dict[str, GraphitiProjectionReceipt] = {}
        self.raise_after_first_effect = False

    def deliver(self, request, *, idempotency_key):
        receipt = self.deliveries.setdefault(
            idempotency_key,
            GraphitiProjectionReceipt(
                proposal_key=request.request.proposal_key,
                decision_id=request.decision.decision_id,
                effect_id=f"effect:{request.request.proposal_key}",
                authority_watermark=request.decision.authority_ledger_seq,
                receipt_digest=DIGEST_B,
            ),
        )
        if self.raise_after_first_effect:
            self.raise_after_first_effect = False
            raise RuntimeError("crash after idempotent projection effect")
        return receipt

    def tombstone(self, request, *, idempotency_key):
        return self.tombstones.setdefault(
            idempotency_key,
            GraphitiProjectionReceipt(
                proposal_key=request.request.proposal_key,
                decision_id=request.decision.decision_id,
                effect_id=f"tombstone:{request.request.proposal_key}",
                authority_watermark=request.decision.authority_ledger_seq,
                receipt_digest=DIGEST_A,
            ),
        )


class _Rights:
    def __init__(self) -> None:
        self.allowed = True

    def is_current(self, request) -> bool:
        return self.allowed


def _consumer(connection, authority, projector, rights, *, max_attempts=3):
    return GraphitiAdmissionConsumer(
        connection,
        authority=authority,
        projector=projector,
        rights=rights,
        clock=lambda: NOW,
        max_attempts=max_attempts,
    )


def test_complete_receipts_map_exactly_and_only_admit_projects(tmp_path) -> None:
    connection = connect(str(tmp_path / "admission.sqlite3"))
    entity = _draft("entity.0001", ExtractionProposalKind.ENTITY_MENTION)
    relation = _draft("relation.0001", ExtractionProposalKind.RELATION)
    source = _seed_receipt(connection, entity, relation)
    authority = _Authority(
        {
            entity.local_id: GraphitiProposalAdmissionAction.ADMIT,
            relation.local_id: GraphitiProposalAdmissionAction.HOLD,
        }
    )
    projector = _Projector()
    rights = _Rights()
    consumer = _consumer(connection, authority, projector, rights)

    assert consumer.enqueue_complete_receipts() == 2
    report = consumer.drain(worker_id="fixture-worker", limit=10)

    assert report.decided == 2
    assert report.projected == 1
    requests = [call[0] for call in authority.calls]
    relation_request = next(
        item for item in requests if item.proposal.kind is ExtractionProposalKind.RELATION
    )
    assert relation_request.proposal_payload == source["proposals"][1]
    assert relation_request.evidence_passages == tuple(source["passages"])
    assert relation_request.relation_payload == source["relations"][0]
    assert relation_request.relation_payload["valid_at"] == "2026-08-20T00:00:00Z"
    assert relation_request.source_lineage["revision_id"] == source["revision_id"]
    assert len(projector.deliveries) == 1
    telemetry = consumer.telemetry()
    assert telemetry.proposal_denominator == 2
    assert telemetry.admitted_count == 1
    assert telemetry.held_count == 1
    assert telemetry.rejected_count == 0
    assert telemetry.admission_backlog == 0
    assert telemetry.contiguous_projection_watermark == 2
    connection.close()


def test_integrity_invalid_terminal_receipt_is_never_claimable_or_silent(tmp_path) -> None:
    connection = connect(str(tmp_path / "invalid.sqlite3"))
    draft = _draft("entity.0001", ExtractionProposalKind.ENTITY_MENTION)
    receipt = _seed_receipt(connection, draft)
    tampered = dict(receipt)
    tampered["proposals"] = [
        {**draft.canonical_value(), "subject_placeholder": "Mallory"}
    ]
    connection.execute(
        "UPDATE unpublished_graphiti_receipts SET receipt_json=? WHERE ingest_id=?",
        (json.dumps(tampered, sort_keys=True), receipt["ingest_id"]),
    )
    connection.commit()
    consumer = _consumer(connection, _Authority({}), _Projector(), _Rights())

    assert consumer.enqueue_complete_receipts() == 0
    assert consumer.drain(worker_id="fixture-worker", limit=10).claimed == 0
    telemetry = consumer.telemetry()
    assert telemetry.proposal_denominator == 1
    assert telemetry.admission_backlog == 1
    assert telemetry.integrity_hold_receipt_count == 1
    connection.close()


def test_restart_reuses_projection_idempotency_key_without_duplicate_effect(tmp_path) -> None:
    connection = connect(str(tmp_path / "restart.sqlite3"))
    draft = _draft("entity.0001", ExtractionProposalKind.ENTITY_MENTION)
    _seed_receipt(connection, draft)
    authority = _Authority(
        {draft.local_id: GraphitiProposalAdmissionAction.ADMIT}
    )
    projector = _Projector()
    projector.raise_after_first_effect = True
    consumer = _consumer(connection, authority, projector, _Rights())
    consumer.enqueue_complete_receipts()

    first = consumer.drain(worker_id="worker-a", limit=1)
    second = consumer.drain(worker_id="worker-b", limit=1)

    assert first.failed == 1
    assert second.projected == 1
    assert len(projector.deliveries) == 1
    assert consumer.telemetry().admission_backlog == 0
    connection.close()


def test_rights_revocation_rejects_unadmitted_and_tombstones_derivatives(
    tmp_path,
) -> None:
    connection = connect(str(tmp_path / "rights.sqlite3"))
    admitted = _draft("entity.0001", ExtractionProposalKind.ENTITY_MENTION)
    _seed_receipt(connection, admitted)
    authority = _Authority(
        {admitted.local_id: GraphitiProposalAdmissionAction.ADMIT}
    )
    projector = _Projector()
    rights = _Rights()
    consumer = _consumer(connection, authority, projector, rights)
    consumer.enqueue_complete_receipts()
    assert consumer.drain(worker_id="worker-a", limit=1).projected == 1

    rights.allowed = False
    revoked = consumer.reconcile_rights(limit=10)

    assert revoked == 1
    assert len(projector.tombstones) == 1
    assert consumer.telemetry().revoked_count == 1

    second = replace(admitted, local_id="entity.0002")
    second_connection = connect(str(tmp_path / "rights-before.sqlite3"))
    _seed_receipt(second_connection, second)
    second_authority = _Authority(
        {second.local_id: GraphitiProposalAdmissionAction.ADMIT}
    )
    second_projector = _Projector()
    second_consumer = _consumer(
        second_connection, second_authority, second_projector, rights
    )
    second_consumer.enqueue_complete_receipts()
    report = second_consumer.drain(worker_id="worker-b", limit=1)
    assert report.decided == 1
    assert report.projected == 0
    assert second_authority.calls[0][1] is GraphitiProposalAdmissionAction.REJECT
    assert len(second_projector.deliveries) == 0
    second_connection.close()
    connection.close()


def test_repeated_authority_failure_dead_letters_without_blocking_enqueue(tmp_path) -> None:
    connection = connect(str(tmp_path / "dead-letter.sqlite3"))
    first = _draft("entity.0001", ExtractionProposalKind.ENTITY_MENTION)
    _seed_receipt(connection, first)

    class BrokenAuthority(_Authority):
        def decide(self, request, *, required_action, idempotency_key):
            raise RuntimeError("governed authority unavailable")

    consumer = _consumer(
        connection, BrokenAuthority({}), _Projector(), _Rights(), max_attempts=2
    )
    assert consumer.enqueue_complete_receipts() == 1
    assert consumer.drain(worker_id="worker-a", limit=1).failed == 1
    assert consumer.drain(worker_id="worker-b", limit=1).dead_lettered == 1
    telemetry = consumer.telemetry()
    assert telemetry.dead_letter_count == 1
    assert telemetry.admission_backlog == 1
    connection.close()
