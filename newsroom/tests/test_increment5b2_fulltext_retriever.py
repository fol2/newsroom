from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment5.branch_contracts import (
    BranchExclusionReason,
    BranchOutcome,
)
from newsroom.increment5.fulltext_contracts import (
    FULLTEXT_COMPONENT_DIGEST,
    FULLTEXT_INDEXED_FIELDS,
    FULLTEXT_QUERY_ID,
    NORMALIZATION_COMPONENT_DIGEST,
    FullTextContractError,
    FullTextIndexState,
)
from newsroom.increment5.fulltext_journal import (
    FullTextReceiptIdempotencyConflict,
    FullTextReceiptJournal,
    FullTextReceiptJournalError,
)
from newsroom.increment5.fulltext_retriever import FullTextRetriever
from newsroom.projection.models import ProjectionGenerationId, ProjectionGenerationState

from .increment5b2_helpers import (
    GENERATION_ID,
    LATER,
    NOW,
    FakeDriver,
    FakeScenario,
    SequenceClock,
    authority_view,
    bindings,
    component_row,
    default_scenario,
    digest,
    index_row,
    request,
    result_row,
    snapshot,
    system,
)


def test_complete_fulltext_receipt_is_bounded_attributable_and_replayable(
    tmp_path: Path,
) -> None:
    driver, work_factory, retriever = system(tmp_path)

    first = retriever.retrieve(request())
    assert first.replayed is False
    receipt = first.receipt
    assert receipt.outcome is BranchOutcome.COMPLETE
    assert receipt.reason_code == "OK"
    assert [item.passage_id for item in receipt.hits] == ["p-en", "p-zh"]
    assert [item.rank for item in receipt.hits] == [1, 2]
    assert [item.dependency_root_id for item in receipt.hits] == [
        "root-en",
        "root-zh",
    ]
    assert all(item.trust_scope.value == "OBSERVED" for item in receipt.hits)
    assert receipt.authority_read_count == 1
    assert receipt.neo4j_read_count == 3
    assert receipt.external_call_count == 0
    assert receipt.gross_cost_microunits == 0
    assert receipt.authority_effect == "NONE"
    assert receipt.hybrid_result_claimed is False
    assert receipt.projection_text_factual_use_allowed is False
    assert receipt.snapshot is not None
    assert receipt.normalized_query is not None
    assert all(
        item.query_id == FULLTEXT_QUERY_ID
        and item.query_digest == receipt.normalized_query.query_digest
        for item in receipt.hits
    )
    assert receipt.authority_view_digest is not None
    assert len(receipt.canonical_bytes) < 262_144

    assert driver.execute_read_count == 3
    assert len(driver.calls) == 3
    fulltext_statement, parameters = driver.calls[-1]
    assert request().query_text not in fulltext_statement
    assert parameters["index_name"] == snapshot().index_name
    assert parameters["generation_id"] == str(GENERATION_ID)
    assert parameters["limit"] == 9
    assert "\\(" not in str(parameters["query"])
    before_calls = list(driver.calls)
    replay = retriever.retrieve(request())
    assert replay.replayed is True
    assert replay.receipt.canonical_bytes == receipt.canonical_bytes
    assert driver.calls == before_calls


def test_restart_returns_first_receipt_without_authority_or_neo4j_calls(
    tmp_path: Path,
) -> None:
    driver, _factory, retriever = system(tmp_path)
    first = retriever.retrieve(request()).receipt

    failing_driver = FakeDriver(default_scenario())
    restarted = FullTextRetriever(
        graph_reader=failing_driver.reader(),
        journal=FullTextReceiptJournal(
            tmp_path / "fulltext-receipts.sqlite3"
        ),
        authority_view_provider=lambda _request: pytest.fail(
            "replay must not read authority"
        ),
        receipt_id_factory=lambda: pytest.fail(
            "replay must not mint a receipt"
        ),
        monotonic_ns=lambda: 0,
    )
    replay = restarted.retrieve(request())

    assert replay.replayed is True
    assert replay.receipt.canonical_bytes == first.canonical_bytes
    assert failing_driver.calls == []


def test_no_match_is_complete_only_after_all_three_neo4j_reads(
    tmp_path: Path,
) -> None:
    driver, _factory, retriever = system(
        tmp_path,
        scenario=default_scenario(rows=[]),
    )
    receipt = retriever.retrieve(
        request(idempotency_key="no-match")
    ).receipt

    assert receipt.outcome is BranchOutcome.COMPLETE
    assert receipt.reason_code == "NO_MATCH"
    assert receipt.neo4j_read_count == 3
    assert not receipt.hits
    assert driver.execute_read_count == 3


