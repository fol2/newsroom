#!/usr/bin/env python3
"""#790 live canary preflight: ops gates + forecast-blocker smokes.

Exit 0 only when every line is PASS. Provider-free; no live Cursor call.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from json import JSONDecoder
from pathlib import Path

ROOT_DEFAULT = Path("/Users/jamesto/Coding/newsroom")
TIP_PLAN_DEFAULT = (
    "sha256:3ad295ccabaf02f61938f8ffbbf1df805d0617f92fd7f9c56d923107a5e2c9c7"
)
PLAN_REL_DEFAULT = "docs/operations/2026-08-28-issue-790-success-sequence-step-13.json"
DISP = "sha256:020f5b5669020da8e0bd4fb74cf2d9c5051533fa3b09dbed54824ccec456638c"
PRED_EVENT = (
    "sha256:32a612bf85399379bc80ccf955b3a99af0c8fd6de2cf47d9ee9e0672d85c5437"
)
PRED_LEDGER = 8867
WORKER = "com.jamesto.newsroom-graphiti-worker"
ACCEPTED_CI = ("focus-gates", "test", "full-deterministic-health")


def sh(*args: str, cwd: Path) -> str:
    return subprocess.check_output(args, text=True, cwd=cwd).strip()


def _check(rows: list[tuple[str, bool, str]], name: str, ok: bool, detail: str) -> None:
    rows.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} — {detail}")


def _ops_gates(
    *,
    root: Path,
    tip_merge: str | None,
    tip_plan: str,
    plan_rel: str,
) -> tuple[list[tuple[str, bool, str]], tuple[str, int] | None]:
    rows: list[tuple[str, bool, str]] = []
    store = root / "data/newsroom/unpublished_store.sqlite3"
    subprocess.run(["git", "fetch", "origin", "main"], check=True, capture_output=True, cwd=root)
    head = sh("git", "rev-parse", "HEAD", cwd=root)
    local = sh("git", "rev-parse", "refs/heads/main", cwd=root)
    origin = sh("git", "rev-parse", "refs/remotes/origin/main", cwd=root)
    github = json.loads(sh("gh", "api", "repos/fol2/newsroom/git/ref/heads/main", cwd=root))[
        "object"
    ]["sha"]
    tip = tip_merge or origin
    branch = sh("git", "symbolic-ref", "--short", "HEAD", cwd=root)
    status = subprocess.check_output(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        text=True,
        cwd=root,
    )
    plan_path = root / plan_rel
    plan_digest = (
        json.loads(plan_path.read_text())["canonical_digest"] if plan_path.is_file() else None
    )
    raw = json.loads(
        sh(
            "gh",
            "api",
            "-H",
            "Accept: application/vnd.github+json",
            f"repos/fol2/newsroom/commits/{tip}/check-runs",
            cwd=root,
        )
    )
    ci_hits = [
        i
        for i in raw.get("check_runs", [])
        if isinstance(i, dict)
        and i.get("name") in ACCEPTED_CI
        and i.get("status") == "completed"
        and i.get("conclusion") == "success"
        and i.get("head_sha") == tip
    ]
    key_ok = False
    envp = root / ".env"
    if envp.is_file():
        for line in envp.read_text().splitlines():
            if line.startswith("CURSOR_API_KEY=") and len(line.split("=", 1)[1].strip()) > 8:
                key_ok = True
    lst = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    pgrep = subprocess.run(
        ["pgrep", "-f", "scripts/hermes_graphiti_worker.py"],
        capture_output=True,
        text=True,
    )
    worker_loaded = WORKER in lst.stdout or bool(pgrep.stdout.strip())
    qc = sh("sqlite3", str(store), "PRAGMA quick_check;", cwd=root)
    conn = sqlite3.connect(f"{store.as_uri()}?mode=ro", uri=True)
    disp = conn.execute(
        "SELECT approved_plan_digest FROM model_usage_conservative_dispositions "
        "WHERE disposition_digest=?",
        (DISP,),
    ).fetchone()
    route = conn.execute(
        "SELECT state, reason FROM model_usage_route_circuit_events "
        "WHERE route='GRAPHITI_CHAT_PRIMARY' "
        "ORDER BY recorded_at DESC, rowid DESC LIMIT 1"
    ).fetchone()
    forbidden = {PRED_EVENT}
    if plan_path.is_file():
        for ev in json.loads(plan_path.read_text()).get("retry_forbidden_events") or []:
            if isinstance(ev, dict) and ev.get("event_id"):
                forbidden.add(str(ev["event_id"]))
    pred = conn.execute(
        "SELECT state, attempt_count FROM unpublished_graphiti_revision_events "
        "WHERE event_id=? AND ledger_seq=?",
        (PRED_EVENT, PRED_LEDGER),
    ).fetchone()
    cands = conn.execute(
        "SELECT event_id, ledger_seq FROM unpublished_graphiti_revision_events "
        "WHERE state='QUEUED' AND attempt_count=0 AND provider_dispatched=0 "
        "ORDER BY ledger_seq DESC LIMIT 40"
    ).fetchall()
    conn.close()

    fresh: list[tuple[str, int]] = []
    clean_event: tuple[str, int] | None = None
    for e, s in cands:
        if e in forbidden or s in {1932, 1972}:
            continue
        fresh.append((e, s))
    if fresh:
        from newsroom.control_plane.cycle import qualify_fresh_graphiti_event

        observed = datetime.now(UTC)
        proving = root / "data/newsroom/proving_store.sqlite3"
        for e, s in fresh[:15]:
            try:
                evidence = qualify_fresh_graphiti_event(
                    proving_store=str(proving),
                    unpublished_store=str(store),
                    event_id=e,
                    ledger_seq=s,
                    clock=lambda: observed,
                )
            except Exception:
                continue
            units = evidence.get("resolved_units") or []
            ingest_ids = [str(u["ingest_id"]) for u in units if isinstance(u, dict)]
            if not ingest_ids:
                continue
            ph = ",".join("?" for _ in ingest_ids)
            c2 = sqlite3.connect(f"{store.as_uri()}?mode=ro", uri=True)
            try:
                prior = False
                for table in (
                    "unpublished_graphiti_ingest",
                    "unpublished_graphiti_failures",
                    "unpublished_graphiti_receipts",
                    "unpublished_graphiti_attempt_receipts",
                    "unpublished_graphiti_spend",
                ):
                    if c2.execute(
                        f"SELECT 1 FROM {table} WHERE ingest_id IN ({ph}) LIMIT 1",
                        ingest_ids,
                    ).fetchone():
                        prior = True
                        break
                if not prior and c2.execute(
                    f"SELECT 1 FROM model_work_envelopes WHERE cycle_id=? "
                    f"OR json_extract(record_json,'$.ingest_id') IN ({ph}) LIMIT 1",
                    (e, *ingest_ids),
                ).fetchone():
                    prior = True
            finally:
                c2.close()
            if not prior:
                clean_event = (e, s)
                break
    fresh = [clean_event] if clean_event else []

    _check(rows, "O01 origin/main == github main == tip", origin == github == tip, origin[:12])
    _check(rows, "O02 HEAD == tip (exact deploy)", head == tip, f"HEAD={head[:12]}")
    _check(rows, "O03 branch == main", branch == "main", branch)
    _check(rows, "O04 HEAD == local == origin", head == local == origin, head[:12])
    _check(
        rows,
        "O05 worktree clean incl. untracked",
        status == "",
        (status.splitlines() or ["clean"])[0],
    )
    _check(rows, "O06 tip Step plan digest on disk", plan_digest == tip_plan, plan_digest or "MISSING")
    _check(
        rows,
        "O07 exact-head accepted CI green",
        bool(ci_hits),
        ",".join(sorted({i["name"] for i in ci_hits})) or "none",
    )
    _check(rows, "O08 CURSOR_API_KEY in .env", key_ok, "present" if key_ok else "ABSENT")
    _check(rows, "O09 graphiti worker UNLOADED", not worker_loaded, "LOADED" if worker_loaded else "unloaded")
    _check(rows, "O10 unpublished_store quick_check=ok", qc == "ok", qc)
    _check(rows, "O11 disposition 020f5b56… retained", disp is not None, (disp[0][:24] + "…") if disp else "ABSENT")
    _check(
        rows,
        "O12 route circuit readable",
        route is not None,
        f"{route[0]}:{str(route[1])[:48]}" if route else "ABSENT",
    )
    _check(
        rows,
        "O13 predecessor event not QUEUED/0",
        pred is not None and not (pred[0] == "QUEUED" and pred[1] == 0),
        f"{pred}" if pred else "ABSENT",
    )
    _check(
        rows,
        "O14 fresh QUEUED attempt-0 CLEAN",
        bool(fresh),
        f"{fresh[0][0][:24]}…/{fresh[0][1]}" if fresh else "NONE",
    )
    return rows, fresh[0] if fresh else None


def _blocker_smokes(repo_for_imports: Path) -> list[tuple[str, bool, str]]:
    """Provider-free dry validation of the nine forecast blockers."""

    rows: list[tuple[str, bool, str]] = []
    sys.path.insert(0, str(repo_for_imports))
    from newsroom.control_plane import issue_790_disposition as disp
    from newsroom.control_plane.cycle import qualify_fresh_graphiti_event
    from newsroom.graphiti_adapter.combined_temporal_contract import build_compact_prompt
    from newsroom.graphiti_adapter.combined_temporal_evidence import segment_source
    from newsroom.graphiti_adapter.combined_temporal_fixtures import FIXTURES
    from newsroom.graphiti_adapter.combined_temporal_types import (
        CombinedTemporalError,
        CombinedTemporalFailureCode,
    )
    from newsroom.graphiti_adapter.combined_temporal_validation import normalise

    gold = next(c for c in FIXTURES if c.name == "pair-current")
    segs = segment_source(gold.revision.body)
    ref = datetime.fromisoformat(gold.revision.published_at.replace("Z", "+00:00"))
    prompt = build_compact_prompt(gold.revision).text

    empty_ok = True
    try:
        normalise({"entities": [], "facts": []}, segs, ref)
    except CombinedTemporalError:
        empty_ok = False
    body = gold.revision.body
    contradictory = {
        "entities": list(gold.gold["entities"])
        + [
            {
                "local_id": 2,
                "name": "Technology and Living",
                "entity_type_id": 0,
                "evidence_segment_ids": [0],
            },
            {
                "local_id": 3,
                "name": "curriculum",
                "entity_type_id": 0,
                "evidence_segment_ids": [0],
            },
        ],
        "facts": [
            {**gold.gold["facts"][0], "fact": body.strip()},
            {
                "source_local_id": 2,
                "target_local_id": 3,
                "relation_type": "ASKED_ABOUT",
                "fact": body.strip(),
                "valid_at": None,
                "invalid_at": None,
                "evidence_segment_ids": [0],
            },
        ],
    }
    contra = None
    try:
        normalise(contradictory, segs, ref)
    except CombinedTemporalError as exc:
        contra = exc.code
    prompt_rules = all(
        token in prompt
        for token in (
            "unique contiguous verbatim span",
            "must be distinct",
            'return {"entities":[],"facts":[]}',
        )
    )
    _check(
        rows,
        "B01 prefer-empty / reject reused fact strings",
        empty_ok and contra == CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED and prompt_rules,
        f"empty={empty_ok} contra={contra} prompt={prompt_rules}",
    )

    gold_ok = True
    try:
        normalise(gold.gold, segs, ref)
    except CombinedTemporalError:
        gold_ok = False
    amb = {
        "entities": [
            {"local_id": 0, "name": "Legislative Council", "entity_type_id": 0, "evidence_segment_ids": [0]},
            {
                "local_id": 1,
                "name": "Technology and Living curriculum",
                "entity_type_id": 0,
                "evidence_segment_ids": [0],
            },
        ],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": 1,
                "relation_type": "ASKED_ABOUT",
                "fact": "Legislative Council Technology and Living curriculum",
                "valid_at": None,
                "invalid_at": None,
                "evidence_segment_ids": [0],
            }
        ],
    }
    amb_code = None
    try:
        normalise(amb, segs, ref)
    except CombinedTemporalError as exc:
        amb_code = exc.code
    _check(
        rows,
        "B02 gold passes; weak attribution fails",
        gold_ok and amb_code == CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
        f"gold={gold_ok} amb={amb_code}",
    )

    self_code = orphan_code = None
    try:
        normalise(
            {
                "entities": [gold.gold["entities"][0]],
                "facts": [{**gold.gold["facts"][0], "source_local_id": 0, "target_local_id": 0}],
            },
            segs,
            ref,
        )
    except CombinedTemporalError as exc:
        self_code = exc.code
    try:
        normalise(
            {
                "entities": list(gold.gold["entities"])
                + [
                    {
                        "local_id": 2,
                        "name": "Technology and Living",
                        "entity_type_id": 0,
                        "evidence_segment_ids": [0],
                    }
                ],
                "facts": gold.gold["facts"],
            },
            segs,
            ref,
        )
    except CombinedTemporalError as exc:
        orphan_code = exc.code
    _check(
        rows,
        "B03 IDENTITY self-loop + orphan entity rejected",
        self_code == CombinedTemporalFailureCode.IDENTITY_INVALID
        and orphan_code == CombinedTemporalFailureCode.IDENTITY_INVALID,
        f"self={self_code} orphan={orphan_code}",
    )

    suffix = json.dumps(gold.gold) + "\n\n[REDACTED]"
    parsed, idx = JSONDecoder().raw_decode(suffix)
    trunc_fail = False
    try:
        JSONDecoder().raw_decode('{"entities":[{"local_id":1')
    except json.JSONDecodeError:
        trunc_fail = True
    _check(
        rows,
        "B04 JSON suffix recoverable; truncate fails closed",
        parsed == gold.gold and idx < len(suffix) and trunc_fail,
        f"suffix_ok={parsed == gold.gold} trunc_fail={trunc_fail}",
    )

    body = Path(disp.__file__).read_text(encoding="utf-8")
    term_req = (
        'process_result.get("state") == "TERMINAL"' in body
        and 'event_after_record.get("state") == "TERMINAL"' in body
    )
    _check(rows, "B05 canary pass requires TERMINAL", term_req, "process+event TERMINAL")

    m = re.search(r"truthful_success = bool\([\s\S]*?\)\n", body)
    truthful_block = m.group(0) if m else ""
    _check(
        rows,
        "B06 empty/zero proposals allowed by stop formula",
        empty_ok and "proposal" not in truthful_block.lower() and any(c.name == "zero-result" for c in FIXTURES),
        "no proposal gate in truthful_success",
    )

    _check(
        rows,
        "B07 fresh-event qualify path available",
        callable(qualify_fresh_graphiti_event),
        "qualify_fresh_graphiti_event",
    )
    _check(
        rows,
        "B08 exact-main evidence collector available",
        callable(disp.collect_issue_790_operational_evidence),
        "collect_issue_790_operational_evidence",
    )
    canary_start = body.find("canary_evidence_passed = bool")
    canary_end = body.find("receipt_without_digest", canary_start)
    canary_block = body[canary_start:canary_end] if canary_start >= 0 and canary_end > canary_start else ""
    _check(
        rows,
        "B09 embedding not required for canary pass",
        bool(canary_block) and "embed" not in canary_block.lower(),
        f"block_bytes={len(canary_block)} no embedding gate",
    )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ops-root", type=Path, default=ROOT_DEFAULT)
    parser.add_argument("--code-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--tip-merge", default=None, help="exact tip SHA; default origin/main")
    parser.add_argument("--tip-plan", default=TIP_PLAN_DEFAULT)
    parser.add_argument("--plan-rel", default=PLAN_REL_DEFAULT)
    parser.add_argument("--ops-only", action="store_true")
    parser.add_argument("--smoke-only", action="store_true")
    args = parser.parse_args(argv)

    print("LIVE CANARY PREFLIGHT (#790)")
    print(f"ops_root={args.ops_root}  code_root={args.code_root}")
    all_rows: list[tuple[str, bool, str]] = []
    canary_event: tuple[str, int] | None = None

    if not args.smoke_only:
        print("\n-- ops gates --")
        ops_rows, canary_event = _ops_gates(
            root=args.ops_root,
            tip_merge=args.tip_merge,
            tip_plan=args.tip_plan,
            plan_rel=args.plan_rel,
        )
        all_rows.extend(ops_rows)

    if not args.ops_only:
        print("\n-- forecast blocker smokes (provider-free) --")
        # Import from code root (worktree or ops tip)
        os.chdir(args.code_root)
        all_rows.extend(_blocker_smokes(args.code_root))

    failed = [name for name, ok, _ in all_rows if not ok]
    print()
    if failed:
        print(f"RESULT: BLOCKED ({len(all_rows) - len(failed)}/{len(all_rows)})")
        print("DO NOT apply/canary until FAIL lines are green.")
        return 1
    print(f"RESULT: READY ({len(all_rows)}/{len(all_rows)})")
    if canary_event is not None:
        print(f"CANARY_EVENT={canary_event[0]}")
        print(f"CANARY_LEDGER={canary_event[1]}")
    print(f"DISPOSITION={DISP}")
    print(f"PLAN={args.tip_plan}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
