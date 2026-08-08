"""Public pure validator with truthful early-failure ordering.

The stable implementation remains in the private core module.  This facade
handles collision/hydration receipts whose authority read failed before result
coverage existed, then delegates every result-bearing receipt to the complete
semantic validator.  The split keeps UNKNOWN early failures fail-closed without
mistaking their intentionally empty result sets for missing requested coverage.
"""

from __future__ import annotations

from . import _named_tool_authority_receipt_validation_core as _core
from .named_tool_authority_execution import NamedAuthorityExecutionReceipt
from .named_tool_contracts import (
    CollisionHydrationLookupToolRequest,
    NamedToolId,
    NamedToolRequest,
)


NamedAuthorityReceiptValidationError = (
    _core.NamedAuthorityReceiptValidationError
)


def _validate_collision_unknown(
    *,
    request: CollisionHydrationLookupToolRequest,
    execution_receipt: NamedAuthorityExecutionReceipt,
    raw_receipt_bytes: bytes,
    value: dict[str, object],
) -> None:
    if set(value) != _core._COLLISION_AUTHORITY_RECEIPT_KEYS:
        raise NamedAuthorityReceiptValidationError(
            "collision authority receipt keys are not exact"
        )
    context = _core._ValidationContext(
        named_tool_request=request,
        execution_receipt=execution_receipt,
    )
    execution, components = _core._validate_authority_common(
        context,
        raw_receipt_bytes,
        value,
    )
    attribution = execution.authority_attribution
    assert attribution is not None
    expected_schema = (
        "newsroom.increment5.collision-hydration-authority-receipt.v1"
    )
    if value["schema_version"] != expected_schema:
        raise NamedAuthorityReceiptValidationError(
            "collision authority receipt schema differs"
        )
    if (
        value["collision_namespace"] != request.collision_namespace
        or value["collision_key_digest"] != request.collision_key_digest
    ):
        raise NamedAuthorityReceiptValidationError(
            "collision authority request payload differs"
        )
    adapter_config_digest = _core._require_digest(
        value["adapter_config_digest"],
        field="collision_adapter_config_digest",
    )
    expected_authority_request = _core._digest(
        _core._canonical(
            {
                "schema_version": (
                    "newsroom.increment5.collision-hydration-authority-request.v1"
                ),
                "tool_request_digest": request.request_digest,
                "adapter_config_digest": adapter_config_digest,
            }
        )
    )
    if attribution.authority_request_digest != expected_authority_request:
        raise NamedAuthorityReceiptValidationError(
            "collision authority request digest differs"
        )
    _core._validate_component_identities(
        components,
        adapter_config_digest=adapter_config_digest,
        expected=_core._COLLISION_AUTHORITY_COMPONENTS,
        field="collision_authority",
    )
    state = _core._require_token(
        value["collision_state"],
        field="collision_state",
    )
    if state != "UNKNOWN":
        raise NamedAuthorityReceiptValidationError(
            "collision early-failure state must remain UNKNOWN"
        )
    candidate_id = _core._optional_text(
        value["candidate_id"],
        field="collision_candidate_id",
    )
    objects = _core._mapping_list(
        value["objects"],
        field="collision_objects",
        keys=_core._AUTHORITY_OBJECT_KEYS,
    )
    passages = _core._mapping_list(
        value["passages"],
        field="collision_passages",
        keys=_core._AUTHORITY_PASSAGE_KEYS,
    )
    missing_objects = _core._sorted_text_list(
        value["missing_object_ids"],
        field="collision_missing_object_ids",
    )
    missing_passages = _core._sorted_text_list(
        value["missing_passage_ids"],
        field="collision_missing_passage_ids",
    )
    ambiguous_passages = _core._sorted_text_list(
        value["ambiguous_passage_ids"],
        field="collision_ambiguous_passage_ids",
    )
    if candidate_id is not None or any(
        (
            objects,
            passages,
            missing_objects,
            missing_passages,
            ambiguous_passages,
        )
    ):
        raise NamedAuthorityReceiptValidationError(
            "early collision failure cannot retain authority results"
        )
    if value["object_bytes_returned"] is not False:
        raise NamedAuthorityReceiptValidationError(
            "collision authority receipt cannot return object bytes"
        )
    reason = _core._require_token(
        value["reason"],
        field="collision_early_failure_reason",
    )
    expected_outcome = _core._AUTHORITY_EARLY_FAILURES.get(reason)
    actual = (
        value["outcome"],
        value["reason"],
        value["result_count"],
        value["no_match"],
    )
    if expected_outcome is None or actual != (
        expected_outcome,
        reason,
        0,
        False,
    ):
        raise NamedAuthorityReceiptValidationError(
            "collision early-failure outcome is not truthful"
        )


def validate_named_authority_receipt(
    *,
    request: NamedToolRequest,
    execution_receipt: NamedAuthorityExecutionReceipt,
    raw_receipt_bytes: bytes,
) -> None:
    """Validate exact retained authority evidence without reading authority."""

    if not isinstance(execution_receipt, NamedAuthorityExecutionReceipt):
        raise TypeError("authority receipt validator requires typed execution")
    if request.envelope.tool_id is (
        NamedToolId.CURRENT_COLLISION_AND_AUTHORITY_HYDRATION_LOOKUP
    ):
        value = _core._decode(raw_receipt_bytes)
        if value.get("collision_state") == "UNKNOWN":
            if not isinstance(request, CollisionHydrationLookupToolRequest):
                raise NamedAuthorityReceiptValidationError(
                    "collision authority request type differs"
                )
            _validate_collision_unknown(
                request=request,
                execution_receipt=execution_receipt,
                raw_receipt_bytes=raw_receipt_bytes,
                value=value,
            )
            return
    _core.validate_named_authority_receipt(
        request=request,
        execution_receipt=execution_receipt,
        raw_receipt_bytes=raw_receipt_bytes,
    )


__all__ = [
    "NamedAuthorityReceiptValidationError",
    "validate_named_authority_receipt",
]
