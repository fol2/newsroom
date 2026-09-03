from __future__ import annotations

from typing import Any

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.models import CommandDefinition
from newsroom.authority.objects import ObjectAccessDecisionId
from newsroom.authority.policy import (
    CommandRegistry,
    PayloadGoldenVector,
    PayloadSchemaContract,
    PayloadSchemaRegistry,
    PayloadSchemaValidationError,
)
from newsroom.authority.types import ObjectAdmissionId, PayloadMode, TrustScope
from newsroom.sources import (
    DiscoveryRepresentationId,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceItemId,
    SourceRevisionId,
)

from .fixtures import (
    FIXTURE_EN_LANGUAGE,
    FIXTURE_EN_TEXT,
    FIXTURE_ZH_HK_LANGUAGE,
    FIXTURE_ZH_HK_TEXT,
    deterministic_fixture_contract_request,
)
from .models import (
    ExtractionInputBinding,
    ExtractionPassageInput,
    ExtractionRunRequest,
)
from .types import (
    ExtractionBudget,
    ExtractionPassageId,
    ExtractionRunId,
    ExtractionRunVersionId,
    ExtractorContractId,
)

EXTRACTOR_CONTRACT_REGISTER_COMMAND = "extraction.contract.register"
EXTRACTION_RUN_EXECUTE_COMMAND = "extraction.run.execute"
EXTRACTION_COMMAND_TYPES = frozenset(
    {EXTRACTOR_CONTRACT_REGISTER_COMMAND, EXTRACTION_RUN_EXECUTE_COMMAND}
)

_CONTRACT_SCHEMA = "extractor_contract_v1"
_RUN_SCHEMA = "extraction_run_execution_v1"
_CONTRACT_VERSION = "extraction-authority-contract-v1"
_DEFINITION_VERSION = "extraction-authority-command-v1"


def _object(value: Any, *, field: str, keys: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or frozenset(value) != keys:
        raise PayloadSchemaValidationError(f"{field} has an invalid exact field set")
    return value


def _text(value: Any, *, field: str, maximum: int = 4096) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not value
        or len(value.encode("utf-8")) > maximum
    ):
        raise PayloadSchemaValidationError(f"{field} is invalid canonical text")
    return value


def _integer(value: Any, *, field: str, minimum: int, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > maximum
    ):
        raise PayloadSchemaValidationError(f"{field} is outside its fixed bound")
    return value


def _component(value: Any, *, field: str) -> None:
    item = _object(
        value,
        field=field,
        keys=frozenset({"component_id", "component_version", "contract_digest"}),
    )
    _text(item["component_id"], field=f"{field}.component_id", maximum=128)
    _text(item["component_version"], field=f"{field}.component_version", maximum=128)
    digest = _text(item["contract_digest"], field=f"{field}.contract_digest", maximum=71)
    if not digest.startswith("sha256:") or len(digest) != 71:
        raise PayloadSchemaValidationError(f"{field}.contract_digest is invalid")


def _contract_payload(value: Any) -> bytes:
    item = _object(
        value,
        field="extractor_contract",
        keys=frozenset(
            {
                "contract_id",
                "framework",
                "model",
                "prompt",
                "output_schema",
                "code",
                "normalisation",
                "policy",
                "execution_profile",
                "producer_kind",
            }
        ),
    )
    _text(item["contract_id"], field="contract_id", maximum=36)
    for field in (
        "framework",
        "model",
        "prompt",
        "output_schema",
        "code",
        "normalisation",
        "policy",
    ):
        _component(item[field], field=field)
    if item["execution_profile"] != "FIXTURE_REPLAY_ONLY":
        raise PayloadSchemaValidationError("real extraction profile is not authorised")
    if item["producer_kind"] not in {
        "DETERMINISTIC_FIXTURE",
        "GRAPHITI_EVALUATION",
    }:
        raise PayloadSchemaValidationError("extractor producer is not authorised")
    return canonical_json_bytes(item)


