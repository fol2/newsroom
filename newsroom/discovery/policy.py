from __future__ import annotations

from collections.abc import Callable
from typing import Any

from newsroom.authority.models import CommandDefinition
from newsroom.authority.policy import (
    CommandRegistry,
    PayloadGoldenVector,
    PayloadSchemaContract,
    PayloadSchemaRegistry,
)
from newsroom.authority.types import PayloadMode, TrustScope, UtcTimestamp
from newsroom.checks import (
    CheckOutcomeId,
    CoverageBasis,
    ObservableTransitionId,
    ObservableTransitionKind,
)
from newsroom.projection.models import ProjectionContractError
from newsroom.sources import (
    CoverageContribution,
    CoverageResponsibility,
    DiscoveryOccurrenceId,
    DiscoveryRepresentationId,
    PortfolioFunction,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceDependency,
    SourceDependencyKind,
    SourceItemId,
    SourceRevisionId,
    SourceRole,
    SourceRoleAssignment,
    VersionedPolicyRef,
)

from .models import (
    DiscoverySignalRequest,
    GateDecisionRequest,
    LeadDispositionDecisionRequest,
    NewsLeadRequest,
    WatchConditionRequest,
)
from .payloads import (
    discovery_signal_payload,
    gate_decision_payload,
    lead_disposition_payload,
    news_lead_payload,
    watch_condition_payload,
)
from .types import (
    DecisionTerminality,
    DiscoverySignalId,
    GateBasis,
    GateDecisionId,
    GateOutcome,
    LeadDispositionDecisionId,
    LeadDispositionOutcome,
    NewsLeadId,
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
    WatchConditionId,
)

DISCOVERY_SIGNAL_ADMIT_COMMAND = "discovery.signal.admit"
DISCOVERY_GATE_DECIDE_COMMAND = "discovery.gate.decide"
DISCOVERY_LEAD_OPEN_COMMAND = "discovery.lead.open"
DISCOVERY_WATCH_CONDITION_RECORD_COMMAND = "discovery.watch_condition.record"
DISCOVERY_LEAD_DISPOSITION_RECORD_COMMAND = "discovery.lead.disposition.record"
DISCOVERY_SIGNAL_LEAD_COMMAND_TYPES = frozenset(
    {
        DISCOVERY_SIGNAL_ADMIT_COMMAND,
        DISCOVERY_GATE_DECIDE_COMMAND,
        DISCOVERY_LEAD_OPEN_COMMAND,
        DISCOVERY_WATCH_CONDITION_RECORD_COMMAND,
        DISCOVERY_LEAD_DISPOSITION_RECORD_COMMAND,
    }
)

_SIGNAL_SCHEMA = "discovery_signal_v1"
_GATE_SCHEMA = "discovery_gate_decision_v1"
_LEAD_SCHEMA = "news_lead_v1"
_WATCH_SCHEMA = "discovery_watch_condition_v1"
_DISPOSITION_SCHEMA = "lead_disposition_decision_v1"
_CONTRACT_VERSION = "discovery-signal-lead-contract-v1"
_DEFINITION_VERSION = "discovery-signal-lead-command-v1"


