from __future__ import annotations

from typing import Any, Callable

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.authority.types import TimePrecision
from newsroom.sources import (
    CheckOutcomeId,
    CoverageContribution,
    CoverageResponsibility,
    SourceItemId,
    SourceRevisionId,
    SourceTime,
    VersionedPolicyRef,
)

from ._payload_common import error, exact
from .baseline_models import (
    AbsenceEndingGuard,
    AgendaMissGuard,
    BaselineManifestEntry,
    ConfirmationOutcomeRef,
)
from .check_models import CandidateObservationRef
from .types import (
    BaselineEntryDisposition,
    CheckRequestId,
    CoverageBasis,
    TriggerKind,
    TriggerRef,
)


_IDEMPOTENCY = "payload-schema-validation"


def _policy(value: Any, *, field: str) -> VersionedPolicyRef:
    item = exact(
        value,
        fields=frozenset({"policy_id", "policy_version"}),
        name=field,
    )
    try:
        return VersionedPolicyRef(
            policy_id=item["policy_id"],
            policy_version=item["policy_version"],
        )
    except (TypeError, ValueError) as exc:
        raise error(f"{field} is invalid") from exc


def _trigger(value: Any) -> TriggerRef:
    item = exact(
        value,
        fields=frozenset(
            {
                "kind",
                "trigger_id",
                "trigger_version",
                "expected_window_digest",
            }
        ),
        name="check trigger",
    )
    try:
        return TriggerRef(
            kind=TriggerKind(item["kind"]),
            trigger_id=item["trigger_id"],
            trigger_version=item["trigger_version"],
            expected_window_digest=item["expected_window_digest"],
        )
    except (TypeError, ValueError) as exc:
        raise error("check trigger is invalid") from exc


def _coverage(value: Any) -> CoverageBasis:
    item = exact(
        value,
        fields=frozenset(
            {
                "obligation_id",
                "responsibility",
                "contribution",
                "coverage_policy",
            }
        ),
        name="check coverage basis",
    )
    try:
        return CoverageBasis(
            obligation_id=item["obligation_id"],
            responsibility=CoverageResponsibility(item["responsibility"]),
            contribution=CoverageContribution(item["contribution"]),
            coverage_policy=_policy(
                item["coverage_policy"],
                field="coverage_policy",
            ),
        )
    except (TypeError, ValueError) as exc:
        raise error("check coverage basis is invalid") from exc


def _candidate(value: Any) -> CandidateObservationRef:
    item = exact(
        value,
        fields=frozenset({"item_key", "item_digest"}),
        name="candidate observation",
    )
    try:
        return CandidateObservationRef(
            item_key=item["item_key"],
            item_digest=item["item_digest"],
        )
    except (TypeError, ValueError) as exc:
        raise error("candidate observation is invalid") from exc


def _manifest_entry(value: Any) -> BaselineManifestEntry:
    item = exact(
        value,
        fields=frozenset(
            {
                "item_key",
                "disposition",
                "reason_code",
                "item_id",
                "revision_id",
            }
        ),
        name="baseline manifest entry",
    )
    try:
        return BaselineManifestEntry(
            item_key=item["item_key"],
            disposition=BaselineEntryDisposition(item["disposition"]),
            reason_code=item["reason_code"],
            item_id=(
                None
                if item["item_id"] is None
                else SourceItemId.parse(item["item_id"])
            ),
            revision_id=(
                None
                if item["revision_id"] is None
                else SourceRevisionId.parse(item["revision_id"])
            ),
        )
    except (TypeError, ValueError) as exc:
        raise error("baseline manifest entry is invalid") from exc



def _confirmation_outcome(value: Any) -> ConfirmationOutcomeRef:
    item = exact(
        value,
        fields=frozenset(
            {
                "outcome_id",
                "request_id",
                "adapter_request_digest",
            }
        ),
        name="confirmation Outcome",
    )
    try:
        return ConfirmationOutcomeRef(
            outcome_id=CheckOutcomeId.parse(item["outcome_id"]),
            request_id=CheckRequestId.parse(item["request_id"]),
            adapter_request_digest=item["adapter_request_digest"],
        )
    except (TypeError, ValueError) as exc:
        raise error("confirmation Outcome is invalid") from exc

