from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from newsroom.authority._security import _AuthorizationRequest
from newsroom.authority.auth import AuthenticationProof
from newsroom.authority.canonical import digest_canonical
from newsroom.authority.models import InlinePayload, SemanticCommand
from newsroom.authority.service import CommandService
from newsroom.authority.types import AggregateId, TrustScope, UtcTimestamp
from newsroom.extraction.models import (
    ExtractionRawOutput,
    ExtractionRunMetadata,
    ExtractionRunRequest,
    ExtractionRunVersion,
    ExtractionUsage,
    ExtractorContract,
    ExtractorContractRequest,
    ProposalEnvelope,
    ProposalProducer,
    ProducedExtraction,
)
from newsroom.extraction.fixtures import fixture_case_for_contract
from newsroom.extraction.output_schema import normalize_fixture_production
from newsroom.extraction.policy import (
    EXTRACTION_RUN_EXECUTE_COMMAND,
    EXTRACTOR_CONTRACT_REGISTER_COMMAND,
)
from newsroom.extraction.producer import DeterministicFixtureExtractor
from newsroom.extraction.types import (
    ExtractionContractError,
    ExtractionFailureCode,
    ExtractionOutcome,
    ExtractionOutputId,
    ExtractionReadPolicy,
    ExtractionRunId,
    ExtractionRunVersionId,
    ExtractorContractId,
    authority_elapsed_ms,
)

from ._extraction_store import _ExtractionAuthorityStore


_EXTRACTION_READ_SCHEMA_DIGEST = digest_canonical(
    {
        "contract": "extraction-authority-read-no-payload-v1",
        "payload_mode": "NO_PAYLOAD",
        "redaction": "metadata-proposals-or-explicit-raw-output-scope",
    }
)


