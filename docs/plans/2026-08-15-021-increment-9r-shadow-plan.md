# Increment 9R owner-approved shadow plan and autonomy envelope

- **Status:** Owner approved; conditional runtime authority remains gated
- **Issue:** [Increment 9R — immutable shadow plan, exact version manifest and owner decisions](https://github.com/fol2/newsroom/issues/488)
- **Wayfinder map:** [Increment 9 owner decisions and Hermes autonomy](https://github.com/fol2/newsroom/issues/502)
- **Owner decision:** [Bind Increment 9 owner decisions and the Hermes autonomy envelope](https://github.com/fol2/newsroom/issues/503)
- **Canonical PR:** [Increment 9R: prepare immutable shadow plan](https://github.com/fol2/newsroom/pull/499)
- **Machine record:** `newsroom/increment9/shadow_plan_v1.json`
- **Machine-record digest:** `sha256:92510c8b3989bb25cfce187b3477a71d8909a691ad8f3b88ae4917e456e9216d`
- **Agent-profile digest:** `sha256:c6835632cb9088167ff049325277802d1b6347bc9df44b1e5b41d1d029c56944`

## Decision

The Human Accountable Owner approved every required binding in `OD-001` through
`OD-014` on 15 August 2026. The exact selections and evidence references live in
the canonical machine record. This document explains their operational meaning.

The approval grants a **Conditional Activation Authority**, not an immediate
side effect. Loading, testing or merging these planning bytes performs no live
source request, provider invocation, credential use, deployment, publication,
canary or production mutation. The authority becomes effective phase by phase
only after the exact dependency, implementation, identity, rights, evidence,
budget, ledger and emergency-stop prerequisites pass.

Once those prerequisites pass, Hermes may proceed without another human reply.
It may deliver the 9A–9G atoms, create and execute the Increment 10 canary and
promote a successful canary to production. Every action remains subject to the
deterministic vetoes and append-only control ledger.

## Accepted planning base

The branch was rebased once, after the independent capacity correction closed,
onto:

- main commit `3d4ace16a75e92b9f80c526f18aa811be6c2b053`;
- tree `4dd2b50aafd074314fbbefe3519f0707b9c5507f`;
- authority schema v32;
- schema fingerprint
  `sha256:3439b82ec6d212116e54765d50cace4d7f147b6ecc3e6ff84146b523c6fd5676`;
- migration-history digest
  `sha256:5a48fd76cd11f266e19a4b48174d0c009f320a8d00d3eeb281a558fc2d561910`;
- Increment 8 exact-main signed run `31871581163`; and
- eighteen-shard capacity run `31900458431` from issue 500 and PR 501.

The 75/90-second testcase and 300/330-second shard and critical-path
warning/hard limits remain unchanged.

## Owner decisions

### OD-001 — Source portfolio, roles, locality and rights

The initial portfolio serves Hong Kong people and families in the UK. It covers
immigration and BN(O), education and families, official warnings, selected Hong
Kong policy and services, and two media comparators.

| ID | Role | Exact endpoint | Detection window |
|---|---|---|---:|
| `UK-01` | Home Office and UKVI authority anchor | `https://www.gov.uk/search/all.atom?organisations%5B%5D=home-office&organisations%5B%5D=uk-visas-and-immigration&order=updated-newest` | 2 hours |
| `UK-02` | BN(O) authority anchor | `https://www.gov.uk/api/content/british-national-overseas-bno-visa` | 2 hours |
| `UK-03` | Immigration Rules authority anchor | `https://www.gov.uk/api/content/guidance/immigration-rules` | 2 hours |
| `UK-05` | DfE and Ofqual education anchor | `https://www.gov.uk/search/all.atom?organisations%5B%5D=department-for-education&organisations%5B%5D=ofqual&order=updated-newest` | 4 hours |
| `UK-10` | Met Office warning anchor | `https://weather.metoffice.gov.uk/public/data/PWSCache/WarningsRSS/Region/UK` | 15 minutes |
| `HK-01` | news.gov.hk official editorial radar | `https://www.news.gov.hk/tc/common/html/topstories.rss.xml` | 2 hours |
| `HK-02` | HKO warning anchor | `https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=warnsum&lang=tc` | 15 minutes |
| `HK-04` | EDB education anchor | `https://www.edb.gov.hk/tc/whats_new_rss.xml` | 4 hours |
| `RAD-01` | RTHK lead-only comparator | `https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml` | 1 hour |
| `RAD-02` | BBC UK lead-only comparator | `https://feeds.bbci.co.uk/news/uk/rss.xml` | 1 hour |

ETag, Last-Modified and canonical body digests drive change detection. An
unchanged check targets zero model calls. Non-urgent changes enter a non-empty
two-hour batch, at most twelve times per day. Structured warning transitions are
deterministic by default.

Each source has a planned rights-record identity. Three independent AI rights
reviews must record the exact terms, access method, data class, destinations and
retention before first I/O. `AUTONOMOUS_RIGHTS_RISK_ACCEPTANCE` is an auditable
risk decision, not a claim of permission. New sources enter a non-decision-
bearing acquisition lane until a new Source Definition Version and Effective
Manifest exist.

### OD-002 — SQLite authority snapshot and export

Schema-v32 governed authority is canonical. The legacy `news_pool.sqlite3` is a
frozen, read-only comparator. The first Epoch freezes one verified SQLite backup
plus a canonical JSONL inventory at a contiguous ledger watermark. After that
snapshot, qualification performs no production read or write. Restore uses a
verified authority backup, reconciles before resume and rebuilds every
derivative projection.

### OD-003 — Neo4j shadow deployment

The isolated target is Neo4j `5.26.2`:

- OCI index digest
  `sha256:099b9f74968c123209972835417985ed2a1cc19c0422c0753a313e26a736c365`;
- Linux ARM64 v8 manifest
  `sha256:a731d66b956a4155333eb09badfb3b17ad51d1aedaaf2c1530e24fd24e5559a9`;
- Python driver `neo4j==6.2.0`, wheel hash
  `b87abdd13a5cc2e3bd51026926c2f20ac38fa3febe98c340520dce19e97388d0`.

It uses a separate database, namespace, credential, volume and network. It is a
rebuildable admitted projection, never canonical authority. The observed host is
`macm4`, model `Mac16,10`, Apple M4, ten physical/logical cores, 16 GiB memory.

### OD-004 — Graphiti runtime

The first implementation is Graphiti-native with `graphiti-core==0.29.3`, wheel
hash `0210510e8043b5b4fa57aa038934e849b2e61d31d298200b0074faf7ca793ed5`.
Graphiti classes remain internal behind newsroom-owned stable types. All output
lands in an isolated Proposal Workspace. Only the Hermes deterministic boundary
may admit a proposal and project its admitted generation.

### OD-005 — Models, prompts and Hermes

| Role | Route | Selector |
|---|---|---|
| System under test | Codex CLI | `gpt-5.6-terra` |
| Primary reviewer A | Claude Agent SDK | `claude-sonnet-5` |
| Primary reviewer B | Grok Build CLI | `grok-4.6` |
| Adjudicator | Gemini API | `gemini-3.7-flash` |

Claude CLI remains excluded. Newsroom owns the provider-neutral agent profiles,
prompt bytes and strict JSON schemas in
`newsroom/increment9/agent_profiles_v1.json`. Hermes adapts those profiles to the
four routes. Invalid output, a missing primary or unresolved backend identity is
`NOT_EVALUATED`; no silent fallback or prose repair is permitted.

Tools and models follow latest. Every dispatch records the observed Effective
Manifest. An Epoch may contain several manifests, but only the final Effective
Manifest Cohort may qualify, and it must independently meet the complete
exposure contract.

### OD-006 — Embedding and indexes

OpenAI `text-embedding-3-large` through the OpenAI API is the initial embedding
route, with 1,024 dimensions and cosine similarity. It is the sole exception to
the CLI/Agent-SDK model routes until a replacement qualifies.

Passages split paragraph, then sentence, then safe UTF-8. The target is 3,072
bytes, maximum 4,096 bytes, with 384-byte overlap. A passage never crosses a
revision or representation. Normalisation uses NFKC, LF, collapsed whitespace,
Latin case-folding and Han bigrams of length two, without script conversion or
transliteration. Language classes are `EN_GB`, `ZH_HANT_HK` and `MIXED`.

Retrieval combines exact, full-text, vector and admitted-graph modes with RRF.
Every individual mode and the hybrid route has a pre-registered ablation.

### OD-007 — Integrated application and Hermes service

Hermes on `macm4` is the local orchestration and admission hub. The observed
installation is Hermes Agent v0.18.2 with upstream commit `17c7b0be`, carried
local commit `8e734810` and repository-owned adapter contracts.

The Hermes Control Plane contains an AI controller and an inseparable
deterministic policy-and-effect boundary. The AI controller makes the final
decision; the deterministic boundary has an unavoidable veto. Only that daemon
holds SQLite, Neo4j and target-adapter credentials. Model subprocesses never do.

Hermes runs as a `launchd` user service under `jamesto`, with one active instance,
health checks, restart, staged update, replay verification, atomic promotion and
rollback. Agents may inspect the complete macM4 host, filesystem, repository and
network. All operations remain ledgered. Credentials come from macOS Keychain or
an equivalent local broker and are injected minimally and transiently.

### OD-008 — Evaluation Epoch and prospective universe

An Epoch lasts at most 28 days. It retains three denominators:

1. every scheduled check;
2. every observed new or changed revision, including blocked and failed work;
3. every semantically eligible case, with deterministic digest sampling only
   when the budget cannot include all eligible cases.

The final manifest requires at least 120 unique semantic cases: at least 60
from official sources; comparators no more than one third; at least ten changed
revisions per claimed source; twenty per claimed beat; thirty each for UK, Hong
Kong, English and Traditional Chinese; twenty mixed-language; ten correction or
supersession cases; twenty related-distinct or false-merge opportunities; all
natural warning transitions; and twelve replay/fault warning transitions.

Core semantic thresholds are hybrid recall@12 at least 90%, every slice at least
80%, MRR@12 at least 0.75, event precision at least 90%, event recall at least
80%, AI-consensus editorial pass at least 90% and exact-ID precision@1 of 100%.
Unsupported material claims, distractor false merges, provenance, trust,
temporal, rights and scope failures have zero tolerance.

Operational thresholds include 99.5% completed scheduled checks, no silent loss,
warning p95 at most 15 minutes, non-urgent batch p95 at most two hours,
retrieval p95 at most five seconds, projection age at most one hour and no gap or
dead letter. Missing exposure is `BLOCKED_ACTIVE_COVERAGE`, never a retrospective
extension or pass.

### OD-009 — Reviewer authority

Increment 9 uses AI Review Consensus as editorial-quality ground truth. It has no
human-labelled benchmark and no independent human anchor. ADR 0006 retains this
hard-to-reverse limitation.

The primaries run concurrently. Hermes does not materialise a peer result to a
shared readable view until both are sealed. Gemini adjudicates disagreement or a
zero-tolerance flag; it cannot replace a missing primary. Each role has an
independent long-term-memory namespace and records its exact snapshot digest.

Reviewers may inspect the full host and perform external research. Their evidence
appendix records every query, URL, retrieved-byte digest, observation time and
purpose.

### OD-010 — Comparator and fault phases

The baseline is the frozen legacy SQLite export, RTHK and BBC, plus exact,
full-text, vector, graph and hybrid ablations. Live Brave, GDELT and the legacy
Gemini path are excluded.

The fixed order is deterministic replay, 28-day prospective baseline, sealed
comparators, isolated fault campaign, then sealed AI review and decision. Faults
cover source, duplicate, ordering, correction, prompt injection, schema, model,
embedding, Neo4j, SQLite, queue, budget, rights purge, credential, egress,
publication, production-write, kill and restore behaviour.

### OD-011 — Gross budgets

The hard Epoch cap is £250 for incremental paid APIs. Existing Codex and Grok
subscription fees do not count, and those two CLIs have no request-count,
reviewer-minute or Hermes runtime quota. Every invocation and all observable
usage remain ledgered. Ordinary CLI resource exhaustion relies on the operating
system; P0 controls and the API cash cap still apply.

Other bounds are 8,400 scheduled checks, 10,500 source HTTP attempts, 2,000
metered API/model requests, 20 million metered input tokens, four million metered
output tokens, ten million embedding tokens or 50,000 passages, and 500 GiB-days
of storage. Source attempts stop at three and metered model attempts at two. No
budget transfer is allowed.

### OD-012 — Licences, credentials, egress and protected artefacts

The Hermes credential broker stores secrets in macOS Keychain or an equivalent
local secret store. Ledger records contain class, scope and digest, never secret
bytes. Live acquisition uses public access or owner-provisioned credentials.
Security-boundary testing belongs to local fixtures and cannot contribute bytes
to the live corpus, evaluation or publication.

Raw HTTP is retained for at most seven days or a shorter source term. Governed
passages and model I/O remain through closeout plus 30 days; derivatives purge
within seven days; backup and protected content within 30 days; audit, incident
and purge tombstones remain for 90 days. A rights or legal revocation stops use
and purges protected bytes within 24 hours while retaining non-content proof.

### OD-013 — Production equivalence

Qualification claims component-scoped equivalence only. The isolated identities,
credentials, single Mac mini, bounded ten-source portfolio, disposable Neo4j,
qualification traffic and lack of scale or high-availability proof are material
differences. Reports cannot infer untested scale, availability, identity,
credential, topology or traffic behaviour.

### OD-014 — Incident, recovery and activation

The owner-signed Autonomy Envelope has no fixed expiry or Epoch-count limit.
Hermes may create, freeze, close and replace Epochs, deliver reviewed changes,
recover, create canaries and promote a qualified production route without
waiting for another human reply.

The Autonomous Control Ledger records pre-I/O intent, capabilities, requests,
budgets, decisions, effects, kill, resume, purge and supersession. It is
append-only, hash-chained and checkpoint-signed. A gap blocks external action.

P0 requires kill within 60 seconds, credential revocation and human notification
within five minutes, and containment within 15 minutes. P1 stops within 60
seconds, notifies within 15 minutes and contains within 30 minutes. A P2 root
cause permits at most two autonomous recoveries before escalation.

Recovery never erases the original failure. A failed Epoch remains failed.
Resumed work is recovery evidence unless a new final manifest independently
qualifies. An early stop blocks every later decision-bearing campaign phase;
autonomous containment, restore and recovery-proof work remains permitted but
cannot be counted as a later phase or as passing evidence. Any authenticated
Human Accountable Owner may issue a signed global
or scoped emergency stop. Hermes may resume after deterministic repair proof
unless the stop explicitly says `HUMAN_RELEASE_REQUIRED`.

After the Increment 9 signed closeout, Hermes creates a distinct Increment 10
canary manifest and verified rollback point. A successful canary promotes the
integrated Newsroom app-serving target and its iPhone, iPad and Android reader
surfaces automatically. Discord and OpenClaw remain excluded.

## Execution graph

| Wave | Atoms | Purpose |
|---:|---|---|
| 0 | 9R / issue 488 | Owner-approved plan and immutable manifest |
| 1 | 9A1, 9B1, 9C1, 9D1 | Contracts for boundary, Epoch, comparator and review |
| 2 | 9A2, 9B2 | Isolated deployment and Hermes controller |
| 3 | 9B3 | Prospective campaign |
| 4 | 9C2 | Fault campaign |
| 5 | 9D2 | Sealed decision |
| 6 | 9G | Exact-main signed closeout |

Hermes uses one issue, branch and pull request per atom. A dependency must be
merged before the next wave uses it. Hermes may arrange independent review,
repair and merge after the required checks pass, notifying the human without
waiting for a reply.

## Current non-effect boundary

Before a later phase's exact gate passes, that phase cannot use live sources,
providers, embeddings, credentials, egress, spend, deployment, evidence intake,
publication, canary or production authority. Planning permits only repository
inspection, canonical record construction, deterministic replay, substantive
review and Wayfinder decision recording.

The current production-authority and public-surface digests must remain unchanged
through this planning PR. Conditional future authority is not evidence of a
current effect.

## Approval and verification procedure

1. Verify the canonical plan and agent-profile byte digests.
2. Confirm all fourteen decisions are `APPROVED`, have exactly their required
   bindings and retain at least one evidence reference.
3. Confirm the Wayfinder decision record and owner identity/time.
4. Confirm the branch contains exactly one rebase onto the capacity main.
5. Run focused canonical replay, tamper, profile, dependency and non-effect tests.
6. Run affected compatibility and source-integrity tests.
7. Push the exact head and run ordinary CI plus the complete eighteen-shard SDLC
   evidence gate.
8. Complete substantive review with zero P1, zero material P2 and no unresolved
   thread before marking the PR ready.

## Outcome vocabulary

- `FAILED`
- `INCONCLUSIVE`
- `CONTINUE_SHADOW`
- `COMPARATOR_ONLY`
- `BLOCKED_ACTIVE_COVERAGE`
- `SCOPED_OPERATIONAL_ELIGIBILITY`

No missing evidence, mixed old-version result or incomplete final Effective
Manifest Cohort can become a pass.
