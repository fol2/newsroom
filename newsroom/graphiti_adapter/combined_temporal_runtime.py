"""Async EVALUATION runtime for combined-temporal extraction."""

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any, Protocol

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_canonical,
)
from newsroom.authority.types import UtcTimestamp
from newsroom.graphiti_adapter.combined_temporal_contract import (
    CONTRACT_NAME,
    SCHEMA,
    SourceRevisionInput,
    _candidate_prompt_digest,
    build_compact_prompt,
)
from newsroom.graphiti_adapter.combined_temporal_extraction import (
    CombinedTemporalLeaf,
    CombinedTemporalOutcome,
    CombinedTemporalTransportResult,
    _leaf,
    _leaf_from_completed,
    _proposal_receipt,
    _validate_and_expand,
)
from newsroom.graphiti_adapter.combined_temporal_pipeline import (
    CombinedTemporalPipelineError,
    ExistingGraphitiPipeline,
)
from newsroom.graphiti_adapter.combined_temporal_response import raw_digest
from newsroom.graphiti_adapter.combined_temporal_types import (
    CombinedTemporalError,
    CombinedTemporalFailureCode,
)
from newsroom.graphiti_adapter.identity import configuration_digest
from newsroom.graphiti_adapter.deterministic_sidecar import (
    DeterministicSidecarInput,
    RelationTriple,
    SemanticRelationProposal,
    collapse_sidecar_duplicates,
    project_deterministic_sidecar,
)
from newsroom.graphiti_adapter.deterministic_summary import (
    AdmittedSummaryAssertion,
    build_deterministic_summary,
)
from newsroom.graphiti_adapter.temporal_vocabulary import TEMPORAL_POLICY_VERSION
from newsroom.graphiti_adapter.local_entity_resolution import (
    CanonicalEntityCandidate,
    EntityMentionInput,
    LocalEntityResolutionOutcome,
    resolve_entity_locally,
)


class AsyncCombinedTemporalTransport(Protocol):
    async def generate_response(
        self,
        *,
        prompt: str,
        schema: Mapping[str, Any],
        response_model: str,
        max_tokens: int,
    ) -> CombinedTemporalTransportResult: ...


class NewsroomCombinedTemporalExtractionV1:
    @classmethod
    def model_json_schema(cls) -> dict[str, Any]:
        return SCHEMA


class CliCombinedTemporalTransport:
    """Forward the compact object through #769's observed CLI client."""

    def __init__(self, llm_client: Any) -> None:
        self._llm_client = llm_client

    async def generate_response(
        self,
        *,
        prompt: str,
        schema: Mapping[str, Any],
        response_model: str,
        max_tokens: int,
    ) -> CombinedTemporalTransportResult:
        if response_model != CONTRACT_NAME or dict(schema) != SCHEMA:
            raise ValueError("combined-temporal runtime request identity differs")
        raw = await self._llm_client._generate_response(
            [SimpleNamespace(role="user", content=prompt)],
            response_model=NewsroomCombinedTemporalExtractionV1,
            max_tokens=max_tokens,
        )
        invocations = list(getattr(self._llm_client, "invocations", ()))
        latest = invocations[-1] if invocations else {}
        usage = latest.get("usage")
        return CombinedTemporalTransportResult(
            raw=raw,
            framework_version="graphiti-core-0.29.3",
            model_version=(
                str(latest["model"]) if latest.get("model") is not None else None
            ),
            token_usage=(
                dict(usage) if isinstance(usage, Mapping) else {"basis": "UNMEASURED"}
            ),
            provider_cost=(
                usage.get("cost_usd_microunits")
                if isinstance(usage, Mapping)
                else None
            ),
        )


