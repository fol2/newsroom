from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path

import pytest

from newsroom.authority import (
    AggregateId, ObjectAdmissionPayload, ObjectAdmissionRequest, ObjectIntegrityError,
    ObjectLimitError, ObjectLimits, SemanticCommand,
)
from newsroom.authority._blob_store import _BlobStore
from .authority_helpers import proof
from .authority_object_helpers import open_object_system


class FailingDirectoryFsyncStore(_BlobStore):
    def __init__(self, root: Path, *, limits: ObjectLimits) -> None:
        # Pre-created directories avoid constructor fsync so the injected fault
        # occurs at the authoritative install boundary.
        root.mkdir(parents=True, mode=0o700)
        (root / ".staging").mkdir(mode=0o700)
        (root / "sha256").mkdir(mode=0o700)
        super().__init__(
            root,
            limits=limits,
            directory_fsync=lambda path: (_ for _ in ()).throw(
                OSError(f"fsync failed for {path}")
            ),
        )


class MutatingAfterPinStore(_BlobStore):
    mutate_on_next_pin = False

    def pin(self, blob_digest: str, *, expected_size: int | None = None):
        pinned = super().pin(blob_digest, expected_size=expected_size)
        if self.mutate_on_next_pin:
            self.mutate_on_next_pin = False
            path = self.path_for(blob_digest)
            os.chmod(path, 0o600)
            path.write_bytes(b"tampered!!!")
            os.chmod(path, 0o400)
        return pinned


def test_oversized_stream_fails_without_staging_or_install(tmp_path: Path) -> None:
    limits = ObjectLimits(
        global_max_bytes=16,
        class_max_bytes={"source_capture": 8},
        max_read_bytes=8,
        io_chunk_bytes=4,
    )
    with open_object_system(tmp_path, limits=limits) as system:
        with pytest.raises(ObjectLimitError, match="hard limit"):
            system.objects.admit(
                ObjectAdmissionRequest(
                    admission_type="source.capture", idempotency_key="oversize"
                ),
                BytesIO(b"123456789"),
                proof=proof(),
            )
        assert list((tmp_path / "objects" / ".staging").iterdir()) == []
        assert list((tmp_path / "objects" / "sha256").rglob("*")) == []


def test_directory_fsync_failure_is_not_reported_as_success(tmp_path: Path) -> None:
    with open_object_system(
        tmp_path,
        blob_store_factory=FailingDirectoryFsyncStore,
    ) as system:
        with pytest.raises(OSError, match="fsync failed"):
            system.objects.admit(
                ObjectAdmissionRequest(
                    admission_type="source.capture", idempotency_key="fsync-fail"
                ),
                BytesIO(b"content"),
                proof=proof(),
            )
        assert system.events.after(0, proof=proof()) == ()


def test_installed_blob_is_read_only(tmp_path: Path) -> None:
    with open_object_system(tmp_path) as system:
        receipt = system.objects.admit(
            ObjectAdmissionRequest(
                admission_type="source.capture", idempotency_key="mode"
            ),
            BytesIO(b"content"),
            proof=proof(),
        )
        hexadecimal = receipt.blob_digest.removeprefix("sha256:")
        path = tmp_path / "objects" / "sha256" / hexadecimal[:2] / hexadecimal[2:]
        assert path.stat().st_mode & 0o222 == 0


def test_mutation_after_initial_pin_is_detected_before_object_command_commit(
    tmp_path: Path,
) -> None:
    captured: list[MutatingAfterPinStore] = []

    def factory(root: Path, *, limits: ObjectLimits):
        store = MutatingAfterPinStore(root, limits=limits)
        captured.append(store)
        return store

    with open_object_system(tmp_path, blob_store_factory=factory) as system:
        receipt = system.objects.admit(
            ObjectAdmissionRequest(
                admission_type="source.capture", idempotency_key="mutate"
            ),
            BytesIO(b"original!!!"),
            proof=proof(),
        )
        captured[0].mutate_on_next_pin = True
        with pytest.raises(ObjectIntegrityError, match="changed"):
            system.commands.execute(
                SemanticCommand(
                    command_type="record.object",
                    aggregate_id=AggregateId.new(),
                    expected_aggregate_version=0,
                    payload=ObjectAdmissionPayload(receipt.admission_id),
                    idempotency_key="mutated-command",
                ),
                proof=proof(),
            )
        assert [event.event_type for event in system.events.after(0, proof=proof())] == [
            "governed.object.admission.activated"
        ]
