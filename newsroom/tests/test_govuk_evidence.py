from contextlib import contextmanager, nullcontext
import io
import json
import urllib.error
from dataclasses import replace
from datetime import UTC, datetime
from email.message import Message

import pytest

from newsroom.authority.canonical import digest_canonical
from newsroom.control_plane.govuk_evidence import (
    GovUkContentHold, GovUkEvidenceAcquisition, MAX_BODY_BYTES, POLICY_DIGEST,
    _api_url, parse_govuk_content_document,
)
from newsroom.control_plane.native_evidence import EvidenceAcquisitionRequest, NativeEvidenceHold
from newsroom.sources import SourceDefinitionVersionId
from newsroom.tests.check_3c_authority_helpers import proof
from newsroom.tests.discovery_3d_authority_helpers import open_discovery_system
from newsroom.tests.test_graphiti_operational_readiness import _unit
from newsroom.tests.test_native_discovery import _seed, NOW


class Response(io.BytesIO):
    status = 200

    def __init__(self, raw, url):
        super().__init__(raw)
        self.url = url
        self.headers = Message()
        self.headers["Content-Type"] = "application/json; charset=utf-8"

    def geturl(self):
        return self.url


def _document(path):
    return {
        "base_path": path, "locale": "en", "document_type": "news_story",
        "title": "Official update", "details": {"body": "<p>Exact independent source text.</p>"},
        "first_published_at": "2026-09-01T10:00:00Z",
        "public_updated_at": "2026-09-02T10:00:00Z",
        "links": {"organisations": [{"title": "Home Office"}]},
    }


def _content_shape(document_type: str, *, release: str | None = None):
    value = _document("/government/example")
    value["document_type"] = document_type
    if document_type == "official_statistics_announcement":
        value["details"] = {
            "display_date": "10 September 2026 9:30am",
            "release_timestamp": release or "2026-09-10T09:30:00+01:00",
            "state": "confirmed",
        }
    elif document_type == "manual":
        value["details"] = {"child_section_groups": [{
            "title": "Standards",
            "child_sections": [{
                "base_path": "/government/example/section-one",
                "title": "Section one",
            }],
        }]}
    elif document_type == "document_collection":
        value["links"]["documents"] = [{
            "base_path": "/government/publications/child",
            "title": "Child document",
        }]
    elif document_type == "transparency":
        value["details"]["attachments"] = [{
            "url": (
                "https://assets.publishing.service.gov.uk/media/example/report.ods"
            ),
            "title": "Attached report",
        }]
        value["links"]["children"] = [{
            "base_path": "/government/example/child",
            "title": "Child publication",
        }]
    return value


@pytest.mark.parametrize("document_type", ["oral_statement", "statistics"])
def test_content_parser_accepts_observed_complete_body_types(document_type):
    document = parse_govuk_content_document(
        "https://www.gov.uk/government/example",
        json.dumps(_content_shape(document_type)).encode(),
        retrieved_at=datetime(2026, 9, 9, tzinfo=UTC),
    )
    assert document.document_type == document_type
    assert document.body_text == "Exact independent source text."


@pytest.mark.parametrize(("document_type", "release", "variant", "reason_code"), [
    ("official_statistics_announcement", "2026-09-10T09:30:00+01:00",
     "confirmed", "SOURCE_ITEM_NOT_YET_PUBLISHED"),
    ("official_statistics_announcement", "2026-12-17T09:30:00Z",
     "provisional-one", "SOURCE_ITEM_NOT_YET_PUBLISHED"),
    ("official_statistics_announcement", "2027-01-15T09:30:00Z",
     "provisional-two", "SOURCE_ITEM_NOT_YET_PUBLISHED"),
    ("manual", None, "inventory", "SOURCE_ITEM_CHILD_COVERAGE_INCOMPLETE"),
    ("document_collection", None, "body", "SOURCE_ITEM_CHILD_COVERAGE_INCOMPLETE"),
    ("document_collection", None, "empty", "SOURCE_ITEM_CHILD_COVERAGE_INCOMPLETE"),
    ("transparency", None, "attachments",
     "SOURCE_ITEM_ATTACHMENT_COVERAGE_INCOMPLETE"),
])
def test_content_parser_retains_specific_known_coverage_holds(
    document_type, release, variant, reason_code,
):
    value = _content_shape(document_type, release=release)
    if variant.startswith("provisional"):
        value["details"]["state"] = "provisional"
    if variant == "empty":
        value["details"]["body"] = "<div></div>"
    with pytest.raises(GovUkContentHold) as caught:
        parse_govuk_content_document(
            "https://www.gov.uk/government/example", json.dumps(value).encode(),
            retrieved_at=datetime(2026, 9, 9, tzinfo=UTC),
        )
    assert caught.value.reason_code == reason_code


