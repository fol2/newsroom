"""Public source/check/discovery/extraction authority facade for Increment 4A."""

from __future__ import annotations

from ._extraction_system import (
    GovernedExtraction,
    GovernedExtractionAuthoritySystem,
    open_governed_extraction_authority_system,
)

__all__ = [
    "GovernedExtraction",
    "GovernedExtractionAuthoritySystem",
    "open_governed_extraction_authority_system",
]
