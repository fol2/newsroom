"""Durable preparation of real native passages before four-branch retrieval.

The Control Plane ledger stores continuation references, not retrieval truth.
Every reused document/context is checked again by the native authority facade.
An interrupted embedding dispatch is held, never silently billed a second time.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import replace

from newsroom.authority import AggregateId, AuthenticationProof, ObjectAdmissionId
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.entities.types import EntityResolutionProposalId
from newsroom.extraction.types import ExtractionProposalKind
from newsroom.graphiti_adapter.identity import typed_id
from newsroom.increment5.native_retrieval import (
    NativeDocumentReceipt, NativeDocumentRequest, NativeEmbeddingReference,
    NativeRetrievalContextReceipt, NativeRetrievalDocuments, NativeRetrievalHold,
    NativeRetrievalSubject,
)
from newsroom.increment6.work_items import RetrievalInputBinding
from newsroom.projection.mapping import canonical_governed_node_id
from newsroom.projection.ontology import ProjectionNodeType
from newsroom.sources import SourceRevisionId

from .corpus import CorpusIngestUnit
from .graphiti_operational_readiness import (
    GRAPHITI_EVALUATION_HYDRATION_POLICY, _evaluation_attempt_for_unit,
)
from .native_cycle import _uuid4_for
from .native_progress import NativeRevisionJournal


def compose_native_documents(*, objects, extraction, commands, events, projector,
                             policies, principal_id: str, authority_domain: str):
    """Bind the existing admitted policy definitions without fixture helpers."""
    document, vector, receipt = policies.retrieval_hydration
    return NativeRetrievalDocuments(
        objects=objects, extraction=extraction, commands=commands, events=events,
        projector=projector, reader_principal_id=principal_id,
        authority_domain=authority_domain, controller_principal_id=principal_id,
        passage_hydration_policy_digest=GRAPHITI_EVALUATION_HYDRATION_POLICY.contract_digest,
        vector_hydration_policy_digest=vector, receipt_hydration_policy_digest=receipt,
        document_hydration_policy_digest=document,
        document_admission_definition_digest=policies.retrieval_document_definition,
        command_definition_digest=policies.retrieval_command_definition,
        context_hydration_policy_digest=policies.retrieval_context_hydration,
        context_admission_definition_digest=policies.retrieval_context_definition,
        context_command_definition_digest=policies.retrieval_context_command_definition,
    )


class NativeRetrievalContinuation:
    """Prepare only new passages; retain the exact first completed context."""

    def __init__(
        self, *, system, documents: NativeRetrievalDocuments,
        journal: NativeRevisionJournal, connection: sqlite3.Connection,
        embedder, generation_id: str, port_for: Callable,
        rights_check: Callable[[CorpusIngestUnit], None],
    ) -> None:
        self._system, self._documents, self._journal = system, documents, journal
        self._connection, self._embedder = connection, embedder
        self._generation, self._port_for, self._rights = generation_id, port_for, rights_check

    def _facts(self, revision_id: str) -> dict:
        return dict(self._journal.progress.get(revision_id, {}).get("facts", {}))

    def _save(self, revision_id: str, stage: str, **updates) -> None:
        self._journal.advance(revision_id, stage=stage, facts={**self._facts(revision_id), **updates})

    def retrieve(self, lead, *, proof: AuthenticationProof) -> RetrievalInputBinding:
        revision_id = str(lead.request.revision_id)
        units = self._journal.units[revision_id]
        for unit in units:
            self._rights(unit)
        retained = self._facts(revision_id).get("retrieval_binding")
        if retained is not None:
            binding = RetrievalInputBinding.from_value(retained)
            receipt = NativeRetrievalContextReceipt.from_bytes(binding.receipt_bytes)
            context = self._documents.read_context(receipt, proof=proof)
            if context.lead_id != str(lead.request.lead_id) or context.lead_digest != lead.canonical_digest:
                raise ValueError("retained native context belongs to another Lead")
            return binding

        self._prepare(units, proof=proof)
        subjects = []
        # Only this daemon's native journal inventory enters its projection.
        # No legacy corpus import, old campaign replay or historical embedding.
        for source_revision, source_units in self._journal.units.items():
            records = self._facts(source_revision).get("retrieval_documents", {})
            if not records:
                continue
            for unit in source_units:
                record = records.get(unit.ingest_id)
                if record is None:
                    continue
                self._rights(unit)
                receipt = NativeDocumentReceipt.from_projection(record["receipt"])
                document = self._documents.require_document(receipt, proof=proof)
                if document.revision_id != source_revision or document.generation_id != self._generation:
                    raise ValueError("native passage continuation identity changed")
                subjects.append(NativeRetrievalSubject(
                    source_revision, record["graph_root_id"], receipt,
                ))
        port = self._port_for(tuple(subjects))
        binding = port.retrieve(lead, proof=proof)
        self._save(revision_id, "RETRIEVAL_COMPLETE", retrieval_binding=binding.canonical_value())
        return binding

    def _prepare(self, units: tuple[CorpusIngestUnit, ...], *, proof: AuthenticationProof) -> None:
        revision_id = units[0].revision_id
        for unit in units:
            facts = self._facts(revision_id)
            documents = dict(facts.get("retrieval_documents", {}))
            if unit.ingest_id in documents:
                self._documents.require_document(
                    NativeDocumentReceipt.from_projection(documents[unit.ingest_id]["receipt"]),
                    proof=proof,
                )
                continue
            self._rights(unit)
            row = self._connection.execute(
                "SELECT i.outcome,i.receipt_digest,r.receipt_json "
                "FROM unpublished_graphiti_ingest i JOIN unpublished_graphiti_receipts r "
                "ON r.ingest_id=i.ingest_id WHERE i.ingest_id=?", (unit.ingest_id,),
            ).fetchone()
            if row is None or row[0] != "COMPLETE":
                raise NativeRetrievalHold("NATIVE_EXTRACTION_RECEIPT_MISSING")
            terminal = json.loads(row[2])
            unsigned = dict(terminal)
            receipt_digest = unsigned.pop("receipt_digest", None)
            if (receipt_digest != row[1] or receipt_digest != digest_bytes(canonical_json_bytes(unsigned))
                    or terminal.get("ingest_id") != unit.ingest_id):
                raise NativeRetrievalHold("NATIVE_EXTRACTION_RECEIPT_DIFFERS")
            attempt_number = terminal.get("attempt_number")
            if type(attempt_number) is not int or attempt_number < 1:
                raise ValueError("native extraction attempt number differs")
            attempt = _evaluation_attempt_for_unit(replace(unit, attempt_number=attempt_number))
            request = attempt.extraction_request
            if len(request.input_binding.passages) != 1:
                raise NativeRetrievalHold("NATIVE_PASSAGE_PARTITION_DIFFERS")
            passage = request.input_binding.passages[0]
            embeddings = dict(facts.get("retrieval_embeddings", {}))
            embedded = embeddings.get(unit.ingest_id)
            if embedded is not None and embedded.get("state") != "RETAINED":
                raise NativeRetrievalHold("NATIVE_EMBEDDING_INTERRUPTED")
            if embedded is None:
                embeddings[unit.ingest_id] = {"state": "STARTED", "passage_id": str(passage.passage_id)}
                self._save(revision_id, "EMBEDDING_STARTED", retrieval_embeddings=embeddings)
                # Exactly the admitted extraction passage, not a feed summary
                # or separately re-tokenised full document.
                text = " ".join(unit.episode_body.split())
                if digest_bytes(text.encode()) != passage.text_digest:
                    raise ValueError("native embedding passage bytes differ")
                reference = self._embedder.retain(
                    text=text, passage_id=str(passage.passage_id),
                    cycle_id=f"native-passage:{unit.ingest_id}", proof=proof,
                )
                embedded = {"state": "RETAINED", "passage_id": str(passage.passage_id),
                            "vector_admission_id": str(reference.vector_admission_id),
                            "receipt_admission_id": str(reference.receipt_admission_id)}
                embeddings[unit.ingest_id] = embedded
                self._save(revision_id, "EMBEDDING_RETAINED", retrieval_embeddings=embeddings)
            elif embedded["passage_id"] != str(passage.passage_id):
                raise ValueError("native embedding continuation passage changed")
            reference = NativeEmbeddingReference(
                ObjectAdmissionId.parse(embedded["vector_admission_id"]),
                ObjectAdmissionId.parse(embedded["receipt_admission_id"]),
            )
            key = f"native-document:{self._generation}:{passage.passage_id}"
            receipt, _document = self._documents.admit(NativeDocumentRequest(
                request, passage.passage_id, unit.authority.item_id, self._generation,
                reference, AggregateId.parse(_uuid4_for(key)), 0, key,
            ), proof=proof)
            graph_root = self._graph_root(request, unit, proof=proof)
            documents[unit.ingest_id] = {"receipt": receipt.projection_value(), "graph_root_id": graph_root}
            self._save(revision_id, "DOCUMENT_RETAINED", retrieval_documents=documents)

    def _graph_root(self, request, unit, *, proof: AuthenticationProof) -> str:
        # Use actual retained entity-resolution authority for this extraction.
        # No entity name or vector hit is promoted into an admitted graph ID.
        for proposal in self._system.extraction.proposals(request.run_version_id, proof=proof):
            if proposal.kind not in {ExtractionProposalKind.ENTITY_MENTION, ExtractionProposalKind.ENTITY_EQUIVALENCE}:
                continue
            proposal_id = typed_id(EntityResolutionProposalId, "graphiti-v1-resolution", proposal.canonical_digest)
            try:
                resolved = self._system.entities.decision(proposal_id, proof=proof)
            except LookupError:
                continue
            if resolved is not None and resolved.accepted_entity_id is not None:
                return canonical_governed_node_id(
                    ProjectionNodeType.AUTHORITY_AGGREGATE, "canonical_entity_id",
                    str(resolved.accepted_entity_id),
                )
        # A valid zero-proposal extraction may have no graph node. Query the
        # genuine SourceRevision event identity and retain the real NO_MATCH;
        # never invent a positive node or skip the actual graph branch.
        revision = self._system.sources.revision(SourceRevisionId.parse(unit.revision_id), proof=proof)
        return canonical_governed_node_id(
            ProjectionNodeType.LEDGER_EVENT, "authority_event_id", str(revision.event_id),
        )
