from __future__ import annotations

from newsroom.authority.canonical import digest_canonical

from .models import ExtractorContractRequest
from .types import (
    ExtractionExecutionProfile,
    ExtractorContractId,
    VersionedExtractionComponent,
)

FIXTURE_EN_TEXT = (
    "The Hong Kong Transport Department issued revised road safety guidance. "
    "The revision supersedes the earlier notice."
)
FIXTURE_ZH_HK_TEXT = "香港運輸署發布經修訂的道路安全指引。該修訂取代較早前的公告。"

FIXTURE_EN_LANGUAGE = "en-GB"
FIXTURE_ZH_HK_LANGUAGE = "zh-HK"
FIXTURE_PRODUCER_KIND = "DETERMINISTIC_FIXTURE"


def _component(component_id: str, version: str, contract: object) -> VersionedExtractionComponent:
    return VersionedExtractionComponent(
        component_id=component_id,
        component_version=version,
        contract_digest=digest_canonical(contract),
    )


FIXTURE_FRAMEWORK_COMPONENT = _component(
    "newsroom.fixture.framework",
    "v1",
    {"runtime": "repository-owned-pure-python", "network": False},
)
FIXTURE_MODEL_COMPONENT = _component(
    "newsroom.fixture.no-model",
    "v1",
    {"model": None, "provider": None, "credentials": False},
)
FIXTURE_PROMPT_COMPONENT = _component(
    "newsroom.fixture.prompt",
    "v1",
    {
        "instruction": "emit-only-fixed-repository-owned-bilingual-fixture",
        "source_is_untrusted_data": True,
    },
)
FIXTURE_OUTPUT_SCHEMA_COMPONENT = _component(
    "newsroom.fixture.output-schema",
    "v1",
    {
        "schema_version": "increment-4a-fixture-output-v1",
        "required": ["entities", "fixture_case", "relations", "schema_version"],
        "additional_properties": False,
    },
)
FIXTURE_CODE_COMPONENT = _component(
    "newsroom.fixture.producer-code",
    "v1",
    {"implementation": "DeterministicFixtureExtractor", "side_effects": []},
)
FIXTURE_NORMALISATION_COMPONENT = _component(
    "newsroom.fixture.normalisation",
    "v1",
    {"unicode": "preserve", "bytes": "utf-8", "ordering": "canonical-json"},
)
FIXTURE_POLICY_COMPONENT = _component(
    "newsroom.fixture.policy",
    "v1",
    {
        "profiles": [ExtractionExecutionProfile.FIXTURE_REPLAY_ONLY.value],
        "allowed_text_digests": [
            digest_canonical(FIXTURE_EN_TEXT),
            digest_canonical(FIXTURE_ZH_HK_TEXT),
        ],
        "real_runtime": False,
    },
)


def deterministic_fixture_contract_request(
    *,
    contract_id: ExtractorContractId,
    idempotency_key: str = "increment-4a-fixture-contract-v1",
) -> ExtractorContractRequest:
    return ExtractorContractRequest(
        contract_id=contract_id,
        framework=FIXTURE_FRAMEWORK_COMPONENT,
        model=FIXTURE_MODEL_COMPONENT,
        prompt=FIXTURE_PROMPT_COMPONENT,
        output_schema=FIXTURE_OUTPUT_SCHEMA_COMPONENT,
        code=FIXTURE_CODE_COMPONENT,
        normalisation=FIXTURE_NORMALISATION_COMPONENT,
        policy=FIXTURE_POLICY_COMPONENT,
        execution_profile=ExtractionExecutionProfile.FIXTURE_REPLAY_ONLY,
        producer_kind=FIXTURE_PRODUCER_KIND,
        idempotency_key=idempotency_key,
    )


EXPECTED_FIXTURE_CONTRACT_SEMANTIC_DIGEST = (
    deterministic_fixture_contract_request(
        contract_id=ExtractorContractId.parse(
            "00000000-0000-4000-8000-000000004001"
        )
    ).semantic_digest
)


__all__ = [
    "EXPECTED_FIXTURE_CONTRACT_SEMANTIC_DIGEST",
    "FIXTURE_EN_LANGUAGE",
    "FIXTURE_EN_TEXT",
    "FIXTURE_PRODUCER_KIND",
    "FIXTURE_ZH_HK_LANGUAGE",
    "FIXTURE_ZH_HK_TEXT",
    "deterministic_fixture_contract_request",
]
