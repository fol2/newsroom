#!/usr/bin/env python3
"""Materialize final completion-state and DEVAL-072 ownership corrections.

Disposable staging helper. It must never be merged into PR #255 or main.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE_HEAD = "05d290bc4a2b775fc8c4a24b77584e616b9a1708"
CONTRACT_DIGEST = (
    "sha256:51a3837ad9cdb70fe8aaa4242997b191c7e848bb1d391c6940cccc2bd45ba06c"
)
PLAN_DIGEST = (
    "sha256:c9d169c46a939573ffc6563704adfae973655f6394293ce591ec689f76a30959"
)

MODEL = ROOT / "newsroom/increment5/_traceability_model.py"
ANCHORS = ROOT / "newsroom/increment5/_traceability_anchors.py"
TRACEABILITY = ROOT / "newsroom/increment5/traceability.py"
TRACE_TEST = ROOT / "newsroom/tests/test_increment5a_traceability.py"
VALIDATOR = ROOT / "scripts/sdlc/increment5_profile_validator.py"
PROFILE_TEST = ROOT / "newsroom/tests/test_increment5a_profile_semantic_envelope.py"
DECISION = ROOT / "docs/decisions/2026-08-02-increment-5a-production-retrieval-contract.md"
EVALUATION = ROOT / "docs/evaluation/2026-08-02-increment-5-retrieval-evaluation-plan-v1.md"
OPERATIONS = ROOT / "docs/operations/increment-5-production-retrieval-contract.md"
TRACE_DOC = ROOT / "docs/traceability/increment-5-production-retrieval.md"
MANIFEST = ROOT / "increment5a-final-state-and-ownership-manifest.json"


def replace_exact(
    text: str,
    old: str,
    new: str,
    *,
    label: str,
    count: int = 1,
) -> str:
    actual = text.count(old)
    if actual != count:
        raise RuntimeError(f"{label}: expected {count} matches, found {actual}")
    return text.replace(old, new)


def update_model() -> None:
    text = MODEL.read_text(encoding="utf-8")
    text = replace_exact(
        text,
        '        "DEVAL-072",\n',
        "",
        label="remove DEVAL-072 from 5A delivery",
    )
    text = replace_exact(
        text,
        'if len(DEFERRED_TO_5E_REQUIREMENTS) != 122:\n    raise RuntimeError("5E closed-world remainder must contain 122 requirements")',
        'if len(DEFERRED_TO_5E_REQUIREMENTS) != 123:\n    raise RuntimeError("5E closed-world remainder must contain 123 requirements")',
        label="5E remainder size",
    )
    MODEL.write_text(text, encoding="utf-8")


def update_anchors() -> None:
    text = ANCHORS.read_text(encoding="utf-8")
    text = replace_exact(
        text,
        '    (f"{_EVALUATION}#public-artifact-safety", frozenset({"DEVAL-072"})),\n',
        '    (\n        "issue:#254:deferred:public-artifact-safety-validation-redaction-"\n        "and-release-controls",\n        frozenset({"DEVAL-072"}),\n    ),\n',
        label="DEVAL-072 executable delivery anchor",
    )
    ANCHORS.write_text(text, encoding="utf-8")


def update_traceability() -> None:
    text = TRACEABILITY.read_text(encoding="utf-8")
    text = replace_exact(
        text,
        """        Increment5DeliveryTrace.DELIVERED_IN_5A: 10,
        Increment5DeliveryTrace.DEFERRED_TO_5B: 0,
        Increment5DeliveryTrace.DEFERRED_TO_5C: 4,
        Increment5DeliveryTrace.DEFERRED_TO_5D: 11,
        Increment5DeliveryTrace.DEFERRED_TO_5E: 122,
""",
        """        Increment5DeliveryTrace.DELIVERED_IN_5A: 9,
        Increment5DeliveryTrace.DEFERRED_TO_5B: 0,
        Increment5DeliveryTrace.DEFERRED_TO_5C: 4,
        Increment5DeliveryTrace.DEFERRED_TO_5D: 11,
        Increment5DeliveryTrace.DEFERRED_TO_5E: 123,
