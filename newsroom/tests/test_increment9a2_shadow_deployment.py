from __future__ import annotations

import json
import sqlite3
import stat
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace

import pytest

from newsroom.authority import migrations as production_migrations
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment9.deployment import (
    ACTUAL_HOST_PROBES,
    ACTUAL_SERVICE_PROBES,
    EXPECTED_COMPONENT_LOCKS,
    EXPECTED_CREDENTIAL_CLASSES,
    EXPECTED_EGRESS_DESTINATIONS,
    EXPECTED_PROBES,
    PROHIBITED_CREDENTIAL_CLASSES,
    DeploymentError,
    DeploymentPlan,
    DeploymentReadinessReceipt,
    EgressPolicy,
    ISOLATED_DIRECTORY_INVENTORY,
    ISOLATED_FILE_INVENTORY,
    IsolatedDeploymentReceipt,
    ProbeEvidence,
    ProbeOutcome,
    ReadinessDisposition,
    ReadinessEvidenceBundle,
    ServiceClass,
    admit_readiness_egress,
    build_deployment_plan,
    expected_probe_identity_digest,
    materialise_isolated_deployment,
    probe_increment9_neo4j,
    probe_macm4_capacity,
    qualify_deployment,
    teardown_isolated_deployment,
    verify_materialised_deployment,
    verify_isolated_sqlite_backup_restore,
)
from newsroom.increment9.plan import INCREMENT_9_SHADOW_PLAN, INCREMENT_9_SHADOW_PLAN_DIGEST
from newsroom.increment9.shadow_contracts import (
    SHADOW_MANIFEST_VERSION,
    ClosureReason,
    DifferenceMateriality,
    ProductionAuthorityReference,
    ProductionDifference,
    ProhibitedEffect,
    ProtectedArtifactClass,
    ProtectedArtifactRule,
    ShadowAccessBoundary,
    ShadowAuthorityIdentity,
    ShadowEffect,
    ShadowManifest,
    ShadowOutcome,
    ShadowScope,
    StopAndClosurePolicy,
)

D = lambda character: "sha256:" + character * 64


def _decisions() -> dict[str, object]:
    return {item.decision_id: item.selection for item in INCREMENT_9_SHADOW_PLAN.owner_decisions}


