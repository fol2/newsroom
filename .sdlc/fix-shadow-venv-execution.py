from __future__ import annotations

from pathlib import Path

SOURCE = Path("scripts/sdlc/workflow_lane.py")
TEST = Path("newsroom/tests/test_sdlc_workflow_lane.py")
WORKFLOW_TEST = Path("newsroom/tests/test_sdlc_evidence_workflow.py")

source = SOURCE.read_text(encoding="utf-8")

marker = '''def _spec(
    *,
'''
helper = '''def _uv_command(*arguments: str) -> list[str]:
    executable = shutil.which("uv")
    if executable is None:
        raise WorkflowLaneError("uv_executable")
    path = Path(executable)
    if not path.is_absolute():
        raise WorkflowLaneError("uv_executable")
    return [path.as_posix(), "run", "--no-sync", "python", *arguments]


def _spec(
    *,
'''
if source.count(marker) != 1 or "def _uv_command(" in source:
    raise SystemExit("uv helper insertion mismatch")
source = source.replace(marker, helper)

replacements = {
'''        argv: list[str] = [
            sys.executable,
            "-m",
            "scripts.sdlc.workflow_lane",
            "source-check",
            "--repo-root",
            ".",
            "--base-sha",
            str(route["base_sha"]),
            "--head-sha",
            str(route["head_sha"]),
        ]
''': '''        argv: list[str] = _uv_command(
            "-m",
            "scripts.sdlc.workflow_lane",
            "source-check",
            "--repo-root",
            ".",
            "--base-sha",
            str(route["base_sha"]),
            "--head-sha",
            str(route["head_sha"]),
        )
''',
'''        argv = [
            sys.executable,
            "-m",
            "scripts.sdlc.workflow_lane",
            "core-tests",
            "--repo-root",
            ".",
            "--report",
            report.relative_to(root).as_posix(),
        ]
''': '''        argv = _uv_command(
            "-m",
            "scripts.sdlc.workflow_lane",
            "core-tests",
            "--repo-root",
            ".",
            "--report",
            report.relative_to(root).as_posix(),
        )
''',
'''        argv = [
            sys.executable,
            "-m",
            "scripts.sdlc.workflow_lane",
            "service-tests",
            "--repo-root",
            ".",
            "--report",
            report.relative_to(root).as_posix(),
            *[str(item) for item in route["service_tests"]],
        ]
''': '''        argv = _uv_command(
            "-m",
            "scripts.sdlc.workflow_lane",
            "service-tests",
            "--repo-root",
            ".",
            "--report",
            report.relative_to(root).as_posix(),
            *[str(item) for item in route["service_tests"]],
        )
''',
}
for old, new in replacements.items():
    if source.count(old) != 1:
        raise SystemExit("command replacement mismatch")
    source = source.replace(old, new)
SOURCE.write_text(source, encoding="utf-8")

tests = TEST.read_text(encoding="utf-8")
if "test_expected_spec_uses_uv_run_to_preserve_locked_environment" in tests:
    raise SystemExit("uv execution tests already present")
tests += '''


def test_expected_spec_uses_uv_run_to_preserve_locked_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract(tmp_path)
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    captured: dict[str, object] = {}
    monkeypatch.setattr(lane_module.shutil, "which", lambda name: "/opt/uv/bin/uv")
    monkeypatch.setattr(
        lane_module,
        "_spec",
        lambda **kwargs: captured.update(kwargs) or SimpleNamespace(),
    )

    lane_module._expected_spec(
        root=tmp_path,
        artifact_root=artifact,
        contract=contract,
        route=_route(),
        gate_id="core-deterministic",
        phase="tests",
    )

    assert captured["argv"][:6] == [
        "/opt/uv/bin/uv",
        "run",
        "--no-sync",
        "python",
        "-m",
        "scripts.sdlc.workflow_lane",
    ]


def test_uv_command_fails_closed_when_uv_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lane_module.shutil, "which", lambda name: None)
    with pytest.raises(WorkflowLaneError, match="uv_executable"):
        lane_module._uv_command("-c", "print('never')")


def test_uv_command_uses_the_locked_project_environment() -> None:
    completed = lane_module.subprocess.run(
        lane_module._uv_command("-c", "import pytest"),
        cwd=REPO_ROOT,
        check=False,
        stdout=lane_module.subprocess.PIPE,
        stderr=lane_module.subprocess.PIPE,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
'''
TEST.write_text(tests, encoding="utf-8")

workflow_tests = WORKFLOW_TEST.read_text(encoding="utf-8")
old_assertion = '    assert "secrets." not in rendered\n'
new_assertion = '    assert "${{ secrets." not in rendered\n'
if workflow_tests.count(old_assertion) != 1:
    raise SystemExit("GitHub secrets assertion mismatch")
workflow_tests = workflow_tests.replace(old_assertion, new_assertion)
WORKFLOW_TEST.write_text(workflow_tests, encoding="utf-8")
