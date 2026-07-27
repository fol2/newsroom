from __future__ import annotations

from dataclasses import replace

import pytest

from newsroom.discovery_adapters import (
    AdapterContractError,
    AdapterKind,
    AdapterRequestId,
    DnsEvidence,
    Header,
    ObservationProposalOutcome,
    RedirectEvidence,
    RedirectHop,
    ShapeField,
    SourceShapeContract,
    TlsEvidence,
    TlsVersion,
    run_fixture_adapter,
)

from .discovery_adapter_3b_helpers import (
    NOW,
    baseline,
    document_shape,
    json_shape,
    request,
    scenario,
)


def test_item_identity_ignores_nonidentity_fields_and_shape_or_producer_versions() -> None:
    original = run_fixture_adapter(
        request(),
        scenario(body=b'{"items":[{"id":"1","title":"One"}]}'),
    )
    changed_title = run_fixture_adapter(
        request(),
        scenario(body=b'{"items":[{"id":"1","title":"Two"}]}'),
    )
    changed_shape = replace(json_shape(), shape_id="json-items-v2")
    reprocessed = run_fixture_adapter(
        request(shape=changed_shape, parser_version="parser-v2"),
        scenario(body=b'{"items":[{"id":"1","title":"One"}]}'),
    )

    keys = {
        original.candidate_items[0].item_key,
        changed_title.candidate_items[0].item_key,
        reprocessed.candidate_items[0].item_key,
    }
    assert len(keys) == 1
    assert original.parser_result is not None
    assert changed_title.parser_result is not None
    assert original.parser_result.representation_digest != (
        changed_title.parser_result.representation_digest
    )


def test_maintained_document_body_change_retains_singleton_item_identity() -> None:
    first = run_fixture_adapter(
        request(
            kind=AdapterKind.MAINTAINED_DOCUMENT,
            shape=document_shape(),
        ),
        scenario(
            body=b"First maintained state.",
            content_type="text/plain; charset=utf-8",
        ),
    )
    second = run_fixture_adapter(
        request(
            kind=AdapterKind.MAINTAINED_DOCUMENT,
            shape=document_shape(),
        ),
        scenario(
            body=b"Second maintained state.",
            content_type="text/plain; charset=utf-8",
        ),
    )

    assert first.outcome is ObservationProposalOutcome.SUCCESS_CHANGED
    assert second.outcome is ObservationProposalOutcome.SUCCESS_CHANGED
    assert first.candidate_items[0].item_key == second.candidate_items[0].item_key
    assert first.candidate_items[0].digest != second.candidate_items[0].digest


def test_parser_upgrade_on_identical_bytes_is_unchanged_but_retains_new_representation() -> None:
    first = run_fixture_adapter(request(parser_version="parser-v1"), scenario())
    assert first.parser_result is not None
    upgraded = run_fixture_adapter(
        request(
            parser_version="parser-v2",
            baseline=baseline(first.parser_result),
        ),
        scenario(),
    )

    assert upgraded.outcome is ObservationProposalOutcome.SUCCESS_UNCHANGED
    assert upgraded.parser_result is not None
    assert upgraded.parser_result.source_body_digest == (
        first.parser_result.source_body_digest
    )
    assert upgraded.parser_result.producer_slot_digest != (
        first.parser_result.producer_slot_digest
    )
    assert upgraded.parser_result.item_keys == first.parser_result.item_keys
    assert upgraded.parser_result.parser_result_id == first.parser_result.parser_result_id
    assert "UNCHANGED_SOURCE_REPROCESSED_NEW_PRODUCER" in upgraded.reason_codes


def test_same_producer_same_bytes_nondeterminism_fails_closed() -> None:
    first = run_fixture_adapter(request(), scenario())
    assert first.parser_result is not None
    inconsistent = replace(
        baseline(first.parser_result),
        representation_digest="sha256:" + "0" * 64,
    )
    result = run_fixture_adapter(
        request(baseline=inconsistent),
        scenario(),
    )

    assert result.outcome is ObservationProposalOutcome.SHAPE_DRIFT
    assert result.reason_codes == (
        "NONDETERMINISTIC_SAME_PRODUCER_REPROCESSING",
    )
    assert result.candidate_items == ()


def test_reprocessing_that_changes_stable_item_key_set_is_quarantined() -> None:
    first = run_fixture_adapter(request(), scenario())
    assert first.parser_result is not None
    changed_identity = SourceShapeContract(
        "json-items-v2",
        AdapterKind.JSON_DOCUMENT,
        ("items",),
        (
            ShapeField("id", ("id",), True),
            ShapeField("title", ("title",), True),
        ),
        ("title",),
    )
    result = run_fixture_adapter(
        request(
            shape=changed_identity,
            parser_version="parser-v2",
            baseline=baseline(first.parser_result),
        ),
        scenario(),
    )

    assert result.outcome is ObservationProposalOutcome.SHAPE_DRIFT
    assert result.reason_codes == ("REPROCESSING_ITEM_IDENTITY_DRIFT",)


