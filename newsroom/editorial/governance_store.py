from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
from pathlib import Path
import shutil
import sqlite3
from typing import Any, Callable, Iterator, Mapping, Sequence

from .packages import (
    PackageArtifact,
    PackageIntegrityError,
    canonicalise_json,
    parse_json_bytes,
    verify_package_bytes,
)
from .policy import ResourceLimits


SCHEMA_VERSION = 1
_ZERO_HASH = "sha256:" + "0" * 64
_EXPECTED_TABLES = frozenset(
    {
        "packages",
        "stable_stories",
        "occurrences",
        "decisions",
        "authority_revisions",
        "authority_heads",
        "delivery_claims",
        "delivery_intents",
        "receipts",
        "pause_state",
        "audit_events",
        "audit_head",
    }
)


class GovernanceStoreError(RuntimeError):
    """Base class for governance persistence failures."""


class GovernanceIntegrityError(GovernanceStoreError):
    """Raised when durable governance state fails integrity verification."""


class GovernanceConflictError(GovernanceStoreError):
    """Raised when immutable identity is reused for different state."""


class GovernanceBusyError(GovernanceStoreError):
    """Raised when SQLite remains busy beyond the configured bound."""


class GovernanceResourceLimitError(GovernanceStoreError):
    """Raised before a write would exceed a policy resource limit."""


class StaleFenceError(GovernanceConflictError):
    """Raised when a claimant no longer owns the current fencing token."""


class GovernancePausedError(GovernanceConflictError):
    """Raised when delivery authority is requested while shadow scope is paused."""


@dataclass(frozen=True, slots=True)
class RuntimeConfiguration:
    schema_version: int
    journal_mode: str
    synchronous: int
    foreign_keys: bool
    busy_timeout_ms: int
    wal_autocheckpoint_pages: int
    max_page_count: int


@dataclass(frozen=True, slots=True)
class PauseState:
    paused: bool
    epoch: int
    actor: str
    reason: str
    changed_at: str


@dataclass(frozen=True, slots=True)
class AuditVerification:
    event_count: int
    head_sequence: int
    head_hash: str


@dataclass(frozen=True, slots=True)
class AuthorityRevision:
    authority_id: int
    stable_story_id: str
    story_version: str
    target: str
    revision: int
    decision_digest: str
    publication_digest: str | None


@dataclass(frozen=True, slots=True)
class EvaluationInspection:
    authority: AuthorityRevision
    candidate_id: str
    run_id: str
    story_id: str
    evidence_digest: str
    candidate_digest: str
    decision_digest: str
    publication_digest: str | None
    outcome: str
    policy_version: str
    controller_version: str


@dataclass(frozen=True, slots=True)
class DeliveryClaim:
    authority_id: int
    owner: str
    fence: int
    pause_epoch: int
    lease_expires_at: str


