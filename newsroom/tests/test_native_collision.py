from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace

import pytest

from newsroom.authority import AuthorityEvents
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.types import AggregateId, ObjectAdmissionId
from newsroom.control_plane.native_collision import (
    NativeCollisionAuthority,
    NativeCollisionHold,
    NativeCollisionIdentity,
)
from newsroom.control_plane.native_cycle import _revision_successor, advance_native_cycle
from newsroom.increment5.branch_contracts import BranchMode, BranchOutcome
from newsroom.increment5.native_retrieval import (
    NATIVE_VECTOR_PROFILE,
    NativeDocumentReceipt,
    NativeGraphBranchReceipt,
    NativeRetrievalContext,
    NativeRetrievalContextReadPort,
    NativeRetrievalContextReceipt,
    NativeRetrievalContextRequest,
    NativeVectorBranchReceipt,
)
from newsroom.increment6.collision import (
    CandidateUseOperation,
    CurrentCollisionEligibilityBlocked,
)
from newsroom.increment6.hypotheses import EventHypothesis
from newsroom.increment6.dispositions import CurrentCandidateCitation
from newsroom.increment6.work_items import RetrievalBindingState, RetrievalInputBinding
from newsroom.tests.discovery_3d_authority_helpers import (
    exact_admission_request,
    proof,
    seed_check_lineage,
)
from newsroom.tests.test_increment5d1_hybrid_composer import (
    _coherent_system,
    _parse_receipt,
    authorize,
)
from newsroom.tests.test_native_triage import (
    _actor_digest,
    _no_match_retrieval,
    _shared_system,
)


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def _native_binding(tmp_path, lead):
    root = tmp_path / "branches"
    root.mkdir()
    dispatcher, requests = _coherent_system(root)
    raw = []
    for index in (0, 1, 3):
        result = dispatcher.execute(
            requests[index], authorize(root, requests[index], name=f"native-{index}")
        )
        assert result.upstream_raw_receipt_bytes is not None
        raw.append(
            _parse_receipt(
                result.receipt.tool_id, result.upstream_raw_receipt_bytes
            )
        )
    exact, fulltext, graph = raw
    assert fulltext.snapshot is not None
    vector = NativeVectorBranchReceipt(
        str(uuid.uuid4()),
        _digest("1"),
        BranchMode.VECTOR,
        BranchOutcome.COMPLETE,
        "NO_MATCH",
        str(fulltext.snapshot.generation_id),
        fulltext.snapshot.generation_identity_digest,
        NATIVE_VECTOR_PROFILE,
        graph.query_valid_time,
        graph.serving_time,
        (),
        1,
    )
    native_graph = NativeGraphBranchReceipt(
        str(uuid.uuid4()),
        _digest("3"),
        (str(lead.request.lead_id),),
        "graph.increment4.admitted",
        "increment4-admitted-v1",
        "increment4-neo4j-v1",
        _digest("4"),
        _digest("5"),
        vector.generation_id,
        "authority-selected-active",
        10,
        graph.query_valid_time,
        graph.serving_time,
        (),
        (),
        reason="NO_MATCH",
    )
    document = NativeDocumentReceipt(
        "native-document-event",
        "native-document-command",
        AggregateId.new(),
        1,
        ObjectAdmissionId.new(),
        _digest("2"),
        ObjectAdmissionId.new(),
        ObjectAdmissionId.new(),
    )
    request = NativeRetrievalContextRequest(
        str(uuid.uuid4()),
        "native-context",
        AggregateId.new(),
        0,
        str(lead.request.lead_id),
        lead.canonical_digest,
        "source-a",
        exact.canonical_bytes,
        fulltext.canonical_bytes,
        vector.canonical_bytes,
        native_graph.canonical_bytes,
        (document,),
    )
    branch_bytes = (
        request.exact_receipt_bytes,
        request.fulltext_receipt_bytes,
        request.vector_receipt_bytes,
        request.graph_receipt_bytes,
    )
    context = NativeRetrievalContext(
        str(uuid.uuid4()),
        request.request_id,
        request.request_digest,
        request.lead_id,
        request.lead_digest,
        request.authority_scope_id,
        vector.generation_id,
        vector.query_valid_time,
        vector.serving_time,
        tuple(digest_bytes(item) for item in branch_bytes),
        tuple(json.loads(item) for item in branch_bytes),
        (document.projection_value(),),
        "COMPLETE",
        False,
    )
    receipt = NativeRetrievalContextReceipt(
        context.context_id,
        request.request_id,
        request.request_digest,
        request.aggregate_id,
        1,
        "native-context-event",
        "native-context-command",
        ObjectAdmissionId.new(),
        context.digest,
        request.authority_scope_id,
        context.generation_id,
        context.query_valid_time,
        context.serving_time,
        *branch_bytes,
        "principal.alpha",
        "newsroom.authority",
        no_match=False,
    )
    binding = RetrievalInputBinding(
        RetrievalBindingState.RECEIPT,
        request.request_id,
        request.idempotency_key,
        request.request_digest,
        request.canonical_bytes,
        context.context_id,
        receipt.receipt_digest,
        receipt.outcome,
        receipt.reason,
        receipt.no_match,
        receipt.canonical_bytes,
    )
    return binding, receipt, context


