# Graphiti one-call combined temporal extraction (#747)

- Role: Dated research qualification of `NewsroomCombinedTemporalExtractionV1`
- Status: Completed provider-free qualification; live calibration owner-gated
- Owner: fol2
- Canonical language: English
- Date: 2026-08-22
- Parent: [#739](https://github.com/fol2/newsroom/issues/739)
- Ticket: [#747](https://github.com/fol2/newsroom/issues/747)
- Closed blocker: [#746](https://github.com/fol2/newsroom/issues/746)
- Measurements: [`2026-08-22-graphiti-combined-temporal-extraction-measurements.json`](2026-08-22-graphiti-combined-temporal-extraction-measurements.json)
- Live packet: [`2026-08-22-graphiti-combined-temporal-extraction-packet.json`](2026-08-22-graphiti-combined-temporal-extraction-packet.json)

This note is non-normative research evidence. It **does not amend `GING-010`**, authorise Cursor SDK runtime, authorise a live call, mutate production Neo4j, or activate backlog ingest.

## 1. Decision

Provider-free recommendation: **`QUALIFIED_PROVIDER_FREE`**.

The Newsroom adapter seam returns entities, relations, `valid_at` / `invalid_at` and integer evidence-segment IDs from **one** `generate_response` leaf. A zero-result object is terminal success. A malformed or temporally invalid object is a typed failed leaf and does not retry. Upstream graphiti-core 0.29.3 remains pinned as regression evidence: zero-edge combined extraction is one `CombinedExtraction` call; a relation-bearing combined extraction then dispatches `BatchEdgeTimestamps`.

This is a call-shape, schema and fail-closed qualification. Fake-transport gold does **not** prove that live model output is no worse than the accepted separate extract path. Token usage remains `UNMEASURED` until an owner-authorised packet; the provider-free proxy is prompt and schema bytes.

Live quality calibration remains **owner-gated**. Issue #746 proved the no-tool Cursor SDK floor is a useful research transport and **REJECT**ed the earlier compact prompts because they lacked deterministic segment IDs and failed gold. This packet substitutes the qualified contract. It does not itself authorise dispatch.

## 2. What is qualified

The authority-private module `newsroom.graphiti_adapter.combined_temporal_extraction` does not fork graphiti-core. It:

1. builds a Newsroom-specific compact prompt and schema;
2. calls an injected fake transport by default;
3. validates and canonicalises the compact object;
4. expands local IDs into Graphiti-compatible node and edge proposals, retaining `entity_type_id` and evidence segment IDs on `attributes`;
5. sets relation temporal fields on the primary object;
6. bypasses `extract_timestamps_batch` after validation;
7. labels every new node `DETERMINISTIC_NEW_NODE` without an LLM dedupe call, keeping same-name local IDs distinct;
8. routes edges through the existing invalidation guard, skipping embeddings;
9. proves one provider leaf before any graph effect (`graph_effect_attempted` is always false; embedding, mutation journal and rollback are not invoked).

Fallback policy remains [#731](https://github.com/fol2/newsroom/issues/731). This seam does not retry an unchanged request.

## 3. Recommendation for #731 and GING-010

[#731](https://github.com/fol2/newsroom/issues/731) may reuse this seam as the **provider-free call-shape candidate** for combined extraction: one distinct leaf per effective source revision, including valid zero-proposal results. Do not adopt graphiti-core's conversational-memory combined prompt. Do not treat the 25,000-token hermetic zero-edge sample as a complete non-zero revision. Do not implement this path in EVALUATION until an owner-authorised live packet passes gold against the separate extract path.

`GING-010` stays as accepted: Graphiti chat remains cursor-agent CLI `composer-2.5` then Grok Build CLI `grok-4.6` medium. The #746 SDK floor is research transport only. No GING-010 amendment is required from this qualification.

## 4. Non-effects

This qualification does not amend `GING-010`, activate Cursor SDK runtime, authorise a live call, weaken Graphiti temporal or evidence semantics, bypass proposal validation, mutate production Neo4j, batch unrelated revisions, publish, or activate backlog ingest.
