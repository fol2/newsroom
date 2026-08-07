"""Build and verify the bounded Increment 5B Tier-M service reconciliation atom."""
from __future__ import annotations

import base64
import os
from pathlib import Path
import shutil
import subprocess

REPOSITORY = "fol2/newsroom"
EXPECTED_BASE = "88d1b14b41354f56f325d173d0021ad0fd20abc2"
PRODUCT_BRANCH = "agent/increment-5b-tierm-service-reconciliation"
CHECKPOINT_BRANCH = "checkpoint/increment-5b-tierm-service-reconciliation-20260807"
FOCUSED_LOG = Path("/tmp/increment5b-tierm-reconciliation-focused.log")
FULL_LOG = Path("/tmp/increment5b-tierm-reconciliation-full.log")
RECEIPT = Path("/tmp/increment5b-tierm-reconciliation-receipt.txt")
FILES = (
    ".github/workflows/evidence.yml",
    "newsroom/tests/test_increment5b_tierm_service_reconciliation.py",
    "scripts/sdlc/workflow_lane.py",
)
FIRST = (
    "newsroom.tests.test_increment5b4_neo4j_service::"
    "test_increment5b4_fixed_port_reads_only_exact_generation_and_allowed_state"
)
SECOND = (
    "newsroom.tests.test_increment5b4_neo4j_service::"
    "test_increment5b4_fixed_port_excludes_future_observations"
)


