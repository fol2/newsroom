from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from newsroom.authority.canonical import digest_canonical
from newsroom.authority.types import UtcTimestamp
from newsroom.increment5.branch_contracts import (
    CANDIDATE_COLLISION_POLICY_ID,
    EXACT_BRANCH_POLICY_ID,
    BranchExclusionReason,
    BranchOutcome,
    BranchReceiptId,
    BranchRequestId,
    CandidateCollisionRequest,
    ExactBranchRequest,
    ExactLookupKind,
    Increment5BranchContractError,
)
from newsroom.increment5.decision import INCREMENT_5A_CONTRACT_DIGEST
from newsroom.increment5.exact_retriever import SQLiteExactRetriever
from newsroom.increment5.receipt_journal import (
    BranchReceiptIdempotencyConflict,
    BranchReceiptJournal,
    BranchReceiptJournalError,
)


from .increment5b1_helpers import (
    LATER,
    NOW,
    _collision_request,
    _digest,
    _request,
    _system,
)


def test_exact_source_native_receipt_is_independent_and_restarts_byte_identically(
    tmp_path: Path,
) -> None:
    authority, journal_path, system = _system(tmp_path)
    first = system.retrieve(_request())
    assert first.replayed is False
    assert first.receipt.outcome is BranchOutcome.COMPLETE
    assert first.receipt.reason_code == "OK"
    assert first.receipt.authority_watermark == 3
    assert [item.authority_id for item in first.receipt.hits] == ["item-a"]
    assert first.receipt.hits[0].dependency_root_id == "item-a"
    assert first.receipt.external_call_count == 0
    assert first.receipt.gross_cost_microunits == 0
    assert first.receipt.authority_effect == "NONE"
    assert first.receipt.hybrid_result_claimed is False
    first_bytes = first.receipt.canonical_bytes

    restarted = SQLiteExactRetriever(
        authority_database=authority,
        journal=BranchReceiptJournal(journal_path),
        receipt_id_factory=lambda: pytest.fail("replay must not mint a receipt"),
    )
    replay = restarted.retrieve(_request())
    assert replay.replayed is True
    assert replay.receipt.canonical_bytes == first_bytes


def test_revision_id_and_source_native_token_are_distinct_scoped_lookups(
    tmp_path: Path,
) -> None:
    _authority, _journal, system = _system(tmp_path)
    by_id = system.retrieve(
        _request(
            key="revision-id",
            kind=ExactLookupKind.SOURCE_REVISION_ID,
            value="revision-a",
        )
    ).receipt
    by_token = system.retrieve(
        _request(
            key="revision-token",
            kind=ExactLookupKind.SOURCE_NATIVE_REVISION_TOKEN,
            value="revision-a",
            authority_scope_id="item-a",
        )
    ).receipt
    assert [item.authority_id for item in by_id.hits] == ["revision-a"]
    assert [item.match_signal for item in by_id.hits] == ["REVISION_ID_EQUAL"]
    assert [item.authority_id for item in by_token.hits] == ["revision-b"]
    assert [item.match_signal for item in by_token.hits] == [
        "SOURCE_NATIVE_REVISION_TOKEN_EQUAL"
    ]


def test_alias_lookup_excludes_retired_authority_without_erasing_lineage(
    tmp_path: Path,
) -> None:
    _authority, _journal, system = _system(tmp_path)
    result = system.retrieve(
        _request(
            key="alias-query",
            kind=ExactLookupKind.AUTHORITY_ALIAS,
            value="synthetic authority",
        )
    )
    assert result.receipt.outcome is BranchOutcome.COMPLETE
    assert result.receipt.reason_code == "OK_WITH_EXCLUSIONS"
    assert [item.authority_id for item in result.receipt.hits] == ["alias-active"]
    assert [(item.authority_id, item.reason) for item in result.receipt.exclusions] == [
        ("alias-retired", BranchExclusionReason.TOMBSTONED)
    ]


