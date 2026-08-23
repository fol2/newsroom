"""Deterministic Graphiti ingest identity (GING-002)."""

from __future__ import annotations

from typing import TypeVar
from uuid import UUID

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
)
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
    SourceDefinitionVersionId,
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


def representation_digest_for(
    *,
    source_id: str,
    item_key: str,
    revision_digest: str,
    published_at: str | None,
    updated_at: str | None,
) -> str:
    """Identity digest for a representation. Observation time must not enter it."""

    return digest_canonical(
        {
            "source_id": source_id,
            "item_key": item_key,
            "revision_digest": revision_digest,
            "published_at": published_at,
            "updated_at": updated_at,
        }
    )


def ingest_key(
    *,
    source_id: str,
    item_key: str,
    content_digest_value: str,
    revision_id: str,
    representation_digest: str,
    published_at: str | None,
    updated_at: str | None,
    chunk_ordinal: int = 1,
) -> str:
    digest = digest_bytes(
        canonical_json_bytes(
            {
                "source_id": source_id,
                "item_key": item_key,
                "revision_id": revision_id,
                "representation_digest": representation_digest,
                "published_at": published_at,
                "updated_at": updated_at,
                "content_digest": content_digest_value,
                "chunk_ordinal": chunk_ordinal,
                "configuration": configuration_digest(),
                "temporal": TEMPORAL_POLICY_VERSION,
            }
        )
    )
    return str(uuid4_from_digest(bytes.fromhex(digest.removeprefix("sha256:")[:32])))


def source_revision_id(
    *,
    source_id: str,
    item_key: str,
    revision_digest: str,
    published_at: str | None,
    updated_at: str | None,
) -> SourceRevisionId:
    return _typed(
        SourceRevisionId,
        "revision",
        source_id,
        item_key,
        revision_digest,
        published_at or "",
        updated_at or "",
    )


def attempt_ids(
    ingest_id: str, attempt_number: int = 1
) -> tuple[GraphitiAttemptId, GraphitiWorkspaceId, GraphitiCleanupReceiptId]:
    return (
        _typed(GraphitiAttemptId, "attempt", ingest_id, attempt_number),
        _typed(GraphitiWorkspaceId, "workspace", ingest_id, attempt_number),
        _typed(GraphitiCleanupReceiptId, "cleanup", ingest_id, attempt_number),
    )


def observation_authority_ids(
    *,
    source_id: str,
    item_key: str,
    revision_digest: str,
    representation_digest: str,
    rights_authority_run_id: str,
    rights_gate_id: str,
    rights_gate_reason: str,
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
    revision_id = source_revision_id(
        source_id=source_id,
        item_key=item_key,
        revision_digest=revision_digest,
        published_at=published_at,
        updated_at=updated_at,
    )
    return (
        _typed(
            ObjectAdmissionId,
            "proving-admission",
            str(revision_id),
        ),
        _typed(
            ObjectAccessDecisionId,
            "proving-access",
            str(revision_id),
            rights_authority_run_id,
            rights_gate_id,
            rights_gate_reason,
        ),
        _typed(SourceDefinitionId, "definition", source_id),
        _typed(SourceItemId, "item", source_id, item_key),
        revision_id,
        _typed(
            DiscoveryRepresentationId,
            "representation",
            source_id,
            item_key,
            representation_digest,
        ),
    )


def source_definition_version_id(
    *, source_id: str, source_url: str
) -> SourceDefinitionVersionId:
    """Bind a version identity to the retained source endpoint definition."""

    return _typed(
        SourceDefinitionVersionId, "definition-version", source_id, source_url
    )
