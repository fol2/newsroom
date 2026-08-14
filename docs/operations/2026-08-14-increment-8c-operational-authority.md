# Increment 8C operational authority

**Role:** implementation record

**Status:** implemented fixture authority

**Owner:** Increment 8 issue #465

**Canonical language:** UK English

**Date:** 2026-08-14

## Boundary

Increment 8C implements the Operational Profile frozen by 8R. It is a deterministic fixture authority only. It authorises no production scheduler, live source or provider, network egress, credential use, external spend, shadow, canary, publication or production activation.

## Schema v31

Migration `increment8_operational_authority_v31` is gated by an exact checked v30 backup. It adds append-only records for:

- the exact approved Operational Profile;
- due-work state versions;
- bounded lease state versions;
- classified retry findings;
- quarantine and authenticated release decisions; and
- immutable Handoff registration anchors.

The migration preserves the complete v1-v30 history and has no destructive down-migration path.

## Queue, lease and recovery semantics

`newsroom.increment8.operations` provides deterministic urgent-first due selection, a 1,000-item queue limit, a 200-item urgent reserve, four-host concurrency, bounded lease renewal with recorded progress, three-attempt exponential retry findings and explicit quarantine. Retry failures do not refresh health or become editorial “no news” outcomes. Queue, lease and quarantine versions retain exact predecessor digests.

Capacity evidence must include average, peak, no-change-heavy and failure-heavy scenarios. It evaluates the frozen CPU, memory, disk, queue-headroom and urgent-reserve values without activating work.

## Handoff registration hardening

New operational registrations use `register_anchored_handoff()`, which atomically writes the accepted v17 Handoff and a v31 canonical registration anchor that binds `max_attempts`. Legacy rows are reported as `GRANDFATHERED_UNANCHORED`. A snapshot captured during hardening is labelled `OBSERVED_ONLY` and never represented as an original registration fact.

The current-use check reconstructs the canonical anchor, verifies every retained scalar and may require the registration-time anchor digest pinned by a later Operational Admission packet. This makes trigger tamper, scalar drift and self-consistent anchor replacement visible at the admission boundary. Historical reads remain separate from operational eligibility.

Issue #428 remains open until Increment 8F binds the exact anchor/version in an explicit Operational Admission decision and completes its final review gate.

## Evidence

Focused tests cover v30-to-v31 backup and upgrade, replay, append-only state, deterministic ordering, queue and host bounds, progress-only lease renewal, retry exhaustion, quarantine, capacity scenarios, grandfathering, observed-only history, atomic registration, backup/restore and tamper detection. Authoritative SDLC evidence remains a separate merge gate.
