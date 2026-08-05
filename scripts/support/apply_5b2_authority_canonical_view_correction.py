from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(relative_path: str, old: str, new: str) -> None:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"5B2 authority-view anchor differs for {relative_path}: count={count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "newsroom/increment5/fulltext_retriever.py",
        """        authority_read_count = 0
        try:
            view = self._authority_view_provider(request)
            if not isinstance(view, FullTextAuthorityView):
                raise FullTextContractError(
                    "authority provider returned an untyped full-text view"
                )
            authority_read_count = 1
        except Exception:
            return self._receipt(
                request,
                start_ns=start_ns,
                outcome=BranchOutcome.UNAVAILABLE,
                reason_code="AUTHORITY_VIEW_UNAVAILABLE",
                authority_read_count=authority_read_count,
            )

        snapshot = view.snapshot
        view_digest = view.view_digest
""",
        """        authority_read_count = 0
        try:
            view = self._authority_view_provider(request)
            if not isinstance(view, FullTextAuthorityView):
                raise FullTextContractError(
                    "authority provider returned an untyped full-text view"
                )
            snapshot = view.snapshot
            view_digest = view.view_digest
            authority_read_count = 1
        except Exception:
            return self._receipt(
                request,
                start_ns=start_ns,
                outcome=BranchOutcome.UNAVAILABLE,
                reason_code="AUTHORITY_VIEW_UNAVAILABLE",
                authority_read_count=authority_read_count,
            )

""",
    )

    replace_once(
        "newsroom/tests/test_increment5b2_fulltext_retriever.py",
        """    replay = retriever.retrieve(current_request)
    assert replay.replayed is True
    assert replay.receipt.canonical_bytes == receipt.canonical_bytes
    assert driver.calls == []


def test_result_overflow_is_incomplete_instead_of_truncated(
""",
        """    replay = retriever.retrieve(current_request)
    assert replay.replayed is True
    assert replay.receipt.canonical_bytes == receipt.canonical_bytes
    assert driver.calls == []


def test_noncanonical_authority_view_returns_journaled_unavailable_receipt(
    tmp_path: Path,
) -> None:
    noncanonical_view = authority_view(
        projection_snapshot=replace(
            snapshot(),
            contiguous_ledger_seq=9_007_199_254_740_992,
        )
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
""",
    )


if __name__ == "__main__":
    main()
