"""Typed outcomes, failure codes, and match signals for 5B branches."""

from __future__ import annotations

from enum import StrEnum

from newsroom.authority.canonical import digest_canonical

from ._retrieval_validation import Increment5RetrievalContractError, bounded_text


class BranchOutcome(StrEnum):
    COMPLETE = "COMPLETE"
    DEGRADED = "DEGRADED"
    INCOMPLETE = "INCOMPLETE"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class BranchFailureCode(StrEnum):
    NONE = "NONE"
    SCOPE_BLOCKED = "SCOPE_BLOCKED"
    RIGHTS_BLOCKED = "RIGHTS_BLOCKED"
    PROFILE_BLOCKED = "PROFILE_BLOCKED"
    QUERY_VALID_TIME_IN_FUTURE = "QUERY_VALID_TIME_IN_FUTURE"
    STALE_AUTHORITY_WATERMARK = "STALE_AUTHORITY_WATERMARK"
    AUTHORITY_STATE_MISMATCH = "AUTHORITY_STATE_MISMATCH"
    REQUIRED_GAP_PRESENT = "REQUIRED_GAP_PRESENT"
    DEAD_LETTER_PRESENT = "DEAD_LETTER_PRESENT"
    WRONG_GENERATION = "WRONG_GENERATION"
    INDEX_UNAVAILABLE = "INDEX_UNAVAILABLE"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    RESULT_LIMIT_EXCEEDED = "RESULT_LIMIT_EXCEEDED"
    TIMEOUT_BUDGET_EXCEEDED = "TIMEOUT_BUDGET_EXCEEDED"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    BUDGET_BLOCKED = "BUDGET_BLOCKED"


class BranchMatchSignal(StrEnum):
    EXACT_IDENTITY = "EXACT_IDENTITY"
    SOURCE_NATIVE_ID = "SOURCE_NATIVE_ID"
    FORMAL_PROCESS_ID = "FORMAL_PROCESS_ID"
    AUTHORITY_ALIAS = "AUTHORITY_ALIAS"
    FULL_TEXT_TERM = "FULL_TEXT_TERM"
    VECTOR_SIMILARITY = "VECTOR_SIMILARITY"
    ADMITTED_RELATION_PATH = "ADMITTED_RELATION_PATH"


class BranchExclusionReason(StrEnum):
    RIGHTS_NOT_CURRENT = "RIGHTS_NOT_CURRENT"
    TOMBSTONED = "TOMBSTONED"
    RETIRED_OR_REJECTED = "RETIRED_OR_REJECTED"
    OUTSIDE_VALID_TIME = "OUTSIDE_VALID_TIME"
    TRUST_SCOPE_NOT_ADMITTED = "TRUST_SCOPE_NOT_ADMITTED"
    RESULT_BOUND = "RESULT_BOUND"
    MALFORMED_PROJECTION_ROW = "MALFORMED_PROJECTION_ROW"


def failure_detail_digest(code: BranchFailureCode, detail: str) -> str:
    if not isinstance(code, BranchFailureCode) or code is BranchFailureCode.NONE:
        raise Increment5RetrievalContractError("failure detail requires a failure code")
    bounded_text(detail, field="branch failure detail", maximum_bytes=1024)
    return digest_canonical({
        "contract": "newsroom.increment5b.branch-failure-detail.v1",
        "code": code.value,
        "detail": detail,
    })


__all__ = [
    "BranchExclusionReason", "BranchFailureCode", "BranchMatchSignal",
    "BranchOutcome", "failure_detail_digest",
]
