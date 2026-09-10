"""Live Story Candidate collision requests for the native Hermes runtime."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path

from newsroom.authority import AuthorityEvents, AuthenticationProof
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes, validate_sha256_digest
from newsroom.discovery import NewsLead
from newsroom.increment5.native_retrieval import (
    NATIVE_CONTEXT_COMMAND,
    NativeRetrievalContext,
    NativeRetrievalContextReceipt,
)
from newsroom.increment6.collision import (
    CandidateUseCollisionBinding,
    CandidateUseOperation,
    CollisionState,
    CurrentCollisionAuthoritySnapshot,
    CurrentCollisionEffectEnforcer,
    CurrentCollisionEligibilityRequest,
    NativeCurrentCollisionReceiptEvidence,
    TrustedCurrentCollisionAuthorityBoundary,
    TrustedCurrentCollisionAuthorityContext,
)
from newsroom.increment6.candidates import StoryCandidateVersion
from newsroom.increment6.hypotheses import EventHypothesisVersion
from newsroom.increment6.relationships import (
    CanonicalOutcome,
    ComparatorEvidence,
    RelationshipAssessment,
    assess_relationships,
)
from newsroom.increment6.dispositions import (
    CurrentCandidateCitation,
    CurrentCandidateCitationReadPort,
    _create_current_candidate_citation_read_port,
)
from newsroom.increment6.work_items import RetrievalInputBinding

from .native_triage import NativeTriageResult


_PROFILE_ID = "hermes-native-story-candidate-collision-v1"
_PORT_ID = "hermes.native.story-candidate-collision.v1"
_QUERY = (
    "SELECT b.candidate_id,h.current_version_id,h.current_version_digest,"
    "b.semantic_scope_digest FROM story_candidate_collision_bindings b "
    "JOIN story_candidate_heads h ON h.candidate_id=b.candidate_id "
    "WHERE b.collision_namespace=? AND b.collision_key_digest=?"
)
_QUERY_DIGEST = digest_bytes(_QUERY.encode("utf-8"))
_ADAPTER_CONFIG_DIGEST = digest_bytes(canonical_json_bytes({
    "schema_version": "newsroom.control-plane.native-collision-adapter.v1",
    "query_digest": _QUERY_DIGEST,
    "tables": ["ledger_events", "story_candidate_collision_bindings", "story_candidate_heads"],
    "read_only": True,
}))
_PORT_REGISTRY_DIGEST = digest_bytes(canonical_json_bytes({
    "schema_version": "newsroom.control-plane.native-collision-port-registry.v1",
    "ports": [_PORT_ID],
}))


class NativeCollisionHold(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class NativeCollisionIdentity:
    authority_scope_id: str
    controller_principal_id: str
    authority_domain: str

    def __post_init__(self) -> None:
        if not all(
            (self.authority_scope_id, self.controller_principal_id, self.authority_domain)
        ):
            raise ValueError("native collision authority identities are required")


class NativeCollisionAuthority:
    """Produce exact requests and fresh, retained read-only authority snapshots."""

    def __init__(
        self,
        *,
        authority_path: Path,
        journal_path: Path,
        identity: NativeCollisionIdentity,
        context_reader: Callable[..., NativeRetrievalContext],
        events: AuthorityEvents,
    ) -> None:
        if not isinstance(authority_path, Path) or not isinstance(journal_path, Path):
            raise TypeError("native collision paths must be Paths")
        if authority_path.resolve() == journal_path.resolve():
            raise ValueError("native collision journal must be separate from authority")
        if not isinstance(identity, NativeCollisionIdentity):
            raise TypeError("native collision identity must be typed")
        if not callable(context_reader):
            raise TypeError("native collision context reader must be callable")
        if type(events) is not AuthorityEvents:
            raise TypeError("native collision events must be typed")
        self._path = authority_path
        self._journal = journal_path
        self._identity = identity
        self._read_context = context_reader
        self._events = events
        self._lock = threading.Lock()
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        with self._journal_connection() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS native_collision_requests("
                "request_digest TEXT PRIMARY KEY,request_evidence_bytes BLOB NOT NULL) STRICT"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS native_collision_receipts("
                "receipt_digest TEXT PRIMARY KEY,request_digest TEXT NOT NULL,"
                "authority_watermark INTEGER NOT NULL,collision_state TEXT NOT NULL,"
                "candidate_id TEXT,execution_receipt_bytes BLOB NOT NULL,"
                "authority_receipt_bytes BLOB NOT NULL) STRICT"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS native_current_candidate_citations("
                "citation_id TEXT PRIMARY KEY,citation_digest TEXT NOT NULL UNIQUE,"
                "citation_bytes BLOB NOT NULL) STRICT"
            )
        self.enforcer = CurrentCollisionEffectEnforcer(
            current_authority_provider=self,
            trusted_boundary=TrustedCurrentCollisionAuthorityBoundary(
                identity.authority_scope_id,
                _PROFILE_ID,
                _ADAPTER_CONFIG_DIGEST,
                _PORT_REGISTRY_DIGEST,
                _PORT_ID,
            ),
        )

    def current_candidate_citation(
        self,
        lead: NewsLead,
        retrieval: RetrievalInputBinding,
        *,
        proof: AuthenticationProof,
    ) -> CurrentCandidateCitation | None:
        """Read the actual current stable source-item Candidate head, if any."""

        if type(lead) is not NewsLead:
            raise TypeError("native collision citation requires an exact Lead")
        receipt, context = self._validated_context(retrieval, lead, proof=proof)
        authorization_receipt_digest, authorization_decision_id = (
            self._context_authorization(receipt, proof=proof)
        )
        namespace, key = self._collision_slot(lead)
        _, candidate_id, version_id, version_digest, semantic_scope_digest = (
            self._read(namespace, key)
        )
        if candidate_id is None:
            return None
        if None in (version_id, version_digest, semantic_scope_digest):
            raise NativeCollisionHold("CURRENT_COLLISION_AUTHORITY_AMBIGUOUS")
        version = self._read_candidate_version(version_id)
        manifest = version.governing_manifest
        if (
            version.candidate_id != candidate_id
            or version.canonical_digest != version_digest
            or manifest.semantic_scope_digest != semantic_scope_digest
            or manifest.collision_namespace != namespace
            or manifest.collision_key_digest != key
        ):
            raise NativeCollisionHold("CURRENT_COLLISION_AUTHORITY_DIFFERS")
        citation = CurrentCandidateCitation.create(
            candidate_id=candidate_id,
            candidate_version_id=version.version_id,
            candidate_version_digest=version.canonical_digest,
            hypothesis_id=manifest.hypothesis_id,
            hypothesis_version_id=manifest.hypothesis_version_id,
            hypothesis_version_digest=manifest.hypothesis_version_digest,
            collision_namespace=namespace,
            collision_key_digest=key,
            source_definition_id=str(lead.request.definition_id),
            source_item_id=str(lead.request.item_id),
            retrieval_context_digest=context.digest,
            authorization_receipt_digest=authorization_receipt_digest,
            authorization_decision_id=authorization_decision_id,
        )
        return citation

    def retain_associated_candidate_citation(
        self,
        citation: CurrentCandidateCitation,
        candidate: StoryCandidateVersion,
        hypothesis: EventHypothesisVersion,
    ) -> CurrentCandidateCitation:
        """Bind a collision-slot Candidate to its checked current association."""
        if (
            type(citation) is not CurrentCandidateCitation
            or type(candidate) is not StoryCandidateVersion
            or type(hypothesis) is not EventHypothesisVersion
            or candidate.candidate_id != citation.candidate_id
            or candidate.version_id != citation.candidate_version_id
            or candidate.canonical_digest != citation.candidate_version_digest
            or candidate.governing_manifest.hypothesis_id != citation.hypothesis_id
            or candidate.governing_manifest.hypothesis_id != hypothesis.hypothesis_id
        ):
            raise NativeCollisionHold("CURRENT_CANDIDATE_ASSOCIATION_DIFFERS")
        associated = CurrentCandidateCitation.create(
            candidate_id=citation.candidate_id,
            candidate_version_id=citation.candidate_version_id,
            candidate_version_digest=citation.candidate_version_digest,
            hypothesis_id=hypothesis.hypothesis_id,
            hypothesis_version_id=hypothesis.version_id,
            hypothesis_version_digest=hypothesis.canonical_digest,
            collision_namespace=citation.collision_namespace,
            collision_key_digest=citation.collision_key_digest,
            source_definition_id=citation.source_definition_id,
            source_item_id=citation.source_item_id,
            retrieval_context_digest=citation.retrieval_context_digest,
            authorization_receipt_digest=citation.authorization_receipt_digest,
            authorization_decision_id=citation.authorization_decision_id,
        )
        self._validate_retained_association(associated)
        self._retain_candidate_citation(associated)
        return associated

    def candidate_citation_read_port(self) -> CurrentCandidateCitationReadPort:
        return _create_current_candidate_citation_read_port(
            self._require_candidate_citation
        )

    def request(
        self,
        triage: NativeTriageResult,
        retrieval: RetrievalInputBinding,
        *,
        proof: AuthenticationProof,
    ) -> CurrentCollisionEligibilityRequest:
        if type(triage) is not NativeTriageResult or triage.hypothesis is None:
            raise TypeError("native collision requires a retained Hypothesis")
        if triage.work.version.retrieval != retrieval:
            raise NativeCollisionHold("RETRIEVAL_COLLISION_AUTHORITY_DIFFERS")
        leads = triage.work.leads
        if len(leads) != 1:
            raise NativeCollisionHold("RETRIEVAL_COLLISION_AUTHORITY_DIFFERS")
        receipt, context = self._validated_context(retrieval, leads[0], proof=proof)
        authorization_receipt_digest, authorization_decision_id = (
            self._context_authorization(receipt, proof=proof)
        )
        collision_namespace, collision_key_digest = self._collision_slot(leads[0])
        watermark, candidate_id, _, _, _ = self._read(
            collision_namespace, collision_key_digest
        )
        binding = CandidateUseCollisionBinding(
            triage.hypothesis.hypothesis_id,
            triage.hypothesis.version_id,
            triage.hypothesis.canonical_digest,
            CandidateUseOperation.ADMIT_NEW_CANDIDATE
            if candidate_id is None else CandidateUseOperation.USE_CURRENT_CANDIDATE,
            candidate_id,
            collision_namespace,
            collision_key_digest,
            context.generation_id,
            context.query_valid_time,
            context.serving_time,
            watermark,
        )
        request_evidence = canonical_json_bytes({
            "schema_version": "newsroom.increment6.native-collision-request.v1",
            "controller_principal_id": self._identity.controller_principal_id,
            "authority_domain": self._identity.authority_domain,
            "retrieval_receipt_digest": receipt.receipt_digest,
            "context_id": context.context_id,
            "context_digest": context.digest,
            "lead_id": context.lead_id,
            "lead_digest": context.lead_digest,
            "authorization_receipt_digest": authorization_receipt_digest,
            "authorization_decision_id": authorization_decision_id,
            "binding": binding.canonical_value(),
        })
        request_digest = digest_bytes(request_evidence)
        self._retain_request(request_digest, request_evidence)
        return CurrentCollisionEligibilityRequest(binding, request_digest)

    def _validated_context(
        self,
        retrieval: RetrievalInputBinding,
        lead: NewsLead,
        *,
        proof: AuthenticationProof,
    ) -> tuple[NativeRetrievalContextReceipt, NativeRetrievalContext]:
        if type(retrieval) is not RetrievalInputBinding or retrieval.receipt_bytes is None:
            raise TypeError("native collision requires a retained retrieval receipt")
        if digest_bytes(retrieval.receipt_bytes) != retrieval.context_digest:
            raise ValueError("native collision retrieval receipt differs")
        try:
            receipt = NativeRetrievalContextReceipt.from_bytes(retrieval.receipt_bytes)
            context = self._read_context(receipt, proof=proof)
        except Exception as exc:
            raise NativeCollisionHold(
                "RETRIEVAL_COLLISION_AUTHORITY_INCOMPLETE"
            ) from exc
        if (
            receipt.receipt_digest != retrieval.context_digest
            or receipt.request_id != retrieval.request_id
            or receipt.request_digest != retrieval.request_digest
            or receipt.context_id != retrieval.context_id
            or receipt.controller_principal_id != self._identity.controller_principal_id
            or receipt.authority_domain != self._identity.authority_domain
            or receipt.authority_scope_id != self._identity.authority_scope_id
            or receipt.outcome != "COMPLETE"
            or context.context_id != receipt.context_id
            or context.digest != receipt.context_object_digest
            or context.authority_scope_id != receipt.authority_scope_id
            or context.generation_id != receipt.generation_id
            or context.query_valid_time != receipt.query_valid_time
            or context.serving_time != receipt.serving_time
            or context.outcome != "COMPLETE"
            or context.no_match is not receipt.no_match
            or not context.selected_documents
            or context.lead_id != str(lead.request.lead_id)
            or context.lead_digest != lead.canonical_digest
        ):
            raise NativeCollisionHold("RETRIEVAL_COLLISION_AUTHORITY_DIFFERS")
        return receipt, context

    @staticmethod
    def _collision_slot(lead: NewsLead) -> tuple[str, str]:
        return "native-story-candidate", digest_bytes(canonical_json_bytes({
            "schema_version": "newsroom.increment6.native-collision-key.v2",
            "source_definition_id": str(lead.request.definition_id),
            "source_item_id": str(lead.request.item_id),
        }))

    def _read_candidate_version(self, version_id: str) -> StoryCandidateVersion:
        uri = f"file:{self._path.resolve()}?mode=ro"
        try:
            with closing(sqlite3.connect(uri, uri=True, isolation_level=None)) as connection:
                row = connection.execute(
                    "SELECT version_bytes FROM story_candidate_admission_receipts_v2 "
                    "WHERE version_id=?",
                    (version_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise NativeCollisionHold("CURRENT_COLLISION_AUTHORITY_UNAVAILABLE") from exc
        if row is None:
            raise NativeCollisionHold("CURRENT_COLLISION_AUTHORITY_DIFFERS")
        try:
            return StoryCandidateVersion.from_canonical_bytes(bytes(row[0]))
        except Exception as exc:
            raise NativeCollisionHold("CURRENT_COLLISION_AUTHORITY_DIFFERS") from exc

    def _retain_candidate_citation(self, citation: CurrentCandidateCitation) -> None:
        with self._lock, self._journal_connection() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO native_current_candidate_citations VALUES(?,?,?)",
                (citation.citation_id, citation.canonical_digest, citation.canonical_bytes),
            )
            row = connection.execute(
                "SELECT citation_digest,citation_bytes FROM native_current_candidate_citations "
                "WHERE citation_id=?",
                (citation.citation_id,),
            ).fetchone()
        if row is None or str(row[0]) != citation.canonical_digest or bytes(row[1]) != citation.canonical_bytes:
            raise NativeCollisionHold("CURRENT_COLLISION_CITATION_DIFFERS")

    def _require_candidate_citation(
        self, citation_id: str, citation_digest: str
    ) -> CurrentCandidateCitation:
        with self._lock, self._journal_connection() as connection:
            row = connection.execute(
                "SELECT citation_digest,citation_bytes FROM native_current_candidate_citations "
                "WHERE citation_id=?",
                (citation_id,),
            ).fetchone()
        if row is None or str(row[0]) != citation_digest:
            raise NativeCollisionHold("CURRENT_COLLISION_CITATION_DIFFERS")
        citation = CurrentCandidateCitation.from_canonical_bytes(bytes(row[1]))
        if citation.citation_id != citation_id or citation.canonical_digest != citation_digest:
            raise NativeCollisionHold("CURRENT_COLLISION_CITATION_DIFFERS")
        self._validate_retained_association(citation)
        return citation

    def _validate_retained_association(
        self, citation: CurrentCandidateCitation
    ) -> None:
        """Recheck the immutable SAME_STATE chain named by a citation."""
        uri = f"file:{self._path.resolve()}?mode=ro"
        try:
            with closing(
                sqlite3.connect(uri, uri=True, isolation_level=None)
            ) as connection:
                candidate_row = connection.execute(
                    "SELECT candidate_id,version_id,version_digest,version_bytes FROM "
                    "story_candidate_admission_receipts_v2 WHERE version_id=?",
                    (citation.candidate_version_id,),
                ).fetchone()
                target_row = connection.execute(
                    "SELECT hypothesis_id,version_id,ordinal,canonical_digest,"
                    "canonical_bytes FROM event_hypothesis_versions_v2 "
                    "WHERE version_id=?",
                    (citation.hypothesis_version_id,),
                ).fetchone()
                if candidate_row is None or target_row is None:
                    raise NativeCollisionHold(
                        "CURRENT_CANDIDATE_ASSOCIATION_DIFFERS"
                    )
                candidate = StoryCandidateVersion.from_canonical_bytes(
                    bytes(candidate_row[3])
                )
                target = EventHypothesisVersion.from_canonical_bytes(
                    bytes(target_row[4])
                )
                if (
                    str(candidate_row[0]) != candidate.candidate_id
                    or str(candidate_row[1]) != candidate.version_id
                    or str(candidate_row[2]) != candidate.canonical_digest
                    or candidate.canonical_bytes != bytes(candidate_row[3])
                    or candidate.candidate_id != citation.candidate_id
                    or candidate.version_id != citation.candidate_version_id
                    or candidate.canonical_digest
                    != citation.candidate_version_digest
                    or candidate.governing_manifest.hypothesis_id
                    != citation.hypothesis_id
                    or str(target_row[0]) != target.hypothesis_id
                    or str(target_row[1]) != target.version_id
                    or int(target_row[2]) != target.ordinal
                    or str(target_row[3]) != target.canonical_digest
                    or target.canonical_bytes != bytes(target_row[4])
                    or target.hypothesis_id != citation.hypothesis_id
                    or target.version_id != citation.hypothesis_version_id
                    or target.canonical_digest
                    != citation.hypothesis_version_digest
                ):
                    raise NativeCollisionHold(
                        "CURRENT_CANDIDATE_ASSOCIATION_DIFFERS"
                    )
                previous_id = candidate.governing_manifest.hypothesis_version_id
                previous_digest = (
                    candidate.governing_manifest.hypothesis_version_digest
                )
                previous_ordinal_row = connection.execute(
                    "SELECT ordinal FROM event_hypothesis_versions_v2 "
                    "WHERE version_id=? AND hypothesis_id=?",
                    (previous_id, citation.hypothesis_id),
                ).fetchone()
                if previous_ordinal_row is None:
                    raise NativeCollisionHold(
                        "CURRENT_CANDIDATE_ASSOCIATION_DIFFERS"
                    )
                previous_ordinal = int(previous_ordinal_row[0])
                while previous_id != target.version_id:
                    rows = connection.execute(
                        "SELECT version_id,ordinal,previous_version_id,"
                        "previous_version_digest,proposed_relationship,"
                        "canonical_digest,canonical_bytes "
                        "FROM event_hypothesis_versions_v2 "
                        "WHERE hypothesis_id=? AND previous_version_id=? LIMIT 2",
                        (citation.hypothesis_id, previous_id),
                    ).fetchall()
                    if len(rows) != 1:
                        raise NativeCollisionHold(
                            "CURRENT_CANDIDATE_ASSOCIATION_DIFFERS"
                        )
                    successor = EventHypothesisVersion.from_canonical_bytes(
                        bytes(rows[0][6])
                    )
                    relationship_rows = connection.execute(
                        "SELECT decision_id,subject_hypothesis_id,"
                        "subject_version_id,subject_version_digest,"
                        "selected_comparator_hypothesis_id,"
                        "selected_comparator_version_id,"
                        "selected_comparator_version_digest,decision,"
                        "assessment_bytes,assessment_digest,evidence_bytes,"
                        "evidence_digest "
                        "FROM event_hypothesis_relationship_decisions "
                        "WHERE subject_version_id=? LIMIT 2",
                        (successor.version_id,),
                    ).fetchall()
                    if len(relationship_rows) != 1:
                        raise NativeCollisionHold(
                            "CURRENT_CANDIDATE_ASSOCIATION_DIFFERS"
                        )
                    relationship = RelationshipAssessment.from_canonical_bytes(
                        bytes(relationship_rows[0][8])
                    )
                    evidence_bytes = bytes(relationship_rows[0][10])
                    evidence_value = json.loads(evidence_bytes)
                    if type(evidence_value) is not list:
                        raise NativeCollisionHold(
                            "CURRENT_CANDIDATE_ASSOCIATION_DIFFERS"
                        )
                    evidence = tuple(
                        ComparatorEvidence.from_value(item)
                        for item in evidence_value
                    )
                    replay = assess_relationships(
                        relationship.subject,
                        relationship.comparator_manifest,
                        evidence,
                    )
                    selected = relationship.comparator
                    previous_ordinal += 1
                    if (
                        successor.version_id != str(rows[0][0])
                        or successor.ordinal != int(rows[0][1])
                        or successor.ordinal != previous_ordinal
                        or successor.previous_version_id != str(rows[0][2])
                        or successor.previous_version_digest != str(rows[0][3])
                        or successor.proposed_relationship.value != str(rows[0][4])
                        or successor.canonical_digest != str(rows[0][5])
                        or successor.canonical_bytes != bytes(rows[0][6])
                        or successor.previous_version_id != previous_id
                        or successor.previous_version_digest != previous_digest
                        or successor.proposed_relationship.value != "SAME_STATE"
                        or relationship.canonical_digest
                        != str(relationship_rows[0][0])
                        or relationship.canonical_digest
                        != str(relationship_rows[0][9])
                        or relationship.subject.hypothesis_id
                        != str(relationship_rows[0][1])
                        or relationship.subject.version_id
                        != str(relationship_rows[0][2])
                        or relationship.subject.version_digest
                        != str(relationship_rows[0][3])
                        or selected is None
                        or selected.hypothesis_id
                        != str(relationship_rows[0][4])
                        or selected.version_id != str(relationship_rows[0][5])
                        or selected.version_digest != str(relationship_rows[0][6])
                        or relationship.decision.value
                        != str(relationship_rows[0][7])
                        or relationship.evidence_digest
                        != str(relationship_rows[0][11])
                        or canonical_json_bytes(evidence_value) != evidence_bytes
                        or replay != relationship
                        or relationship.decision
                        is not CanonicalOutcome.REL_SAME_STATE
                        or relationship.subject.version_id != successor.version_id
                        or relationship.subject.version_digest
                        != successor.canonical_digest
                        or selected.version_id != previous_id
                        or selected.version_digest != previous_digest
                    ):
                        raise NativeCollisionHold(
                            "CURRENT_CANDIDATE_ASSOCIATION_DIFFERS"
                        )
                    previous_id = successor.version_id
                    previous_digest = successor.canonical_digest
                if previous_ordinal != target.ordinal:
                    raise NativeCollisionHold(
                        "CURRENT_CANDIDATE_ASSOCIATION_DIFFERS"
                    )
        except NativeCollisionHold:
            raise
        except Exception as exc:
            raise NativeCollisionHold(
                "CURRENT_CANDIDATE_ASSOCIATION_DIFFERS"
            ) from exc

    def __call__(
        self, request: CurrentCollisionEligibilityRequest
    ) -> CurrentCollisionAuthoritySnapshot:
        if type(request) is not CurrentCollisionEligibilityRequest:
            raise TypeError("native collision request must be exact typed")
        request_evidence = self._request_evidence(request.named_request_digest)
        try:
            retained = json.loads(request_evidence)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise NativeCollisionHold("COLLISION_REQUEST_IDENTITY_DIFFERS") from exc
        if (
            digest_bytes(request_evidence) != request.named_request_digest
            or canonical_json_bytes(retained) != request_evidence
            or retained.get("schema_version")
            != "newsroom.increment6.native-collision-request.v1"
            or retained.get("controller_principal_id")
            != self._identity.controller_principal_id
            or retained.get("authority_domain") != self._identity.authority_domain
            or retained.get("binding") != request.binding.canonical_value()
        ):
            raise NativeCollisionHold("COLLISION_REQUEST_IDENTITY_DIFFERS")
        authorization_receipt_digest = retained.get(
            "authorization_receipt_digest"
        )
        authorization_decision_id = retained.get("authorization_decision_id")
        try:
            validate_sha256_digest(authorization_receipt_digest)
        except (TypeError, ValueError):
            raise NativeCollisionHold("COLLISION_REQUEST_IDENTITY_DIFFERS") from None
        if not isinstance(authorization_decision_id, str) or not authorization_decision_id:
            raise NativeCollisionHold("COLLISION_REQUEST_IDENTITY_DIFFERS")
        (
            watermark,
            candidate_id,
            candidate_version_id,
            candidate_version_digest,
            candidate_semantic_scope_digest,
        ) = self._read(
            request.binding.collision_namespace,
            request.binding.collision_key_digest,
        )
        state = CollisionState.UNOCCUPIED if candidate_id is None else CollisionState.OCCUPIED
        context = TrustedCurrentCollisionAuthorityContext(
            request.binding.generation_id,
            watermark,
            request.binding.query_valid_time,
            request.binding.serving_time,
            self._identity.authority_scope_id,
            _PROFILE_ID,
            _ADAPTER_CONFIG_DIGEST,
            authorization_receipt_digest,
            authorization_decision_id,
            _PORT_REGISTRY_DIGEST,
            _PORT_ID,
        )
        authority_bytes = canonical_json_bytes({
            "schema_version": "newsroom.increment6.native-collision-authority.v1",
            "request_digest": request.named_request_digest,
            "authority_scope_id": context.authority_scope_id,
            "authority_profile_id": context.authority_profile_id,
            "adapter_config_digest": context.adapter_config_digest,
            "generation_id": context.generation_id,
            "authority_watermark": watermark,
            "query_valid_time": context.query_valid_time,
            "serving_time": context.serving_time,
            "collision_namespace": request.binding.collision_namespace,
            "collision_key_digest": request.binding.collision_key_digest,
            "collision_state": state.value,
            "candidate_id": candidate_id,
            "candidate_version_id": candidate_version_id,
            "candidate_version_digest": candidate_version_digest,
            "candidate_semantic_scope_digest": candidate_semantic_scope_digest,
            "subject_id": request.binding.subject_id,
            "subject_version_id": request.binding.subject_version_id,
            "subject_version_digest": request.binding.subject_version_digest,
            "outcome": "COMPLETE",
        })
        execution_bytes = canonical_json_bytes({
            "schema_version": "newsroom.increment6.native-collision-execution.v1",
            "request_digest": request.named_request_digest,
            "authority_receipt_digest": digest_bytes(authority_bytes),
            "authorization_receipt_digest": context.authorization_receipt_digest,
            "authorization_decision_id": context.authorization_decision_id,
            "port_registry_digest": context.port_registry_digest,
            "port_id": context.port_id,
            "generation_id": context.generation_id,
            "authority_watermark": watermark,
            "query_valid_time": context.query_valid_time,
            "serving_time": context.serving_time,
            "outcome": "COMPLETE",
        })
        evidence = NativeCurrentCollisionReceiptEvidence(
            request.named_request_digest, execution_bytes, authority_bytes
        )
        self._retain(evidence, watermark, state, candidate_id)
        return CurrentCollisionAuthoritySnapshot(evidence, context)

    def _context_authorization(
        self,
        receipt: NativeRetrievalContextReceipt,
        *,
        proof: AuthenticationProof,
    ) -> tuple[str, str]:
        try:
            provenance = self._events.provenance(receipt.event_id, proof=proof)
            event = provenance.event
            authentication = provenance.authentication
            request = provenance.authorization_request
            decision = provenance.authorization_decision
            definition = provenance.command_definition
            if (
                event.event_id != receipt.event_id
                or event.command_id != receipt.command_id
                or event.aggregate_id != str(receipt.aggregate_id)
                or event.aggregate_version != receipt.aggregate_version
                or event.object_admission_id != str(receipt.admission_id)
                or event.payload_digest != receipt.context_object_digest
                or definition.command_type != NATIVE_CONTEXT_COMMAND
                or event.principal_id != self._identity.controller_principal_id
                or authentication.principal_id
                != self._identity.controller_principal_id
                or request.principal_id != self._identity.controller_principal_id
                or authentication.authority_domain != self._identity.authority_domain
                or request.authority_domain != self._identity.authority_domain
                or event.authentication_context_id
                != authentication.authentication_context_id
                or request.authentication_context_id
                != authentication.authentication_context_id
                or decision.authentication_context_id
                != authentication.authentication_context_id
                or event.authorization_request_digest != request.request_digest
                or decision.authorization_request_digest != request.request_digest
                or event.authorization_decision_id
                != decision.authorization_decision_id
                or request.operation_type != f"command:{NATIVE_CONTEXT_COMMAND}"
                or request.required_scope != "authority.retrieval.context"
                or not decision.allowed
                or digest_bytes(decision.canonical_bytes)
                != decision.canonical_digest
            ):
                raise ValueError
            validate_sha256_digest(decision.canonical_digest)
            if not decision.authorization_decision_id:
                raise ValueError
        except Exception as exc:
            raise NativeCollisionHold(
                "RETRIEVAL_COLLISION_AUTHORIZATION_DIFFERS"
            ) from exc
        return decision.canonical_digest, decision.authorization_decision_id

    def _read(
        self, namespace: str | None = None, collision_key: str | None = None
    ) -> tuple[
        int,
        str | None,
        str | None,
        str | None,
        str | None,
    ]:
        uri = f"file:{self._path.resolve()}?mode=ro"
        try:
            with closing(sqlite3.connect(uri, uri=True, isolation_level=None)) as connection:
                connection.execute("BEGIN")
                watermark = int(connection.execute(
                    "SELECT COALESCE(MAX(ledger_seq),0) FROM ledger_events"
                ).fetchone()[0])
                if namespace is None:
                    connection.execute("COMMIT")
                    return watermark, None, None, None, None
                rows = connection.execute(_QUERY, (namespace, collision_key)).fetchall()
                connection.execute("COMMIT")
        except sqlite3.Error as exc:
            raise NativeCollisionHold("CURRENT_COLLISION_AUTHORITY_UNAVAILABLE") from exc
        if len(rows) > 1:
            raise NativeCollisionHold("CURRENT_COLLISION_AUTHORITY_AMBIGUOUS")
        if not rows:
            return watermark, None, None, None, None
        row = rows[0]
        return watermark, str(row[0]), str(row[1]), str(row[2]), str(row[3])

    @contextmanager
    def _journal_connection(self):
        connection = sqlite3.connect(self._journal, isolation_level=None)
        try:
            connection.execute("PRAGMA busy_timeout=5000")
            yield connection
        finally:
            connection.close()

    def _retain(
        self,
        evidence: NativeCurrentCollisionReceiptEvidence,
        watermark: int,
        state: CollisionState,
        candidate_id: str | None,
    ) -> None:
        receipt_digest = digest_bytes(canonical_json_bytes({
            "execution": evidence.execution_receipt_digest,
            "authority": evidence.authority_receipt_digest,
        }))
        with self._lock, self._journal_connection() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO native_collision_receipts VALUES(?,?,?,?,?,?,?)",
                (
                    receipt_digest,
                    evidence.request_digest,
                    watermark,
                    state.value,
                    candidate_id,
                    evidence.execution_receipt_bytes,
                    evidence.authority_receipt_bytes,
                ),
            )

    def _retain_request(self, request_digest: str, evidence: bytes) -> None:
        with self._lock, self._journal_connection() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO native_collision_requests VALUES(?,?)",
                (request_digest, evidence),
            )
            retained = connection.execute(
                "SELECT request_evidence_bytes FROM native_collision_requests "
                "WHERE request_digest=?",
                (request_digest,),
            ).fetchone()
        if retained is None or bytes(retained[0]) != evidence:
            raise NativeCollisionHold("COLLISION_REQUEST_IDENTITY_DIFFERS")

    def _request_evidence(self, request_digest: str) -> bytes:
        with self._lock, self._journal_connection() as connection:
            row = connection.execute(
                "SELECT request_evidence_bytes FROM native_collision_requests "
                "WHERE request_digest=?",
                (request_digest,),
            ).fetchone()
        if row is None:
            raise NativeCollisionHold("COLLISION_REQUEST_IDENTITY_DIFFERS")
        return bytes(row[0])


__all__ = [
    "NativeCollisionAuthority",
    "NativeCollisionHold",
    "NativeCollisionIdentity",
]
