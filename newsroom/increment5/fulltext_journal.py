"""Non-authoritative immutable SQLite journal for 5B2 full-text receipts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import sqlite3

from newsroom.authority.canonical import digest_bytes

from .fulltext_contracts import FullTextBranchRequest, FullTextContractError
from .fulltext_receipts import FullTextBranchReceipt


class FullTextReceiptJournalError(RuntimeError):
    """The full-text receipt journal is unavailable or inconsistent."""


class FullTextReceiptIdempotencyConflict(FullTextReceiptJournalError):
    """An idempotency key was reused for materially different request bytes."""


@dataclass(frozen=True, slots=True)
class FullTextJournalResult:
    receipt: FullTextBranchReceipt
    replayed: bool


_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS increment5_fulltext_receipts(
        idempotency_key TEXT PRIMARY KEY,
        request_digest TEXT NOT NULL UNIQUE,
        request_bytes BLOB NOT NULL,
        receipt_digest TEXT NOT NULL UNIQUE,
        receipt_bytes BLOB NOT NULL,
        recorded_at TEXT NOT NULL,
        CHECK(length(request_bytes)>0),
        CHECK(length(receipt_bytes)>0)
    ) STRICT""",
    """CREATE TRIGGER IF NOT EXISTS immutable_increment5_fulltext_receipt_update
       BEFORE UPDATE ON increment5_fulltext_receipts BEGIN
       SELECT RAISE(ABORT,'immutable Increment 5 full-text receipt'); END""",
    """CREATE TRIGGER IF NOT EXISTS immutable_increment5_fulltext_receipt_delete
       BEFORE DELETE ON increment5_fulltext_receipts BEGIN
       SELECT RAISE(ABORT,'Increment 5 full-text receipts are retained'); END""",
)


class FullTextReceiptJournal:
    """Return the first canonical full-text receipt byte-for-byte on replay."""

    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path):
            raise TypeError("full-text journal path must be a pathlib.Path")
        self._path = path.resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._connect() as connection:
                for statement in _SCHEMA:
                    connection.execute(statement)
        except sqlite3.Error as exc:
            raise FullTextReceiptJournalError(
                "cannot initialise Increment 5 full-text receipt journal"
            ) from exc

    def execute(
        self,
        request: FullTextBranchRequest,
        producer: Callable[[], FullTextBranchReceipt],
    ) -> FullTextJournalResult:
        if not isinstance(request, FullTextBranchRequest):
            raise TypeError("full-text journal request must be typed")
        if not callable(producer):
            raise TypeError("full-text receipt producer must be callable")

        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT request_digest,request_bytes,receipt_digest,receipt_bytes "
                "FROM increment5_fulltext_receipts WHERE idempotency_key=?",
                (request.idempotency_key,),
            ).fetchone()
            if row is None:
                duplicate = connection.execute(
                    "SELECT request_digest,request_bytes,receipt_digest,receipt_bytes "
                    "FROM increment5_fulltext_receipts WHERE request_digest=?",
                    (request.request_digest,),
                ).fetchone()
                if duplicate is not None:
                    receipt = self._verified_receipt(
                        duplicate,
                        expected_request_digest=request.request_digest,
                        expected_request_bytes=request.canonical_bytes,
                    )
                    connection.commit()
                    return FullTextJournalResult(
                        receipt=receipt,
                        replayed=True,
                    )

                receipt = producer()
                if not isinstance(receipt, FullTextBranchReceipt):
                    raise FullTextReceiptJournalError(
                        "full-text producer returned an untyped receipt"
                    )
                if (
                    receipt.request_id != request.request_id
                    or receipt.request_digest != request.request_digest
                ):
                    raise FullTextReceiptJournalError(
                        "produced full-text receipt differs from the stable request"
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

            receipt = self._verified_receipt(
                row,
                expected_request_digest=request.request_digest,
                expected_request_bytes=request.canonical_bytes,
            )
            connection.commit()
            return FullTextJournalResult(receipt=receipt, replayed=True)
        except FullTextReceiptIdempotencyConflict:
            raise
        except FullTextReceiptJournalError:
            raise
        except (sqlite3.Error, FullTextContractError) as exc:
            raise FullTextReceiptJournalError(
                "Increment 5 full-text receipt journal is unavailable or inconsistent"
            ) from exc
        finally:
            try:
                connection.close()
            except (UnboundLocalError, sqlite3.Error):
                pass

    @staticmethod
    def _verified_receipt(
        row: sqlite3.Row,
        *,
        expected_request_digest: str,
        expected_request_bytes: bytes,
    ) -> FullTextBranchReceipt:
        stored_request_digest = str(row["request_digest"])
        stored_request_bytes = bytes(row["request_bytes"])
        if (
            stored_request_digest != expected_request_digest
            or stored_request_bytes != expected_request_bytes
        ):
            raise FullTextReceiptIdempotencyConflict(
                "Increment 5 full-text idempotency key was reused with another request"
            )
        receipt_bytes = bytes(row["receipt_bytes"])
        if digest_bytes(receipt_bytes) != str(row["receipt_digest"]):
            raise FullTextReceiptJournalError(
                "stored full-text receipt digest differs"
            )
        receipt = FullTextBranchReceipt.from_canonical_bytes(receipt_bytes)
        if receipt.request_digest != expected_request_digest:
            raise FullTextReceiptJournalError(
                "stored full-text receipt request binding differs"
            )
        return receipt

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._path,
            isolation_level=None,
            timeout=5.0,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection


__all__ = [
    "FullTextJournalResult",
    "FullTextReceiptIdempotencyConflict",
    "FullTextReceiptJournal",
    "FullTextReceiptJournalError",
]
