from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from graphiti_core.prompts.extract_edges import ExtractedEdges
from graphiti_core.prompts.extract_nodes import ExtractedEntities

from newsroom.authority.canonical import digest_canonical
from newsroom.control_plane.graphiti import GraphitiModelUsageObserver
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
    ModelUsageIntegrityError,
    ModelUsageService,
    UsageComponents,
    UsageStatus,
    WorkEnvelope,
    WorkloadClass,
)
from newsroom.graphiti_adapter.cli_client import (
    CliExecution,
    CliPredispatchRefusal,
    CliResponseError,
    run_cli_chain,
)
from newsroom.graphiti_adapter.embedding_meter import MeteredOpenAIEmbedder
from newsroom.graphiti_adapter.usage_meter import cursor_cli_usage

T0 = datetime(2026, 8, 24, 20, 0, tzinfo=UTC)
EXTRACTED_ENTITIES_SCHEMA = json.dumps(ExtractedEntities.model_json_schema())
EXTRACTED_EDGES_SCHEMA = json.dumps(ExtractedEdges.model_json_schema())
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


def test_checked_call_shape_policy_derives_headroom_from_qualified_fixtures() -> None:
    policy = load_checked_graphiti_call_shape_policy()

    assert policy.graphiti_core_release == "graphiti-core-0.29.3"
    assert policy.maximum_qualified_fixture_count == max(
        fixture.distinct_internal_request_count for fixture in policy.fixtures
    )
    assert policy.headroom == max(
        2, (policy.maximum_qualified_fixture_count + 3) // 4
    )
    assert policy.max_distinct_internal_requests == (
        policy.maximum_qualified_fixture_count + policy.headroom
    )
    assert {
        "ZERO_PROPOSAL",
        "RELATIONS",
        "TEMPORAL_CURRENT",
        "CONTRADICTION_INVALIDATION",
        "EXISTING_ENTITY_RESOLUTION",
        "LONG_MULTI_CHUNK",
        "MALFORMED_FALLBACK",
        "TIMEOUT_CANCELLATION",
        "RESTART_PRE_DISPATCH",
        "RESTART_POSSIBLE_IO",
        "EMBEDDING",
    } <= {fixture.fixture_class for fixture in policy.fixtures}
    assert all(
        route.command_semantic_version != "UNSPECIFIED"
        and route.command_flags
        and route.disabled_capabilities
        for route in policy.qualified_routes
    )
    assert {
        "ExtractedEntities",
        "NodeResolutions",
        "ExtractedEdges",
        "EdgeTimestamps",
        "EdgeDuplicate",
        "SummarizedEntities",
        "CombinedExtraction",
        "BatchEdgeTimestamps",
        "EMBEDDING_VECTOR",
        "UNSTRUCTURED",
    } == {
        shape.semantic_request_class for shape in policy.qualified_request_shapes
    }


def test_checked_call_shape_refuses_an_arbitrary_runtime_schema(
    tmp_path: Path,
) -> None:
    service = ModelUsageService(str(tmp_path / "unpublished.sqlite3"))
    envelope = WorkEnvelope.create(
        cycle_id="cycle-schema-drift",
        workload_class=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        admitted_at=T0,
        admission_decision_id=None,
        candidate_id=None,
        hypothesis_digest=None,
        evidence_package_digest=None,
        ingest_id="ingest-schema-drift",
        graphiti_attempt_id="ingest-schema-drift:1",
    )
    service.open_envelope(envelope)
    observer = GraphitiModelUsageObserver(
        service=service,
        envelope=envelope,
        clock=lambda: T0 + timedelta(seconds=1),
        owner_stop_check=lambda: None,
    )

    with pytest.raises(
        ValueError, match="semantic class/schema is outside the checked call shape"
    ):
        observer.before_cli_invocation(
            provider="cursor-agent-cli",
            model="composer-2.5",
            prompt="schema drift",
            schema='{"totally":"unqualified"}',
            semantic_request_class="ExtractedEntities",
            max_tokens=100,
        )

    assert service.graphiti_request_records(envelope_id=envelope.envelope_id)[
        "requests"
    ] == []


def test_internal_request_identity_binds_semantics_without_source_expression() -> None:
    policy = GraphitiCallShapePolicy.create(
        policy_id="fixture-policy",
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
                "fixture_id": "zero",
                "fixture_class": "ZERO_PROPOSAL",
                "distinct_internal_request_count": 1,
            },
        ),
    )
    identity = GraphitiInternalRequestIdentity.create(
        effective_revision_digest=digest_canonical({"revision": "r1"}),
        ingest_obligation_id="ingest-1",
        graphiti_attempt_id="ingest-1:1",
        provider_attempt_id="ingest-1:1:provider-attempt:1:leaf:1",
        internal_ordinal=1,
        semantic_request_class="ExtractedEntities",
        provider="cursor-agent-cli",
        model="composer-2.5",
        reasoning="provider-default",
        prompt_bytes=17,
        prompt_digest=digest_canonical({"prompt": "redacted"}),
        response_schema_identity="ExtractedEntities",
        response_schema_digest=digest_canonical({"schema": "entity"}),
        requested_max_tokens=512,
        framework_identity=policy.framework_identity,
        prompt_identity=policy.prompt_identity,
        ontology_identity=policy.ontology_identity,
        temporal_identity=policy.temporal_identity,
        generation_policy_identity=policy.generation_policy_identity,
        context_manifest_digest=digest_canonical({"context": "manifest"}),
        leaf_class=GraphitiLeafClass.PRIMARY,
        retry_state_digest=digest_canonical({"retry": "initial"}),
        parent_invocation_id=None,
        envelope_id=digest_canonical({"envelope": 1}),
        invocation_id=digest_canonical({"invocation": 1}),
        invocation_policy_digest=digest_canonical({"invocation-policy": 1}),
        call_shape_policy_digest=policy.canonical_digest,
        dispatch_authority_digest=digest_canonical({"rights": "current"}),
        dispatch_deadline_at="2026-08-24T20:03:00+00:00",
        owner_stop_clear=True,
        route_circuit_state="CLOSED",
    )

    record = identity.as_record()
    assert record["canonical_digest"] == identity.canonical_digest
    assert record["semantic_state_digest"] == digest_canonical(
        {
            "semantic_request_class": "ExtractedEntities",
            "prompt_digest": identity.prompt_digest,
            "response_schema_digest": identity.response_schema_digest,
            "requested_max_tokens": 512,
            "leaf_class": "PRIMARY",
            "retry_state_digest": identity.retry_state_digest,
        }
    )
    assert "source_expression" not in record
    assert "prompt" not in record


