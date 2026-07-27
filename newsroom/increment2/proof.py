from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from newsroom.authority import AuthenticationProof, validate_sha256_digest
from newsroom.integrated import IntegratedTriageProposalId
from newsroom.projection import ProjectionGenerationId
from newsroom.retrieval import (
    FindRelatedEventCandidatesRequest,
    INTEGRATED_FIXTURE_V2_RETRIEVAL,
    RetrievalBranch,
    RetrievalContextV2,
    RetrievalContextV2Id,
    RetrievalOutcome,
    RetrievalRequestId,
)

from .models import (
    DevelopmentCandidateAdmissionRequest,
    DevelopmentCandidateAdmissionView,
    INTEGRATED_FIXTURE_V2_DEVELOPMENT_CANDIDATE,
)


class Increment2ProofStateError(RuntimeError):
    """Raised when a composed proof differs from retained Increment 2 authority."""


class _CandidateAuthority(Protocol):
    retrieval: Any
    candidates: Any

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class Increment2PreparedAuthority:
    """Exact authority boundary prepared before the named retrieval is served."""

    fixture_id: str
    generation_id: ProjectionGenerationId
    checkpoint_ledger_seq: int
    relation_key: str

    def __post_init__(self) -> None:
        if self.fixture_id != INTEGRATED_FIXTURE_V2_RETRIEVAL.fixture_id:
            raise Increment2ProofStateError(
                "prepared fixture differs from integrated_fixture_v2"
            )
        if not isinstance(self.generation_id, ProjectionGenerationId):
            raise TypeError("prepared generation identity must be typed")
        if (
            isinstance(self.checkpoint_ledger_seq, bool)
            or not isinstance(self.checkpoint_ledger_seq, int)
            or self.checkpoint_ledger_seq <= 0
        ):
            raise Increment2ProofStateError(
                "prepared projection checkpoint must be positive"
            )
        validate_sha256_digest(self.relation_key, field="relation_key")
        if (
            self.relation_key
            != INTEGRATED_FIXTURE_V2_DEVELOPMENT_CANDIDATE.relation_key
        ):
            raise Increment2ProofStateError(
                "prepared relation differs from Candidate fixture authority"
            )


@dataclass(frozen=True, slots=True)
class Increment2ProofKeys:
    request_id: RetrievalRequestId
    context_id: RetrievalContextV2Id
    proposal_id: IntegratedTriageProposalId
    retrieval_idempotency_key: str
    candidate_idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, RetrievalRequestId):
            raise TypeError("proof retrieval request identity must be typed")
        if not isinstance(self.context_id, RetrievalContextV2Id):
            raise TypeError("proof retrieval context identity must be typed")
        if not isinstance(self.proposal_id, IntegratedTriageProposalId):
            raise TypeError("proof Candidate proposal identity must be typed")
        for field_name in (
            "retrieval_idempotency_key",
            "candidate_idempotency_key",
        ):
            value = getattr(self, field_name)
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or len(value.encode("utf-8")) > 256
            ):
                raise ValueError(f"{field_name} is invalid")


@dataclass(frozen=True, slots=True)
class Increment2ProofEnvironment:
    """Trusted composition only; no authority writer or graph handle is retained."""

    prepare: Callable[
        [AuthenticationProof, Increment2ProofKeys],
        Increment2PreparedAuthority,
    ] = field(repr=False)
    open_candidate_authority: Callable[
        [], _CandidateAuthority
    ] = field(repr=False)

    def __post_init__(self) -> None:
        if not callable(self.prepare):
            raise TypeError("Increment 2 proof preparation must be callable")
        if not callable(self.open_candidate_authority):
            raise TypeError("Increment 2 Candidate authority opener must be callable")


@dataclass(frozen=True, slots=True)
class Increment2CompleteProofResult:
    prepared: Increment2PreparedAuthority
    context: RetrievalContextV2
    candidate: DevelopmentCandidateAdmissionView
    retrieval_replay_confirmed: bool
    candidate_replay_confirmed: bool
    restart_confirmed: bool


