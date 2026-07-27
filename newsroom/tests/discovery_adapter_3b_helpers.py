from __future__ import annotations

from dataclasses import replace
import gzip

from newsroom.authority.types import UtcTimestamp
from newsroom.discovery_adapters import (
    AdapterKind,
    AdapterRequest,
    AdapterRequestId,
    AdapterVersionRef,
    BodyEncoding,
    BodyLimits,
    CaptureId,
    ConditionalValidator,
    DnsEvidence,
    EndpointPolicy,
    FixtureTransportScenario,
    Header,
    ObservationBaseline,
    ObservationProposalId,
    ParserLimits,
    ParserResultId,
    RedirectHop,
    ShapeField,
    SourceShapeContract,
    TimeoutLimits,
    TimingEvidence,
    TlsEvidence,
    TlsVersion,
    TransportAttemptId,
    TransportFailureKind,
)
from newsroom.sources import (
    ObservationModel,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    VersionedPolicyRef,
)

NOW = UtcTimestamp.parse("2042-03-12T10:00:00.000000Z")
REQUEST_ID = AdapterRequestId.parse("00000000-0000-4000-8000-000000004001")
DEFINITION_ID = SourceDefinitionId.parse("00000000-0000-4000-8000-000000004002")
VERSION_ID = SourceDefinitionVersionId.parse("00000000-0000-4000-8000-000000004003")
OTHER_VERSION_ID = SourceDefinitionVersionId.parse("00000000-0000-4000-8000-000000004013")
ATTEMPT_ID = TransportAttemptId.parse("00000000-0000-4000-8000-000000004004")
CAPTURE_ID = CaptureId.parse("00000000-0000-4000-8000-000000004005")
PARSER_RESULT_ID = ParserResultId.parse("00000000-0000-4000-8000-000000004006")
PROPOSAL_ID = ObservationProposalId.parse("00000000-0000-4000-8000-000000004007")


def adapter(version: str = "v1", parser: str = "parser-v1") -> AdapterVersionRef:
    return AdapterVersionRef(
        adapter_id="fixture-adapter",
        adapter_version=version,
        parser_version=parser,
        normalizer_version="normalizer-v1",
    )


def json_shape() -> SourceShapeContract:
    return SourceShapeContract(
        shape_id="json-items-v1",
        kind=AdapterKind.JSON_DOCUMENT,
        items_path=("items",),
        fields=(
            ShapeField("id", ("id",), True),
            ShapeField("title", ("title",), True),
        ),
        identity_fields=("id",),
    )


def feed_shape() -> SourceShapeContract:
    return SourceShapeContract(
        shape_id="feed-items-v1",
        kind=AdapterKind.RSS_ATOM,
        items_path=(),
        fields=(
            ShapeField("id", ("id",), True),
            ShapeField("link", ("link",), True),
            ShapeField("title", ("title",), True),
        ),
        identity_fields=("id",),
    )


def document_shape() -> SourceShapeContract:
    return SourceShapeContract(
        shape_id="maintained-document-v1",
        kind=AdapterKind.MAINTAINED_DOCUMENT,
        items_path=(),
        fields=(
            ShapeField("body", ("body",), True, maximum_bytes=100_000),
            ShapeField("title", ("title",), False),
        ),
        identity_fields=("body",),
    )


