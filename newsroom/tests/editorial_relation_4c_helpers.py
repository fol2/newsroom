from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from newsroom.authority import StaticAuthorizer
from newsroom.authority.entity_system import open_governed_entity_authority_system
from newsroom.authority.editorial_relation_system import (
    open_governed_editorial_relation_authority_system,
)
from newsroom.entities import (
    CanonicalEntityId,
    CanonicalEntityVersionId,
    EntityAliasId,
    EntityAliasKind,
    EntityResolutionDecisionAction,
    EntityResolutionDependencyId,
    EntityResolutionProposalId,
    EntityResolutionProposalKind,
    EntityResolutionProposalRequest,
    EntityResolutionProposalVersionId,
)
from newsroom.integrated.models import IntegratedHypothesisVersionId
from newsroom.relations import (
    EDITORIAL_PREDICATE_REGISTRY_V1,
    EDITORIAL_RELATION_ADMISSION_POLICY_VERSION,
    CanonicalEntityRelationEndpoint,
    EditorialPredicateCode,
    EditorialRelationAssertionId,
    EditorialRelationDecisionAction,
    EditorialRelationDecisionId,
    EditorialRelationDecisionRequest,
    EditorialRelationProducer,
    EditorialRelationProducerKind,
    EditorialRelationProposalId,
    EditorialRelationProposalRequest,
    EditorialRelationProposalVersionId,
    EditorialRelationReadPolicy,
    EditorialRelationSupersessionId,
    EditorialRelationTemporalScope,
    EventHypothesisRelationEndpoint,
    ExtractionRelationEvidence,
)

from .entity_4b_helpers import (
    EN_ALIAS_ID,
    EN_MENTION_ID,
    ENTITY_ID,
    ENTITY_VERSION_ID,
    EntityFixtureState,
    decision_request,
    dependency_request,
    mention_request,
    new_entity_proposal_request,
    entity_authorizer,
    entity_read_policy,
    open_entity_system,
    seed_entity_fixture,
)
from .extraction_4a_helpers import (
    extraction_authenticator,
    extraction_proof,
)
from .source_3a_helpers import SOURCE_NOW
from newsroom.relations.editorial_policy import (
    merge_editorial_relation_authority_registries,
)


def _id(identifier_type: type, suffix: int):
    return identifier_type.parse(
        f"00000000-0000-4000-8000-{suffix:012d}"
    )


ZH_NEW_PROPOSAL_ID = _id(EntityResolutionProposalId, 4701)
ZH_NEW_PROPOSAL_V1_ID = _id(EntityResolutionProposalVersionId, 4702)
ZH_ENTITY_ID = _id(CanonicalEntityId, 4703)
ZH_ENTITY_VERSION_ID = _id(CanonicalEntityVersionId, 4704)
ZH_PRIMARY_ALIAS_ID = _id(EntityAliasId, 4705)
EN_RELATION_DEPENDENCY_ID = _id(EntityResolutionDependencyId, 4711)
ZH_RELATION_DEPENDENCY_ID = _id(EntityResolutionDependencyId, 4712)

RELATION_PROPOSAL_ID = _id(EditorialRelationProposalId, 4721)
RELATION_PROPOSAL_V1_ID = _id(EditorialRelationProposalVersionId, 4722)
RELATION_ASSERTION_ID = _id(EditorialRelationAssertionId, 4723)
RELATION_ACCEPT_DECISION_ID = _id(EditorialRelationDecisionId, 4724)
RELATION_HOLD_DECISION_ID = _id(EditorialRelationDecisionId, 4725)
RELATION_SECOND_DECISION_ID = _id(EditorialRelationDecisionId, 4726)
RELATION_SUPERSESSION_ID = _id(EditorialRelationSupersessionId, 4727)
RELATION_HYPOTHESIS_VERSION_ID = _id(IntegratedHypothesisVersionId, 4731)

RELATION_SCOPES = frozenset(
    {
        "authority.relation.propose",
        "authority.relation.decide",
        "authority.relation.read_proposals",
        "authority.relation.read_admitted",
        "authority.relation.read_projection",
    }
)


@dataclass(frozen=True, slots=True)
class EditorialRelationFixtureState:
    entity: EntityFixtureState
    en_resolution_proposal: object
    zh_resolution_proposal: object
    accepted_dependencies: tuple[EntityResolutionDependencyId, ...]


def relation_authorizer(
    *, scopes: frozenset[str] | None = None
) -> StaticAuthorizer:
    return StaticAuthorizer(
        policy_version="editorial-relation-authority-authz-v1",
        grants_by_principal={
            "principal.alpha": RELATION_SCOPES if scopes is None else scopes
        },
    )


def relation_read_policy() -> EditorialRelationReadPolicy:
    return EditorialRelationReadPolicy(
        policy_id="increment-4c-relation-read-v1",
        purpose="editorial.relation.authority.audit",
        proposal_required_scope="authority.relation.read_proposals",
        admitted_required_scope="authority.relation.read_admitted",
        projection_required_scope="authority.relation.read_projection",
        allowed_principal_ids=frozenset({"principal.alpha"}),
        max_results=100,
    )


