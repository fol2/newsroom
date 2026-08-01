# Increment 5 production retrieval operational contract

**Status:** Contract proposal; no executable runtime authority
**Bound proposal payload:** `sha256:4cc1de54a8d831358bbbe9b65c724d442401e84e3e72918df45807e140bdea56`
**Historical proposal schema:** `sha256:2cdaa92a487ff48dd6095e1cc82af6f67362c168c557d9e6c3ecfe83e83cb647`
**Effective production-qualification schema:** `sha256:1dfdb4de6d2d184efb486d1601a3eb246f1d74352f55955a2b69e962336c31ef`
**Approval-claim schema:** `sha256:8e69e5a66949e103ec4a960af34a509f3ba8b86a9f32b08ed77930f0898b8577`
**Fixture schema:** `sha256:c7faf200a77ddb08fee48394594b85e985aecb9ad342b24cbbf6464bf38f387e`
**Applies to:** issues #251–#254 only after authenticated 5A owner approval

## Fail-closed decision and profile loading

The immutable proposal packet remains pending evidence. A canonical approval
claim is also non-authoritative by itself. Effective production-qualification
authority exists only after `GitHubIssueCommentApprovalVerifier` performs a
fresh authenticated, non-redirecting GitHub REST read and proves the exact
unedited issue #250 comment came from repository owner login `fol2`, immutable
user ID `105634418`, with `author_association=OWNER`, the exact approved body
and the exact comment creation time.

A production retrieval process accepts one canonical manifest validated against
the hardened repository-owned v2 production schema and the verified effective
decision authority. Every required component reference must match contract ID,
contract version, implementation version, configuration digest and identity
digest. Missing, fake, fixture, replay, disabled, unapproved, incompatible or
additional components fail profile validation.

The historical proposal schema exists only under explicit `PROPOSAL_*` names.
All unqualified `PRODUCTION_PROFILE_SCHEMA*` exports resolve to the hardened
qualification schema. The historical schema cannot authorize or validate an
effective production profile.

Fixture replay uses a separate schema, is marked non-qualifying, permits no
protected content, external call or spend, and carries
`production_substitution_allowed=false`. There is no environment-variable,
manifest or adapter upgrade from fixture to production and no default
production manifest.

The repository contains no approval claim or verified approval. Therefore only
fixture replay is admitted and `require_profile(PRODUCTION)` fails before any
model, artifact, index, credential or service action.

## Approval verification controls

The verifier uses one fixed GitHub API endpoint for the claimed comment ID,
explicit token input, a ten-second timeout, no redirects, a 128 KiB response
bound, strict UTF-8 JSON and duplicate-key rejection. It accepts only HTTP 200
GitHub JSON under the fixed API version.

The claim timestamp must be canonical microsecond UTC and must equal GitHub
`created_at`. Edited comments are rejected by requiring
`updated_at == created_at`. The exact comment body is generated from the bound
proposal and schema digests; paraphrases and line-wrap changes are rejected.
The verification digest covers the claim and canonical GitHub response. The
bearer token is not retained in the claim, profile, evidence or effective
contract.

## Artifact and dependency controls

The proposed embedding artifact is preloaded outside the request path and pinned
by package version, package wheel hash, model ID, exact model revision and later
downloaded-artifact digest. Request-time network download, remote code,
external API fallback and unpinned model resolution are prohibited. Model load
is itself an authenticated, audited operational action after verified owner
approval and before qualification.

Neo4j, driver, full-text provider, vector provider, model package and model
artifact compatibility are exact. A change creates a new component digest,
Operational Profile, qualification Epoch and isolated index generation. A
prior generation never silently receives a new chunker, normaliser, model or
index contract.

## Generation lifecycle

Full-text, vector and graph derivatives are generation-scoped. The controller
builds a fresh isolated generation from retained SQLite and governed-object
authority, applies all required derivatives, checks contiguous watermark and
zero required gaps or dead letters, validates index and graph state, executes
qualification probes, then explicitly promotes. The prior generation is
retired or purged under the exact rights-safe request.

A healthy ACTIVE generation is reconciliation-only. Graph or index loss and
contract mismatch require an isolated replacement generation; the serving
generation is not destructively replayed in place. A generation whose component
digests differ from the approved manifest cannot serve. Promotion and rollback
are explicit authenticated decisions.

