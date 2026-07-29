from __future__ import annotations

from typing import Any, Callable, TypeVar

from newsroom.authority._security import _AuthorizationRequest
from newsroom.authority.auth import AuthenticationProof
from newsroom.authority.canonical import digest_canonical
from newsroom.authority.models import InlinePayload, SemanticCommand
from newsroom.authority.service import CommandService
from newsroom.authority.types import AggregateId, UtcTimestamp
from newsroom.extraction.models import (
    ExtractionAttemptRequest,
    ExtractionOutputRequest,
    ExtractionRunRequest,
    ExtractorContractRequest,
    ProposalSetRequest,
)
from newsroom.extraction.policy import (
    EXTRACTION_ATTEMPT_RECORD_COMMAND,
    EXTRACTION_OUTPUT_RETAIN_COMMAND,
    EXTRACTION_PROPOSAL_SET_RETAIN_COMMAND,
    EXTRACTION_RUN_REGISTER_COMMAND,
    EXTRACTOR_CONTRACT_REGISTER_COMMAND,
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
    ExtractionReadPolicy,
    ExtractionRunId,
    ExtractorContractId,
    ProposalSetId,
    bounded_text,
)

from ._extraction_store import _ExtractionAuthorityStore

_Record = TypeVar("_Record")
_EXTRACTION_READ_SCHEMA_DIGEST = digest_canonical(
    {
        "contract": "extraction-authority-read-no-payload-v1",
        "payload_mode": "NO_PAYLOAD",
        "redaction": "typed-record-or-retained-replay-bundle",
    }
)


