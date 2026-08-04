#!/usr/bin/env python3
"""Close the final Increment 5A prewrite snapshot coherence boundary.

Disposable support helper. Never merge this file into PR #255 or main.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "scripts/sdlc/increment5_profile_validator.py"
TESTS = ROOT / "newsroom/tests/test_increment5a_profile_semantic_envelope.py"
MANIFEST = ROOT / "increment5a-snapshot-coherence-manifest.json"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


validator = VALIDATOR.read_text(encoding="utf-8")
validator = replace_once(
    validator,
    """This
stdlib-only inner process then binds the exact repository, validator blob,
manifest bytes, runtime, and completion-time state into a non-authoritative
receipt. The receipt cannot authenticate its own executed source and grants no
authority without the separately signed outer-launch evidence.""",
    """This stdlib-only inner process then binds the exact repository, validator
blob, manifest bytes, runtime, and a bounded prewrite checkout snapshot into a
non-authoritative receipt. It does not attest mutable checkout, index, or HEAD
state at completion or after handoff. The receipt cannot authenticate its own
executed source and grants no authority without the separately signed
outer-launch evidence.""",
    "validator module contract",
)
validator = replace_once(
    validator,
    """    def require_stable_clean_tree(self, commit: str, tree: str) -> None:
        actual_commit = _git_sha(self, "HEAD^{commit}", "code commit SHA")
        actual_tree = _git_sha(self, "HEAD^{tree}", "code tree SHA")
        if actual_commit != commit:
            raise ProfileInputError("code commit SHA differs from expected identity")
        if actual_tree != tree:
            raise ProfileInputError("code tree SHA differs from expected identity")
        self._reject_hidden_index_flags()
        expected = self._read_expected_tree(commit)
        self._require_index_matches_tree(expected)
        self._require_worktree_matches_tree(expected)
""",
    """    def _require_commit_tree_identity(self, commit: str, tree: str) -> None:
        actual_commit = _git_sha(self, "HEAD^{commit}", "code commit SHA")
        actual_tree = _git_sha(self, "HEAD^{tree}", "code tree SHA")
        if actual_commit != commit:
            raise ProfileInputError("code commit SHA differs from expected identity")
        if actual_tree != tree:
            raise ProfileInputError("code tree SHA differs from expected identity")

    def require_stable_clean_tree(self, commit: str, tree: str) -> None:
        self._require_commit_tree_identity(commit, tree)
        self._reject_hidden_index_flags()
        expected = self._read_expected_tree(commit)
        self._require_index_matches_tree(expected)
        self._require_worktree_matches_tree(expected)

        # The worktree traversal is intentionally bounded but can be long. A
        # concurrent HEAD or index change during that traversal must not leave
        # the prewrite snapshot associated with stale repository metadata.
        self._require_commit_tree_identity(commit, tree)
        self._reject_hidden_index_flags()
        self._require_index_matches_tree(expected)
""",
    "coherent repository snapshot",
)
VALIDATOR.write_text(validator, encoding="utf-8")


tests = TESTS.read_text(encoding="utf-8")
tests = replace_once(
    tests,
    """    assert "_reject_hidden_index_flags" in source
    assert "require_validator_blob" in source
""",
    """    assert "_reject_hidden_index_flags" in source
    assert "require_validator_blob" in source
    assert "bounded prewrite checkout snapshot" in source
    assert "completion-time state into a non-authoritative" not in source
    stable = source.split(
        "def require_stable_clean_tree(self, commit: str, tree: str) -> None:",
        1,
    )[1].split("@staticmethod", 1)[0]
    assert stable.count("self._require_commit_tree_identity(commit, tree)") == 2
    assert stable.count("self._reject_hidden_index_flags()") == 2
    assert stable.count("self._require_index_matches_tree(expected)") == 2
    assert stable.index("self._require_worktree_matches_tree(expected)") < stable.rindex(
        "self._require_commit_tree_identity(commit, tree)"
    )