def open_relation_system(
    state: EntityFixtureState | EditorialRelationFixtureState,
    *,
    scopes: frozenset[str] | None = None,
    authorizer=None,
):
    entity_state = state.entity if isinstance(state, EditorialRelationFixtureState) else state
    return open_governed_editorial_relation_authority_system(
        path=entity_state.extraction.database,
        registry=entity_state.extraction.commands,
        payload_schemas=entity_state.extraction.schemas,
        authenticator=extraction_authenticator(),
        authorizer=(
            relation_authorizer(scopes=scopes) if authorizer is None else authorizer
        ),
        read_policy=relation_read_policy(),
        clock=lambda: SOURCE_NOW,
    )



def open_entity_system_after_relation(
    state: EntityFixtureState | EditorialRelationFixtureState,
):
    entity_state = state.entity if isinstance(state, EditorialRelationFixtureState) else state
    registry, schemas = merge_editorial_relation_authority_registries(
        command_registry=entity_state.extraction.commands,
        payload_schemas=entity_state.extraction.schemas,
    )
    return open_governed_entity_authority_system(
        path=entity_state.extraction.database,
        registry=registry,
        payload_schemas=schemas,
        authenticator=extraction_authenticator(),
        authorizer=entity_authorizer(),
        read_policy=entity_read_policy(),
        clock=lambda: SOURCE_NOW,
    )

def _zh_new_entity_proposal_request(
    state: EntityFixtureState,
) -> EntityResolutionProposalRequest:
    return EntityResolutionProposalRequest(
        proposal_id=ZH_NEW_PROPOSAL_ID,
        proposal_version_id=ZH_NEW_PROPOSAL_V1_ID,
        version_number=1,
        expected_previous_version_id=None,
        source_proposal_id=state.zh_source.proposal_id,
        expected_source_proposal_digest=state.zh_source.canonical_digest,
        kind=EntityResolutionProposalKind.MENTION_TO_NEW_ENTITY,
        subject_mention_id=_id(type(EN_MENTION_ID), 4202),
        object_mention_id=None,
        candidate_entity_id=None,
        candidate_entity_version_id=None,
        confidence_basis_points=9_700,
        uncertainty_codes=(),
        basis_codes=("EXACT_SOURCE_MENTION",),
        idempotency_key="relation-fixture-zh-new-entity-v1",
    )


def seed_relation_fixture(
    root: Path,
    *,
    resolve_secondary: bool = True,
) -> EditorialRelationFixtureState:
    state = seed_entity_fixture(root)
    with open_entity_system(state) as system:
        system.entities.admit_mention(
            mention_request(
                state.en_source,
                mention_id=EN_MENTION_ID,
                language="en-GB",
                key="relation-fixture-en-mention-v1",
            ),
            proof=extraction_proof(),
        )
        system.entities.admit_mention(
            mention_request(
                state.zh_source,
                mention_id=_id(type(EN_MENTION_ID), 4202),
                language="zh-HK",
                key="relation-fixture-zh-mention-v1",
            ),
            proof=extraction_proof(),
        )
        en_proposal = system.entities.propose_resolution(
            new_entity_proposal_request(
                state,
                key="relation-fixture-en-resolution-v1",
            ),
            proof=extraction_proof(),
        )
        system.entities.decide_resolution(
            decision_request(
                en_proposal,
                action=EntityResolutionDecisionAction.ACCEPT,
                entity_id=ENTITY_ID,
                version_id=ENTITY_VERSION_ID,
                alias_id=EN_ALIAS_ID,
                alias_kind=EntityAliasKind.PRIMARY_NAME,
                key="relation-fixture-en-accept-v1",
            ),
            proof=extraction_proof(),
        )
        zh_proposal = system.entities.propose_resolution(
            _zh_new_entity_proposal_request(state),
            proof=extraction_proof(),
        )
        if resolve_secondary:
            system.entities.decide_resolution(
                decision_request(
                    zh_proposal,
                    action=EntityResolutionDecisionAction.ACCEPT,
                    entity_id=ZH_ENTITY_ID,
                    version_id=ZH_ENTITY_VERSION_ID,
                    alias_id=ZH_PRIMARY_ALIAS_ID,
                    alias_kind=EntityAliasKind.PRIMARY_NAME,
                    key="relation-fixture-zh-accept-v1",
                ),
                proof=extraction_proof(),
            )
        en_dependency = system.entities.bind_resolution_dependency(
            dependency_request(
                state,
                en_proposal,
                dependency_id=EN_RELATION_DEPENDENCY_ID,
                key="relation-fixture-en-dependency-v1",
            ),
            proof=extraction_proof(),
        )
        zh_dependency = system.entities.bind_resolution_dependency(
            dependency_request(
                state,
                zh_proposal,
                dependency_id=ZH_RELATION_DEPENDENCY_ID,
                key="relation-fixture-zh-dependency-v1",
            ),
            proof=extraction_proof(),
        )
    return EditorialRelationFixtureState(
        entity=state,
        en_resolution_proposal=en_proposal,
        zh_resolution_proposal=zh_proposal,
        accepted_dependencies=(en_dependency.dependency_id, zh_dependency.dependency_id),
    )


