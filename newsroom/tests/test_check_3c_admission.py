from __future__ import annotations

from dataclasses import replace
import sqlite3

import pytest

from newsroom.checks import (
    AdmissionRecordState,
    CandidateObservationRef,
    CheckAttemptId,
    CheckRequestId,
    ObservableTransitionKind,
    ProposalAdmissionConflict,
    ProposalAdmissionRequest,
)
from newsroom.discovery_adapters import (
    AdapterKind,
    AdapterRequestId,
    CaptureId,
    Header,
    ObservationBaseline,
    ConditionalValidator,
    ObservationProposalId,
    ObservationProposalOutcome,
    ParserResultId,
    SourceShapeContract,
    ShapeField,
    TransportAttemptId,
    run_fixture_adapter,
)
from newsroom.sources import (
    DiscoveryOccurrenceKind,
    ObservationModel,
    SourceDefinitionVersionId,
)

from .check_3c_authority_helpers import (
    definition_request,
    open_check_system,
    proof,
    scopes,
    version_request,
)
from .check_3c_helpers import (
    ATTEMPT_ID,
    DEFINITION_ID,
    NOW,
    REQUEST_ID,
    VERSION_ID,
    check_attempt,
    check_request,
)
from .discovery_adapter_3b_helpers import (
    document_shape,
    request as adapter_request_fixture,
    scenario as adapter_scenario_fixture,
)


def _uuid_text(suffix: int) -> str:
    return f"00000000-0000-4000-8000-{suffix:012d}"


def _adapter_request(
    *,
    suffix: int,
    parser_version: str = "parser-v1",
    baseline: ObservationBaseline | None = None,
    shape: SourceShapeContract | None = None,
):
    base = adapter_request_fixture(
        kind=(
            AdapterKind.MAINTAINED_DOCUMENT
            if shape is None
            else shape.kind
        ),
        observation_model=ObservationModel.MUTABLE_ITEM,
        shape=shape or document_shape(),
        baseline=baseline,
        parser_version=parser_version,
        allowed_content_types=(
            ("text/plain",)
            if shape is None
            else ("application/json",)
        ),
    )
    return replace(
        base,
        request_id=AdapterRequestId.parse(_uuid_text(7000 + suffix)),
        source_definition_id=DEFINITION_ID,
        source_definition_version_id=VERSION_ID,
        requested_at=NOW,
    )


def _scenario(
    adapter_request,
    *,
    suffix: int,
    body: bytes = b"First maintained guidance.",
    content_type: str = "text/plain; charset=utf-8",
):
    base = adapter_scenario_fixture(
        body=body,
        content_type=content_type,
        extra_headers=(Header("etag", '"fixture-etag"'),),
    )
    return replace(
        base,
        request_id=adapter_request.request_id,
        attempt_id=TransportAttemptId.parse(_uuid_text(7100 + suffix)),
        capture_id=CaptureId.parse(_uuid_text(7200 + suffix)),
        parser_result_id=ParserResultId.parse(_uuid_text(7300 + suffix)),
        proposal_id=ObservationProposalId.parse(_uuid_text(7400 + suffix)),
        observed_at=NOW,
    )


def _check_records(adapter_request, *, suffix: int):
    request_id = (
        REQUEST_ID
        if suffix == 1
        else CheckRequestId.parse(_uuid_text(7500 + suffix))
    )
    attempt_id = (
        ATTEMPT_ID
        if suffix == 1
        else CheckAttemptId.parse(_uuid_text(7600 + suffix))
    )
    request = replace(
        check_request(),
        request_id=request_id,
        adapter_request_digest=adapter_request.digest,
        producer_slot_digest=adapter_request.producer_slot_digest,
        validator_policy=adapter_request.validator_contract,
        idempotency_key=f"proposal-check-request-{suffix}",
    )
    attempt = replace(
        check_attempt(),
        attempt_id=attempt_id,
        request_id=request_id,
        adapter_request_id=adapter_request.request_id,
        adapter_request_digest=adapter_request.digest,
        idempotency_key=f"proposal-check-attempt-{suffix}",
    )
    return request, attempt


def _seed_check(system, adapter_request, *, suffix: int):
    request, attempt = _check_records(adapter_request, suffix=suffix)
    system.checks.register_request(request, proof=proof())
    system.checks.start_attempt(attempt, proof=proof())
    return request, attempt


def _admission(request, attempt, adapter_request, proposal):
    return ProposalAdmissionRequest(
        check_request_id=request.request_id,
        check_attempt_id=attempt.attempt_id,
        adapter_request=adapter_request,
        proposal=proposal,
    )


def _seed_source(system) -> None:
    system.sources.register_definition(definition_request(), proof=proof())
    system.sources.record_definition_version(version_request(), proof=proof())


