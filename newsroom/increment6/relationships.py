"""Pure Event Hypothesis relationship-decision contract.

This Tier-L module compares immutable Hypothesis Version bindings.  It does not
open a store, authenticate a caller, allocate lineage, or authorise an effect.
Persistence and relationship authority remain outside this phase.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Self

from newsroom.authority.canonical import (
    MAX_SAFE_INTEGER,
    canonical_json_bytes,
    digest_bytes,
)
from newsroom.increment6.hypotheses import (
    EventHypothesisVersion,
    HypothesisSourceBinding,
)

HYPOTHESIS_RELATIONSHIP_DECISION = (
    "newsroom.increment6.hypothesis-relationship-decision.v1"
)
MAX_RELATIONSHIP_CANONICAL_BYTES = 16_777_216
MAX_COMPARATORS = 256
ADEQUATE_MATCH_THRESHOLD = 60
CORRECTION_REVERSAL_THRESHOLD = 80
DEVELOPMENT_THRESHOLD = 75
SAME_STATE_THRESHOLD = 80
RELATED_DISTINCT_THRESHOLD = 60

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_MAX_JSON_DEPTH = 24
_MAX_JSON_NODES = 32768


class RelationshipContractError(ValueError):
    """A relationship value or replay failed closed."""


class RelationshipDecision(StrEnum):
    REL_SAME_STATE = "REL_SAME_STATE"
    REL_DEVELOPMENT_OF = "REL_DEVELOPMENT_OF"
    REL_CORRECTION_REVERSAL_OF = "REL_CORRECTION_REVERSAL_OF"
    REL_RELATED_DISTINCT = "REL_RELATED_DISTINCT"
    REL_NO_ADEQUATE_PRIOR_MATCH = "REL_NO_ADEQUATE_PRIOR_MATCH"
    REL_UNCERTAIN = "REL_UNCERTAIN"


class RelationshipDecisionReason(StrEnum):
    SAME_STATE_THRESHOLD_MET = "SAME_STATE_THRESHOLD_MET"
    DEVELOPMENT_THRESHOLD_MET = "DEVELOPMENT_THRESHOLD_MET"
    CORRECTION_REVERSAL_THRESHOLD_MET = "CORRECTION_REVERSAL_THRESHOLD_MET"
    RELATED_DISTINCT_THRESHOLD_MET = "RELATED_DISTINCT_THRESHOLD_MET"
    COMPLETE_SET_NO_ADEQUATE_MATCH = "COMPLETE_SET_NO_ADEQUATE_MATCH"
    ADEQUATE_MATCH_CLASSIFICATION_UNCERTAIN = "ADEQUATE_MATCH_CLASSIFICATION_UNCERTAIN"


RELATIONSHIP_DECISION_REASON = MappingProxyType(
    {
        RelationshipDecision.REL_SAME_STATE: frozenset(
            {RelationshipDecisionReason.SAME_STATE_THRESHOLD_MET}
        ),
        RelationshipDecision.REL_DEVELOPMENT_OF: frozenset(
            {RelationshipDecisionReason.DEVELOPMENT_THRESHOLD_MET}
        ),
        RelationshipDecision.REL_CORRECTION_REVERSAL_OF: frozenset(
            {RelationshipDecisionReason.CORRECTION_REVERSAL_THRESHOLD_MET}
        ),
        RelationshipDecision.REL_RELATED_DISTINCT: frozenset(
            {RelationshipDecisionReason.RELATED_DISTINCT_THRESHOLD_MET}
        ),
        RelationshipDecision.REL_NO_ADEQUATE_PRIOR_MATCH: frozenset(
            {RelationshipDecisionReason.COMPLETE_SET_NO_ADEQUATE_MATCH}
        ),
        RelationshipDecision.REL_UNCERTAIN: frozenset(
            {RelationshipDecisionReason.ADEQUATE_MATCH_CLASSIFICATION_UNCERTAIN}
        ),
    }
)


class AssessmentStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    UNAVAILABLE = "UNAVAILABLE"


class _NoEffect:
    authorises_authority = False
    authorises_persistence = False
    authorises_external_effect = False
    authorises_publication = False
    authorises_evidence = False
    authorises_egress = False
    authorises_relationship = False
    creates_candidate = False
    creates_lineage = False
    creates_relationship = False


def _normalise[T](operation: object, message: str) -> T:
    try:
        return operation()  # type: ignore[operator,no-any-return]
    except RelationshipContractError:
        raise
    except Exception as exc:
        raise RelationshipContractError(message) from exc


def _digest(value: object, field: str) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise RelationshipContractError(f"{field} must be a canonical SHA-256 digest")
    return value


def _uuid(value: object, field: str) -> str:
    if type(value) is not str or _UUID.fullmatch(value) is None:
        raise RelationshipContractError(f"{field} must be a canonical UUID")
    return value


def _score(value: object, field: str) -> int:
    if type(value) is not int or not 0 <= value <= 100:
        raise RelationshipContractError(f"{field} must be an integer from 0 to 100")
    return value


def _exact(value: object, fields: set[str], field: str) -> dict[str, object]:
    if type(value) is not dict:
        raise RelationshipContractError(f"{field} fields are not exact")
    try:
        if set(value) != fields:
            raise RelationshipContractError(f"{field} fields are not exact")
    except RelationshipContractError:
        raise
    except Exception as exc:
        raise RelationshipContractError(f"{field} fields are not exact") from exc
    return value


def _canonical(value: object, field: str) -> bytes:
    try:
        raw = canonical_json_bytes(value)
    except RelationshipContractError:
        raise
    except Exception as exc:
        raise RelationshipContractError(f"{field} cannot be canonicalised") from exc
    if not raw or len(raw) > MAX_RELATIONSHIP_CANONICAL_BYTES:
        raise RelationshipContractError(f"{field} exceeds the canonical byte bound")
    return raw


def _decode(raw: bytes, field: str) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_RELATIONSHIP_CANONICAL_BYTES:
        raise RelationshipContractError(f"{field} requires bounded immutable bytes")

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise RelationshipContractError(f"{field} contains a duplicate key")
            result[key] = value
        return result

    def integer(text: str) -> int:
        if len(text.lstrip("-")) > 16:
            raise RelationshipContractError(f"{field} integer exceeds bounds")
        value = int(text)
        if not -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
            raise RelationshipContractError(f"{field} integer exceeds bounds")
        return value

    def unsupported(_: str) -> float:
        raise RelationshipContractError(f"{field} contains an unsupported number")

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique,
            parse_int=integer,
            parse_float=unsupported,
            parse_constant=unsupported,
        )
    except RelationshipContractError:
        raise
    except Exception as exc:
        raise RelationshipContractError(f"{field} is not valid UTF-8 JSON") from exc

    pending: list[tuple[object, int]] = [(value, 1)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if depth > _MAX_JSON_DEPTH or nodes > _MAX_JSON_NODES:
            raise RelationshipContractError(f"{field} exceeds structural bounds")
        if type(item) is dict:
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        elif type(item) not in (str, int, bool, type(None)):
            raise RelationshipContractError(f"{field} contains an unsupported value")
    if type(value) is not dict:
        raise RelationshipContractError(f"{field} must be an object")
    try:
        if canonical_json_bytes(value) != raw:
            raise RelationshipContractError(f"{field} is not canonical JSON")
    except RelationshipContractError:
        raise
    except Exception as exc:
        raise RelationshipContractError(f"{field} cannot be normalised") from exc
    return value


def _source_value(source: HypothesisSourceBinding) -> dict[str, object]:
    if type(source) is not HypothesisSourceBinding:
        raise RelationshipContractError(
            "source binding requires the exact contract type"
        )
    return _normalise(source.canonical_value, "source binding cannot be read")


@dataclass(frozen=True, slots=True)
class HypothesisVersionBinding(_NoEffect):
    hypothesis_id: str
    version_id: str
    version_digest: str
    actor_identity_digest: str
    source_bindings: tuple[HypothesisSourceBinding, ...]

    def __post_init__(self) -> None:
        if type(self) is not HypothesisVersionBinding:
            raise RelationshipContractError("Version binding requires the exact type")
        _uuid(self.hypothesis_id, "hypothesis_id")
        _uuid(self.version_id, "version_id")
        _digest(self.version_digest, "version_digest")
        _digest(self.actor_identity_digest, "actor_identity_digest")
        if (
            type(self.source_bindings) is not tuple
            or not self.source_bindings
            or len(self.source_bindings) > 32
            or any(
                type(item) is not HypothesisSourceBinding
                for item in self.source_bindings
            )
        ):
            raise RelationshipContractError(
                "source_bindings must be a non-empty bounded exact tuple"
            )
        keys = tuple(
            (item.decision_lead_id, item.disposition_id)
            for item in self.source_bindings
        )
        if keys != tuple(sorted(set(keys))):
            raise RelationshipContractError(
                "source_bindings must be complete, sorted and unique"
            )
        _canonical(self.canonical_value, "Version binding")

    @classmethod
    def from_version(cls, version: EventHypothesisVersion) -> Self:
        if type(version) is not EventHypothesisVersion:
            raise RelationshipContractError(
                "Version binding requires an exact Hypothesis Version"
            )
        return _normalise(
            lambda: cls(
                version.hypothesis_id,
                version.version_id,
                version.canonical_digest,
                version.actor_identity_digest,
                version.source_bindings,
            ),
            "Hypothesis Version cannot be bound",
        )

    @property
    def canonical_value(self) -> dict[str, object]:
        return _normalise(
            lambda: {
                "hypothesis_id": self.hypothesis_id,
                "version_id": self.version_id,
                "version_digest": self.version_digest,
                "actor_identity_digest": self.actor_identity_digest,
                "source_bindings": [
                    _source_value(item) for item in self.source_bindings
                ],
            },
            "Version binding cannot be represented",
        )

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical(self.canonical_value, "Version binding")

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_value(cls, value: object) -> Self:
        fields = {
            "hypothesis_id",
            "version_id",
            "version_digest",
            "actor_identity_digest",
            "source_bindings",
        }
        item = _exact(value, fields, "Version binding")
        sources = item["source_bindings"]
        if type(sources) is not list or not sources or len(sources) > 32:
            raise RelationshipContractError("source_bindings must be an array")
        return _normalise(
            lambda: cls(
                item["hypothesis_id"],  # type: ignore[arg-type]
                item["version_id"],  # type: ignore[arg-type]
                item["version_digest"],  # type: ignore[arg-type]
                item["actor_identity_digest"],  # type: ignore[arg-type]
                tuple(HypothesisSourceBinding.from_value(source) for source in sources),
            ),
            "Version binding replay failed",
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        return cls.from_value(_decode(raw, "Version binding"))


@dataclass(frozen=True, slots=True)
class ComparatorSetManifest(_NoEffect):
    status: AssessmentStatus
    comparators: tuple[HypothesisVersionBinding, ...]

    def __post_init__(self) -> None:
        if type(self) is not ComparatorSetManifest:
            raise RelationshipContractError(
                "comparator manifest requires the exact type"
            )
        if type(self.status) is not AssessmentStatus:
            raise RelationshipContractError("comparator manifest status must be exact")
        if (
            type(self.comparators) is not tuple
            or len(self.comparators) > MAX_COMPARATORS
            or any(
                type(item) is not HypothesisVersionBinding for item in self.comparators
            )
        ):
            raise RelationshipContractError("comparators must be a bounded exact tuple")
        if self.status is AssessmentStatus.UNAVAILABLE and self.comparators:
            raise RelationshipContractError(
                "an unavailable manifest cannot claim comparators"
            )
        keys = tuple(item.version_id for item in self.comparators)
        if keys != tuple(sorted(set(keys))):
            raise RelationshipContractError("comparators must be sorted and unique")
        _canonical(self.canonical_value, "comparator manifest")

    @classmethod
    def complete(cls, comparators: tuple[HypothesisVersionBinding, ...]) -> Self:
        if type(comparators) is not tuple:
            raise RelationshipContractError("comparators must be an exact tuple")
        if len(comparators) > MAX_COMPARATORS or any(
            type(item) is not HypothesisVersionBinding for item in comparators
        ):
            raise RelationshipContractError("comparators must be a bounded exact tuple")
        return _normalise(
            lambda: cls(
                AssessmentStatus.COMPLETE,
                tuple(sorted(comparators, key=lambda item: item.version_id)),
            ),
            "comparator manifest construction failed",
        )

    @property
    def canonical_value(self) -> dict[str, object]:
        return _normalise(
            lambda: {
                "status": self.status.value,
                "comparators": [item.canonical_value for item in self.comparators],
            },
            "comparator manifest cannot be represented",
        )

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical(self.canonical_value, "comparator manifest")

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_value(cls, value: object) -> Self:
        item = _exact(value, {"status", "comparators"}, "comparator manifest")
        comparators = item["comparators"]
        if type(comparators) is not list or len(comparators) > MAX_COMPARATORS:
            raise RelationshipContractError("comparators must be an array")
        return _normalise(
            lambda: cls(
                AssessmentStatus(item["status"]),  # type: ignore[arg-type]
                tuple(
                    HypothesisVersionBinding.from_value(value) for value in comparators
                ),
            ),
            "comparator manifest replay failed",
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        return cls.from_value(_decode(raw, "comparator manifest"))


@dataclass(frozen=True, slots=True)
class ComparatorEvidence(_NoEffect):
    subject: HypothesisVersionBinding
    comparator: HypothesisVersionBinding
    score: int
    correction_reversal_score: int
    development_score: int
    same_state_score: int
    related_distinct_score: int

    def __post_init__(self) -> None:
        if type(self) is not ComparatorEvidence:
            raise RelationshipContractError(
                "comparator evidence requires the exact type"
            )
        if (
            type(self.subject) is not HypothesisVersionBinding
            or type(self.comparator) is not HypothesisVersionBinding
        ):
            raise RelationshipContractError("evidence bindings must be exact")
        if self.subject.version_id == self.comparator.version_id:
            raise RelationshipContractError("a Version cannot compare with itself")
        for field in (
            "score",
            "correction_reversal_score",
            "development_score",
            "same_state_score",
            "related_distinct_score",
        ):
            _score(getattr(self, field), field)
        _canonical(self.canonical_value, "comparator evidence")

    @property
    def canonical_value(self) -> dict[str, object]:
        return _normalise(
            lambda: {
                "subject": self.subject.canonical_value,
                "comparator": self.comparator.canonical_value,
                "score": self.score,
                "correction_reversal_score": self.correction_reversal_score,
                "development_score": self.development_score,
                "same_state_score": self.same_state_score,
                "related_distinct_score": self.related_distinct_score,
            },
            "comparator evidence cannot be represented",
        )

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical(self.canonical_value, "comparator evidence")

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_value(cls, value: object) -> Self:
        fields = {
            "subject",
            "comparator",
            "score",
            "correction_reversal_score",
            "development_score",
            "same_state_score",
            "related_distinct_score",
        }
        item = _exact(value, fields, "comparator evidence")
        return _normalise(
            lambda: cls(
                HypothesisVersionBinding.from_value(item["subject"]),
                HypothesisVersionBinding.from_value(item["comparator"]),
                item["score"],  # type: ignore[arg-type]
                item["correction_reversal_score"],  # type: ignore[arg-type]
                item["development_score"],  # type: ignore[arg-type]
                item["same_state_score"],  # type: ignore[arg-type]
                item["related_distinct_score"],  # type: ignore[arg-type]
            ),
            "comparator evidence replay failed",
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        return cls.from_value(_decode(raw, "comparator evidence"))


@dataclass(frozen=True, slots=True)
class RelationshipAssessment(_NoEffect):
    status: AssessmentStatus
    subject: HypothesisVersionBinding
    comparator_manifest: ComparatorSetManifest
    decision: RelationshipDecision | None
    reason: RelationshipDecisionReason | None
    comparator: HypothesisVersionBinding | None
    score: int | None
    evidence_digest: str | None

    def __post_init__(self) -> None:
        if type(self) is not RelationshipAssessment:
            raise RelationshipContractError(
                "relationship assessment requires the exact type"
            )
        if type(self.status) is not AssessmentStatus:
            raise RelationshipContractError("assessment status must be exact")
        if (
            type(self.subject) is not HypothesisVersionBinding
            or type(self.comparator_manifest) is not ComparatorSetManifest
        ):
            raise RelationshipContractError("assessment bindings must be exact")
        if self.status is not self.comparator_manifest.status:
            raise RelationshipContractError(
                "assessment status differs from its manifest"
            )
        fields_present = (
            self.decision is not None,
            self.reason is not None,
            self.score is not None,
            self.evidence_digest is not None,
        )
        if self.status is AssessmentStatus.COMPLETE:
            if not all(fields_present):
                raise RelationshipContractError(
                    "complete assessment fields are incomplete"
                )
            if (
                type(self.decision) is not RelationshipDecision
                or type(self.reason) is not RelationshipDecisionReason
            ):
                raise RelationshipContractError("decision and reason must be exact")
            if self.reason not in RELATIONSHIP_DECISION_REASON[self.decision]:
                raise RelationshipContractError("reason is outside the decision family")
            _score(self.score, "assessment score")
            _digest(self.evidence_digest, "evidence_digest")
            pairwise = (
                self.decision is not RelationshipDecision.REL_NO_ADEQUATE_PRIOR_MATCH
            )
            if pairwise != (self.comparator is not None):
                raise RelationshipContractError(
                    "decision comparator binding is inconsistent"
                )
            if self.comparator is not None and (
                type(self.comparator) is not HypothesisVersionBinding
                or self.comparator not in self.comparator_manifest.comparators
            ):
                raise RelationshipContractError(
                    "decision comparator is outside its manifest"
                )
        else:
            if any(fields_present) or self.comparator is not None:
                raise RelationshipContractError(
                    "non-complete assessments cannot contain a decision"
                )
        _canonical(self.canonical_value, "relationship assessment")

    @property
    def canonical_value(self) -> dict[str, object]:
        return _normalise(
            lambda: {
                "schema_version": HYPOTHESIS_RELATIONSHIP_DECISION,
                "status": self.status.value,
                "subject": self.subject.canonical_value,
                "comparator_manifest": self.comparator_manifest.canonical_value,
                "decision": None if self.decision is None else self.decision.value,
                "reason": None if self.reason is None else self.reason.value,
                "comparator": None
                if self.comparator is None
                else self.comparator.canonical_value,
                "score": self.score,
                "evidence_digest": self.evidence_digest,
            },
            "relationship assessment cannot be represented",
        )

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical(self.canonical_value, "relationship assessment")

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def comparator_manifest_digest(self) -> str:
        """Return the exact comparator-set identity bound by this assessment."""
        return self.comparator_manifest.canonical_digest

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        fields = {
            "schema_version",
            "status",
            "subject",
            "comparator_manifest",
            "decision",
            "reason",
            "comparator",
            "score",
            "evidence_digest",
        }
        item = _exact(
            _decode(raw, "relationship assessment"), fields, "relationship assessment"
        )
        if item["schema_version"] != HYPOTHESIS_RELATIONSHIP_DECISION:
            raise RelationshipContractError(
                "relationship assessment schema is unsupported"
            )
        return _normalise(
            lambda: cls(
                AssessmentStatus(item["status"]),  # type: ignore[arg-type]
                HypothesisVersionBinding.from_value(item["subject"]),
                ComparatorSetManifest.from_value(item["comparator_manifest"]),
                None
                if item["decision"] is None
                else RelationshipDecision(item["decision"]),  # type: ignore[arg-type]
                None
                if item["reason"] is None
                else RelationshipDecisionReason(item["reason"]),  # type: ignore[arg-type]
                None
                if item["comparator"] is None
                else HypothesisVersionBinding.from_value(item["comparator"]),
                item["score"],  # type: ignore[arg-type]
                item["evidence_digest"],  # type: ignore[arg-type]
            ),
            "relationship assessment replay failed",
        )


_PRECEDENCE = {
    RelationshipDecision.REL_CORRECTION_REVERSAL_OF: 0,
    RelationshipDecision.REL_DEVELOPMENT_OF: 1,
    RelationshipDecision.REL_SAME_STATE: 2,
    RelationshipDecision.REL_RELATED_DISTINCT: 3,
}


def _classify(
    evidence: ComparatorEvidence,
) -> tuple[RelationshipDecision, RelationshipDecisionReason] | None:
    if evidence.correction_reversal_score >= CORRECTION_REVERSAL_THRESHOLD:
        return (
            RelationshipDecision.REL_CORRECTION_REVERSAL_OF,
            RelationshipDecisionReason.CORRECTION_REVERSAL_THRESHOLD_MET,
        )
    if evidence.development_score >= DEVELOPMENT_THRESHOLD:
        return (
            RelationshipDecision.REL_DEVELOPMENT_OF,
            RelationshipDecisionReason.DEVELOPMENT_THRESHOLD_MET,
        )
    if evidence.same_state_score >= SAME_STATE_THRESHOLD:
        return (
            RelationshipDecision.REL_SAME_STATE,
            RelationshipDecisionReason.SAME_STATE_THRESHOLD_MET,
        )
    if evidence.related_distinct_score >= RELATED_DISTINCT_THRESHOLD:
        return (
            RelationshipDecision.REL_RELATED_DISTINCT,
            RelationshipDecisionReason.RELATED_DISTINCT_THRESHOLD_MET,
        )
    return None


def assess_relationships(
    subject: HypothesisVersionBinding,
    comparator_manifest: ComparatorSetManifest,
    evidence: tuple[ComparatorEvidence, ...],
) -> RelationshipAssessment:
    """Apply the fixed integer policy to one exact, complete comparator set."""
    if (
        type(subject) is not HypothesisVersionBinding
        or type(comparator_manifest) is not ComparatorSetManifest
    ):
        raise RelationshipContractError("assessment bindings must be exact")
    if (
        type(evidence) is not tuple
        or len(evidence) > MAX_COMPARATORS
        or any(type(item) is not ComparatorEvidence for item in evidence)
    ):
        raise RelationshipContractError("evidence must be a bounded exact tuple")
    if comparator_manifest.status is not AssessmentStatus.COMPLETE:
        if evidence:
            raise RelationshipContractError(
                "unavailable comparator sets cannot carry evidence"
            )
        return RelationshipAssessment(
            comparator_manifest.status,
            subject,
            comparator_manifest,
            None,
            None,
            None,
            None,
            None,
        )
    if any(
        item.version_id == subject.version_id
        for item in comparator_manifest.comparators
    ):
        raise RelationshipContractError(
            "subject must be absent from its comparator set"
        )
    by_id: dict[str, ComparatorEvidence] = {}
    for item in evidence:
        if item.subject != subject:
            raise RelationshipContractError("evidence subject binding differs")
        comparator_id = item.comparator.version_id
        if comparator_id in by_id:
            raise RelationshipContractError("duplicate comparator evidence")
        by_id[comparator_id] = item
    expected = {item.version_id: item for item in comparator_manifest.comparators}
    if set(by_id) != set(expected):
        raise RelationshipContractError(
            "evidence does not exactly cover the comparator manifest"
        )
    if any(by_id[key].comparator != expected[key] for key in expected):
        raise RelationshipContractError(
            "evidence comparator binding differs from its manifest"
        )

    ordered_evidence = tuple(by_id[key] for key in sorted(by_id))
    evidence_digest = digest_bytes(
        _canonical([item.canonical_value for item in ordered_evidence], "evidence set")
    )
    adequate = tuple(
        item for item in ordered_evidence if item.score >= ADEQUATE_MATCH_THRESHOLD
    )
    if not adequate:
        return RelationshipAssessment(
            AssessmentStatus.COMPLETE,
            subject,
            comparator_manifest,
            RelationshipDecision.REL_NO_ADEQUATE_PRIOR_MATCH,
            RelationshipDecisionReason.COMPLETE_SET_NO_ADEQUATE_MATCH,
            None,
            0,
            evidence_digest,
        )
    classified = tuple(
        (classification[0], classification[1], item)
        for item in adequate
        if (classification := _classify(item)) is not None
    )
    if not classified:
        best = min(adequate, key=lambda item: (-item.score, item.comparator.version_id))
        return RelationshipAssessment(
            AssessmentStatus.COMPLETE,
            subject,
            comparator_manifest,
            RelationshipDecision.REL_UNCERTAIN,
            RelationshipDecisionReason.ADEQUATE_MATCH_CLASSIFICATION_UNCERTAIN,
            best.comparator,
            best.score,
            evidence_digest,
        )
    decision, reason, selected = min(
        classified,
        key=lambda item: (
            _PRECEDENCE[item[0]],
            -item[2].score,
            item[2].comparator.version_id,
        ),
    )
    return RelationshipAssessment(
        AssessmentStatus.COMPLETE,
        subject,
        comparator_manifest,
        decision,
        reason,
        selected.comparator,
        selected.score,
        evidence_digest,
    )


__all__ = [
    "ADEQUATE_MATCH_THRESHOLD",
    "CORRECTION_REVERSAL_THRESHOLD",
    "DEVELOPMENT_THRESHOLD",
    "HYPOTHESIS_RELATIONSHIP_DECISION",
    "MAX_RELATIONSHIP_CANONICAL_BYTES",
    "RELATED_DISTINCT_THRESHOLD",
    "RELATIONSHIP_DECISION_REASON",
    "SAME_STATE_THRESHOLD",
    "AssessmentStatus",
    "ComparatorEvidence",
    "ComparatorSetManifest",
    "HypothesisVersionBinding",
    "RelationshipAssessment",
    "RelationshipContractError",
    "RelationshipDecision",
    "RelationshipDecisionReason",
    "assess_relationships",
]
