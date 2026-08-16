"""Pure contracts for the Increment 10 semantic Handoff transport.

The module models durable intent and observations. It contains no I/O adapter;
acknowledgement never implies evidence, editorial, publication or runtime authority.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from hashlib import sha256
from typing import Any

from newsroom.authority.canonical import canonical_json_bytes


class TransportContractError(ValueError):
    pass


class AttemptState(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    TIMED_OUT = "TIMED_OUT"
    AMBIGUOUS = "AMBIGUOUS"
    RECONCILED = "RECONCILED"


TERMINAL_STATES = frozenset({AttemptState.ACCEPTED, AttemptState.REJECTED, AttemptState.RECONCILED})


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    attempts_max: int
    backoff_seconds: tuple[int, ...]
    expiry_epoch_seconds: int

    def __post_init__(self) -> None:
        if self.attempts_max < 1 or self.attempts_max > 3:
            raise TransportContractError("attempt ceiling must be within 1..3")
        if len(self.backoff_seconds) != self.attempts_max - 1 or any(v < 0 or v > 30 for v in self.backoff_seconds):
            raise TransportContractError("backoff coordinates differ")
        if self.expiry_epoch_seconds <= 0:
            raise TransportContractError("expiry must be positive")


@dataclass(frozen=True, slots=True)
class Submission:
    schema_version: str
    submission_id: str
    candidate_version_id: str
    handoff_digest: str
    plan_digest: str
    destination: str
    created_epoch_seconds: int
    retry: RetryPolicy

    @property
    def semantic_idempotency_key(self) -> str:
        return _identity(self.candidate_version_id, self.handoff_digest, self.plan_digest, self.destination)

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(asdict(self))

    @property
    def digest(self) -> str:
        return "sha256:" + sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class Attempt:
    schema_version: str
    submission_id: str
    attempt_number: int
    request_id: str
    state: AttemptState
    persisted_epoch_seconds: int
    effect_started_epoch_seconds: int | None
    observed_epoch_seconds: int | None
    response_request_id: str | None
    acknowledgement_id: str | None
    reason: str | None

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def canonical_bytes(self) -> bytes:
        value = asdict(self)
        value["state"] = self.state.value
        return canonical_json_bytes(value)


class _Authority:
    pass


_AUTHORITY = _Authority()


def authority_token() -> object:
    """Return the process-private construction capability for governed callers."""
    return _AUTHORITY


def _require(token: object) -> None:
    if token is not _AUTHORITY:
        raise TransportContractError("transport authority token differs")


def _identity(*parts: str) -> str:
    if any(type(part) is not str or not part for part in parts):
        raise TransportContractError("identity components must be non-empty strings")
    return "sha256:" + sha256(canonical_json_bytes(list(parts))).hexdigest()


def create_submission(token: object, *, candidate_version_id: str, handoff_digest: str, plan_digest: str, destination: str, created_epoch_seconds: int, retry: RetryPolicy) -> Submission:
    _require(token)
    if not candidate_version_id.startswith("candidate-version:") or not handoff_digest.startswith("sha256:") or not plan_digest.startswith("sha256:"):
        raise TransportContractError("governing identities differ")
    if destination != "local://increment10/evidence-intake-fixture-v1":
        raise TransportContractError("destination is outside the frozen plan")
    semantic = _identity(candidate_version_id, handoff_digest, plan_digest, destination)
    return Submission("newsroom.increment10.submission.v1", semantic, candidate_version_id, handoff_digest, plan_digest, destination, created_epoch_seconds, retry)


def start_attempt(token: object, submission: Submission, *, attempt_number: int, request_id: str, persisted_epoch_seconds: int, effect_started_epoch_seconds: int | None = None) -> Attempt:
    _require(token)
    if attempt_number < 1 or attempt_number > submission.retry.attempts_max:
        raise TransportContractError("attempt is outside retry coordinates")
    if persisted_epoch_seconds >= submission.retry.expiry_epoch_seconds:
        raise TransportContractError("submission expired before attempt")
    if effect_started_epoch_seconds is not None and effect_started_epoch_seconds < persisted_epoch_seconds:
        raise TransportContractError("persist-before-effect violated")
    return Attempt("newsroom.increment10.attempt.v1", submission.submission_id, attempt_number, request_id, AttemptState.PENDING, persisted_epoch_seconds, effect_started_epoch_seconds, None, None, None, None)


def observe(token: object, attempt: Attempt, *, state: AttemptState, observed_epoch_seconds: int, response_request_id: str | None = None, acknowledgement_id: str | None = None, reason: str | None = None) -> Attempt:
    _require(token)
    if attempt.terminal:
        raise TransportContractError("terminal attempt is immutable")
    if observed_epoch_seconds < attempt.persisted_epoch_seconds:
        raise TransportContractError("observation precedes persisted intent")
    if response_request_id is not None and response_request_id != attempt.request_id:
        raise TransportContractError("request/response correlation differs")
    if state is AttemptState.ACCEPTED and (not acknowledgement_id or response_request_id is None):
        raise TransportContractError("accepted observation requires correlated acknowledgement")
    if state is AttemptState.RECONCILED:
        raise TransportContractError("reconciliation requires the dedicated transition")
    return replace(attempt, state=state, observed_epoch_seconds=observed_epoch_seconds, response_request_id=response_request_id, acknowledgement_id=acknowledgement_id, reason=reason)


def reconcile(token: object, attempt: Attempt, *, acknowledgement_id: str, observed_epoch_seconds: int, authoritative_request_id: str) -> Attempt:
    _require(token)
    if attempt.state not in {AttemptState.AMBIGUOUS, AttemptState.TIMED_OUT, AttemptState.PARTIAL, AttemptState.UNAVAILABLE}:
        raise TransportContractError("only uncertain attempts may reconcile")
    if authoritative_request_id != attempt.request_id or observed_epoch_seconds < (attempt.observed_epoch_seconds or attempt.persisted_epoch_seconds):
        raise TransportContractError("late acknowledgement chronology or correlation differs")
    return replace(attempt, state=AttemptState.RECONCILED, observed_epoch_seconds=observed_epoch_seconds, response_request_id=authoritative_request_id, acknowledgement_id=acknowledgement_id)


def parse_submission(raw: bytes) -> Submission:
    try:
        pairs: list[tuple[str, Any]] = json.loads(raw, object_pairs_hook=lambda values: values)
        if not isinstance(pairs, list) or any(not isinstance(item, tuple) for item in pairs):
            raise TransportContractError("submission must be an object")
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise TransportContractError("duplicate submission field")
            value[key] = item
        if set(value) != {"schema_version", "submission_id", "candidate_version_id", "handoff_digest", "plan_digest", "destination", "created_epoch_seconds", "retry"}:
            raise TransportContractError("submission fields differ")
        retry = value.pop("retry")
        if not isinstance(retry, list):
            raise TransportContractError("retry must be an object")
        retry_dict = dict(retry)
        if len(retry_dict) != len(retry) or set(retry_dict) != {"attempts_max", "backoff_seconds", "expiry_epoch_seconds"}:
            raise TransportContractError("retry fields differ")
        result = Submission(retry=RetryPolicy(retry_dict["attempts_max"], tuple(retry_dict["backoff_seconds"]), retry_dict["expiry_epoch_seconds"]), **value)
        if raw != result.canonical_bytes() or result.submission_id != result.semantic_idempotency_key:
            raise TransportContractError("submission is non-canonical or identity differs")
        return result
    except TransportContractError:
        raise
    except (TypeError, ValueError, KeyError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise TransportContractError("submission is malformed") from exc