def test_changed_proposal_commits_exact_lineage_and_replays(tmp_path) -> None:
    database = tmp_path / "authority.sqlite3"
    system = open_check_system(database)
    _seed_source(system)
    adapter_request = _adapter_request(suffix=1)
    proposal = run_fixture_adapter(
        adapter_request,
        _scenario(adapter_request, suffix=1),
    )
    assert proposal.outcome is ObservationProposalOutcome.SUCCESS_CHANGED
    request, attempt = _seed_check(system, adapter_request, suffix=1)
    admission = _admission(
        request,
        attempt,
        adapter_request,
        proposal,
    )

    result = system.checks.admit_proposal(admission, proof=proof())

    assert result.outcome.request.kind.value == "SUCCESS_CHANGED"
    assert result.baseline is not None
    assert result.baseline.request.disposition.value == "MAINTAINED_BASELINE_ONLY"
    assert result.baseline_state is AdmissionRecordState.CREATED
    assert result.transitions == ()
    assert result.transition_states == ()
    assert len(result.observations) == 1
    observed = result.observations[0]
    assert observed.item_state is AdmissionRecordState.CREATED
    assert observed.revision_state is AdmissionRecordState.CREATED
    assert observed.representation_state is AdmissionRecordState.CREATED
    assert observed.occurrence_state is AdmissionRecordState.CREATED
    assert (
        observed.occurrence.request.kind
        is DiscoveryOccurrenceKind.FIRST_OBSERVED
    )

    replay = system.checks.admit_proposal(admission, proof=proof())
    assert replay.replayed is True
    assert replay.outcome.event_id == result.outcome.event_id
    assert replay.baseline is not None
    assert replay.baseline.event_id == result.baseline.event_id
    assert replay.baseline_state is AdmissionRecordState.REPLAYED
    assert replay.transitions == ()
    assert replay.transition_states == ()
    assert replay.observations[0].occurrence.event_id == observed.occurrence.event_id
    system.close()

    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM check_outcomes").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM source_items").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM source_revisions").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM discovery_representations"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM discovery_occurrences"
        ).fetchone()[0] == 1

    reopened = open_check_system(database)
    assert reopened.checks.outcome(result.outcome.request.outcome_id, proof=proof())
    assert reopened.sources.revision(
        observed.revision.request.revision_id,
        proof=proof(),
    ).event_id == observed.revision.event_id
    reopened.close()


def test_new_parser_on_unchanged_source_retains_observed_provenance_and_creates_representation_only(
    tmp_path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    system = open_check_system(database)
    _seed_source(system)

    first_request = _adapter_request(suffix=1)
    first_proposal = run_fixture_adapter(
        first_request,
        _scenario(first_request, suffix=1),
    )
    first_check, first_attempt = _seed_check(
        system,
        first_request,
        suffix=1,
    )
    first = system.checks.admit_proposal(
        _admission(
            first_check,
            first_attempt,
            first_request,
            first_proposal,
        ),
        proof=proof(),
    )
    parser_result = first_proposal.parser_result
    assert parser_result is not None
    baseline = ObservationBaseline(
        source_definition_version_id=VERSION_ID,
        validator_contract=first_request.validator_contract,
        source_body_digest=parser_result.source_body_digest,
        producer_slot_digest=parser_result.producer_slot_digest,
        representation_digest=parser_result.representation_digest,
        item_keys=parser_result.item_keys,
        validator=ConditionalValidator(etag='"fixture-etag"'),
        recorded_at=NOW,
    )
    second_request = _adapter_request(
        suffix=2,
        parser_version="parser-v2",
        baseline=baseline,
    )
    second_proposal = run_fixture_adapter(
        second_request,
        _scenario(second_request, suffix=2),
    )
    assert second_proposal.outcome is ObservationProposalOutcome.SUCCESS_UNCHANGED
    second_check, second_attempt = _seed_check(
        system,
        second_request,
        suffix=2,
    )

    second = system.checks.admit_proposal(
        _admission(
            second_check,
            second_attempt,
            second_request,
            second_proposal,
        ),
        proof=proof(),
    )

    assert second.baseline is None
    assert second.transitions == ()
    assert second.outcome.request.candidate_observations == ()
    assert second_proposal.parser_result is not None
    assert second.outcome.request.observed_items == tuple(
        CandidateObservationRef(item.item_key, item.digest)
        for item in second_proposal.parser_result.items
    )
    assert len(second.observations) == 1
    observed = second.observations[0]
    assert observed.item_state is AdmissionRecordState.REUSED
    assert observed.revision_state is AdmissionRecordState.REUSED
    assert observed.representation_state is AdmissionRecordState.CREATED
    assert observed.occurrence_state is AdmissionRecordState.CREATED
    assert observed.revision.event_id == first.observations[0].revision.event_id
    assert (
        observed.representation.request.representation_id
        != first.observations[0].representation.request.representation_id
    )
    assert observed.occurrence.request.kind is DiscoveryOccurrenceKind.REOBSERVED
    system.close()

    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM source_items").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM source_revisions").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM discovery_representations"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM discovery_occurrences"
        ).fetchone()[0] == 2


