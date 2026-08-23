"""Corpus ingest units: one Graphiti episode per source item (GING-001)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

from newsroom.control_plane.editorial import GroupedObservation
from newsroom.effective_revision import (
    EffectiveRevisionIdentity,
    EffectiveRevisionIdentityResolver,
)
from newsroom.graphiti_adapter.identity import (
    MAX_EPISODE_BYTES,
    content_digest,
    ingest_key,
    observation_authority_ids,
    representation_digest_for,
    source_definition_version_id,
    source_revision_id,
)
from newsroom.graphiti_adapter.temporal import TemporalMapping, map_reference_time


class EffectiveRevisionCoverageKey(NamedTuple):
    source_id: str
    item_key: str
    revision_digest: str
    published_at: str
    updated_at: str


class RemappedIngestEffect(NamedTuple):
    source_id: str
    item_key: str
    revision_digest: str
    published_at: str
    updated_at: str
    old_ingest_id: str
    new_ingest_id: str


class EffectivePullFirstSeen(NamedTuple):
    source_id: str
    item_key: str
    revision_digest: str
    published_at: str
    updated_at: str
    first_observed_at: str


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


def effective_pull_ingest_ids(
    *,
    source_id: str,
    item_key: str,
    headline: str,
    body: str,
    canonical_url: str,
    published_at: str | None,
    updated_at: str | None,
) -> tuple[str, ...]:
    """Return the canonical chunk identities for one effective pull."""

    revision_digest = content_digest(
        headline=headline, body=body, canonical_url=canonical_url
    )
    representation_digest = representation_digest_for(
        source_id=source_id,
        item_key=item_key,
        revision_digest=revision_digest,
        published_at=published_at,
        updated_at=updated_at,
    )
    revision_id = source_revision_id(
        source_id=source_id,
        item_key=item_key,
        revision_digest=revision_digest,
        published_at=published_at,
        updated_at=updated_at,
    )
    full_text = "\n".join(
        part for part in (headline.strip(), body.strip(), canonical_url.strip()) if part
    )
    return tuple(
        ingest_key(
            source_id=source_id,
            item_key=item_key,
            content_digest_value=revision_digest,
            revision_id=str(revision_id),
            representation_digest=representation_digest,
            published_at=published_at,
            updated_at=updated_at,
            chunk_ordinal=ordinal,
        )
        for ordinal in range(1, len(chunk_text(full_text)) + 1)
    )


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
    effective_revision: EffectiveRevisionIdentity
    published_at: str | None = None
    updated_at: str | None = None
    chunk_ordinal: int = 1
    chunk_count: int = 1
    predecessor_ingest_id: str | None = None
    attempt_number: int = 1
    authority: CorpusAuthorityBinding | None = None
    source_definition_url: str = ""
    effective_pull_first_observed_at: str = ""

    @property
    def coverage_first_observed_at(self) -> str:
        return (
            self.effective_pull_first_observed_at
            or self.effective_revision.first_observed_at
        )

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
        return representation_digest_for(
            source_id=self.source_id,
            item_key=self.item_key,
            revision_digest=self.revision_digest,
            published_at=self.published_at,
            updated_at=self.updated_at,
        )

    @property
    def ingest_id(self) -> str:
        return ingest_key(
            source_id=self.source_id,
            item_key=self.item_key,
            content_digest_value=self.revision_digest,
            revision_id=self.revision_id,
            representation_digest=self.representation_digest,
            published_at=self.published_at,
            updated_at=self.updated_at,
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
            observed_at=self.coverage_first_observed_at,
        )

    def coverage_key(self) -> EffectiveRevisionCoverageKey:
        return EffectiveRevisionCoverageKey(
            self.source_id,
            self.item_key,
            self.revision_digest,
            self.published_at or "",
            self.updated_at or "",
        )


def units_from(
    observations: tuple[GroupedObservation, ...],
    *,
    proving_run_id: str,
    rights_authority_run_id: str | None = None,
    rights_gate_id: str | None = None,
    rights_gate_reason: str = "retained PASS",
    source_definition_url: str | None = None,
    effective_revision_resolver: EffectiveRevisionIdentityResolver,
) -> tuple[CorpusIngestUnit, ...]:
    units: list[CorpusIngestUnit] = []
    for row in observations:
        revision_digest = content_digest(
            headline=row.item.headline,
            body=row.item.retained_corpus_body,
            canonical_url=row.item.canonical_url,
        )
        effective_revision = effective_revision_resolver.resolve(
            source_id=row.source_id,
            item_key=row.item.item_key,
            revision_digest=revision_digest,
        )
        base = CorpusIngestUnit(
            source_id=row.source_id,
            item_key=row.item.item_key,
            headline=row.item.headline,
            body=row.item.retained_corpus_body,
            canonical_url=row.item.canonical_url,
            observation_digest=row.observation_digest,
            observed_at=row.observed_at,
            proving_run_id=proving_run_id,
            effective_revision=effective_revision,
            published_at=row.item.published_at,
            updated_at=row.item.updated_at,
            source_definition_url=source_definition_url or row.item.canonical_url,
            effective_pull_first_observed_at=(
                effective_revision_resolver.pull_first_observed_at(
                    source_id=row.source_id,
                    item_key=row.item.item_key,
                    revision_digest=revision_digest,
                    published_at=row.item.published_at,
                    updated_at=row.item.updated_at,
                )
            ),
        )
        chunks = chunk_text(base.full_text)
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
                "observed_fallback_at": (
                    base.coverage_first_observed_at
                    if base.published_at is None and base.updated_at is None
                    else None
                ),
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
                effective_revision=base.effective_revision,
                published_at=base.published_at,
                updated_at=base.updated_at,
                chunk_ordinal=ordinal,
                chunk_count=len(chunks),
                predecessor_ingest_id=predecessor,
                authority=authority,
                source_definition_url=base.source_definition_url,
                effective_pull_first_observed_at=(
                    base.effective_pull_first_observed_at
                ),
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
    """One eligible effective revision; chunks remain implementation-level work."""

    revision_id: str
    source_id: str
    item_key: str
    observed_at: str
    source_time: str
    ingest_ids: tuple[str, ...]
    revision_digest: str = ""
    published_at: str | None = None
    updated_at: str | None = None

    def coverage_key(self) -> EffectiveRevisionCoverageKey:
        return EffectiveRevisionCoverageKey(
            self.source_id,
            self.item_key,
            self.revision_digest,
            self.published_at or "",
            self.updated_at or "",
        )


def _effective_revision_chunk_key(
    unit: CorpusIngestUnit,
) -> tuple[str, str, str, str, str, int]:
    return (*unit.coverage_key(), unit.chunk_ordinal)


def unique_chunk_units(
    units: tuple[CorpusIngestUnit, ...],
) -> tuple[CorpusIngestUnit, ...]:
    """Keep one ingest unit per effective-revision chunk.

    Repeated poll observations of unchanged content collapse to the earliest
    retained sighting. A source-supplied version-marker change is a new
    revision. Chunk ordinals stay distinct under that revision.
    """

    selected: dict[tuple[str, str, str, str, str, int], CorpusIngestUnit] = {}
    for unit in units:
        key = _effective_revision_chunk_key(unit)
        previous = selected.get(key)
        if previous is None or unit.observed_at < previous.observed_at:
            selected[key] = unit
    return tuple(
        sorted(
            selected.values(),
            key=lambda item: (
                item.effective_revision.first_observed_at,
                item.revision_id,
                item.chunk_ordinal,
            ),
        )
    )


def _revision_from_chunks(
    chunks: list[CorpusIngestUnit],
) -> EligibleCorpusRevision:
    ordered = sorted(chunks, key=lambda item: item.chunk_ordinal)
    first = ordered[0]
    landed_at = min(chunk.coverage_first_observed_at for chunk in ordered)
    return EligibleCorpusRevision(
        revision_id=first.revision_id,
        source_id=first.source_id,
        item_key=first.item_key,
        observed_at=landed_at,
        source_time=map_reference_time(
            published_at=first.published_at,
            updated_at=first.updated_at,
            observed_at=landed_at,
        ).reference_time.to_text(),
        ingest_ids=tuple(item.ingest_id for item in ordered),
        revision_digest=first.revision_digest,
        published_at=first.published_at,
        updated_at=first.updated_at,
    )


def revisions_from(
    units: tuple[CorpusIngestUnit, ...],
) -> tuple[EligibleCorpusRevision, ...]:
    grouped: dict[tuple[str, str, str, str, str], list[CorpusIngestUnit]] = {}
    for unit in unique_chunk_units(units):
        grouped.setdefault(unit.coverage_key(), []).append(unit)
    revisions = [_revision_from_chunks(chunks) for chunks in grouped.values()]
    return tuple(
        sorted(revisions, key=lambda item: (item.observed_at, item.revision_id))
    )


def synthetic_coverage_revision(
    *,
    source_id: str,
    item_key: str,
    revision_digest: str,
    first_observed_at: str,
    published_at: str | None = None,
    updated_at: str | None = None,
    ingest_ids: tuple[str, ...] = (),
) -> EligibleCorpusRevision:
    """Coverage obligation derivable without a currently retained HTTP body."""

    representation_digest = representation_digest_for(
        source_id=source_id,
        item_key=item_key,
        revision_digest=revision_digest,
        published_at=published_at,
        updated_at=updated_at,
    )
    revision_id = str(
        observation_authority_ids(
            source_id=source_id,
            item_key=item_key,
            revision_digest=revision_digest,
            representation_digest=representation_digest,
            rights_authority_run_id="durable-coverage",
            rights_gate_id=f"RIGHTS_{source_id}",
            rights_gate_reason="durable first-seen",
            published_at=published_at,
            updated_at=updated_at,
        )[4]
    )
    obligation_ids = ingest_ids or (
        ingest_key(
            source_id=source_id,
            item_key=item_key,
            content_digest_value=revision_digest,
            revision_id=revision_id,
            representation_digest=representation_digest,
            published_at=published_at,
            updated_at=updated_at,
            chunk_ordinal=1,
        ),
    )
    return EligibleCorpusRevision(
        revision_id=revision_id,
        source_id=source_id,
        item_key=item_key,
        observed_at=first_observed_at,
        source_time=map_reference_time(
            published_at=published_at,
            updated_at=updated_at,
            observed_at=first_observed_at,
        ).reference_time.to_text(),
        ingest_ids=obligation_ids,
        revision_digest=revision_digest,
        published_at=published_at,
        updated_at=updated_at,
    )


def merge_durable_revisions(
    *,
    window_revisions: tuple[EligibleCorpusRevision, ...],
    first_seen: tuple[tuple[str, str, str, str], ...],
    pull_first_seen: tuple[EffectivePullFirstSeen, ...] = (),
    landed: tuple[EligibleCorpusRevision, ...] = (),
    remapped_effects: tuple[RemappedIngestEffect, ...] = (),
    permitted_source_ids: frozenset[str] | None = None,
) -> tuple[EligibleCorpusRevision, ...]:
    """Keep proven coverage obligations after raw HTTP bodies leave retention.

    Window reconstructions and landed records are authoritative. A receipted
    terminal effect may recover its exact marker-specific pull. Retained
    first-seen state comes only from content that passed eligibility.
    """

    selected: dict[EffectiveRevisionCoverageKey, EligibleCorpusRevision] = {}
    for revision in (*window_revisions, *landed):
        if (
            permitted_source_ids is not None
            and revision.source_id not in permitted_source_ids
        ):
            continue
        selected[revision.coverage_key()] = revision
    first_seen_by_triple = {
        (source_id, item_key, revision_digest): first_observed_at
        for source_id, item_key, revision_digest, first_observed_at in first_seen
        if permitted_source_ids is None or source_id in permitted_source_ids
    }
    effects_by_key: dict[EffectiveRevisionCoverageKey, list[str]] = {}
    for effect in remapped_effects:
        if effect.old_ingest_id:
            effects_by_key.setdefault(
                EffectiveRevisionCoverageKey(
                    effect.source_id,
                    effect.item_key,
                    effect.revision_digest,
                    effect.published_at,
                    effect.updated_at,
                ),
                [],
            ).append(effect.old_ingest_id)
    for pull in pull_first_seen:
        coverage_key = EffectiveRevisionCoverageKey(
            pull.source_id,
            pull.item_key,
            pull.revision_digest,
            pull.published_at,
            pull.updated_at,
        )
        if coverage_key in selected:
            continue
        if (
            pull.source_id,
            pull.item_key,
            pull.revision_digest,
        ) not in first_seen_by_triple:
            continue
        if (
            permitted_source_ids is not None
            and pull.source_id not in permitted_source_ids
        ):
            continue
        selected[coverage_key] = synthetic_coverage_revision(
            source_id=pull.source_id,
            item_key=pull.item_key,
            revision_digest=pull.revision_digest,
            first_observed_at=pull.first_observed_at,
            published_at=pull.published_at or None,
            updated_at=pull.updated_at or None,
            ingest_ids=tuple(sorted(set(effects_by_key.get(coverage_key, ())))),
        )
    for coverage_key, ingest_ids in effects_by_key.items():
        if coverage_key in selected:
            continue
        source_id, item_key, revision_digest, published_at, updated_at = coverage_key
        if permitted_source_ids is not None and source_id not in permitted_source_ids:
            continue
        first_observed_at = first_seen_by_triple.get(
            (source_id, item_key, revision_digest)
        )
        if first_observed_at is None:
            continue
        selected[coverage_key] = synthetic_coverage_revision(
            source_id=source_id,
            item_key=item_key,
            revision_digest=revision_digest,
            first_observed_at=first_observed_at,
            published_at=published_at or None,
            updated_at=updated_at or None,
            ingest_ids=tuple(sorted(set(ingest_ids))),
        )
    covered_triples = {
        (item.source_id, item.item_key, item.revision_digest)
        for item in selected.values()
    }
    for (
        source_id,
        item_key,
        revision_digest,
    ), first_observed_at in first_seen_by_triple.items():
        triple = (source_id, item_key, revision_digest)
        if triple in covered_triples:
            continue
        selected[(source_id, item_key, revision_digest, "", "")] = (
            synthetic_coverage_revision(
                source_id=source_id,
                item_key=item_key,
                revision_digest=revision_digest,
                first_observed_at=first_observed_at,
            )
        )
    return tuple(
        sorted(selected.values(), key=lambda item: (item.observed_at, item.revision_id))
    )
