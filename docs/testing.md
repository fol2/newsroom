# Focused test behaviour

**Role:** Detailed agent and contributor guidance  
**Status:** Accepted  
**Owner:** Product owner  
**Canonical language:** English (UK)  
**Accepted:** 2026-08-27  
**Issue:** #799

`AGENTS.md` is the authority. This document explains how to collect enough evidence without turning every change into a repository-wide campaign.

## Default loop

1. State the changed behaviour and its failure modes.
2. Obtain the canonical Focus Gate manifest.
3. Run F0 once.
4. For executable work, run the manifest's F1/F2 selection once.
5. Add F3 or F4 only when the manifest or a concrete finding requires it.
6. Stop after one coherent evidence set and one feature-complete review.

```bash
python -m scripts.sdlc.focus_gate route \
  --base <base-sha> --head <head-sha> --output .focus/route.json
python -m scripts.sdlc.focus_gate verify --route .focus/route.json
uv sync --dev --locked                 # only when bootstrap_required is true
python -m scripts.sdlc.focus_gate execute \
  --route .focus/route.json --junit .focus/pytest.xml
```

The manifest is deterministic and content-addressed. It records the exact change, reasons, gates, tests, service/research/full-health decisions and expected bootstrap count.

## What each gate proves

**F0** proves exact change integrity. It performs `git diff --check`, validates the canonical manifest, compiles changed Python and parses changed JSON/TOML. Documentation-only work stops here and installs nothing.

**F1** proves the direct behaviour. A defect needs its exact reproduction plus the smallest positive, negative and boundary matrix. Passing a large unrelated suite cannot replace a missing regression.

**F2** proves the affected consumer or contract. The selector uses changed test files, explicit critical path rules, repository imports and package boundaries. Migrations add reopen/rollback coverage; authority changes add authority sentinels.

**F3** proves semantics that require an actual service. Neo4j is started only for a routed service change. A provider call is never implied by F3 and requires separate owner authority.

**F4** covers irreversible or externally visible effects. These controls remain separate, exact and fail-closed.

## Broadening and escalation

Broaden only because:

- a selected test fails and identifies another dependency;
- import or path analysis cannot resolve an executable change;
- a shared dependency or test harness changes;
- a state, service, security or release boundary is touched; or
- the owner explicitly requests a diagnostic full run.

An unknown executable path with no defensible focused selection escalates visibly to full health. It must not silently pass with zero tests.

## Research and full health

Graphiti research fixtures run in `.github/workflows/ci.yml` only when research inputs change, on schedule, or by manual dispatch. They are not product regressions and do not run on unrelated pull requests.

`.github/workflows/evidence.yml` retains the full deterministic inventory for schedule, manual diagnosis and merge queue health. It is intentionally absent from the ordinary pull-request event surface.

## Avoid waste

Do not:

- prepare the environment more than once for one exact change;
- run the same command against unchanged state;
- poll a remote workflow;
- repeat review without a material change or unresolved finding;
- run provider, Neo4j, research or full-health evidence for a route that did not select it;
- increase timeouts merely to preserve a non-diagnostic run; or
- create extra issues, branches, PRs or receipts merely to distribute work.

When touching tests, remove obvious duplicate setup, fixed sleeps and repeated I/O when the simplification is local and semantics-preserving. Do not weaken assertions, determinism or isolation.

## Handover

Report:

- **Manifest:** digest, gates and selected tests.
- **Run:** exact command, outcome and elapsed time.
- **Not run:** broader lanes intentionally omitted.
- **Review:** relevant findings and fixes.
- **Uncertainty:** what the focused evidence does not establish.
- **Remote state:** one observation only, when already available.

A pending independent workflow is evidence to report, not an instruction to wait or retry.
