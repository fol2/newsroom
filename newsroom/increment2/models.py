from __future__ import annotations

from dataclasses import dataclass
import json

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
    validate_sha256_digest,
)
from newsroom.authority.types import EventId, TrustScope, UUIDv4Id, UtcTimestamp, require_token
from newsroom.integrated.models import (
    CandidateAdmissionDecisionId,
    CandidateAdmissionOutcome,
    CandidateRoute,
    IntegratedContractError,
    IntegratedFixtureId,
    IntegratedHypothesisVersionId,
    IntegratedLeadId,
    IntegratedSignalId,
    IntegratedTriageProposalId,
    StoryCandidateId,
    StoryCandidateVersionId,
)
from newsroom.relations import INTEGRATED_FIXTURE_V2, governed_relation_key
from newsroom.retrieval import (
    INTEGRATED_FIXTURE_V2_RETRIEVAL,
    RetrievalContextV2Id,
)


@dataclass(frozen=True, slots=True)
class DevelopmentCandidateAdmissionRequest:
    proposal_id: IntegratedTriageProposalId
    retrieval_context_id: RetrievalContextV2Id
    expected_context_digest: str
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.proposal_id, IntegratedTriageProposalId):
            raise IntegratedContractError("development proposal identity must be typed")
        if not isinstance(self.retrieval_context_id, RetrievalContextV2Id):
            raise IntegratedContractError("retrieval context identity must be typed")
        normalized = validate_sha256_digest(
            self.expected_context_digest,
            field="expected_context_digest",
        )
        if normalized != self.expected_context_digest:
            raise IntegratedContractError(
                "expected context digest must be canonical lowercase"
            )
        if (
            not isinstance(self.idempotency_key, str)
            or not self.idempotency_key
            or self.idempotency_key != self.idempotency_key.strip()
            or len(self.idempotency_key.encode("utf-8")) > 256
        ):
            raise IntegratedContractError(
                "development admission idempotency key is invalid"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "contract": "newsroom-development-candidate-admission-request-v2",
            "proposal_id": str(self.proposal_id),
            "retrieval_context_id": str(self.retrieval_context_id),
            "expected_context_digest": self.expected_context_digest,
            "idempotency_key": self.idempotency_key,
        }


@dataclass(frozen=True, slots=True)
class DevelopmentCandidateManifest:
    fixture_id: IntegratedFixtureId
    signal_id: IntegratedSignalId
    lead_id: IntegratedLeadId
    hypothesis_version_id: IntegratedHypothesisVersionId
    prior_hypothesis_version_id: IntegratedHypothesisVersionId
    prior_candidate_version_id: StoryCandidateVersionId
    current_revision_id: str
    prior_revision_id: str
    canonical_process_id: str
    relation_key: str
    retrieval_contract_digest: str
    route: CandidateRoute = CandidateRoute.DEVELOPMENT
    hypothesis_trust_scope: TrustScope = TrustScope.PROPOSED
    policy_version: str = "integrated-fixture-v2-development-candidate-v1"

    def __post_init__(self) -> None:
        if not isinstance(self.fixture_id, IntegratedFixtureId):
            raise IntegratedContractError("development fixture identity must be typed")
        if not isinstance(self.signal_id, IntegratedSignalId):
            raise IntegratedContractError("development signal identity must be typed")
        if not isinstance(self.lead_id, IntegratedLeadId):
            raise IntegratedContractError("development lead identity must be typed")
        if not isinstance(
            self.hypothesis_version_id, IntegratedHypothesisVersionId
        ) or not isinstance(
            self.prior_hypothesis_version_id, IntegratedHypothesisVersionId
        ):
            raise IntegratedContractError("development hypotheses must be typed")
        if not isinstance(self.prior_candidate_version_id, StoryCandidateVersionId):
            raise IntegratedContractError("prior Candidate version must be typed")
        for field_name in ("current_revision_id", "prior_revision_id"):
            value = getattr(self, field_name)
            try:
                UUIDv4Id.parse(value)
            except ValueError as exc:
                raise IntegratedContractError(
                    f"{field_name} must be canonical UUIDv4"
                ) from exc
        for field_name in ("canonical_process_id", "policy_version"):
            require_token(getattr(self, field_name), field=field_name)
        validate_sha256_digest(self.relation_key, field="relation_key")
        validate_sha256_digest(
            self.retrieval_contract_digest,
            field="retrieval_contract_digest",
        )
        if self.route is not CandidateRoute.DEVELOPMENT:
            raise IntegratedContractError("fixture Candidate route must be DEVELOPMENT")
        if self.hypothesis_trust_scope is not TrustScope.PROPOSED:
            raise IntegratedContractError(
                "development Candidate hypothesis must remain PROPOSED"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "contract": "newsroom-development-candidate-manifest-v2",
            "fixture_id": str(self.fixture_id),
            "signal_id": str(self.signal_id),
            "lead_id": str(self.lead_id),
            "hypothesis_version_id": str(self.hypothesis_version_id),
            "prior_hypothesis_version_id": str(
                self.prior_hypothesis_version_id
            ),
            "prior_candidate_version_id": str(
                self.prior_candidate_version_id
            ),
            "current_revision_id": self.current_revision_id,
            "prior_revision_id": self.prior_revision_id,
            "canonical_process_id": self.canonical_process_id,
            "relation_key": self.relation_key,
            "retrieval_contract_digest": self.retrieval_contract_digest,
            "route": self.route.value,
            "hypothesis_trust_scope": self.hypothesis_trust_scope.value,
            "policy_version": self.policy_version,
        }

    @property
    def manifest_digest(self) -> str:
        return digest_bytes(canonical_json_bytes(self.canonical_value()))

    @property
    def semantic_collision_digest(self) -> str:
        return digest_canonical(
            {
                "contract": "newsroom-development-candidate-semantic-slot-v2",
                "fixture_id": str(self.fixture_id),
                "canonical_process_id": self.canonical_process_id,
                "hypothesis_version_id": str(self.hypothesis_version_id),
                "prior_candidate_version_id": str(
                    self.prior_candidate_version_id
                ),
                "route": self.route.value,
                "relation_key": self.relation_key,
                "manifest_digest": self.manifest_digest,
            }
        )


