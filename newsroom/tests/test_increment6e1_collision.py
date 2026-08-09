from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.increment5.named_tool_authority_adapters import (
    CollisionHydrationNamedToolPort,
    NamedAuthorityAdapterConfig,
    SourceRevisionImpactNamedToolPort,
)
from newsroom.increment5.named_tool_authority_execution import (
    NamedAuthorityExecutionReceipt,
)
from newsroom.increment6.collision import (
    CandidateUseCollisionBinding,
    CandidateUseOperation,
    CollisionEligibilityContractError,
    CollisionEligibilityReason,
    CollisionEligibilityOutcome,
    CollisionState,
    CurrentCollisionAuthoritySnapshot,
    CurrentCollisionEffectEnforcer,
    CurrentCollisionEligibilityBlocked,
    CurrentCollisionEligibilityDecision,
    CurrentCollisionEligibilityRequest,
    CurrentCollisionReceiptEvidence,
    TrustedCurrentCollisionAuthorityContext,
    TrustedCurrentCollisionAuthorityBoundary,
    decide_current_collision_eligibility as _decide_current_collision_eligibility,
)
from newsroom.tests.test_increment5c2_named_tool_authority_execution import (
    COLLISION_DIGEST,
    QUERY_VALID,
    SERVING,
    authority_database,
    authorize,
    collision_request,
    create_schema,
    digest,
    executor,
    ports,
    seed_object,
)


def _occupied_evidence(tmp_path: Path):
    binding = CandidateUseCollisionBinding(
        subject_id="hypothesis:001",
        subject_version_id="hypothesis-version:001",
        subject_version_digest=digest("hypothesis-version:001"),
        operation=CandidateUseOperation.USE_CURRENT_CANDIDATE,
        expected_candidate_id="candidate:001",
        collision_namespace="candidate-development",
        collision_key_digest=COLLISION_DIGEST,
        generation_id="retrieval-generation-v1",
        query_valid_time=QUERY_VALID,
        serving_time=SERVING,
        authority_watermark=42,
    )
    named_request = collision_request(idempotency_key=binding.idempotency_key)
    result = executor(tmp_path, authority_database(tmp_path)).execute(
        named_request,
        authorize(tmp_path, named_request),
    )
    assert result.authority_receipt_bytes is not None
    requirement = CurrentCollisionEligibilityRequest(
        binding=binding,
        named_request_digest=named_request.request_digest,
    )
    evidence = CurrentCollisionReceiptEvidence(
        named_request=named_request,
        execution_receipt_bytes=result.receipt.canonical_bytes,
        authority_receipt_bytes=result.authority_receipt_bytes,
    )
    return requirement, evidence


def _trusted_context(
    evidence: CurrentCollisionReceiptEvidence,
    **changes: object,
) -> TrustedCurrentCollisionAuthorityContext:
    execution = NamedAuthorityExecutionReceipt.from_canonical_bytes(
        evidence.execution_receipt_bytes
    )
    assert execution.authority_attribution is not None
    assert execution.port_id is not None
    assert evidence.authority_receipt_bytes is not None
    authority = json.loads(evidence.authority_receipt_bytes)
    values: dict[str, object] = {
        "generation_id": evidence.named_request.envelope.generation_id,
        "authority_watermark": execution.authority_attribution.authority_watermark,
        "query_valid_time": evidence.named_request.envelope.query_valid_time,
        "serving_time": evidence.named_request.envelope.serving_time,
        "authority_scope_id": authority["authority_scope_id"],
        "authority_profile_id": execution.authority_attribution.authority_profile_id,
        "adapter_config_digest": authority["adapter_config_digest"],
        "authorization_receipt_digest": execution.authorization_receipt_digest,
        "authorization_decision_id": execution.authorization_decision_id,
        "port_registry_digest": execution.port_registry_digest,
        "port_id": execution.port_id,
    }
    values.update(changes)
    return TrustedCurrentCollisionAuthorityContext(**values)  # type: ignore[arg-type]


def _decide(
    *,
    request: CurrentCollisionEligibilityRequest,
    evidence: CurrentCollisionReceiptEvidence,
    trusted_context: TrustedCurrentCollisionAuthorityContext | None = None,
) -> CurrentCollisionEligibilityDecision:
    return _decide_current_collision_eligibility(
        request=request,
        evidence=evidence,
        trusted_context=trusted_context or _trusted_context(evidence),
    )


