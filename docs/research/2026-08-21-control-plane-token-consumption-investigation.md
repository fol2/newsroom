# Control Plane 300-second token consumption investigation

**Status:** Root cause confirmed; reporting only

**Snapshot:** 2026-08-21T09:20:04Z

**Scope:** Local Hermes Control Plane, its CONT writer chain and its EVALUATION
Graphiti route. No public dispatch or production effect was exercised.

**Companion data:**
[`2026-08-21-control-plane-token-consumption-300s.csv`](2026-08-21-control-plane-token-consumption-300s.csv)
contains one row per 300-second UTC bucket from 2026-08-20T00:55:00Z through
2026-08-21T09:20:00Z. The exact-main closeout is
[`2026-08-21-control-plane-token-productivity-closeout.md`](2026-08-21-control-plane-token-productivity-closeout.md).

## Executive finding

The dramatic consumption is real, but `--interval 300` is not a token budget
or a fixed five-minute job boundary. The daemon performs intake and a complete
cycle first, then sleeps for 300 seconds. A busy cycle therefore emits a burst
of model requests and the next cycle starts only after that work plus the
sleep.

The dominant measured cause is the CONT writer:

1. `max_writes=5` limits five **successful stored drafts**, not five model
   attempts.
2. Every candidate attempt launches a fresh Grok CLI process in a fresh
   temporary directory.
3. Each fresh CLI session loads a large global agent context. The retained
   Grok telemetry reports a median `contextTokensUsed` of **37,479**, although
   the median Newsroom prompt is only **389 characters**.
4. A completed Grok writer session consumed a median **51,767 total tokens**.
   A normal burst of five completed sessions is therefore about **258,000
   tokens**, before Cursor fallback or Graphiti.
5. Invalid, failed or planning-residue output does not consume the five-write
   allowance. The loop continues to another candidate, and the writer may also
   call Cursor as fallback.

This is a scheduling and invocation-amplification problem, not an unusually
large article-body problem.

## Measured consumption

The Grok CLI retained provider usage for 464 completed Newsroom writer sessions.
The measurements below are exact sums of those retained `turn_completed.usage`
records.

| Metric | Observed value |
|---|---:|
| Grok writer session directories | 469 |
| Timestamped Grok sessions | 468 |
| Sessions with retained usage | 464 |
| Provider model calls inside those sessions | 499 |
| Input tokens | 26,501,799 |
| Output tokens | 192,078 |
| Total tokens | **26,693,877** |
| Cached-read tokens | 3,971,712 |
| Reasoning tokens | 59,627 |
| Input share of total | 99.28% |
| Median total per completed session | 51,767 |
| Mean total per completed session | 57,530 |
| p95 total per completed session | 106,734 |
| Maximum single-session total | 220,007 |

Daily measured totals:

| UTC date | Sessions | Completed | Total tokens |
|---|---:|---:|---:|
| 2026-08-20 | 420 | 417 | 24,251,855 |
| 2026-08-21 through 08:27Z | 48 | 47 | 2,442,022 |

The largest 300-second UTC buckets were:

| Bucket start | Grok sessions | Model calls | Total tokens |
|---|---:|---:|---:|
| 2026-08-20T09:20:00Z | 6 | 6 | 365,249 |
| 2026-08-20T17:55:00Z | 4 | 6 | 311,384 |
| 2026-08-20T06:15:00Z | 3 | 5 | 266,824 |
| 2026-08-20T21:15:00Z | 3 | 4 | 263,164 |
| 2026-08-21T08:25:00Z | 5 | 5 | 261,442 |

Across the 389 exported buckets, 144 buckets exceeded 100,000 measured Grok
tokens and 14 exceeded 250,000. The full bucket-by-bucket values are in the
companion CSV.

## Why a small article costs about 52,000 tokens

`run_grok_cli()` starts the CLI in a new `TemporaryDirectory` for each draft.
The command disables web search, planning and subagents, but it does not disable
the global system prompt, installed skill catalogue or MCP context. Retained
session artefacts show:

- median Newsroom prompt length: 389 characters;
- median Grok `contextTokensUsed`: 37,479 tokens;
- fixed retained `system_prompt.txt`: 5,773 characters;
- additional injected skill and MCP state in the chat history;
- median billed input: 51,371 tokens;
- median cached-read count: only 128 tokens.

The process consequently pays the context bootstrap repeatedly for short,
independent article prompts. Cached reads were 14.99% of measured input; the
remaining measured input was 22,530,087 tokens.

## Amplifiers beyond the normal five-session burst

### Success-counted loop

The candidate loop stops when `minted >= max_writes`. Failed model calls do not
increment `minted`; they are caught and the loop continues. With roughly
280–295 candidates present during the observed busy period, the theoretical
attempt count is much larger than five whenever provider or output validation
is unhealthy.

### Cursor fallback