def test_rights_denied_match_is_policy_blocked(tmp_path: Path) -> None:
    _authority, _journal, system = _system(tmp_path)
    result = system.retrieve(
        _request(
            key="blocked-source",
            value="blocked-42",
            authority_scope_id="source-b",
        )
    )
    assert result.receipt.outcome is BranchOutcome.POLICY_BLOCKED
    assert result.receipt.reason_code == "RIGHTS_BLOCKED"
    assert not result.receipt.hits
    assert result.receipt.exclusions[0].reason is BranchExclusionReason.RIGHTS_NOT_CURRENT


def test_future_time_wrong_contract_and_wrong_policy_fail_before_sql(tmp_path: Path) -> None:
    authority, _journal, system = _system(tmp_path)
    before = authority.read_bytes()
    future = system.retrieve(
        _request(key="future", query_valid_time=LATER)
    ).receipt
    wrong_contract = system.retrieve(
        _request(key="wrong-contract", contract_digest=_digest("other-contract"))
    ).receipt
    wrong_policy = system.retrieve(
        _request(key="wrong-policy", policy_id="unreviewed-policy")
    ).receipt
    assert future.outcome is BranchOutcome.POLICY_BLOCKED
    assert future.reason_code == "QUERY_VALID_TIME_IN_FUTURE"
    assert wrong_contract.reason_code == "CONTRACT_MISMATCH"
    assert wrong_policy.reason_code == "POLICY_MISMATCH"
    assert authority.read_bytes() == before


def test_stale_watermark_and_missing_schema_are_explicit(tmp_path: Path) -> None:
    _authority, _journal, system = _system(tmp_path)
    stale = system.retrieve(
        _request(key="stale", minimum_ledger_seq=4)
    ).receipt
    assert stale.outcome is BranchOutcome.STALE
    assert stale.reason_code == "AUTHORITY_WATERMARK_STALE"

    empty = tmp_path / "empty.sqlite3"
    with sqlite3.connect(empty) as connection:
        connection.execute("CREATE TABLE unrelated(value TEXT) STRICT")
    unavailable = SQLiteExactRetriever(
        authority_database=empty,
        journal=BranchReceiptJournal(tmp_path / "empty-journal.sqlite3"),
    ).retrieve(_request(key="missing-schema")).receipt
    assert unavailable.outcome is BranchOutcome.UNAVAILABLE
    assert unavailable.reason_code == "AUTHORITY_SCHEMA_UNAVAILABLE"


def test_parameterised_input_cannot_escape_fixed_query(tmp_path: Path) -> None:
    _authority, _journal, system = _system(tmp_path)
    result = system.retrieve(
        _request(key="injection", value="' OR 1=1 --")
    ).receipt
    assert result.outcome is BranchOutcome.COMPLETE
    assert result.reason_code == "NO_MATCH"
    assert not result.hits


def test_result_overflow_fails_closed_instead_of_truncating(tmp_path: Path) -> None:
    authority, _journal, system = _system(tmp_path)
    with sqlite3.connect(authority) as connection:
        for index in range(9):
            entity_id = f"overflow-entity-{index}"
            connection.execute(
                "INSERT INTO canonical_entities VALUES(?,?,?)",
                (entity_id, f"overflow-event-{index}", _digest(entity_id)),
            )
            connection.execute(
                "INSERT INTO canonical_entity_heads VALUES(?,?)",
                (entity_id, "ACTIVE"),
            )
            connection.execute(
                "INSERT INTO entity_aliases VALUES(?,?,?,?,?,?,?,?)",
                (
                    f"overflow-alias-{index}",
                    entity_id,
                    "overflow alias",
                    "Overflow Alias",
                    f"overflow-resolution-{index}",
                    _digest(f"overflow-alias-{index}"),
                    None,
                    None,
                ),
            )
    result = system.retrieve(
        _request(
            key="overflow",
            kind=ExactLookupKind.AUTHORITY_ALIAS,
            value="overflow alias",
        )
    ).receipt
    assert result.outcome is BranchOutcome.INCOMPLETE
    assert result.reason_code == "RESULT_BOUND_EXCEEDED"
    assert not result.hits


