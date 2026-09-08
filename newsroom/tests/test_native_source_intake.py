import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from newsroom.authority import ObjectAdmissionId
from newsroom.control_plane.govuk_rights import GovUkLicenceEvidence, POLICY_DIGEST
from newsroom.control_plane.graphiti_operational_readiness import _source_requests
from newsroom.control_plane.graphiti_operational_readiness import (
    OPERATOR_AUTHORITY_DOMAIN,
    OPERATOR_PRINCIPAL_ID,
)
from newsroom.control_plane.native_runtime import open_native_runtime
from newsroom.control_plane.native_evidence import NativeEvidenceHold
from newsroom.control_plane.native_source_intake import (
    NativeSourceIntake, _fetch_exact, native_evidence_sources,
)
from newsroom.control_plane.native_source_definitions import (
    native_source_definition_requests,
)
from newsroom.increment9.proving import MAX_BODY_BYTES, SOURCE_IDS, SOURCE_URLS
from newsroom.sources import SourceItemId, SourceRevisionId
from newsroom.tests.test_graphiti_operational_readiness import _rights, _unit
from newsroom.tests.test_native_runtime import _args

ATOM = b'''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><id>item-1</id><title>Visa rules updated</title><summary>The official deadline changed.</summary><link href="https://www.gov.uk/item-1"/><published>2026-09-08T10:00:00Z</published><updated>2026-09-08T11:00:00Z</updated></entry></feed>'''


def _document(*, body="The complete maintained-page text.", updated="2026-09-08T11:00:00Z", path="/item-1"):
    return json.dumps({
        "base_path": path,
        "locale": "en",
        "document_type": "news_story",
        "withdrawn_notice": None,
        "first_published_at": "2026-09-08T10:00:00Z",
        "public_updated_at": updated,
        "title": "Visa rules updated",
        "details": {"body": f"<p>{body}</p>"},
        "links": {"organisations": [{"title": "Home Office"}]},
    }, separators=(",", ":")).encode()


def _licence():
    return GovUkLicenceEvidence(
        (
            ObjectAdmissionId.parse("00000000-0000-4000-8000-000000000101"),
            ObjectAdmissionId.parse("00000000-0000-4000-8000-000000000102"),
        ),
        ("sha256:" + "1" * 64, "sha256:" + "2" * 64),
        "2026-09-08T09:00:00.000000Z",
        POLICY_DIGEST,
    )


def _seed_uk01(runtime):
    unit = replace(_unit(), source_definition_url=SOURCE_URLS["UK-01"])
    definition, version, *_ = _source_requests(unit, _rights())
    runtime.authority.sources.register_definition(definition, proof=runtime.proof)
    runtime.authority.sources.record_definition_version(version, proof=runtime.proof)
    return definition.definition_id


def _seed_missing(runtime, source_id):
    requests = native_source_definition_requests(
        source_id=source_id,
        rights=_licence().for_source(
            source_id=source_id, definition_url=SOURCE_URLS[source_id],
        ),
    )
    runtime.authority.sources.register_definition(requests.definition, proof=runtime.proof)
    runtime.authority.sources.record_definition_version(requests.version, proof=runtime.proof)
    return requests.definition.definition_id


def _guide():
    return json.dumps({
        "base_path": "/british-national-overseas-bno-visa", "locale": "en",
        "document_type": "guide", "title": "British National (Overseas) visa",
        "first_published_at": "2020-01-01T00:00:00Z",
        "public_updated_at": "2026-09-08T10:00:00Z", "withdrawn_notice": None,
        "details": {"parts": [
            {"title": f"Part {number}", "slug": f"part-{number}",
             "body": f"<p>Complete guide text {number}.</p>"}
            for number in range(1, 10)
        ]},
        "links": {"organisations": [{"title": "Home Office"}]},
    }).encode()


def _manual():
    return json.dumps({
        "base_path": "/guidance/immigration-rules", "locale": "en",
        "document_type": "manual", "title": "Immigration Rules",
        "first_published_at": "2020-01-01T00:00:00Z",
        "public_updated_at": "2026-09-08T10:00:00Z", "withdrawn_notice": None,
        "details": {"child_section_groups": [{"title": "Rules", "child_sections": [
            {"base_path": "/guidance/immigration-rules/part-1", "title": "Part 1"},
            {"base_path": "/guidance/immigration-rules/part-2", "title": "Part 2"},
        ]}]},
        "links": {"organisations": [{"title": "Home Office"}]},
    }).encode()


