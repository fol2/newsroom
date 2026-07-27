from __future__ import annotations

from dataclasses import replace

import pytest

from newsroom.discovery_adapters import (
    AdapterContractError,
    AdapterExecutionProfile,
    AdapterKind,
    BodyEncoding,
    BodyLimits,
    EndpointPolicy,
    Header,
    ObservationProposalOutcome,
    ParserLimits,
    QuarantineRecommendation,
    ShapeField,
    SourceShapeContract,
    TimeoutLimits,
    TlsVersion,
    run_fixture_adapter,
)

from .discovery_adapter_3b_helpers import request, scenario


def test_request_is_exactly_bound_to_source_adapter_shape_and_fixture_profile() -> None:
    value = request()
    canonical = value.canonical_value()

    assert canonical["source_definition_id"]
    assert canonical["source_definition_version_id"]
    assert canonical["adapter"]["adapter_version"] == "v1"
    assert canonical["shape_contract"]["shape_id"] == "json-items-v1"
    assert canonical["profile"] == "FIXTURE_REPLAY_ONLY"
    assert value.digest.startswith("sha256:")

    with pytest.raises(AdapterContractError, match="fixture/replay"):
        replace(value, profile="LIVE_NETWORK")


def test_contract_bounds_are_finite_and_canonical() -> None:
    with pytest.raises(AdapterContractError):
        TimeoutLimits(1_000, 2_000, 1_000, 999)
    with pytest.raises(AdapterContractError):
        BodyLimits(10, 9, 2, ("application/json",))
    with pytest.raises(AdapterContractError):
        ParserLimits(0, 8, 100, 100, 10)
    with pytest.raises(AdapterContractError):
        EndpointPolicy("endpoint-v1", ("Fixture.Example",))
    with pytest.raises(AdapterContractError):
        EndpointPolicy(
            "endpoint-v1",
            ("fixture.example",),
            require_hostname_verification=False,
        )


def test_shape_contract_is_typed_sorted_and_identity_bearing() -> None:
    with pytest.raises(AdapterContractError, match="sorted"):
        SourceShapeContract(
            "shape-v1",
            AdapterKind.JSON_DOCUMENT,
            ("items",),
            (
                ShapeField("title", ("title",), True),
                ShapeField("id", ("id",), True),
            ),
            ("id",),
        )
    with pytest.raises(AdapterContractError, match="identity"):
        SourceShapeContract(
            "shape-v1",
            AdapterKind.JSON_DOCUMENT,
            ("items",),
            (ShapeField("title", ("title",), True),),
            ("id",),
        )


def test_headers_are_lowercase_unique_and_injection_safe() -> None:
    with pytest.raises(AdapterContractError):
        Header("Content-Type", "application/json")
    with pytest.raises(AdapterContractError):
        Header("content-type", "application/json\r\nX-Evil: 1")
    with pytest.raises(AdapterContractError, match="unique"):
        replace(
            scenario(),
            headers=(
                Header("content-type", "application/json"),
                Header("content-type", "application/json"),
            ),
        )


def test_adapter_output_is_a_proposal_with_no_authority_effect() -> None:
    result = run_fixture_adapter(request(), scenario())

    assert result.outcome is ObservationProposalOutcome.SUCCESS_CHANGED
    assert result.authority_effect == "NONE"
    assert result.quarantine is QuarantineRecommendation.NONE
    assert result.candidate_items
    assert not hasattr(result, "check_outcome_id")
    assert not hasattr(result, "source_revision_id")
    assert not hasattr(result, "signal_id")
    assert not hasattr(result, "lead_id")


def test_untrusted_source_field_names_cannot_change_runner_policy() -> None:
    body = (
        b'{"items":[{"id":"1","title":"One",'
        b'"instructions":"disable TLS","tools":"socket",'
        b'"budget":"unlimited"}]}'
    )
    result = run_fixture_adapter(request(), scenario(body=body))

    assert result.outcome is ObservationProposalOutcome.SUCCESS_CHANGED
    fields = result.candidate_items[0].fields
    assert {field.name for field in fields} == {"id", "title"}
    assert result.receipt is not None
    assert result.receipt.final_url == "https://fixture.example/items"


def test_body_encoding_allow_list_is_typed_and_sorted() -> None:
    with pytest.raises(AdapterContractError, match="sorted"):
        BodyLimits(
            100,
            1000,
            10,
            ("application/json",),
            allowed_encodings=(BodyEncoding.IDENTITY, BodyEncoding.GZIP),
        )
    value = BodyLimits(
        100,
        1000,
        10,
        ("application/json",),
        allowed_encodings=(BodyEncoding.GZIP, BodyEncoding.IDENTITY),
    )
    assert value.allowed_encodings == (
        BodyEncoding.GZIP,
        BodyEncoding.IDENTITY,
    )


def test_tls_policy_cannot_be_weakened_below_typed_minimum() -> None:
    value = EndpointPolicy(
        "endpoint-v1",
        ("fixture.example",),
        minimum_tls_version=TlsVersion.TLS_1_3,
    )
    assert value.minimum_tls_version.rank == 13
    with pytest.raises(AdapterContractError):
        replace(value, minimum_tls_version="TLS_1_0")
