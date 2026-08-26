from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import replace

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_canonical
from newsroom.production_admission import (
    PRODUCTION_GATE_IDS,
    AuthenticationKey,
    BoundArtifact,
    BoundArtifactRole,
    EvaluatedIdentity,
    FreezeIdentity,
    GateAttestation,
    IdentityClass,
    KeyClass,
    OwnerAdmissionInstruction,
    ProductionAdmissionError,
    ProductionAdmissionVerdict,
    ProductionEvidenceManifest,
    ProductionGateId,
    ProductionIdentitySet,
    ProductionOperationalAdmission,
    ProductionReadinessReport,
    ReadinessStatus,
    inspect_readiness,
    mint_production_operational_admission,
)

_FREEZE = FreezeIdentity(exact_main_sha="a" * 40, exact_main_tree="b" * 40)
_OPERATIONAL_MANIFEST = digest_canonical({"manifest": "production"})
_DEPLOYMENT_BYTES = digest_canonical({"deployment": "bytes"})
_STORE = digest_canonical({"store": "production"})
_STOP_CONDITIONS = digest_canonical({"stop_conditions": "production"})
_RECONCILIATION_PROCEDURE = digest_canonical({"reconciliation_procedure": "production"})
_PUBLICATION_SPECS = {
    path: digest_canonical({"accepted_spec": path})
    for path in (
        "docs/specs/editorial-automation/autonomy-and-publication-control.md",
        "docs/specs/editorial-automation/content-generation-and-presentation.md",
        "docs/specs/editorial-automation/publication-engineering-and-projection-control.md",
        "docs/specs/editorial-automation/publication-lifecycle-and-audit.md",
        "docs/specs/editorial-automation/quality-evaluation-and-change-control.md",
        "docs/specs/editorial-automation/rights-and-visuals.md",
        "docs/specs/editorial-automation/sensitive-content-and-escalation.md",
        "docs/specs/editorial-automation/story-eligibility-and-evidence.md",
    )
}
_EVIDENCE_KEY = AuthenticationKey(
    key_id="keychain:newsroom-evidence-v1",
    key_class=KeyClass.EVIDENCE_AUTHORITY,
    secret=b"e" * 32,
)
_OWNER_KEY = AuthenticationKey(
    key_id="keychain:human-accountable-owner-v1",
    key_class=KeyClass.HUMAN_ACCOUNTABLE_OWNER,
    secret=b"o" * 32,
)
_PRODUCTION_KEY = AuthenticationKey(
    key_id="keychain:production-operational-admission-v1",
    key_class=KeyClass.PRODUCTION_OPERATIONAL_ADMISSION,
    secret=b"p" * 32,
)


