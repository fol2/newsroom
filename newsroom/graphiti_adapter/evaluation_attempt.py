"""Build an EVALUATION Graphiti attempt from unpublished Evidence Package text."""

from __future__ import annotations

from newsroom.authority.canonical import digest_bytes, digest_canonical
from newsroom.authority.objects import ObjectAccessDecisionId
from newsroom.authority.types import ObjectAdmissionId
from newsroom.extraction.models import (
    ExtractionInputBinding,
    ExtractionPassageInput,
    ExtractionRunRequest,
    ExtractorContractRequest,
)
from newsroom.extraction.types import (
    ExtractionBudget,
    ExtractionExecutionProfile,
    ExtractionPassageId,
    ExtractionRunId,
    ExtractionRunVersionId,
    ExtractorContractId,
    VersionedExtractionComponent,
)
from newsroom.sources.types import (
    DiscoveryRepresentationId,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceItemId,
    SourceRevisionId,
)

from .contracts import (
    GRAPHITI_ADAPTER_CODE_COMPONENT,
    GRAPHITI_ADAPTER_NORMALISATION_COMPONENT,
    GRAPHITI_ADAPTER_OUTPUT_SCHEMA_COMPONENT,
    GRAPHITI_ADAPTER_POLICY_COMPONENT,
    GRAPHITI_ADAPTER_TEMPORAL_COMPONENT,
    GRAPHITI_PROMPT_COMPONENT,
)
from .evaluation_packet import (
    EVALUATION_GRAPHITI_PACKET,
    EVALUATION_WORKSPACE_POLICY,
    GRAPHITI_CHAT_MODEL,
    GRAPHITI_CORE_RELEASE,
    GRAPHITI_EMBEDDING_MODEL,
)
from .models import GraphitiAdapterConfiguration, GraphitiAttemptRequest, GraphitiInputManifest
from .types import (
    GraphitiAdapterConfigurationId,
    GraphitiAttemptId,
    GraphitiCleanupReceiptId,
    GraphitiExecutionProfile,
    GraphitiInputManifestId,
    GraphitiRuntimeMode,
    GraphitiWorkspaceId,
)

_PIN = digest_canonical(
    {
        "framework": GRAPHITI_CORE_RELEASE,
        "model": GRAPHITI_CHAT_MODEL,
        "embedding": GRAPHITI_EMBEDDING_MODEL,
    }
)
_HYDRATION = digest_canonical({"policy": "graphiti-evaluation-passage-v1"})
_MAX_PASSAGES = 8
_MAX_PASSAGE_BYTES = 8 * 1024


def _component(component_id: str, version: str) -> VersionedExtractionComponent:
    return VersionedExtractionComponent(component_id, version, _PIN)


def _passage(text: str) -> ExtractionPassageInput:
    encoded = text.encode("utf-8")
    blob = digest_bytes(encoded)
    return ExtractionPassageInput(
        passage_id=ExtractionPassageId.new(),
        admission_id=ObjectAdmissionId.new(),
        access_decision_id=ObjectAccessDecisionId.new(),
        hydration_policy_contract_digest=_HYDRATION,
        principal_id="newsroom.control-plane",
        authority_domain="newsroom.evaluation",
        purpose="graphiti.evaluation",
        object_class="source.expression",
        allowed_use="proposal.extraction",
        security_scope="evaluation",
        retention_scope="disposable-workspace",
        byte_offset=0,
        byte_length=len(encoded),
        blob_digest=blob,
        text_digest=blob,
        language="zh-HK",
        text=text,
    )


