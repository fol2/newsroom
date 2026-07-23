from __future__ import annotations

from pathlib import Path

SOURCE = Path("scripts/sdlc/workflow_budget.py")
TEST = Path("newsroom/tests/test_sdlc_workflow_budget.py")

source = SOURCE.read_text(encoding="utf-8")
old_inventory = '''    root = Path(repo_root).resolve()
    _, directory = _relative_existing_directory(root, output_directory)
    try:
'''
new_inventory = '''    root = Path(repo_root).resolve()
    _, directory = _relative_existing_directory(root, output_directory)
    entries = tuple(sorted(directory.iterdir(), key=lambda path: path.name))
    if (
        tuple(path.name for path in entries)
        != ("event.json", "route-output.json", "route.json")
        or any(path.is_symlink() or not path.is_file() for path in entries)
    ):
        raise WorkflowBudgetError("route_inventory")
    try:
'''
if source.count(old_inventory) != 1:
    raise SystemExit("route inventory replacement mismatch")
source = source.replace(old_inventory, new_inventory)

old_output = '''    output = _safe_target(root, output_path, suffix=".json")
    output_relative = output.relative_to(root).as_posix()
'''
new_output = '''    output = _safe_target(root, output_path, suffix=".json")
    if output.is_relative_to(artifact_directory):
        raise WorkflowBudgetError("output_path")
    output_relative = output.relative_to(root).as_posix()
'''
if source.count(old_output) != 1:
    raise SystemExit("lane output separation mismatch")
source = source.replace(old_output, new_output)
SOURCE.write_text(source, encoding="utf-8")

tests = TEST.read_text(encoding="utf-8")
marker = "def test_route_bundle_rejects_unlisted_inventory("
if marker in tests:
    raise SystemExit("artifact boundary tests already present")
tests += '''


def test_route_bundle_rejects_unlisted_inventory(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    context = _context("route")
    event = _event()
    route = _route(contract)
    directory = tmp_path / "route-extra"
    directory.mkdir()
    output = RouteOutput(
        artifact_name=budget._route_artifact_name(context),
        service_required=False,
        route_identity=sha256_identity(route),
        event_identity=str(event.as_dict()["event_identity"]),
    )
    _write(directory / "route.json", route)
    _write(directory / "event.json", event.as_dict())
    _write(directory / "route-output.json", output.as_dict())
    (directory / "unlisted.txt").write_text("unexpected", encoding="utf-8")

    with pytest.raises(budget.WorkflowBudgetError, match="route_inventory"):
        budget.validate_route_bundle(
            repo_root=tmp_path,
            output_directory="route-extra",
            context=context,
            contract=contract,
        )


def test_lane_output_cannot_be_written_inside_artifact_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context("core")
    contract = _contract(tmp_path)
    _write(tmp_path / "route.json", {"route": True})
    (tmp_path / "artifact").mkdir()
    monkeypatch.setattr(budget, "context_from_environment", lambda _root: context)
    monkeypatch.setattr(budget, "load_contract", lambda _root: contract)

    with pytest.raises(budget.WorkflowBudgetError, match="output_path"):
        budget.run_bounded_lane_finalization(
            repo_root=tmp_path,
            route_path="route.json",
            lane_id="core",
            artifact_root="artifact",
            output_path="artifact/lane-output.json",
        )
'''
TEST.write_text(tests, encoding="utf-8")