@pytest.mark.parametrize(("document_type", "mutation"), [
    ("official_statistics_announcement", "elapsed"),
    ("official_statistics_announcement", "malformed"),
    ("manual", "missing"),
    ("document_collection", "unsafe"),
    ("transparency", "missing"),
])
def test_known_content_hold_never_masks_invalid_or_elapsed_content(
    document_type, mutation,
):
    value = _content_shape(document_type)
    if mutation == "elapsed":
        value["details"]["release_timestamp"] = "2026-09-08T09:30:00Z"
    elif mutation == "malformed":
        value["details"]["release_timestamp"] = "not-a-time"
    elif document_type == "manual":
        value["details"]["child_section_groups"] = []
    elif document_type == "document_collection":
        value["links"]["documents"][0]["base_path"] = "//external.example/item"
    else:
        value["details"]["attachments"] = []
        value["links"]["children"] = []
    with pytest.raises(ValueError) as caught:
        parse_govuk_content_document(
            "https://www.gov.uk/government/example", json.dumps(value).encode(),
            retrieved_at=datetime(2026, 9, 9, tzinfo=UTC),
        )
    assert type(caught.value) is ValueError


def _request(system, unit):
    version = system.sources.version_details(
        SourceDefinitionVersionId.parse(unit.authority.definition_version_id), proof=proof(),
    )
    return EvidenceAcquisitionRequest(
        unit.source_id, unit.authority.definition_id, unit.authority.definition_version_id,
        version.canonical_digest, unit.authority.revision_id,
        "https://www.gov.uk/government/news/official-update", POLICY_DIGEST,
    )


@pytest.mark.parametrize("url", [
    "http://www.gov.uk/government/news/x", "https://www.gov.uk.evil.test/x",
    "https://www.gov.uk@127.0.0.1/x", "https://www.gov.uk:443/x",
    "https://www.gov.uk/x?url=http://127.0.0.1", "https://www.gov.uk/x#other",
    "https://www.gov.uk/api/content/x", "https://www.gov.uk/%2e%2e/x",
    "https://www.gov.uk/%2f%2fother/x", "https://www.gov.uk/x%0d%0ay",
])
def test_govuk_route_rejects_ambiguous_or_external_urls(url):
    with pytest.raises(ValueError):
        _api_url(url)


def test_govuk_acquisition_binds_the_composed_transport_policy():
    policy = digest_canonical({"transport": "composed"})
    acquire = GovUkEvidenceAcquisition(
        sources=None, proof=proof(), dispatch_fence=lambda _: nullcontext(),
        transport_policy_digest=policy,
    )
    assert acquire._transport_policy_digest == policy
    with pytest.raises(ValueError):
        GovUkEvidenceAcquisition(
            sources=None, proof=proof(), dispatch_fence=lambda _: nullcontext(),
            transport_policy_digest="not-a-digest",
        )


def test_exact_native_source_fetches_bounded_independent_content(tmp_path, monkeypatch):
    with open_discovery_system(tmp_path / "authority.sqlite3", clock=lambda: NOW) as system:
        unit = replace(_unit(), source_definition_url="https://www.gov.uk/government/organisations/home-office.atom")
        _seed(system, unit)
        request = _request(system, unit)
        calls, held = [], []
        raw = json.dumps(_document("/government/news/official-update")).encode()
        class FencedResponse(Response):
            def read(self, *args):
                assert held == [request]
                return super().read(*args)
        class Opener:
            def open(self, http, timeout):
                assert held == [request]
                calls.append((http.full_url, timeout, http.get_method()))
                return FencedResponse(raw, http.full_url)
        monkeypatch.setattr("urllib.request.build_opener", lambda *args: Opener())
        fenced = []
        @contextmanager
        def fence(request):
            fenced.append(request)
            held.append(request)
            try:
                yield
            finally:
                held.pop()
        acquire = GovUkEvidenceAcquisition(
            sources=system.sources, proof=proof(), dispatch_fence=fence,
            clock=lambda: datetime(2026, 9, 2, 12, 2, tzinfo=UTC),
        )
        result = acquire(request)
        assert fenced == [request] and held == []
        assert calls == [("https://www.gov.uk/api/content/government/news/official-update", 20, "GET")]
        assert result.body == b"Official update\n\nExact independent source text."
        assert result.request_digest == request.digest
        assert result.publisher == "Home Office"
        assert result.publication_time == "2026-09-01T10:00:00.000000Z"
        assert result.source_updated_time == "2026-09-02T10:00:00.000000Z"
        assert result.retrieval_time == "2026-09-02T12:02:00.000000Z"
        assert result.outcome == "COMPLETE"
        assert result.body != unit.body.encode()
        assert result.receipt_digest != result.transport_evidence_digest
        with pytest.raises(NativeEvidenceHold, match="POLICY_MISMATCH"):
            acquire(replace(request, transport_policy_digest="sha256:" + "0" * 64))
        assert len(calls) == 1


