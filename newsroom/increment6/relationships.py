"""Pure Event Hypothesis relationship-decision contract.

This Tier-L module compares immutable Hypothesis Version bindings.  It does not
open a store, authenticate a caller, allocate lineage, or authorise an effect.
Persistence and relationship authority remain outside this phase.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Self

from newsroom.authority.canonical import (
    MAX_SAFE_INTEGER,
    canonical_json_bytes,
    digest_bytes,
)
from newsroom.authority.models import CommandDefinition
from newsroom.authority.policy import (
    CommandRegistry,
    PayloadGoldenVector,
    PayloadSchemaContract,
    PayloadSchemaRegistry,
)
from newsroom.authority.types import PayloadMode, TrustScope, UtcTimestamp
from newsroom.increment6.hypotheses import (
    EventHypothesisVersion,
    HypothesisSourceBinding,
)
from newsroom.increment6.outcomes import (
    CanonicalOutcome,
    ReasonBasisClass,
    ReasonCode,
    ReasonReference,
    StructuredReason,
)

HYPOTHESIS_RELATIONSHIP_DECISION = (
    "newsroom.increment6.hypothesis-relationship-decision.v1"
)
RELATIONSHIP_COMMAND_TYPE = "increment6.relationship-decision.retain"
RELATIONSHIP_AGGREGATE_TYPE = "event_hypothesis_relationship_decision"
RELATIONSHIP_EVENT_TYPE = "event_hypothesis_relationship_decision_retained"
RELATIONSHIP_COMMAND_DEFINITION_VERSION = "relationship-command-v1"
RELATIONSHIP_PAYLOAD_CONTRACT_VERSION = "relationship-schema-v1"
RELATIONSHIP_PAYLOAD_CANONICALIZER_VERSION = "relationship-canonical-json-v1"
RELATIONSHIP_REQUIRED_SCOPE = "authority.relationship.retain"
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
_MAX_SOURCE_BINDINGS = 32
_SOURCE_BINDING_MAX_NODES = 9
_VERSION_BINDING_MAX_NODES = 6 + (_MAX_SOURCE_BINDINGS * _SOURCE_BINDING_MAX_NODES)
# A maximum assessment contains a subject, all comparator bindings in its
# manifest, a selected comparator replica, and bounded structured-reason data.
_MAX_JSON_NODES = 2_048 + ((MAX_COMPARATORS + 2) * _VERSION_BINDING_MAX_NODES)


class RelationshipContractError(ValueError):
    """A relationship value or replay failed closed."""


RELATIONSHIP_DECISION_REASON = MappingProxyType(
    {
        CanonicalOutcome.REL_SAME_STATE: frozenset({ReasonCode.REL_SAME_STATE}),
        CanonicalOutcome.REL_DEVELOPMENT_OF: frozenset({ReasonCode.REL_DEVELOPMENT}),
        CanonicalOutcome.REL_CORRECTION_REVERSAL_OF: frozenset(
            {ReasonCode.REL_CORRECTION_REVERSAL}
        ),
        CanonicalOutcome.REL_RELATED_DISTINCT: frozenset(
            {ReasonCode.REL_RELATED_DISTINCT}
        ),
        CanonicalOutcome.REL_NO_ADEQUATE_PRIOR_MATCH: frozenset(
            {ReasonCode.REL_NO_ADEQUATE_PRIOR_MATCH}
        ),
        CanonicalOutcome.REL_UNCERTAIN: frozenset({ReasonCode.REL_UNCERTAIN}),
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


def _normalise_exact[T](operation: object, message: str, expected: type[T]) -> T:
    value = _normalise(operation, message)
    if type(value) is not expected:
        raise RelationshipContractError(f"{message}: forged value")
    return value


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
            or len(self.source_bindings) > _MAX_SOURCE_BINDINGS
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
        if (
            type(sources) is not list
            or not sources
            or len(sources) > _MAX_SOURCE_BINDINGS
        ):
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
    decision: CanonicalOutcome | None
    reason: StructuredReason | None
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
                type(self.decision) is not CanonicalOutcome
                or type(self.reason) is not StructuredReason
            ):
                raise RelationshipContractError("decision and reason must be exact")
            if (
                self.decision not in RELATIONSHIP_DECISION_REASON
                or self.reason.code not in RELATIONSHIP_DECISION_REASON[self.decision]
            ):
                raise RelationshipContractError("reason is outside the decision family")
            _score(self.score, "assessment score")
            _digest(self.evidence_digest, "evidence_digest")
            pairwise = self.decision is not CanonicalOutcome.REL_NO_ADEQUATE_PRIOR_MATCH
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
                "reason": None
                if self.reason is None
                else self.reason.canonical_value(),
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
        """Parse a structurally valid receipt without claiming verified replay.

        Call :func:`verify_relationship_assessment_replay` with the exact live
        Hypothesis Versions and canonical evidence before relying on policy
        semantics.
        """
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
                else CanonicalOutcome(item["decision"]),  # type: ignore[arg-type]
                None
                if item["reason"] is None
                else StructuredReason.from_mapping(item["reason"]),
                None
                if item["comparator"] is None
                else HypothesisVersionBinding.from_value(item["comparator"]),
                item["score"],  # type: ignore[arg-type]
                item["evidence_digest"],  # type: ignore[arg-type]
            ),
            "relationship assessment replay failed",
        )


@dataclass(frozen=True, slots=True)
class RetainedRelationshipDecisionReceipt(_NoEffect):
    """One exact retained assessment together with its verified evidence set."""

    assessment: RelationshipAssessment
    evidence: tuple[ComparatorEvidence, ...]

    def __post_init__(self) -> None:
        if type(self) is not RetainedRelationshipDecisionReceipt:
            raise RelationshipContractError(
                "retained relationship receipt requires the exact type"
            )
        if type(self.assessment) is not RelationshipAssessment:
            raise RelationshipContractError(
                "retained relationship receipt requires an exact complete assessment"
            )
        if type(self.evidence) is not tuple or len(self.evidence) > MAX_COMPARATORS or (
            any(type(item) is not ComparatorEvidence for item in self.evidence)
        ):
            raise RelationshipContractError(
                "retained relationship evidence must be a bounded exact tuple"
            )

        assessment = RelationshipAssessment.from_canonical_bytes(
            self.assessment.canonical_bytes
        )
        evidence = tuple(
            ComparatorEvidence.from_canonical_bytes(item.canonical_bytes)
            for item in self.evidence
        )
        if (
            assessment.status is not AssessmentStatus.COMPLETE
            or type(self.assessment.score) is not type(assessment.score)
            or type(self.assessment.evidence_digest)
            is not type(assessment.evidence_digest)
            or assessment != self.assessment
            or evidence != self.evidence
        ):
            raise RelationshipContractError(
                "retained relationship receipt values are not exact"
            )
        evidence_ids = tuple(item.comparator.version_id for item in evidence)
        manifest_ids = tuple(
            item.version_id for item in assessment.comparator_manifest.comparators
        )
        if evidence_ids != manifest_ids or evidence_ids != tuple(
            sorted(set(evidence_ids))
        ):
            raise RelationshipContractError(
                "retained relationship evidence is not complete canonical order"
            )
        evidence_bytes = _canonical(
            [item.canonical_value for item in evidence],
            "retained relationship evidence set",
        )
        if digest_bytes(evidence_bytes) != assessment.evidence_digest:
            raise RelationshipContractError(
                "retained relationship evidence-set identity differs"
            )
        replayed = assess_relationships(
            assessment.subject, assessment.comparator_manifest, evidence
        )
        if replayed != assessment or (
            replayed.canonical_bytes != assessment.canonical_bytes
            or replayed.canonical_digest != assessment.canonical_digest
        ):
            raise RelationshipContractError(
                "retained relationship policy replay differs"
            )


_FACADE_TOKEN = object()


class EventHypothesisRelationshipAuthority:
    """Narrow public facade over the private checked v22 authority."""

    __slots__ = ("__authority",)

    def __init__(self, token: object, authority: object) -> None:
        if token is not _FACADE_TOKEN:
            raise RelationshipContractError(
                "relationship authority facade requires the exact private authority"
            )
        self.__authority = authority

    def retain(self, *args: object, **kwargs: object) -> RelationshipAssessment:
        return _normalise(
            lambda: self.__authority.retain(*args, **kwargs),
            "relationship retention failed",
        )  # type: ignore[attr-defined,no-any-return]

    create_or_replay = retain

    def load(self, decision_id: str) -> RelationshipAssessment:
        return _normalise(
            lambda: self.__authority.load(decision_id),
            "relationship load failed",
        )  # type: ignore[attr-defined,no-any-return]

    def load_retained_receipt(
        self, assessment_digest: str
    ) -> RetainedRelationshipDecisionReceipt:
        """Read one verified historical receipt without a currentness claim."""

        return _normalise_exact(
            lambda: self.__authority.load_retained_receipt(assessment_digest),
            "retained relationship receipt load failed",
            RetainedRelationshipDecisionReceipt,
        )

    def history(self) -> tuple[RelationshipAssessment, ...]:
        return _normalise(self.__authority.history, "relationship history failed")  # type: ignore[attr-defined,no-any-return]

    def current(self, decision_id: str, *, proof: object) -> RelationshipAssessment:
        return _normalise(
            lambda: self.__authority.current(decision_id, proof=proof),
            "relationship currentness failed",
        )  # type: ignore[attr-defined,no-any-return]

    require_current = current

    def close(self) -> None:
        _normalise(self.__authority.close, "relationship authority close failed")  # type: ignore[attr-defined]

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def open_event_hypothesis_relationship_authority(
    database: str | Path,
    *,
    retrieval_authority: object,
    authenticator: object,
    authorizer: object,
    command_registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
    clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
    busy_timeout_ms: int = 5000,
) -> EventHypothesisRelationshipAuthority:
    """Open the checked v22 relationship authority."""
    from newsroom.authority.event_hypothesis_relationship_system import (
        open_event_hypothesis_relationship_authority_system,
    )

    authority = _normalise(
        lambda: open_event_hypothesis_relationship_authority_system(
            database,
            retrieval_authority=retrieval_authority,  # type: ignore[arg-type]
            authenticator=authenticator,
            authorizer=authorizer,
            command_registry=command_registry,
            payload_schemas=payload_schemas,
            clock=clock,
            busy_timeout_ms=busy_timeout_ms,
        ),
        "relationship authority open failed",
    )
    if type(authority) is not EventHypothesisRelationshipAuthority:
        raise RelationshipContractError(
            "relationship authority opener returned a forged facade"
        )
    return authority


def _compose_event_hypothesis_relationship_authority(
    authority: object,
) -> EventHypothesisRelationshipAuthority:
    """Private composition seam used only by the authority opener."""

    return EventHypothesisRelationshipAuthority(_FACADE_TOKEN, authority)


_READ_PORT_TOKEN = object()


class EventHypothesisRelationshipReadPort:
    """Narrow transaction-bound v22/v21 read seam for authority composition."""

    __slots__ = ("__authority",)

    def __init__(self, token: object, authority: object) -> None:
        if token is not _READ_PORT_TOKEN:
            raise RelationshipContractError(
                "relationship read port construction is authority-private"
            )
        self.__authority = authority

    def require_retained_receipt_in_transaction(
        self, assessment_digest: str
    ) -> RetainedRelationshipDecisionReceipt:
        return _normalise_exact(
            lambda: self.__authority.require_retained_receipt_in_transaction(
                assessment_digest
            ),
            "retained relationship receipt transaction read failed",
            RetainedRelationshipDecisionReceipt,
        )

    def require_retained_version_in_transaction(
        self, version_id: str
    ) -> EventHypothesisVersion:
        return _normalise_exact(
            lambda: self.__authority.require_retained_version_in_transaction(version_id),
            "retained Hypothesis Version transaction read failed",
            EventHypothesisVersion,
        )

    def require_current_version_in_transaction(
        self, version_id: str, *, proof: object
    ) -> EventHypothesisVersion:
        return _normalise_exact(
            lambda: self.__authority.require_current_version_in_transaction(
                version_id, proof=proof
            ),
            "current Hypothesis Version transaction read failed",
            EventHypothesisVersion,
        )


def _compose_event_hypothesis_relationship_read_port(
    authority: object,
) -> EventHypothesisRelationshipReadPort:
    """Private constructor used only by the checked authority implementation."""

    return EventHypothesisRelationshipReadPort(_READ_PORT_TOKEN, authority)


def _relationship_payload_canonicalizer(value: object) -> bytes:
    raw = _canonical(value, "relationship command payload")
    assessment = RelationshipAssessment.from_canonical_bytes(raw)
    if assessment.status is not AssessmentStatus.COMPLETE:
        raise RelationshipContractError(
            "relationship command payload must be a complete assessment"
        )
    return assessment.canonical_bytes


def relationship_payload_contract() -> PayloadSchemaContract:
    digest = "sha256:" + "0" * 64
    source = HypothesisSourceBinding(
        digest,
        digest,
        digest,
        digest,
        "00000000-0000-4000-8000-000000000001",
        digest,
        "00000000-0000-4000-8000-000000000002",
        digest,
    )
    subject = HypothesisVersionBinding(
        "00000000-0000-4000-8000-000000000003",
        "00000000-0000-5000-8000-000000000004",
        digest,
        digest,
        (source,),
    )
    golden = assess_relationships(
        subject, ComparatorSetManifest.complete(()), ()
    ).canonical_value
    return PayloadSchemaContract(
        schema_version=HYPOTHESIS_RELATIONSHIP_DECISION,
        payload_mode=PayloadMode.INLINE,
        contract_version=RELATIONSHIP_PAYLOAD_CONTRACT_VERSION,
        canonicalizer_implementation_version=(
            RELATIONSHIP_PAYLOAD_CANONICALIZER_VERSION
        ),
        canonicalizer=_relationship_payload_canonicalizer,
        golden_vectors=(
            PayloadGoldenVector(
                name="complete-no-match",
                input_identity="relationship-assessment:no-match",
                value=golden,
                expected_bytes=_relationship_payload_canonicalizer(golden),
            ),
        ),
    )


def relationship_command_definition() -> CommandDefinition:
    contract = relationship_payload_contract()
    return CommandDefinition(
        command_type=RELATIONSHIP_COMMAND_TYPE,
        definition_version=RELATIONSHIP_COMMAND_DEFINITION_VERSION,
        aggregate_type=RELATIONSHIP_AGGREGATE_TYPE,
        event_type=RELATIONSHIP_EVENT_TYPE,
        event_schema_version=1,
        payload_mode=PayloadMode.INLINE,
        payload_schema_version=contract.schema_version,
        payload_schema_contract_version=contract.contract_version,
        payload_schema_contract_digest=contract.contract_digest,
        payload_canonicalizer_version=contract.canonicalizer_implementation_version,
        trust_scope=TrustScope.ADMITTED,
        security_scope="authority.relationship",
        retention_scope="authority.audit",
        required_scope=RELATIONSHIP_REQUIRED_SCOPE,
        max_inline_bytes=MAX_RELATIONSHIP_CANONICAL_BYTES,
    )


def merge_relationship_authority_registries(
    command_registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
) -> tuple[CommandRegistry, PayloadSchemaRegistry]:
    definition = relationship_command_definition()
    definitions = list(command_registry.definitions())
    matches = [
        item
        for item in definitions
        if (item.command_type, item.definition_version)
        == (definition.command_type, definition.definition_version)
    ]
    if matches and matches[0].digest != definition.digest:
        raise RelationshipContractError("relationship command identity conflicts")
    if not matches:
        definitions.append(definition)
    current_commands = {
        item.command_type: (
            RELATIONSHIP_COMMAND_DEFINITION_VERSION
            if item.command_type == RELATIONSHIP_COMMAND_TYPE
            else command_registry.resolve(item.command_type).definition_version
        )
        for item in definitions
    }
    contract = relationship_payload_contract()
    contracts = list(payload_schemas.contracts())
    matches_schema = [
        item
        for item in contracts
        if (item.schema_version, item.payload_mode, item.contract_version)
        == (contract.schema_version, contract.payload_mode, contract.contract_version)
    ]
    if matches_schema and matches_schema[0].contract_digest != contract.contract_digest:
        raise RelationshipContractError("relationship payload identity conflicts")
    if not matches_schema:
        contracts.append(contract)
    current_schemas = {
        (item.schema_version, item.payload_mode): (
            RELATIONSHIP_PAYLOAD_CONTRACT_VERSION
            if item.schema_version == HYPOTHESIS_RELATIONSHIP_DECISION
            else payload_schemas.resolve(
                item.schema_version, item.payload_mode
            ).contract_version
        )
        for item in contracts
    }
    return (
        CommandRegistry(definitions, current_versions=current_commands),
        PayloadSchemaRegistry(contracts, current_versions=current_schemas),
    )


_PRECEDENCE = {
    CanonicalOutcome.REL_CORRECTION_REVERSAL_OF: 0,
    CanonicalOutcome.REL_DEVELOPMENT_OF: 1,
    CanonicalOutcome.REL_SAME_STATE: 2,
    CanonicalOutcome.REL_RELATED_DISTINCT: 3,
}


def _classify(
    evidence: ComparatorEvidence,
) -> CanonicalOutcome | None:
    if evidence.correction_reversal_score >= CORRECTION_REVERSAL_THRESHOLD:
        return CanonicalOutcome.REL_CORRECTION_REVERSAL_OF
    if evidence.development_score >= DEVELOPMENT_THRESHOLD:
        return CanonicalOutcome.REL_DEVELOPMENT_OF
    if evidence.same_state_score >= SAME_STATE_THRESHOLD:
        return CanonicalOutcome.REL_SAME_STATE
    if evidence.related_distinct_score >= RELATED_DISTINCT_THRESHOLD:
        return CanonicalOutcome.REL_RELATED_DISTINCT
    return None


_REASON_EXPLANATIONS = MappingProxyType(
    {
        CanonicalOutcome.REL_SAME_STATE: (
            "The exact comparator met the same-state policy threshold."
        ),
        CanonicalOutcome.REL_DEVELOPMENT_OF: (
            "The exact comparator met the development policy threshold."
        ),
        CanonicalOutcome.REL_CORRECTION_REVERSAL_OF: (
            "The exact comparator met the correction or reversal policy threshold."
        ),
        CanonicalOutcome.REL_RELATED_DISTINCT: (
            "The exact comparator met the related-distinct policy threshold."
        ),
        CanonicalOutcome.REL_NO_ADEQUATE_PRIOR_MATCH: (
            "The complete comparator set contained no adequate prior match."
        ),
        CanonicalOutcome.REL_UNCERTAIN: (
            "The best adequate comparator did not meet a semantic threshold."
        ),
    }
)


def _structured_reason(
    decision: CanonicalOutcome,
    *,
    subject: HypothesisVersionBinding,
    manifest: ComparatorSetManifest,
    evidence_digest: str,
    comparator: HypothesisVersionBinding | None,
) -> StructuredReason:
    references = [
        ReasonReference(
            reference_type="COMPARATOR_MANIFEST",
            identifier=manifest.canonical_digest,
            digest=manifest.canonical_digest,
        ),
        ReasonReference(
            reference_type="POLICY_EVIDENCE",
            identifier=decision.value,
            digest=evidence_digest,
        ),
        ReasonReference(
            reference_type="SUBJECT_VERSION",
            identifier=subject.version_id,
            digest=subject.version_digest,
        ),
    ]
    if comparator is not None:
        references.append(
            ReasonReference(
                reference_type="COMPARATOR_VERSION",
                identifier=comparator.version_id,
                digest=comparator.version_digest,
            )
        )
    references.sort(
        key=lambda item: (item.reference_type, item.identifier, item.digest or "")
    )
    reason_code = next(iter(RELATIONSHIP_DECISION_REASON[decision]))
    return _normalise(
        lambda: StructuredReason(
            code=reason_code,
            basis=ReasonBasisClass.DETERMINISTIC_POLICY,
            references=tuple(references),
            explanation=_REASON_EXPLANATIONS[decision],
        ),
        "relationship reason construction failed",
    )


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
    classified_evidence = tuple((item, _classify(item)) for item in ordered_evidence)
    adequate = tuple(
        (item, classification)
        for item, classification in classified_evidence
        if item.score >= ADEQUATE_MATCH_THRESHOLD or classification is not None
    )
    if not adequate:
        decision = CanonicalOutcome.REL_NO_ADEQUATE_PRIOR_MATCH
        return RelationshipAssessment(
            AssessmentStatus.COMPLETE,
            subject,
            comparator_manifest,
            decision,
            _structured_reason(
                decision,
                subject=subject,
                manifest=comparator_manifest,
                evidence_digest=evidence_digest,
                comparator=None,
            ),
            None,
            0,
            evidence_digest,
        )
    classified = tuple(
        (classification, item)
        for item, classification in adequate
        if classification is not None
    )
    if not classified:
        best = min(
            (item for item, _ in adequate),
            key=lambda item: (-item.score, item.comparator.version_id),
        )
        decision = CanonicalOutcome.REL_UNCERTAIN
        return RelationshipAssessment(
            AssessmentStatus.COMPLETE,
            subject,
            comparator_manifest,
            decision,
            _structured_reason(
                decision,
                subject=subject,
                manifest=comparator_manifest,
                evidence_digest=evidence_digest,
                comparator=best.comparator,
            ),
            best.comparator,
            best.score,
            evidence_digest,
        )
    decision, selected = min(
        classified,
        key=lambda item: (
            _PRECEDENCE[item[0]],
            -item[1].score,
            item[1].comparator.version_id,
        ),
    )
    return RelationshipAssessment(
        AssessmentStatus.COMPLETE,
        subject,
        comparator_manifest,
        decision,
        _structured_reason(
            decision,
            subject=subject,
            manifest=comparator_manifest,
            evidence_digest=evidence_digest,
            comparator=selected.comparator,
        ),
        selected.comparator,
        selected.score,
        evidence_digest,
    )


def verify_relationship_assessment_replay(
    raw: bytes,
    *,
    subject_version: EventHypothesisVersion,
    comparator_versions: tuple[EventHypothesisVersion, ...],
    evidence: tuple[bytes, ...],
) -> RelationshipAssessment:
    """Rebind exact Versions, rerun policy, and verify a canonical receipt.

    ``RelationshipAssessment.from_canonical_bytes`` is deliberately only a
    structural parser.  This verifier is the public semantic replay boundary:
    it reconstructs every binding from exact 6D1 Version values, parses each
    canonical policy input, reruns the deterministic policy, and requires both
    canonical bytes and digest to match.
    """
    parsed = RelationshipAssessment.from_canonical_bytes(raw)
    if type(subject_version) is not EventHypothesisVersion:
        raise RelationshipContractError(
            "verified replay subject requires an exact Hypothesis Version"
        )
    if (
        type(comparator_versions) is not tuple
        or len(comparator_versions) > MAX_COMPARATORS
        or any(type(item) is not EventHypothesisVersion for item in comparator_versions)
    ):
        raise RelationshipContractError(
            "verified replay comparators require a bounded exact Version tuple"
        )
    if (
        type(evidence) is not tuple
        or len(evidence) > MAX_COMPARATORS
        or any(type(item) is not bytes for item in evidence)
    ):
        raise RelationshipContractError(
            "verified replay evidence requires bounded canonical byte values"
        )

    rebound_subject = HypothesisVersionBinding.from_version(subject_version)
    rebound_comparators = tuple(
        sorted(
            (
                HypothesisVersionBinding.from_version(version)
                for version in comparator_versions
            ),
            key=lambda item: item.version_id,
        )
    )
    rebound_manifest = ComparatorSetManifest(
        parsed.comparator_manifest.status, rebound_comparators
    )
    if (
        rebound_subject != parsed.subject
        or rebound_manifest != parsed.comparator_manifest
    ):
        raise RelationshipContractError(
            "verified replay binding differs from the canonical receipt"
        )
    rebound_evidence = tuple(
        ComparatorEvidence.from_canonical_bytes(item) for item in evidence
    )
    replayed = assess_relationships(rebound_subject, rebound_manifest, rebound_evidence)
    if replayed.canonical_bytes != raw or replayed.canonical_digest != digest_bytes(
        raw
    ):
        raise RelationshipContractError(
            "verified replay differs from the canonical relationship assessment"
        )
    return replayed


__all__ = [
    "ADEQUATE_MATCH_THRESHOLD",
    "CORRECTION_REVERSAL_THRESHOLD",
    "DEVELOPMENT_THRESHOLD",
    "HYPOTHESIS_RELATIONSHIP_DECISION",
    "MAX_RELATIONSHIP_CANONICAL_BYTES",
    "RELATED_DISTINCT_THRESHOLD",
    "RELATIONSHIP_COMMAND_TYPE",
    "RELATIONSHIP_DECISION_REASON",
    "RELATIONSHIP_EVENT_TYPE",
    "SAME_STATE_THRESHOLD",
    "AssessmentStatus",
    "ComparatorEvidence",
    "ComparatorSetManifest",
    "EventHypothesisRelationshipAuthority",
    "EventHypothesisRelationshipReadPort",
    "HypothesisVersionBinding",
    "RelationshipAssessment",
    "RelationshipContractError",
    "RetainedRelationshipDecisionReceipt",
    "assess_relationships",
    "merge_relationship_authority_registries",
    "open_event_hypothesis_relationship_authority",
    "relationship_command_definition",
    "relationship_payload_contract",
    "verify_relationship_assessment_replay",
]
