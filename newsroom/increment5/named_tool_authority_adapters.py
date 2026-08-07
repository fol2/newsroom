"""Fixed read-only SQLite adapters for the two authority-backed 5C tools.

The adapters expose only repository-owned parameterised statements over the
current relational authority. They return metadata and exact receipt identities;
they never return governed object bytes. Full factual hydration and composed
Retrieval Context construction remain the Increment 5D boundary.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.authority.migrations import SCHEMA_VERSION

from .named_tool_authority_execution import (
    AttributedAuthorityResult,
    AuthorityComponentIdentity,
    AuthorityReceiptAttribution,
    NamedAuthorityMode,
    NamedAuthorityOutcome,
    NamedAuthorityPolicyBlockedError,
)
from .named_tool_contracts import (
    NAMED_TOOL_CONTRACT_DIGEST,
    NAMED_TOOL_POLICY_ID,
    NAMED_TOOL_PROFILE_ID,
    NAMED_TOOL_RESPONSE_LIMIT_BYTES,
    NAMED_TOOL_TIMEOUT_LIMIT_MS,
    CollisionHydrationLookupToolRequest,
    NamedToolContractError,
    NamedToolId,
    NamedToolRequest,
    SourceRevisionImpactLookupToolRequest,
)


AUTHORITY_PROFILE_ID = "increment5-named-authority-read-v1"
COLLISION_NAMESPACE = "candidate-development"

_COLLISION_QUERY = """
SELECT candidate_id
FROM development_candidates_v2
WHERE semantic_collision_digest=?
ORDER BY candidate_id
LIMIT 2
"""

_OBJECT_QUERY = """
SELECT a.admission_id,a.rights_decision_id,a.blob_digest,a.object_class,
       a.allowed_use,a.security_scope,a.retention_scope,a.valid_from,
       a.valid_until,a.definition_digest,a.created_at,
       av.state AS admission_state,av.reason_code AS admission_reason,
       av.recorded_at AS admission_recorded_at,
       b.size_bytes,
       bv.state AS blob_state,bv.integrity_state,bv.recorded_at AS blob_recorded_at,
       r.allowed AS rights_allowed,r.reason_code AS rights_reason,
       r.valid_from AS rights_valid_from,r.valid_until AS rights_valid_until,
       r.decided_at AS rights_decided_at,r.canonical_digest AS rights_digest,
       r.blob_digest AS rights_blob_digest,r.size_bytes AS rights_size_bytes,
       r.object_class AS rights_object_class,r.allowed_use AS rights_allowed_use,
       r.security_scope AS rights_security_scope,
       r.retention_scope AS rights_retention_scope
FROM object_admissions AS a
JOIN object_admission_heads AS ah ON ah.admission_id=a.admission_id
JOIN object_admission_versions AS av
  ON av.admission_id=ah.admission_id AND av.lifecycle_version=ah.current_version
JOIN blob_identities AS b ON b.blob_digest=a.blob_digest
JOIN blob_lifecycle_heads AS bh ON bh.blob_digest=a.blob_digest
JOIN blob_lifecycle_versions AS bv
  ON bv.blob_digest=bh.blob_digest AND bv.lifecycle_version=bh.current_version
JOIN object_rights_decisions AS r ON r.rights_decision_id=a.rights_decision_id
WHERE a.admission_id=?
LIMIT 2
"""

_PASSAGE_QUERY = """
SELECT p.run_id,p.passage_id,p.admission_id,p.access_decision_id,
       p.hydration_policy_contract_digest,p.principal_id,p.authority_domain,
       p.purpose,p.object_class,p.allowed_use,p.security_scope,
       p.retention_scope,p.byte_offset,p.byte_length,p.blob_digest,
       p.text_digest,p.language,p.canonical_digest AS passage_digest,
       a.rights_decision_id,a.valid_from,a.valid_until,
       a.object_class AS admission_object_class,
       a.allowed_use AS admission_allowed_use,
       a.security_scope AS admission_security_scope,
       a.retention_scope AS admission_retention_scope,
       av.state AS admission_state,av.reason_code AS admission_reason,
       b.size_bytes,
       bv.state AS blob_state,bv.integrity_state,
       r.allowed AS rights_allowed,r.reason_code AS rights_reason,
       r.valid_from AS rights_valid_from,r.valid_until AS rights_valid_until,
       r.decided_at AS rights_decided_at,r.canonical_digest AS rights_digest,
       r.blob_digest AS rights_blob_digest,r.size_bytes AS rights_size_bytes,
       r.object_class AS rights_object_class,r.allowed_use AS rights_allowed_use,
       r.security_scope AS rights_security_scope,
       r.retention_scope AS rights_retention_scope,
       x.admission_id AS access_admission_id,
       x.hydration_policy_contract_digest AS access_policy_digest,
       x.principal_id AS access_principal_id,
       x.authority_domain AS access_authority_domain,
       x.purpose AS access_purpose,
       x.object_class AS access_object_class,
       x.allowed_use AS access_allowed_use,
       x.security_scope AS access_security_scope,
       x.retention_scope AS access_retention_scope,
       x.byte_offset AS access_byte_offset,x.allowed_bytes
FROM extraction_run_passages AS p
JOIN object_admissions AS a ON a.admission_id=p.admission_id
JOIN object_admission_heads AS ah ON ah.admission_id=a.admission_id
JOIN object_admission_versions AS av
  ON av.admission_id=ah.admission_id AND av.lifecycle_version=ah.current_version
JOIN blob_identities AS b ON b.blob_digest=a.blob_digest
JOIN blob_lifecycle_heads AS bh ON bh.blob_digest=a.blob_digest
JOIN blob_lifecycle_versions AS bv
  ON bv.blob_digest=bh.blob_digest AND bv.lifecycle_version=bh.current_version
JOIN object_rights_decisions AS r ON r.rights_decision_id=a.rights_decision_id
JOIN object_access_decisions AS x ON x.access_decision_id=p.access_decision_id
WHERE p.passage_id=?
ORDER BY p.run_id
LIMIT 2
"""

_SOURCE_QUERY = """
SELECT definition_id,name,editorial_purpose,canonical_digest,recorded_at
FROM source_definitions
WHERE definition_id=? AND recorded_at<=?
LIMIT 2
"""

_REVISION_QUERY = """
SELECT r.revision_id,r.item_id,r.definition_id,r.definition_version_id,
       r.prior_revision_id,r.source_native_revision_token,
       r.permitted_state_digest,r.revision_identity_digest,
       r.observed_at,r.recorded_at,
       i.identity_digest AS item_identity_digest
FROM source_revisions AS r
JOIN source_items AS i ON i.item_id=r.item_id AND i.definition_id=r.definition_id
WHERE r.definition_id=?
  AND (? IS NULL OR r.revision_id=?)
  AND r.observed_at>=? AND r.observed_at<?
  AND r.observed_at<=? AND r.recorded_at<=?
  AND (?=1 OR NOT EXISTS(
      SELECT 1 FROM source_revisions AS successor
      WHERE successor.prior_revision_id=r.revision_id
        AND successor.observed_at<=? AND successor.recorded_at<=?
  ))
ORDER BY r.observed_at,r.revision_id
LIMIT ?
"""

_REPRESENTATION_QUERY = """
SELECT representation_id,revision_id,definition_id,definition_version_id,
       adapter_version,parser_version,normalizer_version,
       extraction_scope_version,permitted_fields_digest,
       representation_digest,producer_slot_digest,
       representation_identity_digest,produced_at,recorded_at,canonical_digest
FROM discovery_representations
WHERE revision_id=? AND produced_at>=? AND produced_at<?
  AND produced_at<=? AND recorded_at<=?
ORDER BY produced_at,representation_id
LIMIT ?
"""

_OCCURRENCE_QUERY = """
SELECT occurrence_id,check_outcome_id,revision_id,representation_id,
       definition_id,definition_version_id,occurrence_kind,observed_at,
       receipt_digest,semantic_digest,recorded_at,canonical_digest
FROM discovery_occurrences
WHERE revision_id=? AND observed_at>=? AND observed_at<?
  AND observed_at<=? AND recorded_at<=?
