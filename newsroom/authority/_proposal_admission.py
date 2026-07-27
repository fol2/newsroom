from __future__ import annotations

from typing import Any

from newsroom.authority._capability import _AuthorizedCommandGrant
from newsroom.authority.auth import AuthenticationProof
from newsroom.authority.models import InlinePayload, SemanticCommand
from newsroom.authority.service import CommandService
from newsroom.authority.types import AggregateId

from ._check_store import _CheckAuthorityStore
from ._proposal_admission_commit import _ProposalAdmissionCommitMixin
from ._proposal_admission_planning import _ProposalAdmissionPlanningMixin
from ._proposal_admission_validation import _ProposalAdmissionValidationMixin


class _ProposalAdmissionBoundary(
    _ProposalAdmissionCommitMixin,
    _ProposalAdmissionPlanningMixin,
    _ProposalAdmissionValidationMixin,
):
    """Admit one exact 3B proposal through existing Check/source commands.

    Each durable record remains an independently authenticated command. The
    deterministic plan makes a crash-safe retry resume from the first missing
    record without inventing an enclosing transaction or bypassing either
    authority boundary.
    """

    def __init__(
        self,
        *,
        store: _CheckAuthorityStore,
        command_service: CommandService,
    ) -> None:
        self._store = store
        self._command_service = command_service

    def _authorize(
        self,
        request: Any,
        proof: AuthenticationProof,
        *,
        command_type: str,
        aggregate_id: AggregateId,
    ) -> _AuthorizedCommandGrant:
        command = SemanticCommand(
            command_type=command_type,
            aggregate_id=aggregate_id,
            expected_aggregate_version=0,
            payload=InlinePayload(request.canonical_value()),
            idempotency_key=request.idempotency_key,
        )
        return self._command_service._authorize_for_commit(
            command,
            proof=proof,
        )


__all__ = ["_ProposalAdmissionBoundary"]