@pytest.mark.parametrize(
    ("lifecycle", "reason"),
    [
        ("HELD", BranchExclusionReason.STALE_SOURCE_VERSION),
        ("UNRESOLVED", BranchExclusionReason.STALE_SOURCE_VERSION),
        ("PROPOSED", BranchExclusionReason.STALE_SOURCE_VERSION),
        ("MERGED", BranchExclusionReason.TOMBSTONED),
        ("SPLIT", BranchExclusionReason.TOMBSTONED),
        ("REVERSED", BranchExclusionReason.TOMBSTONED),
    ],
)
def test_every_nonactive_passage_lifecycle_is_excluded(
    lifecycle: str,
    reason: BranchExclusionReason,
) -> None:
    binding = replace(bindings()[1], lifecycle=lifecycle)
    assert binding.exclusion_at(NOW) is reason


def test_current_rights_and_lifecycle_exclusions_are_explicit(
    tmp_path: Path,
) -> None:
    rows = [
        result_row("p-blocked", 3.0),
        result_row("p-tomb", 2.0),
        result_row("p-en", 1.0),
    ]
    _driver, _factory, retriever = system(
        tmp_path,
        scenario=default_scenario(rows=rows),
    )
    receipt = retriever.retrieve(
        request(idempotency_key="with-exclusions")
    ).receipt

    assert receipt.outcome is BranchOutcome.COMPLETE
    assert receipt.reason_code == "OK_WITH_EXCLUSIONS"
    assert [item.passage_id for item in receipt.hits] == ["p-en"]
    assert [(item.authority_id, item.reason) for item in receipt.exclusions] == [
        ("p-blocked", BranchExclusionReason.RIGHTS_NOT_CURRENT),
        ("p-tomb", BranchExclusionReason.TOMBSTONED),
    ]


def test_wholly_ineligible_result_set_is_not_reported_as_no_match(
    tmp_path: Path,
) -> None:
    rows = [
        result_row("p-blocked", 3.0),
        result_row("p-tomb", 2.0),
    ]
    _driver, _factory, retriever = system(
        tmp_path,
        scenario=default_scenario(rows=rows),
    )
    receipt = retriever.retrieve(
        request(idempotency_key="all-excluded")
    ).receipt

    assert receipt.outcome is BranchOutcome.POLICY_BLOCKED
    assert receipt.reason_code == "RIGHTS_BLOCKED"
    assert not receipt.hits
    assert len(receipt.exclusions) == 2


@pytest.mark.parametrize(
    ("changes", "outcome", "reason"),
    [
        (
            {"generation_state": ProjectionGenerationState.RETIRED},
            BranchOutcome.STALE,
            "GENERATION_NOT_ACTIVE",
        ),
        (
            {
                "generation_id": ProjectionGenerationId.parse(
                    "00000000-0000-4000-8000-000000005299"
                )
            },
            BranchOutcome.STALE,
            "GENERATION_MISMATCH",
        ),
        (
            {"generation_identity_digest": digest("other-generation")},
            BranchOutcome.STALE,
            "GENERATION_IDENTITY_MISMATCH",
        ),
        (
            {"fulltext_component_digest": digest("other-fulltext")},
            BranchOutcome.STALE,
            "GENERATION_COMPONENT_MISMATCH",
        ),
        (
            {"rights_manifest_digest": digest("other-rights")},
            BranchOutcome.STALE,
            "RIGHTS_MANIFEST_MISMATCH",
        ),
        (
            {"contiguous_ledger_seq": 41},
            BranchOutcome.STALE,
            "PROJECTION_WATERMARK_STALE",
        ),
        (
            {"open_gap_count": 1},
            BranchOutcome.INCOMPLETE,
            "PROJECTION_GAPS_OPEN",
        ),
        (
            {"dead_letter_count": 1},
            BranchOutcome.INCOMPLETE,
            "PROJECTION_DEAD_LETTERS_PRESENT",
        ),
        (
            {"freshness_deadline": NOW},
            BranchOutcome.COMPLETE,
            "OK",
        ),
        (
            {"index_state": FullTextIndexState.POPULATING},
            BranchOutcome.INCOMPLETE,
            "FULLTEXT_INDEX_POPULATING",
        ),
        (
            {"index_state": FullTextIndexState.FAILED},
            BranchOutcome.UNAVAILABLE,
            "FULLTEXT_INDEX_UNAVAILABLE",
        ),
        (
            {"provider": "fulltext-1.0"},
            BranchOutcome.UNAVAILABLE,
            "COMPONENT_INCOMPATIBLE",
        ),
        (
            {"analyzer": "standard"},
            BranchOutcome.UNAVAILABLE,
            "COMPONENT_INCOMPATIBLE",
        ),
        (
            {"server_version": "2026.05.0"},
            BranchOutcome.UNAVAILABLE,
            "COMPONENT_INCOMPATIBLE",
        ),
    ],
)
def test_snapshot_failures_have_explicit_outcomes(
    tmp_path: Path,
    changes: dict[str, object],
    outcome: BranchOutcome,
    reason: str,
) -> None:
    current = snapshot(**changes)
    view = authority_view(projection_snapshot=current)
    scenario = default_scenario(projection_snapshot=current)
    _driver, _factory, retriever = system(
        tmp_path,
        view=view,
        scenario=scenario,
    )
    receipt = retriever.retrieve(
        request(idempotency_key=f"snapshot-{reason.lower()}")
    ).receipt

    assert receipt.outcome is outcome
    assert receipt.reason_code == reason
    assert receipt.authority_read_count == 1
    if reason != "OK":
        assert receipt.neo4j_read_count == 0