def _run_payload(value: Any) -> bytes:
    item = _object(
        value,
        field="extraction_run",
        keys=frozenset(
            {
                "run_id",
                "run_version_id",
                "version_number",
                "expected_previous_version_id",
                "contract_id",
                "input_binding",
                "budget",
            }
        ),
    )
    for field in ("run_id", "run_version_id", "contract_id"):
        _text(item[field], field=field, maximum=36)
    version = _integer(
        item["version_number"], field="version_number", minimum=1, maximum=1_000_000
    )
    previous = item["expected_previous_version_id"]
    if version == 1:
        if previous is not None:
            raise PayloadSchemaValidationError("initial run version cannot have predecessor")
    else:
        _text(previous, field="expected_previous_version_id", maximum=36)
    budget = _object(
        item["budget"],
        field="budget",
        keys=frozenset(
            {
                "timeout_ms",
                "max_input_bytes",
                "max_output_bytes",
                "max_proposals",
                "max_evidence_ranges",
                "max_request_tokens",
                "max_response_tokens",
                "max_cost_microunits",
            }
        ),
    )
    bounds = {
        "timeout_ms": (1, 300_000),
        "max_input_bytes": (1, 16 * 1024 * 1024),
        "max_output_bytes": (1, 4 * 1024 * 1024),
        "max_proposals": (1, 10_000),
        "max_evidence_ranges": (1, 100_000),
        "max_request_tokens": (0, 10_000_000),
        "max_response_tokens": (0, 10_000_000),
        "max_cost_microunits": (0, 10_000_000_000),
    }
    for field, (minimum, maximum) in bounds.items():
        _integer(budget[field], field=f"budget.{field}", minimum=minimum, maximum=maximum)
    binding = _object(
        item["input_binding"],
        field="input_binding",
        keys=frozenset(
            {
                "definition_id",
                "definition_version_id",
                "item_id",
                "revision_id",
                "representation_id",
                "passages",
            }
        ),
    )
    for field in (
        "definition_id",
        "definition_version_id",
        "item_id",
        "revision_id",
        "representation_id",
    ):
        _text(binding[field], field=f"input_binding.{field}", maximum=36)
    passages = binding["passages"]
    if not isinstance(passages, list) or not passages or len(passages) > 128:
        raise PayloadSchemaValidationError("input passages are outside their bound")
    passage_ids: list[str] = []
    for index, passage in enumerate(passages):
        p = _object(
            passage,
            field=f"passages[{index}]",
            keys=frozenset(
                {
                    "passage_id",
                    "admission_id",
                    "access_decision_id",
                    "hydration_policy_contract_digest",
                    "principal_id",
                    "authority_domain",
                    "purpose",
                    "object_class",
                    "allowed_use",
                    "security_scope",
                    "retention_scope",
                    "byte_offset",
                    "byte_length",
                    "blob_digest",
                    "text_digest",
                    "language",
                }
            ),
        )
        passage_id = _text(p["passage_id"], field="passage_id", maximum=36)
        passage_ids.append(passage_id)
        for field in ("admission_id", "access_decision_id"):
            _text(p[field], field=field, maximum=36)
        for field in (
            "hydration_policy_contract_digest",
            "blob_digest",
            "text_digest",
        ):
            digest = _text(p[field], field=field, maximum=71)
            if not digest.startswith("sha256:") or len(digest) != 71:
                raise PayloadSchemaValidationError(f"{field} is invalid")
        for field in (
            "principal_id",
            "authority_domain",
            "purpose",
            "object_class",
            "allowed_use",
            "security_scope",
            "retention_scope",
            "language",
        ):
            _text(p[field], field=field, maximum=256)
        if p["byte_offset"] != 0:
            raise PayloadSchemaValidationError("fixture passage must start at byte zero")
        _integer(
            p["byte_length"],
            field="byte_length",
            minimum=1,
            maximum=16 * 1024 * 1024,
        )
    if passage_ids != sorted(set(passage_ids)):
        raise PayloadSchemaValidationError("passages must be sorted and unique")
    return canonical_json_bytes(item)


def _golden_contract():
    return deterministic_fixture_contract_request(
        contract_id=ExtractorContractId.parse(
            "00000000-0000-4000-8000-000000004011"
        )
    )


