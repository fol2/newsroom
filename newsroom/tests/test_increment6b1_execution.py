from __future__ import annotations

import json
import uuid
from dataclasses import replace

import pytest

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.increment6.execution import (
    EXECUTION_BATCH,
    EXECUTION_BATCH_SCHEMA,
    WORK_ITEM_LEASE_OWNERSHIP,
    WORK_ITEM_LEASE_SCHEMA,
    WORKER_ATTEMPT,
    WORKER_ATTEMPT_SCHEMA,
    ExecutionBatch,
    ExecutionBatchMember,
    ExecutionContractError,
    LeaseLifecycle,
    WorkerAttempt,
    WorkItemLease,
)
from newsroom.increment6.outcomes import (
    PriorityLane,
    PrioritySelection,
    ReasonReference,
)
from newsroom.increment6.proposals import FixtureWorkerKind, WorkerAttemptBinding


def _id(number: int) -> str:
    return str(uuid.UUID(f"00000000-0000-4000-8000-{number:012d}"))


def _digest(number: int) -> str:
    return "sha256:" + f"{number:064x}"


def _priority(work_item_id: str, version_id: str) -> PrioritySelection:
    return PrioritySelection(
        work_item_id,
        version_id,
        PriorityLane.ROUTINE,
        (ReasonReference("fixture", "execution"),),
    )


def _member(number: int) -> ExecutionBatchMember:
    work_item_id = _id(number)
    version_id = _id(number + 100)
    return ExecutionBatchMember(
        work_item_id,
        version_id,
        _digest(number),
        _id(number + 200),
        _digest(number + 1),
        _priority(work_item_id, version_id),
    )


def _attempt(ordinal: int = 1) -> WorkerAttempt:
    member = _member(1)
    return WorkerAttempt.create(
        work_item_id=member.work_item_id,
        work_item_version_id=member.work_item_version_id,
        work_item_version_digest=member.work_item_version_digest,
        retrieval_context_digest=member.retrieval_context_digest,
        ordinal=ordinal,
        worker_kind=FixtureWorkerKind.REPLAY,
        worker_version="fixture-v1",
        input_digest=_digest(999),
        priority=member.priority,
    )


def test_exact_allocated_constants_and_no_authority_wire_values() -> None:
    assert EXECUTION_BATCH == "EXACT_NO_AUTHORITY_EXECUTION_BATCH"
    assert WORKER_ATTEMPT == "DETERMINISTIC_NO_AUTHORITY_WORKER_ATTEMPT"
    assert WORK_ITEM_LEASE_OWNERSHIP == "CAPABILITY_OWNERSHIP_CLAIM_ONLY"
    assert EXECUTION_BATCH_SCHEMA == "newsroom.increment6.execution-batch.v1"
    assert WORKER_ATTEMPT_SCHEMA == "newsroom.increment6.worker-attempt.v1"
    assert WORK_ITEM_LEASE_SCHEMA == "newsroom.increment6.work-item-lease.v1"


def test_batch_identity_is_permutation_invariant_and_members_are_exact_per_item() -> (
    None
):
    first, second = _member(1), _member(2)
    a = ExecutionBatch.create((first, second))
    b = ExecutionBatch.create((second, first))
    assert a == b
    assert ExecutionBatch.from_canonical_bytes(a.canonical_bytes) == a
    assert a.canonical_value()["authority"] == "NONE"
    assert a.canonical_value()["effect"] == "NONE"
    with pytest.raises(ExecutionContractError, match="sorted unique"):
        replace(a, members=(first, first))
    changed = replace(first, retrieval_context_digest=_digest(55))
    assert ExecutionBatch.create((changed, second)).batch_id != a.batch_id
    maximum = ExecutionBatch.create(tuple(_member(index) for index in range(1, 65)))
    assert len(maximum.members) == 64
    with pytest.raises(ExecutionContractError, match="bounded"):
        ExecutionBatch.create(tuple(_member(index) for index in range(1, 66)))


