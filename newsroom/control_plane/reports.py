"""Compose unpublished news reports from retained source items."""

from __future__ import annotations

from newsroom.control_plane.items import SourceItem

DATELINES = {
    "UK-01": "London — Home Office and UKVI",
    "UK-02": "London — British National (Overseas) visa guidance",
    "UK-03": "London — UK Immigration Rules",
    "UK-05": "London — Department for Education and Ofqual",
    "UK-10": "Exeter — Met Office",
    "HK-01": "Hong Kong — news.gov.hk",
    "HK-02": "Hong Kong — Observatory",
    "HK-04": "Hong Kong — Education Bureau",
    "RAD-01": "Hong Kong — RTHK",
    "RAD-02": "London — BBC News UK",
}


def news_report(item: SourceItem, *, observed_at: str) -> str:
    dateline = DATELINES.get(item.source_id, item.source_id)
    date = observed_at[:10] if observed_at else ""
    lead = item.body if item.body and item.body != item.headline else item.headline
    prefix = f"{dateline}, {date} — " if date else f"{dateline} — "
    return prefix + lead
