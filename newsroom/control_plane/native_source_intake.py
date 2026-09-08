"""Native polling of current approved sources into governed corpus revisions."""

from __future__ import annotations

import ssl
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from urllib.parse import urlsplit

from newsroom.authority import (
    AuthenticationProof, HydrationRequest, ObjectAccessDecisionId, ObjectAdmissionId,
    ObjectAdmissionRequest, UtcTimestamp,
)
from newsroom.authority.canonical import (
    digest_bytes, digest_canonical, validate_sha256_digest,
)
from newsroom.checks import deterministic_uuid4
from newsroom.control_plane.corpus import CorpusAuthorityBinding, CorpusIngestUnit, chunk_text
from newsroom.control_plane.graphiti_operational_readiness import (
    GRAPHITI_EVALUATION_HYDRATION_POLICY,
    OPERATIONAL_ADMISSION_TYPE,
)
from newsroom.control_plane.items import SourceItem, parse_observation
from newsroom.effective_revision import EffectiveRevisionIdentity
from newsroom.graphiti_adapter.identity import content_digest, representation_digest_for
from newsroom.increment9.proving import (
    MAX_BODY_BYTES,
    SOURCE_IDS,
    SOURCE_URLS,
    TIMEOUT_SECONDS,
    USER_AGENT,
)
from newsroom.sources import (
    DiscoveryRepresentationId, DiscoveryRepresentationRequest, IdentityComponent,
    SourceDefinitionId, SourceDefinitionVersionId, SourceItemId, SourceItemIdentityKind,
    SourceDependencyKind, SourceItemRequest, SourceRevisionId, SourceRevisionRequest,
    SourceRole, SourceTime,
)

from .govuk_rights import GovUkLicenceEvidence
from .govuk_evidence import (
    _api_url, _utc, parse_govuk_content_document, parse_govuk_manual_inventory,
)
from .native_policies import (
    NATIVE_SOURCE_OBSERVATION_ADMISSION_TYPE,
    NATIVE_SOURCE_OBSERVATION_PURPOSE,
)
from .native_evidence import (
    DependencyAssessment, NativeEvidenceHold, NativeEvidenceSource,
)

from .veto import VetoError

VERSION = "hermes-native-source-intake-v1"
SUPPORTED = frozenset({"UK-01", "UK-02", "UK-03", "UK-05"})


