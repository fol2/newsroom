from __future__ import annotations

from typing import Any, Callable

from newsroom.authority.canonical import canonical_json_bytes, validate_sha256_digest
from newsroom.authority.models import CommandDefinition
from newsroom.authority.object_policy import merge_authority_registries
from newsroom.authority.policy import (
    CommandRegistry,
    PayloadGoldenVector,
    PayloadSchemaContract,
    PayloadSchemaRegistry,
    PayloadSchemaValidationError,
)
from newsroom.authority.types import PayloadMode, TrustScope, UUIDv4Id, require_token
from newsroom.integrated.policy import merge_integrated_authority_registries
from newsroom.projection.models import ProjectionContractError

from .models import RelationDecisionAction, RelationPredicate, RelationProducerKind, RelationRecordType


INTEGRATED_FIXTURE_V2_BIND_COMMAND = "integrated.fixture.v2.bind"
RELATION_PROPOSAL_COMMAND = "relation.proposal.record"
RELATION_DECISION_COMMAND = "relation.admission.decide"
RELATION_COMMAND_TYPES = frozenset(
    {
        INTEGRATED_FIXTURE_V2_BIND_COMMAND,
        RELATION_PROPOSAL_COMMAND,
        RELATION_DECISION_COMMAND,
    }
)

_FIXTURE_SCHEMA_VERSION = "integrated_fixture_v2_binding_v1"
_PROPOSAL_SCHEMA_VERSION = "governed_relation_proposal_v1"
_DECISION_SCHEMA_VERSION = "governed_relation_decision_v1"
_CONTRACT_VERSION = "governed-relation-contract-v1"
_DEFINITION_VERSION = "governed-relation-command-v1"