def test_changed_maintained_state_creates_revision_and_revised_transition(
    tmp_path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    system = open_check_system(database)
    _seed_source(system)

    first_request = _adapter_request(suffix=1)
    first_proposal = run_fixture_adapter(
        first_request,
        _scenario(first_request, suffix=1),
    )
    first_check, first_attempt = _seed_check(
        system,
        first_request,
        suffix=1,
    )
    first = system.checks.admit_proposal(
        _admission(
            first_check,
            first_attempt,
            first_request,
            first_proposal,
        ),
        proof=proof(),
    )
    parser_result = first_proposal.parser_result
    assert parser_result is not None
    baseline = ObservationBaseline(
        source_definition_version_id=VERSION_ID,
        validator_contract=first_request.validator_contract,
        source_body_digest=parser_result.source_body_digest,
        producer_slot_digest=parser_result.producer_slot_digest,
        representation_digest=parser_result.representation_digest,
        item_keys=parser_result.item_keys,
        validator=ConditionalValidator(etag='"fixture-etag"'),
        recorded_at=NOW,
    )
    second_request = _adapter_request(suffix=3, baseline=baseline)
    second_proposal = run_fixture_adapter(
        second_request,
        _scenario(
            second_request,
            suffix=3,
            body=b"Second maintained guidance.",
        ),
    )
    assert second_proposal.outcome is ObservationProposalOutcome.SUCCESS_CHANGED
    second_check, second_attempt = _seed_check(
        system,
        second_request,
        suffix=3,
    )

    second = system.checks.admit_proposal(
        _admission(
            second_check,
            second_attempt,
            second_request,
            second_proposal,
        ),
        proof=proof(),
    )

    assert second.baseline is None
    assert len(second.transitions) == 1
    transition = second.transitions[0]
    assert transition.request.kind is ObservableTransitionKind.REVISED
    observed = second.observations[0]
    prior = first.observations[0]
    assert observed.item.event_id == prior.item.event_id
    assert observed.revision.request.prior_revision_id == prior.revision.request.revision_id
    assert observed.revision.request.revision_id != prior.revision.request.revision_id
    assert transition.request.prior_revision_id == prior.revision.request.revision_id
    assert transition.request.current_revision_id == observed.revision.request.revision_id
    assert (
        transition.request.representation_id
        == observed.representation.request.representation_id
    )

    replay = system.checks.admit_proposal(
        _admission(
            second_check,
            second_attempt,
            second_request,
            second_proposal,
        ),
        proof=proof(),
    )
    assert replay.replayed is True
    assert replay.transition_states == (AdmissionRecordState.REPLAYED,)
    assert replay.transitions[0].event_id == transition.event_id
    system.close()

    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM baseline_decisions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM source_revisions").fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM observable_transitions"
        ).fetchone()[0] == 1


def test_outcome_prefix_replay_resumes_source_admission(tmp_path) -> None:
    system = open_check_system(tmp_path / "authority.sqlite3")
    _seed_source(system)
    adapter_request = _adapter_request(suffix=1)
    proposal = run_fixture_adapter(
        adapter_request,
        _scenario(adapter_request, suffix=1),
    )
    request, attempt = _seed_check(system, adapter_request, suffix=1)
    admission = _admission(request, attempt, adapter_request, proposal)

    prefix = system.checks.record_outcome(
        admission.outcome_request(),
        proof=proof(),
    )
    resumed = system.checks.admit_proposal(admission, proof=proof())

    assert resumed.outcome.replayed is True
    assert resumed.outcome.event_id == prefix.event_id
    assert len(resumed.observations) == 1
    assert resumed.observations[0].occurrence_state is AdmissionRecordState.CREATED
    system.close()


def test_source_write_scope_is_preflighted_before_outcome_commit(tmp_path) -> None:
    database = tmp_path / "authority.sqlite3"
    seeded = open_check_system(database)
    _seed_source(seeded)
    seeded.close()

    adapter_request = _adapter_request(suffix=1)
    proposal = run_fixture_adapter(
        adapter_request,
        _scenario(adapter_request, suffix=1),
    )
    full = open_check_system(database)
    request, attempt = _seed_check(full, adapter_request, suffix=1)
    full.close()

    restricted_scopes = scopes() - frozenset({"authority.sources.observe"})
    restricted = open_check_system(
        database,
        granted_scopes=restricted_scopes,
    )
    with pytest.raises(PermissionError):
        restricted.checks.admit_proposal(
            _admission(request, attempt, adapter_request, proposal),
            proof=proof(),
        )
    restricted.close()

    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM check_outcomes").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM source_items").fetchone()[0] == 0