def _absence_guard(value: Any) -> AbsenceEndingGuard:
    item = exact(
        value,
        fields=frozenset(
            {
                "complete_scope_digest",
                "filter_contract_digest",
                "pagination_contract_digest",
                "successful_complete_outcome",
                "identity_confirmed",
                "scope_confirmed",
                "pagination_complete",
                "confirmation_outcomes",
                "confirmation_count",
                "required_confirmations",
                "grace_satisfied",
                "no_alternative_explanation",
                "authorizes_ending",
            }
        ),
        name="absence ending guard",
    )
    try:
        guard = AbsenceEndingGuard(
            complete_scope_digest=item["complete_scope_digest"],
            filter_contract_digest=item["filter_contract_digest"],
            pagination_contract_digest=item["pagination_contract_digest"],
            successful_complete_outcome=item[
                "successful_complete_outcome"
            ],
            identity_confirmed=item["identity_confirmed"],
            scope_confirmed=item["scope_confirmed"],
            pagination_complete=item["pagination_complete"],
            confirmation_outcomes=tuple(
                _confirmation_outcome(entry)
                for entry in item["confirmation_outcomes"]
            ),
            required_confirmations=item["required_confirmations"],
            grace_satisfied=item["grace_satisfied"],
            no_alternative_explanation=item[
                "no_alternative_explanation"
            ],
        )
    except (TypeError, ValueError) as exc:
        raise error("absence ending guard is invalid") from exc
    if guard.canonical_value() != item:
        raise error("absence ending guard derived value differs")
    return guard


def _agenda_guard(value: Any) -> AgendaMissGuard:
    item = exact(
        value,
        fields=frozenset(
            {
                "expected_window_digest",
                "confirmation_paths_digest",
                "window_closed",
                "grace_satisfied",
                "confirmation_paths_checked",
                "no_reschedule_or_cancellation",
                "confirmation_outcomes",
                "confirmation_count",
                "required_confirmations",
                "confirmation_outcomes_complete",
                "source_failure_absent",
                "authorizes_miss",
            }
        ),
        name="Agenda miss guard",
    )
    try:
        guard = AgendaMissGuard(
            expected_window_digest=item["expected_window_digest"],
            confirmation_paths_digest=item[
                "confirmation_paths_digest"
            ],
            window_closed=item["window_closed"],
            grace_satisfied=item["grace_satisfied"],
            confirmation_paths_checked=item[
                "confirmation_paths_checked"
            ],
            no_reschedule_or_cancellation=item[
                "no_reschedule_or_cancellation"
            ],
            confirmation_outcomes=tuple(
                _confirmation_outcome(entry)
                for entry in item["confirmation_outcomes"]
            ),
            required_confirmations=item["required_confirmations"],
            confirmation_outcomes_complete=item[
                "confirmation_outcomes_complete"
            ],
            source_failure_absent=item["source_failure_absent"],
        )
    except (TypeError, ValueError) as exc:
        raise error("Agenda miss guard is invalid") from exc
    if guard.canonical_value() != item:
        raise error("Agenda miss guard derived value differs")
    return guard


def _source_time(value: Any) -> SourceTime:
    item = exact(
        value,
        fields=frozenset({"precision", "value", "conflicting_values"}),
        name="source time",
    )
    try:
        selected = SourceTime(
            precision=TimePrecision(item["precision"]),
            value=item["value"],
            conflicting_values=tuple(item["conflicting_values"]),
        )
    except (TypeError, ValueError) as exc:
        raise error("source time is invalid") from exc
    if selected.canonical_value() != item:
        raise error("source time canonical value differs")
    return selected


def _canonicalize(
    value: Any,
    *,
    fields: frozenset[str],
    name: str,
    build: Callable[[dict[str, Any]], object],
) -> bytes:
    item = exact(value, fields=fields, name=name)
    try:
        request = build(item)
        canonical = request.canonical_value()  # type: ignore[attr-defined]
    except (TypeError, ValueError) as exc:
        raise error(f"{name} is invalid") from exc
    if canonical != item:
        raise error(f"{name} canonical value differs from retained payload")
    return canonical_json_bytes(item)


__all__ = [
    "_IDEMPOTENCY",
    "_absence_guard",
    "_agenda_guard",
    "_candidate",
    "_confirmation_outcome",
    "_canonicalize",
    "_coverage",
    "_manifest_entry",
    "_policy",
    "_source_time",
    "_trigger",
]
