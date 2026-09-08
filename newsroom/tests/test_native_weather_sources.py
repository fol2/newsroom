import json
from datetime import UTC, datetime

import pytest

from newsroom.control_plane.native_weather_sources import weather_items

NOW = datetime(2026, 9, 8, 15, tzinfo=UTC)
RSS = b'<rss version="2.0"><channel><title>Met Office warnings for UK</title>{}</channel></rss>'


def test_complete_empty_weather_inventory_is_not_a_parse_error():
    assert weather_items("HK-02", b'{}', observed_at=NOW) == ()
    assert weather_items("UK-10", RSS.replace(b'{}', b''), observed_at=NOW) == ()


def test_hko_retains_every_field_and_exact_source_times():
    warning = {"name": "雷暴警告", "code": "WTS", "actionCode": "ISSUE",
               "issueTime": "2026-09-08T11:00:00+08:00", "updateTime": "2026-09-08T12:00:00+08:00",
               "expireTime": "2026-09-08T23:00:00+08:00", "additional_field": "retained"}
    items = weather_items("HK-02", json.dumps({"WTS": warning}).encode(), observed_at=NOW)
    assert len(items) == 1 and json.loads(items[0].retained_corpus_body) == {"WTS": warning}
    assert items[0].updated_at == "2026-09-08T04:00:00.000000Z"
    assert items[0].published_at == "2026-09-08T03:00:00.000000Z"
    warning.pop("updateTime")
    with pytest.raises(ValueError): weather_items("HK-02", json.dumps({"WTS": warning}).encode(), observed_at=NOW)
    with pytest.raises(ValueError): weather_items("HK-02", b'{"WTS":{},"WTS":{}}', observed_at=NOW)


def test_metoffice_retains_full_entry_without_inventing_updated_time():
    entry = b'<item><title>Rain warning</title><guid>one</guid><link>https://weather.metoffice.gov.uk/warnings</link><pubDate>Tue, 08 Sep 2026 12:00:00 GMT</pubDate><description>Full supplied summary</description><extra>Not discarded</extra></item>'
    items = weather_items("UK-10", RSS.replace(b'{}', entry), observed_at=NOW)
    assert items[0].updated_at is None and items[0].published_at == "2026-09-08T12:00:00.000000Z"
    assert '<extra>Not discarded</extra>' in items[0].retained_corpus_body
    with pytest.raises(ValueError): weather_items("UK-10", RSS.replace(b'{}', entry + entry), observed_at=NOW)
    with pytest.raises(ValueError): weather_items("UK-10", RSS.replace(b'{}', entry.replace(b'weather.metoffice.gov.uk', b'example.org')), observed_at=NOW)
    with pytest.raises(ValueError): weather_items("UK-10", RSS.replace(b'Met Office warnings for UK', b'Another feed'), observed_at=NOW)


def _runtime_arguments(tmp_path, monkeypatch):
    from newsroom.control_plane.graphiti_operational_readiness import (
        OPERATOR_AUTHORITY_DOMAIN,
        OPERATOR_PRINCIPAL_ID,
    )
    from newsroom.tests.test_native_runtime import _args

    arguments = _args(tmp_path, monkeypatch)
    arguments["principal_id"] = OPERATOR_PRINCIPAL_ID
    arguments["authority_domain"] = OPERATOR_AUTHORITY_DOMAIN
    return arguments


def _definition(runtime, source_id, portfolio):
    from dataclasses import replace

    from newsroom.control_plane.graphiti_operational_readiness import (
        _source_requests,
    )
    from newsroom.control_plane.native_source_definitions import (
        native_source_definition_requests,
    )
    from newsroom.increment9.proving import SOURCE_URLS
    from newsroom.tests.test_graphiti_operational_readiness import _rights, _unit

    if source_id == "HK-02":
        requests = native_source_definition_requests(
            source_id=source_id,
            rights=portfolio.for_source(
                source_id=source_id,
                definition_url=SOURCE_URLS[source_id],
            ),
        )
        definition, version = requests.definition, requests.version
    else:
        template = replace(
            _unit(),
            source_id=source_id,
            source_definition_url=SOURCE_URLS[source_id],
        )
        definition, version, *_ = _source_requests(template, _rights())
    runtime.authority.sources.register_definition(definition, proof=runtime.proof)
    runtime.authority.sources.record_definition_version(
        version, proof=runtime.proof
    )
    return definition.definition_id


