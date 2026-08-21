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
from newsroom.authority.types import PayloadMode, TrustScope
from newsroom.extraction.fixtures import deterministic_fixture_contract_request
from newsroom.extraction.types import (
    ExtractionOutputId,
    ExtractionRunId,
    ExtractionRunVersionId,
    ExtractorContractId,
    FixtureExtractionCase,
    ProposalSetId,
    VersionedExtractionComponent,
)
from newsroom.relations.editorial_policy import (
    merge_editorial_relation_authority_registries,
)

from .contracts import qualification_configuration
from .models import (
    GraphitiAdapterConfiguration,
    GraphitiReplayApprovalRequest,
    GraphitiWorkspacePolicy,
    RealGraphitiRuntimeAuthority,
)
from .types import (
    GraphitiAdapterConfigurationId,
    GraphitiAttemptId,
    GraphitiCleanupReceiptId,
    GraphitiCredentialClass,
    GraphitiEgressPolicy,
    GraphitiExecutionProfile,
    GraphitiInputManifestId,
    GraphitiReplayEligibility,
    GraphitiReplaySourceId,
    GraphitiRuntimeMode,
    GraphitiWorkspaceId,
    GraphitiWorkspacePolicyId,
)
from .temporal_vocabulary import parse_temporal_basis

GRAPHITI_CONFIGURATION_REGISTER_COMMAND = "graphiti.adapter.configuration.register"
GRAPHITI_ATTEMPT_EXECUTE_COMMAND = "graphiti.adapter.attempt.execute"
GRAPHITI_REPLAY_APPROVE_COMMAND = "graphiti.adapter.replay.approve"
GRAPHITI_ADAPTER_COMMAND_TYPES = frozenset(
    {
        GRAPHITI_CONFIGURATION_REGISTER_COMMAND,
        GRAPHITI_ATTEMPT_EXECUTE_COMMAND,
        GRAPHITI_REPLAY_APPROVE_COMMAND,
    }
)

_CONFIGURATION_SCHEMA = "graphiti_adapter_configuration_v1"
_ATTEMPT_SCHEMA = "graphiti_adapter_attempt_v1"
_REPLAY_SCHEMA = "graphiti_adapter_replay_approval_v1"
_CONTRACT_VERSION = "graphiti-proposal-adapter-authority-contract-v1"
_DEFINITION_VERSION = "graphiti-proposal-adapter-authority-command-v1"


