from __future__ import annotations

from dataclasses import dataclass

from .canonical import digest_canonical
from .discovery_migration_guards import DISCOVERY_AUTHORITY_GUARD_STATEMENTS
from .discovery_migration_schema import DISCOVERY_AUTHORITY_SCHEMA_STATEMENTS


DISCOVERY_AUTHORITY_SCHEMA_VERSION = 12
DISCOVERY_AUTHORITY_MIGRATION_NAME = "discovery_signal_lead_authority_v12"


@dataclass(frozen=True, slots=True)
class DiscoveryAuthorityMigrationRecord:
    version: int
    name: str
    checksum: str


DISCOVERY_AUTHORITY_MIGRATION_STATEMENTS: tuple[str, ...] = (
    DISCOVERY_AUTHORITY_SCHEMA_STATEMENTS + DISCOVERY_AUTHORITY_GUARD_STATEMENTS
)
DISCOVERY_AUTHORITY_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": DISCOVERY_AUTHORITY_SCHEMA_VERSION,
        "name": DISCOVERY_AUTHORITY_MIGRATION_NAME,
        "statements": list(DISCOVERY_AUTHORITY_MIGRATION_STATEMENTS),
    }
)
DISCOVERY_AUTHORITY_MIGRATION = DiscoveryAuthorityMigrationRecord(
    version=DISCOVERY_AUTHORITY_SCHEMA_VERSION,
    name=DISCOVERY_AUTHORITY_MIGRATION_NAME,
    checksum=DISCOVERY_AUTHORITY_MIGRATION_CHECKSUM,
)


__all__ = [
    "DISCOVERY_AUTHORITY_MIGRATION",
    "DISCOVERY_AUTHORITY_MIGRATION_CHECKSUM",
    "DISCOVERY_AUTHORITY_MIGRATION_NAME",
    "DISCOVERY_AUTHORITY_MIGRATION_STATEMENTS",
    "DISCOVERY_AUTHORITY_SCHEMA_VERSION",
]
