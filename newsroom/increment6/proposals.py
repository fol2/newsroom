"""Strict, provider-independent Triage Proposal contract for Increment 6C1.

A proposal is retained untrusted worker output.  Its digest is content identity,
not approval: parsing or retaining one creates no Hypothesis or Candidate and
grants no evidence, publication, operational, or other editorial authority.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)


PROPOSAL_SCHEMA_VERSION = "newsroom.increment6.triage-proposal.v1"
PROBABILITY_SCALE = 1_000_000
MAX_EVIDENCE_REFERENCES = 32
MAX_RATIONALE_BYTES = 4_096
MAX_CITATION_SPAN_BYTES = 262_144

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,255}\Z")
_DECIMAL = re.compile(r"(?:0\.[0-9]{6}|1\.000000)\Z")


class ProposalContractError(ValueError):
    """Untrusted proposal bytes do not satisfy the exact v1 contract."""


class ProposalRoute(StrEnum):
    CREATE_HYPOTHESIS = "CREATE_HYPOTHESIS"
    ASSOCIATE_HYPOTHESIS = "ASSOCIATE_HYPOTHESIS"
    HOLD = "HOLD"
    WATCH = "WATCH"
    DISMISS = "DISMISS"


class FixtureWorkerKind(StrEnum):
    FAKE = "FAKE"
    REPLAY = "REPLAY"


def _exact_keys(
    value: object, expected: set[str], field: str
) -> Mapping[str, object]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ProposalContractError(f"{field} keys are not exact")
    return value


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ProposalContractError(f"{field} must be a canonical SHA-256 digest")
    try:
        return validate_sha256_digest(value, field=field)
    except CanonicalizationError as exc:
        raise ProposalContractError(str(exc)) from exc


def _text(value: object, field: str, maximum_bytes: int = 256) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > maximum_bytes
    ):
        raise ProposalContractError(f"{field} must be bounded canonical text")
    return value


def _token(value: object, field: str) -> str:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise ProposalContractError(f"{field} must be a bounded canonical token")
    return value


def _uuid(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ProposalContractError(f"{field} must be a canonical UUID")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ProposalContractError(f"{field} must be a canonical UUID") from exc
    if str(parsed) != value:
        raise ProposalContractError(f"{field} must be a canonical UUID")
    return value


def _uint(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProposalContractError(f"{field} must be a non-negative integer")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for name, item in pairs:
        if name in value:
            raise ProposalContractError(f"duplicate object name: {name}")
        value[name] = item
    return value


def _decode_canonical(raw: bytes) -> dict[str, object]:
    if not isinstance(raw, bytes):
        raise ProposalContractError("proposal input must be immutable bytes")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ProposalContractError(f"unsupported JSON constant: {value}")
            ),
        )
    except ProposalContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProposalContractError("proposal is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ProposalContractError("proposal document must be an object")
    try:
        expected = canonical_json_bytes(value)
    except CanonicalizationError as exc:
        raise ProposalContractError("proposal is outside canonical JSON") from exc
    if raw != expected:
        raise ProposalContractError("proposal is not exact canonical JSON")
    return value


def _content_identity(proposal: Mapping[str, object]) -> str:
    """Scope content identity to this exact contract version."""

    return digest_bytes(
        canonical_json_bytes(
            {
                "schema_version": PROPOSAL_SCHEMA_VERSION,
                "proposal": proposal,
            }
        )
    )


@dataclass(frozen=True, slots=True)
class FixedProbability:
    """A [0, 1] value represented by both exact integer and decimal forms."""

    decimal: str
    millionths: int

    @classmethod
    def from_value(cls, value: object, field: str) -> "FixedProbability":
        item = _exact_keys(value, {"decimal", "millionths"}, field)
        millionths = item["millionths"]
        if (
            isinstance(millionths, bool)
            or not isinstance(millionths, int)
            or not 0 <= millionths <= PROBABILITY_SCALE
        ):
            raise ProposalContractError(
                f"{field}.millionths must be an integer from 0 to 1000000"
            )
        decimal = item["decimal"]
        if not isinstance(decimal, str) or _DECIMAL.fullmatch(decimal) is None:
            raise ProposalContractError(
                f"{field}.decimal must use exact six-place [0,1] text"
            )
        whole = millionths // PROBABILITY_SCALE
        fraction = millionths % PROBABILITY_SCALE
        expected = f"{whole}.{fraction:06d}"
        if decimal != expected:
            raise ProposalContractError(
                f"{field} decimal and integer representations differ"
            )
        return cls(decimal=decimal, millionths=millionths)

    def canonical_value(self) -> dict[str, object]:
        return {"decimal": self.decimal, "millionths": self.millionths}


@dataclass(frozen=True, slots=True)
class RetrievalContextBinding:
    context_id: str
    context_digest: str
    contract_digest: str

    @classmethod
    def from_value(cls, value: object) -> "RetrievalContextBinding":
        item = _exact_keys(
            value,
            {"context_id", "context_digest", "contract_digest"},
            "retrieval_context_binding",
        )
        return cls(
            context_id=_uuid(item["context_id"], "context_id"),
            context_digest=_digest(item["context_digest"], "context_digest"),
            contract_digest=_digest(item["contract_digest"], "contract_digest"),
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "context_id": self.context_id,
            "context_digest": self.context_digest,
            "contract_digest": self.contract_digest,
        }


@dataclass(frozen=True, slots=True)
class WorkerAttemptBinding:
    attempt_id: str
    attempt_digest: str
    worker_kind: FixtureWorkerKind
    worker_version: str
    input_digest: str
    retrieval_context_digest: str

    @classmethod
    def from_value(cls, value: object) -> "WorkerAttemptBinding":
        item = _exact_keys(
            value,
            {
                "attempt_id",
                "attempt_digest",
                "worker_kind",
                "worker_version",
                "input_digest",
                "retrieval_context_digest",
            },
            "worker_attempt_binding",
        )
        try:
            worker_kind = FixtureWorkerKind(item["worker_kind"])
        except (TypeError, ValueError) as exc:
            raise ProposalContractError(
                "worker_kind must be FAKE or REPLAY"
            ) from exc
        return cls(
            attempt_id=_token(item["attempt_id"], "attempt_id"),
            attempt_digest=_digest(item["attempt_digest"], "attempt_digest"),
            worker_kind=worker_kind,
            worker_version=_token(item["worker_version"], "worker_version"),
            input_digest=_digest(item["input_digest"], "input_digest"),
            retrieval_context_digest=_digest(
                item["retrieval_context_digest"],
                "worker_retrieval_context_digest",
            ),
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "attempt_id": self.attempt_id,
            "attempt_digest": self.attempt_digest,
            "worker_kind": self.worker_kind.value,
            "worker_version": self.worker_version,
            "input_digest": self.input_digest,
            "retrieval_context_digest": self.retrieval_context_digest,
        }


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    citation_id: str
    context_item_digest: str
    passage_id: str
    passage_text_digest: str
    byte_start: int
    byte_end: int
    quote_digest: str

    @classmethod
    def from_value(cls, value: object) -> "EvidenceReference":
        item = _exact_keys(
            value,
            {
                "citation_id",
                "context_item_digest",
                "passage_id",
                "passage_text_digest",
                "byte_start",
                "byte_end",
                "quote_digest",
            },
            "evidence reference",
        )
        byte_start = _uint(item["byte_start"], "citation byte_start")
        byte_end = _uint(item["byte_end"], "citation byte_end")
        if (
            byte_end <= byte_start
            or byte_end - byte_start > MAX_CITATION_SPAN_BYTES
        ):
            raise ProposalContractError("citation byte range is invalid or unbounded")
        return cls(
            citation_id=_token(item["citation_id"], "citation_id"),
            context_item_digest=_digest(
                item["context_item_digest"], "context_item_digest"
            ),
            passage_id=_text(item["passage_id"], "passage_id"),
            passage_text_digest=_digest(
                item["passage_text_digest"], "passage_text_digest"
            ),
            byte_start=byte_start,
            byte_end=byte_end,
            quote_digest=_digest(item["quote_digest"], "quote_digest"),
        )

    @property
    def byte_range(self) -> tuple[int, int]:
        return self.byte_start, self.byte_end

    def canonical_value(self) -> dict[str, object]:
        return {
            "citation_id": self.citation_id,
            "context_item_digest": self.context_item_digest,
            "passage_id": self.passage_id,
            "passage_text_digest": self.passage_text_digest,
            "byte_start": self.byte_start,
            "byte_end": self.byte_end,
            "quote_digest": self.quote_digest,
        }


@dataclass(frozen=True, slots=True)
class ProposalAuthority:
    effect: str
    creates_hypothesis: bool
    creates_candidate: bool
    mutates_editorial_state: bool
    publication_authority: bool
    evidence_authority: bool
    operational_authority: bool

    @classmethod
    def from_value(cls, value: object) -> "ProposalAuthority":
        fields = {
            "effect",
            "creates_hypothesis",
            "creates_candidate",
            "mutates_editorial_state",
            "publication_authority",
            "evidence_authority",
            "operational_authority",
        }
        item = _exact_keys(value, fields, "authority")
        if item["effect"] != "NONE" or any(
            item[name] is not False for name in fields - {"effect"}
        ):
            raise ProposalContractError(
                "a Triage Proposal grants no authority and has no editorial effect"
            )
        return cls(
            effect="NONE",
            creates_hypothesis=False,
            creates_candidate=False,
            mutates_editorial_state=False,
            publication_authority=False,
            evidence_authority=False,
            operational_authority=False,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "effect": self.effect,
            "creates_hypothesis": self.creates_hypothesis,
            "creates_candidate": self.creates_candidate,
            "mutates_editorial_state": self.mutates_editorial_state,
            "publication_authority": self.publication_authority,
            "evidence_authority": self.evidence_authority,
            "operational_authority": self.operational_authority,
        }


@dataclass(frozen=True, slots=True)
class TriageProposal:
    proposal_id: str
    retrieval_context: RetrievalContextBinding
    worker_attempt: WorkerAttemptBinding
    route: ProposalRoute
    confidence: FixedProbability
    uncertainty: FixedProbability
    evidence_references: tuple[EvidenceReference, ...]
    rationale: str
    authority: ProposalAuthority
    content_identity: str

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> "TriageProposal":
        document = _decode_canonical(raw)
        root = _exact_keys(
            document,
            {"schema_version", "content_identity", "proposal"},
            "proposal document",
        )
        if root["schema_version"] != PROPOSAL_SCHEMA_VERSION:
            raise ProposalContractError("proposal schema version is unsupported")
        content_identity = _digest(root["content_identity"], "content_identity")
        proposal = _exact_keys(
            root["proposal"],
            {
                "proposal_id",
                "retrieval_context_binding",
                "worker_attempt_binding",
                "route",
                "confidence",
                "uncertainty",
                "evidence_references",
                "rationale",
                "authority",
            },
            "proposal",
        )
        if _content_identity(proposal) != content_identity:
            raise ProposalContractError("proposal content identity differs")

        retrieval_context = RetrievalContextBinding.from_value(
            proposal["retrieval_context_binding"]
        )
        worker_attempt = WorkerAttemptBinding.from_value(
            proposal["worker_attempt_binding"]
        )
        if (
            worker_attempt.retrieval_context_digest
            != retrieval_context.context_digest
        ):
            raise ProposalContractError(
                "worker attempt retrieval context digest differs"
            )
        try:
            route = ProposalRoute(proposal["route"])
        except (TypeError, ValueError) as exc:
            raise ProposalContractError("proposal route is unsupported") from exc

        raw_references = proposal["evidence_references"]
        if not isinstance(raw_references, list):
            raise ProposalContractError("evidence references must be an array")
        if not 1 <= len(raw_references) <= MAX_EVIDENCE_REFERENCES:
            raise ProposalContractError("evidence references are empty or unbounded")
        evidence_references = tuple(
            EvidenceReference.from_value(item) for item in raw_references
        )
        citation_ids = tuple(item.citation_id for item in evidence_references)
        if citation_ids != tuple(sorted(set(citation_ids))):
            raise ProposalContractError(
                "evidence references must be sorted and unique by citation_id"
            )

        result = cls(
            proposal_id=_uuid(proposal["proposal_id"], "proposal_id"),
            retrieval_context=retrieval_context,
            worker_attempt=worker_attempt,
            route=route,
            confidence=FixedProbability.from_value(
                proposal["confidence"], "confidence"
            ),
            uncertainty=FixedProbability.from_value(
                proposal["uncertainty"], "uncertainty"
            ),
            evidence_references=evidence_references,
            rationale=_text(
                proposal["rationale"], "rationale", MAX_RATIONALE_BYTES
            ),
            authority=ProposalAuthority.from_value(proposal["authority"]),
            content_identity=content_identity,
        )
        if result.canonical_bytes != raw:
            raise ProposalContractError("proposal typed replay differs")
        return result

    @property
    def grants_authority(self) -> bool:
        return False

    @property
    def creates_hypothesis(self) -> bool:
        return False

    @property
    def creates_candidate(self) -> bool:
        return False

    def proposal_value(self) -> dict[str, object]:
        return {
            "proposal_id": self.proposal_id,
            "retrieval_context_binding": self.retrieval_context.canonical_value(),
            "worker_attempt_binding": self.worker_attempt.canonical_value(),
            "route": self.route.value,
            "confidence": self.confidence.canonical_value(),
            "uncertainty": self.uncertainty.canonical_value(),
            "evidence_references": [
                item.canonical_value() for item in self.evidence_references
            ],
            "rationale": self.rationale,
            "authority": self.authority.canonical_value(),
        }

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": PROPOSAL_SCHEMA_VERSION,
            "content_identity": self.content_identity,
            "proposal": self.proposal_value(),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())


__all__ = [
    "MAX_CITATION_SPAN_BYTES",
    "MAX_EVIDENCE_REFERENCES",
    "MAX_RATIONALE_BYTES",
    "PROBABILITY_SCALE",
    "PROPOSAL_SCHEMA_VERSION",
    "EvidenceReference",
    "FixedProbability",
    "FixtureWorkerKind",
    "ProposalAuthority",
    "ProposalContractError",
    "ProposalRoute",
    "RetrievalContextBinding",
    "TriageProposal",
    "WorkerAttemptBinding",
]
