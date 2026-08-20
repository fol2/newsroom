"""EVALUATION Graphiti executor. Proposal-only; does not write the ledger.

graphiti-core is an optional extra. Construction and authorization checks do not
import it, fetch Keychain secrets, or call OpenRouter. Completeness of this
module is not REAL_GRAPHITI_RUNTIME_ENABLED.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
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
    EvidenceRange,
    ExtractionFailureCode,
    ExtractionOutcome,
    ExtractionOutputValidation,
    ExtractionProposalKind,
    ExtractionUsage,
)
from newsroom.graphiti_adapter.evaluation_packet import (
    GRAPHITI_CHAT_MODEL,
    GRAPHITI_CORE_RELEASE,
    GRAPHITI_EMBEDDING_MODEL,
    GRAPHITI_WORKSPACE_GROUP,
    OPENROUTER_BASE_URL,
    OPENROUTER_CHAT_SLUG,
    OPENROUTER_EMBEDDING_SLUG,
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


def _load_graphiti() -> SimpleNamespace:
    try:
        import importlib.metadata

        from graphiti_core import Graphiti
        from graphiti_core.cross_encoder.openai_reranker_client import (
            OpenAIRerankerClient,
        )
        from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
        from graphiti_core.llm_client.config import LLMConfig
        from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
        from graphiti_core.nodes import EpisodeType
    except ImportError as exc:
        raise GraphitiAdapterContractError(
            "graphiti extra (graphiti-core 0.29.3) is required for real Graphiti execution"
        ) from exc
    installed = importlib.metadata.version("graphiti-core")
    if installed != _GRAPHITI_CORE_VERSION:
        raise GraphitiAdapterContractError(
            "real Graphiti requires graphiti-core 0.29.3"
        )
    return SimpleNamespace(
        Graphiti=Graphiti,
        LLMConfig=LLMConfig,
        OpenAIGenericClient=OpenAIGenericClient,
        OpenAIEmbedder=OpenAIEmbedder,
        OpenAIEmbedderConfig=OpenAIEmbedderConfig,
        OpenAIRerankerClient=OpenAIRerankerClient,
        EpisodeType=EpisodeType,
    )


def _episode_body(attempt: GraphitiAttemptRequest) -> str:
    return "\n\n".join(
        passage.require_text()
        for passage in attempt.extraction_request.input_binding.passages
    )


def _evidence_for(name: str, attempt: GraphitiAttemptRequest) -> EvidenceRange | None:
    needle = name.encode("utf-8")
    if not needle:
        return None
    for passage in attempt.extraction_request.input_binding.passages:
        data = passage.require_text().encode("utf-8")
        start = data.find(needle)
        if start < 0:
            continue
        end = start + len(needle)
        return EvidenceRange(
            passage_id=passage.passage_id,
            start_byte=start,
            end_byte=end,
            evidence_text_digest=digest_bytes(data[start:end]),
        )
    return None


def _proposals_from_result(
    result: Any, attempt: GraphitiAttemptRequest
) -> tuple[ProposalDraft, ...]:
    drafts: list[ProposalDraft] = []
    nodes = getattr(result, "nodes", ()) or ()
    for index, node in enumerate(nodes, start=1):
        raw_name = getattr(node, "name", None)
        if not isinstance(raw_name, str):
            continue
        name = " ".join(raw_name.split())
        if not name:
            continue
        evidence = _evidence_for(name, attempt)
        if evidence is None:
            continue
        drafts.append(
            ProposalDraft(
                local_id=f"entity.{index:04d}",
                kind=ExtractionProposalKind.ENTITY_MENTION,
                subject_placeholder=name,
                object_placeholder=None,
                predicate_hint=None,
                confidence_basis_points=None,
                uncertainty_codes=(),
                rationale_codes=("GRAPHITI_EVALUATION_SPAN",),
                evidence=(evidence,),
            )
        )
    return tuple(sorted(drafts, key=lambda item: item.local_id))


def _usage(
    attempt: GraphitiAttemptRequest,
    raw: dict[str, object] | None,
    proposals: tuple[ProposalDraft, ...],
) -> ExtractionUsage:
    output_bytes = 0 if raw is None else len(canonical_json_bytes(raw))
    return ExtractionUsage(
        elapsed_ms=0,
        input_bytes=attempt.extraction_request.input_binding.input_bytes,
        output_bytes=output_bytes,
        proposal_count=len(proposals),
        evidence_range_count=sum(len(item.evidence) for item in proposals),
        request_tokens=0,
        response_tokens=0,
        cost_microunits=0,
    )


def _produced(
    attempt: GraphitiAttemptRequest,
    *,
    outcome: ExtractionOutcome,
    failure_code: ExtractionFailureCode,
    validation: ExtractionOutputValidation | None,
    raw: dict[str, object] | None,
    proposals: tuple[ProposalDraft, ...],
) -> ProducedExtraction:
    return ProducedExtraction(
        outcome=outcome,
        failure_code=failure_code,
        validation=validation,
        raw_output_value=raw,
        proposals=proposals,
        usage=_usage(attempt, raw, proposals),
    )


def _private_graph(
    produced: ProducedExtraction,
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    nodes = tuple(
        {
            "private_node_id": f"private-node-{index:04d}",
            "proposal_local_id": proposal.local_id,
            "proposal_kind": proposal.kind.value,
            "proposal_digest": proposal.digest,
        }
        for index, proposal in enumerate(produced.proposals, start=1)
    )
    relations: tuple[dict[str, object], ...] = ()
    return nodes, relations


async def _add_episode(
    *,
    api_key: str,
    password: str,
    body: str,
    name: str,
    reference_time: datetime,
) -> Any:
    os.environ.setdefault("GRAPHITI_TELEMETRY_ENABLED", "false")
    runtime = _load_graphiti()
    llm_config = runtime.LLMConfig(
        api_key=api_key,
        model=OPENROUTER_CHAT_SLUG,
        small_model=OPENROUTER_CHAT_SLUG,
        base_url=OPENROUTER_BASE_URL,
    )
    # OpenRouter's gpt-5-mini rejects Graphiti's native json_schema (additionalProperties).
    llm_client = runtime.OpenAIGenericClient(
        config=llm_config,
        structured_output_mode="json_object",
    )
    graphiti = runtime.Graphiti(
        f"bolt://{NEO4J_BOLT_HOST}:{NEO4J_BOLT_PORT}",
        _NEO4J_USER,
        password,
        llm_client=llm_client,
        embedder=runtime.OpenAIEmbedder(
            config=runtime.OpenAIEmbedderConfig(
                api_key=api_key,
                embedding_model=OPENROUTER_EMBEDDING_SLUG,
                base_url=OPENROUTER_BASE_URL,
            )
        ),
        cross_encoder=runtime.OpenAIRerankerClient(config=llm_config),
    )
    try:
        return await graphiti.add_episode(
            name=name,
            episode_body=body,
            source_description=GRAPHITI_WORKSPACE_GROUP,
            reference_time=reference_time,
            source=runtime.EpisodeType.text,
            group_id=GRAPHITI_WORKSPACE_GROUP,
            update_communities=False,
        )
    finally:
        await graphiti.close()


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
                "real Graphiti adapter requires the EVALUATION OpenRouter packet pins"
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
            nodes, relations = _private_graph(produced)
            private.write_private_graph(nodes=nodes, relations=relations)
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
        try:
            _load_graphiti()
            api_key = openrouter_api_key()
            password = neo4j_community_password()
            result = asyncio.run(
                asyncio.wait_for(
                    _add_episode(
                        api_key=api_key,
                        password=password,
                        body=_episode_body(attempt),
                        name=str(attempt.attempt_id),
                        reference_time=started_at.value,
                    ),
                    timeout=timeout_s,
                )
            )
        except asyncio.TimeoutError:
            return _produced(
                attempt,
                outcome=ExtractionOutcome.RETRYABLE_FAILURE,
                failure_code=ExtractionFailureCode.EXECUTION_TIMEOUT,
                validation=None,
                raw=None,
                proposals=(),
            )
        except (BrokerError, GraphitiAdapterContractError):
            raise
        except Exception as exc:
            return _produced(
                attempt,
                outcome=ExtractionOutcome.RETRYABLE_FAILURE,
                failure_code=ExtractionFailureCode.PRODUCER_INTERNAL_ERROR,
                validation=None,
                raw={"error_type": type(exc).__name__},
                proposals=(),
            )

        proposals = _proposals_from_result(result, attempt)
        raw: dict[str, object] = {
            "workspace_group": GRAPHITI_WORKSPACE_GROUP,
            "entity_count": len(getattr(result, "nodes", ()) or ()),
            "relation_count": len(getattr(result, "edges", ()) or ()),
            "proposal_count": len(proposals),
        }
        if not proposals:
            return _produced(
                attempt,
                outcome=ExtractionOutcome.INVALID_OUTPUT,
                failure_code=ExtractionFailureCode.OUTPUT_SCHEMA_INVALID,
                validation=ExtractionOutputValidation.INVALID,
                raw=raw,
                proposals=(),
            )
        return _produced(
            attempt,
            outcome=ExtractionOutcome.SUCCESS,
            failure_code=ExtractionFailureCode.NONE,
            validation=ExtractionOutputValidation.VALID,
            raw=raw,
            proposals=proposals,
        )


__all__ = ["RealGraphitiAdapter"]
