"""Deterministic UTF-8 evidence segmentation."""

from __future__ import annotations

import re

from newsroom.graphiti_adapter.combined_temporal_types import EvidenceSegment

MAX_SEGMENT_BYTES = 512
_SPLIT = re.compile(
    rb"(?:(?<=[.!?])[ \t]+)|(?:\n+)|"
    rb"(?:(?:\xe3\x80\x82|\xef\xbc\x81|\xef\xbc\x9f|\xef\xbc\x9b)[ \t]*)"
)


def segment_source(
    body: str, *, max_bytes: int = MAX_SEGMENT_BYTES
) -> tuple[EvidenceSegment, ...]:
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    data = body.encode("utf-8")
    if not data:
        return (EvidenceSegment(0, 0, 0, ""),)
    cuts = [0]
    for match in _SPLIT.finditer(data):
        end = match.end()
        if end > cuts[-1]:
            cuts.append(end)
    if cuts[-1] < len(data):
        cuts.append(len(data))
    bounds: list[tuple[int, int]] = []
    for start, end in zip(cuts, cuts[1:]):
        if end > start:
            bounds.extend(_split_oversize(data, start, end, max_bytes))
    segments: list[EvidenceSegment] = []
    for index, (start, end) in enumerate(bounds):
        try:
            text = data[start:end].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("segment is not valid UTF-8") from exc
        segments.append(
            EvidenceSegment(
                segment_id=index,
                start_byte=start,
                end_byte=end,
                text=text,
            )
        )
    return tuple(segments)


def _split_oversize(
    data: bytes, start: int, end: int, max_bytes: int
) -> list[tuple[int, int]]:
    parts: list[tuple[int, int]] = []
    cursor = start
    while cursor < end:
        limit = min(cursor + max_bytes, end)
        if limit == end:
            cut = _utf8_cut(data, cursor, end)
            if cut != end:
                raise ValueError("segment is not valid UTF-8")
            parts.append((cursor, end))
            break
        cut = data.rfind(b" ", cursor, limit)
        if cut <= cursor:
            cut = _utf8_cut(data, cursor, limit)
        else:
            cut = _utf8_cut(data, cursor, cut + 1)
        if cut <= cursor:
            raise ValueError("segment is not valid UTF-8")
        parts.append((cursor, cut))
        cursor = cut
    return parts


def _utf8_cut(data: bytes, start: int, limit: int) -> int:
    piece = data[start:limit]
    while piece:
        try:
            piece.decode("utf-8")
            return start + len(piece)
        except UnicodeDecodeError:
            piece = piece[:-1]
    return start


__all__ = ["EvidenceSegment", "segment_source"]
