from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from newsroom.authority import AuthorityPersistenceError, canonical_json_bytes, digest_bytes
from newsroom.relations import (
    INTEGRATED_FIXTURE_V2,
    RelationCurrentState,
    RelationDecisionAction,
    RelationProducer,
    RelationProducerKind,
    RelationProposalId,
)

from .relation_2a_helpers import (
    BINDING_ID,
    RELATION_NOW,
    SECOND_PROPOSAL_ID,
    bind_fixture_and_propose,
    decision_request,
    open_fixture_object_system,
    open_relation_system,
    proof,
    seed_fixture_objects,
)


def _drop_trigger(conn: sqlite3.Connection, name: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",
        (name,),
    ).fetchone()
    assert row is not None and row[0]
    sql = str(row[0])
    conn.execute(f'DROP TRIGGER "{name}"')
    return sql


def _admit_fixture_relation(database: Path, object_root: Path):
    seeded = seed_fixture_objects(database, object_root=object_root)
    proposal = bind_fixture_and_propose(database, seeded)
    with open_relation_system(database) as system:
        admitted = system.relations.decide(
            decision_request(
                proposal,
                action=RelationDecisionAction.ADMIT,
                key="admit-for-lifecycle",
            ),
            proof=proof(),
        )
    assert admitted.assertion is not None
    return seeded, proposal, admitted


