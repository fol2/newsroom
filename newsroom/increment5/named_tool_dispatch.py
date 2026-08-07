"""Closed dispatcher for all six Increment 5C named read-only tools.

The dispatcher selects exactly one already reviewed execution kernel from the
request's typed tool identity.  It does not inspect request content to choose a
backend, does not execute raw queries, and does not perform fusion, hydration,
Candidate mutation, provider work, publication or activation.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable, Mapping, TypeAlias

from .named_tool_authority_execution import (
    AUTHORITY_TOOL_MODES,
    NamedAuthorityExecutionReceipt,
    NamedAuthorityExecutionResult,
    NamedAuthorityPortRegistry,
    NamedToolAuthorityExecutor,
)
from .named_tool_authorization import NamedToolAuthorizationReceipt
from .named_tool_branch_execution import (
    BRANCH_TOOL_MODES,
    NamedBranchPortRegistry,
    NamedToolBranchExecutor,
    NamedToolExecutionReceipt,
    NamedToolExecutionResult,
)
from .named_tool_contracts import (
    NAMED_TOOL_RESPONSE_LIMIT_BYTES,
    AdmittedGraphTraversalToolRequest,
    CollisionHydrationLookupToolRequest,
    ExactAuthorityLookupToolRequest,
    FixedPointVectorRetrievalToolRequest,
    FullTextRetrievalToolRequest,
    NamedToolContractError,
    NamedToolId,
    NamedToolRequest,
    SourceRevisionImpactLookupToolRequest,
)


_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}\Z")
_NAME_RE = re.compile(r"[A-Z][A-Z0-9_]{0,127}\Z")
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


class NamedToolDispatchError(RuntimeError):
    """The closed route, upstream receipt or immutable dispatch journal failed."""


class NamedToolExecutionRoute(StrEnum):
    BRANCH = "BRANCH"
    AUTHORITY = "AUTHORITY"


class NamedToolDispatchOutcome(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class NamedToolDispatchReason(StrEnum):
    NO_MATCH = "NO_MATCH"
    LOCAL_AUTHORIZATION_BLOCKED = "LOCAL_AUTHORIZATION_BLOCKED"
    AUTHORIZATION_BINDING_MISMATCH = "AUTHORIZATION_BINDING_MISMATCH"
    ADAPTER_POLICY_BLOCKED = "ADAPTER_POLICY_BLOCKED"
    PORT_UNAVAILABLE = "PORT_UNAVAILABLE"
    RECEIPT_INVALID = "RECEIPT_INVALID"
    GENERATION_MISMATCH = "GENERATION_MISMATCH"
    UPSTREAM_NON_COMPLETE = "UPSTREAM_NON_COMPLETE"
    RESULT_LIMIT_EXCEEDED = "RESULT_LIMIT_EXCEEDED"
    RESPONSE_LIMIT_EXCEEDED = "RESPONSE_LIMIT_EXCEEDED"


NAMED_TOOL_ROUTES: Mapping[NamedToolId, NamedToolExecutionRoute] = {
    **{tool_id: NamedToolExecutionRoute.BRANCH for tool_id in BRANCH_TOOL_MODES},
    **{
        tool_id: NamedToolExecutionRoute.AUTHORITY
        for tool_id in AUTHORITY_TOOL_MODES
    },
}

_REQUEST_TYPES: Mapping[NamedToolId, type[object]] = {
    NamedToolId.EXACT_AUTHORITY_LOOKUP: ExactAuthorityLookupToolRequest,
    NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL: FullTextRetrievalToolRequest,
    NamedToolId.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL: (
        FixedPointVectorRetrievalToolRequest
    ),
    NamedToolId.BOUNDED_ADMITTED_GRAPH_TRAVERSAL: (
        AdmittedGraphTraversalToolRequest
    ),
    NamedToolId.CURRENT_COLLISION_AND_AUTHORITY_HYDRATION_LOOKUP: (
        CollisionHydrationLookupToolRequest
    ),
    NamedToolId.BOUNDED_SOURCE_REVISION_IMPACT_LOOKUP: (
        SourceRevisionImpactLookupToolRequest
    ),
}

if set(BRANCH_TOOL_MODES) & set(AUTHORITY_TOOL_MODES):
    raise RuntimeError("named-tool execution route inventories overlap")
if set(NAMED_TOOL_ROUTES) != set(NamedToolId):
    raise RuntimeError("named-tool execution route inventory is incomplete")
if set(_REQUEST_TYPES) != set(NamedToolId):
    raise RuntimeError("named-tool request type inventory is incomplete")


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise NamedToolContractError("dispatch value is not canonical JSON") from exc


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise NamedToolDispatchError(
                "retained dispatch JSON contains duplicate keys"
            )
        result[key] = value
    return result


def _require_token(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _TOKEN_RE.fullmatch(value) is None:
        raise NamedToolContractError(f"{field} must be a bounded canonical token")
    return value


def _require_name(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _NAME_RE.fullmatch(value) is None:
        raise NamedToolContractError(f"{field} must be a bounded canonical name")
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


def _component_value(name: str, digest: str) -> dict[str, str]:
    return {"name": name, "digest": digest}


NAMED_TOOL_DISPATCH_CONTRACT_DIGEST = _digest(
    _canonical(
        {
            "schema_version": "newsroom.increment5.named-tool-dispatch-contract.v1",
            "routes": {
                tool_id.value: route.value
                for tool_id, route in sorted(
                    NAMED_TOOL_ROUTES.items(), key=lambda item: item[0].value
                )
            },
            "outcomes": [item.value for item in NamedToolDispatchOutcome],
            "reasons": [item.value for item in NamedToolDispatchReason],
            "external_call_limit": 0,
            "authority_effect": "NONE",
        }
    )
)


@dataclass(frozen=True, slots=True)
class NamedToolComponentIdentity:
    name: str
    digest: str

    def __post_init__(self) -> None:
        _require_token(self.name, field="dispatch_component_name")
        _require_digest(self.digest, field="dispatch_component_digest")

    def canonical_value(self) -> dict[str, str]:
        return _component_value(self.name, self.digest)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "NamedToolComponentIdentity":
        if set(value) != {"name", "digest"}:
            raise NamedToolContractError("dispatch component keys are not exact")
        if not isinstance(value["name"], str) or not isinstance(value["digest"], str):
            raise NamedToolContractError("dispatch component fields must be text")
        return cls(name=value["name"], digest=value["digest"])


@dataclass(frozen=True, slots=True)
class NamedToolUpstreamIdentity:
    route: NamedToolExecutionRoute
    execution_receipt_digest: str
    execution_request_digest: str
    registry_digest: str
    port_id: str | None
    mode: str
    outcome: NamedToolDispatchOutcome
    reason: str | None
    attribution_digest: str | None
    upstream_request_digest: str | None
    upstream_receipt_digest: str | None
    profile_id: str | None
    generation_id: str | None
    generation_digest: str | None
    component_identities: tuple[NamedToolComponentIdentity, ...]
    authority_watermark: int | None
    raw_receipt_bytes: int
    raw_receipt_digest: str | None
    independently_attributable: bool

    def __post_init__(self) -> None:
        if not isinstance(self.route, NamedToolExecutionRoute):
            raise NamedToolContractError("upstream route must be typed")
        for name in (
            "execution_receipt_digest",
            "execution_request_digest",
            "registry_digest",
        ):
            _require_digest(getattr(self, name), field=f"upstream_{name}")
        if self.port_id is not None:
            _require_token(self.port_id, field="upstream_port_id")
        _require_name(self.mode, field="upstream_mode")
        if not isinstance(self.outcome, NamedToolDispatchOutcome):
            raise NamedToolContractError("upstream outcome must be typed")
        if self.reason is not None:
            _require_name(self.reason, field="upstream_reason")
        for name in (
            "attribution_digest",
            "upstream_request_digest",
            "upstream_receipt_digest",
            "generation_digest",
            "raw_receipt_digest",
        ):
            value = getattr(self, name)
            if value is not None:
                _require_digest(value, field=name)
        for name in ("profile_id", "generation_id"):
            value = getattr(self, name)
            if value is not None:
                _require_token(value, field=f"upstream_{name}")
        if not all(
            isinstance(item, NamedToolComponentIdentity)
            for item in self.component_identities
        ):
            raise NamedToolContractError("upstream components must be typed")
        names = tuple(item.name for item in self.component_identities)
        if names != tuple(sorted(set(names))):
            raise NamedToolContractError(
                "upstream component identities must be sorted and unique"
            )
        if len(self.component_identities) > 16:
            raise NamedToolContractError(
                "upstream may retain at most 16 component identities"
            )
        if self.authority_watermark is not None:
            _require_non_negative_int(
                self.authority_watermark,
                field="upstream_authority_watermark",
            )
        _require_non_negative_int(
            self.raw_receipt_bytes,
            field="upstream_raw_receipt_bytes",
        )
        if self.raw_receipt_bytes > NAMED_TOOL_RESPONSE_LIMIT_BYTES:
            raise NamedToolContractError(
                "upstream raw receipt exceeds the global bound"
            )
        if type(self.independently_attributable) is not bool:
            raise NamedToolContractError(
                "upstream independently-attributable flag must be boolean"
            )
        attributed = self.attribution_digest is not None
        if attributed != self.independently_attributable:
            raise NamedToolContractError(
                "upstream attribution flag must match retained attribution"
            )
        attributed_fields = (
            self.upstream_request_digest,
            self.upstream_receipt_digest,
            self.profile_id,
            self.raw_receipt_digest,
        )
        if attributed:
            if any(value is None for value in attributed_fields):
                raise NamedToolContractError(
                    "attributed upstream identity is missing required identities"
                )
            if not self.component_identities:
                raise NamedToolContractError(
                    "attributed upstream identity must retain components"
                )
            if self.raw_receipt_bytes <= 0:
                raise NamedToolContractError(
                    "attributed upstream identity must retain raw receipt bytes"
                )
            if self.raw_receipt_digest != self.upstream_receipt_digest:
                raise NamedToolContractError(
                    "upstream raw receipt digest must match attribution receipt"
                )
        else:
            if any(value is not None for value in attributed_fields):
                raise NamedToolContractError(
                    "non-attributed upstream identity cannot retain attribution fields"
                )
            if self.component_identities or self.raw_receipt_bytes != 0:
                raise NamedToolContractError(
                    "non-attributed upstream identity cannot retain components or bytes"
                )
            if self.generation_id is not None or self.generation_digest is not None:
                raise NamedToolContractError(
                    "non-attributed upstream identity cannot retain generation"
                )
            if self.authority_watermark is not None:
                raise NamedToolContractError(
                    "non-attributed upstream identity cannot retain a watermark"
                )
        if (self.generation_id is None) != (self.generation_digest is None):
            raise NamedToolContractError(
                "upstream generation id and digest must be present together"
            )
        if self.route is NamedToolExecutionRoute.BRANCH:
            if self.authority_watermark is not None:
                raise NamedToolContractError(
                    "branch upstream identity cannot claim an authority watermark"
                )
        elif self.generation_id is not None or self.generation_digest is not None:
            raise NamedToolContractError(
                "authority upstream identity cannot claim branch generation"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "route": self.route.value,
            "execution_receipt_digest": self.execution_receipt_digest,
            "execution_request_digest": self.execution_request_digest,
            "registry_digest": self.registry_digest,
            "port_id": self.port_id,
            "mode": self.mode,
            "outcome": self.outcome.value,
            "reason": self.reason,
            "attribution_digest": self.attribution_digest,
            "upstream_request_digest": self.upstream_request_digest,
            "upstream_receipt_digest": self.upstream_receipt_digest,
            "profile_id": self.profile_id,
            "generation_id": self.generation_id,
            "generation_digest": self.generation_digest,
            "component_identities": [
                item.canonical_value() for item in self.component_identities
            ],
            "authority_watermark": self.authority_watermark,
            "raw_receipt_bytes": self.raw_receipt_bytes,
            "raw_receipt_digest": self.raw_receipt_digest,
            "independently_attributable": self.independently_attributable,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "NamedToolUpstreamIdentity":
        required = {
            "route",
            "execution_receipt_digest",
            "execution_request_digest",
            "registry_digest",
            "port_id",
            "mode",
            "outcome",
            "reason",
            "attribution_digest",
            "upstream_request_digest",
            "upstream_receipt_digest",
            "profile_id",
            "generation_id",
            "generation_digest",
            "component_identities",
            "authority_watermark",
            "raw_receipt_bytes",
            "raw_receipt_digest",
            "independently_attributable",
        }
        if set(value) != required:
            raise NamedToolContractError("upstream identity keys are not exact")
        raw_components = value["component_identities"]
        if not isinstance(raw_components, list) or not all(
            isinstance(item, dict) for item in raw_components
        ):
            raise NamedToolContractError("upstream component identities are malformed")
        text_fields = (
            "execution_receipt_digest",
            "execution_request_digest",
            "registry_digest",
            "mode",
        )
        if not all(isinstance(value[name], str) for name in text_fields):
            raise NamedToolContractError("upstream identity text field is malformed")
        optional_text = (
            "port_id",
            "reason",
            "attribution_digest",
            "upstream_request_digest",
            "upstream_receipt_digest",
            "profile_id",
            "generation_id",
            "generation_digest",
            "raw_receipt_digest",
        )
        if not all(
            value[name] is None or isinstance(value[name], str)
            for name in optional_text
        ):
            raise NamedToolContractError("upstream optional text field is malformed")
        try:
            route = NamedToolExecutionRoute(value["route"])
            outcome = NamedToolDispatchOutcome(value["outcome"])
        except (TypeError, ValueError) as exc:
            raise NamedToolContractError("upstream enum is not accepted") from exc
        return cls(
            route=route,
            execution_receipt_digest=value["execution_receipt_digest"],
            execution_request_digest=value["execution_request_digest"],
            registry_digest=value["registry_digest"],
            port_id=value["port_id"],
            mode=value["mode"],
            outcome=outcome,
            reason=value["reason"],
            attribution_digest=value["attribution_digest"],
            upstream_request_digest=value["upstream_request_digest"],
            upstream_receipt_digest=value["upstream_receipt_digest"],
            profile_id=value["profile_id"],
            generation_id=value["generation_id"],
            generation_digest=value["generation_digest"],
            component_identities=tuple(
                NamedToolComponentIdentity.from_mapping(item)
                for item in raw_components
            ),
            authority_watermark=value["authority_watermark"],
            raw_receipt_bytes=value["raw_receipt_bytes"],
            raw_receipt_digest=value["raw_receipt_digest"],
            independently_attributable=value["independently_attributable"],
        )


def _normalized_reason(
    route: NamedToolExecutionRoute,
    upstream_reason: str | None,
    outcome: NamedToolDispatchOutcome,
    no_match: bool,
) -> NamedToolDispatchReason | None:
    if outcome is NamedToolDispatchOutcome.COMPLETE:
        if no_match and upstream_reason == "NO_MATCH":
            return NamedToolDispatchReason.NO_MATCH
        if not no_match and upstream_reason is None:
            return None
        raise NamedToolContractError("complete upstream reason is inconsistent")
    if upstream_reason is None:
        raise NamedToolContractError("non-complete upstream execution lacks a reason")
    common = {
        "LOCAL_AUTHORIZATION_BLOCKED": (
            NamedToolDispatchReason.LOCAL_AUTHORIZATION_BLOCKED
        ),
        "AUTHORIZATION_BINDING_MISMATCH": (
            NamedToolDispatchReason.AUTHORIZATION_BINDING_MISMATCH
        ),
        "ADAPTER_POLICY_BLOCKED": NamedToolDispatchReason.ADAPTER_POLICY_BLOCKED,
        "RESULT_LIMIT_EXCEEDED": NamedToolDispatchReason.RESULT_LIMIT_EXCEEDED,
        "RESPONSE_LIMIT_EXCEEDED": NamedToolDispatchReason.RESPONSE_LIMIT_EXCEEDED,
    }
    if upstream_reason in common:
        return common[upstream_reason]
    if route is NamedToolExecutionRoute.BRANCH:
        branch = {
            "BRANCH_PORT_UNAVAILABLE": NamedToolDispatchReason.PORT_UNAVAILABLE,
            "BRANCH_RECEIPT_INVALID": NamedToolDispatchReason.RECEIPT_INVALID,
            "BRANCH_GENERATION_MISMATCH": (
                NamedToolDispatchReason.GENERATION_MISMATCH
            ),
            "BRANCH_NON_COMPLETE": NamedToolDispatchReason.UPSTREAM_NON_COMPLETE,
        }
        try:
            return branch[upstream_reason]
        except KeyError as exc:
            raise NamedToolContractError(
                "branch execution reason is not accepted by dispatcher"
            ) from exc
    authority = {
        "AUTHORITY_PORT_UNAVAILABLE": NamedToolDispatchReason.PORT_UNAVAILABLE,
        "AUTHORITY_RECEIPT_INVALID": NamedToolDispatchReason.RECEIPT_INVALID,
        "AUTHORITY_NON_COMPLETE": NamedToolDispatchReason.UPSTREAM_NON_COMPLETE,
    }
    try:
        return authority[upstream_reason]
    except KeyError as exc:
        raise NamedToolContractError(
            "authority execution reason is not accepted by dispatcher"
        ) from exc


@dataclass(frozen=True, slots=True)
class NamedToolDispatchReceipt:
    dispatch_id: str
    dispatch_request_digest: str
    tool_request_digest: str
    tool_envelope_digest: str
    authorization_receipt_digest: str
    authorization_decision_id: str
    dispatch_contract_digest: str
    dispatcher_registry_digest: str
    tool_id: NamedToolId
    route: NamedToolExecutionRoute
    outcome: NamedToolDispatchOutcome
    reason: NamedToolDispatchReason | None
    upstream: NamedToolUpstreamIdentity
    result_count: int
    no_match: bool
    response_limit_bytes: int
    branch_executed: bool
    authority_read_executed: bool
    external_call_count: int = 0
    provider_call_count: int = 0
    model_call_count: int = 0
    embedding_call_count: int = 0
    provider_spend_micros: int = 0
    authority_effect: str = "NONE"
    qualification_authority_granted: bool = False
    production_activation_authorized: bool = False

    def __post_init__(self) -> None:
        _require_uuid(self.dispatch_id, field="named_tool_dispatch_id")
        for name in (
            "dispatch_request_digest",
            "tool_request_digest",
            "tool_envelope_digest",
            "authorization_receipt_digest",
            "dispatch_contract_digest",
            "dispatcher_registry_digest",
        ):
            _require_digest(getattr(self, name), field=name)
        _require_uuid(
            self.authorization_decision_id,
            field="dispatch_authorization_decision_id",
        )
        if self.dispatch_contract_digest != NAMED_TOOL_DISPATCH_CONTRACT_DIGEST:
            raise NamedToolContractError("dispatch contract digest is not accepted")
        if not isinstance(self.tool_id, NamedToolId):
            raise NamedToolContractError("dispatch tool id must be typed")
        if not isinstance(self.route, NamedToolExecutionRoute):
            raise NamedToolContractError("dispatch route must be typed")
        if NAMED_TOOL_ROUTES[self.tool_id] is not self.route:
            raise NamedToolContractError("dispatch route does not match tool")
        if not isinstance(self.outcome, NamedToolDispatchOutcome):
            raise NamedToolContractError("dispatch outcome must be typed")
        if self.reason is not None and not isinstance(
            self.reason, NamedToolDispatchReason
        ):
            raise NamedToolContractError("dispatch reason must be typed")
        if not isinstance(self.upstream, NamedToolUpstreamIdentity):
            raise NamedToolContractError("dispatch upstream identity must be typed")
        if self.upstream.route is not self.route:
            raise NamedToolContractError("dispatch upstream route mismatch")
        if self.upstream.outcome is not self.outcome:
            raise NamedToolContractError("dispatch upstream outcome mismatch")
        _require_non_negative_int(self.result_count, field="dispatch_result_count")
        if type(self.no_match) is not bool:
            raise NamedToolContractError("dispatch no_match must be boolean")
        if (
            isinstance(self.response_limit_bytes, bool)
            or not isinstance(self.response_limit_bytes, int)
            or not 1_024 <= self.response_limit_bytes <= NAMED_TOOL_RESPONSE_LIMIT_BYTES
        ):
            raise NamedToolContractError("dispatch response limit is outside bounds")
        for name in ("branch_executed", "authority_read_executed"):
            if type(getattr(self, name)) is not bool:
                raise NamedToolContractError(f"{name} must be boolean")
        attributed = self.upstream.independently_attributable
        if self.branch_executed != (
            attributed and self.route is NamedToolExecutionRoute.BRANCH
        ):
            raise NamedToolContractError(
                "branch execution flag does not match upstream attribution"
            )
        if self.authority_read_executed != (
            attributed and self.route is NamedToolExecutionRoute.AUTHORITY
        ):
            raise NamedToolContractError(
                "authority-read flag does not match upstream attribution"
            )
        expected_reason = _normalized_reason(
            self.route,
            self.upstream.reason,
            self.outcome,
            self.no_match,
        )
        if self.reason is not expected_reason:
            raise NamedToolContractError("dispatch reason does not match upstream")
        if self.outcome is NamedToolDispatchOutcome.COMPLETE:
            if self.result_count == 0:
                if (
                    not self.no_match
                    or self.reason is not NamedToolDispatchReason.NO_MATCH
                ):
                    raise NamedToolContractError(
                        "complete zero-result dispatch must state NO_MATCH"
                    )
            elif self.no_match or self.reason is not None:
                raise NamedToolContractError(
                    "complete positive dispatch cannot state failure or no-match"
                )
        elif self.result_count != 0 or self.no_match or self.reason is None:
            raise NamedToolContractError(
                "non-complete dispatch must retain a reason and no results"
            )
        for name in (
            "external_call_count",
            "provider_call_count",
            "model_call_count",
            "embedding_call_count",
            "provider_spend_micros",
        ):
            _require_non_negative_int(getattr(self, name), field=name)
            if getattr(self, name) != 0:
                raise NamedToolContractError(
                    "Increment 5 dispatch cannot report external work or spend"
                )
        if self.authority_effect != "NONE":
            raise NamedToolContractError("dispatch cannot claim an authority effect")
        for name in (
            "qualification_authority_granted",
            "production_activation_authorized",
        ):
            if type(getattr(self, name)) is not bool:
                raise NamedToolContractError(f"{name} must be boolean")
            if getattr(self, name):
                raise NamedToolContractError(
                    "dispatch cannot grant qualification or activation authority"
                )

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.increment5.named-tool-dispatch-receipt.v1",
            "dispatch_id": self.dispatch_id,
            "dispatch_request_digest": self.dispatch_request_digest,
            "tool_request_digest": self.tool_request_digest,
            "tool_envelope_digest": self.tool_envelope_digest,
            "authorization_receipt_digest": self.authorization_receipt_digest,
            "authorization_decision_id": self.authorization_decision_id,
            "dispatch_contract_digest": self.dispatch_contract_digest,
            "dispatcher_registry_digest": self.dispatcher_registry_digest,
            "tool_id": self.tool_id.value,
            "route": self.route.value,
            "outcome": self.outcome.value,
            "reason": None if self.reason is None else self.reason.value,
            "upstream": self.upstream.canonical_value(),
            "result_count": self.result_count,
            "no_match": self.no_match,
            "response_limit_bytes": self.response_limit_bytes,
            "branch_executed": self.branch_executed,
            "authority_read_executed": self.authority_read_executed,
            "external_call_count": self.external_call_count,
            "provider_call_count": self.provider_call_count,
            "model_call_count": self.model_call_count,
            "embedding_call_count": self.embedding_call_count,
            "provider_spend_micros": self.provider_spend_micros,
            "authority_effect": self.authority_effect,
            "qualification_authority_granted": self.qualification_authority_granted,
            "production_activation_authorized": self.production_activation_authorized,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical(self.canonical_value())

    @property
    def receipt_digest(self) -> str:
        return _digest(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> "NamedToolDispatchReceipt":
        try:
            value = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_unique_object,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise NamedToolDispatchError(
                "retained dispatch receipt is not JSON"
            ) from exc
        if not isinstance(value, dict):
            raise NamedToolDispatchError(
                "retained dispatch receipt root is not an object"
            )
        required = {
            "schema_version",
            "dispatch_id",
            "dispatch_request_digest",
            "tool_request_digest",
            "tool_envelope_digest",
            "authorization_receipt_digest",
            "authorization_decision_id",
            "dispatch_contract_digest",
            "dispatcher_registry_digest",
            "tool_id",
            "route",
            "outcome",
            "reason",
            "upstream",
            "result_count",
            "no_match",
            "response_limit_bytes",
            "branch_executed",
            "authority_read_executed",
            "external_call_count",
            "provider_call_count",
            "model_call_count",
            "embedding_call_count",
            "provider_spend_micros",
            "authority_effect",
            "qualification_authority_granted",
            "production_activation_authorized",
        }
        if set(value) != required:
            raise NamedToolDispatchError("retained dispatch receipt keys are not exact")
        if value["schema_version"] != (
            "newsroom.increment5.named-tool-dispatch-receipt.v1"
        ):
            raise NamedToolDispatchError(
                "retained dispatch receipt schema is not accepted"
            )
        if not isinstance(value["upstream"], dict):
            raise NamedToolDispatchError("retained upstream identity is not an object")
        text_fields = (
            "dispatch_id",
            "dispatch_request_digest",
            "tool_request_digest",
            "tool_envelope_digest",
            "authorization_receipt_digest",
            "authorization_decision_id",
            "dispatch_contract_digest",
            "dispatcher_registry_digest",
            "authority_effect",
        )
        if not all(isinstance(value[name], str) for name in text_fields):
            raise NamedToolDispatchError("retained dispatch text field is malformed")
        if value["reason"] is not None and not isinstance(value["reason"], str):
            raise NamedToolDispatchError("retained dispatch reason is malformed")
        try:
            receipt = cls(
                dispatch_id=value["dispatch_id"],
                dispatch_request_digest=value["dispatch_request_digest"],
                tool_request_digest=value["tool_request_digest"],
                tool_envelope_digest=value["tool_envelope_digest"],
                authorization_receipt_digest=value[
                    "authorization_receipt_digest"
                ],
                authorization_decision_id=value["authorization_decision_id"],
                dispatch_contract_digest=value["dispatch_contract_digest"],
                dispatcher_registry_digest=value["dispatcher_registry_digest"],
                tool_id=NamedToolId(value["tool_id"]),
                route=NamedToolExecutionRoute(value["route"]),
                outcome=NamedToolDispatchOutcome(value["outcome"]),
                reason=(
                    None
                    if value["reason"] is None
                    else NamedToolDispatchReason(value["reason"])
                ),
                upstream=NamedToolUpstreamIdentity.from_mapping(value["upstream"]),
                result_count=value["result_count"],
                no_match=value["no_match"],
                response_limit_bytes=value["response_limit_bytes"],
                branch_executed=value["branch_executed"],
                authority_read_executed=value["authority_read_executed"],
                external_call_count=value["external_call_count"],
                provider_call_count=value["provider_call_count"],
                model_call_count=value["model_call_count"],
                embedding_call_count=value["embedding_call_count"],
                provider_spend_micros=value["provider_spend_micros"],
                authority_effect=value["authority_effect"],
                qualification_authority_granted=value[
                    "qualification_authority_granted"
                ],
                production_activation_authorized=value[
                    "production_activation_authorized"
                ],
            )
        except (KeyError, TypeError, ValueError, NamedToolContractError) as exc:
            raise NamedToolDispatchError(
                "retained dispatch receipt is malformed"
            ) from exc
        if receipt.canonical_bytes != raw:
            raise NamedToolDispatchError(
                "retained dispatch receipt bytes are not canonical"
            )
        return receipt


UpstreamExecutionResult: TypeAlias = (
    NamedToolExecutionResult | NamedAuthorityExecutionResult
)


def _branch_upstream(result: NamedToolExecutionResult) -> NamedToolUpstreamIdentity:
    receipt = result.receipt
    attribution = receipt.branch_attribution
    if attribution is None:
        return NamedToolUpstreamIdentity(
            route=NamedToolExecutionRoute.BRANCH,
            execution_receipt_digest=receipt.receipt_digest,
            execution_request_digest=receipt.execution_request_digest,
            registry_digest=receipt.port_registry_digest,
            port_id=receipt.port_id,
            mode=receipt.branch_mode.value,
            outcome=NamedToolDispatchOutcome(receipt.outcome.value),
            reason=None if receipt.reason is None else receipt.reason.value,
            attribution_digest=None,
            upstream_request_digest=None,
            upstream_receipt_digest=None,
            profile_id=None,
            generation_id=None,
            generation_digest=None,
            component_identities=(),
            authority_watermark=None,
            raw_receipt_bytes=0,
            raw_receipt_digest=None,
            independently_attributable=False,
        )
    return NamedToolUpstreamIdentity(
        route=NamedToolExecutionRoute.BRANCH,
        execution_receipt_digest=receipt.receipt_digest,
        execution_request_digest=receipt.execution_request_digest,
        registry_digest=receipt.port_registry_digest,
        port_id=receipt.port_id,
        mode=receipt.branch_mode.value,
        outcome=NamedToolDispatchOutcome(receipt.outcome.value),
        reason=None if receipt.reason is None else receipt.reason.value,
        attribution_digest=_digest(_canonical(attribution.canonical_value())),
        upstream_request_digest=attribution.branch_request_digest,
        upstream_receipt_digest=attribution.branch_receipt_digest,
        profile_id=attribution.branch_profile_id,
        generation_id=attribution.branch_generation_id,
        generation_digest=attribution.branch_generation_digest,
        component_identities=tuple(
            NamedToolComponentIdentity(item.name, item.digest)
            for item in attribution.component_identities
        ),
        authority_watermark=None,
        raw_receipt_bytes=attribution.branch_receipt_bytes,
        raw_receipt_digest=attribution.branch_receipt_digest,
        independently_attributable=attribution.independently_attributable,
    )


def _authority_upstream(
    result: NamedAuthorityExecutionResult,
) -> NamedToolUpstreamIdentity:
    receipt = result.receipt
    attribution = receipt.authority_attribution
    if attribution is None:
        return NamedToolUpstreamIdentity(
            route=NamedToolExecutionRoute.AUTHORITY,
            execution_receipt_digest=receipt.receipt_digest,
            execution_request_digest=receipt.execution_request_digest,
            registry_digest=receipt.port_registry_digest,
            port_id=receipt.port_id,
            mode=receipt.authority_mode.value,
            outcome=NamedToolDispatchOutcome(receipt.outcome.value),
            reason=None if receipt.reason is None else receipt.reason.value,
            attribution_digest=None,
            upstream_request_digest=None,
            upstream_receipt_digest=None,
            profile_id=None,
            generation_id=None,
            generation_digest=None,
            component_identities=(),
            authority_watermark=None,
            raw_receipt_bytes=0,
            raw_receipt_digest=None,
            independently_attributable=False,
        )
    return NamedToolUpstreamIdentity(
        route=NamedToolExecutionRoute.AUTHORITY,
        execution_receipt_digest=receipt.receipt_digest,
        execution_request_digest=receipt.execution_request_digest,
        registry_digest=receipt.port_registry_digest,
        port_id=receipt.port_id,
        mode=receipt.authority_mode.value,
        outcome=NamedToolDispatchOutcome(receipt.outcome.value),
        reason=None if receipt.reason is None else receipt.reason.value,
        attribution_digest=_digest(_canonical(attribution.canonical_value())),
        upstream_request_digest=attribution.authority_request_digest,
        upstream_receipt_digest=attribution.authority_receipt_digest,
        profile_id=attribution.authority_profile_id,
        generation_id=None,
        generation_digest=None,
        component_identities=tuple(
            NamedToolComponentIdentity(item.name, item.digest)
            for item in attribution.component_identities
        ),
        authority_watermark=attribution.authority_watermark,
        raw_receipt_bytes=attribution.authority_receipt_bytes,
        raw_receipt_digest=attribution.authority_receipt_digest,
        independently_attributable=attribution.independently_attributable,
    )


def _upstream_identity(result: UpstreamExecutionResult) -> NamedToolUpstreamIdentity:
    if isinstance(result, NamedToolExecutionResult):
        return _branch_upstream(result)
    if isinstance(result, NamedAuthorityExecutionResult):
        return _authority_upstream(result)
    raise NamedToolDispatchError("dispatcher received an unsupported upstream result")


@dataclass(frozen=True, slots=True)
class NamedToolDispatchResult:
    receipt: NamedToolDispatchReceipt
    branch_result: NamedToolExecutionResult | None
    authority_result: NamedAuthorityExecutionResult | None

    def __post_init__(self) -> None:
        if not isinstance(self.receipt, NamedToolDispatchReceipt):
            raise NamedToolContractError("dispatch result receipt must be typed")
        if self.receipt.route is NamedToolExecutionRoute.BRANCH:
            if not isinstance(self.branch_result, NamedToolExecutionResult):
                raise NamedToolContractError(
                    "branch dispatch result must retain branch execution result"
                )
            if self.authority_result is not None:
                raise NamedToolContractError(
                    "branch dispatch result cannot retain authority execution"
                )
            child: UpstreamExecutionResult = self.branch_result
            child_receipt = self.branch_result.receipt
            branch_executed = child_receipt.branch_executed
            authority_read_executed = False
        else:
            if not isinstance(self.authority_result, NamedAuthorityExecutionResult):
                raise NamedToolContractError(
                    "authority dispatch result must retain authority execution result"
                )
            if self.branch_result is not None:
                raise NamedToolContractError(
                    "authority dispatch result cannot retain branch execution"
                )
            child = self.authority_result
            child_receipt = self.authority_result.receipt
            branch_executed = False
            authority_read_executed = child_receipt.authority_read_executed
        if child_receipt.tool_request_digest != self.receipt.tool_request_digest:
            raise NamedToolContractError("dispatch child request binding mismatch")
        if child_receipt.tool_envelope_digest != self.receipt.tool_envelope_digest:
            raise NamedToolContractError("dispatch child envelope binding mismatch")
        if child_receipt.authorization_receipt_digest != (
            self.receipt.authorization_receipt_digest
        ):
            raise NamedToolContractError(
                "dispatch child authorization receipt mismatch"
            )
        if child_receipt.authorization_decision_id != (
            self.receipt.authorization_decision_id
        ):
            raise NamedToolContractError(
                "dispatch child authorization decision mismatch"
            )
        if child_receipt.tool_id is not self.receipt.tool_id:
            raise NamedToolContractError("dispatch child tool mismatch")
        if NamedToolDispatchOutcome(child_receipt.outcome.value) is not (
            self.receipt.outcome
        ):
            raise NamedToolContractError("dispatch child outcome mismatch")
        if child_receipt.result_count != self.receipt.result_count:
            raise NamedToolContractError("dispatch child result-count mismatch")
        if child_receipt.no_match != self.receipt.no_match:
            raise NamedToolContractError("dispatch child no-match mismatch")
        if branch_executed != self.receipt.branch_executed:
            raise NamedToolContractError("dispatch branch-execution mismatch")
        if authority_read_executed != self.receipt.authority_read_executed:
            raise NamedToolContractError("dispatch authority-read mismatch")
        if _upstream_identity(child) != self.receipt.upstream:
            raise NamedToolContractError("dispatch upstream identity mismatch")

    @property
    def upstream_execution_receipt_bytes(self) -> bytes:
        if self.branch_result is not None:
            return self.branch_result.receipt.canonical_bytes
        assert self.authority_result is not None
        return self.authority_result.receipt.canonical_bytes

    @property
    def upstream_raw_receipt_bytes(self) -> bytes | None:
        if self.branch_result is not None:
            return self.branch_result.branch_receipt_bytes
        assert self.authority_result is not None
        return self.authority_result.authority_receipt_bytes


class NamedToolDispatchRegistry:
    """Exact two-kernel registry whose route inventory covers all six tools."""

    def __init__(
        self,
        *,
        branch_executor: NamedToolBranchExecutor,
        authority_executor: NamedToolAuthorityExecutor,
    ) -> None:
        if not isinstance(branch_executor, NamedToolBranchExecutor):
            raise NamedToolDispatchError("branch executor must use the reviewed kernel")
        if not isinstance(authority_executor, NamedToolAuthorityExecutor):
            raise NamedToolDispatchError(
                "authority executor must use the reviewed kernel"
            )
        if not isinstance(branch_executor.registry, NamedBranchPortRegistry):
            raise NamedToolDispatchError("branch executor registry is not typed")
        if not isinstance(authority_executor.registry, NamedAuthorityPortRegistry):
            raise NamedToolDispatchError("authority executor registry is not typed")
        self.branch_executor = branch_executor
        self.authority_executor = authority_executor
        self.registry_digest = _digest(
            _canonical(
                {
                    "schema_version": (
                        "newsroom.increment5.named-tool-dispatch-registry.v1"
                    ),
                    "dispatch_contract_digest": (
                        NAMED_TOOL_DISPATCH_CONTRACT_DIGEST
                    ),
                    "routes": {
                        tool_id.value: route.value
                        for tool_id, route in sorted(
                            NAMED_TOOL_ROUTES.items(),
                            key=lambda item: item[0].value,
                        )
                    },
                    "branch_registry_digest": (
                        branch_executor.registry.registry_digest
                    ),
                    "authority_registry_digest": (
                        authority_executor.registry.registry_digest
                    ),
                }
            )
        )

    def execute(
        self,
        request: NamedToolRequest,
        authorization: NamedToolAuthorizationReceipt,
    ) -> UpstreamExecutionResult:
        route = NAMED_TOOL_ROUTES[request.envelope.tool_id]
        if route is NamedToolExecutionRoute.BRANCH:
            result = self.branch_executor.execute(request, authorization)
            if not isinstance(result, NamedToolExecutionResult):
                raise NamedToolDispatchError(
                    "branch kernel returned the wrong result type"
                )
            return result
        result = self.authority_executor.execute(request, authorization)
        if not isinstance(result, NamedAuthorityExecutionResult):
            raise NamedToolDispatchError(
                "authority kernel returned the wrong result type"
            )
        return result


class NamedToolDispatchJournal:
    """Immutable common journal retaining exact child and raw receipt bytes."""

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
                CREATE TABLE IF NOT EXISTS increment5_named_tool_dispatch_receipts (
                    idempotency_key TEXT PRIMARY KEY,
                    dispatch_request_digest TEXT NOT NULL,
                    receipt_bytes BLOB NOT NULL,
                    receipt_digest TEXT NOT NULL,
                    upstream_execution_receipt_bytes BLOB NOT NULL,
                    upstream_execution_receipt_digest TEXT NOT NULL,
                    upstream_raw_receipt_bytes BLOB,
                    upstream_raw_receipt_digest TEXT
                ) WITHOUT ROWID
                """
            )

    @staticmethod
    def _decode(
        *,
        dispatch_request_digest: str,
        receipt_bytes: bytes,
        receipt_digest: str,
        upstream_execution_receipt_bytes: bytes,
        upstream_execution_receipt_digest: str,
        upstream_raw_receipt_bytes: bytes | None,
        upstream_raw_receipt_digest: str | None,
    ) -> NamedToolDispatchResult:
        if _digest(receipt_bytes) != receipt_digest:
            raise NamedToolDispatchError("retained dispatch receipt digest mismatch")
        receipt = NamedToolDispatchReceipt.from_canonical_bytes(receipt_bytes)
        if receipt.dispatch_request_digest != dispatch_request_digest:
            raise NamedToolDispatchError(
                "retained dispatch semantic binding mismatch"
            )
        if _digest(upstream_execution_receipt_bytes) != (
            upstream_execution_receipt_digest
        ):
            raise NamedToolDispatchError(
                "retained upstream execution receipt digest mismatch"
            )
        if upstream_execution_receipt_digest != (
            receipt.upstream.execution_receipt_digest
        ):
            raise NamedToolDispatchError(
                "upstream execution receipt differs from dispatch identity"
            )
        if receipt.upstream.raw_receipt_digest is None:
            if (
                upstream_raw_receipt_bytes is not None
                or upstream_raw_receipt_digest is not None
            ):
                raise NamedToolDispatchError(
                    "non-attributed dispatch retained unexpected raw receipt"
                )
        else:
            if (
                upstream_raw_receipt_bytes is None
                or upstream_raw_receipt_digest is None
            ):
                raise NamedToolDispatchError(
                    "attributed dispatch is missing raw upstream receipt"
                )
            if _digest(upstream_raw_receipt_bytes) != upstream_raw_receipt_digest:
                raise NamedToolDispatchError(
                    "retained upstream raw receipt digest mismatch"
                )
            if upstream_raw_receipt_digest != receipt.upstream.raw_receipt_digest:
                raise NamedToolDispatchError(
                    "raw receipt differs from dispatch upstream identity"
                )
        if receipt.route is NamedToolExecutionRoute.BRANCH:
            child_receipt = NamedToolExecutionReceipt.from_canonical_bytes(
                upstream_execution_receipt_bytes
            )
            return NamedToolDispatchResult(
                receipt=receipt,
                branch_result=NamedToolExecutionResult(
                    receipt=child_receipt,
                    branch_receipt_bytes=upstream_raw_receipt_bytes,
                ),
                authority_result=None,
            )
        child_receipt = NamedAuthorityExecutionReceipt.from_canonical_bytes(
            upstream_execution_receipt_bytes
        )
        return NamedToolDispatchResult(
            receipt=receipt,
            branch_result=None,
            authority_result=NamedAuthorityExecutionResult(
                receipt=child_receipt,
                authority_receipt_bytes=upstream_raw_receipt_bytes,
            ),
        )

    def _existing(
        self,
        *,
        idempotency_key: str,
        dispatch_request_digest: str,
    ) -> NamedToolDispatchResult | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT
                        dispatch_request_digest,
                        receipt_bytes,
                        receipt_digest,
                        upstream_execution_receipt_bytes,
                        upstream_execution_receipt_digest,
                        upstream_raw_receipt_bytes,
                        upstream_raw_receipt_digest
                    FROM increment5_named_tool_dispatch_receipts
                    WHERE idempotency_key = ?
                    """,
                    (idempotency_key,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise NamedToolDispatchError(
                "named-tool dispatch journal read failed"
            ) from exc
        if row is None:
            return None
        if row[0] != dispatch_request_digest:
            raise NamedToolDispatchError(
                "named-tool dispatch idempotency semantic conflict"
            )
        return self._decode(
            dispatch_request_digest=row[0],
            receipt_bytes=bytes(row[1]),
            receipt_digest=row[2],
            upstream_execution_receipt_bytes=bytes(row[3]),
            upstream_execution_receipt_digest=row[4],
            upstream_raw_receipt_bytes=(
                None if row[5] is None else bytes(row[5])
            ),
            upstream_raw_receipt_digest=row[6],
        )

    def execute(
        self,
        *,
        idempotency_key: str,
        dispatch_request_digest: str,
        producer: Callable[[], NamedToolDispatchResult],
    ) -> NamedToolDispatchResult:
        existing = self._existing(
            idempotency_key=idempotency_key,
            dispatch_request_digest=dispatch_request_digest,
        )
        if existing is not None:
            return existing
        result = producer()
        if result.receipt.dispatch_request_digest != dispatch_request_digest:
            raise NamedToolDispatchError(
                "produced dispatch receipt does not bind semantic request"
            )
        receipt_bytes = result.receipt.canonical_bytes
        receipt_digest = _digest(receipt_bytes)
        execution_bytes = result.upstream_execution_receipt_bytes
        execution_digest = _digest(execution_bytes)
        raw_bytes = result.upstream_raw_receipt_bytes
        raw_digest = None if raw_bytes is None else _digest(raw_bytes)
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT
                    dispatch_request_digest,
                    receipt_bytes,
                    receipt_digest,
                    upstream_execution_receipt_bytes,
                    upstream_execution_receipt_digest,
                    upstream_raw_receipt_bytes,
                    upstream_raw_receipt_digest
                FROM increment5_named_tool_dispatch_receipts
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            if row is not None:
                connection.execute("ROLLBACK")
                if row[0] != dispatch_request_digest:
                    raise NamedToolDispatchError(
                        "named-tool dispatch idempotency semantic conflict"
                    )
                return self._decode(
                    dispatch_request_digest=row[0],
                    receipt_bytes=bytes(row[1]),
                    receipt_digest=row[2],
                    upstream_execution_receipt_bytes=bytes(row[3]),
                    upstream_execution_receipt_digest=row[4],
                    upstream_raw_receipt_bytes=(
                        None if row[5] is None else bytes(row[5])
                    ),
                    upstream_raw_receipt_digest=row[6],
                )
            connection.execute(
                """
                INSERT INTO increment5_named_tool_dispatch_receipts (
                    idempotency_key,
                    dispatch_request_digest,
                    receipt_bytes,
                    receipt_digest,
                    upstream_execution_receipt_bytes,
                    upstream_execution_receipt_digest,
                    upstream_raw_receipt_bytes,
                    upstream_raw_receipt_digest
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    idempotency_key,
                    dispatch_request_digest,
                    receipt_bytes,
                    receipt_digest,
                    execution_bytes,
                    execution_digest,
                    raw_bytes,
                    raw_digest,
                ),
            )
            connection.execute("COMMIT")
        except NamedToolDispatchError:
            if connection is not None:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            raise
        except sqlite3.Error as exc:
            if connection is not None:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            raise NamedToolDispatchError(
                "named-tool dispatch journal write failed"
            ) from exc
        finally:
            if connection is not None:
                connection.close()
        return result


