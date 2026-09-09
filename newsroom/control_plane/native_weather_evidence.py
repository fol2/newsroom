"""Independent evidence acquisition for the fixed HKO and Met Office routes."""

from __future__ import annotations

import ssl
import urllib.error
import urllib.request
from contextlib import AbstractContextManager
from collections.abc import Callable
from datetime import UTC, datetime

from lxml import etree

from newsroom.authority import (
    AuthenticationProof,
    GovernedObjects,
    HydrationRequest,
    ObjectAdmissionId,
)
from newsroom.authority.canonical import (
    digest_bytes,
    digest_canonical,
    validate_sha256_digest,
)
from newsroom.increment9.proving import MAX_BODY_BYTES, SOURCE_URLS
from newsroom.sources import (
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceRevisionId,
)
from newsroom.sources.types import TimePrecision

from .govuk_evidence import _NoRedirect, _utc
from .native_evidence import (
    AcquiredEvidence,
    EvidenceAcquisitionRequest,
    NativeEvidenceHold,
    rights_eligibility_digest,
)
from . import native_source_rights
from .native_source_rights import NativePortfolioRights
from .native_weather_sources import weather_items

VERSION = "hermes-native-weather-evidence-v1"
TIMEOUT_SECONDS = 20
SUPPORTED_SOURCE_IDS = ("HK-02", "UK-10")
POLICY_DIGEST = digest_canonical(
    {
        "version": VERSION,
        "sources": {source_id: SOURCE_URLS[source_id] for source_id in SUPPORTED_SOURCE_IDS},
        "method": "GET",
        "redirects": 0,
        "max_bytes": MAX_BODY_BYTES,
        "timeout_seconds": TIMEOUT_SECONDS,
        "credentials": False,
    }
)
HK02_ATTRIBUTION = "Source: DATA.GOV.HK and the Hong Kong Observatory."
UK10_ATTRIBUTION = (
    "Contains public sector information licensed under the Open Government "
    "Licence v3.0; source: Met Office at the linked warning URL."
)


