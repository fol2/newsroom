from __future__ import annotations

from newsroom.checks.record_models import OperationalFindingOccurrence
from newsroom.checks.types import (
    CheckStateError,
    OperationalFindingOccurrenceId,
)
from newsroom.sources import (
    DiscoveryOccurrence,
    DiscoveryOccurrenceId,
    DiscoveryOccurrenceKind,
    DiscoveryRepresentation,
    SourceDefinitionId,
    SourceItem,
    SourceItemId,
    SourceRevision,
    SourceRevisionId,
)


class _CheckAdmissionLookupMixin:
    """Typed semantic lookups used only by deterministic proposal admission."""

    def source_item_by_identity_digest(
        self,
        definition_id: SourceDefinitionId,
        identity_digest: str,
    ) -> SourceItem | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM source_items WHERE definition_id=? "
                "AND identity_digest=?",
                (str(definition_id), identity_digest),
            ).fetchone()
            return (
                None
                if row is None
                else self._source_item_from_row(
                    self._connection,
                    row,
                    replayed=False,
                )
            )

    def latest_source_revision(
        self,
        item_id: SourceItemId,
    ) -> SourceRevision | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT r.* FROM source_revisions r "
                "JOIN ledger_events e ON e.event_id=r.authority_event_id "
                "WHERE r.item_id=? ORDER BY e.ledger_seq DESC LIMIT 1",
                (str(item_id),),
            ).fetchone()
            return (
                None
                if row is None
                else self._source_revision_from_row(
                    self._connection,
                    row,
                    replayed=False,
                )
            )

    def source_revision_by_identity_digest(
        self,
        item_id: SourceItemId,
        revision_identity_digest: str,
    ) -> SourceRevision | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM source_revisions WHERE item_id=? "
                "AND revision_identity_digest=?",
                (str(item_id), revision_identity_digest),
            ).fetchone()
            return (
                None
                if row is None
                else self._source_revision_from_row(
                    self._connection,
                    row,
                    replayed=False,
                )
            )

    def representation_by_producer_slot(
        self,
        revision_id: SourceRevisionId,
        producer_slot_digest: str,
    ) -> DiscoveryRepresentation | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM discovery_representations WHERE revision_id=? "
                "AND producer_slot_digest=?",
                (str(revision_id), producer_slot_digest),
            ).fetchone()
            return (
                None
                if row is None
                else self._representation_from_row(
                    self._connection,
                    row,
                    replayed=False,
                )
            )

    def discovery_occurrence_by_identity(
        self,
        occurrence_id: DiscoveryOccurrenceId,
    ) -> DiscoveryOccurrence | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM discovery_occurrences WHERE occurrence_id=?",
                (str(occurrence_id),),
            ).fetchone()
            return (
                None
                if row is None
                else self._occurrence_from_row(
                    self._connection,
                    row,
                    replayed=False,
                )
            )

    def discovery_occurrence_for_outcome_revision_any(
        self,
        *,
        check_outcome_id,
        revision_id,
    ) -> DiscoveryOccurrence | None:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM discovery_occurrences WHERE check_outcome_id=? "
                "AND revision_id=? ORDER BY recorded_at,occurrence_id",
                (str(check_outcome_id), str(revision_id)),
            ).fetchall()
            if len(rows) > 1:
                raise CheckStateError(
                    "one Check Outcome retained multiple Occurrences for one Revision"
                )
            return (
                None
                if not rows
                else self._occurrence_from_row(
                    self._connection,
                    rows[0],
                    replayed=False,
                )
            )

    def finding_occurrence_by_identity(
        self,
        occurrence_id: OperationalFindingOccurrenceId,
    ) -> OperationalFindingOccurrence | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM operational_finding_occurrences "
                "WHERE occurrence_id=?",
                (str(occurrence_id),),
            ).fetchone()
            return (
                None
                if row is None
                else self._finding_occurrence_from_row(
                    self._connection,
                    row,
                    replayed=False,
                )
            )

    def has_discovery_occurrence_for_revision(
        self,
        revision_id: SourceRevisionId,
    ) -> bool:
        with self._lock:
            return self._connection.execute(
                "SELECT 1 FROM discovery_occurrences WHERE revision_id=? LIMIT 1",
                (str(revision_id),),
            ).fetchone() is not None



__all__ = ["_CheckAdmissionLookupMixin"]
