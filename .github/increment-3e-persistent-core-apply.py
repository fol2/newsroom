from __future__ import annotations

from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(
            f"expected one exact replacement in {path}: {old[:100]!r}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_span(
    path: Path,
    start_marker: str,
    end_marker: str,
    replacement: str,
) -> None:
    text = path.read_text(encoding="utf-8")
    start = text.find(start_marker)
    end = text.find(end_marker, start + len(start_marker))
    if start < 0 or end < 0 or text.find(start_marker, start + 1) >= 0:
        raise SystemExit(
            f"unable to select one exact span in {path}: {start_marker!r}"
        )
    path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")


pyproject = Path("pyproject.toml")
replace_once(
    pyproject,
    '    "pytest-cov>=4.0",\n]',
    '    "pytest-cov>=4.0",\n    "pytest-xdist==3.8.0",\n]',
)
replace_once(
    pyproject,
    '  "pytest-cov>=4.0",\n]',
    '  "pytest-cov>=4.0",\n  "pytest-xdist==3.8.0",\n]',
)

lane = Path("scripts/sdlc/workflow_lane.py")
replace_once(
    lane,
    '_CORE_SHARD_COUNT = 16\n_CORE_WORKER_COUNT = 5\n',
    '_CORE_WORKER_COUNT = 4\n_CORE_DISTRIBUTION = "loadfile"\n',
)
replace_span(
    lane,
    "def _core_test_files(",
    "def _run_pytest_shard(",
    '''def _core_test_files(root: Path) -> tuple[str, ...]:
    test_root = root / "newsroom" / "tests"
    if test_root.is_symlink() or not test_root.is_dir():
        raise WorkflowLaneError("core_test_root")
    values: list[str] = []
    for path in sorted(test_root.rglob("test_*.py")):
        if path.is_symlink() or not path.is_file():
            raise WorkflowLaneError("core_test_file")
        values.append(path.relative_to(root).as_posix())
    if len(values) < _CORE_WORKER_COUNT:
        raise WorkflowLaneError("core_test_count")
    return tuple(values)


def _core_worker_command(
    *,
    test_files: Sequence[str],
    report: Path,
    basetemp: Path,
) -> tuple[str, ...]:
    if (
        not isinstance(test_files, tuple)
        or len(test_files) < _CORE_WORKER_COUNT
        or tuple(sorted(set(test_files))) != test_files
    ):
        raise WorkflowLaneError("core_test_topology")
    return (
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
        str(_CORE_WORKER_COUNT),
        f"--dist={_CORE_DISTRIBUTION}",
        "--max-worker-restart=0",
        *test_files,
        f"--basetemp={basetemp}",
        f"--junitxml={report}",
    )


''',
)
replace_span(
    lane,
    "def _merge_core_junit_reports(",
    "def _merge_service_junit_reports(",
    "",
)
replace_span(
    lane,
    "def _run_core_pytest_shards(",
    "def core_tests(",
    '''def _run_core_pytest_workers(*, root: Path, report: Path) -> int:
    if report.exists() or report.is_symlink() or not report.parent.is_dir():
        raise WorkflowLaneError("report_exists")
    test_files = _core_test_files(root)
    with tempfile.TemporaryDirectory(prefix="newsroom-core-workers-") as raw_temp:
        command = _core_worker_command(
            test_files=test_files,
            report=report,
            basetemp=Path(raw_temp) / "pytest",
        )
        try:
            completed = subprocess.run(command, cwd=root, check=False)
        except OSError as exc:
            raise WorkflowLaneError("core_worker_process") from exc
    return completed.returncode


''',
)
replace_once(
    lane,
    "    code = _run_core_pytest_shards(root=root, report=report_path)\n",
    "    code = _run_core_pytest_workers(root=root, report=report_path)\n",
)
replace_once(
    lane,
    '''    shard_count = (
        _CORE_SHARD_COUNT
        if lane_id == "core"
        else _SERVICE_SHARD_COUNT
    )
''',
    "",
)
replace_once(
    lane,
    '''        if gate_id in {
            "core-deterministic",
            "service-neo4j",
        }:
            _discard_incomplete_shard_reports(report=report, shard_count=shard_count)
''',
    '''        if gate_id == "service-neo4j":
            _discard_incomplete_shard_reports(
                report=report,
                shard_count=_SERVICE_SHARD_COUNT,
            )
''',
)

tests = Path("newsroom/tests/test_sdlc_workflow_lane.py")
text = tests.read_text(encoding="utf-8")
text = text.replace(
    "test_core_test_command_runs_fixed_shards_and_conditional_clustering",
    "test_core_test_command_runs_persistent_workers_and_conditional_clustering",
    1,
)
if text.count("_run_core_pytest_shards") != 2:
    raise SystemExit("unexpected legacy core runner references")
