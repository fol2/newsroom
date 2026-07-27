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

A `SourceShapeContract` names exact item and field paths, required fields, identity fields and scalar bounds. Parser output is source-scoped proposal data. A shape contract never creates source, coverage, rights or operational authority.

## Preflight and input safety

Before any fixture body is interpreted, the runner validates:

- canonical HTTPS URL, exact allow-listed host and port;
- no user-info, fragment, IP-literal destination, scheme downgrade or redirect loop;
- a contiguous redirect chain within its configured bound;
- supplied DNS evidence containing only public, globally routable addresses;
- supplied TLS evidence with a valid certificate, hostname verification and permitted TLS version;
- independent connect, read, idle and total timing bounds;
- compressed byte, decompressed byte and decompression-ratio limits;
- exact permitted content encoding, media type and charset; and
- response `Content-Length` consistency where supplied.

Preflight rejection returns a `BLOCKED` proposal without a transport receipt. It does not silently broaden the endpoint, switch provider, weaken TLS or create an alternative source path.

## Parser containment

JSON parsing rejects duplicate keys, non-finite numbers, excessive nesting, oversized strings or numbers, excessive collection entries and excessive item counts. RSS/Atom parsing rejects DTD and entity declarations, external resolution, malformed XML, excessive depth, attributes, scalar size and collection size. Maintained HTML uses a non-network parser and extracts text only; no script, style, link or instruction is executed.

Compressed input is expanded incrementally under independent compressed, decompressed and ratio limits. Malformed, truncated or concatenated compressed streams fail closed.

Source fields such as `instructions`, `tools`, `policy`, `url`, `budget` or similar names remain ordinary untrusted fields. They cannot alter endpoint policy, parser limits, tools, egress, credentials, budgets or authority.

## Honest outcomes

The runner preserves these distinctions:

- `SUCCESS_EMPTY` — a successful response or collection with no proposed item;
- `SUCCESS_UNCHANGED` — exact representation match, or HTTP `304` with an exact Source Definition Version, validator-policy and retained validator baseline;
- `SUCCESS_CHANGED` — one or more complete observable-change candidates;
- `SUCCESS_PARTIAL` — only independently valid candidates are emitted and incompleteness remains visible;
- `SUCCESS_TRUNCATED` — bounded candidates are emitted and omitted tail remains visible;
- `BLOCKED`, `REDIRECTED`, `RATE_LIMITED`, `UNAUTHORISED`, `NOT_FOUND`, `GONE`, `MALFORMED`, `SHAPE_DRIFT` and `TRANSPORT_FAILED` — distinct non-success or degraded meanings.

Timeout, TLS, DNS, malformed input, parser rejection, `404`, `410`, `429`, redirect and empty `2xx` never collapse into healthy unchanged. Rolling-list absence never becomes withdrawal. Partial or truncated complete-current-state output never becomes clearance. All proposals retain `authority_effect = NONE`.

## Identity and reprocessing

Parsed item identity is derived only from the exact Source Shape Contract and its declared source-scoped identity fields. URLs, titles, timestamps, filenames and content digests are not global Newsroom identity.

Parser or normalizer upgrades change the `ParserResult.representation_digest` but do not change the item key and cannot fabricate a Source Revision. Increment 3C owns authoritative Check/baseline/transition decisions; Increment 3A remains the only source-lineage authority available in this unit.

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
python -m pytest -q newsroom/tests/test_discovery_adapter_3b_traceability.py
python -m pytest -q
```

Required evidence includes zero required skips, failure or error; exact-head repository gates; no external-I/O imports in the package; and current-head substantive review with zero unresolved P1/P2 findings or review threads.

## Deferred work

Increment 3C owns Check Request/Attempt/Outcome authority, baseline state, retry state, Operational Findings and observable transitions. Increment 3D owns Signal, deterministic gate and News Lead authority. Increment 3E owns the disposable discovery-lineage Neo4j projection and source/parser/coverage health. Named live sources, credentials, source-specific numeric operational profiles, schedules, browser collection, shadow, canary and production activation remain separately blocked.
