from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from . import _classify_change_base as _base
from .contracts import SdlcContract


SCHEMA_VERSION = _base.SCHEMA_VERSION
RISK_CLASSIFIER_VERSION = _base.RISK_CLASSIFIER_VERSION
GitRouteError = _base.GitRouteError
ChangedPath = _base.ChangedPath
canonical_json_bytes = _base.canonical_json_bytes
sha256_identity = _base.sha256_identity
matches_repository_glob = _base.matches_repository_glob
resolve_commit = _base.resolve_commit
resolve_tree = _base.resolve_tree
verify_exact_clean_checkout = _base.verify_exact_clean_checkout
parse_name_status = _base.parse_name_status
changed_paths = _base.changed_paths

_CONTROL_PRODUCT_ATOM_ERROR = (
    "global SDLC control changes and non-test product implementation "
    "must be separate delivery atoms"
)


def _is_non_test_product_implementation(path: str) -> bool:
    if path.startswith("newsroom/"):
        return not path.startswith("newsroom/tests/")
    if path.startswith("scripts/"):
        return not path.startswith("scripts/sdlc/")
    return path.startswith(("deploy/", "release/"))


def _require_control_product_atom_separation(
    contract: SdlcContract,
    changes: tuple[ChangedPath, ...],
) -> None:
    has_control = False
    has_product_implementation = False
    for change in changes:
        for path in change.classified_paths():
            groups = _base._matching_groups(contract, path)
            has_control = has_control or "contract_control" in groups
            has_product_implementation = (
                has_product_implementation
                or _is_non_test_product_implementation(path)
            )
    if has_control and has_product_implementation:
        raise _base.ContractError(_CONTROL_PRODUCT_ATOM_ERROR)


_original_classify_paths = _base.classify_paths


def classify_paths(
    contract: SdlcContract,
    changes: Iterable[ChangedPath],
    *,
    base_sha: str,
    head_sha: str,
    base_tree_sha: str,
    head_tree_sha: str,
) -> dict[str, object]:
    normalized_changes = tuple(changes)
    _require_control_product_atom_separation(contract, normalized_changes)
    return _original_classify_paths(
        contract,
        normalized_changes,
        base_sha=base_sha,
        head_sha=head_sha,
        base_tree_sha=base_tree_sha,
        head_tree_sha=head_tree_sha,
    )


_base.classify_paths = classify_paths
build_git_route = _base.build_git_route
main = _base.main


def __getattr__(name: str) -> Any:
    return getattr(_base, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_base)))


if __name__ == "__main__":
    raise SystemExit(main())
