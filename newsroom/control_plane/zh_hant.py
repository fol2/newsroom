"""Versioned Traditional-Chinese character-shape validation."""

from __future__ import annotations

import re

import hanzidentifier

ZH_HANT_HK_SHAPE_POLICY_VERSION = "newsroom.zh-hant-hk-shape.v5"
_HK_ACCEPTED_CHARACTER_VARIANTS = str.maketrans({"着": "著"})
_TRADITIONAL_HOU_LEXEMES = ("皇后", "太后", "王后", "后羿", "后土", "后稷")
_TRADITIONAL_LI_LEXEMES = (
    "公里",
    "英里",
    "海里",
    "里程",
    "里數",
    "鄰里",
    "萬里",
    "千里",
    "百里",
    "故里",
    "里長",
    "里巷",
    "里弄",
)
_TRADITIONAL_GAN_LEXEMES = (
    "干涉",
    "干預",
    "干犯",
    "干戈",
    "干支",
    "天干",
    "若干",
    "相干",
    "無干",
    "干政",
)


def _without_accepted_ambiguous_lexemes(text: str) -> str:
    for lexeme in (
        *_TRADITIONAL_HOU_LEXEMES,
        *_TRADITIONAL_LI_LEXEMES,
        *_TRADITIONAL_GAN_LEXEMES,
    ):
        text = text.replace(lexeme, "")
    return re.sub(r"[零〇一二三四五六七八九十百千萬兩0-9]+里", "", text)


def contains_simplified_variant(text: str) -> bool:
    """Return true when Chinese text contains Simplified-only forms."""

    if not hanzidentifier.has_chinese(text):
        return False
    if not hanzidentifier.is_traditional(
        text.translate(_HK_ACCEPTED_CHARACTER_VARIANTS)
    ):
        return True
    remaining = _without_accepted_ambiguous_lexemes(text)
    return any(character in remaining for character in "后里干")
