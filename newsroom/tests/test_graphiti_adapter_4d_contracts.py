from __future__ import annotations

from dataclasses import replace

import pytest

from newsroom.authority.canonical import digest_canonical
from newsroom.extraction.types import FixtureExtractionCase, VersionedExtractionComponent
from newsroom.graphiti_adapter import (
    GRAPHITI_ADAPTER_CONTRACT_VERSION,
    GRAPHITI_ADAPTER_POLICY_VERSION,
    QUALIFICATION_WORKSPACE_POLICY,
    REPLAY_WORKSPACE_POLICY,
    GraphitiAdapterConfiguration,
    GraphitiAdapterContractError,
    GraphitiAdapterReadPolicy,
    GraphitiCredentialClass,
    GraphitiEgressPolicy,
    GraphitiExecutionProfile,
    GraphitiRuntimeMode,
    GraphitiRuntimeNotAuthorized,
    GraphitiWorkspacePolicy,
    GraphitiWorkspacePolicyId,
    RealGraphitiRuntimeAuthority,
)
from newsroom.graphiti_adapter.contracts import (
    GRAPHITI_ADAPTER_CODE_COMPONENT,
    GRAPHITI_ADAPTER_NORMALISATION_COMPONENT,
    GRAPHITI_ADAPTER_OUTPUT_SCHEMA_COMPONENT,
    GRAPHITI_ADAPTER_POLICY_COMPONENT,
    GRAPHITI_ADAPTER_TEMPORAL_COMPONENT,
    GRAPHITI_FRAMEWORK_PLACEHOLDER_COMPONENT,
    GRAPHITI_NO_EMBEDDING_COMPONENT,
    GRAPHITI_NO_MODEL_COMPONENT,
    GRAPHITI_PROMPT_COMPONENT,
)

from .extraction_4a_helpers import contract_request, seed_extraction_fixture
from .graphiti_adapter_4d_helpers import (
    FAKE_CONFIGURATION_ID,
    fake_attempt,
)


def _digest(label: str) -> str:
    return digest_canonical({"contract": label})


def _real_authority() -> RealGraphitiRuntimeAuthority:
    return RealGraphitiRuntimeAuthority(
        authority_decision_digest=_digest("owner-decision"),
        framework_release="graphiti-placeholder-release",
        model_release="model-placeholder-release",
        embedding_release="embedding-placeholder-release",
        destination_contract_digest=_digest("destination"),
        data_processing_terms_digest=_digest("terms"),
        prompt_contract_digest=_digest("prompt"),
        output_schema_contract_digest=_digest("output"),
        permitted_expression_digest=_digest("expression"),
        rights_privacy_retention_digest=_digest("rights"),
        workspace_security_digest=_digest("workspace"),
        egress_credential_digest=_digest("egress"),
        budget_digest=_digest("budget"),
        evaluation_plan_digest=_digest("evaluation"),
        rollback_digest=_digest("rollback"),
    )


def test_fixed_contract_and_workspace_policies_are_offline_and_canonical() -> None:
    assert GRAPHITI_ADAPTER_CONTRACT_VERSION == "graphiti-proposal-adapter-v1"
    assert GRAPHITI_ADAPTER_POLICY_VERSION == "graphiti-proposal-only-policy-v1"
    for policy in (QUALIFICATION_WORKSPACE_POLICY, REPLAY_WORKSPACE_POLICY):
        assert policy.egress_policy is GraphitiEgressPolicy.DENY_ALL
        assert policy.credential_class is GraphitiCredentialClass.NONE
        assert policy.cleanup_required is True
        assert policy.persistent_state_allowed is False
        assert policy.canonical_digest.startswith("sha256:")
        rendered = policy.canonical_bytes.decode("utf-8")
        assert "secret" not in rendered
        assert "credential" in rendered  # the bounded class is explicit, not a value


def test_fake_configuration_binds_exact_contract_and_excludes_private_state() -> None:
    contract = contract_request()
    from newsroom.graphiti_adapter import qualification_configuration

    configuration = qualification_configuration(
        configuration_id=FAKE_CONFIGURATION_ID,
        contract=contract,
    )
    assert configuration.runtime_mode is GraphitiRuntimeMode.DETERMINISTIC_FAKE
    assert configuration.execution_profile is GraphitiExecutionProfile.QUALIFICATION
    assert configuration.extractor_contract_digest == contract.digest
    assert configuration.fixture_case is FixtureExtractionCase.BILINGUAL_COMPLETE
    configuration.require_execution_authorized()
    rendered = configuration.canonical_bytes.decode("utf-8")
    for prohibited in (
        "private_node_id",
        "private_relation_id",
        "graphiti_node_id",
        "graphiti_relation_id",
        "neo4j_id",
        '"cypher"',
        '"api_key"',
        '"access_token"',
    ):
        assert prohibited not in rendered


def test_fake_and_replay_profiles_cannot_receive_network_or_credentials() -> None:
    contract = contract_request()
    from newsroom.graphiti_adapter import qualification_configuration

    configuration = qualification_configuration(
        configuration_id=FAKE_CONFIGURATION_ID,
        contract=contract,
    )
    online_policy = GraphitiWorkspacePolicy(
        policy_id=GraphitiWorkspacePolicyId.parse(
            "00000000-0000-4000-8000-000000004821"
        ),
        policy_version="graphiti-disposable-workspace-v1",
        namespace_prefix="graphiti-online",
        max_workspace_bytes=1024,
        max_private_nodes=1,
        max_private_relations=1,
        egress_policy=GraphitiEgressPolicy.APPROVED_PROVIDER_ONLY,
        credential_class=GraphitiCredentialClass.PROPOSAL_WORKSPACE_ONLY,
    )
    with pytest.raises(GraphitiAdapterContractError, match="deny-all"):
        replace(configuration, workspace_policy=online_policy)
    with pytest.raises(GraphitiAdapterContractError, match="qualification"):
        replace(
            configuration,
            execution_profile=GraphitiExecutionProfile.PRODUCTION,
        )


