"""Fail-closed local authorization evaluator for Increment 5C named tools."""

from __future__ import annotations

from collections.abc import Iterable

from ._named_tool_common import (
    CanonicalUtc,
    NamedToolContractError,
    ToolAuthorizationOutcome,
    ToolAuthorizationReason,
    _canonical_json_bytes,
    _digest_bytes,
)
from .named_tool_call import NamedToolCall
from .named_tool_grants import ToolAuthorizationGrant
from .named_tool_receipts import ToolAuthorizationReceipt, _receipt_id

class NamedToolAuthorizer:
    """Evaluate one valid call against repository-owned exact grants."""

    def __init__(self, grants: Iterable[ToolAuthorizationGrant]) -> None:
        unsorted = tuple(grants)
        if any(type(grant) is not ToolAuthorizationGrant for grant in unsorted):
            raise NamedToolContractError("authorization grants must be exact typed records")
        materialized = tuple(sorted(unsorted, key=lambda grant: grant.grant_id))
        if len({grant.grant_id for grant in materialized}) != len(materialized):
            raise NamedToolContractError("authorization grants contain duplicate identities")
        self._grants = materialized

    def authorize(
        self,
        call: NamedToolCall,
        *,
        completed_at: CanonicalUtc,
    ) -> ToolAuthorizationReceipt:
        if type(call) is not NamedToolCall:
            raise NamedToolContractError("authorization call must be an exact typed record")
        if not isinstance(completed_at, CanonicalUtc):
            raise NamedToolContractError("authorization completion time must be typed")
        if completed_at < call.serving_time:
            raise NamedToolContractError(
                "authorization cannot complete before the call serving time"
            )
        if call.authentication.actor_id != call.actor_id:
            return _receipt_for_call(
                call,
                outcome=ToolAuthorizationOutcome.POLICY_BLOCKED,
                reason=ToolAuthorizationReason.ACTOR_PROOF_MISMATCH,
                completed_at=completed_at,
            )
        if call.authentication.policy_digest != call.policy_digest:
            return _receipt_for_call(
                call,
                outcome=ToolAuthorizationOutcome.POLICY_BLOCKED,
                reason=ToolAuthorizationReason.POLICY_DIGEST_MISMATCH,
                completed_at=completed_at,
            )
        if call.authentication.verified_at > call.serving_time:
            return _receipt_for_call(
                call,
                outcome=ToolAuthorizationOutcome.STALE,
                reason=ToolAuthorizationReason.PROOF_NOT_YET_VALID,
                completed_at=completed_at,
            )
        if call.authentication.expires_at < call.serving_time:
            return _receipt_for_call(
                call,
                outcome=ToolAuthorizationOutcome.STALE,
                reason=ToolAuthorizationReason.PROOF_EXPIRED,
                completed_at=completed_at,
            )

        identity_matches = tuple(
            grant
            for grant in self._grants
            if grant.enabled
            and grant.actor_id == call.actor_id
            and grant.tool is call.tool
            and grant.purpose is call.purpose
            and grant.policy_id == call.policy_id
            and grant.profile_id == call.profile_id
        )
        if not identity_matches:
            return _receipt_for_call(
                call,
                outcome=ToolAuthorizationOutcome.POLICY_BLOCKED,
                reason=ToolAuthorizationReason.NO_EXACT_GRANT,
                completed_at=completed_at,
            )

        policy_matches = tuple(
            grant
            for grant in identity_matches
            if grant.policy_digest == call.policy_digest
        )
        if not policy_matches:
            return _receipt_for_call(
                call,
                outcome=ToolAuthorizationOutcome.POLICY_BLOCKED,
                reason=ToolAuthorizationReason.POLICY_DIGEST_MISMATCH,
                completed_at=completed_at,
            )

        current = tuple(
            grant
            for grant in policy_matches
            if grant.valid_from <= call.serving_time <= grant.valid_to
            and grant.valid_from <= call.query_valid_time <= grant.valid_to
        )
        if not current:
            if all(grant.valid_from > call.serving_time for grant in policy_matches):
                reason = ToolAuthorizationReason.GRANT_NOT_YET_VALID
            elif all(grant.valid_to < call.query_valid_time for grant in policy_matches):
                reason = ToolAuthorizationReason.GRANT_EXPIRED
            else:
                reason = ToolAuthorizationReason.NO_CURRENT_GRANT
            return _receipt_for_call(
                call,
                outcome=ToolAuthorizationOutcome.STALE,
                reason=reason,
                completed_at=completed_at,
            )

        scope_matches = tuple(
            grant
            for grant in current
            if set(call.requested_scopes).issubset(set(grant.scopes))
        )
        if not scope_matches:
            return _receipt_for_call(
                call,
                outcome=ToolAuthorizationOutcome.POLICY_BLOCKED,
                reason=ToolAuthorizationReason.SCOPE_NOT_GRANTED,
                completed_at=completed_at,
            )
        if len(scope_matches) != 1:
            return _receipt_for_call(
                call,
                outcome=ToolAuthorizationOutcome.POLICY_BLOCKED,
                reason=ToolAuthorizationReason.AMBIGUOUS_GRANT,
                completed_at=completed_at,
            )
        grant = scope_matches[0]
        return _receipt_for_call(
            call,
            outcome=ToolAuthorizationOutcome.AUTHORIZED,
            reason=ToolAuthorizationReason.AUTHORIZED,
            completed_at=completed_at,
            matched_grant=grant,
        )

    def authorize_payload(
        self,
        payload: object,
        *,
        completed_at: CanonicalUtc,
    ) -> ToolAuthorizationReceipt:
        if not isinstance(completed_at, CanonicalUtc):
            raise NamedToolContractError("authorization completion time must be typed")
        payload_bytes = _canonical_json_bytes(payload)
        payload_digest = _digest_bytes(payload_bytes)
        try:
            call = NamedToolCall.from_mapping(payload)
            if call.canonical_bytes != payload_bytes:
                raise NamedToolContractError("named-tool call is not semantically canonical")
        except NamedToolContractError:
            return ToolAuthorizationReceipt(
                receipt_id=_receipt_id(
                    payload_digest=payload_digest,
                    call_digest=None,
                    outcome=ToolAuthorizationOutcome.MALFORMED,
                    reason=ToolAuthorizationReason.MALFORMED_REQUEST,
                    tool=None,
                    purpose=None,
                    actor_id=None,
                    policy_id=None,
                    policy_digest=None,
                    contract_digest=None,
                    profile_id=None,
                    generation_id=None,
                    requested_scopes=(),
                    matched_grant_id=None,
                    matched_grant_digest=None,
                    completed_at=completed_at,
                    external_calls=0,
                    provider_calls=0,
                    model_calls=0,
                    embedding_calls=0,
                    provider_spend_micros=0,
                ),
                payload_digest=payload_digest,
                call_digest=None,
                outcome=ToolAuthorizationOutcome.MALFORMED,
                reason=ToolAuthorizationReason.MALFORMED_REQUEST,
                tool=None,
                purpose=None,
                actor_id=None,
                policy_id=None,
                policy_digest=None,
                contract_digest=None,
                profile_id=None,
                generation_id=None,
                requested_scopes=(),
                matched_grant_id=None,
                matched_grant_digest=None,
                completed_at=completed_at,
            )
        return self.authorize(call, completed_at=completed_at)


