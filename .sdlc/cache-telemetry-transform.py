from __future__ import annotations

from pathlib import Path

LANE = Path("scripts/sdlc/workflow_lane.py")
BUDGET = Path("scripts/sdlc/workflow_budget.py")
LANE_TEST = Path("newsroom/tests/test_sdlc_workflow_lane.py")
BUDGET_TEST = Path("newsroom/tests/test_sdlc_workflow_budget.py")

lane = LANE.read_text(encoding="utf-8")
old_constants = '''_CORE_TESTS = ("newsroom/tests",)


class WorkflowLaneError(ValueError):
'''
new_constants = '''_CORE_TESTS = ("newsroom/tests",)
_CACHE_KEY_ENV = "NEWSROOM_SDLC_CACHE_KEY"
_CACHE_HIT_ENV = "NEWSROOM_SDLC_CACHE_HIT"
_MAX_CACHE_KEY_CHARS = 2048


class WorkflowLaneError(ValueError):
'''
if lane.count(old_constants) != 1:
    raise SystemExit("lane cache constants mismatch")
lane = lane.replace(old_constants, new_constants)

old_static_end = '''    return values


def _spec(
'''
new_static_end = '''    return values


def _cache_evidence(
    environment: Mapping[str, str] | None = None,
) -> tuple[str | None, bool]:
    source = os.environ if environment is None else environment
    if any(
        not isinstance(name, str) or not isinstance(value, str)
        for name, value in source.items()
    ):
        raise WorkflowLaneError("cache_environment")
    raw_key = source.get(_CACHE_KEY_ENV, "")
    raw_hit = source.get(_CACHE_HIT_ENV, "false")
    if (
        len(raw_key) > _MAX_CACHE_KEY_CHARS
        or any(ord(character) < 32 or ord(character) == 127 for character in raw_key)
        or raw_hit not in {"true", "false"}
    ):
        raise WorkflowLaneError("cache_environment")
    key = raw_key or None
    hit = raw_hit == "true"
    if hit and key is None:
        raise WorkflowLaneError("cache_environment")
    return key, hit


def _spec(
'''
if lane.count(old_static_end) != 1:
    raise SystemExit("lane cache function insertion mismatch")
lane = lane.replace(old_static_end, new_static_end)

old_evidence = '''    if not isinstance(gate_run, dict) or not isinstance(command_digest, str):
        raise WorkflowLaneError("command_run")
    return build_gate_evidence(
'''
new_evidence = '''    if not isinstance(gate_run, dict) or not isinstance(command_digest, str):
        raise WorkflowLaneError("command_run")
    cache_key, cache_hit = _cache_evidence()
    return build_gate_evidence(
'''
if lane.count(old_evidence) != 1:
    raise SystemExit("lane evidence cache insertion mismatch")
lane = lane.replace(old_evidence, new_evidence)
old_cache_args = '''        cache_key=None,
        cache_hit=False,
'''
new_cache_args = '''        cache_key=cache_key,
        cache_hit=cache_hit,
'''
if lane.count(old_cache_args) != 1:
    raise SystemExit("lane evidence cache args mismatch")
lane = lane.replace(old_cache_args, new_cache_args)
LANE.write_text(lane, encoding="utf-8")

budget = BUDGET.read_text(encoding="utf-8")
old_budget_constants = '''_OPTIONAL_STATIC_ENVIRONMENT = (
    "HOME",
    "RUNNER_TEMP",
    "TMPDIR",
    "UV_CACHE_DIR",
)
_ROUTE_OUTPUT_KEYS = frozenset(
'''
new_budget_constants = '''_OPTIONAL_STATIC_ENVIRONMENT = (
    "HOME",
    "RUNNER_TEMP",
    "TMPDIR",
    "UV_CACHE_DIR",
)
_CACHE_TELEMETRY_ENVIRONMENT = (
    "NEWSROOM_SDLC_CACHE_KEY",
    "NEWSROOM_SDLC_CACHE_HIT",
)
_ROUTE_OUTPUT_KEYS = frozenset(
'''
if budget.count(old_budget_constants) != 1:
    raise SystemExit("budget cache constants mismatch")
budget = budget.replace(old_budget_constants, new_budget_constants)
old_optional = '''        for name in _OPTIONAL_STATIC_ENVIRONMENT:
            value = source.get(name)
            if value:
                environment[name] = value
    else:
'''
new_optional = '''        for name in _OPTIONAL_STATIC_ENVIRONMENT:
            value = source.get(name)
            if value:
                environment[name] = value
        for name in _CACHE_TELEMETRY_ENVIRONMENT:
            value = source.get(name)
            if value:
                environment[name] = _text(
                    value, "cache_environment", maximum=2048
                )
    else:
'''
if budget.count(old_optional) != 1:
    raise SystemExit("budget cache environment insertion mismatch")
budget = budget.replace(old_optional, new_optional)
BUDGET.write_text(budget, encoding="utf-8")

lane_test = LANE_TEST.read_text(encoding="utf-8")
old_assertions = '''    assert captured["finalize_ms"] == 0
    assert captured["service_compatibility_digest"] == service_compatibility_digest()
'''
new_assertions = '''    assert captured["finalize_ms"] == 0
    assert captured["cache_key"] is None
    assert captured["cache_hit"] is False
    assert captured["service_compatibility_digest"] == service_compatibility_digest()
'''
if lane_test.count(old_assertions) != 1:
    raise SystemExit("lane evidence assertions mismatch")
