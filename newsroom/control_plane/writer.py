"""CONT writer: Grok Build CLI, then cursor-agent CLI. Graphiti is never the writer."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Callable, Protocol

from newsroom.control_plane.editorial import StoryCandidateRecord
from newsroom.control_plane.evidence import EvidencePackage

GROK_BIN = os.environ.get("NEWSROOM_GROK_BIN", "/Users/jamesto/.grok/bin/grok")
CURSOR_AGENT_BIN = os.environ.get(
    "NEWSROOM_CURSOR_AGENT_BIN", "/Users/jamesto/.local/bin/cursor-agent"
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
_PROMPT = (
    "你係 Newsroom 嘅 CONT 原創記者，唔係 Graphiti。"
    "用香港繁體中文寫一篇未出版新聞稿。必須原創改寫，唔好複製來源標題或 dateline 模板。"
    "唔准 AUTO_PUBLISH，唔准當公開發行。"
    "只輸出 JSON 物件，欄位 title 同 body。"
)


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


def _prompt(candidate: StoryCandidateRecord, package: EvidencePackage) -> str:
    return (
        f"{_PROMPT}\n題旨：{candidate.headline}\n證據：\n"
        + "\n---\n".join(package.passages)
    )


def _extract_json(raw: str) -> str:
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("writer returned no JSON object")
    return raw[start : end + 1]


def _parse_copy(raw: str) -> tuple[str, str]:
    payload = json.loads(_extract_json(raw))
    title = payload.get("title")
    body = payload.get("body")
    if not isinstance(title, str) or not isinstance(body, str):
        raise RuntimeError("writer JSON missing title or body")
    return title.strip(), body.strip()


def _run(command: tuple[str, ...], *, timeout: int) -> str:
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        name = os.path.basename(command[0])
        raise RuntimeError(f"{name} writer failed")
    if not result.stdout.strip():
        raise RuntimeError("writer returned empty stdout")
    return result.stdout


def run_grok_cli(prompt: str) -> str:
    schema = json.dumps(WRITER_SCHEMA, ensure_ascii=False)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", suffix=".txt", delete=False
    ) as handle:
        handle.write(prompt)
        path = handle.name
    try:
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
                "--permission-mode",
                "plan",
                "--max-turns",
                "1",
                "--no-subagents",
            ),
            timeout=180,
        )
    finally:
        os.unlink(path)


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
        prompt = _prompt(candidate, package)
        try:
            title, body = _parse_copy(self._primary(prompt))
            return WriterCopy(title=title, body=body, writer_id=self.writer_id)
        except (RuntimeError, json.JSONDecodeError, OSError, subprocess.TimeoutExpired):
            title, body = _parse_copy(self._fallback(prompt))
            return WriterCopy(
                title=title,
                body=body,
                writer_id="cursor-agent-cli-cont-writer",
            )


def grok_cli_ready() -> bool:
    return shutil.which(GROK_BIN) is not None or os.path.isfile(GROK_BIN)


def cursor_agent_cli_ready() -> bool:
    return shutil.which(CURSOR_AGENT_BIN) is not None or os.path.isfile(CURSOR_AGENT_BIN)


def prove_grok_cli() -> None:
    result = subprocess.run(
        (GROK_BIN, "version"),
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
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
    )
    if result.returncode != 0 or "Available models" not in result.stdout:
        raise RuntimeError("cursor-agent CLI is not logged in or not runnable")


def default_writer() -> WriterPort:
    name = os.environ.get("NEWSROOM_WRITER", "grok").strip().lower()
    if name == "fixture":
        return FixtureWriter()
    return CliChainWriter()
