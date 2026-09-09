from __future__ import annotations

from contextlib import contextmanager, nullcontext

import io
import json
from dataclasses import replace
from datetime import UTC, datetime
from email.message import Message

import pytest

from newsroom.authority import ObjectAdmissionRequest, UtcTimestamp
from newsroom.authority.canonical import digest_bytes, digest_canonical
from newsroom.control_plane.graphiti_operational_readiness import (
    OPERATOR_AUTHORITY_DOMAIN,
    OPERATOR_PRINCIPAL_ID,
    _source_requests,
)
from newsroom.control_plane.native_evidence import (
    EvidenceAcquisitionRequest,
    NativeEvidenceHold,
)
from newsroom.control_plane.native_runtime import open_native_runtime
from newsroom.control_plane.native_source_rights import (
    NativePortfolioRights,
    SourceTermsEvidence,
)
from newsroom.control_plane.native_source_definitions import (
    native_source_definition_requests,
)
from newsroom.control_plane.native_weather_evidence import (
    HK02_ATTRIBUTION,
    POLICY_DIGEST,
    NativeWeatherEvidenceAcquisition,
)
from newsroom.increment9.proving import SOURCE_URLS
from newsroom.tests.test_graphiti_operational_readiness import _rights, _unit
from newsroom.tests.test_native_runtime import _args
from newsroom.tests.test_native_source_intake import _licence
from newsroom.graphiti_adapter.identity import content_digest
from newsroom.sources import (
    IdentityComponent,
    SourceItemId,
    SourceItemIdentityKind,
    SourceItemRequest,
    SourceRevisionId,
    SourceRevisionRequest,
    SourceTime,
)

NOW = datetime(2026, 9, 8, 15, tzinfo=UTC)
CONTROLLER_POLICY_DIGEST = digest_canonical(
    {"govuk": "component-policy", "weather": POLICY_DIGEST}
)
HKO_WARNING = {
    "name": "雷暴警告",
    "code": "WTS",
    "actionCode": "ISSUE",
    "issueTime": "2026-09-08T11:00:00+08:00",
    "updateTime": "2026-09-08T12:00:00+08:00",
    "expireTime": "2026-09-08T23:00:00+08:00",
    "additional_field": "retained",
}
HKO_RAW = json.dumps(
    {"WTS": HKO_WARNING}, ensure_ascii=False, separators=(",", ":"),
).encode()
RSS_ENTRY = (
    b"<item><title>Rain warning</title><guid>one</guid>"
    b"<link>https://weather.metoffice.gov.uk/warnings</link>"
    b"<pubDate>Tue, 08 Sep 2026 12:00:00 GMT</pubDate>"
    b"<description>Full supplied summary</description>"
    b"<extra>Not discarded</extra></item>"
)
RSS_RAW = (
    b'<rss version="2.0"><channel><title>Met Office warnings for UK</title>'
    + RSS_ENTRY
    + b"</channel></rss>"
)


class _Response(io.BytesIO):
    status = 200

    def __init__(self, raw: bytes, url: str, content_type: str) -> None:
        super().__init__(raw)
        self._url = url
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def geturl(self) -> str:
        return self._url


def _seed(runtime, source_id: str, rights):
    if source_id == "HK-02":
        item_key = "WTS"
        headline = HKO_WARNING["name"]
        body = json.dumps(
            {"WTS": HKO_WARNING}, ensure_ascii=False,
            separators=(",", ":"), sort_keys=True,
        )
        canonical_url = SOURCE_URLS[source_id]
        published = "2026-09-08T03:00:00.000000Z"
        updated = "2026-09-08T04:00:00.000000Z"
    else:
        item_key = "one"
        headline = "Rain warning"
        body = RSS_ENTRY.decode()
        canonical_url = "https://weather.metoffice.gov.uk/warnings"
        published = "2026-09-08T12:00:00.000000Z"
        updated = None
    unit = replace(
        _unit(),
        source_id=source_id,
        item_key=item_key,
        headline=headline,
        body=body,
        canonical_url=canonical_url,
        published_at=published,
        updated_at=updated,
        source_definition_url=SOURCE_URLS[source_id],
    )
    if source_id == "HK-02":
        native = native_source_definition_requests(
            source_id=source_id,
            rights=rights.for_source(
                source_id=source_id, definition_url=SOURCE_URLS[source_id]
            ),
        )
        runtime.authority.sources.register_definition(
            native.definition, proof=runtime.proof
        )
        runtime.authority.sources.record_definition_version(
            native.version, proof=runtime.proof
        )
        item_id = SourceItemId.new()
        item = SourceItemRequest(
            item_id,
            native.definition.definition_id,
            native.version.version_id,
            SourceItemIdentityKind.COMPOSITE,
            native.version.item_identity_policy,
            item_key,
            (
                IdentityComponent("item_key", item_key),
                IdentityComponent("source_id", source_id),
            ),
            (),
            f"weather-test-item:{item_id}",
        )
        revision_id = SourceRevisionId.new()
        revision = SourceRevisionRequest(
            revision_id,
            item_id,
            native.version.version_id,
            None,
            updated,
            content_digest(
                headline=headline, body=body, canonical_url=canonical_url
            ),
            native.version.revision_policy,
            "weather-test-v1",
            SourceTime.exact(UtcTimestamp.parse(published)),
            SourceTime.exact(UtcTimestamp.parse(updated)),
            UtcTimestamp.parse("2026-09-08T05:00:00.000000Z"),
            f"weather-test-revision:{revision_id}",
        )
        runtime.authority.sources.register_item(item, proof=runtime.proof)
        runtime.authority.sources.record_revision(revision, proof=runtime.proof)
        requests = (native.definition, native.version, item, revision)
    else:
        requests = _source_requests(unit, _rights())
        for method, request in zip(
            (
                runtime.authority.sources.register_definition,
                runtime.authority.sources.record_definition_version,
                runtime.authority.sources.register_item,
                runtime.authority.sources.record_revision,
                runtime.authority.sources.record_representation,
            ),
            requests,
            strict=True,
        ):
            method(request, proof=runtime.proof)
    version = runtime.authority.sources.version_details(
        requests[1].version_id, proof=runtime.proof
    )
    return unit, EvidenceAcquisitionRequest(
        source_id,
        str(requests[0].definition_id),
        str(requests[1].version_id),
        version.canonical_digest,
        str(requests[3].revision_id),
        canonical_url,
        CONTROLLER_POLICY_DIGEST,
    )