def test_projection_age_beyond_hard_hour_is_stale(tmp_path: Path) -> None:
    current = snapshot(
        validation_recorded_at=type(NOW).parse(
            "2042-03-12T10:59:59.000000Z"
        ),
        freshness_deadline=LATER,
    )
    _driver, _factory, retriever = system(
        tmp_path,
        view=authority_view(projection_snapshot=current),
        scenario=default_scenario(projection_snapshot=current),
    )
    receipt = retriever.retrieve(
        request(idempotency_key="age-stale")
    ).receipt

    assert receipt.outcome is BranchOutcome.STALE
    assert receipt.reason_code == "PROJECTION_FRESHNESS_STALE"


@pytest.mark.parametrize(
    ("indexes", "outcome", "reason"),
    [
        ([], BranchOutcome.UNAVAILABLE, "FULLTEXT_INDEX_MISSING"),
        (
            [index_row(state="POPULATING")],
            BranchOutcome.INCOMPLETE,
            "FULLTEXT_INDEX_POPULATING",
        ),
        (
            [index_row(state="FAILED")],
            BranchOutcome.UNAVAILABLE,
            "FULLTEXT_INDEX_UNAVAILABLE",
        ),
        (
            [index_row(provider="fulltext-1.0")],
            BranchOutcome.UNAVAILABLE,
            "FULLTEXT_INDEX_INCOMPATIBLE",
        ),
        (
            [index_row(analyzer="standard")],
            BranchOutcome.UNAVAILABLE,
            "FULLTEXT_INDEX_INCOMPATIBLE",
        ),
        (
            [index_row(eventually_consistent=True)],
            BranchOutcome.UNAVAILABLE,
            "FULLTEXT_INDEX_INCOMPATIBLE",
        ),
        (
            [index_row(properties=("retrieval_text",))],
            BranchOutcome.UNAVAILABLE,
            "FULLTEXT_INDEX_INCOMPATIBLE",
        ),
        (
            [index_row(), index_row()],
            BranchOutcome.UNAVAILABLE,
            "FULLTEXT_INDEX_AMBIGUOUS",
        ),
    ],
)
def test_live_index_inventory_fails_closed(
    tmp_path: Path,
    indexes: list[dict[str, object]],
    outcome: BranchOutcome,
    reason: str,
) -> None:
    scenario = default_scenario()
    scenario.indexes = indexes
    _driver, _factory, retriever = system(
        tmp_path,
        scenario=scenario,
    )
    receipt = retriever.retrieve(
        request(idempotency_key=f"index-{reason.lower()}")
    ).receipt

    assert receipt.outcome is outcome
    assert receipt.reason_code == reason
    assert receipt.neo4j_read_count == 2
    assert not receipt.hits


def test_live_neo4j_component_mismatch_is_unavailable(tmp_path: Path) -> None:
    scenario = default_scenario()
    scenario.component = component_row(version="2026.05.0")
    _driver, _factory, retriever = system(
        tmp_path,
        scenario=scenario,
    )
    receipt = retriever.retrieve(
        request(idempotency_key="live-component-mismatch")
    ).receipt

    assert receipt.outcome is BranchOutcome.UNAVAILABLE
    assert receipt.reason_code == "NEO4J_INCOMPATIBLE"
    assert receipt.neo4j_read_count == 1


