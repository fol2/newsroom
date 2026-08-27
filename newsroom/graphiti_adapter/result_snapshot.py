"""Validate and restore immutable Graphiti completion snapshots."""

from __future__ import annotations

from dataclasses import dataclass

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.extraction.models import ProducedExtraction, ProposalDraft
from newsroom.extraction.types import (
    EvidenceRange,
    ExtractionContractError,
    ExtractionFailureCode,
    ExtractionOutcome,
    ExtractionOutputValidation,
    ExtractionPassageId,
    ExtractionProposalKind,
    ProposalPredicateHint,
)
from newsroom.graphiti_adapter.contracts import GRAPHITI_PROMPT_COMPONENT
from newsroom.graphiti_adapter.cli_process import validated_process_exit_diagnostic
from newsroom.graphiti_adapter.combined_temporal_types import (
    CombinedTemporalFailureCode,
)
from newsroom.graphiti_adapter.evaluation_packet import (
    GRAPHITI_CHAT_FALLBACK,
    GRAPHITI_CHAT_MODEL,
    GRAPHITI_CORE_RELEASE,
    GRAPHITI_EMBEDDING_MODEL,
    GRAPHITI_GENERATION_ID,
    GRAPHITI_WORKSPACE_GROUP,
)
from newsroom.graphiti_adapter.models import GraphitiAttemptRequest
from newsroom.graphiti_adapter.recovery_vocabulary import (
    GraphitiRecoveryClassification,
)
from newsroom.graphiti_adapter.result_mapping import produced_extraction
from newsroom.graphiti_adapter.types import GraphitiAdapterContractError


@dataclass(frozen=True, slots=True)
class SnapshotRestoration:
    produced: ProducedExtraction
    chat_invocations: tuple[dict[str, object], ...]
    embedding_usage: dict[str, object]
    provider_attempt_number: int
    recovery_classification: GraphitiRecoveryClassification


def _proposal_from_value(value: object) -> ProposalDraft:
    if not isinstance(value, dict):
        raise GraphitiAdapterContractError("retained proposal snapshot is malformed")
    evidence_values = value.get("evidence")
    if not isinstance(evidence_values, list) or any(
        not isinstance(item, dict) for item in evidence_values
    ):
        raise GraphitiAdapterContractError("retained proposal evidence is malformed")
    uncertainty = value.get("uncertainty_codes")
    rationale = value.get("rationale_codes")
    if not isinstance(uncertainty, list) or not isinstance(rationale, list):
        raise GraphitiAdapterContractError("retained proposal codes are malformed")
    try:
        evidence = tuple(
            EvidenceRange(
                passage_id=ExtractionPassageId.parse(str(item["passage_id"])),
                start_byte=int(item["start_byte"]),
                end_byte=int(item["end_byte"]),
                evidence_text_digest=str(item["evidence_text_digest"]),
            )
            for item in evidence_values
        )
        predicate = value.get("predicate_hint")
        return ProposalDraft(
            local_id=str(value["local_id"]),
            kind=ExtractionProposalKind(str(value["kind"])),
            subject_placeholder=str(value["subject_placeholder"]),
            object_placeholder=(
                None
                if value.get("object_placeholder") is None
                else str(value["object_placeholder"])
            ),
            predicate_hint=(
                None if predicate is None else ProposalPredicateHint(str(predicate))
            ),
            confidence_basis_points=(
                None
                if value.get("confidence_basis_points") is None
                else int(value["confidence_basis_points"])
            ),
            uncertainty_codes=tuple(str(item) for item in uncertainty),
            rationale_codes=tuple(str(item) for item in rationale),
            evidence=evidence,
        )
    except (KeyError, TypeError, ValueError, ExtractionContractError) as exc:
        raise GraphitiAdapterContractError(
            "retained proposal snapshot is malformed"
        ) from exc


