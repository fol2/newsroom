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
# Must stay inside the proving HTTP retention window of `_proving()`
# (fetched_at 2026-08-16, seven days). Consume uses this same instant.
OBSERVED_AT = datetime(2026, 8, 20, 0, 1, tzinfo=UTC)
EXACT_HEAD = "e1d8cbff65e039e3f6393b64cba0f7310f976fa5"
EVENT_13361 = (
    "sha256:90c3b4de731f2df8d4353e516762f65450570e1e8372ed7b703423f717351ae7"
)
SUCCESSOR_EVENT_ID = (
    "sha256:db17fb48469b96b7134b9f0ab7c73c27ddc2f4ebb3bc6016fe268b6326ccb08e"
)
SUCCESSOR_LEDGER_SEQ = 13671
EVENT_13677 = (
    "sha256:1f60dac732657a0d89a9d46528aed13bcd7e2af5157a5bc6541bed579067705c"
)
LEDGER_13677 = 13677
EVENT_13683 = (
    "sha256:7d7bd60fac66b52c7e945a97021570e4220e3fdee0c01af4ee744a50a3993944"
)
LEDGER_13683 = 13683
EVENT_13689 = (
    "sha256:0cf4c6da7a7be611d10fb87f82a7038ca42296f6112d5a2a03fcfb35abde9a39"
)
LEDGER_13689 = 13689
EVENT_13690 = (
    "sha256:57bfeadea2a60c8f24a269c0985611ea8828fcaeaccbfd1b7bed84b537293666"
)
LEDGER_13690 = 13690


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


def _bind_candidate(
    connection: sqlite3.Connection,
    source_event_id: str,
    *,
    event_id: str,
    ledger_seq: int,
) -> None:
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
    manifest["ledger_seq"] = ledger_seq
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
            event_id,
            ledger_seq,
            manifest_json,
            digest_canonical(manifest),
            source_event_id,
        ),
    )


def _spent_13665() -> dict[str, object]:
    return {
        "attempt_count": 1,
        "available_at": "2026-08-31T15:24:40.761622Z",
        "event_id": CANDIDATE_EVENT_ID,
        "last_failure_code": "BOUNDED_CANARY_AUTHORITY_EXHAUSTED:AMBIGUOUS_EFFECT",
        "ledger_seq": CANDIDATE_LEDGER_SEQ,
        "provider_dispatched": True,
        "state": "CONFIGURATION_HELD",
    }


def _spent_13671() -> dict[str, object]:
    return {
        "attempt_count": 1,
        "available_at": "2026-08-31T17:39:23.783082Z",
        "event_id": SUCCESSOR_EVENT_ID,
        "last_failure_code": "BOUNDED_CANARY_AUTHORITY_EXHAUSTED:BrokerError",
        "ledger_seq": SUCCESSOR_LEDGER_SEQ,
        "provider_dispatched": False,
        "state": "CONFIGURATION_HELD",
    }


def _spent_13677() -> dict[str, object]:
    return {
        "attempt_count": 1,
        "available_at": "2026-08-31T19:05:29.017000Z",
        "event_id": EVENT_13677,
        "last_failure_code": "BOUNDED_CANARY_AUTHORITY_EXHAUSTED:AMBIGUOUS_EFFECT",
        "ledger_seq": LEDGER_13677,
        "provider_dispatched": True,
        "state": "CONFIGURATION_HELD",
    }


def _spent_13683() -> dict[str, object]:
    return {
        "attempt_count": 1,
        "available_at": "2026-08-31T19:54:47.602000Z",
        "event_id": EVENT_13683,
        "last_failure_code": "BOUNDED_CANARY_AUTHORITY_EXHAUSTED:AMBIGUOUS_EFFECT",
        "ledger_seq": LEDGER_13683,
        "provider_dispatched": True,
        "state": "CONFIGURATION_HELD",
    }


def _spent_13689() -> dict[str, object]:
    return {
        "attempt_count": 1,
        "available_at": "2026-08-31T21:13:35.000000Z",
        "event_id": EVENT_13689,
        "last_failure_code": "BOUNDED_CANARY_AUTHORITY_EXHAUSTED:NO_EVENT_RESULT",
        "ledger_seq": LEDGER_13689,
        "provider_dispatched": False,
        "state": "CONFIGURATION_HELD",
    }


