from __future__ import annotations

from pathlib import Path

import pytest

import scripts.sdlc.focus_gate_v2 as focus_gate
import scripts.sdlc.focus_selector as selector


class _Graph:
    def __init__(self, dependents: dict[str, tuple[str, ...]] | None = None) -> None:
        self._dependents = dependents or {}

    def dependent_paths(self, path: str) -> tuple[str, ...]:
        return self._dependents.get(path, ())


def _write(root: Path, relative: str, content: str = "") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_short_constant_reexport_selects_exact_consumer_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(tmp_path, "newsroom/example/models.py", "X = 7\n")
    _write(
        tmp_path,
        "newsroom/example/__init__.py",
        "from .models import X\n\nOther = 9\n",
    )
    _write(
        tmp_path,
        "newsroom/tests/test_constant.py",
        "from newsroom.example import X\n\n"
        "def test_constant() -> None:\n    assert X == 7\n",
    )
    _write(
        tmp_path,
        "newsroom/tests/test_unrelated_package_import.py",
        "from newsroom.example import Other\n\n"
        "def test_other() -> None:\n    assert Other == 9\n",
    )
    monkeypatch.setattr(
        selector,
        "build_dependency_graph",
        lambda _root: _Graph(
            {
                "newsroom/example/models.py": (
                    "newsroom/example/__init__.py",
                )
            }
        ),
    )

    route = selector.select_focus(
        ("newsroom/example/models.py",),
        repo_root=tmp_path,
    )

    assert route["selected_tests"] == ["newsroom/tests/test_constant.py"]
    assert route["full_health_required"] is False


def test_stateful_route_uses_direct_tests_and_two_bounded_sentinels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(tmp_path, "newsroom/authority/example.py", "def commit() -> int:\n    return 1\n")
    _write(
        tmp_path,
        "newsroom/tests/test_example_authority_consumer.py",
        "from newsroom.authority.example import commit\n\n"
        "def test_commit() -> None:\n    assert commit() == 1\n",
    )
    _write(tmp_path, "newsroom/tests/test_authority_migration_compatibility.py")
    _write(tmp_path, "newsroom/tests/test_authority_store_conformance.py")
    for index in range(5):
        _write(tmp_path, f"newsroom/tests/test_authority_unrelated_{index}.py")
    monkeypatch.setattr(
        selector,
        "build_dependency_graph",
        lambda _root: _Graph(),
    )

    route = selector.select_focus(
        ("newsroom/authority/example.py",),
        repo_root=tmp_path,
    )

    assert set(route["selected_tests"]) == {
        "newsroom/tests/test_example_authority_consumer.py",
        "newsroom/tests/test_authority_migration_compatibility.py",
        "newsroom/tests/test_authority_store_conformance.py",
    }
    assert not any("unrelated" in path for path in route["selected_tests"])
    assert "bounded_stateful_sentinels:F2" in route["reasons"]


def test_discovered_actual_service_consumer_promotes_route_to_f3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(tmp_path, "newsroom/feature.py", "def value() -> int:\n    return 1\n")
    _write(
        tmp_path,
        "newsroom/tests/test_feature_neo4j_service.py",
        "from newsroom.feature import value\n\n"
        "def test_service() -> None:\n    assert value() == 1\n",
    )
    monkeypatch.setattr(
        selector,
        "build_dependency_graph",
        lambda _root: _Graph(),
    )

    route = selector.select_focus(
        ("newsroom/feature.py",),
        repo_root=tmp_path,
    )

    assert "F3" in route["gates"]
    assert route["selected_tests"] == []
    assert route["selected_service_tests"] == [
        "newsroom/tests/test_feature_neo4j_service.py"
    ]
    assert "actual_service_consumer:F3" in route["reasons"]


def test_shared_dependency_change_truthfully_selects_research_and_full_health() -> None:
    route = selector.select_focus(("pyproject.toml",))

    assert route["research_required"] is True
    assert route["full_health_required"] is True
    assert route["bootstrap_required"] is True
    assert {"F0", "F1", "F2"} <= set(route["gates"])


def test_f0_validates_yaml_and_shell_syntax(tmp_path: Path) -> None:
    valid_yaml = tmp_path / "valid.yml"
    invalid_yaml = tmp_path / "invalid.yml"
    valid_shell = tmp_path / "valid.sh"
    invalid_shell = tmp_path / "invalid.sh"

    valid_yaml.write_text("jobs:\n  test:\n    runs-on: ubuntu-latest\n", encoding="utf-8")
    invalid_yaml.write_text("jobs: [\n", encoding="utf-8")
    valid_shell.write_text("#!/usr/bin/env bash\nset -euo pipefail\necho ok\n", encoding="utf-8")
    invalid_shell.write_text("#!/usr/bin/env bash\nif then\n", encoding="utf-8")

    focus_gate._validate_yaml(valid_yaml)
    focus_gate._validate_shell(valid_shell)
    with pytest.raises(focus_gate.FocusGateError, match="invalid YAML"):
        focus_gate._validate_yaml(invalid_yaml)
    with pytest.raises(focus_gate.FocusGateError, match="invalid shell syntax"):
        focus_gate._validate_shell(invalid_shell)
