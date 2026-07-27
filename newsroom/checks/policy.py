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
from newsroom.discovery_adapters import AdapterRequestId, ObservationProposalId
from newsroom.projection.models import ProjectionContractError
from newsroom.sources import (
    CheckOutcomeId,
    CoverageContribution,
    CoverageResponsibility,
    DiscoveryRepresentationId,
    ObservationModel,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceItemId,
    SourceRevisionId,
    SourceTime,
    VersionedPolicyRef,
)

from .baseline_models import (
    BaselineDecisionRequest,
    BaselineManifestEntry,
)
from .check_models import (
    CandidateObservationRef,
    CheckAttemptRequest,
    CheckOutcomeRequest,
    CheckRequestRequest,
)
from .finding_models import (
    OperationalFindingOccurrenceRequest,
    OperationalFindingRequest,
)
from .payloads import (
    baseline_decision_payload,
    check_attempt_payload,
    check_outcome_payload,
    check_request_payload,
    observable_transition_payload,
    operational_finding_occurrence_payload,
    operational_finding_payload,
)
from .transition_models import ObservableTransitionRequest
from .types import (
    BaselineDecisionId,
    BaselineDecisionKind,
    BaselineDisposition,
    BaselineEntryDisposition,
    CheckAttemptId,
    CheckAttemptKind,
    CheckOutcomeKind,
    CheckRequestId,
    CoverageBasis,
    FindingCategory,
    FindingScopeKind,
    FindingSeverity,
    ObservableTransitionId,
    ObservableTransitionKind,
    OperationalFindingId,
    OperationalFindingOccurrenceId,
    QuarantineDisposition,
    TransitionBasis,
    TriggerKind,
    TriggerRef,
)

CHECK_REQUEST_REGISTER_COMMAND = "check.request.register"
CHECK_ATTEMPT_START_COMMAND = "check.attempt.start"
CHECK_OUTCOME_RECORD_COMMAND = "check.outcome.record"
CHECK_BASELINE_DECIDE_COMMAND = "check.baseline.decide"
OBSERVABLE_TRANSITION_RECORD_COMMAND = "source.observable_transition.record"
OPERATIONAL_FINDING_OPEN_COMMAND = "operational.finding.open"
OPERATIONAL_FINDING_OCCURRENCE_RECORD_COMMAND = (
    "operational.finding.occurrence.record"
)
DISCOVERY_CHECK_COMMAND_TYPES = frozenset(
    {
        CHECK_REQUEST_REGISTER_COMMAND,
        CHECK_ATTEMPT_START_COMMAND,
        CHECK_OUTCOME_RECORD_COMMAND,
        CHECK_BASELINE_DECIDE_COMMAND,
        OBSERVABLE_TRANSITION_RECORD_COMMAND,
        OPERATIONAL_FINDING_OPEN_COMMAND,
        OPERATIONAL_FINDING_OCCURRENCE_RECORD_COMMAND,
    }
)

_CHECK_REQUEST_SCHEMA = "check_request_v1"
_CHECK_ATTEMPT_SCHEMA = "check_attempt_v1"
_CHECK_OUTCOME_SCHEMA = "check_outcome_v1"
_BASELINE_DECISION_SCHEMA = "baseline_decision_v1"
_TRANSITION_SCHEMA = "observable_transition_v1"
_FINDING_SCHEMA = "operational_finding_v1"
_FINDING_OCCURRENCE_SCHEMA = "operational_finding_occurrence_v1"
_CONTRACT_VERSION = "discovery-check-contract-v1"
_DEFINITION_VERSION = "discovery-check-command-v1"