def _scope(production_snapshot_digest: str = D("1")) -> ShadowScope:
    decisions = _decisions()
    od2 = decisions["OD-002"]
    od3 = decisions["OD-003"]
    od4 = decisions["OD-004"]
    od12 = decisions["OD-012"]
    od13 = decisions["OD-013"]
    od14 = decisions["OD-014"]
    principal = D("7")
    material = set(od13["known_material_differences"])
    differences = tuple(
        ProductionDifference(
            difference_id=item,
            materiality=(
                DifferenceMateriality.MATERIAL
                if item in material
                else DifferenceMateriality.NON_MATERIAL
            ),
            statement=item.replace("_", " ").title(),
            inference_limit="COMPONENT_SCOPED_EQUIVALENCE_ONLY",
        )
        for item in sorted(material | set(od13["known_non_material_differences"]))
    )
    retention = {
        ProtectedArtifactClass.AUDIT_LEDGER: 90,
        ProtectedArtifactClass.BACKUP: 30,
        ProtectedArtifactClass.CREDENTIAL_METADATA: 90,
        ProtectedArtifactClass.EMBEDDING_INPUT: 30,
        ProtectedArtifactClass.GOVERNED_PASSAGE: 30,
        ProtectedArtifactClass.MODEL_INPUT_OUTPUT: 30,
        ProtectedArtifactClass.RAW_HTTP: 7,
        ProtectedArtifactClass.REVIEW_RESEARCH_BYTES: 30,
        ProtectedArtifactClass.RIGHTS_RECORD: 90,
    }
    deadlines = od14["containment_owner_and_deadline"]
    return ShadowScope(
        scope_id="increment9-shadow-scope-9a2-fixture",
        plan_digest=INCREMENT_9_SHADOW_PLAN_DIGEST,
        production_authority=ProductionAuthorityReference(
            authority="SQLITE_AND_GOVERNED_OBJECTS",
            schema_version=od2["schema_version_and_fingerprint"]["schema_version"],
            schema_fingerprint=od2["schema_version_and_fingerprint"]["schema_fingerprint"],
            migration_history_digest=od2["migration_history_digest"],
            snapshot_digest=production_snapshot_digest,
            export_digest=D("2"),
            cutoff_at="2042-01-01T00:00:00.000000Z",
            watermark="ledger:42",
        ),
        shadow_authority=ShadowAuthorityIdentity(
            authority_id="increment9-shadow-authority-9a2-fixture",
            sqlite_identity=od2["shadow_copy_identity"],
            neo4j_database=od3["database_and_namespace"]["database"],
            neo4j_namespace=od3["database_and_namespace"]["namespace"],
            graphiti_workspace=od4["proposal_workspace_identity"],
            principal_identity_digest=principal,
        ),
        access_boundary=ShadowAccessBoundary(
            purpose_identity="increment9-evaluation-only",
            principal_identity_digest=principal,
            permitted_credential_classes=tuple(
                sorted(
                    set(od12["credential_classes_and_secret_locations"]["classes"])
                    - {"PUBLICATION_TARGET_ADAPTER"}
                )
            ),
            prohibited_credential_classes=("PUBLICATION_TARGET_ADAPTER",),
            egress_policy_digest=D("8"),
            artefact_policy_digest=D("9"),
        ),
        allowed_effects=tuple(sorted(ShadowEffect, key=str)),
        prohibited_effects=tuple(sorted(ProhibitedEffect, key=str)),
        outcomes=tuple(sorted(ShadowOutcome, key=str)),
        production_differences=differences,
        protected_artifacts=tuple(
            ProtectedArtifactRule(
                artifact_class=kind,
                lineage_required=True,
                encrypted_at_rest=True,
                retention_days_max=retention[kind],
                rights_revocation_purge_hours=24,
            )
            for kind in sorted(ProtectedArtifactClass, key=str)
        ),
        stop_and_closure=StopAndClosurePolicy(
            owner_decision_id="OD-014",
            global_kill_authority="HERMES_AND_AUTHENTICATED_HUMAN_OWNER",
            scoped_kill_authority="HERMES_AND_AUTHENTICATED_HUMAN_OWNER",
            p0_kill_seconds=deadlines["p0_kill_seconds"],
            p0_revoke_seconds=deadlines["p0_revoke_seconds"],
            p0_notify_seconds=deadlines["p0_human_notify_seconds"],
            p0_contain_seconds=deadlines["p0_contain_seconds"],
            p1_stop_seconds=deadlines["p1_stop_seconds"],
            p1_notify_seconds=deadlines["p1_notify_seconds"],
            p1_contain_seconds=deadlines["p1_contain_seconds"],
            closure_reasons=tuple(sorted(ClosureReason, key=str)),
            decision_bearing_later_phase_after_early_stop_allowed=False,
            autonomous_recovery_evidence_after_early_stop_allowed=True,
        ),
        created_at="2042-01-01T00:00:00.000000Z",
        expires_at="2042-01-29T00:00:00.000000Z",
    )


def _manifest(scope: ShadowScope) -> ShadowManifest:
    return ShadowManifest(
        manifest_id="increment9-shadow-manifest-9a2-fixture",
        manifest_version=SHADOW_MANIFEST_VERSION,
        version_ordinal=1,
        previous_manifest_digest=None,
        scope_digest=scope.canonical_digest,
        plan_digest=scope.plan_digest,
        effective_manifest_digest=D("3"),
        production_snapshot_digest=scope.production_authority.snapshot_digest,
        shadow_authority_id=scope.shadow_authority.authority_id,
        principal_identity_digest=scope.shadow_authority.principal_identity_digest,
        purpose_identity=scope.access_boundary.purpose_identity,
        egress_policy_digest=scope.access_boundary.egress_policy_digest,
        artefact_policy_digest=scope.access_boundary.artefact_policy_digest,
        created_at="2042-01-01T00:01:00.000000Z",
        expires_at=scope.expires_at,
    )


def _plan(production_snapshot_digest: str = D("1")) -> DeploymentPlan:
    scope = _scope(production_snapshot_digest)
    return build_deployment_plan(
        scope,
        _manifest(scope),
        deployment_id="increment9-deployment-9a2-fixture",
        effective_identity_digests={
            name: D(character)
            for name, character in zip(
                (
                    "controller_code",
                    "controller_config",
                    "graphiti_adapter_code",
                    "ontology_mapping_code",
                    "projector_code",
                ),
                "abcde",
                strict=True,
            )
        },
        created_at="2042-01-01T00:02:00.000000Z",
    )


