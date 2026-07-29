from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from newsroom.authority.canonical import digest_canonical, validate_sha256_digest
from newsroom.authority.types import UUIDv4Id, require_scope, require_token


class ExtractionAuthorityError(RuntimeError):
    """Base error for governed extraction authority."""


class ExtractionContractError(ValueError):
    """An extraction contract, request, or retained value is malformed."""


class ExtractionStateError(ExtractionAuthorityError):
    """Current retained authority cannot support the requested operation."""


class ExtractionIdentifierReuse(ExtractionStateError):
    """An immutable extraction identity is being reused for new semantics."""


class ExtractionSemanticCollision(ExtractionStateError):
    """Equivalent semantics already exist under another stable identity."""


class ExtractionVersionConflict(ExtractionStateError):
    """A run version does not extend the exact retained head."""


class ExtractionRightsDenied(PermissionError, ExtractionAuthorityError):
    """Current governed-object or source rights block extraction use."""


class ExtractorContractId(UUIDv4Id):
    pass


class ExtractionRunId(UUIDv4Id):
    pass


class ExtractionRunVersionId(UUIDv4Id):
    pass


class ExtractionPassageId(UUIDv4Id):
    pass


class ExtractionOutputId(UUIDv4Id):
    pass


class ProposalSetId(UUIDv4Id):
    pass


class ProposalEnvelopeId(UUIDv4Id):
    pass


class ExtractionExecutionProfile(StrEnum):
    FIXTURE_REPLAY_ONLY = "FIXTURE_REPLAY_ONLY"


