"""Closed request records for Increment 5C named read-only tools."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar, TypeAlias
from collections.abc import Mapping

from ._named_tool_common import (
    CanonicalUtc,
    ExactLookupKind,
    NAMED_TOOL_BYTE_BUDGET,
    NAMED_TOOL_DATE_WINDOW_DAYS,
    NAMED_TOOL_GRAPH_DEPTH,
    NAMED_TOOL_GRAPH_FAN_OUT,
    NAMED_TOOL_RESULT_LIMIT,
    NAMED_TOOL_TIMEOUT_MS,
    NamedToolContractError,
    ToolIdentity,
    _bounded_text,
    _bounded_unique_tokens,
    _canonical_json_bytes,
    _digest_bytes,
    _reject_raw_query_surface,
    _require_digest,
    _require_fixed_bounds,
    _require_locale,
    _require_token,
    _require_window,
)

class ToolRequest:
    TOOL: ClassVar[ToolIdentity]

    def canonical_value(self) -> dict[str, object]:
        raise NotImplementedError

    def scope_tokens(self) -> tuple[str, ...]:
        raise NotImplementedError

    def validate_against_call(self, *, query_valid_time: CanonicalUtc) -> None:
        del query_valid_time

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.canonical_value())

    @property
    def request_digest(self) -> str:
        return _digest_bytes(self.canonical_bytes)


@dataclass(frozen=True, slots=True)
class ExactAuthorityToolRequest(ToolRequest):
    TOOL: ClassVar[ToolIdentity] = ToolIdentity.EXACT_AUTHORITY_LOOKUP

    lookup_kind: ExactLookupKind
    lookup_value: str
    authority_scope_id: str | None
    result_limit: int = NAMED_TOOL_RESULT_LIMIT
    byte_budget: int = NAMED_TOOL_BYTE_BUDGET
    timeout_ms: int = NAMED_TOOL_TIMEOUT_MS

    def __post_init__(self) -> None:
        if not isinstance(self.lookup_kind, ExactLookupKind):
            raise NamedToolContractError("exact lookup kind must be typed")
        _bounded_text(self.lookup_value, field="exact_lookup_value")
        scoped = {
            ExactLookupKind.SOURCE_NATIVE_ID,
            ExactLookupKind.SOURCE_NATIVE_REVISION_TOKEN,
        }
        if self.lookup_kind in scoped:
            if self.authority_scope_id is None:
                raise NamedToolContractError(
                    "scoped exact lookup requires an authority scope"
                )
            _require_token(self.authority_scope_id, field="exact_authority_scope_id")
        elif self.authority_scope_id is not None:
            raise NamedToolContractError(
                "unscoped exact lookup cannot carry an authority scope"
            )
        _require_fixed_bounds(
            result_limit=self.result_limit,
            byte_budget=self.byte_budget,
            timeout_ms=self.timeout_ms,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.increment5.named-tool.exact-request.v1",
            "lookup_kind": self.lookup_kind.value,
            "lookup_value": self.lookup_value,
            "authority_scope_id": self.authority_scope_id,
            "result_limit": self.result_limit,
            "byte_budget": self.byte_budget,
            "timeout_ms": self.timeout_ms,
        }

    def scope_tokens(self) -> tuple[str, ...]:
        values = [
            "tool:exact-authority",
            f"lookup-kind:{self.lookup_kind.value}",
        ]
        if self.authority_scope_id is not None:
            values.append(f"authority:{self.authority_scope_id}")
        return tuple(values)


@dataclass(frozen=True, slots=True)
class FullTextToolRequest(ToolRequest):
    TOOL: ClassVar[ToolIdentity] = ToolIdentity.BOUNDED_FULL_TEXT_RETRIEVAL

    normalized_query: str
    locale: str
    window_start: CanonicalUtc
    window_end: CanonicalUtc
    result_limit: int = NAMED_TOOL_RESULT_LIMIT
    byte_budget: int = NAMED_TOOL_BYTE_BUDGET
    timeout_ms: int = NAMED_TOOL_TIMEOUT_MS

    def __post_init__(self) -> None:
        _bounded_text(
            self.normalized_query,
            field="fulltext_normalized_query",
            maximum_bytes=512,
        )
        _reject_raw_query_surface(self.normalized_query)
        _require_locale(self.locale)
        _require_window(self.window_start, self.window_end)
        _require_fixed_bounds(
            result_limit=self.result_limit,
            byte_budget=self.byte_budget,
            timeout_ms=self.timeout_ms,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.increment5.named-tool.fulltext-request.v1",
            "normalized_query": self.normalized_query,
            "locale": self.locale,
            "window_start": self.window_start.to_text(),
            "window_end": self.window_end.to_text(),
            "result_limit": self.result_limit,
            "byte_budget": self.byte_budget,
            "timeout_ms": self.timeout_ms,
        }

    def scope_tokens(self) -> tuple[str, ...]:
        return ("tool:full-text", f"locale:{self.locale}")

    def validate_against_call(self, *, query_valid_time: CanonicalUtc) -> None:
        if self.window_end > query_valid_time:
            raise NamedToolContractError(
                "full-text window cannot extend after query-valid time"
            )


@dataclass(frozen=True, slots=True)
class VectorFixtureToolRequest(ToolRequest):
    TOOL: ClassVar[ToolIdentity] = (
        ToolIdentity.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL
    )

    fixture_query_id: str
    fixture_query_digest: str
    locale: str
    result_limit: int = NAMED_TOOL_RESULT_LIMIT
    byte_budget: int = NAMED_TOOL_BYTE_BUDGET
    timeout_ms: int = NAMED_TOOL_TIMEOUT_MS

    def __post_init__(self) -> None:
        _require_token(self.fixture_query_id, field="vector_fixture_query_id")
        _require_digest(self.fixture_query_digest, field="vector_fixture_query_digest")
        _require_locale(self.locale)
        _require_fixed_bounds(
            result_limit=self.result_limit,
            byte_budget=self.byte_budget,
            timeout_ms=self.timeout_ms,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.increment5.named-tool.vector-request.v1",
            "fixture_query_id": self.fixture_query_id,
            "fixture_query_digest": self.fixture_query_digest,
            "locale": self.locale,
            "result_limit": self.result_limit,
            "byte_budget": self.byte_budget,
            "timeout_ms": self.timeout_ms,
        }

    def scope_tokens(self) -> tuple[str, ...]:
        return (
            "tool:fixed-point-vector",
            f"fixture:{self.fixture_query_id}",
            f"locale:{self.locale}",
        )


@dataclass(frozen=True, slots=True)
class AdmittedGraphToolRequest(ToolRequest):
    TOOL: ClassVar[ToolIdentity] = ToolIdentity.BOUNDED_ADMITTED_GRAPH_TRAVERSAL

    root_id: str
    direction: str = "BOTH"
    depth: int = NAMED_TOOL_GRAPH_DEPTH
    fan_out: int = NAMED_TOOL_GRAPH_FAN_OUT
    window_days: int = NAMED_TOOL_DATE_WINDOW_DAYS
    result_limit: int = NAMED_TOOL_RESULT_LIMIT
    byte_budget: int = NAMED_TOOL_BYTE_BUDGET
    timeout_ms: int = NAMED_TOOL_TIMEOUT_MS

    def __post_init__(self) -> None:
        _require_token(self.root_id, field="graph_root_id")
        if self.direction != "BOTH":
            raise NamedToolContractError("graph direction must remain fixed at BOTH")
        if self.depth != NAMED_TOOL_GRAPH_DEPTH:
            raise NamedToolContractError("graph depth must remain fixed at 2")
        if self.fan_out != NAMED_TOOL_GRAPH_FAN_OUT:
            raise NamedToolContractError("graph fan-out must remain fixed at 32")
        if self.window_days != NAMED_TOOL_DATE_WINDOW_DAYS:
            raise NamedToolContractError("graph window must remain fixed at 31 days")
        _require_fixed_bounds(
            result_limit=self.result_limit,
            byte_budget=self.byte_budget,
            timeout_ms=self.timeout_ms,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.increment5.named-tool.graph-request.v1",
            "root_id": self.root_id,
            "direction": self.direction,
            "depth": self.depth,
            "fan_out": self.fan_out,
            "window_days": self.window_days,
            "result_limit": self.result_limit,
            "byte_budget": self.byte_budget,
            "timeout_ms": self.timeout_ms,
        }

    def scope_tokens(self) -> tuple[str, ...]:
        return ("tool:admitted-graph", f"root:{self.root_id}")


@dataclass(frozen=True, slots=True)
class CollisionHydrationToolRequest(ToolRequest):
    TOOL: ClassVar[ToolIdentity] = (
        ToolIdentity.COLLISION_AUTHORITY_HYDRATION_LOOKUP
    )

    semantic_collision_digest: str
    authority_ids: tuple[str, ...]
    include_retained_bytes: bool = True
    result_limit: int = NAMED_TOOL_RESULT_LIMIT
    byte_budget: int = NAMED_TOOL_BYTE_BUDGET
    timeout_ms: int = NAMED_TOOL_TIMEOUT_MS

    def __post_init__(self) -> None:
        _require_digest(
            self.semantic_collision_digest,
            field="collision_semantic_digest",
        )
        normalized = _bounded_unique_tokens(
            self.authority_ids,
            field="collision_authority_ids",
            maximum=NAMED_TOOL_RESULT_LIMIT,
        )
        object.__setattr__(self, "authority_ids", normalized)
        if self.include_retained_bytes is not True:
            raise NamedToolContractError(
                "collision hydration must retain governed bytes"
            )
        _require_fixed_bounds(
            result_limit=self.result_limit,
            byte_budget=self.byte_budget,
            timeout_ms=self.timeout_ms,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.increment5.named-tool.hydration-request.v1",
            "semantic_collision_digest": self.semantic_collision_digest,
            "authority_ids": list(self.authority_ids),
            "include_retained_bytes": self.include_retained_bytes,
            "result_limit": self.result_limit,
            "byte_budget": self.byte_budget,
            "timeout_ms": self.timeout_ms,
        }

    def scope_tokens(self) -> tuple[str, ...]:
        return (
            "tool:collision-hydration",
            f"collision:{self.semantic_collision_digest}",
            *(f"authority:{authority_id}" for authority_id in self.authority_ids),
        )


@dataclass(frozen=True, slots=True)
class SourceRevisionImpactToolRequest(ToolRequest):
    TOOL: ClassVar[ToolIdentity] = ToolIdentity.SOURCE_REVISION_IMPACT_LOOKUP

    source_id: str
    revision_id: str | None
    window_start: CanonicalUtc
    window_end: CanonicalUtc
    result_limit: int = NAMED_TOOL_RESULT_LIMIT
    byte_budget: int = NAMED_TOOL_BYTE_BUDGET
    timeout_ms: int = NAMED_TOOL_TIMEOUT_MS

    def __post_init__(self) -> None:
        _require_token(self.source_id, field="impact_source_id")
        if self.revision_id is not None:
            _require_token(self.revision_id, field="impact_revision_id")
        _require_window(self.window_start, self.window_end)
        _require_fixed_bounds(
            result_limit=self.result_limit,
            byte_budget=self.byte_budget,
            timeout_ms=self.timeout_ms,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.increment5.named-tool.impact-request.v1",
            "source_id": self.source_id,
            "revision_id": self.revision_id,
            "window_start": self.window_start.to_text(),
            "window_end": self.window_end.to_text(),
            "result_limit": self.result_limit,
            "byte_budget": self.byte_budget,
            "timeout_ms": self.timeout_ms,
        }

    def scope_tokens(self) -> tuple[str, ...]:
        values = ["tool:source-revision-impact", f"source:{self.source_id}"]
        if self.revision_id is not None:
            values.append(f"revision:{self.revision_id}")
        return tuple(values)

    def validate_against_call(self, *, query_valid_time: CanonicalUtc) -> None:
        if self.window_end > query_valid_time:
            raise NamedToolContractError(
                "impact window cannot extend after query-valid time"
            )


TypedToolRequest: TypeAlias = (
    ExactAuthorityToolRequest
    | FullTextToolRequest
    | VectorFixtureToolRequest
    | AdmittedGraphToolRequest
    | CollisionHydrationToolRequest
    | SourceRevisionImpactToolRequest
)

_REQUEST_TYPE_BY_TOOL: Mapping[ToolIdentity, type[ToolRequest]] = MappingProxyType(
    {
        ToolIdentity.EXACT_AUTHORITY_LOOKUP: ExactAuthorityToolRequest,
        ToolIdentity.BOUNDED_FULL_TEXT_RETRIEVAL: FullTextToolRequest,
        ToolIdentity.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL: VectorFixtureToolRequest,
        ToolIdentity.BOUNDED_ADMITTED_GRAPH_TRAVERSAL: AdmittedGraphToolRequest,
        ToolIdentity.COLLISION_AUTHORITY_HYDRATION_LOOKUP: (
            CollisionHydrationToolRequest
        ),
        ToolIdentity.SOURCE_REVISION_IMPACT_LOOKUP: SourceRevisionImpactToolRequest,
    }
)


__all__ = [
    "AdmittedGraphToolRequest",
    "CollisionHydrationToolRequest",
    "ExactAuthorityToolRequest",
    "FullTextToolRequest",
    "SourceRevisionImpactToolRequest",
    "TypedToolRequest",
    "VectorFixtureToolRequest",
]
