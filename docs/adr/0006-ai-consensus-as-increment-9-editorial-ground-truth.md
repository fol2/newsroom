---
status: accepted
date: 2026-08-15
accepted_by_owner: 2026-08-15
---

# AI consensus as Increment 9 editorial ground truth

## Decision

Increment 9 uses sealed, provider-independent AI review consensus as its
editorial-quality ground truth. It has no human-labelled benchmark and no
independent human-review anchor.

Two primary reviewers evaluate every decision-bearing case independently:

- Claude Sonnet 5 through Claude Agent SDK; and
- Grok 4.6 through Grok Build CLI.

Gemini 3.7 Flash, through the Gemini API, adjudicates only a genuine
disagreement or a zero-tolerance flag. It cannot replace an absent or invalid
primary review. The OpenAI `gpt-5.6-terra` system under test is outside every
reviewer family.

## Independence contract

Both primaries receive the same sealed case assignment and start concurrently.
Hermes withholds each result until both are sealed. A reviewer cannot read a
peer result, an adjudication or the later Hermes decision because those objects
do not enter a shared readable view before sealing.

Each role has a separate long-term memory namespace. Every invocation records
the exact memory-snapshot digest. Peer verdicts never enter another role's
namespace.

Reviewers may inspect the full local host and repository and may conduct
external research. This is deliberate: the evaluation judges autonomous
editorial investigation rather than packet-only classification. Each reviewer
must retain an evidence appendix containing every external query, URL,
retrieved-byte digest, observation time and purpose.

## Version and validity contract

Models and their tools follow their current provider route. Each invocation
records every observable model, CLI or SDK identity. An Epoch may therefore
contain more than one Effective Manifest.

Qualification applies only to the final Effective Manifest Cohort, and that
cohort must independently satisfy the complete exposure contract. Earlier
cohorts remain comparative evidence. A backend identity that cannot be resolved
uniquely is `IDENTITY_UNRESOLVED` and is not decision-bearing.

An invalid result, missing primary, unresolved identity or unavailable required
family is `NOT_EVALUATED`. There is no silent provider replacement, prose
guessing or deterministic repair of a review verdict.

## Why this is an ADR

This decision is hard to reverse after prospective evidence exists, surprising
because no human ground-truth set anchors the result, and a real trade-off. It
maximises autonomous operation and cross-provider review capacity while giving
up direct measurement against human editorial judgement.

## Consequences

- AI consensus may establish the Increment 9 editorial metric, but reports must
  state plainly that it is AI consensus rather than human review.
- Cross-provider agreement does not prove that the agreed judgement matches a
  human editor's judgement.
- Shared model blind spots, research-source errors and long-term-memory effects
  remain accepted limitations and must be visible in closeout.
- Missing or invalid review cannot be hidden by changing the denominator.
- A later human-labelled benchmark is a new Evaluation Plan and cannot be
  presented as retrospective validation of this Epoch.

## Rejected alternatives

### Human-labelled anchor set

Rejected by the owner in favour of a fully autonomous evaluation.

### Three-model majority vote on every case

Rejected because it spends adjudicator capacity when the primaries agree and
allows a third model to obscure a missing primary.

### Same-family fallback

Rejected because it weakens the accepted provider-independence claim.

## Evidence

- [Wayfinder decision: Bind Increment 9 owner decisions and the Hermes autonomy envelope](https://github.com/fol2/newsroom/issues/503)
- [Wayfinder map: Increment 9 owner decisions and Hermes autonomy](https://github.com/fol2/newsroom/issues/502)
