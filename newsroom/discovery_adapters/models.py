from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
    validate_sha256_digest,
)
from newsroom.authority.types import UtcTimestamp
from newsroom.sources import (
    ObservationModel,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    VersionedPolicyRef,
)

from .types import (
    AdapterContractError,
    AdapterExecutionProfile,
    AdapterKind,
    AdapterRequestId,
    AdapterVersionRef,
    BodyEncoding,
    BodyLimits,
    CaptureId,
    Completeness,
    EndpointPolicy,
    Header,
    ObservationProposalId,
    ObservationProposalOutcome,
    ParserLimits,
    ParserResultId,
    QuarantineRecommendation,
    RETAINED_RESPONSE_HEADER_NAMES,
    SourceShapeContract,
    TimeoutLimits,
    TlsVersion,
    TransportAttemptId,
    TransportFailureKind,
    bounded_text,
    canonical_host,
    require_token,
    sorted_headers,
    sorted_unique_text,
)


def _require_source_identity(
    definition_id: SourceDefinitionId,
    version_id: SourceDefinitionVersionId,
    *,
    identity: str,
) -> None:
    if not isinstance(definition_id, SourceDefinitionId):
        raise AdapterContractError(f"{identity} source definition must be typed")
    if not isinstance(version_id, SourceDefinitionVersionId):
        raise AdapterContractError(f"{identity} source version must be typed")


@dataclass(frozen=True, slots=True)
class ConditionalValidator:
    etag: str | None = None
    last_modified: str | None = None

    def __post_init__(self) -> None:
        if self.etag is None and self.last_modified is None:
            raise AdapterContractError(
                "conditional validator needs an ETag or Last-Modified"
            )
        if self.etag is not None:
            bounded_text(self.etag, field="etag", maximum_bytes=1024)
        if self.last_modified is not None:
            bounded_text(
                self.last_modified,
                field="last_modified",
                maximum_bytes=256,
            )

    def canonical_value(self) -> dict[str, str | None]:
        return {"etag": self.etag, "last_modified": self.last_modified}


@dataclass(frozen=True, slots=True)
class ObservationBaseline:
    source_definition_version_id: SourceDefinitionVersionId
    validator_contract: VersionedPolicyRef
    source_body_digest: str
    producer_slot_digest: str
    representation_digest: str
    item_keys: tuple[str, ...]
    validator: ConditionalValidator
    recorded_at: UtcTimestamp

    def __post_init__(self) -> None:
        if not isinstance(
            self.source_definition_version_id, SourceDefinitionVersionId
        ):
            raise AdapterContractError("baseline source version must be typed")
        if not isinstance(self.validator_contract, VersionedPolicyRef):
            raise AdapterContractError(
                "baseline validator contract must be typed"
            )
        for field, value in (
            ("baseline_source_body_digest", self.source_body_digest),
            ("baseline_producer_slot_digest", self.producer_slot_digest),
            ("baseline_representation_digest", self.representation_digest),
        ):
            validate_sha256_digest(value, field=field)
        sorted_unique_text(
            self.item_keys,
            field="baseline_item_keys",
            maximum_items=100_000,
            maximum_item_bytes=71,
            allow_empty=True,
        )
        for item in self.item_keys:
            validate_sha256_digest(item, field="baseline_item_key")
        if not isinstance(self.validator, ConditionalValidator):
            raise AdapterContractError("baseline validator must be typed")
        if not isinstance(self.recorded_at, UtcTimestamp):
            raise AdapterContractError(
                "baseline recording time must be typed"
            )

    @property
    def item_keys_digest(self) -> str:
        return digest_canonical(list(self.item_keys))

    def canonical_value(self) -> dict[str, object]:
        return {
            "source_definition_version_id": str(
                self.source_definition_version_id
            ),
            "validator_contract": self.validator_contract.canonical_value(),
            "source_body_digest": self.source_body_digest,
            "producer_slot_digest": self.producer_slot_digest,
            "representation_digest": self.representation_digest,
            "item_keys": list(self.item_keys),
            "item_keys_digest": self.item_keys_digest,
            "validator": self.validator.canonical_value(),
            "recorded_at": self.recorded_at.to_text(),
        }