def _golden_run() -> ExtractionRunRequest:
    en_bytes = FIXTURE_EN_TEXT.encode("utf-8")
    zh_bytes = FIXTURE_ZH_HK_TEXT.encode("utf-8")
    passages = (
        ExtractionPassageInput(
            passage_id=ExtractionPassageId.parse(
                "00000000-0000-4000-8000-000000004021"
            ),
            admission_id=ObjectAdmissionId.parse(
                "00000000-0000-4000-8000-000000004022"
            ),
            access_decision_id=ObjectAccessDecisionId.parse(
                "00000000-0000-4000-8000-000000004023"
            ),
            hydration_policy_contract_digest="sha256:" + "1" * 64,
            principal_id="principal.alpha",
            authority_domain="newsroom.authority",
            purpose="project.discovery",
            object_class="fixture_document",
            allowed_use="discovery.fixture",
            security_scope="authority.fixture",
            retention_scope="authority.audit",
            byte_offset=0,
            byte_length=len(en_bytes),
            blob_digest=digest_bytes(en_bytes),
            text_digest=digest_bytes(en_bytes),
            language=FIXTURE_EN_LANGUAGE,
            text=FIXTURE_EN_TEXT,
        ),
        ExtractionPassageInput(
            passage_id=ExtractionPassageId.parse(
                "00000000-0000-4000-8000-000000004024"
            ),
            admission_id=ObjectAdmissionId.parse(
                "00000000-0000-4000-8000-000000004025"
            ),
            access_decision_id=ObjectAccessDecisionId.parse(
                "00000000-0000-4000-8000-000000004026"
            ),
            hydration_policy_contract_digest="sha256:" + "2" * 64,
            principal_id="principal.alpha",
            authority_domain="newsroom.authority",
            purpose="project.discovery",
            object_class="fixture_document",
            allowed_use="discovery.fixture",
            security_scope="authority.fixture",
            retention_scope="authority.audit",
            byte_offset=0,
            byte_length=len(zh_bytes),
            blob_digest=digest_bytes(zh_bytes),
            text_digest=digest_bytes(zh_bytes),
            language=FIXTURE_ZH_HK_LANGUAGE,
            text=FIXTURE_ZH_HK_TEXT,
        ),
    )
    return ExtractionRunRequest(
        run_id=ExtractionRunId.parse(
            "00000000-0000-4000-8000-000000004031"
        ),
        run_version_id=ExtractionRunVersionId.parse(
            "00000000-0000-4000-8000-000000004032"
        ),
        version_number=1,
        expected_previous_version_id=None,
        contract_id=ExtractorContractId.parse(
            "00000000-0000-4000-8000-000000004011"
        ),
        input_binding=ExtractionInputBinding(
            definition_id=SourceDefinitionId.parse(
                "00000000-0000-4000-8000-000000004041"
            ),
            definition_version_id=SourceDefinitionVersionId.parse(
                "00000000-0000-4000-8000-000000004042"
            ),
            item_id=SourceItemId.parse(
                "00000000-0000-4000-8000-000000004043"
            ),
            revision_id=SourceRevisionId.parse(
                "00000000-0000-4000-8000-000000004044"
            ),
            representation_id=DiscoveryRepresentationId.parse(
                "00000000-0000-4000-8000-000000004045"
            ),
            passages=passages,
        ),
        budget=ExtractionBudget(
            timeout_ms=5_000,
            max_input_bytes=64 * 1024,
            max_output_bytes=64 * 1024,
            max_proposals=32,
            max_evidence_ranges=64,
            max_request_tokens=0,
            max_response_tokens=0,
            max_cost_microunits=0,
        ),
        idempotency_key="increment-4a-run-v1",
    )


