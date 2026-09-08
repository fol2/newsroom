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

    def request(
        self,
        triage: NativeTriageResult,
        retrieval: RetrievalInputBinding,
        *,
        proof: AuthenticationProof,
    ) -> CurrentCollisionEligibilityRequest:
        if type(triage) is not NativeTriageResult or triage.hypothesis is None:
            raise TypeError("native collision requires a retained Hypothesis")
        if type(retrieval) is not RetrievalInputBinding or retrieval.receipt_bytes is None:
            raise TypeError("native collision requires a retained retrieval receipt")
        if triage.work.version.retrieval != retrieval:
            raise NativeCollisionHold("RETRIEVAL_COLLISION_AUTHORITY_DIFFERS")
        if digest_bytes(retrieval.receipt_bytes) != retrieval.context_digest:
            raise ValueError("native collision retrieval receipt differs")
        try:
            receipt = NativeRetrievalContextReceipt.from_bytes(
                retrieval.receipt_bytes
            )
            context = self._read_context(receipt, proof=proof)
        except Exception as exc:
            raise NativeCollisionHold(
                "RETRIEVAL_COLLISION_AUTHORITY_INCOMPLETE"
            ) from exc
        leads = triage.work.leads
        if (
            receipt.receipt_digest != retrieval.context_digest
            or receipt.request_id != retrieval.request_id
            or receipt.request_digest != retrieval.request_digest
            or receipt.context_id != retrieval.context_id
            or receipt.controller_principal_id
            != self._identity.controller_principal_id
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
            or len(leads) != 1
            or context.lead_id != str(leads[0].request.lead_id)
            or context.lead_digest != leads[0].canonical_digest
        ):
            raise NativeCollisionHold("RETRIEVAL_COLLISION_AUTHORITY_DIFFERS")
        authorization_receipt_digest, authorization_decision_id = (
            self._context_authorization(receipt, proof=proof)
        )
        collision_namespace = "native-story-candidate"
        collision_key_digest = digest_bytes(canonical_json_bytes({
            "schema_version": "newsroom.increment6.native-collision-key.v2",
            "source_definition_id": str(leads[0].request.definition_id),
            "source_item_id": str(leads[0].request.item_id),
        }))
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
