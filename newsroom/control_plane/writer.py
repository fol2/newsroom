"""CONT writer port. Graphiti is never the writer. Live copy uses OpenRouter."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from newsroom.control_plane.broker import openrouter_api_key
from newsroom.control_plane.editorial import StoryCandidateRecord
from newsroom.control_plane.evidence import EvidencePackage
from newsroom.graphiti_adapter.evaluation_packet import (
    OPENROUTER_BASE_URL,
    OPENROUTER_WRITER_SLUG,
)

WRITER_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "body": {"type": "string"},
    },
    "required": ["title", "body"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class WriterCopy:
    title: str
    body: str
    writer_id: str


class WriterPort(Protocol):
    writer_id: str

    def write(
        self, candidate: StoryCandidateRecord, package: EvidencePackage
    ) -> WriterCopy: ...


class FixtureWriter:
    """Deterministic evaluation writer. Not live OpenRouter. Not Graphiti."""

    writer_id = "evaluation-fixture-writer-v1"

    def write(
        self, candidate: StoryCandidateRecord, package: EvidencePackage
    ) -> WriterCopy:
        sources = "、".join(package.source_ids)
        body = (
            "【未出版原創評核稿】本報根據已入證嘅 Evidence Package 整理呢單新聞，"
            f"唔係來源標題複本。涉及來源：{sources}。"
            f"候選題旨：{candidate.headline}。"
            "稿件維持香港繁體中文，狀態為未出版，禁止公開發行。"
        )
        return WriterCopy(
            title=f"【未出版】{candidate.headline}",
            body=body,
            writer_id=self.writer_id,
        )


def _parse_copy(raw: str) -> tuple[str, str]:
    payload = json.loads(raw)
    title = payload.get("title")
    body = payload.get("body")
    if not isinstance(title, str) or not isinstance(body, str):
        raise RuntimeError("writer JSON missing title or body")
    return title.strip(), body.strip()


class OpenRouterWriter:
    """CONT writer via OpenRouter `x-ai/grok-4.6`. Injects OPENROUTER_API only."""

    writer_id = "openrouter-x-ai.grok-4.6-cont-writer"

    def __init__(self, *, post=None, api_key=None) -> None:
        self._post = post or _openrouter_chat
        self._api_key = api_key

    def write(
        self, candidate: StoryCandidateRecord, package: EvidencePackage
    ) -> WriterCopy:
        prompt = (
            "你係 Newsroom 嘅 CONT 原創記者，唔係 Graphiti。"
            "用香港繁體中文寫一篇未出版新聞稿。必須原創改寫，唔好複製來源標題或 dateline 模板。"
            "唔准 AUTO_PUBLISH，唔准當公開發行。"
            "只輸出 JSON 物件，欄位 title 同 body。"
            f"\n題旨：{candidate.headline}\n證據：\n"
            + "\n---\n".join(package.passages)
        )
        secret = self._api_key() if self._api_key else openrouter_api_key()
        raw = self._post(prompt=prompt, api_key=secret)
        title, body = _parse_copy(raw)
        return WriterCopy(title=title, body=body, writer_id=self.writer_id)


def _openrouter_chat(*, prompt: str, api_key: str) -> str:
    payload = json.dumps(
        {
            "model": OPENROUTER_WRITER_SLUG,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{OPENROUTER_BASE_URL}/chat/completions",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/fol2/newsroom",
            "X-Title": "newsroom-unpublished-beta",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"OpenRouter writer HTTP {exc.code}") from exc
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("OpenRouter writer returned no choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("OpenRouter writer returned empty content")
    return content


def default_writer() -> WriterPort:
    name = os.environ.get("NEWSROOM_WRITER", "openrouter").strip().lower()
    if name == "fixture":
        return FixtureWriter()
    return OpenRouterWriter()
