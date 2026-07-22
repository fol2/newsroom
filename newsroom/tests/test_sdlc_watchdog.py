from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time

import pytest

from scripts.sdlc.contracts import load_contract
from scripts.sdlc.run_gate import (
    GateRunError,
    LaneDeadline,
    _run_gate_command,
    main as watchdog_main,
    run_configured_gate,
    start_lane_deadline,
)


REPO_ROOT = Path(__file__).parents[2]


def _python(source: str, *arguments: str) -> tuple[str, ...]:
    return (sys.executable, "-c", source, *arguments)


def test_success_and_nonzero_exit_are_typed() -> None:
    passed = _run_gate_command(
        gate_id="route",
        phase="unit",
        argv=_python("print('ok')"),
        deadline=LaneDeadline.start(4),
        command_timeout_seconds=3,
    )
    failed = _run_gate_command(
        gate_id="route",
        phase="unit",
        argv=_python("raise SystemExit(7)"),
        deadline=LaneDeadline.start(4),
        command_timeout_seconds=3,
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

    result = _run_gate_command(
        gate_id="core-deterministic",
        phase="tests",
        argv=_python(
            "from pathlib import Path; Path(__import__('sys').argv[1]).touch()",
            str(marker),
        ),
        deadline=deadline,
        command_timeout_seconds=1,
    )

    assert result.result == "BUDGET_EXCEEDED"
    assert result.returncode is None
    assert result.execution_ms == 0
    assert not marker.exists()


def test_multiple_commands_share_one_lane_deadline() -> None:
    deadline = LaneDeadline.start(2.5)
    started = time.monotonic()
    first = _run_gate_command(
        gate_id="core-deterministic",
        phase="first",
        argv=_python("import time; time.sleep(0.1)"),
        deadline=deadline,
        command_timeout_seconds=1.5,
        termination_grace_seconds=0.1,
    )
    second = _run_gate_command(
        gate_id="core-deterministic",
        phase="second",
        argv=_python("import time; time.sleep(5)"),
        deadline=deadline,
        command_timeout_seconds=3,
        termination_grace_seconds=0.2,
    )

    assert first.result == "PASS"
    assert second.result == "BUDGET_EXCEEDED"
    assert time.monotonic() - started < 2.5
    assert deadline.remaining_seconds() <= 0.25


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

    result = _run_gate_command(
        gate_id="core-deterministic",
        phase="descendants",
        argv=_python(parent, child, str(marker), str(pid_file)),
        deadline=LaneDeadline.start(3),
        command_timeout_seconds=2.5,
        termination_grace_seconds=0.5,
    )

    stop_at = time.monotonic() + 1
    while time.monotonic() < stop_at and not marker.exists():
        time.sleep(0.01)
    assert pid_file.exists()
    assert marker.read_text(encoding="utf-8") == "terminated"
    assert result.result == "BUDGET_EXCEEDED"
    assert result.execution_ms < 2_500
    assert result.result_reason == "BUDGET_EXCEEDED:core-deterministic:descendants"


@pytest.mark.skipif(os.name != "posix", reason="process-group evidence is POSIX-specific")
def test_successful_parent_cannot_leave_background_process(tmp_path: Path) -> None:
    pid_file = tmp_path / "background-pid"
    parent = """
import subprocess
from pathlib import Path
import sys

process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
Path(sys.argv[1]).write_text(str(process.pid), encoding='utf-8')
"""
    result = _run_gate_command(
        gate_id="core-deterministic",
        phase="background",
        argv=_python(parent, str(pid_file)),
        deadline=LaneDeadline.start(4),
        command_timeout_seconds=3,
        termination_grace_seconds=0.5,
    )

    assert pid_file.exists()
    assert result.result == "UNAUTHORISED_EFFECT"
    assert result.result_reason.endswith(":background_process")


def test_output_is_memory_bounded_and_secret_boundary_is_redacted() -> None:
    secret = "ultra-sensitive-boundary"
    environment = dict(os.environ)
    environment["NEWSROOM_TEST_API_TOKEN"] = secret
    result = _run_gate_command(
        gate_id="core-deterministic",
        phase="output",
        argv=_python(
            "import os, sys; "
            "sys.stdout.write('x' * 2000000); "
            "sys.stdout.write(os.environ['NEWSROOM_TEST_API_TOKEN'] + 'z' * 124)"
        ),
        deadline=LaneDeadline.start(5),
        command_timeout_seconds=3.5,
        env=environment,
        output_limit_bytes=128,
    )

    assert result.result == "PASS"
    assert result.stdout_truncated is True
    assert secret not in result.stdout
    assert "sensitive-boundary" not in result.stdout
    assert "***" in result.stdout
    assert len(result.stdout.encode("utf-8")) <= 128


def test_environment_error_does_not_echo_command_or_exception_message() -> None:
    missing = "/definitely-not-a-newsroom-command/secret-value"
    result = _run_gate_command(
        gate_id="route",
        phase="spawn",
        argv=(missing,),
        deadline=LaneDeadline.start(2),
        command_timeout_seconds=1,
        termination_grace_seconds=0.1,
    )

    assert result.result == "ENVIRONMENT_ERROR"
    assert result.returncode is None
    assert "secret-value" not in result.result_reason
    assert result.result_reason.endswith(":FileNotFoundError")


def test_deadline_and_configured_budget_cannot_be_raised() -> None:
    contract = load_contract(REPO_ROOT)
    assert start_lane_deadline(contract, "route").timeout_ms == 55_000

    with pytest.raises(GateRunError, match="below 60"):
        LaneDeadline(0, 60_000)
    with pytest.raises(GateRunError, match="accepted lane timeout"):
        run_configured_gate(
            contract=contract,
            gate_id="route",
            phase="oversized",
            argv=_python("pass"),
            deadline=LaneDeadline.start(59),
        )


def test_invalid_budget_identifier_and_output_limit_are_rejected() -> None:
    with pytest.raises(GateRunError, match="below 60"):
        LaneDeadline.start(60)
    with pytest.raises(GateRunError, match="unsupported characters"):
        _run_gate_command(
            gate_id="bad:gate",
            phase="unit",
            argv=_python("pass"),
            deadline=LaneDeadline.start(1),
            command_timeout_seconds=0.5,
        )
    with pytest.raises(GateRunError, match="output limit"):
        _run_gate_command(
            gate_id="route",
            phase="unit",
            argv=_python("pass"),
            deadline=LaneDeadline.start(2),
            command_timeout_seconds=1,
            output_limit_bytes=1_048_577,
        )
    with pytest.raises(GateRunError, match="five seconds"):
        _run_gate_command(
            gate_id="route",
            phase="unit",
            argv=_python("pass"),
            deadline=LaneDeadline.start(10),
            command_timeout_seconds=9,
            termination_grace_seconds=5.1,
        )


def test_cli_uses_accepted_gate_and_lane_budget(
    capsys: pytest.CaptureFixture[str],
) -> None:
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
