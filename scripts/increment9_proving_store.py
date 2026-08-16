#!/usr/bin/env python3
"""Increment 9P proving store CLI. Network I/O only happens on `fetch`."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from newsroom.increment9.proving import (
    ProvingReport,
    assess,
    list_observations,
    report_json,
    run_proving,
)


def _now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Proving live source store (no publication).")
    parser.add_argument("command", choices=("assess", "fetch", "list"))
    parser.add_argument("--store", default="data/newsroom/proving_store.sqlite3")
    parser.add_argument("--run-id", default="proving-9p")
    parser.add_argument("--attest-no-emergency-stop", action="store_true")
    args = parser.parse_args(argv)
    kill = os.environ.get("NEWSROOM_PROVING_KILL") == "1"
    if args.command == "assess":
        gates = assess(run_id=args.run_id, kill_switch=kill, no_emergency_stop=args.attest_no_emergency_stop)
        sys.stdout.buffer.write(report_json(ProvingReport(args.run_id, False, False, False, 0, gates, ())))
        sys.stdout.write("\n")
        return 0 if all(g.status.value == "PASS" for g in gates) else 2
    if args.command == "list":
        for item in list_observations(args.store):
            print(f"{item.source_id}\t{item.status_code}\t{item.item_count}\t{item.body_digest}")
        return 0
    Path(args.store).parent.mkdir(parents=True, exist_ok=True)
    report = run_proving(
        store_path=args.store,
        run_id=args.run_id,
        fetched_at=_now(),
        kill_switch=kill,
        no_emergency_stop=args.attest_no_emergency_stop,
    )
    sys.stdout.buffer.write(report_json(report))
    sys.stdout.write("\n")
    if not report.authorised:
        return 2
    return 0 if report.complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
