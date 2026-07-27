from __future__ import annotations

from newsroom.discovery_adapters import (
    AdapterKind,
    Header,
    ObservationProposalOutcome,
    QuarantineRecommendation,
    TransportFailureKind,
    run_fixture_adapter,
)
from newsroom.sources import ObservationModel

from .discovery_adapter_3b_helpers import (
    OTHER_VERSION_ID,
    arbitrary_baseline,
    baseline,
    request,
    scenario,
)


def test_successful_empty_changed_and_exact_baseline_unchanged_are_distinct() -> None:
    empty = run_fixture_adapter(
        request(),
        scenario(body=b"", status=204, content_type=None),
    )
    changed = run_fixture_adapter(request(), scenario())
    assert changed.parser_result is not None
    unchanged = run_fixture_adapter(
        request(baseline=baseline(changed.parser_result)),
        scenario(),
    )

    assert empty.outcome is ObservationProposalOutcome.SUCCESS_EMPTY
    assert empty.candidate_items == ()
    assert changed.outcome is ObservationProposalOutcome.SUCCESS_CHANGED
    assert changed.candidate_items
    assert unchanged.outcome is ObservationProposalOutcome.SUCCESS_UNCHANGED
    assert unchanged.candidate_items == ()
    assert unchanged.parser_result is not None
    assert unchanged.parser_result.items
    assert all(
        result.authority_effect == "NONE"
        for result in (empty, changed, unchanged)
    )


def test_304_requires_exact_source_version_policy_and_validator_baseline() -> None:
    exact_baseline = arbitrary_baseline()
    exact = run_fixture_adapter(
        request(baseline=exact_baseline),
        scenario(
            status=304,
            body=b"",
            content_type=None,
            extra_headers=(Header("etag", '"fixture-etag"'),),
        ),
    )
    no_baseline = run_fixture_adapter(
        request(),
        scenario(status=304, body=b"", content_type=None),
    )
    stale_version = run_fixture_adapter(
        request(
            baseline=arbitrary_baseline(version_id=OTHER_VERSION_ID)
        ),
        scenario(status=304, body=b"", content_type=None),
    )
    stale_policy = run_fixture_adapter(
        request(baseline=arbitrary_baseline(policy_version="v2")),
        scenario(status=304, body=b"", content_type=None),
    )
    wrong_validator = run_fixture_adapter(
        request(baseline=exact_baseline),
        scenario(
            status=304,
            body=b"",
            content_type=None,
            extra_headers=(Header("etag", '"different"'),),
        ),
    )

    assert exact.outcome is ObservationProposalOutcome.SUCCESS_UNCHANGED
    for result in (
        no_baseline,
        stale_version,
        stale_policy,
        wrong_validator,
    ):
        assert result.outcome is ObservationProposalOutcome.TRANSPORT_FAILED
        assert result.incomplete is True
        assert result.candidate_items == ()
        assert result.reason_codes == (
            "CONDITIONAL_RESPONSE_WITHOUT_EXACT_BASELINE",
        )


def test_http_status_transport_and_redirect_outcomes_do_not_collapse_to_no_news() -> None:
    cases = (
        (401, ObservationProposalOutcome.UNAUTHORISED, "HTTP_UNAUTHORISED"),
        (403, ObservationProposalOutcome.UNAUTHORISED, "HTTP_FORBIDDEN"),
        (404, ObservationProposalOutcome.NOT_FOUND, "HTTP_NOT_FOUND"),
        (410, ObservationProposalOutcome.GONE, "HTTP_GONE"),
        (429, ObservationProposalOutcome.RATE_LIMITED, "HTTP_RATE_LIMITED"),
        (503, ObservationProposalOutcome.TRANSPORT_FAILED, "HTTP_FAILURE_STATUS"),
        (302, ObservationProposalOutcome.REDIRECTED, "REDIRECT_TERMINAL"),
    )
    for status, outcome, reason in cases:
        result = run_fixture_adapter(
            request(),
            scenario(status=status, body=b"", content_type=None),
        )
        assert result.outcome is outcome
        assert result.outcome is not ObservationProposalOutcome.SUCCESS_UNCHANGED
        assert result.reason_codes == (reason,)
        assert result.incomplete is True
        assert result.candidate_items == ()
        if status == 503:
            assert result.receipt is not None
            assert result.receipt.failure_kind is None

    transport = run_fixture_adapter(
        request(),
        scenario(failure_kind=TransportFailureKind.DNS),
    )
    assert transport.outcome is ObservationProposalOutcome.TRANSPORT_FAILED
    assert transport.reason_codes == ("TRANSPORT_DNS",)
    assert transport.outcome is not ObservationProposalOutcome.SUCCESS_UNCHANGED


