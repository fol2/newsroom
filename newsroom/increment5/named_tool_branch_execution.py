"""Branch-neutral execution kernel for the first four Increment 5C tools.

The kernel requires one exact 5C1 authorization receipt, dispatches to exactly
one registered branch port, validates an independently attributable branch
receipt, retains the raw canonical branch bytes in an immutable audit journal,
and emits one bounded named-tool execution receipt.

Concrete translation into the merged 5B request/receipt classes is deliberately
outside this module and belongs to 5C2B.  This module performs no retrieval,
Neo4j access, hydration, collision check, fusion, Candidate mutation, provider
call, network call, publication or production activation by itself.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence

from newsroom.increment5.named_tool_authorization import (
    NamedToolAuthorizationReceipt,
    NamedToolGateOutcome,
)
from newsroom.increment5.named_tool_contracts import (
    NAMED_TOOL_RESPONSE_LIMIT_BYTES,
    NAMED_TOOL_RESULT_LIMIT,
    NamedToolContractError,
    NamedToolId,
    NamedToolRequest,
)


_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}\Z")
_REASON_RE = re.compile(r"[A-Z0-9][A-Z0-9._:\-]{0,255}\Z")
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


class NamedToolBranchExecutionError(RuntimeError):
    """The branch registry, port result or immutable execution journal failed."""


class NamedBranchMode(StrEnum):
    EXACT = "EXACT"
    FULL_TEXT = "FULL_TEXT"
    VECTOR = "VECTOR"
    ADMITTED_GRAPH = "ADMITTED_GRAPH"


class NamedBranchOutcome(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class NamedToolExecutionOutcome(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class NamedToolExecutionReason(StrEnum):
    NO_MATCH = "NO_MATCH"
    LOCAL_AUTHORIZATION_BLOCKED = "LOCAL_AUTHORIZATION_BLOCKED"
    AUTHORIZATION_BINDING_MISMATCH = "AUTHORIZATION_BINDING_MISMATCH"
    BRANCH_PORT_UNAVAILABLE = "BRANCH_PORT_UNAVAILABLE"
    BRANCH_RECEIPT_INVALID = "BRANCH_RECEIPT_INVALID"
    BRANCH_NON_COMPLETE = "BRANCH_NON_COMPLETE"
    RESULT_LIMIT_EXCEEDED = "RESULT_LIMIT_EXCEEDED"
    RESPONSE_LIMIT_EXCEEDED = "RESPONSE_LIMIT_EXCEEDED"


BRANCH_TOOL_MODES: Mapping[NamedToolId, NamedBranchMode] = {
    NamedToolId.EXACT_AUTHORITY_LOOKUP: NamedBranchMode.EXACT,
    NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL: NamedBranchMode.FULL_TEXT,
    NamedToolId.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL: NamedBranchMode.VECTOR,
    NamedToolId.BOUNDED_ADMITTED_GRAPH_TRAVERSAL: NamedBranchMode.ADMITTED_GRAPH,
}


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise NamedToolContractError("branch execution value is not canonical JSON") from exc


def _digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


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


def _require_non_negative_int(value: int, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise NamedToolContractError(f"{field} must be a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class BranchComponentIdentity:
    name: str
    digest: str

    def __post_init__(self) -> None:
        _require_token(self.name, field="branch_component_name")
        _require_digest(self.digest, field="branch_component_digest")

    def canonical_value(self) -> dict[str, str]:
        return {"name": self.name, "digest": self.digest}

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "BranchComponentIdentity":
        if set(value) != {"name", "digest"}:
            raise NamedToolContractError("branch component identity keys are not exact")
        if not isinstance(value["name"], str) or not isinstance(value["digest"], str):
            raise NamedToolContractError("branch component identity fields must be text")
        return cls(name=value["name"], digest=value["digest"])


@dataclass(frozen=True, slots=True)
class BranchReceiptAttribution:
    tool_request_digest: str
    tool_id: NamedToolId
    branch_mode: NamedBranchMode
    branch_schema_version: str
    branch_request_digest: str
    branch_receipt_digest: str
    branch_profile_id: str
    branch_generation_id: str | None
    branch_generation_digest: str | None
    component_identities: tuple[BranchComponentIdentity, ...]
    query_valid_time: str
    serving_time: str
    outcome: NamedBranchOutcome
    reason: str | None
    result_count: int
    no_match: bool
    branch_receipt_bytes: int
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
            "branch_request_digest",
            "branch_receipt_digest",
        ):
            _require_digest(getattr(self, name), field=name)
        if self.tool_id not in BRANCH_TOOL_MODES:
            raise NamedToolContractError("branch attribution tool is not branch-backed")
        if not isinstance(self.branch_mode, NamedBranchMode):
            raise NamedToolContractError("branch mode must be typed")
        if BRANCH_TOOL_MODES[self.tool_id] is not self.branch_mode:
            raise NamedToolContractError("branch mode does not match named tool")
        _require_token(self.branch_schema_version, field="branch_schema_version")
        _require_token(self.branch_profile_id, field="branch_profile_id")
        if self.branch_generation_id is not None:
            _require_token(self.branch_generation_id, field="branch_generation_id")
        if self.branch_generation_digest is not None:
            _require_digest(
                self.branch_generation_digest,
                field="branch_generation_digest",
            )
        if (self.branch_generation_id is None) != (
            self.branch_generation_digest is None
        ):
            raise NamedToolContractError(
                "branch generation id and digest must be present together"
            )
        if not self.component_identities:
            raise NamedToolContractError(
                "branch attribution must retain at least one component identity"
            )
        if not all(
            isinstance(component, BranchComponentIdentity)
            for component in self.component_identities
        ):
            raise NamedToolContractError("branch component identities must be typed")
        names = tuple(component.name for component in self.component_identities)
        if names != tuple(sorted(set(names))):
            raise NamedToolContractError(
                "branch component identities must be sorted and unique"
            )
        query_valid = _parse_utc(
            self.query_valid_time,
            field="branch_query_valid_time",
        )
        serving = _parse_utc(self.serving_time, field="branch_serving_time")
        if query_valid > serving:
            raise NamedToolContractError(
                "branch query-valid time cannot be after serving time"
            )
        if not isinstance(self.outcome, NamedBranchOutcome):
            raise NamedToolContractError("branch outcome must be typed")
        if self.reason is not None:
            _require_reason(self.reason, field="branch_reason")
        _require_non_negative_int(self.result_count, field="branch_result_count")
        if self.result_count > NAMED_TOOL_RESULT_LIMIT:
            raise NamedToolContractError("branch result count exceeds the global bound")
        if not isinstance(self.no_match, bool):
            raise NamedToolContractError("branch no_match must be boolean")
        if (
            isinstance(self.branch_receipt_bytes, bool)
            or not isinstance(self.branch_receipt_bytes, int)
            or self.branch_receipt_bytes <= 0
        ):
            raise NamedToolContractError(
                "branch receipt byte count must be a positive integer"
            )
        if self.outcome is NamedBranchOutcome.COMPLETE:
            if self.result_count == 0:
                if not self.no_match or self.reason != "NO_MATCH":
                    raise NamedToolContractError(
                        "complete zero-result branch receipt must state NO_MATCH"
                    )
            elif self.no_match or self.reason is not None:
                raise NamedToolContractError(
                    "complete positive branch receipt cannot state no-match or failure"
                )
        else:
            if self.result_count != 0 or self.no_match or self.reason is None:
                raise NamedToolContractError(
                    "non-complete branch receipt must retain a reason and no results"
                )
        if self.independently_attributable is not True:
            raise NamedToolContractError(
                "branch receipt must remain independently attributable"
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
                "Increment 5 branch attribution cannot report external work or spend"
            )
        if self.authority_effect != "NONE":
            raise NamedToolContractError("branch attribution cannot claim authority effect")
        if self.production_activation_authorized:
            raise NamedToolContractError(
                "branch attribution cannot authorize production activation"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "tool_request_digest": self.tool_request_digest,
            "tool_id": self.tool_id.value,
            "branch_mode": self.branch_mode.value,
            "branch_schema_version": self.branch_schema_version,
            "branch_request_digest": self.branch_request_digest,
            "branch_receipt_digest": self.branch_receipt_digest,
            "branch_profile_id": self.branch_profile_id,
            "branch_generation_id": self.branch_generation_id,
            "branch_generation_digest": self.branch_generation_digest,
            "component_identities": [
                component.canonical_value()
                for component in self.component_identities
            ],
            "query_valid_time": self.query_valid_time,
            "serving_time": self.serving_time,
            "outcome": self.outcome.value,
            "reason": self.reason,
            "result_count": self.result_count,
            "no_match": self.no_match,
            "branch_receipt_bytes": self.branch_receipt_bytes,
            "independently_attributable": self.independently_attributable,
            "external_call_count": self.external_call_count,
            "provider_call_count": self.provider_call_count,
            "model_call_count": self.model_call_count,
            "embedding_call_count": self.embedding_call_count,
            "provider_spend_micros": self.provider_spend_micros,
            "authority_effect": self.authority_effect,
            "production_activation_authorized": self.production_activation_authorized,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "BranchReceiptAttribution":
        required = {
            "tool_request_digest",
            "tool_id",
            "branch_mode",
            "branch_schema_version",
            "branch_request_digest",
            "branch_receipt_digest",
            "branch_profile_id",
            "branch_generation_id",
            "branch_generation_digest",
            "component_identities",
            "query_valid_time",
            "serving_time",
            "outcome",
            "reason",
            "result_count",
            "no_match",
            "branch_receipt_bytes",
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
            raise NamedToolContractError("branch attribution keys are not exact")
        raw_components = value["component_identities"]
        if not isinstance(raw_components, list) or not all(
            isinstance(item, dict) for item in raw_components
        ):
            raise NamedToolContractError(
                "branch component identities must be objects"
            )
        text_fields = (
            "tool_request_digest",
            "branch_schema_version",
            "branch_request_digest",
            "branch_receipt_digest",
            "branch_profile_id",
            "query_valid_time",
            "serving_time",
            "authority_effect",
        )
        if not all(isinstance(value[name], str) for name in text_fields):
            raise NamedToolContractError("branch attribution text field is malformed")
        if value["branch_generation_id"] is not None and not isinstance(
            value["branch_generation_id"], str
        ):
            raise NamedToolContractError("branch generation id must be text or null")
        if value["branch_generation_digest"] is not None and not isinstance(
            value["branch_generation_digest"], str
        ):
            raise NamedToolContractError(
                "branch generation digest must be text or null"
            )
        if value["reason"] is not None and not isinstance(value["reason"], str):
            raise NamedToolContractError("branch reason must be text or null")
        try:
            tool_id = NamedToolId(value["tool_id"])
            mode = NamedBranchMode(value["branch_mode"])
            outcome = NamedBranchOutcome(value["outcome"])
        except (TypeError, ValueError) as exc:
            raise NamedToolContractError("branch attribution enum is not accepted") from exc
        return cls(
            tool_request_digest=value["tool_request_digest"],
            tool_id=tool_id,
            branch_mode=mode,
            branch_schema_version=value["branch_schema_version"],
            branch_request_digest=value["branch_request_digest"],
            branch_receipt_digest=value["branch_receipt_digest"],
            branch_profile_id=value["branch_profile_id"],
            branch_generation_id=value["branch_generation_id"],
            branch_generation_digest=value["branch_generation_digest"],
            component_identities=tuple(
                BranchComponentIdentity.from_mapping(item)
                for item in raw_components
            ),
            query_valid_time=value["query_valid_time"],
            serving_time=value["serving_time"],
            outcome=outcome,
            reason=value["reason"],
            result_count=value["result_count"],
            no_match=value["no_match"],
            branch_receipt_bytes=value["branch_receipt_bytes"],
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


@dataclass(frozen=True, slots=True)
class AttributedBranchResult:
    attribution: BranchReceiptAttribution
    branch_receipt_bytes: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.attribution, BranchReceiptAttribution):
            raise NamedToolContractError("branch result attribution must be typed")
        if not isinstance(self.branch_receipt_bytes, bytes) or not self.branch_receipt_bytes:
            raise NamedToolContractError(
                "branch result must retain non-empty canonical receipt bytes"
            )
        if len(self.branch_receipt_bytes) != self.attribution.branch_receipt_bytes:
            raise NamedToolContractError(
                "branch receipt byte count does not match retained bytes"
            )
        if _digest_bytes(self.branch_receipt_bytes) != (
            self.attribution.branch_receipt_digest
        ):
            raise NamedToolContractError(
                "branch receipt digest does not match retained bytes"
            )


class NamedBranchPort(Protocol):
    port_id: str
    tool_id: NamedToolId
    branch_mode: NamedBranchMode

    def execute(self, request: NamedToolRequest) -> AttributedBranchResult:
        ...


class NamedBranchPortRegistry:
    """Closed registry requiring exactly one port for each branch-backed tool."""

    def __init__(self, ports: Sequence[NamedBranchPort]) -> None:
        if len(ports) != len(BRANCH_TOOL_MODES):
            raise NamedToolBranchExecutionError(
                "branch port registry must contain exactly four ports"
            )
        by_tool: dict[NamedToolId, NamedBranchPort] = {}
        port_ids: set[str] = set()
        inventory: list[dict[str, str]] = []
        for port in ports:
            port_id = getattr(port, "port_id", None)
            tool_id = getattr(port, "tool_id", None)
            branch_mode = getattr(port, "branch_mode", None)
            if not isinstance(port_id, str):
                raise NamedToolBranchExecutionError("branch port id must be text")
            _require_token(port_id, field="branch_port_id")
            if port_id in port_ids:
                raise NamedToolBranchExecutionError("branch port ids must be unique")
            port_ids.add(port_id)
            if tool_id not in BRANCH_TOOL_MODES:
                raise NamedToolBranchExecutionError(
                    "branch port tool is not one of the four branch-backed tools"
                )
            if not isinstance(branch_mode, NamedBranchMode):
                raise NamedToolBranchExecutionError("branch port mode must be typed")
            if BRANCH_TOOL_MODES[tool_id] is not branch_mode:
                raise NamedToolBranchExecutionError(
                    "branch port mode does not match its named tool"
                )
            if tool_id in by_tool:
                raise NamedToolBranchExecutionError(
                    "branch port registry contains a duplicate tool"
                )
            if not callable(getattr(port, "execute", None)):
                raise NamedToolBranchExecutionError(
                    "branch port must expose one execute operation"
                )
            by_tool[tool_id] = port
            inventory.append(
                {
                    "port_id": port_id,
                    "tool_id": tool_id.value,
                    "branch_mode": branch_mode.value,
                }
            )
        if set(by_tool) != set(BRANCH_TOOL_MODES):
            raise NamedToolBranchExecutionError(
                "branch port registry is missing a required tool"
            )
        self._ports = by_tool
        self.registry_digest = _digest_bytes(
            _canonical_json_bytes(
                {
                    "schema_version": "newsroom.increment5.named-branch-port-registry.v1",
                    "ports": sorted(inventory, key=lambda item: item["tool_id"]),
                }
            )
        )

    def get(self, tool_id: NamedToolId) -> NamedBranchPort:
        try:
            return self._ports[tool_id]
        except KeyError as exc:
            raise NamedToolBranchExecutionError(
                "no branch port is registered for the named tool"
            ) from exc


@dataclass(frozen=True, slots=True)
class NamedToolExecutionReceipt:
    execution_id: str
    execution_request_digest: str
    tool_request_digest: str
    tool_envelope_digest: str
    authorization_receipt_digest: str
    authorization_decision_id: str
    port_registry_digest: str
    port_id: str | None
    tool_id: NamedToolId
    branch_mode: NamedBranchMode
    outcome: NamedToolExecutionOutcome
    reason: NamedToolExecutionReason | None
    branch_attribution: BranchReceiptAttribution | None
    result_count: int
    no_match: bool
    response_limit_bytes: int
    branch_executed: bool
    authority_effect: str = "NONE"
    qualification_authority_granted: bool = False
    production_activation_authorized: bool = False

    def __post_init__(self) -> None:
        _require_uuid(self.execution_id, field="named_tool_execution_id")
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
            _require_token(self.port_id, field="named_tool_execution_port_id")
        if self.tool_id not in BRANCH_TOOL_MODES:
            raise NamedToolContractError("execution receipt tool is not branch-backed")
        if not isinstance(self.branch_mode, NamedBranchMode):
            raise NamedToolContractError("execution receipt branch mode must be typed")
        if BRANCH_TOOL_MODES[self.tool_id] is not self.branch_mode:
            raise NamedToolContractError(
                "execution receipt branch mode does not match tool"
            )
        if not isinstance(self.outcome, NamedToolExecutionOutcome):
            raise NamedToolContractError("execution receipt outcome must be typed")
        if self.reason is not None and not isinstance(
            self.reason,
            NamedToolExecutionReason,
        ):
            raise NamedToolContractError("execution receipt reason must be typed")
        if self.branch_attribution is not None:
            if not isinstance(self.branch_attribution, BranchReceiptAttribution):
                raise NamedToolContractError("branch attribution must be typed")
            if self.branch_attribution.tool_id is not self.tool_id:
                raise NamedToolContractError(
                    "execution receipt branch attribution tool mismatch"
                )
            if self.branch_attribution.branch_mode is not self.branch_mode:
                raise NamedToolContractError(
                    "execution receipt branch attribution mode mismatch"
                )
        _require_non_negative_int(self.result_count, field="execution_result_count")
        if self.result_count > NAMED_TOOL_RESULT_LIMIT:
            raise NamedToolContractError("execution result count exceeds global bound")
        if not isinstance(self.no_match, bool):
            raise NamedToolContractError("execution no_match must be boolean")
        if (
            isinstance(self.response_limit_bytes, bool)
            or not isinstance(self.response_limit_bytes, int)
            or not 1_024 <= self.response_limit_bytes <= NAMED_TOOL_RESPONSE_LIMIT_BYTES
        ):
            raise NamedToolContractError("execution response limit is outside bounds")
        if not isinstance(self.branch_executed, bool):
            raise NamedToolContractError("branch_executed must be boolean")
        if self.branch_executed != (self.branch_attribution is not None):
            raise NamedToolContractError(
                "branch execution flag must match retained branch attribution"
            )
        if self.branch_executed and self.port_id is None:
            raise NamedToolContractError(
                "executed branch receipt must retain the exact port identity"
            )
        if self.outcome is NamedToolExecutionOutcome.COMPLETE:
            if self.result_count == 0:
                if not self.no_match or self.reason is not NamedToolExecutionReason.NO_MATCH:
                    raise NamedToolContractError(
                        "complete zero-result tool receipt must state NO_MATCH"
                    )
            elif self.no_match or self.reason is not None:
                raise NamedToolContractError(
                    "complete positive tool receipt cannot state no-match or failure"
                )
        else:
            if self.result_count != 0 or self.no_match or self.reason is None:
                raise NamedToolContractError(
                    "non-complete tool receipt must retain a reason and no results"
                )
        if self.authority_effect != "NONE":
            raise NamedToolContractError("tool execution cannot claim authority effect")
        if self.qualification_authority_granted or self.production_activation_authorized:
            raise NamedToolContractError(
                "tool execution cannot grant qualification or activation authority"
            )
        if len(self.canonical_bytes) > self.response_limit_bytes:
            raise NamedToolContractError(
                "named-tool execution receipt exceeds the response bound"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.increment5.named-tool-execution-receipt.v1",
            "execution_id": self.execution_id,
            "execution_request_digest": self.execution_request_digest,
            "tool_request_digest": self.tool_request_digest,
            "tool_envelope_digest": self.tool_envelope_digest,
            "authorization_receipt_digest": self.authorization_receipt_digest,
            "authorization_decision_id": self.authorization_decision_id,
            "port_registry_digest": self.port_registry_digest,
            "port_id": self.port_id,
            "tool_id": self.tool_id.value,
            "branch_mode": self.branch_mode.value,
            "outcome": self.outcome.value,
            "reason": None if self.reason is None else self.reason.value,
            "branch_attribution": (
                None
                if self.branch_attribution is None
                else self.branch_attribution.canonical_value()
            ),
            "result_count": self.result_count,
            "no_match": self.no_match,
            "response_limit_bytes": self.response_limit_bytes,
            "branch_executed": self.branch_executed,
            "authority_effect": self.authority_effect,
            "qualification_authority_granted": self.qualification_authority_granted,
            "production_activation_authorized": self.production_activation_authorized,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.canonical_value())

    @property
    def receipt_digest(self) -> str:
        return _digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> "NamedToolExecutionReceipt":
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise NamedToolBranchExecutionError(
                "retained named-tool execution receipt is not JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise NamedToolBranchExecutionError(
                "retained named-tool execution receipt root is not an object"
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
            "branch_mode",
            "outcome",
            "reason",
            "branch_attribution",
            "result_count",
            "no_match",
            "response_limit_bytes",
            "branch_executed",
            "authority_effect",
            "qualification_authority_granted",
            "production_activation_authorized",
        }
        if set(payload) != required:
            raise NamedToolBranchExecutionError(
                "retained named-tool execution receipt keys are not exact"
            )
        if payload["schema_version"] != (
            "newsroom.increment5.named-tool-execution-receipt.v1"
        ):
            raise NamedToolBranchExecutionError(
                "retained named-tool execution schema is not accepted"
            )
        raw_attribution = payload["branch_attribution"]
        if raw_attribution is not None and not isinstance(raw_attribution, dict):
            raise NamedToolBranchExecutionError(
                "retained branch attribution must be an object or null"
            )
        try:
            receipt = cls(
                execution_id=payload["execution_id"],
                execution_request_digest=payload["execution_request_digest"],
                tool_request_digest=payload["tool_request_digest"],
                tool_envelope_digest=payload["tool_envelope_digest"],
                authorization_receipt_digest=payload[
                    "authorization_receipt_digest"
                ],
                authorization_decision_id=payload["authorization_decision_id"],
                port_registry_digest=payload["port_registry_digest"],
                port_id=payload["port_id"],
                tool_id=NamedToolId(payload["tool_id"]),
                branch_mode=NamedBranchMode(payload["branch_mode"]),
                outcome=NamedToolExecutionOutcome(payload["outcome"]),
                reason=(
                    None
                    if payload["reason"] is None
                    else NamedToolExecutionReason(payload["reason"])
                ),
                branch_attribution=(
                    None
                    if raw_attribution is None
                    else BranchReceiptAttribution.from_mapping(raw_attribution)
                ),
                result_count=payload["result_count"],
                no_match=payload["no_match"],
                response_limit_bytes=payload["response_limit_bytes"],
                branch_executed=payload["branch_executed"],
                authority_effect=payload["authority_effect"],
                qualification_authority_granted=payload[
                    "qualification_authority_granted"
                ],
                production_activation_authorized=payload[
                    "production_activation_authorized"
                ],
            )
        except (KeyError, TypeError, ValueError, NamedToolContractError) as exc:
            raise NamedToolBranchExecutionError(
                "retained named-tool execution receipt is malformed"
            ) from exc
        if receipt.canonical_bytes != raw:
            raise NamedToolBranchExecutionError(
                "retained named-tool execution receipt bytes are not canonical"
            )
        return receipt


@dataclass(frozen=True, slots=True)
class NamedToolExecutionResult:
    receipt: NamedToolExecutionReceipt
    branch_receipt_bytes: bytes | None

    def __post_init__(self) -> None:
        if not isinstance(self.receipt, NamedToolExecutionReceipt):
            raise NamedToolContractError("tool execution result receipt must be typed")
        attribution = self.receipt.branch_attribution
        if attribution is None:
            if self.branch_receipt_bytes is not None:
                raise NamedToolContractError(
                    "non-executed tool result cannot retain branch receipt bytes"
                )
            return
        if not isinstance(self.branch_receipt_bytes, bytes):
            raise NamedToolContractError(
                "executed tool result must retain exact branch receipt bytes"
            )
        if len(self.branch_receipt_bytes) != attribution.branch_receipt_bytes:
            raise NamedToolContractError(
                "tool result branch receipt byte count mismatch"
            )
        if _digest_bytes(self.branch_receipt_bytes) != attribution.branch_receipt_digest:
            raise NamedToolContractError(
                "tool result branch receipt digest mismatch"
            )


class NamedToolExecutionJournal:
    """Immutable execution journal retaining raw branch bytes outside tool response."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialization_lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._initialization_lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS increment5_named_tool_execution_receipts (
                    idempotency_key TEXT PRIMARY KEY,
                    execution_request_digest TEXT NOT NULL,
                    receipt_bytes BLOB NOT NULL,
                    receipt_digest TEXT NOT NULL,
                    branch_receipt_bytes BLOB,
                    branch_receipt_digest TEXT
                ) WITHOUT ROWID
                """
            )

    @staticmethod
    def _decode(
        execution_request_digest: str,
        receipt_bytes: bytes,
        receipt_digest: str,
        branch_receipt_bytes: bytes | None,
        branch_receipt_digest: str | None,
    ) -> NamedToolExecutionResult:
        if _digest_bytes(receipt_bytes) != receipt_digest:
            raise NamedToolBranchExecutionError(
                "retained tool execution receipt digest mismatch"
            )
        receipt = NamedToolExecutionReceipt.from_canonical_bytes(receipt_bytes)
        if receipt.execution_request_digest != execution_request_digest:
            raise NamedToolBranchExecutionError(
                "retained tool execution semantic binding mismatch"
            )
        attribution = receipt.branch_attribution
        if attribution is None:
            if branch_receipt_bytes is not None or branch_receipt_digest is not None:
                raise NamedToolBranchExecutionError(
                    "retained non-executed tool receipt contains branch bytes"
                )
            return NamedToolExecutionResult(receipt=receipt, branch_receipt_bytes=None)
        if branch_receipt_bytes is None or branch_receipt_digest is None:
            raise NamedToolBranchExecutionError(
                "retained executed tool receipt is missing branch bytes"
            )
        if branch_receipt_digest != attribution.branch_receipt_digest:
            raise NamedToolBranchExecutionError(
                "retained branch digest does not match execution attribution"
            )
        if _digest_bytes(branch_receipt_bytes) != branch_receipt_digest:
            raise NamedToolBranchExecutionError(
                "retained raw branch receipt digest mismatch"
            )
        return NamedToolExecutionResult(
            receipt=receipt,
            branch_receipt_bytes=branch_receipt_bytes,
        )

    def _existing(
        self,
        *,
        idempotency_key: str,
        execution_request_digest: str,
    ) -> NamedToolExecutionResult | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT
                        execution_request_digest,
                        receipt_bytes,
                        receipt_digest,
                        branch_receipt_bytes,
                        branch_receipt_digest
                    FROM increment5_named_tool_execution_receipts
                    WHERE idempotency_key = ?
                    """,
                    (idempotency_key,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise NamedToolBranchExecutionError(
                "named-tool execution journal read failed"
            ) from exc
        if row is None:
            return None
        if row[0] != execution_request_digest:
            raise NamedToolBranchExecutionError(
                "named-tool execution idempotency semantic conflict"
            )
        return self._decode(
            row[0],
            bytes(row[1]),
            row[2],
            None if row[3] is None else bytes(row[3]),
            row[4],
        )

    def execute(
        self,
        *,
        idempotency_key: str,
        execution_request_digest: str,
        producer: Callable[[], NamedToolExecutionResult],
    ) -> NamedToolExecutionResult:
        existing = self._existing(
            idempotency_key=idempotency_key,
            execution_request_digest=execution_request_digest,
        )
        if existing is not None:
            return existing
        result = producer()
        if result.receipt.execution_request_digest != execution_request_digest:
            raise NamedToolBranchExecutionError(
                "produced execution receipt does not bind semantic request"
            )
        receipt_bytes = result.receipt.canonical_bytes
        receipt_digest = _digest_bytes(receipt_bytes)
        branch_bytes = result.branch_receipt_bytes
        branch_digest = (
            None if branch_bytes is None else _digest_bytes(branch_bytes)
        )
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT
                    execution_request_digest,
                    receipt_bytes,
                    receipt_digest,
                    branch_receipt_bytes,
                    branch_receipt_digest
                FROM increment5_named_tool_execution_receipts
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            if row is not None:
                connection.execute("ROLLBACK")
                if row[0] != execution_request_digest:
                    raise NamedToolBranchExecutionError(
                        "named-tool execution concurrent semantic conflict"
                    )
                return self._decode(
                    row[0],
                    bytes(row[1]),
                    row[2],
                    None if row[3] is None else bytes(row[3]),
                    row[4],
                )
            connection.execute(
                """
                INSERT INTO increment5_named_tool_execution_receipts (
                    idempotency_key,
                    execution_request_digest,
                    receipt_bytes,
                    receipt_digest,
                    branch_receipt_bytes,
                    branch_receipt_digest
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    idempotency_key,
                    execution_request_digest,
                    receipt_bytes,
                    receipt_digest,
                    branch_bytes,
                    branch_digest,
                ),
            )
            connection.execute("COMMIT")
        except NamedToolBranchExecutionError:
            raise
        except sqlite3.Error as exc:
            if connection is not None:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            raise NamedToolBranchExecutionError(
                "named-tool execution journal write failed"
            ) from exc
        finally:
            if connection is not None:
                connection.close()
        return result


class NamedToolBranchExecutor:
    """Authorize, dispatch exactly one port, validate attribution and journal."""

    def __init__(
        self,
        *,
        registry: NamedBranchPortRegistry,
        journal: NamedToolExecutionJournal,
    ) -> None:
        self.registry = registry
        self.journal = journal

    def execute(
        self,
        request: NamedToolRequest,
        authorization: NamedToolAuthorizationReceipt,
    ) -> NamedToolExecutionResult:
        tool_id = request.envelope.tool_id
        if tool_id not in BRANCH_TOOL_MODES:
            raise NamedToolBranchExecutionError(
                "named tool is not supported by the branch execution kernel"
            )
        execution_request_digest = _digest_bytes(
            _canonical_json_bytes(
                {
                    "schema_version": "newsroom.increment5.named-tool-execution-request.v1",
                    "tool_request_digest": request.request_digest,
                    "authorization_receipt_digest": authorization.receipt_digest,
                    "port_registry_digest": self.registry.registry_digest,
                }
            )
        )
        return self.journal.execute(
            idempotency_key=request.envelope.idempotency_key,
            execution_request_digest=execution_request_digest,
            producer=lambda: self._produce(
                request,
                authorization,
                execution_request_digest,
            ),
        )

    def _produce(
        self,
        request: NamedToolRequest,
        authorization: NamedToolAuthorizationReceipt,
        execution_request_digest: str,
    ) -> NamedToolExecutionResult:
        binding_reason = self._authorization_binding_reason(request, authorization)
        if binding_reason is not None:
            return self._result(
                request,
                authorization,
                execution_request_digest,
                port_id=None,
                outcome=NamedToolExecutionOutcome.POLICY_BLOCKED,
                reason=binding_reason,
                branch_result=None,
            )
        if authorization.outcome is not NamedToolGateOutcome.AUTHORIZED:
            outcome = (
                NamedToolExecutionOutcome.STALE
                if authorization.outcome is NamedToolGateOutcome.STALE
                else NamedToolExecutionOutcome.POLICY_BLOCKED
            )
            return self._result(
                request,
                authorization,
                execution_request_digest,
                port_id=None,
                outcome=outcome,
                reason=NamedToolExecutionReason.LOCAL_AUTHORIZATION_BLOCKED,
                branch_result=None,
            )
        port = self.registry.get(request.envelope.tool_id)
        try:
            branch_result = port.execute(request)
        except Exception:
            return self._result(
                request,
                authorization,
                execution_request_digest,
                port_id=port.port_id,
                outcome=NamedToolExecutionOutcome.UNAVAILABLE,
                reason=NamedToolExecutionReason.BRANCH_PORT_UNAVAILABLE,
                branch_result=None,
            )
        try:
            self._validate_branch_result(request, port, branch_result)
        except (NamedToolContractError, NamedToolBranchExecutionError):
            return self._result(
                request,
                authorization,
                execution_request_digest,
                port_id=port.port_id,
                outcome=NamedToolExecutionOutcome.UNAVAILABLE,
                reason=NamedToolExecutionReason.BRANCH_RECEIPT_INVALID,
                branch_result=None,
            )
        attribution = branch_result.attribution
        if attribution.result_count > request.envelope.result_limit:
            return self._result(
                request,
                authorization,
                execution_request_digest,
                port_id=port.port_id,
                outcome=NamedToolExecutionOutcome.INCOMPLETE,
                reason=NamedToolExecutionReason.RESULT_LIMIT_EXCEEDED,
                branch_result=branch_result,
                force_zero_results=True,
            )
        if attribution.branch_receipt_bytes > request.envelope.response_limit_bytes:
            return self._result(
                request,
                authorization,
                execution_request_digest,
                port_id=port.port_id,
                outcome=NamedToolExecutionOutcome.INCOMPLETE,
                reason=NamedToolExecutionReason.RESPONSE_LIMIT_EXCEEDED,
                branch_result=branch_result,
                force_zero_results=True,
            )
        outcome = NamedToolExecutionOutcome(attribution.outcome.value)
        if outcome is NamedToolExecutionOutcome.COMPLETE:
            reason = (
                NamedToolExecutionReason.NO_MATCH
                if attribution.no_match
                else None
            )
        else:
            reason = NamedToolExecutionReason.BRANCH_NON_COMPLETE
        return self._result(
            request,
            authorization,
            execution_request_digest,
            port_id=port.port_id,
            outcome=outcome,
            reason=reason,
            branch_result=branch_result,
        )

    @staticmethod
    def _authorization_binding_reason(
        request: NamedToolRequest,
        authorization: NamedToolAuthorizationReceipt,
    ) -> NamedToolExecutionReason | None:
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
            return NamedToolExecutionReason.AUTHORIZATION_BINDING_MISMATCH
        if (
            authorization.outcome is NamedToolGateOutcome.AUTHORIZED
            and not authorization.local_tool_call_authorized
        ):
            return NamedToolExecutionReason.AUTHORIZATION_BINDING_MISMATCH
        if (
            authorization.outcome is not NamedToolGateOutcome.AUTHORIZED
            and authorization.local_tool_call_authorized
        ):
            return NamedToolExecutionReason.AUTHORIZATION_BINDING_MISMATCH
        return None

    @staticmethod
    def _validate_branch_result(
        request: NamedToolRequest,
        port: NamedBranchPort,
        result: AttributedBranchResult,
    ) -> None:
        if not isinstance(result, AttributedBranchResult):
            raise NamedToolBranchExecutionError(
                "branch port did not return an attributed branch result"
            )
        attribution = result.attribution
        envelope = request.envelope
        if attribution.tool_request_digest != request.request_digest:
            raise NamedToolBranchExecutionError(
                "branch attribution does not bind the named-tool request"
            )
        if attribution.tool_id is not envelope.tool_id:
            raise NamedToolBranchExecutionError(
                "branch attribution tool does not match request"
            )
        if attribution.branch_mode is not port.branch_mode:
            raise NamedToolBranchExecutionError(
                "branch attribution mode does not match registered port"
            )
        if port.tool_id is not envelope.tool_id:
            raise NamedToolBranchExecutionError(
                "registered port tool does not match request"
            )
        if (
            attribution.branch_generation_id is not None
            and attribution.branch_generation_id != envelope.generation_id
        ):
            raise NamedToolBranchExecutionError(
                "branch generation does not match named-tool envelope"
            )
        if attribution.query_valid_time != envelope.query_valid_time:
            raise NamedToolBranchExecutionError(
                "branch query-valid time does not match named-tool request"
            )
        if attribution.serving_time != envelope.serving_time:
            raise NamedToolBranchExecutionError(
                "branch serving time does not match named-tool request"
            )

    def _result(
        self,
        request: NamedToolRequest,
        authorization: NamedToolAuthorizationReceipt,
        execution_request_digest: str,
        *,
        port_id: str | None,
        outcome: NamedToolExecutionOutcome,
        reason: NamedToolExecutionReason | None,
        branch_result: AttributedBranchResult | None,
        force_zero_results: bool = False,
    ) -> NamedToolExecutionResult:
        attribution = None if branch_result is None else branch_result.attribution
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
                        "NO_BRANCH"
                        if attribution is None
                        else attribution.branch_receipt_digest,
                    )
                ),
            )
        )
        receipt = NamedToolExecutionReceipt(
            execution_id=execution_id,
            execution_request_digest=execution_request_digest,
            tool_request_digest=request.request_digest,
            tool_envelope_digest=request.envelope.envelope_digest,
            authorization_receipt_digest=authorization.receipt_digest,
            authorization_decision_id=authorization.decision_id,
            port_registry_digest=self.registry.registry_digest,
            port_id=port_id,
            tool_id=request.envelope.tool_id,
            branch_mode=BRANCH_TOOL_MODES[request.envelope.tool_id],
            outcome=outcome,
            reason=reason,
            branch_attribution=attribution,
            result_count=result_count,
            no_match=no_match,
            response_limit_bytes=request.envelope.response_limit_bytes,
            branch_executed=attribution is not None,
        )
        return NamedToolExecutionResult(
            receipt=receipt,
            branch_receipt_bytes=(
                None
                if branch_result is None
                else branch_result.branch_receipt_bytes
            ),
        )


__all__ = [
    "BRANCH_TOOL_MODES",
    "AttributedBranchResult",
    "BranchComponentIdentity",
    "BranchReceiptAttribution",
    "NamedBranchMode",
    "NamedBranchOutcome",
    "NamedBranchPort",
    "NamedBranchPortRegistry",
    "NamedToolBranchExecutionError",
    "NamedToolBranchExecutor",
    "NamedToolExecutionJournal",
    "NamedToolExecutionOutcome",
    "NamedToolExecutionReason",
    "NamedToolExecutionReceipt",
    "NamedToolExecutionResult",
]