def test_locator_only_identity_fails_before_outcome_commit(tmp_path) -> None:
    database = tmp_path / "authority.sqlite3"
    system = open_check_system(database)
    system.sources.register_definition(definition_request(), proof=proof())
    locator_version = replace(
        version_request(),
        extraction_scope=("title", "url"),
        idempotency_key="locator-only-source-version",
    )
    system.sources.record_definition_version(locator_version, proof=proof())
    shape = SourceShapeContract(
        shape_id="locator-only-v1",
        kind=AdapterKind.JSON_DOCUMENT,
        items_path=("items",),
        fields=(
            ShapeField("title", ("title",), True),
            ShapeField("url", ("url",), True),
        ),
        identity_fields=("url",),
    )
    adapter_request = _adapter_request(suffix=1, shape=shape)
    proposal = run_fixture_adapter(
        adapter_request,
        _scenario(
            adapter_request,
            suffix=1,
            body=b'{"items":[{"title":"One","url":"https://fixture.example/1"}]}',
            content_type="application/json; charset=utf-8",
        ),
    )
    request, attempt = _seed_check(system, adapter_request, suffix=1)

    with pytest.raises(ProposalAdmissionConflict, match="sole Source Item identity"):
        system.checks.admit_proposal(
            _admission(request, attempt, adapter_request, proposal),
            proof=proof(),
        )
    system.close()

    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM check_outcomes").fetchone()[0] == 0


def test_source_version_upgrade_reuses_state_revision_with_current_representation(
    tmp_path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    system = open_check_system(database)
    _seed_source(system)

    first_request = _adapter_request(suffix=21)
    first_proposal = run_fixture_adapter(
        first_request,
        _scenario(first_request, suffix=21),
    )
    first_check, first_attempt = _seed_check(
        system,
        first_request,
        suffix=21,
    )
    first = system.checks.admit_proposal(
        _admission(
            first_check,
            first_attempt,
            first_request,
            first_proposal,
        ),
        proof=proof(),
    )
    parser_result = first_proposal.parser_result
    assert parser_result is not None

    version_2_id = SourceDefinitionVersionId.parse(
        "00000000-0000-4000-8000-000000006121"
    )
    system.sources.record_definition_version(
        replace(
            version_request(),
            version_id=version_2_id,
            version_number=2,
            expected_previous_version_id=VERSION_ID,
            locator="fixture://increment-3c/maintained-guidance-v2",
            change_reason="Fixture source contract advanced without source-state change.",
            idempotency_key="fixture-check-source-version-v2",
        ),
        proof=proof(),
    )
    baseline = ObservationBaseline(
        source_definition_version_id=version_2_id,
        validator_contract=first_request.validator_contract,
        source_body_digest=parser_result.source_body_digest,
        producer_slot_digest=parser_result.producer_slot_digest,
        representation_digest=parser_result.representation_digest,
        item_keys=parser_result.item_keys,
        validator=ConditionalValidator(etag='"fixture-etag"'),
        recorded_at=NOW,
    )
    second_request = replace(
        _adapter_request(suffix=22, baseline=baseline),
        source_definition_version_id=version_2_id,
    )
    second_proposal = run_fixture_adapter(
        second_request,
        _scenario(second_request, suffix=22),
    )
    assert (
        second_proposal.outcome
        is ObservationProposalOutcome.SUCCESS_UNCHANGED
    )
    second_check, second_attempt = _check_records(
        second_request,
        suffix=22,
    )
    second_check = replace(
        second_check,
        definition_version_id=version_2_id,
    )
    system.checks.register_request(second_check, proof=proof())
    system.checks.start_attempt(second_attempt, proof=proof())

    second = system.checks.admit_proposal(
        _admission(
            second_check,
            second_attempt,
            second_request,
            second_proposal,
        ),
        proof=proof(),
    )

    assert second.transitions == ()
    assert len(second.observations) == 1
    observed = second.observations[0]
    prior = first.observations[0]
    assert observed.revision.event_id == prior.revision.event_id
    assert observed.revision.request.definition_version_id == VERSION_ID
    assert observed.representation is not None
    assert observed.representation.request.definition_version_id == version_2_id
    assert observed.occurrence.request.definition_version_id == version_2_id
    system.close()

    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM source_revisions").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM discovery_representations"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM discovery_occurrences"
        ).fetchone()[0] == 2

    reopened = open_check_system(database)
    assert reopened.sources.revision(
        observed.revision.request.revision_id,
        proof=proof(),
    ).event_id == prior.revision.event_id
    reopened.close()
