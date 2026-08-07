"""Patch and verify the exact Increment 5B Tier-M service-sandbox boundary."""
from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path

REPOSITORY = "fol2/newsroom"
EXPECTED_MAIN = "88d1b14b41354f56f325d173d0021ad0fd20abc2"
EXPECTED_HEAD = "57155935f2e5503fc1f643c40b720266ca121bb0"
PRODUCT_BRANCH = "agent/increment-5b-tierm-service-reconciliation"
CHECKPOINT_BRANCH = "checkpoint/increment-5b-tierm-service-reconciliation-20260807"
PRODUCT_FILES = (
    "newsroom/tests/test_increment5b_tierm_service_reconciliation.py",
    "newsroom/tests/test_sdlc_workflow_lane.py",
    "scripts/sdlc/workflow_lane.py",
)
FOCUSED_LOG = Path("/tmp/increment5b-tierm-sandbox-focused.log")
FULL_LOG = Path("/tmp/increment5b-tierm-sandbox-full.log")
RECEIPT = Path("/tmp/increment5b-tierm-sandbox-receipt.txt")


def run(*args: str, cwd: Path | None = None, capture: bool = False) -> str:
    completed = subprocess.run(
        args,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return completed.stdout.strip() if capture else ""


def replace_once(text: str, old: str, new: str, *, field: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"{field} anchor drifted")
    return text.replace(old, new, 1)


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


def checkout() -> Path:
    root = Path("product")
    run("git", "init", "-q", root.as_posix())
    run("git", "remote", "add", "origin", f"https://github.com/{REPOSITORY}.git", cwd=root)
    run(
        "git",
        "fetch",
        "--no-tags",
        "--depth=2",
        "origin",
        f"refs/heads/{PRODUCT_BRANCH}:refs/remotes/origin/product",
        "refs/heads/main:refs/remotes/origin/main",
        cwd=root,
    )
    if run("git", "rev-parse", "refs/remotes/origin/product", cwd=root, capture=True) != EXPECTED_HEAD:
        raise SystemExit("canonical product head moved")
    if run("git", "rev-parse", "refs/remotes/origin/main", cwd=root, capture=True) != EXPECTED_MAIN:
        raise SystemExit("main moved during Tier-M repair")
    run("git", "checkout", "-q", "--detach", EXPECTED_HEAD, cwd=root)
    return root


def patch(root: Path) -> None:
    lane = root / "scripts/sdlc/workflow_lane.py"
    text = lane.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '    "NEWSROOM_NEO4J_PROJECTOR_USERNAME": "newsroom_projector",\n',
        '    "NEWSROOM_NEO4J_PROJECTOR_USERNAME": "newsroom_projector",\n'
        '    "NEWSROOM_NEO4J_USER": "newsroom_projector",\n',
        field="generic projector username",
    )
    text = replace_once(
        text,
        '        pass_env = ("NEWSROOM_NEO4J_PROJECTOR_PASSWORD",)\n',
        '        pass_env = (\n'
        '            "NEWSROOM_NEO4J_PASSWORD",\n'
        '            "NEWSROOM_NEO4J_PROJECTOR_PASSWORD",\n'
        '        )\n',
        field="service command pass-env",
    )
    lane.write_text(text, encoding="utf-8")

    tests = root / "newsroom/tests/test_sdlc_workflow_lane.py"
    text = tests.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '    monkeypatch.setenv("GITHUB_TOKEN", "must-not-pass")\n'
        '    monkeypatch.setenv("NEWSROOM_NEO4J_PROJECTOR_PASSWORD", "must-not-pass")\n',
        '    monkeypatch.setenv("GITHUB_TOKEN", "must-not-pass")\n'
        '    monkeypatch.setenv("NEWSROOM_NEO4J_PASSWORD", "must-not-pass")\n'
        '    monkeypatch.setenv("NEWSROOM_NEO4J_PROJECTOR_PASSWORD", "must-not-pass")\n',
        field="ambient secret setup",
    )
    text = replace_once(
        text,
        '    assert "GITHUB_TOKEN" not in environment\n'
        '    assert "NEWSROOM_NEO4J_PROJECTOR_PASSWORD" not in environment\n',
        '    assert "GITHUB_TOKEN" not in environment\n'
        '    assert "NEWSROOM_NEO4J_PASSWORD" not in environment\n'
        '    assert "NEWSROOM_NEO4J_PROJECTOR_PASSWORD" not in environment\n',
        field="ambient secret assertions",
    )
    text = replace_once(
        text,
        "def test_service_lane_requires_route_and_passes_only_projector_secret(\n",
        "def test_service_lane_requires_route_and_passes_only_explicit_projector_secrets(\n",
        field="service test identity",
    )
    text = replace_once(
        text,
        '    captured = {}\n'
        '    monkeypatch.setenv("NEWSROOM_NEO4J_PROJECTOR_PASSWORD", "secret")\n',
        '    captured = {}\n'
        '    monkeypatch.setenv("NEWSROOM_NEO4J_PASSWORD", "generic-secret")\n'
        '    monkeypatch.setenv("NEWSROOM_NEO4J_PROJECTOR_PASSWORD", "projector-secret")\n',
        field="service secrets",
    )
    text = replace_once(
        text,
        '    monkeypatch.setenv(\n'
        '        "NEWSROOM_NEO4J_PROJECTOR_USERNAME", "newsroom_projector"\n'
        '    )\n',
        '    monkeypatch.setenv(\n'
        '        "NEWSROOM_NEO4J_PROJECTOR_USERNAME", "newsroom_projector"\n'
        '    )\n'
        '    monkeypatch.setenv("NEWSROOM_NEO4J_USER", "newsroom_projector")\n',
        field="generic projector identity",
    )
    text = replace_once(
        text,
        '    assert captured["spec"]["pass_env"] == (\n'
        '        "NEWSROOM_NEO4J_PROJECTOR_PASSWORD",\n'
        '    )\n',
        '    assert captured["spec"]["pass_env"] == (\n'
        '        "NEWSROOM_NEO4J_PASSWORD",\n'
        '        "NEWSROOM_NEO4J_PROJECTOR_PASSWORD",\n'
        '    )\n',
        field="pass-env assertion",
    )
    text = replace_once(
        text,
        '    assert static["NEWSROOM_NEO4J_SERVICE_REQUIRED"] == "1"\n'
        '    assert static["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"\n'
        '    assert "NEWSROOM_NEO4J_PROJECTOR_PASSWORD" not in static\n',
        '    assert static["NEWSROOM_NEO4J_SERVICE_REQUIRED"] == "1"\n'
        '    assert static["NEWSROOM_NEO4J_USER"] == "newsroom_projector"\n'
        '    assert static["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"\n'
        '    assert "NEWSROOM_NEO4J_PASSWORD" not in static\n'
        '    assert "NEWSROOM_NEO4J_PROJECTOR_PASSWORD" not in static\n',
        field="static service assertions",
    )
    tests.write_text(text, encoding="utf-8")

    focused = root / "newsroom/tests/test_increment5b_tierm_service_reconciliation.py"
    text = focused.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from scripts.sdlc.workflow_lane import _OPTIONAL_CORE_TEST_IDS\n",
        "from scripts.sdlc.workflow_lane import (\n"
        "    _OPTIONAL_CORE_TEST_IDS,\n"
        "    _SERVICE_CONFIGURATION,\n"
        ")\n",
        field="focused imports",
    )
    addition = '''\n\ndef test_service_contract_exposes_generic_projector_identity_without_secret() -> None:\n    assert _SERVICE_CONFIGURATION["NEWSROOM_NEO4J_USER"] == "newsroom_projector"\n    assert _SERVICE_CONFIGURATION["NEWSROOM_NEO4J_PROJECTOR_USERNAME"] == (\n        "newsroom_projector"\n    )\n    assert "NEWSROOM_NEO4J_PASSWORD" not in _SERVICE_CONFIGURATION\n'''
    if "test_service_contract_exposes_generic_projector_identity_without_secret" in text:
        raise SystemExit("focused generic identity regression already exists")
    focused.write_text(text.rstrip() + addition + "\n", encoding="utf-8")


