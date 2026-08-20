from __future__ import annotations

from newsroom.authority.canonical import digest_canonical
from newsroom.extraction.models import ExtractorContractRequest
from newsroom.extraction.types import FixtureExtractionCase, VersionedExtractionComponent

from .models import GraphitiAdapterConfiguration, GraphitiWorkspacePolicy
from .types import (
    GraphitiAdapterConfigurationId,
    GraphitiAdapterContractError,
    GraphitiCredentialClass,
    GraphitiEgressPolicy,
    GraphitiExecutionProfile,
    GraphitiRuntimeMode,
    GraphitiWorkspacePolicyId,
)


GRAPHITI_ADAPTER_CONTRACT_VERSION = "graphiti-proposal-adapter-v1"
GRAPHITI_ADAPTER_POLICY_VERSION = "graphiti-proposal-only-policy-v1"
GRAPHITI_WORKSPACE_POLICY_VERSION = "graphiti-disposable-workspace-v1"


def _component(
    component_id: str,
    component_version: str,
    contract: object,
) -> VersionedExtractionComponent:
    return VersionedExtractionComponent(
        component_id=component_id,
        component_version=component_version,
        contract_digest=digest_canonical(contract),
    )


GRAPHITI_FRAMEWORK_PLACEHOLDER_COMPONENT = _component(
    "newsroom.graphiti.framework-placeholder",
    "unapproved-v1",
    {
        "framework": "Graphiti",
        "release": None,
        "real_runtime_authorized": False,
    },
)
GRAPHITI_NO_MODEL_COMPONENT = _component(
    "newsroom.graphiti.no-model",
    "v1",
    {
        "model": None,
        "provider": None,
        "credentials": False,
        "network": False,
    },
)
GRAPHITI_NO_EMBEDDING_COMPONENT = _component(
    "newsroom.graphiti.no-embedding",
    "v1",
    {
        "embedding": None,
        "provider": None,
        "credentials": False,
        "network": False,
    },
)
GRAPHITI_PROMPT_COMPONENT = _component(
    "newsroom.graphiti.proposal-only-prompt",
    "v1",
    {
        "source_is_untrusted_data": True,
        "tools": [],
        "egress": False,
        "authority": "PROPOSAL_ONLY",
        "caller_cannot_change_contract": True,
    },
)
GRAPHITI_ADAPTER_OUTPUT_SCHEMA_COMPONENT = _component(
    "newsroom.graphiti.adapter-result-schema",
    "v1",
    {
        "outcomes": [
            "COMPLETE",
            "PARTIAL",
            "TIMEOUT",
            "MALFORMED_OUTPUT",
            "PROVIDER_REJECTED",
            "POLICY_BLOCKED",
            "FAILED",
            "AMBIGUOUS_EFFECT",
        ],
        "private_graph_ids_public": False,
        "credentials_public": False,
        "arbitrary_cypher_public": False,
    },
)
GRAPHITI_ADAPTER_CODE_COMPONENT = _component(
    "newsroom.graphiti.adapter-code",
    GRAPHITI_ADAPTER_CONTRACT_VERSION,
    {
        "interface": "ProposalOnlyGraphitiAdapter",
        "implementations": ["deterministic-fake", "approved-replay"],
        "real_runtime": False,
    },
)
GRAPHITI_ADAPTER_NORMALISATION_COMPONENT = _component(
    "newsroom.graphiti.adapter-normalisation",
    "v1",
    {
        "encoding": "utf-8",
        "canonical_json": True,
        "source_text_rewrite": False,
        "private_ids_removed": True,
    },
)
GRAPHITI_ADAPTER_TEMPORAL_COMPONENT = _component(
    "newsroom.graphiti.adapter-temporal-policy",
    "v2",
    {
        "source_time_is_metadata": True,
        "authority_time_is_separate": True,
        "workspace_state_is_disposable": True,
        "reference_time_from_source": True,
        "started_at_forbidden": True,
        "observed_fallback_labelled": True,
        "policy": "graphiti-source-reference-time-v1",
    },
)
GRAPHITI_ADAPTER_POLICY_COMPONENT = _component(
    "newsroom.graphiti.adapter-policy",
    GRAPHITI_ADAPTER_POLICY_VERSION,
    {
        "proposal_only": True,
        "persist_before_admission": True,
        "governed_graph_write": False,
        "entity_decision_write": False,
        "relation_decision_write": False,
        "candidate_write": False,
        "evidence_intake_write": False,
        "publication_write": False,
        "real_runtime_authorized": False,
    },
)

QUALIFICATION_WORKSPACE_POLICY = GraphitiWorkspacePolicy(
    policy_id=GraphitiWorkspacePolicyId.parse(
        "00000000-0000-4000-8000-000000004801"
    ),
    policy_version=GRAPHITI_WORKSPACE_POLICY_VERSION,
    namespace_prefix="graphiti-qualification",
    max_workspace_bytes=4 * 1024 * 1024,
    max_private_nodes=1_000,
    max_private_relations=2_000,
    egress_policy=GraphitiEgressPolicy.DENY_ALL,
    credential_class=GraphitiCredentialClass.NONE,
)

