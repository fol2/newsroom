from __future__ import annotations

import pytest

from newsroom.authority import (
    AuthorizationDenied,
    CommandId,
    CommandRegistry,
    CommittedCommandIdentity,
    IdempotencyIdentityConflict,
    InlinePayload,
    SemanticCommand,
)

from .authority_helpers import (
    admitted_definition,
    command,
    make_service,
    observed_definition,
    proof,
)


class ExistingLookup:
    def __init__(self, identity: CommittedCommandIdentity) -> None:
        self.identity = identity

    def find(
        self, *, idempotency_namespace: str, idempotency_key: str
    ) -> CommittedCommandIdentity | None:
        if (
            idempotency_namespace == self.identity.idempotency_namespace
            and idempotency_key == self.identity.idempotency_key
        ):
            return self.identity
        return None


def test_stable_semantic_digest_survives_policy_version_change() -> None:
    aggregate_id = command().aggregate_id
    request = command(aggregate_id=aggregate_id)
    first = make_service(policy_version="authz-v1").authorize(request, proof=proof())
    second = make_service(policy_version="authz-v2").authorize(request, proof=proof())
    assert first.stable_semantic_request_digest == second.stable_semantic_request_digest
    assert first.idempotency_namespace == second.idempotency_namespace
    assert first.authorization_policy_version != second.authorization_policy_version


def test_stable_semantic_digest_survives_irrelevant_scope_change() -> None:
    aggregate_id = command().aggregate_id
    request = command(aggregate_id=aggregate_id)
    first = make_service(
        scopes=frozenset({"authority.observed.write"})
    ).authorize(request, proof=proof())
    second = make_service(
        scopes=frozenset({"authority.observed.write", "unrelated.read"})
    ).authorize(request, proof=proof())
    assert first.stable_semantic_request_digest == second.stable_semantic_request_digest
    assert first.effective_scope_digest != second.effective_scope_digest


def test_credential_rotation_for_same_principal_keeps_namespace() -> None:
    aggregate_id = command().aggregate_id
    request = command(aggregate_id=aggregate_id)
    first = make_service(credential="old-token").authorize(
        request, proof=proof(credential="old-token")
    )
    second = make_service(credential="new-token").authorize(
        request, proof=proof(credential="new-token")
    )
    assert first.idempotency_namespace == second.idempotency_namespace
    assert first.stable_semantic_request_digest == second.stable_semantic_request_digest
    assert first.authentication_context_id != second.authentication_context_id


def test_genuinely_different_command_changes_semantic_digest() -> None:
    aggregate_id = command().aggregate_id
    first_command = command(aggregate_id=aggregate_id)
    second_command = SemanticCommand(
        command_type=first_command.command_type,
        aggregate_id=aggregate_id,
        expected_aggregate_version=0,
        payload=InlinePayload({"headline": "Different", "count": 1}),
        idempotency_key=first_command.idempotency_key,
    )
    service = make_service()
    first = service.authorize(first_command, proof=proof())
    second = service.authorize(second_command, proof=proof())
    assert first.stable_semantic_request_digest != second.stable_semantic_request_digest


def test_definition_version_change_changes_new_command_semantic_identity() -> None:
    aggregate_id = command().aggregate_id
    request = command(aggregate_id=aggregate_id)
    first = make_service(definition_version="cmd-v1").authorize(request, proof=proof())
    second = make_service(definition_version="cmd-v2").authorize(request, proof=proof())
    assert first.stable_semantic_request_digest != second.stable_semantic_request_digest


def _existing_identity(
    first: object, request: SemanticCommand
) -> CommittedCommandIdentity:
    return CommittedCommandIdentity(
        command_id=str(CommandId.new()),
        authority_domain="newsroom.authority",
        principal_id="principal.alpha",
        command_type=request.command_type,
        idempotency_namespace=first.idempotency_namespace,  # type: ignore[attr-defined]
        idempotency_key=request.idempotency_key,
        command_definition_version=first.command_definition_version,  # type: ignore[attr-defined]
        command_definition_digest=first.command_definition_digest,  # type: ignore[attr-defined]
        stable_semantic_request_digest=first.stable_semantic_request_digest,  # type: ignore[attr-defined]
    )


def test_lost_response_retry_uses_retained_definition_after_upgrade() -> None:
    aggregate_id = command().aggregate_id
    request = command(aggregate_id=aggregate_id)
    first = make_service(definition_version="cmd-v1").authorize(request, proof=proof())
    existing = _existing_identity(first, request)
    registry = CommandRegistry(
        [
            observed_definition(version="cmd-v1"),
            observed_definition(version="cmd-v2"),
            admitted_definition(),
        ],
        current_versions={
            "record.observed": "cmd-v2",
            "record.admitted": "cmd-v1",
        },
    )
    retry = make_service(
        policy_version="authz-v2",
        registry=registry,
        committed_lookup=ExistingLookup(existing),
    ).authorize(request, proof=proof())
    assert retry.replay_of_command_id == existing.command_id
    assert retry.command_definition_version == "cmd-v1"
    assert retry.command_definition_digest == existing.command_definition_digest
    assert (
        retry.stable_semantic_request_digest
        == existing.stable_semantic_request_digest
    )


def test_lost_response_retry_still_checks_current_authorization() -> None:
    request = command()
    first = make_service().authorize(request, proof=proof())
    existing = _existing_identity(first, request)
    with pytest.raises(AuthorizationDenied):
        make_service(
            scopes=frozenset(),
            committed_lookup=ExistingLookup(existing),
        ).authorize(request, proof=proof())


def test_existing_idempotency_key_conflicts_with_different_payload() -> None:
    request = command()
    first = make_service().authorize(request, proof=proof())
    existing = _existing_identity(first, request)
    different = SemanticCommand(
        command_type=request.command_type,
        aggregate_id=request.aggregate_id,
        expected_aggregate_version=request.expected_aggregate_version,
        payload=InlinePayload({"headline": "Different", "count": 1}),
        idempotency_key=request.idempotency_key,
    )
    with pytest.raises(IdempotencyIdentityConflict):
        make_service(committed_lookup=ExistingLookup(existing)).authorize(
            different, proof=proof()
        )
