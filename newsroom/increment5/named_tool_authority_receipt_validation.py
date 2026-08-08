"""Pure semantic validation for retained Increment 5 authority receipts.

This module validates the exact, independently attributable receipt bytes
emitted by the two read-only SQLite authority adapters.  It performs no
repository read itself and creates no authority effect.  Keeping the validator
separate lets both 5D1 composition and 5D2 hydration consume one closed,
content-addressed authority-evidence boundary.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Mapping

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes

from .named_tool_authority_adapters import (
    AUTHORITY_PROFILE_ID,
    COLLISION_QUERY_DIGEST,
    NAMED_TOOL_AUTHORITY_ADAPTER_CONTRACT_DIGEST,
    OBJECT_QUERY_DIGEST,
    OCCURRENCE_QUERY_DIGEST,
    OCCURRENCE_TIME_INTEGRITY_QUERY_DIGEST,
    PASSAGE_QUERY_DIGEST,
    REPRESENTATION_QUERY_DIGEST,
    REPRESENTATION_TIME_INTEGRITY_QUERY_DIGEST,
    REVISION_QUERY_DIGEST,
    REVISION_TIME_INTEGRITY_QUERY_DIGEST,
    SOURCE_QUERY_DIGEST,
)
from .named_tool_authority_execution import NamedAuthorityExecutionReceipt
from .named_tool_contracts import (
    NAMED_TOOL_CONTRACT_DIGEST,
    CollisionHydrationLookupToolRequest,
    NamedToolId,
    NamedToolRequest,
    SourceRevisionImpactLookupToolRequest,
)

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,255}\Z")
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_UTC_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{6})?Z\Z")


class NamedAuthorityReceiptValidationError(ValueError):
    """Retained authority receipt bytes are malformed or semantically false."""


def _canonical(value: object) -> bytes:
    try:
        return canonical_json_bytes(value)
    except Exception as exc:
        raise NamedAuthorityReceiptValidationError(
            "authority receipt is not canonical JSON"
        ) from exc


def _digest(value: bytes) -> str:
    return digest_bytes(value)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise NamedAuthorityReceiptValidationError(
                "retained authority JSON contains duplicate keys"
            )
        result[key] = value
    return result


def _decode(raw: bytes) -> dict[str, object]:
    if not isinstance(raw, bytes):
        raise NamedAuthorityReceiptValidationError(
            "retained authority receipt must be bytes"
        )
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_object
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NamedAuthorityReceiptValidationError(
            "retained authority receipt is not JSON"
        ) from exc
    if not isinstance(value, dict):
        raise NamedAuthorityReceiptValidationError(
            "retained authority receipt root is not an object"
        )
    return value


def _require_digest(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise NamedAuthorityReceiptValidationError(
            f"{field} must be a canonical SHA-256 digest"
        )
    return value


def _require_token(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _TOKEN_RE.fullmatch(value) is None:
        raise NamedAuthorityReceiptValidationError(
            f"{field} must be a bounded canonical token"
        )
    return value


def _require_text(value: object, *, field: str, maximum_bytes: int = 1024) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > maximum_bytes
    ):
        raise NamedAuthorityReceiptValidationError(
            f"{field} must be bounded canonical text"
        )
    return value


def _require_non_negative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise NamedAuthorityReceiptValidationError(
            f"{field} must be a non-negative integer"
        )
    return value


def _require_positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise NamedAuthorityReceiptValidationError(
            f"{field} must be a positive integer"
        )
    return value


def _parse_utc(value: object, *, field: str) -> datetime:
    if not isinstance(value, str) or _UTC_RE.fullmatch(value) is None:
        raise NamedAuthorityReceiptValidationError(
            f"{field} must be canonical UTC text"
        )
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise NamedAuthorityReceiptValidationError(
            f"{field} must be canonical UTC text"
        ) from exc
    if parsed.tzinfo != UTC:
        raise NamedAuthorityReceiptValidationError(f"{field} must use UTC")
    return parsed


@dataclass(frozen=True, slots=True)
class _ValidationContext:
    named_tool_request: NamedToolRequest
    execution_receipt: NamedAuthorityExecutionReceipt

    @property
    def tool_request_digest(self) -> str:
        return self.named_tool_request.request_digest

    @property
    def tool_id(self) -> NamedToolId:
        return self.named_tool_request.envelope.tool_id

    @property
    def query_valid_time(self) -> str:
        return self.named_tool_request.envelope.query_valid_time

    @property
    def serving_time(self) -> str:
        return self.named_tool_request.envelope.serving_time


_COLLISION_AUTHORITY_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "request_digest",
        "adapter_contract_digest",
        "adapter_config_digest",
        "authority_scope_id",
        "authority_watermark",
        "collision_namespace",
        "collision_key_digest",
        "collision_state",
        "candidate_id",
        "objects",
        "passages",
        "missing_object_ids",
        "missing_passage_ids",
        "ambiguous_passage_ids",
        "outcome",
        "reason",
        "result_count",
        "no_match",
        "query_valid_time",
        "serving_time",
        "object_bytes_returned",
        "authority_effect",
    }
)
_SOURCE_IMPACT_AUTHORITY_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "request_digest",
        "adapter_contract_digest",
        "adapter_config_digest",
        "authority_scope_id",
        "authority_watermark",
        "source_id",
        "source_definition_digest",
        "revision_id",
        "window_start",
        "window_end",
        "lineage_depth",
        "include_superseded",
        "revisions",
        "representations",
        "occurrences",
        "outcome",
        "reason",
        "result_count",
        "no_match",
        "query_valid_time",
        "serving_time",
        "authority_effect",
    }
)
_AUTHORITY_OBJECT_KEYS = frozenset(
    {
        "requested_object_id",
        "admission_id",
        "blob_digest",
        "size_bytes",
        "admission_state",
        "admission_reason",
        "blob_state",
        "blob_integrity_state",
        "object_class",
        "allowed_use",
        "security_scope",
        "retention_scope",
        "valid_from",
        "valid_until",
        "rights_decision_id",
        "rights_allowed",
        "rights_reason",
        "rights_valid_from",
        "rights_valid_until",
        "rights_digest",
        "usable",
        "block_reason",
    }
)
_AUTHORITY_PASSAGE_KEYS = frozenset(
    {
        "passage_id",
        "run_id",
        "admission_id",
        "access_decision_id",
        "blob_digest",
        "text_digest",
        "language",
        "byte_offset",
        "byte_length",
        "object_class",
        "allowed_use",
        "security_scope",
        "retention_scope",
        "admission_state",
        "blob_state",
        "blob_integrity_state",
        "rights_decision_id",
        "rights_allowed",
        "rights_reason",
        "rights_digest",
        "usable",
        "block_reason",
    }
)
_REVISION_IMPACT_KEYS = frozenset(
    {
        "revision_id",
        "item_id",
        "prior_revision_id",
        "source_native_revision_token",
        "permitted_state_digest",
        "revision_identity_digest",
        "item_identity_digest",
        "observed_at",
        "recorded_at",
    }
)
_REPRESENTATION_IMPACT_KEYS = frozenset(
    {
        "representation_id",
        "revision_id",
        "adapter_version",
        "parser_version",
        "normalizer_version",
        "extraction_scope_version",
        "permitted_fields_digest",
        "representation_digest",
        "producer_slot_digest",
        "representation_identity_digest",
        "produced_at",
        "recorded_at",
        "canonical_digest",
    }
)
_OCCURRENCE_IMPACT_KEYS = frozenset(
    {
        "occurrence_id",
        "check_outcome_id",
        "revision_id",
        "representation_id",
        "occurrence_kind",
        "observed_at",
        "receipt_digest",
        "semantic_digest",
        "recorded_at",
        "canonical_digest",
    }
)

_COLLISION_AUTHORITY_COMPONENTS = {
    "adapter_contract": NAMED_TOOL_AUTHORITY_ADAPTER_CONTRACT_DIGEST,
    "collision_query": COLLISION_QUERY_DIGEST,
    "named_tool_contract": NAMED_TOOL_CONTRACT_DIGEST,
    "object_query": OBJECT_QUERY_DIGEST,
    "passage_query": PASSAGE_QUERY_DIGEST,
}
_SOURCE_IMPACT_BASE_COMPONENTS = {
    "adapter_contract": NAMED_TOOL_AUTHORITY_ADAPTER_CONTRACT_DIGEST,
    "named_tool_contract": NAMED_TOOL_CONTRACT_DIGEST,
    "occurrence_query": OCCURRENCE_QUERY_DIGEST,
    "representation_query": REPRESENTATION_QUERY_DIGEST,
    "revision_query": REVISION_QUERY_DIGEST,
    "source_query": SOURCE_QUERY_DIGEST,
}
_SOURCE_IMPACT_FULL_COMPONENTS = {
    **_SOURCE_IMPACT_BASE_COMPONENTS,
    "occurrence_time_integrity_query": (
        OCCURRENCE_TIME_INTEGRITY_QUERY_DIGEST
    ),
    "representation_time_integrity_query": (
        REPRESENTATION_TIME_INTEGRITY_QUERY_DIGEST
    ),
    "revision_time_integrity_query": REVISION_TIME_INTEGRITY_QUERY_DIGEST,
}
_AUTHORITY_BLOCK_REASON_ORDER = (
    "ADMISSION_NOT_ACTIVE",
    "BLOB_NOT_ACTIVE",
    "BLOB_NOT_VERIFIED",
    "RIGHTS_DENIED",
    "ADMISSION_NOT_CURRENT",
    "RIGHTS_NOT_CURRENT",
)
_AUTHORITY_EARLY_FAILURES = {
    "AUTHORITY_SCHEMA_UNAVAILABLE": "UNAVAILABLE",
    "AUTHORITY_WATERMARK_STALE": "STALE",
    "QUERY_TIMEOUT": "INCOMPLETE",
    "AUTHORITY_DATABASE_UNAVAILABLE": "UNAVAILABLE",
    "AUTHORITY_INTEGRITY_ERROR": "UNAVAILABLE",
}


def _mapping_list(
    value: object,
    *,
    field: str,
    keys: frozenset[str],
) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list):
        raise NamedAuthorityReceiptValidationError(f"{field} must be a list")
    result: list[Mapping[str, object]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != keys:
            raise NamedAuthorityReceiptValidationError(f"{field}[{index}] keys are not exact")
        result.append(item)
    return tuple(result)


def _sorted_text_list(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise NamedAuthorityReceiptValidationError(f"{field} must be a list")
    result = tuple(
        _require_text(item, field=f"{field}[{index}]")
        for index, item in enumerate(value)
    )
    if result != tuple(sorted(set(result))):
        raise NamedAuthorityReceiptValidationError(f"{field} must be sorted and unique")
    return result


def _optional_text(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, field=field)


def _validate_component_identities(
    components: Mapping[str, str],
    *,
    adapter_config_digest: str,
    expected: Mapping[str, str],
    field: str,
) -> None:
    accepted = {"adapter_config": adapter_config_digest, **expected}
    if dict(components) != accepted:
        raise NamedAuthorityReceiptValidationError(f"{field} component identities differ")


def _valid_at(
    start: object,
    end: object,
    serving: datetime,
    *,
    field: str,
) -> bool:
    start_time = _parse_utc(start, field=f"{field}_valid_from")
    if end is None:
        end_time = None
    else:
        end_time = _parse_utc(end, field=f"{field}_valid_until")
        if end_time <= start_time:
            raise NamedAuthorityReceiptValidationError(
                f"{field} validity interval is not increasing"
            )
    return start_time <= serving and (end_time is None or serving < end_time)


def _block_reasons(value: object, *, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    text = _require_text(value, field=field)
    reasons = tuple(text.split("+"))
    if (
        not reasons
        or len(reasons) != len(set(reasons))
        or any(reason not in _AUTHORITY_BLOCK_REASON_ORDER for reason in reasons)
        or reasons
        != tuple(
            reason for reason in _AUTHORITY_BLOCK_REASON_ORDER if reason in reasons
        )
    ):
        raise NamedAuthorityReceiptValidationError(f"{field} is not canonical")
    return reasons


def _validate_authority_common(
    item: "_ValidationContext",
    raw: bytes,
    value: Mapping[str, object],
) -> tuple[NamedAuthorityExecutionReceipt, Mapping[str, str]]:
    try:
        canonical = _canonical(value)
    except Exception as exc:
        raise NamedAuthorityReceiptValidationError(
            "authority receipt is not canonical JSON"
        ) from exc
    if canonical != raw:
        raise NamedAuthorityReceiptValidationError("authority receipt bytes are not canonical")
    execution = item.execution_receipt
    if not isinstance(execution, NamedAuthorityExecutionReceipt):
        raise NamedAuthorityReceiptValidationError(
            "authority input retained a branch execution receipt"
        )
    attribution = execution.authority_attribution
    if attribution is None:
        raise NamedAuthorityReceiptValidationError(
            "attributed authority input lacks authority attribution"
        )
    if attribution.tool_request_digest != item.tool_request_digest:
        raise NamedAuthorityReceiptValidationError(
            "authority attribution differs from named request"
        )
    if attribution.tool_id is not item.tool_id:
        raise NamedAuthorityReceiptValidationError("authority attribution tool differs")
    if attribution.authority_profile_id != AUTHORITY_PROFILE_ID:
        raise NamedAuthorityReceiptValidationError("authority profile identity differs")
    if attribution.authority_receipt_digest != _digest(raw):
        raise NamedAuthorityReceiptValidationError("authority receipt digest differs")
    if attribution.authority_receipt_bytes != len(raw):
        raise NamedAuthorityReceiptValidationError("authority receipt byte count differs")
    if (
        attribution.query_valid_time != item.query_valid_time
        or attribution.serving_time != item.serving_time
    ):
        raise NamedAuthorityReceiptValidationError("authority receipt time binding differs")

    schema = value.get("schema_version")
    if schema != attribution.authority_schema_version:
        raise NamedAuthorityReceiptValidationError("authority receipt schema differs")
    if value.get("request_digest") != item.tool_request_digest:
        raise NamedAuthorityReceiptValidationError("authority receipt request binding differs")
    if value.get("query_valid_time") != item.query_valid_time or value.get(
        "serving_time"
    ) != item.serving_time:
        raise NamedAuthorityReceiptValidationError("authority receipt query time differs")
    if value.get("outcome") != attribution.outcome.value:
        raise NamedAuthorityReceiptValidationError("authority receipt outcome differs")
    if value.get("reason") != attribution.reason:
        raise NamedAuthorityReceiptValidationError("authority receipt reason differs")
    result_count = _require_non_negative_int(
        value.get("result_count"), field="authority_receipt_result_count"
    )
    if result_count != attribution.result_count:
        raise NamedAuthorityReceiptValidationError("authority receipt result count differs")
    if type(value.get("no_match")) is not bool:
        raise NamedAuthorityReceiptValidationError("authority receipt no_match must be boolean")
    if value["no_match"] != attribution.no_match:
        raise NamedAuthorityReceiptValidationError("authority receipt no-match differs")
    watermark = _require_non_negative_int(
        value.get("authority_watermark"),
        field="authority_receipt_watermark",
    )
    if watermark != attribution.authority_watermark:
        raise NamedAuthorityReceiptValidationError("authority receipt watermark differs")
    _require_token(
        value.get("authority_scope_id"), field="authority_receipt_scope_id"
    )
    if value.get("authority_effect") != "NONE":
        raise NamedAuthorityReceiptValidationError("authority receipt claims an effect")

    components = {
        component.name: component.digest
        for component in attribution.component_identities
    }
    if len(components) != len(attribution.component_identities):
        raise NamedAuthorityReceiptValidationError("authority component identities duplicate")
    adapter_contract = _require_digest(
        value.get("adapter_contract_digest"),
        field="authority_adapter_contract_digest",
    )
    adapter_config = _require_digest(
        value.get("adapter_config_digest"),
        field="authority_adapter_config_digest",
    )
    if adapter_contract != NAMED_TOOL_AUTHORITY_ADAPTER_CONTRACT_DIGEST:
        raise NamedAuthorityReceiptValidationError("authority adapter contract is not accepted")
    if components.get("adapter_contract") != adapter_contract:
        raise NamedAuthorityReceiptValidationError("authority adapter contract differs")
    if components.get("adapter_config") != adapter_config:
        raise NamedAuthorityReceiptValidationError("authority adapter config differs")
    if components.get("named_tool_contract") != NAMED_TOOL_CONTRACT_DIGEST:
        raise NamedAuthorityReceiptValidationError("authority named-tool contract differs")
    return execution, components


def _validate_authority_object(
    value: Mapping[str, object],
    *,
    serving: datetime,
) -> str:
    requested = _require_text(
        value["requested_object_id"], field="authority_object_requested_id"
    )
    if value["admission_id"] != requested:
        raise NamedAuthorityReceiptValidationError("authority object admission differs")
    _require_digest(value["blob_digest"], field="authority_object_blob_digest")
    _require_non_negative_int(
        value["size_bytes"], field="authority_object_size_bytes"
    )
    for name in (
        "admission_state",
        "admission_reason",
        "blob_state",
        "blob_integrity_state",
        "object_class",
        "allowed_use",
        "security_scope",
        "retention_scope",
        "rights_decision_id",
        "rights_reason",
    ):
        _require_text(value[name], field=f"authority_object_{name}")
    admission_current = _valid_at(
        value["valid_from"],
        value["valid_until"],
        serving,
        field="authority_object_admission",
    )
    rights_current = _valid_at(
        value["rights_valid_from"],
        value["rights_valid_until"],
        serving,
        field="authority_object_rights",
    )
    _require_digest(value["rights_digest"], field="authority_object_rights_digest")
    for name in ("rights_allowed", "usable"):
        if type(value[name]) is not bool:
            raise NamedAuthorityReceiptValidationError(f"authority object {name} must be boolean")
    expected_reasons = tuple(
        reason
        for reason, blocked in (
            ("ADMISSION_NOT_ACTIVE", value["admission_state"] != "ACTIVE"),
            ("BLOB_NOT_ACTIVE", value["blob_state"] != "ACTIVE"),
            ("BLOB_NOT_VERIFIED", value["blob_integrity_state"] != "VERIFIED"),
            ("RIGHTS_DENIED", not value["rights_allowed"]),
            ("ADMISSION_NOT_CURRENT", not admission_current),
            ("RIGHTS_NOT_CURRENT", not rights_current),
        )
        if blocked
    )
    usable = not expected_reasons
    if value["usable"] is not usable:
        raise NamedAuthorityReceiptValidationError("authority object usability is inconsistent")
    if _block_reasons(
        value["block_reason"], field="authority_object_block_reason"
    ) != expected_reasons:
        raise NamedAuthorityReceiptValidationError("authority object block reason is inconsistent")
    return requested


def _validate_authority_passage(value: Mapping[str, object]) -> str:
    passage_id = _require_text(value["passage_id"], field="authority_passage_id")
    for name in (
        "run_id",
        "admission_id",
        "access_decision_id",
        "language",
        "object_class",
        "allowed_use",
        "security_scope",
        "retention_scope",
        "admission_state",
        "blob_state",
        "blob_integrity_state",
        "rights_decision_id",
        "rights_reason",
    ):
        _require_text(value[name], field=f"authority_passage_{name}")
    for name in ("blob_digest", "text_digest", "rights_digest"):
        _require_digest(value[name], field=f"authority_passage_{name}")
    _require_non_negative_int(
        value["byte_offset"], field="authority_passage_byte_offset"
    )
    _require_positive_int(
        value["byte_length"], field="authority_passage_byte_length"
    )
    for name in ("rights_allowed", "usable"):
        if type(value[name]) is not bool:
            raise NamedAuthorityReceiptValidationError(f"authority passage {name} must be boolean")
    reasons = _block_reasons(
        value["block_reason"], field="authority_passage_block_reason"
    )
    required_reasons = {
        reason
        for reason, blocked in (
            ("ADMISSION_NOT_ACTIVE", value["admission_state"] != "ACTIVE"),
            ("BLOB_NOT_ACTIVE", value["blob_state"] != "ACTIVE"),
            ("BLOB_NOT_VERIFIED", value["blob_integrity_state"] != "VERIFIED"),
            ("RIGHTS_DENIED", not value["rights_allowed"]),
        )
        if blocked
    }
    if not required_reasons.issubset(reasons):
        raise NamedAuthorityReceiptValidationError("authority passage block reason is inconsistent")
    if value["usable"]:
        if reasons or required_reasons:
            raise NamedAuthorityReceiptValidationError("usable authority passage retains a blocker")
    elif not reasons:
        raise NamedAuthorityReceiptValidationError("blocked authority passage lacks a reason")
    return passage_id


def _validated_collision_authority_receipt(
    item: "_ValidationContext",
    raw: bytes,
    value: Mapping[str, object],
) -> None:
    if set(value) != _COLLISION_AUTHORITY_RECEIPT_KEYS:
        raise NamedAuthorityReceiptValidationError("collision authority receipt keys are not exact")
    execution, components = _validate_authority_common(item, raw, value)
    attribution = execution.authority_attribution
    assert attribution is not None
    expected_schema = (
        "newsroom.increment5.collision-hydration-authority-receipt.v1"
    )
    if value["schema_version"] != expected_schema:
        raise NamedAuthorityReceiptValidationError("collision authority receipt schema differs")
    request = item.named_tool_request
    if not isinstance(request, CollisionHydrationLookupToolRequest):
        raise NamedAuthorityReceiptValidationError("collision authority request type differs")
    if (
        value["collision_namespace"] != request.collision_namespace
        or value["collision_key_digest"] != request.collision_key_digest
    ):
        raise NamedAuthorityReceiptValidationError("collision authority request payload differs")
    expected_authority_request = _digest(
        _canonical(
            {
                "schema_version": (
                    "newsroom.increment5.collision-hydration-authority-request.v1"
                ),
                "tool_request_digest": item.tool_request_digest,
                "adapter_config_digest": value["adapter_config_digest"],
            }
        )
    )
    if attribution.authority_request_digest != expected_authority_request:
        raise NamedAuthorityReceiptValidationError("collision authority request digest differs")
    _validate_component_identities(
        components,
        adapter_config_digest=value["adapter_config_digest"],
        expected=_COLLISION_AUTHORITY_COMPONENTS,
        field="collision authority",
    )
    state = value["collision_state"]
    if state not in {"UNKNOWN", "OCCUPIED", "UNOCCUPIED"}:
        raise NamedAuthorityReceiptValidationError("collision authority state is not accepted")
    candidate_id = _optional_text(
        value["candidate_id"], field="collision_authority_candidate_id"
    )
    if (state == "OCCUPIED") != (candidate_id is not None):
        raise NamedAuthorityReceiptValidationError("collision state and Candidate differ")
    if state == "UNKNOWN" and candidate_id is not None:
        raise NamedAuthorityReceiptValidationError("unknown collision state cannot retain Candidate")

    objects = _mapping_list(
        value["objects"], field="collision_authority_objects", keys=_AUTHORITY_OBJECT_KEYS
    )
    passages = _mapping_list(
        value["passages"],
        field="collision_authority_passages",
        keys=_AUTHORITY_PASSAGE_KEYS,
    )
    serving = _parse_utc(
        value["serving_time"], field="collision_authority_serving_time"
    )
    object_ids = tuple(
        _validate_authority_object(record, serving=serving) for record in objects
    )
    passage_ids = tuple(_validate_authority_passage(record) for record in passages)
    if object_ids != tuple(sorted(set(object_ids))):
        raise NamedAuthorityReceiptValidationError("collision authority objects are not canonical")
    if passage_ids != tuple(sorted(set(passage_ids))):
        raise NamedAuthorityReceiptValidationError("collision authority passages are not canonical")
    missing_objects = _sorted_text_list(
        value["missing_object_ids"], field="collision_missing_object_ids"
    )
    missing_passages = _sorted_text_list(
        value["missing_passage_ids"], field="collision_missing_passage_ids"
    )
    ambiguous_passages = _sorted_text_list(
        value["ambiguous_passage_ids"], field="collision_ambiguous_passage_ids"
    )
    object_groups = (set(object_ids), set(missing_objects))
    if object_groups[0] & object_groups[1]:
        raise NamedAuthorityReceiptValidationError("collision object coverage overlaps")
    if set().union(*object_groups) != set(request.authority_object_ids):
        raise NamedAuthorityReceiptValidationError("collision object coverage differs from request")
    passage_groups = (
        set(passage_ids),
        set(missing_passages),
        set(ambiguous_passages),
    )
    if any(
        passage_groups[left] & passage_groups[right]
        for left in range(len(passage_groups))
        for right in range(left + 1, len(passage_groups))
    ):
        raise NamedAuthorityReceiptValidationError("collision passage coverage overlaps")
    if set().union(*passage_groups) != set(request.passage_ids):
        raise NamedAuthorityReceiptValidationError("collision passage coverage differs from request")
    objects_by_id = {record["admission_id"]: record for record in objects}
    for passage in passages:
        authority_object = objects_by_id.get(passage["admission_id"])
        if authority_object is None:
            continue
        for field in (
            "blob_digest",
            "object_class",
            "allowed_use",
            "security_scope",
            "retention_scope",
            "admission_state",
            "blob_state",
            "blob_integrity_state",
            "rights_decision_id",
            "rights_allowed",
            "rights_reason",
            "rights_digest",
            "usable",
            "block_reason",
        ):
            if passage[field] != authority_object[field]:
                raise NamedAuthorityReceiptValidationError(
                    "collision passage authority differs from its object"
                )
    if type(value["object_bytes_returned"]) is not bool or value[
        "object_bytes_returned"
    ]:
        raise NamedAuthorityReceiptValidationError("collision receipt cannot return object bytes")
    if state == "UNKNOWN":
        if any(
            (
                candidate_id is not None,
                bool(objects),
                bool(passages),
                bool(missing_objects),
                bool(missing_passages),
                bool(ambiguous_passages),
            )
        ):
            raise NamedAuthorityReceiptValidationError(
                "unknown collision receipt cannot retain authority results"
            )
        if value["outcome"] == "COMPLETE":
            raise NamedAuthorityReceiptValidationError(
                "complete collision receipt cannot retain unknown state"
            )
        reason = value["reason"]
        expected_outcome = _AUTHORITY_EARLY_FAILURES.get(reason)
        if expected_outcome is None or value["outcome"] != expected_outcome:
            raise NamedAuthorityReceiptValidationError(
                "collision authority early failure is not truthful"
            )
        return

    total = (1 if candidate_id is not None else 0) + len(objects) + len(passages)
    if total > request.envelope.result_limit:
        expected = ("INCOMPLETE", "RESULT_BOUND_EXCEEDED", 0, False)
    elif missing_objects or missing_passages or ambiguous_passages:
        expected = (
            "INCOMPLETE",
            "REQUESTED_AUTHORITY_UNAVAILABLE",
            0,
            False,
        )
    elif any(not record["usable"] for record in (*objects, *passages)):
        expected = (
            "POLICY_BLOCKED",
            "RIGHTS_OR_LIFECYCLE_BLOCKED",
            0,
            False,
        )
    else:
        expected = (
            "COMPLETE",
            "NO_MATCH" if total == 0 else None,
            total,
            total == 0,
        )
    actual = (
        value["outcome"],
        value["reason"],
        value["result_count"],
        value["no_match"],
    )
    if actual != expected:
        raise NamedAuthorityReceiptValidationError("collision authority outcome is not truthful")


def _validate_revision_record(
    record: Mapping[str, object],
    *,
    query_valid: datetime,
    window_start: datetime,
    window_end: datetime,
    requested_revision: str | None,
) -> tuple[str, datetime]:
    revision_id = _require_text(record["revision_id"], field="impact_revision_id")
    _require_text(record["item_id"], field="impact_revision_item_id")
    _optional_text(record["prior_revision_id"], field="impact_prior_revision_id")
    _optional_text(
        record["source_native_revision_token"],
        field="impact_source_native_revision_token",
    )
    for name in (
        "permitted_state_digest",
        "revision_identity_digest",
        "item_identity_digest",
    ):
        _require_digest(record[name], field=f"impact_revision_{name}")
    observed = _parse_utc(record["observed_at"], field="impact_revision_observed_at")
    recorded = _parse_utc(record["recorded_at"], field="impact_revision_recorded_at")
    if not window_start <= observed < window_end:
        raise NamedAuthorityReceiptValidationError("impact revision is outside the requested window")
    if observed > query_valid or recorded > query_valid:
        raise NamedAuthorityReceiptValidationError("impact revision is after query-valid time")
    if requested_revision is not None and revision_id != requested_revision:
        raise NamedAuthorityReceiptValidationError("impact revision differs from request")
    return revision_id, observed


def _validated_source_impact_authority_receipt(
    item: "_ValidationContext",
    raw: bytes,
    value: Mapping[str, object],
) -> None:
    if set(value) != _SOURCE_IMPACT_AUTHORITY_RECEIPT_KEYS:
        raise NamedAuthorityReceiptValidationError("source-impact authority receipt keys are not exact")
    execution, components = _validate_authority_common(item, raw, value)
    attribution = execution.authority_attribution
    assert attribution is not None
    expected_schema = (
        "newsroom.increment5.source-revision-impact-authority-receipt.v1"
    )
    if value["schema_version"] != expected_schema:
        raise NamedAuthorityReceiptValidationError("source-impact authority receipt schema differs")
    request = item.named_tool_request
    if not isinstance(request, SourceRevisionImpactLookupToolRequest):
        raise NamedAuthorityReceiptValidationError("source-impact authority request type differs")
    for field in ("source_id", "revision_id", "window_start", "window_end"):
        if value[field] != getattr(request, field):
            raise NamedAuthorityReceiptValidationError(f"source-impact {field} differs from request")
    if (
        value["lineage_depth"] != request.lineage_depth
        or value["include_superseded"] is not request.include_superseded
    ):
        raise NamedAuthorityReceiptValidationError("source-impact bounds differ from request")
    expected_authority_request = _digest(
        _canonical(
            {
                "schema_version": (
                    "newsroom.increment5.source-revision-impact-authority-request.v1"
                ),
                "tool_request_digest": item.tool_request_digest,
                "adapter_config_digest": value["adapter_config_digest"],
            }
        )
    )
    if attribution.authority_request_digest != expected_authority_request:
        raise NamedAuthorityReceiptValidationError("source-impact authority request digest differs")
    adapter_config_digest = value["adapter_config_digest"]
    base_components = {
        "adapter_config": adapter_config_digest,
        **_SOURCE_IMPACT_BASE_COMPONENTS,
    }
    full_components = {
        "adapter_config": adapter_config_digest,
        **_SOURCE_IMPACT_FULL_COMPONENTS,
    }
    if dict(components) == full_components:
        full_query_path = True
    elif dict(components) == base_components:
        full_query_path = False
    else:
        raise NamedAuthorityReceiptValidationError(
            "source-impact authority component identities differ"
        )
    source_digest = value["source_definition_digest"]
    if source_digest is not None:
        _require_digest(source_digest, field="impact_source_definition_digest")
    if type(value["include_superseded"]) is not bool:
        raise NamedAuthorityReceiptValidationError("source-impact supersession flag must be boolean")
    if value["lineage_depth"] not in (1, 2):
        raise NamedAuthorityReceiptValidationError("source-impact lineage depth differs")
    query_valid = _parse_utc(
        value["query_valid_time"], field="impact_receipt_query_valid_time"
    )
    window_start = _parse_utc(value["window_start"], field="impact_window_start")
    window_end = _parse_utc(value["window_end"], field="impact_window_end")
    if window_start >= window_end:
        raise NamedAuthorityReceiptValidationError("source-impact window is not increasing")
    revisions = _mapping_list(
        value["revisions"], field="impact_revisions", keys=_REVISION_IMPACT_KEYS
    )
    representations = _mapping_list(
        value["representations"],
        field="impact_representations",
        keys=_REPRESENTATION_IMPACT_KEYS,
    )
    occurrences = _mapping_list(
        value["occurrences"],
        field="impact_occurrences",
        keys=_OCCURRENCE_IMPACT_KEYS,
    )
    revision_values = tuple(
        _validate_revision_record(
            record,
            query_valid=query_valid,
            window_start=window_start,
            window_end=window_end,
            requested_revision=request.revision_id,
        )
        for record in revisions
    )
    revision_ids = tuple(item[0] for item in revision_values)
    if len(revision_ids) != len(set(revision_ids)):
        raise NamedAuthorityReceiptValidationError("source-impact revisions duplicate")
    if revision_values != tuple(sorted(revision_values, key=lambda item: (item[1], item[0]))):
        raise NamedAuthorityReceiptValidationError("source-impact revisions are not canonical")
    revision_set = set(revision_ids)
    revision_order = {
        revision_id: index for index, revision_id in enumerate(revision_ids)
    }
    representation_values: list[tuple[str, str, datetime]] = []
    for record in representations:
        representation_id = _require_text(
            record["representation_id"], field="impact_representation_id"
        )
        revision_id = _require_text(
            record["revision_id"], field="impact_representation_revision_id"
        )
        if revision_id not in revision_set:
            raise NamedAuthorityReceiptValidationError("impact representation lacks revision")
        for name in (
            "adapter_version",
            "parser_version",
            "normalizer_version",
            "extraction_scope_version",
        ):
            _require_text(record[name], field=f"impact_representation_{name}")
        for name in (
            "permitted_fields_digest",
            "representation_digest",
            "producer_slot_digest",
            "representation_identity_digest",
            "canonical_digest",
        ):
            _require_digest(record[name], field=f"impact_representation_{name}")
        produced = _parse_utc(
            record["produced_at"], field="impact_representation_produced_at"
        )
        recorded = _parse_utc(
            record["recorded_at"], field="impact_representation_recorded_at"
        )
        if not window_start <= produced < window_end:
            raise NamedAuthorityReceiptValidationError("impact representation is outside window")
        if produced > query_valid or recorded > query_valid:
            raise NamedAuthorityReceiptValidationError("impact representation is after query-valid time")
        representation_values.append(
            (representation_id, revision_id, produced)
        )
    representation_ids = tuple(item[0] for item in representation_values)
    if len(representation_ids) != len(set(representation_ids)):
        raise NamedAuthorityReceiptValidationError("source-impact representations duplicate")
    expected_representation_order = tuple(
        sorted(
            representation_values,
            key=lambda item: (
                revision_order[item[1]],
                item[2],
                item[0],
            ),
        )
    )
    if tuple(representation_values) != expected_representation_order:
        raise NamedAuthorityReceiptValidationError("source-impact representations are not canonical")
    representation_revision = {
        representation_id: revision_id
        for representation_id, revision_id, _produced in representation_values
    }
    occurrence_values: list[tuple[str, str, str | None, datetime]] = []
    for record in occurrences:
        occurrence_id = _require_text(
            record["occurrence_id"], field="impact_occurrence_id"
        )
        _require_text(
            record["check_outcome_id"], field="impact_occurrence_check_outcome_id"
        )
        revision_id = _require_text(
            record["revision_id"], field="impact_occurrence_revision_id"
        )
        if revision_id not in revision_set:
            raise NamedAuthorityReceiptValidationError("impact occurrence lacks revision")
        representation_id = _optional_text(
            record["representation_id"], field="impact_occurrence_representation_id"
        )
        if representation_id is not None:
            if representation_id not in representation_revision:
                raise NamedAuthorityReceiptValidationError(
                    "impact occurrence lacks its retained representation"
                )
            if representation_revision[representation_id] != revision_id:
                raise NamedAuthorityReceiptValidationError(
                    "impact occurrence representation crosses revisions"
                )
        _require_text(
            record["occurrence_kind"], field="impact_occurrence_kind"
        )
        for name in ("receipt_digest", "semantic_digest", "canonical_digest"):
            _require_digest(record[name], field=f"impact_occurrence_{name}")
        observed = _parse_utc(
            record["observed_at"], field="impact_occurrence_observed_at"
        )
        recorded = _parse_utc(
            record["recorded_at"], field="impact_occurrence_recorded_at"
        )
        if not window_start <= observed < window_end:
            raise NamedAuthorityReceiptValidationError("impact occurrence is outside window")
        if observed > query_valid or recorded > query_valid:
            raise NamedAuthorityReceiptValidationError("impact occurrence is after query-valid time")
        occurrence_values.append(
            (occurrence_id, revision_id, representation_id, observed)
        )
    occurrence_ids = tuple(item[0] for item in occurrence_values)
    if len(occurrence_ids) != len(set(occurrence_ids)):
        raise NamedAuthorityReceiptValidationError("source-impact occurrences duplicate")
    expected_occurrence_order = tuple(
        sorted(
            occurrence_values,
            key=lambda item: (
                revision_order[item[1]],
                item[3],
                item[0],
            ),
        )
    )
    if tuple(occurrence_values) != expected_occurrence_order:
        raise NamedAuthorityReceiptValidationError("source-impact occurrences are not canonical")
    if value["lineage_depth"] == 1 and (representations or occurrences):
        raise NamedAuthorityReceiptValidationError("depth-one impact receipt retains dependent lineage")
    visible = len(revisions) + len(representations) + len(occurrences)
    if value["source_definition_digest"] is None and visible:
        raise NamedAuthorityReceiptValidationError(
            "source-impact lineage exists without retained source authority"
        )
    if full_query_path:
        expected = (
            (
                "INCOMPLETE",
                "RESULT_BOUND_EXCEEDED",
                0,
                False,
            )
            if visible > request.envelope.result_limit
            else (
                "COMPLETE",
                "NO_MATCH" if visible == 0 else None,
                visible,
                visible == 0,
            )
        )
    else:
        if value["source_definition_digest"] is not None or visible:
            raise NamedAuthorityReceiptValidationError(
                "early source-impact failure cannot retain authority results"
            )
        reason = value["reason"]
        expected_outcome = _AUTHORITY_EARLY_FAILURES.get(reason)
        if expected_outcome is None:
            raise NamedAuthorityReceiptValidationError(
                "source-impact early failure reason is not accepted"
            )
        expected = (expected_outcome, reason, 0, False)
    actual = (
        value["outcome"],
        value["reason"],
        value["result_count"],
        value["no_match"],
    )
    if actual != expected:
        raise NamedAuthorityReceiptValidationError(
            "source-impact authority outcome is not truthful"
        )


def _validated_authority_receipt(
    item: "_ValidationContext", raw: bytes
) -> None:
    value = _decode(raw)
    if item.tool_id is NamedToolId.CURRENT_COLLISION_AND_AUTHORITY_HYDRATION_LOOKUP:
        _validated_collision_authority_receipt(item, raw, value)
        return
    if item.tool_id is NamedToolId.BOUNDED_SOURCE_REVISION_IMPACT_LOOKUP:
        _validated_source_impact_authority_receipt(item, raw, value)
        return
    raise NamedAuthorityReceiptValidationError("authority tool is not in the fixed inventory")



def validate_named_authority_receipt(
    *,
    request: NamedToolRequest,
    execution_receipt: NamedAuthorityExecutionReceipt,
    raw_receipt_bytes: bytes,
) -> None:
    """Validate exact retained authority evidence without reading authority."""

    if not isinstance(execution_receipt, NamedAuthorityExecutionReceipt):
        raise TypeError("authority receipt validator requires typed execution")
    context = _ValidationContext(
        named_tool_request=request,
        execution_receipt=execution_receipt,
    )
    _validated_authority_receipt(context, raw_receipt_bytes)


__all__ = [
    "NamedAuthorityReceiptValidationError",
    "validate_named_authority_receipt",
]
