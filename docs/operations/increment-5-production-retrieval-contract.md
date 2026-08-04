# Increment 5 production-retrieval operating contract

This runbook covers implementation and non-production qualification authorized
by 5A. Production activation is outside Increment 5.

## Profiles and validation

`FIXTURE_REPLAY` is hermetic, zero-call, and never qualification evidence.
`PRODUCTION_SHAPED_QUALIFICATION` may use actual Neo4j and a signed,
rights-cleared, repository-safe dataset, but still has zero provider spend, no
model load, no protected content, no write authority, no public effect, and no
production activation.

Every 5E profile is launched only by the signed outer workflow below. Before
any validator byte executes, fixed `/usr/bin/git` resolves the exact validator
blob from the frozen commit and streams those bytes to root-owned system
Python in isolated no-site stdin mode. The canonical manifest enters on a
separate inherited regular-file descriptor.

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

The inner executable is standard-library-only and imports no environment package
or repository Python module. It binds the explicit Git directory, exact index,
and actual work tree; disables replacement objects and fsmonitor; rejects
assume-unchanged and skip-worktree flags; verifies the expected validator blob;
and reads only bounded digest-pinned contract/schema blobs from the exact
commit.

Receipt v6 records `executed_source_identity_attested=false`,
`validation_code_identity_claim_effect=NONE`,
`outer_signed_workflow_binding_required=true`,
`validation_code_delivery=EXACT_COMMIT_GIT_BLOB_STDIN`,
`python_runtime_executable=/usr/bin/python3`,
`python_runtime_origin=ROOT_OWNED_SYSTEM_PYTHON_NO_SITE`,
`site_initialization_used=false`, `external_python_packages_used=false`,
`validation_code_origin=OUTER_SIGNED_GIT_BLOB_LAUNCHER_REQUIRED`,
`validation_data_origin=EXACT_REVIEWED_GIT_BLOBS`, and
`worktree_imports_used=false`. Runtime, commit, tree, validator blob, index
flags, and tracked cleanliness are checked again immediately before output.
The receipt retains authority effect `NONE`; it is necessary evidence only and
cannot authorize qualification or activation without the separately signed
outer evidence envelope.

## Epoch admission

Every qualification Run binds a canonical Epoch record before execution. The
Epoch digest covers the reviewed contract and evaluation-plan digests; exact
components; source inventory; source/provider, adapter, and parser versions;
query, threshold, and policy sets; dataset manifest; label/adjudication policy;
code tree; and generation.

Any frozen identity difference is material. A component, source, query,
threshold, or policy change starts a new Epoch. A Run with missing or mismatched
Epoch identity is `NOT_EVALUATED`. Cross-Epoch pooling is prohibited, and
superseded Epoch Runs remain retained.

## Closed-world requirement ownership

Increment 5 uses 155 accepted requirements. The machine inventory includes the
exact selected `GRAG-*`, `GRPROD-*`, and `TRI-*` ranges plus every requirement
heading in the accepted `DEVAL-*` and `DOPS-*` specifications.

The exact delivery split is `9 / 0 / 2 / 13 / 123 / 7 / 1` for 5A, 5B, 5C,
5D, 5E, prior Increment 4, and outside activation respectively. 5E is derived as
the closed-world remainder after the six smaller explicit groups are removed.
It is not a manually maintained list.

Tests parse the two accepted specifications and require exact equality with the
43-row `DEVAL-*` and 61-row `DOPS-*` machine inventories.

## Implementation ownership

- **5B / #251:** four independent retriever branches and exact receipts.
  This is partial implementation: it closes no selected whole requirement
  until 5D composes the branches.
- **5C / #252:** six typed bounded read-only tools, tool-local authorization,
  and tool-local receipts; no composed hybrid response or fused cross-branch
  receipt.
- **5D / #253:** exact/source-native, formal-process, and explicit-lineage
  retrieval before approximate similarity; deterministic fusion, authoritative
  dependency-root deduplication, complete six-stage discovery lineage,
  hydration, freshness, an exact request collision receipt, and honest
  request-level no-match or incomplete outcomes. The composer also retains the
  response's authority/source basis, upstream freshness, provenance and degraded
  state, plus fused candidates, scores/ranks, deduplication signals, exclusions,
  and known omissions in one inspectable receipt. It creates no upstream or
  downstream operational or editorial effect.
