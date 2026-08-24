from __future__ import annotations

import csv
import io
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from newsroom.authority.canonical import digest_canonical
from newsroom.control_plane.graphiti import (
    GRAPHITI_CHAT_PRIMARY_ROUTE,
    GRAPHITI_CONTEXT_IDENTITY,
    GRAPHITI_EMBEDDING_ROUTE,
    GraphitiModelUsageObserver,
)
from newsroom.control_plane.model_usage import (
    InvocationAllocation,
    InvocationEfficiencyPolicy,
    InvocationTerminal,
    ModelUsageAdmissionError,
    ModelUsageIntegrityError,
    ModelUsageService,
    UsageComponents,
    UsageStatus,
    WorkEnvelope,
    WorkloadClass,
)
from newsroom.graphiti_adapter.contracts import GRAPHITI_PROMPT_COMPONENT
from newsroom.graphiti_adapter.evaluation_packet import (
    CURSOR_AGENT_MODEL_ID,
    OPENROUTER_EMBEDDING_SLUG,
)

T0 = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)


def _digest(value: object) -> str:
    return digest_canonical(value)


def _service(tmp_path: Path) -> ModelUsageService:
    return ModelUsageService(str(tmp_path / "unpublished.sqlite3"))


def _policy(
    *,
    workload: WorkloadClass = WorkloadClass.CONT_WRITER_PRIMARY,
    provider: str = "grok-build-cli",
    route: str = "CONT_PRIMARY",
    model: str = "grok-4.6",
    hard_estimate_ceiling_tokens: int | None = 2_500,
) -> InvocationEfficiencyPolicy:
    return InvocationEfficiencyPolicy.create(
        policy_id=f"policy-{workload.value.lower()}",
        version="v1",
        workload_class=workload,
        provider=provider,
        route=route,
        model=model,
        reasoning="low",
        one_turn=True,
        exact_input=True,
        skills_enabled=False,
        tools_enabled=False,
        mcp_enabled=False,
        prior_message_count=0,
        max_prompt_bytes=4_096,
        max_context_tokens=2_000,
        max_output_tokens=500,
        max_total_tokens=2_500,
        prompt_contract_version="prompt-v1",
        output_schema_digest=_digest({"schema": 1}),
        allowed_context_identities=("context-v1",),
        allowed_config_identities=("config-v1",),
        hard_estimate_ceiling_tokens=hard_estimate_ceiling_tokens,
        evidence_digest=_digest({"qualification": "fixture"}),
        qualified=True,
    )


def _envelope(
    *,
    cycle_id: str = "00000000-0000-4000-8000-000000000001",
    workload: WorkloadClass = WorkloadClass.CONT_WRITER_PRIMARY,
    candidate_id: str | None = "candidate-1",
    ingest_id: str | None = None,
) -> WorkEnvelope:
    return WorkEnvelope.create(
        cycle_id=cycle_id,
        workload_class=workload,
        admitted_at=T0,
        admission_decision_id=("decision-1" if candidate_id else None),
        candidate_id=candidate_id,
        hypothesis_digest=(_digest({"hypothesis": 1}) if candidate_id else None),
        evidence_package_digest=(_digest({"evidence": 1}) if candidate_id else None),
        ingest_id=ingest_id,
        graphiti_attempt_id=(f"{ingest_id}:1" if ingest_id else None),
    )


def _allocation(
    envelope: WorkEnvelope,
    policy: InvocationEfficiencyPolicy,
    *,
    leaf_ordinal: int = 1,
    request: str = "request-1",
    workload: WorkloadClass | None = None,
    parent_invocation_id: str | None = None,
    prompt_bytes: int = 200,
    config_identity: str = "config-v1",
) -> InvocationAllocation:
    return InvocationAllocation.create(
        envelope_id=envelope.envelope_id,
        cycle_id=envelope.cycle_id,
        leaf_ordinal=leaf_ordinal,
        workload_class=workload or policy.workload_class,
        invocation_policy_digest=policy.canonical_digest,
        provider=policy.provider,
        route=policy.route,
        model=policy.model,
        reasoning=policy.reasoning,
        prompt_contract_version=policy.prompt_contract_version,
        prompt_bytes=prompt_bytes,
        prompt_digest=_digest({"prompt": request}),
        request_digest=_digest({"request": request}),
        output_schema_digest=policy.output_schema_digest,
        max_output_tokens=policy.max_output_tokens,
        context_manifest_digest=_digest({"context": "v1"}),
        context_identity="context-v1",
        config_identity=config_identity,
        one_turn=policy.one_turn,
        exact_input=policy.exact_input,
        skills_enabled=policy.skills_enabled,
        tools_enabled=policy.tools_enabled,
        mcp_enabled=policy.mcp_enabled,
        prior_message_count=policy.prior_message_count,
        allocated_at=T0 + timedelta(seconds=leaf_ordinal),
        recovery_deadline_at=T0 + timedelta(seconds=30 + leaf_ordinal),
        parent_invocation_id=parent_invocation_id,
    )


def _reported(
    allocation: InvocationAllocation,
    *,
    total: int = 125,
    outcome: str = "ACCEPTED",
    completed_at: datetime | None = None,
) -> InvocationTerminal:
    return InvocationTerminal.create(
        invocation_id=allocation.invocation_id,
        outcome=outcome,
        failure_class=None,
        usage_status=UsageStatus.REPORTED,
        components=UsageComponents(
            input_tokens=total - 25,
            output_tokens=20,
            cached_read_tokens=5,
            reasoning_tokens=0,
            context_tokens=100,
            total_tokens=total,
            provenance="PROVIDER_REPORTED",
        ),
        dispatch_at=allocation.allocated_at + timedelta(milliseconds=1),
        completed_at=completed_at or allocation.allocated_at + timedelta(seconds=1),
        observed_at=completed_at or allocation.allocated_at + timedelta(seconds=1),
        provider_telemetry_digest=_digest({"invocation": allocation.invocation_id}),
        raw_telemetry_pointer=f"private://telemetry/{allocation.invocation_id}",
        subscription_cli_chat_not_cash_debited=True,
    )


def _open_and_allocate(
    service: ModelUsageService,
    *,
    envelope: WorkEnvelope | None = None,
    policy: InvocationEfficiencyPolicy | None = None,
) -> tuple[WorkEnvelope, InvocationEfficiencyPolicy, InvocationAllocation]:
    envelope = envelope or _envelope()
    policy = policy or _policy(workload=envelope.workload_class)
    service.register_policy(policy)
    service.open_envelope(envelope)
    allocation = _allocation(envelope, policy)
    service.allocate(allocation, owner_emergency_stop=False)
    return envelope, policy, allocation


