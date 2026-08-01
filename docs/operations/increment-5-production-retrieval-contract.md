# Increment 5 production retrieval operational contract

**Status:** Contract proposal; no executable runtime authority
**Bound decision payload:** `sha256:4cc1de54a8d831358bbbe9b65c724d442401e84e3e72918df45807e140bdea56`
**Effective production schema:** `sha256:3e2ac38b2c17d11b8ea29afe58bd0cdf6924146969600cad2b89fc82ec8607b9`
**Fixture schema:** `sha256:c7faf200a77ddb08fee48394594b85e985aecb9ad342b24cbbf6464bf38f387e`
**Applies to:** issues #251–#254 after admitted 5A owner approval

## Fail-closed profile and approval loading

A production retrieval process accepts only a canonical v2 manifest validated
against the repository-owned effective schema, the exact proposal and the
source-pinned owner approval record. Every component reference must match its
contract ID, contract version, implementation version, configuration digest and
identity digest. Missing, fake, fixture, replay, disabled, incompatible or
additional components fail validation.

The approval record is created from the exact owner comment on issue #250 and
committed with its canonical SHA-256 digest pinned in reviewed source. Runtime
code performs no approval HTTP request and accepts no approval/verifier object.
A caller-created authority, subclass, mutable slot, alternate record path or
parsed external record cannot be supplied to the production builder. The
production validator accepts only the canonical module façade and reloads the
same source-pinned record independently.

Before owner approval is materialised, the pinned digest is `None` and the
record path must be absent. A stray unpinned record, missing pinned record,
changed bytes, noncanonical JSON, duplicate key, schema mismatch or wrong
proposal/comment binding fails closed.

Fixture replay uses a separate schema, is non-qualifying, permits no protected
content, external call or spend, and carries
`production_substitution_allowed=false`. There is no environment-variable or
caller-object upgrade from fixture to production and no default production
manifest.

## Artifact and dependency controls

The proposed embedding artifact is preloaded outside the request path and
pinned by package version, package wheel hash, model ID, exact model revision
and later downloaded-artifact digest. Request-time network download, remote
code, external API fallback and unpinned model resolution are prohibited.
Model load is an authenticated, audited operational action after owner approval
and before qualification.

Neo4j, driver, full-text provider, vector provider, model package and model
artifact compatibility are exact. A change creates a new component digest,
Operational Profile, qualification Epoch and isolated index generation. A prior
generation never silently receives a new chunker, normaliser, model or index
contract.

## Generation lifecycle

Full-text, vector and graph derivatives are generation-scoped. The controller
builds a fresh isolated generation from retained SQLite/governed authority,
applies all required derivatives, checks contiguous watermark and zero required
gaps/dead letters, validates index and graph state, executes qualification
probes, then explicitly promotes. The prior generation is retired or purged
under the exact rights-safe request.

A healthy ACTIVE generation is reconciliation-only. Graph/index loss or
contract mismatch requires an isolated replacement generation; the serving
generation is not destructively replayed in place. A generation whose component
digests differ from the approved manifest cannot serve. Promotion and rollback
are explicit authenticated decisions.

Rollback may select a prior generation only when its exact component contracts,
dataset rights and purge state remain current. Same-generation mutation,
history rewrite, graph-free rollback and resurrection of prohibited material
are forbidden. If no rights-current prior generation exists, the affected scope
remains unavailable or blocked while a replacement is built.

## Request limits and outcomes

The contract bounds each request to 5,000 ms, 8 results per branch, 12 retained
dependency roots and 262,144 response bytes. Graph depth is at most 2 and
fan-out at most 32. Named tools own query templates, labels, predicates, trust
scopes, date windows, index names and generation selection; callers cannot
expand them.

Every branch and hydration stage records success/failure, elapsed time, version,
watermark, generation, result count, score/rank receipts, omissions and
dependency health. The final outcome is exactly one of:

- `COMPLETE`: every required mode and authoritative hydration completed under
  current rights;
- `DEGRADED`: an explicitly approved route produced bounded useful context
  while preserving missing branches and mandatory reconciliation;
- `INCOMPLETE`: required authority, provenance, gap closure, collision check or
  hydration is missing;
- `POLICY_BLOCKED`: rights, privacy, trust, purpose or budget policy denies the
  request/result;
- `STALE`: serving projection or authority snapshot exceeds its approved
  freshness bound; or
- `UNAVAILABLE`: required dependency or index cannot serve.

No candidate result is a valid no-match unless every required branch completed
and authoritative hydration/collision checks passed. Timeout, outage, rights
denial, partial response, missing index, graph loss, gap, stale generation and
budget block never become no-match or healthy silence.

## Authority, data handling and logging

Neo4j returns canonical identifiers, paths and retrieval metadata. Factual text
and exact decisions are hydrated from SQLite ledger/governed objects after a
current rights check. Projection text, snippets, embeddings, similarity and
rank are never factual or editorial authority.

Logs and evidence use identifiers, digests, counts, durations and bounded
permitted extracts. Secrets, credentials, prohibited expression and personal
data are not written into public artefacts. Untrusted source/model text cannot
alter tools, Cypher, egress, budgets, profiles, quarantine or authority.

The self-hosted model process receives only data allowed by the exact rights
matrix and request purpose. Rights-restricted, personal-data, secret and
credential vectorisation is blocked in Increment 5 v1. Public governed source
text requires a current rights decision. Synthetic qualification text requires
a signed dataset manifest.

## Purge and non-resurrection

Rights revocation or tombstone blocks new indexing immediately, removes affected
full-text, vector and graph derivatives from every serving/building generation,
invalidates any retrieval context whose permitted material changed, and records
a durable purge receipt. Rebuild reads current authority and cannot recreate
removed material. Qualification includes destructive graph/index loss followed
by rebuild and proves zero residual or resurrected derivatives.

An uncertain purge, ambiguous external/model effect, store failure or audit
failure fails closed and creates a retained Finding/incident. Retry is
idempotent and reconciles ambiguous effects before repeating.

## Health, monitoring and runbook

Health is multidimensional: decision/profile authority, model artifact, graph
service, full-text index, vector index, generation/watermark/gap state,
authoritative hydration, rights, budget, latency, queue/capacity and
reconciliation. Last complete success is distinct from last source or index
change.

Metrics and alerts are attributed to exact decision, component, generation,
tool, purpose and Run versions. Alerts prioritize false no-match, rights
leakage/resurrection, write/scope escape, collision-check loss, gap/dead-letter
state, stale ACTIVE generation and loss of all credible required modes over raw
error volume.

Operational admission in 5E requires an accountable owner, alert routes,
capacity evidence, artifact preload procedure, model/index startup checks,
backup/rebuild procedure, purge runbook, incident response, exact rollback
target, contingency rules and canary scope. Acceptance of 5A or successful 5E
qualification is not production activation.

## Containment

Contain the narrowest safe component, tool, generation, data class or purpose.
Do not substitute a Comparator, fixture vector, fake graph, external API, older
unapproved model or unrestricted exact search to hide failure. Deterministic
independent collection may continue only where its own authority remains
healthy; graph-dependent decisions use an explicitly accepted exact named route
or enter visible Watch/Operational Hold with later reconciliation.
