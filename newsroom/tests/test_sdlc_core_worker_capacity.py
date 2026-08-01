from __future__ import annotations

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