class _ExtractionBoundary:
    """Authenticated command and policy-bounded read boundary for Increment 4A."""

    def __init__(
        self,
        *,
        store: _ExtractionAuthorityStore,
        command_service: CommandService,
        authenticator: Any,
        authorizer: Any,
        read_policy: ExtractionReadPolicy,
        clock: Callable[[], UtcTimestamp],
    ) -> None:
        self._store = store
        self._command_service = command_service
        self._authenticator = authenticator
        self._authorizer = authorizer
        self._read_policy = read_policy
        self._clock = clock

    def _commit(
        self,
        request: Any,
        proof: AuthenticationProof,
        *,
        command_type: str,
        aggregate_id: AggregateId,
        commit: Callable[..., _Record],
    ) -> _Record:
        command = SemanticCommand(
            command_type=command_type,
            aggregate_id=aggregate_id,
            expected_aggregate_version=0,
            payload=InlinePayload(request.canonical_value()),
            idempotency_key=request.idempotency_key,
        )
        grant = self._command_service._authorize_for_commit(command, proof=proof)
        return commit(grant, request=request)

    def register_contract(
        self,
        request: ExtractorContractRequest,
        proof: AuthenticationProof,
    ) -> ExtractorContract:
        if not isinstance(request, ExtractorContractRequest):
            raise TypeError("Extractor Contract must be typed")
        return self._commit(
            request,
            proof,
            command_type=EXTRACTOR_CONTRACT_REGISTER_COMMAND,
            aggregate_id=AggregateId(request.contract_id.value),
            commit=self._store.commit_extractor_contract,
        )

    def register_run(
        self,
        request: ExtractionRunRequest,
        proof: AuthenticationProof,
    ) -> ExtractionRun:
        if not isinstance(request, ExtractionRunRequest):
            raise TypeError("Extraction Run must be typed")
        return self._commit(
            request,
            proof,
            command_type=EXTRACTION_RUN_REGISTER_COMMAND,
            aggregate_id=AggregateId(request.run_id.value),
            commit=self._store.commit_extraction_run,
        )

    def record_attempt(
        self,
        request: ExtractionAttemptRequest,
        proof: AuthenticationProof,
    ) -> ExtractionAttempt:
        if not isinstance(request, ExtractionAttemptRequest):
            raise TypeError("Extraction Attempt must be typed")
        return self._commit(
            request,
            proof,
            command_type=EXTRACTION_ATTEMPT_RECORD_COMMAND,
            aggregate_id=AggregateId(request.attempt_id.value),
            commit=self._store.commit_extraction_attempt,
        )

    def retain_output(
        self,
        request: ExtractionOutputRequest,
        proof: AuthenticationProof,
    ) -> ExtractionOutput:
        if not isinstance(request, ExtractionOutputRequest):
            raise TypeError("Extraction Output must be typed")
        return self._commit(
            request,
            proof,
            command_type=EXTRACTION_OUTPUT_RETAIN_COMMAND,
            aggregate_id=AggregateId(request.output_id.value),
            commit=self._store.commit_extraction_output,
        )

    def retain_proposal_set(
        self,
        request: ProposalSetRequest,
        proof: AuthenticationProof,
    ) -> ProposalSet:
        if not isinstance(request, ProposalSetRequest):
            raise TypeError("Extraction Proposal Set must be typed")
        return self._commit(
            request,
            proof,
            command_type=EXTRACTION_PROPOSAL_SET_RETAIN_COMMAND,
            aggregate_id=AggregateId(request.proposal_set_id.value),
            commit=self._store.commit_proposal_set,
        )

    def _authorize_read(
        self,
        proof: AuthenticationProof,
        *,
        operation: str,
        aggregate_type: str,
        aggregate_id: str,
        sensitive: bool,
        limit: int | None = None,
    ) -> None:
        now = self._clock()
        authentication = self._authenticator.authenticate(proof, now=now)
        authentication.require_current(now)
        self._read_policy.require_principal(authentication.principal_id)
        if limit is not None:
            self._read_policy.require_limit(limit)
        required_scope = (
            self._read_policy.sensitive_required_scope
            if sensitive
            else self._read_policy.metadata_required_scope
        )
        trust_scope = "PROPOSED" if sensitive else "OBSERVED"
        stable = digest_canonical(
            {
                "contract": "extraction-authority-read-v1",
                "policy_digest": self._read_policy.digest,
                "operation": operation,
                "aggregate_type": aggregate_type,
                "aggregate_id": aggregate_id,
                "sensitive": sensitive,
                "limit": limit,
            }
        )
        unsigned = {
            "authentication_context_id": str(
                authentication.authentication_context_id
            ),
            "principal_id": authentication.principal_id,
            "authority_domain": authentication.authority_domain,
            "operation_type": operation,
            "required_scope": required_scope,
            "stable_semantic_request_digest": stable,
            "command_definition_digest": _EXTRACTION_READ_SCHEMA_DIGEST,
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "event_type": "extraction.authority.read",
            "event_schema_version": 1,
            "payload_mode": "NO_PAYLOAD",
            "payload_schema_version": "extraction_authority_read_v1",
            "payload_schema_contract_version": (
                "extraction-authority-read-no-payload-v1"
            ),
            "payload_schema_contract_digest": _EXTRACTION_READ_SCHEMA_DIGEST,
            "payload_canonicalizer_version": "extraction-authority-none-v1",
            "trust_scope": trust_scope,
            "security_scope": "authority.extraction",
            "retention_scope": "authority.audit",
            "object_class": None,
            "allowed_use": None,
        }
        request = _AuthorizationRequest(
            authentication_context_id=authentication.authentication_context_id,
            principal_id=authentication.principal_id,
            authority_domain=authentication.authority_domain,
            operation_type=operation,
            required_scope=required_scope,
            stable_semantic_request_digest=stable,
            command_definition_digest=_EXTRACTION_READ_SCHEMA_DIGEST,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type="extraction.authority.read",
            event_schema_version=1,
            payload_mode="NO_PAYLOAD",
            payload_schema_version="extraction_authority_read_v1",
            payload_schema_contract_version=(
                "extraction-authority-read-no-payload-v1"
            ),
            payload_schema_contract_digest=_EXTRACTION_READ_SCHEMA_DIGEST,
            payload_canonicalizer_version="extraction-authority-none-v1",
            trust_scope=trust_scope,
            security_scope="authority.extraction",
            retention_scope="authority.audit",
            object_class=None,
            allowed_use=None,
            request_digest=digest_canonical(unsigned),
        )
        decision = self._authorizer.authorize(authentication, request, now=now)
        if (
            decision.authentication_context_id
            != authentication.authentication_context_id
            or decision.authorization_request_digest != request.request_digest
        ):
            raise PermissionError(
                "extraction read authorization provenance differs"
            )
        decision.require_allowed()

    def contract(
        self,
        contract_id: ExtractorContractId,
        proof: AuthenticationProof,
    ) -> ExtractorContract:
        if not isinstance(contract_id, ExtractorContractId):
            raise TypeError("Extractor Contract identity must be typed")
        self._authorize_read(
            proof,
            operation="read:extraction:contract",
            aggregate_type="extractor_contract",
            aggregate_id=str(contract_id),
            sensitive=False,
        )
        value = self._store.extractor_contract(contract_id)
        if value is None:
            raise LookupError("Extractor Contract is not retained")
        return value

    def current_contract(
        self,
        contract_family: str,
        proof: AuthenticationProof,
    ) -> ExtractorContract:
        bounded_text(
            contract_family,
            field="contract_family",
            maximum_bytes=256,
        )
        self._authorize_read(
            proof,
            operation="read:extraction:current_contract",
            aggregate_type="extractor_contract_family",
            aggregate_id=contract_family,
            sensitive=False,
        )
        value = self._store.current_extractor_contract(contract_family)
        if value is None:
            raise LookupError("current Extractor Contract is not retained")
        return value

    def run(
        self,
        run_id: ExtractionRunId,
        proof: AuthenticationProof,
    ) -> ExtractionRun:
        if not isinstance(run_id, ExtractionRunId):
            raise TypeError("Extraction Run identity must be typed")
        self._authorize_read(
            proof,
            operation="read:extraction:run",
            aggregate_type="extraction_run",
            aggregate_id=str(run_id),
            sensitive=True,
        )
        value = self._store.extraction_run(run_id)
        if value is None:
            raise LookupError("Extraction Run is not retained")
        return value

    def attempt(
        self,
        attempt_id: ExtractionAttemptId,
        proof: AuthenticationProof,
    ) -> ExtractionAttempt:
        if not isinstance(attempt_id, ExtractionAttemptId):
            raise TypeError("Extraction Attempt identity must be typed")
        self._authorize_read(
            proof,
            operation="read:extraction:attempt",
            aggregate_type="extraction_attempt",
            aggregate_id=str(attempt_id),
            sensitive=False,
        )
        value = self._store.extraction_attempt(attempt_id)
        if value is None:
            raise LookupError("Extraction Attempt is not retained")
        return value

    def attempts(
        self,
        run_id: ExtractionRunId,
        limit: int,
        proof: AuthenticationProof,
    ) -> tuple[ExtractionAttempt, ...]:
        if not isinstance(run_id, ExtractionRunId):
            raise TypeError("Extraction Run identity must be typed")
        self._authorize_read(
            proof,
            operation="read:extraction:attempts",
            aggregate_type="extraction_run",
            aggregate_id=str(run_id),
            sensitive=False,
            limit=limit,
        )
        return self._store.extraction_attempts(run_id, limit=limit)

    def output(
        self,
        output_id: ExtractionOutputId,
        proof: AuthenticationProof,
    ) -> ExtractionOutput:
        if not isinstance(output_id, ExtractionOutputId):
            raise TypeError("Extraction Output identity must be typed")
        self._authorize_read(
            proof,
            operation="read:extraction:output",
            aggregate_type="extraction_output",
            aggregate_id=str(output_id),
            sensitive=True,
        )
        value = self._store.extraction_output(output_id)
        if value is None:
            raise LookupError("Extraction Output is not retained")
        return value

    def proposal_set(
        self,
        proposal_set_id: ProposalSetId,
        proof: AuthenticationProof,
    ) -> ProposalSet:
        if not isinstance(proposal_set_id, ProposalSetId):
            raise TypeError("Proposal Set identity must be typed")
        self._authorize_read(
            proof,
            operation="read:extraction:proposal_set",
            aggregate_type="extraction_proposal_set",
            aggregate_id=str(proposal_set_id),
            sensitive=True,
        )
        value = self._store.proposal_set(proposal_set_id)
        if value is None:
            raise LookupError("Extraction Proposal Set is not retained")
        return value

    def replay(
        self,
        run_id: ExtractionRunId,
        proof: AuthenticationProof,
    ) -> ExtractionReplayBundle:
        if not isinstance(run_id, ExtractionRunId):
            raise TypeError("Extraction Run identity must be typed")
        self._authorize_read(
            proof,
            operation="read:extraction:replay",
            aggregate_type="extraction_run",
            aggregate_id=str(run_id),
            sensitive=True,
        )
        return self._store.replay_bundle(run_id)


__all__ = ["_ExtractionBoundary"]
