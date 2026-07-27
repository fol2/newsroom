from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from newsroom.authority import (
    AuthenticationProof,
    StaticAuthenticator,
    StaticAuthorizer,
    StaticPrincipal,
    UtcTimestamp,
)
from newsroom.authority.policy import CommandRegistry, PayloadSchemaRegistry
from newsroom.sources import (
    BaselinePolicy,
    BaselinePolicyKind,
    CheckOutcomeId,
    CoverageContribution,
    CoverageMapping,
    CoverageResponsibility,
    DiscoveryOccurrenceId,
    DiscoveryOccurrenceKind,
    DiscoveryOccurrenceRequest,
    DiscoveryRepresentationId,
    DiscoveryRepresentationRequest,
    IdentityComponent,
    LocatorContinuityDecisionId,
    LocatorContinuityDecisionRequest,
    LocatorContinuityOutcome,
    ObservationModel,
    PortfolioFunction,
    RightsReference,
    SourceDefinitionId,
    SourceDefinitionRequest,
    SourceDefinitionVersionId,
    SourceDefinitionVersionRequest,
    SourceItemId,
    SourceItemIdentityKind,
    SourceItemRequest,
    SourceLifecycleStage,
    SourceRegistryReadPolicy,
    SourceRevisionId,
    SourceRevisionRequest,
    SourceRole,
    SourceRoleAssignment,
    SourceTime,
    VersionedPolicyRef,
    open_governed_source_registry_authority_system,
)

from .authority_event_helpers import payload_schemas, registry_v1

SOURCE_NOW = UtcTimestamp.parse("2042-03-12T10:00:00.000000Z")
DEFINITION_ID = SourceDefinitionId.parse(
    "00000000-0000-4000-8000-000000003101"
)
VERSION_1_ID = SourceDefinitionVersionId.parse(
    "00000000-0000-4000-8000-000000003102"
)
VERSION_2_ID = SourceDefinitionVersionId.parse(
    "00000000-0000-4000-8000-000000003103"
)
ITEM_ID = SourceItemId.parse("00000000-0000-4000-8000-000000003104")
REVISION_1_ID = SourceRevisionId.parse(
    "00000000-0000-4000-8000-000000003105"
)
REVISION_2_ID = SourceRevisionId.parse(
    "00000000-0000-4000-8000-000000003106"
)
REPRESENTATION_1_ID = DiscoveryRepresentationId.parse(
    "00000000-0000-4000-8000-000000003107"
)
REPRESENTATION_2_ID = DiscoveryRepresentationId.parse(
    "00000000-0000-4000-8000-000000003108"
)
OCCURRENCE_1_ID = DiscoveryOccurrenceId.parse(
    "00000000-0000-4000-8000-000000003109"
)
OCCURRENCE_2_ID = DiscoveryOccurrenceId.parse(
    "00000000-0000-4000-8000-000000003110"
)
CHECK_1_ID = CheckOutcomeId.parse(
    "00000000-0000-4000-8000-000000003111"
)
CHECK_2_ID = CheckOutcomeId.parse(
    "00000000-0000-4000-8000-000000003112"
)
LOCATOR_DECISION_ID = LocatorContinuityDecisionId.parse(
    "00000000-0000-4000-8000-000000003113"
)


@dataclass(slots=True)
class SourceClock:
    current: UtcTimestamp = SOURCE_NOW

    def __call__(self) -> UtcTimestamp:
        return self.current


def proof(*, credential: str = "token-1") -> AuthenticationProof:
    return AuthenticationProof(method="STATIC_TOKEN", credential=credential)


def scopes() -> frozenset[str]:
    return frozenset(
        {
            "authority.sources.manage",
            "authority.sources.observe",
            "authority.sources.read",
            "authority.sources.read_sensitive",
        }
    )


def authenticator() -> StaticAuthenticator:
    return StaticAuthenticator(
        credentials={"token-1": StaticPrincipal("principal.alpha")},
        authority_domain="newsroom.authority",
    )


def authorizer(
    *, granted_scopes: frozenset[str] | None = None
) -> StaticAuthorizer:
    return StaticAuthorizer(
        policy_version="source-registry-authz-v1",
        grants_by_principal={
            "principal.alpha": scopes() if granted_scopes is None else granted_scopes
        },
    )


