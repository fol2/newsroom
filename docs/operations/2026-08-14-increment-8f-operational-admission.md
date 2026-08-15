# Increment 8F Operational Admission

**Role:** final Increment 8 decision and closeout contract

**Status:** implemented; exact-main signed receipt required for closeout

**Owner:** Increment 8 issue #468

**Canonical language:** UK English

**Date:** 2026-08-14

## Decision boundary

Increment 8F admits only the exact deterministic fixture/replay and disposable actual-service qualification boundary. A passing packet makes a separate owner-approved Increment 9 shadow **plan** eligible for consideration. It does not authorise or start a shadow, canary, publication, permanent locality or production activation.

## Qualification packet

The canonical packet binds:

- the frozen readiness record, qualification Run, passing release decision, 120-Case metric report and all required slices;
- zero-tolerance, health, observability, security, runbook and rollback evidence;
- intended hardware and four-scenario capacity evidence;
- zero external spend and exact licence, terms, pricing and replacement-path review digests;
- schema v32, its exact migration history and schema fingerprint;
- checked backup, restore-held-for-reconciliation, passing reconciliation and all eight fixture fault scenarios;
- the exact original-registration Handoff anchor digest, including `max_attempts`;
- independent verification; and
- zero P1 and zero material-P2 findings.

Any missing, stale, failed, forged or mismatched input fails closed before a decision can be created.

## Operational Admission

The only passing verdict is `FIXTURE_OPERATIONAL_ADMITTED`. Its corresponding Increment 9 result is `ELIGIBLE_FOR_SEPARATE_PLAN`. The decision explicitly records:

- `increment9_requires_separate_owner_approved_plan = true`;
- `operational_admission_is_activation = false`;
- `live_shadow_execution_authorised = false`;
- `canary_authorised = false`; and
- `production_activation_authorised = false`.

## Tier-M closeout

The permanent SDLC workflow builds `newsroom.increment8.closeout-receipt.v2` from exact core and actual-Neo4j service lanes. The 13-case inventory covers 8A-8F, v32 recovery migration, the Handoff anchor, hardware/cost/licence, Operational Admission and the retained actual graph-service identity. A manual exact-`main` workflow dispatch validates and signs the decision and receipt together.

Issue #428 closes only after that exact-main receipt proves the anchored Handoff version and this explicit Operational Admission. Parent #148 closes only after the same Tier-M result is retained.
