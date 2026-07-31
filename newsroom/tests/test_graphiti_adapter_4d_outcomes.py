from __future__ import annotations

from contextlib import closing
from dataclasses import replace
import sqlite3

import pytest

from newsroom.authority.canonical import digest_canonical
from newsroom.extraction import (
    ExtractionFailureCode,
    ExtractionOutcome,
    FixtureExtractionCase,
    VersionedExtractionComponent,
)
from newsroom.graphiti_adapter import (
    DeterministicFakeGraphitiAdapter,
    GraphitiAdapterConfiguration,
    GraphitiAdapterConfigurationId,
    GraphitiAdapterOutcome,
    GraphitiCleanupReason,
    GraphitiCredentialClass,
    GraphitiEgressPolicy,
    GraphitiExecutionProfile,
    GraphitiRuntimeMode,
    GraphitiAdapterStateError,
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
    GRAPHITI_PROMPT_COMPONENT,
)

from .extraction_4a_helpers import extraction_proof, open_extraction_system
from .graphiti_adapter_4d_authority_helpers import (
    fake_attempt,
    open_graphiti_system,
    seed_graphiti_authority_fixture,
)


def _digest(label: str) -> str:
    return digest_canonical({"contract": label})


def _real_configuration(contract) -> GraphitiAdapterConfiguration:
    workspace = GraphitiWorkspacePolicy(
        policy_id=GraphitiWorkspacePolicyId.parse(
            "00000000-0000-4000-8000-000000004881"
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
        "graphiti.framework", "placeholder-release", _digest("framework")
    )
    model = VersionedExtractionComponent(
        "graphiti.model", "placeholder-release", _digest("model")
    )
    embedding = VersionedExtractionComponent(
        "graphiti.embedding", "placeholder-release", _digest("embedding")
    )
    authority = RealGraphitiRuntimeAuthority(
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
    return GraphitiAdapterConfiguration(
        configuration_id=GraphitiAdapterConfigurationId.parse(
            "00000000-0000-4000-8000-000000004882"
        ),
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
        workspace_policy=workspace,
        fixture_case=None,
        real_runtime_authority=authority,
        idempotency_key="increment-4d-real-evaluation-placeholder-v1",
    )


@pytest.mark.parametrize(
    ("fixture_case", "expected", "failure_code", "has_output"),
    (
        (
            FixtureExtractionCase.RETRYABLE_FAILURE,
            GraphitiAdapterOutcome.FAILED,
            ExtractionFailureCode.FIXTURE_RETRYABLE,
            False,
        ),
        (
            FixtureExtractionCase.BLOCKING_FAILURE,
            GraphitiAdapterOutcome.PROVIDER_REJECTED,
            ExtractionFailureCode.FIXTURE_BLOCKED,
            False,
        ),
        (
            FixtureExtractionCase.INVALID_OUTPUT,
            GraphitiAdapterOutcome.MALFORMED_OUTPUT,
            ExtractionFailureCode.OUTPUT_SCHEMA_INVALID,
            True,
        ),
    ),
)
def test_authority_retains_honest_noncomplete_outcomes_without_proposal_admission(
    tmp_path, fixture_case, expected, failure_code, has_output
) -> None:
    state = seed_graphiti_authority_fixture(
        tmp_path / "authority", fixture_case=fixture_case
    )
    request = fake_attempt(state, fixture_case=fixture_case)
    workspace_root = (tmp_path / "workspace").resolve()
    with open_graphiti_system(state, workspace_root=workspace_root) as system:
        system.graphiti.register_configuration(
            request.configuration, proof=extraction_proof()
        )
        retained = system.graphiti.execute_attempt(
            request, proof=extraction_proof()
        )
        replayed = system.graphiti.execute_attempt(
            request, proof=extraction_proof()
        )

    assert retained.outcome is expected
    assert retained.failure_code == failure_code.value
    assert (retained.output_id is not None) is has_output
    assert retained.proposal_set_id is None
    assert replayed == replace(retained, replayed=True)
    assert retained.cleanup_receipt.workspace_absent is True
    assert not workspace_root.exists() or not any(workspace_root.iterdir())
    with closing(sqlite3.connect(state.database)) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM entity_resolution_decisions"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM editorial_relation_decisions"
        ).fetchone()[0] == 0


def test_policy_blocked_outcome_is_retained_without_output_or_proposals(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = seed_graphiti_authority_fixture(
        tmp_path / "authority", fixture_case=FixtureExtractionCase.BLOCKING_FAILURE
    )
    request = fake_attempt(
        state, fixture_case=FixtureExtractionCase.BLOCKING_FAILURE
    )
    workspace_root = (tmp_path / "workspace").resolve()
    original = DeterministicFakeGraphitiAdapter.execute

    def policy_blocked(self, *, attempt, workspace_root):
        execution = original(self, attempt=attempt, workspace_root=workspace_root)
        produced = replace(
            execution.produced,
            failure_code=ExtractionFailureCode.POLICY_BLOCKED,
        )
        return replace(
            execution,
            outcome=GraphitiAdapterOutcome.POLICY_BLOCKED,
            failure_code=ExtractionFailureCode.POLICY_BLOCKED.value,
            produced=produced,
            cleanup_receipt=replace(
                execution.cleanup_receipt,
                reason=GraphitiCleanupReason.POLICY_BLOCKED,
            ),
        )

    monkeypatch.setattr(DeterministicFakeGraphitiAdapter, "execute", policy_blocked)
    with open_graphiti_system(state, workspace_root=workspace_root) as system:
        system.graphiti.register_configuration(
            request.configuration, proof=extraction_proof()
        )
        retained = system.graphiti.execute_attempt(
            request, proof=extraction_proof()
        )

    assert retained.outcome is GraphitiAdapterOutcome.POLICY_BLOCKED
    assert retained.failure_code == ExtractionFailureCode.POLICY_BLOCKED.value
    assert retained.output_id is None
    assert retained.proposal_set_id is None
    assert retained.cleanup_receipt.reason is GraphitiCleanupReason.POLICY_BLOCKED


def test_preexisting_extraction_without_attempt_surfaces_ambiguous_effect(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = seed_graphiti_authority_fixture(tmp_path / "authority")
    request = fake_attempt(state)
    workspace_root = (tmp_path / "workspace").resolve()
    with open_extraction_system(state) as extraction:
        extraction.extraction.execute(
            request.extraction_request, proof=extraction_proof()
        )
    with open_graphiti_system(state, workspace_root=workspace_root) as system:
        system.graphiti.register_configuration(
            request.configuration, proof=extraction_proof()
        )

    def forbidden_execute(*_args, **_kwargs):
        raise AssertionError("ambiguous effect must not rerun the private workspace")

    monkeypatch.setattr(
        DeterministicFakeGraphitiAdapter, "execute", forbidden_execute
    )
    from newsroom.graphiti_adapter import GraphitiAdapterAmbiguousEffect

    with open_graphiti_system(state, workspace_root=workspace_root) as system:
        with pytest.raises(
            GraphitiAdapterAmbiguousEffect,
            match="explicit reconciliation is required",
        ):
            system.graphiti.execute_attempt(
                request, proof=extraction_proof()
            )
    with closing(sqlite3.connect(state.database)) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM extraction_run_versions WHERE run_version_id=?",
            (str(request.extraction_request.run_version_id),),
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM graphiti_adapter_attempts WHERE attempt_id=?",
            (str(request.attempt_id),),
        ).fetchone()[0] == 0
    assert not workspace_root.exists()


def test_public_authority_rejects_unapproved_real_runtime_workspace_configuration(
    tmp_path,
) -> None:
    state = seed_graphiti_authority_fixture(tmp_path / "authority")
    request = fake_attempt(state)
    configuration = _real_configuration(request.extraction_contract)
    workspace_root = (tmp_path / "workspace").resolve()
    with open_graphiti_system(state, workspace_root=workspace_root) as system:
        with pytest.raises(
            GraphitiAdapterStateError,
            match="workspace policy is not retained",
        ):
            system.graphiti.register_configuration(
                configuration, proof=extraction_proof()
            )
    with closing(sqlite3.connect(state.database)) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM graphiti_adapter_configurations "
            "WHERE configuration_id=?",
            (str(configuration.configuration_id),),
        ).fetchone()[0] == 0
