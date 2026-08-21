"""Private-beta 9P proving intake. Live HTTPS GET only; no public effect."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from os import environ
from typing import Callable
from uuid import uuid4

from newsroom.control_plane.rights_renewal import automatic_rights_arguments
from newsroom.increment9.prospective_run_authority import persist_authorised_chain
from newsroom.increment9.proving import (
    Fetcher,
    ProvingReport,
    SOURCE_IDS,
    SourceHealthStatus,
    run_proving,
)


@dataclass(frozen=True, slots=True)
class IntakeReport:
    proving_run_id: str
    complete: bool
    authorised: bool
    ok: int
    sources: int
    health: str
    active: int
    degraded: int
    held: int
    blocked: int


def _run_id(now: datetime) -> str:
    stamp = now.strftime("%Y%m%dT%H%M%S%fZ")
    return f"proving-9p-private-beta-{stamp}-{uuid4().hex}"


def run_intake(
    *,
    proving_store: str,
    fetch: Fetcher | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
) -> IntakeReport:
    kill = environ.get("NEWSROOM_PROVING_KILL") == "1"
    instant = clock().astimezone(UTC)
    run_id = _run_id(instant)
    fetched_at = instant.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    chain = persist_authorised_chain(run_id=run_id)
    report: ProvingReport = run_proving(
        store_path=proving_store,
        run_id=run_id,
        fetched_at=fetched_at,
        kill_switch=kill,
        no_emergency_stop=True,
        fetch=fetch,
        run_authority=chain.resolver,
        **automatic_rights_arguments(proving_store=proving_store, now=instant),
    )
    ok = sum(
        1
        for item in report.observations
        if item.status_code == 200 and item.error is None
    )
    health_counts = {
        status: sum(1 for item in report.source_health if item.status is status)
        for status in SourceHealthStatus
    }
    active = health_counts[SourceHealthStatus.ACTIVE]
    degraded = health_counts[SourceHealthStatus.DEGRADED]
    held = health_counts[SourceHealthStatus.HELD]
    blocked = health_counts[SourceHealthStatus.BLOCKED]
    if blocked:
        posture = SourceHealthStatus.BLOCKED.value
    elif active == len(SOURCE_IDS):
        posture = SourceHealthStatus.ACTIVE.value
    elif held and not active and not degraded:
        posture = SourceHealthStatus.HELD.value
    else:
        posture = SourceHealthStatus.DEGRADED.value
    return IntakeReport(
        proving_run_id=run_id,
        complete=report.complete,
        authorised=report.authorised,
        ok=ok,
        sources=len(report.observations),
        health=posture,
        active=active,
        degraded=degraded,
        held=held,
        blocked=blocked,
    )