""",
        label="traceability expected counts",
    )
    marker = '''        "TRI-028": (
            "issue:#254:deferred:urgent-degraded-retrieval-requires-durable-"
            "later-reconciliation"
        ),
'''
    addition = marker + '''        "DEVAL-072": (
            "issue:#254:deferred:public-artifact-safety-validation-redaction-"
            "and-release-controls"
        ),
'''
    text = replace_exact(
        text,
        marker,
        addition,
        label="critical 5E DEVAL-072 invariant",
    )
    TRACEABILITY.write_text(text, encoding="utf-8")


def update_traceability_tests() -> None:
    text = TRACE_TEST.read_text(encoding="utf-8")
    text = replace_exact(
        text,
        """        Increment5DeliveryTrace.DELIVERED_IN_5A: 10,
        Increment5DeliveryTrace.DEFERRED_TO_5C: 4,
        Increment5DeliveryTrace.DEFERRED_TO_5D: 11,
        Increment5DeliveryTrace.DEFERRED_TO_5E: 122,
""",
        """        Increment5DeliveryTrace.DELIVERED_IN_5A: 9,
        Increment5DeliveryTrace.DEFERRED_TO_5C: 4,
        Increment5DeliveryTrace.DEFERRED_TO_5D: 11,
        Increment5DeliveryTrace.DEFERRED_TO_5E: 123,