def test_driver_version_mismatch_fails_before_authority_read(
    tmp_path: Path,
) -> None:
    calls = 0

    def provider(_request):
        nonlocal calls
        calls += 1
        return authority_view()

    driver = FakeDriver(default_scenario())
    retriever = FullTextRetriever(
        graph_reader=driver.reader(driver_version="6.1.0"),
        journal=FullTextReceiptJournal(tmp_path / "driver-mismatch.sqlite3"),
        authority_view_provider=provider,
        monotonic_ns=lambda: 0,
    )
    receipt = retriever.retrieve(
        request(idempotency_key="driver-mismatch")
    ).receipt

    assert receipt.outcome is BranchOutcome.UNAVAILABLE
    assert receipt.reason_code == "DRIVER_INCOMPATIBLE"
    assert receipt.authority_read_count == 0
    assert calls == 0
    assert driver.calls == []


def test_untyped_authority_view_returns_journaled_unavailable_receipt(
    tmp_path: Path,
) -> None:
    driver = FakeDriver(default_scenario())
    retriever = FullTextRetriever(
        graph_reader=driver.reader(),
        journal=FullTextReceiptJournal(
            tmp_path / "untyped-authority.sqlite3"
        ),
        authority_view_provider=lambda _request: object(),
        monotonic_ns=lambda: 0,
    )
    current_request = request(idempotency_key="untyped-authority-view")

    first = retriever.retrieve(current_request)
    receipt = first.receipt

    assert first.replayed is False
    assert receipt.outcome is BranchOutcome.UNAVAILABLE
    assert receipt.reason_code == "AUTHORITY_VIEW_UNAVAILABLE"
    assert receipt.authority_read_count == 0
    assert receipt.neo4j_read_count == 0
    assert receipt.snapshot is None
    assert receipt.authority_view_digest is None
    assert driver.calls == []

    replay = retriever.retrieve(current_request)
    assert replay.replayed is True
    assert replay.receipt.canonical_bytes == receipt.canonical_bytes
    assert driver.calls == []


def test_noncanonical_authority_view_returns_journaled_unavailable_receipt(
    tmp_path: Path,
) -> None:
    corrupt_snapshot = snapshot()
    object.__setattr__(
        corrupt_snapshot,
        "contiguous_ledger_seq",
        9_007_199_254_740_992,
    )
    noncanonical_view = authority_view(
        projection_snapshot=corrupt_snapshot
    )
    driver, _factory, retriever = system(
        tmp_path,
        view=noncanonical_view,
    )
    current_request = request(
        idempotency_key="noncanonical-authority-view"
    )

    first = retriever.retrieve(current_request)
    receipt = first.receipt

    assert first.replayed is False
    assert receipt.outcome is BranchOutcome.UNAVAILABLE
    assert receipt.reason_code == "AUTHORITY_VIEW_UNAVAILABLE"
    assert receipt.authority_read_count == 0
    assert receipt.neo4j_read_count == 0
    assert receipt.snapshot is None
    assert receipt.authority_view_digest is None
    assert driver.calls == []

    replay = retriever.retrieve(current_request)
    assert replay.replayed is True
    assert replay.receipt.canonical_bytes == receipt.canonical_bytes
    assert driver.calls == []


def test_result_overflow_is_incomplete_instead_of_truncated(
    tmp_path: Path,
) -> None:
    custom_bindings = tuple(
        replace(
            bindings()[1],
            passage_id=f"p-overflow-{index}",
            dependency_root_id=f"root-overflow-{index}",
            source_identity=f"source-overflow:revision-{index}",
            provenance_digest=digest(f"overflow-document-{index}"),
        )
        for index in range(9)
    )
    current_view = authority_view(document_bindings=custom_bindings)
    rows = [
        {
            "generation_id": str(GENERATION_ID),
            "passage_id": binding.passage_id,
            "document_digest": binding.provenance_digest,
            "language": binding.language,
            "score": float(20 - index),
        }
        for index, binding in enumerate(custom_bindings)
    ]
    _driver, _factory, retriever = system(
        tmp_path,
        view=current_view,
        scenario=default_scenario(rows=rows),
    )
    receipt = retriever.retrieve(
        request(idempotency_key="overflow")
    ).receipt

    assert receipt.outcome is BranchOutcome.INCOMPLETE
    assert receipt.reason_code == "RESULT_BOUND_EXCEEDED"
    assert not receipt.hits


