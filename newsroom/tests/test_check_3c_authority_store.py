from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3

import pytest

from newsroom.checks.types import (
    CheckAttemptId,
    CheckAttemptKind,
    CheckRequestId,
    CheckSemanticCollision,
    CheckStateError,
    CheckVersionConflict,
    ObservableTransitionId,
    ObservableTransitionKind,
)
from newsroom.tests.check_3c_helpers import (
    ATTEMPT_ID,
    BASELINE_ID,
    FINDING_ID,
    DIGEST_F,
    LATER,
    NOW,
    OUTCOME_ID,
    REQUEST_ID,
    TRANSITION_ID,
    baseline_decision,
    check_attempt,
    check_request,
    changed_outcome,
    finding_occurrence,
    first_transition,
    operational_finding,
)
from newsroom.sources import (
    DiscoveryOccurrenceId,
    DiscoveryRepresentationId,
    IdentityComponent,
    SourceItemId,
    SourceRevisionId,
    SourceStateError,
)

from newsroom.tests.check_3c_authority_helpers import (
    OCCURRENCE_ID,
    definition_request,
    item_request,
    occurrence_request,
    open_check_system,
    proof,
    representation_request,
    revision_request,
    scopes,
    version_request,
)


def seed_complete_fixture(database: Path) -> None:
    with open_check_system(database) as system:
        system.sources.register_definition(
            definition_request(),
            proof=proof(),
        )
        system.sources.record_definition_version(
            version_request(),
            proof=proof(),
        )
        system.checks.register_request(
            check_request(),
            proof=proof(),
        )
        system.checks.start_attempt(
            check_attempt(),
            proof=proof(),
        )
        system.checks.record_outcome(
            changed_outcome(),
            proof=proof(),
        )
        system.sources.register_item(
            item_request(),
            proof=proof(),
        )
        system.sources.record_revision(
            revision_request(),
            proof=proof(),
        )
        system.sources.record_representation(
            representation_request(),
            proof=proof(),
        )
        system.sources.record_occurrence(
            occurrence_request(),
            proof=proof(),
        )
        system.checks.decide_baseline(
            baseline_decision(),
            proof=proof(),
        )
        system.checks.record_transition(
            first_transition(),
            proof=proof(),
        )
        system.checks.open_finding(
            operational_finding(),
            proof=proof(),
        )
        system.checks.record_finding_occurrence(
            finding_occurrence(),
            proof=proof(),
        )