ORDER BY observed_at,occurrence_id
LIMIT ?
"""

_REVISION_TIME_INTEGRITY_QUERY = """
SELECT revision_id,observed_at,recorded_at
FROM source_revisions
WHERE definition_id=?
  AND (? IS NULL OR revision_id=?)
  AND (
      strftime('%Y-%m-%dT%H:%M:%SZ',observed_at) IS NULL
      OR strftime('%Y-%m-%dT%H:%M:%SZ',observed_at)!=observed_at
      OR strftime('%Y-%m-%dT%H:%M:%SZ',recorded_at) IS NULL
      OR strftime('%Y-%m-%dT%H:%M:%SZ',recorded_at)!=recorded_at
  )
LIMIT 1
"""

_REPRESENTATION_TIME_INTEGRITY_QUERY = """
SELECT d.representation_id,d.produced_at,d.recorded_at
FROM discovery_representations AS d
JOIN source_revisions AS r ON r.revision_id=d.revision_id
WHERE r.definition_id=?
  AND (? IS NULL OR r.revision_id=?)
  AND (
      strftime('%Y-%m-%dT%H:%M:%SZ',d.produced_at) IS NULL
      OR strftime('%Y-%m-%dT%H:%M:%SZ',d.produced_at)!=d.produced_at
      OR strftime('%Y-%m-%dT%H:%M:%SZ',d.recorded_at) IS NULL
      OR strftime('%Y-%m-%dT%H:%M:%SZ',d.recorded_at)!=d.recorded_at
  )
LIMIT 1
"""

_OCCURRENCE_TIME_INTEGRITY_QUERY = """
SELECT o.occurrence_id,o.observed_at,o.recorded_at
FROM discovery_occurrences AS o
JOIN source_revisions AS r ON r.revision_id=o.revision_id
WHERE r.definition_id=?
  AND (? IS NULL OR r.revision_id=?)
  AND (
      strftime('%Y-%m-%dT%H:%M:%SZ',o.observed_at) IS NULL
      OR strftime('%Y-%m-%dT%H:%M:%SZ',o.observed_at)!=o.observed_at
      OR strftime('%Y-%m-%dT%H:%M:%SZ',o.recorded_at) IS NULL
      OR strftime('%Y-%m-%dT%H:%M:%SZ',o.recorded_at)!=o.recorded_at
  )
