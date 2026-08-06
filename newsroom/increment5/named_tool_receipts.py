"""Canonical deterministic authorization receipts for Increment 5C."""

from __future__ import annotations

from dataclasses import dataclass
import json
import uuid

from ._named_tool_common import (
    CanonicalUtc,
    NAMED_TOOL_EXTERNAL_CALLS,
    NAMED_TOOL_MODEL_CALLS,
    NAMED_TOOL_EMBEDDING_CALLS,
    NAMED_TOOL_POLICY_ID,
    NAMED_TOOL_PROFILE_ID,
    NAMED_TOOL_PROVIDER_CALLS,
    NAMED_TOOL_PROVIDER_SPEND_MICROS,
    NamedToolContractError,
    TOOL_PURPOSE_BY_IDENTITY,
    ToolAuthorizationOutcome,
    ToolAuthorizationReason,
    ToolIdentity,
    ToolPurpose,
    _bounded_unique_tokens,
    _canonical_json_bytes,
    _decode_text_tuple,
    _digest_bytes,
    _optional_text,
    _parse_enum,
    _require_digest,
    _require_exact_keys,
    _require_int,
    _require_text,
    _require_token,
    _require_uuid5,
)
from .named_tool_contract_identity import NAMED_TOOL_CONTRACT_DIGEST

