"""Stable first-observation identity for retained source revisions."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EffectiveRevisionIdentity:
    source_id: str
    item_key: str
    revision_digest: str
    first_observed_at: str

    def observed_fallback_at(
        self, *, published_at: str | None, updated_at: str | None
    ) -> str | None:
        return (
            self.first_observed_at
            if published_at is None and updated_at is None
            else None
        )


class EffectiveRevisionIdentityResolver:
    """Read the fixed first observation for one content revision."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def resolve(
        self, *, source_id: str, item_key: str, revision_digest: str
    ) -> EffectiveRevisionIdentity:
        row = self._connection.execute(
            """
            SELECT first_seen_at
            FROM proving_revision_first_seen
            WHERE source_id=? AND item_key=? AND revision_digest=?
            """,
            (source_id, item_key, revision_digest),
        ).fetchone()
        
        if row is None:
            raise ValueError(
                f"effective revision {source_id}:{item_key}:{revision_digest} "
                "has no retained first observation"
            )
        
        return EffectiveRevisionIdentity(
            source_id=source_id,
            item_key=item_key,
            revision_digest=revision_digest,
            first_observed_at=str(row[0]),
        )


def create_effective_revision_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS proving_revision_first_seen(
            source_id TEXT NOT NULL,
            item_key TEXT NOT NULL,
            revision_digest TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            PRIMARY KEY(source_id, item_key, revision_digest)
        ) WITHOUT ROWID
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS proving_backfill_watermark(
            processed_until TEXT PRIMARY KEY
        )
        """
    )


def backfill_missing_first_seen(connection: sqlite3.Connection) -> int:
    """Populate missing first-seen entries from earliest observations.
    
    Returns the count of rows written.
    Uses a watermark to track processed observations; cheap no-op if no new observations.
    Parses only observations newer than the watermark.
    Filters to usable observations (status_code=200, body present, no error).
    """
    from newsroom.control_plane.items import parse_observation
    from newsroom.graphiti_adapter.identity import content_digest

    # Get the watermark: highest observation time fully processed
    watermark_row = connection.execute(
        "SELECT processed_until FROM proving_backfill_watermark"
    ).fetchone()
    watermark = watermark_row[0] if watermark_row else None

    # Check if there are usable observations newer than the watermark
    result = connection.execute(
        """
        SELECT MAX(fetched_at) FROM proving_observations
        WHERE status_code=200 AND body IS NOT NULL AND error IS NULL
        """
    ).fetchone()
    latest_observation_time = result[0] if result[0] else None
    
    if latest_observation_time is None:
        return 0  # No usable observations to backfill
    
    if watermark is not None and latest_observation_time <= watermark:
        return 0  # All usable observations already processed

    # Get observations to process: those newer than watermark or all if no watermark
    if watermark is None:
        query = """
            SELECT source_id, fetched_at, url, body
            FROM proving_observations
            WHERE status_code=200 AND body IS NOT NULL AND error IS NULL
            ORDER BY fetched_at ASC
        """
        params = ()
    else:
        query = """
            SELECT source_id, fetched_at, url, body
            FROM proving_observations
            WHERE status_code=200 AND body IS NOT NULL AND error IS NULL
            AND fetched_at > ?
            ORDER BY fetched_at ASC
        """
        params = (watermark,)
    
    observations = connection.execute(query, params).fetchall()

    # Parse observations and build a map of revisions to their earliest observation time
    revisions_seen: dict[tuple[str, str, str], str] = {}
    
    for source_id, fetched_at, url, body in observations:
        for item in parse_observation(source_id=source_id, url=url, body=body):
            key = (
                source_id,
                item.item_key,
                content_digest(
                    headline=item.headline,
                    body=item.retained_corpus_body,
                    canonical_url=item.canonical_url,
                ),
            )
            if key not in revisions_seen:
                revisions_seen[key] = fetched_at

    # Query which revisions already have first-seen rows
    existing = connection.execute(
        "SELECT DISTINCT source_id, item_key, revision_digest FROM proving_revision_first_seen"
    ).fetchall()
    existing_keys = {(row[0], row[1], row[2]) for row in existing}

    # Determine what needs to be written
    to_write = {k: v for k, v in revisions_seen.items() if k not in existing_keys}
    
    if not to_write:
        # Even if nothing new to write, advance watermark to avoid re-parsing
        # Skip watermark update if lock is unavailable; it will be set on next real work
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute("DELETE FROM proving_backfill_watermark")
                connection.execute(
                    "INSERT INTO proving_backfill_watermark(processed_until) VALUES(?)",
                    (latest_observation_time,),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        except sqlite3.OperationalError:
            # Database locked; skip watermark update, will retry on next call
            pass
        return 0

    # Write missing rows under a lock
    connection.execute("BEGIN IMMEDIATE")
    try:
        for (source_id, item_key, revision_digest), observed_at in to_write.items():
            connection.execute(
                """
                INSERT OR IGNORE INTO proving_revision_first_seen(
                    source_id, item_key, revision_digest, first_seen_at
                ) VALUES(?,?,?,?)
                """,
                (source_id, item_key, revision_digest, observed_at),
            )
        # Update watermark only after successful inserts
        connection.execute("DELETE FROM proving_backfill_watermark")
        connection.execute(
            "INSERT INTO proving_backfill_watermark(processed_until) VALUES(?)",
            (latest_observation_time,),
        )
        connection.commit()
        return len(to_write)
    except Exception:
        connection.rollback()
        raise


def retain_effective_revision_first_seen(
    connection: sqlite3.Connection,
    *,
    source_id: str,
    item_key: str,
    revision_digest: str,
    observed_at: str,
) -> EffectiveRevisionIdentity:
    """Fix first-seen state in the same transaction as its observation."""

    connection.execute(
        """
        INSERT OR IGNORE INTO proving_revision_first_seen(
            source_id, item_key, revision_digest, first_seen_at
        ) VALUES(?,?,?,?)
        """,
        (source_id, item_key, revision_digest, observed_at),
    )
    return EffectiveRevisionIdentityResolver(connection).resolve(
        source_id=source_id,
        item_key=item_key,
        revision_digest=revision_digest,
    )


def retain_observation_revision_first_seen(
    connection: sqlite3.Connection,
    *,
    source_id: str,
    url: str,
    body: bytes,
    observed_at: str,
) -> None:
    """Retain item revision facts while retaining their source observation."""

    from newsroom.control_plane.items import parse_observation
    from newsroom.graphiti_adapter.identity import content_digest

    for item in parse_observation(source_id=source_id, url=url, body=body):
        retain_effective_revision_first_seen(
            connection,
            source_id=source_id,
            item_key=item.item_key,
            revision_digest=content_digest(
                headline=item.headline,
                body=item.retained_corpus_body,
                canonical_url=item.canonical_url,
            ),
            observed_at=observed_at,
        )
