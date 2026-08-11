from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.sdlc.workflow_lane as lane_module
from scripts.sdlc.command_spec import CommandRun
from scripts.sdlc.run_gate import GateRunResult
from scripts.sdlc.workflow_lane import WorkflowLaneError

REPO_ROOT = Path(__file__).parents[2]


def _contract_data() -> dict[str, object]:
    return {
        "contract_version": "sdlc-v2.5",
        "status": "accepted",
        "lanes": {
            "core": {
                "hard_timeout_seconds": 220,
                "per_shard_hard_timeout_seconds": 220,
            }
        },
    }


def _write_fragment_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    directory_order: tuple[int, ...] = (0, 1, 2, 3, 4, 5),
) -> tuple[Path, object, object, dict[str, object]]:
    fragments = tmp_path / "fragments"
    fragments.mkdir(parents=True)
    contract = SimpleNamespace(
        repo_root=tmp_path,
        contract_version="sdlc-v2.5",
        data=_contract_data(),
    )
    context = SimpleNamespace(
        run_id=381,
        run_attempt=2,
        job_id="core",
        evaluated_sha="a" * 40,
        evaluated_tree_sha="b" * 40,
    )
    route: dict[str, object] = {
        "head_sha": context.evaluated_sha,
        "head_tree_sha": context.evaluated_tree_sha,
        "clustering_required": False,
    }
    files = tuple(f"newsroom/tests/test_{index}.py" for index in range(6))
    nodes = tuple(f"{path}::test_{index}" for index, path in enumerate(files))
    shards = lane_module._core_node_shards(nodes)
    spec = SimpleNamespace(
        as_dict=lambda: {"schema_version": "test-command-spec"},
        digest="sha256:" + "c" * 64,
    )
    binding = {
        "contract_version": "sdlc-v2.5",
        "contract_digest": "sha256:" + "d" * 64,
        "lockfile_digest": "sha256:" + "e" * 64,
        "python_version": "3.12.11",
        "uv_version": "0.8.0",
        "toolchain_digest": "sha256:" + "f" * 64,
    }
    monkeypatch.setattr(lane_module, "_core_test_files", lambda _root: files)
    monkeypatch.setattr(
        lane_module, "_collect_core_node_ids", lambda _root, **_kwargs: nodes
    )
    monkeypatch.setattr(lane_module, "_core_shard_spec", lambda **_kwargs: spec)
    monkeypatch.setattr(lane_module, "_fragment_provenance", lambda **_kwargs: binding)
    for directory_number, shard_index in enumerate(directory_order):
        directory = fragments / f"input-{directory_number}"
        directory.mkdir()
        run = CommandRun(
            spec.digest,
            GateRunResult(
                "core-deterministic",
                "tests",
                "BUDGET_EXCEEDED",
                "BUDGET_EXCEEDED:core-deterministic:tests",
                None,
                200_000 + shard_index,
                "",
                "",
                False,
                False,
            ),
        )
        body: dict[str, object] = {
            "schema_version": lane_module._CORE_FRAGMENT_SCHEMA,
            "run_id": context.run_id,
            "run_attempt": context.run_attempt,
            "job_id": "core_shard",
            "evaluated_sha": context.evaluated_sha,
            "evaluated_tree_sha": context.evaluated_tree_sha,
            "route_digest": lane_module.sha256_identity(route),
            "shard_index": shard_index,
            "shard_count": 6,
            "file_inventory": list(files),
            "file_inventory_digest": lane_module.sha256_identity(list(files)),
            "node_inventory": list(nodes),
            "node_inventory_digest": lane_module.sha256_identity(list(nodes)),
            "selected_node_ids": list(shards[shard_index]),
            "selected_node_ids_digest": lane_module.sha256_identity(
                list(shards[shard_index])
            ),
            "command_spec": spec.as_dict(),
            "command_run": run.as_dict(),
            "shard_lifecycle": {
                "schema_version": lane_module._CORE_SHARD_LIFECYCLE_SCHEMA,
                "elapsed_ms": 200_000 + shard_index,
                "timeout_ms": 220_000,
                "result": "BUDGET_EXCEEDED",
            },
            "junit_summary": None,
            "report_digest": None,
            **binding,
        }
        fragment = {**body, "fragment_identity": lane_module._fragment_identity(body)}
        (directory / "fragment.json").write_bytes(
            lane_module.canonical_json_bytes(fragment) + b"\n"
        )
    return fragments, contract, context, route


def _rewrite_fragment(
    path: Path,
    changes: dict[str, object],
    *,
    refresh_identity: bool = True,
) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    value.update(changes)
    if refresh_identity:
        unsigned = dict(value)
        unsigned.pop("fragment_identity")
        value["fragment_identity"] = lane_module._fragment_identity(unsigned)
    path.write_bytes(lane_module.canonical_json_bytes(value) + b"\n")


def _rewrite_fragment_as_pass(path: Path) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    command_run = value["command_run"]
    assert isinstance(command_run, dict)
    gate_run = command_run["gate_run"]
    assert isinstance(gate_run, dict)
    gate_run.update(
        {
            "result": "PASS",
            "result_reason": "PASS:core-deterministic:tests",
            "returncode": 0,
        }
    )
    lifecycle = value["shard_lifecycle"]
    assert isinstance(lifecycle, dict)
    lifecycle["result"] = "PASS"
    _rewrite_fragment(
        path,
        {"command_run": command_run, "shard_lifecycle": lifecycle},
    )


def _patch_core_shard_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    result: str,
    report_payload: str | None,
) -> None:
    contract = SimpleNamespace(
        repo_root=tmp_path,
        contract_version="sdlc-v2.5",
        data=_contract_data(),
    )
    context = SimpleNamespace(
        run_id=381,
        run_attempt=2,
        job_id="core_shard",
        evaluated_sha="a" * 40,
        evaluated_tree_sha="b" * 40,
    )
    route = {
        "head_sha": context.evaluated_sha,
        "head_tree_sha": context.evaluated_tree_sha,
        "clustering_required": False,
    }
    files = tuple(f"newsroom/tests/test_{index}.py" for index in range(6))
    nodes = tuple(f"{path}::test_{index}" for index, path in enumerate(files))
    spec = SimpleNamespace(
        as_dict=lambda: {"schema_version": "test-command-spec"},
        digest="sha256:" + "c" * 64,
    )
    returncode = 0 if result == "PASS" else (None if result != "FAIL" else 1)
    reason = (
        "FAIL:core-deterministic:tests:exit=1"
        if result == "FAIL"
        else f"{result}:core-deterministic:tests"
    )
    run = CommandRun(
        spec.digest,
        GateRunResult(
            "core-deterministic",
            "tests",
            result,
            reason,
            returncode,
            219_950,
            "",
            "",
            False,
            False,
        ),
    )
    monkeypatch.setattr(lane_module, "load_contract", lambda _root: contract)
    monkeypatch.setattr(lane_module, "context_from_environment", lambda _root: context)
    monkeypatch.setattr(lane_module, "_load_json", lambda *_args: route)
    monkeypatch.setattr(lane_module, "_validate_route", lambda *_args: route)
    monkeypatch.setattr(lane_module, "_validate_test_topology", lambda *_args: None)
    monkeypatch.setattr(lane_module, "_core_test_files", lambda _root: files)
    monkeypatch.setattr(
        lane_module, "_collect_core_node_ids", lambda _root, **_kwargs: nodes
    )
    monkeypatch.setattr(lane_module, "_core_shard_spec", lambda **_kwargs: spec)
    monkeypatch.setattr(
        lane_module,
        "start_lane_deadline",
        lambda *_args: lane_module.LaneDeadline.start(220),
    )
    monkeypatch.setattr(lane_module, "verify_tracked_checkout", lambda *_args: None)
    monkeypatch.setattr(
        lane_module,
        "_fragment_provenance",
        lambda **_kwargs: {
            "contract_version": "sdlc-v2.5",
            "contract_digest": "sha256:" + "d" * 64,
            "lockfile_digest": "sha256:" + "e" * 64,
            "python_version": "3.12.11",
            "uv_version": "0.8.0",
            "toolchain_digest": "sha256:" + "f" * 64,
        },
    )

    def execute(**_kwargs: object) -> CommandRun:
        if report_payload is not None:
            (tmp_path / "artifacts/core-fragment/pytest.xml").write_text(
                report_payload,
                encoding="utf-8",
            )
        return run

    monkeypatch.setattr(lane_module, "_execute", execute)
    (tmp_path / "artifacts").mkdir()


