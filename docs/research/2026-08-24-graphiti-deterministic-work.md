# Graphiti deterministic and conditional work qualification (#748)

- Role: Dated provider-free research qualification
- Status: Candidate contracts qualified locally; runtime effectiveness unresolved
- Owner: fol2
- Canonical language: English
- Date: 2026-08-24
- Parent: [#739](https://github.com/fol2/newsroom/issues/739)
- Ticket: [#748](https://github.com/fol2/newsroom/issues/748)
- Implementation atom: [#731](https://github.com/fol2/newsroom/issues/731)
- Primary extraction prerequisite: [#747](https://github.com/fol2/newsroom/issues/747)
- Measurements: [`2026-08-24-graphiti-deterministic-work-measurements.json`](2026-08-24-graphiti-deterministic-work-measurements.json)

This note is non-normative research evidence. It does not amend `GING-010`,
authorise a provider call, install or load a local model, call `add_triplet`,
mutate production Graphiti, publish, or activate backlog ingest.

## 1. Decision

Provider-free recommendation: **`HOLD_FOR_731_RUNTIME_MEASUREMENT`**.

The checked-in contracts demonstrate deterministic, proposal-only corpus
lineage; exact Relation Proposal collapse with retained attribution; local
Entity Resolution Proposal outcomes; and bounded summaries of governed
assertions. They make no provider call and no live graph mutation.

The eleven #747 gold fixtures are useful for deterministic replay and quality
comparison, but they are not an executed #737 effective-revision distribution.
They therefore do not establish live dedupe, summary, fallback or retry leaf
counts. The packet reports expected counts, prevalence and average total tokens
as `UNRESOLVED` rather than turning fixture eligibility into observed usage.

## 2. Deterministic sidecar

`deterministic_sidecar.py` accepts typed authority references containing the
exact canonical record bytes, record identity and SHA-256 digest. Construction
verifies that the digest binds the bytes, that the bytes are canonical JSON,
and that their embedded identity matches the reference.
`DeterministicSidecarInput` also verifies record kinds and every projected
cross-record field: Source Item to Source Definition, Source Revision to item,
predecessor, representation, evidence package, rights decision and chunk, and
the exact reference time and chunk order. Changing a marker without changing
its bound authority record is rejected.

The sidecar projects governed Source Definition, Source Item, Source Revision,
predecessor, representation, evidence package, rights-decision and chunk
records into deterministic Relation Proposals. SQLite governed records remain
authority. Every output is proposal-only and must still pass the existing
Newsroom guard and admission seams.

The #747 compact prompt already contains the sidecar exclusion instruction.
Consequently #748 removes **zero incremental prompt bytes**. Provider-free
fixtures also provide no observation of semantic output that would otherwise
have been emitted, so **zero output bytes are claimed as avoided**. The packet
records only the deterministic projection and its reproducible identities.

## 3. Exact duplicate collapse

Collapse occurs only when a semantic Relation Proposal has the exact same typed
`RelationTriple(subject_ref, predicate, object_ref)` as a sidecar Relation
Proposal. A collapse receipt retains the sidecar proposal and authority
bindings, the semantic proposal, and its evidence-segment identities. Fuzzy
names, predicates and objects never collapse.

## 4. Local Entity Resolution Proposal policy

The local policy evaluates, in order:

1. unique exact canonical name and type;
2. unique governed alias or identifier;
3. unique NFKC, punctuation, spacing and case-normalised name and type;
4. source-constrained, type-compatible embedding similarity.

No local reranker is proposed: the fixture has no reproducible model artefact and therefore holds low-margin cases. The thresholds are integer parts per million. Multiple matches, low confidence
or insufficient winner margin produce `AMBIGUOUS_HOLD`; they never guess or
silently dispatch a provider leaf. The exact required outcomes are:

```text
DETERMINISTIC_EXISTING_NODE
DETERMINISTIC_NEW_NODE
AMBIGUOUS_HOLD
```

Canonical code uses Entity Mention, Entity Resolution Proposal, Canonical
Entity and Relation Proposal terminology; “node” appears only in the required
outcome values or when describing graph storage generically.

## 5. Deterministic summary policy

Only typed `AdmittedSummaryAssertion` values bound to exact admission-decision authority records enter the summary builder. They
are sorted by stable identity and joined without paraphrase. Evidence and
temporal links stay outside the convenience string. Empty input yields
`OMITTED_EMPTY`; bounded input yields `DETERMINISTIC_SUMMARY`; excess length or
count yields `OVERLONG_HOLD`. No truncation or provider fallback occurs.

## 6. Token and leaf-count evidence

The token model keeps three evidence classes separate:

- provider-reported chat or embedding usage;
- source-safe low/base/high estimates; and
- unresolved usage or conditional-leaf distributions.

An adoption recommendation requires all gold quality comparisons to pass, zero
expected timestamp leaves, and a strictly lower target average in each low,
base and high sensitivity scenario. Every conditional class expected count per
effective revision must also be non-increasing and at least one avoidable class
must fall. Bernoulli prevalence remains a separate diagnostic and never
substitutes for integer leaf counts. Missing usage, reported usage without a
decomposed target, an unmeasured class distribution, or any non-improving
scenario produces a hold.

Each measured case carries its own primary leaf or miss count. The report sums
those counts and renders the exact expected count in integer parts per million,
so a two-chunk revision contributes two rather than one and a future exact
reuse hit may contribute zero. `primary_tokens` is the aggregate range for all
primary misses in that case, and a zero-miss case must carry an exact zero
range. Any missing case count, including this provider-free fixture
distribution, renders the primary expectation
`UNRESOLVED`; the report never hard-codes one leaf per revision.

The retained exact-main context contains two terminal effective revisions: one
used three chat leaves and three embedding requests; the other used two chat
leaves and three embedding requests. It contains no provider token counts and
does not classify the chat leaves as primary, dedupe, summary or fallback.
Those classes, expected counts and prevalence remain `UNRESOLVED`; all five
chat leaves are explicitly marked as having unresolved provider token usage.

The sensitivity output nevertheless uses the two retained terminal outcomes
at #737 grain: three additional chat leaves across two revisions and three
embedding requests per revision. It combines the #747 fixture primary proxy,
a 256/1,024/4,096-token range for each unclassified conditional leaf, and a
source-safe whitespace embedding proxy. These are estimates, not reported
provider usage:

| Average tokens per terminal effective revision | Low | Base | High |
|---|---:|---:|---:|
| Current retained leaf-count sensitivity | 1,738 | 3,454 | 9,189 |
| Deterministic target sensitivity | 1,354 | 1,918 | 3,045 |

The numeric sensitivity improves in all three scenarios, but adoption remains
held because conditional leaf classes and gold-quality execution are absent.

## 7. Fallback and retry

#731 remains authority. An unchanged prompt/schema digest is not redispatched
in the same attempt. At most one separately receipted fallback is eligible only
for typed malformed output. Authentication, configuration, timeout,
cancellation and systemic failures do not fall back. Systemic or repeated
no-result failure opens the route circuit for later revisions. #748 creates no
new fallback authority.

## 8. Recommendation for #731

Carry the provider-free candidate contracts into #731 only behind its normal
qualification seam. Before adoption, collect an executed #737-grain corpus that
classifies each distinct request, joins usage to a terminal outcome, and proves
strict low/base/high improvement without quality, rights, temporal, rollback,
proposal-only or full-source-expression regression. Keep every remaining
provider leaf distinct and receipted.

## 9. Reproduction and non-effects

```bash
uv run python scripts/graphiti_deterministic_work.py --check
uv run pytest -q newsroom/tests/test_graphiti_deterministic_work.py
```

The packet records regression-suite evidence as `EXTERNAL_RUN_REQUIRED`; the
commands above provide the executable proof rather than embedding a hard-coded
green result. This qualification has no provider, credential, spend, live
Neo4j, production, publication, model-installation or activation effect.
