#!/usr/bin/env python3
"""Complete the snapshot-scoped receipt materialization after v1's known anchor miss.

Disposable support helper. Never merge this file into PR #255 or main.
"""
from __future__ import annotations

import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[2]
V1 = Path(__file__).with_name("_staging_increment5_snapshot_receipt_v1.py")
TESTS = ROOT / "newsroom/tests/test_increment5a_profile_semantic_envelope.py"
DECISION = ROOT / "docs/decisions/2026-08-02-increment-5a-production-retrieval-contract.md"
EVALUATION = ROOT / "docs/evaluation/2026-08-02-increment-5-retrieval-evaluation-plan-v1.md"
OPERATIONS = ROOT / "docs/operations/increment-5-production-retrieval-contract.md"
MANIFEST = ROOT / "increment5a-snapshot-receipt-manifest.json"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


try:
    runpy.run_path(str(V1), run_name="__main__")
except RuntimeError as exc:
    expected = "receipt write and flush order: expected one match, found 0"
    if str(exc) != expected:
        raise

# v1 has already written the validator. Its test changes were still in memory
# when the old source-order anchor failed, so apply those changes here with the
# exact reviewed source shape.
tests = TESTS.read_text(encoding="utf-8")
tests = replace_once(
    tests,
    '        "schema_version": "newsroom.increment5.profile-validation-receipt.v6",\n',
    '        "schema_version": "newsroom.increment5.profile-validation-receipt.v7",\n',
    "expected receipt schema",
)
tests = replace_once(
    tests,
    '        "tracked_checkout_clean": True,\n',
    '        "checkout_snapshot_verified_before_receipt_write": True,\n'
    '        "completion_time_checkout_state_attested": False,\n',
    "expected receipt checkout semantics",
)
tests = replace_once(
    tests,
    '            "REVIEWED_PROFILE_STRUCTURE_SEMANTICS_AND_EXACT_CODE_TREE"\n',
    '            "REVIEWED_PROFILE_STRUCTURE_SEMANTICS_AND_PREWRITE_CODE_TREE_SNAPSHOT"\n',
    "expected validation scope",
)

race_test = r'''def test_receipt_handoff_does_not_attest_completion_time_checkout_state(
    tmp_path: Path,
) -> None:
    clone, clone_commit, clone_tree = _clone_exact_head(tmp_path)
    probe = """
import io, json, sys
from pathlib import Path
sys.argv[0] = "-"
source = Path(sys.argv[1]).read_bytes()
namespace = {"__name__": "validator-handoff-probe", "__file__": sys.argv[1]}
exec(compile(source, "-", "exec"), namespace)
runtime = namespace["_TrustedPythonRuntime"]()
root = Path(sys.argv[2])
view = namespace["_TrustedRepositoryView"](root, root / ".git", root / ".git/index")
blob = namespace["_git_sha"](
    view,
    f"{sys.argv[3]}:scripts/sdlc/increment5_profile_validator.py",
    "validator blob SHA",
)
class MutatingOutput(io.BytesIO):
    def write(self, data):
        tracked = root / "scripts/sdlc/increment5_profile_validator.py"
        tracked.write_text(
            tracked.read_text(encoding="utf-8") + "\\n# changed during handoff\\n",
            encoding="utf-8",
        )
        return super().write(data)
output = MutatingOutput()
receipt = {
    "checkout_snapshot_verified_before_receipt_write": True,
    "completion_time_checkout_state_attested": False,
}
namespace["_emit_receipt"](
    runtime, view, sys.argv[3], sys.argv[4], blob, receipt, output
)
sys.stdout.buffer.write(output.getvalue())
"""
    completed = subprocess.run(
        [
            str(_TRUSTED_PYTHON),
            "-I",
            "-S",
            "-c",
            probe,
            str(clone / _VALIDATOR_RELATIVE_PATH),
            str(clone),
            clone_commit,
            clone_tree,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        cwd=clone,
        env={"LC_ALL": "C", "PYTHONUTF8": "1"},
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8")
    receipt = json.loads(completed.stdout.decode("utf-8"))
    assert receipt == {
        "checkout_snapshot_verified_before_receipt_write": True,
        "completion_time_checkout_state_attested": False,
    }
    assert "tracked_checkout_clean" not in receipt
    assert (
        clone / "scripts/sdlc/increment5_profile_validator.py"
    ).read_text(encoding="utf-8").endswith("# changed during handoff\n")


'''
anchor = "def test_validator_source_has_closed_outer_launch_and_repository_boundaries() -> None:\n"
if tests.count(anchor) != 1:
    raise RuntimeError("handoff-race test insertion anchor differs")