class ExtractionOutcome(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    BLOCKING_FAILURE = "BLOCKING_FAILURE"
    INVALID_OUTPUT = "INVALID_OUTPUT"

    @property
    def terminal(self) -> bool:
        return self in {
            ExtractionOutcome.SUCCESS,
            ExtractionOutcome.BLOCKING_FAILURE,
            ExtractionOutcome.INVALID_OUTPUT,
        }

    @property
    def may_retain_output(self) -> bool:
        return self in {
            ExtractionOutcome.SUCCESS,
            ExtractionOutcome.PARTIAL,
            ExtractionOutcome.INVALID_OUTPUT,
        }

    @property
    def may_retain_proposals(self) -> bool:
        return self in {
            ExtractionOutcome.SUCCESS,
            ExtractionOutcome.PARTIAL,
        }


class ExtractionOutputValidation(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"


class ExtractionProposalKind(StrEnum):
    ENTITY_MENTION = "ENTITY_MENTION"
    ENTITY_EQUIVALENCE = "ENTITY_EQUIVALENCE"
    RELATION = "RELATION"
    CLAIM = "CLAIM"


class ProposalPredicateHint(StrEnum):
    SAME_EVENT_AS = "SAME_EVENT_AS"
    DEVELOPMENT_OF = "DEVELOPMENT_OF"
    SAME_PROCESS_AS = "SAME_PROCESS_AS"
    CORRECTS = "CORRECTS"
    SUPERSEDES = "SUPERSEDES"
    SUPPORTS = "SUPPORTS"
    DISPUTES = "DISPUTES"
    ABOUT_EVENT = "ABOUT_EVENT"


class FixtureExtractionCase(StrEnum):
    BILINGUAL_COMPLETE = "BILINGUAL_COMPLETE"
    BILINGUAL_PARTIAL = "BILINGUAL_PARTIAL"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    BLOCKING_FAILURE = "BLOCKING_FAILURE"
    INVALID_OUTPUT = "INVALID_OUTPUT"


class ExtractionFailureCode(StrEnum):
    NONE = "NONE"
    FIXTURE_PARTIAL = "FIXTURE_PARTIAL"
    FIXTURE_RETRYABLE = "FIXTURE_RETRYABLE"
    FIXTURE_BLOCKED = "FIXTURE_BLOCKED"
    OUTPUT_SCHEMA_INVALID = "OUTPUT_SCHEMA_INVALID"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    PRODUCER_INTERNAL_ERROR = "PRODUCER_INTERNAL_ERROR"


def bounded_text(
    value: str,
    *,
    field: str,
    maximum_bytes: int = 4096,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise ExtractionContractError(f"{field} must be canonical text")
    if not allow_empty and not value:
        raise ExtractionContractError(f"{field} cannot be empty")
    if len(value.encode("utf-8")) > maximum_bytes:
        raise ExtractionContractError(f"{field} exceeds its byte bound")
    return value


def bounded_token(value: str, *, field: str) -> str:
    try:
        return require_token(value, field=field)
    except ValueError as exc:
        raise ExtractionContractError(str(exc)) from exc


def canonical_digest(value: str, *, field: str) -> str:
    try:
        normalized = validate_sha256_digest(value, field=field)
    except ValueError as exc:
        raise ExtractionContractError(str(exc)) from exc
    if normalized != value:
        raise ExtractionContractError(f"{field} must use canonical lowercase text")
    return value


def bounded_int(
    value: int,
    *,
    field: str,
    minimum: int = 0,
    maximum: int,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > maximum
    ):
        raise ExtractionContractError(
            f"{field} must be an integer between {minimum} and {maximum}"
        )
    return value


def sorted_text_tuple(
    values: Iterable[str],
    *,
    field: str,
    allow_empty: bool = True,
    maximum_items: int = 32,
    maximum_item_bytes: int = 256,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ExtractionContractError(f"{field} must be an iterable of text")
    items = tuple(
        sorted(
            {
                bounded_text(
                    item,
                    field=field,
                    maximum_bytes=maximum_item_bytes,
                )
                for item in values
            }
        )
    )
    if not allow_empty and not items:
        raise ExtractionContractError(f"{field} cannot be empty")
    if len(items) > maximum_items:
        raise ExtractionContractError(f"{field} exceeds its item bound")
    return items


@dataclass(frozen=True, slots=True)
class VersionedExtractionComponent:
    component_id: str
    component_version: str
    contract_digest: str

    def __post_init__(self) -> None:
        bounded_token(self.component_id, field="extraction_component_id")
        bounded_token(self.component_version, field="extraction_component_version")
        canonical_digest(
            self.contract_digest, field="extraction_component_contract_digest"
        )

    def canonical_value(self) -> dict[str, str]:
        return {
            "component_id": self.component_id,
            "component_version": self.component_version,
            "contract_digest": self.contract_digest,
        }


@dataclass(frozen=True, slots=True)
class ExtractionBudget:
    timeout_ms: int
    max_input_bytes: int
    max_output_bytes: int
    max_proposals: int
    max_evidence_ranges: int
    max_request_tokens: int
    max_response_tokens: int
    max_cost_microunits: int

    def __post_init__(self) -> None:
        bounded_int(self.timeout_ms, field="timeout_ms", minimum=1, maximum=300_000)
        bounded_int(
            self.max_input_bytes,
            field="max_input_bytes",
            minimum=1,
            maximum=16 * 1024 * 1024,
        )
        bounded_int(
            self.max_output_bytes,
            field="max_output_bytes",
            minimum=1,
            maximum=4 * 1024 * 1024,
        )
        bounded_int(
            self.max_proposals,
            field="max_proposals",
            minimum=1,
            maximum=10_000,
        )
        bounded_int(
            self.max_evidence_ranges,
            field="max_evidence_ranges",
            minimum=1,
            maximum=100_000,
        )
        bounded_int(
            self.max_request_tokens,
            field="max_request_tokens",
            minimum=0,
            maximum=10_000_000,
        )
        bounded_int(
            self.max_response_tokens,
            field="max_response_tokens",
            minimum=0,
            maximum=10_000_000,
        )
        bounded_int(
            self.max_cost_microunits,
            field="max_cost_microunits",
            minimum=0,
            maximum=10_000_000_000,
        )

    def canonical_value(self) -> dict[str, int]:
        return {
            "timeout_ms": self.timeout_ms,
            "max_input_bytes": self.max_input_bytes,
            "max_output_bytes": self.max_output_bytes,
            "max_proposals": self.max_proposals,
            "max_evidence_ranges": self.max_evidence_ranges,
            "max_request_tokens": self.max_request_tokens,
            "max_response_tokens": self.max_response_tokens,
            "max_cost_microunits": self.max_cost_microunits,
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class ExtractionUsage:
    elapsed_ms: int
    input_bytes: int
    output_bytes: int
    proposal_count: int
    evidence_range_count: int
    request_tokens: int = 0
    response_tokens: int = 0
    cost_microunits: int = 0

    def __post_init__(self) -> None:
        bounded_int(self.elapsed_ms, field="elapsed_ms", minimum=0, maximum=300_000)
        bounded_int(
            self.input_bytes,
            field="input_bytes",
            minimum=0,
            maximum=16 * 1024 * 1024,
        )
        bounded_int(
            self.output_bytes,
            field="output_bytes",
            minimum=0,
            maximum=4 * 1024 * 1024,
        )
        bounded_int(
            self.proposal_count,
            field="proposal_count",
            minimum=0,
            maximum=10_000,
        )
        bounded_int(
            self.evidence_range_count,
            field="evidence_range_count",
            minimum=0,
            maximum=100_000,
        )
        bounded_int(
            self.request_tokens,
            field="request_tokens",
            minimum=0,
            maximum=10_000_000,
        )
        bounded_int(
            self.response_tokens,
            field="response_tokens",
            minimum=0,
            maximum=10_000_000,
        )
        bounded_int(
            self.cost_microunits,
            field="cost_microunits",
            minimum=0,
            maximum=10_000_000_000,
        )

    def require_within(self, budget: ExtractionBudget) -> None:
        if not isinstance(budget, ExtractionBudget):
            raise ExtractionContractError("usage budget must be typed")
        if (
            self.elapsed_ms > budget.timeout_ms
            or self.input_bytes > budget.max_input_bytes
            or self.output_bytes > budget.max_output_bytes
            or self.proposal_count > budget.max_proposals
            or self.evidence_range_count > budget.max_evidence_ranges
            or self.request_tokens > budget.max_request_tokens
            or self.response_tokens > budget.max_response_tokens
            or self.cost_microunits > budget.max_cost_microunits
        ):
            raise ExtractionContractError("extraction usage exceeds the fixed budget")

    def canonical_value(self) -> dict[str, int]:
        return {
            "elapsed_ms": self.elapsed_ms,
            "input_bytes": self.input_bytes,
            "output_bytes": self.output_bytes,
            "proposal_count": self.proposal_count,
            "evidence_range_count": self.evidence_range_count,
            "request_tokens": self.request_tokens,
            "response_tokens": self.response_tokens,
            "cost_microunits": self.cost_microunits,
        }


@dataclass(frozen=True, slots=True)
class EvidenceRange:
    passage_id: ExtractionPassageId
    start_byte: int
    end_byte: int
    evidence_text_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.passage_id, ExtractionPassageId):
            raise ExtractionContractError("evidence passage identity must be typed")
        bounded_int(
            self.start_byte,
            field="evidence_start_byte",
            minimum=0,
            maximum=16 * 1024 * 1024,
        )
        bounded_int(
            self.end_byte,
            field="evidence_end_byte",
            minimum=1,
            maximum=16 * 1024 * 1024,
        )
        if self.end_byte <= self.start_byte:
            raise ExtractionContractError("evidence range must be non-empty")
        canonical_digest(
            self.evidence_text_digest, field="evidence_text_digest"
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "passage_id": str(self.passage_id),
            "start_byte": self.start_byte,
            "end_byte": self.end_byte,
            "evidence_text_digest": self.evidence_text_digest,
        }


@dataclass(frozen=True, slots=True)
class ExtractionReadPolicy:
    policy_id: str
    purpose: str
    metadata_required_scope: str
    proposal_required_scope: str
    raw_output_required_scope: str
    allowed_principal_ids: frozenset[str]
    max_results: int = 1000

    def __post_init__(self) -> None:
        bounded_token(self.policy_id, field="extraction_read_policy_id")
        bounded_token(self.purpose, field="extraction_read_purpose")
        for field, value in (
            ("extraction_metadata_read_scope", self.metadata_required_scope),
            ("extraction_proposal_read_scope", self.proposal_required_scope),
            ("extraction_raw_output_read_scope", self.raw_output_required_scope),
        ):
            try:
                require_scope(value, field=field)
            except ValueError as exc:
                raise ExtractionContractError(str(exc)) from exc
        if len(
            {
                self.metadata_required_scope,
                self.proposal_required_scope,
                self.raw_output_required_scope,
            }
        ) != 3:
            raise ExtractionContractError(
                "metadata, proposal, and raw-output reads need distinct scopes"
            )
        if (
            not isinstance(self.allowed_principal_ids, frozenset)
            or not self.allowed_principal_ids
        ):
            raise ExtractionContractError(
                "extraction read principals must be a non-empty frozenset"
            )
        for principal_id in self.allowed_principal_ids:
            bounded_token(principal_id, field="extraction_reader_principal")
        bounded_int(
            self.max_results,
            field="extraction_read_maximum",
            minimum=1,
            maximum=10_000,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "purpose": self.purpose,
            "metadata_required_scope": self.metadata_required_scope,
            "proposal_required_scope": self.proposal_required_scope,
            "raw_output_required_scope": self.raw_output_required_scope,
            "allowed_principal_ids": sorted(self.allowed_principal_ids),
            "max_results": self.max_results,
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())

    def require_principal(self, principal_id: str) -> None:
        if principal_id not in self.allowed_principal_ids:
            raise PermissionError(
                "extraction reader principal is outside the read policy"
            )

    def require_limit(self, limit: int) -> None:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit <= 0
            or limit > self.max_results
        ):
            raise PermissionError("extraction read limit exceeds the read policy")


__all__ = [
    "EvidenceRange",
    "ExtractionAuthorityError",
    "ExtractionBudget",
    "ExtractionContractError",
    "ExtractionExecutionProfile",
    "ExtractionFailureCode",
    "ExtractionIdentifierReuse",
    "ExtractionOutcome",
    "ExtractionOutputId",
    "ExtractionOutputValidation",
    "ExtractionPassageId",
    "ExtractionProposalKind",
    "ExtractionReadPolicy",
    "ExtractionRightsDenied",
    "ExtractionRunId",
    "ExtractionRunVersionId",
    "ExtractionSemanticCollision",
    "ExtractionStateError",
    "ExtractionUsage",
    "ExtractionVersionConflict",
    "ExtractorContractId",
    "FixtureExtractionCase",
    "ProposalEnvelopeId",
    "ProposalPredicateHint",
    "ProposalSetId",
    "VersionedExtractionComponent",
    "bounded_int",
    "bounded_text",
    "bounded_token",
    "canonical_digest",
    "sorted_text_tuple",
]