def resolve_nodes_locally(
    nodes: list[Any],
    existing_nodes: tuple[Any, ...],
    *,
    source_id: str,
    similarities_ppm: Mapping[tuple[str, str], int] | None = None,
) -> tuple[list[Any], dict[str, str], list[tuple[Any, Any]]]:
    """Apply the #748 common-case policy without a chat dedupe leaf."""

    similarities = similarities_ppm or {}
    resolved_nodes: list[Any] = []
    uuid_map: dict[str, str] = {}
    for node in nodes:
        local_id = str(node.uuid)
        entity_type = str(node.attributes["entity_type_id"])
        candidates = tuple(
            CanonicalEntityCandidate(
                canonical_entity_id=str(candidate.uuid),
                canonical_name=str(candidate.name),
                entity_type=str(candidate.attributes.get("entity_type_id", "")),
                governed_aliases=tuple(
                    candidate.attributes.get("governed_aliases", ())
                ),
                governed_identifiers=tuple(
                    candidate.attributes.get("governed_identifiers", ())
                ),
                embedding_similarity_ppm=similarities.get(
                    (local_id, str(candidate.uuid)), 0
                ),
                permitted_source_ids=tuple(
                    candidate.attributes.get(
                        "permitted_source_ids",
                        (candidate.attributes.get("source_id", "UNPERMITTED"),),
                    )
                ),
            )
            for candidate in existing_nodes
        )
        resolution = resolve_entity_locally(
            EntityMentionInput(
                name=str(node.name),
                entity_type=entity_type,
                source_id=source_id,
                governed_identifiers=tuple(
                    node.attributes.get("governed_identifiers", ())
                ),
            ),
            candidates,
        )
        selected = node
        if (
            resolution.outcome
            is LocalEntityResolutionOutcome.DETERMINISTIC_EXISTING_NODE
        ):
            selected = next(
                item
                for item in existing_nodes
                if str(item.uuid) == resolution.selected_canonical_entity_id
            )
            uuid_map[local_id] = str(selected.uuid)
        elif (
            resolution.outcome
            is LocalEntityResolutionOutcome.DETERMINISTIC_NEW_NODE
        ):
            uuid_map[local_id] = local_id
        attributes = dict(getattr(selected, "attributes", {}) or {})
        attributes.update(
            {
                "resolution": resolution.outcome.value,
                "resolution_basis": resolution.basis.value,
                "considered_canonical_entity_ids": list(
                    resolution.considered_canonical_entity_ids
                ),
            }
        )
        selected.attributes = attributes
        resolved_nodes.append(selected)
    return resolved_nodes, uuid_map, []


async def _complete_failure(
    pipeline: ExistingGraphitiPipeline,
    prompt: Any,
    receipt: Mapping[str, object],
    *,
    failure_code: CombinedTemporalFailureCode,
) -> CombinedTemporalLeaf:
    terminal = {
        **receipt,
        "terminal_outcome": CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE,
        "failure_code": failure_code,
    }
    completed = await pipeline._complete_failure(terminal)
    return _leaf(
        prompt,
        completed,
        outcome=CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE,
        failure_code=failure_code,
        journal_skipped=False,
    )