def extraction_payload_contracts() -> tuple[PayloadSchemaContract, ...]:
    contract = _golden_contract()
    run = _golden_run()
    return (
        PayloadSchemaContract(
            schema_version=_CONTRACT_SCHEMA,
            payload_mode=PayloadMode.INLINE,
            contract_version=_CONTRACT_VERSION,
            canonicalizer_implementation_version=(
                "extractor-contract-exact-fields-canonical-json-v1"
            ),
            canonicalizer=_contract_payload,
            golden_vectors=(
                PayloadGoldenVector(
                    name="extractor-contract-exact-fields",
                    input_identity="increment-4a-contract-golden-v1",
                    value=contract.canonical_value(),
                    expected_bytes=contract.canonical_bytes,
                ),
            ),
        ),
        PayloadSchemaContract(
            schema_version=_RUN_SCHEMA,
            payload_mode=PayloadMode.INLINE,
            contract_version=_CONTRACT_VERSION,
            canonicalizer_implementation_version=(
                "extraction-run-exact-fields-canonical-json-v1"
            ),
            canonicalizer=_run_payload,
            golden_vectors=(
                PayloadGoldenVector(
                    name="extraction-run-exact-fields",
                    input_identity="increment-4a-run-golden-v1",
                    value=run.canonical_value(),
                    expected_bytes=run.canonical_bytes,
                ),
            ),
        ),
    )


def extraction_command_definitions() -> tuple[CommandDefinition, ...]:
    contracts = {item.schema_version: item for item in extraction_payload_contracts()}
    specifications = (
        (
            EXTRACTOR_CONTRACT_REGISTER_COMMAND,
            "extractor_contract",
            "extraction.contract.registered",
            _CONTRACT_SCHEMA,
            TrustScope.ADMITTED,
            "authority.extraction.manage",
        ),
        (
            EXTRACTION_RUN_EXECUTE_COMMAND,
            "extraction_run_version",
            "extraction.run.executed",
            _RUN_SCHEMA,
            TrustScope.PROPOSED,
            "authority.extraction.execute",
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
            trust_scope=trust,
            security_scope="authority.extraction",
            retention_scope="authority.audit",
            required_scope=scope,
            max_inline_bytes=512 * 1024,
        )
        for command_type, aggregate_type, event_type, schema, trust, scope in specifications
    )


def merge_extraction_authority_registries(
    *,
    command_registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
) -> tuple[CommandRegistry, PayloadSchemaRegistry]:
    definitions = list(command_registry.definitions())
    by_key = {(item.command_type, item.definition_version): item for item in definitions}
    for definition in extraction_command_definitions():
        key = (definition.command_type, definition.definition_version)
        existing = by_key.get(key)
        if existing is not None and existing.digest != definition.digest:
            raise ValueError(
                f"extraction command identity conflict: {definition.command_type}"
            )
        if existing is None:
            definitions.append(definition)
            by_key[key] = definition
    current_commands = {
        item.command_type: command_registry.resolve(item.command_type).definition_version
        for item in definitions
        if item.command_type not in EXTRACTION_COMMAND_TYPES
    }
    current_commands.update(
        {command_type: _DEFINITION_VERSION for command_type in EXTRACTION_COMMAND_TYPES}
    )

    contracts = list(payload_schemas.contracts())
    by_schema = {
        (item.schema_version, item.payload_mode, item.contract_version): item
        for item in contracts
    }
    additions = extraction_payload_contracts()
    for contract in additions:
        key = (contract.schema_version, contract.payload_mode, contract.contract_version)
        existing = by_schema.get(key)
        if existing is not None and existing.contract_digest != contract.contract_digest:
            raise ValueError(
                f"extraction payload identity conflict: {contract.schema_version}"
            )
        if existing is None:
            contracts.append(contract)
            by_schema[key] = contract
    extraction_versions = {item.schema_version for item in additions}
    current_schemas: dict[tuple[str, PayloadMode], str] = {}
    for schema_version, mode in {
        (item.schema_version, item.payload_mode) for item in contracts
    }:
        if schema_version in extraction_versions:
            current_schemas[(schema_version, mode)] = _CONTRACT_VERSION
        else:
            current_schemas[(schema_version, mode)] = payload_schemas.resolve(
                schema_version, mode
            ).contract_version
    return (
        CommandRegistry(definitions, current_versions=current_commands),
        PayloadSchemaRegistry(contracts, current_versions=current_schemas),
    )


__all__ = [
    "EXTRACTION_COMMAND_TYPES",
    "EXTRACTION_RUN_EXECUTE_COMMAND",
    "EXTRACTOR_CONTRACT_REGISTER_COMMAND",
    "extraction_command_definitions",
    "extraction_payload_contracts",
    "merge_extraction_authority_registries",
]
