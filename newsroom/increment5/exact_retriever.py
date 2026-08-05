"""Read-only SQLite exact retriever for Increment 5B.

The retriever exposes only fixed parameterised queries over admitted authority
surfaces.  It never writes to the authority database, invokes another branch,
performs fusion, or creates a Candidate.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import sqlite3
import time

from newsroom.authority.types import TrustScope, UtcTimestamp

from .branch_contracts import (
    BRANCH_RESULT_LIMIT,
    BRANCH_TIMEOUT_MS,
    CANDIDATE_COLLISION_POLICY_ID,
    EXACT_BRANCH_POLICY_ID,
    BranchExclusion,
    BranchExclusionReason,
    BranchOutcome,
    BranchReceiptId,
    CandidateCollisionRequest,
    ExactBranchHit,
    ExactBranchRequest,
    ExactLookupKind,
    Increment5BranchContractError,
)
from .branch_receipts import CandidateCollisionReceipt, ExactBranchReceipt
from .exact_queries import (
    _ALIAS_QUERY,
    _ENTITY_QUERY,
    _FORMAL_PROCESS_QUERY,
    _REPRESENTATION_QUERY,
    _REQUIRED_TABLES,
    _SOURCE_NATIVE_QUERY,
    _SOURCE_NATIVE_REVISION_QUERY,
    _SOURCE_REVISION_ID_QUERY,
    _WRITE_ACTIONS,
)
from .decision import INCREMENT_5A_CONTRACT_DIGEST
from .receipt_journal import BranchReceiptJournal, JournalResult


class ExactRetrieverError(RuntimeError):
    """The exact retrieval boundary cannot safely execute."""


class SQLiteExactRetriever:
    """Fixed-query exact retrieval against SQLite authority."""

    def __init__(
        self,
        *,
        authority_database: Path,
        journal: BranchReceiptJournal,
        receipt_id_factory: Callable[[], BranchReceiptId] = BranchReceiptId.new,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        if not isinstance(authority_database, Path):
            raise TypeError("authority database path must be a pathlib.Path")
        if not isinstance(journal, BranchReceiptJournal):
            raise TypeError("exact retriever journal must be typed")
        if not callable(receipt_id_factory) or not callable(monotonic_ns):
            raise TypeError("exact retriever factories must be callable")
        self._authority_database = authority_database.resolve()
        self._journal = journal
        self._receipt_id_factory = receipt_id_factory
        self._monotonic_ns = monotonic_ns

    def retrieve(self, request: ExactBranchRequest) -> JournalResult:
        if not isinstance(request, ExactBranchRequest):
            raise TypeError("exact retrieval request must be typed")
        return self._journal.execute_exact(request, lambda: self._execute_exact(request))

    def check_candidate_collision(
        self,
        request: CandidateCollisionRequest,
    ) -> JournalResult:
        if not isinstance(request, CandidateCollisionRequest):
            raise TypeError("Candidate collision request must be typed")
        return self._journal.execute_collision(
            request,
            lambda: self._execute_collision(request),
        )

    def _execute_exact(self, request: ExactBranchRequest) -> ExactBranchReceipt:
        start_ns = self._monotonic_ns()
        if request.contract_digest != INCREMENT_5A_CONTRACT_DIGEST:
            return self._exact_receipt(
                request,
                start_ns=start_ns,
                outcome=BranchOutcome.POLICY_BLOCKED,
                reason_code="CONTRACT_MISMATCH",
            )
        if request.policy_id != EXACT_BRANCH_POLICY_ID:
            return self._exact_receipt(
                request,
                start_ns=start_ns,
                outcome=BranchOutcome.POLICY_BLOCKED,
                reason_code="POLICY_MISMATCH",
            )
        if request.query_valid_time.value > request.serving_time.value:
            return self._exact_receipt(
                request,
                start_ns=start_ns,
                outcome=BranchOutcome.POLICY_BLOCKED,
                reason_code="QUERY_VALID_TIME_IN_FUTURE",
            )

        try:
            with self._open_read_only() as connection:
                required = _REQUIRED_TABLES[request.lookup_kind]
                if not self._has_tables(connection, required):
                    return self._exact_receipt(
                        request,
                        start_ns=start_ns,
                        outcome=BranchOutcome.UNAVAILABLE,
                        reason_code="AUTHORITY_SCHEMA_UNAVAILABLE",
                    )
                watermark = self._watermark(connection)
                if watermark < request.minimum_ledger_seq:
                    return self._exact_receipt(
                        request,
                        start_ns=start_ns,
                        outcome=BranchOutcome.STALE,
                        reason_code="AUTHORITY_WATERMARK_STALE",
                        authority_watermark=watermark,
                    )
                deadline = start_ns + request.timeout_ms * 1_000_000
                connection.set_progress_handler(
                    lambda: 1 if self._monotonic_ns() > deadline else 0,
                    500,
                )
                rows = self._lookup_rows(connection, request)
                if len(rows) > request.result_limit:
                    return self._exact_receipt(
                        request,
                        start_ns=start_ns,
                        outcome=BranchOutcome.INCOMPLETE,
                        reason_code="RESULT_BOUND_EXCEEDED",
                        authority_watermark=watermark,
                    )
                hits, exclusions = self._admit_rows(rows, request.query_valid_time)
                if not hits and exclusions:
                    reason = (
                        "RIGHTS_BLOCKED"
                        if any(
                            item.reason is BranchExclusionReason.RIGHTS_NOT_CURRENT
                            for item in exclusions
                        )
                        else "AUTHORITY_STATE_BLOCKED"
                    )
                    return self._exact_receipt(
                        request,
                        start_ns=start_ns,
                        outcome=BranchOutcome.POLICY_BLOCKED,
                        reason_code=reason,
                        authority_watermark=watermark,
                        exclusions=exclusions,
                    )
                return self._exact_receipt(
                    request,
                    start_ns=start_ns,
                    outcome=BranchOutcome.COMPLETE,
                    reason_code=(
                        "NO_MATCH"
                        if not hits
                        else "OK_WITH_EXCLUSIONS"
                        if exclusions
                        else "OK"
                    ),
                    authority_watermark=watermark,
                    hits=hits,
                    exclusions=exclusions,
                )
        except sqlite3.OperationalError as exc:
            if "interrupted" in str(exc).lower():
                return self._exact_receipt(
                    request,
                    start_ns=start_ns,
                    outcome=BranchOutcome.INCOMPLETE,
                    reason_code="QUERY_TIMEOUT",
                )
            return self._exact_receipt(
                request,
                start_ns=start_ns,
                outcome=BranchOutcome.UNAVAILABLE,
                reason_code="AUTHORITY_DATABASE_UNAVAILABLE",
            )
        except (sqlite3.Error, Increment5BranchContractError, ValueError, KeyError):
            return self._exact_receipt(
                request,
                start_ns=start_ns,
                outcome=BranchOutcome.UNAVAILABLE,
                reason_code="AUTHORITY_INTEGRITY_ERROR",
            )

    def _execute_collision(
        self,
        request: CandidateCollisionRequest,
    ) -> CandidateCollisionReceipt:
        start_ns = self._monotonic_ns()
        if request.contract_digest != INCREMENT_5A_CONTRACT_DIGEST:
            return self._collision_receipt(
                request,
                start_ns=start_ns,
                outcome=BranchOutcome.POLICY_BLOCKED,
                reason_code="CONTRACT_MISMATCH",
            )
        if request.policy_id != CANDIDATE_COLLISION_POLICY_ID:
            return self._collision_receipt(
                request,
                start_ns=start_ns,
                outcome=BranchOutcome.POLICY_BLOCKED,
                reason_code="POLICY_MISMATCH",
            )
        if request.query_valid_time.value > request.serving_time.value:
            return self._collision_receipt(
                request,
                start_ns=start_ns,
                outcome=BranchOutcome.POLICY_BLOCKED,
                reason_code="QUERY_VALID_TIME_IN_FUTURE",
            )
        try:
            with self._open_read_only() as connection:
                if not self._has_tables(
                    connection,
                    frozenset({"ledger_events", "development_candidates_v2"}),
                ):
                    return self._collision_receipt(
                        request,
                        start_ns=start_ns,
                        outcome=BranchOutcome.UNAVAILABLE,
                        reason_code="AUTHORITY_SCHEMA_UNAVAILABLE",
                    )
                watermark = self._watermark(connection)
                if watermark < request.minimum_ledger_seq:
                    return self._collision_receipt(
                        request,
                        start_ns=start_ns,
                        outcome=BranchOutcome.STALE,
                        reason_code="AUTHORITY_WATERMARK_STALE",
                        authority_watermark=watermark,
                    )
                deadline = start_ns + request.timeout_ms * 1_000_000
                connection.set_progress_handler(
                    lambda: 1 if self._monotonic_ns() > deadline else 0,
                    500,
                )
                rows = connection.execute(
                    "SELECT candidate_id FROM development_candidates_v2 "
                    "WHERE semantic_collision_digest=? ORDER BY candidate_id LIMIT 2",
                    (request.semantic_collision_digest,),
                ).fetchall()
                if len(rows) > 1:
                    return self._collision_receipt(
                        request,
                        start_ns=start_ns,
                        outcome=BranchOutcome.INCOMPLETE,
                        reason_code="AUTHORITY_INTEGRITY_ERROR",
                        authority_watermark=watermark,
                    )
                candidate_id = None if not rows else str(rows[0]["candidate_id"])
                return self._collision_receipt(
                    request,
                    start_ns=start_ns,
                    outcome=BranchOutcome.COMPLETE,
                    reason_code="OCCUPIED" if candidate_id is not None else "UNOCCUPIED",
                    authority_watermark=watermark,
                    occupied=candidate_id is not None,
                    candidate_id=candidate_id,
                )
        except sqlite3.OperationalError as exc:
            if "interrupted" in str(exc).lower():
                return self._collision_receipt(
                    request,
                    start_ns=start_ns,
                    outcome=BranchOutcome.INCOMPLETE,
                    reason_code="QUERY_TIMEOUT",
                )
            return self._collision_receipt(
                request,
                start_ns=start_ns,
                outcome=BranchOutcome.UNAVAILABLE,
                reason_code="AUTHORITY_DATABASE_UNAVAILABLE",
            )
        except (sqlite3.Error, Increment5BranchContractError, ValueError, KeyError):
            return self._collision_receipt(
                request,
                start_ns=start_ns,
                outcome=BranchOutcome.UNAVAILABLE,
                reason_code="AUTHORITY_INTEGRITY_ERROR",
            )

    def _lookup_rows(
        self,
        connection: sqlite3.Connection,
        request: ExactBranchRequest,
    ) -> list[sqlite3.Row]:
        limit = request.result_limit + 1
        value = request.lookup_value
        if request.lookup_kind is ExactLookupKind.SOURCE_NATIVE_ID:
            return list(
                connection.execute(
                    _SOURCE_NATIVE_QUERY,
                    (request.authority_scope_id, value, limit),
                )
            )
        if request.lookup_kind is ExactLookupKind.SOURCE_REVISION_ID:
            return list(connection.execute(_SOURCE_REVISION_ID_QUERY, (value, limit)))
        if request.lookup_kind is ExactLookupKind.SOURCE_NATIVE_REVISION_TOKEN:
            return list(
                connection.execute(
                    _SOURCE_NATIVE_REVISION_QUERY,
                    (request.authority_scope_id, value, limit),
                )
            )
        if request.lookup_kind is ExactLookupKind.REPRESENTATION_ID:
            return list(connection.execute(_REPRESENTATION_QUERY, (value, limit)))
        if request.lookup_kind is ExactLookupKind.CANONICAL_ENTITY_ID:
            return list(connection.execute(_ENTITY_QUERY, (value, limit)))
        if request.lookup_kind is ExactLookupKind.AUTHORITY_ALIAS:
            return list(
                connection.execute(
                    _ALIAS_QUERY,
                    (value, value, value, value, limit),
                )
            )
        if request.lookup_kind is ExactLookupKind.FORMAL_PROCESS_ID:
            return list(connection.execute(_FORMAL_PROCESS_QUERY, (value, limit)))
        raise Increment5BranchContractError("unsupported exact lookup kind")

    @staticmethod
    def _admit_rows(
        rows: list[sqlite3.Row],
        query_valid_time: UtcTimestamp,
    ) -> tuple[tuple[ExactBranchHit, ...], tuple[BranchExclusion, ...]]:
        hits: list[ExactBranchHit] = []
        exclusions: list[BranchExclusion] = []
        for row in rows:
            authority_kind = str(row["authority_kind"])
            authority_id = str(row["authority_id"])
            allowed_use = str(row["allowed_use"] or "").upper()
            lifecycle = str(row["lifecycle_state"] or "").upper()
            if any(token in allowed_use for token in ("PROHIBITED", "DENIED", "REVOKED")):
                exclusions.append(
                    BranchExclusion(
                        authority_kind=authority_kind,
                        authority_id=authority_id,
                        reason=BranchExclusionReason.RIGHTS_NOT_CURRENT,
                    )
                )
                continue
            if lifecycle in {"RETIRED", "REJECTED", "MERGED", "SPLIT", "REVERSED"}:
                exclusions.append(
                    BranchExclusion(
                        authority_kind=authority_kind,
                        authority_id=authority_id,
                        reason=BranchExclusionReason.TOMBSTONED,
                    )
                )
                continue
            valid_from = row["valid_from"]
            valid_until = row["valid_until"]
            if (
                valid_from is not None
                and query_valid_time.value < UtcTimestamp.parse(str(valid_from)).value
            ) or (
                valid_until is not None
                and query_valid_time.value >= UtcTimestamp.parse(str(valid_until)).value
            ):
                exclusions.append(
                    BranchExclusion(
                        authority_kind=authority_kind,
                        authority_id=authority_id,
                        reason=BranchExclusionReason.OUTSIDE_QUERY_VALID_TIME,
                    )
                )
                continue
            hits.append(
                ExactBranchHit(
                    rank=len(hits) + 1,
                    authority_kind=authority_kind,
                    authority_id=authority_id,
                    dependency_root_id=str(row["dependency_root_id"]),
                    match_signal=str(row["match_signal"]),
                    source_identity=str(row["source_identity"]),
                    trust_scope=TrustScope(str(row["trust_scope"])),
                    provenance_digest=str(row["provenance_digest"]),
                )
            )
        return tuple(hits), tuple(exclusions)

    def _exact_receipt(
        self,
        request: ExactBranchRequest,
        *,
        start_ns: int,
        outcome: BranchOutcome,
        reason_code: str,
        authority_watermark: int = 0,
        hits: tuple[ExactBranchHit, ...] = (),
        exclusions: tuple[BranchExclusion, ...] = (),
    ) -> ExactBranchReceipt:
        elapsed_ms, timed_out = self._receipt_timing(start_ns)
        if timed_out:
            outcome = BranchOutcome.INCOMPLETE
            reason_code = "QUERY_TIMEOUT"
            hits = ()
            exclusions = ()
        return ExactBranchReceipt(
            receipt_id=self._receipt_id_factory(),
            request_id=request.request_id,
            request_digest=request.request_digest,
            contract_digest=request.contract_digest,
            policy_id=request.policy_id,
            outcome=outcome,
            reason_code=reason_code,
            authority_watermark=authority_watermark,
            started_at=request.serving_time,
            completed_at=request.serving_time,
            elapsed_ms=elapsed_ms,
            hits=hits,
            exclusions=exclusions,
        )

    def _collision_receipt(
        self,
        request: CandidateCollisionRequest,
        *,
        start_ns: int,
        outcome: BranchOutcome,
        reason_code: str,
        authority_watermark: int = 0,
        occupied: bool = False,
        candidate_id: str | None = None,
    ) -> CandidateCollisionReceipt:
        elapsed_ms, timed_out = self._receipt_timing(start_ns)
        if timed_out:
            outcome = BranchOutcome.INCOMPLETE
            reason_code = "QUERY_TIMEOUT"
            occupied = False
            candidate_id = None
        return CandidateCollisionReceipt(
            receipt_id=self._receipt_id_factory(),
            request_id=request.request_id,
            request_digest=request.request_digest,
            contract_digest=request.contract_digest,
            policy_id=request.policy_id,
            outcome=outcome,
            reason_code=reason_code,
            authority_watermark=authority_watermark,
            occupied=occupied,
            candidate_id=candidate_id,
            started_at=request.serving_time,
            completed_at=request.serving_time,
            elapsed_ms=elapsed_ms,
        )

    def _receipt_timing(self, start_ns: int) -> tuple[int, bool]:
        completed = self._monotonic_ns()
        if completed < start_ns:
            raise ExactRetrieverError("monotonic clock moved backwards")
        actual_ms = (completed - start_ns) // 1_000_000
        return min(BRANCH_TIMEOUT_MS, actual_ms), actual_ms > BRANCH_TIMEOUT_MS

    def _open_read_only(self) -> sqlite3.Connection:
        if not self._authority_database.is_file():
            raise sqlite3.OperationalError("authority database unavailable")
        uri = self._authority_database.as_uri() + "?mode=ro"
        connection = sqlite3.connect(
            uri,
            uri=True,
            isolation_level=None,
            timeout=5.0,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.set_authorizer(self._read_only_authorizer)
        return connection

    @staticmethod
    def _read_only_authorizer(
        action: int,
        _arg1: str | None,
        _arg2: str | None,
        _database: str | None,
        _trigger: str | None,
    ) -> int:
        if action in _WRITE_ACTIONS:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    @staticmethod
    def _has_tables(
        connection: sqlite3.Connection,
        required: frozenset[str],
    ) -> bool:
        placeholders = ",".join("?" for _ in required)
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ("
            + placeholders
            + ")",
            tuple(sorted(required)),
        ).fetchall()
        return {str(row["name"]) for row in rows} == set(required)

    @staticmethod
    def _watermark(connection: sqlite3.Connection) -> int:
        row = connection.execute(
            "SELECT COALESCE(MAX(ledger_seq),0) AS watermark FROM ledger_events"
        ).fetchone()
        if row is None:
            return 0
        value = row["watermark"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise Increment5BranchContractError("authority watermark is malformed")
        return value


__all__ = ["ExactRetrieverError", "SQLiteExactRetriever"]
