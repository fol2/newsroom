from __future__ import annotations

import json
import uuid
from dataclasses import replace

import pytest

import newsroom.increment6.execution as execution_contract
from newsroom.authority.canonical import (
    MAX_SAFE_INTEGER,
    canonical_json_bytes,
)
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
    LeaseProgress,
    LeaseProgressEvidence,
    LeaseTransitionReceipt,
    WorkerAttempt,
    WorkItemLease,
)
from newsroom.increment6.outcomes import (
    PriorityLane,
    PrioritySelection,
    ReasonReference,
)
from newsroom.increment6.proposals import FixtureWorkerKind, WorkerAttemptBinding
from newsroom.increment6.scheduling import (
    CapacityPathState,
    CapacityPopulationItem,
    CapacitySnapshot,
    CapacityWorkState,
    ReservedCapacityDecision,
    ReservedCapacityDisposition,
    ReservedCapacityPolicy,
    SchedulingEligibility,
    UrgencyDeadlineInput,
    allocate_reserved_capacity,
    calculate_urgency_deadline,
)
from newsroom.increment6.work_items import (
    ContextLeadBinding,
    TriageWorkItem,
    TriageWorkItemVersion,
)
from newsroom.tests.test_increment6a2_work_items import _decision, _pending
from newsroom.tests.test_increment6b2_scheduling import _policy


def _id(number: int) -> str:
    return str(uuid.UUID(f"00000000-0000-4000-8000-{number:012d}"))


def _digest(number: int) -> str:
    return "sha256:" + f"{number:064x}"


def _priority(work_item_id: str, version_id: str) -> PrioritySelection:
    return PrioritySelection(
        work_item_id,
        version_id,
        PriorityLane.ROUTINE,
        tuple(
            ReasonReference("fixture", f"execution-{index}-" + "x" * 180)
            for index in range(5)
        ),
    )


def _version(number: int) -> TriageWorkItemVersion:
    item = TriageWorkItem.create((_decision(number),))
    version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{item.work_item_id}|1"))
    return TriageWorkItemVersion.create(
        work_item_id=item.work_item_id,
        ordinal=1,
        previous_version_id=None,
        decision_leads=item.decision_leads,
        context_leads=(),
        retrieval=_pending(number + 10_000),
        priority=_priority(item.work_item_id, version_id),
    )


def _maximum_legal_version() -> TriageWorkItemVersion:
    decisions = tuple(_decision(number) for number in range(1, 33))
    contexts = tuple(
        ContextLeadBinding(
            decision.lead_id,
            decision.lead_digest,
            decision.lead_event_id,
            decision.lead_aggregate_version,
            decision.gate_decision_id,
            decision.definition_id,
            decision.definition_version_id,
        )
        for decision in (_decision(number) for number in range(33, 65))
    )
    item = TriageWorkItem.create(decisions)
    version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{item.work_item_id}|1"))
    return TriageWorkItemVersion.create(
        work_item_id=item.work_item_id,
        ordinal=1,
        previous_version_id=None,
        decision_leads=item.decision_leads,
        context_leads=contexts,
        retrieval=_pending(99_999),
        priority=_priority(item.work_item_id, version_id),
    )


def _decision_for(versions: tuple[TriageWorkItemVersion, ...]):
    observations = tuple(
        CapacityPopulationItem(
            calculate_urgency_deadline(
                policy=_policy(),
                item=UrgencyDeadlineInput(
                    version.work_item_id,
                    version.version_id,
                    version.canonical_digest,
                    PrioritySelection.from_canonical_bytes(
                        version.priority.selection_bytes
                    ),
                    PriorityLane.ROUTINE,
                    "2026-08-09T15:00:00Z",
                    "2026-08-09T15:10:00Z",
                    None,
                    SchedulingEligibility.CURRENT_ELIGIBLE,
                    1,
                    1,
                    True,
                ),
            ),
            CapacityWorkState.PENDING,
            None,
        )
        for version in versions
    )
    snapshot = CapacitySnapshot(
        "2026-08-09T15:10:00Z",
        _policy(),
        tuple(sorted(observations, key=lambda item: item.identity_key)),
        CapacityPathState.AVAILABLE,
    )
    return allocate_reserved_capacity(
        policy=ReservedCapacityPolicy(
            "execution-fixture",
            "v1",
            len(versions) + 1,
            1,
            1,
            ReservedCapacityDisposition.URGENT_VISIBLE_OPERATIONAL_HOLD,
        ),
        snapshot=snapshot,
    )


