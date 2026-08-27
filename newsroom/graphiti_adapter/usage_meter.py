"""Observable token accounting for Graphiti chat and embedding providers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TypeGuard

CLI_USAGE_BASIS_REPORTED = "PROVIDER_REPORTED"
CLI_USAGE_BASIS_UNREPORTED = "UNREPORTED"
CLI_USAGE_BASIS_NO_PROVIDER_CALL = "NO_PROVIDER_CALL"
_EXACT_NO_PROVIDER_USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cached_read_tokens",
    "cached_write_tokens",
    "reasoning_tokens",
    "total_tokens",
)


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


def no_provider_call_cli_usage() -> dict[str, object]:
    """Return an exact zero only when provider dispatch was structurally ruled out."""

    return {
        "usage_basis": CLI_USAGE_BASIS_NO_PROVIDER_CALL,
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_read_tokens": 0,
        "cached_write_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
    }


def is_exact_predispatch_no_provider_call(value: object) -> bool:
    """Prove one CLI leaf stopped locally with exact zero provider usage."""

    if not isinstance(value, Mapping):
        return False
    usage = value.get("usage")
    return (
        isinstance(usage, Mapping)
        and value.get("outcome")
        in {"PREDISPATCH_REFUSED", "EXECUTABLE_NOT_FOUND"}
        and usage.get("usage_basis") == CLI_USAGE_BASIS_NO_PROVIDER_CALL
        and set(usage) == {"usage_basis", *_EXACT_NO_PROVIDER_USAGE_FIELDS}
        and all(
            type(usage.get(field)) is int and usage.get(field) == 0
            for field in _EXACT_NO_PROVIDER_USAGE_FIELDS
        )
    )


def cursor_sdk_usage(value: object) -> dict[str, object]:
    """Normalise typed SDK TokenUsage into the retained receipt contract."""

    if value is None:
        return unreported_cli_usage()
    if isinstance(value, Mapping):
        fields = {
            "input_tokens": value.get("input_tokens", value.get("inputTokens")),
            "output_tokens": value.get("output_tokens", value.get("outputTokens")),
            "cached_read_tokens": value.get(
                "cached_read_tokens",
                value.get("cache_read_tokens", value.get("cacheReadTokens")),
            ),
            "cached_write_tokens": value.get(
                "cached_write_tokens",
                value.get("cache_write_tokens", value.get("cacheWriteTokens")),
            ),
        }
        reasoning = value.get(
            "reasoning_tokens", value.get("reasoningTokens")
        )
        total = value.get("total_tokens", value.get("totalTokens"))
    else:
        fields = {
            "input_tokens": getattr(value, "input_tokens", None),
            "output_tokens": getattr(value, "output_tokens", None),
            "cached_read_tokens": getattr(
                value,
                "cached_read_tokens",
                getattr(value, "cache_read_tokens", None),
            ),
            "cached_write_tokens": getattr(
                value,
                "cached_write_tokens",
                getattr(value, "cache_write_tokens", None),
            ),
        }
        reasoning = getattr(value, "reasoning_tokens", None)
        total = getattr(value, "total_tokens", None)
    if not all(_is_non_negative_int(item) for item in fields.values()):
        return unreported_cli_usage()
    if total is None:
        total = sum(item for item in fields.values() if _is_non_negative_int(item))
    if not _is_non_negative_int(total):
        return unreported_cli_usage()
    if reasoning is not None and not _is_non_negative_int(reasoning):
        return unreported_cli_usage()
    return {
        "usage_basis": CLI_USAGE_BASIS_REPORTED,
        **fields,
        "reasoning_tokens": reasoning,
        "total_tokens": total,
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
    context_tokens = value.get("contextTokensUsed")
    if not all(_is_non_negative_int(item) for item in fields.values()):
        return unreported_cli_usage()
    # Cursor's print-mode JSON reports uncached input separately from cache reads
    # and writes, so all four fields are disjoint parts of observed consumption.
    total = sum(item for item in fields.values() if _is_non_negative_int(item))
    if context_tokens is not None and not _is_non_negative_int(context_tokens):
        return unreported_cli_usage()
    result: dict[str, object] = {
        "usage_basis": CLI_USAGE_BASIS_REPORTED,
        **fields,
        "reasoning_tokens": None,
        "total_tokens": total,
    }
    if context_tokens is not None:
        result["context_tokens"] = context_tokens
    return result


def grok_cli_usage(value: object) -> dict[str, object]:
    """Normalise a Grok ``turn_completed`` usage event."""

    if not isinstance(value, Mapping):
        return unreported_cli_usage()
    input_tokens = value.get("inputTokens", value.get("input_tokens"))
    output_tokens = value.get("outputTokens", value.get("output_tokens"))
    total_tokens = value.get("totalTokens", value.get("total_tokens"))
    cached_read = value.get(
        "cachedReadTokens", value.get("cache_read_input_tokens", 0)
    )
    cached_write = value.get(
        "cacheCreationTokens", value.get("cache_creation_input_tokens", 0)
    )
    reasoning = value.get("reasoningTokens", value.get("reasoning_tokens"))
    context_tokens = value.get("contextTokensUsed", value.get("context_tokens"))
    required = (input_tokens, output_tokens, total_tokens, cached_read, cached_write)
    if not all(_is_non_negative_int(item) for item in required):
        return unreported_cli_usage()
    if reasoning is not None and not _is_non_negative_int(reasoning):
        return unreported_cli_usage()
    if context_tokens is not None and not _is_non_negative_int(context_tokens):
        return unreported_cli_usage()
    if context_tokens is None:
        # Grok 1.0.10 headless omits contextTokensUsed. Prompt occupancy is
        # the documented uncached input plus cache buckets, not a silent zero
        # and not the context-window size.
        context_tokens = input_tokens + cached_read + cached_write
    result = {
        "usage_basis": CLI_USAGE_BASIS_REPORTED,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_read_tokens": cached_read,
        "cached_write_tokens": cached_write,
        "reasoning_tokens": reasoning,
        "total_tokens": total_tokens,
        "context_tokens": context_tokens,
    }
    return result


def _exact_chat_usage(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    basis = value.get("usage_basis")
    if basis == CLI_USAGE_BASIS_NO_PROVIDER_CALL:
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_read_tokens": 0,
            "cached_write_tokens": 0,
            "reasoning_tokens": 0,
            "context_tokens": 0,
            "total_tokens": 0,
        }
    if basis != CLI_USAGE_BASIS_REPORTED:
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
        usage = _exact_chat_usage(invocation.get("usage"))
        if usage is not None:
            reported.append(usage)

    def total(key: str) -> int:
        return sum(
            value
            for item in reported
            if _is_non_negative_int(value := item.get(key))
        )

    chat_reasoning = sum(
        value
        for item in reported
        if _is_non_negative_int(value := item.get("reasoning_tokens"))
    )
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
        "NO_PROVIDER_CALL",
    }
    observed_any = bool(reported) or bool(embedding_requests)
    incomplete = unreported_chat > 0 or not embedding_complete
    provider_reported = embedding_basis == "PROVIDER_REPORTED" or any(
        isinstance(usage := invocation.get("usage"), Mapping)
        and usage.get("usage_basis") == "PROVIDER_REPORTED"
        for invocation in invocations
    )
    if not incomplete and not provider_reported:
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
        "chat_context_tokens": total("context_tokens"),
        "chat_total_tokens": chat_total,
        "embedding_request_count": int(embedding_requests),
        "embedding_tokens": int(embedding_tokens),
        "embedding_cost_usd_microunits": int(embedding_cost),
        "observed_total_tokens": chat_total + int(embedding_tokens),
        "unreported_chat_requests": unreported_chat,
    }


__all__ = [
    "cursor_cli_usage",
    "cursor_sdk_usage",
    "grok_cli_usage",
    "is_exact_predispatch_no_provider_call",
    "no_provider_call_cli_usage",
    "summarise_graphiti_usage",
    "unreported_cli_usage",
]
