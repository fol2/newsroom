from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from newsroom.authority import (
    HydrationPolicyContract,
    HydrationPolicyRegistry,
    ObjectAdmissionDenied,
    ObjectHydrationDenied,
    ObjectLimits,
    UtcTimestamp,
    open_governed_object_authority_system,
)
from newsroom.integrated import (
    IntegratedFoundationProofController,
    IntegratedProofEnvironment,
    IntegratedProofKeys,
    IntegratedStateError,
)
from newsroom.projection.neo4j import Neo4jProjectorConfig

from .authority_a2b_helpers import _policy_registries
from .integrated_c1_helpers import (
    authenticator,
    authorizer,
    event_policy,
    integrated_registries,
    manifest,
    proof,
    scopes,
)
from .projection_b1_helpers import (
    FAMILY_ID,
    projection_contracts,
    projection_read_policy,
)
from .test_integrated_c1_contracts import context


def _limits() -> ObjectLimits:
    return ObjectLimits(
        global_max_bytes=1024 * 1024,
        class_max_bytes={"source_capture": 1024 * 1024},
        max_read_bytes=1024 * 1024,
        min_free_bytes=0,
        io_chunk_bytes=64,
        max_staging_bytes=1024 * 1024,
        max_range_bytes=1024 * 1024,
    )


def _config() -> Neo4jProjectorConfig:
    return Neo4jProjectorConfig(
        uri="bolt://localhost:7687",
        database="neo4j",
        username="newsroom_projector",
        password="integrated-test-password",
    )


def _environment(
    tmp_path: Path,
    *,
    hydration_policies: HydrationPolicyRegistry | None = None,
    hydration_purpose: str = "project.discovery",
) -> IntegratedProofEnvironment:
    rights, default_hydration, admissions = _policy_registries()
    commands, schemas = integrated_registries()
    return IntegratedProofEnvironment(
        path=tmp_path / "authority.sqlite3",
        object_root=tmp_path / "objects",
        command_registry=commands,
        payload_schemas=schemas,
        admission_registry=admissions,
        rights_policies=rights,
        hydration_policies=hydration_policies or default_hydration,
        authenticator=authenticator(),
        authorizer=authorizer(),
        event_read_policy=event_policy(),
        projection_read_policy=projection_read_policy(),
        projection_contracts=projection_contracts(),
        object_limits=_limits(),
        neo4j_config=_config(),
        family_id=FAMILY_ID,
        fixture_admission_type="source.capture",
        fixture_hydration_purpose=hydration_purpose,
        clock=lambda: UtcTimestamp.parse(
            "2026-07-24T08:00:00.000000Z"
        ),
    )


def test_context_digest_binds_authoritative_serving_time() -> None:
    current = context()
    serving_time = UtcTimestamp.parse(
        "2026-07-24T08:01:00.000000Z"
    )
    changed = replace(
        current,
        metadata=replace(
            current.metadata,
            serving_time=serving_time,
        ),
        recorded_at=serving_time,
    )
    assert changed.context_digest != current.context_digest


def test_proof_environment_rejects_hydration_policy_outside_admission(
    tmp_path: Path,
) -> None:
    _rights, hydration, _admissions = _policy_registries()
    rogue = HydrationPolicyContract(
        policy_id="integrated-rogue-v1",
        contract_version="hydration-v1",
        implementation_version="hydration-static-v1",
        purpose="integrated.rogue",
        required_scope="authority.objects.read",
        allowed_principal_ids=frozenset({"principal.alpha"}),
        allowed_authority_domains=frozenset({"newsroom.authority"}),
        allowed_object_classes=frozenset({"source_capture"}),
        allowed_uses=frozenset({"project.discovery"}),
        allowed_security_scopes=frozenset({"authority.protected"}),
        allowed_retention_scopes=frozenset({"source.short"}),
        max_bytes=1024 * 1024,
    )
    registry = HydrationPolicyRegistry((*hydration.contracts(), rogue))
    with pytest.raises(
        IntegratedStateError,
        match="outside the admission contract",
    ):
        _environment(
            tmp_path,
            hydration_policies=registry,
            hydration_purpose="integrated.rogue",
        )


def test_fixture_replay_rechecks_current_hydration_after_tombstone(
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path)
    controller = IntegratedFoundationProofController(environment)
    current_manifest = manifest()
    keys = IntegratedProofKeys("integrated-proof-hydration-recheck")
    fixture = controller.record_fixture(
        current_manifest,
        proof=proof(),
        keys=keys,
    )

    rights, hydration, admissions = _policy_registries()
    system = open_governed_object_authority_system(
        path=environment.path,
        object_root=environment.object_root,
        registry=environment.command_registry,
        payload_schemas=environment.payload_schemas,
        admission_registry=admissions,
        rights_policies=rights,
        hydration_policies=hydration,
        authenticator=environment.authenticator,
        authorizer=environment.authorizer,
        event_read_policy=environment.event_read_policy,
        object_limits=environment.object_limits,
        clock=environment.clock,
    )
    try:
        system.objects.revoke(
            fixture.admission_id,
            reason_code="INTEGRATED_REPLAY_REVOKE",
            idempotency_key="integrated-proof-revoke",
            proof=proof(),
        )
        deletion = system.objects.request_deletion(
            current_manifest.manifest_digest,
            reason_code="INTEGRATED_REPLAY_DELETE",
            idempotency_key="integrated-proof-delete",
            proof=proof(),
        )
        system.objects.tombstone(
            deletion.deletion_id,
            reason_code="INTEGRATED_REPLAY_TOMBSTONE",
            idempotency_key="integrated-proof-tombstone",
            proof=proof(),
        )
    finally:
        system.close()

    with pytest.raises((ObjectAdmissionDenied, ObjectHydrationDenied)):
        controller.record_fixture(
            current_manifest,
            proof=proof(),
            keys=keys,
        )