""",
    "validator source coherence assertions",
)
regression = '''\n\n@pytest.mark.parametrize(\n    ("race", "expected_error"),\n    (\n        ("HEAD", "code commit SHA differs from expected identity"),\n        ("INDEX", "tracked repository index differs from HEAD"),\n    ),\n)\ndef test_prewrite_snapshot_rechecks_head_and_index_after_worktree_hashing(\n    tmp_path: Path,\n    race: str,\n    expected_error: str,\n) -> None:\n    clone, clone_commit, clone_tree = _clone_exact_head(tmp_path)\n    probe = """\nimport subprocess, sys\nfrom pathlib import Path\nsys.argv[0] = "-"\nsource = Path(sys.argv[1]).read_bytes()\nnamespace = {"__name__": "validator-snapshot-race-probe", "__file__": sys.argv[1]}\nexec(compile(source, "-", "exec"), namespace)\nroot = Path(sys.argv[2])\nrepository_type = namespace["_TrustedRepositoryView"]\noriginal = repository_type._require_worktree_matches_tree\ndef mutate_repository_metadata(self, expected):\n    original(self, expected)\n    if sys.argv[5] == "HEAD":\n        parent = subprocess.run(\n            ["/usr/bin/git", "-C", str(root), "rev-parse", "HEAD^"],\n            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,\n        )\n        if parent.returncode != 0:\n            raise SystemExit(parent.stderr.decode("utf-8"))\n        changed = subprocess.run(\n            [\n                "/usr/bin/git", "-C", str(root), "update-ref", "HEAD",\n                parent.stdout.decode("ascii", errors="strict").strip(),\n            ],\n            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,\n        )\n    else:\n        changed = subprocess.run(\n            [\n                "/usr/bin/git", "-C", str(root), "update-index",\n                "--force-remove", "--",\n                "scripts/sdlc/increment5_profile_validator.py",\n            ],\n            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,\n        )\n    if changed.returncode != 0:\n        raise SystemExit(changed.stderr.decode("utf-8"))\nrepository_type._require_worktree_matches_tree = mutate_repository_metadata\nview = repository_type(root, root / ".git", root / ".git/index")\ntry:\n    view.require_stable_clean_tree(sys.argv[3], sys.argv[4])\nexcept namespace["ProfileInputError"] as exc:\n    if str(exc) != sys.argv[6]:\n        raise\nelse:\n    raise SystemExit("repository metadata race escaped the prewrite snapshot")\n"""\n    completed = subprocess.run(\n        [\n            str(_TRUSTED_PYTHON),\n            "-I",\n            "-S",\n            "-c",\n            probe,\n            str(clone / _VALIDATOR_RELATIVE_PATH),\n            str(clone),\n            clone_commit,\n            clone_tree,\n            race,\n            expected_error,\n        ],\n        stdout=subprocess.PIPE,\n        stderr=subprocess.PIPE,\n        check=False,\n        cwd=clone,\n        env={"LC_ALL": "C", "PYTHONUTF8": "1"},\n        timeout=30,\n    )\n    assert completed.returncode == 0, completed.stderr.decode("utf-8")\n'''
if "def test_prewrite_snapshot_rechecks_head_and_index_after_worktree_hashing" in tests:
    raise RuntimeError("snapshot-coherence regression already exists")
tests += regression
TESTS.write_text(tests, encoding="utf-8")

manifest = {
    "schema_version": "newsroom.increment5a.snapshot-coherence.v1",
    "source_head": "e34340b269469410c48b8202cd7a61f6cb95a8fd",
    "product_paths": [
        "scripts/sdlc/increment5_profile_validator.py",
        "newsroom/tests/test_increment5a_profile_semantic_envelope.py",
    ],
    "invariants": {
        "module_contract_scope": "BOUNDED_PREWRITE_CHECKOUT_SNAPSHOT",
        "completion_time_checkout_state_attested": False,
        "post_worktree_head_recheck": True,
        "post_worktree_hidden_index_flag_recheck": True,
        "post_worktree_index_tree_recheck": True,
    },
}
MANIFEST.write_text(
    json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
print(json.dumps(manifest, indent=2, sort_keys=True))
