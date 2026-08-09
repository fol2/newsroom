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

from newsroom.authority.canonical import (
    MAX_SAFE_INTEGER,
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
)
from newsroom.increment6.outcomes import (
    ContractAuthority,
    ContractEffect,
    PrioritySelection,
)
from newsroom.increment6.proposals import FixtureWorkerKind, WorkerAttemptBinding
from newsroom.increment6.scheduling import (
    CapacityAllocationDisposition,
    CapacityItemAllocation,
    ReservedCapacityDecision,
)
from newsroom.increment6.work_items import (
    TriageWorkItemVersion,
)

EXECUTION_BATCH = "EXACT_NO_AUTHORITY_EXECUTION_BATCH"
WORKER_ATTEMPT = "DETERMINISTIC_NO_AUTHORITY_WORKER_ATTEMPT"
WORK_ITEM_LEASE_OWNERSHIP = "CAPABILITY_OWNERSHIP_CLAIM_ONLY"

EXECUTION_BATCH_SCHEMA = "newsroom.increment6.execution-batch.v1"
WORKER_ATTEMPT_SCHEMA = "newsroom.increment6.worker-attempt.v1"
WORK_ITEM_LEASE_SCHEMA = "newsroom.increment6.work-item-lease.v1"

_MAX_BATCH_MEMBERS = 48
_MAX_MEMBER_BYTES = 262_144
_MAX_SCHEDULING_BYTES = 48 * 16_384 + 131_072
_MAX_CANONICAL_BYTES = (
    _MAX_BATCH_MEMBERS * _MAX_MEMBER_BYTES + _MAX_SCHEDULING_BYTES + 131_072
)
_MAX_CANONICAL_DEPTH = 68
_MAX_CANONICAL_NODES = _MAX_CANONICAL_BYTES // 2 + 1
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,255}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class ExecutionContractError(ValueError):
    """An execution contract value is malformed or exceeds its envelope."""


