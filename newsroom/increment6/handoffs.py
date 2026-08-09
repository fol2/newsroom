"""Pure contracts for evaluation-only Candidate Version handoffs.

This module deliberately owns no persistence or transport adapter.  It models the
records that those later integrations must durably store before external I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import json
import re


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_HANDOFF_ID = re.compile(r"handoff:sha256:[0-9a-f]{64}")
_ATTEMPT_ID = re.compile(r"attempt:sha256:[0-9a-f]{64}")


class HandoffContractError(ValueError):
    """Raised when an evaluation Handoff contract would become untruthful."""


class HandoffState(str, Enum):
    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    REJECTED = "rejected"
    AMBIGUOUS = "ambiguous"
    RETRY = "retry"


class AcknowledgementOutcome(str, Enum):
    ACKNOWLEDGED = "acknowledged"
    REJECTED = "rejected"


def _text(value: object, field: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > maximum:
        raise HandoffContractError(field)
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise HandoffContractError(field)
    return value


def _matches(value: object, pattern: re.Pattern[str], field: str) -> str:
    text = _text(value, field)
    if pattern.fullmatch(text) is None:
        raise HandoffContractError(field)
    return text


def _identity(prefix: str, value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{prefix}:sha256:{hashlib.sha256(canonical).hexdigest()}"


@dataclass(frozen=True)
class HandoffAttempt:
    attempt_id: str
    handoff_id: str
    attempt_number: int
    semantic_idempotency_key: str
    persisted_before_send: bool = True
    sent: bool = False
    ambiguous: bool = False

    def __post_init__(self) -> None:
        _matches(self.attempt_id, _ATTEMPT_ID, "attempt_id")
        _matches(self.handoff_id, _HANDOFF_ID, "handoff_id")
        if (
            isinstance(self.attempt_number, bool)
            or not isinstance(self.attempt_number, int)
            or self.attempt_number < 1
        ):
            raise HandoffContractError("attempt_number")
        if self.semantic_idempotency_key != self.handoff_id:
            raise HandoffContractError("semantic_idempotency_key")
        if self.persisted_before_send is not True:
            raise HandoffContractError("persisted_before_send")
        if self.ambiguous and not self.sent:
            raise HandoffContractError("ambiguous attempt was not sent")
        expected = _identity(
            "attempt",
            {"handoff_id": self.handoff_id, "attempt_number": self.attempt_number},
        )
        if self.attempt_id != expected:
            raise HandoffContractError("attempt_id")


@dataclass(frozen=True)
class Acknowledgement:
    acknowledgement_id: str
    handoff_id: str
    attempt_id: str
    candidate_version_id: str
    governing_manifest_digest: str
    sink_id: str
    outcome: AcknowledgementOutcome
    response_digest: str

    def __post_init__(self) -> None:
        _text(self.acknowledgement_id, "acknowledgement_id")
        _matches(self.handoff_id, _HANDOFF_ID, "handoff_id")
        _matches(self.attempt_id, _ATTEMPT_ID, "attempt_id")
        _text(self.candidate_version_id, "candidate_version_id")
        _matches(
            self.governing_manifest_digest,
            _DIGEST,
            "governing_manifest_digest",
        )
        _text(self.sink_id, "sink_id")
        if not isinstance(self.outcome, AcknowledgementOutcome):
            raise HandoffContractError("outcome")
        _matches(self.response_digest, _DIGEST, "response_digest")

    @classmethod
    def create(
        cls,
        *,
        acknowledgement_id: str,
        handoff_id: str,
        attempt_id: str,
        candidate_version_id: str,
        governing_manifest_digest: str,
        sink_id: str,
        outcome: AcknowledgementOutcome,
        response_digest: str,
    ) -> Acknowledgement:
        return cls(
            acknowledgement_id=acknowledgement_id,
            handoff_id=handoff_id,
            attempt_id=attempt_id,
            candidate_version_id=candidate_version_id,
            governing_manifest_digest=governing_manifest_digest,
            sink_id=sink_id,
            outcome=outcome,
            response_digest=response_digest,
        )


@dataclass(frozen=True)
class Handoff:
    handoff_id: str
    candidate_version_id: str
    governing_manifest_digest: str
    sink_id: str
    max_attempts: int
    state: HandoffState = HandoffState.PENDING
    attempts: tuple[HandoffAttempt, ...] = ()
    acknowledgements: tuple[Acknowledgement, ...] = ()
    retry_exhausted: bool = False
    ambiguity_reason: str | None = None
    evaluation_only: bool = True
    publication_authority: bool = False
    evidence_authority: bool = False

    def __post_init__(self) -> None:
        _matches(self.handoff_id, _HANDOFF_ID, "handoff_id")
        candidate_version_id = _text(
            self.candidate_version_id, "candidate_version_id"
        )
        manifest_digest = _matches(
            self.governing_manifest_digest,
            _DIGEST,
            "governing_manifest_digest",
        )
        sink_id = _text(self.sink_id, "sink_id")
        if not sink_id.startswith("evaluation-sink:"):
            raise HandoffContractError("sink_id must identify an evaluation sink")
        if isinstance(self.max_attempts, bool) or not isinstance(self.max_attempts, int):
            raise HandoffContractError("max_attempts")
        if self.max_attempts < 1 or self.max_attempts > 100:
            raise HandoffContractError("max_attempts")
        if not isinstance(self.state, HandoffState):
            raise HandoffContractError("state")
        if self.evaluation_only is not True:
            raise HandoffContractError("evaluation_only")
        if self.publication_authority is not False:
            raise HandoffContractError("publication_authority")
        if self.evidence_authority is not False:
            raise HandoffContractError("evidence_authority")
        expected = _identity(
            "handoff",
            {
                "candidate_version_id": candidate_version_id,
                "governing_manifest_digest": manifest_digest,
                "sink_id": sink_id,
                "authority": "evaluation-only",
            },
        )
        if self.handoff_id != expected:
            raise HandoffContractError("handoff_id")
        if any(not isinstance(item, HandoffAttempt) for item in self.attempts):
            raise HandoffContractError("attempts")
        if any(
            not isinstance(item, Acknowledgement)
            for item in self.acknowledgements
        ):
            raise HandoffContractError("acknowledgements")
        expected_numbers = tuple(range(1, len(self.attempts) + 1))
        if tuple(item.attempt_number for item in self.attempts) != expected_numbers:
            raise HandoffContractError("attempt sequence")
        if any(item.handoff_id != self.handoff_id for item in self.attempts):
            raise HandoffContractError("attempt handoff_id")
        if len(self.attempts) > self.max_attempts:
            raise HandoffContractError("attempt limit")
        if self.retry_exhausted and self.state is not HandoffState.AMBIGUOUS:
            raise HandoffContractError("retry_exhausted")
        if self.ambiguity_reason is not None:
            _text(self.ambiguity_reason, "ambiguity_reason")


def create_handoff(
    candidate_version_id: str,
    governing_manifest_digest: str,
    sink_id: str,
    *,
    max_attempts: int = 3,
) -> Handoff:
    """Create or replay one stable logical Handoff without side effects."""
    handoff_id = _identity(
        "handoff",
        {
            "candidate_version_id": candidate_version_id,
            "governing_manifest_digest": governing_manifest_digest,
            "sink_id": sink_id,
            "authority": "evaluation-only",
        },
    )
    return Handoff(
        handoff_id=handoff_id,
        candidate_version_id=candidate_version_id,
        governing_manifest_digest=governing_manifest_digest,
        sink_id=sink_id,
        max_attempts=max_attempts,
    )


def persist_attempt(handoff: Handoff) -> Handoff:
    """Return the attempt record that a repository must commit before sending."""
    if handoff.state is HandoffState.AMBIGUOUS and handoff.retry_exhausted:
        return handoff
    if handoff.state not in (HandoffState.PENDING, HandoffState.RETRY):
        raise HandoffContractError("attempt persistence requires pending or retry state")
    if handoff.attempts and handoff.state is HandoffState.PENDING:
        return handoff
    attempt_number = len(handoff.attempts) + 1
    if attempt_number > handoff.max_attempts:
        raise HandoffContractError("attempt limit")
    attempt = HandoffAttempt(
        attempt_id=_identity(
            "attempt",
            {"handoff_id": handoff.handoff_id, "attempt_number": attempt_number},
        ),
        handoff_id=handoff.handoff_id,
        attempt_number=attempt_number,
        semantic_idempotency_key=handoff.handoff_id,
    )
    return replace(
        handoff,
        state=HandoffState.PENDING,
        attempts=handoff.attempts + (attempt,),
        ambiguity_reason=None,
    )


def _attempt_index(handoff: Handoff, attempt_id: str) -> int:
    for index, attempt in enumerate(handoff.attempts):
        if attempt.attempt_id == attempt_id:
            return index
    raise HandoffContractError("unknown attempt")


def mark_attempt_sent(handoff: Handoff, attempt_id: str) -> Handoff:
    """Record sending only after the exact attempt has been persisted."""
    index = _attempt_index(handoff, attempt_id)
    attempt = handoff.attempts[index]
    if handoff.state is not HandoffState.PENDING:
        raise HandoffContractError("send requires pending state")
    if attempt.sent:
        return handoff
    attempts = list(handoff.attempts)
    attempts[index] = replace(attempt, sent=True)
    return replace(handoff, attempts=tuple(attempts))


def mark_attempt_ambiguous(handoff: Handoff, attempt_id: str) -> Handoff:
    """Record a lost, delayed or otherwise indeterminate target response."""
    index = _attempt_index(handoff, attempt_id)
    attempt = handoff.attempts[index]
    if not attempt.sent:
        raise HandoffContractError("ambiguous attempt was not sent")
    if attempt.ambiguous:
        return handoff
    if handoff.state is not HandoffState.PENDING:
        raise HandoffContractError("ambiguous transition requires pending state")
    attempts = list(handoff.attempts)
    attempts[index] = replace(attempt, ambiguous=True)
    return replace(
        handoff,
        state=HandoffState.AMBIGUOUS,
        attempts=tuple(attempts),
        ambiguity_reason="target_outcome_unknown",
    )


def request_retry(handoff: Handoff) -> Handoff:
    """Request a bounded retry without allocating a second logical Handoff."""
    if handoff.state in (HandoffState.ACKNOWLEDGED, HandoffState.REJECTED):
        raise HandoffContractError("terminal handoff cannot retry")
    if handoff.state is HandoffState.RETRY:
        return handoff
    if handoff.state is not HandoffState.AMBIGUOUS:
        raise HandoffContractError("retry requires ambiguous state")
    if len(handoff.attempts) >= handoff.max_attempts:
        return replace(handoff, retry_exhausted=True)
    return replace(handoff, state=HandoffState.RETRY, ambiguity_reason=None)


def _ack_mismatch(handoff: Handoff, acknowledgement: Acknowledgement) -> str | None:
    comparisons = (
        ("handoff_id", acknowledgement.handoff_id, handoff.handoff_id),
        ("candidate_version_id", acknowledgement.candidate_version_id, handoff.candidate_version_id),
        (
            "governing_manifest_digest",
            acknowledgement.governing_manifest_digest,
            handoff.governing_manifest_digest,
        ),
        ("sink_id", acknowledgement.sink_id, handoff.sink_id),
    )
    for field, actual, expected in comparisons:
        if actual != expected:
            return f"acknowledgement_{field}_mismatch"
    matching_attempt = next(
        (item for item in handoff.attempts if item.attempt_id == acknowledgement.attempt_id),
        None,
    )
    if matching_attempt is None or not matching_attempt.sent:
        return "acknowledgement_attempt_id_mismatch"
    return None


def correlate_acknowledgement(
    handoff: Handoff, acknowledgement: Acknowledgement
) -> Handoff:
    """Correlate an untrusted response to its exact persisted and sent attempt."""
    existing = next(
        (
            item
            for item in handoff.acknowledgements
            if item.acknowledgement_id == acknowledgement.acknowledgement_id
        ),
        None,
    )
    if existing is not None:
        if existing != acknowledgement:
            raise HandoffContractError("acknowledgement identity conflict")
        return handoff

    acknowledgements = handoff.acknowledgements + (acknowledgement,)
    mismatch = _ack_mismatch(handoff, acknowledgement)
    if mismatch is not None:
        return replace(
            handoff,
            state=HandoffState.AMBIGUOUS,
            acknowledgements=acknowledgements,
            retry_exhausted=False,
            ambiguity_reason=mismatch,
        )

    correlated_outcomes = {
        item.outcome
        for item in handoff.acknowledgements
        if _ack_mismatch(handoff, item) is None
    }
    if correlated_outcomes and acknowledgement.outcome not in correlated_outcomes:
        return replace(
            handoff,
            state=HandoffState.AMBIGUOUS,
            acknowledgements=acknowledgements,
            retry_exhausted=False,
            ambiguity_reason="conflicting_acknowledgements",
        )
    state = (
        HandoffState.ACKNOWLEDGED
        if acknowledgement.outcome is AcknowledgementOutcome.ACKNOWLEDGED
        else HandoffState.REJECTED
    )
    return replace(
        handoff,
        state=state,
        acknowledgements=acknowledgements,
        retry_exhausted=False,
        ambiguity_reason=None,
    )


__all__ = [
    "Acknowledgement",
    "AcknowledgementOutcome",
    "Handoff",
    "HandoffAttempt",
    "HandoffContractError",
    "HandoffState",
    "correlate_acknowledgement",
    "create_handoff",
    "mark_attempt_ambiguous",
    "mark_attempt_sent",
    "persist_attempt",
    "request_retry",
]
