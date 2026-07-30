from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from newsroom.authority.canonical import digest_canonical
from newsroom.authority.types import UtcTimestamp
from newsroom.extraction.models import ProducedExtraction
from newsroom.extraction.producer import DeterministicFixtureExtractor
from newsroom.extraction.types import (
    ExtractionOutputId,
    ExtractionOutcome,
    FixtureExtractionCase,
    ProposalSetId,
)
from newsroom.graphiti_adapter import (
    ApprovedReplayBundle,
    GraphitiAdapterConfigurationId,
    GraphitiAttemptId,
    GraphitiAttemptRequest,
    GraphitiCleanupReceiptId,
    GraphitiInputManifest,
    GraphitiInputManifestId,
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
    run_request,
)

FAKE_CONFIGURATION_ID = GraphitiAdapterConfigurationId.parse(
    "00000000-0000-4000-8000-000000004901"
)
FAKE_MANIFEST_ID = GraphitiInputManifestId.parse(
    "00000000-0000-4000-8000-000000004902"
)
FAKE_WORKSPACE_ID = GraphitiWorkspaceId.parse(
    "00000000-0000-4000-8000-000000004903"
)
FAKE_CLEANUP_ID = GraphitiCleanupReceiptId.parse(
    "00000000-0000-4000-8000-000000004904"
)
FAKE_ATTEMPT_ID = GraphitiAttemptId.parse(
    "00000000-0000-4000-8000-000000004905"
)
REPLAY_SOURCE_ID = GraphitiReplaySourceId.parse(
    "00000000-0000-4000-8000-000000004906"
)
REPLAY_CONFIGURATION_ID = GraphitiAdapterConfigurationId.parse(
    "00000000-0000-4000-8000-000000004907"
)
REPLAY_MANIFEST_ID = GraphitiInputManifestId.parse(
    "00000000-0000-4000-8000-000000004908"
)
REPLAY_WORKSPACE_ID = GraphitiWorkspaceId.parse(
    "00000000-0000-4000-8000-000000004909"
)
REPLAY_CLEANUP_ID = GraphitiCleanupReceiptId.parse(
    "00000000-0000-4000-8000-000000004910"
)
REPLAY_ATTEMPT_ID = GraphitiAttemptId.parse(
    "00000000-0000-4000-8000-000000004911"
)
SOURCE_OUTPUT_ID = ExtractionOutputId.parse(
    "00000000-0000-4000-8000-000000004912"
)
SOURCE_PROPOSAL_SET_ID = ProposalSetId.parse(
    "00000000-0000-4000-8000-000000004913"
)
ADAPTER_NOW = UtcTimestamp.parse("2042-03-12T10:00:00.000000Z")


def fake_attempt(
    state: ExtractionFixtureState,
    *,
    fixture_case: FixtureExtractionCase = FixtureExtractionCase.BILINGUAL_COMPLETE,
    attempt_id: GraphitiAttemptId = FAKE_ATTEMPT_ID,
    workspace_id: GraphitiWorkspaceId = FAKE_WORKSPACE_ID,
    cleanup_receipt_id: GraphitiCleanupReceiptId = FAKE_CLEANUP_ID,
) -> GraphitiAttemptRequest:
    contract = contract_request(fixture_case=fixture_case)
    request = run_request(state, contract_id=contract.contract_id)
    configuration = qualification_configuration(
        configuration_id=FAKE_CONFIGURATION_ID,
        contract=contract,
        fixture_case=fixture_case,
    )
    manifest = GraphitiInputManifest.from_run_request(
        manifest_id=FAKE_MANIFEST_ID,
        configuration=configuration,
        contract=contract,
        request=request,
    )
    return GraphitiAttemptRequest(
        attempt_id=attempt_id,
        attempt_number=1,
        expected_previous_attempt_id=None,
        configuration=configuration,
        workspace_id=workspace_id,
        cleanup_receipt_id=cleanup_receipt_id,
        manifest=manifest,
        extraction_contract=contract,
        extraction_request=request,
        replay_source=None,
        idempotency_key="increment-4d-fake-attempt-v1",
    )


