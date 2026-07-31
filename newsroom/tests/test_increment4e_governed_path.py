from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest

from newsroom.authority import UtcTimestamp
from newsroom.sources import open_governed_source_registry_authority_system
from newsroom.entities import EntityAliasKind, EntityResolutionDecisionAction
from newsroom.increment4 import Increment4Neo4jBuildRequest, sorted_snapshot
from newsroom.projection import ProjectionGenerationId, ProjectionGenerationState
from newsroom.relations import (
    EDITORIAL_PREDICATE_REGISTRY_V1,
    EditorialPredicateCode,
    EditorialRelationDecisionAction,
    EditorialRelationDecisionConflict,
    EditorialRelationTemporalScope,
    SourceRevisionRelationEndpoint,
)

from .editorial_relation_4c_helpers import (
    RELATION_ACCEPT_DECISION_ID,
    RELATION_ASSERTION_ID,
    RELATION_HOLD_DECISION_ID,
    RELATION_SECOND_DECISION_ID,
    ZH_ENTITY_ID,
    ZH_ENTITY_VERSION_ID,
    ZH_PRIMARY_ALIAS_ID,
    ZH_RELATION_DEPENDENCY_ID,
    relation_decision_request,
    relation_proposal_request,
)
from .extraction_4a_helpers import extraction_proof
from .entity_4b_helpers import decision_request as entity_decision_request
from .increment4e_governed_path_helpers import (
    graphiti_path_registries,
    graphiti_path_snapshot,
    open_graphiti_path_entity_system,
    open_graphiti_path_increment4_neo4j_system,
    open_graphiti_path_relation_system,
    seed_increment4_graphiti_path,
)
from .projection_b2_helpers import MemoryNeo4jAdapter
from .source_3a_helpers import (
    ITEM_ID,
    REVISION_1_ID,
    REVISION_2_ID,
    SOURCE_NOW,
    authenticator as source_authenticator,
    authorizer as source_authorizer,
    proof as source_proof,
    read_policy as source_read_policy,
    revision_request,
)


GENERATION_ID = ProjectionGenerationId.parse(
    "00000000-0000-4000-8000-000000004981"
)


def _count(path: Path, table: str) -> int:
    with closing(sqlite3.connect(path)) as conn:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    assert row is not None
    return int(row[0])


