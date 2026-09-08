from __future__ import annotations

import json
import uuid
from dataclasses import replace
from types import SimpleNamespace

import pytest

from newsroom.authority import AggregateId, ObjectAdmissionId
from newsroom.authority.canonical import digest_bytes
from newsroom.control_plane.cycle import _receipt
from newsroom.control_plane.corpus import MAX_EPISODE_BYTES
from newsroom.control_plane.graphiti import GraphitiCycleResult
from newsroom.control_plane.graphiti_operational_readiness import (
    _evaluation_attempt_for_unit,
)
from newsroom.control_plane.native_progress import NativeRevisionJournal
from newsroom.control_plane.native_retrieval import NativeRetrievalContinuation
from newsroom.control_plane.store import (
    connect,
    insert_graphiti_attempt_receipt,
    insert_graphiti_ingest,
)
from newsroom.increment5.native_retrieval import (
    NativeDocumentReceipt,
    NativeEmbeddingReference,
    NativeRetrievalHold,
)
from newsroom.tests.discovery_3d_authority_helpers import proof
from newsroom.tests.test_native_collision import _native_binding
from newsroom.tests.test_native_graphiti import _native


GENERATION = "native-generation-v1"


def _lead(unit):
    return SimpleNamespace(
        request=SimpleNamespace(
            revision_id=unit.revision_id,
            lead_id=str(uuid.uuid4()),
        ),
        canonical_digest=digest_bytes(f"lead:{unit.revision_id}".encode()),
    )


def _retain_complete(connection, unit, *, attempt_number=1):
    result = GraphitiCycleResult(
        ingest_id=unit.ingest_id,
        source_id=unit.source_id,
        item_key=unit.item_key,
        outcome="COMPLETE",
        proposal_count=0,
        entity_count=0,
        relation_count=0,
        failure_code="NONE",
        temporal_basis=unit.temporal().basis,
        reference_time=unit.temporal().reference_time.to_text(),
        receipt_digest=digest_bytes(f"raw:{unit.ingest_id}".encode()),
        attempt_number=attempt_number,
        provider_attempt_number=attempt_number,
    )
    terminal = _receipt(
        replace(unit, attempt_number=attempt_number), result, accounting={}
    )
    terminal["dispatch_rights"] = {"scope": "retained-test-rights"}
    final_digest = insert_graphiti_attempt_receipt(
        connection,
        ingest_id=unit.ingest_id,
        attempt_number=attempt_number,
        outcome="COMPLETE",
        receipt=terminal,
    )
    terminal["receipt_digest"] = final_digest
    insert_graphiti_ingest(
        connection,
        ingest_id=unit.ingest_id,
        source_id=unit.source_id,
        item_key=unit.item_key,
        outcome="COMPLETE",
        proposal_count=0,
        entity_count=0,
        relation_count=0,
        failure_code="NONE",
        temporal_basis=unit.temporal().basis.value,
        reference_time=unit.temporal().reference_time.to_text(),
        generation_id=result.generation_id,
        receipt_digest=final_digest,
        receipt=terminal,
    )
    connection.commit()
    return final_digest


class _Embedder:
    def __init__(self):
        self.calls = []

    def retain(self, **arguments):
        self.calls.append(arguments)
        return NativeEmbeddingReference(
            ObjectAdmissionId.new(), ObjectAdmissionId.new()
        )


class _Documents:
    def __init__(self):
        self.documents = {}
        self.contexts = {}
        self.admit_calls = []
        self.require_calls = []
        self.context_reads = []

    def admit(self, request, *, proof):
        self.admit_calls.append(request)
        receipt = NativeDocumentReceipt(
            f"document-event-{len(self.admit_calls)}",
            f"document-command-{len(self.admit_calls)}",
            request.aggregate_id,
            1,
            ObjectAdmissionId.new(),
            digest_bytes(f"document:{request.passage_id}".encode()),
            request.embedding.vector_admission_id,
            request.embedding.receipt_admission_id,
        )
        document = SimpleNamespace(
            revision_id=str(request.extraction_request.input_binding.revision_id),
            generation_id=request.generation_id,
        )
        self.documents[str(receipt.aggregate_id)] = document
        return receipt, document

    def require_document(self, receipt, *, proof):
        self.require_calls.append(receipt)
        return self.documents[str(receipt.aggregate_id)]

    def read_context(self, receipt, *, proof):
        self.context_reads.append(receipt)
        return self.contexts[receipt.context_id]