def test_source_native_identity_is_scoped_to_one_source_definition(
    tmp_path: Path,
) -> None:
    authority, _journal, system = _system(tmp_path)
    with sqlite3.connect(authority) as connection:
        connection.execute(
            "INSERT INTO source_definition_versions VALUES(?,?,?,?)",
            ("source-v3", "source-c", "RETRIEVAL_ALLOWED", "PRODUCTION_ELIGIBLE"),
        )
        connection.execute(
            "INSERT INTO source_definition_version_heads VALUES(?,?)",
            ("source-c", "source-v3"),
        )
        connection.execute(
            "INSERT INTO source_items VALUES(?,?,?,?,?,?)",
            ("item-c", "source-c", "source-v3", "native-42", _digest("item-c"), "event-c"),
        )
    result = system.retrieve(_request(key="source-scoped", value="native-42")).receipt
    assert [item.authority_id for item in result.hits] == ["item-a"]


def test_current_source_head_withdrawal_blocks_historical_item_rights(
    tmp_path: Path,
) -> None:
    authority, _journal, system = _system(tmp_path)
    with sqlite3.connect(authority) as connection:
        connection.execute(
            "INSERT INTO source_definition_versions VALUES(?,?,?,?)",
            ("source-v1-withdrawn", "source-a", "PROHIBITED", "RETIRED"),
        )
        connection.execute(
            "UPDATE source_definition_version_heads SET current_version_id=? "
            "WHERE definition_id=?",
            ("source-v1-withdrawn", "source-a"),
        )
    result = system.retrieve(_request(key="withdrawn-current-rights")).receipt
    assert result.outcome is BranchOutcome.POLICY_BLOCKED
    assert result.reason_code == "RIGHTS_BLOCKED"
    assert not result.hits


def test_unreviewed_actor_or_unscoped_native_lookup_is_rejected() -> None:
    with pytest.raises(Increment5BranchContractError, match="actor and purpose"):
        ExactBranchRequest(
            request_id=BranchRequestId.new(),
            idempotency_key="wrong-actor",
            actor_id="other_worker",
            purpose="exact_identity_lookup",
            policy_id=EXACT_BRANCH_POLICY_ID,
            contract_digest=INCREMENT_5A_CONTRACT_DIGEST,
            lookup_kind=ExactLookupKind.SOURCE_NATIVE_ID,
            lookup_value="native-42",
            authority_scope_id="source-a",
            query_valid_time=NOW,
            serving_time=NOW,
        )
    with pytest.raises(Increment5BranchContractError, match="authority scope"):
        ExactBranchRequest(
            request_id=BranchRequestId.new(),
            idempotency_key="missing-scope",
            actor_id="retrieval_worker",
            purpose="exact_identity_lookup",
            policy_id=EXACT_BRANCH_POLICY_ID,
            contract_digest=INCREMENT_5A_CONTRACT_DIGEST,
            lookup_kind=ExactLookupKind.SOURCE_NATIVE_ID,
            lookup_value="native-42",
            query_valid_time=NOW,
            serving_time=NOW,
        )


def test_candidate_collision_is_relational_separate_and_has_no_ranking_or_creation(
    tmp_path: Path,
) -> None:
    authority, journal_path, system = _system(tmp_path)
    occupied = system.check_candidate_collision(_collision_request())
    assert occupied.replayed is False
    assert occupied.receipt.outcome is BranchOutcome.COMPLETE
    assert occupied.receipt.occupied is True
    assert occupied.receipt.candidate_id == "candidate-a"
    assert occupied.receipt.external_call_count == 0
    assert occupied.receipt.gross_cost_microunits == 0
    assert occupied.receipt.hybrid_result_claimed is False
    assert occupied.receipt.ranking_performed is False
    assert occupied.receipt.candidate_created is False
    assert occupied.receipt.authority_effect == "NONE"

    restarted = SQLiteExactRetriever(
        authority_database=authority,
        journal=BranchReceiptJournal(journal_path),
        receipt_id_factory=lambda: pytest.fail("collision replay must not mint a receipt"),
    )
    replay = restarted.check_candidate_collision(_collision_request())
    assert replay.replayed is True
    assert replay.receipt.canonical_bytes == occupied.receipt.canonical_bytes

    free = system.check_candidate_collision(
        _collision_request(key="collision-free", digest=_digest("free"))
    ).receipt
    assert free.outcome is BranchOutcome.COMPLETE
    assert free.reason_code == "UNOCCUPIED"
    assert free.occupied is False
    assert free.candidate_id is None


