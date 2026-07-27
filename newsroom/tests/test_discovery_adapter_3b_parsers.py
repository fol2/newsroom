from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from newsroom.discovery_adapters import (
    AdapterKind,
    Completeness,
    ObservationProposalOutcome,
    ParserLimits,
    QuarantineRecommendation,
    run_fixture_adapter,
)

from .discovery_adapter_3b_helpers import (
    document_shape,
    feed_shape,
    request,
    scenario,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "discovery_adapters"


def _fixture(name: str) -> bytes:
    return (_FIXTURES / name).read_bytes()


def test_valid_json_fixture_produces_stable_sorted_items() -> None:
    result = run_fixture_adapter(
        request(),
        scenario(body=_fixture("json-items-v1.json")),
    )

    assert result.outcome is ObservationProposalOutcome.SUCCESS_CHANGED
    assert result.parser_result is not None
    assert result.parser_result.completeness is Completeness.COMPLETE
    assert len(result.candidate_items) == 2
    assert tuple(item.item_key for item in result.candidate_items) == tuple(
        sorted(item.item_key for item in result.candidate_items)
    )
    assert {
        {field.name: field.value for field in item.fields}["id"]
        for item in result.candidate_items
    } == {"json-1", "json-2"}


def test_duplicate_key_and_malformed_json_are_not_successful_empty() -> None:
    duplicate = run_fixture_adapter(
        request(),
        scenario(body=_fixture("malformed-json-duplicate-key.json")),
    )
    malformed = run_fixture_adapter(
        request(),
        scenario(body=b'{"items":['),
    )

    for result in (duplicate, malformed):
        assert result.outcome is ObservationProposalOutcome.MALFORMED
        assert result.incomplete is True
        assert result.parser_result is not None
        assert result.parser_result.issues
        assert result.candidate_items == ()
        assert result.quarantine is QuarantineRecommendation.QUARANTINE

    assert duplicate.parser_result is not None
    assert duplicate.parser_result.issues[0].code == "JSON_DUPLICATE_KEY"


def test_json_depth_scalar_collection_and_item_limits_are_bounded() -> None:
    deep = b'{"items":[' + b'{"value":' * 40 + b'0' + b'}' * 40 + b']}'
    deep_request = replace(
        request(),
        parser_limits=ParserLimits(20, 8, 100_000, 10_000, 100),
    )
    deep_result = run_fixture_adapter(deep_request, scenario(body=deep))
    assert deep_result.outcome is ObservationProposalOutcome.MALFORMED

    scalar_request = replace(
        request(),
        parser_limits=ParserLimits(20, 32, 8, 10_000, 100),
    )
    scalar_result = run_fixture_adapter(
        scalar_request,
        scenario(body=b'{"items":[{"id":"123456789","title":"One"}]}'),
    )
    assert scalar_result.outcome is ObservationProposalOutcome.MALFORMED

    collection_request = replace(
        request(),
        parser_limits=ParserLimits(20, 32, 100_000, 2, 100),
    )
    collection_result = run_fixture_adapter(
        collection_request,
        scenario(body=b'{"items":[{"id":"1","title":"One"}]}'),
    )
    assert collection_result.outcome is ObservationProposalOutcome.MALFORMED

    truncated = run_fixture_adapter(
        request(max_items=1),
        scenario(body=_fixture("json-items-v1.json")),
    )
    assert truncated.outcome is ObservationProposalOutcome.SUCCESS_TRUNCATED
    assert truncated.incomplete is True
    assert len(truncated.candidate_items) == 1
    assert "ITEM_LIMIT_TRUNCATED" in truncated.reason_codes


def test_valid_rss_and_atom_fixtures_share_typed_feed_boundary() -> None:
    rss_request = request(
        kind=AdapterKind.RSS_ATOM,
        shape=feed_shape(),
    )
    rss = run_fixture_adapter(
        rss_request,
        scenario(
            body=_fixture("rss-feed-v1.xml"),
            content_type="application/rss+xml; charset=utf-8",
        ),
    )
    atom = run_fixture_adapter(
        rss_request,
        scenario(
            body=_fixture("atom-feed-v1.xml"),
            content_type="application/atom+xml; charset=utf-8",
        ),
    )

    assert rss.outcome is ObservationProposalOutcome.SUCCESS_CHANGED
    assert atom.outcome is ObservationProposalOutcome.SUCCESS_CHANGED
    assert len(rss.candidate_items) == len(atom.candidate_items) == 1
    rss_fields = {field.name: field.value for field in rss.candidate_items[0].fields}
    atom_fields = {field.name: field.value for field in atom.candidate_items[0].fields}
    assert rss_fields == {
        "id": "rss-1",
        "link": "https://fixture.example/rss-1",
        "title": "Fixture RSS item",
    }
    assert atom_fields == {
        "id": "atom-1",
        "link": "https://fixture.example/atom-1",
        "title": "Fixture Atom item",
    }


def test_xml_external_entity_dtd_malformed_and_deep_nesting_fail_closed() -> None:
    feed_request = request(kind=AdapterKind.RSS_ATOM, shape=feed_shape())
    unsafe = run_fixture_adapter(
        feed_request,
        scenario(
            body=_fixture("unsafe-xml-entity.xml"),
            content_type="application/atom+xml; charset=utf-8",
        ),
    )
    malformed = run_fixture_adapter(
        feed_request,
        scenario(
            body=b"<feed><entry></feed>",
            content_type="application/atom+xml; charset=utf-8",
        ),
    )
    deep_request = replace(
        feed_request,
        parser_limits=ParserLimits(20, 8, 100_000, 10_000, 100),
    )
    deep_xml = (
        b'<feed xmlns="http://www.w3.org/2005/Atom">'
        + b"<x>" * 20
        + b"value"
        + b"</x>" * 20
        + b"</feed>"
    )
    deep = run_fixture_adapter(
        deep_request,
        scenario(
            body=deep_xml,
            content_type="application/atom+xml; charset=utf-8",
        ),
    )

    for result in (unsafe, malformed, deep):
        assert result.outcome is ObservationProposalOutcome.MALFORMED
        assert result.outcome is not ObservationProposalOutcome.SUCCESS_EMPTY
        assert result.quarantine is QuarantineRecommendation.QUARANTINE


def test_maintained_html_and_plain_text_are_parsed_without_execution() -> None:
    html_request = request(
        kind=AdapterKind.MAINTAINED_DOCUMENT,
        shape=document_shape(),
    )
    html = run_fixture_adapter(
        html_request,
        scenario(
            body=_fixture("maintained-guidance-v1.html"),
            content_type="text/html; charset=utf-8",
        ),
    )
    text = run_fixture_adapter(
        html_request,
        scenario(
            body=b"Current governed plain text.",
            content_type="text/plain; charset=utf-8",
        ),
    )

    assert html.outcome is ObservationProposalOutcome.SUCCESS_CHANGED
    assert text.outcome is ObservationProposalOutcome.SUCCESS_CHANGED
    html_fields = {field.name: field.value for field in html.candidate_items[0].fields}
    assert "Current governed text." in html_fields["body"]
    assert html_fields["title"] == "Fixture Guidance"
    text_fields = {field.name: field.value for field in text.candidate_items[0].fields}
    assert text_fields == {"body": "Current governed plain text."}


def test_parser_upgrade_changes_representation_not_source_item_identity() -> None:
    original = run_fixture_adapter(request(parser_version="parser-v1"), scenario())
    upgraded = run_fixture_adapter(request(parser_version="parser-v2"), scenario())

    assert original.parser_result is not None
    assert upgraded.parser_result is not None
    assert original.parser_result.representation_digest == (
        upgraded.parser_result.representation_digest
    )
    assert original.parser_result.producer_slot_digest != (
        upgraded.parser_result.producer_slot_digest
    )
    assert original.candidate_items[0].item_key == upgraded.candidate_items[0].item_key
    assert not hasattr(original, "source_revision_id")
    assert not hasattr(upgraded, "source_revision_id")


def test_shape_drift_is_quarantined_instead_of_becoming_publisher_change() -> None:
    missing_required = run_fixture_adapter(
        request(),
        scenario(body=b'{"items":[{"id":"1"}]}'),
    )
    wrong_root = run_fixture_adapter(
        request(),
        scenario(body=b'{"results":[{"id":"1","title":"One"}]}'),
    )

    for result in (missing_required, wrong_root):
        assert result.outcome is ObservationProposalOutcome.SHAPE_DRIFT
        assert result.incomplete is True
        assert result.candidate_items == ()
        assert result.quarantine is QuarantineRecommendation.QUARANTINE
