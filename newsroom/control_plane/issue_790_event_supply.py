"""Bounded issue #790 intake-to-queue bridge with no consumer effects."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

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
from newsroom.increment9.proving import Fetcher


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


def supply_one_graphiti_event(
    *,
    proving_store: str,
    unpublished_store: str,
    expected_frontier_ledger_seq: int,
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    fetch: Fetcher | None = None,
) -> BoundedEventSupplyResult:
    """Intake and project exactly one new revision, leaving it untouched."""

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
    coverage_keys = {unit.coverage_key() for unit in current_units}
    if len(coverage_keys) != 1:
        raise BoundedEventSupplyError(
            "intake must yield exactly one new landed revision"
        )
    selected = tuple(
        unit for unit in current_units if unit.coverage_key() in coverage_keys
    )
    first = selected[0]

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
