"""CONT writer port. Graphiti is never the writer."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Protocol

from newsroom.control_plane.editorial import StoryCandidateRecord
from newsroom.control_plane.evidence import EvidencePackage

GROK_BIN = os.environ.get("NEWSROOM_GROK_BIN", "/Users/jamesto/.grok/bin/grok")
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
    """Deterministic evaluation writer. Not live Grok. Not Graphiti."""

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


class GrokWriter:
    writer_id = "grok-4.6-cont-writer"

    def write(
        self, candidate: StoryCandidateRecord, package: EvidencePackage
    ) -> WriterCopy:
        prompt = (
            "你係 Newsroom 嘅 CONT 原創記者，唔係 Graphiti。"
            "用香港繁體中文寫一篇未出版新聞稿。必須原創改寫，唔好複製來源標題或 dateline 模板。"
            "唔准 AUTO_PUBLISH，唔准當公開發行。只輸出 JSON。"
            f"\n題旨：{candidate.headline}\n證據：\n"
            + "\n---\n".join(package.passages)
        )
        result = subprocess.run(
            [
                GROK_BIN,
                "--single",
                prompt,
                "--output-format",
                "json",
                "--json-schema",
                json.dumps(WRITER_SCHEMA, ensure_ascii=False),
                "--disable-web-search",
                "--always-approve",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "grok writer failed")
        payload = json.loads(result.stdout)
        title = payload.get("title")
        body = payload.get("body")
        if not isinstance(title, str) or not isinstance(body, str):
            raise RuntimeError("grok writer JSON missing title or body")
        return WriterCopy(title=title.strip(), body=body.strip(), writer_id=self.writer_id)


def default_writer() -> WriterPort:
    name = os.environ.get("NEWSROOM_WRITER", "grok").strip().lower()
    if name == "fixture":
        return FixtureWriter()
    return GrokWriter()
