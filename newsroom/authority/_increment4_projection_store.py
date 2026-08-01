from __future__ import annotations

from newsroom.authority.persistence import AuthorityPersistenceError
from newsroom.entities.types import (
    CanonicalEntityId,
    CanonicalEntityLifecycle,
    EntityCreationDecisionKind,
    EntityProjectionAction,
)
from newsroom.increment4.models import (
    Increment4AdmittedProjectionSnapshot,
    Increment4EntityProjectionState,
    Increment4RelationProjectionState,
    sorted_snapshot,
)
from newsroom.projection.models import ProjectionStateError
from newsroom.relations.editorial_types import (
    EditorialRelationAssertionId,
    EditorialRelationStaleDecision,
)

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
            # Every lineage transition retains an UPSERT projection event. Split-
            # created successors stop belonging to current graph state when that
            # split is reversed, while a reversed merge successor remains required
            # to preserve the admitted merge/reversal lineage. Creation authority
            # therefore participates in current graph membership.
            entity_rows = conn.execute(
                "SELECT p.entity_id "
                "FROM entity_preferred_identities AS p "
                "JOIN canonical_entities AS c ON c.entity_id=p.entity_id "
                "JOIN entity_projection_events AS e "
                "ON e.entity_id=p.entity_id "
                "AND e.source_ledger_seq=p.projected_through_ledger_seq "
                "WHERE e.action=? "
                "AND NOT (p.lifecycle=? AND c.created_by_kind=?) "
                "ORDER BY p.entity_id",
                (
                    EntityProjectionAction.UPSERT.value,
                    CanonicalEntityLifecycle.REVERSED.value,
                    EntityCreationDecisionKind.SPLIT.value,
                ),
            ).fetchall()
            for row in entity_rows:
                entity_id = CanonicalEntityId.parse(str(row["entity_id"]))
                try:
                    entity = self.entity(entity_id)
                    preferred = self.preferred_identity(entity_id)
                    version = self.entity_version(
                        preferred.current_entity_version_id
                    )
                except PermissionError:
                    # Rights-invalid current state must disappear from derivative
                    # authority rather than being copied from stale caller memory.
                    continue

                # Alias evidence can have independent rights from the retained
                # entity creation decision. Decode every immutable alias row, but
                # retain only aliases whose own provenance remains currently
                # usable. One revoked alias must not remove an otherwise-current
                # entity or make relation endpoint membership inconsistent.
                alias_rows = conn.execute(
                    "SELECT * FROM entity_aliases WHERE entity_id=? "
                    "ORDER BY language,normalized_text,alias_id",
                    (str(entity_id),),
                ).fetchall()
                admitted_aliases = []
                for alias_row in alias_rows:
                    alias = self._alias_from_row(conn, alias_row)
                    mention = self._mention_from_row(
                        conn,
                        self._mention_row(conn, alias.provenance_mention_id),
                        replayed=False,
                    )
                    try:
                        self._require_mention_current(conn, mention)
                    except PermissionError:
                        continue
                    admitted_aliases.append(alias)
                aliases = tuple(
                    sorted(admitted_aliases, key=lambda item: str(item.alias_id))
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
                except (PermissionError, EditorialRelationStaleDecision):
                    # Rights-invalid or endpoint-stale assertions remain immutable
                    # history but cannot participate in the current graph snapshot.
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
