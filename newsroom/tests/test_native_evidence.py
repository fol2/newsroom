from __future__ import annotations

from dataclasses import replace

import pytest

from newsroom.authority import EventId, UtcTimestamp
from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
)
from newsroom.control_plane.graphiti_operational_readiness import _source_requests
from newsroom.control_plane.native_evidence import (
    _admit_record,
    AcquiredEvidence,
    AcquiredSourceAssessment,
    DependencyAssessment,
    EvidenceAcquisitionRequest,
    EvidenceAssessor,
    EvidenceTransport,
    IndependentEvidenceAssessment,
    NativeEvidenceController,
    NativeEvidenceHold,
    NativeEvidenceError,
    NativeEvidenceSource,
    PublicationRightsAssessment,
)
from newsroom.control_plane.native_assessor import (
    AutonomousNativeEvidenceAssessor,
    NativeAssessmentExecution,
)
from newsroom.control_plane.native_publication import NativePublicationController
from newsroom.increment10.editorial import SourceCurrentness
from newsroom.increment10.evidence import EvidencePackageError, _base_package
from newsroom.increment10.ingress import open_evidence_intake_ingress
from newsroom.increment10.private_serving import open_private_serving_read_port
from newsroom.sources.record_models import SourceDefinitionVersion
from newsroom.tests.authority_helpers import proof
from newsroom.tests.test_graphiti_operational_readiness import _rights, _unit
from newsroom.tests.test_increment10_editorial import _evidence_facade, _ready_package
from newsroom.tests.test_native_assessor import _model_package_value
from newsroom.tests.test_increment10_ingress import _candidate, _receive
from newsroom.tests.test_increment10_private_serving import _open
from newsroom.tests.test_native_assessor import _model_package_value
from newsroom.tests.test_native_publication import _bindings

NOW = UtcTimestamp.parse("2026-09-02T12:02:00.000000Z")
INTEGRITY = tuple(
    (name, "PASS")
    for name in (
        "ACCESS_COMPLETE",
        "ENCODING_VALID",
        "EXTRACTION_COMPLETE",
        "NOT_PAYWALL_FRAGMENT",
        "NOT_TRUNCATED",
        "VERSION_UNAMBIGUOUS",
    )
)