def _patch_source_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[SimpleNamespace, dict[str, object]]:
    contract = SimpleNamespace(
        repo_root=tmp_path,
        contract_version="sdlc-v2.5",
        data=_contract_data(),
    )
    context = SimpleNamespace(
        run_id=381,
        run_attempt=2,
        job_id="source",
        evaluated_sha="a" * 40,
        evaluated_tree_sha="b" * 40,
    )
    route: dict[str, object] = {
        "head_sha": context.evaluated_sha,
        "head_tree_sha": context.evaluated_tree_sha,
        "clustering_required": False,
    }
    spec = SimpleNamespace(
        as_dict=lambda: {"schema_version": "test-command-spec"},
        digest="sha256:" + "c" * 64,
    )
    run = CommandRun(
        spec.digest,
        GateRunResult(
            "source-integrity",
            "source",
            "PASS",
            "PASS:source-integrity:source",
            0,
            1,
            "",
            "",
            False,
            False,
        ),
    )
    monkeypatch.setattr(lane_module, "load_contract", lambda _root: contract)
    monkeypatch.setattr(lane_module, "context_from_environment", lambda _root: context)
    monkeypatch.setattr(lane_module, "_load_json", lambda *_args: route)
    monkeypatch.setattr(lane_module, "_validate_route", lambda *_args: route)
    monkeypatch.setattr(lane_module, "_validate_test_topology", lambda *_args: None)
    monkeypatch.setattr(lane_module, "_source_fragment_spec", lambda **_kwargs: spec)
    monkeypatch.setattr(lane_module, "_execute", lambda **_kwargs: run)
    monkeypatch.setattr(
        lane_module,
        "start_lane_deadline",
        lambda *_args: lane_module.LaneDeadline.start(220),
    )
    monkeypatch.setattr(lane_module, "verify_tracked_checkout", lambda *_args: None)
    monkeypatch.setattr(
        lane_module,
        "_fragment_provenance",
        lambda **_kwargs: {
            "contract_version": "sdlc-v2.5",
            "contract_digest": "sha256:" + "d" * 64,
            "lockfile_digest": "sha256:" + "e" * 64,
            "python_version": "3.12.11",
            "uv_version": "0.8.0",
            "toolchain_digest": "sha256:" + "f" * 64,
        },
    )
    (tmp_path / "artifacts").mkdir()
    return context, route


def _write_bound_junit(fragment_path: Path, *, node_id: str | None = None) -> None:
    value = json.loads(fragment_path.read_text(encoding="utf-8"))
    selected = value["selected_node_ids"]
    assert isinstance(selected, list) and len(selected) == 1
    junit_id = lane_module._junit_id_for_node(node_id or selected[0])
    classname, name = junit_id.rsplit("::", 1)
    report = fragment_path.with_name("pytest.xml")
    report.write_text(
        (
            '<testsuites tests="1" failures="0" errors="0" skipped="0">'
            '<testsuite name="pytest" tests="1" failures="0" errors="0" '
            'skipped="0">'
            f'<testcase classname="{classname}" name="{name}" time="0.001" />'
            "</testsuite></testsuites>"
        ),
        encoding="utf-8",
    )
    summary = lane_module._report_summary(
        repo_root=fragment_path.parents[2],
        artifact_root=fragment_path.parent,
        report=report,
        optional_test_ids=(),
    )
    assert summary is not None
    _rewrite_fragment(
        fragment_path,
        {
            "junit_summary": summary.as_dict(),
            "report_digest": lane_module._file_digest(report),
        },
    )


def _passing_report() -> str:
    return (
        '<testsuite tests="1" failures="0" errors="0" skipped="0">'
        '<testcase classname="newsroom.tests.test_0" name="test_0" '
        'time="0.001" />'
        "</testsuite>"
    )


def _initialise_tracked_file(tmp_path: Path) -> tuple[Path, str]:
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("accepted\n", encoding="utf-8")
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)
    subprocess.run(("git", "add", "tracked.txt"), cwd=tmp_path, check=True)
    subprocess.run(
        (
            "git",
            "-c",
            "user.name=SDLC Test",
            "-c",
            "user.email=sdlc@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ),
        cwd=tmp_path,
        check=True,
    )
    head = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return tracked, head


def _run_reducer_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    source_elapsed_ms: int,
    shard_elapsed_ms: tuple[int, int, int, int, int, int],
    reducer_elapsed_ms: int,
    load_elapsed_ms: int | None = None,
    output_elapsed_ms: int | None = None,
) -> tuple[dict[str, object], list[str]]:
    fragments_root = tmp_path / "fragments"
    source_root = tmp_path / "source"
    output_parent = tmp_path / "output"
    for directory in (fragments_root, source_root, output_parent):
        directory.mkdir(parents=True)
    contract = SimpleNamespace(
        repo_root=tmp_path,
        contract_version="sdlc-v2.5",
        data=_contract_data(),
    )
    context = SimpleNamespace(
        run_id=381,
        run_attempt=2,
        job_id="core",
        evaluated_sha="a" * 40,
        evaluated_tree_sha="b" * 40,
    )
    route: dict[str, object] = {
        "head_sha": context.evaluated_sha,
        "head_tree_sha": context.evaluated_tree_sha,
        "clustering_required": False,
    }

    def run(gate_id: str, phase: str, elapsed_ms: int) -> CommandRun:
        return CommandRun(
            "sha256:" + "9" * 64,
            GateRunResult(
                gate_id,
                phase,
                "PASS",
                f"PASS:{gate_id}:{phase}",
                0,
                elapsed_ms,
                "",
                "",
                False,
                False,
            ),
        )

    source_run = run("source-integrity", "source", 1)
    source = {
        "command_run": source_run.as_dict(),
        "source_lifecycle": {
            "schema_version": lane_module._SOURCE_LIFECYCLE_SCHEMA,
            "elapsed_ms": source_elapsed_ms,
            "timeout_ms": 220_000,
            "result": "PASS",
        },
        "fragment_identity": "sha256:" + "8" * 64,
    }
    fragments = tuple(
        (
            {
                "command_run": run("core-deterministic", "tests", 10).as_dict(),
                "shard_lifecycle": {
                    "schema_version": lane_module._CORE_SHARD_LIFECYCLE_SCHEMA,
                    "elapsed_ms": elapsed,
                    "timeout_ms": 220_000,
                    "result": "PASS",
                },
                "junit_summary": None,
                "fragment_identity": "sha256:" + str(index) * 64,
                "selected_node_ids": [],
            },
            fragments_root / f"shard-{index}.xml",
        )
        for index, elapsed in enumerate(shard_elapsed_ms)
    )
    deadline = lane_module.LaneDeadline.start(220)
    elapsed = {"value": reducer_elapsed_ms}
    order: list[str] = []

    def start(*_args: object) -> object:
        order.append("start")
        return deadline

    def load_fragments(**_kwargs: object) -> object:
        order.append("load-fragments")
        if load_elapsed_ms is not None:
            elapsed["value"] = load_elapsed_ms
        return fragments

    def load_source(**_kwargs: object) -> object:
        order.append("load-source")
        return source

    monkeypatch.setattr(
        lane_module,
        "_context_route",
        lambda **_kwargs: (contract, context, route),
    )
    monkeypatch.setattr(lane_module, "start_lane_deadline", start)
    monkeypatch.setattr(lane_module, "_load_core_fragments", load_fragments)
    monkeypatch.setattr(lane_module, "_load_source_fragment", load_source)
    monkeypatch.setattr(
        lane_module,
        "_deadline_elapsed_ms",
        lambda observed: elapsed["value"] if observed is deadline else 0,
    )
    monkeypatch.setattr(
        lane_module,
        "_expected_spec",
        lambda **_kwargs: SimpleNamespace(digest="sha256:" + "9" * 64),
    )
    monkeypatch.setattr(lane_module, "artifact_name", lambda _context: "artifact")
    monkeypatch.setattr(lane_module, "verify_tracked_checkout", lambda *_args: None)
    if output_elapsed_ms is not None:
        private_write = lane_module._private_write

        def delayed_output(path: Path, value: object) -> None:
            private_write(path, value)
            if "core-deterministic" in path.parts and path.name == "command-run.json":
                elapsed["value"] = output_elapsed_ms

        monkeypatch.setattr(lane_module, "_private_write", delayed_output)

    lane_module.reduce_core_lane(
        repo_root=tmp_path,
        route_path="route.json",
        fragment_root="fragments",
        source_root="source",
        artifact_root="output/core",
    )
    aggregate_path = (
        output_parent / "core/gates/core-deterministic/tests/command-run.json"
    )
    return json.loads(aggregate_path.read_text(encoding="utf-8")), order