def _read_port(contexts):
    # Production obtains this exact type from NativeRetrievalDocuments.
    port = object.__new__(NativeRetrievalContextReadPort)
    object.__setattr__(port, "_read", lambda receipt: contexts[receipt.context_id])
    return port


def _native_collision(tmp_path, contexts, receipts, *, authorized=True) -> NativeCollisionAuthority:
    def provenance(event_id, _proof):
        receipt = receipts[event_id]
        authentication_context_id = "native-context-authentication"
        decision_id = "00000000-0000-4000-8000-000000006201"
        decision_bytes = canonical_json_bytes({
            "authorization_decision_id": decision_id,
            "allowed": authorized,
            "event_id": event_id,
        })
        return SimpleNamespace(
            event=SimpleNamespace(
                event_id=receipt.event_id,
                command_id=receipt.command_id,
                aggregate_id=str(receipt.aggregate_id),
                aggregate_version=receipt.aggregate_version,
                object_admission_id=str(receipt.admission_id),
                payload_digest=receipt.context_object_digest,
                principal_id="principal.alpha",
                authentication_context_id=authentication_context_id,
                authorization_request_digest=_digest("a"),
                authorization_decision_id=decision_id,
            ),
            authentication=SimpleNamespace(
                authentication_context_id=authentication_context_id,
                principal_id="principal.alpha",
                authority_domain="newsroom.authority",
            ),
            authorization_request=SimpleNamespace(
                authentication_context_id=authentication_context_id,
                principal_id="principal.alpha",
                authority_domain="newsroom.authority",
                request_digest=_digest("a"),
                operation_type="command:retrieval.native_context.admit",
                required_scope="authority.retrieval.context",
            ),
            authorization_decision=SimpleNamespace(
                authentication_context_id=authentication_context_id,
                authorization_request_digest=_digest("a"),
                authorization_decision_id=decision_id,
                allowed=authorized,
                canonical_bytes=decision_bytes,
                canonical_digest=digest_bytes(decision_bytes),
            ),
            command_definition=SimpleNamespace(
                command_type="retrieval.native_context.admit",
            ),
        )

    return NativeCollisionAuthority(
        authority_path=tmp_path / "native.sqlite3",
        journal_path=tmp_path / "native-collision.sqlite3",
        identity=NativeCollisionIdentity(
            "source-a",
            "principal.alpha",
            "newsroom.authority",
        ),
        context_reader=lambda receipt, *, proof: contexts[receipt.context_id],
        events=AuthorityEvents(
            policy_id="native-collision-test-events",
            read=lambda *_: (),
            provenance=provenance,
            result=lambda *_: pytest.fail("unexpected command-result read"),
        ),
    )