def test_each_redirect_target_requires_its_own_public_dns_and_tls_evidence() -> None:
    hop = RedirectHop(
        "https://fixture.example/items",
        "https://mirror.example/items",
        302,
    )
    allowed = request(allowed_hosts=("fixture.example", "mirror.example"))

    missing = run_fixture_adapter(
        allowed,
        scenario(redirects=(hop,), redirect_evidence=()),
    )
    private_target = run_fixture_adapter(
        allowed,
        scenario(
            redirects=(hop,),
            redirect_evidence=(
                RedirectEvidence(
                    hop.to_url,
                    DnsEvidence("mirror.example", ("10.0.0.1",), NOW),
                    TlsEvidence(
                        "mirror.example",
                        TlsVersion.TLS_1_3,
                        True,
                        True,
                        NOW,
                    ),
                ),
            ),
        ),
    )

    assert missing.outcome is ObservationProposalOutcome.BLOCKED
    assert private_target.outcome is ObservationProposalOutcome.BLOCKED
    assert missing.receipt is private_target.receipt is None


def test_noncanonical_public_ip_evidence_is_rejected() -> None:
    result = run_fixture_adapter(
        request(),
        scenario(
            dns_addresses=(
                "2606:4700:4700:0000:0000:0000:0000:1111",
            )
        ),
    )
    assert result.outcome is ObservationProposalOutcome.BLOCKED


def test_bad_item_does_not_discard_independently_valid_item() -> None:
    result = run_fixture_adapter(
        request(),
        scenario(
            body=(
                b'{"items":['
                b'{"id":"1","title":"One"},'
                b'{"id":"2"}'
                b"]}"
            )
        ),
    )

    assert result.outcome is ObservationProposalOutcome.SUCCESS_PARTIAL
    assert len(result.candidate_items) == 1
    assert result.parser_result is not None
    assert result.parser_result.shape_drift is False
    assert any(
        issue.code == "REQUIRED_FIELD_MISSING"
        for issue in result.parser_result.issues
    )


def test_nested_unexpected_field_is_shape_drift_not_publisher_change() -> None:
    strict = SourceShapeContract(
        "nested-shape-v1",
        AdapterKind.JSON_DOCUMENT,
        ("items",),
        (
            ShapeField("id", ("meta", "id"), True),
            ShapeField("title", ("title",), True),
        ),
        ("id",),
        allow_additional_fields=False,
    )
    result = run_fixture_adapter(
        request(shape=strict),
        scenario(
            body=(
                b'{"items":[{"meta":{"id":"1","unexpected":"x"},'
                b'"title":"One"}]}'
            )
        ),
    )

    assert result.outcome is ObservationProposalOutcome.SHAPE_DRIFT
    assert result.parser_result is not None
    assert result.parser_result.issues[0].code == "UNEXPECTED_FIELDS"


def test_identity_fields_must_be_required_and_paths_cannot_overlap() -> None:
    with pytest.raises(AdapterContractError, match="required"):
        SourceShapeContract(
            "optional-identity-v1",
            AdapterKind.JSON_DOCUMENT,
            ("items",),
            (ShapeField("id", ("id",), False),),
            ("id",),
        )
    with pytest.raises(AdapterContractError, match="overlap"):
        SourceShapeContract(
            "overlapping-identity-v1",
            AdapterKind.JSON_DOCUMENT,
            ("items",),
            (
                ShapeField("id", ("meta",), True),
                ShapeField("subid", ("meta", "id"), True),
            ),
            ("id", "subid"),
        )


def test_singleton_contract_rejects_multiple_items() -> None:
    singleton = SourceShapeContract(
        "singleton-json-v1",
        AdapterKind.JSON_DOCUMENT,
        ("items",),
        (ShapeField("title", ("title",), True),),
        (),
        singleton_identity="one-logical-document",
    )
    result = run_fixture_adapter(
        request(shape=singleton),
        scenario(
            body=(
                b'{"items":['
                b'{"title":"One"},'
                b'{"title":"Two"}'
                b"]}"
            )
        ),
    )
    assert result.outcome is ObservationProposalOutcome.SHAPE_DRIFT
    assert result.parser_result is not None
    assert result.parser_result.issues[0].code == "SINGLETON_MULTIPLE_ITEMS"


def test_receipt_retains_only_minimum_protocol_headers() -> None:
    result = run_fixture_adapter(
        request(),
        scenario(
            extra_headers=(
                Header("etag", '"fixture-etag"'),
                Header("set-cookie", "session=secret"),
                Header("x-provider-debug", "untrusted"),
            )
        ),
    )
    assert result.receipt is not None
    names = {item.name for item in result.receipt.headers}
    assert "etag" in names
    assert "content-type" in names
    assert "set-cookie" not in names
    assert "x-provider-debug" not in names


def test_body_prohibited_statuses_reject_payload_bytes() -> None:
    for status in (204, 205, 304):
        result = run_fixture_adapter(
            request(),
            scenario(status=status, body=b"unexpected", content_type=None),
        )
        assert result.outcome is ObservationProposalOutcome.TRANSPORT_FAILED
        assert result.reason_codes == (f"HTTP_{status}_WITH_BODY",)


def test_proposal_rejects_cross_record_lineage_substitution() -> None:
    result = run_fixture_adapter(request(), scenario())
    assert result.receipt is not None
    assert result.capture is not None
    assert result.parser_result is not None

    with pytest.raises(AdapterContractError, match="capture lineage"):
        replace(
            result,
            capture=replace(
                result.capture,
                request_id=AdapterRequestId.new(),
            ),
        )
    with pytest.raises(AdapterContractError, match="exact capture"):
        replace(
            result,
            parser_result=replace(
                result.parser_result,
                capture_digest="sha256:" + "f" * 64,
            ),
        )
