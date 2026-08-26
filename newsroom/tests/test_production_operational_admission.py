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
    KeyProvenance,
    OwnerAdmissionInstruction,
    OwnerIssueRecord,
    OwnerIssueSnapshot,
    ProductionAdmissionError,
    ProductionAdmissionVerdict,
    ProductionEvidenceManifest,
    ProductionGateEvidence,
    ProductionGateId,
    ProductionIdentitySet,
    ProductionOperationalAdmission,
    ProductionReadinessReport,
    ReadinessStatus,
    inspect_readiness,
    mint_production_operational_admission,
    owner_issue_binding_marker,
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
    provenance=KeyProvenance.PRODUCTION_TRUST_ROOT,
    secret=b"e" * 32,
)
_OWNER_KEY = AuthenticationKey(
    key_id="keychain:human-accountable-owner-v1",
    key_class=KeyClass.HUMAN_ACCOUNTABLE_OWNER,
    provenance=KeyProvenance.PRODUCTION_TRUST_ROOT,
    secret=b"o" * 32,
)
_PRODUCTION_KEY = AuthenticationKey(
    key_id="keychain:production-operational-admission-v1",
    key_class=KeyClass.PRODUCTION_OPERATIONAL_ADMISSION,
    provenance=KeyProvenance.PRODUCTION_TRUST_ROOT,
    secret=b"p" * 32,
)