@pytest.mark.parametrize(
    ("case_id", "rows"),
    [
        (
            "unknown-passage",
            [
                {
                    "generation_id": str(GENERATION_ID),
                    "passage_id": "p-unknown",
                    "document_digest": digest("unknown"),
                    "language": "en-GB",
                    "score": 1.0,
                }
            ],
        ),
        (
            "document-digest",
            [result_row("p-en", 1.0, document_digest=digest("tampered"))],
        ),
        (
            "malformed-document-digest",
            [result_row("p-en", 1.0, document_digest="not-a-digest")],
        ),
        ("language", [result_row("p-en", 1.0, language="zh-HK")]),
        (
            "duplicate-passage",
            [result_row("p-en", 1.0), result_row("p-en", 0.9)],
        ),
        (
            "ordering",
            [result_row("p-zh", 1.0), result_row("p-en", 2.0)],
        ),
    ],
)
def test_projection_result_integrity_failures_are_unavailable(
    tmp_path: Path,
    case_id: str,
    rows: list[dict[str, object]],
) -> None:
    _driver, _factory, retriever = system(
        tmp_path,
        scenario=default_scenario(rows=rows),
    )
    receipt = retriever.retrieve(
        request(idempotency_key=f"integrity-{case_id}")
    ).receipt

    assert receipt.outcome is BranchOutcome.UNAVAILABLE
    assert receipt.reason_code == "PROJECTION_INTEGRITY_ERROR"
    assert not receipt.hits


def test_caller_lucene_syntax_is_only_a_bound_escaped_value(
    tmp_path: Path,
) -> None:
    driver, _factory, retriever = system(
        tmp_path,
        scenario=default_scenario(rows=[]),
    )
    surface = 'foo") OR *:* OR (bar'
    receipt = retriever.retrieve(
        request(
            idempotency_key="lucene-injection",
            query_text=surface,
        )
    ).receipt

    assert receipt.outcome is BranchOutcome.COMPLETE
    statement, parameters = driver.calls[-1]
    assert surface not in statement
    assert parameters["query"] != surface
    assert "\\*" in parameters["query"]
    assert "\\:" in parameters["query"]
    assert "\\)" in parameters["query"]
    assert parameters["index_name"] == snapshot().index_name
    assert set(parameters) == {
        "index_name",
        "query",
        "generation_id",
        "limit",
    }


def test_one_nanosecond_overrun_is_an_explicit_timeout(
    tmp_path: Path,
) -> None:
    # start + remaining-budget handoff + final receipt
    clock = SequenceClock((0, 0, 0, 0, 5_000_000_001))
    _driver, _factory, retriever = system(
        tmp_path,
        clock=clock,
    )
    receipt = retriever.retrieve(
        request(idempotency_key="one-ns-overrun")
    ).receipt

    assert receipt.outcome is BranchOutcome.INCOMPLETE
    assert receipt.reason_code == "QUERY_TIMEOUT"
    assert receipt.elapsed_ms == 5_000
    assert not receipt.hits


def test_graph_reader_receives_each_remaining_nanosecond_budget(
    tmp_path: Path,
) -> None:
    clock = SequenceClock(
        (0, 100_000_000, 200_000_000, 300_000_000, 400_000_000)
    )
    driver, _factory, retriever = system(
        tmp_path,
        clock=clock,
    )
    receipt = retriever.retrieve(
        request(idempotency_key="managed-timeout")
    ).receipt

    assert receipt.outcome is BranchOutcome.COMPLETE
    assert len(driver.read_requests) == 3
    assert [item.timeout_ns for item in driver.read_requests] == [
        4_900_000_000,
        4_800_000_000,
        4_700_000_000,
    ]


