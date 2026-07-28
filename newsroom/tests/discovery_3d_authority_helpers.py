from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable

from newsroom.authority.discovery_system import (
    open_governed_discovery_authority_system,
)
from newsroom.authority.types import UtcTimestamp
from newsroom.checks import ObservableTransitionKind
from newsroom.discovery import (
    DiscoveryReadPolicy,
    SignalLeadAdmissionRequest,
)
from newsroom.sources import (
    CoverageContribution,
    CoverageResponsibility,
    PortfolioFunction,
    SourceDependency,
    SourceDependencyKind,
    SourceRole,
    SourceRoleAssignment,
)

from .authority_event_helpers import payload_schemas, registry_v1
from .check_3c_authority_helpers import (
    CheckClock,
    OCCURRENCE_ID,
    authenticator,
    check_read_policy,
    definition_request,
    item_request,
    occurrence_request,
    proof,
    representation_request,
    revision_request,
    source_read_policy,
    version_request,
)
from .check_3c_helpers import (
    DEFINITION_ID,
    ITEM_ID,
    OUTCOME_ID,
    REPRESENTATION_ID,
    REVISION_ID,
    TRANSITION_ID,
    VERSION_ID,
    LATER as CHECK_LATER,
    baseline_decision,
    changed_outcome,
    check_attempt,
    check_request,
    first_transition,
)
from .discovery_3d_helpers import (
    DISPOSITION_ID,
    GATE_ID,
    LEAD_ID,
    SIGNAL_ID,
    disposition_request,
    gate_request,
    lead_request,
    signal_request,
)
from newsroom.authority import StaticAuthorizer


def scopes() -> frozenset[str]:
    from .check_3c_authority_helpers import scopes as check_scopes

    return check_scopes() | frozenset(
        {
            "authority.discovery.signals.admit",
            "authority.discovery.gates.decide",
            "authority.discovery.leads.open",
            "authority.discovery.watch.manage",
            "authority.discovery.leads.disposition",
            "authority.discovery.read",
            "authority.discovery.read_sensitive",
        }
    )


def authorizer(*, granted_scopes: frozenset[str] | None = None) -> StaticAuthorizer:
    return StaticAuthorizer(
        policy_version="discovery-signal-lead-authz-v1",
        grants_by_principal={
            "principal.alpha": scopes() if granted_scopes is None else granted_scopes
        },
    )


def discovery_read_policy() -> DiscoveryReadPolicy:
    return DiscoveryReadPolicy(
        policy_id="discovery-signal-lead-read-v1",
        purpose="discovery.signal-lead.audit",
        metadata_required_scope="authority.discovery.read",
        sensitive_required_scope="authority.discovery.read_sensitive",
        allowed_principal_ids=frozenset({"principal.alpha"}),
        max_results=100,
    )


def open_discovery_system(
    database: Path,
    *,
    clock: Callable[[], UtcTimestamp] | None = None,
    granted_scopes: frozenset[str] | None = None,
):
    return open_governed_discovery_authority_system(
        path=database,
        registry=registry_v1(),
        payload_schemas=payload_schemas(),
        authenticator=authenticator(),
        authorizer=authorizer(granted_scopes=granted_scopes),
        source_read_policy=source_read_policy(),
        check_read_policy=check_read_policy(),
        discovery_read_policy=discovery_read_policy(),
        clock=clock or CheckClock(),
    )


def seed_check_lineage(system) -> None:
    system.sources.register_definition(definition_request(), proof=proof())
    system.sources.record_definition_version(version_request(), proof=proof())
    system.checks.register_request(check_request(), proof=proof())
    system.checks.start_attempt(check_attempt(), proof=proof())
    system.checks.record_outcome(changed_outcome(), proof=proof())
    system.sources.register_item(item_request(), proof=proof())
    system.sources.record_revision(revision_request(), proof=proof())
    system.sources.record_representation(representation_request(), proof=proof())
    system.sources.record_occurrence(occurrence_request(), proof=proof())
    system.checks.decide_baseline(baseline_decision(), proof=proof())
    system.checks.record_transition(first_transition(), proof=proof())


def exact_signal_request():
    return replace(
        signal_request(),
        definition_id=DEFINITION_ID,
        definition_version_id=VERSION_ID,
        item_id=ITEM_ID,
        revision_id=REVISION_ID,
        representation_id=REPRESENTATION_ID,
        check_outcome_id=OUTCOME_ID,
        occurrence_id=OCCURRENCE_ID,
        transition_id=TRANSITION_ID,
        admitted_at=CHECK_LATER,
    )


def exact_gate_request():
    request = gate_request()
    return replace(
        request,
        signal_id=SIGNAL_ID,
        evaluated_definition_version_id=VERSION_ID,
        coverage=check_request().coverage,
        rights_decision_id=check_request().rights_decision_id,
        rights_policy_version=check_request().rights_policy_version,
        signal_admission_policy=exact_signal_request().admission_policy,
    )


def exact_lead_request():
    request = lead_request()
    source_version = version_request()
    return replace(
        request,
        signal_id=SIGNAL_ID,
        promoting_gate_decision_id=GATE_ID,
        definition_id=DEFINITION_ID,
        definition_version_id=VERSION_ID,
        item_id=ITEM_ID,
        revision_id=REVISION_ID,
        representation_id=REPRESENTATION_ID,
        occurrence_id=OCCURRENCE_ID,
        transition_id=TRANSITION_ID,
        transition_kind=ObservableTransitionKind.FIRST_OBSERVED,
        coverage=check_request().coverage,
        source_roles=source_version.roles,
        portfolio_functions=source_version.portfolio_functions,
        source_dependencies=source_version.dependencies,
    )


def exact_initial_disposition():
    return replace(
        disposition_request(),
        decision_id=DISPOSITION_ID,
        lead_id=LEAD_ID,
        urgency_route=exact_lead_request().urgency,
    )


def exact_admission_request() -> SignalLeadAdmissionRequest:
    return SignalLeadAdmissionRequest(
        signal=exact_signal_request(),
        gate=exact_gate_request(),
        lead=exact_lead_request(),
        initial_disposition=exact_initial_disposition(),
    )


__all__ = [
    "DISPOSITION_ID",
    "GATE_ID",
    "LEAD_ID",
    "SIGNAL_ID",
    "discovery_read_policy",
    "exact_admission_request",
    "exact_gate_request",
    "exact_initial_disposition",
    "exact_lead_request",
    "exact_signal_request",
    "open_discovery_system",
    "proof",
    "scopes",
    "seed_check_lineage",
]
