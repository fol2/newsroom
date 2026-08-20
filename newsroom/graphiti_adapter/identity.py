"""Deterministic Graphiti ingest identity (GING-002)."""

from __future__ import annotations

from uuid import UUID

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.graphiti_adapter.evaluation_packet import (
    GRAPHITI_CHAT_FALLBACK,
    GRAPHITI_CHAT_MODEL,
    GRAPHITI_CORE_RELEASE,
    GRAPHITI_EMBEDDING_MODEL,
    GRAPHITI_GENERATION_ID,
    TEMPORAL_POLICY_VERSION,
)
from newsroom.graphiti_adapter.types import (
    GraphitiAttemptId,
    GraphitiCleanupReceiptId,
    GraphitiWorkspaceId,
)
from newsroom.sources.types import (
    DiscoveryRepresentationId,
    SourceDefinitionId,
    SourceItemId,
    SourceRevisionId,
)


def uuid4_from_digest(digest: bytes) -> UUID:
    raw = bytearray(digest[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(raw))


def typed_id(factory, *parts: object):
    digest = digest_bytes(canonical_json_bytes(list(parts)))
    hex_part = digest.removeprefix("sha256:")
    return factory.parse(str(uuid4_from_digest(bytes.fromhex(hex_part[:32]))))


def _typed(factory, *parts: object):
    return typed_id(factory, *parts)


def content_digest(*, headline: str, body: str, canonical_url: str) -> str:
    return digest_bytes(
        canonical_json_bytes(
            {"headline": headline, "body": body, "canonical_url": canonical_url}
        )
    )


def configuration_digest() -> str:
    return digest_bytes(
        canonical_json_bytes(
            {
                "framework": GRAPHITI_CORE_RELEASE,
                "chat": GRAPHITI_CHAT_MODEL,
                "fallback": GRAPHITI_CHAT_FALLBACK,
                "embedding": GRAPHITI_EMBEDDING_MODEL,
                "temporal": TEMPORAL_POLICY_VERSION,
                "generation": GRAPHITI_GENERATION_ID,
            }
        )
    )


def ingest_key(
    *,
    source_id: str,
    item_key: str,
    content_digest_value: str,
    chunk_ordinal: int = 1,
) -> str:
    digest = digest_bytes(
        canonical_json_bytes(
            {
                "source_id": source_id,
                "item_key": item_key,
                "content_digest": content_digest_value,
                "chunk_ordinal": chunk_ordinal,
                "configuration": configuration_digest(),
                "temporal": TEMPORAL_POLICY_VERSION,
            }
        )
    )
    return str(uuid4_from_digest(bytes.fromhex(digest.removeprefix("sha256:")[:32])))


def typed_ids(ingest_id: str) -> tuple[
    GraphitiAttemptId,
    GraphitiWorkspaceId,
    GraphitiCleanupReceiptId,
    SourceDefinitionId,
    SourceItemId,
    SourceRevisionId,
    DiscoveryRepresentationId,
]:
    return (
        _typed(GraphitiAttemptId, "attempt", ingest_id),
        _typed(GraphitiWorkspaceId, "workspace", ingest_id),
        _typed(GraphitiCleanupReceiptId, "cleanup", ingest_id),
        _typed(SourceDefinitionId, "definition", ingest_id),
        _typed(SourceItemId, "item", ingest_id),
        _typed(SourceRevisionId, "revision", ingest_id),
        _typed(DiscoveryRepresentationId, "representation", ingest_id),
    )
