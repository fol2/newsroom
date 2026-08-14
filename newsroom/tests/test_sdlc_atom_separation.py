from __future__ import annotations

from pathlib import Path

import pytest

from scripts.sdlc.classify_change import ChangedPath, classify_paths
from scripts.sdlc.contracts import ContractError, load_contract


REPO_ROOT = Path(__file__).parents[2]
BASE_SHA = "0" * 40
HEAD_SHA = "1" * 40
BASE_TREE_SHA = "2" * 40
HEAD_TREE_SHA = "3" * 40


def _route(*paths: str) -> dict[str, object]:
    return classify_paths(
        load_contract(REPO_ROOT),
        tuple(ChangedPath(path) for path in paths),
        base_sha=BASE_SHA,
        head_sha=HEAD_SHA,
        base_tree_sha=BASE_TREE_SHA,
        head_tree_sha=HEAD_TREE_SHA,
    )


@pytest.mark.parametrize(
    ("control_path", "product_path"),
    (
        (".sdlc/gates.toml", "newsroom/increment7/search_authority.py"),
        (".github/workflows/evidence.yml", "scripts/write_run_job.py"),
        (
            "docs/specs/sdlc/high-performance-evidence-sdlc.md",
            "release/production.yml",
        ),
    ),
)
def test_global_control_and_product_implementation_require_separate_atoms(
    control_path: str,
    product_path: str,
) -> None:
    with pytest.raises(ContractError, match="separate delivery atoms"):
        _route(control_path, product_path)


def test_control_atom_can_carry_control_and_repository_tests() -> None:
    route = _route(
        ".sdlc/gates.toml",
        "scripts/sdlc/classify_change.py",
        "newsroom/tests/test_increment6g_final_closeout.py",
    )

    assert route["risk_tier"] == "R3_EXTERNAL_SERVICE_SECURITY"
    assert route["service_required"] is True


def test_product_implementation_can_carry_its_own_tests() -> None:
    route = _route(
        "newsroom/increment7/locality_qualification.py",
        "newsroom/tests/test_increment7e2_locality_no_activation.py",
    )

    assert route["core_required"] is True


def test_rename_between_control_and_product_is_rejected() -> None:
    contract = load_contract(REPO_ROOT)
    change = ChangedPath(
        ".sdlc/renamed-control.py",
        status="R100",
        old_path="newsroom/product_runtime.py",
    )

    with pytest.raises(ContractError, match="separate delivery atoms"):
        classify_paths(
            contract,
            (change,),
            base_sha=BASE_SHA,
            head_sha=HEAD_SHA,
            base_tree_sha=BASE_TREE_SHA,
            head_tree_sha=HEAD_TREE_SHA,
        )