Rollback may select a prior generation only when its exact component contracts,
dataset rights and purge state remain current. Same-generation mutation,
history rewrite, graph-free rollback and resurrection of prohibited material
are forbidden. If no rights-current prior generation exists, the affected
scope remains unavailable or blocked while a replacement is built. Tested
rollback evidence remains a 5E/#254 deliverable.

## Request limits and outcomes

The contract bounds each request to 5,000 ms, 8 results per branch, 12 retained
dependency roots and 262,144 response bytes. Graph depth is at most 2 and
fan-out at most 32. Named tools own query templates, labels, predicates, trust
scopes, date windows, index names and generation selection; callers cannot
expand them.

Every branch and hydration stage records success or failure, elapsed time,
version, watermark, generation, result count, score and rank receipts,
omissions and dependency health. The final outcome is exactly one of:

- `COMPLETE`: every required mode and authoritative hydration completed under
  current rights;
- `DEGRADED`: an explicitly approved route produced bounded useful context
  while preserving missing branches and mandatory reconciliation;
- `INCOMPLETE`: required authority, provenance, gap closure, collision check or
  hydration is missing;
- `POLICY_BLOCKED`: rights, privacy, trust, purpose or budget policy denies the
  request or result;
- `STALE`: serving projection or authority snapshot exceeds its approved
  freshness bound; or
- `UNAVAILABLE`: a required dependency or index cannot serve.

No returned candidate is a valid no-match unless every required branch
completed and authoritative hydration and collision checks passed. Timeout,
outage, rights denial, partial response, missing index, graph loss, gap, stale
generation and budget block never become no-match or healthy silence.

## Authority, data handling and logging

Neo4j returns canonical identifiers, paths and retrieval metadata. Factual text
and exact decisions are hydrated from SQLite ledger and governed objects after
a current rights check. Projection text, snippets, embeddings, similarity and
rank are never factual or editorial authority.

Logs and evidence use identifiers, digests, counts, durations and bounded
permitted extracts. Secrets, credentials, prohibited expression and personal
data are not written into public artefacts. Untrusted source or model text
cannot alter tools, Cypher, egress, budgets, profiles, quarantine or authority.

The self-hosted model process receives only data allowed by the exact rights
matrix and request purpose. Rights-restricted, personal-data, secret and
credential vectorisation is blocked in Increment 5 v1. Public governed source
text requires a current rights decision. Synthetic qualification text requires
a signed dataset manifest. The effective schema fixes
`protected_content_allowed=false`; verified approval cannot override it.

## Purge and non-resurrection

Rights revocation or tombstone blocks new indexing immediately, removes affected
full-text, vector and graph derivatives from every serving and building
generation, invalidates any Retrieval Context whose permitted material changed,
and records a durable purge receipt. Rebuild reads current authority and cannot
recreate removed material. Qualification includes destructive graph and index
loss followed by rebuild and proves zero residual or resurrected derivatives.

An uncertain purge, ambiguous external or model effect, store failure or audit
failure fails closed and creates a retained Finding or incident. Retry is
idempotent and reconciles ambiguous effects before repeating.

## Health, monitoring and runbooks

Health is multidimensional: decision and profile authority, model artifact,
graph service, full-text index, vector index, generation, watermark and gap
state, authoritative hydration, rights, budget, latency, queue and capacity, and
reconciliation. Last complete success is distinct from last source or index
change.

Metrics and alerts are attributed to exact decision, component, generation,
tool, purpose and Run versions. Alerts prioritize false no-match, rights
leakage or resurrection, write or scope escape, collision-check loss, gap and
dead-letter state, stale ACTIVE generation and loss of all credible required
modes over raw error volume.

5E operational evidence must provide accountable ownership, escalation routes,
versioned runbooks, capacity evidence, artifact preload procedure, model and
index startup checks, backup and rebuild procedure, purge runbook, incident
response, tested rollback, contingency rules and final retained Run decision.
Defining those required fields in 5A is not a claim that `DOPS-064`,
`DOPS-072` or `DEVAL-073` has been delivered.

Acceptance of 5A or successful 5E qualification is not production activation.

## Containment

Contain the narrowest safe component, tool, generation, data class or purpose.
Do not substitute a Comparator, fixture vector, fake graph, external API, older
unapproved model or unrestricted exact search to hide failure. Deterministic
independent collection may continue only where its own authority remains
healthy; graph-dependent decisions use an explicitly accepted exact named route
or enter visible Watch or Operational Hold with later reconciliation.
