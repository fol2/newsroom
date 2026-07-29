from __future__ import annotations

from hashlib import sha256
from uuid import UUID

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.types import UtcTimestamp
from newsroom.sources import (
    DiscoveryRepresentationId,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceItemId,
    SourceRevisionId,
    VersionedPolicyRef,
)

from .models import (
    ExtractionAttemptRequest,
    ExtractionOutputRequest,
    ExtractionPassageRef,
    ExtractionResourceBounds,
    ExtractionRunRequest,
    ExtractorContractRequest,
    ProposalEndpoint,
    ProposalEnvelope,
    ProposalSetRequest,
)
from .types import (
    RUNTIME_AUTHORITY_DISABLED,
    ExtractionAttemptId,
    ExtractionAttemptOutcome,
    ExtractionExecutionProfile,
    ExtractionOutputId,
    ExtractionOutputKind,
    ExtractionProducerKind,
    ExtractionRunId,
    ExtractorContractId,
    ProposalEndpointKind,
    ProposalEnvelopeId,
    ProposalKind,
    ProposalSetCompleteness,
    ProposalSetId,
    ProposalUncertainty,
    semantic_digest,
)

FIXTURE_NOW = UtcTimestamp.parse("2042-04-01T10:00:00.000000Z")
FIXTURE_LATER = UtcTimestamp.parse("2042-04-01T10:00:01.000000Z")
FIXTURE_END = UtcTimestamp.parse("2042-04-01T10:00:02.000000Z")

FIXTURE_CONTRACT_ID = ExtractorContractId.parse("00000000-0000-4000-8000-000000009001")
FIXTURE_RUN_ID = ExtractionRunId.parse("00000000-0000-4000-8000-000000009002")
FIXTURE_ATTEMPT_ID = ExtractionAttemptId.parse("00000000-0000-4000-8000-000000009003")
FIXTURE_OUTPUT_ID = ExtractionOutputId.parse("00000000-0000-4000-8000-000000009004")
FIXTURE_PROPOSAL_SET_ID = ProposalSetId.parse("00000000-0000-4000-8000-000000009005")
FIXTURE_DEFINITION_ID = SourceDefinitionId.parse("00000000-0000-4000-8000-000000009101")
FIXTURE_VERSION_ID = SourceDefinitionVersionId.parse("00000000-0000-4000-8000-000000009102")
FIXTURE_ITEM_ID = SourceItemId.parse("00000000-0000-4000-8000-000000009103")
FIXTURE_REVISION_ID = SourceRevisionId.parse("00000000-0000-4000-8000-000000009104")
FIXTURE_REPRESENTATION_ID = DiscoveryRepresentationId.parse("00000000-0000-4000-8000-000000009105")
FIXTURE_RIGHTS_ID = "00000000-0000-4000-8000-000000009199"