def read_policy() -> SourceRegistryReadPolicy:
    return SourceRegistryReadPolicy(
        policy_id="source-registry-read-v1",
        purpose="source.registry.audit",
        metadata_required_scope="authority.sources.read",
        sensitive_required_scope="authority.sources.read_sensitive",
        allowed_principal_ids=frozenset({"principal.alpha"}),
        max_results=100,
    )


def base_registries() -> tuple[CommandRegistry, PayloadSchemaRegistry]:
    return registry_v1(), payload_schemas()


def open_source_system(
    database: Path,
    *,
    clock: Callable[[], UtcTimestamp] | None = None,
    granted_scopes: frozenset[str] | None = None,
):
    commands, schemas = base_registries()
    return open_governed_source_registry_authority_system(
        path=database,
        registry=commands,
        payload_schemas=schemas,
        authenticator=authenticator(),
        authorizer=authorizer(granted_scopes=granted_scopes),
        read_policy=read_policy(),
        clock=clock or SourceClock(),
    )


def definition_request(
    *,
    definition_id: SourceDefinitionId = DEFINITION_ID,
    key: str = "source-definition-v1",
) -> SourceDefinitionRequest:
    return SourceDefinitionRequest(
        definition_id=definition_id,
        name="Fixture maintained guidance",
        editorial_purpose="Detect and preserve revisions in fixture guidance.",
        idempotency_key=key,
    )


def version_request(
    *,
    version_id: SourceDefinitionVersionId = VERSION_1_ID,
    version_number: int = 1,
    previous_version_id: SourceDefinitionVersionId | None = None,
    locator: str = "fixture://increment-3a/maintained-guidance-v1",
    key: str = "source-definition-version-v1",
) -> SourceDefinitionVersionRequest:
    return SourceDefinitionVersionRequest(
        version_id=version_id,
        definition_id=DEFINITION_ID,
        version_number=version_number,
        expected_previous_version_id=previous_version_id,
        locator=locator,
        adapter_contract=VersionedPolicyRef("fixture-adapter", "v1"),
        extraction_scope=("body", "source_updated_time", "title"),
        rights=RightsReference(
            rights_decision_id="00000000-0000-4000-8000-000000003199",
            rights_policy_version="fixture-rights-v1",
            allowed_use="discovery.fixture",
            retention_scope="authority.audit",
        ),
        roles=(
            SourceRoleAssignment(
                role=SourceRole.ORIGINATING_AUTHORITY,
                purpose="Observe fixture guidance revisions.",
                limitations=("Fixture and approved replay only.",),
            ),
        ),
        portfolio_functions=(PortfolioFunction.ANCHOR,),
        coverage_mappings=(
            CoverageMapping(
                obligation_id="COV-021",
                responsibility=CoverageResponsibility.ACTIVE,
                contribution=CoverageContribution.REVISION_VISIBILITY,
                geographies=("FIXTURE",),
                languages=("en-GB",),
                limitations=("No live-source execution.",),
            ),
        ),
        dependencies=(),
        explicit_gaps=(),
        observation_model=ObservationModel.MUTABLE_ITEM,
        baseline_policy=BaselinePolicy(
            reference=VersionedPolicyRef("maintained-baseline", "v1"),
            kind=BaselinePolicyKind.MAINTAINED_DOCUMENT,
            reset_requires_decision=True,
            notes="Initial capture is baseline only.",
        ),
        item_identity_policy=VersionedPolicyRef(
            "fixture-item-identity", "v1"
        ),
        revision_policy=VersionedPolicyRef("fixture-revision-rule", "v1"),
        canonicalization_policy=VersionedPolicyRef(
            "fixture-canonicalizer", "v1"
        ),
        lifecycle_stage=SourceLifecycleStage.RESEARCH_CANDIDATE,
        change_reason=(
            "Initial fixture source contract."
            if version_number == 1
            else "Fixture locator changed without changing source identity."
        ),
        idempotency_key=key,
    )


