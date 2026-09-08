from __future__ import annotations

import json
from types import SimpleNamespace

from newsroom.authority import EventId, ObjectAdmissionId, UtcTimestamp
from newsroom.control_plane.native_evidence import (
    DependencyAssessment,
    NativeEvidenceController,
    NativeEvidenceSource,
    PublicationRightsAssessment,
)
from newsroom.control_plane.graphiti_operational_readiness import _source_requests
from newsroom.control_plane.native_progress import NativeRevisionJournal
from newsroom.control_plane.native_publication import NativePublicationContinuation
from newsroom.control_plane.store import connect
from newsroom.increment10.editorial import (
    EditorialPolicyDecision,
    SourceCurrentness,
    SourceIntegrity,
)
from newsroom.tests.authority_helpers import proof
from newsroom.tests.test_native_graphiti import _native
from newsroom.tests.test_graphiti_operational_readiness import _rights
from newsroom.sources.record_models import SourceDefinitionVersion


_DIGEST = "sha256:" + "a" * 64
_CHECKS = (
    "ACCESS_COMPLETE",
    "ENCODING_VALID",
    "EXTRACTION_COMPLETE",
    "NOT_PAYWALL_FRAGMENT",
    "NOT_TRUNCATED",
    "VERSION_UNAMBIGUOUS",
)


def _decision(package_id):
    return EditorialPolicyDecision.create(
        candidate_version_id="candidate-version",
        candidate_version_digest=_DIGEST,
        governing_manifest_digest=_DIGEST,
        package_admission_id=package_id,
        package_digest=_DIGEST,
        policy_bundle_digest=_DIGEST,
        evaluated_at="2026-09-08T12:03:00Z",
        currentness=(SourceCurrentness(
            "source", "definition", _DIGEST, "CURRENT_VERSION",
            "2026-09-08T12:00:00Z", "2026-09-08T12:01:00Z", None,
            "version", _DIGEST, _DIGEST, "PASS", "CURRENT_VERSION_CONFIRMED",
        ),),
        integrity=(SourceIntegrity(
            "source", ObjectAdmissionId.new(), _DIGEST, _CHECKS,
            "PASS", "INDEPENDENT_ACQUISITION_VERIFIED",
        ),),
        evidence_gate_results=(
            ("CLAIM_TRACEABILITY", "PASS"),
            ("EVIDENCE_SUFFICIENCY", "PASS"),
            ("SOURCE_AUTHORITY", "PASS"),
        ),
    )


def _source(unit):
    request = _source_requests(unit, _rights())[1]
    return NativeEvidenceSource(
        unit,
        SourceDefinitionVersion(
            request,
            EventId.new(),
            1,
            UtcTimestamp.parse("2026-09-08T12:00:00Z"),
            request.digest,
        ),
        PublicationRightsAssessment.create(
            decision="PERMITTED",
            permitted_use="PUBLICATION_EVIDENCE",
            policy_digest=_DIGEST,
            evidence_digest=_DIGEST,
        ),
        DependencyAssessment.create(
            dependency_status="RESOLVED",
            evidential_origin_id="origin",
            originating_report_id="origin",
            evidence_digest=_DIGEST,
        ),
    )


class _Authority:
    def __init__(self):
        self.receives = 0

    def candidate_version(self, _version_id):
        return SimpleNamespace(
            governing_manifest=SimpleNamespace(canonical_digest=_DIGEST)
        )

    def receive_evidence_intake(self, _ingress, **_request):
        self.receives += 1
        return SimpleNamespace(receipt_id="intake-receipt")


class _Publication:
    def __init__(self):
        self.calls = 0

    def advance(self, *_args, **_kwargs):
        self.calls += 1
        receipt = lambda name: SimpleNamespace(event_id=name)
        return SimpleNamespace(
            story_receipt=receipt("story-event"),
            publication_receipt=receipt("publication-event"),
            attempt_receipt=receipt("attempt-event"),
            evidence_receipt=receipt("evidence-event"),
            read_proof=object(),
        )


class _Reader:
    def acknowledged_rows(self):
        return SimpleNamespace(rows=(object(),))

    def close(self):
        return None