def _service_fixture(
    tmp_path: Path,
) -> tuple[
    ModelUsageService,
    WorkEnvelope,
    InvocationEfficiencyPolicy,
    GraphitiCallShapePolicy,
]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    service = ModelUsageService(str(tmp_path / "unpublished.sqlite3"))
    envelope = WorkEnvelope.create(
        cycle_id="cycle-769",
        workload_class=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        admitted_at=T0,
        admission_decision_id=None,
        candidate_id=None,
        hypothesis_digest=None,
        evidence_package_digest=None,
        ingest_id="ingest-769",
        graphiti_attempt_id="ingest-769:1",
    )
    policy = InvocationEfficiencyPolicy.create(
        policy_id="graphiti-primary-fixture",
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
        policy_id="shape-fixture",
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
    provider_attempt_id = f"ingest-769:1:provider-attempt:1:leaf:{ordinal}"
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
        "ingest_obligation_id": "ingest-769",
        "graphiti_attempt_id": "ingest-769:1",
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
        ingest_obligation_id="ingest-769",
        graphiti_attempt_id="ingest-769:1",
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
        dispatch_deadline_at="2026-08-24T20:03:00+00:00",
        owner_stop_clear=True,
        route_circuit_state="CLOSED",
    )
    return allocation, identity


def test_atomic_graphiti_allocation_refuses_duplicate_and_call_shape_drift(
    tmp_path: Path,
) -> None:
    service, envelope, policy, shape = _service_fixture(tmp_path)
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
        max_distinct_internal_requests=shape.max_distinct_internal_requests,
    )

    duplicate, duplicate_identity = _bound_request(
        service=service,
        envelope=envelope,
        policy=policy,
        shape=shape,
        ordinal=2,
        semantic="first",
    )
    with pytest.raises(ModelUsageAdmissionError) as duplicate_error:
        service.allocate_graphiti_request(
            duplicate,
            identity=duplicate_identity,
            max_distinct_internal_requests=shape.max_distinct_internal_requests,
        )
    assert duplicate_error.value.reason_code == "DUPLICATE_INTERNAL_REQUEST"

    restarted_envelope = WorkEnvelope.create(
        cycle_id="cycle-769-restarted",
        workload_class=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        admitted_at=T0 + timedelta(seconds=3),
        admission_decision_id=None,
        candidate_id=None,
        hypothesis_digest=None,
        evidence_package_digest=None,
        ingest_id=envelope.ingest_id,
        graphiti_attempt_id=envelope.graphiti_attempt_id,
    )
    service.open_envelope(restarted_envelope)
    restarted, restarted_identity = _bound_request(
        service=service,
        envelope=restarted_envelope,
        policy=policy,
        shape=shape,
        ordinal=1,
        semantic="first",
    )
    with pytest.raises(ModelUsageAdmissionError) as restart_duplicate:
        service.allocate_graphiti_request(
            restarted,
            identity=restarted_identity,
            max_distinct_internal_requests=shape.max_distinct_internal_requests,
        )
    assert restart_duplicate.value.reason_code == "DUPLICATE_INTERNAL_REQUEST"
    restarted_distinct, restarted_distinct_identity = _bound_request(
        service=service,
        envelope=restarted_envelope,
        policy=policy,
        shape=shape,
        ordinal=1,
        semantic="different-after-restart",
    )
    with pytest.raises(ModelUsageAdmissionError) as restart_identity_reuse:
        service.allocate_graphiti_request(
            restarted_distinct,
            identity=restarted_distinct_identity,
            max_distinct_internal_requests=shape.max_distinct_internal_requests,
        )
    assert (
        restart_identity_reuse.value.reason_code
        == "GRAPHITI_ATTEMPT_IDENTITY_REUSE"
    )
    assert (
        service.next_graphiti_internal_ordinal(
            graphiti_attempt_id=str(envelope.graphiti_attempt_id)
        )
        == 2
    )

    for ordinal in (2, 3):
        allocation, identity = _bound_request(
            service=service,
            envelope=envelope,
            policy=policy,
            shape=shape,
            ordinal=ordinal,
            semantic=f"distinct-{ordinal}",
        )
        service.allocate_graphiti_request(
            allocation,
            identity=identity,
            max_distinct_internal_requests=shape.max_distinct_internal_requests,
        )

    drift, drift_identity = _bound_request(
        service=service,
        envelope=envelope,
        policy=policy,
        shape=shape,
        ordinal=4,
        semantic="one-too-many",
    )
    with pytest.raises(ModelUsageAdmissionError) as drift_error:
        service.allocate_graphiti_request(
            drift,
            identity=drift_identity,
            max_distinct_internal_requests=shape.max_distinct_internal_requests,
        )
    assert drift_error.value.reason_code == "CALL_SHAPE_DRIFT"

    retained = service.graphiti_request_records(envelope_id=envelope.envelope_id)
    assert len(retained["requests"]) == 3
    assert [item["reason_code"] for item in retained["refusals"]] == [
        "DUPLICATE_INTERNAL_REQUEST",
        "CALL_SHAPE_DRIFT",
    ]
    assert service.route_state(policy.route)["state"] == "OPEN"


def test_operational_restart_reuses_the_retained_graphiti_envelope(
    tmp_path: Path,
) -> None:
    service = ModelUsageService(str(tmp_path / "unpublished.sqlite3"))
    first = WorkEnvelope.create(
        cycle_id="event-769",
        workload_class=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        admitted_at=T0,
        admission_decision_id=None,
        candidate_id=None,
        hypothesis_digest=None,
        evidence_package_digest=None,
        ingest_id="ingest-restart-envelope",
        graphiti_attempt_id="ingest-restart-envelope:1",
    )
    assert service.resume_or_open_graphiti_envelope(first) == first

    recreated = WorkEnvelope.create(
        cycle_id=first.cycle_id,
        workload_class=first.workload_class,
        admitted_at=T0 + timedelta(minutes=5),
        admission_decision_id=None,
        candidate_id=None,
        hypothesis_digest=None,
        evidence_package_digest=None,
        ingest_id=first.ingest_id,
        graphiti_attempt_id=first.graphiti_attempt_id,
    )
    resumed = ModelUsageService(service.path).resume_or_open_graphiti_envelope(
        recreated
    )

    assert resumed.envelope_id == first.envelope_id
    assert resumed.canonical_digest == first.canonical_digest
    assert resumed.admitted_at == first.admitted_at


