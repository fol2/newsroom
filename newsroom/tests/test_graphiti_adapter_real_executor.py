from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

from newsroom.authority._graphiti_adapter_boundary import _GraphitiAdapterBoundary
from newsroom.authority.canonical import digest_canonical
from newsroom.extraction.types import VersionedExtractionComponent
from newsroom.graphiti_adapter import (
    DeterministicFakeGraphitiAdapter,
    GraphitiAdapterConfiguration,
    GraphitiAdapterConfigurationId,
    GraphitiAdapterContractError,
    GraphitiAttemptId,
    GraphitiAttemptRequest,
    GraphitiCleanupReceiptId,
    GraphitiCredentialClass,
    GraphitiEgressPolicy,
    GraphitiExecutionProfile,
    GraphitiInputManifest,
    GraphitiInputManifestId,
    GraphitiRuntimeMode,
    GraphitiRuntimeNotAuthorized,
    GraphitiWorkspaceId,
    GraphitiWorkspacePolicy,
    GraphitiWorkspacePolicyId,
    REAL_GRAPHITI_RUNTIME_ENABLED,
    RealGraphitiRuntimeAuthority,
)
from newsroom.graphiti_adapter.contracts import (
    GRAPHITI_ADAPTER_CODE_COMPONENT,
    GRAPHITI_ADAPTER_NORMALISATION_COMPONENT,
    GRAPHITI_ADAPTER_OUTPUT_SCHEMA_COMPONENT,
    GRAPHITI_ADAPTER_POLICY_COMPONENT,
    GRAPHITI_ADAPTER_TEMPORAL_COMPONENT,
    GRAPHITI_PROMPT_COMPONENT,
)
from newsroom.graphiti_adapter.evaluation_packet import (
    EVALUATION_GRAPHITI_PACKET,
    EVALUATION_WORKSPACE_POLICY,
    GRAPHITI_CHAT_MODEL,
    GRAPHITI_CORE_RELEASE,
    GRAPHITI_EMBEDDING_MODEL,
)
from newsroom.graphiti_adapter.real import RealGraphitiAdapter

from .extraction_4a_helpers import contract_request, run_request, seed_extraction_fixture
from .graphiti_adapter_4d_helpers import FAKE_CONFIGURATION_ID

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVALUATION_CONFIGURATION_ID = GraphitiAdapterConfigurationId.parse(
    "00000000-0000-4000-8000-000000004930"
)
EVALUATION_MANIFEST_ID = GraphitiInputManifestId.parse(
    "00000000-0000-4000-8000-000000004931"
)
EVALUATION_WORKSPACE_ID = GraphitiWorkspaceId.parse(
    "00000000-0000-4000-8000-000000004932"
)
EVALUATION_CLEANUP_ID = GraphitiCleanupReceiptId.parse(
    "00000000-0000-4000-8000-000000004933"
)
EVALUATION_ATTEMPT_ID = GraphitiAttemptId.parse(
    "00000000-0000-4000-8000-000000004934"
)


def _digest(label: str) -> str:
    return digest_canonical({"contract": label})


def _placeholder_authority() -> RealGraphitiRuntimeAuthority:
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


def _real_configuration(
    contract,
    *,
    execution_profile: GraphitiExecutionProfile = GraphitiExecutionProfile.EVALUATION,
    authority: RealGraphitiRuntimeAuthority | None = None,
    workspace_policy: GraphitiWorkspacePolicy | None = None,
    framework_version: str = GRAPHITI_CORE_RELEASE,
    model_version: str = GRAPHITI_CHAT_MODEL,
    embedding_version: str = GRAPHITI_EMBEDDING_MODEL,
) -> GraphitiAdapterConfiguration:
    digest = _digest("evaluation-component")
    return GraphitiAdapterConfiguration(
        configuration_id=EVALUATION_CONFIGURATION_ID,
        runtime_mode=GraphitiRuntimeMode.REAL_GRAPHITI,
        execution_profile=execution_profile,
        framework=VersionedExtractionComponent(
            "graphiti.framework", framework_version, digest
        ),
        model=VersionedExtractionComponent("graphiti.model", model_version, digest),
        embedding=VersionedExtractionComponent(
            "graphiti.embedding", embedding_version, digest
        ),
        prompt=GRAPHITI_PROMPT_COMPONENT,
        output_schema=GRAPHITI_ADAPTER_OUTPUT_SCHEMA_COMPONENT,
        code=GRAPHITI_ADAPTER_CODE_COMPONENT,
        normalisation=GRAPHITI_ADAPTER_NORMALISATION_COMPONENT,
        temporal_policy=GRAPHITI_ADAPTER_TEMPORAL_COMPONENT,
        adapter_policy=GRAPHITI_ADAPTER_POLICY_COMPONENT,
        extractor_contract_id=contract.contract_id,
        extractor_contract_digest=contract.digest,
        workspace_policy=workspace_policy or EVALUATION_WORKSPACE_POLICY,
        fixture_case=None,
        real_runtime_authority=authority or EVALUATION_GRAPHITI_PACKET,
        idempotency_key="evaluation-real-adapter-v1",
    )


