"""Provider Terms admitter for Increment 9Q-8: fixture inventory, no live ToS fetch.

HMAC-SHA256 fixture-signed records only. Currentness is a terms-digest bind plus
an injected issued_at/expires_at window. PASS on exactly one path: live route
or named no-provider route. Crossing the paths fails closed.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Mapping

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.increment9.deployment import (
    EXPECTED_EGRESS_DESTINATIONS,
    READINESS_ONLY_DESTINATIONS,
)

GATE_ID = "PROVIDER_TERMS_CURRENT"
LIVE_PATH = "LIVE_ROUTE"
NO_PROVIDER_PATH = "NO_PROVIDER_ROUTE"
LIVE_ROUTE_ID = "live-shadow"
NO_PROVIDER_ROUTE_ID = "no-provider-sources"
NON_PROVIDER_EGRESS = frozenset(
    {"INTEGRATED_NEWSROOM_TARGET", "TEN_APPROVED_SOURCE_ENDPOINTS"}
)
PROVIDER_CLASSES = tuple(
    dest for dest in EXPECTED_EGRESS_DESTINATIONS if dest not in NON_PROVIDER_EGRESS
)
KNOWN_DESTINATIONS = frozenset(EXPECTED_EGRESS_DESTINATIONS) | frozenset(
    READINESS_ONLY_DESTINATIONS
)
FIXTURE_HMAC_KEY = b"newsroom.increment9.provider-terms.fixture-hmac-key"
FIXTURE_NOW = "2026-08-18T12:00:00.000000Z"
FIXTURE_ISSUED_AT = "2026-08-18T00:00:00.000000Z"
FIXTURE_EXPIRES_AT = "2026-08-19T00:00:00.000000Z"
FIXTURE_TERMS_URLS = {
    "ANTHROPIC_AGENT_SDK": "https://terms.anthropic.fixture.invalid/tos",
    "APPROVED_REVIEW_RESEARCH": "https://terms.review-research.fixture.invalid/tos",
    "GOOGLE_GEMINI_API": "https://terms.gemini.fixture.invalid/tos",
    "OPENAI_CODEX": "https://terms.openai-codex.fixture.invalid/tos",
    "OPENAI_EMBEDDINGS": "https://terms.openai-embeddings.fixture.invalid/tos",
    "XAI_GROK_BUILD": "https://terms.xai.fixture.invalid/tos",
}
_INVENTORY_FIELDS = frozenset(
    {"bound_terms", "now", "provider_call_count", "routes"}
)
_BOUND_FIELDS = frozenset({"terms_digest", "terms_url"})
_ROUTE_FIELDS = frozenset(
    {"admitted_destinations", "declaration", "terms_records"}
)
_TERMS_FIELDS = frozenset(
    {
        "expires_at",
        "gate_id",
        "issued_at",
        "provider_class",
        "seal",
        "terms_digest",
        "terms_url",
    }
)
_DECLARATION_FIELDS = frozenset(
    {
        "admitted_destinations",
        "expires_at",
        "issued_at",
        "provider_classes_admitted",
        "route_id",
        "seal",
    }
)
_TIMESTAMP = re.compile(
    r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{6}Z\Z"
)
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/\-]{0,255}\Z")


class ProviderTermsError(ValueError):
    """Provider-terms bind, seal or admission failed closed."""


def _token(value: object, field: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ProviderTermsError(f"{field} token is malformed")
    encoded = value.encode("utf-8", errors="strict")
    if len(encoded) > 256 or _TOKEN.fullmatch(value) is None:
        raise ProviderTermsError(f"{field} token is malformed")
    return value


def _digest(value: object, field: str) -> str:
    if type(value) is not str:
        raise ProviderTermsError(f"{field} digest differs")
    try:
        return validate_sha256_digest(value, field=field)
    except (CanonicalizationError, TypeError, ValueError) as exc:
        raise ProviderTermsError(f"{field} digest differs") from exc


def _timestamp(value: object, field: str) -> str:
    if type(value) is not str or _TIMESTAMP.fullmatch(value) is None:
        raise ProviderTermsError(f"{field} token is malformed")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ProviderTermsError(f"{field} token is malformed") from exc
    return value


def _instant(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def _destinations(value: object) -> tuple[str, ...]:
    if type(value) not in (tuple, list):
        raise ProviderTermsError("record is malformed")
    tokens = tuple(_token(item, "destination") for item in value)
    if tokens != tuple(sorted(set(tokens))):
        raise ProviderTermsError("record is malformed")
    unknown = [item for item in tokens if item not in KNOWN_DESTINATIONS]
    if unknown:
        raise ProviderTermsError("unexpected class")
    return tokens


def _seal(unsigned: Mapping[str, object]) -> str:
    mac = hmac.new(
        FIXTURE_HMAC_KEY, canonical_json_bytes(dict(unsigned)), hashlib.sha256
    )
    return f"hmac-sha256:{mac.hexdigest()}"


def _verify_seal(record: Mapping[str, object]) -> None:
    presented = record.get("seal")
    if type(presented) is not str or not presented.startswith("hmac-sha256:"):
        raise ProviderTermsError("seal is invalid")
    unsigned = {key: record[key] for key in record if key != "seal"}
    expected = _seal(unsigned)
    if not hmac.compare_digest(expected, presented):
        raise ProviderTermsError("seal is invalid")


def _window(issued_at: str, expires_at: str, now: str) -> None:
    if _instant(issued_at) > _instant(now) or _instant(expires_at) <= _instant(now):
        raise ProviderTermsError("record is expired or future-dated")


def _providers(destinations: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(cls for cls in PROVIDER_CLASSES if cls in destinations)


def terms_digest_for(provider_class: str) -> str:
    url = FIXTURE_TERMS_URLS[provider_class]
    return digest_bytes(
        canonical_json_bytes({"provider_class": provider_class, "terms_url": url})
    )


def bound_terms_identity() -> dict[str, dict[str, str]]:
    return {
        cls: {
            "terms_digest": terms_digest_for(cls),
            "terms_url": FIXTURE_TERMS_URLS[cls],
        }
        for cls in PROVIDER_CLASSES
    }


def fixture_terms_record(provider_class: str, **changes: object) -> dict[str, object]:
    if provider_class in FIXTURE_TERMS_URLS:
        url = FIXTURE_TERMS_URLS[provider_class]
        digest = terms_digest_for(provider_class)
    else:
        url = "https://terms.unexpected.fixture.invalid/tos"
        digest = digest_bytes(
            canonical_json_bytes(
                {"provider_class": provider_class, "terms_url": url}
            )
        )
    unsigned: dict[str, object] = {
        "expires_at": FIXTURE_EXPIRES_AT,
        "gate_id": GATE_ID,
        "issued_at": FIXTURE_ISSUED_AT,
        "provider_class": provider_class,
        "terms_digest": digest,
        "terms_url": url,
    }
    for key, value in changes.items():
        if key != "seal":
            unsigned[key] = value
    record = dict(unsigned)
    record["seal"] = changes["seal"] if "seal" in changes else _seal(unsigned)
    return record


def fixture_declaration(
    route_id: str,
    admitted_destinations: tuple[str, ...] | list[str],
    **changes: object,
) -> dict[str, object]:
    unsigned: dict[str, object] = {
        "admitted_destinations": list(admitted_destinations),
        "expires_at": FIXTURE_EXPIRES_AT,
        "issued_at": FIXTURE_ISSUED_AT,
        "provider_classes_admitted": [],
        "route_id": route_id,
    }
    for key, value in changes.items():
        if key != "seal":
            unsigned[key] = value
    record = dict(unsigned)
    record["seal"] = changes["seal"] if "seal" in changes else _seal(unsigned)
    return record


def live_route_destinations() -> tuple[str, ...]:
    return tuple(
        dest
        for dest in EXPECTED_EGRESS_DESTINATIONS
        if dest != "TEN_APPROVED_SOURCE_ENDPOINTS"
    )


def no_provider_destinations() -> tuple[str, ...]:
    return tuple(
        sorted((*READINESS_ONLY_DESTINATIONS, "TEN_APPROVED_SOURCE_ENDPOINTS"))
    )


def fixture_inventory() -> dict[str, object]:
    live_dest = live_route_destinations()
    none_dest = no_provider_destinations()
    return {
        "bound_terms": bound_terms_identity(),
        "now": FIXTURE_NOW,
        "provider_call_count": 0,
        "routes": {
            LIVE_ROUTE_ID: {
                "admitted_destinations": list(live_dest),
                "declaration": None,
                "terms_records": [
                    fixture_terms_record(cls) for cls in _providers(live_dest)
                ],
            },
            NO_PROVIDER_ROUTE_ID: {
                "admitted_destinations": list(none_dest),
                "declaration": fixture_declaration(NO_PROVIDER_ROUTE_ID, none_dest),
                "terms_records": [],
            },
        },
    }


def bind_provider_classes() -> tuple[str, ...]:
    """Refuse drift of the six-class commercial/API subset of OD-012."""

    derived = tuple(
        dest
        for dest in EXPECTED_EGRESS_DESTINATIONS
        if dest not in NON_PROVIDER_EGRESS
    )
    if derived != PROVIDER_CLASSES or len(PROVIDER_CLASSES) != 6:
        raise ProviderTermsError("provider classes differ from OD-012")
    if NON_PROVIDER_EGRESS & set(PROVIDER_CLASSES):
        raise ProviderTermsError("provider classes differ from OD-012")
    if any(cls not in EXPECTED_EGRESS_DESTINATIONS for cls in PROVIDER_CLASSES):
        raise ProviderTermsError("provider classes differ from OD-012")
    return PROVIDER_CLASSES


def bind_inventory(fixture: Mapping[str, object] | None) -> dict[str, object]:
    """Refuse an envelope that is not a valid fixture inventory."""

    if not isinstance(fixture, Mapping) or not fixture:
        raise ProviderTermsError("inventory is required")
    if set(fixture) != _INVENTORY_FIELDS:
        raise ProviderTermsError("inventory is required")
    _timestamp(fixture["now"], "now")
    count = fixture["provider_call_count"]
    if type(count) is not int or count < 0:
        raise ProviderTermsError("inventory is required")
    bound = fixture["bound_terms"]
    if type(bound) is not dict or set(bound) != set(PROVIDER_CLASSES):
        raise ProviderTermsError("inventory is required")
    identities: dict[str, dict[str, str]] = {}
    for cls in PROVIDER_CLASSES:
        item = bound[cls]
        if type(item) is not dict or set(item) != _BOUND_FIELDS:
            raise ProviderTermsError("inventory is required")
        identities[cls] = {
            "terms_digest": _digest(item["terms_digest"], "terms_digest"),
            "terms_url": _token(item["terms_url"], "terms_url"),
        }
    routes = fixture["routes"]
    if type(routes) is not dict or not routes:
        raise ProviderTermsError("inventory is required")
    bound_routes: dict[str, dict[str, object]] = {}
    for route_id, route in routes.items():
        token = _token(route_id, "route_id")
        if type(route) is not dict or set(route) != _ROUTE_FIELDS:
            raise ProviderTermsError("inventory is required")
        if type(route["terms_records"]) not in (tuple, list):
            raise ProviderTermsError("inventory is required")
        declaration = route["declaration"]
        if declaration is not None and type(declaration) is not dict:
            raise ProviderTermsError("inventory is required")
        bound_routes[token] = {
            "admitted_destinations": list(route["admitted_destinations"]),
            "declaration": None if declaration is None else dict(declaration),
            "terms_records": [dict(item) if type(item) is dict else item for item in route["terms_records"]],
        }
    bind_provider_classes()
    return {
        "bound_terms": identities,
        "now": fixture["now"],
        "provider_call_count": count,
        "routes": bound_routes,
    }


@dataclass(frozen=True, slots=True)
class TermsAdmission:
    route_id: str
    path: str
    admitted_provider_classes: tuple[str, ...]
    status: str = "PASS"

    def primitive(self) -> dict[str, object]:
        return {
            "admitted_provider_classes": list(self.admitted_provider_classes),
            "path": self.path,
            "route_id": self.route_id,
            "status": self.status,
        }

    @property
    def digest(self) -> str:
        return digest_bytes(canonical_json_bytes(self.primitive()))


class ProviderTermsAdmitter:
    """Dual-path admitter bound to one injected inventory and now."""

    def __init__(
        self,
        inventory: Mapping[str, object] | None,
        *,
        now: str | None = None,
    ) -> None:
        bound = bind_inventory(inventory)
        self._bound_terms = bound["bound_terms"]
        self._routes = bound["routes"]
        self._provider_call_count = bound["provider_call_count"]
        self._now = _timestamp(now, "now") if now is not None else bound["now"]

    def admit(self, route: object) -> TermsAdmission:
        route_id = _token(route, "route_id")
        presented = self._routes.get(route_id)
        if presented is None:
            raise ProviderTermsError("record is malformed")
        destinations = _destinations(presented["admitted_destinations"])
        records = presented["terms_records"]
        declaration = presented["declaration"]
        if type(records) not in (tuple, list):
            raise ProviderTermsError("record is malformed")
        has_terms = bool(records)
        has_declaration = declaration is not None
        if has_terms and has_declaration:
            raise ProviderTermsError("path crossing is refused")
        if not has_terms and not has_declaration:
            raise ProviderTermsError("records are required")
        if has_declaration:
            return self._admit_no_provider(route_id, destinations, declaration)
        return self._admit_live(route_id, destinations, records)

    def _admit_no_provider(
        self,
        route_id: str,
        destinations: tuple[str, ...],
        declaration: object,
    ) -> TermsAdmission:
        record = _parse_declaration(declaration, now=self._now)
        if record["route_id"] != route_id:
            raise ProviderTermsError("record is malformed")
        declared = _destinations(record["admitted_destinations"])
        claimed = record["provider_classes_admitted"]
        if type(claimed) not in (tuple, list) or any(
            type(item) is not str for item in claimed
        ):
            raise ProviderTermsError("record is malformed")
        contradicted = bool(
            _providers(destinations)
            or _providers(declared)
            or tuple(claimed)
            or self._provider_call_count > 0
        )
        if contradicted:
            raise ProviderTermsError("no-provider declaration is contradicted")
        return TermsAdmission(route_id, NO_PROVIDER_PATH, ())

    def _admit_live(
        self,
        route_id: str,
        destinations: tuple[str, ...],
        records: object,
    ) -> TermsAdmission:
        admitted = _providers(destinations)
        if not admitted:
            raise ProviderTermsError("live coverage is incomplete")
        seen: list[str] = []
        for item in records:  # type: ignore[union-attr]
            parsed = _parse_terms_record(item, now=self._now)
            cls = parsed["provider_class"]
            if cls not in PROVIDER_CLASSES or cls not in admitted:
                raise ProviderTermsError("unexpected class")
            if cls in seen:
                raise ProviderTermsError("record is malformed")
            identity = self._bound_terms[cls]
            if (
                parsed["terms_digest"] != identity["terms_digest"]
                or parsed["terms_url"] != identity["terms_url"]
            ):
                raise ProviderTermsError("terms digest differs")
            seen.append(cls)
        if tuple(cls for cls in PROVIDER_CLASSES if cls in seen) != admitted:
            raise ProviderTermsError("live coverage is incomplete")
        return TermsAdmission(route_id, LIVE_PATH, admitted)


def _parse_terms_record(value: object, *, now: str) -> dict[str, str]:
    if type(value) is not dict or set(value) != _TERMS_FIELDS:
        raise ProviderTermsError("record is malformed")
    gate_id = _token(value["gate_id"], "gate_id")
    if gate_id != GATE_ID:
        raise ProviderTermsError("record is malformed")
    provider_class = _token(value["provider_class"], "provider_class")
    terms_url = _token(value["terms_url"], "terms_url")
    terms_digest = _digest(value["terms_digest"], "terms_digest")
    issued_at = _timestamp(value["issued_at"], "issued_at")
    expires_at = _timestamp(value["expires_at"], "expires_at")
    _verify_seal(value)
    _window(issued_at, expires_at, now)
    return {
        "expires_at": expires_at,
        "gate_id": gate_id,
        "issued_at": issued_at,
        "provider_class": provider_class,
        "terms_digest": terms_digest,
        "terms_url": terms_url,
    }


def _parse_declaration(value: object, *, now: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != _DECLARATION_FIELDS:
        raise ProviderTermsError("record is malformed")
    route_id = _token(value["route_id"], "route_id")
    issued_at = _timestamp(value["issued_at"], "issued_at")
    expires_at = _timestamp(value["expires_at"], "expires_at")
    _verify_seal(value)
    _window(issued_at, expires_at, now)
    return {
        "admitted_destinations": value["admitted_destinations"],
        "expires_at": expires_at,
        "issued_at": issued_at,
        "provider_classes_admitted": value["provider_classes_admitted"],
        "route_id": route_id,
    }


def admit(
    route: object,
    *,
    inventory: Mapping[str, object] | None = None,
    now: str | None = None,
    admitter: ProviderTermsAdmitter | None = None,
) -> TermsAdmission:
    """Admit one named route or refuse fail-closed. No live ToS fetch."""

    active = (
        admitter
        if admitter is not None
        else ProviderTermsAdmitter(inventory, now=now)
    )
    return active.admit(route)


def refuse_namesake_satisfaction(gates: tuple[str, ...] | list[str]) -> None:
    """Refuse RUNTIME_GATES list membership as this First I/O Gate."""

    if GATE_ID in gates:
        raise ProviderTermsError(
            "RUNTIME_GATES membership cannot satisfy this First I/O Gate"
        )
    raise ProviderTermsError(
        "PROVIDER_TERMS_CURRENT is absent from RUNTIME_GATES"
    )


def refuse_increment8_terms_current(terms_current: bool) -> None:
    """Refuse the Increment 8 terms_current boolean as this First I/O Gate."""

    raise ProviderTermsError(
        "Increment 8 terms_current cannot satisfy this First I/O Gate"
    )


def refuse_openrouter_unused() -> None:
    """Refuse the 9P OPENROUTER_UNUSED proving gate as this First I/O Gate."""

    from newsroom.increment9.proving import GateStatus, assess as proving_assess

    gates = proving_assess(
        run_id="fixture-run", kill_switch=False, no_emergency_stop=True
    )
    unused = any(
        item.gate_id == "OPENROUTER_UNUSED" and item.status is GateStatus.PASS
        for item in gates
    )
    if unused:
        raise ProviderTermsError(
            "proving OPENROUTER_UNUSED cannot satisfy this First I/O Gate"
        )
    raise ProviderTermsError("OPENROUTER_UNUSED is absent from proving")


def bind_campaign_provider_terms() -> str:
    """Campaign PROVIDER_TERMS_CURRENT bind: the admitter, not a bare gate name.

    RUNTIME_GATES list membership, Increment 8 terms_current and 9P
    OPENROUTER_UNUSED cannot PASS.
    """

    inventory = fixture_inventory()
    live = admit(LIVE_ROUTE_ID, inventory=inventory)
    named = admit(NO_PROVIDER_ROUTE_ID, inventory=inventory)
    if live.path != LIVE_PATH or named.path != NO_PROVIDER_PATH:
        raise ProviderTermsError("campaign provider terms are unbound")
    if live.status != "PASS" or named.status != "PASS":
        raise ProviderTermsError("campaign provider terms are unbound")
    return live.digest
