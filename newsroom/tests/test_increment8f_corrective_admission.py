from __future__ import annotations

import json
from dataclasses import replace
from inspect import signature
from types import MappingProxyType

import pytest

import newsroom.increment8.admission as admission_module
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment8.admission import (
    AdmissionError,
    IndependentVerificationEvidence,
    OperationalAdmissionDecision,
    QualificationPacket,
    build_operational_admission_decision,
)
from newsroom.increment8.observability import AlertPriority, HealthVerdict
from newsroom.increment8.operations import CapacityEvidence
from newsroom.increment8.recovery import ReconciliationRun
from newsroom.tests.test_increment8f_admission import (
    _D,
    _D3,
    _capacity,
    _health,
    _observability,
    _packet,
    _reconciliation,
    _security,
)

_D2 = "sha256:" + "2" * 64


@pytest.fixture
def admitted_gate(monkeypatch):
    monkeypatch.setattr(admission_module, "corrective_gate_authorised", lambda _gate: True)


def _rebuilt_packet(packet: QualificationPacket, document: dict) -> QualificationPacket:
    raw = canonical_json_bytes(document)
    payload = document["payload"]
    return QualificationPacket(
        MappingProxyType(payload["evidence_digests"]),
        MappingProxyType(payload["retained_evidence"]),
        raw,
        digest_bytes(raw),
    )


def test_packet_retains_reconstructable_evidence_and_builds_exact_decision(
    tmp_path, admitted_gate
) -> None:
    packet = _packet(tmp_path)
    parameters = signature(admission_module.build_qualification_packet).parameters
    assert "rollback_evidence_digest" not in parameters
    assert "independent_verification_digest" not in parameters
    assert {"rollback_evidence", "independent_verification"} <= set(parameters)
    assert "operational_profile" in parameters
    assert QualificationPacket.from_canonical_bytes(packet.canonical_bytes) == packet
    assert set(packet.retained_evidence) == {
        "release_decision",
        "metric_report",
        "operational_profile",
        "capacity",
        "health_postures",
        "observability",
        "security",
        "reconciliation",
        "backup",
        "restore",
        "restore_reconciliation",
        "fault_runs",
        "handoff_anchor",
        "hardware",
        "cost_licence",
        "rollback_evidence",
        "independent_verification",
    }
    decision = build_operational_admission_decision(
        packet=packet,
        owner_identity_digest=_D3,
        decision_recorded_at_digest=_D,
    )
    assert (
        OperationalAdmissionDecision.from_canonical_bytes(
            decision.canonical_bytes, packet=packet
        )
        == decision
    )


def test_decision_rejects_detached_packet_fields_and_missing_evidence(
    tmp_path, admitted_gate
) -> None:
    packet = _packet(tmp_path)
    detached = replace(
        packet,
        evidence_digests=MappingProxyType(
            {**packet.evidence_digests, "handoff_anchor_digest": _D2}
        ),
    )
    with pytest.raises(AdmissionError, match="qualification packet differs"):
        build_operational_admission_decision(
            packet=detached,
            owner_identity_digest=_D3,
            decision_recorded_at_digest=_D,
        )

    document = json.loads(packet.canonical_bytes)
    del document["payload"]["retained_evidence"]["security"]
    incomplete = _rebuilt_packet(packet, document)
    with pytest.raises(AdmissionError, match="qualification packet differs"):
        build_operational_admission_decision(
            packet=incomplete,
            owner_identity_digest=_D3,
            decision_recorded_at_digest=_D,
        )

    document = json.loads(packet.canonical_bytes)
    document["payload"]["evidence_digests"]["p1_finding_count"] = False
    type_confused = _rebuilt_packet(packet, document)
    with pytest.raises(AdmissionError, match="qualification packet differs"):
        build_operational_admission_decision(
            packet=type_confused,
            owner_identity_digest=_D3,
            decision_recorded_at_digest=_D,
        )