def test_attempt_cannot_complete_while_an_earlier_envelope_leaf_is_unresolved(
    tmp_path: Path,
) -> None:
    service, first, policy, shape = _service_fixture(tmp_path)
    allocation, identity = _bound_request(
        service=service,
        envelope=first,
        policy=policy,
        shape=shape,
        ordinal=1,
        semantic="unresolved-prior-envelope",
    )
    service.allocate_graphiti_request(
        allocation,
        identity=identity,
        max_distinct_internal_requests=shape.max_distinct_internal_requests,
    )
    later = WorkEnvelope.create(
        cycle_id="cycle-769-later-envelope",
        workload_class=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        admitted_at=T0 + timedelta(minutes=1),
        admission_decision_id=None,
        candidate_id=None,
        hypothesis_digest=None,
        evidence_package_digest=None,
        ingest_id=first.ingest_id,
        graphiti_attempt_id=first.graphiti_attempt_id,
    )
    service.open_envelope(later)

    with pytest.raises(ModelUsageIntegrityError, match="terminal receipt"):
        service.record_work_outcome(
            envelope_id=later.envelope_id,
            outcome="ZERO_PROPOSAL",
            outcome_record_id="attempt-outcome",
            payload_digest=None,
            terminal_at=T0 + timedelta(minutes=2),
            retained_proposal_count=0,
        )


def test_chat_transport_observes_committed_identity_and_receipts_requested_max_tokens(
    tmp_path: Path,
) -> None:
    service = ModelUsageService(str(tmp_path / "unpublished.sqlite3"))
    envelope = WorkEnvelope.create(
        cycle_id="cycle-wrapper",
        workload_class=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        admitted_at=T0,
        admission_decision_id=None,
        candidate_id=None,
        hypothesis_digest=None,
        evidence_package_digest=None,
        ingest_id="ingest-wrapper",
        graphiti_attempt_id="ingest-wrapper:1",
    )
    service.open_envelope(envelope)
    observer = GraphitiModelUsageObserver(
        service=service,
        envelope=envelope,
        clock=lambda: T0 + timedelta(seconds=10),
        owner_stop_check=lambda: None,
        effective_revision_digest=digest_canonical({"effective_revision": "r1"}),
        ingest_obligation_id="ingest-wrapper",
        provider_attempt_number=1,
        deadline=T0 + timedelta(minutes=3),
        dispatch_authority_digest=digest_canonical({"rights": "current"}),
    )
    invocations: list[dict[str, object]] = []
    provider_calls = 0

    async def cursor_runner(prompt: str, *, max_tokens: int) -> CliExecution:
        nonlocal provider_calls
        assert max_tokens == 77
        provider_calls += 1
        retained = service.graphiti_request_records(envelope_id=envelope.envelope_id)
        assert len(retained["requests"]) == 1
        identity = retained["requests"][0]
        assert identity["requested_max_tokens"] == 77
        assert identity["semantic_request_class"] == "ExtractedEntities"
        leaf = service.query(start=T0, end=T0 + timedelta(minutes=1))["leaves"][0]
        assert leaf["provider_attempt_id"] == identity["provider_attempt_id"]
        assert leaf["transport_dispatch_observed"] is True
        assert leaf["context_manifest"]["schema_version"] == (
            "newsroom.graphiti-hermetic-context-manifest.v1"
        )
        assert leaf["context_manifest"]["effective_revision_digest"] == identity[
            "effective_revision_digest"
        ]
        assert leaf["context_manifest"]["prior_message_count"] == 0
        assert leaf["context_manifest"]["skill_count"] == 0
        assert leaf["context_manifest"]["tool_count"] == 0
        assert leaf["context_manifest"]["mcp_server_count"] == 0
        return CliExecution(
            text='{"extracted_entities":[]}',
            usage=cursor_cli_usage(
                {
                    "inputTokens": 10,
                    "outputTokens": 2,
                    "cacheReadTokens": 0,
                    "cacheWriteTokens": 0,
                }
            ),
        )

    async def grok_runner(_prompt: str, _schema: str | None, *, max_tokens: int) -> CliExecution:
        raise AssertionError("fallback should not run")

    result = asyncio.run(
        run_cli_chain(
            prompt="source-safe prompt",
            schema=EXTRACTED_ENTITIES_SCHEMA,
            semantic_request_class="ExtractedEntities",
            max_tokens=77,
            cursor_runner=cursor_runner,
            grok_runner=grok_runner,
            invocations=invocations,
            invocation_observer=observer,
        )
    )

    assert result == {"extracted_entities": []}
    assert provider_calls == 1
    assert invocations[0]["requested_max_tokens"] == 77
    assert invocations[0]["model_invocation_id"]
    assert invocations[0]["model_invocation_terminal_digest"]

    with pytest.raises(ModelUsageAdmissionError) as duplicate_error:
        asyncio.run(
            run_cli_chain(
                prompt="source-safe prompt",
                schema=EXTRACTED_ENTITIES_SCHEMA,
                semantic_request_class="ExtractedEntities",
                max_tokens=77,
                cursor_runner=cursor_runner,
                grok_runner=grok_runner,
                invocations=[],
                invocation_observer=observer,
            )
        )
    assert duplicate_error.value.reason_code == "DUPLICATE_INTERNAL_REQUEST"
    assert provider_calls == 1


def test_embedding_transport_observes_separate_preallocated_leaf_and_od011_receipt(
    tmp_path: Path,
) -> None:
    service = ModelUsageService(str(tmp_path / "unpublished.sqlite3"))
    envelope = WorkEnvelope.create(
        cycle_id="cycle-embedding",
        workload_class=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        admitted_at=T0,
        admission_decision_id=None,
        candidate_id=None,
        hypothesis_digest=None,
        evidence_package_digest=None,
        ingest_id="ingest-embedding",
        graphiti_attempt_id="ingest-embedding:1",
    )
    service.open_envelope(envelope)
    observer = GraphitiModelUsageObserver(
        service=service,
        envelope=envelope,
        clock=lambda: T0 + timedelta(seconds=20),
        owner_stop_check=lambda: None,
        effective_revision_digest=digest_canonical({"effective_revision": "r2"}),
        ingest_obligation_id="ingest-embedding",
        provider_attempt_number=1,
        deadline=T0 + timedelta(minutes=3),
        dispatch_authority_digest=digest_canonical({"rights": "current"}),
    )

    class Embeddings:
        async def create(self, **_values: object) -> object:
            retained = service.graphiti_request_records(
                envelope_id=envelope.envelope_id
            )
            assert retained["requests"][0]["leaf_class"] == "EMBEDDING"
            assert service.query(start=T0, end=T0 + timedelta(minutes=1))["leaves"]
            return SimpleNamespace(
                id="embedding-request-1",
                data=[SimpleNamespace(embedding=[1.0, 2.0])],
                usage={"prompt_tokens": 4, "total_tokens": 4, "cost": "0.000001"},
            )

    delegate = SimpleNamespace(
        client=SimpleNamespace(embeddings=Embeddings()),
        config=SimpleNamespace(
            embedding_model="openai/text-embedding-3-large",
            embedding_dim=2,
        ),
    )
    embedder = MeteredOpenAIEmbedder(delegate, invocation_observer=observer)

    assert asyncio.run(embedder.create("embedding input")) == [1.0, 2.0]
    request = embedder.receipt()["requests"][0]
    assert request["model_invocation_id"]
    assert request["model_invocation_terminal_digest"]
    leaf = service.query(start=T0, end=T0 + timedelta(minutes=1))["leaves"][0]
    assert leaf["workload_class"] == "GRAPHITI_EMBEDDING"
    assert leaf["od_011_reference"] == "OD-011:EVALUATION_GRAPHITI_EMBEDDING"


