# Increment 8A corrective evaluation authority

Issue: #463  
Parent: #148  
Dependency: corrected 8R contract #462  
Accepted base: `main@f90604e27ad6a7a522bee452755c0c79662b6054`  
Accepted tree: `742772a16110aa508fc2ccf76d3a47a541a74e43`

## Change contract

The v30 tables remain additive and unchanged. This correction strengthens the
canonical records and their authority checks without collecting evaluation
results or granting qualification, shadow, provider, network, spend,
publication or production authority.

The protected invariants are:

1. an Evaluation Plan retains the exact authorised-human identity and role
   manifest, including at least two primary reviewers and one adjudicator;
2. Plan approval precedes Epoch freeze/open, which precedes Run start, Case
   cutoff, labels, adjudication and the release decision;
3. every qualification Case retains the frozen membership facts and the exact
   required-slice and Case-stratum memberships deterministically derived from
   the corrected 8R manifest;
4. each Run contains distinct input-manifest identities, so repeated copies of
   one event cannot satisfy the 120-Case exposure;
5. the authority accepts only transaction-free SQLite connections whose
   foreign-key enforcement is already active, and owns every write
   transaction without committing caller work;
6. each reviewable Case has at most one label per role, every identity is
   authorised for that human role, and every disagreement requires retained
   adjudication by an independent authorised adjudicator;
7. mandatory blocker, Urgent and zero-tolerance second reviews do not count
   towards the separate 20 per cent ordinary-Case sample;
8. a PASS candidate requires all nine exact slices, all three exposure strata,
   non-vacuous reviewed evidence and the frozen distinct-reviewer minimum;
9. the release decision embeds a canonical Metric Report, derives its gate
   values from that retained report, and binds the complete Case, label and
   adjudication evidence-manifest digest;
10. recording any release decision seals its Run against later Cases, labels
    and adjudications.

## Observable finish

- Direct regressions cover all eleven retained P1 bypasses from PR #470.
- The complete valid fixture exposure reaches the corrective readiness
  blockade; it does not persist PASS while later atoms remain incomplete.
- The full Increment 8 focused suite passes.
- One canonical PR closes #463 only. #464-#468, #428, Increment 9 and all live
  effects remain outside this change.