def produced_for(attempt: GraphitiAttemptRequest) -> ProducedExtraction:
    return DeterministicFixtureExtractor().produce(
        contract=attempt.extraction_contract,
        request=attempt.extraction_request,
    )


def replay_payload_digest(produced: ProducedExtraction) -> str:
    return digest_canonical(
        {
            "outcome": produced.outcome.value,
            "failure_code": produced.failure_code.value,
            "validation": (
                None if produced.validation is None else produced.validation.value
            ),
            "raw_output_digest": produced.raw_output_digest,
            "proposals": [item.canonical_value() for item in produced.proposals],
            "usage": produced.usage.canonical_value(),
        }
    )


def replay_source_for(
    source_attempt: GraphitiAttemptRequest,
    produced: ProducedExtraction,
) -> GraphitiReplaySource:
    eligibility = {
        ExtractionOutcome.SUCCESS: GraphitiReplayEligibility.COMPLETE,
        ExtractionOutcome.PARTIAL: GraphitiReplayEligibility.PARTIAL,
        ExtractionOutcome.INVALID_OUTPUT: GraphitiReplayEligibility.MALFORMED_OUTPUT,
    }[produced.outcome]
    proposal_set_id = (
        None
        if eligibility is GraphitiReplayEligibility.MALFORMED_OUTPUT
        else SOURCE_PROPOSAL_SET_ID
    )
    proposal_digest = (
        None
        if proposal_set_id is None
        else digest_canonical(
            [item.canonical_value() for item in produced.proposals]
        )
    )
    assert produced.raw_output_digest is not None
    return GraphitiReplaySource(
        replay_source_id=REPLAY_SOURCE_ID,
        source_attempt_id=source_attempt.attempt_id,
        source_run_version_id=source_attempt.extraction_request.run_version_id,
        source_output_id=SOURCE_OUTPUT_ID,
        source_proposal_set_id=proposal_set_id,
        eligibility=eligibility,
        output_canonical_digest=produced.raw_output_digest,
        proposal_set_canonical_digest=proposal_digest,
        replay_payload_digest=replay_payload_digest(produced),
        approval_event_digest=digest_canonical(
            {"approval": "increment-4d-approved-replay-v1"}
        ),
    )


def replay_attempt(
    source_attempt: GraphitiAttemptRequest,
    source: GraphitiReplaySource,
) -> GraphitiAttemptRequest:
    contract = source_attempt.extraction_contract
    request = source_attempt.extraction_request
    configuration = replay_configuration(
        configuration_id=REPLAY_CONFIGURATION_ID,
        contract=contract,
    )
    manifest = GraphitiInputManifest.from_run_request(
        manifest_id=REPLAY_MANIFEST_ID,
        configuration=configuration,
        contract=contract,
        request=request,
    )
    return GraphitiAttemptRequest(
        attempt_id=REPLAY_ATTEMPT_ID,
        attempt_number=2,
        expected_previous_attempt_id=source_attempt.attempt_id,
        configuration=configuration,
        workspace_id=REPLAY_WORKSPACE_ID,
        cleanup_receipt_id=REPLAY_CLEANUP_ID,
        manifest=manifest,
        extraction_contract=contract,
        extraction_request=request,
        replay_source=source,
        idempotency_key="increment-4d-replay-attempt-v1",
    )


def replay_bundle(
    source_attempt: GraphitiAttemptRequest,
    produced: ProducedExtraction,
) -> ApprovedReplayBundle:
    return ApprovedReplayBundle(
        source=replay_source_for(source_attempt, produced),
        produced=produced,
    )


def replace_attempt(
    attempt: GraphitiAttemptRequest,
    **changes: object,
) -> GraphitiAttemptRequest:
    return replace(attempt, **changes)
