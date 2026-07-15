---
status: accepted
date: 2026-07-15
---

# Source-registry-first, change-driven news discovery

The launch Newsroom will use a beat-owned Source Registry and Planned Agenda as its primary discovery boundary. Source-native structured monitoring and selective change detection emit Discovery Signals; deterministic integrity, newness, duplication and unambiguous scope gates precede model work, and ambiguous survivors are triaged in batches before any Story Candidate may begin evidence acquisition. Hermes may schedule collectors and wake triage work, but it is neither a news source nor evidence authority.

Search remains provider-neutral, separately metered and hard-capped for outer-radar discovery, explicit coverage gaps and recall auditing. It is not the production clock, but launch discovery is not search-zero: a bounded search lane remains available to measure and repair omissions in the initial registry. GDELT, media feeds and search results are lead-generating signals rather than publication evidence, and recall audits must be interpreted with an editor-led missed-story review rather than treating another index as ground truth.

An RSS-only design was rejected because RSS is a transport rather than a coverage model. A generic search-first firehose was rejected because it spends requests and model work when nothing relevant changed, privileges media-dense events and obscures whether important official sources are healthy. A search-zero launch was rejected because a new registry has not yet demonstrated adequate recall.

Consequently, production must fail closed when its approved registry or applicable rights policy is missing or invalid; it must not silently substitute broad default feeds. Source health, planned-release misses and coverage gaps become explicit operational records.

Launch begins with the smallest owner-approved direct-watch subset that covers the agreed UK and Hong Kong beats. The concrete source map is supporting evidence rather than a requirement to activate every interface. Exact endpoints, expansion sources, polling schedules and search-provider choices remain later implementation decisions; this ADR makes no locality-completeness or detection-time commitment.
