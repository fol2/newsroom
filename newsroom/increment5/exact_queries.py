"""Fixed SQLite statements and read-only controls for the 5B exact branch."""

from __future__ import annotations

import sqlite3

from .branch_contracts import ExactLookupKind


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
        getattr(sqlite3, "SQLITE_TRANSACTION", None),
    )
    if action is not None
)

_SOURCE_TABLES = frozenset(
    {
        "ledger_events",
        "source_definition_versions",
        "source_definition_version_heads",
    }
)
_REQUIRED_TABLES: dict[ExactLookupKind, frozenset[str]] = {
    ExactLookupKind.SOURCE_NATIVE_ID: _SOURCE_TABLES | {"source_items"},
    ExactLookupKind.SOURCE_REVISION_ID: _SOURCE_TABLES | {"source_revisions"},
    ExactLookupKind.SOURCE_NATIVE_REVISION_TOKEN: _SOURCE_TABLES | {"source_revisions"},
    ExactLookupKind.REPRESENTATION_ID: _SOURCE_TABLES | {"discovery_representations"},
    ExactLookupKind.CANONICAL_ENTITY_ID: frozenset(
        {"ledger_events", "canonical_entities", "canonical_entity_heads"}
    ),
    ExactLookupKind.AUTHORITY_ALIAS: frozenset(
        {"ledger_events", "entity_aliases", "canonical_entity_heads"}
    ),
    ExactLookupKind.FORMAL_PROCESS_ID: frozenset(
        {
            "ledger_events",
            "development_candidates_v2",
            "development_candidate_versions_v2",
        }
    ),
}


_SOURCE_NATIVE_QUERY = """
SELECT 'SOURCE_ITEM' AS authority_kind,
       i.item_id AS authority_id,
       i.item_id AS dependency_root_id,
       'SOURCE_NATIVE_ID_EQUAL' AS match_signal,
       i.definition_id || ':' || i.definition_version_id AS source_identity,
       'OBSERVED' AS trust_scope,
       i.identity_digest AS provenance_digest,
       v.allowed_use AS allowed_use,
       v.lifecycle_stage AS lifecycle_state,
       CASE
         WHEN h.current_version_id IS NOT NULL AND v.version_id IS NOT NULL
         THEN 1 ELSE 0
       END AS source_policy_available,
       CASE WHEN i.definition_version_id=h.current_version_id THEN 1 ELSE 0 END
         AS source_version_current,
       NULL AS valid_from,
       NULL AS valid_until
FROM source_items AS i
LEFT JOIN source_definition_version_heads AS h
  ON h.definition_id=i.definition_id
LEFT JOIN source_definition_versions AS v
  ON v.version_id=h.current_version_id
 AND v.definition_id=h.definition_id
WHERE i.definition_id=? AND i.source_native_id=?
ORDER BY i.item_id
LIMIT ?
"""

_SOURCE_REVISION_ID_QUERY = """
SELECT 'SOURCE_REVISION' AS authority_kind,
       r.revision_id AS authority_id,
       r.item_id AS dependency_root_id,
       'REVISION_ID_EQUAL' AS match_signal,
       r.definition_id || ':' || r.definition_version_id AS source_identity,
       'OBSERVED' AS trust_scope,
       r.revision_identity_digest AS provenance_digest,
       v.allowed_use AS allowed_use,
       v.lifecycle_stage AS lifecycle_state,
       CASE
         WHEN h.current_version_id IS NOT NULL AND v.version_id IS NOT NULL
         THEN 1 ELSE 0
       END AS source_policy_available,
       CASE WHEN r.definition_version_id=h.current_version_id THEN 1 ELSE 0 END
         AS source_version_current,
       NULL AS valid_from,
       NULL AS valid_until
FROM source_revisions AS r
LEFT JOIN source_definition_version_heads AS h
  ON h.definition_id=r.definition_id
LEFT JOIN source_definition_versions AS v
  ON v.version_id=h.current_version_id
 AND v.definition_id=h.definition_id
WHERE r.revision_id=?
ORDER BY r.revision_id
LIMIT ?
"""

_SOURCE_NATIVE_REVISION_QUERY = """
SELECT 'SOURCE_REVISION' AS authority_kind,
       r.revision_id AS authority_id,
       r.item_id AS dependency_root_id,
       'SOURCE_NATIVE_REVISION_TOKEN_EQUAL' AS match_signal,
       r.definition_id || ':' || r.definition_version_id AS source_identity,
       'OBSERVED' AS trust_scope,
       r.revision_identity_digest AS provenance_digest,
       v.allowed_use AS allowed_use,
       v.lifecycle_stage AS lifecycle_state,
       CASE
         WHEN h.current_version_id IS NOT NULL AND v.version_id IS NOT NULL
         THEN 1 ELSE 0
       END AS source_policy_available,
       CASE WHEN r.definition_version_id=h.current_version_id THEN 1 ELSE 0 END
         AS source_version_current,
       NULL AS valid_from,
       NULL AS valid_until
FROM source_revisions AS r
LEFT JOIN source_definition_version_heads AS h
  ON h.definition_id=r.definition_id
LEFT JOIN source_definition_versions AS v
  ON v.version_id=h.current_version_id
 AND v.definition_id=h.definition_id
WHERE r.item_id=? AND r.source_native_revision_token=?
ORDER BY r.revision_id
LIMIT ?
"""

