from __future__ import annotations

from contextlib import closing
from pathlib import Path
import re
import sqlite3

import pytest

from newsroom.authority.persistence import (
    AuthorityPersistenceError,
    AuthoritySchemaError,
)
from newsroom.entities import (
    EntityContractError,
    EntityLineageVersion,
    EntityReversalDecisionRequest,
    EntityReversalTargetKind,
)

from .entity_4b_helpers import (
    EN_MENTION_ID,
    dependency_request,
    open_entity_system,
    seed_entity_fixture,
)
from .extraction_4a_helpers import extraction_proof
from .test_entity_4b_lineage import (
    MERGE_DECISION_ID,
    MERGE_REVERSAL_ID,
    _accept_bilingual_equivalence,
    _accept_new_entity,
    _admit_mentions,
    _merge_request,
    _seed_two_entities,
    _split_request,
    ENTITY_A_ALIAS_ID,
    ENTITY_A_ID,
    ENTITY_A_PROPOSAL_ID,
    ENTITY_A_PROPOSAL_V1_ID,
    ENTITY_A_V1_ID,
)
from .test_entity_4b_lineage import (
    ENTITY_B_ID,
    MERGE_RESTORED_A_ID,
    MERGE_RESTORED_B_ID,
)


def _disable_trigger(conn: sqlite3.Connection, name: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",
        (name,),
    ).fetchone()
    assert row is not None and row[0]
    conn.execute(f'DROP TRIGGER "{name}"')
    return str(row[0])


def _expect_reopen_failure(state, match: str) -> None:
    with pytest.raises(
        (
            AuthorityPersistenceError,
            AuthoritySchemaError,
            EntityContractError,
        )
    ) as caught:
        open_entity_system(state)
    messages: list[str] = []
    current: BaseException | None = caught.value
    while current is not None:
        messages.append(str(current))
        current = current.__cause__
    assert any(re.search(match, message) for message in messages), messages


def _seed_merge_reversal_and_dependency(tmp_path: Path):
    state = seed_entity_fixture(tmp_path)
    with open_entity_system(state) as system:
        proposal_a, proposal_b = _seed_two_entities(system, state)
        system.entities.bind_resolution_dependency(
            dependency_request(state, proposal_a), proof=extraction_proof()
        )
        merged = system.entities.merge_entities(
            _merge_request((proposal_a.proposal_id, proposal_b.proposal_id)),
            proof=extraction_proof(),
        )
        system.entities.reverse_lineage(
            EntityReversalDecisionRequest(
                reversal_decision_id=MERGE_REVERSAL_ID,
                target_kind=EntityReversalTargetKind.MERGE,
                target_decision_id=str(MERGE_DECISION_ID),
                expected_current_entity_version_ids=tuple(
                    sorted(
                        (
                            *(
                                item.merged_entity_version_id
                                for item in merged.predecessors
                            ),
                            merged.successor_entity_version_id,
                        ),
                        key=str,
                    )
                ),
                restorations=tuple(
                    sorted(
                        (
                            EntityLineageVersion(ENTITY_A_ID, MERGE_RESTORED_A_ID),
                            EntityLineageVersion(ENTITY_B_ID, MERGE_RESTORED_B_ID),
                        ),
                        key=lambda item: str(item.entity_id),
                    )
                ),
                reason_code="INTEGRITY_MERGE_REVERSAL",
                decision_policy_version="entity-resolution-policy-v1",
                idempotency_key="integrity-merge-reversal-v1",
            ),
            proof=extraction_proof(),
        )
    return state


def _seed_split(tmp_path: Path):
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
            key_prefix="integrity-split-source",
        )
        _accept_bilingual_equivalence(system, state)
        system.entities.split_entity(_split_request(), proof=extraction_proof())
    return state


def test_lineage_dependency_and_projection_rows_are_immutable(tmp_path: Path) -> None:
    state = _seed_merge_reversal_and_dependency(tmp_path)
    cases = (
        (
            "immutable_entity_merge_decision_update",
            "UPDATE entity_merge_decisions SET reason_code=reason_code",
            "entity merge decisions are immutable",
        ),
        (
            "immutable_entity_merge_predecessor_update",
            "UPDATE entity_merge_predecessors SET entity_id=entity_id",
            "entity merge predecessors are immutable",
        ),
        (
            "immutable_entity_reversal_decision_update",
            "UPDATE entity_reversal_decisions SET reason_code=reason_code",
            "entity reversal decisions are immutable",
        ),
        (
            "immutable_entity_reversal_expected_version_update",
            "UPDATE entity_reversal_expected_versions "
            "SET entity_version_id=entity_version_id",
            "entity reversal expected versions are immutable",
        ),
        (
            "immutable_entity_reversal_restoration_update",
            "UPDATE entity_reversal_restorations SET entity_id=entity_id",
            "entity reversal restorations are immutable",
        ),
        (
            "immutable_entity_reversal_supersession_update",
            "UPDATE entity_reversal_supersessions SET entity_id=entity_id",
            "entity reversal supersessions are immutable",
        ),
        (
            "immutable_entity_resolution_dependency_update",
            "UPDATE entity_resolution_dependencies SET material=material",
            "entity resolution dependencies are immutable",
        ),
        (
            "immutable_entity_projection_event_update",
            "UPDATE entity_projection_events SET action=action",
            "entity projection events are immutable",
        ),
    )
    with closing(sqlite3.connect(state.extraction.database)) as conn:
        for trigger, statement, match in cases:
            assert conn.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type='trigger' AND name=?",
                (trigger,),
            ).fetchone()[0] == 1
            with pytest.raises(sqlite3.IntegrityError, match=match):
                conn.execute(statement)


