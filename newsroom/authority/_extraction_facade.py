from __future__ import annotations

from typing import Callable

from newsroom.authority.auth import AuthenticationProof
from newsroom.extraction.models import (
    ExtractionRawOutput,
    ExtractionRunMetadata,
    ExtractionRunRequest,
    ExtractionRunVersion,
    ExtractorContract,
    ExtractorContractRequest,
    ProposalEnvelope,
)
from newsroom.extraction.types import (
    ExtractionOutputId,
    ExtractionRunId,
    ExtractionRunVersionId,
    ExtractorContractId,
)


class GovernedExtractionRecords:
    """Authenticated typed facade; no SQLite handle or producer escapes."""

    __slots__ = (
        "__register_contract",
        "__execute",
        "__contract",
        "__metadata",
        "__run_history",
        "__proposals",
        "__raw_output",
    )

    def __init__(
        self,
        *,
        register_contract: Callable[
            [ExtractorContractRequest, AuthenticationProof], ExtractorContract
        ],
        execute: Callable[
            [ExtractionRunRequest, AuthenticationProof], ExtractionRunVersion
        ],
        contract: Callable[
            [ExtractorContractId, AuthenticationProof], ExtractorContract
        ],
        metadata: Callable[
            [ExtractionRunVersionId, AuthenticationProof], ExtractionRunMetadata
        ],
        run_history: Callable[
            [ExtractionRunId, int, AuthenticationProof],
            tuple[ExtractionRunMetadata, ...],
        ],
        proposals: Callable[
            [ExtractionRunVersionId, AuthenticationProof],
            tuple[ProposalEnvelope, ...],
        ],
        raw_output: Callable[
            [ExtractionOutputId, AuthenticationProof], ExtractionRawOutput
        ],
    ) -> None:
        self.__register_contract = register_contract
        self.__execute = execute
        self.__contract = contract
        self.__metadata = metadata
        self.__run_history = run_history
        self.__proposals = proposals
        self.__raw_output = raw_output

    def register_contract(
        self,
        request: ExtractorContractRequest,
        *,
        proof: AuthenticationProof,
    ) -> ExtractorContract:
        return self.__register_contract(request, proof)

    def execute(
        self,
        request: ExtractionRunRequest,
        *,
        proof: AuthenticationProof,
    ) -> ExtractionRunVersion:
        return self.__execute(request, proof)

    def contract(
        self,
        contract_id: ExtractorContractId,
        *,
        proof: AuthenticationProof,
    ) -> ExtractorContract:
        return self.__contract(contract_id, proof)

    def metadata(
        self,
        run_version_id: ExtractionRunVersionId,
        *,
        proof: AuthenticationProof,
    ) -> ExtractionRunMetadata:
        return self.__metadata(run_version_id, proof)

    def run_history(
        self,
        run_id: ExtractionRunId,
        *,
        limit: int,
        proof: AuthenticationProof,
    ) -> tuple[ExtractionRunMetadata, ...]:
        return self.__run_history(run_id, limit, proof)

    def proposals(
        self,
        run_version_id: ExtractionRunVersionId,
        *,
        proof: AuthenticationProof,
    ) -> tuple[ProposalEnvelope, ...]:
        return self.__proposals(run_version_id, proof)

    def raw_output(
        self,
        output_id: ExtractionOutputId,
        *,
        proof: AuthenticationProof,
    ) -> ExtractionRawOutput:
        return self.__raw_output(output_id, proof)


__all__ = ["GovernedExtractionRecords"]
