"""Bounded issue #790 intake-to-queue bridge with no consumer effects."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from newsroom.control_plane.corpus import CorpusIngestUnit
from newsroom.control_plane.cycle import load_graphiti_units
from newsroom.control_plane.graphiti_events import (
    ensure_graphiti_event_schema,
    reconcile_graphiti_events,
)
from newsroom.control_plane.intake import run_intake
from newsroom.control_plane.store import (
    connect,
    emit_effective_revision_landed,
    has_effective_revision_landed,
)
from newsroom.control_plane.veto import assert_private_store
from newsroom.increment9.proving import Fetcher, PROVING_GATES, SOURCE_IDS


class BoundedEventSupplyError(RuntimeError):
    """The one-revision issue #790 supply boundary failed closed."""


@dataclass(frozen=True, slots=True)
class BoundedEventSupplyResult:
    proving_run_id: str
    event_id: str
    ledger_seq: int
    state: str
    attempt_count: int
    provider_dispatched: bool
    claim_owner: str | None
    claim_expires_at: str | None
    unit_count: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _complete_authorised_run_instants(proving_store: str) -> dict[str, str]:
    connection = sqlite3.connect(proving_store)
    try:
        names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if not {"proving_runs", "proving_observations", "proving_gates"} <= names:
            return {}
        rows = connection.execute(
            """
            SELECT run.run_id, MIN(obs.fetched_at)
            FROM proving_runs AS run
            JOIN proving_observations AS obs
              ON obs.run_id=run.run_id
             AND obs.status_code=200
             AND obs.error IS NULL
            GROUP BY run.run_id
            HAVING COUNT(DISTINCT obs.source_id)=?
               AND (
                 SELECT COUNT(*) FROM proving_gates AS gates
                 WHERE gates.run_id=run.run_id
               )=?
               AND (
                 SELECT COUNT(*) FROM proving_gates AS gates
                 WHERE gates.run_id=run.run_id AND gates.status<>'PASS'
               )=0
            """,
            (len(SOURCE_IDS), len(PROVING_GATES)),
        ).fetchall()
    finally:
        connection.close()
    return {str(run_id): str(fetched_at) for run_id, fetched_at in rows}


def _frontier_landed_at(
    connection: sqlite3.Connection, ledger_seq: int
) -> str | None:
    if ledger_seq == 0:
        return None
    row = connection.execute(
        "SELECT landed_at FROM unpublished_graphiti_revision_events "
        "WHERE ledger_seq=?",
        (ledger_seq,),
    ).fetchone()
    if row is None:
        return None
    return str(row[0])


def _stranded_unlanded_units(
    units: Sequence[CorpusIngestUnit],
    *,
    proving_store: str,
    unpublished: sqlite3.Connection,
    window_start: str | None,
) -> tuple[CorpusIngestUnit, ...]:
    retained = _complete_authorised_run_instants(proving_store)
    protected: list[CorpusIngestUnit] = []
    for unit in units:
        fetched_at = retained.get(unit.proving_run_id)
        if fetched_at is None:
            continue
        if window_start is not None and fetched_at < window_start:
            continue
        if unit.coverage_first_observed_at != fetched_at:
            continue
        protected.append(unit)
    unlanded_keys = set()
    seen_keys = set()
    for unit in protected:
        key = unit.coverage_key()
        if key in seen_keys:
            continue
        seen_keys.add(key)
        if not has_effective_revision_landed(
            unpublished,
            unit.effective_revision,
            published_at=unit.published_at or "",
            updated_at=unit.updated_at or "",
        ):
            unlanded_keys.add(key)
    return tuple(unit for unit in protected if unit.coverage_key() in unlanded_keys)