def _fixture_vectors() -> tuple[
    tuple[str, Callable[[Any], bytes], dict[str, Any]], ...
]:
    now = UtcTimestamp.parse("2042-03-12T10:00:00.000000Z")
    digest_a = "sha256:" + "a" * 64
    digest_b = "sha256:" + "b" * 64
    digest_c = "sha256:" + "c" * 64
    digest_d = "sha256:" + "d" * 64
    digest_e = "sha256:" + "e" * 64
    digest_f = "sha256:" + "f" * 64

    request_id = CheckRequestId.parse(
        "00000000-0000-4000-8000-000000005001"
    )
    attempt_id = CheckAttemptId.parse(
        "00000000-0000-4000-8000-000000005002"
    )
    outcome_id = CheckOutcomeId.parse(
        "00000000-0000-4000-8000-000000005003"
    )
    definition_id = SourceDefinitionId.parse(
        "00000000-0000-4000-8000-000000005004"
    )
    version_id = SourceDefinitionVersionId.parse(
        "00000000-0000-4000-8000-000000005005"
    )
    item_id = SourceItemId.parse(
        "00000000-0000-4000-8000-000000005006"
    )
    revision_id = SourceRevisionId.parse(
        "00000000-0000-4000-8000-000000005007"
    )
    representation_id = DiscoveryRepresentationId.parse(
        "00000000-0000-4000-8000-000000005008"
    )
    adapter_request_id = AdapterRequestId.parse(
        "00000000-0000-4000-8000-000000005009"
    )
    proposal_id = ObservationProposalId.parse(
        "00000000-0000-4000-8000-000000005010"
    )
    baseline_id = BaselineDecisionId.parse(
        "00000000-0000-4000-8000-000000005011"
    )
    transition_id = ObservableTransitionId.parse(
        "00000000-0000-4000-8000-000000005012"
    )
    finding_id = OperationalFindingId.parse(
        "00000000-0000-4000-8000-000000005013"
    )
    finding_occurrence_id = OperationalFindingOccurrenceId.parse(
        "00000000-0000-4000-8000-000000005014"
    )

    baseline_policy = VersionedPolicyRef(
        "fixture-baseline",
        "v1",
    )
    revision_policy = VersionedPolicyRef(
        "fixture-revision",
        "v1",
    )
    transition_policy = VersionedPolicyRef(
        "fixture-transition",
        "v1",
    )
    validator_policy = VersionedPolicyRef(
        "fixture-validator",
        "v1",
    )
    finding_policy = VersionedPolicyRef(
        "fixture-finding",
        "v1",
    )

    check_request = CheckRequestRequest(
        request_id=request_id,
        definition_id=definition_id,
        definition_version_id=version_id,
        trigger=TriggerRef(
            TriggerKind.FIXTURE_MANUAL,
            "fixture-trigger",
            "v1",
        ),
        coverage=CoverageBasis(
            "COV-021",
            CoverageResponsibility.ACTIVE,
            CoverageContribution.REVISION_VISIBILITY,
            VersionedPolicyRef("fixture-coverage", "v1"),
        ),
        rights_decision_id=(
            "00000000-0000-4000-8000-000000005099"
        ),
        rights_policy_version="fixture-rights-v1",
        adapter_request_digest=digest_a,
        producer_slot_digest=digest_b,
        baseline_policy=baseline_policy,
        revision_policy=revision_policy,
        transition_policy=transition_policy,
        validator_policy=validator_policy,
        purpose="Exercise deterministic Check authority contracts.",
        requested_at=now,
        idempotency_key="fixture-check-request",
    )
    check_attempt = CheckAttemptRequest(
        attempt_id=attempt_id,
        request_id=request_id,
        attempt_number=1,
        kind=CheckAttemptKind.PRIMARY,
        prior_attempt_id=None,
        adapter_request_id=adapter_request_id,
        adapter_request_digest=digest_a,
        started_at=now,
        idempotency_key="fixture-check-attempt",
    )
    candidate = CandidateObservationRef(digest_c, digest_d)
    check_outcome = CheckOutcomeRequest(
        outcome_id=outcome_id,
        request_id=request_id,
        attempt_id=attempt_id,
        proposal_id=proposal_id,
        definition_id=definition_id,
        definition_version_id=version_id,
        kind=CheckOutcomeKind.SUCCESS_CHANGED,
        reason_codes=("OBSERVABLE_CHANGE_CANDIDATES",),
        quarantine=QuarantineDisposition.NONE,
        incomplete=False,
        receipt_digest=digest_e,
        capture_digest=digest_f,
        parser_result_digest=digest_a,
        source_body_digest=digest_b,
        producer_slot_digest=digest_c,
        representation_digest=digest_d,
        validator_digest=None,
        candidate_observations=(candidate,),
        completed_at=now,
        idempotency_key="fixture-check-outcome",
    )
    baseline = BaselineDecisionRequest(
        decision_id=baseline_id,
        definition_id=definition_id,
        definition_version_id=version_id,
        check_request_id=request_id,
        check_outcome_id=outcome_id,
        kind=BaselineDecisionKind.ESTABLISH,
        disposition=BaselineDisposition.MAINTAINED_BASELINE_ONLY,
        observation_model=ObservationModel.MUTABLE_ITEM,
        baseline_policy=baseline_policy,
        previous_decision_id=None,
        entries=(
            BaselineManifestEntry(
                item_key=digest_c,
                disposition=BaselineEntryDisposition.INCLUDED,
                reason_code="INITIAL_MAINTAINED_STATE",
                item_id=item_id,
                revision_id=revision_id,
            ),
        ),
        source_body_digest=digest_b,
        producer_slot_digest=digest_c,
        representation_digest=digest_d,
        validator_digest=None,
        reason_codes=("MAINTAINED_BASELINE_ONLY",),
        decided_at=now,
        idempotency_key="fixture-baseline-decision",
    )
    transition = ObservableTransitionRequest(
        transition_id=transition_id,
        definition_id=definition_id,
        definition_version_id=version_id,
        check_outcome_id=outcome_id,
        item_id=item_id,
        kind=ObservableTransitionKind.FIRST_OBSERVED,
        basis=TransitionBasis.REVISION,
        observation_model=ObservationModel.MUTABLE_ITEM,
        prior_revision_id=None,
        current_revision_id=revision_id,
        representation_id=representation_id,
        related_item_id=None,
        change_facets=(),
        transition_policy=transition_policy,
        absence_guard=None,
        agenda_guard=None,
        source_asserted_time=SourceTime.unknown(),
        observed_at=now,
        transition_discriminator="first-observed",
        idempotency_key="fixture-observable-transition",
    )
    finding = OperationalFindingRequest(
        finding_id=finding_id,
        scope_kind=FindingScopeKind.CHECK_OUTCOME,
        scope_id=str(outcome_id),
        category=FindingCategory.PARSER,
        severity=FindingSeverity.BLOCKING,
        finding_policy=finding_policy,
        summary="Fixture parser condition requires review.",
        opened_by_request_id=request_id,
        opened_by_attempt_id=attempt_id,
        opened_by_outcome_id=outcome_id,
        opened_at=now,
        idempotency_key="fixture-operational-finding",
    )
    finding_occurrence = OperationalFindingOccurrenceRequest(
        occurrence_id=finding_occurrence_id,
        finding_id=finding_id,
        request_id=request_id,
        attempt_id=attempt_id,
        outcome_id=outcome_id,
        code="PARSER_REJECTED_INPUT",
        detail_digest=digest_e,
        observed_at=now,
        idempotency_key="fixture-finding-occurrence",
    )

    return (
        (
            _CHECK_REQUEST_SCHEMA,
            check_request_payload,
            check_request.canonical_value(),
        ),
        (
            _CHECK_ATTEMPT_SCHEMA,
            check_attempt_payload,
            check_attempt.canonical_value(),
        ),
        (
            _CHECK_OUTCOME_SCHEMA,
            check_outcome_payload,
            check_outcome.canonical_value(),
        ),
        (
            _BASELINE_DECISION_SCHEMA,
            baseline_decision_payload,
            baseline.canonical_value(),
        ),
        (
            _TRANSITION_SCHEMA,
            observable_transition_payload,
            transition.canonical_value(),
        ),
        (
            _FINDING_SCHEMA,
            operational_finding_payload,
            finding.canonical_value(),
        ),
        (
            _FINDING_OCCURRENCE_SCHEMA,
            operational_finding_occurrence_payload,
            finding_occurrence.canonical_value(),
        ),
    )