def test_core_lane_uses_two_persistent_worksteal_workers(
    tmp_path: Path,
) -> None:
    assert lane_module._CORE_WORKER_COUNT == 2
    assert lane_module._CORE_DISTRIBUTION == "worksteal"

    command = lane_module._core_worker_command(
        report=tmp_path / "pytest.xml",
        basetemp=tmp_path / "pytest",
    )

    worker_flag = command.index("-n")
    assert command[worker_flag + 1] == "2"
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
assert reloaded._CORE_WORKER_COUNT == 2
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


def test_core_node_partition_is_deterministic_complete_unique_and_balanced() -> None:
    nodes = tuple(
        f"newsroom/tests/test_{index}.py::test_{index}" for index in range(19)
    )

    first = lane_module._core_node_shards(nodes)
    second = lane_module._core_node_shards(tuple(reversed(nodes)))
    flattened = tuple(node for shard in first for node in shard)

    assert first == second
    assert len(first) == 6
    assert tuple(sorted(flattened)) == tuple(sorted(nodes))
    assert len(flattened) == len(set(flattened))
    assert max(map(len, first)) - min(map(len, first)) == 1


def test_core_file_inventory_is_recursive_and_rejects_symlinks(tmp_path: Path) -> None:
    tests = tmp_path / "newsroom" / "tests"
    nested = tests / "nested"
    nested.mkdir(parents=True)
    for index in range(4):
        target = nested / f"test_nested_{index}.py"
        target.write_text(f"def test_{index}(): pass\n", encoding="utf-8")

    assert lane_module._core_test_files(tmp_path) == tuple(
        f"newsroom/tests/nested/test_nested_{index}.py" for index in range(4)
    )

    (tests / "test_link.py").symlink_to(nested / "test_nested_0.py")
    with pytest.raises(WorkflowLaneError, match="core_test_file"):
        lane_module._core_test_files(tmp_path)


def test_core_node_inventory_semantically_matches_recursive_pytest_collection(
    tmp_path: Path,
) -> None:
    nested = tmp_path / "newsroom" / "tests" / "nested"
    nested.mkdir(parents=True)
    for index in range(4):
        (nested / f"test_nested_{index}.py").write_text(
            f"def test_nested_{index}():\n    assert True\n",
            encoding="utf-8",
        )

    assert lane_module._collect_core_node_ids(tmp_path) == tuple(
        f"newsroom/tests/nested/test_nested_{index}.py::test_nested_{index}"
        for index in range(4)
    )


def test_core_node_inventory_is_rooted_to_a_nested_workspace() -> None:
    with tempfile.TemporaryDirectory(
        prefix=".sdlc-inventory-",
        dir=REPO_ROOT,
    ) as raw_root:
        root = Path(raw_root)
        nested = root / "newsroom" / "tests" / "nested"
        nested.mkdir(parents=True)
        for index in range(4):
            (nested / f"test_nested_{index}.py").write_text(
                f"def test_nested_{index}():\n    assert True\n",
                encoding="utf-8",
            )

        assert lane_module._collect_core_node_ids(root) == tuple(
            f"newsroom/tests/nested/test_nested_{index}.py::test_nested_{index}"
            for index in range(4)
        )


def test_junit_identity_preserves_colons_inside_parameter_ids() -> None:
    assert (
        lane_module._junit_id_for_node(
            "newsroom/tests/test_example.py::TestExample::test_value[a::b]"
        )
        == "newsroom.tests.test_example.TestExample::test_value[a::b]"
    )


def test_core_shard_command_has_fixed_scheduler_and_no_caller_file_surface(
    tmp_path: Path,
) -> None:
    command = lane_module._core_worker_command(
        report=tmp_path / "report.xml",
        basetemp=tmp_path / "temp",
        test_files=("newsroom/tests/test_one.py::test_one",),
    )

    assert command.count("xdist.plugin") == 1
    assert command[command.index("-n") + 1] == "2"
    assert "--dist=worksteal" in command
    assert "--max-worker-restart=0" in command
    assert "newsroom/tests" not in command
    assert "newsroom/tests/test_one.py::test_one" in command


def test_source_fragment_and_canonical_lane_use_the_same_portable_spec() -> None:
    contract = lane_module.load_contract(REPO_ROOT)
    route = {"base_sha": "a" * 40, "head_sha": "b" * 40}

    fragment = lane_module._source_fragment_spec(contract=contract, route=route)
    canonical = lane_module._expected_spec(
        root=REPO_ROOT,
        artifact_root=REPO_ROOT / ".sdlc-run" / "core",
        contract=contract,
        route=route,
        gate_id="source-integrity",
        phase="source",
    )

    assert fragment == canonical


def test_core_shard_spec_binds_full_inventory_and_assigned_node_ids() -> None:
    contract = lane_module.load_contract(REPO_ROOT)
    inventory = tuple(
        f"newsroom/tests/test_{index}.py::test_{index}" for index in range(8)
    )
    selected = lane_module._core_node_shards(inventory)[0]

    spec = lane_module._core_shard_spec(
        contract=contract,
        shard_index=0,
        node_inventory=inventory,
        selected_node_ids=selected,
        report=REPO_ROOT / ".sdlc-run/core-fragment/pytest.xml",
        basetemp=REPO_ROOT / ".sdlc-run/core-fragment/pytest-temp",
        clustering=False,
    )

    assert spec.argv[spec.argv.index("--node-inventory-digest") + 1] == (
        lane_module.sha256_identity(list(inventory))
    )
    assert spec.argv[spec.argv.index("--selected-node-ids-digest") + 1] == (
        lane_module.sha256_identity(list(selected))
    )


def test_core_shard_child_recomputes_bound_inventory_before_pytest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nodes = tuple(f"newsroom/tests/test_{index}.py::test_{index}" for index in range(6))
    selected = lane_module._core_node_shards(nodes)[0]
    monkeypatch.setattr(
        lane_module, "_collect_core_node_ids", lambda _root, **_kwargs: nodes
    )

    with pytest.raises(WorkflowLaneError, match="core_shard_inventory"):
        lane_module.core_shard_tests(
            repo_root=tmp_path,
            report=tmp_path / "pytest.xml",
            basetemp=tmp_path / "pytest-temp",
            shard_index=0,
            node_inventory_digest="sha256:" + "0" * 64,
            selected_node_ids_digest=lane_module.sha256_identity(list(selected)),
            clustering=False,
        )