def _batch(*versions: TriageWorkItemVersion) -> ExecutionBatch:
    return ExecutionBatch.create(
        scheduling_decision=_decision_for(tuple(versions)),
        work_item_versions=tuple(versions),
    )


def _member(number: int) -> ExecutionBatchMember:
    return _batch(_version(number)).members[0]


def _attempt(ordinal: int = 1) -> WorkerAttempt:
    member = _member(1)
    return WorkerAttempt.create(
        member=member,
        ordinal=ordinal,
        worker_kind=FixtureWorkerKind.REPLAY,
        worker_version="fixture-v1",
        input_digest=_digest(999),
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
    first = _member(1)
    versions = (_version(1), _version(2))
    a = _batch(*versions)
    b = _batch(*reversed(versions))
    assert a == b
    assert ExecutionBatch.from_canonical_bytes(a.canonical_bytes) == a
    assert a.canonical_value()["authority"] == "NONE"
    assert a.canonical_value()["effect"] == "NONE"
    with pytest.raises(ExecutionContractError, match="unique"):
        replace(a, members=(first, first))
    with pytest.raises(ExecutionContractError, match="binding"):
        replace(first, retrieval_context_digest=_digest(55))
    maximum = _batch(*(_version(index) for index in range(1, 49)))
    assert len(maximum.members) == 48
    assert len(maximum.canonical_bytes) < 64 * 1024
    assert "work_item_version" not in maximum.members[0].canonical_value()
    assert "scheduling_decision" not in maximum.canonical_value()
    assert ExecutionBatch.from_canonical_bytes(maximum.canonical_bytes) == maximum
    with pytest.raises(ExecutionContractError, match="bounded"):
        ExecutionBatch.create(
            scheduling_decision=_decision_for(
                tuple(_version(index) for index in range(1, 49))
            ),
            work_item_versions=tuple(_version(index) for index in range(1, 50)),
        )


def test_attempt_identity_retry_predecessor_and_proposal_binding() -> None:
    first = _attempt()
    member = _member(1)
    for field, divergent_digest in (
        ("work_item_version_digest", _digest(701)),
        ("retrieval_context_digest", _digest(702)),
        ("priority_digest", _digest(703)),
    ):
        member_values = member.canonical_value()
        member_values[field] = divergent_digest
        binding_values = tuple(
            member_values[name]
            for name in (
                "work_item_id",
                "work_item_version_id",
                "work_item_version_digest",
                "retrieval_context_id",
                "retrieval_context_digest",
                "priority_digest",
                "scheduling_grant_digest",
            )
        )
        member_values["producer_binding_digest"] = (
            ExecutionBatchMember._binding_digest(*binding_values)  # type: ignore[arg-type]
        )
        forged_member = ExecutionBatchMember.from_value(member_values)
        with pytest.raises(ExecutionContractError, match="predecessor binding"):
            WorkerAttempt.create(
                member=forged_member,
                ordinal=2,
                previous_attempt=first,
                worker_kind=FixtureWorkerKind.REPLAY,
                worker_version="fixture-v1",
                input_digest=_digest(999),
            )
    second = WorkerAttempt.create(
        member=member,
        ordinal=2,
        previous_attempt=first,
        worker_kind=FixtureWorkerKind.REPLAY,
        worker_version="fixture-v1",
        input_digest=_digest(999),
    )
    assert second.previous_attempt_id == first.attempt_id
    assert second.previous_attempt_digest == first.canonical_digest
    assert second.attempt_id != first.attempt_id
    assert second.semantic_request_digest == first.semantic_request_digest
    assert second.semantic_request_key == first.semantic_request_key
    assert second.idempotency_key == first.idempotency_key
    assert (
        WorkerAttempt.create(
            member=member,
            ordinal=2,
            previous_attempt=first,
            worker_kind=FixtureWorkerKind.REPLAY,
            worker_version="fixture-v1",
            input_digest=_digest(999),
        )
        == second
    )
    fallback = WorkerAttempt.create(
        member=member,
        ordinal=3,
        previous_attempt=second,
        worker_kind=FixtureWorkerKind.REPLAY,
        worker_version="fixture-v2",
        input_digest=_digest(1000),
    )
    assert fallback.previous_attempt_id == second.attempt_id
    assert fallback.semantic_request_key != second.semantic_request_key
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
    with pytest.raises(ExecutionContractError, match="deterministic"):
        replace(second, previous_attempt_digest=_digest(888))
    divergent_predecessor_digest = _digest(888)
    divergent = replace(
        second,
        attempt_id=str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{WORKER_ATTEMPT_SCHEMA}|{second.semantic_request_digest}|"
                f"{second.ordinal}|{second.previous_attempt_id}|"
                f"{divergent_predecessor_digest}",
            )
        ),
        previous_attempt_digest=divergent_predecessor_digest,
    )
    lease_arguments = {
        "owner_id": "worker:fixture",
        "owner_profile_digest": _digest(3),
        "capability_digest": _digest(4),
        "fence": 1,
    }
    exact_lease = WorkItemLease.pending(attempt=second, **lease_arguments)
    divergent_lease = WorkItemLease.pending(attempt=divergent, **lease_arguments)
    assert divergent.attempt_id != second.attempt_id
    assert divergent_lease.attempt_digest == divergent.canonical_digest
    assert divergent_lease.lease_id != exact_lease.lease_id
    assert divergent_lease.canonical_bytes != exact_lease.canonical_bytes
    with pytest.raises(
        ExecutionContractError, match="exact interoperable bounded integer"
    ):
        replace(second, ordinal=True)