def _enforcer(
    evidence: CurrentCollisionReceiptEvidence,
    *,
    provider=None,
) -> CurrentCollisionEffectEnforcer:
    context = _trusted_context(evidence)
    snapshot = CurrentCollisionAuthoritySnapshot(
        evidence=evidence,
        trusted_context=context,
    )
    return CurrentCollisionEffectEnforcer(
        current_authority_provider=provider or (lambda request: snapshot),
        trusted_boundary=TrustedCurrentCollisionAuthorityBoundary(
            authority_scope_id=context.authority_scope_id,
            authority_profile_id=context.authority_profile_id,
            adapter_config_digest=context.adapter_config_digest,
            port_registry_digest=context.port_registry_digest,
            port_id=context.port_id,
        ),
    )


def test_current_matching_candidate_is_eligible_before_effect(tmp_path: Path) -> None:
    requirement, evidence = _occupied_evidence(tmp_path)

    decision = _decide(
        request=requirement,
        evidence=evidence,
    )

    assert decision.outcome is CollisionEligibilityOutcome.ELIGIBLE
    assert decision.eligible is True
    assert decision.collision_state is CollisionState.OCCUPIED
    assert decision.observed_candidate_id == "candidate:001"
    effects: list[str] = []
    result = _enforcer(evidence).enforce(
        request=requirement,
        effect=lambda permit: effects.append(permit.decision_digest) or "used",
    )
    assert result == "used"
    assert effects == [decision.decision_digest]


