from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from newsroom.authority._editorial_relation_system import (
    open_governed_editorial_relation_authority_system,
)
from newsroom.authority._entity_system import open_governed_entity_authority_system
from newsroom.authority._extraction_system import (
    open_governed_extraction_authority_system,
)
from newsroom.authority._neo4j_projection_system import _open_with_adapter
from newsroom.sources import open_governed_source_registry_authority_system
from newsroom.entities import (
    EntityAliasKind,
    EntityResolutionDecisionAction,
    EntityResolutionProposalKind,
    EntityResolutionProposalRequest,
)
from newsroom.extraction import ExtractionProposalKind, FixtureExtractionCase
from newsroom.graphiti_adapter import GraphitiAttemptRecord, GraphitiAttemptRequest
from newsroom.graphiti_adapter.policy import (
    merge_graphiti_adapter_authority_registries,
)
from newsroom.increment4 import (
    Increment4AdmittedProjectionSnapshot,
    Increment4RelationProjectionState,
    increment4_admitted_contract_registry,
    sorted_snapshot,
)
from newsroom.projection import merge_projection_authority_registries
from newsroom.relations import (
    EditorialRelationCurrentView,
    EditorialRelationDecision,
    EditorialRelationDecisionAction,
    EditorialRelationProjectionEvent,
    EditorialRelationProposal,
)
from .editorial_relation_4c_helpers import (
    EN_RELATION_DEPENDENCY_ID,
    ZH_ENTITY_ID,
    ZH_ENTITY_VERSION_ID,
    ZH_NEW_PROPOSAL_ID,
    ZH_NEW_PROPOSAL_V1_ID,
    ZH_PRIMARY_ALIAS_ID,
    RELATION_ACCEPT_DECISION_ID,
    RELATION_ASSERTION_ID,
    ZH_RELATION_DEPENDENCY_ID,
    EditorialRelationFixtureState,
    relation_authorizer,
    relation_decision_request,
    relation_proposal_request,
    relation_read_policy,
)
from .entity_4b_helpers import (
    EN_ALIAS_ID,
    EN_MENTION_ID,
    ENTITY_ID,
    ENTITY_VERSION_ID,
    ZH_MENTION_ID,
    EntityFixtureState,
    HomonymEntityFixtureState,
    decision_request,
    dependency_request,
    entity_authorizer,
    entity_read_policy,
    mention_request,
    new_entity_proposal_request,
)
from .extraction_4a_helpers import (
    ExtractionFixtureState,
    extraction_authenticator,
    extraction_authorizer,
    extraction_proof,
    extraction_read_policy,
)
from .graphiti_adapter_4d_authority_helpers import (
    approval_from_authority,
    fake_attempt,
    open_graphiti_system,
    replay_attempt_for_new_budgeted_run,
    seed_graphiti_authority_fixture,
)
from .increment4e_helpers import (
    _entity_state,
    _ledger_events,
    increment4_projection_authorizer,
    increment4_projection_read_policy,
)
from .projection_b1_helpers import event_read_policy
from .source_3a_helpers import (
    SOURCE_NOW,
    authenticator as source_authenticator,
    authorizer as source_authorizer,
    read_policy as source_read_policy,
)


@dataclass(frozen=True, slots=True)
class Increment4GraphitiPathState:
    relation: EditorialRelationFixtureState
    source_request: GraphitiAttemptRequest
    source_attempt: GraphitiAttemptRecord
    replay_request: GraphitiAttemptRequest
    replay_attempt: GraphitiAttemptRecord
    workspace_root: Path

    @property
    def extraction(self) -> ExtractionFixtureState:
        return self.relation.entity.extraction


@dataclass(frozen=True, slots=True)
class Increment4HomonymGraphitiPathState:
    entity: HomonymEntityFixtureState
    source_request: GraphitiAttemptRequest
    source_attempt: GraphitiAttemptRecord
    workspace_root: Path

    @property
    def extraction(self) -> ExtractionFixtureState:
        return self.entity.extraction


