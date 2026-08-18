"""Increment 9Q-6 EGRESS_ALLOWLIST_ENFORCED qualification evidence.

CI fixture digests only. Does not mint First I/O Gate Records. Loading this
module performs no network I/O and no production writes.

Qualification proves policy bind, per-request admission and OD-012 bounds bind
on the real contracts, fail-closed.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment9.deployment import (
    EXPECTED_EGRESS_DESTINATIONS,
    EXPECTED_PROBES,
    DeploymentError,
    EgressPolicy,
    admit_readiness_egress,
)
from newsroom.increment9.egress_allowlist import (
    CONTEXT_READINESS,
    CONTEXT_SHADOW,
    DESTINATION_INVENTORY,
    NAMESAKE_A2_PROBES,
    EgressAllowlistError,
    admit,
    bind_campaign_egress_allowlist,
    bind_host_map,
    bind_inventory,
    bound_admitter,
    fixture_access_boundary,
    fixture_request,
    policy_digest,
    receipt_from_primitive,
    refuse_namesake_satisfaction,
)
from newsroom.increment9.shadow_contracts import ShadowAccessBoundary, ShadowContractError

SCHEMA_VERSION = "newsroom.increment9.qualification-evidence.v1"
GATE_ID = "EGRESS_ALLOWLIST_ENFORCED"
HOST_MAP_NAME = "host_map.json"

REFUSAL_CLASSES = (
    "DEFAULT_DENY",
    "UNKNOWN_DESTINATION_CLASS",
    "CONTEXT_CROSSING",
    "POLICY_DIGEST_MISMATCH",
    "INVENTORY_DRIFT",
    "BOUNDS_VIOLATION",
    "RATE_EXCEEDED",
    "MALFORMED_REQUEST",
    "RECEIPT_INTEGRITY",
    "ANTI_NAMESAKE",
)
PACKAGE_FIXTURES = Path(__file__).parent / "fixtures" / "increment9q6_egress_allowlist_enforced"
_MARKERS = {
    "DEFAULT_DENY": b"default_deny",
    "UNKNOWN_DESTINATION_CLASS": b"unknown_destination_class",
    "CONTEXT_CROSSING": b"context_crossing",
    "POLICY_DIGEST_MISMATCH": b"policy_digest_mismatch",
    "INVENTORY_DRIFT": b"inventory_drift",
    "BOUNDS_VIOLATION": b"bounds_violation",
    "RATE_EXCEEDED": b"rate_exceeded",
    "MALFORMED_REQUEST": b"malformed_request",
    "RECEIPT_INTEGRITY": b"receipt_integrity",
    "ANTI_NAMESAKE": b"anti_namesake",
}

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
    egress_policy_digest: str
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
        if path.name not in REFUSAL_CLASSES and path.name != HOST_MAP_NAME
    )
    if extras:
        raise QualificationError(f"unexpected refusal class: {extras[0]}")
    return tuple((rc, inventory / rc) for rc in REFUSAL_CLASSES)


def _load_host_map(inventory: Path) -> dict[str, str]:
    path = inventory / HOST_MAP_NAME
    if not path.is_file():
        raise QualificationError("host map is required")
    try:
        raw = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationError("host map is required") from exc
    if type(raw) is not dict or not raw:
        raise QualificationError("host map is required")
    try:
        return bind_host_map({str(host): str(cls) for host, cls in raw.items()})
    except EgressAllowlistError as exc:
        raise QualificationError("host map is required") from exc


def _digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def _refused(action: Callable[[], object]) -> bool:
    try:
        action()
    except (EgressAllowlistError, DeploymentError, ShadowContractError):
        return True
    return False


def default_probe(refusal_class: str, path: Path) -> bool:
    """Verify that an egress-allowlist refusal class engages on the real contracts.

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
        "DEFAULT_DENY": _should_engage_default_deny,
        "UNKNOWN_DESTINATION_CLASS": _should_engage_unknown_destination_class,
        "CONTEXT_CROSSING": _should_engage_context_crossing,
        "POLICY_DIGEST_MISMATCH": _should_engage_policy_digest_mismatch,
        "INVENTORY_DRIFT": _should_engage_inventory_drift,
        "BOUNDS_VIOLATION": _should_engage_bounds_violation,
        "RATE_EXCEEDED": _should_engage_rate_exceeded,
        "MALFORMED_REQUEST": _should_engage_malformed_request,
        "RECEIPT_INTEGRITY": _should_engage_receipt_integrity,
        "ANTI_NAMESAKE": _should_engage_anti_namesake,
    }
    return bool(probes[refusal_class]())