def test_complete_check_authority_path_replays_and_reopens(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"

    with open_check_system(database) as system:
        system.sources.register_definition(
            definition_request(),
            proof=proof(),
        )
        system.sources.record_definition_version(
            version_request(),
            proof=proof(),
        )

        check = system.checks.register_request(
            check_request(),
            proof=proof(),
        )
        replayed = system.checks.register_request(
            check_request(),
            proof=proof(),
        )
        assert replayed.replayed is True
        assert replayed.event_id == check.event_id

        attempt = system.checks.start_attempt(
            check_attempt(),
            proof=proof(),
        )
        outcome = system.checks.record_outcome(
            changed_outcome(),
            proof=proof(),
        )
        system.sources.register_item(item_request(), proof=proof())
        system.sources.record_revision(revision_request(), proof=proof())
        system.sources.record_representation(
            representation_request(),
            proof=proof(),
        )
        occurrence = system.sources.record_occurrence(
            occurrence_request(),
            proof=proof(),
        )
        baseline = system.checks.decide_baseline(
            baseline_decision(),
            proof=proof(),
        )
        transition = system.checks.record_transition(
            first_transition(),
            proof=proof(),
        )
        finding = system.checks.open_finding(
            operational_finding(),
            proof=proof(),
        )
        finding_event = system.checks.record_finding_occurrence(
            finding_occurrence(),
            proof=proof(),
        )

        assert system.checks.request(REQUEST_ID, proof=proof()) == check
        assert system.checks.attempt(ATTEMPT_ID, proof=proof()) == attempt
        assert system.checks.outcome(OUTCOME_ID, proof=proof()) == outcome
        assert system.checks.attempts(
            REQUEST_ID,
            limit=10,
            proof=proof(),
        ) == (attempt,)
        assert system.checks.outcomes(
            REQUEST_ID,
            limit=10,
            proof=proof(),
        ) == (outcome,)
        assert system.checks.baseline(
            BASELINE_ID,
            proof=proof(),
        ) == baseline
        assert system.checks.current_baseline(
            check.request.definition_id,
            proof=proof(),
        ) == baseline
        assert system.checks.transition(
            TRANSITION_ID,
            proof=proof(),
        ) == transition
        assert system.checks.finding(
            FINDING_ID,
            proof=proof(),
        ) == finding
        assert system.checks.finding_occurrences(
            FINDING_ID,
            limit=10,
            proof=proof(),
        ) == (finding_event,)
        assert occurrence.request.check_outcome_id == OUTCOME_ID

    with sqlite3.connect(database) as conn:
        assert conn.execute(
            "SELECT check_outcome_id FROM discovery_occurrence_check_links "
            "WHERE occurrence_id=?",
            (str(OCCURRENCE_ID),),
        ).fetchone() == (str(OUTCOME_ID),)
        assert conn.execute(
            "SELECT COUNT(*) FROM authority_commands "
            "WHERE command_type='check.request.register'"
        ).fetchone()[0] == 1

    with open_check_system(database) as reopened:
        assert reopened.checks.request(
            REQUEST_ID,
            proof=proof(),
        ).event_id == check.event_id
        assert reopened.checks.current_baseline(
            check.request.definition_id,
            proof=proof(),
        ).request.decision_id == BASELINE_ID
        assert reopened.checks.transition(
            TRANSITION_ID,
            proof=proof(),
        ).request.check_outcome_id == OUTCOME_ID
        assert reopened.checks.finding_occurrences(
            FINDING_ID,
            limit=10,
            proof=proof(),
        )[0].request.outcome_id == OUTCOME_ID


def test_semantic_collision_and_invalid_attempt_head_roll_back_cleanly(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    with open_check_system(database) as system:
        system.sources.register_definition(
            definition_request(),
            proof=proof(),
        )
        system.sources.record_definition_version(
            version_request(),
            proof=proof(),
        )
        system.checks.register_request(
            check_request(),
            proof=proof(),
        )

        equivalent = replace(
            check_request(),
            request_id=CheckRequestId.parse(
                "00000000-0000-4000-8000-000000006151"
            ),
            idempotency_key="fixture-check-request-collision",
        )
        with pytest.raises(CheckSemanticCollision):
            system.checks.register_request(equivalent, proof=proof())

        skipped = check_attempt(
            attempt_id=CheckAttemptId.parse(
                "00000000-0000-4000-8000-000000006152"
            ),
            attempt_number=2,
            kind=CheckAttemptKind.RETRY,
            prior_attempt_id=ATTEMPT_ID,
        )
        with pytest.raises(CheckVersionConflict):
            system.checks.start_attempt(skipped, proof=proof())

    with sqlite3.connect(database) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM check_requests"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM check_attempts"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM authority_commands "
            "WHERE command_type IN ('check.request.register','check.attempt.start')"
        ).fetchone()[0] == 1


def test_check_write_and_read_scopes_are_separate(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    write_scopes = scopes() - {"authority.checks.manage"}
    with open_check_system(
        database,
        granted_scopes=write_scopes,
    ) as system:
        system.sources.register_definition(
            definition_request(),
            proof=proof(),
        )
        system.sources.record_definition_version(
            version_request(),
            proof=proof(),
        )
        with pytest.raises(PermissionError):
            system.checks.register_request(
                check_request(),
                proof=proof(),
            )

    database = tmp_path / "read.sqlite3"
    with open_check_system(database) as system:
        system.sources.register_definition(
            definition_request(),
            proof=proof(),
        )
        system.sources.record_definition_version(
            version_request(),
            proof=proof(),
        )
        system.checks.register_request(
            check_request(),
            proof=proof(),
        )

    read_scopes = scopes() - {"authority.checks.read_sensitive"}
    with open_check_system(
        database,
        granted_scopes=read_scopes,
    ) as system:
        with pytest.raises(PermissionError):
            system.checks.request(REQUEST_ID, proof=proof())


def test_finding_occurrence_limit_is_policy_bounded(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    seed_complete_fixture(database)

    with open_check_system(database) as system:
        assert len(
            system.checks.finding_occurrences(
                FINDING_ID,
                limit=1,
                proof=proof(),
            )
        ) == 1
        with pytest.raises(PermissionError):
            system.checks.finding_occurrences(
                FINDING_ID,
                limit=101,
                proof=proof(),
            )


def test_transition_observation_time_must_match_exact_outcome(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    with open_check_system(database) as system:
        system.sources.register_definition(definition_request(), proof=proof())
        system.sources.record_definition_version(version_request(), proof=proof())
        system.checks.register_request(check_request(), proof=proof())
        system.checks.start_attempt(check_attempt(), proof=proof())
        system.checks.record_outcome(changed_outcome(), proof=proof())
        system.sources.register_item(item_request(), proof=proof())
        system.sources.record_revision(revision_request(), proof=proof())
        system.sources.record_representation(
            representation_request(),
            proof=proof(),
        )
        system.sources.record_occurrence(occurrence_request(), proof=proof())

        wrong_time = replace(
            first_transition(),
            observed_at=NOW,
            idempotency_key="fixture-transition-wrong-time",
        )
        with pytest.raises(
            CheckVersionConflict,
            match="observation time",
        ):
            system.checks.record_transition(wrong_time, proof=proof())

    with sqlite3.connect(database) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM observable_transitions"
        ).fetchone()[0] == 0


def test_attempt_cannot_precede_request_or_unfinished_predecessor(
    tmp_path: Path,
) -> None:
    early_database = tmp_path / "early.sqlite3"
    with open_check_system(early_database) as system:
        system.sources.register_definition(definition_request(), proof=proof())
        system.sources.record_definition_version(version_request(), proof=proof())
        future_request = replace(
            check_request(),
            requested_at=LATER,
            idempotency_key="future-check-request",
        )
        system.checks.register_request(future_request, proof=proof())
        with pytest.raises(CheckVersionConflict, match="chronology"):
            system.checks.start_attempt(check_attempt(), proof=proof())

    unfinished_database = tmp_path / "unfinished.sqlite3"
    with open_check_system(unfinished_database) as system:
        system.sources.register_definition(definition_request(), proof=proof())
        system.sources.record_definition_version(version_request(), proof=proof())
        system.checks.register_request(check_request(), proof=proof())
        first = system.checks.start_attempt(check_attempt(), proof=proof())
        retry = replace(
            check_attempt(),
            attempt_id=CheckAttemptId.parse(
                "00000000-0000-4000-8000-000000006153"
            ),
            attempt_number=2,
            kind=CheckAttemptKind.RETRY,
            prior_attempt_id=first.request.attempt_id,
            started_at=LATER,
            idempotency_key="unfinished-retry",
        )
        with pytest.raises(CheckVersionConflict, match="completed predecessor"):
            system.checks.start_attempt(retry, proof=proof())


def test_retry_cannot_start_before_predecessor_outcome_completion(
    tmp_path: Path,
) -> None:
    database = tmp_path / "chronology.sqlite3"
    with open_check_system(database) as system:
        system.sources.register_definition(definition_request(), proof=proof())
        system.sources.record_definition_version(version_request(), proof=proof())
        system.checks.register_request(check_request(), proof=proof())
        first = system.checks.start_attempt(check_attempt(), proof=proof())
        system.checks.record_outcome(changed_outcome(), proof=proof())
        retry = replace(
            check_attempt(),
            attempt_id=CheckAttemptId.parse(
                "00000000-0000-4000-8000-000000006154"
            ),
            attempt_number=2,
            kind=CheckAttemptKind.RETRY,
            prior_attempt_id=first.request.attempt_id,
            started_at=NOW,
            idempotency_key="premature-retry",
        )
        with pytest.raises(CheckVersionConflict, match="completed predecessor"):
            system.checks.start_attempt(retry, proof=proof())


def test_operational_finding_scope_must_match_exact_check_lineage(
    tmp_path: Path,
) -> None:
    database = tmp_path / "finding-scope.sqlite3"
    with open_check_system(database) as system:
        system.sources.register_definition(definition_request(), proof=proof())
        system.sources.record_definition_version(version_request(), proof=proof())
        system.checks.register_request(check_request(), proof=proof())
        system.checks.start_attempt(check_attempt(), proof=proof())
        system.checks.record_outcome(changed_outcome(), proof=proof())

        wrong_scope = replace(
            operational_finding(),
            scope_id="00000000-0000-4000-8000-000000006199",
            idempotency_key="wrong-finding-scope",
        )
        with pytest.raises(CheckStateError, match="scope differs"):
            system.checks.open_finding(wrong_scope, proof=proof())

    with sqlite3.connect(database) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM operational_findings"
        ).fetchone()[0] == 0


def test_finding_occurrence_must_preserve_case_scope(
    tmp_path: Path,
) -> None:
    database = tmp_path / "finding-occurrence-scope.sqlite3"
    with open_check_system(database) as system:
        system.sources.register_definition(definition_request(), proof=proof())
        system.sources.record_definition_version(version_request(), proof=proof())
        system.checks.register_request(check_request(), proof=proof())
        system.checks.start_attempt(check_attempt(), proof=proof())
        system.checks.record_outcome(changed_outcome(), proof=proof())
        system.checks.open_finding(operational_finding(), proof=proof())

        missing_outcome_scope = replace(
            finding_occurrence(),
            outcome_id=None,
            idempotency_key="finding-occurrence-without-case-outcome",
        )
        with pytest.raises(CheckStateError, match="scope differs"):
            system.checks.record_finding_occurrence(
                missing_outcome_scope,
                proof=proof(),
            )

    with sqlite3.connect(database) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM operational_finding_occurrences"
        ).fetchone()[0] == 0


def test_reobserved_transition_requires_prior_observation(
    tmp_path: Path,
) -> None:
    database = tmp_path / "transition-history.sqlite3"
    with open_check_system(database) as system:
        system.sources.register_definition(definition_request(), proof=proof())
        system.sources.record_definition_version(version_request(), proof=proof())
        system.checks.register_request(check_request(), proof=proof())
        system.checks.start_attempt(check_attempt(), proof=proof())
        system.checks.record_outcome(changed_outcome(), proof=proof())
        system.sources.register_item(item_request(), proof=proof())
        system.sources.record_revision(revision_request(), proof=proof())
        system.sources.record_representation(
            representation_request(),
            proof=proof(),
        )
        system.sources.record_occurrence(occurrence_request(), proof=proof())

        impossible_reobservation = replace(
            first_transition(),
            transition_id=ObservableTransitionId.parse(
                "00000000-0000-4000-8000-000000006155"
            ),
            kind=ObservableTransitionKind.REOBSERVED,
            prior_revision_id=revision_request().revision_id,
            transition_discriminator="impossible-reobservation",
            idempotency_key="impossible-reobservation",
        )
        with pytest.raises(
            CheckVersionConflict,
            match="latest observed source state",
        ):
            system.checks.record_transition(
                impossible_reobservation,
                proof=proof(),
            )

    with sqlite3.connect(database) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM observable_transitions"
        ).fetchone()[0] == 0


