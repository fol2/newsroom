"""Verify and publish the exact Increment 5C2 Evidence projector repair."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

REPOSITORY = "fol2/newsroom"
PRODUCT_BRANCH = "agent/increment-5c2-six-named-tools"
CHECKPOINT_BRANCH = "checkpoint/increment-5c2-six-named-tools-20260807"
EXPECTED_PARENT = "2cd604ca4f1c3f4bdd0da9e643fc5f5475cf87b9"
EXPECTED_PARENT_TREE = "48d278b6878c5078abb7b1ce352bd81771d03595"
EXPECTED_MAIN = "72e0ade55ec05ff6de907319cb9baeeefe30d1ca"
TARGET_PATH = Path("newsroom/tests/test_projection_b2_neo4j_service.py")
NEO4J_IMAGE = "neo4j:2026.06.0-community-trixie"
CONTAINER_NAME = "newsroom-increment5c2-evidence-projector"
FOCUSED_LOG = Path("/tmp/increment5c2-evidence-projector-service.log")
FULL_LOG = Path("/tmp/increment5c2-evidence-projector-full.log")
CLUSTERING_LOG = Path("/tmp/increment5c2-evidence-projector-clustering.log")
RECEIPT = Path("/tmp/increment5c2-evidence-projector-receipt.json")

OLD_AUTH = '''            auth=(
                os.environ["NEO4J_ADMIN_USERNAME"],
                os.environ["NEO4J_ADMIN_PASSWORD"],
            ),
'''
NEW_AUTH = '''            auth=(config.username, config.password),
'''

SERVICE_TESTS = (
    "newsroom/tests/test_complete_projection_2b_neo4j_service.py",
    "newsroom/tests/test_increment4e_neo4j_service.py",
    "newsroom/tests/test_increment5b4_neo4j_service.py",
    "newsroom/tests/test_increment_2d_neo4j_service.py",
    "newsroom/tests/test_integrated_c1_neo4j_service.py",
    "newsroom/tests/test_projection_b2_neo4j_service.py",
    "newsroom/tests/test_projection_b3_neo4j_service.py",
    "newsroom/tests/test_retrieval_2c_neo4j_service.py",
)

SERVICE_ENV_NAMES = {
    "NEO4J_ADMIN_PASSWORD",
    "NEO4J_ADMIN_USERNAME",
    "NEO4J_URI",
    "NEWSROOM_NEO4J_COMPLETE_SERVICE_REQUIRED",
    "NEWSROOM_NEO4J_DATABASE",
    "NEWSROOM_NEO4J_INCREMENT_2D_SERVICE_REQUIRED",
    "NEWSROOM_NEO4J_PASSWORD",
    "NEWSROOM_NEO4J_PROJECTOR_PASSWORD",
    "NEWSROOM_NEO4J_PROJECTOR_USERNAME",
    "NEWSROOM_NEO4J_RETRIEVAL_SERVICE_REQUIRED",
    "NEWSROOM_NEO4J_SERVICE_REQUIRED",
    "NEWSROOM_NEO4J_URI",
    "NEWSROOM_NEO4J_USER",
}


def run(
    *args: str,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    capture: bool = False,
) -> str:
    completed = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if completed.returncode != 0:
        if capture:
            if completed.stdout:
                print(completed.stdout, end="")
            if completed.stderr:
                print(completed.stderr, end="", file=sys.stderr)
        raise SystemExit(f"command failed with exit {completed.returncode}: {args[0]}")
    return completed.stdout.strip() if capture else ""


def run_logged(
    args: tuple[str, ...],
    *,
    cwd: Path,
    env: dict[str, str] | None,
    log: Path,
) -> str:
    completed = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = completed.stdout
    log.write_text(output, encoding="utf-8")
    print(output, end="")
    if completed.returncode != 0:
        raise SystemExit(
            f"verification command failed with exit {completed.returncode}: {args[0]}"
        )
    lines = [line for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def configure_git_auth() -> None:
    token = os.environ["GH_TOKEN"]
    encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    run(
        "git",
        "config",
        "--global",
        "http.https://github.com/.extraheader",
        f"AUTHORIZATION: basic {encoded}",
    )


def remote_sha(root: Path, branch: str) -> str:
    value = run(
        "git",
        "ls-remote",
        "origin",
        f"refs/heads/{branch}",
        cwd=root,
        capture=True,
    )
    if not value:
        raise SystemExit(f"required remote branch is absent: {branch}")
    return value.split()[0]


def checkout_product() -> Path:
    root = Path("product")
    run("git", "init", "-q", root.as_posix())
    run(
        "git",
        "remote",
        "add",
        "origin",
        f"https://github.com/{REPOSITORY}.git",
        cwd=root,
    )
    if remote_sha(root, PRODUCT_BRANCH) != EXPECTED_PARENT:
        raise SystemExit("canonical 5C2 head moved before Evidence projector repair")
    if remote_sha(root, CHECKPOINT_BRANCH) != EXPECTED_PARENT:
        raise SystemExit("5C2 checkpoint moved before Evidence projector repair")
    if remote_sha(root, "main") != EXPECTED_MAIN:
        raise SystemExit("main moved before Evidence projector repair")
    run(
        "git",
        "fetch",
        "--no-tags",
        "--depth=12",
        "origin",
        f"refs/heads/{PRODUCT_BRANCH}:refs/remotes/origin/product",
        "refs/heads/main:refs/remotes/origin/main",
        cwd=root,
    )
    parent = run(
        "git", "rev-parse", "refs/remotes/origin/product", cwd=root, capture=True
    )
    parent_tree = run(
        "git",
        "rev-parse",
        "refs/remotes/origin/product^{tree}",
        cwd=root,
        capture=True,
    )
    if parent != EXPECTED_PARENT or parent_tree != EXPECTED_PARENT_TREE:
        raise SystemExit("fetched 5C2 parent identity drifted")
    run("git", "checkout", "-q", "--detach", EXPECTED_PARENT, cwd=root)
    return root


def apply_repair(root: Path) -> tuple[str, str]:
    target = root / TARGET_PATH
    source = target.read_text(encoding="utf-8")
    if source.count(OLD_AUTH) != 1:
        raise SystemExit("Evidence projector repair anchor is not exact")
    target.write_text(source.replace(OLD_AUTH, NEW_AUTH, 1), encoding="utf-8")
    run("git", "config", "user.name", "James To", cwd=root)
    run(
        "git",
        "config",
        "user.email",
        "105634418+fol2@users.noreply.github.com",
        cwd=root,
    )
    run("git", "add", TARGET_PATH.as_posix(), cwd=root)
    run(
        "git",
        "commit",
        "--no-gpg-sign",
        "-m",
        "Increment 5C2: keep Evidence service on projector identity",
        cwd=root,
    )
    if run("git", "rev-parse", "HEAD^", cwd=root, capture=True) != EXPECTED_PARENT:
        raise SystemExit("Evidence projector repair parent identity drifted")
    changed = tuple(
        line
        for line in run(
            "git",
            "diff",
            "--name-only",
            "HEAD^",
            "HEAD",
            cwd=root,
            capture=True,
        ).splitlines()
        if line
    )
    if changed != (TARGET_PATH.as_posix(),):
        raise SystemExit(f"Evidence projector repair inventory drifted: {changed}")
    patch = run(
        "git",
        "diff",
        "--unified=3",
        "HEAD^",
        "HEAD",
        "--",
        TARGET_PATH.as_posix(),
        cwd=root,
        capture=True,
    )
    if "NEO4J_ADMIN_USERNAME" not in patch or "config.username" not in patch:
        raise SystemExit("Evidence projector repair diff is not the reviewed credential change")
    run("git", "show", "--check", "--oneline", "HEAD", cwd=root)
    return (
        run("git", "rev-parse", "HEAD", cwd=root, capture=True),
        run("git", "rev-parse", "HEAD^{tree}", cwd=root, capture=True),
    )


def clean_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in SERVICE_ENV_NAMES:
        environment.pop(name, None)
    return environment


def setup_environment(root: Path) -> None:
    run("uv", "lock", "--check", cwd=root)
    run("uv", "sync", "--dev", "--locked", cwd=root)
    run(
        "uv",
        "run",
        "--no-sync",
        "python",
        "-m",
        "compileall",
        "-q",
        TARGET_PATH.as_posix(),
        cwd=root,
    )


def setup_projector(root: Path, *, admin_password: str, projector_password: str) -> None:
    script = r'''
import os
import time
from neo4j import GraphDatabase

uri = "bolt://localhost:7687"
last_error = None
for _ in range(200):
    driver = None
    try:
        driver = GraphDatabase.driver(
            uri,
            auth=("neo4j", os.environ["ADMIN_PASSWORD"]),
            connection_timeout=1.0,
        )
        driver.verify_connectivity()
        break
    except Exception as exc:
        last_error = exc
        if driver is not None:
            driver.close()
        time.sleep(0.25)
else:
    raise RuntimeError("authenticated Neo4j readiness timed out") from last_error

assert driver is not None
try:
    with driver.session(database="system") as session:
        session.run(
            "CREATE USER newsroom_projector IF NOT EXISTS "
            "SET PLAINTEXT PASSWORD $password CHANGE NOT REQUIRED",
            password=os.environ["PROJECTOR_PASSWORD"],
        ).consume()
finally:
    driver.close()

projector = GraphDatabase.driver(
    uri,
    auth=("newsroom_projector", os.environ["PROJECTOR_PASSWORD"]),
    connection_timeout=1.0,
)
try:
    projector.verify_connectivity()
finally:
    projector.close()
'''
    environment = clean_environment()
    environment["ADMIN_PASSWORD"] = admin_password
    environment["PROJECTOR_PASSWORD"] = projector_password
    run(
        "uv",
        "run",
        "--no-sync",
        "python",
        "-c",
        script,
        cwd=root,
        env=environment,
    )


def service_environment(projector_password: str) -> dict[str, str]:
    environment = clean_environment()
    environment.update(
        {
            "NEO4J_URI": "bolt://localhost:7687",
            "NEWSROOM_NEO4J_COMPLETE_SERVICE_REQUIRED": "1",
            "NEWSROOM_NEO4J_DATABASE": "neo4j",
            "NEWSROOM_NEO4J_INCREMENT_2D_SERVICE_REQUIRED": "1",
            "NEWSROOM_NEO4J_PASSWORD": projector_password,
            "NEWSROOM_NEO4J_PROJECTOR_PASSWORD": projector_password,
            "NEWSROOM_NEO4J_PROJECTOR_USERNAME": "newsroom_projector",
            "NEWSROOM_NEO4J_RETRIEVAL_SERVICE_REQUIRED": "1",
            "NEWSROOM_NEO4J_SERVICE_REQUIRED": "1",
            "NEWSROOM_NEO4J_URI": "bolt://localhost:7687",
            "NEWSROOM_NEO4J_USER": "newsroom_projector",
        }
    )
    return environment


def verify_service(root: Path) -> str:
    admin_password = secrets.token_urlsafe(32)
    projector_password = secrets.token_urlsafe(32)
    docker_environment = os.environ.copy()
    docker_environment["NEO4J_AUTH"] = f"neo4j/{admin_password}"
    subprocess.run(
        ("docker", "rm", "--force", CONTAINER_NAME),
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        run("docker", "pull", NEO4J_IMAGE, env=docker_environment)
        run(
            "docker",
            "run",
            "--detach",
            "--pull=never",
            "--name",
            CONTAINER_NAME,
            "--publish",
            "127.0.0.1:7687:7687",
            "--env",
            "NEO4J_AUTH",
            NEO4J_IMAGE,
            env=docker_environment,
        )
        setup_projector(
            root,
            admin_password=admin_password,
            projector_password=projector_password,
        )
        return run_logged(
            (
                "uv",
                "run",
                "--no-sync",
                "pytest",
                "-q",
                *SERVICE_TESTS,
                "--junitxml=/tmp/increment5c2-evidence-projector-service.xml",
            ),
            cwd=root,
            env=service_environment(projector_password),
            log=FOCUSED_LOG,
        )
    finally:
        subprocess.run(
            ("docker", "rm", "--force", CONTAINER_NAME),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def verify_deterministic(root: Path) -> dict[str, str]:
    service = verify_service(root)
    full = run_logged(
        ("uv", "run", "--no-sync", "pytest", "-q"),
        cwd=root,
        env=clean_environment(),
        log=FULL_LOG,
    )
    clustering = run_logged(
        (
            "uv",
            "run",
            "--no-sync",
            "python",
            "scripts/eval_clustering_metrics.py",
            "--dataset",
            "newsroom/evals/clustering_eval_dataset_v1.jsonl",
            "--baseline",
            "newsroom/evals/clustering_eval_metrics_baseline_v1.json",
            "--fail-on-regression",
        ),
        cwd=root,
        env=clean_environment(),
        log=CLUSTERING_LOG,
    )
    if run("git", "status", "--porcelain", cwd=root, capture=True):
        raise SystemExit("Evidence projector verification mutated the product tree")
    return {"service": service, "full": full, "clustering": clustering}


def publish(root: Path, *, head: str, tree: str, evidence: dict[str, str]) -> None:
    if remote_sha(root, PRODUCT_BRANCH) != EXPECTED_PARENT:
        raise SystemExit("canonical 5C2 head moved during Evidence projector verification")
    if remote_sha(root, CHECKPOINT_BRANCH) != EXPECTED_PARENT:
        raise SystemExit("5C2 checkpoint moved during Evidence projector verification")
    if remote_sha(root, "main") != EXPECTED_MAIN:
        raise SystemExit("main moved during Evidence projector verification")
    for branch in (PRODUCT_BRANCH, CHECKPOINT_BRANCH):
        run("git", "push", "origin", f"HEAD:refs/heads/{branch}", cwd=root)
    receipt = {
        "schema_version": "newsroom.increment5c2.evidence-projector-repair.v1",
        "parent": EXPECTED_PARENT,
        "parent_tree": EXPECTED_PARENT_TREE,
        "main": EXPECTED_MAIN,
        "head": head,
        "tree": tree,
        "files": [TARGET_PATH.as_posix()],
        **evidence,
    }
    RECEIPT.write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(RECEIPT.read_text(encoding="utf-8"), end="")


def main() -> None:
    configure_git_auth()
    root = checkout_product()
    head, tree = apply_repair(root)
    setup_environment(root)
    evidence = verify_deterministic(root)
    publish(root, head=head, tree=tree, evidence=evidence)


if __name__ == "__main__":
    main()
