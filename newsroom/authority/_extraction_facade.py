from __future__ import annotations

from typing import Callable

from newsroom.authority.auth import AuthenticationProof
from newsroom.extraction.models import (
    ExtractionAttemptRequest,
    ExtractionOutputRequest,
    ExtractionRunRequest,
    ExtractorContractRequest,
    ProposalSetRequest,
)
from newsroom.extraction.records import (
    ExtractionAttempt,
    ExtractionOutput,
    ExtractionReplayBundle,
    ExtractionRun,
    ExtractorContract,
    ProposalSet,
)
from newsroom.extraction.types import (
    ExtractionAttemptId,
    ExtractionOutputId,
    ExtractionRunId,
    ExtractorContractId,
    ProposalSetId,
)


class GovernedExtraction:
    """Typed 4A facade; retained outputs and proposals stay proposal-scoped."""

    __slots__ = (
        "__register_contract",
        "__register_run",
        "__record_attempt",
        "__retain_output",
        "__retain_proposal_set",
        "__contract",
        "__current_contract",
        "__run",
        "__attempt",
        "__attempts",
        "__output",
        "__proposal_set",
        "__replay",
    )

    def __init__(
        self,
        *,
        register_contract: Callable[
            [ExtractorContractRequest, AuthenticationProof], ExtractorContract
        ],
        register_run: Callable[
            [ExtractionRunRequest, AuthenticationProof], ExtractionRun
        ],
        record_attempt: Callable[
            [ExtractionAttemptRequest, AuthenticationProof], ExtractionAttempt
        ],
        retain_output: Callable[
            [ExtractionOutputRequest, AuthenticationProof], ExtractionOutput
        ],
        retain_proposal_set: Callable[
            [ProposalSetRequest, AuthenticationProof], ProposalSet
        ],
        contract: Callable[
            [ExtractorContractId, AuthenticationProof], ExtractorContract
        ],
        current_contract: Callable[
            [str, AuthenticationProof], ExtractorContract
        ],
        run: Callable[[ExtractionRunId, AuthenticationProof], ExtractionRun],
        attempt: Callable[
            [ExtractionAttemptId, AuthenticationProof], ExtractionAttempt
        ],
        attempts: Callable[
            [ExtractionRunId, int, AuthenticationProof],
            tuple[ExtractionAttempt, ...],
        ],
        output: Callable[
            [ExtractionOutputId, AuthenticationProof], ExtractionOutput
        ],
        proposal_set: Callable[
            [ProposalSetId, AuthenticationProof], ProposalSet
        ],
        replay: Callable[
            [ExtractionRunId, AuthenticationProof], ExtractionReplayBundle
        ],
    ) -> None:
        self.__register_contract = register_contract
        self.__register_run = register_run
        self.__record_attempt = record_attempt
        self.__retain_output = retain_output
        self.__retain_proposal_set = retain_proposal_set
        self.__contract = contract
        self.__current_contract = current_contract
        self.__run = run
        self.__attempt = attempt
        self.__attempts = attempts
        self.__output = output
        self.__proposal_set = proposal_set
        self.__replay = replay

    def register_contract(
        self,
        request: ExtractorContractRequest,
        *,
        proof: AuthenticationProof,
    ) -> ExtractorContract:
        return self.__register_contract(request, proof)

    def register_run(
        self,
        request: ExtractionRunRequest,
        *,
        proof: AuthenticationProof,
    ) -> ExtractionRun:
        return self.__register_run(request, proof)

    def record_attempt(
        self,
        request: ExtractionAttemptRequest,
        *,
        proof: AuthenticationProof,
    ) -> ExtractionAttempt:
        return self.__record_attempt(request, proof)

    def retain_output(
        self,
        request: ExtractionOutputRequest,
        *,
        proof: AuthenticationProof,
    ) -> ExtractionOutput:
        return self.__retain_output(request, proof)

    def retain_proposal_set(
        self,
        request: ProposalSetRequest,
        *,
        proof: AuthenticationProof,
    ) -> ProposalSet:
        return self.__retain_proposal_set(request, proof)

    def contract(
        self,
        contract_id: ExtractorContractId,
        *,
        proof: AuthenticationProof,
    ) -> ExtractorContract:
        return self.__contract(contract_id, proof)

    def current_contract(
        self,
        contract_family: str,
        *,
        proof: AuthenticationProof,
    ) -> ExtractorContract:
        return self.__current_contract(contract_family, proof)

    def run(
        self,
        run_id: ExtractionRunId,
        *,
        proof: AuthenticationProof,
    ) -> ExtractionRun:
        return self.__run(run_id, proof)

    def attempt(
        self,
        attempt_id: ExtractionAttemptId,
        *,
        proof: AuthenticationProof,
    ) -> ExtractionAttempt:
        return self.__attempt(attempt_id, proof)

    def attempts(
        self,
        run_id: ExtractionRunId,
        *,
        limit: int,
        proof: AuthenticationProof,
    ) -> tuple[ExtractionAttempt, ...]:
        return self.__attempts(run_id, limit, proof)

    def output(
        self,
        output_id: ExtractionOutputId,
        *,
        proof: AuthenticationProof,
    ) -> ExtractionOutput:
        return self.__output(output_id, proof)

    def proposal_set(
        self,
        proposal_set_id: ProposalSetId,
        *,
        proof: AuthenticationProof,
    ) -> ProposalSet:
        return self.__proposal_set(proposal_set_id, proof)

    def replay(
        self,
        run_id: ExtractionRunId,
        *,
        proof: AuthenticationProof,
    ) -> ExtractionReplayBundle:
        return self.__replay(run_id, proof)


__all__ = ["GovernedExtraction"]