""",
        label="test delivery counts",
    )
    insertion = '''

def test_public_artifact_safety_is_executable_5e_work() -> None:
    row = _rows()["DEVAL-072"]
    assert row.decision_trace is Increment5DecisionTrace.BOUND_BY_5A
    assert row.delivery_trace is Increment5DeliveryTrace.DEFERRED_TO_5E
    assert row.delivery_issue == 254
    assert row.decision_anchor == (
        "issue:#254:deferred:public-artifact-safety-validation-redaction-"
        "and-release-controls"
    )

'''
    anchor = "\ndef test_decision_map_has_no_runtime_approval_or_admission_state() -> None:\n"
    text = replace_exact(
        text,
        anchor,
        insertion + anchor,
        label="DEVAL-072 ownership regression",
    )
    TRACE_TEST.write_text(text, encoding="utf-8")


def update_validator() -> None:
    text = VALIDATOR.read_text(encoding="utf-8")
    old = '''def _require_exact_code_tree(
    expected_commit: str,
    expected_tree: str,
) -> tuple[_TrustedGitProducer, str, str]:
    """Bind HEAD and reject tracked changes before repository imports exist."""

    git = _TrustedGitProducer()
    actual_commit = _git_sha(git, "HEAD^{commit}", "code commit SHA")
    actual_tree = _git_sha(git, "HEAD^{tree}", "code tree SHA")
    if actual_commit != expected_commit:
        raise ProfileInputError("code commit SHA differs from expected identity")
    if actual_tree != expected_tree:
        raise ProfileInputError("code tree SHA differs from expected identity")
    tracked_status = _run_git(
        git,
        "status",
        "--porcelain=v1",
        "--untracked-files=no",
    )
    if tracked_status:
        raise ProfileInputError("tracked repository checkout differs from HEAD")
    return git, actual_commit, actual_tree
'''
    new = '''def _require_stable_clean_code_tree(
    git: _TrustedGitProducer,
    expected_commit: str,
    expected_tree: str,
) -> tuple[str, str]:
    """Require one exact commit/tree and a clean tracked checkout now."""

    actual_commit = _git_sha(git, "HEAD^{commit}", "code commit SHA")
    actual_tree = _git_sha(git, "HEAD^{tree}", "code tree SHA")
    if actual_commit != expected_commit:
        raise ProfileInputError("code commit SHA differs from expected identity")
    if actual_tree != expected_tree:
        raise ProfileInputError("code tree SHA differs from expected identity")
    tracked_status = _run_git(
        git,
        "status",
        "--porcelain=v1",
        "--untracked-files=no",
    )
    if tracked_status:
        raise ProfileInputError("tracked repository checkout differs from HEAD")
    return actual_commit, actual_tree


def _require_exact_code_tree(
    expected_commit: str,
    expected_tree: str,
) -> tuple[_TrustedGitProducer, str, str]:
    """Bind HEAD and reject tracked changes before repository imports exist."""

    git = _TrustedGitProducer()
    actual_commit, actual_tree = _require_stable_clean_code_tree(
        git,
        expected_commit,
        expected_tree,
    )
    return git, actual_commit, actual_tree
'''
    text = replace_exact(
        text,
        old,
        new,
        label="shared stable code-tree invariant",
    )
    old_receipt = '''            receipt = {
                "authority_effect": "NONE",
                "code_commit_sha": actual_commit,
                "code_tree_sha": actual_tree,
                "manifest_digest": digest_bytes(raw),
                "production_activation_authorized": False,
                "profile_kind": profile_kind,
                "qualification_authority_granted": False,
                "schema_version": "newsroom.increment5.profile-validation-receipt.v3",
                "tracked_checkout_clean": True,
                "validation_code_origin": "CACHE_FREE_EXACT_GIT_ARCHIVE",
                "validation_scope": (
                    "REVIEWED_PROFILE_STRUCTURE_SEMANTICS_AND_EXACT_CODE_TREE"
                ),
                "worktree_imports_used": False,
            }
            sys.stdout.buffer.write(canonical_json_bytes(receipt) + b"\\n")
            return 0
'''
    new_receipt = '''            receipt = {
                "authority_effect": "NONE",
                "code_commit_sha": actual_commit,
                "code_tree_sha": actual_tree,
                "manifest_digest": digest_bytes(raw),
                "production_activation_authorized": False,
                "profile_kind": profile_kind,
                "qualification_authority_granted": False,
                "schema_version": "newsroom.increment5.profile-validation-receipt.v3",
                "tracked_checkout_clean": True,
                "validation_code_origin": "CACHE_FREE_EXACT_GIT_ARCHIVE",
                "validation_scope": (
                    "REVIEWED_PROFILE_STRUCTURE_SEMANTICS_AND_EXACT_CODE_TREE"
                ),
                "worktree_imports_used": False,
            }
            receipt_bytes = canonical_json_bytes(receipt) + b"\\n"
            _require_stable_clean_code_tree(
                git,
                actual_commit,
                actual_tree,
            )
            sys.stdout.buffer.write(receipt_bytes)
            return 0
'''
    text = replace_exact(
        text,
        old_receipt,
        new_receipt,
        label="completion-time code-tree revalidation",
    )
    VALIDATOR.write_text(text, encoding="utf-8")


def update_profile_tests() -> None:
    text = PROFILE_TEST.read_text(encoding="utf-8")
    race_test = r'''


def test_receipt_rechecks_tracked_state_after_materialization_starts(
    tmp_path: Path,
) -> None:
    clone, _, _ = _clone_exact_head(tmp_path)
    configured = subprocess.run(
        ["git", "-C", str(clone), "config", "user.name", "receipt-race-test"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )
    assert configured.returncode == 0, configured.stderr.decode("utf-8")
    configured = subprocess.run(
        [
            "git",
            "-C",
            str(clone),
            "config",
            "user.email",
            "receipt-race-test@example.invalid",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )
    assert configured.returncode == 0, configured.stderr.decode("utf-8")

    for index in range(2):
        clone.joinpath("newsroom", f"receipt-race-padding-{index}.bin").write_bytes(
            b"x" * 12_000_000
        )
    committed = subprocess.run(
        [
            "git",
            "-C",
            str(clone),
            "add",
            "newsroom/receipt-race-padding-0.bin",
            "newsroom/receipt-race-padding-1.bin",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    assert committed.returncode == 0, committed.stderr.decode("utf-8")
    committed = subprocess.run(
        ["git", "-C", str(clone), "commit", "-m", "test: widen receipt race"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=60,
    )
    assert committed.returncode == 0, committed.stderr.decode("utf-8")
    clone_commit, clone_tree = _code_identity(clone)

    temp_parent = tmp_path / "validator-temp"
    temp_parent.mkdir()
    environment = _validator_environment()
    environment["TMPDIR"] = str(temp_parent)
    process = subprocess.Popen(
        [
            sys.executable,
            "-I",
            str(clone / _VALIDATOR_RELATIVE_PATH),
            "--expected-code-commit-sha",
            clone_commit,
            "--expected-code-tree-sha",
            clone_tree,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=clone,
        env=environment,
    )
    assert process.stdin is not None
    process.stdin.write(canonical_json_bytes(_fixture_manifest()))
    process.stdin.close()

    deadline = time.monotonic() + 20
    while not tuple(temp_parent.glob("newsroom-increment5-profile-*")):
        if process.poll() is not None:
            stdout = process.stdout.read() if process.stdout is not None else b""
            stderr = process.stderr.read() if process.stderr is not None else b""
            raise AssertionError(
                f"validator exited before materialization: {process.returncode}; "
                f"stdout={stdout!r}; stderr={stderr!r}"
            )
        if time.monotonic() >= deadline:
            process.kill()
            process.wait(timeout=5)
            raise AssertionError("validator never entered exact-tree materialization")
        time.sleep(0.002)

    profile_source = clone / "newsroom/increment5/profiles.py"
    profile_source.write_text(
        profile_source.read_text(encoding="utf-8")
        + "\nraise RuntimeError('completion-time tracked change executed')\n",
        encoding="utf-8",
    )

    assert process.stdout is not None and process.stderr is not None
    stdout = process.stdout.read()
    stderr = process.stderr.read()
    returncode = process.wait(timeout=30)
    assert returncode == 2
    assert stderr == (
        b"increment5 profile validation failed: "
        b"tracked repository checkout differs from HEAD\n"
    )
    assert stdout == b""

'''
    anchor = "\ndef test_validator_materializes_exact_tree_before_repository_import() -> None:\n"
    text = replace_exact(
        text,
        anchor,
        race_test + anchor,
        label="completion-time cleanliness regression",
    )
    text = replace_exact(
        text,
        "import subprocess\nimport sys\n",
        "import subprocess\nimport sys\nimport time\n",
        label="test time import",
    )
    source_assertion = '''    receipt_bytes = source.index(
        "receipt_bytes = canonical_json_bytes(receipt) + b\\\"\\\\n\\\""
    )
    final_stability_check = source.index(
        "_require_stable_clean_code_tree(",
        receipt_bytes,
    )
    receipt_write = source.index(
        "sys.stdout.buffer.write(receipt_bytes)",
        final_stability_check,
    )
    assert receipt_bytes < final_stability_check < receipt_write
'''
    marker = '''    assert "selectors.DefaultSelector()" in source
    assert "stdout=subprocess.PIPE" in source
'''
    text = replace_exact(
        text,
        marker,
        marker + source_assertion,
        label="pre-receipt source order invariant",
    )
    PROFILE_TEST.write_text(text, encoding="utf-8")


def update_docs() -> None:
    decision = DECISION.read_text(encoding="utf-8")
    decision = replace_exact(decision, "- 5A / #250 — 10;", "- 5A / #250 — 9;", label="decision 5A count")
    decision = replace_exact(
        decision,
        "- **5E / #254 — the exact closed-world remainder of 122 requirements.**",
        "- **5E / #254 — the exact closed-world remainder of 123 requirements.**",
        label="decision 5E count",
    )
    decision = replace_exact(
        decision,
        """`validation_code_origin=CACHE_FREE_EXACT_GIT_ARCHIVE`, and
