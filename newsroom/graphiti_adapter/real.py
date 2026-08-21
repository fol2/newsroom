"""EVALUATION Graphiti workspace executor.

CLI transport and graphiti-core result mapping live in focused sibling modules.
This module owns only optional runtime loading, deterministic episode execution
and disposable local workspace orchestration.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.types import UtcTimestamp
from newsroom.control_plane.broker import (
    NEO4J_BOLT_HOST,
    NEO4J_BOLT_PORT,
    BrokerError,
    neo4j_community_password,
    openrouter_api_key,
)
from newsroom.extraction.models import ProducedExtraction, ProposalDraft
from newsroom.extraction.types import (
    ExtractionContractError,
    ExtractionFailureCode,
    ExtractionOutcome,
    ExtractionOutputValidation,
)
from newsroom.graphiti_adapter.cli_client import build_cli_llm_client
from newsroom.graphiti_adapter.contracts import GRAPHITI_PROMPT_COMPONENT
from newsroom.graphiti_adapter.embedding_meter import MeteredOpenAIEmbedder
from newsroom.graphiti_adapter.edge_guard import guard_extracted_edges
from newsroom.graphiti_adapter.evaluation_packet import (
    GRAPHITI_CHAT_FALLBACK,
    GRAPHITI_CHAT_MODEL,
    GRAPHITI_CLEANUP_TIMEOUT_MS,
    GRAPHITI_CORE_RELEASE,
    GRAPHITI_EMBEDDING_MODEL,
    GRAPHITI_EXTRACTION_INSTRUCTIONS,
    GRAPHITI_GENERATION_ID,
    GRAPHITI_WORKSPACE_GROUP,
    OPENROUTER_BASE_URL,
    OPENROUTER_EMBEDDING_SLUG,
)
from newsroom.graphiti_adapter.result_mapping import (
    entity_proposals,
    entity_receipts,
    episode_body,
    episode_uuid,
    is_source_registry_name,
    private_graph,
    produced_extraction,
    relation_proposals,
    relation_receipts,
)
from newsroom.graphiti_adapter.result_snapshot import restore_validated_snapshot
from newsroom.graphiti_adapter.recovery_vocabulary import (
    GraphitiRecoveryClassification,
)
from newsroom.graphiti_adapter.neo4j_guard import (
    GuardError,
    GuardMarker,
    GuardState,
    Neo4jMutationGuard,
)

from .models import (
    GraphitiAdapterExecution,
    GraphitiAttemptRequest,
    GraphitiWorkspaceDescriptor,
    adapter_outcome_for,
)
from .types import (
    GraphitiAdapterContractError,
    GraphitiCleanupReason,
    GraphitiExecutionProfile,
    GraphitiRuntimeMode,
)
from .workspace import DisposableProposalWorkspace

_GRAPHITI_CORE_VERSION = "0.29.3"
_NEO4J_USER = "neo4j"
_REASON_BY_OUTCOME = {
    "COMPLETE": GraphitiCleanupReason.NORMAL,
    "PARTIAL": GraphitiCleanupReason.PARTIAL,
    "TIMEOUT": GraphitiCleanupReason.TIMEOUT,
    "MALFORMED_OUTPUT": GraphitiCleanupReason.MALFORMED_OUTPUT,
    "PROVIDER_REJECTED": GraphitiCleanupReason.PROVIDER_REJECTED,
    "POLICY_BLOCKED": GraphitiCleanupReason.POLICY_BLOCKED,
    "FAILED": GraphitiCleanupReason.FAILED,
    "AMBIGUOUS_EFFECT": GraphitiCleanupReason.AMBIGUOUS_EFFECT,
}

# Compatibility names retained for callers while implementation lives in focused modules.
_is_source_registry_name = is_source_registry_name


def _no_embedding_usage() -> dict[str, object]:
    return {
        "requests": [],
        "request_count": 0,
        "embedding_tokens": 0,
        "cost_usd_microunits": 0,
        "usage_basis": "NO_EMBEDDING_CALL",
    }


@dataclass(slots=True)
class _EpisodeTelemetry:
    chat_invocations: list[dict[str, object]] = field(default_factory=list)
    embedding_usage: dict[str, object] = field(default_factory=_no_embedding_usage)
    predecessor_episode_uuid: str | None = None
    provider_attempt_number: int | None = None
    recovery_classification: GraphitiRecoveryClassification | None = None


ResultValidator = Callable[[Any, _EpisodeTelemetry], dict[str, object]]
SnapshotRestorer = Callable[[dict[str, object], _EpisodeTelemetry], None]


class AmbiguousEpisodeEffect(RuntimeError):
    """The deterministic episode exists without a completed ingest marker."""


def _load_graphiti() -> SimpleNamespace:
    try:
        from graphiti_core import Graphiti
        from graphiti_core.cross_encoder.client import CrossEncoderClient
        from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
        from graphiti_core.errors import NodeNotFoundError
        from graphiti_core.edges import EntityEdge, create_entity_edge_embeddings
        from graphiti_core.nodes import EpisodeType, EpisodicNode
        from graphiti_core.nodes import EntityNode
        from graphiti_core.utils.bulk_utils import resolve_edge_pointers
        from graphiti_core.utils.maintenance.edge_operations import extract_edges
    except ImportError as exc:
        raise GraphitiAdapterContractError(
            "graphiti extra (graphiti-core 0.29.3) is required for real Graphiti execution"
        ) from exc
    if importlib.metadata.version("graphiti-core") != _GRAPHITI_CORE_VERSION:
        raise GraphitiAdapterContractError(
            "real Graphiti requires graphiti-core 0.29.3"
        )

    class IdentityCrossEncoder(CrossEncoderClient):
        async def rank(
            self, query: str, passages: list[str]
        ) -> list[tuple[str, float]]:
            del query
            return [(item, 0.0) for item in passages]

    class GuardedGraphiti(Graphiti):
        """Pinned runtime with automatic edge invalidation disabled."""

        async def _extract_and_resolve_edges(
            self,
            episode: Any,
            extracted_nodes: list[Any],
            previous_episodes: list[Any],
            edge_type_map: dict[tuple[str, str], list[str]],
            group_id: str,
            edge_types: dict[str, type[Any]] | None,
            nodes: list[Any],
            uuid_map: dict[str, str],
            custom_extraction_instructions: str | None = None,
        ) -> tuple[list[Any], list[Any], list[Any]]:
            del nodes
            extracted = await extract_edges(
                self.clients,
                episode,
                extracted_nodes,
                previous_episodes,
                edge_type_map,
                group_id,
                edge_types,
                custom_extraction_instructions,
            )
            return await guard_extracted_edges(
                extracted_edges=extracted,
                uuid_map=uuid_map,
                embedder=self.clients.embedder,
                resolve_pointers=resolve_edge_pointers,
                create_embeddings=create_entity_edge_embeddings,
            )

    return SimpleNamespace(
        Graphiti=GuardedGraphiti,
        OpenAIEmbedder=OpenAIEmbedder,
        OpenAIEmbedderConfig=OpenAIEmbedderConfig,
        IdentityCrossEncoder=IdentityCrossEncoder,
        EpisodeType=EpisodeType,
        EpisodicNode=EpisodicNode,
        EntityEdge=EntityEdge,
        EntityNode=EntityNode,
        NodeNotFoundError=NodeNotFoundError,
        MutationGuard=Neo4jMutationGuard,
    )


def _same_time(left: object, right: datetime) -> bool:
    return isinstance(left, datetime) and left.astimezone(UTC) == right.astimezone(UTC)


async def _ensure_episode(
    *,
    graphiti: Any,
    runtime: SimpleNamespace,
    episode_id: str,
    name: str,
    body: str,
    reference_time: datetime,
) -> tuple[Any, str]:
    """Create the deterministic episode once, or validate the retained identity."""

    try:
        retained = await runtime.EpisodicNode.get_by_uuid(graphiti.driver, episode_id)
    except runtime.NodeNotFoundError:
        retained = runtime.EpisodicNode(
            uuid=episode_id,
            name=name,
            group_id=GRAPHITI_WORKSPACE_GROUP,
            labels=[],
            source=runtime.EpisodeType.text,
            source_description=GRAPHITI_WORKSPACE_GROUP,
            content=body,
            created_at=datetime.now(tz=UTC),
            valid_at=reference_time,
        )
        await retained.save(graphiti.driver)
        return retained, "CREATED"
    if (
        retained.name != name
        or retained.group_id != GRAPHITI_WORKSPACE_GROUP
        or retained.content != body
        or retained.source != runtime.EpisodeType.text
        or not _same_time(retained.valid_at, reference_time)
    ):
        raise GraphitiAdapterContractError(
            "deterministic Graphiti episode identity was reused for different input"
        )
    return retained, "RETAINED"


def _restore_marker_telemetry(
    telemetry: _EpisodeTelemetry, marker: GuardMarker
) -> None:
    telemetry.chat_invocations = [dict(item) for item in marker.chat_invocations]
    telemetry.embedding_usage = (
        dict(marker.embedding_usage)
        if marker.embedding_usage is not None
        else {
            "requests": [],
            "request_count": 0,
            "embedding_tokens": 0,
            "cost_usd_microunits": None,
            "usage_basis": "UNRECONCILED_PROVIDER_EFFECT",
        }
    )
    telemetry.provider_attempt_number = marker.attempt_number


async def _record_guard_telemetry(
    *, guard: Neo4jMutationGuard, llm_client: Any, embedder: MeteredOpenAIEmbedder,
    telemetry: _EpisodeTelemetry, attempt_number: int
) -> None:
    telemetry.chat_invocations = list(getattr(llm_client, "invocations", ()))
    telemetry.embedding_usage = embedder.receipt()
    telemetry.provider_attempt_number = attempt_number
    await guard.record_pending_telemetry(
        chat_invocations=telemetry.chat_invocations,
        embedding_usage=telemetry.embedding_usage,
    )


async def _add_episode(
    *,
    api_key: str,
    password: str,
    body: str,
    name: str,
    episode_id: str,
    reference_time: datetime,
    telemetry: _EpisodeTelemetry,
    attempt_number: int,
    validate_result: ResultValidator,
    restore_result: SnapshotRestorer,
) -> Any:
    os.environ.setdefault("GRAPHITI_TELEMETRY_ENABLED", "false")
    runtime = _load_graphiti()
    llm_client = build_cli_llm_client()
    delegate = runtime.OpenAIEmbedder(
        config=runtime.OpenAIEmbedderConfig(
            api_key=api_key,
            embedding_model=OPENROUTER_EMBEDDING_SLUG,
            base_url=OPENROUTER_BASE_URL,
        )
    )
    embedder = MeteredOpenAIEmbedder(delegate)
    graphiti = runtime.Graphiti(
        f"bolt://{NEO4J_BOLT_HOST}:{NEO4J_BOLT_PORT}",
        _NEO4J_USER,
        password,
        llm_client=llm_client,
        embedder=embedder,
        cross_encoder=runtime.IdentityCrossEncoder(),
    )
    input_digest = digest_bytes(
        canonical_json_bytes(
            {
                "episode_uuid": episode_id,
                "name": name,
                "body": body,
                "reference_time": reference_time.astimezone(UTC).isoformat(),
                "group_id": GRAPHITI_WORKSPACE_GROUP,
            }
        )
    )
    guard = runtime.MutationGuard(
        graphiti.driver,
        group_id=GRAPHITI_WORKSPACE_GROUP,
        episode_uuid=episode_id,
        attempt_number=attempt_number,
        input_digest=input_digest,
    )
    cancellation_cleanup_active = False
    try:
        marker = await guard.begin()
        if marker.state is GuardState.COMPLETE:
            raw = await guard.completed_raw()
            restore_result(raw, telemetry)
            return SimpleNamespace(episode=None, nodes=(), edges=())
        if marker.state is GuardState.RECOVERED_AMBIGUOUS:
            _restore_marker_telemetry(telemetry, marker)
            telemetry.recovery_classification = (
                GraphitiRecoveryClassification.RECOVERED_AMBIGUOUS
            )
            raise AmbiguousEpisodeEffect(
                "prior Graphiti attempt was rolled back after an ambiguous effect"
            )
        if marker.state in {GuardState.PENDING, GuardState.ROLLING_BACK}:
            _restore_marker_telemetry(telemetry, marker)
            telemetry.recovery_classification = (
                GraphitiRecoveryClassification.RECOVERED_PENDING_PROCESS_DEATH
            )
            await guard.rollback_pending(
                chat_invocations=telemetry.chat_invocations,
                embedding_usage=telemetry.embedding_usage,
                reason=telemetry.recovery_classification,
            )
            raise AmbiguousEpisodeEffect(
                "prior Graphiti process ended before durable completion"
            )

        _retained, state = await _ensure_episode(
            graphiti=graphiti,
            runtime=runtime,
            episode_id=episode_id,
            name=name,
            body=body,
            reference_time=reference_time,
        )
        if state != "CREATED":
            raise GraphitiAdapterContractError(
                "deterministic episode predates its durable mutation marker"
            )
        # Do not reuse ambient completed episodes: their source rights may have
        # changed since retention. Ordered chunks may use only their explicit,
        # currently permitted predecessor.
        previous_episode_ids: list[str] = []
        predecessor = telemetry.predecessor_episode_uuid
        if isinstance(predecessor, str) and predecessor:
            previous_episode_ids.insert(0, predecessor)
        try:
            result = await graphiti.add_episode(
                name=name,
                episode_body=body,
                source_description=GRAPHITI_WORKSPACE_GROUP,
                reference_time=reference_time,
                source=runtime.EpisodeType.text,
                group_id=GRAPHITI_WORKSPACE_GROUP,
                uuid=episode_id,
                previous_episode_uuids=list(dict.fromkeys(previous_episode_ids)),
                update_communities=False,
                custom_extraction_instructions=GRAPHITI_EXTRACTION_INSTRUCTIONS,
            )
            await _record_guard_telemetry(
                guard=guard,
                llm_client=llm_client,
                embedder=embedder,
                telemetry=telemetry,
                attempt_number=attempt_number,
            )
            await guard.restore_preexisting()
            raw = validate_result(result, telemetry)
            await guard.complete(raw)
        except asyncio.CancelledError:
            cancellation_cleanup_active = True

            async def cleanup_cancelled_attempt() -> None:
                await _record_guard_telemetry(
                    guard=guard,
                    llm_client=llm_client,
                    embedder=embedder,
                    telemetry=telemetry,
                    attempt_number=attempt_number,
                )
                await guard.rollback_pending(
                    chat_invocations=telemetry.chat_invocations,
                    embedding_usage=telemetry.embedding_usage,
                    reason="CANCELLED_OR_TIMED_OUT",
                )

            try:
                await asyncio.wait_for(
                    cleanup_cancelled_attempt(),
                    timeout=GRAPHITI_CLEANUP_TIMEOUT_MS / 1_000,
                )
            except asyncio.TimeoutError:
                pass
            raise
        except ExtractionContractError:
            await guard.rollback_pending(
                chat_invocations=telemetry.chat_invocations,
                embedding_usage=telemetry.embedding_usage,
                reason="OUTPUT_VALIDATION_FAILED",
            )
            raise
        except (GuardError, GraphitiAdapterContractError):
            raise
        except Exception as exc:
            await _record_guard_telemetry(
                guard=guard,
                llm_client=llm_client,
                embedder=embedder,
                telemetry=telemetry,
                attempt_number=attempt_number,
            )
            await guard.rollback_pending(
                chat_invocations=telemetry.chat_invocations,
                embedding_usage=telemetry.embedding_usage,
                reason=type(exc).__name__,
            )
            telemetry.recovery_classification = (
                GraphitiRecoveryClassification.ROLLED_BACK_AMBIGUOUS_EFFECT
            )
            raise AmbiguousEpisodeEffect(
                "Graphiti write failed after provider dispatch and was rolled back"
            ) from exc
        return result
    finally:
        if telemetry.provider_attempt_number is None:
            telemetry.chat_invocations = list(getattr(llm_client, "invocations", ()))
            telemetry.embedding_usage = embedder.receipt()
        try:
            await asyncio.wait_for(
                graphiti.close(),
                timeout=GRAPHITI_CLEANUP_TIMEOUT_MS / 1_000,
            )
        except asyncio.TimeoutError:
            if not cancellation_cleanup_active:
                raise GraphitiAdapterContractError(
                    "Graphiti connection cleanup timed out"
                ) from None


def _raw_receipt(
    attempt: GraphitiAttemptRequest,
    *,
    started_at: UtcTimestamp,
    telemetry: _EpisodeTelemetry,
    result: Any | None,
    proposals: tuple[ProposalDraft, ...],
) -> dict[str, object]:
    reference = attempt.reference_time
    if reference is None:
        raise GraphitiAdapterContractError("source reference_time is required")
    entities = () if result is None else entity_receipts(result)
    relations = () if result is None else relation_receipts(result)
    actual_episode = attempt.episode_uuid or str(attempt.attempt_id)
    if result is not None:
        returned_episode = episode_uuid(result)
        if returned_episode and returned_episode != actual_episode:
            raise GraphitiAdapterContractError(
                "graphiti-core returned a different deterministic episode identity"
            )
    proposal_values = {item.local_id: item.canonical_value() for item in proposals}
    entity_values = tuple(
        {
            **item,
            "episode_uuid": actual_episode,
            "passage_evidence": proposal_values.get(
                str(item.get("local_id")), {}
            ).get("evidence", []),
        }
        for item in entities
    )
    relation_values = tuple(
        {
            **item,
            "episode_uuid": actual_episode,
            "passage_evidence": proposal_values.get(
                str(item.get("local_id")), {}
            ).get("evidence", []),
            "proposal_status": (
                "PROPOSED"
                if str(item.get("local_id")) in proposal_values
                else "HELD_NO_EXACT_EVIDENCE"
            ),
        }
        for item in relations
    )
    raw: dict[str, object] = {
        "workspace_group": GRAPHITI_WORKSPACE_GROUP,
        "generation_id": attempt.generation_id or GRAPHITI_GENERATION_ID,
        "episode_uuid": actual_episode,
        "attempt_number": attempt.attempt_number,
        "provider_attempt_number": (
            telemetry.provider_attempt_number or attempt.attempt_number
        ),
        "predecessor_episode_uuid": attempt.predecessor_episode_uuid,
        "temporal_basis": attempt.temporal_basis,
        "reference_time": reference.to_text(),
        "ingest_started_at": started_at.to_text(),
        "passages": [item.canonical_value() for item in attempt.manifest.passages],
        "proposals": [item.canonical_value() for item in proposals],
        "entities": list(entity_values),
        "relations": list(relation_values),
        "entity_count": len(entity_values),
        "relation_count": len(relation_values),
        "proposal_count": len(proposals),
        "chat_invocations": list(telemetry.chat_invocations),
        "chat_invocation_count": len(telemetry.chat_invocations),
        "chat_subscription_not_debited": True,
        "embedding_usage": telemetry.embedding_usage,
        "usage_basis": str(
            telemetry.embedding_usage.get("usage_basis", "UNREPORTED")
        ),
        "framework": GRAPHITI_CORE_RELEASE,
        "chat": GRAPHITI_CHAT_MODEL,
        "chat_fallback": GRAPHITI_CHAT_FALLBACK,
        "embedding": GRAPHITI_EMBEDDING_MODEL,
        "prompt_version": GRAPHITI_PROMPT_COMPONENT.component_version,
    }
    if telemetry.recovery_classification is not None:
        raw["recovery_classification"] = telemetry.recovery_classification
    raw["raw_output_digest"] = digest_bytes(canonical_json_bytes(raw))
    return raw


class RealGraphitiAdapter:
    """Repository-owned real Graphiti adapter for EVALUATION only."""

    __slots__ = ("_clock", "_execution_deadline", "_monotonic")

    def __init__(
        self,
        *,
        clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
        monotonic: Callable[[], float] = time.monotonic,
        execution_deadline: datetime | None = None,
    ) -> None:
        self._clock = clock
        self._monotonic = monotonic
        self._execution_deadline = execution_deadline

    def execute(
        self,
        *,
        attempt: GraphitiAttemptRequest,
        workspace_root: object,
    ) -> GraphitiAdapterExecution:
        if not isinstance(attempt, GraphitiAttemptRequest):
            raise GraphitiAdapterContractError("real adapter needs a typed attempt")
        if not isinstance(workspace_root, Path):
            raise GraphitiAdapterContractError(
                "real adapter workspace root must be a pathlib Path"
            )
        configuration = attempt.configuration
        if configuration.runtime_mode is not GraphitiRuntimeMode.REAL_GRAPHITI:
            raise GraphitiAdapterContractError(
                "real adapter rejects a non-real configuration"
            )
        if configuration.execution_profile is not GraphitiExecutionProfile.EVALUATION:
            raise GraphitiAdapterContractError(
                "real Graphiti adapter is authorised only under EVALUATION"
            )
        configuration.require_execution_authorized()
        authority = configuration.real_runtime_authority
        if (
            authority is None
            or authority.framework_release != GRAPHITI_CORE_RELEASE
            or authority.model_release != GRAPHITI_CHAT_MODEL
            or authority.embedding_release != GRAPHITI_EMBEDDING_MODEL
            or configuration.workspace_policy.namespace_prefix
            != GRAPHITI_WORKSPACE_GROUP
        ):
            raise GraphitiAdapterContractError(
                "real Graphiti adapter requires the EVALUATION CLI packet pins"
            )

        started_at = self._clock()
        remaining_timeout_s = attempt.extraction_request.budget.timeout_ms / 1_000
        if self._execution_deadline is not None:
            if (
                self._execution_deadline.tzinfo is None
                or self._execution_deadline.utcoffset() is None
            ):
                raise GraphitiAdapterContractError(
                    "real adapter execution deadline must have an explicit offset"
                )
            remaining_timeout_s = min(
                remaining_timeout_s,
                max(
                    0.0,
                    (
                        self._execution_deadline.astimezone(UTC) - started_at.value
                    ).total_seconds(),
                ),
            )
        monotonic_deadline = self._monotonic() + remaining_timeout_s
        workspace = GraphitiWorkspaceDescriptor(
            workspace_id=attempt.workspace_id,
            configuration_id=configuration.configuration_id,
            policy_id=configuration.workspace_policy.policy_id,
            policy_digest=configuration.workspace_policy.canonical_digest,
            namespace=(
                f"{configuration.workspace_policy.namespace_prefix}-"
                f"{str(attempt.workspace_id)}"
            ),
            created_at=started_at,
        )
        private = DisposableProposalWorkspace(
            root=workspace_root,
            descriptor=workspace,
            policy=configuration.workspace_policy,
        )
        private.activate()
        try:
            produced = self._produce(
                attempt,
                started_at,
                execution_deadline=monotonic_deadline,
            )
            outcome = adapter_outcome_for(produced)
            raw = (
                produced.raw_output_value
                if isinstance(produced.raw_output_value, dict)
                else {}
            )
            relation_values = raw.get("relations", ())
            relations = (
                tuple(relation_values)
                if isinstance(relation_values, (list, tuple))
                else ()
            )
            nodes, private_relations = private_graph(produced, relations)
            private.write_private_graph(nodes=nodes, relations=private_relations)
            ended_at = self._clock()
            cleanup = private.cleanup(
                receipt_id=attempt.cleanup_receipt_id,
                reason=_REASON_BY_OUTCOME[outcome.value],
                recorded_at=ended_at,
            )
        except Exception:
            if private.exists:
                private.cleanup(
                    receipt_id=attempt.cleanup_receipt_id,
                    reason=GraphitiCleanupReason.FAILED,
                    recorded_at=self._clock(),
                )
            raise

        return GraphitiAdapterExecution(
            attempt=attempt,
            outcome=outcome,
            failure_code=produced.failure_code.value,
            produced=produced,
            workspace=workspace,
            cleanup_receipt=cleanup,
            started_at=started_at,
            ended_at=ended_at,
        )

    def _produce(
        self,
        attempt: GraphitiAttemptRequest,
        started_at: UtcTimestamp,
        *,
        execution_deadline: float | None = None,
    ) -> ProducedExtraction:
        timeout_s = attempt.extraction_request.budget.timeout_ms / 1000
        if execution_deadline is None:
            execution_deadline = self._monotonic() + timeout_s
        if attempt.reference_time is None:
            raise GraphitiAdapterContractError(
                "source reference_time is required; started_at must not replace it"
            )
        reference = attempt.reference_time
        deterministic_episode_id = attempt.episode_uuid or str(attempt.attempt_id)
        telemetry = _EpisodeTelemetry(
            predecessor_episode_uuid=attempt.predecessor_episode_uuid
        )
        validated: dict[str, ProducedExtraction] = {}

        def timeout_result() -> ProducedExtraction:
            raw = _raw_receipt(
                attempt,
                started_at=started_at,
                telemetry=telemetry,
                result=None,
                proposals=(),
            )
            return produced_extraction(
                attempt,
                outcome=ExtractionOutcome.RETRYABLE_FAILURE,
                failure_code=ExtractionFailureCode.EXECUTION_TIMEOUT,
                validation=None,
                raw=None,
                proposals=(),
                embedding_usage=telemetry.embedding_usage,
                attempt_receipt=raw,
            )

        def validate_result(
            result: Any, current_telemetry: _EpisodeTelemetry
        ) -> dict[str, object]:
            proposals = tuple(
                sorted(
                    (
                        *entity_proposals(result, attempt),
                        *relation_proposals(result, attempt),
                    ),
                    key=lambda item: item.local_id,
                )
            )
            raw = _raw_receipt(
                attempt,
                started_at=started_at,
                telemetry=current_telemetry,
                result=result,
                proposals=proposals,
            )
            produced = produced_extraction(
                attempt,
                outcome=ExtractionOutcome.SUCCESS,
                failure_code=ExtractionFailureCode.NONE,
                validation=ExtractionOutputValidation.VALID,
                raw=raw,
                proposals=proposals,
                embedding_usage=current_telemetry.embedding_usage,
            )
            try:
                produced.usage.require_within(attempt.extraction_request.budget)
            except ExtractionContractError:
                diagnostic = _raw_receipt(
                    attempt,
                    started_at=started_at,
                    telemetry=current_telemetry,
                    result=None,
                    proposals=(),
                )
                diagnostic.pop("raw_output_digest", None)
                diagnostic["budget_status"] = "EXCEEDED"
                diagnostic["raw_output_digest"] = digest_bytes(
                    canonical_json_bytes(diagnostic)
                )
                validated["produced"] = produced_extraction(
                    attempt,
                    outcome=ExtractionOutcome.INVALID_OUTPUT,
                    failure_code=ExtractionFailureCode.OUTPUT_SCHEMA_INVALID,
                    validation=ExtractionOutputValidation.INVALID,
                    raw=diagnostic,
                    proposals=(),
                    embedding_usage=current_telemetry.embedding_usage,
                )
                raise
            validated["produced"] = produced
            return raw

        def restore_result(
            raw: dict[str, object], current_telemetry: _EpisodeTelemetry
        ) -> None:
            restoration = restore_validated_snapshot(raw=raw, attempt=attempt)
            current_telemetry.chat_invocations = list(
                restoration.chat_invocations
            )
            current_telemetry.embedding_usage = dict(
                restoration.embedding_usage
            )
            current_telemetry.provider_attempt_number = (
                restoration.provider_attempt_number
            )
            current_telemetry.recovery_classification = (
                restoration.recovery_classification
            )
            validated["produced"] = restoration.produced

        try:
            _load_graphiti()
            api_key = openrouter_api_key()
            password = neo4j_community_password()
        except (BrokerError, GraphitiAdapterContractError) as exc:
            raw = _raw_receipt(
                attempt,
                started_at=started_at,
                telemetry=telemetry,
                result=None,
                proposals=(),
            )
            raw.pop("raw_output_digest", None)
            raw["dispatch_state"] = "NOT_DISPATCHED"
            raw["setup_failure"] = type(exc).__name__
            raw["raw_output_digest"] = digest_bytes(canonical_json_bytes(raw))
            return produced_extraction(
                attempt,
                outcome=ExtractionOutcome.RETRYABLE_FAILURE,
                failure_code=ExtractionFailureCode.PRODUCER_INTERNAL_ERROR,
                validation=None,
                raw=None,
                proposals=(),
                embedding_usage=telemetry.embedding_usage,
                attempt_receipt=raw,
            )
        remaining_timeout_s = execution_deadline - self._monotonic()
        if remaining_timeout_s <= 0:
            return timeout_result()
        try:
            result = asyncio.run(
                asyncio.wait_for(
                    _add_episode(
                        api_key=api_key,
                        password=password,
                        body=episode_body(attempt),
                        name=deterministic_episode_id,
                        episode_id=deterministic_episode_id,
                        reference_time=reference.value,
                        telemetry=telemetry,
                        attempt_number=attempt.attempt_number,
                        validate_result=validate_result,
                        restore_result=restore_result,
                    ),
                    timeout=remaining_timeout_s,
                )
            )
        except asyncio.TimeoutError:
            return timeout_result()
        except (BrokerError, GraphitiAdapterContractError):
            raise
        except ExtractionContractError:
            produced = validated.get("produced")
            if produced is None:
                raise
            return produced
        except AmbiguousEpisodeEffect:
            raw = _raw_receipt(
                attempt,
                started_at=started_at,
                telemetry=telemetry,
                result=None,
                proposals=(),
            )
            return produced_extraction(
                attempt,
                outcome=ExtractionOutcome.RETRYABLE_FAILURE,
                failure_code=ExtractionFailureCode.AMBIGUOUS_EFFECT,
                validation=None,
                raw=None,
                proposals=(),
                embedding_usage=telemetry.embedding_usage,
                attempt_receipt=raw,
            )
        except Exception:
            raw = _raw_receipt(
                attempt,
                started_at=started_at,
                telemetry=telemetry,
                result=None,
                proposals=(),
            )
            return produced_extraction(
                attempt,
                outcome=ExtractionOutcome.RETRYABLE_FAILURE,
                failure_code=ExtractionFailureCode.PRODUCER_INTERNAL_ERROR,
                validation=None,
                raw=None,
                proposals=(),
                embedding_usage=telemetry.embedding_usage,
                attempt_receipt=raw,
            )

        produced = validated.get("produced")
        if produced is None:
            raise GraphitiAdapterContractError(
                "Graphiti result was not validated before completion"
            )
        return produced


__all__ = ["RealGraphitiAdapter"]
