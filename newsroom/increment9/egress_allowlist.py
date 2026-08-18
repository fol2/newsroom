"""Per-request default-deny egress admitter for Increment 9Q-6.

Injected fixture host map only. No network, TLS handshake, DNS pinning or
socket. Admission returns an Egress Receipt — destination class, host, policy
digest and bounds — never secret bytes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.increment9.deployment import (
    EXPECTED_CREDENTIAL_CLASSES,
    EXPECTED_EGRESS_DESTINATIONS,
    PROHIBITED_CREDENTIAL_CLASSES,
    READINESS_ONLY_DESTINATIONS,
    DeploymentError,
    EgressPolicy,
    admit_readiness_egress,
)
from newsroom.increment9.plan import INCREMENT_9_SHADOW_PLAN
from newsroom.increment9.shadow_contracts import ShadowAccessBoundary

CONTEXT_SHADOW = "shadow"
CONTEXT_READINESS = "readiness"
ADMITTED_CONTEXTS = frozenset({CONTEXT_SHADOW, CONTEXT_READINESS})
DESTINATION_INVENTORY = tuple(
    sorted((*EXPECTED_EGRESS_DESTINATIONS, *READINESS_ONLY_DESTINATIONS))
)
FIXTURE_HOST_MAP: dict[str, str] = {
    "::1": "LOCAL_NEO4J",
    "127.0.0.1": "LOCAL_NEO4J",
    "anthropic.fixture.invalid": "ANTHROPIC_AGENT_SDK",
    "filesystem.fixture.invalid": "LOCAL_FILESYSTEM",
    "gemini.fixture.invalid": "GOOGLE_GEMINI_API",
    "localhost": "LOCAL_NEO4J",
    "newsroom-target.fixture.invalid": "INTEGRATED_NEWSROOM_TARGET",
    "openai-codex.fixture.invalid": "OPENAI_CODEX",
    "openai-embeddings.fixture.invalid": "OPENAI_EMBEDDINGS",
    "review-research.fixture.invalid": "APPROVED_REVIEW_RESEARCH",
    "sources.fixture.invalid": "TEN_APPROVED_SOURCE_ENDPOINTS",
    "xai.fixture.invalid": "XAI_GROK_BUILD",
}
FIXTURE_PRINCIPAL_DIGEST = "sha256:" + "e" * 64
NAMESAKE_A2_PROBES = ("EGRESS_ALLOWLIST_BOUNDED", "EGRESS_DEFAULT_DENY")
_SECRET_KEYS = frozenset(
    {"api_key", "credential_value", "password", "secret", "secret_bytes"}
)
_RECEIPT_FIELDS = frozenset(
    {"bounds", "destination_class", "host", "policy_digest"}
)
_BOUNDS_FIELDS = frozenset(
    {
        "redirects_max",
        "response_body_bytes_max",
        "source_requests_per_day_max",
        "timeout_seconds",
        "tls_minimum",
    }
)
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/\-]{0,255}\Z")
_HOST = re.compile(r"[A-Za-z0-9:][A-Za-z0-9._:/\-]{0,255}\Z")
_POLICY = EgressPolicy()


class EgressAllowlistError(ValueError):
    """Egress admission, inventory bind or receipt check failed closed."""


def _token(value: object, field: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise EgressAllowlistError(f"{field} token is malformed")
    encoded = value.encode("utf-8", errors="strict")
    pattern = _HOST if field == "host" else _TOKEN
    if len(encoded) > 256 or pattern.fullmatch(value) is None:
        raise EgressAllowlistError(f"{field} token is malformed")
    return value


def _digest(value: object, field: str) -> str:
    if type(value) is not str:
        raise EgressAllowlistError(f"{field} digest differs")
    try:
        return validate_sha256_digest(value, field=field)
    except (CanonicalizationError, TypeError, ValueError) as exc:
        raise EgressAllowlistError(f"{field} digest differs") from exc


def _od012_required() -> set[str]:
    decisions = {
        item.decision_id: item.selection
        for item in INCREMENT_9_SHADOW_PLAN.owner_decisions
    }
    required = decisions["OD-012"]["egress_destination_allowlist"]["required"]
    return set(required)


def policy_digest() -> str:
    """Canonical digest of the frozen OD-012 EgressPolicy contract."""

    return digest_bytes(canonical_json_bytes(_POLICY.primitive()))


def inventory_digest() -> str:
    """Canonical digest of the OD-012 eight-plus-two destination inventory."""

    return digest_bytes(
        canonical_json_bytes({"destination_inventory": list(DESTINATION_INVENTORY)})
    )


def bind_inventory(destinations: tuple[str, ...]) -> tuple[str, ...]:
    """Refuse inventory drift against OD-012 eight-plus-two."""

    if type(destinations) is not tuple:
        raise EgressAllowlistError("destination inventory type differs")
    if destinations != tuple(sorted(set(destinations))) or not destinations:
        raise EgressAllowlistError(
            "destination inventory is not unique and sorted"
        )
    if destinations != DESTINATION_INVENTORY:
        raise EgressAllowlistError("destination inventory differs from OD-012")
    if set(EXPECTED_EGRESS_DESTINATIONS) != _od012_required():
        raise EgressAllowlistError("configured destinations differ from OD-012")
    return destinations


def bind_host_map(host_map: Mapping[str, str]) -> dict[str, str]:
    """Refuse a host map that does not carry the real OD-012 class inventory."""

    if not isinstance(host_map, Mapping) or not host_map:
        raise EgressAllowlistError("host map is required")
    bound: dict[str, str] = {}
    for host, destination in host_map.items():
        key = _token(host, "host")
        if key != key.lower():
            raise EgressAllowlistError("host token is malformed")
        if key in bound:
            raise EgressAllowlistError("host map contains a duplicate host")
        bound[key] = _token(destination, "destination_class")
    from newsroom.increment9.proving import ALLOWED_HOSTS

    if frozenset(bound) == ALLOWED_HOSTS:
        raise EgressAllowlistError(
            "proving allowlist cannot satisfy this First I/O Gate"
        )
    classes = frozenset(bound.values())
    if classes != frozenset(DESTINATION_INVENTORY):
        raise EgressAllowlistError("host map inventory differs from OD-012")
    return bound


def fixture_access_boundary() -> ShadowAccessBoundary:
    digest = policy_digest()
    return ShadowAccessBoundary(
        purpose_identity="increment9-evaluation-only",
        principal_identity_digest=FIXTURE_PRINCIPAL_DIGEST,
        permitted_credential_classes=EXPECTED_CREDENTIAL_CLASSES,
        prohibited_credential_classes=PROHIBITED_CREDENTIAL_CLASSES,
        egress_policy_digest=digest,
        artefact_policy_digest=FIXTURE_PRINCIPAL_DIGEST,
    )


@dataclass(frozen=True, slots=True)
class EgressBounds:
    tls_minimum: str
    redirects_max: int
    response_body_bytes_max: int
    timeout_seconds: int
    source_requests_per_day_max: int

    def primitive(self) -> dict[str, str | int]:
        return {
            "redirects_max": self.redirects_max,
            "response_body_bytes_max": self.response_body_bytes_max,
            "source_requests_per_day_max": self.source_requests_per_day_max,
            "timeout_seconds": self.timeout_seconds,
            "tls_minimum": self.tls_minimum,
        }


def _policy_bounds() -> EgressBounds:
    return EgressBounds(
        tls_minimum=_POLICY.tls_minimum,
        redirects_max=_POLICY.redirects_max,
        response_body_bytes_max=_POLICY.response_body_bytes_max,
        timeout_seconds=_POLICY.timeout_seconds,
        source_requests_per_day_max=_POLICY.source_requests_per_day_max,
    )


@dataclass(frozen=True, slots=True)
class EgressReceipt:
    """Metadata-only admission record. Never secret bytes."""

    destination_class: str
    host: str
    policy_digest: str
    bounds: EgressBounds

    def primitive(self) -> dict[str, object]:
        return {
            "bounds": self.bounds.primitive(),
            "destination_class": self.destination_class,
            "host": self.host,
            "policy_digest": self.policy_digest,
        }

    @property
    def digest(self) -> str:
        return digest_bytes(canonical_json_bytes(self.primitive()))


def receipt_from_primitive(value: object) -> EgressReceipt:
    """Load an Egress Receipt, refusing secret bytes or missing fields."""

    if type(value) is not dict:
        raise EgressAllowlistError("egress receipt is not an object")
    if _SECRET_KEYS & set(value):
        raise EgressAllowlistError("secret bytes are prohibited in an egress receipt")
    if set(value) != _RECEIPT_FIELDS:
        raise EgressAllowlistError("egress receipt fields differ")
    bounds = value["bounds"]
    if type(bounds) is not dict:
        raise EgressAllowlistError("egress receipt fields differ")
    if _SECRET_KEYS & set(bounds):
        raise EgressAllowlistError("secret bytes are prohibited in an egress receipt")
    if set(bounds) != _BOUNDS_FIELDS:
        raise EgressAllowlistError("egress receipt fields differ")
    receipt = EgressReceipt(
        destination_class=_token(value["destination_class"], "destination_class"),
        host=_token(value["host"], "host"),
        policy_digest=_digest(value["policy_digest"], "policy_digest"),
        bounds=EgressBounds(
            tls_minimum=_token(bounds["tls_minimum"], "tls_minimum"),
            redirects_max=bounds["redirects_max"],  # type: ignore[arg-type]
            response_body_bytes_max=bounds["response_body_bytes_max"],  # type: ignore[arg-type]
            timeout_seconds=bounds["timeout_seconds"],  # type: ignore[arg-type]
            source_requests_per_day_max=bounds["source_requests_per_day_max"],  # type: ignore[arg-type]
        ),
    )
    if set(receipt.primitive()) != _RECEIPT_FIELDS:
        raise EgressAllowlistError("secret bytes are prohibited in an egress receipt")
    return receipt


@dataclass(frozen=True, slots=True)
class EgressRequest:
    context: str
    url: str
    policy_digest: str
    destination_inventory: tuple[str, ...]
    tls_minimum: str = "TLS_1_3"
    redirects: int = 0
    body_bytes: int = 0
    timeout_seconds: int = 30
    source_id: str = "FIXTURE_SOURCE"
    day: str = "2026-08-17"
    destination_class: str | None = None


def fixture_request(**changes: object) -> EgressRequest:
    values: dict[str, object] = {
        "context": CONTEXT_SHADOW,
        "url": "https://anthropic.fixture.invalid/v1",
        "policy_digest": policy_digest(),
        "destination_inventory": DESTINATION_INVENTORY,
        "tls_minimum": "TLS_1_3",
        "redirects": 0,
        "body_bytes": 0,
        "timeout_seconds": 30,
        "source_id": "FIXTURE_SOURCE",
        "day": "2026-08-17",
        "destination_class": None,
    }
    values.update(changes)
    return EgressRequest(**values)  # type: ignore[arg-type]


def _parse_url(url: object) -> tuple[str, str, str]:
    if type(url) is not str or not url or url != url.strip():
        raise EgressAllowlistError("url token is malformed")
    parsed = urlsplit(url)
    if parsed.username is not None or parsed.password is not None:
        raise EgressAllowlistError("url carrying credentials is malformed")
    host = parsed.hostname or ""
    if not host:
        raise EgressAllowlistError("host token is malformed")
    scheme = _token(parsed.scheme, "scheme")
    host = _token(host, "host")
    if host != host.lower():
        raise EgressAllowlistError("host token is malformed")
    return scheme, host, url


class EgressAdmitter:
    """Per-request default-deny admitter bound to one policy digest and host map."""

    def __init__(
        self,
        *,
        boundary: ShadowAccessBoundary | None = None,
        host_map: Mapping[str, str] | None = None,
    ) -> None:
        bind_inventory(DESTINATION_INVENTORY)
        self._host_map = bind_host_map(
            host_map if host_map is not None else FIXTURE_HOST_MAP
        )
        active = boundary if boundary is not None else fixture_access_boundary()
        expected = policy_digest()
        if active.egress_policy_digest != expected:
            raise EgressAllowlistError("egress policy digest differs")
        self._policy_digest = expected
        self._counts: dict[tuple[str, str], int] = {}

    def admit(self, request: EgressRequest) -> EgressReceipt:
        if type(request) is not EgressRequest:
            raise EgressAllowlistError("request token is malformed")
        context = _token(request.context, "context")
        if context not in ADMITTED_CONTEXTS:
            raise EgressAllowlistError("context token is malformed")
        source_id = _token(request.source_id, "source_id")
        day = _token(request.day, "day")
        tls_minimum = _token(request.tls_minimum, "tls_minimum")
        for field in ("redirects", "body_bytes", "timeout_seconds"):
            value = getattr(request, field)
            if type(value) is not int or value < 0:
                raise EgressAllowlistError(f"{field} token is malformed")
        scheme, host, url = _parse_url(request.url)
        bind_inventory(request.destination_inventory)
        presented = _digest(request.policy_digest, "policy_digest")
        if presented != self._policy_digest:
            raise EgressAllowlistError("egress policy digest differs")
        if host not in self._host_map:
            raise EgressAllowlistError("host is default-denied")
        resolved = self._host_map[host]
        if resolved not in DESTINATION_INVENTORY:
            raise EgressAllowlistError("unknown destination class")
        if request.destination_class is not None:
            claimed = _token(request.destination_class, "destination_class")
            if claimed not in DESTINATION_INVENTORY:
                raise EgressAllowlistError("unknown destination class")
            if claimed != resolved:
                raise EgressAllowlistError("unknown destination class")
        readiness_class = resolved in READINESS_ONLY_DESTINATIONS
        if context == CONTEXT_SHADOW and readiness_class:
            raise EgressAllowlistError("context crossing is refused")
        if context == CONTEXT_READINESS and not readiness_class:
            raise EgressAllowlistError("context crossing is refused")
        if context == CONTEXT_SHADOW and scheme != "https":
            raise EgressAllowlistError("egress request bounds differ")
        if tls_minimum != _POLICY.tls_minimum:
            raise EgressAllowlistError("egress request bounds differ")
        if request.redirects != _POLICY.redirects_max:
            raise EgressAllowlistError("egress request bounds differ")
        if request.body_bytes > _POLICY.response_body_bytes_max:
            raise EgressAllowlistError("egress request bounds differ")
        if request.timeout_seconds > _POLICY.timeout_seconds:
            raise EgressAllowlistError("egress request bounds differ")
        if context == CONTEXT_READINESS:
            try:
                admitted = admit_readiness_egress(url)
            except DeploymentError as exc:
                raise EgressAllowlistError(
                    "readiness path disagrees with admit_readiness_egress"
                ) from exc
            if admitted != resolved:
                raise EgressAllowlistError(
                    "readiness path disagrees with admit_readiness_egress"
                )
        key = (source_id, day)
        if self._counts.get(key, 0) >= _POLICY.source_requests_per_day_max:
            raise EgressAllowlistError("rate exceeded")
        receipt = EgressReceipt(
            destination_class=resolved,
            host=host,
            policy_digest=self._policy_digest,
            bounds=_policy_bounds(),
        )
        if set(receipt.primitive()) != _RECEIPT_FIELDS:
            raise EgressAllowlistError("secret bytes are prohibited in an egress receipt")
        if _SECRET_KEYS & set(receipt.primitive()):
            raise EgressAllowlistError("secret bytes are prohibited in an egress receipt")
        self._counts[key] = self._counts.get(key, 0) + 1
        return receipt


def bound_admitter(
    *,
    boundary: ShadowAccessBoundary | None = None,
    host_map: Mapping[str, str] | None = None,
) -> EgressAdmitter:
    return EgressAdmitter(boundary=boundary, host_map=host_map)


def admit(
    request: EgressRequest, *, admitter: EgressAdmitter | None = None
) -> EgressReceipt:
    """Admit one request or refuse fail-closed. Never returns secret bytes."""

    active = admitter if admitter is not None else bound_admitter()
    return active.admit(request)


def refuse_namesake_satisfaction() -> None:
    """Refuse the 9P proving-gate namesake as this First I/O Gate."""

    from newsroom.increment9.proving import assess as proving_assess

    proving_assess(
        run_id="fixture-run", kill_switch=False, no_emergency_stop=True
    )
    raise EgressAllowlistError(
        "proving EGRESS_ALLOWLIST_ENFORCED cannot satisfy this First I/O Gate"
    )


def bind_campaign_egress_allowlist(
    destinations: tuple[str, ...] | None = None,
) -> str:
    """Campaign EGRESS_ALLOWLIST_ENFORCED bind: the admitter, not a bare gate name.

    Proving-gate host lists and 9A2 probe names cannot PASS.
    """

    bind_inventory(
        destinations if destinations is not None else DESTINATION_INVENTORY
    )
    receipt = bound_admitter().admit(fixture_request())
    if set(receipt.primitive()) != _RECEIPT_FIELDS:
        raise EgressAllowlistError("secret bytes are prohibited in an egress receipt")
    return receipt.policy_digest
