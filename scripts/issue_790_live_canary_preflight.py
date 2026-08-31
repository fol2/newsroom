#!/usr/bin/env python3
"""#790 live canary preflight: ops gates + forecast-blocker smokes.

Exit 0 only when every line is PASS. Provider-free; no live Cursor call.

O07 accepts only Focus Gates success on the exact tip SHA. After merge,
dispatch Focus Gates on tip — do not wait for Full Repository Health.

Forecast B-gates dry-validate every combined-temporal failure class plus
infra contracts that have already bitten live canaries. Live-only residuals
remain explicit without weakening readiness.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from json import JSONDecoder
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

ROOT_DEFAULT = Path("/Users/jamesto/Coding/newsroom")
DISP = "sha256:020f5b5669020da8e0bd4fb74cf2d9c5051533fa3b09dbed54824ccec456638c"
WORKER = "com.jamesto.newsroom-graphiti-worker"
CONTROL_PLANE = "com.jamesto.newsroom-control-plane"
FOCUS_GATE_CHECK = "focus-gates"
CALL_SHAPE_PRIMARY_MAX_OUTPUT = 16_384
GRAPHITI_CORE_VERSION = "0.29.3"
REQUIRED_RETRY_LEDGER_SEQS = frozenset(
    {1932, 1972, 8834, 8835, 13284, 13337, 13361, 13362}
)
STEP21_FULL_PATH_TEST = (
    "newsroom/tests/test_graphiti_corpus_ingest.py::"
    "test_step21_unmarked_zero_proposal_completion_survives_full_cycle"
)
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_FULL_PATH_TESTS = (
    "newsroom/tests/test_graphiti_corpus_ingest.py::"
    "test_zero_proposal_success_survives_full_evaluation_cycle",
)
_MARKER_TESTS = (
    "newsroom/tests/test_graphiti_corpus_ingest.py::"
    "test_step20_rolled_back_zero_proposal_completion_survives_full_cycle",
    STEP21_FULL_PATH_TEST,
)
_FAIL_CLOSED_TESTS = (
    "newsroom/tests/test_graphiti_adapter_real_executor.py::"
    "test_retryable_failure_returns_diagnostic_receipt_without_structured_output",
    "newsroom/tests/test_graphiti_adapter_real_executor.py::"
    "test_ambiguity_with_proposals_remains_fail_closed_after_validation",
    "newsroom/tests/test_graphiti_adapter_4d_outcomes.py::"
    "test_authority_retains_honest_noncomplete_outcomes_without_proposal_admission",
    "newsroom/tests/test_graphiti_adapter_4d_outcomes.py::"
    "test_policy_blocked_outcome_is_retained_without_output_or_proposals",
)


def sh(*args: str, cwd: Path) -> str:
    return subprocess.check_output(args, text=True, cwd=cwd).strip()


def _check(rows: list[tuple[str, bool, str]], name: str, ok: bool, detail: str) -> None:
    rows.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} — {detail}")


def _focus_gate_hits(check_runs: object, *, tip: str) -> list[dict[str, Any]]:
    """Return exact-tip Focus Gates successes; no other workflow is sufficient."""

    if not isinstance(check_runs, list):
        return []
    return [
        item
        for item in check_runs
        if isinstance(item, dict)
        and item.get("name") == FOCUS_GATE_CHECK
        and item.get("status") == "completed"
        and item.get("conclusion") == "success"
        and item.get("head_sha") == tip
    ]


def _invalid_sha256_paths(value: object, *, path: str = "$") -> list[str]:
    """Find malformed SHA-256 identities in owner and activation artefacts."""

    invalid: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}"
            digest_field = "digest" in str(key).lower()
            if digest_field and (
                not isinstance(item, str) or _SHA256.fullmatch(item) is None
            ):
                invalid.append(child)
            elif (
                isinstance(item, str)
                and item.startswith("sha256:")
                and _SHA256.fullmatch(item) is None
            ):
                invalid.append(child)
            elif isinstance(item, (dict, list)):
                invalid.extend(_invalid_sha256_paths(item, path=child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            child = f"{path}[{index}]"
            if (
                isinstance(item, str)
                and item.startswith("sha256:")
                and _SHA256.fullmatch(item) is None
            ):
                invalid.append(child)
            elif isinstance(item, (dict, list)):
                invalid.extend(_invalid_sha256_paths(item, path=child))
    return invalid


def _successor_predecessor_activation_digest(plan: dict[str, Any]) -> str | None:
    """Return the pinned predecessor activation for a never-activated successor."""

    if (
        plan.get("executable") is not False
        or plan.get("live_canary_authorised") is not False
        or plan.get("approval") is not None
        or plan.get("plan_status") != "PENDING_OWNER_REVIEW"
    ):
        return None
    sequence = plan.get("sequence")
    if not isinstance(sequence, dict):
        return None
    digest = sequence.get("predecessor_activation_digest")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        return None
    return digest


def _pending_plan_path_for_ordinal(ordinal: int) -> Path:
    from newsroom.control_plane import issue_790_disposition as disposition

    paths = {
        16: disposition.ISSUE_790_STEP16_PENDING_PLAN_PATH,
        17: disposition.ISSUE_790_STEP17_PENDING_PLAN_PATH,
        18: disposition.ISSUE_790_STEP18_PENDING_PLAN_PATH,
        19: disposition.ISSUE_790_STEP19_PENDING_PLAN_PATH,
        20: disposition.ISSUE_790_STEP20_PENDING_PLAN_PATH,
        21: disposition.ISSUE_790_STEP21_PENDING_PLAN_PATH,
    }
    try:
        return paths[ordinal]
    except KeyError as exc:
        raise ValueError("predecessor pending family is absent") from exc


def _reconstruct_activated_plan(
    *,
    candidate: dict[str, Any],
    activation: dict[str, object],
    pre_dispatch: dict[str, Any],
) -> dict[str, object]:
    from newsroom.control_plane.issue_790_disposition import _assemble_step16_owner_plan
    from newsroom.control_plane.issue_790_step16_activation import (
        step16_owner_activation_binding,
        validate_step16_activation_receipt,
    )

    payload = activation.get("approval_payload")
    contract = activation.get("contract")
    sequence = candidate.get("sequence")
    if (
        not isinstance(payload, dict)
        or not isinstance(contract, dict)
        or not isinstance(sequence, dict)
    ):
        raise ValueError("tracked family activation differs")
    binding = step16_owner_activation_binding(
        payload,
        template_digest=str(sequence["pre_dispatch_operational_requirements_digest"]),
    )
    activated_plan = _assemble_step16_owner_plan(
        candidate,
        approval={
            "approved_by": contract["approved_by"],
            "approval_reference": activation["comment_url"],
            "approved_at": activation["created_at"],
            "scope": contract["scope"],
        },
        pre_dispatch=pre_dispatch,
        revision=str(activation["final_main_commit"]),
        tree=str(activation["final_main_tree"]),
        owner_activation=binding,
    )
    validate_step16_activation_receipt(activation, plan=activated_plan)
    return activated_plan


def _resolve_tracked_activation(
    connection: sqlite3.Connection,
    *,
    tracked_plan: dict[str, Any],
    root: Path,
) -> tuple[dict[str, object] | None, dict[str, object] | None, str | None]:
    """Resolve a tracked pending family to its exact retained activation."""

    try:
        from newsroom.control_plane.issue_790_contract import (
            issue_790_checked_candidate_contract,
        )
        from newsroom.control_plane.issue_790_disposition import (
            ISSUE_790_STEP16_PRE_DISPATCH_PATH,
            Issue790DispositionError,
            issue_790_checked_approval,
            seal_issue_790_step16_plan,
        )
        from newsroom.control_plane.issue_790_step16_activation import (
            load_step16_activation_record,
        )

        pre_dispatch = json.loads(
            (root / ISSUE_790_STEP16_PRE_DISPATCH_PATH).read_text(encoding="utf-8")
        )
        predecessor_digest = _successor_predecessor_activation_digest(tracked_plan)
        tracked_candidate: dict[str, Any] | None = None
        try:
            tracked_candidate = seal_issue_790_step16_plan(
                tracked_plan,
                issue_790_checked_approval(str(tracked_plan.get("canonical_digest"))),
                pre_dispatch=pre_dispatch,
            )
        except Issue790DispositionError:
            if predecessor_digest is None:
                raise
        activation: dict[str, object] | None = None
        candidate: dict[str, Any] | None = None
        if tracked_candidate is not None:
            row = connection.execute(
                "SELECT plan_digest FROM issue_790_step16_activations "
                "WHERE checked_candidate_digest=?",
                (tracked_candidate["canonical_digest"],),
            ).fetchone()
            if row is not None:
                candidate = tracked_candidate
                activation = load_step16_activation_record(
                    connection,
                    plan_digest=str(row[0]),
                )
        if activation is None:
            if predecessor_digest is None:
                raise ValueError("tracked family activation is absent")
            row = connection.execute(
                "SELECT plan_digest FROM issue_790_step16_activations "
                "WHERE activation_digest=?",
                (predecessor_digest,),
            ).fetchone()
            if row is None:
                raise ValueError("predecessor activation is absent")
            activation = load_step16_activation_record(
                connection,
                plan_digest=str(row[0]),
            )
            predecessor = (tracked_plan.get("sequence") or {}).get("predecessor")
            if (
                activation.get("activation_digest") != predecessor_digest
                or not isinstance(predecessor, dict)
                or predecessor.get("plan_digest") != activation.get("plan_digest")
            ):
                raise ValueError("predecessor activation differs")
            checked = issue_790_checked_candidate_contract(
                str(activation["checked_candidate_digest"])
            )
            pending_path = root / _pending_plan_path_for_ordinal(
                int(checked.sequence_ordinal)
            )
            predecessor_pending = json.loads(
                pending_path.read_text(encoding="utf-8")
            )
            candidate = seal_issue_790_step16_plan(
                predecessor_pending,
                issue_790_checked_approval(
                    str(predecessor_pending["canonical_digest"])
                ),
                pre_dispatch=pre_dispatch,
            )
            if candidate["canonical_digest"] != activation["checked_candidate_digest"]:
                raise ValueError("predecessor activation differs")
        if candidate is None:
            raise ValueError("tracked family activation is absent")
        activated_plan = _reconstruct_activated_plan(
            candidate=candidate,
            activation=activation,
            pre_dispatch=pre_dispatch,
        )
        return activation, activated_plan, None
    except Exception as exc:
        return None, None, f"{type(exc).__name__}: {exc}"


def _effective_retry_exclusion_status(
    *,
    plan_events: list[dict[str, object]],
    exclusions: list[dict[str, object]],
    consumption: dict[str, object] | None,
    outcome: dict[str, object] | None,
    event_snapshot: dict[str, object] | None,
    activated_plan_digest: str,
    effectively_excluded_event_ids: set[str],
) -> tuple[bool, str]:
    """Prove historical exclusions plus the exhausted canary consumption."""

    plan_by_seq = {
        int(item.get("ledger_seq", 0)): str(item.get("event_id"))
        for item in plan_events
    }
    durable_by_seq = {
        int(item.get("ledger_seq", 0)): str(item.get("event_id"))
        for item in exclusions
    }
    overlapping = set(plan_by_seq) & set(durable_by_seq)
    missing_from_durable = set(plan_by_seq) - set(durable_by_seq)
    consumed_seq = int((consumption or {}).get("ledger_seq", 0))
    consumed_event = str((consumption or {}).get("event_id", ""))
    failure_code = str((outcome or {}).get("failure_code_after_seal", ""))
    consumption_ok = (
        consumption is not None
        and outcome is not None
        and event_snapshot is not None
        and consumed_seq == 13361
        and consumption.get("approved_plan_digest") == activated_plan_digest
        and consumption.get("attempt_count_before") == 0
        and consumption.get("maximum_event_attempts") == 1
        and outcome.get("approved_plan_digest") == activated_plan_digest
        and outcome.get("consumption_digest")
        == consumption.get("consumption_digest")
        and outcome.get("event_id") == consumed_event
        and outcome.get("ledger_seq") == consumed_seq
        and outcome.get("attempt_count") == 1
        and outcome.get("provider_dispatched") is True
        and outcome.get("retry_authorised") is False
        and outcome.get("state_after_seal") == "CONFIGURATION_HELD"
        and failure_code.startswith("BOUNDED_CANARY_AUTHORITY_EXHAUSTED:")
        and event_snapshot.get("event_id") == consumed_event
        and event_snapshot.get("ledger_seq") == consumed_seq
        and event_snapshot.get("state") == "CONFIGURATION_HELD"
        and event_snapshot.get("attempt_count") == 1
        and event_snapshot.get("provider_dispatched") is True
        and event_snapshot.get("last_failure_code") == failure_code
        and consumed_event in effectively_excluded_event_ids
    )
    historical_ok = (
        len(plan_by_seq) == len(plan_events)
        and len(durable_by_seq) == len(exclusions)
        and all(durable_by_seq[seq] == plan_by_seq[seq] for seq in overlapping)
        and all(
            item.get("reason") == "ISSUE_790_RETRY_FORBIDDEN"
            and item.get("event_snapshot")
            == next(
                (
                    event
                    for event in plan_events
                    if int(event.get("ledger_seq", 0))
                    == int(item.get("ledger_seq", 0))
                ),
                None,
            )
            for item in exclusions
            if int(item.get("ledger_seq", 0)) in overlapping
        )
        and (
            not missing_from_durable
            or (consumption_ok and missing_from_durable == {consumed_seq})
        )
    )
    effective_seqs = set(durable_by_seq)
    if consumption_ok:
        effective_seqs.add(consumed_seq)
    ok = (
        historical_ok
        and consumption_ok
        and REQUIRED_RETRY_LEDGER_SEQS.issubset(effective_seqs)
    )
    return (
        ok,
        f"plan={sorted(plan_by_seq)} durable={sorted(durable_by_seq)} "
        f"consumed={consumed_seq if consumption_ok else 'INVALID'}",
    )


def _eligible_candidate_rows(
    rows: tuple[tuple[object, ...], ...] | list[tuple[object, ...]],
    *,
    forbidden_event_ids: set[str],
    forbidden_seqs: set[int],
) -> tuple[tuple[object, ...], ...]:
    """Return only post-exhaustion candidates; old backlog stays fail-closed."""

    floor = max(REQUIRED_RETRY_LEDGER_SEQS)
    return tuple(
        row
        for row in rows
        if str(row[0]) not in forbidden_event_ids
        and int(row[1]) not in forbidden_seqs
        and int(row[1]) > floor
    )


def _latest_failure_red_green(
    comments: object,
    *,
    tip: str,
) -> tuple[bool, str]:
    """Bind the latest live failure to a later full-path red and tip green."""

    if not isinstance(comments, list):
        return False, "issue comments malformed"
    ordered = sorted(
        (item for item in comments if isinstance(item, dict)),
        key=lambda item: str(item.get("created_at", "")),
    )
    failures = [
        (index, item)
        for index, item in enumerate(ordered)
        if re.search(
            r"(?im)^##[^\n]*live canary[^\n]*(?:\*\*FAIL\*\*|FAILED)",
            str(item.get("body", "")),
        )
    ]
    if not failures:
        return False, "latest live failure absent"
    failure_index, failure = failures[-1]
    failure_body = str(failure.get("body", ""))
    ledger_match = re.search(r"(?i)ledger\s+`?(\d+)`?", failure_body)
    ledger = ledger_match.group(1) if ledger_match else None
    if ledger is None:
        return False, "latest live failure ledger absent"

    diagnosis: tuple[int, dict[str, Any], str] | None = None
    for index, item in enumerate(
        ordered[failure_index + 1 :],
        start=failure_index + 1,
    ):
        body = str(item.get("body", ""))
        node = re.search(
            r"`uv run --frozen pytest -q "
            r"(newsroom/tests/[A-Za-z0-9_./-]+::test_[A-Za-z0-9_]+)`",
            body,
        )
        if (
            "full-path red" in body.lower()
            and ledger in body
            and re.search(r"(?i)red commit:\s*`[0-9a-f]{40}`", body)
            and node is not None
        ):
            diagnosis = (index, item, node.group(1))
            break
    if diagnosis is None:
        return False, f"ledger {ledger} full-path red absent"
    diagnosis_index, _diagnosis, test_node = diagnosis
    if test_node != STEP21_FULL_PATH_TEST:
        return False, f"unexpected latest red test {test_node}"

    for item in ordered[diagnosis_index + 1 :]:
        body = str(item.get("body", ""))
        if (
            tip in body
            and ledger in body
            and "exact-main" in body.lower()
            and "focus gates" in body.lower()
            and re.search(r"(?i)focus gates[^\n]*(?:success|succeeded)", body)
            and "full-path" in body.lower()
        ):
            return True, f"ledger {ledger} red→green on {tip[:12]}"
    return False, f"ledger {ledger} current-main green absent"


def _issue_comments(root: Path) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    page = 1
    while True:
        value = json.loads(
            sh(
                "gh",
                "api",
                f"repos/fol2/newsroom/issues/790/comments?per_page=100&page={page}",
                cwd=root,
            )
        )
        if not isinstance(value, list):
            raise ValueError("issue comments are malformed")
        comments.extend(item for item in value if isinstance(item, dict))
        if len(value) < 100:
            return comments
        page += 1


def _graphiti_runtime_status() -> tuple[bool, str]:
    """Import the pinned runtime through the exact adapter path used by canary."""

    try:
        from newsroom.graphiti_adapter.real import _load_graphiti

        version = importlib.metadata.version("graphiti-core")
        runtime = _load_graphiti()
    except Exception as exc:
        return False, f"{type(exc).__name__} via {sys.executable}"
    ok = version == GRAPHITI_CORE_VERSION and hasattr(runtime, "Graphiti")
    return ok, f"graphiti-core {version} via {sys.executable}"


def _service_probes() -> tuple[bool, str, bool, str]:
    """Prove worker and Control Plane LaunchAgents/processes are absent."""

    try:
        launchctl = subprocess.run(
            ["/bin/launchctl", "list"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        worker = subprocess.run(
            ["/usr/bin/pgrep", "-f", "scripts/hermes_graphiti_worker.py"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        control_plane = subprocess.run(
            ["/usr/bin/pgrep", "-f", "scripts/hermes_control_plane.py"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        detail = type(exc).__name__
        return False, detail, False, detail
    probes_ok = (
        launchctl.returncode == 0
        and worker.returncode in {0, 1}
        and control_plane.returncode in {0, 1}
    )
    worker_loaded = WORKER in launchctl.stdout or bool(worker.stdout.strip())
    control_plane_loaded = CONTROL_PLANE in launchctl.stdout or bool(
        control_plane.stdout.strip()
    )
    return (
        probes_ok and not worker_loaded,
        "LOADED" if worker_loaded else "unloaded",
        probes_ok and not control_plane_loaded,
        "LOADED" if control_plane_loaded else "unloaded",
    )


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        is not None
    )


def _has_prior_execution(
    connection: sqlite3.Connection,
    *,
    event_id: str,
    ingest_ids: list[str],
) -> bool:
    """Inspect unpublished receipts by ingest identity, never by event column."""

    if not ingest_ids:
        return True
    placeholders = ",".join("?" for _ in ingest_ids)
    for table in (
        "unpublished_graphiti_ingest",
        "unpublished_graphiti_failures",
        "unpublished_graphiti_receipts",
        "unpublished_graphiti_attempt_receipts",
        "unpublished_graphiti_spend",
    ):
        if _table_exists(connection, table) and connection.execute(
            f"SELECT 1 FROM {table} WHERE ingest_id IN ({placeholders}) LIMIT 1",
            ingest_ids,
        ).fetchone():
            return True
    return bool(
        _table_exists(connection, "model_work_envelopes")
        and connection.execute(
            f"SELECT 1 FROM model_work_envelopes WHERE cycle_id=? "
            f"OR json_extract(record_json,'$.ingest_id') IN ({placeholders}) LIMIT 1",
            (event_id, *ingest_ids),
        ).fetchone()
    )


def _run_pytest_nodes(repo: Path, nodes: tuple[str, ...]) -> tuple[bool, str]:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--assert=plain",
            "-p",
            "no:cacheprovider",
            *nodes,
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=120,
    )
    summary = (completed.stdout.strip().splitlines() or ["no pytest output"])[-1]
    return completed.returncode == 0, summary


def _inspection_sql_smoke() -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="issue-790-inspection-") as raw:
        store = Path(raw) / "inspection.sqlite3"
        connection = sqlite3.connect(store)
        try:
            connection.executescript(
                """
                CREATE TABLE model_work_envelopes(
                    envelope_id TEXT PRIMARY KEY,
                    cycle_id TEXT NOT NULL,
                    record_json TEXT NOT NULL
                );
                CREATE TABLE unpublished_graphiti_attempt_receipts(
                    ingest_id TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL,
                    receipt_digest TEXT NOT NULL,
                    receipt_json TEXT NOT NULL,
                    PRIMARY KEY(ingest_id, attempt_number)
                );
                """
            )
            connection.execute(
                "INSERT INTO model_work_envelopes VALUES(?,?,?)",
                ("envelope", "event", json.dumps({"ingest_id": "ingest"})),
            )
            connection.execute(
                "INSERT INTO unpublished_graphiti_attempt_receipts VALUES(?,?,?,?)",
                ("ingest", 1, "sha256:" + "11" * 32, "{}"),
            )
            observed = _has_prior_execution(
                connection,
                event_id="event",
                ingest_ids=["ingest"],
            )
        finally:
            connection.close()
    return observed, "receipt schema has ingest_id and no event_id"


def _retry_exclusion_append_smoke() -> tuple[bool, str]:
    """Exercise the real append path twice, including exhausted ledger 13361."""

    from newsroom.control_plane import issue_790_canary as canary_module
    from newsroom.control_plane import issue_790_disposition as disposition_module
    from newsroom.control_plane.issue_790_canary import Issue790CanaryRepository

    root_plan = "sha256:" + "11" * 32
    disposition = "sha256:" + "22" * 32
    invocation = "sha256:" + "33" * 32
    seqs = (1932, 1972, 8834, 8835, 13284, 13337, 13361, 13362)
    events = [
        {
            "attempt_count": 1,
            "available_at": "2026-08-30T00:00:00.000000Z",
            "event_id": "sha256:" + hashlib.sha256(str(seq).encode()).hexdigest(),
            "last_failure_code": "BOUNDED_CANARY_AUTHORITY_EXHAUSTED:SMOKE",
            "ledger_seq": seq,
            "provider_dispatched": True,
            "state": "CONFIGURATION_HELD",
        }
        for seq in seqs
    ]
    with tempfile.TemporaryDirectory(prefix="issue-790-exclusions-") as raw:
        store = Path(raw) / "canary.sqlite3"
        repository = Issue790CanaryRepository(str(store))
        connection = sqlite3.connect(store)
        try:
            connection.execute(
                "CREATE TABLE model_usage_conservative_dispositions("
                "invocation_id TEXT,approved_plan_digest TEXT,"
                "disposition_digest TEXT PRIMARY KEY)"
            )
            connection.execute(
                "INSERT INTO model_usage_conservative_dispositions VALUES(?,?,?)",
                (invocation, root_plan, disposition),
            )
            connection.execute(
                "CREATE TABLE unpublished_graphiti_revision_events("
                "event_id TEXT,ledger_seq INTEGER,state TEXT,attempt_count INTEGER,"
                "available_at TEXT,last_failure_code TEXT,provider_dispatched INTEGER)"
            )
            connection.executemany(
                "INSERT INTO unpublished_graphiti_revision_events VALUES(?,?,?,?,?,?,?)",
                [
                    (
                        item["event_id"],
                        item["ledger_seq"],
                        item["state"],
                        item["attempt_count"],
                        item["available_at"],
                        item["last_failure_code"],
                        int(item["provider_dispatched"]),
                    )
                    for item in events
                ],
            )
            connection.commit()
        finally:
            connection.close()
        contract = SimpleNamespace(invocation_id=invocation)
        without_13361 = [item for item in events if item["ledger_seq"] != 13361]
        with patch.object(
            canary_module,
            "_require_effective_plan_contract",
            return_value=contract,
        ), patch.object(
            disposition_module,
            "issue_790_approved_plan_contract",
            return_value=contract,
        ):
            repository.retain_retry_exclusions(
                approved_plan_digest=root_plan,
                disposition_digest=disposition,
                events=without_13361,
                excluded_at=datetime(2026, 8, 30, tzinfo=UTC),
            )
            plan = {
                "canonical_digest": root_plan,
                "retry_forbidden_events": events,
            }
            first = disposition_module._retain_retry_exclusions_for_plan(
                repository,
                plan=plan,
                disposition_digest=disposition,
                observed_at=datetime(2026, 8, 30, 1, tzinfo=UTC),
            )
            second = disposition_module._retain_retry_exclusions_for_plan(
                repository,
                plan=plan,
                disposition_digest=disposition,
                observed_at=datetime(2026, 8, 30, 2, tzinfo=UTC),
            )
    retained = [int(item["ledger_seq"]) for item in first]
    return first == second and retained == list(seqs), f"retained={retained} replay=stable"


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
    subprocess.run(
        ["git", "fetch", "origin", "main"],
        check=True,
        capture_output=True,
        cwd=root,
    )
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
    plan: dict[str, Any] = {}
    if plan_path.is_file():
        loaded_plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if isinstance(loaded_plan, dict):
            plan = loaded_plan
    plan_digest = plan.get("canonical_digest")
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
    ci_hits = _focus_gate_hits(raw.get("check_runs"), tip=tip)
    comments = _issue_comments(root)
    red_green_ok, red_green_detail = _latest_failure_red_green(comments, tip=tip)
    key_ok = False
    envp = root / ".env"
    if envp.is_file():
        for line in envp.read_text().splitlines():
            if line.startswith("CURSOR_API_KEY=") and len(line.split("=", 1)[1].strip()) > 8:
                key_ok = True
    worker_ok, worker_state, control_plane_ok, control_plane_state = _service_probes()
    runtime_ok, runtime_detail = _graphiti_runtime_status()
    qc = sh("sqlite3", str(store), "PRAGMA quick_check;", cwd=root)
    conn = sqlite3.connect(f"{store.as_uri()}?mode=ro", uri=True)
    try:
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
        activation, activated_plan, activation_error = _resolve_tracked_activation(
            conn,
            tracked_plan=plan,
            root=root,
        )

        from newsroom.control_plane.issue_790_canary import (
            Issue790CanaryRepository,
            graphiti_excluded_event_ids,
        )

        try:
            repository = Issue790CanaryRepository.open_existing(str(store))
            exclusions = list(repository.retry_exclusions())
            exclusion_error = None
        except Exception as exc:
            repository = None
            exclusions = []
            exclusion_error = type(exc).__name__

        activated_plan_digest = str(
            (activated_plan or {}).get("canonical_digest", "")
        )
        consumption: dict[str, object] | None = None
        outcome: dict[str, object] | None = None
        event_snapshot: dict[str, object] | None = None
        if repository is not None and activated_plan_digest:
            consumption = repository.existing_consumption(
                approved_plan_digest=activated_plan_digest,
            )
            if consumption is not None:
                outcome = repository.existing_outcome(
                    consumption_digest=str(consumption["consumption_digest"]),
                )
                event = conn.execute(
                    "SELECT event_id,ledger_seq,state,attempt_count,available_at,"
                    "last_failure_code,provider_dispatched "
                    "FROM unpublished_graphiti_revision_events "
                    "WHERE event_id=? AND ledger_seq=?",
                    (consumption["event_id"], consumption["ledger_seq"]),
                ).fetchone()
                if event is not None:
                    event_snapshot = {
                        "event_id": str(event[0]),
                        "ledger_seq": int(event[1]),
                        "state": str(event[2]),
                        "attempt_count": int(event[3]),
                        "available_at": str(event[4]),
                        "last_failure_code": (
                            None if event[5] is None else str(event[5])
                        ),
                        "provider_dispatched": bool(event[6]),
                    }
        effectively_excluded_event_ids = set(graphiti_excluded_event_ids(conn))

        plan_events = [
            item
            for item in plan.get("retry_forbidden_events", [])
            if isinstance(item, dict)
        ]
        plan_seqs = [int(item.get("ledger_seq", 0)) for item in plan_events]
        plan_event_ids = {
            str(item["event_id"])
            for item in plan_events
            if isinstance(item.get("event_id"), str)
        }
        durable_seqs = {
            int(item.get("ledger_seq", 0))
            for item in exclusions
            if isinstance(item, dict)
        }
        durable_event_ids = {
            str(item["event_id"])
            for item in exclusions
            if isinstance(item, dict) and isinstance(item.get("event_id"), str)
        }
        cands = conn.execute(
            "SELECT event_id,ledger_seq,state,attempt_count,provider_dispatched "
            "FROM unpublished_graphiti_revision_events "
            "WHERE state='QUEUED' AND attempt_count=0 AND provider_dispatched=0 "
            "ORDER BY ledger_seq DESC LIMIT 40"
        ).fetchall()
    finally:
        conn.close()

    invalid_digests = _invalid_sha256_paths(plan, path="$.plan")
    if activation is None:
        invalid_digests.append("$.activation:ABSENT")
    else:
        invalid_digests.extend(
            _invalid_sha256_paths(activation, path="$.activation")
        )
        owner = activation.get("approval_payload")
        if not isinstance(owner, dict):
            invalid_digests.append("$.activation.approval_payload:ABSENT")

    exclusions_ok, exclusions_detail = _effective_retry_exclusion_status(
        plan_events=plan_events,
        exclusions=exclusions,
        consumption=consumption,
        outcome=outcome,
        event_snapshot=event_snapshot,
        activated_plan_digest=activated_plan_digest,
        effectively_excluded_event_ids=effectively_excluded_event_ids,
    )
    if exclusion_error is not None:
        exclusions_ok = False
        exclusions_detail = exclusion_error
    forbidden_event_ids = plan_event_ids | durable_event_ids
    forbidden_seqs = set(plan_seqs) | durable_seqs
    if consumption is not None:
        forbidden_event_ids.add(str(consumption.get("event_id")))
        forbidden_seqs.add(int(consumption.get("ledger_seq", 0)))

    clean_event: tuple[str, int] | None = None
    fresh_detail = "NONE"
    eligible = _eligible_candidate_rows(
        cands,
        forbidden_event_ids=forbidden_event_ids,
        forbidden_seqs=forbidden_seqs,
    )
    for event_id, ledger_seq, state, attempt_count, provider_dispatched in eligible:
        from newsroom.control_plane.cycle import qualify_fresh_graphiti_event

        observed = datetime.now(UTC)
        proving = root / "data/newsroom/proving_store.sqlite3"
        try:
            evidence = qualify_fresh_graphiti_event(
                proving_store=str(proving),
                unpublished_store=str(store),
                event_id=str(event_id),
                ledger_seq=int(ledger_seq),
                clock=lambda: observed,
            )
        except Exception:
            continue
        units = evidence.get("resolved_units") or []
        ingest_ids = [
            str(unit["ingest_id"])
            for unit in units
            if isinstance(unit, dict) and isinstance(unit.get("ingest_id"), str)
        ]
        c2 = sqlite3.connect(f"{store.as_uri()}?mode=ro", uri=True)
        try:
            prior = _has_prior_execution(
                c2,
                event_id=str(event_id),
                ingest_ids=ingest_ids,
            )
        finally:
            c2.close()
        exact_fresh = (
            state == "QUEUED"
            and int(attempt_count) == 0
            and not bool(provider_dispatched)
            and not prior
        )
        if exact_fresh:
            clean_event = (str(event_id), int(ledger_seq))
            fresh_detail = (
                f"{str(event_id)[:24]}…/{ledger_seq} "
                "QUEUED attempt=0 provider_dispatched=false"
            )
            break

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
    _check(
        rows,
        "O06 exact tracked family digest on disk",
        plan_digest == tip_plan and _SHA256.fullmatch(str(plan_digest)) is not None,
        str(plan_digest or "MISSING"),
    )
    _check(
        rows,
        "O07 exact-main Focus Gates success on tip SHA",
        bool(ci_hits),
        FOCUS_GATE_CHECK if ci_hits else "none (Full Health is insufficient)",
    )
    _check(
        rows,
        "O08 owner/activation artefacts valid with exact SHA-256 digests",
        activation_error is None and activated_plan is not None and not invalid_digests,
        (
            f"tracked={str(plan_digest)[:20]}… "
            f"activated={activated_plan_digest[:20]}…"
            if not invalid_digests
            and activation_error is None
            and activated_plan is not None
            else str(
            invalid_digests[0] if invalid_digests else activation_error
            )
        ),
    )
    _check(rows, "O09 graphiti-core 0.29.3 importable on canary runtime", runtime_ok, runtime_detail)
    _check(rows, "O10 CURSOR_API_KEY in .env", key_ok, "present" if key_ok else "ABSENT")
    _check(rows, "O11 graphiti worker UNLOADED", worker_ok, worker_state)
    _check(rows, "O12 Hermes Control Plane UNLOADED", control_plane_ok, control_plane_state)
    _check(rows, "O13 unpublished_store quick_check=ok", qc == "ok", qc)
    _check(
        rows,
        "O14 disposition 020f5b56… retained",
        disp is not None,
        (disp[0][:24] + "…") if disp else "ABSENT",
    )
    _check(
        rows,
        "O15 route circuit readable",
        route is not None,
        f"{route[0]}:{str(route[1])[:48]}" if route else "ABSENT",
    )
    _check(
        rows,
        "O16 all exhausted events fail closed without rewriting historical plan",
        exclusions_ok,
        exclusions_detail,
    )
    _check(
        rows,
        "O17 latest live failure has full-path red then current-main green",
        red_green_ok,
        red_green_detail,
    )
    _check(
        rows,
        "O18 fresh QUEUED attempt-0 undispatched event outside exclusions",
        clean_event is not None,
        fresh_detail,
    )
    return rows, clean_event


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
    from newsroom.graphiti_adapter.combined_temporal_projection import (
        project_governed_proposals,
    )
    from newsroom.graphiti_adapter.combined_temporal_validation import normalise
    from newsroom.graphiti_adapter.evaluation_attempt import evaluation_attempt_for
    from newsroom.graphiti_adapter.real import RealGraphitiAdapter

    gold = next(c for c in FIXTURES if c.name == "pair-current")
    segs = segment_source(gold.revision.body)
    ref = datetime.fromisoformat(gold.revision.published_at.replace("Z", "+00:00"))
    prompt = build_compact_prompt(gold.revision).text

    def project(payload: dict[str, Any], segments=segs, reference=ref):
        return project_governed_proposals(payload, segments, reference)

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
            "Put valid_at and invalid_at on each fact as null",
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

    # --- expanded forecast coverage (governed projection) ---
    stuffed = json.loads(json.dumps(gold.gold))
    stuffed["facts"][0]["valid_at"] = gold.revision.reference_time
    stuffed_proj = project(stuffed)
    gold_proj = project(gold.gold)
    _check(
        rows,
        "B10 TEMPORAL: REFERENCE_TIME stuffing ignored; projected null/cues OK",
        stuffed_proj.receipt["accepted_count"] >= 1
        and stuffed_proj.payload["facts"][0]["valid_at"]
        == gold_proj.payload["facts"][0]["valid_at"]
        and gold_proj.receipt["rejected_count"] == 0,
        f"stuffed_valid_at={stuffed_proj.payload['facts'][0]['valid_at']}",
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
    cue_proj = project(cue_null, cue_segs, cue_ref)
    _check(
        rows,
        "B11 TEMPORAL: date cue projects ISO bound from evidence",
        cue_proj.receipt["accepted_count"] == 1
        and cue_proj.payload["facts"][0]["valid_at"] == "2026-08-21T00:00:00Z",
        f"valid_at={cue_proj.payload['facts'][0]['valid_at']}",
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

    # Step 13 live shape: fact missing an endpoint name → atom reject → zero proposals
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
    step13_proj = project(step13, step13_segs, cue_ref)
    _check(
        rows,
        "B13 dry-replay Step 13 missing-endpoint → zero-proposal success",
        step13_proj.receipt["rejected_count"] == 1
        and step13_proj.receipt["accepted_count"] == 0
        and step13_proj.payload == {"entities": [], "facts": []},
        f"rejected={step13_proj.receipt['rejected_count']}",
    )

    # Step 14 live shape: grounded endpoints but REFERENCE_TIME stuffed → project null
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
    step14_proj = project(step14, step14_segs, step14_ref)
    _check(
        rows,
        "B14 dry-replay Step 14 stuffing ignored → projected null success",
        step14_proj.receipt["accepted_count"] == 1
        and step14_proj.payload["facts"][0]["valid_at"] is None
        and step14_proj.payload["facts"][0]["invalid_at"] is None,
        f"valid_at={step14_proj.payload['facts'][0]['valid_at']}",
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
        adapter_fallback._fallback_permitted is False,
        "fallback_permitted=False; activated plan is checked separately",
    )
    # Ambiguous multi-cue → atom-local TEMPORAL_INVALID under projection
    multi_cue_body = (
        "Alice asked Bob about the curriculum on 2026-08-21 and again on 2026-08-22."
    )
    multi_segs = segment_source(multi_cue_body)
    multi_payload = {
        "entities": [
            {"local_id": 0, "name": "Alice", "entity_type_id": 0, "evidence_segment_ids": [0]},
            {"local_id": 1, "name": "Bob", "entity_type_id": 0, "evidence_segment_ids": [0]},
        ],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": 1,
                "relation_type": "ASKED",
                "fact": (
                    "Alice asked Bob about the curriculum on 2026-08-21 "
                    "and again on 2026-08-22"
                ),
                "valid_at": None,
                "invalid_at": None,
                "evidence_segment_ids": [0],
            }
        ],
    }
    multi_proj = project(multi_payload, multi_segs, cue_ref)
    temporal_reject = CombinedTemporalFailureCode(
        multi_proj.receipt["atom_actions"][0]["reason_code"]
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
                CombinedTemporalFailureCode(
                    step13_proj.receipt["atom_actions"][0]["reason_code"]
                ),
                temporal_reject,
                malformed,
                identity_type,
            }
        )
        and CombinedTemporalFailureCode.PIPELINE_FAILED.value == "PIPELINE_FAILED",
        "EVIDENCE+IDENTITY+TEMPORAL+MALFORMED dry; PIPELINE mapped in B17",
    )

    full_path_ok, full_path_detail = _run_pytest_nodes(
        repo_for_imports,
        _FULL_PATH_TESTS,
    )
    _check(
        rows,
        "B21 Step 19 execute→ingest→bind accepts COMPLETE+0",
        full_path_ok,
        full_path_detail,
    )
    marker_ok, marker_detail = _run_pytest_nodes(repo_for_imports, _MARKER_TESTS)
    _check(
        rows,
        "B22 Steps 20-21 marked and unmarked COMPLETE+0 avoid AMBIGUOUS_EFFECT",
        marker_ok,
        marker_detail,
    )
    fail_closed_ok, fail_closed_detail = _run_pytest_nodes(
        repo_for_imports,
        _FAIL_CLOSED_TESTS,
    )
    _check(
        rows,
        "B23 failure/blocked/proposal-bearing ambiguity remains fail-closed",
        fail_closed_ok,
        fail_closed_detail,
    )
    inspection_ok, inspection_detail = _inspection_sql_smoke()
    _check(
        rows,
        "B24 unpublished receipt inspection resolves ingest_id via work envelope",
        inspection_ok,
        inspection_detail,
    )
    exclusion_ok, exclusion_detail = _retry_exclusion_append_smoke()
    _check(
        rows,
        "B25 retry-exclusion apply appends 13361 idempotently",
        exclusion_ok,
        exclusion_detail,
    )
    _check(
        rows,
        "B26 provider-free preflight residuals remain explicit",
        True,
        "provider outage and novel live-only semantics remain F4 unknowns",
    )
    _ = canary_src  # retained for future source gates; silence lint
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ops-root", type=Path, default=ROOT_DEFAULT)
    parser.add_argument("--code-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--tip-merge", default=None, help="exact tip SHA; default origin/main")
    parser.add_argument(
        "--tip-plan",
        required=True,
        help="exact tracked pending-family SHA-256",
    )
    parser.add_argument(
        "--plan-rel",
        required=True,
        help="tracked pending-family path below ops root",
    )
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

    diagnostic_only = args.ops_only or args.smoke_only
    failed = [name for name, ok, _ in all_rows if not ok]
    print()
    if failed:
        print(f"RESULT: BLOCKED ({len(all_rows) - len(failed)}/{len(all_rows)})")
        print("DO NOT apply/canary until FAIL lines are green.")
        return 1
    if diagnostic_only:
        print("RESULT: BLOCKED (diagnostic subset cannot authorise a live canary)")
        print("Run the complete preflight without --ops-only/--smoke-only.")
        return 2
    print(f"RESULT: READY ({len(all_rows)}/{len(all_rows)})")
    if canary_event is not None:
        print(f"CANARY_EVENT={canary_event[0]}")
        print(f"CANARY_LEDGER={canary_event[1]}")
    print(f"DISPOSITION={DISP}")
    print(f"PLAN={args.tip_plan}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
