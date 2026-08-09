"""Pure contracts for evaluation-only Candidate Version handoffs.

The SQLite store is deliberately transport-agnostic: it durably records each
attempt before a caller performs external I/O and grants no publication or
evidence authority.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import json
import re
import sqlite3
from typing import Callable, ClassVar


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_HANDOFF_ID = re.compile(r"handoff:sha256:[0-9a-f]{64}")
_ATTEMPT_ID = re.compile(r"attempt:sha256:[0-9a-f]{64}")
_ACKNOWLEDGEMENT_ID = re.compile(r"acknowledgement:sha256:[0-9a-f]{64}")

EVALUATION_HANDOFF = "newsroom.increment6.evaluation-handoff.v1"
HANDOFF_ATTEMPT = "newsroom.increment6.evaluation-handoff-attempt.v1"
HANDOFF_ACKNOWLEDGEMENT = (
    "newsroom.increment6.evaluation-handoff-acknowledgement.v1"
)
HANDOFF_TRANSPORT_STATE = (
    "pending",
    "acknowledged",
    "rejected",
    "ambiguous",
    "retry",
)


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
    schema_identity: ClassVar[str] = HANDOFF_ATTEMPT
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
    schema_identity: ClassVar[str] = HANDOFF_ACKNOWLEDGEMENT
    acknowledgement_id: str
    handoff_id: str
    attempt_id: str
    candidate_version_id: str
    governing_manifest_digest: str
    sink_id: str
    outcome: AcknowledgementOutcome
    response_digest: str

    def __post_init__(self) -> None:
        _matches(
            self.acknowledgement_id,
            _ACKNOWLEDGEMENT_ID,
            "acknowledgement_id",
        )
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
        expected = _identity(
            "acknowledgement",
            {
                "handoff_id": self.handoff_id,
                "attempt_id": self.attempt_id,
                "candidate_version_id": self.candidate_version_id,
                "governing_manifest_digest": self.governing_manifest_digest,
                "sink_id": self.sink_id,
                "outcome": self.outcome.value,
                "response_digest": self.response_digest,
            },
        )
        if self.acknowledgement_id != expected:
            raise HandoffContractError("acknowledgement_id")

    @classmethod
    def create(
        cls,
        *,
        handoff_id: str,
        attempt_id: str,
        candidate_version_id: str,
        governing_manifest_digest: str,
        sink_id: str,
        outcome: AcknowledgementOutcome,
        response_digest: str,
    ) -> Acknowledgement:
        acknowledgement_id = _identity(
            "acknowledgement",
            {
                "handoff_id": handoff_id,
                "attempt_id": attempt_id,
                "candidate_version_id": candidate_version_id,
                "governing_manifest_digest": governing_manifest_digest,
                "sink_id": sink_id,
                "outcome": outcome.value,
                "response_digest": response_digest,
            },
        )
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
    schema_identity: ClassVar[str] = EVALUATION_HANDOFF
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
        (
            "candidate_version_id",
            acknowledgement.candidate_version_id,
            handoff.candidate_version_id,
        ),
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


class EvaluationHandoffStore:
    """Sole-transaction SQLite store for evaluation-only Handoffs.

    Transport callers persist an attempt through this store, commit, and only
    then send it. Every transition reloads the aggregate inside ``BEGIN
    IMMEDIATE`` so concurrent replays serialize to the same logical Handoff.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("connection must be sqlite3.Connection")
        if connection.in_transaction:
            raise HandoffContractError("connection has an active transaction")
        connection.execute("PRAGMA foreign_keys=ON")
        if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise HandoffContractError("foreign keys must be enabled")
        self._connection = connection

    def register(self, handoff: Handoff) -> Handoff:
        """Create or idempotently replay one exact logical Handoff."""
        pristine = create_handoff(
            handoff.candidate_version_id,
            handoff.governing_manifest_digest,
            handoff.sink_id,
            max_attempts=handoff.max_attempts,
        )
        if handoff != pristine:
            raise HandoffContractError("registration requires a pristine Handoff")
        self._begin()
        try:
            self._connection.execute(
                "INSERT OR IGNORE INTO evaluation_handoffs("
                "handoff_id,schema_identity,candidate_version_id,"
                "governing_manifest_digest,sink_id,max_attempts,transport_state,"
                "retry_exhausted,ambiguity_reason,evaluation_only,"
                "publication_authority,evidence_authority) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    handoff.handoff_id,
                    EVALUATION_HANDOFF,
                    handoff.candidate_version_id,
                    handoff.governing_manifest_digest,
                    handoff.sink_id,
                    handoff.max_attempts,
                    handoff.state.value,
                    int(handoff.retry_exhausted),
                    handoff.ambiguity_reason,
                    1,
                    0,
                    0,
                ),
            )
            retained = self._load(handoff.handoff_id)
            if (
                retained.candidate_version_id != handoff.candidate_version_id
                or retained.governing_manifest_digest
                != handoff.governing_manifest_digest
                or retained.sink_id != handoff.sink_id
                or retained.max_attempts != handoff.max_attempts
            ):
                raise HandoffContractError("Handoff replay conflicts with authority")
            self._connection.execute("COMMIT")
            return retained
        except Exception:
            self._rollback()
            raise

    def load(self, handoff_id: str) -> Handoff:
        _matches(handoff_id, _HANDOFF_ID, "handoff_id")
        self._begin()
        try:
            retained = self._load(handoff_id)
            self._connection.execute("COMMIT")
            return retained
        except Exception:
            self._rollback()
            raise

    def persist_attempt(self, handoff_id: str) -> Handoff:
        return self._transition(handoff_id, persist_attempt)

    def mark_attempt_sent(self, handoff_id: str, attempt_id: str) -> Handoff:
        return self._transition(
            handoff_id, lambda value: mark_attempt_sent(value, attempt_id)
        )

    def mark_attempt_ambiguous(
        self, handoff_id: str, attempt_id: str
    ) -> Handoff:
        return self._transition(
            handoff_id, lambda value: mark_attempt_ambiguous(value, attempt_id)
        )

    def request_retry(self, handoff_id: str) -> Handoff:
        return self._transition(handoff_id, request_retry)

    def correlate_acknowledgement(
        self, handoff_id: str, acknowledgement: Acknowledgement
    ) -> Handoff:
        return self._transition(
            handoff_id,
            lambda value: correlate_acknowledgement(value, acknowledgement),
        )

    def _begin(self) -> None:
        if self._connection.in_transaction:
            raise HandoffContractError("connection has an active transaction")
        self._connection.execute("BEGIN IMMEDIATE")

    def _rollback(self) -> None:
        if self._connection.in_transaction:
            self._connection.execute("ROLLBACK")

    def _transition(
        self, handoff_id: str, operation: Callable[[Handoff], Handoff]
    ) -> Handoff:
        _matches(handoff_id, _HANDOFF_ID, "handoff_id")
        self._begin()
        try:
            before = self._load(handoff_id)
            after = operation(before)
            self._write(after)
            retained = self._load(handoff_id)
            if retained != after:
                raise HandoffContractError("persisted Handoff differs from transition")
            self._connection.execute("COMMIT")
            return retained
        except Exception:
            self._rollback()
            raise

    def _load(self, handoff_id: str) -> Handoff:
        row = self._connection.execute(
            "SELECT schema_identity,candidate_version_id,"
            "governing_manifest_digest,sink_id,max_attempts,transport_state,"
            "retry_exhausted,ambiguity_reason,evaluation_only,"
            "publication_authority,evidence_authority "
            "FROM evaluation_handoffs WHERE handoff_id=?",
            (handoff_id,),
        ).fetchone()
        if row is None:
            raise HandoffContractError("unknown Handoff")
        if row[0] != EVALUATION_HANDOFF:
            raise HandoffContractError("Handoff schema identity")
        attempt_rows = self._connection.execute(
            "SELECT schema_identity,attempt_id,attempt_number,"
            "semantic_idempotency_key,persisted_before_send,sent,ambiguous "
            "FROM evaluation_handoff_attempts WHERE handoff_id=? "
            "ORDER BY attempt_number",
            (handoff_id,),
        ).fetchall()
        attempts = tuple(
            HandoffAttempt(
                attempt_id=str(item[1]),
                handoff_id=handoff_id,
                attempt_number=int(item[2]),
                semantic_idempotency_key=str(item[3]),
                persisted_before_send=bool(item[4]),
                sent=bool(item[5]),
                ambiguous=bool(item[6]),
            )
            for item in attempt_rows
            if self._require_schema(item[0], HANDOFF_ATTEMPT)
        )
        acknowledgement_rows = self._connection.execute(
            "SELECT schema_identity,acknowledgement_id,handoff_id,attempt_id,"
            "candidate_version_id,governing_manifest_digest,sink_id,outcome,"
            "response_digest FROM evaluation_handoff_acknowledgements "
            "WHERE recorded_handoff_id=? ORDER BY rowid",
            (handoff_id,),
        ).fetchall()
        acknowledgements = tuple(
            Acknowledgement(
                acknowledgement_id=str(item[1]),
                handoff_id=str(item[2]),
                attempt_id=str(item[3]),
                candidate_version_id=str(item[4]),
                governing_manifest_digest=str(item[5]),
                sink_id=str(item[6]),
                outcome=AcknowledgementOutcome(str(item[7])),
                response_digest=str(item[8]),
            )
            for item in acknowledgement_rows
            if self._require_schema(item[0], HANDOFF_ACKNOWLEDGEMENT)
        )
        return Handoff(
            handoff_id=handoff_id,
            candidate_version_id=str(row[1]),
            governing_manifest_digest=str(row[2]),
            sink_id=str(row[3]),
            max_attempts=int(row[4]),
            state=HandoffState(str(row[5])),
            attempts=attempts,
            acknowledgements=acknowledgements,
            retry_exhausted=bool(row[6]),
            ambiguity_reason=None if row[7] is None else str(row[7]),
            evaluation_only=bool(row[8]),
            publication_authority=bool(row[9]),
            evidence_authority=bool(row[10]),
        )

    @staticmethod
    def _require_schema(actual: object, expected: str) -> bool:
        if actual != expected:
            raise HandoffContractError("record schema identity")
        return True

    def _write(self, handoff: Handoff) -> None:
        for attempt in handoff.attempts:
            exists = self._connection.execute(
                "SELECT 1 FROM evaluation_handoff_attempts WHERE attempt_id=?",
                (attempt.attempt_id,),
            ).fetchone()
            if exists is None:
                self._connection.execute(
                    "INSERT INTO evaluation_handoff_attempts("
                    "attempt_id,schema_identity,handoff_id,attempt_number,"
                    "semantic_idempotency_key,persisted_before_send,sent,ambiguous) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (
                        attempt.attempt_id,
                        HANDOFF_ATTEMPT,
                        attempt.handoff_id,
                        attempt.attempt_number,
                        attempt.semantic_idempotency_key,
                        1,
                        int(attempt.sent),
                        int(attempt.ambiguous),
                    ),
                )
            self._connection.execute(
                "UPDATE evaluation_handoff_attempts SET sent=?,ambiguous=? "
                "WHERE attempt_id=?",
                (int(attempt.sent), int(attempt.ambiguous), attempt.attempt_id),
            )
        for acknowledgement in handoff.acknowledgements:
            self._connection.execute(
                "INSERT OR IGNORE INTO evaluation_handoff_acknowledgements("
                "acknowledgement_id,schema_identity,recorded_handoff_id,"
                "handoff_id,attempt_id,candidate_version_id,"
                "governing_manifest_digest,sink_id,outcome,response_digest) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    acknowledgement.acknowledgement_id,
                    HANDOFF_ACKNOWLEDGEMENT,
                    handoff.handoff_id,
                    acknowledgement.handoff_id,
                    acknowledgement.attempt_id,
                    acknowledgement.candidate_version_id,
                    acknowledgement.governing_manifest_digest,
                    acknowledgement.sink_id,
                    acknowledgement.outcome.value,
                    acknowledgement.response_digest,
                ),
            )
        self._connection.execute(
            "UPDATE evaluation_handoffs SET transport_state=?,"
            "retry_exhausted=?,ambiguity_reason=? WHERE handoff_id=?",
            (
                handoff.state.value,
                int(handoff.retry_exhausted),
                handoff.ambiguity_reason,
                handoff.handoff_id,
            ),
        )


__all__ = [
    "Acknowledgement",
    "AcknowledgementOutcome",
    "EVALUATION_HANDOFF",
    "EvaluationHandoffStore",
    "HANDOFF_ACKNOWLEDGEMENT",
    "HANDOFF_ATTEMPT",
    "HANDOFF_TRANSPORT_STATE",
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
