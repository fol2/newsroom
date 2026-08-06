"""Strict local contracts and authorization for Increment 5C named read-only tools.

This facade deliberately stops before tool execution. It exposes one closed
named-tool contract, deterministic local authorization receipts, and an
immutable non-authoritative replay journal. No raw query, arbitrary vector,
provider, credential, write session, or activation surface is introduced.
"""

from ._named_tool_common import (
    AuthenticationMethod,
    CanonicalUtc,
    ExactLookupKind,
    NAMED_TOOL_BYTE_BUDGET,
    NAMED_TOOL_DATE_WINDOW_DAYS,
    NAMED_TOOL_GRAPH_DEPTH,
    NAMED_TOOL_GRAPH_FAN_OUT,
    NAMED_TOOL_POLICY_ID,
    NAMED_TOOL_PROFILE_ID,
    NAMED_TOOL_RESULT_LIMIT,
    NAMED_TOOL_TIMEOUT_MS,
    NamedToolContractError,
    NamedToolIdempotencyConflict,
    NamedToolJournalError,
    TOOL_PURPOSE_BY_IDENTITY,
    ToolAuthorizationOutcome,
    ToolAuthorizationReason,
    ToolIdentity,
    ToolPurpose,
)
from .named_tool_authorization import (
    NamedToolAuthorizer,
    ToolAuthorizationGrant,
    ToolAuthorizationReceipt,
)
from .named_tool_journal import JournalResult, NamedToolAuthorizationJournal
from .named_tool_requests import (
    AdmittedGraphToolRequest,
    AuthenticatedPrincipalProof,
    CollisionHydrationToolRequest,
    ExactAuthorityToolRequest,
    FullTextToolRequest,
    NAMED_TOOL_CONTRACT_DIGEST,
    NamedToolCall,
    SourceRevisionImpactToolRequest,
    VectorFixtureToolRequest,
)

__all__ = [
    "AdmittedGraphToolRequest",
    "AuthenticatedPrincipalProof",
    "AuthenticationMethod",
    "CanonicalUtc",
    "CollisionHydrationToolRequest",
    "ExactAuthorityToolRequest",
    "ExactLookupKind",
    "FullTextToolRequest",
    "JournalResult",
    "NAMED_TOOL_BYTE_BUDGET",
    "NAMED_TOOL_CONTRACT_DIGEST",
    "NAMED_TOOL_DATE_WINDOW_DAYS",
    "NAMED_TOOL_GRAPH_DEPTH",
    "NAMED_TOOL_GRAPH_FAN_OUT",
    "NAMED_TOOL_POLICY_ID",
    "NAMED_TOOL_PROFILE_ID",
    "NAMED_TOOL_RESULT_LIMIT",
    "NAMED_TOOL_TIMEOUT_MS",
    "NamedToolAuthorizationJournal",
    "NamedToolAuthorizer",
    "NamedToolCall",
    "NamedToolContractError",
    "NamedToolIdempotencyConflict",
    "NamedToolJournalError",
    "SourceRevisionImpactToolRequest",
    "TOOL_PURPOSE_BY_IDENTITY",
    "ToolAuthorizationGrant",
    "ToolAuthorizationOutcome",
    "ToolAuthorizationReason",
    "ToolAuthorizationReceipt",
    "ToolIdentity",
    "ToolPurpose",
    "VectorFixtureToolRequest",
]
