from __future__ import annotations

from dataclasses import dataclass

from .canonical import digest_canonical
from .check_migration_guards import CHECK_AUTHORITY_GUARD_STATEMENTS
from .check_migration_schema import CHECK_AUTHORITY_SCHEMA_STATEMENTS


CHECK_AUTHORITY_SCHEMA_VERSION = 11
CHECK_AUTHORITY_MIGRATION_NAME = "check_transition_authority_v11"


@dataclass(frozen=True, slots=True)
class CheckAuthorityMigrationRecord:
    version: int
    name: str
    checksum: str


CHECK_AUTHORITY_MIGRATION_STATEMENTS: tuple[str, ...] = (
    CHECK_AUTHORITY_SCHEMA_STATEMENTS + CHECK_AUTHORITY_GUARD_STATEMENTS
)
CHECK_AUTHORITY_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": CHECK_AUTHORITY_SCHEMA_VERSION,
        "name": CHECK_AUTHORITY_MIGRATION_NAME,
        "statements": list(CHECK_AUTHORITY_MIGRATION_STATEMENTS),
    }
)
CHECK_AUTHORITY_MIGRATION = CheckAuthorityMigrationRecord(
    version=CHECK_AUTHORITY_SCHEMA_VERSION,
    name=CHECK_AUTHORITY_MIGRATION_NAME,
    checksum=CHECK_AUTHORITY_MIGRATION_CHECKSUM,
)


__all__ = [
    "CHECK_AUTHORITY_MIGRATION",
    "CHECK_AUTHORITY_MIGRATION_CHECKSUM",
    "CHECK_AUTHORITY_MIGRATION_NAME",
    "CHECK_AUTHORITY_MIGRATION_STATEMENTS",
    "CHECK_AUTHORITY_SCHEMA_VERSION",
]
