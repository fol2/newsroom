"""Checked SQLite persistence for bounded Search records.

The authority stores caller-supplied fixture/replay assertions only. It has no
provider client, credential, network, scheduler, retry executor or publication
capability. Gross limits are rechecked in one database-owned transaction.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.migrations import (
    SCHEMA_VERSION,
    apply_pending_migrations,
    prepare_pending_migration_backup,
)
from newsroom.increment7.search import (
    SearchAttempt,
    SearchOutcome,
    SearchPurpose,
    SearchRequest,
    SearchResultReference,
    SearchReviewDecision,
    validate_search_attempt,
    validate_search_outcome,
    validate_search_request,
    validate_search_result,
    validate_search_review,
)

BOUNDED_SEARCH_AUTHORITY = "CHECKED_SQLITE_TRANSACTIONAL_V27"
SEARCH_BUDGET_AUTHORITY = "DETERMINISTIC_GROSS_REQUEST_AGGREGATE"
SEARCH_PROVIDER_PORT = "DISABLED_NO_IMPLEMENTATION"
SEARCH_PRIVACY_AUTHORITY = "EXACT_PURPOSE_REQUEST_REPLAY"


class SearchAuthorityError(ValueError):
    """A persisted Search record or exact authority transition failed closed."""


class _NoEffect:
    authorises_external_effect = False
    authorises_provider = False
    authorises_credentials = False
    authorises_egress = False
    authorises_spend = False
    authorises_schedule = False
    authorises_retry_execution = False
    authorises_fallback = False
    authorises_recursive_search = False
    authorises_publication = False
    creates_signal = False
    creates_lead = False
    creates_candidate = False
    production_activation_authorised = False


def _total(label: str):
    def decorate(function):
        def wrapped(*args: object, **kwargs: object):
            try:
                return function(*args, **kwargs)
            except SearchAuthorityError:
                raise
            except Exception as exc:
                raise SearchAuthorityError(label) from exc

        return wrapped

    return decorate


@dataclass(frozen=True, slots=True)
class SearchBudgetSnapshot(_NoEffect):
    request_id: str
    provider_calls: int
    result_count: int
    gross_cost_microunits: int
    ledger_digest: str | None


_TOKEN = object()


class BoundedSearchReadPort(_NoEffect):
    """Immutable, transaction-owned exact replay port."""

    __slots__ = ("_connection",)

    def __init__(self, token: object, connection: sqlite3.Connection) -> None:
        if token is not _TOKEN:
            raise SearchAuthorityError("bounded Search port construction is private")
        object.__setattr__(self, "_connection", connection)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("BoundedSearchReadPort is immutable")

    def _record(self, table: str, identifier_column: str, identifier: str, kind):
        row = self._connection.execute(
            f"SELECT * FROM {table} WHERE {identifier_column}=?", (identifier,)
        ).fetchone()
        if row is None:
            raise SearchAuthorityError("bounded Search record is absent")
        columns = tuple(
            item[1] for item in self._connection.execute(f"PRAGMA table_info({table})")
        )
        values = dict(zip(columns, row, strict=True))
        bytes_column = next(name for name in columns if name.endswith("_bytes"))
        digest_column = next(name for name in columns if name.endswith("_digest"))
        record = kind.from_canonical_bytes(bytes(values[bytes_column]))
        if record.digest != values[digest_column]:
            raise SearchAuthorityError("bounded Search retained digest differs")
        return record, values

    @_total("Search Purpose replay failed")
    def purpose(self, purpose_id: str) -> SearchPurpose:
        record, row = self._record(
            "search_purposes", "purpose_id", purpose_id, SearchPurpose
        )
        if (
            record.purpose_id != row["purpose_id"]
            or record.purpose_kind.value != row["purpose_kind"]
            or record.query_privacy.value != row["query_privacy"]
            or record.created_at != row["created_at"]
        ):
            raise SearchAuthorityError("Search Purpose retained columns differ")
        return record

    @_total("Search Request replay failed")
    def request(self, request_id: str) -> SearchRequest:
        record, row = self._record(
            "search_requests", "request_id", request_id, SearchRequest
        )
        purpose = self.purpose(record.purpose_id)
        validate_search_request(purpose, record)
        if (
            record.request_id != row["request_id"]
            or record.purpose_id != row["purpose_id"]
            or record.purpose_digest != row["purpose_digest"]
            or record.provider_id != row["provider_id"]
            or record.provider_configuration_digest
            != row["provider_configuration_digest"]
            or record.budget_reservation_digest != row["budget_reservation_digest"]
            or record.query_privacy.value != row["query_privacy"]
            or record.limits.max_provider_calls != row["max_provider_calls"]
            or record.limits.max_results != row["max_results"]
            or record.limits.max_gross_cost_microunits
            != row["max_gross_cost_microunits"]
            or record.limits.max_elapsed_seconds != row["max_elapsed_seconds"]
            or record.requested_at != row["requested_at"]
        ):
            raise SearchAuthorityError("Search Request retained columns differ")
        return record

    @_total("Search Attempt replay failed")
    def attempt(self, attempt_id: str) -> SearchAttempt:
        record, row = self._record(
            "search_attempts", "attempt_id", attempt_id, SearchAttempt
        )
        request = self.request(record.request_id)
        validate_search_attempt(request, record)
        if (
            record.request_digest != row["request_digest"]
            or record.attempt_ordinal != row["attempt_ordinal"]
            or record.variant_ordinal != row["variant_ordinal"]
            or record.language_ordinal != row["language_ordinal"]
            or record.page_number != row["page_number"]
            or record.retry_ordinal != row["retry_ordinal"]
            or record.branch_ordinal != row["branch_ordinal"]
            or record.started_at != row["started_at"]
        ):
            raise SearchAuthorityError("Search Attempt retained columns differ")
        return record

    @_total("Search Outcome replay failed")
    def outcome(self, outcome_id: str) -> SearchOutcome:
        record, row = self._record(
            "search_outcomes", "outcome_id", outcome_id, SearchOutcome
        )
        attempt = self.attempt(record.attempt_id)
        request = self.request(attempt.request_id)
        validate_search_outcome(attempt, record, request)
        if (
            record.attempt_digest != row["attempt_digest"]
            or record.outcome_kind.value != row["outcome_kind"]
            or record.result_count != row["result_count"]
            or record.returned_pages != row["returned_pages"]
            or record.gross_cost_microunits != row["gross_cost_microunits"]
            or record.completed_at != row["completed_at"]
        ):
            raise SearchAuthorityError("Search Outcome retained columns differ")
        return record

    @_total("Search Result Reference replay failed")
    def result(self, result_reference_id: str) -> SearchResultReference:
        record, row = self._record(
            "search_result_references",
            "result_reference_id",
            result_reference_id,
            SearchResultReference,
        )
        outcome = self.outcome(record.outcome_id)
        attempt = self.attempt(outcome.attempt_id)
        validate_search_result(outcome, record, attempt)
        if (
            record.outcome_digest != row["outcome_digest"]
            or record.request_id != row["request_id"]
            or record.request_digest != row["request_digest"]
            or record.rank != row["rank"]
            or record.page_number != row["page_number"]
            or record.recorded_at != row["recorded_at"]
        ):
            raise SearchAuthorityError("Search Result retained columns differ")
        return record

    @_total("Search Review Decision replay failed")
    def review(self, review_decision_id: str) -> SearchReviewDecision:
        record, row = self._record(
            "search_review_decisions",
            "review_decision_id",
            review_decision_id,
            SearchReviewDecision,
        )
        request = self.request(str(row["request_id"]))
        results = tuple(
            self.result(identifier) for identifier in record.result_reference_ids
        )
        validate_search_review(results, record, request)
        if (
            request.digest != row["request_digest"]
            or record.action.value != row["action"]
            or record.work_reference_digest != row["work_reference_digest"]
            or record.decided_at != row["decided_at"]
        ):
            raise SearchAuthorityError("Search Review retained columns differ")
        return record

    @_total("Search budget replay failed")
    def budget(self, request_id: str) -> SearchBudgetSnapshot:
        request = self.request(request_id)
        row = self._connection.execute(
            "SELECT cumulative_provider_calls,cumulative_results,"
            "cumulative_gross_cost_microunits,ledger_digest FROM search_budget_ledger "
            "WHERE request_id=? ORDER BY cumulative_provider_calls DESC LIMIT 1",
            (request_id,),
        ).fetchone()
        snapshot = (
            SearchBudgetSnapshot(request_id, 0, 0, 0, None)
            if row is None
            else SearchBudgetSnapshot(request_id, row[0], row[1], row[2], row[3])
        )
        if (
            snapshot.provider_calls > request.limits.max_provider_calls
            or snapshot.result_count > request.limits.max_results
            or snapshot.gross_cost_microunits > request.limits.max_gross_cost_microunits
        ):
            raise SearchAuthorityError("Search retained gross budget differs")
        return snapshot


class BoundedSearchAuthority(BoundedSearchReadPort):
    """Transactional v27 writer with exact replay and gross preauthorisation."""

    __slots__ = ("_closed",)

    def __init__(self, token: object, connection: sqlite3.Connection) -> None:
        super().__init__(token, connection)
        object.__setattr__(self, "_closed", False)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("BoundedSearchAuthority is immutable")

    def _begin(self) -> None:
        if self._closed:
            raise SearchAuthorityError("bounded Search authority is closed")
        self._connection.execute("BEGIN IMMEDIATE")

    def _finish(self, error: BaseException | None = None) -> None:
        if self._connection.in_transaction:
            self._connection.execute("ROLLBACK" if error else "COMMIT")

    def _exact_replay(
        self, table: str, identifier_column: str, identifier: str, raw: bytes
    ) -> bool:
        bytes_column = {
            "search_purposes": "purpose_bytes",
            "search_requests": "request_bytes",
            "search_attempts": "attempt_bytes",
            "search_outcomes": "outcome_bytes",
            "search_result_references": "result_bytes",
            "search_review_decisions": "decision_bytes",
        }[table]
        row = self._connection.execute(
            f"SELECT {bytes_column} FROM {table} WHERE {identifier_column}=?",
            (identifier,),
        ).fetchone()
        if row is None:
            return False
        if bytes(row[0]) != raw:
            raise SearchAuthorityError("bounded Search identity replay conflicts")
        return True

    @_total("Search Purpose persistence failed")
    def record_purpose(self, raw: bytes) -> SearchPurpose:
        record = SearchPurpose.from_canonical_bytes(raw)
        self._begin()
        try:
            replay = self._exact_replay(
                "search_purposes", "purpose_id", record.purpose_id, raw
            )
            if not replay:
                self._connection.execute(
                    "INSERT INTO search_purposes VALUES(?,?,?,?,?,?)",
                    (
                        record.purpose_id,
                        raw,
                        record.digest,
                        record.purpose_kind.value,
                        record.query_privacy.value,
                        record.created_at,
                    ),
                )
            self._finish()
        except BaseException as exc:
            self._finish(exc)
            raise
        return self.purpose(record.purpose_id)

    @_total("Search Request persistence failed")
    def record_request(self, raw: bytes) -> SearchRequest:
        record = SearchRequest.from_canonical_bytes(raw)
        self._begin()
        try:
            purpose = self.purpose(record.purpose_id)
            validate_search_request(purpose, record)
            replay = self._exact_replay(
                "search_requests", "request_id", record.request_id, raw
            )
            if not replay:
                self._connection.execute(
                    "INSERT INTO search_requests VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        record.request_id,
                        raw,
                        record.digest,
                        record.purpose_id,
                        record.purpose_digest,
                        record.provider_id,
                        record.provider_configuration_digest,
                        record.budget_reservation_digest,
                        record.query_privacy.value,
                        record.limits.max_provider_calls,
                        record.limits.max_results,
                        record.limits.max_gross_cost_microunits,
                        record.limits.max_elapsed_seconds,
                        record.requested_at,
                    ),
                )
            self._finish()
        except BaseException as exc:
            self._finish(exc)
            raise
        return self.request(record.request_id)

    @_total("Search Attempt persistence failed")
    def record_attempt(self, raw: bytes) -> SearchAttempt:
        record = SearchAttempt.from_canonical_bytes(raw)
        self._begin()
        try:
            request = self.request(record.request_id)
            validate_search_attempt(request, record)
            replay = self._exact_replay(
                "search_attempts", "attempt_id", record.attempt_id, raw
            )
            if not replay:
                count = self._connection.execute(
                    "SELECT count(*) FROM search_attempts WHERE request_id=?",
                    (record.request_id,),
                ).fetchone()[0]
                active = self._connection.execute(
                    "SELECT count(*) FROM search_attempts a "
                    "LEFT JOIN search_outcomes o ON o.attempt_id=a.attempt_id "
                    "WHERE a.request_id=? AND o.outcome_id IS NULL",
                    (record.request_id,),
                ).fetchone()[0]
                if (
                    record.attempt_ordinal != count + 1
                    or active >= request.limits.max_concurrent_attempts
                ):
                    raise SearchAuthorityError("Search Attempt ordinal CAS differs")
                self._connection.execute(
                    "INSERT INTO search_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        record.attempt_id,
                        raw,
                        record.digest,
                        record.request_id,
                        record.request_digest,
                        record.attempt_ordinal,
                        record.variant_ordinal,
                        record.language_ordinal,
                        record.page_number,
                        record.retry_ordinal,
                        record.branch_ordinal,
                        record.started_at,
                    ),
                )
            self._finish()
        except BaseException as exc:
            self._finish(exc)
            raise
        return self.attempt(record.attempt_id)

    @_total("Search Outcome persistence failed")
    def record_outcome(self, raw: bytes) -> SearchOutcome:
        record = SearchOutcome.from_canonical_bytes(raw)
        self._begin()
        try:
            attempt = self.attempt(record.attempt_id)
            request = self.request(attempt.request_id)
            validate_search_outcome(attempt, record, request)
            replay = self._exact_replay(
                "search_outcomes", "outcome_id", record.outcome_id, raw
            )
            if not replay:
                previous = self.budget(request.request_id)
                calls = previous.provider_calls + 1
                results = previous.result_count + record.result_count
                cost = previous.gross_cost_microunits + record.gross_cost_microunits
                if (
                    attempt.attempt_ordinal != calls
                    or calls > request.limits.max_provider_calls
                    or results > request.limits.max_results
                    or cost > request.limits.max_gross_cost_microunits
                ):
                    raise SearchAuthorityError("Search gross budget CAS differs")
                self._connection.execute(
                    "INSERT INTO search_outcomes VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        record.outcome_id,
                        raw,
                        record.digest,
                        record.attempt_id,
                        record.attempt_digest,
                        record.outcome_kind.value,
                        record.result_count,
                        record.returned_pages,
                        record.gross_cost_microunits,
                        record.completed_at,
                    ),
                )
                ledger_digest = digest_bytes(
                    canonical_json_bytes(
                        {
                            "attempt_id": attempt.attempt_id,
                            "cumulative_gross_cost_microunits": cost,
                            "cumulative_provider_calls": calls,
                            "cumulative_results": results,
                            "outcome_digest": record.digest,
                            "request_id": request.request_id,
                        }
                    )
                )
                self._connection.execute(
                    "INSERT INTO search_budget_ledger VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        record.outcome_id,
                        request.request_id,
                        attempt.attempt_id,
                        record.gross_cost_microunits,
                        calls,
                        results,
                        cost,
                        ledger_digest,
                        record.completed_at,
                    ),
                )
            self._finish()
        except BaseException as exc:
            self._finish(exc)
            raise
        return self.outcome(record.outcome_id)

    @_total("Search Result Reference persistence failed")
    def record_result(self, raw: bytes) -> SearchResultReference:
        record = SearchResultReference.from_canonical_bytes(raw)
        self._begin()
        try:
            outcome = self.outcome(record.outcome_id)
            attempt = self.attempt(outcome.attempt_id)
            validate_search_result(outcome, record, attempt)
            replay = self._exact_replay(
                "search_result_references",
                "result_reference_id",
                record.result_reference_id,
                raw,
            )
            if not replay:
                count = self._connection.execute(
                    "SELECT count(*) FROM search_result_references WHERE outcome_id=?",
                    (record.outcome_id,),
                ).fetchone()[0]
                if count >= outcome.result_count:
                    raise SearchAuthorityError("Search retained result budget differs")
                self._connection.execute(
                    "INSERT INTO search_result_references VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        record.result_reference_id,
                        raw,
                        record.digest,
                        record.outcome_id,
                        record.outcome_digest,
                        record.request_id,
                        record.request_digest,
                        record.rank,
                        record.page_number,
                        record.recorded_at,
                    ),
                )
            self._finish()
        except BaseException as exc:
            self._finish(exc)
            raise
        return self.result(record.result_reference_id)

    @_total("Search Review Decision persistence failed")
    def record_review(self, raw: bytes) -> SearchReviewDecision:
        record = SearchReviewDecision.from_canonical_bytes(raw)
        self._begin()
        try:
            results = tuple(
                self.result(identifier) for identifier in record.result_reference_ids
            )
            request_ids = {item.request_id for item in results}
            if len(request_ids) != 1:
                raise SearchAuthorityError("Search Review spans Requests")
            request = self.request(request_ids.pop())
            validate_search_review(results, record, request)
            replay = self._exact_replay(
                "search_review_decisions",
                "review_decision_id",
                record.review_decision_id,
                raw,
            )
            if not replay:
                self._connection.execute(
                    "INSERT INTO search_review_decisions VALUES(?,?,?,?,?,?,?,?)",
                    (
                        record.review_decision_id,
                        raw,
                        record.digest,
                        request.request_id,
                        request.digest,
                        record.action.value,
                        record.work_reference_digest,
                        record.decided_at,
                    ),
                )
            self._finish()
        except BaseException as exc:
            self._finish(exc)
            raise
        return self.review(record.review_decision_id)

    def read_port(self) -> BoundedSearchReadPort:
        return BoundedSearchReadPort(_TOKEN, self._connection)

    def close(self) -> None:
        if not self._closed:
            self._connection.close()
            object.__setattr__(self, "_closed", True)


@_total("bounded Search authority open failed")
def open_bounded_search_authority(
    database: str | Path,
    *,
    applied_at: str,
) -> BoundedSearchAuthority:
    """Open checked v27 authority, retaining an exact v26 backup when required."""
    if type(applied_at) is not str or len(applied_at) != 27:
        raise SearchAuthorityError("applied_at differs")
    try:
        parsed_applied_at = datetime.strptime(applied_at, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise SearchAuthorityError("applied_at differs") from exc
    if parsed_applied_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ") != applied_at:
        raise SearchAuthorityError("applied_at differs")
    if database != ":memory:" and not isinstance(database, (str, Path)):
        raise SearchAuthorityError("database path differs")
    connection = sqlite3.connect(str(database), isolation_level=None, timeout=30)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version < SCHEMA_VERSION:
            prepare_pending_migration_backup(connection)
        apply_pending_migrations(connection, applied_at=applied_at)
        if (
            connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION
            or connection.execute("PRAGMA foreign_key_check").fetchall()
            or connection.execute("PRAGMA quick_check").fetchone()[0] != "ok"
        ):
            raise SearchAuthorityError("checked v27 schema differs")
        return BoundedSearchAuthority(_TOKEN, connection)
    except BaseException:
        connection.close()
        raise


__all__ = [
    "BOUNDED_SEARCH_AUTHORITY",
    "SEARCH_BUDGET_AUTHORITY",
    "SEARCH_PRIVACY_AUTHORITY",
    "SEARCH_PROVIDER_PORT",
    "BoundedSearchAuthority",
    "BoundedSearchReadPort",
    "SearchAuthorityError",
    "SearchBudgetSnapshot",
    "open_bounded_search_authority",
]