def test_current_unoccupied_slot_is_eligible_for_new_candidate(
    tmp_path: Path,
) -> None:
    binding = CandidateUseCollisionBinding(
        subject_id="hypothesis:002",
        subject_version_id="hypothesis-version:002",
        subject_version_digest=digest("hypothesis-version:002"),
        operation=CandidateUseOperation.ADMIT_NEW_CANDIDATE,
        expected_candidate_id=None,
        collision_namespace="candidate-development",
        collision_key_digest=COLLISION_DIGEST,
        generation_id="retrieval-generation-v2",
        query_valid_time=QUERY_VALID,
        serving_time=SERVING,
        authority_watermark=42,
    )
    named_request = collision_request(
        idempotency_key=binding.idempotency_key,
        generation_id=binding.generation_id,
    )
    database = authority_database(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM development_candidates_v2")
    result = executor(tmp_path, database).execute(
        named_request,
        authorize(tmp_path, named_request),
    )
    assert result.authority_receipt_bytes is not None
    decision = _decide(
        request=CurrentCollisionEligibilityRequest(
            binding=binding,
            named_request_digest=named_request.request_digest,
        ),
        evidence=CurrentCollisionReceiptEvidence(
            named_request=named_request,
            execution_receipt_bytes=result.receipt.canonical_bytes,
            authority_receipt_bytes=result.authority_receipt_bytes,
        ),
    )

    assert decision.outcome is CollisionEligibilityOutcome.ELIGIBLE
    assert decision.collision_state is CollisionState.UNOCCUPIED
    assert decision.observed_candidate_id is None


def test_occupied_slot_blocks_new_candidate_before_effect(tmp_path: Path) -> None:
    binding = CandidateUseCollisionBinding(
        subject_id="hypothesis:003",
        subject_version_id="hypothesis-version:003",
        subject_version_digest=digest("hypothesis-version:003"),
        operation=CandidateUseOperation.ADMIT_NEW_CANDIDATE,
        expected_candidate_id=None,
        collision_namespace="candidate-development",
        collision_key_digest=COLLISION_DIGEST,
        generation_id="retrieval-generation-v3",
        query_valid_time=QUERY_VALID,
        serving_time=SERVING,
        authority_watermark=42,
    )
    named_request = collision_request(
        idempotency_key=binding.idempotency_key,
        generation_id=binding.generation_id,
    )
    result = executor(tmp_path, authority_database(tmp_path)).execute(
        named_request,
        authorize(tmp_path, named_request),
    )
    assert result.authority_receipt_bytes is not None
    requirement = CurrentCollisionEligibilityRequest(
        binding=binding,
        named_request_digest=named_request.request_digest,
    )
    evidence = CurrentCollisionReceiptEvidence(
        named_request=named_request,
        execution_receipt_bytes=result.receipt.canonical_bytes,
        authority_receipt_bytes=result.authority_receipt_bytes,
    )
    effects: list[str] = []

    with pytest.raises(CurrentCollisionEligibilityBlocked) as caught:
        _enforcer(evidence).enforce(
            request=requirement,
            effect=lambda permit: effects.append(permit.decision_digest),
        )

    assert caught.value.decision.outcome is (
        CollisionEligibilityOutcome.COLLISION_CONFLICT
    )
    assert caught.value.decision.reason is (
        CollisionEligibilityReason.SLOT_ALREADY_OCCUPIED
    )
    assert effects == []


def test_stale_authority_receipt_never_becomes_candidate_eligibility(
    tmp_path: Path,
) -> None:
    binding = CandidateUseCollisionBinding(
        subject_id="hypothesis:004",
        subject_version_id="hypothesis-version:004",
        subject_version_digest=digest("hypothesis-version:004"),
        operation=CandidateUseOperation.USE_CURRENT_CANDIDATE,
        expected_candidate_id="candidate:001",
        collision_namespace="candidate-development",
        collision_key_digest=COLLISION_DIGEST,
        generation_id="retrieval-generation-v4",
        query_valid_time=QUERY_VALID,
        serving_time=SERVING,
        authority_watermark=42,
    )
    named_request = collision_request(
        idempotency_key=binding.idempotency_key,
        generation_id=binding.generation_id,
    )
    database = authority_database(tmp_path)
    result = executor(
        tmp_path,
        database,
        selected_ports=ports(database, minimum_ledger_seq=43),
    ).execute(named_request, authorize(tmp_path, named_request))
    assert result.authority_receipt_bytes is not None

    decision = _decide(
        request=CurrentCollisionEligibilityRequest(
            binding=binding,
            named_request_digest=named_request.request_digest,
        ),
        evidence=CurrentCollisionReceiptEvidence(
            named_request=named_request,
            execution_receipt_bytes=result.receipt.canonical_bytes,
            authority_receipt_bytes=result.authority_receipt_bytes,
        ),
    )

    assert decision.outcome is CollisionEligibilityOutcome.STALE
    assert decision.reason is CollisionEligibilityReason.AUTHORITY_STALE
    assert decision.eligible is False
    assert decision.collision_state is CollisionState.UNKNOWN
    assert decision.candidate_effect_performed is False


def test_incomplete_collision_receipt_never_becomes_candidate_eligibility(
    tmp_path: Path,
) -> None:
    binding = CandidateUseCollisionBinding(
        subject_id="hypothesis:005",
        subject_version_id="hypothesis-version:005",
        subject_version_digest=digest("hypothesis-version:005"),
        operation=CandidateUseOperation.USE_CURRENT_CANDIDATE,
        expected_candidate_id="candidate:001",
        collision_namespace="candidate-development",
        collision_key_digest=COLLISION_DIGEST,
        generation_id="retrieval-generation-v5",
        query_valid_time=QUERY_VALID,
        serving_time=SERVING,
        authority_watermark=42,
    )
    named_request = collision_request(
        idempotency_key=binding.idempotency_key,
        generation_id=binding.generation_id,
        result_limit=2,
    )
    result = executor(tmp_path, authority_database(tmp_path)).execute(
        named_request,
        authorize(tmp_path, named_request),
    )
    assert result.authority_receipt_bytes is not None

    decision = _decide(
        request=CurrentCollisionEligibilityRequest(
            binding=binding,
            named_request_digest=named_request.request_digest,
        ),
        evidence=CurrentCollisionReceiptEvidence(
            named_request=named_request,
            execution_receipt_bytes=result.receipt.canonical_bytes,
            authority_receipt_bytes=result.authority_receipt_bytes,
        ),
    )

    assert decision.outcome is CollisionEligibilityOutcome.INCOMPLETE
    assert decision.reason is CollisionEligibilityReason.AUTHORITY_INCOMPLETE
    assert decision.eligible is False


def test_policy_blocked_collision_receipt_never_becomes_eligibility(
    tmp_path: Path,
) -> None:
    binding = CandidateUseCollisionBinding(
        subject_id="hypothesis:006",
        subject_version_id="hypothesis-version:006",
        subject_version_digest=digest("hypothesis-version:006"),
        operation=CandidateUseOperation.USE_CURRENT_CANDIDATE,
        expected_candidate_id="candidate:001",
        collision_namespace="candidate-development",
        collision_key_digest=COLLISION_DIGEST,
        generation_id="retrieval-generation-v6",
        query_valid_time=QUERY_VALID,
        serving_time=SERVING,
        authority_watermark=42,
    )
    named_request = collision_request(
        idempotency_key=binding.idempotency_key,
        generation_id=binding.generation_id,
    )
    database = tmp_path / "policy-blocked.sqlite"
    with sqlite3.connect(database) as connection:
        create_schema(connection)
        seed_object(connection, allowed=0)
        connection.execute(
            "INSERT INTO development_candidates_v2 VALUES(?,?)",
            ("candidate:001", COLLISION_DIGEST),
        )
    result = executor(tmp_path, database).execute(
        named_request,
        authorize(tmp_path, named_request),
    )
    assert result.authority_receipt_bytes is not None

    decision = _decide(
        request=CurrentCollisionEligibilityRequest(
            binding=binding,
            named_request_digest=named_request.request_digest,
        ),
        evidence=CurrentCollisionReceiptEvidence(
            named_request=named_request,
            execution_receipt_bytes=result.receipt.canonical_bytes,
            authority_receipt_bytes=result.authority_receipt_bytes,
        ),
    )

    assert decision.outcome is CollisionEligibilityOutcome.POLICY_BLOCKED
    assert decision.reason is CollisionEligibilityReason.AUTHORITY_POLICY_BLOCKED
    assert decision.eligible is False


def test_unavailable_collision_receipt_never_becomes_eligibility(
    tmp_path: Path,
) -> None:
    binding = CandidateUseCollisionBinding(
        subject_id="hypothesis:007",
        subject_version_id="hypothesis-version:007",
        subject_version_digest=digest("hypothesis-version:007"),
        operation=CandidateUseOperation.USE_CURRENT_CANDIDATE,
        expected_candidate_id="candidate:001",
        collision_namespace="candidate-development",
        collision_key_digest=COLLISION_DIGEST,
        generation_id="retrieval-generation-v7",
        query_valid_time=QUERY_VALID,
        serving_time=SERVING,
        authority_watermark=42,
    )
    named_request = collision_request(
        idempotency_key=binding.idempotency_key,
        generation_id=binding.generation_id,
    )
    database = tmp_path / "unavailable.sqlite"
    with sqlite3.connect(database) as connection:
        create_schema(connection)
        seed_object(connection, rights_object_class="WRONG_CLASS")
        connection.execute(
            "INSERT INTO development_candidates_v2 VALUES(?,?)",
            ("candidate:001", COLLISION_DIGEST),
        )
    result = executor(tmp_path, database).execute(
        named_request,
        authorize(tmp_path, named_request),
    )
    assert result.authority_receipt_bytes is not None

    decision = _decide(
        request=CurrentCollisionEligibilityRequest(
            binding=binding,
            named_request_digest=named_request.request_digest,
        ),
        evidence=CurrentCollisionReceiptEvidence(
            named_request=named_request,
            execution_receipt_bytes=result.receipt.canonical_bytes,
            authority_receipt_bytes=result.authority_receipt_bytes,
        ),
    )

    assert decision.outcome is CollisionEligibilityOutcome.UNAVAILABLE
    assert decision.reason is CollisionEligibilityReason.AUTHORITY_UNAVAILABLE
    assert decision.eligible is False


def test_tampered_authority_receipt_is_integrity_blocked_before_effect(
    tmp_path: Path,
) -> None:
    requirement, evidence = _occupied_evidence(tmp_path)
    assert evidence.authority_receipt_bytes is not None
    payload = json.loads(evidence.authority_receipt_bytes)
    payload["candidate_id"] = "candidate:tampered"
    tampered = CurrentCollisionReceiptEvidence(
        named_request=evidence.named_request,
        execution_receipt_bytes=evidence.execution_receipt_bytes,
        authority_receipt_bytes=canonical_json_bytes(payload),
    )
    effects: list[str] = []

    with pytest.raises(CurrentCollisionEligibilityBlocked) as caught:
        tampered_snapshot = CurrentCollisionAuthoritySnapshot(
            evidence=tampered,
            trusted_context=_trusted_context(evidence),
        )
        _enforcer(
            evidence,
            provider=lambda request: tampered_snapshot,
        ).enforce(
            request=requirement,
            effect=lambda permit: effects.append(permit.decision_digest),
        )

    assert caught.value.decision.outcome is (
        CollisionEligibilityOutcome.INTEGRITY_BLOCKED
    )
    assert caught.value.decision.reason is (
        CollisionEligibilityReason.AUTHORITY_RECEIPT_INVALID
    )
    assert effects == []


@pytest.mark.parametrize(
    ("binding_changes", "expected_reason"),
    (
        (
            {"subject_id": "hypothesis:other"},
            CollisionEligibilityReason.NAMED_REQUEST_BINDING_DIFFERS,
        ),
        (
            {"generation_id": "retrieval-generation-other"},
            CollisionEligibilityReason.GENERATION_BINDING_DIFFERS,
        ),
        (
            {"query_valid_time": "2026-08-06T08:58:00Z"},
            CollisionEligibilityReason.TIME_BINDING_DIFFERS,
        ),
        (
            {"authority_watermark": 41},
            CollisionEligibilityReason.WATERMARK_BINDING_DIFFERS,
        ),
    ),
)
def test_complete_receipt_cannot_be_rebound_or_accepted_from_cached_state(
    tmp_path: Path,
    binding_changes: dict[str, object],
    expected_reason: CollisionEligibilityReason,
) -> None:
    requirement, evidence = _occupied_evidence(tmp_path)
    rebound = CurrentCollisionEligibilityRequest(
        binding=replace(requirement.binding, **binding_changes),
        named_request_digest=requirement.named_request_digest,
    )

    decision = _decide(
        request=rebound,
        evidence=evidence,
    )

    assert decision.outcome is CollisionEligibilityOutcome.BINDING_MISMATCH
    assert decision.reason is expected_reason
    assert decision.eligible is False


@pytest.mark.parametrize(
    "current_changes",
    (
        {"authority_watermark": 43},
        {"generation_id": "retrieval-generation-current"},
        {"serving_time": "2026-08-06T09:00:01Z"},
    ),
)
def test_cached_complete_receipt_blocks_when_trusted_authority_advances(
    tmp_path: Path,
    current_changes: dict[str, object],
) -> None:
    requirement, evidence = _occupied_evidence(tmp_path)
    effects: list[str] = []
    advanced_snapshot = CurrentCollisionAuthoritySnapshot(
        evidence=evidence,
        trusted_context=_trusted_context(evidence, **current_changes),
    )
    snapshots = iter(
        (
            CurrentCollisionAuthoritySnapshot(
                evidence=evidence,
                trusted_context=_trusted_context(evidence),
            ),
            advanced_snapshot,
        )
    )

    with pytest.raises(CurrentCollisionEligibilityBlocked) as caught:
        _enforcer(
            evidence,
            provider=lambda request: next(snapshots),
        ).enforce(
            request=requirement,
            effect=lambda permit: effects.append(permit.decision_digest),
        )

    assert caught.value.decision.outcome is CollisionEligibilityOutcome.STALE
    assert caught.value.decision.reason in {
        CollisionEligibilityReason.CURRENT_AUTHORITY_ADVANCED,
        CollisionEligibilityReason.CURRENT_SERVING_BOUNDARY_DIFFERS,
    }
    assert effects == []


def test_candidate_caller_cannot_submit_cached_evidence_or_context_to_effect_gate(
    tmp_path: Path,
) -> None:
    requirement, old_evidence = _occupied_evidence(tmp_path)
    old_context = _trusted_context(old_evidence)
    live_snapshot = CurrentCollisionAuthoritySnapshot(
        evidence=old_evidence,
        trusted_context=replace(old_context, authority_watermark=43),
    )
    enforcer = _enforcer(
        old_evidence,
        provider=lambda request: live_snapshot,
    )
    effects: list[str] = []

    with pytest.raises(TypeError):
        enforcer.enforce(
            request=requirement,
            effect=lambda permit: effects.append(permit.decision_digest),
            evidence=old_evidence,  # type: ignore[call-arg]
            trusted_context=old_context,  # type: ignore[call-arg]
        )
    with pytest.raises(CurrentCollisionEligibilityBlocked) as caught:
        enforcer.enforce(
            request=requirement,
            effect=lambda permit: effects.append(permit.decision_digest),
        )

    assert caught.value.decision.outcome is CollisionEligibilityOutcome.STALE
    assert caught.value.decision.reason is (
        CollisionEligibilityReason.CURRENT_AUTHORITY_ADVANCED
    )
    assert effects == []


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("authorization_receipt_digest", digest("different-authorization")),
        ("port_registry_digest", digest("different-registry")),
        ("port_id", "increment5.named.collision-hydration.other"),
    ),
)
def test_execution_provenance_tamper_is_integrity_blocked(
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    requirement, evidence = _occupied_evidence(tmp_path)
    trusted_context = _trusted_context(evidence)
    execution = json.loads(evidence.execution_receipt_bytes)
    execution[field] = replacement
    tampered = CurrentCollisionReceiptEvidence(
        named_request=evidence.named_request,
        execution_receipt_bytes=canonical_json_bytes(execution),
        authority_receipt_bytes=evidence.authority_receipt_bytes,
    )

    decision = _decide(
        request=requirement,
        evidence=tampered,
        trusted_context=trusted_context,
    )

    assert decision.outcome is CollisionEligibilityOutcome.INTEGRITY_BLOCKED
    assert decision.reason is (
        CollisionEligibilityReason.EXECUTION_PROVENANCE_DIFFERS
    )


@pytest.mark.parametrize(
    "identity_changes",
    (
        {"authority_scope_id": "authority:unexpected"},
        {"authority_profile_id": "unexpected-authority-profile"},
        {"adapter_config_digest": digest("unexpected-adapter-config")},
    ),
)
def test_self_consistent_receipt_cannot_select_untrusted_authority_identity(
    tmp_path: Path,
    identity_changes: dict[str, object],
) -> None:
    requirement, evidence = _occupied_evidence(tmp_path)

    decision = _decide(
        request=requirement,
        evidence=evidence,
        trusted_context=_trusted_context(evidence, **identity_changes),
    )

    assert decision.outcome is CollisionEligibilityOutcome.INTEGRITY_BLOCKED
    assert decision.reason is CollisionEligibilityReason.AUTHORITY_IDENTITY_DIFFERS


def test_effect_gate_rejects_self_consistent_unexpected_authority_provider(
    tmp_path: Path,
) -> None:
    requirement, standard_evidence = _occupied_evidence(tmp_path)
    unexpected_config = NamedAuthorityAdapterConfig(
        authority_scope_id="authority:unexpected",
    )
    unexpected_root = tmp_path / "unexpected"
    unexpected_root.mkdir()
    database = authority_database(unexpected_root)
    unexpected_ports = (
        CollisionHydrationNamedToolPort(
            authority_database=database,
            config=unexpected_config,
        ),
        SourceRevisionImpactNamedToolPort(
            authority_database=database,
            config=unexpected_config,
        ),
    )
    result = executor(
        unexpected_root,
        database,
        selected_ports=unexpected_ports,
    ).execute(
        standard_evidence.named_request,
        authorize(unexpected_root, standard_evidence.named_request),
    )
    assert result.authority_receipt_bytes is not None
    unexpected_evidence = CurrentCollisionReceiptEvidence(
        named_request=standard_evidence.named_request,
        execution_receipt_bytes=result.receipt.canonical_bytes,
        authority_receipt_bytes=result.authority_receipt_bytes,
    )
    matching_unexpected_context = _trusted_context(unexpected_evidence)
    assert _decide(
        request=requirement,
        evidence=unexpected_evidence,
        trusted_context=matching_unexpected_context,
    ).eligible
    standard_context = _trusted_context(standard_evidence)
    unexpected_snapshot = CurrentCollisionAuthoritySnapshot(
        evidence=unexpected_evidence,
        trusted_context=matching_unexpected_context,
    )
    enforcer = CurrentCollisionEffectEnforcer(
        current_authority_provider=lambda request: unexpected_snapshot,
        trusted_boundary=TrustedCurrentCollisionAuthorityBoundary(
            authority_scope_id=standard_context.authority_scope_id,
            authority_profile_id=standard_context.authority_profile_id,
            adapter_config_digest=standard_context.adapter_config_digest,
            port_registry_digest=standard_context.port_registry_digest,
            port_id=standard_context.port_id,
        ),
    )
    effects: list[str] = []

    with pytest.raises(CurrentCollisionEligibilityBlocked) as caught:
        enforcer.enforce(
            request=requirement,
            effect=lambda permit: effects.append(permit.decision_digest),
        )

    assert caught.value.decision.outcome is (
        CollisionEligibilityOutcome.INTEGRITY_BLOCKED
    )
    assert caught.value.decision.reason is (
        CollisionEligibilityReason.AUTHORITY_IDENTITY_DIFFERS
    )
    assert effects == []


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("authorization_receipt_digest", digest("advanced-authorization")),
        ("authorization_decision_id", "00000000-0000-4000-8000-000000000099"),
        ("port_registry_digest", digest("advanced-port-registry")),
        ("port_id", "increment5.named.collision-hydration.advanced"),
    ),
)
def test_commit_time_recheck_blocks_execution_provenance_drift(
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    requirement, evidence = _occupied_evidence(tmp_path)
    initial_snapshot = CurrentCollisionAuthoritySnapshot(
        evidence=evidence,
        trusted_context=_trusted_context(evidence),
    )
    execution = json.loads(evidence.execution_receipt_bytes)
    execution[field] = replacement
    changed_evidence = CurrentCollisionReceiptEvidence(
        named_request=evidence.named_request,
        execution_receipt_bytes=canonical_json_bytes(execution),
        authority_receipt_bytes=evidence.authority_receipt_bytes,
    )
    changed_snapshot = CurrentCollisionAuthoritySnapshot(
        evidence=changed_evidence,
        trusted_context=replace(
            initial_snapshot.trusted_context,
            **{field: replacement},
        ),
    )
    snapshots = iter((initial_snapshot, changed_snapshot))
    effects: list[str] = []

    with pytest.raises(CurrentCollisionEligibilityBlocked) as caught:
        _enforcer(
            evidence,
            provider=lambda request: next(snapshots),
        ).enforce(
            request=requirement,
            effect=lambda permit: effects.append(permit.decision_digest),
        )

    assert caught.value.decision.outcome in {
        CollisionEligibilityOutcome.INTEGRITY_BLOCKED,
        CollisionEligibilityOutcome.STALE,
    }
    assert effects == []


def test_commit_time_recheck_blocks_current_candidate_drift(tmp_path: Path) -> None:
    requirement, evidence = _occupied_evidence(tmp_path)
    changed_root = tmp_path / "candidate-drift"
    changed_root.mkdir()
    database = authority_database(changed_root)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE development_candidates_v2 SET candidate_id = ?",
            ("candidate:other",),
        )
    result = executor(changed_root, database).execute(
        evidence.named_request,
        authorize(changed_root, evidence.named_request),
    )
    assert result.authority_receipt_bytes is not None
    changed_evidence = CurrentCollisionReceiptEvidence(
        named_request=evidence.named_request,
        execution_receipt_bytes=result.receipt.canonical_bytes,
        authority_receipt_bytes=result.authority_receipt_bytes,
    )
    snapshots = iter(
        (
            CurrentCollisionAuthoritySnapshot(
                evidence=evidence,
                trusted_context=_trusted_context(evidence),
            ),
            CurrentCollisionAuthoritySnapshot(
                evidence=changed_evidence,
                trusted_context=_trusted_context(changed_evidence),
            ),
        )
    )
    effects: list[str] = []

    with pytest.raises(CurrentCollisionEligibilityBlocked) as caught:
        _enforcer(
            evidence,
            provider=lambda request: next(snapshots),
        ).enforce(
            request=requirement,
            effect=lambda permit: effects.append(permit.decision_digest),
        )

    assert caught.value.decision.outcome is (
        CollisionEligibilityOutcome.COLLISION_CONFLICT
    )
    assert caught.value.decision.reason is (
        CollisionEligibilityReason.CURRENT_CANDIDATE_DIFFERS
    )
    assert effects == []


