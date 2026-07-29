from __future__ import annotations

from dataclasses import dataclass

from newsroom.authority.types import EventId, UtcTimestamp

from .models import (
    ExtractionAttemptRequest,
    ExtractionOutputRequest,
    ExtractionRunRequest,
    ExtractorContractRequest,
    ProposalSetRequest,
)
from .types import ExtractionContractError, canonical_digest


def _validate_committed(
    request: object,
    *,
    event_id: EventId,
    aggregate_version: int,
    recorded_at: UtcTimestamp,
    record_digest: str,
    replayed: bool,
) -> None:
    if not isinstance(event_id, EventId):
        raise ExtractionContractError("authority event identity must be typed")
    if isinstance(aggregate_version, bool) or aggregate_version != 1:
        raise ExtractionContractError("immutable extraction records use version one")
    if not isinstance(recorded_at, UtcTimestamp):
        raise ExtractionContractError("recording time must be typed UTC")
    canonical_digest(record_digest, field="extraction_record_digest")
    if record_digest != request.digest:  # type: ignore[attr-defined]
        raise ExtractionContractError("record digest differs from retained request")
    if not isinstance(replayed, bool):
        raise ExtractionContractError("replay marker must be boolean")


@dataclass(frozen=True, slots=True)
class ExtractorContract:
    request: ExtractorContractRequest
    event_id: EventId
    aggregate_version: int
    recorded_at: UtcTimestamp
    canonical_digest: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.request, ExtractorContractRequest):
            raise ExtractionContractError("extractor contract payload must be retained")
        _validate_committed(
            self.request,
            event_id=self.event_id,
            aggregate_version=self.aggregate_version,
            recorded_at=self.recorded_at,
            record_digest=self.canonical_digest,
            replayed=self.replayed,
        )


@dataclass(frozen=True, slots=True)
class ExtractionRun:
    request: ExtractionRunRequest
    event_id: EventId
    aggregate_version: int
    recorded_at: UtcTimestamp
    canonical_digest: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.request, ExtractionRunRequest):
            raise ExtractionContractError("extraction run payload must be retained")
        _validate_committed(
            self.request,
            event_id=self.event_id,
            aggregate_version=self.aggregate_version,
            recorded_at=self.recorded_at,
            record_digest=self.canonical_digest,
            replayed=self.replayed,
        )


@dataclass(frozen=True, slots=True)
class ExtractionAttempt:
    request: ExtractionAttemptRequest
    event_id: EventId
    aggregate_version: int
    recorded_at: UtcTimestamp
    canonical_digest: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.request, ExtractionAttemptRequest):
            raise ExtractionContractError("extraction attempt payload must be retained")
        _validate_committed(
            self.request,
            event_id=self.event_id,
            aggregate_version=self.aggregate_version,
            recorded_at=self.recorded_at,
            record_digest=self.canonical_digest,
            replayed=self.replayed,
        )


@dataclass(frozen=True, slots=True)
class ExtractionOutput:
    request: ExtractionOutputRequest
    event_id: EventId
    aggregate_version: int
    recorded_at: UtcTimestamp
    canonical_digest: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.request, ExtractionOutputRequest):
            raise ExtractionContractError("extraction output payload must be retained")
        _validate_committed(
            self.request,
            event_id=self.event_id,
            aggregate_version=self.aggregate_version,
            recorded_at=self.recorded_at,
            record_digest=self.canonical_digest,
            replayed=self.replayed,
        )


@dataclass(frozen=True, slots=True)
class ProposalSet:
    request: ProposalSetRequest
    event_id: EventId
    aggregate_version: int
    recorded_at: UtcTimestamp
    canonical_digest: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.request, ProposalSetRequest):
            raise ExtractionContractError("proposal set payload must be retained")
        _validate_committed(
            self.request,
            event_id=self.event_id,
            aggregate_version=self.aggregate_version,
            recorded_at=self.recorded_at,
            record_digest=self.canonical_digest,
            replayed=self.replayed,
        )


@dataclass(frozen=True, slots=True)
class ExtractionReplayBundle:
    run: ExtractionRun
    attempt: ExtractionAttempt
    output: ExtractionOutput
    proposal_set: ProposalSet | None

    def __post_init__(self) -> None:
        if str(self.attempt.request.run_id) != str(self.run.request.run_id):
            raise ExtractionContractError("replay attempt differs from run")
        if (
            str(self.output.request.run_id) != str(self.run.request.run_id)
            or str(self.output.request.attempt_id) != str(self.attempt.request.attempt_id)
        ):
            raise ExtractionContractError("replay output lineage differs")
        if self.proposal_set is not None and (
            str(self.proposal_set.request.run_id) != str(self.run.request.run_id)
            or str(self.proposal_set.request.attempt_id) != str(self.attempt.request.attempt_id)
            or str(self.proposal_set.request.output_id) != str(self.output.request.output_id)
        ):
            raise ExtractionContractError("replay proposal lineage differs")


__all__ = [
    "ExtractionAttempt",
    "ExtractionOutput",
    "ExtractionReplayBundle",
    "ExtractionRun",
    "ExtractorContract",
    "ProposalSet",
]