def test_journal_rejects_semantic_conflict_and_retains_rows(
    tmp_path: Path,
) -> None:
    _driver, _factory, retriever = system(tmp_path)
    retriever.retrieve(request())

    with pytest.raises(FullTextReceiptIdempotencyConflict):
        retriever.retrieve(request(query_text="different query"))

    journal_path = tmp_path / "fulltext-receipts.sqlite3"
    with sqlite3.connect(journal_path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE increment5_fulltext_receipts SET "
                "receipt_digest='sha256:" + "0" * 64 + "'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="retained"):
            connection.execute(
                "DELETE FROM increment5_fulltext_receipts"
            )


def test_journal_detects_corrupted_receipt_bytes(tmp_path: Path) -> None:
    driver, _factory, retriever = system(tmp_path)
    retriever.retrieve(request())
    journal_path = tmp_path / "fulltext-receipts.sqlite3"
    with sqlite3.connect(journal_path) as connection:
        connection.execute(
            "DROP TRIGGER immutable_increment5_fulltext_receipt_update"
        )
        connection.execute(
            "UPDATE increment5_fulltext_receipts SET receipt_bytes=?",
            (b"{}",),
        )

    restarted = FullTextRetriever(
        graph_reader=driver.reader(),
        journal=FullTextReceiptJournal(journal_path),
        authority_view_provider=lambda _request: authority_view(),
        monotonic_ns=lambda: 0,
    )
    with pytest.raises(
        FullTextReceiptJournalError,
        match="digest differs",
    ):
        restarted.retrieve(request())


@pytest.mark.parametrize("passage_id", ["bad passage", "1bad"])
def test_document_binding_rejects_non_token_passage_id(
    passage_id: str,
) -> None:
    with pytest.raises(ValueError, match="valid authority token"):
        replace(bindings()[0], passage_id=passage_id)


def test_journal_rejects_rebound_request_identity(tmp_path: Path) -> None:
    driver, _factory, retriever = system(tmp_path)
    original = retriever.retrieve(request()).receipt
    value = original.canonical_value()
    value["request_id"] = "00000000-0000-4000-8000-000000005299"
    corrupted = canonical_json_bytes(value)
    journal_path = tmp_path / "fulltext-receipts.sqlite3"
    with sqlite3.connect(journal_path) as connection:
        connection.execute(
            "DROP TRIGGER immutable_increment5_fulltext_receipt_update"
        )
        connection.execute(
            "UPDATE increment5_fulltext_receipts SET "
            "receipt_bytes=?,receipt_digest=?",
            (corrupted, digest_bytes(corrupted)),
        )

    restarted = FullTextRetriever(
        graph_reader=driver.reader(),
        journal=FullTextReceiptJournal(journal_path),
        authority_view_provider=lambda _request: authority_view(),
        monotonic_ns=lambda: 0,
    )
    with pytest.raises(
        FullTextReceiptJournalError,
        match="request binding differs",
    ):
        restarted.retrieve(request())


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("query_id", "increment5.fulltext.other"),
        ("query_digest", digest("another-normalized-query")),
    ],
)
def test_journal_rejects_hits_rebound_to_another_query(
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    driver, _factory, retriever = system(tmp_path)
    original = retriever.retrieve(request()).receipt
    value = original.canonical_value()
    assert value["hits"]
    value["hits"][0][field] = replacement
    corrupted = canonical_json_bytes(value)
    journal_path = tmp_path / "fulltext-receipts.sqlite3"
    with sqlite3.connect(journal_path) as connection:
        connection.execute(
            "DROP TRIGGER immutable_increment5_fulltext_receipt_update"
        )
        connection.execute(
            "UPDATE increment5_fulltext_receipts SET "
            "receipt_bytes=?,receipt_digest=?",
            (corrupted, digest_bytes(corrupted)),
        )

    restarted = FullTextRetriever(
        graph_reader=driver.reader(),
        journal=FullTextReceiptJournal(journal_path),
        authority_view_provider=lambda _request: authority_view(),
        monotonic_ns=lambda: 0,
    )
    with pytest.raises(
        FullTextReceiptJournalError,
        match="unavailable or inconsistent",
    ):
        restarted.retrieve(request())


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("generation_state", "RETIRED"),
        (
            "generation_id",
            "00000000-0000-4000-8000-000000005299",
        ),
        (
            "generation_identity_digest",
            digest("another-generation-identity"),
        ),
        (
            "fulltext_component_digest",
            digest("another-snapshot-fulltext-component"),
        ),
        (
            "normalization_component_digest",
            digest("another-snapshot-normalization-component"),
        ),
        (
            "rights_manifest_digest",
            digest("another-rights-manifest"),
        ),
        ("contiguous_ledger_seq", 41),
        ("open_gap_count", 1),
        ("dead_letter_count", 1),
        (
            "freshness_deadline",
            "2042-03-12T11:45:00.000000Z",
        ),
        ("index_state", "FAILED"),
    ],
)
def test_journal_rejects_snapshot_rebound_from_request(
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    driver, _factory, retriever = system(tmp_path)
    original = retriever.retrieve(request()).receipt
    value = original.canonical_value()
    assert value["snapshot"] is not None
    value["snapshot"][field] = replacement
    corrupted = canonical_json_bytes(value)
    journal_path = tmp_path / "fulltext-receipts.sqlite3"
    with sqlite3.connect(journal_path) as connection:
        connection.execute(
            "DROP TRIGGER immutable_increment5_fulltext_receipt_update"
        )
        connection.execute(
            "UPDATE increment5_fulltext_receipts SET "
            "receipt_bytes=?,receipt_digest=?",
            (corrupted, digest_bytes(corrupted)),
        )

    before_calls = list(driver.calls)
    restarted = FullTextRetriever(
        graph_reader=driver.reader(),
        journal=FullTextReceiptJournal(journal_path),
        authority_view_provider=lambda _request: authority_view(),
        monotonic_ns=lambda: 0,
    )
    with pytest.raises(
        FullTextReceiptJournalError,
        match="request binding differs",
    ):
        restarted.retrieve(request())
    assert driver.calls == before_calls


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("language_mode", "EN_GB"),
        ("lucene_query", 'retrieval_text:"another"'),
        ("implementation_version", "another-normalizer-version"),
        ("component_digest", digest("another-normalizer-component")),
    ],
)
def test_journal_rejects_normalized_query_rebound_from_request(
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    driver, _factory, retriever = system(tmp_path)
    original = retriever.retrieve(request()).receipt
    value = original.canonical_value()
    assert value["normalized_query"] is not None
    value["normalized_query"][field] = replacement
    rebound_digest = digest_bytes(
        canonical_json_bytes(value["normalized_query"])
    )
    for hit in value["hits"]:
        hit["query_digest"] = rebound_digest
    corrupted = canonical_json_bytes(value)
    journal_path = tmp_path / "fulltext-receipts.sqlite3"
    with sqlite3.connect(journal_path) as connection:
        connection.execute(
            "DROP TRIGGER immutable_increment5_fulltext_receipt_update"
        )
        connection.execute(
            "UPDATE increment5_fulltext_receipts SET "
            "receipt_bytes=?,receipt_digest=?",
            (corrupted, digest_bytes(corrupted)),
        )

    before_calls = list(driver.calls)
    restarted = FullTextRetriever(
        graph_reader=driver.reader(),
        journal=FullTextReceiptJournal(journal_path),
        authority_view_provider=lambda _request: authority_view(),
        monotonic_ns=lambda: 0,
    )
    with pytest.raises(
        FullTextReceiptJournalError,
        match="request binding differs",
    ):
        restarted.retrieve(request())
    assert driver.calls == before_calls


@pytest.mark.parametrize(
    "changes",
    [
        {"contract_digest": digest("another-contract")},
        {"policy_id": "another-fulltext-policy"},
        {"fulltext_component_digest": digest("another-fulltext-component")},
        {
            "normalization_component_digest": digest(
                "another-normalization-component"
            )
        },
        {
            "started_at": LATER.to_text(),
            "completed_at": LATER.to_text(),
        },
    ],
)
def test_journal_rejects_receipt_fields_rebound_from_request(
    tmp_path: Path,
    changes: dict[str, object],
) -> None:
    driver, _factory, retriever = system(tmp_path)
    original = retriever.retrieve(request()).receipt
    value = original.canonical_value()
    value.update(changes)
    corrupted = canonical_json_bytes(value)
    journal_path = tmp_path / "fulltext-receipts.sqlite3"
    with sqlite3.connect(journal_path) as connection:
        connection.execute(
            "DROP TRIGGER immutable_increment5_fulltext_receipt_update"
        )
        connection.execute(
            "UPDATE increment5_fulltext_receipts SET "
            "receipt_bytes=?,receipt_digest=?",
            (corrupted, digest_bytes(corrupted)),
        )

    restarted = FullTextRetriever(
        graph_reader=driver.reader(),
        journal=FullTextReceiptJournal(journal_path),
        authority_view_provider=lambda _request: authority_view(),
        monotonic_ns=lambda: 0,
    )
    with pytest.raises(
        FullTextReceiptJournalError,
        match="request binding differs",
    ):
        restarted.retrieve(request())


def test_journal_translates_canonical_malformed_receipt_fields(
    tmp_path: Path,
) -> None:
    driver, _factory, retriever = system(tmp_path)
    original = retriever.retrieve(request()).receipt
    value = original.canonical_value()
    value["fulltext_component_digest"] = "not-a-digest"
    corrupted = canonical_json_bytes(value)
    journal_path = tmp_path / "fulltext-receipts.sqlite3"
    with sqlite3.connect(journal_path) as connection:
        connection.execute(
            "DROP TRIGGER immutable_increment5_fulltext_receipt_update"
        )
        connection.execute(
            "UPDATE increment5_fulltext_receipts SET "
            "receipt_bytes=?,receipt_digest=?",
            (corrupted, digest_bytes(corrupted)),
        )

    restarted = FullTextRetriever(
        graph_reader=driver.reader(),
        journal=FullTextReceiptJournal(journal_path),
        authority_view_provider=lambda _request: authority_view(),
        monotonic_ns=lambda: 0,
    )
    with pytest.raises(
        FullTextReceiptJournalError,
        match="unavailable or inconsistent",
    ):
        restarted.retrieve(request())


def test_request_rejects_oversized_and_unbounded_controls() -> None:
    with pytest.raises(FullTextContractError, match="bounded"):
        request(query_text="x" * 16_385)
    with pytest.raises(FullTextContractError, match="fixed at 8"):
        request(result_limit=9)
    with pytest.raises(FullTextContractError, match="fixed at 5000"):
        request(timeout_ms=5_001)
    with pytest.raises(FullTextContractError, match="response byte limit"):
        request(response_byte_limit=262_145)
    with pytest.raises(FullTextContractError, match="canonical non-negative"):
        request(minimum_watermark=9_007_199_254_740_992)
    with pytest.raises(FullTextContractError, match="canonical non-negative"):
        snapshot(index_document_count=9_007_199_254_740_992)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        (
            {"contract_digest": digest("wrong-contract")},
            "CONTRACT_MISMATCH",
        ),
        (
            {"policy_id": "unreviewed-fulltext-policy"},
            "POLICY_MISMATCH",
        ),
        (
            {"fulltext_component_digest": digest("wrong-fulltext")},
            "COMPONENT_MISMATCH",
        ),
        (
            {"normalization_component_digest": digest("wrong-normalizer")},
            "COMPONENT_MISMATCH",
        ),
        (
            {"query_valid_time": LATER},
            "QUERY_VALID_TIME_IN_FUTURE",
        ),
    ],
)
def test_request_policy_failures_do_not_read_authority_or_neo4j(
    tmp_path: Path,
    changes: dict[str, object],
    reason: str,
) -> None:
    provider_calls = 0

    def provider(_request):
        nonlocal provider_calls
        provider_calls += 1
        return authority_view()

    driver, _factory, retriever = system(
        tmp_path,
        provider=provider,
    )
    receipt = retriever.retrieve(
        request(
            idempotency_key=f"policy-{reason.lower()}",
            **changes,
        )
    ).receipt

    assert receipt.outcome is BranchOutcome.POLICY_BLOCKED
    assert receipt.reason_code == reason
    assert receipt.authority_read_count == 0
    assert receipt.neo4j_read_count == 0
    assert provider_calls == 0
    assert driver.calls == []