- **5E / #254:** the complete closed-world evaluation and operating system:
  universe, labels, review and adjudication; Operational Profiles; scheduling;
  access and parser security; health and coverage; queues and capacity;
  monitoring and incidents; security; rights purge; full reconciliation
  recovery; containment; the complete governed-projection/hybrid-retrieval/
  triage/Candidate-admission vertical slice; downstream decision fallback,
  Candidate non-creation and collision-gated admission, collection/Lead
  isolation and system outage semantics; production/canary/live-shadow
  GraphRAG enforcement; executable public-artifact validation, redaction, and
  release controls; rollback and rebuild; and actual-service qualification.

## Decision-bearing system

`HYBRID` is the sole qualification target. Exact-only, full-text-only,
vector-only, and admitted-graph-only are mandatory comparative ablations whose
quality cannot rescue `HYBRID`. A safety or rights violation in any executed
system blocks the affected scope.

## Evaluation universe, labels and review

Before execution, the Epoch binds the exact dataset manifest and
label/adjudication policy. 5E must prove:

- event-level deduplication rather than URL counting;
- no provider, source, index, legacy pipeline, feed, search system, or model as
  complete ground truth;
- prospective methods fixed before review, with retrospective additions
  separately labelled;
- contemporaneous primary labels and later outcomes retained separately;
- explicit unreviewable status where rights or evidence are insufficient;
- negative and failure sampling, not positive-only selection;
- authorised human-reviewed release labels;
- practical blinding of path, confidence, and system outcome;
- independent review or adjudication for blockers, zero-tolerance failures,
  Urgent material errors, and a planned ordinary sample; and
- retained reviewer disagreement that cannot be resolved by model confidence or
  metric preference.

Source promotion, removal, or role change must cite event-level coverage,
resilience, rights, cost, and operational evidence. Quiet-period absence alone
cannot remove a rare-event Anchor. A Comparator cannot become an Anchor merely
because it returns more results. Search value, noise, and cost remain attributed
to exact Purpose and provider version.

## Scheduling, access and parser controls

5E owns every operational `DOPS-*` row except `DOPS-076`. In particular:

- duplicate ticks, deliveries, or restarts create one logical due operation;
- due-work determination and no-work completion require no model;
- jitter, host coordination, missed work, bounded ownership, and catch-up remain
  explicit;
- source access enforces scheme, host, redirect, TLS, credentials, timeout,
  body, content type, and egress;
- conditional requests and status codes retain source-specific semantics;
- parsers block external entities, unsafe deserialisation, decompression bombs,
  and uncontrolled resource use;
- shape drift creates degraded or quarantined state rather than publisher
  activity; and
- delivered channels retain authentication or provenance, replay control,
  bounded payload, and durable receipt.

## Hard limits

Limits are 5,000 ms end-to-end, 8 results per branch, 12 retained candidates,
262,144 response bytes, zero external calls, zero provider cost, graph depth 2,
fan-out 32, and date window 31 days. Limits are never silently widened.

## Outcomes

Outcomes are:

- `COMPLETE` — every mandatory branch, authority, hydration, freshness,
  collision, and reconciliation check for the request completed;
- `DEGRADED` — a named optional contribution failed but bounded meaning remains;
- `INCOMPLETE` — missing authority, mandatory branch, collision, or
  reconciliation prevents complete meaning;
- `POLICY_BLOCKED` — rights, scope, or security forbids the material;
- `STALE` — selected generation or authority is outside the admitted boundary;
  and
- `UNAVAILABLE` — no safe bounded response can be produced.

An empty result is no-match only with `COMPLETE`. This request outcome does
not itself create a Hypothesis or Candidate, authorize Candidate admission,
select Watch or Operational Hold, continue source collection, or change the
product profile; those effects require 5E integration and current authority.

## Security and DOPS-026 / DOPS-067

Only six named tools expose retrieval. Inputs and outputs are typed and bounded.
Raw/generated Cypher, caller Lucene syntax, arbitrary indexes or predicates,
writes, unrestricted source text, model/provider credentials, and projection
text as factual authority are prohibited.

5C proves tool-local caller, purpose, and scope authorization. 5E separately
proves that source/model content cannot alter operational policy, tools, egress,
budgets, credentials, destinations, scope, authority, or admission state.

5E also proves least-privilege credential identity, exact source-access scope,
secret storage/redaction, approved destinations, and rejection of broader,
substituted, or unadmitted credentials, access, or destinations. A successful
tool call is neither `DOPS-026` nor `DOPS-067` evidence.

## Queues, capacity and durable delivery

5E must prove reserved or isolated Urgent capacity; deadline, starvation, and
fairness state for Time-sensitive, Planned, and Routine work; bounded
backpressure that never silently skips required Anchors, Leads, or deadlines;
and current-authority revalidation before commit.

