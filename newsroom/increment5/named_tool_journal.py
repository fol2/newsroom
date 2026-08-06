"""Immutable local replay journal for Increment 5C authorization receipts."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
import sqlite3

from ._named_tool_common import (
    NamedToolContractError,
    NamedToolIdempotencyConflict,
    NamedToolJournalError,
    _digest_bytes,
)
from .named_tool_call import NamedToolCall
from .named_tool_receipts import ToolAuthorizationReceipt

@dataclass(frozen=True, slots=True)
class JournalResult:
    receipt: ToolAuthorizationReceipt
    replayed: bool


_JOURNAL_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS increment5_named_tool_authorizations(
        actor_id TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        call_digest TEXT NOT NULL UNIQUE,
        call_bytes BLOB NOT NULL,
        receipt_digest TEXT NOT NULL UNIQUE,
        receipt_bytes BLOB NOT NULL,
        recorded_at TEXT NOT NULL,
        PRIMARY KEY(actor_id,idempotency_key),
        CHECK(length(call_bytes)>0),
        CHECK(length(receipt_bytes)>0)
    ) STRICT""",
    """CREATE TRIGGER IF NOT EXISTS immutable_named_tool_authorization_update
        BEFORE UPDATE ON increment5_named_tool_authorizations BEGIN
        SELECT RAISE(ABORT,'immutable Increment 5 named-tool authorization'); END""",
    """CREATE TRIGGER IF NOT EXISTS immutable_named_tool_authorization_delete
        BEFORE DELETE ON increment5_named_tool_authorizations BEGIN
        SELECT RAISE(ABORT,'Increment 5 named-tool authorizations are retained'); END""",
)


class NamedToolAuthorizationJournal:
    """Retain first-writer-wins authorization bytes without creating authority."""

    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path):
            raise TypeError("authorization journal path must be pathlib.Path")
        self._path = path.resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with closing(self._connect()) as connection:
                for statement in _JOURNAL_SCHEMA:
                    connection.execute(statement)
        except sqlite3.Error as exc:
            raise NamedToolJournalError(
                "cannot initialise named-tool authorization journal"
            ) from exc

    def execute(
        self,
        call: NamedToolCall,
        producer: Callable[[], ToolAuthorizationReceipt],
    ) -> JournalResult:
        if type(call) is not NamedToolCall:
            raise NamedToolJournalError("journal call must be an exact typed record")
        if not callable(producer):
            raise NamedToolJournalError("journal producer must be callable")
        existing = self._read_existing(call)
        if existing is not None:
            return JournalResult(receipt=existing, replayed=True)

        receipt = producer()
        if type(receipt) is not ToolAuthorizationReceipt:
            raise NamedToolJournalError("journal producer returned another record type")
        if receipt.call_digest != call.call_digest:
            raise NamedToolJournalError(
                "produced authorization receipt differs from the stable call"
            )
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT actor_id,idempotency_key,call_digest,call_bytes,"
                "receipt_digest,receipt_bytes,recorded_at "
                "FROM increment5_named_tool_authorizations "
                "WHERE actor_id=? AND idempotency_key=?",
                (call.actor_id, call.idempotency_key),
            ).fetchone()
            if row is not None:
                winner = self._verified_receipt(row, call=call)
                connection.commit()
                return JournalResult(receipt=winner, replayed=True)
            duplicate = connection.execute(
                "SELECT actor_id,idempotency_key,call_digest,call_bytes,"
                "receipt_digest,receipt_bytes,recorded_at "
                "FROM increment5_named_tool_authorizations WHERE call_digest=?",
                (call.call_digest,),
            ).fetchone()
            if duplicate is not None:
                winner = self._verified_receipt(duplicate, call=call)
                connection.commit()
                return JournalResult(receipt=winner, replayed=True)
            connection.execute(
                "INSERT INTO increment5_named_tool_authorizations("
                "actor_id,idempotency_key,call_digest,call_bytes,receipt_digest,"
                "receipt_bytes,recorded_at) VALUES(?,?,?,?,?,?,?)",
                (
                    call.actor_id,
                    call.idempotency_key,
                    call.call_digest,
                    call.canonical_bytes,
                    receipt.receipt_digest,
                    receipt.canonical_bytes,
                    receipt.completed_at.to_text(),
                ),
            )
            connection.commit()
            return JournalResult(receipt=receipt, replayed=False)
        except (sqlite3.Error, NamedToolContractError) as exc:
            raise NamedToolJournalError(
                "named-tool authorization journal is unavailable or inconsistent"
            ) from exc
        finally:
            try:
                connection.close()
            except (UnboundLocalError, sqlite3.Error):
                pass

    def _read_existing(self, call: NamedToolCall) -> ToolAuthorizationReceipt | None:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT actor_id,idempotency_key,call_digest,call_bytes,"
                    "receipt_digest,receipt_bytes,recorded_at "
                    "FROM increment5_named_tool_authorizations "
                    "WHERE actor_id=? AND idempotency_key=?",
                    (call.actor_id, call.idempotency_key),
                ).fetchone()
                if row is None:
                    return None
                return self._verified_receipt(row, call=call)
        except NamedToolIdempotencyConflict:
            raise
        except NamedToolJournalError:
            raise
        except (sqlite3.Error, NamedToolContractError) as exc:
            raise NamedToolJournalError(
                "named-tool authorization journal is unavailable or inconsistent"
            ) from exc

    @staticmethod
    def _verified_receipt(
        row: sqlite3.Row,
        *,
        call: NamedToolCall,
    ) -> ToolAuthorizationReceipt:
        if str(row["actor_id"]) != call.actor_id or str(
            row["idempotency_key"]
        ) != call.idempotency_key:
            raise NamedToolJournalError("stored authorization row identity differs")
        stored_call_digest = str(row["call_digest"])
        stored_call_bytes = bytes(row["call_bytes"])
        if (
            stored_call_digest != call.call_digest
            or stored_call_bytes != call.canonical_bytes
        ):
            raise NamedToolIdempotencyConflict(
                "named-tool idempotency key was reused with another call"
            )
        receipt_bytes = bytes(row["receipt_bytes"])
        if _digest_bytes(receipt_bytes) != str(row["receipt_digest"]):
            raise NamedToolJournalError("stored authorization receipt digest differs")
        receipt = ToolAuthorizationReceipt.from_canonical_bytes(receipt_bytes)
        if receipt.call_digest != call.call_digest:
            raise NamedToolJournalError("stored authorization receipt binding differs")
        if str(row["recorded_at"]) != receipt.completed_at.to_text():
            raise NamedToolJournalError("stored authorization record time differs")
        return receipt

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, isolation_level=None, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection


__all__ = [
    "JournalResult",
    "NamedToolAuthorizationJournal",
]