class LeaseLifecycle(StrEnum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class LeaseProgress(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    INTERRUPTED = "INTERRUPTED"


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
    if type(value) is not int or not minimum <= value <= MAX_SAFE_INTEGER:
        raise ExecutionContractError(
            f"{field} must be an exact interoperable bounded integer"
        )
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
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ExecutionContractError("UTC value is malformed") from exc


def _exact(value: object, fields: set[str], name: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != fields:
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

    def bounded_integer(text: str) -> int:
        if len(text.lstrip("-")) > 16:
            raise ExecutionContractError("canonical integer exceeds safe range")
        value = int(text)
        if not -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
            raise ExecutionContractError("canonical integer exceeds safe range")
        return value

    def reject_float(_: str) -> float:
        raise ExecutionContractError("floating-point values are unsupported")

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique,
            parse_int=bounded_integer,
            parse_float=reject_float,
            parse_constant=reject_float,
        )
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
    except (
        CanonicalizationError,
        UnicodeError,
        ValueError,
        TypeError,
        OverflowError,
        RecursionError,
        MemoryError,
    ) as exc:
        if isinstance(exc, ExecutionContractError):
            raise
        raise ExecutionContractError("canonical input cannot be normalised") from exc
    return value


def _canonical(value: object, field: str) -> bytes:
    try:
        result = canonical_json_bytes(value)
    except (
        CanonicalizationError,
        UnicodeError,
        ValueError,
        TypeError,
        OverflowError,
        RecursionError,
        MemoryError,
    ) as exc:
        raise ExecutionContractError(
            f"{field} is not canonically representable"
        ) from exc
    if len(result) > _MAX_CANONICAL_BYTES:
        raise ExecutionContractError(f"{field} exceeds the execution envelope")
    return result


@dataclass(frozen=True, slots=True)
class ExecutionBatchMember:
    work_item_id: str
    work_item_version_id: str
    work_item_version_digest: str
    retrieval_context_id: str
    retrieval_context_digest: str
    priority: PrioritySelection
    work_item_version_bytes: bytes
    scheduling_allocation_digest: str

    @classmethod
    def from_producers(
        cls,
        version: TriageWorkItemVersion,
        allocation: CapacityItemAllocation,
    ) -> Self:
        if (
            type(version) is not TriageWorkItemVersion
            or type(allocation) is not CapacityItemAllocation
        ):
            raise ExecutionContractError("batch member producers must be typed")
        if (
            allocation.disposition is not CapacityAllocationDisposition.GRANTED
            or allocation.item.work_item_id != version.work_item_id
            or allocation.item.work_item_version_id != version.version_id
            or allocation.item.work_item_version_digest != version.canonical_digest
            or allocation.item.priority_selection != version.priority
        ):
            raise ExecutionContractError(
                "batch member differs from its exact scheduling grant"
            )
        retrieval = version.retrieval
        retrieval_id = retrieval.context_id or retrieval.request_id
        retrieval_digest = retrieval.context_digest or retrieval.request_digest
        return cls(
            version.work_item_id,
            version.version_id,
            version.canonical_digest,
            retrieval_id,
            retrieval_digest,
            version.priority,
            version.canonical_bytes,
            digest_bytes(
                _canonical(allocation.canonical_value(), "capacity allocation")
            ),
        )

    def __post_init__(self) -> None:
        _uuid(self.work_item_id, "member work_item_id")
        _uuid(self.work_item_version_id, "member work_item_version_id")
        _digest(self.work_item_version_digest, "member Work Item Version digest")
        _uuid(self.retrieval_context_id, "member retrieval_context_id")
        _digest(self.retrieval_context_digest, "member retrieval digest")
        _digest(self.scheduling_allocation_digest, "member allocation digest")
        if type(self.priority) is not PrioritySelection:
            raise ExecutionContractError("member priority must be typed")
        if not isinstance(self.work_item_version_bytes, bytes):
            raise ExecutionContractError(
                "member Work Item Version bytes must be immutable"
            )
        try:
            version = TriageWorkItemVersion.from_canonical_bytes(
                self.work_item_version_bytes
            )
        except Exception as exc:
            raise ExecutionContractError(
                "member Work Item Version binding differs"
            ) from exc
        retrieval = version.retrieval
        retrieval_id = retrieval.context_id or retrieval.request_id
        retrieval_digest = retrieval.context_digest or retrieval.request_digest
        if (
            version.work_item_id != self.work_item_id
            or version.version_id != self.work_item_version_id
            or version.canonical_digest != self.work_item_version_digest
            or retrieval_id != self.retrieval_context_id
            or retrieval_digest != self.retrieval_context_digest
            or version.priority != self.priority
            or self.priority.work_identity != self.work_item_id
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
            "work_item_version": _decode(self.work_item_version_bytes),
            "scheduling_allocation_digest": self.scheduling_allocation_digest,
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
                "work_item_version",
                "scheduling_allocation_digest",
            },
            "batch member",
        )
        if not isinstance(item["work_item_version"], dict):
            raise ExecutionContractError("member Work Item Version must be an object")
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
            _canonical(item["work_item_version"], "member Work Item Version"),
            _string(item["scheduling_allocation_digest"], "allocation digest"),
        )


