"""Parse retained 9P observation bodies into source items. No network I/O."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from lxml import etree

_TAG = re.compile(r"<[^>]+>")
_XML_PARSER = etree.XMLParser(
    resolve_entities=False, no_network=True, recover=True, huge_tree=False
)
MAX_BODY_CHARS = 4_000
MAX_HEADLINE_CHARS = 240


@dataclass(frozen=True, slots=True)
class SourceItem:
    source_id: str
    item_key: str
    headline: str
    body: str
    canonical_url: str


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", _TAG.sub(" ", text or "")).strip()


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _local(tag: object) -> str:
    name = str(tag)
    return name.rsplit("}", 1)[-1].lower()


def _child_text(element: etree._Element, names: tuple[str, ...]) -> str:
    for child in element:
        if _local(child.tag) in names:
            href = child.get("href")
            if href and _local(child.tag) == "link":
                return href.strip()
            return _plain("".join(child.itertext()))
    return ""


def _from_entry(source_id: str, element: etree._Element) -> SourceItem | None:
    headline = _clip(
        _child_text(element, ("title",)) or _plain("".join(element.itertext())[:240]),
        MAX_HEADLINE_CHARS,
    )
    if not headline:
        return None
    link = _child_text(element, ("link",))
    if not link:
        for child in element:
            if _local(child.tag) == "link" and child.get("href"):
                link = child.get("href", "").strip()
                break
    key = _child_text(element, ("guid", "id")) or link or headline
    body = _clip(
        _child_text(element, ("description", "summary", "content", "encoded"))
        or headline,
        MAX_BODY_CHARS,
    )
    return SourceItem(source_id, key, headline, body, link)


def _from_xml(source_id: str, body: bytes) -> tuple[SourceItem, ...]:
    root = etree.fromstring(body, _XML_PARSER)
    items: list[SourceItem] = []
    for element in root.iter():
        if _local(element.tag) in {"item", "entry"}:
            parsed = _from_entry(source_id, element)
            if parsed is not None:
                items.append(parsed)
    return tuple(items)


def _from_mapping(source_id: str, payload: dict[str, object], *, fallback_key: str) -> SourceItem | None:
    title = payload.get("title") or payload.get("name") or payload.get("code")
    if not isinstance(title, str) or not title.strip():
        return None
    description = payload.get("description") or payload.get("summary") or ""
    if not isinstance(description, str) or not description.strip():
        details = payload.get("details")
        if isinstance(details, dict):
            raw = details.get("body")
            description = raw if isinstance(raw, str) else title
        else:
            description = title
    path = payload.get("base_path") or payload.get("url") or payload.get("link") or ""
    url = path if isinstance(path, str) else ""
    if url.startswith("/"):
        url = "https://www.gov.uk" + url
    key = str(payload.get("content_id") or payload.get("code") or fallback_key)
    return SourceItem(
        source_id,
        key,
        _clip(_plain(title), MAX_HEADLINE_CHARS),
        _clip(_plain(description), MAX_BODY_CHARS),
        url,
    )


def _from_json(source_id: str, body: bytes) -> tuple[SourceItem, ...]:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return ()
    if isinstance(value, list):
        items: list[SourceItem] = []
        for index, entry in enumerate(value):
            if isinstance(entry, dict):
                parsed = _from_mapping(source_id, entry, fallback_key=str(index))
                if parsed is not None:
                    items.append(parsed)
        return tuple(items)
    if not isinstance(value, dict):
        return ()
    if "title" in value or "base_path" in value:
        parsed = _from_mapping(source_id, value, fallback_key=source_id)
        return (parsed,) if parsed is not None else ()
    items = []
    for key, entry in value.items():
        if isinstance(entry, dict):
            parsed = _from_mapping(source_id, entry, fallback_key=str(key))
            if parsed is not None:
                items.append(parsed)
    return tuple(items)


def parse_observation(*, source_id: str, url: str, body: bytes) -> tuple[SourceItem, ...]:
    if not body:
        return ()
    stripped = body.lstrip()
    if stripped.startswith(b"{") or stripped.startswith(b"["):
        return _from_json(source_id, body)
    if stripped.startswith(b"<") or "rss" in url or "atom" in url or url.endswith(".xml"):
        try:
            return _from_xml(source_id, body)
        except etree.XMLSyntaxError:
            return ()
    return _from_json(source_id, body)