def test_maximum_legal_version_and_48_members_remain_compact() -> None:
    maximum = _maximum_legal_version()
    assert len(maximum.decision_leads) == 32
    assert len(maximum.context_leads) == 32
    versions = (maximum, *(_version(index) for index in range(33, 80)))
    batch = _batch(*versions)
    assert len(batch.members) == 48
    assert len(batch.canonical_bytes) < 64 * 1024
    assert maximum.canonical_digest in {
        member.work_item_version_digest for member in batch.members
    }
    assert ExecutionBatch.from_canonical_bytes(batch.canonical_bytes) == batch


def test_lease_represents_capability_fence_lifecycle_and_expiry_without_authority() -> (
    None
):
    attempt = _attempt()
    pending = WorkItemLease.pending(
        attempt=attempt,
        owner_id="worker:fixture",
        owner_profile_digest=_digest(3),
        capability_digest=_digest(4),
        fence=1,
    )
    assert pending.attempt_digest == attempt.canonical_digest
    with pytest.raises(ExecutionContractError, match="deterministic"):
        replace(pending, attempt_digest=_digest(888))
    old_wire = pending.canonical_value()
    old_wire.pop("attempt_digest", None)
    with pytest.raises(ExecutionContractError, match="fields"):
        WorkItemLease.from_canonical_bytes(canonical_json_bytes(old_wire))
    assert pending.lifecycle is LeaseLifecycle.PENDING
    lease = pending.claim(
        issued_at="2042-03-12T10:00:00Z",
        expires_at="2042-03-12T10:05:00Z",
        actor_identity_digest=_digest(6),
    )
    later_expiry = pending.claim(
        issued_at="2042-03-12T10:00:00Z",
        expires_at="2042-03-12T10:06:00Z",
        actor_identity_digest=_digest(6),
    )
    assert lease.transition.actor_identity_digest == _digest(6)
    assert lease.transition.transition_id != later_expiry.transition.transition_id
    assert (
        lease.transition.successor_parameters_digest
        != later_expiry.transition.successor_parameters_digest
    )
    with pytest.raises(ExecutionContractError, match="identity"):
        replace(lease.transition, actor_identity_digest=_digest(999))
    old_transition_wire = lease.canonical_value()
    transition_values = old_transition_wire["transitions"]
    assert isinstance(transition_values, list)
    assert isinstance(transition_values[0], dict)
    transition_values[0].pop("actor_identity_digest")
    with pytest.raises(ExecutionContractError, match="fields"):
        WorkItemLease.from_canonical_bytes(
            canonical_json_bytes(old_transition_wire)
        )
    assert lease.is_expired_at("2042-03-12T10:04:59Z") is False
    assert lease.is_expired_at("2042-03-12T10:05:00Z") is True
    expired = lease.expire(
        observed_at="2042-03-12T10:05:00Z",
        actor_identity_digest=_digest(6),
    )
    assert expired.lifecycle is LeaseLifecycle.EXPIRED
    assert expired.issued_at == lease.issued_at
    assert expired.expires_at == lease.expires_at
    assert WorkItemLease.from_canonical_bytes(lease.canonical_bytes) == lease
    assert lease.canonical_value()["authority"] == "NONE"
    released = lease.release(
        observed_at="2042-03-12T10:03:00Z",
        actor_identity_digest=_digest(6),
        progress=(LeaseProgressEvidence(LeaseProgress.COMPLETED, _digest(5)),),
    )
    assert released.issued_at == lease.issued_at
    assert released.expires_at == lease.expires_at
    assert released.transition.predecessor_digest == lease.canonical_digest
    assert len(released.transitions) == 2
    assert released.transitions[0] == lease.transitions[0]
    assert WorkItemLease.from_canonical_bytes(released.canonical_bytes) == released
    with pytest.raises(ExecutionContractError, match="transition"):
        replace(lease, lifecycle=LeaseLifecycle.RELEASED)
    with pytest.raises(ExecutionContractError, match="expiry"):
        replace(lease, expires_at=lease.issued_at)
    with pytest.raises(ExecutionContractError, match="expired transition"):
        lease.release(
            observed_at=lease.expires_at,
            actor_identity_digest=_digest(6),
        )
    with pytest.raises(ExecutionContractError, match="not allowed"):
        pending.expire(
            observed_at="2042-03-12T10:06:00Z",
            actor_identity_digest=_digest(6),
        )
    with pytest.raises(ExecutionContractError, match="not allowed"):
        lease.claim(
            issued_at="2042-03-12T10:01:00Z",
            expires_at="2042-03-12T10:06:00Z",
            actor_identity_digest=_digest(6),
        )
    with pytest.raises(ExecutionContractError, match="not allowed"):
        released.release(
            observed_at="2042-03-12T10:04:00Z",
            actor_identity_digest=_digest(6),
        )
    with pytest.raises(
        ExecutionContractError, match="exact interoperable bounded integer"
    ):
        replace(pending, fence=True)

    other_owner = WorkItemLease.pending(
        attempt=attempt,
        owner_id="worker:other",
        owner_profile_digest=_digest(3),
        capability_digest=_digest(4),
        fence=1,
    )
    retry_attempt = WorkerAttempt.create(
        member=_member(1),
        ordinal=2,
        previous_attempt=attempt,
        worker_kind=FixtureWorkerKind.REPLAY,
        worker_version="fixture-v1",
        input_digest=_digest(999),
    )
    other_attempt = WorkItemLease.pending(
        attempt=retry_attempt,
        owner_id="worker:fixture",
        owner_profile_digest=_digest(3),
        capability_digest=_digest(4),
        fence=1,
    )
    assert other_owner.lease_id != pending.lease_id
    assert other_attempt.lease_id != pending.lease_id


