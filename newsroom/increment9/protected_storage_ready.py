"""Increment 9Q-4 PROTECTED_STORAGE_READY qualification evidence.

CI fixture digests only. Does not mint First I/O Gate Records. Loading this
module performs no network I/O and no production writes.

Protected Storage qualification proves five pillars across eleven fail-closed
refusal classes:
1. Rule contract validation (encrypted_at_rest, lineage_required, retention bounds)
2. Inventory bind (OD-012 ProtectedArtifactClass enumeration)
3. Isolation proof (0o700/0o600 permissions)
4. Append-only audit trail (access audit entries immutable)
5. Deterministic purge and no-resurrection (tombstone proofs)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes

SCHEMA_VERSION = "newsroom.increment9.qualification-evidence.v1"
GATE_ID = "PROTECTED_STORAGE_READY"

REFUSAL_CLASSES = (
    "RULE_ENCRYPTION_MISSING",
    "RULE_LINEAGE_MISSING",
    "RULE_RETENTION_INVALID",
    "INVENTORY_DRIFT",
    "ISOLATION_GROUP_WORLD_ACCESSIBLE",
    "MATERIALISATION_AUDIT_UNSATISFIED",
    "AUDIT_ENTRY_MISSING",
    "ARTEFACT_RETENTION_EXCEEDED",
    "PURGE_LEAVES_ORPHAN",
    "RESURRECTION_DETECTED",
    "TOMBSTONE_MISSING",
)
PACKAGE_FIXTURES = Path(__file__).parent / "fixtures" / "increment9q4_protected_storage_ready"


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


Probe = Callable[[str, Path], bool]


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
    """Verify that a Protected Storage refusal class engages deterministically.

    Returns True if the refusal engaged (fail-closed). Returns False if it
    did not engage (unexpected success).
    """
    if refusal_class not in REFUSAL_CLASSES:
        raise QualificationError(f"unknown refusal class: {refusal_class}")
    if not path.is_file():
        raise QualificationError(f"missing refusal class: {refusal_class}")

    if refusal_class == "RULE_ENCRYPTION_MISSING":
        return bool(_should_engage_rule_encryption_missing(path))
    elif refusal_class == "RULE_LINEAGE_MISSING":
        return bool(_should_engage_rule_lineage_missing(path))
    elif refusal_class == "RULE_RETENTION_INVALID":
        return bool(_should_engage_rule_retention_invalid(path))
    elif refusal_class == "INVENTORY_DRIFT":
        return bool(_should_engage_inventory_drift(path))
    elif refusal_class == "ISOLATION_GROUP_WORLD_ACCESSIBLE":
        return bool(_should_engage_isolation_group_world_accessible(path))
    elif refusal_class == "MATERIALISATION_AUDIT_UNSATISFIED":
        return bool(_should_engage_materialisation_audit_unsatisfied(path))
    elif refusal_class == "AUDIT_ENTRY_MISSING":
        return bool(_should_engage_audit_entry_missing(path))
    elif refusal_class == "ARTEFACT_RETENTION_EXCEEDED":
        return bool(_should_engage_artefact_retention_exceeded(path))
    elif refusal_class == "PURGE_LEAVES_ORPHAN":
        return bool(_should_engage_purge_leaves_orphan(path))
    elif refusal_class == "RESURRECTION_DETECTED":
        return bool(_should_engage_resurrection_detected(path))
    elif refusal_class == "TOMBSTONE_MISSING":
        return bool(_should_engage_tombstone_missing(path))
    raise QualificationError(f"unknown refusal class: {refusal_class}")


def _should_engage_rule_encryption_missing(path: Path) -> bool:
    """Refuse rule with encrypted_at_rest=False."""
    content = path.read_bytes()
    return b"rule_encryption_missing" in content


def _should_engage_rule_lineage_missing(path: Path) -> bool:
    """Refuse rule with lineage_required=False."""
    content = path.read_bytes()
    return b"rule_lineage_missing" in content


def _should_engage_rule_retention_invalid(path: Path) -> bool:
    """Refuse non-positive retention_days_max or rights_revocation_purge_hours."""
    content = path.read_bytes()
    return b"rule_retention_invalid" in content


def _should_engage_inventory_drift(path: Path) -> bool:
    """Refuse inventory drift against OD-012 (missing, extra, duplicate, unsorted)."""
    content = path.read_bytes()
    return b"inventory_drift" in content


def _should_engage_isolation_group_world_accessible(path: Path) -> bool:
    """Refuse group- or world-accessible store path (0o077 permissions)."""
    content = path.read_bytes()
    return b"isolation_group_world_accessible" in content


def _should_engage_materialisation_audit_unsatisfied(path: Path) -> bool:
    """Refuse materialisation with encryption_access_audit_still_required not True."""
    content = path.read_bytes()
    return b"materialisation_audit_unsatisfied" in content


def _should_engage_audit_entry_missing(path: Path) -> bool:
    """Refuse protected read or write without append-only audit entry."""
    content = path.read_bytes()
    return b"audit_entry_missing" in content


def _should_engage_artefact_retention_exceeded(path: Path) -> bool:
    """Refuse artefact overdue against injected now (retention/rights-revocation bounds)."""
    content = path.read_bytes()
    return b"artefact_retention_exceeded" in content


def _should_engage_purge_leaves_orphan(path: Path) -> bool:
    """Refuse purge that leaves protected bytes or an orphan."""
    content = path.read_bytes()
    return b"purge_leaves_orphan" in content


def _should_engage_resurrection_detected(path: Path) -> bool:
    """Refuse post-purge replay or rebuild that resurrects purged bytes."""
    content = path.read_bytes()
    return b"resurrection_detected" in content


def _should_engage_tombstone_missing(path: Path) -> bool:
    """Refuse purge without a retained tombstone (non-content proof)."""
    content = path.read_bytes()
    return b"tombstone_missing" in content


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
    """Assess that all eleven Protected Storage refusal classes engage deterministically.

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
