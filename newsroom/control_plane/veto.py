"""Fail-closed public-effect veto for the private editorial beta."""

from __future__ import annotations

from pathlib import Path

FORBIDDEN_INTENTS = frozenset(
    {
        "AUTO_PUBLISH",
        "TARGET_OPERATION",
        "PUBLIC_DISPATCH",
        "PRODUCTION_MUTATION",
        "IAP",
        "PUBLICATION_ADMISSION",
    }
)


class VetoError(ValueError):
    """The deterministic boundary refused a public or production effect."""


def refuse_public_effect(intent: str) -> None:
    if intent in FORBIDDEN_INTENTS:
        raise VetoError(f"public effect refused: {intent}")


def assert_private_store(path: str) -> str:
    parsed = Path(path)
    name = parsed.name.lower()
    parts = {part.lower() for part in parsed.parts}
    if "news_pool.sqlite3" in name or name == "production.sqlite3":
        raise VetoError("store must not alias production or news_pool")
    if "production" in parts:
        raise VetoError("store must not alias production or news_pool")
    return path
