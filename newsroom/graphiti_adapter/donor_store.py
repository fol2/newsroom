"""Insert-only storage for non-serving Graphiti donor evidence (#772)."""

from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Protocol

from newsroom.graphiti_adapter.donor_identities import (
    EmbeddingRequestIdentityV1,
    EmbeddingVectorIntegrityV1,
    SemanticExtractionRequestIdentityV1,
    ValidatedSemanticExtractionArtifactV1,
    validated_artifact_is_eligible,
)


class DonorStore(Protocol):
    def retain_extraction_request(
        self, identity: SemanticExtractionRequestIdentityV1
    ) -> None: ...

    def retain_validated_artifact(
        self, artifact: ValidatedSemanticExtractionArtifactV1
    ) -> bool: ...

    def count_semantic_opportunity(
        self, identity: SemanticExtractionRequestIdentityV1
    ) -> int: ...

    def retain_embedding_request(
        self, identity: EmbeddingRequestIdentityV1
    ) -> None: ...

    def retain_embedding_integrity(
        self, integrity: EmbeddingVectorIntegrityV1
    ) -> bool: ...


class InMemoryDonorStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._semantic_requests: dict[str, bytes] = {}
        self._validated_artifacts: dict[str, ValidatedSemanticExtractionArtifactV1] = {}
        self._semantic_opportunities: Counter[str] = Counter()
        self._embedding_requests: dict[str, bytes] = {}
        self._embedding_integrity: dict[str, EmbeddingVectorIntegrityV1] = {}

    def retain_extraction_request(
        self, identity: SemanticExtractionRequestIdentityV1
    ) -> None:
        with self._lock:
            self._semantic_requests.setdefault(
                identity.identity_digest, identity.manifest_json
            )

    def retain_validated_artifact(
        self, artifact: ValidatedSemanticExtractionArtifactV1
    ) -> bool:
        if not validated_artifact_is_eligible(artifact):
            return False
        with self._lock:
            if artifact.artifact_digest in self._validated_artifacts:
                return False
            self._validated_artifacts[artifact.artifact_digest] = artifact
            return True

    def count_semantic_opportunity(
        self, identity: SemanticExtractionRequestIdentityV1
    ) -> int:
        with self._lock:
            matched = int(identity.identity_digest in self._semantic_requests)
            if matched:
                self._semantic_opportunities[identity.identity_digest] += 1
            return matched

    def semantic_request_count(self, identity_digest: str | None = None) -> int:
        with self._lock:
            if identity_digest is None:
                return len(self._semantic_requests)
            return int(identity_digest in self._semantic_requests)

    def validated_artifact_count(self, identity_digest: str | None = None) -> int:
        with self._lock:
            if identity_digest is None:
                return len(self._validated_artifacts)
            return sum(
                item.identity_digest == identity_digest
                for item in self._validated_artifacts.values()
            )

    def semantic_opportunity_count(self, identity_digest: str) -> int:
        with self._lock:
            return self._semantic_opportunities[identity_digest]

    def retain_embedding_request(self, identity: EmbeddingRequestIdentityV1) -> None:
        with self._lock:
            self._embedding_requests.setdefault(
                identity.identity_digest, identity.manifest_json
            )

    def retain_embedding_integrity(
        self, integrity: EmbeddingVectorIntegrityV1
    ) -> bool:
        with self._lock:
            if integrity.integrity_digest in self._embedding_integrity:
                return False
            self._embedding_integrity[integrity.integrity_digest] = integrity
            return True

    def embedding_request_count(self, identity_digest: str | None = None) -> int:
        with self._lock:
            if identity_digest is None:
                return len(self._embedding_requests)
            return int(identity_digest in self._embedding_requests)

    def embedding_integrity_count(self, identity_digest: str | None = None) -> int:
        with self._lock:
            if identity_digest is None:
                return len(self._embedding_integrity)
            return sum(
                item.identity_digest == identity_digest
                for item in self._embedding_integrity.values()
            )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS semantic_extraction_request_identities(
    identity_digest TEXT PRIMARY KEY,
    manifest_json TEXT NOT NULL,
    inserted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS validated_semantic_extraction_artifacts(
    artifact_digest TEXT PRIMARY KEY,
    identity_digest TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    inserted_at TEXT NOT NULL,
    UNIQUE(identity_digest, artifact_digest)
);
CREATE TABLE IF NOT EXISTS embedding_request_identities(
    identity_digest TEXT PRIMARY KEY,
    manifest_json TEXT NOT NULL,
    inserted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS embedding_vector_integrity(
    integrity_digest TEXT PRIMARY KEY,
    identity_digest TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    inserted_at TEXT NOT NULL,
    UNIQUE(identity_digest, integrity_digest)
);
CREATE TABLE IF NOT EXISTS donor_opportunity_telemetry(
    kind TEXT NOT NULL,
    identity_digest TEXT NOT NULL,
    observed_at TEXT NOT NULL
);
"""


class SqliteDonorStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        with self._connection() as connection:
            connection.executescript(_SCHEMA)

    def _connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30)

    def retain_extraction_request(
        self, identity: SemanticExtractionRequestIdentityV1
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO semantic_extraction_request_identities "
                "VALUES(?,?,?)",
                (
                    identity.identity_digest,
                    identity.manifest_json.decode("utf-8"),
                    _now(),
                ),
            )

    def retain_validated_artifact(
        self, artifact: ValidatedSemanticExtractionArtifactV1
    ) -> bool:
        if not validated_artifact_is_eligible(artifact):
            return False
        with self._connection() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO validated_semantic_extraction_artifacts "
                "VALUES(?,?,?,?)",
                (
                    artifact.artifact_digest,
                    artifact.identity_digest,
                    artifact.manifest_json.decode("utf-8"),
                    _now(),
                ),
            )
            return cursor.rowcount == 1

    def count_semantic_opportunity(
        self, identity: SemanticExtractionRequestIdentityV1
    ) -> int:
        with self._connection() as connection:
            matched = connection.execute(
                "SELECT COUNT(*) FROM semantic_extraction_request_identities "
                "WHERE identity_digest=?",
                (identity.identity_digest,),
            ).fetchone()[0]
            if matched:
                connection.execute(
                    "INSERT INTO donor_opportunity_telemetry VALUES(?,?,?)",
                    ("SEMANTIC", identity.identity_digest, _now()),
                )
            return int(matched)

    def retain_embedding_request(self, identity: EmbeddingRequestIdentityV1) -> None:
        with self._connection() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO embedding_request_identities VALUES(?,?,?)",
                (
                    identity.identity_digest,
                    identity.manifest_json.decode("utf-8"),
                    _now(),
                ),
            )

    def retain_embedding_integrity(
        self, integrity: EmbeddingVectorIntegrityV1
    ) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO embedding_vector_integrity VALUES(?,?,?,?)",
                (
                    integrity.integrity_digest,
                    integrity.identity_digest,
                    integrity.manifest_json.decode("utf-8"),
                    _now(),
                ),
            )
            return cursor.rowcount == 1

    def embedding_request_count(self, identity_digest: str | None = None) -> int:
        return self._count("embedding_request_identities", identity_digest)

    def embedding_integrity_count(self, identity_digest: str | None = None) -> int:
        return self._count("embedding_vector_integrity", identity_digest)

    def semantic_request_count(self, identity_digest: str | None = None) -> int:
        return self._count(
            "semantic_extraction_request_identities", identity_digest
        )

    def validated_artifact_count(self, identity_digest: str | None = None) -> int:
        return self._count(
            "validated_semantic_extraction_artifacts", identity_digest
        )

    def _count(self, table: str, identity_digest: str | None) -> int:
        query = f"SELECT COUNT(*) FROM {table}"
        values: tuple[str, ...] = ()
        if identity_digest is not None:
            query += " WHERE identity_digest=?"
            values = (identity_digest,)
        with self._connection() as connection:
            return int(connection.execute(query, values).fetchone()[0])


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


__all__ = ["DonorStore", "InMemoryDonorStore", "SqliteDonorStore"]
