"""Private-beta 9P proving intake. Live HTTPS GET only; no public effect."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from os import environ
from typing import Callable
from uuid import uuid4

from newsroom.increment9.prospective_run_authority import persist_authorised_chain
from newsroom.increment9.proving import Fetcher, ProvingReport, run_proving
from newsroom.increment9.rights import (
    HK_01_GATE_ID,
    HK_02_GATE_ID,
    HK_04_GATE_ID,
    RAD_01_GATE_ID,
    RAD_02_GATE_ID,
    UK_02_GATE_ID,
    UK_03_GATE_ID,
    UK_05_GATE_ID,
    UK_10_GATE_ID,
    fixture_inventory,
)


@dataclass(frozen=True, slots=True)
class IntakeReport:
    proving_run_id: str
    complete: bool
    authorised: bool
    ok: int
    sources: int


def _rights(*, now: str) -> dict[str, object]:
    return {
        "rights": fixture_inventory(),
        "rights_uk_02": fixture_inventory(gate=UK_02_GATE_ID),
        "rights_uk_03": fixture_inventory(gate=UK_03_GATE_ID),
        "rights_uk_05": fixture_inventory(gate=UK_05_GATE_ID),
        "rights_uk_10": fixture_inventory(gate=UK_10_GATE_ID),
        "rights_hk_01": fixture_inventory(gate=HK_01_GATE_ID),
        "rights_hk_02": fixture_inventory(gate=HK_02_GATE_ID),
        "rights_hk_04": fixture_inventory(gate=HK_04_GATE_ID),
        "rights_rad_01": fixture_inventory(gate=RAD_01_GATE_ID),
        "rights_rad_02": fixture_inventory(gate=RAD_02_GATE_ID),
        "now": now,
    }


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
        **_rights(now=fetched_at),
    )
    ok = sum(1 for item in report.observations if item.status_code == 200)
    return IntakeReport(
        proving_run_id=run_id,
        complete=report.complete,
        authorised=report.authorised,
        ok=ok,
        sources=len(report.observations),
    )
