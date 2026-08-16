---
status: accepted
date: 2026-08-16
accepted_by_owner: 2026-08-16
---

# Increment 9Q qualification evidence before First I/O Gate Records

Increment 9 remains `BLOCKED_ACTIVE_COVERAGE` because twenty First I/O Gates
are `MISSING`. The owner replaced `REMAIN_BLOCKED` with Increment 9Q: serial
packets that produce Qualification Evidence only.

A 9Q packet does not mint a First I/O Gate Record. Those records bind one exact
main SHA and become `STALE` after later merges. Records are minted once, after
all twenty evidence packets close, on one freeze checkout. A 9P Proving Gate
PASS does not satisfy a namesake First I/O Gate.

Rejected alternatives: reopening the Increment 9 28-day shadow Epoch; minting a
campaign GateRecord per packet; treating 9P PASSes as First I/O Gate PASSes;
starting Increment 11.