def discovery_check_payload_contracts() -> tuple[PayloadSchemaContract, ...]:
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
        for schema_version, canonicalizer, vector in _fixture_vectors()
    )


def discovery_check_command_definitions() -> tuple[CommandDefinition, ...]:
    contracts = {
        item.schema_version: item
        for item in discovery_check_payload_contracts()
    }
    specs = (
        (
            CHECK_REQUEST_REGISTER_COMMAND,
            "check_request",
            "check.request.registered",
            _CHECK_REQUEST_SCHEMA,
            TrustScope.ADMITTED,
            "authority.checks.manage",
        ),
        (
            CHECK_ATTEMPT_START_COMMAND,
            "check_attempt",
            "check.attempt.started",
            _CHECK_ATTEMPT_SCHEMA,
            TrustScope.OBSERVED,
            "authority.checks.execute",
        ),
        (
            CHECK_OUTCOME_RECORD_COMMAND,
            "check_outcome",
            "check.outcome.recorded",
            _CHECK_OUTCOME_SCHEMA,
            TrustScope.OBSERVED,
            "authority.checks.observe",
        ),
        (
            CHECK_BASELINE_DECIDE_COMMAND,
            "baseline_decision",
            "check.baseline.decided",
            _BASELINE_DECISION_SCHEMA,
            TrustScope.ADMITTED,
            "authority.checks.decide",
        ),
        (
            OBSERVABLE_TRANSITION_RECORD_COMMAND,
            "observable_transition",
            "source.observable_transition.recorded",
            _TRANSITION_SCHEMA,
            TrustScope.ADMITTED,
            "authority.checks.decide",
        ),
        (
            OPERATIONAL_FINDING_OPEN_COMMAND,
            "operational_finding",
            "operational.finding.opened",
            _FINDING_SCHEMA,
            TrustScope.ADMITTED,
            "authority.findings.manage",
        ),
        (
            OPERATIONAL_FINDING_OCCURRENCE_RECORD_COMMAND,
            "operational_finding_occurrence",
            "operational.finding.occurrence.recorded",
            _FINDING_OCCURRENCE_SCHEMA,
            TrustScope.OBSERVED,
            "authority.findings.observe",
        ),
    )
    definitions: list[CommandDefinition] = []
    for (
        command_type,
        aggregate_type,
        event_type,
        schema_version,
        trust_scope,
        required_scope,
    ) in specs:
        contract = contracts[schema_version]
        definitions.append(
            CommandDefinition(
                command_type=command_type,
                definition_version=_DEFINITION_VERSION,
                aggregate_type=aggregate_type,
                event_type=event_type,
                event_schema_version=1,
                payload_mode=PayloadMode.INLINE,
                payload_schema_version=contract.schema_version,
                payload_schema_contract_version=contract.contract_version,
                payload_schema_contract_digest=contract.contract_digest,
                payload_canonicalizer_version=(
                    contract.canonicalizer_implementation_version
                ),
                trust_scope=trust_scope,
                security_scope="authority.discovery_checks",
                retention_scope="authority.audit",
                required_scope=required_scope,
                max_inline_bytes=512 * 1024,
            )
        )
    return tuple(definitions)


