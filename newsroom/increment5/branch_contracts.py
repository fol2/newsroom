"""Typed, immutable receipts for independent Increment 5 retrieval branches.

These records are advisory evidence only.  They neither create authority nor
compose a hybrid result; composition remains owned by Increment 5D.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.authority.types import TrustScope, UUIDv4Id, UtcTimestamp, require_token


BRANCH_RESULT_LIMIT = 8
BRANCH_TIMEOUT_MS = 5_000
EXACT_BRANCH_POLICY_ID = "increment5-exact-branch-v1"
EXACT_BRANCH_ACTOR_ID = "retrieval_worker"
EXACT_BRANCH_PURPOSE = "exact_identity_lookup"
CANDIDATE_COLLISION_POLICY_ID = "increment5-candidate-collision-read-v1"
CANDIDATE_COLLISION_ACTOR_ID = "candidate_controller"
CANDIDATE_COLLISION_PURPOSE = "candidate_collision_check"


class Increment5BranchContractError(ValueError):
    """An Increment 5 branch request or receipt is malformed."""


class BranchMode(StrEnum):
    EXACT = "EXACT"
    FULL_TEXT = "FULL_TEXT"
    VECTOR = "VECTOR"
    ADMITTED_GRAPH = "ADMITTED_GRAPH"


class BranchOutcome(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class ExactLookupKind(StrEnum):
    SOURCE_NATIVE_ID = "SOURCE_NATIVE_ID"
    SOURCE_REVISION_ID = "SOURCE_REVISION_ID"
    SOURCE_NATIVE_REVISION_TOKEN = "SOURCE_NATIVE_REVISION_TOKEN"
    REPRESENTATION_ID = "REPRESENTATION_ID"
    CANONICAL_ENTITY_ID = "CANONICAL_ENTITY_ID"
    AUTHORITY_ALIAS = "AUTHORITY_ALIAS"
    FORMAL_PROCESS_ID = "FORMAL_PROCESS_ID"


class BranchExclusionReason(StrEnum):
    RIGHTS_NOT_CURRENT = "RIGHTS_NOT_CURRENT"
    TOMBSTONED = "TOMBSTONED"
    OUTSIDE_QUERY_VALID_TIME = "OUTSIDE_QUERY_VALID_TIME"


class BranchRequestId(UUIDv4Id):
    pass


class BranchReceiptId(UUIDv4Id):
    pass


def _bounded_text(value: str, *, field: str, maximum_bytes: int = 512) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > maximum_bytes
    ):
        raise Increment5BranchContractError(f"{field} must be bounded canonical text")
    return value


def _bounded_non_negative_int(value: int, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise Increment5BranchContractError(f"{field} must be a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class ExactBranchRequest:
    request_id: BranchRequestId
    idempotency_key: str
    actor_id: str
    purpose: str
    policy_id: str
    contract_digest: str
    lookup_kind: ExactLookupKind
    lookup_value: str
    query_valid_time: UtcTimestamp
    serving_time: UtcTimestamp
    authority_scope_id: str | None = None
    minimum_ledger_seq: int = 0
    result_limit: int = BRANCH_RESULT_LIMIT
    timeout_ms: int = BRANCH_TIMEOUT_MS

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, BranchRequestId):
            raise Increment5BranchContractError("branch request identity must be typed")
        _bounded_text(self.idempotency_key, field="branch_idempotency_key", maximum_bytes=256)
        require_token(self.actor_id, field="branch_actor_id")
        require_token(self.purpose, field="branch_purpose")
        if self.actor_id != EXACT_BRANCH_ACTOR_ID or self.purpose != EXACT_BRANCH_PURPOSE:
            raise Increment5BranchContractError(
                "exact branch actor and purpose must equal the reviewed lane"
            )
        require_token(self.policy_id, field="branch_policy_id")
        validate_sha256_digest(self.contract_digest, field="branch_contract_digest")
        if not isinstance(self.lookup_kind, ExactLookupKind):
            raise Increment5BranchContractError("exact lookup kind must be typed")
        _bounded_text(self.lookup_value, field="exact_lookup_value")
        scoped_kinds = {
            ExactLookupKind.SOURCE_NATIVE_ID,
            ExactLookupKind.SOURCE_NATIVE_REVISION_TOKEN,
        }
        if self.lookup_kind in scoped_kinds:
            if self.authority_scope_id is None:
                raise Increment5BranchContractError(
                    "scoped exact lookup requires an authority scope"
                )
            _bounded_text(
                self.authority_scope_id,
                field="exact_authority_scope_id",
                maximum_bytes=128,
            )
        elif self.authority_scope_id is not None:
            raise Increment5BranchContractError(
                "unscoped exact lookup cannot carry an authority scope"
            )
        if not isinstance(self.query_valid_time, UtcTimestamp) or not isinstance(
            self.serving_time, UtcTimestamp
        ):
            raise Increment5BranchContractError("branch times must be typed")
        _bounded_non_negative_int(self.minimum_ledger_seq, field="minimum_ledger_seq")
        if self.result_limit != BRANCH_RESULT_LIMIT:
            raise Increment5BranchContractError("branch result limit must remain fixed at 8")
        if self.timeout_ms != BRANCH_TIMEOUT_MS:
            raise Increment5BranchContractError("branch timeout must remain fixed at 5000 ms")

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.increment5.exact-branch-request.v1",
            "request_id": str(self.request_id),
            "idempotency_key": self.idempotency_key,
            "actor_id": self.actor_id,
            "purpose": self.purpose,
            "policy_id": self.policy_id,
            "contract_digest": self.contract_digest,
            "lookup_kind": self.lookup_kind.value,
            "lookup_value": self.lookup_value,
            "authority_scope_id": self.authority_scope_id,
            "query_valid_time": self.query_valid_time.to_text(),
            "serving_time": self.serving_time.to_text(),
            "minimum_ledger_seq": self.minimum_ledger_seq,
            "result_limit": self.result_limit,
            "timeout_ms": self.timeout_ms,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def request_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


@dataclass(frozen=True, slots=True)
class CandidateCollisionRequest:
    request_id: BranchRequestId
    idempotency_key: str
    actor_id: str
    purpose: str
    policy_id: str
    contract_digest: str
    semantic_collision_digest: str
    query_valid_time: UtcTimestamp
    serving_time: UtcTimestamp
    minimum_ledger_seq: int = 0
    timeout_ms: int = BRANCH_TIMEOUT_MS

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, BranchRequestId):
            raise Increment5BranchContractError("collision request identity must be typed")
        _bounded_text(self.idempotency_key, field="collision_idempotency_key", maximum_bytes=256)
        require_token(self.actor_id, field="collision_actor_id")
        require_token(self.purpose, field="collision_purpose")
        if (
            self.actor_id != CANDIDATE_COLLISION_ACTOR_ID
            or self.purpose != CANDIDATE_COLLISION_PURPOSE
        ):
            raise Increment5BranchContractError(
                "collision actor and purpose must equal the reviewed lane"
            )
        require_token(self.policy_id, field="collision_policy_id")
        validate_sha256_digest(self.contract_digest, field="collision_contract_digest")
        validate_sha256_digest(
            self.semantic_collision_digest,
            field="semantic_collision_digest",
        )
        if not isinstance(self.query_valid_time, UtcTimestamp) or not isinstance(
            self.serving_time, UtcTimestamp
        ):
            raise Increment5BranchContractError("collision times must be typed")
        _bounded_non_negative_int(self.minimum_ledger_seq, field="minimum_ledger_seq")
        if self.timeout_ms != BRANCH_TIMEOUT_MS:
            raise Increment5BranchContractError("collision timeout must remain fixed at 5000 ms")

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.increment5.candidate-collision-request.v1",
            "request_id": str(self.request_id),
            "idempotency_key": self.idempotency_key,
            "actor_id": self.actor_id,
            "purpose": self.purpose,
            "policy_id": self.policy_id,
            "contract_digest": self.contract_digest,
            "semantic_collision_digest": self.semantic_collision_digest,
            "query_valid_time": self.query_valid_time.to_text(),
            "serving_time": self.serving_time.to_text(),
            "minimum_ledger_seq": self.minimum_ledger_seq,
            "timeout_ms": self.timeout_ms,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def request_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


@dataclass(frozen=True, slots=True)
class ExactBranchHit:
    rank: int
    authority_kind: str
    authority_id: str
    dependency_root_id: str
    match_signal: str
    source_identity: str
    trust_scope: TrustScope
    provenance_digest: str
    raw_score_ppm: int = 1_000_000

    def __post_init__(self) -> None:
        if isinstance(self.rank, bool) or not isinstance(self.rank, int) or not 1 <= self.rank <= 8:
            raise Increment5BranchContractError("exact hit rank exceeds the fixed bound")
        for field_name in ("authority_kind", "match_signal"):
            require_token(getattr(self, field_name), field=field_name)
        for field_name in ("authority_id", "dependency_root_id", "source_identity"):
            _bounded_text(getattr(self, field_name), field=field_name)
        if self.trust_scope not in {TrustScope.OBSERVED, TrustScope.ADMITTED}:
            raise Increment5BranchContractError("exact hit trust scope is not permitted")
        validate_sha256_digest(self.provenance_digest, field="exact_hit_provenance_digest")
        if self.raw_score_ppm != 1_000_000:
            raise Increment5BranchContractError("exact hit score must be one")

    def canonical_value(self) -> dict[str, object]:
        return {
            "rank": self.rank,
            "authority_kind": self.authority_kind,
            "authority_id": self.authority_id,
            "dependency_root_id": self.dependency_root_id,
            "match_signal": self.match_signal,
            "source_identity": self.source_identity,
            "trust_scope": self.trust_scope.value,
            "provenance_digest": self.provenance_digest,
            "raw_score_ppm": self.raw_score_ppm,
        }


@dataclass(frozen=True, slots=True)
class BranchExclusion:
    authority_kind: str
    authority_id: str
    reason: BranchExclusionReason

    def __post_init__(self) -> None:
        require_token(self.authority_kind, field="excluded_authority_kind")
        _bounded_text(self.authority_id, field="excluded_authority_id")
        if not isinstance(self.reason, BranchExclusionReason):
            raise Increment5BranchContractError("branch exclusion reason must be typed")

    def canonical_value(self) -> dict[str, str]:
        return {
            "authority_kind": self.authority_kind,
            "authority_id": self.authority_id,
            "reason": self.reason.value,
        }


__all__ = [
    "BRANCH_RESULT_LIMIT",
    "BRANCH_TIMEOUT_MS",
    "CANDIDATE_COLLISION_ACTOR_ID",
    "CANDIDATE_COLLISION_POLICY_ID",
    "CANDIDATE_COLLISION_PURPOSE",
    "EXACT_BRANCH_ACTOR_ID",
    "EXACT_BRANCH_POLICY_ID",
    "EXACT_BRANCH_PURPOSE",
    "BranchExclusion",
    "BranchExclusionReason",
    "BranchMode",
    "BranchOutcome",
    "BranchReceiptId",
    "BranchRequestId",
    "CandidateCollisionRequest",
    "ExactBranchHit",
    "ExactBranchRequest",
    "ExactLookupKind",
    "Increment5BranchContractError",
]
