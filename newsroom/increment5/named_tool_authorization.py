"""Deterministic local authorization gate for Increment 5C named tools.

Authorization here proves only exact caller, purpose, scope and request mechanics.
It never executes a retrieval branch, hydrates authority bytes, checks a
Candidate collision, grants operational/production/publication authority or
satisfies the complete DOPS-026/DOPS-067 boundaries reserved for 5E.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Callable, Mapping, Sequence

from newsroom.increment5.named_tool_contracts import (
    NAMED_TOOL_CONTRACT_DIGEST,
    NamedToolContractError,
    NamedToolId,
    NamedToolPurpose,
    NamedToolRequest,
    PERMITTED_PURPOSES,
    ToolScope,
)


_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}\Z")
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


class NamedToolAuthorizationError(RuntimeError):
    """The local authorization registry or immutable receipt journal failed."""


class NamedToolGateOutcome(StrEnum):
    AUTHORIZED = "AUTHORIZED"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    STALE = "STALE"


class NamedToolGateReason(StrEnum):
    GRANT_UNKNOWN = "GRANT_UNKNOWN"
    ACTOR_MISMATCH = "ACTOR_MISMATCH"
    PRINCIPAL_MISMATCH = "PRINCIPAL_MISMATCH"
    TOOL_MISMATCH = "TOOL_MISMATCH"
    PURPOSE_MISMATCH = "PURPOSE_MISMATCH"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    GRANT_NOT_YET_VALID = "GRANT_NOT_YET_VALID"
    GRANT_EXPIRED = "GRANT_EXPIRED"
    POLICY_ID_MISMATCH = "POLICY_ID_MISMATCH"
    POLICY_DIGEST_MISMATCH = "POLICY_DIGEST_MISMATCH"
    CONTRACT_MISMATCH = "CONTRACT_MISMATCH"
    PROFILE_MISMATCH = "PROFILE_MISMATCH"
    GENERATION_MISMATCH = "GENERATION_MISMATCH"


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise NamedToolContractError("authorization value is not canonical JSON") from exc


def _digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _require_token(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _TOKEN_RE.fullmatch(value) is None:
        raise NamedToolContractError(f"{field} must be a bounded canonical token")
    return value


def _require_digest(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise NamedToolContractError(f"{field} must be a canonical SHA-256 digest")
    return value


def _parse_utc(value: str, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise NamedToolContractError(f"{field} must be a UTC timestamp")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise NamedToolContractError(
            f"{field} must be canonical second-resolution UTC"
        ) from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise NamedToolContractError(
            f"{field} must be canonical second-resolution UTC"
        )
    return parsed


@dataclass(frozen=True, slots=True)
class NamedToolAuthorizationGrant:
    grant_id: str
    actor_id: str
    authenticated_principal_digest: str
    tool_id: NamedToolId
    purposes: tuple[NamedToolPurpose, ...]
    scope: ToolScope
    valid_from: str
    valid_to: str
    policy_id: str
    policy_digest: str
    contract_digest: str
    profile_id: str
    generation_id: str
    grant_digest: str

    def __post_init__(self) -> None:
        _require_token(self.grant_id, field="named_tool_grant_id")
        _require_token(self.actor_id, field="named_tool_grant_actor")
        _require_digest(
            self.authenticated_principal_digest,
            field="named_tool_grant_principal_digest",
        )
        if not isinstance(self.tool_id, NamedToolId):
            raise NamedToolContractError("grant tool_id must be typed")
        if not self.purposes or not all(
            isinstance(purpose, NamedToolPurpose) for purpose in self.purposes
        ):
            raise NamedToolContractError("grant purposes must be typed and non-empty")
        purpose_values = tuple(purpose.value for purpose in self.purposes)
        if purpose_values != tuple(sorted(set(purpose_values))):
            raise NamedToolContractError("grant purposes must be sorted and unique")
        if not set(self.purposes).issubset(PERMITTED_PURPOSES[self.tool_id]):
            raise NamedToolContractError("grant contains a purpose invalid for its tool")
        if not isinstance(self.scope, ToolScope):
            raise NamedToolContractError("grant scope must be typed")
        start = _parse_utc(self.valid_from, field="grant_valid_from")
        end = _parse_utc(self.valid_to, field="grant_valid_to")
        if start >= end:
            raise NamedToolContractError("grant validity window must be increasing")
        _require_token(self.policy_id, field="grant_policy_id")
        _require_digest(self.policy_digest, field="grant_policy_digest")
        _require_digest(self.contract_digest, field="grant_contract_digest")
        _require_token(self.profile_id, field="grant_profile_id")
        _require_token(self.generation_id, field="grant_generation_id")
        _require_digest(self.grant_digest, field="grant_digest")
        expected = _digest_bytes(_canonical_json_bytes(self.unsigned_value()))
        if self.grant_digest != expected:
            raise NamedToolContractError("grant digest does not match canonical bytes")

    def unsigned_value(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.increment5.named-tool-grant.v1",
            "grant_id": self.grant_id,
            "actor_id": self.actor_id,
            "authenticated_principal_digest": self.authenticated_principal_digest,
            "tool_id": self.tool_id.value,
            "purposes": [purpose.value for purpose in self.purposes],
            "scope": self.scope.canonical_value(),
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "policy_id": self.policy_id,
            "policy_digest": self.policy_digest,
            "contract_digest": self.contract_digest,
            "profile_id": self.profile_id,
            "generation_id": self.generation_id,
        }

    def canonical_value(self) -> dict[str, object]:
        return {**self.unsigned_value(), "grant_digest": self.grant_digest}

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.canonical_value())

    @classmethod
    def create(
        cls,
        *,
        grant_id: str,
        actor_id: str,
        authenticated_principal_digest: str,
        tool_id: NamedToolId,
        purposes: Sequence[NamedToolPurpose],
        scope: ToolScope,
        valid_from: str,
        valid_to: str,
        policy_id: str,
        policy_digest: str,
        profile_id: str,
        generation_id: str,
        contract_digest: str = NAMED_TOOL_CONTRACT_DIGEST,
    ) -> "NamedToolAuthorizationGrant":
        sorted_purposes = tuple(sorted(set(purposes), key=lambda item: item.value))
        unsigned = {
            "schema_version": "newsroom.increment5.named-tool-grant.v1",
            "grant_id": grant_id,
            "actor_id": actor_id,
            "authenticated_principal_digest": authenticated_principal_digest,
            "tool_id": tool_id.value,
            "purposes": [purpose.value for purpose in sorted_purposes],
            "scope": scope.canonical_value(),
            "valid_from": valid_from,
            "valid_to": valid_to,
            "policy_id": policy_id,
            "policy_digest": policy_digest,
            "contract_digest": contract_digest,
            "profile_id": profile_id,
            "generation_id": generation_id,
        }
        return cls(
            grant_id=grant_id,
            actor_id=actor_id,
            authenticated_principal_digest=authenticated_principal_digest,
            tool_id=tool_id,
            purposes=sorted_purposes,
            scope=scope,
            valid_from=valid_from,
            valid_to=valid_to,
            policy_id=policy_id,
            policy_digest=policy_digest,
            contract_digest=contract_digest,
            profile_id=profile_id,
            generation_id=generation_id,
            grant_digest=_digest_bytes(_canonical_json_bytes(unsigned)),
        )


class NamedToolGrantRegistry:
    """Immutable in-memory registry of exact reviewed local grants."""

    def __init__(self, grants: Sequence[NamedToolAuthorizationGrant]) -> None:
        if not grants:
            raise NamedToolContractError("grant registry must not be empty")
        if not all(isinstance(grant, NamedToolAuthorizationGrant) for grant in grants):
            raise NamedToolContractError("grant registry entries must be typed")
        identities = [grant.grant_id for grant in grants]
        if len(identities) != len(set(identities)):
            raise NamedToolContractError("grant registry identities must be unique")
        self._grants: Mapping[str, NamedToolAuthorizationGrant] = {
            grant.grant_id: grant for grant in grants
        }
        self.registry_digest = _digest_bytes(
            _canonical_json_bytes(
                {
                    "schema_version": "newsroom.increment5.named-tool-grant-registry.v1",
                    "grants": [
                        grant.canonical_value()
                        for grant in sorted(grants, key=lambda item: item.grant_id)
                    ],
                }
            )
        )

    def get(self, grant_id: str) -> NamedToolAuthorizationGrant | None:
        return self._grants.get(grant_id)


@dataclass(frozen=True, slots=True)
class NamedToolAuthorizationReceipt:
    decision_id: str
    request_digest: str
    envelope_digest: str
    registry_digest: str
    grant_id: str
    grant_digest: str | None
    tool_id: NamedToolId
    actor_id: str
    authenticated_principal_digest: str
    purpose: NamedToolPurpose
    requested_scope_digest: str
    evaluated_at: str
    outcome: NamedToolGateOutcome
    reason: NamedToolGateReason | None
    local_tool_call_authorized: bool
    branch_executed: bool = False
    authority_read_executed: bool = False
    external_call_count: int = 0
    provider_call_count: int = 0
    model_call_count: int = 0
    embedding_call_count: int = 0
    provider_spend_micros: int = 0
    authority_effect: str = "NONE"
    qualification_authority_granted: bool = False
    production_activation_authorized: bool = False

    def __post_init__(self) -> None:
        try:
            parsed = uuid.UUID(self.decision_id)
        except (ValueError, AttributeError) as exc:
            raise NamedToolContractError("authorization decision_id must be a UUID") from exc
        if str(parsed) != self.decision_id:
            raise NamedToolContractError("authorization decision_id must be canonical")
        for name in (
            "request_digest",
            "envelope_digest",
            "registry_digest",
            "authenticated_principal_digest",
            "requested_scope_digest",
        ):
            _require_digest(getattr(self, name), field=name)
        _require_token(self.grant_id, field="authorization_receipt_grant_id")
        if self.grant_digest is not None:
            _require_digest(self.grant_digest, field="authorization_receipt_grant_digest")
        if not isinstance(self.tool_id, NamedToolId):
            raise NamedToolContractError("authorization receipt tool must be typed")
        _require_token(self.actor_id, field="authorization_receipt_actor")
        if not isinstance(self.purpose, NamedToolPurpose):
            raise NamedToolContractError("authorization receipt purpose must be typed")
        _parse_utc(self.evaluated_at, field="authorization_evaluated_at")
        if not isinstance(self.outcome, NamedToolGateOutcome):
            raise NamedToolContractError("authorization outcome must be typed")
        if self.reason is not None and not isinstance(self.reason, NamedToolGateReason):
            raise NamedToolContractError("authorization reason must be typed")
        if self.outcome is NamedToolGateOutcome.AUTHORIZED:
            if self.reason is not None or not self.local_tool_call_authorized:
                raise NamedToolContractError(
                    "authorized receipt must authorize locally without a failure reason"
                )
            if self.grant_digest is None:
                raise NamedToolContractError("authorized receipt must retain grant digest")
        else:
            if self.reason is None or self.local_tool_call_authorized:
                raise NamedToolContractError(
                    "blocked/stale receipt must retain a reason and no authorization"
                )
        if self.branch_executed or self.authority_read_executed:
            raise NamedToolContractError(
                "5C1 local authorization receipt cannot claim branch or authority execution"
            )
        if any(
            value != 0
            for value in (
                self.external_call_count,
                self.provider_call_count,
                self.model_call_count,
                self.embedding_call_count,
                self.provider_spend_micros,
            )
        ):
            raise NamedToolContractError(
                "5C1 authorization receipt cannot report external work or spend"
            )
        if self.authority_effect != "NONE":
            raise NamedToolContractError("authorization receipt cannot claim authority effect")
        if self.qualification_authority_granted or self.production_activation_authorized:
            raise NamedToolContractError(
                "authorization receipt cannot grant qualification or activation authority"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.increment5.named-tool-authorization-receipt.v1",
            "decision_id": self.decision_id,
            "request_digest": self.request_digest,
            "envelope_digest": self.envelope_digest,
            "registry_digest": self.registry_digest,
            "grant_id": self.grant_id,
            "grant_digest": self.grant_digest,
            "tool_id": self.tool_id.value,
            "actor_id": self.actor_id,
            "authenticated_principal_digest": self.authenticated_principal_digest,
            "purpose": self.purpose.value,
            "requested_scope_digest": self.requested_scope_digest,
            "evaluated_at": self.evaluated_at,
            "outcome": self.outcome.value,
            "reason": None if self.reason is None else self.reason.value,
            "local_tool_call_authorized": self.local_tool_call_authorized,
            "branch_executed": self.branch_executed,
            "authority_read_executed": self.authority_read_executed,
            "external_call_count": self.external_call_count,
            "provider_call_count": self.provider_call_count,
            "model_call_count": self.model_call_count,
            "embedding_call_count": self.embedding_call_count,
            "provider_spend_micros": self.provider_spend_micros,
            "authority_effect": self.authority_effect,
            "qualification_authority_granted": self.qualification_authority_granted,
            "production_activation_authorized": self.production_activation_authorized,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.canonical_value())

    @property
    def receipt_digest(self) -> str:
        return _digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> "NamedToolAuthorizationReceipt":
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise NamedToolAuthorizationError(
                "retained authorization receipt is not JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise NamedToolAuthorizationError(
                "retained authorization receipt root is not an object"
            )
        if payload.pop("schema_version", None) != (
            "newsroom.increment5.named-tool-authorization-receipt.v1"
        ):
            raise NamedToolAuthorizationError(
                "retained authorization receipt schema is not accepted"
            )
        try:
            receipt = cls(
                decision_id=payload["decision_id"],
                request_digest=payload["request_digest"],
                envelope_digest=payload["envelope_digest"],
                registry_digest=payload["registry_digest"],
                grant_id=payload["grant_id"],
                grant_digest=payload["grant_digest"],
                tool_id=NamedToolId(payload["tool_id"]),
                actor_id=payload["actor_id"],
                authenticated_principal_digest=payload[
                    "authenticated_principal_digest"
                ],
                purpose=NamedToolPurpose(payload["purpose"]),
                requested_scope_digest=payload["requested_scope_digest"],
                evaluated_at=payload["evaluated_at"],
                outcome=NamedToolGateOutcome(payload["outcome"]),
                reason=(
                    None
                    if payload["reason"] is None
                    else NamedToolGateReason(payload["reason"])
                ),
                local_tool_call_authorized=payload[
                    "local_tool_call_authorized"
                ],
                branch_executed=payload["branch_executed"],
                authority_read_executed=payload["authority_read_executed"],
                external_call_count=payload["external_call_count"],
                provider_call_count=payload["provider_call_count"],
                model_call_count=payload["model_call_count"],
                embedding_call_count=payload["embedding_call_count"],
                provider_spend_micros=payload["provider_spend_micros"],
                authority_effect=payload["authority_effect"],
                qualification_authority_granted=payload[
                    "qualification_authority_granted"
                ],
                production_activation_authorized=payload[
                    "production_activation_authorized"
                ],
            )
        except (KeyError, TypeError, ValueError, NamedToolContractError) as exc:
            raise NamedToolAuthorizationError(
                "retained authorization receipt is malformed"
            ) from exc
        if receipt.canonical_bytes != raw:
            raise NamedToolAuthorizationError(
                "retained authorization receipt bytes are not canonical"
            )
        return receipt


class NamedToolAuthorizationJournal:
    """Immutable non-authoritative first-writer-wins authorization journal."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialization_lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._initialization_lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS increment5_named_tool_authorization_receipts (
                    idempotency_key TEXT PRIMARY KEY,
                    request_digest TEXT NOT NULL,
                    receipt_bytes BLOB NOT NULL,
                    receipt_digest TEXT NOT NULL
                ) WITHOUT ROWID
                """
            )

    @staticmethod
    def _decode(
        request_digest: str,
        receipt_bytes: bytes,
        receipt_digest: str,
    ) -> NamedToolAuthorizationReceipt:
        if _digest_bytes(receipt_bytes) != receipt_digest:
            raise NamedToolAuthorizationError(
                "retained authorization receipt digest mismatch"
            )
        receipt = NamedToolAuthorizationReceipt.from_canonical_bytes(receipt_bytes)
        if receipt.request_digest != request_digest:
            raise NamedToolAuthorizationError(
                "retained authorization request binding mismatch"
            )
        return receipt

    def _existing(
        self,
        request: NamedToolRequest,
    ) -> NamedToolAuthorizationReceipt | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT request_digest, receipt_bytes, receipt_digest
                    FROM increment5_named_tool_authorization_receipts
                    WHERE idempotency_key = ?
                    """,
                    (request.envelope.idempotency_key,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise NamedToolAuthorizationError(
                "authorization journal read failed"
            ) from exc
        if row is None:
            return None
        if row[0] != request.request_digest:
            raise NamedToolAuthorizationError(
                "authorization idempotency key semantic conflict"
            )
        return self._decode(row[0], bytes(row[1]), row[2])

    def execute(
        self,
        request: NamedToolRequest,
        producer: Callable[[], NamedToolAuthorizationReceipt],
    ) -> NamedToolAuthorizationReceipt:
        existing = self._existing(request)
        if existing is not None:
            return existing
        receipt = producer()
        if receipt.request_digest != request.request_digest:
            raise NamedToolAuthorizationError(
                "produced authorization receipt does not bind request"
            )
        raw = receipt.canonical_bytes
        digest = _digest_bytes(raw)
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT request_digest, receipt_bytes, receipt_digest
                FROM increment5_named_tool_authorization_receipts
                WHERE idempotency_key = ?
                """,
                (request.envelope.idempotency_key,),
            ).fetchone()
            if row is not None:
                connection.execute("ROLLBACK")
                if row[0] != request.request_digest:
                    raise NamedToolAuthorizationError(
                        "authorization idempotency key concurrent semantic conflict"
                    )
                return self._decode(row[0], bytes(row[1]), row[2])
            connection.execute(
                """
                INSERT INTO increment5_named_tool_authorization_receipts (
                    idempotency_key, request_digest, receipt_bytes, receipt_digest
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    request.envelope.idempotency_key,
                    request.request_digest,
                    raw,
                    digest,
                ),
            )
            connection.execute("COMMIT")
        except NamedToolAuthorizationError:
            raise
        except sqlite3.Error as exc:
            if connection is not None:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            raise NamedToolAuthorizationError(
                "authorization journal write failed"
            ) from exc
        finally:
            if connection is not None:
                connection.close()
        return receipt


