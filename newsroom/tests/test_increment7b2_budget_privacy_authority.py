from __future__ import annotations

import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from newsroom.authority import migrations
from newsroom.authority.bounded_search_migrations import (
    BOUNDED_SEARCH_MIGRATION_CHECKSUM,
    BOUNDED_SEARCH_MIGRATION_NAME,
    BOUNDED_SEARCH_PREDECESSOR_FINGERPRINT,
    BOUNDED_SEARCH_SCHEMA_VERSION,
    bounded_search_backup_paths,
    prepare_bounded_search_backup,
)
from newsroom.authority.canonical import digest_bytes
from newsroom.authority.migrations import (
    EXPECTED_MIGRATION_HISTORY,
    EXPECTED_SCHEMA_FINGERPRINT,
    SCHEMA_VERSION,
    apply_pending_migrations,
    schema_fingerprint,
)
from newsroom.increment7.search import (
    SearchAttempt,
    SearchDownstreamRoute,
    SearchLimits,
    SearchOutcome,
    SearchOutcomeKind,
    SearchPurpose,
    SearchPurposeKind,
    SearchQueryPrivacy,
    SearchRequest,
    SearchResultReference,
    SearchResultRetention,
    SearchReviewAction,
    SearchReviewDecision,
)
from newsroom.increment7.search_authority import (
    BOUNDED_SEARCH_AUTHORITY,
    SEARCH_PROVIDER_PORT,
    BoundedSearchReadPort,
    SearchAuthorityError,
    open_bounded_search_authority,
)

_AT = "2026-08-14T00:00:00.000000Z"
_D = "sha256:" + "a" * 64


def _id(value: int) -> str:
    return str(uuid.UUID(int=value, version=4))


def _purpose() -> SearchPurpose:
    return SearchPurpose(
        _id(1),
        SearchPurposeKind.PROSPECTIVE_RECALL_AUDIT,
        ("OWNER_APPROVED",),
        ("UK:PUBLIC_POLICY",),
        SearchQueryPrivacy.PUBLIC_ONLY,
        SearchPurposeKind.PROSPECTIVE_RECALL_AUDIT,
        (SearchDownstreamRoute.COVERAGE_AUDIT,),
        "rights-v1",
        (_D,),
        _AT,
    )


def _request(purpose: SearchPurpose | None = None) -> SearchRequest:
    purpose = purpose or _purpose()
    return SearchRequest(
        _id(2),
        purpose.purpose_id,
        purpose.digest,
        "OWNER_APPROVED",
        "sha256:" + "b" * 64,
        "sha256:" + "c" * 64,
        "fixture-provider",
        "sha256:" + "d" * 64,
        "recall-audit-v1",
        "sha256:" + "e" * 64,
        'site:gov.uk "policy decision"',
        (
            'site:gov.uk "policy decision"',
            'site:gov.uk "policy announcement"',
        ),
        ("en-GB",),
        ("United Kingdom",),
        ("gov.uk",),
        "2026-08-13T00:00:00.000000Z",
        _AT,
        SearchLimits(2, 2, 2, 1, 1, 1, 3, 1, 86_400, 60, 1, 150),
        purpose.query_privacy,
        purpose.rights_policy_version,
        "sha256:" + "f" * 64,
        (SearchDownstreamRoute.COVERAGE_AUDIT,),
        purpose.permitted_coverage,
        "sha256:" + "1" * 64,
        purpose.governing_policy_digests,
        _AT,
    )


def _attempt(request: SearchRequest, value: int = 3, ordinal: int = 1) -> SearchAttempt:
    return SearchAttempt(
        _id(value),
        request.request_id,
        request.digest,
        ordinal,
        request.provider_id,
        request.provider_configuration_digest,
        digest_bytes(request.query_variants[ordinal - 1].encode()),
        ordinal,
        1,
        ordinal,
        ordinal - 1,
        ordinal - 1,
        f"2026-08-14T00:00:0{ordinal}.000000Z",
    )