@pytest.mark.parametrize(
    ("results", "expected"),
    [
        (("PASS",) * 6, "PASS"),
        (("FAIL", *("PASS",) * 5), "FAIL"),
        (("FAIL", "BUDGET_EXCEEDED", *("PASS",) * 4), "BUDGET_EXCEEDED"),
        (("FAIL", "ENVIRONMENT_ERROR", *("PASS",) * 4), "ENVIRONMENT_ERROR"),
        (("FAIL", "EVIDENCE_MISMATCH", *("PASS",) * 4), "EVIDENCE_MISMATCH"),
    ],
)
def test_core_reducer_preserves_typed_outcome_precedence(
    results: tuple[str, ...], expected: str
) -> None:
    assert lane_module._reduced_core_outcome(results)[0] == expected


@pytest.mark.parametrize(
    ("results", "junit_outcomes", "expected"),
    [
        (("PASS",) * 6, ("PASS", "FAIL", *("PASS",) * 4), "FAIL"),
        (("PASS", "FAIL", *("PASS",) * 4), ("PASS",) * 6, "FAIL"),
        (
            ("PASS", "BUDGET_EXCEEDED", *("PASS",) * 4),
            ("PASS", "FAIL", *("PASS",) * 4),
            "BUDGET_EXCEEDED",
        ),
    ],
)
def test_core_reducer_preserves_required_skip_product_fail_and_timeout_precedence(
    results: tuple[str, ...],
    junit_outcomes: tuple[str, ...],
    expected: str,
) -> None:
    summaries = tuple({"outcome": outcome} for outcome in junit_outcomes)
    assert lane_module._reduced_core_outcome(results, summaries=summaries)[0] == (
        expected
    )


@pytest.mark.parametrize(
    ("inner_result", "elapsed_ms", "expected"),
    [
        ("PASS", 220_001, "BUDGET_EXCEEDED"),
        ("FAIL", 220_001, "BUDGET_EXCEEDED"),
        ("EVIDENCE_MISMATCH", 220_001, "EVIDENCE_MISMATCH"),
        ("ENVIRONMENT_ERROR", 220_001, "ENVIRONMENT_ERROR"),
    ],
)
def test_full_lifecycle_budget_preserves_typed_precedence(
    inner_result: str, elapsed_ms: int, expected: str
) -> None:
    assert (
        lane_module._lifecycle_result(
            inner_result,
            elapsed_ms=elapsed_ms,
            timeout_ms=220_000,
        )
        == expected
    )


def test_reducer_uses_source_shard_critical_path_plus_sequential_elapsed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    aggregate, order = _run_reducer_fixture(
        tmp_path,
        monkeypatch,
        source_elapsed_ms=60_000,
        shard_elapsed_ms=(200_000, 180_000, 170_000, 160_000, 150_000, 140_000),
        reducer_elapsed_ms=19_000,
    )

    assert order[:3] == ["start", "load-fragments", "load-source"]
    assert aggregate["gate_run"]["execution_ms"] == 219_000
    assert aggregate["gate_run"]["result"] == "PASS"
    accounting = json.loads(aggregate["gate_run"]["stdout"])
    assert accounting["source_lifecycle_ms"] == 60_000
    assert accounting["shard_lifecycle_ms"] == [
        200_000,
        180_000,
        170_000,
        160_000,
        150_000,
        140_000,
    ]
    assert accounting["reducer_lifecycle_ms"] == 19_000
    assert accounting["critical_path_ms"] == 219_000


@pytest.mark.parametrize(
    ("reducer_elapsed_ms", "expected"),
    [
        (499, ("PASS", "PASS:core-deterministic:tests", 0, 219_999)),
        (500, ("PASS", "PASS:core-deterministic:tests", 0, 220_000)),
        (
            501,
            (
                "BUDGET_EXCEEDED",
                "BUDGET_EXCEEDED:core-deterministic:tests",
                124,
                220_001,
            ),
        ),
    ],
)
def test_reducer_critical_path_boundary_emits_valid_immutable_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reducer_elapsed_ms: int,
    expected: tuple[str, str, int, int],
) -> None:
    aggregate, _order = _run_reducer_fixture(
        tmp_path,
        monkeypatch,
        source_elapsed_ms=219_500,
        shard_elapsed_ms=(1, 1, 1, 1, 1, 1),
        reducer_elapsed_ms=reducer_elapsed_ms,
    )

    gate_run = aggregate["gate_run"]
    assert isinstance(gate_run, dict)
    assert (
        gate_run["result"],
        gate_run["result_reason"],
        gate_run["returncode"],
        gate_run["execution_ms"],
    ) == expected
    assert lane_module._validate_command_run(aggregate) == aggregate


def test_slow_reducer_is_typed_budget_exceeded_from_before_input_loading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(
        WorkflowLaneError, match="BUDGET_EXCEEDED:core-deterministic:reducer"
    ):
        _run_reducer_fixture(
            tmp_path,
            monkeypatch,
            source_elapsed_ms=1,
            shard_elapsed_ms=(1, 1, 1, 1, 1, 1),
            reducer_elapsed_ms=220_001,
        )

    assert not (tmp_path / "output/core").exists()


def test_reducer_stops_after_a_load_crosses_its_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(
        lane_module.WorkflowLaneError,
        match="BUDGET_EXCEEDED:core-deterministic:reducer",
    ):
        _run_reducer_fixture(
            tmp_path,
            monkeypatch,
            source_elapsed_ms=1,
            shard_elapsed_ms=(1, 1, 1, 1, 1, 1),
            reducer_elapsed_ms=1,
            load_elapsed_ms=220_001,
        )

    assert not (tmp_path / "output/core").exists()


def test_reducer_output_time_is_bound_and_cannot_publish_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    aggregate, _order = _run_reducer_fixture(
        tmp_path,
        monkeypatch,
        source_elapsed_ms=1,
        shard_elapsed_ms=(1, 1, 1, 1, 1, 1),
        reducer_elapsed_ms=219_999,
        output_elapsed_ms=220_001,
    )

    assert aggregate["gate_run"]["result"] == "BUDGET_EXCEEDED"
    accounting = json.loads(aggregate["gate_run"]["stdout"])
    assert accounting["reducer_lifecycle_ms"] == 220_001
    persisted = json.loads(
        (
            tmp_path / "output/core/gates/core-deterministic/tests/command-run.json"
        ).read_text(encoding="utf-8")
    )
    assert persisted["gate_run"]["result"] == "BUDGET_EXCEEDED"


def test_core_fragment_identity_is_canonical_and_tamper_evident() -> None:
    body = {
        "schema_version": lane_module._CORE_FRAGMENT_SCHEMA,
        "shard_index": 0,
        "selected_node_ids": ["newsroom/tests/test_a.py::test_a"],
    }
    identity = lane_module._fragment_identity(body)

    assert identity == lane_module._fragment_identity(
        {
            "selected_node_ids": ["newsroom/tests/test_a.py::test_a"],
            "shard_index": 0,
            "schema_version": lane_module._CORE_FRAGMENT_SCHEMA,
        }
    )
    assert identity != lane_module._fragment_identity(
        {**body, "selected_node_ids": ["newsroom/tests/test_a.py::test_b"]}
    )