def _complete_evidence() -> tuple[
    ProductionEvidenceManifest, tuple[GateAttestation, ...]
]:
    canary_digest = digest_canonical(
        {"artifact": BoundArtifactRole.LIVE_EVIDENCE_INTAKE_CANARY_CLOSEOUT.value}
    )
    identities = tuple(
        EvaluatedIdentity(
            identity_class=identity_class,
            identity_digest=digest_canonical({"identity_class": identity_class.value}),
            evaluation_evidence_digest=(
                canary_digest
                if identity_class is IdentityClass.LIVE_EVIDENCE_INTAKE
                else digest_canonical({"evaluation": identity_class.value})
            ),
            evaluated_sha=_FREEZE.exact_main_sha,
            evaluated_tree=_FREEZE.exact_main_tree,
            operational_manifest_digest=_OPERATIONAL_MANIFEST,
            production_scope=True,
        )
        for identity_class in IdentityClass
    )
    identity_set = ProductionIdentitySet.build(
        freeze=_FREEZE,
        operational_manifest_digest=_OPERATIONAL_MANIFEST,
        deployment_bytes_digest=_DEPLOYMENT_BYTES,
        relational_schema_version=32,
        migration_history_digest=digest_canonical({"migrations": "exact"}),
        schema_fingerprint=digest_canonical({"schema": "exact"}),
        projection_generation_digest=digest_canonical(
            {"projection_generation": "current"}
        ),
        contiguous_projection_watermark=1606,
        handoff_max_attempts=3,
        identities=identities,
    )
    outcomes = {
        BoundArtifactRole.SHADOW_CLOSEOUT: "SCOPED_OPERATIONAL_ELIGIBILITY",
        BoundArtifactRole.LIVE_EVIDENCE_INTAKE_CANARY_CLOSEOUT: (
            "ELIGIBLE_FOR_ACTIVATION_PLANNING"
        ),
        BoundArtifactRole.BACKUP: "PASS",
        BoundArtifactRole.RESTORE: "PASS",
        BoundArtifactRole.ROLLBACK: "PASS",
    }
    bound_artifacts = tuple(
        BoundArtifact.build(
            role=role,
            artifact_digest=digest_canonical({"artifact": role.value}),
            freeze=_FREEZE,
            operational_manifest_digest=_OPERATIONAL_MANIFEST,
            identity_set_digest=identity_set.digest,
            deployment_bytes_digest=_DEPLOYMENT_BYTES,
            store_identity_digest=_STORE,
            stop_conditions_digest=_STOP_CONDITIONS,
            reconciliation_procedure_digest=_RECONCILIATION_PROCEDURE,
            outcome=outcome,
        )
        for role, outcome in outcomes.items()
    )
    gate_artifacts = {
        gate_id: digest_canonical({"gate": gate_id.value})
        for gate_id in PRODUCTION_GATE_IDS
    }
    gate_artifacts[ProductionGateId.PUBLICATION_LIFECYCLE_SPECIFICATIONS_ACCEPTED] = (
        digest_canonical(_PUBLICATION_SPECS)
    )
    for identity in identities:
        gate_artifacts[identity.identity_class.gate_id] = (
            identity.evaluation_evidence_digest
        )
    canary = next(
        item
        for item in bound_artifacts
        if item.role is BoundArtifactRole.LIVE_EVIDENCE_INTAKE_CANARY_CLOSEOUT
    )
    gate_artifacts[IdentityClass.LIVE_EVIDENCE_INTAKE.gate_id] = canary.artifact_digest
    manifest = ProductionEvidenceManifest.build(
        identity_set=identity_set,
        gate_artifact_digests=gate_artifacts,
        bound_artifacts=bound_artifacts,
        accepted_publication_spec_digests=_PUBLICATION_SPECS,
        fixture_admission_digest=digest_canonical(
            {"fixture_admission": "evidence-only"}
        ),
        fixture_admission_inherited=False,
        readiness_provider_calls=0,
        readiness_publication_effects=0,
        readiness_production_mutations=0,
    )
    attestations = tuple(
        GateAttestation.build(
            gate_id=gate_id,
            evidence_manifest=manifest,
            status=ReadinessStatus.PASS,
            blockers=(),
            issuer_identity="service:newsroom-evidence-authority",
            sealed_at="2026-08-26T10:00:00Z",
            signing_key=_EVIDENCE_KEY,
        )
        for gate_id in PRODUCTION_GATE_IDS
    )
    return manifest, attestations


def _resign(manifest: ProductionEvidenceManifest) -> tuple[GateAttestation, ...]:
    return tuple(
        GateAttestation.build(
            gate_id=gate_id,
            evidence_manifest=manifest,
            status=ReadinessStatus.PASS,
            blockers=(),
            issuer_identity="service:newsroom-evidence-authority",
            sealed_at="2026-08-26T10:00:00Z",
            signing_key=_EVIDENCE_KEY,
        )
        for gate_id in PRODUCTION_GATE_IDS
    )


def _rebuild_manifest(
    source: ProductionEvidenceManifest,
    *,
    bound_artifacts: tuple[BoundArtifact, ...] | None = None,
    accepted_publication_spec_digests: dict[str, str] | None = None,
    fixture_admission_inherited: bool | None = None,
    readiness_provider_calls: int | None = None,
) -> ProductionEvidenceManifest:
    return ProductionEvidenceManifest.build(
        identity_set=source.identity_set,
        gate_artifact_digests=source.gate_artifact_digests,
        bound_artifacts=(
            source.bound_artifacts if bound_artifacts is None else bound_artifacts
        ),
        accepted_publication_spec_digests=(
            source.accepted_publication_spec_digests
            if accepted_publication_spec_digests is None
            else accepted_publication_spec_digests
        ),
        fixture_admission_digest=source.fixture_admission_digest,
        fixture_admission_inherited=(
            source.fixture_admission_inherited
            if fixture_admission_inherited is None
            else fixture_admission_inherited
        ),
        readiness_provider_calls=(
            source.readiness_provider_calls
            if readiness_provider_calls is None
            else readiness_provider_calls
        ),
        readiness_publication_effects=source.readiness_publication_effects,
        readiness_production_mutations=source.readiness_production_mutations,
    )