class Increment2CompleteProofController:
    """Compose the complete fixture proof through retained public facades.

    The controller owns no SQLite connection, Neo4j driver, governed object,
    relation or Candidate authority. The environment prepares the exact fixture
    generation through public authority facades and opens the single-writer
    Candidate boundary. This controller only binds and verifies the hand-offs.
    """

    __slots__ = ("_environment",)

    def __init__(self, environment: Increment2ProofEnvironment) -> None:
        if not isinstance(environment, Increment2ProofEnvironment):
            raise TypeError("Increment 2 proof requires a typed environment")
        self._environment = environment

    def run(
        self,
        *,
        proof: AuthenticationProof,
        keys: Increment2ProofKeys,
    ) -> Increment2CompleteProofResult:
        if not isinstance(proof, AuthenticationProof):
            raise TypeError("Increment 2 proof authentication must be typed")
        if not isinstance(keys, Increment2ProofKeys):
            raise TypeError("Increment 2 proof keys must be typed")

        prepared = self._environment.prepare(proof, keys)
        if not isinstance(prepared, Increment2PreparedAuthority):
            raise TypeError("Increment 2 preparation must return typed authority")
        request = self._retrieval_request(keys)

        system = self._environment.open_candidate_authority()
        try:
            result = system.retrieval.find_related_event_candidates(
                request,
                proof=proof,
            )
            if result.outcome is not RetrievalOutcome.COMPLETE or result.context is None:
                reason = None if result.failure is None else result.failure.reason_code
                raise Increment2ProofStateError(
                    f"complete retrieval proof failed: {reason}"
                )
            context = result.context
            self._require_exact_context(context, prepared)
            candidate_request = DevelopmentCandidateAdmissionRequest(
                proposal_id=keys.proposal_id,
                retrieval_context_id=context.context_id,
                expected_context_digest=context.context_digest,
                idempotency_key=keys.candidate_idempotency_key,
            )
            candidate = system.candidates.admit(
                candidate_request,
                proof=proof,
            )
            retrieval_replay = system.retrieval.find_related_event_candidates(
                request,
                proof=proof,
            )
            candidate_replay = system.candidates.admit(
                candidate_request,
                proof=proof,
            )
            if (
                not retrieval_replay.replayed
                or retrieval_replay.context != context
            ):
                raise Increment2ProofStateError(
                    "retrieval replay differs from retained context authority"
                )
            if candidate_replay != candidate:
                raise Increment2ProofStateError(
                    "Candidate replay differs from retained admission authority"
                )
        finally:
            system.close()

        reopened = self._environment.open_candidate_authority()
        try:
            retained = reopened.candidates.decision(
                candidate.decision_id,
                proof=proof,
            )
            if retained != candidate:
                raise Increment2ProofStateError(
                    "Candidate restart read differs from immutable authority"
                )
        finally:
            reopened.close()

        return Increment2CompleteProofResult(
            prepared=prepared,
            context=context,
            candidate=candidate,
            retrieval_replay_confirmed=True,
            candidate_replay_confirmed=True,
            restart_confirmed=True,
        )

    @staticmethod
    def _retrieval_request(keys: Increment2ProofKeys) -> FindRelatedEventCandidatesRequest:
        fixture = INTEGRATED_FIXTURE_V2_RETRIEVAL
        return FindRelatedEventCandidatesRequest(
            request_id=keys.request_id,
            context_id=keys.context_id,
            fixture_id=fixture.fixture_id,
            query_revision_id=fixture.query_revision_id,
            query_hypothesis_version_id=fixture.query_hypothesis_version_id,
            query_valid_time=fixture.query_valid_time,
            idempotency_key=keys.retrieval_idempotency_key,
        )

    @staticmethod
    def _require_exact_context(
        context: RetrievalContextV2,
        prepared: Increment2PreparedAuthority,
    ) -> None:
        manifest = INTEGRATED_FIXTURE_V2_DEVELOPMENT_CANDIDATE
        if (
            context.projection.identity.generation_id
            != prepared.generation_id
            or context.projection.contiguous_ledger_seq
            != prepared.checkpoint_ledger_seq
        ):
            raise Increment2ProofStateError(
                "retrieval context differs from prepared projection authority"
            )
        if tuple(item.branch for item in context.branches) != tuple(RetrievalBranch):
            raise Increment2ProofStateError(
                "retrieval context does not retain all four named branches"
            )
        graph = next(
            item
            for item in context.branches
            if item.branch is RetrievalBranch.ADMITTED_GRAPH
        )
        if (
            len(graph.hits) != 1
            or graph.hits[0].source_kind != "RELATION_ASSERTION"
            or graph.hits[0].source_identity != prepared.relation_key
        ):
            raise Increment2ProofStateError(
                "retrieval graph branch differs from admitted relation authority"
            )
        if not context.retained_candidates:
            raise Increment2ProofStateError(
                "retrieval context lacks the prior Candidate neighbourhood"
            )
        first = context.retained_candidates[0]
        if (
            first.candidate_version_id
            != str(manifest.prior_candidate_version_id)
            or set(first.contributing_branches) != set(RetrievalBranch)
        ):
            raise Increment2ProofStateError(
                "retrieval fusion differs from the complete fixture contract"
            )
        if tuple(item.passage_id for item in context.hydrated_passages) != (
            "ifv2-prior-en",
            "ifv2-prior-zh-hk",
        ):
            raise Increment2ProofStateError(
                "retrieval context lacks exact bilingual governed hydration"
            )


__all__ = [
    "Increment2CompleteProofController",
    "Increment2CompleteProofResult",
    "Increment2PreparedAuthority",
    "Increment2ProofEnvironment",
    "Increment2ProofKeys",
    "Increment2ProofStateError",
]
