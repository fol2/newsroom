from __future__ import annotations

from pathlib import Path

SOURCE = Path("scripts/sdlc/workflow_budget.py")
TEST = Path("newsroom/tests/test_sdlc_workflow_budget.py")

source = SOURCE.read_text(encoding="utf-8")
old = '''def _child_environment(
    *,
    ambient: Mapping[str, str] | None = None,
    service: bool,
) -> dict[str, str]:
    source = os.environ if ambient is None else ambient
    if any(
        not isinstance(name, str) or not isinstance(value, str)
        for name, value in source.items()
    ):
        raise WorkflowBudgetError("ambient_environment")
    environment = {
        "CI": "true",
        "LANG": source.get("LANG", "C.UTF-8"),
        "LC_ALL": source.get("LC_ALL", "C.UTF-8"),
        "PATH": source.get("PATH", "/usr/bin:/bin"),
        "PYTHONHASHSEED": "0",
        "PYTHONUTF8": "1",
    }
    for name in _OPTIONAL_STATIC_ENVIRONMENT:
        value = source.get(name)
        if value:
            environment[name] = value
    for name in _GITHUB_CONTEXT_ENVIRONMENT:
        value = source.get(name)
        if not value:
            raise WorkflowBudgetError("github_environment")
        environment[name] = value
    if environment["GITHUB_ACTIONS"] != "true":
        raise WorkflowBudgetError("github_environment")
    if service:
        if any(source.get(name) != value for name, value in _SERVICE_CONFIGURATION.items()):
            raise WorkflowBudgetError("service_environment")
        environment.update(_SERVICE_CONFIGURATION)
'''
new = '''def _child_environment(
    *,
    ambient: Mapping[str, str] | None = None,
    service: bool,
    preserve_lane_static: bool,
) -> dict[str, str]:
    source = os.environ if ambient is None else ambient
    if any(
        not isinstance(name, str) or not isinstance(value, str)
        for name, value in source.items()
    ):
        raise WorkflowBudgetError("ambient_environment")
    if service and not preserve_lane_static:
        raise WorkflowBudgetError("service_environment")
    if preserve_lane_static:
        environment = {
            "CI": "true",
            "LANG": source.get("LANG", "C.UTF-8"),
            "LC_ALL": source.get("LC_ALL", "C.UTF-8"),
            "PATH": source.get("PATH", "/usr/bin:/bin"),
            "PYTHONHASHSEED": "0",
            "PYTHONUTF8": "1",
        }
        for name in _OPTIONAL_STATIC_ENVIRONMENT:
            value = source.get(name)
            if value:
                environment[name] = value
    else:
        temporary = source.get("RUNNER_TEMP", "/tmp")
        environment = {
            "CI": "true",
            "HOME": temporary,
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/usr/bin:/bin",
            "PYTHONHASHSEED": "0",
            "PYTHONUTF8": "1",
            "RUNNER_TEMP": temporary,
            "TMPDIR": temporary,
        }
    for name in _GITHUB_CONTEXT_ENVIRONMENT:
        value = source.get(name)
        if not value:
            raise WorkflowBudgetError("github_environment")
        environment[name] = value
    if environment["GITHUB_ACTIONS"] != "true":
        raise WorkflowBudgetError("github_environment")
    if service:
        if any(source.get(name) != value for name, value in _SERVICE_CONFIGURATION.items()):
            raise WorkflowBudgetError("service_environment")
        environment.update(_SERVICE_CONFIGURATION)
'''
if source.count(old) != 1:
    raise SystemExit("environment replacement mismatch")
source = source.replace(old, new)
source = source.replace(
    '''        env=_child_environment(service=False),
''',
    '''        env=_child_environment(service=False, preserve_lane_static=False),
''',
)
source = source.replace(
    '''        env=_child_environment(service=lane_id == "service"),
''',
    '''        env=_child_environment(
            service=lane_id == "service", preserve_lane_static=True
        ),
''',
)
SOURCE.write_text(source, encoding="utf-8")

tests = TEST.read_text(encoding="utf-8")
tests = tests.replace(
    '''        ambient=_ambient("core"), service=False
''',
    '''        ambient=_ambient("core"), service=False, preserve_lane_static=True
''',
)
tests = tests.replace(
    '''        ambient=_ambient("service", service=True), service=True
''',
    '''        ambient=_ambient("service", service=True),
        service=True,
        preserve_lane_static=True,
''',
)
tests = tests.replace(
    '''        budget._child_environment(ambient=wrong, service=True)
''',
    '''        budget._child_environment(
            ambient=wrong, service=True, preserve_lane_static=True
        )
''',
)
tests = tests.replace(
    '''        budget._child_environment(ambient=ambient, service=False)
''',
    '''        budget._child_environment(
            ambient=ambient, service=False, preserve_lane_static=False
        )
''',
)
marker = "def test_route_child_environment_is_fixed_and_drops_uv_cache("
if marker in tests:
    raise SystemExit("environment profile test already present")
tests += '''


def test_route_child_environment_is_fixed_and_drops_uv_cache() -> None:
    environment = budget._child_environment(
        ambient=_ambient("route"),
        service=False,
        preserve_lane_static=False,
    )

    assert environment["PATH"] == "/usr/bin:/bin"
    assert environment["HOME"] == "/tmp/runner"
    assert environment["TMPDIR"] == "/tmp/runner"
    assert "UV_CACHE_DIR" not in environment
    assert "GITHUB_TOKEN" not in environment


def test_service_profile_cannot_use_route_environment() -> None:
    with pytest.raises(budget.WorkflowBudgetError, match="service_environment"):
        budget._child_environment(
            ambient=_ambient("service", service=True),
            service=True,
            preserve_lane_static=False,
        )
'''
TEST.write_text(tests, encoding="utf-8")
