"""Canonical common call envelope for Increment 5C named tools."""

from __future__ import annotations

from dataclasses import dataclass

from ._named_tool_common import (
    AuthenticationMethod,
    CanonicalUtc,
    ExactLookupKind,
    NAMED_TOOL_POLICY_ID,
    NAMED_TOOL_PROFILE_ID,
    NamedToolContractError,
    TOOL_PURPOSE_BY_IDENTITY,
    ToolIdentity,
    ToolPurpose,
    _bounded_text,
    _bounded_unique_tokens,
    _canonical_json_bytes,
    _decode_text_tuple,
    _digest_bytes,
    _optional_text,
    _parse_enum,
    _require_digest,
    _require_exact_keys,
    _require_int,
    _require_mapping,
    _require_text,
    _require_token,
    _require_uuid4,
)
from .named_tool_contract_identity import (
    NAMED_TOOL_CONTRACT_DIGEST,
    _REQUEST_KEYS,
)
from .named_tool_request_types import (
    AdmittedGraphToolRequest,
    CollisionHydrationToolRequest,
    ExactAuthorityToolRequest,
    FullTextToolRequest,
    SourceRevisionImpactToolRequest,
    TypedToolRequest,
    VectorFixtureToolRequest,
    _REQUEST_TYPE_BY_TOOL,
)

@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipalProof:
    actor_id: str
    issuer_id: str
    method: AuthenticationMethod
    proof_digest: str
    policy_digest: str
    verified_at: CanonicalUtc
    expires_at: CanonicalUtc

    def __post_init__(self) -> None:
        _require_token(self.actor_id, field="proof_actor_id")
        _require_token(self.issuer_id, field="proof_issuer_id")
        if not isinstance(self.method, AuthenticationMethod):
            raise NamedToolContractError("authentication method must be typed")
        _require_digest(self.proof_digest, field="authentication_proof_digest")
        _require_digest(self.policy_digest, field="authentication_policy_digest")
        if not isinstance(self.verified_at, CanonicalUtc) or not isinstance(
            self.expires_at, CanonicalUtc
        ):
            raise NamedToolContractError("authentication proof times must be typed")
        if self.verified_at >= self.expires_at:
            raise NamedToolContractError("authentication proof window is invalid")

    def canonical_value(self) -> dict[str, object]:
        return {
            "actor_id": self.actor_id,
            "issuer_id": self.issuer_id,
            "method": self.method.value,
            "proof_digest": self.proof_digest,
            "policy_digest": self.policy_digest,
            "verified_at": self.verified_at.to_text(),
            "expires_at": self.expires_at.to_text(),
        }


