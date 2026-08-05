from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(relative_path: str, old: str, new: str) -> None:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"5B2 retained-query anchor differs for {relative_path}: count={count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "newsroom/increment5/fulltext_contracts.py",
        'FULLTEXT_PURPOSE = "bounded_fulltext_lookup"\n',
        'FULLTEXT_PURPOSE = "bounded_fulltext_lookup"\n'
        'FULLTEXT_QUERY_ID = "increment5.fulltext.v1"\n',
    )
    replace_once(
        "newsroom/increment5/fulltext_contracts.py",
        '    "FULLTEXT_PURPOSE",\n',
        '    "FULLTEXT_PURPOSE",\n    "FULLTEXT_QUERY_ID",\n',
    )

    replace_once(
        "newsroom/increment5/fulltext_retriever.py",
        """    FULLTEXT_PROVIDER,
    INCREMENT5_RETRIEVAL_CONTRACT_DIGEST,
""",
        """    FULLTEXT_PROVIDER,
    FULLTEXT_QUERY_ID,
    INCREMENT5_RETRIEVAL_CONTRACT_DIGEST,
""",
    )
    replace_once(
        "newsroom/increment5/fulltext_retriever.py",
        '\n\n_QUERY_ID = "increment5.fulltext.v1"\n\n\nclass FullTextRetrieverError',
        '\n\nclass FullTextRetrieverError',
    )
    replace_once(
        "newsroom/increment5/fulltext_retriever.py",
        "query_id=_QUERY_ID,",
        "query_id=FULLTEXT_QUERY_ID,",
    )

    replace_once(
        "newsroom/increment5/fulltext_receipts.py",
        """from .fulltext_contracts import (
    FULLTEXT_RESPONSE_BYTE_LIMIT,
""",
        """from .fulltext_contracts import (
    FULLTEXT_QUERY_ID,
    FULLTEXT_RESPONSE_BYTE_LIMIT,
""",
    )
    replace_once(
        "newsroom/increment5/fulltext_receipts.py",
        """        if len({hit.result_key for hit in self.hits}) != len(self.hits):
            raise FullTextContractError(
                "full-text receipt result keys must be unique"
            )
""",
        """        if len({hit.result_key for hit in self.hits}) != len(self.hits):
            raise FullTextContractError(
                "full-text receipt result keys must be unique"
            )
        if self.hits and self.normalized_query is None:
            raise FullTextContractError(
                "full-text hits require normalized query evidence"
            )
        if self.normalized_query is not None and any(
            hit.query_id != FULLTEXT_QUERY_ID
            or hit.query_digest != self.normalized_query.query_digest
            for hit in self.hits
        ):
            raise FullTextContractError(
                "full-text hit query identity differs from normalized query"
            )
""",
    )

    replace_once(
        "newsroom/tests/test_increment5b2_fulltext_retriever.py",
        """    FULLTEXT_INDEXED_FIELDS,
    NORMALIZATION_COMPONENT_DIGEST,
""",
        """    FULLTEXT_INDEXED_FIELDS,
    FULLTEXT_QUERY_ID,
    NORMALIZATION_COMPONENT_DIGEST,
""",
    )
    replace_once(
        "newsroom/tests/test_increment5b2_fulltext_retriever.py",
        """    assert receipt.normalized_query is not None
    assert receipt.authority_view_digest is not None
""",
        """    assert receipt.normalized_query is not None
    assert all(
        item.query_id == FULLTEXT_QUERY_ID
        and item.query_digest == receipt.normalized_query.query_digest
        for item in receipt.hits
    )
    assert receipt.authority_view_digest is not None
""",
    )
    replace_once(
        "newsroom/tests/test_increment5b2_fulltext_retriever.py",
        """def test_journal_translates_canonical_malformed_receipt_fields(
    tmp_path: Path,
) -> None:
""",
        """@pytest.mark.parametrize(
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


def test_journal_translates_canonical_malformed_receipt_fields(
    tmp_path: Path,
) -> None:
""",
    )


if __name__ == "__main__":
    main()
