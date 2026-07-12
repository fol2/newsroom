from __future__ import annotations

from dataclasses import dataclass

from .governance_store import (
    DeliveryClaim,
    DeliveryIntent,
    GovernanceStore,
)
from .publishers import RecordingOnlyPublisher


@dataclass(frozen=True, slots=True)
class RecordingOutcome:
    status: str
    intent_id: str
    receipt_digest: str
    publication_digest: str
    public_effect: bool = False
    reused: bool = False


class ShadowPublicationController:
    """Deterministic recording boundary with no live publisher registry."""

    ACTION_VERSION = "recording-v1"

    def __init__(self, store: GovernanceStore) -> None:
        self._store = store
        self._publisher = RecordingOnlyPublisher()

    def _terminal_outcome(
        self,
        intent: DeliveryIntent,
        *,
        reused: bool,
    ) -> RecordingOutcome:
        receipt = self._store.receipt_for_intent(intent.intent_id)
        if receipt is None:
            raise RuntimeError("terminal delivery intent is missing its receipt")
        return RecordingOutcome(
            status=receipt.status,
            intent_id=intent.intent_id,
            receipt_digest=receipt.receipt_digest,
            publication_digest=intent.publication_digest,
            reused=reused,
        )

    def _unknown(
        self,
        intent: DeliveryIntent,
        claim: DeliveryClaim,
        *,
        reason: str,
    ) -> RecordingOutcome:
        receipt = self._store.mark_intent_unknown(
            intent.intent_id,
            claim=claim,
            reason=reason,
        )
        return RecordingOutcome(
            status="UNKNOWN",
            intent_id=intent.intent_id,
            receipt_digest=receipt.receipt_digest,
            publication_digest=intent.publication_digest,
        )

    def record(
        self,
        authority_id: int,
        *,
        owner: str,
        expected_fence: int,
        lease_seconds: int = 60,
    ) -> RecordingOutcome:
        claim = self._store.claim_authority(
            authority_id,
            owner=owner,
            expected_fence=expected_fence,
            lease_seconds=lease_seconds,
        )
        intent = self._store.record_intent(
            claim,
            action_version=self.ACTION_VERSION,
        )
        if intent.state in {"RECORDED_NOT_PUBLISHED", "UNKNOWN"}:
            return self._terminal_outcome(intent, reused=True)
        if intent.owner != claim.owner or intent.fence != claim.fence:
            return self._unknown(
                intent,
                claim,
                reason="PRIOR_INTENT_WITHOUT_TERMINAL_RECEIPT",
            )

        try:
            publication_digest, publication_bytes = self._store.publication_bytes(
                authority_id
            )
        except Exception:
            return self._unknown(
                intent,
                claim,
                reason="PACKAGE_INTEGRITY_INDETERMINATE_AFTER_INTENT",
            )
        if publication_digest != intent.publication_digest:
            return self._unknown(
                intent,
                claim,
                reason="PACKAGE_IDENTITY_CHANGED_AFTER_INTENT",
            )

        try:
            result = self._publisher.record(
                publication_bytes=publication_bytes,
                intent_id=intent.intent_id,
            )
        except Exception:
            return self._unknown(
                intent,
                claim,
                reason="ADAPTER_RETURN_AMBIGUOUS",
            )
        if result.status != "RECORDED_NOT_PUBLISHED":
            return self._unknown(
                intent,
                claim,
                reason="ADAPTER_RETURN_INDETERMINATE",
            )
        try:
            receipt = self._store.record_receipt(
                intent.intent_id,
                owner=claim.owner,
                fence=claim.fence,
                status="RECORDED_NOT_PUBLISHED",
                payload=dict(result.metadata),
            )
        except Exception:
            return self._unknown(
                intent,
                claim,
                reason="RECEIPT_PERSISTENCE_INDETERMINATE",
            )
        return RecordingOutcome(
            status=receipt.status,
            intent_id=intent.intent_id,
            receipt_digest=receipt.receipt_digest,
            publication_digest=publication_digest,
        )