def test_embedding_dispatch_fence_refusal_terminalises_exact_zero(
    tmp_path: Path,
) -> None:
    service = ModelUsageService(str(tmp_path / "unpublished.sqlite3"))
    envelope = WorkEnvelope.create(
        cycle_id="cycle-embedding-fence",
        workload_class=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        admitted_at=T0,
        admission_decision_id=None,
        candidate_id=None,
        hypothesis_digest=None,
        evidence_package_digest=None,
        ingest_id="ingest-embedding-fence",
        graphiti_attempt_id="ingest-embedding-fence:1",
    )
    service.open_envelope(envelope)
    clock_calls = 0

    def clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        return (
            T0 + timedelta(seconds=1)
            if clock_calls == 1
            else T0 + timedelta(minutes=2)
        )

    observer = GraphitiModelUsageObserver(
        service=service,
        envelope=envelope,
        clock=clock,
        owner_stop_check=lambda: None,
        deadline=T0 + timedelta(minutes=1),
    )
    provider_calls = 0

    class Embeddings:
        async def create(self, **_values: object) -> object:
            nonlocal provider_calls
            provider_calls += 1
            raise AssertionError("embedding provider must remain fenced")

    delegate = SimpleNamespace(
        client=SimpleNamespace(embeddings=Embeddings()),
        config=SimpleNamespace(
            embedding_model="openai/text-embedding-3-large",
            embedding_dim=2,
        ),
    )
    embedder = MeteredOpenAIEmbedder(delegate, invocation_observer=observer)

    with pytest.raises(ModelUsageAdmissionError, match="expired during local preflight"):
        asyncio.run(embedder.create("embedding input"))

    assert provider_calls == 0
    receipt = embedder.receipt()
    request = receipt["requests"][0]
    assert request["outcome"] == "FAILED"
    assert request["usage_basis"] == "NO_PROVIDER_CALL"
    assert request["model_invocation_terminal_digest"]
    assert receipt["usage_basis"] == "NO_PROVIDER_CALL"
    assert receipt["request_count"] == 1
    assert receipt["embedding_tokens"] == 0
    assert receipt["cost_usd_microunits"] == 0
    from newsroom.graphiti_adapter.usage_meter import summarise_graphiti_usage

    assert summarise_graphiti_usage(
        chat_invocations=(), embedding_usage=receipt
    )["usage_basis"] == "NO_PROVIDER_CALL"
    leaf = service.query(start=T0, end=T0 + timedelta(minutes=3))["leaves"][0]
    assert leaf["invocation_outcome"] == "FAILED"
    assert leaf["transport_dispatch_observed"] is False
    assert leaf["pre_dispatch_zero_proved"] is True
    assert leaf["total_tokens"] == 0

    from newsroom.control_plane.store import (
        connect,
        reconcile_graphiti_spend,
        reserve_graphiti_spend,
    )

    spend_connection = connect(str(tmp_path / "unpublished-spend.sqlite3"))
    assert reserve_graphiti_spend(
        spend_connection,
        spend_id="ingest-embedding-fence:1",
        ingest_id="ingest-embedding-fence",
        attempt_number=1,
        proving_run_id="proving-run-1",
        generation_id="generation-1",
        reserved_gbp_microunits=100,
        ceiling_gbp_microunits=1_000,
    )
    accounting = reconcile_graphiti_spend(
        spend_connection,
        spend_id="ingest-embedding-fence:1",
        embedding_usage=receipt,
    )
    assert accounting["status"] == "RECONCILED"
    assert accounting["actual_usd_microunits"] == 0
    assert accounting["actual_gbp_microunits"] == 0
    assert accounting["unused_reservation_released"] is True


@pytest.mark.parametrize("refusal", ["expired_deadline", "owner_stop"])
def test_embedding_refusal_before_allocation_retains_no_phantom_request(
    tmp_path: Path, refusal: str
) -> None:
    service = ModelUsageService(str(tmp_path / "unpublished.sqlite3"))
    envelope = WorkEnvelope.create(
        cycle_id=f"cycle-embedding-{refusal}",
        workload_class=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        admitted_at=T0,
        admission_decision_id=None,
        candidate_id=None,
        hypothesis_digest=None,
        evidence_package_digest=None,
        ingest_id=f"ingest-embedding-{refusal}",
        graphiti_attempt_id=f"ingest-embedding-{refusal}:1",
    )
    service.open_envelope(envelope)

    def owner_stop_check() -> None:
        if refusal == "owner_stop":
            raise RuntimeError("owner stop asserted")

    observer = GraphitiModelUsageObserver(
        service=service,
        envelope=envelope,
        clock=lambda: T0 + timedelta(seconds=1),
        owner_stop_check=owner_stop_check,
        deadline=T0 if refusal == "expired_deadline" else None,
    )
    provider_calls = 0

    class Embeddings:
        async def create(self, **_values: object) -> object:
            nonlocal provider_calls
            provider_calls += 1
            raise AssertionError("embedding provider must remain fenced")

    delegate = SimpleNamespace(
        client=SimpleNamespace(embeddings=Embeddings()),
        config=SimpleNamespace(
            embedding_model="openai/text-embedding-3-large",
            embedding_dim=2,
        ),
    )
    embedder = MeteredOpenAIEmbedder(delegate, invocation_observer=observer)

    expected_error = ValueError if refusal == "expired_deadline" else RuntimeError
    with pytest.raises(expected_error):
        asyncio.run(embedder.create("embedding input"))

    assert provider_calls == 0
    assert embedder.receipt() == {
        "requests": [],
        "request_count": 0,
        "embedding_tokens": 0,
        "cost_usd_microunits": 0,
        "usage_basis": "NO_EMBEDDING_CALL",
    }
    assert service.query(start=T0, end=T0 + timedelta(minutes=1))["leaves"] == []


