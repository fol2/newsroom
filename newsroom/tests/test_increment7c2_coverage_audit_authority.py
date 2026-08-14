from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import replace

import pytest

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.authority.coverage_audit_migrations import (
    COVERAGE_AUDIT_MIGRATION_NAME,
    COVERAGE_AUDIT_SCHEMA_VERSION,
    CoverageAuditBackupError,
    coverage_audit_backup_paths,
    prepare_coverage_audit_backup,
)
from newsroom.authority.migrations import (
    EXPECTED_MIGRATION_HISTORY,
    EXPECTED_SCHEMA_FINGERPRINT,
    SCHEMA_VERSION,
    apply_pending_migrations,
    schema_fingerprint,
)
from newsroom.increment7.coverage import (
    CoverageAssessmentState,
    CoverageAudit,
    CoverageAuditMode,
    CoverageBasisKind,
    CoverageComparator,
    CoverageGap,
    CoverageGapDecision,
    CoverageGapDisposition,
    CoverageGapScope,
    CoverageGapState,
    CoverageObservation,
    CoverageObservationKind,
)
from newsroom.increment7.coverage_authority import (
    COVERAGE_ASSESSMENT,
    COVERAGE_ASSESSMENT_AUTHORITY,
    COVERAGE_AUDIT_AUTHORITY,
    COVERAGE_COMMAND,
    AssessmentFactor,
    CoverageAssessment,
    CoverageAuditReadPort,
    CoverageAuthorityError,
    CoverageCommand,
    DependencyState,
    HealthState,
    TimelinessState,
    deterministic_assessment,
    open_coverage_audit_authority,
    validate_coverage_command,
)
from newsroom.increment7.search import SearchReviewAction, SearchReviewDecision
from newsroom.tests.test_increment7b1_gross_request_privacy import (
    _attempt,
    _outcome,
    _purpose,
    _request,
    _result,
)
from newsroom.tests.test_increment7e2_locality_no_activation import (
    _chain as _locality_chain,
)
from newsroom.tests.test_increment7e2_locality_no_activation import (
    _provider_qualifications,
)

_AT = "2026-08-14T00:00:00.000000Z"
_D = "sha256:" + "a" * 64
_APPLIED = "2026-08-14T09:00:00.000000Z"


def _id(value: int) -> str:
    return str(uuid.UUID(int=value, version=4))


def _search_chain():
    purpose = _purpose()
    request = _request(purpose)
    attempt = _attempt(request)
    outcome = _outcome(attempt)
    result = _result(attempt, outcome)
    review = SearchReviewDecision(
        _id(106),
        (result.result_reference_id,),
        (result.digest,),
        SearchReviewAction.SUPPORT_COVERAGE_GAP_REVIEW,
        "sha256:" + "2" * 64,
        "sha256:" + "3" * 64,
        ("PROSPECTIVE_COMPARATOR_HIT",),
        "2026-08-14T00:00:03.000000Z",
    )
    return purpose, request, attempt, outcome, (result,), review


def _assessment(
    *,
    dependency: DependencyState = DependencyState.AVAILABLE,
    timeliness: TimelinessState = TimelinessState.ON_TIME,
    health: HealthState = HealthState.HEALTHY,
) -> CoverageAssessment:
    dependencies = (AssessmentFactor("search", dependency, "sha256:" + "4" * 64),)
    timings = (AssessmentFactor("window", timeliness, "sha256:" + "5" * 64),)
    healths = (AssessmentFactor("source_pack", health, "sha256:" + "6" * 64),)
    state, limitations = deterministic_assessment(
        dependencies,
        timings,
        healths,
        ("best_effort_not_ground_truth",),
    )
    return CoverageAssessment(
        _id(110),
        dependencies,
        timings,
        healths,
        ("best_effort_not_ground_truth",),
        state,
        limitations,
        "2026-08-14T04:00:00.000000Z",
    )


