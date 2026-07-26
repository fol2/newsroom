from __future__ import annotations

import inspect

import newsroom.authority as authority
from .source_import_inventory import production_import_inventory

from newsroom.authority import (
    AuthenticationProof,
    HydrationRequest,
    ObjectAdmissionRequest,
)


def test_public_api_has_no_direct_store_capability_or_authority_synthesis() -> None:
    prohibited = {
        "GovernedObjectStore",
        "ObjectAuthorityStore",
        "AdmissionCommitCapability",
        "MaintenanceCommitCapability",
        "StaticRightsResolver",
        "StaticRightsRule",
        "RightsPreflight",
        "activate_admission_contract",
        "activate_admission_with_event",
        "authorize_admission_preflight",
        "prepare_admission",
    }
    assert prohibited.isdisjoint(authority.__all__)
    for name in prohibited:
        assert not hasattr(authority, name)


def test_public_request_surfaces_do_not_accept_authority_identity_or_time() -> None:
    admission_fields = set(ObjectAdmissionRequest.__dataclass_fields__)
    assert admission_fields == {"admission_type", "idempotency_key"}
    hydration_fields = set(HydrationRequest.__dataclass_fields__)
    assert hydration_fields == {"admission_id", "purpose", "offset", "length"}
    prohibited = {
        "principal_id",
        "authority_domain",
        "now",
        "rights_status",
        "allowed",
        "object_class",
        "allowed_use",
        "security_scope",
        "retention_scope",
        "blob_digest",
        "size_bytes",
        "event_id",
    }
    assert prohibited.isdisjoint(admission_fields)
    assert prohibited.isdisjoint(hydration_fields)
    assert "proof" in inspect.signature(
        authority.GovernedObjects.admit
    ).parameters
    assert "proof" in inspect.signature(
        authority.GovernedObjects.hydrate
    ).parameters
    assert AuthenticationProof is not None


def test_non_authority_modules_cannot_import_private_object_writer() -> None:
    violations: list[str] = []
    for relative, imports, parse_error in production_import_inventory():
        if "authority" in relative.parts:
            continue
        if parse_error is not None:
            violations.append(f"{relative}: unreadable: {parse_error}")
            continue
        for lineno, module in imports:
            if module.startswith("newsroom.authority._object"):
                violations.append(f"{relative}:{lineno}:{module}")
    assert not violations, "private object-writer imports: " + "; ".join(
        violations
    )