def _poll(runtime, source_id, raw, portfolio, fences):
    from newsroom.control_plane.native_source_intake import NativeSourceIntake
    from newsroom.control_plane.native_weather_sources import poll_other_source

    holder = {}

    def other_source(**request):
        return poll_other_source(holder["intake"], **request)

    intake = NativeSourceIntake(
        sources=runtime.authority.sources,
        objects=runtime.authority.objects,
        proof=runtime.proof,
        definition_ids={source_id: _definition(runtime, source_id, portfolio)},
        licence=portfolio,
        dispatch_fence=lambda observed_source, url: fences.append(
            (observed_source, url)
        ),
        other_source_poll=other_source,
        fetch=lambda _url: (200, raw),
        clock=lambda: NOW,
    )
    holder["intake"] = intake
    return intake, intake._poll_one(source_id)


@pytest.mark.parametrize(
    ("source_id", "raw"),
    (("HK-02", "HKO"), ("UK-10", "RSS")),
)
def test_real_weather_poll_retains_canonical_evidence_source_and_replays(
    tmp_path, monkeypatch, source_id, raw,
):
    import sqlite3

    from newsroom.control_plane.native_evidence import NativeEvidenceSource
    from newsroom.control_plane.native_runtime import open_native_runtime
    from newsroom.control_plane.native_source_intake import native_evidence_sources
    from newsroom.increment9.proving import SOURCE_URLS
    from newsroom.tests.test_native_weather_evidence import (
        HKO_RAW,
        RSS_RAW,
        _portfolio,
    )

    body = HKO_RAW if raw == "HKO" else RSS_RAW
    with open_native_runtime(**_runtime_arguments(tmp_path, monkeypatch)) as runtime:
        portfolio = _portfolio(runtime, monkeypatch)
        fences = []
        intake, disposition = _poll(
            runtime, source_id, body, portfolio, fences
        )
        assert disposition.status == "READY"
        assert disposition.units
        assert fences == [(source_id, SOURCE_URLS[source_id])]
        observations = {item[1]: item for item in disposition.observations}
        sources = native_evidence_sources(
            units=disposition.units,
            sources=runtime.authority.sources,
            objects=runtime.authority.objects,
            observations=observations,
            licence=portfolio,
            proof=runtime.proof,
        )
        assert len(sources) == 1
        assert type(sources[0]) is NativeEvidenceSource
        assert sources[0].unit.body == disposition.units[0].body
        assert sources[0].unit.observation_digest == disposition.units[0].observation_digest
        revision_id = sources[0].unit.authority.revision_id
        with sqlite3.connect(runtime.authority.authority_store_path) as connection:
            before = connection.execute(
                "SELECT COUNT(*) FROM source_revisions"
            ).fetchone()[0]
        replay = intake._poll_one(source_id)
        assert replay.units[0].authority.revision_id == revision_id
        with sqlite3.connect(runtime.authority.authority_store_path) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM source_revisions"
            ).fetchone()[0] == before


def test_valid_empty_weather_inventories_retain_no_revision(tmp_path, monkeypatch):
    import sqlite3

    from newsroom.control_plane.native_runtime import open_native_runtime
    from newsroom.tests.test_native_weather_evidence import _portfolio

    cases = (
        ("HK-02", b"{}"),
        (
            "UK-10",
            b'<rss version="2.0"><channel><title>Met Office warnings for UK</title></channel></rss>',
        ),
    )
    with open_native_runtime(**_runtime_arguments(tmp_path, monkeypatch)) as runtime:
        portfolio = _portfolio(runtime, monkeypatch)
        for source_id, raw in cases:
            _intake, disposition = _poll(
                runtime, source_id, raw, portfolio, []
            )
            assert disposition.status == "READY"
            assert disposition.reason_code == "NO_ACTIVE_WARNINGS_OBSERVED"
            assert disposition.units == ()
        with sqlite3.connect(runtime.authority.authority_store_path) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM source_revisions"
            ).fetchone()[0] == 0


def test_tampered_weather_observation_mapping_is_a_typed_hold(
    tmp_path, monkeypatch,
):
    from newsroom.control_plane.native_evidence import NativeEvidenceHold
    from newsroom.control_plane.native_runtime import open_native_runtime
    from newsroom.control_plane.native_source_intake import native_evidence_sources
    from newsroom.tests.test_native_weather_evidence import HKO_RAW, _portfolio

    with open_native_runtime(**_runtime_arguments(tmp_path, monkeypatch)) as runtime:
        portfolio = _portfolio(runtime, monkeypatch)
        _intake, disposition = _poll(
            runtime, "HK-02", HKO_RAW, portfolio, []
        )
        observations = {item[1]: item for item in disposition.observations}
        digest = disposition.units[0].observation_digest
        observations[digest] = (
            "https://example.invalid/weather",
            *observations[digest][1:],
        )
        with pytest.raises(
            NativeEvidenceHold, match="NATIVE_SOURCE_AUTHORITY_HOLD:HK-02"
        ):
            native_evidence_sources(
                units=disposition.units,
                sources=runtime.authority.sources,
                objects=runtime.authority.objects,
                observations=observations,
                licence=portfolio,
                proof=runtime.proof,
            )