def _gate_facts(
    gate_id: ProductionGateId,
    *,
    identity_set: ProductionIdentitySet,
    bound_artifacts: tuple[BoundArtifact, ...],
) -> dict[str, object]:
    identities = {item.identity_class: item for item in identity_set.identities}

    def identity_facts(identity_class: IdentityClass) -> dict[str, object]:
        identity = identities[identity_class]
        return {
            "identity_digest": identity.identity_digest,
            "evaluation_evidence_digest": identity.evaluation_evidence_digest,
        }

    artifacts = {item.role: item for item in bound_artifacts}
    if gate_id is ProductionGateId.RELATIONAL_SCHEMA_CURRENT:
        return {
            **identity_facts(IdentityClass.RELATIONAL_SCHEMA),
            "relational_schema_version": identity_set.relational_schema_version,
            "migration_history_digest": identity_set.migration_history_digest,
            "schema_fingerprint": identity_set.schema_fingerprint,
        }
    if gate_id is ProductionGateId.OPERATIONAL_PROFILE_CURRENT:
        return {
            **identity_facts(IdentityClass.OPERATIONAL_PROFILE),
            "profile_scope": "production",
            "profile_current": True,
        }
    if gate_id is ProductionGateId.GRAPHRAG_DEPLOYMENT_CURRENT:
        return {
            **identity_facts(IdentityClass.GRAPHRAG_DEPLOYMENT),
            "deployment_bytes_digest": identity_set.deployment_bytes_digest,
            "projection_generation_digest": identity_set.projection_generation_digest,
            "contiguous_projection_watermark": (
                identity_set.contiguous_projection_watermark
            ),
            "admitted_only": True,
        }
    if gate_id is ProductionGateId.RETRIEVAL_CONTRACT_CURRENT:
        return {
            **identity_facts(IdentityClass.RETRIEVAL_CONTRACT),
            "contract_current": True,
            "admitted_only": True,
        }
    if gate_id is ProductionGateId.LIVE_EVIDENCE_INTAKE_CURRENT:
        canary = artifacts[BoundArtifactRole.LIVE_EVIDENCE_INTAKE_CANARY_CLOSEOUT]
        return {
            **identity_facts(IdentityClass.LIVE_EVIDENCE_INTAKE),
            "canary_closeout_digest": canary.artifact_digest,
            "canary_outcome": "ELIGIBLE_FOR_ACTIVATION_PLANNING",
            "run_window_closed": True,
        }
    if gate_id is ProductionGateId.PUBLICATION_ADAPTERS_CURRENT:
        return {
            **identity_facts(IdentityClass.PUBLICATION_ADAPTERS),
            "adapter_inventory_digest": digest_canonical(
                {"publication_adapters": "production"}
            ),
            "adapter_count": 1,
            "adapters_current": True,
        }
    if gate_id is ProductionGateId.HANDOFF_NON_EFFECT_IDENTITIES_CURRENT:
        return {
            **identity_facts(IdentityClass.HANDOFF_NON_EFFECT),
            "handoff_max_attempts": identity_set.handoff_max_attempts,
            "publication_effects": 0,
            "public_dispatch_effects": 0,
            "production_mutations": 0,
        }
    if gate_id is ProductionGateId.EFFECTIVE_REVISION_COVERAGE_CURRENT:
        return {
            "coverage_policy": "FULL_TERMINAL",
            "eligible_revisions": 1606,
            "terminal_revisions": 1606,
            "terminal_coverage_ppm": 1_000_000,
            "required_terminal_coverage_ppm": 1_000_000,
            "hidden_gap_count": 0,
            "threshold_authority_digest": None,
            "contiguous_projection_watermark": (
                identity_set.contiguous_projection_watermark
            ),
        }
    if gate_id is ProductionGateId.SPEND_ACCOUNTING_RECONCILED:
        return {
            "attempt_count": 564,
            "reconciled_attempt_count": 564,
            "unreconciled_attempt_count": 0,
            "usage_uncertainty_count": 0,
            "reserved_gbp_microunits": 0,
            "actual_gbp_microunits": 9792,
        }
    if gate_id is ProductionGateId.RIGHTS_TERMS_CREDENTIALS_EGRESS_CURRENT:
        return {
            "rights_identity_digest": digest_canonical({"rights": "current"}),
            "provider_terms_identity_digest": digest_canonical(
                {"provider_terms": "current"}
            ),
            "credential_identity_digest": digest_canonical({"credentials": "current"}),
            "egress_identity_digest": digest_canonical({"egress": "current"}),
            "rights_current": True,
            "provider_terms_current": True,
            "credentials_current": True,
            "egress_current": True,
        }
    if gate_id is ProductionGateId.HERMES_RUNTIME_CONTROLS_CURRENT:
        return {
            "control_plane": "HERMES",
            "single_instance_count": 1,
            "veto_ready": True,
            "kill_switch_ready": True,
            "signed_human_stop_digest": digest_canonical({"human_stop": "clear"}),
            "human_stop_state": "CLEAR_SIGNED",
            "legacy_stack_running": False,
        }
    if gate_id is ProductionGateId.STORAGE_BACKUP_RESTORE_ROLLBACK_CURRENT:
        backup = artifacts[BoundArtifactRole.BACKUP]
        restore = artifacts[BoundArtifactRole.RESTORE]
        rollback = artifacts[BoundArtifactRole.ROLLBACK]
        return {
            "protected_storage": True,
            "store_identity_digest": backup.store_identity_digest,
            "backup_digest": backup.artifact_digest,
            "restore_digest": restore.artifact_digest,
            "rollback_digest": rollback.artifact_digest,
            "ambiguous_effect_count": 0,
            "unreconciled_ambiguous_effect_count": 0,
        }
    if gate_id is ProductionGateId.PUBLICATION_LIFECYCLE_SPECIFICATIONS_ACCEPTED:
        return {
            "accepted_spec_digests": _PUBLICATION_SPECS,
            "draft_count": 0,
        }
    if gate_id is ProductionGateId.CANARY_ROLLBACK_RESTORE_IDENTITY_BOUND:
        return {
            "canary_digest": artifacts[
                BoundArtifactRole.LIVE_EVIDENCE_INTAKE_CANARY_CLOSEOUT
            ].artifact_digest,
            "restore_digest": artifacts[BoundArtifactRole.RESTORE].artifact_digest,
            "rollback_digest": artifacts[BoundArtifactRole.ROLLBACK].artifact_digest,
            "same_identity": True,
        }
    if gate_id is ProductionGateId.SDLC_CORE_SERVICE_CURRENT:
        return {
            "risk_tier": "R4_RELEASE_OPERATIONAL",
            "core_status": "PASS",
            "service_status": "PASS",
            "owner_authority_required": True,
            "origin_main_present": True,
            "source_main_sha": identity_set.freeze.exact_main_sha,
            "source_main_tree": identity_set.freeze.exact_main_tree,
            "merged_main_ci_digest": digest_canonical({"merged_main_ci": "pass"}),
            "merged_main_ci_status": "PASS",
        }
    if gate_id is ProductionGateId.READINESS_INSPECTION_NON_EFFECT:
        return {
            "provider_calls": 0,
            "publication_effects": 0,
            "production_mutations": 0,
        }
    raise AssertionError(f"unhandled gate {gate_id}")


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
    gate_evidence = {
        gate_id: ProductionGateEvidence.build(
            gate_id=gate_id,
            identity_set=identity_set,
            bound_artifacts=bound_artifacts,
            accepted_publication_spec_digests=_PUBLICATION_SPECS,
            facts=_gate_facts(
                gate_id,
                identity_set=identity_set,
                bound_artifacts=bound_artifacts,
            ),
        )
        for gate_id in PRODUCTION_GATE_IDS
    }
    manifest = ProductionEvidenceManifest.build(
        identity_set=identity_set,
        gate_evidence=gate_evidence,
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
            status=(
                ReadinessStatus.BLOCKED
                if manifest.gate_evidence[gate_id].blockers
                else ReadinessStatus.PASS
            ),
            blockers=manifest.gate_evidence[gate_id].blockers,
            issuer_identity="service:newsroom-evidence-authority",
            sealed_at="2026-08-26T10:00:00Z",
            signing_key=_EVIDENCE_KEY,
        )
        for gate_id in PRODUCTION_GATE_IDS
    )