def _receipt_for_call(
    call: NamedToolCall,
    *,
    outcome: ToolAuthorizationOutcome,
    reason: ToolAuthorizationReason,
    completed_at: CanonicalUtc,
    matched_grant: ToolAuthorizationGrant | None = None,
) -> ToolAuthorizationReceipt:
    matched_id = None if matched_grant is None else matched_grant.grant_id
    matched_digest = None if matched_grant is None else matched_grant.grant_digest
    return ToolAuthorizationReceipt(
        receipt_id=_receipt_id(
            payload_digest=call.call_digest,
            call_digest=call.call_digest,
            outcome=outcome,
            reason=reason,
            tool=call.tool,
            purpose=call.purpose,
            actor_id=call.actor_id,
            policy_id=call.policy_id,
            policy_digest=call.policy_digest,
            contract_digest=call.contract_digest,
            profile_id=call.profile_id,
            generation_id=call.generation_id,
            requested_scopes=call.requested_scopes,
            matched_grant_id=matched_id,
            matched_grant_digest=matched_digest,
            completed_at=completed_at,
            external_calls=0,
            provider_calls=0,
            model_calls=0,
            embedding_calls=0,
            provider_spend_micros=0,
        ),
        payload_digest=call.call_digest,
        call_digest=call.call_digest,
        outcome=outcome,
        reason=reason,
        tool=call.tool,
        purpose=call.purpose,
        actor_id=call.actor_id,
        policy_id=call.policy_id,
        policy_digest=call.policy_digest,
        contract_digest=call.contract_digest,
        profile_id=call.profile_id,
        generation_id=call.generation_id,
        requested_scopes=call.requested_scopes,
        matched_grant_id=matched_id,
        matched_grant_digest=matched_digest,
        completed_at=completed_at,
    )


__all__ = ["NamedToolAuthorizer"]
