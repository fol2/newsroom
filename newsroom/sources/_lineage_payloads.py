from __future__ import annotations

from typing import Any

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.authority.types import UtcTimestamp

from ._payload_common import (
    _digest,
    _enum,
    _error,
    _exact,
    _policy_ref,
    _source_time,
    _strings,
    _text,
    _token,
    _uuid,
)
from .types import (
    DiscoveryOccurrenceKind,
    LocatorContinuityOutcome,
    SourceItemIdentityKind,
)


def _timestamp(value: Any, *, field: str) -> str:
    text = _text(value, field=field, maximum_bytes=64)
    try:
        parsed = UtcTimestamp.parse(text)
    except ValueError as exc:
        raise _error(f"{field} must be a UTC timestamp") from exc
    if parsed.to_text() != text:
        raise _error(f"{field} must use canonical UTC text")
    return text


def _item_payload(value: Any) -> bytes:
    item = _exact(
        value,
        fields=frozenset(
            {
                "item_id",
                "definition_id",
                "definition_version_id",
                "identity_kind",
                "identity_policy",
                "source_native_id",
                "identity_components",
                "uncertainties",
            }
        ),
        name="source item",
    )
    _uuid(item["item_id"], field="item_id")
    _uuid(item["definition_id"], field="definition_id")
    _uuid(item["definition_version_id"], field="definition_version_id")
    identity_kind = _enum(
        item["identity_kind"],
        enum_type=SourceItemIdentityKind,
        field="identity_kind",
    )
    _policy_ref(item["identity_policy"], field="identity_policy")
    native_id = item["source_native_id"]
    if native_id is not None:
        _text(native_id, field="source_native_id", maximum_bytes=2048)
    components = item["identity_components"]
    if not isinstance(components, list) or len(components) > 32:
        raise _error("identity components must be bounded")
    component_names: list[str] = []
    for component in components:
        component_item = _exact(
            component,
            fields=frozenset({"name", "value"}),
            name="identity component",
        )
        component_names.append(
            _token(component_item["name"], field="component.name")
        )
        _text(
            component_item["value"],
            field="component.value",
            maximum_bytes=2048,
        )
    if component_names != sorted(set(component_names)):
        raise _error("identity components must be sorted and unique")
    uncertainties = _strings(
        item["uncertainties"],
        field="uncertainties",
        maximum_items=16,
        allow_empty=True,
    )
    if identity_kind == SourceItemIdentityKind.SOURCE_NATIVE.value:
        if native_id is None:
            raise _error("source-native identity requires a native item id")
    elif identity_kind == SourceItemIdentityKind.COMPOSITE.value:
        if len(component_names) < 2:
            raise _error("composite identity requires at least two components")
        if set(component_names) <= {"locator", "url", "uri"}:
            raise _error("locator cannot be the sole source item identity")
    else:
        if not uncertainties or native_id is not None:
            raise _error(
                "assigned uncertain identity requires uncertainty and no native id"
            )
    if native_id is None and not component_names:
        raise _error("source item has no retained identity basis")
    return canonical_json_bytes(item)


def _locator_payload(value: Any) -> bytes:
    item = _exact(
        value,
        fields=frozenset(
            {
                "decision_id",
                "definition_id",
                "definition_version_id",
                "prior_item_id",
                "prior_locator",
                "observed_locator",
                "outcome",
                "related_item_id",
                "rationale",
                "decision_policy",
                "observed_at",
            }
        ),
        name="source locator continuity decision",
    )
    for field in (
        "decision_id",
        "definition_id",
        "definition_version_id",
        "prior_item_id",
        "related_item_id",
    ):
        _uuid(item[field], field=field)
    prior_locator = _text(
        item["prior_locator"], field="prior_locator", maximum_bytes=8192
    )
    observed_locator = _text(
        item["observed_locator"],
        field="observed_locator",
        maximum_bytes=8192,
    )
    if prior_locator == observed_locator:
        raise _error("locator continuity requires distinct locators")
    outcome = _enum(
        item["outcome"],
        enum_type=LocatorContinuityOutcome,
        field="locator_outcome",
    )
    if outcome == LocatorContinuityOutcome.SAME_ITEM.value:
        if item["related_item_id"] != item["prior_item_id"]:
            raise _error("same-item decision must retain the prior item")
    elif item["related_item_id"] == item["prior_item_id"]:
        raise _error("non-same locator decision requires a separate item")
    _text(item["rationale"], field="locator_rationale", maximum_bytes=4096)
    _policy_ref(item["decision_policy"], field="locator_decision_policy")
    _timestamp(item["observed_at"], field="locator_observed_at")
    return canonical_json_bytes(item)


