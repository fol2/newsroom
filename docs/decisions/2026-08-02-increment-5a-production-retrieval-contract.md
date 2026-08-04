# Increment 5A — production retrieval contract decision

- **Status:** owner-accepted when this record reaches `main` through reviewed PR #255
- **Owner:** `fol2`
- **Issue:** #250; parent #145; programme #141
- **Implementation base:** `main@3ea1874de5e1bd6c622a3760eabb74adfe75d169`
- **Machine record:** `newsroom/increment5/data/increment5a_retrieval_contract_v1.json`
- **Contract digest:** `sha256:51a3837ad9cdb70fe8aaa4242997b191c7e848bb1d391c6940cccc2bd45ba06c`
- **Evaluation plan digest:** `sha256:c9d169c46a939573ffc6563704adfae973655f6394293ce591ec689f76a30959`
- **Superseded stack:** `archive/increment-5a-stack-20260802`

## Decision

5A approves one exact retrieval contract for implementation and non-production
qualification in #251–#254. It does not activate production.

The required branches are:

1. exact authority lookup;
2. bounded full-text retrieval;
3. vector retrieval through a typed interface; and
4. bounded traversal of admitted graph relations.

Branches return ordered receipts and are fused by deterministic reciprocal-rank
fusion with `k=60`. Raw branch scores are never compared. Rank, similarity,
graph paths, and projection text are advisory. Candidate identity, collision
state, rights, retained bytes, and facts remain authoritative only in SQLite
and governed objects.

Deduplication occurs only at the authoritative dependency root. Hydration
re-reads authoritative bytes and rights. A missing branch, stale generation,
denied authority, failed collision check, or incomplete reconciliation cannot
become a silent empty result.

## Source governance, not recursive self-admission

The former branch attempted to make application code prove its own future merge,
workflow history, comments, import closure, and post-merge authority. Every new
proof mechanism enlarged the trusted code base and created another temporal or
unpinned edge.

5A uses two layers instead:

- repository governance—owner control, substantive review, exact-head required
  checks, resolved threads, and merge to `main`—decides accepted source; and
- deterministic product code identifies and parses exact reviewed contract,
  schema, Plan, and Epoch-policy bytes.

The product layer does not call GitHub, inspect a PR, authenticate comments, pin
its own import graph, mint a capability, or require a second post-merge
materialisation record. Digests identify content; they are not a competing
authorization system. A material contract change requires a new version and a
new reviewed merge.

A fresh isolated process may inspect canonical profile bytes for 5E evidence.
Its receipt has authority effect `NONE`; it is not an admission or authorization
subsystem.

## Closed-world normative inventory

The readiness ladder selects exact Increment 5 `GRAG-*`, `GRPROD-*`, and
`TRI-*` ranges and selects the complete `DEVAL-*` and `DOPS-*` families from
their accepted specifications.

The machine map therefore contains:

- 22 `GRAG-*` requirements;
- 20 `GRPROD-*` requirements;
- 9 `TRI-*` requirements;
- all 43 accepted `DEVAL-*` requirements; and
- all 61 accepted `DOPS-*` requirements.

The total is **155 unique requirements**. Tests parse the accepted
shadow-evaluation and reliability/operations specifications and require their
requirement headings to equal the machine `DEVAL-*` and `DOPS-*` inventories.
A hand-selected subset cannot claim completeness.

Delivery ownership is derived rather than patched row by row:

- 5A / #250 — 9;
- 5B / #251 — 0 complete requirements (partial branch implementation);
- 5C / #252 — 2;
- 5D / #253 — 13;
- prior Increment 4 / #144 — 7;
- outside Increment 5 activation — 1; and
- **5E / #254 — the exact closed-world remainder of 123 requirements.**

This replaces the invalid 114-row hand-selected inventory. The complete map is
in `newsroom/increment5/traceability.py`.

## Vector and embedding boundary

Increment 5 v1 selects no embedding model, provider, credential, destination,
download, or spend. `EMBEDDING` is disabled.

The vector seam is qualification-only:

