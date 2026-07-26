from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_PRODUCTION_ROOT = _REPOSITORY_ROOT / "newsroom"

SourceSnapshotEntry = tuple[Path, bytes | None, str | None]
SourceSnapshot = tuple[SourceSnapshotEntry, ...]
ImportInventoryEntry = tuple[Path, tuple[tuple[int, str], ...], str | None]
ImportInventory = tuple[ImportInventoryEntry, ...]


def _production_source_snapshot() -> SourceSnapshot:
    """Capture the exact production-source paths and bytes for cache identity."""

    snapshot: list[SourceSnapshotEntry] = []
    for path in sorted(_PRODUCTION_ROOT.rglob("*.py")):
        relative = path.relative_to(_REPOSITORY_ROOT)
        if "tests" in relative.parts or "__pycache__" in relative.parts:
            continue
        try:
            snapshot.append((relative, path.read_bytes(), None))
        except OSError as exc:
            snapshot.append(
                (relative, None, f"{type(exc).__name__}: {exc}")
            )
    return tuple(snapshot)


@lru_cache(maxsize=2)
def _inventory_from_snapshot(snapshot: SourceSnapshot) -> ImportInventory:
    """Parse one immutable, exact-byte source snapshot.

    The snapshot itself is the cache key.  A production path or byte change
    therefore cannot reuse import facts derived from an earlier repository
    state, while boundary tests in the same pytest process avoid repeating the
    comparatively expensive AST walk over identical source.
    """

    inventory: list[ImportInventoryEntry] = []
    for relative, source_bytes, read_error in snapshot:
        if read_error is not None or source_bytes is None:
            inventory.append((relative, (), read_error or "source is absent"))
            continue
        try:
            source = source_bytes.decode("utf-8")
            tree = ast.parse(source, filename=str(relative))
        except (SyntaxError, UnicodeError) as exc:
            inventory.append((relative, (), f"{type(exc).__name__}: {exc}"))
            continue
        imports: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.append((node.lineno, node.module))
            elif isinstance(node, ast.Import):
                imports.extend((node.lineno, alias.name) for alias in node.names)
        inventory.append(
            (
                relative,
                tuple(sorted(imports, key=lambda item: (item[0], item[1]))),
                None,
            )
        )
    return tuple(inventory)


def production_import_inventory() -> ImportInventory:
    """Return exact-source-bound immutable import facts for production code."""

    return _inventory_from_snapshot(_production_source_snapshot())


__all__ = [
    "ImportInventory",
    "SourceSnapshot",
    "_inventory_from_snapshot",
    "production_import_inventory",
]
