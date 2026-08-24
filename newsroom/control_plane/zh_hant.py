"""Versioned Traditional-Chinese character-shape validation."""

from __future__ import annotations

import hanzidentifier
from opencc import OpenCC

ZH_HANT_HK_SHAPE_POLICY_VERSION = "newsroom.zh-hant-hk-shape.v3"
_SIMPLIFIED_TO_TRADITIONAL = OpenCC("s2tw")
_HK_ACCEPTED_VARIANTS = str.maketrans({"臺": "台", "裡": "裏"})


def _normalise_hk_variants(text: str) -> str:
    return text.translate(_HK_ACCEPTED_VARIANTS).replace("公佈", "公布")


def contains_simplified_variant(text: str) -> bool:
    """Return true when Chinese text is not wholly valid Traditional Chinese."""

    if not hanzidentifier.has_chinese(text):
        return False
    if not hanzidentifier.is_traditional(text):
        return True
    converted = _SIMPLIFIED_TO_TRADITIONAL.convert(text)
    return _normalise_hk_variants(text) != _normalise_hk_variants(converted)
