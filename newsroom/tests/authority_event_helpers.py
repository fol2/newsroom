from __future__ import annotations

from pathlib import Path

from newsroom.authority import (
    AuthorityEventSystem,
    CommandRegistry,
    PayloadSchemaRegistry,
    StaticAuthenticator,
    StaticAuthorizer,
    StaticPrincipal,
    open_authority_event_system,
)

from .authority_helpers import (
    FIXED_NOW,
    admitted_definition,
    default_payload_schemas,
    observed_definition,
)


def registry_v1() -> CommandRegistry:
    return CommandRegistry([observed_definition(), admitted_definition()])


def registry_with_upgrade() -> CommandRegistry:
    return CommandRegistry(
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


def open_test_system(
    path: Path,
    *,
    registry: CommandRegistry | None = None,
    payload_schemas: PayloadSchemaRegistry | None = None,
    policy_version: str = "authz-v1",
    credential: str = "token-1",
    scopes: frozenset[str] = frozenset(
        {
            "authority.observed.write",
            "authority.events.read",
            "authority.audit.read",
        }
    ),
) -> AuthorityEventSystem:
    return open_authority_event_system(
        path=path,
        registry=registry or registry_v1(),
        payload_schemas=payload_schemas or default_payload_schemas(),
        authenticator=StaticAuthenticator(
            credentials={credential: StaticPrincipal("principal.alpha")},
            authority_domain="newsroom.authority",
        ),
        authorizer=StaticAuthorizer(
            policy_version=policy_version,
            grants_by_principal={"principal.alpha": scopes},
        ),
        command_service_version="authority-command-v1",
        clock=lambda: FIXED_NOW,
    )
