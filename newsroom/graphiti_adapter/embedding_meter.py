"""Provider-native metering wrapper for OpenRouter Graphiti embeddings."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Protocol, TypeGuard

from newsroom.graphiti_adapter.evaluation_packet import OPENROUTER_EMBEDDING_SLUG

_PROVIDER_USAGE_KEYS = frozenset(
    {
        "requests",
        "request_count",
        "embedding_tokens",
        "cost_usd_microunits",
        "usage_basis",
    }
)
_PROVIDER_REQUEST_KEYS = frozenset(
    {
        "provider",
        "model",
        "request_id",
        "prompt_tokens",
        "total_tokens",
        "cost_usd_microunits",
        "cost_reported",
        "outcome",
    }
)
_EMBEDDING_USAGE_KEYS = frozenset(
    {
        "requests",
        "request_count",
        "embedding_tokens",
        "cost_usd_microunits",
        "usage_basis",
    }
)


class EmbeddingInvocationObserver(Protocol):
    def before_embedding_invocation(
        self, *, provider: str, model: str, input_data: object
    ) -> object: ...

    def transport_dispatch_started(self, token: object) -> None: ...

    def after_embedding_invocation(
        self,
        token: object,
        *,
        outcome: str,
        usage: dict[str, object],
    ) -> Mapping[str, str] | None: ...


def _is_non_negative_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_exact_no_provider_request(request: object) -> bool:
    return (
        isinstance(request, Mapping)
        and request.get("provider") == "openrouter"
        and request.get("model") == OPENROUTER_EMBEDDING_SLUG
        and request.get("request_id") == ""
        and request.get("prompt_tokens") is None
        and request.get("total_tokens") is None
        and request.get("cost_usd_microunits") is None
        and request.get("cost_reported") is False
        and request.get("outcome") in {"FAILED", "CANCELLED"}
        and request.get("usage_basis") == "NO_PROVIDER_CALL"
    )


def is_exact_provider_reported_usage(
    embedding_usage: Mapping[str, object] | None,
) -> bool:
    """Validate required provider-native fields and internally consistent totals."""

    if embedding_usage is None or not _PROVIDER_USAGE_KEYS <= set(embedding_usage):
        return False
    requests = embedding_usage["requests"]
    request_count = embedding_usage["request_count"]
    embedding_tokens = embedding_usage["embedding_tokens"]
    cost = embedding_usage["cost_usd_microunits"]
    if (
        embedding_usage["usage_basis"] != "PROVIDER_REPORTED"
        or not isinstance(requests, list)
        or not requests
        or not _is_non_negative_int(request_count)
        or not _is_non_negative_int(embedding_tokens)
        or not _is_non_negative_int(cost)
        or request_count != len(requests)
    ):
        return False
    request_tokens = 0
    request_cost = 0
    provider_request_count = 0
    for request in requests:
        if _is_exact_no_provider_request(request):
            continue
        if (
            not isinstance(request, Mapping)
            or not _PROVIDER_REQUEST_KEYS <= set(request)
        ):
            return False
        prompt_tokens = request["prompt_tokens"]
        total_tokens = request["total_tokens"]
        item_cost = request["cost_usd_microunits"]
        if (
            request["provider"] != "openrouter"
            or request["model"] != OPENROUTER_EMBEDDING_SLUG
            or not isinstance(request["request_id"], str)
            or not _is_non_negative_int(total_tokens)
            or not _is_non_negative_int(item_cost)
            or request["cost_reported"] is not True
            or request["outcome"] != "COMPLETE"
        ):
            return False
        if prompt_tokens is not None and (
            not _is_non_negative_int(prompt_tokens)
            or prompt_tokens > total_tokens
        ):
            return False
        provider_request_count += 1
        request_tokens += total_tokens
        request_cost += item_cost
    return (
        provider_request_count > 0
        and request_tokens == embedding_tokens
        and request_cost == cost
    )


def is_exact_no_provider_call_usage(
    embedding_usage: Mapping[str, object] | None,
) -> bool:
    """Validate retained embedding requests proved to stop before provider I/O."""

    if embedding_usage is None or set(embedding_usage) != _EMBEDDING_USAGE_KEYS:
        return False
    requests = embedding_usage["requests"]
    request_count = embedding_usage["request_count"]
    if (
        embedding_usage["usage_basis"] != "NO_PROVIDER_CALL"
        or not isinstance(requests, list)
        or not requests
        or not _is_non_negative_int(request_count)
        or request_count != len(requests)
        or not _is_non_negative_int(embedding_usage["embedding_tokens"])
        or embedding_usage["embedding_tokens"] != 0
        or not _is_non_negative_int(embedding_usage["cost_usd_microunits"])
        or embedding_usage["cost_usd_microunits"] != 0
    ):
        return False
    return all(_is_exact_no_provider_request(request) for request in requests)


def _integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _usd_microunits(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if amount < 0:
        return None
    return int((amount * Decimal(1_000_000)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _usage_value(response: Any) -> dict[str, object]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        value = usage.model_dump()
        return value if isinstance(value, dict) else {}
    if isinstance(usage, dict):
        return usage
    return {
        key: getattr(usage, key)
        for key in ("prompt_tokens", "total_tokens", "cost")
        if hasattr(usage, key)
    }


class MeteredOpenAIEmbedder:
    """Embedder-compatible wrapper retaining each provider response's usage."""

    def __init__(
        self,
        delegate: Any,
        *,
        invocation_observer: EmbeddingInvocationObserver | None = None,
    ) -> None:
        self._delegate = delegate
        self._invocation_observer = invocation_observer
        self.requests: list[dict[str, object]] = []

    async def _create(self, input_data: object) -> Any:
        request: dict[str, object] = {
            "provider": "openrouter",
            "model": self._delegate.config.embedding_model,
            "request_id": "",
            "prompt_tokens": None,
            "total_tokens": None,
            "cost_usd_microunits": None,
            "cost_reported": False,
            "outcome": "UNOBSERVED",
        }
        observer_token = (
            None
            if self._invocation_observer is None
            else self._invocation_observer.before_embedding_invocation(
                provider="openrouter",
                model=self._delegate.config.embedding_model,
                input_data=input_data,
            )
        )
        self.requests.append(request)
        transport_started = False
        try:
            if self._invocation_observer is not None:
                dispatch_started = getattr(
                    self._invocation_observer,
                    "transport_dispatch_started",
                    None,
                )
                if callable(dispatch_started):
                    dispatch_started(observer_token)
            transport_started = True
            response = await self._delegate.client.embeddings.create(
                input=input_data,
                model=self._delegate.config.embedding_model,
            )
        except asyncio.CancelledError:
            if self._invocation_observer is not None:
                usage = (
                    {
                        "usage_basis": "UNREPORTED",
                        "input_tokens": None,
                        "output_tokens": None,
                        "cached_read_tokens": None,
                        "cached_write_tokens": None,
                        "reasoning_tokens": None,
                        "total_tokens": None,
                    }
                    if transport_started
                    else {
                        "usage_basis": "NO_PROVIDER_CALL",
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cached_read_tokens": 0,
                        "cached_write_tokens": 0,
                        "reasoning_tokens": 0,
                        "total_tokens": 0,
                    }
                )
                binding = self._invocation_observer.after_embedding_invocation(
                    observer_token,
                    outcome="CANCELLED",
                    usage=usage,
                )
                request.update(
                    {
                        "outcome": "CANCELLED",
                        "usage_basis": usage["usage_basis"],
                    }
                )
                if binding is not None:
                    request.update(binding)
            raise
        except Exception:
            if self._invocation_observer is not None:
                usage = (
                    {
                        "usage_basis": "UNREPORTED",
                        "input_tokens": None,
                        "output_tokens": None,
                        "cached_read_tokens": None,
                        "cached_write_tokens": None,
                        "reasoning_tokens": None,
                        "total_tokens": None,
                    }
                    if transport_started
                    else {
                        "usage_basis": "NO_PROVIDER_CALL",
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cached_read_tokens": 0,
                        "cached_write_tokens": 0,
                        "reasoning_tokens": 0,
                        "total_tokens": 0,
                    }
                )
                binding = self._invocation_observer.after_embedding_invocation(
                    observer_token,
                    outcome="FAILED",
                    usage=usage,
                )
                request.update(
                    {"outcome": "FAILED", "usage_basis": usage["usage_basis"]}
                )
                if binding is not None:
                    request.update(binding)
            raise
        usage = _usage_value(response)
        cost = _usd_microunits(usage.get("cost"))
        request.update(
            {
                "request_id": str(getattr(response, "id", "") or ""),
                "prompt_tokens": _integer(usage.get("prompt_tokens")),
                "total_tokens": _integer(usage.get("total_tokens")),
                "cost_usd_microunits": cost,
                "cost_reported": cost is not None,
                "outcome": "COMPLETE",
            }
        )
        if self._invocation_observer is not None:
            binding = self._invocation_observer.after_embedding_invocation(
                observer_token,
                outcome="COMPLETE",
                usage={
                    "usage_basis": (
                        "PROVIDER_REPORTED"
                        if request["total_tokens"] is not None
                        else "UNREPORTED"
                    ),
                    "input_tokens": request["prompt_tokens"],
                    "output_tokens": 0,
                    "cached_read_tokens": 0,
                    "cached_write_tokens": 0,
                    "reasoning_tokens": 0,
                    "total_tokens": request["total_tokens"],
                    "provider_telemetry": dict(request),
                },
            )
            if binding is not None:
                request.update(binding)
        return response

    async def create(self, input_data: object) -> list[float]:
        response = await self._create(input_data)
        return response.data[0].embedding[: self._delegate.config.embedding_dim]

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        response = await self._create(input_data_list)
        dimension = self._delegate.config.embedding_dim
        return [item.embedding[:dimension] for item in response.data]

    def receipt(self) -> dict[str, object]:
        token_values = [
            value
            for item in self.requests
            if _is_non_negative_int(value := item.get("total_tokens"))
        ]
        costs = [
            value
            for item in self.requests
            if _is_non_negative_int(value := item.get("cost_usd_microunits"))
        ]
        exact_zero = {
            "requests": list(self.requests),
            "request_count": len(self.requests),
            "embedding_tokens": 0,
            "cost_usd_microunits": 0,
            "usage_basis": "NO_PROVIDER_CALL",
        }
        if is_exact_no_provider_call_usage(exact_zero):
            return exact_zero
        aggregate = {
            "requests": list(self.requests),
            "request_count": len(self.requests),
            "embedding_tokens": sum(token_values),
            "cost_usd_microunits": sum(costs),
            "usage_basis": "PROVIDER_REPORTED",
        }
        if is_exact_provider_reported_usage(aggregate):
            return aggregate
        aggregate["usage_basis"] = (
            "PROVIDER_PARTIALLY_UNREPORTED"
            if self.requests
            else "NO_EMBEDDING_CALL"
        )
        return aggregate


__all__ = [
    "EmbeddingInvocationObserver",
    "MeteredOpenAIEmbedder",
    "is_exact_no_provider_call_usage",
    "is_exact_provider_reported_usage",
]