def _fixture_requests() -> tuple[
    tuple[str, Callable[[Any], bytes], dict[str, Any]], ...
]:
    now = UtcTimestamp.parse("2042-03-12T10:00:00.000000Z")
    later = UtcTimestamp.parse("2042-03-12T10:05:00.000000Z")
    review = UtcTimestamp.parse("2042-03-13T10:00:00.000000Z")
    expiry = UtcTimestamp.parse("2042-03-14T10:00:00.000000Z")

    definition_id = SourceDefinitionId.parse(
        "00000000-0000-4000-8000-000000008001"
    )
    version_id = SourceDefinitionVersionId.parse(
        "00000000-0000-4000-8000-000000008002"
    )
    item_id = SourceItemId.parse("00000000-0000-4000-8000-000000008003")
    revision_id = SourceRevisionId.parse(
        "00000000-0000-4000-8000-000000008004"
    )
    representation_id = DiscoveryRepresentationId.parse(
        "00000000-0000-4000-8000-000000008005"
    )
    outcome_id = CheckOutcomeId.parse(
        "00000000-0000-4000-8000-000000008006"
    )
    occurrence_id = DiscoveryOccurrenceId.parse(
        "00000000-0000-4000-8000-000000008007"
    )
    transition_id = ObservableTransitionId.parse(
        "00000000-0000-4000-8000-000000008008"
    )
    signal_id = DiscoverySignalId.parse(
        "00000000-0000-4000-8000-000000008009"
    )
    gate_id = GateDecisionId.parse(
        "00000000-0000-4000-8000-000000008010"
    )
    lead_id = NewsLeadId.parse("00000000-0000-4000-8000-000000008011")
    watch_id = WatchConditionId.parse(
        "00000000-0000-4000-8000-000000008012"
    )
    disposition_id = LeadDispositionDecisionId.parse(
        "00000000-0000-4000-8000-000000008013"
    )

    def policy(name: str) -> VersionedPolicyRef:
        return VersionedPolicyRef(name, "v1")

    transition_reference = ReasonReference(
        "OBSERVABLE_TRANSITION",
        str(transition_id),
    )
    transition_reason = StructuredReason(
        "CHANGE.GENUINE_TRANSITION",
        ReasonBasisClass.DETERMINISTIC_OBSERVATION,
        (transition_reference,),
        "Exact fixture source transition supports this decision.",
    )
    coverage = CoverageBasis(
        "COV-030",
        CoverageResponsibility.ACTIVE,
        CoverageContribution.DETECTION_PATH,
        policy("fixture-coverage"),
    )
    signal = DiscoverySignalRequest(
        signal_id=signal_id,
        definition_id=definition_id,
        definition_version_id=version_id,
        item_id=item_id,
        revision_id=revision_id,
        representation_id=representation_id,
        check_outcome_id=outcome_id,
        occurrence_id=occurrence_id,
        transition_id=transition_id,
        purpose="SOURCE_TRANSITION",
        discriminator="primary",
        admission_policy=policy("fixture-signal-admission"),
        incomplete=False,
        operational_finding_ids=(),
        admitted_at=now,
        idempotency_key="fixture-signal",
    )
    gate = GateDecisionRequest(
        decision_id=gate_id,
        signal_id=signal_id,
        decision_ordinal=1,
        previous_decision_id=None,
        evaluated_definition_version_id=version_id,
        coverage=coverage,
        rights_decision_id="00000000-0000-4000-8000-000000008099",
        rights_policy_version="fixture-rights-v1",
        signal_admission_policy=policy("fixture-signal-admission"),
        gate_policy=policy("fixture-gate"),
        duplicate_policy=policy("fixture-duplicate"),
        newness_policy=policy("fixture-newness"),
        time_validity_policy=policy("fixture-time-validity"),
        exclusion_policy=policy("fixture-exclusion"),
        basis=GateBasis(
            identity_integrity=True,
            duplicate_signal_id=None,
            duplicate_rule=None,
            observable_newness=ObservableNewness.GENUINE_TRANSITION,
            time_validity=TimeValidity.CURRENT,
            scope_disposition=ScopeDisposition.ACCEPTED,
            clear_exclusion_rule=None,
            rights_current=True,
            policy_current=True,
            operationally_executable=True,
        ),
        outcome=GateOutcome.PROMOTED_TO_LEAD,
        terminality=DecisionTerminality.TERMINAL_EXACT_VERSION,
        primary_reason=transition_reason,
        supporting_reasons=(),
        reason_taxonomy_version="fixture-reasons-v1",
        outcome_taxonomy_version="fixture-outcomes-v1",
        next_action=NextAction(
            NextActionKind.QUEUE_TRIAGE,
            "QUEUE_FOR_TRIAGE",
            instructions="Create one immutable Lead and initial disposition.",
        ),
        decided_at=later,
        idempotency_key="fixture-gate",
    )
    urgency = UrgencyBasis(
        UrgencyRoute.ROUTINE,
        StructuredReason(
            "TIME.ROUTINE_SOURCE_CHANGE",
            ReasonBasisClass.DETERMINISTIC_OBSERVATION,
            (transition_reference,),
            "Fixture transition has no exact urgent or planned deadline.",
        ),
    )
    lead = NewsLeadRequest(
        lead_id=lead_id,
        signal_id=signal_id,
        promoting_gate_decision_id=gate_id,
        definition_id=definition_id,
        definition_version_id=version_id,
        item_id=item_id,
        revision_id=revision_id,
        representation_id=representation_id,
        occurrence_id=occurrence_id,
        transition_id=transition_id,
        transition_kind=ObservableTransitionKind.REVISED,
        coverage=coverage,
        source_roles=(
            SourceRoleAssignment(
                SourceRole.ORIGINATING_AUTHORITY,
                "Observe fixture authority changes.",
                ("Fixture and approved replay only.",),
            ),
        ),
        portfolio_functions=(PortfolioFunction.ANCHOR,),
        source_dependencies=(
            SourceDependency(
                "fixture-origin",
                SourceDependencyKind.ORIGINATING_MATERIAL,
                "Fixture material is the originating source state.",
            ),
        ),
        incompleteness_warnings=(),
        urgency=urgency,
        lead_policy=policy("fixture-lead"),
        reason_taxonomy_version="fixture-reasons-v1",
        outcome_taxonomy_version="fixture-outcomes-v1",
        created_at=later,
        idempotency_key="fixture-lead",
    )
    watch = WatchConditionRequest(
        watch_condition_id=watch_id,
        lead_id=lead_id,
        resume_transition_kinds=(ObservableTransitionKind.REVISED,),
        expected_occurrence="Fixture source publishes a later revision.",
        corroborating_lead_id=None,
        review_at=review,
        expires_at=expiry,
        operator_review_condition=None,
        closure_rule="CLOSE_ON_EXPIRY",
        watch_policy=policy("fixture-watch"),
        recorded_at=later,
        idempotency_key="fixture-watch",
    )
    disposition = LeadDispositionDecisionRequest(
        decision_id=disposition_id,
        lead_id=lead_id,
        decision_ordinal=1,
        previous_decision_id=None,
        outcome=LeadDispositionOutcome.QUEUED_FOR_TRIAGE,
        terminality=DecisionTerminality.PENDING_CONDITION,
        primary_reason=StructuredReason(
            "CHANGE.LEAD_CREATED",
            ReasonBasisClass.DETERMINISTIC_OBSERVATION,
            (transition_reference,),
            "Promoted fixture Signal created one immutable Lead.",
        ),
        supporting_reasons=(),
        watch_condition_id=None,
        next_action=NextAction(
            NextActionKind.QUEUE_TRIAGE,
            "QUEUE_FOR_TRIAGE",
            instructions="Queue without creating a Triage Work Item.",
        ),
        urgency_route=urgency,
        disposition_policy=policy("fixture-lead-disposition"),
        reason_taxonomy_version="fixture-reasons-v1",
        outcome_taxonomy_version="fixture-outcomes-v1",
        decided_at=later,
        idempotency_key="fixture-disposition",
    )
    return (
        (_SIGNAL_SCHEMA, discovery_signal_payload, signal.canonical_value()),
        (_GATE_SCHEMA, gate_decision_payload, gate.canonical_value()),
        (_LEAD_SCHEMA, news_lead_payload, lead.canonical_value()),
        (_WATCH_SCHEMA, watch_condition_payload, watch.canonical_value()),
        (
            _DISPOSITION_SCHEMA,
            lead_disposition_payload,
            disposition.canonical_value(),
        ),
    )


