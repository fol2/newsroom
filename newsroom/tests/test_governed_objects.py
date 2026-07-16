from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import os

import pytest

from newsroom.authority import (
    GovernedObjectStore,
    ObjectAdmissionError,
    ObjectIntegrityError,
    ObjectStoreError,
    RightsStatus,
    UtcTimestamp,
    digest_bytes,
)

_FIXED_TIME = UtcTimestamp(datetime(2026, 7, 16, 19, 0, tzinfo=UTC))


def test_install_is_content_addressed_idempotent_and_verified(tmp_path: Path) -> None:
    store = GovernedObjectStore(tmp_path / "objects")
    data = b"governed bytes"

    first = store.install(
        data,
        object_class="fixture.capture",
        rights_status=RightsStatus.PERMITTED,
        security_scope="authority.internal",
        retention_scope="test.short",
        installed_at=_FIXED_TIME,
    )
    second = store.install(
        data,
        object_class="fixture.capture",
        rights_status=RightsStatus.PERMITTED,
        security_scope="authority.internal",
        retention_scope="test.short",
        installed_at=_FIXED_TIME,
    )

    assert first.digest == second.digest == digest_bytes(data)
    assert store.read(first.digest) == data
    assert store.verify(first.digest) == len(data)


def test_prohibited_or_indeterminate_rights_fail_before_install(tmp_path: Path) -> None:
    store = GovernedObjectStore(tmp_path / "objects")

    for status in (
        RightsStatus.PROHIBITED,
        RightsStatus.REVIEW_REQUIRED,
        RightsStatus.EXPIRED,
        RightsStatus.CONFLICTING,
        RightsStatus.UNSUPPORTED,
    ):
        with pytest.raises(ObjectAdmissionError):
            store.install(
                f"{status.value}-bytes".encode(),
                object_class="fixture.capture",
                rights_status=status,
                security_scope="authority.internal",
                retention_scope="test.short",
                installed_at=_FIXED_TIME,
            )

    assert not (tmp_path / "objects" / "sha256").exists()


def test_corruption_is_detected(tmp_path: Path) -> None:
    store = GovernedObjectStore(tmp_path / "objects")
    installed = store.install(
        b"original",
        object_class="fixture.capture",
        rights_status=RightsStatus.RESTRICTED,
        security_scope="authority.restricted",
        retention_scope="test.short",
        installed_at=_FIXED_TIME,
    )
    store.path_for(installed.digest).write_bytes(b"changed")

    with pytest.raises(ObjectIntegrityError):
        store.verify(installed.digest)
    with pytest.raises(ObjectIntegrityError):
        store.install(
            b"original",
            object_class="fixture.capture",
            rights_status=RightsStatus.RESTRICTED,
            security_scope="authority.restricted",
            retention_scope="test.short",
            installed_at=_FIXED_TIME,
        )


def test_orphan_collection_respects_references_and_grace_period(tmp_path: Path) -> None:
    store = GovernedObjectStore(tmp_path / "objects")
    referenced = store.install(
        b"referenced",
        object_class="fixture.capture",
        rights_status=RightsStatus.PERMITTED,
        security_scope="authority.internal",
        retention_scope="test.short",
        installed_at=_FIXED_TIME,
    )
    orphan = store.install(
        b"orphan",
        object_class="fixture.capture",
        rights_status=RightsStatus.PERMITTED,
        security_scope="authority.internal",
        retention_scope="test.short",
        installed_at=_FIXED_TIME,
    )
    recent = store.install(
        b"recent",
        object_class="fixture.capture",
        rights_status=RightsStatus.PERMITTED,
        security_scope="authority.internal",
        retention_scope="test.short",
        installed_at=_FIXED_TIME,
    )

    old_epoch = 1_000.0
    os.utime(store.path_for(referenced.digest), (old_epoch, old_epoch))
    os.utime(store.path_for(orphan.digest), (old_epoch, old_epoch))
    recent_epoch = 2_000.0
    os.utime(store.path_for(recent.digest), (recent_epoch, recent_epoch))

    removed = store.collect_orphans(
        referenced_digests={referenced.digest},
        grace_seconds=500,
        now_epoch=2_100.0,
    )

    assert removed == (orphan.digest,)
    assert store.read(referenced.digest) == b"referenced"
    assert store.read(recent.digest) == b"recent"
    assert not store.path_for(orphan.digest).exists()



def test_interrupted_install_leaves_no_governed_reference_or_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = GovernedObjectStore(tmp_path / "objects")
    data = b"interrupted"
    digest = digest_bytes(data)

    def fail_link(source: object, target: object) -> None:
        raise OSError("simulated link failure")

    monkeypatch.setattr(os, "link", fail_link)
    with pytest.raises(ObjectStoreError):
        store.install(
            data,
            object_class="fixture.capture",
            rights_status=RightsStatus.PERMITTED,
            security_scope="authority.internal",
            retention_scope="test.short",
            installed_at=_FIXED_TIME,
        )

    assert not store.path_for(digest).exists()
    parent = store.path_for(digest).parent
    assert not list(parent.glob(".install-*"))
