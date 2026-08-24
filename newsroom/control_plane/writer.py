"""CONT writer: Grok Build CLI, then cursor-agent CLI. Graphiti is never the writer."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal, Protocol

from newsroom.control_plane.child_environment import unprivileged_child_environment
from newsroom.control_plane.editorial import StoryCandidateRecord
from newsroom.control_plane.evidence import EvidencePackage
from newsroom.control_plane.zh_hant import contains_simplified_variant

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
_TITLE_RESIDUE_PREFIXES = ("正在", "搜集", "查核", "先查")
_TITLE_RESIDUE_EXACT = frozenset({"新聞稿任務", "Newsroom 原創稿"})
_BODY_RESIDUE_PREFIXES = ("先查", "先核", "正在核")
_FILLER_MARKERS = ("總括而言", "值得注意的是", "放眼未來", "時間會證明")
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
            claim
            for claim in package.governed_claims
            if claim.claim == candidate.headline
        )
        body_claims = tuple(
            claim
            for claim in package.governed_claims
            if claim.claim != candidate.headline
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
        and not re.search(r"[A-Za-z]", text_without_approved_entities)
        and not contains_simplified_variant(text),
        "NOT_COMPLETED_ZH_HANT_HK_REPORT",
    )
    check(
        "NO_PLANNING_RESIDUE_OR_FILLER",
        not copy.title.startswith(_TITLE_RESIDUE_PREFIXES)
        and copy.title not in _TITLE_RESIDUE_EXACT
        and not copy.body.startswith(_BODY_RESIDUE_PREFIXES)
        and not any(marker in text for marker in _FILLER_MARKERS),
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
        exact_links and bounded_segments,
        "UNSUPPORTED_CLAIM_RESIDUE",
    )
    source_expressions = (*package.passages,) + tuple(
        value.strip()
        for item in package.passages
        for value in re.split(r"(?<=[.!?。！？；;])|\n+", item)
        if value.strip()
    )
    approved_overlap = tuple(
        value
        for claim in package.governed_claims
        for value in (*claim.named_entities, *claim.quotations)
        if value
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
    check(
        "NUMERIC_AND_DATE_FIDELITY",
        all(number in governed_text for number in numbers),
        "UNSUPPORTED_NUMBER_OR_DATE",
    )
    quoted = {
        match
        for pattern in (
            r'"([^"\n]+)"',
            r"“([^”\n]+)”",
            r"「([^」\n]+)」",
            r"『([^』\n]+)』",
        )
        for match in re.findall(pattern, text)
    }
    check(
        "QUOTE_FIDELITY",
        all(
            any(
                value in claim.quotations
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
        any(
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
    certainty_terms = ("證實", "已確認", "必定", "肯定會", "proved", "confirmed")
    used_certainty = tuple(term for term in certainty_terms if term in text)
    check(
        "CERTAINTY_FIDELITY",
        not used_certainty
        or all(
            term in governed_text
            and any(claim.certainty == "CONFIRMED" for claim in package.governed_claims)
            for term in used_certainty
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
