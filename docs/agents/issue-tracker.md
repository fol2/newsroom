# Issue tracker: GitHub

Issues and specifications for this repository live in GitHub Issues. Pull requests deliver accepted work; they are not the feature-request surface.

## Proportional delivery

One coherent problem uses one issue, one branch and one ordinary PR by default. Do not create child tickets merely to distribute machines, sub-agents, reviews, experiments or evidence types.

Create a separate issue only when at least one boundary is independently meaningful:

- merge or rollback;
- owner or team;
- dependency ordering;
- release or activation;
- independently testable user value; or
- research whose uncertainty must be resolved before implementation.

A sub-agent can answer an independent question inside the same issue and branch. Parallel execution is not an architecture.

## Operations

- Create: `gh issue create --title "..." --body "..."`
- Read: `gh issue view <number> --comments`
- Comment: `gh issue comment <number> --body "..."`
- Label: `gh issue edit <number> --add-label "..."`
- Claim: `gh issue edit <number> --add-assignee @me`
- Close: `gh issue close <number> --comment "..."`

Resolve a bare `#42` as an issue or PR before acting because GitHub shares one number space.

## Dependencies

Use GitHub native issue dependencies where available. A dependency is a real start/merge constraint, not a status note. Owner amendments can remove or reorder it explicitly.

Do not infer a blocker from related work, an open operational canary, a parent issue or a previous agent's narrative. Read back the current issue body, native dependencies, current `main` and open PR inventory before starting.

## Wayfinding

A map may hold decisions, fog and candidate work. Child tickets remain subject to the proportional delivery rule above. The frontier is the first unassigned child with no open native blocker. Do not decompose a coherent implementation merely because the map can contain more children.

## Completion truth

An implementation is complete only when GitHub readback proves the intended PR, merge commit and current-main files. A local branch, issue comment, stale PR number or claimed workflow result is not completion evidence.
