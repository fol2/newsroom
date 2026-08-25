# Control Plane token-productivity closeout (#732)

## Status

Deterministic exact-main closeout. This issue grants no live provider
authority and no public effects. EVALUATION/private fixtures and injected
writers only. No Grok, Cursor, OpenRouter or Graphiti provider call is
invoked by this document.

The mapping of the sixteen parent behaviour proofs to names already on
`main` is
[`2026-08-21-control-plane-token-productivity-closeout.json`](2026-08-21-control-plane-token-productivity-closeout.json).

The after CSV is
[`2026-08-21-control-plane-token-consumption-after-300s.csv`](2026-08-21-control-plane-token-consumption-after-300s.csv).
It is a ledger export of the deterministic #732 fixture through
`ModelUsageService.export_bucket_csv`, not a live EVALUATION host scrape.

## Canonical split

```text
#727 → #729 → #728 → #730 → #731 → #732 closeout
```

Exact base: `d3b9e21c6857643e9932e186bc2d63307bba92d4`.

## Child line on exact main

Looked up from `git log origin/main --oneline` at this closeout:

| Child | Merge identity on `origin/main` |
| --- | --- |
| #727 zero-quota admission | PR #767 `9c5ca59` |
| #729 durable cooldown | PR #773 `c7f8bf3` |
| #728 usage receipts | `22dee69` Persist exact model usage receipts; later 728 review closures through envelope CSV `e8259b2` |
| #730 hermetic CONT writer | `6745261` through `0a08d8f` |
| #731 Graphiti closeout | PR #731 `f2ea43a`; exact main then `d3b9e21` |

PR #780 does not appear as a merge subject on this exact main. Graphiti
closeout evidence is the #731 line above.

## Policy versions from code

| Policy | Identity |
| --- | --- |
| Write-admission | `newsroom.write-admission.v3+newsroom.evid-012.v7+newsroom.evidence-approval.v8+newsroom.evidence-gates.v2+newsroom.governed-claim.v7+newsroom.governed-input.v10+newsroom.named-entity.v8+newsroom.cont-originality.v3+newsroom.zh-hant-hk-shape.v13` |
| Evaluation cycle | `newsroom.evaluation-cycle.v1@sha256:514c0c23c863fa17a2e17490b1b15ad0067ac5a76c669182e5d7e5ae28d55f45` |
| Model-usage schema | `newsroom.model-usage.v3` |
| CONT hermetic Grok route | `cont-writer-grok-hermetic-command-v2` |
| CONT hermetic Cursor route | `cont-writer-cursor-hermetic-command-v2` |
| Graphiti call-shape `policy_id` | `graphiti-core-0.29.3-newsroom-adapter-v1` |
| Graphiti call-shape `version` | `issue-771-v1` |

Call-shape fields are read from
`newsroom/control_plane/graphiti_call_shape_policy_v1.json`. Schema version
was not bumped for this closeout; `query()` projects existing governor
cooldown columns and `export_bucket_csv` adds columns on the same usage
sqlite.

## Historical baseline (Grok writer lower bound)

Retain the investigation facts. **26,693,877 is a Grok completed-writer
lower bound, not a whole-system total.**

```text
Grok completed writer sessions: 464
input tokens: 26,501,799
total tokens: 26,693,877
input share: 99.28%
median total/session: 51,767
median contextTokensUsed: 37,479
ordinary five-session burst: about 258,000
maximum measured fixed 300-second bucket: 365,249
historical Cursor and Graphiti chat total: incomplete/unreported
```

Companion before CSV:
[`2026-08-21-control-plane-token-consumption-300s.csv`](2026-08-21-control-plane-token-consumption-300s.csv).

## Behaviour-test mapping