def test_fake_and_replay_feed_governed_admission_without_workspace_authority(
    tmp_path: Path,
) -> None:
    state = seed_increment4_graphiti_path(tmp_path)
    database = state.extraction.database

    assert state.source_attempt.outcome.value == "COMPLETE"
    assert state.replay_attempt.outcome.value == "COMPLETE"
    assert state.source_attempt.run_id != state.replay_attempt.run_id
    assert state.source_attempt.cleanup_receipt.workspace_absent is True
    assert state.replay_attempt.cleanup_receipt.workspace_absent is True
    assert not state.workspace_root.exists() or not any(state.workspace_root.iterdir())
    assert _count(database, "graphiti_adapter_attempts") == 2

    with open_graphiti_path_relation_system(state.relation) as relations:
        assert relations.relations.current_relations(
            limit=10,
            proof=extraction_proof(),
        ) == ()
        proposal = relations.relations.propose(
            relation_proposal_request(
                state.relation,
                key="increment-4e-graphiti-relation-proposal-v1",
            ),
            proof=extraction_proof(),
        )
        admitted = relations.relations.decide(
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
        relation_event = [
            event
            for event in relations.relations.projection_events_after(
                after_ledger_seq=0,
                limit=100,
                proof=extraction_proof(),
            )
            if event.assertion_id == RELATION_ASSERTION_ID
            and event.assertion is not None
        ][-1]

    assert admitted.current_state.value == "ADMITTED"
    snapshot = graphiti_path_snapshot(
        state.relation,
        current_relation=current,
        relation_projection_event=relation_event,
    )
    adapter = MemoryNeo4jAdapter()
    with open_graphiti_path_increment4_neo4j_system(
        state.relation,
        adapter,
    ) as projection:
        result = projection.increment4.build_and_promote(
            Increment4Neo4jBuildRequest(
                generation_id=GENERATION_ID,
                snapshot=snapshot,
                reason_code="INCREMENT4_GRAPHITI_GOVERNED_PATH_PROOF",
                idempotency_key="increment-4e-graphiti-generation-v1",
            ),
            proof=extraction_proof(),
        )

    assert result.generation.state is ProjectionGenerationState.ACTIVE
    nodes = [
        node
        for batch in adapter.deliveries.values()
        for node in batch.nodes
    ]
    relations = [
        relation
        for batch in adapter.deliveries.values()
        for relation in batch.relations
    ]
    assert nodes
    assert relations
    assert all(relation.trust_scope.value == "ADMITTED" for relation in relations)
    identity_sources = {node.identity_source for node in nodes}
    assert identity_sources <= {
        "AUTHORITY_EVENT_ID",
        "CANONICAL_ENTITY_ID",
        "CANONICAL_ENTITY_VERSION_ID",
        "EDITORIAL_RELATION_ASSERTION_ID",
        "ENTITY_ALIAS_ID",
    }
    assert not any("GRAPHITI" in source for source in identity_sources)
    assert not any("PROPOSAL" in source for source in identity_sources)
    assert not state.workspace_root.exists() or not any(state.workspace_root.iterdir())


def test_exact_bilingual_evidence_can_add_translation_alias_only_after_acceptance(
    tmp_path: Path,
) -> None:
    from newsroom.entities import (
        EntityAliasKind,
        EntityResolutionDecisionAction,
        EntityResolutionProposalKind,
        EntityResolutionProposalRequest,
    )

    from .entity_4b_helpers import (
        EN_MENTION_ID,
        ENTITY_ID,
        ENTITY_VERSION_ID,
        ZH_ALIAS_ID,
        ZH_EQ_PROPOSAL_ID,
        ZH_EQ_PROPOSAL_V1_ID,
        ZH_MENTION_ID,
        decision_request,
    )
    from .increment4e_governed_path_helpers import (
        open_graphiti_path_entity_system,
    )

    state = seed_increment4_graphiti_path(tmp_path, resolve_secondary=False)
    entity_state = state.relation.entity
    request = EntityResolutionProposalRequest(
        proposal_id=ZH_EQ_PROPOSAL_ID,
        proposal_version_id=ZH_EQ_PROPOSAL_V1_ID,
        version_number=1,
        expected_previous_version_id=None,
        source_proposal_id=entity_state.equivalence_source.proposal_id,
        expected_source_proposal_digest=(
            entity_state.equivalence_source.canonical_digest
        ),
        kind=EntityResolutionProposalKind.MENTION_EQUIVALENCE,
        subject_mention_id=ZH_MENTION_ID,
        object_mention_id=EN_MENTION_ID,
        candidate_entity_id=None,
        candidate_entity_version_id=None,
        confidence_basis_points=8_500,
        uncertainty_codes=("REQUIRES_EXPLICIT_RESOLUTION",),
        basis_codes=("EXACT_BILINGUAL_EVIDENCE",),
        idempotency_key="increment-4e-graphiti-bilingual-equivalence-v1",
    )

    with open_graphiti_path_entity_system(entity_state) as entities:
        proposal = entities.entities.propose_resolution(
            request,
            proof=extraction_proof(),
        )
        assert [
            alias.language
            for alias in entities.entities.aliases(
                ENTITY_ID,
                limit=10,
                proof=extraction_proof(),
            )
        ] == ["en-GB"]
        accepted = entities.entities.decide_resolution(
            decision_request(
                proposal,
                action=EntityResolutionDecisionAction.ACCEPT,
                entity_id=ENTITY_ID,
                version_id=ENTITY_VERSION_ID,
                alias_id=ZH_ALIAS_ID,
                alias_kind=EntityAliasKind.TRANSLATION,
                key="increment-4e-graphiti-bilingual-accept-v1",
            ),
            proof=extraction_proof(),
        )
        aliases = entities.entities.aliases(
            ENTITY_ID,
            limit=10,
            proof=extraction_proof(),
        )

    assert accepted.current_state.value == "ACCEPTED"
    assert {alias.language for alias in aliases} == {"en-GB", "zh-HK"}
    assert {alias.entity_id for alias in aliases} == {ENTITY_ID}
    assert {alias.entity_version_id for alias in aliases} == {ENTITY_VERSION_ID}
    assert {alias.alias_kind for alias in aliases} == {
        EntityAliasKind.PRIMARY_NAME,
        EntityAliasKind.TRANSLATION,
    }


def test_same_name_bilingual_people_from_graphiti_remain_context_separate(
    tmp_path: Path,
) -> None:
    import pytest

    from newsroom.entities import (
        CanonicalEntityId,
        CanonicalEntityVersionId,
        EntityAliasId,
        EntityAliasKind,
        EntityKind,
        EntityMentionId,
        EntityResolutionDecisionAction,
        EntityResolutionProposalId,
        EntityResolutionProposalKind,
        EntityResolutionProposalRequest,
        EntityResolutionProposalVersionId,
        EntityStateError,
    )

    from .entity_4b_helpers import decision_request, mention_request
    from .increment4e_governed_path_helpers import (
        open_graphiti_path_entity_system,
        seed_increment4_homonym_graphiti_path,
    )

    def identifier(identifier_type, suffix: int):
        return identifier_type.parse(
            f"00000000-0000-4000-8000-{suffix:012d}"
        )

    en_transit_mention = identifier(EntityMentionId, 4821)
    en_association_mention = identifier(EntityMentionId, 4822)
    zh_transit_mention = identifier(EntityMentionId, 4823)
    zh_association_mention = identifier(EntityMentionId, 4824)
    transit_proposal_id = identifier(EntityResolutionProposalId, 4831)
    transit_proposal_version_id = identifier(
        EntityResolutionProposalVersionId, 4832
    )
    association_proposal_id = identifier(EntityResolutionProposalId, 4833)
    association_proposal_version_id = identifier(
        EntityResolutionProposalVersionId, 4834
    )
    transit_equivalence_id = identifier(EntityResolutionProposalId, 4841)
    transit_equivalence_version_id = identifier(
        EntityResolutionProposalVersionId, 4842
    )
    association_equivalence_id = identifier(EntityResolutionProposalId, 4843)
    association_equivalence_version_id = identifier(
        EntityResolutionProposalVersionId, 4844
    )
    crossed_equivalence_id = identifier(EntityResolutionProposalId, 4845)
    crossed_equivalence_version_id = identifier(
        EntityResolutionProposalVersionId, 4846
    )
    transit_entity_id = identifier(CanonicalEntityId, 4851)
    transit_version_id = identifier(CanonicalEntityVersionId, 4852)
    transit_en_alias_id = identifier(EntityAliasId, 4853)
    transit_zh_alias_id = identifier(EntityAliasId, 4854)
    association_entity_id = identifier(CanonicalEntityId, 4861)
    association_version_id = identifier(CanonicalEntityVersionId, 4862)
    association_en_alias_id = identifier(EntityAliasId, 4863)
    association_zh_alias_id = identifier(EntityAliasId, 4864)

    state = seed_increment4_homonym_graphiti_path(tmp_path)
    entity_state = state.entity

    def new_entity_request(
        source,
        *,
        mention_id,
        proposal_id,
        proposal_version_id,
        key: str,
    ) -> EntityResolutionProposalRequest:
        return EntityResolutionProposalRequest(
            proposal_id=proposal_id,
            proposal_version_id=proposal_version_id,
            version_number=1,
            expected_previous_version_id=None,
            source_proposal_id=source.proposal_id,
            expected_source_proposal_digest=source.canonical_digest,
            kind=EntityResolutionProposalKind.MENTION_TO_NEW_ENTITY,
            subject_mention_id=mention_id,
            object_mention_id=None,
            candidate_entity_id=None,
            candidate_entity_version_id=None,
            confidence_basis_points=9_600,
            uncertainty_codes=("SAME_NAME_DISTINCT_CONTEXT",),
            basis_codes=("EXACT_SOURCE_MENTION",),
            idempotency_key=key,
        )

    def equivalence_request(
        source,
        *,
        subject_mention_id,
        object_mention_id,
        proposal_id,
        proposal_version_id,
        key: str,
    ) -> EntityResolutionProposalRequest:
        return EntityResolutionProposalRequest(
            proposal_id=proposal_id,
            proposal_version_id=proposal_version_id,
            version_number=1,
            expected_previous_version_id=None,
            source_proposal_id=source.proposal_id,
            expected_source_proposal_digest=source.canonical_digest,
            kind=EntityResolutionProposalKind.MENTION_EQUIVALENCE,
            subject_mention_id=subject_mention_id,
            object_mention_id=object_mention_id,
            candidate_entity_id=None,
            candidate_entity_version_id=None,
            confidence_basis_points=8_000,
            uncertainty_codes=(
                "REQUIRES_EXPLICIT_RESOLUTION",
                "SAME_NAME_DISTINCT_CONTEXT",
            ),
            basis_codes=("CONTEXT_BOUND_BILINGUAL_ALIAS",),
            idempotency_key=key,
        )

    with open_graphiti_path_entity_system(entity_state) as entities:
        mentions = {}
        for source, mention_id, language, key in (
            (
                entity_state.en_transit_source,
                en_transit_mention,
                "en-GB",
                "increment-4e-homonym-en-transit",
            ),
            (
                entity_state.en_association_source,
                en_association_mention,
                "en-GB",
                "increment-4e-homonym-en-association",
            ),
            (
                entity_state.zh_transit_source,
                zh_transit_mention,
                "zh-HK",
                "increment-4e-homonym-zh-transit",
            ),
            (
                entity_state.zh_association_source,
                zh_association_mention,
                "zh-HK",
                "increment-4e-homonym-zh-association",
            ),
        ):
            mentions[mention_id] = entities.entities.admit_mention(
                mention_request(
                    source,
                    mention_id=mention_id,
                    language=language,
                    entity_kind=EntityKind.PERSON,
                    key=key,
                ),
                proof=extraction_proof(),
            )

        assert (
            mentions[en_transit_mention].normalized_text
            == mentions[en_association_mention].normalized_text
        )
        assert (
            mentions[zh_transit_mention].normalized_text
            == mentions[zh_association_mention].normalized_text
        )
        assert (
            mentions[en_transit_mention].start_byte,
            mentions[en_transit_mention].end_byte,
        ) != (
            mentions[en_association_mention].start_byte,
            mentions[en_association_mention].end_byte,
        )

        with pytest.raises(EntityStateError, match="exact mentions"):
            entities.entities.propose_resolution(
                equivalence_request(
                    entity_state.equivalence_association_source,
                    subject_mention_id=zh_transit_mention,
                    object_mention_id=en_association_mention,
                    proposal_id=crossed_equivalence_id,
                    proposal_version_id=crossed_equivalence_version_id,
                    key="increment-4e-crossed-homonym-equivalence",
                ),
                proof=extraction_proof(),
            )

        transit_proposal = entities.entities.propose_resolution(
            new_entity_request(
                entity_state.en_transit_source,
                mention_id=en_transit_mention,
                proposal_id=transit_proposal_id,
                proposal_version_id=transit_proposal_version_id,
                key="increment-4e-transit-new-entity",
            ),
            proof=extraction_proof(),
        )
        association_proposal = entities.entities.propose_resolution(
            new_entity_request(
                entity_state.en_association_source,
                mention_id=en_association_mention,
                proposal_id=association_proposal_id,
                proposal_version_id=association_proposal_version_id,
                key="increment-4e-association-new-entity",
            ),
            proof=extraction_proof(),
        )
        for proposal, entity_id, version_id, alias_id, key in (
            (
                transit_proposal,
                transit_entity_id,
                transit_version_id,
                transit_en_alias_id,
                "increment-4e-transit-accept",
            ),
            (
                association_proposal,
                association_entity_id,
                association_version_id,
                association_en_alias_id,
                "increment-4e-association-accept",
            ),
        ):
            entities.entities.decide_resolution(
                decision_request(
                    proposal,
                    action=EntityResolutionDecisionAction.ACCEPT,
                    entity_id=entity_id,
                    version_id=version_id,
                    alias_id=alias_id,
                    alias_kind=EntityAliasKind.PRIMARY_NAME,
                    key=key,
                ),
                proof=extraction_proof(),
            )

        for source, subject, object_, proposal_id, version_id, entity_id, entity_version_id, alias_id, key in (
            (
                entity_state.equivalence_transit_source,
                zh_transit_mention,
                en_transit_mention,
                transit_equivalence_id,
                transit_equivalence_version_id,
                transit_entity_id,
                transit_version_id,
                transit_zh_alias_id,
                "increment-4e-transit-equivalence",
            ),
            (
                entity_state.equivalence_association_source,
                zh_association_mention,
                en_association_mention,
                association_equivalence_id,
                association_equivalence_version_id,
                association_entity_id,
                association_version_id,
                association_zh_alias_id,
                "increment-4e-association-equivalence",
            ),
        ):
            proposal = entities.entities.propose_resolution(
                equivalence_request(
                    source,
                    subject_mention_id=subject,
                    object_mention_id=object_,
                    proposal_id=proposal_id,
                    proposal_version_id=version_id,
                    key=f"{key}-proposal",
                ),
                proof=extraction_proof(),
            )
            entities.entities.decide_resolution(
                decision_request(
                    proposal,
                    action=EntityResolutionDecisionAction.ACCEPT,
                    entity_id=entity_id,
                    version_id=entity_version_id,
                    alias_id=alias_id,
                    alias_kind=EntityAliasKind.TRANSLATION,
                    key=f"{key}-accept",
                ),
                proof=extraction_proof(),
            )

        transit_aliases = entities.entities.aliases(
            transit_entity_id,
            limit=10,
            proof=extraction_proof(),
        )
        association_aliases = entities.entities.aliases(
            association_entity_id,
            limit=10,
            proof=extraction_proof(),
        )

    assert transit_entity_id != association_entity_id
    assert {alias.language for alias in transit_aliases} == {"en-GB", "zh-HK"}
    assert {alias.language for alias in association_aliases} == {
        "en-GB",
        "zh-HK",
    }
    assert {alias.entity_id for alias in transit_aliases} == {transit_entity_id}
    assert {alias.entity_id for alias in association_aliases} == {
        association_entity_id
    }
    assert not state.workspace_root.exists() or not any(
        state.workspace_root.iterdir()
    )


def test_unresolved_graphiti_identity_holds_relation_then_later_admits_without_rewrite(
    tmp_path: Path,
) -> None:
    state = seed_increment4_graphiti_path(tmp_path, resolve_secondary=False)
    commands, schemas = graphiti_path_registries(state.extraction)
    with open_governed_source_registry_authority_system(
        path=state.extraction.database,
        registry=commands,
        payload_schemas=schemas,
        authenticator=source_authenticator(),
        authorizer=source_authorizer(),
        read_policy=source_read_policy(),
        clock=lambda: SOURCE_NOW,
    ) as sources:
        sources.sources.record_revision(
            revision_request(
                revision_id=REVISION_2_ID,
                prior_revision_id=REVISION_1_ID,
                state_character="e",
                key="increment-4e-graphiti-second-revision-v1",
            ),
            proof=source_proof(),
        )

    predicate = EditorialPredicateCode.DEVELOPMENT_OF
    contract = EDITORIAL_PREDICATE_REGISTRY_V1.contract(predicate)
    request = replace(
        relation_proposal_request(
            state.relation,
            dependency_ids=(ZH_RELATION_DEPENDENCY_ID,),
        ),
        predicate=predicate,
        predicate_contract_digest=contract.digest,
        subject=SourceRevisionRelationEndpoint(
            source_item_id=ITEM_ID,
            source_revision_id=REVISION_1_ID,
        ),
        object=SourceRevisionRelationEndpoint(
            source_item_id=ITEM_ID,
            source_revision_id=REVISION_2_ID,
        ),
        temporal_scope=EditorialRelationTemporalScope(
            valid_from=SOURCE_NOW,
            valid_until=UtcTimestamp.parse("2042-03-13T10:00:00.000000Z"),
            observed_at=SOURCE_NOW,
        ),
        statement=(
            "The later retained source revision develops the earlier retained "
            "revision while identity review remains explicit."
        ),
        idempotency_key="increment-4e-graphiti-held-proposal-v1",
    )

    with open_graphiti_path_relation_system(state.relation) as relations:
        proposal = relations.relations.propose(
            request,
            proof=extraction_proof(),
        )
        with pytest.raises(
            EditorialRelationDecisionConflict,
            match="material entity identity",
        ):
            relations.relations.decide(
                relation_decision_request(
                    proposal,
                    action=EditorialRelationDecisionAction.ACCEPT,
                    decision_id=RELATION_ACCEPT_DECISION_ID,
                    assertion_id=RELATION_ASSERTION_ID,
                    key="increment-4e-graphiti-premature-accept-v1",
                ),
                proof=extraction_proof(),
            )
        held = relations.relations.decide(
            relation_decision_request(
                proposal,
                action=EditorialRelationDecisionAction.HOLD,
                decision_id=RELATION_HOLD_DECISION_ID,
                key="increment-4e-graphiti-hold-v1",
            ),
            proof=extraction_proof(),
        )
        assert held.current_state.value == "HELD"
        assert held.decision_version == 1
        assert relations.relations.current_relations(
            limit=10,
            proof=extraction_proof(),
        ) == ()

    with open_graphiti_path_entity_system(state.relation.entity) as entities:
        accepted = entities.entities.decide_resolution(
            entity_decision_request(
                state.relation.zh_resolution_proposal,
                action=EntityResolutionDecisionAction.ACCEPT,
                entity_id=ZH_ENTITY_ID,
                version_id=ZH_ENTITY_VERSION_ID,
                alias_id=ZH_PRIMARY_ALIAS_ID,
                alias_kind=EntityAliasKind.PRIMARY_NAME,
                key="increment-4e-graphiti-later-identity-accept-v1",
            ),
            proof=extraction_proof(),
        )
        assert accepted.current_state.value == "ACCEPTED"

    with open_graphiti_path_relation_system(state.relation) as relations:
        admitted = relations.relations.decide(
            relation_decision_request(
                proposal,
                action=EditorialRelationDecisionAction.ACCEPT,
                decision_id=RELATION_SECOND_DECISION_ID,
                expected_previous_version=1,
                previous_decision_id=RELATION_HOLD_DECISION_ID,
                assertion_id=RELATION_ASSERTION_ID,
                key="increment-4e-graphiti-later-admit-v1",
            ),
            proof=extraction_proof(),
        )
        current = relations.relations.current(
            RELATION_ASSERTION_ID,
            proof=extraction_proof(),
        )

    assert admitted.current_state.value == "ADMITTED"
    assert admitted.decision_version == 2
    assert current.assertion.admission_decision_id == RELATION_SECOND_DECISION_ID
    with closing(sqlite3.connect(state.extraction.database)) as conn:
        assert conn.execute(
            "SELECT action,decision_version FROM editorial_relation_decisions "
            "WHERE proposal_id=? ORDER BY decision_version",
            (str(proposal.proposal_id),),
        ).fetchall() == [("HOLD", 1), ("ACCEPT", 2)]
    assert state.replay_attempt.run_version_id == (
        state.relation.entity.relation_source.run_version_id
    )
    assert not state.workspace_root.exists() or not any(
        state.workspace_root.iterdir()
    )



def test_correction_and_supersession_project_current_state_with_predecessor_lineage(
    tmp_path: Path,
) -> None:
    from newsroom.projection import ProjectionNodeType
    from newsroom.projection.mapping import canonical_governed_node_id
    from newsroom.relations import (
        EditorialRelationAssertionId,
        EditorialRelationDecisionId,
        EditorialRelationProposalId,
        EditorialRelationProposalVersionId,
        RelationAssertionRelationEndpoint,
    )

    from .editorial_relation_4c_helpers import (
        RELATION_SECOND_ACCEPT_DECISION_ID,
        RELATION_SECOND_ASSERTION_ID,
        RELATION_SECOND_PROPOSAL_ID,
        RELATION_SECOND_PROPOSAL_V1_ID,
        RELATION_SUPERSEDE_DECISION_ID,
        RELATION_SUPERSESSION_ID,
    )
    from .increment4e_governed_path_helpers import (
        admit_increment4_graphiti_path,
        graphiti_path_current_snapshot,
    )

    def relation_id(identifier_type, suffix: int):
        return identifier_type.parse(
            f"00000000-0000-4000-8000-{suffix:012d}"
        )

    correction_proposal_id = relation_id(EditorialRelationProposalId, 4981)
    correction_proposal_version_id = relation_id(
        EditorialRelationProposalVersionId, 4982
    )
    correction_assertion_id = relation_id(EditorialRelationAssertionId, 4983)
    correction_decision_id = relation_id(EditorialRelationDecisionId, 4984)

    state = seed_increment4_graphiti_path(tmp_path)
    admitted = admit_increment4_graphiti_path(state)
    adapter = MemoryNeo4jAdapter()
    first_generation_id = ProjectionGenerationId.parse(
        "00000000-0000-4000-8000-000000004982"
    )
    correction_generation_id = ProjectionGenerationId.parse(
        "00000000-0000-4000-8000-000000004983"
    )
    final_generation_id = ProjectionGenerationId.parse(
        "00000000-0000-4000-8000-000000004984"
    )

    with open_graphiti_path_increment4_neo4j_system(
        state.relation,
        adapter,
    ) as projection:
        first = projection.increment4.build_and_promote(
            Increment4Neo4jBuildRequest(
                generation_id=first_generation_id,
                snapshot=admitted.snapshot,
                reason_code="INCREMENT4_GRAPHITI_PREDECESSOR_PROOF",
                idempotency_key="increment-4e-graphiti-predecessor-generation-v1",
            ),
            proof=extraction_proof(),
        )

    with open_graphiti_path_relation_system(state.relation) as relations:
        second_request = replace(
            relation_proposal_request(state.relation),
            proposal_id=RELATION_SECOND_PROPOSAL_ID,
            proposal_version_id=RELATION_SECOND_PROPOSAL_V1_ID,
            temporal_scope=EditorialRelationTemporalScope(
                valid_from=SOURCE_NOW,
                valid_until=None,
                observed_at=SOURCE_NOW,
            ),
            statement=(
                "A later admitted relation interval succeeds the original "
                "same-process assertion."
            ),
            idempotency_key="increment-4e-graphiti-successor-proposal-v1",
        )
        second_proposal = relations.relations.propose(
            second_request,
            proof=extraction_proof(),
        )
        relations.relations.decide(
            relation_decision_request(
                second_proposal,
                action=EditorialRelationDecisionAction.ACCEPT,
                decision_id=RELATION_SECOND_ACCEPT_DECISION_ID,
                assertion_id=RELATION_SECOND_ASSERTION_ID,
                key="increment-4e-graphiti-successor-accept-v1",
            ),
            proof=extraction_proof(),
        )
        correction_predicate = EditorialPredicateCode.CORRECTS
        correction_contract = EDITORIAL_PREDICATE_REGISTRY_V1.contract(
            correction_predicate
        )
        correction_request = replace(
            relation_proposal_request(state.relation),
            proposal_id=correction_proposal_id,
            proposal_version_id=correction_proposal_version_id,
            predicate=correction_predicate,
            predicate_contract_digest=correction_contract.digest,
            subject=RelationAssertionRelationEndpoint(
                assertion_id=RELATION_ASSERTION_ID
            ),
            object=RelationAssertionRelationEndpoint(
                assertion_id=RELATION_SECOND_ASSERTION_ID
            ),
            resolution_dependency_ids=(),
            statement=(
                "The later admitted assertion corrects the retained "
                "predecessor assertion."
            ),
            idempotency_key="increment-4e-graphiti-correction-proposal-v1",
        )
        correction_proposal = relations.relations.propose(
            correction_request,
            proof=extraction_proof(),
        )
        correction_decision = relations.relations.decide(
            relation_decision_request(
                correction_proposal,
                action=EditorialRelationDecisionAction.ACCEPT,
                decision_id=correction_decision_id,
                assertion_id=correction_assertion_id,
                key="increment-4e-graphiti-correction-accept-v1",
            ),
            proof=extraction_proof(),
        )

    correction_snapshot = graphiti_path_current_snapshot(state.relation)
    assert {
        item.current.assertion.assertion_id
        for item in correction_snapshot.relations
    } == {
        RELATION_ASSERTION_ID,
        RELATION_SECOND_ASSERTION_ID,
        correction_assertion_id,
    }
    with open_graphiti_path_increment4_neo4j_system(
        state.relation,
        adapter,
    ) as projection:
        correction_generation = projection.increment4.build_and_promote(
            Increment4Neo4jBuildRequest(
                generation_id=correction_generation_id,
                snapshot=correction_snapshot,
                reason_code="INCREMENT4_GRAPHITI_CORRECTION_PROOF",
                idempotency_key="increment-4e-graphiti-correction-generation-v1",
            ),
            proof=extraction_proof(),
        )
    correction_batches = tuple(
        batch
        for (generation, _sequence), batch in adapter.deliveries.items()
        if generation == str(correction_generation_id)
    )

    with open_graphiti_path_relation_system(state.relation) as relations:
        superseded = relations.relations.decide(
            relation_decision_request(
                admitted.proposal,
                action=EditorialRelationDecisionAction.SUPERSEDE,
                decision_id=RELATION_SUPERSEDE_DECISION_ID,
                expected_previous_version=admitted.decision.decision_version,
                previous_decision_id=admitted.decision.decision_id,
                target_assertion_id=RELATION_ASSERTION_ID,
                successor_assertion_id=RELATION_SECOND_ASSERTION_ID,
                supersession_id=RELATION_SUPERSESSION_ID,
                key="increment-4e-graphiti-predecessor-supersede-v2",
            ),
            proof=extraction_proof(),
        )
        current_ids = {
            item.assertion.assertion_id
            for item in relations.relations.current_relations(
                limit=100,
                proof=extraction_proof(),
            )
        }

    assert superseded.current_state.value == "SUPERSEDED"
    assert current_ids == {RELATION_SECOND_ASSERTION_ID, correction_assertion_id}
    final_snapshot = graphiti_path_current_snapshot(state.relation)
    with open_graphiti_path_increment4_neo4j_system(
        state.relation,
        adapter,
    ) as projection:
        final = projection.increment4.build_and_promote(
            Increment4Neo4jBuildRequest(
                generation_id=final_generation_id,
                snapshot=final_snapshot,
                reason_code="INCREMENT4_GRAPHITI_FINAL_CURRENT_PROOF",
                idempotency_key="increment-4e-graphiti-final-generation-v1",
            ),
            proof=extraction_proof(),
        )

    assert first.generation.state is ProjectionGenerationState.ACTIVE
    assert correction_generation.generation.state is ProjectionGenerationState.ACTIVE
    assert correction_generation.prior_generation is not None
    assert correction_generation.prior_generation.generation_id == first_generation_id
    assert final.generation.state is ProjectionGenerationState.ACTIVE
    assert final.prior_generation is not None
    assert final.prior_generation.generation_id == correction_generation_id

    correction_assertion_nodes = {
        node.canonical_id
        for batch in correction_batches
        for node in batch.nodes
        if node.identity_source == "EDITORIAL_RELATION_ASSERTION_ID"
    }
    expected_correction_nodes = {
        canonical_governed_node_id(
            ProjectionNodeType.AUTHORITY_VERSION,
            "editorial_relation_assertion_id",
            str(assertion_id),
        )
        for assertion_id in (
            RELATION_ASSERTION_ID,
            RELATION_SECOND_ASSERTION_ID,
            correction_assertion_id,
        )
    }
    assert expected_correction_nodes <= correction_assertion_nodes

    final_batches = tuple(
        batch
        for (generation, _sequence), batch in adapter.deliveries.items()
        if generation == str(final_generation_id)
    )
    final_assertion_nodes = {
        node.canonical_id
        for batch in final_batches
        for node in batch.nodes
        if node.identity_source == "EDITORIAL_RELATION_ASSERTION_ID"
    }
    assert expected_correction_nodes <= final_assertion_nodes
    assert not any(
        generation in {str(first_generation_id), str(correction_generation_id)}
        for generation, _sequence in adapter.deliveries
    )

    with closing(sqlite3.connect(state.extraction.database)) as conn:
        first_history = conn.execute(
            "SELECT action,decision_version FROM editorial_relation_decisions "
            "WHERE proposal_id=? ORDER BY decision_version",
            (str(admitted.proposal.proposal_id),),
        ).fetchall()
        correction_history = conn.execute(
            "SELECT action,decision_version FROM editorial_relation_decisions "
            "WHERE proposal_id=? ORDER BY decision_version",
            (str(correction_proposal_id),),
        ).fetchall()
    assert first_history == [("ACCEPT", 1), ("SUPERSEDE", 2)]
    assert correction_history == [("ACCEPT", 1)]


def test_revoked_graphiti_relation_is_absent_from_replacement_generation(
    tmp_path: Path,
) -> None:
    from .increment4e_governed_path_helpers import (
        admit_increment4_graphiti_path,
        graphiti_path_current_snapshot,
    )

    state = seed_increment4_graphiti_path(tmp_path)
    admitted = admit_increment4_graphiti_path(state)
    adapter = MemoryNeo4jAdapter()
    first_generation_id = ProjectionGenerationId.parse(
        "00000000-0000-4000-8000-000000004985"
    )
    replacement_generation_id = ProjectionGenerationId.parse(
        "00000000-0000-4000-8000-000000004986"
    )

    with open_graphiti_path_increment4_neo4j_system(
        state.relation,
        adapter,
    ) as projection:
        projection.increment4.build_and_promote(
            Increment4Neo4jBuildRequest(
                generation_id=first_generation_id,
                snapshot=admitted.snapshot,
                reason_code="INCREMENT4_GRAPHITI_REVOCATION_BASE",
                idempotency_key="increment-4e-graphiti-revocation-base-v1",
            ),
            proof=extraction_proof(),
        )

    with open_graphiti_path_relation_system(state.relation) as relations:
        revoked = relations.relations.decide(
            relation_decision_request(
                admitted.proposal,
                action=EditorialRelationDecisionAction.REVOKE,
                decision_id=RELATION_SECOND_DECISION_ID,
                expected_previous_version=admitted.decision.decision_version,
                previous_decision_id=admitted.decision.decision_id,
                target_assertion_id=RELATION_ASSERTION_ID,
                key="increment-4e-graphiti-revoke-v2",
            ),
            proof=extraction_proof(),
        )
        assert relations.relations.current_relations(
            limit=100,
            proof=extraction_proof(),
        ) == ()

    assert revoked.current_state.value == "REVOKED"
    replacement_snapshot = graphiti_path_current_snapshot(state.relation)
    assert replacement_snapshot.relations == ()
    with open_graphiti_path_increment4_neo4j_system(
        state.relation,
        adapter,
    ) as projection:
        replacement = projection.increment4.build_and_promote(
            Increment4Neo4jBuildRequest(
                generation_id=replacement_generation_id,
                snapshot=replacement_snapshot,
                reason_code="INCREMENT4_GRAPHITI_REVOCATION_REBUILD",
                idempotency_key="increment-4e-graphiti-revocation-rebuild-v1",
            ),
            proof=extraction_proof(),
        )

    assert replacement.generation.state is ProjectionGenerationState.ACTIVE
    assert replacement.prior_generation is not None
    assert replacement.prior_generation.generation_id == first_generation_id
    replacement_nodes = [
        node
        for (generation, _sequence), batch in adapter.deliveries.items()
        if generation == str(replacement_generation_id)
        for node in batch.nodes
    ]
    assert not any(
        node.identity_source == "EDITORIAL_RELATION_ASSERTION_ID"
        for node in replacement_nodes
    )
    assert not any(
        generation == str(first_generation_id)
        for generation, _sequence in adapter.deliveries
    )
    with closing(sqlite3.connect(state.extraction.database)) as conn:
        assert conn.execute(
            "SELECT action,decision_version FROM editorial_relation_decisions "
            "WHERE proposal_id=? ORDER BY decision_version",
            (str(admitted.proposal.proposal_id),),
        ).fetchall() == [("ACCEPT", 1), ("REVOKE", 2)]


def test_merge_and_reversal_preserve_assertion_endpoints_without_silent_retarget(
    tmp_path: Path,
) -> None:
    from newsroom.entities import (
        CanonicalEntityId,
        CanonicalEntityLifecycle,
        CanonicalEntityVersionId,
        EntityLineageVersion,
        EntityMergeDecisionId,
        EntityMergeDecisionRequest,
        EntityReversalDecisionId,
        EntityReversalDecisionRequest,
        EntityReversalTargetKind,
    )
    from newsroom.relations import EditorialRelationStaleDecision

    from .entity_4b_helpers import ENTITY_ID, ENTITY_VERSION_ID
    from .increment4e_governed_path_helpers import admit_increment4_graphiti_path

    def entity_id(identifier_type, suffix: int):
        return identifier_type.parse(
            f"00000000-0000-4000-8000-{suffix:012d}"
        )

    merge_decision_id = entity_id(EntityMergeDecisionId, 4991)
    successor_entity_id = entity_id(CanonicalEntityId, 4992)
    successor_version_id = entity_id(CanonicalEntityVersionId, 4993)
    reversal_decision_id = entity_id(EntityReversalDecisionId, 4994)
    restored_en_version_id = entity_id(CanonicalEntityVersionId, 4995)
    restored_zh_version_id = entity_id(CanonicalEntityVersionId, 4996)

    state = seed_increment4_graphiti_path(tmp_path)
    admitted = admit_increment4_graphiti_path(state)
    database = state.extraction.database
    with closing(sqlite3.connect(database)) as conn:
        original_assertion = conn.execute(
            "SELECT subject_endpoint_digest,object_endpoint_digest,canonical_bytes,"
            "canonical_digest FROM editorial_relation_assertions WHERE assertion_id=?",
            (str(RELATION_ASSERTION_ID),),
        ).fetchone()
    assert original_assertion is not None

    predecessors = tuple(
        sorted(
            (
                EntityLineageVersion(ENTITY_ID, ENTITY_VERSION_ID),
                EntityLineageVersion(ZH_ENTITY_ID, ZH_ENTITY_VERSION_ID),
            ),
            key=lambda item: str(item.entity_id),
        )
    )
    merge_request = EntityMergeDecisionRequest(
        merge_decision_id=merge_decision_id,
        predecessors=predecessors,
        successor_entity_id=successor_entity_id,
        successor_entity_version_id=successor_version_id,
        preferred_continuation_entity_id=ENTITY_ID,
        basis_resolution_proposal_ids=tuple(
            sorted(
                (
                    state.relation.en_resolution_proposal.proposal_id,
                    state.relation.zh_resolution_proposal.proposal_id,
                ),
                key=str,
            )
        ),
        reason_code="INCREMENT4_FALSE_MERGE_EXERCISE",
        decision_policy_version="entity-resolution-policy-v1",
        idempotency_key="increment-4e-graphiti-merge-v1",
    )

    with open_graphiti_path_entity_system(state.relation.entity) as entities:
        merged = entities.entities.merge_entities(
            merge_request,
            proof=extraction_proof(),
        )
        assert entities.entities.merge_decision(
            merge_decision_id,
            proof=extraction_proof(),
        ).canonical_digest == merged.canonical_digest

    with open_graphiti_path_relation_system(state.relation) as relations:
        with pytest.raises(
            EditorialRelationStaleDecision,
            match="entity version is no longer current",
        ):
            relations.relations.current(
                RELATION_ASSERTION_ID,
                proof=extraction_proof(),
            )

    expected_versions = tuple(
        sorted(
            (
                *(item.merged_entity_version_id for item in merged.predecessors),
                merged.successor_entity_version_id,
            ),
            key=str,
        )
    )
    reversal_request = EntityReversalDecisionRequest(
        reversal_decision_id=reversal_decision_id,
        target_kind=EntityReversalTargetKind.MERGE,
        target_decision_id=str(merge_decision_id),
        expected_current_entity_version_ids=expected_versions,
        restorations=tuple(
            sorted(
                (
                    EntityLineageVersion(ENTITY_ID, restored_en_version_id),
                    EntityLineageVersion(ZH_ENTITY_ID, restored_zh_version_id),
                ),
                key=lambda item: str(item.entity_id),
            )
        ),
        reason_code="INCREMENT4_FALSE_MERGE_REVERSAL",
        decision_policy_version="entity-resolution-policy-v1",
        idempotency_key="increment-4e-graphiti-merge-reversal-v1",
    )
    with open_graphiti_path_entity_system(state.relation.entity) as entities:
        reversal = entities.entities.reverse_lineage(
            reversal_request,
            proof=extraction_proof(),
        )
        replay = entities.entities.reverse_lineage(
            reversal_request,
            proof=extraction_proof(),
        )
        assert replay.replayed is True
        assert replay.canonical_digest == reversal.canonical_digest
        assert entities.entities.reversal_decision(
            reversal_decision_id,
            proof=extraction_proof(),
        ).canonical_digest == reversal.canonical_digest
        for entity_id_, restored_version_id in (
            (ENTITY_ID, restored_en_version_id),
            (ZH_ENTITY_ID, restored_zh_version_id),
        ):
            preferred = entities.entities.preferred(
                entity_id_,
                proof=extraction_proof(),
            )
            assert preferred.lifecycle is CanonicalEntityLifecycle.ACTIVE
            assert preferred.current_entity_version_id == restored_version_id
        successor = entities.entities.preferred(
            successor_entity_id,
            proof=extraction_proof(),
        )
        assert successor.lifecycle is CanonicalEntityLifecycle.REVERSED

    # Reversal restores the identities through new immutable versions. It must
    # not rewrite the previously admitted assertion from v1 to those new v2
    # versions; a new editorial decision is required instead.
    with open_graphiti_path_relation_system(state.relation) as relations:
        with pytest.raises(
            EditorialRelationStaleDecision,
            match="entity version is no longer current",
        ):
            relations.relations.current(
                RELATION_ASSERTION_ID,
                proof=extraction_proof(),
            )

    with closing(sqlite3.connect(database)) as conn:
        retained_decision = conn.execute(
            "SELECT decision_id,action,decision_version FROM "
            "editorial_relation_decisions WHERE proposal_id=? "
            "ORDER BY decision_version",
            (str(admitted.proposal.proposal_id),),
        ).fetchall()
        assert retained_decision == [
            (str(admitted.decision.decision_id), "ACCEPT", 1)
        ]
        after_reversal = conn.execute(
            "SELECT subject_endpoint_digest,object_endpoint_digest,canonical_bytes,"
            "canonical_digest FROM editorial_relation_assertions WHERE assertion_id=?",
            (str(RELATION_ASSERTION_ID),),
        ).fetchone()
    assert after_reversal == original_assertion
    assert not state.workspace_root.exists() or not any(
        state.workspace_root.iterdir()
    )


def test_graphiti_bilingual_entity_split_and_reversal_preserve_partition_history(
    tmp_path: Path,
) -> None:
    from newsroom.entities import (
        CanonicalEntityId,
        CanonicalEntityLifecycle,
        CanonicalEntityVersionId,
        EntityAliasKind,
        EntityLineageVersion,
        EntityResolutionDecisionAction,
        EntityResolutionProposalKind,
        EntityResolutionProposalRequest,
        EntityReversalDecisionId,
        EntityReversalDecisionRequest,
        EntityReversalTargetKind,
        EntitySplitAllocation,
        EntitySplitDecisionId,
        EntitySplitDecisionRequest,
    )

    from .entity_4b_helpers import (
        EN_MENTION_ID,
        ENTITY_ID,
        ENTITY_VERSION_ID,
        ZH_ALIAS_ID,
        ZH_EQ_PROPOSAL_ID,
        ZH_EQ_PROPOSAL_V1_ID,
        ZH_MENTION_ID,
        decision_request,
    )

    def entity_id(identifier_type, suffix: int):
        return identifier_type.parse(
            f"00000000-0000-4000-8000-{suffix:012d}"
        )

    split_decision_id = entity_id(EntitySplitDecisionId, 4971)
    successor_en_id = entity_id(CanonicalEntityId, 4972)
    successor_zh_id = entity_id(CanonicalEntityId, 4973)
    successor_en_version_id = entity_id(CanonicalEntityVersionId, 4974)
    successor_zh_version_id = entity_id(CanonicalEntityVersionId, 4975)
    reversal_decision_id = entity_id(EntityReversalDecisionId, 4976)
    restored_source_version_id = entity_id(CanonicalEntityVersionId, 4977)

    state = seed_increment4_graphiti_path(tmp_path, resolve_secondary=False)
    entity_state = state.relation.entity
    equivalence_request = EntityResolutionProposalRequest(
        proposal_id=ZH_EQ_PROPOSAL_ID,
        proposal_version_id=ZH_EQ_PROPOSAL_V1_ID,
        version_number=1,
        expected_previous_version_id=None,
        source_proposal_id=entity_state.equivalence_source.proposal_id,
        expected_source_proposal_digest=(
            entity_state.equivalence_source.canonical_digest
        ),
        kind=EntityResolutionProposalKind.MENTION_EQUIVALENCE,
        subject_mention_id=ZH_MENTION_ID,
        object_mention_id=EN_MENTION_ID,
        candidate_entity_id=None,
        candidate_entity_version_id=None,
        confidence_basis_points=8_500,
        uncertainty_codes=("REQUIRES_EXPLICIT_RESOLUTION",),
        basis_codes=("EXACT_BILINGUAL_EVIDENCE",),
        idempotency_key="increment-4e-graphiti-split-equivalence-v1",
    )

    with open_graphiti_path_entity_system(entity_state) as entities:
        equivalence = entities.entities.propose_resolution(
            equivalence_request,
            proof=extraction_proof(),
        )
        entities.entities.decide_resolution(
            decision_request(
                equivalence,
                action=EntityResolutionDecisionAction.ACCEPT,
                entity_id=ENTITY_ID,
                version_id=ENTITY_VERSION_ID,
                alias_id=ZH_ALIAS_ID,
                alias_kind=EntityAliasKind.TRANSLATION,
                key="increment-4e-graphiti-split-equivalence-accept-v1",
            ),
            proof=extraction_proof(),
        )
        split_request = EntitySplitDecisionRequest(
            split_decision_id=split_decision_id,
            source_entity_id=ENTITY_ID,
            expected_source_version_id=ENTITY_VERSION_ID,
            successors=tuple(
                sorted(
                    (
                        EntityLineageVersion(
                            successor_en_id,
                            successor_en_version_id,
                        ),
                        EntityLineageVersion(
                            successor_zh_id,
                            successor_zh_version_id,
                        ),
                    ),
                    key=lambda item: str(item.entity_id),
                )
            ),
            allocations=tuple(
                sorted(
                    (
                        EntitySplitAllocation(EN_MENTION_ID, successor_en_id),
                        EntitySplitAllocation(ZH_MENTION_ID, successor_zh_id),
                    ),
                    key=lambda item: (
                        str(item.mention_id),
                        str(item.successor_entity_id),
                    ),
                )
            ),
            reason_code="INCREMENT4_BILINGUAL_FALSE_MERGE_SPLIT",
            decision_policy_version="entity-resolution-policy-v1",
            idempotency_key="increment-4e-graphiti-split-v1",
        )
        split = entities.entities.split_entity(
            split_request,
            proof=extraction_proof(),
        )
        split_replay = entities.entities.split_entity(
            split_request,
            proof=extraction_proof(),
        )
        assert split_replay.replayed is True
        assert split_replay.canonical_digest == split.canonical_digest
        assert {
            item.mention_id: item.successor_entity_id
            for item in split.allocations
        } == {
            EN_MENTION_ID: successor_en_id,
            ZH_MENTION_ID: successor_zh_id,
        }
        assert entities.entities.preferred(
            ENTITY_ID,
            proof=extraction_proof(),
        ).lifecycle is CanonicalEntityLifecycle.SPLIT
        for successor_id, version_id in (
            (successor_en_id, successor_en_version_id),
            (successor_zh_id, successor_zh_version_id),
        ):
            preferred = entities.entities.preferred(
                successor_id,
                proof=extraction_proof(),
            )
            assert preferred.lifecycle is CanonicalEntityLifecycle.ACTIVE
            assert preferred.current_entity_version_id == version_id

        expected_versions = tuple(
            sorted(
                (
                    split.source_split_version_id,
                    *(item.entity_version_id for item in split.successors),
                ),
                key=str,
            )
        )
        reversal_request = EntityReversalDecisionRequest(
            reversal_decision_id=reversal_decision_id,
            target_kind=EntityReversalTargetKind.SPLIT,
            target_decision_id=str(split_decision_id),
            expected_current_entity_version_ids=expected_versions,
            restorations=(
                EntityLineageVersion(
                    ENTITY_ID,
                    restored_source_version_id,
                ),
            ),
            reason_code="INCREMENT4_BILINGUAL_SPLIT_REVERSAL",
            decision_policy_version="entity-resolution-policy-v1",
            idempotency_key="increment-4e-graphiti-split-reversal-v1",
        )
        reversal = entities.entities.reverse_lineage(
            reversal_request,
            proof=extraction_proof(),
        )
        reversal_replay = entities.entities.reverse_lineage(
            reversal_request,
            proof=extraction_proof(),
        )
        assert reversal_replay.replayed is True
        assert reversal_replay.canonical_digest == reversal.canonical_digest
        restored = entities.entities.preferred(
            ENTITY_ID,
            proof=extraction_proof(),
        )
        assert restored.lifecycle is CanonicalEntityLifecycle.ACTIVE
        assert restored.current_entity_version_id == restored_source_version_id
        assert len(reversal.supersessions) == 2
        for superseded in reversal.supersessions:
            preferred = entities.entities.preferred(
                superseded.entity_id,
                proof=extraction_proof(),
            )
            assert preferred.lifecycle is CanonicalEntityLifecycle.REVERSED
            assert preferred.preferred_entity_id == ENTITY_ID

    with closing(sqlite3.connect(state.extraction.database)) as conn:
        split_history = conn.execute(
            "SELECT split_decision_id,source_entity_id,source_split_version_id "
            "FROM entity_split_decisions WHERE split_decision_id=?",
            (str(split_decision_id),),
        ).fetchone()
        reversal_history = conn.execute(
            "SELECT reversal_decision_id,target_kind,target_decision_id "
            "FROM entity_reversal_decisions WHERE reversal_decision_id=?",
            (str(reversal_decision_id),),
        ).fetchone()
    assert split_history == (
        str(split_decision_id),
        str(ENTITY_ID),
        str(split.source_split_version_id),
    )
    assert reversal_history == (
        str(reversal_decision_id),
        "SPLIT",
        str(split_decision_id),
    )

    # Rebuild the admitted graph from the restored current authority. Aliases
    # remain bound to their immutable pre-split version, so the mapper retains
    # that historical version as lineage rather than silently moving aliases to
    # the restored version.
    from newsroom.increment4 import sorted_snapshot
    from .increment4e_helpers import _entity_state, _ledger_events

    with open_graphiti_path_entity_system(entity_state) as entities:
        restored_entity_state = _entity_state(
            entities,
            ENTITY_ID,
            restored_source_version_id,
        )
    events = _ledger_events(state.extraction.database)
    restored_snapshot = sorted_snapshot(
        entities=(restored_entity_state,),
        relations=(),
        events=events,
        through_ledger_seq=events[-1].ledger_seq,
    )
    restored_generation_id = ProjectionGenerationId.parse(
        "00000000-0000-4000-8000-000000004978"
    )
    adapter = MemoryNeo4jAdapter()
    with open_graphiti_path_increment4_neo4j_system(
        state.relation,
        adapter,
    ) as projection:
        rebuilt = projection.increment4.build_and_promote(
            Increment4Neo4jBuildRequest(
                generation_id=restored_generation_id,
                snapshot=restored_snapshot,
                reason_code="INCREMENT4_SPLIT_REVERSAL_REBUILD",
                idempotency_key="increment-4e-split-reversal-rebuild-v1",
            ),
            proof=extraction_proof(),
        )
    assert rebuilt.generation.state is ProjectionGenerationState.ACTIVE
    restored_nodes = [
        node
        for (generation, _sequence), batch in adapter.deliveries.items()
        if generation == str(restored_generation_id)
        for node in batch.nodes
    ]
    entity_version_references = {
        node.canonical_id
        for node in restored_nodes
        if node.identity_source == "CANONICAL_ENTITY_VERSION_ID"
    }
    from newsroom.projection import ProjectionNodeType
    from newsroom.projection.mapping import canonical_governed_node_id

    assert entity_version_references == {
        canonical_governed_node_id(
            ProjectionNodeType.AUTHORITY_VERSION,
            "canonical_entity_version_id",
            str(ENTITY_VERSION_ID),
        ),
        canonical_governed_node_id(
            ProjectionNodeType.AUTHORITY_VERSION,
            "canonical_entity_version_id",
            str(restored_source_version_id),
        ),
    }
    assert len(
        [
            node
            for node in restored_nodes
            if node.identity_source == "ENTITY_ALIAS_ID"
        ]
    ) == 2
    assert not any(
        node.identity_reference_digest
        in {str(successor_en_id), str(successor_zh_id)}
        for node in restored_nodes
    )
    assert not state.workspace_root.exists() or not any(
        state.workspace_root.iterdir()
    )


def test_graphiti_entity_merge_and_reversal_rebuild_exact_lineage(
    tmp_path: Path,
) -> None:
    from newsroom.entities import (
        CanonicalEntityId,
        CanonicalEntityVersionId,
        EntityLineageVersion,
        EntityMergeDecisionId,
        EntityMergeDecisionRequest,
        EntityReversalDecisionId,
        EntityReversalDecisionRequest,
        EntityReversalTargetKind,
    )
    from newsroom.projection import ProjectionRelationType

    from .entity_4b_helpers import ENTITY_ID, ENTITY_VERSION_ID
    from .increment4e_helpers import _entity_state, _ledger_events

    def entity_id(identifier_type, suffix: int):
        return identifier_type.parse(
            f"00000000-0000-4000-8000-{suffix:012d}"
        )

    merge_decision_id = entity_id(EntityMergeDecisionId, 5681)
    successor_entity_id = entity_id(CanonicalEntityId, 5682)
    successor_version_id = entity_id(CanonicalEntityVersionId, 5683)
    reversal_decision_id = entity_id(EntityReversalDecisionId, 5684)
    restored_en_version_id = entity_id(CanonicalEntityVersionId, 5685)
    restored_zh_version_id = entity_id(CanonicalEntityVersionId, 5686)

    state = seed_increment4_graphiti_path(tmp_path)
    predecessors = tuple(
        sorted(
            (
                EntityLineageVersion(ENTITY_ID, ENTITY_VERSION_ID),
                EntityLineageVersion(ZH_ENTITY_ID, ZH_ENTITY_VERSION_ID),
            ),
            key=lambda item: str(item.entity_id),
        )
    )
    merge_request = EntityMergeDecisionRequest(
        merge_decision_id=merge_decision_id,
        predecessors=predecessors,
        successor_entity_id=successor_entity_id,
        successor_entity_version_id=successor_version_id,
        preferred_continuation_entity_id=ENTITY_ID,
        basis_resolution_proposal_ids=tuple(
            sorted(
                (
                    state.relation.en_resolution_proposal.proposal_id,
                    state.relation.zh_resolution_proposal.proposal_id,
                ),
                key=str,
            )
        ),
        reason_code="INCREMENT4_GRAPHITI_EDITORIAL_MERGE",
        decision_policy_version="entity-resolution-policy-v1",
        idempotency_key="increment-4e-graphiti-merge-v1",
    )

    with open_graphiti_path_entity_system(state.relation.entity) as entities:
        merged = entities.entities.merge_entities(
            merge_request,
            proof=extraction_proof(),
        )
        merge_replay = entities.entities.merge_entities(
            merge_request,
            proof=extraction_proof(),
        )
        merged_versions = {
            item.entity_id: item.merged_entity_version_id
            for item in merged.predecessors
        }
        merged_entity_states = (
            _entity_state(entities, ENTITY_ID, merged_versions[ENTITY_ID]),
            _entity_state(
                entities,
                ZH_ENTITY_ID,
                merged_versions[ZH_ENTITY_ID],
            ),
            _entity_state(
                entities,
                successor_entity_id,
                successor_version_id,
            ),
        )

    assert merge_replay.replayed is True
    merge_events = _ledger_events(state.extraction.database)
    merge_snapshot = sorted_snapshot(
        entities=merged_entity_states,
        relations=(),
        events=merge_events,
        through_ledger_seq=merge_events[-1].ledger_seq,
    )
    adapter = MemoryNeo4jAdapter()
    merge_generation_id = ProjectionGenerationId.parse(
        "00000000-0000-4000-8000-000000004987"
    )
    reversal_generation_id = ProjectionGenerationId.parse(
        "00000000-0000-4000-8000-000000004988"
    )
    with open_graphiti_path_increment4_neo4j_system(
        state.relation,
        adapter,
    ) as projection:
        merged_generation = projection.increment4.build_and_promote(
            Increment4Neo4jBuildRequest(
                generation_id=merge_generation_id,
                snapshot=merge_snapshot,
                reason_code="INCREMENT4_GRAPHITI_MERGE_LINEAGE",
                idempotency_key="increment-4e-graphiti-merge-generation-v1",
            ),
            proof=extraction_proof(),
        )
    merge_batches = tuple(
        batch
        for (generation, _sequence), batch in adapter.deliveries.items()
        if generation == str(merge_generation_id)
    )
    merge_nodes = [node for batch in merge_batches for node in batch.nodes]
    merge_relations = [
        relation for batch in merge_batches for relation in batch.relations
    ]
    assert len(
        {
            node.canonical_id
            for node in merge_nodes
            if node.identity_source == "CANONICAL_ENTITY_ID"
        }
    ) == 3
    assert len(
        {
            node.canonical_id
            for node in merge_nodes
            if node.identity_source == "ENTITY_ALIAS_ID"
        }
    ) == 2
    assert len(
        {
            node.canonical_id
            for node in merge_nodes
            if node.identity_source == "CANONICAL_ENTITY_VERSION_ID"
        }
    ) == 5
    assert len(
        [
            relation
            for relation in merge_relations
            if relation.relation_type is ProjectionRelationType.DERIVED_FROM
        ]
    ) == 2

    expected_versions = tuple(
        sorted(
            (
                *(item.merged_entity_version_id for item in merged.predecessors),
                merged.successor_entity_version_id,
            ),
            key=str,
        )
    )
    reversal_request = EntityReversalDecisionRequest(
        reversal_decision_id=reversal_decision_id,
        target_kind=EntityReversalTargetKind.MERGE,
        target_decision_id=str(merge_decision_id),
        expected_current_entity_version_ids=expected_versions,
        restorations=tuple(
            sorted(
                (
                    EntityLineageVersion(ENTITY_ID, restored_en_version_id),
                    EntityLineageVersion(
                        ZH_ENTITY_ID,
                        restored_zh_version_id,
                    ),
                ),
                key=lambda item: str(item.entity_id),
            )
        ),
        reason_code="INCREMENT4_GRAPHITI_MERGE_REVERSAL",
        decision_policy_version="entity-resolution-policy-v1",
        idempotency_key="increment-4e-graphiti-merge-reversal-v1",
    )
    with open_graphiti_path_entity_system(state.relation.entity) as entities:
        reversal = entities.entities.reverse_lineage(
            reversal_request,
            proof=extraction_proof(),
        )
        reversal_replay = entities.entities.reverse_lineage(
            reversal_request,
            proof=extraction_proof(),
        )
        assert len(reversal.supersessions) == 1
        superseded_version_id = reversal.supersessions[0].entity_version_id
        reversed_entity_states = (
            _entity_state(entities, ENTITY_ID, restored_en_version_id),
            _entity_state(
                entities,
                ZH_ENTITY_ID,
                restored_zh_version_id,
            ),
            _entity_state(
                entities,
                successor_entity_id,
                superseded_version_id,
            ),
        )

    assert reversal_replay.replayed is True
    reversal_events = _ledger_events(state.extraction.database)
    reversal_snapshot = sorted_snapshot(
        entities=reversed_entity_states,
        relations=(),
        events=reversal_events,
        through_ledger_seq=reversal_events[-1].ledger_seq,
    )
    with open_graphiti_path_increment4_neo4j_system(
        state.relation,
        adapter,
    ) as projection:
        reversed_generation = projection.increment4.build_and_promote(
            Increment4Neo4jBuildRequest(
                generation_id=reversal_generation_id,
                snapshot=reversal_snapshot,
                reason_code="INCREMENT4_GRAPHITI_REVERSAL_LINEAGE",
                idempotency_key="increment-4e-graphiti-reversal-generation-v1",
            ),
            proof=extraction_proof(),
        )

    assert merged_generation.generation.state is ProjectionGenerationState.ACTIVE
    assert reversed_generation.generation.state is ProjectionGenerationState.ACTIVE
    assert reversed_generation.prior_generation is not None
    assert reversed_generation.prior_generation.generation_id == merge_generation_id
    assert not any(
        generation == str(merge_generation_id)
        for generation, _sequence in adapter.deliveries
    )
    reversal_batches = tuple(
        batch
        for (generation, _sequence), batch in adapter.deliveries.items()
        if generation == str(reversal_generation_id)
    )
    reversal_nodes = [
        node for batch in reversal_batches for node in batch.nodes
    ]
    reversal_relations = [
        relation for batch in reversal_batches for relation in batch.relations
    ]
    assert len(
        {
            node.canonical_id
            for node in reversal_nodes
            if node.identity_source == "CANONICAL_ENTITY_ID"
        }
    ) == 3
    assert len(
        {
            node.canonical_id
            for node in reversal_nodes
            if node.identity_source == "ENTITY_ALIAS_ID"
        }
    ) == 2
    assert len(
        [
            relation
            for relation in reversal_relations
            if relation.relation_type is ProjectionRelationType.DERIVED_FROM
        ]
    ) == 1
    with closing(sqlite3.connect(state.extraction.database)) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM entity_merge_decisions WHERE merge_decision_id=?",
            (str(merge_decision_id),),
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM entity_reversal_decisions "
            "WHERE reversal_decision_id=?",
            (str(reversal_decision_id),),
        ).fetchone()[0] == 1