def _exact_object(value: Any, *, fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(fields):
        raise PayloadSchemaValidationError(
            f"{name} payload fields differ from retained schema"
        )
    return value


def _canonical_uuid(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise PayloadSchemaValidationError(f"{field} must be canonical UUID text")
    try:
        UUIDv4Id.parse(value)
    except ValueError as exc:
        raise PayloadSchemaValidationError(f"{field} must be canonical UUIDv4") from exc
    return value


def _canonical_digest(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise PayloadSchemaValidationError(f"{field} must be a digest string")
    try:
        normalized = validate_sha256_digest(value, field=field)
    except ValueError as exc:
        raise PayloadSchemaValidationError(f"{field} must be sha256") from exc
    if normalized != value:
        raise PayloadSchemaValidationError(f"{field} must be canonical lowercase")
    return value


def _canonical_token(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise PayloadSchemaValidationError(f"{field} must be a token")
    try:
        require_token(value, field=field)
    except ValueError as exc:
        raise PayloadSchemaValidationError(f"{field} must be a token") from exc
    return value


def _fixture_binding_payload_bytes(value: Any) -> bytes:
    item = _exact_object(
        value,
        fields=frozenset(
            {
                "binding_id",
                "fixture_id",
                "schema_version",
                "fixture_digest",
                "manifest_admission_id",
                "manifest_blob_digest",
                "passage_objects",
            }
        ),
        name="integrated fixture v2 binding",
    )
    _canonical_uuid(item["binding_id"], field="binding_id")
    _canonical_uuid(item["fixture_id"], field="fixture_id")
    if item["schema_version"] != "integrated_fixture_v2":
        raise PayloadSchemaValidationError(
            "fixture binding schema_version must be integrated_fixture_v2"
        )
    fixture_digest = _canonical_digest(
        item["fixture_digest"], field="fixture_digest"
    )
    _canonical_uuid(item["manifest_admission_id"], field="manifest_admission_id")
    manifest_digest = _canonical_digest(
        item["manifest_blob_digest"], field="manifest_blob_digest"
    )
    if fixture_digest != manifest_digest:
        raise PayloadSchemaValidationError(
            "fixture binding manifest digest must equal fixture digest"
        )
    passage_objects = item["passage_objects"]
    if not isinstance(passage_objects, list) or not passage_objects or len(passage_objects) > 32:
        raise PayloadSchemaValidationError(
            "fixture binding passage_objects must be a bounded list"
        )
    passage_ids: list[str] = []
    for passage in passage_objects:
        passage_item = _exact_object(
            passage,
            fields=frozenset({"passage_id", "admission_id", "blob_digest"}),
            name="fixture passage object",
        )
        passage_ids.append(_canonical_token(passage_item["passage_id"], field="passage_id"))
        _canonical_uuid(passage_item["admission_id"], field="passage_admission_id")
        _canonical_digest(passage_item["blob_digest"], field="passage_blob_digest")
    if passage_ids != sorted(set(passage_ids)):
        raise PayloadSchemaValidationError(
            "fixture passage objects must be sorted and unique"
        )
    return canonical_json_bytes(item)


def _relation_proposal_payload_bytes(value: Any) -> bytes:
    item = _exact_object(
        value,
        fields=frozenset(
            {
                "proposal_id",
                "fixture_binding_id",
                "subject",
                "predicate",
                "object",
                "trust_scope",
                "temporal_scope",
                "evidence_passage_ids",
                "producer",
                "statement",
                "uncertainties",
            }
        ),
        name="relation proposal",
    )
    _canonical_uuid(item["proposal_id"], field="proposal_id")
    _canonical_uuid(item["fixture_binding_id"], field="fixture_binding_id")
    for name in ("subject", "object"):
        endpoint = _exact_object(
            item[name],
            fields=frozenset({"record_type", "record_id"}),
            name=f"relation {name}",
        )
        try:
            RelationRecordType(str(endpoint["record_type"]))
        except ValueError as exc:
            raise PayloadSchemaValidationError(
                f"relation {name} type is not allow-listed"
            ) from exc
        _canonical_uuid(endpoint["record_id"], field=f"{name}_record_id")
    try:
        RelationPredicate(str(item["predicate"]))
    except ValueError as exc:
        raise PayloadSchemaValidationError(
            "relation predicate is not allow-listed"
        ) from exc
    if item["trust_scope"] != TrustScope.PROPOSED.value:
        raise PayloadSchemaValidationError(
            "relation proposal trust scope must be PROPOSED"
        )
    temporal = _exact_object(
        item["temporal_scope"],
        fields=frozenset({"valid_from", "valid_until", "precision"}),
        name="relation temporal scope",
    )
    if (
        not isinstance(temporal["valid_from"], str)
        or (
            temporal["valid_until"] is not None
            and not isinstance(temporal["valid_until"], str)
        )
        or temporal["precision"] != "EXACT"
    ):
        raise PayloadSchemaValidationError("relation temporal scope is malformed")
    evidence = item["evidence_passage_ids"]
    if (
        not isinstance(evidence, list)
        or not evidence
        or len(evidence) > 16
        or any(not isinstance(entry, str) for entry in evidence)
        or evidence != sorted(set(evidence))
    ):
        raise PayloadSchemaValidationError(
            "relation evidence passage IDs must be sorted and unique"
        )
    for entry in evidence:
        _canonical_token(entry, field="evidence_passage_id")
    producer = _exact_object(
        item["producer"],
        fields=frozenset(
            {"kind", "producer_id", "producer_version", "rule_version"}
        ),
        name="relation producer",
    )
    try:
        RelationProducerKind(str(producer["kind"]))
    except ValueError as exc:
        raise PayloadSchemaValidationError(
            "relation producer kind is not allow-listed"
        ) from exc
    for field in ("producer_id", "producer_version", "rule_version"):
        _canonical_token(producer[field], field=field)
    if (
        not isinstance(item["statement"], str)
        or not item["statement"]
        or item["statement"] != item["statement"].strip()
        or len(item["statement"].encode("utf-8")) > 4096
    ):
        raise PayloadSchemaValidationError(
            "relation statement must be bounded canonical text"
        )
    uncertainties = item["uncertainties"]
    if (
        not isinstance(uncertainties, list)
        or len(uncertainties) > 16
        or any(
            not isinstance(entry, str)
            or not entry
            or entry != entry.strip()
            for entry in uncertainties
        )
        or uncertainties != sorted(set(uncertainties))
    ):
        raise PayloadSchemaValidationError(
            "relation uncertainties must be sorted canonical text"
        )
    return canonical_json_bytes(item)


def _relation_decision_payload_bytes(value: Any) -> bytes:
    item = _exact_object(
        value,
        fields=frozenset(
            {
                "proposal_id",
                "action",
                "expected_proposal_digest",
                "expected_decision_version",
                "expected_previous_decision_id",
                "reason_code",
                "decision_policy_version",
                "successor_proposal_id",
            }
        ),
        name="relation decision",
    )
    _canonical_uuid(item["proposal_id"], field="proposal_id")
    try:
        action = RelationDecisionAction(str(item["action"]))
    except ValueError as exc:
        raise PayloadSchemaValidationError(
            "relation decision action is not allow-listed"
        ) from exc
    _canonical_digest(
        item["expected_proposal_digest"], field="expected_proposal_digest"
    )
    expected_version = item["expected_decision_version"]
    if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 0:
        raise PayloadSchemaValidationError(
            "expected decision version must be non-negative"
        )
    previous = item["expected_previous_decision_id"]
    if expected_version == 0:
        if previous is not None:
            raise PayloadSchemaValidationError(
                "initial decision cannot name a predecessor"
            )
    else:
        _canonical_uuid(previous, field="expected_previous_decision_id")
    _canonical_token(item["reason_code"], field="reason_code")
    _canonical_token(
        item["decision_policy_version"], field="decision_policy_version"
    )
    successor = item["successor_proposal_id"]
    if action is RelationDecisionAction.SUPERSEDE:
        _canonical_uuid(successor, field="successor_proposal_id")
        if successor == item["proposal_id"]:
            raise PayloadSchemaValidationError(
                "proposal cannot supersede itself"
            )
    elif successor is not None:
        raise PayloadSchemaValidationError(
            "only supersession may name a successor proposal"
        )
    return canonical_json_bytes(item)


def relation_payload_contracts() -> tuple[PayloadSchemaContract, ...]:
    fixture_vector = {
        "binding_id": "00000000-0000-4000-8000-000000002101",
        "fixture_id": "00000000-0000-4000-8000-000000002001",
        "schema_version": "integrated_fixture_v2",
        "fixture_digest": "sha256:" + "a" * 64,
        "manifest_admission_id": "00000000-0000-4000-8000-000000002102",
        "manifest_blob_digest": "sha256:" + "a" * 64,
        "passage_objects": [
            {
                "passage_id": "fixture-passage",
                "admission_id": "00000000-0000-4000-8000-000000002103",
                "blob_digest": "sha256:" + "b" * 64,
            }
        ],
    }
    proposal_vector = {
        "proposal_id": "00000000-0000-4000-8000-000000002104",
        "fixture_binding_id": "00000000-0000-4000-8000-000000002101",
        "subject": {
            "record_type": "EVENT_HYPOTHESIS_VERSION",
            "record_id": "00000000-0000-4000-8000-000000002011",
        },
        "predicate": "DEVELOPMENT_OF",
        "object": {
            "record_type": "EVENT_HYPOTHESIS_VERSION",
            "record_id": "00000000-0000-4000-8000-000000002010",
        },
        "trust_scope": "PROPOSED",
        "temporal_scope": {
            "valid_from": "2042-03-12T10:00:00.000000Z",
            "valid_until": None,
            "precision": "EXACT",
        },
        "evidence_passage_ids": ["fixture-passage"],
        "producer": {
            "kind": "DETERMINISTIC_RULE",
            "producer_id": "newsroom.integrated_fixture_v2",
            "producer_version": "fixture-producer-v1",
            "rule_version": "integrated-fixture-development-rule-v1",
        },
        "statement": "A synthetic material development is proposed.",
        "uncertainties": [],
    }
    decision_vector = {
        "proposal_id": "00000000-0000-4000-8000-000000002104",
        "action": "ADMIT",
        "expected_proposal_digest": "sha256:" + "c" * 64,
        "expected_decision_version": 0,
        "expected_previous_decision_id": None,
        "reason_code": "FIXTURE_RULE_MATCHED",
        "decision_policy_version": "relation-admission-policy-v1",
        "successor_proposal_id": None,
    }
    vectors: tuple[
        tuple[str, str, PayloadMode, Callable[[Any], bytes], dict[str, Any]], ...
    ] = (
        (
            "fixture-binding",
            _FIXTURE_SCHEMA_VERSION,
            PayloadMode.INLINE,
            _fixture_binding_payload_bytes,
            fixture_vector,
        ),
        (
            "relation-proposal",
            _PROPOSAL_SCHEMA_VERSION,
            PayloadMode.INLINE,
            _relation_proposal_payload_bytes,
            proposal_vector,
        ),
        (
            "relation-decision",
            _DECISION_SCHEMA_VERSION,
            PayloadMode.INLINE,
            _relation_decision_payload_bytes,
            decision_vector,
        ),
    )
    contracts: list[PayloadSchemaContract] = []
    for name, schema_version, mode, canonicalizer, vector in vectors:
        contracts.append(
            PayloadSchemaContract(
                schema_version=schema_version,
                payload_mode=mode,
                contract_version=_CONTRACT_VERSION,
                canonicalizer_implementation_version=(
                    f"{schema_version}-canonical-json-v1"
                ),
                canonicalizer=canonicalizer,
                golden_vectors=(
                    PayloadGoldenVector(
                        name=name,
                        input_identity=f"{name}-v1",
                        value=vector,
                        expected_bytes=canonicalizer(vector),
                    ),
                ),
            )
        )
    return tuple(contracts)


def relation_command_definitions() -> tuple[CommandDefinition, ...]:
    contracts = {item.schema_version: item for item in relation_payload_contracts()}

    def definition(
        *,
        command_type: str,
        aggregate_type: str,
        event_type: str,
        schema_version: str,
        trust_scope: TrustScope,
        required_scope: str,
    ) -> CommandDefinition:
        contract = contracts[schema_version]
        return CommandDefinition(
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
            security_scope="authority.relation",
            retention_scope="authority.audit",
            required_scope=required_scope,
            max_inline_bytes=64 * 1024,
        )

    return (
        definition(
            command_type=INTEGRATED_FIXTURE_V2_BIND_COMMAND,
            aggregate_type="integrated_fixture_v2_binding",
            event_type="integrated.fixture.v2.bound",
            schema_version=_FIXTURE_SCHEMA_VERSION,
            trust_scope=TrustScope.OBSERVED,
            required_scope="authority.fixture.v2.bind",
        ),
        definition(
            command_type=RELATION_PROPOSAL_COMMAND,
            aggregate_type="relation_proposal",
            event_type="relation.proposal.recorded",
            schema_version=_PROPOSAL_SCHEMA_VERSION,
            trust_scope=TrustScope.PROPOSED,
            required_scope="authority.relation.propose",
        ),
        definition(
            command_type=RELATION_DECISION_COMMAND,
            aggregate_type="relation_admission",
            event_type="relation.admission.decided",
            schema_version=_DECISION_SCHEMA_VERSION,
            trust_scope=TrustScope.ADMITTED,
            required_scope="authority.relation.admit",
        ),
    )


def merge_relation_authority_registries(
    *,
    command_registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
) -> tuple[CommandRegistry, PayloadSchemaRegistry]:
    object_commands, object_schemas = merge_authority_registries(
        command_registry=command_registry,
        payload_schemas=payload_schemas,
    )
    commands, schemas = merge_integrated_authority_registries(
        command_registry=object_commands,
        payload_schemas=object_schemas,
    )

    definitions = list(commands.definitions())
    by_key = {
        (item.command_type, item.definition_version): item
        for item in definitions
    }
    for item in relation_command_definitions():
        key = (item.command_type, item.definition_version)
        existing = by_key.get(key)
        if existing is not None and existing.digest != item.digest:
            raise ProjectionContractError(
                f"relation command identity conflict: {item.command_type}"
            )
        if existing is None:
            definitions.append(item)
            by_key[key] = item

    current_commands = {
        item.command_type: commands.resolve(item.command_type).definition_version
        for item in definitions
        if item.command_type not in RELATION_COMMAND_TYPES
    }
    current_commands.update(
        {command_type: _DEFINITION_VERSION for command_type in RELATION_COMMAND_TYPES}
    )

    contracts = list(schemas.contracts())
    schema_keys = {
        (item.schema_version, item.payload_mode, item.contract_version): item
        for item in contracts
    }
    relation_contracts = relation_payload_contracts()
    for item in relation_contracts:
        key = (item.schema_version, item.payload_mode, item.contract_version)
        existing = schema_keys.get(key)
        if existing is not None and existing.contract_digest != item.contract_digest:
            raise ProjectionContractError(
                f"relation payload identity conflict: {item.schema_version}"
            )
        if existing is None:
            contracts.append(item)
            schema_keys[key] = item

    relation_schema_versions = {item.schema_version for item in relation_contracts}
    current_schemas: dict[tuple[str, PayloadMode], str] = {}
    for schema_version, mode in {
        (item.schema_version, item.payload_mode) for item in contracts
    }:
        if schema_version in relation_schema_versions:
            current_schemas[(schema_version, mode)] = _CONTRACT_VERSION
        else:
            current_schemas[(schema_version, mode)] = schemas.resolve(
                schema_version, mode
            ).contract_version

    return (
        CommandRegistry(definitions, current_versions=current_commands),
        PayloadSchemaRegistry(contracts, current_versions=current_schemas),
    )


__all__ = [
    "INTEGRATED_FIXTURE_V2_BIND_COMMAND",
    "RELATION_COMMAND_TYPES",
    "RELATION_DECISION_COMMAND",
    "RELATION_PROPOSAL_COMMAND",
    "merge_relation_authority_registries",
    "relation_command_definitions",
    "relation_payload_contracts",
]
