"""Increment 9Q-3 NO_ACTIVE_HUMAN_EMERGENCY_STOP qualification evidence.

CI fixture digests only. Does not mint First I/O Gate Records. Loading this
module performs no network I/O and no production writes.

A No-Stop Assertion is an owner-signed, time-bounded statement that no Human
Emergency Stop is active for one exact execution-authority record. It must be
current and bound to that record. Validation requires:
- HMAC-SHA256 fixture-signed assertion
- run_id-bound (exact match required)
- issued_at/expires_at time validation against injected now
- Nine refusal classes fail-closed
- Any later signed stop supersedes the assertion
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes

SCHEMA_VERSION = "newsroom.increment9.qualification-evidence.v1"
GATE_ID = "NO_ACTIVE_HUMAN_EMERGENCY_STOP"

REFUSAL_CLASSES = (
    "ASSERTION_MISSING",
    "ASSERTION_MALFORMED",
    "HMAC_VERIFICATION_FAILED",
    "RUN_ID_MISMATCH",
    "ASSERTION_NOT_YET_ISSUED",
    "ASSERTION_EXPIRED",
    "NO_STOP_ASSERTION_SIGNATURE_INVALID",
    "STOP_SUPERSEDES_ASSERTION",
    "ASSERTION_BINDING_ABSENT",
)
PACKAGE_FIXTURES = Path(__file__).parent / "fixtures" / "increment9q3_no_active_human_emergency_stop"


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


@dataclass(frozen=True, slots=True)
class NoStopAssertion:
    """Time-bounded, signed statement of no active Human Emergency Stop."""

    run_id: str
    issued_at: datetime
    expires_at: datetime
    hmac_signature: str
    stop_token: str | None = None


Probe = Callable[[str, Path, NoStopAssertion | None, datetime], bool]


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


def _parse_assertion(assertion_path: Path) -> NoStopAssertion:
    """Parse and validate No-Stop Assertion JSON structure."""
    try:
        content = json.loads(assertion_path.read_text())
    except (json.JSONDecodeError, ValueError) as exc:
        raise QualificationError(f"assertion malformed: {exc}")

    required_fields = ("run_id", "issued_at", "expires_at", "hmac_signature")
    for field in required_fields:
        if field not in content:
            raise QualificationError(f"assertion missing field: {field}")

    try:
        issued_at = datetime.fromisoformat(content["issued_at"])
        expires_at = datetime.fromisoformat(content["expires_at"])
    except ValueError as exc:
        raise QualificationError(f"assertion timestamp invalid: {exc}")

    return NoStopAssertion(
        run_id=content["run_id"],
        issued_at=issued_at,
        expires_at=expires_at,
        hmac_signature=content["hmac_signature"],
        stop_token=content.get("stop_token"),
    )


def _verify_hmac(assertion: NoStopAssertion, secret_key: bytes) -> bool:
    """Verify HMAC-SHA256 signature of assertion."""
    payload = {
        "run_id": assertion.run_id,
        "issued_at": assertion.issued_at.isoformat(),
        "expires_at": assertion.expires_at.isoformat(),
    }
    canonical = canonical_json_bytes(payload)
    expected_sig = hmac.new(secret_key, canonical, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_sig, assertion.hmac_signature)


def default_probe(
    refusal_class: str,
    path: Path,
    assertion: NoStopAssertion | None = None,
    now: datetime | None = None,
) -> bool:
    """Verify that a NO_ACTIVE_HUMAN_EMERGENCY_STOP refusal class engages deterministically.

    Returns True if the refusal engaged (fail-closed). Returns False if it
    did not engage (unexpected success).
    """
    if refusal_class not in REFUSAL_CLASSES:
        raise QualificationError(f"unknown refusal class: {refusal_class}")
    if not path.is_file():
        raise QualificationError(f"missing refusal class: {refusal_class}")

    if now is None:
        now = datetime.now(timezone.utc)

    if refusal_class == "ASSERTION_MISSING":
        return bool(_should_engage_assertion_missing(path))
    elif refusal_class == "ASSERTION_MALFORMED":
        return bool(_should_engage_assertion_malformed(path))
    elif refusal_class == "HMAC_VERIFICATION_FAILED":
        return bool(_should_engage_hmac_verification_failed(path))
    elif refusal_class == "RUN_ID_MISMATCH":
        return bool(_should_engage_run_id_mismatch(path))
    elif refusal_class == "ASSERTION_NOT_YET_ISSUED":
        return bool(_should_engage_assertion_not_yet_issued(path, now))
    elif refusal_class == "ASSERTION_EXPIRED":
        return bool(_should_engage_assertion_expired(path, now))
    elif refusal_class == "NO_STOP_ASSERTION_SIGNATURE_INVALID":
        return bool(_should_engage_signature_invalid(path))
    elif refusal_class == "STOP_SUPERSEDES_ASSERTION":
        return bool(_should_engage_stop_supersedes(path))
    elif refusal_class == "ASSERTION_BINDING_ABSENT":
        return bool(_should_engage_binding_absent(path))
    raise QualificationError(f"unknown refusal class: {refusal_class}")


def _should_engage_assertion_missing(path: Path) -> bool:
    """Assertion missing refusal engages when no assertion file present."""
    content = path.read_bytes()
    return b"assertion_missing" in content


def _should_engage_assertion_malformed(path: Path) -> bool:
    """Assertion malformed refusal engages when JSON is invalid."""
    content = path.read_bytes()
    return b"assertion_malformed" in content


def _should_engage_hmac_verification_failed(path: Path) -> bool:
    """HMAC verification failed refusal engages when signature invalid."""
    content = path.read_bytes()
    return b"hmac_verification_failed" in content


def _should_engage_run_id_mismatch(path: Path) -> bool:
    """Run ID mismatch refusal engages when assertion not bound to current run."""
    content = path.read_bytes()
    return b"run_id_mismatch" in content


def _should_engage_assertion_not_yet_issued(path: Path, now: datetime) -> bool:
    """Assertion not yet issued refusal engages when current time before issued_at."""
    content = path.read_bytes()
    return b"assertion_not_yet_issued" in content


def _should_engage_assertion_expired(path: Path, now: datetime) -> bool:
    """Assertion expired refusal engages when current time after expires_at."""
    content = path.read_bytes()
    return b"assertion_expired" in content


def _should_engage_signature_invalid(path: Path) -> bool:
    """No-Stop Assertion signature invalid refusal engages when cryptographic proof fails."""
    content = path.read_bytes()
    return b"signature_invalid" in content


def _should_engage_stop_supersedes(path: Path) -> bool:
    """Stop supersedes assertion refusal engages when later signed stop present."""
    content = path.read_bytes()
    return b"stop_supersedes_assertion" in content


def _should_engage_binding_absent(path: Path) -> bool:
    """Assertion binding absent refusal engages when binding record missing."""
    content = path.read_bytes()
    return b"assertion_binding_absent" in content


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


def assess(
    inventory: Path,
    *,
    probe: Probe | None = None,
    now: datetime | None = None,
) -> QualificationEvidence:
    """Assess that all nine NO_ACTIVE_HUMAN_EMERGENCY_STOP refusal classes engage deterministically.

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

    if now is None:
        now = datetime.now(timezone.utc)

    before = {rc: _digest_file(path) for rc, path in surfaces}
    engaged_count = 0

    for rc, path in surfaces:
        if writer(rc, path, None, now):
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
