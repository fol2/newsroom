from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from typing import Iterable, Sequence

from . import focus_gate as legacy
from .classify_change import matches_repository_glob
from .dependencies import DependencyError, build_dependency_graph, module_name_for_path

CONTROL_PATTERNS = (
    ".sdlc/**",
    ".github/workflows/**",
    "scripts/sdlc/focus_gate.py",
    "scripts/sdlc/focus_gate_v2.py",
    "scripts/sdlc/focus_selector.py",
    "newsroom/tests/test_focus_gate.py",
    "newsroom/tests/test_focus_gate_hardening.py",
    "newsroom/tests/test_ci_workflow.py",
    "newsroom/tests/test_sdlc_contract.py",
    "newsroom/tests/test_sdlc_evidence_workflow.py",
)
CONTROL_TESTS = (
    "newsroom/tests/test_focus_gate.py",
    "newsroom/tests/test_focus_gate_hardening.py",
    "newsroom/tests/test_ci_workflow.py",
    "newsroom/tests/test_sdlc_contract.py",
    "newsroom/tests/test_sdlc_evidence_workflow.py",
    "newsroom/tests/test_pr_lifecycle.py",
)
RESEARCH_ONLY_PATTERNS = (
    "docs/research/**/*.json",
    "docs/research/**/*.csv",
    "scripts/graphiti_combined_temporal_extraction.py",
    "scripts/graphiti_deterministic_work.py",
    "scripts/graphiti_runtime_calibration.py",
    "newsroom/tests/test_graphiti_core_0293_*.py",
    "newsroom/tests/test_graphiti_sdk_no_tool_calibration.py",
    "newsroom/tests/test_graphiti_combined_temporal_*.py",
    "newsroom/tests/test_graphiti_donor_identities.py",
    "newsroom/tests/test_graphiti_deterministic_work.py",
)
RESEARCH_TRIGGER_PATTERNS = ("pyproject.toml", "uv.lock", *RESEARCH_ONLY_PATTERNS)
SERVICE_PATTERNS = (
    "newsroom/projection/neo4j/**",
    "newsroom/*neo4j*.py",
    "newsroom/**/*neo4j*.py",
    "newsroom/tests/test_*_neo4j_service.py",
)
STATEFUL_PATTERNS = (
    "newsroom/authority/**",
    "newsroom/integrated/**",
    "newsroom/projection/models.py",
    "newsroom/projection/policy.py",
    "newsroom/schemas/**",
    "newsroom/**/*migration*.py",
    "newsroom/**/*_migrations.py",
)
STATEFUL_SENTINELS = (
    "newsroom/tests/test_authority_migration_compatibility.py",
    "newsroom/tests/test_authority_store_conformance.py",
)
F4_PATTERNS = (
    "deploy/**",
    "release/**",
    ".github/workflows/deploy*.yml",
    ".github/workflows/release*.yml",
    "newsroom/production_admission/**",
    "scripts/production_operational_admission.py",
    "newsroom/**/*credential*.py",
    "newsroom/**/*keychain*.py",
)
SHARED_BREADTH_PATTERNS = ("pyproject.toml", "uv.lock", "newsroom/tests/conftest.py")
PREPARED_CANARY_PARITY_PATTERNS = (
    "newsroom/control_plane/cycle.py",
    "newsroom/control_plane/graphiti.py",
    "newsroom/control_plane/issue_790_disposition.py",
    "newsroom/control_plane/issue_790_canary.py",
    "newsroom/control_plane/issue_790_prepared_canary.py",
    "newsroom/control_plane/issue_790_rehearsal.py",
    "scripts/issue_790_live_canary_preflight.py",
    "scripts/issue_790_prepared_canary_rehearsal.py",
)
PREPARED_CANARY_PARITY_TESTS = (
    "newsroom/tests/test_issue_790_prepared_canary.py",
    "newsroom/tests/test_issue_790_prepared_canary_artifact.py",
    "newsroom/tests/test_issue_790_retry_forbidden_safety_state.py",
)
PREPARED_CANARY_CONSUMER_PATTERNS = (
    "newsroom/control_plane/issue_790_disposition.py",
    "newsroom/control_plane/issue_790_canary.py",
    "newsroom/control_plane/issue_790_prepared_canary.py",
    "newsroom/control_plane/issue_790_rehearsal.py",
    "scripts/issue_790_live_canary_preflight.py",
    "scripts/issue_790_prepared_canary_rehearsal.py",
)
PREPARED_CANARY_CONSUMER_TESTS = (
    "newsroom/tests/test_model_usage_receipts.py",
)
EXECUTABLE_SUFFIXES = frozenset(
    {".py", ".toml", ".json", ".yml", ".yaml", ".sh", ".bash", ".sql"}
)
IGNORED_IMPORT_ROOTS = frozenset({"newsroom", "scripts"})