class NativeSourceIntakeHold(ValueError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _canonical_url_from_api(url: str) -> str:
    prefix = "https://www.gov.uk/api/content"
    if not url.startswith(prefix + "/"):
        raise ValueError("GOV.UK Content API endpoint differs")
    return "https://www.gov.uk" + url.removeprefix(prefix)


def _fetch_exact(url: str) -> tuple[int, bytes]:
    """Fetch only the already-approved exact HTTPS endpoint, without redirects."""

    if (
        url not in SOURCE_URLS.values()
        and not url.startswith("https://www.gov.uk/api/content/")
    ):
        raise ValueError("native source endpoint is not approved")
    request = urllib.request.Request(
        url, method="GET", headers={"User-Agent": USER_AGENT, "Accept": "*/*"}
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        _NoRedirect(),
    )
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            status = int(getattr(response, "status", 200))
            body = response.read(MAX_BODY_BYTES + 1)
    except urllib.error.HTTPError as exc:
        body = exc.read(MAX_BODY_BYTES + 1) if exc.fp else b""
        status = int(exc.code)
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as exc:
        raise ValueError("native source transport failed") from exc
    if len(body) > MAX_BODY_BYTES:
        raise ValueError("native source response exceeds body bound")
    return status, body


@dataclass(frozen=True, slots=True)
class NativeSourceDisposition:
    source_id: str
    status: str
    reason_code: str
    units: tuple[CorpusIngestUnit, ...] = ()
    observation_admission_id: str | None = None
    observation_access_decision_id: str | None = None
    observations: tuple[tuple[str, str, str, str], ...] = ()
    item_holds: tuple[tuple[str, str], ...] = ()


class NativeSourceIntake:
    """Poll eligible retained definitions; every portfolio member remains visible."""

    def __init__(
        self, *, sources, objects, proof: AuthenticationProof,
        definition_ids: Mapping[str, SourceDefinitionId],
        licence: GovUkLicenceEvidence,
        dispatch_fence: Callable[[str, str], None],
        other_source_poll: Callable[..., NativeSourceDisposition] | None = None,
        fetch: Callable[[str], tuple[int, bytes]] = _fetch_exact,
        clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    ) -> None:
        if set(definition_ids) - set(SOURCE_IDS):
            raise ValueError("native source bindings exceed the approved portfolio")
        if not callable(dispatch_fence):
            raise ValueError("native observation authority and dispatch fence are required")
        self._sources, self._objects, self._proof = sources, objects, proof
        self._definitions, self._licence = dict(definition_ids), licence
        self._fence, self._fetch, self._clock = dispatch_fence, fetch, clock
        self._other_source_poll = other_source_poll

    def poll(self) -> tuple[NativeSourceDisposition, ...]:
        results = []
        for source_id in SOURCE_IDS:
            try:
                results.append(self._poll_one(source_id))
            except VetoError:
                raise
            except Exception as exc:
                results.append(NativeSourceDisposition(
                    source_id, "HOLD", getattr(exc, "reason_code", "SOURCE_POLL_FAILED")
                ))
        return tuple(results)

    def _poll_one(self, source_id: str) -> NativeSourceDisposition:
        definition_id = self._definitions.get(source_id)
        if definition_id is None:
            return NativeSourceDisposition(source_id, "HOLD", "SOURCE_DEFINITION_MISSING")
        summary = self._sources.current_summary(definition_id, proof=self._proof)
        version = self._sources.version_details(summary.version_id, proof=self._proof).request
        expected_url = SOURCE_URLS[source_id]
        if version.locator != expected_url:
            return NativeSourceDisposition(source_id, "HOLD", "SOURCE_LOCATOR_MISMATCH")
        if source_id not in SUPPORTED:
            if self._other_source_poll is not None:
                return self._other_source_poll(
                    source_id=source_id, definition_id=definition_id,
                    version_id=summary.version_id, version=version,
                )
            return NativeSourceDisposition(source_id, "HOLD", "CURRENT_RIGHTS_UNSUPPORTED")
        rights = self._licence.for_source(source_id=source_id, definition_url=expected_url)
        if rights.decision != "PERMITTED":
            return NativeSourceDisposition(source_id, "HOLD", "CURRENT_RIGHTS_HOLD")
        if source_id in {"UK-02", "UK-03"}:
            return self._poll_direct_govuk(
                source_id, definition_id, summary.version_id, version, rights,
            )
        self._fence(source_id, expected_url)
        status, raw = self._fetch(expected_url)
        if len(raw) > MAX_BODY_BYTES:
            return NativeSourceDisposition(source_id, "HOLD", "SOURCE_BODY_TOO_LARGE")
        if status != 200 or not raw:
            return NativeSourceDisposition(source_id, "HOLD", "SOURCE_FETCH_INCOMPLETE")
        raw_admission, raw_access = self._admit_observation(source_id, raw)
        observations = [(
            expected_url, digest_bytes(raw), str(raw_admission.admission_id),
            str(raw_access.access_decision_id),
        )]
        items = parse_observation(source_id=source_id, url=expected_url, body=raw)
        if not items:
            return NativeSourceDisposition(
                source_id, "HOLD", "SOURCE_PARSE_EMPTY", (),
                str(raw_admission.admission_id), str(raw_access.access_decision_id),
                tuple(observations),
            )
        units, item_holds = [], []
        for item in items:
            try:
                item_url, item_raw, retrieved = self._fetch_complete_item(source_id, item)
                item_admission, item_access = self._admit_observation(source_id, item_raw)
                observations.append((
                    item_url, digest_bytes(item_raw), str(item_admission.admission_id),
                    str(item_access.access_decision_id),
                ))
                item = self._parse_complete_item(item, item_raw, retrieved)
                units.extend(self._retain_item(
                    source_id, definition_id, summary.version_id, version, item,
                    digest_bytes(item_raw),
                    retrieved.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), rights.record_id,
                ))
            except VetoError:
                raise
            except Exception as exc:
                item_holds.append((
                    item.canonical_url,
                    getattr(exc, "reason_code", "SOURCE_ITEM_RETAIN_FAILED"),
                ))
        status = "HOLD" if item_holds else "READY"
        return NativeSourceDisposition(
            source_id, status,
            "SOURCE_ITEMS_HELD" if item_holds else "GOVERNED_REVISIONS_RETAINED",
            tuple(units),
            str(raw_admission.admission_id), str(raw_access.access_decision_id),
            tuple(observations),
            tuple(item_holds),
        )

    def _poll_direct_govuk(self, source_id, definition_id, version_id, version, rights):
        endpoint = SOURCE_URLS[source_id]
        self._fence(source_id, endpoint)
        status, raw = self._fetch(endpoint)
        if len(raw) > MAX_BODY_BYTES:
            return NativeSourceDisposition(source_id, "HOLD", "SOURCE_BODY_TOO_LARGE")
        if status != 200 or not raw:
            return NativeSourceDisposition(source_id, "HOLD", "SOURCE_FETCH_INCOMPLETE")
        admission, access = self._admit_observation(source_id, raw)
        root_digest = digest_bytes(raw)
        observations = [(endpoint, root_digest, str(admission.admission_id),
                         str(access.access_decision_id))]
        retrieved = self._clock().astimezone(UTC)
        canonical_root = _canonical_url_from_api(endpoint)
        if source_id == "UK-02":
            try:
                document = parse_govuk_content_document(
                    canonical_root, raw, retrieved_at=retrieved,
                )
                if document.document_type != "guide":
                    raise ValueError("BN(O) source is not a complete guide")
                item = SourceItem(
                    source_id, urlsplit(canonical_root).path, document.title,
                    document.body_text, canonical_root,
                    _utc(document.publication), _utc(document.updated), document.body_text,
                )
                units = self._retain_item(
                    source_id, definition_id, version_id, version, item, root_digest,
                    _utc(retrieved), rights.record_id,
                )
            except (TypeError, ValueError, KeyError, UnicodeError):
                return NativeSourceDisposition(
                    source_id, "HOLD", "MULTIPART_COVERAGE_INCOMPLETE", (),
                    str(admission.admission_id), str(access.access_decision_id),
                    tuple(observations),
                )
            return NativeSourceDisposition(
                source_id, "READY", "GOVERNED_REVISIONS_RETAINED", units,
                str(admission.admission_id), str(access.access_decision_id),
                tuple(observations),
            )
        try:
            inventory = parse_govuk_manual_inventory(
                canonical_root, raw, retrieved_at=retrieved,
            )
        except (TypeError, ValueError, KeyError, UnicodeError):
            return NativeSourceDisposition(
                source_id, "HOLD", "MANUAL_CHILD_COVERAGE_INCOMPLETE", (),
                str(admission.admission_id), str(access.access_decision_id),
                tuple(observations),
            )
        units, item_holds = [], []
        for path, title in inventory.sections:
            canonical_url = "https://www.gov.uk" + path
            item = SourceItem(
                source_id, root_digest + "|" + path, title, title, canonical_url,
            )
            try:
                item_url, item_raw, observed = self._fetch_complete_item(source_id, item)
                item_admission, item_access = self._admit_observation(source_id, item_raw)
                observations.append((
                    item_url, digest_bytes(item_raw), str(item_admission.admission_id),
                    str(item_access.access_decision_id),
                ))
                item = self._parse_complete_item(item, item_raw, observed)
                units.extend(self._retain_item(
                    source_id, definition_id, version_id, version, item,
                    digest_bytes(item_raw), _utc(observed), rights.record_id,
                ))
            except VetoError:
                raise
            except Exception as exc:
                item_holds.append((
                    canonical_url,
                    getattr(exc, "reason_code", "SOURCE_ITEM_RETAIN_FAILED"),
                ))
        return NativeSourceDisposition(
            source_id, "HOLD" if item_holds else "READY",
            "SOURCE_ITEMS_HELD" if item_holds else "GOVERNED_REVISIONS_RETAINED",
            tuple(units), str(admission.admission_id), str(access.access_decision_id),
            tuple(observations), tuple(item_holds),
        )

    def _fetch_complete_item(self, source_id, item):
        try:
            url = _api_url(item.canonical_url)
        except ValueError:
            raise NativeSourceIntakeHold("SOURCE_ITEM_CANONICAL_URL_HOLD") from None
        self._fence(source_id, url)
        status, raw = self._fetch(url)
        if len(raw) > MAX_BODY_BYTES:
            raise NativeSourceIntakeHold("SOURCE_ITEM_BODY_TOO_LARGE")
        if status != 200 or not raw:
            raise NativeSourceIntakeHold("SOURCE_ITEM_FETCH_INCOMPLETE")
        return url, raw, self._clock().astimezone(UTC)

    @staticmethod
    def _parse_complete_item(item, raw, observed):
        try:
            document = parse_govuk_content_document(
                item.canonical_url, raw, retrieved_at=observed
            )
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise NativeSourceIntakeHold("SOURCE_ITEM_METADATA_HOLD") from None
        return replace(
            item,
            headline=document.title,
            body=document.body_text,
            corpus_body=document.body_text,
            published_at=_utc(document.publication),
            updated_at=_utc(document.updated),
        )

    def _admit_observation(self, source_id: str, raw: bytes):
        admission = self._objects.admit(ObjectAdmissionRequest(
            NATIVE_SOURCE_OBSERVATION_ADMISSION_TYPE,
            f"native-source-observation:{source_id}:{digest_bytes(raw)}"
        ), raw, proof=self._proof).admission
        access = self._hydrate(admission, NATIVE_SOURCE_OBSERVATION_PURPOSE, raw)
        return admission, access

    def _retain_item(self, source_id, definition_id, version_id, version, item,
                     observation_digest, observed_at, rights_id):
        item_id = deterministic_uuid4(
            SourceItemId, namespace=f"{VERSION}:item",
            semantic_value=[str(version_id), source_id, item.item_key],
        )
        item_request = SourceItemRequest(
            item_id, definition_id, version_id, SourceItemIdentityKind.COMPOSITE,
            version.item_identity_policy, item.item_key,
            (IdentityComponent("item_key", item.item_key), IdentityComponent("source_id", source_id)),
            (), f"native-source-item:{item_id}",
        )
        self._sources.register_item(item_request, proof=self._proof)
        body = item.retained_corpus_body
        revision_digest = content_digest(
            headline=item.headline, body=body, canonical_url=item.canonical_url
        )
        latest = self._sources.latest_revision(item_id, proof=self._proof)
        native_revision_token = item.updated_at
        if (
            native_revision_token is not None
            and latest is not None
            and latest.request.source_native_revision_token == native_revision_token
            and latest.request.permitted_state_digest != revision_digest
        ):
            raise NativeSourceIntakeHold("SOURCE_NATIVE_REVISION_CONFLICT")
        revision_id = deterministic_uuid4(
            SourceRevisionId, namespace=f"{VERSION}:revision",
            semantic_value=[str(item_id), native_revision_token, revision_digest],
        )
        try:
            retained_revision = self._sources.revision(revision_id, proof=self._proof)
        except LookupError:
            retained_revision = None
        replay = retained_revision is not None
        first_observed = (
            retained_revision.request.observed_at.to_text() if replay else observed_at
        )
        prior_revision_id = (
            retained_revision.request.prior_revision_id if replay
            else None if latest is None else latest.request.revision_id
        )
        revision_request = SourceRevisionRequest(
            revision_id, item_id, version_id, prior_revision_id,
            native_revision_token, revision_digest, version.revision_policy,
            VERSION, self._source_time(item.published_at), self._source_time(item.updated_at),
            UtcTimestamp.parse(first_observed), f"native-source-revision:{revision_id}",
        )
        self._sources.record_revision(revision_request, proof=self._proof)
        representation_digest = representation_digest_for(
            source_id=source_id, item_key=item.item_key, revision_digest=revision_digest,
            published_at=item.published_at, updated_at=item.updated_at,
        )
        representation_id = deterministic_uuid4(
            DiscoveryRepresentationId, namespace=f"{VERSION}:representation",
            semantic_value=[str(revision_id), representation_digest],
        )
        fields_digest = digest_canonical({
            "headline": item.headline, "body": body, "canonical_url": item.canonical_url,
            "published_at": item.published_at, "updated_at": item.updated_at,
        })
        representation_request = DiscoveryRepresentationRequest(
            representation_id, revision_id, version_id, VERSION, VERSION, VERSION, VERSION,
            fields_digest, representation_digest, UtcTimestamp.parse(first_observed),
            f"native-source-representation:{representation_id}",
        )
        self._sources.record_representation(representation_request, proof=self._proof)
        base = CorpusIngestUnit(
            source_id, item.item_key, item.headline, body, item.canonical_url,
            observation_digest, observed_at, f"native-source:{observation_digest}",
            EffectiveRevisionIdentity(source_id, item.item_key, revision_digest, first_observed),
            item.published_at, item.updated_at, source_definition_url=version.locator,
            effective_pull_first_observed_at=first_observed,
        )
        chunks = chunk_text(base.full_text)
        result, predecessor = [], None
        source_records = (
            {"record_type": "SOURCE_DEFINITION", "record_id": str(definition_id), "source_id": source_id},
            {"record_type": "SOURCE_DEFINITION_VERSION", "record_id": str(version_id), "definition_id": str(definition_id), "source_id": source_id, "source_url": version.locator},
            {"record_type": "SOURCE_ITEM", "record_id": str(item_id), "definition_id": str(definition_id), "source_id": source_id, "item_key": item.item_key},
            {"record_type": "SOURCE_REVISION", "record_id": str(revision_id), "item_id": str(item_id), "source_id": source_id, "item_key": item.item_key, "revision_digest": revision_digest},
            {"record_type": "DISCOVERY_REPRESENTATION", "record_id": str(representation_id), "source_id": source_id, "item_key": item.item_key, "revision_id": str(revision_id), "representation_digest": representation_digest},
        )
        for ordinal, chunk in enumerate(chunks, 1):
            provisional = replace(base, chunk_ordinal=ordinal, chunk_count=len(chunks), predecessor_ingest_id=predecessor)
            data = " ".join(provisional.episode_body.split()).encode()
            admission = self._objects.admit(ObjectAdmissionRequest(
                OPERATIONAL_ADMISSION_TYPE, f"native-source-passage:{provisional.ingest_id}:{rights_id}"
            ), data, proof=self._proof).admission
            access = self._hydrate(admission, GRAPHITI_EVALUATION_HYDRATION_POLICY.purpose, data)
            binding = CorpusAuthorityBinding(
                str(admission.admission_id), str(access.access_decision_id), str(definition_id),
                str(version_id), str(item_id), str(revision_id), str(representation_id),
                (*source_records,
                 {"record_type": "OBJECT_ADMISSION", "record_id": str(admission.admission_id), "revision_id": str(revision_id), "decision": "ADMIT", "scope": "EVALUATION_CORPUS_INGEST"},
                 {"record_type": "OBJECT_ACCESS_DECISION", "record_id": str(access.access_decision_id), "revision_id": str(revision_id), "decision": "ALLOW", "principal_id": access.principal_id, "authority_domain": access.authority_domain, "purpose": access.purpose}),
            )
            unit = replace(provisional, authority=binding)
            result.append(unit)
            predecessor = unit.ingest_id
        return tuple(result)

    def _hydrate(self, admission, purpose: str, expected: bytes):
        try:
            access = self._objects.latest_access_decision(
                admission.admission_id, purpose=purpose, proof=self._proof
            )
        except KeyError:
            hydrated = self._objects.hydrate(HydrationRequest(
                admission.admission_id, purpose, 0, len(expected)
            ), proof=self._proof)
            if hydrated.data != expected:
                raise ValueError("native source object hydration differs")
            access = hydrated.decision
        if access.admission_id != admission.admission_id or access.allowed_bytes != len(expected):
            raise ValueError("native source object access differs")
        return access

    @staticmethod
    def _source_time(value: str | None) -> SourceTime:
        return SourceTime.unknown() if not value else SourceTime.exact(UtcTimestamp.parse(value))


