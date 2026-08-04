"""Immutable branch provenance, hit, and exclusion records."""

from __future__ import annotations

from dataclasses import dataclass

from newsroom.authority.canonical import digest_canonical
from newsroom.authority.types import TrustScope, UtcTimestamp

from ._retrieval_validation import (
    Increment5RetrievalContractError, bounded_int, bounded_text,
    require_digest, require_mapping, require_sequence, validate_canonical_score,
)
from .contract_types import RetrievalMode
from .retrieval_outcomes import BranchExclusionReason, BranchMatchSignal


@dataclass(frozen=True, slots=True)
class BranchProvenanceRef:
    kind: str
    identity: str
    digest: str
    recorded_at: UtcTimestamp

    def __post_init__(self) -> None:
        bounded_text(self.kind, field="provenance kind", maximum_bytes=128)
        bounded_text(self.identity, field="provenance identity", maximum_bytes=256)
        require_digest(self.digest, field="provenance digest")
        if not isinstance(self.recorded_at, UtcTimestamp):
            raise Increment5RetrievalContractError("provenance time must be typed")

    def canonical_value(self) -> dict[str, object]:
        return {"kind": self.kind, "identity": self.identity,
                "digest": self.digest, "recorded_at": self.recorded_at.to_text()}

    @classmethod
    def from_value(cls, value: object) -> "BranchProvenanceRef":
        item = require_mapping(value, field="branch provenance")
        return cls(str(item["kind"]), str(item["identity"]), str(item["digest"]),
                   UtcTimestamp.parse(str(item["recorded_at"])))


@dataclass(frozen=True, slots=True)
class BranchHit:
    mode: RetrievalMode
    rank: int
    raw_score: str
    match_signal: BranchMatchSignal
    result_key: str
    dependency_root_id: str
    source_kind: str
    source_identity: str
    source_identity_digest: str
    trust_scope: TrustScope
    passage_id: str | None
    provenance: tuple[BranchProvenanceRef, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.mode, RetrievalMode):
            raise Increment5RetrievalContractError("hit mode must be typed")
        bounded_int(self.rank, field="hit rank", minimum=1, maximum=8)
        score = float(validate_canonical_score(self.raw_score))
        if self.mode is RetrievalMode.EXACT and score != 1.0:
            raise Increment5RetrievalContractError("exact score must equal one")
        if self.mode is RetrievalMode.VECTOR and not 0 <= score <= 1:
            raise Increment5RetrievalContractError("vector score must be in [0,1]")
        if self.mode is RetrievalMode.ADMITTED_GRAPH and not 0 < score <= 1:
            raise Increment5RetrievalContractError("graph score must be in (0,1]")
        if self.mode is RetrievalMode.FULL_TEXT and score < 0:
            raise Increment5RetrievalContractError("full-text score cannot be negative")
        if not isinstance(self.match_signal, BranchMatchSignal):
            raise Increment5RetrievalContractError("match signal must be typed")
        for field, value in (("result key", self.result_key),
                             ("dependency root", self.dependency_root_id),
                             ("source kind", self.source_kind),
                             ("source identity", self.source_identity)):
            bounded_text(value, field=field, maximum_bytes=256)
        require_digest(self.source_identity_digest, field="source identity digest")
        if self.trust_scope not in {TrustScope.OBSERVED, TrustScope.ADMITTED}:
            raise Increment5RetrievalContractError("hit trust scope is not permitted")
        if self.passage_id is not None:
            bounded_text(self.passage_id, field="passage identity", maximum_bytes=128)
        if not isinstance(self.provenance, tuple) or not self.provenance or not all(
            isinstance(item, BranchProvenanceRef) for item in self.provenance
        ):
            raise Increment5RetrievalContractError("hit provenance must be typed")
        keys = tuple((p.kind, p.identity, p.digest) for p in self.provenance)
        if keys != tuple(sorted(set(keys))):
            raise Increment5RetrievalContractError("hit provenance must be sorted")

    @property
    def hit_digest(self) -> str:
        return digest_canonical(self.canonical_value())

    def canonical_value(self) -> dict[str, object]:
        return {
            "mode": self.mode.value, "rank": self.rank, "raw_score": self.raw_score,
            "match_signal": self.match_signal.value, "result_key": self.result_key,
            "dependency_root_id": self.dependency_root_id, "source_kind": self.source_kind,
            "source_identity": self.source_identity,
            "source_identity_digest": self.source_identity_digest,
            "trust_scope": self.trust_scope.value, "passage_id": self.passage_id,
            "provenance": [p.canonical_value() for p in self.provenance],
        }

    @classmethod
    def from_value(cls, value: object) -> "BranchHit":
        item = require_mapping(value, field="branch hit")
        return cls(
            mode=RetrievalMode(item["mode"]), rank=item["rank"], raw_score=str(item["raw_score"]),
            match_signal=BranchMatchSignal(item["match_signal"]),
            result_key=str(item["result_key"]), dependency_root_id=str(item["dependency_root_id"]),
            source_kind=str(item["source_kind"]), source_identity=str(item["source_identity"]),
            source_identity_digest=str(item["source_identity_digest"]),
            trust_scope=TrustScope(item["trust_scope"]),
            passage_id=None if item.get("passage_id") is None else str(item["passage_id"]),
            provenance=tuple(BranchProvenanceRef.from_value(p) for p in
                             require_sequence(item["provenance"], field="hit provenance")),
        )


@dataclass(frozen=True, slots=True)
class BranchExclusion:
    reason: BranchExclusionReason
    source_kind: str
    source_identity: str
    source_identity_digest: str
    detail_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.reason, BranchExclusionReason):
            raise Increment5RetrievalContractError("exclusion reason must be typed")
        bounded_text(self.source_kind, field="exclusion source kind", maximum_bytes=128)
        bounded_text(self.source_identity, field="exclusion source identity", maximum_bytes=256)
        require_digest(self.source_identity_digest, field="exclusion identity digest")
        require_digest(self.detail_digest, field="exclusion detail digest")

    def canonical_value(self) -> dict[str, str]:
        return {"reason": self.reason.value, "source_kind": self.source_kind,
                "source_identity": self.source_identity,
                "source_identity_digest": self.source_identity_digest,
                "detail_digest": self.detail_digest}

    @classmethod
    def from_value(cls, value: object) -> "BranchExclusion":
        item = require_mapping(value, field="branch exclusion")
        return cls(BranchExclusionReason(item["reason"]), str(item["source_kind"]),
                   str(item["source_identity"]), str(item["source_identity_digest"]),
                   str(item["detail_digest"]))


__all__ = ["BranchExclusion", "BranchHit", "BranchProvenanceRef"]
