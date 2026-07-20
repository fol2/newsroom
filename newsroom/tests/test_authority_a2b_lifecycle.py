from __future__ import annotations

import json
from pathlib import Path

import pytest

from newsroom.authority import (
    DeletionState,
    HydrationRequest,
    ObjectAdmissionRequest,
    ObjectHydrationDenied,
    ObjectLifecycleError,
)

from .authority_a2b_helpers import admit, open_object_system
from .authority_helpers import proof


def installed_path(root: Path, blob_digest: str) -> Path:
    hex_digest = blob_digest.split(":", 1)[1]
    return root / "objects" / hex_digest[:2] / hex_digest


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

    # A filesystem restore or manual mutation must not override the SQLite
    # tombstone.  Reintroduced bytes are deterministically removed on startup.
    deleted_path = installed_path(object_root, admission.blob.blob_digest)
    deleted_path.parent.mkdir(parents=True, exist_ok=True)
    deleted_path.write_bytes(b"resurrected bytes")
    deleted_path.chmod(0o400)

    # Authority reopens without bytes and without resurrecting hydratable state.
    reopened = open_object_system(database, object_root=object_root)
    try:
        class ExplodingSource:
            touched = False

            def read(self, _size: int) -> bytes:
                self.touched = True
                raise AssertionError("committed replay must not touch source")

        source = ExplodingSource()
        replay = reopened.objects.admit(
            ObjectAdmissionRequest("source.capture", "admit-1"),
            source,
            proof=proof(),
        )
        assert replay.replayed is True
        assert source.touched is False
        assert replay.admission.admission_id == admission.admission_id
        # The idempotent result is the immutable activation result.  It does
        # not restore current authority after revocation/deletion.
        assert replay.admission.active
        assert not deleted_path.exists()
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
        with pytest.raises(ObjectLifecycleError, match="deletion history"):
            reopened.objects.request_deletion(
                admission.blob.blob_digest,
                reason_code="DELETE_AGAIN",
                idempotency_key="delete-again",
                proof=proof(),
            )
        with pytest.raises(ObjectLifecycleError, match="integrity-verified"):
            reopened.objects.create_recovery_pin(
                admission.blob.blob_digest,
                reason_code="PIN_DELETED",
                idempotency_key="pin-deleted",
                proof=proof(),
            )
        assert reopened.objects.collect_orphans(proof=proof()) == ()
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


def test_hydration_cutoff_records_a_pending_deletion(tmp_path: Path) -> None:
    system = open_object_system(tmp_path / "authority.sqlite3")
    try:
        admission = admit(system, data=b"read until tombstone").admission
        deletion = system.objects.request_deletion(
            admission.blob.blob_digest,
            reason_code="DELETE_REQUESTED",
            idempotency_key="cutoff-delete",
            proof=proof(),
        )
        hydrated = system.objects.hydrate(
            HydrationRequest(admission.admission_id, "project.discovery"),
            proof=proof(),
        )
        cutoff = json.loads(
            hydrated.decision.state_cutoff_bytes.decode("utf-8")
        )
        assert cutoff["deletion_id"] == str(deletion.deletion_id)
        assert cutoff["deletion_lifecycle_version"] == 1
        assert cutoff["deletion_state"] == "REQUESTED"
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


def test_recovery_pin_can_be_created_after_tombstone_while_bytes_exist(
    tmp_path: Path,
) -> None:
    system = open_object_system(tmp_path / "authority.sqlite3")
    try:
        admission = admit(system, data=b"pinned tombstone").admission
        system.objects.revoke(
            admission.admission_id,
            reason_code="REVOKED",
            idempotency_key="late-pin-revoke",
            proof=proof(),
        )
        deletion = system.objects.request_deletion(
            admission.blob.blob_digest,
            reason_code="DELETE",
            idempotency_key="late-pin-request",
            proof=proof(),
        )
        system.objects.tombstone(
            deletion.deletion_id,
            reason_code="TOMBSTONE",
            idempotency_key="late-pin-tombstone",
            proof=proof(),
        )
        pin = system.objects.create_recovery_pin(
            admission.blob.blob_digest,
            reason_code="BACKUP_AFTER_TOMBSTONE",
            idempotency_key="late-pin",
            proof=proof(),
        )
        with pytest.raises(ObjectLifecycleError, match="pin"):
            system.objects.complete_deletion(
                deletion.deletion_id,
                idempotency_key="late-pin-complete-blocked",
                proof=proof(),
            )
        system.objects.release_recovery_pin(
            pin.pin_id,
            reason_code="BACKUP_COMPLETE",
            idempotency_key="late-pin-release",
            proof=proof(),
        )
        completed = system.objects.complete_deletion(
            deletion.deletion_id,
            idempotency_key="late-pin-complete",
            proof=proof(),
        )
        assert completed.state is DeletionState.PHYSICALLY_REMOVED
    finally:
        system.close()
