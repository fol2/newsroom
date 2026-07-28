from __future__ import annotations

from dataclasses import replace
import sqlite3

import pytest

from newsroom.authority.types import UtcTimestamp
from newsroom.checks import (
    CandidateObservationRef,
    CheckAttemptId,
    CheckOutcomeId,
    CheckRequestId,
    CheckVersionConflict,
    ObservableTransitionId,
    ObservableTransitionKind,
    ProposalAdmissionConflict,
    TriggerKind,
    TriggerRef,
)
from newsroom.discovery_adapters import (
    AdapterRequestId,
    ObservationProposalId,
    run_fixture_adapter,
)
from newsroom.sources import (
    DiscoveryOccurrenceId,
    DiscoveryOccurrenceKind,
    DiscoveryRepresentationId,
    SourceRevisionId,
)

from .check_3c_authority_helpers import (
    definition_request,
    item_request,
    occurrence_request,
    open_check_system,
    proof,
    representation_request,
    revision_request,
    version_request,
)
from .check_3c_helpers import (
    DIGEST_C,
    DIGEST_D,
    DIGEST_E,
    ITEM_ID,
    check_attempt,
    check_request,
    changed_outcome,
    first_transition,
)
from .test_check_3c_admission import (
    _adapter_request,
    _admission,
    _scenario,
    _seed_check,
    _seed_source,
)


def _uuid(suffix: int) -> str:
    return f"00000000-0000-4000-8000-{suffix:012d}"


def _time(second: int) -> UtcTimestamp:
    return UtcTimestamp.parse(
        f"2042-03-12T10:00:{second:02d}.000000Z"
    )


def _record_check_outcome(
    system,
    *,
    suffix: int,
    completed_at: UtcTimestamp,
    representation_digest: str,
):
    request_id = CheckRequestId.parse(_uuid(9000 + suffix))
    attempt_id = CheckAttemptId.parse(_uuid(9100 + suffix))
    outcome_id = CheckOutcomeId.parse(_uuid(9200 + suffix))
    proposal_id = ObservationProposalId.parse(_uuid(9300 + suffix))
    adapter_request_id = AdapterRequestId.parse(_uuid(9400 + suffix))
    request = replace(
        check_request(),
        request_id=request_id,
        trigger=TriggerRef(
            TriggerKind.FIXTURE_MANUAL,
            f"chronology-trigger-{suffix}",
            "v1",
        ),
        idempotency_key=f"chronology-request-{suffix}",
    )
    attempt = replace(
        check_attempt(),
        attempt_id=attempt_id,
        request_id=request_id,
        adapter_request_id=adapter_request_id,
        idempotency_key=f"chronology-attempt-{suffix}",
    )
    observed = (
        CandidateObservationRef(DIGEST_C, representation_digest),
    )
    outcome = replace(
        changed_outcome(),
        outcome_id=outcome_id,
        request_id=request_id,
        attempt_id=attempt_id,
        proposal_id=proposal_id,
        representation_digest=representation_digest,
        candidate_observations=observed,
        observed_items=observed,
        completed_at=completed_at,
        idempotency_key=f"chronology-outcome-{suffix}",
    )
    system.checks.register_request(request, proof=proof())
    system.checks.start_attempt(attempt, proof=proof())
    return system.checks.record_outcome(outcome, proof=proof())


def _commit_source_prefix_without_occurrence(system, admission) -> None:
    boundary = system.checks._GovernedChecks__admit_proposal.__self__
    store = boundary._store
    retained_request = store.check_request(admission.check_request_id)
    retained_attempt = store.check_attempt(admission.check_attempt_id)
    version = store.source_definition_version(
        admission.adapter_request.source_definition_version_id
    )
    assert retained_request is not None
    assert retained_attempt is not None
    assert version is not None
    boundary._validate_adapter_contract(
        admission,
        version,
        retained_request=retained_request,
        retained_attempt=retained_attempt,
    )
    assert len(admission.parsed_items) == 1
    plan = boundary._plan_observation(
        admission,
        version,
        admission.parsed_items[0],
        trigger_kind=retained_request.request.trigger.kind,
    )
    authorized = boundary._authorize_plan(plan, proof())
    if plan.item_request is not None:
        assert authorized.item_grant is not None
        store.commit_source_item(
            authorized.item_grant,
            request=plan.item_request,
        )
    if plan.revision_request is not None:
        assert authorized.revision_grant is not None
        store.commit_source_revision(
            authorized.revision_grant,
            request=plan.revision_request,
        )
    if plan.representation_request is not None:
        assert authorized.representation_grant is not None
        store.commit_discovery_representation(
            authorized.representation_grant,
            request=plan.representation_request,
        )