def test_core_fragment_binds_contract_lock_toolchain_and_exact_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract = SimpleNamespace(
        repo_root=tmp_path,
        contract_version="sdlc-v2.5",
        data=_contract_data(),
    )
    context = SimpleNamespace(
        run_id=381,
        run_attempt=2,
        job_id="core_shard",
        evaluated_sha="a" * 40,
        evaluated_tree_sha="b" * 40,
    )
    route = {
        "head_sha": context.evaluated_sha,
        "head_tree_sha": context.evaluated_tree_sha,
        "clustering_required": False,
    }
    files = tuple(f"newsroom/tests/test_{index}.py" for index in range(6))
    nodes = tuple(f"{path}::test_{index}" for index, path in enumerate(files))
    spec = SimpleNamespace(
        as_dict=lambda: {"schema_version": "test-command-spec"},
        digest="sha256:" + "c" * 64,
    )
    run = CommandRun(
        spec.digest,
        GateRunResult(
            "core-deterministic",
            "tests",
            "BUDGET_EXCEEDED",
            "BUDGET_EXCEEDED:core-deterministic:tests",
            None,
            219_950,
            "",
            "",
            False,
            False,
        ),
    )
    expected_binding = {
        "contract_version": "sdlc-v2.5",
        "contract_digest": "sha256:" + "d" * 64,
        "lockfile_digest": "sha256:" + "e" * 64,
        "python_version": "3.12.11",
        "uv_version": "0.8.0",
        "toolchain_digest": "sha256:" + "f" * 64,
    }
    monkeypatch.setattr(lane_module, "load_contract", lambda _root: contract)
    monkeypatch.setattr(lane_module, "context_from_environment", lambda _root: context)
    monkeypatch.setattr(lane_module, "_load_json", lambda *_args: route)
    monkeypatch.setattr(lane_module, "_validate_route", lambda *_args: route)
    monkeypatch.setattr(lane_module, "_validate_test_topology", lambda *_args: None)
    monkeypatch.setattr(lane_module, "_core_test_files", lambda _root: files)
    monkeypatch.setattr(
        lane_module, "_collect_core_node_ids", lambda _root, **_kwargs: nodes
    )
    monkeypatch.setattr(lane_module, "_core_shard_spec", lambda **_kwargs: spec)
    monkeypatch.setattr(lane_module, "_execute", lambda **_kwargs: run)
    monkeypatch.setattr(
        lane_module,
        "start_lane_deadline",
        lambda *_args: lane_module.LaneDeadline.start(220),
    )
    monkeypatch.setattr(lane_module, "verify_tracked_checkout", lambda *_args: None)
    monkeypatch.setattr(lane_module, "_report_summary", lambda **_kwargs: None)
    monkeypatch.setattr(
        lane_module, "_fragment_provenance", lambda **_kwargs: expected_binding
    )
    (tmp_path / "artifacts").mkdir()

    fragment = lane_module.execute_core_shard(
        repo_root=tmp_path,
        route_path="route.json",
        shard_index=0,
        artifact_root="artifacts/core-fragment",
    )

    assert {name: fragment[name] for name in expected_binding} == expected_binding
    assert fragment["file_inventory"] == list(files)
    assert fragment["node_inventory"] == list(nodes)
    assert fragment["selected_node_ids"] == list(
        lane_module._core_node_shards(nodes)[0]
    )
    assert fragment["shard_lifecycle"] == {
        "schema_version": lane_module._CORE_SHARD_LIFECYCLE_SCHEMA,
        "elapsed_ms": fragment["shard_lifecycle"]["elapsed_ms"],
        "timeout_ms": 220_000,
        "result": "BUDGET_EXCEEDED",
    }
    unsigned = dict(fragment)
    identity = unsigned.pop("fragment_identity")
    assert identity == lane_module._fragment_identity(unsigned)


def test_fragment_provenance_hashes_exact_contract_and_lockfile_bytes() -> None:
    contract = lane_module.load_contract(REPO_ROOT)
    evaluated_sha = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    provenance = lane_module._fragment_provenance(
        contract=contract,
        context=SimpleNamespace(evaluated_sha=evaluated_sha),
    )

    assert provenance["contract_digest"] == lane_module._file_digest(
        contract.source_path
    )
    assert provenance["lockfile_digest"] == lane_module.git_blob_digest(
        REPO_ROOT,
        evaluated_sha,
        "uv.lock",
    )


def test_fragment_summary_preserves_the_canonical_optional_skip_policy(
    tmp_path: Path,
) -> None:
    optional_test_id = lane_module._OPTIONAL_CORE_TEST_IDS[0]
    classname, name = optional_test_id.split("::", 1)
    optional_node_id = f"{classname.replace('.', '/')}.py::{name}"
    assert lane_module._core_shard_optional_test_ids(
        ("newsroom/tests/test_required.py::test_required", optional_node_id)
    ) == (optional_test_id,)
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    report = artifact / "pytest.xml"
    report.write_text(
        (
            '<testsuite tests="1" failures="0" errors="0" skipped="1">'
            f'<testcase classname="{classname}" name="{name}" time="0.001">'
            '<skipped message="service disabled" />'
            "</testcase></testsuite>"
        ),
        encoding="utf-8",
    )

    summary = lane_module._core_fragment_report_summary(
        repo_root=tmp_path,
        artifact_root=artifact,
        report=report,
        result="PASS",
        optional_test_ids=(optional_test_id,),
    )

    assert summary is not None
    assert summary.outcome == "PASS"
    assert summary.skip_count == 1
    assert summary.required_skip_count == 0


def test_collection_time_tracked_mutation_prevents_fragment_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_verify = lane_module.verify_tracked_checkout
    _patch_core_shard_execution(
        tmp_path,
        monkeypatch,
        result="PASS",
        report_payload=_passing_report(),
    )
    tracked, head = _initialise_tracked_file(tmp_path)
    context = SimpleNamespace(
        run_id=381,
        run_attempt=2,
        job_id="core_shard",
        evaluated_sha=head,
        evaluated_tree_sha="b" * 40,
    )
    route = {
        "head_sha": head,
        "head_tree_sha": context.evaluated_tree_sha,
        "clustering_required": False,
    }
    nodes = tuple(f"newsroom/tests/test_{index}.py::test_{index}" for index in range(6))

    def collect(_root: Path, **_kwargs: object) -> tuple[str, ...]:
        tracked.write_text("mutated during collection\n", encoding="utf-8")
        return nodes

    monkeypatch.setattr(lane_module, "context_from_environment", lambda _root: context)
    monkeypatch.setattr(lane_module, "_load_json", lambda *_args: route)
    monkeypatch.setattr(lane_module, "_validate_route", lambda *_args: route)
    monkeypatch.setattr(lane_module, "_collect_core_node_ids", collect)
    monkeypatch.setattr(lane_module, "verify_tracked_checkout", real_verify)

    with pytest.raises(lane_module.EvidenceError, match="tracked_checkout_dirty"):
        lane_module.execute_core_shard(
            repo_root=tmp_path,
            route_path="route.json",
            shard_index=0,
            artifact_root="artifacts/core-fragment",
        )

    assert not (tmp_path / "artifacts/core-fragment/fragment.json").exists()


def test_test_time_tracked_mutation_prevents_fragment_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_verify = lane_module.verify_tracked_checkout
    _patch_core_shard_execution(
        tmp_path,
        monkeypatch,
        result="PASS",
        report_payload=_passing_report(),
    )
    tracked, head = _initialise_tracked_file(tmp_path)
    context = SimpleNamespace(
        run_id=381,
        run_attempt=2,
        job_id="core_shard",
        evaluated_sha=head,
        evaluated_tree_sha="b" * 40,
    )
    route = {
        "head_sha": head,
        "head_tree_sha": context.evaluated_tree_sha,
        "clustering_required": False,
    }
    execute = lane_module._execute

    def mutate(**kwargs: object) -> CommandRun:
        run = execute(**kwargs)
        tracked.write_text("mutated during pytest\n", encoding="utf-8")
        return run

    monkeypatch.setattr(lane_module, "context_from_environment", lambda _root: context)
    monkeypatch.setattr(lane_module, "_load_json", lambda *_args: route)
    monkeypatch.setattr(lane_module, "_validate_route", lambda *_args: route)
    monkeypatch.setattr(lane_module, "_execute", mutate)
    monkeypatch.setattr(lane_module, "verify_tracked_checkout", real_verify)

    with pytest.raises(lane_module.EvidenceError, match="tracked_checkout_dirty"):
        lane_module.execute_core_shard(
            repo_root=tmp_path,
            route_path="route.json",
            shard_index=0,
            artifact_root="artifacts/core-fragment",
        )

    assert not (tmp_path / "artifacts/core-fragment/fragment.json").exists()