def verify_and_publish(root: Path) -> None:
    run("uv", "lock", "--check", cwd=root)
    run("uv", "sync", "--dev", "--locked", cwd=root)
    focused = (
        "newsroom/tests/test_increment5b_tierm_service_reconciliation.py",
        "newsroom/tests/test_sdlc_workflow_lane.py::test_static_environment_excludes_ambient_secrets",
        "newsroom/tests/test_sdlc_workflow_lane.py::test_service_lane_requires_route_and_passes_only_explicit_projector_secrets",
        "newsroom/tests/test_sdlc_workflow_lane.py::test_optional_core_skips_are_exact_actual_service_cases",
        "newsroom/tests/test_integrated_c1_sdlc_contract.py::test_complete_actual_service_cases_are_optional_only_in_core",
    )
    with FOCUSED_LOG.open("w", encoding="utf-8") as stream:
        subprocess.run(("uv", "run", "pytest", "-q", *focused), cwd=root, check=True, text=True, stdout=stream)
    with FULL_LOG.open("w", encoding="utf-8") as stream:
        subprocess.run(("uv", "run", "pytest", "-q"), cwd=root, check=True, text=True, stdout=stream)

    run("git", "config", "user.name", "James To", cwd=root)
    run("git", "config", "user.email", "105634418+fol2@users.noreply.github.com", cwd=root)
    run("git", "add", "--", *PRODUCT_FILES, cwd=root)
    run("git", "diff", "--cached", "--check", cwd=root)
    actual = tuple(filter(None, run("git", "diff", "--cached", "--name-only", cwd=root, capture=True).splitlines()))
    if tuple(sorted(actual)) != tuple(sorted(PRODUCT_FILES)):
        raise SystemExit(f"product inventory drifted: {actual}")
    run(
        "git",
        "commit",
        "-q",
        "-m",
        "SDLC: pass explicit Neo4j credentials into service sandbox",
        cwd=root,
    )
    head = run("git", "rev-parse", "HEAD", cwd=root, capture=True)
    tree = run("git", "rev-parse", "HEAD^{tree}", cwd=root, capture=True)
    for branch in (PRODUCT_BRANCH, CHECKPOINT_BRANCH):
        run("git", "push", "origin", f"HEAD:refs/heads/{branch}", cwd=root)
    RECEIPT.write_text(
        "\n".join(
            (
                "schema=newsroom.increment5b.tierm-sandbox-repair.v1",
                f"parent={EXPECTED_HEAD}",
                f"head={head}",
                f"tree={tree}",
                f"focused={FOCUSED_LOG.read_text(encoding='utf-8').splitlines()[-1]}",
                f"full={FULL_LOG.read_text(encoding='utf-8').splitlines()[-1]}",
                "files=3",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    print(RECEIPT.read_text(encoding="utf-8"), end="")


def main() -> None:
    configure_auth()
    root = checkout()
    patch(root)
    verify_and_publish(root)


if __name__ == "__main__":
    main()
