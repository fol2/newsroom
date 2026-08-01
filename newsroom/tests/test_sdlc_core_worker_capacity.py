from __future__ import annotations

from pathlib import Path

import scripts.sdlc.workflow_lane as lane_module


def test_core_lane_uses_eight_persistent_loadfile_workers(
    tmp_path: Path,
) -> None:
    assert lane_module._CORE_WORKER_COUNT == 8
    assert lane_module._CORE_DISTRIBUTION == "loadfile"

    command = lane_module._core_worker_command(
        report=tmp_path / "pytest.xml",
        basetemp=tmp_path / "pytest",
    )

    worker_flag = command.index("-n")
    assert command[worker_flag + 1] == "8"
    assert "--dist=loadfile" in command
    assert "--max-worker-restart=0" in command
    assert command.count("xdist.plugin") == 1
