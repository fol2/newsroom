#!/usr/bin/env python3
"""Align reviewed receipt documentation with the tested v7 boundary.

Disposable support helper. Never merge this file into PR #255 or main.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVALUATION = ROOT / "docs/evaluation/2026-08-02-increment-5-retrieval-evaluation-plan-v1.md"
DECISION = ROOT / "docs/decisions/2026-08-02-increment-5a-production-retrieval-contract.md"
TESTS = ROOT / "newsroom/tests/test_increment5a_profile_semantic_envelope.py"
MANIFEST = ROOT / "increment5a-final-doc-consistency-manifest.json"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


evaluation = EVALUATION.read_text(encoding="utf-8")
evaluation = replace_once(
    evaluation,
    """`NOT_EVALUATED`. Every profile-validation receipt is v5 and is produced by
`/usr/bin/python3 -I -S`: isolated mode is mandatory, `site` initialization is
disabled, and the root-owned system interpreter identity is checked before
validation and immediately before output. No environment Python package,
`.pth` startup code, or repository module participates. One explicit Git
directory, index and work tree are bound; replacement objects, fsmonitor,
assume-unchanged and skip-worktree state cannot change or conceal the evidence
inputs. The validator reads only exact digest-pinned contract/schema blobs and
rechecks interpreter, commit, tree, index flags and tracked cleanliness
immediately before output. The receipt tree must equal the Epoch's frozen
`code_tree_sha`; missing, hidden, changed or mismatched state is
`NOT_EVALUATED`.""",
    """`NOT_EVALUATED`. Every profile-validation receipt is v7 and is produced by
`/usr/bin/python3 -I -S`: isolated mode is mandatory, `site` initialization is
disabled, and the root-owned system interpreter identity is checked before
validation and immediately before receipt write. No environment Python package,
`.pth` startup code, or repository module participates. One explicit Git
directory, index, and work tree are bound; replacement objects, fsmonitor,
assume-unchanged, and skip-worktree state cannot change or conceal the evidence
inputs. The validator reads only exact digest-pinned contract/schema blobs and
performs a final content-addressed checkout snapshot immediately before receipt
write. Receipt v7 records
`checkout_snapshot_verified_before_receipt_write=true` and
`completion_time_checkout_state_attested=false`; it contains no
`tracked_checkout_clean` claim and does not attest mutable checkout, index, or
HEAD state at completion or after handoff. The receipt tree must equal the
Epoch's frozen `code_tree_sha`; missing, hidden, changed, or mismatched state is
`NOT_EVALUATED`.""",
    "evaluation receipt protocol",
)
EVALUATION.write_text(evaluation, encoding="utf-8")


decision = DECISION.read_text(encoding="utf-8")
decision = replace_once(
    decision,
    """Interpreter identity and the same
repository/index invariant are rerun immediately before output, so runtime or
completion-time drift emits no receipt.""",
    """Interpreter identity and the same repository/index snapshot are rerun
immediately before receipt write. Drift detected during that final prewrite
snapshot emits no receipt; mutable checkout, index, or HEAD changes during or
after output handoff are explicitly not attested.""",
    "decision prewrite drift guarantee",
)
DECISION.write_text(decision, encoding="utf-8")


tests = TESTS.read_text(encoding="utf-8")
regression = '''\n\ndef test_reviewed_documents_bind_receipt_v7_snapshot_semantics() -> None:\n    evaluation = (\n        _REPOSITORY_ROOT\n        / "docs/evaluation/2026-08-02-increment-5-retrieval-evaluation-plan-v1.md"\n    ).read_text(encoding="utf-8")\n    decision = (\n        _REPOSITORY_ROOT\n        / "docs/decisions/2026-08-02-increment-5a-production-retrieval-contract.md"\n    ).read_text(encoding="utf-8")\n\n    assert "Every profile-validation receipt is v7" in evaluation\n    assert "Every profile-validation receipt is v5" not in evaluation\n    assert "checkout_snapshot_verified_before_receipt_write=true" in evaluation\n    assert "completion_time_checkout_state_attested=false" in evaluation\n    assert "`tracked_checkout_clean` claim" in evaluation\n    assert "does not attest mutable checkout" in evaluation\n    assert "completion-time drift emits no receipt" not in decision\n    assert "Drift detected during that final prewrite" in decision\n    assert "after output handoff are explicitly not attested" in decision\n'''
if "def test_reviewed_documents_bind_receipt_v7_snapshot_semantics" in tests:
    raise RuntimeError("documentation consistency regression already exists")
tests += regression
TESTS.write_text(tests, encoding="utf-8")

manifest = {
    "schema_version": "newsroom.increment5a.final-doc-consistency.v1",
    "source_head": "1ac9d3ad45fdd6eee31bbf783ce8ef6f93935cb2",
    "product_paths": [
        "docs/decisions/2026-08-02-increment-5a-production-retrieval-contract.md",
        "docs/evaluation/2026-08-02-increment-5-retrieval-evaluation-plan-v1.md",
        "newsroom/tests/test_increment5a_profile_semantic_envelope.py",
    ],
    "invariants": {
        "receipt_schema": "newsroom.increment5.profile-validation-receipt.v7",
        "snapshot_verified_before_receipt_write": True,
        "completion_time_checkout_state_attested": False,
        "tracked_checkout_clean_claim_present": False,
        "completion_drift_suppression_scope": "FINAL_PREWRITE_SNAPSHOT_ONLY",
    },
}
MANIFEST.write_text(
    json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
print(json.dumps(manifest, indent=2, sort_keys=True))
