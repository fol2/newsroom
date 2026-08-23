"""Compact schema, prompt and identity for combined-temporal extraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from newsroom.authority.canonical import canonical_json_bytes, digest_canonical
from newsroom.graphiti_adapter.combined_temporal_validation import (
    EvidenceSegment,
    segment_source,
)
from newsroom.graphiti_adapter.evaluation_packet import (
    GRAPHITI_EXTRACTION_INSTRUCTIONS,
    GRAPHITI_WORKSPACE_GROUP,
)
from newsroom.graphiti_adapter.identity import (
    content_digest as revision_content_digest,
    ingest_key,
)
from newsroom.graphiti_adapter.temporal import map_reference_time
from newsroom.graphiti_adapter.temporal_vocabulary import TEMPORAL_POLICY_VERSION

CONTRACT_NAME = "NewsroomCombinedTemporalExtractionV1"
GROUP_ID = GRAPHITI_WORKSPACE_GROUP
SCHEMA: dict[str, Any] = {
    "additionalProperties": False,
    "properties": {
        "entities": {
            "items": {
                "additionalProperties": False,
                "properties": {
                    "entity_type_id": {"type": "integer"},
                    "evidence_segment_ids": {
                        "items": {"type": "integer"},
                        "type": "array",
                    },
                    "local_id": {"type": "integer"},
                    "name": {"type": "string"},
                },
                "required": [
                    "local_id",
                    "name",
                    "entity_type_id",
                    "evidence_segment_ids",
                ],
                "type": "object",
            },
            "type": "array",
        },
        "facts": {
            "items": {
                "additionalProperties": False,
                "properties": {
                    "evidence_segment_ids": {
                        "items": {"type": "integer"},
                        "type": "array",
                    },
                    "fact": {"type": "string"},
                    "invalid_at": {"type": ["string", "null"]},
                    "relation_type": {"type": "string"},
                    "source_local_id": {"type": "integer"},
                    "target_local_id": {"type": "integer"},
                    "valid_at": {"type": ["string", "null"]},
                },
                "required": [
                    "source_local_id",
                    "target_local_id",
                    "relation_type",
                    "fact",
                    "valid_at",
                    "invalid_at",
                    "evidence_segment_ids",
                ],
                "type": "object",
            },
            "type": "array",
        },
    },
    "required": ["entities", "facts"],
    "type": "object",
}
SCHEMA_DIGEST = digest_canonical(SCHEMA)


@dataclass(frozen=True, slots=True)
class SourceRevisionInput:
    body: str
    revision_id: str
    source_id: str
    item_key: str
    representation_digest: str
    published_at: str | None
    updated_at: str | None
    observed_at: str
    ingested_at: str
    chunk_ordinal: int = 1
    predecessor_revision_id: str | None = None
    predecessor_body: str | None = None
    group_id: str = GROUP_ID
    episode_uuid: str | None = None

    @property
    def reference_time(self) -> str:
        return map_reference_time(
            published_at=self.published_at,
            updated_at=self.updated_at,
            observed_at=self.observed_at,
        ).reference_time.to_text()

    @property
    def temporal_basis(self) -> str:
        return map_reference_time(
            published_at=self.published_at,
            updated_at=self.updated_at,
            observed_at=self.observed_at,
        ).basis.value

    @property
    def content_digest(self) -> str:
        return revision_content_digest(
            headline="", body=self.body, canonical_url=""
        )

    @property
    def ingest_id(self) -> str:
        prompt = build_compact_prompt(self)
        return ingest_key(
            source_id=self.source_id,
            item_key=self.item_key,
            content_digest_value=self.content_digest,
            revision_id=self.revision_id,
            representation_digest=self.representation_digest,
            published_at=self.published_at,
            updated_at=self.updated_at,
            observed_at=self.observed_at,
            chunk_ordinal=self.chunk_ordinal,
            schema_digest=SCHEMA_DIGEST,
            prompt_digest=_candidate_prompt_digest(prompt),
            workspace_group=self.group_id,
            episode_uuid=self.episode_uuid,
        )


@dataclass(frozen=True, slots=True)
class CompactPrompt:
    text: str
    schema: dict[str, Any]
    segments: tuple[EvidenceSegment, ...]


def build_compact_prompt(revision: SourceRevisionInput) -> CompactPrompt:
    segments = segment_source(revision.body)
    schema_text = canonical_json_bytes(SCHEMA).decode("utf-8")
    predecessor = revision.predecessor_revision_id or "null"
    lines = [
        CONTRACT_NAME,
        "Return exactly one JSON object. No prose, planning residue or schema echo.",
        "One effective source revision. Do not use any other revision's wording.",
        "Retain every supplied segment; do not summarise or truncate.",
        "Extract only named or source-grounded entities that participate in a retained fact.",
        "The wire entities are untrusted Entity Mentions; they are not Canonical Entities.",
        "Zero facts requires zero entities.",
        "Use the source's certainty. Do not add outside knowledge.",
        "The wire facts are untrusted Relation Proposals; they are not governed facts.",
        "Build each relation_type only from relation words present in its fact; entity-name words are not relation evidence.",
        "Put valid_at and invalid_at on each fact. Resolve relative dates against REFERENCE_TIME to ISO-8601 UTC, or null.",
        "Cite evidence with the integer segment IDs below. Do not invent byte offsets.",
        "A valid empty object is terminal success.",
        "Exclude source-registry identifiers and deterministic corpus metadata (SourceItem, SourceRevision, DERIVED_FROM, OBSERVED_IN).",
        GRAPHITI_EXTRACTION_INSTRUCTIONS,
        f"REFERENCE_TIME: {revision.reference_time}",
        f"TEMPORAL_BASIS: {revision.temporal_basis}",
        f"TEMPORAL_POLICY: {TEMPORAL_POLICY_VERSION}",
        f"REVISION_ID: {revision.revision_id}",
        f"PREDECESSOR_REVISION_ID: {predecessor}",
        "SCHEMA:",
        schema_text,
        "SEGMENTS:",
        *(f"[{item.segment_id}] {item.text}" for item in segments),
    ]
    return CompactPrompt("\n".join(lines), SCHEMA, segments)


def _candidate_prompt_digest(prompt: CompactPrompt) -> str:
    return digest_canonical({"prompt": prompt.text, "schema": SCHEMA})


__all__ = [
    "CONTRACT_NAME",
    "GROUP_ID",
    "SCHEMA",
    "SCHEMA_DIGEST",
    "CompactPrompt",
    "EvidenceSegment",
    "SourceRevisionInput",
    "build_compact_prompt",
    "segment_source",
]
