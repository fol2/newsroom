from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(relative_path: str, old: str, new: str) -> None:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"5B2 P2 correction anchor differs for {relative_path}: count={count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "newsroom/increment5/fulltext_retriever.py",
        """        authority_read_count = 0
        try:
            view = self._authority_view_provider(request)
            authority_read_count = 1
            if not isinstance(view, FullTextAuthorityView):
                raise FullTextContractError(
                    \"authority provider returned an untyped full-text view\"
                )
        except Exception:
""",
        """        authority_read_count = 0
        try:
            view = self._authority_view_provider(request)
            if not isinstance(view, FullTextAuthorityView):
                raise FullTextContractError(
                    \"authority provider returned an untyped full-text view\"
                )
            authority_read_count = 1
        except Exception:
""",
    )

    replace_once(
        "newsroom/increment5/fulltext_contracts.py",
        """        for field_name in (
            \"passage_id\",
            \"dependency_root_id\",
            \"source_identity\",
        ):
            _bounded_text(
                getattr(self, field_name),
                field=field_name,
                maximum_bytes=256,
            )
""",
        """        require_token(self.passage_id, field=\"fulltext_passage_id\")
        for field_name in (
            \"dependency_root_id\",
            \"source_identity\",
        ):
            _bounded_text(
                getattr(self, field_name),
                field=field_name,
                maximum_bytes=256,
            )
""",
    )

    replace_once(
        "newsroom/tests/test_increment5b2_fulltext_retriever.py",
        """    assert calls == 0
    assert driver.calls == []


def test_result_overflow_is_incomplete_instead_of_truncated(
""",
        """    assert calls == 0
    assert driver.calls == []


def test_untyped_authority_view_returns_journaled_unavailable_receipt(
    tmp_path: Path,
) -> None:
    driver = FakeDriver(default_scenario())
    retriever = FullTextRetriever(
        graph_reader=driver.reader(),
        journal=FullTextReceiptJournal(
            tmp_path / \"untyped-authority.sqlite3\"
        ),
        authority_view_provider=lambda _request: object(),
        monotonic_ns=lambda: 0,
    )
    current_request = request(idempotency_key=\"untyped-authority-view\")

    first = retriever.retrieve(current_request)
    receipt = first.receipt

    assert first.replayed is False
    assert receipt.outcome is BranchOutcome.UNAVAILABLE
    assert receipt.reason_code == \"AUTHORITY_VIEW_UNAVAILABLE\"
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

    replace_once(
        "newsroom/tests/test_increment5b2_fulltext_retriever.py",
        """def test_request_rejects_oversized_and_unbounded_controls() -> None:
""",
        """@pytest.mark.parametrize(\"passage_id\", [\"bad passage\", \"1bad\"])
def test_document_binding_rejects_non_token_passage_id(
    passage_id: str,
) -> None:
    with pytest.raises(ValueError, match=\"valid authority token\"):
        replace(bindings()[0], passage_id=passage_id)


def test_request_rejects_oversized_and_unbounded_controls() -> None:
""",
    )


if __name__ == "__main__":
    main()
