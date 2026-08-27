from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path

import pytest

from newsroom.authority.canonical import digest_canonical
from newsroom.control_plane.graphiti_admission import graphiti_admission_telemetry
from newsroom.control_plane.graphiti_requests import (
    GraphitiCallShapePolicy,
    GraphitiInternalRequestIdentity,
    GraphitiLeafClass,
    load_checked_graphiti_call_shape_policy,
)
from newsroom.control_plane.model_usage import (
    InvocationAllocation,
    InvocationEfficiencyPolicy,
    InvocationTerminal,
    ModelUsageAdmissionError,
    ModelUsageService,
    UsageComponents,
    UsageStatus,
    WorkEnvelope,
    WorkloadClass,
)
from newsroom.control_plane.store import connect

from newsroom.tests.test_model_usage_receipts import (
    T0,
    _allocation,
    _digest,
    _envelope,
    _open_and_allocate,
    _policy,
    _reported,
    _service,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
CLOSEOUT_JSON = (
    _REPO_ROOT
    / "docs/research/2026-08-25-graphiti-internal-call-efficiency-closeout.json"
)
GRAPHITI_TELEMETRY_KEYS = (
    "completed_ingests_with_proposals",
    "completed_ingests_zero_proposals",
    "completed_useful_ingest_count",
    "distinct_internal_requests",
    "distinct_internal_requests_per_completed_ingest",
    "call_shape_max_distinct_internal_requests",
    "call_shape_headroom",
    "duplicate_request_refusals",
    "call_shape_drift_refusals",
    "primary_leaf_count",
    "fallback_leaf_count",
    "embedding_leaf_count",
    "fallback_recovery_count",
    "reported_tokens",
    "estimated_tokens",
    "unresolved_invocation_count",
    "failed_or_rolled_back_attempt_tokens",
    "tokens_per_proposal",
    "context_overhead_per_internal_request",
    "route_circuit_states",
    "embedding_tokens",
    "embedding_od_011_references",
    "cli_chat_cash_debited",
    "normal_daily_hard_cut",
    "missing_usage_is_zero",
)
QUALIFIED_ROUTES = (
    {
        "leaf_class": "PRIMARY",
        "provider": "cursor-agent-cli",
        "route": "GRAPHITI_CHAT_PRIMARY",
        "model": "composer-2.5",
        "reasoning": "provider-default",
        "config_identity": "graphiti-cli-command-v1",
        "command_semantic_version": "newsroom.graphiti-provider-dispatch.v1",
        "command_flags": ["fixture-command"],
        "disabled_capabilities": ["skills", "tools", "mcp"],
        "implementation_revision": "newsroom-graphiti-adapter-issue-769-v1",
        "max_prompt_bytes": 4_096,
        "max_context_tokens": 4_096,
        "max_output_tokens": 1_024,
        "max_total_tokens": 8_192,
    },
    {
        "leaf_class": "FALLBACK",
        "provider": "grok-build-cli",
        "route": "GRAPHITI_CHAT_FALLBACK",
        "model": "grok-4.6",
        "reasoning": "medium",
        "config_identity": "graphiti-cli-command-v1",
        "command_semantic_version": "newsroom.graphiti-provider-dispatch.v1",
        "command_flags": ["fixture-command"],
        "disabled_capabilities": ["skills", "tools", "mcp"],
        "implementation_revision": "newsroom-graphiti-adapter-issue-769-v1",
        "max_prompt_bytes": 4_096,
        "max_context_tokens": 4_096,
        "max_output_tokens": 1_024,
        "max_total_tokens": 8_192,
    },
    {
        "leaf_class": "EMBEDDING",
        "provider": "openrouter",
        "route": "GRAPHITI_EMBEDDING",
        "model": "openai/text-embedding-3-large",
        "reasoning": "none",
        "config_identity": "graphiti-embedding-command-v1",
        "command_semantic_version": "newsroom.graphiti-provider-dispatch.v1",
        "command_flags": ["fixture-command"],
        "disabled_capabilities": ["skills", "tools", "mcp"],
        "implementation_revision": "newsroom-graphiti-adapter-issue-769-v1",
        "max_prompt_bytes": 4_096,
        "max_context_tokens": 4_096,
        "max_output_tokens": 1,
        "max_total_tokens": 4_096,
    },
)
QUALIFIED_REQUEST_SHAPES = (
    {
        "leaf_class": "PRIMARY",
        "semantic_request_class": "ExtractedEntities",
        "response_schema_identity": "ExtractedEntities",
        "response_schema_digest": digest_canonical({"schema": "entity"}),
    },
    {
        "leaf_class": "FALLBACK",
        "semantic_request_class": "ExtractedEntities",
        "response_schema_identity": "ExtractedEntities",
        "response_schema_digest": digest_canonical({"schema": "entity"}),
    },
    {
        "leaf_class": "EMBEDDING",
        "semantic_request_class": "EMBEDDING_VECTOR",
        "response_schema_identity": "embedding-vector",
        "response_schema_digest": digest_canonical(
            {
                "schema": "embedding-vector",
                "model": "openai/text-embedding-3-large",
            }
        ),
    },
)


def _graphiti_telemetry(service: ModelUsageService) -> dict[str, object]:
    report = service.report(start=T0, end=T0 + timedelta(minutes=1))
    telemetry = report["graphiti_result_telemetry"]
    assert isinstance(telemetry, dict)
    return telemetry


def _graphiti_envelope(
    *,
    ingest_id: str = "ingest-731",
    cycle_id: str = "cycle-731",
) -> WorkEnvelope:
    return _envelope(
        cycle_id=cycle_id,
        workload=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        candidate_id=None,
        ingest_id=ingest_id,
    )


def _graphiti_policy(
    *,
    workload: WorkloadClass = WorkloadClass.GRAPHITI_CHAT_PRIMARY,
    provider: str = "cursor-agent-cli",
    route: str = "GRAPHITI_CHAT_PRIMARY",
    model: str = "composer-2.5",
) -> InvocationEfficiencyPolicy:
    return _policy(
        workload=workload,
        provider=provider,
        route=route,
        model=model,
    )


def _complete_graphiti_ingest(
    service: ModelUsageService,
    *,
    outcome: str,
    retained_proposal_count: int,
    total: int = 125,
) -> None:
    envelope = _graphiti_envelope()
    policy = _graphiti_policy()
    service.register_policy(policy)
    service.open_envelope(envelope)
    allocation = _allocation(envelope, policy)
    service.allocate(allocation, owner_emergency_stop=False)
    service.complete(_reported(allocation, total=total, outcome="COMPLETE"))
    service.record_work_outcome(
        envelope_id=envelope.envelope_id,
        outcome=outcome,
        outcome_record_id="graphiti-attempt-731",
        payload_digest=None,
        terminal_at=T0 + timedelta(seconds=4),
        retained_proposal_count=retained_proposal_count,
    )


def _request_service(
    tmp_path: Path,
) -> tuple[
    ModelUsageService,
    WorkEnvelope,
    InvocationEfficiencyPolicy,
    GraphitiCallShapePolicy,
]:
    service = _service(tmp_path)
    envelope = WorkEnvelope.create(
        cycle_id="cycle-731-request",
        workload_class=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        admitted_at=T0,
        admission_decision_id=None,
        candidate_id=None,
        hypothesis_digest=None,
        evidence_package_digest=None,
        ingest_id="ingest-731",
        graphiti_attempt_id="ingest-731:1",
    )
    policy = InvocationEfficiencyPolicy.create(
        policy_id="graphiti-primary-731",
        version="v1",
        workload_class=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        provider="cursor-agent-cli",
        route="GRAPHITI_CHAT_PRIMARY",
        model="composer-2.5",
        reasoning="provider-default",
        one_turn=True,
        exact_input=True,
        skills_enabled=False,
        tools_enabled=False,
        mcp_enabled=False,
        prior_message_count=0,
        command_semantic_version="newsroom.graphiti-provider-dispatch.v1",
        command_flags=("fixture-command",),
        context_manifest_schema_version=(
            "newsroom.graphiti-hermetic-context-manifest.v1"
        ),
        disabled_capabilities=("skills", "tools", "mcp"),
        implementation_revision="fixture-implementation-v1",
        max_prompt_bytes=4_096,
        max_context_tokens=4_096,
        max_output_tokens=1_024,
        max_total_tokens=8_192,
        prompt_contract_version="prompt-v1",
        output_schema_digest=digest_canonical({"schema": "entity"}),
        allowed_context_identities=("graphiti-context-v1",),
        allowed_config_identities=("graphiti-cli-command-v1",),
        hard_estimate_ceiling_tokens=None,
        evidence_digest=digest_canonical({"qualified": "fixture"}),
        qualified=True,
    )
    shape = GraphitiCallShapePolicy.create(
        policy_id="shape-731",
        version="v1",
        graphiti_core_release="graphiti-core-0.29.3",
        framework_identity="graphiti-core-0.29.3",
        prompt_identity="prompt-v1",
        ontology_identity="ontology-v1",
        temporal_identity="temporal-v1",
        generation_policy_identity="generation-v1",
        qualified_routes=QUALIFIED_ROUTES,
        qualified_request_shapes=QUALIFIED_REQUEST_SHAPES,
        fixtures=(
            {
                "fixture_id": "single",
                "fixture_class": "ZERO_PROPOSAL",
                "distinct_internal_request_count": 1,
            },
        ),
    )
    service.register_policy(policy)
    service.open_envelope(envelope)
    return service, envelope, policy, shape


def _bound_request(
    *,
    service: ModelUsageService,
    envelope: WorkEnvelope,
    policy: InvocationEfficiencyPolicy,
    shape: GraphitiCallShapePolicy,
    ordinal: int,
    semantic: str,
) -> tuple[InvocationAllocation, GraphitiInternalRequestIdentity]:
    prompt_digest = digest_canonical({"prompt": semantic})
    schema_digest = policy.output_schema_digest
    retry_state_digest = digest_canonical({"state": semantic})
    semantic_state_digest = digest_canonical(
        {
            "semantic_request_class": "ExtractedEntities",
            "prompt_digest": prompt_digest,
            "response_schema_digest": schema_digest,
            "requested_max_tokens": 512,
            "leaf_class": "PRIMARY",
            "retry_state_digest": retry_state_digest,
        }
    )
    effective_revision_digest = digest_canonical({"revision": "r1"})
    system_digest = digest_canonical({"system": "fixture"})
    request_digest = digest_canonical(
        {
            "provider": policy.provider,
            "route": policy.route,
            "model": policy.model,
            "reasoning": policy.reasoning,
            "command_semantic_version": policy.command_semantic_version,
            "command_flags": list(policy.command_flags),
            "implementation_revision": policy.implementation_revision,
            "system_digest": system_digest,
            "prompt_digest": prompt_digest,
            "output_schema_digest": schema_digest,
        }
    )
    provider_attempt_id = f"ingest-731:1:provider-attempt:1:leaf:{ordinal}"
    manifest = {
        "schema_version": policy.context_manifest_schema_version,
        "provider": policy.provider,
        "route": policy.route,
        "model": policy.model,
        "reasoning": policy.reasoning,
        "command_semantic_version": policy.command_semantic_version,
        "command_flags": list(policy.command_flags),
        "implementation_revision": policy.implementation_revision,
        "implementation_worktree_clean": True,
        "disabled_capabilities": list(policy.disabled_capabilities),
        "working_directory_inventory": [],
        "working_directory_inventory_digest": digest_canonical([]),
        "environment_keys": [
            "HOME",
            "LANG",
            "LC_ALL",
            "PATH",
            "TMPDIR",
            "XDG_CACHE_HOME",
            "XDG_CONFIG_HOME",
            "XDG_DATA_HOME",
            "XDG_STATE_HOME",
        ],
        "config_identity": "graphiti-cli-command-v1",
        "context_identity": "graphiti-context-v1",
        "system_digest": system_digest,
        "prompt_contract_version": policy.prompt_contract_version,
        "prompt_bytes": 128,
        "prompt_digest": prompt_digest,
        "schema_digest": schema_digest,
        "output_schema_digest": schema_digest,
        "evidence_package_digest": effective_revision_digest,
        "evidence_package_bytes": 128,
        "effective_revision_digest": effective_revision_digest,
        "ingest_obligation_id": "ingest-731",
        "graphiti_attempt_id": "ingest-731:1",
        "provider_attempt_id": provider_attempt_id,
        "semantic_state_digest": semantic_state_digest,
        "request_digest": request_digest,
        "one_turn": True,
        "exact_input": True,
        "skills_enabled": False,
        "tools_enabled": False,
        "mcp_enabled": False,
        "prior_message_count": 0,
        "skill_count": 0,
        "tool_count": 0,
        "mcp_server_count": 0,
        "mcp_tool_count": 0,
    }
    context_manifest_digest = digest_canonical(manifest)
    service.retain_context_manifest(
        {"context_manifest_digest": context_manifest_digest, **manifest}
    )
    allocation = InvocationAllocation.create(
        envelope_id=envelope.envelope_id,
        cycle_id=envelope.cycle_id,
        leaf_ordinal=ordinal,
        workload_class=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        invocation_policy_digest=policy.canonical_digest,
        provider=policy.provider,
        route=policy.route,
        model=policy.model,
        reasoning=policy.reasoning,
        prompt_contract_version=policy.prompt_contract_version,
        prompt_bytes=128,
        prompt_digest=prompt_digest,
        request_digest=request_digest,
        output_schema_digest=schema_digest,
        max_output_tokens=512,
        context_manifest_digest=context_manifest_digest,
        context_identity="graphiti-context-v1",
        config_identity="graphiti-cli-command-v1",
        one_turn=True,
        exact_input=True,
        skills_enabled=False,
        tools_enabled=False,
        mcp_enabled=False,
        prior_message_count=0,
        allocated_at=T0 + timedelta(seconds=ordinal),
        recovery_deadline_at=T0 + timedelta(minutes=20, seconds=ordinal),
        parent_invocation_id=None,
    )
    identity = GraphitiInternalRequestIdentity.create(
        effective_revision_digest=effective_revision_digest,
        ingest_obligation_id="ingest-731",
        graphiti_attempt_id="ingest-731:1",
        provider_attempt_id=provider_attempt_id,
        internal_ordinal=ordinal,
        semantic_request_class="ExtractedEntities",
        provider=policy.provider,
        model=policy.model,
        reasoning=policy.reasoning,
        prompt_bytes=128,
        prompt_digest=prompt_digest,
        response_schema_identity="ExtractedEntities",
        response_schema_digest=schema_digest,
        requested_max_tokens=512,
        framework_identity=shape.framework_identity,
        prompt_identity=shape.prompt_identity,
        ontology_identity=shape.ontology_identity,
        temporal_identity=shape.temporal_identity,
        generation_policy_identity=shape.generation_policy_identity,
        context_manifest_digest=allocation.context_manifest_digest,
        leaf_class=GraphitiLeafClass.PRIMARY,
        retry_state_digest=retry_state_digest,
        parent_invocation_id=None,
        envelope_id=envelope.envelope_id,
        invocation_id=allocation.invocation_id,
        invocation_policy_digest=policy.canonical_digest,
        call_shape_policy_digest=shape.canonical_digest,
        dispatch_authority_digest=digest_canonical({"rights": "current"}),
        dispatch_deadline_at="2026-08-24T10:03:00+00:00",
        owner_stop_clear=True,
        route_circuit_state="CLOSED",
    )
    return allocation, identity


def test_graphiti_success_increments_completed_ingests_with_proposals(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    _complete_graphiti_ingest(
        service,
        outcome="GRAPHITI_SUCCESS",
        retained_proposal_count=2,
    )

    report = service.report(start=T0, end=T0 + timedelta(minutes=1))
    telemetry = report["graphiti_result_telemetry"]

    assert report["graphiti_valid_ingest_count"] == 1
    assert telemetry["completed_ingests_with_proposals"] == 1
    assert telemetry["completed_ingests_zero_proposals"] == 0
    assert telemetry["completed_useful_ingest_count"] == 1
    assert telemetry["tokens_per_proposal"] == {"numerator": 125, "denominator": 2}


def test_zero_proposal_success_is_completed_useful_ingest(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _complete_graphiti_ingest(
        service,
        outcome="GRAPHITI_SUCCESS_ZERO_PROPOSALS",
        retained_proposal_count=0,
    )

    report = service.report(start=T0, end=T0 + timedelta(minutes=1))
    telemetry = report["graphiti_result_telemetry"]

    assert report["graphiti_valid_ingest_count"] == 1
    assert telemetry["completed_ingests_zero_proposals"] == 1
    assert telemetry["completed_ingests_with_proposals"] == 0
    assert telemetry["completed_useful_ingest_count"] == 1
    assert telemetry["tokens_per_proposal"] is None


def test_graphiti_partial_is_failed_attempt_not_completed_ingest(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    _complete_graphiti_ingest(
        service,
        outcome="GRAPHITI_PARTIAL",
        retained_proposal_count=3,
        total=90,
    )

    report = service.report(start=T0, end=T0 + timedelta(minutes=1))
    telemetry = report["graphiti_result_telemetry"]

    assert report["graphiti_valid_ingest_count"] == 0
    assert telemetry["completed_useful_ingest_count"] == 0
    assert telemetry["completed_ingests_with_proposals"] == 0
    assert telemetry["completed_ingests_zero_proposals"] == 0
    assert telemetry["failed_or_rolled_back_attempt_tokens"] == 90
    assert telemetry["tokens_per_proposal"] is None


def test_duplicate_internal_request_refusal_is_not_a_dispatched_leaf(
    tmp_path: Path,
) -> None:
    service, envelope, policy, shape = _request_service(tmp_path)
    first, first_identity = _bound_request(
        service=service,
        envelope=envelope,
        policy=policy,
        shape=shape,
        ordinal=1,
        semantic="entities",
    )
    service.allocate_graphiti_request(
        first,
        identity=first_identity,
        max_distinct_internal_requests=shape.max_distinct_internal_requests,
    )
    duplicate, duplicate_identity = _bound_request(
        service=service,
        envelope=envelope,
        policy=policy,
        shape=shape,
        ordinal=2,
        semantic="entities",
    )
    with pytest.raises(ModelUsageAdmissionError) as error:
        service.allocate_graphiti_request(
            duplicate,
            identity=duplicate_identity,
            max_distinct_internal_requests=shape.max_distinct_internal_requests,
        )
    assert error.value.reason_code == "DUPLICATE_INTERNAL_REQUEST"

    telemetry = _graphiti_telemetry(service)

    assert telemetry["duplicate_request_refusals"] == 1
    assert telemetry["distinct_internal_requests"] == 1
    assert telemetry["primary_leaf_count"] == 1
    assert telemetry["call_shape_drift_refusals"] == 0
    assert telemetry["context_overhead_per_internal_request"] is None
    assert telemetry["failed_or_rolled_back_attempt_tokens"] == 0


def test_call_shape_drift_refusal_opens_graphiti_route_circuit(
    tmp_path: Path,
) -> None:
    service, envelope, policy, shape = _request_service(tmp_path)
    first, first_identity = _bound_request(
        service=service,
        envelope=envelope,
        policy=policy,
        shape=shape,
        ordinal=1,
        semantic="first",
    )
    service.allocate_graphiti_request(
        first,
        identity=first_identity,
        max_distinct_internal_requests=1,
    )
    drift, drift_identity = _bound_request(
        service=service,
        envelope=envelope,
        policy=policy,
        shape=shape,
        ordinal=2,
        semantic="one-beyond-policy",
    )
    with pytest.raises(ModelUsageAdmissionError) as error:
        service.allocate_graphiti_request(
            drift,
            identity=drift_identity,
            max_distinct_internal_requests=1,
        )
    assert error.value.reason_code == "CALL_SHAPE_DRIFT"

    telemetry = _graphiti_telemetry(service)

    assert telemetry["call_shape_drift_refusals"] == 1
    assert telemetry["duplicate_request_refusals"] == 0
    assert telemetry["route_circuit_states"]["GRAPHITI_CHAT_PRIMARY"] == "OPEN"
    assert telemetry["primary_leaf_count"] == 1


def test_primary_and_typed_fallback_count_recovery_on_success(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    envelope = _graphiti_envelope()
    primary_policy = _graphiti_policy()
    fallback_policy = _graphiti_policy(
        workload=WorkloadClass.GRAPHITI_CHAT_FALLBACK,
        provider="grok-build-cli",
        route="GRAPHITI_CHAT_FALLBACK",
        model="grok-4.6",
    )
    service.register_policy(primary_policy)
    service.register_policy(fallback_policy)
    service.open_envelope(envelope)
    primary = _allocation(envelope, primary_policy)
    fallback = _allocation(
        envelope,
        fallback_policy,
        leaf_ordinal=2,
        request="fallback",
        workload=WorkloadClass.GRAPHITI_CHAT_FALLBACK,
        parent_invocation_id=primary.invocation_id,
    )
    service.allocate(primary, owner_emergency_stop=False)
    service.allocate(fallback, owner_emergency_stop=False)
    service.complete(_reported(primary, total=80, outcome="COMPLETE"))
    service.complete(_reported(fallback, total=70, outcome="COMPLETE"))
    service.record_work_outcome(
        envelope_id=envelope.envelope_id,
        outcome="GRAPHITI_SUCCESS",
        outcome_record_id="graphiti-attempt-fallback",
        payload_digest=None,
        terminal_at=T0 + timedelta(seconds=5),
        retained_proposal_count=1,
    )

    telemetry = _graphiti_telemetry(service)

    assert telemetry["primary_leaf_count"] == 1
    assert telemetry["fallback_leaf_count"] == 1
    assert telemetry["fallback_recovery_count"] == 1
    assert telemetry["completed_ingests_with_proposals"] == 1


def test_in_flight_graphiti_tokens_are_not_failed_attempt_tokens(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    envelope = _graphiti_envelope()
    policy = _graphiti_policy()
    service.register_policy(policy)
    service.open_envelope(envelope)
    allocation = _allocation(envelope, policy)
    service.allocate(allocation, owner_emergency_stop=False)
    service.complete(_reported(allocation, total=125, outcome="COMPLETE"))

    telemetry = _graphiti_telemetry(service)

    assert telemetry["completed_useful_ingest_count"] == 0
    assert telemetry["reported_tokens"] == 125
    assert telemetry["failed_or_rolled_back_attempt_tokens"] == 0


def test_unreported_graphiti_leaf_is_unresolved_not_zero_tokens(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    envelope = _graphiti_envelope()
    policy = _graphiti_policy()
    service.register_policy(policy)
    service.open_envelope(envelope)
    allocation = _allocation(envelope, policy)
    service.allocate(allocation, owner_emergency_stop=False)
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

    report = service.report(start=T0, end=T0 + timedelta(minutes=1))
    telemetry = report["graphiti_result_telemetry"]

    assert telemetry["unresolved_invocation_count"] == 1
    assert telemetry["reported_tokens"] == 0
    assert telemetry["estimated_tokens"] == 0
    assert telemetry["failed_or_rolled_back_attempt_tokens"] == 0
    assert report["observed_total_tokens"] == 0


def test_embedding_leaf_retains_od_011_without_cli_chat_cash(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    envelope = _graphiti_envelope()
    chat_policy = _graphiti_policy()
    embedding_policy = _graphiti_policy(
        workload=WorkloadClass.GRAPHITI_EMBEDDING,
        provider="openrouter",
        route="GRAPHITI_EMBEDDING",
        model="openai/text-embedding-3-small",
    )
    service.register_policy(chat_policy)
    service.register_policy(embedding_policy)
    service.open_envelope(envelope)
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
        outcome="GRAPHITI_SUCCESS",
        outcome_record_id="graphiti-attempt-embedding",
        payload_digest=None,
        terminal_at=T0 + timedelta(seconds=4),
        retained_proposal_count=1,
    )

    report = service.report(start=T0, end=T0 + timedelta(minutes=1))
    telemetry = report["graphiti_result_telemetry"]

    embedding_row = next(
        row
        for row in service.query(start=T0, end=T0 + timedelta(minutes=1))["leaves"]
        if row["workload_class"] == "GRAPHITI_EMBEDDING"
    )
    assert embedding_row["od_011_reference"] == "OD-011:EVALUATION"
    assert telemetry["embedding_leaf_count"] == 1
    assert telemetry["embedding_tokens"] == 40
    assert telemetry["embedding_od_011_references"] == ["OD-011:EVALUATION"]
    assert telemetry["cli_chat_cash_debited"] is False


def test_checked_call_shape_policy_headroom_appears_on_report(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    policy = load_checked_graphiti_call_shape_policy()
    telemetry = _graphiti_telemetry(service)

    assert telemetry["call_shape_max_distinct_internal_requests"] == 6
    assert telemetry["call_shape_headroom"] == 2
    assert telemetry["call_shape_max_distinct_internal_requests"] == (
        policy.max_distinct_internal_requests
    )
    assert telemetry["call_shape_headroom"] == policy.headroom
    assert policy.policy_id == "graphiti-core-0.29.3-newsroom-adapter-v1"
    assert policy.version == "issue-790-v10"


def test_graphiti_object_repeats_no_daily_hard_cut(tmp_path: Path) -> None:
    service = _service(tmp_path)
    telemetry = _graphiti_telemetry(service)

    assert telemetry["normal_daily_hard_cut"] is None
    assert telemetry["missing_usage_is_zero"] is False
    assert telemetry["cli_chat_cash_debited"] is False


def test_cont_only_window_does_not_invent_graphiti_completed_ingests(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    _envelope_value, _policy_value, allocation = _open_and_allocate(service)
    service.complete(_reported(allocation))

    report = service.report(start=T0, end=T0 + timedelta(minutes=1))
    telemetry = report["graphiti_result_telemetry"]

    assert set(telemetry) == set(GRAPHITI_TELEMETRY_KEYS)
    assert telemetry["completed_ingests_with_proposals"] == 0
    assert telemetry["completed_ingests_zero_proposals"] == 0
    assert telemetry["completed_useful_ingest_count"] == 0
    assert telemetry["distinct_internal_requests"] == 0
    assert telemetry["distinct_internal_requests_per_completed_ingest"] is None
    assert telemetry["primary_leaf_count"] == 0
    assert telemetry["fallback_leaf_count"] == 0
    assert telemetry["embedding_leaf_count"] == 0
    assert "oldest_lag_seconds" not in telemetry
    assert report["graphiti_valid_ingest_count"] == 0


def test_graphiti_admission_lag_is_independent_of_cont_usage_report(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    _envelope_value, _policy_value, allocation = _open_and_allocate(service)
    service.complete(_reported(allocation))
    report = service.report(start=T0, end=T0 + timedelta(minutes=1))
    telemetry = report["graphiti_result_telemetry"]

    admission = connect(str(tmp_path / "unpublished-admission.sqlite3"))
    try:
        admission.execute(
            """
            INSERT INTO unpublished_graphiti_admission_queue(
                proposal_key, ingest_id, source_revision_id, source_receipt_digest,
                proposal_digest, proposal_kind, request_json, request_digest,
                state, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "proposal-lag-731",
                "ingest-lag-731",
                "00000000-0000-4000-8000-000000000731",
                digest_canonical({"receipt": "lag"}),
                digest_canonical({"proposal": "lag"}),
                "ENTITY_MENTION",
                "{}",
                digest_canonical({"request": "lag"}),
                "READY",
                T0.isoformat(),
                T0.isoformat(),
            ),
        )
        admission.commit()
        admission_telemetry = graphiti_admission_telemetry(
            admission,
            now=T0 + timedelta(hours=1),
        )
    finally:
        admission.close()

    assert telemetry["completed_useful_ingest_count"] == 0
    assert report["accepted_payload_count"] == 0
    assert "oldest_lag_seconds" not in telemetry
    assert admission_telemetry.oldest_lag_seconds == 3600


def test_issue_731_behaviour_mapping_names_exist() -> None:
    mapping = json.loads(CLOSEOUT_JSON.read_text(encoding="utf-8"))
    defined: set[str] = set()
    for path in (_REPO_ROOT / "newsroom/tests").rglob("test_*.py"):
        defined.update(
            re.findall(r"^def (test_[A-Za-z0-9_]+)\(", path.read_text(), re.M)
        )
    missing = [
        name
        for item in mapping["behaviour_tests"]
        for name in item.get("tests", [])
        if name not in defined
    ]
    assert mapping["issue"] == 731
    assert len(mapping["behaviour_tests"]) == 15
    assert missing == []
    assert mapping["behaviour_tests"][13]["suites"] == [
        "newsroom/tests/test_graphiti_adapter_real_executor.py",
        "newsroom/tests/test_graphiti_corpus_ingest.py",
    ]