- 1,024-dimensional float32 vectors;
- cosine similarity;
- deterministic fixed-point fixture vectors;
- a generation-scoped index in an actual Neo4j service during 5E; and
- no model execution, external call, protected content, or production activation.

This can qualify index construction, query execution, rank handling, fusion,
dependency-root deduplication, hydration, degradation, recovery, and rebuild
behaviour. It cannot establish embedding
relevance or approve a production vector lane. A later model selection requires
a fresh owner decision, rights review, model evaluation, component identity,
and new vector generation.

## Package neutrality

`GraphRAG` names the repository architecture and semantic boundary. It **must
not be equated with mandatory use of Microsoft GraphRAG community
summarisation**.

Microsoft GraphRAG, its community-summarisation pipeline, and equivalent
third-party packages are **not required runtime dependencies**, qualification
modes, or authority surfaces for Increment 5. The selected initial target
remains Neo4j Community plus Graphiti through repository-owned typed interfaces.

An implementation may reproduce the reviewed semantics without importing a
community-summarisation package. Conversely, installing or invoking such a
package **cannot satisfy a required retrieval mode**, create identity or
relation authority, replace authoritative hydration, or alter rights, budgets,
security, temporal, or failure rules.

Any future package addition or replacement requires an exact reviewed version,
licence and rights review, compatibility evidence, and applicable 5E
qualification. Package availability, popularity, or naming does not change the
contract or authorize execution.

## Profiles, reviewed bindings, and non-effects

Only `FIXTURE_REPLAY` and `PRODUCTION_SHAPED_QUALIFICATION` are admitted. Both
require zero external calls, zero provider spend, no model load, no protected
content, no write authority, no public effect, and no production activation.

The qualification profile may use authenticated Neo4j and a signed,
rights-cleared, repository-safe dataset manifest. Its evidence is limited to
retriever, index, fusion, dependency-root deduplication, hydration,
degradation, and recovery behaviour.
Fixture replay is hermetic and is never qualification evidence.

Profile schemas use two non-circular layers:

1. the contract identifies exact structural-schema bytes; and
2. public reviewed-binding schemas replace identity patterns with JSON-Schema
   `const` values for the reviewed contract and all component digests.

The public binding-schema digests remain outside the contract they bind,
avoiding a schema-digest/contract-digest cycle.

### Profile-validation authority boundary

Python code in one process is not a security principal against arbitrary code in
that process: closures, globals, function code, and return objects are mutable.
5A therefore exports no authority-bearing certificate or eligibility boolean.
Public builders remain deterministic conveniences only.

For 5E evidence, canonical manifest bytes are supplied with the exact
expected commit and tree through one admitted command:

