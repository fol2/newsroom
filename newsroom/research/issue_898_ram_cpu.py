"""Provider-free Mini RAM/CPU packet for issue #898.

Stdlib-only at import time so baseline children are not contaminated.
Does not claim queue events, write canonical stores, or start Rust.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import resource
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

UNOBSERVED = "UNOBSERVED"
ISSUE = 898
CLOCK = datetime(2026, 8, 20, tzinfo=UTC)
FETCHED_AT = "2026-08-16T21:41:34.000000Z"
RIGHTS_ASSESSED_AT = "2026-08-20T00:00:00.000000Z"
RIGHTS_EXPIRES_AT = "2099-01-01T00:00:00.000000Z"
WARMUPS = 1
MEASURED_RUNS = 3
MIB = 1024 * 1024
GO_PEAK_RATIO = 0.20
GO_PEAK_BYTES = 64 * MIB

ATOM = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<feed xmlns="http://www.w3.org/2005/Atom">'
    b"<entry><id>urn:example:1</id><title>Home Office update</title>"
    b'<link href="https://www.gov.uk/example-1"/>'
    b"<summary>A retained proving item.</summary></entry></feed>"
)
JSON_DOC = (
    b'{"title":"BNO visa","base_path":"/british-national-overseas-bno-visa",'
    b'"content_id":"abc","description":"Apply for a visa."}'
)


def rss_body(*, guid: str, title: str, description: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<rss version=\"2.0\"><channel><item>"
        f"<guid>{guid}</guid><title>{title}</title>"
        "<link>https://www.news.gov.hk/a</link>"
        f"<description>{description}</description>"
        "</item></channel></rss>"
    ).encode("utf-8")


def current_rss_bytes() -> int | str:
    try:
        out = subprocess.check_output(
            ["ps", "-o", "rss=", "-p", str(os.getpid())],
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return UNOBSERVED
    text = out.strip().split()
    if not text:
        return UNOBSERVED
    return int(text[0]) * 1024


def maxrss_bytes(raw: int) -> int:
    if sys.platform == "darwin":
        return int(raw)
    return int(raw) * 1024


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def canonical_store_paths() -> tuple[Path, Path]:
    from newsroom.control_plane.paths import (
        CANONICAL_PROVING_STORE,
        CANONICAL_UNPUBLISHED_STORE,
    )

    return CANONICAL_PROVING_STORE.resolve(), CANONICAL_UNPUBLISHED_STORE.resolve()


def refuse_canonical_store(path: str | Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    proving, unpublished = canonical_store_paths()
    if resolved in {proving, unpublished}:
        raise RuntimeError(f"refusing canonical store path: {resolved}")
    return resolved


def copy_canonical_proving(destination: Path) -> dict[str, object]:
    proving, _unpublished = canonical_store_paths()
    refuse_canonical_store(destination)
    if not proving.is_file():
        return {"status": UNOBSERVED, "reason": "canonical proving store missing"}
    source_size = proving.stat().st_size
    reuse = (
        destination.is_file()
        and destination.stat().st_size == source_size
    )
    if not reuse:
        shutil.copy2(proving, destination)
        for suffix in ("-wal", "-shm"):
            side = Path(str(proving) + suffix)
            if side.exists():
                shutil.copy2(side, Path(str(destination) + suffix))
    return {
        "status": "COPIED",
        "reused_existing_copy": reuse,
        "source_path_name": proving.name,
        "source_size_bytes": source_size,
        "copy_digest": (
            f"reuse:{source_size}:{destination.stat().st_mtime_ns}"
            if reuse
            else _sha256_file(destination)
        ),
        "writable_canonical": False,
    }


def _rights_packet(source_id: str) -> dict[str, object]:
    from newsroom.graphiti_adapter.evaluation_packet import (
        GRAPHITI_EVALUATION_DESTINATION_TOKENS,
    )
    from newsroom.increment9.rights import FIXTURE_DESTINATIONS, fixture_inventory

    return fixture_inventory(
        gate=f"RIGHTS_{source_id}",
        destinations=tuple(sorted({*FIXTURE_DESTINATIONS, *GRAPHITI_EVALUATION_DESTINATION_TOKENS})),
        now=RIGHTS_ASSESSED_AT,
        issued_at="2026-01-01T00:00:00.000000Z",
        expires_at=RIGHTS_EXPIRES_AT,
    )


def write_proving_store(path: Path, rows: tuple[tuple[str, bytes], ...]) -> None:
    from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
    from newsroom.effective_revision import (
        create_effective_revision_schema,
        retain_observation_revision_first_seen,
    )
    from newsroom.increment9.proving import PROVING_GATES, SOURCE_URLS

    refuse_canonical_store(path)
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE proving_runs(
            run_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            publication INTEGER NOT NULL DEFAULT 0,
            public_dispatch INTEGER NOT NULL DEFAULT 0,
            openrouter_invoked INTEGER NOT NULL DEFAULT 0,
            spend_gbp_minor INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE proving_observations(
            source_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            url TEXT NOT NULL,
            status_code INTEGER NOT NULL,
            body_digest TEXT NOT NULL,
            body BLOB NOT NULL,
            item_count INTEGER NOT NULL,
            error TEXT
        );
        CREATE TABLE proving_gates(
            run_id TEXT NOT NULL,
            gate_id TEXT NOT NULL,
            status TEXT NOT NULL,
            reason TEXT NOT NULL,
            PRIMARY KEY(run_id, gate_id)
        );
        CREATE TABLE proving_rights_packets(
            run_id TEXT NOT NULL,
            gate_id TEXT NOT NULL,
            packet_digest TEXT NOT NULL,
            packet_json TEXT NOT NULL,
            assessed_at TEXT NOT NULL,
            PRIMARY KEY(run_id, gate_id)
        );
        """
    )
    create_effective_revision_schema(connection)
    connection.execute(
        """
        INSERT INTO proving_runs(
            run_id, started_at, publication, public_dispatch,
            openrouter_invoked, spend_gbp_minor
        ) VALUES('run-1', ?, 0, 0, 0, 0)
        """,
        (FETCHED_AT,),
    )
    sources: list[str] = []
    for source_id, body in rows:
        url = SOURCE_URLS[source_id]
        connection.execute(
            "INSERT INTO proving_observations VALUES(?,?,?,?,?,?,?,?,?)",
            (
                source_id,
                "run-1",
                FETCHED_AT,
                url,
                200,
                digest_bytes(body),
                body,
                1,
                None,
            ),
        )
        retain_observation_revision_first_seen(
            connection,
            source_id=source_id,
            url=url,
            body=body,
            observed_at=FETCHED_AT,
        )
        if source_id not in sources:
            sources.append(source_id)
    for gate_id in PROVING_GATES:
        if gate_id.startswith("RIGHTS_"):
            continue
        connection.execute(
            "INSERT INTO proving_gates VALUES(?,?,?,?)",
            ("run-1", gate_id, "PASS", "fixture"),
        )
    for source_id in sources:
        gate_id = f"RIGHTS_{source_id}"
        connection.execute(
            "INSERT INTO proving_gates VALUES(?,?,?,?)",
            ("run-1", gate_id, "PASS", "fixture"),
        )
        packet = _rights_packet(source_id)
        packet_bytes = canonical_json_bytes(packet)
        connection.execute(
            "INSERT INTO proving_rights_packets VALUES(?,?,?,?,?)",
            (
                "run-1",
                gate_id,
                digest_bytes(packet_bytes),
                packet_bytes.decode("utf-8"),
                RIGHTS_ASSESSED_AT,
            ),
        )
    connection.commit()
    connection.close()