`worktree_imports_used=false` while stating:
""",
        """`validation_code_origin=CACHE_FREE_EXACT_GIT_ARCHIVE`, and
`worktree_imports_used=false`. Immediately before receipt emission, the same
trusted producer rechecks the exact commit, tree, and tracked-clean status; any
completion-time drift emits no receipt. The receipt states:
""",
        label="decision completion-time receipt semantics",
    )
    decision = replace_exact(
        decision,
        """The exact dataset manifest and label/adjudication policy are frozen in the
Epoch before execution. 5E owns the complete event-level universe, prospective
and contemporaneous labels, negative/failure sampling, authorised human review,
practical blinding, independent review or adjudication, and retained
disagreement required by `DEVAL-020`–`DEVAL-033`.
""",
        """The exact dataset manifest and label/adjudication policy are frozen in the
Epoch before execution. 5E owns the complete event-level universe, prospective
and contemporaneous labels, negative/failure sampling, authorised human review,
practical blinding, independent review or adjudication, and retained
disagreement required by `DEVAL-020`–`DEVAL-033`.

5A also freezes the `DEVAL-072` public-artifact safety rule but does not claim
its executable delivery. 5E/#254 must implement and retain dataset, manifest,
report, receipt, regression-case, log, index, and context validation/redaction
and release controls before that requirement can close.
""",
        label="decision DEVAL-072 boundary",
    )
    DECISION.write_text(decision, encoding="utf-8")

    evaluation = EVALUATION.read_text(encoding="utf-8")
    evaluation = replace_exact(
        evaluation,
        """Protected material may be represented only through permitted hashes, protected