@dataclass(frozen=True, slots=True)
class ToolAuthorizationReceipt:
    receipt_id: str
    payload_digest: str
    call_digest: str | None
    outcome: ToolAuthorizationOutcome
    reason: ToolAuthorizationReason
    tool: ToolIdentity | None
    purpose: ToolPurpose | None
    actor_id: str | None
    policy_id: str | None
    policy_digest: str | None
    contract_digest: str | None
    profile_id: str | None
    generation_id: str | None
    requested_scopes: tuple[str, ...]
    matched_grant_id: str | None
    matched_grant_digest: str | None
    completed_at: CanonicalUtc
    external_calls: int = NAMED_TOOL_EXTERNAL_CALLS
    provider_calls: int = NAMED_TOOL_PROVIDER_CALLS
    model_calls: int = NAMED_TOOL_MODEL_CALLS
    embedding_calls: int = NAMED_TOOL_EMBEDDING_CALLS
    provider_spend_micros: int = NAMED_TOOL_PROVIDER_SPEND_MICROS

    def __post_init__(self) -> None:
        _require_uuid5(self.receipt_id, field="tool_receipt_id")
        _require_digest(self.payload_digest, field="tool_receipt_payload_digest")
        if not isinstance(self.completed_at, CanonicalUtc):
            raise NamedToolContractError("authorization completion time must be typed")
        if not isinstance(self.outcome, ToolAuthorizationOutcome):
            raise NamedToolContractError("authorization outcome must be typed")
        if not isinstance(self.reason, ToolAuthorizationReason):
            raise NamedToolContractError("authorization reason must be typed")
        allowed_reasons = {
            ToolAuthorizationOutcome.AUTHORIZED: {
                ToolAuthorizationReason.AUTHORIZED,
            },
            ToolAuthorizationOutcome.MALFORMED: {
                ToolAuthorizationReason.MALFORMED_REQUEST,
            },
            ToolAuthorizationOutcome.STALE: {
                ToolAuthorizationReason.PROOF_NOT_YET_VALID,
                ToolAuthorizationReason.PROOF_EXPIRED,
                ToolAuthorizationReason.GRANT_NOT_YET_VALID,
                ToolAuthorizationReason.GRANT_EXPIRED,
                ToolAuthorizationReason.NO_CURRENT_GRANT,
            },
            ToolAuthorizationOutcome.POLICY_BLOCKED: {
                ToolAuthorizationReason.ACTOR_PROOF_MISMATCH,
                ToolAuthorizationReason.POLICY_ID_MISMATCH,
                ToolAuthorizationReason.POLICY_DIGEST_MISMATCH,
                ToolAuthorizationReason.NO_EXACT_GRANT,
                ToolAuthorizationReason.AMBIGUOUS_GRANT,
                ToolAuthorizationReason.SCOPE_NOT_GRANTED,
            },
        }[self.outcome]
        if self.reason not in allowed_reasons:
            raise NamedToolContractError(
                "authorization outcome and reason are semantically inconsistent"
            )
        object.__setattr__(
            self,
            "requested_scopes",
            _bounded_unique_tokens(
                self.requested_scopes,
                field="tool_receipt_scopes",
                maximum=16,
                allow_empty=True,
            ),
        )
        for name in (
            "external_calls",
            "provider_calls",
            "model_calls",
            "embedding_calls",
            "provider_spend_micros",
        ):
            if getattr(self, name) != 0:
                raise NamedToolContractError(
                    "local tool authorization cannot perform external or provider work"
                )
        if self.outcome is ToolAuthorizationOutcome.MALFORMED:
            if self.reason is not ToolAuthorizationReason.MALFORMED_REQUEST:
                raise NamedToolContractError("malformed receipt reason differs")
            if any(
                value is not None
                for value in (
                    self.call_digest,
                    self.tool,
                    self.purpose,
                    self.actor_id,
                    self.policy_id,
                    self.policy_digest,
                    self.contract_digest,
                    self.profile_id,
                    self.generation_id,
                    self.matched_grant_id,
                    self.matched_grant_digest,
                )
            ) or self.requested_scopes:
                raise NamedToolContractError(
                    "malformed receipt cannot trust decoded call fields"
                )
        else:
            if self.call_digest is None:
                raise NamedToolContractError("valid-call receipt requires a call digest")
            _require_digest(self.call_digest, field="tool_receipt_call_digest")
            if self.payload_digest != self.call_digest:
                raise NamedToolContractError(
                    "valid-call receipt payload and call digests must agree"
                )
            if not isinstance(self.tool, ToolIdentity) or not isinstance(
                self.purpose, ToolPurpose
            ):
                raise NamedToolContractError("valid-call receipt requires typed tool data")
            if self.actor_id is None:
                raise NamedToolContractError("valid-call receipt requires actor identity")
            _require_token(self.actor_id, field="tool_receipt_actor_id")
            if self.policy_id != NAMED_TOOL_POLICY_ID:
                raise NamedToolContractError("receipt policy identity drifted")
            if self.policy_digest is None or self.contract_digest is None:
                raise NamedToolContractError("receipt identity digests are absent")
            _require_digest(self.policy_digest, field="tool_receipt_policy_digest")
            _require_digest(self.contract_digest, field="tool_receipt_contract_digest")
            if self.contract_digest != NAMED_TOOL_CONTRACT_DIGEST:
                raise NamedToolContractError("receipt contract identity drifted")
            if self.profile_id != NAMED_TOOL_PROFILE_ID:
                raise NamedToolContractError("receipt profile identity drifted")
            if self.generation_id is None:
                raise NamedToolContractError("receipt generation identity is absent")
            _require_token(self.generation_id, field="tool_receipt_generation_id")
            expected_purpose = TOOL_PURPOSE_BY_IDENTITY[self.tool]
            if self.purpose is not expected_purpose:
                raise NamedToolContractError("receipt purpose does not match tool")
            if self.outcome is ToolAuthorizationOutcome.AUTHORIZED:
                if self.reason is not ToolAuthorizationReason.AUTHORIZED:
                    raise NamedToolContractError("authorized receipt reason differs")
                if self.matched_grant_id is None or self.matched_grant_digest is None:
                    raise NamedToolContractError(
                        "authorized receipt requires exact grant attribution"
                    )
                _require_token(self.matched_grant_id, field="tool_receipt_grant_id")
                _require_digest(
                    self.matched_grant_digest,
                    field="tool_receipt_grant_digest",
                )
            elif self.matched_grant_id is not None or self.matched_grant_digest is not None:
                raise NamedToolContractError(
                    "denied or stale receipt cannot attribute an accepted grant"
                )
        expected_receipt_id = _receipt_id(
            payload_digest=self.payload_digest,
            call_digest=self.call_digest,
            outcome=self.outcome,
            reason=self.reason,
            tool=self.tool,
            purpose=self.purpose,
            actor_id=self.actor_id,
            policy_id=self.policy_id,
            policy_digest=self.policy_digest,
            contract_digest=self.contract_digest,
            profile_id=self.profile_id,
            generation_id=self.generation_id,
            requested_scopes=self.requested_scopes,
            matched_grant_id=self.matched_grant_id,
            matched_grant_digest=self.matched_grant_digest,
            completed_at=self.completed_at,
            external_calls=self.external_calls,
            provider_calls=self.provider_calls,
            model_calls=self.model_calls,
            embedding_calls=self.embedding_calls,
            provider_spend_micros=self.provider_spend_micros,
        )
        if self.receipt_id != expected_receipt_id:
            raise NamedToolContractError("receipt identity does not match evidence")

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.increment5.named-tool-authorization-receipt.v1",
            "receipt_id": self.receipt_id,
            "payload_digest": self.payload_digest,
            "call_digest": self.call_digest,
            "outcome": self.outcome.value,
            "reason": self.reason.value,
            "tool": None if self.tool is None else self.tool.value,
            "purpose": None if self.purpose is None else self.purpose.value,
            "actor_id": self.actor_id,
            "policy_id": self.policy_id,
            "policy_digest": self.policy_digest,
            "contract_digest": self.contract_digest,
            "profile_id": self.profile_id,
            "generation_id": self.generation_id,
            "requested_scopes": list(self.requested_scopes),
            "matched_grant_id": self.matched_grant_id,
            "matched_grant_digest": self.matched_grant_digest,
            "completed_at": self.completed_at.to_text(),
            "external_calls": self.external_calls,
            "provider_calls": self.provider_calls,
            "model_calls": self.model_calls,
            "embedding_calls": self.embedding_calls,
            "provider_spend_micros": self.provider_spend_micros,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.canonical_value())

    @property
    def receipt_digest(self) -> str:
        return _digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, value: bytes) -> ToolAuthorizationReceipt:
        if not isinstance(value, bytes) or not value:
            raise NamedToolContractError("authorization receipt bytes are absent")
        try:
            decoded = json.loads(value)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise NamedToolContractError("authorization receipt is not canonical JSON") from exc
        if not isinstance(decoded, dict) or _canonical_json_bytes(decoded) != value:
            raise NamedToolContractError("authorization receipt JSON is not canonical")
        _require_exact_keys(
            decoded,
            {
                "schema_version",
                "receipt_id",
                "payload_digest",
                "call_digest",
                "outcome",
                "reason",
                "tool",
                "purpose",
                "actor_id",
                "policy_id",
                "policy_digest",
                "contract_digest",
                "profile_id",
                "generation_id",
                "requested_scopes",
                "matched_grant_id",
                "matched_grant_digest",
                "completed_at",
                "external_calls",
                "provider_calls",
                "model_calls",
                "embedding_calls",
                "provider_spend_micros",
            },
            field="named_tool_receipt",
        )
        if (
            decoded["schema_version"]
            != "newsroom.increment5.named-tool-authorization-receipt.v1"
        ):
            raise NamedToolContractError("authorization receipt schema differs")
        tool_value = decoded["tool"]
        purpose_value = decoded["purpose"]
        receipt = cls(
            receipt_id=_require_text(decoded["receipt_id"], field="receipt_id"),
            payload_digest=_require_text(
                decoded["payload_digest"], field="payload_digest"
            ),
            call_digest=_optional_text(decoded["call_digest"], field="call_digest"),
            outcome=_parse_enum(
                ToolAuthorizationOutcome, decoded["outcome"], field="outcome"
            ),
            reason=_parse_enum(
                ToolAuthorizationReason, decoded["reason"], field="reason"
            ),
            tool=(
                None
                if tool_value is None
                else _parse_enum(ToolIdentity, tool_value, field="tool")
            ),
            purpose=(
                None
                if purpose_value is None
                else _parse_enum(ToolPurpose, purpose_value, field="purpose")
            ),
            actor_id=_optional_text(decoded["actor_id"], field="actor_id"),
            policy_id=_optional_text(decoded["policy_id"], field="policy_id"),
            policy_digest=_optional_text(
                decoded["policy_digest"], field="policy_digest"
            ),
            contract_digest=_optional_text(
                decoded["contract_digest"], field="contract_digest"
            ),
            profile_id=_optional_text(decoded["profile_id"], field="profile_id"),
            generation_id=_optional_text(
                decoded["generation_id"], field="generation_id"
            ),
            requested_scopes=_decode_text_tuple(
                decoded["requested_scopes"], field="requested_scopes"
            ),
            matched_grant_id=_optional_text(
                decoded["matched_grant_id"], field="matched_grant_id"
            ),
            matched_grant_digest=_optional_text(
                decoded["matched_grant_digest"], field="matched_grant_digest"
            ),
            completed_at=CanonicalUtc.parse(
                decoded["completed_at"], field="completed_at"
            ),
            external_calls=_require_int(decoded["external_calls"], field="external_calls"),
            provider_calls=_require_int(decoded["provider_calls"], field="provider_calls"),
            model_calls=_require_int(decoded["model_calls"], field="model_calls"),
            embedding_calls=_require_int(
                decoded["embedding_calls"], field="embedding_calls"
            ),
            provider_spend_micros=_require_int(
                decoded["provider_spend_micros"], field="provider_spend_micros"
            ),
        )
        if receipt.canonical_bytes != value:
            raise NamedToolContractError(
                "authorization receipt is not semantically canonical"
            )
        return receipt


