"""Independent evidence acquisition for the fixed HKO and Met Office routes."""

from __future__ import annotations

import ssl
import json
import urllib.error
import urllib.request
from contextlib import AbstractContextManager
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

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
    DiscoveryRepresentationId,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceRevisionId,
)
from newsroom.sources.types import TimePrecision

from .govuk_evidence import _NoRedirect, _utc, _unique_object
from .native_evidence import (
    AcquiredEvidence,
    EvidenceAcquisitionRequest,
    NativeEvidenceHold,
    rights_eligibility_digest,
)
from . import native_source_rights
from .native_source_rights import NativePortfolioRights
from .native_source_intake import verified_native_observation
from .native_weather_sources import weather_items

VERSION = "hermes-native-weather-evidence-v2"
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
HKO_COMPLETED_EVENT_PREFIX = "Official status changed for completed historical event: "


def hko_evidence_body(raw: bytes) -> bytes:
    """Expose documented structured facts without losing the exact source JSON.

    HKO warnsum defines actionCode separately from issue/update time. An update
    or an absent warning is not evidence of cancellation or improved safety.
    https://data.weather.gov.hk/weatherAPI/doc/HKO_Open_Data_API_Documentation.pdf
    """
    value = json.loads(raw, object_pairs_hook=_unique_object)
    if type(value) is not dict or len(value) != 1:
        raise ValueError("one exact HKO warning is required")
    warning = next(iter(value.values()))
    verbs = {"ISSUE": "issued", "REISSUE": "reissued", "CANCEL": "cancelled", "EXTEND": "extended"}
    if type(warning) is not dict or warning.get("actionCode") not in {*verbs, "UPDATE"}:
        raise ValueError("HKO warning action is unsupported")
    name, kind = warning.get("name"), warning.get("type", "")
    if type(name) is not str or not name.strip() or type(kind) is not str:
        raise ValueError("HKO warning name/type differs")
    label = name if not kind or kind in name else kind + name
    action = warning["actionCode"]
    facts = ([] if action == "UPDATE" else [
        f"Official status changed: 香港天文台 {verbs[action]} the {label}."
    ])
    months = ("January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December")
    for field, description in (("issueTime", "issued"), ("updateTime", "updated")):
        instant = datetime.fromisoformat(warning[field])
        if instant.tzinfo is None:
            raise ValueError("HKO warning time lacks a zone")
        local = instant.astimezone(ZoneInfo("Asia/Hong_Kong"))
        clock = local.strftime("%H:%M:%S" if local.second or local.microsecond else "%H:%M")
        if local.microsecond:
            clock += f".{local.microsecond:06d}"
        date = f"{local.day} {months[local.month - 1]} {local.year} at {clock}"
        facts.append(f"The {label} warning record was {description} on {date} (香港時間).")
    return raw + b"\n\n" + "\n".join(facts).encode("utf-8")


def legacy_hko_body(body: bytes) -> bytes:
    """Return the immediate predecessor of an exact supported HKO rendering."""
    raw, separator, _facts = body.partition(b"\n\n")
    if not separator:
        raise ValueError("normalised HKO body differs")
    normalised = hko_evidence_body(raw)
    if body == normalised:
        return raw
    value = json.loads(raw, object_pairs_hook=_unique_object)
    warning = next(iter(value.values()))
    if warning.get("actionCode") == "CANCEL" and body == hko_completed_event_body(raw):
        return normalised
    raise ValueError("normalised HKO body differs")


