"""Repair strict scalar typing in the Increment 5C1 authorization receipt."""
from __future__ import annotations

import base64
import os
from pathlib import Path
import shutil
import subprocess

REPOSITORY = "fol2/newsroom"
EXPECTED_MAIN = "c77624dba9b9bee87278eb9be5621ef35ee3df85"
EXPECTED_HEAD = "5749d98c5491710b300f39b0cf41e41a857acacf"
PRODUCT_BRANCH = "agent/increment-5c1-named-tool-authorization"
CHECKPOINT_BRANCH = "checkpoint/increment-5c1-named-tool-authorization-20260807"
PRODUCT_FILES = (
    "newsroom/increment5/named_tool_authorization.py",
    "newsroom/tests/test_increment5c1_named_tool_authorization.py",
)
FOCUSED_LOG = Path("/tmp/increment5c1-receipt-types-focused.log")
FULL_LOG = Path("/tmp/increment5c1-receipt-types-full.log")
RECEIPT = Path("/tmp/increment5c1-receipt-types-receipt.txt")


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
    if completed.returncode:
        print(output, end="")
        raise subprocess.CalledProcessError(
            completed.returncode,
            args,
            output=output,
        )
    lines = output.splitlines()
    return lines[-1] if lines else ""


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
    if root.exists():
        shutil.rmtree(root)
    run("git", "init", "-q", root.as_posix())
    run(
        "git",
        "remote",
        "add",
        "origin",
        f"https://github.com/{REPOSITORY}.git",
        cwd=root,
    )
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
    actual_head = run(
        "git", "rev-parse", "refs/remotes/origin/product", cwd=root, capture=True
    )
    actual_main = run(
        "git", "rev-parse", "refs/remotes/origin/main", cwd=root, capture=True
    )
    if actual_head != EXPECTED_HEAD:
        raise SystemExit(f"canonical 5C1 head moved: {actual_head}")
    if actual_main != EXPECTED_MAIN:
        raise SystemExit(f"main moved during 5C1 receipt repair: {actual_main}")
    run("git", "checkout", "-q", "--detach", EXPECTED_HEAD, cwd=root)
    return root


def patch(root: Path) -> None:
    authorization = root / PRODUCT_FILES[0]
    text = authorization.read_text(encoding="utf-8")
    anchor = '''        if self.reason is not None and not isinstance(self.reason, NamedToolGateReason):\n            raise NamedToolContractError("authorization reason must be typed")\n        if self.outcome is NamedToolGateOutcome.AUTHORIZED:\n'''
    replacement = '''        if self.reason is not None and not isinstance(self.reason, NamedToolGateReason):\n            raise NamedToolContractError("authorization reason must be typed")\n        for name in (\n            "local_tool_call_authorized",\n            "branch_executed",\n            "authority_read_executed",\n            "qualification_authority_granted",\n            "production_activation_authorized",\n        ):\n            if type(getattr(self, name)) is not bool:\n                raise NamedToolContractError(f"{name} must be boolean")\n        for name in (\n            "external_call_count",\n            "provider_call_count",\n            "model_call_count",\n            "embedding_call_count",\n            "provider_spend_micros",\n        ):\n            if type(getattr(self, name)) is not int:\n                raise NamedToolContractError(f"{name} must be an integer")\n        if self.outcome is NamedToolGateOutcome.AUTHORIZED:\n'''
    text = replace_once(
        text,
        anchor,
        replacement,
        field="receipt scalar type validation",
    )
    authorization.write_text(text, encoding="utf-8")

    tests = root / PRODUCT_FILES[1]
    text = tests.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "import hashlib\nimport inspect\nimport sqlite3\n",
        "import hashlib\nimport inspect\nimport json\nimport sqlite3\n",
        field="test json import",
    )
    anchor = '''def test_receipt_rejects_branch_execution_external_work_and_authority_claims(tmp_path: Path) -> None:\n'''
    addition = '''@pytest.mark.parametrize(\n    ("field", "value"),\n    (\n        ("local_tool_call_authorized", 1),\n        ("branch_executed", 0),\n        ("authority_read_executed", 0.0),\n        ("qualification_authority_granted", 0),\n        ("production_activation_authorized", None),\n    ),\n)\ndef test_receipt_rejects_type_confused_boolean_fields(\n    tmp_path: Path,\n    field: str,\n    value: object,\n) -> None:\n    request = exact_request()\n    receipt = authorizer(tmp_path, request).authorize(request)\n    with pytest.raises(NamedToolContractError, match=f"{field} must be boolean"):\n        replace(receipt, **{field: value})\n\n\n@pytest.mark.parametrize(\n    ("field", "value"),\n    (\n        ("external_call_count", False),\n        ("provider_call_count", 0.0),\n        ("model_call_count", None),\n        ("embedding_call_count", "0"),\n        ("provider_spend_micros", False),\n    ),\n)\ndef test_receipt_rejects_type_confused_integer_fields(\n    tmp_path: Path,\n    field: str,\n    value: object,\n) -> None:\n    request = exact_request()\n    receipt = authorizer(tmp_path, request).authorize(request)\n    with pytest.raises(NamedToolContractError, match=f"{field} must be an integer"):\n        replace(receipt, **{field: value})\n\n\ndef test_journal_rejects_canonical_type_confusion_with_recomputed_digest(\n    tmp_path: Path,\n) -> None:\n    request = fulltext_request(idempotency_key="tool:type-confusion")\n    gate = authorizer(tmp_path, request)\n    gate.authorize(request)\n    path = tmp_path / "tool-authorization.sqlite"\n    with sqlite3.connect(path) as connection:\n        raw = bytes(\n            connection.execute(\n                "SELECT receipt_bytes FROM increment5_named_tool_authorization_receipts "\n                "WHERE idempotency_key = ?",\n                (request.envelope.idempotency_key,),\n            ).fetchone()[0]\n        )\n        payload = json.loads(raw.decode("utf-8"))\n        payload["branch_executed"] = 0\n        tampered = json.dumps(\n            payload,\n            ensure_ascii=False,\n            sort_keys=True,\n            separators=(",", ":"),\n            allow_nan=False,\n        ).encode("utf-8")\n        connection.execute(\n            "UPDATE increment5_named_tool_authorization_receipts "\n            "SET receipt_bytes = ?, receipt_digest = ? WHERE idempotency_key = ?",\n            (\n                tampered,\n                "sha256:" + hashlib.sha256(tampered).hexdigest(),\n                request.envelope.idempotency_key,\n            ),\n        )\n    with pytest.raises(NamedToolAuthorizationError, match="malformed"):\n        gate.authorize(request)\n\n\n'''
    text = replace_once(
        text,
        anchor,
        addition + anchor,
        field="receipt type-confusion regressions",
    )
    tests.write_text(text, encoding="utf-8")


