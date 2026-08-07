"""Bounded execution kernel for the two Increment 5C authority-backed tools.

The kernel consumes an exact 5C1 local-authorization receipt, dispatches to one
closed read-only authority port, retains the complete canonical upstream receipt
in an immutable audit journal, and emits a compact independently attributable
execution receipt.  It does not hydrate object bytes, mutate authority, compose
branches, create Candidates, contact providers, publish, or activate production.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence, TypeAlias

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes

from .named_tool_authorization import (
    NamedToolAuthorizationReceipt,
    NamedToolGateOutcome,
)
from .named_tool_contracts import (
    NAMED_TOOL_RESPONSE_LIMIT_BYTES,
    NAMED_TOOL_RESULT_LIMIT,
    CollisionHydrationLookupToolRequest,
    NamedToolContractError,
    NamedToolId,
    NamedToolRequest,
    SourceRevisionImpactLookupToolRequest,
)


_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}\Z")
_REASON_RE = re.compile(r"[A-Z0-9][A-Z0-9._:\-]{0,255}\Z")
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


class NamedToolAuthorityExecutionError(RuntimeError):
    """The authority registry, port result, or immutable journal failed."""


class NamedAuthorityPolicyBlockedError(RuntimeError):
    """A typed authority adapter cannot safely honour the named request."""


class NamedAuthorityMode(StrEnum):
    COLLISION_HYDRATION = "COLLISION_HYDRATION"
    SOURCE_REVISION_IMPACT = "SOURCE_REVISION_IMPACT"


class NamedAuthorityOutcome(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class NamedAuthorityExecutionOutcome(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class NamedAuthorityExecutionReason(StrEnum):
    NO_MATCH = "NO_MATCH"
    LOCAL_AUTHORIZATION_BLOCKED = "LOCAL_AUTHORIZATION_BLOCKED"
    AUTHORIZATION_BINDING_MISMATCH = "AUTHORIZATION_BINDING_MISMATCH"
    ADAPTER_POLICY_BLOCKED = "ADAPTER_POLICY_BLOCKED"
    AUTHORITY_PORT_UNAVAILABLE = "AUTHORITY_PORT_UNAVAILABLE"
    AUTHORITY_RECEIPT_INVALID = "AUTHORITY_RECEIPT_INVALID"
    AUTHORITY_NON_COMPLETE = "AUTHORITY_NON_COMPLETE"
    RESULT_LIMIT_EXCEEDED = "RESULT_LIMIT_EXCEEDED"
    RESPONSE_LIMIT_EXCEEDED = "RESPONSE_LIMIT_EXCEEDED"


AUTHORITY_TOOL_MODES: Mapping[NamedToolId, NamedAuthorityMode] = {
    NamedToolId.CURRENT_COLLISION_AND_AUTHORITY_HYDRATION_LOOKUP: (
        NamedAuthorityMode.COLLISION_HYDRATION
    ),
    NamedToolId.BOUNDED_SOURCE_REVISION_IMPACT_LOOKUP: (
        NamedAuthorityMode.SOURCE_REVISION_IMPACT
    ),
}


def _canonical(value: object) -> bytes:
    try:
        return canonical_json_bytes(value)
    except Exception as exc:
        raise NamedToolContractError(
            "authority execution value is not canonical JSON"
        ) from exc


def _digest(value: bytes) -> str:
    return digest_bytes(value)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise NamedToolAuthorityExecutionError(
                "retained authority JSON contains duplicate keys"
            )
        result[key] = value
    return result


def _require_token(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _TOKEN_RE.fullmatch(value) is None:
        raise NamedToolContractError(f"{field} must be a bounded canonical token")
    return value


def _require_reason(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _REASON_RE.fullmatch(value) is None:
        raise NamedToolContractError(f"{field} must be a bounded canonical reason")
    return value


def _require_digest(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise NamedToolContractError(f"{field} must be a canonical SHA-256 digest")
    return value


def _require_uuid(value: str, *, field: str) -> str:
    if not isinstance(value, str):
        raise NamedToolContractError(f"{field} must be a canonical UUID")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise NamedToolContractError(f"{field} must be a canonical UUID") from exc
    if str(parsed) != value:
        raise NamedToolContractError(f"{field} must be a canonical UUID")
    return value


def _require_non_negative_int(value: int, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise NamedToolContractError(f"{field} must be a non-negative integer")
    return value


def _parse_utc(value: str, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise NamedToolContractError(f"{field} must be a UTC timestamp")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise NamedToolContractError(
            f"{field} must be canonical second-resolution UTC"
        ) from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise NamedToolContractError(
            f"{field} must be canonical second-resolution UTC"
        )
    return parsed


@dataclass(frozen=True, slots=True)
class AuthorityComponentIdentity:
    name: str
    digest: str

    def __post_init__(self) -> None:
        _require_token(self.name, field="authority_component_name")
        _require_digest(self.digest, field="authority_component_digest")

    def canonical_value(self) -> dict[str, str]:
        return {"name": self.name, "digest": self.digest}

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, object]
    ) -> "AuthorityComponentIdentity":
        if set(value) != {"name", "digest"}:
            raise NamedToolContractError(
                "authority component identity keys are not exact"
            )
        if not isinstance(value["name"], str) or not isinstance(
            value["digest"], str
        ):
            raise NamedToolContractError(
                "authority component identity fields must be text"
            )
        return cls(name=value["name"], digest=value["digest"])


@dataclass(frozen=True, slots=True)
class AuthorityReceiptAttribution:
    tool_request_digest: str
    tool_id: NamedToolId
    authority_mode: NamedAuthorityMode
    authority_schema_version: str
    authority_request_digest: str
    authority_receipt_digest: str
    authority_profile_id: str
    component_identities: tuple[AuthorityComponentIdentity, ...]
    query_valid_time: str
    serving_time: str
    outcome: NamedAuthorityOutcome
    reason: str | None
    result_count: int
    no_match: bool
    authority_watermark: int
    authority_receipt_bytes: int
    independently_attributable: bool = True
    external_call_count: int = 0
    provider_call_count: int = 0
    model_call_count: int = 0
    embedding_call_count: int = 0
    provider_spend_micros: int = 0
    authority_effect: str = "NONE"
    production_activation_authorized: bool = False

    def __post_init__(self) -> None:
        for name in (
            "tool_request_digest",
            "authority_request_digest",
            "authority_receipt_digest",
        ):
            _require_digest(getattr(self, name), field=name)
        if self.tool_id not in AUTHORITY_TOOL_MODES:
            raise NamedToolContractError(
                "authority attribution tool is not authority-backed"
            )
        if not isinstance(self.authority_mode, NamedAuthorityMode):
            raise NamedToolContractError("authority mode must be typed")
        if AUTHORITY_TOOL_MODES[self.tool_id] is not self.authority_mode:
            raise NamedToolContractError(
                "authority mode does not match named tool"
            )
        _require_token(
            self.authority_schema_version,
            field="authority_schema_version",
        )
        _require_token(self.authority_profile_id, field="authority_profile_id")
        if not self.component_identities or len(self.component_identities) > 16:
            raise NamedToolContractError(
                "authority attribution must retain between 1 and 16 components"
            )
        if not all(
            isinstance(item, AuthorityComponentIdentity)
            for item in self.component_identities
        ):
            raise NamedToolContractError(
                "authority component identities must be typed"
            )
        names = tuple(item.name for item in self.component_identities)
        if names != tuple(sorted(set(names))):
            raise NamedToolContractError(
                "authority component identities must be sorted and unique"
            )
        query_valid = _parse_utc(
            self.query_valid_time, field="authority_query_valid_time"
        )
        serving = _parse_utc(self.serving_time, field="authority_serving_time")
        if query_valid > serving:
            raise NamedToolContractError(
                "authority query-valid time cannot be after serving time"
            )
        if not isinstance(self.outcome, NamedAuthorityOutcome):
            raise NamedToolContractError("authority outcome must be typed")
        if self.reason is not None:
            _require_reason(self.reason, field="authority_reason")
        _require_non_negative_int(self.result_count, field="authority_result_count")
        if self.result_count > NAMED_TOOL_RESULT_LIMIT:
            raise NamedToolContractError(
                "authority result count exceeds the global bound"
            )
        if type(self.no_match) is not bool:
            raise NamedToolContractError("authority no_match must be boolean")
        _require_non_negative_int(
            self.authority_watermark,
            field="authority_watermark",
        )
        if (
            isinstance(self.authority_receipt_bytes, bool)
            or not isinstance(self.authority_receipt_bytes, int)
            or not 0 < self.authority_receipt_bytes <= NAMED_TOOL_RESPONSE_LIMIT_BYTES
        ):
            raise NamedToolContractError(
                "authority receipt bytes exceed the absolute response bound"
            )
        if self.outcome is NamedAuthorityOutcome.COMPLETE:
            if self.result_count == 0:
                if not self.no_match or self.reason != "NO_MATCH":
                    raise NamedToolContractError(
                        "complete zero-result authority receipt must state NO_MATCH"
                    )
            elif self.no_match or self.reason is not None:
                raise NamedToolContractError(
                    "complete positive authority receipt cannot state failure"
                )
        else:
            if self.result_count != 0 or self.no_match or self.reason is None:
                raise NamedToolContractError(
                    "non-complete authority receipt must retain a reason and no results"
                )
        if self.independently_attributable is not True:
            raise NamedToolContractError(
                "authority receipt must remain independently attributable"
            )
        for name in (
            "external_call_count",
            "provider_call_count",
            "model_call_count",
            "embedding_call_count",
            "provider_spend_micros",
        ):
            _require_non_negative_int(getattr(self, name), field=name)
        if any(
            getattr(self, name) != 0
            for name in (
                "external_call_count",
                "provider_call_count",
                "model_call_count",
                "embedding_call_count",
                "provider_spend_micros",
            )
        ):
            raise NamedToolContractError(
                "Increment 5 authority attribution cannot report external work"
            )
        if self.authority_effect != "NONE":
            raise NamedToolContractError(
                "authority attribution cannot claim an authority effect"
            )
        if type(self.production_activation_authorized) is not bool:
            raise NamedToolContractError(
                "authority production activation flag must be boolean"
            )
        if self.production_activation_authorized:
            raise NamedToolContractError(
                "authority attribution cannot authorize production activation"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "tool_request_digest": self.tool_request_digest,
            "tool_id": self.tool_id.value,
            "authority_mode": self.authority_mode.value,
            "authority_schema_version": self.authority_schema_version,
            "authority_request_digest": self.authority_request_digest,
            "authority_receipt_digest": self.authority_receipt_digest,
            "authority_profile_id": self.authority_profile_id,
            "component_identities": [
                item.canonical_value() for item in self.component_identities
            ],
            "query_valid_time": self.query_valid_time,
            "serving_time": self.serving_time,
            "outcome": self.outcome.value,
            "reason": self.reason,
            "result_count": self.result_count,
            "no_match": self.no_match,
            "authority_watermark": self.authority_watermark,
            "authority_receipt_bytes": self.authority_receipt_bytes,
            "independently_attributable": self.independently_attributable,
            "external_call_count": self.external_call_count,
            "provider_call_count": self.provider_call_count,
            "model_call_count": self.model_call_count,
            "embedding_call_count": self.embedding_call_count,
            "provider_spend_micros": self.provider_spend_micros,
            "authority_effect": self.authority_effect,
            "production_activation_authorized": (
                self.production_activation_authorized
            ),
        }

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, object]
    ) -> "AuthorityReceiptAttribution":
        required = {
            "tool_request_digest",
            "tool_id",
            "authority_mode",
            "authority_schema_version",
            "authority_request_digest",
            "authority_receipt_digest",
            "authority_profile_id",
            "component_identities",
            "query_valid_time",
            "serving_time",
            "outcome",
            "reason",
            "result_count",
            "no_match",
            "authority_watermark",
            "authority_receipt_bytes",
            "independently_attributable",
            "external_call_count",
            "provider_call_count",
            "model_call_count",
            "embedding_call_count",
            "provider_spend_micros",
            "authority_effect",
            "production_activation_authorized",
        }
        if set(value) != required:
            raise NamedToolContractError("authority attribution keys are not exact")
        raw_components = value["component_identities"]
        if not isinstance(raw_components, list) or not all(
            isinstance(item, dict) for item in raw_components
        ):
            raise NamedToolContractError(
                "authority component identities must be objects"
            )
        try:
            return cls(
                tool_request_digest=value["tool_request_digest"],
                tool_id=NamedToolId(value["tool_id"]),
                authority_mode=NamedAuthorityMode(value["authority_mode"]),
                authority_schema_version=value["authority_schema_version"],
                authority_request_digest=value["authority_request_digest"],
                authority_receipt_digest=value["authority_receipt_digest"],
                authority_profile_id=value["authority_profile_id"],
                component_identities=tuple(
                    AuthorityComponentIdentity.from_mapping(item)
                    for item in raw_components
                ),
                query_valid_time=value["query_valid_time"],
                serving_time=value["serving_time"],
                outcome=NamedAuthorityOutcome(value["outcome"]),
                reason=value["reason"],
                result_count=value["result_count"],
                no_match=value["no_match"],
                authority_watermark=value["authority_watermark"],
                authority_receipt_bytes=value["authority_receipt_bytes"],
                independently_attributable=value["independently_attributable"],
                external_call_count=value["external_call_count"],
                provider_call_count=value["provider_call_count"],
                model_call_count=value["model_call_count"],
                embedding_call_count=value["embedding_call_count"],
                provider_spend_micros=value["provider_spend_micros"],
                authority_effect=value["authority_effect"],
                production_activation_authorized=value[
                    "production_activation_authorized"
                ],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise NamedToolContractError(
                "authority attribution value is malformed"
            ) from exc


@dataclass(frozen=True, slots=True)
class AttributedAuthorityResult:
    attribution: AuthorityReceiptAttribution
    authority_receipt_bytes: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.attribution, AuthorityReceiptAttribution):
            raise NamedToolContractError(
                "authority result attribution must be typed"
            )
        if not isinstance(self.authority_receipt_bytes, bytes) or not (
            self.authority_receipt_bytes
        ):
            raise NamedToolContractError(
                "authority result must retain non-empty canonical receipt bytes"
            )
        if len(self.authority_receipt_bytes) != (
            self.attribution.authority_receipt_bytes
        ):
            raise NamedToolContractError(
                "authority receipt byte count does not match retained bytes"
            )
        if _digest(self.authority_receipt_bytes) != (
            self.attribution.authority_receipt_digest
        ):
            raise NamedToolContractError(
                "authority receipt digest does not match retained bytes"
            )


class NamedAuthorityPort(Protocol):
    port_id: str
    tool_id: NamedToolId
    authority_mode: NamedAuthorityMode

    def execute(self, request: NamedToolRequest) -> AttributedAuthorityResult:
        ...


class NamedAuthorityPortRegistry:
    """Closed registry requiring exactly one port for both authority tools."""

    def __init__(self, ports: Sequence[NamedAuthorityPort]) -> None:
        if len(ports) != len(AUTHORITY_TOOL_MODES):
            raise NamedToolAuthorityExecutionError(
                "authority port registry must contain exactly two ports"
            )
        by_tool: dict[NamedToolId, NamedAuthorityPort] = {}
        ids: set[str] = set()
        inventory: list[dict[str, str]] = []
        for port in ports:
            port_id = getattr(port, "port_id", None)
            tool_id = getattr(port, "tool_id", None)
            mode = getattr(port, "authority_mode", None)
            if not isinstance(port_id, str):
                raise NamedToolAuthorityExecutionError(
                    "authority port id must be text"
                )
            _require_token(port_id, field="authority_port_id")
            if port_id in ids:
                raise NamedToolAuthorityExecutionError(
                    "authority port ids must be unique"
                )
            ids.add(port_id)
            if tool_id not in AUTHORITY_TOOL_MODES:
                raise NamedToolAuthorityExecutionError(
                    "authority port tool is not in the closed inventory"
                )
            if not isinstance(mode, NamedAuthorityMode):
                raise NamedToolAuthorityExecutionError(
                    "authority port mode must be typed"
                )
            if AUTHORITY_TOOL_MODES[tool_id] is not mode:
                raise NamedToolAuthorityExecutionError(
                    "authority port mode does not match its named tool"
                )
            if tool_id in by_tool:
                raise NamedToolAuthorityExecutionError(
                    "authority port registry contains a duplicate tool"
                )
            if not callable(getattr(port, "execute", None)):
                raise NamedToolAuthorityExecutionError(
                    "authority port must expose one execute operation"
                )
            by_tool[tool_id] = port
            inventory.append(
                {
                    "port_id": port_id,
                    "tool_id": tool_id.value,
                    "authority_mode": mode.value,
                }
            )
        if set(by_tool) != set(AUTHORITY_TOOL_MODES):
            raise NamedToolAuthorityExecutionError(
                "authority port registry is missing a required tool"
            )
        self._ports = by_tool
        self.registry_digest = _digest(
            _canonical(
                {
                    "schema_version": (
                        "newsroom.increment5.named-authority-port-registry.v1"
                    ),
                    "ports": sorted(inventory, key=lambda item: item["tool_id"]),
                }
            )
        )

    def get(self, tool_id: NamedToolId) -> NamedAuthorityPort:
        try:
            return self._ports[tool_id]
        except KeyError as exc:
            raise NamedToolAuthorityExecutionError(
                "no authority port is registered for the named tool"
            ) from exc


@dataclass(frozen=True, slots=True)
class NamedAuthorityExecutionReceipt:
    execution_id: str
    execution_request_digest: str
    tool_request_digest: str
    tool_envelope_digest: str
    authorization_receipt_digest: str
    authorization_decision_id: str
    port_registry_digest: str
    port_id: str | None
    tool_id: NamedToolId
    authority_mode: NamedAuthorityMode
    outcome: NamedAuthorityExecutionOutcome
    reason: NamedAuthorityExecutionReason | None
    authority_attribution: AuthorityReceiptAttribution | None
    result_count: int
    no_match: bool
    response_limit_bytes: int
    authority_read_executed: bool
    authority_effect: str = "NONE"
    qualification_authority_granted: bool = False
    production_activation_authorized: bool = False

    def __post_init__(self) -> None:
        _require_uuid(self.execution_id, field="authority_execution_id")
        for name in (
            "execution_request_digest",
            "tool_request_digest",
            "tool_envelope_digest",
            "authorization_receipt_digest",
            "port_registry_digest",
        ):
            _require_digest(getattr(self, name), field=name)
        _require_uuid(
            self.authorization_decision_id,
            field="authorization_decision_id",
        )
        if self.port_id is not None:
            _require_token(self.port_id, field="authority_execution_port_id")
        if self.tool_id not in AUTHORITY_TOOL_MODES:
            raise NamedToolContractError(
                "authority execution receipt tool is not authority-backed"
            )
        if not isinstance(self.authority_mode, NamedAuthorityMode):
            raise NamedToolContractError(
                "authority execution mode must be typed"
            )
        if AUTHORITY_TOOL_MODES[self.tool_id] is not self.authority_mode:
            raise NamedToolContractError(
                "authority execution mode does not match tool"
            )
        if not isinstance(self.outcome, NamedAuthorityExecutionOutcome):
            raise NamedToolContractError(
                "authority execution outcome must be typed"
            )
        if self.reason is not None and not isinstance(
            self.reason, NamedAuthorityExecutionReason
        ):
            raise NamedToolContractError(
                "authority execution reason must be typed"
            )
        if self.authority_attribution is not None:
            if not isinstance(
                self.authority_attribution, AuthorityReceiptAttribution
            ):
                raise NamedToolContractError(
                    "authority execution attribution must be typed"
                )
            if self.authority_attribution.tool_id is not self.tool_id:
                raise NamedToolContractError(
                    "authority execution attribution tool mismatch"
                )
        _require_non_negative_int(self.result_count, field="execution_result_count")
        if self.result_count > NAMED_TOOL_RESULT_LIMIT:
            raise NamedToolContractError(
                "authority execution result count exceeds global bound"
            )
        if type(self.no_match) is not bool:
            raise NamedToolContractError("authority execution no_match must be boolean")
        if (
            isinstance(self.response_limit_bytes, bool)
            or not isinstance(self.response_limit_bytes, int)
            or not 1_024 <= self.response_limit_bytes <= NAMED_TOOL_RESPONSE_LIMIT_BYTES
        ):
            raise NamedToolContractError(
                "authority execution response limit is outside bounds"
            )
        if type(self.authority_read_executed) is not bool:
            raise NamedToolContractError(
                "authority_read_executed must be boolean"
            )
        if self.authority_read_executed != (
            self.authority_attribution is not None
        ):
            raise NamedToolContractError(
                "authority execution flag must match retained attribution"
            )
        if self.authority_read_executed and self.port_id is None:
            raise NamedToolContractError(
                "executed authority receipt must retain the port identity"
            )
        if self.outcome is NamedAuthorityExecutionOutcome.COMPLETE:
            if self.result_count == 0:
                if not self.no_match or self.reason is not (
                    NamedAuthorityExecutionReason.NO_MATCH
                ):
                    raise NamedToolContractError(
                        "complete zero-result execution must state NO_MATCH"
                    )
            elif self.no_match or self.reason is not None:
                raise NamedToolContractError(
                    "complete positive execution cannot state failure"
                )
        else:
            if self.result_count != 0 or self.no_match or self.reason is None:
                raise NamedToolContractError(
                    "non-complete execution must retain reason and no results"
                )
        if self.authority_effect != "NONE":
            raise NamedToolContractError(
                "authority tool execution cannot claim an authority effect"
            )
        for name in (
            "qualification_authority_granted",
            "production_activation_authorized",
        ):
            if type(getattr(self, name)) is not bool:
                raise NamedToolContractError(f"{name} must be boolean")
        if self.qualification_authority_granted or (
            self.production_activation_authorized
        ):
            raise NamedToolContractError(
                "authority execution cannot grant qualification or activation"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": (
                "newsroom.increment5.named-authority-execution-receipt.v1"
            ),
            "execution_id": self.execution_id,
            "execution_request_digest": self.execution_request_digest,
            "tool_request_digest": self.tool_request_digest,
            "tool_envelope_digest": self.tool_envelope_digest,
            "authorization_receipt_digest": self.authorization_receipt_digest,
            "authorization_decision_id": self.authorization_decision_id,
            "port_registry_digest": self.port_registry_digest,
            "port_id": self.port_id,
            "tool_id": self.tool_id.value,
            "authority_mode": self.authority_mode.value,
            "outcome": self.outcome.value,
            "reason": None if self.reason is None else self.reason.value,
            "authority_attribution": (
                None
                if self.authority_attribution is None
                else self.authority_attribution.canonical_value()
            ),
            "result_count": self.result_count,
            "no_match": self.no_match,
            "response_limit_bytes": self.response_limit_bytes,
            "authority_read_executed": self.authority_read_executed,
            "authority_effect": self.authority_effect,
            "qualification_authority_granted": (
                self.qualification_authority_granted
            ),
            "production_activation_authorized": (
                self.production_activation_authorized
            ),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical(self.canonical_value())

    @property
    def receipt_digest(self) -> str:
        return _digest(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> "NamedAuthorityExecutionReceipt":
        try:
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise NamedToolAuthorityExecutionError(
                "retained authority execution receipt is not JSON"
            ) from exc
        if not isinstance(value, dict):
            raise NamedToolAuthorityExecutionError(
                "retained authority execution root is not an object"
            )
        required = {
            "schema_version",
            "execution_id",
            "execution_request_digest",
            "tool_request_digest",
            "tool_envelope_digest",
            "authorization_receipt_digest",
            "authorization_decision_id",
            "port_registry_digest",
            "port_id",
            "tool_id",
            "authority_mode",
            "outcome",
            "reason",
            "authority_attribution",
            "result_count",
            "no_match",
            "response_limit_bytes",
            "authority_read_executed",
            "authority_effect",
            "qualification_authority_granted",
            "production_activation_authorized",
        }
        if set(value) != required or value["schema_version"] != (
            "newsroom.increment5.named-authority-execution-receipt.v1"
        ):
            raise NamedToolAuthorityExecutionError(
                "retained authority execution schema is not accepted"
            )
        raw_attribution = value["authority_attribution"]
        if raw_attribution is not None and not isinstance(raw_attribution, dict):
            raise NamedToolAuthorityExecutionError(
                "retained authority attribution must be an object or null"
            )
        try:
            return cls(
                execution_id=value["execution_id"],
                execution_request_digest=value["execution_request_digest"],
                tool_request_digest=value["tool_request_digest"],
                tool_envelope_digest=value["tool_envelope_digest"],
                authorization_receipt_digest=value[
                    "authorization_receipt_digest"
                ],
                authorization_decision_id=value["authorization_decision_id"],
                port_registry_digest=value["port_registry_digest"],
                port_id=value["port_id"],
                tool_id=NamedToolId(value["tool_id"]),
                authority_mode=NamedAuthorityMode(value["authority_mode"]),
                outcome=NamedAuthorityExecutionOutcome(value["outcome"]),
                reason=(
                    None
                    if value["reason"] is None
                    else NamedAuthorityExecutionReason(value["reason"])
                ),
                authority_attribution=(
                    None
                    if raw_attribution is None
                    else AuthorityReceiptAttribution.from_mapping(raw_attribution)
                ),
                result_count=value["result_count"],
                no_match=value["no_match"],
                response_limit_bytes=value["response_limit_bytes"],
                authority_read_executed=value["authority_read_executed"],
                authority_effect=value["authority_effect"],
                qualification_authority_granted=value[
                    "qualification_authority_granted"
                ],
                production_activation_authorized=value[
                    "production_activation_authorized"
                ],
            )
        except (KeyError, TypeError, ValueError, NamedToolContractError) as exc:
            raise NamedToolAuthorityExecutionError(
                "retained authority execution receipt is malformed"
            ) from exc


@dataclass(frozen=True, slots=True)
class NamedAuthorityExecutionResult:
    receipt: NamedAuthorityExecutionReceipt
    authority_receipt_bytes: bytes | None

    def __post_init__(self) -> None:
        if not isinstance(self.receipt, NamedAuthorityExecutionReceipt):
            raise NamedToolContractError(
                "authority execution result receipt must be typed"
            )
        if self.authority_receipt_bytes is not None and not isinstance(
            self.authority_receipt_bytes, bytes
        ):
            raise NamedToolContractError(
                "authority execution raw receipt must be bytes or null"
            )


class NamedAuthorityExecutionJournal:
    """First-writer-wins non-authoritative execution audit journal."""

    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path):
            raise TypeError("authority execution journal path must be pathlib.Path")
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS increment5_named_tool_authority_receipts(
                        idempotency_key TEXT PRIMARY KEY,
                        execution_request_digest TEXT NOT NULL,
                        receipt_bytes BLOB NOT NULL,
                        receipt_digest TEXT NOT NULL,
                        authority_receipt_bytes BLOB,
                        authority_receipt_digest TEXT
                    ) STRICT
                    """
                )
        except sqlite3.Error as exc:
            raise NamedToolAuthorityExecutionError(
                "authority execution journal initialization failed"
            ) from exc

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            isolation_level=None,
            timeout=5.0,
            check_same_thread=False,
        )
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @staticmethod
    def _execution_request_digest(
        request: NamedToolRequest,
        authorization: NamedToolAuthorizationReceipt,
        registry_digest: str,
    ) -> str:
        return _digest(
            _canonical(
                {
                    "schema_version": (
                        "newsroom.increment5.named-authority-execution-request.v1"
                    ),
                    "tool_request_digest": request.request_digest,
                    "authorization_receipt_digest": authorization.receipt_digest,
                    "port_registry_digest": registry_digest,
                }
            )
        )

    @staticmethod
    def _decode(
        *,
        execution_request_digest: str,
        receipt_bytes: bytes,
        receipt_digest: str,
        authority_bytes: bytes | None,
        authority_digest: str | None,
    ) -> NamedAuthorityExecutionResult:
        if _digest(receipt_bytes) != receipt_digest:
            raise NamedToolAuthorityExecutionError(
                "retained authority execution receipt digest mismatch"
            )
        receipt = NamedAuthorityExecutionReceipt.from_canonical_bytes(receipt_bytes)
        if receipt.execution_request_digest != execution_request_digest:
            raise NamedToolAuthorityExecutionError(
                "retained authority execution request binding mismatch"
            )
        if authority_bytes is None:
            if authority_digest is not None or receipt.authority_attribution is not None:
                raise NamedToolAuthorityExecutionError(
                    "retained authority receipt presence mismatch"
                )
        else:
            if authority_digest is None or _digest(authority_bytes) != authority_digest:
                raise NamedToolAuthorityExecutionError(
                    "retained raw authority receipt digest mismatch"
                )
            attribution = receipt.authority_attribution
            if attribution is None or attribution.authority_receipt_digest != (
                authority_digest
            ):
                raise NamedToolAuthorityExecutionError(
                    "retained authority attribution digest mismatch"
                )
        return NamedAuthorityExecutionResult(
            receipt=receipt,
            authority_receipt_bytes=authority_bytes,
        )

    def _existing(
        self,
        *,
        idempotency_key: str,
        execution_request_digest: str,
    ) -> NamedAuthorityExecutionResult | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT execution_request_digest,receipt_bytes,receipt_digest,
                           authority_receipt_bytes,authority_receipt_digest
                    FROM increment5_named_tool_authority_receipts
                    WHERE idempotency_key=?
                    """,
                    (idempotency_key,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise NamedToolAuthorityExecutionError(
                "authority execution journal read failed"
            ) from exc
        if row is None:
            return None
        if row[0] != execution_request_digest:
            raise NamedToolAuthorityExecutionError(
                "authority execution idempotency semantic conflict"
            )
        return self._decode(
            execution_request_digest=row[0],
            receipt_bytes=bytes(row[1]),
            receipt_digest=row[2],
            authority_bytes=None if row[3] is None else bytes(row[3]),
            authority_digest=row[4],
        )

    def execute(
        self,
        request: NamedToolRequest,
        authorization: NamedToolAuthorizationReceipt,
        registry_digest: str,
        producer: Callable[[str], NamedAuthorityExecutionResult],
    ) -> NamedAuthorityExecutionResult:
        execution_request_digest = self._execution_request_digest(
            request, authorization, registry_digest
        )
        existing = self._existing(
            idempotency_key=request.envelope.idempotency_key,
            execution_request_digest=execution_request_digest,
        )
        if existing is not None:
            return existing
        result = producer(execution_request_digest)
        if result.receipt.execution_request_digest != execution_request_digest:
            raise NamedToolAuthorityExecutionError(
                "produced authority execution receipt does not bind request"
            )
        receipt_bytes = result.receipt.canonical_bytes
        receipt_digest = _digest(receipt_bytes)
        authority_bytes = result.authority_receipt_bytes
        authority_digest = (
            None if authority_bytes is None else _digest(authority_bytes)
        )
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT execution_request_digest,receipt_bytes,receipt_digest,
                       authority_receipt_bytes,authority_receipt_digest
                FROM increment5_named_tool_authority_receipts
                WHERE idempotency_key=?
                """,
                (request.envelope.idempotency_key,),
            ).fetchone()
            if row is not None:
                connection.execute("ROLLBACK")
                if row[0] != execution_request_digest:
                    raise NamedToolAuthorityExecutionError(
                        "concurrent authority execution semantic conflict"
                    )
                return self._decode(
                    execution_request_digest=row[0],
                    receipt_bytes=bytes(row[1]),
                    receipt_digest=row[2],
                    authority_bytes=None if row[3] is None else bytes(row[3]),
                    authority_digest=row[4],
                )
            connection.execute(
                """
                INSERT INTO increment5_named_tool_authority_receipts(
                    idempotency_key,execution_request_digest,receipt_bytes,
                    receipt_digest,authority_receipt_bytes,authority_receipt_digest
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    request.envelope.idempotency_key,
                    execution_request_digest,
                    receipt_bytes,
                    receipt_digest,
                    authority_bytes,
                    authority_digest,
                ),
            )
            connection.execute("COMMIT")
        except NamedToolAuthorityExecutionError:
            raise
        except sqlite3.Error as exc:
            if connection is not None and connection.in_transaction:
                connection.execute("ROLLBACK")
            raise NamedToolAuthorityExecutionError(
                "authority execution journal write failed"
            ) from exc
        finally:
            if connection is not None:
                connection.close()
        return result


class NamedToolAuthorityExecutor:
    """Authorization-first executor for the two fixed authority-backed tools."""

    def __init__(
        self,
        *,
        registry: NamedAuthorityPortRegistry,
        journal: NamedAuthorityExecutionJournal,
    ) -> None:
        if not isinstance(registry, NamedAuthorityPortRegistry):
            raise TypeError("authority executor registry must be typed")
        if not isinstance(journal, NamedAuthorityExecutionJournal):
            raise TypeError("authority executor journal must be typed")
        self.registry = registry
        self.journal = journal

    def execute(
        self,
        request: CollisionHydrationLookupToolRequest
        | SourceRevisionImpactLookupToolRequest,
        authorization: NamedToolAuthorizationReceipt,
    ) -> NamedAuthorityExecutionResult:
        if request.envelope.tool_id not in AUTHORITY_TOOL_MODES:
            raise NamedToolAuthorityExecutionError(
                "named tool is not supported by the authority executor"
            )
        return self.journal.execute(
            request,
            authorization,
            self.registry.registry_digest,
            lambda digest: self._produce(request, authorization, digest),
        )

    def _produce(
        self,
        request: CollisionHydrationLookupToolRequest
        | SourceRevisionImpactLookupToolRequest,
        authorization: NamedToolAuthorizationReceipt,
        execution_request_digest: str,
    ) -> NamedAuthorityExecutionResult:
        binding = self._authorization_binding_reason(request, authorization)
        if binding is not None:
            return self._result(
                request,
                authorization,
                execution_request_digest,
                port_id=None,
                outcome=NamedAuthorityExecutionOutcome.POLICY_BLOCKED,
                reason=binding,
                authority_result=None,
            )
        if authorization.outcome is not NamedToolGateOutcome.AUTHORIZED:
            outcome = (
                NamedAuthorityExecutionOutcome.STALE
                if authorization.outcome is NamedToolGateOutcome.STALE
                else NamedAuthorityExecutionOutcome.POLICY_BLOCKED
            )
            return self._result(
                request,
                authorization,
                execution_request_digest,
                port_id=None,
                outcome=outcome,
                reason=NamedAuthorityExecutionReason.LOCAL_AUTHORIZATION_BLOCKED,
                authority_result=None,
            )
        port = self.registry.get(request.envelope.tool_id)
        try:
            authority_result = port.execute(request)
        except NamedAuthorityPolicyBlockedError:
            return self._result(
                request,
                authorization,
                execution_request_digest,
                port_id=port.port_id,
                outcome=NamedAuthorityExecutionOutcome.POLICY_BLOCKED,
                reason=NamedAuthorityExecutionReason.ADAPTER_POLICY_BLOCKED,
                authority_result=None,
            )
        except Exception:
            return self._result(
                request,
                authorization,
                execution_request_digest,
                port_id=port.port_id,
                outcome=NamedAuthorityExecutionOutcome.UNAVAILABLE,
                reason=NamedAuthorityExecutionReason.AUTHORITY_PORT_UNAVAILABLE,
                authority_result=None,
            )
        try:
            self._validate_authority_result(request, port, authority_result)
        except (NamedToolContractError, NamedToolAuthorityExecutionError):
            return self._result(
                request,
                authorization,
                execution_request_digest,
                port_id=port.port_id,
                outcome=NamedAuthorityExecutionOutcome.UNAVAILABLE,
                reason=NamedAuthorityExecutionReason.AUTHORITY_RECEIPT_INVALID,
                authority_result=None,
            )
        attribution = authority_result.attribution
        if attribution.result_count > request.envelope.result_limit:
            return self._result(
                request,
                authorization,
                execution_request_digest,
                port_id=port.port_id,
                outcome=NamedAuthorityExecutionOutcome.INCOMPLETE,
                reason=NamedAuthorityExecutionReason.RESULT_LIMIT_EXCEEDED,
                authority_result=authority_result,
                force_zero_results=True,
            )
        if attribution.authority_receipt_bytes > (
            request.envelope.response_limit_bytes
        ):
            return self._result(
                request,
                authorization,
                execution_request_digest,
                port_id=port.port_id,
                outcome=NamedAuthorityExecutionOutcome.INCOMPLETE,
                reason=NamedAuthorityExecutionReason.RESPONSE_LIMIT_EXCEEDED,
                authority_result=authority_result,
                force_zero_results=True,
            )
        outcome = NamedAuthorityExecutionOutcome(attribution.outcome.value)
        if outcome is NamedAuthorityExecutionOutcome.COMPLETE:
            reason = (
                NamedAuthorityExecutionReason.NO_MATCH
                if attribution.no_match
                else None
            )
        elif attribution.reason == "RESULT_BOUND_EXCEEDED":
            reason = NamedAuthorityExecutionReason.RESULT_LIMIT_EXCEEDED
        elif attribution.reason == "RESPONSE_BOUND_EXCEEDED":
            reason = NamedAuthorityExecutionReason.RESPONSE_LIMIT_EXCEEDED
        else:
            reason = NamedAuthorityExecutionReason.AUTHORITY_NON_COMPLETE
        return self._result(
            request,
            authorization,
            execution_request_digest,
            port_id=port.port_id,
            outcome=outcome,
            reason=reason,
            authority_result=authority_result,
        )

    @staticmethod
    def _authorization_binding_reason(
        request: NamedToolRequest,
        authorization: NamedToolAuthorizationReceipt,
    ) -> NamedAuthorityExecutionReason | None:
        envelope = request.envelope
        matches = (
            authorization.request_digest == request.request_digest
            and authorization.envelope_digest == envelope.envelope_digest
            and authorization.tool_id is envelope.tool_id
            and authorization.actor_id == envelope.actor_id
            and authorization.authenticated_principal_digest
            == envelope.authenticated_principal_digest
            and authorization.purpose is envelope.purpose
            and authorization.requested_scope_digest
            == envelope.requested_scope.scope_digest
        )
        if not matches:
            return NamedAuthorityExecutionReason.AUTHORIZATION_BINDING_MISMATCH
        if (
            authorization.outcome is NamedToolGateOutcome.AUTHORIZED
            and not authorization.local_tool_call_authorized
        ) or (
            authorization.outcome is not NamedToolGateOutcome.AUTHORIZED
            and authorization.local_tool_call_authorized
        ):
            return NamedAuthorityExecutionReason.AUTHORIZATION_BINDING_MISMATCH
        return None

    @staticmethod
    def _validate_authority_result(
        request: NamedToolRequest,
        port: NamedAuthorityPort,
        result: AttributedAuthorityResult,
    ) -> None:
        if not isinstance(result, AttributedAuthorityResult):
            raise NamedToolAuthorityExecutionError(
                "authority port did not return an attributed result"
            )
        attribution = result.attribution
        envelope = request.envelope
        if attribution.tool_request_digest != request.request_digest:
            raise NamedToolAuthorityExecutionError(
                "authority attribution does not bind named request"
            )
        if attribution.tool_id is not envelope.tool_id:
            raise NamedToolAuthorityExecutionError(
                "authority attribution tool does not match request"
            )
        if attribution.authority_mode is not port.authority_mode:
            raise NamedToolAuthorityExecutionError(
                "authority attribution mode does not match port"
            )
        if port.tool_id is not envelope.tool_id:
            raise NamedToolAuthorityExecutionError(
                "registered authority port tool does not match request"
            )
        if attribution.query_valid_time != envelope.query_valid_time or (
            attribution.serving_time != envelope.serving_time
        ):
            raise NamedToolAuthorityExecutionError(
                "authority temporal attribution does not match request"
            )

    def _result(
        self,
        request: NamedToolRequest,
        authorization: NamedToolAuthorizationReceipt,
        execution_request_digest: str,
        *,
        port_id: str | None,
        outcome: NamedAuthorityExecutionOutcome,
        reason: NamedAuthorityExecutionReason | None,
        authority_result: AttributedAuthorityResult | None,
        force_zero_results: bool = False,
    ) -> NamedAuthorityExecutionResult:
        attribution = (
            None if authority_result is None else authority_result.attribution
        )
        if attribution is None or force_zero_results:
            result_count = 0
            no_match = False
        else:
            result_count = attribution.result_count
            no_match = attribution.no_match
        execution_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                "|".join(
                    (
                        execution_request_digest,
                        outcome.value,
                        "NONE" if reason is None else reason.value,
                        "NO_AUTHORITY"
                        if attribution is None
                        else attribution.authority_receipt_digest,
                    )
                ),
            )
        )
        receipt = NamedAuthorityExecutionReceipt(
            execution_id=execution_id,
            execution_request_digest=execution_request_digest,
            tool_request_digest=request.request_digest,
            tool_envelope_digest=request.envelope.envelope_digest,
            authorization_receipt_digest=authorization.receipt_digest,
            authorization_decision_id=authorization.decision_id,
            port_registry_digest=self.registry.registry_digest,
            port_id=port_id,
            tool_id=request.envelope.tool_id,
            authority_mode=AUTHORITY_TOOL_MODES[request.envelope.tool_id],
            outcome=outcome,
            reason=reason,
            authority_attribution=attribution,
            result_count=result_count,
            no_match=no_match,
            response_limit_bytes=request.envelope.response_limit_bytes,
            authority_read_executed=attribution is not None,
        )
        return NamedAuthorityExecutionResult(
            receipt=receipt,
            authority_receipt_bytes=(
                None
                if authority_result is None
                else authority_result.authority_receipt_bytes
            ),
        )


AuthorityBackedRequest: TypeAlias = (
    CollisionHydrationLookupToolRequest | SourceRevisionImpactLookupToolRequest
)


__all__ = [
    "AUTHORITY_TOOL_MODES",
    "AttributedAuthorityResult",
    "AuthorityBackedRequest",
    "AuthorityComponentIdentity",
    "AuthorityReceiptAttribution",
    "NamedAuthorityExecutionJournal",
    "NamedAuthorityExecutionOutcome",
    "NamedAuthorityExecutionReason",
    "NamedAuthorityExecutionReceipt",
    "NamedAuthorityExecutionResult",
    "NamedAuthorityMode",
    "NamedAuthorityOutcome",
    "NamedAuthorityPolicyBlockedError",
    "NamedAuthorityPort",
    "NamedAuthorityPortRegistry",
    "NamedToolAuthorityExecutionError",
    "NamedToolAuthorityExecutor",
]