def _command(
    *,
    assessment: CoverageAssessment | None = None,
    decision: CoverageGapDecision | None = None,
    previous: CoverageGapDecision | None = None,
    command_value: int = 120,
) -> tuple[CoverageCommand, tuple, tuple, tuple]:
    search = _search_chain()
    request = search[1]
    result = search[4][0]
    review = search[5]
    providers = _provider_qualifications()
    locality = _locality_chain()
    unit = locality[1]
    locality_decision = locality[3]
    assessment = assessment or _assessment()
    comparator = CoverageComparator(
        _id(111),
        CoverageAuditMode.PROSPECTIVE_PRE_REGISTERED,
        CoverageBasisKind.PLANNED_AGENDA,
        "fixture.policy.decision",
        (_D,),
        (unit.digest,),
        unit.source_class_scope,
        (request.digest,),
        "2026-08-14T01:00:00.000000Z",
        "2026-08-14T02:00:00.000000Z",
        None,
        ("sha256:" + "7" * 64,),
        _AT,
    )
    observations = (
        CoverageObservation(
            CoverageObservationKind.SEARCH_RESULT_REFERENCE,
            result.digest,
            result.recorded_at,
        ),
        CoverageObservation(
            CoverageObservationKind.EXPECTATION_NOT_OBSERVED,
            _D,
            "2026-08-14T03:00:00.000000Z",
        ),
    )
    audit = CoverageAudit(
        _id(112),
        comparator.comparator_id,
        comparator.digest,
        comparator.audit_mode,
        observations,
        assessment.derived_state,
        assessment.derived_limitation_codes,
        "sha256:" + "8" * 64,
        assessment.assessed_at,
    )
    gap = CoverageGap(
        _id(113),
        audit.audit_id,
        audit.digest,
        CoverageGapScope.ISOLATED
        if assessment.derived_state is not CoverageAssessmentState.DEFERRED
        else CoverageGapScope.UNDETERMINED,
        CoverageGapState.PROPOSED
        if assessment.derived_state is not CoverageAssessmentState.DEFERRED
        else CoverageGapState.DEFERRED_ASSESSMENT,
        (unit.digest,),
        (_D,),
        (),
        audit.limitation_codes,
        "2026-08-14T05:00:00.000000Z",
    )
    if decision is None:
        decision = CoverageGapDecision(
            _id(114),
            gap.gap_id,
            gap.digest,
            CoverageGapDisposition.CONFIRMED_BEST_EFFORT_GAP
            if assessment.derived_state is not CoverageAssessmentState.DEFERRED
            else CoverageGapDisposition.DEFERRED_INSUFFICIENT_BASIS,
            (result.digest,),
            gap.limitation_codes,
            "sha256:" + "9" * 64,
            ("reviewed_best_effort_gap",),
            None if previous is None else previous.digest,
            "2026-08-14T06:00:00.000000Z"
            if previous is None
            else "2026-08-14T07:00:00.000000Z",
        )
    command = CoverageCommand(
        _id(command_value),
        comparator,
        assessment,
        audit,
        gap,
        decision,
        (request.digest,),
        (result.digest,),
        (review.digest,),
        (providers[0][1].digest,),
        locality[0].digest,
        unit.digest,
        locality_decision.digest,
        None if previous is None else previous.digest,
        _id(command_value + 1),
        "sha256:" + "b" * 64,
        f"coverage-command-{command_value}",
    )
    return command, (search,), providers, locality


def test_deterministic_assessment_derives_state_and_exact_limitations() -> None:
    complete = _assessment()
    partial = _assessment(timeliness=TimelinessState.LATE)
    deferred = _assessment(health=HealthState.UNKNOWN)

    assert complete.derived_state is CoverageAssessmentState.COMPLETE_BEST_EFFORT
    assert partial.derived_state is CoverageAssessmentState.PARTIAL_LIMITED
    assert "timeliness.window.late" in partial.derived_limitation_codes
    assert deferred.derived_state is CoverageAssessmentState.DEFERRED
    assert "health.source_pack.unknown" in deferred.derived_limitation_codes
    for assessment in (complete, partial, deferred):
        assert (
            CoverageAssessment.from_canonical_bytes(assessment.canonical_bytes)
            == assessment
        )
        assert assessment.authorises_evidence is False
        assert assessment.creates_watch is False
        assert assessment.production_activation_authorised is False

    with pytest.raises(CoverageAuthorityError, match="derivation differs"):
        replace(complete, derived_state=CoverageAssessmentState.DEFERRED)
    with pytest.raises(CoverageAuthorityError, match="unique and sorted"):
        replace(
            complete,
            dependency_factors=(
                complete.dependency_factors[0],
                complete.dependency_factors[0],
            ),
        )


def test_command_binds_exact_search_provider_locality_and_coverage_chains() -> None:
    command, searches, providers, locality = _command()
    validate_coverage_command(
        command,
        search_evidence=searches,
        provider_qualifications=providers,
        locality_qualification=locality,
    )
    assert CoverageCommand.from_canonical_bytes(command.canonical_bytes) == command
    assert command.search_request_digests == command.comparator.search_request_digests
    assert (
        command.locality_coverage_unit_digest
        in command.comparator.coverage_unit_digests
    )
    assert command.authorises_search is False
    assert command.authorises_provider is False
    assert command.authorises_locality is False

    with pytest.raises(CoverageAuthorityError, match="Search identity set"):
        validate_coverage_command(
            replace(command, search_review_decision_digests=("sha256:" + "0" * 64,)),
            search_evidence=searches,
            provider_qualifications=providers,
            locality_qualification=locality,
        )
    with pytest.raises(CoverageAuthorityError, match="qualification identity"):
        validate_coverage_command(
            replace(command, locality_decision_digest="sha256:" + "0" * 64),
            search_evidence=searches,
            provider_qualifications=providers,
            locality_qualification=locality,
        )


