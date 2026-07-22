from __future__ import annotations

from pathlib import Path

import pytest

from scripts.sdlc.dependencies import (
    DependencyError,
    build_dependency_graph,
    module_name_for_path,
    python_changes,
)


def _write(root: Path, relative: str, source: str = "") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_module_names_cover_modules_and_packages() -> None:
    assert module_name_for_path("newsroom/core.py") == "newsroom.core"
    assert module_name_for_path("newsroom/projection/__init__.py") == (
        "newsroom.projection"
    )
    assert module_name_for_path("docs/example.py") is None


def test_graph_resolves_relative_reexports_and_transitive_dependents(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "newsroom/__init__.py")
    _write(tmp_path, "newsroom/core.py", "VALUE = 1\n")
    _write(tmp_path, "newsroom/mid.py", "from .core import VALUE\n")
    _write(tmp_path, "newsroom/projection/__init__.py")
    _write(tmp_path, "newsroom/projection/neo4j/__init__.py")
    _write(
        tmp_path,
        "newsroom/projection/neo4j/adapter.py",
        "from newsroom.mid import VALUE\n",
    )

    graph = build_dependency_graph(tmp_path)

    assert graph.dependent_paths("newsroom/core.py") == (
        "newsroom/mid.py",
        "newsroom/projection/neo4j/adapter.py",
    )


def test_package_reexport_links_child_module_to_package_importer(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "newsroom/__init__.py")
    _write(
        tmp_path,
        "newsroom/package/__init__.py",
        "from .models import Contract\n",
    )
    _write(tmp_path, "newsroom/package/models.py", "class Contract: pass\n")
    _write(
        tmp_path,
        "newsroom/consumer.py",
        "from newsroom.package import Contract\n",
    )

    graph = build_dependency_graph(tmp_path)

    assert graph.dependent_paths("newsroom/package/models.py") == (
        "newsroom/consumer.py",
        "newsroom/package/__init__.py",
    )


def test_unresolved_internal_import_and_relative_escape_fail_closed(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "newsroom/__init__.py")
    _write(tmp_path, "newsroom/bad.py", "import newsroom.missing\n")
    with pytest.raises(DependencyError, match="unresolved internal import"):
        build_dependency_graph(tmp_path)

    (tmp_path / "newsroom" / "bad.py").write_text(
        "from ..outside import value\n",
        encoding="utf-8",
    )
    with pytest.raises(DependencyError, match="escapes repository package"):
        build_dependency_graph(tmp_path)


def test_symlinked_dependency_source_is_not_treated_as_tree_content(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "outside.py", "VALUE = 1\n")
    _write(tmp_path, "newsroom/__init__.py")
    (tmp_path / "newsroom" / "linked.py").symlink_to(tmp_path / "outside.py")

    with pytest.raises(DependencyError, match="symlinked"):
        build_dependency_graph(tmp_path)


def test_deleted_or_untracked_python_module_has_no_inferred_safe_edge(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "newsroom/__init__.py")
    graph = build_dependency_graph(tmp_path)

    with pytest.raises(DependencyError, match="absent from head tree"):
        graph.dependent_paths("newsroom/deleted.py")


def test_test_modules_are_excluded_from_production_dependency_analysis() -> None:
    assert python_changes(
        (
            "newsroom/core.py",
            "newsroom/tests/test_core.py",
            "scripts/tool.py",
            "README.md",
        )
    ) == ("newsroom/core.py", "scripts/tool.py")
