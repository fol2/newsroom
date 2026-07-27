from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{path}: expected one reviewed replacement, found {count}"
        )
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_region(
    path: str,
    start_marker: str,
    end_marker: str,
    replacement: str,
) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    start = text.find(start_marker)
    end = text.find(end_marker, start + len(start_marker))
    if start < 0 or end < 0 or text.find(start_marker, start + 1) >= 0:
        raise SystemExit(f"{path}: reviewed region markers differ")
    target.write_text(
        text[:start] + replacement + text[end:],
        encoding="utf-8",
    )


def patch_orchestrator() -> None:
    path = "scripts/sdlc/workflow_orchestrator.py"
    replace_once(
        path,
        "import tempfile\nfrom typing import Mapping, Sequence\n",
        "import tempfile\nimport time\nfrom typing import Mapping, Sequence\n",
    )
    replace_once(
        path,
        "_GITHUB_REQUEST_TIMEOUT_SECONDS = 5.0\n",
        "_GITHUB_REQUEST_TIMEOUT_SECONDS = 5.0\n"
        "_GITHUB_PROPAGATION_RETRY_ATTEMPTS = 4\n"
        "_GITHUB_PROPAGATION_RETRY_DELAY_SECONDS = 0.75\n",
    )
    helper = '''def _fetch_verified_lane(
    *,
    client: GitHubActionsClient,
    root: Path,
    target: Path,
    context: GithubRunContext,
    contract: SdlcContract,
    lane_id: str,
    artifact_name_value: str,
) -> ShadowLaneRecord:
    output_name = f"{lane_id}-transport"
    output_path = target / output_name
    for attempt_index in range(_GITHUB_PROPAGATION_RETRY_ATTEMPTS):
        shutil.rmtree(output_path, ignore_errors=True)
        try:
            fetch_artifact_bundle(
                client=client,
                output_parent=target,
                output_name=output_name,
                run_id=context.run_id,
                run_attempt=context.run_attempt,
                artifact_name=artifact_name_value,
            )
            return verify_shadow_lane(
                repo_root=root,
                bundle_root=output_path,
                lane_id=lane_id,
                decision_context=context,
                contract=contract,
            )
        except (GitHubTransportError, ShadowLaneError):
            shutil.rmtree(output_path, ignore_errors=True)
            if attempt_index + 1 >= _GITHUB_PROPAGATION_RETRY_ATTEMPTS:
                raise
            time.sleep(_GITHUB_PROPAGATION_RETRY_DELAY_SECONDS)
    raise AssertionError("bounded lane verification exhausted without result")


def _lane_verification_failure_code(error: ShadowLaneError) -> str:
    code = str(error)
    if _SAFE_CODE.fullmatch(code) is None:
        return "lane-verification"
    return f"lane-verification-{code}"


'''
    replace_once(
        path,
        "def collect_decision_inputs(\n",
        helper + "def collect_decision_inputs(\n",
    )
    core_service = '''            core_name = artifact_name(_producer_context(context, "core"))
            core = _fetch_verified_lane(
                client=client,
                root=root,
                target=target,
                context=context,
                contract=contract,
                lane_id="core",
                artifact_name_value=core_name,
            )
            service_name = artifact_name(_producer_context(context, "service"))
            if core.receipt.route.service_required:
                service = _fetch_verified_lane(
                    client=client,
                    root=root,
                    target=target,
                    context=context,
                    contract=contract,
                    lane_id="service",
                    artifact_name_value=service_name,
                )
'''
    replace_region(
        path,
        '            core_name = artifact_name(_producer_context(context, "core"))\n',
        "            elif _unexpected_artifact(\n",
        core_service,
    )
    replace_once(
        path,
        "        except ShadowLaneError:\n"
        "            event = core = service = None\n"
        '            failure_result = "EVIDENCE_MISMATCH"\n'
        '            failure_code = "lane-verification"\n',
        "        except ShadowLaneError as exc:\n"
        "            event = core = service = None\n"
        '            failure_result = "EVIDENCE_MISMATCH"\n'
        "            failure_code = _lane_verification_failure_code(exc)\n",
    )


