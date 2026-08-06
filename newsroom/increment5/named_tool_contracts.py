"""Strict branch-neutral contracts for the six Increment 5C named tools.

This module defines request shape only.  It imports and invokes no retriever,
Neo4j adapter, authority store, hydration store, model, provider or network
client.  A valid request still has no authority and cannot claim a completed
tool execution until a later 5C atom retains the appropriate branch or
authority-read receipt.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Mapping, Sequence, TypeAlias


NAMED_TOOL_POLICY_ID = "increment5-named-read-tools-v1"
NAMED_TOOL_PROFILE_ID = "increment5-named-read-tools-v1"
NAMED_TOOL_RESULT_LIMIT = 8
NAMED_TOOL_TIMEOUT_LIMIT_MS = 5_000
NAMED_TOOL_RESPONSE_LIMIT_BYTES = 262_144
NAMED_TOOL_DATE_WINDOW_SECONDS = 2_678_400
NAMED_TOOL_GRAPH_DEPTH_LIMIT = 2
NAMED_TOOL_GRAPH_FANOUT_LIMIT = 32
NAMED_TOOL_QUERY_TEXT_LIMIT_BYTES = 4_096
NAMED_TOOL_IDENTITY_LIMIT_BYTES = 512
NAMED_TOOL_EXTERNAL_CALL_LIMIT = 0
NAMED_TOOL_PROVIDER_SPEND_LIMIT_MICROS = 0

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}\Z")
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class NamedToolContractError(ValueError):
    """A named-tool envelope, scope or request is malformed."""


class NamedToolId(StrEnum):
    EXACT_AUTHORITY_LOOKUP = "EXACT_AUTHORITY_LOOKUP"
    BOUNDED_FULL_TEXT_RETRIEVAL = "BOUNDED_FULL_TEXT_RETRIEVAL"
    BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL = "BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL"
    BOUNDED_ADMITTED_GRAPH_TRAVERSAL = "BOUNDED_ADMITTED_GRAPH_TRAVERSAL"
    CURRENT_COLLISION_AND_AUTHORITY_HYDRATION_LOOKUP = (
        "CURRENT_COLLISION_AND_AUTHORITY_HYDRATION_LOOKUP"
    )
    BOUNDED_SOURCE_REVISION_IMPACT_LOOKUP = "BOUNDED_SOURCE_REVISION_IMPACT_LOOKUP"


class NamedToolPurpose(StrEnum):
    TRIAGE_PRIOR_MATCH = "TRIAGE_PRIOR_MATCH"
    CORRECTION_REVIEW = "CORRECTION_REVIEW"
    COLLISION_CHECK = "COLLISION_CHECK"
    AUTHORITY_HYDRATION = "AUTHORITY_HYDRATION"
    SOURCE_IMPACT = "SOURCE_IMPACT"
    REPLAY_AUDIT = "REPLAY_AUDIT"


class NamedToolLanguage(StrEnum):
    EN_GB = "EN_GB"
    ZH_HANT_HK = "ZH_HANT_HK"
    MIXED = "MIXED"


class ExactLookupKind(StrEnum):
    SOURCE_NATIVE_ID = "SOURCE_NATIVE_ID"
    REVISION_ID = "REVISION_ID"
    REPRESENTATION_ID = "REPRESENTATION_ID"
    CANONICAL_ENTITY_ID = "CANONICAL_ENTITY_ID"
    AUTHORITY_ALIAS = "AUTHORITY_ALIAS"
    FORMAL_PROCESS_ID = "FORMAL_PROCESS_ID"


PERMITTED_PURPOSES: Mapping[NamedToolId, frozenset[NamedToolPurpose]] = {
    NamedToolId.EXACT_AUTHORITY_LOOKUP: frozenset(
        {
            NamedToolPurpose.TRIAGE_PRIOR_MATCH,
            NamedToolPurpose.COLLISION_CHECK,
            NamedToolPurpose.REPLAY_AUDIT,
        }
    ),
    NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL: frozenset(
        {
            NamedToolPurpose.TRIAGE_PRIOR_MATCH,
            NamedToolPurpose.CORRECTION_REVIEW,
            NamedToolPurpose.REPLAY_AUDIT,
        }
    ),
    NamedToolId.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL: frozenset(
        {
            NamedToolPurpose.TRIAGE_PRIOR_MATCH,
            NamedToolPurpose.CORRECTION_REVIEW,
            NamedToolPurpose.REPLAY_AUDIT,
        }
    ),
    NamedToolId.BOUNDED_ADMITTED_GRAPH_TRAVERSAL: frozenset(
        {
            NamedToolPurpose.TRIAGE_PRIOR_MATCH,
            NamedToolPurpose.CORRECTION_REVIEW,
            NamedToolPurpose.REPLAY_AUDIT,
        }
    ),
    NamedToolId.CURRENT_COLLISION_AND_AUTHORITY_HYDRATION_LOOKUP: frozenset(
        {
            NamedToolPurpose.COLLISION_CHECK,
            NamedToolPurpose.AUTHORITY_HYDRATION,
            NamedToolPurpose.REPLAY_AUDIT,
        }
    ),
    NamedToolId.BOUNDED_SOURCE_REVISION_IMPACT_LOOKUP: frozenset(
        {
            NamedToolPurpose.SOURCE_IMPACT,
            NamedToolPurpose.CORRECTION_REVIEW,
            NamedToolPurpose.REPLAY_AUDIT,
        }
    ),
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
        raise NamedToolContractError("value is not canonical JSON") from exc


def _digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _strict_keys(
    value: Mapping[str, object],
    *,
    required: set[str],
    field: str,
) -> None:
    actual = set(value)
    if actual != required:
        raise NamedToolContractError(
            f"{field} keys are not exact; "
            f"missing={sorted(required - actual)}, extra={sorted(actual - required)}"
        )


def _require_token(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _TOKEN_RE.fullmatch(value) is None:
        raise NamedToolContractError(f"{field} must be a bounded canonical token")
    return value


def _require_digest(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise NamedToolContractError(f"{field} must be a canonical SHA-256 digest")
    return value


def _require_text(value: str, *, field: str, maximum_bytes: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > maximum_bytes
        or _CONTROL_RE.search(value) is not None
    ):
        raise NamedToolContractError(f"{field} must be bounded canonical text")
    return value


def _require_uuid4(value: str, *, field: str) -> str:
    if not isinstance(value, str):
        raise NamedToolContractError(f"{field} must be a UUIDv4 string")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise NamedToolContractError(f"{field} must be a UUIDv4 string") from exc
    if parsed.version != 4 or str(parsed) != value:
        raise NamedToolContractError(f"{field} must be a canonical UUIDv4 string")
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


def _require_int_range(value: int, *, field: str, minimum: int, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise NamedToolContractError(
            f"{field} must be an integer in [{minimum}, {maximum}]"
        )
    return value


def _require_text_tuple(
    values: Sequence[object],
    *,
    field: str,
    minimum: int = 0,
    maximum: int = NAMED_TOOL_RESULT_LIMIT,
    item_maximum_bytes: int = NAMED_TOOL_IDENTITY_LIMIT_BYTES,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise NamedToolContractError(f"{field} must be a bounded sequence")
    if not minimum <= len(values) <= maximum:
        raise NamedToolContractError(
            f"{field} must contain between {minimum} and {maximum} values"
        )
    result = tuple(
        _require_text(item, field=f"{field}[{index}]", maximum_bytes=item_maximum_bytes)
        for index, item in enumerate(values)
    )
    if result != tuple(sorted(set(result))):
        raise NamedToolContractError(f"{field} must be sorted and unique")
    return result


def _enum(value: object, enum_type: type[StrEnum], *, field: str):
    if not isinstance(value, str):
        raise NamedToolContractError(f"{field} must be text")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise NamedToolContractError(f"{field} is not accepted") from exc


@dataclass(frozen=True, slots=True)
class ToolScopeClaim:
    dimension: str
    values: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_token(self.dimension, field="scope_dimension")
        object.__setattr__(
            self,
            "values",
            _require_text_tuple(
                self.values,
                field=f"scope[{self.dimension}]",
                minimum=1,
                maximum=32,
            ),
        )

    def canonical_value(self) -> dict[str, object]:
        return {"dimension": self.dimension, "values": list(self.values)}

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ToolScopeClaim":
        _strict_keys(
            value,
            required={"dimension", "values"},
            field="scope_claim",
        )
        dimension = value["dimension"]
        values = value["values"]
        if not isinstance(dimension, str) or not isinstance(values, list):
            raise NamedToolContractError("scope claim has an invalid shape")
        return cls(dimension=dimension, values=tuple(values))


@dataclass(frozen=True, slots=True)
class ToolScope:
    claims: tuple[ToolScopeClaim, ...]

    def __post_init__(self) -> None:
        if not self.claims:
            raise NamedToolContractError("tool scope must contain at least one claim")
        if not all(isinstance(claim, ToolScopeClaim) for claim in self.claims):
            raise NamedToolContractError("tool scope claims must be typed")
        dimensions = tuple(claim.dimension for claim in self.claims)
        if dimensions != tuple(sorted(set(dimensions))):
            raise NamedToolContractError(
                "tool scope claims must be sorted by unique dimension"
            )

    def canonical_value(self) -> dict[str, object]:
        return {"claims": [claim.canonical_value() for claim in self.claims]}

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.canonical_value())

    @property
    def scope_digest(self) -> str:
        return _digest_bytes(self.canonical_bytes)

    def as_mapping(self) -> dict[str, frozenset[str]]:
        return {
            claim.dimension: frozenset(claim.values)
            for claim in self.claims
        }

    def contains(self, requested: "ToolScope") -> bool:
        granted = self.as_mapping()
        for dimension, values in requested.as_mapping().items():
            if dimension not in granted or not values.issubset(granted[dimension]):
                return False
        return True

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ToolScope":
        _strict_keys(value, required={"claims"}, field="tool_scope")
        raw_claims = value["claims"]
        if not isinstance(raw_claims, list) or not all(
            isinstance(item, dict) for item in raw_claims
        ):
            raise NamedToolContractError("tool scope claims must be objects")
        return cls(
            claims=tuple(ToolScopeClaim.from_mapping(item) for item in raw_claims)
        )

    @classmethod
    def from_dimensions(cls, **dimensions: Sequence[str]) -> "ToolScope":
        claims = tuple(
            ToolScopeClaim(dimension=name, values=tuple(sorted(set(values))))
            for name, values in sorted(dimensions.items())
            if values
        )
        return cls(claims=claims)


@dataclass(frozen=True, slots=True)
class NamedToolEnvelope:
    request_id: str
    idempotency_key: str
    tool_id: NamedToolId
    actor_id: str
    authenticated_principal_digest: str
    authorization_grant_id: str
    purpose: NamedToolPurpose
    policy_id: str
    policy_digest: str
    contract_digest: str
    profile_id: str
    generation_id: str
    query_valid_time: str
    serving_time: str
    requested_scope: ToolScope
    result_limit: int
    timeout_ms: int
    response_limit_bytes: int

    def __post_init__(self) -> None:
        _require_uuid4(self.request_id, field="named_tool_request_id")
        _require_text(
            self.idempotency_key,
            field="named_tool_idempotency_key",
            maximum_bytes=256,
        )
        if not isinstance(self.tool_id, NamedToolId):
            raise NamedToolContractError("tool_id must be typed")
        _require_token(self.actor_id, field="named_tool_actor_id")
        _require_digest(
            self.authenticated_principal_digest,
            field="authenticated_principal_digest",
        )
        _require_token(self.authorization_grant_id, field="authorization_grant_id")
        if not isinstance(self.purpose, NamedToolPurpose):
            raise NamedToolContractError("purpose must be typed")
        if self.purpose not in PERMITTED_PURPOSES[self.tool_id]:
            raise NamedToolContractError("purpose is not permitted for the named tool")
        _require_token(self.policy_id, field="named_tool_policy_id")
        _require_digest(self.policy_digest, field="named_tool_policy_digest")
        _require_digest(self.contract_digest, field="named_tool_contract_digest")
        _require_token(self.profile_id, field="named_tool_profile_id")
        _require_token(self.generation_id, field="named_tool_generation_id")
        query_valid = _parse_utc(
            self.query_valid_time,
            field="named_tool_query_valid_time",
        )
        serving = _parse_utc(self.serving_time, field="named_tool_serving_time")
        if query_valid > serving:
            raise NamedToolContractError(
                "named-tool query-valid time cannot be after serving time"
            )
        if not isinstance(self.requested_scope, ToolScope):
            raise NamedToolContractError("requested_scope must be typed")
        _require_int_range(
            self.result_limit,
            field="named_tool_result_limit",
            minimum=1,
            maximum=NAMED_TOOL_RESULT_LIMIT,
        )
        _require_int_range(
            self.timeout_ms,
            field="named_tool_timeout_ms",
            minimum=1,
            maximum=NAMED_TOOL_TIMEOUT_LIMIT_MS,
        )
        _require_int_range(
            self.response_limit_bytes,
            field="named_tool_response_limit_bytes",
            minimum=1_024,
            maximum=NAMED_TOOL_RESPONSE_LIMIT_BYTES,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "idempotency_key": self.idempotency_key,
            "tool_id": self.tool_id.value,
            "actor_id": self.actor_id,
            "authenticated_principal_digest": self.authenticated_principal_digest,
            "authorization_grant_id": self.authorization_grant_id,
            "purpose": self.purpose.value,
            "policy_id": self.policy_id,
            "policy_digest": self.policy_digest,
            "contract_digest": self.contract_digest,
            "profile_id": self.profile_id,
            "generation_id": self.generation_id,
            "query_valid_time": self.query_valid_time,
            "serving_time": self.serving_time,
            "requested_scope": self.requested_scope.canonical_value(),
            "result_limit": self.result_limit,
            "timeout_ms": self.timeout_ms,
            "response_limit_bytes": self.response_limit_bytes,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.canonical_value())

    @property
    def envelope_digest(self) -> str:
        return _digest_bytes(self.canonical_bytes)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "NamedToolEnvelope":
        required = {
            "request_id",
            "idempotency_key",
            "tool_id",
            "actor_id",
            "authenticated_principal_digest",
            "authorization_grant_id",
            "purpose",
            "policy_id",
            "policy_digest",
            "contract_digest",
            "profile_id",
            "generation_id",
            "query_valid_time",
            "serving_time",
            "requested_scope",
            "result_limit",
            "timeout_ms",
            "response_limit_bytes",
        }
        _strict_keys(value, required=required, field="named_tool_envelope")
        raw_scope = value["requested_scope"]
        if not isinstance(raw_scope, dict):
            raise NamedToolContractError("requested_scope must be an object")
        text_fields = (
            "request_id",
            "idempotency_key",
            "actor_id",
            "authenticated_principal_digest",
            "authorization_grant_id",
            "policy_id",
            "policy_digest",
            "contract_digest",
            "profile_id",
            "generation_id",
            "query_valid_time",
            "serving_time",
        )
        if not all(isinstance(value[name], str) for name in text_fields):
            raise NamedToolContractError("named-tool envelope text field is malformed")
        return cls(
            request_id=value["request_id"],
            idempotency_key=value["idempotency_key"],
            tool_id=_enum(value["tool_id"], NamedToolId, field="tool_id"),
            actor_id=value["actor_id"],
            authenticated_principal_digest=value[
                "authenticated_principal_digest"
            ],
            authorization_grant_id=value["authorization_grant_id"],
            purpose=_enum(value["purpose"], NamedToolPurpose, field="purpose"),
            policy_id=value["policy_id"],
            policy_digest=value["policy_digest"],
            contract_digest=value["contract_digest"],
            profile_id=value["profile_id"],
            generation_id=value["generation_id"],
            query_valid_time=value["query_valid_time"],
            serving_time=value["serving_time"],
            requested_scope=ToolScope.from_mapping(raw_scope),
            result_limit=value["result_limit"],
            timeout_ms=value["timeout_ms"],
            response_limit_bytes=value["response_limit_bytes"],
        )


def _require_scope(envelope: NamedToolEnvelope, expected: ToolScope) -> None:
    if envelope.requested_scope.canonical_bytes != expected.canonical_bytes:
        raise NamedToolContractError(
            "requested scope does not exactly match the typed request scope"
        )


def _request_digest(schema_version: str, envelope: NamedToolEnvelope, payload: object) -> str:
    return _digest_bytes(
        _canonical_json_bytes(
            {
                "schema_version": schema_version,
                "envelope": envelope.canonical_value(),
                "payload": payload,
            }
        )
    )


@dataclass(frozen=True, slots=True)
class ExactAuthorityLookupToolRequest:
    envelope: NamedToolEnvelope
    lookup_kind: ExactLookupKind
    lookup_value: str
    lookup_value_digest: str

    SCHEMA_VERSION = "newsroom.increment5.named-tool.exact-authority.v1"

    def __post_init__(self) -> None:
        if self.envelope.tool_id is not NamedToolId.EXACT_AUTHORITY_LOOKUP:
            raise NamedToolContractError("envelope tool does not match exact lookup")
        if not isinstance(self.lookup_kind, ExactLookupKind):
            raise NamedToolContractError("lookup_kind must be typed")
        _require_text(
            self.lookup_value,
            field="exact_lookup_value",
            maximum_bytes=NAMED_TOOL_IDENTITY_LIMIT_BYTES,
        )
        _require_digest(self.lookup_value_digest, field="exact_lookup_value_digest")
        if self.lookup_value_digest != _digest_bytes(self.lookup_value.encode("utf-8")):
            raise NamedToolContractError("exact lookup value digest does not match bytes")
        _require_scope(
            self.envelope,
            ToolScope.from_dimensions(lookup_kind=(self.lookup_kind.value,)),
        )

    def payload_value(self) -> dict[str, str]:
        return {
            "lookup_kind": self.lookup_kind.value,
            "lookup_value": self.lookup_value,
            "lookup_value_digest": self.lookup_value_digest,
        }

    @property
    def request_digest(self) -> str:
        return _request_digest(self.SCHEMA_VERSION, self.envelope, self.payload_value())

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ExactAuthorityLookupToolRequest":
        _strict_keys(
            value,
            required={"schema_version", "envelope", "lookup_kind", "lookup_value", "lookup_value_digest"},
            field="exact_authority_request",
        )
        if value["schema_version"] != cls.SCHEMA_VERSION:
            raise NamedToolContractError("exact authority schema version is not accepted")
        if not isinstance(value["envelope"], dict):
            raise NamedToolContractError("exact authority envelope must be an object")
        for name in ("lookup_value", "lookup_value_digest"):
            if not isinstance(value[name], str):
                raise NamedToolContractError(f"{name} must be text")
        return cls(
            envelope=NamedToolEnvelope.from_mapping(value["envelope"]),
            lookup_kind=_enum(value["lookup_kind"], ExactLookupKind, field="lookup_kind"),
            lookup_value=value["lookup_value"],
            lookup_value_digest=value["lookup_value_digest"],
        )


@dataclass(frozen=True, slots=True)
class FullTextRetrievalToolRequest:
    envelope: NamedToolEnvelope
    query_text: str
    query_text_digest: str
    languages: tuple[NamedToolLanguage, ...]
    source_ids: tuple[str, ...]

    SCHEMA_VERSION = "newsroom.increment5.named-tool.full-text.v1"

    def __post_init__(self) -> None:
        if self.envelope.tool_id is not NamedToolId.BOUNDED_FULL_TEXT_RETRIEVAL:
            raise NamedToolContractError("envelope tool does not match full-text lookup")
        _require_text(
            self.query_text,
            field="full_text_query",
            maximum_bytes=NAMED_TOOL_QUERY_TEXT_LIMIT_BYTES,
        )
        _require_digest(self.query_text_digest, field="full_text_query_digest")
        if self.query_text_digest != _digest_bytes(self.query_text.encode("utf-8")):
            raise NamedToolContractError("full-text query digest does not match bytes")
        if not self.languages or len(set(self.languages)) != len(self.languages):
            raise NamedToolContractError("full-text languages must be unique and non-empty")
        if tuple(language.value for language in self.languages) != tuple(
            sorted(language.value for language in self.languages)
        ):
            raise NamedToolContractError("full-text languages must be sorted")
        object.__setattr__(
            self,
            "source_ids",
            _require_text_tuple(self.source_ids, field="full_text_source_ids"),
        )
        dimensions: dict[str, Sequence[str]] = {
            "language": tuple(language.value for language in self.languages)
        }
        if self.source_ids:
            dimensions["source_id"] = self.source_ids
        _require_scope(self.envelope, ToolScope.from_dimensions(**dimensions))

    def payload_value(self) -> dict[str, object]:
        return {
            "query_text": self.query_text,
            "query_text_digest": self.query_text_digest,
            "languages": [language.value for language in self.languages],
            "source_ids": list(self.source_ids),
        }

    @property
    def request_digest(self) -> str:
        return _request_digest(self.SCHEMA_VERSION, self.envelope, self.payload_value())

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "FullTextRetrievalToolRequest":
        _strict_keys(
            value,
            required={"schema_version", "envelope", "query_text", "query_text_digest", "languages", "source_ids"},
            field="full_text_tool_request",
        )
        if value["schema_version"] != cls.SCHEMA_VERSION:
            raise NamedToolContractError("full-text schema version is not accepted")
        if not isinstance(value["envelope"], dict):
            raise NamedToolContractError("full-text envelope must be an object")
        if not isinstance(value["query_text"], str) or not isinstance(value["query_text_digest"], str):
            raise NamedToolContractError("full-text query fields must be text")
        if not isinstance(value["languages"], list) or not isinstance(value["source_ids"], list):
            raise NamedToolContractError("full-text language/source fields must be lists")
        return cls(
            envelope=NamedToolEnvelope.from_mapping(value["envelope"]),
            query_text=value["query_text"],
            query_text_digest=value["query_text_digest"],
            languages=tuple(
                _enum(item, NamedToolLanguage, field="language")
                for item in value["languages"]
            ),
            source_ids=tuple(value["source_ids"]),
        )


@dataclass(frozen=True, slots=True)
class FixedPointVectorRetrievalToolRequest:
    envelope: NamedToolEnvelope
    fixture_query_id: str
    fixture_query_digest: str

    SCHEMA_VERSION = "newsroom.increment5.named-tool.fixed-point-vector.v1"

    def __post_init__(self) -> None:
        if self.envelope.tool_id is not NamedToolId.BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL:
            raise NamedToolContractError("envelope tool does not match vector lookup")
        _require_token(self.fixture_query_id, field="fixture_query_id")
        _require_digest(self.fixture_query_digest, field="fixture_query_digest")
        _require_scope(
            self.envelope,
            ToolScope.from_dimensions(fixture_query=(self.fixture_query_id,)),
        )

    def payload_value(self) -> dict[str, str]:
        return {
            "fixture_query_id": self.fixture_query_id,
            "fixture_query_digest": self.fixture_query_digest,
        }

    @property
    def request_digest(self) -> str:
        return _request_digest(self.SCHEMA_VERSION, self.envelope, self.payload_value())

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "FixedPointVectorRetrievalToolRequest":
        _strict_keys(
            value,
            required={"schema_version", "envelope", "fixture_query_id", "fixture_query_digest"},
            field="fixed_point_vector_request",
        )
        if value["schema_version"] != cls.SCHEMA_VERSION:
            raise NamedToolContractError("vector schema version is not accepted")
        if not isinstance(value["envelope"], dict):
            raise NamedToolContractError("vector envelope must be an object")
        if not isinstance(value["fixture_query_id"], str) or not isinstance(value["fixture_query_digest"], str):
            raise NamedToolContractError("vector query fields must be text")
        return cls(
            envelope=NamedToolEnvelope.from_mapping(value["envelope"]),
            fixture_query_id=value["fixture_query_id"],
            fixture_query_digest=value["fixture_query_digest"],
        )


@dataclass(frozen=True, slots=True)
class AdmittedGraphTraversalToolRequest:
    envelope: NamedToolEnvelope
    root_id: str
    root_identity_digest: str
    maximum_depth: int
    maximum_fanout: int
    temporal_window_seconds: int

    SCHEMA_VERSION = "newsroom.increment5.named-tool.admitted-graph.v1"

    def __post_init__(self) -> None:
        if self.envelope.tool_id is not NamedToolId.BOUNDED_ADMITTED_GRAPH_TRAVERSAL:
            raise NamedToolContractError("envelope tool does not match graph traversal")
        _require_text(
            self.root_id,
            field="graph_tool_root_id",
            maximum_bytes=NAMED_TOOL_IDENTITY_LIMIT_BYTES,
        )
        _require_digest(self.root_identity_digest, field="graph_tool_root_digest")
        if self.root_identity_digest != _digest_bytes(
            f"canonical-node:{self.root_id}".encode("utf-8")
        ):
            raise NamedToolContractError("graph root digest does not match canonical id")
        _require_int_range(
            self.maximum_depth,
            field="graph_tool_maximum_depth",
            minimum=1,
            maximum=NAMED_TOOL_GRAPH_DEPTH_LIMIT,
        )
        _require_int_range(
            self.maximum_fanout,
            field="graph_tool_maximum_fanout",
            minimum=1,
            maximum=NAMED_TOOL_GRAPH_FANOUT_LIMIT,
        )
        _require_int_range(
            self.temporal_window_seconds,
            field="graph_tool_temporal_window_seconds",
            minimum=1,
            maximum=NAMED_TOOL_DATE_WINDOW_SECONDS,
        )
        _require_scope(
            self.envelope,
            ToolScope.from_dimensions(root_id=(self.root_id,)),
        )

    def payload_value(self) -> dict[str, object]:
        return {
            "root_id": self.root_id,
            "root_identity_digest": self.root_identity_digest,
            "maximum_depth": self.maximum_depth,
            "maximum_fanout": self.maximum_fanout,
            "temporal_window_seconds": self.temporal_window_seconds,
        }

    @property
    def request_digest(self) -> str:
        return _request_digest(self.SCHEMA_VERSION, self.envelope, self.payload_value())

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "AdmittedGraphTraversalToolRequest":
        _strict_keys(
            value,
            required={"schema_version", "envelope", "root_id", "root_identity_digest", "maximum_depth", "maximum_fanout", "temporal_window_seconds"},
            field="admitted_graph_tool_request",
        )
        if value["schema_version"] != cls.SCHEMA_VERSION:
            raise NamedToolContractError("graph schema version is not accepted")
        if not isinstance(value["envelope"], dict):
            raise NamedToolContractError("graph envelope must be an object")
        if not isinstance(value["root_id"], str) or not isinstance(value["root_identity_digest"], str):
            raise NamedToolContractError("graph root fields must be text")
        return cls(
            envelope=NamedToolEnvelope.from_mapping(value["envelope"]),
            root_id=value["root_id"],
            root_identity_digest=value["root_identity_digest"],
            maximum_depth=value["maximum_depth"],
            maximum_fanout=value["maximum_fanout"],
            temporal_window_seconds=value["temporal_window_seconds"],
        )


@dataclass(frozen=True, slots=True)
class CollisionHydrationLookupToolRequest:
    envelope: NamedToolEnvelope
    collision_namespace: str
    collision_key_digest: str
    authority_object_ids: tuple[str, ...]
    passage_ids: tuple[str, ...]
    require_current_collision: bool

    SCHEMA_VERSION = "newsroom.increment5.named-tool.collision-hydration.v1"

    def __post_init__(self) -> None:
        if (
            self.envelope.tool_id
            is not NamedToolId.CURRENT_COLLISION_AND_AUTHORITY_HYDRATION_LOOKUP
        ):
            raise NamedToolContractError(
                "envelope tool does not match collision/hydration lookup"
            )
        _require_token(self.collision_namespace, field="collision_namespace")
        _require_digest(self.collision_key_digest, field="collision_key_digest")
        object.__setattr__(
            self,
            "authority_object_ids",
            _require_text_tuple(
                self.authority_object_ids,
                field="authority_object_ids",
            ),
        )
        object.__setattr__(
            self,
            "passage_ids",
            _require_text_tuple(self.passage_ids, field="passage_ids"),
        )
        if not self.authority_object_ids and not self.passage_ids:
            raise NamedToolContractError(
                "collision/hydration request must name an authority object or passage"
            )
        if self.require_current_collision is not True:
            raise NamedToolContractError(
                "collision/hydration lookup must require current relational collision state"
            )
        dimensions: dict[str, Sequence[str]] = {
            "collision_namespace": (self.collision_namespace,)
        }
        if self.authority_object_ids:
            dimensions["authority_object_id"] = self.authority_object_ids
        if self.passage_ids:
            dimensions["passage_id"] = self.passage_ids
        _require_scope(self.envelope, ToolScope.from_dimensions(**dimensions))

    def payload_value(self) -> dict[str, object]:
        return {
            "collision_namespace": self.collision_namespace,
            "collision_key_digest": self.collision_key_digest,
            "authority_object_ids": list(self.authority_object_ids),
            "passage_ids": list(self.passage_ids),
            "require_current_collision": self.require_current_collision,
        }

    @property
    def request_digest(self) -> str:
        return _request_digest(self.SCHEMA_VERSION, self.envelope, self.payload_value())

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "CollisionHydrationLookupToolRequest":
        _strict_keys(
            value,
            required={"schema_version", "envelope", "collision_namespace", "collision_key_digest", "authority_object_ids", "passage_ids", "require_current_collision"},
            field="collision_hydration_tool_request",
        )
        if value["schema_version"] != cls.SCHEMA_VERSION:
            raise NamedToolContractError("collision/hydration schema version is not accepted")
        if not isinstance(value["envelope"], dict):
            raise NamedToolContractError("collision/hydration envelope must be an object")
        if not isinstance(value["collision_namespace"], str) or not isinstance(value["collision_key_digest"], str):
            raise NamedToolContractError("collision fields must be text")
        if not isinstance(value["authority_object_ids"], list) or not isinstance(value["passage_ids"], list):
            raise NamedToolContractError("collision authority/passage fields must be lists")
        return cls(
            envelope=NamedToolEnvelope.from_mapping(value["envelope"]),
            collision_namespace=value["collision_namespace"],
            collision_key_digest=value["collision_key_digest"],
            authority_object_ids=tuple(value["authority_object_ids"]),
            passage_ids=tuple(value["passage_ids"]),
            require_current_collision=value["require_current_collision"],
        )


@dataclass(frozen=True, slots=True)
class SourceRevisionImpactLookupToolRequest:
    envelope: NamedToolEnvelope
    source_id: str
    revision_id: str | None
    window_start: str
    window_end: str
    lineage_depth: int
    include_superseded: bool

    SCHEMA_VERSION = "newsroom.increment5.named-tool.source-revision-impact.v1"

    def __post_init__(self) -> None:
        if self.envelope.tool_id is not NamedToolId.BOUNDED_SOURCE_REVISION_IMPACT_LOOKUP:
            raise NamedToolContractError("envelope tool does not match source impact lookup")
        _require_text(
            self.source_id,
            field="impact_source_id",
            maximum_bytes=NAMED_TOOL_IDENTITY_LIMIT_BYTES,
        )
        if self.revision_id is not None:
            _require_text(
                self.revision_id,
                field="impact_revision_id",
                maximum_bytes=NAMED_TOOL_IDENTITY_LIMIT_BYTES,
            )
        start = _parse_utc(self.window_start, field="impact_window_start")
        end = _parse_utc(self.window_end, field="impact_window_end")
        if start >= end:
            raise NamedToolContractError("impact window must be increasing")
        if (end - start).total_seconds() > NAMED_TOOL_DATE_WINDOW_SECONDS:
            raise NamedToolContractError("impact window exceeds the fixed bound")
        _require_int_range(
            self.lineage_depth,
            field="impact_lineage_depth",
            minimum=1,
            maximum=NAMED_TOOL_GRAPH_DEPTH_LIMIT,
        )
        if not isinstance(self.include_superseded, bool):
            raise NamedToolContractError("include_superseded must be boolean")
        dimensions: dict[str, Sequence[str]] = {"source_id": (self.source_id,)}
        if self.revision_id is not None:
            dimensions["revision_id"] = (self.revision_id,)
        _require_scope(self.envelope, ToolScope.from_dimensions(**dimensions))

    def payload_value(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "revision_id": self.revision_id,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "lineage_depth": self.lineage_depth,
            "include_superseded": self.include_superseded,
        }

    @property
    def request_digest(self) -> str:
        return _request_digest(self.SCHEMA_VERSION, self.envelope, self.payload_value())

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "SourceRevisionImpactLookupToolRequest":
        _strict_keys(
            value,
            required={"schema_version", "envelope", "source_id", "revision_id", "window_start", "window_end", "lineage_depth", "include_superseded"},
            field="source_revision_impact_request",
        )
        if value["schema_version"] != cls.SCHEMA_VERSION:
            raise NamedToolContractError("source-impact schema version is not accepted")
        if not isinstance(value["envelope"], dict):
            raise NamedToolContractError("source-impact envelope must be an object")
        for name in ("source_id", "window_start", "window_end"):
            if not isinstance(value[name], str):
                raise NamedToolContractError(f"{name} must be text")
        if value["revision_id"] is not None and not isinstance(value["revision_id"], str):
            raise NamedToolContractError("revision_id must be text or null")
        return cls(
            envelope=NamedToolEnvelope.from_mapping(value["envelope"]),
            source_id=value["source_id"],
            revision_id=value["revision_id"],
            window_start=value["window_start"],
            window_end=value["window_end"],
            lineage_depth=value["lineage_depth"],
            include_superseded=value["include_superseded"],
        )


NamedToolRequest: TypeAlias = (
    ExactAuthorityLookupToolRequest
    | FullTextRetrievalToolRequest
    | FixedPointVectorRetrievalToolRequest
    | AdmittedGraphTraversalToolRequest
    | CollisionHydrationLookupToolRequest
    | SourceRevisionImpactLookupToolRequest
)

_REQUEST_DECODERS = {
    ExactAuthorityLookupToolRequest.SCHEMA_VERSION: ExactAuthorityLookupToolRequest.from_mapping,
    FullTextRetrievalToolRequest.SCHEMA_VERSION: FullTextRetrievalToolRequest.from_mapping,
    FixedPointVectorRetrievalToolRequest.SCHEMA_VERSION: FixedPointVectorRetrievalToolRequest.from_mapping,
    AdmittedGraphTraversalToolRequest.SCHEMA_VERSION: AdmittedGraphTraversalToolRequest.from_mapping,
    CollisionHydrationLookupToolRequest.SCHEMA_VERSION: CollisionHydrationLookupToolRequest.from_mapping,
    SourceRevisionImpactLookupToolRequest.SCHEMA_VERSION: SourceRevisionImpactLookupToolRequest.from_mapping,
}


def decode_named_tool_request(value: Mapping[str, object]) -> NamedToolRequest:
    schema = value.get("schema_version")
    if not isinstance(schema, str) or schema not in _REQUEST_DECODERS:
        raise NamedToolContractError("named-tool request schema is not accepted")
    return _REQUEST_DECODERS[schema](value)


def decode_named_tool_json(raw: bytes) -> NamedToolRequest:
    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise NamedToolContractError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    if not isinstance(raw, bytes) or len(raw) > NAMED_TOOL_RESPONSE_LIMIT_BYTES:
        raise NamedToolContractError("named-tool request bytes exceed the fixed bound")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=object_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NamedToolContractError("named-tool request is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise NamedToolContractError("named-tool request root must be an object")
    return decode_named_tool_request(value)


NAMED_TOOL_CONTRACT_DIGEST = _digest_bytes(
    _canonical_json_bytes(
        {
            "schema_version": "newsroom.increment5.named-tool-contract.v1",
            "tool_ids": [item.value for item in NamedToolId],
            "purposes": [item.value for item in NamedToolPurpose],
            "languages": [item.value for item in NamedToolLanguage],
            "permitted_purposes": {
                tool.value: sorted(purpose.value for purpose in purposes)
                for tool, purposes in PERMITTED_PURPOSES.items()
            },
            "bounds": {
                "result_limit": NAMED_TOOL_RESULT_LIMIT,
                "timeout_limit_ms": NAMED_TOOL_TIMEOUT_LIMIT_MS,
                "response_limit_bytes": NAMED_TOOL_RESPONSE_LIMIT_BYTES,
                "date_window_seconds": NAMED_TOOL_DATE_WINDOW_SECONDS,
                "graph_depth_limit": NAMED_TOOL_GRAPH_DEPTH_LIMIT,
                "graph_fanout_limit": NAMED_TOOL_GRAPH_FANOUT_LIMIT,
                "query_text_limit_bytes": NAMED_TOOL_QUERY_TEXT_LIMIT_BYTES,
                "external_call_limit": NAMED_TOOL_EXTERNAL_CALL_LIMIT,
                "provider_spend_limit_micros": NAMED_TOOL_PROVIDER_SPEND_LIMIT_MICROS,
            },
        }
    )
)


__all__ = [
    "NAMED_TOOL_CONTRACT_DIGEST",
    "NAMED_TOOL_DATE_WINDOW_SECONDS",
    "NAMED_TOOL_EXTERNAL_CALL_LIMIT",
    "NAMED_TOOL_GRAPH_DEPTH_LIMIT",
    "NAMED_TOOL_GRAPH_FANOUT_LIMIT",
    "NAMED_TOOL_IDENTITY_LIMIT_BYTES",
    "NAMED_TOOL_POLICY_ID",
    "NAMED_TOOL_PROFILE_ID",
    "NAMED_TOOL_PROVIDER_SPEND_LIMIT_MICROS",
    "NAMED_TOOL_QUERY_TEXT_LIMIT_BYTES",
    "NAMED_TOOL_RESPONSE_LIMIT_BYTES",
    "NAMED_TOOL_RESULT_LIMIT",
    "NAMED_TOOL_TIMEOUT_LIMIT_MS",
    "AdmittedGraphTraversalToolRequest",
    "CollisionHydrationLookupToolRequest",
    "ExactAuthorityLookupToolRequest",
    "ExactLookupKind",
    "FixedPointVectorRetrievalToolRequest",
    "FullTextRetrievalToolRequest",
    "NamedToolContractError",
    "NamedToolEnvelope",
    "NamedToolId",
    "NamedToolLanguage",
    "NamedToolPurpose",
    "NamedToolRequest",
    "PERMITTED_PURPOSES",
    "SourceRevisionImpactLookupToolRequest",
    "ToolScope",
    "ToolScopeClaim",
    "decode_named_tool_json",
    "decode_named_tool_request",
]