def _object(value: Any, *, field: str, keys: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or frozenset(value) != keys:
        raise PayloadSchemaValidationError(f"{field} has an invalid exact field set")
    return value


def _string(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise PayloadSchemaValidationError(f"{field} must be text")
    return value


def _integer(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PayloadSchemaValidationError(f"{field} must be an integer")
    return value


def _boolean(value: Any, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise PayloadSchemaValidationError(f"{field} must be boolean")
    return value


def _required_id(value: Any, parser: Callable[[str], Any], *, field: str) -> Any:
    if not isinstance(value, str):
        raise PayloadSchemaValidationError(f"{field} must be text")
    try:
        return parser(value)
    except (TypeError, ValueError) as exc:
        raise PayloadSchemaValidationError(f"{field} is invalid") from exc


def _optional_id(value: Any, parser: Callable[[str], Any], *, field: str) -> Any:
    if value is None:
        return None
    return _required_id(value, parser, field=field)


def _digest(value: Any, *, field: str) -> str:
    text = _string(value, field=field)
    if len(text) != 71 or not text.startswith("sha256:"):
        raise PayloadSchemaValidationError(f"{field} must be a sha256 digest")
    try:
        int(text[7:], 16)
    except ValueError as exc:
        raise PayloadSchemaValidationError(f"{field} must be a sha256 digest") from exc
    if text.lower() != text:
        raise PayloadSchemaValidationError(f"{field} must be lowercase")
    return text


def _component(value: Any, *, field: str) -> VersionedExtractionComponent:
    item = _object(
        value,
        field=field,
        keys=frozenset({"component_id", "component_version", "contract_digest"}),
    )
    try:
        return VersionedExtractionComponent(
            component_id=_string(item["component_id"], field=f"{field}.component_id"),
            component_version=_string(
                item["component_version"], field=f"{field}.component_version"
            ),
            contract_digest=_digest(
                item["contract_digest"], field=f"{field}.contract_digest"
            ),
        )
    except (TypeError, ValueError) as exc:
        raise PayloadSchemaValidationError(f"{field} is invalid") from exc


def _workspace_policy(value: Any) -> GraphitiWorkspacePolicy:
    item = _object(
        value,
        field="workspace_policy",
        keys=frozenset(
            {
                "policy_id",
                "policy_version",
                "namespace_prefix",
                "max_workspace_bytes",
                "max_private_nodes",
                "max_private_relations",
                "egress_policy",
                "credential_class",
                "cleanup_required",
                "persistent_state_allowed",
            }
        ),
    )
    try:
        return GraphitiWorkspacePolicy(
            policy_id=_required_id(
                item["policy_id"],
                GraphitiWorkspacePolicyId.parse,
                field="workspace_policy.policy_id",
            ),
            policy_version=_string(
                item["policy_version"], field="workspace_policy.policy_version"
            ),
            namespace_prefix=_string(
                item["namespace_prefix"], field="workspace_policy.namespace_prefix"
            ),
            max_workspace_bytes=_integer(
                item["max_workspace_bytes"], field="workspace_policy.max_workspace_bytes"
            ),
            max_private_nodes=_integer(
                item["max_private_nodes"], field="workspace_policy.max_private_nodes"
            ),
            max_private_relations=_integer(
                item["max_private_relations"],
                field="workspace_policy.max_private_relations",
            ),
            egress_policy=GraphitiEgressPolicy(
                _string(item["egress_policy"], field="workspace_policy.egress_policy")
            ),
            credential_class=GraphitiCredentialClass(
                _string(
                    item["credential_class"],
                    field="workspace_policy.credential_class",
                )
            ),
            cleanup_required=_boolean(
                item["cleanup_required"], field="workspace_policy.cleanup_required"
            ),
            persistent_state_allowed=_boolean(
                item["persistent_state_allowed"],
                field="workspace_policy.persistent_state_allowed",
            ),
        )
    except (TypeError, ValueError) as exc:
        raise PayloadSchemaValidationError("workspace_policy is invalid") from exc


def _runtime_authority(value: Any) -> RealGraphitiRuntimeAuthority | None:
    if value is None:
        return None
    keys = frozenset(
        {
            "authority_decision_digest",
            "framework_release",
            "model_release",
            "embedding_release",
            "destination_contract_digest",
            "data_processing_terms_digest",
            "prompt_contract_digest",
            "output_schema_contract_digest",
            "permitted_expression_digest",
            "rights_privacy_retention_digest",
            "workspace_security_digest",
            "egress_credential_digest",
            "budget_digest",
            "evaluation_plan_digest",
            "rollback_digest",
        }
    )
    item = _object(value, field="real_runtime_authority", keys=keys)
    try:
        return RealGraphitiRuntimeAuthority(
            authority_decision_digest=_digest(
                item["authority_decision_digest"],
                field="real_runtime_authority.authority_decision_digest",
            ),
            framework_release=_string(
                item["framework_release"],
                field="real_runtime_authority.framework_release",
            ),
            model_release=_string(
                item["model_release"], field="real_runtime_authority.model_release"
            ),
            embedding_release=_string(
                item["embedding_release"],
                field="real_runtime_authority.embedding_release",
            ),
            destination_contract_digest=_digest(
                item["destination_contract_digest"],
                field="real_runtime_authority.destination_contract_digest",
            ),
            data_processing_terms_digest=_digest(
                item["data_processing_terms_digest"],
                field="real_runtime_authority.data_processing_terms_digest",
            ),
            prompt_contract_digest=_digest(
                item["prompt_contract_digest"],
                field="real_runtime_authority.prompt_contract_digest",
            ),
            output_schema_contract_digest=_digest(
                item["output_schema_contract_digest"],
                field="real_runtime_authority.output_schema_contract_digest",
            ),
            permitted_expression_digest=_digest(
                item["permitted_expression_digest"],
                field="real_runtime_authority.permitted_expression_digest",
            ),
            rights_privacy_retention_digest=_digest(
                item["rights_privacy_retention_digest"],
                field="real_runtime_authority.rights_privacy_retention_digest",
            ),
            workspace_security_digest=_digest(
                item["workspace_security_digest"],
                field="real_runtime_authority.workspace_security_digest",
            ),
            egress_credential_digest=_digest(
                item["egress_credential_digest"],
                field="real_runtime_authority.egress_credential_digest",
            ),
            budget_digest=_digest(
                item["budget_digest"], field="real_runtime_authority.budget_digest"
            ),
            evaluation_plan_digest=_digest(
                item["evaluation_plan_digest"],
                field="real_runtime_authority.evaluation_plan_digest",
            ),
            rollback_digest=_digest(
                item["rollback_digest"],
                field="real_runtime_authority.rollback_digest",
            ),
        )
    except (TypeError, ValueError) as exc:
        raise PayloadSchemaValidationError("real_runtime_authority is invalid") from exc


def _configuration_payload(value: Any) -> bytes:
    keys = frozenset(
        {
            "configuration_id",
            "runtime_mode",
            "execution_profile",
            "framework",
            "model",
            "embedding",
            "prompt",
            "output_schema",
            "code",
            "normalisation",
            "temporal_policy",
            "adapter_policy",
            "extractor_contract_id",
            "extractor_contract_digest",
            "workspace_policy",
            "fixture_case",
            "real_runtime_authority",
        }
    )
    item = _object(value, field="graphiti_adapter_configuration", keys=keys)
    try:
        fixture_case = (
            None
            if item["fixture_case"] is None
            else FixtureExtractionCase(
                _string(item["fixture_case"], field="fixture_case")
            )
        )
        configuration = GraphitiAdapterConfiguration(
            configuration_id=_required_id(
                item["configuration_id"],
                GraphitiAdapterConfigurationId.parse,
                field="configuration_id",
            ),
            runtime_mode=GraphitiRuntimeMode(
                _string(item["runtime_mode"], field="runtime_mode")
            ),
            execution_profile=GraphitiExecutionProfile(
                _string(item["execution_profile"], field="execution_profile")
            ),
            framework=_component(item["framework"], field="framework"),
            model=_component(item["model"], field="model"),
            embedding=_component(item["embedding"], field="embedding"),
            prompt=_component(item["prompt"], field="prompt"),
            output_schema=_component(item["output_schema"], field="output_schema"),
            code=_component(item["code"], field="code"),
            normalisation=_component(item["normalisation"], field="normalisation"),
            temporal_policy=_component(
                item["temporal_policy"], field="temporal_policy"
            ),
            adapter_policy=_component(item["adapter_policy"], field="adapter_policy"),
            extractor_contract_id=_required_id(
                item["extractor_contract_id"],
                ExtractorContractId.parse,
                field="extractor_contract_id",
            ),
            extractor_contract_digest=_digest(
                item["extractor_contract_digest"],
                field="extractor_contract_digest",
            ),
            workspace_policy=_workspace_policy(item["workspace_policy"]),
            fixture_case=fixture_case,
            real_runtime_authority=_runtime_authority(
                item["real_runtime_authority"]
            ),
            idempotency_key="payload-validation-only",
        )
    except PayloadSchemaValidationError:
        raise
    except (TypeError, ValueError) as exc:
        raise PayloadSchemaValidationError(
            f"graphiti_adapter_configuration is invalid: {exc}"
        ) from exc
    canonical = configuration.canonical_value()
    if canonical != item:
        raise PayloadSchemaValidationError(
            "graphiti_adapter_configuration is not canonical"
        )
    return canonical_json_bytes(canonical)


def _attempt_payload(value: Any) -> bytes:
    keys = frozenset(
        {
            "attempt_id",
            "attempt_number",
            "expected_previous_attempt_id",
            "configuration_id",
            "configuration_digest",
            "workspace_id",
            "cleanup_receipt_id",
            "manifest_id",
            "manifest_digest",
            "extractor_contract_id",
            "extractor_contract_digest",
            "run_id",
            "requested_run_version_id",
            "requested_version_number",
            "replay_source_id",
            "replay_source_digest",
            "reference_time",
            "temporal_basis",
            "episode_uuid",
            "generation_id",
            "predecessor_episode_uuid",
        }
    )
    item = _object(value, field="graphiti_adapter_attempt", keys=keys)
    attempt_number = _integer(item["attempt_number"], field="attempt_number")
    if attempt_number <= 0 or attempt_number > 1_000_000:
        raise PayloadSchemaValidationError("attempt_number is outside its bound")
    previous = _optional_id(
        item["expected_previous_attempt_id"],
        GraphitiAttemptId.parse,
        field="expected_previous_attempt_id",
    )
    if (attempt_number == 1) != (previous is None):
        raise PayloadSchemaValidationError(
            "attempt predecessor does not match attempt number"
        )
    for field, parser in (
        ("attempt_id", GraphitiAttemptId.parse),
        ("configuration_id", GraphitiAdapterConfigurationId.parse),
        ("workspace_id", GraphitiWorkspaceId.parse),
        ("cleanup_receipt_id", GraphitiCleanupReceiptId.parse),
        ("manifest_id", GraphitiInputManifestId.parse),
        ("extractor_contract_id", ExtractorContractId.parse),
        ("run_id", ExtractionRunId.parse),
        ("requested_run_version_id", ExtractionRunVersionId.parse),
    ):
        _required_id(item[field], parser, field=field)
    version_number = _integer(
        item["requested_version_number"], field="requested_version_number"
    )
    if version_number <= 0 or version_number > 1_000_000:
        raise PayloadSchemaValidationError(
            "requested_version_number is outside its bound"
        )
    for field in (
        "configuration_digest",
        "manifest_digest",
        "extractor_contract_digest",
    ):
        _digest(item[field], field=field)
    replay_id = _optional_id(
        item["replay_source_id"],
        GraphitiReplaySourceId.parse,
        field="replay_source_id",
    )
    replay_digest = item["replay_source_digest"]
    if replay_id is None:
        if replay_digest is not None:
            raise PayloadSchemaValidationError(
                "replay source digest requires replay source identity"
            )
    else:
        _digest(replay_digest, field="replay_source_digest")
    basis = _string(item["temporal_basis"], field="temporal_basis")
    try:
        parse_temporal_basis(basis)
    except ValueError as exc:
        raise PayloadSchemaValidationError(
            "temporal_basis must be a labelled mapping"
        ) from exc

    reference_time = item["reference_time"]
    if reference_time is not None:
        _string(reference_time, field="reference_time")
    episode_uuid = item["episode_uuid"]
    if episode_uuid is not None:
        _string(episode_uuid, field="episode_uuid")
    predecessor_episode_uuid = item["predecessor_episode_uuid"]
    if predecessor_episode_uuid is not None:
        _string(predecessor_episode_uuid, field="predecessor_episode_uuid")
        if predecessor_episode_uuid == episode_uuid:
            raise PayloadSchemaValidationError(
                "episode predecessor cannot name the current episode"
            )
    _string(item["generation_id"], field="generation_id")
    return canonical_json_bytes(item)


def _replay_payload(value: Any) -> bytes:
    keys = frozenset(
        {
            "replay_source_id",
            "source_attempt_id",
            "source_run_version_id",
            "source_output_id",
            "source_proposal_set_id",
            "eligibility",
            "expected_output_canonical_digest",
            "expected_proposal_set_canonical_digest",
            "expected_replay_payload_digest",
        }
    )
    item = _object(value, field="graphiti_replay_approval", keys=keys)
    try:
        request = GraphitiReplayApprovalRequest(
            replay_source_id=_required_id(
                item["replay_source_id"],
                GraphitiReplaySourceId.parse,
                field="replay_source_id",
            ),
            source_attempt_id=_required_id(
                item["source_attempt_id"],
                GraphitiAttemptId.parse,
                field="source_attempt_id",
            ),
            source_run_version_id=_required_id(
                item["source_run_version_id"],
                ExtractionRunVersionId.parse,
                field="source_run_version_id",
            ),
            source_output_id=_required_id(
                item["source_output_id"],
                ExtractionOutputId.parse,
                field="source_output_id",
            ),
            source_proposal_set_id=_optional_id(
                item["source_proposal_set_id"],
                ProposalSetId.parse,
                field="source_proposal_set_id",
            ),
            eligibility=GraphitiReplayEligibility(
                _string(item["eligibility"], field="eligibility")
            ),
            expected_output_canonical_digest=_digest(
                item["expected_output_canonical_digest"],
                field="expected_output_canonical_digest",
            ),
            expected_proposal_set_canonical_digest=(
                None
                if item["expected_proposal_set_canonical_digest"] is None
                else _digest(
                    item["expected_proposal_set_canonical_digest"],
                    field="expected_proposal_set_canonical_digest",
                )
            ),
            expected_replay_payload_digest=_digest(
                item["expected_replay_payload_digest"],
                field="expected_replay_payload_digest",
            ),
            idempotency_key="payload-validation-only",
        )
    except PayloadSchemaValidationError:
        raise
    except (TypeError, ValueError) as exc:
        raise PayloadSchemaValidationError(
            f"graphiti_replay_approval is invalid: {exc}"
        ) from exc
    canonical = request.canonical_value()
    if canonical != item:
        raise PayloadSchemaValidationError("graphiti_replay_approval is not canonical")
    return canonical_json_bytes(canonical)


def _golden_configuration() -> GraphitiAdapterConfiguration:
    return qualification_configuration(
        configuration_id=GraphitiAdapterConfigurationId.parse(
            "00000000-0000-4000-8000-000000004811"
        ),
        contract=deterministic_fixture_contract_request(
            contract_id=ExtractorContractId.parse(
                "00000000-0000-4000-8000-000000004040"
            )
        ),
        fixture_case=FixtureExtractionCase.BILINGUAL_COMPLETE,
    )


def _golden_attempt_value() -> dict[str, object]:
    digest_value = "sha256:" + "1" * 64
    return {
        "attempt_id": "00000000-0000-4000-8000-000000004812",
        "attempt_number": 1,
        "expected_previous_attempt_id": None,
        "configuration_id": "00000000-0000-4000-8000-000000004811",
        "configuration_digest": digest_value,
        "workspace_id": "00000000-0000-4000-8000-000000004813",
        "cleanup_receipt_id": "00000000-0000-4000-8000-000000004814",
        "manifest_id": "00000000-0000-4000-8000-000000004815",
        "manifest_digest": "sha256:" + "2" * 64,
        "extractor_contract_id": "00000000-0000-4000-8000-000000004040",
        "extractor_contract_digest": "sha256:" + "3" * 64,
        "run_id": "00000000-0000-4000-8000-000000004816",
        "requested_run_version_id": "00000000-0000-4000-8000-000000004817",
        "requested_version_number": 1,
        "replay_source_id": None,
        "replay_source_digest": None,
        "reference_time": None,
        "temporal_basis": "UNSET",
        "episode_uuid": None,
        "generation_id": "",
        "predecessor_episode_uuid": None,
    }


def _golden_replay_request() -> GraphitiReplayApprovalRequest:
    return GraphitiReplayApprovalRequest(
        replay_source_id=GraphitiReplaySourceId.parse(
            "00000000-0000-4000-8000-000000004818"
        ),
        source_attempt_id=GraphitiAttemptId.parse(
            "00000000-0000-4000-8000-000000004812"
        ),
        source_run_version_id=ExtractionRunVersionId.parse(
            "00000000-0000-4000-8000-000000004817"
        ),
        source_output_id=ExtractionOutputId.parse(
            "00000000-0000-4000-8000-000000004819"
        ),
        source_proposal_set_id=ProposalSetId.parse(
            "00000000-0000-4000-8000-000000004820"
        ),
        eligibility=GraphitiReplayEligibility.COMPLETE,
        expected_output_canonical_digest="sha256:" + "4" * 64,
        expected_proposal_set_canonical_digest="sha256:" + "5" * 64,
        expected_replay_payload_digest="sha256:" + "6" * 64,
        idempotency_key="increment-4d-replay-approval-golden-v1",
    )


def graphiti_adapter_payload_contracts() -> tuple[PayloadSchemaContract, ...]:
    configuration = _golden_configuration()
    attempt = _golden_attempt_value()
    replay = _golden_replay_request()
    specifications = (
        (
            _CONFIGURATION_SCHEMA,
            "configuration",
            _configuration_payload,
            configuration.canonical_value(),
            configuration.canonical_bytes,
        ),
        (
            _ATTEMPT_SCHEMA,
            "attempt",
            _attempt_payload,
            attempt,
            canonical_json_bytes(attempt),
        ),
        (
            _REPLAY_SCHEMA,
            "replay-approval",
            _replay_payload,
            replay.canonical_value(),
            replay.canonical_bytes,
        ),
    )
    return tuple(
        PayloadSchemaContract(
            schema_version=schema_version,
            payload_mode=PayloadMode.INLINE,
            contract_version=_CONTRACT_VERSION,
            canonicalizer_implementation_version=(
                f"graphiti-adapter-{name}-typed-exact-canonical-json-v1"
            ),
            canonicalizer=canonicalizer,
            golden_vectors=(
                PayloadGoldenVector(
                    name=f"graphiti-adapter-{name}-exact-fields",
                    input_identity=f"increment-4d-{name}-golden-v1",
                    value=value,
                    expected_bytes=expected_bytes,
                ),
            ),
        )
        for schema_version, name, canonicalizer, value, expected_bytes in specifications
    )


def graphiti_adapter_command_definitions() -> tuple[CommandDefinition, ...]:
    contracts = {
        item.schema_version: item for item in graphiti_adapter_payload_contracts()
    }
    specifications = (
        (
            GRAPHITI_CONFIGURATION_REGISTER_COMMAND,
            "graphiti_adapter_configuration",
            "graphiti.adapter.configuration.registered",
            _CONFIGURATION_SCHEMA,
            TrustScope.ADMITTED,
            "authority.graphiti.configuration",
        ),
        (
            GRAPHITI_ATTEMPT_EXECUTE_COMMAND,
            "graphiti_adapter_attempt",
            "graphiti.adapter.attempt.executed",
            _ATTEMPT_SCHEMA,
            TrustScope.PROPOSED,
            "authority.graphiti.execute",
        ),
        (
            GRAPHITI_REPLAY_APPROVE_COMMAND,
            "graphiti_replay_source",
            "graphiti.adapter.replay.approved",
            _REPLAY_SCHEMA,
            TrustScope.ADMITTED,
            "authority.graphiti.replay.approve",
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
            security_scope="authority.graphiti_adapter",
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


def merge_graphiti_adapter_authority_registries(
    *,
    command_registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
) -> tuple[CommandRegistry, PayloadSchemaRegistry]:
    prior_registry, prior_schemas = merge_editorial_relation_authority_registries(
        command_registry=command_registry,
        payload_schemas=payload_schemas,
    )
    definitions = list(prior_registry.definitions())
    by_key = {(item.command_type, item.definition_version): item for item in definitions}
    for definition in graphiti_adapter_command_definitions():
        key = (definition.command_type, definition.definition_version)
        existing = by_key.get(key)
        if existing is not None and existing.digest != definition.digest:
            raise ValueError(
                f"Graphiti adapter command identity conflict: {definition.command_type}"
            )
        if existing is None:
            definitions.append(definition)
            by_key[key] = definition
    current_commands = {
        item.command_type: prior_registry.resolve(item.command_type).definition_version
        for item in definitions
        if item.command_type not in GRAPHITI_ADAPTER_COMMAND_TYPES
    }
    current_commands.update(
        {
            command_type: _DEFINITION_VERSION
            for command_type in GRAPHITI_ADAPTER_COMMAND_TYPES
        }
    )

    contracts = list(prior_schemas.contracts())
    by_schema = {
        (item.schema_version, item.payload_mode, item.contract_version): item
        for item in contracts
    }
    additions = graphiti_adapter_payload_contracts()
    for contract in additions:
        key = (contract.schema_version, contract.payload_mode, contract.contract_version)
        existing = by_schema.get(key)
        if existing is not None and existing.contract_digest != contract.contract_digest:
            raise ValueError(
                f"Graphiti adapter payload identity conflict: {contract.schema_version}"
            )
        if existing is None:
            contracts.append(contract)
            by_schema[key] = contract
    adapter_versions = {item.schema_version for item in additions}
    current_schemas: dict[tuple[str, PayloadMode], str] = {}
    for schema_version, mode in {
        (item.schema_version, item.payload_mode) for item in contracts
    }:
        if schema_version in adapter_versions:
            current_schemas[(schema_version, mode)] = _CONTRACT_VERSION
        else:
            current_schemas[(schema_version, mode)] = prior_schemas.resolve(
                schema_version, mode
            ).contract_version
    return (
        CommandRegistry(definitions, current_versions=current_commands),
        PayloadSchemaRegistry(contracts, current_versions=current_schemas),
    )


__all__ = [
    "GRAPHITI_ADAPTER_COMMAND_TYPES",
    "GRAPHITI_ATTEMPT_EXECUTE_COMMAND",
    "GRAPHITI_CONFIGURATION_REGISTER_COMMAND",
    "GRAPHITI_REPLAY_APPROVE_COMMAND",
    "graphiti_adapter_command_definitions",
    "graphiti_adapter_payload_contracts",
    "merge_graphiti_adapter_authority_registries",
]
