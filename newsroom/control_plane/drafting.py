"""Immutable retained outcomes for the private CONT drafting path."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.control_plane.writer import WriterValidatorResult

DraftOutcome = Literal["ACCEPTED", "HOLD", "REJECT"]


@dataclass(frozen=True, slots=True)
class DraftOutcomeRecord:
    outcome_id: str
    write_admission_decision_id: str
    candidate_id: str
    evidence_package_digest: str
    provider_attempt_ids: tuple[str, ...]
    outcome: DraftOutcome
    validator_results: tuple[WriterValidatorResult, ...]
    stable_reason_codes: tuple[str, ...]
    payload_digest: str | None
    recorded_at: str
    candidate_attempt_id: str

    def __post_init__(self) -> None:
        identity = {
            "candidate_attempt_id": self.candidate_attempt_id,
            "write_admission_decision_id": self.write_admission_decision_id,
            "candidate_id": self.candidate_id,
            "evidence_package_digest": self.evidence_package_digest,
            "provider_attempt_ids": self.provider_attempt_ids,
            "outcome": self.outcome,
            "stable_reason_codes": self.stable_reason_codes,
            "payload_digest": self.payload_digest,
        }
        if self.outcome_id != digest_bytes(canonical_json_bytes(identity)):
            raise ValueError("draft outcome identity does not match retained fields")
        if len(set(self.provider_attempt_ids)) != len(self.provider_attempt_ids):
            raise ValueError("draft outcome provider attempts must be unique")

    @classmethod
    def create(
        cls,
        *,
        write_admission_decision_id: str,
        candidate_id: str,
        evidence_package_digest: str,
        provider_attempt_ids: tuple[str, ...],
        outcome: DraftOutcome,
        validator_results: tuple[WriterValidatorResult, ...],
        stable_reason_codes: tuple[str, ...],
        payload_digest: str | None,
        recorded_at: str,
        candidate_attempt_id: str,
    ) -> DraftOutcomeRecord:
        identity = {
            "candidate_attempt_id": candidate_attempt_id,
            "write_admission_decision_id": write_admission_decision_id,
            "candidate_id": candidate_id,
            "evidence_package_digest": evidence_package_digest,
            "provider_attempt_ids": provider_attempt_ids,
            "outcome": outcome,
            "stable_reason_codes": stable_reason_codes,
            "payload_digest": payload_digest,
        }
        return cls(
            outcome_id=digest_bytes(canonical_json_bytes(identity)),
            write_admission_decision_id=write_admission_decision_id,
            candidate_id=candidate_id,
            evidence_package_digest=evidence_package_digest,
            provider_attempt_ids=provider_attempt_ids,
            outcome=outcome,
            validator_results=validator_results,
            stable_reason_codes=stable_reason_codes,
            payload_digest=payload_digest,
            recorded_at=recorded_at,
            candidate_attempt_id=candidate_attempt_id,
        )

    def as_record(self) -> dict[str, object]:
        return {
            "outcome_id": self.outcome_id,
            "write_admission_decision_id": self.write_admission_decision_id,
            "candidate_id": self.candidate_id,
            "evidence_package_digest": self.evidence_package_digest,
            "provider_attempt_ids": list(self.provider_attempt_ids),
            "outcome": self.outcome,
            "validator_results": [
                {
                    "validator": item.validator,
                    "result": item.result,
                    "reason_code": item.reason_code,
                }
                for item in self.validator_results
            ],
            "stable_reason_codes": list(self.stable_reason_codes),
            "payload_digest": self.payload_digest,
            "recorded_at": self.recorded_at,
            "candidate_attempt_id": self.candidate_attempt_id,
        }
