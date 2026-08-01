from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import scripts.sdlc.workflow_lane as lane_module


REPO_ROOT = Path(__file__).parents[2]


def test_core_lane_uses_four_persistent_worksteal_workers(
    tmp_path: Path,
) -> None:
    assert lane_module._CORE_WORKER_COUNT == 4
    assert lane_module._CORE_DISTRIBUTION == "worksteal"

    command = lane_module._core_worker_command(
        report=tmp_path / "pytest.xml",
        basetemp=tmp_path / "pytest",
    )

    worker_flag = command.index("-n")
    assert command[worker_flag + 1] == "4"
    assert "--dist=worksteal" in command
    assert "--max-worker-restart=0" in command
    assert command.count("xdist.plugin") == 1
    assert command.count("newsroom/tests") == 1


def test_reload_keeps_canonical_scheduler_contract_in_isolated_process() -> None:
    code = """
import importlib
import scripts.sdlc.workflow_lane as lane
reloaded = importlib.reload(lane)
assert reloaded is lane
assert reloaded._CORE_WORKER_COUNT == 4
assert reloaded._CORE_DISTRIBUTION == 'worksteal'
assert reloaded._CORE_TESTS == ('newsroom/tests',)
"""
    completed = subprocess.run(
        (sys.executable, "-c", code),
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
