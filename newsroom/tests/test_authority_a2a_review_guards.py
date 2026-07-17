from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from newsroom.authority import (
    AuthorityPersistenceError,
    EventReadPolicy,
    MetadataClass,
    TrustScope,
    canonical_json_bytes,
)
from newsroom.authority._event_store import _EventAuthorityStore

from .authority_helpers import FIXED_NOW, command, make_service, proof


def _store_for_service(path: Path, service: object) -> _EventAuthorityStore:
    return _EventAuthorityStore(
        path,
        issuer=service._issuer,  # type: ignore[attr-defined]
        command_registry=service._registry,  # type: ignore[attr-defined]
        payload_schemas=service._payload_schemas,  # type: ignore[attr-defined]
        command_service_version="authority-command-v1",
        clock=lambda: FIXED_NOW,
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("allowed_principal_ids", {"principal.alpha"}),
        ("allowed_security_scopes", {"authority.internal"}),
        ("allowed_trust_scopes", {TrustScope.OBSERVED}),
        ("metadata_classes", {MetadataClass.ROUTING}),
    ],
)
def test_read_policy_rejects_mutable_collection_fields(
    field: str, value: object
) -> None:
    values = {
        "policy_id": "immutable-policy-v1",
        "purpose": "fixture.consumer",
        "required_scope": "authority.fixture.events.read",
        "allowed_principal_ids": frozenset({"principal.alpha"}),
        "allowed_security_scopes": frozenset({"authority.internal"}),
        "allowed_trust_scopes": frozenset({TrustScope.OBSERVED}),
        "metadata_classes": frozenset({MetadataClass.ROUTING}),
    }
    values[field] = value
    with pytest.raises(ValueError, match="frozenset"):
        EventReadPolicy(**values)  # type: ignore[arg-type]


def _insert_authentication(
    store: _EventAuthorityStore, authentication: object
) -> None:
    data = canonical_json_bytes(authentication.canonical_value())  # type: ignore[attr-defined]
    store._execute_test_sql(
        "INSERT INTO authentication_contexts("
        "authentication_context_id,principal_id,authority_domain,"
        "authentication_method,assurance_class,credential_binding_digest,"
        "authenticated_at,expires_at,canonical_bytes,canonical_digest) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            str(authentication.authentication_context_id),  # type: ignore[attr-defined]
            authentication.principal_id,  # type: ignore[attr-defined]
            authentication.authority_domain,  # type: ignore[attr-defined]
            authentication.authentication_method,  # type: ignore[attr-defined]
            authentication.assurance_class,  # type: ignore[attr-defined]
            authentication.credential_binding_digest,  # type: ignore[attr-defined]
            authentication.authenticated_at.to_text(),  # type: ignore[attr-defined]
            authentication.expires_at.to_text(),  # type: ignore[attr-defined]
            data,
            authentication.digest,  # type: ignore[attr-defined]
        ),
    )


def _insert_request(store: _EventAuthorityStore, request: object) -> None:
    data = canonical_json_bytes(request.canonical_value())  # type: ignore[attr-defined]
    store._execute_test_sql(
        "INSERT INTO authorization_requests("
        "request_digest,authentication_context_id,principal_id,authority_domain,"
        "operation_type,required_scope,canonical_bytes,canonical_record_digest,"
        "recorded_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (
            request.request_digest,  # type: ignore[attr-defined]
            str(request.authentication_context_id),  # type: ignore[attr-defined]
            request.principal_id,  # type: ignore[attr-defined]
            request.authority_domain,  # type: ignore[attr-defined]
            request.operation_type,  # type: ignore[attr-defined]
            request.required_scope,  # type: ignore[attr-defined]
            data,
            request.digest,  # type: ignore[attr-defined]
            FIXED_NOW.to_text(),
        ),
    )


def test_authentication_context_id_cannot_be_reused_for_other_provenance(
    tmp_path: Path,
) -> None:
    service = make_service()
    grant = service._authorize_for_commit(command(), proof=proof())
    conflicting = dataclasses.replace(
        grant.authentication, principal_id="principal.other"
    )
    with _store_for_service(
        tmp_path / "authority.sqlite3", service
    ) as store:
        _insert_authentication(store, conflicting)
        with pytest.raises(
            AuthorityPersistenceError, match="authentication_contexts"
        ):
            store.commit(grant)


def test_authorization_decision_id_cannot_be_reused_for_other_provenance(
    tmp_path: Path,
) -> None:
    service = make_service()
    grant = service._authorize_for_commit(command(), proof=proof())
    conflicting = dataclasses.replace(
        grant.authorization,
        authorization_policy_version="authz-other",
    )
    decision_bytes = canonical_json_bytes(conflicting.canonical_value())
    scopes_bytes = canonical_json_bytes(list(conflicting.effective_scopes))
    with _store_for_service(
        tmp_path / "authority.sqlite3", service
    ) as store:
        _insert_authentication(store, grant.authentication)
        _insert_request(store, grant.authorization_request)
        store._execute_test_sql(
            "INSERT INTO authorization_decisions("
            "authorization_decision_id,authentication_context_id,"
            "authorization_request_digest,authorization_policy_version,"
            "effective_scopes,effective_scope_digest,allowed,reason_code,"
            "decided_at,canonical_bytes,canonical_digest) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(conflicting.authorization_decision_id),
                str(conflicting.authentication_context_id),
                conflicting.authorization_request_digest,
                conflicting.authorization_policy_version,
                scopes_bytes,
                conflicting.effective_scope_digest,
                int(conflicting.allowed),
                conflicting.reason_code,
                conflicting.decided_at.to_text(),
                decision_bytes,
                conflicting.digest,
            ),
        )
        with pytest.raises(
            AuthorityPersistenceError, match="authorization_decisions"
        ):
            store.commit(grant)
