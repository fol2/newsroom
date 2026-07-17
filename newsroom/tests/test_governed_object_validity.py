from __future__ import annotations

from datetime import timedelta
from io import BytesIO
from pathlib import Path

import pytest

from newsroom.authority import ObjectAdmissionRequest, UtcTimestamp
from .authority_helpers import FIXED_NOW, proof
from .authority_object_helpers import open_object_system


class MutableClock:
    def __init__(self) -> None:
        self.current = FIXED_NOW

    def __call__(self) -> UtcTimestamp:
        return self.current


class AdvancingStream(BytesIO):
    def __init__(self, value: bytes, *, clock: MutableClock) -> None:
        super().__init__(value)
        self.clock = clock
        self.advanced = False

    def read(self, size: int = -1) -> bytes:
        result = super().read(size)
        if result == b"" and not self.advanced:
            self.advanced = True
            self.clock.current = UtcTimestamp(
                self.clock.current.value + timedelta(seconds=2)
            )
        return result


def test_rights_expiry_between_authorization_and_commit_blocks_admission(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    with open_object_system(
        tmp_path,
        rights_validity_seconds=1,
        clock=clock,
    ) as system:
        with pytest.raises(PermissionError, match="RIGHTS_EXPIRED"):
            system.objects.admit(
                ObjectAdmissionRequest(
                    admission_type="source.capture", idempotency_key="expires"
                ),
                AdvancingStream(b"content", clock=clock),
                proof=proof(),
            )
        assert system.events.after(0, proof=proof()) == ()
