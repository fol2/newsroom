from __future__ import annotations

from pathlib import Path

import pytest

from newsroom.authority.object_policy import merge_authority_registries
from newsroom.entities import EntityRightsDenied
from newsroom.entities.policy import merge_entity_authority_registries
from newsroom.sources import (
    SourceDefinitionVersionId,
    open_governed_source_registry_authority_system,
)

from .authority_a2b_helpers import open_object_system
from .entity_4b_helpers import open_entity_system, seed_entity_fixture
from .extraction_4a_helpers import extraction_proof
from .source_3a_helpers import (
    SOURCE_NOW,
    VERSION_2_ID,
    authenticator,
    authorizer,
    proof,
    read_policy,
    version_request,
)
from .test_entity_4b_lineage import (
    ENTITY_A_ALIAS_ID,
    ENTITY_A_ID,
    ENTITY_A_PROPOSAL_ID,
    ENTITY_A_PROPOSAL_V1_ID,
    ENTITY_A_V1_ID,
    ENTITY_B_ID,
    MERGE_DECISION_ID,
    MERGE_SUCCESSOR_ID,
    SPLIT_SUCCESSOR_A_ID,
    SPLIT_SUCCESSOR_B_ID,
    _accept_bilingual_equivalence,
    _accept_new_entity,
    _admit_mentions,
    _merge_request,
    _seed_two_entities,
    _split_request,
)
from .entity_4b_helpers import EN_MENTION_ID


def _combined_registries(state):
    commands, schemas = merge_entity_authority_registries(
        command_registry=state.extraction.commands,
        payload_schemas=state.extraction.schemas,
    )
    return merge_authority_registries(
        command_registry=commands,
        payload_schemas=schemas,
    )


def test_rights_revocation_blocks_resolution_and_merge_successor_reads(
    tmp_path: Path,
) -> None:
    state = seed_entity_fixture(tmp_path)
    with open_entity_system(state) as system:
        proposal_a, proposal_b = _seed_two_entities(system, state)
        system.entities.merge_entities(
            _merge_request((proposal_a.proposal_id, proposal_b.proposal_id)),
            proof=extraction_proof(),
        )

    commands, schemas = _combined_registries(state)
    with open_object_system(
        state.extraction.database,
        object_root=state.extraction.object_root,
        clock=lambda: SOURCE_NOW,
        command_registry=commands,
        payload_schema_registry=schemas,
    ) as objects:
        objects.objects.revoke(
            state.extraction.input_binding.passages[0].admission_id,
            reason_code="ENTITY_RIGHTS_REVOKED",
            idempotency_key="entity-4b-revoke-en-input",
            proof=proof(),
        )

    # Historical entity and lineage records still reopen, but every public use
    # follows the exact 4A proposal/mention provenance and fails closed.
    with open_entity_system(state) as reopened:
        for operation in (
            lambda: reopened.entities.mention(EN_MENTION_ID, proof=extraction_proof()),
            lambda: reopened.entities.entity(ENTITY_A_ID, proof=extraction_proof()),
            lambda: reopened.entities.entity(
                MERGE_SUCCESSOR_ID, proof=extraction_proof()
            ),
            lambda: reopened.entities.merge_decision(
                MERGE_DECISION_ID, proof=extraction_proof()
            ),
            lambda: reopened.entities.preferred(
                MERGE_SUCCESSOR_ID, proof=extraction_proof()
            ),
        ):
            with pytest.raises(EntityRightsDenied):
                operation()

        # Both bilingual proposals belong to the same immutable Extraction Run.
        # Revoking any required run passage invalidates current use of every
        # downstream entity derived from that proposal set.
        with pytest.raises(EntityRightsDenied):
            reopened.entities.entity(ENTITY_B_ID, proof=extraction_proof())


def test_tombstone_blocks_every_split_successor_bound_to_the_prohibited_run(
    tmp_path: Path,
) -> None:
    state = seed_entity_fixture(tmp_path)
    with open_entity_system(state) as system:
        _admit_mentions(system, state)
        _accept_new_entity(
            system,
            source=state.en_source,
            mention_id=EN_MENTION_ID,
            proposal_id=ENTITY_A_PROPOSAL_ID,
            proposal_version_id=ENTITY_A_PROPOSAL_V1_ID,
            entity_id=ENTITY_A_ID,
            entity_version_id=ENTITY_A_V1_ID,
            alias_id=ENTITY_A_ALIAS_ID,
            key_prefix="entity-lifecycle-en",
        )
        _accept_bilingual_equivalence(system, state)
        system.entities.split_entity(_split_request(), proof=extraction_proof())

    commands, schemas = _combined_registries(state)
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
            reason_code="ENTITY_DELETE_REQUESTED",
            idempotency_key="entity-4b-delete-en-input",
            proof=proof(),
        )
        objects.objects.tombstone(
            deletion.deletion_id,
            reason_code="ENTITY_TOMBSTONED",
            idempotency_key="entity-4b-tombstone-en-input",
            proof=proof(),
        )

    with open_entity_system(state) as reopened:
        with pytest.raises(EntityRightsDenied):
            reopened.entities.entity(
                SPLIT_SUCCESSOR_A_ID, proof=extraction_proof()
            )
        with pytest.raises(EntityRightsDenied):
            reopened.entities.preferred(
                SPLIT_SUCCESSOR_A_ID, proof=extraction_proof()
            )
        # The zh-HK mention is a separate evidence range, but it was produced by
        # the same immutable Extraction Run and therefore cannot survive a
        # prohibited required input as an independently authoritative result.
        with pytest.raises(EntityRightsDenied):
            reopened.entities.entity(
                SPLIT_SUCCESSOR_B_ID, proof=extraction_proof()
            )


def test_source_definition_version_change_blocks_all_entity_provenance_use(
    tmp_path: Path,
) -> None:
    state = seed_entity_fixture(tmp_path)
    with open_entity_system(state) as system:
        proposal_a, proposal_b = _seed_two_entities(system, state)
        system.entities.merge_entities(
            _merge_request((proposal_a.proposal_id, proposal_b.proposal_id)),
            proof=extraction_proof(),
        )

    commands, schemas = _combined_registries(state)
    version_3 = SourceDefinitionVersionId.parse(
        "00000000-0000-4000-8000-000000005202"
    )
    with open_governed_source_registry_authority_system(
        path=state.extraction.database,
        registry=commands,
        payload_schemas=schemas,
        authenticator=authenticator(),
        authorizer=authorizer(),
        read_policy=read_policy(),
        clock=lambda: SOURCE_NOW,
    ) as sources:
        sources.sources.record_definition_version(
            version_request(
                version_id=version_3,
                version_number=3,
                previous_version_id=VERSION_2_ID,
                locator="fixture://increment-4b/entity-guidance-v3",
                key="entity-4b-source-version-v3",
            ),
            proof=proof(),
        )

    with open_entity_system(state) as reopened:
        for entity_id in (ENTITY_A_ID, ENTITY_B_ID, MERGE_SUCCESSOR_ID):
            with pytest.raises(EntityRightsDenied, match="no longer current"):
                reopened.entities.entity(entity_id, proof=extraction_proof())