@dataclass(frozen=True, slots=True)
class DeliveryIntent:
    intent_id: str
    authority_id: int
    action_version: str
    owner: str
    fence: int
    state: str


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    intent_id: str
    status: str
    receipt_digest: str


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("UTC timestamp requires an explicit offset")
    return parsed.astimezone(UTC)


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _require_text(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


class GovernanceStore:
    """Single-file, fail-closed authority for the editorial shadow lane."""

    def __init__(
        self,
        path: Path,
        *,
        limits: ResourceLimits,
        now: Callable[[], str] = _utc_now,
    ) -> None:
        self.path = Path(path)
        self.limits = limits
        self._now = now
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._check_free_space()
        try:
            self._conn = sqlite3.connect(
                self.path,
                timeout=max(limits.busy_timeout_ms, 0) / 1000,
                isolation_level=None,
            )
            self._conn.row_factory = sqlite3.Row
            self._configure_connection()
            self._bootstrap_or_validate()
            self._runtime = self._read_and_verify_runtime_configuration()
        except Exception:
            connection = getattr(self, "_conn", None)
            if connection is not None:
                connection.close()
            raise

    def __enter__(self) -> GovernanceStore:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def _write_transaction(self, *, verify_audit: bool = True) -> Iterator[None]:
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            if verify_audit:
                self._verify_audit_chain_cursor(self._conn)
            yield
            self._conn.execute("COMMIT")
        except sqlite3.OperationalError as exc:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            message = str(exc).lower()
            if "busy" in message or "locked" in message:
                raise GovernanceBusyError("governance store remained busy") from exc
            raise GovernanceStoreError(str(exc)) from exc
        except sqlite3.DatabaseError as exc:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise GovernanceStoreError(str(exc)) from exc
        except Exception:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise

    def _configure_connection(self) -> None:
        self._conn.execute("PRAGMA foreign_keys=ON")
        mode = str(self._conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
        if mode != "wal":
            raise GovernanceStoreError(f"journal_mode WAL unavailable: {mode}")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute(f"PRAGMA busy_timeout={int(self.limits.busy_timeout_ms)}")
        self._conn.execute(
            f"PRAGMA wal_autocheckpoint={int(self.limits.wal_autocheckpoint_pages)}"
        )
        page_size = int(self._conn.execute("PRAGMA page_size").fetchone()[0])
        max_pages = max(1, int(self.limits.max_database_bytes) // page_size)
        self._conn.execute(f"PRAGMA max_page_count={max_pages}")

    def _read_and_verify_runtime_configuration(self) -> RuntimeConfiguration:
        runtime = RuntimeConfiguration(
            schema_version=int(self._conn.execute("PRAGMA user_version").fetchone()[0]),
            journal_mode=str(self._conn.execute("PRAGMA journal_mode").fetchone()[0]).lower(),
            synchronous=int(self._conn.execute("PRAGMA synchronous").fetchone()[0]),
            foreign_keys=bool(self._conn.execute("PRAGMA foreign_keys").fetchone()[0]),
            busy_timeout_ms=int(self._conn.execute("PRAGMA busy_timeout").fetchone()[0]),
            wal_autocheckpoint_pages=int(
                self._conn.execute("PRAGMA wal_autocheckpoint").fetchone()[0]
            ),
            max_page_count=int(
                self._conn.execute("PRAGMA max_page_count").fetchone()[0]
            ),
        )
        expected = RuntimeConfiguration(
            schema_version=SCHEMA_VERSION,
            journal_mode="wal",
            synchronous=2,
            foreign_keys=True,
            busy_timeout_ms=int(self.limits.busy_timeout_ms),
            wal_autocheckpoint_pages=int(self.limits.wal_autocheckpoint_pages),
            max_page_count=max(
                1,
                int(self.limits.max_database_bytes)
                // int(self._conn.execute("PRAGMA page_size").fetchone()[0]),
            ),
        )
        if runtime != expected:
            raise GovernanceStoreError(
                f"governance SQLite configuration mismatch: {runtime!r} != {expected!r}"
            )
        return runtime

    def _bootstrap_or_validate(self) -> None:
        version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        tables = {
            str(row[0])
            for row in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if version == 0:
            if tables:
                raise GovernanceStoreError("refusing to adopt an unversioned governance database")
            self._bootstrap_schema()
            return
        if version != SCHEMA_VERSION:
            raise GovernanceStoreError(
                f"unsupported governance schema version {version}; expected {SCHEMA_VERSION}"
            )
        if tables != _EXPECTED_TABLES:
            missing = sorted(_EXPECTED_TABLES - tables)
            unexpected = sorted(tables - _EXPECTED_TABLES)
            raise GovernanceStoreError(
                f"governance schema table mismatch: missing={missing} unexpected={unexpected}"
            )
        self._verify_audit_chain_cursor(self._conn)
        self.pause_state()
        self._verify_all_packages()
        self._verify_relational_integrity()

    def _bootstrap_schema(self) -> None:
        statements = (
            """CREATE TABLE packages (
                digest TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                digest_algorithm TEXT NOT NULL CHECK (digest_algorithm = 'sha256'),
                byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
                canonical_bytes BLOB NOT NULL,
                created_at TEXT NOT NULL,
                CHECK (length(canonical_bytes) = byte_size)
            ) STRICT""",
            """CREATE TABLE stable_stories (
                stable_story_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL
            ) STRICT""",
            """CREATE TABLE occurrences (
                candidate_id TEXT PRIMARY KEY,
                stable_story_id TEXT NOT NULL REFERENCES stable_stories(stable_story_id),
                story_version TEXT NOT NULL,
                run_id TEXT NOT NULL,
                story_id TEXT NOT NULL,
                candidate_digest TEXT NOT NULL REFERENCES packages(digest),
                created_at TEXT NOT NULL,
                UNIQUE (run_id, story_id),
                UNIQUE (candidate_digest)
            ) STRICT""",
            """CREATE TABLE decisions (
                decision_digest TEXT PRIMARY KEY REFERENCES packages(digest),
                candidate_digest TEXT NOT NULL REFERENCES packages(digest),
                evidence_digest TEXT NOT NULL REFERENCES packages(digest),
                publication_digest TEXT REFERENCES packages(digest),
                outcome TEXT NOT NULL CHECK (outcome IN ('AUTO_PUBLISH','HOLD_FOR_REVIEW','REJECT')),
                policy_version TEXT NOT NULL,
                controller_version TEXT NOT NULL,
                created_at TEXT NOT NULL
            ) STRICT""",
            """CREATE TABLE authority_revisions (
                authority_id INTEGER PRIMARY KEY,
                stable_story_id TEXT NOT NULL REFERENCES stable_stories(stable_story_id),
                story_version TEXT NOT NULL,
                target TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision > 0),
                decision_digest TEXT NOT NULL REFERENCES decisions(decision_digest),
                publication_digest TEXT REFERENCES packages(digest),
                created_at TEXT NOT NULL,
                UNIQUE (stable_story_id, story_version, target, revision)
            ) STRICT""",
            """CREATE TABLE authority_heads (
                stable_story_id TEXT NOT NULL,
                story_version TEXT NOT NULL,
                target TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision > 0),
                authority_id INTEGER NOT NULL UNIQUE REFERENCES authority_revisions(authority_id),
                decision_digest TEXT NOT NULL REFERENCES decisions(decision_digest),
                PRIMARY KEY (stable_story_id, story_version, target)
            ) WITHOUT ROWID, STRICT""",
            """CREATE TABLE delivery_claims (
                authority_id INTEGER PRIMARY KEY REFERENCES authority_revisions(authority_id),
                fence INTEGER NOT NULL DEFAULT 0 CHECK (fence >= 0),
                owner TEXT,
                pause_epoch INTEGER,
                claimed_at TEXT,
                lease_expires_at TEXT
            ) STRICT""",
            """CREATE TABLE delivery_intents (
                intent_id TEXT PRIMARY KEY,
                authority_id INTEGER NOT NULL REFERENCES authority_revisions(authority_id),
                publication_digest TEXT NOT NULL REFERENCES packages(digest),
                decision_digest TEXT NOT NULL REFERENCES decisions(decision_digest),
                target TEXT NOT NULL,
                action_version TEXT NOT NULL,
                owner TEXT NOT NULL,
                fence INTEGER NOT NULL CHECK (fence > 0),
                state TEXT NOT NULL CHECK (state IN ('INTENT_RECORDED','RECORDED_NOT_PUBLISHED','UNKNOWN')),
                created_at TEXT NOT NULL,
                UNIQUE (publication_digest, decision_digest, target, action_version)
            ) STRICT""",
            """CREATE TABLE receipts (
                intent_id TEXT PRIMARY KEY REFERENCES delivery_intents(intent_id),
                status TEXT NOT NULL CHECK (status IN ('RECORDED_NOT_PUBLISHED','UNKNOWN')),
                receipt_digest TEXT NOT NULL,
                receipt_bytes BLOB NOT NULL,
                recorded_at TEXT NOT NULL
            ) STRICT""",
            """CREATE TABLE pause_state (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                paused INTEGER NOT NULL CHECK (paused IN (0,1)),
                epoch INTEGER NOT NULL CHECK (epoch > 0),
                actor TEXT NOT NULL,
                reason TEXT NOT NULL,
                changed_at TEXT NOT NULL
            ) STRICT""",
            """CREATE TABLE audit_events (
                sequence INTEGER PRIMARY KEY,
                event_type TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                payload_bytes BLOB NOT NULL,
                previous_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            ) STRICT""",
            """CREATE TABLE audit_head (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                event_count INTEGER NOT NULL CHECK (event_count >= 0),
                head_sequence INTEGER NOT NULL CHECK (head_sequence >= 0),
                head_hash TEXT NOT NULL
            ) STRICT""",
        )
        with self._write_transaction(verify_audit=False):
            for statement in statements:
                self._conn.execute(statement)
            created_at = self._now()
            self._conn.execute(
                "INSERT INTO audit_head(singleton,event_count,head_sequence,head_hash) VALUES(1,0,0,?)",
                (_ZERO_HASH,),
            )
            self._conn.execute(
                """INSERT INTO pause_state(singleton,paused,epoch,actor,reason,changed_at)
                   VALUES(1,1,1,'SYSTEM','BOOTSTRAP_FAIL_CLOSED',?)""",
                (created_at,),
            )
            self._append_audit(
                event_type="BOOTSTRAP_PAUSED",
                entity_type="pause",
                entity_id="global:1",
                payload={
                    "paused": True,
                    "epoch": 1,
                    "actor": "SYSTEM",
                    "reason": "BOOTSTRAP_FAIL_CLOSED",
                },
                created_at=created_at,
            )
            self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def _append_audit(
        self,
        *,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload: Mapping[str, Any],
        created_at: str | None = None,
    ) -> tuple[int, str]:
        head = self._conn.execute(
            "SELECT event_count,head_sequence,head_hash FROM audit_head WHERE singleton=1"
        ).fetchone()
        if head is None:
            raise GovernanceIntegrityError("audit head is missing")
        sequence = int(head["head_sequence"]) + 1
        previous_hash = str(head["head_hash"])
        timestamp = created_at or self._now()
        payload_bytes = canonicalise_json(dict(payload))
        preimage = canonicalise_json(
            {
                "sequence": sequence,
                "event_type": event_type,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "payload_digest": _sha256(payload_bytes),
                "previous_hash": previous_hash,
                "created_at": timestamp,
            }
        )
        event_hash = _sha256(preimage)
        self._conn.execute(
            """INSERT INTO audit_events(
                   sequence,event_type,entity_type,entity_id,payload_bytes,
                   previous_hash,event_hash,created_at
               ) VALUES(?,?,?,?,?,?,?,?)""",
            (
                sequence,
                event_type,
                entity_type,
                entity_id,
                payload_bytes,
                previous_hash,
                event_hash,
                timestamp,
            ),
        )
        changed = self._conn.execute(
            """UPDATE audit_head
               SET event_count=?,head_sequence=?,head_hash=?
               WHERE singleton=1 AND event_count=? AND head_sequence=? AND head_hash=?""",
            (
                int(head["event_count"]) + 1,
                sequence,
                event_hash,
                int(head["event_count"]),
                int(head["head_sequence"]),
                previous_hash,
            ),
        ).rowcount
        if changed != 1:
            raise GovernanceIntegrityError("audit head compare-and-swap failed")
        return sequence, event_hash

    def _verify_audit_chain_cursor(self, connection: sqlite3.Connection) -> AuditVerification:
        head = connection.execute(
            "SELECT event_count,head_sequence,head_hash FROM audit_head WHERE singleton=1"
        ).fetchone()
        if head is None:
            raise GovernanceIntegrityError("audit head is missing")
        previous_hash = _ZERO_HASH
        expected_sequence = 1
        count = 0
        for row in connection.execute(
            """SELECT sequence,event_type,entity_type,entity_id,payload_bytes,
                      previous_hash,event_hash,created_at
               FROM audit_events ORDER BY sequence"""
        ):
            sequence = int(row["sequence"])
            if sequence != expected_sequence or str(row["previous_hash"]) != previous_hash:
                raise GovernanceIntegrityError("audit sequence or previous hash is broken")
            payload_bytes = bytes(row["payload_bytes"])
            try:
                payload = parse_json_bytes(payload_bytes)
                if not isinstance(payload, dict) or canonicalise_json(payload) != payload_bytes:
                    raise GovernanceIntegrityError("audit payload is not canonical")
            except Exception as exc:
                if isinstance(exc, GovernanceIntegrityError):
                    raise
                raise GovernanceIntegrityError("audit payload is invalid") from exc
            preimage = canonicalise_json(
                {
                    "sequence": sequence,
                    "event_type": str(row["event_type"]),
                    "entity_type": str(row["entity_type"]),
                    "entity_id": str(row["entity_id"]),
                    "payload_digest": _sha256(payload_bytes),
                    "previous_hash": previous_hash,
                    "created_at": str(row["created_at"]),
                }
            )
            actual = _sha256(preimage)
            if actual != str(row["event_hash"]):
                raise GovernanceIntegrityError("audit event hash mismatch")
            previous_hash = actual
            expected_sequence += 1
            count += 1
        if (
            count != int(head["event_count"])
            or count != int(head["head_sequence"])
            or previous_hash != str(head["head_hash"])
        ):
            raise GovernanceIntegrityError("audit head does not match the event chain")
        return AuditVerification(
            event_count=count,
            head_sequence=int(head["head_sequence"]),
            head_hash=str(head["head_hash"]),
        )

    def _check_free_space(self) -> None:
        free = int(shutil.disk_usage(self.path.parent).free)
        if free < int(self.limits.min_free_bytes):
            raise GovernanceResourceLimitError("state filesystem is below min_free_bytes")

    def _database_footprint(self) -> int:
        total = 0
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(self.path) + suffix)
            try:
                total += candidate.stat().st_size
            except FileNotFoundError:
                pass
        return total

    def _validate_artifact(self, artifact: PackageArtifact, *, kind: str) -> dict[str, Any]:
        if artifact.kind != kind:
            raise GovernanceIntegrityError(
                f"expected {kind} package, received {artifact.kind}"
            )
        if artifact.byte_size != len(artifact.canonical_bytes):
            raise GovernanceIntegrityError(f"{kind} package byte size mismatch")
        if artifact.byte_size > int(self.limits.max_package_bytes):
            raise GovernanceResourceLimitError(
                f"{kind} package exceeds max_package_bytes"
            )
        try:
            value = verify_package_bytes(artifact.canonical_bytes, artifact.digest)
        except PackageIntegrityError as exc:
            raise GovernanceIntegrityError(f"{kind} package failed verification") from exc
        if value != artifact.value:
            raise GovernanceIntegrityError(f"{kind} package value differs from its bytes")
        if artifact.schema_version != str(value.get("schema_version", "")):
            raise GovernanceIntegrityError(f"{kind} package schema metadata mismatch")
        if artifact.digest_algorithm != "sha256":
            raise GovernanceIntegrityError(f"{kind} package digest algorithm is unsupported")
        return value

    def _validated_evaluation(
        self,
        *,
        evidence: PackageArtifact,
        candidate: PackageArtifact,
        decision: PackageArtifact,
        publication: PackageArtifact | None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any] | None]:
        evidence_value = self._validate_artifact(evidence, kind="evidence")
        candidate_value = self._validate_artifact(candidate, kind="candidate")
        decision_value = self._validate_artifact(decision, kind="decision")
        publication_value = (
            self._validate_artifact(publication, kind="publication")
            if publication is not None
            else None
        )
        if candidate_value.get("evidence_digest") != evidence.digest:
            raise GovernanceIntegrityError("candidate references a different evidence package")
        if decision_value.get("candidate_digest") != candidate.digest:
            raise GovernanceIntegrityError("decision references a different candidate package")
        if decision_value.get("evidence_digest") != evidence.digest:
            raise GovernanceIntegrityError("decision references a different evidence package")
        if decision_value.get("policy_version") != candidate_value.get("policy_version"):
            raise GovernanceIntegrityError("decision policy version differs from candidate")
        if decision_value.get("controller_version") != candidate_value.get(
            "controller_version"
        ):
            raise GovernanceIntegrityError("decision controller version differs from candidate")
        outcome = str(decision_value.get("outcome", ""))
        if outcome == "AUTO_PUBLISH" and publication_value is None:
            raise GovernanceIntegrityError("AUTO_PUBLISH requires a publication package")
        if outcome != "AUTO_PUBLISH" and publication_value is not None:
            raise GovernanceIntegrityError("held or rejected decisions cannot carry publication bytes")
        if publication_value is not None:
            expected = {
                "candidate_digest": candidate.digest,
                "evidence_digest": evidence.digest,
                "decision_digest": decision.digest,
                "stable_story_id": candidate_value.get("stable_story_id"),
                "story_version": candidate_value.get("story_version"),
                "target": candidate_value.get("target"),
                "policy_version": candidate_value.get("policy_version"),
                "controller_version": candidate_value.get("controller_version"),
            }
            for field, value in expected.items():
                if publication_value.get(field) != value:
                    raise GovernanceIntegrityError(
                        f"publication {field} differs from admitted authority input"
                    )
        evidence_provenance = dict(evidence_value.get("provenance", {}))
        candidate_provenance = dict(candidate_value.get("provenance", {}))
        if (
            evidence_provenance.get("run_id") != candidate_provenance.get("run_id")
            or evidence_provenance.get("story_id") != candidate_provenance.get("story_id")
        ):
            raise GovernanceIntegrityError("candidate and evidence occurrence lineage differs")
        return evidence_value, candidate_value, decision_value, publication_value

    def _check_write_capacity(self, artifacts: Sequence[PackageArtifact]) -> None:
        self._check_free_space()
        new_bytes = 0
        for artifact in artifacts:
            row = self._conn.execute(
                "SELECT byte_size FROM packages WHERE digest=?", (artifact.digest,)
            ).fetchone()
            if row is None:
                new_bytes += artifact.byte_size
        if self._database_footprint() + new_bytes > int(self.limits.max_database_bytes):
            raise GovernanceResourceLimitError("write would exceed max_database_bytes")

    def _insert_package(self, artifact: PackageArtifact, *, created_at: str) -> None:
        row = self._conn.execute(
            """SELECT kind,schema_version,digest_algorithm,byte_size,canonical_bytes
               FROM packages WHERE digest=?""",
            (artifact.digest,),
        ).fetchone()
        if row is not None:
            if (
                str(row["kind"]) != artifact.kind
                or str(row["schema_version"]) != artifact.schema_version
                or str(row["digest_algorithm"]) != artifact.digest_algorithm
                or int(row["byte_size"]) != artifact.byte_size
                or bytes(row["canonical_bytes"]) != artifact.canonical_bytes
            ):
                raise GovernanceConflictError(
                    f"package digest is already bound to different bytes: {artifact.digest}"
                )
            return
        self._conn.execute(
            """INSERT INTO packages(
                   digest,kind,schema_version,digest_algorithm,byte_size,canonical_bytes,created_at
               ) VALUES(?,?,?,?,?,?,?)""",
            (
                artifact.digest,
                artifact.kind,
                artifact.schema_version,
                artifact.digest_algorithm,
                artifact.byte_size,
                artifact.canonical_bytes,
                created_at,
            ),
        )

    def _authority_from_row(self, row: sqlite3.Row) -> AuthorityRevision:
        return AuthorityRevision(
            authority_id=int(row["authority_id"]),
            stable_story_id=str(row["stable_story_id"]),
            story_version=str(row["story_version"]),
            target=str(row["target"]),
            revision=int(row["revision"]),
            decision_digest=str(row["decision_digest"]),
            publication_digest=(
                str(row["publication_digest"])
                if row["publication_digest"] is not None
                else None
            ),
        )

    def record_evaluation(
        self,
        *,
        evidence: PackageArtifact,
        candidate: PackageArtifact,
        decision: PackageArtifact,
        publication: PackageArtifact | None,
    ) -> AuthorityRevision:
        _, candidate_value, decision_value, _ = self._validated_evaluation(
            evidence=evidence,
            candidate=candidate,
            decision=decision,
            publication=publication,
        )
        artifacts = [evidence, candidate, decision]
        if publication is not None:
            artifacts.append(publication)
        self._check_write_capacity(artifacts)
        stable_story_id = _require_text(
            str(candidate_value.get("stable_story_id", "")), field="stable_story_id"
        )
        story_version = _require_text(
            str(candidate_value.get("story_version", "")), field="story_version"
        )
        target = _require_text(str(candidate_value.get("target", "")), field="target")
        candidate_id = _require_text(
            str(candidate_value.get("candidate_id", "")), field="candidate_id"
        )
        provenance = dict(candidate_value.get("provenance", {}))
        run_id = _require_text(str(provenance.get("run_id", "")), field="run_id")
        story_id = _require_text(str(provenance.get("story_id", "")), field="story_id")
        publication_digest = publication.digest if publication is not None else None

        with self._write_transaction():
            head = self._conn.execute(
                """SELECT h.revision,h.authority_id,h.decision_digest,
                          ar.stable_story_id,ar.story_version,ar.target,ar.publication_digest
                   FROM authority_heads h
                   JOIN authority_revisions ar ON ar.authority_id=h.authority_id
                   WHERE h.stable_story_id=? AND h.story_version=? AND h.target=?""",
                (stable_story_id, story_version, target),
            ).fetchone()
            if head is not None and str(head["decision_digest"]) == decision.digest:
                authority = self._authority_from_row(head)
                for artifact in artifacts:
                    self._verify_stored_package(artifact.digest)
                return authority

            self._check_write_capacity(artifacts)
            created_at = self._now()
            for artifact in artifacts:
                self._insert_package(artifact, created_at=created_at)
            self._conn.execute(
                "INSERT INTO stable_stories(stable_story_id,created_at) VALUES(?,?) ON CONFLICT DO NOTHING",
                (stable_story_id, created_at),
            )
            occurrence = self._conn.execute(
                """SELECT stable_story_id,story_version,run_id,story_id,candidate_digest
                   FROM occurrences WHERE candidate_id=?""",
                (candidate_id,),
            ).fetchone()
            occurrence_values = (
                stable_story_id,
                story_version,
                run_id,
                story_id,
                candidate.digest,
            )
            if occurrence is None:
                self._conn.execute(
                    """INSERT INTO occurrences(
                           candidate_id,stable_story_id,story_version,run_id,story_id,
                           candidate_digest,created_at
                       ) VALUES(?,?,?,?,?,?,?)""",
                    (candidate_id, *occurrence_values, created_at),
                )
            elif tuple(occurrence) != occurrence_values:
                raise GovernanceConflictError(
                    "candidate occurrence identity is already bound to different authority input"
                )
            decision_values = (
                candidate.digest,
                evidence.digest,
                publication_digest,
                str(decision_value["outcome"]),
                str(decision_value["policy_version"]),
                str(decision_value["controller_version"]),
            )
            existing_decision = self._conn.execute(
                """SELECT candidate_digest,evidence_digest,publication_digest,outcome,
                          policy_version,controller_version
                   FROM decisions WHERE decision_digest=?""",
                (decision.digest,),
            ).fetchone()
            if existing_decision is None:
                self._conn.execute(
                    """INSERT INTO decisions(
                           decision_digest,candidate_digest,evidence_digest,publication_digest,
                           outcome,policy_version,controller_version,created_at
                       ) VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        decision.digest,
                        *decision_values,
                        created_at,
                    ),
                )
            elif tuple(existing_decision) != decision_values:
                raise GovernanceConflictError(
                    "decision digest is already bound to different authority input"
                )
            revision = (int(head["revision"]) if head is not None else 0) + 1
            cursor = self._conn.execute(
                """INSERT INTO authority_revisions(
                       stable_story_id,story_version,target,revision,decision_digest,
                       publication_digest,created_at
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    stable_story_id,
                    story_version,
                    target,
                    revision,
                    decision.digest,
                    publication_digest,
                    created_at,
                ),
            )
            authority_id = int(cursor.lastrowid)
            if head is None:
                self._conn.execute(
                    """INSERT INTO authority_heads(
                           stable_story_id,story_version,target,revision,authority_id,decision_digest
                       ) VALUES(?,?,?,?,?,?)""",
                    (
                        stable_story_id,
                        story_version,
                        target,
                        revision,
                        authority_id,
                        decision.digest,
                    ),
                )
            else:
                changed = self._conn.execute(
                    """UPDATE authority_heads
                       SET revision=?,authority_id=?,decision_digest=?
                       WHERE stable_story_id=? AND story_version=? AND target=? AND revision=?""",
                    (
                        revision,
                        authority_id,
                        decision.digest,
                        stable_story_id,
                        story_version,
                        target,
                        revision - 1,
                    ),
                ).rowcount
                if changed != 1:
                    raise GovernanceConflictError("authority head compare-and-swap failed")
            self._conn.execute(
                "INSERT INTO delivery_claims(authority_id) VALUES(?)", (authority_id,)
            )
            self._append_audit(
                event_type=(
                    "AUTHORITY_REACTIVATED"
                    if existing_decision is not None
                    else "EVALUATION_RECORDED"
                ),
                entity_type="authority_revision",
                entity_id=str(authority_id),
                payload={
                    "stable_story_id": stable_story_id,
                    "story_version": story_version,
                    "target": target,
                    "revision": revision,
                    "candidate_id": candidate_id,
                    "evidence_digest": evidence.digest,
                    "candidate_digest": candidate.digest,
                    "decision_digest": decision.digest,
                    "publication_digest": publication_digest,
                    "outcome": str(decision_value["outcome"]),
                },
                created_at=created_at,
            )
            return AuthorityRevision(
                authority_id=authority_id,
                stable_story_id=stable_story_id,
                story_version=story_version,
                target=target,
                revision=revision,
                decision_digest=decision.digest,
                publication_digest=publication_digest,
            )

    def _verify_stored_package(self, digest: str) -> dict[str, Any]:
        row = self._conn.execute(
            """SELECT kind,schema_version,digest_algorithm,byte_size,canonical_bytes
               FROM packages WHERE digest=?""",
            (digest,),
        ).fetchone()
        if row is None:
            raise GovernanceIntegrityError(f"referenced package is missing: {digest}")
        data = bytes(row["canonical_bytes"])
        if len(data) != int(row["byte_size"]):
            raise GovernanceIntegrityError(f"stored package size differs: {digest}")
        try:
            value = verify_package_bytes(data, digest)
        except PackageIntegrityError as exc:
            raise GovernanceIntegrityError(f"stored package digest differs: {digest}") from exc
        if str(value.get("schema_version", "")) != str(row["schema_version"]):
            raise GovernanceIntegrityError(f"stored package schema differs: {digest}")
        if str(row["digest_algorithm"]) != "sha256":
            raise GovernanceIntegrityError(f"stored package algorithm differs: {digest}")
        return value

    def _verify_all_packages(self) -> None:
        for row in self._conn.execute("SELECT digest FROM packages ORDER BY digest"):
            self._verify_stored_package(str(row["digest"]))

    def inspect_authority(self, authority_id: int) -> EvaluationInspection:
        if authority_id <= 0:
            raise ValueError("authority_id must be positive")
        with self._write_transaction():
            rows = self._conn.execute(
                """SELECT ar.authority_id,ar.stable_story_id,ar.story_version,ar.target,
                          ar.revision,ar.decision_digest,ar.publication_digest,
                          o.candidate_id,o.run_id,o.story_id,d.evidence_digest,
                          d.candidate_digest,d.outcome,d.policy_version,d.controller_version
                   FROM authority_revisions ar
                   JOIN decisions d ON d.decision_digest=ar.decision_digest
                   JOIN occurrences o ON o.candidate_digest=d.candidate_digest
                   WHERE ar.authority_id=?""",
                (authority_id,),
            ).fetchall()
            if len(rows) != 1:
                raise GovernanceConflictError(
                    "exact authority identifier did not identify one revision"
                )
            row = rows[0]
            digests = [
                str(row["evidence_digest"]),
                str(row["candidate_digest"]),
                str(row["decision_digest"]),
            ]
            if row["publication_digest"] is not None:
                digests.append(str(row["publication_digest"]))
            for digest in digests:
                self._verify_stored_package(digest)
            authority = self._authority_from_row(row)
            self._append_audit(
                event_type="METADATA_INSPECTED",
                entity_type="authority_revision",
                entity_id=str(authority_id),
                payload={
                    "decision_digest": str(row["decision_digest"]),
                    "authority_id": authority.authority_id,
                    "revision": authority.revision,
                },
            )
            return EvaluationInspection(
                authority=authority,
                candidate_id=str(row["candidate_id"]),
                run_id=str(row["run_id"]),
                story_id=str(row["story_id"]),
                evidence_digest=str(row["evidence_digest"]),
                candidate_digest=str(row["candidate_digest"]),
                decision_digest=str(row["decision_digest"]),
                publication_digest=authority.publication_digest,
                outcome=str(row["outcome"]),
                policy_version=str(row["policy_version"]),
                controller_version=str(row["controller_version"]),
            )

    def inspect_evaluation(self, decision_digest: str) -> EvaluationInspection:
        """Compatibility lookup that refuses ambiguous reactivated decisions."""

        _require_text(decision_digest, field="decision_digest")
        rows = self._conn.execute(
            "SELECT authority_id FROM authority_revisions WHERE decision_digest=? ORDER BY authority_id",
            (decision_digest,),
        ).fetchall()
        if len(rows) != 1:
            raise GovernanceConflictError(
                "decision digest is absent or maps to multiple authority revisions; use authority_id"
            )
        return self.inspect_authority(int(rows[0]["authority_id"]))

    def _current_authority_row(self, authority_id: int) -> sqlite3.Row:
        row = self._conn.execute(
            """SELECT ar.authority_id,ar.stable_story_id,ar.story_version,ar.target,
                      ar.revision,ar.decision_digest,ar.publication_digest,
                      d.candidate_digest,d.evidence_digest,d.outcome
               FROM authority_revisions ar
               JOIN authority_heads h
                 ON h.stable_story_id=ar.stable_story_id
                AND h.story_version=ar.story_version
                AND h.target=ar.target
                AND h.authority_id=ar.authority_id
               JOIN decisions d ON d.decision_digest=ar.decision_digest
               WHERE ar.authority_id=?""",
            (authority_id,),
        ).fetchone()
        if row is None:
            raise GovernanceConflictError("authority revision is absent or superseded")
        return row

    def _verify_authority_packages(self, row: sqlite3.Row) -> None:
        evidence = self._verify_stored_package(str(row["evidence_digest"]))
        candidate = self._verify_stored_package(str(row["candidate_digest"]))
        decision = self._verify_stored_package(str(row["decision_digest"]))
        publication = (
            self._verify_stored_package(str(row["publication_digest"]))
            if row["publication_digest"] is not None
            else None
        )
        expected_decision = {
            "candidate_digest": str(row["candidate_digest"]),
            "evidence_digest": str(row["evidence_digest"]),
            "outcome": str(row["outcome"]),
        }
        for field, expected in expected_decision.items():
            if decision.get(field) != expected:
                raise GovernanceIntegrityError(
                    f"decision row differs from immutable package: {field}"
                )
        if candidate.get("evidence_digest") != str(row["evidence_digest"]):
            raise GovernanceIntegrityError("candidate evidence relation is corrupt")
        if not isinstance(evidence.get("provenance"), dict):
            raise GovernanceIntegrityError("evidence provenance is corrupt")
        if publication is not None and (
            publication.get("decision_digest") != str(row["decision_digest"])
            or publication.get("candidate_digest") != str(row["candidate_digest"])
            or publication.get("evidence_digest") != str(row["evidence_digest"])
        ):
            raise GovernanceIntegrityError("publication relation is corrupt")

    def _verify_relational_integrity(self) -> None:
        foreign_key_error = self._conn.execute("PRAGMA foreign_key_check").fetchone()
        if foreign_key_error is not None:
            raise GovernanceIntegrityError("governance foreign-key integrity failed")
        for row in self._conn.execute(
            """SELECT ar.authority_id,ar.stable_story_id,ar.story_version,ar.target,
                      ar.revision,ar.decision_digest,ar.publication_digest,
                      d.candidate_digest,d.evidence_digest,d.outcome
               FROM authority_revisions ar
               JOIN decisions d ON d.decision_digest=ar.decision_digest
               ORDER BY ar.authority_id"""
        ):
            self._verify_authority_packages(row)
        for row in self._conn.execute(
            """SELECT h.stable_story_id,h.story_version,h.target,h.revision,h.authority_id,
                      h.decision_digest,ar.revision AS actual_revision,
                      ar.decision_digest AS actual_decision
               FROM authority_heads h
               JOIN authority_revisions ar ON ar.authority_id=h.authority_id"""
        ):
            if (
                int(row["revision"]) != int(row["actual_revision"])
                or str(row["decision_digest"]) != str(row["actual_decision"])
            ):
                raise GovernanceIntegrityError("authority head differs from its revision")

    def claim_authority(
        self,
        authority_id: int,
        *,
        owner: str,
        expected_fence: int,
        lease_seconds: int = 60,
    ) -> DeliveryClaim:
        owner = _require_text(owner, field="owner")
        if expected_fence < 0:
            raise ValueError("expected_fence must be non-negative")
        if not 1 <= lease_seconds <= 3600:
            raise ValueError("lease_seconds must be between 1 and 3600")
        with self._write_transaction():
            pause = self.pause_state()
            if pause.paused:
                raise GovernancePausedError("shadow scope is paused")
            authority = self._current_authority_row(authority_id)
            if str(authority["outcome"]) != "AUTO_PUBLISH" or authority[
                "publication_digest"
            ] is None:
                raise GovernanceConflictError("authority is not eligible for delivery intent")
            self._verify_authority_packages(authority)
            changed_at = self._now()
            lease_expires_at = (
                _parse_utc(changed_at) + timedelta(seconds=lease_seconds)
            ).isoformat(timespec="microseconds").replace("+00:00", "Z")
            changed = self._conn.execute(
                """UPDATE delivery_claims
                   SET fence=fence+1,owner=?,pause_epoch=?,claimed_at=?,lease_expires_at=?
                   WHERE authority_id=? AND fence=?""",
                (
                    owner,
                    pause.epoch,
                    changed_at,
                    lease_expires_at,
                    authority_id,
                    expected_fence,
                ),
            ).rowcount
            if changed != 1:
                raise StaleFenceError("claim fencing token is stale")
            fence = expected_fence + 1
            self._append_audit(
                event_type="DELIVERY_CLAIMED",
                entity_type="authority_revision",
                entity_id=str(authority_id),
                payload={
                    "authority_id": authority_id,
                    "owner": owner,
                    "fence": fence,
                    "pause_epoch": pause.epoch,
                    "lease_expires_at": lease_expires_at,
                },
                created_at=changed_at,
            )
            return DeliveryClaim(
                authority_id=authority_id,
                owner=owner,
                fence=fence,
                pause_epoch=pause.epoch,
                lease_expires_at=lease_expires_at,
            )

    def _assert_claim(
        self,
        *,
        authority_id: int,
        owner: str,
        fence: int,
        require_active_lease: bool = False,
    ) -> sqlite3.Row:
        row = self._conn.execute(
            """SELECT authority_id,owner,fence,pause_epoch,lease_expires_at
               FROM delivery_claims WHERE authority_id=?""",
            (authority_id,),
        ).fetchone()
        if (
            row is None
            or str(row["owner"] or "") != owner
            or int(row["fence"]) != fence
        ):
            raise StaleFenceError("claim owner or fencing token is stale")
        if require_active_lease:
            expires = str(row["lease_expires_at"] or "")
            if not expires or _parse_utc(self._now()) >= _parse_utc(expires):
                raise StaleFenceError("claim lease has expired")
        return row

    def record_intent(
        self,
        claim: DeliveryClaim,
        *,
        action_version: str,
    ) -> DeliveryIntent:
        action_version = _require_text(action_version, field="action_version")
        with self._write_transaction():
            pause = self.pause_state()
            if pause.paused:
                raise GovernancePausedError("shadow scope is paused")
            claim_row = self._assert_claim(
                authority_id=claim.authority_id,
                owner=claim.owner,
                fence=claim.fence,
                require_active_lease=True,
            )
            if (
                int(claim_row["pause_epoch"]) != claim.pause_epoch
                or pause.epoch != claim.pause_epoch
                or str(claim_row["lease_expires_at"]) != claim.lease_expires_at
            ):
                raise StaleFenceError("pause epoch changed after the authority claim")
            authority = self._current_authority_row(claim.authority_id)
            if str(authority["outcome"]) != "AUTO_PUBLISH" or authority[
                "publication_digest"
            ] is None:
                raise GovernanceConflictError("authority is not eligible for intent")
            self._verify_authority_packages(authority)
            intent_id = _sha256(
                canonicalise_json(
                    {
                        "schema_version": "shadow_delivery_intent_v1",
                        "target": str(authority["target"]),
                        "decision_digest": str(authority["decision_digest"]),
                        "publication_digest": str(authority["publication_digest"]),
                        "action_version": action_version,
                    }
                )
            )
            existing = self._conn.execute(
                """SELECT intent_id,authority_id,action_version,owner,fence,state
                   FROM delivery_intents
                   WHERE publication_digest=? AND decision_digest=? AND target=?
                     AND action_version=?""",
                (
                    str(authority["publication_digest"]),
                    str(authority["decision_digest"]),
                    str(authority["target"]),
                    action_version,
                ),
            ).fetchone()
            if existing is not None:
                if str(existing["intent_id"]) != intent_id:
                    raise GovernanceConflictError("intent identity differs for the same action")
                return DeliveryIntent(
                    intent_id=str(existing["intent_id"]),
                    authority_id=int(existing["authority_id"]),
                    action_version=str(existing["action_version"]),
                    owner=str(existing["owner"]),
                    fence=int(existing["fence"]),
                    state=str(existing["state"]),
                )
            created_at = self._now()
            self._conn.execute(
                """INSERT INTO delivery_intents(
                       intent_id,authority_id,publication_digest,decision_digest,target,
                       action_version,owner,fence,state,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,'INTENT_RECORDED',?)""",
                (
                    intent_id,
                    claim.authority_id,
                    str(authority["publication_digest"]),
                    str(authority["decision_digest"]),
                    str(authority["target"]),
                    action_version,
                    claim.owner,
                    claim.fence,
                    created_at,
                ),
            )
            self._append_audit(
                event_type="DELIVERY_INTENT_RECORDED",
                entity_type="delivery_intent",
                entity_id=intent_id,
                payload={
                    "intent_id": intent_id,
                    "authority_id": claim.authority_id,
                    "owner": claim.owner,
                    "fence": claim.fence,
                    "pause_epoch": claim.pause_epoch,
                    "action_version": action_version,
                    "publication_digest": str(authority["publication_digest"]),
                },
                created_at=created_at,
            )
            return DeliveryIntent(
                intent_id=intent_id,
                authority_id=claim.authority_id,
                action_version=action_version,
                owner=claim.owner,
                fence=claim.fence,
                state="INTENT_RECORDED",
            )

    def record_receipt(
        self,
        intent_id: str,
        *,
        owner: str,
        fence: int,
        status: str,
        payload: Mapping[str, Any],
    ) -> DeliveryReceipt:
        intent_id = _require_text(intent_id, field="intent_id")
        owner = _require_text(owner, field="owner")
        if status not in {"RECORDED_NOT_PUBLISHED", "UNKNOWN"}:
            raise ValueError("unsupported receipt status")
        receipt_bytes = canonicalise_json(dict(payload))
        if len(receipt_bytes) > int(self.limits.max_package_bytes):
            raise GovernanceResourceLimitError("receipt exceeds max_package_bytes")
        receipt_digest = _sha256(receipt_bytes)
        with self._write_transaction():
            intent = self._conn.execute(
                """SELECT intent_id,authority_id,owner,fence,state
                   FROM delivery_intents WHERE intent_id=?""",
                (intent_id,),
            ).fetchone()
            if intent is None:
                raise GovernanceConflictError("delivery intent does not exist")
            self._assert_claim(
                authority_id=int(intent["authority_id"]), owner=owner, fence=fence
            )
            if str(intent["owner"]) != owner or int(intent["fence"]) != fence:
                raise StaleFenceError("intent belongs to a stale claim")
            existing = self._conn.execute(
                """SELECT status,receipt_digest,receipt_bytes
                   FROM receipts WHERE intent_id=?""",
                (intent_id,),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["status"]) != status
                    or str(existing["receipt_digest"]) != receipt_digest
                    or bytes(existing["receipt_bytes"]) != receipt_bytes
                ):
                    raise GovernanceConflictError("intent already has a different receipt")
                return DeliveryReceipt(
                    intent_id=intent_id,
                    status=status,
                    receipt_digest=receipt_digest,
                )
            recorded_at = self._now()
            self._conn.execute(
                """INSERT INTO receipts(
                       intent_id,status,receipt_digest,receipt_bytes,recorded_at
                   ) VALUES(?,?,?,?,?)""",
                (intent_id, status, receipt_digest, receipt_bytes, recorded_at),
            )
            changed = self._conn.execute(
                """UPDATE delivery_intents SET state=?
                   WHERE intent_id=? AND state='INTENT_RECORDED'""",
                (status, intent_id),
            ).rowcount
            if changed != 1:
                raise GovernanceConflictError("intent state cannot accept a receipt")
            self._append_audit(
                event_type="DELIVERY_RECEIPT_RECORDED",
                entity_type="delivery_intent",
                entity_id=intent_id,
                payload={
                    "intent_id": intent_id,
                    "status": status,
                    "receipt_digest": receipt_digest,
                    "owner": owner,
                    "fence": fence,
                },
                created_at=recorded_at,
            )
            return DeliveryReceipt(
                intent_id=intent_id,
                status=status,
                receipt_digest=receipt_digest,
            )

    def runtime_configuration(self) -> RuntimeConfiguration:
        return self._read_and_verify_runtime_configuration()

    def pause_state(self) -> PauseState:
        row = self._conn.execute(
            "SELECT paused,epoch,actor,reason,changed_at FROM pause_state WHERE singleton=1"
        ).fetchone()
        if row is None:
            raise GovernanceIntegrityError("pause state is missing")
        return PauseState(
            paused=bool(row["paused"]),
            epoch=int(row["epoch"]),
            actor=str(row["actor"]),
            reason=str(row["reason"]),
            changed_at=str(row["changed_at"]),
        )

    def _set_pause(self, *, paused: bool, actor: str, reason: str) -> PauseState:
        actor = _require_text(actor, field="actor")
        reason = _require_text(reason, field="reason")
        with self._write_transaction():
            current = self.pause_state()
            if current.paused is paused:
                return current
            epoch = current.epoch + 1
            changed_at = self._now()
            changed = self._conn.execute(
                """UPDATE pause_state
                   SET paused=?,epoch=?,actor=?,reason=?,changed_at=?
                   WHERE singleton=1 AND epoch=? AND paused=?""",
                (
                    int(paused),
                    epoch,
                    actor,
                    reason,
                    changed_at,
                    current.epoch,
                    int(current.paused),
                ),
            ).rowcount
            if changed != 1:
                raise GovernanceConflictError("pause epoch compare-and-swap failed")
            self._append_audit(
                event_type="SHADOW_PAUSED" if paused else "SHADOW_RESUMED",
                entity_type="pause",
                entity_id=f"global:{epoch}",
                payload={
                    "paused": paused,
                    "epoch": epoch,
                    "actor": actor,
                    "reason": reason,
                    "previous_epoch": current.epoch,
                },
                created_at=changed_at,
            )
            return PauseState(
                paused=paused,
                epoch=epoch,
                actor=actor,
                reason=reason,
                changed_at=changed_at,
            )

    def pause(self, *, actor: str, reason: str) -> PauseState:
        return self._set_pause(paused=True, actor=actor, reason=reason)

    def resume(self, *, actor: str, reason: str) -> PauseState:
        return self._set_pause(paused=False, actor=actor, reason=reason)

    def verify_audit_chain(self) -> AuditVerification:
        verified = self._verify_audit_chain_cursor(self._conn)
        self.pause_state()
        self._verify_all_packages()
        self._verify_relational_integrity()
        return verified
