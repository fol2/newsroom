"""Build an EVALUATION Graphiti attempt from one corpus ingest unit."""

from __future__ import annotations

from newsroom.authority.canonical import digest_bytes, digest_canonical
from newsroom.authority.objects import (
    HydrationPolicyContract,
    ObjectAccessDecisionId,
)
from newsroom.authority.types import ObjectAdmissionId
from newsroom.effective_revision import EffectiveRevisionIdentity
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
from newsroom.graphiti_adapter.identity import (
    MAX_EPISODE_BYTES,
    attempt_ids,
    content_digest,
    ingest_key,
    observation_authority_ids,
    representation_digest_for,
    source_definition_version_id,
    typed_id,
)
from newsroom.graphiti_adapter.temporal import map_reference_time
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
    GRAPHITI_EXTRACTION_TIMEOUT_MS,
    GRAPHITI_GENERATION_ID,
)
from .models import GraphitiAdapterConfiguration, GraphitiAttemptRequest, GraphitiInputManifest
from .types import (
    GraphitiAdapterConfigurationId,
    GraphitiExecutionProfile,
    GraphitiInputManifestId,
    GraphitiRuntimeMode,
)

_PIN = digest_canonical(
    {
        "framework": GRAPHITI_CORE_RELEASE,
        "model": GRAPHITI_CHAT_MODEL,
        "embedding": GRAPHITI_EMBEDDING_MODEL,
    }
)
GRAPHITI_EVALUATION_CONTRACT_ID = typed_id(
    ExtractorContractId, "contract", "evaluation-graphiti-contract-v2"
)
GRAPHITI_EVALUATION_CONFIGURATION_ID = typed_id(
    GraphitiAdapterConfigurationId,
    "config",
    "evaluation-graphiti-configuration-v2",
)
GRAPHITI_EVALUATION_HYDRATION_POLICY = HydrationPolicyContract(
    policy_id="graphiti-evaluation-passage",
    contract_version="hydration-v2",
    implementation_version="graphiti-evaluation-passage-v2",
    purpose="graphiti.corpus-ingest",
    required_scope="authority.objects.read",
    allowed_principal_ids=frozenset({"newsroom.control-plane"}),
    allowed_authority_domains=frozenset({"newsroom.evaluation"}),
    allowed_object_classes=frozenset({"source.expression"}),
    allowed_uses=frozenset({"proposal.extraction"}),
    allowed_security_scopes=frozenset({"evaluation"}),
    allowed_retention_scopes=frozenset({"disposable-workspace"}),
    max_bytes=MAX_EPISODE_BYTES,
    allow_ranges=True,
)


def _component(component_id: str, version: str) -> VersionedExtractionComponent:
    return VersionedExtractionComponent(component_id, version, _PIN)


