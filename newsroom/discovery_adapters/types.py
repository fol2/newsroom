from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Iterable

from newsroom.authority.canonical import digest_canonical
from newsroom.authority.types import UUIDv4Id


class AdapterContractError(ValueError):
    """A fixture adapter contract or value is malformed."""


class AdapterRequestId(UUIDv4Id):
    pass


class TransportAttemptId(UUIDv4Id):
    pass


class CaptureId(UUIDv4Id):
    pass


class ParserResultId(UUIDv4Id):
    pass


class ObservationProposalId(UUIDv4Id):
    pass


class AdapterExecutionProfile(StrEnum):
    FIXTURE_REPLAY_ONLY = "FIXTURE_REPLAY_ONLY"


class AdapterKind(StrEnum):
    RSS_ATOM = "RSS_ATOM"
    JSON_DOCUMENT = "JSON_DOCUMENT"
    MAINTAINED_DOCUMENT = "MAINTAINED_DOCUMENT"


class BodyEncoding(StrEnum):
    IDENTITY = "IDENTITY"
    GZIP = "GZIP"
    DEFLATE = "DEFLATE"


class Completeness(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    TRUNCATED = "TRUNCATED"


class ObservationProposalOutcome(StrEnum):
    BLOCKED = "BLOCKED"
    SUCCESS_EMPTY = "SUCCESS_EMPTY"
    SUCCESS_UNCHANGED = "SUCCESS_UNCHANGED"
    SUCCESS_CHANGED = "SUCCESS_CHANGED"
    SUCCESS_PARTIAL = "SUCCESS_PARTIAL"
    SUCCESS_TRUNCATED = "SUCCESS_TRUNCATED"
    REDIRECTED = "REDIRECTED"
    RATE_LIMITED = "RATE_LIMITED"
    UNAUTHORISED = "UNAUTHORISED"
    NOT_FOUND = "NOT_FOUND"
    GONE = "GONE"
    MALFORMED = "MALFORMED"
    SHAPE_DRIFT = "SHAPE_DRIFT"
    TRANSPORT_FAILED = "TRANSPORT_FAILED"


class TransportFailureKind(StrEnum):
    CONNECTION = "CONNECTION"
    DNS = "DNS"
    TLS = "TLS"
    CONNECT_TIMEOUT = "CONNECT_TIMEOUT"
    READ_TIMEOUT = "READ_TIMEOUT"
    IDLE_TIMEOUT = "IDLE_TIMEOUT"
    TOTAL_TIMEOUT = "TOTAL_TIMEOUT"


class QuarantineRecommendation(StrEnum):
    NONE = "NONE"
    REVIEW = "REVIEW"
    QUARANTINE = "QUARANTINE"


class TlsVersion(StrEnum):
    TLS_1_2 = "TLS_1_2"
    TLS_1_3 = "TLS_1_3"

    @property
    def rank(self) -> int:
        return {TlsVersion.TLS_1_2: 12, TlsVersion.TLS_1_3: 13}[self]


_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_HOST = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_HEADER = re.compile(r"^[a-z0-9!#$%&'*+.^_`|~-]{1,128}$")

# Receipts retain only protocol metadata needed for parsing, validation,
# retry/back-pressure or conditional requests. Provider cookies and arbitrary
# response metadata never enter the durable proposal record.
RETAINED_RESPONSE_HEADER_NAMES = frozenset(
    {
        "content-encoding",
        "content-length",
        "content-type",
        "etag",
        "last-modified",
        "location",
        "retry-after",
    }
)


def require_token(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise AdapterContractError(f"{field} is not a canonical token")
    return value


def bounded_text(
    value: str,
    *,
    field: str,
    maximum_bytes: int = 4096,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str) or value != value.strip() or "\x00" in value:
        raise AdapterContractError(f"{field} must be canonical text")
    if not allow_empty and not value:
        raise AdapterContractError(f"{field} cannot be empty")
    if len(value.encode("utf-8")) > maximum_bytes:
        raise AdapterContractError(f"{field} exceeds its byte bound")
    return value


def sorted_unique_text(
    values: Iterable[str],
    *,
    field: str,
    maximum_items: int = 64,
    maximum_item_bytes: int = 1024,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise AdapterContractError(f"{field} must be an immutable tuple")
    if not allow_empty and not values:
        raise AdapterContractError(f"{field} cannot be empty")
    if len(values) > maximum_items:
        raise AdapterContractError(f"{field} exceeds its item bound")
    result = tuple(
        bounded_text(
            item,
            field=field,
            maximum_bytes=maximum_item_bytes,
        )
        for item in values
    )
    if result != tuple(sorted(set(result))):
        raise AdapterContractError(f"{field} must be sorted and unique")
    return result


def canonical_host(value: str) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip().lower()
        or value.endswith(".")
    ):
        raise AdapterContractError("host must be canonical lowercase text")
    try:
        ascii_host = value.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise AdapterContractError("host IDNA encoding is invalid") from exc
    if ascii_host != value or _HOST.fullmatch(value) is None:
        raise AdapterContractError("host is not a canonical DNS name")
    return value


@dataclass(frozen=True, slots=True)
class AdapterVersionRef:
    adapter_id: str
    adapter_version: str
    parser_version: str
    normalizer_version: str

    def __post_init__(self) -> None:
        for field, value in (
            ("adapter_id", self.adapter_id),
            ("adapter_version", self.adapter_version),
            ("parser_version", self.parser_version),
            ("normalizer_version", self.normalizer_version),
        ):
            require_token(value, field=field)

    def canonical_value(self) -> dict[str, str]:
        return {
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "parser_version": self.parser_version,
            "normalizer_version": self.normalizer_version,
        }


@dataclass(frozen=True, slots=True)
class TimeoutLimits:
    connect_ms: int
    read_ms: int
    idle_ms: int
    total_ms: int

    def __post_init__(self) -> None:
        for field, value in (
            ("connect_ms", self.connect_ms),
            ("read_ms", self.read_ms),
            ("idle_ms", self.idle_ms),
            ("total_ms", self.total_ms),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 1 <= value <= 600_000
            ):
                raise AdapterContractError(
                    f"{field} must be between 1 and 600000"
                )
        if self.total_ms < max(self.connect_ms, self.read_ms, self.idle_ms):
            raise AdapterContractError(
                "total timeout cannot be smaller than a component"
            )

    def canonical_value(self) -> dict[str, int]:
        return {
            "connect_ms": self.connect_ms,
            "read_ms": self.read_ms,
            "idle_ms": self.idle_ms,
            "total_ms": self.total_ms,
        }


@dataclass(frozen=True, slots=True)
class BodyLimits:
    max_compressed_bytes: int
    max_decompressed_bytes: int
    max_decompression_ratio: int
    allowed_content_types: tuple[str, ...]
    allowed_charsets: tuple[str, ...] = ("utf-8",)
    allowed_encodings: tuple[BodyEncoding, ...] = (BodyEncoding.IDENTITY,)

    def __post_init__(self) -> None:
        for field, value, maximum in (
            (
                "max_compressed_bytes",
                self.max_compressed_bytes,
                64 * 1024 * 1024,
            ),
            (
                "max_decompressed_bytes",
                self.max_decompressed_bytes,
                128 * 1024 * 1024,
            ),
            ("max_decompression_ratio", self.max_decompression_ratio, 10_000),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 1 <= value <= maximum
            ):
                raise AdapterContractError(f"{field} is outside its safe bound")
        if self.max_decompressed_bytes < self.max_compressed_bytes:
            raise AdapterContractError("decompressed byte bound cannot be smaller")
        content_types = sorted_unique_text(
            self.allowed_content_types,
            field="allowed_content_types",
            maximum_items=32,
            maximum_item_bytes=128,
        )
        if any(
            item != item.lower() or "/" not in item or ";" in item
            for item in content_types
        ):
            raise AdapterContractError(
                "content types must be lowercase media types"
            )
        charsets = sorted_unique_text(
            self.allowed_charsets,
            field="allowed_charsets",
            maximum_items=8,
            maximum_item_bytes=32,
        )
        if any(item != item.lower() for item in charsets):
            raise AdapterContractError("charsets must be lowercase")
        if not isinstance(self.allowed_encodings, tuple) or not self.allowed_encodings:
            raise AdapterContractError(
                "allowed encodings must be a non-empty tuple"
            )
        if any(
            not isinstance(item, BodyEncoding) for item in self.allowed_encodings
        ):
            raise AdapterContractError("allowed encodings must be typed")
        if self.allowed_encodings != tuple(
            sorted(set(self.allowed_encodings), key=lambda item: item.value)
        ):
            raise AdapterContractError(
                "allowed encodings must be sorted and unique"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "max_compressed_bytes": self.max_compressed_bytes,
            "max_decompressed_bytes": self.max_decompressed_bytes,
            "max_decompression_ratio": self.max_decompression_ratio,
            "allowed_content_types": list(self.allowed_content_types),
            "allowed_charsets": list(self.allowed_charsets),
            "allowed_encodings": [item.value for item in self.allowed_encodings],
        }


@dataclass(frozen=True, slots=True)
class ParserLimits:
    max_items: int
    max_depth: int
    max_scalar_bytes: int
    max_collection_entries: int
    max_xml_attributes: int

    def __post_init__(self) -> None:
        for field, value, maximum in (
            ("max_items", self.max_items, 100_000),
            ("max_depth", self.max_depth, 256),
            ("max_scalar_bytes", self.max_scalar_bytes, 4 * 1024 * 1024),
            ("max_collection_entries", self.max_collection_entries, 1_000_000),
            ("max_xml_attributes", self.max_xml_attributes, 1_000_000),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 1 <= value <= maximum
            ):
                raise AdapterContractError(f"{field} is outside its safe bound")

    def canonical_value(self) -> dict[str, int]:
        return {
            "max_items": self.max_items,
            "max_depth": self.max_depth,
            "max_scalar_bytes": self.max_scalar_bytes,
            "max_collection_entries": self.max_collection_entries,
            "max_xml_attributes": self.max_xml_attributes,
        }


@dataclass(frozen=True, slots=True)
class EndpointPolicy:
    policy_id: str
    allowed_hosts: tuple[str, ...]
    allowed_ports: tuple[int, ...] = (443,)
    max_redirects: int = 3
    minimum_tls_version: TlsVersion = TlsVersion.TLS_1_2
    require_hostname_verification: bool = True

    def __post_init__(self) -> None:
        require_token(self.policy_id, field="endpoint_policy_id")
        if not isinstance(self.allowed_hosts, tuple) or not self.allowed_hosts:
            raise AdapterContractError("allowed hosts must be a non-empty tuple")
        hosts = tuple(canonical_host(host) for host in self.allowed_hosts)
        if hosts != tuple(sorted(set(hosts))):
            raise AdapterContractError("allowed hosts must be sorted and unique")
        if (
            not isinstance(self.allowed_ports, tuple)
            or not self.allowed_ports
            or any(
                isinstance(port, bool)
                or not isinstance(port, int)
                or not 1 <= port <= 65535
                for port in self.allowed_ports
            )
            or self.allowed_ports != tuple(sorted(set(self.allowed_ports)))
        ):
            raise AdapterContractError(
                "allowed ports must be sorted unique integers"
            )
        if (
            isinstance(self.max_redirects, bool)
            or not isinstance(self.max_redirects, int)
            or not 0 <= self.max_redirects <= 10
        ):
            raise AdapterContractError("redirect bound must be between 0 and 10")
        if not isinstance(self.minimum_tls_version, TlsVersion):
            raise AdapterContractError("minimum TLS version must be typed")
        if self.require_hostname_verification is not True:
            raise AdapterContractError("hostname verification cannot be disabled")

    def canonical_value(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "allowed_hosts": list(self.allowed_hosts),
            "allowed_ports": list(self.allowed_ports),
            "max_redirects": self.max_redirects,
            "minimum_tls_version": self.minimum_tls_version.value,
            "require_hostname_verification": self.require_hostname_verification,
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class ShapeField:
    name: str
    path: tuple[str, ...]
    required: bool
    maximum_bytes: int = 16_384

    def __post_init__(self) -> None:
        require_token(self.name, field="shape_field_name")
        if not isinstance(self.path, tuple) or not self.path:
            raise AdapterContractError(
                "shape field path must be a non-empty tuple"
            )
        for part in self.path:
            bounded_text(part, field="shape_field_path", maximum_bytes=128)
        if not isinstance(self.required, bool):
            raise AdapterContractError(
                "shape field required flag must be boolean"
            )
        if (
            isinstance(self.maximum_bytes, bool)
            or not isinstance(self.maximum_bytes, int)
            or not 1 <= self.maximum_bytes <= 4 * 1024 * 1024
        ):
            raise AdapterContractError("shape field byte bound is invalid")

    def canonical_value(self) -> dict[str, object]:
        return {
            "name": self.name,
            "path": list(self.path),
            "required": self.required,
            "maximum_bytes": self.maximum_bytes,
        }


def _paths_overlap(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    shortest = min(len(left), len(right))
    return left[:shortest] == right[:shortest]


@dataclass(frozen=True, slots=True)
class SourceShapeContract:
    shape_id: str
    kind: AdapterKind
    items_path: tuple[str, ...]
    fields: tuple[ShapeField, ...]
    identity_fields: tuple[str, ...]
    allow_additional_fields: bool = True
    singleton_identity: str | None = None

    def __post_init__(self) -> None:
        require_token(self.shape_id, field="source_shape_id")
        if not isinstance(self.kind, AdapterKind):
            raise AdapterContractError("shape adapter kind must be typed")
        if not isinstance(self.items_path, tuple):
            raise AdapterContractError("items path must be an immutable tuple")
        for part in self.items_path:
            bounded_text(part, field="items_path", maximum_bytes=128)
        if not isinstance(self.fields, tuple) or not self.fields:
            raise AdapterContractError("shape fields must be a non-empty tuple")
        if any(not isinstance(item, ShapeField) for item in self.fields):
            raise AdapterContractError("shape fields must be typed")
        if self.fields != tuple(sorted(self.fields, key=lambda item: item.name)):
            raise AdapterContractError("shape fields must be sorted by name")
        names = tuple(item.name for item in self.fields)
        if len(names) != len(set(names)):
            raise AdapterContractError("shape field names must be unique")
        paths = tuple(item.path for item in self.fields)
        if len(paths) != len(set(paths)):
            raise AdapterContractError("shape field paths must be unique")

        identities = sorted_unique_text(
            self.identity_fields,
            field="identity_fields",
            maximum_items=16,
            maximum_item_bytes=128,
            allow_empty=True,
        )
        by_name = {item.name: item for item in self.fields}
        if not set(identities) <= set(names):
            raise AdapterContractError(
                "identity fields must resolve to shape fields"
            )
        if any(not by_name[name].required for name in identities):
            raise AdapterContractError("identity fields must be required")
        identity_paths = tuple(by_name[name].path for name in identities)
        for index, path in enumerate(identity_paths):
            if any(
                _paths_overlap(path, other)
                for other in identity_paths[index + 1 :]
            ):
                raise AdapterContractError(
                    "identity field paths cannot overlap"
                )

        if self.singleton_identity is None:
            if not identities:
                raise AdapterContractError(
                    "non-singleton shape requires identity fields"
                )
        else:
            require_token(
                self.singleton_identity,
                field="shape_singleton_identity",
            )
            if identities:
                raise AdapterContractError(
                    "singleton shape cannot also use item identity fields"
                )
        if (
            self.kind is AdapterKind.MAINTAINED_DOCUMENT
            and self.singleton_identity is None
        ):
            raise AdapterContractError(
                "maintained-document shape requires stable singleton identity"
            )
        if not isinstance(self.allow_additional_fields, bool):
            raise AdapterContractError(
                "additional-field flag must be boolean"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "shape_id": self.shape_id,
            "kind": self.kind.value,
            "items_path": list(self.items_path),
            "fields": [item.canonical_value() for item in self.fields],
            "identity_fields": list(self.identity_fields),
            "allow_additional_fields": self.allow_additional_fields,
            "singleton_identity": self.singleton_identity,
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class Header:
    name: str
    value: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.name, str)
            or self.name != self.name.lower()
            or _HEADER.fullmatch(self.name) is None
        ):
            raise AdapterContractError(
                "header name must be canonical lowercase text"
            )
        bounded_text(
            self.value,
            field="header_value",
            maximum_bytes=8192,
            allow_empty=True,
        )
        if "\r" in self.value or "\n" in self.value:
            raise AdapterContractError(
                "header values cannot contain line breaks"
            )

    def canonical_value(self) -> dict[str, str]:
        return {"name": self.name, "value": self.value}


def sorted_headers(values: Iterable[Header]) -> tuple[Header, ...]:
    if not isinstance(values, tuple) or any(
        not isinstance(item, Header) for item in values
    ):
        raise AdapterContractError(
            "headers must be an immutable typed tuple"
        )
    result = tuple(sorted(values, key=lambda item: item.name))
    if len(result) != len({item.name for item in result}):
        raise AdapterContractError(
            "fixture headers must have unique names"
        )
    return result


__all__ = [
    "AdapterContractError",
    "AdapterExecutionProfile",
    "AdapterKind",
    "AdapterRequestId",
    "AdapterVersionRef",
    "BodyEncoding",
    "BodyLimits",
    "CaptureId",
    "Completeness",
    "EndpointPolicy",
    "Header",
    "ObservationProposalId",
    "ObservationProposalOutcome",
    "ParserLimits",
    "ParserResultId",
    "QuarantineRecommendation",
    "RETAINED_RESPONSE_HEADER_NAMES",
    "ShapeField",
    "SourceShapeContract",
    "TimeoutLimits",
    "TlsVersion",
    "TransportAttemptId",
    "TransportFailureKind",
    "bounded_text",
    "canonical_host",
    "require_token",
    "sorted_headers",
    "sorted_unique_text",
]
