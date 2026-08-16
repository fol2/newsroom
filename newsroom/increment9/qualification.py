"""Increment 9Q-1 PRODUCTION_NONMUTATION_BASELINE qualification evidence.

CI fixture digests only. Does not mint First I/O Gate Records. Loading this
module performs no network I/O and no production writes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes

SCHEMA_VERSION = "newsroom.increment9.qualification-evidence.v1"
GATE_ID = "PRODUCTION_NONMUTATION_BASELINE"
WRITER_ROUTES = (
    "PUBLICATION",
    "DISCORD_OR_PUBLIC_DISPATCH",
    "EVIDENCE_INTAKE",
    "CANARY",
    "PRODUCTION_SQLITE",
    "PRODUCTION_NEO4J",
)
FORBIDDEN_INVENTORY_MARKERS = ("news_pool.sqlite3",)
PACKAGE_FIXTURES = Path(__file__).parent / "fixtures" / "increment9q1_nonmutation"
_PROHIBITED = {
    "PUBLICATION": "PUBLICATION",
    "DISCORD_OR_PUBLIC_DISPATCH": "DISCORD_OR_PUBLIC_DISPATCH",
    "EVIDENCE_INTAKE": "EVIDENCE_INTAKE",
    "CANARY": "CANARY",
    "PRODUCTION_SQLITE": "PRODUCTION_SQLITE_WRITE",
    "PRODUCTION_NEO4J": "PRODUCTION_NEO4J_WRITE",
}

Probe = Callable[[str, Path], bool]


class QualificationError(ValueError):
    """Qualification inventory, probe or digest check failed closed."""


@dataclass(frozen=True, slots=True)
class SurfaceDigest:
    route: str
    before_digest: str
    after_digest: str


@dataclass(frozen=True, slots=True)
class QualificationEvidence:
    gate_id: str
    status: str
    publication: bool
    public_dispatch: bool
    production_writer_successes: int
    surfaces: tuple[SurfaceDigest, ...]
    evidence_digest: str


def _reject_forbidden(inventory: Path) -> None:
    lowered = str(inventory).lower()
    if any(marker in lowered for marker in FORBIDDEN_INVENTORY_MARKERS):
        raise QualificationError("inventory must not alias news_pool")


def _surfaces(inventory: Path) -> tuple[tuple[str, Path], ...]:
    if not inventory.is_dir():
        raise QualificationError("inventory is required")
    missing = [route for route in WRITER_ROUTES if not (inventory / route).is_file()]
    if missing:
        raise QualificationError(f"missing surface: {missing[0]}")
    extras = sorted(
        path.name for path in inventory.iterdir() if path.name not in WRITER_ROUTES
    )
    if extras:
        raise QualificationError(f"unexpected surface: {extras[0]}")
    return tuple((route, inventory / route) for route in WRITER_ROUTES)


def _digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def default_probe(route: str, path: Path) -> bool:
    if route not in WRITER_ROUTES:
        raise QualificationError(f"unknown writer route: {route}")
    if not path.is_file():
        raise QualificationError(f"missing surface: {route}")
    from newsroom.increment9.shadow_contracts import ProhibitedEffect, _NoEffect

    if _PROHIBITED[route] not in {item.value for item in ProhibitedEffect}:
        return True
    if route == "PUBLICATION":
        return bool(_NoEffect.authorises_publication)
    if route == "EVIDENCE_INTAKE":
        return bool(_NoEffect.authorises_evidence_intake)
    if route == "CANARY":
        return bool(_NoEffect.authorises_canary)
    if route == "PRODUCTION_SQLITE":
        from newsroom.increment9.proving import ProvingError, list_observations

        try:
            list_observations(str(path))
        except ProvingError:
            return False
        return True
    if route == "PRODUCTION_NEO4J":
        from newsroom.increment9.deployment import DeploymentError, admit_readiness_egress

        try:
            admit_readiness_egress("neo4j://production.example:7687")
        except DeploymentError:
            return False
        return True
    if route == "DISCORD_OR_PUBLIC_DISPATCH":
        from newsroom.increment9.proving import ProvingError, assert_allowed_url

        try:
            assert_allowed_url("https://discord.com/api")
        except ProvingError:
            return False
        return True
    raise QualificationError(f"unknown writer route: {route}")


def _surface_payload(records: tuple[SurfaceDigest, ...]) -> list[dict[str, str]]:
    return [
        {
            "after_digest": item.after_digest,
            "before_digest": item.before_digest,
            "route": item.route,
        }
        for item in records
    ]


def assess(inventory: Path, *, probe: Probe | None = None) -> QualificationEvidence:
    _reject_forbidden(inventory)
    surfaces = _surfaces(inventory)
    writer = default_probe if probe is None else probe
    before = {route: _digest_file(path) for route, path in surfaces}
    successes = 0
    for route, path in surfaces:
        if writer(route, path):
            successes += 1
    if successes:
        raise QualificationError("writer route succeeded")
    after = {route: _digest_file(path) for route, path in surfaces}
    records = tuple(
        SurfaceDigest(route, before[route], after[route]) for route, _ in surfaces
    )
    if any(item.before_digest != item.after_digest for item in records):
        raise QualificationError("surface digest mutated")
    payload = {
        "gate_id": GATE_ID,
        "production_writer_successes": 0,
        "public_dispatch": False,
        "publication": False,
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "surfaces": _surface_payload(records),
    }
    return QualificationEvidence(
        gate_id=GATE_ID,
        status="PASS",
        publication=False,
        public_dispatch=False,
        production_writer_successes=0,
        surfaces=records,
        evidence_digest=digest_bytes(canonical_json_bytes(payload)),
    )


def evidence_json(evidence: QualificationEvidence) -> bytes:
    payload = {
        "evidence_digest": evidence.evidence_digest,
        "gate_id": evidence.gate_id,
        "production_writer_successes": evidence.production_writer_successes,
        "public_dispatch": evidence.public_dispatch,
        "publication": evidence.publication,
        "schema_version": SCHEMA_VERSION,
        "status": evidence.status,
        "surfaces": _surface_payload(evidence.surfaces),
    }
    return canonical_json_bytes(payload)
