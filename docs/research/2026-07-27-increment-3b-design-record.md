# Increment 3B generic adapter design record

**Status:** Active implementation design
**Issue:** #206
**Parent:** #143
**Authorised base:** `main@86afbf878f6b138ae0c99386d42828b32f12b645`
**Runtime boundary:** Repository fixtures and approved replay only

## Purpose

Increment 3B adds production-shaped, transport-neutral observation proposal interfaces on top of the stable Increment 3A source contracts. The unit does not create Check Outcomes, Source Revisions, Signals, Leads, source schedules or external access authority.

## Package boundary

The implementation is isolated under `newsroom.discovery_adapters` and contains:

- immutable adapter request, transport receipt, Capture, parser-result and observation-proposal records;
- fixture/replay-only transport scenarios;
- exact endpoint, DNS, redirect, TLS, timeout, size, content-type and encoding policy contracts;
- bounded decompression;
- safe RSS/Atom, structured JSON and maintained-document parsers;
- source-shape contracts and deterministic drift assessment;
- conditional-validator and exact-baseline checks;
- explicit empty, unchanged, observable-change, partial, truncated, blocked, rate-limited, redirected, unauthorised, not-found, gone, malformed, shape-drift and transport-failure outcomes; and
- quarantine recommendations that remain proposals rather than operational decisions.

## Authority separation

1. The public runner accepts only typed 3A Source Definition and Source Definition Version identities, immutable server-owned contracts and one repository fixture/replay transport scenario.
2. There is no HTTP client, socket use, credential input, scheduler, browser adapter or named source.
3. Endpoint and DNS logic validates supplied evidence only; it never performs resolution or access.
4. Adapter and parser output remains untrusted observation proposal data. It cannot write the authority ledger or choose Check, Revision, Signal, Lead or editorial state.
5. A parser or normaliser version change may create a later Representation proposal but cannot create Source Revision identity.
6. `304` may propose unchanged only when the request carries an exact valid baseline and matching validator contract.
7. Empty `2xx`, `404`, `410`, `429`, redirect, TLS, timeout, malformed and partial outcomes retain distinct meanings.
8. Rolling-list absence and partial complete-state results cannot propose withdrawal or clearance.

## Security posture

- HTTPS, exact allow-listed host and port, strict hostname verification and TLS version identity are mandatory contracts.
- IP literals, user-info, fragments, scheme downgrade, unapproved redirects and any private, loopback, link-local, multicast, reserved or unspecified DNS answer fail preflight.
- XML DTDs, external entities, entity expansion and parser network access are rejected.
- JSON duplicate keys, excessive depth, oversized scalars and excessive collection size are rejected.
- Compressed and decompressed byte limits and decompression ratio are independently enforced.
- Source fields named as instructions, tools, URLs, policies or budgets remain ordinary untrusted data and cannot alter runner configuration.

## Normative traceability

The review unit targets `FLOW-010`–`FLOW-026`, `SRC-020`–`SRC-026`, `CHG-001`–`CHG-019`, `DOPS-020`–`DOPS-026`, applicable `DREC-*` and `DOUT-*`, plus accepted ADRs 0001, 0002, 0004 and 0005.

## Deferred work

Check Request/Attempt/Outcome authority, baseline decisions, observable transitions and Operational Findings begin in Increment 3C. Structural Neo4j projection and source/parser/coverage health begin in Increment 3E. Live source qualification, credentials, numeric operational profiles, schedules, shadow, canary and production remain separately blocked.