@dataclass(frozen=True, slots=True)
class NamedToolCall:
    request_id: str
    idempotency_key: str
    tool: ToolIdentity
    purpose: ToolPurpose
    actor_id: str
    authentication: AuthenticatedPrincipalProof
    requested_scopes: tuple[str, ...]
    policy_id: str
    policy_digest: str
    contract_digest: str
    profile_id: str
    generation_id: str
    query_valid_time: CanonicalUtc
    serving_time: CanonicalUtc
    request: TypedToolRequest

    def __post_init__(self) -> None:
        _require_uuid4(self.request_id, field="tool_request_id")
        _bounded_text(
            self.idempotency_key,
            field="tool_idempotency_key",
            maximum_bytes=256,
        )
        if not isinstance(self.tool, ToolIdentity):
            raise NamedToolContractError("tool identity must be typed")
        if not isinstance(self.purpose, ToolPurpose):
            raise NamedToolContractError("tool purpose must be typed")
        expected_purpose = TOOL_PURPOSE_BY_IDENTITY[self.tool]
        if self.purpose is not expected_purpose:
            raise NamedToolContractError("tool purpose does not match tool identity")
        _require_token(self.actor_id, field="tool_actor_id")
        if type(self.authentication) is not AuthenticatedPrincipalProof:
            raise NamedToolContractError("authentication proof must be exact and typed")
        normalized_scopes = _bounded_unique_tokens(
            self.requested_scopes,
            field="tool_requested_scopes",
            maximum=16,
        )
        object.__setattr__(self, "requested_scopes", normalized_scopes)
        if self.policy_id != NAMED_TOOL_POLICY_ID:
            raise NamedToolContractError("named-tool policy identity drifted")
        _require_digest(self.policy_digest, field="tool_policy_digest")
        _require_digest(self.contract_digest, field="tool_contract_digest")
        if self.contract_digest != NAMED_TOOL_CONTRACT_DIGEST:
            raise NamedToolContractError("named-tool contract identity drifted")
        if self.profile_id != NAMED_TOOL_PROFILE_ID:
            raise NamedToolContractError("named-tool profile identity drifted")
        _require_token(self.generation_id, field="tool_generation_id")
        if not isinstance(self.query_valid_time, CanonicalUtc) or not isinstance(
            self.serving_time, CanonicalUtc
        ):
            raise NamedToolContractError("named-tool call times must be typed")
        if self.query_valid_time > self.serving_time:
            raise NamedToolContractError("query-valid time cannot follow serving time")
        expected_request_type = _REQUEST_TYPE_BY_TOOL[self.tool]
        if type(self.request) is not expected_request_type:
            raise NamedToolContractError("request schema does not match selected tool")
        self.request.validate_against_call(query_valid_time=self.query_valid_time)
        required_scopes = set(self.request.scope_tokens())
        if set(self.requested_scopes) != required_scopes:
            raise NamedToolContractError(
                "requested scope differs from the exact request-derived scope"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.increment5.named-tool-call.v1",
            "request_id": self.request_id,
            "idempotency_key": self.idempotency_key,
            "tool": self.tool.value,
            "purpose": self.purpose.value,
            "actor_id": self.actor_id,
            "authentication": self.authentication.canonical_value(),
            "requested_scopes": list(self.requested_scopes),
            "policy_id": self.policy_id,
            "policy_digest": self.policy_digest,
            "contract_digest": self.contract_digest,
            "profile_id": self.profile_id,
            "generation_id": self.generation_id,
            "query_valid_time": self.query_valid_time.to_text(),
            "serving_time": self.serving_time.to_text(),
            "request": self.request.canonical_value(),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.canonical_value())

    @property
    def call_digest(self) -> str:
        return _digest_bytes(self.canonical_bytes)

    @classmethod
    def from_mapping(cls, value: object) -> NamedToolCall:
        mapping = _require_mapping(value, field="named_tool_call")
        _require_exact_keys(
            mapping,
            {
                "schema_version",
                "request_id",
                "idempotency_key",
                "tool",
                "purpose",
                "actor_id",
                "authentication",
                "requested_scopes",
                "policy_id",
                "policy_digest",
                "contract_digest",
                "profile_id",
                "generation_id",
                "query_valid_time",
                "serving_time",
                "request",
            },
            field="named_tool_call",
        )
        if mapping["schema_version"] != "newsroom.increment5.named-tool-call.v1":
            raise NamedToolContractError("named-tool call schema version differs")
        tool = _parse_enum(ToolIdentity, mapping["tool"], field="tool")
        purpose = _parse_enum(ToolPurpose, mapping["purpose"], field="purpose")
        authentication = _decode_authentication(mapping["authentication"])
        request = _decode_request(tool, mapping["request"])
        return cls(
            request_id=_require_text(mapping["request_id"], field="request_id"),
            idempotency_key=_require_text(
                mapping["idempotency_key"], field="idempotency_key"
            ),
            tool=tool,
            purpose=purpose,
            actor_id=_require_text(mapping["actor_id"], field="actor_id"),
            authentication=authentication,
            requested_scopes=_decode_text_tuple(
                mapping["requested_scopes"], field="requested_scopes"
            ),
            policy_id=_require_text(mapping["policy_id"], field="policy_id"),
            policy_digest=_require_text(
                mapping["policy_digest"], field="policy_digest"
            ),
            contract_digest=_require_text(
                mapping["contract_digest"], field="contract_digest"
            ),
            profile_id=_require_text(mapping["profile_id"], field="profile_id"),
            generation_id=_require_text(
                mapping["generation_id"], field="generation_id"
            ),
            query_valid_time=CanonicalUtc.parse(
                mapping["query_valid_time"], field="query_valid_time"
            ),
            serving_time=CanonicalUtc.parse(
                mapping["serving_time"], field="serving_time"
            ),
            request=request,
        )


