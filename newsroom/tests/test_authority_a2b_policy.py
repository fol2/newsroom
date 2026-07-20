from __future__ import annotations

import dataclasses

import pytest

import newsroom.authority as authority
from newsroom.authority import (
    HydrationPolicyRegistry,
    ObjectAdmissionDefinition,
    ObjectAdmissionRegistry,
    ObjectPolicyError,
    RightsPolicyContract,
    RightsPolicyRegistry,
    UnknownHydrationPolicyContract,
    UnknownObjectAdmissionDefinition,
)

from .authority_a2b_helpers import _policy_registries


def test_admission_registry_resolves_current_and_exact_versions() -> None:
    rights, hydration, registry = _policy_registries()
    current = registry.resolve("source.capture")
    assert current.allowed_use == "project.discovery"
    assert registry.resolve_exact(
        current.admission_type,
        current.definition_version,
        current.digest,
    ) == current
    with pytest.raises(UnknownObjectAdmissionDefinition):
        registry.resolve_exact(
            current.admission_type,
            current.definition_version,
            "sha256:" + "0" * 64,
        )
    assert rights.resolve_digest(current.rights_policy_contract_digest)
    for digest in current.hydration_policy_contract_digests:
        assert hydration.resolve_digest(digest)


def test_definition_is_bound_to_exact_rights_and_hydration_contracts() -> None:
    rights, hydration, registry = _policy_registries()
    selected = registry.resolve("source.capture")
    changed_rights = RightsPolicyContract(
        policy_key="source-permitted",
        contract_version="rights-v2",
        implementation_version="rights-static-v2",
        preflight_allowed=True,
        reason_code="PERMITTED",
    )
    expanded = RightsPolicyRegistry(
        (*rights.contracts(), changed_rights),
        current_versions={
            "source-permitted": "rights-v2",
            "source-prohibited": "rights-v1",
            "source-short": "rights-v1",
        },
    )
    # The old definition remains bound to the exact v1 digest even when v2 is current.
    rebuilt = ObjectAdmissionRegistry(
        (selected,),
        rights_policies=expanded,
        hydration_policies=hydration,
    )
    assert rebuilt.resolve("source.capture").rights_policy_contract_digest == selected.rights_policy_contract_digest


def test_hydration_registry_rejects_ambiguous_purpose() -> None:
    _, hydration, _ = _policy_registries()
    original = hydration.resolve_for_purpose("project.discovery")
    second = dataclasses.replace(
        original,
        policy_id="project-discovery-v2",
        contract_version="hydration-v2",
        implementation_version="hydration-static-v2",
    )
    with pytest.raises(ObjectPolicyError, match="purpose"):
        HydrationPolicyRegistry((original, second))


def test_public_api_exposes_facade_not_authority_synthesis_helpers() -> None:
    required = {
        "GovernedObjectAuthoritySystem",
        "GovernedObjects",
        "ObjectAdmissionDefinition",
        "RightsPolicyContract",
        "HydrationPolicyContract",
        "open_governed_object_authority_system",
    }
    assert required.issubset(authority.__all__)
    prohibited = {
        "StaticRightsResolver",
        "authorize_admission_preflight",
        "activate_admission_with_event",
        "AdmissionCommitCapability",
        "MaintenanceCommitCapability",
        "GovernedObjectStore",
        "GovernedCAS",
    }
    assert prohibited.isdisjoint(authority.__all__)
    assert all(not hasattr(authority, name) for name in prohibited)
