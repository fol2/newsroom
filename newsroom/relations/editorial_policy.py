from __future__ import annotations

from typing import Any, Callable

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.authority.models import CommandDefinition
from newsroom.authority.policy import (
    CommandRegistry,
    PayloadGoldenVector,
    PayloadSchemaContract,
    PayloadSchemaRegistry,
    PayloadSchemaValidationError,
)
from newsroom.authority.types import EventId, PayloadMode, TrustScope, UtcTimestamp
from newsroom.entities.policy import merge_entity_authority_registries
from newsroom.entities.types import (
    CanonicalEntityId,
    CanonicalEntityVersionId,
    EntityResolutionDependencyId,
)
from newsroom.extraction.types import (
    ExtractionOutputId,
    ExtractionPassageId,
    ExtractionRunId,
    ExtractionRunVersionId,
    ProposalEnvelopeId,
)
from newsroom.integrated.models import (
    IntegratedHypothesisVersionId,
    StoryCandidateId,
    StoryCandidateVersionId,
)
from newsroom.sources.types import SourceItemId, SourceRevisionId

from .editorial_models import (
    EDITORIAL_PREDICATE_REGISTRY_V1,
    EDITORIAL_RELATION_ADMISSION_POLICY_VERSION,
    CanonicalEntityRelationEndpoint,
    EditorialRelationDecisionRequest,
    EditorialRelationProducer,
    EditorialRelationProposalRequest,
    EditorialRelationTemporalScope,
    EventHypothesisRelationEndpoint,
    ExtractionRelationEvidence,
    RelationAssertionRelationEndpoint,
    SourceRevisionRelationEndpoint,
    StoryCandidateRelationEndpoint,
    WorkflowRelationEvidence,
)
from .editorial_types import (
    EditorialPredicateCode,
    EditorialRelationAssertionId,
    EditorialRelationDecisionAction,
    EditorialRelationDecisionId,
    EditorialRelationEndpointKind,
    EditorialRelationEvidenceKind,
    EditorialRelationProducerKind,
    EditorialRelationProposalId,
    EditorialRelationProposalVersionId,
    EditorialRelationSupersessionId,
)


EDITORIAL_RELATION_PROPOSAL_COMMAND = "editorial.relation.proposal.record"
EDITORIAL_RELATION_DECISION_COMMAND = "editorial.relation.decision.record"
EDITORIAL_RELATION_COMMAND_TYPES = frozenset(
    {
        EDITORIAL_RELATION_PROPOSAL_COMMAND,
        EDITORIAL_RELATION_DECISION_COMMAND,
    }
)

_PROPOSAL_SCHEMA = "editorial_relation_proposal_v1"
_DECISION_SCHEMA = "editorial_relation_decision_v1"
_CONTRACT_VERSION = "editorial-relation-authority-contract-v1"
_DEFINITION_VERSION = "editorial-relation-authority-command-v1"