def test_later_check_is_blocked_while_prior_observed_outcome_lacks_occurrence(
    tmp_path,
) -> None:
    database = tmp_path / "unresolved-prior-outcome.sqlite3"
    system = open_check_system(database)
    _seed_source(system)

    first_adapter = _adapter_request(suffix=41)
    first_proposal = run_fixture_adapter(
        first_adapter,
        _scenario(first_adapter, suffix=41),
    )
    first_request, first_attempt = _seed_check(
        system,
        first_adapter,
        suffix=41,
    )
    first_admission = _admission(
        first_request,
        first_attempt,
        first_adapter,
        first_proposal,
    )
    system.checks.record_outcome(
        first_admission.outcome_request(),
        proof=proof(),
    )

    second_adapter = _adapter_request(suffix=42)
    second_scenario = replace(
        _scenario(second_adapter, suffix=42),
        observed_at=_time(1),
    )
    second_proposal = run_fixture_adapter(
        second_adapter,
        second_scenario,
    )
    second_request, second_attempt = _seed_check(
        system,
        second_adapter,
        suffix=42,
    )
    second_admission = _admission(
        second_request,
        second_attempt,
        second_adapter,
        second_proposal,
    )

    with pytest.raises(
        ProposalAdmissionConflict,
        match="prior observed Check Outcome lacks retained source Occurrence",
    ):
        system.checks.admit_proposal(
            second_admission,
            proof=proof(),
        )
    system.close()

    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM check_outcomes").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM check_outcome_observed_items"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM discovery_occurrences"
        ).fetchone()[0] == 0


def test_same_time_later_crash_prefix_does_not_block_exact_earlier_replay(
    tmp_path,
) -> None:
    database = tmp_path / "same-time-replay-boundary.sqlite3"
    system = open_check_system(database)
    _seed_source(system)

    first_adapter = _adapter_request(suffix=43)
    first_proposal = run_fixture_adapter(
        first_adapter,
        _scenario(first_adapter, suffix=43),
    )
    first_request, first_attempt = _seed_check(
        system,
        first_adapter,
        suffix=43,
    )
    first_admission = _admission(
        first_request,
        first_attempt,
        first_adapter,
        first_proposal,
    )
    first = system.checks.admit_proposal(
        first_admission,
        proof=proof(),
    )

    later_adapter = _adapter_request(suffix=44)
    later_proposal = run_fixture_adapter(
        later_adapter,
        _scenario(
            later_adapter,
            suffix=44,
            body=b"Later same-time source state.",
        ),
    )
    later_request, later_attempt = _seed_check(
        system,
        later_adapter,
        suffix=44,
    )
    later_admission = _admission(
        later_request,
        later_attempt,
        later_adapter,
        later_proposal,
    )
    assert later_admission.completed_at == first_admission.completed_at
    system.checks.record_outcome(
        later_admission.outcome_request(),
        proof=proof(),
    )
    _commit_source_prefix_without_occurrence(system, later_admission)

    replay = system.checks.admit_proposal(
        first_admission,
        proof=proof(),
    )
    assert replay.replayed is True
    assert replay.outcome.event_id == first.outcome.event_id
    assert replay.observations[0].occurrence.event_id == (
        first.observations[0].occurrence.event_id
    )

    next_adapter = _adapter_request(suffix=45)
    next_proposal = run_fixture_adapter(
        next_adapter,
        _scenario(next_adapter, suffix=45),
    )
    next_request, next_attempt = _seed_check(
        system,
        next_adapter,
        suffix=45,
    )
    with pytest.raises(
        ProposalAdmissionConflict,
        match="prior observed Check Outcome lacks retained source Occurrence",
    ):
        system.checks.admit_proposal(
            _admission(
                next_request,
                next_attempt,
                next_adapter,
                next_proposal,
            ),
            proof=proof(),
        )
    system.close()

    with sqlite3.connect(database) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM check_outcomes"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM source_revisions"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM discovery_representations"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM discovery_occurrences"
        ).fetchone()[0] == 1