def _portfolio(runtime, monkeypatch):
    from newsroom.control_plane import native_source_rights as source_rights

    terms = {}
    evidence = {}
    observations = {}
    for source_id in ("HK-02", "UK-10"):
        entries = []
        retained = []
        for index, (url, _old_digest) in enumerate(source_rights.TERMS[source_id]):
            raw = (
                f"<main>Fixture retained terms for {source_id} {index}</main>"
            ).encode()
            expected = source_rights.terms_text_digest(source_id, raw)
            entries.append((url, expected))
            admission = runtime.authority.objects.admit(
                ObjectAdmissionRequest(
                    "evidence.source", f"weather-rights:{source_id}:{expected}"
                ),
                raw,
                proof=runtime.proof,
            ).admission
            access = runtime.authority.objects.hydrate(
                source_rights.HydrationRequest(
                    admission.admission_id, "evidence.source"
                ),
                proof=runtime.proof,
            ).decision
            retained.append((
                url, digest_bytes(raw), str(admission.admission_id),
                str(access.access_decision_id),
            ))
        terms[source_id] = tuple(entries)
        observations[source_id] = tuple(retained)
    monkeypatch.setattr(source_rights, "TERMS", terms)
    for source_id in ("HK-02", "UK-10"):
        evidence[source_id] = SourceTermsEvidence(
            source_id,
            "2026-09-08T09:00:00+00:00",
            "REVIEWED_REUSE_PERMITTED",
            observations[source_id],
        )
    # The weather route verifies only its exact retained portfolio terms; the
    # GOV.UK licence member is neither consulted nor relabelled for this source.
    return NativePortfolioRights(_licence(), evidence)


def _acquisition(runtime, rights, fences):
    return NativeWeatherEvidenceAcquisition(
        sources=runtime.authority.sources,
        objects=runtime.authority.objects,
        proof=runtime.proof,
        rights=rights,
        transport_policy_digest=CONTROLLER_POLICY_DIGEST,
        dispatch_fence=lambda request: nullcontext(fences.append(request)),
        clock=lambda: NOW,
    )