The writer calls Grok first. Any runtime, JSON or finished-copy validation
failure causes a second call through Cursor. Local Cursor transcripts contain
94 direct Newsroom writer invocations over the wider retained period, 93 of
them inside the CSV window. Those transcripts do not contain token usage, so
their tokens are absent from the measured total.

### Graphiti work

The Control Plane log reports 67 cycles with `graphiti=1`. Historical Graphiti
chat usage was not retained as tokens. The old executor explicitly recorded
zero request and response tokens, while the current result mapping assigns
`request_tokens` from embedding usage only and sets `response_tokens=0`.
Current CLI invocation receipts retain provider and outcome but no chat token
counts.

The error log contains 3,318 `Error in generating LLM response: Connection
error.` entries. They are untimestamped and do not prove billed tokens, but
they demonstrate a large unmetered provider-attempt surface during the same
operational period.

## Accounting boundary

**26,693,877 is a measured lower bound, not the whole Control Plane total.** It
includes retained Grok CONT-writer usage only. It excludes:

- Cursor writer fallback tokens;
- historical Graphiti chat tokens;
- Graphiti requests that failed before a durable receipt;
- the one timestamp-less Grok session and five Grok sessions without usage;
- any provider-side difference not written into local CLI telemetry.

The unpublished ledger currently has no writer-token receipt. Historical log
and current database counts also diverge: the log reports 67 Graphiti successes,
whereas only 12 legacy COMPLETE Graphiti rows remain and the new corpus-ingest
receipt tables are empty at this snapshot. The ledger therefore cannot
reconstruct historical token consumption by itself.

## Code path evidence

| Behaviour | Evidence |
|---|---|
| Sleep happens after the complete cycle | `scripts/hermes_control_plane.py:123-143` |
| Default maximum is five successful writes | `scripts/hermes_control_plane.py:53-54`; `newsroom/control_plane/cycle.py:1495-1528` |
| Fresh Grok temporary directory per attempt | `newsroom/control_plane/writer.py:151-176` |
| Grok failure invokes Cursor fallback | `newsroom/control_plane/writer.py:197-224` |
| Graphiti can invoke Cursor then Grok for every internal chat request | `newsroom/graphiti_adapter/cli_client.py:213-295` |
| Graphiti chat invocation records omit tokens | `newsroom/graphiti_adapter/cli_client.py:229-291` |
| Current extraction usage counts embedding tokens only | `newsroom/graphiti_adapter/result_mapping.py:196-214` |

## Current live state at the snapshot

The last measured Grok writer session began at 2026-08-21T08:27:26Z. From the
current daemon restart at 08:37Z through the 09:19Z cycle, intake was
unauthorised and each cycle reported zero candidates, zero mints and zero
Graphiti completions. No new Grok writer session appeared in that interval.
This explains why the latest exported buckets are zero; it does not remove the
root cause when authorised candidates return.

## Recommended controls

1. Cap **provider attempts per cycle**, separately from successful stored
   outputs and separately for each provider.
2. Persist one receipt per writer attempt with provider, model, outcome, input,
   output, cached, reasoning and total tokens.
3. Prevent fallback after a cycle-level token or attempt budget is exhausted.
4. Run the CONT transformation through a minimal-context invocation path rather
   than a full coding-agent bootstrap.
5. Record Graphiti chat usage independently from embedding usage and retain
   failed dispatch receipts.
6. Add a rolling 300-second token ceiling and a daily hard ceiling that fail
   closed before another provider call.
7. Timestamp and structure provider errors so attempts can be joined to cycle,
   candidate and usage receipts.

## Conclusion

The principal root cause is repeated full-agent context bootstrap combined
with a success-counted loop. At the observed median, five ordinary Grok writer
sessions consume about 258,000 tokens. Retry, multi-call sessions, Cursor
fallback and Graphiti raise the real total further, while current accounting
records only the Grok portion exactly.

## Immediate Graphiti metering correction

Implemented on 2026-08-21 while leaving Graphiti enabled and keeping the CONT
writer paused:

- Cursor Graphiti chat now uses the CLI JSON result envelope and retains
  provider-reported input, output, cache-read and cache-write tokens for every
  invocation.
- Grok fallback now uses streaming JSON and retains the final
  `turn_completed.usage` fields, including reasoning and cache tokens.
- Existing OpenRouter embedding response metering is combined with chat usage
  in a durable `token_usage` object on every Graphiti attempt receipt.
- Unknown usage is labelled `UNREPORTED` or
  `PROVIDER_PARTIALLY_UNREPORTED`; it is never converted to a silent zero.
- A read-only operator command aggregates retained attempts into fixed
  300-second UTC windows:

```bash
.venv/bin/python scripts/hermes_control_plane.py usage \
  --unpublished data/newsroom/unpublished_store.sqlite3 \
  --usage-window 300
```

Historical Graphiti chat calls cannot be reconstructed because the previous
text-only CLI path discarded provider telemetry. The meter applies to newly
executed Graphiti attempts after the Control Plane reload.
