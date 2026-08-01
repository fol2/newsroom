from __future__ import annotations

import json
import os
from pathlib import Path
import time

import pytest


collect_ignore_glob = ["_archive/*"]

_DIAGNOSTIC_DIRECTORY = (
    Path(".sdlc-run")
    / "core"
    / "gates"
    / "core-deterministic"
    / "tests"
    / "reports"
)


def _record_test_event(event: str, nodeid: str, **values: object) -> None:
    if not _DIAGNOSTIC_DIRECTORY.is_dir():
        return
    worker = os.environ.get("PYTEST_XDIST_WORKER", "controller")
    path = _DIAGNOSTIC_DIRECTORY / f"temporary-test-timing-{worker}.jsonl"
    payload = {
        "event": event,
        "nodeid": nodeid,
        "monotonic_ns": time.monotonic_ns(),
        **values,
    }
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None):
    started = time.monotonic_ns()
    _record_test_event("start", item.nodeid)
    outcome = yield
    _record_test_event(
        "finish",
        item.nodeid,
        duration_ns=time.monotonic_ns() - started,
        force_result=outcome.force_result is not None,
    )