def _revision_payload(value: Any) -> bytes:
    item = _exact(
        value,
        fields=frozenset(
            {
                "revision_id",
                "item_id",
                "definition_version_id",
                "prior_revision_id",
                "source_native_revision_token",
                "permitted_state_digest",
                "revision_policy",
                "canonicalizer_version",
                "source_published_time",
                "source_updated_time",
                "observed_at",
            }
        ),
        name="source revision",
    )
    revision_id = _uuid(item["revision_id"], field="revision_id")
    _uuid(item["item_id"], field="item_id")
    _uuid(item["definition_version_id"], field="definition_version_id")
    previous = _uuid(
        item["prior_revision_id"],
        field="prior_revision_id",
        optional=True,
    )
    if previous == revision_id:
        raise _error("source revision cannot precede itself")
    if item["source_native_revision_token"] is not None:
        _text(
            item["source_native_revision_token"],
            field="source_native_revision_token",
            maximum_bytes=2048,
        )
    _digest(item["permitted_state_digest"], field="permitted_state_digest")
    _policy_ref(item["revision_policy"], field="revision_policy")
    _token(item["canonicalizer_version"], field="canonicalizer_version")
    _source_time(item["source_published_time"], field="source_published_time")
    _source_time(item["source_updated_time"], field="source_updated_time")
    _timestamp(item["observed_at"], field="revision_observed_at")
    return canonical_json_bytes(item)


def _representation_payload(value: Any) -> bytes:
    item = _exact(
        value,
        fields=frozenset(
            {
                "representation_id",
                "revision_id",
                "definition_version_id",
                "adapter_version",
                "parser_version",
                "normalizer_version",
                "extraction_scope_version",
                "permitted_fields_digest",
                "representation_digest",
                "produced_at",
            }
        ),
        name="discovery representation",
    )
    for field in ("representation_id", "revision_id", "definition_version_id"):
        _uuid(item[field], field=field)
    for field in (
        "adapter_version",
        "parser_version",
        "normalizer_version",
        "extraction_scope_version",
    ):
        _token(item[field], field=field)
    _digest(item["permitted_fields_digest"], field="permitted_fields_digest")
    _digest(item["representation_digest"], field="representation_digest")
    _timestamp(item["produced_at"], field="representation_produced_at")
    return canonical_json_bytes(item)


def _occurrence_payload(value: Any) -> bytes:
    item = _exact(
        value,
        fields=frozenset(
            {
                "occurrence_id",
                "check_outcome_id",
                "revision_id",
                "representation_id",
                "definition_version_id",
                "kind",
                "observed_at",
                "receipt_digest",
                "source_asserted_time",
            }
        ),
        name="discovery occurrence",
    )
    for field in (
        "occurrence_id",
        "check_outcome_id",
        "revision_id",
        "definition_version_id",
    ):
        _uuid(item[field], field=field)
    _uuid(item["representation_id"], field="representation_id", optional=True)
    _enum(
        item["kind"],
        enum_type=DiscoveryOccurrenceKind,
        field="occurrence_kind",
    )
    _timestamp(item["observed_at"], field="occurrence_observed_at")
    _digest(item["receipt_digest"], field="receipt_digest")
    _source_time(item["source_asserted_time"], field="source_asserted_time")
    return canonical_json_bytes(item)


__all__ = [
    "_item_payload",
    "_locator_payload",
    "_occurrence_payload",
    "_representation_payload",
    "_revision_payload",
]