def run(*args: str, cwd: Path | None = None, capture: bool = False) -> str:
    completed = subprocess.run(
        args,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return completed.stdout.strip() if capture else ""


def run_logged(args: tuple[str, ...], *, cwd: Path, log: Path) -> str:
    completed = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = completed.stdout or ""
    log.write_text(output, encoding="utf-8")
    print(output, end="")
    if completed.returncode:
        raise subprocess.CalledProcessError(completed.returncode, args, output=output)
    lines = output.splitlines()
    return lines[-1] if lines else ""


def configure_auth() -> None:
    token = os.environ["GH_TOKEN"]
    encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    run(
        "git",
        "config",
        "--global",
        "http.https://github.com/.extraheader",
        f"AUTHORIZATION: basic {encoded}",
    )


def checkout_product(product: Path) -> None:
    if product.exists():
        shutil.rmtree(product)
    product.mkdir()
    run("git", "init", "-q", cwd=product)
    run("git", "remote", "add", "origin", f"https://github.com/{REPOSITORY}.git", cwd=product)
    run(
        "git",
        "fetch",
        "--no-tags",
        "--depth=1",
        "origin",
        "refs/heads/main:refs/remotes/origin/main",
        cwd=product,
    )
    run("git", "checkout", "-q", "--detach", EXPECTED_BASE, cwd=product)
    actual = run("git", "ls-remote", "origin", "refs/heads/main", cwd=product, capture=True).split()[0]
    if actual != EXPECTED_BASE:
        raise SystemExit(f"main moved: expected={EXPECTED_BASE} actual={actual}")


def patch(product: Path) -> None:
    lane = product / "scripts/sdlc/workflow_lane.py"
    evidence = product / ".github/workflows/evidence.yml"
    regression = product / "newsroom/tests/test_increment5b_tierm_service_reconciliation.py"

    lane_text = lane.read_text(encoding="utf-8")
    if FIRST in lane_text or SECOND in lane_text:
        raise SystemExit("5B4 optional-core identities already exist")
    start = lane_text.index("_OPTIONAL_CORE_TEST_IDS = (")
    end = lane_text.index("\n)\n_SERVICE_CONFIGURATION", start)
    insertion = f"\n    {FIRST!r},\n    {SECOND!r},"
    lane.write_text(lane_text[:end] + insertion + lane_text[end:], encoding="utf-8")

    evidence_text = evidence.read_text(encoding="utf-8")
    anchor = (
        '          set -a\n'
        '          source "${projector_file}"\n'
        '          set +a\n'
        '          uv run --no-sync python -m scripts.sdlc.workflow_lane execute \\\n'
    )
    replacement = (
        '          set -a\n'
        '          source "${projector_file}"\n'
        '          set +a\n'
        '          export NEWSROOM_NEO4J_USER="${NEWSROOM_NEO4J_PROJECTOR_USERNAME}"\n'
        '          export NEWSROOM_NEO4J_PASSWORD="${NEWSROOM_NEO4J_PROJECTOR_PASSWORD}"\n'
        '          uv run --no-sync python -m scripts.sdlc.workflow_lane execute \\\n'
    )
    if evidence_text.count(anchor) != 1:
        raise SystemExit("service credential alias anchor drifted")
    evidence.write_text(evidence_text.replace(anchor, replacement, 1), encoding="utf-8")

    regression.write_text(
        f'''from pathlib import Path

from scripts.sdlc.workflow_lane import _OPTIONAL_CORE_TEST_IDS

EXPECTED = {{{FIRST!r}, {SECOND!r}}}


def test_increment5b4_authenticated_tests_are_core_optional() -> None:
    assert EXPECTED <= set(_OPTIONAL_CORE_TEST_IDS)


def test_service_lane_aliases_projector_credentials() -> None:
    workflow = (
        Path(__file__).resolve().parents[2]
        / ".github"
        / "workflows"
        / "evidence.yml"
    ).read_text(encoding="utf-8")
    user_alias = 'export NEWSROOM_NEO4J_USER="${{NEWSROOM_NEO4J_PROJECTOR_USERNAME}}"'
    password_alias = (
        'export NEWSROOM_NEO4J_PASSWORD="${{NEWSROOM_NEO4J_PROJECTOR_PASSWORD}}"'
    )
    service = workflow.index("  service:")
    execute = workflow.index("--lane service", service)
    assert service < workflow.index(user_alias, service) < execute
    assert service < workflow.index(password_alias, service) < execute
''',
        encoding="utf-8",
    )


def commit_and_verify_shape(product: Path) -> tuple[str, str]:
    run("git", "config", "user.name", "James To", cwd=product)
    run("git", "config", "user.email", "105634418+fol2@users.noreply.github.com", cwd=product)
    run("git", "add", "--", *FILES, cwd=product)
    run("git", "diff", "--cached", "--check", cwd=product)
    run(
        "git",
        "commit",
        "-q",
        "-m",
        "SDLC: reconcile Increment 5B authenticated service tests",
        cwd=product,
    )
    count = run("git", "rev-list", "--count", f"{EXPECTED_BASE}..HEAD", cwd=product, capture=True)
    actual = tuple(
        line
        for line in run("git", "diff", "--name-only", f"{EXPECTED_BASE}..HEAD", cwd=product, capture=True).splitlines()
        if line
    )
    if count != "1" or tuple(sorted(actual)) != tuple(sorted(FILES)):
        raise SystemExit(f"invalid reconciliation atom: count={count} files={actual}")
    if run("git", "diff", "--name-only", cwd=product, capture=True):
        raise SystemExit("tracked product tree is not clean before verification")
    return (
        run("git", "rev-parse", "HEAD", cwd=product, capture=True),
        run("git", "rev-parse", "HEAD^{tree}", cwd=product, capture=True),
    )


def main() -> None:
    configure_auth()
    product = Path("product")
    checkout_product(product)
    patch(product)
    head, tree = commit_and_verify_shape(product)

    run("uv", "sync", "--frozen", cwd=product)
    run(
        "python",
        "-m",
        "compileall",
        "-q",
        "scripts/sdlc/workflow_lane.py",
        "newsroom/tests/test_increment5b_tierm_service_reconciliation.py",
        cwd=product,
    )
    focused = run_logged(
        (
            "uv",
            "run",
            "pytest",
            "-q",
            "newsroom/tests/test_increment5b_tierm_service_reconciliation.py",
            "newsroom/tests/test_sdlc_workflow_lane.py",
            "newsroom/tests/test_integrated_c1_sdlc_contract.py",
        ),
        cwd=product,
        log=FOCUSED_LOG,
    )
    full = run_logged(("uv", "run", "pytest", "-q"), cwd=product, log=FULL_LOG)
    if run("git", "diff", "--name-only", cwd=product, capture=True):
        raise SystemExit("verification mutated tracked product bytes")

    RECEIPT.write_text(
        "\n".join(
            (
                "schema=newsroom.increment5b.tier-m-service-reconciliation.v1",
                f"head={head}",
                f"tree={tree}",
                f"parent={EXPECTED_BASE}",
                f"focused={focused}",
                f"full={full}",
                "files=3",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    for branch in (PRODUCT_BRANCH, CHECKPOINT_BRANCH):
        run("git", "push", "--force", "origin", f"HEAD:refs/heads/{branch}", cwd=product)
    print(RECEIPT.read_text(encoding="utf-8"), end="")


if __name__ == "__main__":
    main()