def test_requested_max_tokens_is_forwarded_and_enforced_on_reported_usage(
    tmp_path: Path,
) -> None:
    service = ModelUsageService(str(tmp_path / "unpublished.sqlite3"))
    envelope = WorkEnvelope.create(
        cycle_id="cycle-max-output",
        workload_class=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        admitted_at=T0,
        admission_decision_id=None,
        candidate_id=None,
        hypothesis_digest=None,
        evidence_package_digest=None,
        ingest_id="ingest-max-output",
        graphiti_attempt_id="ingest-max-output:1",
    )
    service.open_envelope(envelope)
    observer = GraphitiModelUsageObserver(
        service=service,
        envelope=envelope,
        clock=lambda: T0 + timedelta(seconds=10),
        owner_stop_check=lambda: None,
        deadline=T0 + timedelta(minutes=3),
    )
    captured_prompt = ""

    async def cursor_runner(prompt: str, *, max_tokens: int) -> CliExecution:
        nonlocal captured_prompt
        assert max_tokens == 3
        captured_prompt = prompt
        return CliExecution(
            text='{"extracted_entities":[]}',
            usage=cursor_cli_usage(
                {
                    "inputTokens": 10,
                    "outputTokens": 4,
                    "cacheReadTokens": 0,
                    "cacheWriteTokens": 0,
                }
            ),
        )

    with pytest.raises(CliResponseError, match="exceeded requested max_tokens"):
        asyncio.run(
            run_cli_chain(
                prompt="bounded prompt",
                schema=EXTRACTED_ENTITIES_SCHEMA,
                semantic_request_class="ExtractedEntities",
                max_tokens=3,
                cursor_runner=cursor_runner,
                grok_runner=lambda _prompt, _schema, *, max_tokens: "not called",
                invocations=[],
                invocation_observer=observer,
            )
        )

    assert "maximum_output_tokens=3" in captured_prompt
    leaf = service.query(start=T0, end=T0 + timedelta(minutes=1))["leaves"][0]
    assert leaf["policy_breach"] == "REQUESTED_MAX_OUTPUT_TOKENS_EXCEEDED"
    assert service.route_state("GRAPHITI_CHAT_PRIMARY")["state"] == "OPEN"


def test_requested_max_tokens_rejects_unreported_output_at_transport_boundary() -> None:
    invocations: list[dict[str, object]] = []

    with pytest.raises(CliResponseError, match="exceeded requested max_tokens"):
        asyncio.run(
            run_cli_chain(
                prompt="bounded prompt",
                schema=None,
                max_tokens=1,
                cursor_runner=lambda _prompt, *, max_tokens: CliExecution(
                    text='{"value":"' + ("x" * 10_000) + '"}',
                    usage={"usage_basis": "UNREPORTED"},
                ),
                grok_runner=lambda _prompt, _schema, *, max_tokens: "not called",
                invocations=invocations,
            )
        )

    assert invocations[0]["outcome"] == "OUTPUT_LIMIT_EXCEEDED"
    assert invocations[0]["requested_max_tokens"] == 1


def test_reported_output_uses_exact_provider_tokens_not_byte_ceiling() -> None:
    invocations: list[dict[str, object]] = []
    result = asyncio.run(
        run_cli_chain(
            prompt="bounded prompt",
            schema=None,
            max_tokens=10,
            cursor_runner=lambda _prompt, *, max_tokens: CliExecution(
                text='{"value":"ok"}',
                usage={
                    "usage_basis": "PROVIDER_REPORTED",
                    "input_tokens": 3,
                    "output_tokens": 4,
                    "cached_read_tokens": 0,
                    "cached_write_tokens": 0,
                    "reasoning_tokens": 0,
                    "total_tokens": 7,
                },
            ),
            grok_runner=lambda _prompt, _schema, *, max_tokens: "not called",
            invocations=invocations,
        )
    )

    assert result == {"value": "ok"}
    assert invocations[0]["outcome"] == "COMPLETE"


def test_missing_reported_output_tokens_uses_conservative_byte_ceiling() -> None:
    invocations: list[dict[str, object]] = []

    with pytest.raises(CliResponseError, match="exceeded requested max_tokens"):
        asyncio.run(
            run_cli_chain(
                prompt="bounded prompt",
                schema=None,
                max_tokens=1,
                cursor_runner=lambda _prompt, *, max_tokens: CliExecution(
                    text='{"value":"' + ("x" * 10_000) + '"}',
                    usage={
                        "usage_basis": "PROVIDER_REPORTED",
                        "input_tokens": 3,
                        "output_tokens": None,
                        "cached_read_tokens": None,
                        "cached_write_tokens": None,
                        "reasoning_tokens": None,
                        "total_tokens": None,
                    },
                ),
                grok_runner=lambda _prompt, _schema, *, max_tokens: "not called",
                invocations=invocations,
            )
        )

    assert invocations[0]["outcome"] == "OUTPUT_LIMIT_EXCEEDED"


def test_negative_reported_output_tokens_uses_conservative_byte_ceiling() -> None:
    invocations: list[dict[str, object]] = []

    with pytest.raises(CliResponseError, match="exceeded requested max_tokens"):
        asyncio.run(
            run_cli_chain(
                prompt="bounded prompt",
                schema=None,
                max_tokens=1,
                cursor_runner=lambda _prompt, *, max_tokens: CliExecution(
                    text='{"value":"' + ("x" * 10_000) + '"}',
                    usage={
                        "usage_basis": "PROVIDER_REPORTED",
                        "input_tokens": 3,
                        "output_tokens": -1,
                        "cached_read_tokens": 0,
                        "cached_write_tokens": 0,
                        "reasoning_tokens": 0,
                        "total_tokens": 2,
                    },
                ),
                grok_runner=lambda _prompt, _schema, *, max_tokens: "not called",
                invocations=invocations,
            )
        )

    assert invocations[0]["outcome"] == "OUTPUT_LIMIT_EXCEEDED"


def test_post_marker_executable_loss_is_usage_uncertain(
    tmp_path: Path,
) -> None:
    service = ModelUsageService(str(tmp_path / "unpublished.sqlite3"))
    envelope = WorkEnvelope.create(
        cycle_id="cycle-post-marker-executable-loss",
        workload_class=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        admitted_at=T0,
        admission_decision_id=None,
        candidate_id=None,
        hypothesis_digest=None,
        evidence_package_digest=None,
        ingest_id="ingest-post-marker-executable-loss",
        graphiti_attempt_id="ingest-post-marker-executable-loss:1",
    )
    service.open_envelope(envelope)
    observer = GraphitiModelUsageObserver(
        service=service,
        envelope=envelope,
        clock=lambda: T0 + timedelta(seconds=10),
        owner_stop_check=lambda: None,
    )
    invocations: list[dict[str, object]] = []

    def missing_after_marker(
        _prompt: str,
        *,
        max_tokens: int,
        dispatch_started: object,
    ) -> CliExecution:
        del max_tokens
        assert callable(dispatch_started)
        dispatch_started()
        raise FileNotFoundError("fixture executable disappeared")

    result = asyncio.run(
        run_cli_chain(
            prompt="source-safe prompt",
            schema=EXTRACTED_ENTITIES_SCHEMA,
            semantic_request_class="ExtractedEntities",
            max_tokens=100,
            cursor_runner=missing_after_marker,
            grok_runner=lambda _prompt, _schema, *, max_tokens: CliExecution(
                text='{"extracted_entities":[]}',
                usage=cursor_cli_usage(
                    {
                        "inputTokens": 2,
                        "outputTokens": 2,
                        "cacheReadTokens": 0,
                        "cacheWriteTokens": 0,
                    }
                ),
            ),
            invocations=invocations,
            invocation_observer=observer,
        )
    )

    assert result == {"extracted_entities": []}
    assert invocations[0]["usage"]["usage_basis"] == "UNREPORTED"
    primary = next(
        leaf
        for leaf in service.query(start=T0, end=T0 + timedelta(minutes=1))["leaves"]
        if leaf["workload_class"] == "GRAPHITI_CHAT_PRIMARY"
    )
    assert primary["transport_dispatch_observed"] is True
    assert primary["pre_dispatch_zero_proved"] is False
    assert primary["dispatch_at"] is not None


