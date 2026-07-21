from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable

from newsroom.authority import (
    AggregateId,
    AuthenticationProof,
    CommandDefinition,
    CommandRegistry,
    EventReadPolicy,
    MetadataClass,
    PayloadMode,
    StaticAuthenticator,
    StaticAuthorizer,
    StaticPrincipal,
    TrustScope,
    UtcTimestamp,
)
from newsroom.projection import (
    GraphitiProposalWorkspaceContract,
    OntologyRegistry,
    ProjectionContractRegistry,
    ProjectionFamilyDefinition,
    ProjectionFamilyKind,
    ProjectionFamilyRegistry,
    ProjectionReadPolicy,
    StructuralMappingContract,
    StructuralMappingRegistry,
    native_ontology_v1,
    native_structural_mapping_v1,
)
from newsroom.projection.system import open_native_projection_authority_system

from .authority_event_helpers import payload_schemas, registry_v1
from .authority_helpers import FIXED_NOW, fixture_payload_contract


FAMILY_ID = "graph.structural"
FAMILY_AGGREGATE_ID = AggregateId.parse(
    "11111111-1111-4111-8111-111111111111"
)


def source_command_registry() -> CommandRegistry:
    base = registry_v1()
    contract = fixture_payload_contract()
    source = CommandDefinition(
        command_type="source.item.write",
        definition_version="source-command-v1",
        aggregate_type="source_item",
        event_type="source.item.versioned",
        event_schema_version=1,
        payload_mode=PayloadMode.INLINE,
        payload_schema_version=contract.schema_version,
        payload_schema_contract_version=contract.contract_version,
        payload_schema_contract_digest=contract.contract_digest,
        payload_canonicalizer_version=contract.canonicalizer_implementation_version,
        trust_scope=TrustScope.OBSERVED,
        security_scope="authority.internal",
        retention_scope="authority.default",
        required_scope="authority.observed.write",
        max_inline_bytes=4096,
    )
    optional_candidate = CommandDefinition(
        command_type="candidate.fixture.write",
        definition_version="candidate-command-v1",
        aggregate_type="candidate_fixture",
        event_type="candidate.derived",
        event_schema_version=1,
        payload_mode=PayloadMode.INLINE,
        payload_schema_version=contract.schema_version,
        payload_schema_contract_version=contract.contract_version,
        payload_schema_contract_digest=contract.contract_digest,
        payload_canonicalizer_version=contract.canonicalizer_implementation_version,
        trust_scope=TrustScope.OBSERVED,
        security_scope="authority.internal",
        retention_scope="authority.default",
        required_scope="authority.observed.write",
        max_inline_bytes=4096,
    )
    return CommandRegistry(
        (*base.definitions(), source, optional_candidate)
    )


def projection_contracts() -> ProjectionContractRegistry:
    ontology = native_ontology_v1()
    base_mapping = native_structural_mapping_v1(ontology)
    mapping = StructuralMappingContract(
        mapping_id="newsroom.structural",
        mapping_version="mapping-test-v1",
        implementation_version="mapping-python-test-v1",
        ontology_contract_digest=ontology.contract_digest,
        mappings=base_mapping.mappings,
    )
    mapping.validate_against(ontology)
    family = ProjectionFamilyDefinition(
        family_id=FAMILY_ID,
        authority_aggregate_id=FAMILY_AGGREGATE_ID,
        family_kind=ProjectionFamilyKind.GRAPH,
        definition_version="family-v1",
        projector_version="structural-projector-v1",
        ontology_contract_digest=ontology.contract_digest,
        mapping_contract_digest=mapping.contract_digest,
        max_delivery_attempts=3,
        max_gap_span=100,
    )
    ontologies = OntologyRegistry((ontology,))
    mappings = StructuralMappingRegistry((mapping,))
    families = ProjectionFamilyRegistry(
        (family,), ontologies=ontologies, mappings=mappings
    )
    graphiti = GraphitiProposalWorkspaceContract(
        workspace_id="graphiti.proposals",
        contract_version="graphiti-workspace-v1",
        implementation_version="graphiti-seam-v1",
        endpoint_reference="config://graphiti/proposal-endpoint",
        secret_reference="secret://graphiti/proposal-token",
    )
    return ProjectionContractRegistry(
        ontologies=ontologies,
        mappings=mappings,
        families=families,
        graphiti_workspaces=(graphiti,),
    )


def projection_read_policy() -> ProjectionReadPolicy:
    return ProjectionReadPolicy(
        policy_id="projection-reader-v1",
        purpose="projector.structural",
        required_scope="authority.projection.read",
        allowed_principal_ids=frozenset({"principal.alpha"}),
        allowed_family_ids=frozenset({FAMILY_ID}),
        allowed_family_kinds=frozenset({ProjectionFamilyKind.GRAPH}),
        max_results=1000,
    )


def event_read_policy() -> EventReadPolicy:
    return EventReadPolicy(
        policy_id="projection-event-reader-v1",
        purpose="projection.test",
        required_scope="authority.fixture.events.read",
        allowed_principal_ids=frozenset({"principal.alpha"}),
        allowed_security_scopes=frozenset(
            {"authority.internal", "authority.projection"}
        ),
        allowed_trust_scopes=frozenset(
            {TrustScope.OBSERVED, TrustScope.ADMITTED}
        ),
        metadata_classes=frozenset(
            {MetadataClass.ROUTING, MetadataClass.PROVENANCE, MetadataClass.RESULT}
        ),
        minimum_ledger_seq=1,
        maximum_ledger_seq=None,
        max_results=1000,
    )


def open_projection_system(
    path: Path,
    *,
    scopes: frozenset[str] | None = None,
    clock: Callable[[], UtcTimestamp] | None = None,
    contracts: ProjectionContractRegistry | None = None,
    authenticator: object | None = None,
):
    policy = event_read_policy()
    selected = scopes or frozenset(
        {
            "authority.observed.write",
            "authority.admitted.write",
            policy.required_scope,
            "authority.projection.manage",
            "authority.projection.write",
            "authority.projection.read",
        }
    )
    return open_native_projection_authority_system(
        path=path,
        registry=source_command_registry(),
        payload_schemas=payload_schemas(),
        contracts=contracts or projection_contracts(),
        authenticator=authenticator or StaticAuthenticator(
            credentials={"token-1": StaticPrincipal("principal.alpha")},
            authority_domain="newsroom.authority",
        ),
        authorizer=StaticAuthorizer(
            policy_version="authz-v1",
            grants_by_principal={"principal.alpha": selected},
        ),
        event_read_policy=policy,
        projection_read_policy=projection_read_policy(),
        clock=clock or (lambda: FIXED_NOW),
    )


def proof() -> AuthenticationProof:
    return AuthenticationProof(method="STATIC_TOKEN", credential="token-1")