class NativeWeatherEvidenceAcquisition:
    """Acquire one exact current weather item from its fixed HTTPS inventory."""

    def __init__(
        self,
        *,
        sources,
        objects: GovernedObjects,
        proof: AuthenticationProof,
        rights: NativePortfolioRights,
        transport_policy_digest: str,
        dispatch_fence: Callable[[EvidenceAcquisitionRequest], AbstractContextManager[None]],
        clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    ) -> None:
        if (
            type(objects) is not GovernedObjects
            or type(proof) is not AuthenticationProof
            or type(rights) is not NativePortfolioRights
            or not callable(dispatch_fence)
            or not callable(clock)
        ):
            raise ValueError("native weather acquisition configuration differs")
        try:
            validate_sha256_digest(transport_policy_digest)
        except (TypeError, ValueError):
            raise ValueError(
                "native weather acquisition configuration differs"
            ) from None
        self._sources = sources
        self._objects = objects
        self._proof = proof
        self._rights = rights
        self._transport_policy_digest = transport_policy_digest
        self._fence = dispatch_fence
        self._clock = clock

    def __call__(self, request: EvidenceAcquisitionRequest) -> AcquiredEvidence:
        if type(request) is not EvidenceAcquisitionRequest:
            raise TypeError("exact independent acquisition request required")

        def hold(reason: str) -> NativeEvidenceHold:
            return NativeEvidenceHold(reason, request.source_id)

        if request.source_id not in SUPPORTED_SOURCE_IDS:
            raise hold("WEATHER_SOURCE_UNSUPPORTED")
        if request.transport_policy_digest != self._transport_policy_digest:
            raise hold("TRANSPORT_POLICY_MISMATCH")
        endpoint = SOURCE_URLS[request.source_id]
        try:
            definition_id = SourceDefinitionId.parse(request.source_definition_id)
            version_id = SourceDefinitionVersionId.parse(
                request.source_definition_version_id
            )
            revision_id = SourceRevisionId.parse(request.source_revision_id)
            current = self._sources.current_summary(definition_id, proof=self._proof)
            version = self._sources.version_details(version_id, proof=self._proof)
            revision = self._sources.revision(revision_id, proof=self._proof)
            item = self._sources.item(revision.request.item_id, proof=self._proof)
            item_key = item.request.source_native_id or dict(
                (component.name, component.value)
                for component in item.request.identity_components
            ).get("item_key")
            latest = self._sources.latest_revision(
                revision.request.item_id, proof=self._proof
            )
            if (
                current.version_id != version_id
                or current.definition_id != definition_id
                or version.request.definition_id != definition_id
                or version.canonical_digest
                != request.source_definition_version_digest
                or version.request.locator != endpoint
                or revision.request.definition_version_id != version_id
                or item.request.definition_id != definition_id
                or item.request.definition_version_id != version_id
                or latest is None
                or latest.request.revision_id != revision_id
                or request.canonical_url != request.canonical_url.strip()
            ):
                raise ValueError("source binding differs")
            rights = self._require_current_rights(request.source_id, endpoint)
        except (LookupError, TypeError, ValueError):
            raise hold("WEATHER_SOURCE_BINDING_HOLD") from None

        http_request = urllib.request.Request(
            endpoint,
            method="GET",
            headers={
                "User-Agent": "Newsroom-Hermes/1.0",
                "Accept": (
                    "application/json"
                    if request.source_id == "HK-02"
                    else "application/rss+xml, application/xml, text/xml"
                ),
                "Accept-Encoding": "identity",
            },
        )
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )
        try:
            with self._fence(request), opener.open(http_request, timeout=TIMEOUT_SECONDS) as response:
                status = response.status
                response_url = response.geturl()
                content_type = response.headers.get_content_type()
                raw = response.read(MAX_BODY_BYTES + 1)
        except (urllib.error.URLError, TimeoutError, OSError):
            raise hold("WEATHER_ACQUISITION_UNAVAILABLE") from None
        retrieved = self._clock()
        expected_types = (
            {"application/json"}
            if request.source_id == "HK-02"
            else {"application/rss+xml", "application/xml", "text/xml"}
        )
        if (
            retrieved.tzinfo is None
            or status != 200
            or response_url != endpoint
            or content_type not in expected_types
            or not raw
            or len(raw) > MAX_BODY_BYTES
        ):
            raise hold("WEATHER_ACQUISITION_INCOMPLETE")
        retrieved = retrieved.astimezone(UTC)
        try:
            inventory = weather_items(
                request.source_id, raw, observed_at=retrieved
            )
            matches = tuple(
                candidate
                for candidate in inventory
                if candidate.item_key == item_key
                and candidate.canonical_url == request.canonical_url
            )
            if len(matches) != 1:
                raise ValueError("exact weather item is absent")
            observed = matches[0]
            expected_body = observed.retained_corpus_body.encode("utf-8")
            from newsroom.graphiti_adapter.identity import content_digest

            if (
                revision.request.permitted_state_digest
                != content_digest(
                    headline=observed.headline,
                    body=observed.retained_corpus_body,
                    canonical_url=observed.canonical_url,
                )
                or not self._same_source_time(
                    revision.request.source_published_time, observed.published_at
                )
                or not self._same_source_time(
                    revision.request.source_updated_time, observed.updated_at
                )
            ):
                raise ValueError("weather revision differs")
        except (
            KeyError,
            TypeError,
            ValueError,
            UnicodeError,
            etree.XMLSyntaxError,
        ):
            raise hold("WEATHER_EVIDENCE_METADATA_HOLD") from None

        # RSS pubDate is not a source-asserted update/version time. Publication
        # time must never be silently promoted to that stronger currentness fact.
        if request.source_id == "UK-10" or observed.updated_at is None:
            raise hold("SOURCE_VERSION_TIME_NOT_ASSERTED")

        body_digest = digest_bytes(expected_body)
        transport_digest = digest_canonical(
            {
                "version": VERSION,
                "request_digest": request.digest,
                "endpoint": endpoint,
                "response_url": response_url,
                "http_status": status,
                "content_type": content_type,
                "response_digest": digest_bytes(raw),
                "item_key": observed.item_key,
                "body_digest": body_digest,
                "publication_time": observed.published_at,
                "source_updated_time": observed.updated_at,
                "retrieval_time": _utc(retrieved),
            }
        )
        rights_digest = rights_eligibility_digest(
            rights, body_digest=body_digest, transport_digest=transport_digest,
            exclusion_signals=(), text_only=True,
        )
        return AcquiredEvidence.create(
            request_digest=request.digest,
            outcome="COMPLETE",
            canonical_url=request.canonical_url,
            body=expected_body,
            body_digest=body_digest,
            publisher="Hong Kong Observatory",
            responsible_body="Hong Kong Observatory",
            source_type="PRIMARY_OFFICIAL",
            publication_time=observed.published_at,
            source_updated_time=observed.updated_at,
            retrieval_time=_utc(retrieved),
            geography="Hong Kong",
            language="zh-HK",
            transport_evidence_digest=transport_digest,
            currentness_basis="AUTHORITATIVE_CURRENT_CONTENT_ENDPOINT",
            rights_eligibility_digest=rights_digest,
            licence_attribution=HK02_ATTRIBUTION,
            exclusion_signals=(),
            text_only=True,
        )

    def _require_current_rights(self, source_id: str, endpoint: str):
        assessment = self._rights.for_source(
            source_id=source_id, definition_url=endpoint
        )
        evidence = self._rights.evidence.get(source_id)
        if (
            assessment.decision != "PERMITTED"
            or assessment.permitted_use != "PUBLICATION_EVIDENCE"
            or assessment.policy_digest != native_source_rights.POLICY_DIGEST
            or evidence is None
            or evidence.reason != "REVIEWED_REUSE_PERMITTED"
        ):
            raise ValueError("weather rights differ")
        expected = dict(native_source_rights.TERMS[source_id])
        if {entry[0] for entry in evidence.observations} != set(expected):
            raise ValueError("weather rights inventory differs")
        for url, digest, admission_id, _access_id in evidence.observations:
            retained = self._objects.hydrate(
                HydrationRequest(ObjectAdmissionId.parse(admission_id), "evidence.source"),
                proof=self._proof,
            )
            if (
                digest_bytes(retained.data) != digest
                or native_source_rights.terms_text_digest(source_id, retained.data)
                != expected[url]
            ):
                raise ValueError("weather rights bytes differ")
        return assessment

    @staticmethod
    def _same_source_time(retained, observed: str | None) -> bool:
        if observed is None:
            return retained.precision is TimePrecision.UNKNOWN
        return (
            retained.precision is TimePrecision.EXACT
            and retained.value == observed
        )


__all__ = [
    "HK02_ATTRIBUTION",
    "NativeWeatherEvidenceAcquisition",
    "POLICY_DIGEST",
    "SUPPORTED_SOURCE_IDS",
    "UK10_ATTRIBUTION",
]