def test_occurrence_requires_exact_check_outcome_lineage(
    tmp_path: Path,
) -> None:
    database = tmp_path / "occurrence-check-lineage.sqlite3"
    with open_check_system(database) as system:
        system.sources.register_definition(definition_request(), proof=proof())
        system.sources.record_definition_version(version_request(), proof=proof())
        system.checks.register_request(check_request(), proof=proof())
        system.checks.start_attempt(check_attempt(), proof=proof())
        system.sources.register_item(item_request(), proof=proof())
        system.sources.record_revision(revision_request(), proof=proof())
        system.sources.record_representation(
            representation_request(),
            proof=proof(),
        )

        with pytest.raises(SourceStateError, match="retained Check Outcome"):
            system.sources.record_occurrence(
                occurrence_request(),
                proof=proof(),
            )

        system.checks.record_outcome(changed_outcome(), proof=proof())
        wrong_time = replace(
            occurrence_request(),
            observed_at=NOW,
            idempotency_key="occurrence-wrong-outcome-time",
        )
        with pytest.raises(SourceStateError, match="exact Check Outcome lineage"):
            system.sources.record_occurrence(wrong_time, proof=proof())

        retained = system.sources.record_occurrence(
            occurrence_request(),
            proof=proof(),
        )
        assert retained.request.check_outcome_id == OUTCOME_ID


