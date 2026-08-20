"""EVALUATION Graphiti workspace executor.

CLI transport and graphiti-core result mapping live in focused sibling modules.
This module owns only optional runtime loading, deterministic episode execution
and disposable local workspace orchestration.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import os
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
    ExtractionFailureCode,
    ExtractionOutcome,
    ExtractionOutputValidation,
)
from newsroom.graphiti_adapter.cli_client import build_cli_llm_client
from newsroom.graphiti_adapter.contracts import GRAPHITI_PROMPT_COMPONENT
from newsroom.graphiti_adapter.embedding_meter import MeteredOpenAIEmbedder
from newsroom.graphiti_adapter.evaluation_packet import (
    GRAPHITI_CHAT_MODEL,
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


@dataclass(slots=True)
class _EpisodeTelemetry:
    chat_invocations: list[dict[str, object]] = field(default_factory=list)
    embedding_usage: dict[str, object] = field(default_factory=dict)


def _load_graphiti() -> SimpleNamespace:
    try:
        from graphiti_core import Graphiti
        from graphiti_core.cross_encoder.client import CrossEncoderClient
        from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
        from graphiti_core.errors import NodeNotFoundError
        from graphiti_core.nodes import EpisodeType, EpisodicNode
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

    return SimpleNamespace(
        Graphiti=Graphiti,
        OpenAIEmbedder=OpenAIEmbedder,
        OpenAIEmbedderConfig=OpenAIEmbedderConfig,
        IdentityCrossEncoder=IdentityCrossEncoder,
        EpisodeType=EpisodeType,
        EpisodicNode=EpisodicNode,
        NodeNotFoundError=NodeNotFoundError,
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
) -> None:
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
        return
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


async def _add_episode(
    *,
    api_key: str,
    password: str,
    body: str,
    name: str,
    episode_id: str,
    reference_time: datetime,
    telemetry: _EpisodeTelemetry,
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
    try:
        previous = await graphiti.retrieve_episodes(
            reference_time,
            last_n=10,
            group_ids=[GRAPHITI_WORKSPACE_GROUP],
            source=runtime.EpisodeType.text,
        )
        previous_episode_ids = [
            str(item.uuid)
            for item in previous
            if str(getattr(item, "uuid", "")) != episode_id
        ]
        await _ensure_episode(
            graphiti=graphiti,
            runtime=runtime,
            episode_id=episode_id,
            name=name,
            body=body,
            reference_time=reference_time,
        )
        return await graphiti.add_episode(
            name=name,
            episode_body=body,
            source_description=GRAPHITI_WORKSPACE_GROUP,
            reference_time=reference_time,
            source=runtime.EpisodeType.text,
            group_id=GRAPHITI_WORKSPACE_GROUP,
            uuid=episode_id,
            previous_episode_uuids=previous_episode_ids,
            update_communities=False,
            custom_extraction_instructions=GRAPHITI_EXTRACTION_INSTRUCTIONS,
        )
    finally:
        telemetry.chat_invocations = list(getattr(llm_client, "invocations", ()))
        telemetry.embedding_usage = embedder.receipt()
        await graphiti.close()


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
    raw: dict[str, object] = {
        "workspace_group": GRAPHITI_WORKSPACE_GROUP,
        "generation_id": attempt.generation_id or GRAPHITI_GENERATION_ID,
        "episode_uuid": actual_episode,
        "temporal_basis": attempt.temporal_basis,
        "reference_time": reference.to_text(),
        "ingest_started_at": started_at.to_text(),
        "passages": [item.canonical_value() for item in attempt.manifest.passages],
        "proposals": [item.canonical_value() for item in proposals],
        "entities": list(entities),
        "relations": list(relations),
        "entity_count": len(entities),
        "relation_count": len(relations),
        "proposal_count": len(proposals),
        "chat_invocations": list(telemetry.chat_invocations),
        "chat_invocation_count": len(telemetry.chat_invocations),
        "chat_subscription_not_debited": True,
        "embedding_usage": telemetry.embedding_usage,
        "usage_basis": str(
            telemetry.embedding_usage.get("usage_basis", "UNREPORTED")
        ),
        "prompt_version": GRAPHITI_PROMPT_COMPONENT.component_version,
    }
    raw["raw_output_digest"] = digest_bytes(canonical_json_bytes(raw))
    return raw


class RealGraphitiAdapter:
    """Repository-owned real Graphiti adapter for EVALUATION only."""

    __slots__ = ("_clock",)

    def __init__(
        self,
        *,
        clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
    ) -> None:
        self._clock = clock

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
            produced = self._produce(attempt, started_at)
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
    ) -> ProducedExtraction:
        timeout_s = attempt.extraction_request.budget.timeout_ms / 1000
        if attempt.reference_time is None:
            raise GraphitiAdapterContractError(
                "source reference_time is required; started_at must not replace it"
            )
        reference = attempt.reference_time
        deterministic_episode_id = attempt.episode_uuid or str(attempt.attempt_id)
        telemetry = _EpisodeTelemetry()
        try:
            _load_graphiti()
            api_key = openrouter_api_key()
            password = neo4j_community_password()
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
                    ),
                    timeout=timeout_s,
                )
            )
        except asyncio.TimeoutError:
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
                raw=raw,
                proposals=(),
                embedding_usage=telemetry.embedding_usage,
            )
        except (BrokerError, GraphitiAdapterContractError):
            raise
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
                raw=raw,
                proposals=(),
                embedding_usage=telemetry.embedding_usage,
            )

        proposals = tuple(
            sorted(
                (*entity_proposals(result, attempt), *relation_proposals(result, attempt)),
                key=lambda item: item.local_id,
            )
        )
        raw = _raw_receipt(
            attempt,
            started_at=started_at,
            telemetry=telemetry,
            result=result,
            proposals=proposals,
        )
        relations = raw["relations"]
        if not proposals and not relations:
            return produced_extraction(
                attempt,
                outcome=ExtractionOutcome.INVALID_OUTPUT,
                failure_code=ExtractionFailureCode.OUTPUT_SCHEMA_INVALID,
                validation=ExtractionOutputValidation.INVALID,
                raw=raw,
                proposals=(),
                embedding_usage=telemetry.embedding_usage,
            )
        return produced_extraction(
            attempt,
            outcome=ExtractionOutcome.SUCCESS,
            failure_code=ExtractionFailureCode.NONE,
            validation=ExtractionOutputValidation.VALID,
            raw=raw,
            proposals=proposals,
            embedding_usage=telemetry.embedding_usage,
        )


__all__ = ["RealGraphitiAdapter"]