def test_relation_revocation_removes_projection_without_deleting_history(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seeded, proposal, admitted = _admit_fixture_relation(
        database, tmp_path / "objects"
    )

    with open_relation_system(database) as system:
        revoked = system.relations.decide(
            decision_request(
                proposal,
                action=RelationDecisionAction.REVOKE,
                expected_version=1,
                previous_decision_id=admitted.decision.decision_id,
                key="revoke-relation",
            ),
            proof=proof(),
        )
        assert revoked.current_state is RelationCurrentState.REVOKED
        assert revoked.assertion is None
        assert system.relations.admitted(
            valid_at=RELATION_NOW, proof=proof()
        ) == ()
        events = system.relations.projection_events_after(
            0, valid_at=RELATION_NOW, proof=proof()
        )
        assert [item.action.value for item in events] == ["UPSERT", "REMOVE"]
        assert events[-1].reason_code == "RELATION_REVOKED"
        assert events[0].assertion == admitted.assertion
        assert system.relations.decision(
            admitted.decision.decision_id, proof=proof()
        ) == admitted.decision

    with open_relation_system(database) as reopened:
        assert reopened.relations.proposal(proposal.proposal_id, proof=proof()) == proposal
        assert reopened.relations.admitted(
            valid_at=RELATION_NOW, proof=proof()
        ) == ()


def test_relation_invalidation_removes_admitted_projection(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    _seeded, proposal, admitted = _admit_fixture_relation(
        database, tmp_path / "objects"
    )

    with open_relation_system(database) as system:
        invalidated = system.relations.decide(
            decision_request(
                proposal,
                action=RelationDecisionAction.INVALIDATE,
                expected_version=1,
                previous_decision_id=admitted.decision.decision_id,
                key="invalidate-relation",
            ),
            proof=proof(),
        )
        assert invalidated.current_state is RelationCurrentState.INVALIDATED
        events = system.relations.projection_events_after(
            admitted.decision.authority_ledger_seq,
            valid_at=RELATION_NOW,
            proof=proof(),
        )
        assert len(events) == 1
        assert events[0].action.value == "REMOVE"
        assert events[0].reason_code == "RELATION_INVALIDATED"


def test_relation_supersession_links_successor_and_removes_prior_assertion(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seeded, proposal, admitted = _admit_fixture_relation(
        database, tmp_path / "objects"
    )
    successor_request = INTEGRATED_FIXTURE_V2.relation.request(
        proposal_id=SECOND_PROPOSAL_ID,
        fixture_binding_id=BINDING_ID,
        idempotency_key="successor-proposal",
    )
    successor_request = successor_request.__class__(
        proposal_id=successor_request.proposal_id,
        fixture_binding_id=successor_request.fixture_binding_id,
        subject=successor_request.subject,
        predicate=successor_request.predicate,
        object=successor_request.object,
        temporal_scope=successor_request.temporal_scope,
        evidence_passage_ids=successor_request.evidence_passage_ids,
        producer=RelationProducer(
            RelationProducerKind.AUTHORISED_OPERATOR,
            "fixture-reviewer",
            "fixture-reviewer-v2",
            "fixture-supersession-rule-v1",
        ),
        statement="A later synthetic proposal supersedes the admitted assertion.",
        uncertainties=successor_request.uncertainties,
        idempotency_key=successor_request.idempotency_key,
    )

    with open_relation_system(database) as system:
        successor = system.relations.propose(successor_request, proof=proof())
        superseded = system.relations.decide(
            decision_request(
                proposal,
                action=RelationDecisionAction.SUPERSEDE,
                expected_version=1,
                previous_decision_id=admitted.decision.decision_id,
                successor_proposal_id=successor.proposal_id,
                key="supersede-relation",
            ),
            proof=proof(),
        )
        assert superseded.current_state is RelationCurrentState.SUPERSEDED
        assert superseded.decision.successor_proposal_id == successor.proposal_id
        assert system.relations.admitted(
            valid_at=RELATION_NOW, proof=proof()
        ) == ()
        events = system.relations.projection_events_after(
            admitted.decision.authority_ledger_seq,
            valid_at=RELATION_NOW,
            proof=proof(),
        )
        assert len(events) == 1
        assert events[0].reason_code == "RELATION_SUPERSEDED"
        assert system.relations.proposal(successor.proposal_id, proof=proof()) == successor


def test_governed_evidence_revocation_removes_relation_and_links_admission(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    seeded, _proposal, admitted = _admit_fixture_relation(database, object_root)
    target = seeded.admission_by_passage_id["ifv2-new-en"]

    with open_fixture_object_system(database, object_root=object_root) as objects:
        revocation = objects.objects.revoke(
            target,
            reason_code="FIXTURE_EVIDENCE_REVOKED",
            idempotency_key="revoke-fixture-evidence",
            proof=proof(),
        )

    with open_relation_system(database) as system:
        assert system.relations.admitted(
            valid_at=RELATION_NOW, proof=proof()
        ) == ()
        events = system.relations.projection_events_after(
            admitted.decision.authority_ledger_seq,
            valid_at=RELATION_NOW,
            proof=proof(),
        )
        assert len(events) == 1
        assert events[0].action.value == "REMOVE"
        assert events[0].source_event_id == revocation.event_id
        assert events[0].reason_code == "OBJECT_ADMISSION_REVOKED"
        assert events[0].tombstone_object_admission_ids == (target,)


def test_governed_deletion_tombstone_is_latest_removal_and_never_resurrects(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    seeded, _proposal, admitted = _admit_fixture_relation(database, object_root)
    passage = INTEGRATED_FIXTURE_V2.passage_by_id["ifv2-new-en"]
    target = seeded.admission_by_passage_id[passage.passage_id]

    with open_fixture_object_system(database, object_root=object_root) as objects:
        objects.objects.revoke(
            target,
            reason_code="FIXTURE_EVIDENCE_REVOKED",
            idempotency_key="delete-revoke",
            proof=proof(),
        )
        deletion = objects.objects.request_deletion(
            passage.blob_digest,
            reason_code="FIXTURE_EVIDENCE_DELETE",
            idempotency_key="delete-request",
            proof=proof(),
        )
        tombstone = objects.objects.tombstone(
            deletion.deletion_id,
            reason_code="FIXTURE_EVIDENCE_TOMBSTONE",
            idempotency_key="delete-tombstone",
            proof=proof(),
        )

    with open_relation_system(database) as system:
        events = system.relations.projection_events_after(
            admitted.decision.authority_ledger_seq,
            valid_at=RELATION_NOW,
            proof=proof(),
        )
        assert len(events) == 1
        assert events[0].source_event_id == tombstone.event_id
        assert events[0].reason_code == "OBJECT_DELETION_TOMBSTONED"
        assert events[0].tombstone_object_admission_ids == (target,)
        assert system.relations.admitted(
            valid_at=RELATION_NOW, proof=proof()
        ) == ()

    with open_relation_system(database) as reopened:
        assert reopened.relations.admitted(
            valid_at=RELATION_NOW, proof=proof()
        ) == ()
        assert reopened.relations.projection_events_after(
            admitted.decision.authority_ledger_seq,
            valid_at=RELATION_NOW,
            proof=proof(),
        )[0].reason_code == "OBJECT_DELETION_TOMBSTONED"


def test_latest_lifecycle_event_and_reason_remain_exact_with_multiple_invalid_objects(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    seeded, _proposal, admitted = _admit_fixture_relation(database, object_root)
    first_passage = INTEGRATED_FIXTURE_V2.passage_by_id["ifv2-new-en"]
    first = seeded.admission_by_passage_id[first_passage.passage_id]
    second = seeded.admission_by_passage_id["ifv2-prior-zh-hk"]

    with open_fixture_object_system(database, object_root=object_root) as objects:
        objects.objects.revoke(
            first,
            reason_code="FIRST_REVOKED",
            idempotency_key="multi-first-revoke",
            proof=proof(),
        )
        objects.objects.revoke(
            second,
            reason_code="SECOND_REVOKED",
            idempotency_key="multi-second-revoke",
            proof=proof(),
        )
        deletion = objects.objects.request_deletion(
            first_passage.blob_digest,
            reason_code="FIRST_DELETE",
            idempotency_key="multi-first-delete",
            proof=proof(),
        )
        tombstone = objects.objects.tombstone(
            deletion.deletion_id,
            reason_code="FIRST_TOMBSTONE",
            idempotency_key="multi-first-tombstone",
            proof=proof(),
        )

    with open_relation_system(database) as system:
        events = system.relations.projection_events_after(
            admitted.decision.authority_ledger_seq,
            valid_at=RELATION_NOW,
            proof=proof(),
        )
        assert len(events) == 1
        assert events[0].source_event_id == tombstone.event_id
        assert events[0].reason_code == "OBJECT_DELETION_TOMBSTONED"
        assert events[0].tombstone_object_admission_ids == tuple(
            sorted((first, second), key=str)
        )


def test_reopen_rejects_proposal_column_rebinding(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    seeded = seed_fixture_objects(database, object_root=tmp_path / "objects")
    bind_fixture_and_propose(database, seeded)

    conn = sqlite3.connect(database)
    try:
        trigger = _drop_trigger(conn, "immutable_relation_proposal_update")
        conn.execute(
            "UPDATE relation_proposals SET producer_version='tampered-v9'"
        )
        conn.execute(trigger)
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(AuthorityPersistenceError, match="canonical|semantic"):
        open_relation_system(database)


def test_reopen_rejects_proposal_evidence_rebinding(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    seeded = seed_fixture_objects(database, object_root=tmp_path / "objects")
    bind_fixture_and_propose(database, seeded)
    replacement = seeded.admission_by_passage_id["ifv2-prior-en"]
    replacement_digest = INTEGRATED_FIXTURE_V2.passage_by_id[
        "ifv2-prior-en"
    ].blob_digest

    conn = sqlite3.connect(database)
    try:
        trigger = _drop_trigger(conn, "immutable_relation_proposal_evidence_update")
        conn.execute(
            "UPDATE relation_proposal_evidence SET admission_id=?,blob_digest=? "
            "WHERE passage_id='ifv2-new-en'",
            (str(replacement), replacement_digest),
        )
        conn.execute(trigger)
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(AuthorityPersistenceError, match="cross-record"):
        open_relation_system(database)


def test_reopen_rejects_decision_head_rebinding(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    _seeded, _proposal, _admitted = _admit_fixture_relation(
        database, tmp_path / "objects"
    )

    conn = sqlite3.connect(database)
    try:
        trigger = _drop_trigger(conn, "relation_decision_head_update_guard")
        conn.execute(
            "UPDATE relation_decision_heads SET current_state='REJECTED'"
        )
        conn.execute(trigger)
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(AuthorityPersistenceError, match="decision head"):
        open_relation_system(database)


def test_reopen_rejects_assertion_canonical_tampering(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    _seeded, _proposal, _admitted = _admit_fixture_relation(
        database, tmp_path / "objects"
    )

    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM relation_assertions").fetchone()
        assert row is not None
        value = json.loads(bytes(row["canonical_bytes"]).decode("utf-8"))
        value["statement"] = "Tampered but re-digested assertion bytes."
        canonical = canonical_json_bytes(value)
        trigger = _drop_trigger(conn, "immutable_relation_assertion_update")
        conn.execute(
            "UPDATE relation_assertions SET canonical_bytes=?,canonical_digest=?",
            (canonical, digest_bytes(canonical)),
        )
        conn.execute(trigger)
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(AuthorityPersistenceError, match="assertion"):
        open_relation_system(database)


def test_reopen_rejects_governed_rights_canonical_tampering(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seeded = seed_fixture_objects(database, object_root=tmp_path / "objects")
    bind_fixture_and_propose(database, seeded)

    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT r.* FROM object_rights_decisions r "
            "JOIN object_admissions a ON a.rights_decision_id=r.rights_decision_id "
            "WHERE a.admission_id=?",
            (str(seeded.manifest_admission_id),),
        ).fetchone()
        assert row is not None
        value = json.loads(bytes(row["canonical_bytes"]).decode("utf-8"))
        value["reason_code"] = "TAMPERED"
        canonical = canonical_json_bytes(value)
        trigger = _drop_trigger(
            conn, "immutable_object_rights_decisions_update"
        )
        conn.execute(
            "UPDATE object_rights_decisions SET canonical_bytes=?,canonical_digest=? "
            "WHERE rights_decision_id=?",
            (canonical, digest_bytes(canonical), str(row["rights_decision_id"])),
        )
        conn.execute(trigger)
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(AuthorityPersistenceError, match="rights canonical"):
        open_relation_system(database)
