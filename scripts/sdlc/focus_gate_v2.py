from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path
from shutil import copyfile
from typing import Mapping, Sequence

from . import focus_gate as legacy
from .focus_selector import select_focus

FocusGateError = legacy.FocusGateError

HARDENING_CONTRACT_VERSION = "focus-gates-hardening-v1"
_EXPECTED = {
    "schema_version": "newsroom.sdlc.focus-gates-hardening.v1",
    "contract_version": HARDENING_CONTRACT_VERSION,
    "status": "accepted",
    "issue": 811,
    "ordinary_router": "scripts/sdlc/focus_gate_v2.py",
    "selector": "scripts/sdlc/focus_selector.py",
    "full_health_events": ["push_main", "schedule", "workflow_dispatch"],
    "merge_model": "agent_exact_head_focus_review",
    "platform_required_status_checks": False,
    "stateful_sentinel_count": 2,
    "f0_syntax": ["python", "json", "toml", "yaml", "shell"],
}


def load_hardening_contract(repo_root: str | Path) -> Mapping[str, object]:
    root = Path(repo_root).resolve()
    legacy.load_focus_contract(root)
    path = root / ".sdlc" / "gates.toml"
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    selected = data.get("focus_hardening")
    if selected != _EXPECTED:
        raise legacy.FocusGateError("Focus Gate hardening contract differs from accepted policy")
    for key in ("ordinary_router", "selector"):
        target = root / str(selected[key])
        if target.is_symlink() or not target.is_file():
            raise legacy.FocusGateError(f"Focus Gate hardening file is missing: {selected[key]}")
    return selected


def build_route(
    repo_root: str | Path,
    *,
    base_reference: str,
    head_reference: str,
) -> dict[str, object]:
    root = Path(repo_root).resolve()
    load_hardening_contract(root)
    base_sha = legacy.resolve_commit(root, base_reference)
    head_sha = legacy.resolve_commit(root, head_reference)
    head_tree_sha = legacy.resolve_tree(root, head_sha)
    legacy.verify_exact_clean_checkout(root, head_sha=head_sha, head_tree_sha=head_tree_sha)
    changes = legacy.changed_paths(root, base_sha, head_sha)
    selected_paths = tuple(
        sorted({path for change in changes for path in change.classified_paths()})
    )
    return select_focus(
        selected_paths,
        repo_root=root,
        base_sha=base_sha,
        head_sha=head_sha,
        base_tree_sha=legacy.resolve_tree(root, base_sha),
        head_tree_sha=head_tree_sha,
    )


def _validate_yaml(path: Path) -> None:
    try:
        import yaml
    except ImportError as exc:
        raise legacy.FocusGateError(
            "YAML validation requires the routed locked environment"
        ) from exc
    try:
        yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise legacy.FocusGateError(f"invalid YAML: {path}") from exc


def _validate_shell(path: Path) -> None:
    completed = subprocess.run(
        ("bash", "-n", str(path)),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        detail = completed.stderr.strip() or "bash syntax check failed"
        raise legacy.FocusGateError(f"invalid shell syntax: {path}: {detail}")


def verify_route(repo_root: str | Path, route_path: str | Path) -> dict[str, object]:
    root = Path(repo_root).resolve()
    load_hardening_contract(root)
    route = legacy._load_manifest(route_path)
    current_head = legacy.resolve_commit(root, "HEAD")
    current_tree = legacy.resolve_tree(root, current_head)
    if (route["head_sha"], route["head_tree_sha"]) != (current_head, current_tree):
        raise legacy.FocusGateError("manifest does not describe the checked-out head")
    status = subprocess.run(
        ("git", "status", "--porcelain=v1", "--untracked-files=no"),
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if status.returncode or status.stdout:
        raise legacy.FocusGateError("tracked checkout differs from the routed head")
    legacy._git_diff_check(root, str(route["base_sha"]), current_head)

    for relative in route["changed_paths"]:
        path = root / str(relative)
        if not path.exists():
            continue
        if path.is_symlink() or not path.is_file():
            raise legacy.FocusGateError(f"unsupported changed entry: {relative}")
        suffix = path.suffix.lower()
        if suffix == ".py":
            compile(path.read_text(encoding="utf-8"), str(path), "exec", dont_inherit=True)
        elif suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))
        elif suffix == ".toml":
            tomllib.loads(path.read_text(encoding="utf-8"))
        elif suffix in {".yml", ".yaml"}:
            _validate_yaml(path)
        elif suffix in {".sh", ".bash"}:
            _validate_shell(path)
    for selected in (*route["selected_tests"], *route["selected_service_tests"]):
        if selected != "newsroom/tests" and not (
            root / str(selected).split("::", 1)[0]
        ).is_file():
            raise legacy.FocusGateError(f"selected test is missing: {selected}")
    return route