def supply_one_graphiti_event(
    *,
    proving_store: str,
    unpublished_store: str,
    expected_frontier_ledger_seq: int,
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    fetch: Fetcher | None = None,
) -> BoundedEventSupplyResult:
    """Intake and project one new revision, leaving it untouched.

    Several new coverage keys at the intake instant select the first key in
    coverage-tuple order. Other new keys stay unlanded. If this instant
    first-saw none, one unlanded key first-seen on a retained complete
    authorised proving run still qualifies. Old-run and pre-frontier
    first-seen keys do not.
    """
    if type(expected_frontier_ledger_seq) is not int or expected_frontier_ledger_seq < 0:
        raise BoundedEventSupplyError("expected frontier must be non-negative")
    assert_private_store(proving_store)
    assert_private_store(unpublished_store)
    if Path(proving_store).resolve() == Path(unpublished_store).resolve():
        raise BoundedEventSupplyError("proving and unpublished stores must be distinct")
    observed_at = clock().astimezone(UTC)
    report = run_intake(
        proving_store=proving_store,
        fetch=fetch,
        clock=lambda: observed_at,
    )
    if not report.complete or not report.authorised:
        raise BoundedEventSupplyError("intake must be complete and authorised")

    try:
        units = load_graphiti_units(
            proving_store=proving_store,
            evaluated_at=observed_at,
        )
    except ValueError as exc:
        raise BoundedEventSupplyError("intake units are not eligible") from exc
    intake_observed_at = _utc_text(observed_at)
    current_units = tuple(
        unit
        for unit in units
        if unit.proving_run_id == report.proving_run_id
        and unit.coverage_first_observed_at == intake_observed_at
    )

    connection = connect(unpublished_store)
    try:
        ensure_graphiti_event_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        frontier = int(
            connection.execute(
                "SELECT COALESCE(MAX(ledger_seq),0) "
                "FROM unpublished_graphiti_revision_events"
            ).fetchone()[0]
        )
        if frontier != expected_frontier_ledger_seq:
            raise BoundedEventSupplyError("Graphiti event frontier changed")
        if not current_units:
            current_units = _stranded_unlanded_units(
                units,
                proving_store=proving_store,
                unpublished=connection,
                window_start=_frontier_landed_at(
                    connection, expected_frontier_ledger_seq
                ),
            )
        coverage_keys = {unit.coverage_key() for unit in current_units}
        if not coverage_keys:
            raise BoundedEventSupplyError(
                f"intake must yield at least one new landed revision "
                f"({len(coverage_keys)})"
            )
        selected_key = sorted(coverage_keys)[0]
        selected = tuple(
            unit for unit in current_units if unit.coverage_key() == selected_key
        )
        first = selected[0]
        if has_effective_revision_landed(
            connection,
            first.effective_revision,
            published_at=first.published_at or "",
            updated_at=first.updated_at or "",
        ):
            raise BoundedEventSupplyError("selected revision is already landed")
        if not emit_effective_revision_landed(
            connection,
            first.effective_revision,
            published_at=first.published_at,
            updated_at=first.updated_at,
            ingest_ids=tuple(unit.ingest_id for unit in selected),
            landed_at=min(unit.coverage_first_observed_at for unit in selected),
        ):
            raise BoundedEventSupplyError("selected revision was not landed")
        landed = connection.execute(
            "SELECT ledger.seq,landed.ledger_digest "
            "FROM unpublished_effective_revision_landed AS landed "
            "JOIN ledger ON ledger.digest=landed.ledger_digest "
            "WHERE landed.source_id=? AND landed.item_key=? "
            "AND landed.revision_digest=? AND landed.published_at=? "
            "AND landed.updated_at=?",
            (
                first.source_id,
                first.item_key,
                first.revision_digest,
                first.published_at or "",
                first.updated_at or "",
            ),
        ).fetchone()
        if landed is None or int(landed[0]) <= expected_frontier_ledger_seq:
            raise BoundedEventSupplyError("landed revision is not post-frontier")
        event_id = str(landed[1])
        if (
            reconcile_graphiti_events(
                connection,
                selected,
                available_at=observed_at,
                event_id=event_id,
            )
            != 1
        ):
            raise BoundedEventSupplyError("exact Graphiti event was not projected")
        row = connection.execute(
            "SELECT event_id,ledger_seq,state,attempt_count,provider_dispatched,"
            "claim_owner,claim_expires_at,unit_count "
            "FROM unpublished_graphiti_revision_events WHERE event_id=?",
            (event_id,),
        ).fetchone()
        if row is None or row[2:] != (
            "QUEUED",
            0,
            0,
            None,
            None,
            len(selected),
        ):
            raise BoundedEventSupplyError("projected event is not untouched attempt-0")
        connection.commit()
    except ValueError as exc:
        if connection.in_transaction:
            connection.rollback()
        raise BoundedEventSupplyError("exact event projection was rejected") from exc
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()

    return BoundedEventSupplyResult(
        proving_run_id=report.proving_run_id,
        event_id=event_id,
        ledger_seq=int(row[1]),
        state=str(row[2]),
        attempt_count=int(row[3]),
        provider_dispatched=bool(row[4]),
        claim_owner=None,
        claim_expires_at=None,
        unit_count=int(row[7]),
    )
