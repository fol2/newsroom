from __future__ import annotations

import ast
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.increment9.plan import INCREMENT_9_SHADOW_PLAN, INCREMENT_9_SHADOW_PLAN_DIGEST
from newsroom.increment9.shadow_contracts import (
    SHADOW_MANIFEST,
    SHADOW_MANIFEST_VERSION,
    SHADOW_SCOPE,
    ClosureReason,
    DifferenceMateriality,
    ProductionAuthorityReference,
    ProductionDifference,
    ProhibitedEffect,
    ProtectedArtifactClass,
    ProtectedArtifactRule,
    ShadowAccessBoundary,
    ShadowAuthorityIdentity,
    ShadowContractError,
    ShadowEffect,
    ShadowManifest,
    ShadowOutcome,
    ShadowScope,
    StopAndClosurePolicy,
    _admit_for_later_deployment,
    validate_manifest_chain,
    validate_manifest_for_scope,
)

D = lambda character: "sha256:" + character * 64


def _decisions() -> dict[str, object]:
    return {
        item.decision_id: item.selection
        for item in INCREMENT_9_SHADOW_PLAN.owner_decisions
    }


def _scope() -> ShadowScope:
    decisions = _decisions()
    od2 = decisions["OD-002"]
    od3 = decisions["OD-003"]
    od4 = decisions["OD-004"]
    od12 = decisions["OD-012"]
    od13 = decisions["OD-013"]
    od14 = decisions["OD-014"]
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
        for item in sorted(
            material | set(od13["known_non_material_differences"])
        )
    )
    artifacts = tuple(
        ProtectedArtifactRule(
            artifact_class=kind,
            lineage_required=True,
            encrypted_at_rest=True,
            retention_days_max=retention[kind],
            rights_revocation_purge_hours=24,
        )
        for kind in sorted(ProtectedArtifactClass, key=str)
    )
    deadlines = od14["containment_owner_and_deadline"]
    principal = D("7")
    return ShadowScope(
        scope_id="increment9-shadow-scope-fixture",
        plan_digest=INCREMENT_9_SHADOW_PLAN_DIGEST,
        production_authority=ProductionAuthorityReference(
            authority="SQLITE_AND_GOVERNED_OBJECTS",
            schema_version=od2["schema_version_and_fingerprint"]["schema_version"],
            schema_fingerprint=od2["schema_version_and_fingerprint"]["schema_fingerprint"],
            migration_history_digest=od2["migration_history_digest"],
            snapshot_digest=D("1"),
            export_digest=D("2"),
            cutoff_at="2042-01-01T00:00:00.000000Z",
            watermark="ledger:42",
        ),
        shadow_authority=ShadowAuthorityIdentity(
            authority_id="increment9-shadow-authority-fixture",
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
        protected_artifacts=artifacts,
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


def _manifest(scope: ShadowScope | None = None, **changes: object) -> ShadowManifest:
    scope = scope or _scope()
    values: dict[str, object] = {
        "manifest_id": "increment9-shadow-manifest-fixture",
        "manifest_version": SHADOW_MANIFEST_VERSION,
        "version_ordinal": 1,
        "previous_manifest_digest": None,
        "scope_digest": scope.canonical_digest,
        "plan_digest": scope.plan_digest,
        "effective_manifest_digest": D("3"),
        "production_snapshot_digest": scope.production_authority.snapshot_digest,
        "shadow_authority_id": scope.shadow_authority.authority_id,
        "principal_identity_digest": scope.shadow_authority.principal_identity_digest,
        "purpose_identity": scope.access_boundary.purpose_identity,
        "egress_policy_digest": scope.access_boundary.egress_policy_digest,
        "artefact_policy_digest": scope.access_boundary.artefact_policy_digest,
        "created_at": "2042-01-01T00:01:00.000000Z",
        "expires_at": scope.expires_at,
    }
    values.update(changes)
    return ShadowManifest(**values)  # type: ignore[arg-type]


def test_scope_and_manifest_round_trip_exact_canonical_bytes() -> None:
    scope = _scope()
    manifest = _manifest(scope)
    assert ShadowScope.from_bytes(scope.canonical_bytes) == scope
    assert ShadowManifest.from_bytes(manifest.canonical_bytes) == manifest
    assert scope.canonical_bytes == canonical_json_bytes(json.loads(scope.canonical_bytes))
    assert validate_manifest_for_scope(scope, manifest) == manifest
    assert SHADOW_SCOPE.endswith("shadow-scope.v1")
    assert SHADOW_MANIFEST.endswith("shadow-manifest.v1")


@pytest.mark.parametrize("kind", ("unknown", "duplicate", "noncanonical"))
def test_strict_scope_parser_rejects_unknown_duplicate_and_noncanonical_bytes(
    kind: str,
) -> None:
    raw = _scope().canonical_bytes
    if kind == "unknown":
        value = json.loads(raw)
        value["unknown"] = True
        raw = canonical_json_bytes(value)
    elif kind == "duplicate":
        raw = raw.replace(
            b'{"access_boundary":',
            b'{"access_boundary":null,"access_boundary":',
            1,
        )
    else:
        raw += b"\n"
    with pytest.raises(ShadowContractError):
        ShadowScope.from_bytes(raw)


def test_strict_parser_rejects_nested_unknown_fields() -> None:
    value = json.loads(_scope().canonical_bytes)
    value["access_boundary"]["unknown"] = True
    with pytest.raises(ShadowContractError, match="access_boundary fields differ"):
        ShadowScope.from_bytes(canonical_json_bytes(value))


def test_contracts_are_frozen_and_have_no_effect_authority() -> None:
    scope = _scope()
    manifest = _manifest(scope)
    with pytest.raises(FrozenInstanceError):
        scope.scope_id = "changed"  # type: ignore[misc]
    for record in (scope, manifest, scope.access_boundary, scope.shadow_authority):
        assert record.authorises_deployment is False
        assert record.authorises_credentials is False
        assert record.authorises_external_egress is False
        assert record.authorises_spend is False
        assert record.authorises_shadow_campaign is False
        assert record.authorises_publication is False
        assert record.authorises_production_mutation is False
        assert record.exposes_connection is False


def test_allowed_and_prohibited_effect_sets_are_closed() -> None:
    scope = _scope()
    assert set(scope.allowed_effects) == set(ShadowEffect)
    assert set(scope.prohibited_effects) == set(ProhibitedEffect)
    assert ProhibitedEffect.EVIDENCE_INTAKE in scope.prohibited_effects
    assert ProhibitedEffect.PUBLICATION in scope.prohibited_effects
    assert ProhibitedEffect.PRODUCTION_AUTHORITY_MUTATION in scope.prohibited_effects
    with pytest.raises(ShadowContractError, match="prohibited effect closure"):
        replace(scope, prohibited_effects=scope.prohibited_effects[:-1])


def test_stale_partial_unavailable_rights_and_policy_outcomes_are_explicit() -> None:
    scope = _scope()
    assert set(scope.outcomes) == set(ShadowOutcome)
    assert {
        ShadowOutcome.STALE,
        ShadowOutcome.PARTIAL,
        ShadowOutcome.UNAVAILABLE,
        ShadowOutcome.RIGHTS_BLOCKED,
        ShadowOutcome.POLICY_BLOCKED,
    } <= set(scope.outcomes)
    with pytest.raises(ShadowContractError, match="outcome closure"):
        replace(scope, outcomes=(ShadowOutcome.AVAILABLE,))


def test_production_and_shadow_authorities_cannot_alias_or_drift() -> None:
    scope = _scope()
    with pytest.raises(ShadowContractError, match="OD-002"):
        replace(
            scope,
            production_authority=replace(scope.production_authority, schema_version=33),
        )
    with pytest.raises(ShadowContractError, match="OD-002/003/004"):
        replace(
            scope,
            shadow_authority=replace(scope.shadow_authority, neo4j_namespace="production"),
        )
    with pytest.raises(ShadowContractError, match="principal identities"):
        replace(
            scope,
            access_boundary=replace(scope.access_boundary, principal_identity_digest=D("0")),
        )


def test_owner_bound_credentials_differences_artifacts_and_deadlines_fail_closed() -> None:
    scope = _scope()
    with pytest.raises(ShadowContractError, match="credential classes"):
        replace(
            scope,
            access_boundary=replace(
                scope.access_boundary,
                permitted_credential_classes=(
                    scope.access_boundary.permitted_credential_classes[:-1]
                ),
            ),
        )
    with pytest.raises(ShadowContractError, match="publication credential"):
        replace(
            scope,
            access_boundary=replace(
                scope.access_boundary,
                permitted_credential_classes=tuple(
                    sorted(
                        (
                            set(scope.access_boundary.permitted_credential_classes)
                            - {"NEO4J_SHADOW_WRITER"}
                        )
                        | {"PUBLICATION_TARGET_ADAPTER"}
                    )
                ),
                prohibited_credential_classes=("NEO4J_SHADOW_WRITER",),
            ),
        )
    with pytest.raises(ShadowContractError, match="production-equivalence"):
        replace(scope, production_differences=scope.production_differences[:-1])
    with pytest.raises(ShadowContractError, match="artefact inventory"):
        replace(scope, protected_artifacts=scope.protected_artifacts[:-1])
    with pytest.raises(ShadowContractError, match="containment deadlines"):
        replace(
            scope,
            stop_and_closure=replace(scope.stop_and_closure, p0_kill_seconds=61),
        )


def test_protected_artifacts_require_lineage_encryption_retention_and_purge() -> None:
    rule = _scope().protected_artifacts[0]
    with pytest.raises(ShadowContractError, match="lineage and encryption"):
        replace(rule, lineage_required=False)
    with pytest.raises(ShadowContractError, match="bounded integer"):
        replace(rule, retention_days_max=0)
    with pytest.raises(ShadowContractError, match="bounded integer"):
        replace(rule, rights_revocation_purge_hours=0)


def test_scope_and_manifest_have_hard_expiry_and_exact_access_identity() -> None:
    scope = _scope()
    with pytest.raises(ShadowContractError, match="expiry"):
        replace(scope, expires_at=scope.created_at)
    manifest = _manifest(scope)
    with pytest.raises(ShadowContractError, match="exceeds scope expiry"):
        validate_manifest_for_scope(
            scope,
            replace(manifest, expires_at="2042-01-30T00:00:00.000000Z"),
        )
    with pytest.raises(ShadowContractError, match="access policy"):
        validate_manifest_for_scope(
            scope, replace(manifest, egress_policy_digest=D("0"))
        )


def test_manifest_versions_form_one_contiguous_content_addressed_chain() -> None:
    scope = _scope()
    first = _manifest(scope)
    second = _manifest(
        scope,
        manifest_id="increment9-shadow-manifest-fixture-2",
        version_ordinal=2,
        previous_manifest_digest=first.canonical_digest,
        effective_manifest_digest=D("4"),
        created_at="2042-01-02T00:00:00.000000Z",
    )
    assert validate_manifest_chain(scope, (first, second)) == (first, second)
    with pytest.raises(ShadowContractError, match="predecessor"):
        validate_manifest_chain(
            scope, (first, replace(second, previous_manifest_digest=D("0")))
        )
    with pytest.raises(ShadowContractError, match="ordinal"):
        validate_manifest_chain(scope, (first, replace(second, version_ordinal=3)))


def test_early_stop_blocks_decision_phases_but_retains_recovery_proof() -> None:
    policy = _scope().stop_and_closure
    assert policy.decision_bearing_later_phase_after_early_stop_allowed is False
    assert policy.autonomous_recovery_evidence_after_early_stop_allowed is True
    with pytest.raises(ShadowContractError, match="later phases"):
        replace(
            policy,
            decision_bearing_later_phase_after_early_stop_allowed=True,
        )
    with pytest.raises(ShadowContractError, match="recovery evidence"):
        replace(
            policy,
            autonomous_recovery_evidence_after_early_stop_allowed=False,
        )


def test_private_deployment_seam_returns_only_an_inert_identity_receipt() -> None:
    scope = _scope()
    manifest = _manifest(scope)
    permit = _admit_for_later_deployment(scope, manifest)
    assert permit.manifest_digest == manifest.canonical_digest
    assert permit.shadow_authority_id == scope.shadow_authority.authority_id
    assert permit.authorises_deployment is False
    assert permit.authorises_credentials is False
    assert not hasattr(permit, "connection")
    assert not hasattr(permit, "credential")


def test_contract_module_has_no_network_database_subprocess_or_secret_import() -> None:
    path = Path("newsroom/increment9/shadow_contracts.py")
    tree = ast.parse(path.read_text())
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imports.isdisjoint(
        {"asyncio", "httpx", "neo4j", "requests", "socket", "sqlite3", "subprocess"}
    )
    raw = path.read_text().lower()
    assert "authorization: bearer" not in raw
    assert "-----begin private key-----" not in raw
    assert "sk-proj-" not in raw