```bash
set -euo pipefail
REPOSITORY_ROOT="$(pwd -P)"
GIT_DIR="$REPOSITORY_ROOT/.git"
GIT_INDEX_FILE="$GIT_DIR/index"
PROFILE_MANIFEST="${PROFILE_MANIFEST:?canonical profile path required}"
CODE_COMMIT_SHA="$(
  env -i PATH=/usr/bin:/bin LC_ALL=C GIT_CONFIG_GLOBAL=/dev/null \
    GIT_CONFIG_NOSYSTEM=1 GIT_NO_REPLACE_OBJECTS=1 \
    GIT_DIR="$GIT_DIR" GIT_WORK_TREE="$REPOSITORY_ROOT" \
    GIT_INDEX_FILE="$GIT_INDEX_FILE" \
    /usr/bin/git --git-dir="$GIT_DIR" --work-tree="$REPOSITORY_ROOT" \
      --no-replace-objects -c core.fsmonitor=false \
      rev-parse --verify 'HEAD^{commit}'
)"
CODE_TREE_SHA="$(
  env -i PATH=/usr/bin:/bin LC_ALL=C GIT_CONFIG_GLOBAL=/dev/null \
    GIT_CONFIG_NOSYSTEM=1 GIT_NO_REPLACE_OBJECTS=1 \
    GIT_DIR="$GIT_DIR" GIT_WORK_TREE="$REPOSITORY_ROOT" \
    GIT_INDEX_FILE="$GIT_INDEX_FILE" \
    /usr/bin/git --git-dir="$GIT_DIR" --work-tree="$REPOSITORY_ROOT" \
      --no-replace-objects -c core.fsmonitor=false \
      rev-parse --verify 'HEAD^{tree}'
)"
VALIDATOR_PATH='scripts/sdlc/increment5_profile_validator.py'
VALIDATOR_BLOB_SHA="$(
  env -i PATH=/usr/bin:/bin LC_ALL=C GIT_CONFIG_GLOBAL=/dev/null \
    GIT_CONFIG_NOSYSTEM=1 GIT_NO_REPLACE_OBJECTS=1 \
    GIT_DIR="$GIT_DIR" GIT_WORK_TREE="$REPOSITORY_ROOT" \
    GIT_INDEX_FILE="$GIT_INDEX_FILE" \
    /usr/bin/git --git-dir="$GIT_DIR" --work-tree="$REPOSITORY_ROOT" \
      --no-replace-objects -c core.fsmonitor=false \
      rev-parse --verify "$CODE_COMMIT_SHA:$VALIDATOR_PATH"
)"
env -i PATH=/usr/bin:/bin LC_ALL=C GIT_CONFIG_GLOBAL=/dev/null \
  GIT_CONFIG_NOSYSTEM=1 GIT_NO_REPLACE_OBJECTS=1 \
  GIT_DIR="$GIT_DIR" GIT_WORK_TREE="$REPOSITORY_ROOT" \
  GIT_INDEX_FILE="$GIT_INDEX_FILE" \
  /usr/bin/git --git-dir="$GIT_DIR" --work-tree="$REPOSITORY_ROOT" \
    --no-replace-objects -c core.fsmonitor=false \
    cat-file blob "$VALIDATOR_BLOB_SHA" | \
  env -i PATH=/usr/bin:/bin LC_ALL=C PYTHONUTF8=1 \
    /usr/bin/python3 -I -S - \
      --repository-root "$REPOSITORY_ROOT" \
      --git-dir "$GIT_DIR" \
      --index-file "$GIT_INDEX_FILE" \
      --manifest-fd 3 \
      --expected-validator-blob-sha "$VALIDATOR_BLOB_SHA" \
      --expected-code-commit-sha "$CODE_COMMIT_SHA" \
      --expected-code-tree-sha "$CODE_TREE_SHA" \
      3<"$PROFILE_MANIFEST"
```

The inner receipt deliberately sets `executed_source_identity_attested=false` and `validation_code_identity_claim_effect=NONE`. The signed outer workflow must bind the exact validator blob SHA, complete launcher command, system-Python/runtime-image identity, canonical manifest bytes, inner-receipt digest, Epoch, and code tree. A direct worktree-path invocation or an unbound inner receipt is `NOT_EVALUATED`.

The content-addressed checkout comparison is a bounded snapshot completed before receipt write, not a lock over mutable worktree, index, or HEAD state. The receipt therefore records `checkout_snapshot_verified_before_receipt_write=true` and explicitly records `completion_time_checkout_state_attested=false`; it never claims `tracked_checkout_clean`. A concurrent change after the final snapshot cannot falsify the receipt because the signed outer workflow relies on immutable commit, tree, validator-blob, manifest, and receipt identities rather than a mutable checkout-at-handoff assertion.


The executable requires both isolated mode and disabled `site` initialization
before any import other than built-in `sys`. It then verifies that the actual
interpreter is the root-owned, non-writable `/usr/bin/python3` target and uses
**only the Python standard library**. It imports neither `jsonschema` nor any
repository Python package. Caller virtualenv/site-packages, `.pth` startup code,
`PYTHONPATH`, user site packages, ignored bytecode, and mutable repository module
imports are therefore outside the admitted evidence path.

