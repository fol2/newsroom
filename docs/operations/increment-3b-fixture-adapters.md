# Increment 3B fixture adapter operations

**Status:** implementation review unit for issue #206
**Authority base:** `main@86afbf878f6b138ae0c99386d42828b32f12b645`
**Execution profile:** `FIXTURE_REPLAY_ONLY`

Increment 3B provides production-shaped transport and parser proposal interfaces without external access. It accepts one typed Increment 3A Source Definition/Version contract and one repository-owned fixture scenario. It returns immutable transport, Capture, parser and observation-proposal evidence. It does not write the authority ledger or create a Check Outcome, Source Revision, Discovery Signal, News Lead, Story Candidate, Operational Finding or production action.

## Public boundary

The public package is `newsroom.discovery_adapters`.

`run_fixture_adapter(request, scenario)` is a pure, synchronous fixture evaluator. There is no HTTP library, socket, DNS resolver, credential input, scheduler, browser runtime, model call or source-specific adapter behind this function. Endpoint, DNS and TLS objects are supplied evidence to validate; the runner never obtains them itself.

The only execution profile is `FIXTURE_REPLAY_ONLY`. Any other profile is rejected at contract construction.

## Supported generic shapes

The review unit supports three generic parser families:

| Adapter kind | Fixture content | Intended observation models |
| --- | --- | --- |
| `RSS_ATOM` | Safe RSS 2.0 or Atom XML | append-only, rolling-list and planned-agenda proposals |
| `JSON_DOCUMENT` | Strict JSON document or item collection | append-only, complete-current-state, rolling-list and explicit-delta proposals |
| `MAINTAINED_DOCUMENT` | UTF-8 plain text or bounded HTML text extraction | mutable-item proposals |

A `SourceShapeContract` names exact item and field paths, required fields, stable source-scoped identity fields and scalar bounds. Identity fields must be required and their paths cannot overlap. A maintained or other singleton document uses an explicit stable singleton identity. A shape contract never creates source, coverage, rights or operational authority.

## Preflight and input safety

Before any fixture body is interpreted, the runner validates:

- canonical ASCII HTTPS URL, exact allow-listed host and port;
- no raw whitespace, control character, backslash, literal or encoded dot segment, noncanonical percent escape, user-info, fragment, IP-literal destination, scheme downgrade or redirect loop;
- a contiguous redirect chain within its configured bound;
- separate DNS and TLS evidence for the initial endpoint and every redirect target;
- supplied DNS evidence containing only canonical public, globally routable addresses;
- supplied TLS evidence with a valid certificate, hostname verification and permitted TLS version;
- independent connect, read, idle and total timing bounds;
- compressed byte, decompressed byte and decompression-ratio limits;
- syntactically valid and exactly permitted content encoding, media type, parameter quoting and charset; and
- response `Content-Length` consistency where supplied.

Preflight rejection returns a `BLOCKED` proposal without a transport receipt. It does not silently broaden the endpoint, switch provider, weaken TLS or create an alternative source path.

## Parser containment

JSON parsing rejects duplicate keys, non-finite numbers, excessive nesting, oversized strings or numbers, excessive collection entries and excessive item counts. RSS/Atom parsing rejects DTD and entity declarations, external resolution, malformed XML, excessive depth, attributes, scalar size and collection size. RSS/Atom and maintained-document bytes must independently decode as UTF-8; an XML declaration cannot override or conflict with the transport charset. Maintained HTML uses a non-network parser and extracts text only; no script, style, link or instruction is executed.

Compressed input is expanded incrementally under independent compressed, decompressed and ratio limits. Malformed, truncated or concatenated compressed streams fail closed.

Source fields such as `instructions`, `tools`, `policy`, `url`, `budget` or similar names remain ordinary untrusted fields. They cannot alter endpoint policy, parser limits, tools, egress, credentials, budgets or authority.

## Honest outcomes

The runner preserves these distinctions:

- `SUCCESS_EMPTY` — a successful response or collection with no proposed item;
- `SUCCESS_UNCHANGED` — exact source/producer/representation replay, a new producer over unchanged source bytes with the same stable item-key set, normalized representation equality, or HTTP `304` with an exact Source Definition Version, validator-policy and retained validator baseline;
- `SUCCESS_CHANGED` — one or more complete observable-change candidates;
- `SUCCESS_PARTIAL` — only independently valid candidates are emitted and incompleteness remains visible;
- `SUCCESS_TRUNCATED` — bounded candidates are emitted and omitted tail remains visible;
- `BLOCKED`, `REDIRECTED`, `RATE_LIMITED`, `UNAUTHORISED`, `NOT_FOUND`, `GONE`, `MALFORMED`, `SHAPE_DRIFT` and `TRANSPORT_FAILED` — distinct non-success or degraded meanings.

