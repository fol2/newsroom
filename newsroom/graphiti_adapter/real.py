"""EVALUATION Graphiti executor. Proposal-only; does not write the ledger.

graphiti-core is an optional extra. Construction and authorization checks do not
import it, fetch Keychain secrets, or call OpenRouter. Completeness of this
module is not REAL_GRAPHITI_RUNTIME_ENABLED.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import tempfile
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
    CURSOR_AGENT_MODEL_ID,
    GRAPHITI_CHAT_MODEL,
    GRAPHITI_CORE_RELEASE,
    GRAPHITI_EMBEDDING_MODEL,
    GRAPHITI_GENERATION_ID,
    GRAPHITI_WORKSPACE_GROUP,
    GROK_CHAT_MODEL_ID,
    GROK_CHAT_REASONING,
    OPENROUTER_BASE_URL,
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
_SOURCE_REGISTRY_ID = re.compile(r"^[A-Z]{2,3}-\d{2}(?::.*)?$")
_EXTRACTION_INSTRUCTIONS = (
    "Extract people, organisations, places, events, policies and their relations "
    "from the source content. Do not treat newsroom source-registry identifiers "
    "(for example HK-04, RAD-02, UK-01) as world entities or relations. "
    "Do not extract SourceItem, SourceRevision, DERIVED_FROM or OBSERVED_IN lineage."
)
CURSOR_AGENT_BIN = os.environ.get(
    "NEWSROOM_CURSOR_AGENT_BIN", "/Users/jamesto/.local/bin/cursor-agent"
)
GROK_BIN = os.environ.get("NEWSROOM_GROK_BIN", "/Users/jamesto/.grok/bin/grok")
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


def _extract_json(raw: str) -> str:
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("Graphiti CLI returned no JSON object")
    return raw[start : end + 1]


def _run_cli(command: tuple[str, ...], *, timeout: int, cwd: str | None = None) -> str:
    name = os.path.basename(command[0])
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{name} Graphiti LLM timed out") from None
    if result.returncode != 0:
        raise RuntimeError(f"{name} Graphiti LLM failed")
    if not result.stdout.strip():
        raise RuntimeError("Graphiti LLM returned empty stdout")
    return result.stdout


def _run_cursor_agent_llm(prompt: str) -> str:
    return _run_cli(
        (
            CURSOR_AGENT_BIN,
            "--print",
            "--mode",
            "ask",
            "--output-format",
            "text",
            "--sandbox",
            "enabled",
            "--trust",
            "--model",
            CURSOR_AGENT_MODEL_ID,
            prompt,
        ),
        timeout=180,
    )


def _run_grok_llm(prompt: str, *, schema: str | None) -> str:
    with tempfile.TemporaryDirectory(prefix="newsroom-grok-graphiti-") as cwd:
        path = os.path.join(cwd, "prompt.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(prompt)
        command = [
            GROK_BIN,
            "--prompt-file",
            path,
            "-m",
            GROK_CHAT_MODEL_ID,
            "--disable-web-search",
            "--no-plan",
            "--max-turns",
            "3",
            "--no-subagents",
            "--reasoning-effort",
            GROK_CHAT_REASONING,
        ]
        if schema:
            command.extend(["--json-schema", schema])
        return _run_cli(tuple(command), timeout=300, cwd=cwd)


def _messages_to_prompt(messages: list[Any]) -> str:
    return "\n\n".join(
        f"{getattr(message, 'role', 'user')}:\n{getattr(message, 'content', '')}"
        for message in messages
    )


def build_cli_llm_client() -> Any:
    from graphiti_core.llm_client.client import LLMClient
    from graphiti_core.llm_client.config import LLMConfig
    from graphiti_core.llm_client.errors import EmptyResponseError
    from pydantic import BaseModel

    class CliChainGraphitiLlmClient(LLMClient):
        def __init__(self) -> None:
            super().__init__(
                LLMConfig(model=CURSOR_AGENT_MODEL_ID, small_model=CURSOR_AGENT_MODEL_ID),
                cache=False,
            )
            self.invocations: list[dict[str, str]] = []

        async def _generate_response(
            self,
            messages: list[Any],
            response_model: type[BaseModel] | None = None,
            max_tokens: int = 0,
            model_size: object = None,
        ) -> dict[str, Any]:
            prompt = _messages_to_prompt(messages)
            schema = (
                json.dumps(response_model.model_json_schema())
                if response_model is not None
                else None
            )
            try:
                raw = await asyncio.to_thread(_run_cursor_agent_llm, prompt)
                self.invocations.append(
                    {"provider": "cursor-agent-cli", "model": CURSOR_AGENT_MODEL_ID}
                )
            except (RuntimeError, OSError):
                raw = await asyncio.to_thread(_run_grok_llm, prompt, schema=schema)
                self.invocations.append(
                    {"provider": "grok-build-cli", "model": GROK_CHAT_MODEL_ID}
                )
            try:
                payload = json.loads(_extract_json(raw))
            except json.JSONDecodeError as exc:
                raise EmptyResponseError("Graphiti CLI returned malformed JSON") from exc
            if not isinstance(payload, dict):
                raise EmptyResponseError("Graphiti CLI JSON was not an object")
            return payload

    return CliChainGraphitiLlmClient()


def _load_graphiti() -> SimpleNamespace:
    try:
        import importlib.metadata

        from graphiti_core import Graphiti
        from graphiti_core.cross_encoder.client import CrossEncoderClient
        from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
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

    class IdentityCrossEncoder(CrossEncoderClient):
        async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
            return [(item, 0.0) for item in passages]

    return SimpleNamespace(
        Graphiti=Graphiti,
        OpenAIEmbedder=OpenAIEmbedder,
        OpenAIEmbedderConfig=OpenAIEmbedderConfig,
        IdentityCrossEncoder=IdentityCrossEncoder,
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


def _is_source_registry_name(name: str) -> bool:
    return _SOURCE_REGISTRY_ID.match(name) is not None


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
        if not name or _is_source_registry_name(name):
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


def _iso(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _relation_receipts(result: Any) -> tuple[dict[str, object], ...]:
    receipts: list[dict[str, object]] = []
    edges = getattr(result, "edges", ()) or ()
    for index, edge in enumerate(edges, start=1):
        receipts.append(
            {
                "local_id": f"relation.{index:04d}",
                "uuid": getattr(edge, "uuid", None),
                "name": getattr(edge, "name", None),
                "fact": getattr(edge, "fact", None),
                "source_node_uuid": getattr(edge, "source_node_uuid", None),
                "target_node_uuid": getattr(edge, "target_node_uuid", None),
                "valid_at": _iso(getattr(edge, "valid_at", None)),
                "invalid_at": _iso(getattr(edge, "invalid_at", None)),
                "expired_at": _iso(getattr(edge, "expired_at", None)),
            }
        )
    return tuple(receipts)


def _entity_receipts(result: Any) -> tuple[dict[str, object], ...]:
    receipts: list[dict[str, object]] = []
    nodes = getattr(result, "nodes", ()) or ()
    for index, node in enumerate(nodes, start=1):
        name = getattr(node, "name", None)
        receipts.append(
            {
                "local_id": f"entity.{index:04d}",
                "uuid": getattr(node, "uuid", None),
                "name": name,
                "summary": getattr(node, "summary", None),
                "source_registry_id": (
                    True
                    if isinstance(name, str) and _is_source_registry_name(name)
                    else False
                ),
            }
        )
    return tuple(receipts)


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
    relations: tuple[dict[str, object], ...],
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
    private_relations = tuple(
        {
            "private_relation_id": f"private-relation-{index:04d}",
            "proposal_local_id": item["local_id"],
            "name": item.get("name"),
            "fact": item.get("fact"),
            "source_node_uuid": item.get("source_node_uuid"),
            "target_node_uuid": item.get("target_node_uuid"),
            "valid_at": item.get("valid_at"),
            "invalid_at": item.get("invalid_at"),
        }
        for index, item in enumerate(relations, start=1)
    )
    return nodes, private_relations


async def _add_episode(
    *,
    api_key: str,
    password: str,
    body: str,
    name: str,
    reference_time: datetime,
    episode_uuid: str,
) -> tuple[Any, list[dict[str, str]]]:
    os.environ.setdefault("GRAPHITI_TELEMETRY_ENABLED", "false")
    runtime = _load_graphiti()
    llm_client = build_cli_llm_client()
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
        cross_encoder=runtime.IdentityCrossEncoder(),
    )
    try:
        result = await graphiti.add_episode(
            name=name,
            episode_body=body,
            source_description=GRAPHITI_WORKSPACE_GROUP,
            reference_time=reference_time,
            source=runtime.EpisodeType.text,
            group_id=GRAPHITI_WORKSPACE_GROUP,
            uuid=episode_uuid,
            update_communities=False,
            custom_extraction_instructions=_EXTRACTION_INSTRUCTIONS,
        )
        return result, list(getattr(llm_client, "invocations", ()))
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
            raw = produced.raw_output_value if isinstance(produced.raw_output_value, dict) else {}
            relations = tuple(raw.get("relations", ())) if isinstance(raw.get("relations"), list | tuple) else ()
            nodes, private_relations = _private_graph(produced, relations)
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
        episode_uuid = attempt.episode_uuid or str(attempt.attempt_id)
        try:
            _load_graphiti()
            api_key = openrouter_api_key()
            password = neo4j_community_password()
            result, invocations = asyncio.run(
                asyncio.wait_for(
                    _add_episode(
                        api_key=api_key,
                        password=password,
                        body=_episode_body(attempt),
                        name=episode_uuid,
                        reference_time=reference.value,
                        episode_uuid=episode_uuid,
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
        relations = _relation_receipts(result)
        entities = _entity_receipts(result)
        raw: dict[str, object] = {
            "workspace_group": GRAPHITI_WORKSPACE_GROUP,
            "generation_id": attempt.generation_id or GRAPHITI_GENERATION_ID,
            "episode_uuid": episode_uuid,
            "temporal_basis": attempt.temporal_basis,
            "reference_time": reference.to_text(),
            "ingest_started_at": started_at.to_text(),
            "entities": list(entities),
            "relations": list(relations),
            "entity_count": len(entities),
            "relation_count": len(relations),
            "proposal_count": len(proposals) + len(relations),
            "chat_invocations": invocations,
            "chat_subscription_not_debited": True,
        }
        raw["raw_output_digest"] = digest_bytes(canonical_json_bytes(raw))
        if not proposals and not relations:
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
