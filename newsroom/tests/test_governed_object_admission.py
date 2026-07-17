from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from newsroom.authority import (
    AggregateId,
    ObjectAdmissionDenied,
    ObjectAdmissionPayload,
    ObjectAdmissionRequest,
    ObjectHydrationDenied,
    SemanticCommand,
)

from .authority_helpers import proof
from .authority_object_helpers import open_object_system


def test_caller_cannot_self_certify_prohibited_bytes_and_denial_precedes_staging(
    tmp_path: Path,
) -> None:
    with open_object_system(tmp_path, rights_allowed=False) as system:
        assert "rights_status" not in ObjectAdmissionRequest.__dataclass_fields__
        with pytest.raises(ObjectAdmissionDenied, match="RIGHTS_PROHIBITED"):
            system.objects.admit(
                ObjectAdmissionRequest(
                    admission_type="source.capture", idempotency_key="deny-1"
                ),
                BytesIO(b"protected"),
                proof=proof(),
            )
        assert list((tmp_path / "objects" / ".staging").iterdir()) == []


def test_same_bytes_support_distinct_governed_admissions(tmp_path: Path) -> None:
    with open_object_system(tmp_path) as system:
        first = system.objects.admit(
            ObjectAdmissionRequest(
                admission_type="source.capture", idempotency_key="admit-1"
            ),
            BytesIO(b"same bytes"),
            proof=proof(),
        )
        second = system.objects.admit(
            ObjectAdmissionRequest(
                admission_type="source.capture", idempotency_key="admit-2"
            ),
            BytesIO(b"same bytes"),
            proof=proof(),
        )
        assert first.blob_digest == second.blob_digest
        assert first.admission_id != second.admission_id
        assert first.rights_decision_id != second.rights_decision_id
        assert [event.event_type for event in system.events.after(0, proof=proof())] == [
            "governed.object.admission.activated",
            "governed.object.admission.activated",
        ]


def test_admission_replay_stages_nothing_and_verifies_original_blob(
    tmp_path: Path,
) -> None:
    request = ObjectAdmissionRequest(
        admission_type="source.capture", idempotency_key="admit-replay"
    )
    with open_object_system(tmp_path) as system:
        first = system.objects.admit(request, BytesIO(b"content"), proof=proof())
        second = system.objects.admit(
            request,
            BytesIO(b"different bytes that must never be staged"),
            proof=proof(),
        )
        assert second.replayed is True
        assert second.admission_id == first.admission_id
        assert second.blob_digest == first.blob_digest
        assert list((tmp_path / "objects" / ".staging").iterdir()) == []


def test_object_backed_command_and_authenticated_hydration(tmp_path: Path) -> None:
    with open_object_system(tmp_path) as system:
        admitted = system.objects.admit(
            ObjectAdmissionRequest(
                admission_type="source.capture", idempotency_key="admit-command"
            ),
            BytesIO(b"source bytes"),
            proof=proof(),
        )
        committed = system.commands.execute(
            SemanticCommand(
                command_type="record.object",
                aggregate_id=AggregateId.new(),
                expected_aggregate_version=0,
                payload=ObjectAdmissionPayload(admitted.admission_id),
                idempotency_key="object-command",
            ),
            proof=proof(),
        )
        hydrated = system.objects.hydrate(
            admitted.admission_id,
            purpose="project.discovery",
            max_bytes=64,
            proof=proof(),
        )
        assert hydrated.bytes_value == b"source bytes"
        assert hydrated.blob_digest == admitted.blob_digest
        events = system.events.after(0, proof=proof())
        assert [event.event_type for event in events] == [
            "governed.object.admission.activated",
            "fixture.object.recorded",
        ]
        assert events[-1].command_id == committed.command_id


def test_revoked_admission_blocks_command_and_hydration(tmp_path: Path) -> None:
    with open_object_system(tmp_path) as system:
        admitted = system.objects.admit(
            ObjectAdmissionRequest(
                admission_type="source.capture", idempotency_key="admit-revoke"
            ),
            BytesIO(b"source bytes"),
            proof=proof(),
        )
        assert system.objects.revoke(admitted.admission_id, proof=proof()) == 2
        with pytest.raises(ValueError, match="not active"):
            system.commands.execute(
                SemanticCommand(
                    command_type="record.object",
                    aggregate_id=AggregateId.new(),
                    expected_aggregate_version=0,
                    payload=ObjectAdmissionPayload(admitted.admission_id),
                    idempotency_key="revoked-command",
                ),
                proof=proof(),
            )
        with pytest.raises(ObjectHydrationDenied):
            system.objects.hydrate(
                admitted.admission_id,
                purpose="project.discovery",
                max_bytes=64,
                proof=proof(),
            )
        assert [event.event_type for event in system.events.after(0, proof=proof())] == [
            "governed.object.admission.activated",
            "governed.object.admission.revoked",
        ]