@dataclass(frozen=True, slots=True)
class ExecutionBatch:
    batch_id: str
    members: tuple[ExecutionBatchMember, ...]
    scheduling_decision_digest: str
    scheduling_decision_bytes: bytes
    schema_identity: str = EXECUTION_BATCH_SCHEMA
    authority: ContractAuthority = ContractAuthority.NONE
    effect: ContractEffect = ContractEffect.NONE

    @classmethod
    def create(
        cls,
        *,
        scheduling_decision: ReservedCapacityDecision,
        work_item_versions: tuple[TriageWorkItemVersion, ...],
    ) -> Self:
        if type(scheduling_decision) is not ReservedCapacityDecision:
            raise ExecutionContractError(
                "Execution Batch scheduling decision must be typed"
            )
        if (
            type(work_item_versions) is not tuple
            or not 1 <= len(work_item_versions) <= _MAX_BATCH_MEMBERS
            or any(
                type(version) is not TriageWorkItemVersion
                for version in work_item_versions
            )
        ):
            raise ExecutionContractError(
                "Execution Batch Versions exceed the bounded typed envelope"
            )
        versions = {
            (version.work_item_id, version.version_id): version
            for version in work_item_versions
        }
        granted = tuple(
            allocation
            for allocation in scheduling_decision.allocations
            if allocation.disposition is CapacityAllocationDisposition.GRANTED
        )
        try:
            members = tuple(
                ExecutionBatchMember.from_producers(
                    versions[
                        (
                            allocation.item.work_item_id,
                            allocation.item.work_item_version_id,
                        )
                    ],
                    allocation,
                )
                for allocation in granted
            )
        except KeyError as exc:
            raise ExecutionContractError(
                "Execution Batch lacks an exact granted Work Item Version"
            ) from exc
        if len(versions) != len(work_item_versions) or len(versions) != len(members):
            raise ExecutionContractError(
                "Execution Batch Versions differ from exact scheduling grants"
            )
        if (
            type(members) is not tuple
            or not 1 <= len(members) <= _MAX_BATCH_MEMBERS
            or any(type(member) is not ExecutionBatchMember for member in members)
        ):
            raise ExecutionContractError(
                "Execution Batch members exceed the bounded typed envelope"
            )
        ordered = tuple(sorted(members, key=lambda member: member.work_item_id))
        decision_bytes = scheduling_decision.canonical_bytes
        decision_digest = scheduling_decision.decision_digest
        identity = digest_bytes(
            _canonical(
                {
                    "scheduling_decision_digest": decision_digest,
                    "members": [member.canonical_value() for member in ordered],
                },
                "batch identity",
            )
        )
        return cls(
            str(uuid.uuid5(uuid.NAMESPACE_URL, f"{EXECUTION_BATCH_SCHEMA}|{identity}")),
            ordered,
            decision_digest,
            decision_bytes,
        )

    def __post_init__(self) -> None:
        _uuid(self.batch_id, "batch_id")
        _digest(self.scheduling_decision_digest, "scheduling decision digest")
        if not isinstance(self.scheduling_decision_bytes, bytes):
            raise ExecutionContractError("scheduling decision bytes must be immutable")
        try:
            decision = ReservedCapacityDecision.from_canonical_bytes(
                self.scheduling_decision_bytes
            )
        except Exception as exc:
            raise ExecutionContractError("scheduling decision binding differs") from exc
        if decision.decision_digest != self.scheduling_decision_digest:
            raise ExecutionContractError("scheduling decision digest differs")
        if (
            self.schema_identity != EXECUTION_BATCH_SCHEMA
            or self.authority is not ContractAuthority.NONE
            or self.effect is not ContractEffect.NONE
        ):
            raise ExecutionContractError("Execution Batch claims authority or effect")
        if (
            type(self.members) is not tuple
            or not 1 <= len(self.members) <= _MAX_BATCH_MEMBERS
            or any(type(member) is not ExecutionBatchMember for member in self.members)
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
        granted = tuple(
            allocation
            for allocation in decision.allocations
            if allocation.disposition is CapacityAllocationDisposition.GRANTED
        )
        allocation_digests = {
            (
                allocation.item.work_item_id,
                allocation.item.work_item_version_id,
            ): digest_bytes(
                _canonical(allocation.canonical_value(), "capacity allocation")
            )
            for allocation in granted
        }
        if (
            len(allocation_digests) != len(granted)
            or any(
                allocation_digests.get(
                    (member.work_item_id, member.work_item_version_id)
                )
                != member.scheduling_allocation_digest
                for member in self.members
            )
            or len(self.members) != len(granted)
        ):
            raise ExecutionContractError(
                "Execution Batch scheduling grant binding differs"
            )
        identity = digest_bytes(
            _canonical(
                {
                    "scheduling_decision_digest": self.scheduling_decision_digest,
                    "members": [member.canonical_value() for member in self.members],
                },
                "batch identity",
            )
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
            "scheduling_decision_digest": self.scheduling_decision_digest,
            "scheduling_decision": _decode(self.scheduling_decision_bytes),
            "members": [member.canonical_value() for member in self.members],
        }

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical(self.canonical_value(), "Execution Batch")

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
                "batch_id",
                "members",
                "scheduling_decision_digest",
                "scheduling_decision",
            },
            "Execution Batch",
        )
        if not isinstance(item["members"], list):
            raise ExecutionContractError("Execution Batch members must be an array")
        if not isinstance(item["scheduling_decision"], dict):
            raise ExecutionContractError("scheduling decision must be an object")
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
            _string(item["scheduling_decision_digest"], "scheduling decision digest"),
            _canonical(item["scheduling_decision"], "scheduling decision"),
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
    semantic_request_digest: str
    semantic_request_key: str
    ordinal: int
    previous_attempt_id: str | None
    previous_attempt_digest: str | None
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
        member: ExecutionBatchMember,
        ordinal: int,
        previous_attempt: WorkerAttempt | None = None,
        worker_kind: FixtureWorkerKind,
        worker_version: str,
        input_digest: str,
    ) -> Self:
        if type(member) is not ExecutionBatchMember:
            raise ExecutionContractError("Worker Attempt member must be typed")
        work_item_id = member.work_item_id
        work_item_version_id = member.work_item_version_id
        work_item_version_digest = member.work_item_version_digest
        retrieval_context_digest = member.retrieval_context_digest
        priority = member.priority
        _integer(ordinal, "attempt ordinal")
        if not isinstance(worker_kind, FixtureWorkerKind):
            raise ExecutionContractError("worker kind must be typed")
        _token(worker_version, "worker version")
        _digest(input_digest, "attempt input digest")
        if ordinal == 1 and previous_attempt is not None:
            raise ExecutionContractError("first attempt cannot have a predecessor")
        if ordinal > 1 and type(previous_attempt) is not WorkerAttempt:
            raise ExecutionContractError("later attempt requires its exact predecessor")
        request_value = {
            "work_item_id": work_item_id,
            "work_item_version_id": work_item_version_id,
            "work_item_version_digest": work_item_version_digest,
            "retrieval_context_digest": retrieval_context_digest,
            "worker_kind": worker_kind.value,
            "worker_version": worker_version,
            "input_digest": input_digest,
            "priority_digest": digest_bytes(priority.canonical_bytes),
        }
        request_digest = digest_bytes(_canonical(request_value, "semantic request"))
        previous_id = None if previous_attempt is None else previous_attempt.attempt_id
        previous_digest = (
            None if previous_attempt is None else previous_attempt.canonical_digest
        )
        if previous_attempt is not None and (
            previous_attempt.work_item_id != work_item_id
            or previous_attempt.work_item_version_id != work_item_version_id
            or previous_attempt.ordinal + 1 != ordinal
        ):
            raise ExecutionContractError("attempt predecessor binding differs")
        attempt_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{WORKER_ATTEMPT_SCHEMA}|{request_digest}|{ordinal}|{previous_id}",
            )
        )
        return cls(
            attempt_id,
            work_item_id,
            work_item_version_id,
            work_item_version_digest,
            retrieval_context_digest,
            request_digest,
            f"worker-request:{request_digest}",
            ordinal,
            previous_id,
            previous_digest,
            worker_kind,
            worker_version,
            input_digest,
            f"worker-request:{request_digest}",
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
        _digest(self.semantic_request_digest, "semantic request digest")
        _integer(self.ordinal, "attempt ordinal")
        if not isinstance(self.worker_kind, FixtureWorkerKind):
            raise ExecutionContractError("worker kind must be typed")
        if type(self.priority) is not PrioritySelection:
            raise ExecutionContractError("Worker Attempt priority binding differs")
        request_value = {
            "work_item_id": self.work_item_id,
            "work_item_version_id": self.work_item_version_id,
            "work_item_version_digest": self.work_item_version_digest,
            "retrieval_context_digest": self.retrieval_context_digest,
            "worker_kind": self.worker_kind.value,
            "worker_version": self.worker_version,
            "input_digest": self.input_digest,
            "priority_digest": digest_bytes(self.priority.canonical_bytes),
        }
        request_digest = digest_bytes(_canonical(request_value, "semantic request"))
        expected = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{WORKER_ATTEMPT_SCHEMA}|{request_digest}|{self.ordinal}|{self.previous_attempt_id}",
            )
        )
        if (
            (self.ordinal == 1)
            != (
                self.previous_attempt_id is None
                and self.previous_attempt_digest is None
            )
            or (
                self.previous_attempt_id is not None
                and self.previous_attempt_digest is None
            )
            or (
                self.previous_attempt_id is None
                and self.previous_attempt_digest is not None
            )
        ):
            raise ExecutionContractError("Worker Attempt predecessor binding differs")
        if self.previous_attempt_id is not None:
            _uuid(self.previous_attempt_id, "previous_attempt_id")
            _digest(self.previous_attempt_digest, "previous attempt digest")
        if (
            self.attempt_id != expected
            or self.semantic_request_digest != request_digest
            or self.semantic_request_key != f"worker-request:{request_digest}"
            or self.idempotency_key != self.semantic_request_key
        ):
            raise ExecutionContractError(
                "Worker Attempt deterministic identity differs"
            )
        _token(self.worker_version, "worker version")
        if (
            self.priority.work_identity != self.work_item_id
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
            "semantic_request_digest": self.semantic_request_digest,
            "semantic_request_key": self.semantic_request_key,
            "ordinal": self.ordinal,
            "previous_attempt_id": self.previous_attempt_id,
            "previous_attempt_digest": self.previous_attempt_digest,
            "worker_kind": self.worker_kind.value,
            "worker_version": self.worker_version,
            "input_digest": self.input_digest,
            "idempotency_key": self.idempotency_key,
            "priority": self.priority.canonical_value(),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical(self.canonical_value(), "Worker Attempt")

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
                "semantic_request_digest",
                "semantic_request_key",
                "ordinal",
                "previous_attempt_id",
                "previous_attempt_digest",
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
            _string(item["semantic_request_digest"], "semantic request digest"),
            _string(item["semantic_request_key"], "semantic request key"),
            _integer(item["ordinal"], "attempt ordinal"),
            None
            if item["previous_attempt_id"] is None
            else _string(item["previous_attempt_id"], "previous_attempt_id"),
            None
            if item["previous_attempt_digest"] is None
            else _string(item["previous_attempt_digest"], "previous_attempt_digest"),
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
class LeaseProgressEvidence:
    progress: LeaseProgress
    evidence_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.progress, LeaseProgress):
            raise ExecutionContractError("lease progress must be typed")
        _digest(self.evidence_digest, "lease progress evidence digest")

    def canonical_value(self) -> dict[str, object]:
        return {
            "progress": self.progress.value,
            "evidence_digest": self.evidence_digest,
        }

    @classmethod
    def from_value(cls, value: object) -> Self:
        item = _exact(value, {"progress", "evidence_digest"}, "lease progress")
        try:
            progress = LeaseProgress(item["progress"])
        except (TypeError, ValueError) as exc:
            raise ExecutionContractError("lease progress must be typed") from exc
        return cls(progress, _string(item["evidence_digest"], "lease progress digest"))