def execute_route(
    repo_root: str | Path,
    route_path: str | Path,
    *,
    junit: str | Path,
) -> int:
    root = Path(repo_root).resolve()
    route = verify_route(root, route_path)
    if route["research_required"] and not route["bootstrap_required"]:
        return 0
    if route["full_health_required"]:
        return legacy.execute_full_health(root, junit=junit)
    selected_tests = tuple(sorted(set(route["selected_tests"])))
    selected_service_tests = tuple(sorted(set(route["selected_service_tests"])))
    if not selected_tests and not selected_service_tests:
        return 0
    commands = build_selected_test_commands(
        root,
        selected_tests=selected_tests,
        selected_service_tests=selected_service_tests,
        junit=junit,
    )
    requested_report = legacy._junit_path(root, junit)
    requested_report.unlink(missing_ok=True)
    phase_reports: list[Path] = []
    for command in commands:
        phase_report = Path(
            next(
                value.split("=", 1)[1]
                for value in command
                if value.startswith("--junitxml=")
            )
        )
        phase_report.unlink(missing_ok=True)
        result = subprocess.run(command, cwd=root, check=False).returncode
        phase_reports.append(phase_report)
        if result:
            _merge_junit_reports(requested_report, tuple(phase_reports))
            return result
    _merge_junit_reports(requested_report, tuple(phase_reports))
    return 0


def build_selected_test_commands(
    repo_root: str | Path,
    *,
    selected_tests: Sequence[str],
    selected_service_tests: Sequence[str],
    junit: str | Path,
) -> tuple[tuple[str, ...], ...]:
    """Build the fixed parallel/local then serial/service Focus commands."""

    root = Path(repo_root).resolve()
    requested = legacy._junit_path(root, junit)
    suffix = requested.suffix or ".xml"
    stem = requested.with_suffix("")
    common = (
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--assert=plain",
        "-p",
        "no:cacheprovider",
    )
    commands: list[tuple[str, ...]] = []
    local = tuple(sorted(set(selected_tests)))
    service = tuple(sorted(set(selected_service_tests)))
    if local:
        commands.append(
            (
                *common,
                "-n",
                "4",
                "--dist",
                "worksteal",
                "--max-worker-restart=0",
                *local,
                f"--junitxml={stem}-provider-free{suffix}",
            )
        )
    if service:
        commands.append(
            (
                *common,
                *service,
                f"--junitxml={stem}-service{suffix}",
            )
        )
    return tuple(commands)


def _merge_junit_reports(destination: Path, reports: Sequence[Path]) -> None:
    """Preserve the requested JUnit path while retaining phase reports."""

    existing = tuple(path for path in reports if path.is_file())
    if not existing:
        return
    if len(existing) == 1:
        copyfile(existing[0], destination)
        return
    suites = ET.Element("testsuites")
    totals = {key: 0 for key in ("tests", "failures", "errors", "skipped")}
    total_time = 0.0
    for report in existing:
        root = ET.parse(report).getroot()
        children = list(root) if root.tag == "testsuites" else [root]
        for child in children:
            suites.append(child)
            for key in totals:
                totals[key] += int(child.attrib.get(key, "0"))
            total_time += float(child.attrib.get("time", "0"))
    suites.attrib.update({key: str(value) for key, value in totals.items()})
    suites.attrib["time"] = f"{total_time:.6f}"
    ET.ElementTree(suites).write(destination, encoding="utf-8", xml_declaration=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Route and execute hardened Focus Gates")
    parser.add_argument("--repo-root", default=".")
    commands = parser.add_subparsers(dest="command", required=True)
    route = commands.add_parser("route")
    route.add_argument("--base", required=True)
    route.add_argument("--head", required=True)
    route.add_argument("--output", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--route", required=True)
    execute = commands.add_parser("execute")
    execute.add_argument("--route", required=True)
    execute.add_argument("--junit", required=True)
    full_health = commands.add_parser("full-health")
    full_health.add_argument("--junit", required=True)
    summary = commands.add_parser("summary")
    summary.add_argument("--route", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "route":
            value = build_route(
                arguments.repo_root,
                base_reference=arguments.base,
                head_reference=arguments.head,
            )
            legacy._write_manifest(arguments.output, value)
        elif arguments.command == "verify":
            value = verify_route(arguments.repo_root, arguments.route)
        elif arguments.command == "execute":
            return execute_route(
                arguments.repo_root,
                arguments.route,
                junit=arguments.junit,
            )
        elif arguments.command == "full-health":
            load_hardening_contract(arguments.repo_root)
            return legacy.execute_full_health(arguments.repo_root, junit=arguments.junit)
        else:
            value = legacy._load_manifest(arguments.route)
        sys.stdout.write(legacy.canonical_json_bytes(value).decode("utf-8") + "\n")
        return 0
    except (
        legacy.FocusGateError,
        json.JSONDecodeError,
        OSError,
        UnicodeError,
        tomllib.TOMLDecodeError,
    ) as exc:
        print(f"FOCUS_GATE_ERROR:{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