def _outcome(attempt: SearchAttempt, value: int = 4, cost: int = 100) -> SearchOutcome:
    return SearchOutcome(
        _id(value),
        attempt.attempt_id,
        attempt.digest,
        SearchOutcomeKind.SUCCESS_RESULTS,
        1,
        1,
        cost,
        None,
        "en-GB",
        None,
        f"2026-08-14T00:00:0{attempt.attempt_ordinal + 2}.000000Z",
    )


def _result(
    attempt: SearchAttempt, outcome: SearchOutcome, value: int = 5
) -> SearchResultReference:
    return SearchResultReference(
        _id(value),
        outcome.outcome_id,
        outcome.digest,
        attempt.request_id,
        attempt.request_digest,
        attempt.provider_id,
        attempt.provider_configuration_digest,
        f"provider-result-{value}",
        1,
        attempt.page_number,
        f"https://example.org/report-{value}",
        "Example Publisher",
        "Policy decision",
        None,
        "2026-08-14",
        "en-GB",
        "news",
        (),
        SearchResultRetention.ATTRIBUTED_METADATA,
        "rights-v1",
        f"2026-08-14T00:00:0{attempt.attempt_ordinal + 4}.000000Z",
    )


def _decision(result: SearchResultReference) -> SearchReviewDecision:
    return SearchReviewDecision(
        _id(6),
        (result.result_reference_id,),
        (result.digest,),
        SearchReviewAction.SUPPORT_COVERAGE_GAP_REVIEW,
        "sha256:" + "2" * 64,
        "sha256:" + "3" * 64,
        ("PROSPECTIVE_COMPARATOR_HIT",),
        "2026-08-14T00:00:07.000000Z",
    )


def _downgrade_empty_v27_to_v26(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys=OFF")
    immutable = connection.execute(
        "SELECT sql FROM sqlite_master WHERE name='immutable_authority_migrations_delete'"
    ).fetchone()[0]
    connection.execute("DROP TRIGGER immutable_authority_migrations_delete")
    for table in (
        "search_budget_ledger",
        "search_review_decisions",
        "search_result_references",
        "search_outcomes",
        "search_attempts",
        "search_requests",
        "search_purposes",
    ):
        for (name,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",
            (table,),
        ).fetchall():
            connection.execute(f'DROP TRIGGER "{name}"')
        connection.execute(f"DROP TABLE {table}")
    connection.execute("DELETE FROM authority_migrations WHERE version=27")
    connection.execute(immutable)
    connection.execute("PRAGMA user_version=26")
    connection.execute("PRAGMA foreign_keys=ON")


def _record_chain(authority):
    purpose = _purpose()
    request = _request(purpose)
    attempt = _attempt(request)
    outcome = _outcome(attempt)
    result = _result(attempt, outcome)
    decision = _decision(result)
    authority.record_purpose(purpose.canonical_bytes)
    authority.record_request(request.canonical_bytes)
    authority.record_attempt(attempt.canonical_bytes)
    authority.record_outcome(outcome.canonical_bytes)
    authority.record_result(result.canonical_bytes)
    authority.record_review(decision.canonical_bytes)
    return purpose, request, attempt, outcome, result, decision


def test_v27_fresh_history_fingerprint_integrity_and_reserved_tables() -> None:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.execute("PRAGMA foreign_keys=ON")
    apply_pending_migrations(connection, applied_at=_AT)
    assert SCHEMA_VERSION == BOUNDED_SEARCH_SCHEMA_VERSION == 27
    assert EXPECTED_MIGRATION_HISTORY[-1] == (
        27,
        BOUNDED_SEARCH_MIGRATION_NAME,
        BOUNDED_SEARCH_MIGRATION_CHECKSUM,
    )
    assert schema_fingerprint(connection) == EXPECTED_SCHEMA_FINGERPRINT
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
    assert {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'search_%'"
        )
    } == {
        "search_purposes",
        "search_requests",
        "search_attempts",
        "search_outcomes",
        "search_result_references",
        "search_review_decisions",
        "search_budget_ledger",
    }