@dataclass(frozen=True, slots=True)
class LeaseTransitionReceipt:
    transition_id: str
    lease_id: str
    predecessor_digest: str
    from_lifecycle: LeaseLifecycle
    to_lifecycle: LeaseLifecycle
    observed_at: str
    progress: tuple[LeaseProgressEvidence, ...]

    @classmethod
    def create(
        cls,
        *,
        lease_id: str,
        predecessor_digest: str,
        from_lifecycle: LeaseLifecycle,
        to_lifecycle: LeaseLifecycle,
        observed_at: str,
        progress: tuple[LeaseProgressEvidence, ...] = (),
    ) -> Self:
        identity = _canonical(
            {
                "lease_id": lease_id,
                "predecessor_digest": predecessor_digest,
                "from_lifecycle": from_lifecycle.value,
                "to_lifecycle": to_lifecycle.value,
                "observed_at": observed_at,
                "progress": [item.canonical_value() for item in progress],
            },
            "lease transition",
        )
        return cls(
            str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{WORK_ITEM_LEASE_SCHEMA}|transition|{digest_bytes(identity)}",
                )
            ),
            lease_id,
            predecessor_digest,
            from_lifecycle,
            to_lifecycle,
            observed_at,
            progress,
        )

    def __post_init__(self) -> None:
        _uuid(self.transition_id, "lease transition_id")
        _uuid(self.lease_id, "lease transition lease_id")
        _digest(self.predecessor_digest, "lease predecessor digest")
        if not isinstance(self.from_lifecycle, LeaseLifecycle) or not isinstance(
            self.to_lifecycle, LeaseLifecycle
        ):
            raise ExecutionContractError("lease transition lifecycle must be typed")
        _utc(self.observed_at, "lease transition observed_at")
        if (
            not isinstance(self.progress, tuple)
            or len(self.progress) > 32
            or any(type(item) is not LeaseProgressEvidence for item in self.progress)
        ):
            raise ExecutionContractError(
                "lease progress evidence must be bounded and typed"
            )
        identity = _canonical(
            {
                "lease_id": self.lease_id,
                "predecessor_digest": self.predecessor_digest,
                "from_lifecycle": self.from_lifecycle.value,
                "to_lifecycle": self.to_lifecycle.value,
                "observed_at": self.observed_at,
                "progress": [item.canonical_value() for item in self.progress],
            },
            "lease transition",
        )
        expected = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{WORK_ITEM_LEASE_SCHEMA}|transition|{digest_bytes(identity)}",
            )
        )
        if self.transition_id != expected:
            raise ExecutionContractError("lease transition identity differs")

    def canonical_value(self) -> dict[str, object]:
        return {
            "transition_id": self.transition_id,
            "lease_id": self.lease_id,
            "predecessor_digest": self.predecessor_digest,
            "from_lifecycle": self.from_lifecycle.value,
            "to_lifecycle": self.to_lifecycle.value,
            "observed_at": self.observed_at,
            "progress": [item.canonical_value() for item in self.progress],
        }

    @classmethod
    def from_value(cls, value: object) -> Self:
        item = _exact(
            value,
            {
                "transition_id",
                "lease_id",
                "predecessor_digest",
                "from_lifecycle",
                "to_lifecycle",
                "observed_at",
                "progress",
            },
            "lease transition",
        )
        if not isinstance(item["progress"], list):
            raise ExecutionContractError("lease progress must be an array")
        try:
            source = LeaseLifecycle(item["from_lifecycle"])
            target = LeaseLifecycle(item["to_lifecycle"])
        except (TypeError, ValueError) as exc:
            raise ExecutionContractError(
                "lease transition lifecycle must be typed"
            ) from exc
        return cls(
            _string(item["transition_id"], "lease transition_id"),
            _string(item["lease_id"], "lease transition lease_id"),
            _string(item["predecessor_digest"], "lease predecessor digest"),
            source,
            target,
            _string(item["observed_at"], "lease transition observed_at"),
            tuple(
                LeaseProgressEvidence.from_value(entry) for entry in item["progress"]
            ),
        )