def test_govuk_transport_unavailable_then_succeeds_without_changing_request(
    tmp_path, monkeypatch
):
    with open_discovery_system(
        tmp_path / "authority.sqlite3", clock=lambda: NOW
    ) as system:
        unit = replace(
            _unit(),
            source_definition_url=(
                "https://www.gov.uk/government/organisations/home-office.atom"
            ),
        )
        _seed(system, unit)
        request = _request(system, unit)
        raw = json.dumps(_document("/government/news/official-update")).encode()
        calls = []

        class Opener:
            def open(self, http, timeout):
                calls.append((http.full_url, timeout))
                if len(calls) == 1:
                    raise urllib.error.URLError("temporary source failure")
                return Response(raw, http.full_url)

        monkeypatch.setattr("urllib.request.build_opener", lambda *args: Opener())
        acquire = GovUkEvidenceAcquisition(
            sources=system.sources,
            proof=proof(),
            dispatch_fence=lambda _: nullcontext(),
            clock=lambda: datetime(2026, 9, 2, 12, 2, tzinfo=UTC),
        )

        with pytest.raises(
            NativeEvidenceHold, match="GOVUK_ACQUISITION_UNAVAILABLE"
        ):
            acquire(request)
        result = acquire(request)

        assert result.request_digest == request.digest
        assert result.outcome == "COMPLETE"
        assert len(calls) == 2


@pytest.mark.parametrize("failure", ["too_large", "wrong_path", "missing_date", "future_date", "no_body", "redirect", "duplicate_json"])
def test_incomplete_source_response_is_never_complete(tmp_path, monkeypatch, failure):
    with open_discovery_system(tmp_path / "authority.sqlite3", clock=lambda: NOW) as system:
        unit = replace(_unit(), source_definition_url="https://www.gov.uk/government/organisations/home-office.atom")
        _seed(system, unit)
        request = _request(system, unit)
        document = _document("/government/news/official-update")
        if failure == "wrong_path": document["base_path"] = "/other"
        if failure == "missing_date": document.pop("first_published_at")
        if failure == "future_date": document["public_updated_at"] = "2027-01-01T00:00:00Z"
        if failure == "no_body": document["details"] = {}
        raw = json.dumps(document).encode()
        if failure == "too_large": raw = b"x" * (MAX_BODY_BYTES + 1)
        if failure == "duplicate_json": raw = b'{"base_path":"a","base_path":"b"}'
        class Opener:
            def open(self, http, timeout):
                return Response(raw, "https://other.test" if failure == "redirect" else http.full_url)
        monkeypatch.setattr("urllib.request.build_opener", lambda *args: Opener())
        acquire = GovUkEvidenceAcquisition(
            sources=system.sources, proof=proof(), dispatch_fence=lambda _: nullcontext(),
            clock=lambda: datetime(2026, 9, 2, 12, 2, tzinfo=UTC),
        )
        with pytest.raises(NativeEvidenceHold):
            acquire(request)


def test_explicit_exclusions_are_signals_not_invented_semantic_passes():
    from newsroom.control_plane.govuk_evidence import _exclusion_signals
    assert _exclusion_signals({"details": {}}, "Government published an update.") == ()
    assert _exclusion_signals({"details": {"copyright_notice": "Third-party copyright"}}, "Update") == ("THIRD_PARTY_RIGHTS",)
    assert _exclusion_signals({"details": {}}, "This material is not covered by the Open Government Licence.") == ("NON_OGL_CONTENT",)
    assert _exclusion_signals({"details": {"personal_information": True}}, "Details") == ("EXCLUDED_PERSONAL_OR_IDENTITY_CONTENT",)


