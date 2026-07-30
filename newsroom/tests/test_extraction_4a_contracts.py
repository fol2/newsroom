from __future__ import annotations

import dataclasses
from datetime import timedelta
from pathlib import Path

import pytest

from newsroom.authority import UtcTimestamp
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.extraction import (
    DeterministicFixtureExtractor,
    EvidenceRange,
    ExtractionBudget,
    ExtractionContractError,
    ExtractionExecutionProfile,
    ExtractionFailureCode,
    ExtractionOutcome,
    ExtractionOutputValidation,
    ExtractionPassageId,
    ExtractionProposalKind,
    ExtractionRunId,
    ExtractionRunVersionId,
    ExtractionUsage,
    ExtractorContractId,
    EXPECTED_FIXTURE_CONTRACT_SEMANTIC_DIGESTS,
    FIXTURE_ALLOWED_TEXT_DIGESTS,
    FIXTURE_EN_TEXT,
    FIXTURE_HOMONYM_ALLOWED_TEXT_DIGESTS,
    FIXTURE_HOMONYM_EN_TEXT,
    FIXTURE_HOMONYM_ZH_HK_TEXT,
    FIXTURE_ZH_HK_TEXT,
    FixtureExtractionCase,
    ProducedExtraction,
    ProposalDraft,
    ProposalPredicateHint,
    VersionedExtractionComponent,
)
from newsroom.extraction.types import authority_elapsed_ms

from .extraction_4a_helpers import (
    contract_request,
    run_request,
    seed_extraction_fixture,
    seed_homonym_extraction_fixture,
)
from .source_3a_helpers import SOURCE_NOW


def _passage_id(value: int) -> ExtractionPassageId:
    return ExtractionPassageId.parse(
        f"00000000-0000-4000-8000-{value:012d}"
    )


def _evidence(value: int = 1) -> EvidenceRange:
    return EvidenceRange(
        passage_id=_passage_id(value),
        start_byte=0,
        end_byte=4,
        evidence_text_digest=digest_bytes(b"test"),
    )


def _proposal(*, local_id: str = "entity.fixture") -> ProposalDraft:
    return ProposalDraft(
        local_id=local_id,
        kind=ExtractionProposalKind.ENTITY_MENTION,
        subject_placeholder="Fixture Entity",
        object_placeholder=None,
        predicate_hint=None,
        confidence_basis_points=9_000,
        uncertainty_codes=(),
        rationale_codes=("EXACT_FIXTURE_SPAN",),
        evidence=(_evidence(),),
    )


@pytest.mark.parametrize(
    ("factory", "match"),
    (
        (
            lambda: ExtractionBudget(
                timeout_ms=True,
                max_input_bytes=1,
                max_output_bytes=1,
                max_proposals=1,
                max_evidence_ranges=1,
                max_request_tokens=0,
                max_response_tokens=0,
                max_cost_microunits=0,
            ),
            "timeout_ms",
        ),
        (
            lambda: ExtractionBudget(
                timeout_ms=1,
                max_input_bytes=1.0,  # type: ignore[arg-type]
                max_output_bytes=1,
                max_proposals=1,
                max_evidence_ranges=1,
                max_request_tokens=0,
                max_response_tokens=0,
                max_cost_microunits=0,
            ),
            "max_input_bytes",
        ),
        (
            lambda: ExtractionUsage(
                elapsed_ms=0,
                input_bytes=0,
                output_bytes=0,
                proposal_count=-1,
                evidence_range_count=0,
            ),
            "proposal_count",
        ),
        (
            lambda: EvidenceRange(
                passage_id=_passage_id(1),
                start_byte=4,
                end_byte=4,
                evidence_text_digest=digest_bytes(b""),
            ),
            "non-empty",
        ),
    ),
)
def test_finite_integer_and_evidence_bounds_fail_closed(
    factory,
    match: str,
) -> None:
    with pytest.raises(ExtractionContractError, match=match):
        factory()


def test_usage_must_fit_the_exact_fixed_budget() -> None:
    budget = ExtractionBudget(
        timeout_ms=10,
        max_input_bytes=10,
        max_output_bytes=10,
        max_proposals=1,
        max_evidence_ranges=1,
        max_request_tokens=0,
        max_response_tokens=0,
        max_cost_microunits=0,
    )
    ExtractionUsage(
        elapsed_ms=10,
        input_bytes=10,
        output_bytes=10,
        proposal_count=1,
        evidence_range_count=1,
    ).require_within(budget)
    with pytest.raises(ExtractionContractError, match="exceeds"):
        ExtractionUsage(
            elapsed_ms=11,
            input_bytes=10,
            output_bytes=10,
            proposal_count=1,
            evidence_range_count=1,
        ).require_within(budget)
    ExtractionUsage(
        elapsed_ms=300_001,
        input_bytes=10,
        output_bytes=0,
        proposal_count=0,
        evidence_range_count=0,
    ).require_within(budget, allow_elapsed_timeout=True)
    with pytest.raises(ExtractionContractError, match="must exceed"):
        ExtractionUsage(
            elapsed_ms=10,
            input_bytes=10,
            output_bytes=0,
            proposal_count=0,
            evidence_range_count=0,
        ).require_within(budget, allow_elapsed_timeout=True)
    with pytest.raises(ExtractionContractError, match="elapsed_ms"):
        ExtractionUsage(
            elapsed_ms=86_400_001,
            input_bytes=10,
            output_bytes=0,
            proposal_count=0,
            evidence_range_count=0,
        )