def request(
    *,
    kind: AdapterKind = AdapterKind.JSON_DOCUMENT,
    observation_model: ObservationModel = ObservationModel.APPEND_ONLY,
    shape: SourceShapeContract | None = None,
    baseline: ObservationBaseline | None = None,
    parser_version: str = "parser-v1",
    max_items: int = 20,
    allowed_hosts: tuple[str, ...] = ("fixture.example",),
    allowed_content_types: tuple[str, ...] | None = None,
    allowed_encodings: tuple[BodyEncoding, ...] = (BodyEncoding.IDENTITY,),
) -> AdapterRequest:
    selected_shape = shape or {
        AdapterKind.JSON_DOCUMENT: json_shape(),
        AdapterKind.RSS_ATOM: feed_shape(),
        AdapterKind.MAINTAINED_DOCUMENT: document_shape(),
    }[kind]
    content_types = allowed_content_types or {
        AdapterKind.JSON_DOCUMENT: ("application/json",),
        AdapterKind.RSS_ATOM: (
            "application/atom+xml",
            "application/rss+xml",
            "application/xml",
        ),
        AdapterKind.MAINTAINED_DOCUMENT: ("text/html", "text/plain"),
    }[kind]
    return AdapterRequest(
        request_id=REQUEST_ID,
        source_definition_id=DEFINITION_ID,
        source_definition_version_id=VERSION_ID,
        adapter=adapter(parser=parser_version),
        kind=kind,
        observation_model=observation_model,
        endpoint="https://fixture.example/items",
        endpoint_policy=EndpointPolicy(
            "fixture-endpoint-v1",
            allowed_hosts,
        ),
        timeout_limits=TimeoutLimits(1_000, 2_000, 1_000, 5_000),
        body_limits=BodyLimits(
            100_000,
            1_000_000,
            100,
            content_types,
            allowed_encodings=allowed_encodings,
        ),
        parser_limits=ParserLimits(max_items, 32, 100_000, 10_000, 100),
        shape_contract=selected_shape,
        validator_contract=VersionedPolicyRef("fixture-validator", "v1"),
        requested_at=NOW,
        baseline=baseline,
    )


def baseline(
    representation_digest: str,
    *,
    version_id: SourceDefinitionVersionId = VERSION_ID,
    policy_version: str = "v1",
) -> ObservationBaseline:
    return ObservationBaseline(
        source_definition_version_id=version_id,
        validator_contract=VersionedPolicyRef(
            "fixture-validator",
            policy_version,
        ),
        representation_digest=representation_digest,
        validator=ConditionalValidator(etag='"fixture-etag"'),
        recorded_at=NOW,
    )


def scenario(
    *,
    status: int | None = 200,
    body: bytes = b'{"items":[{"id":"1","title":"One"}]}',
    content_type: str | None = "application/json; charset=utf-8",
    content_encoding: BodyEncoding = BodyEncoding.IDENTITY,
    redirects: tuple[RedirectHop, ...] = (),
    failure_kind: TransportFailureKind | None = None,
    timing: TimingEvidence | None = None,
    dns_addresses: tuple[str, ...] = ("93.184.216.34",),
    tls_valid: bool = True,
    tls_hostname_verified: bool = True,
    extra_headers: tuple[Header, ...] = (),
) -> FixtureTransportScenario:
    if failure_kind is not None:
        status = None
        body = b""
        headers: tuple[Header, ...] = ()
    else:
        values = list(extra_headers)
        values.append(Header("content-length", str(len(body))))
        if content_type is not None:
            values.append(Header("content-type", content_type))
        if content_encoding is not BodyEncoding.IDENTITY:
            values.append(Header("content-encoding", content_encoding.value.lower()))
        headers = tuple(sorted(values, key=lambda item: item.name))
    final_host = "fixture.example"
    if redirects:
        final_host = redirects[-1].to_url.split("/")[2].split(":")[0]
    return FixtureTransportScenario(
        scenario_id="fixture-scenario-v1",
        request_id=REQUEST_ID,
        attempt_id=ATTEMPT_ID,
        capture_id=CAPTURE_ID,
        parser_result_id=PARSER_RESULT_ID,
        proposal_id=PROPOSAL_ID,
        observed_at=NOW,
        dns_evidence=DnsEvidence(final_host, dns_addresses, NOW),
        tls_evidence=TlsEvidence(
            final_host,
            TlsVersion.TLS_1_3,
            tls_valid,
            tls_hostname_verified,
            NOW,
        ),
        timing=timing or TimingEvidence(10, 20, 5, 30),
        status_code=status,
        headers=headers,
        body=body,
        content_encoding=content_encoding,
        redirects=redirects,
        failure_kind=failure_kind,
    )


def gzip_scenario(body: bytes) -> FixtureTransportScenario:
    compressed = gzip.compress(body, mtime=0)
    return scenario(
        body=compressed,
        content_encoding=BodyEncoding.GZIP,
    )
