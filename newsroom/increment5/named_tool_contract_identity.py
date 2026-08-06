"""Canonical identity of the closed Increment 5C named-tool contract."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from ._named_tool_common import (
    AuthenticationMethod,
    ExactLookupKind,
    NAMED_TOOL_BYTE_BUDGET,
    NAMED_TOOL_DATE_WINDOW_DAYS,
    NAMED_TOOL_GRAPH_DEPTH,
    NAMED_TOOL_GRAPH_FAN_OUT,
    NAMED_TOOL_POLICY_ID,
    NAMED_TOOL_PROFILE_ID,
    NAMED_TOOL_RESULT_LIMIT,
    NAMED_TOOL_TIMEOUT_MS,
    TOOL_PURPOSE_BY_IDENTITY,
    ToolAuthorizationOutcome,
    ToolAuthorizationReason,
    ToolIdentity,
    _canonical_json_bytes,
    _digest_bytes,
)

_REQUEST_KEYS: Mapping[ToolIdentity, frozenset[str]] = MappingProxyType(
    {
    ToolIdentity.EXACT_AUTHORITY_LOOKUP: frozenset(
        {
            "schema_version",
            "lookup_kind",
            "lookup_value",
            "authority_scope_id",
            "result_limit",
            "byte_budget",
            "timeout_ms",
        }
    ),
    ToolIdentity.BOUNDED_FULL_TEXT_RETRIEVAL: frozenset(
        {
            "schema_version",
            "normalized_query",
            "locale",
            "window_start",
            "window_end",
            "result_limit",
            "byte_budget",
            "timeout_ms",
        }
    ),
    ToolIdentity.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL: frozenset(
        {
            "schema_version",
            "fixture_query_id",
            "fixture_query_digest",
            "locale",
            "result_limit",
            "byte_budget",
            "timeout_ms",
        }
    ),
    ToolIdentity.BOUNDED_ADMITTED_GRAPH_TRAVERSAL: frozenset(
        {
            "schema_version",
            "root_id",
            "direction",
            "depth",
            "fan_out",
            "window_days",
            "result_limit",
            "byte_budget",
            "timeout_ms",
        }
    ),
    ToolIdentity.COLLISION_AUTHORITY_HYDRATION_LOOKUP: frozenset(
        {
            "schema_version",
            "semantic_collision_digest",
            "authority_ids",
            "include_retained_bytes",
            "result_limit",
            "byte_budget",
            "timeout_ms",
        }
    ),
    ToolIdentity.SOURCE_REVISION_IMPACT_LOOKUP: frozenset(
        {
            "schema_version",
            "source_id",
            "revision_id",
            "window_start",
            "window_end",
            "result_limit",
            "byte_budget",
            "timeout_ms",
        }
    ),
    }
)


def _contract_value() -> dict[str, object]:
    return {
        "schema_version": "newsroom.increment5.named-tool-contract.v1",
        "policy_id": NAMED_TOOL_POLICY_ID,
        "profile_id": NAMED_TOOL_PROFILE_ID,
        "tools": [tool.value for tool in ToolIdentity],
        "purposes": {
            tool.value: TOOL_PURPOSE_BY_IDENTITY[tool].value for tool in ToolIdentity
        },
        "authentication_methods": [method.value for method in AuthenticationMethod],
        "authorization_outcomes": [
            outcome.value for outcome in ToolAuthorizationOutcome
        ],
        "authorization_reasons": [reason.value for reason in ToolAuthorizationReason],
        "exact_lookup_kinds": [kind.value for kind in ExactLookupKind],
        "request_keys": {
            tool.value: sorted(_REQUEST_KEYS[tool]) for tool in ToolIdentity
        },
        "bounds": {
            "result_limit": NAMED_TOOL_RESULT_LIMIT,
            "timeout_ms": NAMED_TOOL_TIMEOUT_MS,
            "byte_budget": NAMED_TOOL_BYTE_BUDGET,
            "graph_depth": NAMED_TOOL_GRAPH_DEPTH,
            "graph_fan_out": NAMED_TOOL_GRAPH_FAN_OUT,
            "date_window_days": NAMED_TOOL_DATE_WINDOW_DAYS,
        },
        "local_only": True,
        "read_only": True,
        "external_calls": 0,
        "provider_calls": 0,
        "model_calls": 0,
        "embedding_calls": 0,
        "provider_spend_micros": 0,
    }


NAMED_TOOL_CONTRACT_DIGEST = _digest_bytes(_canonical_json_bytes(_contract_value()))


__all__ = ["NAMED_TOOL_CONTRACT_DIGEST"]
