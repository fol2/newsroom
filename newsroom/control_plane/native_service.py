"""Long-running shell for the autonomous private native pipeline."""

from __future__ import annotations

import fcntl
import math
import os
import sqlite3
import threading
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager, contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

from newsroom.control_plane.native_pipeline import NativePipeline, NativePipelineReport
from newsroom.authority.canonical import validate_sha256_digest
from newsroom.control_plane.store import append_ledger, connect
from newsroom.control_plane.veto import VetoError

LOCK_IDENTITY = "newsroom-hermes-native-service-v1\n"


class NativeServiceAlreadyRunning(RuntimeError):
    """Raised before any pipeline effect when the singleton lock is held."""


@dataclass(frozen=True, slots=True)
class NativeServiceReport:
    cycle_id: str
    outcome: str
    failure_class: str | None
    pipeline: NativePipelineReport | None


@contextmanager
def _instance_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise NativeServiceAlreadyRunning("native service lock is held") from exc
        handle.seek(0)
        identity = handle.read()
        if not identity:
            handle.write(LOCK_IDENTITY)
            handle.flush()
            os.fsync(handle.fileno())
        elif identity != LOCK_IDENTITY:
            raise RuntimeError("native service lock identity differs")
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


class NativeService:
    """Run every native revision to its retained outcome; never publish publicly."""

    def __init__(
        self, *,
        pipeline_factory: Callable[[], AbstractContextManager[NativePipeline]],
        ledger_path: str,
        lock_path: Path,
        stop_check: Callable[[], None],
        interval_seconds: float = 300,
        failure_backoff_seconds: float = 60,
        wait: Callable[[float], bool] | None = None,
        cycle_id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
        qualify_once: Callable[[sqlite3.Connection, str], object] | None = None,
    ) -> None:
        if not callable(pipeline_factory) or not callable(stop_check):
            raise TypeError("native service pipeline and stop check are required")
        if qualify_once is not None and not callable(qualify_once):
            raise TypeError("native qualification callback must be callable")
        if (
            not math.isfinite(interval_seconds)
            or not math.isfinite(failure_backoff_seconds)
            or interval_seconds <= 0
            or failure_backoff_seconds <= 0
        ):
            raise ValueError("native service waits must be positive")
        self._pipeline_factory = pipeline_factory
        self._ledger_path, self._lock_path = ledger_path, lock_path
        self._stop_check = stop_check
        self._interval, self._backoff = interval_seconds, failure_backoff_seconds
        self._shutdown = threading.Event()
        self._wait = wait or self._shutdown.wait
        self._cycle_id = cycle_id_factory
        self._qualify_once = qualify_once

    def request_shutdown(self) -> None:
        self._shutdown.set()

    def run(self, *, once: bool = False) -> NativeServiceReport | None:
        last = None
        with _instance_lock(self._lock_path):
            self._stop_check()
            ledger = connect(self._ledger_path)
            try:
                with self._pipeline_factory() as pipeline:
                    identity = getattr(pipeline, "runtime_identity_digest", None)
                    if identity is not None:
                        validate_sha256_digest(identity)
                    binding = {} if identity is None else {"runtime_identity_digest": identity}
                    while not self._shutdown.is_set():
                        self._stop_check()
                        cycle_id = self._cycle_id()
                        if type(cycle_id) is not str or not cycle_id:
                            raise ValueError("native service cycle identity differs")
                        self._append(ledger, "NATIVE_SERVICE_CYCLE_STARTED", {
                            "cycle_id": cycle_id,
                            **binding,
                        })
                        try:
                            report = pipeline.tick(cycle_id=cycle_id)
                            if type(report) is not NativePipelineReport:
                                raise TypeError("native pipeline report differs")
                        except VetoError:
                            raise
                        except Exception as exc:
                            last = NativeServiceReport(
                                cycle_id, "FAILED", type(exc).__name__, None,
                            )
                        else:
                            last = NativeServiceReport(cycle_id, "COMPLETE", None, report)
                        self._append(ledger, "NATIVE_SERVICE_CYCLE_TERMINAL", {
                            **binding,
                            "cycle_id": last.cycle_id,
                            "outcome": last.outcome,
                            "failure_class": last.failure_class,
                            "pipeline": (
                                None if last.pipeline is None else asdict(last.pipeline)
                            ),
                        })
                        if once and self._qualify_once is not None:
                            if identity is None:
                                raise ValueError("native qualification requires a runtime identity")
                            self._qualify_once(ledger, identity)
                        if once or self._wait(
                            self._interval if last.outcome == "COMPLETE" else self._backoff
                        ):
                            break
            finally:
                ledger.close()
        return last

    @staticmethod
    def _append(connection: sqlite3.Connection, kind: str, payload: dict) -> None:
        append_ledger(connection, kind, payload)
        connection.commit()


__all__ = [
    "NativeService", "NativeServiceAlreadyRunning", "NativeServiceReport",
]