def _service_class(probe_id: str) -> ServiceClass:
    if probe_id in ACTUAL_SERVICE_PROBES:
        return ServiceClass.ACTUAL_ISOLATED_SERVICE
    if probe_id in ACTUAL_HOST_PROBES:
        return ServiceClass.ACTUAL_ISOLATED_HOST
    return ServiceClass.DETERMINISTIC_FIXTURE


def _bundle(plan: DeploymentPlan, **changes: object) -> ReadinessEvidenceBundle:
    probes = tuple(
        ProbeEvidence(
            probe_id=probe_id,
            outcome=ProbeOutcome.PASS,
            service_class=(service_class := _service_class(probe_id)),
            evidence_digest=D("f"),
            observed_identity_digest=expected_probe_identity_digest(
                plan, probe_id, service_class
            ),
            started_at="2042-01-01T00:03:00.000000Z",
            completed_at="2042-01-01T00:04:00.000000Z",
        )
        for probe_id in EXPECTED_PROBES
    )
    values: dict[str, object] = {
        "bundle_id": "increment9-readiness-bundle-fixture",
        "deployment_plan_digest": plan.canonical_digest,
        "scope_digest": plan.scope_digest,
        "manifest_digest": plan.manifest_digest,
        "production_before_digest": plan.production_snapshot_digest,
        "production_after_digest": plan.production_snapshot_digest,
        "probes": probes,
        "sealed_at": "2042-01-01T00:05:00.000000Z",
    }
    values.update(changes)
    return ReadinessEvidenceBundle(**values)  # type: ignore[arg-type]


def test_plan_round_trips_and_binds_exact_owner_decisions() -> None:
    plan = _plan()
    assert DeploymentPlan.from_bytes(plan.canonical_bytes) == plan
    assert plan.owner_plan_digest == INCREMENT_9_SHADOW_PLAN_DIGEST
    assert dict(plan.component_locks) == dict(EXPECTED_COMPONENT_LOCKS)
    assert plan.credential_classes == EXPECTED_CREDENTIAL_CLASSES
    assert plan.prohibited_credential_classes == PROHIBITED_CREDENTIAL_CLASSES
    assert plan.egress_policy.configured_destinations == EXPECTED_EGRESS_DESTINATIONS
    assert plan.egress_policy.readiness_destinations == ("LOCAL_FILESYSTEM", "LOCAL_NEO4J")


def test_deployment_plan_is_frozen_and_remains_readiness_only() -> None:
    plan = _plan()
    with pytest.raises(FrozenInstanceError):
        plan.deployment_id = "changed"  # type: ignore[misc]
    assert plan.authorises_readiness_local_neo4j is True
    assert plan.authorises_readiness_shadow_credentials is True
    assert plan.authorises_campaign is False
    assert plan.authorises_source_portfolio_io is False
    assert plan.authorises_provider_or_model_call is False
    assert plan.authorises_publication is False
    assert plan.authorises_evidence_intake is False
    assert plan.authorises_canary is False
    assert plan.authorises_production_mutation is False


@pytest.mark.parametrize("kind", ("unknown", "duplicate", "noncanonical"))
def test_strict_plan_parser_rejects_unknown_duplicate_and_noncanonical_bytes(kind: str) -> None:
    raw = _plan().canonical_bytes
    if kind == "unknown":
        value = json.loads(raw)
        value["unknown"] = True
        raw = canonical_json_bytes(value)
    elif kind == "duplicate":
        raw = raw.replace(b'{"component_locks":', b'{"component_locks":{},"component_locks":', 1)
    else:
        raw += b"\n"
    with pytest.raises(DeploymentError):
        DeploymentPlan.from_bytes(raw)


def test_deployment_rejects_component_or_effect_drift() -> None:
    plan = _plan()
    with pytest.raises(DeploymentError, match="component locks"):
        replace(plan, component_locks={**plan.component_locks, "neo4j_image": "neo4j:latest"})
    with pytest.raises(DeploymentError, match="non-effect"):
        replace(plan, public_effect_adapter_present=True)
    with pytest.raises(DeploymentError, match="production reads"):
        replace(plan, production_reads_after_snapshot=1)