def test_v26_upgrade_requires_exact_backup_and_rolls_back_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "search.sqlite3"
    connection = sqlite3.connect(database, isolation_level=None)
    connection.execute("PRAGMA foreign_keys=ON")
    apply_pending_migrations(connection, applied_at=_AT)
    _downgrade_empty_v27_to_v26(connection)
    assert schema_fingerprint(connection) == BOUNDED_SEARCH_PREDECESSOR_FINGERPRINT
    with pytest.raises(Exception, match="prepared backup"):
        apply_pending_migrations(connection, applied_at=_AT)
    backup, digest_path = bounded_search_backup_paths(database)
    receipt = prepare_bounded_search_backup(connection, backup)
    assert receipt.backup_path == backup and digest_path.exists()
    statements = migrations.BOUNDED_SEARCH_MIGRATION_STATEMENTS
    monkeypatch.setattr(
        migrations,
        "BOUNDED_SEARCH_MIGRATION_STATEMENTS",
        (statements[0], "CREATE TABLE deliberate_failure("),
    )
    with pytest.raises(sqlite3.OperationalError):
        apply_pending_migrations(connection, applied_at=_AT)
    assert connection.execute("PRAGMA user_version").fetchone() == (26,)
    assert schema_fingerprint(connection) == BOUNDED_SEARCH_PREDECESSOR_FINGERPRINT
    monkeypatch.setattr(migrations, "BOUNDED_SEARCH_MIGRATION_STATEMENTS", statements)
    apply_pending_migrations(connection, applied_at=_AT)
    assert connection.execute("PRAGMA user_version").fetchone() == (27,)
    restored = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)
    try:
        assert restored.execute("PRAGMA user_version").fetchone() == (26,)
        assert schema_fingerprint(restored) == BOUNDED_SEARCH_PREDECESSOR_FINGERPRINT
    finally:
        restored.close()