text = text.replace("_run_core_pytest_shards", "_run_core_pytest_workers")
text = text.replace("shard_calls", "worker_calls")
tests.write_text(text, encoding="utf-8")
replace_span(
    tests,
    "def test_core_test_shards_are_fixed_deterministic_and_complete(",
    "def test_service_shards_cover_exact_inventory_deterministically(",
    '''def test_core_test_inventory_is_sorted_complete_and_rejects_symlinks(
    tmp_path: Path,
) -> None:
    test_root = tmp_path / "newsroom/tests"
    test_root.mkdir(parents=True)
    expected: list[str] = []
    for index in range(lane_module._CORE_WORKER_COUNT):
        path = test_root / f"test_{index}.py"
        path.write_text("def test_ok(): assert True\n", encoding="utf-8")
        expected.append(path.relative_to(tmp_path).as_posix())

    assert lane_module._core_test_files(tmp_path) == tuple(sorted(expected))

    if os.name != "posix":
        pytest.skip("symlink evidence is POSIX-specific")
    target = test_root / "outside.py"
    target.write_text("def test_outside(): assert True\n", encoding="utf-8")
    (test_root / "test_link.py").symlink_to(target)
    with pytest.raises(WorkflowLaneError, match="core_test_file"):
        lane_module._core_test_files(tmp_path)


def test_core_worker_command_is_pinned_persistent_and_file_scoped(
    tmp_path: Path,
) -> None:
    report = tmp_path / "report.xml"
    basetemp = tmp_path / "basetemp"
    files = tuple(
        f"newsroom/tests/test_{index}.py"
        for index in range(lane_module._CORE_WORKER_COUNT)
    )
    command = lane_module._core_worker_command(
        test_files=files,
        report=report,
        basetemp=basetemp,
    )

    assert lane_module._CORE_WORKER_COUNT == 4
    assert lane_module._CORE_DISTRIBUTION == "loadfile"
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
        "4",
        "--dist=loadfile",
        "--max-worker-restart=0",
    )
    assert command[13 : 13 + len(files)] == files
    assert command[-2:] == (
        f"--basetemp={basetemp}",
        f"--junitxml={report}",
    )


def test_persistent_core_dependency_is_exactly_pinned() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert pyproject.count('"pytest-xdist==3.8.0"') == 2


''',
)
replace_span(
    tests,
    "def test_core_shard_reports_merge_to_one_exact_private_report(",
    "def test_parallel_service_runner_merges_all_shards_and_propagates_failure(",
    '''def test_persistent_core_runner_invokes_one_session_and_propagates_failure(
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
    assert "--dist=loadfile" in command
    assert "--max-worker-restart=0" in command


''',
)
replace_span(
    tests,
    "def test_finalizer_discards_interrupted_core_shard_reports(",
    "def test_shard_report_cleanup_rejects_unexpected_identity(",
    '''def test_finalizer_discards_interrupted_service_shard_reports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract(tmp_path)
    route = _route(service=True)
    artifact = tmp_path / "artifact-interrupted-shards"
    run_path = artifact / "gates/service-neo4j/tests/command-run.json"
    report = run_path.parent / "reports/pytest.xml"
    report.parent.mkdir(parents=True)
    partials = tuple(
        report.with_name(f"pytest-shard-{index:02d}.xml")
        for index in range(lane_module._SERVICE_SHARD_COUNT)
    )
    for index, path in enumerate(partials):
        path.write_text(_junit_case(f"partial_{index}"), encoding="utf-8")
    context = SimpleNamespace(runner_environment="github-hosted")
    command = _run(
        "service-neo4j",
        "tests",
        "BUDGET_EXCEEDED",
    ).as_dict()
    monkeypatch.setattr(
        lane_module, "_context_route", lambda **_kwargs: (contract, context, route)
    )
    monkeypatch.setattr(lane_module, "_existing_artifact_root", lambda *_args: artifact)
    monkeypatch.setattr(
        lane_module, "_validate_route", lambda _contract, value: route
    )
    monkeypatch.setattr(
        lane_module,
        "_load_json",
        lambda _root, value: route if Path(value).name == "route.json" else command,
    )
    monkeypatch.setattr(
        lane_module,
        "_layout",
        lambda *_args: (("service-neo4j", "tests", run_path, report),),
    )
    monkeypatch.setattr(
        lane_module,
        "_expected_spec",
        lambda **_kwargs: SimpleNamespace(digest=command["command_spec_digest"]),
    )
    monkeypatch.setattr(
        lane_module,
        "_evidence",
        lambda **_kwargs: {
            "schema_version": "newsroom.sdlc.evidence.v1",
            "result": "BUDGET_EXCEEDED",
        },
    )

    def create_envelope(**_kwargs):
        assert not tuple(report.parent.glob("pytest-shard-*.xml"))
        return SimpleNamespace(
            envelope_identity="sha256:" + "6" * 64,
            as_dict=lambda: {"schema_version": "test-envelope"},
        )

    monkeypatch.setattr(lane_module, "create_envelope", create_envelope)
    monkeypatch.setattr(lane_module, "validate_envelope", lambda _value: None)
    monkeypatch.setattr(lane_module, "artifact_name", lambda _context: "artifact")

    output = lane_module.finalize_lane(
        repo_root=tmp_path,
        route_path="route.json",
        lane_id="service",
        artifact_root="artifact-interrupted-shards",
    )

    assert output.gate_results == (
        ("service-neo4j", "tests", "BUDGET_EXCEEDED"),
    )
    assert all(not path.exists() for path in partials)


''',
)
text = tests.read_text(encoding="utf-8")
cleanup_start = text.index(
    "def test_shard_report_cleanup_rejects_unexpected_identity("
)
cleanup_end = text.index(
    "def test_failed_finalization_removes_derived_partial_files(",
    cleanup_start,
)
cleanup = text[cleanup_start:cleanup_end]
if cleanup.count("lane_module._CORE_SHARD_COUNT") != 2:
    raise SystemExit("unexpected cleanup shard-count references")