def patch_tests() -> None:
    path = "newsroom/tests/test_sdlc_workflow_orchestrator.py"
    replace_once(
        path,
        "from scripts.sdlc.shadow_decision import failure_shadow_decision\n",
        "from scripts.sdlc.shadow_decision import failure_shadow_decision\n"
        "from scripts.sdlc.shadow_lane import ShadowLaneError\n",
    )
    retry_tests = '''

def test_collection_retries_transient_lane_verification_and_cleans_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = _FakeLane("core", False)
    fetched = _patch_collection_dependencies(monkeypatch, core=core)
    attempts = 0
    sleeps: list[float] = []

    def verify(*, lane_id, **_kwargs):
        nonlocal attempts
        assert lane_id == "core"
        attempts += 1
        if attempts == 1:
            raise ShadowLaneError("job_telemetry")
        return core

    monkeypatch.setattr(orchestrator, "verify_shadow_lane", verify)
    monkeypatch.setattr(
        orchestrator, "_GITHUB_PROPAGATION_RETRY_ATTEMPTS", 3
    )
    monkeypatch.setattr(
        orchestrator, "_GITHUB_PROPAGATION_RETRY_DELAY_SECONDS", 0.25
    )
    monkeypatch.setattr(orchestrator.time, "sleep", sleeps.append)

    value = orchestrator.collect_decision_inputs(
        repo_root=tmp_path, output_directory="decision-input"
    )

    assert value["status"] == "READY"
    assert attempts == 2
    assert len(fetched) == 2
    assert sleeps == [0.25]
    assert (tmp_path / "decision-input" / "core-transport").is_dir()


def test_collection_retries_transient_transport_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = _FakeLane("core", False)
    _patch_collection_dependencies(monkeypatch, core=core)
    fetch_attempts = 0
    sleeps: list[float] = []

    def fetch(**kwargs):
        nonlocal fetch_attempts
        fetch_attempts += 1
        if fetch_attempts == 1:
            raise GitHubTransportError("jobs")
        Path(kwargs["output_parent"], kwargs["output_name"]).mkdir()
        return object()

    monkeypatch.setattr(orchestrator, "fetch_artifact_bundle", fetch)
    monkeypatch.setattr(
        orchestrator, "_GITHUB_PROPAGATION_RETRY_ATTEMPTS", 2
    )
    monkeypatch.setattr(
        orchestrator, "_GITHUB_PROPAGATION_RETRY_DELAY_SECONDS", 0.5
    )
    monkeypatch.setattr(orchestrator.time, "sleep", sleeps.append)

    value = orchestrator.collect_decision_inputs(
        repo_root=tmp_path, output_directory="decision-input"
    )

    assert value["status"] == "READY"
    assert fetch_attempts == 2
    assert sleeps == [0.5]


def test_collection_exhaustion_is_typed_redacted_and_cleans_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = _FakeLane("core", False)
    fetched = _patch_collection_dependencies(monkeypatch, core=core)
    sleeps: list[float] = []
    monkeypatch.setattr(
        orchestrator,
        "verify_shadow_lane",
        lambda **_kwargs: (_ for _ in ()).throw(
            ShadowLaneError("job_telemetry")
        ),
    )
    monkeypatch.setattr(
        orchestrator, "_GITHUB_PROPAGATION_RETRY_ATTEMPTS", 3
    )
    monkeypatch.setattr(
        orchestrator, "_GITHUB_PROPAGATION_RETRY_DELAY_SECONDS", 0.1
    )
    monkeypatch.setattr(orchestrator.time, "sleep", sleeps.append)

    value = orchestrator.collect_decision_inputs(
        repo_root=tmp_path, output_directory="decision-input"
    )

    assert value["status"] == "ERROR"
    assert value["failure_result"] == "EVIDENCE_MISMATCH"
    assert value["failure_code"] == "lane-verification-job_telemetry"
    assert len(fetched) == 3
    assert sleeps == [0.1, 0.1]
    assert not (tmp_path / "decision-input" / "core-transport").exists()
    assert (
        orchestrator._lane_verification_failure_code(
            ShadowLaneError("provider secret/value")
        )
        == "lane-verification"
    )
'''
    replace_once(
        path,
        "\n\ndef test_transport_error_is_redacted_to_stable_failure_code(\n",
        retry_tests
        + "\n\ndef test_transport_error_is_redacted_to_stable_failure_code(\n",
    )
    replace_once(
        path,
        "def test_transport_error_is_redacted_to_stable_failure_code(\n"
        "    tmp_path: Path, monkeypatch: pytest.MonkeyPatch\n"
        ") -> None:\n"
        '    monkeypatch.setattr(orchestrator, "context_from_environment", lambda _root: _context())\n',
        "def test_transport_error_is_redacted_to_stable_failure_code(\n"
        "    tmp_path: Path, monkeypatch: pytest.MonkeyPatch\n"
        ") -> None:\n"
        "    monkeypatch.setattr(\n"
        '        orchestrator, "_GITHUB_PROPAGATION_RETRY_ATTEMPTS", 1\n'
        "    )\n"
        '    monkeypatch.setattr(orchestrator, "context_from_environment", lambda _root: _context())\n',
    )


if __name__ == "__main__":
    print("patch-stage:orchestrator")
    patch_orchestrator()
    print("patch-stage:tests")
    patch_tests()
    print("patch-stage:complete")