def test_nested_policy_and_scalar_types_are_strict() -> None:
    with pytest.raises(DeploymentError, match="boolean"):
        EgressPolicy(default_deny=1)  # type: ignore[arg-type]
    with pytest.raises(DeploymentError, match="tuples"):
        EgressPolicy(configured_destinations=list(EXPECTED_EGRESS_DESTINATIONS))  # type: ignore[arg-type]
    with pytest.raises(DeploymentError, match="bounded integer"):
        replace(_plan(), production_reads_after_snapshot=False)


def test_sqlite_backup_restore_uses_exact_schema_identity() -> None:
    result = verify_isolated_sqlite_backup_restore()
    assert result.startswith("sha256:") and len(result) == 71


def _production_snapshot(tmp_path):
    path = tmp_path / "frozen-production-v32.sqlite3"
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        production_migrations.apply_pending_migrations(
            connection, applied_at="2042-01-01T00:00:00.000000Z"
        )
    finally:
        connection.close()
    path.chmod(0o600)
    return path, digest_bytes(path.read_bytes())


def _materialise(tmp_path):
    snapshot, snapshot_digest = _production_snapshot(tmp_path)
    plan = _plan(snapshot_digest)
    parent = tmp_path / "protected"
    parent.mkdir(mode=0o700)
    root = parent / plan.deployment_id
    receipt = materialise_isolated_deployment(
        plan,
        root=root,
        production_snapshot=snapshot,
        receipt_id="increment9-isolated-deployment-receipt",
        created_at="2042-01-01T00:03:00.000000Z",
    )
    return plan, root, receipt, snapshot


def test_materialised_deployment_is_private_exact_and_restorable(tmp_path) -> None:
    plan, root, receipt, _ = _materialise(tmp_path)
    assert IsolatedDeploymentReceipt.from_bytes(receipt.canonical_bytes) == receipt
    assert receipt.directory_inventory == ISOLATED_DIRECTORY_INVENTORY
    assert tuple(sorted(receipt.protected_file_digests)) == ISOLATED_FILE_INVENTORY
    assert receipt.secret_value_count == 0
    assert receipt.production_path_count == 0
    assert receipt.public_effect_adapter_count == 0
    assert receipt.encryption_access_audit_still_required is True
    assert receipt.epoch_schema_version == 1
    assert receipt.production_snapshot_schema_version == 32
    assert receipt.production_snapshot_digest == plan.production_snapshot_digest
    assert (root / "graphiti" / plan.graphiti_workspace).is_dir()
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    for relative in ISOLATED_FILE_INVENTORY:
        assert stat.S_IMODE((root / relative).stat().st_mode) == 0o600
    result = verify_materialised_deployment(plan, receipt, root=root)
    assert result.startswith("sha256:")
    forged = replace(
        receipt,
        protected_file_digests=dict(receipt.protected_file_digests),
        production_snapshot_backup_restore_digest=D("9"),
    )
    with pytest.raises(DeploymentError, match="backup and restore"):
        verify_materialised_deployment(plan, forged, root=root)


def test_materialised_deployment_rejects_tamper_extra_files_and_symlinks(tmp_path) -> None:
    plan, root, receipt, snapshot = _materialise(tmp_path)
    (root / "deployment-plan.json").write_bytes(b"tampered")
    with pytest.raises(DeploymentError, match="digest"):
        verify_materialised_deployment(plan, receipt, root=root)

    shutil_root = tmp_path / "second"
    shutil_root.mkdir(mode=0o700)
    second_root = shutil_root / plan.deployment_id
    second = materialise_isolated_deployment(
        plan,
        root=second_root,
        production_snapshot=snapshot,
        receipt_id="increment9-second-receipt",
        created_at="2042-01-01T00:03:00.000000Z",
    )
    (second_root / "unexpected").write_text("orphan", encoding="utf-8")
    with pytest.raises(DeploymentError, match="inventory"):
        verify_materialised_deployment(plan, second, root=second_root)