@pytest.mark.parametrize(
    ("failure", "expected_outcome"),
    [
        (
            CliPredispatchRefusal("unsupported max token control"),
            "PREDISPATCH_REFUSED",
        ),
        (OSError("hermetic workspace unavailable"), "FAILED"),
    ],
)
def test_cli_setup_failure_remains_proved_pre_dispatch_zero(
    tmp_path: Path, failure: Exception, expected_outcome: str
) -> None:
    service = ModelUsageService(str(tmp_path / "unpublished.sqlite3"))
    envelope = WorkEnvelope.create(
        cycle_id="cycle-preflight-refusal",
        workload_class=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        admitted_at=T0,
        admission_decision_id=None,
        candidate_id=None,
        hypothesis_digest=None,
        evidence_package_digest=None,
        ingest_id="ingest-preflight-refusal",
        graphiti_attempt_id="ingest-preflight-refusal:1",
    )
    service.open_envelope(envelope)
    observer = GraphitiModelUsageObserver(
        service=service,
        envelope=envelope,
        clock=lambda: T0 + timedelta(seconds=10),
        owner_stop_check=lambda: None,
    )

    def refused_cursor(
        _prompt: str,
        *,
        max_tokens: int,
        dispatch_started: object = None,
    ) -> CliExecution:
        del max_tokens, dispatch_started
        raise failure

    result = asyncio.run(
        run_cli_chain(
            prompt="source-safe prompt",
            schema=EXTRACTED_ENTITIES_SCHEMA,
            semantic_request_class="ExtractedEntities",
            max_tokens=100,
            cursor_runner=refused_cursor,
            grok_runner=lambda _prompt, _schema, *, max_tokens: CliExecution(
                text='{"extracted_entities":[]}',
                usage=cursor_cli_usage(
                    {
                        "inputTokens": 2,
                        "outputTokens": 2,
                        "cacheReadTokens": 0,
                        "cacheWriteTokens": 0,
                    }
                ),
            ),
            invocations=[],
            invocation_observer=observer,
        )
    )

    assert result == {"extracted_entities": []}
    leaves = service.query(start=T0, end=T0 + timedelta(minutes=1))["leaves"]
    primary = next(
        leaf
        for leaf in leaves
        if leaf["workload_class"] == "GRAPHITI_CHAT_PRIMARY"
    )
    assert primary["invocation_outcome"] == expected_outcome
    assert primary["transport_dispatch_observed"] is False
    assert primary["pre_dispatch_zero_proved"] is True
    assert primary["total_tokens"] == 0


def test_async_cli_capability_preflight_kills_child_on_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from newsroom.graphiti_adapter import cli_client

    started = asyncio.Event()
    killed = False
    waited = False

    class Process:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            started.set()
            await asyncio.Future()
            raise AssertionError("cancelled preflight resumed")

        def kill(self) -> None:
            nonlocal killed
            killed = True

        async def wait(self) -> None:
            nonlocal waited
            waited = True

    async def create_process(*_command: str, **_values: object) -> Process:
        return Process()

    monkeypatch.setattr(
        cli_client.asyncio, "create_subprocess_exec", create_process
    )
    workspace = cli_client._hermetic_cli_workspace(
        str(tmp_path), binary="/bin/fixture-cli"
    )

    async def cancel_preflight() -> None:
        task = asyncio.create_task(
            cli_client._prove_cli_controls_async(
                binary="/bin/fixture-cli",
                required_controls=("--max-output-tokens",),
                workspace=workspace,
            )
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_preflight())
    assert killed is True
    assert waited is True


def test_dispatch_fence_rechecks_deadline_after_local_preflight(
    tmp_path: Path,
) -> None:
    service = ModelUsageService(str(tmp_path / "unpublished.sqlite3"))
    envelope = WorkEnvelope.create(
        cycle_id="cycle-preflight-deadline",
        workload_class=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        admitted_at=T0,
        admission_decision_id=None,
        candidate_id=None,
        hypothesis_digest=None,
        evidence_package_digest=None,
        ingest_id="ingest-preflight-deadline",
        graphiti_attempt_id="ingest-preflight-deadline:1",
    )
    service.open_envelope(envelope)
    now = T0 + timedelta(seconds=1)
    owner_stop_checks = 0

    def owner_stop_check() -> None:
        nonlocal owner_stop_checks
        owner_stop_checks += 1

    observer = GraphitiModelUsageObserver(
        service=service,
        envelope=envelope,
        clock=lambda: now,
        owner_stop_check=owner_stop_check,
        deadline=T0 + timedelta(minutes=1),
    )
    provider_calls = 0

    def cursor_runner(
        _prompt: str,
        *,
        max_tokens: int,
        dispatch_started: object,
    ) -> CliExecution:
        nonlocal now, provider_calls
        del max_tokens
        now = T0 + timedelta(minutes=2)
        assert callable(dispatch_started)
        dispatch_started()
        provider_calls += 1
        return CliExecution(text="{}", usage={"usage_basis": "UNREPORTED"})

    with pytest.raises(ModelUsageAdmissionError, match="expired during local preflight"):
        asyncio.run(
            run_cli_chain(
                prompt="source-safe prompt",
                schema=EXTRACTED_ENTITIES_SCHEMA,
                semantic_request_class="ExtractedEntities",
                max_tokens=100,
                cursor_runner=cursor_runner,
                grok_runner=lambda _prompt, _schema, *, max_tokens: "not called",
                invocations=[],
                invocation_observer=observer,
            )
        )

    assert provider_calls == 0
    assert owner_stop_checks == 1
    leaf = service.query(start=T0, end=T0 + timedelta(minutes=3))["leaves"][0]
    assert leaf["invocation_outcome"] == "DISPATCH_FENCE_REFUSED"
    assert leaf["transport_dispatch_observed"] is False
    assert leaf["pre_dispatch_zero_proved"] is True