@dataclass(frozen=True, slots=True)
class Increment4GraphitiAdmittedPath:
    path: Increment4GraphitiPathState
    proposal: EditorialRelationProposal
    decision: EditorialRelationDecision
    current: EditorialRelationCurrentView
    projection_event: EditorialRelationProjectionEvent
    snapshot: Increment4AdmittedProjectionSnapshot


def graphiti_path_registries(state: ExtractionFixtureState):
    commands, schemas = merge_graphiti_adapter_authority_registries(
        command_registry=state.commands,
        payload_schemas=state.schemas,
    )
    return merge_projection_authority_registries(
        command_registry=commands,
        payload_schemas=schemas,
    )


def open_graphiti_path_source_system(state: ExtractionFixtureState):
    commands, schemas = graphiti_path_registries(state)
    return open_governed_source_registry_authority_system(
        path=state.database,
        registry=commands,
        payload_schemas=schemas,
        authenticator=source_authenticator(),
        authorizer=source_authorizer(),
        read_policy=source_read_policy(),
        clock=lambda: SOURCE_NOW,
    )


def open_graphiti_path_extraction_system(state: ExtractionFixtureState):
    commands, schemas = graphiti_path_registries(state)
    return open_governed_extraction_authority_system(
        path=state.database,
        registry=commands,
        payload_schemas=schemas,
        authenticator=extraction_authenticator(),
        authorizer=extraction_authorizer(),
        read_policy=extraction_read_policy(),
        clock=lambda: SOURCE_NOW,
    )


def open_graphiti_path_entity_system(
    state: EntityFixtureState | HomonymEntityFixtureState,
    *,
    scopes: frozenset[str] | None = None,
):
    commands, schemas = graphiti_path_registries(state.extraction)
    return open_governed_entity_authority_system(
        path=state.extraction.database,
        registry=commands,
        payload_schemas=schemas,
        authenticator=extraction_authenticator(),
        authorizer=entity_authorizer(scopes=scopes),
        read_policy=entity_read_policy(),
        clock=lambda: SOURCE_NOW,
    )


def open_graphiti_path_relation_system(
    state: EditorialRelationFixtureState,
    *,
    scopes: frozenset[str] | None = None,
):
    commands, schemas = graphiti_path_registries(state.entity.extraction)
    return open_governed_editorial_relation_authority_system(
        path=state.entity.extraction.database,
        registry=commands,
        payload_schemas=schemas,
        authenticator=extraction_authenticator(),
        authorizer=relation_authorizer(scopes=scopes),
        read_policy=relation_read_policy(),
        clock=lambda: SOURCE_NOW,
    )



def open_graphiti_path_increment4_neo4j_system(
    state: EditorialRelationFixtureState,
    adapter,
    *,
    scopes: frozenset[str] | None = None,
):
    commands, schemas = graphiti_path_registries(state.entity.extraction)
    return _open_with_adapter(
        path=state.entity.extraction.database,
        registry=commands,
        payload_schemas=schemas,
        contracts=increment4_admitted_contract_registry(),
        authenticator=extraction_authenticator(),
        authorizer=increment4_projection_authorizer(scopes=scopes),
        event_read_policy=event_read_policy(),
        projection_read_policy=increment4_projection_read_policy(),
        adapter=adapter,
        clock=lambda: SOURCE_NOW,
    )


def graphiti_path_current_snapshot(
    state: EditorialRelationFixtureState,
) -> Increment4AdmittedProjectionSnapshot:
    with open_graphiti_path_relation_system(state) as relations:
        current = relations.relations.current_relations(
            limit=100,
            proof=extraction_proof(),
        )
        projection_events = relations.relations.projection_events_after(
            after_ledger_seq=0,
            limit=100,
            proof=extraction_proof(),
        )
    latest_upsert_by_assertion = {
        event.assertion_id: event
        for event in projection_events
        if event.assertion is not None
    }
    relation_states = tuple(
        Increment4RelationProjectionState(
            item,
            latest_upsert_by_assertion[item.assertion.assertion_id],
        )
        for item in current
    )
    with open_graphiti_path_entity_system(state.entity) as entities:
        admitted_entities = (
            _entity_state(entities, ENTITY_ID, ENTITY_VERSION_ID),
            _entity_state(entities, ZH_ENTITY_ID, ZH_ENTITY_VERSION_ID),
        )
    events = _ledger_events(state.entity.extraction.database)
    return sorted_snapshot(
        entities=admitted_entities,
        relations=relation_states,
        events=events,
        through_ledger_seq=events[-1].ledger_seq,
    )