def test_continuation_retains_times_and_replays_without_evidence_redispatch(
    tmp_path, monkeypatch
) -> None:
    unit = _native()
    connection = connect(str(tmp_path / "private.sqlite3"))
    journal = NativeRevisionJournal(connection)
    journal.land((unit,))
    journal.advance(
        unit.revision_id,
        stage="CANDIDATE_ADMITTED",
        facts={"candidate_version_id": "candidate-version", "graphiti_receipts": [{}]},
    )
    package_id = ObjectAdmissionId.new()
    decision = _decision(package_id)
    evidence_calls = []
    evidence = object.__new__(NativeEvidenceController)

    def acquire(_self, **_request):
        evidence_calls.append("acquired")
        return SimpleNamespace(
            retained=SimpleNamespace(package_admission_id=package_id),
            editorial_decision=decision,
            acquisition_receipt_digests=(_DIGEST,),
        )

    monkeypatch.setattr(NativeEvidenceController, "acquire_and_retain", acquire)
    monkeypatch.setattr(
        "newsroom.control_plane.native_publication.open_private_serving_read_port",
        lambda *_args, **_kwargs: _Reader(),
    )
    authority, publication = _Authority(), _Publication()
    runtime = SimpleNamespace(
        authority=authority,
        ingress=object(),
        publication=publication,
        proof=proof(),
        policies=SimpleNamespace(publication=SimpleNamespace(
            target_path=tmp_path / "serving.sqlite3",
            target_id="private",
            target_context_digest=_DIGEST,
        )),
    )
    times = iter((
        UtcTimestamp.parse("2026-09-08T12:00:00Z"),
        UtcTimestamp.parse("2026-09-08T12:01:00Z"),
        UtcTimestamp.parse("2026-09-08T12:04:00Z"),
        UtcTimestamp.parse("2026-09-08T12:05:00Z"),
    ))
    continuation = NativePublicationContinuation(
        journal=journal,
        runtime=runtime,
        evidence_controller=evidence,
        sources={unit.revision_id: (_source(unit),)},
        clock=lambda: next(times),
    )

    first = continuation.advance(
        revision_id=unit.revision_id, candidate_version_id="candidate-version"
    )
    replay = continuation.advance(
        revision_id=unit.revision_id, candidate_version_id="candidate-version"
    )

    assert first.state == replay.state == "ACKNOWLEDGED"
    assert authority.receives == 1
    assert evidence_calls == ["acquired"]
    assert publication.calls == 2
    retained = journal.progress[unit.revision_id]
    assert retained["stage"] == "ACKNOWLEDGED"
    assert retained["facts"]["intake_received_epoch_seconds"] == 1788868800
    assert retained["facts"]["assessment_started_at"] == "2026-09-08T12:01:00.000000Z"
    assert retained["facts"]["editorial_decision"] == json.loads(
        decision.canonical_bytes()
    )
    assert retained["facts"]["publication_applied_at"] == "2026-09-08T12:04:00.000000Z"
    assert retained["facts"]["publication_observed_at"] == "2026-09-08T12:05:00.000000Z"
    assert retained["facts"]["graphiti_receipts"] == [{}]
    connection.close()


def test_started_acquisition_without_result_holds_without_redispatch(
    tmp_path, monkeypatch
) -> None:
    unit = _native()
    connection = connect(str(tmp_path / "private.sqlite3"))
    journal = NativeRevisionJournal(connection)
    journal.land((unit,))
    journal.advance(unit.revision_id, stage="ASSESSMENT_STARTED", facts={
        "candidate_version_id": "candidate-version",
        "intake_receipt_id": "intake-receipt",
        "assessment_started_at": "2026-09-08T12:01:00Z",
    })
    evidence = object.__new__(NativeEvidenceController)
    monkeypatch.setattr(
        NativeEvidenceController,
        "acquire_and_retain",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("redispatched")),
    )
    runtime = SimpleNamespace(
        authority=_Authority(), ingress=object(), publication=_Publication(),
        proof=proof(), policies=SimpleNamespace(publication=object()),
    )
    continuation = NativePublicationContinuation(
        journal=journal, runtime=runtime, evidence_controller=evidence,
        sources={unit.revision_id: (_source(unit),)},
    )

    result = continuation.advance(
        revision_id=unit.revision_id, candidate_version_id="candidate-version"
    )

    assert result.state == "ASSESSMENT_INTERRUPTED"
    assert journal.progress[unit.revision_id]["stage"] == "ASSESSMENT_INTERRUPTED"
    connection.close()