def test_journal_rejects_semantic_conflict_and_retains_immutable_rows(tmp_path: Path) -> None:
    _authority, journal_path, system = _system(tmp_path)
    system.retrieve(_request())
    with pytest.raises(BranchReceiptIdempotencyConflict):
        system.retrieve(_request(value="different-native"))

    with sqlite3.connect(journal_path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE increment5_branch_receipts SET receipt_digest='sha256:0000000000000000000000000000000000000000000000000000000000000000'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="retained"):
            connection.execute("DELETE FROM increment5_branch_receipts")


def test_journal_detects_corrupted_receipt_bytes(tmp_path: Path) -> None:
    authority, journal_path, system = _system(tmp_path)
    system.retrieve(_request())
    with sqlite3.connect(journal_path) as connection:
        connection.execute("DROP TRIGGER immutable_increment5_branch_receipt_update")
        connection.execute(
            "UPDATE increment5_branch_receipts SET receipt_bytes=?",
            (b"{}",),
        )
    restarted = SQLiteExactRetriever(
        authority_database=authority,
        journal=BranchReceiptJournal(journal_path),
    )
    with pytest.raises(BranchReceiptJournalError, match="digest differs"):
        restarted.retrieve(_request())


def test_request_bounds_reject_oversize_and_unbounded_controls() -> None:
    with pytest.raises(Increment5BranchContractError, match="bounded"):
        _request(value="x" * 513)
    with pytest.raises(Increment5BranchContractError, match="fixed at 8"):
        ExactBranchRequest(
            request_id=BranchRequestId.new(),
            idempotency_key="bad-limit",
            actor_id="retrieval_worker",
            purpose="exact_identity_lookup",
            policy_id=EXACT_BRANCH_POLICY_ID,
            contract_digest=INCREMENT_5A_CONTRACT_DIGEST,
            lookup_kind=ExactLookupKind.SOURCE_NATIVE_ID,
            lookup_value="native-42",
            authority_scope_id="source-a",
            query_valid_time=NOW,
            serving_time=NOW,
            result_limit=9,
        )

@pytest.mark.parametrize(
    ("kind", "value", "expected_id", "expected_root"),
    [
        (ExactLookupKind.REPRESENTATION_ID, "representation-a", "representation-a", "revision-a"),
        (ExactLookupKind.CANONICAL_ENTITY_ID, "entity-active", "entity-active", "entity-active"),
        (ExactLookupKind.FORMAL_PROCESS_ID, "formal-process-a", "candidate-version-a", "formal-process-a"),
    ],
)
def test_remaining_exact_lookup_kinds_are_fixed_and_attributable(
    tmp_path: Path,
    kind: ExactLookupKind,
    value: str,
    expected_id: str,
    expected_root: str,
) -> None:
    _authority, _journal, system = _system(tmp_path)
    result = system.retrieve(
        _request(key=f"lookup-{kind.value.lower()}", kind=kind, value=value)
    ).receipt
    assert result.outcome is BranchOutcome.COMPLETE
    assert [item.authority_id for item in result.hits] == [expected_id]
    assert result.hits[0].dependency_root_id == expected_root


def test_elapsed_overrun_is_an_explicit_incomplete_timeout(tmp_path: Path) -> None:
    authority, journal_path, _system_value = _system(tmp_path)
    ticks = iter((0, 5_000_000_001))
    system = SQLiteExactRetriever(
        authority_database=authority,
        journal=BranchReceiptJournal(journal_path),
        monotonic_ns=lambda: next(ticks),
    )
    result = system.retrieve(_request(key="elapsed-overrun")).receipt
    assert result.outcome is BranchOutcome.INCOMPLETE
    assert result.reason_code == "QUERY_TIMEOUT"
    assert result.elapsed_ms == 5_000
    assert not result.hits
