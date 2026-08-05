from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(relative_path: str, old: str, new: str) -> None:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"5B2 request-receipt anchor differs for {relative_path}: count={count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "newsroom/increment5/fulltext_journal.py",
        "from newsroom.increment5.branch_contracts import BranchRequestId\n\n",
        "",
    )
    replace_once(
        "newsroom/increment5/fulltext_journal.py",
        """                    receipt = self._verified_receipt(
                        duplicate,
                        expected_request_id=request.request_id,
                        expected_request_digest=request.request_digest,
                        expected_request_bytes=request.canonical_bytes,
                    )
""",
        """                    receipt = self._verified_receipt(
                        duplicate,
                        request=request,
                    )
""",
    )
    replace_once(
        "newsroom/increment5/fulltext_journal.py",
        """                if (
                    receipt.request_id != request.request_id
                    or receipt.request_digest != request.request_digest
                ):
                    raise FullTextReceiptJournalError(
                        "produced full-text receipt differs from the stable request"
                    )
""",
        """                try:
                    self._require_request_binding(receipt, request)
                except FullTextReceiptJournalError as exc:
                    raise FullTextReceiptJournalError(
                        "produced full-text receipt differs from the stable request"
                    ) from exc
""",
    )
    replace_once(
        "newsroom/increment5/fulltext_journal.py",
        """            receipt = self._verified_receipt(
                row,
                expected_request_id=request.request_id,
                expected_request_digest=request.request_digest,
                expected_request_bytes=request.canonical_bytes,
            )
""",
        """            receipt = self._verified_receipt(
                row,
                request=request,
            )
""",
    )
    replace_once(
        "newsroom/increment5/fulltext_journal.py",
        """    def _verified_receipt(
        row: sqlite3.Row,
        *,
        expected_request_id: BranchRequestId,
        expected_request_digest: str,
        expected_request_bytes: bytes,
    ) -> FullTextBranchReceipt:
        stored_request_digest = str(row["request_digest"])
        stored_request_bytes = bytes(row["request_bytes"])
        if (
            stored_request_digest != expected_request_digest
            or stored_request_bytes != expected_request_bytes
        ):
""",
        """    def _verified_receipt(
        row: sqlite3.Row,
        *,
        request: FullTextBranchRequest,
    ) -> FullTextBranchReceipt:
        stored_request_digest = str(row["request_digest"])
        stored_request_bytes = bytes(row["request_bytes"])
        if (
            stored_request_digest != request.request_digest
            or stored_request_bytes != request.canonical_bytes
        ):
""",
    )
    replace_once(
        "newsroom/increment5/fulltext_journal.py",
        """        receipt = FullTextBranchReceipt.from_canonical_bytes(receipt_bytes)
        if (
            receipt.request_id != expected_request_id
            or receipt.request_digest != expected_request_digest
        ):
            raise FullTextReceiptJournalError(
                "stored full-text receipt request binding differs"
            )
        return receipt

    def _connect(self) -> sqlite3.Connection:
""",
        """        receipt = FullTextBranchReceipt.from_canonical_bytes(receipt_bytes)
        FullTextReceiptJournal._require_request_binding(receipt, request)
        return receipt

    @staticmethod
    def _require_request_binding(
        receipt: FullTextBranchReceipt,
        request: FullTextBranchRequest,
    ) -> None:
        if (
            receipt.request_id != request.request_id
            or receipt.request_digest != request.request_digest
            or receipt.contract_digest != request.contract_digest
            or receipt.policy_id != request.policy_id
            or receipt.fulltext_component_digest
            != request.fulltext_component_digest
            or receipt.normalization_component_digest
            != request.normalization_component_digest
            or receipt.started_at != request.serving_time
            or receipt.completed_at != request.serving_time
        ):
            raise FullTextReceiptJournalError(
                "stored full-text receipt request binding differs"
            )

    def _connect(self) -> sqlite3.Connection:
""",
    )

    replace_once(
        "newsroom/tests/test_increment5b2_fulltext_retriever.py",
        """def test_journal_translates_canonical_malformed_receipt_fields(
    tmp_path: Path,
) -> None:
""",
        """@pytest.mark.parametrize(
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
""",
    )


if __name__ == "__main__":
    main()
