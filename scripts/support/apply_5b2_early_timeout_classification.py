from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(relative_path: str, old: str, new: str) -> None:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"5B2 early-timeout anchor differs for {relative_path}: count={count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "newsroom/increment5/fulltext_retriever.py",
        """        except Neo4jFullTextReadTimeout:
            return self._receipt(
                request,
                start_ns=start_ns,
                outcome=BranchOutcome.INCOMPLETE,
                reason_code=\"QUERY_TIMEOUT\",
                authority_read_count=1,
                neo4j_read_count=neo4j_reads,
                snapshot=snapshot,
                authority_view_digest=view_digest,
                normalized_query=normalized,
            )
""",
        """        except Neo4jFullTextReadTimeout:
            # A port timeout can arrive before the repository-owned cumulative
            # deadline.  The receipt builder independently promotes elapsed
            # work at or beyond the hard bound to QUERY_TIMEOUT; an earlier
            # transport or server timeout is unavailable rather than a false
            # claim that 5,000 ms elapsed.
            return self._receipt(
                request,
                start_ns=start_ns,
                outcome=BranchOutcome.UNAVAILABLE,
                reason_code=\"NEO4J_READ_UNAVAILABLE\",
                authority_read_count=1,
                neo4j_read_count=neo4j_reads,
                snapshot=snapshot,
                authority_view_digest=view_digest,
                normalized_query=normalized,
            )
""",
    )
    replace_once(
        "newsroom/increment5/fulltext_retriever.py",
        """        timed_out = elapsed_ns > BRANCH_TIMEOUT_MS * 1_000_000
""",
        """        timed_out = elapsed_ns >= BRANCH_TIMEOUT_MS * 1_000_000
""",
    )
    replace_once(
        "newsroom/tests/test_increment5b2_fulltext_retriever.py",
        """def test_one_nanosecond_overrun_is_an_explicit_timeout(
""",
        """def test_early_graph_timeout_is_journaled_as_unavailable(
    tmp_path: Path,
) -> None:
    scenario = default_scenario()
    scenario.failure_on = \"query\"
    driver, _factory, retriever = system(
        tmp_path,
        scenario=scenario,
        clock=SequenceClock((0, 0, 0, 0, 0)),
    )
    current_request = request(idempotency_key=\"early-neo4j-timeout\")

    first = retriever.retrieve(current_request)
    receipt = first.receipt

    assert first.replayed is False
    assert receipt.outcome is BranchOutcome.UNAVAILABLE
    assert receipt.reason_code == \"NEO4J_READ_UNAVAILABLE\"
    assert receipt.elapsed_ms == 0
    assert receipt.authority_read_count == 1
    assert receipt.neo4j_read_count == 2
    assert receipt.normalized_query is not None
    assert not receipt.hits
    assert not receipt.exclusions

    before_calls = list(driver.calls)
    replay = retriever.retrieve(current_request)
    assert replay.replayed is True
    assert replay.receipt.canonical_bytes == receipt.canonical_bytes
    assert driver.calls == before_calls


def test_exact_deadline_before_graph_read_is_query_timeout(
    tmp_path: Path,
) -> None:
    driver, _factory, retriever = system(
        tmp_path,
        clock=SequenceClock((0, 5_000_000_000, 5_000_000_000)),
    )
    receipt = retriever.retrieve(
        request(idempotency_key=\"exact-deadline-before-read\")
    ).receipt

    assert receipt.outcome is BranchOutcome.INCOMPLETE
    assert receipt.reason_code == \"QUERY_TIMEOUT\"
    assert receipt.elapsed_ms == 5_000
    assert receipt.authority_read_count == 1
    assert receipt.neo4j_read_count == 0
    assert not receipt.hits
    assert not receipt.exclusions
    assert driver.calls == []
    assert driver.read_requests == []


def test_one_nanosecond_overrun_is_an_explicit_timeout(
""",
    )


if __name__ == "__main__":
    main()