def item_request(
    *,
    version_id: SourceDefinitionVersionId = VERSION_1_ID,
    key: str = "source-item-v1",
) -> SourceItemRequest:
    return SourceItemRequest(
        item_id=ITEM_ID,
        definition_id=DEFINITION_ID,
        definition_version_id=version_id,
        identity_kind=SourceItemIdentityKind.COMPOSITE,
        identity_policy=VersionedPolicyRef("fixture-item-identity", "v1"),
        source_native_id=None,
        identity_components=(
            IdentityComponent("document_class", "guidance"),
            IdentityComponent("publisher_key", "fixture-authority"),
        ),
        uncertainties=(),
        idempotency_key=key,
    )


def locator_decision_request() -> LocatorContinuityDecisionRequest:
    return LocatorContinuityDecisionRequest(
        decision_id=LOCATOR_DECISION_ID,
        definition_id=DEFINITION_ID,
        definition_version_id=VERSION_2_ID,
        prior_item_id=ITEM_ID,
        prior_locator="fixture://increment-3a/maintained-guidance-v1",
        observed_locator="fixture://increment-3a/maintained-guidance-v2",
        outcome=LocatorContinuityOutcome.SAME_ITEM,
        related_item_id=ITEM_ID,
        rationale="Fixture identity policy proves continuity.",
        decision_policy=VersionedPolicyRef(
            "fixture-locator-continuity", "v1"
        ),
        observed_at=SOURCE_NOW,
        idempotency_key="source-locator-continuity-v1",
    )


def revision_request(
    *,
    revision_id: SourceRevisionId = REVISION_1_ID,
    version_id: SourceDefinitionVersionId = VERSION_2_ID,
    prior_revision_id: SourceRevisionId | None = None,
    state_character: str = "a",
    key: str = "source-revision-v1",
) -> SourceRevisionRequest:
    return SourceRevisionRequest(
        revision_id=revision_id,
        item_id=ITEM_ID,
        definition_version_id=version_id,
        prior_revision_id=prior_revision_id,
        source_native_revision_token=f"fixture-{state_character}",
        permitted_state_digest="sha256:" + state_character * 64,
        revision_policy=VersionedPolicyRef("fixture-revision-rule", "v1"),
        canonicalizer_version="fixture-canonicalizer-v1",
        source_published_time=SourceTime.unknown(),
        source_updated_time=SourceTime.unknown(),
        observed_at=SOURCE_NOW,
        idempotency_key=key,
    )


def representation_request(
    *,
    representation_id: DiscoveryRepresentationId = REPRESENTATION_1_ID,
    revision_id: SourceRevisionId = REVISION_1_ID,
    parser_version: str = "fixture-parser-v1",
    digest_character: str = "b",
    key: str = "source-representation-v1",
) -> DiscoveryRepresentationRequest:
    return DiscoveryRepresentationRequest(
        representation_id=representation_id,
        revision_id=revision_id,
        definition_version_id=VERSION_2_ID,
        adapter_version="fixture-adapter-v1",
        parser_version=parser_version,
        normalizer_version="fixture-normalizer-v1",
        extraction_scope_version="fixture-scope-v1",
        permitted_fields_digest="sha256:" + "d" * 64,
        representation_digest="sha256:" + digest_character * 64,
        produced_at=SOURCE_NOW,
        idempotency_key=key,
    )


def occurrence_request(
    *,
    occurrence_id: DiscoveryOccurrenceId = OCCURRENCE_1_ID,
    check_outcome_id: CheckOutcomeId = CHECK_1_ID,
    representation_id: DiscoveryRepresentationId = REPRESENTATION_1_ID,
    kind: DiscoveryOccurrenceKind = DiscoveryOccurrenceKind.FIRST_OBSERVED,
    key: str = "source-occurrence-v1",
) -> DiscoveryOccurrenceRequest:
    return DiscoveryOccurrenceRequest(
        occurrence_id=occurrence_id,
        check_outcome_id=check_outcome_id,
        revision_id=REVISION_1_ID,
        representation_id=representation_id,
        definition_version_id=VERSION_2_ID,
        kind=kind,
        observed_at=SOURCE_NOW,
        receipt_digest="sha256:" + "e" * 64,
        source_asserted_time=SourceTime.unknown(),
        idempotency_key=key,
    )