def _matches(path: str, patterns: Iterable[str]) -> bool:
    return any(matches_repository_glob(path, pattern) for pattern in patterns)


def _matches_any(paths: Iterable[str], patterns: Iterable[str]) -> bool:
    return any(_matches(path, patterns) for path in paths)


def _is_documentation(path: str) -> bool:
    return path.endswith(".md") or (
        path.startswith("docs/") and Path(path).suffix.lower() not in EXECUTABLE_SUFFIXES
    )


def _is_research_only(path: str) -> bool:
    return _matches(path, RESEARCH_ONLY_PATTERNS)


def _triggers_research(path: str) -> bool:
    return _matches(path, RESEARCH_TRIGGER_PATTERNS)


def _is_test(path: str) -> bool:
    return path.startswith("newsroom/tests/test_") and path.endswith(".py")


def _is_service_test(path: str) -> bool:
    return _is_test(path) and path.endswith("_neo4j_service.py")


def _assignment_names(target: ast.expr) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        return {name for item in target.elts for name in _assignment_names(item)}
    return set()


def _literal_string_set(value: ast.expr) -> set[str] | None:
    if not isinstance(value, (ast.List, ast.Tuple, ast.Set)):
        return None
    values: set[str] = set()
    for item in value.elts:
        if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
            return None
        values.add(item.value)
    return values


def _defined_names(path: Path) -> set[str]:
    """Return exact top-level public symbols, including short names/constants."""

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError):
        return set()
    names: set[str] = set()
    declared_all: set[str] | None = None
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            assigned = {name for target in node.targets for name in _assignment_names(target)}
            names.update(assigned)
            if "__all__" in assigned:
                literal = _literal_string_set(node.value)
                if literal is not None:
                    declared_all = literal
        elif isinstance(node, ast.AnnAssign):
            names.update(_assignment_names(node.target))
    public = {name for name in names if not name.startswith("_")}
    return public if declared_all is None else public & declared_all


def _changed_public_symbols(repo_root: Path, path: str, base_sha: str, head_sha: str) -> set[str] | None:
    def source(revision: str) -> bytes | None:
        try:
            result = subprocess.run(
                ("git", "show", f"{revision}:{path}"), cwd=repo_root, capture_output=True,
            )
        except OSError:
            return None
        return result.stdout if result.returncode == 0 else None

    before, after = source(base_sha), source(head_sha)
    if before is None or after is None:
        return None
    try:
        old_tree = ast.parse(before, filename=path)
        new_tree = ast.parse(after, filename=path)
    except (SyntaxError, UnicodeError):
        return None

    kinds = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    old_defs = {node.name: node for node in old_tree.body if isinstance(node, kinds)}
    new_defs = {node.name: node for node in new_tree.body if isinstance(node, kinds)}
    if old_defs.keys() != new_defs.keys() or [
        ast.dump(node) for node in old_tree.body if not isinstance(node, kinds)
    ] != [ast.dump(node) for node in new_tree.body if not isinstance(node, kinds)]:
        return None
    changed = {name for name in old_defs if ast.dump(old_defs[name]) != ast.dump(new_defs[name])}
    if not changed or any(name.startswith("_") for name in changed):
        return None
    while True:
        callers = {
            name for name, node in new_defs.items()
            if any(isinstance(item, ast.Name) and item.id in changed for item in ast.walk(node))
        }
        expanded = changed | callers
        if expanded == changed:
            if any(
                isinstance(item, ast.Name) and item.id in changed
                for node in new_tree.body if not isinstance(node, kinds)
                for item in ast.walk(node)
            ):
                return None
            return changed
        changed = expanded


def _imports_module(imported: str, selected: str) -> bool:
    if imported in IGNORED_IMPORT_ROOTS or selected in IGNORED_IMPORT_ROOTS:
        return False
    return imported == selected or imported.startswith(selected + ".")


def _attribute_chain(node: ast.AST) -> tuple[str, ...] | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return tuple(reversed(parts))


def _imported_from(node: ast.ImportFrom, importer: str | None) -> str | None:
    if not node.level:
        return node.module
    if importer is None:
        return None
    parts = importer.rpartition(".")[0].split(".")
    base = parts[: len(parts) - node.level + 1]
    return ".".join((*base, *(node.module.split(".") if node.module else ())))


def _imports_public_symbol(
    tree: ast.AST, package: str, symbols: set[str], importer: str | None = None
) -> bool:
    if not symbols:
        return False
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and _imported_from(node, importer) == package:
            if any(alias.name == "*" or alias.name in symbols for alias in node.names):
                return True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == package:
                    aliases.add(alias.asname or alias.name.split(".")[0])
    package_parts = tuple(package.split("."))
    for node in ast.walk(tree):
        chain = _attribute_chain(node)
        if not chain or chain[-1] not in symbols:
            continue
        if chain[:-1] == package_parts:
            return True
        if len(chain) == 2 and chain[0] in aliases:
            return True
    return False


