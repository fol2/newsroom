from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from newsroom.authority import StaticAuthorizer
from newsroom.authority.graphiti_adapter_system import (
    open_governed_graphiti_adapter_authority_system,
)
from newsroom.authority._extraction_system import (
    open_governed_extraction_authority_system,
)
from newsroom.extraction.types import (
    ExtractionOutputId,
    ExtractionRunId,
    ExtractionRunVersionId,
    FixtureExtractionCase,
    ProposalSetId,
)
from newsroom.graphiti_adapter import (
    GraphitiAdapterConfigurationId,
    GraphitiAdapterReadPolicy,
    GraphitiAttemptId,
    GraphitiAttemptRecord,
    GraphitiAttemptRequest,
    GraphitiCleanupReceiptId,
    GraphitiInputManifest,
    GraphitiInputManifestId,
    GraphitiReplayApprovalRequest,
    GraphitiReplayEligibility,
    GraphitiReplaySource,
    GraphitiReplaySourceId,
    GraphitiWorkspaceId,
    qualification_configuration,
    replay_configuration,
)

from .extraction_4a_helpers import (
    ExtractionFixtureState,
    contract_request,
    extraction_authenticator,
    extraction_authorizer,
    extraction_proof,
    extraction_read_policy,
    extraction_scopes,
    open_extraction_system,
    run_request,
    seed_extraction_fixture,
    seed_homonym_extraction_fixture,
)
from .graphiti_adapter_4d_helpers import fake_attempt, replay_payload_digest
from .source_3a_helpers import SOURCE_NOW


GRAPHITI_SCOPES = frozenset(
    {
        "authority.graphiti.configuration",
        "authority.graphiti.execute",
        "authority.graphiti.replay.approve",
        "authority.graphiti.read_configuration",
        "authority.graphiti.read_attempts",
        "authority.graphiti.read_replay",
    }
)


def graphiti_authorizer(*, scopes: frozenset[str] | None = None) -> StaticAuthorizer:
    return StaticAuthorizer(
        policy_version="graphiti-adapter-authority-authz-v1",
        grants_by_principal={
            "principal.alpha": (
                GRAPHITI_SCOPES | extraction_scopes()
                if scopes is None
                else scopes
            )
        },
    )


def graphiti_read_policy() -> GraphitiAdapterReadPolicy:
    return GraphitiAdapterReadPolicy(
        policy_id="increment-4d-graphiti-read-v1",
        purpose="graphiti.adapter.authority.audit",
        attempt_required_scope="authority.graphiti.read_attempts",
        configuration_required_scope="authority.graphiti.read_configuration",
        replay_required_scope="authority.graphiti.read_replay",
        allowed_principal_ids=frozenset({"principal.alpha"}),
        max_results=100,
    )


def seed_graphiti_authority_fixture(
    root: Path,
    *,
    fixture_case=None,
) -> ExtractionFixtureState:
    from newsroom.extraction.types import FixtureExtractionCase

    selected = (
        FixtureExtractionCase.BILINGUAL_COMPLETE
        if fixture_case is None
        else fixture_case
    )
    state = (
        seed_homonym_extraction_fixture(root)
        if selected is FixtureExtractionCase.BILINGUAL_HOMONYM
        else seed_extraction_fixture(root)
    )
    with open_extraction_system(state) as extraction:
        extraction.extraction.register_contract(
            contract_request(fixture_case=selected), proof=extraction_proof()
        )
    return state


def open_graphiti_system(
    state: ExtractionFixtureState,
    *,
    workspace_root: Path,
    scopes: frozenset[str] | None = None,
    clock=lambda: SOURCE_NOW,
):
    return open_governed_graphiti_adapter_authority_system(
        path=state.database,
        workspace_root=workspace_root.resolve(),
        registry=state.commands,
        payload_schemas=state.schemas,
        authenticator=extraction_authenticator(),
        authorizer=graphiti_authorizer(scopes=scopes),
        read_policy=graphiti_read_policy(),
        clock=clock,
    )


