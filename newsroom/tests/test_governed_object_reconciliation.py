from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from newsroom.authority import ObjectAdmissionRequest, ObjectLifecycleError, ObjectLimits
from newsroom.authority._blob_store import _BlobStore

from .authority_helpers import proof
from .authority_object_helpers import open_object_system


def test_reconciliation_failure_releases_writer_lock(tmp_path: Path) -> None:
    with open_object_system(tmp_path) as system:
        admitted = system.objects.admit(
            ObjectAdmissionRequest(
                admission_type="source.capture", idempotency_key="reconcile"
            ),
            BytesIO(b"recoverable bytes"),
            proof=proof(),
        )

    hexadecimal = admitted.blob_digest.removeprefix("sha256:")
    path = tmp_path / "objects" / "sha256" / hexadecimal[:2] / hexadecimal[2:]
    path.unlink()
    with pytest.raises(ObjectLifecycleError, match="missing or corrupt"):
        open_object_system(tmp_path)

    # The failed constructor must have released both SQLite and flock ownership.
    limits = ObjectLimits(
        global_max_bytes=1024,
        class_max_bytes={"source_capture": 512},
        max_read_bytes=512,
        io_chunk_bytes=32,
    )
    blob_store = _BlobStore(tmp_path / "objects", limits=limits)
    staged = blob_store.stage(BytesIO(b"recoverable bytes"), object_class="source_capture")
    assert staged.blob_digest == admitted.blob_digest
    blob_store.install(staged)
    with open_object_system(tmp_path):
        pass