def test_materialisation_rejects_wrong_or_non_v32_frozen_snapshot(tmp_path) -> None:
    protected = tmp_path / "snapshot-negative"
    protected.mkdir(mode=0o700)
    wrong = protected / "wrong.sqlite3"
    sqlite3.connect(wrong).close()
    wrong.chmod(0o600)
    plan = _plan(digest_bytes(wrong.read_bytes()))
    root = protected / plan.deployment_id
    with pytest.raises(DeploymentError, match="production snapshot"):
        materialise_isolated_deployment(
            plan,
            root=root,
            production_snapshot=wrong,
            receipt_id="wrong-snapshot-receipt",
            created_at="2042-01-01T00:03:00.000000Z",
        )
    assert not root.exists()


def test_teardown_proves_purge_and_no_resurrection(tmp_path) -> None:
    plan, root, receipt, _ = _materialise(tmp_path)
    digest = teardown_isolated_deployment(plan, receipt, root=root)
    assert digest.startswith("sha256:")
    assert not root.exists()


def test_cli_materialises_verifies_and_tears_down_exact_authority(tmp_path) -> None:
    snapshot, snapshot_digest = _production_snapshot(tmp_path)
    plan = _plan(snapshot_digest)
    protected = tmp_path / "protected-cli"
    protected.mkdir(mode=0o700)
    plan_path = protected / "plan.json"
    plan_path.write_bytes(plan.canonical_bytes)
    plan_path.chmod(0o600)
    root = protected / plan.deployment_id
    receipt = protected / "receipt.json"
    verify = protected / "verify.json"
    teardown = protected / "teardown.json"
    base = [sys.executable, "scripts/increment9_shadow_deployment.py"]
    subprocess.run(
        base
        + [
            "materialise",
            "--plan",
            str(plan_path),
            "--root",
            str(root),
            "--production-snapshot",
            str(snapshot),
            "--receipt-id",
            "increment9-cli-materialised-receipt",
            "--created-at",
            "2042-01-01T00:03:00.000000Z",
            "--output",
            str(receipt),
        ],
        check=True,
    )
    subprocess.run(
        base
        + [
            "verify-materialised",
            "--plan",
            str(plan_path),
            "--receipt",
            str(receipt),
            "--root",
            str(root),
            "--output",
            str(verify),
        ],
        check=True,
    )
    subprocess.run(
        base
        + [
            "teardown",
            "--plan",
            str(plan_path),
            "--receipt",
            str(receipt),
            "--root",
            str(root),
            "--output",
            str(teardown),
        ],
        check=True,
    )
    assert not root.exists()
    for path in (receipt, verify, teardown):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert json.loads(path.read_bytes())["secret_value_count"] == 0


@pytest.mark.parametrize(
    "uri",
    (
        "https://localhost:7687",
        "bolt://TARGET:7687",
        "bolt://user:secret@localhost:7687",
        "bolt://localhost:7687/path",
    ),
)
def test_readiness_egress_default_denies_every_nonlocal_route(uri: str) -> None:
    with pytest.raises(DeploymentError, match="default-denied"):
        admit_readiness_egress(uri)
    assert admit_readiness_egress("bolt://127.0.0.1:7687") == "LOCAL_NEO4J"


def test_capacity_probe_is_read_only_and_secret_free() -> None:
    result = probe_macm4_capacity(root="/")
    assert result["secret_value_count"] == 0
    assert type(result["matches_od003"]) is bool
    assert str(result["evidence_digest"]).startswith("sha256:")


@pytest.mark.parametrize("command", ("sqlite-backup-restore", "capacity"))
def test_cli_writes_canonical_mode_0600_evidence(tmp_path, command: str) -> None:
    output = tmp_path / f"{command}.json"
    subprocess.run(
        [
            sys.executable,
            "scripts/increment9_shadow_deployment.py",
            command,
            "--output",
            str(output),
        ],
        check=True,
    )
    raw = output.read_bytes()
    assert raw == canonical_json_bytes(json.loads(raw))
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert json.loads(raw)["secret_value_count"] == 0


def test_exact_clean_bundle_grants_only_9b2_controller_qualification() -> None:
    plan = _plan()
    bundle = _bundle(plan)
    assert ReadinessEvidenceBundle.from_bytes(bundle.canonical_bytes) == bundle
    receipt = qualify_deployment(plan, bundle, receipt_id="increment9-readiness-receipt-fixture")
    assert receipt.disposition is ReadinessDisposition.READY_FOR_9B2_CONTROLLER_QUALIFICATION
    assert set(receipt.actual_service_probe_ids) == ACTUAL_SERVICE_PROBES
    assert receipt.production_nonmutation_proved is True
    assert receipt.teardown_complete is True
    assert receipt.runtime_campaign_authority_still_required is True
    assert receipt.authorises_campaign is False
    assert DeploymentReadinessReceipt.from_bytes(receipt.canonical_bytes) == receipt


