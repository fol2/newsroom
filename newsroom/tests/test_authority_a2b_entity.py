from __future__ import annotations

from contextlib import closing
import sqlite3
from pathlib import Path

import pytest

from newsroom.authority.object_policy import merge_authority_registries
from newsroom.entities import EntityAliasKind, EntityResolutionDecisionAction
from newsroom.entities.policy import merge_entity_authority_registries

from .authority_a2b_helpers import open_object_system
from .entity_4b_helpers import (
    EN_ALIAS_ID,
    EN_MENTION_ID,
    ENTITY_ID,
    ENTITY_VERSION_ID,
    decision_request,
    mention_request,
    new_entity_proposal_request,
    open_entity_system,
    seed_entity_fixture,
)
from .extraction_4a_helpers import extraction_proof
from .source_3a_helpers import SOURCE_NOW, proof


def test_entity_reads_recheck_complete_extraction_rights_after_revocation(
    tmp_path: Path,
) -> None:
    state = seed_entity_fixture(tmp_path)
    with open_entity_system(state) as system:
        system.entities.admit_mention(
            mention_request(
                state.en_source,
                mention_id=EN_MENTION_ID,
                language="en-GB",
                key="a2b-entity-mention-v1",
            ),
            proof=extraction_proof(),
        )
        proposal = system.entities.propose_resolution(
            new_entity_proposal_request(
                state, key="a2b-entity-proposal-v1"
            ),
            proof=extraction_proof(),
        )
        accepted = system.entities.decide_resolution(
            decision_request(
                proposal,
                action=EntityResolutionDecisionAction.ACCEPT,
                entity_id=ENTITY_ID,
                version_id=ENTITY_VERSION_ID,
                alias_id=EN_ALIAS_ID,
                alias_kind=EntityAliasKind.PRIMARY_NAME,
                key="a2b-entity-decision-v1",
            ),
            proof=extraction_proof(),
        )

    commands, schemas = merge_entity_authority_registries(
        command_registry=state.extraction.commands,
        payload_schemas=state.extraction.schemas,
    )
    commands, schemas = merge_authority_registries(
        command_registry=commands,
        payload_schemas=schemas,
    )
    with open_object_system(
        state.extraction.database,
        object_root=state.extraction.object_root,
        clock=lambda: SOURCE_NOW,
        command_registry=commands,
        payload_schema_registry=schemas,
    ) as objects:
        objects.objects.revoke(
            state.extraction.input_binding.passages[0].admission_id,
            reason_code="A2B_ENTITY_INPUT_REVOKED",
            idempotency_key="a2b-entity-input-revoked-v1",
            proof=proof(),
        )

    with open_entity_system(state) as reopened:
        with pytest.raises(PermissionError):
            reopened.entities.entity(ENTITY_ID, proof=extraction_proof())
        with pytest.raises(PermissionError):
            reopened.entities.aliases(
                ENTITY_ID, limit=10, proof=extraction_proof()
            )
        with pytest.raises(PermissionError):
            reopened.entities.preferred(
                ENTITY_ID, proof=extraction_proof()
            )

    with closing(sqlite3.connect(state.extraction.database)) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM canonical_entities WHERE entity_id=?",
            (str(ENTITY_ID),),
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM entity_resolution_decisions "
            "WHERE decision_id=?",
            (str(accepted.decision_id),),
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM entity_aliases WHERE alias_id=?",
            (str(EN_ALIAS_ID),),
        ).fetchone()[0] == 1