def test_parser_rejects_duplicate_unknown_enum_bool_depth_size_and_large_integer() -> (
    None
):
    batch = _batch(_version(1))
    with pytest.raises(ExecutionContractError, match="duplicate"):
        ExecutionBatch.from_canonical_bytes(b'{"a":1,"a":2}')
    value = json.loads(batch.canonical_bytes)
    value["unknown"] = True
    with pytest.raises(ExecutionContractError, match="fields"):
        ExecutionBatch.from_canonical_bytes(canonical_json_bytes(value))
    deep = b'{"a":' * 70 + b"null" + b"}" * 70
    with pytest.raises(ExecutionContractError, match="structural"):
        ExecutionBatch.from_canonical_bytes(deep)
    with pytest.raises(ExecutionContractError, match="envelope"):
        ExecutionBatch.from_canonical_bytes(b"{" + b" " * 262_144 + b"}")
    huge = b'{"a":' + b"9" * 5000 + b"}"
    with pytest.raises(ExecutionContractError, match="safe range"):
        ExecutionBatch.from_canonical_bytes(huge)

    lease = WorkItemLease.pending(
        attempt=_attempt(),
        owner_id="worker:fixture",
        owner_profile_digest=_digest(3),
        capability_digest=_digest(4),
        fence=1,
    )
    lease_value = json.loads(lease.canonical_bytes)
    lease_value["lifecycle"] = "UNKNOWN"
    with pytest.raises(ExecutionContractError, match="fields"):
        WorkItemLease.from_canonical_bytes(canonical_json_bytes(lease_value))
    lease_value = json.loads(lease.canonical_bytes)
    lease_value["fence"] = True
    with pytest.raises(
        ExecutionContractError, match="exact interoperable bounded integer"
    ):
        WorkItemLease.from_canonical_bytes(canonical_json_bytes(lease_value))
    attempt_value = json.loads(_attempt().canonical_bytes)
    attempt_value["worker_version"] = 1
    with pytest.raises(ExecutionContractError, match="string"):
        WorkerAttempt.from_canonical_bytes(canonical_json_bytes(attempt_value))


