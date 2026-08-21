"""Observable token accounting for Graphiti chat and embedding providers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TypeGuard


CLI_USAGE_BASIS_REPORTED = "PROVIDER_REPORTED"
CLI_USAGE_BASIS_UNREPORTED = "UNREPORTED"


def _is_non_negative_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def unreported_cli_usage() -> dict[str, object]:
    """Return an explicit unknown shape; unknown usage is never a silent zero."""

    return {
        "usage_basis": CLI_USAGE_BASIS_UNREPORTED,
        "input_tokens": None,
        "output_tokens": None,
        "cached_read_tokens": None,
        "cached_write_tokens": None,
        "reasoning_tokens": None,
        "total_tokens": None,
    }


def cursor_cli_usage(value: object) -> dict[str, object]:
    """Normalise Cursor's final JSON usage into the retained receipt contract."""

    if not isinstance(value, Mapping):
        return unreported_cli_usage()
    fields = {
        "input_tokens": value.get("inputTokens"),
        "output_tokens": value.get("outputTokens"),
        "cached_read_tokens": value.get("cacheReadTokens"),
        "cached_write_tokens": value.get("cacheWriteTokens"),
    }
    if not all(_is_non_negative_int(item) for item in fields.values()):
        return unreported_cli_usage()
    # Cursor's print-mode JSON reports uncached input separately from cache reads
    # and writes, so all four fields are disjoint parts of observed consumption.
    total = sum(int(item) for item in fields.values())
    return {
        "usage_basis": CLI_USAGE_BASIS_REPORTED,
        **fields,
        "reasoning_tokens": None,
        "total_tokens": total,
    }


def grok_cli_usage(value: object) -> dict[str, object]:
    """Normalise a Grok ``turn_completed`` usage event."""

    if not isinstance(value, Mapping):
        return unreported_cli_usage()
    input_tokens = value.get("inputTokens")
    output_tokens = value.get("outputTokens")
    total_tokens = value.get("totalTokens")
    cached_read = value.get("cachedReadTokens", 0)
    cached_write = value.get("cacheCreationTokens", 0)
    reasoning = value.get("reasoningTokens")
    required = (input_tokens, output_tokens, total_tokens, cached_read, cached_write)
    if not all(_is_non_negative_int(item) for item in required):
        return unreported_cli_usage()
    if reasoning is not None and not _is_non_negative_int(reasoning):
        return unreported_cli_usage()
    return {
        "usage_basis": CLI_USAGE_BASIS_REPORTED,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_read_tokens": cached_read,
        "cached_write_tokens": cached_write,
        "reasoning_tokens": reasoning,
        "total_tokens": total_tokens,
    }


def _reported_chat_usage(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    if value.get("usage_basis") != CLI_USAGE_BASIS_REPORTED:
        return None
    required = (
        "input_tokens",
        "output_tokens",
        "cached_read_tokens",
        "cached_write_tokens",
        "total_tokens",
    )
    if not all(_is_non_negative_int(value.get(key)) for key in required):
        return None
    reasoning = value.get("reasoning_tokens")
    if reasoning is not None and not _is_non_negative_int(reasoning):
        return None
    return value


def summarise_graphiti_usage(
    *,
    chat_invocations: Iterable[Mapping[str, object]],
    embedding_usage: Mapping[str, object] | None,
) -> dict[str, object]:
    """Build one query-friendly total without disguising unreported calls as zero."""

    invocations = tuple(chat_invocations)
    reported: list[Mapping[str, object]] = []
    cursor_requests = 0
    grok_requests = 0
    for invocation in invocations:
        provider = invocation.get("provider")
        cursor_requests += int(provider == "cursor-agent-cli")
        grok_requests += int(provider == "grok-build-cli")
        usage = _reported_chat_usage(invocation.get("usage"))
        if usage is not None:
            reported.append(usage)

    def total(key: str) -> int:
        return sum(int(item[key]) for item in reported)

    chat_reasoning = sum(int(item.get("reasoning_tokens") or 0) for item in reported)
    unreported_chat = len(invocations) - len(reported)
    embedding_basis = (
        str(embedding_usage.get("usage_basis"))
        if isinstance(embedding_usage, Mapping)
        else "UNREPORTED"
    )
    embedding_requests = (
        embedding_usage.get("request_count", 0)
        if isinstance(embedding_usage, Mapping)
        else 0
    )
    embedding_tokens = (
        embedding_usage.get("embedding_tokens", 0)
        if isinstance(embedding_usage, Mapping)
        else 0
    )
    embedding_cost = (
        embedding_usage.get("cost_usd_microunits", 0)
        if isinstance(embedding_usage, Mapping)
        else 0
    )
    if not _is_non_negative_int(embedding_requests):
        embedding_requests = 0
    if not _is_non_negative_int(embedding_tokens):
        embedding_tokens = 0
    if not _is_non_negative_int(embedding_cost):
        embedding_cost = 0

    embedding_complete = embedding_basis in {
        "PROVIDER_REPORTED",
        "NO_EMBEDDING_CALL",
    }
    observed_any = bool(reported) or bool(embedding_requests)
    incomplete = unreported_chat > 0 or not embedding_complete
    if not invocations and not embedding_requests and embedding_complete:
        basis = "NO_PROVIDER_CALL"
    elif incomplete:
        basis = "PROVIDER_PARTIALLY_UNREPORTED" if observed_any else "UNREPORTED"
    else:
        basis = "PROVIDER_REPORTED"

    chat_total = total("total_tokens")
    return {
        "usage_basis": basis,
        "chat_request_count": len(invocations),
        "cursor_request_count": cursor_requests,
        "grok_request_count": grok_requests,
        "chat_input_tokens": total("input_tokens"),
        "chat_output_tokens": total("output_tokens"),
        "chat_cached_read_tokens": total("cached_read_tokens"),
        "chat_cached_write_tokens": total("cached_write_tokens"),
        "chat_reasoning_tokens": chat_reasoning,
        "chat_total_tokens": chat_total,
        "embedding_request_count": int(embedding_requests),
        "embedding_tokens": int(embedding_tokens),
        "embedding_cost_usd_microunits": int(embedding_cost),
        "observed_total_tokens": chat_total + int(embedding_tokens),
        "unreported_chat_requests": unreported_chat,
    }


__all__ = [
    "cursor_cli_usage",
    "grok_cli_usage",
    "summarise_graphiti_usage",
    "unreported_cli_usage",
]
