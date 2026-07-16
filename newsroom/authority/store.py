from __future__ import annotations

from .store_base import (
    AuthorityBusyError,
    AuthorityStoreBase,
    AuthorityStoreError,
    ExpectedVersionConflict,
    IdempotencyConflict,
    MigrationChecksumError,
    ObjectMetadataConflict,
    UnknownObjectReference,
    UnsupportedSchemaVersionError,
    UnversionedDatabaseError,
)
from .store_commands import AuthorityStoreCommandsMixin


class AuthorityStore(AuthorityStoreCommandsMixin, AuthorityStoreBase):
    """Single-writer SQLite authority composed from schema and command concerns."""

    pass


__all__ = [
    "AuthorityBusyError",
    "AuthorityStore",
    "AuthorityStoreError",
    "ExpectedVersionConflict",
    "IdempotencyConflict",
    "MigrationChecksumError",
    "ObjectMetadataConflict",
    "UnknownObjectReference",
    "UnsupportedSchemaVersionError",
    "UnversionedDatabaseError",
]