def test_exact_replay_is_byte_stable_and_decision_round_trips(
    tmp_path: Path,
) -> None:
    requirement, evidence = _occupied_evidence(tmp_path)

    first = _decide(
        request=requirement,
        evidence=evidence,
    )
    replay = _decide(
        request=requirement,
        evidence=evidence,
    )
    restored = CurrentCollisionEligibilityDecision.from_canonical_bytes(
        first.canonical_bytes
    )

    assert replay.canonical_bytes == first.canonical_bytes
    assert replay.decision_digest == first.decision_digest
    assert restored == first


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.__setitem__("eligible", False),
        lambda value: value.__setitem__(
            "schema_version",
            "newsroom.increment6.candidate-collision-eligibility.v2",
        ),
        lambda value: value.__setitem__("unexpected", "field"),
    ),
)
def test_decision_parser_rejects_tamper_and_schema_widening(
    tmp_path: Path,
    mutate,
) -> None:
    requirement, evidence = _occupied_evidence(tmp_path)
    decision = _decide(
        request=requirement,
        evidence=evidence,
    )
    value = json.loads(decision.canonical_bytes)
    mutate(value)

    with pytest.raises(CollisionEligibilityContractError):
        CurrentCollisionEligibilityDecision.from_canonical_bytes(
            canonical_json_bytes(value)
        )


