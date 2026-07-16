from __future__ import annotations

import ast
from pathlib import Path


def test_non_authority_application_modules_do_not_import_private_authority_modules() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    newsroom_root = repository_root / "newsroom"
    violations: list[str] = []
    for path in newsroom_root.rglob("*.py"):
        relative = path.relative_to(repository_root)
        if "authority" in relative.parts or "tests" in relative.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeError) as exc:
            violations.append(f"{relative}: unreadable: {exc}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("newsroom.authority._"):
                    violations.append(f"{relative}:{node.lineno}: {node.module}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("newsroom.authority._"):
                        violations.append(f"{relative}:{node.lineno}: {alias.name}")
    assert not violations, "private authority boundary imports: " + "; ".join(violations)
