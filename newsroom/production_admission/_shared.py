"""Canonical primitives and trust-key records for production admission."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)


class ProductionAdmissionError(ValueError):
    """Production readiness or admission evidence failed closed."""


_GIT_SHA = re.compile(r"[0-9a-f]{40}")


def _git_sha(value: object, field: str) -> str:
    if not isinstance(value, str) or _GIT_SHA.fullmatch(value) is None:
        raise ProductionAdmissionError(f"{field} must be a lowercase Git SHA")
    return value


def _digest(value: object, field: str) -> str:
    try:
        return validate_sha256_digest(value, field=field)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ProductionAdmissionError(f"{field} must be a canonical digest") from exc


def _optional_digest(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _digest(value, field)


def _token(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > 256
        or re.fullmatch(r"[A-Za-z0-9._:/-]+", value) is None
    ):
        raise ProductionAdmissionError(f"{field} must be bounded canonical text")
    return value


def _timestamp(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ProductionAdmissionError(f"{field} must be canonical UTC text")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ProductionAdmissionError(f"{field} must be canonical UTC text") from exc
    if (
        parsed.tzinfo is None
        or parsed.astimezone(UTC).utcoffset() != parsed.utcoffset()
    ):
        raise ProductionAdmissionError(f"{field} must be UTC")
    return value


def _boolean(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise ProductionAdmissionError(f"{field} must be boolean")
    return value


def _nonnegative_integer(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ProductionAdmissionError(f"{field} must be a non-negative integer")
    return value


def _positive_integer(value: object, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise ProductionAdmissionError(f"{field} must be a positive integer")
    return value


def _seal(unsigned: Mapping[str, object], secret: bytes) -> str:
    return (
        "hmac-sha256:"
        + hmac.new(
            secret,
            canonical_json_bytes(unsigned),
            hashlib.sha256,
        ).hexdigest()
    )


def _verify_seal(
    value: Mapping[str, object], *, secret: bytes, field: str = "seal"
) -> None:
    presented = value.get(field)
    if not isinstance(presented, str) or not presented.startswith("hmac-sha256:"):
        raise ProductionAdmissionError(f"{field} is invalid")
    unsigned = {name: item for name, item in value.items() if name != field}
    if not hmac.compare_digest(presented, _seal(unsigned, secret)):
        raise ProductionAdmissionError(f"{field} is invalid")


def _canonical_document(raw: bytes) -> Mapping[str, object]:
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProductionAdmissionError("record is not canonical JSON") from exc
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise ProductionAdmissionError("record is not canonical JSON")
    return MappingProxyType(value)


@dataclass(frozen=True, slots=True)
class FreezeIdentity:
    exact_main_sha: str
    exact_main_tree: str

    def __post_init__(self) -> None:
        _git_sha(self.exact_main_sha, "exact_main_sha")
        _git_sha(self.exact_main_tree, "exact_main_tree")

    def canonical_value(self) -> dict[str, str]:
        return {
            "exact_main_sha": self.exact_main_sha,
            "exact_main_tree": self.exact_main_tree,
        }


class KeyClass(StrEnum):
    EVIDENCE_AUTHORITY = "EVIDENCE_AUTHORITY"
    HUMAN_ACCOUNTABLE_OWNER = "HUMAN_ACCOUNTABLE_OWNER"
    PRODUCTION_OPERATIONAL_ADMISSION = "PRODUCTION_OPERATIONAL_ADMISSION"


class KeyProvenance(StrEnum):
    PRODUCTION_TRUST_ROOT = "PRODUCTION_TRUST_ROOT"
    TEST_FIXTURE = "TEST_FIXTURE"
    SYNTHETIC = "SYNTHETIC"


PRODUCTION_KEY_IDS = {
    KeyClass.EVIDENCE_AUTHORITY: frozenset({"keychain:newsroom-evidence-v1"}),
    KeyClass.HUMAN_ACCOUNTABLE_OWNER: frozenset(
        {"keychain:human-accountable-owner-v1"}
    ),
    KeyClass.PRODUCTION_OPERATIONAL_ADMISSION: frozenset(
        {"keychain:production-operational-admission-v1"}
    ),
}

_INCREMENT9Q_PROVIDER_TERMS_FIXTURE_KEY_DIGEST = (
    "sha256:39d90a5bab66a0c7cee30bf1484840d4c30a733ffda2519198576824cd1c1d95"
)
_INCREMENT9Q_RIGHTS_FIXTURE_KEY_DIGEST = (
    "sha256:1db8400c270e066c8a8b78ef6a2f5c39ee9fa1c7f99f9fb79f695261d2ddb135"
)
_INCREMENT9Q_FIXTURE_KEY_DIGESTS = frozenset(
    {
        _INCREMENT9Q_PROVIDER_TERMS_FIXTURE_KEY_DIGEST,
        _INCREMENT9Q_RIGHTS_FIXTURE_KEY_DIGEST,
    }
)


def production_key_id(key_class: KeyClass) -> str:
    """Return the single configured identifier for a production trust root."""

    if not isinstance(key_class, KeyClass):
        raise ProductionAdmissionError("key_class differs")
    identifiers = PRODUCTION_KEY_IDS[key_class]
    if len(identifiers) != 1:  # pragma: no cover - static configuration guard
        raise ProductionAdmissionError("production trust-root inventory differs")
    return next(iter(identifiers))


@dataclass(frozen=True, slots=True)
class AuthenticationKey:
    """An injected key reference; secret bytes never enter canonical records."""

    key_id: str
    key_class: KeyClass
    provenance: KeyProvenance
    secret: bytes = field(repr=False)

    def __post_init__(self) -> None:
        _token(self.key_id, "key_id")
        if not isinstance(self.key_class, KeyClass):
            raise ProductionAdmissionError("key_class differs")
        if not isinstance(self.provenance, KeyProvenance):
            raise ProductionAdmissionError("key provenance differs")
        if (
            self.provenance is KeyProvenance.PRODUCTION_TRUST_ROOT
            and self.key_id not in PRODUCTION_KEY_IDS[self.key_class]
        ):
            raise ProductionAdmissionError("production trust-root key id differs")
        if not isinstance(self.secret, bytes) or len(self.secret) < 32:
            raise ProductionAdmissionError("authentication key is too short")
        if (
            self.key_class is KeyClass.PRODUCTION_OPERATIONAL_ADMISSION
            and digest_bytes(self.secret) in _INCREMENT9Q_FIXTURE_KEY_DIGESTS
        ):
            raise ProductionAdmissionError(
                "Increment 9Q fixture key is ineligible for production admission"
            )

    def require_production_trust_root(
        self,
        expected_class: KeyClass,
        *,
        expected_key_id: str | None = None,
    ) -> None:
        """Enforce the complete production trust-root invariant in one place."""

        if (
            not isinstance(expected_class, KeyClass)
            or self.key_class is not expected_class
            or self.provenance is not KeyProvenance.PRODUCTION_TRUST_ROOT
            or self.key_id not in PRODUCTION_KEY_IDS[expected_class]
            or (expected_key_id is not None and self.key_id != expected_key_id)
        ):
            raise ProductionAdmissionError("production trust-root key differs")

    @property
    def fingerprint(self) -> str:
        """Return a domain-separated public commitment to this exact key."""

        fingerprint_domain = canonical_json_bytes(
            {
                "schema_version": "newsroom.authentication-key-fingerprint.v1",
                "key_id": self.key_id,
                "key_class": self.key_class.value,
            }
        )
        return (
            "sha256:"
            + hmac.new(
                self.secret,
                fingerprint_domain,
                hashlib.sha256,
            ).hexdigest()
        )