def test_cancellation_before_dispatch_marker_has_matching_zero_receipts(
    tmp_path: Path,
) -> None:
    service = ModelUsageService(str(tmp_path / "unpublished.sqlite3"))
    envelope = WorkEnvelope.create(
        cycle_id="cycle-cancel-preflight",
        workload_class=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        admitted_at=T0,
        admission_decision_id=None,
        candidate_id=None,
        hypothesis_digest=None,
        evidence_package_digest=None,
        ingest_id="ingest-cancel-preflight",
        graphiti_attempt_id="ingest-cancel-preflight:1",
    )
    service.open_envelope(envelope)
    observer = GraphitiModelUsageObserver(
        service=service,
        envelope=envelope,
        clock=lambda: T0 + timedelta(seconds=10),
        owner_stop_check=lambda: None,
    )
    invocations: list[dict[str, object]] = []

    async def cancel_before_marker() -> None:
        started = asyncio.Event()

        async def cursor_runner(
            _prompt: str,
            *,
            max_tokens: int,
            dispatch_started: object,
        ) -> CliExecution:
            del max_tokens, dispatch_started
            started.set()
            await asyncio.Future()
            raise AssertionError("cancelled preflight resumed")

        task = asyncio.create_task(
            run_cli_chain(
                prompt="source-safe prompt",
                schema=EXTRACTED_ENTITIES_SCHEMA,
                semantic_request_class="ExtractedEntities",
                max_tokens=100,
                cursor_runner=cursor_runner,
                grok_runner=lambda _prompt, _schema, *, max_tokens: "not called",
                invocations=invocations,
                invocation_observer=observer,
            )
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_before_marker())
    leaf = service.query(start=T0, end=T0 + timedelta(minutes=1))["leaves"][0]
    assert leaf["invocation_outcome"] == "CANCELLED"
    assert leaf["transport_dispatch_observed"] is False
    assert leaf["pre_dispatch_zero_proved"] is True
    assert invocations[0]["usage"]["usage_basis"] == "NO_PROVIDER_CALL"


def test_cancellation_retains_uncertain_leaf_before_control_returns(
    tmp_path: Path,
) -> None:
    service = ModelUsageService(str(tmp_path / "unpublished.sqlite3"))
    envelope = WorkEnvelope.create(
        cycle_id="cycle-cancel",
        workload_class=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        admitted_at=T0,
        admission_decision_id=None,
        candidate_id=None,
        hypothesis_digest=None,
        evidence_package_digest=None,
        ingest_id="ingest-cancel",
        graphiti_attempt_id="ingest-cancel:1",
    )
    service.open_envelope(envelope)
    observer = GraphitiModelUsageObserver(
        service=service,
        envelope=envelope,
        clock=lambda: T0 + timedelta(seconds=10),
        owner_stop_check=lambda: None,
        deadline=T0 + timedelta(minutes=3),
    )
    invocations: list[dict[str, object]] = []

    async def cancel_during_transport() -> None:
        started = asyncio.Event()

        async def cursor_runner(_prompt: str, *, max_tokens: int) -> CliExecution:
            started.set()
            await asyncio.sleep(60)
            raise AssertionError("cancelled transport resumed")

        task = asyncio.create_task(
            run_cli_chain(
                prompt="cancel prompt",
                schema=EXTRACTED_ENTITIES_SCHEMA,
                semantic_request_class="ExtractedEntities",
                max_tokens=100,
                cursor_runner=cursor_runner,
                grok_runner=lambda _prompt, _schema, *, max_tokens: "not called",
                invocations=invocations,
                invocation_observer=observer,
            )
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_during_transport())

    leaf = service.query(start=T0, end=T0 + timedelta(minutes=1))["leaves"][0]
    assert leaf["invocation_outcome"] == "CANCELLED"
    assert leaf["usage_status"] == "UNREPORTED"
    assert leaf["total_tokens"] is None
    assert invocations[0]["model_invocation_terminal_digest"] == leaf[
        "terminal_digest"
    ]


def test_typed_fallback_has_a_distinct_identity_and_exact_parent(
    tmp_path: Path,
) -> None:
    service = ModelUsageService(str(tmp_path / "unpublished.sqlite3"))
    envelope = WorkEnvelope.create(
        cycle_id="cycle-fallback",
        workload_class=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        admitted_at=T0,
        admission_decision_id=None,
        candidate_id=None,
        hypothesis_digest=None,
        evidence_package_digest=None,
        ingest_id="ingest-fallback",
        graphiti_attempt_id="ingest-fallback:1",
    )
    service.open_envelope(envelope)
    observer = GraphitiModelUsageObserver(
        service=service,
        envelope=envelope,
        clock=lambda: T0 + timedelta(seconds=30),
        owner_stop_check=lambda: None,
    )
    invocations: list[dict[str, object]] = []

    result = asyncio.run(
        run_cli_chain(
            prompt="fallback prompt",
            schema=EXTRACTED_EDGES_SCHEMA,
            semantic_request_class="ExtractedEdges",
            max_tokens=512,
            cursor_runner=lambda _prompt, *, max_tokens: CliExecution(
                text="malformed",
                usage={"usage_basis": "UNAVAILABLE"},
            ),
            grok_runner=lambda _prompt, _schema, *, max_tokens: CliExecution(
                text='{"edges":[]}',
                usage={
                    "usage_basis": "PROVIDER_REPORTED",
                    "input_tokens": 10,
                    "output_tokens": 2,
                    "cached_read_tokens": 0,
                    "cached_write_tokens": 0,
                    "reasoning_tokens": 0,
                    "total_tokens": 12,
                },
            ),
            invocations=invocations,
            invocation_observer=observer,
        )
    )

    assert result == {"edges": []}
    requests = service.graphiti_request_records(envelope_id=envelope.envelope_id)[
        "requests"
    ]
    assert [item["leaf_class"] for item in requests] == ["PRIMARY", "FALLBACK"]
    assert requests[1]["parent_invocation_id"] == requests[0]["invocation_id"]
    assert requests[1]["semantic_state_digest"] != requests[0][
        "semantic_state_digest"
    ]