def test_native_collision_reads_current_candidate_and_replays_after_restart(
    tmp_path, monkeypatch
) -> None:
    retrieval_authority, _ = _no_match_retrieval(tmp_path)
    contexts = {}
    receipts = {}
    retrieval_authority._native_context_read_port = _read_port(contexts)
    collision = _native_collision(tmp_path, contexts, receipts)
    with _shared_system(
        tmp_path, monkeypatch, retrieval_authority, collision=collision.enforcer
    ) as system:
        seed_check_lineage(system)
        admitted = system.discovery.admit_signal_to_lead(
            exact_admission_request(), proof=proof()
        )
        status = system.discovery.current_status(
            admitted.lead.request.signal_id, proof=proof()
        )
        retrieval, receipt, context = _native_binding(tmp_path, status.lead)
        assert not retrieval.no_match
        contexts[context.context_id] = context
        receipts[receipt.event_id] = receipt
        outcome = advance_native_cycle(
            system,
            (status,),
            retrieval=type(
                "Retrieval",
                (),
                {"retrieve": lambda self, lead, *, proof: retrieval},
            )(),
            collision_requests=collision,
            actor_identity_digest=_actor_digest(),
            proof=proof(),
            owner_stop_check=lambda: None,
            owner_stop_fence=nullcontext,
        )[0]
        assert outcome.state == "CANDIDATE_ADMITTED"
        triage = outcome.triage
        candidate = outcome.triage.candidate
        assert candidate is not None

    reopened_collision = _native_collision(tmp_path, contexts, receipts)
    with _shared_system(
        tmp_path,
        monkeypatch,
        retrieval_authority,
        collision=reopened_collision.enforcer,
    ) as reopened:
        replay = advance_native_cycle(
            reopened,
            (status,),
            retrieval=type(
                "Retrieval",
                (),
                {"retrieve": lambda self, lead, *, proof: retrieval},
            )(),
            collision_requests=reopened_collision,
            actor_identity_digest=_actor_digest(),
            proof=proof(),
            owner_stop_check=lambda: None,
            owner_stop_fence=nullcontext,
        )[0]
        assert replay.state == "CANDIDATE_ADMITTED"
        assert replay.triage.candidate == candidate

        citation = reopened_collision.current_candidate_citation(
            status.lead, retrieval, proof=proof()
        )
        assert citation is not None
        stale_values = {
            field: getattr(citation, field)
            for field in citation.__dataclass_fields__
            if field != "citation_id"
        }
        stale_values["candidate_version_digest"] = "sha256:" + "0" * 64
        with pytest.raises(NativeCollisionHold, match="CURRENT_CANDIDATE_CITATION_STALE"):
            _revision_successor(
                reopened,
                status.lead,
                CurrentCandidateCitation.create(**stale_values),
                proof=proof(),
            )

        proposal_id = str(uuid.uuid4())
        hypothesis_id = EventHypothesis.allocate(
            proposal_id, triage.hypothesis.proposal_local_id
        ).hypothesis_id
        other_hypothesis = replace(
            triage.hypothesis,
            hypothesis_id=hypothesis_id,
            version_id=str(uuid.uuid5(uuid.UUID(hypothesis_id), "version:1")),
            proposal_id=proposal_id,
        )
        occupied = reopened_collision.request(
            replace(triage, hypothesis=other_hypothesis), retrieval, proof=proof()
        )
        assert occupied.binding.operation is CandidateUseOperation.USE_CURRENT_CANDIDATE
        assert occupied.binding.expected_candidate_id == candidate.candidate_id

    with sqlite3.connect(tmp_path / "native-collision.sqlite3") as journal:
        states = {
            row[0]
            for row in journal.execute(
                "SELECT collision_state FROM native_collision_receipts"
            )
        }
        assert journal.execute(
            "SELECT count(*) FROM native_collision_requests"
        ).fetchone()[0] == 3
    assert states == {"UNOCCUPIED", "OCCUPIED"}
    assert NativeRetrievalContextReceipt.from_bytes(receipt.canonical_bytes) == receipt


