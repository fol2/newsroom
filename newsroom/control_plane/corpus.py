"""Corpus ingest units: one Graphiti episode per source item (GING-001)."""

from __future__ import annotations

from dataclasses import dataclass

from newsroom.control_plane.editorial import GroupedObservation
from newsroom.graphiti_adapter.identity import content_digest, ingest_key
from newsroom.graphiti_adapter.temporal import TemporalMapping, map_reference_time


@dataclass(frozen=True, slots=True)
class CorpusIngestUnit:
    source_id: str
    item_key: str
    headline: str
    body: str
    canonical_url: str
    observation_digest: str
    observed_at: str
    published_at: str | None = None
    updated_at: str | None = None
    chunk_ordinal: int = 1

    @property
    def episode_body(self) -> str:
        parts = [self.headline.strip(), self.body.strip()]
        if self.canonical_url.strip():
            parts.append(self.canonical_url.strip())
        return "\n".join(part for part in parts if part)

    @property
    def digest(self) -> str:
        return content_digest(
            headline=self.headline,
            body=self.body,
            canonical_url=self.canonical_url,
        )

    @property
    def ingest_id(self) -> str:
        return ingest_key(
            source_id=self.source_id,
            item_key=self.item_key,
            content_digest_value=self.digest,
            chunk_ordinal=self.chunk_ordinal,
        )

    def temporal(self) -> TemporalMapping:
        return map_reference_time(
            published_at=self.published_at,
            updated_at=self.updated_at,
            observed_at=self.observed_at,
        )


def units_from(observations: tuple[GroupedObservation, ...]) -> tuple[CorpusIngestUnit, ...]:
    units = [
        CorpusIngestUnit(
            source_id=row.source_id,
            item_key=row.item.item_key,
            headline=row.item.headline,
            body=row.item.body,
            canonical_url=row.item.canonical_url,
            observation_digest=row.observation_digest,
            observed_at=row.observed_at,
            published_at=row.item.published_at,
            updated_at=row.item.updated_at,
        )
        for row in observations
    ]
    return tuple(sorted(units, key=lambda item: item.ingest_id))
