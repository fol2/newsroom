# Increment 9B1 Evaluation Epoch and Shadow Run authority

- **Status:** authority contract implemented; no external execution
- **Issue:** [#491](https://github.com/fol2/newsroom/issues/491)
- **Planning authority:** [#488](https://github.com/fol2/newsroom/issues/488)
- **Contracts:** `newsroom.increment9.epoch`
- **Isolated persistence:** `newsroom.authority.increment9_shadow_migrations`

## Boundary

9B1 defines immutable prospective authority records and one append-only SQLite
persistence seam. It does not make source, provider, model or embedding calls;
obtain credentials; create spend; start a shadow campaign; publish; ingest
Evidence; or mutate production.

The SQLite schema is standalone. It has a distinct application ID and migration
receipt and is intentionally absent from the production authority migration
registry. Installation rejects a database with a production `user_version`, an
existing application identity or any unrelated table.

## Evaluation Epoch

`EvaluationEpoch` binds:

- the exact owner-approved Increment 9 plan and Shadow Scope;
- source portfolio and prospective universe;
- slice, threshold, comparator and reviewer rules;
- budget and rights rules; and
- opening, cutoff and close instants.

The Epoch is prospective-only. Hindsight changes are false and immutable.
Changing any of the universe, source portfolio, slices, thresholds, comparator,
reviewer, budget or rights dimensions requires a new Epoch.

## Effective Manifest Cohorts

`EffectiveManifest` records exact code, image, configuration, source, provider,
model, prompt, embedding, index, ontology, projector, Operational Profile,
retrieval, triage, Candidate and Handoff identities.

An unresolved identity is explicitly non-decision-bearing. Compatible changes
to those implementation identities create a new `ManifestCohort` inside the
same Epoch. They never alter an existing cohort. Each cohort has an ordinal,
exact predecessor, opening instant, exposure contract and required slices. A
cohort does not carry a predicted closing instant; a successor opening or the
final `CohortCloseout` supplies that later fact.

No cohort predicts at creation whether it will be final. A separate immutable
`CohortCloseout` selects the last retained cohort only after its evidence has
closed. That final cohort qualifies only when:

- its manifest identity is resolved;
- its own exposure minima pass;
- its own complete denominator is retained;
- its observed slices exactly cover every required slice; and
- it has no unresolved identity.

Earlier cohorts remain retained comparative evidence and are never pooled to
qualify the final manifest. The closeout seals the Epoch authority, so no later
cohort or evidence record can be appended under the closed Epoch.

## Run and Attempt lineage

Every `ShadowRun` binds one Epoch digest, cohort digest, Effective Manifest,
production snapshot and pre-run production-non-mutation digest. Prospective
baseline, comparator and fault Runs must be prospective. Replay qualification
and readiness probes remain explicitly separate kinds.

Every `RunAttempt` has a positive ordinal and exact predecessor. A restart needs
a reason. Lost response and ambiguous effect are explicit retained outcomes;
they cannot be rewritten as success.

## Persist-before-effect

Every proposed external operation is first represented by an `EffectIntent`
with Attempt digest, monotonic sequence, request digest and budget reservation.
An `EffectResult` is accepted only after the exact intent is already persisted.
Its response, usage, outcome and completion time are correlated to that intent.
A missing response is valid only for lost-response, ambiguous, unavailable or
failed outcomes.

The authority similarly retains checkpoints, source watermarks, inventory and
ledger digests, provider/token/storage/money cost records, and terminal Run
outcomes. Partial, stale, unavailable, blocked, failed, early-stopped,
inconclusive, lost-response and ambiguous-effect outcomes are never
decision-bearing.

## Isolated persistence

`ShadowEpochAuthority` verifies the standalone schema before every use. Records
are canonical JSON bytes with SHA-256 identities. The schema provides:

- unique schema/id and digest identities;
- bounded record bytes;
- ordered Epoch inventory;
- unique per-record-kind Attempt sequences;
- immutable update triggers; and
- retained delete triggers.

Before append, the authority reconstructs and verifies every referenced Epoch,
manifest, cohort, Run, Attempt and effect intent. A missing or mismatched
predecessor rolls back the transaction. Concurrent duplicate appends fail
closed.

`ReplayController` is a deterministic fake/replay path. It only appends supplied
canonical records in dependency order and exposes no network or production
effect capability.

## Outcomes and currentness

The closed Run/effect outcomes are complete, partial, stale, unavailable,
blocked, failed, early-stopped, inconclusive, lost response and ambiguous
effect. Checkpoints and retained inventories make restart and reconciliation
explicit.

`classify_manifest_change` returns exactly one of:

- `UNCHANGED`;
- `COMPATIBLE_NEW_COHORT`;
- `INCOMPATIBLE_NEW_EPOCH`; or
- `UNRESOLVED_NOT_DECISION_BEARING`.

Unknown dimensions fail closed instead of receiving a guessed compatibility
classification.

## Completion boundary

9B1 proves contracts and isolated persistence semantics only. It does not prove
an actual Neo4j/Graphiti deployment, credentials, default-deny egress, a live
provider path, production-equivalent controller integration or prospective
campaign evidence. Those remain gated by #490, #492 and #493.