def _passage(
    text: str,
    *,
    ingest_id: str,
    admission_id: ObjectAdmissionId,
    access_decision_id: ObjectAccessDecisionId,
) -> ExtractionPassageInput:
    encoded = text.encode("utf-8")
    blob = digest_bytes(encoded)
    return ExtractionPassageInput(
        passage_id=typed_id(ExtractionPassageId, "passage", ingest_id),
        admission_id=admission_id,
        access_decision_id=access_decision_id,
        hydration_policy_contract_digest=(
            GRAPHITI_EVALUATION_HYDRATION_POLICY.contract_digest
        ),
        principal_id="newsroom.control-plane",
        authority_domain="newsroom.evaluation",
        purpose="graphiti.corpus-ingest",
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


def evaluation_attempt_for_body(
    *,
    episode_body: str,
    ingest_id: str,
    proving_run_id: str,
    source_id: str,
    item_key: str,
    observation_digest: str,
    published_at: str | None,
    updated_at: str | None,
    effective_revision: EffectiveRevisionIdentity,
    canonical_url: str = "",
    revision_digest: str | None = None,
    representation_digest: str | None = None,
    authority_ids: tuple[str, str, str, str, str, str, str] | None = None,
    attempt_number: int = 1,
    predecessor_episode_uuid: str | None = None,
) -> GraphitiAttemptRequest:
    text = " ".join(episode_body.split())
    if not text:
        raise ValueError("EVALUATION Graphiti attempt needs retained passages")
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_EPISODE_BYTES:
        raise ValueError("EVALUATION Graphiti attempt exceeds the episode chunk bound")
    temporal = map_reference_time(
        published_at=published_at,
        updated_at=updated_at,
        observed_at=effective_revision.first_observed_at,
    )
    attempt_id, workspace_id, cleanup_id = attempt_ids(ingest_id, attempt_number)
    previous_attempt_id = (
        None if attempt_number == 1 else attempt_ids(ingest_id, attempt_number - 1)[0]
    )
    if authority_ids is None:
        revision_digest = revision_digest or content_digest(
            headline="", body=text, canonical_url=canonical_url
        )
        representation_digest = representation_digest or representation_digest_for(
            source_id=source_id,
            item_key=item_key,
            revision_digest=revision_digest,
            published_at=published_at,
            updated_at=updated_at,
        )
        generated = observation_authority_ids(
            source_id=source_id,
            item_key=item_key,
            revision_digest=revision_digest,
            representation_digest=representation_digest,
            rights_authority_run_id=proving_run_id,
            rights_gate_id=f"RIGHTS_{source_id}",
            rights_gate_reason="evaluation fixture",
            published_at=published_at,
            updated_at=updated_at,
        )
        definition_version_id = source_definition_version_id(
            source_id=source_id, source_url=canonical_url
        )
    else:
        admission_id = ObjectAdmissionId.parse(authority_ids[0])
        access_id = ObjectAccessDecisionId.parse(authority_ids[1])
        definition_id = SourceDefinitionId.parse(authority_ids[2])
        definition_version_id = SourceDefinitionVersionId.parse(authority_ids[3])
        item_id = SourceItemId.parse(authority_ids[4])
        revision_id = SourceRevisionId.parse(authority_ids[5])
        representation_id = DiscoveryRepresentationId.parse(authority_ids[6])
        generated = None
    if generated is not None:
        (
            admission_id,
            access_id,
            definition_id,
            item_id,
            revision_id,
            representation_id,
        ) = generated
    bound = (
        _passage(
            text,
            ingest_id=ingest_id,
            admission_id=admission_id,
            access_decision_id=access_id,
        ),
    )
    contract = ExtractorContractRequest(
        contract_id=GRAPHITI_EVALUATION_CONTRACT_ID,
        framework=_component("graphiti.framework", GRAPHITI_CORE_RELEASE),
        model=_component("graphiti.model", GRAPHITI_CHAT_MODEL),
        prompt=GRAPHITI_PROMPT_COMPONENT,
        output_schema=GRAPHITI_ADAPTER_OUTPUT_SCHEMA_COMPONENT,
        code=GRAPHITI_ADAPTER_CODE_COMPONENT,
        normalisation=GRAPHITI_ADAPTER_NORMALISATION_COMPONENT,
        policy=GRAPHITI_ADAPTER_POLICY_COMPONENT,
        execution_profile=ExtractionExecutionProfile.FIXTURE_REPLAY_ONLY,
        producer_kind="GRAPHITI_EVALUATION",
        idempotency_key="evaluation-graphiti-contract-v2",
    )
    configuration = GraphitiAdapterConfiguration(
        configuration_id=GRAPHITI_EVALUATION_CONFIGURATION_ID,
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
        idempotency_key="evaluation-graphiti-configuration-v2",
    )
    request = ExtractionRunRequest(
        run_id=typed_id(ExtractionRunId, "run", ingest_id),
        run_version_id=typed_id(ExtractionRunVersionId, "run-version", ingest_id),
        version_number=1,
        expected_previous_version_id=None,
        contract_id=contract.contract_id,
        input_binding=ExtractionInputBinding(
            definition_id=definition_id,
            definition_version_id=definition_version_id,
            item_id=item_id,
            revision_id=revision_id,
            representation_id=representation_id,
            passages=bound,
        ),
        budget=ExtractionBudget(
            timeout_ms=GRAPHITI_EXTRACTION_TIMEOUT_MS,
            max_input_bytes=64 * 1024,
            max_output_bytes=256 * 1024,
            max_proposals=100,
            max_evidence_ranges=500,
            max_request_tokens=8_000,
            # Align to GRAPHITI_CHAT_PRIMARY call-shape max_output_tokens.
            max_response_tokens=16_384,
            max_cost_microunits=500_000,
        ),
        idempotency_key="evaluation-graphiti-run-v2",
    )
    return GraphitiAttemptRequest(
        attempt_id=attempt_id,
        attempt_number=attempt_number,
        expected_previous_attempt_id=previous_attempt_id,
        configuration=configuration,
        workspace_id=workspace_id,
        cleanup_receipt_id=cleanup_id,
        manifest=GraphitiInputManifest.from_run_request(
            manifest_id=typed_id(GraphitiInputManifestId, "manifest", ingest_id),
            configuration=configuration,
            contract=contract,
            request=request,
        ),
        extraction_contract=contract,
        extraction_request=request,
        replay_source=None,
        idempotency_key=f"evaluation-graphiti-attempt-{ingest_id}",
        reference_time=temporal.reference_time,
        temporal_basis=temporal.basis,
        episode_uuid=ingest_id,
        generation_id=GRAPHITI_GENERATION_ID,
        predecessor_episode_uuid=predecessor_episode_uuid,
    )


def evaluation_attempt_for(passages: tuple[str, ...]) -> GraphitiAttemptRequest:
    if not passages:
        raise ValueError("EVALUATION Graphiti attempt needs retained passages")
    body = "\n\n".join(" ".join(item.split()) for item in passages if item.split())
    digest = content_digest(headline="", body=body, canonical_url="")
    observed_at = "2026-08-20T00:00:00.000000Z"
    effective_revision = EffectiveRevisionIdentity(
        source_id="evaluation",
        item_key="passages",
        revision_digest=digest,
        first_observed_at=observed_at,
    )
    ingest_id = ingest_key(
        source_id="evaluation",
        item_key="passages",
        content_digest_value=digest,
        revision_id=digest,
        representation_digest=digest,
        published_at=None,
        updated_at=None,
    )
    return evaluation_attempt_for_body(
        episode_body=body,
        ingest_id=ingest_id,
        proving_run_id="evaluation",
        source_id="evaluation",
        item_key="passages",
        observation_digest=digest,
        published_at=None,
        updated_at=None,
        effective_revision=effective_revision,
    )


__all__ = [
    "GRAPHITI_EVALUATION_CONFIGURATION_ID",
    "GRAPHITI_EVALUATION_CONTRACT_ID",
    "evaluation_attempt_for",
    "evaluation_attempt_for_body",
]