def deterministic_uuid4_text(namespace: str, identity: str) -> str:
    raw = bytearray(sha256(f"{namespace}\x00{identity}".encode("utf-8")).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(UUID(bytes=bytes(raw)))


def fixture_contract_request(*, key: str = "extraction-contract-fixture-v1") -> ExtractorContractRequest:
    policy = lambda name: VersionedPolicyRef(name, "v1")
    return ExtractorContractRequest(
        contract_id=FIXTURE_CONTRACT_ID,
        contract_family="repository-fixture-extractor",
        version_number=1,
        previous_contract_id=None,
        framework=policy("repository-deterministic-fake"),
        model_placeholder=policy("no-model-fixture-placeholder"),
        prompt_contract=policy("fixture-extraction-prompt"),
        output_schema_contract=policy("fixture-extraction-output"),
        code_contract=policy("fixture-extractor-code"),
        normalization_contract=policy("fixture-output-normalization"),
        extraction_policy=policy("fixture-extraction-policy"),
        producer_kind=ExtractionProducerKind.DETERMINISTIC_FAKE,
        execution_profile=ExtractionExecutionProfile.FIXTURE,
        resource_bounds=ExtractionResourceBounds(
            max_input_bytes=128 * 1024,
            max_output_bytes=256 * 1024,
            max_proposals=64,
            max_attempts=3,
            max_duration_ms=10_000,
            max_input_tokens=0,
            max_output_tokens=0,
            max_cost_microunits=0,
        ),
        runtime_authority=RUNTIME_AUTHORITY_DISABLED,
        registered_at=FIXTURE_NOW,
        idempotency_key=key,
    )


FIXTURE_EN_PASSAGE = (
    "The Hong Kong Monetary Authority published a repository-owned fixture update."
)
FIXTURE_ZH_HANT_PASSAGE = "香港金融管理局發布咗一則由儲存庫擁有嘅測試更新。"


def fixture_passages() -> tuple[ExtractionPassageRef, ...]:
    en_bytes = FIXTURE_EN_PASSAGE.encode("utf-8")
    zh_bytes = FIXTURE_ZH_HANT_PASSAGE.encode("utf-8")
    return (
        ExtractionPassageRef(
            passage_id="fixture-en-001",
            ordinal=0,
            source_field="body",
            start_offset=0,
            end_offset=len(en_bytes),
            text_digest=digest_bytes(en_bytes),
            language="en-GB",
        ),
        ExtractionPassageRef(
            passage_id="fixture-zh-hant-001",
            ordinal=1,
            source_field="body",
            start_offset=len(en_bytes) + 1,
            end_offset=len(en_bytes) + 1 + len(zh_bytes),
            text_digest=digest_bytes(zh_bytes),
            language="zh-Hant-HK",
        ),
    )


def fixture_run_request(
    *,
    contract: ExtractorContractRequest | None = None,
    definition_id: SourceDefinitionId = FIXTURE_DEFINITION_ID,
    definition_version_id: SourceDefinitionVersionId = FIXTURE_VERSION_ID,
    item_id: SourceItemId = FIXTURE_ITEM_ID,
    revision_id: SourceRevisionId = FIXTURE_REVISION_ID,
    representation_id: DiscoveryRepresentationId = FIXTURE_REPRESENTATION_ID,
    rights_decision_id: str = FIXTURE_RIGHTS_ID,
    rights_policy_version: str = "fixture-rights-v1",
    allowed_use: str = "discovery.extraction.fixture",
    retention_scope: str = "authority.audit",
    key: str = "extraction-run-fixture-v1",
) -> ExtractionRunRequest:
    exact_contract = contract or fixture_contract_request()
    passages = fixture_passages()
    manifest = {
        "allowed_use": allowed_use,
        "contract_digest": exact_contract.digest,
        "contract_id": str(exact_contract.contract_id),
        "definition_id": str(definition_id),
        "definition_version_id": str(definition_version_id),
        "item_id": str(item_id),
        "passages": [item.canonical_value() for item in passages],
        "representation_id": str(representation_id),
        "retention_scope": retention_scope,
        "revision_id": str(revision_id),
        "rights_decision_id": rights_decision_id,
        "rights_policy_version": rights_policy_version,
    }
    return ExtractionRunRequest(
        run_id=FIXTURE_RUN_ID,
        contract_id=exact_contract.contract_id,
        contract_digest=exact_contract.digest,
        definition_id=definition_id,
        definition_version_id=definition_version_id,
        item_id=item_id,
        revision_id=revision_id,
        representation_id=representation_id,
        rights_decision_id=rights_decision_id,
        rights_policy_version=rights_policy_version,
        allowed_use=allowed_use,
        retention_scope=retention_scope,
        passages=passages,
        input_manifest_digest=semantic_digest(manifest),
        producer_id="repository-fixture-extractor",
        producer_version="v1",
        requested_at=FIXTURE_LATER,
        idempotency_key=key,
    )


def fixture_structured_output() -> dict[str, object]:
    return {
        "entities": [
            {
                "language": "en-GB",
                "local_id": "entity-hkma-en",
                "surface_text": "Hong Kong Monetary Authority",
            },
            {
                "language": "zh-Hant-HK",
                "local_id": "entity-hkma-zh",
                "surface_text": "香港金融管理局",
            },
        ],
        "relations": [
            {
                "object_local_id": "entity-hkma-zh",
                "predicate_hint": "POSSIBLE_ALIAS_OF",
                "subject_local_id": "entity-hkma-en",
            }
        ],
        "schema": "fixture-extraction-output-v1",
    }


def fixture_attempt_request(*, key: str = "extraction-attempt-fixture-v1") -> ExtractionAttemptRequest:
    output = fixture_structured_output()
    output_bytes = len(canonical_json_bytes(output))
    return ExtractionAttemptRequest(
        attempt_id=FIXTURE_ATTEMPT_ID,
        run_id=FIXTURE_RUN_ID,
        attempt_number=1,
        previous_attempt_id=None,
        outcome=ExtractionAttemptOutcome.SUCCESS,
        producer_execution_id="fixture-execution-001",
        started_at=FIXTURE_LATER,
        ended_at=FIXTURE_END,
        input_bytes=216,
        output_bytes=output_bytes,
        input_tokens=0,
        output_tokens=0,
        cost_microunits=0,
        error_code=None,
        error_summary=None,
        idempotency_key=key,
    )


def fixture_output_request(*, key: str = "extraction-output-fixture-v1") -> ExtractionOutputRequest:
    return ExtractionOutputRequest(
        output_id=FIXTURE_OUTPUT_ID,
        run_id=FIXTURE_RUN_ID,
        attempt_id=FIXTURE_ATTEMPT_ID,
        output_kind=ExtractionOutputKind.INLINE_STRUCTURED,
        output_schema_digest=semantic_digest(
            VersionedPolicyRef("fixture-extraction-output", "v1").canonical_value()
        ),
        structured_output=fixture_structured_output(),
        object_admission_id=None,
        hydration_digest=None,
        valid=True,
        validation_errors=(),
        retained_at=FIXTURE_END,
        idempotency_key=key,
    )


def fixture_proposals() -> tuple[ProposalEnvelope, ...]:
    first = ProposalEnvelope(
        proposal_id=ProposalEnvelopeId.parse("00000000-0000-4000-8000-000000009011"),
        proposal_kind=ProposalKind.ENTITY_MENTION,
        producer_local_id="entity-hkma-en",
        subject=ProposalEndpoint(
            placeholder_id="entity-hkma-en",
            kind=ProposalEndpointKind.MENTION,
            surface_text="Hong Kong Monetary Authority",
            language="en-GB",
            normalized_hint="hong-kong-monetary-authority",
        ),
        object=None,
        predicate_hint=None,
        passage_ids=("fixture-en-001",),
        confidence_basis_points=9700,
        uncertainty=ProposalUncertainty.LOW,
        uncertainty_reasons=(),
        attributes={"entity_type_hint": "ORGANISATION"},
    )
    second = ProposalEnvelope(
        proposal_id=ProposalEnvelopeId.parse("00000000-0000-4000-8000-000000009012"),
        proposal_kind=ProposalKind.ENTITY_MENTION,
        producer_local_id="entity-hkma-zh",
        subject=ProposalEndpoint(
            placeholder_id="entity-hkma-zh",
            kind=ProposalEndpointKind.MENTION,
            surface_text="香港金融管理局",
            language="zh-Hant-HK",
            normalized_hint=None,
        ),
        object=None,
        predicate_hint=None,
        passage_ids=("fixture-zh-hant-001",),
        confidence_basis_points=9600,
        uncertainty=ProposalUncertainty.LOW,
        uncertainty_reasons=(),
        attributes={"entity_type_hint": "ORGANISATION"},
    )
    third = ProposalEnvelope(
        proposal_id=ProposalEnvelopeId.parse("00000000-0000-4000-8000-000000009013"),
        proposal_kind=ProposalKind.RELATION,
        producer_local_id="relation-possible-alias",
        subject=first.subject,
        object=second.subject,
        predicate_hint="POSSIBLE_ALIAS_OF",
        passage_ids=("fixture-en-001", "fixture-zh-hant-001"),
        confidence_basis_points=7200,
        uncertainty=ProposalUncertainty.HIGH,
        uncertainty_reasons=("bilingual-name-equivalence-needs-editorial-resolution",),
        attributes={"admission_authority": False},
    )
    return (first, second, third)


def fixture_proposal_set_request(*, key: str = "extraction-proposal-set-fixture-v1") -> ProposalSetRequest:
    return ProposalSetRequest(
        proposal_set_id=FIXTURE_PROPOSAL_SET_ID,
        run_id=FIXTURE_RUN_ID,
        attempt_id=FIXTURE_ATTEMPT_ID,
        output_id=FIXTURE_OUTPUT_ID,
        completeness=ProposalSetCompleteness.COMPLETE,
        proposals=fixture_proposals(),
        retained_at=FIXTURE_END,
        idempotency_key=key,
    )


__all__ = [
    "FIXTURE_ATTEMPT_ID",
    "FIXTURE_EN_PASSAGE",
    "FIXTURE_CONTRACT_ID",
    "FIXTURE_DEFINITION_ID",
    "FIXTURE_END",
    "FIXTURE_ITEM_ID",
    "FIXTURE_LATER",
    "FIXTURE_NOW",
    "FIXTURE_OUTPUT_ID",
    "FIXTURE_PROPOSAL_SET_ID",
    "FIXTURE_REPRESENTATION_ID",
    "FIXTURE_REVISION_ID",
    "FIXTURE_RIGHTS_ID",
    "FIXTURE_RUN_ID",
    "FIXTURE_VERSION_ID",
    "FIXTURE_ZH_HANT_PASSAGE",
    "deterministic_uuid4_text",
    "fixture_attempt_request",
    "fixture_contract_request",
    "fixture_output_request",
    "fixture_passages",
    "fixture_proposal_set_request",
    "fixture_proposals",
    "fixture_run_request",
    "fixture_structured_output",
]