def hko_completed_event_body(raw: bytes) -> bytes:
    """Add one dated terminal-event span without inventing a cancellation time."""

    body = hko_evidence_body(raw)
    value = json.loads(raw, object_pairs_hook=_unique_object)
    warning = next(iter(value.values()))
    if warning.get("actionCode") != "CANCEL":
        raise ValueError("completed HKO event is not an explicit cancellation")
    name, kind = warning["name"], warning.get("type", "")
    label = name if not kind or kind in name else kind + name
    updated = body.decode("utf-8").splitlines()[-1]
    prefix = f"The {label} warning record was updated on "
    if not updated.startswith(prefix) or not updated.endswith("."):
        raise ValueError("completed HKO event update time differs")
    date = updated.removeprefix(prefix).removesuffix(".")
    sentence = (
        f"{HKO_COMPLETED_EVENT_PREFIX}香港天文台 cancelled the {label} "
        f"(record updated on {date})."
    )
    disclaimer = (
        "The timestamp above is the record update time and no exact "
        "cancellation time is asserted."
    )
    return body + b"\n" + sentence.encode("utf-8") + b"\n" + disclaimer.encode("utf-8")


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
        retained_units: Mapping[str, tuple] | None = None,
        observations: Mapping[str, tuple[str, str, str, str]] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    ) -> None:
        if (
            type(objects) is not GovernedObjects
            or type(proof) is not AuthenticationProof
            or type(rights) is not NativePortfolioRights
            or not callable(dispatch_fence)
            or not callable(clock)
            or (retained_units is not None and not isinstance(retained_units, Mapping))
            or (observations is not None and not isinstance(observations, Mapping))
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
        self._retained_units = {} if retained_units is None else retained_units
        self._observations = {} if observations is None else observations
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
            if (
                not matches
                and request.source_id == "HK-02"
                and request.source_revision_id in self._retained_units
            ):
                return self._retained_completed_event(
                    request=request, rights=rights, version=version,
                    revision=revision, item=item, current_raw=raw,
                    rehydrated_at=retrieved,
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
        except NativeEvidenceHold:
            raise
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

        try:
            expected_body = hko_evidence_body(expected_body)
        except (KeyError, TypeError, ValueError):
            raise hold("WEATHER_STRUCTURED_FACTS_HOLD") from None

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

    def _retained_completed_event(
        self, *, request, rights, version, revision, item,
        current_raw: bytes, rehydrated_at: datetime,
    ) -> AcquiredEvidence:
        """Rehydrate one exact retained HKO cancellation as historical evidence."""

        def hold() -> NativeEvidenceHold:
            return NativeEvidenceHold(
                "WEATHER_RETAINED_COMPLETED_EVENT_HOLD", request.source_id
            )

        retained = self._retained_units.get(request.source_revision_id)
        item_key = item.request.source_native_id or dict(
            (component.name, component.value)
            for component in item.request.identity_components
        ).get("item_key")
        if (
            request.source_id != "HK-02"
            or type(retained) is not tuple
            or len(retained) != 1
        ):
            raise hold()
        unit = retained[0]
        authority = unit.authority
        try:
            observed_at = datetime.fromisoformat(
                unit.observed_at.replace("Z", "+00:00")
            ).astimezone(UTC)
            representation = self._sources.representation(
                DiscoveryRepresentationId.parse(authority.representation_id),
                proof=self._proof,
            )
            verified = verified_native_observation(
                unit=unit, observations=self._observations,
                objects=self._objects, proof=self._proof,
                expected_url=SOURCE_URLS["HK-02"],
            )
            historical = tuple(
                candidate for candidate in weather_items(
                    "HK-02", verified.raw, observed_at=observed_at,
                )
                if candidate.item_key == unit.item_key
                and candidate.canonical_url == unit.canonical_url
            )
            raw_value = json.loads(
                verified.raw, object_pairs_hook=_unique_object
            )
            warning = raw_value.get(unit.item_key)
            from newsroom.graphiti_adapter.identity import content_digest

            if (
                authority is None
                or unit.chunk_ordinal != 1
                or unit.chunk_count != 1
                or unit.source_id != "HK-02"
                or unit.item_key != item_key
                or unit.revision_id != request.source_revision_id
                or unit.canonical_url != request.canonical_url
                or unit.source_definition_url != version.request.locator
                or authority.definition_id != request.source_definition_id
                or authority.definition_version_id
                != request.source_definition_version_id
                or authority.item_id != str(item.request.item_id)
                or authority.revision_id != str(revision.request.revision_id)
                or revision.request.definition_version_id != version.version_id
                or revision.request.item_id != item.request.item_id
                or representation.request.revision_id
                != revision.request.revision_id
                or representation.request.definition_version_id
                != version.version_id
                or representation.request.representation_digest
                != unit.representation_digest
                or representation.request.permitted_fields_digest
                != digest_canonical({
                    "headline": historical[0].headline,
                    "body": historical[0].retained_corpus_body,
                    "canonical_url": historical[0].canonical_url,
                    "published_at": historical[0].published_at,
                    "updated_at": historical[0].updated_at,
                })
                or len(historical) != 1
                or type(warning) is not dict
                or warning.get("actionCode") != "CANCEL"
                or historical[0].headline != unit.headline
                or historical[0].retained_corpus_body != unit.body
                or historical[0].published_at != unit.published_at
                or historical[0].updated_at != unit.updated_at
                or revision.request.permitted_state_digest
                != content_digest(
                    headline=unit.headline, body=unit.body,
                    canonical_url=unit.canonical_url,
                )
                or not self._same_source_time(
                    revision.request.source_published_time, unit.published_at
                )
                or not self._same_source_time(
                    revision.request.source_updated_time, unit.updated_at
                )
                or rehydrated_at < observed_at
            ):
                raise ValueError("retained completed event binding differs")
            body = hko_completed_event_body(
                historical[0].retained_corpus_body.encode("utf-8")
            )
        except (
            AttributeError, KeyError, LookupError, PermissionError, TypeError,
            ValueError, UnicodeError, etree.XMLSyntaxError,
        ):
            raise hold() from None

        body_digest = digest_bytes(body)
        rehydrated_text = _utc(rehydrated_at)
        transport_digest = digest_canonical({
            "version": VERSION,
            "mode": "RETAINED_AUTHORITATIVE_COMPLETED_EVENT",
            "request_digest": request.digest,
            "endpoint": SOURCE_URLS["HK-02"],
            "current_response_digest": digest_bytes(current_raw),
            "current_item_absent": True,
            "observation_digest": verified.digest,
            "observation_admission_id": str(verified.admission_id),
            "observation_access_decision_id": verified.access_decision_id,
            "source_observed_time": unit.observed_at,
            "rehydrated_at": rehydrated_text,
            "item_key": unit.item_key,
            "body_digest": body_digest,
            "publication_time": unit.published_at,
            "source_updated_time": unit.updated_at,
        })
        rights_digest = rights_eligibility_digest(
            rights, body_digest=body_digest, transport_digest=transport_digest,
            exclusion_signals=(), text_only=True,
        )
        return AcquiredEvidence.create(
            request_digest=request.digest, outcome="COMPLETE",
            canonical_url=request.canonical_url, body=body,
            body_digest=body_digest, publisher="Hong Kong Observatory",
            responsible_body="Hong Kong Observatory",
            source_type="PRIMARY_OFFICIAL",
            publication_time=unit.published_at,
            source_updated_time=unit.updated_at,
            retrieval_time=rehydrated_text,
            source_observed_time=unit.observed_at,
            geography="Hong Kong", language="zh-HK",
            transport_evidence_digest=transport_digest,
            currentness_basis="RETAINED_AUTHORITATIVE_COMPLETED_EVENT",
            rights_eligibility_digest=rights_digest,
            licence_attribution=HK02_ATTRIBUTION,
            exclusion_signals=(), text_only=True,
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