Average, peak, no-change-heavy, and failure-heavy capacity evidence is
mandatory. A committed transition and required downstream work must be atomic
or deterministically reconcilable. Authoritative-state or audit failure blocks
affected effects.

## Reconciliation and recovery

5D can reconcile one retrieval request through fusion, deduplication, hydration,
freshness, collision, and explicit outcomes. That is not the complete
operational reconciliation required by `DOPS-050`.

5E detects and retains evidence for orphaned ownership, missing outcomes,
ambiguous external effects, duplicate delivery, stale work, pending Handoffs,
and projection mismatch. Ambiguous effects are reconciled or retried
idempotently rather than repeated blindly.

Replay retains exact versions and creates later outputs rather than rewriting
history. Catch-up is bounded and prioritises current Urgent and Planned state.
After restore, automatic operation remains blocked until baselines, leases,
queues, Handoffs, and coverage posture are reconciled.

## Monitoring, incidents and manual action

5E monitoring includes schedule, complete-success age, outcome, parser, retry,
queue, budget, coverage, storage, and reconciliation metrics. Structured
records trace due trigger through Check, transition, Lead, Work Item, Candidate,
and Handoff without prohibited data.

Alert priority reflects consequence, coverage, integrity, and urgency rather
than raw error count. Material operational or integrity failures create retained
incidents with scope, timeline, containment, recovery, root cause, and follow-up.
Confirmed errors and material near misses create rights-permitted regression
Cases where applicable.

Retry, requeue, quarantine release, contingency, and override actions are
authenticated and audited.

## Scoped containment and DOPS-073

A per-request `DEGRADED`, `INCOMPLETE`, or `UNAVAILABLE` result is not a
system-level containment mechanism. 5E proves the ability to pause the
narrowest safe affected scope and broaden containment when shared authority,
rights, security, or integrity is uncertain.

Containment actions are role-bounded, authenticated, audited, reversible where
safe, and retained with their trigger, scope, dependencies, exit criteria, and
recovery evidence.

## Rights, purge and recovery

Rights are checked at read time. Personal data, secrets, rights-restricted text,
and public governed source text cannot enter the v1 vector lane.

Withdrawal stops derivative creation. Purge removes passages, full-text entries,
fixed-point vectors, graph derivatives, and cached contexts; records derivative
identities and a purge receipt; rebuilds an isolated generation; and proves
non-resurrection before selection. Any residual blocks qualification.

Rollback selects a prior generation only when exact component identities match,
rights remain current, freshness and completeness pass, and no purged material
returns. Otherwise return `UNAVAILABLE`, `STALE`, or `POLICY_BLOCKED` until a
safe isolated generation qualifies.

## DEVAL-046 evidence

Retain separate counts, opportunity denominators, and ppm rates for false merge,
fragmentation, snowball absorption, false or missed development, duplicate
Candidate creation, and unnecessary Candidate creation. Every class requires at
least ten relevant preregistered cases. Cross-class pooling is prohibited; a
missing class is `NOT_EVALUATED`.

Candidate-related checks use read-only expected dispositions and create no
Candidate.

## Version, challenger, canary and operational admission

Before 5E qualifies a scope, Operational Admission enumerates exact source,
adapter, parser, Profile, worker, retrieval, and provider versions and proves
that every new version starts without inherited authority.

Material operational changes support a bounded canary or equivalent
qualification where technically appropriate. Canary evidence cannot activate
production and cannot weaken rights, safety, authority, or zero-tolerance gates.

A second graph engine may be tested only after a retained measured blocker
against Neo4j Community plus Graphiti or an owner-approved bounded comparison
purpose. Without that record, evidence must prove one implementation only.

## Evidence and stopping conditions

Retain Plan/Epoch/Run/profile/generation identity, branch receipts,
fusion/dedup/hydration outcomes, rights and collision state, event universe,
prospective method, samples, labels, reviewer assignments, adjudications,
disagreement, exposure counts, family metrics, six error-class reports,
comparative results, temporal and rebuild counts, exact components,
purge/rebuild linkage, credential/source/destination evidence, queue and
capacity evidence, health metrics, incidents, manual actions, reconciliation
and containment evidence, and final owner outcome.

Stop and preserve evidence on any successful write, generated query execution,
external call or spend, model load, protected-content vector, authority bypass,
false no-match, purge residual, identity drift, wrong Epoch, unadmitted version,
unapproved challenger, credential/access/destination violation, unresolved
reconciliation, failed containment, or silent branch loss. CI success alone
never activates production.