def _owner_issue_record(
    authority_issue_number: int = 900,
    *,
    report: ProductionReadinessReport | None = None,
    manifest: ProductionEvidenceManifest | None = None,
) -> OwnerIssueRecord:
    if report is None and manifest is None:
        manifest, attestations = _complete_evidence()
        report = inspect_readiness(
            freeze=_FREEZE,
            evidence_manifest=manifest,
            attestations=attestations,
            trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
        )
    if report is None or manifest is None:
        raise AssertionError("owner issue helper needs both report and manifest")
    return OwnerIssueRecord.from_github_api(
        {
            "number": authority_issue_number,
            "html_url": (
                f"https://github.com/fol2/newsroom/issues/{authority_issue_number}"
            ),
            "node_id": f"I_fixture_{authority_issue_number}",
            "updated_at": "2026-08-26T10:28:00Z",
            "user": {"login": "fol2"},
            "author_association": "OWNER",
            "state": "open",
            "title": "Production Operational Admission instruction",
            "body": (
                "Exact owner production-admission instruction.\n\n"
                + owner_issue_binding_marker(
                    report=report,
                    evidence_manifest=manifest,
                    production_signing_key=_PRODUCTION_KEY,
                )
            ),
        }
    )


def _owner_instruction(
    *,
    report: ProductionReadinessReport,
    manifest: ProductionEvidenceManifest,
    authority_issue_number: int = 900,
    issued_at: str = "2026-08-26T10:30:00Z",
) -> OwnerAdmissionInstruction:
    snapshot = OwnerIssueSnapshot.build(
        owner_issue=_owner_issue_record(
            authority_issue_number,
            report=report,
            manifest=manifest,
        ),
        captured_at="2026-08-26T10:29:00Z",
        report=report,
        evidence_manifest=manifest,
        production_signing_key=_PRODUCTION_KEY,
        owner_signing_key=_OWNER_KEY,
    )
    return OwnerAdmissionInstruction.build(
        authority_issue_snapshot=snapshot,
        issued_at=issued_at,
        report=report,
        evidence_manifest=manifest,
        production_signing_key=_PRODUCTION_KEY,
        owner_signing_key=_OWNER_KEY,
    )


