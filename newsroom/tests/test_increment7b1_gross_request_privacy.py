from __future__ import annotations

import json
import uuid
from dataclasses import replace

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment7.search import (
    SEARCH_AMPLIFICATION_BUDGET,
    SEARCH_QUERY_PRIVACY,
    SearchAttempt,
    SearchContractError,
    SearchDownstreamRoute,
    SearchLimits,
    SearchOutcome,
    SearchOutcomeKind,
    SearchPurpose,
    SearchPurposeKind,
    SearchQueryPrivacy,
    SearchRequest,
    SearchResultReference,
    SearchResultRetention,
    SearchReviewAction,
    SearchReviewDecision,
    validate_search_attempt,
    validate_search_outcome,
    validate_search_request,
    validate_search_result,
    validate_search_review,
)

_AT = "2026-08-14T00:00:00.000000Z"
_D = "sha256:" + "a" * 64


def _id(value: int) -> str:
    return str(uuid.UUID(int=value, version=4))


def _limits() -> SearchLimits:
    return SearchLimits(20, 2, 3, 2, 1, 1, 4, 5, 86_400, 60, 1, 50_000)


def _purpose(
    kind: SearchPurposeKind = SearchPurposeKind.PROSPECTIVE_RECALL_AUDIT,
) -> SearchPurpose:
    routes = (
        (SearchDownstreamRoute.COVERAGE_AUDIT, SearchDownstreamRoute.NO_WORK)
        if kind is SearchPurposeKind.PROSPECTIVE_RECALL_AUDIT
        else (
            SearchDownstreamRoute.NO_WORK,
            SearchDownstreamRoute.PUBLISHER_SOURCE_CHECK,
        )
    )
    return SearchPurpose(
        _id(1),
        kind,
        ("OWNER_APPROVED",),
        ("UK:PUBLIC_POLICY",),
        SearchQueryPrivacy.PUBLIC_ONLY,
        kind,
        tuple(sorted(routes, key=str)),
        "rights-v1",
        (_D,),
        _AT,
    )


def _request(purpose: SearchPurpose | None = None, **changes: object) -> SearchRequest:
    purpose = purpose or _purpose()
    values: dict[str, object] = {
        "request_id": _id(2),
        "purpose_id": purpose.purpose_id,
        "purpose_digest": purpose.digest,
        "trigger_kind": "OWNER_APPROVED",
        "trigger_reference_digest": "sha256:" + "b" * 64,
        "requester_identity_digest": "sha256:" + "c" * 64,
        "provider_id": "fixture-provider",
        "provider_configuration_digest": "sha256:" + "d" * 64,
        "query_template_id": "recall-audit-v1",
        "query_template_digest": "sha256:" + "e" * 64,
        "rendered_query": 'site:gov.uk "policy decision"',
        "language_tags": ("en-GB",),
        "geography_bounds": ("United Kingdom",),
        "domain_bounds": ("gov.uk",),
        "window_start": "2026-08-13T00:00:00.000000Z",
        "window_end": _AT,
        "limits": _limits(),
        "query_privacy": purpose.query_privacy,
        "rights_policy_version": purpose.rights_policy_version,
        "budget_reservation_digest": "sha256:" + "f" * 64,
        "allowed_downstream_routes": (SearchDownstreamRoute.COVERAGE_AUDIT,),
        "coverage_basis": purpose.permitted_coverage,
        "context_reference_digest": "sha256:" + "1" * 64,
        "governing_policy_digests": (_D,),
        "requested_at": _AT,
    }
    values.update(changes)
    return SearchRequest(**values)  # type: ignore[arg-type]


def _attempt(request: SearchRequest) -> SearchAttempt:
    return SearchAttempt(
        _id(3),
        request.request_id,
        request.digest,
        1,
        request.provider_id,
        request.provider_configuration_digest,
        digest_bytes(request.rendered_query.encode()),
        1,
        1,
        1,
        0,
        0,
        _AT,
    )


def _outcome(attempt: SearchAttempt, **changes: object) -> SearchOutcome:
    values: dict[str, object] = {
        "outcome_id": _id(4),
        "attempt_id": attempt.attempt_id,
        "attempt_digest": attempt.digest,
        "outcome_kind": SearchOutcomeKind.SUCCESS_RESULTS,
        "result_count": 1,
        "returned_pages": 1,
        "gross_cost_microunits": 100,
        "provider_altered_query": None,
        "provider_locale": "en-GB",
        "retry_after_seconds": None,
        "completed_at": "2026-08-14T00:00:01.000000Z",
    }
    values.update(changes)
    return SearchOutcome(**values)  # type: ignore[arg-type]