def discovery_signal_lead_payload_contracts() -> tuple[PayloadSchemaContract, ...]:
    return tuple(
        PayloadSchemaContract(
            schema_version=schema_version,
            payload_mode=PayloadMode.INLINE,
            contract_version=_CONTRACT_VERSION,
            canonicalizer_implementation_version=(
                f"{schema_version}-canonical-json-v1"
            ),
            canonicalizer=canonicalizer,
            golden_vectors=(
                PayloadGoldenVector(
                    name=f"{schema_version}-exact-fields",
                    input_identity=f"{schema_version}-golden-v1",
                    value=vector,
                    expected_bytes=canonicalizer(vector),
                ),
            ),
        )
        for schema_version, canonicalizer, vector in _fixture_requests()
    )


def discovery_signal_lead_command_definitions() -> tuple[CommandDefinition, ...]:
    contracts = {
        item.schema_version: item
        for item in discovery_signal_lead_payload_contracts()
    }
    specs = (
        (
            DISCOVERY_SIGNAL_ADMIT_COMMAND,
            "discovery_signal",
            "discovery.signal.admitted",
            _SIGNAL_SCHEMA,
            "authority.discovery.signals.admit",
        ),
        (
            DISCOVERY_GATE_DECIDE_COMMAND,
            "gate_decision",
            "discovery.gate.decided",
            _GATE_SCHEMA,
            "authority.discovery.gates.decide",
        ),
        (
            DISCOVERY_LEAD_OPEN_COMMAND,
            "news_lead",
            "discovery.lead.opened",
            _LEAD_SCHEMA,
            "authority.discovery.leads.open",
        ),
        (
            DISCOVERY_WATCH_CONDITION_RECORD_COMMAND,
            "watch_condition",
            "discovery.watch_condition.recorded",
            _WATCH_SCHEMA,
            "authority.discovery.watch.manage",
        ),
        (
            DISCOVERY_LEAD_DISPOSITION_RECORD_COMMAND,
            "lead_disposition_decision",
            "discovery.lead.disposition.recorded",
            _DISPOSITION_SCHEMA,
            "authority.discovery.leads.disposition",
        ),
    )
    return tuple(
        CommandDefinition(
            command_type=command_type,
            definition_version=_DEFINITION_VERSION,
            aggregate_type=aggregate_type,
            event_type=event_type,
            event_schema_version=1,
            payload_mode=PayloadMode.INLINE,
            payload_schema_version=contracts[schema_version].schema_version,
            payload_schema_contract_version=contracts[schema_version].contract_version,
            payload_schema_contract_digest=contracts[schema_version].contract_digest,
            payload_canonicalizer_version=(
                contracts[schema_version].canonicalizer_implementation_version
            ),
            trust_scope=TrustScope.ADMITTED,
            security_scope="authority.discovery",
            retention_scope="authority.audit",
            required_scope=required_scope,
            max_inline_bytes=512 * 1024,
        )
        for (
            command_type,
            aggregate_type,
            event_type,
            schema_version,
            required_scope,
        ) in specs
    )


