"""Public composition facade for deterministic Increment 1C Candidate authority."""

from ._integrated_system import (
    CandidateAdmissions,
    IntegratedCandidateAuthoritySystem,
    open_candidate_admission_authority_system,
)

__all__ = [
    "CandidateAdmissions",
    "IntegratedCandidateAuthoritySystem",
    "open_candidate_admission_authority_system",
]
