from __future__ import annotations

from collections.abc import Callable
from typing import Any

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.authority.policy import PayloadSchemaValidationError
from newsroom.authority.types import UtcTimestamp
from newsroom.checks import CoverageBasis, ObservableTransitionId, ObservableTransitionKind
from newsroom.sources import (
    CoverageContribution,
    CoverageResponsibility,
    PortfolioFunction,
    SourceDefinitionId,
    SourceDependency,
    SourceDependencyKind,
    SourceRole,
    SourceRoleAssignment,
    VersionedPolicyRef,
)

from .types import (
    DecisionTerminality,
    DiscoveryContractError,
    DiscoverySignalId,
    GateBasis,
    GateOutcome,
    LeadDispositionOutcome,
    NextAction,
    NextActionKind,
    ObservableNewness,
    ReasonBasisClass,
    ReasonReference,
    ScopeDisposition,
    StructuredReason,
    TimeValidity,
    UrgencyBasis,
    UrgencyRoute,
)

_IDEMPOTENCY = "payload-schema-validation"


def _error(message: str) -> PayloadSchemaValidationError:
    return PayloadSchemaValidationError(message)


def _exact(
    value: Any,
    *,
    fields: frozenset[str],
    name: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(fields):
        raise _error(f"{name} payload fields differ from retained schema")
    return value


def _canonicalize(
    value: Any,
    *,
    fields: frozenset[str],
    name: str,
    build: Callable[[dict[str, Any]], object],
) -> bytes:
    item = _exact(value, fields=fields, name=name)
    try:
        request = build(item)
        canonical = request.canonical_value()  # type: ignore[attr-defined]
    except (TypeError, ValueError) as exc:
        raise _error(f"{name} is invalid") from exc
    if canonical != item:
        raise _error(f"{name} canonical value differs from retained payload")
    return canonical_json_bytes(item)


def _policy(value: Any, *, field: str) -> VersionedPolicyRef:
    item = _exact(
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
        raise _error(f"{field} is invalid") from exc


def _coverage(value: Any) -> CoverageBasis:
    item = _exact(
        value,
        fields=frozenset(
            {
                "obligation_id",
                "responsibility",
                "contribution",
                "coverage_policy",
            }
        ),
        name="discovery coverage basis",
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
        raise _error("discovery coverage basis is invalid") from exc


def _reason_reference(value: Any) -> ReasonReference:
    item = _exact(
        value,
        fields=frozenset({"reference_type", "identifier", "digest"}),
        name="reason reference",
    )
    try:
        return ReasonReference(
            reference_type=item["reference_type"],
            identifier=item["identifier"],
            digest=item["digest"],
        )
    except (TypeError, ValueError) as exc:
        raise _error("reason reference is invalid") from exc


def _reason(value: Any) -> StructuredReason:
    item = _exact(
        value,
        fields=frozenset({"code", "basis", "references", "explanation"}),
        name="structured reason",
    )
    if not isinstance(item["references"], list):
        raise _error("structured reason references must be a list")
    try:
        return StructuredReason(
            code=item["code"],
            basis=ReasonBasisClass(item["basis"]),
            references=tuple(
                _reason_reference(reference) for reference in item["references"]
            ),
            explanation=item["explanation"],
        )
    except (TypeError, ValueError) as exc:
        raise _error("structured reason is invalid") from exc


def _timestamp(value: Any, *, field: str, optional: bool = False) -> UtcTimestamp | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise _error(f"{field} must be canonical UTC text")
    try:
        parsed = UtcTimestamp.parse(value)
    except (TypeError, ValueError) as exc:
        raise _error(f"{field} must be canonical UTC text") from exc
    if parsed.to_text() != value:
        raise _error(f"{field} must be canonical UTC text")
    return parsed


def _next_action(value: Any) -> NextAction:
    item = _exact(
        value,
        fields=frozenset(
            {
                "kind",
                "action_code",
                "owner",
                "dependency",
                "due_at",
                "expires_at",
                "instructions",
            }
        ),
        name="next action",
    )
    try:
        return NextAction(
            kind=NextActionKind(item["kind"]),
            action_code=item["action_code"],
            owner=item["owner"],
            dependency=item["dependency"],
            due_at=_timestamp(item["due_at"], field="next_action.due_at", optional=True),
            expires_at=_timestamp(
                item["expires_at"],
                field="next_action.expires_at",
                optional=True,
            ),
            instructions=item["instructions"],
        )
    except (TypeError, ValueError) as exc:
        raise _error("next action is invalid") from exc


def _gate_basis(value: Any) -> GateBasis:
    item = _exact(
        value,
        fields=frozenset(
            {
                "identity_integrity",
                "duplicate_signal_id",
                "duplicate_rule",
                "observable_newness",
                "time_validity",
                "scope_disposition",
                "clear_exclusion_rule",
                "rights_current",
                "policy_current",
                "operationally_executable",
                "ambiguities",
            }
        ),
        name="Gate basis",
    )
    if not isinstance(item["ambiguities"], list):
        raise _error("Gate ambiguities must be a list")
    try:
        return GateBasis(
            identity_integrity=item["identity_integrity"],
            duplicate_signal_id=(
                None
                if item["duplicate_signal_id"] is None
                else DiscoverySignalId.parse(item["duplicate_signal_id"])
            ),
            duplicate_rule=(
                None
                if item["duplicate_rule"] is None
                else _policy(item["duplicate_rule"], field="duplicate_rule")
            ),
            observable_newness=ObservableNewness(item["observable_newness"]),
            time_validity=TimeValidity(item["time_validity"]),
            scope_disposition=ScopeDisposition(item["scope_disposition"]),
            clear_exclusion_rule=(
                None
                if item["clear_exclusion_rule"] is None
                else _policy(
                    item["clear_exclusion_rule"],
                    field="clear_exclusion_rule",
                )
            ),
            rights_current=item["rights_current"],
            policy_current=item["policy_current"],
            operationally_executable=item["operationally_executable"],
            ambiguities=tuple(item["ambiguities"]),
        )
    except (TypeError, ValueError) as exc:
        raise _error("Gate basis is invalid") from exc


def _urgency(value: Any) -> UrgencyBasis:
    item = _exact(
        value,
        fields=frozenset(
            {
                "route",
                "primary_reason",
                "hard_deadline",
                "planned_window",
                "isolation_required",
                "unknown_factors",
            }
        ),
        name="urgency basis",
    )
    if not isinstance(item["unknown_factors"], list):
        raise _error("urgency unknown factors must be a list")
    try:
        return UrgencyBasis(
            route=UrgencyRoute(item["route"]),
            primary_reason=_reason(item["primary_reason"]),
            hard_deadline=_timestamp(
                item["hard_deadline"],
                field="urgency.hard_deadline",
                optional=True,
            ),
            planned_window=item["planned_window"],
            isolation_required=item["isolation_required"],
            unknown_factors=tuple(item["unknown_factors"]),
        )
    except (TypeError, ValueError) as exc:
        raise _error("urgency basis is invalid") from exc


def _role(value: Any) -> SourceRoleAssignment:
    item = _exact(
        value,
        fields=frozenset({"role", "purpose", "limitations"}),
        name="source role assignment",
    )
    if not isinstance(item["limitations"], list):
        raise _error("source role limitations must be a list")
    try:
        return SourceRoleAssignment(
            role=SourceRole(item["role"]),
            purpose=item["purpose"],
            limitations=tuple(item["limitations"]),
        )
    except (TypeError, ValueError) as exc:
        raise _error("source role assignment is invalid") from exc


def _dependency(value: Any) -> SourceDependency:
    item = _exact(
        value,
        fields=frozenset(
            {
                "dependency_id",
                "kind",
                "description",
                "upstream_source_definition_id",
            }
        ),
        name="source dependency",
    )
    try:
        return SourceDependency(
            dependency_id=item["dependency_id"],
            kind=SourceDependencyKind(item["kind"]),
            description=item["description"],
            upstream_source_definition_id=(
                None
                if item["upstream_source_definition_id"] is None
                else SourceDefinitionId.parse(item["upstream_source_definition_id"])
            ),
        )
    except (TypeError, ValueError) as exc:
        raise _error("source dependency is invalid") from exc


def _transition_kinds(value: Any) -> tuple[ObservableTransitionKind, ...]:
    if not isinstance(value, list):
        raise _error("Watch transition kinds must be a list")
    try:
        return tuple(ObservableTransitionKind(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise _error("Watch transition kinds are invalid") from exc


__all__ = [
    "_IDEMPOTENCY",
    "_canonicalize",
    "_coverage",
    "_dependency",
    "_gate_basis",
    "_next_action",
    "_policy",
    "_reason",
    "_role",
    "_timestamp",
    "_transition_kinds",
    "_urgency",
]