def _manual_section(number):
    return json.dumps({
        "base_path": f"/guidance/immigration-rules/part-{number}", "locale": "en",
        "document_type": "manual_section", "title": f"Part {number}",
        "first_published_at": "2020-01-01T00:00:00Z",
        "public_updated_at": "2026-09-08T10:00:00Z", "withdrawn_notice": None,
        "details": {"body": f"<p>Complete rules section {number}.</p>",
                    "manual": {"organisations": [{"title": "Home Office"}]}},
        "links": {},
    }).encode()


def test_native_source_poll_retains_real_lineage_replay_and_all_dispositions(
    tmp_path, monkeypatch,
):
    args = _args(tmp_path, monkeypatch)
    args["principal_id"] = OPERATOR_PRINCIPAL_ID
    args["authority_domain"] = OPERATOR_AUTHORITY_DOMAIN
    page = [_document()]
    fences = []
    instant = [datetime(2026, 9, 8, 12, tzinfo=UTC)]

    with open_native_runtime(**args) as runtime:
        definition_id = _seed_uk01(runtime)
        intake = NativeSourceIntake(
            sources=runtime.authority.sources, objects=runtime.authority.objects,
            proof=runtime.proof, definition_ids={"UK-01": definition_id},
            licence=_licence(), dispatch_fence=lambda source, url: fences.append((source, url)),
            fetch=lambda url: (200, ATOM if url == SOURCE_URLS["UK-01"] else page[0]),
            clock=lambda: instant[0],
        )
        first = intake.poll()
        assert tuple(item.source_id for item in first) == SOURCE_IDS
        assert len(first) == 10
        assert first[0].status == "READY" and first[0].units, first[0]
        assert all(item.status == "HOLD" for item in first[1:])
        unit = first[0].units[0]
        assert unit.proving_run_id.startswith("native-source:sha256:")
        assert unit.authority is not None
        assert unit.body == "The complete maintained-page text."
        assert len(first[0].observations) == 2
        evidence_sources = native_evidence_sources(
            units=first[0].units, sources=runtime.authority.sources,
            objects=runtime.authority.objects,
            observations={item[1]: item for item in first[0].observations},
            licence=_licence(), proof=runtime.proof,
        )
        assert len(evidence_sources) == 1
        assert evidence_sources[0].unit == unit
        assert evidence_sources[0].dependency.dependency_status == "RESOLVED"
        assert evidence_sources[0].dependency.evidential_origin_id == unit.observation_digest
        with pytest.raises(NativeEvidenceHold, match="NATIVE_SOURCE_CHUNK_BINDING_HOLD"):
            native_evidence_sources(
                units=(replace(unit, observation_digest="sha256:" + "f" * 64),),
                sources=runtime.authority.sources, objects=runtime.authority.objects,
                observations={item[1]: item for item in first[0].observations},
                licence=_licence(), proof=runtime.proof,
            )
        bad_observations = {item[1]: item for item in first[0].observations}
        bad_observations[unit.observation_digest] = (
            "https://www.gov.uk/api/content/unrelated",
            *bad_observations[unit.observation_digest][1:],
        )
        with pytest.raises(NativeEvidenceHold, match="NATIVE_SOURCE_AUTHORITY_HOLD"):
            native_evidence_sources(
                units=first[0].units, sources=runtime.authority.sources,
                objects=runtime.authority.objects, observations=bad_observations,
                licence=_licence(), proof=runtime.proof,
            )
        old_revision = unit.authority.revision_id

        replay = intake.poll()[0].units[0]
        assert replay.ingest_id == unit.ingest_id
        assert replay.authority.revision_id == old_revision

        page[0] = _document(body="A changed complete document.", updated="2026-09-08T12:30:00Z")
        instant[0] = datetime(2026, 9, 8, 13, tzinfo=UTC)
        changed = intake.poll()[0].units[0]
        assert changed.authority.revision_id != old_revision
        retained = runtime.authority.sources.revision(
            SourceRevisionId.parse(changed.authority.revision_id), proof=runtime.proof
        )
        assert str(retained.request.prior_revision_id) == old_revision
        latest = runtime.authority.sources.latest_revision(
            SourceItemId.parse(changed.authority.item_id), proof=runtime.proof
        )
        assert latest == retained
        # Re-observing the second revision must retain its predecessor, rather
        # than rewriting the original immutable request as a first revision.
        assert intake.poll()[0].units[0].authority.revision_id == changed.authority.revision_id

        page[0] = _document(updated="2026-09-08T14:00:00Z")
        instant[0] = datetime(2026, 9, 8, 15, tzinfo=UTC)
        returned = intake.poll()[0].units[0]
        assert returned.authority.revision_id not in {
            old_revision, changed.authority.revision_id,
        }
        returned_revision = runtime.authority.sources.revision(
            SourceRevisionId.parse(returned.authority.revision_id), proof=runtime.proof
        )
        assert str(returned_revision.request.prior_revision_id) == changed.authority.revision_id
        assert returned.revision_digest == unit.revision_digest
        assert returned_revision.request.observed_at.to_text() == "2026-09-08T15:00:00.000000Z"
        assert fences == [
            item
            for _ in range(5)
            for item in (
                ("UK-01", SOURCE_URLS["UK-01"]),
                ("UK-01", "https://www.gov.uk/api/content/item-1"),
            )
        ]
        # A new source version with unchanged text is still observed now; it
        # must not borrow the preceding version's observation timestamp.
        page[0] = _document(updated="2026-09-08T16:00:00Z")
        instant[0] = datetime(2026, 9, 8, 17, tzinfo=UTC)
        metadata_only = intake.poll()[0].units[0]
        metadata_revision = runtime.authority.sources.revision(
            SourceRevisionId.parse(metadata_only.authority.revision_id), proof=runtime.proof
        )
        assert str(metadata_revision.request.prior_revision_id) == returned.authority.revision_id
        assert metadata_revision.request.observed_at.to_text() == "2026-09-08T17:00:00.000000Z"
        assert metadata_only.revision_digest == returned.revision_digest


