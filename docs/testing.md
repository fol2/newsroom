# Agent test behaviour

**Role:** Agent test behaviour
**Status:** Accepted behavioural guidance; creates no machine gate
**Owner:** Product owner
**Canonical language:** English (UK)
**Accepted:** 2026-08-26

## Default loop

1. Identify the behaviour changed and select the smallest relevant test files
   or node IDs.
2. Run that focused selection once per unchanged code, configuration and
   environment state.
3. Broaden the selection only when a dependency or a concrete failure points to
   another affected surface.
4. Stop and report the command, outcome, elapsed time, omissions and remaining
   uncertainty.

```bash
uv run --no-sync python -m pytest -q \
  newsroom/tests/test_RELEVANT.py::test_relevant_behaviour
```

Prepare the locked environment after checkout or a dependency change, not
before every test command:

```bash
uv lock --check
uv sync --dev --locked
```

The purpose is to answer the immediate engineering question, not to accumulate
every possible receipt before an agent can hand work over.

## Leave touched tests slimmer and faster

The `ponytail` skill remains active for test work. When touching a test or
fixture, first look for a small, semantics-preserving improvement in that same
surface:

- delete only demonstrably redundant setup or cases while preserving coverage;
- reuse an existing helper instead of adding another fixture layer;
- shrink expensive fixture data and setup; reuse setup at a broader scope only
  when isolation remains intact;
- replace fixed sleeps with direct state or readiness checks;
- avoid repeated filesystem, database, subprocess or repository-wide setup;
- preserve assertions, determinism and isolation.

Prefer an obvious local simplification over a new runner, cache, abstraction or
performance framework. Use a focused `--durations` observation only when the
slow part is unclear; it is diagnostic evidence, not a new benchmark gate. If
there is no simple safe speed-up, leave the test unchanged and report that
rather than inventing infrastructure.

## Avoid token- and compute-burning loops

Agents do not do any of the following by default:

- launch the complete `newsroom/tests` suite;
- wait or repeatedly poll for a remote workflow;
- rerun the same command against unchanged code, configuration and environment;
- increase a timeout merely to keep a long run alive;
- repeat review cycles after the current findings have been addressed without
  a new question or new evidence;
- add or expand machine enforcement whose predicate is compliance with this
  behavioural guidance.

Only an explicit user request authorises a complete-suite run. State its
diagnostic question before starting. If any run stops being proportionate to
that question, terminate it and report the partial evidence. Separately
scheduled automation can continue independently; its pending or failed state is
reported rather than turned into an agent retry loop.

## Handover language

Report facts without converting them into implicit gates:

- **Run:** exact focused command and result.
- **Not run:** broader checks intentionally omitted.
- **Observed:** remote status if it was already readily available.
- **Uncertainty:** what the focused evidence does not establish.

Words such as *canonical*, *complete* or *required* in an automation contract do
not by themselves instruct an agent to wait for that automation. Merge,
deployment and activation decisions remain separate from an agent's focused
validation handover. The repository's current merge policy still determines
merge eligibility.

## Changing this behaviour

`AGENTS.md` is the authority for agent behaviour; this guide supplies test
detail. Other documents should link here rather than copy the policy. Never
introduce a machine gate as an implementation detail of behavioural guidance.