def _should_engage_default_deny() -> bool:
    return _refused(
        lambda: admit(
            fixture_request(url="https://absent.fixture.invalid/v1")
        )
    )


def _should_engage_unknown_destination_class() -> bool:
    return _refused(
        lambda: admit(
            fixture_request(destination_class="NOT_A_DESTINATION_CLASS")
        )
    )


def _should_engage_context_crossing() -> bool:
    shadow_readiness = _refused(
        lambda: admit(
            fixture_request(
                context=CONTEXT_SHADOW,
                url="https://filesystem.fixture.invalid/v1",
            )
        )
    )
    readiness_shadow = _refused(
        lambda: admit(
            fixture_request(
                context=CONTEXT_READINESS,
                url="https://anthropic.fixture.invalid/v1",
            )
        )
    )
    return shadow_readiness and readiness_shadow


def _should_engage_policy_digest_mismatch() -> bool:
    other = "sha256:" + "0" * 64
    request_closed = other != policy_digest() and _refused(
        lambda: admit(fixture_request(policy_digest=other))
    )
    boundary = fixture_access_boundary()
    wrong = ShadowAccessBoundary(
        purpose_identity=boundary.purpose_identity,
        principal_identity_digest=boundary.principal_identity_digest,
        permitted_credential_classes=boundary.permitted_credential_classes,
        prohibited_credential_classes=boundary.prohibited_credential_classes,
        egress_policy_digest=other,
        artefact_policy_digest=boundary.artefact_policy_digest,
    )
    construct_closed = _refused(lambda: bound_admitter(boundary=wrong))
    return request_closed and construct_closed


def _should_engage_inventory_drift() -> bool:
    missing = DESTINATION_INVENTORY[:-1]
    extra = tuple(sorted((*DESTINATION_INVENTORY, "EXTRA_DESTINATION")))
    unsorted = (
        DESTINATION_INVENTORY[1],
        DESTINATION_INVENTORY[0],
        *DESTINATION_INVENTORY[2:],
    )
    duplicate = (DESTINATION_INVENTORY[0], *DESTINATION_INVENTORY)
    drifted = (missing, extra, unsorted, duplicate)
    bind_closed = all(
        _refused(lambda inv=inv: bind_inventory(inv)) for inv in drifted
    )
    request_closed = all(
        _refused(lambda inv=inv: admit(fixture_request(destination_inventory=inv)))
        for inv in drifted
    )
    policy_closed = _refused(
        lambda: EgressPolicy(
            configured_destinations=EXPECTED_EGRESS_DESTINATIONS[:-1]
        )
    )
    return bind_closed and request_closed and policy_closed


def _should_engage_bounds_violation() -> bool:
    return all(
        (
            _refused(
                lambda: admit(
                    fixture_request(url="http://anthropic.fixture.invalid/v1")
                )
            ),
            _refused(lambda: admit(fixture_request(tls_minimum="TLS_1_2"))),
            _refused(lambda: admit(fixture_request(redirects=1))),
            _refused(lambda: admit(fixture_request(body_bytes=8_388_609))),
            _refused(lambda: admit(fixture_request(timeout_seconds=31))),
        )
    )


def _should_engage_rate_exceeded() -> bool:
    admitter = bound_admitter()
    for _ in range(36):
        admit(
            fixture_request(source_id="RATE_SOURCE", day="2026-08-17"),
            admitter=admitter,
        )
    return _refused(
        lambda: admit(
            fixture_request(source_id="RATE_SOURCE", day="2026-08-17"),
            admitter=admitter,
        )
    )


def _should_engage_malformed_request() -> bool:
    over_long = "H" * 257
    return all(
        (
            _refused(
                lambda: admit(fixture_request(url="https:///missing-host"))
            ),
            _refused(
                lambda: admit(
                    fixture_request(
                        url="https://user:secret@anthropic.fixture.invalid/v1"
                    )
                )
            ),
            _refused(lambda: admit(fixture_request(source_id=over_long))),
            _refused(lambda: admit(fixture_request(source_id="not a token"))),
        )
    )


