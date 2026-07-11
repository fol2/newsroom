# Implementation plans

Plans describe how the repository will move from its current state towards one or more specifications. They are time-bound execution documents, not permanent product requirements.

## What belongs here

Examples include:

- milestones and work breakdown;
- dependency and sequencing decisions;
- migration and rollout steps;
- test, evaluation and validation work;
- release gates and rollback preparation;
- known delivery risks, blockers and ownership;
- temporary compatibility or transition arrangements.

Every plan should link to the specification or explicit owner decision that defines the intended outcome. A plan may propose that a spec be changed, but it does not change the spec by itself.

## Status values

- `Proposed` — being discussed and not yet approved for execution.
- `Active` — approved and currently being worked.
- `Blocked` — approved but unable to progress; state the blocker.
- `Completed` — finished and validated against the stated outcome.
- `Cancelled` — intentionally stopped; record why.

## Minimum document shape

```markdown
# <Plan title>

**Status:** Proposed | Active | Blocked | Completed | Cancelled  
**Owner:** <name or role>  
**Last updated:** YYYY-MM-DD  
**Target spec:** <one or more links>  
**Target branch or release:** <value or none>

## Intended outcome

## Current state

## Work items and milestones

## Validation

## Risks and blockers

## Decisions needed

## Completion record
```

## Writing rules

- Do not duplicate the full specification; link to it.
- Make milestones observable and validation explicit.
- Record assumptions that may invalidate the plan.
- Keep unresolved product decisions visible rather than making an implementation choice silently.
- Mark completed or cancelled plans instead of leaving stale plans looking active.
- When implementation reveals a requirement change, update or supersede the relevant spec through review rather than treating the plan as the new source of truth.