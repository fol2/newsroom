"""Non-authoritative immutable SQLite journal for Increment 5 branch receipts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import TypeVar

from newsroom.authority.canonical import digest_bytes

from .branch_contracts import (
    CandidateCollisionRequest,
    ExactBranchRequest,
    Increment5BranchContractError,
)

from .branch_receipts import CandidateCollisionReceipt, ExactBranchReceipt


class BranchReceiptJournalError(RuntimeError):
    """The non-authoritative receipt journal is unavailable or inconsistent."""


class BranchReceiptIdempotencyConflict(BranchReceiptJournalError):
    """An idempotency key was reused for a materially different request."""


ReceiptT = TypeVar("ReceiptT", ExactBranchReceipt, CandidateCollisionReceipt)


@dataclass(frozen=True, slots=True)
class JournalResult:
    receipt: ExactBranchReceipt | CandidateCollisionReceipt
    replayed: bool


_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS increment5_branch_receipts(
        request_type TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        request_digest TEXT NOT NULL UNIQUE,
        request_bytes BLOB NOT NULL,
        receipt_type TEXT NOT NULL,
        receipt_digest TEXT NOT NULL UNIQUE,
        receipt_bytes BLOB NOT NULL,
        recorded_at TEXT NOT NULL,
        PRIMARY KEY(request_type,idempotency_key),
        CHECK(request_type IN('EXACT','CANDIDATE_COLLISION')),
        CHECK(receipt_type IN('EXACT','CANDIDATE_COLLISION')),
        CHECK(length(request_bytes)>0),
        CHECK(length(receipt_bytes)>0)
    ) STRICT""",
    """CREATE TRIGGER IF NOT EXISTS immutable_increment5_branch_receipt_update
        BEFORE UPDATE ON increment5_branch_receipts BEGIN
        SELECT RAISE(ABORT,'immutable Increment 5 branch receipt'); END""",
    """CREATE TRIGGER IF NOT EXISTS immutable_increment5_branch_receipt_delete
        BEFORE DELETE ON increment5_branch_receipts BEGIN
        SELECT RAISE(ABORT,'Increment 5 branch receipts are retained'); END""",
)


class BranchReceiptJournal:
    """Persist one byte-identical receipt for each stable branch request."""

    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path):
            raise TypeError("receipt journal path must be a pathlib.Path")
        self._path = path.resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._connect() as connection:
                for statement in _SCHEMA:
                    connection.execute(statement)
        except sqlite3.Error as exc:
            raise BranchReceiptJournalError("cannot initialise Increment 5 receipt journal") from exc

    def execute_exact(
        self,
        request: ExactBranchRequest,
        producer: Callable[[], ExactBranchReceipt],
    ) -> JournalResult:
        return self._execute(
            request_type="EXACT",
            idempotency_key=request.idempotency_key,
            request_digest=request.request_digest,
            request_bytes=request.canonical_bytes,
            producer=producer,
            parser=ExactBranchReceipt.from_canonical_bytes,
        )

    def execute_collision(
        self,
        request: CandidateCollisionRequest,
        producer: Callable[[], CandidateCollisionReceipt],
    ) -> JournalResult:
        return self._execute(
            request_type="CANDIDATE_COLLISION",
            idempotency_key=request.idempotency_key,
            request_digest=request.request_digest,
            request_bytes=request.canonical_bytes,
            producer=producer,
            parser=CandidateCollisionReceipt.from_canonical_bytes,
        )

    def _execute(
        self,
        *,
        request_type: str,
        idempotency_key: str,
        request_digest: str,
        request_bytes: bytes,
        producer: Callable[[], ReceiptT],
        parser: Callable[[bytes], ReceiptT],
    ) -> JournalResult:
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT request_digest,request_bytes,receipt_type,receipt_digest,"
                "receipt_bytes FROM increment5_branch_receipts "
                "WHERE request_type=? AND idempotency_key=?",
                (request_type, idempotency_key),
            ).fetchone()
            if row is None:
                duplicate = connection.execute(
                    "SELECT request_digest,request_bytes,receipt_type,receipt_digest,"
                    "receipt_bytes FROM increment5_branch_receipts "
                    "WHERE request_digest=?",
                    (request_digest,),
                ).fetchone()
                if duplicate is not None:
                    receipt = self._verified_receipt(
                        duplicate,
                        expected_request_digest=request_digest,
                        expected_request_bytes=request_bytes,
                        expected_receipt_type=request_type,
                        parser=parser,
                    )
                    connection.commit()
                    return JournalResult(receipt=receipt, replayed=True)

                receipt = producer()
                if receipt.request_digest != request_digest:
                    raise BranchReceiptJournalError(
                        "produced branch receipt differs from the stable request"
                    )
                receipt_bytes = receipt.canonical_bytes
                receipt_digest = receipt.receipt_digest
                connection.execute(
                    "INSERT INTO increment5_branch_receipts("
                    "request_type,idempotency_key,request_digest,request_bytes,"
                    "receipt_type,receipt_digest,receipt_bytes,recorded_at"
                    ") VALUES(?,?,?,?,?,?,?,?)",
                    (
                        request_type,
                        idempotency_key,
                        request_digest,
                        request_bytes,
                        request_type,
                        receipt_digest,
                        receipt_bytes,
                        receipt.completed_at.to_text(),
                    ),
                )
                connection.commit()
                return JournalResult(receipt=receipt, replayed=False)

            receipt = self._verified_receipt(
                row,
                expected_request_digest=request_digest,
                expected_request_bytes=request_bytes,
                expected_receipt_type=request_type,
                parser=parser,
            )
            connection.commit()
            return JournalResult(receipt=receipt, replayed=True)
        except BranchReceiptIdempotencyConflict:
            raise
        except BranchReceiptJournalError:
            raise
        except (sqlite3.Error, Increment5BranchContractError) as exc:
            raise BranchReceiptJournalError(
                "Increment 5 receipt journal is unavailable or inconsistent"
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
        expected_receipt_type: str,
        parser: Callable[[bytes], ReceiptT],
    ) -> ReceiptT:
        stored_request_digest = str(row["request_digest"])
        stored_request_bytes = bytes(row["request_bytes"])
        if (
            stored_request_digest != expected_request_digest
            or stored_request_bytes != expected_request_bytes
        ):
            raise BranchReceiptIdempotencyConflict(
                "Increment 5 branch idempotency key was reused with another request"
            )
        if str(row["receipt_type"]) != expected_receipt_type:
            raise BranchReceiptJournalError("stored branch receipt type differs")
        receipt_bytes = bytes(row["receipt_bytes"])
        if digest_bytes(receipt_bytes) != str(row["receipt_digest"]):
            raise BranchReceiptJournalError("stored branch receipt digest differs")
        receipt = parser(receipt_bytes)
        if receipt.request_digest != expected_request_digest:
            raise BranchReceiptJournalError("stored branch receipt request binding differs")
        return receipt

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, isolation_level=None, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection


__all__ = [
    "BranchReceiptIdempotencyConflict",
    "BranchReceiptJournal",
    "BranchReceiptJournalError",
    "JournalResult",
]
