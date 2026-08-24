"""Versioned Traditional-Chinese character-shape validation."""

from __future__ import annotations

import hanzidentifier

ZH_HANT_HK_SHAPE_POLICY_VERSION = "newsroom.zh-hant-hk-shape.v2"


def contains_simplified_variant(text: str) -> bool:
    """Return true when Chinese text is not wholly valid Traditional Chinese."""

    return hanzidentifier.has_chinese(text) and not hanzidentifier.is_traditional(text)
