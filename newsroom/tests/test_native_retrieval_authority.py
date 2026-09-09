from __future__ import annotations

import io
import json
import sqlite3
import uuid
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from newsroom.authority import AggregateId, EventId, UtcTimestamp
from newsroom.authority._graphiti_increment4_system import (
    _AUTHORITY_COMPOSITION_TOKEN,
)
from newsroom.authority.canonical import digest_bytes, digest_canonical
from newsroom.control_plane.graphiti_operational_readiness import (
    OPERATOR_AUTHORITY_DOMAIN,
    OPERATOR_PRINCIPAL_ID,
    _evaluation_attempt_for_unit,
    bootstrap_operational_authority,
    build_and_reconcile_operational_generation,
)
from newsroom.control_plane.model_usage import ModelUsageService
from newsroom.control_plane.native_embeddings import NativePassageEmbedder
from newsroom.control_plane.native_retrieval import compose_native_documents
from newsroom.control_plane.native_runtime import open_native_runtime
from newsroom.discovery import NewsLead
from newsroom.graphiti_adapter.real import RealGraphitiAdapter
from newsroom.increment4.neo4j import Increment4Neo4jActiveReadRequest
from newsroom.increment5.branch_contracts import (
    EXACT_BRANCH_ACTOR_ID,
    EXACT_BRANCH_POLICY_ID,
    EXACT_BRANCH_PURPOSE,
    BranchRequestId,
    ExactBranchRequest,
    ExactLookupKind,
)
from newsroom.increment5.decision import INCREMENT_5A_CONTRACT_DIGEST
from newsroom.increment5.exact_retriever import SQLiteExactRetriever
from newsroom.increment5.native_retrieval import (
    NativeDocumentRequest,
    NativeGraphBranchReceipt,
    NativeRetrievalContextReceipt,
    NativeRetrievalContextRequest,
    NativeRetrievalDocuments,
    NativeRetrievalError,
    NativeRetrievalPort,
    NativeRetrievalSubject,
    NativeVectorRequest,
)
from newsroom.increment5.receipt_journal import BranchReceiptJournal
from newsroom.increment6.dispositions import (
    _create_current_candidate_citation_read_port,
)
from newsroom.projection.mapping import canonical_governed_node_id
from newsroom.projection.ontology import ProjectionNodeType
from newsroom.sources import SourceRevisionId
from newsroom.tests.increment5b2_helpers import (
    NOW,
    default_scenario,
    request as fulltext_request,
    snapshot as fulltext_snapshot,
    system as fulltext_system,
)
from newsroom.tests.test_graphiti_adapter_4d_outcomes import (
    _production_shaped_execution,
)
from newsroom.tests.test_graphiti_operational_readiness import _plan, _unit
from newsroom.tests.test_native_embeddings import _policy, _response
from newsroom.tests.discovery_3d_authority_helpers import exact_admission_request
from newsroom.tests.test_native_runtime import _args


class _Projection:
    def __init__(self, generation_id: str) -> None:
        suffix = generation_id.replace("-", "")[:16]
        self.document_label = f"NewsroomNativeRetrievalDocument_{suffix}"
        self.fulltext_index = f"native_fulltext_{suffix}"
        self.rows: list[tuple[object, object, tuple[float, ...]]] = []

    def upsert(self, receipt, document, vector) -> None:
        self.rows.append((receipt, document, vector))

    def retrieve(self, *, query_text: str, query_vector: tuple[float, ...]):
        return (), tuple(
            ({**receipt.projection_value(), "score": 1.0})
            for receipt, _document, _vector in self.rows
        )

    def retrieve_vector(self, *, query_vector: tuple[float, ...]):
        return self.retrieve(query_text="unused", query_vector=query_vector)[1]


def _open_documents(runtime, projection) -> NativeRetrievalDocuments:
    return compose_native_documents(
        objects=runtime.authority.objects,
        extraction=runtime.authority.extraction,
        commands=runtime.authority.commands,
        events=runtime.authority.events,
        projector=projection,
        policies=runtime.policies,
        principal_id=OPERATOR_PRINCIPAL_ID,
        authority_domain=OPERATOR_AUTHORITY_DOMAIN,
    )


