"""Strict, effect-free bounded Search contracts for Increment 7B1.

These records describe approved fixture/replay intent and attributed observations.
They provide no provider client, credentials, network, spend, scheduling, evidence,
Signal, Lead, Candidate, fallback or recursive-search authority.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Self
from urllib.parse import urlsplit

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)

SEARCH_PURPOSE = "newsroom.increment7.search-purpose.v1"
SEARCH_REQUEST = "newsroom.increment7.search-request.v1"
SEARCH_ATTEMPT = "newsroom.increment7.search-attempt.v1"
SEARCH_OUTCOME = "newsroom.increment7.search-outcome.v1"
SEARCH_RESULT_REFERENCE = "newsroom.increment7.search-result-reference.v1"
SEARCH_REVIEW_DECISION = "newsroom.increment7.search-review-decision.v1"
SEARCH_AMPLIFICATION_BUDGET = "HARD_GROSS_PREAUTHORISED_LIMITS"
SEARCH_QUERY_PRIVACY = "PUBLIC_MINIMISED_VERSIONED_CLASSIFICATION"
MAX_SEARCH_CANONICAL_BYTES = 1_048_576
MAX_QUERY_BYTES = 4_096
MAX_TEXT_BYTES = 2_048
MAX_SEQUENCE = 64

_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,255}\Z")
_LANGUAGE = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,3}\Z")
_UTC = re.compile(
    r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{6}Z\Z"
)
_QUERY_WORD = re.compile(r"[A-Za-z0-9]+")
_BROAD_SCOPE_WORDS = frozenset(
    {
        "ai",
        "asia",
        "business",
        "china",
        "crypto",
        "economy",
        "education",
        "entertainment",
        "europe",
        "finance",
        "global",
        "health",
        "hong",
        "kong",
        "politics",
        "science",
        "sport",
        "sports",
        "technology",
        "tech",
        "uk",
        "united",
        "kingdom",
        "us",
        "world",
    }
)
_BROAD_NEWS_WORDS = frozenset(
    {"breaking", "headlines", "latest", "news", "stories", "today", "updates"}
)


class SearchContractError(ValueError):
    """Untrusted Search values or bytes failed the exact v1 contract."""


class SearchPurposeKind(StrEnum):
    PROSPECTIVE_OUTER_RADAR = "PROSPECTIVE_OUTER_RADAR"
    PROSPECTIVE_RECALL_AUDIT = "PROSPECTIVE_RECALL_AUDIT"
    COVERAGE_GAP_INVESTIGATION = "COVERAGE_GAP_INVESTIGATION"
    MISSED_PLANNED_OCCURRENCE_RECOVERY = "MISSED_PLANNED_OCCURRENCE_RECOVERY"
    SUPPLEMENTAL_DISCOVERY = "SUPPLEMENTAL_DISCOVERY"
    SOURCE_OUTAGE_CONTINGENCY = "SOURCE_OUTAGE_CONTINGENCY"
    MANUAL_RESEARCH = "MANUAL_RESEARCH"


class SearchQueryPrivacy(StrEnum):
    PUBLIC_ONLY = "PUBLIC_ONLY"
    PUBLIC_SENSITIVE_POLICY_APPROVED = "PUBLIC_SENSITIVE_POLICY_APPROVED"
    AGGREGATED_NON_IDENTIFYING = "AGGREGATED_NON_IDENTIFYING"


class SearchDownstreamRoute(StrEnum):
    NO_WORK = "NO_WORK"
    PUBLISHER_SOURCE_CHECK = "PUBLISHER_SOURCE_CHECK"
    SEARCH_CHANNEL_SIGNAL = "SEARCH_CHANNEL_SIGNAL"
    EXISTING_EDITORIAL_RECORD = "EXISTING_EDITORIAL_RECORD"
    COVERAGE_AUDIT = "COVERAGE_AUDIT"
    RIGHTS_SOURCE_OPERATIONAL_FOLLOW_UP = "RIGHTS_SOURCE_OPERATIONAL_FOLLOW_UP"


class SearchOutcomeKind(StrEnum):
    SUCCESS_ZERO_RESULTS = "SUCCESS_ZERO_RESULTS"
    SUCCESS_RESULTS = "SUCCESS_RESULTS"
    SUCCESS_PARTIAL_TRUNCATED = "SUCCESS_PARTIAL_TRUNCATED"
    PROVIDER_ALTERED_QUERY = "PROVIDER_ALTERED_QUERY"
    RATE_LIMITED = "RATE_LIMITED"
    BUDGET_BLOCKED = "BUDGET_BLOCKED"
    RIGHTS_OR_PRIVACY_BLOCKED = "RIGHTS_OR_PRIVACY_BLOCKED"
    AUTHENTICATION_OR_CONFIGURATION_FAILURE = "AUTHENTICATION_OR_CONFIGURATION_FAILURE"
    PROVIDER_OR_TRANSPORT_FAILURE = "PROVIDER_OR_TRANSPORT_FAILURE"
    CANCELLED_OR_SUPERSEDED = "CANCELLED_OR_SUPERSEDED"


class SearchReviewAction(StrEnum):
    NO_WORK = "NO_WORK"
    CREATE_PUBLISHER_SOURCE_CHECK = "CREATE_PUBLISHER_SOURCE_CHECK"
    CREATE_SEARCH_CHANNEL_SIGNAL = "CREATE_SEARCH_CHANNEL_SIGNAL"
    RELATE_EXISTING_EDITORIAL_RECORD = "RELATE_EXISTING_EDITORIAL_RECORD"
    SUPPORT_COVERAGE_GAP_REVIEW = "SUPPORT_COVERAGE_GAP_REVIEW"
    QUERY_OR_PROVIDER_NOISE = "QUERY_OR_PROVIDER_NOISE"
    RIGHTS_SOURCE_OPERATIONAL_FOLLOW_UP = "RIGHTS_SOURCE_OPERATIONAL_FOLLOW_UP"


class SearchResultRetention(StrEnum):
    POINTER_ONLY = "POINTER_ONLY"
    ATTRIBUTED_METADATA = "ATTRIBUTED_METADATA"
    RIGHTS_LIMITED_SNIPPET = "RIGHTS_LIMITED_SNIPPET"


class _NoEffect:
    authorises_external_effect = False
    authorises_provider = False
    authorises_credentials = False
    authorises_egress = False
    authorises_spend = False
    authorises_schedule = False
    authorises_fallback = False
    authorises_recursive_search = False
    authorises_underlying_retrieval = False
    authorises_model_submission = False
    authorises_evidence = False
    authorises_publication = False
    creates_signal = False
    creates_lead = False
    creates_candidate = False
    production_activation_authorised = False


def _text(value: object, field: str, maximum: int = MAX_TEXT_BYTES) -> str:
    try:
        size = len(value.encode()) if type(value) is str else 0
    except UnicodeError as exc:
        raise SearchContractError(f"{field} must be canonical text") from exc
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or size > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise SearchContractError(f"{field} must be canonical text")
    return value


def _token(value: object, field: str) -> str:
    value = _text(value, field, 256)
    if _TOKEN.fullmatch(value) is None:
        raise SearchContractError(f"{field} must be a canonical token")
    return value


def _uuid(value: object, field: str) -> str:
    if type(value) is not str or _UUID.fullmatch(value) is None:
        raise SearchContractError(f"{field} must be a canonical UUID")
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError
    except ValueError as exc:
        raise SearchContractError(f"{field} must be a canonical UUID") from exc
    return value


def _digest(value: object, field: str) -> str:
    try:
        return validate_sha256_digest(value, field=field)
    except (CanonicalizationError, TypeError, ValueError) as exc:
        raise SearchContractError(f"{field} must be a SHA-256 digest") from exc


def _timestamp(value: object, field: str) -> str:
    value = _text(value, field, 27)
    if _UTC.fullmatch(value) is None:
        raise SearchContractError(f"{field} must be an exact UTC timestamp")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise SearchContractError(f"{field} must be an exact UTC timestamp") from exc
    return value


def _seconds_between(start: str, end: str) -> float:
    parsed_start = datetime.strptime(start, "%Y-%m-%dT%H:%M:%S.%fZ")
    parsed_end = datetime.strptime(end, "%Y-%m-%dT%H:%M:%S.%fZ")
    return (parsed_end - parsed_start).total_seconds()


def _is_generic_firehose(query: str) -> bool:
    words = tuple(word.casefold() for word in _QUERY_WORD.findall(query))
    has_specific_syntax = any(
        marker in query for marker in ('"', "site:", "domain:", "intitle:")
    ) or any(character.isdigit() for character in query)
    broad_only = bool(words) and set(words).issubset(
        _BROAD_SCOPE_WORDS | _BROAD_NEWS_WORDS
    )
    category_firehose = (
        bool(words)
        and len(words) <= 5
        and words[-1] in _BROAD_NEWS_WORDS
        and any(word in _BROAD_SCOPE_WORDS for word in words[:-1])
    )
    return not has_specific_syntax and (broad_only or category_firehose)


def _enum[T: StrEnum](kind: type[T], value: object, field: str) -> T:
    if type(value) is not str and type(value) is not kind:
        raise SearchContractError(f"{field} differs")
    try:
        return kind(value)
    except ValueError as exc:
        raise SearchContractError(f"{field} differs") from exc


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= 9_007_199_254_740_991:
        raise SearchContractError(f"{field} must be a bounded integer")
    return value


def _strings(
    value: object,
    field: str,
    *,
    maximum: int = MAX_SEQUENCE,
    required: bool = False,
    validator=_text,
) -> tuple[str, ...]:
    if (
        type(value) not in (list, tuple)
        or len(value) > maximum
        or (required and not value)
    ):
        raise SearchContractError(f"{field} must be a bounded array")
    result = tuple(validator(item, field) for item in value)
    if tuple(sorted(set(result))) != result:
        raise SearchContractError(f"{field} must be unique and sorted")
    return result


def _ordered_digests(value: object, field: str) -> tuple[str, ...]:
    if type(value) not in (list, tuple) or not value or len(value) > MAX_SEQUENCE:
        raise SearchContractError(f"{field} must be a bounded array")
    result = tuple(_digest(item, field) for item in value)
    if len(set(result)) != len(result):
        raise SearchContractError(f"{field} must be unique")
    return result


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SearchContractError(f"duplicate object name: {key}")
        result[key] = value
    return result


def _document(raw: bytes, schema: str, fields: tuple[str, ...]) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_SEARCH_CANONICAL_BYTES:
        raise SearchContractError("Search bytes are not bounded")
    try:
        value = json.loads(raw.decode(), object_pairs_hook=_pairs)
        canonical = canonical_json_bytes(value)
    except SearchContractError:
        raise
    except (
        UnicodeError,
        json.JSONDecodeError,
        CanonicalizationError,
        RecursionError,
        ValueError,
    ) as exc:
        raise SearchContractError("Search bytes are not canonical JSON") from exc
    if type(value) is not dict or raw != canonical:
        raise SearchContractError("Search bytes are not exact canonical JSON")
    if tuple(value) != tuple(sorted(fields)) or value.get("schema_version") != schema:
        raise SearchContractError("Search record fields or schema differ")
    return value


def _dict(record: object, fields: tuple[str, ...]) -> dict[str, object]:
    result: dict[str, object] = {}
    for field in fields:
        value = getattr(record, field)
        if isinstance(value, StrEnum):
            value = value.value
        elif isinstance(value, SearchLimits):
            value = value.to_dict()
        elif isinstance(value, tuple):
            value = [
                item.value if isinstance(item, StrEnum) else item for item in value
            ]
        result[field] = value
    return result


@dataclass(frozen=True, slots=True)
class SearchLimits(_NoEffect):
    max_results: int
    max_pages: int
    max_query_variants: int
    max_languages: int
    max_retries: int
    max_branches: int
    max_provider_calls: int
    max_downstream_work_items: int
    max_time_range_seconds: int
    max_elapsed_seconds: int
    max_concurrent_attempts: int
    max_gross_cost_microunits: int

    def __post_init__(self) -> None:
        for field in self.__dataclass_fields__:
            _integer(getattr(self, field), field, minimum=0)
        if (
            min(
                self.max_results,
                self.max_pages,
                self.max_query_variants,
                self.max_languages,
                self.max_provider_calls,
                self.max_time_range_seconds,
                self.max_elapsed_seconds,
                self.max_concurrent_attempts,
            )
            < 1
            or self.max_pages > self.max_provider_calls
            or self.max_languages > self.max_query_variants
            or self.max_retries + 1 > self.max_provider_calls
            or self.max_branches + 1 > self.max_provider_calls
        ):
            raise SearchContractError("Search amplification limits are inconsistent")

    def to_dict(self) -> dict[str, int]:
        return {
            field: getattr(self, field) for field in sorted(self.__dataclass_fields__)
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        fields = tuple(sorted(cls.__dataclass_fields__))
        if type(value) is not dict or tuple(value) != fields:
            raise SearchContractError("Search limits fields differ")
        return cls(**value)  # type: ignore[arg-type]


_PURPOSE_FIELDS = (
    "schema_version",
    "purpose_id",
    "purpose_kind",
    "authorised_trigger_kinds",
    "permitted_coverage",
    "query_privacy",
    "budget_class",
    "allowed_downstream_routes",
    "rights_policy_version",
    "governing_policy_digests",
    "created_at",
)


@dataclass(frozen=True, slots=True)
class SearchPurpose(_NoEffect):
    purpose_id: str
    purpose_kind: SearchPurposeKind
    authorised_trigger_kinds: tuple[str, ...]
    permitted_coverage: tuple[str, ...]
    query_privacy: SearchQueryPrivacy
    budget_class: SearchPurposeKind
    allowed_downstream_routes: tuple[SearchDownstreamRoute, ...]
    rights_policy_version: str
    governing_policy_digests: tuple[str, ...]
    created_at: str
    schema_version: str = SEARCH_PURPOSE

    def __post_init__(self) -> None:
        if self.schema_version != SEARCH_PURPOSE:
            raise SearchContractError("Search Purpose schema differs")
        _uuid(self.purpose_id, "purpose_id")
        object.__setattr__(
            self,
            "purpose_kind",
            _enum(SearchPurposeKind, self.purpose_kind, "purpose_kind"),
        )
        object.__setattr__(
            self,
            "budget_class",
            _enum(SearchPurposeKind, self.budget_class, "budget_class"),
        )
        if self.budget_class is not self.purpose_kind:
            raise SearchContractError(
                "Search budget class must remain purpose-specific"
            )
        object.__setattr__(
            self,
            "authorised_trigger_kinds",
            _strings(
                self.authorised_trigger_kinds,
                "authorised_trigger_kinds",
                required=True,
                validator=_token,
            ),
        )
        object.__setattr__(
            self,
            "permitted_coverage",
            _strings(self.permitted_coverage, "permitted_coverage", required=True),
        )
        object.__setattr__(
            self,
            "query_privacy",
            _enum(SearchQueryPrivacy, self.query_privacy, "query_privacy"),
        )
        if (
            type(self.allowed_downstream_routes) is not tuple
            or not self.allowed_downstream_routes
        ):
            raise SearchContractError("allowed_downstream_routes must be bounded")
        routes = tuple(
            _enum(SearchDownstreamRoute, value, "allowed_downstream_routes")
            for value in self.allowed_downstream_routes
        )
        if tuple(sorted(set(routes), key=str)) != routes:
            raise SearchContractError(
                "allowed_downstream_routes must be unique and sorted"
            )
        object.__setattr__(self, "allowed_downstream_routes", routes)
        _token(self.rights_policy_version, "rights_policy_version")
        object.__setattr__(
            self,
            "governing_policy_digests",
            _strings(
                self.governing_policy_digests,
                "governing_policy_digests",
                required=True,
                validator=_digest,
            ),
        )
        _timestamp(self.created_at, "created_at")

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(_dict(self, _PURPOSE_FIELDS))

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        value = _document(raw, SEARCH_PURPOSE, _PURPOSE_FIELDS)
        value["purpose_kind"] = _enum(
            SearchPurposeKind, value["purpose_kind"], "purpose_kind"
        )
        value["budget_class"] = _enum(
            SearchPurposeKind, value["budget_class"], "budget_class"
        )
        value["query_privacy"] = _enum(
            SearchQueryPrivacy, value["query_privacy"], "query_privacy"
        )
        value["allowed_downstream_routes"] = tuple(
            _enum(SearchDownstreamRoute, item, "allowed_downstream_routes")
            for item in value["allowed_downstream_routes"]
        )  # type: ignore[union-attr]
        for field in (
            "authorised_trigger_kinds",
            "permitted_coverage",
            "governing_policy_digests",
        ):
            value[field] = tuple(value[field])  # type: ignore[arg-type]
        result = cls(**value)  # type: ignore[arg-type]
        if result.canonical_bytes != raw:
            raise SearchContractError("Search Purpose replay differs")
        return result


_REQUEST_FIELDS = (
    "schema_version",
    "request_id",
    "purpose_id",
    "purpose_digest",
    "trigger_kind",
    "trigger_reference_digest",
    "requester_identity_digest",
    "provider_id",
    "provider_configuration_digest",
    "query_template_id",
    "query_template_digest",
    "rendered_query",
    "language_tags",
    "geography_bounds",
    "domain_bounds",
    "window_start",
    "window_end",
    "limits",
    "query_privacy",
    "rights_policy_version",
    "budget_reservation_digest",
    "allowed_downstream_routes",
    "context_reference_digest",
    "governing_policy_digests",
    "requested_at",
)


@dataclass(frozen=True, slots=True)
class SearchRequest(_NoEffect):
    request_id: str
    purpose_id: str
    purpose_digest: str
    trigger_kind: str
    trigger_reference_digest: str
    requester_identity_digest: str
    provider_id: str
    provider_configuration_digest: str
    query_template_id: str
    query_template_digest: str
    rendered_query: str
    language_tags: tuple[str, ...]
    geography_bounds: tuple[str, ...]
    domain_bounds: tuple[str, ...]
    window_start: str
    window_end: str
    limits: SearchLimits
    query_privacy: SearchQueryPrivacy
    rights_policy_version: str
    budget_reservation_digest: str
    allowed_downstream_routes: tuple[SearchDownstreamRoute, ...]
    context_reference_digest: str | None
    governing_policy_digests: tuple[str, ...]
    requested_at: str
    schema_version: str = SEARCH_REQUEST

    def __post_init__(self) -> None:
        if self.schema_version != SEARCH_REQUEST:
            raise SearchContractError("Search Request schema differs")
        for field in ("request_id", "purpose_id"):
            _uuid(getattr(self, field), field)
        for field in (
            "purpose_digest",
            "trigger_reference_digest",
            "requester_identity_digest",
            "provider_configuration_digest",
            "query_template_digest",
            "budget_reservation_digest",
        ):
            _digest(getattr(self, field), field)
        _token(self.trigger_kind, "trigger_kind")
        _token(self.provider_id, "provider_id")
        _token(self.query_template_id, "query_template_id")
        query = _text(self.rendered_query, "rendered_query", MAX_QUERY_BYTES)
        if _is_generic_firehose(query):
            raise SearchContractError("generic search firehose is prohibited")
        object.__setattr__(
            self,
            "language_tags",
            _strings(
                self.language_tags,
                "language_tags",
                required=True,
                validator=lambda value, field: _language(value, field),
            ),
        )
        object.__setattr__(
            self,
            "geography_bounds",
            _strings(self.geography_bounds, "geography_bounds"),
        )
        object.__setattr__(self, "domain_bounds", _domains(self.domain_bounds))
        _timestamp(self.window_start, "window_start")
        _timestamp(self.window_end, "window_end")
        if self.window_end <= self.window_start:
            raise SearchContractError("Search Request window must be ordered")
        if type(self.limits) is not SearchLimits:
            raise SearchContractError("Search Request limits differ")
        object.__setattr__(
            self,
            "query_privacy",
            _enum(SearchQueryPrivacy, self.query_privacy, "query_privacy"),
        )
        _token(self.rights_policy_version, "rights_policy_version")
        if (
            type(self.allowed_downstream_routes) is not tuple
            or not self.allowed_downstream_routes
        ):
            raise SearchContractError("Search Request routes are empty")
        routes = tuple(
            _enum(SearchDownstreamRoute, route, "allowed_downstream_routes")
            for route in self.allowed_downstream_routes
        )
        if tuple(sorted(set(routes), key=str)) != routes:
            raise SearchContractError("Search Request routes must be unique and sorted")
        object.__setattr__(self, "allowed_downstream_routes", routes)
        if self.context_reference_digest is not None:
            _digest(self.context_reference_digest, "context_reference_digest")
        object.__setattr__(
            self,
            "governing_policy_digests",
            _strings(
                self.governing_policy_digests,
                "governing_policy_digests",
                required=True,
                validator=_digest,
            ),
        )
        _timestamp(self.requested_at, "requested_at")

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(_dict(self, _REQUEST_FIELDS))

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        value = _document(raw, SEARCH_REQUEST, _REQUEST_FIELDS)
        value["limits"] = SearchLimits.from_dict(value["limits"])
        value["query_privacy"] = _enum(
            SearchQueryPrivacy, value["query_privacy"], "query_privacy"
        )
        value["allowed_downstream_routes"] = tuple(
            _enum(SearchDownstreamRoute, item, "allowed_downstream_routes")
            for item in value["allowed_downstream_routes"]
        )  # type: ignore[union-attr]
        for field in (
            "language_tags",
            "geography_bounds",
            "domain_bounds",
            "governing_policy_digests",
        ):
            value[field] = tuple(value[field])  # type: ignore[arg-type]
        result = cls(**value)  # type: ignore[arg-type]
        if result.canonical_bytes != raw:
            raise SearchContractError("Search Request replay differs")
        return result


def _language(value: object, field: str) -> str:
    value = _text(value, field, 32)
    if _LANGUAGE.fullmatch(value) is None:
        raise SearchContractError(f"{field} must contain canonical language tags")
    return value


def _domains(value: object) -> tuple[str, ...]:
    domains = _strings(
        value, "domain_bounds", validator=lambda item, field: _text(item, field, 253)
    )
    for domain in domains:
        if (
            domain != domain.lower()
            or urlsplit(f"https://{domain}").hostname != domain
            or "." not in domain
        ):
            raise SearchContractError("domain_bounds must contain canonical hosts")
    return domains


_ATTEMPT_FIELDS = (
    "schema_version",
    "attempt_id",
    "request_id",
    "request_digest",
    "attempt_ordinal",
    "provider_id",
    "provider_configuration_digest",
    "rendered_query_digest",
    "variant_ordinal",
    "language_ordinal",
    "page_number",
    "retry_ordinal",
    "branch_ordinal",
    "started_at",
)


@dataclass(frozen=True, slots=True)
class SearchAttempt(_NoEffect):
    attempt_id: str
    request_id: str
    request_digest: str
    attempt_ordinal: int
    provider_id: str
    provider_configuration_digest: str
    rendered_query_digest: str
    variant_ordinal: int
    language_ordinal: int
    page_number: int
    retry_ordinal: int
    branch_ordinal: int
    started_at: str
    schema_version: str = SEARCH_ATTEMPT

    def __post_init__(self) -> None:
        if self.schema_version != SEARCH_ATTEMPT:
            raise SearchContractError("Search Attempt schema differs")
        for field in ("attempt_id", "request_id"):
            _uuid(getattr(self, field), field)
        for field in (
            "request_digest",
            "provider_configuration_digest",
            "rendered_query_digest",
        ):
            _digest(getattr(self, field), field)
        _token(self.provider_id, "provider_id")
        for field in (
            "attempt_ordinal",
            "variant_ordinal",
            "language_ordinal",
            "page_number",
        ):
            _integer(getattr(self, field), field, minimum=1)
        for field in ("retry_ordinal", "branch_ordinal"):
            _integer(getattr(self, field), field)
        _timestamp(self.started_at, "started_at")

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(_dict(self, _ATTEMPT_FIELDS))

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        value = _document(raw, SEARCH_ATTEMPT, _ATTEMPT_FIELDS)
        result = cls(**value)  # type: ignore[arg-type]
        if result.canonical_bytes != raw:
            raise SearchContractError("Search Attempt replay differs")
        return result


_OUTCOME_FIELDS = (
    "schema_version",
    "outcome_id",
    "attempt_id",
    "attempt_digest",
    "outcome_kind",
    "result_count",
    "returned_pages",
    "gross_cost_microunits",
    "provider_altered_query",
    "provider_locale",
    "retry_after_seconds",
    "completed_at",
)


@dataclass(frozen=True, slots=True)
class SearchOutcome(_NoEffect):
    outcome_id: str
    attempt_id: str
    attempt_digest: str
    outcome_kind: SearchOutcomeKind
    result_count: int
    returned_pages: int
    gross_cost_microunits: int
    provider_altered_query: str | None
    provider_locale: str | None
    retry_after_seconds: int | None
    completed_at: str
    schema_version: str = SEARCH_OUTCOME

    def __post_init__(self) -> None:
        if self.schema_version != SEARCH_OUTCOME:
            raise SearchContractError("Search Outcome schema differs")
        for field in ("outcome_id", "attempt_id"):
            _uuid(getattr(self, field), field)
        _digest(self.attempt_digest, "attempt_digest")
        object.__setattr__(
            self,
            "outcome_kind",
            _enum(SearchOutcomeKind, self.outcome_kind, "outcome_kind"),
        )
        for field in ("result_count", "returned_pages", "gross_cost_microunits"):
            _integer(getattr(self, field), field)
        success = self.outcome_kind in {
            SearchOutcomeKind.SUCCESS_ZERO_RESULTS,
            SearchOutcomeKind.SUCCESS_RESULTS,
            SearchOutcomeKind.SUCCESS_PARTIAL_TRUNCATED,
            SearchOutcomeKind.PROVIDER_ALTERED_QUERY,
        }
        if not success and (self.result_count or self.returned_pages):
            raise SearchContractError("blocked or failed Search Outcome has results")
        if (
            self.outcome_kind is SearchOutcomeKind.SUCCESS_ZERO_RESULTS
            and self.result_count != 0
        ):
            raise SearchContractError("zero-result Search Outcome differs")
        if (
            self.outcome_kind
            in {
                SearchOutcomeKind.SUCCESS_RESULTS,
                SearchOutcomeKind.SUCCESS_PARTIAL_TRUNCATED,
            }
            and self.result_count < 1
        ):
            raise SearchContractError("successful Search Outcome lacks results")
        if success and self.result_count > 0 and self.returned_pages < 1:
            raise SearchContractError("successful Search Outcome lacks a returned page")
        altered = self.outcome_kind is SearchOutcomeKind.PROVIDER_ALTERED_QUERY
        if altered != (self.provider_altered_query is not None):
            raise SearchContractError("provider query alteration visibility differs")
        if self.provider_altered_query is not None:
            _text(
                self.provider_altered_query, "provider_altered_query", MAX_QUERY_BYTES
            )
        if self.provider_locale is not None:
            _language(self.provider_locale, "provider_locale")
        rate_limited = self.outcome_kind is SearchOutcomeKind.RATE_LIMITED
        if self.retry_after_seconds is not None:
            _integer(self.retry_after_seconds, "retry_after_seconds", minimum=1)
        if not rate_limited and self.retry_after_seconds is not None:
            raise SearchContractError("retry_after_seconds belongs only to rate limit")
        _timestamp(self.completed_at, "completed_at")

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(_dict(self, _OUTCOME_FIELDS))

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        value = _document(raw, SEARCH_OUTCOME, _OUTCOME_FIELDS)
        value["outcome_kind"] = _enum(
            SearchOutcomeKind, value["outcome_kind"], "outcome_kind"
        )
        result = cls(**value)  # type: ignore[arg-type]
        if result.canonical_bytes != raw:
            raise SearchContractError("Search Outcome replay differs")
        return result


_RESULT_FIELDS = (
    "schema_version",
    "result_reference_id",
    "outcome_id",
    "outcome_digest",
    "provider_id",
    "provider_configuration_digest",
    "provider_result_id",
    "rank",
    "page_number",
    "url",
    "publisher",
    "title",
    "snippet",
    "asserted_date",
    "language",
    "result_type",
    "dependency_signals",
    "retention_class",
    "rights_reference",
    "recorded_at",
)


@dataclass(frozen=True, slots=True)
class SearchResultReference(_NoEffect):
    result_reference_id: str
    outcome_id: str
    outcome_digest: str
    provider_id: str
    provider_configuration_digest: str
    provider_result_id: str | None
    rank: int
    page_number: int
    url: str | None
    publisher: str | None
    title: str | None
    snippet: str | None
    asserted_date: str | None
    language: str | None
    result_type: str | None
    dependency_signals: tuple[str, ...]
    retention_class: SearchResultRetention
    rights_reference: str
    recorded_at: str
    schema_version: str = SEARCH_RESULT_REFERENCE

    def __post_init__(self) -> None:
        if self.schema_version != SEARCH_RESULT_REFERENCE:
            raise SearchContractError("Search Result Reference schema differs")
        for field in ("result_reference_id", "outcome_id"):
            _uuid(getattr(self, field), field)
        for field in ("outcome_digest", "provider_configuration_digest"):
            _digest(getattr(self, field), field)
        _token(self.provider_id, "provider_id")
        if self.provider_result_id is not None:
            _text(self.provider_result_id, "provider_result_id", 512)
        _integer(self.rank, "rank", minimum=1)
        _integer(self.page_number, "page_number", minimum=1)
        if self.url is not None:
            url = _text(self.url, "url", 4_096)
            parts = urlsplit(url)
            if (
                parts.scheme not in {"http", "https"}
                or not parts.hostname
                or parts.username
                or parts.password
                or parts.fragment
            ):
                raise SearchContractError(
                    "Search result URL is not a bounded public pointer"
                )
        for field in ("publisher", "title", "snippet", "asserted_date", "result_type"):
            value = getattr(self, field)
            if value is not None:
                _text(value, field, 8_192 if field == "snippet" else MAX_TEXT_BYTES)
        if self.language is not None:
            _language(self.language, "language")
        object.__setattr__(
            self,
            "dependency_signals",
            _strings(self.dependency_signals, "dependency_signals", validator=_digest),
        )
        object.__setattr__(
            self,
            "retention_class",
            _enum(SearchResultRetention, self.retention_class, "retention_class"),
        )
        if self.retention_class is SearchResultRetention.POINTER_ONLY and any(
            value is not None
            for value in (
                self.publisher,
                self.title,
                self.snippet,
                self.asserted_date,
                self.language,
                self.result_type,
            )
        ):
            raise SearchContractError("pointer-only result retains provider metadata")
        if (
            self.retention_class is not SearchResultRetention.RIGHTS_LIMITED_SNIPPET
            and self.snippet is not None
        ):
            raise SearchContractError("snippet retention class differs")
        _token(self.rights_reference, "rights_reference")
        _timestamp(self.recorded_at, "recorded_at")

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(_dict(self, _RESULT_FIELDS))

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        value = _document(raw, SEARCH_RESULT_REFERENCE, _RESULT_FIELDS)
        value["dependency_signals"] = tuple(value["dependency_signals"])  # type: ignore[arg-type]
        value["retention_class"] = _enum(
            SearchResultRetention, value["retention_class"], "retention_class"
        )
        result = cls(**value)  # type: ignore[arg-type]
        if result.canonical_bytes != raw:
            raise SearchContractError("Search Result Reference replay differs")
        return result


_REVIEW_FIELDS = (
    "schema_version",
    "review_decision_id",
    "result_reference_ids",
    "result_reference_digests",
    "action",
    "work_reference_digest",
    "reviewer_identity_digest",
    "reason_codes",
    "decided_at",
)


@dataclass(frozen=True, slots=True)
class SearchReviewDecision(_NoEffect):
    review_decision_id: str
    result_reference_ids: tuple[str, ...]
    result_reference_digests: tuple[str, ...]
    action: SearchReviewAction
    work_reference_digest: str | None
    reviewer_identity_digest: str
    reason_codes: tuple[str, ...]
    decided_at: str
    schema_version: str = SEARCH_REVIEW_DECISION

    def __post_init__(self) -> None:
        if self.schema_version != SEARCH_REVIEW_DECISION:
            raise SearchContractError("Search Review Decision schema differs")
        _uuid(self.review_decision_id, "review_decision_id")
        object.__setattr__(
            self,
            "result_reference_ids",
            _strings(
                self.result_reference_ids,
                "result_reference_ids",
                required=True,
                validator=_uuid,
            ),
        )
        object.__setattr__(
            self,
            "result_reference_digests",
            _ordered_digests(
                self.result_reference_digests,
                "result_reference_digests",
            ),
        )
        if len(self.result_reference_ids) != len(self.result_reference_digests):
            raise SearchContractError("Search review result bindings differ")
        object.__setattr__(
            self, "action", _enum(SearchReviewAction, self.action, "action")
        )
        needs_work = self.action not in {
            SearchReviewAction.NO_WORK,
            SearchReviewAction.QUERY_OR_PROVIDER_NOISE,
        }
        if needs_work != (self.work_reference_digest is not None):
            raise SearchContractError("Search review work binding differs")
        if self.work_reference_digest is not None:
            _digest(self.work_reference_digest, "work_reference_digest")
        _digest(self.reviewer_identity_digest, "reviewer_identity_digest")
        object.__setattr__(
            self,
            "reason_codes",
            _strings(
                self.reason_codes, "reason_codes", required=True, validator=_token
            ),
        )
        _timestamp(self.decided_at, "decided_at")

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(_dict(self, _REVIEW_FIELDS))

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        value = _document(raw, SEARCH_REVIEW_DECISION, _REVIEW_FIELDS)
        value["action"] = _enum(SearchReviewAction, value["action"], "action")
        for field in (
            "result_reference_ids",
            "result_reference_digests",
            "reason_codes",
        ):
            value[field] = tuple(value[field])  # type: ignore[arg-type]
        result = cls(**value)  # type: ignore[arg-type]
        if result.canonical_bytes != raw:
            raise SearchContractError("Search Review Decision replay differs")
        return result


def validate_search_request(purpose: SearchPurpose, request: SearchRequest) -> None:
    if type(purpose) is not SearchPurpose or type(request) is not SearchRequest:
        raise SearchContractError("Search Purpose and Request must be exact records")
    if (
        request.purpose_id != purpose.purpose_id
        or request.purpose_digest != purpose.digest
        or request.trigger_kind not in purpose.authorised_trigger_kinds
        or request.query_privacy is not purpose.query_privacy
        or request.rights_policy_version != purpose.rights_policy_version
        or not set(request.allowed_downstream_routes).issubset(
            purpose.allowed_downstream_routes
        )
        or request.requested_at < purpose.created_at
        or (
            request.window_end > request.window_start
            and _window_seconds(request) > request.limits.max_time_range_seconds
        )
    ):
        raise SearchContractError("Search Request exceeds its exact Purpose")
    needs_context = purpose.purpose_kind in {
        SearchPurposeKind.PROSPECTIVE_RECALL_AUDIT,
        SearchPurposeKind.COVERAGE_GAP_INVESTIGATION,
        SearchPurposeKind.MISSED_PLANNED_OCCURRENCE_RECOVERY,
        SearchPurposeKind.SUPPLEMENTAL_DISCOVERY,
        SearchPurposeKind.SOURCE_OUTAGE_CONTINGENCY,
    }
    if needs_context != (request.context_reference_digest is not None):
        raise SearchContractError("Search Purpose context binding differs")
    if (
        purpose.purpose_kind is SearchPurposeKind.PROSPECTIVE_RECALL_AUDIT
        and SearchDownstreamRoute.COVERAGE_AUDIT
        not in request.allowed_downstream_routes
    ):
        raise SearchContractError("prospective audit lacks pre-registered audit route")


def _window_seconds(request: SearchRequest) -> float:
    start = datetime.strptime(request.window_start, "%Y-%m-%dT%H:%M:%S.%fZ")
    end = datetime.strptime(request.window_end, "%Y-%m-%dT%H:%M:%S.%fZ")
    return (end - start).total_seconds()


def validate_search_attempt(request: SearchRequest, attempt: SearchAttempt) -> None:
    if type(request) is not SearchRequest or type(attempt) is not SearchAttempt:
        raise SearchContractError("Search Request and Attempt must be exact records")
    limits = request.limits
    if (
        attempt.request_id != request.request_id
        or attempt.request_digest != request.digest
        or attempt.provider_id != request.provider_id
        or attempt.provider_configuration_digest
        != request.provider_configuration_digest
        or attempt.rendered_query_digest
        != digest_bytes(request.rendered_query.encode())
        or attempt.attempt_ordinal > limits.max_provider_calls
        or attempt.variant_ordinal > limits.max_query_variants
        or attempt.language_ordinal > limits.max_languages
        or attempt.page_number > limits.max_pages
        or attempt.retry_ordinal > limits.max_retries
        or attempt.branch_ordinal > limits.max_branches
        or attempt.started_at < request.requested_at
        or _seconds_between(request.requested_at, attempt.started_at)
        > limits.max_elapsed_seconds
    ):
        raise SearchContractError("Search Attempt exceeds its exact Request")


def validate_search_outcome(
    attempt: SearchAttempt, outcome: SearchOutcome, request: SearchRequest
) -> None:
    if any(
        type(value) is not kind
        for value, kind in (
            (attempt, SearchAttempt),
            (outcome, SearchOutcome),
            (request, SearchRequest),
        )
    ):
        raise SearchContractError("Search Outcome binding requires exact records")
    validate_search_attempt(request, attempt)
    if (
        outcome.attempt_id != attempt.attempt_id
        or outcome.attempt_digest != attempt.digest
        or outcome.completed_at < attempt.started_at
        or _seconds_between(request.requested_at, outcome.completed_at)
        > request.limits.max_elapsed_seconds
        or outcome.result_count > request.limits.max_results
        or outcome.returned_pages > request.limits.max_pages
        or outcome.gross_cost_microunits > request.limits.max_gross_cost_microunits
    ):
        raise SearchContractError("Search Outcome exceeds its exact Attempt or budget")


def validate_search_result(
    outcome: SearchOutcome, result: SearchResultReference, attempt: SearchAttempt
) -> None:
    if any(
        type(value) is not kind
        for value, kind in (
            (outcome, SearchOutcome),
            (result, SearchResultReference),
            (attempt, SearchAttempt),
        )
    ):
        raise SearchContractError("Search Result binding requires exact records")
    if (
        outcome.outcome_kind
        not in {
            SearchOutcomeKind.SUCCESS_RESULTS,
            SearchOutcomeKind.SUCCESS_PARTIAL_TRUNCATED,
            SearchOutcomeKind.PROVIDER_ALTERED_QUERY,
        }
        or outcome.attempt_id != attempt.attempt_id
        or outcome.attempt_digest != attempt.digest
        or result.outcome_id != outcome.outcome_id
        or result.outcome_digest != outcome.digest
        or result.provider_id != attempt.provider_id
        or result.provider_configuration_digest != attempt.provider_configuration_digest
        or result.rank > outcome.result_count
        or result.page_number > outcome.returned_pages
        or result.recorded_at < outcome.completed_at
    ):
        raise SearchContractError("Search Result Reference exceeds its exact Outcome")


def validate_search_review(
    results: tuple[SearchResultReference, ...], decision: SearchReviewDecision
) -> None:
    if (
        type(results) is not tuple
        or not results
        or any(type(item) is not SearchResultReference for item in results)
        or type(decision) is not SearchReviewDecision
    ):
        raise SearchContractError("Search review binding requires exact records")
    ordered = tuple(sorted(results, key=lambda item: item.result_reference_id))
    if (
        results != ordered
        or tuple(item.result_reference_id for item in results)
        != decision.result_reference_ids
        or tuple(item.digest for item in results) != decision.result_reference_digests
        or decision.decided_at < max(item.recorded_at for item in results)
    ):
        raise SearchContractError("Search Review Decision result binding differs")


__all__ = [
    "MAX_SEARCH_CANONICAL_BYTES",
    "SEARCH_AMPLIFICATION_BUDGET",
    "SEARCH_ATTEMPT",
    "SEARCH_OUTCOME",
    "SEARCH_PURPOSE",
    "SEARCH_QUERY_PRIVACY",
    "SEARCH_REQUEST",
    "SEARCH_RESULT_REFERENCE",
    "SEARCH_REVIEW_DECISION",
    "SearchAttempt",
    "SearchContractError",
    "SearchDownstreamRoute",
    "SearchLimits",
    "SearchOutcome",
    "SearchOutcomeKind",
    "SearchPurpose",
    "SearchPurposeKind",
    "SearchQueryPrivacy",
    "SearchRequest",
    "SearchResultReference",
    "SearchResultRetention",
    "SearchReviewAction",
    "SearchReviewDecision",
    "validate_search_attempt",
    "validate_search_outcome",
    "validate_search_request",
    "validate_search_result",
    "validate_search_review",
]
