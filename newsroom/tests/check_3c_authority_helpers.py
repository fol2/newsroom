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
from newsroom.authority.check_system import (
    open_governed_check_authority_system,
)
from newsroom.checks.read_policy import DiscoveryCheckReadPolicy
from newsroom.sources import (
    BaselinePolicy,
    BaselinePolicyKind,
    CoverageContribution,
    CoverageMapping,
    CoverageResponsibility,
    DiscoveryOccurrenceId,
    DiscoveryOccurrenceKind,
    DiscoveryOccurrenceRequest,
    DiscoveryRepresentationRequest,
    IdentityComponent,
    ObservationModel,
    PortfolioFunction,
    RightsReference,
    SourceDefinitionRequest,
    SourceDefinitionVersionRequest,
    SourceItemIdentityKind,
    SourceItemRequest,
    SourceLifecycleStage,
    SourceRegistryReadPolicy,
    SourceRevisionRequest,
    SourceRole,
    SourceRoleAssignment,
    SourceTime,
    VersionedPolicyRef,
)

from .authority_event_helpers import payload_schemas, registry_v1
from .check_3c_helpers import (
    DEFINITION_ID,
    DIGEST_D,
    DIGEST_E,
    ITEM_ID,
    NOW,
    OUTCOME_ID,
    REPRESENTATION_ID,
    REVISION_ID,
    VERSION_ID,
)


OCCURRENCE_ID = DiscoveryOccurrenceId.parse(
    "00000000-0000-4000-8000-000000006016"
)


@dataclass(slots=True)
class CheckClock:
    current: UtcTimestamp = NOW

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
            "authority.checks.manage",
            "authority.checks.execute",
            "authority.checks.observe",
            "authority.checks.decide",
            "authority.findings.manage",
            "authority.findings.observe",
            "authority.checks.read",
            "authority.checks.read_sensitive",
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
        policy_version="discovery-check-authz-v1",
        grants_by_principal={
            "principal.alpha": scopes() if granted_scopes is None else granted_scopes
        },
    )


def source_read_policy() -> SourceRegistryReadPolicy:
    return SourceRegistryReadPolicy(
        policy_id="source-registry-read-v1",
        purpose="source.registry.audit",
        metadata_required_scope="authority.sources.read",
        sensitive_required_scope="authority.sources.read_sensitive",
        allowed_principal_ids=frozenset({"principal.alpha"}),
        max_results=100,
    )


def check_read_policy() -> DiscoveryCheckReadPolicy:
    return DiscoveryCheckReadPolicy(
        policy_id="discovery-check-read-v1",
        purpose="discovery.check.audit",
        metadata_required_scope="authority.checks.read",
        sensitive_required_scope="authority.checks.read_sensitive",
        allowed_principal_ids=frozenset({"principal.alpha"}),
        max_results=100,
    )


def open_check_system(
    database: Path,
    *,
    clock: Callable[[], UtcTimestamp] | None = None,
    granted_scopes: frozenset[str] | None = None,
):
    return open_governed_check_authority_system(
        path=database,
        registry=registry_v1(),
        payload_schemas=payload_schemas(),
        authenticator=authenticator(),
        authorizer=authorizer(granted_scopes=granted_scopes),
        source_read_policy=source_read_policy(),
        check_read_policy=check_read_policy(),
        clock=clock or CheckClock(),
    )


def definition_request() -> SourceDefinitionRequest:
    return SourceDefinitionRequest(
        definition_id=DEFINITION_ID,
        name="Fixture maintained Check guidance",
        editorial_purpose="Exercise Check and transition authority.",
        idempotency_key="fixture-check-source-definition",
    )


def version_request() -> SourceDefinitionVersionRequest:
    return SourceDefinitionVersionRequest(
        version_id=VERSION_ID,
        definition_id=DEFINITION_ID,
        version_number=1,
        expected_previous_version_id=None,
        locator="fixture://increment-3c/maintained-guidance",
        adapter_contract=VersionedPolicyRef("fixture-adapter", "v1"),
        extraction_scope=("body", "source_updated_time", "title"),
        rights=RightsReference(
            rights_decision_id="00000000-0000-4000-8000-000000006099",
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
            reference=VersionedPolicyRef("fixture-baseline", "v1"),
            kind=BaselinePolicyKind.MAINTAINED_DOCUMENT,
            reset_requires_decision=True,
            notes="Initial capture is baseline only.",
        ),
        item_identity_policy=VersionedPolicyRef(
            "fixture-item-identity", "v1"
        ),
        revision_policy=VersionedPolicyRef("fixture-revision", "v1"),
        canonicalization_policy=VersionedPolicyRef(
            "fixture-canonicalizer", "v1"
        ),
        lifecycle_stage=SourceLifecycleStage.RESEARCH_CANDIDATE,
        change_reason="Initial Increment 3C fixture source contract.",
        idempotency_key="fixture-check-source-version",
    )


def item_request() -> SourceItemRequest:
    return SourceItemRequest(
        item_id=ITEM_ID,
        definition_id=DEFINITION_ID,
        definition_version_id=VERSION_ID,
        identity_kind=SourceItemIdentityKind.COMPOSITE,
        identity_policy=VersionedPolicyRef(
            "fixture-item-identity", "v1"
        ),
        source_native_id=None,
        identity_components=(
            IdentityComponent("document_class", "guidance"),
            IdentityComponent("publisher_key", "fixture-authority"),
        ),
        uncertainties=(),
        idempotency_key="fixture-check-source-item",
    )


def revision_request() -> SourceRevisionRequest:
    return SourceRevisionRequest(
        revision_id=REVISION_ID,
        item_id=ITEM_ID,
        definition_version_id=VERSION_ID,
        prior_revision_id=None,
        source_native_revision_token="fixture-check-revision-1",
        permitted_state_digest=DIGEST_D,
        revision_policy=VersionedPolicyRef("fixture-revision", "v1"),
        canonicalizer_version="fixture-canonicalizer-v1",
        source_published_time=SourceTime.unknown(),
        source_updated_time=SourceTime.unknown(),
        observed_at=NOW,
        idempotency_key="fixture-check-source-revision",
    )


def representation_request() -> DiscoveryRepresentationRequest:
    return DiscoveryRepresentationRequest(
        representation_id=REPRESENTATION_ID,
        revision_id=REVISION_ID,
        definition_version_id=VERSION_ID,
        adapter_version="fixture-adapter-v1",
        parser_version="fixture-parser-v1",
        normalizer_version="fixture-normalizer-v1",
        extraction_scope_version="fixture-scope-v1",
        permitted_fields_digest="sha256:" + "9" * 64,
        representation_digest=DIGEST_D,
        produced_at=NOW,
        idempotency_key="fixture-check-representation",
    )


def occurrence_request() -> DiscoveryOccurrenceRequest:
    return DiscoveryOccurrenceRequest(
        occurrence_id=OCCURRENCE_ID,
        check_outcome_id=OUTCOME_ID,
        revision_id=REVISION_ID,
        representation_id=REPRESENTATION_ID,
        definition_version_id=VERSION_ID,
        kind=DiscoveryOccurrenceKind.FIRST_OBSERVED,
        observed_at=NOW,
        receipt_digest=DIGEST_E,
        source_asserted_time=SourceTime.unknown(),
        idempotency_key="fixture-check-occurrence",
    )


__all__ = [
    "CheckClock",
    "OCCURRENCE_ID",
    "check_read_policy",
    "definition_request",
    "item_request",
    "occurrence_request",
    "open_check_system",
    "proof",
    "representation_request",
    "revision_request",
    "scopes",
    "source_read_policy",
    "version_request",
]