def test_missing_production_evidence_lists_every_gate_as_a_precise_blocker() -> None:
    freeze = FreezeIdentity(exact_main_sha="a" * 40, exact_main_tree="b" * 40)

    report = inspect_readiness(
        freeze=freeze,
        evidence_manifest=None,
        attestations=(),
        trusted_evidence_keys={},
    )

    assert (
        ProductionReadinessReport.from_canonical_bytes(report.canonical_bytes) == report
    )
    assert tuple(result.gate_id for result in report.gates) == PRODUCTION_GATE_IDS
    assert all(result.status is ReadinessStatus.BLOCKED for result in report.gates)
    assert all(
        result.blockers == ("MISSING_PRODUCTION_EVIDENCE_MANIFEST",)
        for result in report.gates
    )
    assert report.ready_for_admission is False
    assert report.provider_calls == 0
    assert report.publication_effects == 0
    assert report.production_mutations == 0
    assert report.production_activation_authorised is False


def test_complete_current_sealed_evidence_produces_a_replayable_ready_report() -> None:
    manifest, attestations = _complete_evidence()

    report = inspect_readiness(
        freeze=_FREEZE,
        evidence_manifest=manifest,
        attestations=attestations,
        trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
    )

    assert (
        ProductionEvidenceManifest.from_canonical_bytes(manifest.canonical_bytes)
        == manifest
    )
    assert (
        ProductionReadinessReport.from_canonical_bytes(report.canonical_bytes) == report
    )
    assert report.ready_for_admission is True
    assert all(result.status is ReadinessStatus.PASS for result in report.gates)
    assert report.evidence_manifest_digest == manifest.digest
    assert report.operational_manifest_digest == _OPERATIONAL_MANIFEST
    assert report.identity_set_digest == manifest.identity_set.digest
    assert report.relational_schema_version == 32
    assert (
        report.migration_history_digest
        == manifest.identity_set.migration_history_digest
    )
    assert report.schema_fingerprint == manifest.identity_set.schema_fingerprint
    assert report.projection_generation_digest == (
        manifest.identity_set.projection_generation_digest
    )
    assert report.contiguous_projection_watermark == 1606
    assert report.handoff_max_attempts == 3


def test_publication_spec_inventory_is_exact_and_binds_the_gate() -> None:
    manifest, _ = _complete_evidence()
    incomplete = dict(_PUBLICATION_SPECS)
    incomplete.pop(next(iter(incomplete)))

    with pytest.raises(ProductionAdmissionError, match="publication spec inventory"):
        _rebuild_manifest(
            manifest,
            accepted_publication_spec_digests=incomplete,
        )

    drifted_specs = dict(_PUBLICATION_SPECS)
    drifted_specs[next(iter(drifted_specs))] = digest_canonical(
        {"accepted_spec": "drifted"}
    )
    drifted = _rebuild_manifest(
        manifest,
        accepted_publication_spec_digests=drifted_specs,
    )
    report = inspect_readiness(
        freeze=_FREEZE,
        evidence_manifest=drifted,
        attestations=_resign(drifted),
        trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
    )

    result = next(
        item
        for item in report.gates
        if item.gate_id
        is ProductionGateId.PUBLICATION_LIFECYCLE_SPECIFICATIONS_ACCEPTED
    )
    assert result.blockers == ("PUBLICATION_SPEC_EVIDENCE_DRIFT",)