def test_collection_subprocess_timeout_is_typed_and_publishes_no_fragment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collect = lane_module._collect_core_node_ids
    _patch_core_shard_execution(
        tmp_path,
        monkeypatch,
        result="PASS",
        report_payload=_passing_report(),
    )
    deadline = lane_module.LaneDeadline.start(220)
    observed: list[float | None] = []

    def timeout(*args: object, **kwargs: object) -> object:
        observed.append(kwargs.get("timeout"))  # type: ignore[arg-type]
        raise subprocess.TimeoutExpired(args[0], kwargs.get("timeout", 0))

    monkeypatch.setattr(lane_module, "start_lane_deadline", lambda *_args: deadline)
    monkeypatch.setattr(lane_module, "_collect_core_node_ids", collect)
    monkeypatch.setattr(lane_module.subprocess, "run", timeout)

    with pytest.raises(
        lane_module.WorkflowLaneError,
        match="BUDGET_EXCEEDED:core-deterministic:collection",
    ):
        lane_module.execute_core_shard(
            repo_root=tmp_path,
            route_path="route.json",
            shard_index=0,
            artifact_root="artifacts/core-fragment",
        )

    assert observed and 0 < observed[0] <= 220
    assert not (tmp_path / "artifacts/core-fragment/fragment.json").exists()


def test_slow_collection_is_charged_to_the_shard_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_core_shard_execution(
        tmp_path,
        monkeypatch,
        result="PASS",
        report_payload=_passing_report(),
    )
    deadline = lane_module.LaneDeadline.start(220)
    elapsed = {"value": 1}
    order: list[str] = []
    collect = lane_module._collect_core_node_ids
    execute = lane_module._execute

    def start(*_args: object) -> object:
        order.append("start")
        return deadline

    def slow_collection(root: Path, **_kwargs: object) -> tuple[str, ...]:
        order.append("collect")
        result = collect(root)
        elapsed["value"] = 220_001
        return result

    def observed_execute(**kwargs: object) -> CommandRun:
        order.append("execute")
        assert kwargs["deadline"] is deadline
        return execute(**kwargs)

    monkeypatch.setattr(lane_module, "start_lane_deadline", start)
    monkeypatch.setattr(lane_module, "_collect_core_node_ids", slow_collection)
    monkeypatch.setattr(lane_module, "_execute", observed_execute)
    monkeypatch.setattr(
        lane_module,
        "_deadline_elapsed_ms",
        lambda observed: elapsed["value"] if observed is deadline else 0,
    )

    with pytest.raises(
        WorkflowLaneError, match="BUDGET_EXCEEDED:core-deterministic:collection"
    ):
        lane_module.execute_core_shard(
            repo_root=tmp_path,
            route_path="route.json",
            shard_index=0,
            artifact_root="artifacts/core-fragment",
        )

    assert order == ["start", "collect"]
    assert not (tmp_path / "artifacts/core-fragment/fragment.json").exists()


def test_fragment_finalisation_timeout_overrides_a_product_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_core_shard_execution(
        tmp_path,
        monkeypatch,
        result="PASS",
        report_payload=_passing_report(),
    )
    elapsed = {"value": 219_999}
    provenance = lane_module._fragment_provenance

    def slow_finalisation(**kwargs: object) -> dict[str, str]:
        value = provenance(**kwargs)
        elapsed["value"] = 220_001
        return value

    monkeypatch.setattr(lane_module, "_fragment_provenance", slow_finalisation)
    monkeypatch.setattr(
        lane_module, "_deadline_elapsed_ms", lambda _deadline: elapsed["value"]
    )

    fragment = lane_module.execute_core_shard(
        repo_root=tmp_path,
        route_path="route.json",
        shard_index=0,
        artifact_root="artifacts/core-fragment",
    )

    assert fragment["command_run"]["gate_run"]["result"] == "PASS"
    assert fragment["shard_lifecycle"] == {
        "schema_version": lane_module._CORE_SHARD_LIFECYCLE_SCHEMA,
        "elapsed_ms": 220_001,
        "timeout_ms": 220_000,
        "result": "BUDGET_EXCEEDED",
    }
    assert fragment["junit_summary"] is None
    assert fragment["report_digest"] is None


def test_fragment_durable_write_time_cannot_publish_a_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_core_shard_execution(
        tmp_path,
        monkeypatch,
        result="PASS",
        report_payload=_passing_report(),
    )
    elapsed = {"value": 219_999}
    private_write = lane_module._private_write

    def delayed_write(path: Path, value: object) -> None:
        private_write(path, value)
        if "fragment" in path.name:
            elapsed["value"] = 220_001

    monkeypatch.setattr(lane_module, "_private_write", delayed_write)
    monkeypatch.setattr(
        lane_module, "_deadline_elapsed_ms", lambda _deadline: elapsed["value"]
    )

    fragment = lane_module.execute_core_shard(
        repo_root=tmp_path,
        route_path="route.json",
        shard_index=0,
        artifact_root="artifacts/core-fragment",
    )

    assert fragment["shard_lifecycle"]["result"] == "BUDGET_EXCEEDED"
    persisted = json.loads(
        (tmp_path / "artifacts/core-fragment/fragment.json").read_text(encoding="utf-8")
    )
    assert persisted["shard_lifecycle"]["result"] == "BUDGET_EXCEEDED"
    assert not (tmp_path / "artifacts/core-fragment/pytest.xml").exists()


def test_source_callback_mutation_prevents_fragment_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_verify = lane_module.verify_tracked_checkout
    _patch_source_execution(tmp_path, monkeypatch)
    tracked, head = _initialise_tracked_file(tmp_path)
    context = SimpleNamespace(
        run_id=381,
        run_attempt=2,
        job_id="source",
        evaluated_sha=head,
        evaluated_tree_sha="b" * 40,
    )
    route = {
        "head_sha": head,
        "head_tree_sha": context.evaluated_tree_sha,
        "clustering_required": False,
    }
    execute = lane_module._execute

    def mutate(**kwargs: object) -> CommandRun:
        run = execute(**kwargs)
        tracked.write_text("mutated during source execution\n", encoding="utf-8")
        return run

    monkeypatch.setattr(lane_module, "context_from_environment", lambda _root: context)
    monkeypatch.setattr(lane_module, "_load_json", lambda *_args: route)
    monkeypatch.setattr(lane_module, "_validate_route", lambda *_args: route)
    monkeypatch.setattr(lane_module, "_execute", mutate)
    monkeypatch.setattr(lane_module, "verify_tracked_checkout", real_verify)

    with pytest.raises(lane_module.EvidenceError, match="tracked_checkout_dirty"):
        lane_module.execute_source_fragment(
            repo_root=tmp_path,
            route_path="route.json",
            artifact_root="artifacts/source-fragment",
        )

    assert not (tmp_path / "artifacts/source-fragment/source-fragment.json").exists()