def test_tombstoned_graphiti_source_purges_derivatives_and_cannot_resurrect(
    tmp_path: Path,
) -> None:
    from newsroom.entities import EntityRightsDenied
    from newsroom.increment4 import (
        Increment4Neo4jActiveReadRequest,
        sorted_snapshot,
    )
    from newsroom.relations import EditorialRelationRightsDenied

    from .authority_a2b_helpers import open_object_system
    from .authority_helpers import proof as object_proof
    from .entity_4b_helpers import ENTITY_ID
    from .increment4e_governed_path_helpers import admit_increment4_graphiti_path
    from .increment4e_helpers import _ledger_events

    state = seed_increment4_graphiti_path(tmp_path)
    admitted = admit_increment4_graphiti_path(state)
    first_generation_id = ProjectionGenerationId.parse(
        "00000000-0000-4000-8000-000000004985"
    )
    purge_generation_id = ProjectionGenerationId.parse(
        "00000000-0000-4000-8000-000000004986"
    )
    adapter = MemoryNeo4jAdapter()
    with open_graphiti_path_increment4_neo4j_system(
        state.relation,
        adapter,
    ) as projection:
        initial = projection.increment4.build_and_promote(
            Increment4Neo4jBuildRequest(
                generation_id=first_generation_id,
                snapshot=admitted.snapshot,
                reason_code="INCREMENT4_TOMBSTONE_BASE",
                idempotency_key="increment-4e-tombstone-base-v1",
            ),
            proof=extraction_proof(),
        )
    assert initial.generation.state is ProjectionGenerationState.ACTIVE
    original_canonical_ids = tuple(
        sorted(
            {
                node.canonical_id
                for (generation, _sequence), batch in adapter.deliveries.items()
                if generation == str(first_generation_id)
                for node in batch.nodes
            }
        )
    )
    assert original_canonical_ids

    commands, schemas = graphiti_path_registries(state.extraction)
    passage = state.extraction.input_binding.passages[0]
    with open_object_system(
        state.extraction.database,
        object_root=state.extraction.object_root,
        clock=lambda: SOURCE_NOW,
        command_registry=commands,
        payload_schema_registry=schemas,
    ) as objects:
        deletion = objects.objects.request_deletion(
            passage.blob_digest,
            reason_code="INCREMENT4_SOURCE_DELETE_REQUESTED",
            idempotency_key="increment-4e-source-delete-v1",
            proof=object_proof(),
        )
        tombstone = objects.objects.tombstone(
            deletion.deletion_id,
            reason_code="INCREMENT4_SOURCE_TOMBSTONED",
            idempotency_key="increment-4e-source-tombstone-v1",
            proof=object_proof(),
        )
    assert tombstone.deletion_id == deletion.deletion_id

    with open_graphiti_path_entity_system(state.relation.entity) as entities:
        with pytest.raises(EntityRightsDenied):
            entities.entities.preferred(
                ENTITY_ID,
                proof=extraction_proof(),
            )
    with open_graphiti_path_relation_system(state.relation) as relations:
        with pytest.raises(EditorialRelationRightsDenied):
            relations.relations.current_relations(
                limit=100,
                proof=extraction_proof(),
            )

    # Current admitted authority is now empty. Immutable ledger history remains
    # sufficient to advance an empty replacement generation through the exact
    # tombstone watermark and physically purge the retired graph.
    events = _ledger_events(state.extraction.database)
    empty_snapshot = sorted_snapshot(
        entities=(),
        relations=(),
        events=events,
        through_ledger_seq=events[-1].ledger_seq,
    )
    request = Increment4Neo4jBuildRequest(
        generation_id=purge_generation_id,
        snapshot=empty_snapshot,
        reason_code="INCREMENT4_TOMBSTONE_PURGE",
        idempotency_key="increment-4e-tombstone-purge-v1",
    )
    with open_graphiti_path_increment4_neo4j_system(
        state.relation,
        adapter,
    ) as projection:
        purged = projection.increment4.build_and_promote(
            request,
            proof=extraction_proof(),
        )
        read = projection.increment4.read_active(
            Increment4Neo4jActiveReadRequest(
                canonical_ids=original_canonical_ids,
                query_valid_time=SOURCE_NOW,
                limit=100,
            ),
            proof=extraction_proof(),
        )
        replay = projection.increment4.build_and_promote(
            request,
            proof=extraction_proof(),
        )

    assert purged.generation.state is ProjectionGenerationState.ACTIVE
    assert purged.prior_generation is not None
    assert purged.prior_generation.generation_id == first_generation_id
    assert purged.projected_batch_count == 0
    assert purged.purged_retired_graph_record_count > 0
    assert read.nodes == ()
    assert read.relations == ()
    assert replay.validation.validation_digest == purged.validation.validation_digest
    assert replay.promotion.promotion_digest == purged.promotion.promotion_digest
    assert not adapter.deliveries

    with closing(sqlite3.connect(state.extraction.database)) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM graphiti_adapter_attempts"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM extraction_run_versions"
        ).fetchone()[0] >= 2
        assert conn.execute(
            "SELECT COUNT(*) FROM entity_resolution_decisions"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM editorial_relation_assertions"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM object_deletion_heads h "
            "JOIN object_deletion_versions v "
            "ON v.deletion_id=h.deletion_id AND v.lifecycle_version=h.current_version "
            "WHERE h.deletion_id=? AND v.state='TOMBSTONED'",
            (str(deletion.deletion_id),),
        ).fetchone()[0] == 1
    assert not state.workspace_root.exists() or not any(
        state.workspace_root.iterdir()
    )