def test_native_collision_rechecks_watermark_and_rejects_cross_work_binding(
    tmp_path, monkeypatch
) -> None:
    retrieval_authority, legacy_retrieval = _no_match_retrieval(tmp_path)
    contexts = {}
    receipts = {}
    retrieval_authority._native_context_read_port = _read_port(contexts)
    collision = _native_collision(tmp_path, contexts, receipts)
    with _shared_system(
        tmp_path, monkeypatch, retrieval_authority, collision=collision.enforcer
    ) as system:
        seed_check_lineage(system)
        admitted = system.discovery.admit_signal_to_lead(
            exact_admission_request(), proof=proof()
        )
        status = system.discovery.current_status(
            admitted.lead.request.signal_id, proof=proof()
        )
        retrieval, receipt, context = _native_binding(tmp_path, status.lead)
        contexts[context.context_id] = context
        receipts[receipt.event_id] = receipt
        held = advance_native_cycle(
            system,
            (status,),
            retrieval=type(
                "Retrieval",
                (),
                {"retrieve": lambda self, lead, *, proof: retrieval},
            )(),
            collision_requests=type(
                "Hold",
                (),
                {"request": lambda self, triage, retrieval, *, proof: None},
            )(),
            actor_identity_digest=_actor_digest(),
            proof=proof(),
            owner_stop_check=lambda: None,
            owner_stop_fence=nullcontext,
        )[0]
        request = collision.request(held.triage, retrieval, proof=proof())
        with pytest.raises(NativeCollisionHold, match="AUTHORITY_DIFFERS"):
            collision.request(
                replace(
                    held.triage,
                    work=replace(
                        held.triage.work,
                        version=replace(
                            held.triage.work.version,
                            retrieval=legacy_retrieval,
                        ),
                    ),
                ),
                retrieval,
                proof=proof(),
            )
        read = collision._read
        monkeypatch.setattr(
            collision,
            "_read",
            lambda namespace=None, key=None: (
                read(namespace, key)[0] + 1,
                *read(namespace, key)[1:],
            ),
        )
        with pytest.raises(CurrentCollisionEligibilityBlocked) as exc_info:
            collision.enforcer.enforce(request=request, effect=lambda _: None)
        assert exc_info.value.decision.outcome.value == "BINDING_MISMATCH"

        denied = _native_collision(
            tmp_path, contexts, receipts, authorized=False
        )
        with pytest.raises(
            NativeCollisionHold,
            match="RETRIEVAL_COLLISION_AUTHORIZATION_DIFFERS",
        ):
            denied.request(held.triage, retrieval, proof=proof())


@pytest.mark.parametrize("text,microsecond", [
    ("2026-09-08T15:00:00Z", 0),
    ("2026-09-08T15:00:00.000000Z", 0),
    ("2026-09-08T15:00:00.123456Z", 123456),
])
def test_native_collision_preserves_authority_timestamp_precision(text, microsecond):
    from newsroom.increment6.collision import _parse_utc
    assert _parse_utc(text, field="serving_time").microsecond == microsecond


@pytest.mark.parametrize("text", [
    "2026-09-08T15:00:00.1Z", "2026-09-08T15:00:00.1234567Z",
    "2026-09-08T15:00:00+00:00", "2026-09-08 15:00:00Z",
])
def test_native_collision_rejects_noncanonical_timestamp(text):
    from newsroom.increment6.collision import _parse_utc, CollisionEligibilityContractError
    with pytest.raises(CollisionEligibilityContractError):
        _parse_utc(text, field="serving_time")