_REPRESENTATION_QUERY = """
SELECT 'DISCOVERY_REPRESENTATION' AS authority_kind,
       d.representation_id AS authority_id,
       d.revision_id AS dependency_root_id,
       'REPRESENTATION_ID_EQUAL' AS match_signal,
       d.definition_id || ':' || d.definition_version_id AS source_identity,
       'OBSERVED' AS trust_scope,
       d.representation_identity_digest AS provenance_digest,
       v.allowed_use AS allowed_use,
       v.lifecycle_stage AS lifecycle_state,
       CASE
         WHEN h.current_version_id IS NOT NULL AND v.version_id IS NOT NULL
         THEN 1 ELSE 0
       END AS source_policy_available,
       CASE WHEN d.definition_version_id=h.current_version_id THEN 1 ELSE 0 END
         AS source_version_current,
       NULL AS valid_from,
       NULL AS valid_until
FROM discovery_representations AS d
LEFT JOIN source_definition_version_heads AS h
  ON h.definition_id=d.definition_id
LEFT JOIN source_definition_versions AS v
  ON v.version_id=h.current_version_id
 AND v.definition_id=h.definition_id
WHERE d.representation_id=?
ORDER BY d.representation_id
LIMIT ?
"""

_ENTITY_QUERY = """
SELECT 'CANONICAL_ENTITY' AS authority_kind,
       e.entity_id AS authority_id,
       e.entity_id AS dependency_root_id,
       'CANONICAL_ENTITY_ID_EQUAL' AS match_signal,
       e.authority_event_id AS source_identity,
       'ADMITTED' AS trust_scope,
       e.canonical_digest AS provenance_digest,
       'PERMITTED' AS allowed_use,
       h.lifecycle AS lifecycle_state,
       NULL AS valid_from,
       NULL AS valid_until
FROM canonical_entities AS e
JOIN canonical_entity_heads AS h ON h.entity_id=e.entity_id
WHERE e.entity_id=?
ORDER BY e.entity_id
LIMIT ?
"""

_ALIAS_QUERY = """
SELECT 'ENTITY_ALIAS' AS authority_kind,
       a.alias_id AS authority_id,
       a.entity_id AS dependency_root_id,
       CASE WHEN a.normalized_text=? THEN 'AUTHORITY_NORMALIZED_ALIAS_EQUAL'
            ELSE 'AUTHORITY_SURFACE_ALIAS_EQUAL' END AS match_signal,
       a.resolution_decision_id AS source_identity,
       'ADMITTED' AS trust_scope,
       a.canonical_digest AS provenance_digest,
       'PERMITTED' AS allowed_use,
       h.lifecycle AS lifecycle_state,
       a.valid_from AS valid_from,
       a.valid_until AS valid_until
FROM entity_aliases AS a
JOIN canonical_entity_heads AS h ON h.entity_id=a.entity_id
WHERE a.normalized_text=? OR a.alias_text=?
ORDER BY CASE WHEN a.normalized_text=? THEN 0 ELSE 1 END, a.alias_id
LIMIT ?
"""

_FORMAL_PROCESS_QUERY = """
SELECT 'STORY_CANDIDATE_VERSION' AS authority_kind,
       v.candidate_version_id AS authority_id,
       v.canonical_process_id AS dependency_root_id,
       'FORMAL_PROCESS_ID_EQUAL' AS match_signal,
       v.candidate_id AS source_identity,
       'ADMITTED' AS trust_scope,
       v.canonical_digest AS provenance_digest,
       'PERMITTED' AS allowed_use,
       'ACTIVE' AS lifecycle_state,
       NULL AS valid_from,
       NULL AS valid_until
FROM development_candidate_versions_v2 AS v
JOIN development_candidates_v2 AS c ON c.candidate_id=v.candidate_id
WHERE v.canonical_process_id=?
ORDER BY v.candidate_version_id
LIMIT ?
"""


__all__ = [
    "_ALIAS_QUERY",
    "_ENTITY_QUERY",
    "_FORMAL_PROCESS_QUERY",
    "_REPRESENTATION_QUERY",
    "_REQUIRED_TABLES",
    "_SOURCE_NATIVE_QUERY",
    "_SOURCE_NATIVE_REVISION_QUERY",
    "_SOURCE_REVISION_ID_QUERY",
    "_WRITE_ACTIONS",
]