def test_latest_transition_uses_outcome_chronology_not_commit_order(
    tmp_path,
) -> None:
    database = tmp_path / "transition-semantic-order.sqlite3"
    system = open_check_system(database)
    system.sources.register_definition(definition_request(), proof=proof())
    system.sources.record_definition_version(version_request(), proof=proof())
    system.sources.register_item(item_request(), proof=proof())

    base_time = _time(0)
    first_time = _time(1)
    second_time = _time(2)
    digest_0 = "sha256:" + "0" * 64
    digest_1 = "sha256:" + "1" * 64
    digest_2 = "sha256:" + "2" * 64

    base_outcome = _record_check_outcome(
        system,
        suffix=1,
        completed_at=base_time,
        representation_digest=digest_0,
    )
    first_outcome = _record_check_outcome(
        system,
        suffix=2,
        completed_at=first_time,
        representation_digest=digest_1,
    )
    second_outcome = _record_check_outcome(
        system,
        suffix=3,
        completed_at=second_time,
        representation_digest=digest_2,
    )

    revision_0_id = SourceRevisionId.parse(_uuid(9501))
    revision_1_id = SourceRevisionId.parse(_uuid(9502))
    revision_2_id = SourceRevisionId.parse(_uuid(9503))
    representation_0_id = DiscoveryRepresentationId.parse(_uuid(9601))
    representation_1_id = DiscoveryRepresentationId.parse(_uuid(9602))
    representation_2_id = DiscoveryRepresentationId.parse(_uuid(9603))

    prior_revision = None
    for index, (
        outcome,
        observed_at,
        revision_id,
        representation_id,
        representation_digest,
    ) in enumerate(
        (
            (
                base_outcome,
                base_time,
                revision_0_id,
                representation_0_id,
                digest_0,
            ),
            (
                first_outcome,
                first_time,
                revision_1_id,
                representation_1_id,
                digest_1,
            ),
            (
                second_outcome,
                second_time,
                revision_2_id,
                representation_2_id,
                digest_2,
            ),
        ),
        start=1,
    ):
        revision = replace(
            revision_request(),
            revision_id=revision_id,
            prior_revision_id=prior_revision,
            source_native_revision_token=f"chronology-revision-{index}",
            permitted_state_digest="sha256:" + str(index) * 64,
            observed_at=observed_at,
            idempotency_key=f"chronology-revision-{index}",
        )
        representation = replace(
            representation_request(),
            representation_id=representation_id,
            revision_id=revision_id,
            representation_digest=representation_digest,
            produced_at=observed_at,
            idempotency_key=f"chronology-representation-{index}",
        )
        occurrence = replace(
            occurrence_request(),
            occurrence_id=DiscoveryOccurrenceId.parse(_uuid(9700 + index)),
            check_outcome_id=outcome.request.outcome_id,
            revision_id=revision_id,
            representation_id=representation_id,
            kind=(
                DiscoveryOccurrenceKind.FIRST_OBSERVED
                if index == 1
                else DiscoveryOccurrenceKind.REOBSERVED
            ),
            observed_at=observed_at,
            receipt_digest=DIGEST_E,
            idempotency_key=f"chronology-occurrence-{index}",
        )
        system.sources.record_revision(revision, proof=proof())
        system.sources.record_representation(representation, proof=proof())
        system.sources.record_occurrence(occurrence, proof=proof())
        prior_revision = revision_id

    boundary = system.checks._GovernedChecks__admit_proposal.__self__
    store = boundary._store
    prior_to_first = store.latest_observed_source_revision(
        ITEM_ID,
        exclude_outcome_id=first_outcome.request.outcome_id,
        before_completed_at=first_time,
    )
    assert prior_to_first is not None
    assert prior_to_first.request.revision_id == revision_0_id
    assert store.discovery_occurrence_count_for_item(
        ITEM_ID,
        exclude_outcome_id=first_outcome.request.outcome_id,
        before_completed_at=first_time,
    ) == 1
    assert store.discovery_occurrence_count_for_revision(
        revision_1_id,
        exclude_outcome_id=first_outcome.request.outcome_id,
        before_completed_at=first_time,
    ) == 0

    later_transition = replace(
        first_transition(),
        transition_id=ObservableTransitionId.parse(_uuid(9802)),
        check_outcome_id=second_outcome.request.outcome_id,
        kind=ObservableTransitionKind.REVISED,
        prior_revision_id=revision_1_id,
        current_revision_id=revision_2_id,
        representation_id=representation_2_id,
        change_facets=("PERMITTED_STATE_DIGEST",),
        observed_at=second_time,
        transition_discriminator="chronology-later-revision",
        idempotency_key="chronology-later-transition",
    )
    earlier_transition = replace(
        first_transition(),
        transition_id=ObservableTransitionId.parse(_uuid(9801)),
        check_outcome_id=first_outcome.request.outcome_id,
        kind=ObservableTransitionKind.REVISED,
        prior_revision_id=revision_0_id,
        current_revision_id=revision_1_id,
        representation_id=representation_1_id,
        change_facets=("PERMITTED_STATE_DIGEST",),
        observed_at=first_time,
        transition_discriminator="chronology-earlier-revision",
        idempotency_key="chronology-earlier-transition",
    )

    committed_later = system.checks.record_transition(
        later_transition,
        proof=proof(),
    )
    system.checks.record_transition(
        earlier_transition,
        proof=proof(),
    )

    latest = store.latest_observable_transition_for_item(ITEM_ID)
    assert latest is not None
    assert latest.event_id == committed_later.event_id
    assert latest.request.observed_at == second_time
    system.close()

    open_check_system(database).close()


