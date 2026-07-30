from __future__ import annotations

from pathlib import Path

import pytest

from newsroom.relations import (
    EditorialRelationDecisionAction,
    EditorialRelationRightsDenied,
)
from newsroom.relations.editorial_policy import (
    merge_editorial_relation_authority_registries,
)
from newsroom.sources import (
    SourceDefinitionVersionId,
    open_governed_source_registry_authority_system,
)

from .authority_a2b_helpers import open_object_system
from .editorial_relation_4c_helpers import (
    RELATION_ACCEPT_DECISION_ID,
    RELATION_ASSERTION_ID,
    open_relation_system,
    relation_decision_request,
    relation_proposal_request,
    seed_relation_fixture,
)
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


def _combined_registries(state):
    return merge_editorial_relation_authority_registries(
        command_registry=state.entity.extraction.commands,
        payload_schemas=state.entity.extraction.schemas,
    )


def _seed_admitted_relation(tmp_path: Path):
    state = seed_relation_fixture(tmp_path)
    with open_relation_system(state) as system:
        proposal = system.relations.propose(
            relation_proposal_request(state), proof=extraction_proof()
        )
        decision = system.relations.decide(
            relation_decision_request(
                proposal,
                action=EditorialRelationDecisionAction.ACCEPT,
                decision_id=RELATION_ACCEPT_DECISION_ID,
                assertion_id=RELATION_ASSERTION_ID,
                key="relation-rights-accept-v1",
            ),
            proof=extraction_proof(),
        )
    return state, proposal, decision


def _assert_every_current_surface_denied(state, proposal) -> None:
    with open_relation_system(state) as reopened:
        operations = (
            lambda: reopened.relations.proposal(
                proposal.proposal_id, proof=extraction_proof()
            ),
            lambda: reopened.relations.proposal_version(
                proposal.proposal_version_id, proof=extraction_proof()
            ),
            lambda: reopened.relations.decision(
                proposal.proposal_id, proof=extraction_proof()
            ),
            lambda: reopened.relations.assertion(
                RELATION_ASSERTION_ID, proof=extraction_proof()
            ),
            lambda: reopened.relations.current(
                RELATION_ASSERTION_ID, proof=extraction_proof()
            ),
            lambda: reopened.relations.current_relations(
                limit=100, proof=extraction_proof()
            ),
            lambda: reopened.relations.projection_events_after(
                after_ledger_seq=0,
                limit=100,
                proof=extraction_proof(),
            ),
        )
        for operation in operations:
            with pytest.raises(EditorialRelationRightsDenied):
                operation()


def test_governed_object_revocation_blocks_all_current_relation_use(
    tmp_path: Path,
) -> None:
    state, proposal, _decision = _seed_admitted_relation(tmp_path)
    commands, schemas = _combined_registries(state)
    with open_object_system(
        state.entity.extraction.database,
        object_root=state.entity.extraction.object_root,
        clock=lambda: SOURCE_NOW,
        command_registry=commands,
        payload_schema_registry=schemas,
    ) as objects:
        objects.objects.revoke(
            state.entity.extraction.input_binding.passages[0].admission_id,
            reason_code="RELATION_RIGHTS_REVOKED",
            idempotency_key="relation-4c-revoke-en-input",
            proof=proof(),
        )

    _assert_every_current_surface_denied(state, proposal)


def test_governed_object_tombstone_blocks_relation_use_without_deleting_history(
    tmp_path: Path,
) -> None:
    state, proposal, _decision = _seed_admitted_relation(tmp_path)
    commands, schemas = _combined_registries(state)
    passage = state.entity.extraction.input_binding.passages[0]
    with open_object_system(
        state.entity.extraction.database,
        object_root=state.entity.extraction.object_root,
        clock=lambda: SOURCE_NOW,
        command_registry=commands,
        payload_schema_registry=schemas,
    ) as objects:
        deletion = objects.objects.request_deletion(
            passage.blob_digest,
            reason_code="RELATION_DELETE_REQUESTED",
            idempotency_key="relation-4c-delete-en-input",
            proof=proof(),
        )
        objects.objects.tombstone(
            deletion.deletion_id,
            reason_code="RELATION_TOMBSTONED",
            idempotency_key="relation-4c-tombstone-en-input",
            proof=proof(),
        )

    _assert_every_current_surface_denied(state, proposal)


def test_source_definition_version_change_blocks_relation_current_use(
    tmp_path: Path,
) -> None:
    state, proposal, _decision = _seed_admitted_relation(tmp_path)
    commands, schemas = _combined_registries(state)
    version_3 = SourceDefinitionVersionId.parse(
        "00000000-0000-4000-8000-000000005302"
    )
    with open_governed_source_registry_authority_system(
        path=state.entity.extraction.database,
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
                locator="fixture://increment-4c/relation-guidance-v3",
                key="relation-4c-source-version-v3",
            ),
            proof=proof(),
        )

    _assert_every_current_surface_denied(state, proposal)