def test_exact_chain_replays_across_restart_without_provider_authority(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    authority = open_bounded_search_authority(database, applied_at=_AT)
    records = _record_chain(authority)
    for record, reread in zip(
        records,
        (
            authority.purpose(records[0].purpose_id),
            authority.request(records[1].request_id),
            authority.attempt(records[2].attempt_id),
            authority.outcome(records[3].outcome_id),
            authority.result(records[4].result_reference_id),
            authority.review(records[5].review_decision_id),
        ),
        strict=True,
    ):
        assert reread == record
        assert record.authorises_provider is False
    assert authority.budget(records[1].request_id).gross_cost_microunits == 100
    assert isinstance(authority.read_port(), BoundedSearchReadPort)
    assert BOUNDED_SEARCH_AUTHORITY == "CHECKED_SQLITE_TRANSACTIONAL_V27"
    assert SEARCH_PROVIDER_PORT == "DISABLED_NO_IMPLEMENTATION"
    assert not hasattr(authority, "search") and not hasattr(authority, "execute")
    authority.close()
    reopened = open_bounded_search_authority(database, applied_at=_AT)
    try:
        assert reopened.review(records[5].review_decision_id) == records[5]
        assert reopened.record_purpose(records[0].canonical_bytes) == records[0]
        with pytest.raises(SearchAuthorityError, match="replay conflicts"):
            reopened.record_purpose(
                replace(records[0], rights_policy_version="rights-v2").canonical_bytes
            )
    finally:
        reopened.close()


def test_gross_budget_attempt_order_and_result_limits_fail_closed(
    tmp_path: Path,
) -> None:
    authority = open_bounded_search_authority(
        tmp_path / "budget.sqlite3", applied_at=_AT
    )
    try:
        purpose, request, first, first_outcome, *_ = _record_chain(authority)
        second = _attempt(request, 13, 2)
        authority.record_attempt(second.canonical_bytes)
        over_budget = _outcome(second, 14, 51)
        with pytest.raises(SearchAuthorityError, match="gross budget"):
            authority.record_outcome(over_budget.canonical_bytes)
        assert authority.budget(request.request_id).gross_cost_microunits == 100
        gap = replace(second, attempt_id=_id(30), attempt_ordinal=3)
        with pytest.raises(SearchAuthorityError, match="ordinal CAS"):
            authority.record_attempt(gap.canonical_bytes)
        duplicate_rank = replace(
            _result(first, first_outcome, 15),
            result_reference_id=_id(15),
        )
        with pytest.raises(SearchAuthorityError, match="result budget|persistence"):
            authority.record_result(duplicate_rank.canonical_bytes)
        assert authority.purpose(purpose.purpose_id) == purpose
    finally:
        authority.close()


def test_concurrent_first_attempt_has_one_cas_winner(tmp_path: Path) -> None:
    database = tmp_path / "concurrent.sqlite3"
    seed = open_bounded_search_authority(database, applied_at=_AT)
    purpose = _purpose()
    request = _request(purpose)
    seed.record_purpose(purpose.canonical_bytes)
    seed.record_request(request.canonical_bytes)
    seed.close()
    barrier = threading.Barrier(2)

    def write(value: int) -> str:
        authority = open_bounded_search_authority(database, applied_at=_AT)
        try:
            attempt = _attempt(request, value, 1)
            barrier.wait()
            authority.record_attempt(attempt.canonical_bytes)
            return "ok"
        except SearchAuthorityError:
            return "blocked"
        finally:
            authority.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, (20, 21))) == ["blocked", "ok"]
    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT count(*) FROM search_attempts"
        ).fetchone() == (1,)
    finally:
        connection.close()

    ordered_database = tmp_path / "out-of-order.sqlite3"
    ordered = open_bounded_search_authority(ordered_database, applied_at=_AT)
    purpose = _purpose()
    request = replace(
        _request(purpose),
        request_id=_id(40),
        budget_reservation_digest="sha256:" + "4" * 64,
        limits=replace(_request(purpose).limits, max_concurrent_attempts=2),
    )
    first = _attempt(request, 41, 1)
    second = _attempt(request, 42, 2)
    ordered.record_purpose(purpose.canonical_bytes)
    ordered.record_request(request.canonical_bytes)
    ordered.record_attempt(first.canonical_bytes)
    ordered.record_attempt(second.canonical_bytes)
    second_outcome = replace(
        _outcome(second, 43, 40),
        completed_at="2026-08-14T00:00:03.000000Z",
    )
    first_outcome = replace(
        _outcome(first, 44, 40),
        completed_at="2026-08-14T00:00:04.000000Z",
    )
    ordered.record_outcome(second_outcome.canonical_bytes)
    ordered.record_outcome(first_outcome.canonical_bytes)
    assert ordered.budget(request.request_id).provider_calls == 2
    assert ordered.budget(request.request_id).gross_cost_microunits == 80
    ordered.close()


def test_immutable_rows_and_relational_tamper_are_detected(tmp_path: Path) -> None:
    database = tmp_path / "tamper.sqlite3"
    authority = open_bounded_search_authority(database, applied_at=_AT)
    records = _record_chain(authority)
    attacker = sqlite3.connect(database, isolation_level=None)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            attacker.execute(
                "UPDATE search_requests SET query_privacy='OTHER' WHERE request_id=?",
                (records[1].request_id,),
            )
        attacker.execute("DROP TRIGGER immutable_search_budget_ledger")
        attacker.execute(
            "UPDATE search_budget_ledger SET cumulative_gross_cost_microunits=1 "
            "WHERE request_id=?",
            (records[1].request_id,),
        )
        with pytest.raises(SearchAuthorityError, match="retained gross budget"):
            authority.budget(records[1].request_id)
        attacker.execute("DROP TRIGGER immutable_search_requests")
        attacker.execute(
            "UPDATE search_requests SET query_privacy='OTHER' WHERE request_id=?",
            (records[1].request_id,),
        )
        with pytest.raises(SearchAuthorityError, match="retained columns"):
            authority.request(records[1].request_id)
    finally:
        attacker.close()
        authority.close()
    with pytest.raises(SearchAuthorityError, match="schema differs"):
        open_bounded_search_authority(database, applied_at=_AT)
