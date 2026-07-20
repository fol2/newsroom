from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from newsroom.authority import (
    AuthenticationProof,
    HydrationPolicyContract,
    HydrationPolicyRegistry,
    MetadataClass,
    ObjectAdmissionDefinition,
    ObjectAdmissionRegistry,
    ObjectAdmissionRequest,
    ObjectLimits,
    RightsPolicyContract,
    RightsPolicyRegistry,
    StaticAuthenticator,
    StaticAuthorizer,
    StaticPrincipal,
    TrustScope,
    UtcTimestamp,
    open_governed_object_authority_system,
)

from .authority_event_helpers import fixture_read_policy, payload_schemas, registry_v1
from .authority_helpers import FIXED_NOW, proof


@dataclass(slots=True)
class MutableClock:
    current: UtcTimestamp

    def __call__(self) -> UtcTimestamp:
        return self.current


def _policy_registries() -> tuple[
    RightsPolicyRegistry,
    HydrationPolicyRegistry,
    ObjectAdmissionRegistry,
]:
    permitted = RightsPolicyContract(
        policy_key="source-permitted",
        contract_version="rights-v1",
        implementation_version="rights-static-v1",
        preflight_allowed=True,
        reason_code="PERMITTED",
    )
    prohibited = RightsPolicyContract(
        policy_key="source-prohibited",
        contract_version="rights-v1",
        implementation_version="rights-static-v1",
        preflight_allowed=False,
        reason_code="PROHIBITED",
    )
    short = RightsPolicyContract(
        policy_key="source-short",
        contract_version="rights-v1",
        implementation_version="rights-static-v1",
        preflight_allowed=True,
        reason_code="PERMITTED",
        validity_seconds=30,
    )
    rights = RightsPolicyRegistry((permitted, prohibited, short))

    hydration_contract = HydrationPolicyContract(
        policy_id="project-discovery-v1",
        contract_version="hydration-v1",
        implementation_version="hydration-static-v1",
        purpose="project.discovery",
        required_scope="authority.objects.read",
        allowed_principal_ids=frozenset({"principal.alpha"}),
        allowed_authority_domains=frozenset({"newsroom.authority"}),
        allowed_object_classes=frozenset({"source_capture"}),
        allowed_uses=frozenset({"project.discovery", "publish.article"}),
        allowed_security_scopes=frozenset({"authority.protected"}),
        allowed_retention_scopes=frozenset({"source.short", "source.long"}),
        max_bytes=1024 * 1024,
        allow_ranges=True,
    )
    hydration = HydrationPolicyRegistry((hydration_contract,))

    def definition(
        admission_type: str,
        *,
        allowed_use: str,
        retention_scope: str,
        rights_contract: RightsPolicyContract,
    ) -> ObjectAdmissionDefinition:
        return ObjectAdmissionDefinition(
            admission_type=admission_type,
            definition_version="admission-v1",
            object_class="source_capture",
            allowed_use=allowed_use,
            security_scope="authority.protected",
            retention_scope=retention_scope,
            required_write_scope="authority.objects.admit",
            required_read_scope="authority.objects.read",
            required_manage_scope="authority.objects.manage",
            rights_policy_contract_digest=rights_contract.contract_digest,
            hydration_policy_contract_digests=frozenset(
                {hydration_contract.contract_digest}
            ),
        )

    admissions = ObjectAdmissionRegistry(
        (
            definition(
                "source.capture",
                allowed_use="project.discovery",
                retention_scope="source.short",
                rights_contract=permitted,
            ),
            definition(
                "source.publish",
                allowed_use="publish.article",
                retention_scope="source.long",
                rights_contract=permitted,
            ),
            definition(
                "source.prohibited",
                allowed_use="project.discovery",
                retention_scope="source.short",
                rights_contract=prohibited,
            ),
            definition(
                "source.short",
                allowed_use="project.discovery",
                retention_scope="source.short",
                rights_contract=short,
            ),
        ),
        rights_policies=rights,
        hydration_policies=hydration,
    )
    return rights, hydration, admissions


def open_object_system(
    database: Path,
    *,
    object_root: Path | None = None,
    scopes: frozenset[str] | None = None,
    policy_registries: tuple[
        RightsPolicyRegistry,
        HydrationPolicyRegistry,
        ObjectAdmissionRegistry,
    ]
    | None = None,
    object_limits: ObjectLimits | None = None,
    authenticator: object | None = None,
    authorizer: object | None = None,
    clock: Callable[[], UtcTimestamp] | None = None,
    fault_hook: Callable[[str], None] | None = None,
    disk_usage: Callable[[Path], object] | None = None,
    command_registry: object | None = None,
    payload_schema_registry: object | None = None,
):
    rights, hydration, admissions = (
        _policy_registries()
        if policy_registries is None
        else policy_registries
    )
    event_policy = fixture_read_policy(
        allowed_security_scopes=frozenset(
            {"authority.internal", "authority.object_lifecycle"}
        ),
        allowed_trust_scopes=frozenset(
            {TrustScope.OBSERVED, TrustScope.ADMITTED}
        ),
        metadata_classes=frozenset(
            {
                MetadataClass.ROUTING,
                MetadataClass.PROVENANCE,
                MetadataClass.RESULT,
            }
        ),
        max_results=1000,
    )
    selected_scopes = (
        scopes
        if scopes is not None
        else frozenset(
            {
                "authority.observed.write",
                "authority.admitted.write",
                event_policy.required_scope,
                "authority.objects.admit",
                "authority.objects.read",
                "authority.objects.manage",
                "authority.objects.lifecycle.write",
            }
        )
    )
    kwargs = {
        "path": Path(database),
        "object_root": Path(object_root or database.with_suffix(".objects")),
        "registry": command_registry or registry_v1(),
        "payload_schemas": payload_schema_registry or payload_schemas(),
        "admission_registry": admissions,
        "rights_policies": rights,
        "hydration_policies": hydration,
        "authenticator": (
            authenticator
            if authenticator is not None
            else StaticAuthenticator(
                credentials={
                    "token-1": StaticPrincipal("principal.alpha")
                },
                authority_domain="newsroom.authority",
            )
        ),
        "authorizer": (
            authorizer
            if authorizer is not None
            else StaticAuthorizer(
                policy_version="authz-v1",
                grants_by_principal={"principal.alpha": selected_scopes},
            )
        ),
        "event_read_policy": event_policy,
        "object_limits": object_limits
        or ObjectLimits(
            global_max_bytes=1024 * 1024,
            class_max_bytes={"source_capture": 1024 * 1024},
            max_read_bytes=1024 * 1024,
            min_free_bytes=0,
            io_chunk_bytes=64,
            max_staging_bytes=1024 * 1024,
            max_range_bytes=1024 * 1024,
        ),
        "clock": clock or (lambda: FIXED_NOW),
        "cas_fault_hook": fault_hook,
    }
    if disk_usage is not None:
        kwargs["disk_usage"] = disk_usage
    return open_governed_object_authority_system(**kwargs)


def admit(
    system,
    *,
    data: bytes = b"governed-object-fixture",
    key: str = "admit-1",
    admission_type: str = "source.capture",
    authentication_proof: AuthenticationProof | None = None,
):
    return system.objects.admit(
        ObjectAdmissionRequest(admission_type, key),
        data,
        proof=authentication_proof or proof(),
    )