def test_native_source_poll_holds_oversize_and_duplicate_native_revision(tmp_path, monkeypatch):
    args = _args(tmp_path, monkeypatch)
    args["principal_id"] = OPERATOR_PRINCIPAL_ID
    args["authority_domain"] = OPERATOR_AUTHORITY_DOMAIN
    feed = [ATOM]
    page = [_document()]

    with open_native_runtime(**args) as runtime:
        definition_id = _seed_uk01(runtime)
        intake = NativeSourceIntake(
            sources=runtime.authority.sources, objects=runtime.authority.objects,
            proof=runtime.proof, definition_ids={"UK-01": definition_id},
            licence=_licence(), dispatch_fence=lambda *_: None,
            fetch=lambda url: (200, feed[0] if url == SOURCE_URLS["UK-01"] else page[0]),
            clock=lambda: datetime(2026, 9, 8, 12, tzinfo=UTC),
        )
        assert intake.poll()[0].status == "READY"

        page[0] = _document(body="Different bytes.")
        duplicate = intake.poll()[0]
        assert duplicate.status == "HOLD"
        assert duplicate.reason_code == "SOURCE_ITEMS_HELD"
        assert duplicate.item_holds == ((
            "https://www.gov.uk/item-1", "SOURCE_NATIVE_REVISION_CONFLICT",
        ),)
        assert not duplicate.units

        page[0] = b"x" * (MAX_BODY_BYTES + 1)
        oversized_page = intake.poll()[0]
        assert oversized_page.reason_code == "SOURCE_ITEMS_HELD"
        assert oversized_page.item_holds[0][1] == "SOURCE_ITEM_BODY_TOO_LARGE"
        assert oversized_page.observation_admission_id is not None

        feed[0] = b"x" * (MAX_BODY_BYTES + 1)
        oversized = intake.poll()[0]
        assert oversized.status == "HOLD"
        assert oversized.reason_code == "SOURCE_BODY_TOO_LARGE"
        assert oversized.observation_admission_id is None


