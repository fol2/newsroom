"""Fixture-only health, observability, incident and security evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes, validate_sha256_digest
from newsroom.increment8.readiness import INCREMENT_8_READINESS, INCREMENT_8_READINESS_DIGEST


class ObservabilityError(ValueError):
    """Operational evidence violates the frozen Profile or accepted contract."""


class HealthDimension(StrEnum):
    AUTHORITY = "AUTHORITY"
    SCHEDULE = "SCHEDULE"
    TRANSPORT = "TRANSPORT"
    PARSER = "PARSER"
    FRESHNESS = "FRESHNESS"
    SEMANTIC_INTEGRITY = "SEMANTIC_INTEGRITY"
    DOWNSTREAM = "DOWNSTREAM"
    BUDGET = "BUDGET"


class DimensionState(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


class ObservationOutcome(StrEnum):
    COMPLETE_CHANGED = "COMPLETE_CHANGED"
    COMPLETE_UNCHANGED = "COMPLETE_UNCHANGED"
    MISSING = "MISSING"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    MALFORMED = "MALFORMED"
    BLOCKED = "BLOCKED"


class HealthVerdict(StrEnum):
    HEALTHY_CHANGED = "HEALTHY_CHANGED"
    HEALTHY_UNCHANGED = "HEALTHY_UNCHANGED"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"
    STALE = "STALE"


class PathRole(StrEnum):
    ANCHOR = "ANCHOR"
    COMPLEMENT = "COMPLEMENT"
    COMPARATOR = "COMPARATOR"
    SEARCH = "SEARCH"


class CoverageVerdict(StrEnum):
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    COVERAGE_BLOCKED = "COVERAGE_BLOCKED"


class AlertPriority(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class IncidentState(StrEnum):
    OPEN = "OPEN"
    CONTAINED = "CONTAINED"
    RECOVERED = "RECOVERED"
    CLOSED = "CLOSED"


class ManualAction(StrEnum):
    RETRY = "RETRY"
    REQUEUE = "REQUEUE"
    QUARANTINE_RELEASE = "QUARANTINE_RELEASE"
    CONTINGENCY = "CONTINGENCY"
    OVERRIDE = "OVERRIDE"


_EXPECTED_DIMENSIONS = tuple(d.value for d in HealthDimension)
_EXPECTED_METRICS = (
    "budget",
    "complete_success_age",
    "coverage",
    "outcome",
    "parser",
    "queue",
    "reconciliation",
    "retry",
    "schedule",
    "storage",
)
_EXPECTED_PATH_STAGES = (
    "candidate",
    "check",
    "due_trigger",
    "handoff",
    "lead",
    "transition",
    "work_item",
)


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ObservabilityError(f"{field} must be an integer >= {minimum}")
    return value


def _token(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or len(value.encode()) > 256:
        raise ObservabilityError(f"{field} must be bounded text")
    allowed = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-/")
    if any(character not in allowed for character in value):
        raise ObservabilityError(f"{field} contains unsupported characters")
    return value


def _digest(value: object, field: str) -> str:
    try:
        return validate_sha256_digest(value, field=field)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ObservabilityError(f"{field} must be a canonical digest") from exc


def _time(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ObservabilityError(f"{field} must be canonical UTC text")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ObservabilityError(f"{field} must be canonical UTC text") from exc
    if parsed.utcoffset() != timedelta(0):
        raise ObservabilityError(f"{field} must be UTC")
    return value


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")


def _record(schema: str, payload: Mapping[str, object]) -> tuple[bytes, str]:
    raw = canonical_json_bytes({"schema_version": schema, "payload": dict(payload)})
    return raw, digest_bytes(raw)


def _sorted_tokens(values: Sequence[str], field: str, *, empty: bool = False) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ObservabilityError(f"{field} must be a sequence")
    result = tuple(_token(item, field) for item in values)
    if (not empty and not result) or result != tuple(sorted(set(result))):
        raise ObservabilityError(f"{field} must be sorted and unique")
    return result


@dataclass(frozen=True, slots=True)
class HealthPosture:
    scope_id: str
    dimension_states: Mapping[str, str]
    observation_outcome: ObservationOutcome
    last_complete_success_at: str | None
    last_source_change_at: str | None
    observed_at: str
    complete_success_age_seconds: int | None
    verdict: HealthVerdict
    canonical_bytes: bytes
    digest: str

    @classmethod
    def build(
        cls,
        *,
        scope_id: str,
        dimension_states: Mapping[str, DimensionState],
        observation_outcome: ObservationOutcome,
        last_complete_success_at: str | None,
        last_source_change_at: str | None,
        observed_at: str,
    ) -> HealthPosture:
        if tuple(sorted(dimension_states)) != tuple(sorted(_EXPECTED_DIMENSIONS)):
            raise ObservabilityError("health dimension inventory differs")
        if not isinstance(observation_outcome, ObservationOutcome) or any(
            not isinstance(value, DimensionState) for value in dimension_states.values()
        ):
            raise ObservabilityError("health evidence must use typed values")
        observed = _time(observed_at, "observed_at")
        success = None if last_complete_success_at is None else _time(last_complete_success_at, "last_complete_success_at")
        changed = None if last_source_change_at is None else _time(last_source_change_at, "last_source_change_at")
        if success is not None and _dt(success) > _dt(observed):
            raise ObservabilityError("complete success is in the future")
        if changed is not None and _dt(changed) > _dt(observed):
            raise ObservabilityError("source change is in the future")
        age = None if success is None else int((_dt(observed) - _dt(success)).total_seconds())
        freshness = int(INCREMENT_8_READINESS.operational_profile["schedule"]["freshness_objective_seconds"])  # type: ignore[index]
        states = {name: dimension_states[name].value for name in sorted(dimension_states)}
        if DimensionState.BLOCKED.value in states.values():
            verdict = HealthVerdict.BLOCKED
        elif success is None or age is None or age > freshness:
            verdict = HealthVerdict.STALE
        elif observation_outcome not in {ObservationOutcome.COMPLETE_CHANGED, ObservationOutcome.COMPLETE_UNCHANGED}:
            verdict = HealthVerdict.DEGRADED
        elif any(value is not DimensionState.HEALTHY for value in dimension_states.values()):
            verdict = HealthVerdict.DEGRADED
        elif observation_outcome is ObservationOutcome.COMPLETE_UNCHANGED:
            verdict = HealthVerdict.HEALTHY_UNCHANGED
        else:
            verdict = HealthVerdict.HEALTHY_CHANGED
        payload = {
            "scope_id": _token(scope_id, "scope_id"),
            "dimension_states": states,
            "observation_outcome": observation_outcome.value,
            "last_complete_success_at": success,
            "last_source_change_at": changed,
            "observed_at": observed,
            "complete_success_age_seconds": age,
            "freshness_objective_seconds": freshness,
            "verdict": verdict.value,
            "freshness_uses_last_success": True,
        }
        raw, record_digest = _record("newsroom.increment8.health-posture.v1", payload)
        return cls(str(payload["scope_id"]), MappingProxyType(states), observation_outcome, success, changed, observed, age, verdict, raw, record_digest)


@dataclass(frozen=True, slots=True)
class CoveragePath:
    path_id: str
    role: PathRole
    health_digest: str
    healthy: bool
    authority_current: bool

    @classmethod
    def build(cls, *, path_id: str, role: PathRole, health: HealthPosture, authority_current: bool) -> CoveragePath:
        if not isinstance(role, PathRole) or not isinstance(health, HealthPosture) or not isinstance(authority_current, bool):
            raise ObservabilityError("coverage path evidence differs")
        healthy = health.verdict in {HealthVerdict.HEALTHY_CHANGED, HealthVerdict.HEALTHY_UNCHANGED}
        return cls(_token(path_id, "path_id"), role, health.digest, healthy, authority_current)


@dataclass(frozen=True, slots=True)
class CoveragePosture:
    obligation_id: str
    verdict: CoverageVerdict
    containment_invoked: bool
    canonical_bytes: bytes
    digest: str

    @classmethod
    def build(
        cls,
        *,
        obligation_id: str,
        active: bool,
        paths: Sequence[CoveragePath],
        containment_policy_digest: str,
    ) -> CoveragePosture:
        if not isinstance(active, bool) or not paths or any(not isinstance(path, CoveragePath) for path in paths):
            raise ObservabilityError("coverage obligation evidence differs")
        if len({path.path_id for path in paths}) != len(paths):
            raise ObservabilityError("coverage paths must be unique")
        anchors = [path for path in paths if path.role is PathRole.ANCHOR]
        if not anchors:
            raise ObservabilityError("coverage obligation requires an Anchor")
        healthy_anchor = any(path.healthy and path.authority_current for path in anchors)
        healthy_other = any(path.healthy and path.authority_current for path in paths if path.role is PathRole.COMPLEMENT)
        if active and not healthy_anchor:
            verdict = CoverageVerdict.COVERAGE_BLOCKED
            containment = True
        elif healthy_anchor and healthy_other:
            verdict = CoverageVerdict.AVAILABLE
            containment = False
        else:
            verdict = CoverageVerdict.DEGRADED
            containment = False
        payload = {
            "obligation_id": _token(obligation_id, "obligation_id"),
            "active": active,
            "paths": [
                {"path_id": path.path_id, "role": path.role.value, "health_digest": path.health_digest, "healthy": path.healthy, "authority_current": path.authority_current}
                for path in sorted(paths, key=lambda item: item.path_id)
            ],
            "containment_policy_digest": _digest(containment_policy_digest, "containment_policy_digest"),
            "verdict": verdict.value,
            "containment_invoked": containment,
            "comparator_substitution_allowed": False,
        }
        raw, record_digest = _record("newsroom.increment8.coverage-posture.v1", payload)
        return cls(str(payload["obligation_id"]), verdict, containment, raw, record_digest)


@dataclass(frozen=True, slots=True)
class AccessContract:
    contract_id: str
    approved_hosts: tuple[str, ...]
    maximum_redirects: int
    request_timeout_seconds: int
    maximum_body_bytes: int
    content_types: tuple[str, ...]
    canonical_bytes: bytes
    digest: str

    @classmethod
    def build(
        cls,
        *,
        contract_id: str,
        approved_hosts: Sequence[str],
        maximum_redirects: int,
        request_timeout_seconds: int,
        maximum_body_bytes: int,
        content_types: Sequence[str],
    ) -> AccessContract:
        hosts = _sorted_tokens(approved_hosts, "approved_hosts")
        types = _sorted_tokens(content_types, "content_types")
        redirects = _integer(maximum_redirects, "maximum_redirects")
        timeout = _integer(request_timeout_seconds, "request_timeout_seconds", minimum=1)
        body = _integer(maximum_body_bytes, "maximum_body_bytes", minimum=1)
        frozen_timeout = int(INCREMENT_8_READINESS.operational_profile["execution"]["request_timeout_seconds"])  # type: ignore[index]
        if redirects > 5 or timeout > frozen_timeout or body > 10_000_000:
            raise ObservabilityError("access contract exceeds fixture bounds")
        payload = {
            "contract_id": _token(contract_id, "contract_id"),
            "schemes": ["https"],
            "approved_hosts": list(hosts),
            "maximum_redirects": redirects,
            "tls_verification_required": True,
            "credential_references": 0,
            "request_timeout_seconds": timeout,
            "maximum_body_bytes": body,
            "content_types": list(types),
            "egress_destinations": 0,
            "external_entity_resolution": False,
            "unsafe_deserialisation": False,
            "maximum_decompression_ratio": 20,
            "untrusted_input_can_change_policy": False,
            "untrusted_input_can_change_tools": False,
            "untrusted_input_can_change_egress": False,
            "untrusted_input_can_change_budget": False,
            "untrusted_input_can_change_authority": False,
        }
        raw, record_digest = _record("newsroom.increment8.access-contract.v1", payload)
        return cls(str(payload["contract_id"]), hosts, redirects, timeout, body, types, raw, record_digest)


@dataclass(frozen=True, slots=True)
class EventInputContract:
    channel_id: str
    canonical_bytes: bytes
    digest: str

    @classmethod
    def build(
        cls,
        *,
        channel_id: str,
        authentication_key_digest: str,
        provenance_policy_digest: str,
        replay_window_seconds: int,
        maximum_payload_bytes: int,
    ) -> EventInputContract:
        replay = _integer(replay_window_seconds, "replay_window_seconds", minimum=1)
        payload_bytes = _integer(maximum_payload_bytes, "maximum_payload_bytes", minimum=1)
        if replay > 900 or payload_bytes > 1_000_000:
            raise ObservabilityError("event input exceeds fixture bounds")
        payload = {
            "channel_id": _token(channel_id, "channel_id"),
            "authentication_key_digest": _digest(authentication_key_digest, "authentication_key_digest"),
            "provenance_policy_digest": _digest(provenance_policy_digest, "provenance_policy_digest"),
            "replay_window_seconds": replay,
            "maximum_payload_bytes": payload_bytes,
            "durable_receipt_required": True,
            "untrusted_payload_policy_authority": False,
            "live_delivery_authorised": False,
        }
        raw, record_digest = _record("newsroom.increment8.event-input-contract.v1", payload)
        return cls(str(payload["channel_id"]), raw, record_digest)


def classify_transport_outcome(
    *,
    status_code: int,
    body_bytes: int,
    valid_baseline: bool,
    validator_contract: bool,
    shape_valid: bool,
) -> str:
    code = _integer(status_code, "status_code", minimum=100)
    body = _integer(body_bytes, "body_bytes")
    if not all(isinstance(value, bool) for value in (valid_baseline, validator_contract, shape_valid)):
        raise ObservabilityError("transport flags must be boolean")
    if code == 304:
        return "COMPLETE_UNCHANGED" if valid_baseline and validator_contract else "INVALID_NOT_MODIFIED"
    if 200 <= code < 300:
        if body == 0:
            return "EMPTY_SUCCESS"
        return "COMPLETE_CHANGED" if shape_valid else "SHAPE_DRIFT_QUARANTINE"
    if code == 404:
        return "SOURCE_NOT_FOUND"
    if code == 410:
        return "SOURCE_GONE_REVIEW"
    if code == 429:
        return "RATE_LIMITED"
    if 300 <= code < 400:
        return "REDIRECT_REVIEW"
    return "TRANSPORT_FAILURE"


@dataclass(frozen=True, slots=True)
class ObservabilityRecord:
    priority: AlertPriority
    canonical_bytes: bytes
    digest: str

    @classmethod
    def build(
        cls,
        *,
        source_version_digest: str,
        component_version_digest: str,
        profile_digest: str,
        provider_version_digest: str,
        policy_version_digest: str,
        metrics: Mapping[str, int],
        path_correlation: Mapping[str, str],
        coverage_blocked: bool,
        integrity_uncertain: bool,
        urgent: bool,
        owner_digest: str,
        escalation_digest: str,
        runbook_version_digest: str,
    ) -> ObservabilityRecord:
        if tuple(sorted(metrics)) != _EXPECTED_METRICS:
            raise ObservabilityError("health metric inventory differs")
        if tuple(sorted(path_correlation)) != _EXPECTED_PATH_STAGES:
            raise ObservabilityError("correlation path inventory differs")
        if not all(isinstance(value, bool) for value in (coverage_blocked, integrity_uncertain, urgent)):
            raise ObservabilityError("alert consequence flags must be boolean")
        checked_metrics = {name: _integer(metrics[name], name) for name in _EXPECTED_METRICS}
        correlation = {name: _digest(path_correlation[name], name) for name in _EXPECTED_PATH_STAGES}
        if integrity_uncertain or (coverage_blocked and urgent):
            priority = AlertPriority.P1
        elif coverage_blocked:
            priority = AlertPriority.P2
        elif urgent:
            priority = AlertPriority.P3
        else:
            priority = AlertPriority.P4
        payload = {
            "readiness_digest": INCREMENT_8_READINESS_DIGEST,
            "source_version_digest": _digest(source_version_digest, "source_version_digest"),
            "component_version_digest": _digest(component_version_digest, "component_version_digest"),
            "profile_digest": _digest(profile_digest, "profile_digest"),
            "provider_version_digest": _digest(provider_version_digest, "provider_version_digest"),
            "policy_version_digest": _digest(policy_version_digest, "policy_version_digest"),
            "metrics": checked_metrics,
            "path_correlation": correlation,
            "prohibited_data_logged": False,
            "coverage_blocked": coverage_blocked,
            "integrity_uncertain": integrity_uncertain,
            "urgent": urgent,
            "alert_priority": priority.value,
            "owner_digest": _digest(owner_digest, "owner_digest"),
            "escalation_digest": _digest(escalation_digest, "escalation_digest"),
            "runbook_version_digest": _digest(runbook_version_digest, "runbook_version_digest"),
        }
        raw, record_digest = _record("newsroom.increment8.observability-record.v1", payload)
        return cls(priority, raw, record_digest)


@dataclass(frozen=True, slots=True)
class IncidentRecord:
    incident_id: str
    version: int
    state: IncidentState
    integrity_related: bool
    near_miss: bool
    root_cause_digest: str | None
    follow_up_digest: str | None
    regression_case_digest: str | None
    previous_digest: str | None
    canonical_bytes: bytes
    digest: str

    @classmethod
    def open(
        cls,
        *,
        incident_id: str,
        scope_digest: str,
        opened_at: str,
        timeline_digest: str,
        integrity_related: bool,
        near_miss: bool,
    ) -> IncidentRecord:
        if not isinstance(integrity_related, bool) or not isinstance(near_miss, bool):
            raise ObservabilityError("incident flags must be boolean")
        payload = {
            "incident_id": _token(incident_id, "incident_id"), "version": 1, "state": IncidentState.OPEN.value,
            "scope_digest": _digest(scope_digest, "scope_digest"), "timeline_digest": _digest(timeline_digest, "timeline_digest"),
            "opened_at": _time(opened_at, "opened_at"), "containment_digest": None, "recovery_digest": None,
            "root_cause_digest": None, "follow_up_digest": None, "regression_case_digest": None,
            "integrity_related": integrity_related, "near_miss": near_miss, "previous_digest": None,
        }
        raw, record_digest = _record("newsroom.increment8.incident-record.v1", payload)
        return cls(str(payload["incident_id"]), 1, IncidentState.OPEN, integrity_related, near_miss, None, None, None, None, raw, record_digest)

    def transition(
        self,
        *,
        state: IncidentState,
        evidence_digest: str,
        root_cause_digest: str | None = None,
        follow_up_digest: str | None = None,
        regression_case_digest: str | None = None,
    ) -> IncidentRecord:
        allowed = {IncidentState.OPEN: IncidentState.CONTAINED, IncidentState.CONTAINED: IncidentState.RECOVERED, IncidentState.RECOVERED: IncidentState.CLOSED}
        if not isinstance(state, IncidentState) or allowed.get(self.state) is not state:
            raise ObservabilityError("incident transition is not allowed")
        value = json.loads(self.canonical_bytes)["payload"]
        value["version"] = self.version + 1
        value["state"] = state.value
        value["previous_digest"] = self.digest
        if state is IncidentState.CONTAINED:
            value["containment_digest"] = _digest(evidence_digest, "evidence_digest")
        elif state is IncidentState.RECOVERED:
            value["recovery_digest"] = _digest(evidence_digest, "evidence_digest")
        else:
            value["root_cause_digest"] = _digest(root_cause_digest, "root_cause_digest")
            value["follow_up_digest"] = _digest(follow_up_digest, "follow_up_digest")
            if self.integrity_related or self.near_miss:
                value["regression_case_digest"] = _digest(regression_case_digest, "regression_case_digest")
            elif regression_case_digest is not None:
                value["regression_case_digest"] = _digest(regression_case_digest, "regression_case_digest")
        raw, record_digest = _record("newsroom.increment8.incident-record.v1", value)
        return IncidentRecord(self.incident_id, self.version + 1, state, self.integrity_related, self.near_miss, value["root_cause_digest"], value["follow_up_digest"], value["regression_case_digest"], self.digest, raw, record_digest)


@dataclass(frozen=True, slots=True)
class ManualActionReceipt:
    action: ManualAction
    canonical_bytes: bytes
    digest: str

    @classmethod
    def build(
        cls,
        *,
        action: ManualAction,
        scope_digest: str,
        actor_identity_digest: str,
        authorisation_digest: str,
        evidence_digest: str,
        acted_at: str,
    ) -> ManualActionReceipt:
        if not isinstance(action, ManualAction):
            raise ObservabilityError("manual action must be typed")
        payload = {
            "action": action.value, "scope_digest": _digest(scope_digest, "scope_digest"),
            "actor_identity_digest": _digest(actor_identity_digest, "actor_identity_digest"),
            "authorisation_digest": _digest(authorisation_digest, "authorisation_digest"),
            "evidence_digest": _digest(evidence_digest, "evidence_digest"), "acted_at": _time(acted_at, "acted_at"),
            "authenticated": True, "audited": True, "automatic": False,
        }
        raw, record_digest = _record("newsroom.increment8.manual-action-receipt.v1", payload)
        return cls(action, raw, record_digest)


@dataclass(frozen=True, slots=True)
class SecurityAdmission:
    eligible: bool
    blocking_reasons: tuple[str, ...]
    canonical_bytes: bytes
    digest: str

    @classmethod
    def build(
        cls,
        *,
        access_contract: AccessContract,
        exact_version_approved: bool,
        rights_current: bool,
        terms_current: bool,
        pricing_current: bool,
        credential_scope_current: bool,
        rollback_tested: bool,
        scoped_disable_tested: bool,
        graph_capability_admitted: bool,
        runbook_version_digest: str,
    ) -> SecurityAdmission:
        flags = {
            "exact_version_approved": exact_version_approved, "rights_current": rights_current,
            "terms_current": terms_current, "pricing_current": pricing_current,
            "credential_scope_current": credential_scope_current, "rollback_tested": rollback_tested,
            "scoped_disable_tested": scoped_disable_tested, "graph_capability_admitted": graph_capability_admitted,
        }
        if not isinstance(access_contract, AccessContract) or any(not isinstance(value, bool) for value in flags.values()):
            raise ObservabilityError("security admission evidence differs")
        reasons = tuple(sorted(name for name, value in flags.items() if not value))
        payload = {
            "access_contract_digest": access_contract.digest, **flags, "blocking_reasons": list(reasons),
            "runbook_version_digest": _digest(runbook_version_digest, "runbook_version_digest"),
            "canary_supported": True, "canary_authorised": False, "production_activation_authorised": False,
            "live_credentials": 0, "network_egress_destinations": 0, "external_spend_pence": 0,
            "eligible": not reasons,
        }
        raw, record_digest = _record("newsroom.increment8.security-admission.v1", payload)
        return cls(not reasons, reasons, raw, record_digest)


__all__ = [
    "AccessContract", "AlertPriority", "CoveragePath", "CoveragePosture", "CoverageVerdict",
    "DimensionState", "EventInputContract", "HealthDimension", "HealthPosture", "HealthVerdict", "IncidentRecord",
    "IncidentState", "ManualAction", "ManualActionReceipt", "ObservationOutcome", "ObservabilityError",
    "ObservabilityRecord", "PathRole", "SecurityAdmission", "classify_transport_outcome",
]