def test_deadline_owner_stop_and_max_tokens_refuse_before_transport(
    tmp_path: Path,
) -> None:
    service = ModelUsageService(str(tmp_path / "unpublished.sqlite3"))
    envelope = WorkEnvelope.create(
        cycle_id="cycle-authority",
        workload_class=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
        admitted_at=T0,
        admission_decision_id=None,
        candidate_id=None,
        hypothesis_digest=None,
        evidence_package_digest=None,
        ingest_id="ingest-authority",
        graphiti_attempt_id="ingest-authority:1",
    )
    service.open_envelope(envelope)

    expired = GraphitiModelUsageObserver(
        service=service,
        envelope=envelope,
        clock=lambda: T0 + timedelta(minutes=4),
        owner_stop_check=lambda: None,
        deadline=T0 + timedelta(minutes=3),
    )
    with pytest.raises(ValueError, match="deadline has expired"):
        expired.before_cli_invocation(
            provider="cursor-agent-cli",
            model="composer-2.5",
            prompt="expired",
            schema=EXTRACTED_ENTITIES_SCHEMA,
            semantic_request_class="ExtractedEntities",
            max_tokens=100,
        )

    owner_stop_checks = 0

    def prove_owner_stop() -> None:
        nonlocal owner_stop_checks
        owner_stop_checks += 1
        raise ModelUsageAdmissionError("owner emergency stop is active")

    stopped = GraphitiModelUsageObserver(
        service=service,
        envelope=envelope,
        clock=lambda: T0 + timedelta(seconds=1),
        deadline=T0 + timedelta(minutes=3),
        owner_stop_check=prove_owner_stop,
    )
    with pytest.raises(ModelUsageAdmissionError, match="emergency stop"):
        stopped.before_cli_invocation(
            provider="cursor-agent-cli",
            model="composer-2.5",
            prompt="stopped",
            schema=EXTRACTED_ENTITIES_SCHEMA,
            semantic_request_class="ExtractedEntities",
            max_tokens=100,
        )
    assert owner_stop_checks == 1

    oversized = GraphitiModelUsageObserver(
        service=service,
        envelope=envelope,
        clock=lambda: T0 + timedelta(seconds=2),
        owner_stop_check=lambda: None,
        deadline=T0 + timedelta(minutes=3),
    )
    with pytest.raises(ModelUsageAdmissionError, match="differs from invocation policy"):
        oversized.before_cli_invocation(
            provider="cursor-agent-cli",
            model="composer-2.5",
            prompt="oversized",
            schema=EXTRACTED_ENTITIES_SCHEMA,
            semantic_request_class="ExtractedEntities",
            max_tokens=16_385,
        )

    with pytest.raises(ModelUsageAdmissionError, match="checked qualified policy"):
        oversized.before_cli_invocation(
            provider="unqualified-provider",
            model="unqualified-model",
            prompt="route drift",
            schema=EXTRACTED_ENTITIES_SCHEMA,
            semantic_request_class="ExtractedEntities",
            max_tokens=100,
        )

    assert service.graphiti_request_records(envelope_id=envelope.envelope_id)[
        "requests"
    ] == []


def test_restart_distinguishes_pre_dispatch_zero_from_possible_io_uncertainty(
    tmp_path: Path,
) -> None:
    pre_service, pre_envelope, pre_policy, shape = _service_fixture(
        tmp_path / "pre"
    )
    pre_allocation, pre_identity = _bound_request(
        service=pre_service,
        envelope=pre_envelope,
        policy=pre_policy,
        shape=shape,
        ordinal=1,
        semantic="pre-dispatch",
    )
    pre_service.allocate_graphiti_request(
        pre_allocation,
        identity=pre_identity,
        max_distinct_internal_requests=shape.max_distinct_internal_requests,
    )

    restarted_pre = ModelUsageService(pre_service.path)
    restarted_pre.recover_unresolved(observed_at=T0 + timedelta(minutes=21))
    pre_leaf = restarted_pre.query(
        start=T0, end=T0 + timedelta(minutes=22)
    )["leaves"][0]
    assert pre_leaf["graphiti_internal_request"]["canonical_digest"] == (
        pre_identity.canonical_digest
    )
    assert pre_leaf["invocation_outcome"] == "RECOVERED_PRE_DISPATCH"
    assert pre_leaf["pre_dispatch_zero_proved"] is True
    assert pre_leaf["total_tokens"] == 0

    io_service, io_envelope, io_policy, io_shape = _service_fixture(tmp_path / "io")
    io_allocation, io_identity = _bound_request(
        service=io_service,
        envelope=io_envelope,
        policy=io_policy,
        shape=io_shape,
        ordinal=1,
        semantic="possible-io",
    )
    io_service.allocate_graphiti_request(
        io_allocation,
        identity=io_identity,
        max_distinct_internal_requests=io_shape.max_distinct_internal_requests,
    )
    io_service.observe_transport(
        invocation_id=io_allocation.invocation_id,
        observed_at=T0 + timedelta(seconds=2),
        state="DISPATCH_STARTED",
        evidence_digest=digest_canonical({"possible_io": True}),
    )

    restarted_io = ModelUsageService(io_service.path)
    restarted_io.recover_unresolved(observed_at=T0 + timedelta(minutes=21))
    io_leaf = restarted_io.query(start=T0, end=T0 + timedelta(minutes=22))[
        "leaves"
    ][0]
    assert io_leaf["invocation_outcome"] == "RECOVERED_UNRESOLVED"
    assert io_leaf["usage_status"] == "AMBIGUOUS"
    assert io_leaf["total_tokens"] is None


def test_graphiti_attempt_cannot_complete_before_every_leaf_has_a_terminal(
    tmp_path: Path,
) -> None:
    service, envelope, policy, shape = _service_fixture(tmp_path)
    allocation, identity = _bound_request(
        service=service,
        envelope=envelope,
        policy=policy,
        shape=shape,
        ordinal=1,
        semantic="terminal-gate",
    )
    service.allocate_graphiti_request(
        allocation,
        identity=identity,
        max_distinct_internal_requests=shape.max_distinct_internal_requests,
    )

    with pytest.raises(ModelUsageIntegrityError, match="terminal receipt"):
        service.record_work_outcome(
            envelope_id=envelope.envelope_id,
            outcome="ZERO_PROPOSAL",
            outcome_record_id="outcome-before-terminal",
            payload_digest=None,
            terminal_at=T0 + timedelta(seconds=3),
            retained_proposal_count=0,
        )

    service.complete(
        InvocationTerminal.create(
            invocation_id=allocation.invocation_id,
            outcome="COMPLETE",
            failure_class=None,
            usage_status=UsageStatus.REPORTED,
            components=UsageComponents(
                input_tokens=4,
                output_tokens=0,
                total_tokens=4,
                provenance="PROVIDER_REPORTED",
            ),
            dispatch_at=T0 + timedelta(seconds=2),
            completed_at=T0 + timedelta(seconds=3),
            observed_at=T0 + timedelta(seconds=3),
            subscription_cli_chat_not_cash_debited=True,
        )
    )
    service.record_work_outcome(
        envelope_id=envelope.envelope_id,
        outcome="ZERO_PROPOSAL",
        outcome_record_id="outcome-after-terminal",
        payload_digest=None,
        terminal_at=T0 + timedelta(seconds=4),
        retained_proposal_count=0,
    )
