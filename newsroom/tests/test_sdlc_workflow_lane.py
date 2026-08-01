from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

import scripts.sdlc.workflow_lane as lane_module

from ._sdlc_workflow_lane_tests_impl import *  # noqa: F401,F403


def test_core_worker_command_is_pinned_persistent_and_file_scoped(
    tmp_path: Path,
) -> None:
    report = tmp_path / "report.xml"
    basetemp = tmp_path / "basetemp"
    command = lane_module._core_worker_command(
        report=report,
        basetemp=basetemp,
    )

    assert lane_module._CORE_WORKER_COUNT == 3
    assert lane_module._CORE_DISTRIBUTION == "worksteal"
    assert command[:13] == (
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--assert=plain",
        "-p",
        "no:cacheprovider",
        "-p",
        "xdist.plugin",
        "-n",
        "3",
        "--dist=worksteal",
        "--max-worker-restart=0",
    )
    assert command[13:14] == lane_module._CORE_TESTS == (
        "newsroom/tests",
    )
    assert command[-2:] == (
        f"--basetemp={basetemp}",
        f"--junitxml={report}",
    )


def test_persistent_core_runner_invokes_one_session_and_propagates_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_root = tmp_path / "newsroom/tests"
    test_root.mkdir(parents=True)
    for index in range(lane_module._CORE_WORKER_COUNT):
        (test_root / f"test_{index}.py").write_text(
            "def test_ok(): assert True\n",
            encoding="utf-8",
        )
    report = tmp_path / "pytest.xml"
    calls: list[tuple[tuple[str, ...], Path, bool]] = []

    def run(argv, *, cwd, check):
        calls.append((tuple(argv), cwd, check))
        return SimpleNamespace(returncode=9)

    monkeypatch.setattr(lane_module.subprocess, "run", run)

    assert lane_module._run_core_pytest_workers(
        root=tmp_path,
        report=report,
    ) == 9
    assert len(calls) == 1
    command, cwd, check = calls[0]
    assert cwd == tmp_path
    assert check is False
    assert command.count("xdist.plugin") == 1
    assert "--dist=worksteal" in command
    assert "--max-worker-restart=0" in command