def approval_from_authority(
    state: ExtractionFixtureState,
    attempt,
    *,
    replay_source_id: GraphitiReplaySourceId = GraphitiReplaySourceId.parse(
        "00000000-0000-4000-8000-000000004951"
    ),
    key: str = "increment-4d-replay-approval-v1",
) -> GraphitiReplayApprovalRequest:
    import sqlite3

    from newsroom.authority.canonical import digest_canonical
    from newsroom.extraction.models import ProposalDraft

    from newsroom.authority._extraction_system import (
        open_governed_extraction_authority_system,
    )
    from newsroom.graphiti_adapter.policy import (
        merge_graphiti_adapter_authority_registries,
    )
    from .extraction_4a_helpers import (
        extraction_authorizer,
        extraction_read_policy,
    )

    commands, schemas = merge_graphiti_adapter_authority_registries(
        command_registry=state.commands,
        payload_schemas=state.schemas,
    )
    with open_governed_extraction_authority_system(
        path=state.database,
        registry=commands,
        payload_schemas=schemas,
        authenticator=extraction_authenticator(),
        authorizer=extraction_authorizer(),
        read_policy=extraction_read_policy(),
        clock=lambda: SOURCE_NOW,
    ) as extraction:
        metadata = extraction.extraction.metadata(
            attempt.run_version_id, proof=extraction_proof()
        )
        assert metadata.output is not None
        proposals = extraction.extraction.proposals(
            attempt.run_version_id, proof=extraction_proof()
        )
    conn = sqlite3.connect(state.database)
    conn.row_factory = sqlite3.Row
    try:
        proposal_set_digest = None
        if attempt.proposal_set_id is not None:
            row = conn.execute(
                "SELECT canonical_digest FROM extraction_proposal_sets "
                "WHERE proposal_set_id=?",
                (str(attempt.proposal_set_id),),
            ).fetchone()
            assert row is not None
            proposal_set_digest = str(row["canonical_digest"])
    finally:
        conn.close()
    drafts = tuple(
        ProposalDraft(
            local_id=item.local_id,
            kind=item.kind,
            subject_placeholder=item.subject_placeholder,
            object_placeholder=item.object_placeholder,
            predicate_hint=item.predicate_hint,
            confidence_basis_points=item.confidence_basis_points,
            uncertainty_codes=item.uncertainty_codes,
            rationale_codes=item.rationale_codes,
            evidence=item.evidence,
        )
        for item in proposals
    )
    replay_digest = digest_canonical(
        {
            "outcome": metadata.outcome.value,
            "failure_code": metadata.failure_code.value,
            "validation": metadata.output.validation.value,
            "raw_output_digest": metadata.output.canonical_digest,
            "proposals": [item.canonical_value() for item in drafts],
            "usage": metadata.usage.canonical_value(),
        }
    )
    eligibility = {
        "COMPLETE": GraphitiReplayEligibility.COMPLETE,
        "PARTIAL": GraphitiReplayEligibility.PARTIAL,
        "MALFORMED_OUTPUT": GraphitiReplayEligibility.MALFORMED_OUTPUT,
    }[attempt.outcome.value]
    return GraphitiReplayApprovalRequest(
        replay_source_id=replay_source_id,
        source_attempt_id=attempt.attempt_id,
        source_run_version_id=attempt.run_version_id,
        source_output_id=attempt.output_id,
        source_proposal_set_id=attempt.proposal_set_id,
        eligibility=eligibility,
        expected_output_canonical_digest=metadata.output.canonical_digest,
        expected_proposal_set_canonical_digest=proposal_set_digest,
        expected_replay_payload_digest=replay_digest,
        idempotency_key=key,
    )


def replay_attempt_for_next_version(
    state: ExtractionFixtureState,
    source_attempt: GraphitiAttemptRecord,
    source: GraphitiReplaySource,
) -> GraphitiAttemptRequest:
    request = run_request(
        state,
        run_id=source_attempt.run_id,
        run_version_id=ExtractionRunVersionId.parse(
            "00000000-0000-4000-8000-000000004962"
        ),
        version_number=source_attempt.attempt_number + 1,
        previous=source_attempt.run_version_id,
        key="increment-4d-replay-run-v2",
    )
    contract = contract_request(
        fixture_case=FixtureExtractionCase.BILINGUAL_PARTIAL
    )
    configuration = replay_configuration(
        configuration_id=source_configuration_id(),
        contract=contract,
    )
    manifest = GraphitiInputManifest.from_run_request(
        manifest_id=GraphitiInputManifestId.parse(
            "00000000-0000-4000-8000-000000004963"
        ),
        configuration=configuration,
        contract=contract,
        request=request,
    )
    return GraphitiAttemptRequest(
        attempt_id=GraphitiAttemptId.parse(
            "00000000-0000-4000-8000-000000004964"
        ),
        attempt_number=source_attempt.attempt_number + 1,
        expected_previous_attempt_id=source_attempt.attempt_id,
        configuration=configuration,
        workspace_id=GraphitiWorkspaceId.parse(
            "00000000-0000-4000-8000-000000004965"
        ),
        cleanup_receipt_id=GraphitiCleanupReceiptId.parse(
            "00000000-0000-4000-8000-000000004966"
        ),
        manifest=manifest,
        extraction_contract=contract,
        extraction_request=request,
        replay_source=source,
        idempotency_key="increment-4d-approved-replay-attempt-v2",
    )