def test_native_source_poll_preserves_completed_items_when_later_item_holds(
    tmp_path, monkeypatch,
):
    args = _args(tmp_path, monkeypatch)
    args["principal_id"] = OPERATOR_PRINCIPAL_ID
    args["authority_domain"] = OPERATOR_AUTHORITY_DOMAIN
    second = ATOM.split(b"<entry>", 1)[1].replace(
        b"item-1", b"item-2"
    ).replace(b"/item-1", b"/item-2")
    body = [ATOM.replace(b"</feed>", b"<entry>" + second)]

    with open_native_runtime(**args) as runtime:
        definition_id = _seed_uk01(runtime)
        intake = NativeSourceIntake(
            sources=runtime.authority.sources, objects=runtime.authority.objects,
            proof=runtime.proof, definition_ids={"UK-01": definition_id},
            licence=_licence(), dispatch_fence=lambda *_: None,
            fetch=lambda url: (
                (200, body[0]) if url == SOURCE_URLS["UK-01"]
                else (200, _document()) if url.endswith("/item-1")
                else (200, b'{}')
            ),
            clock=lambda: datetime(2026, 9, 8, 12, tzinfo=UTC),
        )
        held = intake.poll()[0]
        assert held.status == "HOLD"
        assert held.reason_code == "SOURCE_ITEMS_HELD"
        assert held.item_holds == ((
            "https://www.gov.uk/item-2", "SOURCE_ITEM_METADATA_HOLD",
        ),)
        assert held.units
        assert len(held.observations) == 3
        retained = held.units[0]
        latest = runtime.authority.sources.latest_revision(
            SourceItemId.parse(retained.authority.item_id), proof=runtime.proof
        )
        assert str(latest.request.revision_id) == retained.authority.revision_id

        body[0] = ATOM
        replay = intake.poll()[0]
        assert replay.status == "READY"
        assert replay.units[0].authority.revision_id == retained.authority.revision_id


def test_native_exact_fetch_rejects_any_endpoint_outside_fixed_portfolio():
    try:
        _fetch_exact("https://example.com/not-approved")
    except ValueError as exc:
        assert str(exc) == "native source endpoint is not approved"
    else:
        raise AssertionError("unapproved endpoint was fetched")


def test_native_bno_guide_retains_all_nine_parts_as_one_revision(tmp_path, monkeypatch):
    args = _args(tmp_path, monkeypatch)
    args["principal_id"] = OPERATOR_PRINCIPAL_ID
    args["authority_domain"] = OPERATOR_AUTHORITY_DOMAIN
    with open_native_runtime(**args) as runtime:
        definition_id = _seed_missing(runtime, "UK-02")
        intake = NativeSourceIntake(
            sources=runtime.authority.sources, objects=runtime.authority.objects,
            proof=runtime.proof, definition_ids={"UK-02": definition_id},
            licence=_licence(), dispatch_fence=lambda *_: None,
            fetch=lambda _: (200, _guide()),
            clock=lambda: datetime(2026, 9, 8, 12, tzinfo=UTC),
        )
        disposition = intake.poll()[SOURCE_IDS.index("UK-02")]
        assert disposition.status == "READY"
        assert len(disposition.observations) == 1
        text = disposition.units[0].body
        assert all(f"Part {number}\nComplete guide text {number}." in text
                   for number in range(1, 10))
        assert len({unit.authority.revision_id for unit in disposition.units}) == 1


