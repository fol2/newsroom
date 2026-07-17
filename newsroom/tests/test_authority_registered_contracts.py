from __future__ import annotations

import dataclasses

import pytest

from newsroom.authority import digest_canonical
from newsroom.authority._capability import InvalidCommitCapability
from newsroom.authority._security import (
    _AuthorizationDecision,
    _AuthorizationRequest,
    _effective_scope_digest,
)

from .authority_helpers import command, make_service, proof


def _changed_request(grant, **changes: object) -> _AuthorizationRequest:
    unsigned = grant.authorization_request.unsigned_value()
    unsigned.update(changes)
    return dataclasses.replace(
        grant.authorization_request,
        **changes,
        request_digest=digest_canonical(unsigned),
    )


def _decision_for(
    grant, request: _AuthorizationRequest, scopes: tuple[str, ...]
) -> _AuthorizationDecision:
    return dataclasses.replace(
        grant.authorization,
        authorization_request_digest=request.request_digest,
        effective_scopes=scopes,
        effective_scope_digest=_effective_scope_digest(
            grant.authentication, scopes
        ),
        allowed=True,
        reason_code="AUTHZ_ALLOWED",
    )


def _resign(service, grant, **changes):
    values = {
        field.name: getattr(grant, field.name)
        for field in dataclasses.fields(grant)
        if field.name != "signature"
    }
    values.update(changes)
    return service._issuer.issue(**values)


def test_same_issuer_cannot_sign_unregistered_server_definition() -> None:
    service = make_service()
    grant = service._authorize_for_commit(command(), proof=proof())
    fabricated_definition = dataclasses.replace(
        grant.definition,
        definition_version="cmd-fabricated",
        required_scope="authority.weaker.write",
    )
    request = _changed_request(
        grant,
        operation_type=f"command:{fabricated_definition.command_type}",
        required_scope=fabricated_definition.required_scope,
        command_definition_digest=fabricated_definition.digest,
    )
    decision = _decision_for(
        grant, request, ("authority.weaker.write",)
    )
    resigned = _resign(
        service,
        grant,
        definition=fabricated_definition,
        authorization_request=request,
        authorization=decision,
    )
    with pytest.raises(InvalidCommitCapability, match="registered"):
        service._issuer.verify(resigned)
