"""Provider-native metering wrapper for OpenRouter Graphiti embeddings."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, TypeGuard

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
            or (
                prompt_tokens is not None
                and not _is_non_negative_int(prompt_tokens)
            )
            or not _is_non_negative_int(total_tokens)
            or not _is_non_negative_int(item_cost)
            or request["cost_reported"] is not True
            or request["outcome"] != "COMPLETE"
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
    return int((amount * Decimal(1_000_000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


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

    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate
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
        response = await self._delegate.client.embeddings.create(
            input=input_data,
            model=self._delegate.config.embedding_model,
        )
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
            int(item["total_tokens"])
            for item in self.requests
            if isinstance(item.get("total_tokens"), int)
        ]
        costs = [
            int(item["cost_usd_microunits"])
            for item in self.requests
            if isinstance(item.get("cost_usd_microunits"), int)
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


__all__ = ["MeteredOpenAIEmbedder", "is_exact_provider_reported_usage"]
