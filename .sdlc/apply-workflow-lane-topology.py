from __future__ import annotations

from pathlib import Path

SOURCE = Path("scripts/sdlc/workflow_lane.py")
TEST = Path("newsroom/tests/test_sdlc_workflow_lane.py")

source = SOURCE.read_text(encoding="utf-8")
old_constants = '''_SERVICE_CONFIGURATION = {
    "NEWSROOM_NEO4J_DATABASE": "neo4j",
    "NEWSROOM_NEO4J_PROJECTOR_USERNAME": "newsroom_projector",
    "NEWSROOM_NEO4J_SERVICE_REQUIRED": "1",
    "NEWSROOM_NEO4J_URI": "bolt://localhost:7687",
}


class WorkflowLaneError(ValueError):
'''
new_constants = '''_SERVICE_CONFIGURATION = {
    "NEWSROOM_NEO4J_DATABASE": "neo4j",
    "NEWSROOM_NEO4J_PROJECTOR_USERNAME": "newsroom_projector",
    "NEWSROOM_NEO4J_SERVICE_REQUIRED": "1",
    "NEWSROOM_NEO4J_URI": "bolt://localhost:7687",
}
_CORE_TESTS = ("newsroom/tests",)


class WorkflowLaneError(ValueError):
'''
if source.count(old_constants) != 1:
    raise SystemExit("constant insertion mismatch")
source = source.replace(old_constants, new_constants)

old_service_environment = '''def _service_environment() -> dict[str, str]:
    if any(
        os.environ.get(name) != value
        for name, value in _SERVICE_CONFIGURATION.items()
    ):
        raise WorkflowLaneError("service_configuration")
    return dict(_SERVICE_CONFIGURATION)


def _expected_spec(
'''
new_service_environment = '''def _service_environment() -> dict[str, str]:
    if any(
        os.environ.get(name) != value
        for name, value in _SERVICE_CONFIGURATION.items()
    ):
        raise WorkflowLaneError("service_configuration")
    return dict(_SERVICE_CONFIGURATION)


def _repository_service_tests(repo_root: Path) -> tuple[str, ...]:
    return tuple(
        sorted(
            path.relative_to(repo_root).as_posix()
            for path in (repo_root / "newsroom" / "tests").glob(
                "test_projection_*_neo4j_service.py"
            )
            if path.is_file() and not path.is_symlink()
        )
    )


def _validate_test_topology(
    contract: SdlcContract,
    route: Mapping[str, object],
) -> None:
    expected_service = (
        _repository_service_tests(contract.repo_root)
        if route["service_required"] is True
        else ()
    )
    if (
        tuple(route["core_tests"]) != _CORE_TESTS
        or tuple(route["service_tests"]) != expected_service
        or tuple(route["sentinels"]) != tuple(contract.sentinels)
        or (route["service_required"] is True and not expected_service)
    ):
        raise WorkflowLaneError("test_topology")


def _expected_spec(
'''
if source.count(old_service_environment) != 1:
    raise SystemExit("topology function insertion mismatch")
source = source.replace(old_service_environment, new_service_environment)

old_context = '''    route = _validate_route(contract, _load_json(root, route_path))
    if (
        route["head_sha"] != context.evaluated_sha
'''
new_context = '''    route = _validate_route(contract, _load_json(root, route_path))
    _validate_test_topology(contract, route)
    if (
        route["head_sha"] != context.evaluated_sha
'''
if source.count(old_context) != 1:
    raise SystemExit("context topology binding mismatch")
source = source.replace(old_context, new_context)
SOURCE.write_text(source, encoding="utf-8")

tests = TEST.read_text(encoding="utf-8")
marker = "def test_route_test_topology_is_repository_owned("
if marker in tests:
    raise SystemExit("topology tests already present")
tests += '''


@pytest.mark.parametrize(
    ("service_required", "field", "value"),
    [
        (False, "core_tests", ["newsroom/tests/test_sdlc_workflow_lane.py"]),
        (True, "service_tests", ["--collect-only"]),
        (False, "sentinels", ["invented_sentinel"]),
    ],
)
def test_route_test_topology_is_repository_owned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    service_required: bool,
    field: str,
    value: list[str],
) -> None:
    contract = _contract(tmp_path)
    expected_service = (
        ("newsroom/tests/test_projection_b2_neo4j_service.py",)
        if service_required
        else ()
    )
    monkeypatch.setattr(
        lane_module,
        "_repository_service_tests",
        lambda _root: expected_service,
    )
    route = _route(service=service_required)
    route["sentinels"] = list(contract.sentinels)
    route[field] = value

    with pytest.raises(WorkflowLaneError, match="test_topology"):
        lane_module._validate_test_topology(contract, route)


def test_exact_route_test_topology_is_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract(tmp_path)
    service_tests = ("newsroom/tests/test_projection_b2_neo4j_service.py",)
    monkeypatch.setattr(
        lane_module,
        "_repository_service_tests",
        lambda _root: service_tests,
    )
    route = _route(service=True)
    route["sentinels"] = list(contract.sentinels)

    lane_module._validate_test_topology(contract, route)
'''
TEST.write_text(tests, encoding="utf-8")