| # | Behaviour | Existing test names |
| --- | --- | --- |
| 1 | Zero-quota quality | `test_zero_qualifying_candidates_succeed_without_writer_or_filler`, `test_hold_and_reject_candidates_never_reach_injected_writer`, `test_zero_quota_run_cycle_retains_zero_call_admissions_without_provider_tokens` |
| 2 | At-most semantics | `test_two_write_ready_candidates_never_trigger_three_replacements`, `test_five_ready_candidates_with_valid_primary_results_insert_five`, `test_two_write_ready_run_cycle_attempts_two_not_three_with_usage_join` |
| 3 | No filler | `test_filler_output_is_rejected_and_never_inserted` |
| 4 | Bounded provider leaves | `test_malformed_primary_then_one_valid_fallback_consumes_two_leaf_calls`, `test_second_candidate_cannot_consume_second_cycle_fallback` |
| 5 | Useful-output circuit | `test_exhausted_candidate_routes_open_no_useful_output_circuit`, `test_systemic_authentication_failure_opens_route_circuit_immediately` |
| 6 | Outcome-aware backoff | `test_idle_cycle_keeps_normal_cooldown_and_streak`, `test_first_unproductive_provider_cycle_uses_900_second_backoff` |
| 7 | Durable cooldown | `test_restart_reuses_retained_normal_and_longer_cooldowns`, `test_productive_cooldown_starts_after_complete_work`, `test_governed_cli_cycle_identities_are_visible_on_export_bucket_csv` |
| 8 | Exact receipts | `test_controller_allocates_every_primary_and_fallback_leaf_before_dispatch`, `test_graphiti_chat_and_embedding_are_distinct_and_terminal_ingests_are_valid` |
| 9 | No silent zero | `test_estimate_is_explicit_and_unbounded_missing_usage_opens_only_route`, `test_missing_usage_is_not_inferred_as_zero` |
| 10 | No parent/child double count | `test_parent_and_child_totals_are_not_double_counted` |
| 11 | No generic daily cut | `test_more_than_daily_500k_is_alerted_but_not_an_admission_gate`, plus after-CSV and closeout artefact tests |
| 12 | Per-invocation control | `test_policy_preflight_and_post_dispatch_breach_are_route_local` |
| 13 | Graphiti call shape | `test_checked_call_shape_policy_derives_headroom_from_qualified_fixtures`, `test_atomic_graphiti_allocation_refuses_duplicate_and_call_shape_drift` |
| 14 | Graphiti valid zero result | `test_true_empty_graphiti_extraction_is_a_valid_zero_proposal_success`, `test_zero_proposal_result_is_terminal_revision_coverage` |
| 15 | Regression suites | `newsroom/tests/test_zero_quota_write_loop.py`, `newsroom/tests/test_model_usage_receipts.py`, `newsroom/tests/test_durable_cycle_governor.py`, `newsroom/tests/test_cont_calibration.py`, `newsroom/tests/test_graphiti_adapter_real_executor.py`, `newsroom/tests/test_graphiti_corpus_ingest.py` |
| 16 | Permanent SDLC | `test_ci_is_an_exact_head_bounded_compatibility_gate`, `test_sdlc_workflow_retains_dynamic_complete_evidence_topology`, `test_execution_jobs_check_out_the_exact_evaluated_head_without_credentials` |

This closeout does not re-run those sixteen suites. The JSON mapping
asserts that every listed function name exists under `newsroom/tests/`.

## Quantitative pass table

