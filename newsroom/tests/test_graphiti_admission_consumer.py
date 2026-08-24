from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.control_plane.graphiti_admission import (
    GraphitiAdmissionConsumer,
    GraphitiGovernedDecision,
    GraphitiProjectionReconciliationReceipt,
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
from newsroom.graphiti_adapter.evaluation_packet import GRAPHITI_WORKSPACE_GROUP
from newsroom.extraction.types import (
    EvidenceRange,
    ExtractionPassageId,
    ExtractionProposalKind,
    ProposalPredicateHint,
)


NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
DIGEST_A = "sha256:" + ("a1" * 32)
DIGEST_B = "sha256:" + ("b2" * 32)
PROJECTION_GENERATION_ID = "00000000-0000-4000-8000-000000007589"
SECOND_PROJECTION_GENERATION_ID = "00000000-0000-4000-8000-000000007590"
SUBJECT_RESOLUTION_ID = "00000000-0000-4000-8000-000000007591"
OBJECT_RESOLUTION_ID = "00000000-0000-4000-8000-000000007592"


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
    entities = [
        {
            "local_id": item.local_id,
            "uuid": f"private-{item.local_id}",
            "name": item.subject_placeholder,
            "summary": "private Graphiti summary",
            "source_registry_id": False,
        }
        for item in drafts
        if item.kind is not ExtractionProposalKind.RELATION
    ]
    receipt: dict[str, object] = {
        "ingest_id": ingest_id,
        "source_id": "UK-01",
        "item_key": "item-758",
        "revision_id": revision_id,
        "outcome": "COMPLETE",
        "proposal_count": len(drafts),
        "entity_count": len(entities),
        "relation_count": len(relations),
        "failure_code": "NONE",
        "generation_id": "newsroom-eval-generation-758",
        "workspace_group": GRAPHITI_WORKSPACE_GROUP,
        "episode_uuid": ingest_id,
        "reference_time": "2026-08-20T00:00:00Z",
        "temporal_basis": "SOURCE_PUBLISHED",
        "authority_record_ids": [item["record_id"] for item in records],
        "proposals": [item.canonical_value() for item in drafts],
        "passages": [passage],
        "entities": entities,
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
        self.endpoints_current = True

    def _decide(self, request, *, required_action, idempotency_key):
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
            endpoint_resolution_decision_ids=(
                (SUBJECT_RESOLUTION_ID, OBJECT_RESOLUTION_ID)
                if request.proposal.kind is ExtractionProposalKind.RELATION
                and action is GraphitiProposalAdmissionAction.ADMIT
                else ()
            ),
            resolved_endpoint_names=(
                request.proposed_endpoints
                if request.proposal.kind is ExtractionProposalKind.RELATION
                and action is GraphitiProposalAdmissionAction.ADMIT
                else ()
            ),
        )
        return self.effects.setdefault(idempotency_key, decision)

    def decide_entity_resolution(
        self, request, *, required_action, idempotency_key
    ):
        assert request.proposal.kind is not ExtractionProposalKind.RELATION
        return self._decide(
            request,
            required_action=required_action,
            idempotency_key=idempotency_key,
        )

    def decide_relation_admission(
        self, request, *, required_action, idempotency_key
    ):
        assert request.proposal.kind is ExtractionProposalKind.RELATION
        return self._decide(
            request,
            required_action=required_action,
            idempotency_key=idempotency_key,
        )

    def relation_endpoint_resolutions_current(self, request, decision):
        return (
            self.endpoints_current
            and decision.endpoint_resolution_decision_ids
            == (SUBJECT_RESOLUTION_ID, OBJECT_RESOLUTION_ID)
            and decision.resolved_endpoint_names == request.proposed_endpoints
        )


class _Projector:
    def __init__(self) -> None:
        self.deliveries: dict[str, GraphitiProjectionReceipt] = {}
        self.tombstones: dict[str, GraphitiProjectionReceipt] = {}
        self.raise_after_first_effect = False

    def recover_increment4_admitted_receipt(self, *, idempotency_key):
        return self.deliveries.get(idempotency_key)

    def deliver_increment4_admitted(self, request, *, idempotency_key):
        receipt = self.deliveries.setdefault(
            idempotency_key,
            GraphitiProjectionReceipt(
                proposal_key=request.request.proposal_key,
                decision_id=request.decision.decision_id,
                effect_id=f"effect:{request.request.proposal_key}",
                authority_watermark=request.decision.authority_ledger_seq,
                receipt_digest=DIGEST_B,
                generation_id=PROJECTION_GENERATION_ID,
            ),
        )
        if self.raise_after_first_effect:
            self.raise_after_first_effect = False
            raise RuntimeError("crash after idempotent projection effect")
        return receipt

    def tombstone_increment4_admitted(self, request, *, idempotency_key):
        return self.tombstones.setdefault(
            idempotency_key,
            GraphitiProjectionReceipt(
                proposal_key=request.request.proposal_key,
                decision_id=request.decision.decision_id,
                effect_id=f"tombstone:{request.request.proposal_key}",
                authority_watermark=request.decision.authority_ledger_seq,
                receipt_digest=DIGEST_A,
                generation_id=PROJECTION_GENERATION_ID,
            ),
        )

    def reconcile_increment4_admitted(self, expected, *, generation_id):
        effect_ids = tuple(sorted(receipt.effect_id for receipt in expected))
        retained = (*expected, *self.tombstones.values())
        return GraphitiProjectionReconciliationReceipt(
            generation_id=generation_id,
            expected_effect_ids=effect_ids,
            actual_effect_ids=effect_ids,
            authority_watermark=max(receipt.authority_watermark for receipt in retained),
            receipt_digest=DIGEST_A,
        )


class _Rights:
    def __init__(self) -> None:
        self.allowed = True

    def is_current(self, request) -> bool:
        return self.allowed


def _consumer(
    connection,
    authority,
    projector,
    rights,
    *,
    max_attempts=3,
    projection_generation_id=PROJECTION_GENERATION_ID,
):
    return GraphitiAdmissionConsumer(
        connection,
        authority=authority,
        projector=projector,
        rights=rights,
        clock=lambda: NOW,
        max_attempts=max_attempts,
        projection_generation_id=projection_generation_id,
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
    assert relation_request.proposed_endpoints == ("Alice", "Example Council")
    assert relation_request.relation_statement == "Alice briefed Example Council"
    assert relation_request.relation_temporal_bounds == {
        "valid_at": "2026-08-20T00:00:00Z",
        "invalid_at": None,
        "expired_at": None,
    }
    assert "private-alice" not in json.dumps(relation_request.canonical_value())
    retained_request = json.loads(
        connection.execute(
            "SELECT request_json FROM unpublished_graphiti_admission_queue "
            "WHERE proposal_kind='RELATION'"
        ).fetchone()[0]
    )
    assert retained_request["private_graph_receipt"]["source_node_uuid"] == (
        "private-alice"
    )
    assert relation_request.source_lineage["revision_id"] == source["revision_id"]
    assert len(projector.deliveries) == 1
    telemetry = consumer.telemetry()
    assert telemetry.proposal_denominator == 2
    assert telemetry.admitted_count == 1
    assert telemetry.held_count == 1
    assert telemetry.rejected_count == 0
    assert telemetry.admission_backlog == 0
    assert telemetry.contiguous_projection_watermark == 102
    reconciliation = consumer.reconcile_projection(
        generation_id=PROJECTION_GENERATION_ID
    )
    assert reconciliation.actual_effect_ids == tuple(
        receipt.effect_id for receipt in projector.deliveries.values()
    )
    assert consumer.telemetry().projection_reconciled is True
    assert consumer.telemetry().projection_gap_count == 0
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
    assert consumer.reconcile_projection(
        generation_id=PROJECTION_GENERATION_ID
    ).actual_effect_ids == ()
    assert consumer.telemetry().projection_reconciled is True

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
        def _decide(self, request, *, required_action, idempotency_key):
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


def test_malformed_claim_is_dead_lettered_without_blocking_later_work(tmp_path) -> None:
    connection = connect(str(tmp_path / "malformed-claim.sqlite3"))
    first = _draft("entity.0001", ExtractionProposalKind.ENTITY_MENTION)
    second = _draft("entity.0002", ExtractionProposalKind.ENTITY_MENTION)
    _seed_receipt(connection, first, second)
    authority = _Authority(
        {
            first.local_id: GraphitiProposalAdmissionAction.ADMIT,
            second.local_id: GraphitiProposalAdmissionAction.ADMIT,
        }
    )
    consumer = _consumer(connection, authority, _Projector(), _Rights())
    assert consumer.enqueue_complete_receipts() == 2
    connection.execute(
        "UPDATE unpublished_graphiti_admission_queue SET request_json='{}' "
        "WHERE queue_seq=(SELECT MIN(queue_seq) "
        "FROM unpublished_graphiti_admission_queue)",
    )
    connection.commit()

    report = consumer.drain(worker_id="worker-a", limit=1)

    assert report.claimed == 1
    assert report.projected == 1
    assert authority.calls[0][0].proposal.local_id == second.local_id
    assert consumer.telemetry().dead_letter_count == 1
    connection.close()


def test_cross_proposal_decision_identity_collision_never_marks_projected(
    tmp_path,
) -> None:
    connection = connect(str(tmp_path / "decision-collision.sqlite3"))
    first = _draft("entity.0001", ExtractionProposalKind.ENTITY_MENTION)
    second = _draft("entity.0002", ExtractionProposalKind.ENTITY_MENTION)
    _seed_receipt(connection, first, second)

    class CollidingAuthority(_Authority):
        def _decide(self, request, *, required_action, idempotency_key):
            decision = super()._decide(
                request,
                required_action=required_action,
                idempotency_key=idempotency_key,
            )
            return replace(decision, decision_id="decision:collision")

    consumer = _consumer(
        connection,
        CollidingAuthority(
            {
                first.local_id: GraphitiProposalAdmissionAction.ADMIT,
                second.local_id: GraphitiProposalAdmissionAction.ADMIT,
            }
        ),
        _Projector(),
        _Rights(),
    )
    consumer.enqueue_complete_receipts()

    report = consumer.drain(worker_id="worker-a", limit=2)

    assert report.projected == 1
    assert report.failed == 1
    states = dict(
        connection.execute(
            "SELECT proposal_key, state FROM unpublished_graphiti_admission_queue"
        )
    )
    assert sum(state == "PROJECTED" for state in states.values()) == 1
    assert sum(state == "READY" for state in states.values()) == 1
    connection.close()


def test_cross_proposal_projection_identity_collision_never_marks_projected(
    tmp_path,
) -> None:
    connection = connect(str(tmp_path / "projection-collision.sqlite3"))
    first = _draft("entity.0001", ExtractionProposalKind.ENTITY_MENTION)
    second = _draft("entity.0002", ExtractionProposalKind.ENTITY_MENTION)
    _seed_receipt(connection, first, second)

    class CollidingProjector(_Projector):
        def deliver_increment4_admitted(self, request, *, idempotency_key):
            receipt = super().deliver_increment4_admitted(
                request,
                idempotency_key=idempotency_key,
            )
            return replace(receipt, effect_id="effect:collision")

    consumer = _consumer(
        connection,
        _Authority(
            {
                first.local_id: GraphitiProposalAdmissionAction.ADMIT,
                second.local_id: GraphitiProposalAdmissionAction.ADMIT,
            }
        ),
        CollidingProjector(),
        _Rights(),
    )
    consumer.enqueue_complete_receipts()

    report = consumer.drain(worker_id="worker-a", limit=2)

    assert report.projected == 1
    assert report.failed == 1
    states = dict(
        connection.execute(
            "SELECT proposal_key, state FROM unpublished_graphiti_admission_queue"
        )
    )
    assert sum(state == "PROJECTED" for state in states.values()) == 1
    assert sum(state == "DECIDED" for state in states.values()) == 1
    connection.close()


def test_receipt_count_mismatch_is_an_explicit_integrity_hold(tmp_path) -> None:
    connection = connect(str(tmp_path / "count-mismatch.sqlite3"))
    draft = _draft("entity.0001", ExtractionProposalKind.ENTITY_MENTION)
    receipt = _seed_receipt(connection, draft)
    connection.execute(
        "UPDATE unpublished_graphiti_ingest SET entity_count=99 WHERE ingest_id=?",
        (receipt["ingest_id"],),
    )
    connection.commit()
    consumer = _consumer(connection, _Authority({}), _Projector(), _Rights())

    assert consumer.enqueue_complete_receipts() == 0
    assert consumer.telemetry().integrity_hold_receipt_count == 1
    connection.close()


def test_projection_reconciliation_refuses_missing_admitted_effect(tmp_path) -> None:
    connection = connect(str(tmp_path / "projection-gap.sqlite3"))
    first = _draft("entity.0001", ExtractionProposalKind.ENTITY_MENTION)
    second = _draft("entity.0002", ExtractionProposalKind.ENTITY_MENTION)
    _seed_receipt(connection, first, second)

    class FailingSecondProjector(_Projector):
        def deliver_increment4_admitted(self, request, *, idempotency_key):
            if request.request.proposal.local_id == second.local_id:
                raise RuntimeError("fixture projection failure")
            return super().deliver_increment4_admitted(
                request, idempotency_key=idempotency_key
            )

    consumer = _consumer(
        connection,
        _Authority(
            {
                first.local_id: GraphitiProposalAdmissionAction.ADMIT,
                second.local_id: GraphitiProposalAdmissionAction.ADMIT,
            }
        ),
        FailingSecondProjector(),
        _Rights(),
    )
    consumer.enqueue_complete_receipts()
    assert consumer.drain(worker_id="worker-a", limit=2).failed == 1

    with pytest.raises(Exception, match="missing governed effects"):
        consumer.reconcile_projection(
            generation_id=PROJECTION_GENERATION_ID
        )
    assert consumer.telemetry().projection_gap_count == 1
    assert consumer.telemetry().projection_reconciled is False
    connection.close()


def test_rights_reconciliation_failure_is_durable_and_does_not_block_later_rows(
    tmp_path,
) -> None:
    connection = connect(str(tmp_path / "rights-retry.sqlite3"))
    first = _draft("entity.0001", ExtractionProposalKind.ENTITY_MENTION)
    second = _draft("entity.0002", ExtractionProposalKind.ENTITY_MENTION)
    _seed_receipt(connection, first, second)

    class FailingFirstTombstoneProjector(_Projector):
        failed = False

        def tombstone_increment4_admitted(self, request, *, idempotency_key):
            if not self.failed:
                self.failed = True
                raise RuntimeError("fixture tombstone failure")
            return super().tombstone_increment4_admitted(
                request, idempotency_key=idempotency_key
            )

    projector = FailingFirstTombstoneProjector()
    rights = _Rights()
    consumer = _consumer(
        connection,
        _Authority(
            {
                first.local_id: GraphitiProposalAdmissionAction.ADMIT,
                second.local_id: GraphitiProposalAdmissionAction.ADMIT,
            }
        ),
        projector,
        rights,
    )
    consumer.enqueue_complete_receipts()
    assert consumer.drain(worker_id="worker-a", limit=2).projected == 2
    rights.allowed = False

    assert consumer.reconcile_rights(limit=2) == 1
    failure = connection.execute(
        "SELECT attempt_count, last_error FROM unpublished_graphiti_admission_queue "
        "WHERE state='PROJECTED'"
    ).fetchone()
    assert failure is not None
    assert failure[0] == 1
    assert str(failure[1]).startswith("RIGHTS_RECONCILIATION:")
    assert consumer.reconcile_rights(limit=2) == 1
    assert consumer.telemetry().revoked_count == 2
    connection.close()


def test_passage_rights_ids_must_bind_exact_retained_authority(tmp_path) -> None:
    connection = connect(str(tmp_path / "passage-rights.sqlite3"))
    draft = _draft("entity.0001", ExtractionProposalKind.ENTITY_MENTION)
    receipt = _seed_receipt(connection, draft)
    tampered = dict(receipt)
    tampered["passages"] = [
        {**receipt["passages"][0], "admission_id": "bogus-admission"}
    ]
    unsigned = dict(tampered)
    unsigned.pop("receipt_digest")
    tampered_digest = digest_bytes(canonical_json_bytes(unsigned))
    tampered["receipt_digest"] = tampered_digest
    connection.execute(
        "UPDATE unpublished_graphiti_ingest SET receipt_digest=? WHERE ingest_id=?",
        (tampered_digest, receipt["ingest_id"]),
    )
    connection.execute(
        "UPDATE unpublished_graphiti_receipts SET receipt_json=? WHERE ingest_id=?",
        (json.dumps(tampered, sort_keys=True), receipt["ingest_id"]),
    )
    connection.commit()
    consumer = _consumer(connection, _Authority({}), _Projector(), _Rights())

    assert consumer.enqueue_complete_receipts() == 0
    assert consumer.telemetry().integrity_hold_receipt_count == 1
    connection.close()


def test_projector_cannot_raise_the_authority_watermark(tmp_path) -> None:
    connection = connect(str(tmp_path / "watermark.sqlite3"))
    draft = _draft("entity.0001", ExtractionProposalKind.ENTITY_MENTION)
    _seed_receipt(connection, draft)

    class InflatingProjector(_Projector):
        def deliver_increment4_admitted(self, request, *, idempotency_key):
            receipt = super().deliver_increment4_admitted(
                request, idempotency_key=idempotency_key
            )
            return replace(receipt, authority_watermark=999_999)

    consumer = _consumer(
        connection,
        _Authority({draft.local_id: GraphitiProposalAdmissionAction.ADMIT}),
        InflatingProjector(),
        _Rights(),
    )
    consumer.enqueue_complete_receipts()

    report = consumer.drain(worker_id="worker-a", limit=1)

    assert report.failed == 1
    assert report.projected == 0
    assert consumer.telemetry().contiguous_projection_watermark is None
    connection.close()


def test_relation_admit_requires_current_endpoint_authority(tmp_path) -> None:
    connection = connect(str(tmp_path / "endpoint-authority.sqlite3"))
    draft = _draft("relation.0001", ExtractionProposalKind.RELATION)
    _seed_receipt(connection, draft)

    class StaleEndpointAuthority(_Authority):
        def relation_endpoint_resolutions_current(self, request, decision):
            return False

    consumer = _consumer(
        connection,
        StaleEndpointAuthority(
            {draft.local_id: GraphitiProposalAdmissionAction.ADMIT}
        ),
        _Projector(),
        _Rights(),
    )
    consumer.enqueue_complete_receipts()

    report = consumer.drain(worker_id="worker-a", limit=1)

    assert report.failed == 1
    assert report.projected == 0
    assert consumer.telemetry().admitted_count == 0
    connection.close()


def test_relation_projection_retry_rechecks_endpoint_authority(tmp_path) -> None:
    connection = connect(str(tmp_path / "endpoint-retry.sqlite3"))
    draft = _draft("relation.0001", ExtractionProposalKind.RELATION)
    _seed_receipt(connection, draft)
    authority = _Authority(
        {draft.local_id: GraphitiProposalAdmissionAction.ADMIT}
    )
    projector = _Projector()
    projector.raise_after_first_effect = True
    consumer = _consumer(connection, authority, projector, _Rights())
    consumer.enqueue_complete_receipts()
    assert consumer.drain(worker_id="worker-a", limit=1).failed == 1
    authority.endpoints_current = False

    retry = consumer.drain(worker_id="worker-b", limit=1)

    assert retry.failed == 0
    assert retry.projected == 0
    assert consumer.telemetry().projected_count == 1
    assert consumer.telemetry().revoked_count == 1
    assert len(projector.tombstones) == 1
    connection.close()


def test_reconciliation_rejects_cross_generation_receipts(tmp_path) -> None:
    connection = connect(str(tmp_path / "generation-drift.sqlite3"))
    draft = _draft("entity.0001", ExtractionProposalKind.ENTITY_MENTION)
    _seed_receipt(connection, draft)
    authority = _Authority(
        {draft.local_id: GraphitiProposalAdmissionAction.ADMIT}
    )
    projector = _Projector()
    consumer = _consumer(connection, authority, projector, _Rights())
    consumer.enqueue_complete_receipts()
    assert consumer.drain(worker_id="worker-a", limit=1).projected == 1
    reopened = _consumer(
        connection,
        authority,
        projector,
        _Rights(),
        projection_generation_id=SECOND_PROJECTION_GENERATION_ID,
    )

    with pytest.raises(Exception, match="another generation"):
        reopened.reconcile_projection(
            generation_id=SECOND_PROJECTION_GENERATION_ID
        )
    connection.close()


def test_permanent_rights_tombstone_failure_dead_letters_and_fails_closed(
    tmp_path,
) -> None:
    connection = connect(str(tmp_path / "rights-dead-letter.sqlite3"))
    draft = _draft("entity.0001", ExtractionProposalKind.ENTITY_MENTION)
    _seed_receipt(connection, draft)

    class BrokenTombstoneProjector(_Projector):
        def tombstone_increment4_admitted(self, request, *, idempotency_key):
            raise RuntimeError("fixture permanent tombstone failure")

    rights = _Rights()
    consumer = _consumer(
        connection,
        _Authority({draft.local_id: GraphitiProposalAdmissionAction.ADMIT}),
        BrokenTombstoneProjector(),
        rights,
        max_attempts=2,
    )
    consumer.enqueue_complete_receipts()
    assert consumer.drain(worker_id="worker-a", limit=1).projected == 1
    consumer.reconcile_projection(generation_id=PROJECTION_GENERATION_ID)
    assert consumer.telemetry().projection_reconciled is True
    rights.allowed = False

    assert consumer.reconcile_rights(limit=1) == 0
    assert consumer.reconcile_rights(limit=1) == 0
    telemetry = consumer.telemetry()
    assert telemetry.dead_letter_count == 1
    assert telemetry.projection_gap_count == 1
    assert telemetry.projection_reconciled is False
    with pytest.raises(Exception, match="rights tombstone failures"):
        consumer.reconcile_projection(generation_id=PROJECTION_GENERATION_ID)
    connection.close()


def test_recovered_projection_tombstone_failure_uses_rights_failure_state(
    tmp_path,
) -> None:
    connection = connect(str(tmp_path / "recovered-rights-failure.sqlite3"))
    draft = _draft("relation.0001", ExtractionProposalKind.RELATION)
    _seed_receipt(connection, draft)
    authority = _Authority(
        {draft.local_id: GraphitiProposalAdmissionAction.ADMIT}
    )

    class BrokenRecoveryTombstoneProjector(_Projector):
        def tombstone_increment4_admitted(self, request, *, idempotency_key):
            raise RuntimeError("fixture recovered tombstone failure")

    projector = BrokenRecoveryTombstoneProjector()
    projector.raise_after_first_effect = True
    consumer = _consumer(connection, authority, projector, _Rights())
    consumer.enqueue_complete_receipts()
    assert consumer.drain(worker_id="worker-a", limit=1).failed == 1
    authority.endpoints_current = False

    retry = consumer.drain(worker_id="worker-b", limit=1)

    assert retry.failed == 1
    row = connection.execute(
        "SELECT state, last_error FROM unpublished_graphiti_admission_queue"
    ).fetchone()
    assert row[0] == "PROJECTED"
    assert str(row[1]).startswith("RIGHTS_RECONCILIATION:")
    assert consumer.telemetry().projection_reconciled is False
    assert consumer.telemetry().projection_gap_count == 1
    connection.close()
