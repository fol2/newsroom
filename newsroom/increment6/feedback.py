"""Pure evaluation-feedback and mandatory reconciliation contracts.

The records in this module are deliberately evaluation-only.  They perform no
persistence, Evidence Intake, Candidate mutation, provider, or publication
effect; the following v25 authority atom owns persistence and effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import re
from typing import ClassVar, Self
import uuid

from newsroom.authority.canonical import (
    MAX_SAFE_INTEGER,
    canonical_json_bytes,
    digest_bytes,
)
from newsroom.increment6.candidates import StoryCandidateVersion
from newsroom.increment6.handoffs import (
    Acknowledgement,
    AcknowledgementOutcome,
    Handoff,
    HandoffAttempt,
    HandoffState,
)
from newsroom.increment6.work_items import SupplementalDiscoveryReentry


EVALUATION_FEEDBACK = "newsroom.increment6.evaluation-feedback.v1"
RECONCILIATION_OBLIGATION = "newsroom.increment6.reconciliation-obligation.v1"
RECONCILIATION_DISPOSITION = "newsroom.increment6.reconciliation-disposition.v1"
MAX_FEEDBACK_CANONICAL_BYTES = 1_048_576

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_FEEDBACK_ID = re.compile(r"feedback:sha256:[0-9a-f]{64}")
_OBLIGATION_ID = re.compile(r"obligation:sha256:[0-9a-f]{64}")
_DISPOSITION_ID = re.compile(r"disposition:sha256:[0-9a-f]{64}")


class FeedbackContractError(ValueError):
    """Raised when feedback or reconciliation would become untruthful."""


class EvaluationFeedbackOutcome(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"


class EvaluationFeedbackReason(str, Enum):
    INTAKE_ACCEPTED = "intake_accepted"
    DUPLICATE_OR_MERGED_CANDIDATE = "duplicate_or_merged_candidate"
    INSUFFICIENT_PUBLIC_EVIDENCE = "insufficient_public_evidence"
    OUT_OF_SCOPE = "out_of_scope"
    RIGHTS_BLOCK = "rights_block"
    STALE_CANDIDATE = "stale_candidate"
    CANDIDATE_CLOSED = "candidate_closed"
    SUPPLEMENTAL_DISCOVERY_REQUESTED = "supplemental_discovery_requested"


class FeedbackCorrelationOutcome(str, Enum):
    READY = "ready"
    DELAYED_READY = "delayed_ready"
    EXACT_REPLAY = "exact_replay"
    PENDING_ACKNOWLEDGEMENT = "pending_acknowledgement"
    AMBIGUOUS_ACKNOWLEDGEMENT = "ambiguous_acknowledgement"
    HANDOFF_REJECTED = "handoff_rejected"
    UNCORRELATED = "uncorrelated"
    BINDING_CONFLICT = "binding_conflict"


class ReconciliationObligationKind(str, Enum):
    RECORD_INTAKE_ACCEPTANCE = "record_intake_acceptance"
    RECORD_DUPLICATE_OR_MERGE = "record_duplicate_or_merge"
    REVIEW_INSUFFICIENT_PUBLIC_EVIDENCE = "review_insufficient_public_evidence"
    RECORD_OUT_OF_SCOPE = "record_out_of_scope"
    RECORD_RIGHTS_BLOCK = "record_rights_block"
    RECORD_STALE_CANDIDATE = "record_stale_candidate"
    RECORD_CANDIDATE_CLOSED = "record_candidate_closed"
    GOVERN_SUPPLEMENTAL_DISCOVERY = "govern_supplemental_discovery"


class ReconciliationDispositionOutcome(str, Enum):
    FULFILLED = "fulfilled"
    BLOCKED = "blocked"
    UNRESOLVED = "unresolved"


class ReconciliationDispositionReason(str, Enum):
    FEEDBACK_RECORDED = "feedback_recorded"
    SUPPLEMENTAL_DISCOVERY_REENTERED = "supplemental_discovery_reentered"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    POLICY_BLOCKED = "policy_blocked"
    AWAITING_RECONCILIATION = "awaiting_reconciliation"
    AMBIGUOUS_RECONCILIATION = "ambiguous_reconciliation"


_FEEDBACK_REASON_MATRIX = {
    EvaluationFeedbackOutcome.ACCEPTED: {
        EvaluationFeedbackReason.INTAKE_ACCEPTED,
    },
    EvaluationFeedbackOutcome.REJECTED: {
        EvaluationFeedbackReason.DUPLICATE_OR_MERGED_CANDIDATE,
        EvaluationFeedbackReason.OUT_OF_SCOPE,
        EvaluationFeedbackReason.RIGHTS_BLOCK,
        EvaluationFeedbackReason.STALE_CANDIDATE,
        EvaluationFeedbackReason.CANDIDATE_CLOSED,
    },
    EvaluationFeedbackOutcome.INCONCLUSIVE: {
        EvaluationFeedbackReason.INSUFFICIENT_PUBLIC_EVIDENCE,
        EvaluationFeedbackReason.SUPPLEMENTAL_DISCOVERY_REQUESTED,
    },
}

_OBLIGATION_KIND = {
    EvaluationFeedbackReason.INTAKE_ACCEPTED: ReconciliationObligationKind.RECORD_INTAKE_ACCEPTANCE,
    EvaluationFeedbackReason.DUPLICATE_OR_MERGED_CANDIDATE: ReconciliationObligationKind.RECORD_DUPLICATE_OR_MERGE,
    EvaluationFeedbackReason.INSUFFICIENT_PUBLIC_EVIDENCE: ReconciliationObligationKind.REVIEW_INSUFFICIENT_PUBLIC_EVIDENCE,
    EvaluationFeedbackReason.OUT_OF_SCOPE: ReconciliationObligationKind.RECORD_OUT_OF_SCOPE,
    EvaluationFeedbackReason.RIGHTS_BLOCK: ReconciliationObligationKind.RECORD_RIGHTS_BLOCK,
    EvaluationFeedbackReason.STALE_CANDIDATE: ReconciliationObligationKind.RECORD_STALE_CANDIDATE,
    EvaluationFeedbackReason.CANDIDATE_CLOSED: ReconciliationObligationKind.RECORD_CANDIDATE_CLOSED,
    EvaluationFeedbackReason.SUPPLEMENTAL_DISCOVERY_REQUESTED: ReconciliationObligationKind.GOVERN_SUPPLEMENTAL_DISCOVERY,
}

_DISPOSITION_REASON_MATRIX = {
    ReconciliationDispositionOutcome.FULFILLED: {
        ReconciliationDispositionReason.FEEDBACK_RECORDED,
        ReconciliationDispositionReason.SUPPLEMENTAL_DISCOVERY_REENTERED,
    },
    ReconciliationDispositionOutcome.BLOCKED: {
        ReconciliationDispositionReason.DEPENDENCY_UNAVAILABLE,
        ReconciliationDispositionReason.POLICY_BLOCKED,
    },
    ReconciliationDispositionOutcome.UNRESOLVED: {
        ReconciliationDispositionReason.AWAITING_RECONCILIATION,
        ReconciliationDispositionReason.AMBIGUOUS_RECONCILIATION,
    },
}


def _total(message: str):
    def decorate(operation):
        def wrapped(*args, **kwargs):
            try:
                return operation(*args, **kwargs)
            except FeedbackContractError:
                raise
            except Exception as exc:
                raise FeedbackContractError(message) from exc

        return wrapped

    return decorate


def _require(condition: object, message: str) -> None:
    if condition is not True:
        raise FeedbackContractError(message)


def _text(value: object, field: str, *, maximum: int = 512) -> str:
    if type(value) is not str or not value:
        raise FeedbackContractError(f"{field} must be exact non-empty text")
    try:
        encoded = value.encode("utf-8")
    except UnicodeError as exc:
        raise FeedbackContractError(f"{field} must be valid UTF-8 text") from exc
    if len(encoded) > maximum or any(
        ord(character) < 32 or ord(character) == 127 for character in value
    ):
        raise FeedbackContractError(f"{field} exceeds canonical text bounds")
    return value


def _digest(value: object, field: str) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise FeedbackContractError(f"{field} must be a canonical SHA-256 digest")
    return value


def _uuid(value: object, field: str) -> str:
    if type(value) is not str:
        raise FeedbackContractError(f"{field} must be a canonical UUIDv4")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise FeedbackContractError(f"{field} must be a canonical UUIDv4") from exc
    if str(parsed) != value or parsed.version != 4:
        raise FeedbackContractError(f"{field} must be a canonical UUIDv4")
    return value


def _positive(value: object, field: str) -> int:
    if type(value) is not int or not 1 <= value <= MAX_SAFE_INTEGER:
        raise FeedbackContractError(f"{field} must be an exact positive integer")
    return value


def _identity(prefix: str, value: object) -> str:
    try:
        return f"{prefix}:sha256:{digest_bytes(canonical_json_bytes(value)).split(':', 1)[1]}"
    except Exception as exc:
        raise FeedbackContractError(f"{prefix} identity cannot be derived") from exc


def _canonical(value: object, field: str) -> bytes:
    try:
        raw = canonical_json_bytes(value)
    except Exception as exc:
        raise FeedbackContractError(f"{field} cannot be canonicalised") from exc
    if not raw or len(raw) > MAX_FEEDBACK_CANONICAL_BYTES:
        raise FeedbackContractError(f"{field} exceeds the canonical byte bound")
    return raw


def _exact(value: object, fields: set[str], field: str) -> dict[str, object]:
    if type(value) is not dict:
        raise FeedbackContractError(f"{field} fields are not exact")
    try:
        if set(value) != fields:
            raise FeedbackContractError(f"{field} fields are not exact")
    except FeedbackContractError:
        raise
    except Exception as exc:
        raise FeedbackContractError(f"{field} fields are not exact") from exc
    return value


def _decode(raw: bytes, field: str) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_FEEDBACK_CANONICAL_BYTES:
        raise FeedbackContractError(f"{field} requires bounded immutable bytes")

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise FeedbackContractError(f"{field} contains a duplicate key")
            result[key] = value
        return result

    def integer(text: str) -> int:
        if len(text.lstrip("-")) > 16:
            raise FeedbackContractError(f"{field} integer exceeds bounds")
        value = int(text)
        if not -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
            raise FeedbackContractError(f"{field} integer exceeds bounds")
        return value

    def unsupported(_: str):
        raise FeedbackContractError(f"{field} contains an unsupported number")

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique,
            parse_int=integer,
            parse_float=unsupported,
            parse_constant=unsupported,
        )
    except FeedbackContractError:
        raise
    except Exception as exc:
        raise FeedbackContractError(f"{field} is not valid UTF-8 JSON") from exc
    pending: list[tuple[object, int]] = [(value, 1)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if depth > 24 or nodes > 32768:
            raise FeedbackContractError(f"{field} exceeds structural bounds")
        if type(item) in (dict, list):
            children = item.values() if type(item) is dict else item
            pending.extend((child, depth + 1) for child in children)
        elif type(item) not in (str, int, bool, type(None)):
            raise FeedbackContractError(f"{field} contains an unsupported value")
    if type(value) is not dict or _canonical(value, field) != raw:
        raise FeedbackContractError(f"{field} is not canonical")
    return value


def _document(schema: str, name: str, value: dict[str, object]) -> bytes:
    return _canonical({name: value, "schema_version": schema}, name)


def _decode_document(
    raw: bytes, schema: str, name: str, fields: set[str]
) -> dict[str, object]:
    root = _exact(_decode(raw, name), {name, "schema_version"}, name)
    if root["schema_version"] != schema:
        raise FeedbackContractError(f"{name} schema identity differs")
    return _exact(root[name], fields, name)


def _enum(kind, value: object, field: str):
    if type(value) is not str:
        raise FeedbackContractError(f"{field} is not an exact enum value")
    try:
        return kind(value)
    except ValueError as exc:
        raise FeedbackContractError(f"{field} is not an exact enum value") from exc


@dataclass(frozen=True, slots=True)
class EvaluationFeedback:
    schema_identity: ClassVar[str] = EVALUATION_FEEDBACK
    feedback_id: str
    source_feedback_id: str
    handoff_id: str
    handoff_attempt_id: str
    handoff_attempt_number: int
    acknowledgement_id: str
    acknowledgement_response_digest: str
    candidate_id: str
    candidate_version_id: str
    candidate_version_digest: str
    governing_manifest_digest: str
    sink_id: str
    outcome: EvaluationFeedbackOutcome
    reason: EvaluationFeedbackReason
    detail_digest: str
    duplicate_or_merged_candidate_id: str | None
    request_id: str
    actor_identity_digest: str
    idempotency_key: str
    expected_feedback_digest: None = None
    evaluation_only: bool = True
    publication_authority: bool = False
    evidence_authority: bool = False
    candidate_authority: bool = False

    @_total("invalid Evaluation Feedback")
    def __post_init__(self) -> None:
        _require(type(self) is EvaluationFeedback, "Evaluation Feedback must be exact")
        if (
            type(self.feedback_id) is not str
            or _FEEDBACK_ID.fullmatch(self.feedback_id) is None
        ):
            raise FeedbackContractError("feedback_id must be canonical")
        _text(self.source_feedback_id, "source_feedback_id")
        _text(self.handoff_id, "handoff_id")
        _text(self.handoff_attempt_id, "handoff_attempt_id")
        _positive(self.handoff_attempt_number, "handoff_attempt_number")
        _text(self.acknowledgement_id, "acknowledgement_id")
        _digest(
            self.acknowledgement_response_digest,
            "acknowledgement_response_digest",
        )
        for name in ("candidate_id", "candidate_version_id", "request_id"):
            _uuid(getattr(self, name), name)
        for name in (
            "candidate_version_digest",
            "governing_manifest_digest",
            "detail_digest",
            "actor_identity_digest",
        ):
            _digest(getattr(self, name), name)
        _text(self.sink_id, "sink_id")
        if not self.sink_id.startswith("evaluation-sink:"):
            raise FeedbackContractError("sink_id must identify an evaluation sink")
        _text(self.idempotency_key, "idempotency_key")
        if (
            type(self.outcome) is not EvaluationFeedbackOutcome
            or type(self.reason) is not EvaluationFeedbackReason
        ):
            raise FeedbackContractError("feedback outcome and reason must be exact")
        if self.reason not in _FEEDBACK_REASON_MATRIX[self.outcome]:
            raise FeedbackContractError("feedback outcome and reason differ")
        duplicate = (
            self.reason is EvaluationFeedbackReason.DUPLICATE_OR_MERGED_CANDIDATE
        )
        if duplicate != (self.duplicate_or_merged_candidate_id is not None):
            raise FeedbackContractError("duplicate or merged Candidate binding differs")
        if self.duplicate_or_merged_candidate_id is not None:
            _uuid(
                self.duplicate_or_merged_candidate_id,
                "duplicate_or_merged_candidate_id",
            )
            if self.duplicate_or_merged_candidate_id == self.candidate_id:
                raise FeedbackContractError("duplicate or merged Candidate is self")
        if self.expected_feedback_digest is not None:
            raise FeedbackContractError("new feedback requires expected absence CAS")
        if (
            self.evaluation_only is not True
            or self.publication_authority is not False
            or self.evidence_authority is not False
            or self.candidate_authority is not False
        ):
            raise FeedbackContractError("feedback authority boundary differs")
        expected = _identity(
            "feedback",
            {
                "acknowledgement_id": self.acknowledgement_id,
                "candidate_version_id": self.candidate_version_id,
                "handoff_attempt_id": self.handoff_attempt_id,
                "handoff_id": self.handoff_id,
                "source_feedback_id": self.source_feedback_id,
            },
        )
        if self.feedback_id != expected:
            raise FeedbackContractError("feedback_id differs")
        _ = self.canonical_bytes

    @property
    def canonical_value(self) -> dict[str, object]:
        value = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "schema_identity"
        }
        value["outcome"] = self.outcome.value
        value["reason"] = self.reason.value
        return value

    @property
    def canonical_bytes(self) -> bytes:
        return _document(EVALUATION_FEEDBACK, "feedback", self.canonical_value)

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        fields = set(cls.__dataclass_fields__) - {"schema_identity"}
        item = _decode_document(raw, EVALUATION_FEEDBACK, "feedback", fields)
        copied = dict(item)
        copied["outcome"] = _enum(EvaluationFeedbackOutcome, item["outcome"], "outcome")
        copied["reason"] = _enum(EvaluationFeedbackReason, item["reason"], "reason")
        try:
            value = cls(**copied)  # type: ignore[arg-type]
        except FeedbackContractError:
            raise
        except Exception as exc:
            raise FeedbackContractError("Evaluation Feedback replay failed") from exc
        if value.canonical_bytes != raw:
            raise FeedbackContractError("Evaluation Feedback replay differs")
        return value


def _feedback_binding_matches(
    handoff: Handoff,
    candidate_version: StoryCandidateVersion,
    feedback: EvaluationFeedback,
) -> bool:
    return (
        feedback.handoff_id == handoff.handoff_id
        and feedback.candidate_id == candidate_version.candidate_id
        and feedback.candidate_version_id == candidate_version.version_id
        and feedback.candidate_version_digest == candidate_version.canonical_digest
        and feedback.governing_manifest_digest
        == candidate_version.governing_manifest.canonical_digest
        == handoff.governing_manifest_digest
        and feedback.sink_id == handoff.sink_id
        and handoff.candidate_version_id == candidate_version.version_id
    )


@_total("feedback correlation failed")
def correlate_evaluation_feedback(
    handoff: Handoff,
    candidate_version: StoryCandidateVersion,
    feedback: EvaluationFeedback,
    retained: tuple[EvaluationFeedback, ...],
) -> FeedbackCorrelationOutcome:
    """Classify one untrusted response without performing a state transition."""
    if (
        type(handoff) is not Handoff
        or type(candidate_version) is not StoryCandidateVersion
        or type(feedback) is not EvaluationFeedback
        or type(retained) is not tuple
        or any(type(item) is not EvaluationFeedback for item in retained)
    ):
        raise FeedbackContractError("feedback correlation inputs must be exact")
    _ = EvaluationFeedback.from_canonical_bytes(feedback.canonical_bytes)
    seen_ids: set[str] = set()
    for item in retained:
        if item.feedback_id in seen_ids:
            raise FeedbackContractError("retained feedback identities duplicate")
        seen_ids.add(item.feedback_id)
        if item.feedback_id == feedback.feedback_id:
            return (
                FeedbackCorrelationOutcome.EXACT_REPLAY
                if item.canonical_bytes == feedback.canonical_bytes
                else FeedbackCorrelationOutcome.BINDING_CONFLICT
            )
        if (
            item.handoff_id == feedback.handoff_id
            or item.acknowledgement_id == feedback.acknowledgement_id
            or item.request_id == feedback.request_id
            or (
                item.actor_identity_digest,
                item.idempotency_key,
            )
            == (feedback.actor_identity_digest, feedback.idempotency_key)
        ):
            return FeedbackCorrelationOutcome.BINDING_CONFLICT
    if not _feedback_binding_matches(handoff, candidate_version, feedback):
        return FeedbackCorrelationOutcome.UNCORRELATED
    attempt = next(
        (
            item
            for item in handoff.attempts
            if item.attempt_id == feedback.handoff_attempt_id
        ),
        None,
    )
    if (
        attempt is None
        or not attempt.sent
        or attempt.attempt_number != feedback.handoff_attempt_number
    ):
        return FeedbackCorrelationOutcome.UNCORRELATED
    acknowledgement = next(
        (
            item
            for item in handoff.acknowledgements
            if item.acknowledgement_id == feedback.acknowledgement_id
        ),
        None,
    )
    if acknowledgement is None:
        if handoff.state is HandoffState.AMBIGUOUS:
            return FeedbackCorrelationOutcome.AMBIGUOUS_ACKNOWLEDGEMENT
        if handoff.state is HandoffState.REJECTED:
            return FeedbackCorrelationOutcome.HANDOFF_REJECTED
        return FeedbackCorrelationOutcome.PENDING_ACKNOWLEDGEMENT
    exact_ack = (
        acknowledgement.handoff_id == feedback.handoff_id
        and acknowledgement.attempt_id == feedback.handoff_attempt_id
        and acknowledgement.candidate_version_id == feedback.candidate_version_id
        and acknowledgement.governing_manifest_digest
        == feedback.governing_manifest_digest
        and acknowledgement.sink_id == feedback.sink_id
        and acknowledgement.response_digest == feedback.acknowledgement_response_digest
    )
    if not exact_ack:
        return FeedbackCorrelationOutcome.UNCORRELATED
    if (
        handoff.state is HandoffState.AMBIGUOUS
        or len({item.outcome for item in handoff.acknowledgements}) > 1
    ):
        return FeedbackCorrelationOutcome.AMBIGUOUS_ACKNOWLEDGEMENT
    if (
        acknowledgement.outcome is AcknowledgementOutcome.REJECTED
        or handoff.state is HandoffState.REJECTED
    ):
        return FeedbackCorrelationOutcome.HANDOFF_REJECTED
    if handoff.state is not HandoffState.ACKNOWLEDGED:
        return FeedbackCorrelationOutcome.PENDING_ACKNOWLEDGEMENT
    return (
        FeedbackCorrelationOutcome.DELAYED_READY
        if attempt is not handoff.attempts[-1]
        else FeedbackCorrelationOutcome.READY
    )


@_total("Evaluation Feedback construction failed")
def create_evaluation_feedback(
    *,
    handoff: Handoff,
    attempt: HandoffAttempt,
    acknowledgement: Acknowledgement,
    candidate_version: StoryCandidateVersion,
    source_feedback_id: str,
    outcome: EvaluationFeedbackOutcome,
    reason: EvaluationFeedbackReason,
    detail_digest: str,
    request_id: str,
    actor_identity_digest: str,
    idempotency_key: str,
    duplicate_or_merged_candidate_id: str | None = None,
) -> EvaluationFeedback:
    """Build feedback only from one exact acknowledged evaluation Handoff."""
    if (
        type(handoff) is not Handoff
        or type(attempt) is not HandoffAttempt
        or type(acknowledgement) is not Acknowledgement
        or type(candidate_version) is not StoryCandidateVersion
    ):
        raise FeedbackContractError("feedback producer records must be exact")
    feedback_id = _identity(
        "feedback",
        {
            "acknowledgement_id": acknowledgement.acknowledgement_id,
            "candidate_version_id": candidate_version.version_id,
            "handoff_attempt_id": attempt.attempt_id,
            "handoff_id": handoff.handoff_id,
            "source_feedback_id": source_feedback_id,
        },
    )
    feedback = EvaluationFeedback(
        feedback_id=feedback_id,
        source_feedback_id=source_feedback_id,
        handoff_id=handoff.handoff_id,
        handoff_attempt_id=attempt.attempt_id,
        handoff_attempt_number=attempt.attempt_number,
        acknowledgement_id=acknowledgement.acknowledgement_id,
        acknowledgement_response_digest=acknowledgement.response_digest,
        candidate_id=candidate_version.candidate_id,
        candidate_version_id=candidate_version.version_id,
        candidate_version_digest=candidate_version.canonical_digest,
        governing_manifest_digest=candidate_version.governing_manifest.canonical_digest,
        sink_id=handoff.sink_id,
        outcome=outcome,
        reason=reason,
        detail_digest=detail_digest,
        duplicate_or_merged_candidate_id=duplicate_or_merged_candidate_id,
        request_id=request_id,
        actor_identity_digest=actor_identity_digest,
        idempotency_key=idempotency_key,
    )
    correlation = correlate_evaluation_feedback(
        handoff, candidate_version, feedback, ()
    )
    if correlation not in {
        FeedbackCorrelationOutcome.READY,
        FeedbackCorrelationOutcome.DELAYED_READY,
    }:
        raise FeedbackContractError(
            f"feedback requires exact acknowledged Handoff: {correlation.value}"
        )
    return feedback


@dataclass(frozen=True, slots=True)
class ReconciliationObligation:
    schema_identity: ClassVar[str] = RECONCILIATION_OBLIGATION
    obligation_id: str
    feedback_id: str
    feedback_digest: str
    handoff_id: str
    candidate_id: str
    candidate_version_id: str
    candidate_version_digest: str
    kind: ReconciliationObligationKind
    request_id: str
    actor_identity_digest: str
    idempotency_key: str
    expected_disposition_ordinal: int = 0
    mandatory: bool = True
    visible_until_fulfilled: bool = True
    evaluation_only: bool = True
    publication_authority: bool = False
    evidence_authority: bool = False
    candidate_authority: bool = False

    @_total("invalid Reconciliation Obligation")
    def __post_init__(self) -> None:
        _require(
            type(self) is ReconciliationObligation,
            "Reconciliation Obligation must be exact",
        )
        if (
            type(self.obligation_id) is not str
            or _OBLIGATION_ID.fullmatch(self.obligation_id) is None
        ):
            raise FeedbackContractError("obligation_id must be canonical")
        if (
            type(self.feedback_id) is not str
            or _FEEDBACK_ID.fullmatch(self.feedback_id) is None
        ):
            raise FeedbackContractError("feedback_id must be canonical")
        _digest(self.feedback_digest, "feedback_digest")
        _text(self.handoff_id, "handoff_id")
        for name in ("candidate_id", "candidate_version_id", "request_id"):
            _uuid(getattr(self, name), name)
        _digest(self.candidate_version_digest, "candidate_version_digest")
        if type(self.kind) is not ReconciliationObligationKind:
            raise FeedbackContractError("obligation kind must be exact")
        _digest(self.actor_identity_digest, "actor_identity_digest")
        _text(self.idempotency_key, "idempotency_key")
        if type(self.expected_disposition_ordinal) is not int or (
            self.expected_disposition_ordinal != 0
        ):
            raise FeedbackContractError("new obligation requires zero disposition CAS")
        if (
            self.mandatory is not True
            or self.visible_until_fulfilled is not True
            or self.evaluation_only is not True
            or self.publication_authority is not False
            or self.evidence_authority is not False
            or self.candidate_authority is not False
        ):
            raise FeedbackContractError("obligation authority boundary differs")
        expected = _identity(
            "obligation",
            {
                "feedback_digest": self.feedback_digest,
                "feedback_id": self.feedback_id,
                "kind": self.kind.value,
            },
        )
        if self.obligation_id != expected:
            raise FeedbackContractError("obligation_id differs")
        _ = self.canonical_bytes

    @property
    def canonical_value(self) -> dict[str, object]:
        value = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "schema_identity"
        }
        value["kind"] = self.kind.value
        return value

    @property
    def canonical_bytes(self) -> bytes:
        return _document(RECONCILIATION_OBLIGATION, "obligation", self.canonical_value)

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        fields = set(cls.__dataclass_fields__) - {"schema_identity"}
        item = _decode_document(raw, RECONCILIATION_OBLIGATION, "obligation", fields)
        copied = dict(item)
        copied["kind"] = _enum(ReconciliationObligationKind, item["kind"], "kind")
        try:
            value = cls(**copied)  # type: ignore[arg-type]
        except FeedbackContractError:
            raise
        except Exception as exc:
            raise FeedbackContractError(
                "Reconciliation Obligation replay failed"
            ) from exc
        if value.canonical_bytes != raw:
            raise FeedbackContractError("Reconciliation Obligation replay differs")
        return value


@_total("Reconciliation Obligation construction failed")
def create_reconciliation_obligation(
    feedback: EvaluationFeedback,
    *,
    request_id: str,
    actor_identity_digest: str,
    idempotency_key: str,
) -> ReconciliationObligation:
    """Create the one mandatory obligation derived from exact feedback."""
    if type(feedback) is not EvaluationFeedback:
        raise FeedbackContractError("feedback must be exact")
    replay = EvaluationFeedback.from_canonical_bytes(feedback.canonical_bytes)
    kind = _OBLIGATION_KIND[replay.reason]
    obligation_id = _identity(
        "obligation",
        {
            "feedback_digest": replay.canonical_digest,
            "feedback_id": replay.feedback_id,
            "kind": kind.value,
        },
    )
    return ReconciliationObligation(
        obligation_id=obligation_id,
        feedback_id=replay.feedback_id,
        feedback_digest=replay.canonical_digest,
        handoff_id=replay.handoff_id,
        candidate_id=replay.candidate_id,
        candidate_version_id=replay.candidate_version_id,
        candidate_version_digest=replay.candidate_version_digest,
        kind=kind,
        request_id=request_id,
        actor_identity_digest=actor_identity_digest,
        idempotency_key=idempotency_key,
    )


def _supplemental_digest(value: SupplementalDiscoveryReentry) -> str:
    try:
        return digest_bytes(canonical_json_bytes(value.canonical_value()))
    except Exception as exc:
        raise FeedbackContractError("supplemental re-entry is invalid") from exc


@dataclass(frozen=True, slots=True)
class ReconciliationDisposition:
    schema_identity: ClassVar[str] = RECONCILIATION_DISPOSITION
    disposition_id: str
    obligation_id: str
    obligation_digest: str
    obligation_kind: ReconciliationObligationKind
    feedback_id: str
    feedback_digest: str
    candidate_id: str
    candidate_version_id: str
    candidate_version_digest: str
    ordinal: int
    previous_disposition_id: str | None
    previous_disposition_digest: str | None
    outcome: ReconciliationDispositionOutcome
    reason: ReconciliationDispositionReason
    resolution_digest: str
    supplemental_reentry: SupplementalDiscoveryReentry | None
    request_id: str
    actor_identity_digest: str
    idempotency_key: str
    expected_current_disposition_id: str | None
    expected_current_disposition_digest: str | None
    expected_current_ordinal: int
    immutable: bool = True
    evaluation_only: bool = True
    publication_authority: bool = False
    evidence_authority: bool = False
    candidate_authority: bool = False

    @_total("invalid Reconciliation Disposition")
    def __post_init__(self) -> None:
        _require(
            type(self) is ReconciliationDisposition,
            "Reconciliation Disposition must be exact",
        )
        if (
            type(self.disposition_id) is not str
            or _DISPOSITION_ID.fullmatch(self.disposition_id) is None
        ):
            raise FeedbackContractError("disposition_id must be canonical")
        if (
            type(self.obligation_id) is not str
            or _OBLIGATION_ID.fullmatch(self.obligation_id) is None
        ):
            raise FeedbackContractError("obligation_id must be canonical")
        _digest(self.obligation_digest, "obligation_digest")
        if type(self.obligation_kind) is not ReconciliationObligationKind:
            raise FeedbackContractError("obligation kind must be exact")
        if (
            type(self.feedback_id) is not str
            or _FEEDBACK_ID.fullmatch(self.feedback_id) is None
        ):
            raise FeedbackContractError("feedback_id must be canonical")
        for name in (
            "feedback_digest",
            "candidate_version_digest",
            "resolution_digest",
            "actor_identity_digest",
        ):
            _digest(getattr(self, name), name)
        for name in (
            "candidate_id",
            "candidate_version_id",
            "request_id",
        ):
            _uuid(getattr(self, name), name)
        _positive(self.ordinal, "ordinal")
        previous = self.previous_disposition_id is not None
        if previous != (self.previous_disposition_digest is not None):
            raise FeedbackContractError("disposition predecessor is partial")
        if previous:
            if type(self.previous_disposition_id) is not str or (
                _DISPOSITION_ID.fullmatch(self.previous_disposition_id) is None
            ):
                raise FeedbackContractError("previous_disposition_id must be canonical")
            _digest(
                self.previous_disposition_digest,
                "previous_disposition_digest",
            )
        current = self.expected_current_disposition_id is not None
        if current != (self.expected_current_disposition_digest is not None):
            raise FeedbackContractError("disposition CAS is partial")
        if type(self.expected_current_ordinal) is not int or (
            self.expected_current_ordinal < 0
        ):
            raise FeedbackContractError("disposition CAS ordinal differs")
        if self.ordinal == 1:
            if previous or current or self.expected_current_ordinal != 0:
                raise FeedbackContractError("first disposition CAS differs")
        elif (
            not previous
            or not current
            or self.expected_current_ordinal != self.ordinal - 1
            or self.expected_current_disposition_id != self.previous_disposition_id
            or self.expected_current_disposition_digest
            != self.previous_disposition_digest
        ):
            raise FeedbackContractError("successor disposition CAS differs")
        if (
            type(self.outcome) is not ReconciliationDispositionOutcome
            or type(self.reason) is not ReconciliationDispositionReason
        ):
            raise FeedbackContractError("disposition outcome and reason must be exact")
        if self.reason not in _DISPOSITION_REASON_MATRIX[self.outcome]:
            raise FeedbackContractError("disposition outcome and reason differ")
        supplemental = (
            self.obligation_kind
            is ReconciliationObligationKind.GOVERN_SUPPLEMENTAL_DISCOVERY
        )
        if (
            self.supplemental_reentry is not None
            and type(self.supplemental_reentry) is not SupplementalDiscoveryReentry
        ):
            raise FeedbackContractError("supplemental re-entry must be exact")
        if self.outcome is ReconciliationDispositionOutcome.FULFILLED:
            expected_reason = (
                ReconciliationDispositionReason.SUPPLEMENTAL_DISCOVERY_REENTERED
                if supplemental
                else ReconciliationDispositionReason.FEEDBACK_RECORDED
            )
            if self.reason is not expected_reason:
                raise FeedbackContractError("fulfilled disposition reason differs")
            if supplemental != (self.supplemental_reentry is not None):
                raise FeedbackContractError("supplemental fulfilment proof differs")
        elif self.supplemental_reentry is not None:
            raise FeedbackContractError(
                "non-fulfilled disposition has supplemental proof"
            )
        if self.supplemental_reentry is not None and (
            self.resolution_digest != _supplemental_digest(self.supplemental_reentry)
        ):
            raise FeedbackContractError("supplemental resolution digest differs")
        _text(self.idempotency_key, "idempotency_key")
        if (
            self.immutable is not True
            or self.evaluation_only is not True
            or self.publication_authority is not False
            or self.evidence_authority is not False
            or self.candidate_authority is not False
        ):
            raise FeedbackContractError("disposition authority boundary differs")
        expected = _identity(
            "disposition",
            {"obligation_id": self.obligation_id, "ordinal": self.ordinal},
        )
        if self.disposition_id != expected:
            raise FeedbackContractError("disposition_id differs")
        _ = self.canonical_bytes

    @property
    def canonical_value(self) -> dict[str, object]:
        value = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "schema_identity"
        }
        value["obligation_kind"] = self.obligation_kind.value
        value["outcome"] = self.outcome.value
        value["reason"] = self.reason.value
        value["supplemental_reentry"] = (
            None
            if self.supplemental_reentry is None
            else self.supplemental_reentry.canonical_value()
        )
        return value

    @property
    def canonical_bytes(self) -> bytes:
        return _document(
            RECONCILIATION_DISPOSITION,
            "disposition",
            self.canonical_value,
        )

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        fields = set(cls.__dataclass_fields__) - {"schema_identity"}
        item = _decode_document(raw, RECONCILIATION_DISPOSITION, "disposition", fields)
        copied = dict(item)
        copied["obligation_kind"] = _enum(
            ReconciliationObligationKind,
            item["obligation_kind"],
            "obligation_kind",
        )
        copied["outcome"] = _enum(
            ReconciliationDispositionOutcome, item["outcome"], "outcome"
        )
        copied["reason"] = _enum(
            ReconciliationDispositionReason, item["reason"], "reason"
        )
        try:
            copied["supplemental_reentry"] = (
                None
                if item["supplemental_reentry"] is None
                else SupplementalDiscoveryReentry.from_value(
                    item["supplemental_reentry"]
                )
            )
            value = cls(**copied)  # type: ignore[arg-type]
        except FeedbackContractError:
            raise
        except Exception as exc:
            raise FeedbackContractError(
                "Reconciliation Disposition replay failed"
            ) from exc
        if value.canonical_bytes != raw:
            raise FeedbackContractError("Reconciliation Disposition replay differs")
        return value


@_total("Reconciliation history validation failed")
def validate_reconciliation_history(
    obligation: ReconciliationObligation,
    history: tuple[ReconciliationDisposition, ...],
) -> tuple[ReconciliationDisposition, ...]:
    """Validate a complete immutable contiguous disposition history."""
    if type(obligation) is not ReconciliationObligation or type(history) is not tuple:
        raise FeedbackContractError("reconciliation history inputs must be exact")
    _ = ReconciliationObligation.from_canonical_bytes(obligation.canonical_bytes)
    if any(type(item) is not ReconciliationDisposition for item in history):
        raise FeedbackContractError("reconciliation history must be an exact tuple")
    request_ids: set[str] = set()
    idempotency: set[tuple[str, str]] = set()
    previous: ReconciliationDisposition | None = None
    for ordinal, item in enumerate(history, 1):
        _ = ReconciliationDisposition.from_canonical_bytes(item.canonical_bytes)
        if (
            item.ordinal != ordinal
            or item.obligation_id != obligation.obligation_id
            or item.obligation_digest != obligation.canonical_digest
            or item.obligation_kind is not obligation.kind
            or item.feedback_id != obligation.feedback_id
            or item.feedback_digest != obligation.feedback_digest
            or item.candidate_id != obligation.candidate_id
            or item.candidate_version_id != obligation.candidate_version_id
            or item.candidate_version_digest != obligation.candidate_version_digest
        ):
            raise FeedbackContractError("disposition obligation binding differs")
        expected_previous = (
            (None, None)
            if previous is None
            else (previous.disposition_id, previous.canonical_digest)
        )
        if (
            item.previous_disposition_id,
            item.previous_disposition_digest,
        ) != expected_previous:
            raise FeedbackContractError("disposition predecessor differs")
        if previous is not None and (
            previous.outcome is ReconciliationDispositionOutcome.FULFILLED
        ):
            raise FeedbackContractError("fulfilled reconciliation is terminal")
        request_key = (item.actor_identity_digest, item.idempotency_key)
        if item.request_id in request_ids or request_key in idempotency:
            raise FeedbackContractError("disposition request bindings duplicate")
        request_ids.add(item.request_id)
        idempotency.add(request_key)
        previous = item
    return history


def _same_supplemental(
    left: SupplementalDiscoveryReentry | None,
    right: SupplementalDiscoveryReentry | None,
) -> bool:
    if left is None or right is None:
        return left is right
    return left.canonical_value() == right.canonical_value()


@_total("Reconciliation Disposition append failed")
def append_reconciliation_disposition(
    obligation: ReconciliationObligation,
    history: tuple[ReconciliationDisposition, ...],
    *,
    outcome: ReconciliationDispositionOutcome,
    reason: ReconciliationDispositionReason,
    resolution_digest: str,
    request_id: str,
    actor_identity_digest: str,
    idempotency_key: str,
    expected_current_disposition_id: str | None,
    expected_current_disposition_digest: str | None,
    expected_current_ordinal: int,
    supplemental_reentry: SupplementalDiscoveryReentry | None = None,
) -> ReconciliationDisposition:
    """Append or replay one CAS-bound immutable disposition."""
    history = validate_reconciliation_history(obligation, history)
    for item in history:
        if item.request_id == request_id or (
            item.actor_identity_digest,
            item.idempotency_key,
        ) == (actor_identity_digest, idempotency_key):
            exact = (
                item.outcome is outcome
                and item.reason is reason
                and item.resolution_digest == resolution_digest
                and item.request_id == request_id
                and item.actor_identity_digest == actor_identity_digest
                and item.idempotency_key == idempotency_key
                and item.expected_current_disposition_id
                == expected_current_disposition_id
                and item.expected_current_disposition_digest
                == expected_current_disposition_digest
                and item.expected_current_ordinal == expected_current_ordinal
                and _same_supplemental(item.supplemental_reentry, supplemental_reentry)
            )
            if exact:
                return item
            raise FeedbackContractError("disposition request binding conflict")
    previous = history[-1] if history else None
    if previous is not None and (
        previous.outcome is ReconciliationDispositionOutcome.FULFILLED
    ):
        raise FeedbackContractError("fulfilled reconciliation is terminal")
    expected = (
        (None, None, 0)
        if previous is None
        else (previous.disposition_id, previous.canonical_digest, previous.ordinal)
    )
    if (
        expected_current_disposition_id,
        expected_current_disposition_digest,
        expected_current_ordinal,
    ) != expected:
        raise FeedbackContractError("disposition CAS differs")
    ordinal = len(history) + 1
    return ReconciliationDisposition(
        disposition_id=_identity(
            "disposition",
            {"obligation_id": obligation.obligation_id, "ordinal": ordinal},
        ),
        obligation_id=obligation.obligation_id,
        obligation_digest=obligation.canonical_digest,
        obligation_kind=obligation.kind,
        feedback_id=obligation.feedback_id,
        feedback_digest=obligation.feedback_digest,
        candidate_id=obligation.candidate_id,
        candidate_version_id=obligation.candidate_version_id,
        candidate_version_digest=obligation.candidate_version_digest,
        ordinal=ordinal,
        previous_disposition_id=None if previous is None else previous.disposition_id,
        previous_disposition_digest=None
        if previous is None
        else previous.canonical_digest,
        outcome=outcome,
        reason=reason,
        resolution_digest=resolution_digest,
        supplemental_reentry=supplemental_reentry,
        request_id=request_id,
        actor_identity_digest=actor_identity_digest,
        idempotency_key=idempotency_key,
        expected_current_disposition_id=expected_current_disposition_id,
        expected_current_disposition_digest=expected_current_disposition_digest,
        expected_current_ordinal=expected_current_ordinal,
    )


def reconciliation_is_open(
    obligation: ReconciliationObligation,
    history: tuple[ReconciliationDisposition, ...],
) -> bool:
    """Keep an obligation visible until a terminal fulfilled disposition."""
    verified = validate_reconciliation_history(obligation, history)
    return not verified or (
        verified[-1].outcome is not ReconciliationDispositionOutcome.FULFILLED
    )


__all__ = [
    "EVALUATION_FEEDBACK",
    "EvaluationFeedback",
    "EvaluationFeedbackOutcome",
    "EvaluationFeedbackReason",
    "FeedbackContractError",
    "FeedbackCorrelationOutcome",
    "MAX_FEEDBACK_CANONICAL_BYTES",
    "RECONCILIATION_DISPOSITION",
    "RECONCILIATION_OBLIGATION",
    "ReconciliationDisposition",
    "ReconciliationDispositionOutcome",
    "ReconciliationDispositionReason",
    "ReconciliationObligation",
    "ReconciliationObligationKind",
    "append_reconciliation_disposition",
    "correlate_evaluation_feedback",
    "create_evaluation_feedback",
    "create_reconciliation_obligation",
    "reconciliation_is_open",
    "validate_reconciliation_history",
]
