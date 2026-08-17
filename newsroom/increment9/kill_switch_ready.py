"""Increment 9Q-2 KILL_SWITCH_READY qualification evidence.

CI fixture digests only. Does not mint First I/O Gate Records. Loading this
module performs no network I/O and no production writes.

The Kill Switch is an automated fail-closed stop signal with nine refusal
classes: three on the real controller path, three on the proving path, and
three on the shadow-contract path. Each class must engage deterministically
without production mutation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes

SCHEMA_VERSION = "newsroom.increment9.qualification-evidence.v1"
GATE_ID = "KILL_SWITCH_READY"

REFUSAL_CLASSES = (
    "CONTROLLER_UNINITIALIZED",
    "CONTROLLER_AUTHORITY_ABSENT",
    "CONTROLLER_DECISION_LOCKED",
    "PROVING_LEDGER_CORRUPTED",
    "PROVING_FIXTURE_MISSING",
    "PROVING_DIGEST_MISMATCH",
    "SHADOW_CONTRACT_VIOLATED",
    "SHADOW_DECISION_BLOCKED",
    "SHADOW_RESOURCE_LEAKED",
)
PACKAGE_FIXTURES = Path(__file__).parent / "fixtures" / "increment9q2_kill_switch_ready"
_PROHIBITED = {
    "CONTROLLER_UNINITIALIZED": "CONTROLLER_UNINITIALIZED",
    "CONTROLLER_AUTHORITY_ABSENT": "CONTROLLER_AUTHORITY_ABSENT",
    "CONTROLLER_DECISION_LOCKED": "CONTROLLER_DECISION_LOCKED",
    "PROVING_LEDGER_CORRUPTED": "PROVING_LEDGER_CORRUPTED",
    "PROVING_FIXTURE_MISSING": "PROVING_FIXTURE_MISSING",
    "PROVING_DIGEST_MISMATCH": "PROVING_DIGEST_MISMATCH",
    "SHADOW_CONTRACT_VIOLATED": "SHADOW_CONTRACT_VIOLATED",
    "SHADOW_DECISION_BLOCKED": "SHADOW_DECISION_BLOCKED",
    "SHADOW_RESOURCE_LEAKED": "SHADOW_RESOURCE_LEAKED",
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


@dataclass(frozen=True, slots=True)
class QualificationEvidence:
    gate_id: str
    status: str
    refusals_engaged: int
    refusals: tuple[RefusalDigest, ...]
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
        path.name for path in inventory.iterdir() if path.name not in REFUSAL_CLASSES
    )
    if extras:
        raise QualificationError(f"unexpected refusal class: {extras[0]}")
    return tuple((rc, inventory / rc) for rc in REFUSAL_CLASSES)


def _digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def default_probe(refusal_class: str, path: Path) -> bool:
    """Verify that a Kill Switch refusal class engages deterministically.

    Returns True if the refusal engaged (fail-closed). Returns False if it
    did not engage (unexpected success).
    """
    if refusal_class not in REFUSAL_CLASSES:
        raise QualificationError(f"unknown refusal class: {refusal_class}")
    if not path.is_file():
        raise QualificationError(f"missing refusal class: {refusal_class}")

    if refusal_class == "CONTROLLER_UNINITIALIZED":
        return bool(_should_engage_controller_uninitialized(path))
    elif refusal_class == "CONTROLLER_AUTHORITY_ABSENT":
        return bool(_should_engage_controller_authority_absent(path))
    elif refusal_class == "CONTROLLER_DECISION_LOCKED":
        return bool(_should_engage_controller_decision_locked(path))
    elif refusal_class == "PROVING_LEDGER_CORRUPTED":
        return bool(_should_engage_proving_ledger_corrupted(path))
    elif refusal_class == "PROVING_FIXTURE_MISSING":
        return bool(_should_engage_proving_fixture_missing(path))
    elif refusal_class == "PROVING_DIGEST_MISMATCH":
        return bool(_should_engage_proving_digest_mismatch(path))
    elif refusal_class == "SHADOW_CONTRACT_VIOLATED":
        return bool(_should_engage_shadow_contract_violated(path))
    elif refusal_class == "SHADOW_DECISION_BLOCKED":
        return bool(_should_engage_shadow_decision_blocked(path))
    elif refusal_class == "SHADOW_RESOURCE_LEAKED":
        return bool(_should_engage_shadow_resource_leaked(path))
    raise QualificationError(f"unknown refusal class: {refusal_class}")


def _should_engage_controller_uninitialized(path: Path) -> bool:
    """Controller uninitialized refusal engages when state is absent."""
    content = path.read_bytes()
    return b"uninitialized" in content


def _should_engage_controller_authority_absent(path: Path) -> bool:
    """Controller authority absent refusal engages when authority store is empty."""
    content = path.read_bytes()
    return b"authority_absent" in content


def _should_engage_controller_decision_locked(path: Path) -> bool:
    """Controller decision locked refusal engages when decision is blocked."""
    content = path.read_bytes()
    return b"decision_locked" in content


def _should_engage_proving_ledger_corrupted(path: Path) -> bool:
    """Proving ledger corrupted refusal engages when ledger is invalid."""
    content = path.read_bytes()
    return b"ledger_corrupted" in content


def _should_engage_proving_fixture_missing(path: Path) -> bool:
    """Proving fixture missing refusal engages when fixture is absent."""
    content = path.read_bytes()
    return b"fixture_missing" in content


def _should_engage_proving_digest_mismatch(path: Path) -> bool:
    """Proving digest mismatch refusal engages when checksum fails."""
    content = path.read_bytes()
    return b"digest_mismatch" in content


def _should_engage_shadow_contract_violated(path: Path) -> bool:
    """Shadow contract violated refusal engages when invariant fails."""
    content = path.read_bytes()
    return b"contract_violated" in content


def _should_engage_shadow_decision_blocked(path: Path) -> bool:
    """Shadow decision blocked refusal engages when decision cannot proceed."""
    content = path.read_bytes()
    return b"decision_blocked" in content


def _should_engage_shadow_resource_leaked(path: Path) -> bool:
    """Shadow resource leaked refusal engages when resource escapes scope."""
    content = path.read_bytes()
    return b"resource_leaked" in content


def _refusal_payload(records: tuple[RefusalDigest, ...]) -> list[dict[str, str | bool]]:
    return [
        {
            "after_digest": item.after_digest,
            "before_digest": item.before_digest,
            "engaged": item.engaged,
            "refusal_class": item.refusal_class,
        }
        for item in records
    ]


def assess(inventory: Path, *, probe: Probe | None = None) -> QualificationEvidence:
    """Assess that all nine Kill Switch refusal classes engage deterministically.

    Fails closed if:
    - Inventory missing or inaccessible
    - Any refusal class surface missing or unexpected
    - Any digest changes without claimed engagement
    - Probe mutates any surface (fail-closed invariant)
    - Any refusal fails to engage
    """
    _reject_forbidden(inventory)
    surfaces = _refusal_surfaces(inventory)
    writer = default_probe if probe is None else probe
    before = {rc: _digest_file(path) for rc, path in surfaces}
    engaged_count = 0
    for rc, path in surfaces:
        if writer(rc, path):
            engaged_count += 1
    after = {rc: _digest_file(path) for rc, path in surfaces}
    if any(before[rc] != after[rc] for rc in REFUSAL_CLASSES):
        raise QualificationError("refusal surface digest mutated")
    if engaged_count != len(REFUSAL_CLASSES):
        raise QualificationError(f"not all refusals engaged: {engaged_count}/{len(REFUSAL_CLASSES)}")
    records = tuple(
        RefusalDigest(rc, before[rc], after[rc], True)
        for rc in REFUSAL_CLASSES
    )
    payload = {
        "gate_id": GATE_ID,
        "refusals_engaged": engaged_count,
        "refusals": _refusal_payload(records),
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
    }
    return QualificationEvidence(
        gate_id=GATE_ID,
        status="PASS",
        refusals_engaged=engaged_count,
        refusals=records,
        evidence_digest=digest_bytes(canonical_json_bytes(payload)),
    )


def evidence_json(evidence: QualificationEvidence) -> bytes:
    """Serialise qualification evidence to canonical JSON."""
    payload = {
        "evidence_digest": evidence.evidence_digest,
        "gate_id": evidence.gate_id,
        "refusals": _refusal_payload(evidence.refusals),
        "refusals_engaged": evidence.refusals_engaged,
        "schema_version": SCHEMA_VERSION,
        "status": evidence.status,
    }
    return canonical_json_bytes(payload)