def test_parser_normalises_lone_surrogate_and_constructed_nested_failures() -> None:
    with pytest.raises(ExecutionContractError):
        ExecutionBatch.from_canonical_bytes(b'{"batch_id":"\\ud800"}')
    member = _member(1).canonical_value()
    member["priority_digest"] = []
    batch = _batch(_version(1)).canonical_value()
    batch["members"] = [member]
    with pytest.raises(ExecutionContractError, match="priority"):
        ExecutionBatch.from_canonical_bytes(canonical_json_bytes(batch))


@pytest.mark.parametrize(
    "value",
    [MAX_SAFE_INTEGER + 1, -(MAX_SAFE_INTEGER + 1), True],
)
def test_public_integer_contract_is_interoperably_bounded(value: object) -> None:
    with pytest.raises(ExecutionContractError):
        replace(_attempt(), ordinal=value)


def test_public_constructors_normalise_foreign_and_canonical_failures() -> None:
    class Impostor:
        work_item_id = _id(1)

    with pytest.raises(ExecutionContractError):
        ExecutionBatch.create(  # type: ignore[arg-type]
            scheduling_decision=Impostor(), work_item_versions=()
        )


def test_lease_chain_rejects_recomputed_wrong_predecessor_and_progress_regression() -> (
    None
):
    pending = WorkItemLease.pending(
        attempt=_attempt(),
        owner_id="worker:fixture",
        owner_profile_digest=_digest(3),
        capability_digest=_digest(4),
        fence=1,
    )
    claimed = pending.claim(
        issued_at="2042-03-12T10:00:00Z",
        expires_at="2042-03-12T10:05:00Z",
        actor_identity_digest=_digest(7),
        progress=(LeaseProgressEvidence(LeaseProgress.COMPLETED, _digest(5)),),
    )
    with pytest.raises(ExecutionContractError, match="progress"):
        claimed.release(
            observed_at="2042-03-12T10:03:00Z",
            actor_identity_digest=_digest(7),
            progress=(LeaseProgressEvidence(LeaseProgress.IN_PROGRESS, _digest(6)),),
        )
    with pytest.raises(ExecutionContractError, match="not allowed"):
        LeaseTransitionReceipt.create(
            lease_id=pending.lease_id,
            predecessor_digest=pending.canonical_digest,
            successor_parameters_digest=_digest(7),
            actor_identity_digest=_digest(8),
            from_lifecycle=LeaseLifecycle.PENDING,
            to_lifecycle=LeaseLifecycle.EXPIRED,
            observed_at="2042-03-12T10:05:00Z",
        )

    released = pending.claim(
        issued_at="2042-03-12T10:00:00Z",
        expires_at="2042-03-12T10:05:00Z",
        actor_identity_digest=_digest(7),
    ).release(
        observed_at="2042-03-12T10:03:00Z",
        actor_identity_digest=_digest(8),
    )
    wrong = LeaseTransitionReceipt.create(
        lease_id=released.lease_id,
        predecessor_digest=_digest(999),
        successor_parameters_digest=released.transition.successor_parameters_digest,
        actor_identity_digest=_digest(8),
        from_lifecycle=LeaseLifecycle.CLAIMED,
        to_lifecycle=LeaseLifecycle.RELEASED,
        observed_at="2042-03-12T10:03:00Z",
    )
    value = released.canonical_value()
    value["transitions"][-1] = wrong.canonical_value()  # type: ignore[index]
    with pytest.raises(ExecutionContractError, match="predecessor chain"):
        WorkItemLease.from_canonical_bytes(canonical_json_bytes(value))


