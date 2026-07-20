from __future__ import annotations

from pathlib import Path

import pytest

from newsroom.authority import (
    DeletionState,
    HydrationRequest,
    ObjectHydrationDenied,
    ObjectLifecycleError,
)

from .authority_a2b_helpers import admit, open_object_system
from .authority_helpers import proof


def test_ordered_lifecycle_events_and_deletion_non_resurrection(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    system = open_object_system(database, object_root=object_root)
    admission = admit(system, data=b"delete me").admission
    activation_event = str(admission.activation_event_id)
    system.objects.revoke(
        admission.admission_id,
        reason_code="RIGHTS_REVOKED",
        idempotency_key="revoke",
        proof=proof(),
    )
    deletion = system.objects.request_deletion(
        admission.blob.blob_digest,
        reason_code="RIGHTS_DELETE",
        idempotency_key="delete-request",
        proof=proof(),
    )
    requested_event = str(deletion.event_id)
    tombstoned = system.objects.tombstone(
        deletion.deletion_id,
        reason_code="TOMBSTONE",
        idempotency_key="tombstone",
        proof=proof(),
    )
    assert tombstoned.state is DeletionState.TOMBSTONED
    with pytest.raises(Exception):
        system.objects.hydrate(
            HydrationRequest(admission.admission_id, "project.discovery"),
            proof=proof(),
        )
    completed = system.objects.complete_deletion(
        deletion.deletion_id,
        idempotency_key="complete",
        proof=proof(),
    )
    assert completed.state is DeletionState.PHYSICALLY_REMOVED
    events = system.events.after(0, limit=1000, proof=proof())
    types = [event.event_type for event in events]
    assert types.count("governed_object.admission.activated") == 1
    assert types.count("governed_object.admission.revoked") == 1
    assert types.count("governed_blob.deletion.requested") == 1
    assert types.count("governed_blob.deletion.tombstoned") == 1
    assert types.count("governed_blob.deletion.completed") == 1
    assert activation_event in {event.event_id for event in events}
    assert requested_event in {event.event_id for event in events}
    system.close()

    # Authority reopens without bytes and without resurrecting hydratable state.
    reopened = open_object_system(database, object_root=object_root)
    try:
        with pytest.raises((ObjectHydrationDenied, Exception)):
            reopened.objects.hydrate(
                HydrationRequest(admission.admission_id, "project.discovery"),
                proof=proof(),
            )
        assert reopened.objects.request_deletion(
            admission.blob.blob_digest,
            reason_code="RIGHTS_DELETE",
            idempotency_key="delete-request",
            proof=proof(),
        ).state is DeletionState.PHYSICALLY_REMOVED
    finally:
        reopened.close()


def test_requested_and_failed_never_allow_unlink(tmp_path: Path) -> None:
    system = open_object_system(tmp_path / "authority.sqlite3")
    try:
        admission = admit(system).admission
        deletion = system.objects.request_deletion(
            admission.blob.blob_digest,
            reason_code="DELETE",
            idempotency_key="request",
            proof=proof(),
        )
        assert deletion.state is DeletionState.REQUESTED
        with pytest.raises(ObjectLifecycleError, match="TOMBSTONED"):
            system.objects.complete_deletion(
                deletion.deletion_id,
                idempotency_key="too-early",
                proof=proof(),
            )
    finally:
        system.close()


def test_recovery_pin_blocks_physical_removal_without_restoring_hydration(
    tmp_path: Path,
) -> None:
    system = open_object_system(tmp_path / "authority.sqlite3")
    try:
        admission = admit(system).admission
        pin = system.objects.create_recovery_pin(
            admission.blob.blob_digest,
            reason_code="BACKUP_CUTOFF",
            idempotency_key="pin",
            proof=proof(),
        )
        system.objects.revoke(
            admission.admission_id,
            reason_code="REVOKED",
            idempotency_key="revoke",
            proof=proof(),
        )
        deletion = system.objects.request_deletion(
            admission.blob.blob_digest,
            reason_code="DELETE",
            idempotency_key="request",
            proof=proof(),
        )
        system.objects.tombstone(
            deletion.deletion_id,
            reason_code="TOMBSTONE",
            idempotency_key="tombstone",
            proof=proof(),
        )
        with pytest.raises((ObjectHydrationDenied, Exception)):
            system.objects.hydrate(
                HydrationRequest(admission.admission_id, "project.discovery"),
                proof=proof(),
            )
        with pytest.raises(ObjectLifecycleError, match="pin"):
            system.objects.complete_deletion(
                deletion.deletion_id,
                idempotency_key="complete-blocked",
                proof=proof(),
            )
        released = system.objects.release_recovery_pin(
            pin.pin_id,
            reason_code="BACKUP_RELEASED",
            idempotency_key="release",
            proof=proof(),
        )
        assert not released.active
        completed = system.objects.complete_deletion(
            deletion.deletion_id,
            idempotency_key="complete",
            proof=proof(),
        )
        assert completed.state is DeletionState.PHYSICALLY_REMOVED
    finally:
        system.close()
