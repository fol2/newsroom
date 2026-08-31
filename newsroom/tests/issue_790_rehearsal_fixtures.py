"""Representative unpublished copy for issue #790 PreparedCanary rehearsal."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from newsroom.authority.canonical import digest_canonical
from newsroom.control_plane.issue_790_canary import Issue790CanaryRepository
from newsroom.control_plane.issue_790_disposition import (
    ISSUE_790_STEP22_PENDING_PLAN_PATH,
)
from newsroom.control_plane.issue_790_prepared_canary import (
    CANDIDATE_EVENT_ID,
    CANDIDATE_LEDGER_SEQ,
)
from newsroom.control_plane.issue_790_rehearsal import sqlite_backup_copy
from newsroom.control_plane.model_usage import ModelUsageService
from newsroom.tests.test_graphiti_event_consumer import (
    MutableClock,
    _projected_zero_ref_event,
)

_ROOT = Path(__file__).resolve().parents[2]
SEALED_13361_AVAILABLE_AT = "2026-08-30T20:58:43.662872Z"
LIVE_13361_AVAILABLE_AT = "2026-08-30T21:29:18.946358Z"
OBSERVED_AT = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
EXACT_HEAD = "e1d8cbff65e039e3f6393b64cba0f7310f976fa5"
EVENT_13361 = (
    "sha256:90c3b4de731f2df8d4353e516762f65450570e1e8372ed7b703423f717351ae7"
)


@dataclass(frozen=True, slots=True)
class RehearsalStores:
    proving: Path
    sealed_unpublished: Path
    work_unpublished: Path
    plan: dict[str, object]
    sealed_digest: str


def pending_plan() -> dict[str, object]:
    return json.loads((_ROOT / ISSUE_790_STEP22_PENDING_PLAN_PATH).read_text())


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _insert_retry_forbidden_rows(
    connection: sqlite3.Connection,
    events: list[dict[str, object]],
    *,
    live_13361_drift: bool,
) -> None:
    for item in events:
        seq = int(item["ledger_seq"])
        event_id = str(item["event_id"])
        available_at = str(item["available_at"])
        if live_13361_drift and seq == 13361:
            available_at = LIVE_13361_AVAILABLE_AT
        manifest = {
            "event_type": "EFFECTIVE_SOURCE_REVISION_LANDED",
            "landed_ingest_ids": [],
            "landed_payload_digest": "sha256:" + "00" * 32,
            "ledger_digest": event_id,
            "ledger_seq": seq,
            "unit_refs": [],
        }
        manifest_json = json.dumps(
            manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        connection.execute(
            """
            INSERT INTO unpublished_graphiti_revision_events(
                event_id,ledger_seq,ledger_digest,source_id,item_key,
                revision_digest,published_at,updated_at,landed_at,
                manifest_json,manifest_digest,unit_count,projector_version,
                projection_generation,state,attempt_count,available_at,
                last_failure_code,provider_dispatched
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                event_id,
                seq,
                event_id,
                f"RF-{seq}",
                f"item-{seq}",
                event_id,
                str(item.get("available_at") or ""),
                "",
                available_at,
                manifest_json,
                digest_canonical(manifest),
                0,
                "issue-790-rehearsal-projector",
                "issue-790-rehearsal-projection",
                str(item["state"]),
                int(item["attempt_count"]),
                available_at,
                item.get("last_failure_code"),
                int(bool(item["provider_dispatched"])),
            ),
        )


