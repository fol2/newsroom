from __future__ import annotations

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes

from .fixtures import (
    EXPECTED_FIXTURE_CONTRACT_SEMANTIC_DIGEST,
    FIXTURE_EN_LANGUAGE,
    FIXTURE_EN_TEXT,
    FIXTURE_PRODUCER_KIND,
    FIXTURE_ZH_HK_LANGUAGE,
    FIXTURE_ZH_HK_TEXT,
)
from .models import (
    ExtractorContractRequest,
    ExtractionRunRequest,
    ProducedExtraction,
    ProposalDraft,
)
from .types import (
    EvidenceRange,
    ExtractionContractError,
    ExtractionExecutionProfile,
    ExtractionFailureCode,
    ExtractionOutcome,
    ExtractionOutputValidation,
    ExtractionProposalKind,
    ExtractionUsage,
    FixtureExtractionCase,
    ProposalPredicateHint,
)


def _range_for(text: str, phrase: str, passage_id) -> EvidenceRange:
    data = text.encode("utf-8")
    phrase_data = phrase.encode("utf-8")
    start = data.find(phrase_data)
    if start < 0:
        raise ExtractionContractError("fixture phrase is absent from governed passage")
    end = start + len(phrase_data)
    return EvidenceRange(
        passage_id=passage_id,
        start_byte=start,
        end_byte=end,
        evidence_text_digest=digest_bytes(data[start:end]),
    )


