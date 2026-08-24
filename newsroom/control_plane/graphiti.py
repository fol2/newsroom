"""EVALUATION Graphiti runner for corpus ingest, decoupled from CONT writes."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol, runtime_checkable

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
)
from newsroom.control_plane.corpus import CorpusIngestUnit
from newsroom.control_plane.model_usage import (
    InvocationAllocation,
    InvocationEfficiencyPolicy,
    InvocationTerminal,
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


GRAPHITI_CONTEXT_IDENTITY = "graphiti-combined-temporal-hermetic-v1"
GRAPHITI_CHAT_PRIMARY_ROUTE = "GRAPHITI_CHAT_PRIMARY"
GRAPHITI_CHAT_FALLBACK_ROUTE = "GRAPHITI_CHAT_FALLBACK"
GRAPHITI_EMBEDDING_ROUTE = "GRAPHITI_EMBEDDING"


class GraphitiModelUsageObserver:
    def __init__(
        self,
        *,
        service: ModelUsageService,
        envelope: WorkEnvelope,
        clock: Callable[[], datetime],
    ) -> None:
        self._service = service
        self._envelope = envelope
        self._clock = clock
        self._ordinal = 0
        self._allocations: list[InvocationAllocation] = []
        self._dispatch_at: dict[str, datetime] = {}
        self._policies: dict[str, InvocationEfficiencyPolicy] = {}
        self._primary_by_prompt: dict[str, str] = {}

    def _allocate(
        self,
        *,
        workload: WorkloadClass,
        provider: str,
        route: str,
        model: str,
        reasoning: str,
        prompt_bytes: bytes,
        output_schema_digest: str,
        parent_invocation_id: str | None = None,
    ) -> InvocationAllocation:
        policy = self._service.qualified_policy(
            workload_class=workload,
            provider=provider,
            route=route,
            model=model,
            reasoning=reasoning,
        )
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
        prompt_digest = digest_bytes(prompt_bytes)
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
            request_digest=digest_canonical(
                {
                    "provider": provider,
                    "route": route,
                    "model": model,
                    "prompt_digest": prompt_digest,
                    "output_schema_digest": output_schema_digest,
                }
            ),
            output_schema_digest=output_schema_digest,
            max_output_tokens=policy.max_output_tokens,
            context_manifest_digest=digest_canonical(
                {
                    "context_identity": GRAPHITI_CONTEXT_IDENTITY,
                    "ingest_id": self._envelope.ingest_id,
                    "graphiti_attempt_id": self._envelope.graphiti_attempt_id,
                    "prompt_digest": prompt_digest,
                }
            ),
            context_identity=GRAPHITI_CONTEXT_IDENTITY,
            one_turn=True,
            exact_input=True,
            skills_enabled=False,
            tools_enabled=False,
            mcp_enabled=False,
            prior_message_count=0,
            allocated_at=self._clock().astimezone(UTC),
            parent_invocation_id=parent_invocation_id,
        )
        self._service.allocate(allocation)
        self._allocations.append(allocation)
        self._policies[allocation.invocation_id] = policy
        dispatch_at = self._clock().astimezone(UTC)
        self._service.observe_transport(
            invocation_id=allocation.invocation_id,
            observed_at=dispatch_at,
            state="DISPATCH_STARTED",
            evidence_digest=digest_canonical(
                {
                    "invocation_id": allocation.invocation_id,
                    "provider": provider,
                    "route": route,
                    "request_digest": allocation.request_digest,
                }
            ),
        )
        self._dispatch_at[allocation.invocation_id] = dispatch_at
        return allocation

    def link_provider_attempts(
        self, *, provider_attempt_number: int, linked_at: datetime
    ) -> None:
        if provider_attempt_number <= 0:
            raise ValueError("Graphiti provider attempt number must be positive")
        attempt_id = self._envelope.graphiti_attempt_id
        if attempt_id is None:
            raise ValueError("Graphiti work envelope lacks an attempt identity")
        for allocation in self._allocations:
            self._service.link_provider_attempt(
                invocation_id=allocation.invocation_id,
                provider_attempt_id=(
                    f"{attempt_id}:provider-attempt:{provider_attempt_number}:"
                    f"leaf:{allocation.leaf_ordinal}"
                ),
                linked_at=linked_at,
            )

    def before_cli_invocation(
        self, *, provider: str, model: str, prompt: str, schema: str | None
    ) -> object:
        prompt_digest = digest_bytes(prompt.encode("utf-8"))
        primary = provider == "cursor-agent-cli"
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
            output_schema_digest=digest_canonical(
                {"response_schema": schema or "UNSTRUCTURED"}
            ),
            parent_invocation_id=(
                None if primary else self._primary_by_prompt.get(prompt_digest)
            ),
        )
        if primary:
            self._primary_by_prompt[prompt_digest] = allocation.invocation_id
        return allocation

    def after_cli_invocation(
        self,
        token: object,
        *,
        outcome: str,
        usage: dict[str, object],
    ) -> None:
        if not isinstance(token, InvocationAllocation):
            raise TypeError("Graphiti chat usage token is not an allocation")
        self._complete(
            token,
            outcome=outcome,
            usage=usage,
            od_011_reference=None,
            subscription_not_debited=True,
        )

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
            output_schema_digest=digest_canonical(
                {"schema": "embedding-vector", "model": model}
            ),
        )

    def after_embedding_invocation(
        self,
        token: object,
        *,
        outcome: str,
        usage: dict[str, object],
    ) -> None:
        if not isinstance(token, InvocationAllocation):
            raise TypeError("Graphiti embedding usage token is not an allocation")
        self._complete(
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
    ) -> None:
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
                    total_tokens=policy.max_total_tokens,
                    provenance="BOUNDED_ESTIMATE",
                )
            )
        )
        telemetry = usage.get("provider_telemetry", usage)
        telemetry_mapping = telemetry if isinstance(telemetry, dict) else usage
        completed_at = self._clock().astimezone(UTC)
        self._service.complete(
            InvocationTerminal.create(
                invocation_id=allocation.invocation_id,
                outcome=outcome,
                failure_class=(
                    None
                    if reported
                    else (
                        "EXECUTABLE_NOT_FOUND"
                        if no_provider_call
                        else "MISSING_PROVIDER_TELEMETRY"
                    )
                ),
                usage_status=(
                    UsageStatus.REPORTED
                    if reported or no_provider_call
                    else UsageStatus.ESTIMATED
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
                    if not reported and not no_provider_call
                    else None
                ),
                estimate_calculation=(
                    f"qualified_policy.max_total_tokens={policy.max_total_tokens}"
                    if not reported and not no_provider_call
                    else None
                ),
            ),
            provider_telemetry=telemetry_mapping if reported else None,
        )


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
        model_usage.open_envelope(envelope)
        observer = GraphitiModelUsageObserver(
            service=model_usage,
            envelope=envelope,
            clock=self._clock,
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