def test_invalid_evidence_seal_and_fixture_inheritance_fail_closed() -> None:
    manifest, _ = _complete_evidence()
    inherited = _rebuild_manifest(manifest, fixture_admission_inherited=True)
    resealed = list(_resign(inherited))
    target = PRODUCTION_GATE_IDS[0]
    index = PRODUCTION_GATE_IDS.index(target)
    resealed[index] = replace(resealed[index], seal="hmac-sha256:" + "0" * 64)

    report = inspect_readiness(
        freeze=_FREEZE,
        evidence_manifest=inherited,
        attestations=tuple(resealed),
        trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
    )

    by_gate = {result.gate_id: result for result in report.gates}
    assert "INVALID_GATE_ATTESTATION_SEAL" in by_gate[target].blockers
    assert (
        "FIXTURE_OPERATIONAL_ADMISSION_INHERITED"
        in by_gate[ProductionGateId.HANDOFF_NON_EFFECT_IDENTITIES_CURRENT].blockers
    )
    assert report.ready_for_admission is False


def test_canary_restore_and_rollback_must_bind_the_same_bytes_and_store() -> None:
    manifest, _ = _complete_evidence()
    artifacts = tuple(
        (
            BoundArtifact.build(
                role=item.role,
                artifact_digest=item.artifact_digest,
                freeze=item.freeze,
                operational_manifest_digest=item.operational_manifest_digest,
                identity_set_digest=item.identity_set_digest,
                deployment_bytes_digest=item.deployment_bytes_digest,
                store_identity_digest=digest_canonical({"store": "drifted"}),
                stop_conditions_digest=item.stop_conditions_digest,
                reconciliation_procedure_digest=(item.reconciliation_procedure_digest),
                outcome=item.outcome,
            )
            if item.role is BoundArtifactRole.RESTORE
            else item
        )
        for item in manifest.bound_artifacts
    )
    drifted = _rebuild_manifest(manifest, bound_artifacts=artifacts)

    report = inspect_readiness(
        freeze=_FREEZE,
        evidence_manifest=drifted,
        attestations=_resign(drifted),
        trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
    )

    gate = next(
        result
        for result in report.gates
        if result.gate_id is ProductionGateId.CANARY_ROLLBACK_RESTORE_IDENTITY_BOUND
    )
    assert gate.blockers == ("CANARY_ROLLBACK_RESTORE_IDENTITY_DRIFT",)


def test_provider_use_during_readiness_inspection_is_never_a_pass() -> None:
    manifest, _ = _complete_evidence()
    effected = _rebuild_manifest(manifest, readiness_provider_calls=1)

    report = inspect_readiness(
        freeze=_FREEZE,
        evidence_manifest=effected,
        attestations=_resign(effected),
        trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
    )

    gate = next(
        result
        for result in report.gates
        if result.gate_id is ProductionGateId.READINESS_INSPECTION_NON_EFFECT
    )
    assert gate.blockers == ("READINESS_INSPECTION_CREATED_EFFECT",)


def test_authenticated_owner_instruction_mints_one_idempotent_non_activation_record() -> (
    None
):
    manifest, attestations = _complete_evidence()
    report = inspect_readiness(
        freeze=_FREEZE,
        evidence_manifest=manifest,
        attestations=attestations,
        trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
    )
    instruction = OwnerAdmissionInstruction.build(
        authority_issue_number=900,
        owner_identity="github:fol2",
        issued_at="2026-08-26T10:30:00Z",
        report=report,
        evidence_manifest=manifest,
        production_signing_key_id=_PRODUCTION_KEY.key_id,
        owner_signing_key=_OWNER_KEY,
    )

    first = mint_production_operational_admission(
        freeze=_FREEZE,
        report=report,
        evidence_manifest=manifest,
        attestations=attestations,
        trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
        owner_instruction=instruction,
        trusted_owner_keys={_OWNER_KEY.key_id: _OWNER_KEY},
        production_signing_key=_PRODUCTION_KEY,
    )
    replay = mint_production_operational_admission(
        freeze=_FREEZE,
        report=report,
        evidence_manifest=manifest,
        attestations=attestations,
        trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
        owner_instruction=instruction,
        trusted_owner_keys={_OWNER_KEY.key_id: _OWNER_KEY},
        production_signing_key=_PRODUCTION_KEY,
    )

    assert first == replay
    assert first.verdict is ProductionAdmissionVerdict.PRODUCTION_OPERATIONAL_ADMITTED
    assert (
        ProductionOperationalAdmission.from_canonical_bytes(
            first.canonical_bytes,
            report=report,
            evidence_manifest=manifest,
            owner_instruction=instruction,
            trusted_owner_keys={_OWNER_KEY.key_id: _OWNER_KEY},
            trusted_production_keys={_PRODUCTION_KEY.key_id: _PRODUCTION_KEY},
        )
        == first
    )
    assert first.increment11r_authorised is False
    assert first.production_activation_authorised is False
    assert first.publication_authorised is False
    assert first.public_dispatch_authorised is False
    assert first.production_mutation_authorised is False
    assert dict(first.accepted_publication_spec_digests) == _PUBLICATION_SPECS