def test_native_documents_admit_retain_context_and_reopen(
    tmp_path, monkeypatch,
) -> None:
    now = UtcTimestamp(datetime(2042, 3, 12, 12, tzinfo=UTC))
    args = _args(tmp_path, monkeypatch)
    args["clock"] = lambda: now
    args["principal_id"] = OPERATOR_PRINCIPAL_ID
    args["authority_domain"] = OPERATOR_AUTHORITY_DOMAIN
    retrieval = args.pop("retrieval_authority")
    collision = args.pop("collision_enforcer")
    citation_port = _create_current_candidate_citation_read_port(
        lambda *_: (_ for _ in ()).throw(LookupError("no retained citation"))
    )
    args["native_dependency_factory"] = lambda **_: (
        retrieval, collision, citation_port
    )
    unit = _unit()
    plan = _plan(unit)
    generation_id = str(fulltext_snapshot().generation_id)

    monkeypatch.setattr(
        RealGraphitiAdapter,
        "execute",
        lambda _self, *, attempt, workspace_root: _production_shaped_execution(
            attempt
        ),
    )
    response = _response()

    class _Response(io.BytesIO):
        status = 200

        def geturl(self):
            return "https://openrouter.ai/api/v1/embeddings"

    class _Opener:
        def open(self, request, timeout):
            return _Response(json.dumps(response).encode())

    monkeypatch.setattr("urllib.request.build_opener", lambda *_: _Opener())

    projection = _Projection(generation_id)
    with open_native_runtime(**args) as runtime:
        bootstrap, _binder = bootstrap_operational_authority(
            runtime.authority, proof=runtime.proof, plan=plan
        )
        bound = bootstrap.bound_units[0]
        attempt = _evaluation_attempt_for_unit(bound)
        runtime.authority.graphiti.execute_attempt(
            attempt,
            proof=runtime.proof,
            execution_deadline=datetime(2042, 3, 12, 12, 1, tzinfo=UTC),
            fallback_permitted=False,
            invocation_observer=object(),
        )
        build_and_reconcile_operational_generation(
            runtime.authority,
            proof=runtime.proof,
            plan=plan,
            bootstrap=bootstrap,
        )
        passage = attempt.extraction_request.input_binding.passages[0]
        usage = ModelUsageService(str(tmp_path / "usage.sqlite3"))
        policy = _policy()
        usage.register_policy(policy)
        embedding = NativePassageEmbedder(
            api_key="test-key-never-live",
            objects=runtime.authority.objects,
            usage=usage,
            policy=policy,
            dispatch_fence=nullcontext,
            implementation_worktree_clean=True,
            clock=lambda: now.value,
        ).retain(
            text=passage.require_text(),
            passage_id=str(passage.passage_id),
            cycle_id="native-authority-test",
            proof=runtime.proof,
        )
        documents = _open_documents(runtime, projection)
        document_receipt, document = documents.admit(
            NativeDocumentRequest(
                attempt.extraction_request,
                passage.passage_id,
                "event:source",
                generation_id,
                embedding,
                AggregateId.new(),
                0,
                "native-document-authority-test",
            ),
            proof=runtime.proof,
        )
        exact_request = ExactBranchRequest(
            BranchRequestId.new(),
            "native-authority-exact",
            EXACT_BRANCH_ACTOR_ID,
            EXACT_BRANCH_PURPOSE,
            EXACT_BRANCH_POLICY_ID,
            INCREMENT_5A_CONTRACT_DIGEST,
            ExactLookupKind.SOURCE_REVISION_ID,
            str(attempt.extraction_request.input_binding.revision_id),
            NOW,
            NOW,
        )
        exact_retriever = SQLiteExactRetriever(
            authority_database=args["authority_path"],
            journal=BranchReceiptJournal(tmp_path / "exact.sqlite3"),
        )
        exact = exact_retriever.retrieve(exact_request).receipt
        snapshot = fulltext_snapshot(
            document_label=projection.document_label,
            index_name=projection.fulltext_index,
            index_document_count=1,
        )
        view = documents.fulltext_authority_view(
            (document_receipt,), snapshot, proof=runtime.proof
        )
        fulltext_retriever = fulltext_system(
            tmp_path,
            view=view,
            scenario=default_scenario(projection_snapshot=snapshot, rows=[]),
        )[2]
        fulltext = fulltext_retriever.retrieve(
            fulltext_request(
                expected_generation_id=snapshot.generation_id,
                expected_generation_identity_digest=snapshot.generation_identity_digest,
                expected_rights_manifest_digest=snapshot.rights_manifest_digest,
                source_ids=(document.source_id,),
                query_valid_time=NOW,
                serving_time=NOW,
            )
        ).receipt
        vector_request = NativeVectorRequest(
            str(uuid.uuid4()),
            "native-authority-vector",
            document_receipt.event_id,
            document.digest,
            generation_id,
            NOW.to_text(),
            NOW.to_text(),
        )
        vector = documents.retrieve_vector(vector_request, proof=runtime.proof)
        revision = runtime.authority.sources.revision(
            SourceRevisionId.parse(document.revision_id), proof=runtime.proof
        )
        graph_id = canonical_governed_node_id(
            ProjectionNodeType.LEDGER_EVENT,
            "authority_event_id",
            str(revision.event_id),
        )
        graph_response = runtime.authority.increment4.read_active(
            Increment4Neo4jActiveReadRequest((graph_id,), NOW, 64),
            proof=runtime.proof,
        )
        graph = NativeGraphBranchReceipt.from_response(
            digest_canonical({"graph": graph_id}), (graph_id,), graph_response
        )
        lead_request = replace(
            exact_admission_request().lead,
            revision_id=SourceRevisionId.parse(document.revision_id),
        )
        lead = NewsLead(
            lead_request,
            EventId.new(),
            1,
            lead_request.created_at,
            lead_request.digest,
        )
        subject = NativeRetrievalSubject(
            document.revision_id, graph_id, document_receipt,
            "Official deadline changed",
        )
        document_inventory = documents.authenticated_document_inventory(
            (document_receipt,), proof=runtime.proof,
        )
        with pytest.raises(
            NativeRetrievalError, match="document inventory type differs",
        ):
            documents.fulltext_authority_view_from_inventory(
                object(), (document_receipt,), snapshot,
            )
        with pytest.raises(
            NativeRetrievalError, match="document inventory type differs",
        ):
            NativeRetrievalPort(
                documents=documents,
                exact=exact_retriever,
                fulltext=fulltext_retriever,
                increment4=runtime.authority.increment4,
                fulltext_view=view,
                subjects=(subject,),
                document_inventory=object(),
                authority_scope_id="native-authority-scope",
                rights_inventory_digest=digest_canonical({"rights": "first"}),
                minimum_authority_watermark=0,
            )
        with pytest.raises(
            NativeRetrievalError, match="document inventory binding differs",
        ):
            NativeRetrievalPort(
                documents=documents,
                exact=exact_retriever,
                fulltext=fulltext_retriever,
                increment4=runtime.authority.increment4,
                fulltext_view=view,
                subjects=(replace(
                    subject,
                    document_receipt=replace(
                        document_receipt, event_id="different-authority-event",
                    ),
                ),),
                document_inventory=document_inventory,
                authority_scope_id="native-authority-scope",
                rights_inventory_digest=digest_canonical({"rights": "first"}),
                minimum_authority_watermark=0,
            )
        wrong_proof_inventory = documents.authenticated_document_inventory(
            (document_receipt,), proof=runtime.proof,
        )
        wrong_proof_port = NativeRetrievalPort(
            documents=documents,
            exact=exact_retriever,
            fulltext=fulltext_retriever,
            increment4=runtime.authority.increment4,
            fulltext_view=view,
            subjects=(subject,),
            document_inventory=wrong_proof_inventory,
            authority_scope_id="native-authority-scope",
            rights_inventory_digest=digest_canonical({"rights": "first"}),
            minimum_authority_watermark=0,
        )
        with pytest.raises(
            NativeRetrievalError, match="document inventory proof differs",
        ):
            wrong_proof_port.retrieve(
                lead,
                proof=replace(runtime.proof, credential="wrong-credential"),
            )
        first_port = NativeRetrievalPort(
            documents=documents,
            exact=exact_retriever,
            fulltext=fulltext_retriever,
            increment4=runtime.authority.increment4,
            fulltext_view=view,
            subjects=(subject,),
            document_inventory=document_inventory,
            authority_scope_id="native-authority-scope",
            rights_inventory_digest=digest_canonical({"rights": "first"}),
            minimum_authority_watermark=0,
        )
        first_binding = first_port.retrieve(lead, proof=runtime.proof)
        with sqlite3.connect(tmp_path / "fulltext-receipts.sqlite3") as retained:
            fulltext_request_value = json.loads(retained.execute(
                "SELECT request_bytes FROM increment5_fulltext_receipts "
                "WHERE idempotency_key LIKE 'native-fulltext:%'"
            ).fetchone()[0])
        assert fulltext_request_value["query_text"] == "Official deadline changed"
        assert first_port.retrieve(lead, proof=runtime.proof) == first_binding
        with pytest.raises(
            NativeRetrievalError, match="document inventory binding differs",
        ):
            NativeRetrievalPort(
                documents=documents,
                exact=exact_retriever,
                fulltext=fulltext_retriever,
                increment4=runtime.authority.increment4,
                fulltext_view=view,
                subjects=(subject,),
                document_inventory=document_inventory,
                authority_scope_id="native-authority-scope",
                rights_inventory_digest=digest_canonical({"rights": "second"}),
                minimum_authority_watermark=0,
            )
        changed_inventory = documents.authenticated_document_inventory(
            (document_receipt,), proof=runtime.proof,
        )
        changed_port = NativeRetrievalPort(
            documents=documents,
            exact=exact_retriever,
            fulltext=fulltext_retriever,
            increment4=runtime.authority.increment4,
            fulltext_view=view,
            subjects=(subject,),
            document_inventory=changed_inventory,
            authority_scope_id="native-authority-scope",
            rights_inventory_digest=digest_canonical({"rights": "second"}),
            minimum_authority_watermark=0,
        )
        changed_binding = changed_port.retrieve(lead, proof=runtime.proof)
        assert changed_binding != first_binding
        assert NativeRetrievalContextReceipt.from_bytes(
            changed_binding.receipt_bytes
        ).rights_inventory_digest == digest_canonical({"rights": "second"})
        context_request = NativeRetrievalContextRequest(
            str(uuid.uuid4()),
            "native-context-authority-test",
            AggregateId.new(),
            0,
            "lead-one",
            "sha256:" + "3" * 64,
            "native-authority-scope",
            digest_canonical({"rights": "current"}),
            exact.canonical_bytes,
            fulltext.canonical_bytes,
            vector.canonical_bytes,
            graph.canonical_bytes,
            (document_receipt,),
        )
        binding = documents.retain_context(context_request, proof=runtime.proof)
        receipt = NativeRetrievalContextReceipt.from_bytes(binding.receipt_bytes)
        assert documents.read_context(receipt, proof=runtime.proof).generation_id == generation_id
        assert documents.retain_context(
            context_request, proof=runtime.proof
        ) == binding
        later = UtcTimestamp(datetime(2042, 3, 12, 12, 0, 1, tzinfo=UTC))
        changed_time_replay = replace(
            context_request,
            exact_receipt_bytes=replace(exact, completed_at=later).canonical_bytes,
            fulltext_receipt_bytes=replace(
                fulltext, completed_at=later
            ).canonical_bytes,
            vector_receipt_bytes=replace(
                vector, serving_time=later.to_text()
            ).canonical_bytes,
            graph_receipt_bytes=replace(
                graph, serving_time=later.to_text()
            ).canonical_bytes,
        )
        with pytest.raises(
            NativeRetrievalError, match="context admission replay differs"
        ):
            documents.retain_context(changed_time_replay, proof=runtime.proof)
        assert documents.read_context(
            receipt, proof=runtime.proof
        ).serving_time == context_request.branch_receipts()[2].serving_time
        root, *_ = runtime.authority._base._authority_composition(
            _AUTHORITY_COMPOSITION_TOKEN
        )
        access_count = root._connection.execute(
            "SELECT COUNT(*) FROM object_access_decisions"
        ).fetchone()[0]
        with pytest.raises(RuntimeError, match="force outer rollback"):
            with root._lock, root._transaction():
                assert documents.context_read_port(
                    proof=runtime.proof
                ).require(receipt).context_id == receipt.context_id
                assert root._connection.execute(
                    "SELECT COUNT(*) FROM object_access_decisions"
                ).fetchone()[0] > access_count
                raise RuntimeError("force outer rollback")
        assert root._connection.execute(
            "SELECT COUNT(*) FROM object_access_decisions"
        ).fetchone()[0] == access_count
        replay = documents.admit(
            NativeDocumentRequest(
                attempt.extraction_request,
                passage.passage_id,
                "event:source",
                generation_id,
                embedding,
                document_receipt.aggregate_id,
                0,
                "native-document-authority-test",
            ),
            proof=runtime.proof,
        )[0]
        assert replay == document_receipt
        with pytest.raises(NativeRetrievalError):
            documents.require_document(
                replace(document_receipt, document_digest="sha256:" + "f" * 64),
                proof=runtime.proof,
            )

    reopened_projection = _Projection(generation_id)
    with open_native_runtime(**args) as reopened:
        documents = _open_documents(reopened, reopened_projection)
        context = documents.read_context(receipt, proof=reopened.proof)
        assert context.context_id == receipt.context_id
        assert documents.require_document(
            document_receipt, proof=reopened.proof
        ).digest == document.digest
