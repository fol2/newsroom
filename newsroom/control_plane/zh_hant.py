"""Versioned Traditional-Chinese character-shape validation."""

from __future__ import annotations

import re

from opencc import OpenCC

ZH_HANT_HK_SHAPE_POLICY_VERSION = "newsroom.zh-hant-hk-shape.v8"
_S2T = OpenCC("s2t")
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
_HK_ACCEPTED_S2T_LEXEMES = (
    "獲准",
    "准許",
    "批准",
    "公布",
    "才",
    "群組",
    "群體",
    "社群",
    "了解",
    "核查",
    "平台",
)


def _without_accepted_ambiguous_lexemes(text: str) -> str:
    for lexeme in (
        *_TRADITIONAL_HOU_LEXEMES,
        *_TRADITIONAL_LI_LEXEMES,
        *_TRADITIONAL_GAN_LEXEMES,
        *_HK_ACCEPTED_S2T_LEXEMES,
    ):
        text = text.replace(lexeme, "")
    return re.sub(r"[零〇一二三四五六七八九十百千萬兩0-9]+里", "", text)


def contains_simplified_variant(text: str) -> bool:
    """Return true when Chinese text contains Simplified-only forms."""

    if not re.search(r"[\u3400-\u9fff]", text):
        return False
    remaining = _without_accepted_ambiguous_lexemes(text)
    return (
        _S2T.convert(remaining) != remaining
        or any(character in remaining for character in "后里干余于")
        or bool(re.search(r"[零〇一二三四五六七八九十百千萬兩0-9]+只", remaining))
    )
