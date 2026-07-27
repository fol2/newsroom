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
    CheckVersionConflict,
)
from newsroom.tests.check_3c_helpers import (
    ATTEMPT_ID,
    BASELINE_ID,
    FINDING_ID,
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
        system.checks.decide_baseline(
            baseline_decision(),
            proof=proof(),
        )
        system.sources.record_occurrence(
            occurrence_request(),
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
        baseline = system.checks.decide_baseline(
            baseline_decision(),
            proof=proof(),
        )
        occurrence = system.sources.record_occurrence(
            occurrence_request(),
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