def write_unpublished_store(path: Path) -> None:
    from newsroom.control_plane.store import connect

    refuse_canonical_store(path)
    connection = connect(str(path))
    connection.close()


def measure(work: Callable[[], dict[str, object]]) -> dict[str, object]:
    gc.collect()
    rss_before = current_rss_bytes()
    usage_before = resource.getrusage(resource.RUSAGE_SELF)
    tracemalloc.start()
    started = time.perf_counter()
    try:
        outcome = work()
        status = "OK"
    except Exception as exc:  # noqa: BLE001 — case outcome must stay bounded
        outcome = {"error": f"{type(exc).__name__}: {exc}"}
        status = "ERROR"
    wall = time.perf_counter() - started
    traced_current, traced_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    gc.collect()
    usage_after = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "pid": os.getpid(),
        "status": status,
        "rss_before_bytes": rss_before,
        "rss_after_bytes": current_rss_bytes(),
        "ru_maxrss_bytes": maxrss_bytes(usage_after.ru_maxrss),
        "user_cpu_seconds": usage_after.ru_utime - usage_before.ru_utime,
        "system_cpu_seconds": usage_after.ru_stime - usage_before.ru_stime,
        "wall_seconds": wall,
        "tracemalloc_peak_bytes": traced_peak,
        "tracemalloc_current_bytes": traced_current,
        "outcome": outcome,
    }


def _open_proving(path: str) -> sqlite3.Connection:
    from newsroom.control_plane.sqlite_profile import apply_control_plane_sqlite_profile

    refuse_canonical_store(path)
    connection = sqlite3.connect(path)
    apply_control_plane_sqlite_profile(connection, query_only=True)
    return connection


def _counts(units: tuple[Any, ...], rows: tuple[Any, ...] = ()) -> dict[str, object]:
    body_bytes = 0
    for row in rows:
        body = getattr(row, "body", b"")
        body_bytes += len(body) if isinstance(body, (bytes, bytearray)) else 0
    return {
        "row_count": len(rows),
        "unit_count": len(units),
        "body_bytes": body_bytes,
        "source_ids": sorted({getattr(unit, "source_id", "") for unit in units}),
    }


