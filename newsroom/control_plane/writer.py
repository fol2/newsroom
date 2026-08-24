"""CONT writer: Grok Build CLI, then cursor-agent CLI. Graphiti is never the writer."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal, Protocol

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.control_plane.child_environment import unprivileged_child_environment
from newsroom.control_plane.editorial import StoryCandidateRecord
from newsroom.control_plane.evidence import EvidencePackage
from newsroom.control_plane.zh_hant import (
    contains_discourse_filler,
    contains_non_han_letter,
    contains_simplified_variant,
)

GROK_BIN = os.environ.get("NEWSROOM_GROK_BIN", "/Users/jamesto/.grok/bin/grok")
CURSOR_AGENT_BIN = os.environ.get(
    "NEWSROOM_CURSOR_AGENT_BIN", "/Users/jamesto/.local/bin/cursor-agent"
)
WRITER_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "body": {"type": "string"},
        "evidence_links": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "governed_claim_id": {"type": "string"},
                    "rendered_assertion": {"type": "string"},
                },
                "required": [
                    "governed_claim_id",
                    "rendered_assertion",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "body", "evidence_links"],
    "additionalProperties": False,
}
_PROMPT = (
    "你係 Newsroom 嘅 CONT 原創記者，唔係 Graphiti。"
    "用香港繁體中文寫一篇已經完成嘅未出版新聞稿。"
    "JSON 嘅 title 同 body 必須係完稿正文，唔係計劃、核對清單、任務說明或工作備註。"
    "標題唔可以「正在」「搜集」「查核」「先查」開頭，亦唔可以係「新聞稿任務」。"
    "正文唔可以「先查」「先核」「正在核」開頭。"
    "必須原創改寫，唔好複製來源標題或 dateline 模板。"
    "唔准 AUTO_PUBLISH，唔准當公開發行。"
    "只輸出 JSON 物件，欄位 title 同 body。"
    "另外輸出 evidence_links 陣列；每項必須使用以下 approved_governed_claims "
    "入面完全相同嘅 governed_claim_id 同 rendered_assertion。"
    "標題只可以係「【未出版】」加一個 approved claim；"
    "正文只可以係「本報根據已核實證據報道：」加 approved claims，claims 之間用「；」。"
    "唔可以自行加事實、名字、數字、日期、引句、因果或肯定程度。"
)
_TITLE_RESIDUE_PREFIXES = ("正在", "搜集", "查核", "先查", "草稿：")
_TITLE_RESIDUE_EXACT = frozenset({"新聞稿任務", "Newsroom 原創稿"})
_BODY_RESIDUE_PREFIXES = ("先查", "先核", "正在核")
_FILLER_MARKERS = (
    "總括而言",
    "總而言之",
    "值得注意的是",
    "放眼未來",
    "時間會證明",
    "草稿：",
)
_CHINESE_NUMERAL_FACT = re.compile(
    r"(?:百分之|星期|第)?[零〇一二三四五六七八九十百千萬万億亿兆兩两"
    r"壹貳贰參叁肆伍陸陆柒捌玖拾佰仟ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]+"
    r"(?:[\u3400-\u9fff])?"
)
_QUANTIFIED_FACT = re.compile(
    r"(?P<number>[+\-−]?\d+(?:[.,]\d+)*(?:%|％)?|"
    r"[零〇一二三四五六七八九十百千萬万億亿兆兩两壹貳贰參叁肆伍陸陆柒捌玖拾佰仟"
    r"ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ①-⑳⑴-⒇㉑-㊿]+)\s*"
    r"(?P<unit>平方公里|平方米|公頃|英畝|港元|公噸|公斤|公里|分鐘|分钟|"
    r"小時|小时|星期|個月|个月|階段|阶段|百分比|%|％|元|噸|吨|米|日|天|"
    r"月|年|期|級|级|批|次|成|倍|間|间|部|條|条|所|座|架|輛|辆|艘|層|层|"
    r"項|项|個|个|名|位|戶|户|宗|件|℃|℉|°C|°F)"
    r"(?P<object>[\u3400-\u9fff]{1,8})?(?=$|[，,。；;：:\s])"
)
_NUMBER_ADJACENT_HAN_FACT = re.compile(
    r"(?P<number>第?(?:[+\-−]?\d+(?:[.,]\d+)*(?:%|％)?|"
    r"[零〇一二三四五六七八九十百千萬万億亿兆兩两壹貳贰參叁肆伍陸陆柒捌玖拾佰仟"
    r"ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ①-⑳⑴-⒇㉑-㊿]+))"
    r"\s*(?P<unit>[\u3400-\u9fff]{1,8})(?=$|[，,。；;：:\s])"
)
_CURRENCY_FACT = re.compile(
    r"(?P<currency>HK\$|US\$|£|€|¥|￥|\$)\s*"
    r"(?P<number>[+\-−]?\d+(?:[.,]\d+)*)|"
    r"(?P<number_after>[+\-−]?\d+(?:[.,]\d+)*)\s*"
    r"(?P<currency_after>港元|英鎊|歐元|美元|日圓|人民幣)"
)
_RELATIVE_TIME_FACT = re.compile(
    r"\b(?:today|tomorrow|yesterday|tonight|this\s+(?:morning|afternoon|evening|"
    r"week|month|year)|next\s+(?:week|month|year)|last\s+(?:week|month|year)|"
    r"day\s+after\s+tomorrow|end\s+of\s+(?:the\s+)?(?:month|year)|year[ -]end)\b|"
    r"今日|今天|明日|聽日|听日|昨日|尋日|寻日|下星期|下週|下周|本星期|"
    r"本週|本周|上星期|上週|上周|本月|下月|上月|今年|明年|去年|今早|"
    r"今朝|今晚|今午|後日|后日|月底|月尾|年底|年尾|即日|當日|当日|"
    r"翌日|翌晨|翌晚|本季|今季|下季|上季|本季度|下季度|上季度|清晨|"
    r"早上|上午|中午|下午|傍晚|黃昏|黄昏|晚間|晚间|深夜",
    re.IGNORECASE,
)


def _remove_exact_expressions(text: str, expressions: tuple[str, ...]) -> str:
    for expression in sorted(expressions, key=len, reverse=True):
        text = text.replace(expression, "")
    return text


def _quantified_relations(text: str) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (
            match.group("number"),
            match.group("unit"),
            match.group("object") or "",
        )
        for match in _QUANTIFIED_FACT.finditer(text)
    )


def _number_adjacent_han_relations(text: str) -> tuple[tuple[str, str], ...]:
    return tuple(
        (match.group("number"), match.group("unit"))
        for match in _NUMBER_ADJACENT_HAN_FACT.finditer(text)
    )


def _currency_relations(text: str) -> tuple[tuple[str, str], ...]:
    return tuple(
        (
            match.group("currency") or match.group("currency_after"),
            match.group("number") or match.group("number_after"),
        )
        for match in _CURRENCY_FACT.finditer(text)
    )


def _unicode_currency_relations(text: str) -> tuple[tuple[str, str], ...]:
    relations: list[tuple[str, str]] = []
    for index, character in enumerate(text):
        if unicodedata.category(character) != "Sc":
            continue
        before = re.search(r"[+\-−]?\d+(?:[.,]\d+)*\s*$", text[:index])
        after = re.match(r"\s*([+\-−]?\d+(?:[.,]\d+)*)", text[index + 1 :])
        if before is not None:
            relations.append((character, before.group(0).strip()))
        elif after is not None:
            relations.append((character, after.group(1)))
    return tuple(relations)


def _unicode_number_relations(text: str) -> tuple[tuple[str, float], ...]:
    return tuple(
        (character, unicodedata.numeric(character))
        for character in text
        if unicodedata.category(character).startswith("N")
    )


def _has_unicode_quote_delimiter(text: str) -> bool:
    for character in text:
        name = unicodedata.name(character, "")
        if (
            unicodedata.category(character) in {"Pi", "Pf"}
            or "QUOTATION MARK" in name
            or "ANGLE BRACKET ORNAMENT" in name
        ):
            return True
    return False


def _unicode_quoted_contents(text: str) -> tuple[str, ...]:
    positions = tuple(
        index
        for index, character in enumerate(text)
        if _has_unicode_quote_delimiter(character)
    )
    return tuple(
        text[start + 1 : end]
        for start, end in zip(positions[::2], positions[1::2], strict=False)
        if start + 1 < end
    )


def _unicode_quotes_are_balanced(text: str) -> bool:
    return sum(_has_unicode_quote_delimiter(character) for character in text) % 2 == 0


def _signed_number_relations(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[+\-−]\d+(?:[.,]\d+)*", text))


def _numeric_han_context(text: str) -> str:
    match = re.search(
        r"\d|[零〇一二三四五六七八九十百千萬万億亿兆兩两壹貳贰參叁肆伍陸陆"
        r"柒捌玖拾佰仟ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ①-⑳⑴-⒇㉑-㊿]",
        text,
    )
    if match is None or not re.search(r"[\u3400-\u9fff]", text):
        return ""
    return "".join(
        character
        for character in text
        if character.isdigit() or "\u3400" <= character <= "\u9fff"
    )


_SYSTEMIC_MARKERS = (
    "authentication",
    "not logged in",
    "login required",
    "unauthorized",
    "forbidden",
    "invalid api key",
    "api key invalid",
    "permission denied",
    "invalid model",
    "invalid command",
    "configuration",
    "quota",
    "rate limit",
    "rate-limit",
    "rate_limit_exceeded",
    "rate_limit_error",
    "too many requests",
    "payment required",
    "billing required",
    "no such file",
    "not found",
)

WriterRoute = Literal["PRIMARY", "FALLBACK"]
WriterFailureClass = Literal[
    "FALLBACK_ELIGIBLE", "SYSTEMIC", "CANDIDATE_LOCAL", "UNKNOWN"
]
ORIGINALITY_ALIGNMENT_MIN_SOURCE_COVERAGE = 0.8


@dataclass(frozen=True, slots=True)
class WriterEvidenceLink:
    governed_claim_id: str
    rendered_assertion: str


@dataclass(frozen=True, slots=True)
class WriterValidatorResult:
    validator: str
    result: Literal["PASS", "FAIL"]
    reason_code: str


@dataclass(frozen=True, slots=True)
class WriterCopy:
    title: str
    body: str
    writer_id: str
    evidence_package_digest: str = ""
    evidence_links: tuple[WriterEvidenceLink, ...] = ()


@dataclass(frozen=True, slots=True)
class WriterRouteProbeResult:
    executable_ok: bool
    authentication_ok: bool
    configuration_ok: bool
    provider_available: bool
    provider_dispatched: bool
    provider_receipt_reference: str | None


class WriterDispatchError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        failure_class: WriterFailureClass,
        reason_code: str,
    ) -> None:
        super().__init__(message)
        self.failure_class = failure_class
        self.reason_code = reason_code


class CliProcessError(RuntimeError):
    def __init__(self, message: str, *, provider_status: int | None) -> None:
        super().__init__(message)
        self.provider_status = provider_status


class WriterPort(Protocol):
    writer_id: str

    def write(
        self, candidate: StoryCandidateRecord, package: EvidencePackage
    ) -> WriterCopy: ...


class DispatchWriterPort(Protocol):
    writer_id: str

    def dispatch(
        self,
        candidate: StoryCandidateRecord,
        package: EvidencePackage,
        *,
        route: WriterRoute,
    ) -> WriterCopy: ...


class FixtureWriter:
    writer_id = "evaluation-fixture-writer-v1"

    def write(
        self, candidate: StoryCandidateRecord, package: EvidencePackage
    ) -> WriterCopy:
        headline_claim = next(
            claim for claim in package.governed_claims if claim.claim_role == "HEADLINE"
        )
        body_claims = tuple(
            claim
            for claim in package.governed_claims
            if claim.claim_role == "SUBSTANTIVE"
        )
        body = "本報根據已核實證據報道：" + "；".join(
            claim.rendered_assertion_zh_hant_hk for claim in body_claims
        )
        return WriterCopy(
            title=f"【未出版】{headline_claim.rendered_assertion_zh_hant_hk}",
            body=body,
            writer_id=self.writer_id,
            evidence_package_digest=package.digest,
            evidence_links=tuple(
                WriterEvidenceLink(
                    governed_claim_id=claim.claim_id,
                    rendered_assertion=claim.rendered_assertion_zh_hant_hk,
                )
                for claim in (headline_claim, *body_claims)
            ),
        )


def _prompt(candidate: StoryCandidateRecord, package: EvidencePackage) -> str:
    approved_claims = [
        {
            "governed_claim_id": claim.claim_id,
            "claim": claim.claim,
            "supporting_excerpt": claim.supporting_excerpt,
            "rendered_assertion": claim.rendered_assertion_zh_hant_hk,
            "claim_role": claim.claim_role,
            "status": claim.status.value,
            "attribution": claim.attribution,
            "named_entities": list(claim.named_entities),
            "rendered_named_entities": list(claim.rendered_named_entities),
            "quotations": list(claim.quotations),
            "certainty": claim.certainty,
            "originality_basis": claim.originality_basis,
            "originality_policy_version": claim.originality_policy_version,
        }
        for claim in package.governed_claims
    ]
    return (
        f"{_PROMPT}\n題旨：{candidate.headline}\n"
        f"approved_governed_claims：{json.dumps(approved_claims, ensure_ascii=False)}"
        "\n證據：\n" + "\n---\n".join(package.passages)
    )


def _extract_json(raw: str) -> str:
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("writer returned no JSON object")
    return raw[start : end + 1]


def _copy_fields(
    payload: object,
) -> tuple[str, str, tuple[WriterEvidenceLink, ...]] | None:
    if not isinstance(payload, dict):
        return None
    title = payload.get("title")
    body = payload.get("body")
    if isinstance(title, str) and isinstance(body, str):
        raw_links = payload.get("evidence_links", [])
        if not isinstance(raw_links, list):
            return None
        links: list[WriterEvidenceLink] = []
        for item in raw_links:
            if not isinstance(item, dict):
                return None
            claim_id = item.get("governed_claim_id")
            rendered = item.get("rendered_assertion")
            if not isinstance(claim_id, str) or not isinstance(rendered, str):
                return None
            links.append(WriterEvidenceLink(claim_id.strip(), rendered.strip()))
        return title.strip(), body.strip(), tuple(links)
    return None


def _finished_copy(
    title: str,
    body: str,
    links: tuple[WriterEvidenceLink, ...] = (),
) -> tuple[str, str, tuple[WriterEvidenceLink, ...]]:
    if not title or not body:
        raise RuntimeError("writer JSON missing title or body")
    if title.startswith(_TITLE_RESIDUE_PREFIXES) or title in _TITLE_RESIDUE_EXACT:
        raise RuntimeError("writer returned planning residue, not unpublished copy")
    if body.startswith(_BODY_RESIDUE_PREFIXES):
        raise RuntimeError("writer returned planning residue, not unpublished copy")
    return title, body, links


def _parse_copy(raw: str) -> tuple[str, str, tuple[WriterEvidenceLink, ...]]:
    payload = json.loads(_extract_json(raw))
    found = _copy_fields(payload)
    if found:
        return _finished_copy(*found)
    for key in ("structured_output", "structuredOutput"):
        found = _copy_fields(payload.get(key))
        if found:
            return _finished_copy(*found)
    text = payload.get("text")
    if isinstance(text, str) and text.strip():
        found = _copy_fields(json.loads(_extract_json(text)))
        if found:
            return _finished_copy(*found)
    raise RuntimeError("writer JSON missing title or body")


def validate_writer_copy(
    copy: WriterCopy, package: EvidencePackage
) -> tuple[WriterValidatorResult, ...]:
    text = f"{copy.title}\n{copy.body}"
    results: list[WriterValidatorResult] = []

    def check(name: str, passed: bool, reason: str) -> None:
        results.append(
            WriterValidatorResult(name, "PASS" if passed else "FAIL", reason)
        )

    check(
        "EVIDENCE_PACKAGE_BINDING",
        copy.evidence_package_digest == package.digest,
        "EVIDENCE_PACKAGE_DRIFT",
    )
    text_without_approved_entities = text
    for claim in package.governed_claims:
        for entity in claim.named_entities:
            text_without_approved_entities = text_without_approved_entities.replace(
                entity, ""
            )
    check(
        "COMPLETED_ORIGINAL_ZH_HANT_HK_REPORT",
        bool(copy.title.strip() and copy.body.strip())
        and any("\u3400" <= character <= "\u9fff" for character in text)
        and not contains_non_han_letter(text_without_approved_entities)
        and not contains_simplified_variant(text_without_approved_entities),
        "NOT_COMPLETED_ZH_HANT_HK_REPORT",
    )
    check(
        "NO_PLANNING_RESIDUE_OR_FILLER",
        not copy.title.removeprefix("【未出版】").startswith(_TITLE_RESIDUE_PREFIXES)
        and copy.title.removeprefix("【未出版】") not in _TITLE_RESIDUE_EXACT
        and not copy.body.startswith(_BODY_RESIDUE_PREFIXES)
        and not any(marker in text for marker in _FILLER_MARKERS)
        and not contains_discourse_filler(text),
        "PLANNING_RESIDUE_OR_FILLER",
    )
    check(
        "NO_RAW_PROPOSED_GRAPHITI_CONTEXT",
        "PROPOSED Graphiti" not in text and "graphiti_workspace" not in text,
        "RAW_PROPOSED_GRAPHITI_CONTEXT",
    )
    governed_claims = {claim.claim_id: claim for claim in package.governed_claims}
    exact_links = bool(copy.evidence_links) and all(
        (governed := governed_claims.get(link.governed_claim_id)) is not None
        and link.rendered_assertion == governed.rendered_assertion_zh_hant_hk
        and link.rendered_assertion in text
        for link in copy.evidence_links
    )
    check(
        "CLAIM_EVIDENCE_LINKS",
        exact_links,
        "UNSUPPORTED_MATERIAL_CLAIM",
    )
    linked_ids = tuple(link.governed_claim_id for link in copy.evidence_links)
    headline_claims = tuple(
        claim for claim in package.governed_claims if claim.claim_role == "HEADLINE"
    )
    substantive_claims = tuple(
        claim
        for claim in package.governed_claims
        if claim.claim_role == "SUBSTANTIVE"
        and claim.claim in package.substantive_new_information
    )
    rendered_assertions = tuple(
        claim.rendered_assertion_zh_hant_hk for claim in package.governed_claims
    )
    exact_role_structure = (
        len(rendered_assertions) == len(set(rendered_assertions))
        and len(headline_claims) == 1
        and copy.title
        == f"【未出版】{headline_claims[0].rendered_assertion_zh_hant_hk}"
        and copy.body.startswith("本報根據已核實證據報道：")
        and copy.body.count("本報根據已核實證據報道：") == 1
        and all(
            copy.title.count(claim.rendered_assertion_zh_hant_hk) == 1
            and copy.body.count(claim.rendered_assertion_zh_hant_hk) == 0
            if claim.claim_role == "HEADLINE"
            else copy.title.count(claim.rendered_assertion_zh_hant_hk) == 0
            and copy.body.count(claim.rendered_assertion_zh_hant_hk) == 1
            for claim in package.governed_claims
        )
    )
    check(
        "ROLE_SPECIFIC_EXACT_ONCE_STRUCTURE",
        exact_role_structure,
        "DUPLICATE_OR_MISPLACED_GOVERNED_CLAIM",
    )
    check(
        "REQUIRED_GOVERNED_CLAIM_COVERAGE",
        len(linked_ids) == len(set(linked_ids))
        and set(linked_ids) == set(governed_claims)
        and len(headline_claims) == 1
        and headline_claims[0].rendered_assertion_zh_hant_hk in copy.title
        and bool(substantive_claims)
        and all(
            claim.rendered_assertion_zh_hant_hk in copy.body
            for claim in substantive_claims
        ),
        "REQUIRED_GOVERNED_CLAIM_MISSING",
    )
    narrative_segments = tuple(
        segment.strip() for segment in re.split(r"\n+", text) if segment.strip()
    )
    check(
        "CENTRAL_CLAIM_COVERAGE",
        bool(copy.evidence_links)
        and all(
            any(link.rendered_assertion in segment for link in copy.evidence_links)
            for segment in narrative_segments
        ),
        "UNMAPPED_CENTRAL_CLAIM",
    )
    allowed_scaffolding = (
        "【未出版】",
        "本報根據已核實證據報道：",
    )
    bounded_segments = True
    for segment in narrative_segments:
        residue = segment
        for link in sorted(
            copy.evidence_links, key=lambda item: -len(item.rendered_assertion)
        ):
            residue = residue.replace(link.rendered_assertion, "")
        for scaffold in allowed_scaffolding:
            residue = residue.replace(scaffold, "")
        residue = re.sub(r"[\s，,；;：:、（）()【】《》〈〉—-]+", "", residue)
        if residue:
            bounded_segments = False
            break
    check(
        "GOVERNED_CLAIM_ENTAILMENT_BOUNDARY",
        exact_links and exact_role_structure and bounded_segments,
        "UNSUPPORTED_CLAIM_RESIDUE",
    )
    source_expressions = (*package.passages,) + tuple(
        value.strip()
        for item in package.passages
        for value in re.split(r"(?<=[.!?。！？；;])|\n+", item)
        if value.strip()
    )
    numeric_expression_patterns = (
        re.compile(r"\d+(?:(?:[年月日時时分秒號号點点])|(?:[.,:/-]\d+)|\d+)+"),
        re.compile(
            r"(?:[零〇一二三四五六七八九十百千萬万億亿兆兩两]+"
            r"(?:年|月|日|號|号|時|时|分|秒|點|点))+"
        ),
        re.compile(
            r"[零〇一二三四五六七八九十百千萬万億亿兆兩两]+\s*"
            r"(?:港元|元|人|宗|件|公噸|噸|吨|公斤|公里|米|分鐘|分钟|小時|"
            r"小时|日|天|星期|個月|个月|年|戶|户|名|位|%|％)"
        ),
        re.compile(
            r"第?[零〇一二三四五六七八九十百千萬万億亿兆兩两]+\s*"
            r"(?:階段|阶段|間|间|批|次|項|项|個|个|所|座|架|輛|辆|艘|"
            r"層|层|期|級|级|成|倍)"
        ),
        re.compile(
            r"\d+(?:[.,]\d+)*\s*(?:%|％|minutes?|mins?|hours?|hrs?|days?|"
            r"weeks?|months?|years?|million|billion|trillion|people|cases?|"
            r"tonnes?|kilograms?|kilometres?|公里|米|分鐘|分钟|小時|小时|日|天|"
            r"星期|個月|个月|年|港元|元|人|宗|件|公噸|噸|吨|公斤|戶|户|名|位)",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:\d{1,2}\s+)?(?:January|February|March|April|May|June|July|"
            r"August|September|October|November|December)(?:\s+\d{1,2})?"
            r"(?:,?\s+\d{4})?",
            re.IGNORECASE,
        ),
        re.compile(r"[零〇一二三四五六七八九十百千萬万億亿兆兩两]+"),
    )
    approved_numeric_expressions = tuple(
        match.group(0)
        for claim in package.governed_claims
        for evidence_text in (claim.claim, claim.supporting_excerpt)
        for pattern in numeric_expression_patterns
        for match in pattern.finditer(evidence_text)
    ) + tuple(
        match.group(0)
        for claim in package.governed_claims
        for _source, target in claim.localised_factual_expressions
        for pattern in numeric_expression_patterns
        for match in pattern.finditer(target)
    )
    approved_overlap = (
        tuple(
            value
            for claim in package.governed_claims
            for value in (*claim.named_entities, *claim.quotations)
            if value
        )
        + approved_numeric_expressions
    )

    def normalise_originality(value: str) -> str:
        for approved in sorted(approved_overlap, key=len, reverse=True):
            value = value.replace(approved, "")
        return "".join(
            character.casefold() for character in value if character.isalnum()
        )

    normalised_draft = normalise_originality(text)
    copied_source_expression = any(
        sequence in normalised_draft
        for expression in source_expressions
        for normalised_expression in (normalise_originality(expression),)
        for sequence in (
            normalised_expression[index : index + 12]
            for index in range(max(0, len(normalised_expression) - 11))
        )
    )
    aligned_source_expression = any(
        len(normalised_expression) >= 4
        and sum(
            block.size
            for block in SequenceMatcher(
                None,
                normalised_expression,
                normalised_segment,
                autojunk=False,
            ).get_matching_blocks()
        )
        / len(normalised_expression)
        >= ORIGINALITY_ALIGNMENT_MIN_SOURCE_COVERAGE
        for expression in source_expressions
        for normalised_expression in (normalise_originality(expression),)
        for segment in narrative_segments
        for normalised_segment in (normalise_originality(segment),)
    )
    check(
        "ORIGINALITY_BOUNDARY",
        not copied_source_expression and not aligned_source_expression,
        "VERBATIM_SOURCE_EXPRESSION",
    )
    governed_text = "\n".join(
        value
        for claim in package.governed_claims
        for value in (claim.claim, claim.supporting_excerpt)
    )
    numbers = set(re.findall(r"\d+(?:[.,]\d+)*(?:%|％)?", text))
    governed_numbers = set(re.findall(r"\d+(?:[.,]\d+)*(?:%|％)?", governed_text))
    governed_numbers.update(
        number
        for claim in package.governed_claims
        for _source, target in claim.localised_factual_expressions
        for number in re.findall(r"\d+(?:[.,]\d+)*(?:%|％)?", target)
    )
    draft_numeric_expressions = {
        match.group(0)
        for pattern in numeric_expression_patterns
        for match in pattern.finditer(text)
    }
    claim_numeric_relations = all(
        _quantified_relations(source_without_localised)
        == _quantified_relations(rendered_without_localised)
        and _number_adjacent_han_relations(source_without_localised)
        == _number_adjacent_han_relations(rendered_without_localised)
        and _currency_relations(source_without_localised)
        == _currency_relations(rendered_without_localised)
        and _unicode_currency_relations(source_without_localised)
        == _unicode_currency_relations(rendered_without_localised)
        and _unicode_number_relations(source_without_localised)
        == _unicode_number_relations(rendered_without_localised)
        and _signed_number_relations(source_without_localised)
        == _signed_number_relations(rendered_without_localised)
        and _numeric_han_context(source_without_localised)
        == _numeric_han_context(rendered_without_localised)
        and tuple(
            match.group(0)
            for match in _CHINESE_NUMERAL_FACT.finditer(source_without_localised)
        )
        == tuple(
            match.group(0)
            for match in _CHINESE_NUMERAL_FACT.finditer(rendered_without_localised)
        )
        for claim in package.governed_claims
        for source_without_localised, rendered_without_localised in (
            (
                _remove_exact_expressions(
                    claim.claim,
                    tuple(
                        source
                        for source, _target in claim.localised_factual_expressions
                    ),
                ),
                _remove_exact_expressions(
                    claim.rendered_assertion_zh_hant_hk,
                    tuple(
                        target
                        for _source, target in claim.localised_factual_expressions
                    ),
                ),
            ),
        )
    )
    claim_relative_time_relations = all(
        tuple(
            match.group(0).casefold()
            for match in _RELATIVE_TIME_FACT.finditer(source_without_localised)
        )
        == tuple(
            match.group(0).casefold()
            for match in _RELATIVE_TIME_FACT.finditer(rendered_without_localised)
        )
        for claim in package.governed_claims
        for source_without_localised, rendered_without_localised in (
            (
                _remove_exact_expressions(
                    claim.claim,
                    tuple(
                        source
                        for source, _target in claim.localised_factual_expressions
                    ),
                ),
                _remove_exact_expressions(
                    claim.rendered_assertion_zh_hant_hk,
                    tuple(
                        target
                        for _source, target in claim.localised_factual_expressions
                    ),
                ),
            ),
        )
    )
    check(
        "NUMERIC_AND_DATE_FIDELITY",
        numbers.issubset(governed_numbers)
        and draft_numeric_expressions.issubset(set(approved_numeric_expressions))
        and claim_numeric_relations
        and claim_relative_time_relations,
        "UNSUPPORTED_NUMBER_OR_DATE",
    )
    quoted = {
        match
        for pattern in (
            r'"([^"\n]+)"',
            r"“([^”\n]+)”",
            r"「([^」\n]+)」",
            r"『([^』\n]+)』",
            r"‘([^’\n]+)’",
            r"〝([^〞\n]+)〞",
            r"﹁([^﹂\n]+)﹂",
            r"❝([^❞\n]+)❞",
            r"﹃([^﹄\n]+)﹄",
            r"«([^»\n]+)»",
            r"‹([^›\n]+)›",
            r"(?<![A-Za-z])'([^'\n]+)'(?![A-Za-z])",
        )
        for match in re.findall(pattern, text)
    }
    quoted.update(_unicode_quoted_contents(text))
    check(
        "QUOTE_FIDELITY",
        _unicode_quotes_are_balanced(text)
        and all(
            any(
                value in claim.quotations
                and claim.attribution in claim.rendered_assertion_zh_hant_hk
                and any(
                    value in segment and claim.attribution in segment
                    for segment in narrative_segments
                )
                for claim in package.governed_claims
            )
            for value in quoted
        ),
        "UNSUPPORTED_OR_UNATTRIBUTED_QUOTATION",
    )
    attribution_bound = all(
        claim.attribution in claim.rendered_assertion_zh_hant_hk
        and any(
            claim.rendered_assertion_zh_hant_hk in segment
            and claim.attribution in segment
            for segment in narrative_segments
        )
        for claim in package.governed_claims
        if claim.quotations or claim.status.value == "ATTRIBUTED_CLAIM_OR_OPINION"
    )
    check(
        "ATTRIBUTION_FIDELITY",
        attribution_bound,
        "REQUIRED_ATTRIBUTION_MISSING",
    )
    resolved_record_ids = {
        record_id for record_id, _digest in package.resolved_evidence_records
    }
    check(
        "CERTAINTY_FIDELITY",
        all(
            claim.certainty == "CONFIRMED"
            and claim.semantic_relation_evidence_id in resolved_record_ids
            for claim in package.governed_claims
        ),
        "CERTAINTY_EXCEEDS_EVIDENCE",
    )
    return tuple(results)


def _provider_control_status(message: str) -> int | None:
    lowered = message.lower()
    status = re.search(
        r"\b(?:http(?:\s*(?:status|error))?|status(?:\s+code)?|api\s*error|"
        r"provider\s+error|request\s+failed|writer\s+failed|error)"
        r"\s*[:=\[(]?\s*(401|402|403|429)\b",
        lowered,
    )
    if status:
        return int(status.group(1))
    machine_status = re.search(
        r'["\']?(?:status(?:\s*_?\s*code)?|code)["\']?\s*:\s*'
        r"(401|402|403|429)\b",
        lowered,
    )
    if machine_status:
        return int(machine_status.group(1))
    if re.fullmatch(r"\s*(?:401|402|403|429)\s*", lowered):
        return int(lowered.strip())
    return None


def _failure(
    message: str, *, provider_status: int | None = None
) -> WriterDispatchError:
    lowered = message.lower()
    if (
        provider_status in {401, 402, 403, 429}
        or _provider_control_status(message) in {401, 402, 403, 429}
        or any(marker in lowered for marker in _SYSTEMIC_MARKERS)
    ):
        return WriterDispatchError(
            message,
            failure_class="SYSTEMIC",
            reason_code="SYSTEMIC_PROVIDER_FAILURE",
        )
    return WriterDispatchError(
        message,
        failure_class="FALLBACK_ELIGIBLE",
        reason_code="PRIMARY_OUTPUT_UNUSABLE",
    )


def _run(command: tuple[str, ...], *, timeout: int, cwd: str | None = None) -> str:
    name = os.path.basename(command[0])
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=unprivileged_child_environment(),
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{name} writer timed out") from None
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise CliProcessError(
            f"{name} writer failed: {detail}".rstrip(),
            provider_status=_provider_control_status(detail),
        )
    if not result.stdout.strip():
        raise RuntimeError("writer returned empty stdout")
    return result.stdout


def run_grok_cli(prompt: str) -> str:
    schema = json.dumps(WRITER_SCHEMA, ensure_ascii=False)
    with tempfile.TemporaryDirectory(prefix="newsroom-grok-writer-") as cwd:
        path = os.path.join(cwd, "prompt.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(prompt)
        return _run(
            (
                GROK_BIN,
                "--prompt-file",
                path,
                "-m",
                "grok-4.6",
                "--json-schema",
                schema,
                "--disable-web-search",
                "--sandbox",
                "read-only",
                "--permission-mode",
                "plan",
                "--tools",
                "",
                "--deny",
                "*",
                "--no-plan",
                "--max-turns",
                "3",
                "--no-subagents",
                "--reasoning-effort",
                "low",
            ),
            timeout=300,
            cwd=cwd,
        )


def run_cursor_agent_cli(prompt: str) -> str:
    return _run(
        (
            CURSOR_AGENT_BIN,
            "--print",
            "--mode",
            "ask",
            "--output-format",
            "text",
            "--sandbox",
            "enabled",
            "--trust",
            prompt,
        ),
        timeout=180,
    )


class CliChainWriter:
    """Primary: Grok Build CLI. Fallback: cursor-agent CLI."""

    writer_id = "grok-build-cli-cont-writer"

    def __init__(
        self,
        *,
        primary: Callable[[str], str] | None = None,
        fallback: Callable[[str], str] | None = None,
    ) -> None:
        self._primary = primary or run_grok_cli
        self._fallback = fallback or run_cursor_agent_cli

    def write(
        self, candidate: StoryCandidateRecord, package: EvidencePackage
    ) -> WriterCopy:
        try:
            return self.dispatch(candidate, package, route="PRIMARY")
        except WriterDispatchError as exc:
            if exc.failure_class == "SYSTEMIC":
                raise
            return self.dispatch(candidate, package, route="FALLBACK")

    def dispatch(
        self,
        candidate: StoryCandidateRecord,
        package: EvidencePackage,
        *,
        route: WriterRoute,
    ) -> WriterCopy:
        prompt = _prompt(candidate, package)
        invoke = self._primary if route == "PRIMARY" else self._fallback
        writer_id = (
            self.writer_id if route == "PRIMARY" else "cursor-agent-cli-cont-writer"
        )
        try:
            title, body, links = _parse_copy(invoke(prompt))
        except WriterDispatchError:
            raise
        except CliProcessError as exc:
            raise _failure(str(exc), provider_status=exc.provider_status) from exc
        except (
            RuntimeError,
            json.JSONDecodeError,
            OSError,
            subprocess.TimeoutExpired,
        ) as exc:
            raise _failure(str(exc)) from exc
        return WriterCopy(
            title=title,
            body=body,
            writer_id=writer_id,
            evidence_package_digest=package.digest,
            evidence_links=links,
        )


def grok_cli_ready() -> bool:
    return shutil.which(GROK_BIN) is not None or os.path.isfile(GROK_BIN)


def cursor_agent_cli_ready() -> bool:
    return shutil.which(CURSOR_AGENT_BIN) is not None or os.path.isfile(
        CURSOR_AGENT_BIN
    )


def prove_grok_cli() -> None:
    result = subprocess.run(
        (GROK_BIN, "version"),
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
        env=unprivileged_child_environment(),
    )
    if result.returncode != 0 or "grok" not in result.stdout.lower():
        raise RuntimeError("Grok Build CLI is not logged in or not runnable")


def probe_grok_writer_route() -> WriterRouteProbeResult:
    """Run the no-content CONT route probe against the pinned Grok model list."""

    executable_ok = grok_cli_ready()
    if not executable_ok:
        return WriterRouteProbeResult(False, False, False, False, False, None)
    try:
        result = subprocess.run(
            (GROK_BIN, "models"),
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
            env=unprivileged_child_environment(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        receipt = digest_bytes(
            canonical_json_bytes(
                {
                    "probe": "GROK_MODELS_NO_CONTENT",
                    "exception_class": type(exc).__name__,
                }
            )
        )
        return WriterRouteProbeResult(True, False, False, False, True, receipt)
    receipt = digest_bytes(
        canonical_json_bytes(
            {
                "probe": "GROK_MODELS_NO_CONTENT",
                "return_code": result.returncode,
                "stdout_digest": digest_bytes(result.stdout.encode()),
                "stderr_digest": digest_bytes(result.stderr.encode()),
            }
        )
    )
    available = result.returncode == 0
    configured = available and "grok-4.6" in result.stdout
    return WriterRouteProbeResult(
        executable_ok=True,
        authentication_ok=available,
        configuration_ok=configured,
        provider_available=available,
        provider_dispatched=True,
        provider_receipt_reference=receipt,
    )


def prove_cursor_agent_cli() -> None:
    result = subprocess.run(
        (CURSOR_AGENT_BIN, "--list-models"),
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
        env=unprivileged_child_environment(),
    )
    if result.returncode != 0 or "Available models" not in result.stdout:
        raise RuntimeError("cursor-agent CLI is not logged in or not runnable")


def default_writer() -> WriterPort:
    name = os.environ.get("NEWSROOM_WRITER", "grok").strip().lower()
    if name == "fixture":
        return FixtureWriter()
    return CliChainWriter()