def test_source_lifecycle_starts_before_artifact_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_source_execution(tmp_path, monkeypatch)
    deadline = lane_module.LaneDeadline.start(220)
    prepare = lane_module._prepare_artifact_root
    execute = lane_module._execute
    order: list[str] = []

    def start(*_args: object) -> object:
        order.append("start")
        return deadline

    def observed_prepare(*args: object, **kwargs: object) -> Path:
        order.append("prepare")
        return prepare(*args, **kwargs)  # type: ignore[arg-type]

    def observed_execute(**kwargs: object) -> CommandRun:
        order.append("execute")
        assert kwargs["deadline"] is deadline
        return execute(**kwargs)

    monkeypatch.setattr(lane_module, "start_lane_deadline", start)
    monkeypatch.setattr(lane_module, "_prepare_artifact_root", observed_prepare)
    monkeypatch.setattr(lane_module, "_execute", observed_execute)

    lane_module.execute_source_fragment(
        repo_root=tmp_path,
        route_path="route.json",
        artifact_root="artifacts/source-fragment",
    )

    assert order[:3] == ["start", "prepare", "execute"]


def test_source_output_time_is_bound_and_cannot_publish_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_source_execution(tmp_path, monkeypatch)
    elapsed = {"value": 219_999}
    private_write = lane_module._private_write

    def delayed_write(path: Path, value: object) -> None:
        private_write(path, value)
        if "source-fragment" in path.name:
            elapsed["value"] = 220_001

    monkeypatch.setattr(lane_module, "_private_write", delayed_write)
    monkeypatch.setattr(
        lane_module, "_deadline_elapsed_ms", lambda _deadline: elapsed["value"]
    )

    fragment = lane_module.execute_source_fragment(
        repo_root=tmp_path,
        route_path="route.json",
        artifact_root="artifacts/source-fragment",
    )

    assert fragment["source_lifecycle"] == {
        "schema_version": lane_module._SOURCE_LIFECYCLE_SCHEMA,
        "elapsed_ms": 220_001,
        "timeout_ms": 220_000,
        "result": "BUDGET_EXCEEDED",
    }
    persisted = json.loads(
        (tmp_path / "artifacts/source-fragment/source-fragment.json").read_text(
            encoding="utf-8"
        )
    )
    assert persisted["source_lifecycle"]["result"] == "BUDGET_EXCEEDED"


def test_true_shard_timeout_discards_incomplete_junit_and_stays_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_core_shard_execution(
        tmp_path,
        monkeypatch,
        result="BUDGET_EXCEEDED",
        report_payload="<testsuite>",
    )

    fragment = lane_module.execute_core_shard(
        repo_root=tmp_path,
        route_path="route.json",
        shard_index=0,
        artifact_root="artifacts/core-fragment",
    )

    assert fragment["command_run"]["gate_run"]["result"] == "BUDGET_EXCEEDED"
    assert fragment["junit_summary"] is None
    assert fragment["report_digest"] is None
    assert not (tmp_path / "artifacts/core-fragment/pytest.xml").exists()


def test_true_shard_timeout_discards_well_formed_partial_junit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_core_shard_execution(
        tmp_path,
        monkeypatch,
        result="BUDGET_EXCEEDED",
        report_payload=(
            '<testsuite tests="1" failures="0" errors="0" skipped="0">'
            '<testcase classname="newsroom.tests.test_0" name="test_0" '
            'time="0.001" />'
            "</testsuite>"
        ),
    )

    fragment = lane_module.execute_core_shard(
        repo_root=tmp_path,
        route_path="route.json",
        shard_index=0,
        artifact_root="artifacts/core-fragment",
    )

    assert fragment["command_run"]["gate_run"]["result"] == "BUDGET_EXCEEDED"
    assert fragment["junit_summary"] is None
    assert fragment["report_digest"] is None
    assert not (tmp_path / "artifacts/core-fragment/pytest.xml").exists()


def test_product_result_without_junit_fails_closed_as_evidence_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_core_shard_execution(
        tmp_path,
        monkeypatch,
        result="FAIL",
        report_payload=None,
    )

    with pytest.raises(WorkflowLaneError, match="core_fragment_report_required"):
        lane_module.execute_core_shard(
            repo_root=tmp_path,
            route_path="route.json",
            shard_index=0,
            artifact_root="artifacts/core-fragment",
        )


def test_fragment_loader_is_input_order_deterministic_and_validates_bindings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fragments, contract, context, route = _write_fragment_set(
        tmp_path,
        monkeypatch,
        directory_order=(5, 4, 3, 2, 1, 0),
    )

    loaded = lane_module._load_core_fragments(
        root=tmp_path,
        fragment_root=fragments,
        contract=contract,  # type: ignore[arg-type]
        context=context,
        route=route,
    )

    assert tuple(fragment["shard_index"] for fragment, _report in loaded) == (
        0,
        1,
        2,
        3,
        4,
        5,
    )


@pytest.mark.parametrize(
    ("field", "replacement", "reason", "refresh_identity"),
    [
        ("fragment_identity", "sha256:" + "0" * 64, "core_fragment_identity", False),
        ("evaluated_sha", "1" * 40, "core_fragment_provenance", True),
        ("evaluated_tree_sha", "2" * 40, "core_fragment_provenance", True),
        ("route_digest", "sha256:" + "3" * 64, "core_fragment_provenance", True),
        ("contract_digest", "sha256:" + "4" * 64, "core_fragment_provenance", True),
        (
            "file_inventory",
            ["newsroom/tests/test_unexpected.py"],
            "core_fragment_provenance",
            True,
        ),
        (
            "selected_node_ids",
            ["newsroom/tests/test_unexpected.py::test_unexpected"],
            "core_fragment_provenance",
            True,
        ),
        (
            "command_spec",
            {"schema_version": "tampered-command-spec"},
            "core_fragment_spec",
            True,
        ),
        (
            "shard_lifecycle",
            {
                "schema_version": "newsroom.sdlc.core-shard-lifecycle.v1",
                "elapsed_ms": 220_001,
                "timeout_ms": 220_000,
                "result": "PASS",
            },
            "core_fragment_lifecycle",
            True,
        ),
    ],
)
def test_fragment_loader_rejects_tamper_and_wrong_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    replacement: object,
    reason: str,
    refresh_identity: bool,
) -> None:
    fragments, contract, context, route = _write_fragment_set(tmp_path, monkeypatch)
    _rewrite_fragment(
        fragments / "input-0" / "fragment.json",
        {field: replacement},
        refresh_identity=refresh_identity,
    )

    with pytest.raises(WorkflowLaneError, match=reason):
        lane_module._load_core_fragments(
            root=tmp_path,
            fragment_root=fragments,
            contract=contract,  # type: ignore[arg-type]
            context=context,
            route=route,
        )


def test_fragment_loader_rejects_wrong_gate_run_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fragments, contract, context, route = _write_fragment_set(tmp_path, monkeypatch)
    path = fragments / "input-0" / "fragment.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    command_run = value["command_run"]
    assert isinstance(command_run, dict)
    gate_run = command_run["gate_run"]
    assert isinstance(gate_run, dict)
    gate_run.update(
        {
            "gate_id": "source-integrity",
            "phase": "source",
            "result_reason": "BUDGET_EXCEEDED:source-integrity:source",
        }
    )
    _rewrite_fragment(path, {"command_run": command_run})

    with pytest.raises(WorkflowLaneError, match="core_fragment_run_identity"):
        lane_module._load_core_fragments(
            root=tmp_path,
            fragment_root=fragments,
            contract=contract,  # type: ignore[arg-type]
            context=context,
            route=route,
        )


def test_fragment_loader_requires_junit_for_product_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fragments, contract, context, route = _write_fragment_set(tmp_path, monkeypatch)
    path = fragments / "input-0" / "fragment.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    command_run = value["command_run"]
    assert isinstance(command_run, dict)
    gate_run = command_run["gate_run"]
    assert isinstance(gate_run, dict)
    gate_run.update(
        {
            "result": "FAIL",
            "result_reason": "FAIL:core-deterministic:tests:exit=1",
            "returncode": 1,
        }
    )
    lifecycle = value["shard_lifecycle"]
    assert isinstance(lifecycle, dict)
    lifecycle["result"] = "FAIL"
    _rewrite_fragment(
        path,
        {"command_run": command_run, "shard_lifecycle": lifecycle},
    )

    with pytest.raises(WorkflowLaneError, match="core_fragment_report_required"):
        lane_module._load_core_fragments(
            root=tmp_path,
            fragment_root=fragments,
            contract=contract,  # type: ignore[arg-type]
            context=context,
            route=route,
        )


