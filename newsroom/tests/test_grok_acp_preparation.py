from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import pytest

from newsroom.graphiti_adapter import cli_client
from newsroom.graphiti_adapter.cursor_transport import CliPredispatchRefusal


_ACP_FIXTURE = r'''#!{python}
import json, os, pathlib, sys, time

scenario = os.environ["FIXTURE_SCENARIO"]
record = pathlib.Path(os.environ["FIXTURE_RECORD"])
pathlib.Path(os.environ["FIXTURE_PID"]).write_text(str(os.getpid()))
with record.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({{"argv": sys.argv[1:]}}) + "\n")
    handle.flush()
    for raw in sys.stdin:
        request = json.loads(raw)
        handle.write(json.dumps(request) + "\n")
        handle.flush()
        if scenario == "missing":
            sys.exit(0)
        if scenario == "malformed":
            print("not-json", flush=True)
            time.sleep(30)
        if scenario == "timeout":
            time.sleep(30)
        if scenario == "output-bound":
            print("x" * 70000, flush=True)
            time.sleep(30)
        response_id = request["id"]
        if scenario == "error":
            response = {{"jsonrpc": "2.0", "id": response_id,
                        "error": {{"code": -32000, "message": "fixture"}}}}
        elif request["method"] == "session/new":
            session_id = ("different-session" if scenario == "id-mismatch"
                          else request["params"]["_meta"]["sessionId"])
            response = {{"jsonrpc": "2.0", "id": response_id,
                        "result": {{"sessionId": session_id}}}}
        elif request["method"] == "_x.ai/session/rename":
            response = {{"jsonrpc": "2.0", "id": response_id,
                        "result": {{"success": True}}}}
        elif request["method"] == "session/close":
            response = {{"jsonrpc": "2.0", "id": response_id,
                        "result": {{"_meta": {{"x.ai/closeOutcome": "closed"}}}}}}
        else:
            response = {{"jsonrpc": "2.0", "id": response_id, "result": {{}}}}
        notification = {{"jsonrpc": "2.0", "method": "session/update", "params": {{}}}}
        print(json.dumps(notification), flush=True)
        print(json.dumps(response), flush=True)
        if scenario not in ("success", "id-mismatch"):
            time.sleep(30)
time.sleep(30)
'''


def _workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str
) -> tuple[cli_client._GraphitiCliWorkspace, Path, Path]:
    binary = tmp_path / "grok-fixture"
    binary.write_text(_ACP_FIXTURE.format(python=sys.executable), encoding="utf-8")
    binary.chmod(0o700)
    record = tmp_path / "requests.ndjson"
    pid_path = tmp_path / "pid"
    (tmp_path / "root").mkdir()
    workspace = cli_client._hermetic_cli_workspace(
        str(tmp_path / "root"), binary=str(binary)
    )
    workspace.environment.update(
        FIXTURE_SCENARIO=scenario,
        FIXTURE_RECORD=str(record),
        FIXTURE_PID=str(pid_path),
    )
    monkeypatch.setattr(cli_client, "GROK_BIN", str(binary))
    return workspace, record, pid_path


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_grok_acp_preparation_awaits_create_rename_and_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, record, pid_path = _workspace(tmp_path, monkeypatch, "success")

    session_id = asyncio.run(
        cli_client._prepare_grok_resume_session_async(workspace)
    )

    records = [json.loads(line) for line in record.read_text().splitlines()]
    assert records[0]["argv"] == [
        "--cwd",
        workspace.cwd,
        "--model",
        "grok-4.6",
        "--reasoning-effort",
        "medium",
        "agent",
        "--no-leader",
        "stdio",
    ]
    requests = records[1:]
    assert [item["method"] for item in requests] == [
        "initialize",
        "session/new",
        "_x.ai/session/rename",
        "session/close",
    ]
    assert requests[0]["params"]["protocolVersion"] == 1
    assert requests[0]["params"]["clientCapabilities"] == {}
    assert requests[1]["params"] == {
        "cwd": workspace.cwd,
        "mcpServers": [],
        "_meta": {
            "source": "newsroom-graphiti-fallback",
            "sessionId": session_id,
            "sessionKind": "headless",
            "modelId": "grok-4.6",
        },
    }
    assert requests[2]["params"] == {
        "sessionId": session_id,
        "title": "newsroom-graphiti-fallback",
        "cwd": workspace.cwd,
    }
    assert requests[3]["params"] == {"sessionId": session_id}
    assert not _is_running(int(pid_path.read_text()))