class DeterministicFixtureExtractor:
    """Pure repository-owned proposal producer with no runtime integrations."""

    producer_kind = FIXTURE_PRODUCER_KIND

    @staticmethod
    def _validate_contract(contract: ExtractorContractRequest) -> None:
        if not isinstance(contract, ExtractorContractRequest):
            raise TypeError("fixture extractor needs a typed contract")
        if (
            contract.execution_profile
            is not ExtractionExecutionProfile.FIXTURE_REPLAY_ONLY
            or contract.producer_kind != FIXTURE_PRODUCER_KIND
            or contract.semantic_digest
            != EXPECTED_FIXTURE_CONTRACT_SEMANTIC_DIGEST
        ):
            raise ExtractionContractError(
                "deterministic fixture extractor rejects an incompatible contract"
            )

    @staticmethod
    def _validate_passages(request: ExtractionRunRequest):
        by_language = {
            passage.language: passage
            for passage in request.input_binding.passages
        }
        en = by_language.get(FIXTURE_EN_LANGUAGE)
        zh = by_language.get(FIXTURE_ZH_HK_LANGUAGE)
        if en is None or zh is None or len(by_language) != 2:
            raise ExtractionContractError(
                "deterministic bilingual fixture requires exact en-GB and zh-HK passages"
            )
        if en.require_text() != FIXTURE_EN_TEXT or zh.require_text() != FIXTURE_ZH_HK_TEXT:
            raise ExtractionContractError(
                "deterministic fixture output is rejected outside approved fixture bytes"
            )
        return en, zh

    @staticmethod
    def _usage(
        request: ExtractionRunRequest,
        raw: dict[str, object] | None,
        proposals: tuple[ProposalDraft, ...],
    ) -> ExtractionUsage:
        output_bytes = 0 if raw is None else len(canonical_json_bytes(raw))
        return ExtractionUsage(
            elapsed_ms=1,
            input_bytes=request.input_binding.input_bytes,
            output_bytes=output_bytes,
            proposal_count=len(proposals),
            evidence_range_count=sum(len(item.evidence) for item in proposals),
            request_tokens=0,
            response_tokens=0,
            cost_microunits=0,
        )

    def produce(
        self,
        *,
        contract: ExtractorContractRequest,
        request: ExtractionRunRequest,
    ) -> ProducedExtraction:
        self._validate_contract(contract)
        if not isinstance(request, ExtractionRunRequest):
            raise TypeError("fixture extractor needs a typed run request")
        en, zh = self._validate_passages(request)
        case = request.fixture_case

        if case is FixtureExtractionCase.RETRYABLE_FAILURE:
            return ProducedExtraction(
                outcome=ExtractionOutcome.RETRYABLE_FAILURE,
                failure_code=ExtractionFailureCode.FIXTURE_RETRYABLE,
                validation=None,
                raw_output_value=None,
                proposals=(),
                usage=self._usage(request, None, ()),
            )
        if case is FixtureExtractionCase.BLOCKING_FAILURE:
            return ProducedExtraction(
                outcome=ExtractionOutcome.BLOCKING_FAILURE,
                failure_code=ExtractionFailureCode.FIXTURE_BLOCKED,
                validation=None,
                raw_output_value=None,
                proposals=(),
                usage=self._usage(request, None, ()),
            )
        if case is FixtureExtractionCase.INVALID_OUTPUT:
            raw = {
                "fixture_case": case.value,
                "malformed_entities": "not-an-array",
            }
            return ProducedExtraction(
                outcome=ExtractionOutcome.INVALID_OUTPUT,
                failure_code=ExtractionFailureCode.OUTPUT_SCHEMA_INVALID,
                validation=ExtractionOutputValidation.INVALID,
                raw_output_value=raw,
                proposals=(),
                usage=self._usage(request, raw, ()),
            )

        en_name = "Hong Kong Transport Department"
        zh_name = "香港運輸署"
        en_guidance = "revised road safety guidance"
        earlier_notice = "earlier notice"
        proposals = (
            ProposalDraft(
                local_id="entity.transport-department.en",
                kind=ExtractionProposalKind.ENTITY_MENTION,
                subject_placeholder=en_name,
                object_placeholder=None,
                predicate_hint=None,
                confidence_basis_points=9_800,
                uncertainty_codes=(),
                rationale_codes=("EXACT_FIXTURE_SPAN",),
                evidence=(_range_for(en.require_text(), en_name, en.passage_id),),
            ),
            ProposalDraft(
                local_id="entity.transport-department.zh-hk",
                kind=ExtractionProposalKind.ENTITY_MENTION,
                subject_placeholder=zh_name,
                object_placeholder=None,
                predicate_hint=None,
                confidence_basis_points=9_800,
                uncertainty_codes=(),
                rationale_codes=("EXACT_FIXTURE_SPAN",),
                evidence=(_range_for(zh.require_text(), zh_name, zh.passage_id),),
            ),
            ProposalDraft(
                local_id="equivalence.transport-department.bilingual",
                kind=ExtractionProposalKind.ENTITY_EQUIVALENCE,
                subject_placeholder=en_name,
                object_placeholder=zh_name,
                predicate_hint=None,
                confidence_basis_points=8_500,
                uncertainty_codes=("REQUIRES_EXPLICIT_RESOLUTION",),
                rationale_codes=("BILINGUAL_FIXTURE_ALIAS",),
                evidence=(
                    _range_for(en.require_text(), en_name, en.passage_id),
                    _range_for(zh.require_text(), zh_name, zh.passage_id),
                ),
            ),
        )
        if case is FixtureExtractionCase.BILINGUAL_COMPLETE:
            proposals += (
                ProposalDraft(
                    local_id="relation.guidance-supersedes-notice",
                    kind=ExtractionProposalKind.RELATION,
                    subject_placeholder=en_guidance,
                    object_placeholder=earlier_notice,
                    predicate_hint=ProposalPredicateHint.SUPERSEDES,
                    confidence_basis_points=9_500,
                    uncertainty_codes=("REQUIRES_RELATION_ADMISSION",),
                    rationale_codes=("EXPLICIT_SUPERSEDES_LANGUAGE",),
                    evidence=(
                        _range_for(en.require_text(), en_guidance, en.passage_id),
                        _range_for(en.require_text(), earlier_notice, en.passage_id),
                    ),
                ),
            )
            outcome = ExtractionOutcome.SUCCESS
            failure_code = ExtractionFailureCode.NONE
        elif case is FixtureExtractionCase.BILINGUAL_PARTIAL:
            outcome = ExtractionOutcome.PARTIAL
            failure_code = ExtractionFailureCode.FIXTURE_PARTIAL
        else:  # pragma: no cover - closed enum is exhaustively handled above
            raise ExtractionContractError("unsupported deterministic fixture case")

        raw = {
            "schema_version": "increment-4a-fixture-output-v1",
            "fixture_case": case.value,
            "entities": [
                {"local_id": item.local_id, "text": item.subject_placeholder}
                for item in proposals
                if item.kind is ExtractionProposalKind.ENTITY_MENTION
            ],
            "relations": [
                {
                    "local_id": item.local_id,
                    "subject": item.subject_placeholder,
                    "object": item.object_placeholder,
                    "predicate": (
                        None
                        if item.predicate_hint is None
                        else item.predicate_hint.value
                    ),
                }
                for item in proposals
                if item.kind is ExtractionProposalKind.RELATION
            ],
        }
        return ProducedExtraction(
            outcome=outcome,
            failure_code=failure_code,
            validation=ExtractionOutputValidation.VALID,
            raw_output_value=raw,
            proposals=proposals,
            usage=self._usage(request, raw, proposals),
        )


__all__ = ["DeterministicFixtureExtractor"]