def test_native_manual_retains_every_section_and_root_inventory(tmp_path, monkeypatch):
    args = _args(tmp_path, monkeypatch)
    args["principal_id"] = OPERATOR_PRINCIPAL_ID
    args["authority_domain"] = OPERATOR_AUTHORITY_DOMAIN
    bodies = {
        SOURCE_URLS["UK-03"]: _manual(),
        "https://www.gov.uk/api/content/guidance/immigration-rules/part-1": _manual_section(1),
        "https://www.gov.uk/api/content/guidance/immigration-rules/part-2": _manual_section(2),
    }
    with open_native_runtime(**args) as runtime:
        definition_id = _seed_missing(runtime, "UK-03")
        intake = NativeSourceIntake(
            sources=runtime.authority.sources, objects=runtime.authority.objects,
            proof=runtime.proof, definition_ids={"UK-03": definition_id},
            licence=_licence(), dispatch_fence=lambda *_: None,
            fetch=lambda url: (200, bodies[url]),
            clock=lambda: datetime(2026, 9, 8, 12, tzinfo=UTC),
        )
        disposition = intake.poll()[SOURCE_IDS.index("UK-03")]
        assert disposition.status == "READY"
        assert len(disposition.observations) == 3
        revision_units = {}
        for unit in disposition.units:
            revision_units.setdefault(unit.revision_id, []).append(unit)
        assert len(revision_units) == 2
        assert {units[0].canonical_url for units in revision_units.values()} == {
            "https://www.gov.uk/guidance/immigration-rules/part-1",
            "https://www.gov.uk/guidance/immigration-rules/part-2",
        }
        observations = {item[1]: item for item in disposition.observations}
        for units in revision_units.values():
            assert native_evidence_sources(
                units=tuple(units), sources=runtime.authority.sources,
                objects=runtime.authority.objects, observations=observations,
                licence=_licence(), proof=runtime.proof,
            )
        root = disposition.units[0].item_key.split("|", 1)[0]
        tampered = dict(observations)
        tampered.pop(root)
        with pytest.raises(NativeEvidenceHold, match="NATIVE_SOURCE_AUTHORITY_HOLD"):
            native_evidence_sources(
                units=tuple(next(iter(revision_units.values()))),
                sources=runtime.authority.sources, objects=runtime.authority.objects,
                observations=tampered, licence=_licence(), proof=runtime.proof,
            )


def test_native_manual_keeps_successful_sections_when_one_child_holds(tmp_path, monkeypatch):
    args = _args(tmp_path, monkeypatch)
    args["principal_id"] = OPERATOR_PRINCIPAL_ID
    args["authority_domain"] = OPERATOR_AUTHORITY_DOMAIN
    with open_native_runtime(**args) as runtime:
        definition_id = _seed_missing(runtime, "UK-03")
        intake = NativeSourceIntake(
            sources=runtime.authority.sources, objects=runtime.authority.objects,
            proof=runtime.proof, definition_ids={"UK-03": definition_id},
            licence=_licence(), dispatch_fence=lambda *_: None,
            fetch=lambda url: (
                (200, _manual()) if url == SOURCE_URLS["UK-03"]
                else (200, _manual_section(1)) if url.endswith("part-1")
                else (503, b"")
            ),
            clock=lambda: datetime(2026, 9, 8, 12, tzinfo=UTC),
        )
        disposition = intake.poll()[SOURCE_IDS.index("UK-03")]
        assert disposition.status == "HOLD"
        assert disposition.item_holds == ((
            "https://www.gov.uk/guidance/immigration-rules/part-2",
            "SOURCE_ITEM_FETCH_INCOMPLETE",
        ),)
        assert disposition.units


@pytest.mark.parametrize("stop_at", [1, 2])
def test_native_source_stop_propagates_at_feed_and_item_boundaries(tmp_path, monkeypatch, stop_at):
    from newsroom.control_plane.veto import VetoError
    args = _args(tmp_path, monkeypatch)
    args["principal_id"] = OPERATOR_PRINCIPAL_ID
    args["authority_domain"] = OPERATOR_AUTHORITY_DOMAIN
    fences, fetches = [], []
    def fence(source_id, url):
        fences.append(url)
        if len(fences) == stop_at:
            raise VetoError("owner stop")
    def fetch(url):
        fetches.append(url)
        return (200, ATOM if url == SOURCE_URLS["UK-01"] else _document())
    with open_native_runtime(**args) as runtime:
        definition_id = _seed_uk01(runtime)
        intake = NativeSourceIntake(
            sources=runtime.authority.sources, objects=runtime.authority.objects,
            proof=runtime.proof, definition_ids={"UK-01": definition_id},
            licence=_licence(), dispatch_fence=fence, fetch=fetch,
            clock=lambda: datetime(2026, 9, 8, 12, tzinfo=UTC),
        )
        with pytest.raises(VetoError, match="owner stop"):
            intake.poll()
    assert len(fences) == stop_at
    assert len(fetches) == stop_at - 1
