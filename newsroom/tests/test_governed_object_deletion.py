from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from newsroom.authority import (
    ObjectAdmissionRequest,
    ObjectHydrationDenied,
)
from newsroom.authority._blob_store import _BlobStore

from .authority_helpers import proof
from .authority_object_helpers import open_object_system


def _admit(system, *, key: str = "admit"):
    return system.objects.admit(
        ObjectAdmissionRequest(
            admission_type="source.capture", idempotency_key=key
        ),
        BytesIO(b"deletable bytes"),
        proof=proof(),
    )


def test_recovery_pin_delays_physical_deletion_but_blocks_hydration(
    tmp_path: Path,
) -> None:
    with open_object_system(tmp_path) as system:
        admitted = _admit(system)
        pin_id = system.objects.pin_recovery(
            admitted.blob_digest,
            reason_code="BACKUP_SNAPSHOT",
            proof=proof(),
        )
        pending = system.objects.delete_blob(
            admitted.blob_digest,
            reason_code="RIGHTS_DELETION",
            proof=proof(),
        )
        assert pending.completed is False
        with pytest.raises(ObjectHydrationDenied):
            system.objects.hydrate(
                admitted.admission_id,
                purpose="project.discovery",
                max_bytes=64,
                proof=proof(),
            )
        hexadecimal = admitted.blob_digest.removeprefix("sha256:")
        path = tmp_path / "objects" / "sha256" / hexadecimal[:2] / hexadecimal[2:]
        assert path.exists()
        system.objects.release_recovery_pin(pin_id, proof=proof())
        completed = system.objects.delete_blob(
            admitted.blob_digest,
            reason_code="RIGHTS_DELETION",
            proof=proof(),
        )
        assert completed.completed is True
        assert not path.exists()
        assert [event.event_type for event in system.events.after(0, proof=proof())] == [
            "governed.object.admission.activated",
            "governed.blob.deletion_requested",
            "governed.blob.deleted",
        ]


def test_deletion_survives_reopen_and_cannot_resurrect_bytes(tmp_path: Path) -> None:
    with open_object_system(tmp_path) as system:
        admitted = _admit(system)
        completed = system.objects.delete_blob(
            admitted.blob_digest,
            reason_code="PRIVACY_DELETION",
            proof=proof(),
        )
        assert completed.completed
    with open_object_system(tmp_path) as reopened:
        with pytest.raises(ObjectHydrationDenied):
            reopened.objects.hydrate(
                admitted.admission_id,
                purpose="project.discovery",
                max_bytes=64,
                proof=proof(),
            )
        assert [event.event_type for event in reopened.events.after(0, proof=proof())][-2:] == [
            "governed.blob.deletion_requested",
            "governed.blob.deleted",
        ]


def test_gc_derives_orphan_liveness_from_authority_not_caller_digest_set(
    tmp_path: Path,
) -> None:
    captured: list[_BlobStore] = []

    def factory(root: Path, *, limits):
        store = _BlobStore(root, limits=limits)
        captured.append(store)
        return store

    with open_object_system(tmp_path, blob_store_factory=factory) as system:
        staged = captured[0].stage(BytesIO(b"crash orphan"), object_class="source_capture")
        digest = staged.blob_digest
        captured[0].install(staged)
        removed = system.objects.collect_garbage(
            grace_seconds=0,
            proof=proof(),
        )
        assert removed == (digest,)
        assert not captured[0].path_for(digest).exists()
