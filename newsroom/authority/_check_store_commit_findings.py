from __future__ import annotations

from newsroom.authority._capability import _AuthorizedCommandGrant
from newsroom.checks.finding_models import (
    OperationalFindingOccurrenceRequest,
    OperationalFindingRequest,
)
from newsroom.checks.policy import (
    OPERATIONAL_FINDING_OCCURRENCE_RECORD_COMMAND,
    OPERATIONAL_FINDING_OPEN_COMMAND,
)
from newsroom.checks.record_models import (
    OperationalFinding,
    OperationalFindingOccurrence,
)
from newsroom.checks.types import CheckStateError, FindingScopeKind


class _CheckStoreCommitFindingMixin:
    def _require_finding_lineage(
        self,
        conn,
        *,
        request_id,
        attempt_id,
        outcome_id,
    ) -> None:
        parent_request = None
        if request_id is not None:
            parent_request = self._check_request_row(conn, str(request_id))
        if attempt_id is not None:
            attempt = self._check_attempt_row(conn, str(attempt_id))
            if (
                parent_request is not None
                and str(attempt["request_id"]) != str(request_id)
            ):
                raise CheckStateError(
                    "Operational Finding Attempt differs from Request"
                )
            if parent_request is None:
                parent_request = self._check_request_row(
                    conn,
                    str(attempt["request_id"]),
                )
        if outcome_id is not None:
            outcome = self._check_outcome_row(conn, str(outcome_id))
            if request_id is not None and str(outcome["request_id"]) != str(
                request_id
            ):
                raise CheckStateError(
                    "Operational Finding Outcome differs from Request"
                )
            if attempt_id is not None and str(outcome["attempt_id"]) != str(
                attempt_id
            ):
                raise CheckStateError(
                    "Operational Finding Outcome differs from Attempt"
                )

    def commit_operational_finding(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        request: OperationalFindingRequest,
    ) -> OperationalFinding:
        if not isinstance(request, OperationalFindingRequest):
            raise TypeError(
                "Operational Finding commit requires a typed request"
            )
        self._require_check_grant(
            grant,
            command_type=OPERATIONAL_FINDING_OPEN_COMMAND,
            aggregate_id=str(request.finding_id),
            canonical_bytes=request.canonical_bytes,
        )
        with self._lock, self._transaction() as conn:
            if grant.replay_of_command_id is not None:
                committed = self._commit_grant_in_transaction(
                    conn,
                    grant,
                    recorded_at=self._clock().to_text(),
                )
                return self._operational_finding_for_event(
                    conn,
                    committed.event_id,
                    replayed=True,
                )
            self._require_finding_lineage(
                conn,
                request_id=request.opened_by_request_id,
                attempt_id=request.opened_by_attempt_id,
                outcome_id=request.opened_by_outcome_id,
            )
            lineage_error = self._finding_lineage_error(
                conn,
                scope_kind=request.scope_kind,
                scope_id=request.scope_id,
                request_id=request.opened_by_request_id,
                attempt_id=request.opened_by_attempt_id,
                outcome_id=request.opened_by_outcome_id,
                observed_at=request.opened_at,
            )
            if lineage_error is not None:
                raise CheckStateError(lineage_error)
            self._check_identifier_absent(
                conn,
                table="operational_findings",
                column="finding_id",
                identifier=str(request.finding_id),
                identity="Operational Finding identity",
            )
            self._check_semantic_absent(
                conn,
                table="operational_findings",
                semantic_digest=request.semantic_digest,
                identity="Operational Finding semantics",
            )
            recorded_at = self._clock().to_text()
            committed = self._commit_grant_in_transaction(
                conn,
                grant,
                recorded_at=recorded_at,
            )
            if committed.replayed:
                return self._operational_finding_for_event(
                    conn,
                    committed.event_id,
                    replayed=True,
                )
            conn.execute(
                "INSERT INTO operational_findings("
                "finding_id,scope_kind,scope_id,category,severity,"
                "finding_policy_id,finding_policy_version,summary,"
                "opened_by_request_id,opened_by_attempt_id,opened_by_outcome_id,"
                "opened_at,semantic_digest,authority_event_id,"
                "authority_aggregate_version,canonical_bytes,canonical_digest,"
                "recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(request.finding_id),
                    request.scope_kind.value,
                    request.scope_id,
                    request.category.value,
                    request.severity.value,
                    request.finding_policy.policy_id,
                    request.finding_policy.policy_version,
                    request.summary,
                    (
                        None
                        if request.opened_by_request_id is None
                        else str(request.opened_by_request_id)
                    ),
                    (
                        None
                        if request.opened_by_attempt_id is None
                        else str(request.opened_by_attempt_id)
                    ),
                    (
                        None
                        if request.opened_by_outcome_id is None
                        else str(request.opened_by_outcome_id)
                    ),
                    request.opened_at.to_text(),
                    request.semantic_digest,
                    committed.event_id,
                    committed.aggregate_version,
                    request.canonical_bytes,
                    request.digest,
                    recorded_at,
                ),
            )
            return self._operational_finding_for_event(
                conn,
                committed.event_id,
                replayed=False,
            )

    def commit_operational_finding_occurrence(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        request: OperationalFindingOccurrenceRequest,
    ) -> OperationalFindingOccurrence:
        if not isinstance(request, OperationalFindingOccurrenceRequest):
            raise TypeError(
                "Finding occurrence commit requires a typed request"
            )
        self._require_check_grant(
            grant,
            command_type=OPERATIONAL_FINDING_OCCURRENCE_RECORD_COMMAND,
            aggregate_id=str(request.occurrence_id),
            canonical_bytes=request.canonical_bytes,
        )
        with self._lock, self._transaction() as conn:
            if grant.replay_of_command_id is not None:
                committed = self._commit_grant_in_transaction(
                    conn,
                    grant,
                    recorded_at=self._clock().to_text(),
                )
                return self._finding_occurrence_for_event(
                    conn,
                    committed.event_id,
                    replayed=True,
                )
            finding = self._operational_finding_row(
                conn,
                str(request.finding_id),
            )
            self._require_finding_lineage(
                conn,
                request_id=request.request_id,
                attempt_id=request.attempt_id,
                outcome_id=request.outcome_id,
            )
            lineage_error = self._finding_lineage_error(
                conn,
                scope_kind=FindingScopeKind(str(finding["scope_kind"])),
                scope_id=str(finding["scope_id"]),
                request_id=request.request_id,
                attempt_id=request.attempt_id,
                outcome_id=request.outcome_id,
                observed_at=request.observed_at,
            )
            if lineage_error is not None:
                raise CheckStateError(lineage_error)
            self._check_identifier_absent(
                conn,
                table="operational_finding_occurrences",
                column="occurrence_id",
                identifier=str(request.occurrence_id),
                identity="Finding occurrence identity",
            )
            self._check_semantic_absent(
                conn,
                table="operational_finding_occurrences",
                semantic_digest=request.semantic_digest,
                identity="Finding occurrence semantics",
            )
            recorded_at = self._clock().to_text()
            committed = self._commit_grant_in_transaction(
                conn,
                grant,
                recorded_at=recorded_at,
            )
            if committed.replayed:
                return self._finding_occurrence_for_event(
                    conn,
                    committed.event_id,
                    replayed=True,
                )
            conn.execute(
                "INSERT INTO operational_finding_occurrences("
                "occurrence_id,finding_id,request_id,attempt_id,outcome_id,"
                "code,detail_digest,observed_at,semantic_digest,"
                "authority_event_id,authority_aggregate_version,"
                "canonical_bytes,canonical_digest,recorded_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(request.occurrence_id),
                    str(request.finding_id),
                    None if request.request_id is None else str(request.request_id),
                    None if request.attempt_id is None else str(request.attempt_id),
                    None if request.outcome_id is None else str(request.outcome_id),
                    request.code,
                    request.detail_digest,
                    request.observed_at.to_text(),
                    request.semantic_digest,
                    committed.event_id,
                    committed.aggregate_version,
                    request.canonical_bytes,
                    request.digest,
                    recorded_at,
                ),
            )
            return self._finding_occurrence_for_event(
                conn,
                committed.event_id,
                replayed=False,
            )


__all__ = ["_CheckStoreCommitFindingMixin"]