The trusted repository view captures one absolute Git directory, one exact index
file, and `_REPOSITORY_ROOT` as the explicit work tree. Every command carries
`--git-dir`, `--work-tree`, `--no-replace-objects`, and
`core.fsmonitor=false`; the environment independently fixes `GIT_DIR`,
`GIT_INDEX_FILE`, `GIT_WORK_TREE`, and `GIT_NO_REPLACE_OBJECTS=1`. Lowercase
assume-unchanged tags and skip-worktree tags are rejected before cleanliness can
be claimed.

Validation reads only five bounded, digest-pinned blobs from the supplied
commit: the exact contract and four structural/public profile schemas. The
stdlib semantic validator checks canonical JSON, exact fields, identities,
budgets, effects, rights, eligibility, and profile-specific invariants. It does
not execute code from those blobs.

Receipt v7 binds the manifest, commit and tree while recording
`python_runtime_executable=/usr/bin/python3`,
`python_runtime_origin=ROOT_OWNED_SYSTEM_PYTHON_NO_SITE`,
`site_initialization_used=false`, `external_python_packages_used=false`,
`validation_code_origin=OUTER_SIGNED_GIT_BLOB_LAUNCHER_REQUIRED`,
`validation_data_origin=EXACT_REVIEWED_GIT_BLOBS`, and
`worktree_imports_used=false`. Interpreter identity and the same repository/index snapshot are rerun
immediately before receipt write. Drift detected during that final prewrite
snapshot emits no receipt; mutable checkout, index, or HEAD changes during or
after output handoff are explicitly not attested. The receipt retains authority effect
`NONE` and grants no qualification, component, source, model, provider, spend,
write, production, or public-effect authority.

These profiles are not production deployment profiles. Production rejection of
fake, disabled, or omitted GraphRAG and production build/readiness validation
remain 5E/#254 work. `GRPROD-002` and `GRPROD-023` are therefore bound by
5A but delivered only when #254 implements and verifies the production, canary,
and complete-live-shadow rejection paths.

## Frozen Epoch boundary

`DEVAL-011` is enforced by the machine Plan’s exact `epoch_protocol`, not by
reviewer judgement after results exist.

Before any Run, 5E creates a canonical Epoch record whose SHA-256 identity binds
the reviewed contract and external evaluation-plan digests; every component;
the exact source inventory; source/provider, adapter and parser versions; the
query set; thresholds; policies; dataset manifest; label/adjudication policy;
code tree; and generation.

Any difference in a frozen identity is material. A material **component,
source, query, threshold, or policy** change starts a new Epoch. A Run binds the
exact Epoch digest. All frozen identities must remain equal inside one Epoch.
Cross-Epoch pooling is prohibited. A missing or mismatched Epoch is
`NOT_EVALUATED`, and superseded Epoch Runs remain retained.

The Plan digest remains outside the Plan it identifies. The Epoch record binds
that externally reviewed digest at Run creation, avoiding a Plan self-reference.

## Frozen evaluation extension

The canonical machine Plan is
`newsroom/increment5/data/increment5_retrieval_evaluation_plan_v1.json`, digest
`sha256:c9d169c46a939573ffc6563704adfae973655f6394293ce591ec689f76a30959`.
It binds the contract summary exactly and freezes:

- `HYBRID` as the sole qualification-bearing system;
- four separately reported, non-rescuing comparative ablations;
- the exact Epoch rollover protocol;
- independent blocking criteria for all three mandatory query families;
- all six `DEVAL-046` error classes with definitions, cases, counts,
  opportunity denominators, and separate ppm rates;
- 100 unique cases, family floors of 30/30/40, per-case-type, per-slice,
  family/slice, and per-error-class exposure floors;
- no cross-family reuse, calibration counting, or cross-Epoch pooling; and
- zero temporal-correctness and rebuild-reproducibility mismatches.

False merge and false/missed development bind to existing family blockers. The
other four error classes remain mandatory separate reports; no automatic
threshold may be invented after outcomes are visible. Candidate-related
measurement is read-only and creates no Candidate.