def merge_discovery_check_authority_registries(
    *,
    command_registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
) -> tuple[CommandRegistry, PayloadSchemaRegistry]:
    definitions = list(command_registry.definitions())
    by_key = {
        (item.command_type, item.definition_version): item
        for item in definitions
    }
    for definition in discovery_check_command_definitions():
        key = (definition.command_type, definition.definition_version)
        existing = by_key.get(key)
        if existing is not None and existing.digest != definition.digest:
            raise ProjectionContractError(
                f"Check command identity conflict: {definition.command_type}"
            )
        if existing is None:
            definitions.append(definition)
            by_key[key] = definition
    current_commands = {
        item.command_type: command_registry.resolve(
            item.command_type
        ).definition_version
        for item in definitions
        if item.command_type not in DISCOVERY_CHECK_COMMAND_TYPES
    }
    current_commands.update(
        {
            command_type: _DEFINITION_VERSION
            for command_type in DISCOVERY_CHECK_COMMAND_TYPES
        }
    )

    contracts = list(payload_schemas.contracts())
    by_schema = {
        (item.schema_version, item.payload_mode, item.contract_version): item
        for item in contracts
    }
    check_contracts = discovery_check_payload_contracts()
    for contract in check_contracts:
        key = (
            contract.schema_version,
            contract.payload_mode,
            contract.contract_version,
        )
        existing = by_schema.get(key)
        if (
            existing is not None
            and existing.contract_digest != contract.contract_digest
        ):
            raise ProjectionContractError(
                f"Check payload identity conflict: {contract.schema_version}"
            )
        if existing is None:
            contracts.append(contract)
            by_schema[key] = contract
    check_versions = {item.schema_version for item in check_contracts}
    current_schemas: dict[tuple[str, PayloadMode], str] = {}
    for schema_version, mode in {
        (item.schema_version, item.payload_mode) for item in contracts
    }:
        if schema_version in check_versions:
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
    "CHECK_ATTEMPT_START_COMMAND",
    "CHECK_BASELINE_DECIDE_COMMAND",
    "CHECK_OUTCOME_RECORD_COMMAND",
    "CHECK_REQUEST_REGISTER_COMMAND",
    "DISCOVERY_CHECK_COMMAND_TYPES",
    "OBSERVABLE_TRANSITION_RECORD_COMMAND",
    "OPERATIONAL_FINDING_OCCURRENCE_RECORD_COMMAND",
    "OPERATIONAL_FINDING_OPEN_COMMAND",
    "discovery_check_command_definitions",
    "discovery_check_payload_contracts",
    "merge_discovery_check_authority_registries",
]