def test_split_rows_are_immutable(tmp_path: Path) -> None:
    state = _seed_split(tmp_path)
    cases = (
        (
            "immutable_entity_split_decision_update",
            "UPDATE entity_split_decisions SET reason_code=reason_code",
            "entity split decisions are immutable",
        ),
        (
            "immutable_entity_split_successor_update",
            "UPDATE entity_split_successors SET entity_id=entity_id",
            "entity split successors are immutable",
        ),
        (
            "immutable_entity_split_allocation_update",
            "UPDATE entity_split_allocations SET mention_id=mention_id",
            "entity split allocations are immutable",
        ),
    )
    with closing(sqlite3.connect(state.extraction.database)) as conn:
        for trigger, statement, match in cases:
            assert conn.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type='trigger' AND name=?",
                (trigger,),
            ).fetchone()[0] == 1
            with pytest.raises(sqlite3.IntegrityError, match=match):
                conn.execute(statement)


def test_reopen_rejects_dependency_request_and_canonical_tamper(
    tmp_path: Path,
) -> None:
    state = _seed_merge_reversal_and_dependency(tmp_path)
    with closing(sqlite3.connect(state.extraction.database)) as conn:
        trigger = _disable_trigger(
            conn, "immutable_entity_resolution_dependency_update"
        )
        conn.execute(
            "UPDATE entity_resolution_dependencies "
            "SET material=CASE material WHEN 1 THEN 0 ELSE 1 END"
        )
        conn.execute(trigger)
        conn.commit()
    _expect_reopen_failure(
        state,
        "entity resolution dependency differs from its request|"
        "entity resolution dependency canonical bytes differ",
    )


def test_reopen_rejects_missing_projection_event_coverage(tmp_path: Path) -> None:
    state = _seed_merge_reversal_and_dependency(tmp_path)
    with closing(sqlite3.connect(state.extraction.database)) as conn:
        trigger = _disable_trigger(conn, "immutable_entity_projection_event_delete")
        row = conn.execute(
            "SELECT projection_event_id FROM entity_projection_events "
            "ORDER BY source_ledger_seq,projection_event_id LIMIT 1"
        ).fetchone()
        assert row is not None
        conn.execute(
            "DELETE FROM entity_projection_events WHERE projection_event_id=?",
            (str(row[0]),),
        )
        conn.execute(trigger)
        conn.commit()
    _expect_reopen_failure(
        state,
        "lacks projection-event coverage|latest projection event",
    )


def test_reopen_rejects_divergent_preferred_projection(tmp_path: Path) -> None:
    state = _seed_merge_reversal_and_dependency(tmp_path)
    with closing(sqlite3.connect(state.extraction.database)) as conn:
        update_guard = _disable_trigger(conn, "entity_preferred_identity_update_guard")
        lineage_guard = _disable_trigger(
            conn, "entity_preferred_identity_update_lineage_guard"
        )
        rows = conn.execute(
            "SELECT entity_id FROM entity_preferred_identities "
            "ORDER BY entity_id LIMIT 2"
        ).fetchall()
        assert len(rows) == 2
        conn.execute(
            "UPDATE entity_preferred_identities SET preferred_entity_id=? "
            "WHERE entity_id=?",
            (str(rows[1][0]), str(rows[0][0])),
        )
        conn.execute(update_guard)
        conn.execute(lineage_guard)
        conn.commit()
    _expect_reopen_failure(
        state,
        "preferred entity projection differs from its latest event|"
        "latest entity projection event differs from current authority",
    )


def test_reopen_rejects_entity_event_without_typed_dependency_record(
    tmp_path: Path,
) -> None:
    state = _seed_merge_reversal_and_dependency(tmp_path)
    with closing(sqlite3.connect(state.extraction.database)) as conn:
        trigger = _disable_trigger(
            conn, "immutable_entity_resolution_dependency_delete"
        )
        conn.execute("DELETE FROM entity_resolution_dependencies")
        conn.execute(trigger)
        conn.commit()
    _expect_reopen_failure(
        state,
        "entity.resolution.dependency.bound event lacks its typed entity record",
    )