def native_evidence_sources(
    *, units: tuple[CorpusIngestUnit, ...], sources, objects,
    observations: Mapping[str, tuple[str, str, str, str]],
    licence: GovUkLicenceEvidence, proof: AuthenticationProof,
) -> tuple[NativeEvidenceSource, ...]:
    """Bind retained complete-page revisions to independent evidence inputs."""

    if not units or any(type(unit) is not CorpusIngestUnit for unit in units):
        raise ValueError("native evidence source units differ")
    grouped: dict[str, list[CorpusIngestUnit]] = {}
    for unit in units:
        grouped.setdefault(unit.revision_id, []).append(unit)
    result = []
    for revision_units in grouped.values():
        ordered = tuple(sorted(revision_units, key=lambda item: item.chunk_ordinal))
        unit = ordered[0]

        def hold(reason: str):
            return NativeEvidenceHold(reason, unit.source_id)

        authority = unit.authority
        weather = unit.source_id in {"HK-02", "UK-10"}
        if (
            authority is None
            or tuple(item.chunk_ordinal for item in ordered)
            != tuple(range(1, unit.chunk_count + 1))
            or any(
                item.chunk_count != unit.chunk_count
                or item.revision_id != unit.revision_id
                or item.body != unit.body
                or item.headline != unit.headline
                or item.canonical_url != unit.canonical_url
                for item in ordered
            )
            or unit.proving_run_id != "native-source:" + unit.observation_digest
        ):
            raise hold("NATIVE_SOURCE_CHUNK_BINDING_HOLD")
        try:
            validate_sha256_digest(unit.observation_digest)
            expected_api_url = SOURCE_URLS[unit.source_id] if weather else _api_url(unit.canonical_url)
            observation = observations[unit.observation_digest]
            if (
                type(observation) is not tuple
                or len(observation) != 4
                or observation[0] != expected_api_url
                or observation[1] != unit.observation_digest
            ):
                raise ValueError("raw observation reference differs")
            ObjectAccessDecisionId.parse(observation[3])
            if unit.source_id == "UK-03":
                _require_manual_inventory_binding(
                    unit=unit, observations=observations, objects=objects,
                    proof=proof, root_api_url=unit.source_definition_url,
                )
            version = sources.version_details(
                SourceDefinitionVersionId.parse(authority.definition_version_id),
                proof=proof,
            )
            revision = sources.revision(
                SourceRevisionId.parse(authority.revision_id), proof=proof,
            )
            representation = sources.representation(
                DiscoveryRepresentationId.parse(authority.representation_id),
                proof=proof,
            )
            current = sources.current_summary(
                SourceDefinitionId.parse(authority.definition_id), proof=proof,
            )
        except (TypeError, ValueError, LookupError, KeyError):
            raise hold("NATIVE_SOURCE_AUTHORITY_HOLD") from None
        request = version.request
        roles = tuple(
            role for role in request.roles
            if role.role in {SourceRole.ORIGINATING_AUTHORITY, SourceRole.RESPONSIBLE_OPERATOR}
        )
        dependencies = tuple(
            dependency for dependency in request.dependencies
            if dependency.kind is SourceDependencyKind.ORIGINATING_MATERIAL
        )
        if (
            current.version_id != version.version_id
            or str(request.definition_id) != authority.definition_id
            or request.locator != unit.source_definition_url
            or len(roles) != 1
            or (len(dependencies) != 1 and not (unit.source_id == "UK-10" and not dependencies))
            or revision.request.item_id != SourceItemId.parse(authority.item_id)
            or revision.request.definition_version_id != version.version_id
            or revision.request.permitted_state_digest != unit.revision_digest
            or representation.request.revision_id != revision.request.revision_id
            or representation.request.definition_version_id != version.version_id
            or representation.request.representation_digest != unit.representation_digest
        ):
            raise hold("NATIVE_SOURCE_AUTHORITY_HOLD")
        for item in ordered:
            expected = " ".join(item.episode_body.split()).encode()
            hydrated = objects.hydrate(HydrationRequest(
                ObjectAdmissionId.parse(item.authority.admission_id),
                GRAPHITI_EVALUATION_HYDRATION_POLICY.purpose, 0, len(expected),
            ), proof=proof)
            if hydrated.data != expected:
                raise hold("NATIVE_SOURCE_CANONICAL_PAGE_HOLD")
        try:
            raw_admission_id = ObjectAdmissionId.parse(observation[2])
            raw_access = objects.latest_access_decision(
                raw_admission_id,
                purpose=NATIVE_SOURCE_OBSERVATION_PURPOSE, proof=proof,
            )
            if raw_access.admission_id != raw_admission_id:
                raise ValueError("raw observation access differs")
            raw = objects.hydrate(HydrationRequest(
                raw_admission_id, NATIVE_SOURCE_OBSERVATION_PURPOSE,
                0, raw_access.allowed_bytes,
            ), proof=proof).data
            retrieved = datetime.fromisoformat(unit.observed_at.replace("Z", "+00:00"))
            if weather:
                from .native_weather_sources import weather_items
                items = tuple(item for item in weather_items(
                    unit.source_id, raw, observed_at=retrieved,
                ) if item.item_key == unit.item_key)
                matches = len(items) == 1 and (
                    items[0].canonical_url == unit.canonical_url
                    and items[0].headline == unit.headline
                    and items[0].retained_corpus_body == unit.body
                    and items[0].published_at == unit.published_at
                    and items[0].updated_at == unit.updated_at
                )
            else:
                document = parse_govuk_content_document(
                    unit.canonical_url, raw, retrieved_at=retrieved,
                )
                matches = (
                    document.title == unit.headline
                    and document.body_text == unit.body
                    and _utc(document.publication) == unit.published_at
                    and _utc(document.updated) == unit.updated_at
                )
        except (TypeError, ValueError, KeyError, UnicodeError):
            raise hold("NATIVE_SOURCE_RAW_OBSERVATION_HOLD") from None
        if (
            digest_bytes(raw) != unit.observation_digest
            or not matches
        ):
            raise hold("NATIVE_SOURCE_RAW_OBSERVATION_HOLD")
        rights = licence.for_source(
            source_id=unit.source_id, definition_url=request.locator,
        )
        if rights.decision != "PERMITTED":
            raise hold("NATIVE_SOURCE_RIGHTS_HOLD")
        dependency = dependencies[0] if dependencies else None
        dependency_receipt = DependencyAssessment.create(
            dependency_status="RESOLVED",
            evidential_origin_id=unit.observation_digest,
            originating_report_id=authority.revision_id,
            evidence_digest=digest_canonical({
                "source_definition_version": version.canonical_digest,
                "source_revision": revision.canonical_digest,
                "originating_material_dependency": None if dependency is None else dependency.canonical_value(),
                "canonical_url": unit.canonical_url,
                "observation_digest": unit.observation_digest,
                "canonical_page_digest": unit.revision_digest,
            }),
        )
        result.append(NativeEvidenceSource(unit, version, rights, dependency_receipt))
    return tuple(result)


