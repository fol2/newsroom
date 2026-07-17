from __future__ import annotations

from newsroom.authority import (
    INCREMENT_1A2A_DEFERRED,
    INCREMENT_1A2A_TRACEABILITY,
)


def test_a2a_traceability_covers_modules_and_tests() -> None:
    required = {
        "newsroom.authority.migrations",
        "newsroom.authority._event_store_base",
        "newsroom.authority._event_store_commit",
        "newsroom.authority._event_store_read",
        "newsroom.authority._event_system",
        "newsroom.authority.persistence",
        "newsroom.tests.test_authority_a2a_event_envelope",
        "newsroom.tests.test_authority_a2a_integrity",
        "newsroom.tests.test_authority_a2a_read_policy",
    }
    assert required.issubset(INCREMENT_1A2A_TRACEABILITY)
    assert all(
        requirements
        for requirements in INCREMENT_1A2A_TRACEABILITY.values()
    )


def test_a2a_does_not_claim_object_lifecycle_or_grag_028() -> None:
    claimed = {
        requirement
        for requirements in INCREMENT_1A2A_TRACEABILITY.values()
        for requirement in requirements
    }
    assert "GRAG-028" not in claimed
    assert {
        "FILESYSTEM_CAS",
        "RIGHTS_ADMISSION",
        "OBJECT_HYDRATION",
        "DELETION_TOMBSTONES",
        "GARBAGE_COLLECTION",
        "RECOVERY_PINS",
    }.issubset(INCREMENT_1A2A_DEFERRED)
    assert "SUCCESSFUL_READ_AUDIT_RETENTION" in (
        INCREMENT_1A2A_DEFERRED
    )
