"""Increment 9Q-8 PROVIDER_TERMS_CURRENT qualification evidence.

CI fixture digests only. Does not mint First I/O Gate Records. Loading this
module performs no network I/O and no production writes.

Qualification proves dual-path terms admission on the real contracts,
fail-closed: live-route Provider Terms Records or a named-route No-Provider
Declaration.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment8.observability import AccessContract, SecurityAdmission
from newsroom.increment9.provider_terms import (
    FIXTURE_NOW,
    GATE_ID,
    LIVE_PATH,
    LIVE_ROUTE_ID,
    NO_PROVIDER_PATH,
    NO_PROVIDER_ROUTE_ID,
    ProviderTermsError,
    admit,
    bind_campaign_provider_terms,
    bind_inventory,
    fixture_declaration,
    fixture_inventory,
    fixture_terms_record,
    refuse_increment8_terms_current,
    refuse_namesake_satisfaction,
    refuse_openrouter_unused,
)

SCHEMA_VERSION = "newsroom.increment9.qualification-evidence.v1"
INVENTORY_NAME = "inventory.json"

REFUSAL_CLASSES = (
    "NO_RECORDS",
    "PATH_CROSSING",
    "NO_PROVIDER_CONTRADICTED",
    "INCOMPLETE_LIVE_COVERAGE",
    "UNEXPECTED_CLASS",
    "TERMS_DIGEST_DRIFT",
    "EXPIRED_OR_FUTURE_DATED",
    "INVALID_SEAL",
    "MALFORMED_RECORD",
    "ANTI_NAMESAKE",
)
PACKAGE_FIXTURES = (
    Path(__file__).parent / "fixtures" / "increment9q8_provider_terms_current"
)
_MARKERS = {
    "NO_RECORDS": b"no_records",
    "PATH_CROSSING": b"path_crossing",
    "NO_PROVIDER_CONTRADICTED": b"no_provider_contradicted",
    "INCOMPLETE_LIVE_COVERAGE": b"incomplete_live_coverage",
    "UNEXPECTED_CLASS": b"unexpected_class",
    "TERMS_DIGEST_DRIFT": b"terms_digest_drift",
    "EXPIRED_OR_FUTURE_DATED": b"expired_or_future_dated",
    "INVALID_SEAL": b"invalid_seal",
    "MALFORMED_RECORD": b"malformed_record",
    "ANTI_NAMESAKE": b"anti_namesake",
}
_DIGEST = "sha256:" + "0" * 64

Probe = Callable[[str, Path], bool]


class QualificationError(ValueError):
    """Qualification inventory, probe or digest check failed closed."""


@dataclass(frozen=True, slots=True)
class RefusalDigest:
    refusal_class: str
    before_digest: str
    after_digest: str
    engaged: bool
    count: int


@dataclass(frozen=True, slots=True)
class QualificationEvidence:
    gate_id: str
    status: str
    refusals_engaged: int
    refusals: tuple[RefusalDigest, ...]
    live_route_digest: str
    no_provider_route_digest: str
    evidence_digest: str


def _reject_forbidden(inventory: Path) -> None:
    lowered = str(inventory).lower()
    if "news_pool" in lowered:
        raise QualificationError("inventory must not alias news_pool")


def _refusal_surfaces(inventory: Path) -> tuple[tuple[str, Path], ...]:
    if not inventory.is_dir():
        raise QualificationError("inventory is required")
    missing = [rc for rc in REFUSAL_CLASSES if not (inventory / rc).is_file()]
    if missing:
        raise QualificationError(f"missing refusal class: {missing[0]}")
    extras = sorted(
        path.name
        for path in inventory.iterdir()
        if path.name not in REFUSAL_CLASSES and path.name != INVENTORY_NAME
    )
    if extras:
        raise QualificationError(f"unexpected refusal class: {extras[0]}")
    return tuple((rc, inventory / rc) for rc in REFUSAL_CLASSES)


def _load_inventory(inventory: Path) -> dict[str, object]:
    path = inventory / INVENTORY_NAME
    if not path.is_file():
        raise QualificationError("inventory is required")
    try:
        raw = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationError("inventory is required") from exc
    if type(raw) is not dict or not raw:
        raise QualificationError("inventory is required")
    try:
        bind_inventory(raw)
    except ProviderTermsError as exc:
        raise QualificationError("inventory is required") from exc
    return raw


def _digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def _refused(action: Callable[[], object]) -> bool:
    try:
        action()
    except ProviderTermsError:
        return True
    return False


def default_probe(refusal_class: str, path: Path) -> bool:
    """Verify that a provider-terms refusal class engages on the real contracts.

    Returns True if the refusal engaged (fail-closed). Returns False if it
    did not engage (unexpected success).
    """
    if refusal_class not in REFUSAL_CLASSES:
        raise QualificationError(f"unknown refusal class: {refusal_class}")
    if not path.is_file():
        raise QualificationError(f"missing refusal class: {refusal_class}")
    if _MARKERS[refusal_class] not in path.read_bytes():
        return False
    probes = {
        "NO_RECORDS": _should_engage_no_records,
        "PATH_CROSSING": _should_engage_path_crossing,
        "NO_PROVIDER_CONTRADICTED": _should_engage_no_provider_contradicted,
        "INCOMPLETE_LIVE_COVERAGE": _should_engage_incomplete_live_coverage,
        "UNEXPECTED_CLASS": _should_engage_unexpected_class,
        "TERMS_DIGEST_DRIFT": _should_engage_terms_digest_drift,
        "EXPIRED_OR_FUTURE_DATED": _should_engage_expired_or_future_dated,
        "INVALID_SEAL": _should_engage_invalid_seal,
        "MALFORMED_RECORD": _should_engage_malformed_record,
        "ANTI_NAMESAKE": _should_engage_anti_namesake,
    }
    return bool(probes[refusal_class]())


def _should_engage_no_records() -> bool:
    empty = fixture_inventory()
    empty["routes"][LIVE_ROUTE_ID]["terms_records"] = []
    empty["routes"][LIVE_ROUTE_ID]["declaration"] = None
    return all(
        (
            _refused(lambda: admit(LIVE_ROUTE_ID, inventory=None)),
            _refused(lambda: admit(LIVE_ROUTE_ID, inventory={})),
            _refused(lambda: admit(LIVE_ROUTE_ID, inventory=empty)),
        )
    )


def _should_engage_path_crossing() -> bool:
    inventory = fixture_inventory()
    live = inventory["routes"][LIVE_ROUTE_ID]
    live["declaration"] = fixture_declaration(
        LIVE_ROUTE_ID, live["admitted_destinations"]
    )
    named = fixture_inventory()
    named["routes"][NO_PROVIDER_ROUTE_ID]["terms_records"] = [
        fixture_terms_record("ANTHROPIC_AGENT_SDK")
    ]
    return _refused(lambda: admit(LIVE_ROUTE_ID, inventory=inventory)) and _refused(
        lambda: admit(NO_PROVIDER_ROUTE_ID, inventory=named)
    )


def _should_engage_no_provider_contradicted() -> bool:
    destinations = fixture_inventory()
    route = destinations["routes"][NO_PROVIDER_ROUTE_ID]
    route["admitted_destinations"] = sorted(
        {*route["admitted_destinations"], "ANTHROPIC_AGENT_SDK"}
    )
    counted = fixture_inventory()
    counted["provider_call_count"] = 1
    return _refused(
        lambda: admit(NO_PROVIDER_ROUTE_ID, inventory=destinations)
    ) and _refused(lambda: admit(NO_PROVIDER_ROUTE_ID, inventory=counted))


def _should_engage_incomplete_live_coverage() -> bool:
    inventory = fixture_inventory()
    records = inventory["routes"][LIVE_ROUTE_ID]["terms_records"]
    records.pop()
    return _refused(lambda: admit(LIVE_ROUTE_ID, inventory=inventory))


def _should_engage_unexpected_class() -> bool:
    outside_six = fixture_inventory()
    outside_six["routes"][LIVE_ROUTE_ID]["terms_records"].append(
        fixture_terms_record("INTEGRATED_NEWSROOM_TARGET")
    )
    outside_route = fixture_inventory()
    live = outside_route["routes"][LIVE_ROUTE_ID]
    live["admitted_destinations"] = ["ANTHROPIC_AGENT_SDK"]
    live["terms_records"] = [
        fixture_terms_record("ANTHROPIC_AGENT_SDK"),
        fixture_terms_record("GOOGLE_GEMINI_API"),
    ]
    return _refused(
        lambda: admit(LIVE_ROUTE_ID, inventory=outside_six)
    ) and _refused(lambda: admit(LIVE_ROUTE_ID, inventory=outside_route))


def _should_engage_terms_digest_drift() -> bool:
    inventory = fixture_inventory()
    records = inventory["routes"][LIVE_ROUTE_ID]["terms_records"]
    cls = records[0]["provider_class"]
    records[0] = fixture_terms_record(cls, terms_digest=_DIGEST)
    return _refused(lambda: admit(LIVE_ROUTE_ID, inventory=inventory))


def _should_engage_expired_or_future_dated() -> bool:
    expired = fixture_inventory()
    records = expired["routes"][LIVE_ROUTE_ID]["terms_records"]
    cls = records[0]["provider_class"]
    records[0] = fixture_terms_record(cls, expires_at=FIXTURE_NOW)
    future = fixture_inventory()
    future_records = future["routes"][LIVE_ROUTE_ID]["terms_records"]
    future_cls = future_records[0]["provider_class"]
    future_records[0] = fixture_terms_record(
        future_cls, issued_at="2026-08-18T12:00:00.000001Z"
    )
    return _refused(lambda: admit(LIVE_ROUTE_ID, inventory=expired)) and _refused(
        lambda: admit(LIVE_ROUTE_ID, inventory=future)
    )


def _should_engage_invalid_seal() -> bool:
    inventory = fixture_inventory()
    records = inventory["routes"][LIVE_ROUTE_ID]["terms_records"]
    cls = records[0]["provider_class"]
    records[0] = fixture_terms_record(cls, seal="hmac-sha256:" + "0" * 64)
    return _refused(lambda: admit(LIVE_ROUTE_ID, inventory=inventory))


def _should_engage_malformed_record() -> bool:
    missing = fixture_inventory()
    del missing["routes"][LIVE_ROUTE_ID]["terms_records"][0]["terms_url"]
    extra = fixture_inventory()
    extra["routes"][LIVE_ROUTE_ID]["terms_records"][0]["extra"] = "field"
    empty_route = fixture_inventory()
    empty_route["routes"][NO_PROVIDER_ROUTE_ID]["declaration"] = fixture_declaration(
        "", empty_route["routes"][NO_PROVIDER_ROUTE_ID]["admitted_destinations"]
    )
    over_long = fixture_inventory()
    over_long["routes"][LIVE_ROUTE_ID]["terms_records"][0] = fixture_terms_record(
        "H" * 257
    )
    return all(
        (
            _refused(lambda: admit(LIVE_ROUTE_ID, inventory=missing)),
            _refused(lambda: admit(LIVE_ROUTE_ID, inventory=extra)),
            _refused(lambda: admit(NO_PROVIDER_ROUTE_ID, inventory=empty_route)),
            _refused(lambda: admit(LIVE_ROUTE_ID, inventory=over_long)),
        )
    )


def _security_admission(*, terms_current: bool) -> SecurityAdmission:
    contract = AccessContract.build(
        contract_id="fixture-access:v1",
        approved_hosts=["fixture.invalid"],
        maximum_redirects=0,
        request_timeout_seconds=30,
        maximum_body_bytes=1_000_000,
        content_types=["application/json"],
    )
    return SecurityAdmission.build(
        access_contract=contract,
        exact_version_approved=True,
        rights_current=True,
        terms_current=terms_current,
        pricing_current=True,
        credential_scope_current=True,
        rollback_tested=True,
        scoped_disable_tested=True,
        graph_capability_admitted=True,
        runbook_version_digest="sha256:" + "1" * 64,
    )


def _should_engage_anti_namesake() -> bool:
    from scripts.increment9_shadow_campaign import RUNTIME_GATES

    namesake_closed = _refused(lambda: refuse_namesake_satisfaction(RUNTIME_GATES))
    listed = GATE_ID in RUNTIME_GATES
    admission = _security_admission(terms_current=True)
    payload = json.loads(admission.canonical_bytes)["payload"]
    boolean_closed = payload["terms_current"] is True and _refused(
        lambda: refuse_increment8_terms_current(payload["terms_current"])
    )
    openrouter_closed = _refused(lambda: refuse_openrouter_unused())
    authorised = not _refused(lambda: bind_campaign_provider_terms())
    return (
        namesake_closed
        and listed
        and boolean_closed
        and openrouter_closed
        and authorised
    )


def _refusal_payload(
    records: tuple[RefusalDigest, ...],
) -> list[dict[str, str | bool | int]]:
    return [
        {
            "after_digest": item.after_digest,
            "before_digest": item.before_digest,
            "count": item.count,
            "engaged": item.engaged,
            "refusal_class": item.refusal_class,
        }
        for item in records
    ]


def _demonstrate(inventory: Mapping[str, object]) -> tuple[str, str]:
    live = admit(LIVE_ROUTE_ID, inventory=inventory)
    named = admit(NO_PROVIDER_ROUTE_ID, inventory=inventory)
    if live.path != LIVE_PATH or named.path != NO_PROVIDER_PATH:
        raise QualificationError("inventory is required")
    if live.status != "PASS" or named.status != "PASS":
        raise QualificationError("inventory is required")
    return live.digest, named.digest


def assess(
    inventory: Path,
    *,
    probe: Probe | None = None,
    terms_inventory: Mapping[str, object] | None = None,
) -> QualificationEvidence:
    """Assess that all ten provider-terms refusal classes engage deterministically.

    Fails closed if:
    - Inventory missing or inaccessible
    - Fixture terms inventory missing or invalid
    - Any refusal class surface missing or unexpected
    - Any digest changes without claimed engagement
    - Probe mutates any surface (fail-closed invariant)
    - Any refusal fails to engage
    """
    _reject_forbidden(inventory)
    surfaces = _refusal_surfaces(inventory)
    if terms_inventory is None:
        bound = _load_inventory(inventory)
    else:
        try:
            bind_inventory(terms_inventory)
        except ProviderTermsError as exc:
            raise QualificationError("inventory is required") from exc
        bound = dict(terms_inventory)
    writer = default_probe if probe is None else probe
    bind_inventory(bound)
    before = {rc: _digest_file(path) for rc, path in surfaces}
    engaged_count = 0
    for rc, path in surfaces:
        if writer(rc, path):
            engaged_count += 1
    after = {rc: _digest_file(path) for rc, path in surfaces}
    if any(before[rc] != after[rc] for rc in REFUSAL_CLASSES):
        raise QualificationError("refusal surface digest mutated")
    if engaged_count != len(REFUSAL_CLASSES):
        raise QualificationError(
            f"not all refusals engaged: {engaged_count}/{len(REFUSAL_CLASSES)}"
        )
    records = tuple(
        RefusalDigest(rc, before[rc], after[rc], True, 1) for rc in REFUSAL_CLASSES
    )
    live_digest, named_digest = _demonstrate(bound)
    payload = {
        "gate_id": GATE_ID,
        "live_route_digest": live_digest,
        "no_provider_route_digest": named_digest,
        "pass_derivations": [LIVE_PATH, NO_PROVIDER_PATH],
        "refusals": _refusal_payload(records),
        "refusals_engaged": engaged_count,
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
    }
    return QualificationEvidence(
        gate_id=GATE_ID,
        status="PASS",
        refusals_engaged=engaged_count,
        refusals=records,
        live_route_digest=live_digest,
        no_provider_route_digest=named_digest,
        evidence_digest=digest_bytes(canonical_json_bytes(payload)),
    )


def evidence_json(evidence: QualificationEvidence) -> bytes:
    """Serialise qualification evidence to canonical JSON."""
    payload = {
        "evidence_digest": evidence.evidence_digest,
        "gate_id": evidence.gate_id,
        "live_route_digest": evidence.live_route_digest,
        "no_provider_route_digest": evidence.no_provider_route_digest,
        "pass_derivations": [LIVE_PATH, NO_PROVIDER_PATH],
        "refusals": _refusal_payload(evidence.refusals),
        "refusals_engaged": evidence.refusals_engaged,
        "schema_version": SCHEMA_VERSION,
        "status": evidence.status,
    }
    return canonical_json_bytes(payload)
