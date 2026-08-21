"""Host-level Control Plane state paths shared by every checkout."""

from __future__ import annotations

from pathlib import Path


def _canonical_state_root(home: Path) -> Path:
    legacy = home / "Coding" / "newsroom" / "data" / "newsroom"
    fresh = home / ".local" / "share" / "newsroom"
    legacy_pair = (
        legacy / "proving_store.sqlite3",
        legacy / "unpublished_store.sqlite3",
    )
    fresh_pair = (
        fresh / "proving_store.sqlite3",
        fresh / "unpublished_store.sqlite3",
    )
    legacy_present = tuple(path.exists() for path in legacy_pair)
    fresh_present = tuple(path.exists() for path in fresh_pair)
    if any(legacy_present) and not all(legacy_present):
        raise RuntimeError(
            "legacy Control Plane store pair is incomplete; refusing a split authority"
        )
    if any(fresh_present) and not all(fresh_present):
        if any(legacy_present):
            raise RuntimeError(
                "fresh Control Plane store pair is incomplete beside legacy state; "
                "refusing a split authority"
            )
        return fresh
    if all(legacy_present) and all(fresh_present):
        if all(
            legacy_path.samefile(fresh_path)
            for legacy_path, fresh_path in zip(
                legacy_pair, fresh_pair, strict=True
            )
        ):
            return legacy
        raise RuntimeError(
            "multiple Control Plane store pairs exist; refusing ambiguous authority"
        )
    if all(legacy_present):
        return legacy
    return fresh


HOST_CONTROL_PLANE_STATE_ROOT = _canonical_state_root(Path.home())
CANONICAL_PROVING_STORE = HOST_CONTROL_PLANE_STATE_ROOT / "proving_store.sqlite3"
CANONICAL_UNPUBLISHED_STORE = (
    HOST_CONTROL_PLANE_STATE_ROOT / "unpublished_store.sqlite3"
)


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    path.chmod(0o700)


def ensure_control_plane_state_root() -> None:
    if HOST_CONTROL_PLANE_STATE_ROOT == Path.home() / ".local" / "share" / "newsroom":
        _ensure_private_directory(HOST_CONTROL_PLANE_STATE_ROOT)


def _require_canonical_store(*, supplied: str, canonical: Path, label: str) -> None:
    if Path(supplied).resolve() != canonical.resolve():
        raise ValueError(f"real Graphiti requires the canonical {label} store")


def require_canonical_proving_store(path: str) -> None:
    _require_canonical_store(
        supplied=path,
        canonical=CANONICAL_PROVING_STORE,
        label="proving",
    )


def require_canonical_unpublished_store(path: str) -> None:
    _require_canonical_store(
        supplied=path,
        canonical=CANONICAL_UNPUBLISHED_STORE,
        label="unpublished",
    )


__all__ = [
    "CANONICAL_PROVING_STORE",
    "CANONICAL_UNPUBLISHED_STORE",
    "HOST_CONTROL_PLANE_STATE_ROOT",
    "ensure_control_plane_state_root",
    "require_canonical_proving_store",
    "require_canonical_unpublished_store",
]
