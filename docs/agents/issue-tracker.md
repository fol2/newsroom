# Issue tracker: GitHub

Engineering plans, tickets, and PRDs for this repository live as GitHub issues. Use the `gh` CLI for issue operations and infer the repository from `git remote -v`.

## Conventions

- Create: `gh issue create --title "..." --body "..."`
- Read: `gh issue view <number> --comments`
- List: `gh issue list --state open --json number,title,body,labels,comments`
- Comment: `gh issue comment <number> --body "..."`
- Label: `gh issue edit <number> --add-label "..."` or `--remove-label "..."`
- Close: `gh issue close <number> --comment "..."`

When a skill says to publish work to the issue tracker, create a GitHub issue. When it says to fetch a ticket, read the issue and its comments.

## Pull requests as a triage surface

External pull requests are not a request surface and must not enter the issue-triage state machine. Existing maintainer and collaborator pull requests continue through the normal review workflow.

GitHub issues and pull requests share one number space. Resolve an ambiguous reference with `gh pr view <number>` and fall back to `gh issue view <number>`.

## Dependencies

Use GitHub sub-issues and native issue dependencies where available. Otherwise, record `Part of #<number>` and `Blocked by: #<number>` explicitly in issue bodies.

A ticket is ready only when all blocking issues are closed.
