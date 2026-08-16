# Increment 9D2 sealed review, metrics and shadow decision

- **Issue:** [#497](https://github.com/fol2/newsroom/issues/497)
- **Status:** empty-universe blocked decision authority implemented
- **Dependencies:** #493, #495 and #496
- **Module:** `newsroom.increment9.decision`
- **Executable:** `scripts/increment9_shadow_decision.py`

## Sealed universe and stop inheritance

The exact 9B3 evidence stopped before first I/O and contains no Run/Attempt or
decision-bearing case. The exact 9C2 evidence retained all 26 comparator/fault
phases as not run under that higher-precedence stop. Therefore the only eligible
9D2 universe is the sealed empty universe. Retrospective cases, fixtures,
substitution, denominator repair and optimistic missing-evidence normalisation
remain prohibited.

The command reconstructs both canonical bundles and a current exact-main
#493/#495/#496 closure record. Any non-empty, executed, non-blocked or tampered
input is rejected by this blocked-decision path.

## Review and adjudication

No reviewer is invoked because there is no eligible case and no reviewer runtime
identity or protected-evidence authority. The exact OD-009 profiles remain
listed, but each is `NOT_EVALUATED` with `IDENTITY_UNRESOLVED` and
`MISSING_EVIDENCE`, zero invocations and zero labels. No same-family fallback,
adjudicator substitution, human label or deterministic fabrication occurs.

## Complete reporting

The decision retains complete, explicit inventories:

- all 12 pre-registered metrics, each denominator 0 and `NOT_EVALUATED`;
- all required jurisdiction, language, source-role, beat and case-kind slices,
  each count 0 and `NOT_EVALUATED`;
- every source, retrieval, GraphRAG, extraction, triage and operational ablation
  mode, each count 0 and `NOT_EVALUATED`;
- all 12 zero-tolerance classes with zero observed findings but
  `evidence_absent=true` and `NOT_EVALUATED`;
- capacity, cost, coverage, degradation, quality, recovery, rights, security and
  timeliness domains as `NOT_EVALUATED`;
- zero source/provider/model/embedding/reviewer usage, storage and spend; and
- the complete OD-013 production-equivalence statement with no claim permitted.

Zero observed findings are not reported as a zero-tolerance PASS. Missing
prospective evidence stays visible and blocks eligibility.

## Decision

The sole retained disposition is `BLOCKED_ACTIVE_COVERAGE`, with exact reasons:

- active coverage is zero;
- baseline stopped before first I/O;
- comparator/fault phases did not run;
- required exposure is unmet;
- reviewer identities are unresolved; and
- the review universe is empty.

Publication, Evidence Intake, canary, production mutation/activation,
Increment 10 and autonomous publication authority are all false. The decision
may feed only the final #498 closeout, which must retain this blocked result.

## Canonical evidence

`BlockedShadowDecision` is frozen and strict-canonical. Parsing reconstructs all
metric, slice, ablation and reviewer records and re-applies every invariant.
Duplicate keys, extra/missing fields, reordered inventories, invented values,
non-zero usage, eligibility claims or altered authority flags fail closed.

```bash
python scripts/increment9_shadow_decision.py build-blocked \
  --repo . \
  --campaign-bundle /protected/9b3/campaign-bundle.json \
  --fault-bundle /protected/9c2/fault-bundle.json \
  --dependency-evidence /protected/9d2/dependencies.json \
  --decision-id increment9-shadow-decision-001 \
  --decided-at 2026-08-16T00:00:00.000000Z \
  --output /protected/9d2/decision.json

python scripts/increment9_shadow_decision.py verify \
  --decision /protected/9d2/decision.json
```