def restore_validated_snapshot(
    *, raw: dict[str, object], attempt: GraphitiAttemptRequest
) -> SnapshotRestoration:
    """Verify original bytes, then bind an optional retry receipt envelope."""

    retained_digest = raw.get("raw_output_digest")
    unsigned = dict(raw)
    unsigned.pop("raw_output_digest", None)
    if retained_digest != digest_bytes(canonical_json_bytes(unsigned)):
        raise GraphitiAdapterContractError(
            "retained Graphiti result inner digest differs"
        )
    retained_attempt = raw.get("attempt_number")
    provider_attempt = raw.get("provider_attempt_number")
    if (
        not isinstance(retained_attempt, int)
        or isinstance(retained_attempt, bool)
        or not 1 <= retained_attempt <= attempt.attempt_number
        or not isinstance(provider_attempt, int)
        or isinstance(provider_attempt, bool)
        or not 1 <= provider_attempt <= retained_attempt
    ):
        raise GraphitiAdapterContractError(
            "retained Graphiti attempt identity is malformed"
        )
    reference = attempt.reference_time
    expected = {
        "workspace_group": GRAPHITI_WORKSPACE_GROUP,
        "generation_id": attempt.generation_id or GRAPHITI_GENERATION_ID,
        "episode_uuid": attempt.episode_uuid or str(attempt.attempt_id),
        "predecessor_episode_uuid": attempt.predecessor_episode_uuid,
        "temporal_basis": attempt.temporal_basis,
        "reference_time": None if reference is None else reference.to_text(),
        "framework": GRAPHITI_CORE_RELEASE,
        "chat": GRAPHITI_CHAT_MODEL,
        "chat_fallback": GRAPHITI_CHAT_FALLBACK,
        "embedding": GRAPHITI_EMBEDDING_MODEL,
        "prompt_version": GRAPHITI_PROMPT_COMPONENT.component_version,
    }
    if any(raw.get(key) != value for key, value in expected.items()):
        raise GraphitiAdapterContractError(
            "retained Graphiti result differs from the current immutable attempt"
        )
    retained_passages = raw.get("passages")
    current_passages = [item.canonical_value() for item in attempt.manifest.passages]
    if (
        not isinstance(retained_passages, list)
        or len(retained_passages) != len(current_passages)
        or any(not isinstance(item, dict) for item in retained_passages)
    ):
        raise GraphitiAdapterContractError("retained Graphiti passages are malformed")
    # A renewed current rights decision has a new access-decision identity.
    # Completion recovery preserves the original authority receipt while the
    # control plane separately proves the latest global/source gates at dispatch.
    stable_retained = [
        {key: value for key, value in item.items() if key != "access_decision_id"}
        for item in retained_passages
    ]
    stable_current = [
        {key: value for key, value in item.items() if key != "access_decision_id"}
        for item in current_passages
    ]
    if stable_retained != stable_current or any(
        not isinstance(item.get("access_decision_id"), str)
        or not item["access_decision_id"]
        for item in retained_passages
    ):
        raise GraphitiAdapterContractError(
            "retained Graphiti passage content or original authority differs"
        )
    recovered_raw = dict(raw)
    if retained_attempt != attempt.attempt_number:
        recovered_raw["attempt_number"] = attempt.attempt_number
        recovered_raw["recovered_validated_raw_digest"] = retained_digest
        recovered_raw["recovery_classification"] = (
            GraphitiRecoveryClassification.RECOVERED_IMMUTABLE_COMPLETE
        )
        recovered_raw.pop("raw_output_digest", None)
        recovered_raw["raw_output_digest"] = digest_bytes(
            canonical_json_bytes(recovered_raw)
        )
    proposals_value = recovered_raw.get("proposals")
    invocations = recovered_raw.get("chat_invocations")
    usage = recovered_raw.get("embedding_usage")
    entities = recovered_raw.get("entities")
    relations = recovered_raw.get("relations")
    if (
        not isinstance(proposals_value, list)
        or not isinstance(invocations, list)
        or any(not isinstance(item, dict) for item in invocations)
        or not isinstance(usage, dict)
        or not isinstance(entities, list)
        or not isinstance(relations, list)
        or recovered_raw.get("proposal_count") != len(proposals_value)
        or recovered_raw.get("entity_count") != len(entities)
        or recovered_raw.get("relation_count") != len(relations)
        or recovered_raw.get("chat_invocation_count") != len(invocations)
    ):
        raise GraphitiAdapterContractError("retained Graphiti result is malformed")
    try:
        for invocation in invocations:
            if "process_exit_diagnostic" in invocation:
                validated_process_exit_diagnostic(
                    invocation["process_exit_diagnostic"]
                )
    except ValueError as exc:
        raise GraphitiAdapterContractError(
            "retained Graphiti process-exit diagnostic is malformed"
        ) from exc
    proposals = tuple(
        sorted(
            (_proposal_from_value(item) for item in proposals_value),
            key=lambda item: item.local_id,
        )
    )
    embedding_usage = dict(usage)
    combined_failure = recovered_raw.get("combined_temporal_failure_code")
    pipeline_failed = (
        combined_failure == CombinedTemporalFailureCode.PIPELINE_FAILED.value
    )
    produced = produced_extraction(
        attempt,
        outcome=(
            ExtractionOutcome.RETRYABLE_FAILURE
            if pipeline_failed
            else (
                ExtractionOutcome.INVALID_OUTPUT
                if isinstance(combined_failure, str)
                else ExtractionOutcome.SUCCESS
            )
        ),
        failure_code=(
            ExtractionFailureCode.PRODUCER_INTERNAL_ERROR
            if pipeline_failed
            else (
                ExtractionFailureCode.OUTPUT_SCHEMA_INVALID
                if isinstance(combined_failure, str)
                else ExtractionFailureCode.NONE
            )
        ),
        validation=(
            None
            if pipeline_failed
            else (
                ExtractionOutputValidation.INVALID
                if isinstance(combined_failure, str)
                else ExtractionOutputValidation.VALID
            )
        ),
        raw=None if pipeline_failed else recovered_raw,
        proposals=proposals,
        embedding_usage=embedding_usage,
        attempt_receipt=recovered_raw if pipeline_failed else None,
    )
    produced.usage.require_within(attempt.extraction_request.budget)
    return SnapshotRestoration(
        produced=produced,
        chat_invocations=tuple(dict(item) for item in invocations),
        embedding_usage=embedding_usage,
        provider_attempt_number=provider_attempt,
        recovery_classification=(
            GraphitiRecoveryClassification.RECOVERED_IMMUTABLE_COMPLETE
        ),
    )


__all__ = ["SnapshotRestoration", "restore_validated_snapshot"]