def graphiti_path_snapshot(
    state: EditorialRelationFixtureState,
    *,
    current_relation,
    relation_projection_event,
):
    with open_graphiti_path_entity_system(state.entity) as entities:
        admitted_entities = (
            _entity_state(entities, ENTITY_ID, ENTITY_VERSION_ID),
            _entity_state(entities, ZH_ENTITY_ID, ZH_ENTITY_VERSION_ID),
        )
    events = _ledger_events(state.entity.extraction.database)
    return sorted_snapshot(
        entities=admitted_entities,
        relations=(
            Increment4RelationProjectionState(
                current_relation,
                relation_projection_event,
            ),
        ),
        events=events,
        through_ledger_seq=events[-1].ledger_seq,
    )

def _proposals_from_attempt(
    state: ExtractionFixtureState,
    attempt: GraphitiAttemptRecord,
):
    with open_graphiti_path_extraction_system(state) as extraction:
        return extraction.extraction.proposals(
            attempt.run_version_id,
            proof=extraction_proof(),
        )


def _entity_fixture_from_attempt(
    state: ExtractionFixtureState,
    attempt: GraphitiAttemptRecord,
) -> EntityFixtureState:
    proposals = _proposals_from_attempt(state, attempt)
    en_source = next(
        proposal
        for proposal in proposals
        if proposal.kind is ExtractionProposalKind.ENTITY_MENTION
        and proposal.subject_placeholder == "Hong Kong Transport Department"
    )
    zh_source = next(
        proposal
        for proposal in proposals
        if proposal.kind is ExtractionProposalKind.ENTITY_MENTION
        and proposal.subject_placeholder == "香港運輸署"
    )
    equivalence_source = next(
        proposal
        for proposal in proposals
        if proposal.kind is ExtractionProposalKind.ENTITY_EQUIVALENCE
    )
    relation_source = next(
        proposal
        for proposal in proposals
        if proposal.kind is ExtractionProposalKind.RELATION
    )
    return EntityFixtureState(
        extraction=state,
        en_source=en_source,
        zh_source=zh_source,
        equivalence_source=equivalence_source,
        relation_source=relation_source,
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
        subject_mention_id=ZH_MENTION_ID,
        object_mention_id=None,
        candidate_entity_id=None,
        candidate_entity_version_id=None,
        confidence_basis_points=9_700,
        uncertainty_codes=(),
        basis_codes=("EXACT_SOURCE_MENTION",),
        idempotency_key="increment-4e-graphiti-zh-new-entity-v1",
    )


def seed_increment4_homonym_graphiti_path(
    root: Path,
) -> Increment4HomonymGraphitiPathState:
    extraction_state = seed_graphiti_authority_fixture(
        root / "authority",
        fixture_case=FixtureExtractionCase.BILINGUAL_HOMONYM,
    )
    workspace_root = (root / "proposal-workspace").resolve()
    source_request = fake_attempt(
        extraction_state,
        fixture_case=FixtureExtractionCase.BILINGUAL_HOMONYM,
    )
    with open_graphiti_system(
        extraction_state,
        workspace_root=workspace_root,
    ) as graphiti:
        graphiti.graphiti.register_configuration(
            source_request.configuration,
            proof=extraction_proof(),
        )
        source_attempt = graphiti.graphiti.execute_attempt(
            source_request,
            proof=extraction_proof(),
        )
    proposals = {
        proposal.local_id: proposal
        for proposal in _proposals_from_attempt(extraction_state, source_attempt)
    }
    entity_state = HomonymEntityFixtureState(
        extraction=extraction_state,
        en_transit_source=proposals[
            "entity.chan-chi-ming.harbour-transit.en"
        ],
        en_association_source=proposals[
            "entity.chan-chi-ming.harbour-association.en"
        ],
        zh_transit_source=proposals[
            "entity.chan-chi-ming.harbour-transit.zh-hk"
        ],
        zh_association_source=proposals[
            "entity.chan-chi-ming.harbour-association.zh-hk"
        ],
        equivalence_transit_source=proposals[
            "equivalence.chan-chi-ming.harbour-transit.bilingual"
        ],
        equivalence_association_source=proposals[
            "equivalence.chan-chi-ming.harbour-association.bilingual"
        ],
    )
    return Increment4HomonymGraphitiPathState(
        entity=entity_state,
        source_request=source_request,
        source_attempt=source_attempt,
        workspace_root=workspace_root,
    )


