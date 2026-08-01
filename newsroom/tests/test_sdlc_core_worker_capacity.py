from __future__ import annotations

import importlib
from pathlib import Path

import scripts.sdlc._workflow_lane_impl as implementation_module
import scripts.sdlc.workflow_lane as lane_module


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


def test_private_implementation_and_reload_keep_scheduler_contract() -> None:
    assert lane_module is implementation_module
    assert implementation_module._CORE_WORKER_COUNT == 4
    assert implementation_module._CORE_DISTRIBUTION == "worksteal"

    reloaded = importlib.reload(implementation_module)

    assert reloaded is implementation_module
    assert lane_module is implementation_module
    assert reloaded._CORE_WORKER_COUNT == 4
    assert reloaded._CORE_DISTRIBUTION == "worksteal"