| Measure | Historical behaviour | Required exact-head outcome | Deterministic exact-head outcome |
| --- | --- | --- | --- |
| Qualifying-output target | implementation behaved like five was a target | 0–5 accepted; no filler | 0–5; two ready never yield three attempts; five ready insert five; filler never inserted |
| Writer calls when `WRITE_READY=0` | not represented | 0 | 0 writer calls, 0 payloads, `retain_zero_call_admission` counts > 0, `leaf_dispatch_count==0` |
| Writer provider leaves per cycle | unbounded by successful-output cap | <= 5 | bounded by existing leaf-budget tests; five ready insert five |
| Writer fallbacks per cycle | unbounded by successful-output cap | <= 1 | second candidate cannot consume a second cycle fallback |
| Replacement attempts after terminal no-result | backlog could continue | 0 by default | exhausted candidate opens the no-useful-output circuit |
| Accepted calibration payloads | not tied to efficiency proof | >= 3 from <= 5 known-ready candidates | **not closed on this atom** |
| Median Grok writer context | 37,479 | <= 10,000 and >=70% reduction | **not closed on this atom** |
| Maximum calibration context | historical max far larger | <= 15,000 | **not closed on this atom** |
| Tokens per accepted payload | unavailable | reported with usage status | after CSV `productive_tokens` on the deterministic fixture |
| No-result tokens | hidden in aggregate | reported explicitly | after CSV `no_result_tokens` |
| Dispatch/receipt mismatch | historical gaps | 0 | mapped exact-receipt tests |
| Missing usage rendered as zero | historical Graphiti gap | 0 | `UNREPORTED`/`AMBIGUOUS`/`INVALID` remain explicit; after CSV splits those counts |
| Daily 500,000 normal hard cut | earlier remediation proposal | absent | `report()["normal_daily_hard_cut"]` is `None`; 500k is alerted but not an admission gate |
| Daily/fixed 300-second reporting | provider-directory reconstruction | exact ledger export | after CSV from `export_bucket_csv` of the deterministic fixture |
| Idle zero-call cycle marked failure | not distinguished | 0 occurrences | `IDLE_QUALIFIED_ZERO` projected into CSV; idle HOLD is admission-only |
| Post-cycle cooldown/backoff bypasses | not durable | 0 | governor cooldown identities survive into CSV JSON columns |
| Graphiti proposal quota | none in product | none; zero-proposal success valid | mapped Graphiti zero-proposal success tests |
| Public effects | 0 | 0 | 0; no publication, no public TargetOperation |

Do not read the third column as a universal tokens-per-article pass number.
The hard pass on this atom is exact accounting, no waste loops, and
retained before/after evidence. Live context reduction remains an
evidence gap.

## After CSV contract

`export_bucket_csv` keeps every historical incident column and adds:

- `unreported_invocations`, `ambiguous_invocations`, `invalid_invocations`
  (`unresolved_invocations` remains the sum of those three)
- `admission_only_hold`, `admission_only_reject`
- `idle_qualified_zero_cycles`, `productive_cycles`,
  `unproductive_provider_cycles`, `systemic_provider_failure_cycles`
- `cont_reported_tokens`, `graphiti_reported_tokens` (`workload_class`
  prefix `CONT_` versus `GRAPHITI_`; `usage_status=REPORTED` only)
- `cycle_ids`, `cycle_outcome_classes`, `cooldown_seconds_values`,
  `next_cycle_eligible_at_values` as JSON arrays

Empty interior buckets inside the proof window are still emitted. Cycle
cooldown fields are projected from `unpublished_governed_cycles` when
that table exists; `model_usage_cycle_outcomes` remains the fallback
store.

## Limitations

- #730 dry selection had 0 `WRITE_READY` candidates, so there is no live
  CONT productive calibration packet on this atom.
- No live provider calls were authorised or executed.
- The after CSV is a ledger export of a deterministic fixture proving the
  query contract, not a live EVALUATION host scrape.
- Accepted calibration payloads, p50 context `<= 10,000`, 70% reduction
  from 37,479, and maximum calibration context `<= 15,000` remain unproved
  here. 26,693,877 stays a Grok-writer lower bound.

## Non-effects

- No `AUTO_PUBLISH`, Publication Bundle, public TargetOperation, Increment
  11 or production mutation
- No daily 500,000-token hard cut
- No Graphiti proposal quota and no #772 cache serving
- No CONT writer-chain, Graphiti SSOT, rights, authority, rollback, or
  #722/#724 corpus-schedule change
- Public effects remain 0
