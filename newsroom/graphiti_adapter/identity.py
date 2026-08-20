"""Deterministic Graphiti ingest identity (GING-002)."""

from __future__ import annotations

from typing import TypeVar
from uuid import UUID

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.objects import ObjectAccessDecisionId
from newsroom.authority.types import ObjectAdmissionId, UUIDv4Id
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

MAX_EPISODE_BYTES = 8 * 1024
TypedId = TypeVar("TypedId", bound=UUIDv4Id)


def uuid4_from_digest(digest: bytes) -> UUID:
    raw = bytearray(digest[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(raw))


def typed_id(factory: type[TypedId], *parts: object) -> TypedId:
    digest = digest_bytes(canonical_json_bytes(list(parts)))
    hex_part = digest.removeprefix("sha256:")
    return factory.parse(str(uuid4_from_digest(bytes.fromhex(hex_part[:32]))))


def _typed(factory: type[TypedId], *parts: object) -> TypedId:
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
    observation_digest: str,
    published_at: str | None,
    updated_at: str | None,
    observed_at: str,
    chunk_ordinal: int = 1,
) -> str:
    digest = digest_bytes(
        canonical_json_bytes(
            {
                "source_id": source_id,
                "item_key": item_key,
                "observation_digest": observation_digest,
                "published_at": published_at,
                "updated_at": updated_at,
                "observed_at": observed_at,
                "content_digest": content_digest_value,
                "chunk_ordinal": chunk_ordinal,
                "configuration": configuration_digest(),
                "temporal": TEMPORAL_POLICY_VERSION,
            }
        )
    )
    return str(uuid4_from_digest(bytes.fromhex(digest.removeprefix("sha256:")[:32])))


def attempt_ids(ingest_id: str) -> tuple[
    GraphitiAttemptId, GraphitiWorkspaceId, GraphitiCleanupReceiptId
]:
    return (
        _typed(GraphitiAttemptId, "attempt", ingest_id),
        _typed(GraphitiWorkspaceId, "workspace", ingest_id),
        _typed(GraphitiCleanupReceiptId, "cleanup", ingest_id),
    )


def observation_authority_ids(
    *,
    proving_run_id: str,
    source_id: str,
    item_key: str,
    observation_digest: str,
    published_at: str | None,
    updated_at: str | None,
) -> tuple[
    ObjectAdmissionId,
    ObjectAccessDecisionId,
    SourceDefinitionId,
    SourceItemId,
    SourceRevisionId,
    DiscoveryRepresentationId,
]:
    return (
        _typed(
            ObjectAdmissionId,
            "proving-admission",
            proving_run_id,
            source_id,
            observation_digest,
        ),
        _typed(
            ObjectAccessDecisionId,
            "proving-access",
            proving_run_id,
            source_id,
            observation_digest,
        ),
        _typed(SourceDefinitionId, "definition", source_id),
        _typed(SourceItemId, "item", source_id, item_key),
        _typed(
            SourceRevisionId,
            "revision",
            source_id,
            item_key,
            observation_digest,
            published_at or "",
            updated_at or "",
        ),
        _typed(
            DiscoveryRepresentationId,
            "representation",
            source_id,
            observation_digest,
        ),
    )
