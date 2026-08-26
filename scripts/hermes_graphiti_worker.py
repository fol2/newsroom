#!/usr/bin/env python3
"""Consume durable Graphiti revision events independently from source polling."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict

from newsroom.control_plane.cycle import consume_next_graphiti_event
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
    once: bool,
    idle_seconds: float,
    failure_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    while True:
        result = consume()
        if result is not None or once:
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
        if once:
            return 0
        if result is not None and result.state in {"RETRY_HELD", "DEAD_LETTER"}:
            sleep(failure_seconds)
        elif result is None:
            sleep(idle_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Unpublished EVALUATION Graphiti event worker."
    )
    parser.add_argument("--proving", default=str(CANONICAL_PROVING_STORE))
    parser.add_argument("--unpublished", default=str(CANONICAL_UNPUBLISHED_STORE))
    parser.add_argument(
        "--idle-seconds",
        type=float,
        default=1.0,
        help="wait after finding no claimable event; independent from source polling",
    )
    parser.add_argument(
        "--failure-seconds",
        type=float,
        default=30.0,
        help="worker backoff after a retry-held provider or graph result",
    )
    parser.add_argument(
        "--once", action="store_true", help="process at most one revision event"
    )
    args = parser.parse_args(argv)
    if args.idle_seconds <= 0:
        parser.error("--idle-seconds must be positive")
    if args.failure_seconds < 30:
        parser.error("--failure-seconds must be at least 30")

    ensure_control_plane_state_root()
    graphiti = EvaluationGraphitiRunner()
    owner_id = f"hermes-graphiti:{uuid.uuid4()}"
    return _run(
        consume=lambda: consume_next_graphiti_event(
            proving_store=args.proving,
            unpublished_store=args.unpublished,
            graphiti=graphiti,
            owner_id=owner_id,
        ),
        once=args.once,
        idle_seconds=args.idle_seconds,
        failure_seconds=args.failure_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
