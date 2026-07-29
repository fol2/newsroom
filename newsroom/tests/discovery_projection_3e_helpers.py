from __future__ import annotations

from pathlib import Path
from typing import Callable

from newsroom.authority import (
    EventReadPolicy,
    MetadataClass,
    StaticAuthorizer,
    TrustScope,
    UtcTimestamp,
)
from newsroom.authority._neo4j_projection_system import _open_with_adapter
from newsroom.checks.policy import merge_discovery_check_authority_registries
from newsroom.discovery.policy import merge_discovery_signal_lead_registries
from newsroom.projection import (
    DISCOVERY_LINEAGE_FAMILY_ID,
    ProjectionFamilyKind,
    ProjectionReadPolicy,
    discovery_lineage_contract_registry,
)
from newsroom.sources.policy import merge_source_registry_authority_registries

from .authority_event_helpers import payload_schemas, registry_v1
from .check_3c_authority_helpers import authenticator
from .discovery_3d_authority_helpers import proof, scopes
from .projection_b2_helpers import MemoryNeo4jAdapter


def increment3_registries():
    source_registry, source_schemas = merge_source_registry_authority_registries(
        command_registry=registry_v1(),
        payload_schemas=payload_schemas(),
    )
    check_registry, check_schemas = merge_discovery_check_authority_registries(
        command_registry=source_registry,
        payload_schemas=source_schemas,
    )
    return merge_discovery_signal_lead_registries(
        command_registry=check_registry,
        payload_schemas=check_schemas,
    )


def lineage_event_read_policy() -> EventReadPolicy:
    return EventReadPolicy(
        policy_id="discovery-lineage-event-reader-v1",
        purpose="projection.discovery-lineage.fixture",
        required_scope="authority.discovery_lineage.events.read",
        allowed_principal_ids=frozenset({"principal.alpha"}),
        allowed_security_scopes=frozenset(
            {
                "authority.source_registry",
                "authority.discovery_checks",
                "authority.discovery",
                "authority.projection",
            }
        ),
        allowed_trust_scopes=frozenset(
            {TrustScope.OBSERVED, TrustScope.ADMITTED}
        ),
        metadata_classes=frozenset(
            {
                MetadataClass.ROUTING,
                MetadataClass.PROVENANCE,
                MetadataClass.RESULT,
            }
        ),
        minimum_ledger_seq=1,
        maximum_ledger_seq=None,
        max_results=1_000,
    )


def lineage_projection_read_policy() -> ProjectionReadPolicy:
    return ProjectionReadPolicy(
        policy_id="discovery-lineage-reader-v1",
        purpose="projection.discovery-lineage.audit",
        required_scope="authority.discovery_lineage.read",
        allowed_principal_ids=frozenset({"principal.alpha"}),
        allowed_family_ids=frozenset({DISCOVERY_LINEAGE_FAMILY_ID}),
        allowed_family_kinds=frozenset({ProjectionFamilyKind.GRAPH}),
        max_results=1_000,
    )


def lineage_scopes() -> frozenset[str]:
    return scopes() | frozenset(
        {
            "authority.discovery_lineage.events.read",
            "authority.discovery_lineage.read",
            "authority.projection.manage",
            "authority.projection.write",
            "authority.projection.read",
        }
    )


def open_lineage_projection_system(
    path: Path,
    adapter: MemoryNeo4jAdapter,
    *,
    clock: Callable[[], UtcTimestamp] | None = None,
):
    command_registry, schemas = increment3_registries()
    return _open_with_adapter(
        path=path,
        registry=command_registry,
        payload_schemas=schemas,
        contracts=discovery_lineage_contract_registry(),
        authenticator=authenticator(),
        authorizer=StaticAuthorizer(
            policy_version="discovery-lineage-authz-v1",
            grants_by_principal={"principal.alpha": lineage_scopes()},
        ),
        event_read_policy=lineage_event_read_policy(),
        projection_read_policy=lineage_projection_read_policy(),
        adapter=adapter,
        clock=clock or UtcTimestamp.now,
    )


__all__ = [
    "MemoryNeo4jAdapter",
    "increment3_registries",
    "lineage_event_read_policy",
    "lineage_projection_read_policy",
    "lineage_scopes",
    "open_lineage_projection_system",
    "proof",
]
