"""Deterministic exact-first hybrid composition for Increment 5D1.

The composer consumes independently attributable Increment 5C dispatch results,
validates their retained execution and raw branch receipts, and produces one
immutable read-only composition receipt.  It performs fixed reciprocal-rank
fusion (``k=60``) and deduplicates only by the authority-provided dependency
root.  Raw branch scores are retained only through branch-hit digests and are
never compared across modes.

This module deliberately does not hydrate governed bytes, construct the final
Retrieval Context, mutate Candidate or Hypothesis authority, call providers, or
activate publication.  Those remain later boundaries.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from fractions import Fraction
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.types import TrustScope

from .admitted_graph_retriever import AdmittedGraphReceipt
from .branch_receipts import ExactBranchReceipt
from .fulltext_receipts import FullTextBranchReceipt
from .named_tool_authority_execution import NamedAuthorityExecutionReceipt
from .named_tool_branch_execution import NamedToolExecutionReceipt
from .named_tool_contracts import NamedToolId
from .named_tool_dispatch import (
    NamedToolDispatchOutcome,
    NamedToolDispatchReceipt,
    NamedToolDispatchResult,
    NamedToolExecutionRoute,
)
from .vector_retriever import VectorBranchReceipt


_RRF_K = 60
_CANDIDATE_LIMIT = 12
_RESPONSE_LIMIT_BYTES = 262_144
_MAX_INPUTS = 6
_MAX_BRANCH_ORIGINS = 32
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,255}\Z")
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_UTC_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{6})?Z\Z")


class HybridCompositionError(RuntimeError):
    """The composition request, upstream evidence or journal is invalid."""


class HybridCompositionPurpose(StrEnum):
    TRIAGE_PRIOR_MATCH = "TRIAGE_PRIOR_MATCH"
    CORRECTION_REVIEW = "CORRECTION_REVIEW"
    COLLISION_REVIEW = "COLLISION_REVIEW"
    REPLAY_AUDIT = "REPLAY_AUDIT"


class HybridMode(StrEnum):
    EXACT = "EXACT"
    FULL_TEXT = "FULL_TEXT"
    VECTOR = "VECTOR"
    ADMITTED_GRAPH = "ADMITTED_GRAPH"


class HybridManifestState(StrEnum):
    COMPLETE_RESULTS = "COMPLETE_RESULTS"
    COMPLETE_NO_MATCH = "COMPLETE_NO_MATCH"
    INCOMPLETE = "INCOMPLETE"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    MISSING = "MISSING"
    NOT_REQUIRED = "NOT_REQUIRED"


class HybridCompositionOutcome(StrEnum):
    COMPLETE = "COMPLETE"
    DEGRADED = "DEGRADED"
    INCOMPLETE = "INCOMPLETE"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class HybridCompositionReason(StrEnum):
    NO_MATCH = "NO_MATCH"
    MISSING_MANDATORY_TOOL = "MISSING_MANDATORY_TOOL"
    MANDATORY_TOOL_INCOMPLETE = "MANDATORY_TOOL_INCOMPLETE"
    MANDATORY_TOOL_POLICY_BLOCKED = "MANDATORY_TOOL_POLICY_BLOCKED"
    MANDATORY_TOOL_STALE = "MANDATORY_TOOL_STALE"
    MANDATORY_TOOL_UNAVAILABLE = "MANDATORY_TOOL_UNAVAILABLE"
    OPTIONAL_EVIDENCE_NON_COMPLETE = "OPTIONAL_EVIDENCE_NON_COMPLETE"
    RECEIPT_INVALID = "RECEIPT_INVALID"
    RESPONSE_LIMIT_EXCEEDED = "RESPONSE_LIMIT_EXCEEDED"


class HybridPrecedence(StrEnum):
    EXACT_FIRST = "EXACT_FIRST"
    APPROXIMATE = "APPROXIMATE"


class HybridExclusionReason(StrEnum):
    RESULT_BOUND = "RESULT_BOUND"


_COMPOSER_LOCAL_FAILURES = frozenset(
    {
        HybridCompositionReason.RECEIPT_INVALID,
        HybridCompositionReason.RESPONSE_LIMIT_EXCEEDED,
    }
)


_BRANCH_TOOLS = (
    NamedToolId.EXACT_AUTHORITY_LOOKUP,
    NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL,
    NamedToolId.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL,
    NamedToolId.BOUNDED_ADMITTED_GRAPH_TRAVERSAL,
)
_AUXILIARY_TOOLS = (
    NamedToolId.CURRENT_COLLISION_AND_AUTHORITY_HYDRATION_LOOKUP,
    NamedToolId.BOUNDED_SOURCE_REVISION_IMPACT_LOOKUP,
)
_ALL_TOOLS = _BRANCH_TOOLS + _AUXILIARY_TOOLS
_TOOL_ORDER = {tool_id: index for index, tool_id in enumerate(_ALL_TOOLS)}
_MODE_BY_TOOL = {
    NamedToolId.EXACT_AUTHORITY_LOOKUP: HybridMode.EXACT,
    NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL: HybridMode.FULL_TEXT,
    NamedToolId.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL: HybridMode.VECTOR,
    NamedToolId.BOUNDED_ADMITTED_GRAPH_TRAVERSAL: HybridMode.ADMITTED_GRAPH,
}
_MODE_ORDER = {mode: index for index, mode in enumerate(HybridMode)}
_REQUIRED_AUXILIARY_BY_PURPOSE = {
    HybridCompositionPurpose.TRIAGE_PRIOR_MATCH: (),
    HybridCompositionPurpose.CORRECTION_REVIEW: (
        NamedToolId.BOUNDED_SOURCE_REVISION_IMPACT_LOOKUP,
    ),
    HybridCompositionPurpose.COLLISION_REVIEW: (
        NamedToolId.CURRENT_COLLISION_AND_AUTHORITY_HYDRATION_LOOKUP,
    ),
    HybridCompositionPurpose.REPLAY_AUDIT: _AUXILIARY_TOOLS,
}


HYBRID_COMPOSER_CONTRACT_DIGEST = digest_bytes(
    canonical_json_bytes(
        {
            "schema_version": "newsroom.increment5.hybrid-composer-contract.v1",
            "required_branch_tools": [item.value for item in _BRANCH_TOOLS],
            "purpose_auxiliary_tools": {
                purpose.value: [item.value for item in tools]
                for purpose, tools in _REQUIRED_AUXILIARY_BY_PURPOSE.items()
            },
            "fusion": {
                "algorithm": "RECIPROCAL_RANK_FUSION",
                "reciprocal_rank_k": _RRF_K,
                "branch_weights": "EQUAL_ONE",
                "score_representation": "REDUCED_RATIONAL",
                "raw_score_comparison": False,
            },
            "precedence": [
                "EXACT_DEPENDENCY_ROOTS_FIRST",
                "RRF_SCORE_DESC",
                "BEST_BRANCH_RANK_ASC",
                "DEPENDENCY_ROOT_ID_ASC",
            ],
            "deduplication": {
                "root": "AUTHORITATIVE_DEPENDENCY_ROOT",
                "best_hit_per_mode_for_score": True,
                "retain_every_origin": True,
                "similarity_can_merge_roots": False,
            },
            "candidate_limit": _CANDIDATE_LIMIT,
            "response_limit_bytes": _RESPONSE_LIMIT_BYTES,
            "authority_effect": "NONE",
            "external_calls": 0,
            "provider_spend_micros": 0,
        }
    )
)


def _canonical(value: object) -> bytes:
    return canonical_json_bytes(value)


def _digest(value: bytes) -> str:
    return digest_bytes(value)


def _branch_hit_digest(value: Mapping[str, object]) -> str:
    # Vector proof integers intentionally exceed the interoperable JSON integer
    # range used for authority records.  They remain valid retained branch
    # evidence, so content-address the exact deterministic JSON value without
    # attempting to reinterpret or pool those mode-specific scores.
    try:
        raw = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise HybridCompositionError("branch hit is not deterministic JSON") from exc
    return _digest(raw)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise HybridCompositionError(
                "retained composition JSON contains duplicate keys"
            )
        value[key] = item
    return value


def _decode(raw: bytes) -> dict[str, object]:
    if not isinstance(raw, bytes):
        raise HybridCompositionError("retained composition receipt must be bytes")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HybridCompositionError("retained composition receipt is not JSON") from exc
    if not isinstance(value, dict):
        raise HybridCompositionError("retained composition root is not an object")
    return value


def _require_digest(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise HybridCompositionError(f"{field} must be a canonical SHA-256 digest")
    return value


def _require_token(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _TOKEN_RE.fullmatch(value) is None:
        raise HybridCompositionError(f"{field} must be a bounded canonical token")
    return value


def _require_text(value: object, *, field: str, maximum_bytes: int = 1024) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > maximum_bytes
    ):
        raise HybridCompositionError(f"{field} must be bounded canonical text")
    return value


def _require_non_negative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HybridCompositionError(f"{field} must be a non-negative integer")
    return value


def _require_positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise HybridCompositionError(f"{field} must be a positive integer")
    return value


def _parse_utc(value: object, *, field: str) -> datetime:
    if not isinstance(value, str) or _UTC_RE.fullmatch(value) is None:
        raise HybridCompositionError(f"{field} must be canonical UTC text")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise HybridCompositionError(f"{field} must be canonical UTC text") from exc
    if parsed.tzinfo != UTC:
        raise HybridCompositionError(f"{field} must use UTC")
    return parsed


def _uuid(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise HybridCompositionError(f"{field} must be a canonical UUID")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise HybridCompositionError(f"{field} must be a canonical UUID") from exc
    if str(parsed) != value:
        raise HybridCompositionError(f"{field} must be a canonical UUID")
    return value


def _fixed_tool_sort(values: Iterable[NamedToolId]) -> tuple[NamedToolId, ...]:
    return tuple(sorted(values, key=_TOOL_ORDER.__getitem__))


def _fixed_mode_sort(values: Iterable[HybridMode]) -> tuple[HybridMode, ...]:
    return tuple(sorted(values, key=_MODE_ORDER.__getitem__))


def _dispatch_state(receipt: NamedToolDispatchReceipt) -> HybridManifestState:
    if receipt.outcome is NamedToolDispatchOutcome.COMPLETE:
        return (
            HybridManifestState.COMPLETE_NO_MATCH
            if receipt.no_match
            else HybridManifestState.COMPLETE_RESULTS
        )
    return HybridManifestState(receipt.outcome.value)


def _execution_receipt(
    value: "HybridCompositionInput",
) -> NamedToolExecutionReceipt | NamedAuthorityExecutionReceipt:
    if value.dispatch_receipt.route is NamedToolExecutionRoute.BRANCH:
        return NamedToolExecutionReceipt.from_canonical_bytes(
            value.execution_receipt_bytes
        )
    return NamedAuthorityExecutionReceipt.from_canonical_bytes(
        value.execution_receipt_bytes
    )


@dataclass(frozen=True, slots=True)
class HybridCompositionInput:
    """Exact retained bytes for one independently attributable 5C dispatch."""

    dispatch_receipt: NamedToolDispatchReceipt
    execution_receipt_bytes: bytes
    raw_upstream_receipt_bytes: bytes | None

    def __post_init__(self) -> None:
        if not isinstance(self.dispatch_receipt, NamedToolDispatchReceipt):
            raise HybridCompositionError("composition input dispatch receipt is not typed")
        if (
            NamedToolDispatchReceipt.from_canonical_bytes(
                self.dispatch_receipt.canonical_bytes
            )
            != self.dispatch_receipt
        ):
            raise HybridCompositionError("dispatch receipt canonical round trip failed")
        if not isinstance(self.execution_receipt_bytes, bytes):
            raise HybridCompositionError("composition input execution receipt must be bytes")
        execution = _execution_receipt(self)
        upstream = self.dispatch_receipt.upstream
        if execution.receipt_digest != upstream.execution_receipt_digest:
            raise HybridCompositionError("execution receipt digest differs from dispatch")
        if execution.execution_request_digest != upstream.execution_request_digest:
            raise HybridCompositionError("execution request digest differs from dispatch")
        if execution.tool_request_digest != self.dispatch_receipt.tool_request_digest:
            raise HybridCompositionError("execution request binding differs from dispatch")
        if execution.tool_id is not self.dispatch_receipt.tool_id:
            raise HybridCompositionError("execution tool identity differs from dispatch")
        if execution.outcome.value != self.dispatch_receipt.outcome.value:
            raise HybridCompositionError("execution outcome differs from dispatch")
        if execution.result_count != self.dispatch_receipt.result_count:
            raise HybridCompositionError("execution result count differs from dispatch")
        if execution.no_match != self.dispatch_receipt.no_match:
            raise HybridCompositionError("execution no-match differs from dispatch")
        if upstream.independently_attributable:
            if not isinstance(self.raw_upstream_receipt_bytes, bytes):
                raise HybridCompositionError(
                    "attributed composition input must retain raw upstream bytes"
                )
            if len(self.raw_upstream_receipt_bytes) != upstream.raw_receipt_bytes:
                raise HybridCompositionError("raw upstream byte count differs")
            if _digest(self.raw_upstream_receipt_bytes) != upstream.raw_receipt_digest:
                raise HybridCompositionError("raw upstream digest differs")
        elif self.raw_upstream_receipt_bytes is not None:
            raise HybridCompositionError(
                "non-attributed composition input cannot retain raw upstream bytes"
            )

    @classmethod
    def from_dispatch_result(
        cls,
        result: NamedToolDispatchResult,
    ) -> "HybridCompositionInput":
        if not isinstance(result, NamedToolDispatchResult):
            raise TypeError("composition input requires a typed dispatch result")
        return cls(
            dispatch_receipt=result.receipt,
            execution_receipt_bytes=result.upstream_execution_receipt_bytes,
            raw_upstream_receipt_bytes=result.upstream_raw_receipt_bytes,
        )

    @property
    def tool_id(self) -> NamedToolId:
        return self.dispatch_receipt.tool_id

    @property
    def dispatch_receipt_digest(self) -> str:
        return self.dispatch_receipt.receipt_digest

    @property
    def execution_receipt_digest(self) -> str:
        return _digest(self.execution_receipt_bytes)

    @property
    def query_valid_time(self) -> str | None:
        execution = _execution_receipt(self)
        attribution = (
            execution.branch_attribution
            if isinstance(execution, NamedToolExecutionReceipt)
            else execution.authority_attribution
        )
        return None if attribution is None else attribution.query_valid_time

    @property
    def serving_time(self) -> str | None:
        execution = _execution_receipt(self)
        attribution = (
            execution.branch_attribution
            if isinstance(execution, NamedToolExecutionReceipt)
            else execution.authority_attribution
        )
        return None if attribution is None else attribution.serving_time

    def canonical_value(self) -> dict[str, object]:
        return {
            "tool_id": self.tool_id.value,
            "route": self.dispatch_receipt.route.value,
            "dispatch_receipt_digest": self.dispatch_receipt_digest,
            "dispatch_request_digest": self.dispatch_receipt.dispatch_request_digest,
            "execution_receipt_digest": self.execution_receipt_digest,
            "raw_upstream_receipt_digest": (
                None
                if self.raw_upstream_receipt_bytes is None
                else _digest(self.raw_upstream_receipt_bytes)
            ),
            "raw_upstream_receipt_bytes": (
                0
                if self.raw_upstream_receipt_bytes is None
                else len(self.raw_upstream_receipt_bytes)
            ),
            "outcome": self.dispatch_receipt.outcome.value,
            "reason": (
                None
                if self.dispatch_receipt.reason is None
                else self.dispatch_receipt.reason.value
            ),
            "result_count": self.dispatch_receipt.result_count,
            "no_match": self.dispatch_receipt.no_match,
            "independently_attributable": (
                self.dispatch_receipt.upstream.independently_attributable
            ),
        }


@dataclass(frozen=True, slots=True)
class HybridCompositionRequest:
    request_id: str
    idempotency_key: str
    purpose: HybridCompositionPurpose
    query_valid_time: str
    serving_time: str
    inputs: tuple[HybridCompositionInput, ...]
    reciprocal_rank_k: int = _RRF_K
    candidate_limit: int = _CANDIDATE_LIMIT
    response_limit_bytes: int = _RESPONSE_LIMIT_BYTES

    def __post_init__(self) -> None:
        _uuid(self.request_id, field="hybrid_request_id")
        _require_token(self.idempotency_key, field="hybrid_idempotency_key")
        if not isinstance(self.purpose, HybridCompositionPurpose):
            raise HybridCompositionError("hybrid composition purpose must be typed")
        query_valid = _parse_utc(
            self.query_valid_time,
            field="hybrid_query_valid_time",
        )
        serving = _parse_utc(self.serving_time, field="hybrid_serving_time")
        if query_valid > serving:
            raise HybridCompositionError(
                "hybrid query-valid time cannot exceed serving time"
            )
        if not isinstance(self.inputs, tuple) or len(self.inputs) > _MAX_INPUTS:
            raise HybridCompositionError("hybrid inputs exceed the fixed inventory")
        if not all(isinstance(item, HybridCompositionInput) for item in self.inputs):
            raise HybridCompositionError("hybrid inputs must be typed")
        normalized = tuple(sorted(self.inputs, key=lambda item: _TOOL_ORDER[item.tool_id]))
        tool_ids = tuple(item.tool_id for item in normalized)
        if len(tool_ids) != len(set(tool_ids)):
            raise HybridCompositionError("hybrid inputs must contain unique tool ids")
        if any(item not in _ALL_TOOLS for item in tool_ids):
            raise HybridCompositionError("hybrid input contains an unknown tool")
        object.__setattr__(self, "inputs", normalized)
        for item in normalized:
            if item.query_valid_time is not None and item.query_valid_time != (
                self.query_valid_time
            ):
                raise HybridCompositionError(
                    "upstream query-valid time differs from composition request"
                )
            if item.serving_time is not None and item.serving_time != self.serving_time:
                raise HybridCompositionError(
                    "upstream serving time differs from composition request"
                )
        if self.reciprocal_rank_k != _RRF_K:
            raise HybridCompositionError("reciprocal-rank constant is fixed at 60")
        if self.candidate_limit != _CANDIDATE_LIMIT:
            raise HybridCompositionError("retained candidate limit is fixed at 12")
        if self.response_limit_bytes != _RESPONSE_LIMIT_BYTES:
            raise HybridCompositionError("composition response limit is fixed")

    @property
    def required_tools(self) -> tuple[NamedToolId, ...]:
        return _fixed_tool_sort(
            _BRANCH_TOOLS + _REQUIRED_AUXILIARY_BY_PURPOSE[self.purpose]
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.increment5.hybrid-composition-request.v1",
            "request_id": self.request_id,
            "idempotency_key": self.idempotency_key,
            "purpose": self.purpose.value,
            "query_valid_time": self.query_valid_time,
            "serving_time": self.serving_time,
            "composer_contract_digest": HYBRID_COMPOSER_CONTRACT_DIGEST,
            "required_tools": [item.value for item in self.required_tools],
            "inputs": [item.canonical_value() for item in self.inputs],
            "reciprocal_rank_k": self.reciprocal_rank_k,
            "candidate_limit": self.candidate_limit,
            "response_limit_bytes": self.response_limit_bytes,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical(self.canonical_value())

    @property
    def request_digest(self) -> str:
        return _digest(self.canonical_bytes)


@dataclass(frozen=True, slots=True)
class HybridManifestEntry:
    tool_id: NamedToolId
    mandatory: bool
    state: HybridManifestState
    route: NamedToolExecutionRoute | None
    dispatch_receipt_digest: str | None
    execution_receipt_digest: str | None
    raw_upstream_receipt_digest: str | None
    result_count: int
    no_match: bool
    generation_id: str | None
    generation_digest: str | None
    authority_watermark: int | None
    blocking: bool

    def __post_init__(self) -> None:
        if not isinstance(self.tool_id, NamedToolId):
            raise HybridCompositionError("manifest tool id must be typed")
        if type(self.mandatory) is not bool or type(self.blocking) is not bool:
            raise HybridCompositionError("manifest flags must be boolean")
        if not isinstance(self.state, HybridManifestState):
            raise HybridCompositionError("manifest state must be typed")
        if self.route is not None and not isinstance(
            self.route, NamedToolExecutionRoute
        ):
            raise HybridCompositionError("manifest route must be typed")
        for name in (
            "dispatch_receipt_digest",
            "execution_receipt_digest",
            "raw_upstream_receipt_digest",
            "generation_digest",
        ):
            value = getattr(self, name)
            if value is not None:
                _require_digest(value, field=f"manifest_{name}")
        if self.generation_id is not None:
            _require_token(self.generation_id, field="manifest_generation_id")
        _require_non_negative_int(self.result_count, field="manifest_result_count")
        if type(self.no_match) is not bool:
            raise HybridCompositionError("manifest no_match must be boolean")
        if self.authority_watermark is not None:
            _require_non_negative_int(
                self.authority_watermark,
                field="manifest_authority_watermark",
            )
        absent = self.state in {
            HybridManifestState.MISSING,
            HybridManifestState.NOT_REQUIRED,
        }
        if absent:
            if any(
                value is not None
                for value in (
                    self.route,
                    self.dispatch_receipt_digest,
                    self.execution_receipt_digest,
                    self.raw_upstream_receipt_digest,
                    self.generation_id,
                    self.generation_digest,
                    self.authority_watermark,
                )
            ) or self.result_count != 0 or self.no_match:
                raise HybridCompositionError(
                    "absent manifest entry cannot retain execution evidence"
                )
        elif any(
            value is None
            for value in (
                self.route,
                self.dispatch_receipt_digest,
                self.execution_receipt_digest,
            )
        ):
            raise HybridCompositionError(
                "present manifest entry is missing receipt identity"
            )
        if self.state is HybridManifestState.COMPLETE_RESULTS:
            if self.result_count <= 0 or self.no_match:
                raise HybridCompositionError(
                    "complete-results manifest must retain positive results"
                )
        elif self.state is HybridManifestState.COMPLETE_NO_MATCH:
            if self.result_count != 0 or not self.no_match:
                raise HybridCompositionError(
                    "complete no-match manifest is inconsistent"
                )
        elif not absent and (self.result_count != 0 or self.no_match):
            raise HybridCompositionError(
                "non-complete manifest cannot expose results or no-match"
            )
        expected_blocking = self.mandatory and self.state not in {
            HybridManifestState.COMPLETE_RESULTS,
            HybridManifestState.COMPLETE_NO_MATCH,
        }
        if self.blocking != expected_blocking:
            raise HybridCompositionError("manifest blocking flag is inconsistent")

    def canonical_value(self) -> dict[str, object]:
        return {
            "tool_id": self.tool_id.value,
            "mandatory": self.mandatory,
            "state": self.state.value,
            "route": None if self.route is None else self.route.value,
            "dispatch_receipt_digest": self.dispatch_receipt_digest,
            "execution_receipt_digest": self.execution_receipt_digest,
            "raw_upstream_receipt_digest": self.raw_upstream_receipt_digest,
            "result_count": self.result_count,
            "no_match": self.no_match,
            "generation_id": self.generation_id,
            "generation_digest": self.generation_digest,
            "authority_watermark": self.authority_watermark,
            "blocking": self.blocking,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "HybridManifestEntry":
        required = {
            "tool_id",
            "mandatory",
            "state",
            "route",
            "dispatch_receipt_digest",
            "execution_receipt_digest",
            "raw_upstream_receipt_digest",
            "result_count",
            "no_match",
            "generation_id",
            "generation_digest",
            "authority_watermark",
            "blocking",
        }
        if set(value) != required:
            raise HybridCompositionError("manifest entry keys are not exact")
        return cls(
            tool_id=NamedToolId(value["tool_id"]),
            mandatory=value["mandatory"],
            state=HybridManifestState(value["state"]),
            route=(
                None
                if value["route"] is None
                else NamedToolExecutionRoute(value["route"])
            ),
            dispatch_receipt_digest=value["dispatch_receipt_digest"],
            execution_receipt_digest=value["execution_receipt_digest"],
            raw_upstream_receipt_digest=value["raw_upstream_receipt_digest"],
            result_count=value["result_count"],
            no_match=value["no_match"],
            generation_id=value["generation_id"],
            generation_digest=value["generation_digest"],
            authority_watermark=value["authority_watermark"],
            blocking=value["blocking"],
        )


@dataclass(frozen=True, slots=True)
class HybridPathHop:
    relation_id: str
    predicate: str
    source_id: str
    target_id: str
    direction: str
    relation_decision_digest: str
    relation_provenance_digest: str

    def __post_init__(self) -> None:
        for name in (
            "relation_id",
            "source_id",
            "target_id",
        ):
            _require_text(getattr(self, name), field=f"hybrid_path_{name}")
        _require_token(self.predicate, field="hybrid_path_predicate")
        _require_token(self.direction, field="hybrid_path_direction")
        for name in (
            "relation_decision_digest",
            "relation_provenance_digest",
        ):
            _require_digest(getattr(self, name), field=f"hybrid_path_{name}")

    def canonical_value(self) -> dict[str, str]:
        return {
            "relation_id": self.relation_id,
            "predicate": self.predicate,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "direction": self.direction,
            "relation_decision_digest": self.relation_decision_digest,
            "relation_provenance_digest": self.relation_provenance_digest,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "HybridPathHop":
        required = {
            "relation_id",
            "predicate",
            "source_id",
            "target_id",
            "direction",
            "relation_decision_digest",
            "relation_provenance_digest",
        }
        if set(value) != required or not all(
            isinstance(value[item], str) for item in required
        ):
            raise HybridCompositionError("hybrid path hop keys are not exact")
        return cls(**{item: value[item] for item in required})


@dataclass(frozen=True, slots=True)
class HybridOrigin:
    mode: HybridMode
    tool_id: NamedToolId
    rank: int
    result_id: str
    dependency_root_id: str
    source_identity: str
    passage_id: str | None
    trust_scope: str | None
    provenance_digest: str
    branch_hit_digest: str
    dispatch_receipt_digest: str
    upstream_receipt_digest: str
    exact_match_signal: str | None
    path: tuple[HybridPathHop, ...]
    used_for_score: bool

    def __post_init__(self) -> None:
        if not isinstance(self.mode, HybridMode):
            raise HybridCompositionError("hybrid origin mode must be typed")
        if self.tool_id not in _MODE_BY_TOOL or _MODE_BY_TOOL[self.tool_id] is not self.mode:
            raise HybridCompositionError("hybrid origin tool and mode differ")
        if isinstance(self.rank, bool) or not isinstance(self.rank, int) or not 1 <= self.rank <= 8:
            raise HybridCompositionError("hybrid origin rank exceeds fixed bound")
        for name in ("result_id", "dependency_root_id", "source_identity"):
            _require_text(getattr(self, name), field=f"hybrid_origin_{name}")
        if self.passage_id is not None:
            _require_text(self.passage_id, field="hybrid_origin_passage_id")
        if self.trust_scope is not None:
            _require_token(self.trust_scope, field="hybrid_origin_trust_scope")
        for name in (
            "provenance_digest",
            "branch_hit_digest",
            "dispatch_receipt_digest",
            "upstream_receipt_digest",
        ):
            _require_digest(getattr(self, name), field=f"hybrid_origin_{name}")
        if self.mode is HybridMode.EXACT:
            if self.exact_match_signal is None:
                raise HybridCompositionError("exact origin must retain match signal")
            _require_token(
                self.exact_match_signal,
                field="hybrid_origin_exact_match_signal",
            )
        elif self.exact_match_signal is not None:
            raise HybridCompositionError(
                "non-exact origin cannot retain an exact match signal"
            )
        if not isinstance(self.path, tuple) or not all(
            isinstance(item, HybridPathHop) for item in self.path
        ):
            raise HybridCompositionError("hybrid origin path must be typed")
        if self.mode is HybridMode.ADMITTED_GRAPH:
            if not self.path or len(self.path) > 2:
                raise HybridCompositionError(
                    "graph origin must retain its bounded path"
                )
        elif self.path:
            raise HybridCompositionError("non-graph origin cannot retain a graph path")
        if type(self.used_for_score) is not bool:
            raise HybridCompositionError("hybrid origin score flag must be boolean")

    @property
    def origin_digest(self) -> str:
        return _digest(_canonical(self.canonical_value()))

    def canonical_value(self) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "tool_id": self.tool_id.value,
            "rank": self.rank,
            "result_id": self.result_id,
            "dependency_root_id": self.dependency_root_id,
            "source_identity": self.source_identity,
            "passage_id": self.passage_id,
            "trust_scope": self.trust_scope,
            "provenance_digest": self.provenance_digest,
            "branch_hit_digest": self.branch_hit_digest,
            "dispatch_receipt_digest": self.dispatch_receipt_digest,
            "upstream_receipt_digest": self.upstream_receipt_digest,
            "exact_match_signal": self.exact_match_signal,
            "path": [item.canonical_value() for item in self.path],
            "used_for_score": self.used_for_score,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "HybridOrigin":
        required = {
            "mode",
            "tool_id",
            "rank",
            "result_id",
            "dependency_root_id",
            "source_identity",
            "passage_id",
            "trust_scope",
            "provenance_digest",
            "branch_hit_digest",
            "dispatch_receipt_digest",
            "upstream_receipt_digest",
            "exact_match_signal",
            "path",
            "used_for_score",
        }
        if set(value) != required or not isinstance(value["path"], list):
            raise HybridCompositionError("hybrid origin keys are not exact")
        return cls(
            mode=HybridMode(value["mode"]),
            tool_id=NamedToolId(value["tool_id"]),
            rank=value["rank"],
            result_id=value["result_id"],
            dependency_root_id=value["dependency_root_id"],
            source_identity=value["source_identity"],
            passage_id=value["passage_id"],
            trust_scope=value["trust_scope"],
            provenance_digest=value["provenance_digest"],
            branch_hit_digest=value["branch_hit_digest"],
            dispatch_receipt_digest=value["dispatch_receipt_digest"],
            upstream_receipt_digest=value["upstream_receipt_digest"],
            exact_match_signal=value["exact_match_signal"],
            path=tuple(HybridPathHop.from_mapping(item) for item in value["path"]),
            used_for_score=value["used_for_score"],
        )


@dataclass(frozen=True, slots=True)
class HybridReciprocalRankScore:
    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        _require_positive_int(self.numerator, field="hybrid_score_numerator")
        _require_positive_int(self.denominator, field="hybrid_score_denominator")
        if self.numerator >= self.denominator:
            raise HybridCompositionError("hybrid score must be less than one")
        if math.gcd(self.numerator, self.denominator) != 1:
            raise HybridCompositionError("hybrid score must be reduced")

    @classmethod
    def from_fraction(cls, value: Fraction) -> "HybridReciprocalRankScore":
        if not isinstance(value, Fraction) or value <= 0 or value >= 1:
            raise HybridCompositionError("hybrid score fraction is outside bounds")
        return cls(value.numerator, value.denominator)

    @property
    def fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)

    def canonical_value(self) -> dict[str, int]:
        return {"numerator": self.numerator, "denominator": self.denominator}

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, object]
    ) -> "HybridReciprocalRankScore":
        if set(value) != {"numerator", "denominator"}:
            raise HybridCompositionError("hybrid score keys are not exact")
        return cls(value["numerator"], value["denominator"])


@dataclass(frozen=True, slots=True)
class HybridCandidate:
    final_rank: int
    dependency_root_id: str
    precedence: HybridPrecedence
    score: HybridReciprocalRankScore
    best_branch_rank: int
    contributing_modes: tuple[HybridMode, ...]
    origins: tuple[HybridOrigin, ...]

    def __post_init__(self) -> None:
        _require_positive_int(self.final_rank, field="hybrid_candidate_final_rank")
        _require_text(
            self.dependency_root_id,
            field="hybrid_candidate_dependency_root",
        )
        if not isinstance(self.precedence, HybridPrecedence):
            raise HybridCompositionError("hybrid candidate precedence must be typed")
        if not isinstance(self.score, HybridReciprocalRankScore):
            raise HybridCompositionError("hybrid candidate score must be typed")
        if isinstance(self.best_branch_rank, bool) or not 1 <= self.best_branch_rank <= 8:
            raise HybridCompositionError("hybrid candidate best rank is outside bounds")
        if not isinstance(self.contributing_modes, tuple):
            raise HybridCompositionError("candidate modes must be an immutable tuple")
        expected_modes = _fixed_mode_sort(self.contributing_modes)
        if self.contributing_modes != expected_modes or len(expected_modes) != len(
            set(expected_modes)
        ):
            raise HybridCompositionError(
                "candidate contributing modes must be sorted and unique"
            )
        if not isinstance(self.origins, tuple) or not self.origins:
            raise HybridCompositionError("hybrid candidate must retain origins")
        if len(self.origins) > _MAX_BRANCH_ORIGINS:
            raise HybridCompositionError("hybrid candidate origins exceed fixed bound")
        expected_origins = tuple(sorted(self.origins, key=_origin_sort_key))
        if self.origins != expected_origins:
            raise HybridCompositionError("hybrid candidate origins are not canonical")
        if any(item.dependency_root_id != self.dependency_root_id for item in self.origins):
            raise HybridCompositionError("candidate origins cross dependency roots")
        actual_modes = _fixed_mode_sort({item.mode for item in self.origins})
        if actual_modes != self.contributing_modes:
            raise HybridCompositionError("candidate modes differ from origins")
        selected = [item for item in self.origins if item.used_for_score]
        if {item.mode for item in selected} != set(self.contributing_modes):
            raise HybridCompositionError(
                "candidate must select exactly one score origin per mode"
            )
        if any(sum(1 for item in selected if item.mode is mode) != 1 for mode in actual_modes):
            raise HybridCompositionError(
                "candidate has duplicate score origins for a mode"
            )
        expected_score = sum(
            (Fraction(1, _RRF_K + item.rank) for item in selected),
            start=Fraction(0, 1),
        )
        if self.score.fraction != expected_score:
            raise HybridCompositionError("candidate score differs from fixed RRF")
        if self.best_branch_rank != min(item.rank for item in self.origins):
            raise HybridCompositionError("candidate best rank differs from origins")
        has_exact = any(item.mode is HybridMode.EXACT for item in self.origins)
        expected_precedence = (
            HybridPrecedence.EXACT_FIRST
            if has_exact
            else HybridPrecedence.APPROXIMATE
        )
        if self.precedence is not expected_precedence:
            raise HybridCompositionError("candidate precedence differs from origins")

    @property
    def candidate_digest(self) -> str:
        return _digest(_canonical(self.canonical_value()))

    def canonical_value(self) -> dict[str, object]:
        return {
            "final_rank": self.final_rank,
            "dependency_root_id": self.dependency_root_id,
            "precedence": self.precedence.value,
            "score": self.score.canonical_value(),
            "best_branch_rank": self.best_branch_rank,
            "contributing_modes": [item.value for item in self.contributing_modes],
            "origins": [item.canonical_value() for item in self.origins],
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "HybridCandidate":
        required = {
            "final_rank",
            "dependency_root_id",
            "precedence",
            "score",
            "best_branch_rank",
            "contributing_modes",
            "origins",
        }
        if (
            set(value) != required
            or not isinstance(value["score"], dict)
            or not isinstance(value["contributing_modes"], list)
            or not isinstance(value["origins"], list)
        ):
            raise HybridCompositionError("hybrid candidate keys are not exact")
        return cls(
            final_rank=value["final_rank"],
            dependency_root_id=value["dependency_root_id"],
            precedence=HybridPrecedence(value["precedence"]),
            score=HybridReciprocalRankScore.from_mapping(value["score"]),
            best_branch_rank=value["best_branch_rank"],
            contributing_modes=tuple(
                HybridMode(item) for item in value["contributing_modes"]
            ),
            origins=tuple(HybridOrigin.from_mapping(item) for item in value["origins"]),
        )


@dataclass(frozen=True, slots=True)
class HybridExclusion:
    dependency_root_id: str
    reason: HybridExclusionReason
    would_be_rank: int
    score: HybridReciprocalRankScore
    origin_digests: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_text(
            self.dependency_root_id,
            field="hybrid_exclusion_dependency_root",
        )
        if not isinstance(self.reason, HybridExclusionReason):
            raise HybridCompositionError("hybrid exclusion reason must be typed")
        if self.would_be_rank <= _CANDIDATE_LIMIT:
            raise HybridCompositionError("result-bound exclusion rank is not excluded")
        if not isinstance(self.score, HybridReciprocalRankScore):
            raise HybridCompositionError("hybrid exclusion score must be typed")
        if (
            not isinstance(self.origin_digests, tuple)
            or not self.origin_digests
            or self.origin_digests != tuple(sorted(set(self.origin_digests)))
        ):
            raise HybridCompositionError(
                "hybrid exclusion origin digests must be sorted and unique"
            )
        for item in self.origin_digests:
            _require_digest(item, field="hybrid_exclusion_origin_digest")

    def canonical_value(self) -> dict[str, object]:
        return {
            "dependency_root_id": self.dependency_root_id,
            "reason": self.reason.value,
            "would_be_rank": self.would_be_rank,
            "score": self.score.canonical_value(),
            "origin_digests": list(self.origin_digests),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "HybridExclusion":
        required = {
            "dependency_root_id",
            "reason",
            "would_be_rank",
            "score",
            "origin_digests",
        }
        if (
            set(value) != required
            or not isinstance(value["score"], dict)
            or not isinstance(value["origin_digests"], list)
        ):
            raise HybridCompositionError("hybrid exclusion keys are not exact")
        return cls(
            dependency_root_id=value["dependency_root_id"],
            reason=HybridExclusionReason(value["reason"]),
            would_be_rank=value["would_be_rank"],
            score=HybridReciprocalRankScore.from_mapping(value["score"]),
            origin_digests=tuple(value["origin_digests"]),
        )


def _composition_evidence_digest(
    *,
    manifest: Sequence[HybridManifestEntry],
    candidates: Sequence[HybridCandidate],
    exclusions: Sequence[HybridExclusion],
    known_omission_tools: Sequence[NamedToolId],
    total_dependency_roots: int,
    no_match: bool,
    truncated: bool,
) -> str:
    return _digest(
        _canonical(
            {
                "manifest": [item.canonical_value() for item in manifest],
                "candidates": [item.canonical_value() for item in candidates],
                "exclusions": [item.canonical_value() for item in exclusions],
                "known_omission_tools": [
                    item.value for item in known_omission_tools
                ],
                "total_dependency_roots": total_dependency_roots,
                "no_match": no_match,
                "truncated": truncated,
            }
        )
    )


@dataclass(frozen=True, slots=True)
class HybridCompositionReceipt:
    composition_id: str
    request_digest: str
    request_id: str
    purpose: HybridCompositionPurpose
    query_valid_time: str
    serving_time: str
    contract_digest: str
    outcome: HybridCompositionOutcome
    reason: HybridCompositionReason | None
    manifest: tuple[HybridManifestEntry, ...]
    candidates: tuple[HybridCandidate, ...]
    exclusions: tuple[HybridExclusion, ...]
    known_omission_tools: tuple[NamedToolId, ...]
    total_dependency_roots: int
    no_match: bool
    truncated: bool
    reciprocal_rank_k: int = _RRF_K
    candidate_limit: int = _CANDIDATE_LIMIT
    response_limit_bytes: int = _RESPONSE_LIMIT_BYTES
    raw_scores_compared: bool = False
    fusion_is_authority: bool = False
    external_call_count: int = 0
    provider_call_count: int = 0
    model_call_count: int = 0
    embedding_call_count: int = 0
    provider_spend_micros: int = 0
    authority_effect: str = "NONE"
    qualification_authority_granted: bool = False
    production_activation_authorized: bool = False

    def __post_init__(self) -> None:
        _uuid(self.composition_id, field="hybrid_composition_id")
        _uuid(self.request_id, field="hybrid_receipt_request_id")
        _require_digest(self.request_digest, field="hybrid_request_digest")
        if not isinstance(self.purpose, HybridCompositionPurpose):
            raise HybridCompositionError("receipt purpose must be typed")
        query_valid = _parse_utc(
            self.query_valid_time,
            field="hybrid_receipt_query_valid_time",
        )
        serving = _parse_utc(
            self.serving_time,
            field="hybrid_receipt_serving_time",
        )
        if query_valid > serving:
            raise HybridCompositionError("receipt query-valid time exceeds serving")
        if self.contract_digest != HYBRID_COMPOSER_CONTRACT_DIGEST:
            raise HybridCompositionError("receipt composer contract is not accepted")
        if not isinstance(self.outcome, HybridCompositionOutcome):
            raise HybridCompositionError("composition outcome must be typed")
        if self.reason is not None and not isinstance(
            self.reason, HybridCompositionReason
        ):
            raise HybridCompositionError("composition reason must be typed")
        if not isinstance(self.manifest, tuple) or not all(
            isinstance(item, HybridManifestEntry) for item in self.manifest
        ):
            raise HybridCompositionError("composition manifest must be typed")
        if tuple(item.tool_id for item in self.manifest) != _ALL_TOOLS:
            raise HybridCompositionError("composition manifest must cover six tools")
        if not isinstance(self.candidates, tuple) or not all(
            isinstance(item, HybridCandidate) for item in self.candidates
        ):
            raise HybridCompositionError("composition candidates must be typed")
        if len(self.candidates) > _CANDIDATE_LIMIT:
            raise HybridCompositionError("composition candidates exceed fixed bound")
        if tuple(item.final_rank for item in self.candidates) != tuple(
            range(1, len(self.candidates) + 1)
        ):
            raise HybridCompositionError("composition ranks must be contiguous")
        if len({item.dependency_root_id for item in self.candidates}) != len(
            self.candidates
        ):
            raise HybridCompositionError("composition roots must be unique")
        if tuple(self.candidates) != tuple(
            sorted(self.candidates, key=_candidate_sort_key)
        ):
            raise HybridCompositionError("composition candidates are not ordered")
        if not isinstance(self.exclusions, tuple) or not all(
            isinstance(item, HybridExclusion) for item in self.exclusions
        ):
            raise HybridCompositionError("composition exclusions must be typed")
        if tuple(item.would_be_rank for item in self.exclusions) != tuple(
            range(_CANDIDATE_LIMIT + 1, _CANDIDATE_LIMIT + 1 + len(self.exclusions))
        ):
            raise HybridCompositionError("composition exclusions are not contiguous")
        roots = [item.dependency_root_id for item in self.candidates] + [
            item.dependency_root_id for item in self.exclusions
        ]
        if len(roots) != len(set(roots)):
            raise HybridCompositionError("composition retained and excluded roots overlap")
        if (
            not isinstance(self.known_omission_tools, tuple)
            or self.known_omission_tools
            != _fixed_tool_sort(set(self.known_omission_tools))
        ):
            raise HybridCompositionError(
                "known omission tools must be sorted and unique"
            )
        expected_omissions = _fixed_tool_sort(
            item.tool_id
            for item in self.manifest
            if item.state
            not in {
                HybridManifestState.COMPLETE_RESULTS,
                HybridManifestState.COMPLETE_NO_MATCH,
                HybridManifestState.NOT_REQUIRED,
            }
        )
        if self.known_omission_tools != expected_omissions:
            raise HybridCompositionError("known omissions differ from manifest")
        _require_non_negative_int(
            self.total_dependency_roots,
            field="hybrid_total_dependency_roots",
        )
        if self.total_dependency_roots != len(self.candidates) + len(self.exclusions):
            raise HybridCompositionError("dependency-root total is inconsistent")
        if type(self.no_match) is not bool or type(self.truncated) is not bool:
            raise HybridCompositionError("composition result flags must be boolean")
        if self.truncated != bool(self.exclusions):
            raise HybridCompositionError("composition truncation flag is inconsistent")
        blockers = tuple(item for item in self.manifest if item.blocking)
        optional_noncomplete = tuple(
            item
            for item in self.manifest
            if not item.mandatory
            and item.state
            not in {
                HybridManifestState.COMPLETE_RESULTS,
                HybridManifestState.COMPLETE_NO_MATCH,
                HybridManifestState.NOT_REQUIRED,
            }
        )
        local_failure = self.reason in _COMPOSER_LOCAL_FAILURES
        if blockers:
            if self.candidates or self.exclusions or self.no_match or self.reason is None:
                raise HybridCompositionError(
                    "blocked composition cannot retain candidates or no-match"
                )
            if local_failure:
                raise HybridCompositionError(
                    "manifest-blocked composition cannot claim a local failure"
                )
            expected_outcome, expected_reason = _blocking_outcome(blockers)
            if self.outcome is not expected_outcome or self.reason is not expected_reason:
                raise HybridCompositionError(
                    "blocked composition outcome differs from the manifest"
                )
        elif local_failure:
            if (
                self.outcome is not HybridCompositionOutcome.INCOMPLETE
                or self.candidates
                or self.exclusions
                or self.no_match
            ):
                raise HybridCompositionError(
                    "local composition failure must be empty and incomplete"
                )
        elif self.outcome is HybridCompositionOutcome.COMPLETE:
            if optional_noncomplete:
                raise HybridCompositionError(
                    "complete composition cannot hide optional non-complete evidence"
                )
            if self.candidates:
                if self.no_match or self.reason is not None:
                    raise HybridCompositionError(
                        "positive complete composition cannot state failure"
                    )
            elif not self.no_match or self.reason is not HybridCompositionReason.NO_MATCH:
                raise HybridCompositionError(
                    "empty complete composition must state no-match"
                )
        elif self.outcome is HybridCompositionOutcome.DEGRADED:
            if blockers or not optional_noncomplete:
                raise HybridCompositionError(
                    "degraded composition requires only optional omissions"
                )
            if self.reason is not HybridCompositionReason.OPTIONAL_EVIDENCE_NON_COMPLETE:
                raise HybridCompositionError("degraded composition reason is incorrect")
            if self.no_match:
                raise HybridCompositionError("degraded composition cannot claim no-match")
        elif not blockers:
            raise HybridCompositionError("non-complete outcome requires a blocker")
        if self.reciprocal_rank_k != _RRF_K:
            raise HybridCompositionError("receipt reciprocal-rank constant drifted")
        if self.candidate_limit != _CANDIDATE_LIMIT:
            raise HybridCompositionError("receipt candidate limit drifted")
        if self.response_limit_bytes != _RESPONSE_LIMIT_BYTES:
            raise HybridCompositionError("receipt response limit drifted")
        for name in ("raw_scores_compared", "fusion_is_authority"):
            if type(getattr(self, name)) is not bool or getattr(self, name):
                raise HybridCompositionError(f"{name} must remain false")
        for name in (
            "external_call_count",
            "provider_call_count",
            "model_call_count",
            "embedding_call_count",
            "provider_spend_micros",
        ):
            if getattr(self, name) != 0:
                raise HybridCompositionError(
                    "composition cannot report external work or spend"
                )
        if self.authority_effect != "NONE":
            raise HybridCompositionError("composition cannot claim authority effect")
        for name in (
            "qualification_authority_granted",
            "production_activation_authorized",
        ):
            if type(getattr(self, name)) is not bool or getattr(self, name):
                raise HybridCompositionError(
                    "composition cannot grant qualification or activation"
                )
        evidence_digest = _composition_evidence_digest(
            manifest=self.manifest,
            candidates=self.candidates,
            exclusions=self.exclusions,
            known_omission_tools=self.known_omission_tools,
            total_dependency_roots=self.total_dependency_roots,
            no_match=self.no_match,
            truncated=self.truncated,
        )
        expected_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                "|".join(
                    (
                        self.request_digest,
                        self.outcome.value,
                        "NONE" if self.reason is None else self.reason.value,
                        evidence_digest,
                    )
                ),
            )
        )
        if self.composition_id != expected_id:
            raise HybridCompositionError("composition identity differs from evidence")

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.increment5.hybrid-composition-receipt.v1",
            "composition_id": self.composition_id,
            "request_digest": self.request_digest,
            "request_id": self.request_id,
            "purpose": self.purpose.value,
            "query_valid_time": self.query_valid_time,
            "serving_time": self.serving_time,
            "contract_digest": self.contract_digest,
            "outcome": self.outcome.value,
            "reason": None if self.reason is None else self.reason.value,
            "manifest": [item.canonical_value() for item in self.manifest],
            "candidates": [item.canonical_value() for item in self.candidates],
            "exclusions": [item.canonical_value() for item in self.exclusions],
            "known_omission_tools": [item.value for item in self.known_omission_tools],
            "total_dependency_roots": self.total_dependency_roots,
            "no_match": self.no_match,
            "truncated": self.truncated,
            "reciprocal_rank_k": self.reciprocal_rank_k,
            "candidate_limit": self.candidate_limit,
            "response_limit_bytes": self.response_limit_bytes,
            "raw_scores_compared": self.raw_scores_compared,
            "fusion_is_authority": self.fusion_is_authority,
            "external_call_count": self.external_call_count,
            "provider_call_count": self.provider_call_count,
            "model_call_count": self.model_call_count,
            "embedding_call_count": self.embedding_call_count,
            "provider_spend_micros": self.provider_spend_micros,
            "authority_effect": self.authority_effect,
            "qualification_authority_granted": self.qualification_authority_granted,
            "production_activation_authorized": self.production_activation_authorized,
        }

    @property
    def canonical_bytes(self) -> bytes:
        raw = _canonical(self.canonical_value())
        if len(raw) > self.response_limit_bytes:
            raise HybridCompositionError(
                "composition receipt exceeds the fixed response limit"
            )
        return raw

    @property
    def receipt_digest(self) -> str:
        return _digest(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> "HybridCompositionReceipt":
        value = _decode(raw)
        required = {
            "schema_version",
            "composition_id",
            "request_digest",
            "request_id",
            "purpose",
            "query_valid_time",
            "serving_time",
            "contract_digest",
            "outcome",
            "reason",
            "manifest",
            "candidates",
            "exclusions",
            "known_omission_tools",
            "total_dependency_roots",
            "no_match",
            "truncated",
            "reciprocal_rank_k",
            "candidate_limit",
            "response_limit_bytes",
            "raw_scores_compared",
            "fusion_is_authority",
            "external_call_count",
            "provider_call_count",
            "model_call_count",
            "embedding_call_count",
            "provider_spend_micros",
            "authority_effect",
            "qualification_authority_granted",
            "production_activation_authorized",
        }
        if set(value) != required:
            raise HybridCompositionError("composition receipt keys are not exact")
        if value["schema_version"] != "newsroom.increment5.hybrid-composition-receipt.v1":
            raise HybridCompositionError("composition receipt schema differs")
        for name in ("manifest", "candidates", "exclusions", "known_omission_tools"):
            if not isinstance(value[name], list):
                raise HybridCompositionError(f"composition {name} must be a list")
        receipt = cls(
            composition_id=value["composition_id"],
            request_digest=value["request_digest"],
            request_id=value["request_id"],
            purpose=HybridCompositionPurpose(value["purpose"]),
            query_valid_time=value["query_valid_time"],
            serving_time=value["serving_time"],
            contract_digest=value["contract_digest"],
            outcome=HybridCompositionOutcome(value["outcome"]),
            reason=(
                None
                if value["reason"] is None
                else HybridCompositionReason(value["reason"])
            ),
            manifest=tuple(
                HybridManifestEntry.from_mapping(item) for item in value["manifest"]
            ),
            candidates=tuple(
                HybridCandidate.from_mapping(item) for item in value["candidates"]
            ),
            exclusions=tuple(
                HybridExclusion.from_mapping(item) for item in value["exclusions"]
            ),
            known_omission_tools=tuple(
                NamedToolId(item) for item in value["known_omission_tools"]
            ),
            total_dependency_roots=value["total_dependency_roots"],
            no_match=value["no_match"],
            truncated=value["truncated"],
            reciprocal_rank_k=value["reciprocal_rank_k"],
            candidate_limit=value["candidate_limit"],
            response_limit_bytes=value["response_limit_bytes"],
            raw_scores_compared=value["raw_scores_compared"],
            fusion_is_authority=value["fusion_is_authority"],
            external_call_count=value["external_call_count"],
            provider_call_count=value["provider_call_count"],
            model_call_count=value["model_call_count"],
            embedding_call_count=value["embedding_call_count"],
            provider_spend_micros=value["provider_spend_micros"],
            authority_effect=value["authority_effect"],
            qualification_authority_granted=value["qualification_authority_granted"],
            production_activation_authorized=value["production_activation_authorized"],
        )
        if receipt.canonical_bytes != raw:
            raise HybridCompositionError("retained composition receipt is not canonical")
        return receipt


class HybridCompositionJournal:
    """Immutable first-writer-wins receipt journal for deterministic replay."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS increment5d1_hybrid_receipts (
                    idempotency_key TEXT PRIMARY KEY,
                    request_digest TEXT NOT NULL,
                    receipt_digest TEXT NOT NULL,
                    receipt_bytes BLOB NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def execute(
        self,
        *,
        idempotency_key: str,
        request_digest: str,
        producer: Callable[[], HybridCompositionReceipt],
    ) -> HybridCompositionReceipt:
        _require_token(idempotency_key, field="hybrid_journal_idempotency_key")
        _require_digest(request_digest, field="hybrid_journal_request_digest")
        if not callable(producer):
            raise TypeError("hybrid journal producer must be callable")
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT request_digest,receipt_digest,receipt_bytes
                FROM increment5d1_hybrid_receipts
                WHERE idempotency_key=?
                """,
                (idempotency_key,),
            ).fetchone()
            if row is not None:
                if row[0] != request_digest:
                    raise HybridCompositionError(
                        "hybrid idempotency key is bound to another request"
                    )
                raw = bytes(row[2])
                if _digest(raw) != row[1]:
                    raise HybridCompositionError(
                        "retained hybrid receipt digest is corrupt"
                    )
                return HybridCompositionReceipt.from_canonical_bytes(raw)
            receipt = producer()
            if not isinstance(receipt, HybridCompositionReceipt):
                raise HybridCompositionError("hybrid producer returned wrong type")
            if receipt.request_digest != request_digest:
                raise HybridCompositionError("hybrid producer request digest differs")
            raw = receipt.canonical_bytes
            connection.execute(
                """
                INSERT INTO increment5d1_hybrid_receipts(
                    idempotency_key,request_digest,receipt_digest,receipt_bytes
                ) VALUES(?,?,?,?)
                """,
                (idempotency_key, request_digest, receipt.receipt_digest, raw),
            )
            connection.commit()
            return receipt


class HybridComposer:
    """Compose one exact, bounded, non-authoritative hybrid result."""

    def __init__(self, *, journal: HybridCompositionJournal) -> None:
        if not isinstance(journal, HybridCompositionJournal):
            raise TypeError("hybrid composer requires a typed journal")
        self.journal = journal

    def execute(self, request: HybridCompositionRequest) -> HybridCompositionReceipt:
        if not isinstance(request, HybridCompositionRequest):
            raise TypeError("hybrid composer request must be typed")
        return self.journal.execute(
            idempotency_key=request.idempotency_key,
            request_digest=request.request_digest,
            producer=lambda: self._produce(request),
        )

    def _produce(self, request: HybridCompositionRequest) -> HybridCompositionReceipt:
        manifest = _manifest(request)
        blockers = tuple(item for item in manifest if item.blocking)
        optional_noncomplete = tuple(
            item
            for item in manifest
            if not item.mandatory
            and item.state
            not in {
                HybridManifestState.COMPLETE_RESULTS,
                HybridManifestState.COMPLETE_NO_MATCH,
                HybridManifestState.NOT_REQUIRED,
            }
        )
        if blockers:
            outcome, reason = _blocking_outcome(blockers)
            return _receipt(
                request=request,
                manifest=manifest,
                outcome=outcome,
                reason=reason,
                candidates=(),
                exclusions=(),
                no_match=False,
            )
        try:
            origins = _origins(request)
            candidates, exclusions = _fuse(origins)
        except (HybridCompositionError, ValueError, TypeError):
            return _receipt(
                request=request,
                manifest=manifest,
                outcome=HybridCompositionOutcome.INCOMPLETE,
                reason=HybridCompositionReason.RECEIPT_INVALID,
                candidates=(),
                exclusions=(),
                no_match=False,
            )
        if optional_noncomplete:
            outcome = HybridCompositionOutcome.DEGRADED
            reason = HybridCompositionReason.OPTIONAL_EVIDENCE_NON_COMPLETE
            no_match = False
        elif candidates:
            outcome = HybridCompositionOutcome.COMPLETE
            reason = None
            no_match = False
        else:
            outcome = HybridCompositionOutcome.COMPLETE
            reason = HybridCompositionReason.NO_MATCH
            no_match = True
        receipt = _receipt(
            request=request,
            manifest=manifest,
            outcome=outcome,
            reason=reason,
            candidates=candidates,
            exclusions=exclusions,
            no_match=no_match,
        )
        try:
            receipt.canonical_bytes
        except HybridCompositionError:
            fallback = _receipt(
                request=request,
                manifest=manifest,
                outcome=HybridCompositionOutcome.INCOMPLETE,
                reason=HybridCompositionReason.RESPONSE_LIMIT_EXCEEDED,
                candidates=(),
                exclusions=(),
                no_match=False,
            )
            # The compact fallback is intentionally independent of the oversized
            # candidate payload.  If this fixed six-entry receipt ever exceeds the
            # global limit, fail closed instead of recording an unbounded receipt.
            fallback.canonical_bytes
            return fallback
        return receipt


def _manifest(request: HybridCompositionRequest) -> tuple[HybridManifestEntry, ...]:
    by_tool = {item.tool_id: item for item in request.inputs}
    required = set(request.required_tools)
    values: list[HybridManifestEntry] = []
    for tool_id in _ALL_TOOLS:
        value = by_tool.get(tool_id)
        mandatory = tool_id in required
        if value is None:
            state = (
                HybridManifestState.MISSING
                if mandatory
                else HybridManifestState.NOT_REQUIRED
            )
            values.append(
                HybridManifestEntry(
                    tool_id=tool_id,
                    mandatory=mandatory,
                    state=state,
                    route=None,
                    dispatch_receipt_digest=None,
                    execution_receipt_digest=None,
                    raw_upstream_receipt_digest=None,
                    result_count=0,
                    no_match=False,
                    generation_id=None,
                    generation_digest=None,
                    authority_watermark=None,
                    blocking=mandatory,
                )
            )
            continue
        receipt = value.dispatch_receipt
        upstream = receipt.upstream
        values.append(
            HybridManifestEntry(
                tool_id=tool_id,
                mandatory=mandatory,
                state=_dispatch_state(receipt),
                route=receipt.route,
                dispatch_receipt_digest=value.dispatch_receipt_digest,
                execution_receipt_digest=value.execution_receipt_digest,
                raw_upstream_receipt_digest=(
                    None
                    if value.raw_upstream_receipt_bytes is None
                    else _digest(value.raw_upstream_receipt_bytes)
                ),
                result_count=receipt.result_count,
                no_match=receipt.no_match,
                generation_id=upstream.generation_id,
                generation_digest=upstream.generation_digest,
                authority_watermark=upstream.authority_watermark,
                blocking=mandatory
                and _dispatch_state(receipt)
                not in {
                    HybridManifestState.COMPLETE_RESULTS,
                    HybridManifestState.COMPLETE_NO_MATCH,
                },
            )
        )
    return tuple(values)


def _blocking_outcome(
    blockers: Sequence[HybridManifestEntry],
) -> tuple[HybridCompositionOutcome, HybridCompositionReason]:
    states = {item.state for item in blockers}
    if HybridManifestState.POLICY_BLOCKED in states:
        return (
            HybridCompositionOutcome.POLICY_BLOCKED,
            HybridCompositionReason.MANDATORY_TOOL_POLICY_BLOCKED,
        )
    if HybridManifestState.STALE in states:
        return (
            HybridCompositionOutcome.STALE,
            HybridCompositionReason.MANDATORY_TOOL_STALE,
        )
    if HybridManifestState.UNAVAILABLE in states:
        return (
            HybridCompositionOutcome.UNAVAILABLE,
            HybridCompositionReason.MANDATORY_TOOL_UNAVAILABLE,
        )
    if HybridManifestState.MISSING in states:
        return (
            HybridCompositionOutcome.INCOMPLETE,
            HybridCompositionReason.MISSING_MANDATORY_TOOL,
        )
    return (
        HybridCompositionOutcome.INCOMPLETE,
        HybridCompositionReason.MANDATORY_TOOL_INCOMPLETE,
    )


def _origins(request: HybridCompositionRequest) -> tuple[HybridOrigin, ...]:
    values: list[HybridOrigin] = []
    for item in request.inputs:
        if item.tool_id not in _BRANCH_TOOLS:
            continue
        if item.dispatch_receipt.outcome is not NamedToolDispatchOutcome.COMPLETE:
            continue
        raw = item.raw_upstream_receipt_bytes
        if raw is None:
            raise HybridCompositionError("complete branch is missing raw receipt bytes")
        values.extend(_branch_origins(item, raw))
    if len(values) > _MAX_BRANCH_ORIGINS:
        raise HybridCompositionError("hybrid request exceeds the branch-origin bound")
    return tuple(sorted(values, key=_origin_sort_key))


def _validated_branch_receipt(
    item: HybridCompositionInput,
    raw: bytes,
) -> ExactBranchReceipt | FullTextBranchReceipt | VectorBranchReceipt | AdmittedGraphReceipt:
    # Reject duplicate-key JSON before invoking any legacy parser.
    _decode(raw)
    execution = _execution_receipt(item)
    if not isinstance(execution, NamedToolExecutionReceipt):
        raise HybridCompositionError("branch input retained an authority execution receipt")
    attribution = execution.branch_attribution
    if attribution is None:
        raise HybridCompositionError("complete branch input lacks attribution")
    if attribution.branch_receipt_digest != _digest(raw):
        raise HybridCompositionError("branch receipt digest differs from attribution")
    if attribution.branch_receipt_bytes != len(raw):
        raise HybridCompositionError("branch receipt byte count differs from attribution")

    tool_id = item.tool_id
    if tool_id is NamedToolId.EXACT_AUTHORITY_LOOKUP:
        receipt: (
            ExactBranchReceipt
            | FullTextBranchReceipt
            | VectorBranchReceipt
            | AdmittedGraphReceipt
        ) = ExactBranchReceipt.from_canonical_bytes(raw)
        request_digest = receipt.request_digest
        profile_id = receipt.implementation_version
        generation_id = None
        generation_digest = None
        result_count = len(receipt.hits)
        outcome = receipt.outcome.value
        no_match = receipt.outcome.value == "COMPLETE" and result_count == 0
        started = _parse_utc(receipt.started_at.to_text(), field="exact_started_at")
        completed = _parse_utc(receipt.completed_at.to_text(), field="exact_completed_at")
        if not (
            _parse_utc(attribution.query_valid_time, field="exact_query_valid")
            <= started
            <= completed
            <= _parse_utc(attribution.serving_time, field="exact_serving")
        ):
            raise HybridCompositionError("exact receipt chronology differs from attribution")
    elif tool_id is NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL:
        receipt = FullTextBranchReceipt.from_canonical_bytes(raw)
        request_digest = receipt.request_digest
        profile_id = receipt.snapshot.profile.value
        generation_id = str(receipt.snapshot.generation_id)
        generation_digest = receipt.snapshot.generation_identity_digest
        result_count = len(receipt.hits)
        outcome = receipt.outcome.value
        no_match = receipt.outcome.value == "COMPLETE" and result_count == 0
        started = _parse_utc(receipt.started_at.to_text(), field="fulltext_started_at")
        completed = _parse_utc(receipt.completed_at.to_text(), field="fulltext_completed_at")
        if not (
            _parse_utc(attribution.query_valid_time, field="fulltext_query_valid")
            <= started
            <= completed
            <= _parse_utc(attribution.serving_time, field="fulltext_serving")
        ):
            raise HybridCompositionError("full-text receipt chronology differs from attribution")
    elif tool_id is NamedToolId.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL:
        receipt = VectorBranchReceipt.from_canonical_bytes(raw)
        request_digest = receipt.request_digest
        profile_id = receipt.profile_id
        generation_id = receipt.generation_id
        generation_digest = receipt.generation_digest
        result_count = len(receipt.hits)
        outcome = receipt.outcome.value
        no_match = receipt.outcome.value == "COMPLETE" and result_count == 0
        if (
            receipt.query_valid_time != attribution.query_valid_time
            or receipt.serving_time != attribution.serving_time
        ):
            raise HybridCompositionError("vector receipt time binding differs")
    elif tool_id is NamedToolId.BOUNDED_ADMITTED_GRAPH_TRAVERSAL:
        receipt = AdmittedGraphReceipt.from_canonical_bytes(raw)
        request_digest = receipt.request_digest
        profile_id = receipt.profile_id
        generation_id = receipt.generation_id
        generation_digest = receipt.generation_digest
        result_count = len(receipt.hits)
        outcome = receipt.outcome.value
        no_match = receipt.outcome.value == "COMPLETE" and result_count == 0
        if (
            receipt.query_valid_time != attribution.query_valid_time
            or receipt.serving_time != attribution.serving_time
        ):
            raise HybridCompositionError("graph receipt time binding differs")
    else:
        raise HybridCompositionError("branch tool is not in the fixed fusion inventory")

    if request_digest != attribution.branch_request_digest:
        raise HybridCompositionError("branch request digest differs from attribution")
    if profile_id != attribution.branch_profile_id:
        raise HybridCompositionError("branch profile differs from attribution")
    if (generation_id, generation_digest) != (
        attribution.branch_generation_id,
        attribution.branch_generation_digest,
    ):
        raise HybridCompositionError("branch generation differs from attribution")
    if outcome != attribution.outcome.value:
        raise HybridCompositionError("branch outcome differs from attribution")
    if result_count != attribution.result_count or no_match != attribution.no_match:
        raise HybridCompositionError("branch result semantics differ from attribution")
    return receipt


def _branch_origins(
    item: HybridCompositionInput,
    raw: bytes,
) -> tuple[HybridOrigin, ...]:
    dispatch_digest = item.dispatch_receipt_digest
    upstream_digest = _digest(raw)
    tool_id = item.tool_id
    receipt = _validated_branch_receipt(item, raw)
    if tool_id is NamedToolId.EXACT_AUTHORITY_LOOKUP:
        if not isinstance(receipt, ExactBranchReceipt):
            raise HybridCompositionError("exact receipt parser returned wrong type")
        return tuple(
            HybridOrigin(
                mode=HybridMode.EXACT,
                tool_id=tool_id,
                rank=hit.rank,
                result_id=hit.authority_id,
                dependency_root_id=hit.dependency_root_id,
                source_identity=hit.source_identity,
                passage_id=None,
                trust_scope=hit.trust_scope.value,
                provenance_digest=hit.provenance_digest,
                branch_hit_digest=_branch_hit_digest(hit.canonical_value()),
                dispatch_receipt_digest=dispatch_digest,
                upstream_receipt_digest=upstream_digest,
                exact_match_signal=hit.match_signal,
                path=(),
                used_for_score=False,
            )
            for hit in receipt.hits
        )
    if tool_id is NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL:
        if not isinstance(receipt, FullTextBranchReceipt):
            raise HybridCompositionError("full-text receipt parser returned wrong type")
        return tuple(
            HybridOrigin(
                mode=HybridMode.FULL_TEXT,
                tool_id=tool_id,
                rank=hit.rank,
                result_id=hit.result_key,
                dependency_root_id=hit.dependency_root_id,
                source_identity=hit.source_identity,
                passage_id=hit.passage_id,
                trust_scope=hit.trust_scope.value,
                provenance_digest=_branch_hit_digest(hit.canonical_value()),
                branch_hit_digest=_branch_hit_digest(hit.canonical_value()),
                dispatch_receipt_digest=dispatch_digest,
                upstream_receipt_digest=upstream_digest,
                exact_match_signal=None,
                path=(),
                used_for_score=False,
            )
            for hit in receipt.hits
        )
    if tool_id is NamedToolId.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL:
        if not isinstance(receipt, VectorBranchReceipt):
            raise HybridCompositionError("vector receipt parser returned wrong type")
        return tuple(
            HybridOrigin(
                mode=HybridMode.VECTOR,
                tool_id=tool_id,
                rank=hit.rank,
                result_id=hit.passage_id,
                dependency_root_id=hit.dependency_root_id,
                source_identity=hit.source_revision_id,
                passage_id=hit.passage_id,
                trust_scope=None,
                provenance_digest=hit.provenance_digest,
                branch_hit_digest=_branch_hit_digest(hit.canonical_value()),
                dispatch_receipt_digest=dispatch_digest,
                upstream_receipt_digest=upstream_digest,
                exact_match_signal=None,
                path=(),
                used_for_score=False,
            )
            for hit in receipt.hits
        )
    if tool_id is NamedToolId.BOUNDED_ADMITTED_GRAPH_TRAVERSAL:
        if not isinstance(receipt, AdmittedGraphReceipt):
            raise HybridCompositionError("graph receipt parser returned wrong type")
        return tuple(
            HybridOrigin(
                mode=HybridMode.ADMITTED_GRAPH,
                tool_id=tool_id,
                rank=hit.rank,
                result_id=hit.canonical_id,
                dependency_root_id=hit.dependency_root_id,
                source_identity=hit.source_revision_id,
                passage_id=None,
                trust_scope=TrustScope.ADMITTED.value,
                provenance_digest=hit.provenance_digest,
                branch_hit_digest=_branch_hit_digest(hit.canonical_value()),
                dispatch_receipt_digest=dispatch_digest,
                upstream_receipt_digest=upstream_digest,
                exact_match_signal=None,
                path=tuple(
                    HybridPathHop(
                        relation_id=hop.relation_id,
                        predicate=hop.predicate,
                        source_id=hop.source_id,
                        target_id=hop.target_id,
                        direction=hop.direction.value,
                        relation_decision_digest=hop.relation_decision_digest,
                        relation_provenance_digest=hop.relation_provenance_digest,
                    )
                    for hop in hit.path
                ),
                used_for_score=False,
            )
            for hit in receipt.hits
        )
    raise HybridCompositionError("branch tool is not in the fixed fusion inventory")


def _origin_sort_key(item: HybridOrigin) -> tuple[int, int, str, str]:
    return (
        _MODE_ORDER[item.mode],
        item.rank,
        item.result_id,
        item.branch_hit_digest,
    )


def _candidate_sort_key(item: HybridCandidate) -> tuple[int, Fraction, int, str]:
    return (
        0 if item.precedence is HybridPrecedence.EXACT_FIRST else 1,
        -item.score.fraction,
        item.best_branch_rank,
        item.dependency_root_id,
    )


def _select_score_origins(origins: Sequence[HybridOrigin]) -> tuple[HybridOrigin, ...]:
    ordered = tuple(sorted(origins, key=_origin_sort_key))
    selected_positions: set[int] = set()
    seen_modes: set[HybridMode] = set()
    for index, item in enumerate(ordered):
        if item.mode not in seen_modes:
            seen_modes.add(item.mode)
            selected_positions.add(index)
    return tuple(
        replace(item, used_for_score=index in selected_positions)
        for index, item in enumerate(ordered)
    )


def _fuse(
    origins: tuple[HybridOrigin, ...],
) -> tuple[tuple[HybridCandidate, ...], tuple[HybridExclusion, ...]]:
    grouped: dict[str, list[HybridOrigin]] = {}
    for item in origins:
        grouped.setdefault(item.dependency_root_id, []).append(item)
    ranked: list[HybridCandidate] = []
    for root_id in sorted(grouped):
        root_origins = _select_score_origins(grouped[root_id])
        score = sum(
            (
                Fraction(1, _RRF_K + item.rank)
                for item in root_origins
                if item.used_for_score
            ),
            start=Fraction(0, 1),
        )
        ranked.append(
            HybridCandidate(
                final_rank=1,
                dependency_root_id=root_id,
                precedence=(
                    HybridPrecedence.EXACT_FIRST
                    if any(item.mode is HybridMode.EXACT for item in root_origins)
                    else HybridPrecedence.APPROXIMATE
                ),
                score=HybridReciprocalRankScore.from_fraction(score),
                best_branch_rank=min(item.rank for item in root_origins),
                contributing_modes=_fixed_mode_sort(
                    {item.mode for item in root_origins}
                ),
                origins=root_origins,
            )
        )
    ranked.sort(key=_candidate_sort_key)
    reranked = tuple(
        replace(item, final_rank=index)
        for index, item in enumerate(ranked, start=1)
    )
    retained = reranked[:_CANDIDATE_LIMIT]
    exclusions = tuple(
        HybridExclusion(
            dependency_root_id=item.dependency_root_id,
            reason=HybridExclusionReason.RESULT_BOUND,
            would_be_rank=item.final_rank,
            score=item.score,
            origin_digests=tuple(
                sorted({origin.origin_digest for origin in item.origins})
            ),
        )
        for item in reranked[_CANDIDATE_LIMIT:]
    )
    return retained, exclusions


def _receipt(
    *,
    request: HybridCompositionRequest,
    manifest: tuple[HybridManifestEntry, ...],
    outcome: HybridCompositionOutcome,
    reason: HybridCompositionReason | None,
    candidates: tuple[HybridCandidate, ...],
    exclusions: tuple[HybridExclusion, ...],
    no_match: bool,
) -> HybridCompositionReceipt:
    omissions = _fixed_tool_sort(
        item.tool_id
        for item in manifest
        if item.state
        not in {
            HybridManifestState.COMPLETE_RESULTS,
            HybridManifestState.COMPLETE_NO_MATCH,
            HybridManifestState.NOT_REQUIRED,
        }
    )
    total_dependency_roots = len(candidates) + len(exclusions)
    truncated = bool(exclusions)
    evidence_digest = _composition_evidence_digest(
        manifest=manifest,
        candidates=candidates,
        exclusions=exclusions,
        known_omission_tools=omissions,
        total_dependency_roots=total_dependency_roots,
        no_match=no_match,
        truncated=truncated,
    )
    composition_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            "|".join(
                (
                    request.request_digest,
                    outcome.value,
                    "NONE" if reason is None else reason.value,
                    evidence_digest,
                )
            ),
        )
    )
    return HybridCompositionReceipt(
        composition_id=composition_id,
        request_digest=request.request_digest,
        request_id=request.request_id,
        purpose=request.purpose,
        query_valid_time=request.query_valid_time,
        serving_time=request.serving_time,
        contract_digest=HYBRID_COMPOSER_CONTRACT_DIGEST,
        outcome=outcome,
        reason=reason,
        manifest=manifest,
        candidates=candidates,
        exclusions=exclusions,
        known_omission_tools=omissions,
        total_dependency_roots=total_dependency_roots,
        no_match=no_match,
        truncated=truncated,
    )


__all__ = [
    "HYBRID_COMPOSER_CONTRACT_DIGEST",
    "HybridCandidate",
    "HybridComposer",
    "HybridCompositionError",
    "HybridCompositionInput",
    "HybridCompositionJournal",
    "HybridCompositionOutcome",
    "HybridCompositionPurpose",
    "HybridCompositionReason",
    "HybridCompositionReceipt",
    "HybridCompositionRequest",
    "HybridExclusion",
    "HybridExclusionReason",
    "HybridManifestEntry",
    "HybridManifestState",
    "HybridMode",
    "HybridOrigin",
    "HybridPathHop",
    "HybridPrecedence",
    "HybridReciprocalRankScore",
]
