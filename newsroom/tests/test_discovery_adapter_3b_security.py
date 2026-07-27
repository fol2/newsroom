from __future__ import annotations

from dataclasses import replace
import gzip

import pytest

from newsroom.discovery_adapters import (
    AdapterContractError,
    BodyEncoding,
    ObservationProposalOutcome,
    RedirectHop,
    TimingEvidence,
    TlsEvidence,
    TlsVersion,
    validate_endpoint,
    validate_redirects,
    run_fixture_adapter,
)

from .discovery_adapter_3b_helpers import NOW, request, scenario


def test_endpoint_requires_canonical_https_allowlisted_host_and_port() -> None:
    policy = request().endpoint_policy
    assert validate_endpoint("https://fixture.example/items", policy).hostname == (
        "fixture.example"
    )

    for value in (
        "http://fixture.example/items",
        "https://user@fixture.example/items",
        "https://fixture.example/items#fragment",
        "https://127.0.0.1/items",
        "https://fixture.example:444/items",
        "https://FIXTURE.example/items",
        "https://fixture.example",
    ):
        with pytest.raises(AdapterContractError):
            validate_endpoint(value, policy)


def test_private_loopback_linklocal_reserved_and_unspecified_dns_fail_preflight() -> None:
    for address in (
        "127.0.0.1",
        "10.0.0.1",
        "169.254.1.1",
        "224.0.0.1",
        "0.0.0.0",
        "::1",
        "fc00::1",
        "fe80::1",
        "2001:db8::1",
    ):
        result = run_fixture_adapter(
            request(),
            scenario(dns_addresses=(address,)),
        )
        assert result.outcome is ObservationProposalOutcome.BLOCKED
        assert result.receipt is None


def test_tls_validation_and_hostname_verification_fail_closed() -> None:
    invalid_certificate = run_fixture_adapter(
        request(),
        scenario(tls_valid=False),
    )
    invalid_hostname = run_fixture_adapter(
        request(),
        scenario(tls_hostname_verified=False),
    )
    assert invalid_certificate.outcome is ObservationProposalOutcome.BLOCKED
    assert invalid_hostname.outcome is ObservationProposalOutcome.BLOCKED

    weak = replace(
        scenario(),
        tls_evidence=TlsEvidence(
            "fixture.example",
            TlsVersion.TLS_1_2,
            True,
            True,
            NOW,
        ),
    )
    strict_request = replace(
        request(),
        endpoint_policy=replace(
            request().endpoint_policy,
            minimum_tls_version=TlsVersion.TLS_1_3,
        ),
    )
    assert (
        run_fixture_adapter(strict_request, weak).outcome
        is ObservationProposalOutcome.BLOCKED
    )


def test_redirect_chain_is_contiguous_allowlisted_bounded_and_loop_free() -> None:
    first = RedirectHop(
        "https://fixture.example/items",
        "https://mirror.example/items",
        302,
    )
    allowed_request = request(
        allowed_hosts=("fixture.example", "mirror.example")
    )
    redirected = scenario(redirects=(first,))
    result = run_fixture_adapter(allowed_request, redirected)
    assert result.outcome is ObservationProposalOutcome.SUCCESS_CHANGED
    assert result.receipt is not None
    assert result.receipt.final_url == "https://mirror.example/items"

    blocked = run_fixture_adapter(request(), redirected)
    assert blocked.outcome is ObservationProposalOutcome.BLOCKED

    with pytest.raises(AdapterContractError, match="loop"):
        validate_redirects(
            "https://fixture.example/items",
            (
                first,
                RedirectHop(
                    "https://mirror.example/items",
                    "https://fixture.example/items",
                    302,
                ),
            ),
            allowed_request.endpoint_policy,
        )

    with pytest.raises(AdapterContractError, match="contiguous"):
        validate_redirects(
            "https://fixture.example/items",
            (
                RedirectHop(
                    "https://mirror.example/items",
                    "https://fixture.example/other",
                    302,
                ),
            ),
            allowed_request.endpoint_policy,
        )


def test_timeout_components_remain_distinct_transport_failures() -> None:
    cases = (
        (TimingEvidence(1_001, 1, 1, 1_001), "CONNECT_TIMEOUT"),
        (TimingEvidence(1, 2_001, 1, 2_001), "READ_TIMEOUT"),
        (TimingEvidence(1, 1, 1_001, 1_001), "IDLE_TIMEOUT"),
        (TimingEvidence(1, 1, 1, 5_001), "TOTAL_TIMEOUT"),
    )
    for timing, reason in cases:
        result = run_fixture_adapter(request(), scenario(timing=timing))
        assert result.outcome is ObservationProposalOutcome.TRANSPORT_FAILED
        assert result.reason_codes == (f"TRANSPORT_{reason}",)
        assert result.receipt is not None
        assert result.receipt.failure_kind is not None


def test_content_length_encoding_and_decompression_contract_fail_closed() -> None:
    base = scenario()
    wrong_length = replace(
        base,
        headers=(
            replace(base.headers[0], value="999"),
            base.headers[1],
        ),
    )
    assert (
        run_fixture_adapter(request(), wrong_length).outcome
        is ObservationProposalOutcome.TRANSPORT_FAILED
    )

    body = b'{"items":[{"id":"1","title":"One"}]}'
    compressed = gzip.compress(body, mtime=0)
    compressed_scenario = scenario(
        body=compressed,
        content_encoding=BodyEncoding.GZIP,
    )
    denied = run_fixture_adapter(request(), compressed_scenario)
    assert denied.outcome is ObservationProposalOutcome.TRANSPORT_FAILED

    allowed = run_fixture_adapter(
        request(
            allowed_encodings=(BodyEncoding.GZIP, BodyEncoding.IDENTITY),
        ),
        compressed_scenario,
    )
    assert allowed.outcome is ObservationProposalOutcome.SUCCESS_CHANGED
    assert allowed.capture is not None
    assert allowed.capture.body == body


def test_decompression_ratio_and_truncated_stream_are_rejected() -> None:
    expanded = b"a" * 20_000
    compressed = gzip.compress(expanded, mtime=0)
    ratio_limited_request = replace(
        request(
            allowed_encodings=(BodyEncoding.GZIP, BodyEncoding.IDENTITY),
            allowed_content_types=("text/plain",),
        ),
        body_limits=replace(
            request(
                allowed_encodings=(BodyEncoding.GZIP, BodyEncoding.IDENTITY),
                allowed_content_types=("text/plain",),
            ).body_limits,
            max_decompression_ratio=2,
        ),
    )
    rejected = run_fixture_adapter(
        ratio_limited_request,
        scenario(
            body=compressed,
            content_type="text/plain",
            content_encoding=BodyEncoding.GZIP,
        ),
    )
    assert rejected.outcome is ObservationProposalOutcome.TRANSPORT_FAILED

    truncated = run_fixture_adapter(
        request(
            allowed_encodings=(BodyEncoding.GZIP, BodyEncoding.IDENTITY),
        ),
        scenario(
            body=compressed[:-3],
            content_encoding=BodyEncoding.GZIP,
        ),
    )
    assert truncated.outcome is ObservationProposalOutcome.TRANSPORT_FAILED
