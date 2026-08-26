"""EVALUATION Graphiti runner for corpus ingest, decoupled from CONT writes."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol, runtime_checkable

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
)
from newsroom.control_plane.corpus import CorpusIngestUnit
from newsroom.control_plane.graphiti_fallback_policy import (
    FallbackEligibility,
    classify_graphiti_fallback,
    load_checked_graphiti_fallback_circuit_policy,
)
from newsroom.control_plane.graphiti_requests import (
    GraphitiCallShapePolicy,
    GraphitiInternalRequestIdentity,
    GraphitiLeafClass,
    graphiti_semantic_state_digest,
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
from newsroom.graphiti_adapter.contracts import GRAPHITI_PROMPT_COMPONENT
from newsroom.graphiti_adapter.evaluation_packet import (
    GRAPHITI_CHAT_FALLBACK,
    GRAPHITI_CHAT_MODEL,
    GRAPHITI_CORE_RELEASE,
    GRAPHITI_EMBEDDING_MODEL,
    GRAPHITI_GENERATION_ID,
    GRAPHITI_WORKSPACE_GROUP,
    GROK_CHAT_REASONING,
)
from newsroom.graphiti_adapter.temporal_vocabulary import TemporalBasis


@dataclass(frozen=True, slots=True)
class GraphitiCycleResult:
    ingest_id: str
    source_id: str
    item_key: str
    outcome: str
    proposal_count: int
    entity_count: int
    relation_count: int
    failure_code: str
    temporal_basis: TemporalBasis
    reference_time: str
    generation_id: str = GRAPHITI_GENERATION_ID
    receipt_digest: str = ""
    workspace_group: str = GRAPHITI_WORKSPACE_GROUP
    episode_uuid: str = ""
    entities: tuple[dict[str, object], ...] = ()
    relations: tuple[dict[str, object], ...] = ()
    proposals: tuple[dict[str, object], ...] = ()
    passages: tuple[dict[str, object], ...] = ()
    chat_invocations: tuple[dict[str, object], ...] = ()
    embedding_usage: dict[str, object] | None = None
    token_usage: dict[str, object] | None = None
    request_tokens: int = 0
    response_tokens: int = 0
    cost_microunits: int = 0
    usage_basis: str = "UNOBSERVED"
    prompt_version: str = GRAPHITI_PROMPT_COMPONENT.component_version
    framework: str = GRAPHITI_CORE_RELEASE
    chat: str = GRAPHITI_CHAT_MODEL
    chat_fallback: str = GRAPHITI_CHAT_FALLBACK
    embedding: str = GRAPHITI_EMBEDDING_MODEL
    attempt_number: int = 1
    provider_attempt_number: int = 1
    predecessor_episode_uuid: str | None = None
    raw_receipt: dict[str, object] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.temporal_basis, TemporalBasis):
            raise TypeError("GraphitiCycleResult.temporal_basis must be typed")


class GraphitiPort(Protocol):
    def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult: ...


@runtime_checkable
class GovernedRealGraphitiPort(GraphitiPort, Protocol):
    requires_canonical_control_plane_stores: bool

    def ingest_until(
        self, unit: CorpusIngestUnit, *, deadline: datetime
    ) -> GraphitiCycleResult: ...

    def ingest_with_usage(
        self,
        unit: CorpusIngestUnit,
        *,
        model_usage: ModelUsageService,
        cycle_id: str,
        dispatch_authority: Mapping[str, object],
        owner_stop_check: Callable[[], None],
        deadline: datetime | None = None,
    ) -> GraphitiCycleResult: ...


GRAPHITI_CONTEXT_IDENTITY = "graphiti-combined-temporal-hermetic-v1"
GRAPHITI_CONTEXT_MANIFEST_SCHEMA_VERSION = (
    "newsroom.graphiti-hermetic-context-manifest.v1"
)
GRAPHITI_CHAT_PRIMARY_ROUTE = "GRAPHITI_CHAT_PRIMARY"
GRAPHITI_CHAT_FALLBACK_ROUTE = "GRAPHITI_CHAT_FALLBACK"
GRAPHITI_EMBEDDING_ROUTE = "GRAPHITI_EMBEDDING"
_GRAPHITI_ADAPTER_DIRECTORY = Path(__file__).parent.parent / "graphiti_adapter"
_GRAPHITI_HERMETIC_ENVIRONMENT_KEYS = (
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "TMPDIR",
    "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_STATE_HOME",
)


def _graphiti_transport_implementation_revision(
    leaf_class: GraphitiLeafClass,
) -> str:
    if leaf_class is GraphitiLeafClass.EMBEDDING:
        return digest_bytes(
            (_GRAPHITI_ADAPTER_DIRECTORY / "embedding_meter.py").read_bytes()
        )
    sources = (
        _GRAPHITI_ADAPTER_DIRECTORY / "cli_process.py",
        _GRAPHITI_ADAPTER_DIRECTORY / "cli_client.py",
        _GRAPHITI_ADAPTER_DIRECTORY / "cursor_transport.py",
    )
    retained = b"".join(
        path.name.encode("utf-8") + b"\x00" + path.read_bytes() + b"\x00"
        for path in sources
    )
    return digest_bytes(retained)


class GraphitiModelUsageObserver:
    def __init__(
        self,
        *,
        service: ModelUsageService,
        envelope: WorkEnvelope,
        clock: Callable[[], datetime],
        effective_revision_digest: str | None = None,
        ingest_obligation_id: str | None = None,
        provider_attempt_number: int = 1,
        deadline: datetime | None = None,
        dispatch_authority_digest: str | None = None,
        owner_stop_check: Callable[[], None],
        call_shape_policy: GraphitiCallShapePolicy | None = None,
    ) -> None:
        self._service = service
        self._envelope = envelope
        self._clock = clock
        if envelope.graphiti_attempt_id is None:
            raise ValueError("Graphiti usage observer lacks an attempt identity")
        self._ordinal = (
            service.next_graphiti_internal_ordinal(
                graphiti_attempt_id=envelope.graphiti_attempt_id
            )
            - 1
        )
        self._allocations: list[InvocationAllocation] = []
        self._dispatch_at: dict[str, datetime] = {}
        self._policies: dict[str, InvocationEfficiencyPolicy] = {}
        self._primary_by_request: dict[str, str] = {}
        self._terminal_outcome: dict[str, str] = {}
        self._fallback_by_primary: set[str] = set()
        self._shape = call_shape_policy or load_checked_graphiti_call_shape_policy()
        self._fallback_policy = load_checked_graphiti_fallback_circuit_policy()
        if self._fallback_policy.call_shape_policy_digest != self._shape.canonical_digest:
            raise ValueError("Graphiti fallback policy differs from the call shape")
        self._effective_revision_digest = effective_revision_digest or digest_canonical(
            {"ingest_id": envelope.ingest_id, "basis": "LEGACY_TEST_FIXTURE"}
        )
        self._ingest_obligation_id = ingest_obligation_id or envelope.ingest_id
        if self._ingest_obligation_id is None:
            raise ValueError("Graphiti usage observer lacks an ingest obligation")
        if provider_attempt_number <= 0:
            raise ValueError("Graphiti provider attempt number must be positive")
        self._provider_attempt_number = provider_attempt_number
        self._deadline = deadline
        self._dispatch_authority_digest = (
            dispatch_authority_digest
            or digest_canonical(
                {
                    "envelope_id": envelope.envelope_id,
                    "basis": "LEGACY_TEST_FIXTURE",
                }
            )
        )
        self._owner_stop_check = owner_stop_check

    def _policy_for(
        self,
        *,
        workload: WorkloadClass,
        provider: str,
        route: str,
        model: str,
        reasoning: str,
        output_schema_digest: str,
        semantic_request_class: str,
        response_schema_identity: str,
    ) -> InvocationEfficiencyPolicy:
        leaf_class = (
            GraphitiLeafClass.EMBEDDING
            if workload is WorkloadClass.GRAPHITI_EMBEDDING
            else GraphitiLeafClass.FALLBACK
            if workload is WorkloadClass.GRAPHITI_CHAT_FALLBACK
            else GraphitiLeafClass.PRIMARY
        )
        route_contract = self._shape.route_for(leaf_class)
        implementation_revision = _graphiti_transport_implementation_revision(
            leaf_class
        )
        if implementation_revision != route_contract.implementation_revision:
            raise ModelUsageAdmissionError(
                "Graphiti transport implementation differs from the checked policy"
            )
        self._shape.qualify_request(
            leaf_class=leaf_class,
            semantic_request_class=semantic_request_class,
            response_schema_identity=response_schema_identity,
            response_schema_digest=output_schema_digest,
        )
        if (
            provider,
            route,
            model,
            reasoning,
        ) != (
            route_contract.provider,
            route_contract.route,
            route_contract.model,
            route_contract.reasoning,
        ):
            raise ModelUsageAdmissionError(
                "Graphiti route differs from the checked qualified policy"
            )
        policy = InvocationEfficiencyPolicy.create(
            policy_id=(
                f"graphiti-{workload.value.lower()}-{semantic_request_class.lower()}-"
                f"{output_schema_digest.removeprefix('sha256:')[:12]}"
            ),
            version=self._shape.version,
            workload_class=workload,
            provider=provider,
            route=route,
            model=model,
            reasoning=reasoning,
            one_turn=True,
            exact_input=True,
            skills_enabled=False,
            tools_enabled=False,
            mcp_enabled=False,
            prior_message_count=0,
            command_semantic_version=route_contract.command_semantic_version,
            command_flags=route_contract.command_flags,
            context_manifest_schema_version=GRAPHITI_CONTEXT_MANIFEST_SCHEMA_VERSION,
            disabled_capabilities=route_contract.disabled_capabilities,
            implementation_revision=implementation_revision,
            max_prompt_bytes=route_contract.max_prompt_bytes,
            max_context_tokens=route_contract.max_context_tokens,
            max_output_tokens=route_contract.max_output_tokens,
            max_total_tokens=route_contract.max_total_tokens,
            prompt_contract_version=GRAPHITI_PROMPT_COMPONENT.component_version,
            output_schema_digest=output_schema_digest,
            allowed_context_identities=(GRAPHITI_CONTEXT_IDENTITY,),
            allowed_config_identities=(route_contract.config_identity,),
            hard_estimate_ceiling_tokens=None,
            evidence_digest=digest_canonical(
                {
                    "call_shape_policy_digest": self._shape.canonical_digest,
                    "fallback_circuit_policy_digest": (
                        self._fallback_policy.canonical_digest
                    ),
                    "qualified_route": route_contract.as_record(),
                    "semantic_request_class": semantic_request_class,
                    "output_schema_digest": output_schema_digest,
                    "bounds": {
                        "prompt_bytes": route_contract.max_prompt_bytes,
                        "context_tokens": route_contract.max_context_tokens,
                        "output_tokens": route_contract.max_output_tokens,
                    },
                }
            ),
            qualified=True,
        )
        self._service.register_policy(policy)
        return policy

    def _allocate(
        self,
        *,
        workload: WorkloadClass,
        provider: str,
        route: str,
        model: str,
        reasoning: str,
        prompt_bytes: bytes,
        semantic_request_class: str,
        response_schema_identity: str,
        output_schema_digest: str,
        requested_max_tokens: int,
        parent_invocation_id: str | None = None,
    ) -> InvocationAllocation:
        now = self._clock().astimezone(UTC)
        if self._deadline is not None:
            if self._deadline.tzinfo is None or self._deadline.utcoffset() is None:
                raise ValueError("Graphiti dispatch deadline must be timezone-aware")
            if now >= self._deadline.astimezone(UTC):
                raise ValueError("Graphiti dispatch deadline has expired")
        policy = self._policy_for(
            workload=workload,
            provider=provider,
            route=route,
            model=model,
            reasoning=reasoning,
            output_schema_digest=output_schema_digest,
            semantic_request_class=semantic_request_class,
            response_schema_identity=response_schema_identity,
        )
        if requested_max_tokens <= 0:
            requested_max_tokens = policy.max_output_tokens
        if (
            not policy.one_turn
            or not policy.exact_input
            or policy.skills_enabled
            or policy.tools_enabled
            or policy.mcp_enabled
            or policy.prior_message_count != 0
        ):
            raise ValueError(
                "Graphiti invocation controls do not match the exact one-turn contract"
            )
        self._ordinal += 1
        allocated_at = now
        prompt_digest = digest_bytes(prompt_bytes)
        leaf_class = (
            GraphitiLeafClass.EMBEDDING
            if workload is WorkloadClass.GRAPHITI_EMBEDDING
            else GraphitiLeafClass.FALLBACK
            if workload is WorkloadClass.GRAPHITI_CHAT_FALLBACK
            else GraphitiLeafClass.PRIMARY
        )
        route_contract = self._shape.route_for(leaf_class)
        retry_state_digest = digest_canonical(
            {
                "leaf_class": leaf_class.value,
                "parent_invocation_id": parent_invocation_id,
                "semantic_request_class": semantic_request_class,
            }
        )
        semantic_state_digest = graphiti_semantic_state_digest(
            semantic_request_class=semantic_request_class,
            prompt_digest=prompt_digest,
            response_schema_digest=output_schema_digest,
            requested_max_tokens=requested_max_tokens,
            leaf_class=leaf_class,
            retry_state_digest=retry_state_digest,
        )
        provider_attempt_id = (
            f"{self._envelope.graphiti_attempt_id}:provider-attempt:"
            f"{self._provider_attempt_number}:leaf:{self._ordinal}"
        )
        system_digest = digest_canonical(
            {"system_identity": self._shape.prompt_identity}
        )
        request_digest = digest_canonical(
            {
                "provider": provider,
                "route": route,
                "model": model,
                "reasoning": reasoning,
                "command_semantic_version": route_contract.command_semantic_version,
                "command_flags": list(route_contract.command_flags),
                "implementation_revision": policy.implementation_revision,
                "system_digest": system_digest,
                "prompt_digest": prompt_digest,
                "output_schema_digest": output_schema_digest,
            }
        )
        context_manifest = {
            "schema_version": GRAPHITI_CONTEXT_MANIFEST_SCHEMA_VERSION,
            "provider": provider,
            "route": route,
            "model": model,
            "reasoning": reasoning,
            "command_semantic_version": route_contract.command_semantic_version,
            "command_flags": list(route_contract.command_flags),
            "implementation_revision": policy.implementation_revision,
            "implementation_worktree_clean": (
                policy.implementation_revision
                == _graphiti_transport_implementation_revision(leaf_class)
            ),
            "disabled_capabilities": list(route_contract.disabled_capabilities),
            "working_directory_inventory": [],
            "working_directory_inventory_digest": digest_canonical([]),
            "environment_keys": (
                []
                if leaf_class is GraphitiLeafClass.EMBEDDING
                else list(_GRAPHITI_HERMETIC_ENVIRONMENT_KEYS)
            ),
            "config_identity": route_contract.config_identity,
            "context_identity": GRAPHITI_CONTEXT_IDENTITY,
            "system_digest": system_digest,
            "prompt_contract_version": GRAPHITI_PROMPT_COMPONENT.component_version,
            "prompt_bytes": len(prompt_bytes),
            "prompt_digest": prompt_digest,
            "schema_digest": output_schema_digest,
            "output_schema_digest": output_schema_digest,
            "evidence_package_digest": self._effective_revision_digest,
            "evidence_package_bytes": len(prompt_bytes),
            "effective_revision_digest": self._effective_revision_digest,
            "ingest_obligation_id": self._ingest_obligation_id,
            "graphiti_attempt_id": self._envelope.graphiti_attempt_id,
            "provider_attempt_id": provider_attempt_id,
            "dispatch_authority_digest": self._dispatch_authority_digest,
            "dispatch_deadline": (
                None
                if self._deadline is None
                else self._deadline.astimezone(UTC).isoformat()
            ),
            "semantic_state_digest": semantic_state_digest,
            "request_digest": request_digest,
            "call_shape_policy_digest": self._shape.canonical_digest,
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
        context_manifest_digest = digest_canonical(context_manifest)
        self._service.retain_context_manifest(
            {
                "context_manifest_digest": context_manifest_digest,
                **context_manifest,
            }
        )
        allocation = InvocationAllocation.create(
            envelope_id=self._envelope.envelope_id,
            cycle_id=self._envelope.cycle_id,
            leaf_ordinal=self._ordinal,
            workload_class=workload,
            invocation_policy_digest=policy.canonical_digest,
            provider=provider,
            route=route,
            model=model,
            reasoning=reasoning,
            prompt_contract_version=GRAPHITI_PROMPT_COMPONENT.component_version,
            prompt_bytes=len(prompt_bytes),
            prompt_digest=prompt_digest,
            request_digest=request_digest,
            output_schema_digest=output_schema_digest,
            max_output_tokens=requested_max_tokens,
            context_manifest_digest=context_manifest_digest,
            context_identity=GRAPHITI_CONTEXT_IDENTITY,
            config_identity=route_contract.config_identity,
            one_turn=True,
            exact_input=True,
            skills_enabled=False,
            tools_enabled=False,
            mcp_enabled=False,
            prior_message_count=0,
            allocated_at=allocated_at,
            recovery_deadline_at=allocated_at + timedelta(minutes=16),
            parent_invocation_id=parent_invocation_id,
        )
        self._owner_stop_check()
        route_circuit_state = str(self._service.route_state(route)["state"])
        if route_circuit_state != "CLOSED":
            raise ModelUsageAdmissionError("affected route circuit is open")
        identity = GraphitiInternalRequestIdentity.create(
            effective_revision_digest=self._effective_revision_digest,
            ingest_obligation_id=self._ingest_obligation_id,
            graphiti_attempt_id=str(self._envelope.graphiti_attempt_id),
            provider_attempt_id=provider_attempt_id,
            internal_ordinal=self._ordinal,
            semantic_request_class=semantic_request_class,
            provider=provider,
            model=model,
            reasoning=reasoning,
            prompt_bytes=len(prompt_bytes),
            prompt_digest=prompt_digest,
            response_schema_identity=response_schema_identity,
            response_schema_digest=output_schema_digest,
            requested_max_tokens=requested_max_tokens,
            framework_identity=self._shape.framework_identity,
            prompt_identity=self._shape.prompt_identity,
            ontology_identity=self._shape.ontology_identity,
            temporal_identity=self._shape.temporal_identity,
            generation_policy_identity=self._shape.generation_policy_identity,
            context_manifest_digest=context_manifest_digest,
            leaf_class=leaf_class,
            retry_state_digest=retry_state_digest,
            parent_invocation_id=parent_invocation_id,
            envelope_id=self._envelope.envelope_id,
            invocation_id=allocation.invocation_id,
            invocation_policy_digest=policy.canonical_digest,
            call_shape_policy_digest=self._shape.canonical_digest,
            dispatch_authority_digest=self._dispatch_authority_digest,
            dispatch_deadline_at=(
                None
                if self._deadline is None
                else self._deadline.astimezone(UTC).isoformat()
            ),
            owner_stop_clear=True,
            route_circuit_state=route_circuit_state,
        )
        self._service.allocate_graphiti_request(
            allocation,
            identity=identity,
            max_distinct_internal_requests=self._shape.max_distinct_internal_requests,
        )
        self._allocations.append(allocation)
        self._policies[allocation.invocation_id] = policy
        return allocation

    def transport_dispatch_started(self, token: object) -> None:
        """Retain the provider-I/O boundary after local preflight succeeds."""

        if not isinstance(token, InvocationAllocation):
            raise TypeError("Graphiti transport token is not an allocation")
        if token.invocation_id in self._dispatch_at:
            raise ModelUsageAdmissionError("Graphiti transport dispatch repeated")
        dispatch_at = self._clock().astimezone(UTC)
        if self._deadline is not None and dispatch_at >= self._deadline.astimezone(UTC):
            raise ModelUsageAdmissionError(
                "Graphiti dispatch deadline expired during local preflight"
            )
        self._owner_stop_check()
        if self._service.route_state(token.route)["state"] != "CLOSED":
            raise ModelUsageAdmissionError(
                "Graphiti route circuit opened during local preflight"
            )
        self._service.observe_transport(
            invocation_id=token.invocation_id,
            observed_at=dispatch_at,
            state="DISPATCH_STARTED",
            evidence_digest=digest_canonical(
                {
                    "invocation_id": token.invocation_id,
                    "provider": token.provider,
                    "route": token.route,
                    "request_digest": token.request_digest,
                }
            ),
        )
        self._dispatch_at[token.invocation_id] = dispatch_at

    def link_provider_attempts(
        self, *, provider_attempt_number: int, linked_at: datetime
    ) -> None:
        if provider_attempt_number <= 0:
            raise ValueError("Graphiti provider attempt number must be positive")
        del linked_at
        if not self._allocations:
            return
        if provider_attempt_number != self._provider_attempt_number:
            raise ValueError("Graphiti provider attempt identity changed after dispatch")

    def before_cli_invocation(
        self,
        *,
        provider: str,
        model: str,
        prompt: str,
        schema: str | None,
        semantic_request_class: str = "UNSTRUCTURED",
        max_tokens: int = 0,
    ) -> object:
        prompt_digest = digest_bytes(prompt.encode("utf-8"))
        schema_digest = digest_canonical(
            {"response_schema": schema or "UNSTRUCTURED"}
        )
        request_key = digest_canonical(
            {
                "semantic_request_class": semantic_request_class,
                "prompt_digest": prompt_digest,
                "response_schema_digest": schema_digest,
                "requested_max_tokens": max_tokens,
            }
        )
        primary = provider == "cursor-agent-cli"
        fallback = provider == "grok-build-cli"
        parent_invocation_id = (
            self._primary_by_request.get(request_key) if fallback else None
        )
        parent_outcome = (
            None
            if parent_invocation_id is None
            else self._terminal_outcome.get(parent_invocation_id)
        )
        if fallback and (
            parent_outcome is None
            or classify_graphiti_fallback(parent_outcome).eligibility
            is not FallbackEligibility.ELIGIBLE
        ):
            raise ModelUsageAdmissionError(
                "Graphiti fallback requires a malformed primary"
            )
        if fallback and parent_invocation_id in self._fallback_by_primary:
            raise ModelUsageAdmissionError(
                "Graphiti primary already has its single fallback leaf"
            )
        allocation = self._allocate(
            workload=(
                WorkloadClass.GRAPHITI_CHAT_PRIMARY
                if primary
                else WorkloadClass.GRAPHITI_CHAT_FALLBACK
            ),
            provider=provider,
            route=(
                GRAPHITI_CHAT_PRIMARY_ROUTE
                if primary
                else GRAPHITI_CHAT_FALLBACK_ROUTE
            ),
            model=model,
            reasoning="provider-default" if primary else GROK_CHAT_REASONING,
            prompt_bytes=prompt.encode("utf-8"),
            semantic_request_class=semantic_request_class,
            response_schema_identity=semantic_request_class,
            output_schema_digest=schema_digest,
            requested_max_tokens=max_tokens,
            parent_invocation_id=parent_invocation_id,
        )
        if primary:
            self._primary_by_request[request_key] = allocation.invocation_id
        elif fallback and parent_invocation_id is not None:
            self._fallback_by_primary.add(parent_invocation_id)
        return allocation

    def after_cli_invocation(
        self,
        token: object,
        *,
        outcome: str,
        usage: dict[str, object],
    ) -> dict[str, str]:
        if not isinstance(token, InvocationAllocation):
            raise TypeError("Graphiti chat usage token is not an allocation")
        binding = self._complete(
            token,
            outcome=outcome,
            usage=usage,
            od_011_reference=None,
            subscription_not_debited=True,
        )
        self._terminal_outcome[token.invocation_id] = outcome
        return binding

    def before_embedding_invocation(
        self, *, provider: str, model: str, input_data: object
    ) -> object:
        prompt_bytes = canonical_json_bytes({"embedding_input": input_data})
        return self._allocate(
            workload=WorkloadClass.GRAPHITI_EMBEDDING,
            provider=provider,
            route=GRAPHITI_EMBEDDING_ROUTE,
            model=model,
            reasoning="none",
            prompt_bytes=prompt_bytes,
            semantic_request_class="EMBEDDING_VECTOR",
            response_schema_identity="embedding-vector",
            output_schema_digest=digest_canonical(
                {"schema": "embedding-vector", "model": model}
            ),
            requested_max_tokens=1,
        )

    def after_embedding_invocation(
        self,
        token: object,
        *,
        outcome: str,
        usage: dict[str, object],
    ) -> dict[str, str]:
        if not isinstance(token, InvocationAllocation):
            raise TypeError("Graphiti embedding usage token is not an allocation")
        return self._complete(
            token,
            outcome=outcome,
            usage=usage,
            od_011_reference="OD-011:EVALUATION_GRAPHITI_EMBEDDING",
            subscription_not_debited=False,
        )

    def _complete(
        self,
        allocation: InvocationAllocation,
        *,
        outcome: str,
        usage: dict[str, object],
        od_011_reference: str | None,
        subscription_not_debited: bool,
    ) -> dict[str, str]:
        reported = usage.get("usage_basis") == "PROVIDER_REPORTED"
        no_provider_call = usage.get("usage_basis") == "NO_PROVIDER_CALL"
        policy = self._policies[allocation.invocation_id]
        components = (
            UsageComponents(
                input_tokens=usage.get("input_tokens"),  # type: ignore[arg-type]
                output_tokens=usage.get("output_tokens"),  # type: ignore[arg-type]
                cached_read_tokens=usage.get("cached_read_tokens"),  # type: ignore[arg-type]
                cached_write_tokens=usage.get("cached_write_tokens"),  # type: ignore[arg-type]
                reasoning_tokens=usage.get("reasoning_tokens"),  # type: ignore[arg-type]
                context_tokens=usage.get("context_tokens"),  # type: ignore[arg-type]
                total_tokens=usage.get("total_tokens"),  # type: ignore[arg-type]
                provenance="PROVIDER_REPORTED",
            )
            if reported
            else (
                UsageComponents(total_tokens=0, provenance="CLI_DERIVED")
                if no_provider_call
                else UsageComponents(
                    total_tokens=policy.hard_estimate_ceiling_tokens,
                    provenance="BOUNDED_ESTIMATE",
                )
                if policy.hard_estimate_ceiling_tokens is not None
                else UsageComponents(
                    provenance="UNAVAILABLE",
                )
            )
        )
        telemetry = usage.get("provider_telemetry", usage)
        telemetry_mapping = telemetry if isinstance(telemetry, dict) else usage
        completed_at = self._clock().astimezone(UTC)
        outcome_class = classify_graphiti_fallback(outcome).outcome_class
        route_circuit_reason = (
            outcome_class.value
            if outcome_class in self._fallback_policy.circuit_open_classes
            else None
        )
        terminal = self._service.complete(
            InvocationTerminal.create(
                invocation_id=allocation.invocation_id,
                outcome=outcome,
                failure_class=(
                    None
                    if reported
                    else (
                        outcome
                        if no_provider_call
                        else "MISSING_PROVIDER_TELEMETRY"
                    )
                ),
                usage_status=(
                    UsageStatus.REPORTED
                    if reported or no_provider_call
                    else UsageStatus.ESTIMATED
                    if policy.hard_estimate_ceiling_tokens is not None
                    else UsageStatus.UNREPORTED
                ),
                components=components,
                dispatch_at=(
                    None
                    if no_provider_call
                    else self._dispatch_at[allocation.invocation_id]
                ),
                completed_at=completed_at,
                observed_at=completed_at,
                provider_telemetry_digest=(
                    digest_canonical(telemetry_mapping) if reported else None
                ),
                raw_telemetry_pointer=(
                    "sqlite-private://model_provider_telemetry/"
                    f"{allocation.invocation_id}"
                    if reported
                    else None
                ),
                od_011_reference=od_011_reference,
                subscription_cli_chat_not_cash_debited=subscription_not_debited,
                pre_dispatch_zero_proved=no_provider_call,
                estimate_policy_digest=(
                    policy.canonical_digest
                    if not reported
                    and not no_provider_call
                    and policy.hard_estimate_ceiling_tokens is not None
                    else None
                ),
                estimate_calculation=(
                    "qualified_policy.hard_estimate_ceiling_tokens="
                    f"{policy.hard_estimate_ceiling_tokens}"
                    if not reported
                    and not no_provider_call
                    and policy.hard_estimate_ceiling_tokens is not None
                    else None
                ),
            ),
            provider_telemetry=telemetry_mapping if reported else None,
        )
        if route_circuit_reason is not None:
            self._service.open_route_circuit(
                route=allocation.route,
                reason=route_circuit_reason,
                invocation_id=allocation.invocation_id,
                recorded_at=completed_at,
            )
        return {
            "model_work_envelope_id": allocation.envelope_id,
            "model_invocation_id": allocation.invocation_id,
            "model_invocation_allocation_digest": allocation.canonical_digest,
            "model_invocation_terminal_digest": terminal.terminal_digest,
        }


class EvaluationGraphitiRunner:
    """Real Graphiti under EVALUATION. Does not write the ledger or admitted labels."""

    requires_canonical_control_plane_stores = True

    def __init__(
        self, *, clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC)
    ) -> None:
        self._clock = clock
        self._pending_usage: dict[
            tuple[str, int], tuple[ModelUsageService, WorkEnvelope]
        ] = {}

    def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
        return self._ingest(unit, deadline=None)

    def ingest_until(
        self, unit: CorpusIngestUnit, *, deadline: datetime
    ) -> GraphitiCycleResult:
        return self._ingest(unit, deadline=deadline)

    def ingest_with_usage(
        self,
        unit: CorpusIngestUnit,
        *,
        model_usage: ModelUsageService,
        cycle_id: str,
        dispatch_authority: Mapping[str, object],
        owner_stop_check: Callable[[], None],
        deadline: datetime | None = None,
    ) -> GraphitiCycleResult:
        envelope = WorkEnvelope.create(
            cycle_id=cycle_id,
            workload_class=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
            admitted_at=self._clock().astimezone(UTC),
            admission_decision_id=None,
            candidate_id=None,
            hypothesis_digest=None,
            evidence_package_digest=None,
            ingest_id=unit.ingest_id,
            graphiti_attempt_id=f"{unit.ingest_id}:{unit.attempt_number}",
        )
        envelope = model_usage.resume_or_open_graphiti_envelope(envelope)
        observer = GraphitiModelUsageObserver(
            service=model_usage,
            envelope=envelope,
            clock=self._clock,
            effective_revision_digest=digest_canonical(
                {
                    "source_id": unit.effective_revision.source_id,
                    "item_key": unit.effective_revision.item_key,
                    "revision_digest": unit.effective_revision.revision_digest,
                    "first_observed_at": unit.effective_revision.first_observed_at,
                }
            ),
            ingest_obligation_id=unit.ingest_id,
            provider_attempt_number=unit.attempt_number,
            deadline=deadline,
            dispatch_authority_digest=digest_canonical(dict(dispatch_authority)),
            owner_stop_check=owner_stop_check,
        )
        self._pending_usage[(unit.ingest_id, unit.attempt_number)] = (
            model_usage,
            envelope,
        )
        result = self._ingest(unit, deadline=deadline, invocation_observer=observer)
        terminal_at = self._clock().astimezone(UTC)
        observer.link_provider_attempts(
            provider_attempt_number=result.provider_attempt_number,
            linked_at=terminal_at,
        )
        return result

    def finalise_usage(
        self,
        unit: CorpusIngestUnit,
        *,
        outcome: str,
        outcome_record_id: str,
        retained_proposal_count: int,
        terminal_at: datetime,
        connection: sqlite3.Connection,
    ) -> None:
        pending = self._pending_usage.pop(
            (unit.ingest_id, unit.attempt_number), None
        )
        if pending is None:
            return
        model_usage, envelope = pending
        model_usage.record_work_outcome(
            envelope_id=envelope.envelope_id,
            outcome=outcome,
            outcome_record_id=outcome_record_id,
            payload_digest=None,
            terminal_at=terminal_at,
            retained_proposal_count=retained_proposal_count,
            connection=connection,
        )

    def _ingest(
        self,
        unit: CorpusIngestUnit,
        *,
        deadline: datetime | None,
        invocation_observer: object | None = None,
    ) -> GraphitiCycleResult:
        from newsroom.graphiti_adapter.evaluation_attempt import (
            evaluation_attempt_for_body,
        )
        from newsroom.graphiti_adapter.real import RealGraphitiAdapter

        temporal = unit.temporal()
        attempt = evaluation_attempt_for_body(
            episode_body=unit.episode_body,
            ingest_id=unit.ingest_id,
            proving_run_id=unit.proving_run_id,
            source_id=unit.source_id,
            item_key=unit.item_key,
            observation_digest=unit.observation_digest,
            published_at=unit.published_at,
            updated_at=unit.updated_at,
            effective_revision=unit.effective_revision,
            canonical_url=unit.canonical_url,
            revision_digest=unit.revision_digest,
            representation_digest=unit.representation_digest,
            authority_ids=(
                None
                if unit.authority is None
                else (
                    unit.authority.admission_id,
                    unit.authority.access_decision_id,
                    unit.authority.definition_id,
                    unit.authority.definition_version_id,
                    unit.authority.item_id,
                    unit.authority.revision_id,
                    unit.authority.representation_id,
                )
            ),
            attempt_number=unit.attempt_number,
            predecessor_episode_uuid=unit.predecessor_ingest_id,
        )
        with TemporaryDirectory() as root:
            adapter = (
                RealGraphitiAdapter(execution_deadline=deadline)
                if invocation_observer is None
                else RealGraphitiAdapter(
                    execution_deadline=deadline,
                    invocation_observer=invocation_observer,
                )
            )
            execution = adapter.execute(
                attempt=attempt,
                workspace_root=Path(root),
            )
        raw = (
            execution.produced.raw_output_value
            or execution.produced.attempt_receipt_value
        )
        payload = raw if isinstance(raw, dict) else {}
        relations = (
            tuple(payload["relations"])
            if isinstance(payload.get("relations"), list)
            else ()
        )
        entities = (
            tuple(payload["entities"])
            if isinstance(payload.get("entities"), list)
            else ()
        )
        invocations = payload.get("chat_invocations")
        proposal_receipts = payload.get("proposals")
        passage_receipts = payload.get("passages")
        embedding_usage = payload.get("embedding_usage")
        token_usage = payload.get("token_usage")
        usage = execution.produced.usage
        usage_basis = payload.get("usage_basis")
        return GraphitiCycleResult(
            ingest_id=unit.ingest_id,
            source_id=unit.source_id,
            item_key=unit.item_key,
            outcome=execution.outcome.value,
            proposal_count=len(execution.produced.proposals),
            entity_count=len(entities),
            relation_count=len(relations),
            failure_code=execution.failure_code,
            temporal_basis=temporal.basis,
            reference_time=temporal.reference_time.to_text(),
            generation_id=GRAPHITI_GENERATION_ID,
            receipt_digest=str(payload.get("raw_output_digest") or ""),
            episode_uuid=str(payload.get("episode_uuid") or ""),
            entities=entities,
            relations=relations,
            proposals=(
                tuple(proposal_receipts)
                if isinstance(proposal_receipts, list)
                else ()
            ),
            passages=(
                tuple(passage_receipts)
                if isinstance(passage_receipts, list)
                else ()
            ),
            chat_invocations=tuple(invocations) if isinstance(invocations, list) else (),
            embedding_usage=(
                embedding_usage if isinstance(embedding_usage, dict) else None
            ),
            token_usage=token_usage if isinstance(token_usage, dict) else None,
            request_tokens=usage.request_tokens,
            response_tokens=usage.response_tokens,
            cost_microunits=usage.cost_microunits,
            usage_basis=str(usage_basis) if isinstance(usage_basis, str) else "UNOBSERVED",
            prompt_version=GRAPHITI_PROMPT_COMPONENT.component_version,
            attempt_number=unit.attempt_number,
            provider_attempt_number=(
                int(payload["provider_attempt_number"])
                if isinstance(payload.get("provider_attempt_number"), int)
                and not isinstance(payload.get("provider_attempt_number"), bool)
                else unit.attempt_number
            ),
            predecessor_episode_uuid=unit.predecessor_ingest_id,
            raw_receipt=payload,
        )


__all__ = [
    "EvaluationGraphitiRunner",
    "GraphitiCycleResult",
    "GraphitiModelUsageObserver",
    "GraphitiPort",
]