def _event_for(unit: Any) -> Any:
    from newsroom.control_plane.graphiti_events import GraphitiRevisionEvent

    return GraphitiRevisionEvent(
        event_id="measure-event",
        ledger_seq=1,
        source_id=unit.source_id,
        item_key=unit.item_key,
        revision_digest=unit.revision_digest,
        published_at=unit.published_at or "",
        updated_at=unit.updated_at or "",
        expected_unit_count=1,
        landed_ingest_ids=(unit.ingest_id,),
        landed_payload_digest="sha256:" + ("00" * 32),
        unit_refs=(),
        state="QUEUED",
        attempt_count=0,
        units=(),
    )


def case_bare_interpreter() -> dict[str, object]:
    return measure(lambda: {"imported": False})


def case_import_cycle() -> dict[str, object]:
    def work() -> dict[str, object]:
        from newsroom.control_plane import cycle as cycle_module

        return {"module": cycle_module.__name__}

    return measure(work)


def case_instantiate_runner() -> dict[str, object]:
    def work() -> dict[str, object]:
        from newsroom.control_plane.graphiti import EvaluationGraphitiRunner

        runner = EvaluationGraphitiRunner()
        return {"runner": type(runner).__name__, "graphiti_core_imported": "graphiti_core" in sys.modules}

    return measure(work)


def case_idle_worker() -> dict[str, object]:
    def work() -> dict[str, object]:
        import scripts.hermes_graphiti_worker as worker
        from newsroom.control_plane.graphiti import EvaluationGraphitiRunner

        runner = EvaluationGraphitiRunner()
        return {
            "worker_module": worker.__name__,
            "runner": type(runner).__name__,
            "graphiti_core_imported": "graphiti_core" in sys.modules,
        }

    return measure(work)


def case_hermes_cycle_import() -> dict[str, object]:
    def work() -> dict[str, object]:
        import scripts.hermes_control_plane as hermes
        from newsroom.control_plane.cycle import run_cycle

        return {
            "hermes_module": hermes.__name__,
            "run_cycle": run_cycle.__name__,
        }

    return measure(work)