def test_acquisition_facts_are_in_the_exact_retained_receipt():
    from newsroom.authority.canonical import digest_bytes
    from newsroom.control_plane.native_evidence import AcquiredEvidence, NativeEvidenceError
    result = AcquiredEvidence.create(
        request_digest=digest_bytes(b"request"), outcome="COMPLETE",
        canonical_url="https://www.gov.uk/government/news/update", body=b"Update",
        body_digest=digest_bytes(b"Update"), publisher="Home Office",
        responsible_body="Home Office", source_type="PRIMARY_OFFICIAL",
        publication_time="2026-09-01T10:00:00Z", source_updated_time="2026-09-01T10:00:00Z",
        retrieval_time="2026-09-01T11:00:00Z", geography="UK", language="en-GB",
        transport_evidence_digest=digest_bytes(b"transport"),
        currentness_basis="AUTHORITATIVE_CURRENT_CONTENT_ENDPOINT",
        rights_eligibility_digest=digest_bytes(b"reviewed terms and exact source"),
        licence_attribution="Observed attribution", exclusion_signals=(), text_only=True,
    )
    for changes in ({"currentness_basis": ""}, {"rights_eligibility_digest": ""},
                    {"licence_attribution": ""}, {"text_only": False},
                    {"exclusion_signals": ("THIRD_PARTY_RIGHTS",)}):
        with pytest.raises(NativeEvidenceError, match="receipt differs"):
            replace(result, **changes)


def test_native_evidence_origin_comparison_rejects_embedded_credentials():
    from newsroom.control_plane.native_evidence import _same_https_origin
    assert _same_https_origin("https://www.gov.uk/a", "https://www.gov.uk/feed")
    assert not _same_https_origin("https://user:password@www.gov.uk/a", "https://www.gov.uk/feed")
    assert not _same_https_origin("https://www.gov.uk/a", "https://user:password@www.gov.uk/feed")


def test_maintained_guide_includes_every_part_and_rejects_partial_parts():
    from newsroom.control_plane.govuk_evidence import _document_text
    value = {"document_type": "guide", "details": {"parts": [
        {"title": f"Part {number}", "slug": f"part-{number}",
         "body": f"<p>Exact text {number}.</p>"}
        for number in range(1, 10)
    ]}}
    text = _document_text(value)
    assert len(value["details"]["parts"]) == 9
    assert all(f"Part {number}\nExact text {number}." in text for number in range(1, 10))
    value["details"]["parts"][1]["body"] = ""
    with pytest.raises(ValueError, match="absent"):
        _document_text(value)
    value["details"]["parts"][1]["body"] = "Text"
    value["details"]["parts"][1]["slug"] = "part-1"
    with pytest.raises(ValueError, match="identity"):
        _document_text(value)


def test_manual_inventory_requires_every_unique_child_section():
    from newsroom.control_plane.govuk_evidence import parse_govuk_manual_inventory

    value = {
        "base_path": "/guidance/immigration-rules", "locale": "en",
        "document_type": "manual", "title": "Immigration Rules",
        "first_published_at": "2020-01-01T00:00:00Z",
        "public_updated_at": "2026-09-08T10:00:00Z",
        "withdrawn_notice": None,
        "details": {"child_section_groups": [
            {"title": "Rules", "child_sections": [
                {"base_path": "/guidance/immigration-rules/part-1", "title": "Part 1"},
                {"base_path": "/guidance/immigration-rules/part-2", "title": "Part 2"},
            ]},
        ]},
        "links": {"organisations": [{"title": "Home Office"}]},
    }
    raw = json.dumps(value).encode()
    inventory = parse_govuk_manual_inventory(
        "https://www.gov.uk/guidance/immigration-rules", raw,
        retrieved_at=datetime(2026, 9, 8, 11, tzinfo=UTC),
    )
    assert inventory.sections == (
        ("/guidance/immigration-rules/part-1", "Part 1"),
        ("/guidance/immigration-rules/part-2", "Part 2"),
    )
    value["details"]["child_section_groups"][0]["child_sections"][1]["base_path"] = (
        "/guidance/immigration-rules/part-1"
    )
    with pytest.raises(ValueError, match="incomplete"):
        parse_govuk_manual_inventory(
            "https://www.gov.uk/guidance/immigration-rules", json.dumps(value).encode(),
            retrieved_at=datetime(2026, 9, 8, 11, tzinfo=UTC),
        )