def _receipt_id(
    *,
    payload_digest: str,
    call_digest: str | None,
    outcome: ToolAuthorizationOutcome,
    reason: ToolAuthorizationReason,
    tool: ToolIdentity | None,
    purpose: ToolPurpose | None,
    actor_id: str | None,
    policy_id: str | None,
    policy_digest: str | None,
    contract_digest: str | None,
    profile_id: str | None,
    generation_id: str | None,
    requested_scopes: tuple[str, ...],
    matched_grant_id: str | None,
    matched_grant_digest: str | None,
    completed_at: CanonicalUtc,
    external_calls: int,
    provider_calls: int,
    model_calls: int,
    embedding_calls: int,
    provider_spend_micros: int,
) -> str:
    identity = {
        "payload_digest": payload_digest,
        "call_digest": call_digest,
        "outcome": outcome.value,
        "reason": reason.value,
        "tool": None if tool is None else tool.value,
        "purpose": None if purpose is None else purpose.value,
        "actor_id": actor_id,
        "policy_id": policy_id,
        "policy_digest": policy_digest,
        "contract_digest": contract_digest,
        "profile_id": profile_id,
        "generation_id": generation_id,
        "requested_scopes": list(requested_scopes),
        "matched_grant_id": matched_grant_id,
        "matched_grant_digest": matched_grant_digest,
        "completed_at": completed_at.to_text(),
        "external_calls": external_calls,
        "provider_calls": provider_calls,
        "model_calls": model_calls,
        "embedding_calls": embedding_calls,
        "provider_spend_micros": provider_spend_micros,
    }
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            _digest_bytes(_canonical_json_bytes(identity)),
        )
    )


__all__ = ["ToolAuthorizationReceipt"]
