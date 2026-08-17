---
status: accepted
date: 2026-08-17
accepted_by_owner: 2026-08-17
---

# Legacy operational Newsroom is dead; Increment 11B is a fresh start

The OpenClaw planners, OpenClaw runner, Discord publishing path, Brave News
API clock, GDELT DOC 2.0 index, broad media RSS pool, `news_pool.sqlite3` and
per-link Gemini clustering path are not the operational Newsroom and must not
be restarted. There is no live interim path to preserve. Increment 11B is a
fresh start: the Hermes Control Plane becomes the first operational Newsroom,
and the first public target remains the integrated app-serving system and
native readers.

RSS and Atom remain valid transports for Source Registry Source Definitions.
Brave and GDELT are permanently ineligible as clocks, indexes, pools,
comparators, Evidence Intake channels or Source Definitions. Topic 7 may still
choose a different bounded-search provider.

Increment 11C is not a compatibility window for this legacy stack. Dual-write
and historical import are refused. Old Discord posts are not Story Versions.
Working-tree deletion of this legacy code is authorised separately and does not
block Increment 11B; git history is the inspirational archive.

Rejected alternatives: keeping OpenClaw and Discord live until 11B; an
Increment 11C dual-run; Discord as a non-production observer; importing
Discord history; treating RSS-the-transport as legacy; leaving Brave or GDELT
available for Topic 7; blocking 11B on tree deletion.

## Evidence

- [When OpenClaw and Discord stop being the operational Newsroom](https://github.com/fol2/newsroom/issues/563)
- [ADR 0004 — source-portfolio-first discovery](0004-source-registry-first-change-driven-discovery.md)
- [ADR 0007 — Discord and OpenClaw are not target dependencies](0007-hermes-autonomy-envelope-and-conditional-activation.md)
