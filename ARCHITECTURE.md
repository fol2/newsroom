# Newsroom architecture

The Newsroom is a governed editorial system. Authority lives in the SQLite
ledger and governed objects. Neo4j, Graphiti, vector and full-text indexes are
rebuildable projections. Models may propose; only deterministic or authorised
controllers may commit. GraphRAG is mandatory for qualifying production,
evaluation and complete live-shadow profiles.

The running operator is the Hermes Control Plane. The first public target is
the integrated app-serving system and native readers. `newsroom-hub` is
designated private Control Plane UI, not the Control Plane.

## Dead operational stack

OpenClaw planners, the OpenClaw runner, Discord publishing, Brave News, GDELT
DOC 2.0, the broad media RSS pool, `news_pool.sqlite3` and per-link Gemini
clustering are not the operational Newsroom and must not be restarted. There is
no live interim path to preserve. Increment 11B is a Hermes fresh start.
RSS/Atom remains a Source Definition transport. Git history is the archive.

See [ADR 0009](docs/adr/0009-legacy-operational-newsroom-dead.md).

## Where to read next

- [Documentation map](docs/README.md)
- [CONTEXT.md](CONTEXT.md) — domain language
- [docs/adr/](docs/adr/) — accepted architecture decisions
- [Increment 1C operating guide](docs/operations/increment-1c-integrated-foundation.md)