def merge_discovery_signal_lead_registries(
    *,
    command_registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
) -> tuple[CommandRegistry, PayloadSchemaRegistry]:
    definitions = list(command_registry.definitions())
    by_key = {
        (item.command_type, item.definition_version): item
        for item in definitions
    }
    for definition in discovery_signal_lead_command_definitions():
        key = (definition.command_type, definition.definition_version)
        existing = by_key.get(key)
        if existing is not None and existing.digest != definition.digest:
            raise ProjectionContractError(
                f"Discovery command identity conflict: {definition.command_type}"
            )
        if existing is None:
            definitions.append(definition)
            by_key[key] = definition
    current_commands = {
        item.command_type: command_registry.resolve(
            item.command_type
        ).definition_version
        for item in definitions
        if item.command_type not in DISCOVERY_SIGNAL_LEAD_COMMAND_TYPES
    }
    current_commands.update(
        {
            command_type: _DEFINITION_VERSION
            for command_type in DISCOVERY_SIGNAL_LEAD_COMMAND_TYPES
        }
    )

    contracts = list(payload_schemas.contracts())
    by_schema = {
        (item.schema_version, item.payload_mode, item.contract_version): item
        for item in contracts
    }
    discovery_contracts = discovery_signal_lead_payload_contracts()
    for contract in discovery_contracts:
        key = (
            contract.schema_version,
            contract.payload_mode,
            contract.contract_version,
        )
        existing = by_schema.get(key)
        if existing is not None and existing.contract_digest != contract.contract_digest:
            raise ProjectionContractError(
                f"Discovery payload identity conflict: {contract.schema_version}"
            )
        if existing is None:
            contracts.append(contract)
            by_schema[key] = contract
    discovery_versions = {item.schema_version for item in discovery_contracts}
    current_schemas: dict[tuple[str, PayloadMode], str] = {}
    for schema_version, mode in {
        (item.schema_version, item.payload_mode) for item in contracts
    }:
        if schema_version in discovery_versions:
            current_schemas[(schema_version, mode)] = _CONTRACT_VERSION
        else:
            current_schemas[(schema_version, mode)] = payload_schemas.resolve(
                schema_version,
                mode,
            ).contract_version
    return (
        CommandRegistry(definitions, current_versions=current_commands),
        PayloadSchemaRegistry(contracts, current_versions=current_schemas),
    )


__all__ = [
    "DISCOVERY_GATE_DECIDE_COMMAND",
    "DISCOVERY_LEAD_DISPOSITION_RECORD_COMMAND",
    "DISCOVERY_LEAD_OPEN_COMMAND",
    "DISCOVERY_SIGNAL_ADMIT_COMMAND",
    "DISCOVERY_SIGNAL_LEAD_COMMAND_TYPES",
    "DISCOVERY_WATCH_CONDITION_RECORD_COMMAND",
    "discovery_signal_lead_command_definitions",
    "discovery_signal_lead_payload_contracts",
    "merge_discovery_signal_lead_registries",
]