def retry_fake_attempt(
    state: ExtractionFixtureState,
    source_attempt: GraphitiAttemptRecord,
    *,
    timeout_ms: int = 10_000,
) -> GraphitiAttemptRequest:
    contract = contract_request()
    request = run_request(
        state,
        run_id=source_attempt.run_id,
        run_version_id=ExtractionRunVersionId.parse(
            "00000000-0000-4000-8000-000000004972"
        ),
        version_number=source_attempt.attempt_number + 1,
        previous=source_attempt.run_version_id,
        contract_id=contract.contract_id,
        timeout_ms=timeout_ms,
        key="increment-4d-fake-retry-run-v2",
    )
    configuration = qualification_configuration(
        configuration_id=GraphitiAdapterConfigurationId.parse(
            "00000000-0000-4000-8000-000000004901"
        ),
        contract=contract,
        fixture_case=FixtureExtractionCase.BILINGUAL_COMPLETE,
    )
    manifest = GraphitiInputManifest.from_run_request(
        manifest_id=GraphitiInputManifestId.parse(
            "00000000-0000-4000-8000-000000004973"
        ),
        configuration=configuration,
        contract=contract,
        request=request,
    )
    return GraphitiAttemptRequest(
        attempt_id=GraphitiAttemptId.parse(
            "00000000-0000-4000-8000-000000004974"
        ),
        attempt_number=source_attempt.attempt_number + 1,
        expected_previous_attempt_id=source_attempt.attempt_id,
        configuration=configuration,
        workspace_id=GraphitiWorkspaceId.parse(
            "00000000-0000-4000-8000-000000004975"
        ),
        cleanup_receipt_id=GraphitiCleanupReceiptId.parse(
            "00000000-0000-4000-8000-000000004976"
        ),
        manifest=manifest,
        extraction_contract=contract,
        extraction_request=request,
        replay_source=None,
        idempotency_key="increment-4d-fake-retry-attempt-v2",
    )



def replay_attempt_for_new_budgeted_run(
    state: ExtractionFixtureState,
    source: GraphitiReplaySource,
) -> GraphitiAttemptRequest:
    run_id = ExtractionRunId.parse("00000000-0000-4000-8000-000000004971")
    run_version_id = ExtractionRunVersionId.parse(
        "00000000-0000-4000-8000-000000004972"
    )
    request = run_request(
        state,
        run_id=run_id,
        run_version_id=run_version_id,
        timeout_ms=20_000,
        key="increment-4d-complete-replay-run-v1",
    )
    contract = contract_request()
    configuration = replay_configuration(
        configuration_id=GraphitiAdapterConfigurationId.parse(
            "00000000-0000-4000-8000-000000004973"
        ),
        contract=contract,
        idempotency_key="increment-4d-complete-replay-config-v1",
    )
    manifest = GraphitiInputManifest.from_run_request(
        manifest_id=GraphitiInputManifestId.parse(
            "00000000-0000-4000-8000-000000004974"
        ),
        configuration=configuration,
        contract=contract,
        request=request,
    )
    return GraphitiAttemptRequest(
        attempt_id=GraphitiAttemptId.parse(
            "00000000-0000-4000-8000-000000004975"
        ),
        attempt_number=1,
        expected_previous_attempt_id=None,
        configuration=configuration,
        workspace_id=GraphitiWorkspaceId.parse(
            "00000000-0000-4000-8000-000000004976"
        ),
        cleanup_receipt_id=GraphitiCleanupReceiptId.parse(
            "00000000-0000-4000-8000-000000004977"
        ),
        manifest=manifest,
        extraction_contract=contract,
        extraction_request=request,
        replay_source=source,
        idempotency_key="increment-4d-complete-replay-attempt-v1",
    )

def source_configuration_id():
    from newsroom.graphiti_adapter import GraphitiAdapterConfigurationId

    return GraphitiAdapterConfigurationId.parse(
        "00000000-0000-4000-8000-000000004967"
    )


__all__ = [
    "GRAPHITI_SCOPES",
    "approval_from_authority",
    "fake_attempt",
    "graphiti_authorizer",
    "graphiti_read_policy",
    "open_graphiti_system",
    "replay_attempt_for_new_budgeted_run",
    "replay_attempt_for_next_version",
    "retry_fake_attempt",
    "seed_graphiti_authority_fixture",
    "source_configuration_id",
]
