# Residual review findings: editorial shadow governance

Source review run: `20260712-052507-ba9876df`

Review artifact: `/tmp/compound-engineering/ce-code-review/20260712-052507-ba9876df/review.json`

Branch reviewed: `jamesto/editorial-shadow-governance`

Base: `40d9de3c185f43f1e0841c175b84572f922b786c`

Review head: `44745df429673716d0466194f28330d1dbdc7dce`

The agent-mode review reported 15 actionable findings. Finding #13 was applied as the isolated review-fix commit `049a1a1`: a fresh-process capability test now scrubs Gateway and Discord credentials, denies and counts socket egress, and exercises both evaluation and eligible recording.

The remaining findings were not changed in the review-fix pass because they alter public contracts, editorial outcomes, security posture, concurrency semantics or architecture, or because their confidence and corroboration did not satisfy the LFG mechanical-apply bar. They are recorded as durable GitHub issues for explicit follow-up:

| Finding | Severity | Durable issue | Review-fix disposition |
|---|---|---|---|
| #1 Mutable package value can diverge from its digest | P1 | [Issue 61](https://github.com/fol2/newsroom/issues/61) | Package-authority behaviour change |
| #2 Publication content is not bound to decision identity | P1 | [Issue 62](https://github.com/fol2/newsroom/issues/62) | Publication identity contract change |
| #3 Normal record replay requires an undisclosed fencing token | P1 | [Issue 63](https://github.com/fol2/newsroom/issues/63) | CLI and persistence contract change |
| #4 Audit verification omits mutable control and delivery state | P1 | [Issue 64](https://github.com/fol2/newsroom/issues/64) | Integrity and security behaviour change |
| #5 Prohibited evidence can still become AUTO_PUBLISH | P1 | [Issue 65](https://github.com/fol2/newsroom/issues/65) | Editorial outcome change |
| #6 Reactivated unfinished intent can invoke the adapter twice | P1 | [Issue 66](https://github.com/fol2/newsroom/issues/66) | Concurrency behaviour change |
| #7 Active claim can be replaced before adapter entry | P1 | [Issue 67](https://github.com/fol2/newsroom/issues/67) | Lease and fencing semantics change |
| #8 GovernanceStore combines five responsibilities in one class | P1 | [Issue 68](https://github.com/fol2/newsroom/issues/68) | Substantial architecture refactor |
| #9 Durability tests never exercise process-crash recovery | P1 | [Issue 69](https://github.com/fol2/newsroom/issues/69) | Anchor 75 without cross-persona corroboration |
| #10 Delivery responses change shape across successful commands | P1 | [Issue 70](https://github.com/fol2/newsroom/issues/70) | Public CLI response contract change |
| #11 Unsupported network filesystems are not rejected | P1 | [Issue 71](https://github.com/fol2/newsroom/issues/71) | Filesystem admission and security posture change |
| #12 Intake errors disclose untrusted JSON values | P2 | [Issue 72](https://github.com/fol2/newsroom/issues/72) | Public error and disclosure contract change |
| #14 Repeated controls silently discard the operator reason | P2 | [Issue 73](https://github.com/fol2/newsroom/issues/73) | Audit event behaviour change |
| #15 Policy failures bypass the JSON CLI error contract | P2 | [Issue 74](https://github.com/fol2/newsroom/issues/74) | Anchor 75 without cross-persona corroboration and CLI contract change |

These issues are not duplicated in the pull-request body. The code-review artifact and each issue retain the evidence, suggested fix, confidence and reviewer attribution needed for follow-up.