def _real_attempt(
    tmp_path: Path,
    *,
    execution_profile: GraphitiExecutionProfile = GraphitiExecutionProfile.EVALUATION,
    authority: RealGraphitiRuntimeAuthority | None = None,
    workspace_policy: GraphitiWorkspacePolicy | None = None,
) -> GraphitiAttemptRequest:
    state = seed_extraction_fixture(tmp_path / "authority")
    contract = contract_request()
    request = run_request(state, contract_id=contract.contract_id)
    configuration = _real_configuration(
        contract,
        execution_profile=execution_profile,
        authority=authority,
        workspace_policy=workspace_policy,
    )
    manifest = GraphitiInputManifest.from_run_request(
        manifest_id=EVALUATION_MANIFEST_ID,
        configuration=configuration,
        contract=contract,
        request=request,
    )
    return GraphitiAttemptRequest(
        attempt_id=EVALUATION_ATTEMPT_ID,
        attempt_number=1,
        expected_previous_attempt_id=None,
        configuration=configuration,
        workspace_id=EVALUATION_WORKSPACE_ID,
        cleanup_receipt_id=EVALUATION_CLEANUP_ID,
        manifest=manifest,
        extraction_contract=contract,
        extraction_request=request,
        replay_source=None,
        idempotency_key="evaluation-real-attempt-v1",
    )


def test_flag_is_true_for_evaluation_and_graphiti_core_is_an_optional_extra() -> None:
    assert REAL_GRAPHITI_RUNTIME_ENABLED is True
    pyproject = (_REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "graphiti-core==0.29.3" in pyproject
    assert "[project.optional-dependencies]" in pyproject
    lock = (_REPOSITORY_ROOT / "uv.lock").read_text(encoding="utf-8")
    assert 'name = "graphiti-core"' in lock
    assert 'version = "0.29.3"' in lock


def test_openrouter_generic_client_uses_json_object_mode() -> None:
    from newsroom.graphiti_adapter.real import _add_episode

    source = inspect.getsource(_add_episode)
    assert 'structured_output_mode="json_object"' in source
    assert "OpenAIGenericClient" in source


def test_else_branch_constructs_real_adapter_instead_of_unreachable_assertion() -> None:
    source = inspect.getsource(_GraphitiAdapterBoundary._execute_attempt_locked)
    assert "unreachable real Graphiti execution path" not in source
    assert "require_execution_authorized()" in source
    assert "adapter = RealGraphitiAdapter(" in source
    assert inspect.signature(RealGraphitiAdapter.execute) == inspect.signature(
        DeterministicFakeGraphitiAdapter.execute
    )


def test_placeholder_packet_still_fails_closed(tmp_path: Path) -> None:
    policy = GraphitiWorkspacePolicy(
        policy_id=GraphitiWorkspacePolicyId.parse(
            "00000000-0000-4000-8000-000000004935"
        ),
        policy_version="graphiti-disposable-workspace-v1",
        namespace_prefix="graphiti-real-evaluation",
        max_workspace_bytes=1024 * 1024,
        max_private_nodes=100,
        max_private_relations=100,
        egress_policy=GraphitiEgressPolicy.APPROVED_PROVIDER_ONLY,
        credential_class=GraphitiCredentialClass.PROPOSAL_WORKSPACE_ONLY,
    )
    attempt = _real_attempt(
        tmp_path,
        authority=_placeholder_authority(),
        workspace_policy=policy,
    )
    attempt.configuration.require_execution_authorized()
    with pytest.raises(GraphitiAdapterContractError, match="EVALUATION OpenRouter packet pins"):
        RealGraphitiAdapter().execute(
            attempt=attempt,
            workspace_root=(tmp_path / "workspace").resolve(),
        )
    assert "graphiti_core" not in sys.modules


def test_evaluation_packet_is_the_only_authorised_real_profile(tmp_path: Path) -> None:
    assert REAL_GRAPHITI_RUNTIME_ENABLED is True
    production = _real_attempt(
        tmp_path, execution_profile=GraphitiExecutionProfile.PRODUCTION
    )
    with pytest.raises(GraphitiAdapterContractError, match="EVALUATION"):
        RealGraphitiAdapter().execute(
            attempt=production,
            workspace_root=(tmp_path / "workspace").resolve(),
        )
    with pytest.raises(GraphitiRuntimeNotAuthorized, match="EVALUATION"):
        production.configuration.require_execution_authorized()


def test_authorised_evaluation_attempt_does_not_import_graphiti_core(tmp_path: Path) -> None:
    assert "graphiti_core" not in sys.modules
    from newsroom.graphiti_adapter.evaluation_attempt import evaluation_attempt_for
    from newsroom.graphiti_adapter.evaluation_packet import GRAPHITI_WORKSPACE_GROUP

    attempt = evaluation_attempt_for(("香港天文台發出強烈季候風信號。",))
    attempt.configuration.require_execution_authorized()
    assert attempt.configuration.workspace_policy.namespace_prefix == GRAPHITI_WORKSPACE_GROUP
    assert "graphiti_core" not in sys.modules
    assert REAL_GRAPHITI_RUNTIME_ENABLED is True