def _object(value: Any, *, field: str, keys: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or frozenset(value) != keys:
        raise PayloadSchemaValidationError(f"{field} has an invalid exact field set")
    return value


def _required_id(value: Any, parser: Callable[[str], Any], *, field: str) -> Any:
    if not isinstance(value, str):
        raise PayloadSchemaValidationError(f"{field} must be canonical identity text")
    try:
        return parser(value)
    except (TypeError, ValueError) as exc:
        raise PayloadSchemaValidationError(f"{field} is invalid") from exc


def _optional_id(value: Any, parser: Callable[[str], Any], *, field: str) -> Any:
    if value is None:
        return None
    return _required_id(value, parser, field=field)


def _string(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise PayloadSchemaValidationError(f"{field} must be text")
    return value


def _integer(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PayloadSchemaValidationError(f"{field} must be an integer")
    return value


def _optional_integer(value: Any, *, field: str) -> int | None:
    if value is None:
        return None
    return _integer(value, field=field)


def _enum(value: Any, enum_type: type, *, field: str) -> Any:
    if not isinstance(value, str):
        raise PayloadSchemaValidationError(f"{field} must be text")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise PayloadSchemaValidationError(f"{field} is invalid") from exc


def _strings(value: Any, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise PayloadSchemaValidationError(f"{field} must be a text array")
    return tuple(value)


def _endpoint(value: Any, *, field: str):
    if not isinstance(value, dict) or "kind" not in value:
        raise PayloadSchemaValidationError(f"{field} must be an endpoint object")
    kind = _enum(value["kind"], EditorialRelationEndpointKind, field=f"{field}.kind")
    if kind is EditorialRelationEndpointKind.CANONICAL_ENTITY_VERSION:
        item = _object(
            value,
            field=field,
            keys=frozenset({"kind", "entity_id", "entity_version_id"}),
        )
        return CanonicalEntityRelationEndpoint(
            entity_id=_required_id(
                item["entity_id"], CanonicalEntityId.parse, field=f"{field}.entity_id"
            ),
            entity_version_id=_required_id(
                item["entity_version_id"],
                CanonicalEntityVersionId.parse,
                field=f"{field}.entity_version_id",
            ),
        )
    if kind is EditorialRelationEndpointKind.SOURCE_REVISION:
        item = _object(
            value,
            field=field,
            keys=frozenset({"kind", "source_item_id", "source_revision_id"}),
        )
        return SourceRevisionRelationEndpoint(
            source_item_id=_required_id(
                item["source_item_id"], SourceItemId.parse, field=f"{field}.source_item_id"
            ),
            source_revision_id=_required_id(
                item["source_revision_id"],
                SourceRevisionId.parse,
                field=f"{field}.source_revision_id",
            ),
        )
    if kind is EditorialRelationEndpointKind.EVENT_HYPOTHESIS_VERSION:
        item = _object(
            value,
            field=field,
            keys=frozenset({"kind", "hypothesis_version_id"}),
        )
        return EventHypothesisRelationEndpoint(
            hypothesis_version_id=_required_id(
                item["hypothesis_version_id"],
                IntegratedHypothesisVersionId.parse,
                field=f"{field}.hypothesis_version_id",
            )
        )
    if kind is EditorialRelationEndpointKind.STORY_CANDIDATE_VERSION:
        item = _object(
            value,
            field=field,
            keys=frozenset({"kind", "candidate_id", "candidate_version_id"}),
        )
        return StoryCandidateRelationEndpoint(
            candidate_id=_required_id(
                item["candidate_id"], StoryCandidateId.parse, field=f"{field}.candidate_id"
            ),
            candidate_version_id=_required_id(
                item["candidate_version_id"],
                StoryCandidateVersionId.parse,
                field=f"{field}.candidate_version_id",
            ),
        )
    item = _object(
        value,
        field=field,
        keys=frozenset({"kind", "assertion_id"}),
    )
    return RelationAssertionRelationEndpoint(
        assertion_id=_required_id(
            item["assertion_id"],
            EditorialRelationAssertionId.parse,
            field=f"{field}.assertion_id",
        )
    )


def _temporal(value: Any) -> EditorialRelationTemporalScope:
    item = _object(
        value,
        field="temporal_scope",
        keys=frozenset({"valid_from", "valid_until", "observed_at"}),
    )
    return EditorialRelationTemporalScope(
        valid_from=(
            UtcTimestamp.parse(item["valid_from"])
            if isinstance(item["valid_from"], str)
            else None
        ),
        valid_until=(
            UtcTimestamp.parse(item["valid_until"])
            if isinstance(item["valid_until"], str)
            else None
        ),
        observed_at=UtcTimestamp.parse(
            _string(item["observed_at"], field="observed_at")
        ),
    )


def _evidence(value: Any) -> tuple[ExtractionRelationEvidence | WorkflowRelationEvidence, ...]:
    if not isinstance(value, list):
        raise PayloadSchemaValidationError("evidence must be an array")
    results = []
    for raw in value:
        if not isinstance(raw, dict) or "kind" not in raw:
            raise PayloadSchemaValidationError("evidence item must be an object")
        kind = _enum(raw["kind"], EditorialRelationEvidenceKind, field="evidence.kind")
        if kind is EditorialRelationEvidenceKind.EXTRACTION_PROPOSAL:
            item = _object(
                raw,
                field="extraction_evidence",
                keys=frozenset(
                    {
                        "kind",
                        "source_proposal_id",
                        "source_proposal_digest",
                        "run_id",
                        "run_version_id",
                        "output_id",
                        "passage_id",
                        "source_evidence_ordinal",
                        "start_byte",
                        "end_byte",
                        "evidence_text_digest",
                    }
                ),
            )
            results.append(
                ExtractionRelationEvidence(
                    source_proposal_id=_required_id(
                        item["source_proposal_id"],
                        ProposalEnvelopeId.parse,
                        field="source_proposal_id",
                    ),
                    source_proposal_digest=_string(
                        item["source_proposal_digest"], field="source_proposal_digest"
                    ),
                    run_id=_required_id(item["run_id"], ExtractionRunId.parse, field="run_id"),
                    run_version_id=_required_id(
                        item["run_version_id"],
                        ExtractionRunVersionId.parse,
                        field="run_version_id",
                    ),
                    output_id=_required_id(
                        item["output_id"], ExtractionOutputId.parse, field="output_id"
                    ),
                    passage_id=_required_id(
                        item["passage_id"], ExtractionPassageId.parse, field="passage_id"
                    ),
                    source_evidence_ordinal=_integer(
                        item["source_evidence_ordinal"], field="source_evidence_ordinal"
                    ),
                    start_byte=_integer(item["start_byte"], field="start_byte"),
                    end_byte=_integer(item["end_byte"], field="end_byte"),
                    evidence_text_digest=_string(
                        item["evidence_text_digest"], field="evidence_text_digest"
                    ),
                )
            )
        else:
            item = _object(
                raw,
                field="workflow_evidence",
                keys=frozenset(
                    {
                        "kind",
                        "authority_event_id",
                        "aggregate_type",
                        "aggregate_id",
                        "aggregate_version",
                        "event_digest",
                    }
                ),
            )
            results.append(
                WorkflowRelationEvidence(
                    authority_event_id=_required_id(
                        item["authority_event_id"],
                        EventId.parse,
                        field="authority_event_id",
                    ),
                    aggregate_type=_string(item["aggregate_type"], field="aggregate_type"),
                    aggregate_id=_string(item["aggregate_id"], field="aggregate_id"),
                    aggregate_version=_integer(
                        item["aggregate_version"], field="aggregate_version"
                    ),
                    event_digest=_string(item["event_digest"], field="event_digest"),
                )
            )
    return tuple(results)


def _producer(value: Any) -> EditorialRelationProducer:
    item = _object(
        value,
        field="producer",
        keys=frozenset({"kind", "producer_id", "producer_version", "contract_digest"}),
    )
    return EditorialRelationProducer(
        kind=_enum(item["kind"], EditorialRelationProducerKind, field="producer.kind"),
        producer_id=_string(item["producer_id"], field="producer_id"),
        producer_version=_string(item["producer_version"], field="producer_version"),
        contract_digest=_string(item["contract_digest"], field="producer_contract_digest"),
    )


def _proposal_payload(value: Any) -> bytes:
    keys = frozenset(
        {
            "proposal_id",
            "proposal_version_id",
            "version_number",
            "expected_previous_version_id",
            "predicate_registry_digest",
            "predicate_contract_digest",
            "predicate",
            "subject",
            "object",
            "temporal_scope",
            "evidence",
            "resolution_dependency_ids",
            "producer",
            "statement",
            "confidence_basis_points",
            "uncertainty_codes",
            "basis_codes",
        }
    )
    item = _object(value, field="editorial_relation_proposal", keys=keys)
    try:
        request = EditorialRelationProposalRequest(
            proposal_id=_required_id(
                item["proposal_id"], EditorialRelationProposalId.parse, field="proposal_id"
            ),
            proposal_version_id=_required_id(
                item["proposal_version_id"],
                EditorialRelationProposalVersionId.parse,
                field="proposal_version_id",
            ),
            version_number=_integer(item["version_number"], field="version_number"),
            expected_previous_version_id=_optional_id(
                item["expected_previous_version_id"],
                EditorialRelationProposalVersionId.parse,
                field="expected_previous_version_id",
            ),
            predicate_registry_digest=_string(
                item["predicate_registry_digest"], field="predicate_registry_digest"
            ),
            predicate_contract_digest=_string(
                item["predicate_contract_digest"], field="predicate_contract_digest"
            ),
            predicate=_enum(item["predicate"], EditorialPredicateCode, field="predicate"),
            subject=_endpoint(item["subject"], field="subject"),
            object=_endpoint(item["object"], field="object"),
            temporal_scope=_temporal(item["temporal_scope"]),
            evidence=_evidence(item["evidence"]),
            resolution_dependency_ids=tuple(
                _required_id(
                    raw,
                    EntityResolutionDependencyId.parse,
                    field="resolution_dependency_id",
                )
                for raw in item["resolution_dependency_ids"]
            ) if isinstance(item["resolution_dependency_ids"], list) else (),
            producer=_producer(item["producer"]),
            statement=_string(item["statement"], field="statement"),
            confidence_basis_points=_optional_integer(
                item["confidence_basis_points"], field="confidence_basis_points"
            ),
            uncertainty_codes=_strings(
                item["uncertainty_codes"], field="uncertainty_codes"
            ),
            basis_codes=_strings(item["basis_codes"], field="basis_codes"),
            idempotency_key="payload-validation-only",
        )
    except PayloadSchemaValidationError:
        raise
    except (TypeError, ValueError) as exc:
        raise PayloadSchemaValidationError(
            f"editorial relation proposal is invalid: {exc}"
        ) from exc
    canonical = request.canonical_value()
    if canonical != item:
        raise PayloadSchemaValidationError(
            "editorial relation proposal is not canonical"
        )
    return canonical_json_bytes(canonical)


def _decision_payload(value: Any) -> bytes:
    keys = frozenset(
        {
            "decision_id",
            "action",
            "proposal_id",
            "proposal_version_id",
            "expected_proposal_version_digest",
            "expected_previous_decision_id",
            "expected_previous_decision_version",
            "assertion_id",
            "target_assertion_id",
            "successor_assertion_id",
            "supersession_id",
            "reason_code",
            "decision_policy_version",
        }
    )
    item = _object(value, field="editorial_relation_decision", keys=keys)
    try:
        request = EditorialRelationDecisionRequest(
            decision_id=_required_id(
                item["decision_id"], EditorialRelationDecisionId.parse, field="decision_id"
            ),
            action=_enum(
                item["action"], EditorialRelationDecisionAction, field="action"
            ),
            proposal_id=_required_id(
                item["proposal_id"], EditorialRelationProposalId.parse, field="proposal_id"
            ),
            proposal_version_id=_required_id(
                item["proposal_version_id"],
                EditorialRelationProposalVersionId.parse,
                field="proposal_version_id",
            ),
            expected_proposal_version_digest=_string(
                item["expected_proposal_version_digest"],
                field="expected_proposal_version_digest",
            ),
            expected_previous_decision_id=_optional_id(
                item["expected_previous_decision_id"],
                EditorialRelationDecisionId.parse,
                field="expected_previous_decision_id",
            ),
            expected_previous_decision_version=_integer(
                item["expected_previous_decision_version"],
                field="expected_previous_decision_version",
            ),
            assertion_id=_optional_id(
                item["assertion_id"],
                EditorialRelationAssertionId.parse,
                field="assertion_id",
            ),
            target_assertion_id=_optional_id(
                item["target_assertion_id"],
                EditorialRelationAssertionId.parse,
                field="target_assertion_id",
            ),
            successor_assertion_id=_optional_id(
                item["successor_assertion_id"],
                EditorialRelationAssertionId.parse,
                field="successor_assertion_id",
            ),
            supersession_id=_optional_id(
                item["supersession_id"],
                EditorialRelationSupersessionId.parse,
                field="supersession_id",
            ),
            reason_code=_string(item["reason_code"], field="reason_code"),
            decision_policy_version=_string(
                item["decision_policy_version"], field="decision_policy_version"
            ),
            idempotency_key="payload-validation-only",
        )
    except PayloadSchemaValidationError:
        raise
    except (TypeError, ValueError) as exc:
        raise PayloadSchemaValidationError(
            f"editorial relation decision is invalid: {exc}"
        ) from exc
    canonical = request.canonical_value()
    if canonical != item:
        raise PayloadSchemaValidationError(
            "editorial relation decision is not canonical"
        )
    return canonical_json_bytes(canonical)


def _golden_proposal() -> EditorialRelationProposalRequest:
    predicate = EditorialPredicateCode.ABOUT_EVENT
    contract = EDITORIAL_PREDICATE_REGISTRY_V1.contract(predicate)
    evidence = ExtractionRelationEvidence(
        source_proposal_id=ProposalEnvelopeId.parse(
            "00000000-0000-4000-8000-00000000c001"
        ),
        source_proposal_digest="sha256:" + "11" * 32,
        run_id=ExtractionRunId.parse("00000000-0000-4000-8000-00000000c002"),
        run_version_id=ExtractionRunVersionId.parse(
            "00000000-0000-4000-8000-00000000c003"
        ),
        output_id=ExtractionOutputId.parse(
            "00000000-0000-4000-8000-00000000c004"
        ),
        passage_id=ExtractionPassageId.parse(
            "00000000-0000-4000-8000-00000000c005"
        ),
        source_evidence_ordinal=0,
        start_byte=0,
        end_byte=16,
        evidence_text_digest="sha256:" + "22" * 32,
    )
    return EditorialRelationProposalRequest(
        proposal_id=EditorialRelationProposalId.parse(
            "00000000-0000-4000-8000-00000000c010"
        ),
        proposal_version_id=EditorialRelationProposalVersionId.parse(
            "00000000-0000-4000-8000-00000000c011"
        ),
        version_number=1,
        expected_previous_version_id=None,
        predicate_registry_digest=EDITORIAL_PREDICATE_REGISTRY_V1.digest,
        predicate_contract_digest=contract.digest,
        predicate=predicate,
        subject=CanonicalEntityRelationEndpoint(
            entity_id=CanonicalEntityId.parse(
                "00000000-0000-4000-8000-00000000c020"
            ),
            entity_version_id=CanonicalEntityVersionId.parse(
                "00000000-0000-4000-8000-00000000c021"
            ),
        ),
        object=EventHypothesisRelationEndpoint(
            hypothesis_version_id=IntegratedHypothesisVersionId.parse(
                "00000000-0000-4000-8000-00000000c022"
            )
        ),
        temporal_scope=EditorialRelationTemporalScope(
            valid_from=None,
            valid_until=None,
            observed_at=UtcTimestamp.parse("2042-03-12T10:00:00.000000Z"),
        ),
        evidence=(evidence,),
        resolution_dependency_ids=(
            EntityResolutionDependencyId.parse(
                "00000000-0000-4000-8000-00000000c030"
            ),
        ),
        producer=EditorialRelationProducer(
            kind=EditorialRelationProducerKind.EXTRACTION_RUN,
            producer_id="fixture.editorial-relation",
            producer_version="fixture-editorial-relation-v1",
            contract_digest="sha256:" + "33" * 32,
        ),
        statement="The admitted entity is about the retained event hypothesis.",
        confidence_basis_points=7500,
        uncertainty_codes=("IDENTITY_REVIEWED",),
        basis_codes=("EXACT_OCCURRENCE",),
        idempotency_key="editorial-relation-proposal-golden",
    )


def _golden_decision(proposal: EditorialRelationProposalRequest) -> EditorialRelationDecisionRequest:
    return EditorialRelationDecisionRequest(
        decision_id=EditorialRelationDecisionId.parse(
            "00000000-0000-4000-8000-00000000c040"
        ),
        action=EditorialRelationDecisionAction.ACCEPT,
        proposal_id=proposal.proposal_id,
        proposal_version_id=proposal.proposal_version_id,
        expected_proposal_version_digest=proposal.canonical_digest,
        expected_previous_decision_id=None,
        expected_previous_decision_version=0,
        assertion_id=EditorialRelationAssertionId.parse(
            "00000000-0000-4000-8000-00000000c041"
        ),
        target_assertion_id=None,
        successor_assertion_id=None,
        supersession_id=None,
        reason_code="EXPLICIT_EDITORIAL_ACCEPT",
        decision_policy_version=EDITORIAL_RELATION_ADMISSION_POLICY_VERSION,
        idempotency_key="editorial-relation-decision-golden",
    )


def editorial_relation_payload_contracts() -> tuple[PayloadSchemaContract, ...]:
    proposal = _golden_proposal()
    decision = _golden_decision(proposal)
    specifications = (
        (_PROPOSAL_SCHEMA, "proposal", _proposal_payload, proposal),
        (_DECISION_SCHEMA, "decision", _decision_payload, decision),
    )
    return tuple(
        PayloadSchemaContract(
            schema_version=schema_version,
            payload_mode=PayloadMode.INLINE,
            contract_version=_CONTRACT_VERSION,
            canonicalizer_implementation_version=(
                f"editorial-relation-{name}-typed-exact-canonical-json-v1"
            ),
            canonicalizer=canonicalizer,
            golden_vectors=(
                PayloadGoldenVector(
                    name=f"editorial-relation-{name}-exact-fields",
                    input_identity=f"increment-4c-{name}-golden-v1",
                    value=request.canonical_value(),
                    expected_bytes=canonical_json_bytes(request.canonical_value()),
                ),
            ),
        )
        for schema_version, name, canonicalizer, request in specifications
    )


def editorial_relation_command_definitions() -> tuple[CommandDefinition, ...]:
    contracts = {
        item.schema_version: item for item in editorial_relation_payload_contracts()
    }
    specifications = (
        (
            EDITORIAL_RELATION_PROPOSAL_COMMAND,
            "editorial_relation_proposal_version",
            "editorial.relation.proposed",
            _PROPOSAL_SCHEMA,
            TrustScope.PROPOSED,
            "authority.relation.propose",
        ),
        (
            EDITORIAL_RELATION_DECISION_COMMAND,
            "editorial_relation_decision",
            "editorial.relation.decided",
            _DECISION_SCHEMA,
            TrustScope.ADMITTED,
            "authority.relation.decide",
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
            payload_schema_version=contracts[schema].schema_version,
            payload_schema_contract_version=contracts[schema].contract_version,
            payload_schema_contract_digest=contracts[schema].contract_digest,
            payload_canonicalizer_version=(
                contracts[schema].canonicalizer_implementation_version
            ),
            trust_scope=trust_scope,
            security_scope="authority.relation",
            retention_scope="authority.audit",
            required_scope=required_scope,
            max_inline_bytes=1024 * 1024,
        )
        for (
            command_type,
            aggregate_type,
            event_type,
            schema,
            trust_scope,
            required_scope,
        ) in specifications
    )


def merge_editorial_relation_authority_registries(
    *,
    command_registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
) -> tuple[CommandRegistry, PayloadSchemaRegistry]:
    entity_registry, entity_schemas = merge_entity_authority_registries(
        command_registry=command_registry,
        payload_schemas=payload_schemas,
    )
    definitions = list(entity_registry.definitions())
    by_key = {(item.command_type, item.definition_version): item for item in definitions}
    for definition in editorial_relation_command_definitions():
        key = (definition.command_type, definition.definition_version)
        existing = by_key.get(key)
        if existing is not None and existing.digest != definition.digest:
            raise ValueError(
                f"editorial relation command identity conflict: {definition.command_type}"
            )
        if existing is None:
            definitions.append(definition)
            by_key[key] = definition
    current_commands = {
        item.command_type: entity_registry.resolve(item.command_type).definition_version
        for item in definitions
        if item.command_type not in EDITORIAL_RELATION_COMMAND_TYPES
    }
    current_commands.update(
        {
            command_type: _DEFINITION_VERSION
            for command_type in EDITORIAL_RELATION_COMMAND_TYPES
        }
    )

    contracts = list(entity_schemas.contracts())
    by_schema = {
        (item.schema_version, item.payload_mode, item.contract_version): item
        for item in contracts
    }
    additions = editorial_relation_payload_contracts()
    for contract in additions:
        key = (contract.schema_version, contract.payload_mode, contract.contract_version)
        existing = by_schema.get(key)
        if existing is not None and existing.contract_digest != contract.contract_digest:
            raise ValueError(
                f"editorial relation payload identity conflict: {contract.schema_version}"
            )
        if existing is None:
            contracts.append(contract)
            by_schema[key] = contract
    editorial_versions = {item.schema_version for item in additions}
    current_schemas: dict[tuple[str, PayloadMode], str] = {}
    for schema_version, mode in {
        (item.schema_version, item.payload_mode) for item in contracts
    }:
        if schema_version in editorial_versions:
            current_schemas[(schema_version, mode)] = _CONTRACT_VERSION
        else:
            current_schemas[(schema_version, mode)] = entity_schemas.resolve(
                schema_version, mode
            ).contract_version
    return (
        CommandRegistry(definitions, current_versions=current_commands),
        PayloadSchemaRegistry(contracts, current_versions=current_schemas),
    )


__all__ = [
    "EDITORIAL_RELATION_COMMAND_TYPES",
    "EDITORIAL_RELATION_DECISION_COMMAND",
    "EDITORIAL_RELATION_PROPOSAL_COMMAND",
    "editorial_relation_command_definitions",
    "editorial_relation_payload_contracts",
    "merge_editorial_relation_authority_registries",
]
