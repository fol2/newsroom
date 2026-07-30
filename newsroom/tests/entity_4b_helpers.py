from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from newsroom.authority import StaticAuthorizer
from newsroom.authority.entity_system import open_governed_entity_authority_system
from newsroom.entities import (
    ENTITY_NORMALISATION_CONTRACT_DIGEST,
    CanonicalEntityId,
    CanonicalEntityVersionId,
    EntityAliasId,
    EntityAliasKind,
    EntityKind,
    EntityMentionAdmissionRequest,
    EntityMentionId,
    EntityReadPolicy,
    EntityResolutionDecisionAction,
    EntityResolutionDecisionRequest,
    EntityResolutionDependencyId,
    EntityResolutionDependencyRequest,
    EntityResolutionProposalId,
    EntityResolutionProposalKind,
    EntityResolutionProposalRequest,
    EntityResolutionProposalVersionId,
    classify_entity_script,
    normalize_entity_text,
)
from newsroom.extraction import (
    ExtractionProposalKind,
    FixtureExtractionCase,
    ProposalEnvelope,
)

from .extraction_4a_helpers import (
    ExtractionFixtureState,
    contract_request,
    extraction_authenticator,
    extraction_proof,
    open_extraction_system,
    run_request,
    seed_extraction_fixture,
    seed_homonym_extraction_fixture,
)
from .source_3a_helpers import SOURCE_NOW


def _id(cls, suffix: int):
    return cls.parse(f"00000000-0000-4000-8000-{suffix:012d}")


EN_MENTION_ID = _id(EntityMentionId, 4201)
ZH_MENTION_ID = _id(EntityMentionId, 4202)
EN_NEW_PROPOSAL_ID = _id(EntityResolutionProposalId, 4211)
EN_NEW_PROPOSAL_V1_ID = _id(EntityResolutionProposalVersionId, 4212)
ZH_EQ_PROPOSAL_ID = _id(EntityResolutionProposalId, 4221)
ZH_EQ_PROPOSAL_V1_ID = _id(EntityResolutionProposalVersionId, 4222)
ENTITY_ID = _id(CanonicalEntityId, 4231)
ENTITY_VERSION_ID = _id(CanonicalEntityVersionId, 4232)
EN_ALIAS_ID = _id(EntityAliasId, 4233)
ZH_ALIAS_ID = _id(EntityAliasId, 4234)
DEPENDENCY_ID = _id(EntityResolutionDependencyId, 4241)


@dataclass(frozen=True, slots=True)
class EntityFixtureState:
    extraction: ExtractionFixtureState
    en_source: ProposalEnvelope
    zh_source: ProposalEnvelope
    equivalence_source: ProposalEnvelope
    relation_source: ProposalEnvelope


@dataclass(frozen=True, slots=True)
class HomonymEntityFixtureState:
    extraction: ExtractionFixtureState
    en_transit_source: ProposalEnvelope
    en_association_source: ProposalEnvelope
    zh_transit_source: ProposalEnvelope
    zh_association_source: ProposalEnvelope
    equivalence_transit_source: ProposalEnvelope
    equivalence_association_source: ProposalEnvelope


ENTITY_SCOPES = frozenset(
    {
        "authority.entity.mention",
        "authority.entity.propose",
        "authority.entity.decide",
        "authority.entity.dependency",
        "authority.entity.merge",
        "authority.entity.split",
        "authority.entity.reverse",
        "authority.entity.read_proposals",
        "authority.entity.read_admitted",
        "authority.entity.read_projection",
    }
)


def entity_authorizer(*, scopes: frozenset[str] | None = None) -> StaticAuthorizer:
    return StaticAuthorizer(
        policy_version="entity-authority-authz-v1",
        grants_by_principal={"principal.alpha": ENTITY_SCOPES if scopes is None else scopes},
    )


def entity_read_policy() -> EntityReadPolicy:
    return EntityReadPolicy(
        policy_id="increment-4b-entity-read-v1",
        purpose="entity.authority.audit",
        proposal_required_scope="authority.entity.read_proposals",
        admitted_required_scope="authority.entity.read_admitted",
        projection_required_scope="authority.entity.read_projection",
        allowed_principal_ids=frozenset({"principal.alpha"}),
        max_results=100,
    )


def seed_entity_fixture(root: Path) -> EntityFixtureState:
    state = seed_extraction_fixture(root)
    system = open_extraction_system(state)
    try:
        system.extraction.register_contract(contract_request(), proof=extraction_proof())
        result = system.extraction.execute(run_request(state), proof=extraction_proof())
        assert result.proposal_set is not None
        proposals = result.proposal_set.proposals
    finally:
        system.close()
    en = next(
        proposal
        for proposal in proposals
        if proposal.kind is ExtractionProposalKind.ENTITY_MENTION
        and proposal.subject_placeholder == "Hong Kong Transport Department"
    )
    zh = next(
        proposal
        for proposal in proposals
        if proposal.kind is ExtractionProposalKind.ENTITY_MENTION
        and proposal.subject_placeholder == "香港運輸署"
    )
    equivalence = next(
        proposal
        for proposal in proposals
        if proposal.kind is ExtractionProposalKind.ENTITY_EQUIVALENCE
    )
    relation = next(
        proposal
        for proposal in proposals
        if proposal.kind is ExtractionProposalKind.RELATION
    )
    return EntityFixtureState(state, en, zh, equivalence, relation)


