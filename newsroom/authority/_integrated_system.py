from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ._capability import _CapabilityIssuer
from ._event_system import _ReadBoundary
from ._integrated_store import _IntegratedCandidateStore
from .auth import AuthenticationProof
from .models import InlinePayload, SemanticCommand
from .persistence import AuthorityEvents, EventReadPolicy
from .policy import CommandRegistry, PayloadSchemaRegistry
from .service import CommandService
from .types import UtcTimestamp
from newsroom.integrated.models import (
    CandidateAdmissionRequest,
    CandidateAdmissionView,
    IntegratedFixtureManifest,
    IntegratedRetrievalContext,
)
from newsroom.integrated.policy import (
    CANDIDATE_ADMISSION_COMMAND,
    merge_integrated_authority_registries,
)
from newsroom.projection.policy import ProjectionContractRegistry


class CandidateAdmissions:
    """Authenticated deterministic Candidate authority; no model write path."""

    __slots__ = ("__admit",)

    def __init__(
        self,
        admit: Callable[
            [
                CandidateAdmissionRequest,
                IntegratedRetrievalContext,
                IntegratedFixtureManifest,
                AuthenticationProof,
            ],
            CandidateAdmissionView,
        ],
    ) -> None:
        self.__admit = admit

    def admit(
        self,
        request: CandidateAdmissionRequest,
        *,
        context: IntegratedRetrievalContext,
        manifest: IntegratedFixtureManifest,
        proof: AuthenticationProof,
    ) -> CandidateAdmissionView:
        return self.__admit(request, context, manifest, proof)


class IntegratedCandidateAuthoritySystem:
    """Candidate authority and bounded event evidence over one SQLite writer."""

    __slots__ = ("events", "candidates", "__close")

    def __init__(
        self,
        *,
        events: AuthorityEvents,
        candidates: CandidateAdmissions,
        close: Callable[[], None],
    ) -> None:
        self.events = events
        self.candidates = candidates
        self.__close = close

    def close(self) -> None:
        self.__close()

    def __enter__(self) -> IntegratedCandidateAuthoritySystem:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


class _CandidateAdmissionBoundary:
    def __init__(
        self,
        *,
        store: _IntegratedCandidateStore,
        command_service: CommandService,
    ) -> None:
        self._store = store
        self._command_service = command_service

    def admit(
        self,
        request: CandidateAdmissionRequest,
        context: IntegratedRetrievalContext,
        manifest: IntegratedFixtureManifest,
        proof: AuthenticationProof,
    ) -> CandidateAdmissionView:
        if not isinstance(request, CandidateAdmissionRequest):
            raise TypeError("candidate admission requires a typed request")
        if not isinstance(context, IntegratedRetrievalContext):
            raise TypeError(
                "candidate admission requires a typed retrieval context"
            )
        if not isinstance(manifest, IntegratedFixtureManifest):
            raise TypeError(
                "candidate admission requires a typed fixture manifest"
            )

        collision_digest = self._store.semantic_collision_digest(
            request,
            manifest,
            context,
        )
        payload = {
            "proposal_id": str(request.proposal_id),
            "route": request.route.value,
            "fixture_id": str(request.fixture_id),
            "retrieval_context_digest": context.context_digest,
            "manifest_digest": manifest.manifest_digest,
            "semantic_collision_digest": collision_digest,
        }
        command = SemanticCommand(
            command_type=CANDIDATE_ADMISSION_COMMAND,
            aggregate_id=request.proposal_id.as_aggregate_id(),
            expected_aggregate_version=0,
            payload=InlinePayload(payload),
            idempotency_key=request.idempotency_key,
        )
        grant = self._command_service._authorize_for_commit(
            command,
            proof=proof,
        )
        return self._store.commit_candidate_admission(
            grant,
            request=request,
            context=context,
            manifest=manifest,
            semantic_collision_digest=collision_digest,
        )


def open_candidate_admission_authority_system(
    *,
    path: Path,
    registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
    contracts: ProjectionContractRegistry,
    authenticator: Any,
    authorizer: Any,
    event_read_policy: EventReadPolicy,
    command_service_version: str = "authority-command-v1",
    busy_timeout_ms: int = 5_000,
    clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
) -> IntegratedCandidateAuthoritySystem:
    """Open the exact deterministic Candidate-admission authority boundary."""

    merged_registry, merged_schemas = merge_integrated_authority_registries(
        command_registry=registry,
        payload_schemas=payload_schemas,
    )
    issuer = _CapabilityIssuer(
        command_registry=merged_registry,
        payload_schemas=merged_schemas,
    )
    store: _IntegratedCandidateStore | None = None
    try:
        store = _IntegratedCandidateStore(
            path,
            issuer=issuer,
            command_registry=merged_registry,
            payload_schemas=merged_schemas,
            command_service_version=command_service_version,
            busy_timeout_ms=busy_timeout_ms,
            clock=clock,
            contracts=contracts,
        )
        command_service = CommandService(
            registry=merged_registry,
            payload_schemas=merged_schemas,
            authenticator=authenticator,
            authorizer=authorizer,
            committed_lookup=store,
            clock=clock,
            _issuer=issuer,
        )
        read_boundary = _ReadBoundary(
            store=store,
            policy=event_read_policy,
            authenticator=authenticator,
            authorizer=authorizer,
            clock=clock,
        )
        boundary = _CandidateAdmissionBoundary(
            store=store,
            command_service=command_service,
        )
        return IntegratedCandidateAuthoritySystem(
            events=AuthorityEvents(
                policy_id=event_read_policy.policy_id,
                read=read_boundary.events_after,
                provenance=read_boundary.provenance,
                result=read_boundary.command_result,
            ),
            candidates=CandidateAdmissions(boundary.admit),
            close=store.close,
        )
    except Exception:
        if store is not None:
            store.close()
        raise


__all__ = [
    "CandidateAdmissions",
    "IntegratedCandidateAuthoritySystem",
    "open_candidate_admission_authority_system",
]
