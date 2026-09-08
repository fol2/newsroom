#!/usr/bin/env python3
"""CLI seam for the autonomous private Hermes native service."""

from __future__ import annotations

import argparse
import json
import signal
from collections.abc import Callable, Sequence
from dataclasses import asdict

from newsroom.control_plane.native_service import NativeService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--lock", required=True)
    parser.add_argument("--interval", type=float, default=300)
    parser.add_argument("--failure-backoff", type=float, default=60)
    return parser


def main(
    factory: Callable[[argparse.Namespace], NativeService] | None = None,
    argv: Sequence[str] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    if factory is None:
        from newsroom.control_plane.native_composition import deployed_native_service
        factory = deployed_native_service
    service = factory(args)
    if type(service) is not NativeService:
        raise TypeError("Hermes native factory returned another service")

    def stop(_signal, _frame) -> None:
        service.request_shutdown()

    previous = {
        number: signal.signal(number, stop)
        for number in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        report = service.run(once=args.once)
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
    print(json.dumps(
        {"service": None if report is None else asdict(report), "public_effect": False},
        sort_keys=True,
    ))
    return 0 if report is None or report.outcome == "COMPLETE" else 2


__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
