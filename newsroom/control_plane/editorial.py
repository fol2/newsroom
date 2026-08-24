"""EVALUATION editorial kinds: Signal → Lead → Hypothesis → Candidate.

Same-event key is canonical URL (or source+item). No snowball merge.
These records are the private-beta composition, not Increment 6 closeout.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.control_plane.governed_context import GovernedContext
from newsroom.control_plane.items import SourceItem


def event_key(item: SourceItem) -> str:
    url = item.canonical_url.strip()
    if url:
        return f"url:{url}"
    return f"item:{item.source_id}:{item.item_key}"


def _id(kind: str, key: str) -> str:
    return digest_bytes(canonical_json_bytes({"kind": kind, "key": key}))


@dataclass(frozen=True, slots=True)
class DiscoverySignalRecord:
    signal_id: str
    source_id: str
    item_key: str
    observation_digest: str


@dataclass(frozen=True, slots=True)
class NewsLeadRecord:
    lead_id: str
    signal_id: str
    headline: str


@dataclass(frozen=True, slots=True)
class EventHypothesisRecord:
    hypothesis_id: str
    event_key: str
    lead_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    governed_context: GovernedContext | None = None


@dataclass(frozen=True, slots=True)
class StoryCandidateRecord:
    candidate_id: str
    hypothesis_id: str
    headline: str
    items: tuple[SourceItem, ...]
    signals: tuple[DiscoverySignalRecord, ...]
    leads: tuple[NewsLeadRecord, ...]
    governed_context: GovernedContext | None = None


@dataclass(frozen=True, slots=True)
class GroupedObservation:
    source_id: str
    observation_digest: str
    item: SourceItem
    observed_at: str


def form_candidates(
    observations: tuple[GroupedObservation, ...],
    *,
    governed_context: GovernedContext | None = None,
    governed_context_builder: Callable[
        [tuple[GroupedObservation, ...]], GovernedContext
    ]
    | None = None,
) -> tuple[StoryCandidateRecord, ...]:
    if governed_context is not None and governed_context_builder is not None:
        raise ValueError("governed context and builder are mutually exclusive")
    buckets: dict[str, list[GroupedObservation]] = {}
    for row in observations:
        buckets.setdefault(event_key(row.item), []).append(row)
    candidates: list[StoryCandidateRecord] = []
    for key, rows in buckets.items():
        canonical_rows = tuple(rows)
        candidate_context = (
            governed_context_builder(canonical_rows)
            if governed_context_builder is not None
            else (
                None
                if governed_context is None
                else governed_context.scoped_to(
                    frozenset((row.source_id, row.item.item_key) for row in rows)
                )
            )
        )
        signals: list[DiscoverySignalRecord] = []
        leads: list[NewsLeadRecord] = []
        items: list[SourceItem] = []
        sources: list[str] = []
        for row in rows:
            items.append(row.item)
            sources.append(row.source_id)
            signal = DiscoverySignalRecord(
                signal_id=_id(
                    "discovery_signal",
                    f"{row.source_id}:{row.item.item_key}:{row.observation_digest}",
                ),
                source_id=row.source_id,
                item_key=row.item.item_key,
                observation_digest=row.observation_digest,
            )
            signals.append(signal)
            leads.append(
                NewsLeadRecord(
                    lead_id=_id("news_lead", signal.signal_id),
                    signal_id=signal.signal_id,
                    headline=row.item.headline,
                )
            )
        hypothesis = EventHypothesisRecord(
            hypothesis_id=_id("event_hypothesis", key),
            event_key=key,
            lead_ids=tuple(lead.lead_id for lead in leads),
            source_ids=tuple(sorted(set(sources))),
            governed_context=candidate_context,
        )
        candidates.append(
            StoryCandidateRecord(
                candidate_id=_id("story_candidate", hypothesis.hypothesis_id),
                hypothesis_id=hypothesis.hypothesis_id,
                headline=rows[0].item.headline,
                items=tuple(items),
                signals=tuple(signals),
                leads=tuple(leads),
                governed_context=hypothesis.governed_context,
            )
        )
    return tuple(sorted(candidates, key=lambda item: item.candidate_id))