def test_occurrence_cannot_attach_representation_for_unobserved_item(
    tmp_path: Path,
) -> None:
    database = tmp_path / "occurrence-observed-item-lineage.sqlite3"
    other_item_id = SourceItemId.parse(
        "00000000-0000-4000-8000-000000006201"
    )
    other_revision_id = SourceRevisionId.parse(
        "00000000-0000-4000-8000-000000006202"
    )
    other_representation_id = DiscoveryRepresentationId.parse(
        "00000000-0000-4000-8000-000000006203"
    )
    other_occurrence_id = DiscoveryOccurrenceId.parse(
        "00000000-0000-4000-8000-000000006204"
    )

    with open_check_system(database) as system:
        system.sources.register_definition(definition_request(), proof=proof())
        system.sources.record_definition_version(version_request(), proof=proof())
        system.checks.register_request(check_request(), proof=proof())
        system.checks.start_attempt(check_attempt(), proof=proof())
        system.checks.record_outcome(changed_outcome(), proof=proof())

        other_item = replace(
            item_request(),
            item_id=other_item_id,
            identity_components=(
                IdentityComponent("document_class", "guidance-other"),
                IdentityComponent("publisher_key", "fixture-authority"),
            ),
            idempotency_key="fixture-other-source-item",
        )
        other_revision = replace(
            revision_request(),
            revision_id=other_revision_id,
            item_id=other_item_id,
            source_native_revision_token="fixture-other-revision",
            permitted_state_digest=DIGEST_F,
            idempotency_key="fixture-other-source-revision",
        )
        other_representation = replace(
            representation_request(),
            representation_id=other_representation_id,
            revision_id=other_revision_id,
            representation_digest=DIGEST_F,
            idempotency_key="fixture-other-representation",
        )
        system.sources.register_item(other_item, proof=proof())
        system.sources.record_revision(other_revision, proof=proof())
        system.sources.record_representation(other_representation, proof=proof())

        unrelated_occurrence = replace(
            occurrence_request(),
            occurrence_id=other_occurrence_id,
            revision_id=other_revision_id,
            representation_id=other_representation_id,
            idempotency_key="fixture-unobserved-item-occurrence",
        )
        with pytest.raises(
            SourceStateError,
            match="not one exact observed item",
        ):
            system.sources.record_occurrence(
                unrelated_occurrence,
                proof=proof(),
            )

    with sqlite3.connect(database) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM discovery_occurrences"
        ).fetchone()[0] == 0