def seed_increment4_graphiti_path(
    root: Path,
    *,
    resolve_secondary: bool = True,
) -> Increment4GraphitiPathState:
    extraction_state = seed_graphiti_authority_fixture(root / "authority")
    workspace_root = (root / "proposal-workspace").resolve()
    source_request = fake_attempt(extraction_state)
    with open_graphiti_system(
        extraction_state,
        workspace_root=workspace_root,
    ) as graphiti:
        graphiti.graphiti.register_configuration(
            source_request.configuration,
            proof=extraction_proof(),
        )
        source_attempt = graphiti.graphiti.execute_attempt(
            source_request,
            proof=extraction_proof(),
        )
    approval_request = approval_from_authority(
        extraction_state,
        source_attempt,
        key="increment-4e-approved-replay-v1",
    )
    with open_graphiti_system(
        extraction_state,
        workspace_root=workspace_root,
    ) as graphiti:
        approval = graphiti.graphiti.approve_replay(
            approval_request,
            proof=extraction_proof(),
        )
        replay_request = replay_attempt_for_new_budgeted_run(
            extraction_state,
            approval.source,
        )
        graphiti.graphiti.register_configuration(
            replay_request.configuration,
            proof=extraction_proof(),
        )
        replay_attempt = graphiti.graphiti.execute_attempt(
            replay_request,
            proof=extraction_proof(),
        )

    # Downstream authority deliberately binds the approved replay Run Version,
    # proving retained output—not the disposable private workspace—is sufficient.
    entity_state = _entity_fixture_from_attempt(extraction_state, replay_attempt)
    with open_graphiti_path_entity_system(entity_state) as entities:
        entities.entities.admit_mention(
            mention_request(
                entity_state.en_source,
                mention_id=EN_MENTION_ID,
                language="en-GB",
                key="increment-4e-graphiti-en-mention-v1",
            ),
            proof=extraction_proof(),
        )
        entities.entities.admit_mention(
            mention_request(
                entity_state.zh_source,
                mention_id=ZH_MENTION_ID,
                language="zh-HK",
                key="increment-4e-graphiti-zh-mention-v1",
            ),
            proof=extraction_proof(),
        )
        en_proposal = entities.entities.propose_resolution(
            new_entity_proposal_request(
                entity_state,
                key="increment-4e-graphiti-en-resolution-v1",
            ),
            proof=extraction_proof(),
        )
        entities.entities.decide_resolution(
            decision_request(
                en_proposal,
                action=EntityResolutionDecisionAction.ACCEPT,
                entity_id=ENTITY_ID,
                version_id=ENTITY_VERSION_ID,
                alias_id=EN_ALIAS_ID,
                alias_kind=EntityAliasKind.PRIMARY_NAME,
                key="increment-4e-graphiti-en-accept-v1",
            ),
            proof=extraction_proof(),
        )
        zh_proposal = entities.entities.propose_resolution(
            _zh_new_entity_proposal_request(entity_state),
            proof=extraction_proof(),
        )
        if resolve_secondary:
            entities.entities.decide_resolution(
                decision_request(
                    zh_proposal,
                    action=EntityResolutionDecisionAction.ACCEPT,
                    entity_id=ZH_ENTITY_ID,
                    version_id=ZH_ENTITY_VERSION_ID,
                    alias_id=ZH_PRIMARY_ALIAS_ID,
                    alias_kind=EntityAliasKind.PRIMARY_NAME,
                    key="increment-4e-graphiti-zh-accept-v1",
                ),
                proof=extraction_proof(),
            )
        en_dependency = entities.entities.bind_resolution_dependency(
            dependency_request(
                entity_state,
                en_proposal,
                dependency_id=EN_RELATION_DEPENDENCY_ID,
                key="increment-4e-graphiti-en-dependency-v1",
            ),
            proof=extraction_proof(),
        )
        zh_dependency = entities.entities.bind_resolution_dependency(
            dependency_request(
                entity_state,
                zh_proposal,
                dependency_id=ZH_RELATION_DEPENDENCY_ID,
                key="increment-4e-graphiti-zh-dependency-v1",
            ),
            proof=extraction_proof(),
        )

    relation_state = EditorialRelationFixtureState(
        entity=entity_state,
        en_resolution_proposal=en_proposal,
        zh_resolution_proposal=zh_proposal,
        accepted_dependencies=(
            en_dependency.dependency_id,
            zh_dependency.dependency_id,
        ),
    )
    return Increment4GraphitiPathState(
        relation=relation_state,
        source_request=source_request,
        source_attempt=source_attempt,
        replay_request=replay_request,
        replay_attempt=replay_attempt,
        workspace_root=workspace_root,
    )