def _result(attempt: SearchAttempt, outcome: SearchOutcome) -> SearchResultReference:
    return SearchResultReference(
        _id(5),
        outcome.outcome_id,
        outcome.digest,
        attempt.provider_id,
        attempt.provider_configuration_digest,
        "provider-result-1",
        1,
        1,
        "https://example.org/report",
        "Example Publisher",
        "Policy decision",
        None,
        "2026-08-14",
        "en-GB",
        "news",
        (),
        SearchResultRetention.ATTRIBUTED_METADATA,
        "rights-v1",
        "2026-08-14T00:00:02.000000Z",
    )


def test_complete_search_record_chain_roundtrips_without_effects() -> None:
    purpose = _purpose()
    request = _request(purpose)
    attempt = _attempt(request)
    outcome = _outcome(attempt)
    result = _result(attempt, outcome)
    decision = SearchReviewDecision(
        _id(6),
        (result.result_reference_id,),
        (result.digest,),
        SearchReviewAction.SUPPORT_COVERAGE_GAP_REVIEW,
        "sha256:" + "2" * 64,
        "sha256:" + "3" * 64,
        ("PROSPECTIVE_COMPARATOR_HIT",),
        "2026-08-14T00:00:03.000000Z",
    )
    validate_search_request(purpose, request)
    validate_search_attempt(request, attempt)
    validate_search_outcome(attempt, outcome, request)
    validate_search_result(outcome, result, attempt)
    validate_search_review((result,), decision, request)
    for record in (purpose, request, attempt, outcome, result, decision):
        assert type(record).from_canonical_bytes(record.canonical_bytes) == record
        assert record.authorises_provider is False
        assert record.authorises_egress is False
        assert record.authorises_spend is False
        assert record.creates_signal is False
        assert record.creates_candidate is False
    assert SEARCH_AMPLIFICATION_BUDGET == "HARD_GROSS_PREAUTHORISED_LIMITS"
    assert SEARCH_QUERY_PRIVACY == "PUBLIC_MINIMISED_VERSIONED_CLASSIFICATION"


def test_purpose_specific_context_and_prospective_route_are_mandatory() -> None:
    purpose = _purpose()
    request = _request(purpose)
    with pytest.raises(SearchContractError, match="context binding"):
        validate_search_request(
            purpose, replace(request, context_reference_digest=None)
        )
    with pytest.raises(SearchContractError, match="Purpose"):
        validate_search_request(
            purpose,
            replace(
                request, query_privacy=SearchQueryPrivacy.AGGREGATED_NON_IDENTIFYING
            ),
        )
    with pytest.raises(SearchContractError, match="Purpose"):
        validate_search_request(
            purpose,
            replace(request, coverage_basis=("US:ELECTION",)),
        )
    with pytest.raises(SearchContractError, match="Purpose"):
        validate_search_request(
            purpose,
            replace(request, governing_policy_digests=("sha256:" + "8" * 64,)),
        )
    with pytest.raises(SearchContractError, match="audit route"):
        validate_search_request(
            purpose,
            replace(
                request, allowed_downstream_routes=(SearchDownstreamRoute.NO_WORK,)
            ),
        )


def test_generic_firehose_and_unbounded_amplification_fail_closed() -> None:
    for query in (
        "UK news",
        '"UK news"',
        "UK latest news",
        "UK latest news 2026",
        "politics news",
        "technology news",
    ):
        with pytest.raises(SearchContractError, match="firehose"):
            _request(rendered_query=query)
    with pytest.raises(SearchContractError, match="inconsistent"):
        replace(_limits(), max_retries=4, max_provider_calls=4)
    request = _request()
    attempt = replace(_attempt(request), page_number=3)
    with pytest.raises(SearchContractError, match="exceeds"):
        validate_search_attempt(request, attempt)
    with pytest.raises(SearchContractError, match="exceeds"):
        validate_search_attempt(
            request,
            replace(_attempt(request), language_ordinal=2),
        )
    with pytest.raises(SearchContractError, match="exceeds"):
        validate_search_attempt(
            request,
            replace(
                _attempt(request),
                started_at="2026-08-14T00:01:01.000000Z",
            ),
        )