@dataclass(frozen=True, slots=True)
class WorkItemLease:
    lease_id: str
    attempt_id: str
    work_item_id: str
    work_item_version_id: str
    work_item_version_digest: str
    owner_id: str
    owner_profile_digest: str
    capability_digest: str
    fence: int
    lifecycle: LeaseLifecycle
    issued_at: str | None
    expires_at: str | None
    transition: LeaseTransitionReceipt | None
    schema_identity: str = WORK_ITEM_LEASE_SCHEMA
    authority: ContractAuthority = ContractAuthority.NONE
    effect: ContractEffect = ContractEffect.NONE

    @classmethod
    def pending(
        cls,
        *,
        attempt: WorkerAttempt,
        owner_id: str,
        owner_profile_digest: str,
        capability_digest: str,
        fence: int,
    ) -> Self:
        if type(attempt) is not WorkerAttempt:
            raise ExecutionContractError("lease attempt must be typed")
        _integer(fence, "lease fence")
        values = (
            attempt.attempt_id,
            attempt.work_item_id,
            attempt.work_item_version_id,
            attempt.work_item_version_digest,
            owner_id,
            owner_profile_digest,
            capability_digest,
            fence,
        )
        lease_id = cls._identity(*values)
        return cls(lease_id, *values, LeaseLifecycle.PENDING, None, None, None)

    @staticmethod
    def _identity(
        attempt_id: str,
        work_item_id: str,
        work_item_version_id: str,
        work_item_version_digest: str,
        owner_id: str,
        owner_profile_digest: str,
        capability_digest: str,
        fence: int,
    ) -> str:
        value = {
            "attempt_id": attempt_id,
            "work_item_id": work_item_id,
            "work_item_version_id": work_item_version_id,
            "work_item_version_digest": work_item_version_digest,
            "owner_id": owner_id,
            "owner_profile_digest": owner_profile_digest,
            "capability_digest": capability_digest,
            "fence": fence,
        }
        return str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{WORK_ITEM_LEASE_SCHEMA}|{digest_bytes(_canonical(value, 'lease identity'))}",
            )
        )

    def __post_init__(self) -> None:
        for value, field in (
            (self.lease_id, "lease_id"),
            (self.attempt_id, "lease attempt_id"),
            (self.work_item_id, "lease work_item_id"),
            (self.work_item_version_id, "lease work_item_version_id"),
        ):
            _uuid(value, field)
        _digest(self.work_item_version_digest, "lease Work Item Version digest")
        _token(self.owner_id, "lease owner")
        _digest(self.owner_profile_digest, "lease owner profile digest")
        _digest(self.capability_digest, "lease capability")
        _integer(self.fence, "lease fence")
        expected = self._identity(
            self.attempt_id,
            self.work_item_id,
            self.work_item_version_id,
            self.work_item_version_digest,
            self.owner_id,
            self.owner_profile_digest,
            self.capability_digest,
            self.fence,
        )
        if self.lease_id != expected or not isinstance(self.lifecycle, LeaseLifecycle):
            raise ExecutionContractError(
                "Lease deterministic identity or lifecycle differs"
            )
        if self.lifecycle is LeaseLifecycle.PENDING:
            if (
                self.issued_at is not None
                or self.expires_at is not None
                or self.transition is not None
            ):
                raise ExecutionContractError(
                    "pending Lease cannot contain acquisition or transition evidence"
                )
        else:
            issued = _utc(self.issued_at, "lease issued_at")
            expires = _utc(self.expires_at, "lease expires_at")
            if _utc_value(expires) <= _utc_value(issued):
                raise ExecutionContractError("lease expiry must follow issue time")
            if type(self.transition) is not LeaseTransitionReceipt:
                raise ExecutionContractError(
                    "Lease lifecycle requires a typed transition receipt"
                )
            source = (
                LeaseLifecycle.PENDING
                if self.lifecycle is LeaseLifecycle.CLAIMED
                else LeaseLifecycle.CLAIMED
            )
            if (
                self.transition.lease_id != self.lease_id
                or self.transition.from_lifecycle is not source
                or self.transition.to_lifecycle is not self.lifecycle
            ):
                raise ExecutionContractError("Lease transition predecessor differs")
            observed = _utc_value(self.transition.observed_at)
            if self.lifecycle is LeaseLifecycle.CLAIMED and observed != _utc_value(
                issued
            ):
                raise ExecutionContractError(
                    "Lease acquisition transition time differs"
                )
            if self.lifecycle is LeaseLifecycle.RELEASED and not (
                _utc_value(issued) <= observed < _utc_value(expires)
            ):
                raise ExecutionContractError("Lease release transition time differs")
            if self.lifecycle is LeaseLifecycle.EXPIRED and observed < _utc_value(
                expires
            ):
                raise ExecutionContractError("Lease expiry transition time differs")
        if (
            self.schema_identity != WORK_ITEM_LEASE_SCHEMA
            or self.authority is not ContractAuthority.NONE
            or self.effect is not ContractEffect.NONE
        ):
            raise ExecutionContractError("Lease contract claims authority or effect")
        _ = self.canonical_bytes

    def claim(self, *, issued_at: str, expires_at: str) -> Self:
        if self.lifecycle is not LeaseLifecycle.PENDING:
            raise ExecutionContractError("only a pending Lease can be claimed")
        _utc(issued_at, "lease issued_at")
        _utc(expires_at, "lease expires_at")
        if _utc_value(expires_at) <= _utc_value(issued_at):
            raise ExecutionContractError("lease expiry must follow issue time")
        receipt = LeaseTransitionReceipt.create(
            lease_id=self.lease_id,
            predecessor_digest=self.canonical_digest,
            from_lifecycle=LeaseLifecycle.PENDING,
            to_lifecycle=LeaseLifecycle.CLAIMED,
            observed_at=issued_at,
        )
        return self._with(LeaseLifecycle.CLAIMED, issued_at, expires_at, receipt)

    def release(
        self, *, observed_at: str, progress: tuple[LeaseProgressEvidence, ...] = ()
    ) -> Self:
        if self.is_expired_at(observed_at):
            raise ExecutionContractError(
                "Lease at or beyond expiry must use the expired transition"
            )
        return self._finish(LeaseLifecycle.RELEASED, observed_at, progress)

    def expire(
        self, *, observed_at: str, progress: tuple[LeaseProgressEvidence, ...] = ()
    ) -> Self:
        if not self.is_expired_at(observed_at):
            raise ExecutionContractError("Lease has not reached its expiry boundary")
        return self._finish(LeaseLifecycle.EXPIRED, observed_at, progress)

    def _finish(
        self,
        lifecycle: LeaseLifecycle,
        observed_at: str,
        progress: tuple[LeaseProgressEvidence, ...],
    ) -> Self:
        if self.lifecycle is not LeaseLifecycle.CLAIMED:
            raise ExecutionContractError("only a claimed Lease can become terminal")
        _utc(observed_at, "lease transition observed_at")
        if self.issued_at is None or _utc_value(observed_at) < _utc_value(
            self.issued_at
        ):
            raise ExecutionContractError(
                "Lease transition cannot precede acquisition time"
            )
        receipt = LeaseTransitionReceipt.create(
            lease_id=self.lease_id,
            predecessor_digest=self.canonical_digest,
            from_lifecycle=LeaseLifecycle.CLAIMED,
            to_lifecycle=lifecycle,
            observed_at=observed_at,
            progress=progress,
        )
        return self._with(lifecycle, self.issued_at, self.expires_at, receipt)

    def _with(
        self,
        lifecycle: LeaseLifecycle,
        issued_at: str | None,
        expires_at: str | None,
        transition: LeaseTransitionReceipt,
    ) -> Self:
        return WorkItemLease(
            self.lease_id,
            self.attempt_id,
            self.work_item_id,
            self.work_item_version_id,
            self.work_item_version_digest,
            self.owner_id,
            self.owner_profile_digest,
            self.capability_digest,
            self.fence,
            lifecycle,
            issued_at,
            expires_at,
            transition,
            self.schema_identity,
            self.authority,
            self.effect,
        )

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
            "attempt_id": self.attempt_id,
            "work_item_id": self.work_item_id,
            "work_item_version_id": self.work_item_version_id,
            "work_item_version_digest": self.work_item_version_digest,
            "owner_id": self.owner_id,
            "owner_profile_digest": self.owner_profile_digest,
            "capability_digest": self.capability_digest,
            "fence": self.fence,
            "lifecycle": self.lifecycle.value,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "transition": None
            if self.transition is None
            else self.transition.canonical_value(),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical(self.canonical_value(), "Work Item Lease")

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        fields = {
            "schema_identity",
            "authority",
            "effect",
            "lease_id",
            "attempt_id",
            "work_item_id",
            "work_item_version_id",
            "work_item_version_digest",
            "owner_id",
            "owner_profile_digest",
            "capability_digest",
            "fence",
            "lifecycle",
            "issued_at",
            "expires_at",
            "transition",
        }
        item = _exact(_decode(raw), fields, "Work Item Lease")
        try:
            lifecycle = LeaseLifecycle(item["lifecycle"])
            authority = ContractAuthority(item["authority"])
            effect = ContractEffect(item["effect"])
        except (TypeError, ValueError) as exc:
            raise ExecutionContractError("Lease typed fields differ") from exc
        value = cls(
            _string(item["lease_id"], "lease_id"),
            _string(item["attempt_id"], "lease attempt_id"),
            _string(item["work_item_id"], "lease work_item_id"),
            _string(item["work_item_version_id"], "lease version_id"),
            _string(item["work_item_version_digest"], "lease version digest"),
            _string(item["owner_id"], "owner_id"),
            _string(item["owner_profile_digest"], "owner_profile_digest"),
            _string(item["capability_digest"], "capability_digest"),
            _integer(item["fence"], "lease fence"),
            lifecycle,
            None
            if item["issued_at"] is None
            else _string(item["issued_at"], "issued_at"),
            None
            if item["expires_at"] is None
            else _string(item["expires_at"], "expires_at"),
            None
            if item["transition"] is None
            else LeaseTransitionReceipt.from_value(item["transition"]),
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
    "LeaseProgress",
    "LeaseProgressEvidence",
    "LeaseTransitionReceipt",
    "WorkItemLease",
    "WorkerAttempt",
]
