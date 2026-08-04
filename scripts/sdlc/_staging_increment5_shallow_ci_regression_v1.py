#!/usr/bin/env python3
"""Make the Increment 5A HEAD-race regression independent of Git history depth.

Disposable support helper. Never merge this file into PR #255 or main.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "newsroom/tests/test_increment5a_profile_semantic_envelope.py"
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
        commit_bytes = (
            f"tree {sys.argv[4]}\\n"
            "author Snapshot Race <snapshot@example.invalid> 0 +0000\\n"
            "committer Snapshot Race <snapshot@example.invalid> 0 +0000\\n"
            "\\n"
            "snapshot race\\n"
        ).encode("ascii")
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

if '["/usr/bin/git", "-C", str(root), "rev-parse", "HEAD^"]' in tests:
    raise RuntimeError("history-dependent HEAD race remains")
if '"hash-object",\n                "-t", "commit", "-w", "--stdin"' not in tests:
    raise RuntimeError("synthetic same-tree commit race is absent")

TESTS.write_text(tests, encoding="utf-8")

manifest = {
    "schema_version": "newsroom.increment5a.shallow-ci-regression.v1",
    "source_head": "cc20190f8548708d1a4c76458cfc9ce8767faed9",
    "product_paths": [
        "newsroom/tests/test_increment5a_profile_semantic_envelope.py",
    ],
    "invariants": {
        "head_race_requires_parent_history": False,
        "alternate_commit_uses_expected_tree": True,
        "alternate_commit_identity_differs": True,
        "index_race_coverage_unchanged": True,
        "validator_product_blob_unchanged": True,
    },
}
MANIFEST.write_text(
    json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
print(json.dumps(manifest, indent=2, sort_keys=True))