def test_self_consistent_packet_cannot_rebind_retained_security(
    tmp_path, admitted_gate
) -> None:
    packet = _packet(tmp_path)
    document = json.loads(packet.canonical_bytes)
    security = document["payload"]["retained_evidence"]["security"]
    security["payload"]["rights_current"] = False
    security["payload"]["eligible"] = True
    security["payload"]["blocking_reasons"] = []
    security_raw = canonical_json_bytes(security)
    document["payload"]["evidence_digests"]["security_digest"] = digest_bytes(
        security_raw
    )
    forged = _rebuilt_packet(packet, document)
    with pytest.raises(AdmissionError, match="qualification packet differs"):
        build_operational_admission_decision(
            packet=forged,
            owner_identity_digest=_D3,
            decision_recorded_at_digest=_D,
        )


def test_packet_rejects_retained_derived_fields_that_differ_from_reconstruction(
    tmp_path, admitted_gate
) -> None:
    packet = _packet(tmp_path)
    for field, value in (("alert_priority", "P1"),):
        document = json.loads(packet.canonical_bytes)
        document["payload"]["retained_evidence"]["observability"]["payload"][
            field
        ] = value
        forged = _rebuilt_packet(packet, document)
        with pytest.raises(AdmissionError, match="qualification packet differs"):
            build_operational_admission_decision(
                packet=forged,
                owner_identity_digest=_D3,
                decision_recorded_at_digest=_D,
            )

    document = json.loads(packet.canonical_bytes)
    document["payload"]["retained_evidence"]["health_postures"][0]["payload"][
        "verdict"
    ] = "HEALTHY_CHANGED"
    forged_health = _rebuilt_packet(packet, document)
    with pytest.raises(AdmissionError, match="qualification packet differs"):
        build_operational_admission_decision(
            packet=forged_health,
            owner_identity_digest=_D3,
            decision_recorded_at_digest=_D,
        )


def test_packet_sorts_and_requires_canonical_retained_evidence_order(
    tmp_path, admitted_gate
) -> None:
    packet = _packet(tmp_path)
    document = json.loads(packet.canonical_bytes)
    retained_faults = document["payload"]["retained_evidence"]["fault_runs"]
    retained_digests = [digest_bytes(canonical_json_bytes(item)) for item in retained_faults]
    assert retained_digests == sorted(retained_digests)

    document["payload"]["retained_evidence"]["fault_runs"] = list(
        reversed(retained_faults)
    )
    reordered = _rebuilt_packet(packet, document)
    with pytest.raises(AdmissionError, match="qualification packet differs"):
        build_operational_admission_decision(
            packet=reordered,
            owner_identity_digest=_D3,
            decision_recorded_at_digest=_D,
        )


def test_builder_reconstructs_detached_and_semantically_forged_evidence(
    tmp_path, admitted_gate
) -> None:
    with pytest.raises(AdmissionError, match="security evidence"):
        _packet(tmp_path / "security", security=replace(_security(), eligible=False))
    with pytest.raises(AdmissionError, match="health evidence"):
        _packet(
            tmp_path / "health",
            health_postures=[replace(_health(), verdict=HealthVerdict.HEALTHY_CHANGED)],
        )
    with pytest.raises(AdmissionError, match="observability evidence"):
        _packet(
            tmp_path / "observability",
            observability=replace(_observability(), priority=AlertPriority.P1),
        )

    capacity = _capacity()
    forged_capacity = CapacityEvidence.build(
        {**capacity.payload, "cpu_cores": 0, "status": "PASS"}
    )
    with pytest.raises(AdmissionError, match="capacity evidence semantics"):
        _packet(tmp_path / "capacity", capacity=forged_capacity)

    reconciliation = _reconciliation()
    forged_reconciliation = ReconciliationRun.build(
        {
            **reconciliation.payload,
            "finding_counts": {
                **reconciliation.payload["finding_counts"],  # type: ignore[dict-item]
                "AMBIGUOUS_EFFECT": 1,
            },
            "status": "PASS",
            "automatic_operation_blocked": False,
        }
    )
    with pytest.raises(AdmissionError, match="reconciliation"):
        _packet(tmp_path / "reconciliation", reconciliation=forged_reconciliation)
    with pytest.raises(AdmissionError, match="evidence"):
        _packet(
            tmp_path / "rollback",
            rollback_evidence=object(),
        )
    self_verification = IndependentVerificationEvidence.build(
        verifier_identity_digest=_D,
        verification_method_digest=_D,
        reviewed_evidence_manifest_digest=_D,
        verified_at_digest=_D,
    )
    with pytest.raises(AdmissionError, match="qualification evidence is contradictory"):
        _packet(
            tmp_path / "self-verification",
            independent_verification=self_verification,
        )