def seed_homonym_entity_fixture(root: Path) -> HomonymEntityFixtureState:
    state = seed_homonym_extraction_fixture(root)
    system = open_extraction_system(state)
    try:
        contract = contract_request(
            fixture_case=FixtureExtractionCase.BILINGUAL_HOMONYM,
            key="increment-4b-homonym-contract-v1",
        )
        system.extraction.register_contract(contract, proof=extraction_proof())
        result = system.extraction.execute(
            run_request(
                state,
                contract_id=contract.contract_id,
                key="increment-4b-homonym-run-v1",
            ),
            proof=extraction_proof(),
        )
        assert result.proposal_set is not None
        by_local_id = {
            proposal.local_id: proposal
            for proposal in result.proposal_set.proposals
        }
    finally:
        system.close()
    return HomonymEntityFixtureState(
        extraction=state,
        en_transit_source=by_local_id[
            "entity.chan-chi-ming.harbour-transit.en"
        ],
        en_association_source=by_local_id[
            "entity.chan-chi-ming.harbour-association.en"
        ],
        zh_transit_source=by_local_id[
            "entity.chan-chi-ming.harbour-transit.zh-hk"
        ],
        zh_association_source=by_local_id[
            "entity.chan-chi-ming.harbour-association.zh-hk"
        ],
        equivalence_transit_source=by_local_id[
            "equivalence.chan-chi-ming.harbour-transit.bilingual"
        ],
        equivalence_association_source=by_local_id[
            "equivalence.chan-chi-ming.harbour-association.bilingual"
        ],
    )


def open_entity_system(
    state: EntityFixtureState | HomonymEntityFixtureState,
    *,
    scopes: frozenset[str] | None = None,
):
    return open_governed_entity_authority_system(
        path=state.extraction.database,
        registry=state.extraction.commands,
        payload_schemas=state.extraction.schemas,
        authenticator=extraction_authenticator(),
        authorizer=entity_authorizer(scopes=scopes),
        read_policy=entity_read_policy(),
        clock=lambda: SOURCE_NOW,
    )


def mention_request(
    source: ProposalEnvelope,
    *,
    mention_id: EntityMentionId,
    language: str,
    key: str,
    entity_kind: EntityKind = EntityKind.GOVERNMENT_BODY,
) -> EntityMentionAdmissionRequest:
    return EntityMentionAdmissionRequest(
        mention_id=mention_id,
        source_proposal_id=source.proposal_id,
        expected_source_proposal_digest=source.canonical_digest,
        entity_kind=entity_kind,
        language=language,
        script=classify_entity_script(source.subject_placeholder),
        normalized_text=normalize_entity_text(source.subject_placeholder),
        normalization_contract_digest=ENTITY_NORMALISATION_CONTRACT_DIGEST,
        idempotency_key=key,
    )


def new_entity_proposal_request(
    state: EntityFixtureState,
    *,
    proposal_id: EntityResolutionProposalId = EN_NEW_PROPOSAL_ID,
    version_id: EntityResolutionProposalVersionId = EN_NEW_PROPOSAL_V1_ID,
    key: str = "entity-resolution-en-new-v1",
) -> EntityResolutionProposalRequest:
    return EntityResolutionProposalRequest(
        proposal_id=proposal_id,
        proposal_version_id=version_id,
        version_number=1,
        expected_previous_version_id=None,
        source_proposal_id=state.en_source.proposal_id,
        expected_source_proposal_digest=state.en_source.canonical_digest,
        kind=EntityResolutionProposalKind.MENTION_TO_NEW_ENTITY,
        subject_mention_id=EN_MENTION_ID,
        object_mention_id=None,
        candidate_entity_id=None,
        candidate_entity_version_id=None,
        confidence_basis_points=9_800,
        uncertainty_codes=(),
        basis_codes=("EXACT_SOURCE_MENTION",),
        idempotency_key=key,
    )


def dependency_request(
    state: EntityFixtureState,
    proposal,
    *,
    dependency_id: EntityResolutionDependencyId = DEPENDENCY_ID,
    material: bool = True,
    key: str = "entity-resolution-dependency-v1",
) -> EntityResolutionDependencyRequest:
    return EntityResolutionDependencyRequest(
        dependency_id=dependency_id,
        dependent_proposal_id=state.relation_source.proposal_id,
        expected_dependent_proposal_digest=state.relation_source.canonical_digest,
        resolution_proposal_id=proposal.proposal_id,
        expected_resolution_proposal_version_id=proposal.proposal_version_id,
        expected_resolution_proposal_digest=proposal.canonical_digest,
        material=material,
        idempotency_key=key,
    )

def decision_request(
    proposal,
    *,
    action: EntityResolutionDecisionAction,
    expected_decision_version: int = 0,
    previous=None,
    entity_id: CanonicalEntityId | None = None,
    version_id: CanonicalEntityVersionId | None = None,
    alias_id: EntityAliasId | None = None,
    alias_kind: EntityAliasKind | None = None,
    key: str,
) -> EntityResolutionDecisionRequest:
    return EntityResolutionDecisionRequest(
        proposal_id=proposal.proposal_id,
        expected_proposal_version_id=proposal.proposal_version_id,
        expected_proposal_digest=proposal.canonical_digest,
        action=action,
        expected_decision_version=expected_decision_version,
        expected_previous_decision_id=previous,
        accepted_entity_id=entity_id,
        accepted_entity_version_id=version_id,
        alias_id=alias_id,
        alias_kind=alias_kind,
        reason_code=f"FIXTURE_{action.value}",
        decision_policy_version="entity-resolution-policy-v1",
        idempotency_key=key,
    )


__all__ = [name for name in globals() if name.isupper()] + [
    "EntityFixtureState",
    "HomonymEntityFixtureState",
    "decision_request",
    "dependency_request",
    "entity_authorizer",
    "entity_read_policy",
    "mention_request",
    "new_entity_proposal_request",
    "open_entity_system",
    "seed_entity_fixture",
    "seed_homonym_entity_fixture",
]
