# Graphiti runtime calibration (#771)

## Verdict

The provider-free packet recommends **ADOPT** for the runtime policy. This is
not live execution authority: owner-gated packets remain unauthorised, public
effects are zero, and provider calls are zero.

The canonical measurement is
[`2026-08-25-graphiti-runtime-calibration-measurements.json`](2026-08-25-graphiti-runtime-calibration-measurements.json).
It binds the existing combined-temporal prompt/schema/context identities, the
three qualified Graphiti routes, the checked call-shape policy and the sibling
fallback/circuit policy.

## Result

- Every measured effective-revision cache miss uses one combined-temporal
  primary leaf. Ordinary timestamp, dedupe and summary leaves remain local
  where #748 qualified them.
- Only `MALFORMED_OUTPUT` is fallback-eligible. The fake malformed primary is
  linked to one distinct, pre-receipted fallback; unchanged redispatch and a
  second fallback are refused.
- The source-safe combined-temporal gold and #748 authority, rights, entity
  resolution, ambiguity and summary gold pass. `same-name` remains
  `AMBIGUOUS_HOLD`; the zero-proposal case remains
  `TERMINAL_SUCCESS_ZERO_PROPOSALS`.
- Average provider-token estimates at #737 effective-revision grain are lower
  for low, base and high scenarios than the retained current path. Estimates
  remain labelled as estimates; missing usage is not converted to zero.
- Failed or rolled-back attempt usage is reported separately from terminal
  success averages. Deterministic validation and local-work cost are also
  separate and are not labelled as provider tokens.

The policy opens only the affected Graphiti route after systemic transport,
usage or call-shape failure. Release evidence preference remains
`DETERMINISTIC_HEALTH_PROBE`, then `AUTHORISED_OPERATOR_RESET`, under #729.
A Graphiti route circuit does not rewrite or block the CONT writer circuit.

## Non-effects

No production state, graph, source expression, GING-010 policy, semantic reuse,
backlog ingest or publication state is changed. No per-ingest or daily token
quota is introduced.