@dataclass(frozen=True, slots=True)
class DevelopmentCandidateAdmissionView:
    decision_id: CandidateAdmissionDecisionId
    outcome: CandidateAdmissionOutcome
    proposal_id: IntegratedTriageProposalId
    candidate_id: StoryCandidateId
    candidate_version_id: StoryCandidateVersionId
    candidate_version: int
    route: CandidateRoute
    fixture_id: IntegratedFixtureId
    retrieval_context_id: RetrievalContextV2Id
    retrieval_context_digest: str
    manifest_digest: str
    semantic_collision_digest: str
    relation_key: str
    prior_candidate_version_id: StoryCandidateVersionId
    authority_event_id: EventId
    authority_aggregate_version: int
    recorded_at: UtcTimestamp

    def __post_init__(self) -> None:
        if not isinstance(self.decision_id, CandidateAdmissionDecisionId):
            raise IntegratedContractError("candidate decision identity must be typed")
        if not isinstance(self.outcome, CandidateAdmissionOutcome):
            raise IntegratedContractError("candidate outcome must be typed")
        if not isinstance(self.proposal_id, IntegratedTriageProposalId):
            raise IntegratedContractError("candidate proposal identity must be typed")
        if not isinstance(self.candidate_id, StoryCandidateId):
            raise IntegratedContractError("candidate identity must be typed")
        if not isinstance(self.candidate_version_id, StoryCandidateVersionId):
            raise IntegratedContractError("candidate version identity must be typed")
        if (
            isinstance(self.candidate_version, bool)
            or not isinstance(self.candidate_version, int)
            or self.candidate_version <= 0
        ):
            raise IntegratedContractError("candidate version must be positive")
        if self.route is not CandidateRoute.DEVELOPMENT:
            raise IntegratedContractError("2D Candidate route must be DEVELOPMENT")
        if not isinstance(self.fixture_id, IntegratedFixtureId):
            raise IntegratedContractError("Candidate fixture identity must be typed")
        if not isinstance(self.retrieval_context_id, RetrievalContextV2Id):
            raise IntegratedContractError("Candidate context identity must be typed")
        if not isinstance(
            self.prior_candidate_version_id, StoryCandidateVersionId
        ):
            raise IntegratedContractError("prior Candidate identity must be typed")
        for field_name in (
            "retrieval_context_digest",
            "manifest_digest",
            "semantic_collision_digest",
            "relation_key",
        ):
            validate_sha256_digest(getattr(self, field_name), field=field_name)
        if not isinstance(self.authority_event_id, EventId):
            raise IntegratedContractError("Candidate authority event must be typed")
        if (
            isinstance(self.authority_aggregate_version, bool)
            or not isinstance(self.authority_aggregate_version, int)
            or self.authority_aggregate_version <= 0
        ):
            raise IntegratedContractError(
                "Candidate authority aggregate version must be positive"
            )
        if not isinstance(self.recorded_at, UtcTimestamp):
            raise IntegratedContractError("Candidate decision time must be typed")


_fixture_value = json.loads(INTEGRATED_FIXTURE_V2.canonical_bytes.decode("utf-8"))
_revisions = _fixture_value["revisions"]
_hypotheses = _fixture_value["event_hypotheses"]
_relation = INTEGRATED_FIXTURE_V2.relation

INTEGRATED_FIXTURE_V2_DEVELOPMENT_CANDIDATE = DevelopmentCandidateManifest(
    fixture_id=IntegratedFixtureId.parse(INTEGRATED_FIXTURE_V2.fixture_id),
    signal_id=IntegratedSignalId.parse(str(_fixture_value["signals"][1])),
    lead_id=IntegratedLeadId.parse(str(_fixture_value["leads"][1])),
    hypothesis_version_id=IntegratedHypothesisVersionId.parse(
        str(_hypotheses["new_version_id"])
    ),
    prior_hypothesis_version_id=IntegratedHypothesisVersionId.parse(
        str(_hypotheses["prior_version_id"])
    ),
    prior_candidate_version_id=StoryCandidateVersionId.parse(
        INTEGRATED_FIXTURE_V2.prior_candidate_version_id
    ),
    current_revision_id=str(_revisions[1]["source_revision_id"]),
    prior_revision_id=str(_revisions[0]["source_revision_id"]),
    canonical_process_id=str(
        _fixture_value["formal_process"]["canonical_process_id"]
    ),
    relation_key=governed_relation_key(
        fixture_binding_id=INTEGRATED_FIXTURE_V2_RETRIEVAL.relation_fixture_binding_id,
        subject=_relation.subject,
        predicate=_relation.predicate,
        object=_relation.object,
        temporal_scope=_relation.temporal_scope,
    ),
    retrieval_contract_digest=INTEGRATED_FIXTURE_V2_RETRIEVAL.contract_digest,
)


__all__ = [
    "DevelopmentCandidateAdmissionRequest",
    "DevelopmentCandidateAdmissionView",
    "DevelopmentCandidateManifest",
    "INTEGRATED_FIXTURE_V2_DEVELOPMENT_CANDIDATE",
]
