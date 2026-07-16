from __future__ import annotations

from newsroom.authority import InlinePayload, SemanticCommand

from .authority_helpers import command, make_service, proof


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


def test_definition_version_change_changes_semantic_identity() -> None:
    aggregate_id = command().aggregate_id
    request = command(aggregate_id=aggregate_id)
    first = make_service(definition_version="cmd-v1").authorize(request, proof=proof())
    second = make_service(definition_version="cmd-v2").authorize(request, proof=proof())
    assert first.stable_semantic_request_digest != second.stable_semantic_request_digest
