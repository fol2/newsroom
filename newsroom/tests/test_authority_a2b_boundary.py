from __future__ import annotations

import ast
import inspect
from pathlib import Path

import newsroom.authority as authority
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
    repository_root = Path(__file__).resolve().parents[2]
    newsroom_root = repository_root / "newsroom"
    violations: list[str] = []
    for path in newsroom_root.rglob("*.py"):
        relative = path.relative_to(repository_root)
        if "authority" in relative.parts or "tests" in relative.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeError) as exc:
            violations.append(f"{relative}: unreadable: {exc}")
            continue
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            elif isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            for module in modules:
                if module.startswith("newsroom.authority._object"):
                    violations.append(f"{relative}:{node.lineno}:{module}")
    assert not violations, "private object-writer imports: " + "; ".join(
        violations
    )