def test_hold_or_reject_admission_creates_no_envelope_or_leaf(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.retain_zero_call_admission(
        decision_id="decision-hold",
        decision="HOLD",
        cycle_id="00000000-0000-4000-8000-000000000001",
        recorded_at=T0,
    )
    service.retain_zero_call_admission(
        decision_id="decision-reject",
        decision="REJECT",
        cycle_id="00000000-0000-4000-8000-000000000001",
        recorded_at=T0,
    )

    report = service.report(start=T0, end=T0 + timedelta(minutes=1))

    assert report["envelope_count"] == 0
    assert report["leaf_dispatch_count"] == 0
    assert report["zero_call_admission_counts"] == {"HOLD": 1, "REJECT": 1}


def test_primary_and_fallback_are_distinct_leaves_joined_to_one_outcome(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    envelope, _primary_policy, primary = _open_and_allocate(service)
    fallback_policy = _policy(
        workload=WorkloadClass.CONT_WRITER_FALLBACK,
        provider="cursor-agent-cli",
        route="CONT_FALLBACK",
        model="cursor-pinned",
    )
    service.register_policy(fallback_policy)
    fallback = _allocation(
        envelope,
        fallback_policy,
        leaf_ordinal=2,
        workload=WorkloadClass.CONT_WRITER_FALLBACK,
        request="request-fallback",
        parent_invocation_id=primary.invocation_id,
    )
    service.allocate(fallback, owner_emergency_stop=False)
    service.link_provider_attempt(
        invocation_id=primary.invocation_id,
        provider_attempt_id="provider-primary",
        linked_at=T0 + timedelta(seconds=2),
    )
    service.link_provider_attempt(
        invocation_id=fallback.invocation_id,
        provider_attempt_id="provider-fallback",
        linked_at=T0 + timedelta(seconds=2),
    )
    service.complete(_reported(primary, total=125, outcome="REJECTED_OUTPUT"))
    service.complete(_reported(fallback, total=125, outcome="ACCEPTED_OUTPUT"))
    service.record_work_outcome(
        envelope_id=envelope.envelope_id,
        outcome="ACCEPTED",
        outcome_record_id="draft-outcome-1",
        payload_digest=_digest({"payload": 1}),
        terminal_at=T0 + timedelta(seconds=4),
        accepted_provider_attempt_id="provider-fallback",
    )

    rows = service.query(start=T0, end=T0 + timedelta(minutes=1))["leaves"]

    assert [row["workload_class"] for row in rows] == [
        "CONT_WRITER_PRIMARY",
        "CONT_WRITER_FALLBACK",
    ]
    assert rows[1]["parent_invocation_id"] == primary.invocation_id
    assert {row["work_outcome"] for row in rows} == {"ACCEPTED"}
    assert {row["payload_digest"] for row in rows} == {_digest({"payload": 1})}
    report = service.report(start=T0, end=T0 + timedelta(minutes=1))
    assert report["productive_tokens"] == 125
    assert report["no_result_tokens"] == 125
    assert report["no_result_reasons"] == {"REJECTED_OUTPUT": 125}


def test_rejected_provider_output_is_no_result_usage_not_productivity(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    envelope, _policy_value, allocation = _open_and_allocate(service)
    service.complete(_reported(allocation, outcome="PLANNING_RESIDUE"))
    service.record_work_outcome(
        envelope_id=envelope.envelope_id,
        outcome="REJECT",
        outcome_record_id="draft-outcome-reject",
        payload_digest=None,
        terminal_at=T0 + timedelta(seconds=3),
    )

    report = service.report(start=T0, end=T0 + timedelta(minutes=1))

    assert report["accepted_payload_count"] == 0
    assert report["productive_tokens"] == 0
    assert report["no_result_tokens"] == 125
    assert report["tokens_per_accepted_payload"] is None
    assert report["no_result_reasons"] == {"PLANNING_RESIDUE": 125}


def test_no_result_cycle_joins_durable_backoff_state(tmp_path: Path) -> None:
    service = _service(tmp_path)
    envelope, _policy_value, allocation = _open_and_allocate(service)
    service.complete(_reported(allocation, outcome="REJECTED_OUTPUT"))
    service.record_work_outcome(
        envelope_id=envelope.envelope_id,
        outcome="REJECT",
        outcome_record_id="draft-outcome-reject",
        payload_digest=None,
        terminal_at=T0 + timedelta(seconds=3),
        cycle_outcome="UNPRODUCTIVE_PROVIDER",
        route_circuit_state="CLOSED",
        route_circuit_reason="FIRST_NO_RESULT_BACKOFF",
    )

    row = service.query(start=T0, end=T0 + timedelta(minutes=1))["envelopes"][0]

    assert row["cycle_outcome"] == "UNPRODUCTIVE_PROVIDER"
    assert row["route_circuit_reason"] == "FIRST_NO_RESULT_BACKOFF"


def test_reported_components_validate_without_context_double_counting(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    _envelope_value, _policy_value, allocation = _open_and_allocate(service)
    service.complete(_reported(allocation, total=125))

    report = service.report(start=T0, end=T0 + timedelta(minutes=1))

    assert report["observed_total_tokens"] == 125
    assert report["context_tokens"] == 100
    invalid_envelope = _envelope(
        cycle_id="00000000-0000-4000-8000-000000000099",
        candidate_id="candidate-invalid",
    )
    service.open_envelope(invalid_envelope)
    invalid_allocation = _allocation(invalid_envelope, _policy_value, request="invalid")
    service.allocate(invalid_allocation, owner_emergency_stop=False)
    service.complete(
        InvocationTerminal.create(
            invocation_id=invalid_allocation.invocation_id,
            outcome="ACCEPTED",
            failure_class=None,
            usage_status=UsageStatus.REPORTED,
            components=UsageComponents(
                input_tokens=100,
                output_tokens=20,
                cached_read_tokens=5,
                cached_write_tokens=0,
                reasoning_tokens=0,
                context_tokens=100,
                total_tokens=224,
                provenance="PROVIDER_REPORTED",
            ),
            dispatch_at=T0 + timedelta(seconds=2),
            completed_at=T0 + timedelta(seconds=3),
            observed_at=T0 + timedelta(seconds=3),
            provider_telemetry_digest=_digest({"invalid": 1}),
            raw_telemetry_pointer="private://invalid",
            subscription_cli_chat_not_cash_debited=True,
        )
    )
    invalid_row = service.query(start=T0, end=T0 + timedelta(minutes=1))["leaves"][1]
    assert invalid_row["usage_status"] == "INVALID"
    assert invalid_row["failure_class"] == "REPORTED_COMPONENT_TOTAL_INVALID"
    assert (
        service.report(start=T0, end=T0 + timedelta(minutes=1))["observed_total_tokens"]
        == 125
    )


def test_estimate_is_explicit_and_unbounded_missing_usage_opens_only_route(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    _envelope_value, policy, allocation = _open_and_allocate(service)
    service.complete(
        InvocationTerminal.create(
            invocation_id=allocation.invocation_id,
            outcome="REJECTED_OUTPUT",
            failure_class=None,
            usage_status=UsageStatus.ESTIMATED,
            components=UsageComponents(
                total_tokens=2_500, provenance="BOUNDED_ESTIMATE"
            ),
            dispatch_at=T0 + timedelta(seconds=1),
            completed_at=T0 + timedelta(seconds=2),
            observed_at=T0 + timedelta(seconds=2),
            estimate_policy_digest=policy.canonical_digest,
            estimate_calculation="hard_estimate_ceiling_tokens=2500",
            subscription_cli_chat_not_cash_debited=True,
        )
    )
    second_envelope = _envelope(
        cycle_id="00000000-0000-4000-8000-000000000002",
        candidate_id="candidate-2",
    )
    service.open_envelope(second_envelope)
    second = _allocation(second_envelope, policy, request="request-2")
    service.allocate(second, owner_emergency_stop=False)
    service.complete(
        InvocationTerminal.create(
            invocation_id=second.invocation_id,
            outcome="TRANSPORT_LOST",
            failure_class="MISSING_TELEMETRY",
            usage_status=UsageStatus.UNREPORTED,
            components=UsageComponents(provenance="UNAVAILABLE"),
            dispatch_at=T0 + timedelta(seconds=5),
            completed_at=T0 + timedelta(seconds=6),
            observed_at=T0 + timedelta(seconds=6),
            subscription_cli_chat_not_cash_debited=True,
        )
    )

    report = service.report(start=T0, end=T0 + timedelta(minutes=1))

    assert report["estimated_tokens"] == 2_500
    assert report["unresolved_invocation_count"] == 1
    assert service.route_state("CONT_PRIMARY")["state"] == "OPEN"
    assert service.route_state("GRAPHITI_EMBEDDING")["state"] == "CLOSED"
    with pytest.raises(ModelUsageAdmissionError, match="unresolved usage"):
        service.allocate(
            _allocation(
                second_envelope,
                policy,
                leaf_ordinal=2,
                request="request-3",
            ),
            owner_emergency_stop=False,
        )


def test_proved_pre_dispatch_failure_is_explicit_zero(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _envelope_value, _policy_value, allocation = _open_and_allocate(service)
    service.complete(
        InvocationTerminal.create(
            invocation_id=allocation.invocation_id,
            outcome="EXECUTABLE_NOT_FOUND",
            failure_class="LOCAL_EXECUTABLE",
            usage_status=UsageStatus.REPORTED,
            components=UsageComponents(total_tokens=0, provenance="CLI_DERIVED"),
            dispatch_at=None,
            completed_at=T0 + timedelta(seconds=2),
            observed_at=T0 + timedelta(seconds=2),
            pre_dispatch_zero_proved=True,
            subscription_cli_chat_not_cash_debited=True,
        )
    )

    row = service.query(start=T0, end=T0 + timedelta(minutes=1))["leaves"][0]

    assert row["total_tokens"] == 0
    assert row["pre_dispatch_zero_proved"] is True


def test_telemetry_digest_mismatch_is_retained_invalid_and_opens_route(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    _envelope_value, _policy_value, allocation = _open_and_allocate(service)
    terminal = _reported(allocation)
    service.complete(
        terminal,
        provider_telemetry={"different": "content"},
    )

    row = service.query(start=T0, end=T0 + timedelta(minutes=1))["leaves"][0]

    assert row["usage_status"] == "INVALID"
    assert row["failure_class"] == "TELEMETRY_DIGEST_MISMATCH"
    assert service.route_state("CONT_PRIMARY")["state"] == "OPEN"
    connection = sqlite3.connect(tmp_path / "unpublished.sqlite3")
    telemetry = json.loads(
        connection.execute(
            "SELECT record_json FROM model_provider_telemetry"
        ).fetchone()[0]
    )
    connection.close()
    assert telemetry["provider_telemetry"] == {"different": "content"}
    assert (
        service.report(start=T0, end=T0 + timedelta(minutes=1))["observed_total_tokens"]
        == 0
    )


def test_duplicate_request_digest_is_stopped_before_dispatch(tmp_path: Path) -> None:
    service = _service(tmp_path)
    envelope, policy, first = _open_and_allocate(service)

    with pytest.raises(ModelUsageAdmissionError, match="duplicate request"):
        service.allocate(
            _allocation(
                envelope,
                policy,
                leaf_ordinal=2,
                request="request-1",
            ),
            owner_emergency_stop=False,
        )

    assert (
        service.report(start=T0, end=T0 + timedelta(minutes=1))["allocation_count"]
        == 1
    )
    assert first.invocation_id


def test_policy_preflight_and_post_dispatch_breach_are_route_local(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    envelope = _envelope()
    policy = _policy()
    service.register_policy(policy)
    service.open_envelope(envelope)
    with pytest.raises(ModelUsageAdmissionError, match="prompt bytes"):
        service.allocate(
            _allocation(envelope, policy, prompt_bytes=4_097),
            owner_emergency_stop=False,
        )
    with pytest.raises(ModelUsageAdmissionError, match="config identity"):
        service.allocate(
            _allocation(envelope, policy, config_identity="unqualified-config-v2"),
            owner_emergency_stop=False,
        )

    allocation = _allocation(envelope, policy, prompt_bytes=4_096)
    service.allocate(allocation, owner_emergency_stop=False)
    service.complete(_reported(allocation, total=2_501))

    row = service.query(start=T0, end=T0 + timedelta(minutes=1))["leaves"][0]
    assert row["policy_breach"] == "MAX_TOTAL_TOKENS_EXCEEDED"
    assert service.route_state("CONT_PRIMARY")["state"] == "OPEN"


@pytest.mark.parametrize(
    "work_outcome",
    ["GRAPHITI_SUCCESS_ZERO_PROPOSALS", "GRAPHITI_PARTIAL"],
)
def test_graphiti_chat_and_embedding_are_distinct_and_terminal_ingests_are_valid(
    tmp_path: Path, work_outcome: str
) -> None:
    service = _service(tmp_path)
    envelope = _envelope(
        workload=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        candidate_id=None,
        ingest_id="ingest-1",
    )
    service.open_envelope(envelope)
    chat_policy = _policy(
        workload=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        provider="cursor-agent-cli",
        route="GRAPHITI_CHAT",
        model="cursor-pinned",
    )
    embedding_policy = _policy(
        workload=WorkloadClass.GRAPHITI_EMBEDDING,
        provider="openrouter",
        route="GRAPHITI_EMBEDDING",
        model="openai/text-embedding-3-small",
    )
    service.register_policy(chat_policy)
    service.register_policy(embedding_policy)
    chat = _allocation(envelope, chat_policy)
    embedding = _allocation(
        envelope,
        embedding_policy,
        leaf_ordinal=2,
        request="embedding-request",
        workload=WorkloadClass.GRAPHITI_EMBEDDING,
        parent_invocation_id=chat.invocation_id,
    )
    service.allocate(chat, owner_emergency_stop=False)
    service.allocate(embedding, owner_emergency_stop=False)
    service.complete(_reported(chat, total=125, outcome="COMPLETE"))
    service.complete(
        InvocationTerminal.create(
            invocation_id=embedding.invocation_id,
            outcome="COMPLETE",
            failure_class=None,
            usage_status=UsageStatus.REPORTED,
            components=UsageComponents(
                input_tokens=40,
                total_tokens=40,
                provenance="PROVIDER_REPORTED",
            ),
            dispatch_at=T0 + timedelta(seconds=2),
            completed_at=T0 + timedelta(seconds=3),
            observed_at=T0 + timedelta(seconds=3),
            provider_telemetry_digest=_digest({"embedding": 1}),
            raw_telemetry_pointer="private://embedding/1",
            od_011_reference="OD-011:EVALUATION",
            subscription_cli_chat_not_cash_debited=False,
        )
    )
    service.record_work_outcome(
        envelope_id=envelope.envelope_id,
        outcome=work_outcome,
        outcome_record_id="graphiti-attempt-1",
        payload_digest=None,
        terminal_at=T0 + timedelta(seconds=4),
        retained_proposal_count=0,
    )

    report = service.report(start=T0, end=T0 + timedelta(minutes=1))

    assert report["graphiti_valid_ingest_count"] == 1
    assert report["graphiti_tokens_per_valid_ingest"] == {
        "numerator": 165,
        "denominator": 1,
    }
    assert report["graphiti_tokens_per_retained_proposal"] is None
    assert report["workload_totals"]["GRAPHITI_CHAT_PRIMARY"] == 125
    assert report["workload_totals"]["GRAPHITI_EMBEDDING"] == 40


def test_parent_and_child_totals_are_not_double_counted(tmp_path: Path) -> None:
    service = _service(tmp_path)
    envelope, _primary_policy, primary = _open_and_allocate(service)
    fallback_policy = _policy(
        workload=WorkloadClass.CONT_WRITER_FALLBACK,
        provider="cursor-agent-cli",
        route="CONT_FALLBACK",
        model="cursor-pinned",
    )
    service.register_policy(fallback_policy)
    fallback = _allocation(
        envelope,
        fallback_policy,
        leaf_ordinal=2,
        request="fallback",
        parent_invocation_id=primary.invocation_id,
    )
    service.allocate(fallback, owner_emergency_stop=False)
    service.complete(_reported(primary, total=125))
    service.complete(_reported(fallback, total=125))

    report = service.report(start=T0, end=T0 + timedelta(minutes=1))

    assert report["observed_total_tokens"] == 250
    assert report["envelope_allocated_tokens"] == 250


def test_fixed_buckets_include_zeros_rolling_views_and_daily_totals(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    _envelope_value, policy, first = _open_and_allocate(service)
    service.complete(
        _reported(first, total=125, completed_at=T0 + timedelta(seconds=10))
    )
    second_envelope = _envelope(
        cycle_id="00000000-0000-4000-8000-000000000002",
        candidate_id="candidate-2",
    )
    service.open_envelope(second_envelope)
    second = _allocation(second_envelope, policy, request="second")
    service.allocate(second, owner_emergency_stop=False)
    service.complete(
        _reported(
            second, total=125, completed_at=T0 + timedelta(minutes=10, seconds=10)
        )
    )

    report = service.report(
        start=T0,
        end=T0 + timedelta(minutes=15),
        bucket_seconds=300,
    )

    assert [bucket["observed_total_tokens"] for bucket in report["fixed_buckets"]] == [
        125,
        0,
        125,
    ]
    assert report["utc_day_totals"] == {"2026-08-24": 250}
    assert report["rolling_300_at_dispatch"] == [
        {"invocation_id": first.invocation_id, "observed_total_tokens": 0},
        {"invocation_id": second.invocation_id, "observed_total_tokens": 0},
    ]


def test_fixed_buckets_are_utc_aligned_for_unaligned_proof_window(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    _envelope_value, _policy_value, allocation = _open_and_allocate(service)
    service.complete(_reported(allocation, completed_at=T0 + timedelta(seconds=2)))

    report = service.report(
        start=T0 + timedelta(milliseconds=500),
        end=T0 + timedelta(minutes=5, milliseconds=500),
        bucket_seconds=300,
    )

    assert [bucket["window_start"] for bucket in report["fixed_buckets"]] == [
        "2026-08-24T10:00:00.000000Z",
        "2026-08-24T10:05:00.000000Z",
    ]
    assert [bucket["observed_total_tokens"] for bucket in report["fixed_buckets"]] == [
        125,
        0,
    ]


def test_more_than_daily_500k_is_alerted_but_not_an_admission_gate(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    baseline = _policy()
    policy = InvocationEfficiencyPolicy.create(
        **{
            field: getattr(baseline, field)
            for field in baseline.__dataclass_fields__
            if field
            not in {
                "canonical_digest",
                "max_total_tokens",
                "max_output_tokens",
                "hard_estimate_ceiling_tokens",
            }
        },
        max_total_tokens=300_000,
        max_output_tokens=20_000,
        hard_estimate_ceiling_tokens=300_000,
    )
    service.register_policy(policy)
    for index in range(2):
        envelope = _envelope(
            cycle_id=f"00000000-0000-4000-8000-{index + 10:012d}",
            candidate_id=f"candidate-{index + 10}",
        )
        service.open_envelope(envelope)
        allocation = _allocation(envelope, policy, request=f"request-{index + 10}")
        service.allocate(allocation, owner_emergency_stop=False)
        service.complete(
            InvocationTerminal.create(
                invocation_id=allocation.invocation_id,
                outcome="ACCEPTED",
                failure_class=None,
                usage_status=UsageStatus.REPORTED,
                components=UsageComponents(
                    input_tokens=260_000,
                    output_tokens=10_000,
                    total_tokens=270_000,
                    provenance="PROVIDER_REPORTED",
                ),
                dispatch_at=T0 + timedelta(minutes=index),
                completed_at=T0 + timedelta(minutes=index, seconds=10),
                observed_at=T0 + timedelta(minutes=index, seconds=10),
                provider_telemetry_digest=_digest({"large": index}),
                raw_telemetry_pointer=f"private://large/{index}",
                subscription_cli_chat_not_cash_debited=True,
            )
        )

    report = service.report(start=T0, end=T0 + timedelta(days=1))

    assert report["observed_total_tokens"] == 540_000
    assert report["daily_500k_alert"] is True
    assert report["normal_daily_hard_cut"] is None
    assert report["leaf_dispatch_count"] == 2


def test_owner_emergency_stop_overrides_otherwise_valid_allocation(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    envelope = _envelope()
    policy = _policy()
    service.register_policy(policy)
    service.open_envelope(envelope)

    with pytest.raises(ModelUsageAdmissionError, match="emergency stop"):
        service.allocate(_allocation(envelope, policy), owner_emergency_stop=True)


def test_restart_recovery_retains_unresolved_leaf_without_duplication(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    first_service = ModelUsageService(str(path))
    _envelope_value, _policy_value, _allocation_value = _open_and_allocate(
        first_service
    )
    restarted = ModelUsageService(str(path))
    restarted.recover_unresolved(observed_at=T0 + timedelta(minutes=1))
    restarted.recover_unresolved(observed_at=T0 + timedelta(minutes=2))
    report = restarted.report(start=T0, end=T0 + timedelta(minutes=3))

    assert report["allocation_count"] == 1
    assert report["actual_provider_dispatch_count"] == 0
    assert report["unresolved_invocation_count"] == 1
    row = restarted.query(start=T0, end=T0 + timedelta(minutes=3))["leaves"][0]
    assert row["usage_status"] == "AMBIGUOUS"
    assert row["total_tokens"] is None
    assert service_row_count(path, "model_invocation_terminals") == 1


def test_restart_recovery_does_not_claim_a_live_invocation(tmp_path: Path) -> None:
    path = tmp_path / "unpublished.sqlite3"
    active = ModelUsageService(str(path))
    _envelope_value, _policy_value, allocation = _open_and_allocate(active)
    active.observe_transport(
        invocation_id=allocation.invocation_id,
        observed_at=T0 + timedelta(seconds=2),
        state="DISPATCH_STARTED",
        evidence_digest=_digest({"live": True}),
    )

    concurrent = ModelUsageService(str(path))
    assert concurrent.recover_unresolved(
        observed_at=T0 + timedelta(seconds=3)
    ) == 0
    active.complete(_reported(allocation, completed_at=T0 + timedelta(seconds=4)))
    assert active.query(start=T0, end=T0 + timedelta(minutes=1))["leaves"][0][
        "usage_status"
    ] == "REPORTED"


def test_concurrent_recovery_is_idempotent_at_the_retained_deadline(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    service = ModelUsageService(str(path))
    _envelope_value, _policy_value, allocation = _open_and_allocate(service)
    service.observe_transport(
        invocation_id=allocation.invocation_id,
        observed_at=T0 + timedelta(seconds=2),
        state="DISPATCH_STARTED",
        evidence_digest=_digest({"concurrent": True}),
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(
            pool.map(
                lambda seconds: ModelUsageService(str(path)).recover_unresolved(
                    observed_at=T0 + timedelta(seconds=seconds)
                ),
                (40, 45),
            )
        )

    assert sum(results) >= 2
    assert service_row_count(path, "model_invocation_terminals") == 1
    assert service_row_count(path, "model_work_outcomes") == 1
    leaf = service.query(start=T0, end=T0 + timedelta(minutes=1))["leaves"][0]
    assert leaf["completed_at"] == "2026-08-24T10:00:31.000000Z"
    assert leaf["work_outcome_terminal_at"] == "2026-08-24T10:00:31.000000Z"


def test_later_provider_telemetry_appends_reconciliation_without_editing_history(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    _envelope_value, _policy_value, allocation = _open_and_allocate(service)
    service.complete(
        InvocationTerminal.create(
            invocation_id=allocation.invocation_id,
            outcome="TRANSPORT_LOST",
            failure_class="MISSING_TELEMETRY",
            usage_status=UsageStatus.UNREPORTED,
            components=UsageComponents(provenance="UNAVAILABLE"),
            dispatch_at=T0 + timedelta(seconds=1),
            completed_at=T0 + timedelta(seconds=2),
            observed_at=T0 + timedelta(seconds=2),
            subscription_cli_chat_not_cash_debited=True,
        )
    )
    service.reconcile(
        invocation_id=allocation.invocation_id,
        components=UsageComponents(
            input_tokens=100,
            output_tokens=20,
            cached_read_tokens=5,
            total_tokens=125,
            provenance="PROVIDER_REPORTED",
        ),
        provider_telemetry={"late": "valid"},
        observed_at=T0 + timedelta(minutes=5),
        raw_telemetry_pointer="private://late/1",
    )

    historical = service.query(start=T0, end=T0 + timedelta(minutes=1))["leaves"][0]
    row = service.query(start=T0, end=T0 + timedelta(minutes=6))["leaves"][0]

    assert historical["usage_status"] == "UNREPORTED"
    assert historical["reconciliation_usage_status"] is None
    assert row["usage_status"] == "REPORTED"
    assert row["total_tokens"] == 125
    assert row["terminal_usage_status"] == "UNREPORTED"
    assert row["reconciliation_usage_status"] == "REPORTED"
    assert row["reconciled_at"] == "2026-08-24T10:05:00.000000Z"
    assert service.route_state("CONT_PRIMARY")["state"] == "CLOSED"
    assert (
        service_row_count(
            tmp_path / "unpublished.sqlite3", "model_invocation_terminals"
        )
        == 1
    )
    assert (
        service_row_count(
            tmp_path / "unpublished.sqlite3", "model_usage_reconciliations"
        )
        == 1
    )
    assert (
        service_row_count(tmp_path / "unpublished.sqlite3", "model_provider_telemetry")
        == 1
    )


def test_reconciled_policy_breach_keeps_the_route_open(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _envelope_value, _policy_value, allocation = _open_and_allocate(service)
    service.complete(
        InvocationTerminal.create(
            invocation_id=allocation.invocation_id,
            outcome="TRANSPORT_LOST",
            failure_class="MISSING_TELEMETRY",
            usage_status=UsageStatus.UNREPORTED,
            components=UsageComponents(provenance="UNAVAILABLE"),
            dispatch_at=T0 + timedelta(seconds=1),
            completed_at=T0 + timedelta(seconds=2),
            observed_at=T0 + timedelta(seconds=2),
            subscription_cli_chat_not_cash_debited=True,
        )
    )
    service.reconcile(
        invocation_id=allocation.invocation_id,
        components=UsageComponents(
            input_tokens=2_900,
            output_tokens=100,
            total_tokens=3_000,
            provenance="PROVIDER_REPORTED",
        ),
        provider_telemetry={"late": "over-limit"},
        observed_at=T0 + timedelta(minutes=5),
        raw_telemetry_pointer="private://late/over-limit",
    )

    row = service.query(start=T0, end=T0 + timedelta(minutes=6))["leaves"][0]
    assert row["policy_breach"] == "MAX_TOTAL_TOKENS_EXCEEDED"
    assert service.route_state("CONT_PRIMARY")["state"] == "OPEN"


def test_reconciliation_closes_only_after_every_route_uncertainty_is_resolved(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    envelope = _envelope(
        workload=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        candidate_id=None,
        ingest_id="ingest-reconciliation",
    )
    policy = _policy(
        workload=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        provider="cursor-agent-cli",
        route="GRAPHITI_CHAT",
        model="cursor-pinned",
    )
    _envelope_value, _policy_value, first = _open_and_allocate(
        service, envelope=envelope, policy=policy
    )
    second = _allocation(
        envelope,
        policy,
        leaf_ordinal=2,
        request="request-2",
    )
    service.allocate(second, owner_emergency_stop=False)
    for ordinal, allocation in enumerate((second, first), start=1):
        service.complete(
            InvocationTerminal.create(
                invocation_id=allocation.invocation_id,
                outcome="TRANSPORT_LOST",
                failure_class="MISSING_TELEMETRY",
                usage_status=UsageStatus.UNREPORTED,
                components=UsageComponents(provenance="UNAVAILABLE"),
                dispatch_at=T0 + timedelta(seconds=ordinal),
                completed_at=T0 + timedelta(seconds=ordinal + 2),
                observed_at=T0 + timedelta(seconds=ordinal + 2),
                subscription_cli_chat_not_cash_debited=True,
            )
        )

    for ordinal, allocation in enumerate((first, second), start=1):
        service.reconcile(
            invocation_id=allocation.invocation_id,
            components=UsageComponents(
                input_tokens=100,
                output_tokens=25,
                total_tokens=125,
                provenance="PROVIDER_REPORTED",
            ),
            provider_telemetry={"late": ordinal},
            observed_at=T0 + timedelta(minutes=ordinal),
            raw_telemetry_pointer=f"private://late/{ordinal}",
        )
        assert service.route_state("GRAPHITI_CHAT")["state"] == (
            "OPEN" if ordinal == 1 else "CLOSED"
        )


def test_reconciliation_does_not_clear_an_earlier_policy_breach(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    envelope = _envelope(
        workload=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        candidate_id=None,
        ingest_id="ingest-policy-breach",
    )
    policy = _policy(
        workload=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        provider="cursor-agent-cli",
        route="GRAPHITI_CHAT",
        model="cursor-pinned",
    )
    _envelope_value, _policy_value, breached = _open_and_allocate(
        service, envelope=envelope, policy=policy
    )
    uncertain = _allocation(
        envelope,
        policy,
        leaf_ordinal=2,
        request="request-uncertain",
    )
    service.allocate(uncertain, owner_emergency_stop=False)
    service.complete(_reported(breached, total=2_501))
    service.complete(
        InvocationTerminal.create(
            invocation_id=uncertain.invocation_id,
            outcome="TRANSPORT_LOST",
            failure_class="MISSING_TELEMETRY",
            usage_status=UsageStatus.UNREPORTED,
            components=UsageComponents(provenance="UNAVAILABLE"),
            dispatch_at=T0 + timedelta(seconds=2),
            completed_at=T0 + timedelta(seconds=4),
            observed_at=T0 + timedelta(seconds=4),
            subscription_cli_chat_not_cash_debited=True,
        )
    )
    service.reconcile(
        invocation_id=uncertain.invocation_id,
        components=UsageComponents(
            input_tokens=100,
            output_tokens=25,
            total_tokens=125,
            provenance="PROVIDER_REPORTED",
        ),
        provider_telemetry={"late": "valid"},
        observed_at=T0 + timedelta(minutes=1),
        raw_telemetry_pointer="private://late/valid",
    )

    assert service.route_state("GRAPHITI_CHAT")["state"] == "OPEN"


def test_cont_usage_circuit_uses_the_canonical_governor_route(tmp_path: Path) -> None:
    from newsroom.control_plane.cycle_governor import DurableCycleGovernor

    path = tmp_path / "unpublished.sqlite3"
    DurableCycleGovernor(str(path))
    service = ModelUsageService(str(path))
    _envelope_value, policy, allocation = _open_and_allocate(service)
    service.complete(
        InvocationTerminal.create(
            invocation_id=allocation.invocation_id,
            outcome="TRANSPORT_LOST",
            failure_class="MISSING_TELEMETRY",
            usage_status=UsageStatus.UNREPORTED,
            components=UsageComponents(provenance="UNAVAILABLE"),
            dispatch_at=T0 + timedelta(seconds=1),
            completed_at=T0 + timedelta(seconds=2),
            observed_at=T0 + timedelta(seconds=2),
            subscription_cli_chat_not_cash_debited=True,
        )
    )

    connection = sqlite3.connect(path)
    routes = connection.execute(
        "SELECT route,state FROM unpublished_route_circuits ORDER BY route"
    ).fetchall()
    connection.execute(
        "UPDATE unpublished_route_circuits SET state='CLOSED' WHERE route='CONT'"
    )
    connection.commit()
    connection.close()
    assert routes == [("CONT", "OPEN")]
    assert service.route_state("CONT_PRIMARY")["state"] == "OPEN"

    later_envelope = _envelope(
        cycle_id="00000000-0000-4000-8000-000000000099",
        candidate_id="candidate-after-health",
    )
    service.open_envelope(later_envelope)
    with pytest.raises(ModelUsageAdmissionError, match="unresolved usage"):
        service.allocate(
            _allocation(later_envelope, policy, request="after-health"),
            owner_emergency_stop=False,
        )
    service.reconcile(
        invocation_id=allocation.invocation_id,
        components=UsageComponents(
            input_tokens=100,
            output_tokens=25,
            total_tokens=125,
            provenance="PROVIDER_REPORTED",
        ),
        provider_telemetry={"late": "canonical-route"},
        observed_at=T0 + timedelta(minutes=1),
        raw_telemetry_pointer="private://late/canonical-route",
    )
    service.allocate(
        _allocation(later_envelope, policy, request="after-health"),
        owner_emergency_stop=False,
    )


def test_usage_windows_are_sliced_by_terminal_event_time(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _envelope_value, _policy_value, allocation = _open_and_allocate(service)
    service.complete(
        _reported(
            allocation,
            total=125,
            completed_at=T0 + timedelta(minutes=1, seconds=10),
        )
    )

    first = service.report(start=T0, end=T0 + timedelta(minutes=1))
    second = service.report(
        start=T0 + timedelta(minutes=1),
        end=T0 + timedelta(minutes=2),
    )

    assert first["observed_total_tokens"] == 0
    assert first["fixed_buckets"][0]["observed_total_tokens"] == 0
    assert second["observed_total_tokens"] == 125
    assert second["fixed_buckets"][0]["observed_total_tokens"] == 125
    assert second["utc_day_totals"] == {"2026-08-24": 125}


def test_work_outcome_is_visible_in_its_own_cross_bucket_window(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    envelope, _policy_value, allocation = _open_and_allocate(service)
    service.complete(
        _reported(
            allocation,
            completed_at=T0 + timedelta(minutes=4, seconds=59),
            outcome="ACCEPTED_OUTPUT",
        )
    )
    service.record_work_outcome(
        envelope_id=envelope.envelope_id,
        outcome="ACCEPTED",
        outcome_record_id="draft-cross-window",
        payload_digest=_digest({"payload": "cross-window"}),
        terminal_at=T0 + timedelta(minutes=5, seconds=1),
    )

    second = service.report(
        start=T0 + timedelta(minutes=5),
        end=T0 + timedelta(minutes=10),
    )
    buckets = list(
        csv.DictReader(
            io.StringIO(
                service.export_bucket_csv(
                    start=T0 + timedelta(minutes=5),
                    end=T0 + timedelta(minutes=10),
                )
            )
        )
    )
    assert second["accepted_payload_count"] == 1
    assert buckets[0]["minted_reported"] == "1"
    short_rows = list(
        csv.DictReader(
            io.StringIO(
                service.export_bucket_csv(
                    start=T0,
                    end=T0 + timedelta(minutes=5),
                )
            )
        )
    )
    long_rows = list(
        csv.DictReader(
            io.StringIO(
                service.export_bucket_csv(
                    start=T0,
                    end=T0 + timedelta(minutes=10),
                )
            )
        )
    )
    assert short_rows[0]["productive_tokens"] == long_rows[0]["productive_tokens"]
    assert short_rows[0]["no_result_tokens"] == long_rows[0]["no_result_tokens"]
    assert short_rows[0]["productive_tokens"] == "0"
    assert short_rows[0]["no_result_tokens"] == "125"


def test_deterministic_csv_export_reconciles_leaf_count_and_uncertainty(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    _envelope_value, _policy_value, allocation = _open_and_allocate(service)
    service.complete(_reported(allocation))

    first = service.export_csv(start=T0, end=T0 + timedelta(minutes=1))
    second = service.export_csv(start=T0, end=T0 + timedelta(minutes=1))
    rows = list(csv.DictReader(io.StringIO(first)))

    assert first == second
    assert len(rows) == 1
    assert rows[0]["invocation_id"] == allocation.invocation_id
    assert rows[0]["usage_status"] == "REPORTED"
    assert rows[0]["uncertainty"] == ""
    assert (
        service.report(start=T0, end=T0 + timedelta(minutes=1))[
            "leaf_dispatch_count_reconciles"
        ]
        is True
    )
    bucket_rows = list(
        csv.DictReader(
            io.StringIO(
                service.export_bucket_csv(
                    start=T0,
                    end=T0 + timedelta(minutes=10),
                )
            )
        )
    )
    assert len(bucket_rows) == 2
    assert bucket_rows[0]["grok_model_calls"] == "1"
    assert bucket_rows[0]["grok_total_tokens"] == "125"
    assert bucket_rows[1]["grok_total_tokens"] == "0"


def test_estimate_requires_the_separately_qualified_hard_ceiling(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    policy = _policy(hard_estimate_ceiling_tokens=None)
    _envelope_value, _policy_value, allocation = _open_and_allocate(
        service, policy=policy
    )

    with pytest.raises(ModelUsageIntegrityError, match="bounded estimate evidence"):
        service.complete(
            InvocationTerminal.create(
                invocation_id=allocation.invocation_id,
                outcome="TRANSPORT_LOST",
                failure_class="MISSING_TELEMETRY",
                usage_status=UsageStatus.ESTIMATED,
                components=UsageComponents(
                    total_tokens=policy.max_total_tokens,
                    provenance="BOUNDED_ESTIMATE",
                ),
                dispatch_at=T0 + timedelta(seconds=1),
                completed_at=T0 + timedelta(seconds=2),
                observed_at=T0 + timedelta(seconds=2),
                subscription_cli_chat_not_cash_debited=True,
                estimate_policy_digest=policy.canonical_digest,
                estimate_calculation="unproved policy maximum",
            )
        )


def test_graphiti_provider_observer_persists_chat_and_embedding_leaves(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    envelope = _envelope(
        workload=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        candidate_id=None,
        ingest_id="ingest-observed",
    )
    service.open_envelope(envelope)
    for policy in (
        InvocationEfficiencyPolicy.create(
            policy_id="graphiti-chat-primary",
            version="v1",
            workload_class=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
            provider="cursor-agent-cli",
            route=GRAPHITI_CHAT_PRIMARY_ROUTE,
            model=CURSOR_AGENT_MODEL_ID,
            reasoning="provider-default",
            one_turn=True,
            exact_input=True,
            skills_enabled=False,
            tools_enabled=False,
            mcp_enabled=False,
            prior_message_count=0,
            max_prompt_bytes=4_096,
            max_context_tokens=2_000,
            max_output_tokens=500,
            max_total_tokens=2_500,
            prompt_contract_version=GRAPHITI_PROMPT_COMPONENT.component_version,
            output_schema_digest=_digest({"response_schema": "UNSTRUCTURED"}),
            allowed_context_identities=(GRAPHITI_CONTEXT_IDENTITY,),
            allowed_config_identities=("graphiti-cli-command-v1",),
            hard_estimate_ceiling_tokens=2_500,
            evidence_digest=_digest({"graphiti": "chat"}),
            qualified=True,
        ),
        InvocationEfficiencyPolicy.create(
            policy_id="graphiti-embedding",
            version="v1",
            workload_class=WorkloadClass.GRAPHITI_EMBEDDING,
            provider="openrouter",
            route=GRAPHITI_EMBEDDING_ROUTE,
            model=OPENROUTER_EMBEDDING_SLUG,
            reasoning="none",
            one_turn=True,
            exact_input=True,
            skills_enabled=False,
            tools_enabled=False,
            mcp_enabled=False,
            prior_message_count=0,
            max_prompt_bytes=4_096,
            max_context_tokens=2_000,
            max_output_tokens=500,
            max_total_tokens=2_500,
            prompt_contract_version=GRAPHITI_PROMPT_COMPONENT.component_version,
            output_schema_digest=_digest(
                {"schema": "embedding-vector", "model": OPENROUTER_EMBEDDING_SLUG}
            ),
            allowed_context_identities=(GRAPHITI_CONTEXT_IDENTITY,),
            allowed_config_identities=("graphiti-embedding-command-v1",),
            hard_estimate_ceiling_tokens=2_500,
            evidence_digest=_digest({"graphiti": "embedding"}),
            qualified=True,
        ),
    ):
        service.register_policy(policy)
    observer = GraphitiModelUsageObserver(
        service=service,
        envelope=envelope,
        clock=lambda: T0 + timedelta(seconds=10),
    )
    chat = observer.before_cli_invocation(
        provider="cursor-agent-cli",
        model=CURSOR_AGENT_MODEL_ID,
        prompt="chat prompt",
        schema=None,
    )
    observer.after_cli_invocation(
        chat,
        outcome="COMPLETE",
        usage={
            "usage_basis": "PROVIDER_REPORTED",
            "input_tokens": 10,
            "output_tokens": 2,
            "cached_read_tokens": 0,
            "cached_write_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 12,
        },
    )
    embedding = observer.before_embedding_invocation(
        provider="openrouter",
        model=OPENROUTER_EMBEDDING_SLUG,
        input_data=["embedding input"],
    )
    observer.after_embedding_invocation(
        embedding,
        outcome="COMPLETE",
        usage={
            "usage_basis": "PROVIDER_REPORTED",
            "input_tokens": 4,
            "output_tokens": 0,
            "cached_read_tokens": 0,
            "cached_write_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 4,
            "provider_telemetry": {"request_id": "embedding-1", "total_tokens": 4},
        },
    )

    leaves = service.query(start=T0, end=T0 + timedelta(minutes=1))["leaves"]

    assert [leaf["workload_class"] for leaf in leaves] == [
        "GRAPHITI_CHAT_PRIMARY",
        "GRAPHITI_EMBEDDING",
    ]
    assert [leaf["total_tokens"] for leaf in leaves] == [12, 4]


def test_graphiti_missing_telemetry_without_a_hard_bound_is_unreported(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    envelope = _envelope(
        workload=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        candidate_id=None,
        ingest_id="ingest-unbounded",
    )
    service.open_envelope(envelope)
    service.register_policy(
        InvocationEfficiencyPolicy.create(
            policy_id="graphiti-chat-unbounded",
            version="v1",
            workload_class=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
            provider="cursor-agent-cli",
            route=GRAPHITI_CHAT_PRIMARY_ROUTE,
            model=CURSOR_AGENT_MODEL_ID,
            reasoning="provider-default",
            one_turn=True,
            exact_input=True,
            skills_enabled=False,
            tools_enabled=False,
            mcp_enabled=False,
            prior_message_count=0,
            max_prompt_bytes=4_096,
            max_context_tokens=2_000,
            max_output_tokens=500,
            max_total_tokens=2_500,
            prompt_contract_version=GRAPHITI_PROMPT_COMPONENT.component_version,
            output_schema_digest=_digest({"response_schema": "UNSTRUCTURED"}),
            allowed_context_identities=(GRAPHITI_CONTEXT_IDENTITY,),
            allowed_config_identities=("graphiti-cli-command-v1",),
            hard_estimate_ceiling_tokens=None,
            evidence_digest=_digest({"graphiti": "unbounded"}),
            qualified=True,
        )
    )
    observer = GraphitiModelUsageObserver(
        service=service,
        envelope=envelope,
        clock=lambda: T0 + timedelta(seconds=10),
    )
    token = observer.before_cli_invocation(
        provider="cursor-agent-cli",
        model=CURSOR_AGENT_MODEL_ID,
        prompt="chat prompt",
        schema=None,
    )
    observer.after_cli_invocation(
        token,
        outcome="TRANSPORT_LOST",
        usage={"usage_basis": "UNAVAILABLE"},
    )

    leaf = service.query(start=T0, end=T0 + timedelta(minutes=1))["leaves"][0]
    assert leaf["usage_status"] == "UNREPORTED"
    assert leaf["total_tokens"] is None
    assert service.route_state(GRAPHITI_CHAT_PRIMARY_ROUTE)["state"] == "OPEN"


def service_row_count(path: Path, table: str) -> int:
    connection = sqlite3.connect(path)
    try:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        connection.close()


def test_hermes_usage_command_exports_shared_receipts_as_json_and_csv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import hermes_control_plane as hermes

    path = tmp_path / "unpublished.sqlite3"
    service = ModelUsageService(str(path))
    _envelope_value, _policy_value, allocation = _open_and_allocate(service)
    service.complete(_reported(allocation))
    monkeypatch.setattr(hermes, "ensure_control_plane_state_root", lambda: None)
    common = [
        "usage",
        "--unpublished",
        str(path),
        "--usage-start",
        "2026-08-24T10:00:00Z",
        "--usage-end",
        "2026-08-24T10:01:00Z",
    ]

    assert hermes.main(common) == 0
    json_report = json.loads(capsys.readouterr().out)
    assert json_report["leaf_dispatch_count"] == 1
    assert json_report["observed_total_tokens"] == 125

    assert hermes.main([*common, "--usage-format", "leaf-csv"]) == 0
    rows = list(csv.DictReader(io.StringIO(capsys.readouterr().out)))
    assert [row["invocation_id"] for row in rows] == [allocation.invocation_id]


def test_hermes_usage_command_exports_allocation_free_envelope_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import hermes_control_plane as hermes

    path = tmp_path / "unpublished.sqlite3"
    service = ModelUsageService(str(path))
    envelope = _envelope()
    service.open_envelope(envelope)
    service.record_work_outcome(
        envelope_id=envelope.envelope_id,
        outcome="HOLD",
        outcome_record_id="owner-stop-outcome",
        payload_digest=None,
        terminal_at=T0 + timedelta(seconds=1),
        stable_reason_codes=("OWNER_EMERGENCY_STOP",),
    )
    monkeypatch.setattr(hermes, "ensure_control_plane_state_root", lambda: None)
    common = [
        "usage",
        "--unpublished",
        str(path),
        "--usage-start",
        "2026-08-24T10:00:00Z",
        "--usage-end",
        "2026-08-24T10:01:00Z",
    ]

    assert hermes.main(common) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["leaf_dispatch_count"] == 0
    assert report["envelope_outcome_counts"] == {"HOLD": 1}
    assert report["envelopes"][0]["outcome"] == "HOLD"
    assert report["envelopes"][0]["stable_reason_codes"] == [
        "OWNER_EMERGENCY_STOP"
    ]

    assert hermes.main([*common, "--usage-format", "envelope-csv"]) == 0
    rows = list(csv.DictReader(io.StringIO(capsys.readouterr().out)))
    assert len(rows) == 1
    assert rows[0]["envelope_id"] == envelope.envelope_id
    assert rows[0]["outcome"] == "HOLD"
    assert rows[0]["work_outcome_terminal_at"] == "2026-08-24T10:00:01.000000Z"
    assert rows[0]["stable_reason_codes"] == '["OWNER_EMERGENCY_STOP"]'
