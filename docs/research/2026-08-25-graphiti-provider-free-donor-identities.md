# Graphiti provider-free donor identities (#772)

- Role: Dated provider-free implementation record
- Status: Completed — `CONTROLLER_ONLY_PROVED`; donors seeded, not served
- Owner: fol2
- Canonical language: English
- Date: 2026-08-25
- Parent: [#731](https://github.com/fol2/newsroom/issues/731)
- Ticket: [#772](https://github.com/fol2/newsroom/issues/772)
- Research basis: [#765](https://github.com/fol2/newsroom/issues/765) `RESEARCH_ONLY`; [#766](https://github.com/fol2/newsroom/issues/766) `REJECT`
- Primary extraction prerequisite: [#747](https://github.com/fol2/newsroom/issues/747)

This note is non-normative research evidence. It does not amend `GING-010`,
authorise cache serving, skip a provider call, mutate production Neo4j, activate
backlog ingest, or publish.

## Track A decision

`CONTROLLER_ONLY_PROVED`.

Every gold fixture was validated twice with identical body, evidence segments,
reference time, temporal basis and policy, schema and provider-free gold payload,
but different `revision_id` and `predecessor_revision_id`. Entity Mentions,
Relation Proposals, evidence-segment resolution and absolute or null temporals
were identical. The two lineage fields therefore moved out of model-visible
prompt text. They remain controller metadata on `SourceRevisionInput`; GING-002
continues to bind `revision_id`. Neither field enters the semantic request
identity.

The changed prompt measurement pin was regenerated with
`measure_token_effectiveness()` from
`scripts/graphiti_combined_temporal_extraction.py`.

## Donor seed boundary

`SemanticExtractionRequestIdentityV1` and `EmbeddingRequestIdentityV1` retain
canonical request manifests. Only terminal validated #747 success results mint
`ValidatedSemanticExtractionArtifactV1`; embedding results retain vector length,
finite-value evidence and an IEEE-754 byte digest rather than canonical JSON
floats. In-memory and caller-supplied SQLite stores are insert-only.

Matching identities are telemetry only. Extraction and embedding still dispatch
through their ordinary providers unless the existing same-ingest completed
marker selects replay. No donor API returns proposal or vector material for
reuse. The EVALUATION executor seeds
`workspace_root/donor_identities.sqlite3` beside the disposable namespace so
donors outlive workspace cleanup. Callers may still inject an in-memory store.

This work does not amend `GING-010`, does not authorise cache serving and grants
no authority to retained material.

## Reconsideration trigger

Reconsider exact reuse only after all #765 section 9 conditions exist:

1. qualified #747 donor artefacts with exact request and validator identities;
2. proved separation or deliberate retention of source-specific prompt metadata;
3. exact embedding input/vector identities and integrity evidence;
4. materially improved retained-expression coverage beyond the unresolved 711 rows;
5. provider-free hit, rebinding, rights, corruption and concurrency fixtures; and
6. provider-reported low/base/high net savings with no quality, evidence,
   temporal, rights or rollback regression.
