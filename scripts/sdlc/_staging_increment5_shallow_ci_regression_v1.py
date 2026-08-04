#!/usr/bin/env python3
"""Close the shallow-CI and owner-execute review findings for Increment 5A.

Disposable support helper. Never merge this file into PR #255 or main.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "newsroom/tests/test_increment5a_profile_semantic_envelope.py"
VALIDATOR = ROOT / "scripts/sdlc/increment5_profile_validator.py"
MANIFEST = ROOT / "increment5a-shallow-ci-regression-manifest.json"


tests = TESTS.read_text(encoding="utf-8")
start_marker = '    if sys.argv[5] == "HEAD":\n'
end_marker = '    else:\n        changed = subprocess.run(\n'
if tests.count(start_marker) != 1:
    raise RuntimeError(
        f"HEAD race start marker differs: found {tests.count(start_marker)}"
    )
start = tests.index(start_marker)
end = tests.index(end_marker, start)
new_head = '''    if sys.argv[5] == "HEAD":
        # Create a different commit identity over the same exact tree. This
        # tests the HEAD recheck without assuming that a shallow checkout
        # contains any parent commit object.
        newline = bytes((10,))
        commit_bytes = newline.join(
            (
                f"tree {sys.argv[4]}".encode("ascii"),
                b"author Snapshot Race <snapshot@example.invalid> 0 +0000",
                b"committer Snapshot Race <snapshot@example.invalid> 0 +0000",
                b"",
                b"snapshot race",
                b"",
            )
        )
        alternate = subprocess.run(
            [
                "/usr/bin/git", "-C", str(root), "hash-object",
                "-t", "commit", "-w", "--stdin",
            ],
            input=commit_bytes,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if alternate.returncode != 0:
            raise SystemExit(alternate.stderr.decode("utf-8"))
        changed = subprocess.run(
            [
                "/usr/bin/git", "-C", str(root), "update-ref", "HEAD",
                alternate.stdout.decode("ascii", errors="strict").strip(),
            ],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
'''
tests = tests[:start] + new_head + tests[end:]

mode_regression = '''\n\n@pytest.mark.skipif(os.name != "posix", reason="POSIX mode semantics required")\ndef test_worktree_mode_matching_uses_owner_execute_bit(tmp_path: Path) -> None:\n    clone, clone_commit, clone_tree = _clone_exact_head(tmp_path)\n    validator = clone / _VALIDATOR_RELATIVE_PATH\n    validator.chmod(0o650)\n    probe = """\nimport sys\nfrom pathlib import Path\nsys.argv[0] = "-"\nsource = Path(sys.argv[1]).read_bytes()\nnamespace = {"__name__": "validator-owner-execute-probe", "__file__": sys.argv[1]}\nexec(compile(source, "-", "exec"), namespace)\nroot = Path(sys.argv[2])\nview = namespace["_TrustedRepositoryView"](\n    root, root / ".git", root / ".git/index"\n)\ntry:\n    view.require_stable_clean_tree(sys.argv[3], sys.argv[4])\nexcept namespace["ProfileInputError"] as exc:\n    if str(exc) != "tracked repository checkout differs from HEAD":\n        raise\nelse:\n    raise SystemExit("group-only execute bit escaped Git mode verification")\n"""\n    completed = subprocess.run(\n        [\n            str(_TRUSTED_PYTHON),\n            "-I",\n            "-S",\n            "-c",\n            probe,\n            str(validator),\n            str(clone),\n            clone_commit,\n            clone_tree,\n        ],\n        stdout=subprocess.PIPE,\n        stderr=subprocess.PIPE,\n        check=False,\n        cwd=clone,\n        env={"LC_ALL": "C", "PYTHONUTF8": "1"},\n        timeout=30,\n    )\n    assert completed.returncode == 0, completed.stderr.decode("utf-8")\n'''
if "def test_worktree_mode_matching_uses_owner_execute_bit" in tests:
    raise RuntimeError("owner-execute regression already exists")
tests += mode_regression

if '["/usr/bin/git", "-C", str(root), "rev-parse", "HEAD^"]' in tests:
    raise RuntimeError("history-dependent HEAD race remains")
if '"hash-object",\n                "-t", "commit", "-w", "--stdin"' not in tests:
    raise RuntimeError("synthetic same-tree commit race is absent")
if "newline = bytes((10,))" not in tests:
    raise RuntimeError("nested commit construction still depends on escapes")
TESTS.write_text(tests, encoding="utf-8")

validator = VALIDATOR.read_text(encoding="utf-8")
old_mode = "executable = bool(stat.S_IMODE(before.st_mode) & 0o111)"
new_mode = "executable = bool(stat.S_IMODE(before.st_mode) & stat.S_IXUSR)"
if validator.count(old_mode) != 1:
    raise RuntimeError(
        f"owner-execute expression differs: found {validator.count(old_mode)}"
    )
validator = validator.replace(old_mode, new_mode, 1)
VALIDATOR.write_text(validator, encoding="utf-8")

manifest = {
    "schema_version": "newsroom.increment5a.shallow-ci-regression.v3",
    "source_head": "cc20190f8548708d1a4c76458cfc9ce8767faed9",
    "product_paths": [
        "newsroom/tests/test_increment5a_profile_semantic_envelope.py",
        "scripts/sdlc/increment5_profile_validator.py",
    ],
    "invariants": {
        "head_race_requires_parent_history": False,
        "head_race_nested_escape_dependency": False,
        "alternate_commit_uses_expected_tree": True,
        "alternate_commit_identity_differs": True,
        "index_race_coverage_unchanged": True,
        "git_executable_mode_uses_owner_execute_bit": True,
        "group_only_execute_is_rejected": True,
    },
}
MANIFEST.write_text(
    json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
print(json.dumps(manifest, indent=2, sort_keys=True))