def test_attempt_identity_retry_predecessor_and_proposal_binding() -> None:
    first = _attempt()
    second = _attempt(2)
    assert second.previous_attempt_id == first.attempt_id
    assert second.attempt_id != first.attempt_id
    assert second.idempotency_key == f"worker-attempt:{second.attempt_id}"
    assert WorkerAttempt.from_canonical_bytes(second.canonical_bytes) == second
    assert second.proposal_binding == WorkerAttemptBinding(
        second.attempt_id,
        second.canonical_digest,
        second.worker_kind,
        second.worker_version,
        second.input_digest,
        second.work_item_version_digest,
        second.retrieval_context_digest,
    )
    with pytest.raises(ExecutionContractError, match="deterministic"):
        replace(second, previous_attempt_id=_id(888))
    with pytest.raises(ExecutionContractError, match="exact integer"):
        replace(second, ordinal=True)


def test_lease_represents_capability_fence_lifecycle_and_expiry_without_authority() -> (
    None
):
    pending = WorkItemLease.pending(_id(1), _id(101), 1)
    assert pending.lifecycle is LeaseLifecycle.PENDING
    lease = replace(
        pending,
        owner_id="worker:fixture",
        capability_digest=_digest(4),
        lifecycle=LeaseLifecycle.CLAIMED,
        issued_at="2042-03-12T10:00:00Z",
        expires_at="2042-03-12T10:05:00Z",
    )
    assert lease.is_expired_at("2042-03-12T10:04:59Z") is False
    assert lease.is_expired_at("2042-03-12T10:05:00Z") is True
    assert WorkItemLease.from_canonical_bytes(lease.canonical_bytes) == lease
    assert lease.canonical_value()["authority"] == "NONE"
    with pytest.raises(ExecutionContractError, match="owner capability"):
        replace(lease, lifecycle=LeaseLifecycle.RELEASED)
    with pytest.raises(ExecutionContractError, match="expiry"):
        replace(lease, expires_at=lease.issued_at)
    with pytest.raises(ExecutionContractError, match="exact integer"):
        replace(pending, fence=True)


def test_parser_rejects_duplicate_unknown_enum_bool_depth_size_and_large_integer() -> (
    None
):
    batch = ExecutionBatch.create((_member(1),))
    with pytest.raises(ExecutionContractError, match="duplicate"):
        ExecutionBatch.from_canonical_bytes(b'{"a":1,"a":2}')
    value = json.loads(batch.canonical_bytes)
    value["unknown"] = True
    with pytest.raises(ExecutionContractError, match="fields"):
        ExecutionBatch.from_canonical_bytes(canonical_json_bytes(value))
    deep = b'{"a":' * 30 + b"null" + b"}" * 30
    with pytest.raises(ExecutionContractError, match="structural"):
        ExecutionBatch.from_canonical_bytes(deep)
    with pytest.raises(ExecutionContractError, match="envelope"):
        ExecutionBatch.from_canonical_bytes(b"{" + b" " * 262_144 + b"}")
    huge = b'{"a":' + b"9" * 5000 + b"}"
    with pytest.raises(ExecutionContractError, match="invalid"):
        ExecutionBatch.from_canonical_bytes(huge)

    lease = WorkItemLease.pending(_id(1), _id(101), 1)
    lease_value = json.loads(lease.canonical_bytes)
    lease_value["lifecycle"] = "UNKNOWN"
    with pytest.raises(ExecutionContractError, match="typed"):
        WorkItemLease.from_canonical_bytes(canonical_json_bytes(lease_value))
    lease_value = json.loads(lease.canonical_bytes)
    lease_value["fence"] = True
    with pytest.raises(ExecutionContractError, match="exact integer"):
        WorkItemLease.from_canonical_bytes(canonical_json_bytes(lease_value))
    attempt_value = json.loads(_attempt().canonical_bytes)
    attempt_value["worker_version"] = 1
    with pytest.raises(ExecutionContractError, match="string"):
        WorkerAttempt.from_canonical_bytes(canonical_json_bytes(attempt_value))


def test_parser_normalises_lone_surrogate_and_constructed_nested_failures() -> None:
    with pytest.raises(ExecutionContractError):
        ExecutionBatch.from_canonical_bytes(b'{"batch_id":"\\ud800"}')
    member = _member(1).canonical_value()
    assert isinstance(member["priority"], dict)
    member["priority"] = dict(member["priority"])
    member["priority"]["lane"] = "UNKNOWN"
    batch = ExecutionBatch.create((_member(1),)).canonical_value()
    batch["members"] = [member]
    with pytest.raises(ExecutionContractError, match="priority"):
        ExecutionBatch.from_canonical_bytes(canonical_json_bytes(batch))
