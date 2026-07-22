# SDLC-V2 owner acceptance

- Role: Normative owner acceptance record
- Status: Accepted
- Owner: fol2
- Canonical language: English
- Date: 2026-07-22
- Specification: `docs/specs/sdlc/high-performance-evidence-sdlc.md`
- Migration plan: `docs/plans/2026-07-21-007-sdlc-v2-migration.md`
- Contract version: `sdlc-v2.2`
- Issue: #98
- PR: #99

## Decision

The owner accepts `SDLC-V2` and authorises its reversible Phase 1/2 implementation.

This record supersedes only the pre-acceptance status metadata and outstanding-owner-decision section in the referenced `sdlc-v2.2` specification and migration plan. Their substantive technical contract is adopted without weakening it.

Accepted policy values:

1. Review trigger: 400 net executable lines / 12 changed files.
2. Selective-test blocking eligibility: at least 30 calendar days and 500 representative changes, zero known misses, and at least 99.5% mutation-kill recall relative to the full suite.
3. A prewarmed ephemeral runner may be evaluated only after measured hosted-runner feedback p95 cannot meet 60 seconds.
4. A critical main-certification failure automatically pauses merges until owner resume.
5. Evidence retention: PR 30 days, main 180 days, release 7 years.

## Implementation authority

This acceptance authorises:

- Phase 1 telemetry, risk classification, budget enforcement and typed evidence;
- Phase 2 one always-reporting shadow decision workflow;
- exact-head paired evidence against the existing workflow set;
- reversible caching and conditional actual-service experiments within the accepted plan.

It does not authorise release, production, live-source, Graphiti, model, embedding, publication, shadow product execution, canary, spending or public effects.

Existing workflows remain in place until paired shadow evidence satisfies the migration plan. B3 product work may resume after minimum Phase 1/2 controls are available.
