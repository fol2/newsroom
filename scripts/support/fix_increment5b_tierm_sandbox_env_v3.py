"""Verify the Tier-M sandbox repair on an immutable local commit before push."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from scripts.support import fix_increment5b_tierm_sandbox_env as repair


def verify_and_publish(root: Path) -> None:
    repair.run("uv", "lock", "--check", cwd=root)
    repair.run("uv", "sync", "--dev", "--locked", cwd=root)
    repair.run("git", "config", "user.name", "James To", cwd=root)
    repair.run(
        "git",
        "config",
        "user.email",
        "105634418+fol2@users.noreply.github.com",
        cwd=root,
    )
    repair.run("git", "add", "--", *repair.PRODUCT_FILES, cwd=root)
    repair.run("git", "diff", "--cached", "--check", cwd=root)
    actual = tuple(
        filter(
            None,
            repair.run(
                "git", "diff", "--cached", "--name-only", cwd=root, capture=True
            ).splitlines(),
        )
    )
    if tuple(sorted(actual)) != tuple(sorted(repair.PRODUCT_FILES)):
        raise SystemExit(f"product inventory drifted: {actual}")
    repair.run(
        "git",
        "commit",
        "-q",
        "-m",
        "SDLC: pass explicit Neo4j credentials into service sandbox",
        cwd=root,
    )

    focused = (
        "newsroom/tests/test_increment5b_tierm_service_reconciliation.py",
        "newsroom/tests/test_sdlc_workflow_lane.py::test_static_environment_excludes_ambient_secrets",
        "newsroom/tests/test_sdlc_workflow_lane.py::test_service_lane_requires_route_and_passes_only_explicit_projector_secrets",
        "newsroom/tests/test_sdlc_workflow_lane.py::test_optional_core_skips_are_exact_actual_service_cases",
        "newsroom/tests/test_integrated_c1_sdlc_contract.py::test_complete_actual_service_cases_are_optional_only_in_core",
    )
    with repair.FOCUSED_LOG.open("w", encoding="utf-8") as stream:
        subprocess.run(
            ("uv", "run", "pytest", "-q", *focused),
            cwd=root,
            check=True,
            text=True,
            stdout=stream,
        )
    with repair.FULL_LOG.open("w", encoding="utf-8") as stream:
        subprocess.run(
            ("uv", "run", "pytest", "-q"),
            cwd=root,
            check=True,
            text=True,
            stdout=stream,
        )

    head = repair.run("git", "rev-parse", "HEAD", cwd=root, capture=True)
    tree = repair.run("git", "rev-parse", "HEAD^{tree}", cwd=root, capture=True)
    if repair.run("git", "status", "--porcelain", cwd=root, capture=True):
        raise SystemExit("verified product tree is not clean")
    for branch in (repair.PRODUCT_BRANCH, repair.CHECKPOINT_BRANCH):
        repair.run("git", "push", "origin", f"HEAD:refs/heads/{branch}", cwd=root)
    repair.RECEIPT.write_text(
        "\n".join(
            (
                "schema=newsroom.increment5b.tierm-sandbox-repair.v2",
                f"parent={repair.EXPECTED_HEAD}",
                f"head={head}",
                f"tree={tree}",
                f"focused={repair.FOCUSED_LOG.read_text(encoding='utf-8').splitlines()[-1]}",
                f"full={repair.FULL_LOG.read_text(encoding='utf-8').splitlines()[-1]}",
                "files=3",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    print(repair.RECEIPT.read_text(encoding="utf-8"), end="")


if __name__ == "__main__":
    repair.EXPECTED_HEAD = "ad2d2b324d148a798433ad8bec4adeaf92f3a621"
    repair.verify_and_publish = verify_and_publish
    repair.main()
