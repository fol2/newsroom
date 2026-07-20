from __future__ import annotations

import newsroom.authority as authority
from newsroom.authority import (
    INCREMENT_1A2B_DEFERRED,
    INCREMENT_1A2B_EXCLUSIONS,
    INCREMENT_1A2B_PENDING,
    INCREMENT_1A2B_TRACEABILITY,
)


def test_a2b_traceability_covers_implementation_and_fault_evidence() -> None:
    required = {
        "newsroom.authority._event_store_commit",
        "newsroom.authority.service",
        "newsroom.authority._object_capability",
        "newsroom.authority._object_cas",
        "newsroom.authority._object_store_base",
        "newsroom.authority._object_store_admission",
        "newsroom.authority._object_store_hydration",
        "newsroom.authority._object_store_lifecycle",
        "newsroom.authority._object_system",
        "newsroom.tests.test_authority_a2b_object_commands",
        "newsroom.tests.test_authority_a2b_integrity_faults",
        "newsroom.tests.test_authority_a2b_fault_matrix",
    }
    assert required.issubset(INCREMENT_1A2B_TRACEABILITY)
    assert all(INCREMENT_1A2B_TRACEABILITY.values())


def test_grag_028_is_claimed_only_with_non_resurrection_evidence() -> None:
    claimed = {
        requirement
        for requirements in INCREMENT_1A2B_TRACEABILITY.values()
        for requirement in requirements
    }
    assert "GRAG-028" in claimed
    assert INCREMENT_1A2B_PENDING == ()


def test_deferred_and_excluded_work_remains_explicit() -> None:
    assert {
        "SUCCESSFUL_READ_AUDIT_RETENTION",
        "FILESYSTEM_TYPE_QUALIFICATION",
        "BACKUP_ENCRYPTION_KEYS_RPO_RTO",
    }.issubset(INCREMENT_1A2B_DEFERRED)
    assert {
        "NEO4J",
        "GRAPHITI_EXECUTION",
        "LIVE_SOURCES",
        "MODEL_CALLS",
        "SHADOW",
        "CANARY",
        "PRODUCTION_ACTIVATION",
    }.issubset(INCREMENT_1A2B_EXCLUSIONS)


def test_public_api_does_not_export_private_mutation_components() -> None:
    for name in (
        "_GovernedCAS",
        "_GovernedObjectAuthorityStore",
        "_ObjectCapabilityIssuer",
    ):
        assert name not in authority.__all__
        assert not hasattr(authority, name)
