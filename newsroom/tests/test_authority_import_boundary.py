from __future__ import annotations

from pathlib import Path

from .source_import_inventory import (
    _inventory_from_snapshot,
    production_import_inventory,
)


def test_non_authority_application_modules_do_not_import_private_authority_modules() -> None:
    violations: list[str] = []
    for relative, imports, parse_error in production_import_inventory():
        if "authority" in relative.parts:
            continue
        if parse_error is not None:
            violations.append(f"{relative}: unreadable: {parse_error}")
            continue
        for lineno, module in imports:
            if module.startswith("newsroom.authority._"):
                violations.append(f"{relative}:{lineno}: {module}")
    assert not violations, "private authority boundary imports: " + "; ".join(violations)


def test_import_inventory_cache_is_bound_to_exact_source_bytes() -> None:
    path = Path("newsroom/example.py")
    first = ((path, b"import os\n", None),)
    second = ((path, b"import sys\n", None),)

    first_inventory = _inventory_from_snapshot(first)
    assert first_inventory is _inventory_from_snapshot(first)
    assert first_inventory[0][1] == ((1, "os"),)
    assert _inventory_from_snapshot(second)[0][1] == ((1, "sys"),)
    assert _inventory_from_snapshot(second) != first_inventory