@pytest.mark.parametrize("missing_gate", PRODUCTION_GATE_IDS)
def test_every_missing_gate_attestation_is_a_named_blocker(
    missing_gate: ProductionGateId,
) -> None:
    manifest, attestations = _complete_evidence()

    report = inspect_readiness(
        freeze=_FREEZE,
        evidence_manifest=manifest,
        attestations=tuple(
            item for item in attestations if item.gate_id is not missing_gate
        ),
        trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
    )

    result = next(item for item in report.gates if item.gate_id is missing_gate)
    assert result.blockers == ("MISSING_GATE_ATTESTATION",)
    assert report.ready_for_admission is False


def test_blocked_gate_cannot_be_hidden_by_a_signed_attestation() -> None:
    manifest, attestations = _complete_evidence()
    blocked_gate = ProductionGateId.EFFECTIVE_REVISION_COVERAGE_CURRENT
    changed = tuple(
        (
            GateAttestation.build(
                gate_id=blocked_gate,
                evidence_manifest=manifest,
                status=ReadinessStatus.BLOCKED,
                blockers=("TERMINAL_COVERAGE_INCOMPLETE",),
                issuer_identity="service:newsroom-evidence-authority",
                sealed_at="2026-08-26T10:00:00Z",
                signing_key=_EVIDENCE_KEY,
            )
            if item.gate_id is blocked_gate
            else item
        )
        for item in attestations
    )

    report = inspect_readiness(
        freeze=_FREEZE,
        evidence_manifest=manifest,
        attestations=changed,
        trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
    )

    result = next(item for item in report.gates if item.gate_id is blocked_gate)
    assert result.blockers == ("TERMINAL_COVERAGE_INCOMPLETE",)
    with pytest.raises(ProductionAdmissionError, match="ready evidence"):
        OwnerAdmissionInstruction.build(
            authority_issue_number=900,
            owner_identity="github:fol2",
            issued_at="2026-08-26T10:30:00Z",
            report=report,
            evidence_manifest=manifest,
            production_signing_key_id=_PRODUCTION_KEY.key_id,
            owner_signing_key=_OWNER_KEY,
        )


def test_implementation_issue_is_not_an_owner_production_admission_instruction() -> (
    None
):
    manifest, attestations = _complete_evidence()
    report = inspect_readiness(
        freeze=_FREEZE,
        evidence_manifest=manifest,
        attestations=attestations,
        trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
    )

    with pytest.raises(ProductionAdmissionError, match="dedicated"):
        OwnerAdmissionInstruction.build(
            authority_issue_number=760,
            owner_identity="github:fol2",
            issued_at="2026-08-26T10:30:00Z",
            report=report,
            evidence_manifest=manifest,
            production_signing_key_id=_PRODUCTION_KEY.key_id,
            owner_signing_key=_OWNER_KEY,
        )


