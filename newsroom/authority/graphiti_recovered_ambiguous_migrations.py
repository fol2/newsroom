"""Append-only v39 Graphiti recovered-ambiguous progression guards."""

from __future__ import annotations

from dataclasses import dataclass

from .canonical import digest_canonical

GRAPHITI_RECOVERED_AMBIGUOUS_SCHEMA_VERSION = 39
GRAPHITI_RECOVERED_AMBIGUOUS_MIGRATION_NAME = (
    "graphiti_recovered_ambiguous_progression_v39"
)


@dataclass(frozen=True, slots=True)
class GraphitiRecoveredAmbiguousMigrationRecord:
    version: int
    name: str
    checksum: str


_RECOVERY_EVENT_MATCH = """
    SELECT 1
    FROM graphiti_adapter_attempts AS p
    JOIN ledger_events AS e ON e.event_id=NEW.authority_event_id
    JOIN authority_payloads AS a ON a.payload_id=e.payload_id
    WHERE p.attempt_id=NEW.previous_attempt_id
      AND p.run_id=NEW.run_id
      AND p.attempt_number=NEW.attempt_number-2
      AND p.outcome='AMBIGUOUS_EFFECT'
      AND json_type(CAST(NEW.canonical_bytes AS TEXT),
          '$.recovered_ambiguous_progression')='object'
      AND json_extract(CAST(NEW.canonical_bytes AS TEXT),
          '$.recovered_ambiguous_progression')=json_extract(
              CAST(a.payload_bytes AS TEXT),
              '$.recovered_ambiguous_progression')
      AND json_extract(CAST(a.payload_bytes AS TEXT),
          '$.recovered_ambiguous_progression.authoritative_attempt_id')=p.attempt_id
      AND json_extract(CAST(a.payload_bytes AS TEXT),
          '$.recovered_ambiguous_progression.authoritative_attempt_digest')=p.canonical_digest
      AND json_extract(CAST(a.payload_bytes AS TEXT),
          '$.recovered_ambiguous_progression.authoritative_attempt_number')=p.attempt_number
      AND json_extract(CAST(a.payload_bytes AS TEXT),
          '$.recovered_ambiguous_progression.authoritative_run_version_id')=p.run_version_id
      AND json_extract(CAST(a.payload_bytes AS TEXT),
          '$.recovered_ambiguous_progression.authoritative_recorded_at')=p.recorded_at
      AND json_extract(CAST(a.payload_bytes AS TEXT),
          '$.recovered_ambiguous_progression.skipped_attempt_number')=NEW.attempt_number-1
      AND json_extract(CAST(a.payload_bytes AS TEXT),
          '$.recovered_ambiguous_progression.marker_attempt_number')=p.attempt_number
      AND json_extract(CAST(a.payload_bytes AS TEXT),
          '$.recovered_ambiguous_progression.marker_workspace_id')=p.workspace_id
      AND p.recorded_at<=json_extract(CAST(a.payload_bytes AS TEXT),
          '$.recovered_ambiguous_progression.skipped_recorded_at')
"""

GRAPHITI_RECOVERED_AMBIGUOUS_MIGRATION_STATEMENTS: tuple[str, ...] = (
    "DROP TRIGGER graphiti_attempt_chain_guard",
    f"""CREATE TRIGGER graphiti_attempt_chain_guard
        BEFORE INSERT ON graphiti_adapter_attempts
        WHEN (NEW.attempt_number=1 AND NEW.previous_attempt_id IS NOT NULL)
          OR (NEW.attempt_number>1 AND NOT EXISTS(
              SELECT 1 FROM graphiti_adapter_attempts
              WHERE attempt_id=NEW.previous_attempt_id
                AND run_id=NEW.run_id
                AND attempt_number=NEW.attempt_number-1
          ) AND NOT EXISTS({_RECOVERY_EVENT_MATCH}))
        BEGIN SELECT RAISE(ABORT,'invalid graphiti attempt chain'); END""",
    "DROP TRIGGER graphiti_attempt_head_update_guard",
    f"""CREATE TRIGGER graphiti_attempt_head_update_guard
        BEFORE UPDATE ON graphiti_adapter_attempt_heads
        WHEN NEW.run_id!=OLD.run_id OR NOT (
            (OLD.terminal=0
             AND NEW.current_attempt_number=OLD.current_attempt_number+1)
            OR
            (OLD.terminal=1
             AND NEW.current_attempt_number=OLD.current_attempt_number+2
             AND EXISTS(
                 SELECT 1
                 FROM graphiti_adapter_attempts AS c
                 JOIN graphiti_adapter_attempts AS p
                   ON p.attempt_id=OLD.current_attempt_id
                 JOIN ledger_events AS e ON e.event_id=c.authority_event_id
                 JOIN authority_payloads AS a ON a.payload_id=e.payload_id
                 WHERE c.attempt_id=NEW.current_attempt_id
                   AND c.run_id=OLD.run_id
                   AND c.attempt_number=NEW.current_attempt_number
                   AND c.previous_attempt_id=OLD.current_attempt_id
                   AND p.run_id=OLD.run_id
                   AND p.attempt_number=OLD.current_attempt_number
                   AND p.outcome='AMBIGUOUS_EFFECT'
                   AND json_type(CAST(c.canonical_bytes AS TEXT),
                       '$.recovered_ambiguous_progression')='object'
                   AND json_extract(CAST(c.canonical_bytes AS TEXT),
                       '$.recovered_ambiguous_progression')=json_extract(
                           CAST(a.payload_bytes AS TEXT),
                           '$.recovered_ambiguous_progression')
                   AND json_extract(CAST(a.payload_bytes AS TEXT),
                       '$.recovered_ambiguous_progression.authoritative_attempt_id')=p.attempt_id
                   AND json_extract(CAST(a.payload_bytes AS TEXT),
                       '$.recovered_ambiguous_progression.authoritative_attempt_digest')=p.canonical_digest
                   AND json_extract(CAST(a.payload_bytes AS TEXT),
                       '$.recovered_ambiguous_progression.authoritative_attempt_number')=p.attempt_number
                   AND json_extract(CAST(a.payload_bytes AS TEXT),
                       '$.recovered_ambiguous_progression.skipped_attempt_number')=c.attempt_number-1
                   AND json_extract(CAST(a.payload_bytes AS TEXT),
                       '$.recovered_ambiguous_progression.marker_workspace_id')=p.workspace_id
             ))
        )
        BEGIN SELECT RAISE(ABORT,'invalid graphiti attempt head advance'); END""",
)

GRAPHITI_RECOVERED_AMBIGUOUS_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": GRAPHITI_RECOVERED_AMBIGUOUS_SCHEMA_VERSION,
        "name": GRAPHITI_RECOVERED_AMBIGUOUS_MIGRATION_NAME,
        "statements": list(GRAPHITI_RECOVERED_AMBIGUOUS_MIGRATION_STATEMENTS),
    }
)
GRAPHITI_RECOVERED_AMBIGUOUS_MIGRATION = (
    GraphitiRecoveredAmbiguousMigrationRecord(
        GRAPHITI_RECOVERED_AMBIGUOUS_SCHEMA_VERSION,
        GRAPHITI_RECOVERED_AMBIGUOUS_MIGRATION_NAME,
        GRAPHITI_RECOVERED_AMBIGUOUS_MIGRATION_CHECKSUM,
    )
)


__all__ = [
    name
    for name in globals()
    if name.startswith(
        ("GRAPHITI_RECOVERED_AMBIGUOUS_", "GraphitiRecoveredAmbiguous")
    )
]