def test_not_ready_receipt_cannot_claim_success_reason() -> None:
    plan = _plan()
    receipt = qualify_deployment(
        plan,
        replace(_bundle(plan), production_after_digest=D("9")),
        receipt_id="not-ready-receipt",
    )
    with pytest.raises(DeploymentError, match="not-ready receipt reason"):
        replace(receipt, reason="ALL_READINESS_PROBES_PASS")


@pytest.mark.parametrize(
    ("change", "expected"),
    (
        ("outcome", ReadinessDisposition.NOT_READY),
        ("secret", ReadinessDisposition.NOT_READY),
        ("orphan", ReadinessDisposition.NOT_READY),
        ("production", ReadinessDisposition.NOT_READY),
        ("identity", ReadinessDisposition.NOT_READY),
        ("service_class", ReadinessDisposition.NOT_READY),
    ),
)
def test_incomplete_or_unsafe_evidence_fails_closed(
    change: str, expected: ReadinessDisposition
) -> None:
    plan = _plan()
    bundle = _bundle(plan)
    probes = list(bundle.probes)
    if change == "outcome":
        probes[0] = replace(probes[0], outcome=ProbeOutcome.FAIL)
        bundle = replace(bundle, probes=tuple(probes))
    elif change == "secret":
        probes[0] = replace(probes[0], secret_value_count=1)
        bundle = replace(bundle, probes=tuple(probes))
    elif change == "orphan":
        probes[0] = replace(probes[0], orphan_resource_count=1)
        bundle = replace(bundle, probes=tuple(probes))
    elif change == "production":
        bundle = replace(bundle, production_after_digest=D("9"))
    elif change == "identity":
        probes[0] = replace(probes[0], observed_identity_digest=D("9"))
        bundle = replace(bundle, probes=tuple(probes))
    else:
        target = EXPECTED_PROBES.index("NEO4J_AUTHENTICATED")
        replacement = ServiceClass.DETERMINISTIC_FIXTURE
        probes[target] = replace(
            probes[target],
            service_class=replacement,
            observed_identity_digest=expected_probe_identity_digest(
                plan, probes[target].probe_id, replacement
            ),
        )
        bundle = replace(bundle, probes=tuple(probes))
    assert qualify_deployment(plan, bundle, receipt_id="failed-readiness").disposition is expected


def test_bundle_rejects_missing_reordered_or_campaign_evidence() -> None:
    plan = _plan()
    bundle = _bundle(plan)
    with pytest.raises(DeploymentError, match="exact and ordered"):
        replace(bundle, probes=bundle.probes[:-1])
    with pytest.raises(DeploymentError, match="exact and ordered"):
        replace(bundle, probes=tuple(reversed(bundle.probes)))
    with pytest.raises(DeploymentError, match="campaign"):
        replace(bundle, decision_bearing_case_count=1)


def test_bundle_before_plan_or_after_expiry_fails_closed() -> None:
    plan = _plan()
    bundle = _bundle(plan)
    probes = list(bundle.probes)
    probes[0] = replace(
        probes[0],
        started_at="2042-01-01T00:01:00.000000Z",
        completed_at="2042-01-01T00:01:30.000000Z",
    )
    early = replace(bundle, probes=tuple(probes))
    assert qualify_deployment(plan, early, receipt_id="early").disposition is ReadinessDisposition.NOT_READY
    late = replace(bundle, sealed_at="2042-01-29T00:00:01.000000Z")
    assert qualify_deployment(plan, late, receipt_id="late").disposition is ReadinessDisposition.NOT_READY


@pytest.mark.parametrize(
    "uri",
    (
        "bolt://TARGET:7687",
        "https://localhost:7687",
        "bolt://user:secret@localhost:7687",
        "bolt://localhost:7687/path",
    ),
)
def test_actual_service_probe_rejects_nonlocal_or_embedded_credentials(uri: str) -> None:
    with pytest.raises(DeploymentError, match="local and credential-separated"):
        probe_increment9_neo4j(uri=uri, username="neo4j", password="secret")
