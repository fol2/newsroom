from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import ast
import json
from pathlib import Path
import sqlite3
import sys
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from newsroom.increment5.named_tool_contracts import (  # noqa: E402
    AdmittedGraphToolRequest,
    AuthenticatedPrincipalProof,
    AuthenticationMethod,
    CanonicalUtc,
    CollisionHydrationToolRequest,
    ExactAuthorityToolRequest,
    ExactLookupKind,
    FullTextToolRequest,
    NAMED_TOOL_BYTE_BUDGET,
    NAMED_TOOL_CONTRACT_DIGEST,
    NAMED_TOOL_POLICY_ID,
    NAMED_TOOL_PROFILE_ID,
    NAMED_TOOL_RESULT_LIMIT,
    NAMED_TOOL_TIMEOUT_MS,
    NamedToolAuthorizationJournal,
    NamedToolAuthorizer,
    NamedToolCall,
    NamedToolContractError,
    NamedToolIdempotencyConflict,
    NamedToolJournalError,
    SourceRevisionImpactToolRequest,
    ToolAuthorizationGrant,
    ToolAuthorizationOutcome,
    ToolAuthorizationReason,
    ToolAuthorizationReceipt,
    ToolIdentity,
    ToolPurpose,
    TOOL_PURPOSE_BY_IDENTITY,
    VectorFixtureToolRequest,
)


DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64


def ts(day: int, hour: int = 12) -> CanonicalUtc:
    return CanonicalUtc(datetime(2026, 8, day, hour, tzinfo=UTC))


def exact_request() -> ExactAuthorityToolRequest:
    return ExactAuthorityToolRequest(
        lookup_kind=ExactLookupKind.SOURCE_NATIVE_ID,
        lookup_value="native-123",
        authority_scope_id="source-registry",
    )


def request_for(tool: ToolIdentity):
    if tool is ToolIdentity.EXACT_AUTHORITY_LOOKUP:
        return exact_request()
    if tool is ToolIdentity.BOUNDED_FULL_TEXT_RETRIEVAL:
        return FullTextToolRequest(
            normalized_query="香港 climate transition",
            locale="mixed",
            window_start=ts(1),
            window_end=ts(5),
        )
    if tool is ToolIdentity.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL:
        return VectorFixtureToolRequest(
            fixture_query_id="fixture-query-001",
            fixture_query_digest=DIGEST_B,
            locale="zh-Hant-HK",
        )
    if tool is ToolIdentity.BOUNDED_ADMITTED_GRAPH_TRAVERSAL:
        return AdmittedGraphToolRequest(root_id="canonical:root")
    if tool is ToolIdentity.COLLISION_AUTHORITY_HYDRATION_LOOKUP:
        return CollisionHydrationToolRequest(
            semantic_collision_digest=DIGEST_C,
            authority_ids=("authority:a", "authority:b"),
        )
    return SourceRevisionImpactToolRequest(
        source_id="source-1",
        revision_id="revision-2",
        window_start=ts(1),
        window_end=ts(5),
    )


def proof(*, actor: str = "retrieval-worker", expires: CanonicalUtc | None = None):
    return AuthenticatedPrincipalProof(
        actor_id=actor,
        issuer_id="newsroom-authn",
        method=AuthenticationMethod.OIDC,
        proof_digest=DIGEST_B,
        policy_digest=DIGEST_A,
        verified_at=ts(5, 10),
        expires_at=expires or ts(7),
    )


def call_for(
    tool: ToolIdentity = ToolIdentity.EXACT_AUTHORITY_LOOKUP,
    *,
    actor: str = "retrieval-worker",
    authentication: AuthenticatedPrincipalProof | None = None,
    request=None,
    scopes: tuple[str, ...] | None = None,
    idempotency_key: str = "call-001",
) -> NamedToolCall:
    selected_request = request or request_for(tool)
    selected_scopes = scopes or selected_request.scope_tokens()
    return NamedToolCall(
        request_id=str(uuid.uuid4()),
        idempotency_key=idempotency_key,
        tool=tool,
        purpose={
            ToolIdentity.EXACT_AUTHORITY_LOOKUP: ToolPurpose.EXACT_IDENTITY_LOOKUP,
            ToolIdentity.BOUNDED_FULL_TEXT_RETRIEVAL: ToolPurpose.RETRIEVE_TEXT_CONTEXT,
            ToolIdentity.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL: (
                ToolPurpose.RETRIEVE_VECTOR_CONTEXT
            ),
            ToolIdentity.BOUNDED_ADMITTED_GRAPH_TRAVERSAL: (
                ToolPurpose.RETRIEVE_ADMITTED_GRAPH_CONTEXT
            ),
            ToolIdentity.COLLISION_AUTHORITY_HYDRATION_LOOKUP: (
                ToolPurpose.HYDRATE_COLLISION_AUTHORITY
            ),
            ToolIdentity.SOURCE_REVISION_IMPACT_LOOKUP: (
                ToolPurpose.ASSESS_SOURCE_REVISION_IMPACT
            ),
        }[tool],
        actor_id=actor,
        authentication=authentication or proof(actor=actor),
        requested_scopes=selected_scopes,
        policy_id=NAMED_TOOL_POLICY_ID,
        policy_digest=DIGEST_A,
        contract_digest=NAMED_TOOL_CONTRACT_DIGEST,
        profile_id=NAMED_TOOL_PROFILE_ID,
        generation_id="generation-5c1-prep",
        query_valid_time=ts(6),
        serving_time=ts(6),
        request=selected_request,
    )


def grant_for(
    call: NamedToolCall,
    *,
    grant_id: str = "grant-001",
    scopes: tuple[str, ...] | None = None,
    policy_digest: str = DIGEST_A,
    valid_from: CanonicalUtc | None = None,
    valid_to: CanonicalUtc | None = None,
) -> ToolAuthorizationGrant:
    return ToolAuthorizationGrant(
        grant_id=grant_id,
        actor_id=call.actor_id,
        tool=call.tool,
        purpose=call.purpose,
        scopes=scopes or call.requested_scopes,
        policy_id=NAMED_TOOL_POLICY_ID,
        policy_digest=policy_digest,
        profile_id=NAMED_TOOL_PROFILE_ID,
        valid_from=valid_from or ts(1),
        valid_to=valid_to or ts(20),
    )


def authorize(call: NamedToolCall, grants=None) -> ToolAuthorizationReceipt:
    actual_grants = [grant_for(call)] if grants is None else grants
    return NamedToolAuthorizer(actual_grants).authorize(call, completed_at=ts(6, 13))