def test_decision_parser_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    requirement, evidence = _occupied_evidence(tmp_path)
    decision = _decide(
        request=requirement,
        evidence=evidence,
    )
    duplicate = decision.canonical_bytes.replace(
        b'"eligible":true,',
        b'"eligible":true,"eligible":true,',
        1,
    )
    assert duplicate != decision.canonical_bytes

    with pytest.raises(CollisionEligibilityContractError, match="duplicate JSON key"):
        CurrentCollisionEligibilityDecision.from_canonical_bytes(duplicate)


def test_different_current_candidate_is_not_eligible_for_use(tmp_path: Path) -> None:
    binding = CandidateUseCollisionBinding(
        subject_id="hypothesis:008",
        subject_version_id="hypothesis-version:008",
        subject_version_digest=digest("hypothesis-version:008"),
        operation=CandidateUseOperation.USE_CURRENT_CANDIDATE,
        expected_candidate_id="candidate:other",
        collision_namespace="candidate-development",
        collision_key_digest=COLLISION_DIGEST,
        generation_id="retrieval-generation-v8",
        query_valid_time=QUERY_VALID,
        serving_time=SERVING,
        authority_watermark=42,
    )
    named_request = collision_request(
        idempotency_key=binding.idempotency_key,
        generation_id=binding.generation_id,
    )
    result = executor(tmp_path, authority_database(tmp_path)).execute(
        named_request,
        authorize(tmp_path, named_request),
    )
    assert result.authority_receipt_bytes is not None

    decision = _decide(
        request=CurrentCollisionEligibilityRequest(
            binding=binding,
            named_request_digest=named_request.request_digest,
        ),
        evidence=CurrentCollisionReceiptEvidence(
            named_request=named_request,
            execution_receipt_bytes=result.receipt.canonical_bytes,
            authority_receipt_bytes=result.authority_receipt_bytes,
        ),
    )

    assert decision.outcome is CollisionEligibilityOutcome.COLLISION_CONFLICT
    assert decision.reason is (
        CollisionEligibilityReason.CURRENT_CANDIDATE_DIFFERS
    )
    assert decision.eligible is False