def _should_engage_receipt_integrity() -> bool:
    secret_record = {
        "bounds": {
            "redirects_max": 0,
            "response_body_bytes_max": 8_388_608,
            "source_requests_per_day_max": 36,
            "timeout_seconds": 30,
            "tls_minimum": "TLS_1_3",
        },
        "destination_class": "ANTHROPIC_AGENT_SDK",
        "host": "anthropic.fixture.invalid",
        "policy_digest": policy_digest(),
        "secret": "sk-fixture-not-a-real-secret",
    }
    load_closed = _refused(lambda: receipt_from_primitive(secret_record))
    missing = {
        "destination_class": "ANTHROPIC_AGENT_SDK",
        "host": "anthropic.fixture.invalid",
        "policy_digest": policy_digest(),
    }
    missing_closed = _refused(lambda: receipt_from_primitive(missing))
    receipt = admit(fixture_request())
    primitive = receipt.primitive()
    evidence = json.loads(canonical_json_bytes(primitive).decode("utf-8"))
    clean = set(primitive) == {
        "bounds",
        "destination_class",
        "host",
        "policy_digest",
    } and not ({"secret", "secret_bytes"} & set(evidence))
    return load_closed and missing_closed and clean


def _should_engage_anti_namesake() -> bool:
    from newsroom.increment9.proving import ALLOWED_HOSTS

    namesake_closed = _refused(lambda: refuse_namesake_satisfaction())
    proving_hosts = _refused(
        lambda: bind_host_map(
            {host: "TEN_APPROVED_SOURCE_ENDPOINTS" for host in ALLOWED_HOSTS}
        )
    )
    a2_as_destinations = _refused(
        lambda: bind_campaign_egress_allowlist(NAMESAKE_A2_PROBES)
    )
    a2_not_this_gate = all(name not in REFUSAL_CLASSES for name in NAMESAKE_A2_PROBES)
    a2_remain_readiness = all(name in EXPECTED_PROBES for name in NAMESAKE_A2_PROBES)
    authorised = not _refused(lambda: bind_campaign_egress_allowlist())
    disagree = _refused(
        lambda: admit(
            fixture_request(
                context=CONTEXT_READINESS,
                url="https://localhost:7687",
            )
        )
    )
    neo4j = admit(
        fixture_request(context=CONTEXT_READINESS, url="bolt://127.0.0.1:7687")
    )
    agrees = (
        neo4j.destination_class == "LOCAL_NEO4J"
        and admit_readiness_egress("bolt://127.0.0.1:7687") == "LOCAL_NEO4J"
    )
    return (
        namesake_closed
        and proving_hosts
        and a2_as_destinations
        and a2_not_this_gate
        and a2_remain_readiness
        and authorised
        and disagree
        and agrees
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


def assess(
    inventory: Path,
    *,
    probe: Probe | None = None,
    host_map: Mapping[str, str] | None = None,
) -> QualificationEvidence:
    """Assess that all ten egress-allowlist refusal classes engage deterministically.

    Fails closed if:
    - Inventory missing or inaccessible
    - Host map missing or invalid
    - Any refusal class surface missing or unexpected
    - Any digest changes without claimed engagement
    - Probe mutates any surface (fail-closed invariant)
    - Any refusal fails to engage
    """
    _reject_forbidden(inventory)
    surfaces = _refusal_surfaces(inventory)
    if host_map is None:
        bound_map = _load_host_map(inventory)
    else:
        try:
            bound_map = bind_host_map(host_map)
        except EgressAllowlistError as exc:
            raise QualificationError("host map is required") from exc
    writer = default_probe if probe is None else probe
    bind_inventory(DESTINATION_INVENTORY)
    bound_admitter(host_map=bound_map)
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
    digest = policy_digest()
    payload = {
        "egress_policy_digest": digest,
        "gate_id": GATE_ID,
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
        egress_policy_digest=digest,
        evidence_digest=digest_bytes(canonical_json_bytes(payload)),
    )


def evidence_json(evidence: QualificationEvidence) -> bytes:
    """Serialise qualification evidence to canonical JSON."""
    payload = {
        "egress_policy_digest": evidence.egress_policy_digest,
        "evidence_digest": evidence.evidence_digest,
        "gate_id": evidence.gate_id,
        "refusals": _refusal_payload(evidence.refusals),
        "refusals_engaged": evidence.refusals_engaged,
        "schema_version": SCHEMA_VERSION,
        "status": evidence.status,
    }
    return canonical_json_bytes(payload)