cleanup = cleanup.replace(
    "lane_module._CORE_SHARD_COUNT",
    "lane_module._SERVICE_SHARD_COUNT",
)
text = text[:cleanup_start] + cleanup + text[cleanup_end:]
if "stat." not in text:
    text = text.replace("import stat\n", "")
tests.write_text(text, encoding="utf-8")

health = Path("newsroom/projection/neo4j/discovery_lineage_reads.py")
replace_once(
    health,
    '''        # A live status read commonly follows the caller's timestamp. Preserve
        # every authority evidence clock and move only the final assessment time
        # forward so the evidence chronology remains explicit and valid.
        effective_assessed_at = assessed_at
        for item in evidence:
            if item.observed_at.value > effective_assessed_at.value:
                effective_assessed_at = item.observed_at
''',
    '''        # The live status observation is taken inside this assessment call and
        # may therefore follow the caller's lower-bound timestamp. Persisted
        # validation, gap and dead-letter evidence is never allowed to move the
        # assessment clock forward; future retained evidence still fails closed.
        effective_assessed_at = (
            status.serving_time
            if status.serving_time.value > assessed_at.value
            else assessed_at
        )
''',
)

chronology = Path(
    "newsroom/tests/test_discovery_projection_3e_health_chronology.py"
)
replace_once(
    chronology,
    "from pathlib import Path\n\n",
    "from dataclasses import replace\nfrom datetime import timedelta\nfrom pathlib import Path\n\nimport pytest\n\n",
)
replace_once(
    chronology,
    '''    DISCOVERY_LINEAGE_FAMILY_ID,
    DiscoveryHealthState,
''',
    '''    DISCOVERY_LINEAGE_FAMILY_ID,
    DiscoveryHealthContractError,
    DiscoveryHealthState,
''',
)
replace_once(
    chronology,
    '''        expected_assessed_at = max(
            [requested_at, *(item.observed_at for item in assessment.evidence)],
            key=lambda value: value.value,
        )
        assert assessment.assessed_at == expected_assessed_at
''',
    '''        assert assessment.assessed_at == status_evidence.observed_at
''',
)
with chronology.open("a", encoding="utf-8") as stream:
    stream.write(
        '''


def test_persisted_future_validation_evidence_still_fails_closed(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seed_complete_lineage(database)
    system = open_lineage_projection_system(database, MemoryNeo4jAdapter())
    try:
        _activate(system)
        status = system.projections.status(
            DISCOVERY_LINEAGE_FAMILY_ID,
            proof=proof(),
        )
        assert status.generation_id is not None
        validation = system.projections.validation(
            status.generation_id,
            proof=proof(),
        )
        future = UtcTimestamp(
            status.serving_time.value + timedelta(seconds=1)
        )
        facade = DiscoveryLineageProjectionFacade(
            active_read=lambda request, auth: system.structural.read_active(
                request,
                proof=auth,
            ),
            reconcile_active=lambda request, auth: system.structural.reconcile_active(
                request,
                proof=auth,
            ),
            status=lambda _family_id, _auth: status,
            validation=lambda _generation_id, _auth: replace(
                validation,
                recorded_at=future,
            ),
            gaps=lambda generation_id, limit, auth: system.projections.gaps(
                generation_id,
                limit=limit,
                proof=auth,
            ),
            dead_letters=lambda generation_id, limit, auth: (
                system.projections.dead_letters(
                    generation_id,
                    limit=limit,
                    proof=auth,
                )
            ),
            eligibility=lambda identifiers, auth: system.health.require_lineage_eligible(
                identifiers,
                proof=auth,
            ),
        )

        with pytest.raises(
            DiscoveryHealthContractError,
            match="evidence cannot follow",
        ):
            facade.assess_projection(
                _request(),
                policy=_POLICY,
                assessed_at=status.serving_time,
                proof=proof(),
            )
    finally:
        system.close()
'''
    )