def test_zero_partial_rate_limit_and_budget_block_remain_distinct() -> None:
    attempt = _attempt(_request())
    zero = _outcome(
        attempt, outcome_kind=SearchOutcomeKind.SUCCESS_ZERO_RESULTS, result_count=0
    )
    partial = _outcome(
        attempt, outcome_kind=SearchOutcomeKind.SUCCESS_PARTIAL_TRUNCATED
    )
    rate = _outcome(
        attempt,
        outcome_kind=SearchOutcomeKind.RATE_LIMITED,
        result_count=0,
        returned_pages=0,
        retry_after_seconds=30,
    )
    blocked = _outcome(
        attempt,
        outcome_kind=SearchOutcomeKind.BUDGET_BLOCKED,
        result_count=0,
        returned_pages=0,
        gross_cost_microunits=0,
    )
    assert len({zero.digest, partial.digest, rate.digest, blocked.digest}) == 4
    with pytest.raises(SearchContractError, match="has results"):
        replace(blocked, result_count=1)
    with pytest.raises(SearchContractError, match="only to rate limit"):
        replace(blocked, retry_after_seconds=30)


def test_provider_alteration_and_rights_limited_retention_are_explicit() -> None:
    request = _request()
    attempt = _attempt(request)
    with pytest.raises(SearchContractError, match="alteration visibility"):
        _outcome(attempt, outcome_kind=SearchOutcomeKind.PROVIDER_ALTERED_QUERY)
    altered = _outcome(
        attempt,
        outcome_kind=SearchOutcomeKind.PROVIDER_ALTERED_QUERY,
        provider_altered_query='site:gov.uk "policy decisions"',
    )
    result = _result(attempt, altered)
    with pytest.raises(SearchContractError, match="retention class"):
        replace(result, snippet="Untrusted provider snippet")
    snippet = replace(
        result,
        snippet="Untrusted provider snippet",
        retention_class=SearchResultRetention.RIGHTS_LIMITED_SNIPPET,
    )
    validate_search_result(altered, snippet, attempt)
    assert snippet.authorises_evidence is False
    assert snippet.authorises_underlying_retrieval is False


def test_outcome_result_and_review_bind_exact_predecessors_and_budgets() -> None:
    request = _request()
    attempt = _attempt(request)
    outcome = _outcome(attempt)
    result = _result(attempt, outcome)
    with pytest.raises(SearchContractError, match="budget"):
        validate_search_outcome(
            attempt, replace(outcome, gross_cost_microunits=50_001), request
        )
    with pytest.raises(SearchContractError, match="exact Request"):
        validate_search_outcome(
            attempt,
            outcome,
            replace(request, request_id=_id(99)),
        )
    with pytest.raises(SearchContractError, match="exact Outcome"):
        validate_search_result(outcome, replace(result, outcome_digest=_D), attempt)
    with pytest.raises(SearchContractError, match="exact Outcome"):
        validate_search_result(
            outcome,
            result,
            replace(attempt, attempt_id=_id(98)),
        )
    with pytest.raises(SearchContractError, match="budget"):
        validate_search_outcome(
            attempt,
            replace(outcome, completed_at="2026-08-14T00:01:01.000000Z"),
            request,
        )
    decision = SearchReviewDecision(
        _id(7),
        (result.result_reference_id,),
        (result.digest,),
        SearchReviewAction.NO_WORK,
        None,
        "sha256:" + "4" * 64,
        ("NOT_RELEVANT",),
        "2026-08-14T00:00:03.000000Z",
    )
    with pytest.raises(SearchContractError, match="result binding"):
        validate_search_review(
            (replace(result, result_reference_id=_id(8)),), decision, request
        )
    excluded = replace(
        decision,
        action=SearchReviewAction.CREATE_SEARCH_CHANNEL_SIGNAL,
        work_reference_digest="sha256:" + "5" * 64,
    )
    with pytest.raises(SearchContractError, match="result binding"):
        validate_search_review((result,), excluded, request)


def test_unknown_duplicate_noncanonical_and_invalid_calendar_bytes_fail() -> None:
    request = _request()
    value = json.loads(request.canonical_bytes)
    value["silent_fallback_provider"] = "other"
    with pytest.raises(SearchContractError, match="fields"):
        SearchRequest.from_canonical_bytes(canonical_json_bytes(value))
    duplicate = request.canonical_bytes.replace(
        b'"provider_id":', b'"provider_id":"other","provider_id":', 1
    )
    with pytest.raises(SearchContractError, match="duplicate"):
        SearchRequest.from_canonical_bytes(duplicate)
    with pytest.raises(SearchContractError, match="canonical JSON"):
        SearchRequest.from_canonical_bytes(request.canonical_bytes + b" ")
    with pytest.raises(SearchContractError, match="timestamp"):
        replace(request, requested_at="2026-02-30T00:00:00.000000Z")