def test_fragment_loader_rejects_tampered_junit_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fragments, contract, context, route = _write_fragment_set(tmp_path, monkeypatch)
    path = fragments / "input-0" / "fragment.json"
    _rewrite_fragment_as_pass(path)
    _write_bound_junit(path)
    report = path.with_name("pytest.xml")
    report.write_text(
        report.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    with pytest.raises(WorkflowLaneError, match="core_fragment_report_digest"):
        lane_module._load_core_fragments(
            root=tmp_path,
            fragment_root=fragments,
            contract=contract,  # type: ignore[arg-type]
            context=context,
            route=route,
        )


def test_reducer_rejects_self_consistent_junit_outside_assigned_union(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fragments, contract, context, route = _write_fragment_set(tmp_path, monkeypatch)
    for index in range(6):
        path = fragments / f"input-{index}" / "fragment.json"
        _rewrite_fragment_as_pass(path)
        _write_bound_junit(path)
    _write_bound_junit(
        fragments / "input-0" / "fragment.json",
        node_id="newsroom/tests/test_unexpected.py::test_unexpected",
    )
    source_run = CommandRun(
        "sha256:" + "9" * 64,
        GateRunResult(
            "source-integrity",
            "source",
            "PASS",
            "PASS:source-integrity:source",
            0,
            1,
            "",
            "",
            False,
            False,
        ),
    )
    source = {
        "command_run": source_run.as_dict(),
        "source_lifecycle": {
            "schema_version": lane_module._SOURCE_LIFECYCLE_SCHEMA,
            "elapsed_ms": 1,
            "timeout_ms": 220_000,
            "result": "PASS",
        },
    }
    source_root = tmp_path / "source"
    source_root.mkdir()
    (tmp_path / "output").mkdir()
    monkeypatch.setattr(
        lane_module,
        "_context_route",
        lambda **_kwargs: (contract, context, route),
    )
    monkeypatch.setattr(
        lane_module,
        "start_lane_deadline",
        lambda *_args: lane_module.LaneDeadline.start(220),
    )
    monkeypatch.setattr(
        lane_module,
        "_existing_artifact_root",
        lambda _root, value: fragments if str(value) == "fragments" else source_root,
    )
    monkeypatch.setattr(lane_module, "_load_source_fragment", lambda **_kwargs: source)
    monkeypatch.setattr(
        lane_module,
        "_expected_spec",
        lambda **_kwargs: SimpleNamespace(digest=source_run.command_spec_digest),
    )
    with pytest.raises(WorkflowLaneError, match="core_fragment_report_inventory"):
        lane_module.reduce_core_lane(
            repo_root=tmp_path,
            route_path="route.json",
            fragment_root="fragments",
            source_root="source",
            artifact_root="output/core",
        )


def test_reducer_validates_available_junit_when_another_shard_timed_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fragments, contract, context, route = _write_fragment_set(tmp_path, monkeypatch)
    path = fragments / "input-0" / "fragment.json"
    _rewrite_fragment_as_pass(path)
    _write_bound_junit(
        path,
        node_id="newsroom/tests/test_unexpected.py::test_unexpected",
    )
    source_run = CommandRun(
        "sha256:" + "9" * 64,
        GateRunResult(
            "source-integrity",
            "source",
            "PASS",
            "PASS:source-integrity:source",
            0,
            1,
            "",
            "",
            False,
            False,
        ),
    )
    source_root = tmp_path / "source"
    source_root.mkdir()
    (tmp_path / "output").mkdir()
    monkeypatch.setattr(
        lane_module,
        "_context_route",
        lambda **_kwargs: (contract, context, route),
    )
    monkeypatch.setattr(
        lane_module,
        "start_lane_deadline",
        lambda *_args: lane_module.LaneDeadline.start(220),
    )
    monkeypatch.setattr(
        lane_module,
        "_existing_artifact_root",
        lambda _root, value: fragments if str(value) == "fragments" else source_root,
    )
    monkeypatch.setattr(
        lane_module,
        "_load_source_fragment",
        lambda **_kwargs: {
            "command_run": source_run.as_dict(),
            "source_lifecycle": {
                "schema_version": lane_module._SOURCE_LIFECYCLE_SCHEMA,
                "elapsed_ms": 1,
                "timeout_ms": 220_000,
                "result": "PASS",
            },
            "fragment_identity": "sha256:" + "8" * 64,
        },
    )
    monkeypatch.setattr(
        lane_module,
        "_expected_spec",
        lambda **_kwargs: SimpleNamespace(digest=source_run.command_spec_digest),
    )
    monkeypatch.setattr(lane_module, "artifact_name", lambda _context: "artifact")

    with pytest.raises(WorkflowLaneError, match="core_fragment_report_inventory"):
        lane_module.reduce_core_lane(
            repo_root=tmp_path,
            route_path="route.json",
            fragment_root="fragments",
            source_root="source",
            artifact_root="output/core",
        )


def test_fragment_loader_rejects_duplicate_and_noncanonical_fragments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fragments, contract, context, route = _write_fragment_set(tmp_path, monkeypatch)
    _rewrite_fragment(fragments / "input-1" / "fragment.json", {"shard_index": 0})
    with pytest.raises(WorkflowLaneError, match="core_fragment_duplicate"):
        lane_module._load_core_fragments(
            root=tmp_path,
            fragment_root=fragments,
            contract=contract,  # type: ignore[arg-type]
            context=context,
            route=route,
        )

    fragments, contract, context, route = _write_fragment_set(
        tmp_path / "noncanonical", monkeypatch
    )
    path = fragments / "input-0" / "fragment.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(WorkflowLaneError, match="input_canonical"):
        lane_module._load_core_fragments(
            root=tmp_path / "noncanonical",
            fragment_root=fragments,
            contract=contract,  # type: ignore[arg-type]
            context=context,
            route=route,
        )


def test_reducer_rejects_missing_or_extra_fragment_count() -> None:
    with pytest.raises(WorkflowLaneError, match="core_fragment_count"):
        lane_module._reduced_core_outcome(("PASS",) * 5)
    with pytest.raises(WorkflowLaneError, match="core_fragment_count"):
        lane_module._reduced_core_outcome(("PASS",) * 7)


def test_fragment_loader_rejects_missing_and_extra_artifact_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fragments = tmp_path / "fragments"
    fragments.mkdir()
    for index in range(6):
        directory = fragments / f"shard-{index}"
        directory.mkdir()
        (directory / "fragment.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        lane_module,
        "_core_test_files",
        lambda _root: tuple(f"newsroom/tests/test_{index}.py" for index in range(6)),
    )
    monkeypatch.setattr(
        lane_module,
        "_collect_core_node_ids",
        lambda _root, **_kwargs: tuple(
            f"newsroom/tests/test_{index}.py::test_{index}" for index in range(6)
        ),
    )

    (fragments / "shard-5" / "fragment.json").unlink()
    with pytest.raises(WorkflowLaneError, match="core_fragment_count"):
        lane_module._load_core_fragments(
            root=tmp_path,
            fragment_root=fragments,
            contract=None,  # type: ignore[arg-type]
            context=None,
            route={},
        )

    (fragments / "shard-5" / "fragment.json").write_text("{}\n", encoding="utf-8")
    (fragments / "unexpected").write_text("extra", encoding="utf-8")
    with pytest.raises(WorkflowLaneError, match="core_fragment_count"):
        lane_module._load_core_fragments(
            root=tmp_path,
            fragment_root=fragments,
            contract=None,  # type: ignore[arg-type]
            context=None,
            route={},
        )
