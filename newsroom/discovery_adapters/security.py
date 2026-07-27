from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import SplitResult, unquote_to_bytes, urlsplit, urlunsplit

from .models import (
    DnsEvidence,
    RedirectEvidence,
    RedirectHop,
    TlsEvidence,
)
from .types import AdapterContractError, EndpointPolicy, canonical_host


_HEX = frozenset("0123456789ABCDEF")


def _validate_uri_component(
    value: str,
    *,
    field: str,
    reject_dot_segments: bool = False,
) -> None:
    try:
        value.encode("ascii", errors="strict")
    except UnicodeError as exc:
        raise AdapterContractError(
            f"{field} must use ASCII with percent-encoded UTF-8"
        ) from exc
    index = 0
    while index < len(value):
        character = value[index]
        code = ord(character)
        if code <= 0x20 or code == 0x7F or character == "\\":
            raise AdapterContractError(
                f"{field} contains raw whitespace, control or backslash"
            )
        if character != "%":
            index += 1
            continue
        if (
            index + 2 >= len(value)
            or value[index + 1] not in _HEX
            or value[index + 2] not in _HEX
        ):
            raise AdapterContractError(
                f"{field} percent encoding is not canonical uppercase hex"
            )
        decoded = int(value[index + 1 : index + 3], 16)
        if decoded < 0x20 or decoded == 0x7F or decoded == 0x5C:
            raise AdapterContractError(
                f"{field} percent encoding contains a prohibited octet"
            )
        index += 3
    if reject_dot_segments:
        for segment in value.split("/"):
            if unquote_to_bytes(segment) in {b".", b".."}:
                raise AdapterContractError(
                    "endpoint path contains a dot segment"
                )


def _split_endpoint(url: str) -> SplitResult:
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise AdapterContractError("endpoint URL is invalid") from exc
    if parsed.scheme != "https":
        raise AdapterContractError("only HTTPS endpoints are permitted")
    if parsed.username is not None or parsed.password is not None:
        raise AdapterContractError("endpoint user-info is prohibited")
    if parsed.fragment:
        raise AdapterContractError("endpoint fragments are prohibited")
    if not parsed.hostname:
        raise AdapterContractError("endpoint hostname is required")
    host = parsed.hostname.lower()
    canonical_host(host)
    try:
        ip_address(host)
    except ValueError:
        pass
    else:
        raise AdapterContractError("endpoint IP literals are prohibited")
    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise AdapterContractError("endpoint port is invalid") from exc
    netloc = host if port == 443 else f"{host}:{port}"
    path = parsed.path or "/"
    _validate_uri_component(
        path,
        field="endpoint path",
        reject_dot_segments=True,
    )
    _validate_uri_component(parsed.query, field="endpoint query")
    normalized = SplitResult("https", netloc, path, parsed.query, "")
    if urlunsplit(normalized) != url:
        raise AdapterContractError(
            "endpoint URL must use canonical HTTPS form"
        )
    return normalized


def validate_endpoint(url: str, policy: EndpointPolicy) -> SplitResult:
    if not isinstance(policy, EndpointPolicy):
        raise AdapterContractError("endpoint policy must be typed")
    parsed = _split_endpoint(url)
    host = parsed.hostname
    assert host is not None
    if host not in policy.allowed_hosts:
        raise AdapterContractError(
            "endpoint host is outside the allow-list"
        )
    port = parsed.port or 443
    if port not in policy.allowed_ports:
        raise AdapterContractError(
            "endpoint port is outside the allow-list"
        )
    return parsed


def validate_dns_evidence(
    url: str,
    policy: EndpointPolicy,
    evidence: DnsEvidence,
) -> None:
    parsed = validate_endpoint(url, policy)
    host = parsed.hostname
    assert host is not None
    if not isinstance(evidence, DnsEvidence):
        raise AdapterContractError("DNS evidence must be typed")
    if evidence.host != host:
        raise AdapterContractError(
            "DNS evidence host differs from endpoint"
        )
    for value in evidence.addresses:
        try:
            address = ip_address(value)
        except ValueError as exc:
            raise AdapterContractError(
                "DNS evidence contains an invalid address"
            ) from exc
        if value != value.lower() or str(address) != value:
            raise AdapterContractError(
                "DNS evidence address is not canonical"
            )
        if (
            not address.is_global
            or address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            raise AdapterContractError(
                "DNS evidence contains a non-public address"
            )


def validate_tls_evidence(
    url: str,
    policy: EndpointPolicy,
    evidence: TlsEvidence,
) -> None:
    parsed = validate_endpoint(url, policy)
    host = parsed.hostname
    assert host is not None
    if not isinstance(evidence, TlsEvidence):
        raise AdapterContractError("TLS evidence must be typed")
    if evidence.host != host:
        raise AdapterContractError(
            "TLS evidence host differs from endpoint"
        )
    if not evidence.certificate_valid:
        raise AdapterContractError("TLS certificate validation failed")
    if not evidence.hostname_verified:
        raise AdapterContractError("TLS hostname verification failed")
    if evidence.negotiated_version.rank < policy.minimum_tls_version.rank:
        raise AdapterContractError(
            "negotiated TLS version is below policy"
        )


def validate_redirects(
    initial_url: str,
    redirects: tuple[RedirectHop, ...],
    policy: EndpointPolicy,
) -> str:
    validate_endpoint(initial_url, policy)
    if not isinstance(redirects, tuple):
        raise AdapterContractError(
            "redirect chain must be an immutable tuple"
        )
    if len(redirects) > policy.max_redirects:
        raise AdapterContractError(
            "redirect chain exceeds the policy bound"
        )
    current = initial_url
    seen = {initial_url}
    for hop in redirects:
        if not isinstance(hop, RedirectHop):
            raise AdapterContractError(
                "redirect chain entries must be typed"
            )
        if hop.from_url != current:
            raise AdapterContractError(
                "redirect chain is not contiguous"
            )
        validate_endpoint(hop.from_url, policy)
        validate_endpoint(hop.to_url, policy)
        if hop.to_url in seen:
            raise AdapterContractError(
                "redirect chain contains a loop"
            )
        seen.add(hop.to_url)
        current = hop.to_url
    return current


def validate_endpoint_evidence(
    *,
    initial_url: str,
    policy: EndpointPolicy,
    dns: DnsEvidence,
    tls: TlsEvidence,
    redirects: tuple[RedirectHop, ...],
    redirect_evidence: tuple[RedirectEvidence, ...] = (),
) -> str:
    final_url = validate_redirects(initial_url, redirects, policy)
    validate_dns_evidence(initial_url, policy, dns)
    validate_tls_evidence(initial_url, policy, tls)
    if not isinstance(redirect_evidence, tuple) or any(
        not isinstance(item, RedirectEvidence)
        for item in redirect_evidence
    ):
        raise AdapterContractError(
            "redirect endpoint evidence must be a typed tuple"
        )
    if len(redirect_evidence) != len(redirects):
        raise AdapterContractError(
            "each redirect target requires exact DNS and TLS evidence"
        )
    for hop, evidence in zip(
        redirects,
        redirect_evidence,
        strict=True,
    ):
        if evidence.url != hop.to_url:
            raise AdapterContractError(
                "redirect evidence URL differs from redirect target"
            )
        validate_dns_evidence(hop.to_url, policy, evidence.dns_evidence)
        validate_tls_evidence(hop.to_url, policy, evidence.tls_evidence)
    return final_url


__all__ = [
    "validate_dns_evidence",
    "validate_endpoint",
    "validate_endpoint_evidence",
    "validate_redirects",
    "validate_tls_evidence",
]
