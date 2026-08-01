from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


_FOCUSED_TEST = '''from __future__ import annotations

from pathlib import Path

import scripts.sdlc.workflow_lane as lane_module


def test_core_lane_uses_six_persistent_worksteal_workers(
    tmp_path: Path,
) -> None:
    assert lane_module._CORE_WORKER_COUNT == 6
    assert lane_module._CORE_DISTRIBUTION == "worksteal"

    command = lane_module._core_worker_command(
        report=tmp_path / "pytest.xml",
        basetemp=tmp_path / "pytest",
    )

    worker_flag = command.index("-n")
    assert command[worker_flag + 1] == "6"
    assert "--dist=worksteal" in command
    assert "--max-worker-restart=0" in command
    assert command.count("xdist.plugin") == 1
    assert command.count("newsroom/tests") == 1
'''

_MAIN_CI = '''name: CI

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install uv
        run: |
          python -m pip install --upgrade pip
          python -m pip install uv

      - name: Lockfile Check
        run: uv lock --check

      - name: Sync (Dev)
        run: uv sync --dev --locked

      - name: Tests
        run: uv run python -m pytest -q

      - name: Clustering Eval Gate
        run: |
          uv run python scripts/eval_clustering_metrics.py \\
            --dataset newsroom/evals/clustering_eval_dataset_v1.jsonl \\
            --baseline newsroom/evals/clustering_eval_metrics_baseline_v1.json \\
            --fail-on-regression
'''


def _report_directory() -> Path:
    for argument in sys.argv:
        if argument.startswith("--junitxml="):
            path = Path(argument.split("=", 1)[1]).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            return path.parent
    raise AssertionError("signed core command did not expose its JUnit path")


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def test_temporary_export_exact_sdlc_sources() -> None:
    output = _report_directory()

    lane = Path("scripts/sdlc/workflow_lane.py").read_text(encoding="utf-8")
    old = '_CORE_WORKER_COUNT = 8\n_CORE_DISTRIBUTION = "loadfile"\n'
    new = '_CORE_WORKER_COUNT = 6\n_CORE_DISTRIBUTION = "worksteal"\n'
    assert lane.count(old) == 1
    lane = lane.replace(old, new, 1)

    tests = Path("newsroom/tests/test_sdlc_workflow_lane.py").read_text(
        encoding="utf-8"
    )
    replacements = {
        'assert lane_module._CORE_DISTRIBUTION == "loadfile"':
            'assert lane_module._CORE_DISTRIBUTION == "worksteal"',
        '"--dist=loadfile",': '"--dist=worksteal",',
        'assert "--dist=loadfile" in command':
            'assert "--dist=worksteal" in command',
    }
    for old_text, new_text in replacements.items():
        assert tests.count(old_text) >= 1
        tests = tests.replace(old_text, new_text)

    exports = {
        "workflow_lane.py": lane.encode("utf-8"),
        "test_sdlc_workflow_lane.py": tests.encode("utf-8"),
        "test_sdlc_core_worker_capacity.py": _FOCUSED_TEST.encode("utf-8"),
        "ci.yml": _MAIN_CI.encode("utf-8"),
    }
    manifest: dict[str, object] = {"schema_version": "temp-sdlc-export-v1"}
    for name, data in exports.items():
        (output / f"export-{name}").write_bytes(data)
        manifest[name] = {"digest": _digest(data), "size_bytes": len(data)}
    (output / "export-manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    raise AssertionError("temporary exact patched source export")
