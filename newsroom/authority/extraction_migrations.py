from __future__ import annotations

from dataclasses import dataclass

from .canonical import digest_canonical
from .extraction_migration_guards import EXTRACTION_AUTHORITY_GUARD_STATEMENTS
from .extraction_migration_schema import EXTRACTION_AUTHORITY_SCHEMA_STATEMENTS


EXTRACTION_AUTHORITY_SCHEMA_VERSION = 13
EXTRACTION_AUTHORITY_MIGRATION_NAME = "extraction_run_proposal_authority_v13"


@dataclass(frozen=True, slots=True)
class ExtractionAuthorityMigrationRecord:
    version: int
    name: str
    checksum: str


EXTRACTION_AUTHORITY_MIGRATION_STATEMENTS: tuple[str, ...] = (
    EXTRACTION_AUTHORITY_SCHEMA_STATEMENTS + EXTRACTION_AUTHORITY_GUARD_STATEMENTS
)
EXTRACTION_AUTHORITY_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": EXTRACTION_AUTHORITY_SCHEMA_VERSION,
        "name": EXTRACTION_AUTHORITY_MIGRATION_NAME,
        "statements": list(EXTRACTION_AUTHORITY_MIGRATION_STATEMENTS),
    }
)
EXTRACTION_AUTHORITY_MIGRATION = ExtractionAuthorityMigrationRecord(
    version=EXTRACTION_AUTHORITY_SCHEMA_VERSION,
    name=EXTRACTION_AUTHORITY_MIGRATION_NAME,
    checksum=EXTRACTION_AUTHORITY_MIGRATION_CHECKSUM,
)


__all__ = [
    "EXTRACTION_AUTHORITY_MIGRATION",
    "EXTRACTION_AUTHORITY_MIGRATION_CHECKSUM",
    "EXTRACTION_AUTHORITY_MIGRATION_NAME",
    "EXTRACTION_AUTHORITY_MIGRATION_STATEMENTS",
    "EXTRACTION_AUTHORITY_SCHEMA_VERSION",
]
