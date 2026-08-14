# Increment 8E recovery authority

**Role:** implementation record

**Status:** implemented fixture authority

**Owner:** Increment 8 issue #467

**Canonical language:** UK English

**Date:** 2026-08-14

## Boundary

Increment 8E implements deterministic fixture reconciliation, backup, restore, replay, purge and fault-injection evidence. It starts no automatic operation and authorises no live source or provider, credential, egress, spend, shadow, canary, publication or production activation.

## Schema v32

Migration `increment8_recovery_authority_v32` requires an exact checked v31 backup. It adds append-only reconciliation Runs, backup Manifests, restore Runs, purge Receipts and fault-injection Runs. The complete v1-v31 migration history remains retained and there is no destructive down-migration path.

## Reconciliation and replay

Reconciliation separately counts orphaned ownership, missing outcomes, ambiguous effects, duplicate delivery, stale work, pending Handoffs and projection mismatch without model judgement. Any Finding blocks automatic operation. Replay binds exact input and version digests, is capped at 1,000 items and creates a later output instead of rewriting history. Catch-up is capped at the frozen Profile limit and deterministically prioritises Urgent, Time-sensitive and Planned work before Routine history.

## Backup and restore

Checked SQLite backup records authority logical and file digests, integrity status, audit-state digest and the required authority, baseline, dedupe, pending-work and audit inventory. The minimum retention and RPO values come from the frozen Operational Profile.

Restore verifies the exact file digest, logical database digest and SQLite integrity before copying. A successful copy remains `RECONCILIATION_REQUIRED`; automatic operation stays stopped until baselines, leases, queues, Handoffs and coverage posture have each been reconciled.

## Purge and fault injection

Purge Receipts bind scope, before/after state, authenticated authority, reason and time. They always require rebuild and do not resume operation. Fixture fault scenarios verify fail-closed store handling, orphaned leases, missing outcomes, ambiguous effects, duplicate delivery, stale work, pending Handoffs and projection mismatch. Every fault record fixes `live_effect_authorised` to false.
