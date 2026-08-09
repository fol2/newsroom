"""Pure Increment 6B1 execution identity and ownership contract values.

These immutable phase-one values grant no grouping, dispatch, lease, worker,
Proposal, Candidate, publication, evidence, egress, or external-effect authority.
A future v20 trusted store and composition root must atomically validate current
Work Item authority before persisting any claim or attempt.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Self

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment6.outcomes import (
    ContractAuthority,
    ContractEffect,
    PrioritySelection,
)
from newsroom.increment6.proposals import FixtureWorkerKind, WorkerAttemptBinding

EXECUTION_BATCH = "EXACT_NO_AUTHORITY_EXECUTION_BATCH"
WORKER_ATTEMPT = "DETERMINISTIC_NO_AUTHORITY_WORKER_ATTEMPT"
WORK_ITEM_LEASE_OWNERSHIP = "CAPABILITY_OWNERSHIP_CLAIM_ONLY"

EXECUTION_BATCH_SCHEMA = "newsroom.increment6.execution-batch.v1"
WORKER_ATTEMPT_SCHEMA = "newsroom.increment6.worker-attempt.v1"
WORK_ITEM_LEASE_SCHEMA = "newsroom.increment6.work-item-lease.v1"

_MAX_BATCH_MEMBERS = 64
_MAX_CANONICAL_BYTES = 262_144
_MAX_CANONICAL_DEPTH = 24
_MAX_CANONICAL_NODES = 16_384
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,255}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class ExecutionContractError(ValueError):
    """An execution contract value is malformed or exceeds its envelope."""


class LeaseLifecycle(StrEnum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


def _token(value: object, field: str) -> str:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise ExecutionContractError(f"{field} must be a bounded token")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ExecutionContractError(f"{field} must be a string")
    return value


def _uuid(value: object, field: str) -> str:
    try:
        parsed = uuid.UUID(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, AttributeError) as exc:
        raise ExecutionContractError(f"{field} must be a canonical UUID") from exc
    if not isinstance(value, str) or str(parsed) != value:
        raise ExecutionContractError(f"{field} must be a canonical UUID")
    return value


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ExecutionContractError(f"{field} must be a canonical SHA-256 digest")
    return value


def _integer(value: object, field: str, *, minimum: int = 1) -> int:
    if type(value) is not int or value < minimum:
        raise ExecutionContractError(f"{field} must be an exact integer")
    return value


def _utc(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ExecutionContractError(f"{field} must be canonical UTC")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ExecutionContractError(f"{field} must be canonical UTC") from exc
    if parsed.tzinfo != UTC or parsed.isoformat().replace("+00:00", "Z") != value:
        raise ExecutionContractError(f"{field} must be canonical UTC")
    return value


def _utc_value(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _exact(value: object, fields: set[str], name: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ExecutionContractError(f"{name} fields differ")
    return value


def _decode(raw: bytes) -> dict[str, object]:
    if not isinstance(raw, bytes) or not raw or len(raw) > _MAX_CANONICAL_BYTES:
        raise ExecutionContractError("canonical input exceeds the execution envelope")

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ExecutionContractError(f"duplicate object name: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    except ExecutionContractError:
        raise
    except (
        UnicodeError,
        json.JSONDecodeError,
        ValueError,
        RecursionError,
        MemoryError,
    ) as exc:
        raise ExecutionContractError("canonical input is invalid UTF-8 JSON") from exc
    pending: list[tuple[object, int]] = [(value, 1)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if depth > _MAX_CANONICAL_DEPTH or nodes > _MAX_CANONICAL_NODES:
            raise ExecutionContractError("canonical input exceeds structural bounds")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif not isinstance(item, (str, int, float, bool, type(None))):
            raise ExecutionContractError(
                "canonical input contains an unsupported value"
            )
    if not isinstance(value, dict):
        raise ExecutionContractError("canonical input must be an object")
    try:
        if canonical_json_bytes(value) != raw:
            raise ExecutionContractError("canonical input bytes differ")
    except (UnicodeError, ValueError, TypeError, RecursionError, MemoryError) as exc:
        if isinstance(exc, ExecutionContractError):
            raise
        raise ExecutionContractError("canonical input cannot be normalised") from exc
    return value


@dataclass(frozen=True, slots=True)
class ExecutionBatchMember:
    work_item_id: str
    work_item_version_id: str
    work_item_version_digest: str
    retrieval_context_id: str
    retrieval_context_digest: str
    priority: PrioritySelection

    def __post_init__(self) -> None:
        _uuid(self.work_item_id, "member work_item_id")
        _uuid(self.work_item_version_id, "member work_item_version_id")
        _digest(self.work_item_version_digest, "member Work Item Version digest")
        _uuid(self.retrieval_context_id, "member retrieval_context_id")
        _digest(self.retrieval_context_digest, "member retrieval digest")
        if not isinstance(self.priority, PrioritySelection):
            raise ExecutionContractError("member priority must be typed")
        if (
            self.priority.work_identity != self.work_item_id
            or self.priority.work_version != self.work_item_version_id
            or self.priority.authority is not ContractAuthority.NONE
            or self.priority.effect is not ContractEffect.NONE
        ):
            raise ExecutionContractError("member priority binding differs")

    def canonical_value(self) -> dict[str, object]:
        return {
            "work_item_id": self.work_item_id,
            "work_item_version_id": self.work_item_version_id,
            "work_item_version_digest": self.work_item_version_digest,
            "retrieval_context_id": self.retrieval_context_id,
            "retrieval_context_digest": self.retrieval_context_digest,
            "priority": self.priority.canonical_value(),
        }

    @classmethod
    def from_value(cls, value: object) -> Self:
        item = _exact(
            value,
            {
                "work_item_id",
                "work_item_version_id",
                "work_item_version_digest",
                "retrieval_context_id",
                "retrieval_context_digest",
                "priority",
            },
            "batch member",
        )
        try:
            priority = PrioritySelection.from_mapping(item["priority"])  # type: ignore[arg-type]
        except Exception as exc:
            raise ExecutionContractError("member priority differs") from exc
        return cls(
            _string(item["work_item_id"], "member work_item_id"),
            _string(item["work_item_version_id"], "member version_id"),
            _string(item["work_item_version_digest"], "member version digest"),
            _string(item["retrieval_context_id"], "member retrieval id"),
            _string(item["retrieval_context_digest"], "member retrieval digest"),
            priority,
        )


@dataclass(frozen=True, slots=True)
class ExecutionBatch:
    batch_id: str
    members: tuple[ExecutionBatchMember, ...]
    schema_identity: str = EXECUTION_BATCH_SCHEMA
    authority: ContractAuthority = ContractAuthority.NONE
    effect: ContractEffect = ContractEffect.NONE

    @classmethod
    def create(cls, members: tuple[ExecutionBatchMember, ...]) -> Self:
        ordered = tuple(sorted(members, key=lambda member: member.work_item_id))
        identity = digest_bytes(
            canonical_json_bytes([member.canonical_value() for member in ordered])
        )
        return cls(
            str(uuid.uuid5(uuid.NAMESPACE_URL, f"{EXECUTION_BATCH_SCHEMA}|{identity}")),
            ordered,
        )

    def __post_init__(self) -> None:
        _uuid(self.batch_id, "batch_id")
        if (
            self.schema_identity != EXECUTION_BATCH_SCHEMA
            or self.authority is not ContractAuthority.NONE
            or self.effect is not ContractEffect.NONE
        ):
            raise ExecutionContractError("Execution Batch claims authority or effect")
        if (
            not isinstance(self.members, tuple)
            or not 1 <= len(self.members) <= _MAX_BATCH_MEMBERS
            or any(
                not isinstance(member, ExecutionBatchMember) for member in self.members
            )
        ):
            raise ExecutionContractError(
                "Execution Batch members exceed the bounded typed envelope"
            )
        if self.members != tuple(
            sorted(self.members, key=lambda member: member.work_item_id)
        ) or len({member.work_item_id for member in self.members}) != len(self.members):
            raise ExecutionContractError(
                "Execution Batch members must be sorted unique per Work Item"
            )
        identity = digest_bytes(
            canonical_json_bytes([member.canonical_value() for member in self.members])
        )
        expected = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"{EXECUTION_BATCH_SCHEMA}|{identity}")
        )
        if (
            self.batch_id != expected
            or len(self.canonical_bytes) > _MAX_CANONICAL_BYTES
        ):
            raise ExecutionContractError("Execution Batch identity or envelope differs")

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_identity": self.schema_identity,
            "authority": self.authority.value,
            "effect": self.effect.value,
            "batch_id": self.batch_id,
            "members": [member.canonical_value() for member in self.members],
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        item = _exact(
            _decode(raw),
            {"schema_identity", "authority", "effect", "batch_id", "members"},
            "Execution Batch",
        )
        if not isinstance(item["members"], list):
            raise ExecutionContractError("Execution Batch members must be an array")
        try:
            authority = ContractAuthority(item["authority"])
            effect = ContractEffect(item["effect"])
        except (TypeError, ValueError) as exc:
            raise ExecutionContractError(
                "Execution Batch authority fields differ"
            ) from exc
        value = cls(
            _string(item["batch_id"], "batch_id"),
            tuple(
                ExecutionBatchMember.from_value(member) for member in item["members"]
            ),
            _string(item["schema_identity"], "batch schema_identity"),
            authority,
            effect,
        )
        if value.canonical_bytes != raw:
            raise ExecutionContractError("Execution Batch bytes differ")
        return value


@dataclass(frozen=True, slots=True)
class WorkerAttempt:
    attempt_id: str
    work_item_id: str
    work_item_version_id: str
    work_item_version_digest: str
    retrieval_context_digest: str
    ordinal: int
    previous_attempt_id: str | None
    worker_kind: FixtureWorkerKind
    worker_version: str
    input_digest: str
    idempotency_key: str
    priority: PrioritySelection
    schema_identity: str = WORKER_ATTEMPT_SCHEMA
    authority: ContractAuthority = ContractAuthority.NONE
    effect: ContractEffect = ContractEffect.NONE

    @classmethod
    def create(
        cls,
        *,
        work_item_id: str,
        work_item_version_id: str,
        work_item_version_digest: str,
        retrieval_context_digest: str,
        ordinal: int,
        worker_kind: FixtureWorkerKind,
        worker_version: str,
        input_digest: str,
        priority: PrioritySelection,
    ) -> Self:
        _integer(ordinal, "attempt ordinal")
        attempt_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{WORKER_ATTEMPT_SCHEMA}|{work_item_id}|{work_item_version_id}|{ordinal}",
            )
        )
        previous = (
            None
            if ordinal == 1
            else str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{WORKER_ATTEMPT_SCHEMA}|{work_item_id}|{work_item_version_id}|{ordinal - 1}",
                )
            )
        )
        return cls(
            attempt_id,
            work_item_id,
            work_item_version_id,
            work_item_version_digest,
            retrieval_context_digest,
            ordinal,
            previous,
            worker_kind,
            worker_version,
            input_digest,
            f"worker-attempt:{attempt_id}",
            priority,
        )

    def __post_init__(self) -> None:
        for value, field in (
            (self.attempt_id, "attempt_id"),
            (self.work_item_id, "work_item_id"),
            (self.work_item_version_id, "work_item_version_id"),
        ):
            _uuid(value, field)
        _digest(self.work_item_version_digest, "Work Item Version digest")
        _digest(self.retrieval_context_digest, "retrieval context digest")
        _digest(self.input_digest, "attempt input digest")
        _integer(self.ordinal, "attempt ordinal")
        expected = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{WORKER_ATTEMPT_SCHEMA}|{self.work_item_id}|{self.work_item_version_id}|{self.ordinal}",
            )
        )
        previous = (
            None
            if self.ordinal == 1
            else str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{WORKER_ATTEMPT_SCHEMA}|{self.work_item_id}|{self.work_item_version_id}|{self.ordinal - 1}",
                )
            )
        )
        if (
            self.attempt_id != expected
            or self.previous_attempt_id != previous
            or self.idempotency_key != f"worker-attempt:{expected}"
        ):
            raise ExecutionContractError(
                "Worker Attempt deterministic identity differs"
            )
        if not isinstance(self.worker_kind, FixtureWorkerKind):
            raise ExecutionContractError("worker kind must be typed")
        _token(self.worker_version, "worker version")
        if (
            not isinstance(self.priority, PrioritySelection)
            or self.priority.work_identity != self.work_item_id
            or self.priority.work_version != self.work_item_version_id
        ):
            raise ExecutionContractError("Worker Attempt priority binding differs")
        if (
            self.schema_identity != WORKER_ATTEMPT_SCHEMA
            or self.authority is not ContractAuthority.NONE
            or self.effect is not ContractEffect.NONE
            or len(self.canonical_bytes) > _MAX_CANONICAL_BYTES
        ):
            raise ExecutionContractError(
                "Worker Attempt claims authority, effect, or excess bytes"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_identity": self.schema_identity,
            "authority": self.authority.value,
            "effect": self.effect.value,
            "attempt_id": self.attempt_id,
            "work_item_id": self.work_item_id,
            "work_item_version_id": self.work_item_version_id,
            "work_item_version_digest": self.work_item_version_digest,
            "retrieval_context_digest": self.retrieval_context_digest,
            "ordinal": self.ordinal,
            "previous_attempt_id": self.previous_attempt_id,
            "worker_kind": self.worker_kind.value,
            "worker_version": self.worker_version,
            "input_digest": self.input_digest,
            "idempotency_key": self.idempotency_key,
            "priority": self.priority.canonical_value(),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def proposal_binding(self) -> WorkerAttemptBinding:
        return WorkerAttemptBinding(
            self.attempt_id,
            self.canonical_digest,
            self.worker_kind,
            self.worker_version,
            self.input_digest,
            self.work_item_version_digest,
            self.retrieval_context_digest,
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        item = _exact(
            _decode(raw),
            {
                "schema_identity",
                "authority",
                "effect",
                "attempt_id",
                "work_item_id",
                "work_item_version_id",
                "work_item_version_digest",
                "retrieval_context_digest",
                "ordinal",
                "previous_attempt_id",
                "worker_kind",
                "worker_version",
                "input_digest",
                "idempotency_key",
                "priority",
            },
            "Worker Attempt",
        )
        try:
            priority = PrioritySelection.from_mapping(item["priority"])  # type: ignore[arg-type]
            worker_kind = FixtureWorkerKind(item["worker_kind"])
            authority = ContractAuthority(item["authority"])
            effect = ContractEffect(item["effect"])
        except Exception as exc:
            raise ExecutionContractError("Worker Attempt typed fields differ") from exc
        value = cls(
            _string(item["attempt_id"], "attempt_id"),
            _string(item["work_item_id"], "attempt work_item_id"),
            _string(item["work_item_version_id"], "attempt version_id"),
            _string(item["work_item_version_digest"], "attempt version digest"),
            _string(item["retrieval_context_digest"], "attempt retrieval digest"),
            _integer(item["ordinal"], "attempt ordinal"),
            None
            if item["previous_attempt_id"] is None
            else _string(item["previous_attempt_id"], "previous_attempt_id"),
            worker_kind,
            _string(item["worker_version"], "worker_version"),
            _string(item["input_digest"], "input_digest"),
            _string(item["idempotency_key"], "idempotency_key"),
            priority,
            _string(item["schema_identity"], "attempt schema_identity"),
            authority,
            effect,
        )
        if value.canonical_bytes != raw:
            raise ExecutionContractError("Worker Attempt bytes differ")
        return value


@dataclass(frozen=True, slots=True)
class WorkItemLease:
    lease_id: str
    work_item_id: str
    work_item_version_id: str
    owner_id: str | None
    capability_digest: str | None
    fence: int
    lifecycle: LeaseLifecycle
    issued_at: str | None
    expires_at: str | None
    schema_identity: str = WORK_ITEM_LEASE_SCHEMA
    authority: ContractAuthority = ContractAuthority.NONE
    effect: ContractEffect = ContractEffect.NONE

    @classmethod
    def pending(cls, work_item_id: str, work_item_version_id: str, fence: int) -> Self:
        lease_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{WORK_ITEM_LEASE_SCHEMA}|{work_item_id}|{work_item_version_id}|{fence}",
            )
        )
        return cls(
            lease_id,
            work_item_id,
            work_item_version_id,
            None,
            None,
            fence,
            LeaseLifecycle.PENDING,
            None,
            None,
        )

    def __post_init__(self) -> None:
        for value, field in (
            (self.lease_id, "lease_id"),
            (self.work_item_id, "lease work_item_id"),
            (self.work_item_version_id, "lease work_item_version_id"),
        ):
            _uuid(value, field)
        _integer(self.fence, "lease fence")
        expected = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{WORK_ITEM_LEASE_SCHEMA}|{self.work_item_id}|{self.work_item_version_id}|{self.fence}",
            )
        )
        if self.lease_id != expected or not isinstance(self.lifecycle, LeaseLifecycle):
            raise ExecutionContractError(
                "Lease deterministic identity or lifecycle differs"
            )
        claimed = self.lifecycle is LeaseLifecycle.CLAIMED
        if claimed:
            _token(self.owner_id, "lease owner")
            _digest(self.capability_digest, "lease capability")
            issued = _utc(self.issued_at, "lease issued_at")
            expires = _utc(self.expires_at, "lease expires_at")
            if _utc_value(expires) <= _utc_value(issued):
                raise ExecutionContractError("lease expiry must follow issue time")
        elif any(
            value is not None
            for value in (
                self.owner_id,
                self.capability_digest,
                self.issued_at,
                self.expires_at,
            )
        ):
            raise ExecutionContractError(
                "non-claimed Lease cannot retain an owner capability"
            )
        if (
            self.schema_identity != WORK_ITEM_LEASE_SCHEMA
            or self.authority is not ContractAuthority.NONE
            or self.effect is not ContractEffect.NONE
        ):
            raise ExecutionContractError("Lease contract claims authority or effect")

    def is_expired_at(self, observed_at: str) -> bool:
        _utc(observed_at, "lease observation time")
        return (
            self.lifecycle is LeaseLifecycle.CLAIMED
            and self.expires_at is not None
            and _utc_value(observed_at) >= _utc_value(self.expires_at)
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_identity": self.schema_identity,
            "authority": self.authority.value,
            "effect": self.effect.value,
            "lease_id": self.lease_id,
            "work_item_id": self.work_item_id,
            "work_item_version_id": self.work_item_version_id,
            "owner_id": self.owner_id,
            "capability_digest": self.capability_digest,
            "fence": self.fence,
            "lifecycle": self.lifecycle.value,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        item = _exact(
            _decode(raw),
            {
                "schema_identity",
                "authority",
                "effect",
                "lease_id",
                "work_item_id",
                "work_item_version_id",
                "owner_id",
                "capability_digest",
                "fence",
                "lifecycle",
                "issued_at",
                "expires_at",
            },
            "Work Item Lease",
        )
        try:
            lifecycle = LeaseLifecycle(item["lifecycle"])
            authority = ContractAuthority(item["authority"])
            effect = ContractEffect(item["effect"])
        except (TypeError, ValueError) as exc:
            raise ExecutionContractError("Lease typed fields differ") from exc
        value = cls(
            _string(item["lease_id"], "lease_id"),
            _string(item["work_item_id"], "lease work_item_id"),
            _string(item["work_item_version_id"], "lease version_id"),
            None if item["owner_id"] is None else _string(item["owner_id"], "owner_id"),
            None
            if item["capability_digest"] is None
            else _string(item["capability_digest"], "capability_digest"),
            _integer(item["fence"], "lease fence"),
            lifecycle,
            None
            if item["issued_at"] is None
            else _string(item["issued_at"], "issued_at"),
            None
            if item["expires_at"] is None
            else _string(item["expires_at"], "expires_at"),
            _string(item["schema_identity"], "lease schema_identity"),
            authority,
            effect,
        )
        if value.canonical_bytes != raw:
            raise ExecutionContractError("Lease bytes differ")
        return value


__all__ = [
    "EXECUTION_BATCH",
    "EXECUTION_BATCH_SCHEMA",
    "WORKER_ATTEMPT",
    "WORKER_ATTEMPT_SCHEMA",
    "WORK_ITEM_LEASE_OWNERSHIP",
    "WORK_ITEM_LEASE_SCHEMA",
    "ExecutionBatch",
    "ExecutionBatchMember",
    "ExecutionContractError",
    "LeaseLifecycle",
    "WorkItemLease",
    "WorkerAttempt",
]