def test_public_exact_builtins_and_typed_values_precede_dereference() -> None:
    class BytesSubclass(bytes):
        def decode(self, *args: object, **kwargs: object) -> str:
            raise RuntimeError("must not run")

    class StringSubclass(str):
        def endswith(self, *args: object, **kwargs: object) -> bool:
            raise RuntimeError("must not run")

    class DictSubclass(dict[str, object]):
        def __iter__(self):
            raise RuntimeError("must not run")

    with pytest.raises(ExecutionContractError):
        ExecutionBatch.from_canonical_bytes(BytesSubclass(b"{}"))
    with pytest.raises(ExecutionContractError):
        ExecutionBatchMember.from_value(DictSubclass())
    with pytest.raises(ExecutionContractError):
        WorkerAttempt.create(
            member=_member(1),
            ordinal=1,
            worker_kind=object(),  # type: ignore[arg-type]
            worker_version="fixture-v1",
            input_digest=_digest(9),
        )
    with pytest.raises(ExecutionContractError):
        WorkItemLease.pending(
            attempt=_attempt(),
            owner_id=StringSubclass("worker:fixture"),
            owner_profile_digest=_digest(3),
            capability_digest=_digest(4),
            fence=1,
        )


def test_public_exact_facades_normalise_uninitialised_and_dependency_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    member = object.__new__(ExecutionBatchMember)
    with pytest.raises(ExecutionContractError):
        ExecutionBatch._from_bindings((member,), _digest(1), _digest(2))
    with pytest.raises(ExecutionContractError):
        WorkerAttempt.create(
            member=member,
            ordinal=1,
            worker_kind=FixtureWorkerKind.REPLAY,
            worker_version="fixture-v1",
            input_digest=_digest(9),
        )
    with pytest.raises(ExecutionContractError):
        ExecutionBatch.create(
            scheduling_decision=object.__new__(ReservedCapacityDecision),
            work_item_versions=(_version(1),),
        )
    with pytest.raises(ExecutionContractError):
        WorkerAttempt.create(
            member=_member(1),
            ordinal=2,
            previous_attempt=object.__new__(WorkerAttempt),
            worker_kind=FixtureWorkerKind.REPLAY,
            worker_version="fixture-v1",
            input_digest=_digest(9),
        )

    progress = object.__new__(LeaseProgressEvidence)
    with pytest.raises(ExecutionContractError):
        LeaseTransitionReceipt.create(
            lease_id=_id(1),
            predecessor_digest=_digest(1),
            successor_parameters_digest=_digest(2),
            actor_identity_digest=_digest(3),
            from_lifecycle=LeaseLifecycle.PENDING,
            to_lifecycle=LeaseLifecycle.CLAIMED,
            observed_at="2042-03-12T10:00:00Z",
            progress=(progress,),
        )

    claimed = WorkItemLease.pending(
        attempt=_attempt(),
        owner_id="worker:fixture",
        owner_profile_digest=_digest(3),
        capability_digest=_digest(4),
        fence=1,
    ).claim(
        issued_at="2042-03-12T10:00:00Z",
        expires_at="2042-03-12T10:05:00Z",
        actor_identity_digest=_digest(6),
    )
    receipt = object.__new__(LeaseTransitionReceipt)
    with pytest.raises(ExecutionContractError):
        replace(claimed, transitions=(receipt,))
    with pytest.raises(ExecutionContractError):
        WorkItemLease.pending(
            attempt=object.__new__(WorkerAttempt),
            owner_id="worker:fixture",
            owner_profile_digest=_digest(3),
            capability_digest=_digest(4),
            fence=1,
        )

    raw = _batch(_version(1)).canonical_bytes
    with monkeypatch.context() as context:
        context.setattr(
            execution_contract,
            "canonical_json_bytes",
            lambda _: (_ for _ in ()).throw(RuntimeError("dependency failure")),
        )
        with pytest.raises(ExecutionContractError):
            ExecutionBatch.from_canonical_bytes(raw)

    with monkeypatch.context() as context:
        context.setattr(
            execution_contract,
            "canonical_json_bytes",
            lambda _: (_ for _ in ()).throw(KeyboardInterrupt()),
        )
        with pytest.raises(KeyboardInterrupt):
            ExecutionBatch.from_canonical_bytes(raw)