def _imports_changed_surface(
    tree: ast.AST, module: str, symbols: set[str], importer: str | None = None
) -> bool:
    parent, _, leaf = module.rpartition(".")
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call) and node.args
            and isinstance(node.args[0], ast.Constant) and node.args[0].value == module
        ):
            return True
        if isinstance(node, ast.Import) and any(alias.name == module for alias in node.names):
            return True
        if isinstance(node, ast.ImportFrom):
            if node.level:
                if importer is None:
                    return True
            imported_from = _imported_from(node, importer)
            if imported_from == parent and any(alias.name == leaf for alias in node.names):
                return True
            if imported_from == module and any(
                alias.name == "*" or alias.name in symbols for alias in node.names
            ):
                return True
    return False


def _discover_tests(
    repo_root: Path,
    source_paths: Sequence[str],
    *,
    base_sha: str = "0" * 40,
    head_sha: str = "1" * 40,
) -> tuple[set[str], bool]:
    direct: set[str] = set()
    dependents: set[str] = set()
    reexports: set[str] = set()
    direct_symbols: dict[str, set[str] | None] = {}
    unresolved = False
    try:
        graph = build_dependency_graph(repo_root)
    except DependencyError:
        graph = None
        unresolved = True

    def retain(relative: str) -> None:
        selected = module_name_for_path(relative)
        if selected is not None:
            (reexports if relative.endswith("/__init__.py") else dependents).add(selected)

    for relative in source_paths:
        module = module_name_for_path(relative)
        if module is None:
            continue
        direct.add(module)
        symbols = _changed_public_symbols(repo_root, relative, base_sha, head_sha)
        direct_symbols[module] = symbols
        if graph is None:
            continue
        if symbols is None or not hasattr(graph, "reverse_importers"):
            try:
                for nested in graph.dependent_paths(relative):
                    retain(nested)
            except DependencyError:
                unresolved = True
            continue
        importers = graph.reverse_importers.get(module, frozenset())
        for importer in importers:
            importer_path = graph.module_to_path.get(importer)
            if importer_path is None:
                continue
            if symbols is not None:
                try:
                    tree = ast.parse((repo_root / importer_path).read_text(encoding="utf-8"))
                except (OSError, SyntaxError, UnicodeError):
                    unresolved = True
                    continue
                if not _imports_changed_surface(
                    tree, module, symbols,
                    importer=None if importer_path.endswith('/__init__.py') else importer,
                ):
                    continue
            retain(importer_path)
            try:
                for nested in graph.dependent_paths(importer_path):
                    retain(nested)
            except DependencyError:
                unresolved = True
    symbols: set[str] = set()
    for relative in source_paths:
        path = repo_root / relative
        if path.is_file() and not path.is_symlink():
            symbols.update(_defined_names(path))
    selected: set[str] = set()
    for path in legacy._test_files(repo_root):
        relative = path.relative_to(repo_root).as_posix()
        if _is_research_only(relative):
            continue
        importer = module_name_for_path(relative)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
            imports = legacy._imported_modules(tree, importer=importer)
        except (OSError, SyntaxError, UnicodeError, DependencyError):
            unresolved = True
            continue
        direct_hit = any(
            (
                _imports_changed_surface(tree, module, direct_symbols[module], importer)
                if direct_symbols[module] is not None
                else any(_imports_module(imported, module) for imported in imports)
            )
            for module in direct
        )
        dependent_hit = any(
            _imports_module(imported, module)
            for imported in imports
            for module in dependents
        )
        reexport_hit = any(
            _imports_public_symbol(
                tree, package, symbols, module_name_for_path(relative)
            ) for package in reexports
        )
        if direct_hit or dependent_hit or reexport_hit:
            selected.add(relative)
    return selected, unresolved