class _ExtractionBoundary:
    def __init__(
        self,
        *,
        store: _ExtractionAuthorityStore,
        command_service: CommandService,
        authenticator: Any,
        authorizer: Any,
        read_policy: ExtractionReadPolicy,
        producer: ProposalProducer,
        clock: Callable[[], UtcTimestamp],
    ) -> None:
        if type(producer) is not DeterministicFixtureExtractor:
            raise TypeError(
                "Increment 4A accepts only the repository-owned deterministic producer"
            )
        self._store = store
        self._command_service = command_service
        self._authenticator = authenticator
        self._authorizer = authorizer
        self._read_policy = read_policy
        self._producer = producer
        self._clock = clock

    def register_contract(
        self,
        request: ExtractorContractRequest,
        proof: AuthenticationProof,
    ) -> ExtractorContract:
        if not isinstance(request, ExtractorContractRequest):
            raise TypeError("extractor contract must be a typed request")
        command = SemanticCommand(
            command_type=EXTRACTOR_CONTRACT_REGISTER_COMMAND,
            aggregate_id=AggregateId(request.contract_id.value),
            expected_aggregate_version=0,
            payload=InlinePayload(request.canonical_value()),
            idempotency_key=request.idempotency_key,
        )
        grant = self._command_service._authorize_for_commit(command, proof=proof)
        return self._store.commit_extractor_contract(grant, request=request)

    @staticmethod
    def _failed_production(
        request: ExtractionRunRequest,
        *,
        outcome: ExtractionOutcome,
        failure_code: ExtractionFailureCode,
    ) -> ProducedExtraction:
        return ProducedExtraction(
            outcome=outcome,
            failure_code=failure_code,
            validation=None,
            raw_output_value=None,
            proposals=(),
            usage=ExtractionUsage(
                elapsed_ms=0,
                input_bytes=request.input_binding.input_bytes,
                output_bytes=0,
                proposal_count=0,
                evidence_range_count=0,
                request_tokens=0,
                response_tokens=0,
                cost_microunits=0,
            ),
        )

    def execute(
        self,
        request: ExtractionRunRequest,
        proof: AuthenticationProof,
    ) -> ExtractionRunVersion:
        if not isinstance(request, ExtractionRunRequest):
            raise TypeError("extraction run must be a typed request")
        command = SemanticCommand(
            command_type=EXTRACTION_RUN_EXECUTE_COMMAND,
            aggregate_id=AggregateId(request.run_version_id.value),
            expected_aggregate_version=0,
            payload=InlinePayload(request.canonical_value()),
            idempotency_key=request.idempotency_key,
        )
        grant = self._command_service._authorize_for_commit(command, proof=proof)
        if grant.replay_of_command_id is not None:
            return self._store.commit_extraction_run(
                grant,
                request=request,
                production=None,
                started_at=None,
                ended_at=None,
            )

        # Authorisation happens before any producer work. The preflight then
        # resolves the exact current source/object rights and fixture bytes.
        contract = self._store.preflight_extraction(
            request,
            principal_id=grant.authentication.principal_id,
        )
        started_at = self._clock()
        try:
            # Contract compatibility is checked before any producer code sees
            # the rights-permitted passage bytes. An incompatible attempt is
            # still retained honestly as a blocking Run Version.
            fixture_case_for_contract(contract.request)
        except ExtractionContractError:
            production = self._failed_production(
                request,
                outcome=ExtractionOutcome.BLOCKING_FAILURE,
                failure_code=ExtractionFailureCode.POLICY_BLOCKED,
            )
        else:
            try:
                produced = self._producer.produce(
                    contract=contract.request,
                    request=request,
                )
            except ExtractionContractError:
                production = self._failed_production(
                    request,
                    outcome=ExtractionOutcome.BLOCKING_FAILURE,
                    failure_code=ExtractionFailureCode.POLICY_BLOCKED,
                )
            except Exception:
                # Arbitrary producer exception text is deliberately discarded.
                production = self._failed_production(
                    request,
                    outcome=ExtractionOutcome.RETRYABLE_FAILURE,
                    failure_code=ExtractionFailureCode.PRODUCER_INTERNAL_ERROR,
                )
            else:
                if not isinstance(produced, ProducedExtraction):
                    production = self._failed_production(
                        request,
                        outcome=ExtractionOutcome.RETRYABLE_FAILURE,
                        failure_code=ExtractionFailureCode.PRODUCER_INTERNAL_ERROR,
                    )
                else:
                    try:
                        production = normalize_fixture_production(
                            contract=contract.request,
                            request=request,
                            production=produced,
                        )
                    except ExtractionContractError:
                        production = self._failed_production(
                            request,
                            outcome=ExtractionOutcome.BLOCKING_FAILURE,
                            failure_code=ExtractionFailureCode.POLICY_BLOCKED,
                        )
        ended_at = self._clock()
        elapsed_ms = authority_elapsed_ms(started_at, ended_at)
        if elapsed_ms > request.budget.timeout_ms:
            # The deterministic producer runs in-process in 4A. Authority
            # therefore classifies a returned over-budget attempt rather than
            # pretending it completed successfully. Any untrusted output and
            # proposals are discarded before persistence; only bounded,
            # redacted resource usage survives in an immutable retryable
            # attempt. Interruptible external-adapter execution remains a
            # separately owner-authorised later boundary.
            production = ProducedExtraction(
                outcome=ExtractionOutcome.RETRYABLE_FAILURE,
                failure_code=ExtractionFailureCode.EXECUTION_TIMEOUT,
                validation=None,
                raw_output_value=None,
                proposals=(),
                usage=ExtractionUsage(
                    elapsed_ms=elapsed_ms,
                    input_bytes=request.input_binding.input_bytes,
                    output_bytes=0,
                    proposal_count=0,
                    evidence_range_count=0,
                    request_tokens=production.usage.request_tokens,
                    response_tokens=production.usage.response_tokens,
                    cost_microunits=production.usage.cost_microunits,
                ),
            )
        else:
            production = replace(
                production,
                usage=replace(production.usage, elapsed_ms=elapsed_ms),
            )
        return self._store.commit_extraction_run(
            grant,
            request=request,
            production=production,
            started_at=started_at,
            ended_at=ended_at,
        )

    def _authorize_read(
        self,
        proof: AuthenticationProof,
        *,
        operation: str,
        aggregate_type: str,
        aggregate_id: str,
        required_scope: str,
        trust_scope: TrustScope,
        limit: int | None = None,
    ) -> None:
        now = self._clock()
        authentication = self._authenticator.authenticate(proof, now=now)
        authentication.require_current(now)
        self._read_policy.require_principal(authentication.principal_id)
        if limit is not None:
            self._read_policy.require_limit(limit)
        stable = digest_canonical(
            {
                "contract": "extraction-authority-read-v1",
                "policy_digest": self._read_policy.digest,
                "operation": operation,
                "aggregate_type": aggregate_type,
                "aggregate_id": aggregate_id,
                "required_scope": required_scope,
                "trust_scope": trust_scope.value,
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
            "trust_scope": trust_scope.value,
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
            trust_scope=trust_scope.value,
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
            raise TypeError("extractor contract identity must be typed")
        self._authorize_read(
            proof,
            operation="read:extraction:contract",
            aggregate_type="extractor_contract",
            aggregate_id=str(contract_id),
            required_scope=self._read_policy.metadata_required_scope,
            trust_scope=TrustScope.ADMITTED,
        )
        return self._store.contract(contract_id)

    def metadata(
        self,
        run_version_id: ExtractionRunVersionId,
        proof: AuthenticationProof,
    ) -> ExtractionRunMetadata:
        if not isinstance(run_version_id, ExtractionRunVersionId):
            raise TypeError("run version identity must be typed")
        self._authorize_read(
            proof,
            operation="read:extraction:metadata",
            aggregate_type="extraction_run_version",
            aggregate_id=str(run_version_id),
            required_scope=self._read_policy.metadata_required_scope,
            trust_scope=TrustScope.PROPOSED,
        )
        return self._store.metadata(run_version_id)

    def run_history(
        self,
        run_id: ExtractionRunId,
        limit: int,
        proof: AuthenticationProof,
    ) -> tuple[ExtractionRunMetadata, ...]:
        if not isinstance(run_id, ExtractionRunId):
            raise TypeError("run identity must be typed")
        self._authorize_read(
            proof,
            operation="read:extraction:run_history",
            aggregate_type="extraction_run",
            aggregate_id=str(run_id),
            required_scope=self._read_policy.metadata_required_scope,
            trust_scope=TrustScope.PROPOSED,
            limit=limit,
        )
        return self._store.run_history(run_id, limit=limit)

    def proposals(
        self,
        run_version_id: ExtractionRunVersionId,
        proof: AuthenticationProof,
    ) -> tuple[ProposalEnvelope, ...]:
        if not isinstance(run_version_id, ExtractionRunVersionId):
            raise TypeError("run version identity must be typed")
        self._authorize_read(
            proof,
            operation="read:extraction:proposals",
            aggregate_type="extraction_run_version",
            aggregate_id=str(run_version_id),
            required_scope=self._read_policy.proposal_required_scope,
            trust_scope=TrustScope.PROPOSED,
        )
        return self._store.proposals(run_version_id)

    def raw_output(
        self,
        output_id: ExtractionOutputId,
        proof: AuthenticationProof,
    ) -> ExtractionRawOutput:
        if not isinstance(output_id, ExtractionOutputId):
            raise TypeError("output identity must be typed")
        self._authorize_read(
            proof,
            operation="read:extraction:raw_output",
            aggregate_type="extraction_output",
            aggregate_id=str(output_id),
            required_scope=self._read_policy.raw_output_required_scope,
            trust_scope=TrustScope.PROPOSED,
        )
        return self._store.raw_output(output_id)


__all__ = ["_ExtractionBoundary"]
