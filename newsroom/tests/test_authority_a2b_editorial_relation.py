from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

import pytest

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


def test_editorial_relation_reads_recheck_rights_after_object_revocation(
    tmp_path: Path,
) -> None:
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
                key="a2b-editorial-relation-accept-v1",
            ),
            proof=extraction_proof(),
        )

    commands, schemas = merge_editorial_relation_authority_registries(
        command_registry=state.entity.extraction.commands,
        payload_schemas=state.entity.extraction.schemas,
    )
    with open_object_system(
        state.entity.extraction.database,
        object_root=state.entity.extraction.object_root,
        clock=lambda: SOURCE_NOW,
        command_registry=commands,
        payload_schema_registry=schemas,
    ) as objects:
        objects.objects.revoke(
            state.entity.extraction.input_binding.passages[0].admission_id,
            reason_code="A2B_EDITORIAL_RELATION_INPUT_REVOKED",
            idempotency_key="a2b-editorial-relation-input-revoked-v1",
            proof=proof(),
        )

    with open_relation_system(state) as reopened:
        operations = (
            lambda: reopened.relations.proposal(
                proposal.proposal_id, proof=extraction_proof()
            ),
            lambda: reopened.relations.assertion(
                RELATION_ASSERTION_ID, proof=extraction_proof()
            ),
            lambda: reopened.relations.current(
                RELATION_ASSERTION_ID, proof=extraction_proof()
            ),
            lambda: reopened.relations.current_relations(
                limit=10, proof=extraction_proof()
            ),
            lambda: reopened.relations.projection_events_after(
                after_ledger_seq=0,
                limit=10,
                proof=extraction_proof(),
            ),
        )
        for operation in operations:
            with pytest.raises(EditorialRelationRightsDenied):
                operation()

    with closing(sqlite3.connect(state.entity.extraction.database)) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM editorial_relation_proposals WHERE proposal_id=?",
            (str(proposal.proposal_id),),
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM editorial_relation_decisions WHERE decision_id=?",
            (str(decision.decision_id),),
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM editorial_relation_assertions WHERE assertion_id=?",
            (str(RELATION_ASSERTION_ID),),
        ).fetchone()[0] == 1