def select_focus(
    paths: Iterable[str],
    *,
    repo_root: str | Path | None = None,
    base_sha: str = "0" * 40,
    head_sha: str = "1" * 40,
    base_tree_sha: str = "2" * 40,
    head_tree_sha: str = "3" * 40,
) -> dict[str, object]:
    root = None if repo_root is None else Path(repo_root).resolve()
    changed = tuple(sorted(set(paths)))
    if not changed:
        raise legacy.FocusGateError("a Focus Gate route requires at least one changed path")

    reasons: set[str] = set()
    gates = {"F0"}
    tests: set[str] = set()
    service_tests: set[str] = set()
    executable = [path for path in changed if not _is_documentation(path)]
    source_paths = [
        path
        for path in changed
        if path.endswith(".py")
        and path.startswith(("newsroom/", "scripts/"))
        and not _is_test(path)
    ]
    research_paths = [path for path in executable if _is_research_only(path)]
    normal_executable = [path for path in executable if not _is_research_only(path)]
    research_required = any(_triggers_research(path) for path in changed)
    research_only = bool(research_paths) and not normal_executable
    full_health_required = _matches_any(changed, SHARED_BREADTH_PATTERNS)
    owner_required = _matches_any(changed, F4_PATTERNS)
    service_required = _matches_any(changed, SERVICE_PATTERNS)
    stateful_required = _matches_any(changed, STATEFUL_PATTERNS)
    control_required = _matches_any(changed, CONTROL_PATTERNS)

    if all(_is_documentation(path) for path in changed):
        reasons.add("documentation_only:F0")
    if research_required:
        reasons.add("research_inputs_changed:isolated_lane")
    if normal_executable:
        gates.add("F1")
        reasons.add("executable_change:F1")
    if stateful_required or control_required:
        gates.add("F2")
        reasons.add("stateful_contract:F2" if stateful_required else "sdlc_control:F2")
    if service_required:
        gates.add("F3")
        reasons.add("actual_neo4j_semantics:F3")
    if owner_required:
        gates.add("F4")
        reasons.add("irreversible_or_public_effect:F4")

    for path in changed:
        if _is_test(path) and not _is_research_only(path):
            (service_tests if _is_service_test(path) else tests).add(path)
    if control_required:
        tests.update(legacy._existing(root, CONTROL_TESTS))

    if source_paths and not research_only and root is not None:
        discovered, unresolved = _discover_tests(
            root, source_paths, base_sha=base_sha, head_sha=head_sha
        )
        for path in discovered:
            (service_tests if _is_service_test(path) else tests).add(path)
        if discovered:
            gates.add("F2")
            reasons.add("repository_import_or_symbol_consumers:F2")
        if unresolved:
            full_health_required = True
            reasons.add("unresolved_dependency_analysis:full_health")

    if _matches_any(changed, PREPARED_CANARY_PARITY_PATTERNS):
        tests.update(legacy._existing(root, PREPARED_CANARY_PARITY_TESTS))
        gates.add("F1")
        reasons.add("prepared_canary_parity:F1")
    if _matches_any(changed, PREPARED_CANARY_CONSUMER_PATTERNS):
        tests.update(legacy._existing(root, PREPARED_CANARY_CONSUMER_TESTS))
        gates.add("F2")
        reasons.add("prepared_canary_consumers:F2")
    if stateful_required:
        if not (tests or service_tests):
            full_health_required = True
            reasons.add("stateful_without_direct_evidence:full_health")
        tests.update(legacy._existing(root, STATEFUL_SENTINELS))
        reasons.add("bounded_stateful_sentinels:F2")
    if service_tests:
        service_required = True
        gates.add("F3")
        reasons.add("actual_service_consumer:F3")
    if service_required and not service_tests:
        service_tests.update(legacy._glob_tests(root, ("test_*_neo4j_service.py",)))
        reasons.add("service_fallback_inventory:F3")

    known_roots = ("newsroom/", "scripts/", "docs/", ".github/", ".sdlc/")
    unknown = [
        path
        for path in normal_executable
        if not path.startswith(known_roots) and path not in {"pyproject.toml", "uv.lock"}
    ]
    if unknown:
        full_health_required = True
        reasons.add("unknown_executable_path:full_health")

    tests = legacy._existing(root, tests)
    service_tests = legacy._existing(root, service_tests)
    if normal_executable and not research_only and not (
        tests or service_tests or full_health_required
    ):
        full_health_required = True
        reasons.add("no_defensible_focused_test:full_health")
    if full_health_required:
        gates.update({"F1", "F2"})
        reasons.add("cross_cutting_or_unresolved:full_health")

    yaml_bootstrap = any(Path(path).suffix.lower() in {".yml", ".yaml"} for path in executable)
    if research_only:
        tests.clear()
        service_tests.clear()
        full_health_required = False
        service_required = False
        gates = {"F0"}
    bootstrap = bool(tests or service_tests or full_health_required or service_required or yaml_bootstrap)
    body = legacy._manifest_without_digest(
        changed=changed,
        base_sha=base_sha,
        head_sha=head_sha,
        base_tree_sha=base_tree_sha,
        head_tree_sha=head_tree_sha,
        gates=sorted(gates),
        tests=sorted(tests),
        service_tests=sorted(service_tests),
        research_required=research_required,
        full_health_required=full_health_required,
        owner_authority_required=owner_required,
        bootstrap_required=bootstrap,
        reasons=sorted(reasons),
    )
    return {**body, "manifest_digest": legacy._digest(body)}