def test_transition_rejects_prior_observed_outcome_without_occurrence(
    tmp_path,
) -> None:
    database = tmp_path / "transition-unresolved-prior.sqlite3"
    system = open_check_system(database)
    system.sources.register_definition(definition_request(), proof=proof())
    system.sources.record_definition_version(version_request(), proof=proof())
    system.sources.register_item(item_request(), proof=proof())

    _record_check_outcome(
        system,
        suffix=11,
        completed_at=_time(0),
        representation_digest=DIGEST_D,
    )
    current_outcome = _record_check_outcome(
        system,
        suffix=12,
        completed_at=_time(1),
        representation_digest=DIGEST_D,
    )
    revision = replace(
        revision_request(),
        observed_at=_time(1),
        idempotency_key="unresolved-prior-revision",
    )
    representation = replace(
        representation_request(),
        produced_at=_time(1),
        idempotency_key="unresolved-prior-representation",
    )
    occurrence = replace(
        occurrence_request(),
        occurrence_id=DiscoveryOccurrenceId.parse(_uuid(9901)),
        check_outcome_id=current_outcome.request.outcome_id,
        observed_at=_time(1),
        idempotency_key="unresolved-prior-current-occurrence",
    )
    system.sources.record_revision(revision, proof=proof())
    system.sources.record_representation(representation, proof=proof())
    system.sources.record_occurrence(occurrence, proof=proof())

    transition = replace(
        first_transition(),
        transition_id=ObservableTransitionId.parse(_uuid(9902)),
        check_outcome_id=current_outcome.request.outcome_id,
        observed_at=_time(1),
        idempotency_key="unresolved-prior-first-transition",
    )
    with pytest.raises(
        CheckVersionConflict,
        match="prior observed Check Outcome lacks one exact source Occurrence",
    ):
        system.checks.record_transition(transition, proof=proof())
    system.close()


def test_latest_representation_uses_produced_time_not_commit_order(
    tmp_path,
) -> None:
    database = tmp_path / "representation-semantic-order.sqlite3"
    system = open_check_system(database)
    system.sources.register_definition(definition_request(), proof=proof())
    system.sources.record_definition_version(version_request(), proof=proof())
    system.sources.register_item(item_request(), proof=proof())
    system.sources.record_revision(revision_request(), proof=proof())

    later = replace(
        representation_request(),
        representation_id=DiscoveryRepresentationId.parse(_uuid(9951)),
        parser_version="chronology-parser-v2",
        representation_digest="sha256:" + "2" * 64,
        produced_at=_time(2),
        idempotency_key="chronology-later-representation",
    )
    earlier = replace(
        representation_request(),
        representation_id=DiscoveryRepresentationId.parse(_uuid(9952)),
        parser_version="chronology-parser-v1",
        representation_digest="sha256:" + "1" * 64,
        produced_at=_time(1),
        idempotency_key="chronology-earlier-representation",
    )
    committed_later = system.sources.record_representation(
        later,
        proof=proof(),
    )
    system.sources.record_representation(earlier, proof=proof())

    boundary = system.checks._GovernedChecks__admit_proposal.__self__
    latest = boundary._store.latest_representation_for_revision(
        revision_request().revision_id
    )
    assert latest is not None
    assert latest.event_id == committed_later.event_id
    assert latest.request.produced_at == _time(2)
    system.close()