def test_real_runtime_evaluation_is_authorized_production_stays_closed() -> None:
    contract = contract_request()
    online_policy = GraphitiWorkspacePolicy(
        policy_id=GraphitiWorkspacePolicyId.parse(
            "00000000-0000-4000-8000-000000004822"
        ),
        policy_version="graphiti-disposable-workspace-v1",
        namespace_prefix="graphiti-real-evaluation",
        max_workspace_bytes=1024 * 1024,
        max_private_nodes=100,
        max_private_relations=100,
        egress_policy=GraphitiEgressPolicy.APPROVED_PROVIDER_ONLY,
        credential_class=GraphitiCredentialClass.PROPOSAL_WORKSPACE_ONLY,
    )
    framework = VersionedExtractionComponent(
        "graphiti.framework",
        "placeholder-release",
        _digest("framework"),
    )
    model = VersionedExtractionComponent(
        "graphiti.model",
        "placeholder-release",
        _digest("model"),
    )
    embedding = VersionedExtractionComponent(
        "graphiti.embedding",
        "placeholder-release",
        _digest("embedding"),
    )
    configuration = GraphitiAdapterConfiguration(
        configuration_id=FAKE_CONFIGURATION_ID,
        runtime_mode=GraphitiRuntimeMode.REAL_GRAPHITI,
        execution_profile=GraphitiExecutionProfile.EVALUATION,
        framework=framework,
        model=model,
        embedding=embedding,
        prompt=GRAPHITI_PROMPT_COMPONENT,
        output_schema=GRAPHITI_ADAPTER_OUTPUT_SCHEMA_COMPONENT,
        code=GRAPHITI_ADAPTER_CODE_COMPONENT,
        normalisation=GRAPHITI_ADAPTER_NORMALISATION_COMPONENT,
        temporal_policy=GRAPHITI_ADAPTER_TEMPORAL_COMPONENT,
        adapter_policy=GRAPHITI_ADAPTER_POLICY_COMPONENT,
        extractor_contract_id=contract.contract_id,
        extractor_contract_digest=contract.digest,
        workspace_policy=online_policy,
        fixture_case=None,
        real_runtime_authority=_real_authority(),
        idempotency_key="real-evaluation-placeholder-v1",
    )
    configuration.require_execution_authorized()
    production = replace(
        configuration,
        execution_profile=GraphitiExecutionProfile.PRODUCTION,
        idempotency_key="real-production-placeholder-v1",
    )
    with pytest.raises(GraphitiRuntimeNotAuthorized, match="EVALUATION"):
        production.require_execution_authorized()


def test_manifest_is_digest_only_and_attempt_is_exact(tmp_path) -> None:
    state = seed_extraction_fixture(tmp_path)
    attempt = fake_attempt(state)
    value = attempt.manifest.canonical_value()
    assert value["passages"]
    assert all("text" not in item for item in value["passages"])
    rendered = attempt.canonical_bytes.decode("utf-8")
    assert state.input_binding.passages[0].require_text() not in rendered
    assert state.input_binding.passages[1].require_text() not in rendered
    assert attempt.manifest.input_binding_digest == state.input_binding.digest
    assert attempt.manifest.requested_run_version_id == attempt.extraction_request.run_version_id

    with pytest.raises(GraphitiAdapterContractError, match="manifest configuration digest"):
        replace(
            attempt,
            manifest=replace(
                attempt.manifest,
                configuration_digest=_digest("different-config"),
            ),
        )


def test_attempt_chain_and_read_policy_are_closed(tmp_path) -> None:
    state = seed_extraction_fixture(tmp_path)
    attempt = fake_attempt(state)
    with pytest.raises(GraphitiAdapterContractError, match="predecessor"):
        replace(attempt, attempt_number=2)
    with pytest.raises(GraphitiAdapterContractError, match="cannot name"):
        replace(
            attempt,
            expected_previous_attempt_id=attempt.attempt_id,
        )
    with pytest.raises(GraphitiAdapterContractError, match="distinct scopes"):
        GraphitiAdapterReadPolicy(
            policy_id="graphiti-adapter-read-v1",
            purpose="graphiti.adapter.audit",
            attempt_required_scope="authority.graphiti.read",
            configuration_required_scope="authority.graphiti.read",
            replay_required_scope="authority.graphiti.read",
            allowed_principal_ids=frozenset({"principal.alpha"}),
        )


def test_configuration_components_are_fixed_and_versioned() -> None:
    components = (
        GRAPHITI_FRAMEWORK_PLACEHOLDER_COMPONENT,
        GRAPHITI_NO_MODEL_COMPONENT,
        GRAPHITI_NO_EMBEDDING_COMPONENT,
        GRAPHITI_PROMPT_COMPONENT,
        GRAPHITI_ADAPTER_OUTPUT_SCHEMA_COMPONENT,
        GRAPHITI_ADAPTER_CODE_COMPONENT,
        GRAPHITI_ADAPTER_NORMALISATION_COMPONENT,
        GRAPHITI_ADAPTER_TEMPORAL_COMPONENT,
        GRAPHITI_ADAPTER_POLICY_COMPONENT,
    )
    assert len({item.component_id for item in components}) == len(components)
    assert all(item.contract_digest.startswith("sha256:") for item in components)