REPLAY_WORKSPACE_POLICY = GraphitiWorkspacePolicy(
    policy_id=GraphitiWorkspacePolicyId.parse(
        "00000000-0000-4000-8000-000000004802"
    ),
    policy_version=GRAPHITI_WORKSPACE_POLICY_VERSION,
    namespace_prefix="graphiti-replay",
    max_workspace_bytes=1 * 1024 * 1024,
    max_private_nodes=1,
    max_private_relations=1,
    egress_policy=GraphitiEgressPolicy.DENY_ALL,
    credential_class=GraphitiCredentialClass.NONE,
)


def qualification_configuration(
    *,
    configuration_id: GraphitiAdapterConfigurationId,
    contract: ExtractorContractRequest,
    fixture_case: FixtureExtractionCase = FixtureExtractionCase.BILINGUAL_COMPLETE,
    idempotency_key: str = "increment-4d-qualification-config-v1",
) -> GraphitiAdapterConfiguration:
    if not isinstance(contract, ExtractorContractRequest):
        raise GraphitiAdapterContractError(
            "qualification configuration requires a typed extractor contract"
        )
    return GraphitiAdapterConfiguration(
        configuration_id=configuration_id,
        runtime_mode=GraphitiRuntimeMode.DETERMINISTIC_FAKE,
        execution_profile=GraphitiExecutionProfile.QUALIFICATION,
        framework=GRAPHITI_FRAMEWORK_PLACEHOLDER_COMPONENT,
        model=GRAPHITI_NO_MODEL_COMPONENT,
        embedding=GRAPHITI_NO_EMBEDDING_COMPONENT,
        prompt=GRAPHITI_PROMPT_COMPONENT,
        output_schema=GRAPHITI_ADAPTER_OUTPUT_SCHEMA_COMPONENT,
        code=GRAPHITI_ADAPTER_CODE_COMPONENT,
        normalisation=GRAPHITI_ADAPTER_NORMALISATION_COMPONENT,
        temporal_policy=GRAPHITI_ADAPTER_TEMPORAL_COMPONENT,
        adapter_policy=GRAPHITI_ADAPTER_POLICY_COMPONENT,
        extractor_contract_id=contract.contract_id,
        extractor_contract_digest=contract.digest,
        workspace_policy=QUALIFICATION_WORKSPACE_POLICY,
        fixture_case=fixture_case,
        real_runtime_authority=None,
        idempotency_key=idempotency_key,
    )


def replay_configuration(
    *,
    configuration_id: GraphitiAdapterConfigurationId,
    contract: ExtractorContractRequest,
    idempotency_key: str = "increment-4d-replay-config-v1",
) -> GraphitiAdapterConfiguration:
    if not isinstance(contract, ExtractorContractRequest):
        raise GraphitiAdapterContractError(
            "replay configuration requires a typed extractor contract"
        )
    return GraphitiAdapterConfiguration(
        configuration_id=configuration_id,
        runtime_mode=GraphitiRuntimeMode.APPROVED_REPLAY,
        execution_profile=GraphitiExecutionProfile.REPLAY,
        framework=GRAPHITI_FRAMEWORK_PLACEHOLDER_COMPONENT,
        model=GRAPHITI_NO_MODEL_COMPONENT,
        embedding=GRAPHITI_NO_EMBEDDING_COMPONENT,
        prompt=GRAPHITI_PROMPT_COMPONENT,
        output_schema=GRAPHITI_ADAPTER_OUTPUT_SCHEMA_COMPONENT,
        code=GRAPHITI_ADAPTER_CODE_COMPONENT,
        normalisation=GRAPHITI_ADAPTER_NORMALISATION_COMPONENT,
        temporal_policy=GRAPHITI_ADAPTER_TEMPORAL_COMPONENT,
        adapter_policy=GRAPHITI_ADAPTER_POLICY_COMPONENT,
        extractor_contract_id=contract.contract_id,
        extractor_contract_digest=contract.digest,
        workspace_policy=REPLAY_WORKSPACE_POLICY,
        fixture_case=None,
        real_runtime_authority=None,
        idempotency_key=idempotency_key,
    )


__all__ = [
    "GRAPHITI_ADAPTER_CODE_COMPONENT",
    "GRAPHITI_ADAPTER_CONTRACT_VERSION",
    "GRAPHITI_ADAPTER_NORMALISATION_COMPONENT",
    "GRAPHITI_ADAPTER_OUTPUT_SCHEMA_COMPONENT",
    "GRAPHITI_ADAPTER_POLICY_COMPONENT",
    "GRAPHITI_ADAPTER_POLICY_VERSION",
    "GRAPHITI_ADAPTER_TEMPORAL_COMPONENT",
    "GRAPHITI_FRAMEWORK_PLACEHOLDER_COMPONENT",
    "GRAPHITI_NO_EMBEDDING_COMPONENT",
    "GRAPHITI_NO_MODEL_COMPONENT",
    "GRAPHITI_PROMPT_COMPONENT",
    "GRAPHITI_WORKSPACE_POLICY_VERSION",
    "QUALIFICATION_WORKSPACE_POLICY",
    "REPLAY_WORKSPACE_POLICY",
    "qualification_configuration",
    "replay_configuration",
]
