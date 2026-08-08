"""Public Retrieval Context boundary with truthful non-complete ordering.

The private core owns the immutable contracts, hydration and replay machinery.
This facade keeps result-bearing authority validation unchanged while preserving
valid non-complete authority receipts as evidence instead of trying to hydrate
them as successful passage results.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from . import _retrieval_context_core as _core
from ._retrieval_context_core import *  # noqa: F403
from .named_tool_authority_execution import (
    NamedAuthorityExecutionOutcome,
    NamedAuthorityExecutionReceipt,
)
from .named_tool_authority_receipt_validation import (
    validate_named_authority_receipt,
)
from .named_tool_contracts import NamedToolId, NamedToolPurpose


class RetrievalContextBuilder(_core.RetrievalContextBuilder):
    """Build a context while separating valid failure evidence from results."""

    def _validate_authority(
        self,
        request: _core.RetrievalContextRequest,
        composition: _core.HybridCompositionReceipt,
        planned: Sequence[_core._PlannedCandidate],
    ) -> tuple[
        NamedAuthorityExecutionReceipt,
        Mapping[str, object],
        _core.RetrievalAuthorityEvidence,
        Mapping[str, _core.GovernedPassageReference],
    ]:
        authority_request = request.authority_request
        if authority_request is None:
            raise _core.RetrievalContextError("authority request is missing")
        envelope = authority_request.envelope
        if envelope.tool_id is not (
            NamedToolId.CURRENT_COLLISION_AND_AUTHORITY_HYDRATION_LOOKUP
        ):
            raise _core.RetrievalContextError("authority tool differs")
        if envelope.purpose not in {
            NamedToolPurpose.AUTHORITY_HYDRATION,
            NamedToolPurpose.COLLISION_CHECK,
            NamedToolPurpose.REPLAY_AUDIT,
        }:
            raise _core.RetrievalContextError("authority purpose differs")
        if (
            envelope.actor_id != request.actor_id
            or envelope.authenticated_principal_digest
            != request.authenticated_principal_digest
            or envelope.policy_id != request.policy_id
            or envelope.policy_digest != request.policy_digest
            or envelope.contract_digest != request.named_tool_contract_digest
            or envelope.profile_id != request.profile_id
            or envelope.query_valid_time != request.query_valid_time
        ):
            raise _core.RetrievalContextError(
                "authority caller or contract differs"
            )
        authority_time = _core._parse_utc(
            envelope.serving_time,
            "authority_serving_time",
        )
        if not (
            _core._parse_utc(
                request.composition_serving_time,
                "composition_serving_time",
            )
            <= authority_time
            <= _core._parse_utc(
                request.context_serving_time,
                "context_serving_time",
            )
        ):
            raise _core.RetrievalContextError(
                "authority time is outside context"
            )
        expected_passages = tuple(
            sorted(item.passage_id for item in planned)
        )
        if authority_request.passage_ids != expected_passages:
            raise _core.RetrievalContextError(
                "authority passage plan differs"
            )
        if composition.candidates:
            if authority_request.authority_object_ids:
                raise _core.RetrievalContextError(
                    "positive plan added authority objects"
                )
        elif not authority_request.authority_object_ids:
            raise _core.RetrievalContextError(
                "empty plan lacks authority object"
            )
        if authority_request.collision_key_digest != (
            _core.context_collision_key_digest(composition)
        ):
            raise _core.RetrievalContextError("collision key differs")
        if (
            request.authority_execution_receipt_bytes is None
            or request.authority_receipt_bytes is None
            or request.authority_request_bytes is None
        ):
            raise _core.RetrievalContextError(
                "authority evidence is incomplete"
            )
        execution = NamedAuthorityExecutionReceipt.from_canonical_bytes(
            request.authority_execution_receipt_bytes
        )
        validate_named_authority_receipt(
            request=authority_request,
            execution_receipt=execution,
            raw_receipt_bytes=request.authority_receipt_bytes,
        )
        raw = _core._decode_canonical(
            request.authority_receipt_bytes,
            "authority_receipt",
        )
        authority = _core.RetrievalAuthorityEvidence(
            tool_request_digest=authority_request.request_digest,
            named_request_bytes_digest=_core._digest_bytes(
                request.authority_request_bytes
            ),
            execution_receipt_digest=execution.receipt_digest,
            raw_receipt_digest=_core._digest_bytes(
                request.authority_receipt_bytes
            ),
            adapter_contract_digest=raw["adapter_contract_digest"],
            adapter_config_digest=raw["adapter_config_digest"],
            authority_scope_id=raw["authority_scope_id"],
            authority_watermark=raw["authority_watermark"],
            collision_namespace=raw["collision_namespace"],
            collision_key_digest=raw["collision_key_digest"],
            collision_state=raw["collision_state"],
            candidate_id=raw["candidate_id"],
            requested_object_ids=tuple(
                sorted(authority_request.authority_object_ids)
            ),
            requested_passage_ids=tuple(
                sorted(authority_request.passage_ids)
            ),
            query_valid_time=raw["query_valid_time"],
            serving_time=raw["serving_time"],
            outcome=raw["outcome"],
            reason=raw["reason"],
        )
        if (
            authority.tool_request_digest != execution.tool_request_digest
            or authority.query_valid_time != request.query_valid_time
            or authority.serving_time != envelope.serving_time
        ):
            raise _core.RetrievalContextError(
                "authority evidence binding differs"
            )

        # A truthful non-complete receipt is evidence, not a hydration result.
        # Its semantic validator has already checked coverage/result emptiness or
        # blocked metadata as appropriate.  Preserve it for outcome mapping and
        # never construct usable governed passage references from it.
        if execution.outcome is not NamedAuthorityExecutionOutcome.COMPLETE:
            return execution, raw, authority, {}

        raw_passages = raw["passages"]
        if not isinstance(raw_passages, list) or not all(
            isinstance(item, dict) for item in raw_passages
        ):
            raise _core.RetrievalContextError(
                "authority passages are not objects"
            )
        references = {
            item["passage_id"]: (
                _core.GovernedPassageReference.from_authority(item)
            )
            for item in raw_passages
        }
        if len(references) != len(raw_passages):
            raise _core.RetrievalContextError(
                "authority passages duplicate"
            )
        if tuple(sorted(references)) != expected_passages:
            raise _core.RetrievalContextError(
                "authority result differs from plan"
            )
        return execution, raw, authority, references


__all__ = list(_core.__all__)
