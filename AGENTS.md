# Newsroom Agent Guide

## 0. Development workflow

When asked to create PRs (especially when using multiple sub-agents), prefer **real GitHub PRs** by default:

- Each sub-agent should work on its own branch (and worktree if helpful).
- Push the branch to the remote.
- Open a GitHub PR (e.g. via `gh pr create`) and share the PR link/number in the handoff.
- Merge via GitHub after review.

If GitHub access is unavailable (no remote, no auth, or network restrictions), fall back to local branches and clearly state that the workflow is local-only.

## 1. Operational Newsroom

The operational Newsroom is the **Hermes Control Plane**: a distinct daemon LaunchAgent with veto, ledger, broker, signed stop, Newsroom schedule and live dispatcher. `newsroom-hub` is private Control Plane UI, not the Control Plane. Canonical terms live in `CONTEXT.md`. Hard-to-reverse decisions live in `docs/adr/`.

This repository does not run OpenClaw cron planners, the OpenClaw runner, Discord publishing, Brave News, GDELT DOC 2.0, the broad media RSS pool, `news_pool.sqlite3` or per-link Gemini clustering. That stack is dead and must not be restarted. RSS/Atom remains a Source Definition transport. Git history is the archive. See [ADR 0009](docs/adr/0009-legacy-operational-newsroom-dead.md).

Increment 11B is a Hermes fresh start. This file grants no live source, credential, spend, publication or activation authority.

## 2. Agent documentation

- [Issue tracker](docs/agents/issue-tracker.md)
- [Triage labels](docs/agents/triage-labels.md)
- [Domain docs](docs/agents/domain.md)
- [Documentation map](docs/README.md)

## 3. Development

- Python 3.12+, deps in `pyproject.toml` (locked in `uv.lock`)
- Install (dev): `uv sync --dev`
- Default to the smallest focused test files or node IDs that exercise the
  changed behaviour. Broaden only when a dependency or a concrete failure
  identifies another affected surface. See [`docs/testing.md`](docs/testing.md).
- Do not autonomously start the complete test suite. Only an explicit user
  request authorises it; state the diagnostic question before starting.
- Do not wait or poll for remote workflows, or rerun the same check against
  unchanged code, configuration and environment. If a run stops being
  proportionate to its question, terminate it and report the partial evidence.
- Stop after collecting a coherent set of focused evidence and report what was
  run, what was not run, and any remaining uncertainty. Pending or failed
  automation is evidence to report, not a reason for an agent retry loop.
- Change agent behaviour through concise instructions and review feedback. Do
  not add or expand a machine gate whose predicate is compliance with this
  behavioural guidance. Existing product, security and repository-lifecycle
  controls are separate concerns.
- Existing CI and SDLC automation may report independently, but agents do not
  treat waiting for it as a prerequisite for a handover. Merge eligibility
  remains a separate observation of the repository's current merge policy.
- The `ponytail` skill stays active in full mode for every coding-related task,
  including design, implementation, refactoring, tests and review. Understand
  the real flow, then choose the first simple solution that works. Do not
  over-engineer.
- Keep a slim-and-trim ratchet on touched code: prefer deletion, reuse and the
  standard library; remove nearby duplication or obsolete scaffolding when it
  is safe, but do not expand into unrelated cleanup.
- When touching a test or fixture, look for a simple semantics-preserving way
  to make that focused path faster. Remove duplicate setup, sleeps and repeated
  I/O before adding runners, caches, abstractions or performance gates. Do not
  weaken assertions or isolation for speed.
- Repository documents and code use UK English