def case_process_tree() -> dict[str, object]:
    needles = (
        "hermes_control_plane",
        "hermes_graphiti_worker",
        "newsroom-hub",
        "neo4j",
        "com.jamesto.newsroom",
    )
    try:
        out = subprocess.check_output(
            ["ps", "-axo", "pid=,rss=,command="],
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        return {
            "status": UNOBSERVED,
            "reason": f"{type(exc).__name__}: {exc}",
            "signalled": False,
        }
    rows: list[dict[str, object]] = []
    for line in out.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not any(needle in stripped.lower() or needle in stripped for needle in needles):
            continue
        pid_text, rss_text, *command = stripped.split()
        try:
            pid = int(pid_text)
            rss_kib = int(rss_text)
        except ValueError:
            continue
        rows.append(
            {
                "pid": pid,
                "rss_bytes": rss_kib * 1024,
                "command": " ".join(command)[:200],
            }
        )
    return {
        "status": "OK",
        "signalled": False,
        "process_count": len(rows),
        "processes": rows,
        "largest_rss_bytes": max((int(item["rss_bytes"]) for item in rows), default=0),
    }


def _load_units(proving: str) -> tuple[Any, ...]:
    from newsroom.control_plane.cycle import load_graphiti_units

    return load_graphiti_units(proving_store=proving, evaluated_at=CLOCK)


def case_load_units(proving: str, *, clock: datetime = CLOCK) -> dict[str, object]:
    def work() -> dict[str, object]:
        from newsroom.control_plane.cycle import load_graphiti_units

        units = load_graphiti_units(proving_store=proving, evaluated_at=clock)
        return {
            "unit_count": len(units),
            "source_count": len({unit.source_id for unit in units}),
            "chunk_count": len(units),
        }

    return measure(work)


def case_resolve_event(proving: str, *, clock: datetime = CLOCK) -> dict[str, object]:
    def work() -> dict[str, object]:
        from newsroom.control_plane.cycle import (
            _resolve_graphiti_event_units,
            load_graphiti_units,
        )

        units = load_graphiti_units(proving_store=proving, evaluated_at=clock)
        if not units:
            return {"unit_count": 0, "selected_unit_count": 0, "queue_claimed": False}
        selected = _resolve_graphiti_event_units(
            proving_store=proving,
            event=_event_for(units[0]),
            evaluated_at=clock,
        )
        return {
            "unit_count": len(units),
            "selected_unit_count": len(selected),
            "queue_claimed": False,
            "source_id": units[0].source_id,
        }

    return measure(work)


def case_permitted_rows(proving: str, *, clock: datetime = CLOCK) -> dict[str, object]:
    def work() -> dict[str, object]:
        from newsroom.control_plane.cycle import _permitted_rows, _utc_text

        connection = _open_proving(proving)
        try:
            run_id, latest, corpus = _permitted_rows(
                connection,
                evaluated_at=_utc_text(clock),
            )
        finally:
            connection.close()
        body_bytes = sum(len(row.body) for row in corpus)
        return {
            "run_id_present": bool(run_id),
            "latest_row_count": len(latest),
            "corpus_row_count": len(corpus),
            "body_bytes": body_bytes,
        }

    return measure(work)


def case_parsed_observations(proving: str, *, clock: datetime = CLOCK) -> dict[str, object]:
    def work() -> dict[str, object]:
        from newsroom.control_plane.cycle import (
            _parsed_observations,
            _permitted_rows,
            _utc_text,
        )

        connection = _open_proving(proving)
        try:
            _run_id, _latest, corpus = _permitted_rows(
                connection,
                evaluated_at=_utc_text(clock),
            )
            parsed = _parsed_observations(corpus)
        finally:
            connection.close()
        return {
            "corpus_row_count": len(corpus),
            "parsed_item_count": len(parsed),
            "body_bytes": sum(len(row.body) for row in corpus),
        }

    return measure(work)


def case_units_from(proving: str, *, clock: datetime = CLOCK) -> dict[str, object]:
    def work() -> dict[str, object]:
        from newsroom.control_plane.corpus import units_from
        from newsroom.control_plane.cycle import (
            _parsed_observations,
            _permitted_rows,
            _utc_text,
        )
        from newsroom.effective_revision import EffectiveRevisionIdentityResolver

        connection = _open_proving(proving)
        try:
            _run_id, _latest, corpus = _permitted_rows(
                connection,
                evaluated_at=_utc_text(clock),
            )
            resolver = EffectiveRevisionIdentityResolver(connection)
            collected: list[Any] = []
            for row in corpus:
                collected.extend(
                    units_from(
                        _parsed_observations((row,)),
                        proving_run_id=row.run_id,
                        rights_authority_run_id=row.rights_authority_run_id,
                        rights_gate_id=row.rights_gate_id,
                        rights_gate_reason=row.rights_gate_reason,
                        source_definition_url=row.url,
                        effective_revision_resolver=resolver,
                    )
                )
        finally:
            connection.close()
        return {"unit_count": len(collected), "corpus_row_count": len(corpus)}

    return measure(work)


def case_unique_and_revisions(proving: str, *, clock: datetime = CLOCK) -> dict[str, object]:
    def work() -> dict[str, object]:
        from newsroom.control_plane.corpus import revisions_from, unique_chunk_units
        from newsroom.control_plane.cycle import load_graphiti_units

        units = load_graphiti_units(proving_store=proving, evaluated_at=clock)
        unique = unique_chunk_units(units)
        revisions = revisions_from(unique)
        return {
            "unit_count": len(units),
            "unique_unit_count": len(unique),
            "revision_count": len(revisions),
        }

    return measure(work)


def case_admission_generation() -> dict[str, object]:
    def work() -> dict[str, object]:
        from newsroom.control_plane.graphiti_admission import (
            graphiti_admission_generation_identity,
        )

        digest = "sha256:" + ("ab" * 32)
        ingest_ids = ("ingest-a", "ingest-b")
        receipts = (
            {"ingest_id": "ingest-a", "receipt_digest": digest, "proposal_count": 1},
            {"ingest_id": "ingest-b", "receipt_digest": digest, "proposal_count": 1},
        )
        members = (
            {
                "ingest_id": "ingest-a",
                "proposal_key": "proposal-a",
                "proposal_envelope_id": "00000000-0000-4000-8000-000000000001",
                "decision_digest": digest,
                "decision": {"action": "HOLD"},
            },
            {
                "ingest_id": "ingest-b",
                "proposal_key": "proposal-b",
                "proposal_envelope_id": "00000000-0000-4000-8000-000000000002",
                "decision_digest": digest,
                "decision": {"action": "HOLD"},
            },
        )
        cohort_digest, generation_id = graphiti_admission_generation_identity(
            ingest_ids=ingest_ids,
            source_receipts=receipts,
            members=members,
        )
        return {
            "cohort_digest": cohort_digest,
            "generation_id_present": bool(generation_id),
            "member_count": len(members),
        }

    return measure(work)


def case_cycle_max_writes_0(
    proving: str,
    unpublished: str | None = None,
    *,
    clock: datetime = CLOCK,
) -> dict[str, object]:
    owned_unpublished: Path | None = None
    if unpublished is None:
        handle = tempfile.NamedTemporaryFile(
            prefix="newsroom-898-unpub-",
            suffix=".sqlite3",
            delete=False,
        )
        handle.close()
        owned_unpublished = Path(handle.name)
        write_unpublished_store(owned_unpublished)
        unpublished = str(owned_unpublished)

    def work() -> dict[str, object]:
        from newsroom.control_plane.cycle import run_cycle
        from newsroom.control_plane.evidence import package_for
        from newsroom.control_plane.writer import FixtureWriter

        report = run_cycle(
            proving_store=proving,
            unpublished_store=unpublished,
            writer=FixtureWriter(),
            max_writes=0,
            graphiti=None,
            max_graphiti=0,
            max_writer_provider_dispatches=0,
            max_writer_fallback_dispatches=0,
            clock=lambda: clock,
            evidence_package_builder=package_for,
        )
        return {
            "poll_observation_count": report.poll_observation_count,
            "candidates": report.candidates,
            "minted": report.minted,
            "graphiti": report.graphiti,
            "write_ready": report.write_ready,
        }

    try:
        return measure(work)
    finally:
        if owned_unpublished is not None:
            owned_unpublished.unlink(missing_ok=True)
            for suffix in ("-wal", "-shm"):
                Path(str(owned_unpublished) + suffix).unlink(missing_ok=True)


def fixture_rows(kind: str) -> tuple[tuple[str, bytes], ...]:
    from newsroom.graphiti_adapter.identity import MAX_EPISODE_BYTES

    if kind == "solo":
        return (("UK-01", ATOM),)
    if kind == "representative":
        return (
            ("UK-01", ATOM),
            ("HK-01", rss_body(guid="hk-1", title="香港政府新聞", description="保留來源正文。")),
            ("UK-02", JSON_DOC),
        )
    if kind == "times10":
        extras = tuple(
            (
                "HK-01",
                rss_body(
                    guid=f"hk-extra-{index}",
                    title=f"Unrelated item {index}",
                    description=f"Source-safe unrelated observation {index}.",
                ),
            )
            for index in range(10)
        )
        return (("UK-01", ATOM),) + extras
    if kind == "json":
        return (("UK-02", JSON_DOC),)
    if kind == "rss":
        return (("HK-01", rss_body(guid="hk-1", title="香港政府新聞", description="保留來源正文。")),)
    if kind == "atom":
        return (("UK-01", ATOM),)
    if kind == "large":
        return (
            (
                "HK-01",
                rss_body(
                    guid="large-1",
                    title="Large retained body",
                    description="L" * MAX_EPISODE_BYTES,
                ),
            ),
        )
    if kind == "malformed":
        return (("UK-02", b"{not-json"),)
    if kind == "empty":
        return (("UK-01", b""),)
    raise ValueError(f"unknown fixture kind: {kind}")


def build_workspace(root: Path) -> dict[str, str]:
    root.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    for kind in (
        "solo",
        "representative",
        "times10",
        "json",
        "rss",
        "atom",
        "large",
        "malformed",
        "empty",
    ):
        proving = root / f"proving-{kind}.sqlite3"
        unpublished = root / f"unpublished-{kind}.sqlite3"
        proving.unlink(missing_ok=True)
        unpublished.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(str(proving) + suffix).unlink(missing_ok=True)
            Path(str(unpublished) + suffix).unlink(missing_ok=True)
        write_proving_store(proving, fixture_rows(kind))
        write_unpublished_store(unpublished)
        paths[f"proving_{kind}"] = str(proving)
        paths[f"unpublished_{kind}"] = str(unpublished)
    copied = root / "proving-copied.sqlite3"
    copy_meta = copy_canonical_proving(copied)
    paths["copy_meta"] = json.dumps(copy_meta, sort_keys=True)
    if copy_meta.get("status") == "COPIED":
        paths["proving_copied"] = str(copied)
        unpublished_copied = root / "unpublished-copied.sqlite3"
        write_unpublished_store(unpublished_copied)
        paths["unpublished_copied"] = str(unpublished_copied)
    return paths


CASE_SPECS: tuple[tuple[str, str, str], ...] = (
    ("A1_bare_interpreter", "bare", ""),
    ("A2_import_cycle", "import_cycle", ""),
    ("A3_instantiate_runner", "instantiate_runner", ""),
    ("A4_idle_worker", "idle_worker", ""),
    ("A5_hermes_cycle_import", "hermes_cycle_import", ""),
    ("A6_process_tree", "process_tree", ""),
    ("B1_one_event_solo", "resolve", "solo"),
    ("B2_one_event_representative", "resolve", "representative"),
    ("B3_one_event_times10", "resolve", "times10"),
    ("B4_shape_json", "resolve", "json"),
    ("B5_shape_rss", "resolve", "rss"),
    ("B6_shape_atom", "resolve", "atom"),
    ("B7_large_body", "resolve", "large"),
    ("B8_malformed", "resolve", "malformed"),
    ("B9_empty", "resolve", "empty"),
    ("B10_copied_canonical", "resolve_copied", "copied"),
    ("C1_permitted_rows", "permitted_rows", "times10"),
    ("C2_parsed_observations", "parsed_observations", "times10"),
    ("C3_units_from", "units_from", "times10"),
    ("C4_unique_and_revisions", "unique_and_revisions", "times10"),
    ("C5_load_graphiti_units", "load", "times10"),
    ("C6_resolve_event_units", "resolve_copied_or_times10", "times10"),
    ("C7_admission_generation", "admission_generation", ""),
    ("D1_cycle_max_writes_0", "cycle", "copied_or_representative"),
)


def run_named_case(name: str, workspace: dict[str, str]) -> dict[str, object]:
    spec = {item[0]: item for item in CASE_SPECS}[name]
    _case_name, kind, store = spec
    copied = workspace.get("proving_copied")
    times10 = workspace["proving_times10"]
    stage_store = times10
    stage_clock = CLOCK

    if kind == "bare":
        return case_bare_interpreter()
    if kind == "import_cycle":
        return case_import_cycle()
    if kind == "instantiate_runner":
        return case_instantiate_runner()
    if kind == "idle_worker":
        return case_idle_worker()
    if kind == "hermes_cycle_import":
        return case_hermes_cycle_import()
    if kind == "process_tree":
        return case_process_tree()
    if kind == "admission_generation":
        return case_admission_generation()
    if kind == "resolve":
        return case_resolve_event(workspace[f"proving_{store}"])
    if kind == "resolve_copied":
        if not copied:
            return {"status": UNOBSERVED, "reason": "canonical proving copy missing"}
        return case_resolve_event(copied, clock=datetime.now(tz=UTC))
    if kind == "permitted_rows":
        return case_permitted_rows(stage_store, clock=stage_clock)
    if kind == "parsed_observations":
        return case_parsed_observations(stage_store, clock=stage_clock)
    if kind == "units_from":
        return case_units_from(stage_store, clock=stage_clock)
    if kind == "unique_and_revisions":
        return case_unique_and_revisions(stage_store, clock=stage_clock)
    if kind == "load":
        return case_load_units(stage_store, clock=stage_clock)
    if kind == "resolve_copied_or_times10":
        return case_resolve_event(stage_store, clock=stage_clock)
    if kind == "cycle":
        if copied:
            return case_cycle_max_writes_0(copied, clock=datetime.now(tz=UTC))
        return case_cycle_max_writes_0(workspace["proving_representative"])
    raise ValueError(f"unknown case kind: {kind}")


def _parse_time_l(stderr: str) -> int | str:
    for line in stderr.splitlines():
        if "maximum resident set size" in line:
            number = line.strip().split()[0]
            try:
                return int(number)
            except ValueError:
                return UNOBSERVED
    return UNOBSERVED


def run_child_case(
    *,
    executable: str,
    module: str,
    case: str,
    workspace: Path,
    env: dict[str, str],
) -> dict[str, object]:
    command = [
        "/usr/bin/time",
        "-l",
        executable,
        "-m",
        module,
        "--case",
        case,
        "--workspace",
        str(workspace),
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    payload: dict[str, object]
    try:
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError, ValueError):
        payload = {
            "status": "ERROR",
            "outcome": {
                "error": "child stdout was not JSON",
                "stderr_tail": completed.stderr[-1000:],
                "returncode": completed.returncode,
            },
        }
    payload["time_l_maxrss_bytes"] = _parse_time_l(completed.stderr)
    payload["returncode"] = completed.returncode
    payload["command"] = command
    return payload


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if not ordered:
        raise ValueError("median of empty sample")
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def summarise_case(name: str, runs: list[dict[str, object]]) -> dict[str, object]:
    measured = runs[WARMUPS:]
    peaks: list[int] = []
    cpus: list[float] = []
    retained: list[int] = []
    for item in measured:
        peak = item.get("ru_maxrss_bytes")
        after = item.get("rss_after_bytes")
        user = item.get("user_cpu_seconds")
        system = item.get("system_cpu_seconds")
        if isinstance(peak, int):
            peaks.append(peak)
        if isinstance(after, int):
            retained.append(after)
        if isinstance(user, (int, float)) and isinstance(system, (int, float)):
            cpus.append(float(user) + float(system))
    return {
        "case": name,
        "warmup_count": WARMUPS,
        "measured_count": len(measured),
        "max_peak_rss_bytes": max(peaks) if peaks else UNOBSERVED,
        "median_cpu_seconds": _median(cpus) if cpus else UNOBSERVED,
        "max_retained_rss_bytes": max(retained) if retained else UNOBSERVED,
        "runs": runs,
    }


def decide(summaries: dict[str, dict[str, object]]) -> dict[str, object]:
    import_peak = summaries.get("A2_import_cycle", {}).get("max_peak_rss_bytes")
    ranked: list[dict[str, object]] = []
    for name, summary in summaries.items():
        peak = summary.get("max_peak_rss_bytes")
        if not isinstance(peak, int):
            continue
        removable = (
            max(0, peak - import_peak) if isinstance(import_peak, int) else peak
        )
        ranked.append(
            {
                "case": name,
                "peak_rss_bytes": peak,
                "retained_rss_bytes": summary.get("max_retained_rss_bytes"),
                "local_cpu_seconds": summary.get("median_cpu_seconds"),
                "removable_peak_rss_bytes": removable,
            }
        )
    ranked.sort(
        key=lambda item: (
            int(item["removable_peak_rss_bytes"]),
            int(item["peak_rss_bytes"]),
        ),
        reverse=True,
    )
    leader = ranked[0] if ranked else None
    threshold_ok = False
    if leader is not None:
        removable = int(leader["removable_peak_rss_bytes"])
        peak = int(leader["peak_rss_bytes"])
        threshold_ok = removable >= GO_PEAK_BYTES or (
            peak > 0 and removable / peak >= GO_PEAK_RATIO
        )
    h2_names = {
        "B10_copied_canonical",
        "C1_permitted_rows",
        "C2_parsed_observations",
        "C5_load_graphiti_units",
        "C6_resolve_event_units",
        "D1_cycle_max_writes_0",
    }
    h2_leads = bool(leader and str(leader["case"]) in h2_names)
    if not ranked:
        decision = "HOLD_FOR_MINI_MEASUREMENT"
        reason = "no measured peaks"
    elif h2_leads:
        decision = "NO_GO"
        reason = (
            "H2 full-corpus reconstruction is the largest measured contributor; "
            "next correction is exact row selection plus bounded/streaming "
            "resolution in Python, not a Rust translation of the scan"
        )
    elif threshold_ok:
        decision = "GO"
        reason = "leading candidate meets the pre-registered RSS floor"
    else:
        decision = "NO_GO"
        reason = "no candidate meets 20% of process peak RSS or 64 MiB removable peak"
    return {
        "go_or_no_go": decision,
        "reason": reason,
        "threshold_ok": threshold_ok,
        "leader": leader,
        "ranked_candidate_boundaries": ranked[:12],
        "h2_leads": h2_leads,
        "import_peak_rss_bytes": import_peak if isinstance(import_peak, int) else UNOBSERVED,
    }


def host_identity() -> dict[str, object]:
    values: dict[str, object] = {
        "platform": sys.platform,
        "executable": sys.executable,
    }
    try:
        completed = subprocess.run(
            [
                "/usr/sbin/sysctl",
                "-n",
                "hw.model",
                "machdep.cpu.brand_string",
                "hw.physicalcpu",
                "hw.logicalcpu",
                "hw.memsize",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        lines = completed.stdout.splitlines()
        values.update(
            {
                "machine_model": lines[0],
                "chip": lines[1],
                "physical_cores": int(lines[2]),
                "logical_cores": int(lines[3]),
                "memory_bytes": int(lines[4]),
            }
        )
    except (OSError, subprocess.CalledProcessError, IndexError, ValueError):
        values["machine_model"] = UNOBSERVED
    return values


def git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return UNOBSERVED


def assemble_packet(
    *,
    summaries: dict[str, dict[str, object]],
    copy_meta: dict[str, object],
    workspace_digest: str,
) -> dict[str, object]:
    decision = decide(summaries)
    questions = {
        "1_largest_idle_rss_process": summaries.get("A6_process_tree", {})
        .get("runs", [{}])[-1]
        .get("largest_rss_bytes", UNOBSERVED)
        if summaries.get("A6_process_tree")
        else UNOBSERVED,
        "2_rss_retained_before_useful_work": summaries.get(
            "A4_idle_worker", {}
        ).get("max_retained_rss_bytes", UNOBSERVED),
        "3_active_peak_resolving_one_graphiti_event": summaries.get(
            "B10_copied_canonical", summaries.get("B2_one_event_representative", {})
        ).get("max_peak_rss_bytes", UNOBSERVED),
        "4_rss_after_one_event_or_cycle": summaries.get(
            "D1_cycle_max_writes_0", {}
        ).get("max_retained_rss_bytes", UNOBSERVED),
        "5_stage_largest_removable_peak_rss": (decision.get("leader") or {}).get(
            "case", UNOBSERVED
        ),
        "6_stage_most_local_cpu": max(
            (
                (
                    name,
                    summary.get("median_cpu_seconds"),
                )
                for name, summary in summaries.items()
                if isinstance(summary.get("median_cpu_seconds"), (int, float))
            ),
            key=lambda item: float(item[1]),
            default=(UNOBSERVED, UNOBSERVED),
        )[0],
        "7_one_event_scales_with_unrelated_corpus": {
            "solo_peak": summaries.get("B1_one_event_solo", {}).get(
                "max_peak_rss_bytes", UNOBSERVED
            ),
            "times10_peak": summaries.get("B3_one_event_times10", {}).get(
                "max_peak_rss_bytes", UNOBSERVED
            ),
            "copied_peak": summaries.get("B10_copied_canonical", {}).get(
                "max_peak_rss_bytes", UNOBSERVED
            ),
        },
        "8_latest_bodies_parsed_or_materialised_more_than_once": "YES_STATIC",
        "9_dominant_memory_source": (decision.get("leader") or {}).get(
            "case", UNOBSERVED
        ),
        "10_bounded_rust_process_would_remove_dominant_allocation": (
            False if decision["go_or_no_go"] == "NO_GO" else UNOBSERVED
        ),
    }
    return {
        "issue": ISSUE,
        "status": "MEASURED",
        "decision": decision["go_or_no_go"],
        "decision_reason": decision["reason"],
        "inspection_head": git_head(),
        "inspection_date": datetime.now(tz=UTC).strftime("%Y-%m-%d"),
        "intended_hardware": host_identity(),
        "copy_meta": copy_meta,
        "workspace_digest": workspace_digest,
        "method": {
            "peak_rss_and_cpu": ["/usr/bin/time -l", "resource.getrusage"],
            "current_or_retained_rss": ["ps -o rss"],
            "python_allocation_supplement": "tracemalloc",
            "fresh_process_per_case": True,
            "warmup_plus_measured_runs": f"{WARMUPS} warmup and {MEASURED_RUNS} fresh-process executions",
        },
        "go_gate": decision,
        "questions": questions,
        "cases": summaries,
        "non_effects": [
            "no Rust production code",
            "no provider or model-catalogue call",
            "no queue claim, consume, retry or release",
            "no writable canonical-store access",
            "no Neo4j or Graphiti mutation",
            "no publication, deployment, activation or canary",
            "no live daemon restart, signal or reconfiguration",
        ],
    }


def orchestrate(*, output: Path, workspace: Path | None = None) -> dict[str, object]:
    close_workspace = False
    if workspace is None:
        workspace = Path(tempfile.mkdtemp(prefix="newsroom-898-"))
        close_workspace = True
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        paths = build_workspace(workspace)
        copy_meta = json.loads(paths.get("copy_meta", "{}"))
        summaries: dict[str, dict[str, object]] = {}
        for name, _kind, _store in CASE_SPECS:
            runs: list[dict[str, object]] = []
            repeats = 1 if name == "A6_process_tree" else WARMUPS + MEASURED_RUNS
            if name == "A1_bare_interpreter":
                for _ in range(repeats):
                    script = (
                        "import gc,json,os,resource,subprocess,sys,time,tracemalloc\n"
                        "gc.collect()\n"
                        "rss=lambda:int(subprocess.check_output(['ps','-o','rss=','-p',str(os.getpid())],text=True).split()[0])*1024\n"
                        "before=rss(); u0=resource.getrusage(resource.RUSAGE_SELF); tracemalloc.start(); t0=time.perf_counter()\n"
                        "ok=True\n"
                        "traced,peak=tracemalloc.get_traced_memory(); tracemalloc.stop(); gc.collect(); u1=resource.getrusage(resource.RUSAGE_SELF)\n"
                        "raw=u1.ru_maxrss; maxrss=raw if sys.platform=='darwin' else raw*1024\n"
                        "print(json.dumps({'pid':os.getpid(),'status':'OK','rss_before_bytes':before,'rss_after_bytes':rss(),'ru_maxrss_bytes':maxrss,'user_cpu_seconds':u1.ru_utime-u0.ru_utime,'system_cpu_seconds':u1.ru_stime-u0.ru_stime,'wall_seconds':time.perf_counter()-t0,'tracemalloc_peak_bytes':peak,'outcome':{'imported':False}}))\n"
                    )
                    completed = subprocess.run(
                        ["/usr/bin/time", "-l", sys.executable, "-c", script],
                        check=False,
                        capture_output=True,
                        text=True,
                        env=env,
                    )
                    try:
                        payload = json.loads(completed.stdout.strip().splitlines()[-1])
                    except (json.JSONDecodeError, IndexError, ValueError):
                        payload = {
                            "status": "ERROR",
                            "outcome": {"error": completed.stderr[-1000:]},
                        }
                    payload["time_l_maxrss_bytes"] = _parse_time_l(completed.stderr)
                    runs.append(payload)
            else:
                for _ in range(repeats):
                    runs.append(
                        run_child_case(
                            executable=sys.executable,
                            module="newsroom.research.issue_898_ram_cpu",
                            case=name,
                            workspace=workspace,
                            env=env,
                        )
                    )
            summaries[name] = summarise_case(name, runs)
        workspace_digest = hashlib.sha256(
            json.dumps(sorted(paths.items()), sort_keys=True).encode()
        ).hexdigest()
        packet = assemble_packet(
            summaries=summaries,
            copy_meta=copy_meta,
            workspace_digest="sha256:" + workspace_digest,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return packet
    finally:
        if close_workspace:
            shutil.rmtree(workspace, ignore_errors=True)


def load_workspace(path: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in path.glob("proving-*.sqlite3"):
        mapping[f"proving_{item.stem.removeprefix('proving-')}"] = str(item)
    for item in path.glob("unpublished-*.sqlite3"):
        mapping[f"unpublished_{item.stem.removeprefix('unpublished-')}"] = str(item)
    return mapping


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Issue #898 Mini RAM/CPU packet")
    parser.add_argument("--case")
    parser.add_argument("--workspace", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/research/2026-09-02-issue-898-ram-cpu-measurements.json"),
    )
    args = parser.parse_args(argv)
    if args.case:
        if args.workspace is None:
            raise SystemExit("--workspace is required with --case")
        payload = run_named_case(args.case, load_workspace(args.workspace))
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    orchestrate(output=args.output, workspace=args.workspace)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
