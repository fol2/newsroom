from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from newsroom.authority.entity_projection_rebuild import (
    rebuild_governed_entity_preferred_projection,
)
from newsroom.authority.object_policy import merge_authority_registries
from newsroom.entities import (
    EntityLineageVersion,
    EntityProjectionAction,
    EntityReversalDecisionRequest,
    EntityReversalTargetKind,
)
from newsroom.entities.policy import merge_entity_authority_registries

from .authority_a2b_helpers import open_object_system
from .entity_4b_helpers import open_entity_system, seed_entity_fixture
from .extraction_4a_helpers import extraction_proof
from .source_3a_helpers import SOURCE_NOW, proof
from .test_entity_4b_lineage import (
    ENTITY_A_ID,
    ENTITY_B_ID,
    MERGE_DECISION_ID,
    MERGE_RESTORED_A_ID,
    MERGE_RESTORED_B_ID,
    MERGE_REVERSAL_ID,
    _merge_request,
    _seed_two_entities,
)


def _projection_rows(database: Path) -> tuple[tuple[object, ...], ...]:
    conn = sqlite3.connect(database)
    try:
        return tuple(
            conn.execute(
                "SELECT entity_id,current_entity_version_id,preferred_entity_id,"
                "lifecycle,decided_by_kind,decided_by_id,"
                "projected_through_ledger_seq,updated_at "
                "FROM entity_preferred_identities ORDER BY entity_id"
            ).fetchall()
        )
    finally:
        conn.close()


def _wipe_preferred_projection(database: Path) -> tuple[int, int]:
    conn = sqlite3.connect(database)
    try:
        before = (
            int(conn.execute("SELECT COUNT(*) FROM ledger_events").fetchone()[0]),
            int(
                conn.execute(
                    "SELECT COUNT(*) FROM entity_projection_events"
                ).fetchone()[0]
            ),
        )
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='entity_preferred_identity_delete_guard'"
        ).fetchone()
        assert row is not None and row[0]
        conn.execute("DROP TRIGGER entity_preferred_identity_delete_guard")
        conn.execute("DELETE FROM entity_preferred_identities")
        conn.execute(str(row[0]))
        conn.commit()
        assert conn.execute(
            "SELECT COUNT(*) FROM entity_preferred_identities"
        ).fetchone()[0] == 0
        return before
    finally:
        conn.close()


def _rebuild(state):
    return rebuild_governed_entity_preferred_projection(
        path=state.extraction.database,
        registry=state.extraction.commands,
        payload_schemas=state.extraction.schemas,
        clock=lambda: SOURCE_NOW,
    )



def test_projection_event_stream_is_ordered_admitted_only_and_scope_bounded(
    tmp_path: Path,
) -> None:
    state = seed_entity_fixture(tmp_path)
    with open_entity_system(state) as system:
        _seed_two_entities(system, state)
        events = system.entities.projection_events_after(
            0, limit=100, proof=extraction_proof()
        )
        assert len(events) == 2
        assert tuple(item.source_ledger_seq for item in events) == tuple(
            sorted(item.source_ledger_seq for item in events)
        )
        assert {item.action for item in events} == {EntityProjectionAction.UPSERT}
        assert {str(item.entity_id) for item in events} == {
            str(ENTITY_A_ID),
            str(ENTITY_B_ID),
        }
        assert all(item.preferred_entity_id == item.entity_id for item in events)
        assert all(item.trust_scope.value == "ADMITTED" for item in events)
        assert all(item.canonical_digest.startswith("sha256:") for item in events)

        tail = system.entities.projection_events_after(
            events[0].source_ledger_seq, limit=100, proof=extraction_proof()
        )
        assert tail == events[1:]
        assert system.entities.projection_events_after(
            0, limit=1, proof=extraction_proof()
        ) == events[:1]

    scopes_without_projection = frozenset(
        {
            "authority.entity.read_proposals",
            "authority.entity.read_admitted",
        }
    )
    with open_entity_system(state, scopes=scopes_without_projection) as restricted:
        with pytest.raises(PermissionError):
            restricted.entities.projection_events_after(
                0, limit=100, proof=extraction_proof()
            )


def test_preferred_projection_rebuilds_exactly_after_merge_reversal_loss(
    tmp_path: Path,
) -> None:
    state = seed_entity_fixture(tmp_path)
    with open_entity_system(state) as system:
        proposal_a, proposal_b = _seed_two_entities(system, state)
        merged = system.entities.merge_entities(
            _merge_request((proposal_a.proposal_id, proposal_b.proposal_id)),
            proof=extraction_proof(),
        )
        request = EntityReversalDecisionRequest(
            reversal_decision_id=MERGE_REVERSAL_ID,
            target_kind=EntityReversalTargetKind.MERGE,
            target_decision_id=str(MERGE_DECISION_ID),
            expected_current_entity_version_ids=tuple(
                sorted(
                    (
                        *(item.merged_entity_version_id for item in merged.predecessors),
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
            reason_code="PROJECTION_REBUILD_MERGE_REVERSAL",
            decision_policy_version="entity-resolution-policy-v1",
            idempotency_key="projection-rebuild-merge-reversal-v1",
        )
        system.entities.reverse_lineage(request, proof=extraction_proof())

    before_rows = _projection_rows(state.extraction.database)
    counts = _wipe_preferred_projection(state.extraction.database)
    rebuilt = _rebuild(state)
    after_rows = _projection_rows(state.extraction.database)

    assert after_rows == before_rows
    assert tuple(str(item.entity_id) for item in rebuilt) == tuple(
        str(row[0]) for row in before_rows
    )
    conn = sqlite3.connect(state.extraction.database)
    try:
        assert (
            int(conn.execute("SELECT COUNT(*) FROM ledger_events").fetchone()[0]),
            int(
                conn.execute(
                    "SELECT COUNT(*) FROM entity_projection_events"
                ).fetchone()[0]
            ),
        ) == counts
    finally:
        conn.close()
    # The ordinary checked open accepts the rebuilt derivative.
    with open_entity_system(state):
        pass


def test_projection_rebuild_fails_atomically_when_source_rights_are_revoked(
    tmp_path: Path,
) -> None:
    state = seed_entity_fixture(tmp_path)
    with open_entity_system(state) as system:
        _seed_two_entities(system, state)

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
            reason_code="PROJECTION_REBUILD_INPUT_REVOKED",
            idempotency_key="projection-rebuild-input-revoked-v1",
            proof=proof(),
        )

    _wipe_preferred_projection(state.extraction.database)
    with pytest.raises(PermissionError):
        _rebuild(state)
    conn = sqlite3.connect(state.extraction.database)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM entity_preferred_identities"
        ).fetchone()[0] == 0
    finally:
        conn.close()
