from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest

from newsroom.authority import UtcTimestamp
from newsroom.sources import open_governed_source_registry_authority_system
from newsroom.entities import EntityAliasKind, EntityResolutionDecisionAction
from newsroom.increment4 import Increment4Neo4jBuildRequest
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