def test_command_parser_rejects_noncanonical_duplicate_unknown_and_oversized() -> None:
    command = _command()[0]
    pretty = json.dumps(json.loads(command.canonical_bytes), indent=2).encode()
    with pytest.raises(CoverageAuthorityError, match="exact canonical JSON"):
        CoverageCommand.from_canonical_bytes(pretty)
    duplicate = command.canonical_bytes.replace(
        b'"command_id":',
        b'"command_id":"' + _id(999).encode() + b'","command_id":',
        1,
    )
    with pytest.raises(CoverageAuthorityError, match="duplicate object name"):
        CoverageCommand.from_canonical_bytes(duplicate)
    unknown = json.loads(command.canonical_bytes)
    unknown["activate_provider"] = False
    with pytest.raises(CoverageAuthorityError, match="fields or schema"):
        CoverageCommand.from_canonical_bytes(canonical_json_bytes(unknown))
    oversized = command.canonical_bytes.replace(
        b'"idempotency_key":"coverage-command-120"',
        b'"idempotency_key":"' + b"x" * 9_000_000 + b'"',
    )
    with pytest.raises(CoverageAuthorityError, match="not bounded"):
        CoverageCommand.from_canonical_bytes(oversized)


def test_v28_fresh_create_history_fingerprint_and_reserved_tables() -> None:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.execute("PRAGMA foreign_keys=ON")
    apply_pending_migrations(connection, applied_at=_APPLIED)
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert SCHEMA_VERSION == COVERAGE_AUDIT_SCHEMA_VERSION == 28
    assert EXPECTED_MIGRATION_HISTORY[-1][1] == COVERAGE_AUDIT_MIGRATION_NAME
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 28
    assert schema_fingerprint(connection) == EXPECTED_SCHEMA_FINGERPRINT
    assert {
        "coverage_audits",
        "coverage_audit_observations",
        "coverage_gaps",
        "coverage_gap_decisions",
    } <= tables
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"


