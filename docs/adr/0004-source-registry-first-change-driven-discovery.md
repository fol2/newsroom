---
status: proposed
date: 2026-07-15
owner_review: pending
---

# Source-registry-first, change-driven news discovery

## Decision status

This ADR is a proposal for owner review. The product owner has not accepted the source-registry-first architecture, the role of search, the launch source subset, Hermes orchestration, or any implementation schedule. It authorises neither production nor shadow implementation.

Discovery decisions will be reviewed in sequence rather than accepted as one package:

1. discovery coverage contract;
2. end-to-end discovery workflow;
3. discovery record semantics;
4. source roles and source selection;
5. change and Planned Agenda semantics;
6. triage and event grouping;
7. search and coverage audit;
8. shadow evaluation;
9. reliability and operational behaviour;
10. prioritisation, scoring and outcome vocabulary;
11. locality expansion; and
12. implementation planning.

This ADR may be accepted, amended, split or rejected only after the preceding decisions establish that its proposed architecture satisfies the agreed coverage and workflow contracts.

## Context

The current Newsroom uses broad Brave queries, GDELT, broad media RSS feeds and per-link Gemini clustering. That implementation does not conform to the utility-first charter and does not reliably distinguish a new item, a revision to an existing item, a failed source check and an unchanged source.

Research has identified directly testable UK and Hong Kong feeds, APIs, calendars and pages, but endpoint availability is not evidence that any source set provides sufficient editorial coverage. RSS is a transport rather than a coverage model, and a search provider is an implementation choice rather than a product boundary.

## Candidate decision

The candidate architecture is:

- define an owner-approved coverage boundary before choosing sources;
- maintain a source registry and Planned Agenda for the coverage that is later approved;
- prefer permitted source-native structured interfaces and selective change detection where they fit an agreed source role;
- perform deterministic integrity, identity, duplication and observable-newness checks before model work;
- triage ambiguous survivors in bounded batches before any Story Candidate enters evidence acquisition;
- keep discovery records separate from Source Observations and publication evidence;
- meter search separately for roles that are later approved, rather than making a generic search loop the implicit production clock; and
- make source health, planned-release misses and observed coverage gaps explicit.

Hermes is one possible scheduler and orchestration implementation. It is not part of the product decision, a news source or an evidence authority.

## Questions that must be resolved before acceptance

- What coverage classes are active obligations, best effort, explicit deferred gaps or out of scope at launch?
- What are the exact state transitions from source check to Story Candidate and evidence hand-off?
- How are source-item identity, revisions, deletions, cancellations and current-state transitions represented?
- Which source roles are required for official utility changes, unscheduled incidents, local impact, Hong Kong current affairs and qualifying global events?
- What roles may media feeds, responsible operators, reader leads, GDELT and web search play?
- How will shadow evaluation measure relevant misses without treating another index as recall ground truth?
- Which rights, retention and model-submission decisions are required before each source can be used in shadow or production?
- What reliability, latency and cost evidence is required before production authority?

## Consequences if accepted

- Production would fail closed when its approved discovery configuration or applicable rights policy is missing or invalid; it would not silently substitute broad default feeds.
- An unchanged source check would not invoke a model.
- A source change would remain a discovery signal until it passes the agreed workflow; it would not become evidence merely because it was detected.
- Search, media feeds and other radar channels would remain lead-generating inputs with explicit budgets, rights and evaluation roles.
- Exact endpoints, source schedules, locality coverage, storage technology, scoring and provider choices would remain separate decisions.