@dataclass(frozen=True, slots=True)
class AdapterRequest:
    request_id: AdapterRequestId
    source_definition_id: SourceDefinitionId
    source_definition_version_id: SourceDefinitionVersionId
    adapter: AdapterVersionRef
    kind: AdapterKind
    observation_model: ObservationModel
    endpoint: str
    endpoint_policy: EndpointPolicy
    timeout_limits: TimeoutLimits
    body_limits: BodyLimits
    parser_limits: ParserLimits
    shape_contract: SourceShapeContract
    validator_contract: VersionedPolicyRef
    requested_at: UtcTimestamp
    baseline: ObservationBaseline | None = None
    profile: AdapterExecutionProfile = AdapterExecutionProfile.FIXTURE_REPLAY_ONLY

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, AdapterRequestId):
            raise AdapterContractError("adapter request identity must be typed")
        _require_source_identity(
            self.source_definition_id,
            self.source_definition_version_id,
            identity="adapter request",
        )
        if not isinstance(self.adapter, AdapterVersionRef):
            raise AdapterContractError(
                "adapter version reference must be typed"
            )
        if not isinstance(self.kind, AdapterKind):
            raise AdapterContractError("adapter kind must be typed")
        if not isinstance(self.observation_model, ObservationModel):
            raise AdapterContractError("observation model must be typed")
        bounded_text(
            self.endpoint,
            field="adapter_endpoint",
            maximum_bytes=4096,
        )
        if not isinstance(self.endpoint_policy, EndpointPolicy):
            raise AdapterContractError("endpoint policy must be typed")
        if not isinstance(self.timeout_limits, TimeoutLimits):
            raise AdapterContractError("timeout limits must be typed")
        if not isinstance(self.body_limits, BodyLimits):
            raise AdapterContractError("body limits must be typed")
        if not isinstance(self.parser_limits, ParserLimits):
            raise AdapterContractError("parser limits must be typed")
        if not isinstance(self.shape_contract, SourceShapeContract):
            raise AdapterContractError("shape contract must be typed")
        if self.shape_contract.kind is not self.kind:
            raise AdapterContractError(
                "shape contract kind differs from adapter kind"
            )
        if not isinstance(self.validator_contract, VersionedPolicyRef):
            raise AdapterContractError("validator contract must be typed")
        if not isinstance(self.requested_at, UtcTimestamp):
            raise AdapterContractError("request time must be typed")
        if self.baseline is not None and not isinstance(
            self.baseline, ObservationBaseline
        ):
            raise AdapterContractError("baseline must be typed")
        if self.profile is not AdapterExecutionProfile.FIXTURE_REPLAY_ONLY:
            raise AdapterContractError("Increment 3B is fixture/replay only")

    @property
    def producer_slot_digest(self) -> str:
        return digest_canonical(
            {
                "adapter": self.adapter.canonical_value(),
                "shape_contract_digest": self.shape_contract.digest,
            }
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "request_id": str(self.request_id),
            "source_definition_id": str(self.source_definition_id),
            "source_definition_version_id": str(
                self.source_definition_version_id
            ),
            "adapter": self.adapter.canonical_value(),
            "kind": self.kind.value,
            "observation_model": self.observation_model.value,
            "endpoint": self.endpoint,
            "endpoint_policy": self.endpoint_policy.canonical_value(),
            "timeout_limits": self.timeout_limits.canonical_value(),
            "body_limits": self.body_limits.canonical_value(),
            "parser_limits": self.parser_limits.canonical_value(),
            "shape_contract": self.shape_contract.canonical_value(),
            "producer_slot_digest": self.producer_slot_digest,
            "validator_contract": self.validator_contract.canonical_value(),
            "requested_at": self.requested_at.to_text(),
            "baseline": (
                None
                if self.baseline is None
                else self.baseline.canonical_value()
            ),
            "profile": self.profile.value,
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class DnsEvidence:
    host: str
    addresses: tuple[str, ...]
    observed_at: UtcTimestamp

    def __post_init__(self) -> None:
        canonical_host(self.host)
        sorted_unique_text(
            self.addresses,
            field="dns_addresses",
            maximum_items=32,
            maximum_item_bytes=64,
        )
        if not isinstance(self.observed_at, UtcTimestamp):
            raise AdapterContractError(
                "DNS observation time must be typed"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "host": self.host,
            "addresses": list(self.addresses),
            "observed_at": self.observed_at.to_text(),
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class TlsEvidence:
    host: str
    negotiated_version: TlsVersion
    certificate_valid: bool
    hostname_verified: bool
    observed_at: UtcTimestamp

    def __post_init__(self) -> None:
        canonical_host(self.host)
        if not isinstance(self.negotiated_version, TlsVersion):
            raise AdapterContractError(
                "negotiated TLS version must be typed"
            )
        if not isinstance(self.certificate_valid, bool):
            raise AdapterContractError(
                "certificate validity must be boolean"
            )
        if not isinstance(self.hostname_verified, bool):
            raise AdapterContractError(
                "hostname verification must be boolean"
            )
        if not isinstance(self.observed_at, UtcTimestamp):
            raise AdapterContractError(
                "TLS observation time must be typed"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "host": self.host,
            "negotiated_version": self.negotiated_version.value,
            "certificate_valid": self.certificate_valid,
            "hostname_verified": self.hostname_verified,
            "observed_at": self.observed_at.to_text(),
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class RedirectHop:
    from_url: str
    to_url: str
    status_code: int

    def __post_init__(self) -> None:
        bounded_text(
            self.from_url,
            field="redirect_from_url",
            maximum_bytes=4096,
        )
        bounded_text(
            self.to_url,
            field="redirect_to_url",
            maximum_bytes=4096,
        )
        if self.status_code not in {301, 302, 303, 307, 308}:
            raise AdapterContractError("redirect status code is invalid")
        if self.from_url == self.to_url:
            raise AdapterContractError("redirect hop must change the URL")

    def canonical_value(self) -> dict[str, object]:
        return {
            "from_url": self.from_url,
            "to_url": self.to_url,
            "status_code": self.status_code,
        }


@dataclass(frozen=True, slots=True)
class RedirectEvidence:
    url: str
    dns_evidence: DnsEvidence
    tls_evidence: TlsEvidence

    def __post_init__(self) -> None:
        bounded_text(
            self.url,
            field="redirect_evidence_url",
            maximum_bytes=4096,
        )
        if not isinstance(self.dns_evidence, DnsEvidence):
            raise AdapterContractError(
                "redirect DNS evidence must be typed"
            )
        if not isinstance(self.tls_evidence, TlsEvidence):
            raise AdapterContractError(
                "redirect TLS evidence must be typed"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "url": self.url,
            "dns_evidence": self.dns_evidence.canonical_value(),
            "tls_evidence": self.tls_evidence.canonical_value(),
        }


@dataclass(frozen=True, slots=True)
class TimingEvidence:
    connect_ms: int
    read_ms: int
    maximum_idle_ms: int
    total_ms: int

    def __post_init__(self) -> None:
        for field, value in (
            ("connect_ms", self.connect_ms),
            ("read_ms", self.read_ms),
            ("maximum_idle_ms", self.maximum_idle_ms),
            ("total_ms", self.total_ms),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise AdapterContractError(
                    f"{field} must be a non-negative integer"
                )
        if self.total_ms < max(
            self.connect_ms,
            self.read_ms,
            self.maximum_idle_ms,
        ):
            raise AdapterContractError(
                "total timing cannot be smaller than a component"
            )

    def canonical_value(self) -> dict[str, int]:
        return {
            "connect_ms": self.connect_ms,
            "read_ms": self.read_ms,
            "maximum_idle_ms": self.maximum_idle_ms,
            "total_ms": self.total_ms,
        }


@dataclass(frozen=True, slots=True)
class FixtureTransportScenario:
    scenario_id: str
    request_id: AdapterRequestId
    attempt_id: TransportAttemptId
    capture_id: CaptureId
    parser_result_id: ParserResultId
    proposal_id: ObservationProposalId
    observed_at: UtcTimestamp
    dns_evidence: DnsEvidence
    tls_evidence: TlsEvidence
    timing: TimingEvidence
    status_code: int | None
    headers: tuple[Header, ...]
    body: bytes
    content_encoding: BodyEncoding = BodyEncoding.IDENTITY
    redirects: tuple[RedirectHop, ...] = ()
    redirect_evidence: tuple[RedirectEvidence, ...] = ()
    failure_kind: TransportFailureKind | None = None
    profile: AdapterExecutionProfile = AdapterExecutionProfile.FIXTURE_REPLAY_ONLY

    def __post_init__(self) -> None:
        require_token(self.scenario_id, field="fixture_scenario_id")
        for value, expected, field in (
            (self.request_id, AdapterRequestId, "request identity"),
            (self.attempt_id, TransportAttemptId, "attempt identity"),
            (self.capture_id, CaptureId, "capture identity"),
            (
                self.parser_result_id,
                ParserResultId,
                "parser-result identity",
            ),
            (self.proposal_id, ObservationProposalId, "proposal identity"),
        ):
            if not isinstance(value, expected):
                raise AdapterContractError(
                    f"fixture {field} must be typed"
                )
        if not isinstance(self.observed_at, UtcTimestamp):
            raise AdapterContractError(
                "fixture observation time must be typed"
            )
        if not isinstance(self.dns_evidence, DnsEvidence):
            raise AdapterContractError("fixture DNS evidence must be typed")
        if not isinstance(self.tls_evidence, TlsEvidence):
            raise AdapterContractError("fixture TLS evidence must be typed")
        if not isinstance(self.timing, TimingEvidence):
            raise AdapterContractError("fixture timing evidence must be typed")
        if self.status_code is not None and (
            isinstance(self.status_code, bool)
            or not isinstance(self.status_code, int)
            or not 100 <= self.status_code <= 599
        ):
            raise AdapterContractError("fixture status code is invalid")
        if not isinstance(self.body, bytes):
            raise AdapterContractError(
                "fixture body must be immutable bytes"
            )
        if not isinstance(self.content_encoding, BodyEncoding):
            raise AdapterContractError(
                "fixture content encoding must be typed"
            )
        if self.headers != sorted_headers(self.headers):
            raise AdapterContractError(
                "fixture headers must be canonically sorted"
            )
        if not isinstance(self.redirects, tuple) or any(
            not isinstance(item, RedirectHop) for item in self.redirects
        ):
            raise AdapterContractError(
                "fixture redirects must be a typed tuple"
            )
        if not isinstance(self.redirect_evidence, tuple) or any(
            not isinstance(item, RedirectEvidence)
            for item in self.redirect_evidence
        ):
            raise AdapterContractError(
                "fixture redirect evidence must be a typed tuple"
            )
        if self.failure_kind is not None and not isinstance(
            self.failure_kind, TransportFailureKind
        ):
            raise AdapterContractError(
                "fixture failure kind must be typed"
            )
        if self.failure_kind is not None and (
            self.status_code is not None or self.body or self.headers
        ):
            raise AdapterContractError(
                "transport-failure fixture cannot also claim an HTTP response"
            )
        if self.failure_kind is None and self.status_code is None:
            raise AdapterContractError(
                "successful fixture requires an HTTP status"
            )
        if self.profile is not AdapterExecutionProfile.FIXTURE_REPLAY_ONLY:
            raise AdapterContractError(
                "fixture transport cannot gain network authority"
            )

    def header(self, name: str) -> str | None:
        selected = name.lower()
        return next(
            (item.value for item in self.headers if item.name == selected),
            None,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "request_id": str(self.request_id),
            "attempt_id": str(self.attempt_id),
            "capture_id": str(self.capture_id),
            "parser_result_id": str(self.parser_result_id),
            "proposal_id": str(self.proposal_id),
            "observed_at": self.observed_at.to_text(),
            "dns_evidence": self.dns_evidence.canonical_value(),
            "tls_evidence": self.tls_evidence.canonical_value(),
            "timing": self.timing.canonical_value(),
            "status_code": self.status_code,
            "headers": [item.canonical_value() for item in self.headers],
            "body_digest": digest_bytes(self.body),
            "body_length": len(self.body),
            "content_encoding": self.content_encoding.value,
            "redirects": [item.canonical_value() for item in self.redirects],
            "redirect_evidence": [
                item.canonical_value() for item in self.redirect_evidence
            ],
            "failure_kind": (
                None
                if self.failure_kind is None
                else self.failure_kind.value
            ),
            "profile": self.profile.value,
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class TransportReceipt:
    attempt_id: TransportAttemptId
    request_id: AdapterRequestId
    source_definition_id: SourceDefinitionId
    source_definition_version_id: SourceDefinitionVersionId
    scenario_id: str
    final_url: str
    status_code: int | None
    headers: tuple[Header, ...]
    content_encoding: BodyEncoding
    compressed_digest: str
    compressed_length: int
    decompressed_digest: str | None
    decompressed_length: int | None
    dns_evidence_digest: str
    tls_evidence_digest: str
    redirect_digest: str
    redirect_evidence_digest: str
    timing: TimingEvidence
    observed_at: UtcTimestamp
    failure_kind: TransportFailureKind | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.attempt_id, TransportAttemptId):
            raise AdapterContractError(
                "transport receipt attempt must be typed"
            )
        if not isinstance(self.request_id, AdapterRequestId):
            raise AdapterContractError(
                "transport receipt request must be typed"
            )
        _require_source_identity(
            self.source_definition_id,
            self.source_definition_version_id,
            identity="transport receipt",
        )
        require_token(self.scenario_id, field="receipt_scenario_id")
        bounded_text(
            self.final_url,
            field="receipt_final_url",
            maximum_bytes=4096,
        )
        if self.status_code is not None and (
            isinstance(self.status_code, bool)
            or not isinstance(self.status_code, int)
            or not 100 <= self.status_code <= 599
        ):
            raise AdapterContractError("receipt status code is invalid")
        if self.headers != sorted_headers(self.headers):
            raise AdapterContractError(
                "receipt headers must be canonically sorted"
            )
        if any(
            item.name not in RETAINED_RESPONSE_HEADER_NAMES
            for item in self.headers
        ):
            raise AdapterContractError(
                "receipt contains non-retained response metadata"
            )
        if not isinstance(self.content_encoding, BodyEncoding):
            raise AdapterContractError(
                "receipt content encoding must be typed"
            )
        for field, value in (
            ("compressed_digest", self.compressed_digest),
            ("dns_evidence_digest", self.dns_evidence_digest),
            ("tls_evidence_digest", self.tls_evidence_digest),
            ("redirect_digest", self.redirect_digest),
            ("redirect_evidence_digest", self.redirect_evidence_digest),
        ):
            validate_sha256_digest(value, field=field)
        if self.decompressed_digest is not None:
            validate_sha256_digest(
                self.decompressed_digest,
                field="decompressed_digest",
            )
        for field, value in (
            ("compressed_length", self.compressed_length),
            ("decompressed_length", self.decompressed_length),
        ):
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise AdapterContractError(
                    f"{field} must be non-negative"
                )
        if (self.decompressed_digest is None) != (
            self.decompressed_length is None
        ):
            raise AdapterContractError(
                "decompressed digest and length move together"
            )
        if not isinstance(self.timing, TimingEvidence):
            raise AdapterContractError("receipt timing must be typed")
        if not isinstance(self.observed_at, UtcTimestamp):
            raise AdapterContractError(
                "receipt observation time must be typed"
            )
        if self.failure_kind is not None and not isinstance(
            self.failure_kind, TransportFailureKind
        ):
            raise AdapterContractError(
                "receipt failure kind must be typed"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "attempt_id": str(self.attempt_id),
            "request_id": str(self.request_id),
            "source_definition_id": str(self.source_definition_id),
            "source_definition_version_id": str(
                self.source_definition_version_id
            ),
            "scenario_id": self.scenario_id,
            "final_url": self.final_url,
            "status_code": self.status_code,
            "headers": [item.canonical_value() for item in self.headers],
            "content_encoding": self.content_encoding.value,
            "compressed_digest": self.compressed_digest,
            "compressed_length": self.compressed_length,
            "decompressed_digest": self.decompressed_digest,
            "decompressed_length": self.decompressed_length,
            "dns_evidence_digest": self.dns_evidence_digest,
            "tls_evidence_digest": self.tls_evidence_digest,
            "redirect_digest": self.redirect_digest,
            "redirect_evidence_digest": self.redirect_evidence_digest,
            "timing": self.timing.canonical_value(),
            "observed_at": self.observed_at.to_text(),
            "failure_kind": (
                None
                if self.failure_kind is None
                else self.failure_kind.value
            ),
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class Capture:
    capture_id: CaptureId
    attempt_id: TransportAttemptId
    request_id: AdapterRequestId
    source_definition_id: SourceDefinitionId
    source_definition_version_id: SourceDefinitionVersionId
    receipt_digest: str
    content_type: str
    charset: str
    body: bytes
    captured_at: UtcTimestamp

    def __post_init__(self) -> None:
        if not isinstance(self.capture_id, CaptureId):
            raise AdapterContractError("capture identity must be typed")
        if not isinstance(self.attempt_id, TransportAttemptId):
            raise AdapterContractError("capture attempt must be typed")
        if not isinstance(self.request_id, AdapterRequestId):
            raise AdapterContractError(
                "capture request identity must be typed"
            )
        _require_source_identity(
            self.source_definition_id,
            self.source_definition_version_id,
            identity="capture",
        )
        validate_sha256_digest(
            self.receipt_digest,
            field="capture_receipt_digest",
        )
        if (
            not isinstance(self.content_type, str)
            or self.content_type != self.content_type.lower()
            or "/" not in self.content_type
            or ";" in self.content_type
        ):
            raise AdapterContractError(
                "capture content type is not canonical"
            )
        if (
            not isinstance(self.charset, str)
            or self.charset != self.charset.lower()
        ):
            raise AdapterContractError("capture charset is not canonical")
        if not isinstance(self.body, bytes):
            raise AdapterContractError(
                "capture body must be immutable bytes"
            )
        if not isinstance(self.captured_at, UtcTimestamp):
            raise AdapterContractError("capture time must be typed")

    @property
    def body_digest(self) -> str:
        return digest_bytes(self.body)

    def canonical_value(self) -> dict[str, object]:
        return {
            "capture_id": str(self.capture_id),
            "attempt_id": str(self.attempt_id),
            "request_id": str(self.request_id),
            "source_definition_id": str(self.source_definition_id),
            "source_definition_version_id": str(
                self.source_definition_version_id
            ),
            "receipt_digest": self.receipt_digest,
            "content_type": self.content_type,
            "charset": self.charset,
            "body_digest": self.body_digest,
            "body_length": len(self.body),
            "captured_at": self.captured_at.to_text(),
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class ParsedField:
    name: str
    value: str

    def __post_init__(self) -> None:
        require_token(self.name, field="parsed_field_name")
        bounded_text(
            self.value,
            field="parsed_field_value",
            maximum_bytes=4 * 1024 * 1024,
            allow_empty=True,
        )

    def canonical_value(self) -> dict[str, str]:
        return {"name": self.name, "value": self.value}


@dataclass(frozen=True, slots=True)
class ParsedItem:
    item_key: str
    fields: tuple[ParsedField, ...]
    uncertainties: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        validate_sha256_digest(self.item_key, field="parsed_item_key")
        if not isinstance(self.fields, tuple) or not self.fields:
            raise AdapterContractError(
                "parsed item fields must be a non-empty tuple"
            )
        if any(not isinstance(item, ParsedField) for item in self.fields):
            raise AdapterContractError("parsed item fields must be typed")
        if self.fields != tuple(
            sorted(self.fields, key=lambda item: item.name)
        ):
            raise AdapterContractError("parsed item fields must be sorted")
        if len(self.fields) != len({item.name for item in self.fields}):
            raise AdapterContractError(
                "parsed item field names must be unique"
            )
        sorted_unique_text(
            self.uncertainties,
            field="parsed_item_uncertainties",
            maximum_items=32,
            maximum_item_bytes=1024,
            allow_empty=True,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "item_key": self.item_key,
            "fields": [item.canonical_value() for item in self.fields],
            "uncertainties": list(self.uncertainties),
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class ParserIssue:
    code: str
    message: str
    item_index: int | None = None

    def __post_init__(self) -> None:
        require_token(self.code, field="parser_issue_code")
        bounded_text(
            self.message,
            field="parser_issue_message",
            maximum_bytes=2048,
        )
        if self.item_index is not None and (
            isinstance(self.item_index, bool)
            or not isinstance(self.item_index, int)
            or self.item_index < 0
        ):
            raise AdapterContractError(
                "parser issue item index is invalid"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "item_index": self.item_index,
        }


@dataclass(frozen=True, slots=True)
class ParserResult:
    parser_result_id: ParserResultId
    capture_id: CaptureId
    capture_digest: str
    request_id: AdapterRequestId
    source_definition_id: SourceDefinitionId
    source_definition_version_id: SourceDefinitionVersionId
    adapter: AdapterVersionRef
    shape_contract_digest: str
    source_body_digest: str
    producer_slot_digest: str
    completeness: Completeness
    items: tuple[ParsedItem, ...]
    issues: tuple[ParserIssue, ...]
    representation_digest: str
    shape_drift: bool
    produced_at: UtcTimestamp

    def __post_init__(self) -> None:
        if not isinstance(self.parser_result_id, ParserResultId):
            raise AdapterContractError(
                "parser-result identity must be typed"
            )
        if not isinstance(self.capture_id, CaptureId):
            raise AdapterContractError("parser-result capture must be typed")
        validate_sha256_digest(
            self.capture_digest,
            field="parser_capture_digest",
        )
        if not isinstance(self.request_id, AdapterRequestId):
            raise AdapterContractError("parser-result request must be typed")
        _require_source_identity(
            self.source_definition_id,
            self.source_definition_version_id,
            identity="parser result",
        )
        if not isinstance(self.adapter, AdapterVersionRef):
            raise AdapterContractError("parser-result adapter must be typed")
        for field, value in (
            ("parser_shape_contract_digest", self.shape_contract_digest),
            ("parser_source_body_digest", self.source_body_digest),
            ("parser_producer_slot_digest", self.producer_slot_digest),
            ("parser_representation_digest", self.representation_digest),
        ):
            validate_sha256_digest(value, field=field)
        if not isinstance(self.completeness, Completeness):
            raise AdapterContractError(
                "parser completeness must be typed"
            )
        if not isinstance(self.items, tuple) or any(
            not isinstance(item, ParsedItem) for item in self.items
        ):
            raise AdapterContractError("parser items must be a typed tuple")
        if self.items != tuple(
            sorted(self.items, key=lambda item: item.item_key)
        ):
            raise AdapterContractError(
                "parser items must be sorted by key"
            )
        if len(self.items) != len({item.item_key for item in self.items}):
            raise AdapterContractError("parser item keys must be unique")
        if not isinstance(self.issues, tuple) or any(
            not isinstance(item, ParserIssue) for item in self.issues
        ):
            raise AdapterContractError("parser issues must be a typed tuple")
        if self.issues != tuple(
            sorted(
                self.issues,
                key=lambda item: (
                    item.code,
                    -1 if item.item_index is None else item.item_index,
                    item.message,
                ),
            )
        ):
            raise AdapterContractError(
                "parser issues must be canonically sorted"
            )
        if not isinstance(self.shape_drift, bool):
            raise AdapterContractError(
                "shape-drift flag must be boolean"
            )
        if not isinstance(self.produced_at, UtcTimestamp):
            raise AdapterContractError(
                "parser production time must be typed"
            )

    @property
    def item_keys(self) -> tuple[str, ...]:
        return tuple(item.item_key for item in self.items)

    @property
    def item_keys_digest(self) -> str:
        return digest_canonical(list(self.item_keys))

    def canonical_value(self) -> dict[str, object]:
        return {
            "parser_result_id": str(self.parser_result_id),
            "capture_id": str(self.capture_id),
            "capture_digest": self.capture_digest,
            "request_id": str(self.request_id),
            "source_definition_id": str(self.source_definition_id),
            "source_definition_version_id": str(
                self.source_definition_version_id
            ),
            "adapter": self.adapter.canonical_value(),
            "shape_contract_digest": self.shape_contract_digest,
            "source_body_digest": self.source_body_digest,
            "producer_slot_digest": self.producer_slot_digest,
            "completeness": self.completeness.value,
            "items": [item.canonical_value() for item in self.items],
            "item_keys_digest": self.item_keys_digest,
            "issues": [item.canonical_value() for item in self.issues],
            "representation_digest": self.representation_digest,
            "shape_drift": self.shape_drift,
            "produced_at": self.produced_at.to_text(),
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class ObservationProposal:
    proposal_id: ObservationProposalId
    request_id: AdapterRequestId
    source_definition_id: SourceDefinitionId
    source_definition_version_id: SourceDefinitionVersionId
    outcome: ObservationProposalOutcome
    reason_codes: tuple[str, ...]
    quarantine: QuarantineRecommendation
    incomplete: bool
    receipt: TransportReceipt | None = None
    capture: Capture | None = None
    parser_result: ParserResult | None = None
    candidate_items: tuple[ParsedItem, ...] = ()
    authority_effect: str = "NONE"

    def __post_init__(self) -> None:
        if not isinstance(self.proposal_id, ObservationProposalId):
            raise AdapterContractError(
                "observation proposal identity must be typed"
            )
        if not isinstance(self.request_id, AdapterRequestId):
            raise AdapterContractError(
                "observation proposal request must be typed"
            )
        _require_source_identity(
            self.source_definition_id,
            self.source_definition_version_id,
            identity="proposal",
        )
        if not isinstance(self.outcome, ObservationProposalOutcome):
            raise AdapterContractError("proposal outcome must be typed")
        sorted_unique_text(
            self.reason_codes,
            field="proposal_reason_codes",
            maximum_items=32,
            maximum_item_bytes=128,
        )
        if not isinstance(self.quarantine, QuarantineRecommendation):
            raise AdapterContractError(
                "quarantine recommendation must be typed"
            )
        if not isinstance(self.incomplete, bool):
            raise AdapterContractError(
                "proposal incomplete flag must be boolean"
            )
        if self.receipt is not None and not isinstance(
            self.receipt, TransportReceipt
        ):
            raise AdapterContractError("proposal receipt must be typed")
        if self.capture is not None and not isinstance(
            self.capture, Capture
        ):
            raise AdapterContractError("proposal capture must be typed")
        if self.parser_result is not None and not isinstance(
            self.parser_result, ParserResult
        ):
            raise AdapterContractError(
                "proposal parser result must be typed"
            )
        if not isinstance(self.candidate_items, tuple) or any(
            not isinstance(item, ParsedItem) for item in self.candidate_items
        ):
            raise AdapterContractError(
                "proposal candidates must be a typed tuple"
            )
        if self.candidate_items != tuple(
            sorted(self.candidate_items, key=lambda item: item.item_key)
        ):
            raise AdapterContractError(
                "proposal candidates must be sorted"
            )
        if self.authority_effect != "NONE":
            raise AdapterContractError(
                "adapter proposals cannot commit authority"
            )
        self._validate_lineage()
        self._validate_outcome()

    def _validate_lineage(self) -> None:
        expected = (
            self.request_id,
            self.source_definition_id,
            self.source_definition_version_id,
        )
        if self.receipt is not None:
            actual = (
                self.receipt.request_id,
                self.receipt.source_definition_id,
                self.receipt.source_definition_version_id,
            )
            if actual != expected:
                raise AdapterContractError(
                    "proposal receipt lineage differs from proposal"
                )
        if self.capture is not None:
            actual = (
                self.capture.request_id,
                self.capture.source_definition_id,
                self.capture.source_definition_version_id,
            )
            if actual != expected:
                raise AdapterContractError(
                    "proposal capture lineage differs from proposal"
                )
            if self.receipt is None:
                raise AdapterContractError(
                    "capture requires a transport receipt"
                )
            if (
                self.capture.attempt_id != self.receipt.attempt_id
                or self.capture.receipt_digest != self.receipt.digest
            ):
                raise AdapterContractError(
                    "capture is not bound to the exact receipt"
                )
        if self.parser_result is not None:
            actual = (
                self.parser_result.request_id,
                self.parser_result.source_definition_id,
                self.parser_result.source_definition_version_id,
            )
            if actual != expected:
                raise AdapterContractError(
                    "proposal parser lineage differs from proposal"
                )
            if self.capture is None:
                raise AdapterContractError(
                    "parser result requires a capture"
                )
            if (
                self.parser_result.capture_id != self.capture.capture_id
                or self.parser_result.capture_digest != self.capture.digest
                or self.parser_result.source_body_digest
                != self.capture.body_digest
            ):
                raise AdapterContractError(
                    "parser result is not bound to the exact capture"
                )

    def _validate_outcome(self) -> None:
        candidate_outcomes = {
            ObservationProposalOutcome.SUCCESS_CHANGED,
            ObservationProposalOutcome.SUCCESS_PARTIAL,
            ObservationProposalOutcome.SUCCESS_TRUNCATED,
        }
        if self.outcome in candidate_outcomes and not self.candidate_items:
            raise AdapterContractError(
                "changed proposal requires candidate items"
            )
        if self.outcome not in candidate_outcomes and self.candidate_items:
            raise AdapterContractError(
                "non-change proposal cannot carry candidates"
            )
        if self.outcome in {
            ObservationProposalOutcome.SUCCESS_PARTIAL,
            ObservationProposalOutcome.SUCCESS_TRUNCATED,
        } and not self.incomplete:
            raise AdapterContractError(
                "partial or truncated proposal must remain incomplete"
            )
        if self.outcome in {
            ObservationProposalOutcome.SUCCESS_CHANGED,
            ObservationProposalOutcome.SUCCESS_EMPTY,
            ObservationProposalOutcome.SUCCESS_UNCHANGED,
        } and self.incomplete:
            raise AdapterContractError(
                "complete success cannot be marked incomplete"
            )
        if self.parser_result is not None and (
            self.parser_result.items != self.candidate_items
            and self.outcome in candidate_outcomes
        ):
            raise AdapterContractError(
                "proposal candidates differ from parser result"
            )
        if (
            self.outcome is ObservationProposalOutcome.BLOCKED
            and self.receipt is not None
        ):
            raise AdapterContractError(
                "preflight block occurs before a receipt"
            )
        if self.outcome in {
            ObservationProposalOutcome.MALFORMED,
            ObservationProposalOutcome.SHAPE_DRIFT,
        } and self.parser_result is None:
            raise AdapterContractError(
                "parser failure outcome requires parser evidence"
            )

    def canonical_value(self) -> dict[str, Any]:
        return {
            "proposal_id": str(self.proposal_id),
            "request_id": str(self.request_id),
            "source_definition_id": str(self.source_definition_id),
            "source_definition_version_id": str(
                self.source_definition_version_id
            ),
            "outcome": self.outcome.value,
            "reason_codes": list(self.reason_codes),
            "quarantine": self.quarantine.value,
            "incomplete": self.incomplete,
            "receipt_digest": (
                None if self.receipt is None else self.receipt.digest
            ),
            "capture_digest": (
                None if self.capture is None else self.capture.digest
            ),
            "parser_result_digest": (
                None
                if self.parser_result is None
                else self.parser_result.digest
            ),
            "candidate_item_digests": [
                item.digest for item in self.candidate_items
            ],
            "authority_effect": self.authority_effect,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


__all__ = [
    "AdapterRequest",
    "Capture",
    "ConditionalValidator",
    "DnsEvidence",
    "FixtureTransportScenario",
    "ObservationBaseline",
    "ObservationProposal",
    "ParsedField",
    "ParsedItem",
    "ParserIssue",
    "ParserResult",
    "RedirectEvidence",
    "RedirectHop",
    "TimingEvidence",
    "TlsEvidence",
    "TransportReceipt",
]
