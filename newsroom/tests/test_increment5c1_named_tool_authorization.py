from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from increment5c1_test_support import *  # noqa: F403,F401


def test_exact_grant_authorizes_and_receipt_is_deterministic() -> None:
    call = call_for()
    grant = grant_for(call)
    first = authorize(call, [grant])
    second = authorize(call, [grant])
    assert first == second
    assert first.outcome is ToolAuthorizationOutcome.AUTHORIZED
    assert first.reason is ToolAuthorizationReason.AUTHORIZED
    assert first.matched_grant_id == grant.grant_id
    assert first.matched_grant_digest == grant.grant_digest
    assert first.external_calls == first.provider_calls == first.model_calls == 0
    assert first.embedding_calls == first.provider_spend_micros == 0

def test_actor_proof_mismatch_fails_closed() -> None:
    call = call_for(authentication=proof(actor="other-worker"))
    receipt = authorize(call, [grant_for(call)])
    assert receipt.outcome is ToolAuthorizationOutcome.POLICY_BLOCKED
    assert receipt.reason is ToolAuthorizationReason.ACTOR_PROOF_MISMATCH

def test_expired_or_not_yet_valid_proof_is_stale() -> None:
    expired = call_for(authentication=proof(expires=ts(5, 23)))
    receipt = authorize(expired, [grant_for(expired)])
    assert receipt.outcome is ToolAuthorizationOutcome.STALE
    assert receipt.reason is ToolAuthorizationReason.PROOF_EXPIRED

    future_proof = replace(proof(), verified_at=ts(7), expires_at=ts(8))
    call = call_for(authentication=future_proof)
    receipt = authorize(call, [grant_for(call)])
    assert receipt.outcome is ToolAuthorizationOutcome.STALE
    assert receipt.reason is ToolAuthorizationReason.PROOF_NOT_YET_VALID

def test_wrong_policy_scope_or_missing_exact_grant_is_blocked() -> None:
    call = call_for()
    wrong_policy = grant_for(call, policy_digest=DIGEST_C)
    receipt = authorize(call, [wrong_policy])
    assert receipt.reason is ToolAuthorizationReason.POLICY_DIGEST_MISMATCH

    insufficient = grant_for(call, scopes=("tool:exact-authority",))
    receipt = authorize(call, [insufficient])
    assert receipt.reason is ToolAuthorizationReason.SCOPE_NOT_GRANTED

    receipt = authorize(call, [])
    assert receipt.reason is ToolAuthorizationReason.NO_EXACT_GRANT

def test_expired_future_and_ambiguous_grants_fail_closed() -> None:
    call = call_for()
    expired = grant_for(call, valid_from=ts(1), valid_to=ts(5))
    receipt = authorize(call, [expired])
    assert receipt.outcome is ToolAuthorizationOutcome.STALE
    assert receipt.reason is ToolAuthorizationReason.GRANT_EXPIRED

    future = grant_for(call, valid_from=ts(7), valid_to=ts(20))
    receipt = authorize(call, [future])
    assert receipt.reason is ToolAuthorizationReason.GRANT_NOT_YET_VALID

    first = grant_for(call, grant_id="grant-a")
    second = grant_for(call, grant_id="grant-b")
    receipt = authorize(call, [first, second])
    assert receipt.outcome is ToolAuthorizationOutcome.POLICY_BLOCKED
    assert receipt.reason is ToolAuthorizationReason.AMBIGUOUS_GRANT

def test_malformed_receipt_retains_only_untrusted_payload_digest() -> None:
    payload = call_for().canonical_value()
    del payload["request"]
    receipt = NamedToolAuthorizer([]).authorize_payload(payload, completed_at=ts(6, 13))
    assert receipt.outcome is ToolAuthorizationOutcome.MALFORMED
    assert receipt.reason is ToolAuthorizationReason.MALFORMED_REQUEST
    assert receipt.call_digest is None
    assert receipt.tool is receipt.purpose is receipt.actor_id is None
    assert receipt.requested_scopes == ()
    assert receipt.external_calls == 0

def test_receipt_round_trip_is_byte_identical_and_tamper_detecting() -> None:
    receipt = authorize(call_for())
    parsed = ToolAuthorizationReceipt.from_canonical_bytes(receipt.canonical_bytes)
    assert parsed == receipt
    assert parsed.canonical_bytes == receipt.canonical_bytes

    changed = json.loads(receipt.canonical_bytes)
    changed["actor_id"] = "other-worker"
    tampered = json.dumps(changed, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(NamedToolContractError, match="identity|receipt"):
        ToolAuthorizationReceipt.from_canonical_bytes(tampered)