async def extract_combined_temporal_async(
    revision: SourceRevisionInput,
    *,
    transport: AsyncCombinedTemporalTransport,
    pipeline: ExistingGraphitiPipeline,
    max_tokens: int = 16_384,
    sidecar_input: DeterministicSidecarInput | None = None,
    admitted_summary_assertions: tuple[AdmittedSummaryAssertion, ...] = (),
    attempt_prepared: bool = False,
) -> CombinedTemporalLeaf:
    """Run one combined-temporal leaf without crossing event loops."""

    UtcTimestamp.parse(revision.ingested_at)
    prompt = build_compact_prompt(revision)
    prompt_digest = _candidate_prompt_digest(prompt)
    completed = None if attempt_prepared else await pipeline._prepare_attempt()
    if completed is not None:
        return _leaf_from_completed(
            revision=revision,
            prompt=prompt,
            prompt_digest=prompt_digest,
            completed=completed,
        )
    receipt: dict[str, object] = {
        "prompt_digest": prompt_digest,
        "ingest_id": revision.ingest_id,
        "temporal_basis": revision.temporal_basis,
        "configuration_digest": configuration_digest(),
        "temporal_policy_digest": digest_canonical(TEMPORAL_POLICY_VERSION),
        "invocation_count": 1,
        "chat_receipts_include_transport": True,
        "transport_calls": [],
    }
    try:
        result = await transport.generate_response(
            prompt=prompt.text,
            schema=SCHEMA,
            response_model=CONTRACT_NAME,
            max_tokens=max_tokens,
        )
        raw = result.raw
        raw_digest_value = raw_digest(raw)
        usage = dict(result.token_usage)
        receipt.update(
            {
                "raw_output_digest": raw_digest_value,
                "framework_version": result.framework_version,
                "model_version": result.model_version,
                "token_usage": usage,
                "provider_cost": result.provider_cost,
                "transport_calls": [
                    {
                        "response_model": CONTRACT_NAME,
                        "prompt_bytes": len(prompt.text.encode("utf-8")),
                        "schema_bytes": len(canonical_json_bytes(SCHEMA)),
                        "raw_output_digest": raw_digest_value,
                        "framework_version": result.framework_version,
                        "model_version": result.model_version,
                        "token_usage": usage,
                        "provider_cost": result.provider_cost,
                    }
                ],
            }
        )
    except Exception:
        return await _complete_failure(
            pipeline,
            prompt,
            receipt,
            failure_code=CombinedTemporalFailureCode.PIPELINE_FAILED,
        )
    try:
        normalised, ranges, nodes, edges = _validate_and_expand(
            revision=revision,
            prompt=prompt,
            raw=raw,
        )
        receipt["proposal_receipt"] = _proposal_receipt(
            revision=revision,
            payload=normalised,
            ranges=ranges,
        )
        if sidecar_input is not None:
            sidecar = project_deterministic_sidecar(sidecar_input)
            node_names = {str(node.uuid): str(node.name) for node in nodes}
            semantic = tuple(
                SemanticRelationProposal(
                    proposal_id=str(edge.uuid),
                    relation=RelationTriple(
                        node_names[str(edge.source_node_uuid)],
                        str(edge.name),
                        node_names[str(edge.target_node_uuid)],
                    ),
                    evidence_segment_ids=tuple(
                        edge.attributes["evidence_segment_ids"]
                    ),
                )
                for edge in edges
            )
            collapse = collapse_sidecar_duplicates(sidecar, semantic)
            collapsed_ids = {
                item.semantic_proposal_id for item in collapse.collapsed_duplicates
            }
            for edge in edges:
                if str(edge.uuid) in collapsed_ids:
                    edge.attributes = {
                        **edge.attributes,
                        "collapsed_sidecar_duplicate": True,
                    }
            receipt["deterministic_sidecar"] = {
                "relation_proposals": [
                    item.canonical_value() for item in sidecar.relation_proposals
                ],
                "authority": sidecar.authority,
                "proposal_only": sidecar.proposal_only,
                "model_leaf_count": sidecar.model_leaf_count,
                "digest": sidecar.digest,
            }
            receipt["sidecar_collapse"] = {
                "semantic_relation_proposals": [
                    item.canonical_value()
                    for item in collapse.semantic_relation_proposals
                ],
                "collapsed_duplicates": [
                    item.canonical_value()
                    for item in collapse.collapsed_duplicates
                ],
                "model_leaf_count": collapse.model_leaf_count,
                "digest": collapse.digest,
            }
        if admitted_summary_assertions:
            summary = build_deterministic_summary(admitted_summary_assertions)
            receipt["deterministic_summary"] = {
                "outcome": summary.outcome.value,
                "summary": summary.summary,
                "assertion_ids": list(summary.assertion_ids),
                "evidence_links": list(summary.evidence_links),
                "temporal_links": list(summary.temporal_links),
                "admission_decisions": [
                    item.canonical_value() for item in summary.admission_decisions
                ],
                "maximum_bytes": summary.maximum_bytes,
                "provider_leaf_count": summary.provider_leaf_count,
                "requires_separate_policy": summary.requires_separate_policy,
                "digest": summary.digest,
            }
    except CombinedTemporalError as exc:
        return await _complete_failure(
            pipeline,
            prompt,
            receipt,
            failure_code=exc.code,
        )
    except CanonicalizationError:
        return await _complete_failure(
            pipeline,
            prompt,
            receipt,
            failure_code=CombinedTemporalFailureCode.MALFORMED_OBJECT,
        )
    try:
        pipeline_result = await pipeline._execute(
            nodes=nodes,
            edges=edges,
            receipt={**receipt, "provider_attempt_number": 1},
        )
    except CombinedTemporalPipelineError as exc:
        return _leaf(
            prompt,
            receipt,
            outcome=CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE,
            failure_code=CombinedTemporalFailureCode.PIPELINE_FAILED,
            embedding_skipped=False,
            journal_skipped=False,
            rollback_skipped=not exc.rollback_completed,
            graph_effect_attempted=exc.graph_effect_attempted,
        )
    if pipeline_result.completed_receipt is not None:
        receipt = dict(pipeline_result.completed_receipt)
    return _leaf(
        prompt,
        receipt,
        outcome=(
            CombinedTemporalOutcome.TERMINAL_SUCCESS_ZERO_PROPOSALS
            if not normalised["facts"]
            else CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS
        ),
        payload=normalised,
        payload_digest=digest_canonical(normalised),
        nodes=pipeline_result.nodes,
        edges=pipeline_result.edges,
        guarded_edges=pipeline_result.guarded_edges,
        evidence_ranges=ranges,
        node_resolutions=pipeline_result.node_resolutions,
        embedding_skipped=pipeline_result.embedding_skipped,
        journal_skipped=pipeline_result.journal_skipped,
        rollback_skipped=pipeline_result.rollback_skipped,
        graph_effect_attempted=pipeline_result.graph_effect_attempted,
    )


__all__ = [
    "AsyncCombinedTemporalTransport",
    "CliCombinedTemporalTransport",
    "NewsroomCombinedTemporalExtractionV1",
    "extract_combined_temporal_async",
    "resolve_nodes_locally",
]