class NamedToolDispatcher:
    """Route one typed request through one exact reviewed execution kernel."""

    def __init__(
        self,
        *,
        registry: NamedToolDispatchRegistry,
        journal: NamedToolDispatchJournal,
    ) -> None:
        if not isinstance(registry, NamedToolDispatchRegistry):
            raise NamedToolDispatchError("dispatcher registry must be typed")
        if not isinstance(journal, NamedToolDispatchJournal):
            raise NamedToolDispatchError("dispatcher journal must be typed")
        self.registry = registry
        self.journal = journal

    def execute(
        self,
        request: NamedToolRequest,
        authorization: NamedToolAuthorizationReceipt,
    ) -> NamedToolDispatchResult:
        if not hasattr(request, "envelope") or not hasattr(request, "request_digest"):
            raise TypeError("named-tool dispatch request must be typed")
        tool_id = request.envelope.tool_id
        expected_type = _REQUEST_TYPES.get(tool_id)
        if expected_type is None or not isinstance(request, expected_type):
            raise NamedToolDispatchError(
                "named-tool request type does not match the closed tool identity"
            )
        if not isinstance(authorization, NamedToolAuthorizationReceipt):
            raise TypeError("named-tool dispatch authorization must be typed")
        dispatch_request_digest = _digest(
            _canonical(
                {
                    "schema_version": (
                        "newsroom.increment5.named-tool-dispatch-request.v1"
                    ),
                    "tool_request_digest": request.request_digest,
                    "authorization_receipt_digest": authorization.receipt_digest,
                    "dispatcher_registry_digest": self.registry.registry_digest,
                }
            )
        )
        return self.journal.execute(
            idempotency_key=request.envelope.idempotency_key,
            dispatch_request_digest=dispatch_request_digest,
            producer=lambda: self._produce(
                request,
                authorization,
                dispatch_request_digest,
            ),
        )

    def _produce(
        self,
        request: NamedToolRequest,
        authorization: NamedToolAuthorizationReceipt,
        dispatch_request_digest: str,
    ) -> NamedToolDispatchResult:
        child = self.registry.execute(request, authorization)
        upstream = _upstream_identity(child)
        if isinstance(child, NamedToolExecutionResult):
            child_receipt = child.receipt
            branch_result: NamedToolExecutionResult | None = child
            authority_result: NamedAuthorityExecutionResult | None = None
            branch_executed = child_receipt.branch_executed
            authority_read_executed = False
        else:
            child_receipt = child.receipt
            branch_result = None
            authority_result = child
            branch_executed = False
            authority_read_executed = child_receipt.authority_read_executed
        outcome = NamedToolDispatchOutcome(child_receipt.outcome.value)
        reason = _normalized_reason(
            upstream.route,
            upstream.reason,
            outcome,
            child_receipt.no_match,
        )
        dispatch_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                "|".join(
                    (
                        dispatch_request_digest,
                        upstream.execution_receipt_digest,
                        outcome.value,
                        "NONE" if reason is None else reason.value,
                    )
                ),
            )
        )
        receipt = NamedToolDispatchReceipt(
            dispatch_id=dispatch_id,
            dispatch_request_digest=dispatch_request_digest,
            tool_request_digest=request.request_digest,
            tool_envelope_digest=request.envelope.envelope_digest,
            authorization_receipt_digest=authorization.receipt_digest,
            authorization_decision_id=authorization.decision_id,
            dispatch_contract_digest=NAMED_TOOL_DISPATCH_CONTRACT_DIGEST,
            dispatcher_registry_digest=self.registry.registry_digest,
            tool_id=request.envelope.tool_id,
            route=upstream.route,
            outcome=outcome,
            reason=reason,
            upstream=upstream,
            result_count=child_receipt.result_count,
            no_match=child_receipt.no_match,
            response_limit_bytes=request.envelope.response_limit_bytes,
            branch_executed=branch_executed,
            authority_read_executed=authority_read_executed,
        )
        return NamedToolDispatchResult(
            receipt=receipt,
            branch_result=branch_result,
            authority_result=authority_result,
        )


__all__ = [
    "NAMED_TOOL_DISPATCH_CONTRACT_DIGEST",
    "NAMED_TOOL_ROUTES",
    "NamedToolComponentIdentity",
    "NamedToolDispatchError",
    "NamedToolDispatchJournal",
    "NamedToolDispatchOutcome",
    "NamedToolDispatchReason",
    "NamedToolDispatchReceipt",
    "NamedToolDispatchRegistry",
    "NamedToolDispatchResult",
    "NamedToolDispatcher",
    "NamedToolExecutionRoute",
    "NamedToolUpstreamIdentity",
]