@pytest.mark.parametrize(
    "scenario",
    ("missing", "malformed", "error", "id-mismatch", "timeout", "output-bound"),
)
def test_grok_acp_preparation_fails_closed_before_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    workspace, record, pid_path = _workspace(tmp_path, monkeypatch, scenario)
    if scenario == "timeout":
        monkeypatch.setattr(cli_client, "GROK_ACP_PREP_TIMEOUT_SECONDS", 1.0)

    with pytest.raises(CliPredispatchRefusal):
        asyncio.run(cli_client._prepare_grok_resume_session_async(workspace))

    assert record.exists()
    assert not _is_running(int(pid_path.read_text()))


def test_grok_acp_preparation_cancellation_stops_owned_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, record, pid_path = _workspace(tmp_path, monkeypatch, "timeout")

    async def cancel() -> None:
        task = asyncio.create_task(
            cli_client._prepare_grok_resume_session_async(workspace)
        )
        deadline = asyncio.get_running_loop().time() + 1
        while not record.exists():
            if asyncio.get_running_loop().time() >= deadline:
                pytest.fail("ACP fixture did not receive a request")
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel())
    assert not _is_running(int(pid_path.read_text()))


@pytest.mark.parametrize("asynchronous", (False, True))
def test_grok_dispatch_marker_follows_successful_acp_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, asynchronous: bool
) -> None:
    events: list[str] = []
    monkeypatch.setattr(cli_client, "_prove_cli_controls", lambda **_values: None)

    async def prove_async(**_values: object) -> None:
        return None

    monkeypatch.setattr(cli_client, "_prove_cli_controls_async", prove_async)
    monkeypatch.setattr(
        cli_client,
        "_prepare_grok_resume_session",
        lambda _workspace: events.append("prepared") or "fixture-session",
    )

    async def prepare_async(_workspace: object) -> str:
        events.append("prepared")
        return "fixture-session"

    monkeypatch.setattr(cli_client, "_prepare_grok_resume_session_async", prepare_async)

    def run(*_args: object, **kwargs: object) -> str:
        events.append("run")
        assert kwargs.get("cwd") is not None
        return "{}"

    async def run_async(*_args: object, **kwargs: object) -> str:
        return run(*_args, **kwargs)

    monkeypatch.setattr(cli_client, "run_cli", run)
    monkeypatch.setattr(cli_client, "run_cli_async", run_async)
    callback = lambda: events.append("dispatch")

    if asynchronous:
        asyncio.run(
            cli_client.run_grok_llm_async(
                "prompt", None, max_tokens=1, dispatch_started=callback
            )
        )
    else:
        cli_client.run_grok_llm(
            "prompt", None, max_tokens=1, dispatch_started=callback
        )

    assert events == ["prepared", "dispatch", "run"]


@pytest.mark.parametrize("asynchronous", (False, True))
def test_grok_acp_failure_precedes_dispatch_marker(
    monkeypatch: pytest.MonkeyPatch, asynchronous: bool
) -> None:
    monkeypatch.setattr(cli_client, "_prove_cli_controls", lambda **_values: None)

    async def prove_async(**_values: object) -> None:
        return None

    monkeypatch.setattr(cli_client, "_prove_cli_controls_async", prove_async)

    def fail(_workspace: object) -> str:
        raise CliPredispatchRefusal("fixture")

    async def fail_async(_workspace: object) -> str:
        raise CliPredispatchRefusal("fixture")

    monkeypatch.setattr(cli_client, "_prepare_grok_resume_session", fail)
    monkeypatch.setattr(cli_client, "_prepare_grok_resume_session_async", fail_async)
    dispatches: list[None] = []

    with pytest.raises(CliPredispatchRefusal):
        if asynchronous:
            asyncio.run(
                cli_client.run_grok_llm_async(
                    "prompt",
                    None,
                    max_tokens=1,
                    dispatch_started=lambda: dispatches.append(None),
                )
            )
        else:
            cli_client.run_grok_llm(
                "prompt",
                None,
                max_tokens=1,
                dispatch_started=lambda: dispatches.append(None),
            )

    assert dispatches == []
