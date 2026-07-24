"""Increment 1C integrated-foundation proof contracts and deterministic services."""

from .models import (
    CandidateAdmissionDecisionId,
    CandidateAdmissionOutcome,
    CandidateAdmissionRequest,
    CandidateAdmissionView,
    CandidateRoute,
    IntegratedContractError,
    IntegratedExactIndexEntry,
    IntegratedFixtureId,
    IntegratedFixtureManifest,
    IntegratedFoundationError,
    IntegratedHypothesisVersionId,
    IntegratedLeadId,
    IntegratedRetrievalContext,
    IntegratedRetrievalContextId,
    IntegratedSignalId,
    IntegratedStateError,
    IntegratedTriageProposalId,
    IntegratedUrgency,
    StoryCandidateId,
    StoryCandidateVersionId,
)
from .policy import (
    CANDIDATE_ADMISSION_COMMAND,
    INTEGRATED_COMMAND_TYPES,
    INTEGRATED_FIXTURE_COMMAND,
    integrated_command_definitions,
    integrated_payload_contracts,
    merge_integrated_authority_registries,
)

_AUTHORITY_FACADE_NAMES = {
    "CandidateAdmissions",
    "IntegratedCandidateAuthoritySystem",
    "open_candidate_admission_authority_system",
}
_PROOF_FACADE_NAMES = {
    "IntegratedFixtureAuthority",
    "IntegratedFoundationProofController",
    "IntegratedFoundationProofResult",
    "IntegratedProjectionAuthority",
    "IntegratedProofEnvironment",
    "IntegratedProofKeys",
}


def __getattr__(name: str):
    if name in _AUTHORITY_FACADE_NAMES:
        from newsroom.authority import integrated_system as _system

        return getattr(_system, name)
    if name in _PROOF_FACADE_NAMES:
        from . import proof as _proof

        return getattr(_proof, name)
    raise AttributeError(name)


__all__ = [
    "CANDIDATE_ADMISSION_COMMAND",
    "CandidateAdmissionDecisionId",
    "CandidateAdmissionOutcome",
    "CandidateAdmissionRequest",
    "CandidateAdmissionView",
    "CandidateAdmissions",
    "CandidateRoute",
    "INTEGRATED_COMMAND_TYPES",
    "INTEGRATED_FIXTURE_COMMAND",
    "IntegratedCandidateAuthoritySystem",
    "IntegratedContractError",
    "IntegratedExactIndexEntry",
    "IntegratedFixtureAuthority",
    "IntegratedFixtureId",
    "IntegratedFixtureManifest",
    "IntegratedFoundationError",
    "IntegratedFoundationProofController",
    "IntegratedFoundationProofResult",
    "IntegratedHypothesisVersionId",
    "IntegratedLeadId",
    "IntegratedProjectionAuthority",
    "IntegratedProofEnvironment",
    "IntegratedProofKeys",
    "IntegratedRetrievalContext",
    "IntegratedRetrievalContextId",
    "IntegratedSignalId",
    "IntegratedStateError",
    "IntegratedTriageProposalId",
    "IntegratedUrgency",
    "StoryCandidateId",
    "StoryCandidateVersionId",
    "integrated_command_definitions",
    "integrated_payload_contracts",
    "merge_integrated_authority_registries",
    "open_candidate_admission_authority_system",
]