def test_tampered_owner_instruction_and_unlisted_production_key_are_refused() -> None:
    manifest, attestations = _complete_evidence()
    report = inspect_readiness(
        freeze=_FREEZE,
        evidence_manifest=manifest,
        attestations=attestations,
        trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
    )
    instruction = OwnerAdmissionInstruction.build(
        authority_issue_number=900,
        owner_identity="github:fol2",
        issued_at="2026-08-26T10:30:00Z",
        report=report,
        evidence_manifest=manifest,
        production_signing_key_id=_PRODUCTION_KEY.key_id,
        owner_signing_key=_OWNER_KEY,
    )

    with pytest.raises(ProductionAdmissionError, match="owner instruction"):
        mint_production_operational_admission(
            freeze=_FREEZE,
            report=report,
            evidence_manifest=manifest,
            attestations=attestations,
            trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
            owner_instruction=replace(instruction, owner_identity="github:someone"),
            trusted_owner_keys={_OWNER_KEY.key_id: _OWNER_KEY},
            production_signing_key=_PRODUCTION_KEY,
        )

    other_key = AuthenticationKey(
        key_id="keychain:another-production-key",
        key_class=KeyClass.PRODUCTION_OPERATIONAL_ADMISSION,
        secret=b"x" * 32,
    )
    with pytest.raises(ProductionAdmissionError, match="signing key"):
        mint_production_operational_admission(
            freeze=_FREEZE,
            report=report,
            evidence_manifest=manifest,
            attestations=attestations,
            trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
            owner_instruction=instruction,
            trusted_owner_keys={_OWNER_KEY.key_id: _OWNER_KEY},
            production_signing_key=other_key,
        )


def test_verification_refuses_an_owner_instruction_for_different_evidence() -> None:
    manifest, attestations = _complete_evidence()
    report = inspect_readiness(
        freeze=_FREEZE,
        evidence_manifest=manifest,
        attestations=attestations,
        trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
    )
    instruction = OwnerAdmissionInstruction.build(
        authority_issue_number=900,
        owner_identity="github:fol2",
        issued_at="2026-08-26T10:30:00Z",
        report=report,
        evidence_manifest=manifest,
        production_signing_key_id=_PRODUCTION_KEY.key_id,
        owner_signing_key=_OWNER_KEY,
    )
    admission = mint_production_operational_admission(
        freeze=_FREEZE,
        report=report,
        evidence_manifest=manifest,
        attestations=attestations,
        trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
        owner_instruction=instruction,
        trusted_owner_keys={_OWNER_KEY.key_id: _OWNER_KEY},
        production_signing_key=_PRODUCTION_KEY,
    )

    other_manifest = ProductionEvidenceManifest.build(
        identity_set=manifest.identity_set,
        gate_artifact_digests=manifest.gate_artifact_digests,
        bound_artifacts=manifest.bound_artifacts,
        accepted_publication_spec_digests=(manifest.accepted_publication_spec_digests),
        fixture_admission_digest=digest_canonical(
            {"fixture_admission": "different-evidence-only"}
        ),
        fixture_admission_inherited=False,
        readiness_provider_calls=0,
        readiness_publication_effects=0,
        readiness_production_mutations=0,
    )
    other_attestations = _resign(other_manifest)
    other_report = inspect_readiness(
        freeze=_FREEZE,
        evidence_manifest=other_manifest,
        attestations=other_attestations,
        trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
    )
    other_instruction = OwnerAdmissionInstruction.build(
        authority_issue_number=901,
        owner_identity="github:fol2",
        issued_at="2026-08-26T10:31:00Z",
        report=other_report,
        evidence_manifest=other_manifest,
        production_signing_key_id=_PRODUCTION_KEY.key_id,
        owner_signing_key=_OWNER_KEY,
    )

    forged = json.loads(admission.canonical_bytes)
    forged.update(
        {
            "owner_instruction_id": other_instruction.instruction_id,
            "owner_instruction_digest": other_instruction.digest,
            "authority_issue_number": other_instruction.authority_issue_number,
            "authority_issue_url": other_instruction.authority_issue_url,
            "issuer_identity": other_instruction.owner_identity,
            "issued_at": other_instruction.issued_at,
        }
    )
    forged.pop("seal")
    forged["seal"] = (
        "hmac-sha256:"
        + hmac.new(
            _PRODUCTION_KEY.secret,
            canonical_json_bytes(forged),
            hashlib.sha256,
        ).hexdigest()
    )

    with pytest.raises(ProductionAdmissionError, match="owner instruction binding"):
        ProductionOperationalAdmission.from_canonical_bytes(
            canonical_json_bytes(forged),
            report=report,
            evidence_manifest=manifest,
            owner_instruction=other_instruction,
            trusted_owner_keys={_OWNER_KEY.key_id: _OWNER_KEY},
            trusted_production_keys={_PRODUCTION_KEY.key_id: _PRODUCTION_KEY},
        )
