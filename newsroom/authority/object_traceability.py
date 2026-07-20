from __future__ import annotations


_COMMON = (
    "ADR-0001",
    "ADR-0002",
    "ADR-0004",
    "DREC-006",
    "DREC-016",
    "DREC-070",
    "DREC-073",
    "DREC-074",
    "DREC-076",
    "DREC-077",
    "GRAG-002",
    "GRAG-003",
    "GRAG-004",
    "GRAG-005",
    "GRAG-010",
    "GRAG-030",
    "GRPROD-005",
    "GRPROD-020",
)

INCREMENT_1A2B_TRACEABILITY: dict[str, tuple[str, ...]] = {
    "newsroom.authority.objects": _COMMON,
    "newsroom.authority.object_policy": _COMMON,
    "newsroom.authority.object_boundary": _COMMON,
    "newsroom.authority._object_capability": _COMMON,
    "newsroom.authority.object_migrations": _COMMON,
    "newsroom.authority._object_cas": _COMMON,
    "newsroom.authority._object_store_base": _COMMON,
    "newsroom.authority._object_store_admission": _COMMON,
    "newsroom.authority._object_store_hydration": _COMMON,
    "newsroom.authority._object_store_lifecycle": (*_COMMON, "GRAG-028"),
    "newsroom.authority._object_system": _COMMON,
    "newsroom.tests.test_authority_a2b_boundary": _COMMON,
    "newsroom.tests.test_authority_a2b_admission_hydration": _COMMON,
    "newsroom.tests.test_authority_a2b_lifecycle": (*_COMMON, "GRAG-028"),
    "newsroom.tests.test_authority_a2b_integrity_faults": (*_COMMON, "GRAG-028"),
    "newsroom.tests.test_authority_a2b_fault_matrix": (*_COMMON, "GRAG-028"),
    "newsroom.tests.test_authority_a2b_sqlite": (*_COMMON, "GRAG-028"),
    "newsroom.tests.test_authority_a2b_traceability": (*_COMMON, "GRAG-028"),
}

# Empty only when the implementation and current-head evidence cover every
# issue #86 deliverable. CI and substantive review remain separate merge gates.
INCREMENT_1A2B_PENDING: tuple[str, ...] = ()

INCREMENT_1A2B_DEFERRED: tuple[str, ...] = (
    "SUCCESSFUL_READ_AUDIT_RETENTION",
    "DENIED_ATTEMPT_AUDIT_RETENTION",
    "FILESYSTEM_TYPE_QUALIFICATION",
    "PRODUCTION_OBJECT_LIMITS_AND_ALERTS",
    "BACKUP_ENCRYPTION_KEYS_RPO_RTO",
)

INCREMENT_1A2B_EXCLUSIONS: tuple[str, ...] = (
    "NEO4J",
    "GRAPHITI_EXECUTION",
    "LIVE_SOURCES",
    "MODEL_CALLS",
    "EMBEDDINGS",
    "SEARCH_PROVIDER_CALLS",
    "EVIDENCE_INTAKE",
    "PUBLICATION",
    "SHADOW",
    "CANARY",
    "PRODUCTION_ACTIVATION",
    "SPENDING",
)

__all__ = [
    "INCREMENT_1A2B_DEFERRED",
    "INCREMENT_1A2B_EXCLUSIONS",
    "INCREMENT_1A2B_PENDING",
    "INCREMENT_1A2B_TRACEABILITY",
]
