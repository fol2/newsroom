from __future__ import annotations

import ast
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class DependencyError(ValueError):
    """Raised when a repository-owned Python dependency cannot be resolved safely."""


def module_name_for_path(path: str) -> str | None:
    candidate = Path(path)
    if candidate.suffix != ".py" or not candidate.parts:
        return None
    if candidate.parts[0] not in {"newsroom", "scripts"}:
        return None
    parts = list(candidate.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) if parts else None


def _source_paths(repo_root: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    for package in ("newsroom", "scripts"):
        root = repo_root / package
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            relative = path.relative_to(repo_root)
            if "__pycache__" in relative.parts:
                continue
            if relative.parts[:2] == ("newsroom", "tests"):
                continue
            paths.append(path)
    return tuple(sorted(paths))


def _package_for(module: str, path: Path) -> str:
    return module if path.name == "__init__.py" else module.rpartition(".")[0]


def _relative_module(package: str, level: int, module: str | None) -> str:
    package_parts = package.split(".") if package else []
    parents = level - 1
    if parents >= len(package_parts):
        raise DependencyError(
            f"relative import escapes repository package: {package or '<root>'}"
        )
    prefix = package_parts[: len(package_parts) - parents]
    if module:
        prefix.extend(module.split("."))
    return ".".join(prefix)


def _known_prefixes(module: str, modules: set[str]) -> tuple[str, ...]:
    parts = module.split(".")
    return tuple(
        candidate
        for index in range(1, len(parts) + 1)
        if (candidate := ".".join(parts[:index])) in modules
    )


@dataclass(frozen=True)
class DependencyGraph:
    repo_root: Path
    path_to_module: dict[str, str]
    module_to_path: dict[str, str]
    reverse_importers: dict[str, frozenset[str]]

    def dependent_paths(self, path: str) -> tuple[str, ...]:
        module = self.path_to_module.get(path)
        if module is None:
            raise DependencyError(f"changed Python module is absent from head tree: {path}")
        seen = {module}
        queue = deque([module])
        while queue:
            imported = queue.popleft()
            for importer in self.reverse_importers.get(imported, frozenset()):
                if importer not in seen:
                    seen.add(importer)
                    queue.append(importer)
        return tuple(
            sorted(
                self.module_to_path[item]
                for item in seen - {module}
                if item in self.module_to_path
            )
        )


def build_dependency_graph(repo_root: str | Path) -> DependencyGraph:
    root = Path(repo_root).resolve()
    path_to_module: dict[str, str] = {}
    module_to_path: dict[str, str] = {}
    sources: dict[str, tuple[Path, ast.AST]] = {}

    for source_path in _source_paths(root):
        relative = source_path.relative_to(root).as_posix()
        module = module_name_for_path(relative)
        if module is None:
            continue
        if module in module_to_path:
            raise DependencyError(f"duplicate repository module: {module}")
        try:
            tree = ast.parse(
                source_path.read_text(encoding="utf-8"),
                filename=relative,
            )
        except (OSError, SyntaxError, UnicodeError) as exc:
            raise DependencyError(f"cannot parse repository module: {relative}") from exc
        path_to_module[relative] = module
        module_to_path[module] = relative
        sources[module] = (source_path, tree)

    modules = set(module_to_path)
    reverse: dict[str, set[str]] = defaultdict(set)
    for importer, (source_path, tree) in sources.items():
        package = _package_for(importer, source_path)
        dependencies: set[str] = set()
        importer_path = module_to_path[importer]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".", 1)[0] not in {"newsroom", "scripts"}:
                        continue
                    if alias.name not in modules:
                        raise DependencyError(
                            f"unresolved internal import in {importer_path}: {alias.name}"
                        )
                    dependencies.update(_known_prefixes(alias.name, modules))
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = _relative_module(package, node.level, node.module)
                else:
                    base = node.module or ""
                if not base or base.split(".", 1)[0] not in {"newsroom", "scripts"}:
                    continue
                base_prefixes = _known_prefixes(base, modules)
                if not base_prefixes:
                    raise DependencyError(
                        f"unresolved internal import in {importer_path}: {base}"
                    )
                dependencies.update(base_prefixes)
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    child = f"{base}.{alias.name}"
                    if child in modules:
                        dependencies.update(_known_prefixes(child, modules))
        for imported in dependencies - {importer}:
            reverse[imported].add(importer)

    return DependencyGraph(
        repo_root=root,
        path_to_module=path_to_module,
        module_to_path=module_to_path,
        reverse_importers={
            module: frozenset(importers)
            for module, importers in reverse.items()
        },
    )


def python_changes(paths: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                path
                for path in paths
                if not path.startswith("newsroom/tests/")
                and module_name_for_path(path)
            }
        )
    )
