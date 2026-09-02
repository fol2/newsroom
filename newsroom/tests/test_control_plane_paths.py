"""Canonical host paths for the operational Increment 4 authority."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from newsroom.control_plane import paths


def _canonical_paths(root: Path) -> tuple[Path, Path, Path]:
    return (
        root / "increment4_authority.sqlite3",
        root / "object_cas",
        root / "graphiti_workspaces",
    )


def test_increment4_paths_are_one_private_state_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "control-plane"
    authority, object_cas, workspaces = _canonical_paths(root)
    monkeypatch.setattr(paths, "HOST_CONTROL_PLANE_STATE_ROOT", root)
    monkeypatch.setattr(paths, "CANONICAL_INCREMENT4_AUTHORITY_STORE", authority)
    monkeypatch.setattr(paths, "CANONICAL_OBJECT_CAS_ROOT", object_cas)
    monkeypatch.setattr(paths, "CANONICAL_GRAPHITI_WORKSPACE_ROOT", workspaces)

    paths.ensure_increment4_state_paths()

    assert not authority.exists()
    assert root.is_dir()
    assert stat.S_IMODE(object_cas.stat().st_mode) == 0o700
    assert stat.S_IMODE(workspaces.stat().st_mode) == 0o700
    paths.require_canonical_increment4_authority_store(authority)
    paths.require_canonical_object_cas_root(object_cas)
    paths.require_canonical_graphiti_workspace_root(workspaces)


@pytest.mark.parametrize(
    ("require_canonical", "name"),
    [
        (paths.require_canonical_increment4_authority_store, "authority.sqlite3"),
        (paths.require_canonical_object_cas_root, "objects"),
        (paths.require_canonical_graphiti_workspace_root, "workspaces"),
    ],
)
def test_increment4_path_fences_reject_alternates_and_symlink_identity_conflicts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    require_canonical: object,
    name: str,
) -> None:
    root = tmp_path / "control-plane"
    root.mkdir()
    canonical = root / name
    canonical.mkdir() if canonical.suffix == "" else canonical.touch()
    alias = root / f"alias-{name}"
    alias.symlink_to(canonical, target_is_directory=canonical.is_dir())
    constant = {
        "authority.sqlite3": "CANONICAL_INCREMENT4_AUTHORITY_STORE",
        "objects": "CANONICAL_OBJECT_CAS_ROOT",
        "workspaces": "CANONICAL_GRAPHITI_WORKSPACE_ROOT",
    }[name]
    monkeypatch.setattr(paths, "HOST_CONTROL_PLANE_STATE_ROOT", root)
    monkeypatch.setattr(paths, constant, canonical)

    with pytest.raises(ValueError, match="canonical"):
        require_canonical(alias)  # type: ignore[operator]
    with pytest.raises(ValueError, match="canonical"):
        require_canonical(root / "nested" / ".." / name)  # type: ignore[operator]

    canonical.unlink() if canonical.is_file() else canonical.rmdir()
    elsewhere = tmp_path / f"elsewhere-{name}"
    elsewhere.mkdir() if canonical.suffix == "" else elsewhere.touch()
    canonical.symlink_to(elsewhere, target_is_directory=elsewhere.is_dir())
    with pytest.raises(ValueError, match="symlink"):
        require_canonical(canonical)  # type: ignore[operator]
