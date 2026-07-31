from __future__ import annotations

from pathlib import Path

from newsroom.extraction.models import (
    ExtractionRunRequest,
    ExtractorContractRequest,
    ProducedExtraction,
)

from .models import (
    GraphitiAdapterExecution,
    GraphitiAttemptRequest,
    ProposalOnlyGraphitiAdapter,
)
from .types import GraphitiAdapterContractError, GraphitiAdapterStateError


class GraphitiProposalProducerBridge:
    """One-shot bridge into the checked Increment 4A ProposalProducer seam.

    The qualification and replay configurations intentionally retain the exact
    repository-owned extractor producer kind.  Rich 4D attempt history is
    retained separately and never changes the established 4A output vocabulary.
    """

    __slots__ = ("_adapter", "_attempt", "_workspace_root", "_execution")

    def __init__(
        self,
        *,
        adapter: ProposalOnlyGraphitiAdapter,
        attempt: GraphitiAttemptRequest,
        workspace_root: Path,
    ) -> None:
        if not isinstance(attempt, GraphitiAttemptRequest):
            raise GraphitiAdapterContractError("producer bridge attempt must be typed")
        if not isinstance(workspace_root, Path):
            raise GraphitiAdapterContractError(
                "producer bridge workspace root must be a pathlib Path"
            )
        self._adapter = adapter
        self._attempt = attempt
        self._workspace_root = workspace_root
        self._execution: GraphitiAdapterExecution | None = None

    @property
    def producer_kind(self) -> str:
        return self._attempt.extraction_contract.producer_kind

    @property
    def execution(self) -> GraphitiAdapterExecution:
        if self._execution is None:
            raise GraphitiAdapterStateError(
                "adapter execution is unavailable before producer invocation"
            )
        return self._execution

    def produce(
        self,
        *,
        contract: ExtractorContractRequest,
        request: ExtractionRunRequest,
    ) -> ProducedExtraction:
        if self._execution is not None:
            raise GraphitiAdapterStateError(
                "proposal adapter bridge is one-shot; use exact approved replay"
            )
        if contract != self._attempt.extraction_contract:
            raise GraphitiAdapterContractError(
                "producer bridge received a different extractor contract"
            )
        if request != self._attempt.extraction_request:
            raise GraphitiAdapterContractError(
                "producer bridge received a different extraction request"
            )
        self._execution = self._adapter.execute(
            attempt=self._attempt,
            workspace_root=self._workspace_root,
        )
        return self._execution.produced


__all__ = ["GraphitiProposalProducerBridge"]