lane_test = lane_test.replace(old_assertions, new_assertions)
marker = "def test_cache_evidence_is_exact_and_fail_closed("
if marker in lane_test:
    raise SystemExit("lane cache tests already present")
lane_test += '''


def test_cache_evidence_is_exact_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEWSROOM_SDLC_CACHE_KEY", raising=False)
    monkeypatch.delenv("NEWSROOM_SDLC_CACHE_HIT", raising=False)
    assert lane_module._cache_evidence() == (None, False)

    monkeypatch.setenv("NEWSROOM_SDLC_CACHE_KEY", "uv-linux-py312-lock")
    monkeypatch.setenv("NEWSROOM_SDLC_CACHE_HIT", "false")
    assert lane_module._cache_evidence() == ("uv-linux-py312-lock", False)

    monkeypatch.setenv("NEWSROOM_SDLC_CACHE_HIT", "true")
    assert lane_module._cache_evidence() == ("uv-linux-py312-lock", True)

    monkeypatch.delenv("NEWSROOM_SDLC_CACHE_KEY")
    with pytest.raises(WorkflowLaneError, match="cache_environment"):
        lane_module._cache_evidence()

    monkeypatch.setenv("NEWSROOM_SDLC_CACHE_KEY", "key")
    monkeypatch.setenv("NEWSROOM_SDLC_CACHE_HIT", "maybe")
    with pytest.raises(WorkflowLaneError, match="cache_environment"):
        lane_module._cache_evidence()

    monkeypatch.setenv("NEWSROOM_SDLC_CACHE_KEY", "bad\\nkey")
    monkeypatch.setenv("NEWSROOM_SDLC_CACHE_HIT", "false")
    with pytest.raises(WorkflowLaneError, match="cache_environment"):
        lane_module._cache_evidence()


def test_gate_evidence_records_exact_cache_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract(tmp_path)
    captured = {}
    monkeypatch.setenv("NEWSROOM_SDLC_CACHE_KEY", "uv-cache-exact-key")
    monkeypatch.setenv("NEWSROOM_SDLC_CACHE_HIT", "true")
    monkeypatch.setattr(lane_module, "installed_uv_version", lambda: "0.8.0")
    monkeypatch.setattr(
        lane_module,
        "build_gate_evidence",
        lambda **kwargs: captured.update(kwargs) or {"result": "PASS"},
    )

    lane_module._evidence(
        repo_root=tmp_path,
        contract=contract,
        route=_route(),
        command_run=_run("source-integrity", "source").as_dict(),
        summary=None,
        runner_kind="github-hosted",
        service_digest=None,
    )

    assert captured["cache_key"] == "uv-cache-exact-key"
    assert captured["cache_hit"] is True
'''
LANE_TEST.write_text(lane_test, encoding="utf-8")

budget_test = BUDGET_TEST.read_text(encoding="utf-8")
old_ambient = '''        "UV_CACHE_DIR": "/tmp/uv-cache",
        "GITHUB_TOKEN": "must-not-pass",
'''
new_ambient = '''        "UV_CACHE_DIR": "/tmp/uv-cache",
        "NEWSROOM_SDLC_CACHE_KEY": "uv-linux-py312-lock",
        "NEWSROOM_SDLC_CACHE_HIT": "true",
        "GITHUB_TOKEN": "must-not-pass",
'''
if budget_test.count(old_ambient) != 1:
    raise SystemExit("budget ambient cache insertion mismatch")
budget_test = budget_test.replace(old_ambient, new_ambient)
old_preserve = '''    assert environment["HOME"] == "/home/runner"
    assert environment["GITHUB_JOB"] == "core"
'''
new_preserve = '''    assert environment["HOME"] == "/home/runner"
    assert environment["GITHUB_JOB"] == "core"
    assert environment["NEWSROOM_SDLC_CACHE_KEY"] == "uv-linux-py312-lock"
    assert environment["NEWSROOM_SDLC_CACHE_HIT"] == "true"
'''
if budget_test.count(old_preserve) != 1:
    raise SystemExit("budget preserve cache assertions mismatch")
budget_test = budget_test.replace(old_preserve, new_preserve)
old_route_drop = '''    assert "UV_CACHE_DIR" not in environment
    assert "GITHUB_TOKEN" not in environment
'''
new_route_drop = '''    assert "UV_CACHE_DIR" not in environment
    assert "NEWSROOM_SDLC_CACHE_KEY" not in environment
    assert "NEWSROOM_SDLC_CACHE_HIT" not in environment
    assert "GITHUB_TOKEN" not in environment
'''
if budget_test.count(old_route_drop) != 1:
    raise SystemExit("budget route cache assertions mismatch")
budget_test = budget_test.replace(old_route_drop, new_route_drop)
marker = "def test_lane_cache_telemetry_rejects_control_characters("
if marker in budget_test:
    raise SystemExit("budget cache tests already present")
budget_test += '''


def test_lane_cache_telemetry_rejects_control_characters() -> None:
    ambient = _ambient("core")
    ambient["NEWSROOM_SDLC_CACHE_KEY"] = "bad\\nkey"
    with pytest.raises(budget.WorkflowBudgetError, match="cache_environment"):
        budget._child_environment(
            ambient=ambient,
            service=False,
            preserve_lane_static=True,
        )
'''
BUDGET_TEST.write_text(budget_test, encoding="utf-8")