def test_authority_provider_failure_is_explicit_unavailable(
    tmp_path: Path,
) -> None:
    driver, _factory, retriever = system(
        tmp_path,
        provider=lambda _request: (_ for _ in ()).throw(
            RuntimeError("authority unavailable")
        ),
    )
    receipt = retriever.retrieve(
        request(idempotency_key="authority-unavailable")
    ).receipt

    assert receipt.outcome is BranchOutcome.UNAVAILABLE
    assert receipt.reason_code == "AUTHORITY_VIEW_UNAVAILABLE"
    assert receipt.authority_read_count == 0
    assert driver.calls == []


@pytest.mark.parametrize("failure_on", ("component", "index", "query"))
def test_neo4j_read_failure_is_explicit_unavailable(
    tmp_path: Path,
    failure_on: str,
) -> None:
    scenario = default_scenario()
    scenario.failure_on = failure_on
    _driver, _factory, retriever = system(
        tmp_path,
        scenario=scenario,
    )
    receipt = retriever.retrieve(
        request(idempotency_key=f"read-failure-{failure_on}")
    ).receipt

    assert receipt.outcome in {
        BranchOutcome.UNAVAILABLE,
        BranchOutcome.INCOMPLETE,
    }
    assert receipt.reason_code in {
        "NEO4J_READ_UNAVAILABLE",
        "QUERY_TIMEOUT",
    }
    assert not receipt.hits