references, bounded permitted extracts, or independently reproducible fixtures.
A safety or rights omission blocks the Run; final-report redaction cannot repair
prohibited material entering an index, log, or retained context.
""",
        """Protected material may be represented only through permitted hashes, protected
references, bounded permitted extracts, or independently reproducible fixtures.
A safety or rights omission blocks the Run; final-report redaction cannot repair
prohibited material entering an index, log, or retained context.

This section freezes the rule in 5A; it is not executable public-artifact safety
evidence. `DEVAL-072` belongs to 5E/#254, which must implement and retain the
validators, redaction/rejection receipts, release gates, and negative tests over
all repository-visible and retained artifact classes before reporting delivery.
""",
        label="evaluation DEVAL-072 delivery boundary",
    )
    EVALUATION.write_text(evaluation, encoding="utf-8")

    operations = OPERATIONS.read_text(encoding="utf-8")
    operations = replace_exact(
        operations,
        """`production_activation_authorized=false`. The receipt tree must equal the
frozen Epoch tree; mismatch is `NOT_EVALUATED`. It is necessary profile
evidence, never sufficient qualification evidence.
""",
        """`production_activation_authorized=false`. Immediately before writing the
receipt, the validator rechecks the exact commit, tree, trusted Git identity,
and tracked-clean state; any completion-time drift emits no receipt. The receipt
tree must equal the frozen Epoch tree; mismatch is `NOT_EVALUATED`. It is
necessary profile evidence, never sufficient qualification evidence.
""",
        label="operations completion-time receipt semantics",
    )
    operations = replace_exact(
        operations,
        "The exact delivery split is `10 / 0 / 4 / 11 / 122 / 7 / 1` for 5A, 5B, 5C,\n",
        "The exact delivery split is `9 / 0 / 4 / 11 / 123 / 7 / 1` for 5A, 5B, 5C,\n",
        label="operations delivery split",
    )
    operations = replace_exact(
        operations,
        """  isolation and system outage semantics; production/canary/live-shadow
  GraphRAG enforcement; rollback and rebuild; and actual-service
  qualification.
""",
        """  isolation and system outage semantics; production/canary/live-shadow
  GraphRAG enforcement; executable public-artifact validation, redaction, and
  release controls; rollback and rebuild; and actual-service qualification.
