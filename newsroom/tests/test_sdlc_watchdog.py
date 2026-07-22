from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time

import pytest

from scripts.sdlc.run_gate import (
    GateRunError,
    LaneDeadline,
    main as watchdog_main,
    run_gate_command,
)


REPO_ROOT = Path(__file__).parents[2]


def _python(source: str, *arguments: str) -> tuple[str, ...]:
    return (sys.executable, "-c", source, *arguments)


def test_success_and_nonzero_exit_are_typed() -> None:
    deadline = LaneDeadline.start(2)
    passed = run_gate_command(
        gate_id="route",
        phase="unit",
        argv=_python("print('ok')"),
        deadline=deadline,
        command_timeout_seconds=1,
    )
    failed = run_gate_command(
        gate_id="route",
        phase="unit",
        argv=_python("raise SystemExit(7)"),
        deadline=LaneDeadline.start(2),
        command_timeout_seconds=1,
    )

    assert passed.result == "PASS"
    assert passed.returncode == 0
    assert passed.stdout == "ok\n"
    assert passed.result_reason == "PASS:route:unit"
    assert failed.result == "FAIL"
    assert failed.returncode == 7
    assert failed.result_reason == "FAIL:route:unit:exit=7"


def test_expired_shared_deadline_prevents_process_start(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    deadline = LaneDeadline(time.monotonic_ns() - 2_000_000_000, 10)

    result = run_gate_command(
        gate_id="core-deterministic",
        phase="tests",
        argv=_python("from pathlib import Path; Path(__import__('sys').argv[1]).touch()", str(marker)),
        deadline=deadline,
        command_timeout_seconds=1,
    )

    assert result.result == "BUDGET_EXCEEDED"
    assert result.returncode is None
    assert result.execution_ms == 0
    assert not marker.exists()


def test_multiple_commands_share_one_lane_deadline() -> None:
    deadline = LaneDeadline.start(0.4)
    first = run_gate_command(
        gate_id="core-deterministic",
        phase="first",
        argv=_python("import time; time.sleep(0.1)"),
        deadline=deadline,
        command_timeout_seconds=0.3,
    )
    second = run_gate_command(
        gate_id="core-deterministic",
        phase="second",
        argv=_python("import time; time.sleep(1)"),
        deadline=deadline,
        command_timeout_seconds=0.9,
        termination_grace_seconds=0.1,
    )

    assert first.result == "PASS"
    assert second.result == "BUDGET_EXCEEDED"
    assert second.execution_ms < 400
    assert deadline.remaining_seconds() == 0


@pytest.mark.skipif(os.name != "posix", reason="process-group evidence is POSIX-specific")
def test_timeout_terminates_descendant_process_group(tmp_path: Path) -> None:
    marker = tmp_path / "child-terminated"
    pid_file = tmp_path / "child-pid"
    child = """
import signal
from pathlib import Path
import sys
import time

def stop(*_args):
    Path(sys.argv[1]).write_text('terminated', encoding='utf-8')
    raise SystemExit(0)

signal.signal(signal.SIGTERM, stop)
time.sleep(30)
"""
    parent = """
import subprocess
from pathlib import Path
import sys
import time

process = subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2]])
Path(sys.argv[3]).write_text(str(process.pid), encoding='utf-8')
time.sleep(30)
"""

    result = run_gate_command(
        gate_id="core-deterministic",
        phase="descendants",
        argv=_python(parent, child, str(marker), str(pid_file)),
        deadline=LaneDeadline.start(0.7),
        command_timeout_seconds=0.65,
        termination_grace_seconds=0.4,
    )

    stop_at = time.monotonic() + 1
    while time.monotonic() < stop_at and not marker.exists():
        time.sleep(0.01)
    assert pid_file.exists()
    assert marker.read_text(encoding="utf-8") == "terminated"
    assert result.result == "BUDGET_EXCEEDED"
    assert result.result_reason == "BUDGET_EXCEEDED:core-deterministic:descendants"


def test_output_is_bounded_and_secret_values_are_redacted() -> None:
    environment = dict(os.environ)
    environment["NEWSROOM_TEST_API_TOKEN"] = "highly-sensitive-value"
    result = run_gate_command(
        gate_id="core-deterministic",
        phase="output",
        argv=_python(
            "import os; print('x' * 4096); print(os.environ['NEWSROOM_TEST_API_TOKEN'])"
        ),
        deadline=LaneDeadline.start(2),
        command_timeout_seconds=1,
        env=environment,
        output_limit_bytes=128,
    )

    assert result.result == "PASS"
    assert result.stdout_truncated is True
    assert "highly-sensitive-value" not in result.stdout
    assert "***" in result.stdout
    assert len(result.stdout.encode("utf-8")) <= 128


def test_environment_error_does_not_echo_command_or_exception_message() -> None:
    missing = "/definitely-not-a-newsroom-command/secret-value"
    result = run_gate_command(
        gate_id="route",
        phase="spawn",
        argv=(missing,),
        deadline=LaneDeadline.start(1),
        command_timeout_seconds=0.5,
    )

    assert result.result == "ENVIRONMENT_ERROR"
    assert result.returncode is None
    assert "secret-value" not in result.result_reason
    assert result.result_reason.endswith(":FileNotFoundError")


def test_invalid_budget_or_identifier_is_rejected() -> None:
    with pytest.raises(GateRunError, match="below 60"):
        LaneDeadline.start(60)
    with pytest.raises(GateRunError, match="unsupported characters"):
        run_gate_command(
            gate_id="bad:gate",
            phase="unit",
            argv=_python("pass"),
            deadline=LaneDeadline.start(1),
            command_timeout_seconds=0.5,
        )


def test_cli_uses_accepted_gate_and_lane_budget(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = watchdog_main(
        (
            "--repo-root",
            str(REPO_ROOT),
            "--gate-id",
            "route",
            "--phase",
            "cli",
            "--",
            sys.executable,
            "-c",
            "print('cli-ok')",
        )
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["schema_version"] == "newsroom.sdlc.gate-run.v1"
    assert payload["result"] == "PASS"
    assert payload["stdout"] == "cli-ok\n"