def _require_manual_inventory_binding(
    *, unit: CorpusIngestUnit,
    observations: Mapping[str, tuple[str, str, str, str]], objects,
    proof: AuthenticationProof, root_api_url: str,
) -> None:
    root_digest, separator, section_path = unit.item_key.partition("|")
    validate_sha256_digest(root_digest)
    root = observations[root_digest]
    if separator != "|" or root[0] != root_api_url or root[1] != root_digest:
        raise ValueError("manual inventory reference differs")
    admission_id = ObjectAdmissionId.parse(root[2])
    ObjectAccessDecisionId.parse(root[3])
    access = objects.latest_access_decision(
        admission_id, purpose=NATIVE_SOURCE_OBSERVATION_PURPOSE, proof=proof,
    )
    if access.admission_id != admission_id:
        raise ValueError("manual inventory access differs")
    raw = objects.hydrate(HydrationRequest(
        admission_id, NATIVE_SOURCE_OBSERVATION_PURPOSE, 0, access.allowed_bytes,
    ), proof=proof).data
    if digest_bytes(raw) != root_digest:
        raise ValueError("manual inventory bytes differ")
    inventory = parse_govuk_manual_inventory(
        _canonical_url_from_api(root_api_url), raw,
        retrieved_at=datetime.fromisoformat(unit.observed_at.replace("Z", "+00:00")),
    )
    if section_path not in {path for path, _ in inventory.sections}:
        raise ValueError("manual section is outside its retained inventory")


__all__ = [
    "NativeSourceDisposition", "NativeSourceIntake", "SOURCE_IDS",
    "native_evidence_sources",
]