def admit_increment4_graphiti_path(
    state: Increment4GraphitiPathState,
) -> Increment4GraphitiAdmittedPath:
    with open_graphiti_path_relation_system(state.relation) as relations:
        proposal = relations.relations.propose(
            relation_proposal_request(
                state.relation,
                key="increment-4e-graphiti-relation-proposal-v1",
            ),
            proof=extraction_proof(),
        )
        decision = relations.relations.decide(
            relation_decision_request(
                proposal,
                action=EditorialRelationDecisionAction.ACCEPT,
                decision_id=RELATION_ACCEPT_DECISION_ID,
                assertion_id=RELATION_ASSERTION_ID,
                key="increment-4e-graphiti-relation-accept-v1",
            ),
            proof=extraction_proof(),
        )
        current = relations.relations.current(
            RELATION_ASSERTION_ID,
            proof=extraction_proof(),
        )
        projection_event = [
            item
            for item in relations.relations.projection_events_after(
                after_ledger_seq=0,
                limit=100,
                proof=extraction_proof(),
            )
            if item.assertion_id == RELATION_ASSERTION_ID
            and item.assertion is not None
        ][-1]

    with open_graphiti_path_entity_system(state.relation.entity) as entities:
        projected_entities = (
            _entity_state(entities, ENTITY_ID, ENTITY_VERSION_ID),
            _entity_state(entities, ZH_ENTITY_ID, ZH_ENTITY_VERSION_ID),
        )
    events = _ledger_events(state.extraction.database)
    snapshot = sorted_snapshot(
        entities=projected_entities,
        relations=(
            Increment4RelationProjectionState(current, projection_event),
        ),
        events=events,
        through_ledger_seq=events[-1].ledger_seq,
    )
    return Increment4GraphitiAdmittedPath(
        path=state,
        proposal=proposal,
        decision=decision,
        current=current,
        projection_event=projection_event,
        snapshot=snapshot,
    )


__all__ = [
    "Increment4GraphitiAdmittedPath",
    "Increment4GraphitiPathState",
    "admit_increment4_graphiti_path",
    "Increment4HomonymGraphitiPathState",
    "graphiti_path_current_snapshot",
    "graphiti_path_registries",
    "graphiti_path_snapshot",
    "open_graphiti_path_entity_system",
    "open_graphiti_path_increment4_neo4j_system",
    "open_graphiti_path_extraction_system",
    "open_graphiti_path_relation_system",
    "open_graphiti_path_source_system",
    "seed_increment4_graphiti_path",
    "seed_increment4_homonym_graphiti_path",
]