def evaluation_attempt_for(passages: tuple[str, ...]) -> GraphitiAttemptRequest:
    if not passages:
        raise ValueError("EVALUATION Graphiti attempt needs retained passages")
    clipped: list[str] = []
    for raw in passages[:_MAX_PASSAGES]:
        text = " ".join(raw.split())
        if not text:
            continue
        encoded = text.encode("utf-8")
        if len(encoded) > _MAX_PASSAGE_BYTES:
            text = encoded[:_MAX_PASSAGE_BYTES].decode("utf-8", errors="ignore").rstrip()
        if text:
            clipped.append(text)
    if not clipped:
        raise ValueError("EVALUATION Graphiti attempt needs non-empty passages")
    bound = tuple(sorted((_passage(item) for item in clipped), key=lambda item: str(item.passage_id)))
    contract = ExtractorContractRequest(
        contract_id=ExtractorContractId.new(),
        framework=_component("graphiti.framework", GRAPHITI_CORE_RELEASE),
        model=_component("graphiti.model", GRAPHITI_CHAT_MODEL),
        prompt=GRAPHITI_PROMPT_COMPONENT,
        output_schema=GRAPHITI_ADAPTER_OUTPUT_SCHEMA_COMPONENT,
        code=GRAPHITI_ADAPTER_CODE_COMPONENT,
        normalisation=GRAPHITI_ADAPTER_NORMALISATION_COMPONENT,
        policy=GRAPHITI_ADAPTER_POLICY_COMPONENT,
        execution_profile=ExtractionExecutionProfile.FIXTURE_REPLAY_ONLY,
        producer_kind="GRAPHITI_EVALUATION",
        idempotency_key="evaluation-graphiti-contract-v1",
    )
    configuration = GraphitiAdapterConfiguration(
        configuration_id=GraphitiAdapterConfigurationId.new(),
        runtime_mode=GraphitiRuntimeMode.REAL_GRAPHITI,
        execution_profile=GraphitiExecutionProfile.EVALUATION,
        framework=contract.framework,
        model=contract.model,
        embedding=_component("graphiti.embedding", GRAPHITI_EMBEDDING_MODEL),
        prompt=GRAPHITI_PROMPT_COMPONENT,
        output_schema=GRAPHITI_ADAPTER_OUTPUT_SCHEMA_COMPONENT,
        code=GRAPHITI_ADAPTER_CODE_COMPONENT,
        normalisation=GRAPHITI_ADAPTER_NORMALISATION_COMPONENT,
        temporal_policy=GRAPHITI_ADAPTER_TEMPORAL_COMPONENT,
        adapter_policy=GRAPHITI_ADAPTER_POLICY_COMPONENT,
        extractor_contract_id=contract.contract_id,
        extractor_contract_digest=contract.digest,
        workspace_policy=EVALUATION_WORKSPACE_POLICY,
        fixture_case=None,
        real_runtime_authority=EVALUATION_GRAPHITI_PACKET,
        idempotency_key="evaluation-graphiti-configuration-v1",
    )
    request = ExtractionRunRequest(
        run_id=ExtractionRunId.new(),
        run_version_id=ExtractionRunVersionId.new(),
        version_number=1,
        expected_previous_version_id=None,
        contract_id=contract.contract_id,
        input_binding=ExtractionInputBinding(
            definition_id=SourceDefinitionId.new(),
            definition_version_id=SourceDefinitionVersionId.new(),
            item_id=SourceItemId.new(),
            revision_id=SourceRevisionId.new(),
            representation_id=DiscoveryRepresentationId.new(),
            passages=bound,
        ),
        budget=ExtractionBudget(
            timeout_ms=120_000,
            max_input_bytes=64 * 1024,
            max_output_bytes=256 * 1024,
            max_proposals=100,
            max_evidence_ranges=500,
            max_request_tokens=8_000,
            max_response_tokens=4_000,
            max_cost_microunits=500_000,
        ),
        idempotency_key="evaluation-graphiti-run-v1",
    )
    return GraphitiAttemptRequest(
        attempt_id=GraphitiAttemptId.new(),
        attempt_number=1,
        expected_previous_attempt_id=None,
        configuration=configuration,
        workspace_id=GraphitiWorkspaceId.new(),
        cleanup_receipt_id=GraphitiCleanupReceiptId.new(),
        manifest=GraphitiInputManifest.from_run_request(
            manifest_id=GraphitiInputManifestId.new(),
            configuration=configuration,
            contract=contract,
            request=request,
        ),
        extraction_contract=contract,
        extraction_request=request,
        replay_source=None,
        idempotency_key="evaluation-graphiti-attempt-v1",
    )


__all__ = ["evaluation_attempt_for"]
