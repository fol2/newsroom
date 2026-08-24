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
    for request in requests:
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
        request_tokens += total_tokens
        request_cost += item_cost
    return request_tokens == embedding_tokens and request_cost == cost


def _integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
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
        self.requests.append(request)
        observer_token = (
            None
            if self._invocation_observer is None
            else self._invocation_observer.before_embedding_invocation(
                provider="openrouter",
                model=self._delegate.config.embedding_model,
                input_data=input_data,
            )
        )
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
        all_costs_reported = bool(self.requests) and len(costs) == len(self.requests)
        all_tokens_reported = bool(self.requests) and len(token_values) == len(self.requests)
        if all_costs_reported and all_tokens_reported:
            basis = "PROVIDER_REPORTED"
        elif self.requests:
            basis = "PROVIDER_PARTIALLY_UNREPORTED"
        else:
            basis = "NO_EMBEDDING_CALL"
        return {
            "requests": list(self.requests),
            "request_count": len(self.requests),
            "embedding_tokens": sum(token_values),
            "cost_usd_microunits": sum(costs),
            "usage_basis": basis,
        }


__all__ = [
    "EmbeddingInvocationObserver",
    "MeteredOpenAIEmbedder",
    "is_exact_provider_reported_usage",
]
