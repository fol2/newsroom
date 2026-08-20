"""Corpus ingest units: one Graphiti episode per source item (GING-001)."""

from __future__ import annotations

from dataclasses import dataclass

from newsroom.control_plane.editorial import GroupedObservation
from newsroom.graphiti_adapter.identity import (
    MAX_EPISODE_BYTES,
    content_digest,
    ingest_key,
    observation_authority_ids,
)
from newsroom.graphiti_adapter.temporal import TemporalMapping, map_reference_time


def chunk_text(text: str, *, limit: int = MAX_EPISODE_BYTES) -> tuple[str, ...]:
    data = text.encode("utf-8")
    if not data:
        return ()
    chunks: list[str] = []
    offset = 0
    while offset < len(data):
        end = min(offset + limit, len(data))
        piece = data[offset:end]
        while piece:
            try:
                chunks.append(piece.decode("utf-8"))
                offset += len(piece)
                break
            except UnicodeDecodeError:
                piece = piece[:-1]
        else:
            raise ValueError("episode chunk is not valid UTF-8")
    return tuple(chunks)


@dataclass(frozen=True, slots=True)
class CorpusIngestUnit:
    source_id: str
    item_key: str
    headline: str
    body: str
    canonical_url: str
    observation_digest: str
    observed_at: str
    proving_run_id: str
    published_at: str | None = None
    updated_at: str | None = None
    chunk_ordinal: int = 1

    @property
    def full_text(self) -> str:
        parts = [self.headline.strip(), self.body.strip()]
        if self.canonical_url.strip():
            parts.append(self.canonical_url.strip())
        return "\n".join(part for part in parts if part)

    @property
    def episode_body(self) -> str:
        chunks = chunk_text(self.full_text)
        if not chunks:
            return ""
        return chunks[self.chunk_ordinal - 1]

    @property
    def digest(self) -> str:
        return content_digest(
            headline="",
            body=self.episode_body,
            canonical_url="",
        )

    @property
    def ingest_id(self) -> str:
        return ingest_key(
            source_id=self.source_id,
            item_key=self.item_key,
            content_digest_value=self.digest,
            observation_digest=self.observation_digest,
            published_at=self.published_at,
            updated_at=self.updated_at,
            observed_at=self.observed_at,
            chunk_ordinal=self.chunk_ordinal,
        )

    @property
    def revision_id(self) -> str:
        """Stable SourceRevision identity shared by all chunks of this revision."""

        return str(
            observation_authority_ids(
                proving_run_id=self.proving_run_id,
                source_id=self.source_id,
                item_key=self.item_key,
                observation_digest=self.observation_digest,
                published_at=self.published_at,
                updated_at=self.updated_at,
            )[4]
        )

    def temporal(self) -> TemporalMapping:
        return map_reference_time(
            published_at=self.published_at,
            updated_at=self.updated_at,
            observed_at=self.observed_at,
        )


def units_from(
    observations: tuple[GroupedObservation, ...],
    *,
    proving_run_id: str,
) -> tuple[CorpusIngestUnit, ...]:
    units: list[CorpusIngestUnit] = []
    for row in observations:
        base = CorpusIngestUnit(
            source_id=row.source_id,
            item_key=row.item.item_key,
            headline=row.item.headline,
            body=row.item.body,
            canonical_url=row.item.canonical_url,
            observation_digest=row.observation_digest,
            observed_at=row.observed_at,
            proving_run_id=proving_run_id,
            published_at=row.item.published_at,
            updated_at=row.item.updated_at,
        )
        chunks = chunk_text(base.full_text)
        for ordinal in range(1, len(chunks) + 1):
            units.append(
                CorpusIngestUnit(
                    source_id=base.source_id,
                    item_key=base.item_key,
                    headline=base.headline,
                    body=base.body,
                    canonical_url=base.canonical_url,
                    observation_digest=base.observation_digest,
                    observed_at=base.observed_at,
                    proving_run_id=base.proving_run_id,
                    published_at=base.published_at,
                    updated_at=base.updated_at,
                    chunk_ordinal=ordinal,
                )
            )
    return tuple(sorted(units, key=lambda item: item.ingest_id))


@dataclass(frozen=True, slots=True)
class EligibleCorpusRevision:
    """Coverage denominator entry; chunks remain implementation-level work."""

    revision_id: str
    source_id: str
    item_key: str
    observed_at: str
    source_time: str
    ingest_ids: tuple[str, ...]


def revisions_from(
    units: tuple[CorpusIngestUnit, ...],
) -> tuple[EligibleCorpusRevision, ...]:
    grouped: dict[str, list[CorpusIngestUnit]] = {}
    for unit in units:
        grouped.setdefault(unit.revision_id, []).append(unit)
    revisions = []
    for revision_id, chunks in grouped.items():
        ordered = sorted(chunks, key=lambda item: item.chunk_ordinal)
        first = ordered[0]
        revisions.append(
            EligibleCorpusRevision(
                revision_id=revision_id,
                source_id=first.source_id,
                item_key=first.item_key,
                observed_at=first.observed_at,
                source_time=first.temporal().reference_time.to_text(),
                ingest_ids=tuple(item.ingest_id for item in ordered),
            )
        )
    return tuple(
        sorted(revisions, key=lambda item: (item.observed_at, item.revision_id))
    )
