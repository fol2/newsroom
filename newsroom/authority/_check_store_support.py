from __future__ import annotations

import sqlite3

from newsroom.authority._capability import _AuthorizedCommandGrant
from newsroom.authority.canonical import digest_bytes
from newsroom.authority.persistence import AuthorityPersistenceError
from newsroom.authority.types import PayloadMode, TrustScope
from newsroom.checks.policy import (
    CHECK_ATTEMPT_START_COMMAND,
    CHECK_BASELINE_DECIDE_COMMAND,
    CHECK_OUTCOME_RECORD_COMMAND,
    CHECK_REQUEST_REGISTER_COMMAND,
    OBSERVABLE_TRANSITION_RECORD_COMMAND,
    OPERATIONAL_FINDING_OCCURRENCE_RECORD_COMMAND,
    OPERATIONAL_FINDING_OPEN_COMMAND,
)


_CHECK_RECORD_SPECS: dict[str, tuple[str, str, TrustScope]] = {
    CHECK_REQUEST_REGISTER_COMMAND: (
        "check_request",
        "check.request.registered",
        TrustScope.ADMITTED,
    ),
    CHECK_ATTEMPT_START_COMMAND: (
        "check_attempt",
        "check.attempt.started",
        TrustScope.OBSERVED,
    ),
    CHECK_OUTCOME_RECORD_COMMAND: (
        "check_outcome",
        "check.outcome.recorded",
        TrustScope.OBSERVED,
    ),
    CHECK_BASELINE_DECIDE_COMMAND: (
        "baseline_decision",
        "check.baseline.decided",
        TrustScope.ADMITTED,
    ),
    OBSERVABLE_TRANSITION_RECORD_COMMAND: (
        "observable_transition",
        "source.observable_transition.recorded",
        TrustScope.ADMITTED,
    ),
    OPERATIONAL_FINDING_OPEN_COMMAND: (
        "operational_finding",
        "operational.finding.opened",
        TrustScope.ADMITTED,
    ),
    OPERATIONAL_FINDING_OCCURRENCE_RECORD_COMMAND: (
        "operational_finding_occurrence",
        "operational.finding.occurrence.recorded",
        TrustScope.OBSERVED,
    ),
}


class _CheckStoreSupport:
    def _require_check_grant(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        command_type: str,
        aggregate_id: str,
        canonical_bytes: bytes,
    ) -> None:
        self._issuer.verify(grant)
        spec = _CHECK_RECORD_SPECS.get(command_type)
        if spec is None:
            raise AuthorityPersistenceError("unknown discovery Check command")
        aggregate_type, event_type, trust_scope = spec
        definition = grant.definition
        if (
            grant.command_type != command_type
            or grant.aggregate_id != aggregate_id
            or grant.expected_aggregate_version != 0
            or definition.command_type != command_type
            or definition.aggregate_type != aggregate_type
            or definition.event_type != event_type
            or definition.trust_scope is not trust_scope
            or definition.security_scope != "authority.discovery_checks"
            or definition.retention_scope != "authority.audit"
            or definition.payload_mode is not PayloadMode.INLINE
            or grant.payload.kind != PayloadMode.INLINE.value
            or grant.payload.inline_bytes != canonical_bytes
            or grant.payload.digest != digest_bytes(canonical_bytes)
        ):
            raise AuthorityPersistenceError(
                "discovery Check grant differs from the typed record"
            )

    @classmethod
    def _check_request_row(
        cls, conn: sqlite3.Connection, request_id: str
    ) -> sqlite3.Row:
        return cls._required_row_by_id(
            conn,
            table="check_requests",
            column="request_id",
            identifier=request_id,
            identity="Check Request",
        )

    @classmethod
    def _check_attempt_row(
        cls, conn: sqlite3.Connection, attempt_id: str
    ) -> sqlite3.Row:
        return cls._required_row_by_id(
            conn,
            table="check_attempts",
            column="attempt_id",
            identifier=attempt_id,
            identity="Check Attempt",
        )

    @classmethod
    def _check_outcome_row(
        cls, conn: sqlite3.Connection, outcome_id: str
    ) -> sqlite3.Row:
        return cls._required_row_by_id(
            conn,
            table="check_outcomes",
            column="outcome_id",
            identifier=outcome_id,
            identity="Check Outcome",
        )

    @classmethod
    def _baseline_decision_row(
        cls, conn: sqlite3.Connection, decision_id: str
    ) -> sqlite3.Row:
        return cls._required_row_by_id(
            conn,
            table="baseline_decisions",
            column="decision_id",
            identifier=decision_id,
            identity="Baseline Decision",
        )

    @classmethod
    def _observable_transition_row(
        cls, conn: sqlite3.Connection, transition_id: str
    ) -> sqlite3.Row:
        return cls._required_row_by_id(
            conn,
            table="observable_transitions",
            column="transition_id",
            identifier=transition_id,
            identity="Observable Transition",
        )

    @classmethod
    def _operational_finding_row(
        cls, conn: sqlite3.Connection, finding_id: str
    ) -> sqlite3.Row:
        return cls._required_row_by_id(
            conn,
            table="operational_findings",
            column="finding_id",
            identifier=finding_id,
            identity="Operational Finding",
        )

    @classmethod
    def _finding_occurrence_row(
        cls, conn: sqlite3.Connection, occurrence_id: str
    ) -> sqlite3.Row:
        return cls._required_row_by_id(
            conn,
            table="operational_finding_occurrences",
            column="occurrence_id",
            identifier=occurrence_id,
            identity="Operational Finding occurrence",
        )


__all__ = ["_CHECK_RECORD_SPECS", "_CheckStoreSupport"]
