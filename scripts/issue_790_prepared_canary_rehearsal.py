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
    prepared_canary_from_record,
)
from newsroom.control_plane.issue_790_rehearsal import (
    RehearsalEvaluationGraphitiRunner,
    RehearsalRealGraphitiAdapter,
    refuse_live_issue_790_store_paths,
    sqlite_backup_copy,
)
from newsroom.control_plane.issue_790_disposition import run_issue_790_canary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unpublished", type=Path, required=True)
    parser.add_argument("--proving", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--prepared-canary", type=Path, required=True)
    parser.add_argument("--exact-head", required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--disposition-digest", required=True)
    args = parser.parse_args(argv)

    refuse_live_issue_790_store_paths(args.work_dir)
    work_unpublished = args.work_dir / "unpublished_rehearsal.sqlite3"
    work_proving = args.work_dir / "proving_rehearsal.sqlite3"
    sqlite_backup_copy(args.unpublished, work_unpublished)
    sqlite_backup_copy(args.proving, work_proving)
    refuse_live_issue_790_store_paths(work_unpublished, work_proving)
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    prepared_record = json.loads(args.prepared_canary.read_text(encoding="utf-8"))
    if not isinstance(prepared_record, dict):
        raise ValueError("prepared canary must be a JSON object")
    restored = prepared_canary_from_record(prepared_record)
    if restored.exact_head != args.exact_head:
        raise ValueError("prepared canary exact head differs")
    observed_at = datetime.now(tz=UTC)
    RehearsalRealGraphitiAdapter.provider_calls = 0
    RehearsalRealGraphitiAdapter.dispatch_started = False
    result = run_issue_790_canary(
        store=work_unpublished,
        proving_store=work_proving,
        backup_path=args.work_dir / "unpublished_pre_operation.sqlite3",
        plan=plan,
        observed_at=observed_at,
        repository_root=args.repository_root,
        prepared=restored,
        event_id=str(restored.candidate_identity["event_id"]),
        ledger_seq=int(restored.candidate_identity["ledger_seq"]),
        disposition_digest=args.disposition_digest,
        graphiti=RehearsalEvaluationGraphitiRunner(
            fallback_permitted=False,
            clock=lambda: observed_at,
        ),
    )
    print(f"PREPARED_CANARY_DIGEST={restored.decision_digest}")
    print(f"PREPARED_CANARY_RECORD_DIGEST={prepared_record['record_digest']}")
    print("FULL_PRODUCTION_PATH=1")
    print(f"DISPATCH_STARTED={RehearsalRealGraphitiAdapter.dispatch_started}")
    print(f"PROVIDER_CALLS={RehearsalRealGraphitiAdapter.provider_calls}")
    print(f"CANARY_EVIDENCE_PASSED={result['canary_evidence_passed']}")
    process = (
        result["process_result"]
        if isinstance(result.get("process_result"), dict)
        else {}
    )
    outcome = result["outcome"] if isinstance(result.get("outcome"), dict) else {}
    print(f"PROCESS_STATE={process.get('state')}")
    print(f"RESULT_CLASS={outcome.get('result_class')}")
    if (
        RehearsalRealGraphitiAdapter.provider_calls != 0
        or not RehearsalRealGraphitiAdapter.dispatch_started
        or result["exception"] is not None
        or process.get("state") != "TERMINAL"
        or outcome.get("result_class") != "TRUTHFUL_PROVIDER_SUCCESS"
        or result["canary_evidence_passed"] is not True
    ):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