Only HTTP `200` is accepted as a body-bearing complete-success contract in this unit. Bodyless `204` and `205` remain explicit empty success with an empty Capture. HTTP `206` and other uncontracted `2xx` statuses fail closed rather than masquerading as complete source state. Timeout, TLS, DNS, malformed input, parser rejection, `404`, `410`, `429`, redirect and empty `2xx` never collapse into healthy unchanged. `204`, `205` and `304` responses carrying payload bytes fail the transport contract. Rolling-list absence never becomes withdrawal. Partial or truncated complete-current-state output never becomes clearance. All proposals retain `authority_effect = NONE`.

A mixed valid/invalid collection may return independently valid items as `SUCCESS_PARTIAL`. An all-invalid collection, identity collision, unexpected strict-shape field, singleton multiplicity or stable item-key drift is contained as `SHAPE_DRIFT` rather than publisher change.

## Identity, baseline and reprocessing

Source Item proposal identity is derived only from the typed Source Definition identity plus the configured required identity-field values, or from the typed Source Definition identity plus an explicit singleton identity. Non-identity fields, uncertainty wording, shape-contract versions, adapter versions, parser versions, normalizer versions, URLs, titles, timestamps, filenames and content digests cannot allocate a second logical Source Item.

An exact baseline retains, separately:

- Source Definition Version and validator-contract identity;
- source-body digest;
- producer-slot digest, which binds adapter, parser, normalizer and shape-contract versions;
- normalized representation digest;
- sorted stable item-key set; and
- retained conditional validator evidence.

Representation equality is parsed and normalized content equality. A parser or normalizer upgrade may therefore keep the same representation digest while changing the producer-slot digest. Reprocessing unchanged source bytes under a new producer remains `SUCCESS_UNCHANGED` when the stable item-key set is unchanged, while retaining the new Parser Result provenance. It cannot fabricate a Source Revision.

The same producer over the same source bytes must reproduce the same representation and stable item-key set. A mismatch is nondeterministic reprocessing and fails closed as `SHAPE_DRIFT`. Reprocessing under a new producer that changes stable item identity is likewise quarantined.

Transport receipts retain only protocol metadata needed for parsing, conditional validation, redirect evidence and retry/back-pressure. Cookies and arbitrary provider-debug headers are discarded. Capture, Parser Result and Observation Proposal construction revalidates exact request, source-version, receipt and capture lineage so records cannot be substituted across attempts.

Increment 3C owns authoritative Check/baseline/transition decisions. Increment 3A remains the only source-lineage authority available in this unit.

## Repository fixtures

Representative fixtures are retained under:

```text
newsroom/tests/fixtures/discovery_adapters/
```

They include valid JSON, RSS, Atom and maintained HTML plus duplicate-key JSON and unsafe entity-bearing XML. Fixtures are test evidence only and cannot qualify any named live source.

## Stop and rollback

Stopping 3B means stop invoking the fixture runner. There is no network worker, credential, schedule, lease, queue, database migration, Neo4j projection or public effect to disable.

This unit adds no authority schema migration and no durable runtime state. Rollback is a normal code revert. Existing Increment 3A source authority remains untouched. Do not interpret removal of this package as removal, retirement or mutation of any Source Definition or retained source lineage.

## Evidence commands

Run from the repository root:

```bash
python -m pytest -q newsroom/tests/test_discovery_adapter_3b_contracts.py
python -m pytest -q newsroom/tests/test_discovery_adapter_3b_security.py
python -m pytest -q newsroom/tests/test_discovery_adapter_3b_parsers.py
python -m pytest -q newsroom/tests/test_discovery_adapter_3b_runner.py
python -m pytest -q newsroom/tests/test_discovery_adapter_3b_review_regressions.py
python -m pytest -q newsroom/tests/test_discovery_adapter_3b_traceability.py
python -m pytest -q
```

Required evidence includes zero required skips, failure or error; exact-head repository gates; no external-I/O imports in the package; and current-head substantive review with zero unresolved P1/P2 findings or review threads.

## Deferred work

Increment 3C owns Check Request/Attempt/Outcome authority, authoritative baseline state, retry state, Operational Findings and observable transitions. Increment 3D owns Signal, deterministic gate and News Lead authority. Increment 3E owns the disposable discovery-lineage Neo4j projection and source/parser/coverage health. Named live sources, credentials, source-specific numeric operational profiles, schedules, browser collection, shadow, canary and production activation remain separately blocked.
