# Hermetic CONT writer route

- **Role:** Operational implementation record
- **Status:** EVALUATION; productive calibration pending
- **Owner:** Hermes Control Plane
- **Canonical language:** English
- **Issue:** #730

## Boundary

Each Grok CONT leaf now runs in a fresh non-repository workspace with an
isolated `HOME`, isolated XDG roots and a fixed environment allow-list. The
only copied provider state is the private Grok login file. The route rejects a
missing, non-regular, over-sized or over-permissive login file before provider
dispatch.

The pinned Grok command is `1.0.8`, model `grok-4.6`, reasoning `low`, one
turn. It overrides the coding-agent system instruction, passes the Newsroom
prompt verbatim and disables web search, planning, subagents, tools and MCP.
A machine-readable `grok inspect` preflight must prove no repository root,
project instructions, skills, plugins, MCP servers, hooks, LSP servers or
configuration layers before the provider command can run.

The installed Cursor CLI does not expose controls that prove zero tools and
zero MCP servers. Its fallback therefore terminates before provider dispatch
with `HERMETIC_CAPABILITY_UNPROVABLE`; it never falls back to ambient Cursor
state.

## Retained evidence

Before allocation and dispatch, the shared model-usage store retains the
canonical non-secret context manifest. The append-only
`newsroom.model-usage.v2` migration preserves the v1 receipt history while
adding manifest and context-observation provenance. The manifest binds:

- provider, route, model, reasoning, command version and semantic flags;
- the exact Git revision and proof that its tracked worktree was clean;
- empty working-directory inventory and digest;
- permitted login/configuration digests without credential bytes;
- disabled capabilities and exact zero skill/tool/MCP/prior-message counts;
- system, prompt and schema byte counts and digests; and
- the exact Evidence Package digest.

The allocation links the context-manifest digest. Terminal completion retains
a second observation containing provider-reported context tokens when they
exist. Full prompts, source expressions and secrets remain outside the usage
receipt.

## Productive calibration

First register a bounded bootstrap policy for the selected candidates. This
policy is EVALUATION-only in effect: it is bound to at most five candidate
identities, the clean Git revision, command semantics, manifest contract and
the 15,000-context-token ceiling. It cannot admit any other candidate:

```bash
.venv/bin/python scripts/hermes_control_plane.py writer-calibration \
  --unpublished data/newsroom/unpublished_store.sqlite3 \
  --calibration-candidates CANDIDATE_1,CANDIDATE_2,CANDIDATE_3 \
  --calibration-version issue-730-v1 \
  --stage-calibration-policy
```

After the governed cycles have produced shared receipts, the operator
assessment reads those receipts only; it does not rerun the historical ambient
baseline:

```bash
.venv/bin/python scripts/hermes_control_plane.py writer-calibration \
  --unpublished data/newsroom/unpublished_store.sqlite3 \
  --usage-start START \
  --usage-end END \
  --calibration-candidates CANDIDATE_1,CANDIDATE_2,CANDIDATE_3 \
  --calibration-version issue-730-v1
```

Add `--register-policy` only after the packet passes. The command then mints
and registers the exact primary invocation-efficiency policy. A failed packet
cannot mint or register a policy. Both the bootstrap and final policy versions
include the current Git revision; a dirty or unversioned worktree fails before
registration, allocation or assessment. On a later clean revision, its matching
candidate-scoped bootstrap takes precedence over an old-revision final policy;
after another successful calibration, the latest retained final policy for that
exact revision supersedes its predecessor without editing policy history.

The assessment requires three accepted unpublished payloads from at most five
candidates, three distinct prompt sizes, complete context telemetry, p50
context no greater than 10,000, maximum context no greater than 15,000, at
least 70% reduction from 37,479, one primary call per candidate, zero ambient
capabilities and zero public effects. It also reports accepted-payload token
totals and median, no-result tokens, primary acceptance, fallback recovery and
the context-to-Newsroom-input ratio. Missing output or total usage on any
dispatched leaf fails the packet; unknown usage is never reported as zero.
Public-effect counts are derived from the retained unpublished payload rows and
their schema-enforced `publication_bundle`, `auto_publish` and `status` fields.

## Current exact-head observation

The no-dispatch dry selection against the retained proving store on 2026-08-24
formed 287 candidates, all `HOLD`, and zero `WRITE_READY` candidates. It made
zero provider calls and zero public effects. Consequently no productive live
packet or invocation-efficiency policy has been minted from that retained set.
Continuous CONT writing remains held until three qualified retained candidates
can satisfy the productive and context gates.

## Non-effects

This implementation does not change provider, model, reasoning, evidence,
language, originality, Graphiti, publication or authority contracts. It does
not activate continuous writing, register a failed calibration, publish a
payload or grant Cursor fallback authority.