def test_stale_expected_handoff_anchor_and_decision_tamper_fail_closed(
    tmp_path, admitted_gate
) -> None:
    with pytest.raises(AdmissionError, match="Handoff"):
        _packet(tmp_path / "stale-anchor", expected_handoff_anchor_digest=_D2)

    packet = _packet(tmp_path / "decision")
    decision = build_operational_admission_decision(
        packet=packet,
        owner_identity_digest=_D3,
        decision_recorded_at_digest=_D,
    )
    with pytest.raises(AdmissionError, match="Operational Admission semantics"):
        OperationalAdmissionDecision.from_canonical_bytes(
            decision.canonical_bytes.replace(
                b'"operational_admission_is_activation":false',
                b'"operational_admission_is_activation":true',
            ),
            packet=packet,
        )


def test_restore_reconciliation_profile_and_admission_owner_are_exact(
    tmp_path, admitted_gate
) -> None:
    packet = _packet(tmp_path / "valid")

    document = json.loads(packet.canonical_bytes)
    restore_reconciliation = document["payload"]["retained_evidence"][
        "restore_reconciliation"
    ]
    restore_reconciliation["payload"]["restored_state_digest"] = _D2
    forged_restore = _rebuilt_packet(packet, document)
    with pytest.raises(AdmissionError, match="qualification packet differs"):
        build_operational_admission_decision(
            packet=forged_restore,
            owner_identity_digest=_D3,
            decision_recorded_at_digest=_D,
        )

    document = json.loads(packet.canonical_bytes)
    retained = document["payload"]["retained_evidence"]
    previous = retained["restore_reconciliation"]
    earlier = ReconciliationRun.build(
        {**previous["payload"], "started_at": "2042-01-05T00:00:00.000000Z"}
    )
    retained["restore_reconciliation"] = json.loads(earlier.canonical_bytes)
    document["payload"]["evidence_digests"][
        "restore_reconciliation_digest"
    ] = earlier.digest
    forged_time = _rebuilt_packet(packet, document)
    with pytest.raises(AdmissionError, match="qualification packet differs"):
        build_operational_admission_decision(
            packet=forged_time,
            owner_identity_digest=_D3,
            decision_recorded_at_digest=_D,
        )

    document = json.loads(packet.canonical_bytes)
    rollback = document["payload"]["retained_evidence"]["rollback_evidence"]
    rollback["payload"]["restore_digest"] = _D2
    rollback_raw = canonical_json_bytes(rollback)
    document["payload"]["evidence_digests"][
        "rollback_evidence_digest"
    ] = digest_bytes(rollback_raw)
    forged_rollback = _rebuilt_packet(packet, document)
    with pytest.raises(AdmissionError, match="qualification packet differs"):
        build_operational_admission_decision(
            packet=forged_rollback,
            owner_identity_digest=_D3,
            decision_recorded_at_digest=_D,
        )

    document = json.loads(packet.canonical_bytes)
    profile = document["payload"]["retained_evidence"]["operational_profile"]
    profile["payload"]["profile_definition"]["execution"]["host_concurrency"] = 99
    forged_profile = _rebuilt_packet(packet, document)
    with pytest.raises(AdmissionError, match="qualification packet differs"):
        build_operational_admission_decision(
            packet=forged_profile,
            owner_identity_digest=_D3,
            decision_recorded_at_digest=_D,
        )

    with pytest.raises(AdmissionError, match="owner is not independent"):
        build_operational_admission_decision(
            packet=packet,
            owner_identity_digest=_D2,
            decision_recorded_at_digest=_D,
        )

    decision = build_operational_admission_decision(
        packet=packet,
        owner_identity_digest=_D3,
        decision_recorded_at_digest=_D,
    )
    decision_document = json.loads(decision.canonical_bytes)
    decision_document["payload"]["owner_identity_digest"] = _D
    with pytest.raises(AdmissionError, match="Operational Admission semantics"):
        OperationalAdmissionDecision.from_canonical_bytes(
            canonical_json_bytes(decision_document), packet=packet
        )
    with pytest.raises(AdmissionError, match="owner is not independent"):
        build_operational_admission_decision(
            packet=packet,
            owner_identity_digest=_D,
            decision_recorded_at_digest=_D,
        )
