from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(relative_path: str, old: str, new: str) -> None:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"5B2 timeout receipt anchor differs for {relative_path}: count={count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "newsroom/increment5/fulltext_receipts.py",
        """        if self.snapshot is not None and not isinstance(
            self.snapshot, FullTextProjectionSnapshot
        ):
""",
        """        if self.reason_code == \"QUERY_TIMEOUT\" and (
            self.outcome is not BranchOutcome.INCOMPLETE
            or self.elapsed_ms != BRANCH_TIMEOUT_MS
        ):
            raise FullTextContractError(
                \"full-text timeout receipt differs from its hard deadline\"
            )
        if self.snapshot is not None and not isinstance(
            self.snapshot, FullTextProjectionSnapshot
        ):
""",
    )

    replace_once(
        "newsroom/tests/test_increment5b2_fulltext_retriever.py",
        """    assert not receipt.exclusions
    assert driver.calls == []

    replay = retriever.retrieve(current_request)
""",
        """    assert not receipt.exclusions
    assert driver.calls == []
    with pytest.raises(FullTextContractError, match=\"timeout receipt\"):
        replace(receipt, elapsed_ms=4_999)
    with pytest.raises(FullTextContractError, match=\"timeout receipt\"):
        replace(receipt, outcome=BranchOutcome.STALE)

    replay = retriever.retrieve(current_request)
""",
    )


if __name__ == "__main__":
    main()