LIMIT 1
"""

_REQUIRED_COLLISION_TABLES = frozenset(
    {
        "ledger_events",
        "development_candidates_v2",
        "object_admissions",
        "object_admission_heads",
        "object_admission_versions",
        "blob_identities",
        "blob_lifecycle_heads",
        "blob_lifecycle_versions",
        "object_rights_decisions",
        "object_access_decisions",
        "extraction_run_passages",
    }
)
_REQUIRED_IMPACT_TABLES = frozenset(
    {
        "ledger_events",
        "source_definitions",
        "source_items",
        "source_revisions",
        "discovery_representations",
        "discovery_occurrences",
    }
)

_WRITE_ACTIONS = frozenset(
    action
    for action in (
        getattr(sqlite3, "SQLITE_INSERT", None),
        getattr(sqlite3, "SQLITE_UPDATE", None),
        getattr(sqlite3, "SQLITE_DELETE", None),
        getattr(sqlite3, "SQLITE_CREATE_INDEX", None),
        getattr(sqlite3, "SQLITE_CREATE_TABLE", None),
        getattr(sqlite3, "SQLITE_CREATE_TEMP_INDEX", None),
        getattr(sqlite3, "SQLITE_CREATE_TEMP_TABLE", None),
        getattr(sqlite3, "SQLITE_CREATE_TEMP_TRIGGER", None),
        getattr(sqlite3, "SQLITE_CREATE_TEMP_VIEW", None),
        getattr(sqlite3, "SQLITE_CREATE_TRIGGER", None),
        getattr(sqlite3, "SQLITE_CREATE_VIEW", None),
        getattr(sqlite3, "SQLITE_DROP_INDEX", None),
        getattr(sqlite3, "SQLITE_DROP_TABLE", None),
        getattr(sqlite3, "SQLITE_DROP_TEMP_INDEX", None),
        getattr(sqlite3, "SQLITE_DROP_TEMP_TABLE", None),
        getattr(sqlite3, "SQLITE_DROP_TEMP_TRIGGER", None),
        getattr(sqlite3, "SQLITE_DROP_TEMP_VIEW", None),
        getattr(sqlite3, "SQLITE_DROP_TRIGGER", None),
        getattr(sqlite3, "SQLITE_DROP_VIEW", None),
        getattr(sqlite3, "SQLITE_ALTER_TABLE", None),
        getattr(sqlite3, "SQLITE_ATTACH", None),
        getattr(sqlite3, "SQLITE_DETACH", None),
    )
    if action is not None
)


class AuthorityAdapterIntegrityError(RuntimeError):
    """The current authority state is internally inconsistent."""


def _digest_sql(text: str) -> str:
    return digest_bytes(text.encode("utf-8"))


COLLISION_QUERY_DIGEST = _digest_sql(_COLLISION_QUERY)
OBJECT_QUERY_DIGEST = _digest_sql(_OBJECT_QUERY)
PASSAGE_QUERY_DIGEST = _digest_sql(_PASSAGE_QUERY)
SOURCE_QUERY_DIGEST = _digest_sql(_SOURCE_QUERY)
REVISION_QUERY_DIGEST = _digest_sql(_REVISION_QUERY)
REPRESENTATION_QUERY_DIGEST = _digest_sql(_REPRESENTATION_QUERY)
OCCURRENCE_QUERY_DIGEST = _digest_sql(_OCCURRENCE_QUERY)
REVISION_TIME_INTEGRITY_QUERY_DIGEST = _digest_sql(_REVISION_TIME_INTEGRITY_QUERY)
REPRESENTATION_TIME_INTEGRITY_QUERY_DIGEST = _digest_sql(
    _REPRESENTATION_TIME_INTEGRITY_QUERY
)
OCCURRENCE_TIME_INTEGRITY_QUERY_DIGEST = _digest_sql(
    _OCCURRENCE_TIME_INTEGRITY_QUERY
)

NAMED_TOOL_AUTHORITY_ADAPTER_CONTRACT_DIGEST = digest_bytes(
    canonical_json_bytes(
        {
            "schema_version": "newsroom.increment5.named-authority-adapters.v1",
            "authority_schema_version": SCHEMA_VERSION,
            "profile_id": AUTHORITY_PROFILE_ID,
            "named_tool_contract": NAMED_TOOL_CONTRACT_DIGEST,
            "policy_id": NAMED_TOOL_POLICY_ID,
            "tools": {
                NamedToolId.CURRENT_COLLISION_AND_AUTHORITY_HYDRATION_LOOKUP.value: {
                    "mode": NamedAuthorityMode.COLLISION_HYDRATION.value,
                    "queries": [
                        COLLISION_QUERY_DIGEST,
                        OBJECT_QUERY_DIGEST,
                        PASSAGE_QUERY_DIGEST,
                    ],
                    "object_bytes_returned": False,
                },
                NamedToolId.BOUNDED_SOURCE_REVISION_IMPACT_LOOKUP.value: {
                    "mode": NamedAuthorityMode.SOURCE_REVISION_IMPACT.value,
                    "queries": [
                        SOURCE_QUERY_DIGEST,
                        REVISION_QUERY_DIGEST,
                        REPRESENTATION_QUERY_DIGEST,
                        OCCURRENCE_QUERY_DIGEST,
                        REVISION_TIME_INTEGRITY_QUERY_DIGEST,
                        REPRESENTATION_TIME_INTEGRITY_QUERY_DIGEST,
                        OCCURRENCE_TIME_INTEGRITY_QUERY_DIGEST,
                    ],
                },
            },
            "timeout_ms": NAMED_TOOL_TIMEOUT_LIMIT_MS,
            "response_limit_bytes": NAMED_TOOL_RESPONSE_LIMIT_BYTES,
            "authority_effect": "NONE",
        }
    )
)


def _parse_utc(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise AuthorityAdapterIntegrityError(f"{field} is not text")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise AuthorityAdapterIntegrityError(
            f"{field} is not canonical second-resolution UTC"
        ) from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise AuthorityAdapterIntegrityError(f"{field} is not canonical UTC")
    return parsed


def _valid_at(start: object, end: object, serving: datetime, *, field: str) -> bool:
    start_time = _parse_utc(start, field=f"{field}_valid_from")
    if end is None:
        end_time = None
    else:
        end_time = _parse_utc(end, field=f"{field}_valid_until")
        if end_time <= start_time:
            raise AuthorityAdapterIntegrityError(
                f"{field} validity interval is not increasing"
            )
    return start_time <= serving and (end_time is None or serving < end_time)


def _require_int(value: object, *, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise AuthorityAdapterIntegrityError(f"{field} is not a valid integer")
    return value


def _require_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise AuthorityAdapterIntegrityError(f"{field} is not bounded text")
    return value


def _components(values: Iterable[tuple[str, str]]) -> tuple[AuthorityComponentIdentity, ...]:
    return tuple(
        AuthorityComponentIdentity(name=name, digest=digest)
        for name, digest in sorted(values)
    )


@dataclass(frozen=True, slots=True)
class NamedAuthorityAdapterConfig:
    authority_scope_id: str
    minimum_ledger_seq: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.authority_scope_id, str) or not (
            self.authority_scope_id
        ):
            raise ValueError("authority scope id must be non-empty text")
        if (
            isinstance(self.minimum_ledger_seq, bool)
            or not isinstance(self.minimum_ledger_seq, int)
            or self.minimum_ledger_seq < 0
        ):
            raise ValueError("minimum ledger sequence must be non-negative")

    @property
    def config_digest(self) -> str:
        return digest_bytes(
            canonical_json_bytes(
                {
                    "schema_version": (
                        "newsroom.increment5.named-authority-adapter-config.v1"
                    ),
                    "authority_scope_id": self.authority_scope_id,
                    "minimum_ledger_seq": self.minimum_ledger_seq,
                }
            )
        )


@dataclass(frozen=True, slots=True)
class AuthorityObjectMetadata:
    requested_object_id: str
    admission_id: str
    blob_digest: str
    size_bytes: int
    admission_state: str
    admission_reason: str
    blob_state: str
    blob_integrity_state: str
    object_class: str
    allowed_use: str
    security_scope: str
    retention_scope: str
    valid_from: str
    valid_until: str | None
    rights_decision_id: str
    rights_allowed: bool
    rights_reason: str
    rights_valid_from: str
    rights_valid_until: str | None
    rights_digest: str
    usable: bool
    block_reason: str | None

    def canonical_value(self) -> dict[str, object]:
        return {
            "requested_object_id": self.requested_object_id,
            "admission_id": self.admission_id,
            "blob_digest": self.blob_digest,
            "size_bytes": self.size_bytes,
            "admission_state": self.admission_state,
            "admission_reason": self.admission_reason,
            "blob_state": self.blob_state,
            "blob_integrity_state": self.blob_integrity_state,
            "object_class": self.object_class,
            "allowed_use": self.allowed_use,
            "security_scope": self.security_scope,
            "retention_scope": self.retention_scope,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "rights_decision_id": self.rights_decision_id,
            "rights_allowed": self.rights_allowed,
            "rights_reason": self.rights_reason,
            "rights_valid_from": self.rights_valid_from,
            "rights_valid_until": self.rights_valid_until,
            "rights_digest": self.rights_digest,
            "usable": self.usable,
            "block_reason": self.block_reason,
        }


@dataclass(frozen=True, slots=True)
class AuthorityPassageMetadata:
    passage_id: str
    run_id: str
    admission_id: str
    access_decision_id: str
    blob_digest: str
    text_digest: str
    language: str
    byte_offset: int
    byte_length: int
    object_class: str
    allowed_use: str
    security_scope: str
    retention_scope: str
    admission_state: str
    blob_state: str
    blob_integrity_state: str
    rights_decision_id: str
    rights_allowed: bool
    rights_reason: str
    rights_digest: str
    usable: bool
    block_reason: str | None

    def canonical_value(self) -> dict[str, object]:
        return {
            "passage_id": self.passage_id,
            "run_id": self.run_id,
            "admission_id": self.admission_id,
            "access_decision_id": self.access_decision_id,
            "blob_digest": self.blob_digest,
            "text_digest": self.text_digest,
            "language": self.language,
            "byte_offset": self.byte_offset,
            "byte_length": self.byte_length,
            "object_class": self.object_class,
            "allowed_use": self.allowed_use,
            "security_scope": self.security_scope,
            "retention_scope": self.retention_scope,
            "admission_state": self.admission_state,
            "blob_state": self.blob_state,
            "blob_integrity_state": self.blob_integrity_state,
            "rights_decision_id": self.rights_decision_id,
            "rights_allowed": self.rights_allowed,
            "rights_reason": self.rights_reason,
            "rights_digest": self.rights_digest,
            "usable": self.usable,
            "block_reason": self.block_reason,
        }


@dataclass(frozen=True, slots=True)
class RevisionImpactRecord:
    revision_id: str
    item_id: str
    prior_revision_id: str | None
    source_native_revision_token: str | None
    permitted_state_digest: str
    revision_identity_digest: str
    item_identity_digest: str
    observed_at: str
    recorded_at: str

    def canonical_value(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RepresentationImpactRecord:
    representation_id: str
    revision_id: str
    adapter_version: str
    parser_version: str
    normalizer_version: str
    extraction_scope_version: str
    permitted_fields_digest: str
    representation_digest: str
    producer_slot_digest: str
    representation_identity_digest: str
    produced_at: str
    recorded_at: str
    canonical_digest: str

    def canonical_value(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class OccurrenceImpactRecord:
    occurrence_id: str
    check_outcome_id: str
    revision_id: str
    representation_id: str | None
    occurrence_kind: str
    observed_at: str
    receipt_digest: str
    semantic_digest: str
    recorded_at: str
    canonical_digest: str

    def canonical_value(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CollisionHydrationAuthorityReceipt:
    request_digest: str
    adapter_contract_digest: str
    adapter_config_digest: str
    authority_scope_id: str
    authority_watermark: int
    collision_namespace: str
    collision_key_digest: str
    collision_state: str
    candidate_id: str | None
    objects: tuple[AuthorityObjectMetadata, ...]
    passages: tuple[AuthorityPassageMetadata, ...]
    missing_object_ids: tuple[str, ...]
    missing_passage_ids: tuple[str, ...]
    ambiguous_passage_ids: tuple[str, ...]
    outcome: NamedAuthorityOutcome
    reason: str | None
    result_count: int
    no_match: bool
    query_valid_time: str
    serving_time: str
    object_bytes_returned: bool = False
    authority_effect: str = "NONE"

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(
            {
                "schema_version": (
                    "newsroom.increment5.collision-hydration-authority-receipt.v1"
                ),
                "request_digest": self.request_digest,
                "adapter_contract_digest": self.adapter_contract_digest,
                "adapter_config_digest": self.adapter_config_digest,
                "authority_scope_id": self.authority_scope_id,
                "authority_watermark": self.authority_watermark,
                "collision_namespace": self.collision_namespace,
                "collision_key_digest": self.collision_key_digest,
                "collision_state": self.collision_state,
                "candidate_id": self.candidate_id,
                "objects": [item.canonical_value() for item in self.objects],
                "passages": [item.canonical_value() for item in self.passages],
                "missing_object_ids": list(self.missing_object_ids),
                "missing_passage_ids": list(self.missing_passage_ids),
                "ambiguous_passage_ids": list(self.ambiguous_passage_ids),
                "outcome": self.outcome.value,
                "reason": self.reason,
                "result_count": self.result_count,
                "no_match": self.no_match,
                "query_valid_time": self.query_valid_time,
                "serving_time": self.serving_time,
                "object_bytes_returned": self.object_bytes_returned,
                "authority_effect": self.authority_effect,
            }
        )


@dataclass(frozen=True, slots=True)
class SourceRevisionImpactAuthorityReceipt:
    request_digest: str
    adapter_contract_digest: str
    adapter_config_digest: str
    authority_scope_id: str
    authority_watermark: int
    source_id: str
    source_definition_digest: str | None
    revision_id: str | None
    window_start: str
    window_end: str
    lineage_depth: int
    include_superseded: bool
    revisions: tuple[RevisionImpactRecord, ...]
    representations: tuple[RepresentationImpactRecord, ...]
    occurrences: tuple[OccurrenceImpactRecord, ...]
    outcome: NamedAuthorityOutcome
    reason: str | None
    result_count: int
    no_match: bool
    query_valid_time: str
    serving_time: str
    authority_effect: str = "NONE"

    def __post_init__(self) -> None:
        query_valid = _parse_utc(
            self.query_valid_time, field="impact_receipt_query_valid_time"
        )
        serving = _parse_utc(
            self.serving_time, field="impact_receipt_serving_time"
        )
        if query_valid > serving:
            raise AuthorityAdapterIntegrityError(
                "impact receipt query-valid time is after serving time"
            )
        window_start = _parse_utc(
            self.window_start, field="impact_receipt_window_start"
        )
        window_end = _parse_utc(
            self.window_end, field="impact_receipt_window_end"
        )
        if window_start >= window_end:
            raise AuthorityAdapterIntegrityError(
                "impact receipt window is not increasing"
            )
        if type(self.include_superseded) is not bool:
            raise AuthorityAdapterIntegrityError(
                "impact receipt supersession flag is not boolean"
            )
        if self.lineage_depth not in (1, 2):
            raise AuthorityAdapterIntegrityError(
                "impact receipt lineage depth is outside the fixed bound"
            )
        if not all(
            isinstance(item, RevisionImpactRecord) for item in self.revisions
        ):
            raise AuthorityAdapterIntegrityError(
                "impact receipt revisions are not typed"
            )
        if not all(
            isinstance(item, RepresentationImpactRecord)
            for item in self.representations
        ):
            raise AuthorityAdapterIntegrityError(
                "impact receipt representations are not typed"
            )
        if not all(
            isinstance(item, OccurrenceImpactRecord) for item in self.occurrences
        ):
            raise AuthorityAdapterIntegrityError(
                "impact receipt occurrences are not typed"
            )
        if self.lineage_depth == 1 and (self.representations or self.occurrences):
            raise AuthorityAdapterIntegrityError(
                "depth-one impact receipt cannot retain dependent lineage"
            )
        revision_ids = {item.revision_id for item in self.revisions}
        if len(revision_ids) != len(self.revisions):
            raise AuthorityAdapterIntegrityError(
                "impact receipt revision identities are not unique"
            )
        for revision in self.revisions:
            observed = _parse_utc(
                revision.observed_at, field="impact_revision_observed_at"
            )
            recorded = _parse_utc(
                revision.recorded_at, field="impact_revision_recorded_at"
            )
            if not window_start <= observed < window_end:
                raise AuthorityAdapterIntegrityError(
                    "impact revision is outside the requested window"
                )
            if observed > query_valid or recorded > query_valid:
                raise AuthorityAdapterIntegrityError(
                    "impact revision is after the query-valid cutoff"
                )
            if self.revision_id is not None and revision.revision_id != self.revision_id:
                raise AuthorityAdapterIntegrityError(
                    "impact revision does not match the requested identity"
                )
        for representation in self.representations:
            produced = _parse_utc(
                representation.produced_at,
                field="impact_representation_produced_at",
            )
            recorded = _parse_utc(
                representation.recorded_at,
                field="impact_representation_recorded_at",
            )
            if representation.revision_id not in revision_ids:
                raise AuthorityAdapterIntegrityError(
                    "impact representation lacks its retained revision"
                )
            if not window_start <= produced < window_end:
                raise AuthorityAdapterIntegrityError(
                    "impact representation is outside the requested window"
                )
            if produced > query_valid or recorded > query_valid:
                raise AuthorityAdapterIntegrityError(
                    "impact representation is after the query-valid cutoff"
                )
        for occurrence in self.occurrences:
            observed = _parse_utc(
                occurrence.observed_at, field="impact_occurrence_observed_at"
            )
            recorded = _parse_utc(
                occurrence.recorded_at, field="impact_occurrence_recorded_at"
            )
            if occurrence.revision_id not in revision_ids:
                raise AuthorityAdapterIntegrityError(
                    "impact occurrence lacks its retained revision"
                )
            if not window_start <= observed < window_end:
                raise AuthorityAdapterIntegrityError(
                    "impact occurrence is outside the requested window"
                )
            if observed > query_valid or recorded > query_valid:
                raise AuthorityAdapterIntegrityError(
                    "impact occurrence is after the query-valid cutoff"
                )
        if self.source_definition_digest is not None:
            validate_sha256_digest(
                self.source_definition_digest, field="source_definition_digest"
            )
        if self.authority_effect != "NONE":
            raise AuthorityAdapterIntegrityError(
                "impact receipt cannot claim an authority effect"
            )

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(
            {
                "schema_version": (
                    "newsroom.increment5.source-revision-impact-authority-receipt.v1"
                ),
                "request_digest": self.request_digest,
                "adapter_contract_digest": self.adapter_contract_digest,
                "adapter_config_digest": self.adapter_config_digest,
                "authority_scope_id": self.authority_scope_id,
                "authority_watermark": self.authority_watermark,
                "source_id": self.source_id,
                "source_definition_digest": self.source_definition_digest,
                "revision_id": self.revision_id,
                "window_start": self.window_start,
                "window_end": self.window_end,
                "lineage_depth": self.lineage_depth,
                "include_superseded": self.include_superseded,
                "revisions": [item.canonical_value() for item in self.revisions],
                "representations": [
                    item.canonical_value() for item in self.representations
                ],
                "occurrences": [
                    item.canonical_value() for item in self.occurrences
                ],
                "outcome": self.outcome.value,
                "reason": self.reason,
                "result_count": self.result_count,
                "no_match": self.no_match,
                "query_valid_time": self.query_valid_time,
                "serving_time": self.serving_time,
                "authority_effect": self.authority_effect,
            }
        )


class _SQLiteAuthorityPort:
    def __init__(
        self,
        *,
        authority_database: Path,
        config: NamedAuthorityAdapterConfig,
        monotonic_ns=time.monotonic_ns,
    ) -> None:
        if not isinstance(authority_database, Path):
            raise TypeError("authority database path must be pathlib.Path")
        if not isinstance(config, NamedAuthorityAdapterConfig):
            raise TypeError("authority adapter configuration must be typed")
        if not callable(monotonic_ns):
            raise TypeError("authority adapter clock must be callable")
        self.authority_database = authority_database.resolve()
        self.config = config
        self.monotonic_ns = monotonic_ns

    def _preflight(self, request: NamedToolRequest, expected: NamedToolId) -> None:
        envelope = request.envelope
        if envelope.tool_id is not expected:
            raise NamedAuthorityPolicyBlockedError(
                "named request does not match authority adapter tool"
            )
        if (
            envelope.policy_id != NAMED_TOOL_POLICY_ID
            or envelope.contract_digest != NAMED_TOOL_CONTRACT_DIGEST
            or envelope.profile_id != NAMED_TOOL_PROFILE_ID
        ):
            raise NamedAuthorityPolicyBlockedError(
                "named request does not use accepted policy, contract and profile"
            )
        if envelope.timeout_ms != NAMED_TOOL_TIMEOUT_LIMIT_MS:
            raise NamedAuthorityPolicyBlockedError(
                "authority adapter cannot safely honour a narrower timeout"
            )

    def _open_snapshot(self) -> sqlite3.Connection:
        if not self.authority_database.is_file():
            raise sqlite3.OperationalError("authority database unavailable")
        connection = sqlite3.connect(
            self.authority_database.as_uri() + "?mode=ro",
            uri=True,
            isolation_level=None,
            timeout=5.0,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("BEGIN")
        connection.set_authorizer(self._read_only_authorizer)
        return connection

    @staticmethod
    def _read_only_authorizer(
        action: int,
        _arg1: str | None,
        _arg2: str | None,
        _database: str | None,
        _trigger: str | None,
    ) -> int:
        return sqlite3.SQLITE_DENY if action in _WRITE_ACTIONS else sqlite3.SQLITE_OK

    @staticmethod
    def _close_snapshot(connection: sqlite3.Connection) -> None:
        connection.set_progress_handler(None, 0)
        connection.set_authorizer(None)
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        connection.close()

    @staticmethod
    def _has_tables(
        connection: sqlite3.Connection, required: frozenset[str]
    ) -> bool:
        placeholders = ",".join("?" for _ in required)
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ("
            + placeholders
            + ")",
            tuple(sorted(required)),
        ).fetchall()
        return {str(row["name"]) for row in rows} == set(required)

    @staticmethod
    def _watermark(connection: sqlite3.Connection) -> int:
        row = connection.execute(
            "SELECT COALESCE(MAX(ledger_seq),0) AS watermark FROM ledger_events"
        ).fetchone()
        return _require_int(row["watermark"] if row else 0, field="watermark")

    def _deadline(self, request: NamedToolRequest) -> int:
        return self.monotonic_ns() + request.envelope.timeout_ms * 1_000_000

    def _progress(self, deadline: int):
        return lambda: 1 if self.monotonic_ns() > deadline else 0

    def _attributed(
        self,
        *,
        request: NamedToolRequest,
        mode: NamedAuthorityMode,
        schema_version: str,
        authority_request_digest: str,
        raw: bytes,
        outcome: NamedAuthorityOutcome,
        reason: str | None,
        result_count: int,
        no_match: bool,
        watermark: int,
        components: Sequence[tuple[str, str]],
    ) -> AttributedAuthorityResult:
        if len(raw) > NAMED_TOOL_RESPONSE_LIMIT_BYTES:
            raise NamedToolContractError(
                "authority receipt exceeds the absolute response bound"
            )
        attribution = AuthorityReceiptAttribution(
            tool_request_digest=request.request_digest,
            tool_id=request.envelope.tool_id,
            authority_mode=mode,
            authority_schema_version=schema_version,
            authority_request_digest=authority_request_digest,
            authority_receipt_digest=digest_bytes(raw),
            authority_profile_id=AUTHORITY_PROFILE_ID,
            component_identities=_components(components),
            query_valid_time=request.envelope.query_valid_time,
            serving_time=request.envelope.serving_time,
            outcome=outcome,
            reason=reason,
            result_count=result_count,
            no_match=no_match,
            authority_watermark=watermark,
            authority_receipt_bytes=len(raw),
        )
        return AttributedAuthorityResult(
            attribution=attribution,
            authority_receipt_bytes=raw,
        )


class CollisionHydrationNamedToolPort(_SQLiteAuthorityPort):
    port_id = "increment5.named.collision-hydration.v1"
    tool_id = NamedToolId.CURRENT_COLLISION_AND_AUTHORITY_HYDRATION_LOOKUP
    authority_mode = NamedAuthorityMode.COLLISION_HYDRATION

    def execute(self, request: NamedToolRequest) -> AttributedAuthorityResult:
        if not isinstance(request, CollisionHydrationLookupToolRequest):
            raise NamedAuthorityPolicyBlockedError(
                "collision adapter requires its typed request"
            )
        self._preflight(request, self.tool_id)
        if request.collision_namespace != COLLISION_NAMESPACE:
            raise NamedAuthorityPolicyBlockedError(
                "collision namespace is not in the closed authority surface"
            )
        authority_request_digest = digest_bytes(
            canonical_json_bytes(
                {
                    "schema_version": (
                        "newsroom.increment5.collision-hydration-authority-request.v1"
                    ),
                    "tool_request_digest": request.request_digest,
                    "adapter_config_digest": self.config.config_digest,
                }
            )
        )
        watermark = 0
        connection: sqlite3.Connection | None = None
        try:
            connection = self._open_snapshot()
            if not self._has_tables(connection, _REQUIRED_COLLISION_TABLES):
                return self._receipt(
                    request,
                    authority_request_digest=authority_request_digest,
                    watermark=0,
                    outcome=NamedAuthorityOutcome.UNAVAILABLE,
                    reason="AUTHORITY_SCHEMA_UNAVAILABLE",
                )
            watermark = self._watermark(connection)
            if watermark < self.config.minimum_ledger_seq:
                return self._receipt(
                    request,
                    authority_request_digest=authority_request_digest,
                    watermark=watermark,
                    outcome=NamedAuthorityOutcome.STALE,
                    reason="AUTHORITY_WATERMARK_STALE",
                )
            if (
                len(request.authority_object_ids) + len(request.passage_ids)
                > request.envelope.result_limit
            ):
                return self._receipt(
                    request,
                    authority_request_digest=authority_request_digest,
                    watermark=watermark,
                    outcome=NamedAuthorityOutcome.INCOMPLETE,
                    reason="RESULT_BOUND_EXCEEDED",
                )
            deadline = self._deadline(request)
            connection.set_progress_handler(self._progress(deadline), 250)
            collision_rows = connection.execute(
                _COLLISION_QUERY, (request.collision_key_digest,)
            ).fetchall()
            if len(collision_rows) > 1:
                raise AuthorityAdapterIntegrityError(
                    "collision digest resolves to multiple Candidates"
                )
            candidate_id = (
                None
                if not collision_rows
                else _require_text(collision_rows[0]["candidate_id"], field="candidate_id")
            )
            serving = _parse_utc(request.envelope.serving_time, field="serving_time")
            objects: list[AuthorityObjectMetadata] = []
            missing_objects: list[str] = []
            for object_id in request.authority_object_ids:
                rows = connection.execute(_OBJECT_QUERY, (object_id,)).fetchall()
                if not rows:
                    missing_objects.append(object_id)
                elif len(rows) != 1:
                    raise AuthorityAdapterIntegrityError(
                        "authority object identity is ambiguous"
                    )
                else:
                    objects.append(self._object_metadata(object_id, rows[0], serving))
            passages: list[AuthorityPassageMetadata] = []
            missing_passages: list[str] = []
            ambiguous_passages: list[str] = []
            for passage_id in request.passage_ids:
                rows = connection.execute(_PASSAGE_QUERY, (passage_id,)).fetchall()
                if not rows:
                    missing_passages.append(passage_id)
                elif len(rows) > 1:
                    ambiguous_passages.append(passage_id)
                else:
                    passages.append(self._passage_metadata(rows[0], serving))
            result_count = (1 if candidate_id is not None else 0) + len(objects) + len(passages)
            if result_count > request.envelope.result_limit:
                outcome = NamedAuthorityOutcome.INCOMPLETE
                reason = "RESULT_BOUND_EXCEEDED"
                visible_count = 0
                no_match = False
            elif missing_objects or missing_passages or ambiguous_passages:
                outcome = NamedAuthorityOutcome.INCOMPLETE
                reason = "REQUESTED_AUTHORITY_UNAVAILABLE"
                visible_count = 0
                no_match = False
            elif any(not item.usable for item in (*objects, *passages)):
                outcome = NamedAuthorityOutcome.POLICY_BLOCKED
                reason = "RIGHTS_OR_LIFECYCLE_BLOCKED"
                visible_count = 0
                no_match = False
            else:
                outcome = NamedAuthorityOutcome.COMPLETE
                reason = "NO_MATCH" if result_count == 0 else None
                visible_count = result_count
                no_match = result_count == 0
            receipt = CollisionHydrationAuthorityReceipt(
                request_digest=request.request_digest,
                adapter_contract_digest=NAMED_TOOL_AUTHORITY_ADAPTER_CONTRACT_DIGEST,
                adapter_config_digest=self.config.config_digest,
                authority_scope_id=self.config.authority_scope_id,
                authority_watermark=watermark,
                collision_namespace=request.collision_namespace,
                collision_key_digest=request.collision_key_digest,
                collision_state="OCCUPIED" if candidate_id else "UNOCCUPIED",
                candidate_id=candidate_id,
                objects=tuple(objects),
                passages=tuple(passages),
                missing_object_ids=tuple(missing_objects),
                missing_passage_ids=tuple(missing_passages),
                ambiguous_passage_ids=tuple(ambiguous_passages),
                outcome=outcome,
                reason=reason,
                result_count=visible_count,
                no_match=no_match,
                query_valid_time=request.envelope.query_valid_time,
                serving_time=request.envelope.serving_time,
            )
            raw = receipt.canonical_bytes
            return self._attributed(
                request=request,
                mode=self.authority_mode,
                schema_version="newsroom.increment5.collision-hydration-authority-receipt.v1",
                authority_request_digest=authority_request_digest,
                raw=raw,
                outcome=outcome,
                reason=reason,
                result_count=visible_count,
                no_match=no_match,
                watermark=watermark,
                components=(
                    ("adapter_config", self.config.config_digest),
                    ("adapter_contract", NAMED_TOOL_AUTHORITY_ADAPTER_CONTRACT_DIGEST),
                    ("collision_query", COLLISION_QUERY_DIGEST),
                    ("named_tool_contract", NAMED_TOOL_CONTRACT_DIGEST),
                    ("object_query", OBJECT_QUERY_DIGEST),
                    ("passage_query", PASSAGE_QUERY_DIGEST),
                ),
            )
        except sqlite3.OperationalError as exc:
            reason = "QUERY_TIMEOUT" if "interrupted" in str(exc).lower() else "AUTHORITY_DATABASE_UNAVAILABLE"
            return self._receipt(
                request,
                authority_request_digest=authority_request_digest,
                watermark=watermark,
                outcome=NamedAuthorityOutcome.INCOMPLETE if reason == "QUERY_TIMEOUT" else NamedAuthorityOutcome.UNAVAILABLE,
                reason=reason,
            )
        except (sqlite3.Error, AuthorityAdapterIntegrityError, ValueError):
            return self._receipt(
                request,
                authority_request_digest=authority_request_digest,
                watermark=watermark,
                outcome=NamedAuthorityOutcome.UNAVAILABLE,
                reason="AUTHORITY_INTEGRITY_ERROR",
            )
        finally:
            if connection is not None:
                self._close_snapshot(connection)

    def _receipt(
        self,
        request: CollisionHydrationLookupToolRequest,
        *,
        authority_request_digest: str,
        watermark: int,
        outcome: NamedAuthorityOutcome,
        reason: str,
    ) -> AttributedAuthorityResult:
        receipt = CollisionHydrationAuthorityReceipt(
            request_digest=request.request_digest,
            adapter_contract_digest=NAMED_TOOL_AUTHORITY_ADAPTER_CONTRACT_DIGEST,
            adapter_config_digest=self.config.config_digest,
            authority_scope_id=self.config.authority_scope_id,
            authority_watermark=watermark,
            collision_namespace=request.collision_namespace,
            collision_key_digest=request.collision_key_digest,
            collision_state="UNKNOWN",
            candidate_id=None,
            objects=(),
            passages=(),
            missing_object_ids=(),
            missing_passage_ids=(),
            ambiguous_passage_ids=(),
            outcome=outcome,
            reason=reason,
            result_count=0,
            no_match=False,
            query_valid_time=request.envelope.query_valid_time,
            serving_time=request.envelope.serving_time,
        )
        raw = receipt.canonical_bytes
        return self._attributed(
            request=request,
            mode=self.authority_mode,
            schema_version="newsroom.increment5.collision-hydration-authority-receipt.v1",
            authority_request_digest=authority_request_digest,
            raw=raw,
            outcome=outcome,
            reason=reason,
            result_count=0,
            no_match=False,
            watermark=watermark,
            components=(
                ("adapter_config", self.config.config_digest),
                ("adapter_contract", NAMED_TOOL_AUTHORITY_ADAPTER_CONTRACT_DIGEST),
                ("collision_query", COLLISION_QUERY_DIGEST),
                ("named_tool_contract", NAMED_TOOL_CONTRACT_DIGEST),
                ("object_query", OBJECT_QUERY_DIGEST),
                ("passage_query", PASSAGE_QUERY_DIGEST),
            ),
        )

    @staticmethod
    def _object_metadata(
        requested_id: str, row: sqlite3.Row, serving: datetime
    ) -> AuthorityObjectMetadata:
        admission_id = _require_text(row["admission_id"], field="admission_id")
        if admission_id != requested_id:
            raise AuthorityAdapterIntegrityError("object request binding mismatch")
        blob_digest = validate_sha256_digest(row["blob_digest"], field="blob_digest")
        rights_blob = validate_sha256_digest(
            row["rights_blob_digest"], field="rights_blob_digest"
        )
        metadata = (
            _require_text(row["object_class"], field="object_class"),
            _require_text(row["allowed_use"], field="allowed_use"),
            _require_text(row["security_scope"], field="security_scope"),
            _require_text(row["retention_scope"], field="retention_scope"),
        )
        rights_metadata = (
            _require_text(row["rights_object_class"], field="rights_object_class"),
            _require_text(row["rights_allowed_use"], field="rights_allowed_use"),
            _require_text(row["rights_security_scope"], field="rights_security_scope"),
            _require_text(row["rights_retention_scope"], field="rights_retention_scope"),
        )
        size = _require_int(row["size_bytes"], field="size_bytes")
        if blob_digest != rights_blob or metadata != rights_metadata or size != _require_int(
            row["rights_size_bytes"], field="rights_size_bytes"
        ):
            raise AuthorityAdapterIntegrityError(
                "rights decision metadata differs from admission"
            )
        rights_allowed_value = _require_int(
            row["rights_allowed"], field="rights_allowed"
        )
        if rights_allowed_value not in (0, 1):
            raise AuthorityAdapterIntegrityError("rights allowed value is invalid")
        for name in (
            "created_at",
            "admission_recorded_at",
            "blob_recorded_at",
            "rights_decided_at",
        ):
            if name in row.keys():
                _parse_utc(row[name], field=name)
        admission_valid = _valid_at(
            row["valid_from"], row["valid_until"], serving, field="admission"
        )
        rights_valid = _valid_at(
            row["rights_valid_from"],
            row["rights_valid_until"],
            serving,
            field="rights",
        )
        admission_state = _require_text(row["admission_state"], field="admission_state")
        blob_state = _require_text(row["blob_state"], field="blob_state")
        integrity = _require_text(row["integrity_state"], field="integrity_state")
        usable = (
            admission_state == "ACTIVE"
            and blob_state == "ACTIVE"
            and integrity == "VERIFIED"
            and rights_allowed_value == 1
            and admission_valid
            and rights_valid
        )
        reasons = []
        if admission_state != "ACTIVE":
            reasons.append("ADMISSION_NOT_ACTIVE")
        if blob_state != "ACTIVE":
            reasons.append("BLOB_NOT_ACTIVE")
        if integrity != "VERIFIED":
            reasons.append("BLOB_NOT_VERIFIED")
        if rights_allowed_value != 1:
            reasons.append("RIGHTS_DENIED")
        if not admission_valid:
            reasons.append("ADMISSION_NOT_CURRENT")
        if not rights_valid:
            reasons.append("RIGHTS_NOT_CURRENT")
        return AuthorityObjectMetadata(
            requested_object_id=requested_id,
            admission_id=admission_id,
            blob_digest=blob_digest,
            size_bytes=size,
            admission_state=admission_state,
            admission_reason=_require_text(row["admission_reason"], field="admission_reason"),
            blob_state=blob_state,
            blob_integrity_state=integrity,
            object_class=metadata[0],
            allowed_use=metadata[1],
            security_scope=metadata[2],
            retention_scope=metadata[3],
            valid_from=_require_text(row["valid_from"], field="valid_from"),
            valid_until=row["valid_until"],
            rights_decision_id=_require_text(row["rights_decision_id"], field="rights_decision_id"),
            rights_allowed=rights_allowed_value == 1,
            rights_reason=_require_text(row["rights_reason"], field="rights_reason"),
            rights_valid_from=_require_text(row["rights_valid_from"], field="rights_valid_from"),
            rights_valid_until=row["rights_valid_until"],
            rights_digest=validate_sha256_digest(row["rights_digest"], field="rights_digest"),
            usable=usable,
            block_reason=None if usable else "+".join(reasons),
        )

    @classmethod
    def _passage_metadata(
        cls, row: sqlite3.Row, serving: datetime
    ) -> AuthorityPassageMetadata:
        admission = cls._object_metadata(str(row["admission_id"]), row, serving)
        passage_metadata = (
            _require_text(row["object_class"], field="passage_object_class"),
            _require_text(row["allowed_use"], field="passage_allowed_use"),
            _require_text(row["security_scope"], field="passage_security_scope"),
            _require_text(row["retention_scope"], field="passage_retention_scope"),
        )
        admission_metadata = (
            _require_text(row["admission_object_class"], field="admission_object_class"),
            _require_text(row["admission_allowed_use"], field="admission_allowed_use"),
            _require_text(row["admission_security_scope"], field="admission_security_scope"),
            _require_text(row["admission_retention_scope"], field="admission_retention_scope"),
        )
        access_metadata = (
            _require_text(row["access_object_class"], field="access_object_class"),
            _require_text(row["access_allowed_use"], field="access_allowed_use"),
            _require_text(row["access_security_scope"], field="access_security_scope"),
            _require_text(row["access_retention_scope"], field="access_retention_scope"),
        )
        if not passage_metadata == admission_metadata == access_metadata:
            raise AuthorityAdapterIntegrityError(
                "passage, admission, and access metadata differ"
            )
        if row["access_admission_id"] != row["admission_id"]:
            raise AuthorityAdapterIntegrityError("passage access admission differs")
        if row["access_policy_digest"] != row["hydration_policy_contract_digest"]:
            raise AuthorityAdapterIntegrityError("passage access policy differs")
        if (
            row["access_principal_id"] != row["principal_id"]
            or row["access_authority_domain"] != row["authority_domain"]
            or row["access_purpose"] != row["purpose"]
        ):
            raise AuthorityAdapterIntegrityError("passage access identity differs")
        offset = _require_int(row["byte_offset"], field="byte_offset")
        length = _require_int(row["byte_length"], field="byte_length", minimum=1)
        access_offset = _require_int(row["access_byte_offset"], field="access_byte_offset")
        allowed_bytes = _require_int(row["allowed_bytes"], field="allowed_bytes")
        if access_offset > offset or offset + length > access_offset + allowed_bytes:
            raise AuthorityAdapterIntegrityError("passage exceeds access decision range")
        passage_blob = validate_sha256_digest(row["blob_digest"], field="passage_blob_digest")
        if passage_blob != admission.blob_digest:
            raise AuthorityAdapterIntegrityError("passage blob differs from admission")
        return AuthorityPassageMetadata(
            passage_id=_require_text(row["passage_id"], field="passage_id"),
            run_id=_require_text(row["run_id"], field="run_id"),
            admission_id=admission.admission_id,
            access_decision_id=_require_text(row["access_decision_id"], field="access_decision_id"),
            blob_digest=passage_blob,
            text_digest=validate_sha256_digest(row["text_digest"], field="text_digest"),
            language=_require_text(row["language"], field="language"),
            byte_offset=offset,
            byte_length=length,
            object_class=passage_metadata[0],
            allowed_use=passage_metadata[1],
            security_scope=passage_metadata[2],
            retention_scope=passage_metadata[3],
            admission_state=admission.admission_state,
            blob_state=admission.blob_state,
            blob_integrity_state=admission.blob_integrity_state,
            rights_decision_id=admission.rights_decision_id,
            rights_allowed=admission.rights_allowed,
            rights_reason=admission.rights_reason,
            rights_digest=admission.rights_digest,
            usable=admission.usable,
            block_reason=admission.block_reason,
        )


class SourceRevisionImpactNamedToolPort(_SQLiteAuthorityPort):
    port_id = "increment5.named.source-revision-impact.v1"
    tool_id = NamedToolId.BOUNDED_SOURCE_REVISION_IMPACT_LOOKUP
    authority_mode = NamedAuthorityMode.SOURCE_REVISION_IMPACT

    def execute(self, request: NamedToolRequest) -> AttributedAuthorityResult:
        if not isinstance(request, SourceRevisionImpactLookupToolRequest):
            raise NamedAuthorityPolicyBlockedError(
                "source impact adapter requires its typed request"
            )
        self._preflight(request, self.tool_id)
        authority_request_digest = digest_bytes(
            canonical_json_bytes(
                {
                    "schema_version": (
                        "newsroom.increment5.source-revision-impact-authority-request.v1"
                    ),
                    "tool_request_digest": request.request_digest,
                    "adapter_config_digest": self.config.config_digest,
                }
            )
        )
        watermark = 0
        connection: sqlite3.Connection | None = None
        try:
            connection = self._open_snapshot()
            if not self._has_tables(connection, _REQUIRED_IMPACT_TABLES):
                return self._receipt(request, authority_request_digest, 0, NamedAuthorityOutcome.UNAVAILABLE, "AUTHORITY_SCHEMA_UNAVAILABLE")
            watermark = self._watermark(connection)
            if watermark < self.config.minimum_ledger_seq:
                return self._receipt(request, authority_request_digest, watermark, NamedAuthorityOutcome.STALE, "AUTHORITY_WATERMARK_STALE")
            deadline = self._deadline(request)
            connection.set_progress_handler(self._progress(deadline), 250)
            source_rows = connection.execute(
                _SOURCE_QUERY,
                (request.source_id, request.envelope.query_valid_time),
            ).fetchall()
            if len(source_rows) > 1:
                raise AuthorityAdapterIntegrityError("source identity is ambiguous")
            source_digest = None if not source_rows else validate_sha256_digest(
                source_rows[0]["canonical_digest"], field="source_definition_digest"
            )
            if source_rows:
                _parse_utc(source_rows[0]["recorded_at"], field="source_recorded_at")
                integrity_parameters = (
                    request.source_id,
                    request.revision_id,
                    request.revision_id,
                )
                for statement in (
                    _REVISION_TIME_INTEGRITY_QUERY,
                    _REPRESENTATION_TIME_INTEGRITY_QUERY,
                    _OCCURRENCE_TIME_INTEGRITY_QUERY,
                ):
                    if connection.execute(
                        statement, integrity_parameters
                    ).fetchone() is not None:
                        raise AuthorityAdapterIntegrityError(
                            "source lineage contains a non-canonical timestamp"
                        )
            limit = request.envelope.result_limit + 1
            revision_rows = [] if not source_rows else connection.execute(
                _REVISION_QUERY,
                (
                    request.source_id,
                    request.revision_id,
                    request.revision_id,
                    request.window_start,
                    request.window_end,
                    request.envelope.query_valid_time,
                    request.envelope.query_valid_time,
                    1 if request.include_superseded else 0,
                    request.envelope.query_valid_time,
                    request.envelope.query_valid_time,
                    limit,
                ),
            ).fetchall()
            revisions = tuple(self._revision(row, request.source_id) for row in revision_rows)
            representations: list[RepresentationImpactRecord] = []
            occurrences: list[OccurrenceImpactRecord] = []
            if request.lineage_depth == 2:
                for revision in revisions:
                    representations.extend(
                        self._representation(row, request.source_id, revision.revision_id)
                        for row in connection.execute(
                            _REPRESENTATION_QUERY,
                            (
                                revision.revision_id,
                                request.window_start,
                                request.window_end,
                                request.envelope.query_valid_time,
                                request.envelope.query_valid_time,
                                limit,
                            ),
                        ).fetchall()
                    )
                    occurrences.extend(
                        self._occurrence(row, request.source_id, revision.revision_id)
                        for row in connection.execute(
                            _OCCURRENCE_QUERY,
                            (
                                revision.revision_id,
                                request.window_start,
                                request.window_end,
                                request.envelope.query_valid_time,
                                request.envelope.query_valid_time,
                                limit,
                            ),
                        ).fetchall()
                    )
            total = len(revisions) + len(representations) + len(occurrences)
            if total > request.envelope.result_limit:
                outcome = NamedAuthorityOutcome.INCOMPLETE
                reason = "RESULT_BOUND_EXCEEDED"
                visible_count = 0
                no_match = False
            else:
                outcome = NamedAuthorityOutcome.COMPLETE
                reason = "NO_MATCH" if total == 0 else None
                visible_count = total
                no_match = total == 0
            receipt = SourceRevisionImpactAuthorityReceipt(
                request_digest=request.request_digest,
                adapter_contract_digest=NAMED_TOOL_AUTHORITY_ADAPTER_CONTRACT_DIGEST,
                adapter_config_digest=self.config.config_digest,
                authority_scope_id=self.config.authority_scope_id,
                authority_watermark=watermark,
                source_id=request.source_id,
                source_definition_digest=source_digest,
                revision_id=request.revision_id,
                window_start=request.window_start,
                window_end=request.window_end,
                lineage_depth=request.lineage_depth,
                include_superseded=request.include_superseded,
                revisions=revisions,
                representations=tuple(representations),
                occurrences=tuple(occurrences),
                outcome=outcome,
                reason=reason,
                result_count=visible_count,
                no_match=no_match,
                query_valid_time=request.envelope.query_valid_time,
                serving_time=request.envelope.serving_time,
            )
            raw = receipt.canonical_bytes
            return self._attributed(
                request=request,
                mode=self.authority_mode,
                schema_version="newsroom.increment5.source-revision-impact-authority-receipt.v1",
                authority_request_digest=authority_request_digest,
                raw=raw,
                outcome=outcome,
                reason=reason,
                result_count=visible_count,
                no_match=no_match,
                watermark=watermark,
                components=(
                    ("adapter_config", self.config.config_digest),
                    ("adapter_contract", NAMED_TOOL_AUTHORITY_ADAPTER_CONTRACT_DIGEST),
                    ("named_tool_contract", NAMED_TOOL_CONTRACT_DIGEST),
                    (
                        "occurrence_time_integrity_query",
                        OCCURRENCE_TIME_INTEGRITY_QUERY_DIGEST,
                    ),
                    ("occurrence_query", OCCURRENCE_QUERY_DIGEST),
                    (
                        "representation_time_integrity_query",
                        REPRESENTATION_TIME_INTEGRITY_QUERY_DIGEST,
                    ),
                    (
                        "revision_time_integrity_query",
                        REVISION_TIME_INTEGRITY_QUERY_DIGEST,
                    ),
                    ("representation_query", REPRESENTATION_QUERY_DIGEST),
                    ("revision_query", REVISION_QUERY_DIGEST),
                    ("source_query", SOURCE_QUERY_DIGEST),
                ),
            )
        except sqlite3.OperationalError as exc:
            reason = "QUERY_TIMEOUT" if "interrupted" in str(exc).lower() else "AUTHORITY_DATABASE_UNAVAILABLE"
            return self._receipt(
                request,
                authority_request_digest,
                watermark,
                NamedAuthorityOutcome.INCOMPLETE if reason == "QUERY_TIMEOUT" else NamedAuthorityOutcome.UNAVAILABLE,
                reason,
            )
        except (sqlite3.Error, AuthorityAdapterIntegrityError, ValueError):
            return self._receipt(
                request,
                authority_request_digest,
                watermark,
                NamedAuthorityOutcome.UNAVAILABLE,
                "AUTHORITY_INTEGRITY_ERROR",
            )
        finally:
            if connection is not None:
                self._close_snapshot(connection)

    def _receipt(
        self,
        request: SourceRevisionImpactLookupToolRequest,
        authority_request_digest: str,
        watermark: int,
        outcome: NamedAuthorityOutcome,
        reason: str,
    ) -> AttributedAuthorityResult:
        receipt = SourceRevisionImpactAuthorityReceipt(
            request_digest=request.request_digest,
            adapter_contract_digest=NAMED_TOOL_AUTHORITY_ADAPTER_CONTRACT_DIGEST,
            adapter_config_digest=self.config.config_digest,
            authority_scope_id=self.config.authority_scope_id,
            authority_watermark=watermark,
            source_id=request.source_id,
            source_definition_digest=None,
            revision_id=request.revision_id,
            window_start=request.window_start,
            window_end=request.window_end,
            lineage_depth=request.lineage_depth,
            include_superseded=request.include_superseded,
            revisions=(),
            representations=(),
            occurrences=(),
            outcome=outcome,
            reason=reason,
            result_count=0,
            no_match=False,
            query_valid_time=request.envelope.query_valid_time,
            serving_time=request.envelope.serving_time,
        )
        raw = receipt.canonical_bytes
        return self._attributed(
            request=request,
            mode=self.authority_mode,
            schema_version="newsroom.increment5.source-revision-impact-authority-receipt.v1",
            authority_request_digest=authority_request_digest,
            raw=raw,
            outcome=outcome,
            reason=reason,
            result_count=0,
            no_match=False,
            watermark=watermark,
            components=(
                ("adapter_config", self.config.config_digest),
                ("adapter_contract", NAMED_TOOL_AUTHORITY_ADAPTER_CONTRACT_DIGEST),
                ("named_tool_contract", NAMED_TOOL_CONTRACT_DIGEST),
                ("occurrence_query", OCCURRENCE_QUERY_DIGEST),
                ("representation_query", REPRESENTATION_QUERY_DIGEST),
                ("revision_query", REVISION_QUERY_DIGEST),
                ("source_query", SOURCE_QUERY_DIGEST),
            ),
        )

    @staticmethod
    def _revision(row: sqlite3.Row, source_id: str) -> RevisionImpactRecord:
        if row["definition_id"] != source_id:
            raise AuthorityAdapterIntegrityError("revision source binding mismatch")
        _parse_utc(row["observed_at"], field="revision_observed_at")
        _parse_utc(row["recorded_at"], field="revision_recorded_at")
        return RevisionImpactRecord(
            revision_id=_require_text(row["revision_id"], field="revision_id"),
            item_id=_require_text(row["item_id"], field="item_id"),
            prior_revision_id=row["prior_revision_id"],
            source_native_revision_token=row["source_native_revision_token"],
            permitted_state_digest=validate_sha256_digest(row["permitted_state_digest"], field="permitted_state_digest"),
            revision_identity_digest=validate_sha256_digest(row["revision_identity_digest"], field="revision_identity_digest"),
            item_identity_digest=validate_sha256_digest(row["item_identity_digest"], field="item_identity_digest"),
            observed_at=row["observed_at"],
            recorded_at=row["recorded_at"],
        )

    @staticmethod
    def _representation(
        row: sqlite3.Row, source_id: str, revision_id: str
    ) -> RepresentationImpactRecord:
        if row["definition_id"] != source_id or row["revision_id"] != revision_id:
            raise AuthorityAdapterIntegrityError("representation lineage mismatch")
        _parse_utc(row["produced_at"], field="representation_produced_at")
        _parse_utc(row["recorded_at"], field="representation_recorded_at")
        return RepresentationImpactRecord(
            representation_id=_require_text(row["representation_id"], field="representation_id"),
            revision_id=revision_id,
            adapter_version=_require_text(row["adapter_version"], field="adapter_version"),
            parser_version=_require_text(row["parser_version"], field="parser_version"),
            normalizer_version=_require_text(row["normalizer_version"], field="normalizer_version"),
            extraction_scope_version=_require_text(row["extraction_scope_version"], field="extraction_scope_version"),
            permitted_fields_digest=validate_sha256_digest(row["permitted_fields_digest"], field="permitted_fields_digest"),
            representation_digest=validate_sha256_digest(row["representation_digest"], field="representation_digest"),
            producer_slot_digest=validate_sha256_digest(row["producer_slot_digest"], field="producer_slot_digest"),
            representation_identity_digest=validate_sha256_digest(row["representation_identity_digest"], field="representation_identity_digest"),
            produced_at=row["produced_at"],
            recorded_at=row["recorded_at"],
            canonical_digest=validate_sha256_digest(row["canonical_digest"], field="representation_canonical_digest"),
        )

    @staticmethod
    def _occurrence(
        row: sqlite3.Row, source_id: str, revision_id: str
    ) -> OccurrenceImpactRecord:
        if row["definition_id"] != source_id or row["revision_id"] != revision_id:
            raise AuthorityAdapterIntegrityError("occurrence lineage mismatch")
        _parse_utc(row["observed_at"], field="occurrence_observed_at")
        _parse_utc(row["recorded_at"], field="occurrence_recorded_at")
        return OccurrenceImpactRecord(
            occurrence_id=_require_text(row["occurrence_id"], field="occurrence_id"),
            check_outcome_id=_require_text(row["check_outcome_id"], field="check_outcome_id"),
            revision_id=revision_id,
            representation_id=row["representation_id"],
            occurrence_kind=_require_text(row["occurrence_kind"], field="occurrence_kind"),
            observed_at=row["observed_at"],
            receipt_digest=validate_sha256_digest(row["receipt_digest"], field="occurrence_receipt_digest"),
            semantic_digest=validate_sha256_digest(row["semantic_digest"], field="occurrence_semantic_digest"),
            recorded_at=row["recorded_at"],
            canonical_digest=validate_sha256_digest(row["canonical_digest"], field="occurrence_canonical_digest"),
        )


__all__ = [
    "AUTHORITY_PROFILE_ID",
    "COLLISION_NAMESPACE",
    "NAMED_TOOL_AUTHORITY_ADAPTER_CONTRACT_DIGEST",
    "AuthorityObjectMetadata",
    "AuthorityPassageMetadata",
    "CollisionHydrationAuthorityReceipt",
    "CollisionHydrationNamedToolPort",
    "NamedAuthorityAdapterConfig",
    "OccurrenceImpactRecord",
    "RepresentationImpactRecord",
    "RevisionImpactRecord",
    "SourceRevisionImpactAuthorityReceipt",
    "SourceRevisionImpactNamedToolPort",
]
