# Increment 3A source registry operations

**Status:** Implementation review unit for issue #205  
**Parent:** #143  
**Authorised base:** `main@eb900c8b16e42506fdf0ff7c12de62773d0dad42`  
**Runtime boundary:** Fixture and approved replay only

Increment 3A creates durable source-registry authority. It does not fetch, schedule, parse, execute, project, rank, publish, spend or activate anything.

## Authority boundary

SQLite remains canonical. Checked schema version 10 adds immutable Source Definition, Source Definition Version, Source Item, locator-continuity decision, Source Revision, Discovery Representation and Discovery Occurrence records. Each durable row is committed in the same SQLite transaction as its authenticated command, authorization evidence, audit record and ledger event.

The public surface is `GovernedSourceRegistryAuthoritySystem.sources`. Raw SQLite handles, command grants, command registries and private writers are not exported. The ordinary metadata read returns a redacted `SourceDefinitionVersionSummary`. Full source-version configuration and source-native lineage details, including locators, item identifiers and revision tokens, require the separate `authority.sources.read_sensitive` scope. Authorization occurs before lookup so an unauthorised read cannot become an existence oracle.

## Commands and scopes

| Command | Required scope | Durable meaning |
| --- | --- | --- |
| `source.definition.register` | `authority.sources.manage` | Allocate one stable source identity. |
| `source.definition.version.record` | `authority.sources.manage` | Append one immutable exact-head source-contract version. |
| `source.item.register` | `authority.sources.observe` | Allocate one stable source-scoped item identity under the retained rule. |
| `source.locator.continuity.decide` | `authority.sources.manage` | Record an explicit same, different, possible-replacement, possible-equivalence or uncertain decision when a locator changes. |
| `source.revision.record` | `authority.sources.observe` | Record one deterministically distinct permitted source state. |
| `discovery.representation.record` | `authority.sources.observe` | Record parser/normalizer-specific representation output without changing source state. |
| `discovery.occurrence.record` | `authority.sources.observe` | Record one check-linked observation or re-observation of a retained revision. |

All commands use exact payload schemas, executable golden vectors and canonical JSON. Domain records are immutable aggregate version 1 records. Source Definition Version ordering is separately enforced through an exact version-head chain.

## Core invariants

1. Source Definition and lineage identifiers are canonical UUIDv4 values and cannot be reused for different canonical records.
2. A new Source Definition Version must extend the exact retained head. A semantic no-op against the current head is rejected. A later explicit reversion to older semantics is allowed as a new immutable version, preserving the intervening history.
3. Source roles, portfolio functions, coverage mappings, dependencies, explicit gaps, rights references, observation model, baseline policy and adapter, identity, revision and canonicalisation policies are versioned together.
4. `execution_authority` is fixed to `FIXTURE_REPLAY_ONLY_DISABLED` in the model, payload schema, SQL constraint, startup validation and read summary.
5. A Comparator cannot claim an Active coverage mapping. A source may carry both Anchor and Comparator functions only while the Active contribution remains an actual production-path contribution rather than `COMPARATOR`.
6. A URL or external locator cannot be the sole global Source Item identity. A locator change requires an explicit retained continuity decision; the item row is never silently mutated.
7. Stable Source Item equality is based on the source-scoped identity basis, not policy-version metadata or uncertainty wording. A source-native item identifier is separately unique within its Source Definition.
8. Source Revision equality is based on the source-native revision token and/or permitted source-state digest, not parser, canonicalizer or revision-policy version. Reusing a source-native revision token for different permitted state fails closed.
9. Parser, adapter or normalizer changes create Discovery Representations rather than Source Revisions. Repeated observation creates Discovery Occurrences rather than duplicate Revisions or transition authority.
10. Source-published and source-updated time are retained separately from Newsroom observation and recording time. Exact, approximate and date-only values must use canonical typed representations; unknown and conflicting time remain explicit.
11. One producer-version slot cannot emit conflicting representation bytes. A changed producer contract uses a new slot.
12. Startup reconstructs every retained record from canonical bytes and rebinds normalized SQL columns, child-table blobs, event envelopes, contiguous version chains, exact heads, source-event coverage and the disabled execution boundary. Trigger-bypassing, re-digested normalized-column tampering fails reopen.

## Fixture and approved-replay workflow

1. Register a Source Definition.
2. Record version 1 with explicit roles, portfolio function, coverage contribution, rights reference, observation model, baseline policy and adapter/identity/revision policies.
3. Register stable Source Items under the current Source Definition Version.
4. Append a new Source Definition Version for each material configuration, role, rights, locator, extraction-scope or policy change. Never update an earlier version.
5. When a locator changes, record a continuity decision against the retained prior item and both locator values.
6. Record a Source Revision only when the source-state equality rule establishes a different permitted source state.
7. Record one Discovery Representation for each approved adapter/parser/normalizer producer slot.
8. Record Discovery Occurrences for first observation, delivery and re-observation. `CheckOutcomeId` is a forward-compatible reference seam only; authoritative Check, Attempt, Outcome and baseline state begin in Increment 3C.

## Stop and rollback boundary

Stopping Increment 3A means stop issuing source-registry commands. Existing records remain immutable audit history. There is no network process, source schedule, credential, parser runner, Neo4j source projection, model call, publication path or production activation to disable.

Migration version 10 is forward-only. Before opening a database at version 10, rollback is an ordinary source revert. After version 10 has opened a database, restore a verified pre-v10 backup or apply a reviewed forward fix. Do not delete migration rows, rewrite retained source records or reconstruct authority from a projection.

## Evidence commands

Run from the repository root in the locked development environment:

```bash
uv lock --check
uv sync --dev --locked
uv run python -m pytest -q \
  newsroom/tests/test_source_3a_contracts.py \
  newsroom/tests/test_source_3a_authority.py \
  newsroom/tests/test_source_3a_lifecycle_integrity.py \
  newsroom/tests/test_source_3a_review_regressions.py \
  newsroom/tests/test_source_3a_traceability.py
uv run python -m pytest -q
```

The migration evidence must show `PRAGMA user_version = 10` and the exact checked migration name and checksum. Reopen tests must execute after a complete close. Permission tests must prove metadata reads do not expose sensitive configuration or source-native lineage. Tamper tests must drop the relevant immutability trigger, change one normalized SQL value, restore the trigger and prove reopen rejects the database.

## Deferred by design

Increment 3B owns generic transport and parser execution. Increment 3C owns Check Request, Attempt and Outcome authority, baselines and observable transitions. Increment 3D owns Signal, deterministic Gate Decision, Lead and Watch Condition foundations. Increment 3E owns disposable Neo4j discovery-lineage projection and source, parser, projection and coverage-health seams. Nothing in Increment 3A authorises those later units.