def test_computed_properties_normalise_uninitialised_and_dependency_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt = _attempt()
    assert attempt.proposal_binding.attempt_id == attempt.attempt_id
    with pytest.raises(ExecutionContractError):
        _ = object.__new__(WorkerAttempt).proposal_binding

    claimed = WorkItemLease.pending(
        attempt=attempt,
        owner_id="worker:fixture",
        owner_profile_digest=_digest(3),
        capability_digest=_digest(4),
        fence=1,
    ).claim(
        issued_at="2042-03-12T10:00:00Z",
        expires_at="2042-03-12T10:05:00Z",
        actor_identity_digest=_digest(6),
    )
    assert claimed.transition == claimed.transitions[-1]
    with pytest.raises(ExecutionContractError):
        _ = object.__new__(WorkItemLease).transition

    batch = _batch(_version(1))
    with monkeypatch.context() as context:
        context.setattr(
            execution_contract,
            "digest_bytes",
            lambda _: (_ for _ in ()).throw(RuntimeError("dependency failure")),
        )
        with pytest.raises(ExecutionContractError):
            _ = batch.canonical_digest

    with monkeypatch.context() as context:
        context.setattr(
            execution_contract,
            "digest_bytes",
            lambda _: (_ for _ in ()).throw(KeyboardInterrupt()),
        )
        with pytest.raises(KeyboardInterrupt):
            _ = batch.canonical_digest
