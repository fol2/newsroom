#!/usr/bin/env python3
"""Align Increment 5A docs with the stdlib exact-Git-blob validator."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DECISION = ROOT / "docs/decisions/2026-08-02-increment-5a-production-retrieval-contract.md"
OPERATIONS = ROOT / "docs/operations/increment-5-production-retrieval-contract.md"
EVALUATION = ROOT / "docs/evaluation/2026-08-02-increment-5-retrieval-evaluation-plan-v1.md"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label} replacement count differs: {count}")
    return text.replace(old, new, 1)


def update_decision() -> None:
    text = DECISION.read_text(encoding="utf-8")
    old = '''Public builders are deterministic conveniences. Their private check returns
only `None` and is not admissible evidence. For 5E evidence, exact canonical
manifest bytes must be supplied inside the fresh exact-head signed workflow to:

```text
CODE_COMMIT_SHA="$(git rev-parse --verify 'HEAD^{commit}')"
CODE_TREE_SHA="$(git rev-parse --verify 'HEAD^{tree}')"
python -I scripts/sdlc/increment5_profile_validator.py \\
  --expected-code-commit-sha "$CODE_COMMIT_SHA" \\
  --expected-code-tree-sha "$CODE_TREE_SHA"
```

Before importing any Newsroom module, the validator resolves the actual Git
commit and tree, requires them to equal the caller-supplied identities, and
rejects staged or tracked differences. It does not resolve Git through caller
`PATH`. It selects only an allow-listed root-owned system executable whose file
and directory chain are not group- or world-writable, uses an absolute path,
neutralizes replacement refs, external attributes, hooks, fsmonitor and mutable
global/system configuration, and records the exact executable path and SHA-256
digest.

Ignored and untracked runtime artefacts are never used as code. The validator
streams a temporary `git archive` materialization from the exact commit through
a bounded pipe, terminates the producer before writing any byte beyond
67,108,864 bytes, removes partial output on every failure, rejects unsafe paths,
non-regular entries and tracked bytecode, disables bytecode writes, removes
checkout paths from the import search path, and verifies that every loaded
`newsroom.*` module came from the cache-free materialization.

It then rejects non-canonical JSON, duplicate names, identity drift, wrong
profile/eligibility pairs, widened budgets or effects, fixture substitution,
unsafe dataset state, and missing actual-service requirements. Its canonical v4
receipt binds the manifest digest, profile kind, `code_commit_sha`,
`code_tree_sha`, trusted Git path and digest,
`git_producer_policy=ROOT_OWNED_NON_WRITABLE_SYSTEM_PATH`,
`archive_streaming_enforced=true`, `archive_stream_limit_bytes=67108864`,
`tracked_checkout_clean=true`,
`validation_code_origin=CACHE_FREE_EXACT_GIT_ARCHIVE`, and
`worktree_imports_used=false` while stating:

- `authority_effect = NONE`;
- `qualification_authority_granted = false`; and
- `production_activation_authorized = false`.

The receipt is necessary profile evidence, never sufficient qualification
evidence. Its `code_tree_sha` must equal the frozen Epoch `code_tree_sha`, and
5E must freeze and compare the Git executable path/digest, producer policy and
archive limit inside the Epoch policy set. A missing or mismatched tree or
producer identity is `NOT_EVALUATED`. It grants no component, source, model,
provider, spend, write, production, or public-effect authority.
'''
    new = '''Public builders are deterministic conveniences. Their private check returns
only `None` and is not admissible evidence. A 5E evidence manifest is a bounded
canonical file. The fresh signed exact-head workflow resolves root-owned,
non-writable Git and Python executables, freezes their paths and SHA-256 digests,
and executes the validator only by streaming its exact commit blob to isolated,
no-site Python:

```text
GIT=/usr/bin/git
PYTHON=/absolute/root-owned/python
CODE_COMMIT_SHA=<frozen exact commit>
CODE_TREE_SHA=<frozen exact tree>
VALIDATOR_PATH=scripts/sdlc/increment5_profile_validator.py
VALIDATOR_DIGEST=<sha256 of exact validator blob>

"$GIT" --git-dir="$PWD/.git" --no-replace-objects \\
  cat-file blob "$CODE_COMMIT_SHA:$VALIDATOR_PATH" | \\
"$PYTHON" -I -S - \\
  --repository-root "$PWD" \\
  --manifest-path "$MANIFEST" \\
  --expected-code-commit-sha "$CODE_COMMIT_SHA" \\
  --expected-code-tree-sha "$CODE_TREE_SHA" \\
  --expected-validator-blob-digest "$VALIDATOR_DIGEST"
```

Direct checkout-file or `-c` execution is rejected. `-I -S` removes caller
`PYTHONPATH`, site initialization and site-packages. The validator imports only
the standard library, verifies that Python and Git satisfy the root-owned,
non-group/world-writable runtime policy, and records their exact paths and
digests. It never imports `newsroom`, `jsonschema`, or another third-party
package.

The validator resolves the supplied commit and tree without consulting `HEAD`,
the index or the worktree. It reads only bounded exact blobs for its own source,
the reviewed contract, and the four structural/public profile schemas. Every
blob is canonical and digest-bound; public schema bindings are reconstructed
with the standard library and compared exactly. Hidden checkout changes,
`assume-unchanged`, `skip-worktree`, ignored bytecode, untracked files, mutable
import paths and checkout code therefore cannot affect validation.

The canonical v5 receipt binds the manifest, profile, contract, selected schema,
commit/tree, validator blob, Python runtime and Git producer while stating:

- `validator_source_origin = EXACT_GIT_BLOB_PIPE`;
- `validator_launch_mode = PYTHON_ISOLATED_NO_SITE_STDIN`;
- `repository_object_access = EXACT_COMMIT_BLOBS_ONLY`;
- `stdlib_only = true` and `third_party_imports_used = false`;
- `worktree_or_index_used = false`;
- `authority_effect = NONE`;
- `qualification_authority_granted = false`; and
- `production_activation_authorized = false`.

The receipt is necessary profile evidence, never sufficient qualification
evidence. The signed workflow must retain the exact source-pipe command and the
Epoch policy set must freeze the commit/tree, validator blob, Python and Git
paths/digests and launch policy. Missing or mismatched evidence is
`NOT_EVALUATED`. The receipt grants no component, source, model, provider,
spend, write, production, or public-effect authority.
'''
    DECISION.write_text(
        replace_once(text, old, new, "decision exact-blob boundary"),
        encoding="utf-8",
    )


def update_operations() -> None:
    text = OPERATIONS.read_text(encoding="utf-8")
    old = '''Every 5E evidence manifest is canonical JSON validated inside the fresh
exact-head signed process with:

```text
CODE_COMMIT_SHA="$(git rev-parse --verify 'HEAD^{commit}')"
CODE_TREE_SHA="$(git rev-parse --verify 'HEAD^{tree}')"
python -I scripts/sdlc/increment5_profile_validator.py \\
  --expected-code-commit-sha "$CODE_COMMIT_SHA" \\
  --expected-code-tree-sha "$CODE_TREE_SHA"
```

The validator verifies the supplied Git commit and tree and rejects staged or
tracked differences before importing any Newsroom module. Git is selected only
from fixed root-owned, non-group/world-writable system paths; caller `PATH` is
ignored, mutable Git replacement/attribute/hook/configuration surfaces are
neutralized, and the exact Git executable path and SHA-256 digest are retained.

Validation code is streamed from an exact-commit `git archive` through a hard
67,108,864-byte generation cap. The producer is terminated before an overflow
chunk is written, partial output is removed, and ignored bytecode, untracked
runtime artefacts and checkout paths are never imported. Receipt v4 binds the
manifest, profile, commit/tree, trusted Git path/digest and producer policy,
`archive_streaming_enforced=true`, the exact archive limit,
`tracked_checkout_clean=true`,
`validation_code_origin=CACHE_FREE_EXACT_GIT_ARCHIVE`, and
`worktree_imports_used=false` while stating `authority_effect=NONE`,
`qualification_authority_granted=false`, and
`production_activation_authorized=false`. The receipt tree and producer policy
identities must equal the frozen Epoch; mismatch is `NOT_EVALUATED`. It is
necessary profile evidence, never sufficient qualification evidence.
'''
    new = '''Every 5E evidence manifest is a bounded canonical file validated in a fresh
signed exact-head process. The workflow streams the exact validator Git blob to
root-owned Python using `-I -S -`; direct checkout execution is rejected. It
retains the exact source-pipe command, commit/tree, validator blob digest, and
root-owned Python/Git paths and digests.

The validator is standard-library-only. It reads no worktree or index state and
imports no repository or third-party package. Instead, it performs bounded
`cat-file blob` reads from the exact commit for its own source, the reviewed
contract and all four profile schemas; verifies their exact digests and
canonical bytes; reconstructs the public schema bindings; and enforces the full
fixture/qualification semantic envelope directly.

Receipt v5 binds those identities and records
`EXACT_GIT_BLOB_PIPE`, `PYTHON_ISOLATED_NO_SITE_STDIN`,
`EXACT_COMMIT_BLOBS_ONLY`, `stdlib_only=true`,
`third_party_imports_used=false`, and `worktree_or_index_used=false`, while
stating `authority_effect=NONE`, `qualification_authority_granted=false`, and
`production_activation_authorized=false`. The Epoch policy set must freeze and
match every producer/runtime identity and the signed workflow command; mismatch
is `NOT_EVALUATED`. The receipt is necessary profile evidence, never sufficient
qualification evidence.
'''
    OPERATIONS.write_text(
        replace_once(text, old, new, "operations exact-blob boundary"),
        encoding="utf-8",
    )


def update_evaluation() -> None:
    text = EVALUATION.read_text(encoding="utf-8")
    old = '''Cross-Epoch pooling is prohibited. A missing or mismatched Epoch is
`NOT_EVALUATED`. Every profile-validation receipt is v4, binds the actual Git
commit and tree, the root-owned system Git executable path and SHA-256 digest,
the exact producer policy, and the streaming archive limit. It records that
staged/tracked checkout state was clean and that all Newsroom imports came from
a cache-free exact-commit materialization rather than checkout or ignored
bytecode. The Epoch policy-set digest must freeze those producer identities and
limits before execution. Its `code_tree_sha` must equal the Epoch's frozen
`code_tree_sha`; a missing, dirty, non-materialized, producer-mismatched, or
code-tree-mismatched receipt is `NOT_EVALUATED`. Superseded Epoch Runs remain
retained. The Epoch record binds the plan digest externally at Run creation, so
the machine plan does not contain a self-referential digest.
'''
    new = '''Cross-Epoch pooling is prohibited. A missing or mismatched Epoch is
`NOT_EVALUATED`. Every profile-validation receipt is v5 and binds the exact
commit/tree, validator blob, selected contract/schema blobs, and root-owned
Python and Git paths/digests. The signed workflow retains the command that pipes
the exact validator blob into isolated no-site Python. The validator records
standard-library-only execution and exact-commit-blob access with no index,
worktree, checkout-code or third-party import use.

The Epoch policy-set digest freezes these runtime/source identities and launch
rules before execution. A missing source-pipe command, wrong validator blob,
wrong Python/Git identity, non-isolated or site-enabled process, third-party
import, worktree/index dependency, or code-tree mismatch is `NOT_EVALUATED`.
Superseded Epoch Runs remain retained. The Epoch record binds the plan digest
externally at Run creation, so the machine plan does not contain a
self-referential digest.
'''
    EVALUATION.write_text(
        replace_once(text, old, new, "evaluation exact-blob boundary"),
        encoding="utf-8",
    )


def main() -> int:
    update_decision()
    update_operations()
    update_evaluation()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
