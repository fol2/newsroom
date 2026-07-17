from __future__ import annotations

import newsroom.authority as authority
from newsroom.authority import (
    INCREMENT_1A2B_EXCLUSIONS,
    INCREMENT_1A2B_PENDING,
    INCREMENT_1A2B_TRACEABILITY,
)


def test_initial_a2b_traceability_covers_contract_policy_and_tests() -> None:
    required = {
        "newsroom.authority.objects",
        "newsroom.authority.object_policy",
        "newsroom.tests.test_authority_a2b_contracts",
        "newsroom.tests.test_authority_a2b_policy",
        "newsroom.tests.test_authority_a2b_traceability",
    }
    assert required.issubset(INCREMENT_1A2B_TRACEABILITY)
    assert all(
        requirements
        for requirements in INCREMENT_1A2B_TRACEABILITY.values()
    )


def test_initial_slice_does_not_claim_grag_028_completion() -> None:
    claimed = {
        requirement
        for requirements in INCREMENT_1A2B_TRACEABILITY.values()
        for requirement in requirements
    }
    assert "GRAG-028" not in claimed
    assert "GRAG_028_COMPLETION_EVIDENCE" in INCREMENT_1A2B_PENDING


def test_pending_register_covers_full_a2b_exit_contract() -> None:
    required = {
        "SQLITE_RIGHTS_AND_ADMISSION_MIGRATION",
        "HMAC_BOUND_ADMISSION_AND_MAINTENANCE_CAPABILITIES",
        "STREAMING_FILESYSTEM_CAS",
        "FAIL_CLOSED_FILE_AND_DIRECTORY_FSYNC",
        "READ_ONLY_INSTALLED_BLOBS",
        "PINNED_FD_FINAL_REHASH",
        "OBJECT_BACKED_COMMAND_TRANSACTION_RECHECK",
        "AUTHENTICATED_BOUNDED_HYDRATION",
        "ORDERED_ADMISSION_EVENT",
        "ORDERED_REVOCATION_EVENT",
        "ORDERED_DELETION_REQUEST_EVENT",
        "ORDERED_TOMBSTONE_AND_COMPLETION_EVENTS",
        "LAWFUL_DELETION_OF_REFERENCED_BYTES",
        "DELETION_NON_RESURRECTION_REPLAY",
        "AUTHORITATIVE_GARBAGE_COLLECTION",
        "RECOVERY_PIN_PERSISTENCE",
        "STARTUP_RECONCILIATION",
        "REPLAY_WITHOUT_STAGING_LEAKS",
        "FSYNC_UNLINK_MUTATION_AND_GC_INTERLEAVING_FAULTS",
        "CONSTRUCTOR_FAILURE_LOCK_CLEANUP",
    }
    assert required.issubset(INCREMENT_1A2B_PENDING)


def test_later_work_remains_explicitly_excluded() -> None:
    assert {
        "NEO4J",
        "GRAPHITI_EXECUTION",
        "LIVE_SOURCES",
        "MODEL_CALLS",
        "EMBEDDINGS",
        "SEARCH_PROVIDER_CALLS",
        "SHADOW",
        "CANARY",
        "PRODUCTION_ACTIVATION",
        "SPENDING",
    }.issubset(INCREMENT_1A2B_EXCLUSIONS)


def test_public_api_exposes_contracts_but_not_mutation_capabilities() -> None:
    assert "ObjectAdmissionDefinition" in authority.__all__
    assert "StaticRightsResolver" in authority.__all__
    prohibited = {
        "BlobStore",
        "GovernedObjectStore",
        "ObjectAuthorityStore",
        "AdmissionCommitCapability",
        "MaintenanceCommitCapability",
    }
    assert prohibited.isdisjoint(authority.__all__)
    for name in prohibited:
        assert not hasattr(authority, name)