def test_authority_elapsed_time_uses_a_strict_ceiling_at_millisecond_precision() -> None:
    exact = UtcTimestamp(SOURCE_NOW.value + timedelta(milliseconds=10))
    over = UtcTimestamp(SOURCE_NOW.value + timedelta(microseconds=10_001))

    assert authority_elapsed_ms(SOURCE_NOW, exact) == 10
    assert authority_elapsed_ms(SOURCE_NOW, over) == 11
    with pytest.raises(ExtractionContractError, match="cannot be negative"):
        authority_elapsed_ms(exact, SOURCE_NOW)


def test_contract_and_run_canonical_identity_excludes_idempotency_key(
    tmp_path: Path,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    first_contract = contract_request(key="first-contract-key")
    replay_contract = contract_request(key="different-contract-key")
    assert first_contract.canonical_bytes == replay_contract.canonical_bytes
    assert first_contract.digest == replay_contract.digest
    assert first_contract.semantic_digest == replay_contract.semantic_digest

    first_run = run_request(state, key="first-run-key")
    replay_run = run_request(state, key="different-run-key")
    assert first_run.canonical_bytes == replay_run.canonical_bytes
    assert first_run.digest == replay_run.digest
    assert first_run.stable_run_semantic_digest == replay_run.stable_run_semantic_digest

    component_fields = (
        "framework",
        "model",
        "prompt",
        "output_schema",
        "code",
        "normalisation",
        "policy",
    )
    semantic_digests = {first_contract.semantic_digest}
    for offset, field_name in enumerate(component_fields, start=1):
        original = getattr(first_contract, field_name)
        changed_component = VersionedExtractionComponent(
            component_id=original.component_id,
            component_version=f"{original.component_version}-changed",
            contract_digest="sha256:" + f"{offset:x}" * 64,
        )
        changed = dataclasses.replace(
            first_contract,
            contract_id=ExtractorContractId.parse(
                f"00000000-0000-4000-8000-{4900 + offset:012d}"
            ),
            **{field_name: changed_component},
        )
        assert changed.semantic_digest not in semantic_digests
        semantic_digests.add(changed.semantic_digest)
        changed_run = dataclasses.replace(first_run, contract_id=changed.contract_id)
        assert (
            changed_run.stable_run_semantic_digest
            != first_run.stable_run_semantic_digest
        )

    assert len(semantic_digests) == 1 + len(component_fields)


def test_fixture_scenario_is_versioned_contract_policy_not_run_input(
    tmp_path: Path,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    complete = contract_request(
        contract_id=ExtractorContractId.parse(
            "00000000-0000-4000-8000-000000004911"
        ),
        fixture_case=FixtureExtractionCase.BILINGUAL_COMPLETE,
        key="complete-contract",
    )
    partial = contract_request(
        contract_id=ExtractorContractId.parse(
            "00000000-0000-4000-8000-000000004912"
        ),
        fixture_case=FixtureExtractionCase.BILINGUAL_PARTIAL,
        key="partial-contract",
    )

    assert complete.policy != partial.policy
    assert complete.semantic_digest != partial.semantic_digest
    assert complete.semantic_digest == EXPECTED_FIXTURE_CONTRACT_SEMANTIC_DIGESTS[
        FixtureExtractionCase.BILINGUAL_COMPLETE
    ]
    assert partial.semantic_digest == EXPECTED_FIXTURE_CONTRACT_SEMANTIC_DIGESTS[
        FixtureExtractionCase.BILINGUAL_PARTIAL
    ]

    complete_run = run_request(state, contract_id=complete.contract_id)
    partial_run = run_request(
        state,
        contract_id=partial.contract_id,
        run_id=ExtractionRunId.parse(
            "00000000-0000-4000-8000-000000004913"
        ),
        run_version_id=ExtractionRunVersionId.parse(
            "00000000-0000-4000-8000-000000004914"
        ),
        key="partial-run",
    )
    assert "fixture_case" not in complete_run.canonical_value()
    assert "fixture_case" not in partial_run.canonical_value()


def test_run_version_chain_and_typed_identity_contracts_fail_closed(
    tmp_path: Path,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    with pytest.raises(ExtractionContractError, match="predecessor"):
        dataclasses.replace(
            run_request(state),
            version_number=2,
            expected_previous_version_id=None,
        )
    with pytest.raises(ExtractionContractError, match="initial"):
        dataclasses.replace(
            run_request(state),
            expected_previous_version_id=ExtractionRunVersionId.parse(
                "00000000-0000-4000-8000-000000004902"
            ),
        )
    with pytest.raises(ExtractionContractError, match="typed"):
        dataclasses.replace(
            run_request(state),
            run_id="not-a-run-id",  # type: ignore[arg-type]
        )


def test_proposal_shape_codes_and_evidence_are_canonical() -> None:
    proposal = _proposal()
    assert proposal.digest.startswith("sha256:")
    assert canonical_json_bytes(proposal.canonical_value())

    with pytest.raises(ExtractionContractError, match="relation proposal"):
        dataclasses.replace(
            proposal,
            kind=ExtractionProposalKind.RELATION,
            object_placeholder=None,
            predicate_hint=ProposalPredicateHint.SUPERSEDES,
        )
    with pytest.raises(ExtractionContractError, match="only relation"):
        dataclasses.replace(
            proposal,
            predicate_hint=ProposalPredicateHint.SUPPORTS,
        )
    with pytest.raises(ExtractionContractError, match="sorted and unique"):
        dataclasses.replace(
            proposal,
            uncertainty_codes=("Z_CODE", "A_CODE"),
        )
    with pytest.raises(ExtractionContractError, match="evidence must be sorted"):
        dataclasses.replace(
            proposal,
            evidence=(
                EvidenceRange(
                    passage_id=_passage_id(2),
                    start_byte=0,
                    end_byte=4,
                    evidence_text_digest=digest_bytes(b"test"),
                ),
                _evidence(1),
            ),
        )


def test_produced_extraction_outcome_matrix_prevents_false_success() -> None:
    proposal = _proposal()
    raw = {"schema_version": "fixture", "entities": []}
    usage = ExtractionUsage(
        elapsed_ms=1,
        input_bytes=0,
        output_bytes=len(canonical_json_bytes(raw)),
        proposal_count=1,
        evidence_range_count=1,
    )
    complete = ProducedExtraction(
        outcome=ExtractionOutcome.SUCCESS,
        failure_code=ExtractionFailureCode.NONE,
        validation=ExtractionOutputValidation.VALID,
        raw_output_value=raw,
        proposals=(proposal,),
        usage=usage,
    )
    assert complete.raw_output_digest == digest_bytes(canonical_json_bytes(raw))

    with pytest.raises(ExtractionContractError, match="needs proposals"):
        ProducedExtraction(
            outcome=ExtractionOutcome.SUCCESS,
            failure_code=ExtractionFailureCode.NONE,
            validation=ExtractionOutputValidation.VALID,
            raw_output_value=raw,
            proposals=(),
            usage=dataclasses.replace(
                usage,
                proposal_count=0,
                evidence_range_count=0,
            ),
        )
    with pytest.raises(ExtractionContractError, match="cannot create proposal"):
        ProducedExtraction(
            outcome=ExtractionOutcome.INVALID_OUTPUT,
            failure_code=ExtractionFailureCode.OUTPUT_SCHEMA_INVALID,
            validation=ExtractionOutputValidation.INVALID,
            raw_output_value=raw,
            proposals=(proposal,),
            usage=usage,
        )

    internal_failure = ProducedExtraction(
        outcome=ExtractionOutcome.RETRYABLE_FAILURE,
        failure_code=ExtractionFailureCode.PRODUCER_INTERNAL_ERROR,
        validation=None,
        raw_output_value=None,
        proposals=(),
        usage=ExtractionUsage(
            elapsed_ms=1,
            input_bytes=0,
            output_bytes=0,
            proposal_count=0,
            evidence_range_count=0,
        ),
    )
    assert internal_failure.raw_output_value is None

    timeout_failure = dataclasses.replace(
        internal_failure,
        failure_code=ExtractionFailureCode.EXECUTION_TIMEOUT,
    )
    assert timeout_failure.outcome is ExtractionOutcome.RETRYABLE_FAILURE
    assert timeout_failure.raw_output_value is None
    with pytest.raises(ExtractionContractError, match="incompatible"):
        dataclasses.replace(
            timeout_failure,
            outcome=ExtractionOutcome.BLOCKING_FAILURE,
        )

    with pytest.raises(ExtractionContractError, match="incompatible"):
        dataclasses.replace(
            internal_failure,
            outcome=ExtractionOutcome.BLOCKING_FAILURE,
        )
    with pytest.raises(ExtractionContractError, match="incompatible"):
        dataclasses.replace(
            internal_failure,
            failure_code=ExtractionFailureCode.POLICY_BLOCKED,
        )


def test_deterministic_fixture_producer_is_exact_bilingual_and_side_effect_free(
    tmp_path: Path,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    producer = DeterministicFixtureExtractor()
    contract = contract_request()
    request = run_request(state)

    first = producer.produce(contract=contract, request=request)
    second = producer.produce(contract=contract, request=request)
    assert first == second
    assert first.outcome is ExtractionOutcome.SUCCESS
    assert first.validation is ExtractionOutputValidation.VALID
    assert tuple(item.local_id for item in first.proposals) == (
        "entity.transport-department.en",
        "entity.transport-department.zh-hk",
        "equivalence.transport-department.bilingual",
        "relation.guidance-supersedes-notice",
    )
    assert first.proposals[2].uncertainty_codes == (
        "REQUIRES_EXPLICIT_RESOLUTION",
    )
    assert first.proposals[3].uncertainty_codes == (
        "REQUIRES_RELATION_ADMISSION",
    )
    assert first.usage.request_tokens == 0
    assert first.usage.response_tokens == 0
    assert first.usage.cost_microunits == 0

    # Typed contract construction fails before the producer could select a runtime.
    with pytest.raises(ExtractionContractError, match="execution profile"):
        dataclasses.replace(
            contract,
            execution_profile="PRODUCTION",  # type: ignore[arg-type]
        )


def test_homonym_fixture_is_separately_versioned_and_occurrence_bound(
    tmp_path: Path,
) -> None:
    state = seed_homonym_extraction_fixture(tmp_path)
    producer = DeterministicFixtureExtractor()
    contract = contract_request(
        fixture_case=FixtureExtractionCase.BILINGUAL_HOMONYM,
        key="homonym-contract",
    )
    request = run_request(
        state, contract_id=contract.contract_id, key="homonym-run"
    )

    produced = producer.produce(contract=contract, request=request)

    assert produced.outcome is ExtractionOutcome.SUCCESS
    assert produced.validation is ExtractionOutputValidation.VALID
    assert produced.raw_output_value is not None
    assert produced.raw_output_value["schema_version"] == (
        "increment-4b-homonym-fixture-output-v1"
    )
    assert len(produced.proposals) == 6
    mentions = tuple(
        item
        for item in produced.proposals
        if item.kind is ExtractionProposalKind.ENTITY_MENTION
    )
    equivalences = tuple(
        item
        for item in produced.proposals
        if item.kind is ExtractionProposalKind.ENTITY_EQUIVALENCE
    )
    assert len(mentions) == 4
    assert len(equivalences) == 2
    assert {item.subject_placeholder for item in mentions} == {
        "Chan Chi Ming",
        "陳志明",
    }
    assert len(
        {
            (
                str(item.evidence[0].passage_id),
                item.evidence[0].start_byte,
                item.evidence[0].end_byte,
            )
            for item in mentions
        }
    ) == 4
    assert len(
        {
            tuple(
                (str(evidence.passage_id), evidence.start_byte, evidence.end_byte)
                for evidence in item.evidence
            )
            for item in equivalences
        }
    ) == 2

    ordinary_state = seed_extraction_fixture(tmp_path / "ordinary")
    with pytest.raises(ExtractionContractError, match="approved fixture bytes"):
        producer.produce(
            contract=contract,
            request=run_request(
                ordinary_state,
                contract_id=contract.contract_id,
                key="wrong-homonym-bytes",
            ),
        )


def test_fixture_policy_binds_exact_admitted_utf8_bytes() -> None:
    assert FIXTURE_ALLOWED_TEXT_DIGESTS == (
        digest_bytes(FIXTURE_EN_TEXT.encode("utf-8")),
        digest_bytes(FIXTURE_ZH_HK_TEXT.encode("utf-8")),
    )
    assert FIXTURE_HOMONYM_ALLOWED_TEXT_DIGESTS == (
        digest_bytes(FIXTURE_HOMONYM_EN_TEXT.encode("utf-8")),
        digest_bytes(FIXTURE_HOMONYM_ZH_HK_TEXT.encode("utf-8")),
    )


def test_execution_profile_is_closed_to_fixture_replay_only() -> None:
    assert tuple(ExtractionExecutionProfile) == (
        ExtractionExecutionProfile.FIXTURE_REPLAY_ONLY,
    )
    assert tuple(FixtureExtractionCase) == (
        FixtureExtractionCase.BILINGUAL_COMPLETE,
        FixtureExtractionCase.BILINGUAL_PARTIAL,
        FixtureExtractionCase.BILINGUAL_HOMONYM,
        FixtureExtractionCase.RETRYABLE_FAILURE,
        FixtureExtractionCase.BLOCKING_FAILURE,
        FixtureExtractionCase.INVALID_OUTPUT,
    )
    assert ExtractionRunId is not ExtractionRunVersionId