def test_partial_output_emits_only_independently_valid_candidates() -> None:
    duplicate_delivery = (
        b'{"items":['
        b'{"id":"1","title":"One"},'
        b'{"id":"1","title":"One"}'
        b"]}"
    )
    result = run_fixture_adapter(
        request(),
        scenario(body=duplicate_delivery),
    )

    assert result.outcome is ObservationProposalOutcome.SUCCESS_PARTIAL
    assert result.incomplete is True
    assert len(result.candidate_items) == 1
    assert result.parser_result is not None
    assert result.parser_result.issues[0].code == "DUPLICATE_ITEM"
    assert result.quarantine is QuarantineRecommendation.REVIEW


def test_partial_complete_state_and_rolling_list_cannot_propose_clearance() -> None:
    partial_body = (
        b'{"items":['
        b'{"id":"1","title":"One"},'
        b'{"id":"1","title":"One"}'
        b"]}"
    )
    for model in (
        ObservationModel.COMPLETE_CURRENT_STATE,
        ObservationModel.ROLLING_LIST,
    ):
        result = run_fixture_adapter(
            request(observation_model=model),
            scenario(body=partial_body),
        )
        assert result.outcome is ObservationProposalOutcome.SUCCESS_PARTIAL
        assert "NO_CLEARANCE_OR_WITHDRAWAL_AUTHORITY" in result.reason_codes
        assert result.authority_effect == "NONE"
        assert not hasattr(result, "withdrawal")
        assert not hasattr(result, "clearance")


def test_empty_rolling_list_is_not_withdrawal_or_healthy_unchanged() -> None:
    result = run_fixture_adapter(
        request(observation_model=ObservationModel.ROLLING_LIST),
        scenario(body=b'{"items":[]}'),
    )

    assert result.outcome is ObservationProposalOutcome.SUCCESS_EMPTY
    assert result.outcome is not ObservationProposalOutcome.SUCCESS_UNCHANGED
    assert result.candidate_items == ()
    assert result.authority_effect == "NONE"
    assert not hasattr(result, "withdrawal")


def test_content_type_charset_and_parser_failure_remain_malformed() -> None:
    wrong_content = run_fixture_adapter(
        request(),
        scenario(content_type="text/plain; charset=utf-8"),
    )
    wrong_charset = run_fixture_adapter(
        request(),
        scenario(content_type="application/json; charset=latin-1"),
    )
    malformed = run_fixture_adapter(
        request(),
        scenario(body=b"not-json"),
    )

    for result in (wrong_content, wrong_charset, malformed):
        assert result.outcome is ObservationProposalOutcome.MALFORMED
        assert result.outcome is not ObservationProposalOutcome.SUCCESS_EMPTY
        assert result.incomplete is True
        assert result.parser_result is not None
        assert result.quarantine is QuarantineRecommendation.QUARANTINE


def test_adapter_kind_is_shape_bound_and_no_named_runtime_is_invoked() -> None:
    value = request(kind=AdapterKind.JSON_DOCUMENT)
    result = run_fixture_adapter(value, scenario())

    assert result.outcome is ObservationProposalOutcome.SUCCESS_CHANGED
    assert result.receipt is not None
    assert result.receipt.scenario_id == "fixture-scenario-v1"
    assert result.receipt.final_url == value.endpoint
    assert not hasattr(result, "http_session")
    assert not hasattr(result, "credential")
    assert not hasattr(result, "scheduler")