def _decode_request(tool: ToolIdentity, value: object) -> TypedToolRequest:
    mapping = _require_mapping(value, field="request")
    _require_exact_keys(mapping, set(_REQUEST_KEYS[tool]), field="request")
    expected_schema = {
        ToolIdentity.EXACT_AUTHORITY_LOOKUP: (
            "newsroom.increment5.named-tool.exact-request.v1"
        ),
        ToolIdentity.BOUNDED_FULL_TEXT_RETRIEVAL: (
            "newsroom.increment5.named-tool.fulltext-request.v1"
        ),
        ToolIdentity.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL: (
            "newsroom.increment5.named-tool.vector-request.v1"
        ),
        ToolIdentity.BOUNDED_ADMITTED_GRAPH_TRAVERSAL: (
            "newsroom.increment5.named-tool.graph-request.v1"
        ),
        ToolIdentity.COLLISION_AUTHORITY_HYDRATION_LOOKUP: (
            "newsroom.increment5.named-tool.hydration-request.v1"
        ),
        ToolIdentity.SOURCE_REVISION_IMPACT_LOOKUP: (
            "newsroom.increment5.named-tool.impact-request.v1"
        ),
    }[tool]
    if mapping["schema_version"] != expected_schema:
        raise NamedToolContractError("named-tool request schema version differs")
    common = {
        "result_limit": _require_int(mapping["result_limit"], field="result_limit"),
        "byte_budget": _require_int(mapping["byte_budget"], field="byte_budget"),
        "timeout_ms": _require_int(mapping["timeout_ms"], field="timeout_ms"),
    }
    if tool is ToolIdentity.EXACT_AUTHORITY_LOOKUP:
        return ExactAuthorityToolRequest(
            lookup_kind=_parse_enum(
                ExactLookupKind, mapping["lookup_kind"], field="lookup_kind"
            ),
            lookup_value=_require_text(mapping["lookup_value"], field="lookup_value"),
            authority_scope_id=_optional_text(
                mapping["authority_scope_id"], field="authority_scope_id"
            ),
            **common,
        )
    if tool is ToolIdentity.BOUNDED_FULL_TEXT_RETRIEVAL:
        return FullTextToolRequest(
            normalized_query=_require_text(
                mapping["normalized_query"], field="normalized_query"
            ),
            locale=_require_text(mapping["locale"], field="locale"),
            window_start=CanonicalUtc.parse(
                mapping["window_start"], field="window_start"
            ),
            window_end=CanonicalUtc.parse(mapping["window_end"], field="window_end"),
            **common,
        )
    if tool is ToolIdentity.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL:
        return VectorFixtureToolRequest(
            fixture_query_id=_require_text(
                mapping["fixture_query_id"], field="fixture_query_id"
            ),
            fixture_query_digest=_require_text(
                mapping["fixture_query_digest"], field="fixture_query_digest"
            ),
            locale=_require_text(mapping["locale"], field="locale"),
            **common,
        )
    if tool is ToolIdentity.BOUNDED_ADMITTED_GRAPH_TRAVERSAL:
        return AdmittedGraphToolRequest(
            root_id=_require_text(mapping["root_id"], field="root_id"),
            direction=_require_text(mapping["direction"], field="direction"),
            depth=_require_int(mapping["depth"], field="depth"),
            fan_out=_require_int(mapping["fan_out"], field="fan_out"),
            window_days=_require_int(mapping["window_days"], field="window_days"),
            **common,
        )
    if tool is ToolIdentity.COLLISION_AUTHORITY_HYDRATION_LOOKUP:
        include_retained = mapping["include_retained_bytes"]
        if not isinstance(include_retained, bool):
            raise NamedToolContractError("include_retained_bytes must be boolean")
        return CollisionHydrationToolRequest(
            semantic_collision_digest=_require_text(
                mapping["semantic_collision_digest"],
                field="semantic_collision_digest",
            ),
            authority_ids=_decode_text_tuple(
                mapping["authority_ids"], field="authority_ids"
            ),
            include_retained_bytes=include_retained,
            **common,
        )
    return SourceRevisionImpactToolRequest(
        source_id=_require_text(mapping["source_id"], field="source_id"),
        revision_id=_optional_text(mapping["revision_id"], field="revision_id"),
        window_start=CanonicalUtc.parse(mapping["window_start"], field="window_start"),
        window_end=CanonicalUtc.parse(mapping["window_end"], field="window_end"),
        **common,
    )


def _decode_authentication(value: object) -> AuthenticatedPrincipalProof:
    mapping = _require_mapping(value, field="authentication")
    _require_exact_keys(
        mapping,
        {
            "actor_id",
            "issuer_id",
            "method",
            "proof_digest",
            "policy_digest",
            "verified_at",
            "expires_at",
        },
        field="authentication",
    )
    return AuthenticatedPrincipalProof(
        actor_id=_require_text(mapping["actor_id"], field="actor_id"),
        issuer_id=_require_text(mapping["issuer_id"], field="issuer_id"),
        method=_parse_enum(
            AuthenticationMethod, mapping["method"], field="method"
        ),
        proof_digest=_require_text(mapping["proof_digest"], field="proof_digest"),
        policy_digest=_require_text(mapping["policy_digest"], field="policy_digest"),
        verified_at=CanonicalUtc.parse(mapping["verified_at"], field="verified_at"),
        expires_at=CanonicalUtc.parse(mapping["expires_at"], field="expires_at"),
    )


__all__ = ["AuthenticatedPrincipalProof", "NamedToolCall"]
