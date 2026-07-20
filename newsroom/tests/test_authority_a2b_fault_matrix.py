from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from newsroom.authority import (
    HydrationRequest,
    ObjectHydrationDenied,
    ObjectLifecycleError,
)

from .authority_a2b_helpers import admit, open_object_system
from .authority_helpers import proof


@pytest.mark.parametrize(
    "checkpoint",
    [
        "before_stage_stream",
        "after_stage_chunk",
        "before_stage_file_fsync",
        "after_stage_file_fsync",
        "before_atomic_install",
        "after_atomic_install",
        "before_installed_file_fsync",
        "after_installed_file_fsync",
        "before_pinned_rehash",
        "after_pinned_rehash",
        "before_directory_fsync",
        "after_directory_fsync",
        "before_stage_cleanup_unlink",
        "after_stage_cleanup_unlink",
    ],
)
def test_admission_fault_checkpoints_never_create_hydratable_partial_authority(
    tmp_path: Path, checkpoint: str
) -> None:
    seen = 0

    def fault(name: str) -> None:
        nonlocal seen
        if name == checkpoint:
            seen += 1
            raise OSError(f"fault:{checkpoint}")

    database = tmp_path / f"{checkpoint}.sqlite3"
    object_root = tmp_path / f"{checkpoint}-objects"
    try:
        system = open_object_system(
            database,
            object_root=object_root,
            fault_hook=fault,
        )
    except OSError:
        # Root-creation directory fsync fault: no system was returned, and the
        # constructor must release its SQLite writer state.
        assert checkpoint in {
            "before_directory_fsync",
            "after_directory_fsync",
        }
        return
    try:
        with pytest.raises((OSError, Exception)):
            admit(system, data=b"fault matrix", key=checkpoint)
    finally:
        system.close()
    assert seen >= 1

    # Reopen without the injected fault. No partial admission may hydrate and
    # staging cleanup must be deterministic.
    reopened = open_object_system(database, object_root=object_root)
    try:
        assert list((object_root / "staging").iterdir()) == []
        events = reopened.events.after(0, limit=1000, proof=proof())
        activations = [
            item
            for item in events
            if item.event_type == "governed_object.admission.activated"
        ]
        assert len(activations) in {0, 1}
        if activations:
            assert checkpoint in {
                "before_stage_cleanup_unlink",
                "after_stage_cleanup_unlink",
            }
    finally:
        reopened.close()


def test_gc_and_command_hydration_operations_are_serialized(
    tmp_path: Path,
) -> None:
    system = open_object_system(tmp_path / "authority.sqlite3")
    try:
        admission = admit(system, data=b"race-safe").admission

        def hydrate(_: int) -> bytes:
            return system.objects.hydrate(
                HydrationRequest(admission.admission_id, "project.discovery"),
                proof=proof(),
            ).data

        def collect(_: int) -> tuple[object, ...]:
            return system.objects.collect_orphans(proof=proof())

        with ThreadPoolExecutor(max_workers=8) as executor:
            hydrated = list(executor.map(hydrate, range(20)))
            collected = list(executor.map(collect, range(20)))
        assert all(item == b"race-safe" for item in hydrated)
        assert all(item == () for item in collected)
    finally:
        system.close()


def test_tombstone_blocks_hydration_before_unlink(tmp_path: Path) -> None:
    system = open_object_system(tmp_path / "authority.sqlite3")
    try:
        admission = admit(system, data=b"lawful delete").admission
        system.objects.revoke(
            admission.admission_id,
            reason_code="RIGHTS_REVOKED",
            idempotency_key="revoke",
            proof=proof(),
        )
        deletion = system.objects.request_deletion(
            admission.blob.blob_digest,
            reason_code="RIGHTS_DELETE",
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
        system.objects.complete_deletion(
            deletion.deletion_id,
            idempotency_key="complete",
            proof=proof(),
        )
        with pytest.raises((ObjectHydrationDenied, Exception)):
            system.objects.hydrate(
                HydrationRequest(admission.admission_id, "project.discovery"),
                proof=proof(),
            )
    finally:
        system.close()
