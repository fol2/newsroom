from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from newsroom.authority.editorial_relation_projection_rebuild import (
    rebuild_governed_editorial_relation_current_projection,
)
from newsroom.authority.persistence import AuthoritySchemaError
from newsroom.relations import (
    EditorialRelationDecisionAction,
    EditorialRelationRightsDenied,
)
from newsroom.relations.editorial_policy import (
    merge_editorial_relation_authority_registries,
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
from .source_3a_helpers import SOURCE_NOW, proof


def _seed_admitted_relation(tmp_path: Path):
    state = seed_relation_fixture(tmp_path)
    with open_relation_system(state) as system:
        proposal = system.relations.propose(
            relation_proposal_request(state), proof=extraction_proof()
        )
        system.relations.decide(
            relation_decision_request(
                proposal,
                action=EditorialRelationDecisionAction.ACCEPT,
                decision_id=RELATION_ACCEPT_DECISION_ID,
                assertion_id=RELATION_ASSERTION_ID,
                key="relation-projection-rebuild-accept-v1",
            ),
            proof=extraction_proof(),
        )
    return state


def _registries(state):
    return merge_editorial_relation_authority_registries(
        command_registry=state.entity.extraction.commands,
        payload_schemas=state.entity.extraction.schemas,
    )


def _delete_assertion_head(state) -> None:
    with closing(sqlite3.connect(state.entity.extraction.database)) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='editorial_relation_assertion_head_delete_guard'"
        ).fetchone()
        assert row is not None and row[0]
        conn.execute("DROP TRIGGER editorial_relation_assertion_head_delete_guard")
        conn.execute(
            "DELETE FROM editorial_relation_assertion_heads WHERE assertion_id=?",
            (str(RELATION_ASSERTION_ID),),
        )
        conn.execute(str(row[0]))
        conn.commit()


def test_rebuild_restores_only_missing_current_projection_without_new_events(
    tmp_path: Path,
) -> None:
    state = _seed_admitted_relation(tmp_path)
    with closing(sqlite3.connect(state.entity.extraction.database)) as conn:
        before = conn.execute(
            "SELECT (SELECT COUNT(*) FROM ledger_events),"
            "(SELECT COUNT(*) FROM editorial_relation_projection_events)"
        ).fetchone()
    _delete_assertion_head(state)

    with pytest.raises(
        AuthoritySchemaError, match="current projection is incomplete"
    ):
        open_relation_system(state)

    commands, schemas = _registries(state)
    rebuilt = rebuild_governed_editorial_relation_current_projection(
        path=state.entity.extraction.database,
        registry=commands,
        payload_schemas=schemas,
        clock=lambda: SOURCE_NOW,
    )
    assert [item.assertion.assertion_id for item in rebuilt] == [
        RELATION_ASSERTION_ID
    ]

    with closing(sqlite3.connect(state.entity.extraction.database)) as conn:
        after = conn.execute(
            "SELECT (SELECT COUNT(*) FROM ledger_events),"
            "(SELECT COUNT(*) FROM editorial_relation_projection_events)"
        ).fetchone()
    assert after == before
    with open_relation_system(state) as reopened:
        assert reopened.relations.current(
            RELATION_ASSERTION_ID, proof=extraction_proof()
        ).assertion.assertion_id == RELATION_ASSERTION_ID


def test_rebuild_refuses_divergent_existing_projection(tmp_path: Path) -> None:
    state = _seed_admitted_relation(tmp_path)
    with closing(sqlite3.connect(state.entity.extraction.database)) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='editorial_relation_assertion_head_update_guard'"
        ).fetchone()
        assert row is not None and row[0]
        conn.execute("DROP TRIGGER editorial_relation_assertion_head_update_guard")
        conn.execute(
            "UPDATE editorial_relation_assertion_heads SET lifecycle='REVOKED' "
            "WHERE assertion_id=?",
            (str(RELATION_ASSERTION_ID),),
        )
        conn.execute(str(row[0]))
        conn.commit()

    commands, schemas = _registries(state)
    with pytest.raises(AuthoritySchemaError):
        rebuild_governed_editorial_relation_current_projection(
            path=state.entity.extraction.database,
            registry=commands,
            payload_schemas=schemas,
            clock=lambda: SOURCE_NOW,
        )


def test_rights_revocation_blocks_rebuild_atomically(tmp_path: Path) -> None:
    state = _seed_admitted_relation(tmp_path)
    commands, schemas = _registries(state)
    with open_object_system(
        state.entity.extraction.database,
        object_root=state.entity.extraction.object_root,
        clock=lambda: SOURCE_NOW,
        command_registry=commands,
        payload_schema_registry=schemas,
    ) as objects:
        objects.objects.revoke(
            state.entity.extraction.input_binding.passages[0].admission_id,
            reason_code="RELATION_REBUILD_RIGHTS_REVOKED",
            idempotency_key="relation-rebuild-rights-revoke-v1",
            proof=proof(),
        )

    _delete_assertion_head(state)
    with pytest.raises(EditorialRelationRightsDenied):
        rebuild_governed_editorial_relation_current_projection(
            path=state.entity.extraction.database,
            registry=commands,
            payload_schemas=schemas,
            clock=lambda: SOURCE_NOW,
        )
    with closing(sqlite3.connect(state.entity.extraction.database)) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM editorial_relation_assertion_heads"
        ).fetchone()[0] == 0