class NamedToolAuthorizer:
    """Exact local grant matcher with deterministic denial semantics."""

    def __init__(
        self,
        *,
        registry: NamedToolGrantRegistry,
        journal: NamedToolAuthorizationJournal,
    ) -> None:
        self.registry = registry
        self.journal = journal

    def authorize(self, request: NamedToolRequest) -> NamedToolAuthorizationReceipt:
        return self.journal.execute(request, lambda: self._decide(request))

    def _decide(self, request: NamedToolRequest) -> NamedToolAuthorizationReceipt:
        envelope = request.envelope
        grant = self.registry.get(envelope.authorization_grant_id)
        if grant is None:
            return self._receipt(
                request,
                grant=None,
                outcome=NamedToolGateOutcome.POLICY_BLOCKED,
                reason=NamedToolGateReason.GRANT_UNKNOWN,
            )
        checks: tuple[
            tuple[bool, NamedToolGateOutcome, NamedToolGateReason], ...
        ] = (
            (
                grant.actor_id == envelope.actor_id,
                NamedToolGateOutcome.POLICY_BLOCKED,
                NamedToolGateReason.ACTOR_MISMATCH,
            ),
            (
                grant.authenticated_principal_digest
                == envelope.authenticated_principal_digest,
                NamedToolGateOutcome.POLICY_BLOCKED,
                NamedToolGateReason.PRINCIPAL_MISMATCH,
            ),
            (
                grant.tool_id is envelope.tool_id,
                NamedToolGateOutcome.POLICY_BLOCKED,
                NamedToolGateReason.TOOL_MISMATCH,
            ),
            (
                envelope.purpose in grant.purposes,
                NamedToolGateOutcome.POLICY_BLOCKED,
                NamedToolGateReason.PURPOSE_MISMATCH,
            ),
            (
                grant.policy_id == envelope.policy_id,
                NamedToolGateOutcome.POLICY_BLOCKED,
                NamedToolGateReason.POLICY_ID_MISMATCH,
            ),
            (
                grant.policy_digest == envelope.policy_digest,
                NamedToolGateOutcome.POLICY_BLOCKED,
                NamedToolGateReason.POLICY_DIGEST_MISMATCH,
            ),
            (
                grant.contract_digest == envelope.contract_digest,
                NamedToolGateOutcome.POLICY_BLOCKED,
                NamedToolGateReason.CONTRACT_MISMATCH,
            ),
            (
                grant.profile_id == envelope.profile_id,
                NamedToolGateOutcome.POLICY_BLOCKED,
                NamedToolGateReason.PROFILE_MISMATCH,
            ),
            (
                grant.generation_id == envelope.generation_id,
                NamedToolGateOutcome.STALE,
                NamedToolGateReason.GENERATION_MISMATCH,
            ),
            (
                grant.scope.contains(envelope.requested_scope),
                NamedToolGateOutcome.POLICY_BLOCKED,
                NamedToolGateReason.SCOPE_MISMATCH,
            ),
        )
        for passed, outcome, reason in checks:
            if not passed:
                return self._receipt(
                    request,
                    grant=grant,
                    outcome=outcome,
                    reason=reason,
                )
        evaluated = _parse_utc(envelope.serving_time, field="authorization_serving_time")
        if evaluated < _parse_utc(grant.valid_from, field="grant_valid_from"):
            return self._receipt(
                request,
                grant=grant,
                outcome=NamedToolGateOutcome.STALE,
                reason=NamedToolGateReason.GRANT_NOT_YET_VALID,
            )
        if evaluated >= _parse_utc(grant.valid_to, field="grant_valid_to"):
            return self._receipt(
                request,
                grant=grant,
                outcome=NamedToolGateOutcome.STALE,
                reason=NamedToolGateReason.GRANT_EXPIRED,
            )
        return self._receipt(
            request,
            grant=grant,
            outcome=NamedToolGateOutcome.AUTHORIZED,
            reason=None,
        )

    def _receipt(
        self,
        request: NamedToolRequest,
        *,
        grant: NamedToolAuthorizationGrant | None,
        outcome: NamedToolGateOutcome,
        reason: NamedToolGateReason | None,
    ) -> NamedToolAuthorizationReceipt:
        envelope = request.envelope
        grant_digest = None if grant is None else grant.grant_digest
        decision_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                "|".join(
                    (
                        request.request_digest,
                        self.registry.registry_digest,
                        grant_digest or "NO_GRANT",
                        outcome.value,
                        "NONE" if reason is None else reason.value,
                    )
                ),
            )
        )
        return NamedToolAuthorizationReceipt(
            decision_id=decision_id,
            request_digest=request.request_digest,
            envelope_digest=envelope.envelope_digest,
            registry_digest=self.registry.registry_digest,
            grant_id=envelope.authorization_grant_id,
            grant_digest=grant_digest,
            tool_id=envelope.tool_id,
            actor_id=envelope.actor_id,
            authenticated_principal_digest=envelope.authenticated_principal_digest,
            purpose=envelope.purpose,
            requested_scope_digest=envelope.requested_scope.scope_digest,
            evaluated_at=envelope.serving_time,
            outcome=outcome,
            reason=reason,
            local_tool_call_authorized=outcome is NamedToolGateOutcome.AUTHORIZED,
        )


__all__ = [
    "NamedToolAuthorizationError",
    "NamedToolAuthorizationGrant",
    "NamedToolAuthorizationJournal",
    "NamedToolAuthorizationReceipt",
    "NamedToolAuthorizer",
    "NamedToolGateOutcome",
    "NamedToolGateReason",
    "NamedToolGrantRegistry",
]
