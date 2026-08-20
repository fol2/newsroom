"""Corpus ingest units: one Graphiti episode per source item (GING-001)."""

from __future__ import annotations

from dataclasses import dataclass

from newsroom.authority.canonical import digest_canonical
from newsroom.control_plane.editorial import GroupedObservation
from newsroom.graphiti_adapter.identity import (
    MAX_EPISODE_BYTES,
    content_digest,
    ingest_key,
    observation_authority_ids,
    source_definition_version_id,
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
class CorpusAuthorityBinding:
    """Retained source and current-rights records bound into an ingest manifest."""

    admission_id: str
    access_decision_id: str
    definition_id: str
    definition_version_id: str
    item_id: str
    revision_id: str
    representation_id: str
    records: tuple[dict[str, object], ...]


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
    chunk_count: int = 1
    predecessor_ingest_id: str | None = None
    attempt_number: int = 1
    authority: CorpusAuthorityBinding | None = None
    source_definition_url: str = ""

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
    def revision_digest(self) -> str:
        return content_digest(
            headline=self.headline,
            body=self.body,
            canonical_url=self.canonical_url,
        )

    @property
    def representation_digest(self) -> str:
        return digest_canonical(
            {
                "source_id": self.source_id,
                "item_key": self.item_key,
                "revision_digest": self.revision_digest,
                "published_at": self.published_at,
                "updated_at": self.updated_at,
            }
        )

    @property
    def ingest_id(self) -> str:
        return ingest_key(
            source_id=self.source_id,
            item_key=self.item_key,
            content_digest_value=self.digest,
            revision_id=self.revision_id,
            representation_digest=self.representation_digest,
            published_at=self.published_at,
            updated_at=self.updated_at,
            observed_at=self.observed_at,
            chunk_ordinal=self.chunk_ordinal,
        )

    @property
    def revision_id(self) -> str:
        """Stable SourceRevision identity shared by all chunks of this revision."""

        if self.authority is not None:
            return self.authority.revision_id
        return str(
            observation_authority_ids(
                source_id=self.source_id,
                item_key=self.item_key,
                revision_digest=self.revision_digest,
                representation_digest=self.representation_digest,
                rights_authority_run_id=self.proving_run_id,
                rights_gate_id=f"RIGHTS_{self.source_id}",
                rights_gate_reason="evaluation fixture",
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
    rights_authority_run_id: str | None = None,
    rights_gate_id: str | None = None,
    rights_gate_reason: str = "retained PASS",
    source_definition_url: str | None = None,
) -> tuple[CorpusIngestUnit, ...]:
    units: list[CorpusIngestUnit] = []
    for row in observations:
        base = CorpusIngestUnit(
            source_id=row.source_id,
            item_key=row.item.item_key,
            headline=row.item.headline,
            body=row.item.retained_corpus_body,
            canonical_url=row.item.canonical_url,
            observation_digest=row.observation_digest,
            observed_at=row.observed_at,
            proving_run_id=proving_run_id,
            published_at=row.item.published_at,
            updated_at=row.item.updated_at,
            source_definition_url=source_definition_url or row.item.canonical_url,
        )
        chunks = chunk_text(base.full_text)
        revision_digest = base.revision_digest
        representation_digest = base.representation_digest
        authority_run_id = rights_authority_run_id or proving_run_id
        gate_id = rights_gate_id or f"RIGHTS_{base.source_id}"
        (
            admission_id,
            access_id,
            definition_id,
            item_id,
            revision_id,
            representation_id,
        ) = observation_authority_ids(
            source_id=base.source_id,
            item_key=base.item_key,
            revision_digest=revision_digest,
            representation_digest=representation_digest,
            rights_authority_run_id=authority_run_id,
            rights_gate_id=gate_id,
            rights_gate_reason=rights_gate_reason,
            published_at=base.published_at,
            updated_at=base.updated_at,
        )
        definition_version_id = source_definition_version_id(
            source_id=base.source_id,
            source_url=base.source_definition_url,
        )
        records: tuple[dict[str, object], ...] = (
            {
                "record_type": "SOURCE_DEFINITION",
                "record_id": str(definition_id),
                "source_id": base.source_id,
            },
            {
                "record_type": "SOURCE_DEFINITION_VERSION",
                "record_id": str(definition_version_id),
                "definition_id": str(definition_id),
                "source_id": base.source_id,
                "source_url": base.source_definition_url,
            },
            {
                "record_type": "SOURCE_ITEM",
                "record_id": str(item_id),
                "definition_id": str(definition_id),
                "source_id": base.source_id,
                "item_key": base.item_key,
            },
            {
                "record_type": "SOURCE_REVISION",
                "record_id": str(revision_id),
                "item_id": str(item_id),
                "source_id": base.source_id,
                "item_key": base.item_key,
                "revision_digest": revision_digest,
                "published_at": base.published_at,
                "updated_at": base.updated_at,
            },
            {
                "record_type": "DISCOVERY_REPRESENTATION",
                "record_id": str(representation_id),
                "source_id": base.source_id,
                "item_key": base.item_key,
                "revision_id": str(revision_id),
                "representation_digest": representation_digest,
            },
            {
                "record_type": "OBJECT_ADMISSION",
                "record_id": str(admission_id),
                "revision_id": str(revision_id),
                "decision": "ADMIT",
                "scope": "EVALUATION_CORPUS_INGEST",
            },
            {
                "record_type": "OBJECT_ACCESS_DECISION",
                "record_id": str(access_id),
                "revision_id": str(revision_id),
                "decision": "ALLOW",
                "principal_id": "newsroom.control-plane",
                "purpose": "graphiti.corpus-ingest",
                "rights_authority_run_id": authority_run_id,
                "rights_gate_id": gate_id,
                "rights_gate_status": "PASS",
                "rights_gate_reason": rights_gate_reason,
            },
        )
        authority = CorpusAuthorityBinding(
            admission_id=str(admission_id),
            access_decision_id=str(access_id),
            definition_id=str(definition_id),
            definition_version_id=str(definition_version_id),
            item_id=str(item_id),
            revision_id=str(revision_id),
            representation_id=str(representation_id),
            records=records,
        )
        predecessor: str | None = None
        for ordinal in range(1, len(chunks) + 1):
            unit = CorpusIngestUnit(
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
                chunk_count=len(chunks),
                predecessor_ingest_id=predecessor,
                authority=authority,
                source_definition_url=base.source_definition_url,
            )
            units.append(unit)
            predecessor = unit.ingest_id
    return tuple(
        sorted(
            units,
            key=lambda item: (
                item.observed_at,
                item.revision_id,
                item.chunk_ordinal,
            ),
        )
    )


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