def test_missing_retained_authority_bytes_fail_closed_as_unavailable(
    tmp_path: Path,
) -> None:
    requirement, evidence = _occupied_evidence(tmp_path)
    missing = CurrentCollisionReceiptEvidence(
        named_request=evidence.named_request,
        execution_receipt_bytes=evidence.execution_receipt_bytes,
        authority_receipt_bytes=None,
    )

    decision = _decide(
        request=requirement,
        evidence=missing,
        trusted_context=_trusted_context(evidence),
    )

    assert decision.outcome is CollisionEligibilityOutcome.UNAVAILABLE
    assert decision.reason is CollisionEligibilityReason.AUTHORITY_RECEIPT_MISSING
    assert decision.eligible is False


def test_tampered_execution_binding_is_integrity_blocked(tmp_path: Path) -> None:
    requirement, evidence = _occupied_evidence(tmp_path)
    execution = json.loads(evidence.execution_receipt_bytes)
    execution["tool_request_digest"] = digest("different-request")
    tampered = CurrentCollisionReceiptEvidence(
        named_request=evidence.named_request,
        execution_receipt_bytes=canonical_json_bytes(execution),
        authority_receipt_bytes=evidence.authority_receipt_bytes,
    )

    decision = _decide(
        request=requirement,
        evidence=tampered,
    )

    assert decision.outcome is CollisionEligibilityOutcome.INTEGRITY_BLOCKED
    assert decision.reason is (
        CollisionEligibilityReason.EXECUTION_RECEIPT_INVALID
    )
    assert decision.eligible is False


def test_parser_cannot_rebind_eligible_decision_to_another_candidate(
    tmp_path: Path,
) -> None:
    requirement, evidence = _occupied_evidence(tmp_path)
    decision = _decide(
        request=requirement,
        evidence=evidence,
    )
    value = json.loads(decision.canonical_bytes)
    value["eligibility_request"]["binding"]["expected_candidate_id"] = (
        "candidate:other"
    )
    rebound = CurrentCollisionEligibilityRequest.from_mapping(
        value["eligibility_request"]
    )
    value["eligibility_request_digest"] = rebound.request_digest

    with pytest.raises(CollisionEligibilityContractError):
        CurrentCollisionEligibilityDecision.from_canonical_bytes(
            canonical_json_bytes(value)
        )