tests = tests.replace(anchor, race_test + anchor, 1)
tests = replace_once(
    tests,
    '    assert \'"validation_code_delivery": "EXACT_COMMIT_GIT_BLOB_STDIN"\' in source\n',
    '    assert \'"validation_code_delivery": "EXACT_COMMIT_GIT_BLOB_STDIN"\' in source\n'
    '    assert \'"checkout_snapshot_verified_before_receipt_write": True\' in source\n'
    '    assert \'"completion_time_checkout_state_attested": False\' in source\n'
    '    assert \'"tracked_checkout_clean"\' not in source\n',
    "source-level receipt semantics",
)
tests = replace_once(
    tests,
    '''    assert emit.index("runtime.require_unchanged()") < emit.index(
        "repository.require_stable_clean_tree("
    ) < emit.index("repository.require_validator_blob(") < emit.index(
        "output.write(raw)"
    )
''',
    '''    assert emit.index("runtime.require_unchanged()") < emit.index(
        "repository.require_stable_clean_tree("
    ) < emit.index("repository.require_validator_blob(") < emit.index(
        "output.write(raw)"
    ) < emit.index("output.flush()")
''',
    "receipt write and flush order",
)
TESTS.write_text(tests, encoding="utf-8")

old_snapshot = (
    "The clean-tree decision does not trust Git's index stat cache. The validator "
    "compares the stage-zero index inventory directly with the exact commit tree, "
    "then computes the Git blob identity and executable/symlink mode of every "
    "tracked worktree entry with the Python standard library. Local `trustctime`, "
    "`checkStat`, `ignoreStat`, `fileMode`, fsmonitor, restored mtimes, and same-size "
    "edits therefore cannot create a false `tracked_checkout_clean=true` claim."
)
new_snapshot = (
    "The content-addressed checkout comparison is a bounded snapshot completed "
    "before receipt write, not a lock over mutable worktree, index, or HEAD state. "
    "The receipt therefore records "
    "`checkout_snapshot_verified_before_receipt_write=true` and explicitly records "
    "`completion_time_checkout_state_attested=false`; it never claims "
    "`tracked_checkout_clean`. A concurrent change after the final snapshot cannot "
    "falsify the receipt because the signed outer workflow relies on immutable "
    "commit, tree, validator-blob, manifest, and receipt identities rather than a "
    "mutable checkout-at-handoff assertion."
)
for path in (DECISION, EVALUATION, OPERATIONS):
    text = path.read_text(encoding="utf-8")
    if old_snapshot not in text:
        raise RuntimeError(f"snapshot paragraph differs: {path}")
    text = text.replace(old_snapshot, new_snapshot, 1)
    text = text.replace("Receipt v6", "Receipt v7")
    text = text.replace(
        "the same repository/index invariant are rerun immediately before output, "
        "so runtime or completion-time drift emits no receipt.",
        "the same repository/index snapshot is rerun immediately before receipt "
        "write. The receipt does not attest mutable checkout state at completion "
        "or after handoff.",
    )
    path.write_text(text, encoding="utf-8")

manifest = {
    "schema_version": "newsroom.increment5a.snapshot-scoped-receipt.v1",
    "source_head": "3c573411ed01077fd9164f2fdc46da3b704c5fed",
    "product_paths": [
        "docs/decisions/2026-08-02-increment-5a-production-retrieval-contract.md",
        "docs/evaluation/2026-08-02-increment-5-retrieval-evaluation-plan-v1.md",
        "docs/operations/increment-5-production-retrieval-contract.md",
        "newsroom/tests/test_increment5a_profile_semantic_envelope.py",
        "scripts/sdlc/increment5_profile_validator.py",
    ],
    "receipt_boundary": {
        "immutable_git_identities_bound": True,
        "snapshot_verified_before_receipt_write": True,
        "completion_time_checkout_state_attested": False,
        "tracked_checkout_clean_claim_present": False,
        "outer_signed_workflow_binding_required": True,
        "authority_effect": "NONE",
    },
}
MANIFEST.write_text(
    json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
print(json.dumps(manifest, indent=2, sort_keys=True))
