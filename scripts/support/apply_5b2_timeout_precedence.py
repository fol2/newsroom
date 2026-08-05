from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(relative_path: str, old: str, new: str) -> None:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"5B2 timeout-precedence anchor differs for {relative_path}: "
            f"count={count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "newsroom/increment5/fulltext_journal.py",
        """            if snapshot_failure is not None:
                expected_outcome, expected_reason = snapshot_failure
                if (
                    receipt.outcome is not expected_outcome
                    or receipt.reason_code != expected_reason
                    or receipt.normalized_query is not None
                    or receipt.neo4j_read_count != 0
                    or receipt.hits
                    or receipt.exclusions
                ):
                    raise FullTextReceiptJournalError(
                        \"stored full-text receipt request binding differs\"
                    )
                return
""",
        """            if snapshot_failure is not None:
                expected_outcome, expected_reason = snapshot_failure
                timeout_override = (
                    receipt.outcome is BranchOutcome.INCOMPLETE
                    and receipt.reason_code == \"QUERY_TIMEOUT\"
                )
                if timeout_override:
                    if (
                        receipt.normalized_query is not None
                        or receipt.neo4j_read_count != 0
                        or receipt.hits
                        or receipt.exclusions
                    ):
                        raise FullTextReceiptJournalError(
                            \"stored full-text receipt request binding differs\"
                        )
                    return
                if (
                    receipt.outcome is not expected_outcome
                    or receipt.reason_code != expected_reason
                    or receipt.normalized_query is not None
                    or receipt.neo4j_read_count != 0
                    or receipt.hits
                    or receipt.exclusions
                ):
                    raise FullTextReceiptJournalError(
                        \"stored full-text receipt request binding differs\"
                    )
                return
""",
    )

    replace_once(
        "newsroom/tests/test_increment5b2_fulltext_retriever.py",
        """def test_projection_age_beyond_hard_hour_is_stale(tmp_path: Path) -> None:
""",
        """def test_timeout_override_of_stale_snapshot_is_journaled_and_replayed(
    tmp_path: Path,
) -> None:
    current = snapshot(
        generation_state=ProjectionGenerationState.RETIRED,
    )
    driver, _factory, retriever = system(
        tmp_path,
        view=authority_view(projection_snapshot=current),
        scenario=default_scenario(projection_snapshot=current),
        clock=SequenceClock((0, 5_000_000_001)),
    )
    current_request = request(
        idempotency_key=\"stale-timeout-override\"
    )

    first = retriever.retrieve(current_request)
    receipt = first.receipt

    assert first.replayed is False
    assert receipt.outcome is BranchOutcome.INCOMPLETE
    assert receipt.reason_code == \"QUERY_TIMEOUT\"
    assert receipt.elapsed_ms == 5_000
    assert receipt.snapshot == current
    assert receipt.authority_read_count == 1
    assert receipt.neo4j_read_count == 0
    assert receipt.normalized_query is None
    assert not receipt.hits
    assert not receipt.exclusions
    assert driver.calls == []

    replay = retriever.retrieve(current_request)
    assert replay.replayed is True
    assert replay.receipt.canonical_bytes == receipt.canonical_bytes
    assert driver.calls == []


def test_projection_age_beyond_hard_hour_is_stale(tmp_path: Path) -> None:
""",
    )


if __name__ == "__main__":
    main()
