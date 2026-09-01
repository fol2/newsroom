#!/usr/bin/env python3
"""Consume durable Graphiti revision events independently from source polling."""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import asdict

from newsroom.control_plane.cycle import (
    GRAPHITI_UNIT_RESERVATION_GBP_MICROUNITS,
    consume_next_graphiti_event,
    qualify_fresh_graphiti_event,
)
from newsroom.control_plane.graphiti import EvaluationGraphitiRunner
from newsroom.control_plane.graphiti_events import GraphitiProcessResult
from newsroom.control_plane.paths import (
    CANONICAL_PROVING_STORE,
    CANONICAL_UNPUBLISHED_STORE,
    ensure_control_plane_state_root,
)


def _run(
    *,
    consume: Callable[[], GraphitiProcessResult | None],
) -> int:
    """Run exactly one selected event and fail closed on any other result."""

    try:
        result = consume()
    except (OSError, RuntimeError, TypeError, ValueError, sqlite3.Error) as exc:
        _emit_stop("EXACT_EVENT_EXECUTION_REFUSED", completed=0)
        print(
            json.dumps(
                {
                    "event": "GRAPHITI_WORKER_DIAGNOSTIC",
                    "failure_type": type(exc).__name__,
                    "failure": str(exc),
                    "public_dispatch": False,
                    "auto_publish": False,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return 2
    _emit_result(result)
    if result is None:
        _emit_stop("EXACT_EVENT_NOT_CLAIMED", completed=0)
        return 2
    if result.state != "TERMINAL":
        _emit_stop("NON_TERMINAL_EVENT_RESULT", completed=0, result=result)
        return 2
    _emit_stop("EXACT_EVENT_TERMINAL", completed=1, result=result)
    return 0


def _emit_result(result: GraphitiProcessResult | None) -> None:
    print(
        json.dumps(
            {
                "event": "GRAPHITI_EVENT_IDLE"
                if result is None
                else "GRAPHITI_EVENT_RESULT",
                "result": None if result is None else asdict(result),
                "public_dispatch": False,
                "auto_publish": False,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


def _emit_stop(
    reason: str,
    *,
    completed: int,
    result: GraphitiProcessResult | None = None,
) -> None:
    print(
        json.dumps(
            {
                "event": "GRAPHITI_WORKER_STOPPED",
                "reason": reason,
                "completed_events": completed,
                "result": None if result is None else asdict(result),
                "public_dispatch": False,
                "auto_publish": False,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Unpublished EVALUATION Graphiti event worker."
    )
    parser.add_argument("--proving", default=str(CANONICAL_PROVING_STORE))
    parser.add_argument("--unpublished", default=str(CANONICAL_UNPUBLISHED_STORE))
    parser.add_argument(
        "--once",
        action="store_true",
        help="retained compatibility flag; exact-event mode is always one event",
    )
    parser.add_argument(
        "--max-runtime-seconds",
        type=float,
        default=180.0,
        help="hard upper bound for the selected event's provider dispatch",
    )
    parser.add_argument(
        "--event-id",
        required=True,
        help="claim one exact fresh event rather than the generic queue",
    )
    parser.add_argument(
        "--ledger-seq",
        type=int,
        required=True,
        help="ledger sequence bound to --event-id provider-free preflight",
    )
    parser.add_argument(
        "--max-reserved-gbp-microunits",
        type=int,
        required=True,
        help="finite conservative embedding reservation cap for the exact event",
    )
    args = parser.parse_args(argv)
    if (
        not math.isfinite(args.max_runtime_seconds)
        or args.max_runtime_seconds <= 0
    ):
        parser.error("--max-runtime-seconds must be finite and positive")
    if args.ledger_seq <= 0:
        parser.error("--ledger-seq must be positive")
    if args.max_reserved_gbp_microunits <= 0:
        parser.error("a positive --max-reserved-gbp-microunits is required")

    ensure_control_plane_state_root()
    try:
        preflight = qualify_fresh_graphiti_event(
            proving_store=args.proving,
            unpublished_store=args.unpublished,
            event_id=args.event_id,
            ledger_seq=args.ledger_seq,
        )
        resolved_units = preflight.get("resolved_units")
        if not isinstance(resolved_units, list) or not resolved_units:
            raise ValueError("exact event preflight resolved no units")
    except (OSError, RuntimeError, TypeError, ValueError, sqlite3.Error) as exc:
        _emit_stop(
            "PREFLIGHT_REFUSED",
            completed=0,
        )
        print(
            json.dumps(
                {
                    "event": "GRAPHITI_WORKER_DIAGNOSTIC",
                    "failure_type": type(exc).__name__,
                    "failure": str(exc),
                    "public_dispatch": False,
                    "auto_publish": False,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return 2
    reserved_bound = (
        len(resolved_units) * GRAPHITI_UNIT_RESERVATION_GBP_MICROUNITS
    )
    if reserved_bound > args.max_reserved_gbp_microunits:
        _emit_stop("RESERVED_SPEND_BOUND_EXCEEDED", completed=0)
        return 2
    print(
        json.dumps(
            {
                "event": "GRAPHITI_EVENT_PREFLIGHT",
                "preflight": preflight,
                "reserved_gbp_microunits_bound": reserved_bound,
                "max_reserved_gbp_microunits": (
                    args.max_reserved_gbp_microunits
                ),
                "public_dispatch": False,
                "auto_publish": False,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    graphiti = EvaluationGraphitiRunner(fallback_permitted=False)
    owner_id = f"hermes-graphiti:{uuid.uuid4()}"
    return _run(
        consume=lambda: consume_next_graphiti_event(
            proving_store=args.proving,
            unpublished_store=args.unpublished,
            graphiti=graphiti,
            owner_id=owner_id,
            event_id=args.event_id,
            require_fresh=True,
            recover_model_usage=False,
            max_dispatch_seconds=args.max_runtime_seconds,
            prepared_event_preflight=preflight,
            max_reserved_gbp_microunits=args.max_reserved_gbp_microunits,
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
