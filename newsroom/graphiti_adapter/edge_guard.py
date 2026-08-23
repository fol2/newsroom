"""Structural edge guard for the pinned Graphiti 0.29.3 runtime."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


async def guard_extracted_edges(
    *,
    extracted_edges: list[Any],
    uuid_map: dict[str, str],
    embedder: Any,
    resolve_pointers: Callable[[list[Any], dict[str, str]], list[Any]],
    create_embeddings: Callable[[Any, list[Any]], Awaitable[None]],
) -> tuple[list[Any], list[Any], list[Any]]:
    """Keep fresh episode edges and bypass all existing-edge resolution."""

    resolved = resolve_pointers(extracted_edges, uuid_map)
    unique: dict[tuple[str, str, str, str], Any] = {}
    for edge in resolved:
        key = (
            str(edge.source_node_uuid),
            str(edge.target_node_uuid),
            str(getattr(edge, "name", "") or ""),
            " ".join(str(edge.fact).split()),
        )
        unique.setdefault(key, edge)
    guarded = list(unique.values())
    await create_embeddings(embedder, guarded)
    # The middle collection is graphiti-core's invalidation write set. It is
    # structurally empty; no existing edge is searched, reused or invalidated.
    return guarded, [], guarded


__all__ = ["guard_extracted_edges"]