def verify_and_publish(root: Path) -> None:
    run("git", "config", "user.name", "James To", cwd=root)
    run(
        "git",
        "config",
        "user.email",
        "105634418+fol2@users.noreply.github.com",
        cwd=root,
    )
    run("git", "add", "--", *PRODUCT_FILES, cwd=root)
    run("git", "diff", "--cached", "--check", cwd=root)
    actual = tuple(
        line
        for line in run(
            "git", "diff", "--cached", "--name-only", cwd=root, capture=True
        ).splitlines()
        if line
    )
    if tuple(sorted(actual)) != tuple(sorted(PRODUCT_FILES)):
        raise SystemExit(f"5C1 repair inventory drifted: {actual}")
    run(
        "git",
        "commit",
        "-q",
        "-m",
        "Increment 5C1: enforce exact receipt scalar types",
        cwd=root,
    )
    head = run("git", "rev-parse", "HEAD", cwd=root, capture=True)
    tree = run("git", "rev-parse", "HEAD^{tree}", cwd=root, capture=True)

    run("uv", "lock", "--check", cwd=root)
    run("uv", "sync", "--dev", "--locked", cwd=root)
    run(
        "python",
        "-m",
        "compileall",
        "-q",
        "newsroom/increment5/named_tool_authorization.py",
        cwd=root,
    )
    focused = run_logged(
        (
            "uv",
            "run",
            "pytest",
            "-q",
            "newsroom/tests/test_increment5c1_named_tool_authorization.py",
            "newsroom/tests/test_increment5c1_named_tool_contracts.py",
        ),
        cwd=root,
        log=FOCUSED_LOG,
    )
    full = run_logged(
        ("uv", "run", "pytest", "-q"),
        cwd=root,
        log=FULL_LOG,
    )
    status = run(
        "git", "status", "--porcelain", "--untracked-files=no", cwd=root, capture=True
    )
    if status:
        raise SystemExit(f"verification mutated tracked product bytes: {status}")
    current_main = run(
        "git", "ls-remote", "origin", "refs/heads/main", cwd=root, capture=True
    ).split()[0]
    current_product = run(
        "git",
        "ls-remote",
        "origin",
        f"refs/heads/{PRODUCT_BRANCH}",
        cwd=root,
        capture=True,
    ).split()[0]
    current_checkpoint = run(
        "git",
        "ls-remote",
        "origin",
        f"refs/heads/{CHECKPOINT_BRANCH}",
        cwd=root,
        capture=True,
    ).split()[0]
    if current_main != EXPECTED_MAIN:
        raise SystemExit(f"main moved before 5C1 repair publication: {current_main}")
    if current_product != EXPECTED_HEAD or current_checkpoint != EXPECTED_HEAD:
        raise SystemExit(
            "5C1 canonical/checkpoint ref moved before repair publication: "
            f"product={current_product} checkpoint={current_checkpoint}"
        )
    for branch in (PRODUCT_BRANCH, CHECKPOINT_BRANCH):
        run("git", "push", "origin", f"HEAD:refs/heads/{branch}", cwd=root)
    RECEIPT.write_text(
        "\n".join(
            (
                "schema=newsroom.increment5c1.receipt-types-repair.v1",
                f"parent={EXPECTED_HEAD}",
                f"head={head}",
                f"tree={tree}",
                f"focused={focused}",
                f"full={full}",
                "files=2",
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
