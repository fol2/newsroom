from __future__ import annotations

INCREMENT_1A_REVIEW_BOUNDARIES: tuple[str, ...] = (
    "A1_COMMAND_AUTHENTICATION_AUTHORIZATION_CONTRACT",
    "A2A_SQLITE_EVENT_AUTHORITY",
    "A2B_GOVERNED_OBJECT_ADMISSION_AND_CAS",
)

INCREMENT_1A_TRACEABILITY: dict[str, tuple[str, ...]] = {
    "newsroom.authority.types": (
        "ADR-0001", "ADR-0002", "ADR-0004", "DREC-001", "DREC-002",
        "DREC-003", "DREC-004", "DREC-005", "DREC-006", "DREC-074",
        "GRAG-001", "GRAG-010", "GRAG-030",
    ),
    "newsroom.authority.policy": (
        "DREC-006", "DREC-076", "GRAG-001", "GRAG-011", "GRPROD-005",
    ),
    "newsroom.authority.service": (
        "ADR-0001", "ADR-0002", "DREC-006", "DREC-070", "DREC-076",
        "GRAG-005", "GRAG-011", "GRAG-012", "GRPROD-005", "GRPROD-020",
    ),
    "newsroom.authority._security": (
        "ADR-0002", "DREC-070", "DREC-076", "GRAG-002", "GRAG-010",
    ),
    "newsroom.authority._capability": (
        "ADR-0002", "DREC-006", "DREC-070", "GRAG-002", "GRAG-005",
    ),
    "newsroom.authority._event_store": (
        "ADR-0001", "ADR-0002", "DREC-006", "DREC-007", "DREC-070",
        "DREC-073", "DREC-076", "DREC-077", "GRAG-002", "GRAG-005",
        "GRAG-030", "GRPROD-020",
    ),
    "newsroom.authority._blob_store": (
        "ADR-0001", "ADR-0002", "DREC-016", "GRAG-003", "GRAG-028",
        "GRPROD-020",
    ),
    "newsroom.authority._rights": (
        "ADR-0001", "DREC-016", "DREC-076", "GRAG-010", "GRAG-028",
    ),
    "newsroom.authority._object_store": (
        "ADR-0001", "ADR-0002", "DREC-006", "DREC-016", "DREC-070",
        "DREC-073", "DREC-077", "GRAG-002", "GRAG-003", "GRAG-004",
        "GRAG-005", "GRAG-028", "GRPROD-020",
    ),
    "newsroom.authority._object_service": (
        "ADR-0001", "ADR-0002", "DREC-016", "DREC-070", "DREC-076",
        "GRAG-010", "GRAG-028", "GRPROD-005",
    ),
    "newsroom.authority._object_system": (
        "ADR-0001", "ADR-0002", "DREC-016", "GRAG-003", "GRAG-028",
        "GRPROD-020",
    ),
}

INCREMENT_1A_EVIDENCE: dict[str, tuple[str, ...]] = {
    "A1": (
        "test_authority_boundary.py",
        "test_authority_security_records.py",
        "test_authority_idempotency_contract.py",
        "test_authority_payload_contract.py",
    ),
    "A2a": (
        "test_authority_event_persistence.py",
        "test_authority_migrations_and_integrity.py",
        "test_authority_concurrency_and_causation.py",
    ),
    "A2b": (
        "test_governed_object_admission.py",
        "test_governed_object_capability_binding.py",
        "test_governed_blob_faults.py",
        "test_governed_object_validity.py",
        "test_governed_object_deletion.py",
        "test_governed_object_reconciliation.py",
    ),
}
