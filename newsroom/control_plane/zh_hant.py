"""Versioned Traditional-Chinese character-shape validation."""

from __future__ import annotations

import re
from importlib.resources import files

ZH_HANT_HK_SHAPE_POLICY_VERSION = "newsroom.zh-hant-hk-shape.v13"
_DISCOURSE_FILLER = re.compile(
    r"(?:^|[，,；;。])\s*(?:(?:整體|總體|簡單|簡要|概括|總括)(?:而言|來說)|"
    r"簡而言之)|"
    r"(?:^|[，,；;。])\s*(?:由此|因此)(?:可見|可知)|"
    r"(?:^|[，,；;。])\s*說到底|"
    r"(?:^|[，,；;。])\s*(?:歸根究底|眾所周知)|"
    r"(?:^|[，,；;。])\s*[\u3400-\u9fff]{0,6}(?:話說回來|话说回来|"
    r"不言而喻|而言|而論|而论|來說|来说|到底|究底|周知|看來|看来|實際上|实际上)|"
    r"(?:^|[，,；;。])\s*(?:毫無疑問|毫无疑问|總括來講|总括来讲)|"
    r"(?:^|[，,；;。])\s*值得(?:留意|注意|一提)|"
    r"總而言之|總的來說|放眼未來|時間會證明"
)


def contains_discourse_filler(text: str) -> bool:
    return bool(_DISCOURSE_FILLER.search(text))


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
    "舞台",
    "月台",
    "港台",
    "窗台",
    "擂台",
    "露台",
    "炮台",
    "新台幣",
    "台北",
    "高峰會",
    "周一",
    "周二",
    "周三",
    "周四",
    "周五",
    "周六",
    "周日",
    "周末",
    "周年",
    "搜集",
    "人口回流",
    "回流英國",
    "回流香港",
    "高峰期",
    "每周",
    "查核",
    "控制程序",
)
_HK_ACCEPTED_AMBIGUOUS_CHARACTERS = frozenset("峰布家")
_SIMPLIFIED_EXCLUSIVE_CHARACTERS = frozenset(
    source
    for line in (
        files("opencc")
        .joinpath("dictionary/STCharacters.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    if line and not line.startswith("#")
    for source, targets in (line.split("\t", 1),)
    if source not in targets.split()
)
_SIMPLIFIED_CONTEXT_PHRASES = frozenset(
    source
    for line in (
        files("opencc")
        .joinpath("dictionary/STPhrases.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    if line and not line.startswith("#")
    for source, targets in (line.split("\t", 1),)
    if len(source) > 1 and source not in targets.split()
)
_MAX_SIMPLIFIED_CONTEXT_PHRASE_LENGTH = max(
    map(len, _SIMPLIFIED_CONTEXT_PHRASES), default=0
)
_SIMPLIFIED_CONTEXT_PATTERNS = (
    re.compile(r"(?:碗|食|吃|煮|炒|湯|汤|拉)面|面(?:條|条)"),
    re.compile(r"(?:一|兩|两|幾|几|這|这|那|同)伙(?:人|匪|賊|贼)?|伙伴"),
    re.compile(r"舍(?:得|棄|弃)|不舍|施舍|割舍"),
    re.compile(r"包扎|扎(?:實|实)|駐扎|驻扎"),
    re.compile(r"制造|占用|征收|放松|涂改|谷物|手表|云端|系上|(?:不)?适合|准确|明确"),
)


def _without_accepted_ambiguous_lexemes(text: str) -> str:
    for lexeme in (
        *_TRADITIONAL_HOU_LEXEMES,
        *_TRADITIONAL_LI_LEXEMES,
        *_TRADITIONAL_GAN_LEXEMES,
        *_HK_ACCEPTED_S2T_LEXEMES,
    ):
        text = text.replace(lexeme, "")
    text = "".join(
        character
        for character in text
        if character not in _HK_ACCEPTED_AMBIGUOUS_CHARACTERS
    )
    return re.sub(r"[零〇一二三四五六七八九十百千萬兩0-9]+里", "", text)


def contains_simplified_variant(text: str) -> bool:
    """Return true when Chinese text contains Simplified-only forms."""

    if not re.search(r"[\u3400-\u9fff]", text):
        return False
    remaining = _without_accepted_ambiguous_lexemes(text)
    return (
        any(character in _SIMPLIFIED_EXCLUSIVE_CHARACTERS for character in remaining)
        or any(
            remaining[start:end] in _SIMPLIFIED_CONTEXT_PHRASES
            for start in range(len(remaining))
            for end in range(
                start + 2,
                min(
                    len(remaining),
                    start + _MAX_SIMPLIFIED_CONTEXT_PHRASE_LENGTH,
                )
                + 1,
            )
        )
        or any(pattern.search(remaining) for pattern in _SIMPLIFIED_CONTEXT_PATTERNS)
        or any(character in remaining for character in "后里干余于万叶")
        or bool(re.search(r"[零〇一二三四五六七八九十百千萬兩0-9]+只", remaining))
    )


def contains_non_han_letter(text: str) -> bool:
    """Return true for alphabetic scripts outside the governed Han inventory."""

    return any(
        character.isalpha() and not "\u3400" <= character <= "\u9fff"
        for character in text
    )
