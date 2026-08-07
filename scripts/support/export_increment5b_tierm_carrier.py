"""Export the exact tested Increment 5B Tier-M blobs through a harmless carrier."""
from __future__ import annotations

import sys
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from scripts.support import repair_increment5b_tierm_v5 as v5

EXPECTED_TESTED_TREE = "ba01421317612897dc48e167cb49a083398763a0"
CARRIER_BRANCH = "support/carrier-increment5b-tierm-reconciliation-20260807"
CHECKPOINT_BRANCH = "checkpoint/carrier-increment5b-tierm-reconciliation-20260807"
CARRIER_WORKFLOW_PATH = "scripts/support/exported_increment5b_tierm_evidence.yml"
PRODUCT_PATHS = (
    ".github/workflows/evidence.yml",
    "newsroom/tests/test_increment5b_tierm_service_reconciliation.py",
    "newsroom/tests/test_integrated_c1_sdlc_contract.py",
    "newsroom/tests/test_sdlc_workflow_lane.py",
    "scripts/sdlc/workflow_lane.py",
)
CARRIER_PATHS = (
    CARRIER_WORKFLOW_PATH,
    "newsroom/tests/test_increment5b_tierm_service_reconciliation.py",
    "newsroom/tests/test_integrated_c1_sdlc_contract.py",
    "newsroom/tests/test_sdlc_workflow_lane.py",
    "scripts/sdlc/workflow_lane.py",
)
RECEIPT = Path("/tmp/increment5b-tierm-carrier-receipt.txt")


def main() -> None:
    v5.base.FIRST, v5.base.SECOND = tuple(sorted((v5.base.FIRST, v5.base.SECOND)))
    v5.base.configure_auth()
    product = Path("product")
    v5.base.checkout_product(product)
    v5.patch(product)

    v5.base.run("git", "add", "--", *PRODUCT_PATHS, cwd=product)
    v5.base.run("git", "diff", "--cached", "--check", cwd=product)
    tested_tree = v5.base.run("git", "write-tree", cwd=product, capture=True)
    tested_paths = tuple(
        line
        for line in v5.base.run(
            "git", "diff", "--cached", "--name-only", cwd=product, capture=True
        ).splitlines()
        if line
    )
    if tested_tree != EXPECTED_TESTED_TREE:
        raise SystemExit(
            f"tested tree drifted: expected={EXPECTED_TESTED_TREE} actual={tested_tree}"
        )
    if tuple(sorted(tested_paths)) != tuple(sorted(PRODUCT_PATHS)):
        raise SystemExit(f"tested product inventory drifted: {tested_paths}")

    workflow = product / ".github/workflows/evidence.yml"
    carrier = product / CARRIER_WORKFLOW_PATH
    carrier.parent.mkdir(parents=True, exist_ok=True)
    carrier.write_bytes(workflow.read_bytes())
    v5.base.run("git", "restore", "--staged", ":/", cwd=product)
    v5.base.run("git", "restore", ".github/workflows/evidence.yml", cwd=product)

    v5.base.run("git", "config", "user.name", "James To", cwd=product)
    v5.base.run(
        "git",
        "config",
        "user.email",
        "105634418+fol2@users.noreply.github.com",
        cwd=product,
    )
    v5.base.run("git", "add", "--", *CARRIER_PATHS, cwd=product)
    v5.base.run("git", "diff", "--cached", "--check", cwd=product)
    actual = tuple(
        line
        for line in v5.base.run(
            "git", "diff", "--cached", "--name-only", cwd=product, capture=True
        ).splitlines()
        if line
    )
    if tuple(sorted(actual)) != tuple(sorted(CARRIER_PATHS)):
        raise SystemExit(f"carrier inventory drifted: {actual}")
    if v5.base.run(
        "git", "diff", "--cached", "--name-only", "--", ".github/workflows", cwd=product, capture=True
    ):
        raise SystemExit("carrier still changes a permanent workflow path")

    v5.base.run(
        "git",
        "commit",
        "-q",
        "-m",
        "Support: carry exact tested Increment 5B Tier-M blobs",
        cwd=product,
    )
    carrier_head = v5.base.run("git", "rev-parse", "HEAD", cwd=product, capture=True)
    carrier_tree = v5.base.run("git", "rev-parse", "HEAD^{tree}", cwd=product, capture=True)

    for branch in (CARRIER_BRANCH, CHECKPOINT_BRANCH):
        v5.base.run(
            "git", "push", "--force", "origin", f"HEAD:refs/heads/{branch}", cwd=product
        )

    mapping = {
        ".github/workflows/evidence.yml": v5.base.run(
            "git", "hash-object", CARRIER_WORKFLOW_PATH, cwd=product, capture=True
        ),
        "newsroom/tests/test_increment5b_tierm_service_reconciliation.py": v5.base.run(
            "git", "hash-object", "newsroom/tests/test_increment5b_tierm_service_reconciliation.py", cwd=product, capture=True
        ),
        "newsroom/tests/test_integrated_c1_sdlc_contract.py": v5.base.run(
            "git", "hash-object", "newsroom/tests/test_integrated_c1_sdlc_contract.py", cwd=product, capture=True
        ),
        "newsroom/tests/test_sdlc_workflow_lane.py": v5.base.run(
            "git", "hash-object", "newsroom/tests/test_sdlc_workflow_lane.py", cwd=product, capture=True
        ),
        "scripts/sdlc/workflow_lane.py": v5.base.run(
            "git", "hash-object", "scripts/sdlc/workflow_lane.py", cwd=product, capture=True
        ),
    }
    lines = [
        "schema=newsroom.increment5b.tier-m-carrier.v1",
        f"parent={v5.base.EXPECTED_BASE}",
        f"tested_tree={tested_tree}",
        f"carrier_head={carrier_head}",
        f"carrier_tree={carrier_tree}",
    ]
    lines.extend(f"blob[{path}]={sha}" for path, sha in mapping.items())
    RECEIPT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(RECEIPT.read_text(encoding="utf-8"), end="")


if __name__ == "__main__":
    main()
