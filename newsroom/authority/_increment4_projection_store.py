from __future__ import annotations

from newsroom.authority.persistence import AuthorityPersistenceError
from newsroom.entities.types import (
    CanonicalEntityId,
    EntityProjectionAction,
)
from newsroom.increment4.models import (
    Increment4AdmittedProjectionSnapshot,
    Increment4EntityProjectionState,
    Increment4RelationProjectionState,
    sorted_snapshot,
)
from newsroom.projection.models import ProjectionStateError
from newsroom.relations.editorial_types import EditorialRelationAssertionId

from ._editorial_relation_store import _EditorialRelationAuthorityStore
from ._projection_store import _ProjectionAuthorityStore


class _Increment4ProjectionAuthorityStore(
    _EditorialRelationAuthorityStore,
    _ProjectionAuthorityStore,
):
    """Projection authority with exact governed Increment 4 snapshot reads."""

    def increment4_admitted_snapshot(self) -> Increment4AdmittedProjectionSnapshot:
        """Rederive current admitted graph input from retained SQLite authority.

        Callers may carry a snapshot only as an optimistic exact-value assertion.
        The returned object is reconstructed inside the authority boundary after
        current rights and retained canonical records have been revalidated.
        """

        with self._lock:
            conn = self._connection
            source_watermark = self.latest_projection_source_ledger_seq()
            if source_watermark <= 0:
                raise ProjectionStateError(
                    "Increment 4 admitted projection has no retained source authority"
                )

            entity_states: list[Increment4EntityProjectionState] = []
            # The latest retained projection action defines current graph
            # membership. MERGED lineage can remain an UPSERT state, while
            # split/reversal/tombstone removals must not be resurrected.
            entity_rows = conn.execute(
                "SELECT p.entity_id "
                "FROM entity_preferred_identities AS p "
                "JOIN entity_projection_events AS e "
                "ON e.entity_id=p.entity_id "
                "AND e.source_ledger_seq=p.projected_through_ledger_seq "
                "WHERE e.action=? "
                "ORDER BY p.entity_id",
                (EntityProjectionAction.UPSERT.value,),
            ).fetchall()
            for row in entity_rows:
                entity_id = CanonicalEntityId.parse(str(row["entity_id"]))
                try:
                    entity = self.entity(entity_id)
                    preferred = self.preferred_identity(entity_id)
                    version = self.entity_version(
                        preferred.current_entity_version_id
                    )
                    alias_count = int(
                        conn.execute(
                            "SELECT COUNT(*) FROM entity_aliases WHERE entity_id=?",
                            (str(entity_id),),
                        ).fetchone()[0]
                    )
                    aliases = tuple(
                        sorted(
                            self.aliases(entity_id, limit=max(1, alias_count)),
                            key=lambda item: str(item.alias_id),
                        )
                    )
                except PermissionError:
                    # Rights-invalid current state must disappear from derivative
                    # authority rather than being copied from stale caller memory.
                    continue
                if len(aliases) != alias_count:
                    raise AuthorityPersistenceError(
                        "Increment 4 entity alias authority is incomplete"
                    )
                projection_rows = conn.execute(
                    "SELECT * FROM entity_projection_events "
                    "WHERE entity_id=? AND source_ledger_seq=? "
                    "ORDER BY projection_event_id",
                    (
                        str(entity_id),
                        preferred.projected_through_ledger_seq,
                    ),
                ).fetchall()
                if len(projection_rows) != 1:
                    raise AuthorityPersistenceError(
                        "Increment 4 entity lacks one exact current projection event"
                    )
                projection_event = self._projection_event_from_row(
                    conn, projection_rows[0]
                )
                if projection_event.source_ledger_seq > source_watermark:
                    raise AuthorityPersistenceError(
                        "Increment 4 entity projection exceeds source authority"
                    )
                entity_states.append(
                    Increment4EntityProjectionState(
                        entity=entity,
                        version=version,
                        preferred=preferred,
                        aliases=aliases,
                        projection_event=projection_event,
                    )
                )

            relation_states: list[Increment4RelationProjectionState] = []
            relation_rows = conn.execute(
                "SELECT assertion_id FROM editorial_current_admitted_relations "
                "ORDER BY assertion_id"
            ).fetchall()
            for row in relation_rows:
                assertion_id = EditorialRelationAssertionId.parse(
                    str(row["assertion_id"])
                )
                try:
                    current = self.editorial_current(assertion_id)
                except PermissionError:
                    continue
                projection_row = conn.execute(
                    "SELECT * FROM editorial_relation_projection_events "
                    "WHERE assertion_id=? AND source_ledger_seq<=? "
                    "ORDER BY source_ledger_seq DESC,projection_event_id DESC LIMIT 1",
                    (str(assertion_id), source_watermark),
                ).fetchone()
                if projection_row is None:
                    raise AuthorityPersistenceError(
                        "Increment 4 relation lacks current projection authority"
                    )
                projection_event = self._editorial_projection_event_from_row(
                    conn, projection_row
                )
                relation_states.append(
                    Increment4RelationProjectionState(
                        current=current,
                        projection_event=projection_event,
                    )
                )

            event_rows = conn.execute(
                "SELECT * FROM ledger_events WHERE ledger_seq<=? ORDER BY ledger_seq",
                (source_watermark,),
            ).fetchall()
            events = tuple(self._event_from_row(row) for row in event_rows)
            if not events or events[-1].ledger_seq != source_watermark:
                raise AuthorityPersistenceError(
                    "Increment 4 source watermark lacks an exact retained event"
                )
            return sorted_snapshot(
                entities=entity_states,
                relations=relation_states,
                events=events,
                through_ledger_seq=source_watermark,
            )


__all__ = ["_Increment4ProjectionAuthorityStore"]