def _rebuild_manifest(
    source: ProductionEvidenceManifest,
    *,
    bound_artifacts: tuple[BoundArtifact, ...] | None = None,
    accepted_publication_spec_digests: dict[str, str] | None = None,
    gate_fact_overrides: dict[ProductionGateId, dict[str, object]] | None = None,
    fixture_admission_inherited: bool | None = None,
    readiness_provider_calls: int | None = None,
) -> ProductionEvidenceManifest:
    selected_bound = (
        source.bound_artifacts if bound_artifacts is None else bound_artifacts
    )
    selected_specs = (
        source.accepted_publication_spec_digests
        if accepted_publication_spec_digests is None
        else accepted_publication_spec_digests
    )
    gate_evidence = {
        gate_id: ProductionGateEvidence.build(
            gate_id=gate_id,
            identity_set=source.identity_set,
            bound_artifacts=selected_bound,
            accepted_publication_spec_digests=selected_specs,
            facts=(
                evidence.facts
                if gate_fact_overrides is None or gate_id not in gate_fact_overrides
                else gate_fact_overrides[gate_id]
            ),
        )
        for gate_id, evidence in source.gate_evidence.items()
    }
    return ProductionEvidenceManifest.build(
        identity_set=source.identity_set,
        gate_evidence=gate_evidence,
        bound_artifacts=selected_bound,
        accepted_publication_spec_digests=selected_specs,
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


def test_typed_coverage_evidence_prevents_an_arbitrary_signed_pass() -> None:
    manifest, _ = _complete_evidence()
    gate_id = ProductionGateId.EFFECTIVE_REVISION_COVERAGE_CURRENT
    incomplete_facts = dict(manifest.gate_evidence[gate_id].facts)
    incomplete_facts.update(
        {
            "terminal_revisions": 6,
            "terminal_coverage_ppm": 3_735,
        }
    )
    incomplete = _rebuild_manifest(
        manifest,
        gate_fact_overrides={gate_id: incomplete_facts},
    )

    with pytest.raises(ProductionAdmissionError, match="failing retained evidence"):
        GateAttestation.build(
            gate_id=gate_id,
            evidence_manifest=incomplete,
            status=ReadinessStatus.PASS,
            blockers=(),
            issuer_identity="service:newsroom-evidence-authority",
            sealed_at="2026-08-26T10:00:00Z",
            signing_key=_EVIDENCE_KEY,
        )

    report = inspect_readiness(
        freeze=_FREEZE,
        evidence_manifest=incomplete,
        attestations=_resign(incomplete),
        trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
    )
    result = next(item for item in report.gates if item.gate_id is gate_id)
    assert result.blockers == ("TERMINAL_EFFECTIVE_REVISION_COVERAGE_INCOMPLETE",)


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
    assert result.blockers == ("PUBLICATION_SPECIFICATIONS_NOT_ACCEPTED",)


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


def test_backup_restore_and_rollback_must_bind_the_same_store() -> None:
    manifest, _ = _complete_evidence()
    drifted_store = digest_canonical({"store": "backup-only-drift"})
    artifacts = tuple(
        (
            BoundArtifact.build(
                role=item.role,
                artifact_digest=item.artifact_digest,
                freeze=item.freeze,
                operational_manifest_digest=item.operational_manifest_digest,
                identity_set_digest=item.identity_set_digest,
                deployment_bytes_digest=item.deployment_bytes_digest,
                store_identity_digest=drifted_store,
                stop_conditions_digest=item.stop_conditions_digest,
                reconciliation_procedure_digest=(item.reconciliation_procedure_digest),
                outcome=item.outcome,
            )
            if item.role is BoundArtifactRole.BACKUP
            else item
        )
        for item in manifest.bound_artifacts
    )
    gate_id = ProductionGateId.STORAGE_BACKUP_RESTORE_ROLLBACK_CURRENT
    updated_facts = dict(manifest.gate_evidence[gate_id].facts)
    updated_facts["store_identity_digest"] = drifted_store
    drifted = _rebuild_manifest(
        manifest,
        bound_artifacts=artifacts,
        gate_fact_overrides={gate_id: updated_facts},
    )

    report = inspect_readiness(
        freeze=_FREEZE,
        evidence_manifest=drifted,
        attestations=_resign(drifted),
        trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
    )

    gate = next(result for result in report.gates if result.gate_id is gate_id)
    assert gate.blockers == ("BACKUP_RESTORE_ROLLBACK_STORE_IDENTITY_DRIFT",)


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
    instruction = _owner_instruction(
        report=report,
        manifest=manifest,
    )

    first = mint_production_operational_admission(
        freeze=_FREEZE,
        report=report,
        evidence_manifest=manifest,
        attestations=attestations,
        trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
        owner_instruction=instruction,
        current_owner_issue=_owner_issue_record(),
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
        current_owner_issue=_owner_issue_record(),
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
    assert (
        first.authority_issue_snapshot_digest
        == instruction.authority_issue_snapshot.digest
    )
    assert (
        OwnerIssueSnapshot.from_canonical_bytes(
            instruction.authority_issue_snapshot.canonical_bytes
        )
        == instruction.authority_issue_snapshot
    )


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
    with pytest.raises(ProductionAdmissionError, match="owner evidence binding"):
        OwnerIssueSnapshot.build(
            owner_issue=_owner_issue_record(),
            captured_at="2026-08-26T10:29:00Z",
            report=report,
            evidence_manifest=manifest,
            production_signing_key=_PRODUCTION_KEY,
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
        OwnerIssueSnapshot.build(
            owner_issue=OwnerIssueRecord(
                authority_issue_number=760,
                authority_issue_url="https://github.com/fol2/newsroom/issues/760",
                authority_issue_node_id="I_fixture_760",
                authority_issue_updated_at="2026-08-26T10:28:00Z",
                owner_identity="github:fol2",
                title="Production Operational Admission instruction",
                body=owner_issue_binding_marker(
                    report=report,
                    evidence_manifest=manifest,
                    production_signing_key=_PRODUCTION_KEY,
                ),
            ),
            captured_at="2026-08-26T10:29:00Z",
            report=report,
            evidence_manifest=manifest,
            production_signing_key=_PRODUCTION_KEY,
            owner_signing_key=_OWNER_KEY,
        )


def test_owner_issue_must_retain_the_exact_machine_readable_binding() -> None:
    manifest, attestations = _complete_evidence()
    report = inspect_readiness(
        freeze=_FREEZE,
        evidence_manifest=manifest,
        attestations=attestations,
        trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
    )
    issue_without_binding = replace(
        _owner_issue_record(report=report, manifest=manifest),
        body="An unstructured approval with no exact retained identities.",
    )

    with pytest.raises(ProductionAdmissionError, match="binding is absent"):
        OwnerIssueSnapshot.build(
            owner_issue=issue_without_binding,
            captured_at="2026-08-26T10:29:00Z",
            report=report,
            evidence_manifest=manifest,
            production_signing_key=_PRODUCTION_KEY,
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
    instruction = _owner_instruction(
        report=report,
        manifest=manifest,
    )

    with pytest.raises(ProductionAdmissionError, match="owner instruction"):
        mint_production_operational_admission(
            freeze=_FREEZE,
            report=report,
            evidence_manifest=manifest,
            attestations=attestations,
            trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
            owner_instruction=replace(instruction, owner_identity="github:someone"),
            current_owner_issue=_owner_issue_record(),
            trusted_owner_keys={_OWNER_KEY.key_id: _OWNER_KEY},
            production_signing_key=_PRODUCTION_KEY,
        )

    other_key = AuthenticationKey(
        key_id="keychain:another-production-key",
        key_class=KeyClass.PRODUCTION_OPERATIONAL_ADMISSION,
        provenance=KeyProvenance.TEST_FIXTURE,
        secret=b"x" * 32,
    )
    with pytest.raises(ProductionAdmissionError, match="trust-root key"):
        mint_production_operational_admission(
            freeze=_FREEZE,
            report=report,
            evidence_manifest=manifest,
            attestations=attestations,
            trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
            owner_instruction=instruction,
            current_owner_issue=_owner_issue_record(),
            trusted_owner_keys={_OWNER_KEY.key_id: _OWNER_KEY},
            production_signing_key=other_key,
        )

    fixture_key = AuthenticationKey(
        key_id=_PRODUCTION_KEY.key_id,
        key_class=KeyClass.PRODUCTION_OPERATIONAL_ADMISSION,
        provenance=KeyProvenance.TEST_FIXTURE,
        secret=_PRODUCTION_KEY.secret,
    )
    with pytest.raises(ProductionAdmissionError, match="trust-root key"):
        mint_production_operational_admission(
            freeze=_FREEZE,
            report=report,
            evidence_manifest=manifest,
            attestations=attestations,
            trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
            owner_instruction=instruction,
            current_owner_issue=_owner_issue_record(),
            trusted_owner_keys={_OWNER_KEY.key_id: _OWNER_KEY},
            production_signing_key=fixture_key,
        )

    same_id_different_secret = AuthenticationKey(
        key_id=_PRODUCTION_KEY.key_id,
        key_class=KeyClass.PRODUCTION_OPERATIONAL_ADMISSION,
        provenance=KeyProvenance.PRODUCTION_TRUST_ROOT,
        secret=b"q" * 32,
    )
    with pytest.raises(ProductionAdmissionError, match="fingerprint differs"):
        mint_production_operational_admission(
            freeze=_FREEZE,
            report=report,
            evidence_manifest=manifest,
            attestations=attestations,
            trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
            owner_instruction=instruction,
            current_owner_issue=_owner_issue_record(),
            trusted_owner_keys={_OWNER_KEY.key_id: _OWNER_KEY},
            production_signing_key=same_id_different_secret,
        )


def test_mint_refuses_live_owner_issue_drift() -> None:
    manifest, attestations = _complete_evidence()
    report = inspect_readiness(
        freeze=_FREEZE,
        evidence_manifest=manifest,
        attestations=attestations,
        trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
    )
    instruction = _owner_instruction(report=report, manifest=manifest)
    drifted_issue = replace(
        _owner_issue_record(),
        title="Owner edited the issue",
    )

    with pytest.raises(ProductionAdmissionError, match="live authority"):
        mint_production_operational_admission(
            freeze=_FREEZE,
            report=report,
            evidence_manifest=manifest,
            attestations=attestations,
            trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
            owner_instruction=instruction,
            current_owner_issue=drifted_issue,
            trusted_owner_keys={_OWNER_KEY.key_id: _OWNER_KEY},
            production_signing_key=_PRODUCTION_KEY,
        )


def test_verification_refuses_an_owner_instruction_for_different_evidence() -> None:
    manifest, attestations = _complete_evidence()
    report = inspect_readiness(
        freeze=_FREEZE,
        evidence_manifest=manifest,
        attestations=attestations,
        trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
    )
    instruction = _owner_instruction(
        report=report,
        manifest=manifest,
    )
    admission = mint_production_operational_admission(
        freeze=_FREEZE,
        report=report,
        evidence_manifest=manifest,
        attestations=attestations,
        trusted_evidence_keys={_EVIDENCE_KEY.key_id: _EVIDENCE_KEY},
        owner_instruction=instruction,
        current_owner_issue=_owner_issue_record(),
        trusted_owner_keys={_OWNER_KEY.key_id: _OWNER_KEY},
        production_signing_key=_PRODUCTION_KEY,
    )

    other_manifest = ProductionEvidenceManifest.build(
        identity_set=manifest.identity_set,
        gate_evidence=manifest.gate_evidence,
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
    other_instruction = _owner_instruction(
        authority_issue_number=901,
        issued_at="2026-08-26T10:31:00Z",
        report=other_report,
        manifest=other_manifest,
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
