"""Materialize and verify the hardened first-four branch kernel for Increment 5C2."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess

REPOSITORY = "fol2/newsroom"
EXPECTED_BASE = "72e0ade55ec05ff6de907319cb9baeeefe30d1ca"
EXPECTED_BASE_TREE = "12b4856334c7e97f4f699fe133ddd08c59b9ed81"
SOURCE_BRANCH = "support/materialize-increment-5c2a-20260806"
EXPECTED_SOURCE = "1da01a460c6b77e3d1cfb70140222eedd0f21afa"
PRODUCT_BRANCH = "agent/increment-5c2-six-named-tools"
CHECKPOINT_BRANCH = "checkpoint/increment-5c2-six-named-tools-20260807"
PRODUCT_FILES = (
    "newsroom/increment5/named_tool_branch_execution.py",
    "newsroom/tests/test_increment5c2a_named_tool_branch_execution.py",
)
FOCUSED_LOG = Path("/tmp/increment5c2-kernel-focused.log")
FULL_LOG = Path("/tmp/increment5c2-kernel-full.log")
RECEIPT = Path("/tmp/increment5c2-kernel-receipt.json")


def run(*args: str, cwd: Path | None = None, capture: bool = False, binary: bool = False):
    completed = subprocess.run(
        args,
        cwd=cwd,
        check=True,
        text=not binary,
        stdout=subprocess.PIPE if capture else None,
    )
    return completed.stdout if capture else None


def run_text(*args: str, cwd: Path | None = None) -> str:
    value = run(*args, cwd=cwd, capture=True)
    assert isinstance(value, str)
    return value.strip()


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
        raise subprocess.CalledProcessError(completed.returncode, args, output=output)
    return output.splitlines()[-1] if output.splitlines() else ""


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
    run("git", "remote", "add", "origin", f"https://github.com/{REPOSITORY}.git", cwd=root)
    run(
        "git",
        "fetch",
        "--no-tags",
        "--depth=1",
        "origin",
        "refs/heads/main:refs/remotes/origin/main",
        f"refs/heads/{SOURCE_BRANCH}:refs/remotes/origin/source",
        cwd=root,
    )
    if run_text("git", "rev-parse", "refs/remotes/origin/main", cwd=root) != EXPECTED_BASE:
        raise SystemExit("main moved before 5C2 kernel materialization")
    if run_text("git", "rev-parse", "refs/remotes/origin/source", cwd=root) != EXPECTED_SOURCE:
        raise SystemExit("preserved 5C2 kernel source moved")
    run("git", "checkout", "-q", "--detach", EXPECTED_BASE, cwd=root)
    if run_text("git", "rev-parse", "HEAD^{tree}", cwd=root) != EXPECTED_BASE_TREE:
        raise SystemExit("accepted 5C1 base tree drifted")
    return root


def copy_source(root: Path) -> None:
    for path in PRODUCT_FILES:
        payload = run(
            "git",
            "show",
            f"refs/remotes/origin/source:{path}",
            cwd=root,
            capture=True,
            binary=True,
        )
        assert isinstance(payload, bytes)
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)


def patch(root: Path) -> None:
    module = root / PRODUCT_FILES[0]
    text = module.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''Concrete translation into the merged 5B request/receipt classes is deliberately\noutside this module and belongs to 5C2B.  This module performs no retrieval,\nNeo4j access, hydration, collision check, fusion, Candidate mutation, provider\ncall, network call, publication or production activation by itself.\n''',
        '''Concrete adapters and the two authority-backed tools remain later commits in\nthe same 5C2 canonical PR. This kernel performs no retrieval, graph access,\nhydration, collision decision, fusion, Candidate mutation, external service\ncall, publication or production activation by itself.\n''',
        field="kernel delivery boundary",
    )
    text = replace_once(
        text,
        '''def _digest_bytes(value: bytes) -> str:\n    return "sha256:" + hashlib.sha256(value).hexdigest()\n\n\ndef _require_token''',
        '''def _digest_bytes(value: bytes) -> str:\n    return "sha256:" + hashlib.sha256(value).hexdigest()\n\n\ndef _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:\n    result: dict[str, object] = {}\n    for key, value in pairs:\n        if key in result:\n            raise NamedToolBranchExecutionError("retained JSON contains duplicate keys")\n        result[key] = value\n    return result\n\n\ndef _require_token''',
        field="duplicate-key decoder",
    )
    loads = 'json.loads(raw.decode("utf-8"))'
    if text.count(loads) < 1:
        raise SystemExit("canonical receipt JSON decoder anchor drifted")
    text = text.replace(
        loads,
        'json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)',
    )
    text = replace_once(
        text,
        '''        if not isinstance(self.no_match, bool):\n            raise NamedToolContractError("branch no_match must be boolean")\n''',
        '''        if type(self.no_match) is not bool:\n            raise NamedToolContractError("branch no_match must be boolean")\n''',
        field="branch no-match exact type",
    )
    text = replace_once(
        text,
        '''        if self.production_activation_authorized:\n            raise NamedToolContractError(\n                "branch attribution cannot authorize production activation"\n            )\n''',
        '''        if type(self.production_activation_authorized) is not bool:\n            raise NamedToolContractError(\n                "branch production activation flag must be boolean"\n            )\n        if self.production_activation_authorized:\n            raise NamedToolContractError(\n                "branch attribution cannot authorize production activation"\n            )\n''',
        field="branch activation exact type",
    )
    text = replace_once(
        text,
        '''        if not isinstance(self.no_match, bool):\n            raise NamedToolContractError("execution no_match must be boolean")\n''',
        '''        if type(self.no_match) is not bool:\n            raise NamedToolContractError("execution no_match must be boolean")\n''',
        field="execution no-match exact type",
    )
    text = replace_once(
        text,
        '''        if not isinstance(self.branch_executed, bool):\n            raise NamedToolContractError("branch_executed must be boolean")\n''',
        '''        if type(self.branch_executed) is not bool:\n            raise NamedToolContractError("branch_executed must be boolean")\n''',
        field="execution branch flag exact type",
    )
    text = replace_once(
        text,
        '''        if self.qualification_authority_granted or self.production_activation_authorized:\n            raise NamedToolContractError(\n                "tool execution cannot grant qualification or activation authority"\n            )\n''',
        '''        if type(self.qualification_authority_granted) is not bool:\n            raise NamedToolContractError(\n                "qualification authority flag must be boolean"\n            )\n        if type(self.production_activation_authorized) is not bool:\n            raise NamedToolContractError(\n                "production activation flag must be boolean"\n            )\n        if self.qualification_authority_granted or self.production_activation_authorized:\n            raise NamedToolContractError(\n                "tool execution cannot grant qualification or activation authority"\n            )\n''',
        field="execution authority flags exact type",
    )
    module.write_text(text, encoding="utf-8")

    tests = root / PRODUCT_FILES[1]
    text = tests.read_text(encoding="utf-8")
    addition = '''\n\n@pytest.mark.parametrize(\n    ("field", "value", "message"),\n    (\n        ("no_match", 0, "branch no_match must be boolean"),\n        (\n            "production_activation_authorized",\n            0,\n            "branch production activation flag must be boolean",\n        ),\n    ),\n)\ndef test_branch_attribution_rejects_type_confused_flags(\n    field: str, value: object, message: str\n) -> None:\n    request = exact_request()\n    base = branch_result(request).attribution\n    with pytest.raises(NamedToolContractError, match=message):\n        replace(base, **{field: value})\n\n\n@pytest.mark.parametrize(\n    ("field", "value", "message"),\n    (\n        ("no_match", 0, "execution no_match must be boolean"),\n        ("branch_executed", 1, "branch_executed must be boolean"),\n        (\n            "qualification_authority_granted",\n            0,\n            "qualification authority flag must be boolean",\n        ),\n        (\n            "production_activation_authorized",\n            0,\n            "production activation flag must be boolean",\n        ),\n    ),\n)\ndef test_execution_receipt_rejects_type_confused_flags(\n    tmp_path: Path, field: str, value: object, message: str\n) -> None:\n    request = exact_request()\n    result = executor(tmp_path)[0].execute(request, authorization(tmp_path, request))\n    with pytest.raises(NamedToolContractError, match=message):\n        replace(result.receipt, **{field: value})\n\n\ndef test_execution_receipt_decoder_rejects_duplicate_keys(tmp_path: Path) -> None:\n    request = exact_request()\n    receipt = executor(tmp_path)[0].execute(\n        request, authorization(tmp_path, request)\n    ).receipt\n    raw = receipt.canonical_bytes.replace(\n        b'"authority_effect":"NONE"',\n        b'"authority_effect":"NONE","authority_effect":"NONE"',\n        1,\n    )\n    with pytest.raises(NamedToolBranchExecutionError, match="duplicate keys"):\n        NamedToolExecutionReceipt.from_canonical_bytes(raw)\n'''
    if "test_execution_receipt_decoder_rejects_duplicate_keys" in text:
        raise SystemExit("5C2 kernel hardening tests already exist")
    tests.write_text(text.rstrip() + addition + "\n", encoding="utf-8")


def main() -> None:
    configure_auth()
    root = checkout()
    copy_source(root)
    patch(root)
    run("git", "config", "user.name", "James To", cwd=root)
    run("git", "config", "user.email", "105634418+fol2@users.noreply.github.com", cwd=root)
    run("git", "add", "--", *PRODUCT_FILES, cwd=root)
    run("git", "diff", "--cached", "--check", cwd=root)
    actual = tuple(
        line for line in run_text("git", "diff", "--cached", "--name-only", cwd=root).splitlines() if line
    )
    if tuple(sorted(actual)) != tuple(sorted(PRODUCT_FILES)):
        raise SystemExit(f"5C2 kernel inventory drifted: {actual}")
    run(
        "git",
        "commit",
        "-q",
        "-m",
        "Increment 5C2: add hardened first-four branch execution kernel",
        cwd=root,
    )
    head = run_text("git", "rev-parse", "HEAD", cwd=root)
    tree = run_text("git", "rev-parse", "HEAD^{tree}", cwd=root)
    run("uv", "lock", "--check", cwd=root)
    run("uv", "sync", "--dev", "--locked", cwd=root)
    run("python", "-m", "compileall", "-q", PRODUCT_FILES[0], cwd=root)
    focused = run_logged(
        (
            "uv", "run", "pytest", "-q",
            PRODUCT_FILES[1],
            "newsroom/tests/test_increment5c1_named_tool_authorization.py",
            "newsroom/tests/test_increment5c1_named_tool_contracts.py",
        ),
        cwd=root,
        log=FOCUSED_LOG,
    )
    full = run_logged(("uv", "run", "pytest", "-q"), cwd=root, log=FULL_LOG)
    if run_text("git", "status", "--porcelain", "--untracked-files=no", cwd=root):
        raise SystemExit("5C2 kernel verification mutated tracked bytes")
    if run_text("git", "ls-remote", "origin", "refs/heads/main", cwd=root).split()[0] != EXPECTED_BASE:
        raise SystemExit("main moved before 5C2 kernel publication")
    for branch in (PRODUCT_BRANCH, CHECKPOINT_BRANCH):
        if run_text("git", "ls-remote", "origin", f"refs/heads/{branch}", cwd=root):
            raise SystemExit(f"5C2 publication ref already exists: {branch}")
        run("git", "push", "origin", f"HEAD:refs/heads/{branch}", cwd=root)
    receipt = {
        "schema_version": "newsroom.increment5c2.kernel-checkpoint.v1",
        "base": EXPECTED_BASE,
        "base_tree": EXPECTED_BASE_TREE,
        "source": EXPECTED_SOURCE,
        "head": head,
        "tree": tree,
        "focused": focused,
        "full": full,
        "files": list(PRODUCT_FILES),
        "complete_5c2": False,
        "remaining": ["four concrete branch adapters", "collision/authority tool", "source/revision impact tool", "integrated six-tool receipts"],
    }
    RECEIPT.write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(RECEIPT.read_text(encoding="utf-8"), end="")


if __name__ == "__main__":
    main()