def _continuation(
    connection,
    journal,
    documents,
    embedder,
    binding,
    context,
    subjects,
    *,
    interrupt_before_binding=False,
):
    class _Port:
        def retrieve(self, lead, *, proof):
            subjects.append(self.subjects)
            if interrupt_before_binding:
                raise RuntimeError("context retention interrupted")
            documents.contexts[binding.context_id] = context
            return binding

    def port_for(items):
        port = _Port()
        port.subjects = items
        return port

    system = SimpleNamespace(
        extraction=SimpleNamespace(proposals=lambda *_args, **_kwargs: ()),
        entities=SimpleNamespace(),
        sources=SimpleNamespace(
            revision=lambda *_args, **_kwargs: SimpleNamespace(
                event_id="retained-source-revision-event"
            )
        ),
    )
    return NativeRetrievalContinuation(
        system=system,
        documents=documents,
        journal=journal,
        connection=connection,
        embedder=embedder,
        generation_id=GENERATION,
        port_for=port_for,
        rights_check=lambda _unit: None,
    )


def test_multi_chunk_embeddings_and_context_are_reused_across_restart(tmp_path):
    base = replace(
        _native(), body="Retained native passage. " * (MAX_EPISODE_BYTES // 25 + 1)
    )
    units = tuple(
        replace(base, chunk_ordinal=ordinal, chunk_count=2)
        for ordinal in (1, 2)
    )
    database = tmp_path / "private.sqlite3"
    connection = connect(str(database))
    journal = NativeRevisionJournal(connection)
    journal.land(units)
    journal.advance(
        base.revision_id,
        stage="GRAPHITI_COMPLETE",
        facts={"graphiti_receipts": [unit.ingest_id for unit in units]},
    )
    terminal_digests = {
        unit.ingest_id: _retain_complete(connection, unit, attempt_number=ordinal + 1)
        for ordinal, unit in enumerate(units)
    }
    lead = _lead(base)
    binding, _receipt_value, context = _native_binding(tmp_path, lead)
    documents, embedder, subjects = _Documents(), _Embedder(), []
    continuation = _continuation(
        connection,
        journal,
        documents,
        embedder,
        binding,
        context,
        subjects,
        interrupt_before_binding=True,
    )

    with pytest.raises(RuntimeError, match="context retention interrupted"):
        continuation.retrieve(lead, proof=proof())
    assert len(embedder.calls) == len(documents.admit_calls) == 2
    assert [call["cycle_id"] for call in embedder.calls] == [
        f"native-passage:{unit.ingest_id}" for unit in units
    ]
    assert [call["passage_id"] for call in embedder.calls] == [
        str(
            _evaluation_attempt_for_unit(
                replace(unit, attempt_number=ordinal + 1)
            ).extraction_request.input_binding.passages[0].passage_id
        )
        for ordinal, unit in enumerate(units)
    ]
    assert len(subjects) == 1 and len(subjects[0]) == 2
    facts = journal.progress[base.revision_id]["facts"]
    assert facts["graphiti_receipts"] == [unit.ingest_id for unit in units]
    assert set(facts["retrieval_documents"]) == {
        unit.ingest_id for unit in units
    }
    assert {
        unit.ingest_id: facts["retrieval_embeddings"][unit.ingest_id]["state"]
        for unit in units
    } == {unit.ingest_id: "RETAINED" for unit in units}
    assert "retrieval_binding" not in facts
    for unit in units:
        row = connection.execute(
            "SELECT receipt_digest FROM unpublished_graphiti_ingest WHERE ingest_id=?",
            (unit.ingest_id,),
        ).fetchone()
        assert row[0] == terminal_digests[unit.ingest_id]

    connection.close()

    reopened = connect(str(database))
    try:
        replay = NativeRevisionJournal(reopened)
        replay_subjects = []
        replay_continuation = _continuation(
            reopened,
            replay,
            documents,
            embedder,
            binding,
            context,
            replay_subjects,
        )
        assert replay_continuation.retrieve(lead, proof=proof()) == binding
        assert len(embedder.calls) == len(documents.admit_calls) == 2
        assert len(replay_subjects) == 1 and len(replay_subjects[0]) == 2
        assert documents.context_reads == []
        replay_facts = replay.progress[base.revision_id]["facts"]
        replay.advance(
            base.revision_id,
            stage="CANDIDATE_ADMITTED",
            facts={**replay_facts, "candidate_version_id": "candidate-version-1"},
        )
    finally:
        reopened.close()

    final_connection = connect(str(database))
    try:
        final_journal = NativeRevisionJournal(final_connection)
        fresh_requests = []
        final_continuation = _continuation(
            final_connection,
            final_journal,
            documents,
            embedder,
            binding,
            context,
            fresh_requests,
        )
        assert final_continuation.retrieve(lead, proof=proof()) == binding
        assert fresh_requests == []
        assert len(documents.context_reads) == 1
        replay_facts = final_journal.progress[base.revision_id]["facts"]
        assert replay_facts["candidate_version_id"] == "candidate-version-1"
        assert replay_facts["graphiti_receipts"] == [
            unit.ingest_id for unit in units
        ]
        assert replay_facts["retrieval_binding"] == binding.canonical_value()
    finally:
        final_connection.close()


def test_started_embedding_holds_without_redispatch(tmp_path):
    unit = _native()
    connection = connect(str(tmp_path / "private.sqlite3"))
    try:
        journal = NativeRevisionJournal(connection)
        journal.land((unit,))
        _retain_complete(connection, unit, attempt_number=3)
        passage = _evaluation_attempt_for_unit(
            replace(unit, attempt_number=3)
        ).extraction_request.input_binding.passages[0]
        journal.advance(
            unit.revision_id,
            stage="EMBEDDING_STARTED",
            facts={
                "retrieval_embeddings": {
                    unit.ingest_id: {
                        "state": "STARTED",
                        "passage_id": str(passage.passage_id),
                    }
                }
            },
        )
        lead = _lead(unit)
        binding, _receipt_value, context = _native_binding(tmp_path, lead)
        documents, embedder = _Documents(), _Embedder()
        documents.contexts[binding.context_id] = context
        continuation = _continuation(
            connection, journal, documents, embedder, binding, context, []
        )

        with pytest.raises(
            NativeRetrievalHold, match="NATIVE_EMBEDDING_INTERRUPTED"
        ):
            continuation.retrieve(lead, proof=proof())
        assert embedder.calls == []
        assert documents.admit_calls == []
        assert journal.progress[unit.revision_id]["stage"] == "EMBEDDING_STARTED"
    finally:
        connection.close()


def test_terminal_receipt_tamper_holds_before_embedding(tmp_path):
    unit = _native()
    connection = connect(str(tmp_path / "private.sqlite3"))
    try:
        journal = NativeRevisionJournal(connection)
        journal.land((unit,))
        retained_digest = _retain_complete(connection, unit, attempt_number=4)
        raw = connection.execute(
            "SELECT receipt_json FROM unpublished_graphiti_receipts WHERE ingest_id=?",
            (unit.ingest_id,),
        ).fetchone()[0]
        terminal = json.loads(raw)
        assert terminal["receipt_digest"] == retained_digest
        terminal["attempt_number"] = 5
        connection.execute(
            "UPDATE unpublished_graphiti_receipts SET receipt_json=? WHERE ingest_id=?",
            (json.dumps(terminal, ensure_ascii=False, sort_keys=True), unit.ingest_id),
        )
        connection.commit()
        lead = _lead(unit)
        binding, _receipt_value, context = _native_binding(tmp_path, lead)
        documents, embedder = _Documents(), _Embedder()
        continuation = _continuation(
            connection, journal, documents, embedder, binding, context, []
        )

        with pytest.raises(
            NativeRetrievalHold, match="NATIVE_EXTRACTION_RECEIPT_DIFFERS"
        ):
            continuation.retrieve(lead, proof=proof())
        assert embedder.calls == []
        assert documents.admit_calls == []
    finally:
        connection.close()