def test_hko_acquires_exact_retained_warning_with_current_rights(
    tmp_path, monkeypatch,
):
    args = _args(tmp_path, monkeypatch)
    args["principal_id"] = OPERATOR_PRINCIPAL_ID
    args["authority_domain"] = OPERATOR_AUTHORITY_DOMAIN
    calls = []
    with open_native_runtime(**args) as runtime:
        rights = _portfolio(runtime, monkeypatch)
        unit_value, request = _seed(runtime, "HK-02", rights)

        held = []
        class FencedResponse(_Response):
            def read(self, *args):
                assert held == [request]
                return super().read(*args)
        class _Opener:
            def open(self, http, timeout):
                assert held == [request]
                calls.append((http.full_url, timeout, http.get_method()))
                return FencedResponse(HKO_RAW, http.full_url, "application/json")

        monkeypatch.setattr("urllib.request.build_opener", lambda *_: _Opener())
        fences = []
        @contextmanager
        def fence(request):
            held.append(request)
            fences.append(request)
            try:
                yield
            finally:
                held.pop()
        acquisition = _acquisition(runtime, rights, fences)
        acquisition._fence = fence
        result = acquisition(request)
        assert held == []
        assert calls == [(SOURCE_URLS["HK-02"], 20, "GET")]
        assert fences == [request]
        assert json.loads(result.body) == {"WTS": HKO_WARNING}
        assert result.publication_time == "2026-09-08T03:00:00.000000Z"
        assert result.source_updated_time == "2026-09-08T04:00:00.000000Z"
        assert result.publisher == "Hong Kong Observatory"
        assert result.licence_attribution == HK02_ATTRIBUTION
        assert result.currentness_basis == "AUTHORITATIVE_CURRENT_CONTENT_ENDPOINT"
        assert result.rights_eligibility_digest
        # Exercise the actual assessor admission boundary with transport output,
        # not an independently constructed digest fixture. No model is called.
        from newsroom.control_plane.native_assessor import AutonomousNativeEvidenceAssessor
        from newsroom.control_plane.native_evidence import (
            DependencyAssessment, NativeEvidenceSource, PublicationRightsAssessment,
        )
        from newsroom.sources import SourceDefinitionVersionId
        from newsroom.tests.test_increment10_ingress import _candidate
        from newsroom.tests.test_increment10_editorial import _ready_package
        from newsroom.increment10.evidence import _base_package

        candidate_root = tmp_path / "assessor-candidate"
        candidate_root.mkdir()
        connection, _, candidate = _candidate(candidate_root)
        try:
            current_rights = rights.for_source(source_id="HK-02", definition_url=SOURCE_URLS["HK-02"])
            source = NativeEvidenceSource(
                unit_value,
                runtime.authority.sources.version_details(SourceDefinitionVersionId.parse(request.source_definition_version_id), proof=runtime.proof),
                current_rights,
                DependencyAssessment.create(
                    dependency_status="RESOLVED", evidential_origin_id="HKO",
                    originating_report_id=request.source_revision_id,
                    evidence_digest=result.transport_evidence_digest,
                ),
            )
            class AssessmentReached(Exception):
                pass
            def dispatch(prompt):
                assert json.loads(prompt)["sources"][0]["acquisition_receipt_id"] == result.receipt_digest
                raise AssessmentReached
            assessor = AutonomousNativeEvidenceAssessor(dispatch=dispatch)
            base = _base_package(_ready_package(candidate)[1])
            with pytest.raises(AssessmentReached):
                assessor(candidate, base, (source,), (result,))
            for changed in ("policy_digest", "evidence_digest"):
                values = {name: getattr(current_rights, name) for name in (
                    "decision", "permitted_use", "policy_digest", "evidence_digest",
                )}
                values[changed] = digest_canonical({"changed": changed})
                altered = replace(source, rights=PublicationRightsAssessment.create(**values))
                with pytest.raises(NativeEvidenceHold, match="SOURCE_POLICY_FACTS_HOLD"):
                    assessor(candidate, base, (altered,), (result,))
        finally:
            connection.close()


def test_met_office_pubdate_does_not_become_an_asserted_version_time(
    tmp_path, monkeypatch,
):
    args = _args(tmp_path, monkeypatch)
    args["principal_id"] = OPERATOR_PRINCIPAL_ID
    args["authority_domain"] = OPERATOR_AUTHORITY_DOMAIN
    with open_native_runtime(**args) as runtime:
        rights = _portfolio(runtime, monkeypatch)
        _unit_value, request = _seed(runtime, "UK-10", rights)

        class _Opener:
            def open(self, http, timeout):
                return _Response(RSS_RAW, http.full_url, "application/rss+xml")

        monkeypatch.setattr("urllib.request.build_opener", lambda *_: _Opener())
        fences = []
        with pytest.raises(
            NativeEvidenceHold, match="SOURCE_VERSION_TIME_NOT_ASSERTED:UK-10"
        ):
            _acquisition(runtime, rights, fences)(request)
        assert fences == [request]


def test_binding_mismatch_and_empty_inventory_fail_before_evidence_emission(
    tmp_path, monkeypatch,
):
    args = _args(tmp_path, monkeypatch)
    args["principal_id"] = OPERATOR_PRINCIPAL_ID
    args["authority_domain"] = OPERATOR_AUTHORITY_DOMAIN
    calls = []
    with open_native_runtime(**args) as runtime:
        rights = _portfolio(runtime, monkeypatch)
        _unit_value, request = _seed(runtime, "HK-02", rights)
        acquire = _acquisition(runtime, rights, [])
        with pytest.raises(NativeEvidenceHold, match="TRANSPORT_POLICY_MISMATCH"):
            acquire(replace(request, transport_policy_digest=POLICY_DIGEST))
        with pytest.raises(NativeEvidenceHold, match="WEATHER_SOURCE_BINDING_HOLD"):
            acquire(replace(
                request,
                source_definition_version_digest="sha256:" + "0" * 64,
            ))
        assert calls == []

        class _Opener:
            def open(self, http, timeout):
                calls.append(http.full_url)
                return _Response(b"{}", http.full_url, "application/json")

        monkeypatch.setattr("urllib.request.build_opener", lambda *_: _Opener())
        with pytest.raises(NativeEvidenceHold, match="WEATHER_EVIDENCE_METADATA_HOLD"):
            acquire(request)
        assert calls == [SOURCE_URLS["HK-02"]]
        with pytest.raises(ValueError, match="configuration differs"):
            NativeWeatherEvidenceAcquisition(
                sources=runtime.authority.sources,
                objects=runtime.authority.objects,
                proof=runtime.proof,
                rights=rights,
                transport_policy_digest="not-a-digest",
                dispatch_fence=lambda _: nullcontext(),
            )
