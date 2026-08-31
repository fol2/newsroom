#!/usr/bin/env python3
"""Provider-free PreparedCanary rehearsal against a sqlite backup copy.

Refuses Mini live proving_store.sqlite3 and unpublished_store.sqlite3 writes.
Does not mint Step 23 or call a live provider.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from newsroom.control_plane.issue_790_prepared_canary import (
    prepare_issue_790_canary,
)
from newsroom.control_plane.issue_790_rehearsal import (
    refuse_live_issue_790_store_paths,
    run_prepared_canary_rehearsal,
    sqlite_backup_copy,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unpublished", type=Path, required=True)
    parser.add_argument("--proving", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--exact-head", required=True)
    args = parser.parse_args(argv)

    refuse_live_issue_790_store_paths(
        args.unpublished, args.proving, args.work_dir, args.plan
    )
    work_unpublished = args.work_dir / "unpublished_rehearsal.sqlite3"
    work_proving = args.work_dir / "proving_rehearsal.sqlite3"
    sqlite_backup_copy(args.unpublished, work_unpublished)
    sqlite_backup_copy(args.proving, work_proving)
    refuse_live_issue_790_store_paths(work_unpublished, work_proving)
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    observed_at = datetime.now(tz=UTC)
    prepared = prepare_issue_790_canary(
        store=work_unpublished,
        proving_store=work_proving,
        plan=plan,
        observed_at=observed_at,
        exact_head=args.exact_head,
        role="preflight",
    )
    result = run_prepared_canary_rehearsal(
        store=work_unpublished,
        proving_store=work_proving,
        plan=plan,
        observed_at=observed_at,
        exact_head=args.exact_head,
        prepared=prepared,
        event_id=str(prepared.candidate_identity["event_id"]),
        ledger_seq=int(prepared.candidate_identity["ledger_seq"]),
    )
    print(f"PREPARED_CANARY_DIGEST={prepared.decision_digest}")
    print(f"DISPATCH_STARTED={result['dispatch_started']}")
    print(f"PROVIDER_CALLS={result['provider_calls']}")
    if result.get("post_dispatch_error"):
        print(f"POST_DISPATCH_ERROR={result['post_dispatch_error']}")
    if result["provider_calls"] != 0 or not result["dispatch_started"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
