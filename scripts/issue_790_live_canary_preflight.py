#!/usr/bin/env python3
"""#790 live canary preflight: ops gates + forecast-blocker smokes.

Exit 0 only when every line is PASS. Provider-free; no live Cursor call.

O07 exact-head CI prefers Focus Gates on the tip SHA. After merge, dispatch
Focus Gates on tip — do not wait for Full Repository Health.

Forecast B-gates dry-validate every combined-temporal failure class plus
infra contracts that have already bitten live canaries. Residual model
non-compliance cannot be proved provider-free; that residual is printed.
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
from typing import Any

ROOT_DEFAULT = Path("/Users/jamesto/Coding/newsroom")
TIP_PLAN_DEFAULT = (
    "sha256:58220d3a2b389ca25bf86f71b4d7974c6186ee26ab705af351091a20228e1db8"
)
PLAN_REL_DEFAULT = "docs/operations/2026-08-28-issue-790-success-sequence-step-15.json"
DISP = "sha256:020f5b5669020da8e0bd4fb74cf2d9c5051533fa3b09dbed54824ccec456638c"
PRED_EVENT = (
    "sha256:3706d21a68b548a0fd5be56c5409a577c24fa265f7270887ac4cf8fce9a74d35"
)
PRED_LEDGER = 8865
WORKER = "com.jamesto.newsroom-graphiti-worker"
ACCEPTED_CI = ("focus-gates", "test", "full-deterministic-health")
CALL_SHAPE_PRIMARY_MAX_OUTPUT = 16_384


def sh(*args: str, cwd: Path) -> str:
    return subprocess.check_output(args, text=True, cwd=cwd).strip()


def _check(rows: list[tuple[str, bool, str]], name: str, ok: bool, detail: str) -> None:
    rows.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} — {detail}")


def _expect_code(
    payload: dict[str, Any],
    segs: Any,
    ref: datetime,
    *,
    normalise: Any,
    CombinedTemporalError: Any,
) -> Any:
    try:
        normalise(payload, segs, ref)
    except CombinedTemporalError as exc:
        return exc.code
    return None


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
    """Provider-free dry validation of forecast live-canary blockers."""

    rows: list[tuple[str, bool, str]] = []
    sys.path.insert(0, str(repo_for_imports))
    from newsroom.control_plane import issue_790_disposition as disp
    from newsroom.control_plane.cycle import qualify_fresh_graphiti_event
    from newsroom.control_plane.graphiti_requests import (
        load_checked_graphiti_call_shape_policy,
    )
    from newsroom.graphiti_adapter.combined_temporal_contract import build_compact_prompt
    from newsroom.graphiti_adapter.combined_temporal_evidence import segment_source
    from newsroom.graphiti_adapter.combined_temporal_fixtures import FIXTURES
    from newsroom.graphiti_adapter.combined_temporal_types import (
        CombinedTemporalError,
        CombinedTemporalFailureCode,
    )
    from newsroom.graphiti_adapter.combined_temporal_validation import normalise
    from newsroom.graphiti_adapter.evaluation_attempt import evaluation_attempt_for
    from newsroom.graphiti_adapter.real import RealGraphitiAdapter

    gold = next(c for c in FIXTURES if c.name == "pair-current")
    segs = segment_source(gold.revision.body)
    ref = datetime.fromisoformat(gold.revision.published_at.replace("Z", "+00:00"))
    prompt = build_compact_prompt(gold.revision).text
    expect = lambda payload: _expect_code(
        payload,
        segs,
        ref,
        normalise=normalise,
        CombinedTemporalError=CombinedTemporalError,
    )

    empty_ok = expect({"entities": [], "facts": []}) is None
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
    contra = expect(contradictory)
    prompt_rules = all(
        token in prompt
        for token in (
            "unique contiguous verbatim span",
            "must be distinct",
            "both endpoint entity names",
            "Do not copy REFERENCE_TIME",
            "no date cue",
            'return {"entities":[],"facts":[]}',
        )
    )
    _check(
        rows,
        "B01 prefer-empty / reject reused fact strings",
        empty_ok and contra is CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED and prompt_rules,
        f"empty={empty_ok} contra={contra} prompt={prompt_rules}",
    )

    gold_ok = expect(gold.gold) is None
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
    amb_code = expect(amb)
    _check(
        rows,
        "B02 gold passes; weak attribution fails",
        gold_ok and amb_code is CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
        f"gold={gold_ok} amb={amb_code}",
    )

    self_code = expect(
        {
            "entities": [gold.gold["entities"][0]],
            "facts": [{**gold.gold["facts"][0], "source_local_id": 0, "target_local_id": 0}],
        }
    )
    orphan_code = expect(
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
        }
    )
    _check(
        rows,
        "B03 IDENTITY self-loop + orphan entity rejected",
        self_code is CombinedTemporalFailureCode.IDENTITY_INVALID
        and orphan_code is CombinedTemporalFailureCode.IDENTITY_INVALID,
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

    disp_src = Path(disp.__file__).read_text(encoding="utf-8")
    term_req = (
        'process_result.get("state") == "TERMINAL"' in disp_src
        and 'event_after_record.get("state") == "TERMINAL"' in disp_src
    )
    _check(rows, "B05 canary pass requires TERMINAL", term_req, "process+event TERMINAL")

    m = re.search(r"truthful_success = bool\([\s\S]*?\)\n", disp_src)
    truthful_block = m.group(0) if m else ""
    _check(
        rows,
        "B06 empty/zero proposals allowed by stop formula",
        empty_ok
        and "proposal" not in truthful_block.lower()
        and any(c.name == "zero-result" for c in FIXTURES),
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
    canary_start = disp_src.find("canary_evidence_passed = bool")
    canary_end = disp_src.find("receipt_without_digest", canary_start)
    canary_block = (
        disp_src[canary_start:canary_end]
        if canary_start >= 0 and canary_end > canary_start
        else ""
    )
    _check(
        rows,
        "B09 embedding not required for canary pass",
        bool(canary_block) and "embed" not in canary_block.lower(),
        f"block_bytes={len(canary_block)} no embedding gate",
    )

    # --- expanded forecast coverage (post Step 14 surprise) ---
    stuffed = json.loads(json.dumps(gold.gold))
    stuffed["facts"][0]["valid_at"] = gold.revision.reference_time
    stuffed_code = expect(stuffed)
    null_ok = expect(gold.gold) is None
    _check(
        rows,
        "B10 TEMPORAL: REFERENCE_TIME stuffing rejected; null bounds OK",
        stuffed_code is CombinedTemporalFailureCode.TEMPORAL_INVALID and null_ok,
        f"stuffed={stuffed_code} null_gold={null_ok}",
    )

    cue_body = "Alice asked Bob about the curriculum on 2026-08-21."
    cue_segs = segment_source(cue_body)
    cue_ref = datetime(2026, 8, 26, 5, 28, 42, tzinfo=UTC)
    cue_null = {
        "entities": [
            {"local_id": 0, "name": "Alice", "entity_type_id": 0, "evidence_segment_ids": [0]},
            {"local_id": 1, "name": "Bob", "entity_type_id": 0, "evidence_segment_ids": [0]},
        ],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": 1,
                "relation_type": "ASKED",
                "fact": "Alice asked Bob about the curriculum on 2026-08-21",
                "valid_at": None,
                "invalid_at": None,
                "evidence_segment_ids": [0],
            }
        ],
    }
    cue_null_code = _expect_code(
        cue_null,
        cue_segs,
        cue_ref,
        normalise=normalise,
        CombinedTemporalError=CombinedTemporalError,
    )
    _check(
        rows,
        "B11 TEMPORAL: date cue with both nulls rejected",
        cue_null_code is CombinedTemporalFailureCode.TEMPORAL_INVALID,
        f"code={cue_null_code}",
    )

    bad_relation = json.loads(json.dumps(gold.gold))
    bad_relation["facts"][0]["relation_type"] = "asked about"
    malformed = expect(bad_relation)
    bad_type = json.loads(json.dumps(gold.gold))
    bad_type["entities"][0]["entity_type_id"] = 1
    identity_type = expect(bad_type)
    _check(
        rows,
        "B12 MALFORMED relation_type + non-zero entity_type_id rejected",
        malformed is CombinedTemporalFailureCode.MALFORMED_OBJECT
        and identity_type is CombinedTemporalFailureCode.IDENTITY_INVALID,
        f"relation={malformed} type_id={identity_type}",
    )

    # Step 13 live shape: fact missing an endpoint name
    step13 = {
        "entities": [
            {"local_id": 0, "name": "Police officer", "entity_type_id": 0, "evidence_segment_ids": [0]},
            {"local_id": 1, "name": "woman", "entity_type_id": 0, "evidence_segment_ids": [0]},
        ],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": 1,
                "relation_type": "STARTED_SEXUAL_RELATIONSHIP_WITH",
                "fact": "starting sexual relationship with woman",
                "valid_at": None,
                "invalid_at": None,
                "evidence_segment_ids": [0],
            }
        ],
    }
    step13_segs = segment_source(
        "Police officer sacked after starting sexual relationship with woman."
    )
    step13_code = _expect_code(
        step13,
        step13_segs,
        cue_ref,
        normalise=normalise,
        CombinedTemporalError=CombinedTemporalError,
    )
    _check(
        rows,
        "B13 dry-replay Step 13 missing-endpoint → EVIDENCE_UNRESOLVED",
        step13_code is CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
        f"code={step13_code}",
    )

    # Step 14 live shape: grounded endpoints but REFERENCE_TIME stuffed
    step14_body = "李家超探訪元州邨居民 試踏健身單車。"
    step14_segs = segment_source(step14_body)
    step14_ref = datetime(2026, 8, 26, 7, 29, 33, tzinfo=UTC)
    step14 = {
        "entities": [
            {"local_id": 0, "name": "李家超", "entity_type_id": 0, "evidence_segment_ids": [0]},
            {"local_id": 1, "name": "元州邨", "entity_type_id": 0, "evidence_segment_ids": [0]},
        ],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": 1,
                "relation_type": "VISITED",
                "fact": "李家超探訪元州邨居民",
                "valid_at": "2026-08-26T07:29:33.000000Z",
                "invalid_at": None,
                "evidence_segment_ids": [0],
            }
        ],
    }
    step14_code = _expect_code(
        step14,
        step14_segs,
        step14_ref,
        normalise=normalise,
        CombinedTemporalError=CombinedTemporalError,
    )
    step14_null = json.loads(json.dumps(step14))
    step14_null["facts"][0]["valid_at"] = None
    step14_null_code = _expect_code(
        step14_null,
        step14_segs,
        step14_ref,
        normalise=normalise,
        CombinedTemporalError=CombinedTemporalError,
    )
    _check(
        rows,
        "B14 dry-replay Step 14 REFERENCE_TIME valid_at → TEMPORAL_INVALID; null OK",
        step14_code is CombinedTemporalFailureCode.TEMPORAL_INVALID
        and step14_null_code is None,
        f"stuffed={step14_code} null={step14_null_code}",
    )

    attempt = evaluation_attempt_for(("A retained source passage.",))
    budget = attempt.extraction_request.budget.max_response_tokens
    policy = load_checked_graphiti_call_shape_policy()
    primary = next(r for r in policy.qualified_routes if r.leaf_class.value == "PRIMARY")
    _check(
        rows,
        "B15 extraction budget matches call-shape PRIMARY max_output",
        budget == CALL_SHAPE_PRIMARY_MAX_OUTPUT
        and int(primary.max_output_tokens) == CALL_SHAPE_PRIMARY_MAX_OUTPUT,
        f"budget={budget} call_shape={primary.max_output_tokens}",
    )

    cycle_src = (
        repo_for_imports / "newsroom/control_plane/cycle.py"
    ).read_text(encoding="utf-8")
    real_src = (
        repo_for_imports / "newsroom/graphiti_adapter/real.py"
    ).read_text(encoding="utf-8")
    usage_src = (
        repo_for_imports / "newsroom/control_plane/model_usage.py"
    ).read_text(encoding="utf-8")
    _check(
        rows,
        "B16 attempt receipt retains combined_temporal_failure_code",
        'receipt["combined_temporal_failure_code"] = fine' in cycle_src
        or (
            "combined_temporal_failure_code" in cycle_src
            and 'receipt["combined_temporal_failure_code"]' in cycle_src
        ),
        "cycle._receipt copies fine code",
    )
    _check(
        rows,
        "B17 PIPELINE_FAILED maps to PRODUCER_INTERNAL_ERROR (not schema)",
        "PIPELINE_FAILED" in real_src
        and "PRODUCER_INTERNAL_ERROR" in real_src
        and "combined_temporal_failure_code" in real_src,
        "real.validate_failure pipeline branch present",
    )
    _check(
        rows,
        "B18 canary policy_breach does not permanently block successor apply",
        "canary_non_success_leaf" in usage_src
        or "issue_790" in usage_src.lower()
        and "policy_breach" in usage_src,
        "usage blocking route exemption present",
    )

    canary_src = (
        repo_for_imports / "newsroom/control_plane/issue_790_canary.py"
    ).read_text(encoding="utf-8")
    adapter_fallback = RealGraphitiAdapter(fallback_permitted=False)
    _check(
        rows,
        "B19 canary fallback remains disabled before provider dispatch",
        adapter_fallback._fallback_permitted is False
        and "DISABLED_BEFORE_PROVIDER_DISPATCH" in (
            (repo_for_imports / PLAN_REL_DEFAULT).read_text(encoding="utf-8")
            if (repo_for_imports / PLAN_REL_DEFAULT).is_file()
            else (repo_for_imports / "docs/operations/2026-08-28-issue-790-success-sequence-step-14.json").read_text(encoding="utf-8")
            if (repo_for_imports / "docs/operations/2026-08-28-issue-790-success-sequence-step-14.json").is_file()
            else ""
        ),
        "fallback_permitted=False + plan fallback_mode",
    )
    _check(
        rows,
        "B20 all CombinedTemporalFailureCode failure values are exercised above",
        {
            CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
            CombinedTemporalFailureCode.IDENTITY_INVALID,
            CombinedTemporalFailureCode.TEMPORAL_INVALID,
            CombinedTemporalFailureCode.MALFORMED_OBJECT,
        }.issubset(
            {
                contra,
                amb_code,
                self_code,
                orphan_code,
                stuffed_code,
                cue_null_code,
                malformed,
                identity_type,
                step13_code,
                step14_code,
            }
        )
        and CombinedTemporalFailureCode.PIPELINE_FAILED.value == "PIPELINE_FAILED",
        "EVIDENCE+IDENTITY+TEMPORAL+MALFORMED dry; PIPELINE mapped in B17",
    )

    print(
        "RESIDUAL (cannot preflight provider-free): model still ignoring "
        "prefer-empty / temporal-null; provider outage; Neo4j pipeline after "
        "a schema-valid extract; novel attribution edge cases."
    )
    _ = canary_src  # retained for future source gates; silence lint
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