The exact dataset manifest and label/adjudication policy are frozen in the
Epoch before execution. 5E owns the complete event-level universe, prospective
and contemporaneous labels, negative/failure sampling, authorised human review,
practical blinding, independent review or adjudication, and retained
disagreement required by `DEVAL-020`–`DEVAL-033`.

5A also freezes the `DEVAL-072` public-artifact safety rule but does not claim
its executable delivery. 5E/#254 must implement and retain dataset, manifest,
report, receipt, regression-case, log, index, and context validation/redaction
and release controls before that requirement can close.

## Dependency boundaries

- **5B / #251:** four independent typed retrievers and exact branch receipts;
  no final fusion, dependency-root deduplication, or exact-before-approximate
  orchestration. It is a partial implementation dependency and closes no
  selected whole requirement by itself.
- **5C / #252:** six bounded named read-only tools plus tool-local caller,
  purpose, and scope authorization; no raw Cypher, arbitrary index, writes,
  composed-hybrid response contract, or cross-branch fused receipt.
- **5D / #253:** exact/source-native, formal-process, and explicit-lineage
  retrieval precedes approximate similarity; deterministic fusion and
  authoritative dependency-root deduplication then produce one read-only
  request. The composer owns the hybrid response explanation—authority and
  source basis, upstream freshness, provenance completeness, and degraded
  state—and one inspectable receipt containing branch and fused candidates,
  scores/ranks, deduplication signals, exclusions, and known omissions. 5D also
  owns complete projectable and hydratable
  `Source → Revision → Signal → Lead → Hypothesis → Candidate` lineage,
  authoritative hydration, freshness, the request's exact collision receipt,
  and honest request-level no-match or incomplete outcomes. It stops before
  upstream collection, downstream decisions, Hypothesis or Candidate effects,
  Candidate admission, and product-profile outage behaviour.
- **5E / #254:** the closed-world remainder: Epoch-bound profile validation and
  hybrid qualification; complete `DEVAL-*` universe, labels, review,
  adjudication, metrics, role-change and decision evidence; every operational
  `DOPS-*` row except `DOPS-076`; production-readiness validation; monitoring;
  queues; durability; least-privilege credentials and egress; the complete
  governed-projection → hybrid-retrieval → triage → Candidate-admission
  vertical slice; downstream exact-fallback/Watch/Hold decisions; Candidate
  non-creation and collision-gated admission; source-collection and Lead
  isolation during graph loss; system outage policy; full reconciliation
  recovery; scoped containment;
  security; purge; rollback; rebuild; and actual-Neo4j evidence.

Four independently working branches are not a hybrid system and cannot satisfy
`TRI-021`; exact-before-approximate orchestration, fusion, and dependency-aware
deduplication create that system in 5D. A request may truthfully return no-match,
incomplete state, exact collision status, or graph unavailability, but it cannot
itself create or suppress a Hypothesis or Candidate, gate Candidate admission,
place a downstream decision into Watch or Operational Hold, keep upstream source
collection running, or define whether the product has become graph-free. Those
cross-request effects (`GRAG-044`, `GRAG-045`, `GRPROD-024`, `TRI-024`, and
`TRI-026`) belong to 5E together with `GRPROD-021`. Likewise, request-level
`COMPLETE`/`INCOMPLETE`/`UNAVAILABLE` outcomes do not deliver `DOPS-050` full
operational reconciliation or `DOPS-073` system-level containment. Those require
5E controls for orphaned ownership, ambiguous calls, duplicate delivery, stale
work, pending Handoffs, narrow-scope pause, and broader containment when shared
authority or integrity is uncertain.

`DOPS-067` also remains 5E work: a tool-local authorization success does not
prove least-privilege source/provider credentials, source-access scopes, or
approved network destinations.

## Completion

PR #255 is the review unit. When its exact clean head passes all required checks,
substantive review has no unresolved P1/P2 finding, all actionable threads are
resolved, and it is merged to `main`, this decision becomes effective and #250
may close. No follow-up admission PR is required.

That merge authorizes starting 5B. It authorizes none of the stated runtime
non-effects.
