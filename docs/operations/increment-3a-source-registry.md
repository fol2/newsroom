# Increment 3A source registry operations

Status: implementation review unit for issue #205. This unit is deliberately fixture- and approved-replay-only. It creates durable source authority but does not fetch, schedule, parse, execute, project, rank, publish, spend, or activate anything.

## Authority boundary

SQLite remains canonical. Schema v10 adds immutable Source Definition, Source Definition Version, Source Item, locator-continuity decision, Source Revision, Discovery Representation, and Discovery Occurrence records. Every durable row is written in the same transaction as its authenticated command, authorization evidence, audit record, and ledger event.

The public surface is `GovernedSourceRegistryAuthoritySystem.sources`. Raw SQLite handles, command grants, registry configuration, locators, and private writers are not exported. Metadata reads expose a `SourceDefinitionVersionSummary`; full version details, including the locator and detailed configuration, require the separate `authority.sources.read_sensitive` scope.

## Commands and scopes

| Command | Required scope | Durable meaning |
| --- | --- | --- |
| `source.definition.register` | `authority.sources.manage` | Create one stable source identity. |
| `source.definition.version.record` | `authority.sources.manage` | Append an immutable, exact-head source contract version. |
| `source.item.register` | `authority.sources.observe` | Assign a stable source-item identity under a retained policy. |
| `source.locator.continuity.decide` | `authority.sources.manage` | Record an explicit same/different/uncertain identity decision when a locator changes. |
| `source.revision.record` | `authority.sources.observe` | Record a new permitted source state under an exact revision rule. |
| `discovery.representation.record` | `authority.sources.observe` | Record parser/normalizer-specific representation bytes without changing source state. |
| `discovery.occurrence.record` | `authority.sources.observe` | Record a check-linked observation of an existing revision. |

All commands use exact payload schemas with golden vectors and canonical JSON. Aggregate versions are one because the domain records are immutable; Source Definition Version ordering is separately guarded by the version-head table.

## Invariants

1. A Source Definition ID and every lineage ID are never reused for different canonical bytes.
2. A new Source Definition Version must extend the exact retained head. A no-op semantic version is rejected.
3. Roles, portfolio functions, coverage mappings, dependencies, explicit gaps, rights, observation model, baseline policy, identity rule, revision rule, and canonicalization rule are versioned together.
4. `execution_authority` is fixed to `FIXTURE_REPLAY_ONLY_DISABLED` in the model, payload schema, SQL check, startup integrity check, and metadata view.
5. External locator text cannot be the sole Source Item identity. Locator changes require a retained continuity decision; the item row is never silently mutated.
6. A source-state digest identifies a Source Revision. Parser or normalizer changes create Discovery Representations. Repeat checks create Discovery Occurrences. These operations are not interchangeable.
7. One producer-version slot cannot emit conflicting representation bytes. A changed parser or normalizer version creates a new slot.
8. Startup validates canonical bytes and digests, normalized child tables, event envelopes, contiguous version chains, exact version heads, source-event coverage, and the disabled execution boundary.

## Fixture/replay workflow

1. Register a Source Definition.
2. Record version 1 with explicit roles, portfolio function, coverage contribution, rights, observation model, baseline policy, and identity/revision policies.
3. Register stable Source Items under the current version.
4. Append a new Source Definition Version for any configuration or locator change. Never update an old version.
5. If a locator changed, record a continuity decision against retained old and new locators.
6. Record Source Revisions only when permitted source state changes.
7. Record a Discovery Representation for each approved parser/normalizer producer slot.
8. Record Discovery Occurrences for first observation and re-observation. `CheckOutcomeId` is a forward-compatible seam; authoritative Check and baseline state begin in Increment 3C.

## Stop and rollback boundary

Stopping 3A means stop issuing source-registry commands. Existing rows remain immutable audit history. There is no network process, schedule, credential, parser runner, Neo4j source projection, model call, publication path, or production activation to disable.

Schema migration v10 is forward-only. Operational rollback is application rollback to a build that understands v10, not destructive database downgrade. If a pre-v10 build must be inspected, use a copied database and read-only tooling; do not mutate or delete source authority.

## Evidence commands

Run from the repository root:

```bash
python -m pytest newsroom/tests/test_source_3a_contracts.py -q
python -m pytest newsroom/tests/test_source_3a_authority.py -q
python -m pytest newsroom/tests/test_source_3a_lifecycle_integrity.py -q
python -m pytest newsroom/tests/test_source_3a_traceability.py -q
python -m pytest -q
```

The migration test must show `PRAGMA user_version = 10` and the exact checked v10 migration name/checksum. Reopen tests must pass after a complete close. Permission tests must prove metadata reads do not expose locators and that sensitive reads fail before existence lookup when the scope is absent.

## Deferred by design

Increment 3B owns generic transport and parser execution boundaries. Increment 3C owns Check, Request Attempt, Outcome, baseline state, observable transitions, and planned-agenda operational semantics. Increment 3D owns Signal, Gate, Lead, Watch Condition, Candidate, and evidence intake. Increment 3E owns disposable Neo4j discovery-lineage projection and projection health. Nothing in 3A authorizes those later units.