def build_rehearsal_stores(
    tmp_path: Path,
    *,
    successor: bool = False,
    unused_13677: bool = False,
    unused_13683: bool = False,
    unused_13689: bool = False,
    unused_13690: bool = False,
) -> RehearsalStores:
    """Full sqlite backup-style copy with unused 13665 and drifted 13361."""

    if sum(
        (successor, unused_13677, unused_13683, unused_13689, unused_13690)
    ) > 1:
        raise ValueError(
            "successor, unused_13677, unused_13683, unused_13689 and "
            "unused_13690 are mutually exclusive"
        )
    clock = MutableClock(OBSERVED_AT)
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
        if unused_13690:
            unused = {
                "event_id": EVENT_13690,
                "ledger_seq": LEDGER_13690,
            }
            _bind_candidate(
                connection,
                source_event_id,
                event_id=str(unused["event_id"]),
                ledger_seq=int(unused["ledger_seq"]),
            )
            _insert_retry_forbidden_rows(
                connection,
                [
                    _spent_13665(),
                    _spent_13671(),
                    _spent_13677(),
                    _spent_13683(),
                    _spent_13689(),
                ],
                live_13361_drift=False,
            )
        elif unused_13689:
            _bind_candidate(
                connection,
                source_event_id,
                event_id=EVENT_13689,
                ledger_seq=LEDGER_13689,
            )
            _insert_retry_forbidden_rows(
                connection,
                [_spent_13665(), _spent_13671(), _spent_13677(), _spent_13683()],
                live_13361_drift=False,
            )
        elif unused_13683:
            unused = _spent_13683()
            _bind_candidate(
                connection,
                source_event_id,
                event_id=str(unused["event_id"]),
                ledger_seq=int(unused["ledger_seq"]),
            )
            _insert_retry_forbidden_rows(
                connection,
                [_spent_13665(), _spent_13671(), _spent_13677()],
                live_13361_drift=False,
            )
        elif unused_13677:
            unused = _spent_13677()
            _bind_candidate(
                connection,
                source_event_id,
                event_id=str(unused["event_id"]),
                ledger_seq=int(unused["ledger_seq"]),
            )
            _insert_retry_forbidden_rows(
                connection,
                [_spent_13665(), _spent_13671()],
                live_13361_drift=False,
            )
        elif successor:
            _bind_candidate(
                connection,
                source_event_id,
                event_id=SUCCESSOR_EVENT_ID,
                ledger_seq=SUCCESSOR_LEDGER_SEQ,
            )
            _insert_retry_forbidden_rows(
                connection,
                [_spent_13665()],
                live_13361_drift=False,
            )
        else:
            _bind_candidate(
                connection,
                source_event_id,
                event_id=CANDIDATE_EVENT_ID,
                ledger_seq=CANDIDATE_LEDGER_SEQ,
            )
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


def insert_unused_queued_attempt_zero(
    store: Path,
    *,
    source_ledger_seq: int,
    event_id: str,
    ledger_seq: int,
) -> None:
    """Clone a later unused QUEUED attempt-0 identity from an existing event.

    Live 13690 landed after 13689 aborted. The successor keeps a distinct
    source/item identity so UNIQUE(source, item, revision) stays intact.
    """

    connection = sqlite3.connect(store)
    try:
        source = connection.execute(
            "SELECT source_id,item_key,revision_digest,published_at,updated_at,"
            "landed_at,manifest_json,unit_count,projector_version,"
            "projection_generation,available_at,proposal_count "
            "FROM unpublished_graphiti_revision_events WHERE ledger_seq=?",
            (source_ledger_seq,),
        ).fetchone()
        if source is None:
            raise AssertionError(f"source event {source_ledger_seq} is absent")
        manifest = json.loads(str(source[6]))
        if not isinstance(manifest, dict):
            raise AssertionError("source event manifest is malformed")
        manifest["ledger_seq"] = ledger_seq
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
                last_failure_code,provider_dispatched,claim_owner,
                claim_expires_at,terminal_at,proposal_count
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                event_id,
                ledger_seq,
                event_id,
                f"{source[0]}-{ledger_seq}",
                f"{source[1]}-{ledger_seq}",
                source[2],
                source[3],
                source[4],
                source[5],
                manifest_json,
                digest_canonical(manifest),
                source[7],
                source[8],
                source[9],
                "QUEUED",
                0,
                source[10],
                None,
                0,
                None,
                None,
                None,
                source[11],
            ),
        )
        connection.commit()
    finally:
        connection.close()


def transfer_proving_identity(
    store: Path, *, spent_ledger_seq: int, unused_ledger_seq: int
) -> None:
    """Give a successor the spent event's proving 5-tuple after seal.

    UNIQUE(source, item, revision, published, updated) can only hold one
    row. After 13689 is sealed it no longer needs proving lookup; 13690 does.
    """

    connection = sqlite3.connect(store)
    try:
        spent = connection.execute(
            "SELECT source_id,item_key,revision_digest,published_at,updated_at "
            "FROM unpublished_graphiti_revision_events WHERE ledger_seq=?",
            (spent_ledger_seq,),
        ).fetchone()
        unused = connection.execute(
            "SELECT 1 FROM unpublished_graphiti_revision_events WHERE ledger_seq=?",
            (unused_ledger_seq,),
        ).fetchone()
        if spent is None or unused is None:
            raise AssertionError("spent or unused event is absent")
        connection.execute(
            "UPDATE unpublished_graphiti_revision_events "
            "SET source_id=?, item_key=? WHERE ledger_seq=?",
            (f"{spent[0]}-spent", f"{spent[1]}-spent", spent_ledger_seq),
        )
        connection.execute(
            "UPDATE unpublished_graphiti_revision_events "
            "SET source_id=?, item_key=?, revision_digest=?, published_at=?, "
            "updated_at=? WHERE ledger_seq=?",
            (
                spent[0],
                spent[1],
                spent[2],
                spent[3],
                spent[4],
                unused_ledger_seq,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def event_identity(store: Path, ledger_seq: int) -> tuple[str, int, str]:
    connection = sqlite3.connect(f"{store.absolute().as_uri()}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT event_id,ledger_seq,state,attempt_count,provider_dispatched "
            "FROM unpublished_graphiti_revision_events WHERE ledger_seq=?",
            (ledger_seq,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise AssertionError(f"event {ledger_seq} is absent")
    return str(row[0]), int(row[1]), str(row[2])


def candidate_identity(store: Path) -> tuple[str, int, str]:
    return event_identity(store, CANDIDATE_LEDGER_SEQ)


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