def _bind_candidate_13665(connection: sqlite3.Connection, source_event_id: str) -> None:
    row = connection.execute(
        "SELECT manifest_json FROM unpublished_graphiti_revision_events "
        "WHERE event_id=?",
        (source_event_id,),
    ).fetchone()
    if row is None:
        raise AssertionError("projected Graphiti event is absent")
    manifest = json.loads(str(row[0]))
    if not isinstance(manifest, dict):
        raise AssertionError("projected Graphiti event manifest is malformed")
    manifest["ledger_seq"] = CANDIDATE_LEDGER_SEQ
    manifest_json = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    connection.execute(
        """
        UPDATE unpublished_graphiti_revision_events
        SET event_id=?, ledger_seq=?, manifest_json=?, manifest_digest=?
        WHERE event_id=?
        """,
        (
            CANDIDATE_EVENT_ID,
            CANDIDATE_LEDGER_SEQ,
            manifest_json,
            digest_canonical(manifest),
            source_event_id,
        ),
    )


def build_rehearsal_stores(tmp_path: Path) -> RehearsalStores:
    """Full sqlite backup-style copy with unused 13665 and drifted 13361."""

    clock = MutableClock(datetime(2026, 8, 20, 0, 1, tzinfo=UTC))
    proving, unpublished, source_event_id, _ledger_seq = _projected_zero_ref_event(
        tmp_path, clock
    )
    plan = pending_plan()
    assert any(
        item["event_id"] == EVENT_13361 and item["ledger_seq"] == 13361
        for item in plan["retry_forbidden_events"]
    )
    ModelUsageService(str(unpublished))
    Issue790CanaryRepository(str(unpublished))
    connection = sqlite3.connect(unpublished)
    try:
        _bind_candidate_13665(connection, source_event_id)
        _insert_retry_forbidden_rows(
            connection,
            list(plan["retry_forbidden_events"]),
            live_13361_drift=True,
        )
        connection.commit()
    finally:
        connection.close()
    sealed = tmp_path / "sealed_unpublished.sqlite3"
    sqlite_backup_copy(Path(unpublished), sealed)
    work = tmp_path / "work_unpublished.sqlite3"
    sqlite_backup_copy(sealed, work)
    return RehearsalStores(
        proving=Path(proving),
        sealed_unpublished=sealed,
        work_unpublished=work,
        plan=plan,
        sealed_digest=file_digest(sealed),
    )


def candidate_identity(store: Path) -> tuple[str, int, str]:
    connection = sqlite3.connect(f"{store.absolute().as_uri()}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT event_id,ledger_seq,state,attempt_count,provider_dispatched "
            "FROM unpublished_graphiti_revision_events WHERE ledger_seq=?",
            (CANDIDATE_LEDGER_SEQ,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise AssertionError("candidate 13665 is absent")
    return str(row[0]), int(row[1]), str(row[2])


def retry_available_at(store: Path, ledger_seq: int) -> str:
    connection = sqlite3.connect(f"{store.absolute().as_uri()}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT available_at FROM unpublished_graphiti_revision_events "
            "WHERE ledger_seq=?",
            (ledger_seq,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise AssertionError(f"retry-forbidden {ledger_seq} is absent")
    return str(row[0])


_ALLOWED_MUTATIONS = frozenset(
    {
        "attempt_count",
        "claim_expires_at",
        "claim_owner",
        "last_failure_code",
        "provider_dispatched",
        "state",
    }
)


def mutate_retry_field(
    store: Path, *, ledger_seq: int, field: str, value: object
) -> None:
    if field not in _ALLOWED_MUTATIONS:
        raise ValueError(f"unsupported retry mutation field: {field}")
    connection = sqlite3.connect(store)
    try:
        connection.execute(
            f"UPDATE unpublished_graphiti_revision_events SET {field}=? "
            "WHERE ledger_seq=?",
            (value, ledger_seq),
        )
        connection.commit()
    finally:
        connection.close()


def dispatch_started_count(store: Path) -> int:
    connection = sqlite3.connect(f"{store.absolute().as_uri()}?mode=ro", uri=True)
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "model_transport_observations" not in tables:
            return 0
        row = connection.execute(
            "SELECT COUNT(*) FROM model_transport_observations "
            "WHERE state='DISPATCH_STARTED'"
        ).fetchone()
    finally:
        connection.close()
    return 0 if row is None else int(row[0])
