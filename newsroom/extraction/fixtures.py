from __future__ import annotations

from types import MappingProxyType

from newsroom.authority.canonical import digest_bytes, digest_canonical

from .models import ExtractorContractRequest
from .output_schema import (
    FIXTURE_OUTPUT_SCHEMA_DIGEST,
    FIXTURE_OUTPUT_SCHEMA_ID,
    FIXTURE_OUTPUT_SCHEMA_VERSION,
)
from .types import (
    ExtractionContractError,
    ExtractionExecutionProfile,
    ExtractorContractId,
    FixtureExtractionCase,
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
FIXTURE_ALLOWED_TEXT_DIGESTS = (
    digest_bytes(FIXTURE_EN_TEXT.encode("utf-8")),
    digest_bytes(FIXTURE_ZH_HK_TEXT.encode("utf-8")),
)


def _component(
    component_id: str,
    version: str,
    contract: object,
) -> VersionedExtractionComponent:
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
FIXTURE_OUTPUT_SCHEMA_COMPONENT = VersionedExtractionComponent(
    component_id=FIXTURE_OUTPUT_SCHEMA_ID,
    component_version=FIXTURE_OUTPUT_SCHEMA_VERSION,
    contract_digest=FIXTURE_OUTPUT_SCHEMA_DIGEST,
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


def _fixture_policy_component(
    fixture_case: FixtureExtractionCase,
) -> VersionedExtractionComponent:
    if not isinstance(fixture_case, FixtureExtractionCase):
        raise ExtractionContractError("fixture case must be typed")
    suffix = fixture_case.value.lower().replace("_", "-")
    return _component(
        "newsroom.fixture.policy",
        f"v1-{suffix}",
        {
            "profiles": [ExtractionExecutionProfile.FIXTURE_REPLAY_ONLY.value],
            "allowed_text_digests": list(FIXTURE_ALLOWED_TEXT_DIGESTS),
            "fixture_case": fixture_case.value,
            "real_runtime": False,
        },
    )


FIXTURE_POLICY_COMPONENTS = MappingProxyType(
    {
        fixture_case: _fixture_policy_component(fixture_case)
        for fixture_case in FixtureExtractionCase
    }
)


def deterministic_fixture_contract_request(
    *,
    contract_id: ExtractorContractId,
    fixture_case: FixtureExtractionCase = FixtureExtractionCase.BILINGUAL_COMPLETE,
    idempotency_key: str = "increment-4a-fixture-contract-v1",
) -> ExtractorContractRequest:
    if not isinstance(fixture_case, FixtureExtractionCase):
        raise ExtractionContractError("fixture case must be typed")
    return ExtractorContractRequest(
        contract_id=contract_id,
        framework=FIXTURE_FRAMEWORK_COMPONENT,
        model=FIXTURE_MODEL_COMPONENT,
        prompt=FIXTURE_PROMPT_COMPONENT,
        output_schema=FIXTURE_OUTPUT_SCHEMA_COMPONENT,
        code=FIXTURE_CODE_COMPONENT,
        normalisation=FIXTURE_NORMALISATION_COMPONENT,
        policy=FIXTURE_POLICY_COMPONENTS[fixture_case],
        execution_profile=ExtractionExecutionProfile.FIXTURE_REPLAY_ONLY,
        producer_kind=FIXTURE_PRODUCER_KIND,
        idempotency_key=idempotency_key,
    )


_EXPECTED_CONTRACT_ID = ExtractorContractId.parse(
    "00000000-0000-4000-8000-000000004001"
)
EXPECTED_FIXTURE_CONTRACT_SEMANTIC_DIGESTS = MappingProxyType(
    {
        fixture_case: deterministic_fixture_contract_request(
            contract_id=_EXPECTED_CONTRACT_ID,
            fixture_case=fixture_case,
        ).semantic_digest
        for fixture_case in FixtureExtractionCase
    }
)
EXPECTED_FIXTURE_CONTRACT_SEMANTIC_DIGEST = (
    EXPECTED_FIXTURE_CONTRACT_SEMANTIC_DIGESTS[
        FixtureExtractionCase.BILINGUAL_COMPLETE
    ]
)


def fixture_case_for_contract(
    contract: ExtractorContractRequest,
) -> FixtureExtractionCase:
    """Resolve the private deterministic scenario from the versioned contract."""

    if not isinstance(contract, ExtractorContractRequest):
        raise TypeError("fixture contract resolution needs a typed contract")
    if (
        contract.execution_profile
        is not ExtractionExecutionProfile.FIXTURE_REPLAY_ONLY
        or contract.producer_kind != FIXTURE_PRODUCER_KIND
    ):
        raise ExtractionContractError(
            "deterministic fixture extractor rejects an incompatible contract"
        )
    for fixture_case, semantic_digest in (
        EXPECTED_FIXTURE_CONTRACT_SEMANTIC_DIGESTS.items()
    ):
        if contract.semantic_digest == semantic_digest:
            return fixture_case
    raise ExtractionContractError(
        "deterministic fixture extractor rejects an incompatible contract"
    )


__all__ = [
    "EXPECTED_FIXTURE_CONTRACT_SEMANTIC_DIGEST",
    "EXPECTED_FIXTURE_CONTRACT_SEMANTIC_DIGESTS",
    "FIXTURE_ALLOWED_TEXT_DIGESTS",
    "FIXTURE_EN_LANGUAGE",
    "FIXTURE_EN_TEXT",
    "FIXTURE_PRODUCER_KIND",
    "FIXTURE_ZH_HK_LANGUAGE",
    "FIXTURE_ZH_HK_TEXT",
    "deterministic_fixture_contract_request",
    "fixture_case_for_contract",
]