def test_independent_source_evidence_holds_then_reaches_private_ack(tmp_path) -> None:
    candidate_connection, candidate_port, version = _candidate(tmp_path)
    ingress = open_evidence_intake_ingress(tmp_path / "intake.sqlite3")
    acknowledgement = _receive(
        ingress,
        candidate_connection,
        candidate_port,
        version,
        request_id="request-1",
    )

    def candidate_version(version_id):
        candidate_connection.execute("BEGIN")
        try:
            return candidate_port.require_retained_version_in_transaction(version_id)
        finally:
            candidate_connection.rollback()

    candidate_port = candidate_port._with_bounded_version(candidate_version)
    system, registries, hydration, definitions, commands = _open(
        tmp_path / "objects.sqlite3"
    )
    packages = _evidence_facade(system, ingress, registries)
    passage, assessed_package, records = _ready_package(version)
    source_id = _unit().source_id
    source_record = next(
        item for item in records if item["record_type"] == "SOURCE_RECORD"
    )
    unit = replace(
        _unit(),
        headline="",
        body=passage,
        canonical_url=source_record["canonical_url"],
    )
    unit = replace(
        unit,
        effective_revision=replace(
            unit.effective_revision,
            revision_digest=unit.revision_digest
        ),
    )
    version_request = _source_requests(unit, _rights())[1]
    source_version = SourceDefinitionVersion(
        version_request,
        EventId.new(),
        1,
        NOW,
        version_request.digest,
    )
    transport_digest = "sha256:" + "7" * 64
    currentness_evidence = "sha256:" + "c" * 64
    calls = []
    assessment_markers = []

    def acquired(request):
        body = passage.encode()
        rights_receipt = PublicationRightsAssessment.create(
            decision="PERMITTED",
            permitted_use="PUBLICATION_EVIDENCE",
            policy_digest="sha256:" + "1" * 64,
            evidence_digest="sha256:" + "2" * 64,
        ).record_id
        return AcquiredEvidence.create(
            request_digest=request.digest,
            outcome="COMPLETE",
            canonical_url=unit.canonical_url,
            body=body,
            body_digest=digest_bytes(body),
            publisher=source_record["publisher"],
            responsible_body=source_record["responsible_body"],
            source_type=source_record["source_type"],
            publication_time=source_record["publication_time"],
            source_updated_time=source_record["publication_time"],
            retrieval_time=source_record["retrieval_time"],
            geography=source_record["geography"],
            language=source_record["language"],
            transport_evidence_digest=currentness_evidence,
            currentness_basis="AUTHORITATIVE_CURRENT_CONTENT_ENDPOINT",
            rights_eligibility_digest=digest_canonical(
                {
                    "rights_receipt": rights_receipt,
                    "body_digest": digest_bytes(body),
                    "transport": currentness_evidence,
                    "exclusion_signals": (),
                    "text_only": True,
                }
            ),
            licence_attribution="Contains public sector information licensed",
            exclusion_signals=(),
            text_only=True,
        )

    request = EvidenceAcquisitionRequest(
        source_id,
        unit.authority.definition_id,
        unit.authority.definition_version_id,
        source_version.canonical_digest,
        unit.authority.revision_id,
        unit.canonical_url,
        transport_digest,
    )
    acquisition = acquired(request)

    def acquire(request):
        calls.append(request.digest)
        return acquired(request)

    rights = PublicationRightsAssessment.create(
        decision="PERMITTED",
        permitted_use="PUBLICATION_EVIDENCE",
        policy_digest="sha256:" + "1" * 64,
        evidence_digest="sha256:" + "2" * 64,
    )
    dependency = DependencyAssessment.create(
        dependency_status="RESOLVED",
        evidential_origin_id="origin-1",
        originating_report_id="origin-1",
        evidence_digest="sha256:" + "3" * 64,
    )
    currentness = SourceCurrentness(
        source_id,
        str(version_request.definition_id),
        source_version.canonical_digest,
        "CURRENT_VERSION",
        source_record["publication_time"],
        source_record["retrieval_time"],
        None,
        str(version_request.version_id),
        "sha256:" + "d" * 64,
        currentness_evidence,
        "PASS",
        "CURRENT_VERSION_CONFIRMED",
    )
    source = NativeEvidenceSource(
        unit,
        source_version,
        rights,
        dependency,
    )
    assessed_package = replace(
        assessed_package,
        source_ids=(source_id,),
        governed_claims=tuple(
            replace(
                claim,
                source_ids=(source_id,),
            )
            for claim in assessed_package.governed_claims
        ),
    )
    assessor = AutonomousNativeEvidenceAssessor(
        lambda _prompt: NativeAssessmentExecution(
            canonical_json_bytes(
                {"package": _model_package_value(assessed_package)}
            ).decode(),
            {},
        )
    )
    assessed = assessor(
        version, _base_package(assessed_package), (source,), (acquisition,)
    )
    assert assessed.governed_claims
    assert any(
        claim.rendered_assertion_zh_hant_hk != claim.claim
        for claim in assessed.governed_claims
    )
    assert all(claim.source_authority_decision_ids for claim in assessed.governed_claims)
    assert all(
        record["record_id"] and record.get("claim_digest")
        for record in assessed.assessment_records
        if record["record_type"] == "SEMANTIC_RELATION_EVIDENCE"
    )
    wrong_source = replace(
        assessed_package,
        governed_claims=(
            replace(assessed_package.governed_claims[0], source_ids=("wrong-source",)),
            *assessed_package.governed_claims[1:],
        ),
    )
    with pytest.raises(NativeEvidenceHold, match="ASSESSOR_CLAIM_BINDING_HOLD"):
        AutonomousNativeEvidenceAssessor(
            lambda _prompt: NativeAssessmentExecution(
                canonical_json_bytes(
                    {"package": _model_package_value(wrong_source)}
                ).decode(),
                {},
            )
        )(version, _base_package(assessed_package), (source,), (acquisition,))
    missing_claim = _model_package_value(assessed_package)
    missing_claim["qualification_evidence"][0][
        "governed_claim_id"
    ] = "missing-claim"
    with pytest.raises(EvidencePackageError, match="qualification claim differs"):
        AutonomousNativeEvidenceAssessor(
            lambda _prompt: NativeAssessmentExecution(
                canonical_json_bytes({"package": missing_claim}).decode(), {}
            )
        )(version, _base_package(assessed_package), (source,), (acquisition,))

    def evidence_controller(selected_assessor):
        return NativeEvidenceController(
            objects=system.objects,
            candidate_port=candidate_port,
            evidence_packages=packages,
            transport=EvidenceTransport(acquire),
            assessor=EvidenceAssessor(selected_assessor),
            policy_bundle_digest="sha256:" + "a" * 64,
            transport_policy_digest=transport_digest,
            clock=lambda: UtcTimestamp.parse("2026-09-08T12:02:00Z"),
        )

    candidate_connection.commit()
    negative_value = _model_package_value(assessed_package)
    negative_value["governed_claims"][0]["semantic_relation"][
        "source_polarity"
    ] = "NEGATED"
    negative_assessor = AutonomousNativeEvidenceAssessor(
        lambda _prompt: NativeAssessmentExecution(
            canonical_json_bytes({"package": negative_value}).decode(), {}
        )
    )
    with pytest.raises(EvidencePackageError, match="semantic relation"):
        negative_assessor(
            version, _base_package(assessed_package), (source,), (acquisition,)
        )
    # Keep the downstream defence independent of the now-stricter producer.
    negative = replace(assessed, assessment_records=tuple(
        {**record, "source_polarity": "NEGATED"}
        if record["record_type"] == "SEMANTIC_RELATION_EVIDENCE" else record
        for record in assessed.assessment_records
    ))
    with pytest.raises(NativeEvidenceHold, match="EVIDENCE_VALIDATION_HOLD"):
        evidence_controller(lambda *_args: negative).acquire_and_retain(
            candidate_version_id=version.version_id,
            intake_receipt_id=acknowledgement.receipt_id,
            sources=(source,),
            proof=proof(),
        )
    calls.clear()

    controller = evidence_controller(assessor)
    with pytest.raises(NativeEvidenceHold, match="PUBLICATION_RIGHTS_HOLD"):
        controller.acquire_and_retain(
            candidate_version_id=version.version_id,
            intake_receipt_id=acknowledgement.receipt_id,
            sources=(
                source,
                replace(
                    source,
                    rights=PublicationRightsAssessment.create(
                        decision="HOLD",
                        permitted_use=rights.permitted_use,
                        policy_digest=rights.policy_digest,
                        evidence_digest=rights.evidence_digest,
                    ),
                ),
            ),
            proof=proof(),
        )
    assert calls == []
    evidence = controller.acquire_and_retain(
        candidate_version_id=version.version_id,
        intake_receipt_id=acknowledgement.receipt_id,
        sources=(source,),
        before_assessment=lambda: assessment_markers.append("started"),
        proof=proof(),
    )
    assert len(calls) == 1
    assert assessment_markers == ["started"]
    assert evidence.editorial_decision.evaluated_at == "2026-09-08T12:02:00.000000Z"

    bindings = _bindings(tmp_path, registries, hydration, definitions, commands)
    publisher = NativePublicationController(
        objects=system.objects,
        commands=system.commands,
        events=system.events,
        candidate_port=candidate_port,
        evidence_packages=packages,
        bindings=bindings,
    )
    published = publisher.advance(
        evidence.retained.package_admission_id,
        evidence.editorial_decision,
        expected_story_version=0,
        expected_publication_version=0,
        expected_delivery_evidence_version=0,
        applied_at="2026-07-16T11:00:00Z",
        observed_at="2026-07-16T11:30:00Z",
        proof=proof(),
    )
    reader = open_private_serving_read_port(
        bindings.target_path,
        target_id=bindings.target_id,
        target_context_digest=bindings.target_context_digest,
        proof=published.read_proof,
    )
    assert tuple(row.surface_kind for row in reader.acknowledged_rows().rows) == (
        "ARTICLE",
        "FEED_CARD",
    )
    reader.close()
    publisher.close()
    system.close()
    ingress.close()
    candidate_connection.close()


def test_retained_record_replay_binds_exact_revision_bytes(tmp_path, monkeypatch):
    system, *_ = _open(tmp_path / "records.sqlite3")
    try:
        first = canonical_json_bytes({
            "record_id": "stable-rights-policy", "record_type": "RIGHTS_DECISION",
            "base_package_digest": "sha256:" + "1" * 64,
        })
        second = canonical_json_bytes({
            "record_id": "stable-rights-policy", "record_type": "RIGHTS_DECISION",
            "base_package_digest": "sha256:" + "2" * 64,
        })
        first_id = _admit_record(system.objects, first, proof())
        second_id = _admit_record(system.objects, second, proof())
        assert first_id != second_id
        assert _admit_record(system.objects, first, proof()) == first_id
        assert _admit_record(system.objects, second, proof()) == second_id
        from newsroom.authority import ObjectAdmissionRequest
        stale = system.objects.admit(
            ObjectAdmissionRequest("evidence.record", f"record:{digest_bytes(first)}"),
            first, proof=proof(),
        )
        monkeypatch.setattr(type(system.objects), "admit", lambda *_args, **_kwargs: stale)
        with pytest.raises(NativeEvidenceError, match="record content differs"):
            _admit_record(system.objects, second, proof())
    finally:
        system.close()
