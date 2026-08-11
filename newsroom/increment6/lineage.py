"""Pure append-only Event Hypothesis lineage contract.

The values in this module bind already-existing 6D1 Hypothesis Versions and
already-decided 6D2 relationship assessments.  They allocate no Version,
write no authority state, and grant no Candidate, evidence, publication,
model, provider, egress, or external-effect capability.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
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
from newsroom.increment6.hypotheses import EventHypothesisVersion
from newsroom.increment6.outcomes import CanonicalOutcome
from newsroom.increment6.relationships import (
    AssessmentStatus,
    ComparatorEvidence,
    ComparatorSetManifest,
    HypothesisVersionBinding,
    RelationshipAssessment,
    assess_relationships,
)

HYPOTHESIS_LINEAGE = "newsroom.increment6.hypothesis-lineage.v1"
LINEAGE_COMMAND_TYPE = "increment6.hypothesis-lineage.retain"
LINEAGE_AGGREGATE_TYPE = "event_hypothesis_lineage"
LINEAGE_EVENT_TYPE = "event_hypothesis_lineage_retained"
LINEAGE_COMMAND_DEFINITION_VERSION = "lineage-command-v1"
LINEAGE_PAYLOAD_CONTRACT_VERSION = "lineage-schema-v1"
LINEAGE_PAYLOAD_CANONICALIZER_VERSION = "lineage-canonical-json-v1"
LINEAGE_REQUIRED_SCOPE = "authority.hypothesis-lineage.retain"

HYPOTHESIS_CONSOLIDATION = "HYPOTHESIS_CONSOLIDATION"
HYPOTHESIS_SPLIT = "HYPOTHESIS_SPLIT"
HYPOTHESIS_REVERSAL_LINEAGE = "HYPOTHESIS_REVERSAL_LINEAGE"
MAX_LINEAGE_CANONICAL_BYTES = 1_048_576
MAX_LINEAGE_INPUTS = 32
MAX_LINEAGE_OUTPUTS = 32
MAX_LINEAGE_RELATIONSHIP_BINDINGS = 32
MAX_LINEAGE_COMPARATOR_EVIDENCE = 1_024
MAX_LINEAGE_REPLAY_RECEIPTS = 1_024
MAX_LINEAGE_REPLAY_NODES = 32_800

_NAMESPACE = uuid.UUID("ddbe290d-e859-53cb-870a-19c71238a66f")
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MAX_JSON_DEPTH = 16
_MAX_JSON_NODES = 32_768


class HypothesisLineageContractError(ValueError):
    """A lineage value, receipt, or replay failed closed."""


class HypothesisLineageKind(StrEnum):
    CONSOLIDATION = HYPOTHESIS_CONSOLIDATION
    SPLIT = HYPOTHESIS_SPLIT
    REVERSAL = HYPOTHESIS_REVERSAL_LINEAGE


class _NoEffect:
    authorises_authority = False
    authorises_persistence = False
    authorises_external_effect = False
    authorises_publication = False
    authorises_evidence = False
    authorises_egress = False
    authorises_relationship = False
    creates_candidate = False
    creates_hypothesis = False
    creates_version = False
    creates_relationship = False


def _normalise[T](operation: object, message: str) -> T:
    try:
        return operation()  # type: ignore[operator,no-any-return]
    except HypothesisLineageContractError:
        raise
    except Exception as exc:
        raise HypothesisLineageContractError(message) from exc


def _normalise_exact[T](operation: object, message: str, expected: type[T]) -> T:
    value = _normalise(operation, message)
    if type(value) is not expected:
        raise HypothesisLineageContractError(message)
    if expected is HypothesisLineageReceipt:
        return _normalise(
            lambda: HypothesisLineageReceipt.from_canonical_bytes(
                value.canonical_bytes
            ),
            message,
        )  # type: ignore[return-value,union-attr]
    return value


def _normalise_tuple[T](
    operation: object, message: str, expected: type[T]
) -> tuple[T, ...]:
    value = _normalise(operation, message)
    if type(value) is not tuple or any(type(item) is not expected for item in value):
        raise HypothesisLineageContractError(message)
    if expected is HypothesisLineageReceipt:
        return _normalise(
            lambda: tuple(
                HypothesisLineageReceipt.from_canonical_bytes(item.canonical_bytes)
                for item in value
            ),
            message,
        )  # type: ignore[return-value,union-attr]
    if expected is HypothesisLineageHead:
        return _normalise(
            lambda: tuple(
                HypothesisLineageHead(
                    HypothesisLineageNodeBinding.from_value(item.node.canonical_value),
                    item.generation,
                )
                for item in value
            ),
            message,
        )  # type: ignore[return-value,union-attr]
    return value


def _uuid(value: object, field: str) -> str:
    if type(value) is not str or _UUID.fullmatch(value) is None:
        raise HypothesisLineageContractError(f"{field} must be a canonical UUID")
    return value


def _digest(value: object, field: str) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise HypothesisLineageContractError(
            f"{field} must be a canonical SHA-256 digest"
        )
    return value


def _generation(value: object, field: str = "expected_generation") -> int:
    if type(value) is not int or not 0 <= value < MAX_SAFE_INTEGER:
        raise HypothesisLineageContractError(
            f"{field} must be an exact bounded non-negative integer"
        )
    return value


def _exact(value: object, fields: set[str], field: str) -> dict[str, object]:
    if type(value) is not dict:
        raise HypothesisLineageContractError(f"{field} fields are not exact")
    try:
        if set(value) != fields:
            raise HypothesisLineageContractError(f"{field} fields are not exact")
    except HypothesisLineageContractError:
        raise
    except Exception as exc:
        raise HypothesisLineageContractError(f"{field} fields are not exact") from exc
    return value


def _canonical(value: object, field: str) -> bytes:
    try:
        raw = canonical_json_bytes(value)
    except HypothesisLineageContractError:
        raise
    except Exception as exc:
        raise HypothesisLineageContractError(
            f"{field} cannot be canonicalised"
        ) from exc
    if not raw or len(raw) > MAX_LINEAGE_CANONICAL_BYTES:
        raise HypothesisLineageContractError(
            f"{field} exceeds the canonical byte bound"
        )
    return raw


def _decode(raw: bytes) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_LINEAGE_CANONICAL_BYTES:
        raise HypothesisLineageContractError(
            "lineage receipt requires bounded immutable bytes"
        )

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise HypothesisLineageContractError(
                    "lineage receipt contains a duplicate key"
                )
            result[key] = value
        return result

    def integer(text: str) -> int:
        if len(text.lstrip("-")) > 16:
            raise HypothesisLineageContractError(
                "lineage receipt integer exceeds bounds"
            )
        value = int(text)
        if not -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
            raise HypothesisLineageContractError(
                "lineage receipt integer exceeds bounds"
            )
        return value

    def unsupported(_: str) -> float:
        raise HypothesisLineageContractError(
            "lineage receipt contains an unsupported number"
        )

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique,
            parse_int=integer,
            parse_float=unsupported,
            parse_constant=unsupported,
        )
    except HypothesisLineageContractError:
        raise
    except Exception as exc:
        raise HypothesisLineageContractError(
            "lineage receipt is not valid UTF-8 JSON"
        ) from exc
    pending: list[tuple[object, int]] = [(value, 1)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if depth > _MAX_JSON_DEPTH or nodes > _MAX_JSON_NODES:
            raise HypothesisLineageContractError(
                "lineage receipt exceeds structural bounds"
            )
        if type(item) is dict:
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        elif type(item) not in (str, int, bool, type(None)):
            raise HypothesisLineageContractError(
                "lineage receipt contains an unsupported value"
            )
    if type(value) is not dict:
        raise HypothesisLineageContractError("lineage receipt must be an object")
    try:
        if canonical_json_bytes(value) != raw:
            raise HypothesisLineageContractError(
                "lineage receipt is not canonical JSON"
            )
    except HypothesisLineageContractError:
        raise
    except Exception as exc:
        raise HypothesisLineageContractError(
            "lineage receipt cannot be normalised"
        ) from exc
    return value


@dataclass(frozen=True, slots=True)
class HypothesisLineageNodeBinding(_NoEffect):
    hypothesis_id: str
    version_id: str
    version_digest: str

    def __post_init__(self) -> None:
        if type(self) is not HypothesisLineageNodeBinding:
            raise HypothesisLineageContractError("node binding requires the exact type")
        _uuid(self.hypothesis_id, "hypothesis_id")
        _uuid(self.version_id, "version_id")
        _digest(self.version_digest, "version_digest")

    @classmethod
    def from_version(cls, version: EventHypothesisVersion) -> Self:
        if type(version) is not EventHypothesisVersion:
            raise HypothesisLineageContractError(
                "node binding requires an exact Hypothesis Version"
            )

        def bind() -> Self:
            raw = version.canonical_bytes
            if EventHypothesisVersion.from_canonical_bytes(raw) != version:
                raise HypothesisLineageContractError(
                    "Hypothesis Version differs from its canonical replay"
                )
            return cls(version.hypothesis_id, version.version_id, digest_bytes(raw))

        return _normalise(bind, "Hypothesis Version cannot be bound")

    @property
    def canonical_value(self) -> dict[str, object]:
        return _normalise(
            lambda: {
                "hypothesis_id": self.hypothesis_id,
                "version_id": self.version_id,
                "version_digest": self.version_digest,
            },
            "node binding cannot be represented",
        )

    @classmethod
    def from_value(cls, value: object) -> Self:
        item = _exact(
            value,
            {"hypothesis_id", "version_id", "version_digest"},
            "node binding",
        )
        return _normalise(
            lambda: cls(
                item["hypothesis_id"],  # type: ignore[arg-type]
                item["version_id"],  # type: ignore[arg-type]
                item["version_digest"],  # type: ignore[arg-type]
            ),
            "node binding replay failed",
        )


def _node_key(node: HypothesisLineageNodeBinding) -> tuple[str, str, str]:
    return node.hypothesis_id, node.version_id, node.version_digest


@dataclass(frozen=True, slots=True)
class HypothesisLineageEvidenceBinding(_NoEffect):
    evidence_digest: str
    subject_version_id: str
    comparator_version_id: str
    classification: CanonicalOutcome

    def __post_init__(self) -> None:
        if type(self) is not HypothesisLineageEvidenceBinding:
            raise HypothesisLineageContractError(
                "evidence binding requires the exact type"
            )
        _digest(self.evidence_digest, "evidence_digest")
        _uuid(self.subject_version_id, "evidence subject_version_id")
        _uuid(self.comparator_version_id, "evidence comparator_version_id")
        if self.subject_version_id == self.comparator_version_id:
            raise HypothesisLineageContractError("evidence cannot contain a self edge")
        if type(self.classification) is not CanonicalOutcome:
            raise HypothesisLineageContractError(
                "evidence classification must be exact"
            )

    @property
    def canonical_value(self) -> dict[str, object]:
        return _normalise(
            lambda: {
                "evidence_digest": self.evidence_digest,
                "subject_version_id": self.subject_version_id,
                "comparator_version_id": self.comparator_version_id,
                "classification": self.classification.value,
            },
            "evidence binding cannot be represented",
        )

    @classmethod
    def from_value(cls, value: object) -> Self:
        item = _exact(
            value,
            {
                "evidence_digest",
                "subject_version_id",
                "comparator_version_id",
                "classification",
            },
            "evidence binding",
        )
        return _normalise(
            lambda: cls(
                item["evidence_digest"],  # type: ignore[arg-type]
                item["subject_version_id"],  # type: ignore[arg-type]
                item["comparator_version_id"],  # type: ignore[arg-type]
                CanonicalOutcome(item["classification"]),  # type: ignore[arg-type]
            ),
            "evidence binding replay failed",
        )


@dataclass(frozen=True, slots=True)
class HypothesisLineageRelationshipBinding(_NoEffect):
    assessment_digest: str
    outcome: CanonicalOutcome
    subject: HypothesisLineageNodeBinding
    comparator_manifest_digest: str
    evidence_set_digest: str
    evidence: tuple[HypothesisLineageEvidenceBinding, ...]

    def __post_init__(self) -> None:
        if type(self) is not HypothesisLineageRelationshipBinding:
            raise HypothesisLineageContractError(
                "relationship binding requires the exact type"
            )
        _digest(self.assessment_digest, "assessment_digest")
        _digest(self.comparator_manifest_digest, "comparator_manifest_digest")
        _digest(self.evidence_set_digest, "evidence_set_digest")
        if type(self.outcome) is not CanonicalOutcome:
            raise HypothesisLineageContractError("relationship outcome must be exact")
        if type(self.subject) is not HypothesisLineageNodeBinding:
            raise HypothesisLineageContractError(
                "relationship subject must be an exact node binding"
            )
        if (
            type(self.evidence) is not tuple
            or not self.evidence
            or len(self.evidence) > MAX_LINEAGE_OUTPUTS
            or any(
                type(item) is not HypothesisLineageEvidenceBinding
                for item in self.evidence
            )
        ):
            raise HypothesisLineageContractError(
                "relationship evidence must be a non-empty bounded exact tuple"
            )
        comparator_ids = tuple(item.comparator_version_id for item in self.evidence)
        if comparator_ids != tuple(sorted(set(comparator_ids))):
            raise HypothesisLineageContractError(
                "relationship evidence must be comparator-sorted and unique"
            )
        if any(
            item.subject_version_id != self.subject.version_id for item in self.evidence
        ):
            raise HypothesisLineageContractError(
                "relationship evidence subject differs from the decision subject"
            )

    @classmethod
    def from_assessment(
        cls,
        assessment: RelationshipAssessment,
        evidence: tuple[ComparatorEvidence, ...],
    ) -> Self:
        return HypothesisLineageRelationshipProof.from_assessment(
            assessment, evidence
        ).binding

    @property
    def canonical_value(self) -> dict[str, object]:
        return _normalise(
            lambda: {
                "assessment_digest": self.assessment_digest,
                "outcome": self.outcome.value,
                "subject": self.subject.canonical_value,
                "comparator_manifest_digest": self.comparator_manifest_digest,
                "evidence_set_digest": self.evidence_set_digest,
                "evidence": [item.canonical_value for item in self.evidence],
            },
            "relationship binding cannot be represented",
        )

    @classmethod
    def from_value(cls, value: object) -> Self:
        item = _exact(
            value,
            {
                "assessment_digest",
                "outcome",
                "subject",
                "comparator_manifest_digest",
                "evidence_set_digest",
                "evidence",
            },
            "relationship binding",
        )
        raw_evidence = item["evidence"]
        if type(raw_evidence) is not list or not 1 <= len(raw_evidence) <= 32:
            raise HypothesisLineageContractError(
                "relationship evidence must be a bounded array"
            )
        return _normalise(
            lambda: cls(
                item["assessment_digest"],  # type: ignore[arg-type]
                CanonicalOutcome(item["outcome"]),  # type: ignore[arg-type]
                HypothesisLineageNodeBinding.from_value(item["subject"]),
                item["comparator_manifest_digest"],  # type: ignore[arg-type]
                item["evidence_set_digest"],  # type: ignore[arg-type]
                tuple(
                    HypothesisLineageEvidenceBinding.from_value(entry)
                    for entry in raw_evidence
                ),
            ),
            "relationship binding replay failed",
        )


def _relationship_key(
    binding: HypothesisLineageRelationshipBinding,
) -> tuple[str, str]:
    return binding.subject.version_id, binding.assessment_digest


def _verified_relationship_binding(
    assessment: RelationshipAssessment,
    evidence: tuple[ComparatorEvidence, ...],
) -> HypothesisLineageRelationshipBinding:
    if type(assessment) is not RelationshipAssessment:
        raise HypothesisLineageContractError(
            "relationship proof requires an exact Relationship Assessment"
        )
    if (
        type(evidence) is not tuple
        or not evidence
        or len(evidence) > MAX_LINEAGE_OUTPUTS
        or any(type(item) is not ComparatorEvidence for item in evidence)
    ):
        raise HypothesisLineageContractError(
            "relationship proof requires bounded exact Comparator Evidence"
        )
    if (
        assessment.status is not AssessmentStatus.COMPLETE
        or type(assessment.decision) is not CanonicalOutcome
        or type(assessment.subject) is not HypothesisVersionBinding
        or assessment.evidence_digest is None
    ):
        raise HypothesisLineageContractError(
            "relationship proof requires a complete decision"
        )
    assessment_raw = assessment.canonical_bytes
    if RelationshipAssessment.from_canonical_bytes(assessment_raw) != assessment:
        raise HypothesisLineageContractError(
            "Relationship Assessment differs from its canonical replay"
        )
    ordered = tuple(sorted(evidence, key=lambda item: item.comparator.version_id))
    compact: list[HypothesisLineageEvidenceBinding] = []
    for item in ordered:
        raw = item.canonical_bytes
        if ComparatorEvidence.from_canonical_bytes(raw) != item:
            raise HypothesisLineageContractError(
                "Comparator Evidence differs from its canonical replay"
            )
        classified = assess_relationships(
            item.subject,
            ComparatorSetManifest.complete((item.comparator,)),
            (item,),
        )
        if type(classified.decision) is not CanonicalOutcome:
            raise HypothesisLineageContractError(
                "Comparator Evidence has no deterministic classification"
            )
        compact.append(
            HypothesisLineageEvidenceBinding(
                digest_bytes(raw),
                item.subject.version_id,
                item.comparator.version_id,
                classified.decision,
            )
        )
    replayed = assess_relationships(
        assessment.subject, assessment.comparator_manifest, ordered
    )
    if replayed.canonical_bytes != assessment_raw:
        raise HypothesisLineageContractError(
            "relationship proof differs from the public D2 policy replay"
        )
    return HypothesisLineageRelationshipBinding(
        digest_bytes(assessment_raw),
        assessment.decision,
        HypothesisLineageNodeBinding(
            assessment.subject.hypothesis_id,
            assessment.subject.version_id,
            assessment.subject.version_digest,
        ),
        assessment.comparator_manifest_digest,
        assessment.evidence_digest,
        tuple(compact),
    )


class HypothesisLineageRelationshipProof(_NoEffect):
    """Exact D2 producer proof; instances are created only by the factory."""

    __slots__ = ("__assessment", "__evidence")

    def __init__(self) -> None:
        raise HypothesisLineageContractError(
            "relationship proof must be created from exact D2 producers"
        )

    @classmethod
    def from_assessment(
        cls,
        assessment: RelationshipAssessment,
        evidence: tuple[ComparatorEvidence, ...],
    ) -> Self:
        def build() -> Self:
            _verified_relationship_binding(assessment, evidence)
            value = object.__new__(cls)
            object.__setattr__(
                value, "_HypothesisLineageRelationshipProof__assessment", assessment
            )
            object.__setattr__(
                value,
                "_HypothesisLineageRelationshipProof__evidence",
                tuple(sorted(evidence, key=lambda item: item.comparator.version_id)),
            )
            return value

        return _normalise(build, "relationship proof construction failed")

    @property
    def assessment(self) -> RelationshipAssessment:
        return _normalise(
            lambda: self.__assessment, "relationship proof assessment is unavailable"
        )

    @property
    def evidence(self) -> tuple[ComparatorEvidence, ...]:
        return _normalise(
            lambda: self.__evidence, "relationship proof evidence is unavailable"
        )

    @property
    def binding(self) -> HypothesisLineageRelationshipBinding:
        return _normalise(
            lambda: _verified_relationship_binding(self.assessment, self.evidence),
            "relationship proof verification failed",
        )


@dataclass(frozen=True, slots=True)
class HypothesisLineageTarget(_NoEffect):
    lineage_id: str
    lineage_digest: str

    def __post_init__(self) -> None:
        if type(self) is not HypothesisLineageTarget:
            raise HypothesisLineageContractError(
                "lineage target requires the exact type"
            )
        _uuid(self.lineage_id, "target lineage_id")
        _digest(self.lineage_digest, "target lineage_digest")

    @property
    def canonical_value(self) -> dict[str, object]:
        return _normalise(
            lambda: {
                "lineage_id": self.lineage_id,
                "lineage_digest": self.lineage_digest,
            },
            "lineage target cannot be represented",
        )

    @classmethod
    def from_value(cls, value: object) -> Self:
        item = _exact(value, {"lineage_id", "lineage_digest"}, "lineage target")
        return _normalise(
            lambda: cls(
                item["lineage_id"],  # type: ignore[arg-type]
                item["lineage_digest"],  # type: ignore[arg-type]
            ),
            "lineage target replay failed",
        )


def _versions(values: object, field: str) -> tuple[HypothesisLineageNodeBinding, ...]:
    if type(values) is not tuple or any(
        type(item) is not EventHypothesisVersion for item in values
    ):
        raise HypothesisLineageContractError(
            f"{field} must be an exact tuple of Hypothesis Versions"
        )
    return _normalise(
        lambda: tuple(
            sorted(
                (HypothesisLineageNodeBinding.from_version(item) for item in values),
                key=_node_key,
            )
        ),
        f"{field} Versions cannot be bound",
    )


def _relationship_proofs(
    values: object,
) -> tuple[HypothesisLineageRelationshipBinding, ...]:
    if type(values) is not tuple or any(
        type(item) is not HypothesisLineageRelationshipProof for item in values
    ):
        raise HypothesisLineageContractError(
            "relationship_proofs must be an exact tuple of producer proofs"
        )
    return _normalise(
        lambda: tuple(
            sorted(
                (item.binding for item in values),
                key=_relationship_key,
            )
        ),
        "relationship proofs cannot be bound",
    )


@dataclass(frozen=True, slots=True)
class HypothesisLineageReceipt(_NoEffect):
    lineage_id: str
    kind: HypothesisLineageKind
    expected_generation: int
    inputs: tuple[HypothesisLineageNodeBinding, ...]
    outputs: tuple[HypothesisLineageNodeBinding, ...]
    relationships: tuple[HypothesisLineageRelationshipBinding, ...]
    reversal_target: HypothesisLineageTarget | None = None

    def __post_init__(self) -> None:
        if type(self) is not HypothesisLineageReceipt:
            raise HypothesisLineageContractError(
                "lineage receipt requires the exact type"
            )
        _normalise(self._validate, "lineage receipt construction failed")

    def _validate(self) -> None:
        _uuid(self.lineage_id, "lineage_id")
        if type(self.kind) is not HypothesisLineageKind:
            raise HypothesisLineageContractError("lineage kind must be exact")
        _generation(self.expected_generation)
        for field, values, limit in (
            ("inputs", self.inputs, MAX_LINEAGE_INPUTS),
            ("outputs", self.outputs, MAX_LINEAGE_OUTPUTS),
        ):
            if (
                type(values) is not tuple
                or not values
                or len(values) > limit
                or any(
                    type(item) is not HypothesisLineageNodeBinding for item in values
                )
            ):
                raise HypothesisLineageContractError(
                    f"{field} must be a non-empty bounded exact tuple"
                )
            keys = tuple(_node_key(item) for item in values)
            if keys != tuple(sorted(set(keys))):
                raise HypothesisLineageContractError(
                    f"{field} must be sorted and unique"
                )
            version_ids = tuple(item.version_id for item in values)
            if len(version_ids) != len(set(version_ids)):
                raise HypothesisLineageContractError(
                    f"{field} cannot rebind one Version identity"
                )
            hypothesis_ids = tuple(item.hypothesis_id for item in values)
            if len(hypothesis_ids) != len(set(hypothesis_ids)):
                raise HypothesisLineageContractError(
                    f"{field} must bind distinct Hypothesis identities"
                )
        if any(
            left.version_id == right.version_id
            for left in self.inputs
            for right in self.outputs
        ):
            raise HypothesisLineageContractError("lineage cannot contain a self edge")
        if (
            type(self.relationships) is not tuple
            or len(self.relationships) > MAX_LINEAGE_RELATIONSHIP_BINDINGS
            or any(
                type(item) is not HypothesisLineageRelationshipBinding
                for item in self.relationships
            )
        ):
            raise HypothesisLineageContractError(
                "relationships must be a bounded exact tuple"
            )
        relationship_keys = tuple(
            _relationship_key(item) for item in self.relationships
        )
        if relationship_keys != tuple(sorted(set(relationship_keys))):
            raise HypothesisLineageContractError(
                "relationships must be sorted and unique"
            )
        if len({item.assessment_digest for item in self.relationships}) != len(
            self.relationships
        ):
            raise HypothesisLineageContractError(
                "one relationship assessment cannot be reused"
            )
        if len({item.subject.version_id for item in self.relationships}) != len(
            self.relationships
        ):
            raise HypothesisLineageContractError(
                "one relationship decision per unique subject is required"
            )
        if (
            sum(len(item.evidence) for item in self.relationships)
            > MAX_LINEAGE_COMPARATOR_EVIDENCE
        ):
            raise HypothesisLineageContractError(
                "compact comparator evidence bound exceeded"
            )
        if self.kind is HypothesisLineageKind.REVERSAL:
            if type(self.reversal_target) is not HypothesisLineageTarget:
                raise HypothesisLineageContractError(
                    "reversal requires an exact lineage target"
                )
        elif self.reversal_target is not None:
            raise HypothesisLineageContractError(
                "only reversal may contain a lineage target"
            )
        expected_id = self._derived_lineage_id
        if self.lineage_id != expected_id:
            raise HypothesisLineageContractError(
                "lineage_id differs from its semantic identity"
            )
        self._validate_shape_and_basis()
        _ = self.canonical_bytes

    @property
    def _semantic_value(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "expected_generation": self.expected_generation,
            "inputs": [item.canonical_value for item in self.inputs],
            "reversal_target": (
                None
                if self.reversal_target is None
                else self.reversal_target.canonical_value
            ),
        }

    @property
    def _derived_lineage_id(self) -> str:
        return _normalise(
            lambda: str(
                uuid.uuid5(
                    _NAMESPACE, canonical_json_bytes(self._semantic_value).decode()
                )
            ),
            "lineage identity cannot be derived",
        )

    def _validate_shape_and_basis(self) -> None:
        actual = {item.subject.version_id: item for item in self.relationships}
        required: dict[str, tuple[set[str], CanonicalOutcome]] = {}
        if self.kind is HypothesisLineageKind.CONSOLIDATION:
            if len(self.inputs) < 2 or len(self.outputs) != 1:
                raise HypothesisLineageContractError(
                    "consolidation requires two to 32 inputs and one output"
                )
            output = self.outputs[0]
            required = {
                output.version_id: (
                    {item.version_id for item in self.inputs},
                    CanonicalOutcome.REL_SAME_STATE,
                )
            }
        elif self.kind is HypothesisLineageKind.SPLIT:
            if len(self.inputs) != 1 or not 2 <= len(self.outputs) <= 32:
                raise HypothesisLineageContractError(
                    "split requires one input and two to 32 outputs"
                )
            source = self.inputs[0]
            required = {
                output.version_id: (
                    {
                        source.version_id,
                        *(item.version_id for item in self.outputs if item != output),
                    },
                    CanonicalOutcome.REL_RELATED_DISTINCT,
                )
                for output in self.outputs
            }
        else:
            if not self.inputs or not self.outputs:
                raise HypothesisLineageContractError(
                    "reversal requires non-empty inputs and outputs"
                )
            required = {
                output.version_id: (
                    {item.version_id for item in self.inputs},
                    CanonicalOutcome.REL_CORRECTION_REVERSAL_OF,
                )
                for output in self.outputs
            }
        if set(actual) != set(required):
            raise HypothesisLineageContractError(
                "relationship basis has missing or extra endpoints"
            )
        for subject_id, (comparators, outcome) in required.items():
            binding = actual[subject_id]
            if binding.outcome is not outcome:
                raise HypothesisLineageContractError(
                    "relationship basis has the wrong outcome"
                )
            subject = next(
                item for item in self.outputs if item.version_id == subject_id
            )
            if binding.subject != subject:
                raise HypothesisLineageContractError(
                    "relationship subject differs from the exact lineage output"
                )
            if {item.comparator_version_id for item in binding.evidence} != comparators:
                raise HypothesisLineageContractError(
                    "relationship basis has missing or extra comparator endpoints"
                )
            if any(item.classification is not outcome for item in binding.evidence):
                raise HypothesisLineageContractError(
                    "relationship evidence has the wrong classification"
                )

    @classmethod
    def _build(
        cls,
        kind: HypothesisLineageKind,
        expected_generation: int,
        inputs: tuple[HypothesisLineageNodeBinding, ...],
        outputs: tuple[HypothesisLineageNodeBinding, ...],
        relationships: tuple[HypothesisLineageRelationshipBinding, ...],
        reversal_target: HypothesisLineageTarget | None = None,
    ) -> Self:
        semantic = {
            "kind": kind.value,
            "expected_generation": _generation(expected_generation),
            "inputs": [item.canonical_value for item in inputs],
            "reversal_target": (
                None if reversal_target is None else reversal_target.canonical_value
            ),
        }
        lineage_id = _normalise(
            lambda: str(
                uuid.uuid5(_NAMESPACE, canonical_json_bytes(semantic).decode())
            ),
            "lineage identity cannot be derived",
        )
        return _normalise(
            lambda: cls(
                lineage_id,
                kind,
                expected_generation,
                inputs,
                outputs,
                relationships,
                reversal_target,
            ),
            "lineage receipt construction failed",
        )

    @classmethod
    def consolidation(
        cls,
        *,
        expected_generation: int,
        inputs: tuple[EventHypothesisVersion, ...],
        output: EventHypothesisVersion,
        relationship_proofs: tuple[HypothesisLineageRelationshipProof, ...],
    ) -> Self:
        if type(output) is not EventHypothesisVersion:
            raise HypothesisLineageContractError(
                "consolidation output must be an exact Hypothesis Version"
            )
        return cls._build(
            HypothesisLineageKind.CONSOLIDATION,
            expected_generation,
            _versions(inputs, "inputs"),
            _versions((output,), "outputs"),
            _relationship_proofs(relationship_proofs),
        )

    @classmethod
    def split(
        cls,
        *,
        expected_generation: int,
        source: EventHypothesisVersion,
        outputs: tuple[EventHypothesisVersion, ...],
        relationship_proofs: tuple[HypothesisLineageRelationshipProof, ...],
    ) -> Self:
        if type(source) is not EventHypothesisVersion:
            raise HypothesisLineageContractError(
                "split source must be an exact Hypothesis Version"
            )
        return cls._build(
            HypothesisLineageKind.SPLIT,
            expected_generation,
            _versions((source,), "inputs"),
            _versions(outputs, "outputs"),
            _relationship_proofs(relationship_proofs),
        )

    @classmethod
    def reversal(
        cls,
        *,
        expected_generation: int,
        target: HypothesisLineageReceipt,
        outputs: tuple[EventHypothesisVersion, ...],
        relationship_proofs: tuple[HypothesisLineageRelationshipProof, ...],
    ) -> Self:
        def build() -> Self:
            if type(target) is not HypothesisLineageReceipt:
                raise HypothesisLineageContractError(
                    "reversal target must be an exact lineage receipt"
                )
            if target.kind is HypothesisLineageKind.REVERSAL:
                raise HypothesisLineageContractError(
                    "a reversal cannot target a reversal"
                )
            return cls._build(
                HypothesisLineageKind.REVERSAL,
                expected_generation,
                target.outputs,
                _versions(outputs, "outputs"),
                _relationship_proofs(relationship_proofs),
                HypothesisLineageTarget(target.lineage_id, target.canonical_digest),
            )

        return _normalise(build, "reversal construction failed")

    @property
    def canonical_value(self) -> dict[str, object]:
        return _normalise(
            lambda: {
                "schema_version": HYPOTHESIS_LINEAGE,
                "lineage_id": self.lineage_id,
                "kind": self.kind.value,
                "expected_generation": self.expected_generation,
                "inputs": [item.canonical_value for item in self.inputs],
                "outputs": [item.canonical_value for item in self.outputs],
                "relationships": [item.canonical_value for item in self.relationships],
                "reversal_target": (
                    None
                    if self.reversal_target is None
                    else self.reversal_target.canonical_value
                ),
            },
            "lineage receipt cannot be represented",
        )

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical(self.canonical_value, "lineage receipt")

    @property
    def canonical_digest(self) -> str:
        return _normalise(
            lambda: digest_bytes(self.canonical_bytes),
            "lineage receipt cannot be digested",
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        """Parse structural bytes without granting semantic producer trust."""

        fields = {
            "schema_version",
            "lineage_id",
            "kind",
            "expected_generation",
            "inputs",
            "outputs",
            "relationships",
            "reversal_target",
        }
        item = _exact(_decode(raw), fields, "lineage receipt")
        if item["schema_version"] != HYPOTHESIS_LINEAGE:
            raise HypothesisLineageContractError(
                "lineage receipt schema is unsupported"
            )
        for field, limit in (
            ("inputs", MAX_LINEAGE_INPUTS),
            ("outputs", MAX_LINEAGE_OUTPUTS),
            ("relationships", MAX_LINEAGE_RELATIONSHIP_BINDINGS),
        ):
            value = item[field]
            if type(value) is not list or len(value) > limit:
                raise HypothesisLineageContractError(f"{field} must be a bounded array")
        return _normalise(
            lambda: cls(
                item["lineage_id"],  # type: ignore[arg-type]
                HypothesisLineageKind(item["kind"]),  # type: ignore[arg-type]
                item["expected_generation"],  # type: ignore[arg-type]
                tuple(
                    HypothesisLineageNodeBinding.from_value(value)
                    for value in item["inputs"]  # type: ignore[union-attr]
                ),
                tuple(
                    HypothesisLineageNodeBinding.from_value(value)
                    for value in item["outputs"]  # type: ignore[union-attr]
                ),
                tuple(
                    HypothesisLineageRelationshipBinding.from_value(value)
                    for value in item["relationships"]  # type: ignore[union-attr]
                ),
                (
                    None
                    if item["reversal_target"] is None
                    else HypothesisLineageTarget.from_value(item["reversal_target"])
                ),
            ),
            "lineage receipt replay failed",
        )


@dataclass(frozen=True, slots=True)
class HypothesisLineageHead(_NoEffect):
    node: HypothesisLineageNodeBinding
    generation: int

    def __post_init__(self) -> None:
        if type(self) is not HypothesisLineageHead:
            raise HypothesisLineageContractError("lineage head requires the exact type")
        if type(self.node) is not HypothesisLineageNodeBinding:
            raise HypothesisLineageContractError("lineage head node must be exact")
        _generation(self.generation, "generation")

    @classmethod
    def from_version(cls, version: EventHypothesisVersion, generation: int = 0) -> Self:
        return _normalise(
            lambda: cls(HypothesisLineageNodeBinding.from_version(version), generation),
            "lineage head cannot be bound",
        )


@dataclass(frozen=True, slots=True)
class HypothesisLineageEdge(_NoEffect):
    lineage_id: str
    kind: HypothesisLineageKind
    predecessor: HypothesisLineageNodeBinding
    successor: HypothesisLineageNodeBinding

    def __post_init__(self) -> None:
        if type(self) is not HypothesisLineageEdge:
            raise HypothesisLineageContractError("lineage edge requires the exact type")
        _uuid(self.lineage_id, "lineage_id")
        if type(self.kind) is not HypothesisLineageKind:
            raise HypothesisLineageContractError("lineage edge kind must be exact")
        if (
            type(self.predecessor) is not HypothesisLineageNodeBinding
            or type(self.successor) is not HypothesisLineageNodeBinding
        ):
            raise HypothesisLineageContractError("lineage edge nodes must be exact")
        if self.predecessor.version_id == self.successor.version_id:
            raise HypothesisLineageContractError("lineage edge cannot be a self edge")


@dataclass(frozen=True, slots=True)
class HypothesisLineageReplay(_NoEffect):
    history: tuple[HypothesisLineageReceipt, ...]
    active_heads: tuple[HypothesisLineageHead, ...]
    edges: tuple[HypothesisLineageEdge, ...]
    consumed: tuple[HypothesisLineageNodeBinding, ...]

    def __post_init__(self) -> None:
        if type(self) is not HypothesisLineageReplay:
            raise HypothesisLineageContractError(
                "lineage replay requires the exact type"
            )
        if (
            type(self.history) is not tuple
            or any(type(item) is not HypothesisLineageReceipt for item in self.history)
            or type(self.active_heads) is not tuple
            or any(
                type(item) is not HypothesisLineageHead for item in self.active_heads
            )
            or type(self.edges) is not tuple
            or any(type(item) is not HypothesisLineageEdge for item in self.edges)
            or type(self.consumed) is not tuple
            or any(
                type(item) is not HypothesisLineageNodeBinding for item in self.consumed
            )
        ):
            raise HypothesisLineageContractError("lineage replay values must be exact")


def verify_hypothesis_lineage_receipt(
    receipt: HypothesisLineageReceipt,
    *,
    versions: tuple[EventHypothesisVersion, ...],
    relationship_proofs: tuple[HypothesisLineageRelationshipProof, ...],
    reversal_target: HypothesisLineageReceipt | None,
) -> HypothesisLineageReceipt:
    """Rebind a structural receipt to exact D1 and replayed D2 producers."""

    def verify() -> HypothesisLineageReceipt:
        if type(receipt) is not HypothesisLineageReceipt:
            raise HypothesisLineageContractError(
                "semantic verification requires an exact lineage receipt"
            )
        expected_nodes = tuple(
            sorted({*receipt.inputs, *receipt.outputs}, key=_node_key)
        )
        producer_nodes = _versions(versions, "semantic producer")
        if producer_nodes != expected_nodes:
            raise HypothesisLineageContractError(
                "lineage nodes differ from exact Hypothesis Version producers"
            )
        if _relationship_proofs(relationship_proofs) != receipt.relationships:
            raise HypothesisLineageContractError(
                "lineage decisions differ from exact D2 producer proofs"
            )
        node_by_version_id = {item.version_id: item for item in producer_nodes}

        def require_endpoint(binding: HypothesisVersionBinding) -> None:
            expected = node_by_version_id.get(binding.version_id)
            actual = HypothesisLineageNodeBinding(
                binding.hypothesis_id,
                binding.version_id,
                binding.version_digest,
            )
            if expected != actual:
                raise HypothesisLineageContractError(
                    "D2 proof endpoint differs from its exact D1 producer"
                )

        for proof in relationship_proofs:
            assessment = proof.assessment
            require_endpoint(assessment.subject)
            for comparator in assessment.comparator_manifest.comparators:
                require_endpoint(comparator)
            for evidence in proof.evidence:
                require_endpoint(evidence.subject)
                require_endpoint(evidence.comparator)

        if receipt.kind is HypothesisLineageKind.REVERSAL:
            if type(reversal_target) is not HypothesisLineageReceipt:
                raise HypothesisLineageContractError(
                    "reversal semantic verification requires the exact target receipt"
                )
            target_raw = reversal_target.canonical_bytes
            if (
                HypothesisLineageReceipt.from_canonical_bytes(target_raw)
                != reversal_target
                or reversal_target.kind is HypothesisLineageKind.REVERSAL
                or receipt.reversal_target is None
                or receipt.reversal_target.lineage_id != reversal_target.lineage_id
                or receipt.reversal_target.lineage_digest != digest_bytes(target_raw)
                or receipt.inputs != reversal_target.outputs
            ):
                raise HypothesisLineageContractError(
                    "reversal target receipt is missing, changed, or inconsistent"
                )
            if sorted(item.hypothesis_id for item in receipt.outputs) != sorted(
                item.hypothesis_id for item in reversal_target.inputs
            ):
                raise HypothesisLineageContractError(
                    "reversal outputs do not restore target input identities one-to-one"
                )
        elif reversal_target is not None:
            raise HypothesisLineageContractError(
                "non-reversal semantic verification cannot receive a target"
            )
        return receipt

    return _normalise(verify, "lineage semantic verification failed")


def replay_hypothesis_lineage(
    receipts: tuple[HypothesisLineageReceipt, ...],
    *,
    initial_heads: tuple[HypothesisLineageHead, ...],
    versions: tuple[EventHypothesisVersion, ...],
    relationship_proofs: tuple[HypothesisLineageRelationshipProof, ...],
) -> HypothesisLineageReplay:
    """Replay bounded receipts without mutating a Version or an authority store."""

    def replay() -> HypothesisLineageReplay:
        if (
            type(receipts) is not tuple
            or len(receipts) > MAX_LINEAGE_REPLAY_RECEIPTS
            or any(type(item) is not HypothesisLineageReceipt for item in receipts)
        ):
            raise HypothesisLineageContractError(
                "receipts must be a bounded exact tuple"
            )
        if (
            type(initial_heads) is not tuple
            or len(initial_heads) > MAX_LINEAGE_REPLAY_NODES
            or any(type(item) is not HypothesisLineageHead for item in initial_heads)
        ):
            raise HypothesisLineageContractError(
                "initial_heads must be a bounded exact tuple"
            )
        if any(head.generation != 0 for head in initial_heads):
            raise HypothesisLineageContractError(
                "lineage replay is full-rebuild-only from generation-zero roots"
            )
        all_nodes = tuple(
            sorted(
                {
                    *(head.node for head in initial_heads),
                    *(
                        node
                        for receipt in receipts
                        for node in (*receipt.inputs, *receipt.outputs)
                    ),
                },
                key=_node_key,
            )
        )
        rebound_versions = _versions(versions, "replay producer")
        if (
            len(rebound_versions) > MAX_LINEAGE_REPLAY_NODES
            or rebound_versions != all_nodes
        ):
            raise HypothesisLineageContractError(
                "replay Versions differ from the complete exact producer set"
            )
        if (
            type(relationship_proofs) is not tuple
            or len(relationship_proofs)
            > MAX_LINEAGE_REPLAY_RECEIPTS * MAX_LINEAGE_RELATIONSHIP_BINDINGS
            or any(
                type(item) is not HypothesisLineageRelationshipProof
                for item in relationship_proofs
            )
        ):
            raise HypothesisLineageContractError(
                "relationship_proofs must be a bounded exact tuple"
            )
        proof_by_digest: dict[str, HypothesisLineageRelationshipProof] = {}
        for proof in relationship_proofs:
            binding = proof.binding
            if binding.assessment_digest in proof_by_digest:
                raise HypothesisLineageContractError(
                    "relationship proofs contain a duplicate assessment"
                )
            proof_by_digest[binding.assessment_digest] = proof
        expected_proof_digests = {
            binding.assessment_digest
            for receipt in receipts
            for binding in receipt.relationships
        }
        if set(proof_by_digest) != expected_proof_digests:
            raise HypothesisLineageContractError(
                "relationship proofs differ from the complete receipt set"
            )
        version_by_id = {version.version_id: version for version in versions}
        if len(version_by_id) != len(versions):
            raise HypothesisLineageContractError(
                "replay producers contain a duplicate Version identity"
            )
        verified_receipts: dict[str, HypothesisLineageReceipt] = {}
        for receipt in receipts:
            receipt_versions = tuple(
                version_by_id[node.version_id]
                for node in (*receipt.inputs, *receipt.outputs)
            )
            receipt_proofs = tuple(
                proof_by_digest[binding.assessment_digest]
                for binding in receipt.relationships
            )
            target = (
                None
                if receipt.reversal_target is None
                else verified_receipts.get(receipt.reversal_target.lineage_id)
            )
            verify_hypothesis_lineage_receipt(
                receipt,
                versions=receipt_versions,
                relationship_proofs=receipt_proofs,
                reversal_target=target,
            )
            verified_receipts.setdefault(receipt.lineage_id, receipt)

        active: dict[str, HypothesisLineageHead] = {}
        node_by_id: dict[str, HypothesisLineageNodeBinding] = {}
        for head in initial_heads:
            version_id = head.node.version_id
            hypothesis_id = head.node.hypothesis_id
            if hypothesis_id in active:
                raise HypothesisLineageContractError(
                    "initial heads contain a duplicate active Hypothesis"
                )
            active[hypothesis_id] = head
            node_by_id[version_id] = head.node
        history: list[HypothesisLineageReceipt] = []
        receipt_by_id: dict[str, HypothesisLineageReceipt] = {}
        edges: list[HypothesisLineageEdge] = []
        consumed: dict[str, HypothesisLineageNodeBinding] = {}
        for receipt in receipts:
            retained = receipt_by_id.get(receipt.lineage_id)
            if retained is not None:
                if retained.canonical_bytes == receipt.canonical_bytes:
                    continue
                raise HypothesisLineageContractError(
                    "semantic lineage identity has divergent canonical bytes"
                )
            if len(history) >= MAX_LINEAGE_REPLAY_RECEIPTS:
                raise HypothesisLineageContractError("lineage receipt bound exceeded")
            target: HypothesisLineageReceipt | None = None
            if receipt.kind is HypothesisLineageKind.REVERSAL:
                target_binding = receipt.reversal_target
                if target_binding is None:
                    raise HypothesisLineageContractError("reversal target is absent")
                target = receipt_by_id.get(target_binding.lineage_id)
                if (
                    target is None
                    or target.kind is HypothesisLineageKind.REVERSAL
                    or target.canonical_digest != target_binding.lineage_digest
                ):
                    raise HypothesisLineageContractError(
                        "reversal target is missing, changed, or itself a reversal"
                    )
            input_heads: list[HypothesisLineageHead] = []
            for node in receipt.inputs:
                head = active.get(node.hypothesis_id)
                if head is None:
                    if node.version_id in consumed:
                        raise HypothesisLineageContractError(
                            "a consumed lineage node cannot be reused"
                        )
                    raise HypothesisLineageContractError(
                        "lineage input is not an active head"
                    )
                if head.node != node:
                    raise HypothesisLineageContractError(
                        "lineage input differs from the exact active head"
                    )
                input_heads.append(head)
            generations = {head.generation for head in input_heads}
            if generations != {receipt.expected_generation}:
                raise HypothesisLineageContractError(
                    "lineage inputs are mixed-generation or stale"
                )
            if receipt.kind is HypothesisLineageKind.REVERSAL:
                assert target is not None
                if receipt.inputs != target.outputs:
                    raise HypothesisLineageContractError(
                        "reversal inputs differ from the target outputs"
                    )
            for node in receipt.outputs:
                if node.hypothesis_id in active and node.hypothesis_id not in {
                    item.hypothesis_id for item in receipt.inputs
                }:
                    raise HypothesisLineageContractError(
                        "lineage output Hypothesis is already active"
                    )
                prior = node_by_id.get(node.version_id)
                if prior is not None:
                    if prior != node:
                        raise HypothesisLineageContractError(
                            "one Version identity has divergent bindings"
                        )
                    raise HypothesisLineageContractError(
                        "lineage output Version has already been seen"
                    )
            if len(node_by_id) + len(receipt.outputs) > MAX_LINEAGE_REPLAY_NODES:
                raise HypothesisLineageContractError("lineage node bound exceeded")
            for node in receipt.inputs:
                consumed[node.version_id] = node
                del active[node.hypothesis_id]
            next_generation = receipt.expected_generation + 1
            for node in receipt.outputs:
                node_by_id[node.version_id] = node
                active[node.hypothesis_id] = HypothesisLineageHead(
                    node, next_generation
                )
            edges.extend(
                HypothesisLineageEdge(receipt.lineage_id, receipt.kind, source, output)
                for source in receipt.inputs
                for output in receipt.outputs
            )
            history.append(receipt)
            receipt_by_id[receipt.lineage_id] = receipt
        return HypothesisLineageReplay(
            tuple(history),
            tuple(sorted(active.values(), key=lambda item: _node_key(item.node))),
            tuple(edges),
            tuple(sorted(consumed.values(), key=_node_key)),
        )

    return _normalise(replay, "lineage replay failed")


def _lineage_payload_canonicalizer(value: object) -> bytes:
    raw = _canonical(value, "lineage command payload")
    return HypothesisLineageReceipt.from_canonical_bytes(raw).canonical_bytes


def _lineage_golden_receipt() -> HypothesisLineageReceipt:
    digest = "sha256:" + "0" * 64
    inputs = (
        HypothesisLineageNodeBinding(
            "00000000-0000-4000-8000-000000000001",
            "00000000-0000-5000-8000-000000000011",
            digest,
        ),
        HypothesisLineageNodeBinding(
            "00000000-0000-4000-8000-000000000002",
            "00000000-0000-5000-8000-000000000012",
            digest,
        ),
    )
    output = HypothesisLineageNodeBinding(
        "00000000-0000-4000-8000-000000000003",
        "00000000-0000-5000-8000-000000000013",
        digest,
    )
    evidence = tuple(
        HypothesisLineageEvidenceBinding(
            digest, output.version_id, item.version_id, CanonicalOutcome.REL_SAME_STATE
        )
        for item in inputs
    )
    relationship = HypothesisLineageRelationshipBinding(
        digest, CanonicalOutcome.REL_SAME_STATE, output, digest, digest, evidence
    )
    return HypothesisLineageReceipt._build(
        HypothesisLineageKind.CONSOLIDATION, 0, inputs, (output,), (relationship,)
    )


def lineage_payload_contract() -> PayloadSchemaContract:
    golden = _lineage_golden_receipt()
    return PayloadSchemaContract(
        schema_version=HYPOTHESIS_LINEAGE,
        payload_mode=PayloadMode.INLINE,
        contract_version=LINEAGE_PAYLOAD_CONTRACT_VERSION,
        canonicalizer_implementation_version=LINEAGE_PAYLOAD_CANONICALIZER_VERSION,
        canonicalizer=_lineage_payload_canonicalizer,
        golden_vectors=(
            PayloadGoldenVector(
                "consolidation",
                "lineage:consolidation",
                golden.canonical_value,
                golden.canonical_bytes,
            ),
        ),
    )


def lineage_command_definition() -> CommandDefinition:
    contract = lineage_payload_contract()
    return CommandDefinition(
        command_type=LINEAGE_COMMAND_TYPE,
        definition_version=LINEAGE_COMMAND_DEFINITION_VERSION,
        aggregate_type=LINEAGE_AGGREGATE_TYPE,
        event_type=LINEAGE_EVENT_TYPE,
        event_schema_version=1,
        payload_mode=PayloadMode.INLINE,
        payload_schema_version=contract.schema_version,
        payload_schema_contract_version=contract.contract_version,
        payload_schema_contract_digest=contract.contract_digest,
        payload_canonicalizer_version=contract.canonicalizer_implementation_version,
        trust_scope=TrustScope.ADMITTED,
        security_scope="authority.hypothesis-lineage",
        retention_scope="authority.audit",
        required_scope=LINEAGE_REQUIRED_SCOPE,
        max_inline_bytes=MAX_LINEAGE_CANONICAL_BYTES,
    )


def merge_lineage_authority_registries(
    command_registry: CommandRegistry, payload_schemas: PayloadSchemaRegistry
) -> tuple[CommandRegistry, PayloadSchemaRegistry]:
    definition = lineage_command_definition()
    definitions = list(command_registry.definitions())
    matches = [
        item
        for item in definitions
        if (item.command_type, item.definition_version)
        == (definition.command_type, definition.definition_version)
    ]
    if matches and matches[0].digest != definition.digest:
        raise HypothesisLineageContractError("lineage command identity conflicts")
    if not matches:
        definitions.append(definition)
    current_commands = {
        item.command_type: (
            LINEAGE_COMMAND_DEFINITION_VERSION
            if item.command_type == LINEAGE_COMMAND_TYPE
            else command_registry.resolve(item.command_type).definition_version
        )
        for item in definitions
    }
    contract = lineage_payload_contract()
    contracts = list(payload_schemas.contracts())
    schema_matches = [
        item
        for item in contracts
        if (item.schema_version, item.payload_mode, item.contract_version)
        == (contract.schema_version, contract.payload_mode, contract.contract_version)
    ]
    if schema_matches and schema_matches[0].contract_digest != contract.contract_digest:
        raise HypothesisLineageContractError("lineage payload identity conflicts")
    if not schema_matches:
        contracts.append(contract)
    current_schemas = {
        (item.schema_version, item.payload_mode): (
            LINEAGE_PAYLOAD_CONTRACT_VERSION
            if item.schema_version == HYPOTHESIS_LINEAGE
            else payload_schemas.resolve(
                item.schema_version, item.payload_mode
            ).contract_version
        )
        for item in contracts
    }
    return CommandRegistry(
        definitions, current_versions=current_commands
    ), PayloadSchemaRegistry(contracts, current_versions=current_schemas)


_FACADE_TOKEN = object()


class EventHypothesisLineageAuthority:
    """Narrow public facade over checked v23 lineage authority."""

    __slots__ = ("__authority",)

    def __init__(self, token: object, authority: object) -> None:
        if token is not _FACADE_TOKEN:
            raise HypothesisLineageContractError(
                "lineage authority construction is private"
            )
        self.__authority = authority

    def retain(
        self, receipt_bytes: bytes, *, proof: object
    ) -> HypothesisLineageReceipt:
        return _normalise_exact(
            lambda: self.__authority.retain(receipt_bytes, proof=proof),
            "lineage retention failed",
            HypothesisLineageReceipt,
        )  # type: ignore[attr-defined,no-any-return]

    create_or_replay = retain

    def load(self, lineage_id: str) -> HypothesisLineageReceipt:
        return _normalise_exact(
            lambda: self.__authority.load(lineage_id),
            "lineage load failed",
            HypothesisLineageReceipt,
        )  # type: ignore[attr-defined,no-any-return]

    def history(self) -> tuple[HypothesisLineageReceipt, ...]:
        return _normalise_tuple(
            self.__authority.history, "lineage history failed", HypothesisLineageReceipt
        )  # type: ignore[attr-defined,no-any-return]

    def current_heads(self, *, proof: object) -> tuple[HypothesisLineageHead, ...]:
        return _normalise_tuple(
            lambda: self.__authority.current_heads(proof=proof),
            "lineage current heads failed",
            HypothesisLineageHead,
        )  # type: ignore[attr-defined,no-any-return]

    def close(self) -> None:
        _normalise(self.__authority.close, "lineage authority close failed")  # type: ignore[attr-defined]

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _compose_event_hypothesis_lineage_authority(
    authority: object,
) -> EventHypothesisLineageAuthority:
    return EventHypothesisLineageAuthority(_FACADE_TOKEN, authority)


def open_event_hypothesis_lineage_authority(
    database: str | Path,
    *,
    retrieval_authority: object,
    authenticator: object,
    authorizer: object,
    command_registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
    clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
    busy_timeout_ms: int = 5000,
) -> EventHypothesisLineageAuthority:
    from newsroom.authority.event_hypothesis_lineage_system import (
        open_event_hypothesis_lineage_authority_system,
    )

    authority = _normalise(
        lambda: open_event_hypothesis_lineage_authority_system(
            database,
            retrieval_authority=retrieval_authority,
            authenticator=authenticator,
            authorizer=authorizer,
            command_registry=command_registry,
            payload_schemas=payload_schemas,
            clock=clock,
            busy_timeout_ms=busy_timeout_ms,
        ),
        "lineage authority open failed",
    )
    if type(authority) is not EventHypothesisLineageAuthority:
        raise HypothesisLineageContractError(
            "lineage authority opener returned a forged facade"
        )
    return authority


__all__ = [
    "HYPOTHESIS_CONSOLIDATION",
    "HYPOTHESIS_LINEAGE",
    "HYPOTHESIS_REVERSAL_LINEAGE",
    "HYPOTHESIS_SPLIT",
    "LINEAGE_AGGREGATE_TYPE",
    "LINEAGE_COMMAND_TYPE",
    "LINEAGE_EVENT_TYPE",
    "LINEAGE_REQUIRED_SCOPE",
    "MAX_LINEAGE_CANONICAL_BYTES",
    "MAX_LINEAGE_COMPARATOR_EVIDENCE",
    "MAX_LINEAGE_INPUTS",
    "MAX_LINEAGE_OUTPUTS",
    "MAX_LINEAGE_RELATIONSHIP_BINDINGS",
    "MAX_LINEAGE_REPLAY_NODES",
    "MAX_LINEAGE_REPLAY_RECEIPTS",
    "EventHypothesisLineageAuthority",
    "HypothesisLineageContractError",
    "HypothesisLineageEdge",
    "HypothesisLineageEvidenceBinding",
    "HypothesisLineageHead",
    "HypothesisLineageKind",
    "HypothesisLineageNodeBinding",
    "HypothesisLineageReceipt",
    "HypothesisLineageRelationshipBinding",
    "HypothesisLineageRelationshipProof",
    "HypothesisLineageReplay",
    "HypothesisLineageTarget",
    "lineage_command_definition",
    "lineage_payload_contract",
    "merge_lineage_authority_registries",
    "open_event_hypothesis_lineage_authority",
    "replay_hypothesis_lineage",
    "verify_hypothesis_lineage_receipt",
]