""",
        label="operations 5E artifact safety ownership",
    )
    OPERATIONS.write_text(operations, encoding="utf-8")

    trace_doc = TRACE_DOC.read_text(encoding="utf-8")
    replacements = (
        ("5A contains the ten contract, Plan, profile, non-activation, and", "5A contains the nine contract, Plan, profile, non-activation, and", "trace doc 5A prose"),
        ("remaining 122 requirements belong to 5E", "remaining 123 requirements belong to 5E", "trace doc remainder prose"),
        ("| 5A / #250 | 10 |", "| 5A / #250 | 9 |", "trace doc 5A table"),
        ("| 5E / #254 | 122 |", "| 5E / #254 | 123 |", "trace doc 5E table"),
        ("`DEVAL-010`, `DEVAL-011`, `DEVAL-012`, `DEVAL-051`, `DEVAL-072`,\n`DOPS-076`,", "`DEVAL-010`, `DEVAL-011`, `DEVAL-012`, `DEVAL-051`, `DOPS-076`,", "trace doc delivered list"),
    )
    for old, new, label in replacements:
        trace_doc = replace_exact(trace_doc, old, new, label=label)
    trace_doc = replace_exact(
        trace_doc,
        """The Epoch freezes the exact dataset manifest and label/adjudication policy before
a Run. 5E must execute and retain these controls; a model, provider, legacy
pipeline, feed, index, or metric cannot become sole ground truth.
""",
        """The Epoch freezes the exact dataset manifest and label/adjudication policy before
a Run. 5E must execute and retain these controls; a model, provider, legacy
pipeline, feed, index, or metric cannot become sole ground truth.

`DEVAL-072` also belongs to 5E. The 5A plan freezes the public-artifact safety
rule, but #254 must implement validation, redaction/rejection receipts, release
gates, and negative tests over datasets, manifests, reports, receipts,
regression cases, logs, indexes, and retained contexts before delivery exists.
""",
        label="trace doc DEVAL-072 ownership",
    )
    trace_doc = replace_exact(
        trace_doc,
        "- `DEVAL-046` → 5E/#254: all six error classes are reported separately with counts, opportunity denominators, and rates.\n",
        "- `DEVAL-046` → 5E/#254: all six error classes are reported separately with counts, opportunity denominators, and rates.\n- `DEVAL-072` → 5E/#254: prose policy is not executable artifact inspection, redaction, release-gate, or negative-test evidence.\n",
        label="trace doc key DEVAL-072 boundary",
    )
    TRACE_DOC.write_text(trace_doc, encoding="utf-8")


def main() -> None:
    update_model()
    update_anchors()
    update_traceability()
    update_traceability_tests()
    update_validator()
    update_profile_tests()
    update_docs()
    changed = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (
            MODEL,
            ANCHORS,
            TRACEABILITY,
            TRACE_TEST,
            VALIDATOR,
            PROFILE_TEST,
            DECISION,
            EVALUATION,
            OPERATIONS,
            TRACE_DOC,
        )
    )
    manifest = {
        "changed_paths": changed,
        "completion_state_boundary": {
            "initial_exact_tree_check": True,
            "pre_receipt_exact_tree_recheck": True,
            "receipt_on_completion_time_drift": False,
            "shared_invariant": "_require_stable_clean_code_tree",
        },
        "contract_digest_unchanged": CONTRACT_DIGEST,
        "delivery_counts": {
            "5A": 9,
            "5B": 0,
            "5C": 4,
            "5D": 11,
            "5E": 123,
            "INCREMENT_4": 7,
            "OUTSIDE_ACTIVATION": 1,
            "TOTAL": 155,
        },
        "evaluation_plan_digest_unchanged": PLAN_DIGEST,
        "public_artifact_safety": {
            "decision_bound_by_5A": True,
            "delivery_issue": 254,
            "delivery_trace": "DEFERRED_TO_5E",
            "requirement": "DEVAL-072",
        },
        "schema_version": "newsroom.increment5a.final-state-and-ownership.v1",
        "source_head": SOURCE_HEAD,
    }
    MANIFEST.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