def _create_v27(path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, isolation_level=None)
    connection.execute("PRAGMA foreign_keys=ON")
    apply_pending_migrations(connection, applied_at=_APPLIED)
    connection.execute("PRAGMA foreign_keys=OFF")
    connection.execute("BEGIN EXCLUSIVE")
    immutable = connection.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE name='immutable_authority_migrations_delete'"
    ).fetchone()[0]
    connection.execute("DROP TRIGGER immutable_authority_migrations_delete")
    for table in (
        "coverage_gap_decisions",
        "coverage_audit_observations",
        "coverage_gaps",
        "coverage_audits",
    ):
        for (name,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",
            (table,),
        ).fetchall():
            connection.execute(f'DROP TRIGGER "{name}"')
        connection.execute(f"DROP TABLE {table}")
    connection.execute("DELETE FROM authority_migrations WHERE version=28")
    connection.execute(immutable)
    connection.execute("PRAGMA user_version=27")
    connection.execute("COMMIT")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def test_v27_upgrade_requires_exact_backup_and_preserves_restore_point(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "authority.sqlite3"
    connection = _create_v27(database)
    with pytest.raises(CoverageAuditBackupError, match="requires prepared backup"):
        apply_pending_migrations(connection, applied_at=_APPLIED)
    backup, digest_path = coverage_audit_backup_paths(database)
    receipt = prepare_coverage_audit_backup(connection, backup)
    assert receipt.backup_path == backup
    assert digest_path.is_file()
    from newsroom.authority import migrations

    statements = migrations.COVERAGE_AUDIT_MIGRATION_STATEMENTS
    monkeypatch.setattr(
        migrations,
        "COVERAGE_AUDIT_MIGRATION_STATEMENTS",
        (statements[0], "CREATE TABLE deliberate_failure("),
    )
    with pytest.raises(sqlite3.OperationalError):
        apply_pending_migrations(connection, applied_at=_APPLIED)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 27
    assert schema_fingerprint(connection) == (
        "sha256:d7fc1557bd02588969efdd53c749a2f125ab5bab146395c4cf8f7d51b1e32719"
    )
    monkeypatch.setattr(migrations, "COVERAGE_AUDIT_MIGRATION_STATEMENTS", statements)
    apply_pending_migrations(connection, applied_at=_APPLIED)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 28

    restored = sqlite3.connect(backup, isolation_level=None)
    try:
        assert restored.execute("PRAGMA user_version").fetchone()[0] == 27
        assert restored.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        restored.close()


def test_authority_persists_exact_replay_restart_and_rejects_tamper(tmp_path) -> None:
    path = tmp_path / "coverage.sqlite3"
    command, searches, providers, locality = _command()
    authority = open_coverage_audit_authority(path, applied_at=_APPLIED)
    decision = authority.record(
        command.canonical_bytes,
        search_evidence=searches,
        provider_qualifications=providers,
        locality_qualification=locality,
    )
    assert decision == command.decision
    assert (
        authority.record(
            command.canonical_bytes,
            search_evidence=searches,
            provider_qualifications=providers,
            locality_qualification=locality,
        )
        == decision
    )
    port = authority.read_port()
    assert type(port) is CoverageAuditReadPort
    assert port.audit(command.audit.audit_id) == command.audit
    assert port.assessment(command.audit.audit_id) == command.assessment
    assert port.gap(command.gap.gap_id) == command.gap
    assert port.decision(decision.decision_id) == decision
    assert port.command(command.command_id) == command
    authority.close()

    reopened = open_coverage_audit_authority(path, applied_at=_APPLIED)
    assert reopened.read_port().command(command.command_id) == command
    reopened.close()

    attacker = sqlite3.connect(path, isolation_level=None)
    attacker.execute("DROP TRIGGER immutable_coverage_audits")
    attacker.execute(
        "UPDATE coverage_audits SET assessment_state='DEFERRED' WHERE audit_id=?",
        (command.audit.audit_id,),
    )
    attacker.close()
    reopened = open_coverage_audit_authority(path, applied_at=_APPLIED)
    with pytest.raises(CoverageAuthorityError, match="retained representation"):
        reopened.read_port().audit(command.audit.audit_id)
    reopened.close()


def test_successor_decision_is_cas_bound_and_preserves_initial_bytes(tmp_path) -> None:
    path = tmp_path / "coverage.sqlite3"
    first_command, searches, providers, locality = _command()
    authority = open_coverage_audit_authority(path, applied_at=_APPLIED)
    first = authority.record(
        first_command.canonical_bytes,
        search_evidence=searches,
        provider_qualifications=providers,
        locality_qualification=locality,
    )
    successor_decision = replace(
        first,
        decision_id=_id(115),
        supersedes_decision_digest=first.digest,
        decided_at="2026-08-14T07:00:00.000000Z",
    )
    successor, searches, providers, locality = _command(
        decision=successor_decision,
        previous=first,
        command_value=130,
    )
    assert (
        authority.record(
            successor.canonical_bytes,
            search_evidence=searches,
            provider_qualifications=providers,
            locality_qualification=locality,
        )
        == successor_decision
    )
    assert authority.read_port().decision(first.decision_id) == first
    stale = replace(
        successor,
        command_id=_id(140),
        request_id=_id(141),
        idempotency_key="coverage-command-stale",
        expected_previous_decision_digest=None,
        decision=replace(
            successor.decision, decision_id=_id(142), supersedes_decision_digest=None
        ),
    )
    with pytest.raises(CoverageAuthorityError, match="predecessor"):
        authority.record(
            stale.canonical_bytes,
            search_evidence=searches,
            provider_qualifications=providers,
            locality_qualification=locality,
        )
    authority.close()


def test_competing_identical_writers_have_one_retained_decision(tmp_path) -> None:
    path = tmp_path / "coverage.sqlite3"
    command, searches, providers, locality = _command()
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    authorities = [
        open_coverage_audit_authority(path, applied_at=_APPLIED) for _ in range(2)
    ]

    def writer(authority) -> None:
        barrier.wait()
        result = authority.record(
            command.canonical_bytes,
            search_evidence=searches,
            provider_qualifications=providers,
            locality_qualification=locality,
        )
        outcomes.append(result.digest)
        authority.close()

    threads = [
        threading.Thread(target=writer, args=(authority,)) for authority in authorities
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert outcomes == [command.decision.digest, command.decision.digest]
    connection = sqlite3.connect(path)
    assert (
        connection.execute("SELECT COUNT(*) FROM coverage_gap_decisions").fetchone()[0]
        == 1
    )
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    connection.close()


def test_allocated_schemas_authority_and_non_effects_are_exact() -> None:
    assert COVERAGE_COMMAND == "newsroom.increment7.coverage-command.v1"
    assert COVERAGE_ASSESSMENT == "newsroom.increment7.coverage-assessment.v1"
    assert COVERAGE_AUDIT_AUTHORITY == "CHECKED_SQLITE_TRANSACTIONAL_V28"
    assert COVERAGE_ASSESSMENT_AUTHORITY == "DETERMINISTIC_DEPENDENCY_TIMELINESS_HEALTH"
    command = _command()[0]
    for value in (command, command.assessment):
        assert value.authorises_external_effect is False
        assert value.authorises_credentials is False
        assert value.authorises_egress is False
        assert value.authorises_spend is False
        assert value.authorises_publication is False
        assert value.creates_candidate is False
        assert value.creates_watch is False
        assert value.production_activation_authorised is False
