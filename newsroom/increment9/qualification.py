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
FORBIDDEN_INVENTORY_MARKERS = ("news_pool.sqlite3", "production")

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


def default_probe(route: str, path: Path) -> bool:
    if route not in WRITER_ROUTES:
        raise QualificationError(f"unknown writer route: {route}")
    if not path.is_file():
        raise QualificationError(f"missing surface: {route}")
    return False


def _reject_forbidden(inventory: Path) -> None:
    lowered = str(inventory).lower()
    if "news_pool.sqlite3" in lowered:
        raise QualificationError("inventory must not alias news_pool")
    if "production" in lowered:
        raise QualificationError("inventory must not alias production")


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
        "surfaces": [
            {
                "after_digest": item.after_digest,
                "before_digest": item.before_digest,
                "route": item.route,
            }
            for item in records
        ],
    }
    digest = digest_bytes(canonical_json_bytes(payload))
    return QualificationEvidence(
        gate_id=GATE_ID,
        status="PASS",
        publication=False,
        public_dispatch=False,
        production_writer_successes=0,
        surfaces=records,
        evidence_digest=digest,
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
        "surfaces": [
            {
                "after_digest": item.after_digest,
                "before_digest": item.before_digest,
                "route": item.route,
            }
            for item in evidence.surfaces
        ],
    }
    return canonical_json_bytes(payload)