def relation_proposal_request(
    state: EditorialRelationFixtureState,
    *,
    proposal_id: EditorialRelationProposalId = RELATION_PROPOSAL_ID,
    proposal_version_id: EditorialRelationProposalVersionId = RELATION_PROPOSAL_V1_ID,
    version_number: int = 1,
    previous_version_id: EditorialRelationProposalVersionId | None = None,
    dependency_ids: tuple[EntityResolutionDependencyId, ...] | None = None,
    key: str = "relation-proposal-v1",
) -> EditorialRelationProposalRequest:
    source = state.entity.relation_source
    evidence_range = source.evidence[0]
    evidence = ExtractionRelationEvidence(
        source_proposal_id=source.proposal_id,
        source_proposal_digest=source.canonical_digest,
        run_id=source.run_id,
        run_version_id=source.run_version_id,
        output_id=source.output_id,
        passage_id=evidence_range.passage_id,
        source_evidence_ordinal=0,
        start_byte=evidence_range.start_byte,
        end_byte=evidence_range.end_byte,
        evidence_text_digest=evidence_range.evidence_text_digest,
    )
    predicate = EditorialPredicateCode.ABOUT_EVENT
    contract = EDITORIAL_PREDICATE_REGISTRY_V1.contract(predicate)
    dependencies = (
        state.accepted_dependencies if dependency_ids is None else dependency_ids
    )
    return EditorialRelationProposalRequest(
        proposal_id=proposal_id,
        proposal_version_id=proposal_version_id,
        version_number=version_number,
        expected_previous_version_id=previous_version_id,
        predicate_registry_digest=EDITORIAL_PREDICATE_REGISTRY_V1.digest,
        predicate_contract_digest=contract.digest,
        predicate=predicate,
        subject=CanonicalEntityRelationEndpoint(
            entity_id=ENTITY_ID,
            entity_version_id=ENTITY_VERSION_ID,
        ),
        object=EventHypothesisRelationEndpoint(
            hypothesis_version_id=RELATION_HYPOTHESIS_VERSION_ID
        ),
        temporal_scope=EditorialRelationTemporalScope(
            valid_from=None,
            valid_until=None,
            observed_at=SOURCE_NOW,
        ),
        evidence=(evidence,),
        resolution_dependency_ids=dependencies,
        producer=EditorialRelationProducer(
            kind=EditorialRelationProducerKind.EXTRACTION_RUN,
            producer_id="fixture.increment-4c",
            producer_version="fixture-increment-4c-v1",
            contract_digest=source.producer_contract_digest,
        ),
        statement="The admitted entity is about the retained event hypothesis.",
        confidence_basis_points=9_100,
        uncertainty_codes=("EDITORIAL_REVIEW_REQUIRED",),
        basis_codes=("EXACT_EXTRACTION_EVIDENCE",),
        idempotency_key=key,
    )


def relation_decision_request(
    proposal,
    *,
    action: EditorialRelationDecisionAction,
    decision_id: EditorialRelationDecisionId,
    expected_previous_version: int = 0,
    previous_decision_id: EditorialRelationDecisionId | None = None,
    assertion_id: EditorialRelationAssertionId | None = None,
    target_assertion_id: EditorialRelationAssertionId | None = None,
    successor_assertion_id: EditorialRelationAssertionId | None = None,
    supersession_id: EditorialRelationSupersessionId | None = None,
    key: str,
) -> EditorialRelationDecisionRequest:
    return EditorialRelationDecisionRequest(
        decision_id=decision_id,
        action=action,
        proposal_id=proposal.proposal_id,
        proposal_version_id=proposal.proposal_version_id,
        expected_proposal_version_digest=proposal.canonical_digest,
        expected_previous_decision_id=previous_decision_id,
        expected_previous_decision_version=expected_previous_version,
        assertion_id=assertion_id,
        target_assertion_id=target_assertion_id,
        successor_assertion_id=successor_assertion_id,
        supersession_id=supersession_id,
        reason_code=f"FIXTURE_{action.value}",
        decision_policy_version=EDITORIAL_RELATION_ADMISSION_POLICY_VERSION,
        idempotency_key=key,
    )


__all__ = [name for name in globals() if name.isupper()] + [
    "EditorialRelationFixtureState",
    "open_entity_system_after_relation",
    "open_relation_system",
    "relation_authorizer",
    "relation_decision_request",
    "relation_proposal_request",
    "relation_read_policy",
    "seed_relation_fixture",
]
