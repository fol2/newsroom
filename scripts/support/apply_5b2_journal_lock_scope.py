from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_between(
    relative_path: str,
    *,
    start: str,
    end: str,
    replacement: str,
) -> None:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    start_index = text.find(start)
    end_index = text.find(end, start_index)
    if start_index < 0 or end_index < 0:
        raise SystemExit(f"5B2 journal lock-scope anchors differ for {relative_path}")
    if text.find(start, start_index + 1) >= 0:
        raise SystemExit(f"5B2 journal start anchor is not unique for {relative_path}")
    path.write_text(
        text[:start_index] + replacement + text[end_index:],
        encoding="utf-8",
    )


def replace_once(relative_path: str, old: str, new: str) -> None:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"5B2 journal lock-scope anchor differs for {relative_path}: count={count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_between(
        "newsroom/increment5/fulltext_journal.py",
        start="    def execute(\n",
        end="    @staticmethod\n    def _verified_receipt(\n",
        replacement='''    def execute(
        self,
        request: FullTextBranchRequest,
        producer: Callable[[], FullTextBranchReceipt],
    ) -> FullTextJournalResult:
        if not isinstance(request, FullTextBranchRequest):
            raise TypeError("full-text journal request must be typed")
        if not callable(producer):
            raise TypeError("full-text receipt producer must be callable")

        try:
            existing = self._read_existing(request)
            if existing is not None:
                return FullTextJournalResult(
                    receipt=existing,
                    replayed=True,
                )

            # Authority and Neo4j work must never execute while this journal
            # holds a SQLite write reservation.  Concurrent new requests may
            # therefore run their independently bounded producers in parallel.
            receipt = producer()
            if not isinstance(receipt, FullTextBranchReceipt):
                raise FullTextReceiptJournalError(
                    "full-text producer returned an untyped receipt"
                )
            try:
                self._require_request_binding(receipt, request)
            except FullTextReceiptJournalError as exc:
                raise FullTextReceiptJournalError(
                    "produced full-text receipt differs from the stable request"
                ) from exc
            return self._insert_or_replay(request, receipt)
        except FullTextReceiptIdempotencyConflict:
            raise
        except FullTextReceiptJournalError:
            raise
        except (sqlite3.Error, FullTextContractError) as exc:
            raise FullTextReceiptJournalError(
                "Increment 5 full-text receipt journal is unavailable or inconsistent"
            ) from exc

    def _read_existing(
        self,
        request: FullTextBranchRequest,
    ) -> FullTextBranchReceipt | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT request_digest,request_bytes,receipt_digest,receipt_bytes "
                "FROM increment5_fulltext_receipts WHERE idempotency_key=?",
                (request.idempotency_key,),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    "SELECT request_digest,request_bytes,receipt_digest,receipt_bytes "
                    "FROM increment5_fulltext_receipts WHERE request_digest=?",
                    (request.request_digest,),
                ).fetchone()
            if row is None:
                return None
            return self._verified_receipt(row, request=request)
        finally:
            connection.close()

    def _insert_or_replay(
        self,
        request: FullTextBranchRequest,
        receipt: FullTextBranchReceipt,
    ) -> FullTextJournalResult:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT request_digest,request_bytes,receipt_digest,receipt_bytes "
                "FROM increment5_fulltext_receipts WHERE idempotency_key=?",
                (request.idempotency_key,),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    "SELECT request_digest,request_bytes,receipt_digest,receipt_bytes "
                    "FROM increment5_fulltext_receipts WHERE request_digest=?",
                    (request.request_digest,),
                ).fetchone()
            if row is not None:
                retained = self._verified_receipt(row, request=request)
                connection.commit()
                return FullTextJournalResult(
                    receipt=retained,
                    replayed=True,
                )

            receipt_bytes = receipt.canonical_bytes
            connection.execute(
                "INSERT INTO increment5_fulltext_receipts("
                "idempotency_key,request_digest,request_bytes,"
                "receipt_digest,receipt_bytes,recorded_at"
                ") VALUES(?,?,?,?,?,?)",
                (
                    request.idempotency_key,
                    request.request_digest,
                    request.canonical_bytes,
                    receipt.receipt_digest,
                    receipt_bytes,
                    receipt.completed_at.to_text(),
                ),
            )
            connection.commit()
            return FullTextJournalResult(
                receipt=receipt,
                replayed=False,
            )
        finally:
            connection.close()

''',
    )

    replace_once(
        "newsroom/tests/test_increment5b2_fulltext_retriever.py",
        """from newsroom.increment5.branch_contracts import (\n    BranchExclusionReason,\n    BranchOutcome,\n)\n""",
        """from newsroom.increment5.branch_contracts import (\n    BranchExclusionReason,\n    BranchOutcome,\n    BranchRequestId,\n)\n""",
    )

    replace_once(
        "newsroom/tests/test_increment5b2_fulltext_retriever.py",
        """def test_restart_returns_first_receipt_without_authority_or_neo4j_calls(\n    tmp_path: Path,\n) -> None:\n""",
        """def test_journal_does_not_hold_write_lock_while_producing(\n    tmp_path: Path,\n) -> None:\n    journal_path = tmp_path / \"fulltext-receipts.sqlite3\"\n    inner_driver = FakeDriver(default_scenario())\n    inner_retriever = FullTextRetriever(\n        graph_reader=inner_driver.reader(),\n        journal=FullTextReceiptJournal(journal_path),\n        authority_view_provider=lambda _request: authority_view(),\n        monotonic_ns=lambda: 0,\n    )\n    inner_request = request(\n        request_id=BranchRequestId.parse(\n            \"00000000-0000-4000-8000-000000005271\"\n        ),\n        idempotency_key=\"nested-inner-request\",\n    )\n    inner_result = None\n\n    def outer_provider(_request):\n        nonlocal inner_result\n        inner_result = inner_retriever.retrieve(inner_request)\n        return authority_view()\n\n    outer_driver = FakeDriver(default_scenario())\n    outer_retriever = FullTextRetriever(\n        graph_reader=outer_driver.reader(),\n        journal=FullTextReceiptJournal(journal_path),\n        authority_view_provider=outer_provider,\n        monotonic_ns=lambda: 0,\n    )\n    outer_request = request(\n        request_id=BranchRequestId.parse(\n            \"00000000-0000-4000-8000-000000005272\"\n        ),\n        idempotency_key=\"nested-outer-request\",\n    )\n\n    outer_result = outer_retriever.retrieve(outer_request)\n\n    assert outer_result.replayed is False\n    assert outer_result.receipt.outcome is BranchOutcome.COMPLETE\n    assert inner_result is not None\n    assert inner_result.replayed is False\n    assert inner_result.receipt.outcome is BranchOutcome.COMPLETE\n    assert outer_driver.execute_read_count == 3\n    assert inner_driver.execute_read_count == 3\n\n    replay_journal = FullTextReceiptJournal(journal_path)\n    inner_replay = replay_journal.execute(\n        inner_request,\n        lambda: pytest.fail(\"retained inner receipt must replay\"),\n    )\n    outer_replay = replay_journal.execute(\n        outer_request,\n        lambda: pytest.fail(\"retained outer receipt must replay\"),\n    )\n    assert inner_replay.replayed is True\n    assert outer_replay.replayed is True\n    assert (\n        inner_replay.receipt.canonical_bytes\n        == inner_result.receipt.canonical_bytes\n    )\n    assert (\n        outer_replay.receipt.canonical_bytes\n        == outer_result.receipt.canonical_bytes\n    )\n\n\ndef test_restart_returns_first_receipt_without_authority_or_neo4j_calls(\n    tmp_path: Path,\n) -> None:\n""",
    )


if __name__ == "__main__":
    main()
