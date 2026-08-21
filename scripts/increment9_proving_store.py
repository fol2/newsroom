#!/usr/bin/env python3
"""Increment 9P proving store CLI. Network I/O only happens on `fetch`."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from newsroom.control_plane.paths import (
    CANONICAL_PROVING_STORE,
    ensure_control_plane_state_root,
)
from newsroom.control_plane.rights_renewal import automatic_rights_arguments
from newsroom.increment9.prospective_run_authority import persist_authorised_chain
from newsroom.increment9.proving import (
    ProvingReport,
    assess,
    list_observations,
    report_json,
    run_proving,
)


DEFAULT_PROVING_STORE = str(CANONICAL_PROVING_STORE)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Proving live source store (no publication).")
    parser.add_argument("command", choices=("assess", "fetch", "list"))
    parser.add_argument("--store", default=DEFAULT_PROVING_STORE)
    parser.add_argument("--run-id", default="proving-9p")
    parser.add_argument("--attest-no-emergency-stop", action="store_true")
    args = parser.parse_args(argv)
    ensure_control_plane_state_root()
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
    instant = datetime.now(tz=UTC)
    fetched_at = instant.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    chain = persist_authorised_chain(run_id=args.run_id)
    report = run_proving(
        store_path=args.store,
        run_id=args.run_id,
        fetched_at=fetched_at,
        kill_switch=kill,
        no_emergency_stop=args.attest_no_emergency_stop,
        run_authority=chain.resolver,
        **automatic_rights_arguments(proving_store=args.store, now=instant),
    )
    sys.stdout.buffer.write(report_json(report))
    sys.stdout.write("\n")
    if not report.authorised:
        return 2
    return 0 if report.complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
