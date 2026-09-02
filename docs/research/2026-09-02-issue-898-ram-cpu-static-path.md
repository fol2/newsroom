# Attribute Newsroom RAM/CPU — static path packet (#898)

- Role: Dated provider-free research evidence
- Status: Partial static inspection; Mini RSS/CPU remain `UNOBSERVED`
- Owner: fol2
- Canonical language: English
- Date: 2026-09-02
- Ticket: [#898](https://github.com/fol2/newsroom/issues/898)
- Inspection head: `6b1e525cd8333602f8dc72b573a7615ac8e7947e`
- Companion: [`2026-09-02-issue-898-ram-cpu-static-path.json`](2026-09-02-issue-898-ram-cpu-static-path.json)

This note is non-normative. It authorises no Rust production code, provider
call, queue claim, writable canonical-store access, Neo4j mutation,
publication or activation. It is not the accepted #898 measurement packet.

## Decision

**`HOLD_FOR_MINI_MEASUREMENT`**

No `GO` or `NO_GO` is recorded. The pre-registered gate needs measured
removable peak RSS, retained idle RSS and local CPU on the intended Mini.
Unobserved values remain `UNOBSERVED` and are not rendered as zero. A `NO_GO`
must name the next measured non-Rust memory correction; that name cannot be
invented from this inspection.

## Intended hardware

The intended Mini is macm4: Mac16,10, Apple M4, 10 cores, 16 GiB.
`probe_macm4_capacity` checks that host identity and total RAM
(≥ 17,179,869,184 bytes). It does not observe process RSS.

This inspection did not sample a live process tree. Issue #898 forbids
restarting or signalling a live daemon merely to profile it.

## Idle processes versus one-shot work

The documented long-lived Python daemon is the Hermes Control Plane serve
loop (`com.jamesto.newsroom-control-plane`). After a governed unit it waits
the EVALUATION post-cycle cooldown (default and minimum 300 s). Current serve
cycles inject `graphiti=None` and `max_graphiti=0`, so Graphiti work is not in
that idle process.

`scripts/hermes_graphiti_worker.py` requires `--event-id` or
`--campaign-packet`. Exact-event mode is always one event. A LaunchAgent
KeepAlive policy for that worker is not in this repository, so it is unknown
whether the worker is long-lived idle or only transient when an event is
claimed.

`EvaluationGraphitiRunner` construction does not import `graphiti-core`.
`graphiti-core` is imported only inside `newsroom.graphiti_adapter.real._load_graphiti`
at real execution. Hypothesis H1 — that idle Python/import/native-library RSS
of the Graphiti worker dominates before useful work — remains unmeasured.

SQLite is in-process in the Python daemons (ADR 0002). Neo4j is a separate
Community server. The Mini install script does not pin heap or pagecache.
Writer Grok CLI children are per-attempt, not idle retained RSS of the Control
Plane.

## One-event reconstruction (unmeasured H2)

Provider-free one-event unit resolution does not look up that event first. It
reconstructs every current rights-permitted corpus unit, then filters to the
event identity:

```text
_resolve_graphiti_event_units
→ load_graphiti_units
→ _permitted_rows
→ _parsed_observations
→ units_from
→ unique_chunk_units
```

`_permitted_rows` iterates proving-run observations inside a 7-day
`_RAW_HTTP_RETENTION` window, copies each usable HTTP body into memory, and
applies no event-id or unit-ref filter. Full-corpus reconstruction is static
hypothesis H2, not a measured RSS ranking.

If H2 later wins on Mini evidence, the prescribed direction is exact row
selection plus bounded or streaming resolution, not a Rust translation of the
full-corpus scan.

## Repeated parse of retained bodies (path fact)

Latest observation bodies are parsed more than once.

During `_permitted_rows`, `assess_content` already parses each retained body
via `_parsed_item_count` → `parse_observation`. The same bodies are parsed
again when units are materialised (`_parsed_observations` per corpus row).
`run_cycle` also parses `latest_rows` for candidate formation, while those
same latest rows are part of `corpus_rows`.

That is a static duplication fact. How much RSS or CPU it costs is
`UNOBSERVED`.

A no-write Control Plane cycle still materialises latest observations, parsed
items, all permitted corpus units, revisions, candidates and write-admission
decisions in one process before the write loop (H3). Governed admission
generation on already-retained fixtures (H4) was not executed.

## Stages still to measure independently

1. `_permitted_rows`
2. `_parsed_observations`
3. `units_from`
4. `unique_chunk_units` and `revisions_from`
5. full `load_graphiti_units`
6. `_resolve_graphiti_event_units`
7. governed admission generation on already-retained fixtures

Peak RSS must be distinguished from retained RSS after idle or cleanup.
Authoritative method: `/usr/bin/time -l` and `resource.getrusage` for maximum
RSS and CPU; `ps -o rss` for current/retained snapshots. One warm-up and at
least three fresh-process runs per case. Report median CPU and maximum
observed peak RSS.

## Pre-registered GO gate (unchanged)

Recommend a first Rust atom only when all of the following hold:

1. it is the largest measured removable local-memory contributor, or it
   materially reduces the largest long-lived idle footprint;
2. the removable peak is at least 20% of the relevant process peak RSS or at
   least 64 MiB on the Mini;
3. input/output can be bounded and replayed deterministically;
4. Rust needs no authority-store write, credential, provider, Neo4j-mutation,
   publication or activation capability;
5. Python remains authoritative in shadow comparison without dual write;
6. the reduction is not a microbenchmark hidden by unchanged end-to-end RSS.

No candidate currently meets those thresholds because the metric packet does
not exist.

## What still closes #898

Run the issue’s provider-free, read-only cases A–D on the Mini. Produce the
canonical JSON profiling report, stage attribution, ranked boundaries, and an
explicit `GO` or `NO_GO`. Do not start a Rust implementation until that
measured decision.
