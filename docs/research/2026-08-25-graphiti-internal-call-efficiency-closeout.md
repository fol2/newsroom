# Graphiti internal-call efficiency closeout (#731)

## Status

#731 closeout after #769, #770 and #771. This is not live execution
authority: owner-gated packets remain unauthorised, public effects remain
zero, and no provider is invoked by this document.

The mapping of the fifteen parent behaviour tests to names already on
`main` is
[`2026-08-25-graphiti-internal-call-efficiency-closeout.json`](2026-08-25-graphiti-internal-call-efficiency-closeout.json).

## Canonical split

```text
#729 → #728 → #730 → #769 → #770 → #771 → #731 closeout
```

#772 optional future-donor instrumentation is not required for this
closeout and cannot serve cache hits or skip provider calls.

## Outcome classes

Both terminal success classes count as completed useful ingest work.
Proposal count is secondary telemetry only. No proposal quota exists.

| Stored work outcome | Telemetry class | Completed useful ingest |
| --- | --- | --- |
| `GRAPHITI_SUCCESS` | `TERMINAL_SUCCESS_WITH_PROPOSALS` | yes |
| `GRAPHITI_SUCCESS_ZERO_PROPOSALS` | `TERMINAL_SUCCESS_ZERO_PROPOSALS` | yes |
| `GRAPHITI_PARTIAL` | failed / rolled-back attempt | no |
| `GRAPHITI_RETRY_HELD` | failed / rolled-back attempt | no |
| `GRAPHITI_REJECTED_BINDING` | failed / rolled-back attempt | no |
| other `GRAPHITI_*` failures | failed / rolled-back attempt | no |

A failed attempt is never productive merely because nodes or edges were
partially written. `#724` validation and rollback remain authoritative.
`graphiti_valid_ingest_count` is the count of the two success classes
only.

## Checked `GraphitiCallShapePolicy`

Read from `newsroom/control_plane/graphiti_call_shape_policy_v1.json`:

| Field | Value |
| --- | --- |
| `policy_id` | `graphiti-core-0.29.3-newsroom-adapter-v1` |
| `version` | `issue-771-v1` |
| `graphiti_core_release` | `graphiti-core-0.29.3` |
| `maximum_qualified_fixture_count` | 4 |
| `headroom` | 2 |
| `max_distinct_internal_requests` | 6 |

A later distinct request beyond that qualified shape is
`CALL_SHAPE_DRIFT`. Identical prompt-plus-schema digests within one
attempt are `DUPLICATE_INTERNAL_REQUEST`. Both refusals happen before
provider I/O.

## Withdrawn arbitrary gates

These earlier guessed gates remain absent and are not replaced:

```text
8 Graphiti chat calls per ingest
2 Grok fallbacks per ingest
100,000-token ingest envelope
200,000 unresolved Graphiti tokens per day
```

`max_graphiti=1` remains the EVALUATION ingest-unit throttle. It is not
a provider-call count and is not the target corpus schedule (`GING-001`).

Daily totals remain telemetry. `normal_daily_hard_cut` is `None`.
Missing usage is never coerced to zero.

## Result-aware telemetry

The usage seam is `ModelUsageService.report()["graphiti_result_telemetry"]`
on the existing usage sqlite. It does not open a second invocation
store. Token fields on that object are window aggregates joined to
terminal ingest outcomes in the same report; they do not invent a
per-leaf total when usage is `UNREPORTED`/`AMBIGUOUS`/`INVALID`.
Missing `context_tokens` on an internal request leaves
`context_overhead_per_internal_request` unset rather than zero.

Embedding cash cost remains OD-011 spend evidence
(`graphiti_usage_report` and the spend disposition rows). The usage
report links those leaves through `embedding_od_011_references` and
does not debit CLI chat.

Lag, coverage, watermark and projection gaps remain
`graphiti_admission_telemetry()` on the unpublished Graphiti admission
store. Those tables may be absent from the usage sqlite, so the usage
report does not duplicate that query. A CONT-only usage window reports
Graphiti completed-ingest zeros; admission lag can still be non-zero on
its own store. Graphiti route `OPEN` does not rewrite the CONT writer
circuit; that independence is already proved by
`test_systemic_graphiti_circuit_does_not_block_a_qualified_cont_cycle`.

## Behaviour-test mapping

| # | Behaviour | Existing test names |
| --- | --- | --- |
| 1 | Fixtures derive call-shape max and headroom | `test_checked_call_shape_policy_derives_headroom_from_qualified_fixtures` |
| 2 | `CALL_SHAPE_DRIFT` before the extra provider call | `test_atomic_graphiti_allocation_refuses_duplicate_and_call_shape_drift` |
| 3 | Identical prompt-plus-schema digest refused | same test as 2 |
| 4 | Committed #728 identity before dispatch | `test_chat_transport_observes_committed_identity_and_receipts_requested_max_tokens`, `test_cli_chain_allocates_each_hidden_leaf_before_provider_runner` |
| 5 | `max_tokens` passed and enforced | `test_requested_max_tokens_is_forwarded_and_enforced_on_reported_usage` |
| 6 | Hermetic single-turn Cursor/Grok separate receipts | `test_typed_fallback_has_a_distinct_identity_and_exact_parent` |
| 7 | At most one typed Grok fallback | `test_observer_refuses_a_second_fallback_for_the_same_primary` |
| 8 | Cursor auth/config opens the route circuit | `test_cli_setup_failure_remains_proved_pre_dispatch_zero`, `test_result_shaped_setup_failure_opens_systemic_circuit` |
| 9 | Missing usage is uncertainty | `test_invalid_embedding_token_telemetry_terminalises_as_uncertain`, `test_post_marker_executable_loss_is_usage_uncertain` |
| 10 | Context-policy breach stops later calls | `test_policy_preflight_and_post_dispatch_breach_are_route_local` |
| 11 | Embedding links OD-011 without charging CLI chat | `test_embedding_transport_observes_separate_preallocated_leaf_and_od011_receipt` |
| 12 | Cancellation/timeout kills the child and retains uncertainty | `test_async_cli_capability_preflight_kills_child_on_cancellation`, `test_cancellation_retains_uncertain_leaf_before_control_returns` |
| 13 | Zero-proposal success is a completed ingest | `test_true_empty_graphiti_extraction_is_a_valid_zero_proposal_success`, `test_zero_proposal_result_is_terminal_revision_coverage` |
| 14 | #724 regression suites remain green | `test_graphiti_adapter_real_executor.py`, `test_graphiti_corpus_ingest.py` |
| 15 | Graphiti hold/circuit does not block CONT | `test_systemic_graphiti_circuit_does_not_block_a_qualified_cont_cycle` |

This closeout does not re-run those fifteen suites. The JSON mapping
asserts that every listed function name exists under `newsroom/tests/`.

## Non-effects

- No `GING-001`–`GING-010` amend
- No `GRAG-020/021/023/040/045` or GRAG lock change
- No #765 cache serving or #766 delta/no-op activation
- No #772 donor identities
- No daily Graphiti quota and no 100,000-token ingest reservation
- No live provider packets and no public effects
- #730 remaining CONT calibration and #732 exact-main CONT+Graphiti
  proof remain out of scope
