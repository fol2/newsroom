"""Exact repository-owned grants for Increment 5C named tools."""

from __future__ import annotations

from dataclasses import dataclass

from ._named_tool_common import (
    CanonicalUtc,
    NAMED_TOOL_POLICY_ID,
    NAMED_TOOL_PROFILE_ID,
    NamedToolContractError,
    TOOL_PURPOSE_BY_IDENTITY,
    ToolIdentity,
    ToolPurpose,
    _bounded_unique_tokens,
    _canonical_json_bytes,
    _decode_text_tuple,
    _digest_bytes,
    _parse_enum,
    _require_digest,
    _require_exact_keys,
    _require_mapping,
    _require_text,
    _require_token,
)

@dataclass(frozen=True, slots=True)
class ToolAuthorizationGrant:
    grant_id: str
    actor_id: str
    tool: ToolIdentity
    purpose: ToolPurpose
    scopes: tuple[str, ...]
    policy_id: str
    policy_digest: str
    profile_id: str
    valid_from: CanonicalUtc
    valid_to: CanonicalUtc
    enabled: bool = True

    def __post_init__(self) -> None:
        _require_token(self.grant_id, field="tool_grant_id")
        _require_token(self.actor_id, field="tool_grant_actor_id")
        if not isinstance(self.tool, ToolIdentity):
            raise NamedToolContractError("grant tool must be typed")
        if not isinstance(self.purpose, ToolPurpose):
            raise NamedToolContractError("grant purpose must be typed")
        if TOOL_PURPOSE_BY_IDENTITY[self.tool] is not self.purpose:
            raise NamedToolContractError("grant purpose does not match tool")
        object.__setattr__(
            self,
            "scopes",
            _bounded_unique_tokens(self.scopes, field="tool_grant_scopes", maximum=32),
        )
        if self.policy_id != NAMED_TOOL_POLICY_ID:
            raise NamedToolContractError("grant policy identity drifted")
        _require_digest(self.policy_digest, field="tool_grant_policy_digest")
        if self.profile_id != NAMED_TOOL_PROFILE_ID:
            raise NamedToolContractError("grant profile identity drifted")
        if not isinstance(self.valid_from, CanonicalUtc) or not isinstance(
            self.valid_to, CanonicalUtc
        ):
            raise NamedToolContractError("grant validity times must be typed")
        if self.valid_from >= self.valid_to:
            raise NamedToolContractError("grant validity window is invalid")
        if not isinstance(self.enabled, bool):
            raise NamedToolContractError("grant enabled flag must be boolean")

    @property
    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.increment5.named-tool-grant.v1",
            "grant_id": self.grant_id,
            "actor_id": self.actor_id,
            "tool": self.tool.value,
            "purpose": self.purpose.value,
            "scopes": list(self.scopes),
            "policy_id": self.policy_id,
            "policy_digest": self.policy_digest,
            "profile_id": self.profile_id,
            "valid_from": self.valid_from.to_text(),
            "valid_to": self.valid_to.to_text(),
            "enabled": self.enabled,
        }

    @property
    def grant_digest(self) -> str:
        return _digest_bytes(_canonical_json_bytes(self.canonical_value))

    @classmethod
    def from_mapping(cls, value: object) -> ToolAuthorizationGrant:
        mapping = _require_mapping(value, field="named_tool_grant")
        _require_exact_keys(
            mapping,
            {
                "schema_version",
                "grant_id",
                "actor_id",
                "tool",
                "purpose",
                "scopes",
                "policy_id",
                "policy_digest",
                "profile_id",
                "valid_from",
                "valid_to",
                "enabled",
            },
            field="named_tool_grant",
        )
        if mapping["schema_version"] != "newsroom.increment5.named-tool-grant.v1":
            raise NamedToolContractError("named-tool grant schema version differs")
        return cls(
            grant_id=_require_text(mapping["grant_id"], field="grant_id"),
            actor_id=_require_text(mapping["actor_id"], field="actor_id"),
            tool=_parse_enum(ToolIdentity, mapping["tool"], field="tool"),
            purpose=_parse_enum(ToolPurpose, mapping["purpose"], field="purpose"),
            scopes=_decode_text_tuple(mapping["scopes"], field="scopes"),
            policy_id=_require_text(mapping["policy_id"], field="policy_id"),
            policy_digest=_require_text(
                mapping["policy_digest"], field="policy_digest"
            ),
            profile_id=_require_text(mapping["profile_id"], field="profile_id"),
            valid_from=CanonicalUtc.parse(mapping["valid_from"], field="valid_from"),
            valid_to=CanonicalUtc.parse(mapping["valid_to"], field="valid_to"),
            enabled=mapping["enabled"] if isinstance(mapping["enabled"], bool) else None,  # type: ignore[arg-type]
        )


__all__ = ["ToolAuthorizationGrant"]
